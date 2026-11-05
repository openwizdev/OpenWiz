# Review correction: R2 and R3; R1 waits for D3

Review: PR #1063 comment 6678755159, CHANGES at db73b7056dd1c029df357d42375c1069c0b1ec76. User instruction: fix R2/R3 now; R1 waits for PR #1301's verified merge, then merge main again and finish integration.

Red proof commit: 310ac96d. `red-merge.log` records the App.tsx conflict with main; `red-rules.log` records all three missing Home descriptions in D2's rules. Both were committed before the fixes.

Implementation commit: 3f9bed4f89e09c43d373ff994630110021f8c0e8. Main merged: 61501bae3e62d3dec6995c5fd586734e3cc42bd4. Only conflicted file was App.tsx. Resolution retains Home's onHome handler and main's Sessions handler that clears selected thread/launcher before showing Sessions. Main's atomic withdrawal of Answer eligibility (#413) was incorporated without conflict, along with its regression proofs, the setup page/API/CSS, and current contracts. R6-F's Home composition remains; App.tsx now includes these newer behavior fixes instead of remaining byte-identical to the frozen source.

R3 changes only D2's desktop Views, four-phone-tabs and command-destination descriptions to put Home first. No redesign, new operation or token change. The rest of the D2 rewrite remains intact.

## Scoped verification at 3f9bed4f

- `git merge-tree --write-tree HEAD origin/main`: exit 0 against 61501bae (`green-merge.log`).
- The same three literal checks from the red run now pass (`green-rules.log`).
- `npm run typecheck`: PASS.
- `npm run check`: PASS, 37 source files.
- `CIRCLE_NODE_TOTAL=2 npm run build`: PASS; one worker, four static pages, including /setup.
- `node --test test/unit/home.test.ts test/unit/statusMark.test.ts test/unit/contrast.test.ts`: 10/10 PASS, zero skips (`targeted-unit.log`).
- `node --test --test-concurrency=1 test/browser/home.test.mjs test/browser/command-navigation.test.mjs test/browser/c5_answer.test.mjs`: 20/20 PASS, zero skips (`targeted-browser.log`). Three affected files only. Covers the retained phone-sheet close, Home navigation/lane/honesty, composer drafts/owner-press/focus and immediate target withdrawal/replacement safeguards.
- `cargo fmt --check`: PASS. No Rust crate changed by D4; no local clippy or full workspace/browser suites.
- `git diff --check origin/main...HEAD`: PASS; changed paths all under apps/web/ or exact approved changes/1030.md. A check against pre-merge HEAD also saw existing whitespace in main's unrelated private evidence; those inherited files were not edited.

No new helper. Existing policy reads were checked: merged AGENTS.md blob 2b9ae846b0dd4fcb93625ae1566b448f8de0e28a and fleet settings c4915e1d1ecfff15b933621b1d75a44012fd7741 were re-read; helpers and apps/web instructions remain unchanged. No new dependency, live call, STATUS.md edit, branch retarget or history rewrite.

## Still open

R1 remains open: PR #1301 was OPEN with no merge commit at the dependency check. This is an interim correction, not a final green hand-back or merge approval. After #1301 is verified merged, merge that main, retain shell-only caching/installability and D2, refresh the 390/1440 captures and comparison ledger on the integrated source, run affected checks, push for full PC CI, then reply/re-check on the final head. Historical 30 captures and CI on db73b705 remain preparation evidence only.

No background CI/review watcher, polling loop or sleep is left running. Further evidence-only pushes wait for a real CI/review fix. This revision is the specifically requested R2/R3 fix; push uses --no-verify after scoped checks under the standing hook ruling.
