# R1: final Home + D2 + D3 integration

Integrated source: f29618b9323db492c844741ab06237c03f8ffe66, tree 94da64bceddef97a9938589ddab613b8994ded48. Main incorporated: bde2a0bdb151d5970aaf4874ad981d3608feca44. Subsequent hand-back changes add only this evidence.

R1's prerequisite is verified: PR #1301 merged at f3440b0ca9f68dfe0ec9ce843ac88ce2576758f6 on 2026-11-06; D2 PR #1207 merged at 9b0ab92290a808ecb37d34ed69b290100336d002. Both are ancestors of this source. D3 was not implemented independently. `red-pwa.log` was committed at 47eb1c0c before integration and shows the missing manifest/worker/registration/icons. `green-pwa-preservation.log` verifies their presence and byte equality with merged D3, plus D2 ancestry and the Home rule corrections. R2/R3 remain resolved; `green-merge.log` records a conflict-free merge check.

## Contract and source preservation

Read #1301's exact web-api.v1.md delta; integrated contract blob 6b0442bdf56beea20eb5306ccf584683b435e189. It adds the manifest/worker/registration/icons web routes, PNG/webmanifest types, same-origin manifest/worker CSP, cache headers and safe route-template logs. The worker caches the static shell only; API answers and non-GET requests are never cached, queued, retried or replayed. No new Home request, route, source resolver, write, storage or approval operation.

D3's public assets, _document.tsx wiring, unit proof, apps/web instructions, server web implementation and web API contract match its verified merge. Home is presentation state inside /; the manifest starts at /. D2's rewrite and Home-first/four-tabs/command destination descriptions remain. Main's Sessions close-sheet and atomic Answer-target withdrawal fixes, setup page/API/CSS and prior contract corrections remain.

The frozen winner remains R6-F at 0f55ce87db42abb1f8391818d481f1e429d6aee3. `adoption-integrated.json` records the seven winner product-file hashes: five remain identical; Fleets retains D1's shape prop, and App retains the newer main behavior fixes. No competing climb, token change or new design was introduced. The original final report, ledger, rankings and screenshots remain linked in the parent README and PR.

## Scoped checks on the integrated source

- `npm run typecheck`: PASS.
- `npm run check`: PASS, 37 source files; schema/guard/spacing checks.
- `CIRCLE_NODE_TOTAL=2 npm run build`: PASS; one worker, four pages including /setup; manifest, worker, registration and icons exported.
- `node --test --test-concurrency=1 test/unit/home.test.ts test/unit/statusMark.test.ts test/unit/contrast.test.ts test/unit/pwa.test.ts`: 18/18 PASS, zero skips (`targeted-unit-pwa.log`). PWA P1–P8 include real fixture Chromium installability, worker control, shell-only caching, offline API/write failure and no replay after reconnection, plus cache-failure behavior. This is fixture evidence, not installation on Jake's phone.
- `node --test --test-concurrency=1 test/browser/home.test.mjs test/browser/command-navigation.test.mjs test/browser/c5_answer.test.mjs`: 20/20 PASS, zero skips (`targeted-browser.log`). Three affected files only: Home composition/ordering/honesty, shared lane/cache, single composer/drafts/owner press, phone sheet close, focus and target withdrawal/replacement.
- `cargo fmt --check`: PASS. No Rust crate changed by D4; no local clippy applicable.
- Exact D3 preservation, both prerequisite merges, Home rules and merge compatibility: PASS.
- Owned-path and whitespace checks against main: PASS. No dependency, toolchain, STATUS.md or frozen release-file change.

Full workspace/browser suites are delegated to PC CI under Jake's credits rule. CI and Claude exact-head re-check remain gates after this push. No CI/review watcher, polling loop or sleep is left running. No new helper was needed; the original archived helper and clean no-push check remain recorded in the parent evidence.

## Fresh integrated capture ledger

Command: `node test/design-screens.mjs docs/evidence/1030/review-2/shots home,home-live,home-answer,home-loading,home-empty,home-error,home-stale,sessions,thread,new-thread,fleets,fleet-detail,loading,empty,error`.

Result: 30/30 real Chromium captures at 390×844 and 1440×900, synthetic data visibly labelled DEMO. Zero page errors or horizontal overflow. The source is pinned in `shots/capture.json`. Each raw screenshot is unchanged; full-page and viewport/modal/scroll cropping are explicit. Comparison/contact-sheet tools are inspection aids, not alternate evidence captures.

| State, both widths | Comparison with the previous best / preparation |
| --- | --- |
| Home | R6-F hierarchy retained: numbered Needs you, fleets, then Live now. Both fresh Home PNGs are pixel-identical to the D1-corrected preparation. Relative to frozen R6-F, D1's distinct status glyphs and timestamp seconds remain the documented corrections. |
| Home Answer | Existing single composer, ticket/spec prefix, owner-press Queue/Steer and context preserved. Phone is a real viewport-only modal; desktop keeps Home beside it. Both images match the earlier preparation exactly. |
| Home Live reading | Actual scroll shows the gap, qualified provenance and both active rows above fixed phone tabs. Both images match. Full-page phone shots honestly retain fixed-tab overdraw at the initial viewport edge; nothing was hidden or truncated. |
| Home loading / empty | Reading remains distinct from fresh zero; Nothing needs you, No fleets and No active sessions retain their separate meanings. All four images match. |
| Home partial / stale / error | Gap/scope remain visible; failed reads retain last-good snapshots and rows with explicit error/stale cues; initial failures invent no data. All captured images match. |
| Sessions, Thread, Fleets, Fleet detail, Loading, Empty, Error | Existing M6 composition and reported content retained with Home navigation. All images match. |
| New thread | Same geometry, words and content at both widths. Phone matches exactly; desktop differs in 49 pixels at rounded control/focus edges, maximum RGB-channel delta 6, with no observed text/layout drift. |

`capture-comparison.json` records all 30 dimension/pixel comparisons against preparation source 57bac829: 30 same dimensions, 29 pixel-identical images. Pixel counts are diagnostic, not a design score. Builder inspected the entire 30-image contact sheet plus full Home phone/desktop, scrolled phone and New thread desktop. The frozen R6-F comparison from the parent ledger remains applicable; these captures verify preservation after integration, not a new judge winner.

## Craft inspection

- Surfaces: the charcoal main sheet, raised decision/fleet rows and phone/desktop composer preserve the approved hierarchy; no extra decorative borders or clipping observed.
- Text: `contrast-region.json` measures exact opaque colours occurring in the first desktop decision region (x346, y195, 959×118). Primary text/panel 13.86:1, supporting text/panel 6.72:1, gold/panel 9.66:1, Answer text/gold 10.65:1; all exceed 4.5:1. The scoped contrast tests also retain the 3:1 identifying-shape floor. This region check is not a full-page accessibility claim.
- Controls/meaning: visible neutral keycaps and distinct SVG/word statuses remain; gold stays on Needs you, purple marks navigation/focus/live. Disabled Start retains its explanation. The observed native closed selects remain dark. New popup/OS/touch/screen-reader acceptance is not claimed.
- Honesty: separate fleet/inventory snapshot provenance, partial gap, listed-page scope, unknowns and uncertain delivery behavior are preserved; the API is never represented as cached/offline data.

## Hand-back boundary

R1's missing PWA and final integrated rendering/checks are now addressed by the merged D3, preservation checks, fresh captures and affected proofs. The dependency wait is satisfied; no unrelated hold, live approval or release authority is inferred. R2/R3 remain resolved as the review confirmed. Full PC CI and the Claude APPROVE must bind to the pushed head before merge; no merge, live account read/write, publish or phone installation has been performed. Design changelog remains staged/unassigned for Jake's shipping-version choice.
