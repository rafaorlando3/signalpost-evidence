# Source register and attribution

Observed 26 September 2026. This project does not incorporate the challenge starter's implementation.

| Source | Purpose | Access and retention |
| --- | --- | --- |
| [Brønnøysund datasets](https://www.brreg.no/en/use-of-data-from-the-bronnoysund-register-centre/datasets-and-api/) | Identity, roles, workplaces | Public documented API; official page provides Norwegian Licence for Open Government Data (NLOD) information. Retain retrieval date and source; no endorsement implied. |
| [Entity API documentation](https://data.brreg.no/enhetsregisteret/api/dokumentasjon/en/index.html) | Legal names, organisation numbers, employee counts, addresses, roles | Query only requested organisations and their registered units. Birth dates and personal identity numbers removed from retained roles responses. |
| [Annual accounts API](https://github.com/brreg/regnskapsregister-api) | Latest filed company accounts and available history | Match exact organisation; exclude consolidated accounts; preserve period and currency; absence is null. |
| Company websites linked by registry records | Description, legal identity, literal contact and social links, structured jobs/news | Read robots.txt first. Respect denial and fail closed if unavailable. No authentication, paywall or CAPTCHA bypass. Keep local evidence; do not redistribute full pages as if MIT-licensed. |
| [Signalpost challenge](https://builderr.ai/challenges/signalpost) | Brief, sample universe, rubric | Benchmark rules and input manifest, not ground-truth accuracy labels. |

## Manifest provenance

Public universe archive: `https://builderr.ai/signalpost-company-universe-2025.jsonl.gz`.

Archive SHA-256: `1c89710e5b01f8617e86d09fbdff4a52f2f8dbbba297e74f7164b5984f5a0384`.

411,160 rows; deterministic selection of 1,000 without replacement with Python `random.Random(20260926).sample(rows, 1000)`. The first 10 and first 100 form the initial smaller samples. The selection was made before the coverage results; companies were not selected for easy website matches. Final `manifest.txt` lists the exact numbers.

## Outbound policy

Only HTTP/HTTPS, ports 80/443, no URL credentials. DNS answers must all be public IPs; the validated address is pinned while original-host TLS verification remains enabled. Redirects share the request budget; cross-host website redirects recheck robots. Maximum response size 2 MB. TLS errors and source failures remain visible, with no insecure fallback. No personal banking, account or document data from this workspace is used.

## Remaining limits

robots.txt is not a complete legal-rights assessment. Public-fact extraction is limited, but bulk redistribution of downloaded HTML has not been approved. Source caches are local and excluded from the release archive. The archive contains extracted profiles and source references; live execution rebuilds source caches. The organizer must confirm how its frozen snapshot maps to the documented adapter; compatibility is not asserted before that check.

## Optional discovery and separate experiments (26 September)

Tavily basic search is an optional candidate-URL source: https://docs.tavily.com/documentation/api-reference/endpoint/search . Account free plan shows 1,000 monthly credits and pay-as-you-go disabled. It was created with the holder's explicit authorization, without a card or marketing opt-in. API credentials are passed in process memory, not included in source, reports or archives. Terms: https://www.tavily.com/terms ; pricing: https://docs.tavily.com/documentation/api-credits .

Search output is used for discovery only. Company facts come from independently fetched original pages. Candidate URLs nominate domain roots. The adaptive query may additionally retain at most two shallow same-host legal/contact hints; customer, case-study, partner and portfolio paths cannot seed identity evidence. Search snippets only rank candidates and are discarded. Every asserted website still passes the original-page identity check. Directory/social candidates are excluded. Output caches are local; no raw search snippets/answers are published. Do not share API credentials with evaluators; evaluator credentials/access arrangements remain to be resolved.

NAV jobs API experiment: https://navikt.github.io/pam-stilling-feed/ and https://arbeidsplassen.nav.no/vilkar-api . Examined 3,000 recent feed entries with four requests and no exact target organisation matches. This does not establish absence of hiring. Not integrated into profile coverage. Public experimental token, contact details and full descriptions were not retained.

The additional holdout contains 100 organisations drawn with seed 2026092603 from universe entries outside the original 1,000. It was frozen before the version comparison. Subsequent search experiments use it for development; any future unbiased final estimate needs another untouched holdout.

Version 0.7 validation selects 100 additional organisation numbers before collection, excluding the prior 1,400 numbers. It is organisation-disjoint, not guaranteed domain-disjoint. The code was frozen before seeing these outcomes; only its release version label changed afterward. Literal contact channels are read from mailto/tel links on identity-checked pages, with source URL and original href. They are not inferred email addresses or tested contact endpoints.
