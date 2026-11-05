# D4 adoption proof plan

Latest integration: [R1 final Home + D2 + D3 record](review-2/README.md), source `f29618b9323db492c844741ab06237c03f8ffe66`. Both prerequisites are verified merged; fresh 30 captures and 38 affected tests pass. PC CI and Claude exact-head review remain required. Earlier sections below preserve historical preparation evidence.

Frozen winner: R6-F, source `0f55ce87db42abb1f8391818d481f1e429d6aee3`, source branch `room/design-hill-climb-2`. The final report is retained in the private evidence record at `87aa0f69`. Adopt its delta from M6 `85d20b5101ab3b56fbf9997468db28df3fc2c727`; retain newer D1 fixes on main. No competing climb.

| Claim | Proof and evidence class |
| --- | --- |
| Exact final winner adopted; prior D1 corrections retained | Integration diff against the two named commits; independent helper pointers checked by builder; source review |
| Numbered decisions precede fleets, then active listed sessions; Answer uses the existing composer and owner press | Adopted `test/browser/home.test.mjs` fixtures in PC CI; new focused `test/unit/home.test.ts` public render proofs locally |
| Observatory shell, command navigation, tokens, icon/shape/word, and truthful unknowns | Existing statusMark proofs and focused Home render proofs locally; adopted browser proofs in PC CI; synthetic screenshot comparison |
| D2/PWA integration retained | Confirmed integration wait: D2 and D3 remain held under release freeze; verify both before final integration, captures, CI and review. Current main has no PWA. No installability claim |
| Final integrated Home, Answer, live reading and designed states at 390/1440 | Real browser captures on synthetic DEMO fixtures, comparison with frozen R6-F and original H0/M6; rendering evidence only |
| No behavior regression | Affected checks locally; all three PC CI checks on exact PR head. Claude exact-head review by fleet; no live acceptance claim |

Credits rule: no full local workspace/browser suites. No Rust crate is touched, so only `cargo fmt --check` applies locally. Existing original climb red logs and ledger remain immutable on the source branch; new render proofs are committed red before adoption. Evidence here is synthetic only.

## Results at integrated source 57bac829fb808e6ca27edb586ab8080804349b67

- `npm ci --ignore-scripts`: pass; locked dependencies unchanged, zero audit findings.
- `npm run typecheck`, `npm run check`: pass (36 source files).
- `CIRCLE_NODE_TOTAL=2 npm run build`: pass, one worker, three static pages.
- `cargo fmt --check`: pass on Rust 1.99.1. No Rust crates touched; no local clippy/build/workspace tests required by Jake's credits rule.
- `node --test test/unit/home.test.ts test/unit/statusMark.test.ts`: 7/7 pass, zero skips. See `green-render.log`. `red-home.log` records the pre-adoption missing HomeLive seam. The first post-adoption run passed both Live tests and exposed two mistakes in the newly drafted test selectors/fixture path; those expectations were corrected to the existing public markup/schema, with no product fix.
- `node --test --test-concurrency=1 test/browser/home.test.mjs test/browser/command-navigation.test.mjs`: 7/7 pass, zero skips, about 12 seconds. This is two affected files, not the full browser suite. See `targeted-browser.log`.
- `node test/design-screens.mjs docs/evidence/1030/shots home,home-live,home-answer,home-loading,home-empty,home-error,home-stale,sessions,thread,new-thread,fleets,fleet-detail,loading,empty,error`: 30/30 captures, no page errors or horizontal overflow. Both 390×844 and 1440×900; real rendered pages on synthetic DEMO fixtures, no live accounts. See `shots/capture.json`.

`adoption.json` pins the source hashes. All seven winner product files match R6-F byte for byte except Fleets.tsx, whose only difference preserves D1's state-specific `shape={marker.kind}`. Other D1 status and timestamp corrections remain intact. Capture integration preserves current main's event-based waits, loading state, DEMO label, error/overflow failures; it adds the winner's modal viewport and scroll recording, and explicit Home loading/empty/error/stale fixtures. No new package, route, write, approval action, storage, data contract or shared token value.

## Integration ledger: R6-F retained

This is a preservation comparison, not a new climb or a claim of a new judge winner. The original report and all comparisons remain untouched on the source branch:

- Frozen final report: retained privately at `87aa0f69`.
- Original ledger, round comparisons and R6-F screenshots: retained privately at `0f55ce87db42abb1f8391818d481f1e429d6aee3`.
- Original H0 red logs and foundation captures: retained privately at that same source commit.

| Integrated capture, each phone + desktop | Comparison / source review |
| --- | --- |
| `shots/home/` | Compared directly with original R6-F PNGs: same hierarchy, two numbered decisions, paired desktop fleet cards and both active sessions; same 390×1112 full-page phone composition. D1 now distinguishes needs_info and blocked shapes and displays seconds in the read chip. DEMO label added by capture only. Retain R6-F. |
| `shots/home-live/` | The real scrolled phone viewport shows Live now, provenance, gap, and both live rows above fixed tabs. The full-page phone shot honestly retains fixed-tab overdraw at the initial viewport edge; no content was hidden or truncated. |
| `shots/home-answer/` | One existing composer, ticket/spec prefix, retained source context and owner-press Queue/Steer. Phone modal is viewport-only, explicitly recorded; desktop retains adjacent Home. |
| `shots/home-loading/`, `home-empty/` | Loading says reading, with no false zero. Fresh zero distinguishes Nothing needs you, No fleets and No active sessions. Existing M6 shell treatment retained. |
| `shots/home/`, `home-stale/` | Partial inventory retains its gap and scope. Failed subsequent reads retain both snapshots and rows, with explicit errors, last-good times and stale cues. No false complete/live claim. |
| `shots/home-error/` | Both initial source failures remain explicit, with no invented snapshot, empty claim or decisions. Existing neutral error icon and Retry retained. |
| `shots/sessions/`, `thread/`, `new-thread/`, `fleets/`, `fleet-detail/`, `loading/`, `empty/`, `error/` | Contact-sheet review retains M6's sheet, companion/modal behavior, shared typography, status words/shapes and existing content; only Home navigation is added. Existing fixture detail orchestrator remains absent. |

The builder inspected the complete 30-image contact sheet plus full-size Home phone/desktop, scrolled phone, Answer phone and Home-state phone captures. Screenshot evidence proves rendering only. No greyscale image manipulation, live screen-reader/touch acceptance, installation or PWA behavior is claimed.

## Helper and checklist

One Cloud fast Codex Terra High scout/checklist helper at `b4cf669fb337d6f992cf63edfe88164b8c4a1eea`: four pointers used, zero ignored/wrong. Builder independently checked all four against Git: preserve D1 shape prop, capture event waits/loading, DEMO/error checks and browser-clock fix; synthetic fixture inputs unchanged. Archived after report. Swarm check: `clean #1030: nothing changed but the writes you named (branches 0, comments 4)`.

Applicable checklist items hold: no new outside-input reader/guard/write/retry policy; fixtures and requests remain synthetic; public render and adopted browser proofs assert exact rows and preserve the owner-press gate; source cache/lane and draft/focus behavior covered by the targeted Home proof; original red provenance retained and new red committed before adoption. No private files are read by the new tests or capture runner, and no dependency changes. Owned paths checked before each commit. Full PC CI and exact-head Claude review remain pending; final hand-back and merge wait for the confirmed D2/PWA integration below.

The repo hook is installed. Its broad local workspace clippy/static commands are superseded by Jake's targeted-only credits rule for this web-only change; push uses the already completed applicable fmt/typecheck/static safeguards and lets PC CI run the full set.

Final test-only tightening: the partial-zero render proof now constructs a fixture accepted by `readFleets` (GitHub version read failed, known empty decisions), rather than mutating the already-read model, and fixes its time zone to UTC. `node --test test/unit/home.test.ts`: 4/4 pass, zero skips (`green-home-final.log`). Product source and captures remain identical to `57bac829`.

PC checkpoint: changelog run `41955915306` refused at `ff82dd02`: `product change needs changes/<ticket>.md or the reviewed no-changelog label`. This is the already-open ownership question, not grounds for exempting the product change. CI run `41955915320` was still running when this test-only follow-up was prepared.

## Approved changelog and integration wait

[Ops answer on #1030](https://github.com/jparker2006/ClosedWiz/issues/1030#issuecomment-6648163473) adds exactly `changes/1030.md` to D4 ownership. Its `kind: changed` sentence is bounded by synthetic evidence. The ticket retains the Design milestone; the line is staged/unassigned, following D1. Jake chooses the shipping version later. No version field or release claim is added; STATUS.md remains orchestrator-owned.

The same answer confirms that preparation may continue, while final green hand-back and merge wait for both D2 (#1028) and D3 (#1029) to land or be incorporated. Both are still open and held. The fleet has recorded a structured wait for #1029; after its verified merge, also verify #1028 before final integration, fresh 390/1440 captures, PC CI and Claude exact-head review. This preparation does not implement either held ticket or waive D4 acceptance. Current captures remain preparation evidence at the named source, not final post-PWA evidence.

On resume, policy blob IDs were checked before reuse; unchanged AGENTS.md/fleet/helpers reads were reused and apps/web/AGENTS.md was read. The only new product input is the changelog line: validate its exact format/content, run cargo fmt --check, and push for PC CI. No Rust crates or runtime web files changed, so no local clippy or repeated app/browser suites are needed for this follow-up.

## Review correction R2/R3

[Review-1 correction record](review-1/README.md): main 61501bae is incorporated at 3f9bed4f, preserving the Sessions close-sheet and atomic Answer-target withdrawal fixes; D2's Views/tabs/command descriptions now include Home. Ten focused unit tests and twenty tests in three affected browser files pass, alongside typecheck/static/capped build/fmt. The historical source-equivalence manifest and screenshots above remain bound to their original preparation source. R1 still waits for PR #1301; final integrated captures, full PC CI and exact-head review remain required after that merge. No final green hand-back yet.
