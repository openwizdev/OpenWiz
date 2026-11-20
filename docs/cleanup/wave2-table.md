# Cleanup wave 2: every large folder, its callers, and keep, fold, move or delete

CW2-0 (#1389) of spec #1388 writes this table for Jake's go. It is read-only:
nothing is deleted, folded or moved until Jake says go, and the wave's other
tickets are planned from the rows he approves.

- **Base:** OpenWiz `879c5daea0c3549eff7ae5914adc718005ce81c1` (`origin/main`
  at counting time). WizSkills `main` was
  `99016a51bfd7a84b3961aebaf6eb94410cbf668e`.
- **The repository:** 529,022 text lines at the base.
- **The wave:** 1 replace (50,739 lines out, at most 1,000 back), 1 fold
  (about 5,260 out), 3 moves (33,233 out) and 31 keep rows. That is about
  **88,200 lines out**. Once the running specs below are also done, the
  repository is about **269,200 lines: over the spec's 250,000 direction.**
  #979 keeps `tools/collector` (35,345) public in OpenWiz. The direction is met
  only if #979 also moves most of the collector out, which would give about
  233,800. See [Totals](#totals).
- **Not in this table** (already leaving through another spec):
  - AP11 (#1264): `apps/` (with `apps/web` and `apps/site`), `crates/server`,
    `crates/service`, `crates/store`, `tests/web-api` and `tests/service`.
  - The WizRoom move (#979): `tools/collector`, `tools/war-room` and
    `ci/wizroom` (wave 1 gave `ci/wizroom` to WizRoom too). #979 keeps
    `tools/collector` public in OpenWiz, so the projection in
    [Totals](#totals) counts it as staying.
  - The docs cleanup (#1293): `docs/evidence`.

## How to verify

One command lists every folder of 5,000 lines or more, with its lines and
files, counted recursively:

```sh
base=879c5daea0c3549eff7ae5914adc718005ce81c1
git grep -I -c '' "$base" -- . |
  awk -F: '{ n = $NF; t += n; c = split($2, a, "/"); d = ""
             for (i = 1; i < c; i++) { d = (d == "" ? a[i] : d "/" a[i]); L[d] += n; F[d]++ } }
       END { print t, "all"; for (d in L) if (L[d] >= 5000) printf "%d %d %s\n", L[d], F[d], d }' |
  sort -k3
```

- **Lines:** `git grep -c ''` counts every line of each tracked text file at the
  base. It counts blank lines and a last line with no newline. `-I` skips
  binary files. No tracked path contains `:`.
- **Files:** text files with at least one line. Empty files and binary files
  are not counted.
- **Lines** in a row are recursive: the folder and everything under it.
- **Own lines** are what the row decides. They are its lines minus its child
  rows and minus excluded folders inside it. So each line is counted once, and
  the totals add own lines.
- **Callers:** found with `git grep -n -F <folder>` at the base. The search
  covers `.github/workflows/`, `.github/actions/`, `.githooks/`, scripts in
  `ci/` and `tools/`, `Cargo.toml` and test targets, skills (`.claude/skills/`
  and WizSkills `main`) and Markdown. It excludes `docs/evidence`, `docs/cleanup`
  and the committed `ci/select/map.json`. Those name paths as history or data,
  not as callers.
  - A **caller** runs, imports, loads or links the folder.
  - A path filter alone counts as a trigger, not a caller, and is marked as one.
  - `.githooks/pre-push` runs only `tools/privacy-check/hook.py`. So no row
    except `tools` has a hook caller.
- **AP11's share:** joins `docs/cleanup/app-table.md`'s delete and fold rows to
  the files still at the base. AP11's delete rows still match 131,931 lines.

## Words

| Word | Meaning here |
| --- | --- |
| **Keep** | The folder stays. Smaller cuts inside it belong to the spec named in **Collides with**, or to a later wave. |
| **Fold** | The content stays in OpenWiz in a much smaller form. The row names that form. |
| **Move** | The folder leaves OpenWiz for the named repository and path. The row lists the callers to repoint first. |
| **Delete** | The folder goes. **Replace** is a delete that also adds a small successor, with a stated line budget. |
| **Collides with** | A running spec that owns, edits or relies on paths in the row. It is never a gate. It says what to sequence. |

## The table

Lines and files are recursive. **Own** is what the row decides, as explained in
[How to verify](#how-to-verify).

### CI

| Folder | Lines | Files | Own | Callers | Call | Reason | Destination | Collides with |
| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| `.github` | 6,413 | 33 | 6,413 | GitHub Actions runs `workflows/*.yml`. `ci.yml` uses `actions/docs-only` and `actions/docs-only/setup`. `changelog.yml` uses `actions/changelog`. The `export-review` skill and the wave 1 tables name it. No hook caller. | **keep** | This is CI itself. The `ci/select` row shrinks it: the trace, sign and plant code goes from `actions/docs-only/run.py`, `plan.py`, `test_plan.py`, `test_workflow.py`, `test_execution.py` (it imports `ci/select/test_trace` and asserts the `always` lane runs the four `ci/select` tests) and `test.sh` (line 853 fakes `ci/select/trace.py`), and the `select-map` job goes from `ci.yml`. | — | FF5 #1335 (owns `ci.yml` run conditions); #979 (`war-room.yml`, `war-room-proof.yml` leave); AP11 (web jobs) |
| `ci` | 66,792 | 196 | 6,679 | Own lines: `main-batch` (2,312), `escapes` (1,790), `shard` (1,519), `hosted` (540), `runner` (84), `retry.sh` and `rust-tests.sh` (434). Their callers: `ci.yml` (`main-batch/shadow.py capture`, `shard/shard.py share` and `shard/test.py`). `actions/docs-only` (`run.py` runs the `release:ci2-*` units, `hosted/test.sh` and `rust-tests.sh`; `gate.py` imports `escapes`; `setup/action.yml` runs `hosted/guard.sh`, `hosted/setup.sh` and `runner/cache.sh`; `decide.sh` and `plan.py` run `retry.sh`). `ci-escapes.yml` runs `escapes`. | **keep** | All of it runs in CI today. `escapes` finds tests a merged plan skipped that then failed on `main`. That stays useful with path-based selection. `ci/wizroom` (1,565) is excluded as #979's. | — | FF5 #1335 (reads the plan these read); #979 (`ci/wizroom`) |
| `ci/select` | 50,739 | 16 | 50,739 | `actions/docs-only/action.yml` (`job.py traces`, `select`, `validate`). `actions/docs-only/plan.py` (imports `job`; checks for `map.json`). `actions/docs-only/run.py` (runs `trace.py`, `planted.py` and the four `test_*.py` files in the `always` lane). `actions/docs-only/test_execution.py` (imports `ci/select/test_trace`, lines 71-73; asserts that the `always` lane runs `test_pick.py`, `test_trace.py`, `test_job.py` and `test_steps.py`, lines 152-153). `actions/docs-only/test.sh:853` (fakes `ci/select/trace.py`). `ci.yml#select-map` (`map.py`, `job.py sign`) and `ci.yml#changes` (imports `ci/select`). `tools/open-import/paths.json`. Docs: `contracts/ci-selection.v1.md` and `ci/escapes/README.md`. | **replace** with path-based selection | 47,281 of its lines are `map.json`. That file is a committed copy of one traced map. Per its own README, CI never selects from it. Only `test_pick.py` reads it, and `planted.py` checks that it exists. The other 3,458 lines are the tracer, resolver, signed-map build and checks. FF5's open PR #1391 grows them (`resolve.py` maps Rust tests through `.d` files and rlibs; `pick.py` gains rule 9), so the replacement deletes more than is counted here. Before the delete, the replacement must also edit `actions/docs-only/test_execution.py` and `test.sh`, or the `always` lane fails on every pull request. `classify.sh`'s path table (in `.github/actions/docs-only/`) already decides jobs by path. The replacement extends that table to lanes and test ids, with a budget of 1,000 lines including tests. See [What FF5 needs](#what-ff5-1335-needs-from-path-based-selection). | — | **FF5 #1335** (owns `ci/select/`; PR #1391 open, after the base) |
| `ci/selection` | 7,809 | 85 | 2,249 | These are the fixtures of `contracts/ci-selection.v1.md`. `valid/` and `reads/` are read by `actions/docs-only/test_gate.py`, `test_lanes.py` and `test_execution.py`, by `ci/escapes/test.py` and `escapes.py`, by `ci/shard/test.py` and by `ci/select/test_steps.py`. `ci-escapes.yml` has a trigger (path filter only). `tools/open-import/paths.json` lists them. | **keep** | The plan record stays with path-based selection. Lanes, `shard`, `gate` and `escapes` read it. | — | FF5 #1335 (relies on `contracts/ci-selection.v1.md`) |
| `ci/selection/invalid` | 5,560 | 54 | 5,560 | `ci/escapes/test.py` reads every file, with each refusal reason from `ci/selection/README.md`. Line 503 also loads `test-twice.json`. `ci/shard/test.py` (lines 28, 103, 166, 180) loads `test-twice.json`, `duplicate-key.json` and `rust-test-unknown-kind.json` by name. `ci/selection/reads/plan-refused.json:17` names `invalid/test-twice.json`. | **fold** | Each file is a full valid plan with one defect. For example, `test-twice.json` is `valid/selected-mixed.json` with one test added twice. Fold the 54 files into one table: a valid base, then one edit and one reason per case, about 300 lines. Every case and every refusal reason stays. `duplicate-key.json` (rule 1) can't be a parsed base plus one edit, so it stays as raw text. The readers in `ci/shard/test.py` and `reads/plan-refused.json` are repointed in the same change. | — | FF5 #1335 (contract fixtures) |

### Contracts and docs

| Folder | Lines | Files | Own | Callers | Call | Reason | Destination | Collides with |
| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| `contracts` | 31,741 | 134 | 31,741 | These are the product's public records. They are read by `crates/*`, `tests/*` schema checks, `tools/install`, `tools/release`, `tools/wizskills` and `tools/github-app`. Docs: `AGENTS.md`, `README.md`, `STATUS.md` and `GLOSSARY.md`. Skills: `export-review`. | **keep** | The kernel's rules live here. AP11 already deletes `cockpit.v1.*` and `web-api.v1.md` (1,731 lines). `wizroom.v1.md` and `review-loops.v1.md` and `v2.md` are read only by `tools/war-room` and `STATUS.md`, so #979's split checker decides where they go. | — | AP11 (1,731 lines); #1365 KN1 (records v1, PR #1387 open); #979 (`wizroom.v1.md`, `review-loops.*`) |
| `docs` | 18,743 | 291 | 5,640 | Own lines: `cleanup` (these tables, 2,229), `agents` (fleet settings read by the fleet skills and `crates/cli`'s fleet planner, 1,341), top-level guides (1,139), `adr`, `decisions`, `spikes`, `security`, `live-checks` and `brand`. Linked from `AGENTS.md` and `README.md`. | **keep** | #1293 already rules on every Markdown file here, file by file. A second table would fight it. `docs/evidence` (13,103) is excluded as #1293's. | — | #1293 |

### Crates (the product)

| Folder | Lines | Files | Own | Callers | Call | Reason | Destination | Collides with |
| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| `crates` | 75,554 | 183 | 0 | Workspace `Cargo.toml` | **keep** | This is only a parent. Every line is in a child row or an AP11 folder (`server`, `service`, `store`: 25,410). | — | AP11 |
| `crates/adapters` | 18,317 | 27 | 0 | Workspace `Cargo.toml` | **keep** | This is only a parent. | — | #1365 (drivers live in `adapters/`) |
| `crates/adapters/cloudroom` | 9,651 | 13 | 280 | Workspace `Cargo.toml` and `crates/cli`'s dependency. `tests/fixtures/room-cli-v127` and `crates/adapters/cloudroom/tests`. | **keep** | Kernel: this is the Cloudroom driver. AP11 keeps it whole. | — | #1365 (Cloudroom driver) |
| `crates/adapters/cloudroom/src` | 9,371 | 11 | 9,371 | `crates/cli` and `crates/core` call sites. `tests/cli-agent` loop tests. | **keep** | As its parent. | — | #1365 |
| `crates/adapters/github` | 8,666 | 14 | 17 | Workspace `Cargo.toml` and `crates/cli`'s dependency | **keep** | Kernel: the GitHub reader. `plan.rs` builds `contracts/plan.v1`. | — | #1365 (records v1 reads) |
| `crates/adapters/github/src` | 8,649 | 13 | 8,649 | `crates/cli` (`fleet`, `github token`). `tests/fleet` and `tests/cli-agent`. | **keep** | As its parent. | — | #1365 |
| `crates/cli` | 9,903 | 24 | 120 | Workspace `Cargo.toml`. `packages.yml` and `tools/release/build_products.py` build the `openwiz` binary. The WizSkills `install` skill runs it. | **keep** | Kernel: the command. | — | AP11 (deletes 2,368 lines of `src`); #1365 |
| `crates/cli/src` | 9,783 | 22 | 9,783 | As its parent. `tests/cli-agent` and `tests/fleet` run the binary. | **keep** | As its parent. | — | AP11; #1365 |
| `crates/core` | 21,924 | 63 | 4,118 | Workspace `Cargo.toml`. `crates/cli` and both adapters depend on it. Own lines are `tests/` (1,249) and the crate's non-`src` files. | **keep** | Kernel: the engine. | — | AP11; #1365 |
| `crates/core/src` | 17,806 | 43 | 10,686 | As its parent | **keep** | Kernel. AP11 deletes `notifications` and `messaging/lookup.rs` (1,138 lines). | — | AP11 (1,138 lines); #1365 |
| `crates/core/src/fleet` | 7,120 | 11 | 7,120 | `crates/cli` (`fleet`, `fleet due`, `fleet tick`). `tests/fleet`. `contracts/fleet.v1.md` and `fleet-tick.v1.md`. | **keep** | Kernel: the fleet planner. | — | #1365 |

### Tests

| Folder | Lines | Files | Own | Callers | Call | Reason | Destination | Collides with |
| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| `tests` | 121,226 | 460 | 8,743 | `tests/Cargo.toml` (`openwiz-tests`, 13 `[[test]]` targets). `ci/rust-tests.sh`, run by `actions/docs-only/run.py`. | **keep** | Own lines are `attachments`, `loops`, `support`, the fakes and small targets. AP11 deletes `attachments` (2,931), `loops` (739) and the send pieces. Wave 1 (#1145, #1160) already cut these groups under the bolder rule. `web-api` and `service` (37,777) are excluded as AP11's. | — | AP11 |
| `tests/checks` | 5,595 | 14 | 5,595 | `[[test]] checks`, always run (`run.py`'s `always` lane). `AGENTS.md`, contracts' "checked by" lines. | **keep** | These are the repository's safety checks: fixture privacy scan, schema conformance and plan links. | — | AP11 (`cockpit_schema_conformance.rs`, a kept-caller edit) |
| `tests/cli-agent` | 7,122 | 12 | 7,122 | `[[test]] cli-agent`. `docs/agents/fleet.md`. | **keep** | Proves the command's agent surface: loops, `github token` and process. | — | none |
| `tests/fixtures` | 17,691 | 165 | 12,226 | `tests/proof`, `tests/messaging`, `tests/new-thread`, `tests/fleet` and `tests/checks/fixture_scan.rs`. `crates/adapters/cloudroom/tests` (`room-cli-v127`). `tools/release` (`release/`). `tools/install/tests/first-hour` (`first-hour/`). `tools/live-smoke`. | **keep** | Kept tests read them. `tools/test-value/unread_fixtures.py` already guards against unread fixtures, and #1160 deleted 14 of them today. | — | AP11 (web-only fixtures) |
| `tests/fixtures/room-cli-0.43.1` | 5,465 | 99 | 5,465 | `tests/proof/support.rs` and the P1, P2, P4, P4b, P7 and P12 tests. `tests/messaging/support.rs`, `tests/cli-agent/process.rs`, `tests/checks/fixture_scan.rs` and `tools/live-smoke/test_fixture.py`. | **keep** | Kept proofs read it. When AP11 removes `tests/messaging`, it removes one reader, not all of them. | — | AP11 (one reader) |
| `tests/fleet` | 18,710 | 51 | 18,710 | `[[test]] fleet`. `contracts/fleet.v1.md` and `fleet-tick.v1.md`. | **keep** | This is the engine's proof, and the engine is the kernel. | — | #1365 |
| `tests/messaging` | 9,312 | 22 | 9,312 | `[[test]] messaging` | **keep** (AP11's rows decide) | AP11 deletes 7,873 lines and keeps 1,439. | — | AP11 |
| `tests/new-thread` | 9,042 | 33 | 9,042 | `[[test]] new-thread` | **keep** (AP11's rows decide) | AP11 deletes 5,051 lines and keeps 3,991. | — | AP11 |
| `tests/proof` | 7,234 | 15 | 7,234 | `[[test]] proof`. `AGENTS.md` and `docs/agents/huntr.md`. | **keep** | The 0.0.1 proof cases, cut by #1145 today. One pending case remains. | — | none |

### Tools

| Folder | Lines | Files | Own | Callers | Call | Reason | Destination | Collides with |
| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| `tools` | 152,386 | 770 | 20,647 | Own lines are tools of under 5,000 lines each: `live-smoke`, `github-app`, `fleet-load`, `open-import` (`ci.yml` carriage guard), `privacy-check` (`.githooks/pre-push`, `privacy.yml`), `stall-alarm`, `roadmap`, `wizskills` (`war-room-proof.yml`, `tools/release`) and `ci-overload`. | **keep** | Each one is under this wave's 5,000-line bar, so none is judged here. `collector` and `war-room` (60,370) are excluded as #979's. | — | #979 (`stall-alarm`, `ci-overload` and `privacy-check` consume its public layer) |
| `tools/install` | 22,618 | 70 | 9,588 | `actions/docs-only/run.py` runs the `release:install`, `release:pull` and `release:setup-api` units. `classify.sh`. The WizSkills `install` skill runs `tools/install/install` (`preflight`, `download`, `install`, `open`). `contracts/install.v1.md` and `setup-onboard.v1.md`. | **keep** | Product: the installer and setup. | — | AP11 (setup API route, kept-caller edits) |
| `tools/install/tests` | 13,030 | 31 | 8,022 | `run.py` runs `release:security-baseline`, `release:security-candidate`, `release:setup-onboard-init` and `release:setup-onboard-journey`. `first-hour-contract/check.py` imports `tools/skills-eval/records.py`. | **keep** | These protect the install and first-hour release gates. | — | the `tools/skills-eval` move (one import to repoint) |
| `tools/install/tests/setup-onboard-contract` | 5,008 | 3 | 5,008 | `run.py` runs `release:setup-onboard-contract` (`test_contract.py`). `contracts/setup-onboard.v1.md`. | **keep** | This is the setup-onboard contract's case set. 4,212 lines are one `cases.json`. | — | none |
| `tools/release` | 13,979 | 27 | 13,979 | `packages.yml` runs `product_identity.py`, `build_products.py` and `package.py`. `run.py` runs the `release:test`, `release:package` and `release:product-identity` units. `classify.sh`. The `export-review` skill. `RELEASING.md` and `changes/README.md`. | **keep** | Product: packaging and release. | — | AP11 (kept-caller edits C6, C9) |
| `tools/skills-eval` | 19,721 | 119 | 7,601 | No CI workflow or `run.py` unit runs its tests. `war-room-proof.yml` has only a trigger (path filter). **OpenWiz loads it (to repoint before the move):** `tools/collector/sources.py:475` loads `records.py` at run time, on the war room's preview and publish path (`war-room.yml`), and `trends_reads.py:33` reads its `openwiz.skills-eval.score.v1` score. The collector's tests load it too: `test_ci3.py:742` (`records.py`), `test_journey.py:661` (`fakeworld.py`) and `test_experiment_contract.py:20` (`replay/contract-fixtures`). Also `tools/war-room/experiments` (`precheck`, `replay` fixtures), `ci/wizroom/test_split.py` and `tools/install/tests/first-hour-contract/check.py` (`records.py`). **It loads OpenWiz back:** `precheck/test_contract.py:23,160-161` loads `tools/collector/experiment_contract.py` and two collector fixtures (`bottlenecks-contract/accepted.json`, `journey/journeys.json`). `weekly/run.py:369` puts `tools/collector` on `sys.path`. `eval.py:91,272` and `weekly/collect.py:40` read `contracts/decisions.v1.schema.json`. Docs: `docs/agents/skills-eval.md` (the weekly loop's runbook), `tools/collector/collector.v1.md` and `journey-contract.md`. Skills: none in OpenWiz; WizSkills names it only in `review-ticket/evidence/ws6.md`. | **move** | It evaluates WizSkills' skills, with their text, cases and paid runs, so it belongs beside WizSkills' `tools/measure`. The coupling runs both ways, because #979 keeps the collector in OpenWiz. Repoint both directions before OpenWiz deletes its copy. (1) OpenWiz reads it from the pinned WizSkills release: `tools/wizskills/install.py` already installs that release into `.wizskills/`, and both war room workflows already run it. So `sources.py`, the collector tests and `war-room/experiments` load `.wizskills/tools/skills-eval/...`, and `first-hour-contract/check.py` gets a copy of the `records.py` validator in `tools/install`. (2) WizSkills reads the collector's `experiment_contract.py`, its two fixtures and `contracts/decisions.v1.schema.json` from an OpenWiz checkout at a pinned commit, passed in by path, never by a sibling-folder path. If either side can't be repointed, the call becomes **keep**. | WizSkills `tools/skills-eval/` | **#979** (the collector stays in OpenWiz and loads it on the publish path; #979's WM-P2 needs its suites unchanged at step 0, so move after step 0) |
| `tools/skills-eval/cases` | 12,120 | 89 | 12,120 | `tools/skills-eval/eval.py` and `cases.py` | **move** | The eval's synthetic cases. | WizSkills `tools/skills-eval/cases/` | as its parent |
| `tools/test-value` | 15,051 | 152 | 1,539 | `ci.yml#always` runs `test_budget.py` and `budget.py` (the PR test-code budget). `run.py` runs the `release:test-value` (`test_measure.py`) and `release:test-value-unread-fixtures` units. | **keep** | The budget guard and the unread-fixture check run in CI. | — | none |
| `tools/test-value/evidence` | 13,512 | 144 | 13,512 | No code reads it. Only `tests/checks/skills.rs:4` links to it (a comment, `tv12/ledger.md`). The evidence's own `cw11/coverage.py` is campaign evidence, not a caller. | **move** | These are ledgers and logs of finished test-value passes, so they are private records and the product doesn't need them. 6,357 of its lines are Markdown that #1293 already moves (32 rows). The other 7,155 (JSON, text, patches, logs) go with them. | ClosedWiz `private/openwiz-docs/tools/test-value/evidence/` (#1293's rule) | **#1293** (its 32 move rows; repoint `tests/checks/skills.rs:4` first) |

## What FF5 (#1335) needs from path-based selection

FF5 had no branch at the base. Its PR #1391 opened after it, and it grows the
tracer and resolver: `resolve.py` maps Rust tests through `.d` files and rlibs,
and `pick.py` adds rule 9, under which a new doc or skill that no test reads
reaches no test, while "a doc a Rust test reads still runs it". It owns `ci/select/`
and, in `.github/workflows/ci.yml`, only the jobs' run conditions. Its third
criterion keeps "main-push tracing and signing of the selection map"
unchanged, but this row deletes that tracing and signing. So **FF5 lands first,
as it is approved, and the replacement ticket is blocked by FF5**. The
replacement's acceptance tests are FF5's rules, carried over. Selection by path
must give FF5:

1. **Skip rules by path class.** A change that is only docs, only skills or
   only site skips the `rust` and `web` lanes in pull-request selection,
   unless a test reads the changed file.
   - Today `classify.sh` sends `docs/.+`, `GLOSSARY.md` and every skills folder
     to `rust`, because Rust tests read some of them. For example,
     `tests/checks` reads skills, and PR #1391's planted case reads
     `docs/agents/fleet.md`.
   - So the path table must name **test ids** as well as lanes. A doc or
     skill path selects every Rust test that reads it (its readers are named
     in the table), and only those. It never selects the whole `rust` lane. A
     doc no test reads selects nothing, which is #1391's rule 9.
   - `rust:test:checks` stays always-run.
2. **A planted case per skip rule.** For each rule there is one planted edit
   that its catcher must still select, as `ci/select/planted.py`'s `CASES`
   do today (CI3's anti-gaming rule). The replacement keeps a `planted` check
   with no tracer: it plants each edit and asserts the selected ids include
   the catcher.
3. **Only one case narrows.** Pushes to `main`, the nightly run, merge groups,
   reruns, `release-*` and stale events run everything. This is `decide.sh`'s
   plain case, unchanged. An unknown path, or any CI or toolchain path, also
   runs everything.
4. **The old web view's export runs when `apps/web/**` changes,** until AP11
   deletes it.
5. **The same plan record.** The output is still an `openwiz.ci-selection.v1`
   record (`contracts/ci-selection.v1.md`), with lanes, skips with reasons and
   the same test ids. `run.py`, `shard`, `gate` and `escapes` read it without
   change.
6. **The timing record stays.** Each job's time per head (`ci3.v1`) has
   nothing to do with the selector. The replacement must not drop it.
7. **The budget rows change.** The CI budget rows (#782, #1097) change for the
   `select-map` job, which the replacement removes.

FF5's other criteria (its test rule, keepers for deleted tests) apply to the
replacement unchanged.

## Totals

Own lines, at the base.

| Call | Rows | Own lines | Lines out of OpenWiz |
| --- | ---: | ---: | ---: |
| keep | 31 | 245,098 | 0 |
| replace (`ci/select`) | 1 | 50,739 | about 49,700 (50,739 out, at most 1,000 back) |
| fold (`ci/selection/invalid`) | 1 | 5,560 | about 5,260 |
| move (`tools/skills-eval` to WizSkills, `tools/test-value/evidence` to ClosedWiz) | 3 | 33,233 | 33,233 |
| **all rows** | **36** | **334,630** | **about 88,200** |

The rows cover every line, once:

| Lines | What |
| ---: | --- |
| 529,022 | the repository |
| − 114,289 | AP11's folders: `apps` 51,102, `crates/server` 10,102, `crates/service` 7,928, `crates/store` 7,380, `tests/web-api` 20,516, `tests/service` 17,261 |
| − 61,935 | #979's folders: `tools/collector` 35,345, `tools/war-room` 25,025, `ci/wizroom` 1,565 |
| − 13,103 | #1293's `docs/evidence` |
| − 5,065 | in no folder of 5,000 lines: root files 1,253, `release` 1,937, `changes` 1,045, `.claude` 318, `deploy` 259, `loops` 140, `.githooks` 113 |
| **= 334,630** | the rows' own lines |

The line count the repository would reach:

| Step | Lines out | Repository |
| --- | ---: | ---: |
| At the base | | 529,022 |
| AP11 (#1264): its delete rows that still match files | 131,931 | 397,091 |
| WizRoom (#979): `tools/war-room`, `ci/wizroom` (`tools/collector` stays public) | 26,590 | 370,501 |
| Docs cleanup (#1293): `docs/evidence` | 13,103 | 357,398 |
| **This wave** | about 88,200 | **about 269,200** |

**About 269,200 is over the spec's 250,000 direction.** The direction is met
only if #979 also moves most of `tools/collector` (35,345) out of OpenWiz. That
would give about 233,800. This wave alone can't reach 250,000: every other
large folder left is the kernel, its tests, its contracts, or the installer
and release tools.

Each figure is a bound:

- `tools/collector` is counted as staying whole. Anything #979 moves out of
  it lowers the count.
- #1293's other Markdown moves outside `docs/evidence` are not counted, except
  the `tools/test-value/evidence` Markdown, which this wave counts once in its
  move row. Those moves would lower the count further.
- AP11's fold rows move lines within OpenWiz, so they are not counted as
  removed.

## Order after Jake's go

1. `tools/test-value/evidence` move: with #1293's DS move of the same folder,
   or right after it.
2. `ci/selection/invalid` fold: any time. It touches the fixtures,
   `ci/escapes/test.py`, `ci/shard/test.py` and
   `ci/selection/reads/plan-refused.json`.
3. `ci/select` replace: blocked by FF5 (#1335).
4. `tools/skills-eval` move: blocked by #979's step 0. First the WizSkills
   pull request lands, reading OpenWiz at a pinned commit. Then OpenWiz
   repoints the collector, `war-room/experiments` and `first-hour-contract`
   to `.wizskills/`. Then OpenWiz deletes its copy.
