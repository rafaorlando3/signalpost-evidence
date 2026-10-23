# Signalpost Evidence v0.7

Python standard-library research for Norwegian companies. The delivery keeps the v0.7 collection and evidence rules, with reviewed reliability fixes for subprocess deadlines, terminal envelopes and validation. It does not include R3/R4 filters or strategies.

## Run a plain list LIVE

Python 3.11+ is supported. CPython 3.12.15 is pinned in `runtime.txt` and was measured in this delivery's clean Linux virtual environment. No pip packages, API key or model service are required.

Create a clean virtual environment (CPython 3.12.15 is the pinned runtime in `runtime.txt`; Python 3.11+ is supported). No pip install or third-party runtime packages are needed:

 ```sh
 python3 -m venv .venv
 . .venv/bin/activate
 ```

 Create a UTF-8 file with one organisation number per line, then run from this repository:

Example `orgs.txt` (the evaluator supplies its own dynamic list):

```text
810034882
920295738
```

```sh
python3 -B cli.py --org-list orgs.txt --output runs/result.jsonl --cache cache/run --timeout-seconds 2400
```

This command defaults to LIVE public registry APIs and permitted company pages, fresh retrieval, four workers and `--search none`. It writes one v0.7 JSON envelope per input line, in order, plus `runs/result.summary.json`. A compact copy of the summary goes to stderr. Output/cache directories are created when needed. Use new output and summary filenames for each run; existing files and final-path symlinks are refused.

Invalid numbers and blank lines receive explicit failed envelopes. Duplicates receive separate envelopes linked by `_cli.duplicate_of`; one observation per distinct valid number is reused within the command. The unchanged collector caps that observation at **20 HTTP requests**, including redirects, retries and robots requests, and a 90-second Fetcher budget checked before requests (DNS/lock waits can overrun that local budget). The supervisor caps collection at the supplied finite deadline (default 2400 seconds, maximum 2600). Interrupted rows retain failures and conservative request upper bounds. For 100 distinct valid numbers the request ceiling is 2000; that ceiling is not a performance or coverage result.

## Optional Docker run

 The Dockerfile keeps the pinned Python base image and uses the same CLI as its entrypoint. The lower-level evaluator remains installed and can be selected with an explicit entrypoint.

 ```sh
 docker build -t signalpost:v0.7 .
 docker run --rm -v "$PWD:/work" signalpost:v0.7 --org-list /work/orgs.txt --output /work/runs/result.jsonl --cache /work/cache/run --timeout-seconds 2400
 ```

 The mounted directory retains outputs and source snapshots after the container exits. No pip install or API key is needed.

 ## Read the result

Each claim preserves its `availability`: `available`, `not_available`, `blocked`, `not_applicable`, `ambiguous` or `failed`. `run.terminal_status=completed` only means collection finished; it can coexist with failed or unavailable claims. `_cli.claim_status_counts` and the summary show all six states separately. These states are the v0.7 evidence contract, not a claim of compatibility with an unpublished organizer adapter.

An `available` claim has a value and evidence references. Missing data is not zero. Source errors are not deletions. Registry identity uses the exact organisation number; websites require the existing v0.7 identity checks. Contact links do not prove responsiveness or social-account ownership. Source URLs, dates, periods, hashes, pointers and retained snapshot references remain in the envelope.

The exit codes are 0 when every entry finishes with at least one available claim, 2 when complete output includes an invalid/failed/no-available-claim entry or a collector guard failure, 1 for input/output/configuration errors, and 130 for cancellation. Exit 0 does not mean every requested field is available or independently correct. See [CLI.md](CLI.md) for parsing, duplicate accounting and refresh details.

## Replay and refresh

Keep outputs and the complete cache, including immutable `snapshots/`. To replay without HTTP:

```sh
python3 -B cli.py --org-list orgs.txt --output runs/replay.jsonl --cache cache/run --replay --previous runs/result.jsonl
```

Replay requires an existing cache; cache misses remain explicit unknown/failure states. Fresh collection is the default; add `--previous runs/result.jsonl` to compare with retained supported observations. Repeated unchanged observations have no material changes. Recovery compares against the last supported value through history, preserving original evidence.

`--registry-snapshot FILE.jsonl` uses the documented [frozen registry interchange](FROZEN-REGISTRY.md), with preserved source timestamps and no live registry fallback. Company pages can still be fetched unless `--replay` is also supplied. The organizer's snapshot schema is not claimed compatible without confirmation.

## Validation and public smoke

```sh
python3 -B -m unittest discover -s tests -p 'test_cli.py' -v
python3 -B -m unittest discover -s tests -q
```

The CLI tests use synthetic fixtures and mocks; they do not establish live source coverage. 112 offline regression tests passed on the same isolated CPython 3.12.15 runtime. The measured code is commit `2b7aaf6260b90a8e78356c4d623f36b93281f772`; this delivery adds reports and aligns runtime/packaging documentation without changing those Python sources.

| Check | Terminal results | Collection time | Requests | New paid API cost |
| --- | ---: | ---: | ---: | ---: |
| Fresh clone, empty venv/cache, 5 unseen companies | 5/5; 0 execution failures | 19.650 s | 41 | US$0 |
| Separate fresh clone/venv/cache, 100 unseen companies | 100/100; 0 execution failures | 111.424 s | 535 | US$0 |
| Offline replay/refresh of those 100 | 100/100; 0 material changes | 6.479 s | 0 | US$0 |

The 100-company smoke includes 1497 `available`, 671 `not_available`, 90 `ambiguous`, 36 `blocked` and 6 `failed` claims. Completion does not mean complete or independently verified facts. The offline replay preserved identical claims, evidence IDs/content hashes and complete previous envelopes. One ambiguous/null website observation changed retrieval/path metadata; the envelopes are not byte-identical. See the report for this limitation.

Public reports: [100-company smoke](smoke/smoke100-report.json), [5-company cold run](smoke/cold5-report.json), and [inputs/reproduction notes](smoke/README.md). Inputs were frozen before execution from the verified official universe, excluding 1700 previously used organisation numbers. No private cache or downloaded source body is required to start the LIVE command. The optional Docker recipe pins the upstream Python 3.12.15 image; the validation above used a fresh virtual environment in the already available isolation runtime, not a newly built Docker image.

To run the included smoke input with the same LIVE entrypoint:

```sh
python3 -B cli.py --org-list smoke/orgs-smoke100.txt --output runs/smoke100.jsonl --cache cache/smoke100 --timeout-seconds 2400
```

The older measured experiments remain documented in `RESULTS-v07.md`; they are separate from this delivery's smoke. There is no official score or qualification claim.

## Retention and rights

Raw run outputs and source-body caches remain runtime artifacts outside this delivery. The public `smoke/` directory contains only organisation-number inputs and run reports. Historical development profiles in the original v0.7 artifact remain separate and are not read by the LIVE CLI. Do not commit caches, credentials, private inputs or complete downloaded HTML. Keep the cache locally if a source audit must be reproducible. Roles responses redact birth identifiers in retained bodies; original and retained hashes can differ and remain identified.

The lower-level `agent.py` and `evaluator.py` JSONL interfaces remain available. This plain-list CLI exposes only free public collection with search disabled; no paid search is activated. Code is MIT; third-party content retains its own rights. See [SOURCES.md](SOURCES.md).
