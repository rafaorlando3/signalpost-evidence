# Signalpost version 3 (revision 2): qualification report

Product commit: `1a50b433f98dcb3bf89e5f7b8356ba4729c905ab`  
Product tree: `a4cfb6aed70fe4a2c1d382e66a7f266add1ebcdb` (945 files verified).  
CI orchestration commit: `3511cb679eb064a7bdda128e2c5fdfaca27d9988` (10 added orchestration files; product unchanged).  
Actual run: [42932202413](https://github.com/rafaorlando3/signalpost-evidence/actions/runs/42932202413), completed successfully on 11 November 2026 at 00:40:34 UTC, standard public GitHub Actions Linux runner.

## Changes covered

- Retained-source identity auditing reconstructs the registration/root/contact-map chain, checks the entire proof and operator compatibility, and rejects tampered/missing/mismatched evidence.
- Viewer identity-proof rendering handles operator, contact-map, business and legacy proof shapes, absent or malformed spans, and escaped source text without throwing.
- Docker packaging includes `contact_map_identity` and its local import closure. CLI documentation/defaults and the build allowlist agree with the implementation.
- Existing collector, identity abstention, attribution, news and hiring behavior remains covered by the full regression suite. No personal search credential or paid service is required.

## Actual test results

- Core pinned Python 3.12.15 image: 604 tests discovered, 599 passed; exactly five Node-dependent tests skipped and reported as skipped.
- Supplemental test-only Node v24.22.2 image: **604 tests passed, zero failures/errors/skips**. All five workspace-rendering Node tests executed. Targeted groups: contact-map auditing 13, rendering templates 2, workspace rendering 5, CLI/package consistency 7.
- Unmodified production image built, CLI help ran, and all 30 root modules imported.
- Fresh diagnostic batch: **100 inputs, 100 completed envelopes**, zero rejected envelopes and zero unsuccessful entries, empty initial cache, `--search none`.
- Structural validation and retained-source consistency audit passed with zero reported errors. The collector marked 33 websites available; that is not independently established ownership precision.
- 2,060 HTTP requests, maximum 24 per company; third-party service cost US$0. Cold batch wall time 409 seconds; runtime p50 10,472 ms and p95 30,396 ms per company. Container exit 0, stopped before audit, no OOM or timeout. Job-owned cleanup completed successfully.

[Machine-readable actual report](revision3-ci-report.json) includes all 100 per-company outcomes, exact image IDs, input/output hashes, actual unit results and audit limitations.

Input SHA-256: `4a348a856c5f23c199e6ddb650c327a5e2cb6b292f4fe331423069919bc4f19c`  
Output SHA-256: `7f5c87a9986d1a934c66f94d8bbcbf2f806876234c8aea747e4459a5c8125296`  
CLI summary SHA-256: `ae80e961121414841c4a6bda242afdb2e1dc4fc315445a7b9f0f66e09dabf5be`

## Reproduction

Check out the exact product commit above, use Python 3.12.15, and supply one organisation number per line in `orgs.txt`:

```sh
python3 -B cli.py --org-list orgs.txt --output runs/result.jsonl --cache cache/new-run --timeout-seconds 2400 --search none
```

Use fresh output and cache directories. The README contains the pinned Docker option. Node is only a test dependency for executing the renderer assertions; it is not a product dependency.

## Limits

This prespecified diagnostic sample is alphabetically biased (90 AS / 10 ASA, 44 registry website hints / 56 without hints). It is not an official shared scoring batch or a representative population sample. Source audit checks consistency with retained evidence, not independent ground truth, source completeness or ownership accuracy. There are 33 items requiring external identity review. Precision, recall, official score and probability of winning are not established; no before/after live recall improvement is claimed from this batch.

The public CI retains this compact report and ordinary logs; the complete ephemeral source cache and generated HTML workspace were not uploaded. The Node validation image uses an official pinned tarball and vendor libstdc++6 resolved at build time; its exact image ID is recorded, without a claim of bit-for-bit apt reproducibility across future builds. Node execution is not browser end-to-end testing.
