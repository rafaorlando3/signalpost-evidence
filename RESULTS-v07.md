# Version 0.7 review, 26 September 2026

## Decision and measured results

Freeze this version for organizer review. Adaptive discovery is the preferred optional search configuration; the no-key default remains available. Further speculative query variations are not justified before official feedback. There is no official score, qualification, competitor-superiority claim or revenue.

| Sample | v0.6 baseline | v0.7 | Interpretation |
| --- | ---: | ---: | --- |
| Development, 1,000 companies, registry discovery | 37 verified sites | 37 | No additional website coverage; all previous sites retained |
| Separate 100 companies, optional search | 4 verified sites | 7 | Three gains; no previously verified site lost |
| Same separate 100, declared social links | 1 company | 3 | Links from checked source sites; social-account ownership not independently verified |
| Development contact extraction | Not implemented | 104 links at 30 companies | Literal mailto/tel links, each with its source |
| Separate 100 contact extraction | Not implemented | 33 links at 7 companies | Additional supported fields, not evidence of paid demand |

The 100 organisations were selected before collection and exclude the prior 1,400 organisation numbers. The sample is not guaranteed domain-disjoint. Collection logic was frozen before viewing its results. Only the version label changed for release. Paired final outputs use the same retained sources. The earlier 1,000-company set is development data; it is not an independent test. Website counts are observed availability, not recall. No independent labelled ground-truth set or competitor outputs are available.

Three new websites were manually checked against their retained source text: ELLERA AS (920295738), KS-MØTEPLASSER AS (929290755), and INDO NATURALS AS (922302936). Every added site explicitly publishes the requested organisation number. Indo Naturals' retrieved legal terms identify the seller but carry a March 2020 update date; the current published page is evidence, not independent confirmation of subsequent ownership changes.

## Fresh-page validation and source failure

A second 100-company run started with an empty HTTP cache. It retained all seven confirmed sites and three social-link companies, with contact links available at six companies. Saved search candidates were the only preloaded fixtures. Each consulted query reserved one request against the 20-per-company cap, but no new search-provider query was issued. **This is a cold HTTP collection test with fixed query results, not a fully cold end-to-end provider benchmark.**

The run took 365.16 seconds, made 1,404 actual HTTP requests and reserved 192 hypothetical search requests: 1,596 total for budget checking, at most 20 per company. All 100 terminal envelopes completed, with no missing search fixture. The 192 live query round trips and any provider-side result drift were not measured in that timing.

The annual-accounts endpoint returned failed responses for 95 companies during this run, primarily HTTP 503, leaving filed-account fields available for only five. Those failures are preserved. Terminal completion therefore does not mean complete company data. Earlier cached observations must not be represented as fresh successes. The organizer's frozen official snapshot may avoid live-source instability, but its actual input format still needs confirmation; our documented adapter is not yet claimed to match it.

## What changed

A second discovery query combines legal name, exact organisation number and Norway only after prior leads fail. Irrelevant directory results are filtered and candidates ranked before crawling. Search snippets are used for discovery only, discarded afterward and never cited as facts. Up to two shallow same-host legal/contact hints can accelerate exact-number checks. Later candidates retain a portion of the existing request budget. Robots-declared sitemaps are checked within the same cap.

Parsing now tolerates malformed optional HTML attributes. Explicit organisation-number labels support dotted groups and additional common labels without treating bare order/phone numbers as identity. Contact fields include only literal mailto/tel links from identity-checked source pages; guessed emails and identifiable third-party contexts are excluded. The retained-source audit checks contact values, original hrefs, explicit organisation numbers and literal identity spans. Contact reordering does not create a false refresh change.

Rejected experiment: a number-only query returned irrelevant international pages and added no confirmed sites in the development sample. It was replaced before the independent adaptive run. A corrected 20-company development probe retained two sites and added no coverage. Those failures are part of the record; they are not included as extra successful discoveries.

## Verification

88 unit/integration tests pass on macOS and the pinned Linux Python image. Final development and independent outputs pass structural validation and retained-source consistency audits. The cold HTTP output passes the same checks. Negative tests reject modified contact values, header injection and misleading organisation-number contexts. These audits check consistency with captured evidence; they do not certify real-world completeness or official correctness.

The public package contains original source, tests, exactly 1,000 matching profiles and manifest, a standalone review page, measurements, input for the separate 100 and an optional Dockerfile pinned to the official Python image. No model inference or third-party Python dependencies are required at runtime. Full downloaded source caches, search snippets, API keys and private user documents are excluded.

## Costs and execution options

The Tavily account moved from 305 to 609 of 1,000 free monthly credits: 304 used in this improvement round, 391 remaining at observation. Pay-as-you-go was disabled and the observed paid API charge was US$0. Breakdown: 93 for the rejected development query, 96 for the fresh independent baseline, 97 additional independent adaptive queries and 18 for the corrected development probe. Compute, electricity, connectivity and development/model costs are excluded.

Default mode needs no key or paid API. Recommended optional evaluator mode adds `--search tavily --search-strategy adaptive --search-credit-limit 200` with an evaluator-supplied `TAVILY_API_KEY`. At the [published Tavily rate](https://docs.tavily.com/documentation/api-credits), 200 basic queries represent at most US$1.60 in nominal query charges per 100-company batch. This is a planning estimate for an evaluator's own authorized account, not permission to activate paid usage for the author. Each API request shares the company HTTP cap.

## Submission status

This document accompanies the code for review. It does not establish that an email was delivered, the repository was accepted, an official run completed or a prize was earned. Repository publication and the exact submitted commit are tracked separately. The frozen-snapshot adapter, country eligibility and payment arrangements remain subject to organizer confirmation. No participant has been shown to outperform all competitors by these local observations.
