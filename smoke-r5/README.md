# R5 paired smoke100

Use orgs100.txt and POLICY.json with exclusions1805.txt for the frozen sampling specification. Five additional cold candidates were reserved but not executed. Baseline and R5 used separate empty caches; only R5 enabled free basic search. Source timestamps differ, so this is not an official frozen-web score.

From repository root, with an existing permitted TAVILY_API_KEY supplied only through the server-side environment and confirmed free balance/PayGo Off:

```sh
python3 -B cli.py --org-list smoke-r5/orgs100.txt --output runs/r5-smoke100.jsonl --cache cache/r5-smoke100 --timeout-seconds 2400 --search tavily-free --search-credit-limit 300 --search-free-credit-limit 300 --search-strategy adaptive
```

Use new paths and reconcile the same monthly account across runs. No credential or source-body cache is bundled. New LIVE sources may differ from these observations. Baseline reproduction uses public c2e81e14f8e7ee7423083710a8244b28970d9adb and --search none.

R5: 100 terminal rows, 1,518 available claims, 1,841 HTTP requests including 184 search attempts, 431.405 seconds root runtime, US$0 paid API cost. Account usage counter remained zero despite 184 response-reported credits; do not infer zero consumption.

Zero demonstrated wrong-company publications in 20 fixed AI-inspected cases does not certify every fact or population precision. Unknown contacts, social ownership, role dates and synthesis limitations remain in the ledgers.

Initial LIVE-to-replay strict equality failed for unconfirmed website states/references. Repeated replay over the identical final read-only cache has equal claims/evidence, exact original history, zero network/material changes; the 2,942-file manifest stayed unchanged. Whole JSONL contains changing execution metadata. Source bodies and the complete operational cache remain private; hashes/URLs/pointers and extracted observations are public.

The local promotion criteria passed. No official score, qualification, daily activation or email submission is claimed. Historical v0.7 evidence is under smoke/ and V07-DELIVERY.md.
