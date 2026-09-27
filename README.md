# Signalpost Evidence

Original Norwegian company research agent, using Python's standard library. It accepts company numbers, collects legal/financial records and evidence from identity-checked websites, records missing information, and compares successive observations.

## Install and run

Python 3.11+, tested on pinned Python 3.14.7, macOS and Linux aarch64. No pip dependencies. Optional Dockerfile pins the official Python image. From the repository root:

```sh
python3 evaluator.py --timeout-seconds 2400 -- --input INPUT.jsonl --output runs/evaluation.jsonl --cache cache/evaluation --fresh --workers 4
```

Input is one JSON object per line: `{"organisation_number":"810034882"}`. Every input receives one terminal envelope, in order. For a repeated observation add `--previous runs/previous.jsonl`; retain previous outputs and snapshots. Maximum 20 HTTP requests per company, including retries and redirects; 100 inputs therefore stay within 2,000 requests. Default wall-clock deadline is 2,400 seconds. A timeout is an explicit failed run, not a successful empty result.

Default mode uses live official APIs and permitted company pages, with no API key, model inference or paid API. `--registry-snapshot FILE.jsonl` instead uses the documented frozen interchange format with preserved source timestamps and no live fallback. **The organizer's actual snapshot schema has not yet been provided; this adapter is not claimed to be compatible until that interface is confirmed.** See FROZEN-REGISTRY.md.

## Artifacts and tests

`profiles-1000.jsonl`, `input-1000.jsonl` and `manifest.txt` identify the same 1,000 eligible companies. Open `review.html` locally for search, comparison and evidence inspection. `RESULTS-v07.md` documents measured gains, failed experiments and remaining limits. There is no official score or qualification claim.

```sh
python3 -m unittest discover -s tests -q
python3 validate.py input-1000.jsonl profiles-1000.jsonl
```

Source-body caches are intentionally excluded from this distribution. Public profiles contain source URLs, retrieval dates, reporting periods, hashes and selected literal evidence. A fresh run retains its own immutable snapshots under the supplied cache path. The source audit requires those retained files; it cannot be rerun against an omitted cache. No private personal documents or credentials are included.

## Optional search

Tavily candidate discovery is off by default. To enable it, supply `TAVILY_API_KEY` in the server environment and add `--search tavily --search-strategy adaptive --search-credit-limit 200`. This preferred optional mode can use up to two basic queries per company. Legacy remains available for comparison. Results only nominate domains; snippets are never claim evidence. Provider queries count toward the same HTTP limit.

The evaluator must supply its own authorized provider key if it elects to use this optional mode. No personal account key is shared, and default execution does not need one. At the published $0.008/credit rate, 200 basic queries imply at most $1.60 nominal provider charges per 100 companies. This is an evaluator planning estimate. Credit limits do not prove remaining free account allowance. Paid usage is not authorized by this repository. See cost-reconciliation.json for the developer's observed free tests, which exclude compute, electricity and development/model costs.

## Attribution and refresh

Registry identity is matched by exact organisation number. Company websites require an explicit matching number without conflict, or the declared registry domain/observed redirect plus exact name and address. Group, parent and customer pages are not merged into the entity. Contact and social fields are literal links declared on checked company pages; account ownership and contact responsiveness are not independently tested. Dates and financial currencies are explicit. Missing data never becomes zero. Source failure is not a deletion, and recovery compares against the last supported observation.

Code: MIT. Third-party content remains governed by its own source rights; see SOURCES.md. No competitor code, private user records, credentials or full downloaded HTML are distributed.
