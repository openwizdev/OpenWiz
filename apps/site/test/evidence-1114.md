# #1114 evidence

## Proof plan (before copy changes)

- Exact source text/link checks against independent approved literals prove the new Works today cards and their evidence classes/gaps, the combined changelog entry, and Now/Next direction. Existing browser checks independently verify rendered and hidden text on PC CI.
- The combined entry has an explicit pending publication date, no invented datetime, and precedes both unchanged historical entries.
- The static export remains exactly eight runtime files, byte for byte; installation commands stay unchanged.
- CI wiring: `npm run test:ci`. Release guards: `python3 tools/release/test.py`, with recording fake tools, never actual product/browser suites.
- `cargo fmt --check`; no Rust crate changes, so clippy does not apply.
- Per Jake's credits ruling, `npm test` and browser/full suites run on PC CI only. Hook remains installed; scoped equivalents are recorded before pushing with `--no-verify`.

## Red, before the HTML fix

Base: `f39d3bbdc2efb63b0fb35816011507ee9c1d8fcb`.
Command: `node --test apps/site/test/build.test.mjs` (exit 1).
The expected literals were updated from the release sources before either HTML page.

```text
✔ static export contains exactly the eight reviewed runtime files, byte for byte
✖ index.html: static release copy and links match the approved literals
  AssertionError: approved claim text, including hidden text
✖ changelog/index.html: static release copy and links match the approved literals
  AssertionError: approved claim text, including hidden text
✖ combined release keeps an explicit pending date and the two historical entries
  AssertionError: combined release has one addressable entry
ℹ tests 4
ℹ pass 1
ℹ fail 3
```

The first two failures show missing release/direction copy; the third shows the combined entry does not yet exist. Source guards also plant changed version text, a hidden claim, and a wrong link; each must be refused once the pages match.

## Sources read before copy changes

- `export/openwiz-0.0.5` at `14fab2616c07a3ae47eab8b4b993e449412bdcaf`: `README.md`, `CHANGELOG.md`.
- `export/openwiz-0.0.5-evidence` at `901b89b6440988ea50428f045f7d9006b9e2bcf3`: the private export claim check.
- Policy blob IDs: `AGENTS.md` `17ee4c0b592332348b7951003cbe281c7ba37302`; `apps/web/AGENTS.md` `088a3d7a269bc21196bbc42f7133625391622e80`; `docs/agents/fleet.md` `6d962f0c59f01b7a531077ae8d434531d6cd98e7`; `docs/agents/helpers.md` `48b1d35033f8b869a8d2038863d2e7dd3f8d6a74`.

## Helper

One spec tracer/scout on `f39d3bbdc2efb63b0fb35816011507ee9c1d8fcb`: 8 pointers checked against source; 8 used, 0 ignored, 0 wrong. Its palette warning informs the entry link/test index change. Its CI run: 3 passed. Archived before the check.

```text
clean #1114: nothing changed but the writes you named (branches 0, comments 2)
```

## Green and hand-back checks

Implementation commit: `77a08fa2190ebee829c58fb3e08086cda2013aa0`, tree `315a43e58626385d38f762a3f81af6a178fd8480`. The hand-back commit adds only this evidence. Commands below checked this implementation tree (the release suite completed after the implementation commit). Node 24.22.1; Rust 1.99.1/rustfmt installed after the initial `cargo: command not found` result.

| Command | Result |
| --- | --- |
| `npm --prefix apps/site run build` | PASS: 8 static runtime files |
| `node --test apps/site/test/build.test.mjs` | PASS: 4 tests; both exact copy/link checks, planted bad version/hidden claim/link, placeholder/history checks |
| `npm --prefix apps/site run test:ci` | PASS: 3 tests |
| `python3 tools/release/test.py` | PASS: 53 tests, 158.148 s; recording fake build tools, no live product/browser calls |
| `cargo fmt --check` | PASS after installing the pinned toolchain |
| `git diff --check` | PASS |
| `git merge-tree --write-tree HEAD origin/main` | PASS: no conflict with `be7ff062` |
| Owned-path and changelog-format checks | PASS: seven paths, required `changes/1114.md` format |

Supplemental source inspection compared the new changelog prose with the pinned export entry after stripping Markdown/HTML presentation; it matched exactly. Both historical entries, the hero, Building now and Install were compared with the base and remain byte-for-byte unchanged. The read-only qualifier now explicitly names 0.0.1 and 0.0.2. The new palette destination moves the browser test's second selection to 0.0.2 and Install to index 4.

`core.hooksPath` is `.githooks`; the hook stays installed. Per Jake's standing ruling, scoped equivalents above replace its workspace checks for this push, using `git push --no-verify`. No Rust crates changed: clippy is not applicable. Browser suites (`npm test`) and full required checks are reserved for PC CI; local results do not claim those passed.

Checklist review: claim classes/gaps retained, no unapproved dependency, no real session data or credentials, no changes outside owned paths, source guards reject planted violations, historical copy/commands retained. Other checklist categories concern product I/O/state/guards and do not apply to this copy change.

## Claim mapping and publication limits

| Site copy | Release source and evidence class |
| --- | --- |
| 0.0.3 Queue/Steer, operation records, uncertainty | README introduction / CHANGELOG item 1; claim-check C2–C3: fixture test |
| 0.0.3 PC release-blocking claims and combined-candidate limit | README LIVE-0.0.3 / CHANGELOG item 1; C5 and its L1/L6–L9 table: bounded live observation; busy-Cloud, network-cut, browser, access-path and identity gaps retained |
| 0.0.4 preview/create, local files/images, Queue/create attachments | CHANGELOG item 2; C6–C9: fixture tests; full live acceptance pending |
| 0.0.5 eight skills and exact-head matching merges | CHANGELOG item 3 / README fleet introduction; C12–C13, F5/F8: files, limited live observation and fixture helper checks |
| 0.0.5 discovery, holds, five-ready scale, cross-version timing, manual intervention | CHANGELOG item 3; F1–F7: gaps retained; no unattended-operation claim |
| Combined validation, quick Mac/Safari/real-radio/unattended gaps, no PACP claim | CHANGELOG validation paragraph; C14–C15/C19 and the public-placeholder limits |
| Staged status and pending date | CHANGELOG staged marker / C18 plus #1114's date-placeholder requirement; no publication claim |
| Fleets now; cockpit next | #1114 approved scope; explicitly “being built” / “directions”, no working-feature claim |

New Source/Testing links use the public repository's `main` destinations, to receive the release at Jake's publication step; those links do not establish current publication. Older evidence remains pinned to the historical public commit. Jake must review the `approved-copy.mjs` changes (only Works today, Now and Next, and the new combined entry/link expectations), final wording and date. The ticket's unassigned milestone question is on #1114; the required changelog line is present but assigned to no release. No deployment, public push, tag, release, live read or live write was performed.
