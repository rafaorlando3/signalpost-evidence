# Signalpost Evidence v0.7

Python standard-library research for Norwegian companies. The delivery keeps the v0.7 collection and evidence rules, with reviewed reliability fixes for subprocess deadlines, terminal envelopes and validation. It does not include R3/R4 filters or strategies.

## Run a plain list LIVE

Python 3.11+ is required. The delivery server has Python 3.12.3; validation results are recorded below once run. No pip packages, API key or model service are required.

Create a clean virtual environment (CPython 3.14.7 is the pinned runtime in `runtime.txt`; Python 3.11+ is supported). No pip install or third-party runtime packages are needed:

 ```sh
 python3 -m venv .venv
 . .venv/bin/activate
 ```

 Create a UTF-8 file with one organisation number per line, then run from this repository:

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

The CLI tests use synthetic fixtures and mocks; they do not establish live source coverage. Public LIVE smoke evidence, the exact tested Python version, counts and limitations will be added here after the delivery run. No new LIVE result is claimed by this text.

The older measured experiments remain documented in `RESULTS-v07.md`; they are separate from this delivery's smoke. There is no official score or qualification claim.

## Retention and rights

Generated outputs and source-body caches are runtime artifacts, excluded from the code delivery. Do not commit caches, credentials, private inputs or complete downloaded HTML. Keep the cache locally if a source audit must be reproducible. Roles responses redact birth identifiers in retained bodies; original and retained hashes can differ and remain identified.

The lower-level `agent.py` and `evaluator.py` JSONL interfaces remain available. This plain-list CLI exposes only free public collection with search disabled; no paid search is activated. Code is MIT; third-party content retains its own rights. See [SOURCES.md](SOURCES.md).
