# Public v0.7 smoke evidence

`orgs-smoke100.txt` contains the 100 independent LIVE smoke inputs; `smoke100-report.json` records all 100 terminal outcomes and per-company states/errors, input/output hashes, requests, runtime and offline refresh checks. `orgs-cold5.txt` and `cold5-report.json` describe the separate 5-company fresh-clone check. The two lists were frozen before collection and are disjoint from 1700 earlier company inputs.

From a clean clone with CPython 3.12.15, create and activate an empty virtual environment using the main README. No pip package is required. Then run:

```sh
python3 -B cli.py --org-list smoke/orgs-smoke100.txt --output runs/smoke100.jsonl --cache cache/smoke100 --timeout-seconds 2400
```

The command above is the same dynamic-file interface as the evaluator command. Use a new output filename each time. The fresh source cache is populated by public requests; no search-provider key, private snapshot, source-body cache or precomputed profile is needed. Preserve the generated cache locally for source-body audits; these reports do not redistribute downloaded bodies.

Results are operational smoke evidence, not official ranking, precision or recall. Unavailable/ambiguous/blocked/failed fields remain explicit. The 100-company run had 6 failed claims but zero failed executions. Replay is semantically idempotent for claims/material changes; one ambiguous observation has different retrieval/path metadata, as recorded in the report.
