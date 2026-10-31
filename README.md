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
