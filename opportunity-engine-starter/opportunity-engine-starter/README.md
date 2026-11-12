# Autonomous Opportunity Engine

A cloud-first system that discovers real, potentially paid work, evaluates whether it can be delivered by software agents, and records evidence for a human go/no-go decision.

## Current stage: Demand Scanner v0.1

The first stage:
1. Searches public pages for specific paid project requests and bounty opportunities.
2. Normalizes and deduplicates result URLs.
3. Scores results using transparent rules: payment evidence, execution fit, source quality, scope clarity, and risk signals.
4. Publishes a ranked report and machine-readable ledger.

It does not contact clients, submit bids, accept contracts, access private accounts, or move money. A promising score means "worth investigating", not "guaranteed paid work".

## Run it in the cloud

The GitHub Actions workflow named **Opportunity Scanner** runs once each day and can be started manually:

1. Open the repository's **Actions** tab.
2. Select **Opportunity Scanner**.
3. Select **Run workflow**.

No local computer or local server is required.

Firecrawl's Search endpoint can be tried without an API key, with an API key available for higher rate limits. Add a repository Actions secret named `FIRECRAWL_API_KEY` later if needed. Never commit API keys, cookies, passwords, or customer credentials.

## Outputs

- `data/opportunities.json` — deduplicated opportunity ledger.
- `docs/latest-opportunities.md` — latest ranked scan report.

The repository is public, so the ledger is limited to public page titles, URLs, snippets, timestamps, and scores. Do not add private customer information or personal contact details.

## Scoring interpretation

- **Promising** — payment evidence and a matching automatable task type were found, with no obvious blocking risk. It still needs human verification.
- **Review** — a possible match exists, but payment, scope, source reliability, or risk needs checking.
- **Hold** — a risk signal requires human review before any further action.
- **Low signal** — insufficient evidence to justify work.

Scores are ranking aids, not estimates of the probability of getting paid.

## Design rules

- Prefer primary listings and direct bounty pages over copied job aggregators.
- Keep the source URL and the exact text that supported each assessment.
- Do not infer a budget, deadline, customer identity, or payment status when the page does not state it.
- Never bypass logins, paywalls, CAPTCHAs, access controls, or robots restrictions.
- Do not automatically apply, message, purchase, sign contracts, or spend money.
- Keep discovery, execution, verification, and payment as separate stages.
- Track false positives and false negatives so scoring can improve from evidence.

## Roadmap

- [x] Create a cloud-hosted repository.
- [x] Add the first discovery and scoring engine.
- [ ] Configure and verify the cloud scan.
- [ ] Add deeper page verification for high-scoring candidates.
- [ ] Add an opportunity review queue and decision history.
- [ ] Add specialized execution workers with strict permissions.
- [ ] Add independent QA and delivery evidence.
- [ ] Add customer approval, invoicing, and payment tracking.
- [ ] Add safe autonomy controls, budgets, and rollback paths.
