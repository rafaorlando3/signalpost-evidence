# R5 operational and source policy

R5 starts from public v0.7 commit c2e81e14f8e7ee7423083710a8244b28970d9adb. R3/R4 strategies and filters remain archived. Coverage groups and sampling are declared before inspecting the paired results. They are internal proxies, not the organizer’s unpublished family weights or an official score.

## Secret and API configuration

The sole optional secret is TAVILY_API_KEY, supplied in the server-side process environment. Do not put its value in argv, a URL, an env file, repository, cache, artifact, log or client page. No credential is bundled. The evaluator supplies its own permitted key/plan. The local runtime injects the key through encrypted SSH stdin into a child process environment; Docker Config.Env does not contain it.

Use --search tavily-free only after confirming a Researcher free balance and Pay-as-you-go/Auto upgrade off. --search-credit-limit is a run-wide request ceiling, and --search-free-credit-limit is the confirmed allowance for that run, bounded by the current account balance. Neither authorizes a payment. Reconcile usage across runs. Basic is fixed; advanced and paid fallback are not activated. Unknown usage prevents new searches. The normal no-key command remains --search none; it still produces terminal envelopes and cited reports.

No model API or external synthesis service is used. Synthesis is deterministic from supported claims and their evidence. Runtime uses the pinned CPython 3.12.15 standard library; no pip dependency or paid subscription is required.

## Outbound policy

Company-page requests retain v0.7 public-IP checks, TLS verification, redirect validation, robots checks and the 20-request company ceiling, including search requests. API search uses only the fixed api.tavily.com HTTPS host; authorization is never forwarded to redirects. Results are candidates only. They must pass the existing public URL and exact-identity checks before facts become available. No unofficial social-platform scraping is added. Social URLs mean links declared on identity-checked pages, not independent proof that the destination account is owned by the company.

Operator/publisher identity, group relationships and dated-item attribution are qualified separately. A statement about a group is not silently rewritten as the legal entity’s own activity. Menu text, product pages and modified/updated timestamps are not publication dates for news. Insufficient attribution is ambiguous and its evidence/qualifiers remain visible. Independently supported sibling items and other families remain usable.

## Retention and output

Every input line retains one terminal envelope, including duplicates and invalid inputs. Duplicate input lines reuse one bounded observation and have explicit linkage. The six availability states remain distinct. A completed run does not establish completeness or accuracy. Existing outputs/review directories are refused.

The cache contains retained source snapshots and minimal URL-discovery metadata for replay. Do not commit downloaded bodies or cache directories. Registry role-body redaction and original/retained hashes remain declared. Third-party content is not relicensed by this repository’s MIT licence. --previous preserves earlier envelopes/evidence; replay must not create material facts or false changes. Readable Markdown and HTML preserve source dates, hashes, claim-level attribution, unknowns and refresh changes.

The official frozen registry snapshot is passed with --registry-snapshot using the documented interchange. Compatibility with an unpublished organizer schema is not asserted. The organizer supplies the official batch and cutoff.

## Promotion criterion

The paired sample is 100 new companies, excluding 1,805 previously used numbers. website URL+description count as ONE conservative external proxy family; the others are contacts, declared social links, job postings and dated activity. Promotion requires more companies in at least 3 of these 5 families and zero material wrong-company publication observed in the deterministic 20-company manual review, plus operational/replay/smoke checks. Zero observed in 20 is not a population guarantee or a 65/100 score. No changed sample or omitted error is allowed to manufacture a pass.
