# Plain-list CLI — R5 over v0.7

## Command

```sh
python3 -B cli.py --org-list orgs.txt --output runs/result.jsonl --cache cache/run --timeout-seconds 2400
```

LIVE is the default: `agent.py --fresh --search none` under the existing `evaluator.collect` supervisor. R5 adds bounded free discovery and cited readable reports; the legacy terminal schema and refresh comparison remain. Python 3.11+ and the standard library are sufficient; no dependency installation is needed.

Options:

| Option | Meaning |
| --- | --- |
| `--org-list PATH` | UTF-8 file, one organisation number per physical line |
| `--orgs NUMBER ...` | Direct entries; mutually exclusive with the file |
| `--output PATH` | Required, new JSONL output |
| `--summary PATH` | New summary JSON; defaults to OUTPUT with suffix `.summary.json` |
| `--cache PATH` | Required retained response cache and immutable snapshots |
| `--timeout-seconds N` | Finite collection deadline, default 2400, maximum 2600 |
| `--workers N` | 1..8; default 4 |
| `--replay` | Cache-only, no HTTP; cache must already exist |
| `--fresh` | Explicit LIVE default; mutually exclusive with replay |
| `--previous PATH` | Previous v0.7 envelopes for the unchanged refresh comparison |
| `--registry-snapshot PATH` | Documented local frozen-registry JSONL interchange |
| `--search none` | Default: no provider calls or keys |
| `--search tavily-free` | Optional fixed-basic discovery after account/free-balance verification |
| `--search-credit-limit N` | Maximum reserved search attempts for the run, 1..1000 |
| `--search-free-credit-limit N` | Caller-confirmed free allowance, 0..1000; LIVE search requires nonzero allowance |
| `--search-strategy MODE` | legacy, name_focus, or adaptive (default) |
| `--report-dir PATH` | New review directory; default OUTPUT.review |

Registry snapshot mode disables live registry fallback, but still permits public website requests in LIVE mode. Add `--replay` for a fully offline run. Snapshot timestamps/hashes are retained. An unavailable source does not become a deletion, and refresh recovery uses the last supported observation. For repeated numbers in the previous file, the last envelope is selected, matching the underlying agent.

## Entry and artifact contract

The input limit is 4 MB and 1..10000 entries. Only LF and CRLF separate physical file lines. A trailing newline closes the final line and adds no phantom entry; a blank line is an invalid entry that receives output. UTF-8 BOM is accepted. VT/FF/NEL/Unicode separators stay inside the entry and cannot split JSONL records. Outer ASCII spaces and tabs are removed for checksum validation and retained in `raw_input`. Numbers must be nine ASCII digits with the Norwegian checksum.

Every accepted input entry receives one envelope, including duplicates and invalid entries. An unreadable, empty, oversized or invalid-UTF-8 file is a command error before output creation. Unexpected collector startup errors produce failed rows with conservative request upper bounds, not successful empty results. The supervisor preserves its matching complete prefix and synthesizes failures for the remainder after a deadline or malformed/incomplete collector output.

Distinct valid numbers are collected once per invocation. Duplicate entries reuse that observation and its evidence; `_cli.observation_reused` and `observation_input_index` identify this. Each repeated envelope's `operations` describes the shared observation: **do not sum those operations across duplicate output lines**. The summary counts requests once per distinct valid number and explicitly distinguishes observed counts from upper bounds. Invalid entries use zero requests.

The existing Fetcher limits each distinct company observation to 20 HTTP requests, including redirects, retries and robots checks. It checks a 90-second local time budget before requests, but DNS/lock waits can overrun it; the subprocess supervisor supplies the effective collection deadline. The collection supervisor has a finite overall wait and kills its process group on POSIX. The CLI adds no HTTP client or retry. It validates output order, shape and the request ceiling before publishing facts.

Outputs and summaries use exclusive creation and are never overwritten. Parent directories are created. Both final paths are reserved before collecting; a force-killed CLI or storage failure can leave an incomplete artifact, so only a completed summary and its `output_sha256` identify a completed CLI publication. Final-path symlinks are refused; operator-chosen parent directory symlinks follow normal filesystem behavior. The CLI is not a directory-confinement mechanism.

## Evidence state versus execution state

The six claim `availability` values are preserved:

| State | Interpretation |
| --- | --- |
| `available` | A value with evidence references was published by the v0.7 extractor |
| `not_available` | The field/source did not provide a value in the observed scope |
| `blocked` | Access or policy prevented observation |
| `not_applicable` | The collector explicitly marks the field inapplicable |
| `ambiguous` | Attribution or interpretation was not established |
| `failed` | Collection could not establish the value |

`run.terminal_status` is separately `completed` or `failed`. A completed run can have no available claims. `_cli.outcome` is a local execution summary: `completed_with_available_claims`, `completed_without_available_claims` or `failed`. It is not a seventh claim state or an accuracy score. Every envelope and the summary include counts for all six availability states, including zeros. Summary claim counts include duplicate output entries, and say so explicitly.

Exit 0 means all entries completed and each has at least one available claim. Exit 2 means the full JSONL includes a failed/invalid/no-available-claim entry, rejected envelope or supervisor failure. Exit 1 means a command/configuration/artifact error; exit 130 means cancellation. A cancellation during collection first asks the existing supervisor to kill the child and publishes explicit failures where possible. A completed summary does not prove source completeness, factual accuracy or organizer qualification.

## Local validation

```sh
python3 -B -m unittest discover -s tests -p 'test_cli.py' -v
```

Tests exercise synthetic replay/refresh, LIVE command construction with a mocked supervisor, six-state preservation, input line accounting, duplicate budgets, deadline-prefix propagation, invalid envelopes, exclusive artifacts and cancellation. No LIVE request is needed for these tests. Live smoke results and the tested installed Python version belong in the delivery evidence section of README after execution.

## R5 billing and cache scope

The evaluator supplies its permitted TAVILY_API_KEY through the server-side environment only. Flags do not verify billing. Confirm a sufficient free balance and PayGo/auto-upgrade off before LIVE search; reconcile all runs against the same monthly account. No paid fallback is activated. Unknown reported usage stops new searches. Duplicate observations are not double-counted in search summaries. Provider request costs remain null until reconciled against account evidence.

Readable reports preserve claim qualifiers and source references. The latest-response cache index is shared by URL; fixed-cache replay is idempotent, but preceding LIVE failed/blocked/ambiguous observations need not be reproduced byte-for-byte from that final index. Exact previous envelopes and immutable source snapshots are retained. See README and smoke-r5 for both the initial strict failure and the successful same-snapshot test.
