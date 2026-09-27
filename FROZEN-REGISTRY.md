# Frozen registry input

`--registry-snapshot FILE.jsonl` activates a local interchange adapter. The organizer's actual snapshot format and invocation have not been supplied or verified; this adapter is preparation, not official compatibility certification.

Each line is a successful registry response with `requested_url`, final `url`, timezone-bearing `retrieved_at`, `status: "available"`, `status_code: 200`, `content_sha256`, and retained UTF-8 `text` containing JSON. An optional parsed `json` must equal the text. `retained_text_sha256` is required when redaction makes retained text differ from original bytes. Only `https://data.brreg.no` URLs are accepted. Duplicate requested URLs, invalid JSON, mismatched hashes or timezone-less dates reject the snapshot.

When active, all registry reads come from this file, including in `--fresh` mode. A missing registry response is `failed`; it never silently falls back to live registry data. External company pages still follow the normal network/robots policy. Loading the frozen file is not an outbound request. Original source timestamps are preserved; the input artifact SHA256 is recorded in refresh/run metadata. Role birth dates and personal identification fields are redacted before retention. Existing replay/cache modes continue to work for external pages.

Example invocation:

```sh
python3 agent.py --input input.jsonl --output runs/evaluation.jsonl --cache cache/evaluation --registry-snapshot registry.jsonl --fresh --workers 4
```

The required URL set currently consists of entity, accounts, roles and first-page subunits responses per organisation. Financial periods are selected from company accounts, not consolidated group accounts. This schema needs an explicitly agreed conversion if the organizer supplies another structure; do not relabel invented or live data as a frozen official source.

Tests prohibit all DNS/network access for a supplied-registry-only fixture, verify missing-source failure without fallback, preserve retrieval dates, and reject corrupt/external records. Real organizer integration, Linux evaluation and payment eligibility remain separate gates.
