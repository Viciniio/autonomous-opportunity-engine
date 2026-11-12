#!/usr/bin/env python3
"""Discover and rank public, potentially paid work. No outreach or transactions."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "data" / "opportunities.json"
REPORT = ROOT / "docs" / "latest-opportunities.md"
SEARCH_URL = "https://api.firecrawl.dev/v2/search"

QUERIES = [
    ("upwork", 'site:upwork.com/freelance-jobs/ (automation OR "web scraping" OR "data extraction" OR "lead generation" OR "API integration") (budget OR hourly OR "fixed price")'),
    ("freelancer", 'site:freelancer.com/projects/ ("web scraping" OR automation OR "data research" OR "lead generation" OR "data extraction") (budget OR "fixed price" OR bids)'),
    ("forhire", 'site:reddit.com/r/forhire/ "[Hiring]" (automation OR scraping OR research OR spreadsheet OR website OR Python)'),
    ("bounties", '(site:algora.io/bounties OR site:github.com) (bounty OR reward) (bug OR feature OR integration) paid'),
]

FIT_GROUPS = {
    "web_data": [r"web scraping", r"scrap(?:e|er|ing)", r"data extraction", r"extract data", r"crawl(?:ing)?", r"data collection"],
    "research": [r"web research", r"online research", r"market research", r"data research", r"competitor research"],
    "lead_generation": [r"lead generation", r"lead list", r"prospect list", r"list building", r"data enrichment"],
    "automation": [r"automation", r"workflow", r"zapier", r"make\.com", r"\bn8n\b", r"google sheets", r"spreadsheet automation"],
    "software": [r"api integration", r"api development", r"python script", r"bug fix", r"website fix", r"website development", r"landing page", r"web app", r"software integration"],
    "operations": [r"data entry", r"product listing", r"catalog upload", r"document formatting", r"pdf conversion", r"quality assurance", r"\bqa testing\b"],
}
PAYMENT_PATTERNS = [
    r"\$\s?\d", r"\b(?:usd|eur|gbp|cad|aud)\s?\d", r"\d[\d,]*(?:\.\d+)?\s?(?:usd|eur|gbp|cad|aud)\b",
    r"\bbudget\b", r"\bfixed[- ]price\b", r"\bhourly rate\b", r"\bper hour\b", r"\bpaid\b", r"\bpayment\b",
    r"\bcompensation\b", r"\bbounty\b", r"\breward\b", r"\bprize pool\b", r"\bcontract\b",
]
RISK_PATTERNS = {
    "personal_data_or_contact_harvesting": [r"scrape (?:personal|private) data", r"harvest emails", r"collect phone numbers", r"sell.*personal data"],
    "credential_or_access_abuse": [r"steal passwords", r"credential theft", r"bypass login", r"account takeover", r"session hijack"],
    "evasion_or_spam": [r"captcha bypass", r"bypass paywall", r"mass dm", r"bulk spam", r"fake reviews", r"bot accounts"],
    "high_stakes_advice": [r"medical diagnosis", r"legal advice", r"investment advice", r"financial advice"],
    "regulated_or_speculative": [r"casino", r"gambling", r"crypto trading", r"wallet recovery", r"adult content"],
}
EMPLOYMENT_PATTERNS = [r"\bfull[- ]time\b", r"\bpart[- ]time employee\b", r"\bpermanent position\b", r"\bsalary\b", r"\binternship\b", r"\bemployment\b"]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            return ""
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in {"ref", "source", "campaign", "fbclid", "gclid"}]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", urlencode(query), ""))
    except ValueError:
        return ""


def domain_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def firecrawl_search(query: str, limit: int = 10) -> list[dict]:
    payload = {"query": query, "limit": limit, "sources": [{"type": "web"}], "highlights": True, "safe": True, "tbs": "qdr:m"}
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("FIRECRAWL_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = Request(SEARCH_URL, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    for attempt in range(3):
        try:
            with urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
            if not body.get("success", True):
                raise RuntimeError(str(body.get("error", "Firecrawl search failed")))
            data = body.get("data", {})
            if isinstance(data, list):
                return data
            return data.get("web", []) if isinstance(data, dict) else []
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Firecrawl HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Firecrawl connection failed: {exc}") from exc
    return []


def evaluate(title: str, description: str, url: str) -> dict:
    text = (title + " " + description).lower()
    fits = [name for name, patterns in FIT_GROUPS.items() if any(re.search(pattern, text, re.I) for pattern in patterns)]
    payment = [pattern for pattern in PAYMENT_PATTERNS if re.search(pattern, text, re.I)]
    risks = [name for name, patterns in RISK_PATTERNS.items() if any(re.search(pattern, text, re.I) for pattern in patterns)]
    employment = any(re.search(pattern, text, re.I) for pattern in EMPLOYMENT_PATTERNS)

    fit_points = min(40, len(fits) * 10)
    explicit_money = any(re.search(pattern, text, re.I) for pattern in (r"\$\s?\d", r"\b(?:usd|eur|gbp)\s?\d", r"\d+\s?(?:usd|eur|gbp)\b", r"\bbounty\b", r"\bprize pool\b"))
    payment_points = 25 if explicit_money else (16 if payment else 0)
    domain = domain_of(url)
    trusted_marketplace = any(domain == d or domain.endswith("." + d) for d in ("upwork.com", "freelancer.com", "contra.com", "algora.io"))
    source_points = 10 if trusted_marketplace else (5 if domain == "reddit.com" else 0)
    clarity_points = 10 if len(description) >= 240 else (6 if len(description) >= 100 else 2)
    employment_penalty = 15 if employment else 0
    risk_penalty = 30 if risks else 0
    score = max(0, min(100, fit_points + payment_points + source_points + clarity_points - employment_penalty - risk_penalty))

    if risks:
        classification = "hold"
    elif employment:
        classification = "review"
    elif payment and fits and score >= 55:
        classification = "promising"
    elif payment or fits:
        classification = "review"
    else:
        classification = "low_signal"

    return {
        "score": score,
        "classification": classification,
        "fit_signals": fits,
        "payment_evidence": payment[:8],
        "risk_flags": risks,
        "employment_posting_signal": employment,
        "score_components": {
            "execution_fit": fit_points,
            "payment_evidence": payment_points,
            "source_quality": source_points,
            "scope_clarity": clarity_points,
            "employment_penalty": employment_penalty,
            "risk_penalty": risk_penalty,
        },
    }


def load_ledger() -> dict:
    if not LEDGER.exists():
        return {"version": 1, "updated_at": None, "opportunities": []}
    try:
        loaded = json.loads(LEDGER.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            return {"version": 1, "updated_at": None, "opportunities": loaded}
        return loaded if isinstance(loaded, dict) else {"version": 1, "updated_at": None, "opportunities": []}
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "updated_at": None, "opportunities": []}


def save_outputs(ledger: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated_at"] = now_iso()
    temporary = LEDGER.with_suffix(".tmp")
    temporary.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(LEDGER)

    records = sorted(ledger["opportunities"], key=lambda item: (item.get("score", 0), item.get("last_seen_at", "")), reverse=True)
    counts = {key: sum(1 for item in records if item.get("classification") == key) for key in ("promising", "review", "hold", "low_signal")}
    lines = [
        "# Latest Opportunity Scan", "",
        f"Updated: {ledger['updated_at']} (UTC)", "",
        f"Ledger size: **{len(records)}** · Promising: **{counts['promising']}** · Review: **{counts['review']}** · Hold: **{counts['hold']}** · Low signal: **{counts['low_signal']}**",
        "",
        "> A promising score is a research priority, not proof of a live budget or a guarantee of payment. Verify the source before taking any action.", "",
    ]
    shown = 0
    for item in records:
        if item.get("classification") == "low_signal":
            continue
        shown += 1
        if shown > 30:
            break
        lines.extend([
            f"## [{item.get('score', 0)}/100 · {item.get('classification', 'review').upper()}] {item.get('title', 'Untitled')}", "",
            f"- Source: [{item.get('domain', 'unknown')}]({item.get('url', '')})",
            f"- First seen: {item.get('first_seen_at', 'unknown')} · Last seen: {item.get('last_seen_at', 'unknown')} · Seen: {item.get('times_seen', 1)} time(s)",
            f"- Fit signals: {', '.join(item.get('fit_signals', [])) or 'none detected'}",
            f"- Payment signals: {', '.join(item.get('payment_evidence', [])) or 'not found in snippet'}",
            f"- Risk flags: {', '.join(item.get('risk_flags', [])) or 'none detected'}", "",
            (item.get("description", "")[:700].replace("\n", " ").strip() or "No search excerpt was supplied."), "",
        ])
    if shown == 0:
        lines.extend(["No candidate opportunities were found in the latest scans.", ""])
    lines.extend(["---", "", "This report is generated from public search results. Re-open and independently verify each listing before treating it as actionable.", ""])
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run() -> int:
    ledger = load_ledger()
    by_url = {item.get("url"): item for item in ledger.get("opportunities", []) if item.get("url")}
    run_at = now_iso()
    searches_ok = 0
    searches_failed = []
    raw_results = 0

    for query_id, query in QUERIES:
        try:
            results = firecrawl_search(query, limit=10)
            searches_ok += 1
            raw_results += len(results)
            for result in results:
                url = canonical_url(str(result.get("url", "")))
                title = str(result.get("title", "")).strip()[:300]
                description = str(result.get("description", result.get("snippet", ""))).strip()[:1800]
                if not url or not title:
                    continue
                if url in by_url:
                    record = by_url[url]
                    record["last_seen_at"] = run_at
                    record["times_seen"] = int(record.get("times_seen", 1)) + 1
                    found_queries = set(record.get("search_queries", []))
                    found_queries.add(query_id)
                    record["search_queries"] = sorted(found_queries)
                    if len(description) > len(record.get("description", "")):
                        record["description"] = description
                    record.update(evaluate(title, record.get("description", description), url))
                else:
                    record = {
                        "id": hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
                        "title": title,
                        "url": url,
                        "domain": domain_of(url),
                        "description": description,
                        "first_seen_at": run_at,
                        "last_seen_at": run_at,
                        "times_seen": 1,
                        "search_queries": [query_id],
                        "source": "firecrawl_web",
                        **evaluate(title, description, url),
                    }
                    by_url[url] = record
            time.sleep(1)
        except Exception as exc:  # Record per-query errors and continue other sources.
            searches_failed.append({"query_id": query_id, "error": str(exc)[:500]})

    records = sorted(by_url.values(), key=lambda item: (item.get("score", 0), item.get("last_seen_at", "")), reverse=True)
    ledger["opportunities"] = records[:1000]
    save_outputs(ledger)
    summary = {
        "run_at": run_at,
        "searches_succeeded": searches_ok,
        "searches_failed": searches_failed,
        "raw_results": raw_results,
        "unique_opportunities": len(records),
        "promising": sum(1 for item in records if item.get("classification") == "promising"),
        "review": sum(1 for item in records if item.get("classification") == "review"),
        "hold": sum(1 for item in records if item.get("classification") == "hold"),
        "report": "docs/latest-opportunities.md",
        "ledger": "data/opportunities.json",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if searches_ok == 0 else 0


def self_test() -> int:
    paid = evaluate(
        "Python web scraping and market research automation project - $300 fixed price",
        "Need a scraper and an automated spreadsheet workflow to collect public product prices from public pages, compare competitors, and deliver a clean Google Sheets report. The project has a fixed budget of $300 and a clear deliverable.",
        "https://www.upwork.com/freelance-jobs/apply/example",
    )
    irrelevant = evaluate("A short article about migratory birds", "An editorial about seasonal bird migration and coastal habitats.", "https://example.com/article")
    risky = evaluate("Scrape personal data and harvest emails", "Need to harvest private emails and bypass login controls.", "https://example.com/task")
    assert paid["classification"] == "promising", paid
    assert irrelevant["classification"] == "low_signal", irrelevant
    assert risky["classification"] == "hold", risky
    print("Self-test passed: paid fit, low-signal, and risk-hold cases.")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else run())
