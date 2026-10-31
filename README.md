# Signalpost — three attribution fixes, local review candidate (2026-10-31)

This candidate combines Soham's three requested corrections: parent/group site attribution, corporate social-profile ownership, and real dated company posts. It starts from the repository's existing R5 improvements and compares with submitted version 1, `c2e81e14f8e7ee7423083710a8244b28970d9adb`. This local commit is **not** a submitted or activated official revision.

## One evaluator command

Standard library only; no credentials, paid APIs, browser session, fixed company list, or bundled cache required:

```sh
python3 -B cli.py --org-list orgs.txt --output runs/result.jsonl --cache cache/new-run --timeout-seconds 2400 --search none
```

Use a new output and report directory. Inputs are supplied dynamically by the evaluator. The live collector retains the existing public-IP/TLS/robots checks and 20-request company budget. Unknown or blocked sources remain explicit. Registry contact details are not published as contact claims; only literal contact links from identity-checked websites are retained. The optional pre-existing free-search feature is unchanged and is not used in this comparison.

Tested locally on CPython **3.12.14**. The inherited `runtime.txt`/Docker recipe pin 3.12.15; that image was not built in this review. `Dockerfile` includes both new modules. Source and test hashes are listed in `review-20261031/source-freeze.json` and the review manifest. No third-party Python packages are required.

## Changes

- `attribution.py`: exact legal-entity social declarations, bounded public destination corroboration, group-brand safeguards and post-subject attribution. A footer link, a personal LinkedIn profile, a share action, or group metadata is not sufficient ownership evidence.
- `agent.py`: group/operator conflicts prevent inherited website facts; real article detail/content and publication dates are required. Menu headings, products/collections and modified-only dates are withheld. Genuine first-person announcements can be attributed through an exact-entity publisher.
- `output_contract.py`: additive mapping to the current starter kit's `OUTPUT_CONTRACT.md`. `official_website` aliases the existing `website.verified_url`; legacy fields remain. `run_id`, `confidence`, evidence `claim_span` and operations keys are emitted. Confidence is an **uncalibrated rule score**, not measured precision. Source spans, extraction pointers, hashes, snapshots and previous envelopes remain available.

## Measured comparison and limitations

See [Portuguese review](review-20261031/RESULTADO.html), [metrics](review-20261031/METRICS.json), [sampling](review-20261031/selection.json) and [100 company reports](review-20261031/candidate-reviewed.review/index.html).

100 new companies were selected before execution (50 declared websites / 50 without) excluding 1,905 previously used numbers. Independent live collection populated a shared immutable URL-response snapshot. Both reported comparison arms replay that same snapshot; baseline captures take priority and candidate captures fill absent URLs. Pre-final live candidate claims are **not** the reported candidate arm. Raw page bodies remain private in the local cache; the manifest binds them without republishing them.

| Published family | c2e81e14 | Candidate |
|---|---:|---:|
| Verified sites, companies | 16 | 16 |
| Corporate social profiles, companies / links | 12 / 27 | 1 / 1 |
| Dated activity, companies / posts | 1 / 4 | 1 / 1 |
| Website contact channels, companies / items | 15 / 49 | 15 / 49 |
| Structured job postings | 0 | 0 |

The revision is more conservative and **loses coverage**. Withheld social links/posts have not all been proved false; some cannot be corroborated under public access limits. No overall precision, recall or official-score increase is claimed. In the explicit 10-case synthetic adversarial suite, false publications fell from 7 to 0 with no lost positive controls. That is targeted regression evidence, not population accuracy. Source inspection of all 16 published websites found no demonstrated wrong-company site; it is a local inspection, not blind independent gold validation.

100/100 terminal envelopes pass the legacy structural checker and the local check of the downloaded minimum contract. This does not claim execution of Builderr's private official evaluator. A separate final-source cold-cache run covers 10 of these companies. Exact live runtime/requests are in `review-20261031/cold10.summary.json`.

```sh
python3 -B -m unittest discover -s tests -q
python3 -B review-20261031/measure.py
```

167 offline tests passed. On macOS, set `TMPDIR` to a canonical directory without symlink ancestors when running the test suite; the inherited report writer deliberately rejects symlink paths. `measure.py` expects the private captured cache to recheck its manifest; a clean evaluator clone does not need that cache for a new live batch. Refresh/replay verification is documented in the review integrity artifact. Do not treat a self-reported proxy, a prepared commit or this review as an organizer receipt or official qualification.

## Historical artifacts

[ARCHIVE-R5-README.md](ARCHIVE-R5-README.md), `smoke-r5/`, `RELEASE-MANIFEST.json` and `checksums.json` describe the earlier R5 snapshot. `V07-DELIVERY.md`, `smoke/`, `RESULTS-v07.md`, historical profiles and earlier reports describe v0.7. Their old hashes/measurements do not describe this candidate. Current evidence is exclusively under `review-20261031/` and `REVIEW-MANIFEST.json`.
