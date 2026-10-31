# Signalpost — entity-attributed social recovery, local review (2026-10-31)

Current local candidate builds on the three-fix review `2aaaef3cac092c04f58e8b2f27fbb59de696c20e`; the official submitted version remains `c2e81e14f8e7ee7423083710a8244b28970d9adb`. No send, push or official revision activation is implied.

## Run from evaluator-supplied organisation numbers

Python standard library only; no credentials, paid APIs or bundled source cache are needed:

```sh
python3 -B cli.py --org-list orgs.txt --output runs/result.jsonl --cache cache/new-run --timeout-seconds 2400 --search none
```

Use new output/report directories. Registry contact claims remain disabled; website contacts remain separate. Exact-entity website checks, bounded crawling, TLS/public-IP/robots controls, terminal envelopes, previous evidence and refresh behavior remain intact. The legacy format/version label is retained; the commit and source manifest identify this candidate.

Tested in CPython 3.12.14. The inherited runtime/Docker recipe pins 3.12.15; that image is not claimed to have been rebuilt. `Dockerfile` copies the new modules and the pinned `organization_types.json` data. No third-party Python dependencies. On macOS, run tests with `TMPDIR` set to a canonical non-symlink directory, because the inherited report writer refuses symlink ancestors.

## Recovery rules

The previous review was too conservative (27 social URLs reduced to 1). We now also extract an explicit company-declared social/follow control when the profile identifier matches the full legal identity or a trade-name explicitly bound to that verified site. Multiple matching networks in corporate navigation can corroborate a declaration. Person/other-entity sameAs, agency/sponsor/author/share contexts, personal LinkedIn profiles, hashtags and media-item URLs remain excluded. A bare matching footer link still fails the ownership check. A regional/legal differentiator may not be dropped to match a parent group.

Schema.org organisation subtypes are recognized through the pinned transitive Organization hierarchy. A subtype node still needs an exact name plus registered address/site URL or exact corporate ID. Conflicting IDs veto a same-name assertion. Norwegian letters, leading legal forms and official localized LinkedIn hosts are normalized. Every fallback carries the source href, source URL, name-matching criterion, contextual statement and verification scope.

**Scope:** these are identity-matched company declarations, not independent social-platform authentication or proof of account access. URLs are not asserted to be distinct accounts; aliases can remain. Rights/access denials remain explicit. The new rules derive from company-owned pages and pinned schema metadata, with no new paid connector.

## Measured comparison

See the [Portuguese review](review-social-recovery-20261031/RESULTADO.html) and [metrics](review-social-recovery-20261031/METRICS.json).

| Local sample | c2e81e14 social URLs / firms | Previous strict review | Recovery |
|---|---:|---:|---:|
| Earlier 100 (development) | 27 / 12 | 1 / 1 | 18 / 9 |
| Separate new 100 | 40 / 12 | 2 / 1 | 14 / 7 |

The separate sample was selected/frozen before execution, excluding 2,005 previously used companies, stratified 50 with registered website / 50 without. Independent baseline/recovery LIVE runs collected URL snapshots; paired runs use one immutable union snapshot (baseline responses have priority). Source dates/cache are declared. This is not a population estimate or an official score. Raw source bodies remain private local cache files.

Both paired versions retain the same site/contact/news/job family coverage. Known Wix, personal, group and hashtag errors remain unpublished. Local inspection of all retained social evidence found no demonstrated wrong-company attribution, but is neither independent platform verification nor blind human gold accuracy. 181 offline tests passed; the original synthetic adversarial suite retains a 7→0 false-publication improvement over the submitted base with no lost positive controls. The 100-company replay preserves prior envelopes and exact claims/evidence with no material false changes. LIVE collection returned 100/100 terminal envelopes; individual field failures remain visible.

```sh
python3 -B -m unittest discover -s tests -q
python3 -B review-social-recovery-20261031/measure_recovery.py
```

The measure script rechecks private cache manifests when those caches are present. A new live evaluator run from a clean clone does not need them. `REVIEW-MANIFEST.json` binds current sources/tests/data; `review-social-recovery-20261031/` contains current measured artifacts.

## Public competitors and optional independent review

The last public standings still say reviewed **17 October 2026**, despite checking on 31 October. Karthik leads that published provisional round at 70.43*. No current winner or current-day ranking is inferred. [Official source and all rows](review-social-recovery-20261031/PUBLIC-STANDINGS.json). The public table does not link the leading entrants' repositories; no competitor code was incorporated.

[Independent public-profile review brief for Argon/Grok](review-social-recovery-20261031/INDEPENDENT-REVIEW-ARGON-GROK.txt) contains only business identities, source URLs and profile links. No external message was sent. Our official score/rank remains unknown.

## Historical evidence

`review-20261031/`, `ARCHIVE-THREE-FIXES-README.md` and `runs/CLEAN-VERIFICATION.json` refer to the previous local three-fix candidate. `ARCHIVE-R5-README.md`, `smoke-r5/`, old `RELEASE-MANIFEST.json` and `checksums.json` describe historical R5. `smoke/`, historical profiles and v0.7 documents describe earlier versions. Their measurements/hashes do not identify the current candidate.

### Additional local evaluation (31 October 2026)

The agent now also uses bounded, untrusted name/domain leads and ordinary canonical-host candidates. Every site must still pass exact entity checks. Public dual-stack DNS prefers IPv4 without weakening private-address rejection or TLS validation. Company-contact extraction supports literal visible text as well as actual contact links, and withholds unresolved regional-company contact blocks on shared sites. No registry phone/email is promoted into website contacts.

The local scale protocol uses 1,100 randomly selected previously unused organisation numbers, an explicitly supplied frozen registry snapshot, and fresh external website requests. The interchange snapshot is our documented adapter, not a claim of compatibility with an unpublished Builderr format. Report capture and final-extractor replay are recorded separately. Missing or failed source fields stay explicit even when the overall envelope is completed.

A larger smoke test does not yield an official score. Official family weights, the private verified union and actual evaluator resource budget are not published. The old starter proxy must not be presented as the current 50/30/12/8 score. Primary-source rechecks of independent research are tracked locally; training cohorts are not labelled unseen validation.

### Follow-up gap closure (31 October 2026)

Verified company news indexes now supply ordered discovery leads before redundant sitemap requests. Legal ownership pages and contact pages precede repeated auxiliary identity pages; sitemap discovery remains a fallback. The page exploration bound is twelve attempted URLs including the entry page, within the existing twenty-request company cap (robots, maps and redirects also count toward that cap). The space saved by avoiding redundant maps can cover more articles without dropping useful contact/about pages. No index link, sitemap date or discovery priority is publication evidence. Exact entity attribution, real article content and a supported publication date are still required. No company-specific URL or name was added to the runtime. Follow-up A/B artifacts are separate from the earlier `affe542` evaluation.

### Gemini research follow-up (31 October 2026)

An independently supplied PDF was parsed as research leads, never runtime input or a replacement for source evidence. The collector now groups adjacent leading initials when generating its maximum two generic domain leads, and recognizes a literal `Org.` label only with a valid Norwegian organisation checksum. Conflicting entity IDs still veto identity. Neither change embeds company names or URLs. Registry phone/email claims remain disabled.

A fresh ten-company capture used 128 requests in 44.051 seconds, with no paid API. A paired replay of 100 companies uses an immutable union of the previous cache (precedence) and that capture. Against `abac582`, website coverage rises from 57 to 58 companies, descriptions from 52 to 53, and contacts from 338 to 340 facts across 51 to 52 companies. Social links remain 39 and dated activity remains 26. Only P.E. Gaarud changes between those paired outputs. These figures are not comparable directly to the earlier 56-site run because the retained source set differs. Research/development cohorts are not blind gold.

238 unit tests pass. Research caveats include profile labels without hrefs, group-versus-entity ownership, bundled news-index dates, undated hiring pages and spontaneous applications. No Gemini record is promoted merely because its supplied label says verified. Official score remains unknown; nothing was submitted or pushed. Detailed local artifacts are in `evaluation-20261031/gemini-review-20261031/`.

### Follow-up of the independent 20-company source audit

Corporate references such as “vår Facebook side” and “our Facebook page” now count as an explicit first-party profile declaration only when the profile identifier also matches the full legal/trade-name or the exact registered entity domain under the existing rules. Third-party contexts, different-entity sameAs and unsupported handles remain excluded. The retained evidence excerpt is centered on the literal declaration. No network request, company-specific URL, domain lead or registry contact was added.

On an identical retained-source A/B of 100 companies against `f74d874`, the change recovers the Kilsund Travel Facebook declaration: 39 to 40 profile URLs across 20 to 21 companies. Other external families remain unchanged. This is a development diagnostic, not an official score. The reported SanOmega recovery in a separate fresh 20-company capture came from an existing `.no` redirect responding successfully, not from a code improvement. The experimental third `.as` domain lead and foundation-prefix adjustment were removed after the controlled comparison showed no gain.

The audit also exposed a stale application link: the Haugesund savings-role company page still invites applications, but its linked FINN ad is expired. No open vacancy was added. Shorts/posts do not become profiles, search snippets do not become fetched primary documents, and event/deadline dates do not become publication dates. 240 tests pass. Local evidence and limitations are under `evaluation-20261031/argon-review-20261031/`; no revision has been sent or activated.

### Verified historical-name and pressroom discovery follow-up

A current first-party social declaration may now match the full former legal name on the same organisation's official `historiskeNavn` record. Both dated bounds must be valid and the period must have ended by the source observation. Historical names retain all regional/legal qualifiers; Person/foreign-identifier vetoes and explicit declaration requirements remain. Proof records retain the historical name, dates and organisation number, and the social claim references the official registry response. This is company-declared evidence, not a claim that the destination account resolves or is authenticated.

Generic `presserom`, `pressroom` and `newsroom` article paths now supply bounded activity leads and detail-page recognition. Publication dates and company-subject attribution remain mandatory. An isolated `cookie_settings=true` UI toggle on an identity-page lead is normalized to its content URL; other query parameters are unchanged and the fetched response still supplies the identity proof. No company-specific URL or profile was added.

Against `b3ea5a5` on identical retained sources for 100 companies, social URLs rise from 40 to 42 (DIPS LinkedIn and YouTube), with 21 covered companies unchanged. Dated articles rise from 26 to 29 across the same nine companies: four Entra press releases are added and one earlier Q2 consensus article falls outside the twelve-page exploration bound. Sites, descriptions, contacts and hiring counts are unchanged. The lost older article is explicitly recorded; no full-retention claim is made. 245 tests pass. The independent FINN discovery is a validated research lead, not a runtime hiring gain; no known URL was injected into runtime input. Official score remains unmeasured, and no revision has been sent or activated. Detailed artifacts are in `evaluation-20261031/grok-positive-review-20261031/`.
