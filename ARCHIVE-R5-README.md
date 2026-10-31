# Signalpost Evidence — R5, review 1 over v0.7

R5 adds explicitly bounded free search, cited company summaries, and one Markdown report per input plus an HTML index. It starts from public v0.7 `c2e81e14f8e7ee7423083710a8244b28970d9adb`. R3/R4 remain archived. The tested Python sources are frozen in code commit `24071565b899ed87fa9b0bfe6cc87f79fe5e6224`; the delivery commit adds documentation and measured artifacts without changing them. Envelopes retain the legacy v0.7 schema/version for compatibility.

## One evaluator command

Use CPython **3.12.15**, pinned in `runtime.txt`, with the standard library only. No pip packages or model API are required. A clean clone and empty virtual environment passed all 154 offline tests. Supply a UTF-8 `orgs.txt`, one Norwegian organisation number per physical line; the evaluator supplies its own dynamic batch.

With an existing permitted `TAVILY_API_KEY` already in the **server-side process environment**, and at least 300 free basic credits confirmed for this run:

```sh
python3 -B cli.py --org-list orgs.txt --output runs/result.jsonl --cache cache/run --timeout-seconds 2400 --search tavily-free --search-credit-limit 300 --search-free-credit-limit 300 --search-strategy adaptive
```

Confirm the account's free balance, Pay-as-you-go **Off** and Auto upgrade **Off** before using those flags. Never put the secret in argv, a URL, an env file, an artifact or client page. No key is bundled; evaluators provide their own permitted account. The numeric flags cannot themselves verify billing or authorize payment. Reconcile credits across invocations. Advanced search, automatic expansion and paid fallback are disabled; unknown provider usage halts new searches. Maximum three reserved requests per company, within the run-wide cap.

The tested account has **1,000 monthly free credits, not 1,000 per day**. The included 100-company pilot used 184 basic requests. A 300-credit cap does not fund unbounded daily 1,000-company search: after exhaustion, unresolved web fields remain unavailable/ambiguous while other bounded collection continues. No continuously sufficient free allowance for that workload was established. A paid provider requires a separate cost decision; see [SEARCH-COSTS.md](SEARCH-COSTS.md).

For a LIVE command needing no provider key or search credits:

```sh
python3 -B cli.py --org-list orgs.txt --output runs/no-search.jsonl --cache cache/no-search --timeout-seconds 2400 --search none
```

Outputs and review directories must be new. Every input line receives one terminal envelope in order; duplicates link to one reused observation and invalid entries remain explicit failures. Defaults: four workers, 20 HTTP requests per unique company including search/robots/redirects, 90-second local Fetcher budget, and a supervised 2,400-second collection deadline (maximum 2,600). DNS/lock waits can overrun the local budget. Exit 0 means each entry completed with an available claim, not that every field is correct or complete. See [CLI.md](CLI.md).

## Measured paired sample

Both arms used the same **100 new companies**, selected before execution and excluding 1,805 previously used organisation numbers. Only R5 enabled free search. Source timestamps differ between arms; this is a local functional comparison, not official ground truth or a guaranteed population estimate.

| Companies with a nonempty available, referenced claim | v0.7, search none | R5, free search | Change |
|---|---:|---:|---:|
| Website profile (URL or description; one family) | 6 | 8 | +2 |
| Declared contact channels | 4 | 6 | +2 |
| Declared social links | 5 | 6 | +1 |
| Structured job postings | 0 | 0 | 0 |
| Dated activity | 0 | 0 | 0 |

The predeclared coverage threshold passed in three external proxy families. The gain is **small**, with no gain in jobs/news. Registry/roles/locations/financial coverage stayed 100/98/77/99. These groupings are ours; no official weighted recall or score is inferred. **There is no official 65/100 or 70+ result.**

R5 produced **100/100 terminal envelopes**, no synthesized execution failures, in 431.405 seconds including the root command/report step. The supervisor measured 427.723 seconds. It reported 1,841 HTTP requests including 184 search attempts. Claim states: 1,518 available, 230 not_available, 240 ambiguous, 252 blocked, 60 failed, 0 not_applicable. Completion and syntactic evidence validity are separate from factual accuracy.

Two AI reviewers inspected the fixed 20-case sample against retained primary sources: **zero demonstrated wrong-company publication**. This is case-by-case AI inspection, not a blind human gold set or a 0% error guarantee. The sample prioritizes all eight published websites and pads twelve companies by the frozen hash rule. It does not estimate overall precision.

Known limits remain visible: one generic `info@email.com` website link may be a template artifact and is not a verified contact endpoint; `roles[].effective_at` copies a role-group `sistEndret` update and does not prove an individual appointment date; social links can identify a group/regional channel rather than an exclusive legal-entity account; one business-context summary truncates a legal phrase; some limitations have mixed or missing source references. These findings were retained rather than tuned away using this holdout. Full claims and source references remain available.

## Read and reproduce the evidence

- [Paired metrics and integrity audit](smoke-r5/AB100-METRICS.json)
- [100 organisation inputs](smoke-r5/orgs100.txt), [sampling policy](smoke-r5/POLICY.json), and [run/reproduction notes](smoke-r5/README.md)
- [R5 result JSONL](smoke-r5/R5-result.jsonl) and [baseline result JSONL](smoke-r5/baseline-result.jsonl)
- [Company Markdown index](smoke-r5/review/index.md); download/open `smoke-r5/review/index.html` or `workspace.html` for standalone HTML
- [20-case summary](smoke-r5/MANUAL20-SUMMARY.json), [first reviewer](smoke-r5/MANUAL20-QA.json), [second reviewer](smoke-r5/MANUAL20-ROOT-DELEGATED.json)
- [Cost reconciliation](smoke-r5/COST-RECONCILIATION.json), [154 tests](smoke-r5/UNIT3-RESULT.json), [clean clone/empty venv](smoke-r5/CLEAN-VENV-RESULT.json)

Each company report preserves the six claim states, evidence IDs, source URLs, retrieval dates, periods, qualifiers, and refresh history. Concise synthesis is deterministic from supported observations, with references; no paid LLM is used. HTML/Markdown escape untrusted content. `--report-dir` selects a new report directory; the default is `OUTPUT.review`.

## Snapshot idempotence and refresh

Keep the complete local cache, including immutable `snapshots/`, and the previous JSONL:

```sh
python3 -B cli.py --org-list orgs.txt --output runs/replay.jsonl --cache cache/run --replay --previous runs/result.jsonl --search tavily-free --search-credit-limit 300 --search-free-credit-limit 300 --search-strategy adaptive
```

Replay performs no HTTP and needs no secret. Two replays over the identical completed read-only cache snapshot produced exactly equal claims and evidence for **100/100**, preserved the exact original LIVE envelopes, and reported zero material changes. The 2,942-file cache manifest was unchanged. [Acceptance](smoke-r5/REPLAY-ACCEPTANCE.json) and [independent review](smoke-r5/REPLAY-INDEPENDENT-REVIEW.json) state the precise scope.

The stronger **LIVE versus first replay equality check failed** and is [retained](smoke-r5/REPLAY-INITIAL-STRICT-CHECK.json): states/references of unconfirmed website observations changed. The cache has a shared latest-response index by URL; it is not a per-company replay log of every transient error. All available LIVE claims stayed identical, prior envelopes stayed exact, and original source snapshots remained retained. Do not call the entire LIVE run byte-reproducible from that latest index. Re-running the same fixed cache snapshot and preserving refresh history are the verified properties.

`--registry-snapshot` uses the documented [frozen-registry interchange](FROZEN-REGISTRY.md). The organizer supplies its snapshot/cutoff; compatibility with an unpublished schema is not asserted. External caches and timestamps must be declared.

## Runtime, rights and historical files

```sh
python3 -B -m unittest discover -s tests -q
```

154 tests passed without network in CPython 3.12.15, including a clean local clone and an empty venv with no third-party packages. The optional Dockerfile pins the official Python manifest and includes both readable report modules; this revised image recipe was not built or pulled. Tests and live measurement used an already available isolated CPython runtime, with read-only sources and limited CPU/memory. [Release manifest](RELEASE-MANIFEST.json) and [file checksums](checksums.json) bind sources and artifacts.

Raw downloaded page bodies and account credentials are excluded from the public repository. Evidence bodies remain in the private runtime cache for audit; public reports include extracted claims, URLs, hashes, dates and source pointers. Search snippets/answers/raw responses are not retained. Roles bodies redact birth identifiers. MIT covers our code, not third-party content. Public-source access follows [SOURCES.md](SOURCES.md), [R5 policy](R5-POLICY.md), TLS/public-IP/robots checks and the documented budgets.

`V07-DELIVERY.md`, `smoke/`, `RESULTS-v07.md`, historical profiles and their older reports are historical v0.7 artifacts; the LIVE CLI does not read them. R5 evidence is exclusively under `smoke-r5/`. Publication of this repository commit is not an official activation, an email submission, or qualification.
