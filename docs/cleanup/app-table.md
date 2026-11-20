# Keep, fold or delete: the web view, site copy, server, service and store

AP9 (#1262) of spec #1223 writes this table for AP10 (#1263): Jake reads it and
says go, or names rows to change. Changed rows go back to AP9's builder before
AP11 (#1264) starts. AP11 does exactly the approved delete and fold rows, edits
the kept callers listed below and records the lines it removed in
[Totals](#totals). Until Jake's go, this table deletes nothing.

- **Base:** OpenWiz `e817c9a293f4317d210a13e8821bb7377fdbef5c` (`origin/main` at
  inventory time). WizSite `main` was `333bbb8078a3d6337fd0649c8536f42d30f106d4`.
- **649 files, one row each:** 560 delete (131,937 lines), 22 fold (5,176 lines)
  and 67 keep (25,287 lines). The [Totals](#totals) table splits them by part.
- **Order:** AP11 waits for #1150 (CW9: `.github/workflows/` and `tools/`) and
  #1160 (the cleanup wave's last sweep of `tests/`). Rows under `tests/` may
  change in that sweep; AP11 re-reads each row's file at its own base, and a
  file that changed or vanished there goes back to this table, not straight to
  deletion.

## Words

| Word | Meaning here |
| --- | --- |
| **Delete** | The whole file goes, with its `mod`, `[[test]]`, workspace or import line. |
| **Fold** | The file moves to the named new home, with only the edits the move needs. The row names what it drops, if anything. |
| **Keep** | The file stays. AP11 may drop only lines that name a deleted part, so the kept code still builds. |
| **Kept caller** | A file outside this table that names a deleted or folded file. Each one is listed under [Kept callers AP11 edits](#kept-callers-ap11-edits) as `C1` to `C13`. |
| **Left for later** | Needed by nothing kept once AP11 lands, but not named for deletion by spec #1223. It stays and is listed under [Left for later](#left-for-later). |

## What stays, and why

Spec #1223: "OpenWiz becomes the command, the adapters and the engine."

- **The command, install and setup.** `crates/cli` keeps `ls`, `show`, `help`,
  `help --agent`, `fleets`, `fleet <spec>`, `fleet due`, `fleet tick --dry-run`,
  `loop`, `init` and `github token`. `tools/install` stays: the installer and
  the setup tools (`tools/install/setup/`), with the setup state contract
  `contracts/setup.v1.md`.
- **The adapters.** `crates/adapters/cloudroom` and `crates/adapters/github`
  stay whole, including the halves of send and new that the engine uses
  (`messaging.rs`, `new_thread.rs`).
- **The engine.** In this table, the engine means the fleet planner and the
  loop planner in `crates/core` (`fleet/`, `fleet/tick/`, `loops/`) and the
  commands that run them. It starts agents through core `new_thread` (the
  operation, its record and its status) and messages loops through core
  `messaging`'s `Messenger` and `tell`. So those core modules stay, with the
  prompt and attachment types their records bind. Only `messaging/lookup.rs`,
  which serves only `send --check` and the server, goes.
- **The store's engine half moves into the command.** Spec #1223 deletes the
  store, but the kept `fleet` and `loop` commands need its state directory, its
  start records and its loop switches. Those files fold into
  `crates/cli/src/state/`. The send records (`FileStore`), the new-thread
  records, the attachment store and the setup-state reader go with the commands
  and routes that used them.
- **The loop configuration stays as it is.** `openwiz loop on` and `off` take
  their trusted context from the owner-only `service/config.json`, checked
  against `contracts/service.v1.schema.json`. So that schema, its contract
  `contracts/service.v1.md` and the example `deploy/pc/config.example.json` are
  keep rows, and the file, its location and its shape do not change. See
  [The loop configuration](#the-loop-configuration).

Everything else in the five parts goes: every file of the web view, OpenWiz's
copy of the website (WizSite serves the landing page and `/changelog` at its
`main` above), the server, the service, and the commands `send`, `new`,
`models` and `attachment`.

## The loop configuration

The service goes, but its configuration file stays, because the kept `openwiz
loop` reads it. Read at the base; this table changes none of it.

**The read path.** `openwiz loop on|off <name>` (`crates/cli/src/loops.rs:95`)
calls `installed(checkout, state)` in `crates/store/src/loops/config.rs`, which
folds unchanged into `crates/cli/src/state/loops/config.rs`. That reader:

1. checks the private state with `paths::inspect` (`loops/paths.rs:168` to
   `175`): `service/` and `service/config.json` are required, owner-only and
   not symlinks; the service's other files (`state.json`, `app/`, `clone/`,
   `builds/`) are checked only when present, so their absence after the
   service goes refuses nothing;
2. reads `<state>/service/config.json` and validates it with
   `document::service_config` (`loops/document.rs:93`) against `$defs.config`
   of `contracts/service.v1.schema.json`, compiled in with `include_str!`, plus
   the port bound;
3. requires a nonblank, NUL-free `operator`, and binds the context to the
   config's `repository` and `project`, with the checkout's `origin` matching
   that repository; each switch re-reads and rechecks all three.

A missing or invalid file refuses the switch ("cannot read service
configuration"). The fold keeps steps 1 to 3 byte for byte; only the
`include_str!` paths change, for the new directory depth. The kept proofs of
those checks, `tests/loops/l6_config.rs` and `tests/cli-agent/process.rs`,
build their config from the `openwiz.service-config.v1` example in
`contracts/service.v1.md`, which stays.

**Existing installs.** The file was written by the owner's setup from
`deploy/pc/config.example.json` (`deploy/pc/README.md:64`, then filled in by
hand), as `contracts/service.v1.md` says ("written by Jake's setup, never by
the service"). AP11 deletes no state and changes neither the reader nor the
schema, so an existing `service/config.json` keeps working with no migration.
Deleting `openwiz-service` leaves the file's service-only fields (`tick`,
`health`, `server`, `orchestrator_thread`, `service_issue`, `github_app`,
`loops`, `events`) unused, but still required by the schema.

**Fresh installs.** Nothing writes the file today: `tools/install/install.py`
creates only the `service/` directory, and no setup tool, CLI command or skill
writes `service/config.json` (search: `config\.json` in `tools/install/setup`,
`tools/install/install.py`, `tools/install/pull.py`, `crates/cli/src`). So on a
fresh install `openwiz loop on|off` refuses until the owner writes the file by
hand, before and after AP11 alike. D6 asks Jake whether that should change.

## Decisions for Jake

Each one is a choice this table makes that AP10 can change. The rows follow the
recommendation.

- **D1. The service's loop runner and loop watchdog go with the service.**
  Spec #786 (0.0.17) kept them as loop features; spec #1223 deletes the service
  whole. Cloudroom loops, which `launch-fleet` creates directly, keep running
  loops; `openwiz loop` keeps its local switches. Nothing in OpenWiz then runs a
  loop itself or watches loop health. Recommended: delete, as the rows say.
- **D2. Some proofs of kept core rules go with the commands they ran through.**
  The engine reuses core `new_thread` and `messaging`, but many of their proofs
  run `openwiz send` or `openwiz new`, or read the file stores that go. The
  rows keep every proof that runs through the core with an in-memory store or
  fake client (`tests/new-thread`: 17 kept), and delete those that need a
  deleted command or store (`tests/messaging`: all but the allowlist, structure
  and shared files; `tests/new-thread`: 16, including N9 lost acknowledgement,
  N12 claims across processes and N13 crash recovery). AP11's acceptance
  criteria make it name a keeper for each deleted test or say its behaviour is
  gone. This table has not verified a keeper in `tests/fleet` for N9, N12 or
  N13. Recommended: delete as the rows say, with AP11 naming keepers.
- **D3. Core attachment types stay; the attachment feature goes.** The store,
  the CLI commands, `--attach`, the server routes and the tray go. Core
  `attachment.rs`, `prompt.rs`, the allowlist's one `attachment_args` and the
  attachment contracts stay, because the start record's prompt digest binds
  them and removing them changes the allowlist, which needs Jake's yes under
  `AGENTS.md`. The alternative is removing them too, a contract and allowlist
  change for its own ticket. Recommended: keep, as the rows say.
- **D4. The installer's web pieces.** `tools/install` still installs and opens
  the web view (`install.py --serve`, `--open`), packages the service and the
  web export, and runs an access step for reaching the server through a tunnel
  (`tools/install/access/`). These are kept callers, not rows, and lie outside
  AP11's owned paths. Recommended: AP10 adds `tools/install/` (shared: only
  lines and cases for the deleted parts) to AP11's owned paths, and AP11
  removes them; the access step's own fixtures fold to `tools/install/access/`
  only while that step stays. If Jake drops the access step, those 3 fold rows
  become delete rows.
- **D5. Kept callers outside AP11's owned paths.** `tools/live-smoke/`,
  `tools/skills-eval/`, `tools/test-value/`, `tests/checks/`, `tests/proof/`,
  `tests/cli-agent/`, `tests/fleet/`, `tests/loops/`, `ci/escapes/`,
  `ci/shard/`, `ci/rust-tests.sh`, `.githooks/`, `.github/actions/`,
  `crates/cli/`, `crates/core/src/fleet/` and two adapter files name deleted or
  folded parts (C2 to C13). The fold rows' new homes (`crates/cli/src/state/`,
  `crates/cli/tests/`, `tests/proof/`, `crates/adapters/github/src/`,
  `tools/install/`) are outside them too. Recommended: AP10 adds each, shared,
  for only those lines, cases and moved files.
- **D6. The loop configuration's home and provisioning.** The rows keep
  `service/config.json`, `contracts/service.v1.schema.json`,
  `contracts/service.v1.md` and `deploy/pc/config.example.json` unchanged, so
  AP11 changes no configuration (see [The loop
  configuration](#the-loop-configuration)). Changing any of it is a
  configuration and contract change for Jake: (a) keep it as it is
  (recommended for AP11); (b) later, a loop-only config contract with only
  `repository`, `project` and `operator`, at a new or the same path, which
  changes the reader (`state/loops/config.rs`, `document.rs`), the schema, the
  two proofs (`tests/loops/l6_config.rs`, `tests/cli-agent/process.rs`) and
  every existing install's file; (c) have setup write the file on fresh
  installs, which changes `tools/install/setup/`. Recommended: (a) now; (b) and
  (c), if wanted, as their own tickets.

## How to check this table

The table's files are exactly this list (649 paths):

```sh
base=e817c9a293f4317d210a13e8821bb7377fdbef5c
git ls-tree -r --name-only "$base" -- \
  apps/web apps/site crates/server crates/service crates/store \
  crates/core/src/attachment.rs crates/core/tests/attachment \
  crates/core/src/messaging crates/core/src/new_thread crates/core/src/prompt.rs \
  crates/core/src/notifications \
  crates/cli/src/send.rs crates/cli/src/attach.rs crates/cli/src/attachment.rs \
  crates/cli/src/new_thread.rs \
  crates/adapters/cloudroom/src/messaging.rs crates/adapters/cloudroom/src/new_thread.rs \
  crates/adapters/cloudroom/tests/new_thread_readers.rs \
  tests/web-api tests/service tests/messaging tests/new-thread tests/attachments \
  tests/notifications tests/send-harness tests/fixture-entrypoints/server.rs \
  tests/loops/l6_api.rs tests/loops/l6_executor.rs \
  contracts/web-api.v1.md contracts/cockpit.v1.md contracts/cockpit.v1.schema.json \
  contracts/service.v1.md contracts/service.v1.schema.json \
  contracts/setup.v1.md contracts/setup.v1.schema.json \
  contracts/plan.v1.md contracts/plan.v1.schema.json \
  contracts/attachment.v1.schema.json contracts/attachment-mime-types.v1.md \
  contracts/messaging.v1.schema.json contracts/new-thread.v1.schema.json \
  contracts/prompt.v1.schema.json \
  docs/web-access.md docs/service-install.md deploy/pc
```

Every path it prints has exactly one row below, and every row is one of them.
The act-from-the-UI pieces outside the five folders are the files whose job is
composing, sending, attachments, new threads, messaging or the cockpit, their
crate tests and test targets, and the contracts and docs written only for those
pieces or the five parts. The core and adapter modules the engine shares with
them are rows too, marked keep, so the reason they stay is written down.

**Lines** count newline characters at the base, plus one when the last line
has none. Binary files show `binary` and count zero.

**Searches.** Each row's "Uses today" names a search. Each search runs
`git grep -l -E <pattern> "$base" --` over the whole tree, then leaves out the
table's own rows and these history paths, where a path is a record of a past
run, not a caller: `changes/`, `CHANGELOG.md`, `release/` (frozen),
`docs/evidence/`, `docs/cleanup/`, `docs/live-checks/`, `docs/spikes/`,
`tools/test-value/evidence/`, `tests/fleet/evidence-*`,
`ci/selection/valid/`, `ci/selection/invalid/`, `ci/main-batch/fixtures/`,
`ci/shard/times.tsv` and `Cargo.lock`. Every file a search found outside those
is a kept caller below; a search with no kept result says so.

| Search | Pattern | Kept results |
| --- | --- | --- |
| S1 | `apps/web` | C2, C3, C4, C6, C8, C9, C10, C11 and C12's files |
| S2 | `apps/site` | C3, C4, C6, C11 and C12's files |
| S3 | `openwiz[-_]server\|crates/server` | C1, C3, C4, C6, C7, C8, C9, C11 and C12's files |
| S4 | `openwiz[-_]service\|crates/service` | C1, C3, C4, C6, C7, C8, C9 and C12's files |
| S5 | `openwiz[-_]store\|crates/store` | C1, C4, C7, C8, C9, C11 and C12's files |
| S6 | `core::notifications\|messaging::lookup\|notifications::(model\|stock)` | none |
| S7 | `(crate\|openwiz_cli)::(send\|new_thread\|attach\|attachment)\b` | C7 (`main.rs`, `response.rs`) and C8 (`tests/cli-agent/main.rs`, `review.rs`). Not callers: CloudRoom `allowlist.rs` and core `fleet/starts.rs` match only their own crate's kept `new_thread` |
| S8 | the deleted test targets, files and binaries by name (`--test web-api` and so on, `tests/service/` and the other folders, `send-harness`, `fixture-entrypoints/server`, `l6_api`, `l6_executor`, `t2_locate`) | C1, C3, C4, C5, C6, C8, C10, C12 and C13's files. Not callers: two core test files say only that they were moved from `tests/` (history) |
| S9 | `(web-api\|cockpit\|service\|setup)\.v1\|web-access\.md\|service-install\.md\|deploy/pc` | C3, C4, C6, C8, C9, C10 and C12's files. Not callers: files that name only the kept `setup.v1` or `public-cloudroom-setup.v1` (most setup tools, CloudRoom `allowlist.rs`) |

Module-level uses inside the crates (which kept file uses which core, store or
CLI module) were read from each kept file's `use` lines and paths, and
`contracts/engine-retirement.v1.md`'s page and command maps, re-checked at the
base.

## Kept callers AP11 edits

AP11 drops only the named lines and cases; it never deletes these files. "In
AP11" says whether AP11's current owned paths cover it.

| Id | Kept files | What names a deleted or folded part | In AP11 |
| --- | --- | --- | --- |
| C1 | `Cargo.toml`, `crates/cli/Cargo.toml`, `tests/Cargo.toml` (and `Cargo.lock`) | Workspace members `crates/server`, `crates/service`, `crates/store`; the `openwiz-store` and `openwiz-server` dependencies; the `web-api`, `messaging`, `new-thread`, `attachments`, `service`, `notifications` targets and the `send-harness` and `openwiz-server` fixture binaries | Root manifests yes; `crates/cli/Cargo.toml` and `tests/Cargo.toml` no (D5) |
| C2 | `.gitignore`, `.githooks/test.sh` | `apps/web` build output; one synthetic changed path | No (D5) |
| C3 | `.github/workflows/ci.yml`, `.github/workflows/packages.yml`, `.github/actions/docs-only/` (`action.yml`, `classify.sh`, `run.py`, `setup/action.yml`, `test.sh`, `test_*.py`, `test_rust_runner.sh`), `.github/actions/changelog/` | The web, site and service lanes and packages, their classifier rows and test expectations | Workflows yes; actions no (D5) |
| C4 | `ci/select/` (`map.json`, `job.py`, `planted.py`, `resolve.py`, `steps.py`, `trace.py`, `units.py`, `README.md`, `test_*.py`), `ci/escapes/test.py`, `ci/shard/test.py`, `ci/rust-tests.sh`, `contracts/ci-selection.v1.md` | Selector units, steps and fixtures for the deleted crates, targets and apps | `ci/select/` yes; the rest no (D5) |
| C5 | `tools/collector/steps.tsv` | A step naming a deleted test target | No: WizRoom (#979) owns `tools/collector/` |
| C6 | `tools/release/` (`check.py`, `scans.py`, `candidate.py`, `product_identity.py`, `README.md`, `findings.md`, `test*.py`) | Packaging and scans of the web export, site, server and service | Yes |
| C7 | `crates/cli/src/main.rs`, `response.rs`, `lib.rs`, `build.rs`, `agent-catalogue.json`, `agent_help.rs`, `fleet_tick.rs`, `fleet_tick_graph.rs`, `loops.rs`, `loop_export.rs`; `crates/core/src/fleet/starts.rs` (comments) | Dispatch, help and catalogue rows of `send`, `new`, `models`, `attachment`; the `openwiz_store` imports that move to `crate::state` | No (D5) |
| C8 | `tests/checks/` (`skills.rs`, `ci_selection.rs`, `cockpit_schema_conformance.rs`, `main.rs`), `tests/proof/p08a_allowlist_static.rs`, `tests/cli-agent/` (`main.rs`, `process.rs`, `review.rs`), `tests/fleet/` (`b4_fake.rs`, `b4_record.rs`), `tests/loops/` (`main.rs`, `fixture.rs`, `l6_cli.rs`, `l6_config.rs`, `l6_switches.rs`) | Paths, imports and cases of deleted parts; the store imports that fold; `cockpit_schema_conformance.rs` proves only the deleted cockpit contract. `p08a_allowlist_static.rs`'s static cases that compile in deleted service and store source (lines 1424, 1486, 1516, 1590, 2238, 2254) go with those files. `tests/loops/l6_config.rs:6` and `tests/cli-agent/process.rs:892` compile the kept `contracts/service.v1.md` and need no edit | No (D5) |
| C9 | `tools/install/` (`install.py`, `fixture_bundle.py`, `platform/runtime.py`, `platform/test_runtime.py`, `test_install.py`, `test_setup_api.mjs`, `setup/store.py`, `access/`, `cloudroom/`, `tests/first-hour/`, `tests/journey/test_journey.py`, `tests/public-release-security/`, `tests/setup-onboard-contract/`, `first-hour-live-kit.md`) | `--serve` and `--open`, the service and web export in the bundle, the web fixtures that fold here, the setup page's client (`api.ts`) and synthetic answers | No (D4) |
| C10 | `tools/live-smoke/` (`browser.mjs`, `test_fixture.py`), `tools/skills-eval/` (`cases/*.json`, `required-text.json`) | The web view's npm tools; text cases naming the web view | No (D5) |
| C11 | `tools/test-value/README.md`, `test_count.py`, `test_measure.py` | Counts and paths of the deleted targets and apps | No (D5) |
| C12 | `AGENTS.md`, `README.md`, `CONTRIBUTING.md`, `RELEASING.md`, `docs/agents/fleet.md`, `docs/agents/huntr.md`, `docs/cli.md`, `docs/github-app.md`, `docs/decisions/public-offer.md`, `docs/decisions/public-cloudroom-setup.md`, `docs/decisions/public-feedback.md`, `docs/security/public-release-review.md`, `contracts/` (`cli.v1.md`, `decisions.v1.md`, `engine-retirement.v1.md`, `feedback.v1.md`, `first-hour.v1.md`, `fleet-tick.v1.md`, `github-identity.v1.md`, `install.v1.schema.json`, `open-development.v1.md`, `public-cloudroom-setup.v1.md`, `setup-onboard.v1.md`, `agent-github-reads.v1.md`, `setup.v1.md`'s route section), `tests/fixtures/release/` READMEs | Links and lines naming deleted parts | `AGENTS.md`, `README.md` and `docs/agents/fleet.md` yes; the rest no (D5). A contract edit beyond a dead link is a contract change and goes to Jake |
| C13 | `crates/adapters/github/src/app.rs`, `crates/adapters/cloudroom/src/locate.rs` | `app.rs`'s `#[path]` to `tests/service/t7_transport.rs`, which folds beside it; a comment naming `t2_bundle_pair.rs` | No (D5) |

## Left for later

Needed by nothing kept once AP11 lands, but adapter or core files that spec
#1223 does not name for deletion. They stay, for a later decision.

- **L1.** `crates/adapters/github/src/plan.rs`, `plan_reads.rs`,
  `decisions.rs`, `decisions_json.rs` and `events.rs`: only the server's plan
  and Decisions routes and the service's event intake used them (search:
  `adapter_github::(plan|plan_reads|decisions|decisions_json|events)` finds no
  kept caller). `contracts/plan.v1.md` and its schema stay with them, checked by
  `tests/checks/plan_decisions_schema_conformance.rs`.
- **L2.** The send operation's own code inside the kept core `messaging` files
  (`send.rs`'s `send`, `preview.rs`, `reconcile.rs`): after `openwiz send`
  goes, only the engine's `Messenger`, `TellReply`, `OpId`, `sha256_hex` and
  `StoreError` in the same files are used.
- **L3.** `crates/core/src/health/`: used by the kept GitHub `decisions.rs` and
  CloudRoom `loops.rs`, both themselves partly left over after D1.

## Totals

AP11 fills in the last column with the lines it removed, per part, as its
fourth acceptance criterion asks.

| Part | Files | Delete (lines) | Fold (lines) | Keep (lines) | Removed by AP11 |
| --- | ---: | ---: | ---: | ---: | --- |
| The web view (`apps/web`) | 324 | 313 (48550) | 11 (621) | 0 (0) | 48550: 313 files deleted; 11 folded unchanged |
| OpenWiz's copy of the website (`apps/site`) | 19 | 19 (1931) | 0 (0) | 0 (0) | 1931: 19 files deleted |
| The local server (`crates/server`) | 18 | 18 (10090) | 0 (0) | 0 (0) | 10102: 18 files deleted (12 lines more than at the base, from #1274) |
| The service (`crates/service`) | 33 | 33 (7928) | 0 (0) | 0 (0) | 7928: 33 files deleted |
| The store (`crates/store`) | 18 | 9 (3738) | 9 (3642) | 0 (0) | 4158: 9 files deleted (3738); 420 removed or rewritten in the fold (the send record and claim code in `mod.rs`; renamed lines in `state_dir.rs` and the loops files) |
| Act-from-the-UI pieces in the core, command line and adapters | 36 | 8 (3506) | 0 (0) | 28 (10475) | 3565: 8 files deleted (3506); 59 dropped from keep rows |
| Their tests | 182 | 153 (53832) | 2 (913) | 27 (6816) | 54455: 152 files deleted (53814; `tests/service/t7_python.rs` was already gone in #1143); 633 dropped from keep rows; 8 in the folds |
| Their contracts, docs and deployment | 19 | 7 (2362) | 0 (0) | 12 (7996) | 2362: 7 files deleted |
| **Total** | **649** | **560 (131937)** | **22 (5176)** | **67 (25287)** | **133051** |

Granted beside the table on #1264, each "behaviour gone": `tests/fleet/lock_release.rs` (144, the
new-thread file store's claim lock), `tests/checks/cockpit_schema_conformance.rs` (321, the cockpit
contract), `tools/install/test_setup_api.mjs` (89, the web setup client),
`tools/install/tests/first-hour/providers/recording.ts` (241, the web page's fault cases), and
`tools/install/platform/runtime.py` and `test_runtime.py` (311 and 226, the local service supervisor),
and `tools/live-smoke/browser.mjs` (89, the web view's live browser sitting) with its probe rule and
cases: 1421 lines in the files.

Kept beside the table by J233 (#1264): `openwiz models --json`, read-only, because setup's harness
check and onboarding read it. Its read and rendering moved from the deleted `crates/cli/src/new_thread.rs`
to `crates/cli/src/models.rs` (about 100 lines); `new`'s write paths went as the row says.

The CI budget table (`tools/war-room/budgets.tsv`) loses the rows of the removed `web-build`, `web`,
`web-export`, `rust-export` and `site` jobs (13 rows); `rust`'s three rows, derived from the
`rust-export` twin with the same steps, now carry that twin's own sources.

## The rows

### The web view (`apps/web`)

324 files: 313 delete, 11 fold, 0 keep.

| Path | Lines | What it does | Uses today (search) | Disposition | New home |
| --- | ---: | --- | --- | --- | --- |
| `apps/web/.gitignore` | 6 | Web view build, config or rules | Other `apps/web` files, its CI lane and the server's `--web-root` (S1) | **delete** |  |
| `apps/web/AGENTS.md` | 28 | apps/web: the OpenWiz web viewer | Other `apps/web` files, its CI lane and the server's `--web-root` (S1) | **delete** |  |
| `apps/web/docs/design-rules.md` | 435 | OpenWiz web: design rules | Other `apps/web` files, its CI lane and the server's `--web-root` (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/README.md` | 72 | D4 adoption proof plan | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/adoption.json` | 55 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/captures.log` | 1 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/green-home-final.log` | 12 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/green-render.log` | 15 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/red-home.log` | 35 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-1/README.md` | 29 | Review correction: R2 and R3; R1 waits for D3 | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-1/green-merge.log` | 1 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-1/green-rules.log` | 3 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-1/red-merge.log` | 8 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-1/red-rules.log` | 6 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-1/targeted-browser.log` | 28 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-1/targeted-unit.log` | 18 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/README.md` | 55 | R1: final Home + D2 + D3 integration | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/adoption-integrated.json` | 52 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/capture-comparison.json` | 397 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/captures.log` | 1 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/contrast-region.json` | 45 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/green-merge.log` | 1 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/green-pwa-preservation.log` | 6 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/red-pwa.log` | 8 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/capture.json` | 464 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/empty/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/empty/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/error/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/error/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/fleet-detail/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/fleet-detail/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/fleets/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/fleets/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/home-answer/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/home-answer/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/home-empty/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/home-empty/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/home-error/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/home-error/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/home-live/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/home-live/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/home-loading/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/home-loading/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/home-stale/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/home-stale/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/loading/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/loading/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/new-thread/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/new-thread/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/overview/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/overview/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/sessions/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/sessions/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/thread/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/shots/thread/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/targeted-browser.log` | 28 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/review-2/targeted-unit-pwa.log` | 26 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/capture.json` | 462 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/empty/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/empty/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/error/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/error/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/fleet-detail/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/fleet-detail/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/fleets/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/fleets/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/home-answer/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/home-answer/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/home-empty/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/home-empty/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/home-error/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/home-error/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/home-live/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/home-live/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/home-loading/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/home-loading/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/home-stale/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/home-stale/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/loading/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/loading/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/new-thread/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/new-thread/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/overview/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/overview/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/sessions/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/sessions/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/thread/desktop.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/shots/thread/phone.png` | binary | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/docs/evidence/1030/targeted-browser.log` | 15 | Evidence for #1030's web view pages (logs, shots) | Nothing; evidence for #1030's web pages (S1) | **delete** |  |
| `apps/web/next.config.mjs` | 46 | A static export (out/), served same-origin under / by openwiz-server (option (a)). The app calls… | Other `apps/web` files, its CI lane and the server's `--web-root` (S1) | **delete** |  |
| `apps/web/package-lock.json` | 1104 | openwiz-web | Other `apps/web` files, its CI lane and the server's `--web-root` (S1) | **delete** |  |
| `apps/web/package.json` | 31 | OpenWiz 0.0.2: the read-only web viewer over openwiz-server's API. A static export, same-origin under /. | npm for the web view; kept: `tools/live-smoke/browser.mjs` and `tools/release/check.py` read it (S1, C10, C6) | **delete** |  |
| `apps/web/pages/404.tsx` | 12 | The static export's 404 page, in the app's own style. Next's default one carries inline styles, which the… | Web view static export only (S1) | **delete** |  |
| `apps/web/pages/_app.tsx` | 22 | Next.js page of the web view | Web view static export only (S1) | **delete** |  |
| `apps/web/pages/_document.tsx` | 26 | The fonts are bundled (public/fonts, OFL 1.1). Nothing is loaded from another origin. The installable app… | Web view static export only (S1) | **delete** |  |
| `apps/web/pages/index.tsx` | 5 | Next.js page of the web view | Web view static export only (S1) | **delete** |  |
| `apps/web/pages/setup.tsx` | 44 | Next.js page of the web view | Web view static export only (S1) | **delete** |  |
| `apps/web/public/fonts/Geist-var.woff2` | binary | Web view static asset (installable shell) | Web view static export only (S1) | **delete** |  |
| `apps/web/public/fonts/GeistMono-var.woff2` | binary | Web view static asset (installable shell) | Web view static export only (S1) | **delete** |  |
| `apps/web/public/fonts/OFL.txt` | 93 | Web view static asset (installable shell) | Web view static export only (S1) | **delete** |  |
| `apps/web/public/icons/apple-touch-icon.png` | binary | Web view static asset (installable shell) | Web view static export only (S1) | **delete** |  |
| `apps/web/public/icons/icon-192.png` | binary | Web view static asset (installable shell) | Web view static export only (S1) | **delete** |  |
| `apps/web/public/icons/icon-512.png` | binary | Web view static asset (installable shell) | Web view static export only (S1) | **delete** |  |
| `apps/web/public/icons/icon-maskable-512.png` | binary | Web view static asset (installable shell) | Web view static export only (S1) | **delete** |  |
| `apps/web/public/manifest.webmanifest` | 16 | Web view static asset (installable shell) | Web view static export only (S1) | **delete** |  |
| `apps/web/public/sw-register.js` | 8 | OpenWiz's one service worker registration (#1029): the app shell's worker, /sw.js, for the whole app. It… | Web view static export only (S1) | **delete** |  |
| `apps/web/public/sw.js` | 98 | OpenWiz's app-shell worker (#1029). It only makes the installed app open: | Web view static export only (S1) | **delete** |  |
| `apps/web/scripts/check.mjs` | 637 | Static checks for apps/web, on the TypeScript compiler API (no ESLint: approval W-7). Exits 1 with one… | Other `apps/web` files, its CI lane and the server's `--web-root` (S1) | **delete** |  |
| `apps/web/src/api.ts` | 550 | The only module that makes requests: same origin, /api/v1/...; GET, and the POSTs (below): the send, the… | Every page; kept: `tools/install/test_setup_api.mjs` and first-hour `providers/recording.ts` import it (S1, C9) | **delete** |  |
| `apps/web/src/attachments.ts` | 510 | The attachment tray's presentation state (#16, B3): one list per target (a thread's composer, or a… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/cockpit.ts` | 549 | Page 1 of the cockpit (0.0.10 T3, #536): GET /api/v1/cockpit, read as contracts/cockpit.v1.md says, and… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/command.ts` | 365 | The cockpit's command bar (0.0.10 T4, #537): a pure function over the page's own data. It reads nothing,… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/App.tsx` | 597 | The page: the header with the envelope's coverage, snapshot and gaps, the connection state, the list, and… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/AttachmentTray.tsx` | 172 | The one attachment tray (#16, B3), in the one prompt body's attachments region, so the composer and the… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/CloudRoomSetup.tsx` | 19 | #2201: setup's CloudRoom step, its one sign-in screen and the powered-by line… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/Cockpit.tsx` | 687 | Page 1 of the cockpit (0.0.10 T3, #536): Needs you on top, numbered in the server's order (oldest first),… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/CommandBar.tsx` | 221 | The cockpit's command bar (0.0.10 T4, #537), docked at the bottom of the page: the controller's words over… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/CommandNavigation.tsx` | 151 | Navigation uses only the already listed snapshot and the app's existing handlers. | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/Composer.tsx` | 605 | The composer: one text message to the open thread, under its final output, inside #6's panel and sheet… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/Decisions.tsx` | 672 | Decisions (0.0.11 U6, #656): every open decision request as a card, read from GET /api/v1/decisions… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/Detail.tsx` | 274 | The details of one session, as show returns them: a modal bottom sheet on phones, a side panel on desktop… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/FeedbackShare.tsx` | 109 | #2292: the owner's feedback handoff and the OpenWiz share, on the Home screen (contracts/feedback.v1.md).… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/FirstHour.tsx` | 290 | The first-hour journey guidance (#2223): install, connections, the first idea, its grill and approvals,… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/FleetDetail.tsx` | 298 | One fleet (#126, spec 3's C2): its graph, drawn by our own code (pills in columns by step, arrows between… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/FleetProgress.tsx` | 7 | The reported merged count, drawn as a quiet track beside its existing words. | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/Fleets.tsx` | 232 | The fleets list (#125, spec 3's C1): "Needs you" at the very top, each item saying what it needs and from… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/HomeLive.tsx` | 37 | The active subset of the existing inventory page, in its presentation order. No independent read. | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/Icons.tsx` | 15 | A web view page or control | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/Inventory.tsx` | 217 | The list: one page of the core's order under its group headings (G1), thin rows (name, status, age), the… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/Launcher.tsx` | 636 | The launcher (#12): one new Cloud thread in one existing project, opened from the project's heading,… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/Loops.tsx` | 215 | The loops page (0.0.9 L7, #549): every OpenWiz loop with its cadence, next run, last run, 24-hour cost and… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/NeedsYouAnswer.tsx` | 17 | C5: opens the one existing composer. It never sends or owns draft state. | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/PlanGraph.tsx` | 480 | The plan graph page (0.0.11 U3, #653), drawn to the design target in the approved #647 structure: the… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/PromptBody.tsx` | 123 | The one prompt body (#12, decided in #12's planning): the labelled text field, its keyboard press… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/ReadyStock.tsx` | 55 | One read-only view over the cockpit snapshot; no delivery or work controls. | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/Setup.tsx` | 81 | The setup page's independent components and recorded effects (#1105). Display only: every state comes from… | Setup page; kept: `tests/checks/skills.rs` reads it (S1, C8) | **delete** |  |
| `apps/web/src/components/Status.tsx` | 126 | Status as a word and a shape: the session marker (V2), the connection pill and the notice that says what… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/StatusMark.tsx` | 23 | Every state has a shape as well as its word. Live motion stops under reduced motion. | Web view pages only (S1) | **delete** |  |
| `apps/web/src/components/Ui.tsx` | 11 | A web view page or control | Web view pages only (S1) | **delete** |  |
| `apps/web/src/composer.ts` | 564 | The composer's presentation state, one per thread id, and the one place a send is made. From WS-7, WS-8… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/css.d.ts` | 3 | CSS files are imported for their side effect only (pages/_app.tsx). Lets npm run typecheck run before Next… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/decisions.ts` | 484 | Decisions (0.0.11 U6, #656): GET /api/v1/decisions, read as contracts/decisions.v1.md says, and what each… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/envelope.ts` | 245 | The openwiz.inventory.v1 envelope, as contracts/inventory.v1.schema.json defines it. One type per schema… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/feedback.ts` | 114 | #2292: the app's half of contracts/feedback.v1.md. The owner writes only the public feedback they choose,… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/fleetGraph.ts` | 523 | One fleet's view (#126, spec 3's C2): the shapes of openwiz fleet <spec> --json it reads… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/fleets.ts` | 892 | The fleets list (#125, spec 3's C1): openwiz fleets --json (contracts/fleet.v1.md), read exactly, and what… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/launcher.ts` | 595 | The launcher's presentation state, one per project id, and the one place a thread is created (#12). From… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/loops.ts` | 413 | The loops page (#549): GET /api/v1/loops, read exactly as contracts/web-api.v1.md's "Loops view" says, the… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/markers.ts` | 23 | Status as a word, a glyph and a shape (V2). The word is the core's, as reported. The tier for each word is… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/messaging.ts` | 238 | The send shapes the composer reads, as contracts/messaging.v1.schema.json defines them: the report… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/newthread.ts` | 306 | The new-thread shapes the launcher reads (#12), as contracts/new-thread.v1.schema.json defines them: the… | Launcher; kept: first-hour `providers/recording.ts` imports it (S1, C9) | **delete** |  |
| `apps/web/src/notificationTarget.ts` | 36 | The Decisions page's bound mode. Push notifications and their landing are retired (0.0.17 ER4); only this… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/plan.ts` | 620 | The plan graph page (0.0.11 U3, #653): GET /api/v1/plan, read as contracts/plan.v1.md says, and what the… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/poller.ts` | 229 | One refresh loop: at most one read in flight. The next read starts only after the last one ended or timed… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/present.ts` | 81 | Presentation of envelope values, as text. Nothing here decides membership, order, visibility, truncation… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/readyStock.ts` | 100 | Strict stock decoding and display only. No source, permission or work effects. | Web view pages only (S1) | **delete** |  |
| `apps/web/src/setup.ts` | 55 | Setup page wording and status marks (#1105). Pure: no fetch, no effects. T5 (remote_access,… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/timing.ts` | 45 | PROVISIONAL engineering choices, for fixture work only. They are not targets: ticket 1's real baseline… | Web view pages only (S1) | **delete** |  |
| `apps/web/src/viewer.ts` | 233 | The page's presentation state, and nothing else: the current page, the last good snapshot (with when it… | Web view pages only (S1) | **delete** |  |
| `apps/web/styles/cockpit.css` | 143 | Page 1 of the cockpit (#536), drawn to the approved design target in Observatory: | Web view pages only (S1) | **delete** |  |
| `apps/web/styles/decisions.css` | 77 | Decisions (#656), drawn to the approved design target in Observatory: | Web view pages only (S1) | **delete** |  |
| `apps/web/styles/feedback.css` | 34 | The feedback handoff and the OpenWiz share (#2292), at the foot of Home, in | Web view pages only (S1) | **delete** |  |
| `apps/web/styles/first-hour.css` | 62 | The first-hour journey guidance (#2223). Every rule is scoped to .fh. | Web view pages only (S1) | **delete** |  |
| `apps/web/styles/globals.css` | 861 | The list screens' values (hill-climb #1451). They live here, not in tokens.css, which apps/site copies… | Web view pages only (S1) | **delete** |  |
| `apps/web/styles/loops.css` | 55 | The loops page (#549), drawn to the approved design target in Observatory: | Web view pages only (S1) | **delete** |  |
| `apps/web/styles/plan.css` | 131 | The plan graph page (#653), drawn to the approved design target in | Web view pages only (S1) | **delete** |  |
| `apps/web/styles/setup.css` | 46 | Approved setup target; every rule is scoped to this page. | Web view pages only (S1) | **delete** |  |
| `apps/web/styles/tokens.css` | 108 | Observatory + command navigation: shared app / landing-page foundation. Import this file before consumer… | Web view pages only (S1) | **delete** |  |
| `apps/web/test/attachment-screens.mjs` | 118 | Renders DEMO-labelled screenshots of the attachment tray's states (#16) at 390 and 1440 px, in the… | Web view test run only (S1) | **delete** |  |
| `apps/web/test/browser/aw05-aw06-tray.test.mjs` | 213 | AW5 (#16), the page's half: the action button is disabled while any attachment is selected, uploading or… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/aw07-aw08-tray.test.mjs` | 138 | AW7 (#16): safe previews. An SVG with a script, an HTML page, a polyglot (a PNG with markup after it) and… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/aw09-aw11-tray.test.mjs` | 244 | AW9 (#16): reloads and reconnects. Reloading mid-upload, losing the network and signing out each keep the… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/c4_reader.test.mjs` | 178 | #128 fixture proof at the public API seam. Expected shapes come from the contract's literal examples,… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/c4_refresh.test.mjs` | 407 | #128 proof plan (fixture evidence, never a live claim): S3-5: the shipped page reads each visible fleet… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/c5_answer.test.mjs` | 369 | S3-6 (#129), fixture evidence: HTTP retries and provider calls are counted separately. All expected… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/c5_reader.test.mjs` | 117 | #129: the optional, server-verified target at the public fleet API seam. | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/c5_server.test.mjs` | 108 | C5 HTTP target verification, against the real server and recorded fakes. Every environment and scenario is… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/ck-answer.test.mjs` | 235 | CK2 (#536, spec #530): answering Needs you on page 1 of the cockpit, on the fake API. An answer is one… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/ck-command-scope.test.mjs` | 140 | CK3 (#537, spec #530): the command bar's reading words on the page. cd narrows Needs you and the grid (the… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/ck-command-y.test.mjs` | 223 | CK3 (#537, spec #530): the command bar's y and approve act only on the item open on screen. y opens that… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/ck-empty.test.mjs` | 89 | CK5 (#536, spec #530): empty means empty. "Nothing needs you" appears only when projects and Needs you are… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/ck-layout.test.mjs` | 114 | CK4 (#536, spec #530): page 1 against the design target at 390 and 1440 CSS px, on the target's synthetic… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/ck-navigation.test.mjs` | 92 | The review of #1560 (R1-R3, at 4edce8f7): the cockpit keeps one read lane and one owner of its answers… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/ck-reader.test.mjs` | 73 | CK1's page half (#536): the cockpit reads cockpit.v1 exactly. The text is parsed strictly, so a key… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/ck-record.test.mjs` | 196 | CK2's answer record (#536, the self-review's findings on efd706a0): an answer is bound to the item it was… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/cloudroom-setup.test.mjs` | 145 | PR2 (#2201): setup's CloudRoom step on the real setup tool, server and page. Recording fakes only:… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/command-navigation.test.mjs` | 159 | K1: snapshot-only navigation, keyboard access and focus in both app layouts. | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/design-pass.test.mjs` | 206 | The design pass (#75): presentation proofs at 390 and 1440 px. The selected row has a shape, not only a… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/detail-resize.test.mjs` | 90 | Browser test of a web view page | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/e11-decisions-answer.test.mjs` | 386 | EP4 (#656, spec #648): a decision card's answer is one send through the existing send path (the core's… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/e11-decisions-layout.test.mjs` | 100 | EP4's screens (#656): Decisions against the design target at 390 and 1440 CSS px, in the target's state:… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/e11-decisions-states.test.mjs` | 183 | EP3/EP4 (#656, spec #648): what each decision card shows, and when it may not be answered. Cards come in… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/e11-plan-layout.test.mjs` | 238 | EP2 (#653, spec #648): the plan graph page against its design target at 390 and 1440 CSS px, on the… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/e11-plan-states.test.mjs` | 382 | EP2 (#653): the plan page's honest states, from the target's README: loading, partial (dashed, never gold,… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/e11-plan-trace.test.mjs` | 204 | EP2 (#653): trace. Hover or keyboard focus previews a ticket's direct prerequisites and dependents; a… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/feedback-share.test.mjs` | 165 | #2292: the feedback handoff and the OpenWiz share on Home, in Chromium, at phone and desktop widths… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/first-hour-pages.test.mjs` | 576 | First-hour pages. This file is shared: #2223 owns the synthetic component-state section below; #2205 adds… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/home.test.mjs` | 247 | H0: synthetic browser evidence for local Home navigation, source honesty, one fleet lane/cache, and the… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/install-access.test.mjs` | 286 | IF7: real setup-page route choices; fixture server, no accounts or writes. The old page only names… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/install-connections.test.mjs` | 397 | IF4/IF5 (#1105): the actual setup tool, server and page on a plain consumer. Recording fakes only: the… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/install-journey.test.mjs` | 105 | IF1/IF9 (#1109): the one install line's journey in Chromium. The actual install entry… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/install-package.test.mjs` | 78 | IF1/IF9: actual offline installer and installed server. Synthetic package only. | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/lp-list.test.mjs` | 145 | LP6 (#549), the loops page on the fake API: every loop the read returns is listed with its cadence, next… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/lp-switch.test.mjs` | 164 | LP6 (#549), the loop switch on the fake API: one press is one POST /api/v1/loops/{id}/on/off with exactly… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/ready-stock.test.mjs` | 69 | PA6/PA7 synthetic client rendering. PC CI only; no real-phone/live claim. | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/setup-github-login.test.mjs` | 148 | #633: GitHub browser sign-in and the explicit App skip, on the real setup tools (setup.py,… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/u-real-server.test.mjs` | 133 | The launcher (#12) through ticket 1's real openwiz-server and its new-thread routes, with the repository's… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/u07-u10-launcher.test.mjs` | 374 | U7 to U10 (#12): the launcher's settings, labels, effects and success, on the fake API's new-thread… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/u11-sol-round-1.test.mjs` | 126 | Sol's round 1 on PR #157 (#12 A2), R1 and R2, on the fake API. Synthetic values only. | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/u11-u13-launcher.test.mjs` | 238 | U11 to U13 (#12): what a refusal, an uncertain create and the page's refresh do to the launcher, on the… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/u14-u15-launcher.test.mjs` | 253 | U14 and U15 (#12): the launcher reuses #6's panel and sheet and the one prompt body (npm run check proves… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/v1-faithful.test.mjs` | 85 | V1: faithful to the envelope. Ticket 1's openwiz-server runs over every 0.0.1 fixture scenario; the page… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/v10-thin.test.mjs` | 111 | V10: a thin client. Only same-origin requests, to the API and the app's own files; no service worker,… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/v11-perf.test.mjs` | 118 | V11, synthetic half: refresh measurements for performance-targets.md. The targets are PENDING (no A9… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/v2-status.test.mjs` | 108 | V2: status without colour. Each status can be told apart in greyscale by its word and its shape, and the… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/v3-inert.test.mjs` | 207 | V3: untrusted text stays inert. HTML, script, links, markdown, bidirectional controls and over-long… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/v4-overlap.test.mjs` | 238 | V4: reads never overlap. With a server slower than the interval, no second list or detail request starts… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/v5-place.test.mjs` | 250 | V5: refresh keeps your place. Updates, inserts above the viewport, removals and page shifts keep the… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/v6-states.test.mjs` | 307 | V6: states are honest. Stale, partial, disconnected, signed out, busy and each core error have their own… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/v7-soak.test.mjs` | 166 | V7: bounded over time. A recorded soak run on the fake clock: two simulated hours of refreshes with… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/v8-paging.test.mjs` | 121 | V8: paging stays within the contract. Only limit and offset exist; the page sends offset alone (the core's… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/v9-layout.test.mjs` | 341 | V9: layout. A bottom sheet at phone widths and a side panel at desktop widths, 44-point targets, a visible… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/w10-no-double.test.mjs` | 517 | W10: no double send. Double clicks, a repeated keyboard send, client retries, reloads and a duplicated tab… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/w11-refresh.test.mjs` | 99 | W11: the composer coexists with 0.0.2's auto-refresh. A refresh never clears the draft, moves the focus or… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/w12-reuse.test.mjs` | 61 | W12: reuse. The composer renders inside #6's panel (desktop) and sheet (phone), after the final output in… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/w13-inert.test.mjs` | 171 | W13: accessible and inert. A pasted file is refused with words; a pasted file path is text. Updated for… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/w7-target.test.mjs` | 107 | W7: the right target. A send always goes to the open thread, from the path only. Drafts are kept per… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/w7-w13-real-server.test.mjs` | 290 | W7 to W13 through ticket 1's real openwiz-server (#91's send, preview and lookup routes), with the… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/w8-effects.test.mjs` | 236 | W8: the action and its effects come before pressing, from the core's preview: idle is Send ("starts a… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/w8-no-false-changed.test.mjs` | 175 | W8, #143: the · changed mark says the buttons or their effect changed under a draft. It is never drawn for… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/browser/w9-outcomes.test.mjs` | 345 | W9: the requested mode and the reported delivery stay separate, and queued, sent, failed, unsupported and… | Web view browser run only (S1) | **delete** |  |
| `apps/web/test/composer-screens.mjs` | 219 | Renders DEMO-labelled screenshots of the composer's states (#9 step 3) at 390 and 1440 px, on the fake… | Web view test run only (S1) | **delete** |  |
| `apps/web/test/design-screens.mjs` | 228 | Design hill-climb captures (2026-11-04): the built app (out/) on the run's design brief's synthetic… | Web view test run only (S1) | **delete** |  |
| `apps/web/test/file-times.tsv` | 57 | Web view test runner or screen capture | Web view test run only (S1) | **delete** |  |
| `apps/web/test/fixtures/cloudroom-setup/README.md` | 7 | CloudRoom setup page fixtures (#2201) | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/cloudroom-setup/install-checksum-mismatch.json` | 1 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/cloudroom-setup/install-declined.json` | 1 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/cloudroom-setup/install-failed.json` | 1 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/cloudroom-setup/install-uncertain.json` | 1 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/cockpit/README.md` | 8 | Cockpit fixtures (#536) | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/cockpit/cockpit.mjs` | 105 | The cockpit proofs' site (#536): the page's static export, the scripted fake API for every other route… | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/cockpit/empty.json` | 86 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/cockpit/target.json` | 388 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/decisions/README.md` | 9 | Decisions fixtures (#656) | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/decisions/decisions.mjs` | 79 | The decision cards' proofs' site (#656): the page's static export, the scripted fake API for every other… | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/decisions/empty.json` | 31 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/decisions/summary.json` | 58 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/decisions/target.json` | 206 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/first-hour-pages/README.md` | 16 | First-hour component states (#2223) | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/first-hour-pages/red.txt` | 27 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/first-hour-pages/states.mjs` | 199 | The first-hour component's synthetic states (#2223). Each state is the text the existing reads would… | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/install-access/README.md` | 35 | IF7 synthetic providers | Kept: `tools/install/access/test_access.py`, first-hour `journey.py` and `codes.py`, `public-release-security` baseline read it (S1, C9) | **fold** | `tools/install/access/fixtures/` (same names) |
| `apps/web/test/fixtures/install-access/driver.py` | 73 | Test-only entry: inject recording management APIs into the INSTALLED tool. Optional loopback edge… | Kept: `tools/install/access/test_access.py`, first-hour `journey.py` and `codes.py`, `public-release-security` baseline read it (S1, C9) | **fold** | `tools/install/access/fixtures/` (same names) |
| `apps/web/test/fixtures/install-access/provider.py` | 181 | Synthetic recording providers; never delegate a request to a real service. Shapes are synthetic… | Kept: `tools/install/access/test_access.py`, first-hour `journey.py` and `codes.py`, `public-release-security` baseline read it (S1, C9) | **fold** | `tools/install/access/fixtures/` (same names) |
| `apps/web/test/fixtures/install-connections/consumer/README.md` | 5 | synthetic-consumer | Kept: `tools/install/tests/journey/test_journey.py` reads this folder (S1, C9) | **fold** | `tools/install/tests/fixtures/install-connections/` (same names) |
| `apps/web/test/fixtures/install-connections/consumer/docs/agents/fleet.md` | 45 | Fleet settings | Kept: `tools/install/tests/journey/test_journey.py` reads this folder (S1, C9) | **fold** | `tools/install/tests/fixtures/install-connections/` (same names) |
| `apps/web/test/fixtures/install-connections/fake-openwiz` | 37 | Synthetic consumer fixture for the setup connections step | Kept: `tools/install/tests/journey/test_journey.py` reads this folder (S1, C9) | **fold** | `tools/install/tests/fixtures/install-connections/` (same names) |
| `apps/web/test/fixtures/install-connections/fleet-empty.md` | 11 | Fleet settings | Kept: `tools/install/tests/journey/test_journey.py` reads this folder (S1, C9) | **fold** | `tools/install/tests/fixtures/install-connections/` (same names) |
| `apps/web/test/fixtures/install-connections/fleet-merge-scaffold.md` | 46 | Fleet settings | Kept: `tools/install/tests/journey/test_journey.py` reads this folder (S1, C9) | **fold** | `tools/install/tests/fixtures/install-connections/` (same names) |
| `apps/web/test/fixtures/install-connections/fleet-small-builder-placeholder.md` | 55 | Fleet settings | Kept: `tools/install/tests/journey/test_journey.py` reads this folder (S1, C9) | **fold** | `tools/install/tests/fixtures/install-connections/` (same names) |
| `apps/web/test/fixtures/install-connections/fleet-template.md` | 95 | Fleet settings | Kept: `tools/install/tests/journey/test_journey.py` reads this folder (S1, C9) | **fold** | `tools/install/tests/fixtures/install-connections/` (same names) |
| `apps/web/test/fixtures/install-connections/gh` | 38 | Synthetic consumer fixture for the setup connections step | Kept: `tools/install/tests/journey/test_journey.py` reads this folder (S1, C9) | **fold** | `tools/install/tests/fixtures/install-connections/` (same names) |
| `apps/web/test/fixtures/install-journey/expected.json` | 4 | #1109, reconciled by #2293: the setup page's cost panel, as the install journey expects it. Independent… | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/loops/README.md` | 10 | Loops fixtures (#549) | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/loops/empty.json` | 6 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/loops/loops.mjs` | 96 | The loops proofs' site (#549): the page's static export, the scripted fake API for every other route, GET… | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/loops/target.json` | 216 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/plan/README.md` | 8 | Plan page fixtures (#653, 0.0.11 U3) | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/plan/plan.mjs` | 137 | The plan page proofs' site (#653): the page's static export, the scripted fake API for every other route,… | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/plan/target.json` | 2843 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/ready-stock/README.md` | 6 | Ready stock fixtures | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fixtures/ready-stock/partial.json` | 180 | Synthetic fixture for a web view test | Web view browser tests only (S1) | **delete** |  |
| `apps/web/test/fleets-screens.mjs` | 73 | Renders DEMO-labelled screenshots of the fleets list (#125) on synthetic fleets, each state at 390 and… | Web view test run only (S1) | **delete** |  |
| `apps/web/test/launcher-screens.mjs` | 166 | Renders DEMO-labelled screenshots of the launcher's states (#12) at 390 and 1440 px, on the fake API: node… | Web view test run only (S1) | **delete** |  |
| `apps/web/test/run-browser.mjs` | 147 | The browser proofs, 3 files at a time, longest first (#431, K14; spec #330: "3 files at a time, longest… | Web view test run only (S1) | **delete** |  |
| `apps/web/test/screens.mjs` | 151 | Renders DEMO-labelled screenshots of the built app on synthetic envelopes, every state at 390 and 1440 px,… | Web view test run only (S1) | **delete** |  |
| `apps/web/test/soak-skip.mjs` | 43 | The soak off the PR path (#1261, folding K13 #430). Only on a pull request's first run against main… | Web view test run only (S1) | **delete** |  |
| `apps/web/test/support/attachment-synthetic.mjs` | 70 | Synthetic attachment reports for the browser proofs (#16), in the shapes of… | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/browser.mjs` | 203 | The browser for the proofs: the image's Chromium, driven by playwright-core (approved: W-5). Every page… | Every browser test, and `apps/site`'s tests (deleted); no kept caller (S1) | **delete** |  |
| `apps/web/test/support/cloud-queue.mjs` | 75 | #1007: synthetic Cloud Queue receipt through HTTP and the web composer. Uses only the repository fake… | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/composer.mjs` | 117 | Shared setup for the composer's proofs (#9 step 3, W7 to W13), on the fake API's send routes. Synthetic… | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/expect.mjs` | 111 | What the page must show for an envelope (V1), written independently of the app's own code: the CLI's text… | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/fake-api.mjs` | 511 | A scripted fake of the web API for the browser proofs. It answers from the test's responders, can hold… | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/fleet-fixtures.ts` | 278 | Synthetic fleets for #125 (spec 3's C1): openwiz fleets --json as the contract's own example 1 prints it… | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/fleet-graph-fixtures.ts` | 287 | Synthetic openwiz fleet <spec> --json envelopes for #126's proofs: the contract's own examples… | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/fleets-page.ts` | 71 | The fleets list (#125) in a page like the app's, for the browser proofs and the renders: its markup inside… | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/harness.mjs` | 29 | Shared setup for the proofs that run against the fake API. | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/launcher.mjs` | 134 | Shared setup for the launcher's proofs (#12, U7 to U15), on the fake API's new-thread routes. Synthetic… | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/newthread-synthetic.ts` | 192 | Synthetic new-thread answers for the launcher's proofs (#12): the Cloud options, the preview, the report… | Web tests; kept: first-hour `providers/recording.ts` imports it (S1, C9) | **delete** |  |
| `apps/web/test/support/paths.mjs` | 7 | Shared helper for the web view tests | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/png.mjs` | 88 | A small PNG reader for the greyscale proofs (V2): 8-bit, non-interlaced, RGB or RGBA, which is what… | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/rust.mjs` | 164 | Ticket 1's openwiz-server, run over one of 0.0.1's fixture scenarios with a verified isolated bundle… | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/serve.mjs` | 150 | A test-only server for out/, with the headers the page needs from openwiz-server once it serves static… | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/style-tokens.ts` | 28 | Test-only reader for the app's base colour tokens and compatibility aliases. | Web view tests only (S1) | **delete** |  |
| `apps/web/test/support/synthetic.ts` | 310 | Synthetic openwiz.inventory.v1 envelopes for the web proofs. Every value is invented: ids are thr_web_NNNN… | Web tests; kept: first-hour `providers/recording.ts` imports it (S1, C9) | **delete** |  |
| `apps/web/test/support/tray.mjs` | 101 | Shared setup for the attachment tray's proofs (#16, AW5 to AW11), on the fake API's attachment routes.… | Web view tests only (S1) | **delete** |  |
| `apps/web/test/unit/api.test.ts` | 194 | V6 and V8 at the request level: same-origin GETs to the contract's routes only, and every response becomes… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/attachments.test.ts` | 702 | The attachment tray's state (#16, B3): AW5's gate (mirrored), AW6's honest states, AW7's safe previews,… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/cockpit-fresh.test.ts` | 44 | #2849: a cockpit part is stale when either device clock says its read is older than 70 seconds, as… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/command.test.ts` | 379 | #537 (0.0.10 T4), CK3: the command bar's parser, a pure function over the page's own data, table-tested… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/composer.test.ts` | 565 | The composer's state (#9 step 3): WS-8's answer table; op ids derived from the draft's root, the mode and… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/contrast.test.ts` | 65 | V2: WCAG AA contrast of the stylesheet's own tokens: 4.5:1 for text, 3:1 for the shapes that tell statuses… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/decision-repository.test.ts` | 91 | Render the actual card tree without a browser. The loader exposes the existing pure Cards component only… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/envelope.test.ts` | 140 | V1: the web accepts exactly the openwiz.inventory.v1 envelope, and nothing outside it. | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/feedback.test.ts` | 142 | #2292: the app's feedback handoff and share (contracts/feedback.v1.md, "Two entry routes" and "Sharing"),… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/first-hour-decisions.test.ts` | 200 | #2514: decision availability at the exported firstHour boundary. Existing first-hour cases omit… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/first-hour-prerequisites.test.ts` | 90 | #2516: fixture proofs at the exported firstHour presentation boundary. Existing fleet cases omit… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/first-hour-recovery.test.ts` | 522 | #2222 (P12 of #2194, PR4 at the contract seam): the first hour's fault cases. | Web unit run; kept: first-hour `providers/README.md` names it (S1, C9) | **delete** |  |
| `apps/web/test/unit/fleet-duplicate-reads.test.ts` | 80 | #829: synthetic fixtures at the public readFleet → fleetModel seam. | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/fleetGraph.test.ts` | 920 | #126 (spec 3's C2): one fleet's drawn graph and its tickets, on fixtures: S3-3 (states read without… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/fleets.test.ts` | 718 | #125 (spec 3's C1): the fleets list, on fixtures. The strict reader of openwiz fleets --json… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/home.test.ts` | 82 | #1030: render the adopted Home at public component seams without a browser. | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/launcher.test.ts` | 329 | The launcher's state (#12): U7, nothing preselected and only offered settings, a switch that empties what… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/markers.test.ts` | 38 | V2 at the vocabulary level: every status keeps its word, and each tier has its own glyph. A word without a… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/newthread.test.ts` | 228 | Synthetic attachments and project references at the three public new-thread parser seams (#464, #636,… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/poller.test.ts` | 311 | V4 and V7 at the loop level: one read in flight, the next only after the last ended or timed out, capped… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/present.test.ts` | 128 | V1 at the text level: values appear word for word, as the CLI prints them; rows sit under the group the… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/pwa.test.ts` | 357 | #1029 (spec #1022's D4, fixture portion): the app is installable. Over the static export (out/, as npm run… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/readyStock.test.ts` | 52 | PA6/PA7 client boundary: optional stock must decode without dropping cockpit. Existing cockpit tests cover… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/statusMark.test.ts` | 64 | Render the shipped SVG component without a browser. Status identity must survive removing colour and… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/support.ts` | 164 | Test doubles for the unit proofs: a manual clock, a page visibility switch and a scripted fetch that… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/t6-sources.test.ts` | 114 | #539 (0.0.10 T6): the web readers accept exactly the new source facts, and the fleets model shows each… | Web view unit run only (S1) | **delete** |  |
| `apps/web/test/unit/viewer.test.ts` | 249 | The page's state: the last good snapshot is kept through failures, the selection survives refreshes (V5),… | Web view unit run only (S1) | **delete** |  |
| `apps/web/tsconfig.json` | 25 | Web view build, config or rules | Other `apps/web` files, its CI lane and the server's `--web-root` (S1) | **delete** |  |

### OpenWiz's copy of the website (`apps/site`)

19 files: 19 delete, 0 fold, 0 keep.

| Path | Lines | What it does | Uses today (search) | Disposition | New home |
| --- | ---: | --- | --- | --- | --- |
| `apps/site/.gitignore` | 1 | OpenWiz's copy of the public site: build or config | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |
| `apps/site/README.md` | 62 | OpenWiz public site | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |
| `apps/site/build.mjs` | 13 | A static export: only the reviewed public assets, without a runtime server. | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |
| `apps/site/changelog/index.html` | 2 | The changelog page (WizSite has its own) | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |
| `apps/site/fonts/Geist-var.woff2` | binary | A font or its licence, for the site | The site's pages only (S2) | **delete** |  |
| `apps/site/fonts/GeistMono-var.woff2` | binary | A font or its licence, for the site | The site's pages only (S2) | **delete** |  |
| `apps/site/fonts/OFL.txt` | 93 | A font or its licence, for the site | The site's pages only (S2) | **delete** |  |
| `apps/site/fonts/Virgil-OFL.txt` | 45 | A font or its licence, for the site | The site's pages only (S2) | **delete** |  |
| `apps/site/fonts/Virgil.woff2` | binary | A font or its licence, for the site | The site's pages only (S2) | **delete** |  |
| `apps/site/index.html` | 52 | The landing page (WizSite has its own) | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |
| `apps/site/package.json` | 10 | openwiz-site | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |
| `apps/site/script.js` | 142 | The ⌘K palette: filter the site's sections and pages, then follow a link. | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |
| `apps/site/style.css` | 654 | openwiz.dev (#1352, page climb E2, "Engraved night", ref | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |
| `apps/site/test/approved-copy.mjs` | 105 | Independent literals from the approved copy and the release claim sources. #1352 (Jake, landing grill… | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |
| `apps/site/test/build.test.mjs` | 122 | A cheap source check before the browser's rendered/hidden-text copy checks. These pages use literal HTML,… | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |
| `apps/site/test/ci.test.mjs` | 31 | Commands moved to the plan executor; preserve every previous obligation. | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |
| `apps/site/test/evidence-1114.md` | 81 | #1114 evidence | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |
| `apps/site/test/site.test.mjs` | 410 | Reuse the repository's approved test tools; the site adds no dependency. | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |
| `apps/site/tokens.css` | 108 | Observatory + command navigation: shared app / landing-page foundation. Import this file before consumer… | Its own build and tests, the site CI lane and release scans (S2, C3, C4, C6) | **delete** |  |

### The local server (`crates/server`)

18 files: 18 delete, 0 fold, 0 keep.

| Path | Lines | What it does | Uses today (search) | Disposition | New home |
| --- | ---: | --- | --- | --- | --- |
| `crates/server/Cargo.toml` | 22 | The loopback HTTP server for the web view | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/build.rs` | 2 | #1148: the compiled product identity, from the CLI's one build script. | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/api.rs` | 565 | The routes: query parsing, the calls into the core, the CLI's outcome mapping, and single-flight with a… | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/attachments.rs` | 349 | The attachment routes (#16, B3): the upload (POST /api/v1/attachments), the list (GET) and the removal… | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/cockpit.rs` | 1690 | GET /api/v1/cockpit (#535, 0.0.10 T2): the cockpit's one read, openwiz.cockpit.v1… | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/decisions.rs` | 918 | Read-only decisions endpoint. Source failures remain explicit, never empty work. | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/fleets.rs` | 346 | Fleet reads (#127): the CLI operations, plus #129's optional verified server-configured orchestrator… | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/http.rs` | 353 | A strict, bounded HTTP/1.1 request head reader and a response writer. | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/lib.rs` | 1399 | openwiz-server: the OpenWiz HTTP API, a thin client of the core like the openwiz CLI. See… | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/loops.rs` | 764 | Local loop switches; trust is supplied by embedding, never an HTTP caller. | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/main.rs` | 315 | The openwiz-server program: the CloudRoom adapter (the verified app bundle, as the openwiz CLI builds it)… | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/new_thread.rs` | 388 | The new-thread routes (#12, A2): the create (POST /api/v1/projects/{id}/threads), the new-thread preview (POST | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/plan.rs` | 845 | Repository plan projection. The HTTP runner owns slots, guards and deadlines. | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/ready_stock.rs` | 497 | Read-only stock assembly from existing bounded readers. Fixture proofs do not establish live coverage or… | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/send.rs` | 474 | The one write (#9): POST /api/v1/sessions/{id}/messages, and the send lookup. See contracts/web-api.v1.md,… | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/setup.rs` | 751 | Installation and connection readiness are separate. No external calls and no file here: lib.rs reads the… | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/src/web.rs` | 332 | The web page: apps/web's static export, from one directory given by --web-root (A8, #46). An explicit list… | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |
| `crates/server/tests/host_names.rs` | 80 | The server's two host-name rules, through its public API: the name an owner may configure for the tunnel… | Only `openwiz-service` (deleted) and server tests; a dev-dependency of `tests`, packaged by install and release (S3, C1, C6, C9) | **delete** |  |

### The service (`crates/service`)

33 files: 33 delete, 0 fold, 0 keep.

| Path | Lines | What it does | Uses today (search) | Disposition | New home |
| --- | ---: | --- | --- | --- | --- |
| `crates/service/Cargo.toml` | 89 | The always-on local service | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/build.rs` | 3 | The service build identity and #1148 product identity, from the one build script the CLI, server and… | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/examples/fixture.rs` | 33 | Test-only verified bundle and job injection. Production has no fixture settings. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/app.rs` | 84 | Shared default App client for tick/health, with an isolated event-read factory. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/bootstrap.rs` | 280 | Installed startup gate. Existing source deployments keep their prior path. Packaged starts require a… | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/document.rs` | 625 | Strict service document readers. The embedded contract supplies the shape; unknown schema rules fail… | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/empty-state.json` | 1 | The always-on local service | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/events/intake.rs` | 448 | #805's transport-independent intake: GitHub deliveries -> L4's router, once. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/events/mod.rs` | 316 | Injected GitHub hints -> fresh fleet facts -> existing send operation. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/events/relay.rs` | 134 | Shared durable relay records for direct events and the fleet check-in. The record is the existing strict… | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/health/loops.rs` | 189 | LP4's pure watchdog planner. No scheduler, I/O, persistence or notification delivery. Inputs must come… | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/health/mod.rs` | 279 | The loops watchdog's health job (LP4): one report-only pass that saves its incidents before it posts their… | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/health/records.rs` | 430 | Contract record formatting and conservative, durable comment reconciliation. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/health/watchdog.rs` | 134 | Independent loop observations, registered through the existing health job. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/lib.rs` | 156 | OpenWiz's PC service: a registered-job scheduler and the embedded HTTP API. #269's approved exception… | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/loops/approval.rs` | 251 | Trusted exact-definition approvals from setup-owned service configuration. This supplies only the existing… | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/loops/check.rs` | 103 | A check's deadline covers exit and EOF, including inherited stdout pipes. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/loops/limits.rs` | 125 | LP1 is a safety fuse solely on loop checks and original loop agents. These capacities do not govern fleet… | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/loops/mod.rs` | 546 | Run approved immutable default-branch definitions through the core planner. Production must supply a… | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/loops/production.rs` | 195 | L12: the existing Runner, installation binding and setup-owned LP1 inputs. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/loops/repository.rs` | 1 | The always-on local service | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/loops/storage.rs` | 1 | The always-on local service | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/main.rs` | 3 | The always-on local service | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/paths.rs` | 67 | Private-state checks. macOS uses an ephemeral owner probe; never reads a key. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/runtime.rs` | 433 | One service process: embedded HTTP, private status IPC and registered jobs. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/scheduler.rs` | 213 | Registered jobs use monotonic elapsed seconds; no job registers itself. A delayed poll skips missed… | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/state.rs` | 112 | The service's owner-only, atomic state. Startup never re-dispatches a try. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/tick.rs` | 92 | The fleet tick's job name, sources and scheduler seam. The service no longer registers the scheduled fleet… | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/update.rs` | 1690 | T6: outbound-only updates. Calls have fixed forms; no shell command string. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/src/web_api.rs` | 102 | Same server implementation, stores, providers and guards as openwiz-server. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/tests/l5_watchdog.rs` | 326 | LP4, synthetic planner observations only. No live runtime or delivery claim. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/tests/t4_paths.rs` | 221 | State-path guards, on private synthetic directories only. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |
| `crates/service/tests/t4_scheduler.rs` | 246 | Synthetic jobs and a controlled monotonic clock; no live tools. | Only its own and `tests/service` tests; packaged by install and release (S4, C1, C6, C7, C9) | **delete** |  |

### The store (`crates/store`)

18 files: 9 delete, 9 fold, 0 keep.

| Path | Lines | What it does | Uses today (search) | Disposition | New home |
| --- | ---: | --- | --- | --- | --- |
| `crates/store/Cargo.toml` | 15 | The `store` crate manifest | Workspace member; `cli` and `tests` depend on it until the fold (S5, C1) | **delete** |  |
| `crates/store/src/attachments.rs` | 2013 | The staged attachments on disk (OpenWiz 0.0.4, B1 phase 2, ClosedWiz#14): the controller's private copy of… | Only `openwiz attachment`, `send`/`new --attach`, the server and attachment tests (S5) | **delete** |  |
| `crates/store/src/lib.rs` | 841 | The send record on disk: one owner-only directory of JSON files that implements the core's [SendStore].… | Kept: `cli` `fleet_tick.rs` and `loops.rs` (`default_state_dir`), `fleet_tick_graph.rs` (via `starts`) (S5) | **fold** | `crates/cli/src/state/mod.rs`, without `FileStore` (send records) |
| `crates/store/src/loops/config.rs` | 149 | Switch context from private install configuration; no discovery process. | Kept: `cli` `loops.rs:95` (`installed`, the trusted loop context of `openwiz loop on/off`), `tests/loops/l6_config.rs` (S5) | **fold** | `crates/cli/src/state/loops/config.rs`, reading the same `service/config.json` (see "The loop configuration") |
| `crates/store/src/loops/document.rs` | 339 | Strict loop documents; validation reads the compiled loops.v1 schema. | Kept: `cli` `loops.rs` through `config.rs` (`service_config`, the loop config check), `tests/loops/*` (S5, S9) | **fold** | `crates/cli/src/state/loops/document.rs`; only its two `include_str!` paths (to the kept `contracts/loops.v1.schema.json` and `contracts/service.v1.schema.json`) change, for the new depth |
| `crates/store/src/loops/mod.rs` | 199 | Local, durable switches for OpenWiz definitions. No CloudRoom loop calls. | Kept: `cli` `loops.rs` (`openwiz loop`), `tests/loops/*` (S5) | **fold** | `crates/cli/src/state/loops/` (same names) |
| `crates/store/src/loops/paths.rs` | 555 | Private-state checks. macOS uses an ephemeral owner probe; never reads a key. | Kept: `cli` `loops.rs` (`openwiz loop`), `tests/loops/*` (S5) | **fold** | `crates/cli/src/state/loops/` (same names) |
| `crates/store/src/loops/repository.rs` | 508 | Read immutable blobs from the checkout's verified default-branch ref. | Kept: `cli` `loops.rs` (`openwiz loop`), `tests/loops/*` (S5) | **fold** | `crates/cli/src/state/loops/` (same names) |
| `crates/store/src/loops/storage.rs` | 414 | One owner per pass and atomic, synced private records. No repository writes. | Kept: `cli` `loops.rs` (`openwiz loop`), `tests/loops/*` (S5) | **fold** | `crates/cli/src/state/loops/` (same names) |
| `crates/store/src/new_thread.rs` | 104 | The new-thread record on disk (OpenWiz 0.0.4, A1 phase 2): the new_thread record kind, in the same state… | Only `openwiz new`, the server and new-thread tests (S5) | **delete** |  |
| `crates/store/src/setup.rs` | 803 | The setup state (#1105): <state>/setup/state.json, openwiz.setup-state.v1. | Only the server's `GET /api/v1/setup` and `tests/service` (S5); the setup tools write the file in Python | **delete** |  |
| `crates/store/src/starts.rs` | 361 | The start record on disk (OpenWiz 0.0.6 spec 2, B4, ClosedWiz#120): one record per start (a ticket's… | Kept: `cli` `fleet_tick_graph.rs` (`StartFileStore`), `tests/fleet/b4_record.rs` (S5) | **fold** | `crates/cli/src/state/starts.rs` |
| `crates/store/tests/attachments/ap04_ready.rs` | 310 | AP4 Ready means verified, the store's half. ready is set only after the copy is synced, renamed, made… | Proves the attachment store only (S5) | **delete** |  |
| `crates/store/tests/attachments/ap05_originals.rs` | 94 | AP5 Originals unchanged, the store's half: whatever is at the source's path when it is opened must be the… | Proves the attachment store only (S5) | **delete** |  |
| `crates/store/tests/attachments/ap07_low_disk.rs` | 201 | AP7 Low disk, the store's half. Staging is refused, with "low disk", when it would leave less than 1 GiB… | Proves the attachment store only (S5) | **delete** |  |
| `crates/store/tests/attachments/bench.rs` | 182 | A private source directory and state directory for each test, outside the repository, the store opened on… | Proves the attachment store only (S5) | **delete** |  |
| `crates/store/tests/attachments/main.rs` | 16 | The attachment staging proof cases that need only openwiz-store (#14): AP4's order of durable steps and… | Proves the attachment store only (S5) | **delete** |  |
| `crates/store/tests/state_dir.rs` | 276 | The send store's state directory: where it is by default, that it is never inside a repository, and that… | Proves `default_state_dir`, which the kept `fleet` and `loop` commands use (S5) | **fold** | `crates/cli/tests/state_dir.rs` |

### Act-from-the-UI pieces in the core, command line and adapters

36 files: 8 delete, 0 fold, 28 keep.

| Path | Lines | What it does | Uses today (search) | Disposition | New home |
| --- | ---: | --- | --- | --- | --- |
| `crates/adapters/cloudroom/src/messaging.rs` | 748 | The CloudRoom side of send: the target read and the one write, thread tell, translated for the core's… | Kept: `loops.rs`'s `ProjectMessenger` delegates to it (the engine's loop messages) (S6) | **keep** |  |
| `crates/adapters/cloudroom/src/new_thread.rs` | 879 | The CloudRoom side of new threads (OpenWiz 0.0.4, ClosedWiz#11): the [NewThreadClient] the core calls (A1… | Kept: `allowlist.rs` (`HARNESS_PROVIDERS`, `CLI_REASONING_LEVELS`) and the engine's starts through core `new_thread` (S6) | **keep** |  |
| `crates/adapters/cloudroom/tests/new_thread_readers.rs` | 265 | The new-thread readers of room-cli's answers, through the adapter's public functions alone: the spawn… | Proves the kept spawn readers (S6) | **keep** |  |
| `crates/cli/src/attach.rs` | 145 | --attach <path> and --attachment <id> on openwiz send and openwiz new (OpenWiz 0.0.4, B2, ClosedWiz#15):… | Only `main.rs`'s `send`, `new`, `models` and `attachment` dispatch and `response.rs`'s `new` flag table (S7, C7) | **delete** |  |
| `crates/cli/src/attachment.rs` | 518 | openwiz attachment add / ls / rm (OpenWiz 0.0.4, B1 phase 2, ClosedWiz#14): parse the command line, call… | Only `main.rs`'s `send`, `new`, `models` and `attachment` dispatch and `response.rs`'s `new` flag table (S7, C7) | **delete** |  |
| `crates/cli/src/new_thread.rs` | 990 | openwiz new, openwiz new --status and openwiz models (OpenWiz 0.0.4, ClosedWiz#11): parse the command… | Only `main.rs`'s `send`, `new`, `models` and `attachment` dispatch and `response.rs`'s `new` flag table (S7, C7) | **delete** |  |
| `crates/cli/src/send.rs` | 715 | openwiz send: parses the command line, calls the core's send, and prints its report as text or as… | Only `main.rs`'s `send`, `new`, `models` and `attachment` dispatch and `response.rs`'s `new` flag table (S7, C7) | **delete** |  |
| `crates/core/src/attachment.rs` | 1068 | Attachments: OpenWiz 0.0.4's file model (B1 phase 1, ClosedWiz#14). | Kept: `prompt.rs` and `cloudroom` `allowlist.rs` use its types, so the start record's prompt digest reads unchanged (S6, D3) | **keep** |  |
| `crates/core/src/messaging/effects.rs` | 218 | What a send is expected to do, worked out before sending from one read of the target, and shown with that… | Kept: the engine. `cloudroom` `loops.rs` sends loop messages through `send::Messenger`; core `fleet/starts.rs`, `fleet/tick`, `loops` and `cli` `fleet_tick_*` use `OpId`, `record` and `sha256_hex` (S6) | **keep** |  |
| `crates/core/src/messaging/lookup.rs` | 102 | lookup: one op id's send record, as a report, or "no record". For "Check again": it never claims the op… | Only `openwiz send --check` and the server's send status route (S6) | **delete** |  |
| `crates/core/src/messaging/mod.rs` | 256 | Messaging: OpenWiz's one write, send. It delivers one text message to one existing session and reports… | Kept: the engine. `cloudroom` `loops.rs` sends loop messages through `send::Messenger`; core `fleet/starts.rs`, `fleet/tick`, `loops` and `cli` `fleet_tick_*` use `OpId`, `record` and `sha256_hex` (S6) | **keep** |  |
| `crates/core/src/messaging/preview.rs` | 219 | preview: what a send to one target in one mode would do, worked out before any text is written. It reads… | Kept: the kept `send.rs`'s send operation calls it (S6, L2) | **keep** |  |
| `crates/core/src/messaging/reconcile.rs` | 81 | The rule for a lost acknowledgement. | Kept: the kept `send.rs`'s send operation calls it (S6, L2) | **keep** |  |
| `crates/core/src/messaging/record.rs` | 251 | The send record, the interface of its store, and the recovery rule. | Kept: the engine. `cloudroom` `loops.rs` sends loop messages through `send::Messenger`; core `fleet/starts.rs`, `fleet/tick`, `loops` and `cli` `fleet_tick_*` use `OpId`, `record` and `sha256_hex` (S6) | **keep** |  |
| `crates/core/src/messaging/send.rs` | 1213 | The send operation: one text message to one existing session, one provider call per op id, and an honest… | Kept: the engine. `cloudroom` `loops.rs` sends loop messages through `send::Messenger`; core `fleet/starts.rs`, `fleet/tick`, `loops` and `cli` `fleet_tick_*` use `OpId`, `record` and `sha256_hex` (S6) | **keep** |  |
| `crates/core/src/messaging/sha256.rs` | 124 | SHA-256 (FIPS 180-4), for the text hash an op id is bound to, and for each staged attachment's bytes… | Kept: the engine. `cloudroom` `loops.rs` sends loop messages through `send::Messenger`; core `fleet/starts.rs`, `fleet/tick`, `loops` and `cli` `fleet_tick_*` use `OpId`, `record` and `sha256_hex` (S6) | **keep** |  |
| `crates/core/src/new_thread/effects.rs` | 323 | What a create does, worked out before creating, in the core's words, and the project rules it starts from… | Kept: the engine. Core `fleet/starts.rs` starts agents through `operation`, `outcome`, `record` and `status`; `cloudroom` `loops.rs`, `loop_files.rs` and `github` `tick.rs` use `read::StrictJson` (S6) | **keep** |  |
| `crates/core/src/new_thread/mod.rs` | 262 | New threads: OpenWiz 0.0.4's start of one new Cloud thread in one existing project, with the harness,… | Kept: the engine. Core `fleet/starts.rs` starts agents through `operation`, `outcome`, `record` and `status`; `cloudroom` `loops.rs`, `loop_files.rs` and `github` `tick.rs` use `read::StrictJson` (S6) | **keep** |  |
| `crates/core/src/new_thread/operation.rs` | 767 | The new_thread operation: one new Cloud thread in one existing project, one provider call per op id, and… | Kept: the engine. Core `fleet/starts.rs` starts agents through `operation`, `outcome`, `record` and `status`; `cloudroom` `loops.rs`, `loop_files.rs` and `github` `tick.rs` use `read::StrictJson` (S6) | **keep** |  |
| `crates/core/src/new_thread/options.rs` | 378 | The Cloud options: which harnesses, models and efforts CloudRoom reports right now, and nothing else. | Kept: the engine. Core `fleet/starts.rs` starts agents through `operation`, `outcome`, `record` and `status`; `cloudroom` `loops.rs`, `loop_files.rs` and `github` `tick.rs` use `read::StrictJson` (S6) | **keep** |  |
| `crates/core/src/new_thread/outcome.rs` | 295 | What a create came to: created, refused, failed or uncertain. | Kept: the engine. Core `fleet/starts.rs` starts agents through `operation`, `outcome`, `record` and `status`; `cloudroom` `loops.rs`, `loop_files.rs` and `github` `tick.rs` use `read::StrictJson` (S6) | **keep** |  |
| `crates/core/src/new_thread/read.rs` | 729 | Reading a stored new-thread record back (A1 phase 2): hand-written and strict, never serde's derived readers. | Kept: the engine. Core `fleet/starts.rs` starts agents through `operation`, `outcome`, `record` and `status`; `cloudroom` `loops.rs`, `loop_files.rs` and `github` `tick.rs` use `read::StrictJson` (S6) | **keep** |  |
| `crates/core/src/new_thread/record.rs` | 209 | The new-thread record, the interface of its store, and the recovery rule. | Kept: the engine. Core `fleet/starts.rs` starts agents through `operation`, `outcome`, `record` and `status`; `cloudroom` `loops.rs`, `loop_files.rs` and `github` `tick.rs` use `read::StrictJson` (S6) | **keep** |  |
| `crates/core/src/new_thread/start.rs` | 274 | After creation: the start stage and the reported configuration, from one thread show read (sheet A-4: no… | Kept: the engine. Core `fleet/starts.rs` starts agents through `operation`, `outcome`, `record` and `status`; `cloudroom` `loops.rs`, `loop_files.rs` and `github` `tick.rs` use `read::StrictJson` (S6) | **keep** |  |
| `crates/core/src/new_thread/status.rs` | 143 | new_thread_status: one op id's record and, once created, its start stage. **Read-only:** it never creates,… | Kept: the engine. Core `fleet/starts.rs` starts agents through `operation`, `outcome`, `record` and `status`; `cloudroom` `loops.rs`, `loop_files.rs` and `github` `tick.rs` use `read::StrictJson` (S6) | **keep** |  |
| `crates/core/src/notifications/mod.rs` | 4 | The notification types the ready stock and Decisions still read (0.0.15 T1, T6). Push notifications are… | Only the server's cockpit, ready stock and Decisions routes, `tests/notifications` and `tests/web-api` (S6) | **delete** |  |
| `crates/core/src/notifications/model.rs` | 698 | Strict versioned contract types, not source verification or notification policy. Deserialize checks wire… | Only the server's cockpit, ready stock and Decisions routes, `tests/notifications` and `tests/web-api` (S6) | **delete** |  |
| `crates/core/src/notifications/stock.rs` | 334 | Ready-stock policy over independently read facts. No I/O or work authority. | Only the server's cockpit, ready stock and Decisions routes, `tests/notifications` and `tests/web-api` (S6) | **delete** |  |
| `crates/core/src/prompt.rs` | 524 | The prompt payload that send and new_thread share (OpenWiz 0.0.4), and the one gate both pass before… | Kept: core `fleet/starts.rs` (`PromptPayload`, `attachments_digest`) and `cloudroom` `allowlist.rs` (S6) | **keep** |  |
| `crates/core/tests/attachment/ap01_kind.rs` | 407 | AP1 Kind from bytes. PNG, JPEG, GIF and WebP are images; HEIC and HEIF are refused with the stated reason;… | Proves the kept core attachment types (S6, D3) | **keep** |  |
| `crates/core/tests/attachment/ap02_limits.rs` | 135 | AP2 Provider limits only. 10 MiB per image and 25 MiB per file, except a file whose extension CloudRoom… | Proves the kept core attachment types (S6, D3) | **keep** |  |
| `crates/core/tests/attachment/ap03_safe_names.rs` | 340 | AP3 Safe names. Whatever the owner's file is called, the **staged name** OpenWiz hands to CloudRoom is a… | Proves the kept core attachment types (S6, D3) | **keep** |  |
| `crates/core/tests/attachment/main.rs` | 18 | The attachment model's proof cases that need only openwiz-core (#14): AP1 kind from bytes, AP2's limits,… | Proves the kept core attachment types (S6, D3) | **keep** |  |
| `crates/core/tests/attachment/rules.rs` | 181 | The readiness, retention and free-disk rules (B-2, B-3, B-6) that phase 2's store follows. Pure functions… | Proves the kept core attachment types (S6, D3) | **keep** |  |
| `crates/core/tests/attachment/sha256_stream.rs` | 107 | The streaming SHA-256 (Sha256Hasher) that staging hashes with: the same hash as sha256_hex of the whole… | Proves the kept core attachment types (S6, D3) | **keep** |  |
| `crates/core/tests/attachment/support.rs` | 61 | Synthetic file bytes for the attachment proofs, built in memory at test time (never committed). The same… | Proves the kept core attachment types (S6, D3) | **keep** |  |

### Their tests

182 files: 153 delete, 2 fold, 27 keep.

| Path | Lines | What it does | Uses today (search) | Disposition | New home |
| --- | ---: | --- | --- | --- | --- |
| `tests/attachments/ad_static.rs` | 575 | B2 (ClosedWiz#15): the rules and the static checks. AD8 (no stronger claim), AD11 (one implementation),… | Proves kept core `prompt` rules (digest, gate) and the allowlist's one `attachment_args` (S8, D3) | **keep** |  |
| `tests/attachments/ap02_limits.rs` | 32 | AP2 Provider limits only, the store and CLI half: the store stages 200 small files in one add, and the… | Only its target; it runs the attachment store or `openwiz attachment`, which go (S8, D2) | **delete** |  |
| `tests/attachments/ap04_ready.rs` | 85 | AP4 Ready means verified. Stopping the process right after each staging step leaves either nothing usable… | Only its target; it runs the attachment store or `openwiz attachment`, which go (S8, D2) | **delete** |  |
| `tests/attachments/ap05_originals.rs` | 189 | AP5 Originals unchanged. The hash, size, mtime and mode of every source file are the same after add,… | Only its target; it runs the attachment store or `openwiz attachment`, which go (S8, D2) | **delete** |  |
| `tests/attachments/ap06_streaming.rs` | 78 | AP6 Streaming. A file at its size limit is staged with bounded memory, measured: the child process's peak… | Only its target; it runs the attachment store or `openwiz attachment`, which go (S8, D2) | **delete** |  |
| `tests/attachments/ap07_low_disk.rs` | 174 | AP7 Low disk, the CLI's half and the real measure: add says "low disk" and exits 5, free space that can't… | Only its target; it runs the attachment store or `openwiz attachment`, which go (S8, D2) | **delete** |  |
| `tests/attachments/ap08_removal_expiry.rs` | 694 | AP8 Removal and expiry. rm deletes the bytes and the metadata. A ready attachment no operation has claimed… | Only its target; it runs the attachment store or `openwiz attachment`, which go (S8, D2) | **delete** |  |
| `tests/attachments/ap09_owner_only.rs` | 127 | AP9 Owner-only storage. Every directory the store makes is 0700, the staged copy 0400 and the store's own… | Only its target; it runs the attachment store or `openwiz attachment`, which go (S8, D2) | **delete** |  |
| `tests/attachments/ap10_no_dispatch.rs` | 136 | AP10 No dispatch path. Phase 1 adds no room-cli call: the model names no invocation, no process and no… | Proves the kept allowlist names each attachment flag once (S8, D3) | **keep** |  |
| `tests/attachments/ap11_cli.rs` | 770 | AP11, the CLI half. openwiz attachment add reports every path, in the order given, and one failure hides… | Only its target; it runs the attachment store or `openwiz attachment`, which go (S8, D2) | **delete** |  |
| `tests/attachments/ap11_schema.rs` | 230 | AP11, the schema half: contracts/attachment.v1.schema.json describes exactly what the core serializes: the… | Proves the kept `attachment.v1` schema (S8, D3) | **keep** |  |
| `tests/attachments/ap12_logs.rs` | 68 | AP12 Logs are clean. OpenWiz's only log is stderr: every run in this suite goes through the bench, which… | Only its target; it runs the attachment store or `openwiz attachment`, which go (S8, D2) | **delete** |  |
| `tests/attachments/bench.rs` | 380 | The phase 2 bench: a private source directory and state directory for each test, outside the repository,… | Only its target; it runs the attachment store or `openwiz attachment`, which go (S8, D2) | **delete** |  |
| `tests/attachments/child.rs` | 121 | The self-exec child: this test binary, run again as its own process, stages one file through the store,… | Only its target; it runs the attachment store or `openwiz attachment`, which go (S8, D2) | **delete** |  |
| `tests/attachments/main.rs` | 64 | The OpenWiz 0.0.4 attachment proof cases (AP), ClosedWiz#14. Each case was written before the behaviour,… | Shared by this target's kept files; AP11 drops only its helpers for deleted parts (S8) | **keep** |  |
| `tests/attachments/parity.rs` | 315 | AP11, the schema half: **one table of JSON**, each row read by the core and checked by the schema, and… | Proves the kept core reads and the schema agree (S8, D3) | **keep** |  |
| `tests/attachments/program.rs` | 79 | The release openwiz attachment add, ls, rm, as processes: the real free-space measure (/bin/df, sheet… | Only its target; it runs the attachment store or `openwiz attachment`, which go (S8, D2) | **delete** |  |
| `tests/attachments/staging.rs` | 134 | Staged attachments for the B2 proofs (ClosedWiz#15), shared by the messaging and new-thread targets… | Only its target; it runs the attachment store or `openwiz attachment`, which go (S8, D2) | **delete** |  |
| `tests/attachments/support.rs` | 66 | Shared helpers for the attachment proofs: synthetic file bytes, built in memory at test time (never… | Shared by this target's kept files; AP11 drops only its helpers for deleted parts (S8) | **keep** |  |
| `tests/fixture-entrypoints/server.rs` | 10 | Test-only server: exact production dispatch, private verified fake bundle. | Only the `openwiz-server` fixture binary for server and service tests (S8) | **delete** |  |
| `tests/loops/l6_api.rs` | 498 | LP5 HTTP seam, private fixtures with explicit trusted operator context. | Proves the server's loop routes (`openwiz_server`) only (S8) | **delete** |  |
| `tests/loops/l6_executor.rs` | 241 | LP5: real scheduler, synthetic checks and never a live provider. | Proves the service's loop scheduler (`openwiz_service`); registered by `crates/service/Cargo.toml` (S8) | **delete** |  |
| `tests/messaging/ad_send_attachments.rs` | 1358 | B2 (ClosedWiz#15): attachments in send. AD1 to AD5, AD7, AD9, AD10 and AD13's send half, on the fake… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m01_exact_invocation.rs` | 213 | M1 Exact invocation: one thread tell per send, with an explicit --mode and --json, never auto, a default… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m02_one_target.rs` | 150 | M2 One target: exactly one id, resolved in the same operation. Not found means zero tell calls. Archived… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m03_mode_rules.rs` | 89 | M3 Mode rules: the requested mode is the one passed: queue by default, steer only when asked for, never… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m04_outcome_mapping.rs` | 1043 | M4 Outcome mapping, for every row of the receipt table. The requested mode and the reported delivery are… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m05_effects.rs` | 657 | M5 Effects are worked out before sending, with the read's age, for every state. A queue that appears… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m06_lost_acknowledgement.rs` | 276 | M6 Lost acknowledgement: a room-cli that accepts and then times out gives uncertain, keeps the text and… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m07_op_id_binding.rs` | 166 | M7 Op-id binding: the same op id with the same target, mode and text makes one call. The same op id with… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m08_cross_process_claim.rs` | 129 | M8 Claiming across processes: many processes racing on one op id make exactly one tell call, counted… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m09_crash_recovery.rs` | 298 | M9 Crash recovery: a sender killed at each step gives the recovery table's outcome, and nothing is ever… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m10_record.rs` | 309 | M10 The record is synced, readable by the owner only, outside the repository, and correct under concurrent… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m11_inventory_unchanged.rs` | 58 | M11 The inventory is unchanged: P1 to P12 still pass (the proof test binary, unchanged apart from P8(a)… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m12_allowlist.rs` | 629 | M12 Allowlist: thread tell is send's only write, and every other mutating subcommand is still refused.… | Proves the kept allowlist's `tell` shape, which the engine's loop messages use (S8) | **keep** |  |
| `tests/messaging/m13_drift.rs` | 529 | M13 Drift: an unexpected receipt shape gives uncertain with a gap, never accepted. Since #37 the room-cli… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m14_cli.rs` | 805 | M14 CLI: --json matches the text, the JSON matches contracts/messaging.v1.schema.json, and each outcome's… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m15_text_only.rs` | 96 | M15 Text only: a file path in the text is sent as text, never uploaded or read. | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m16_preview.rs` | 525 | M16 Preview (#79, sheet U5): what a send to one target in one mode would do, before any text is written.… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m17_lookup.rs` | 465 | M17 Lookup (#79, sheet U6): one op id's send record, for "Check again". A known op id gives its recorded… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/m18_in_flight.rs` | 707 | M18 The in-flight guard (#79, sheet U7): a new op id whose target, mode and text match a send still… | Only its target; it runs `openwiz send` or its `FileStore` record, which go (S8, D2) | **delete** |  |
| `tests/messaging/main.rs` | 57 | The OpenWiz 0.0.3 messaging proof cases, M1 to M15 (ClosedWiz#8), and M16 to M18 (#79: preview, lookup and… | Shared by this target's kept files; AP11 drops only its helpers for deleted parts (S8) | **keep** |  |
| `tests/messaging/structure.rs` | 159 | Structure: every label and shape the core serializes for send is in the published messaging schema. | Proves the kept core serializes only labels in `messaging.v1` (S8) | **keep** |  |
| `tests/messaging/support.rs` | 594 | Shared helpers for the messaging proofs: the fake room-cli set to a send scenario, a private state… | Shared by this target's kept files; AP11 drops only its helpers for deleted parts (S8) | **keep** |  |
| `tests/new-thread/ad_new_thread_attachments.rs` | 696 | B2 (ClosedWiz#15): attachments in new_thread. AD1's spawn half, AD4, AD6, AD7, AD9, AD10 and AD13's new… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/boundary_readers.rs` | 368 | Sol, round 1, R2: the two JSON documents room-cli hands a create, the spawn receipt and the cloud status… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/contract_tables.rs` | 451 | One table of good and bad JSON per contract (Sol re-check, round 2). | Proves kept core rules through the core and an in-memory store or fake client (S8) | **keep** |  |
| `tests/new-thread/fake.rs` | 593 | The new-thread proofs' fake room-cli (A1 phase 2): a private copy of the repository's fake per test, a… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/harness.rs` | 189 | The self-exec harness: this test binary, run again as its own process, calls the core's new_thread with… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/inspect_claim_race.rs` | 141 | #244: hold the inspection/fork/claim window open at the store seam. The inspection fixture gives a child a… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/main.rs` | 76 | The OpenWiz 0.0.4 new-thread proof cases (ClosedWiz#11), each written before the behaviour. A1 phase 1: N1… | Shared by this target's kept files; AP11 drops only its helpers for deleted parts (S8) | **keep** |  |
| `tests/new-thread/n01_end_to_end.rs` | 202 | N1 end to end (A1 phase 2): openwiz new --yes makes exactly one thread spawn, with --project, --machine… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/n02_no_rewrite.rs` | 224 | N2 (sheet A-15): no rewrite. Every room-cli call runs without ROOM_THREAD_ID, ROOM_PROJECT_ID or any BB_*… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/n03_existing_projects.rs` | 182 | N3 Existing projects only (sheet A-5): the project is read with project list in the same run, and only a… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/n04_offered_only.rs` | 417 | N4: offered combinations only. A harness, model or effort outside the same-run catalogue is refused with… | Proves kept core rules through the core and an in-memory store or fake client (S8); AP11 drops its `openwiz new` cases | **keep** |  |
| `tests/new-thread/n05_honest_options.rs` | 119 | N5: honest options. The read time, the saved-copy label and the unavailable harnesses with their reasons;… | Proves kept core rules through the core and an in-memory store or fake client (S8) | **keep** |  |
| `tests/new-thread/n06_outcome_mapping.rs` | 245 | N6: outcome mapping for every row of the result table. Created never implies started. | Proves kept core rules through the core and an in-memory store or fake client (S8) | **keep** |  |
| `tests/new-thread/n07_requested_and_reported.rs` | 116 | N7: requested and reported stay separate. A reported harness, model or effort that differs from the… | Proves kept core rules through the core and an in-memory store or fake client (S8) | **keep** |  |
| `tests/new-thread/n08_start_stages.rs` | 146 | N8: start stages for every status row, separate from creation, within the follow bound (sheet A-9).… | Proves kept core rules through the core and an in-memory store or fake client (S8) | **keep** |  |
| `tests/new-thread/n09_lost_acknowledgement.rs` | 254 | N9 Lost acknowledgement: a fake that creates the thread and then never answers gives **uncertain**, keeps… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/n10_no_retry.rs` | 79 | N10, the refusal half only (sheet A-3: no retry in 0.0.4). There is no --retry and no retry operation:… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/n11_op_id_binding.rs` | 176 | N11: op-id binding. The same op id and binding make one call; any difference is refused with zero calls.… | Proves kept core rules through the core and an in-memory store or fake client (S8) | **keep** |  |
| `tests/new-thread/n12_cross_process_claim.rs` | 140 | N12 Claiming across processes: many processes racing on one op id make exactly one spawn call, counted… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/n13_crash_recovery.rs` | 321 | N13 Crash recovery: a create stopped at each step gives the recovery table's outcome, and nothing is… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/n14_prompt_seam.rs` | 117 | N14: the prompt seam. A file path in the text is sent as text; the empty list has its fixed digest on… | Proves kept core rules through the core and an in-memory store or fake client (S8) | **keep** |  |
| `tests/new-thread/n15_nothing_else_changes.rs` | 51 | N15 Nothing else changes: the inventory and send keep their behaviour (P1 to P12 and M1 to M18 run… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/n16_allowlist.rs` | 124 | N16 Allowlist (sheet A-2): thread spawn and cloud status are the only additions, each in exactly the shape… | Proves kept core rules through the core and an in-memory store or fake client (S8) | **keep** |  |
| `tests/new-thread/n17_drift.rs` | 219 | N17: drift. An unexpected receipt shape gives uncertain with a gap; an unexpected catalogue shape gives no… | Proves kept core rules through the core and an in-memory store or fake client (S8); AP11 drops its `openwiz new` cases | **keep** |  |
| `tests/new-thread/n18_cli.rs` | 992 | N18, the CLI half (A1 phase 2), and N5's: openwiz new prints the effects and the exact command before… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/n18_report.rs` | 231 | N18, the core's half (the CLI's is phase 2's): the report, the record and the preview match… | Proves kept core rules through the core and an in-memory store or fake client (S8) | **keep** |  |
| `tests/new-thread/n19_status_read_only.rs` | 259 | N19: status is read-only. new_thread_status makes zero spawn calls and no write, for every record state;… | Proves kept core rules through the core and an in-memory store or fake client (S8) | **keep** |  |
| `tests/new-thread/pattern.rs` | 378 | Two keywords for the new-thread and prompt schemas (Sol round 1, finding 2), on top of the shared checker… | Proves kept core rules through the core and an in-memory store or fake client (S8) | **keep** |  |
| `tests/new-thread/record_load.rs` | 130 | #244: binding reads expose the stored record without inspecting its owner's lock or recovering it. The… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/record_store.rs` | 489 | The new_thread record kind in openwiz-store (A1 phase 2): owner-only, outside every repository, beside the… | Only its target; it runs `openwiz new` as a process or CLI call, or `NewThreadFileStore`, which go (S8, D2) | **delete** |  |
| `tests/new-thread/schema_parity.rs` | 337 | Schema parity (Sol round 1, finding 2): contracts/prompt.v1.schema.json and… | Proves kept core rules through the core and an in-memory store or fake client (S8) | **keep** |  |
| `tests/new-thread/structure.rs` | 119 | Structure: every label the core can serialize is in the schema. | Proves kept core rules through the core and an in-memory store or fake client (S8) | **keep** |  |
| `tests/new-thread/support.rs` | 461 | Shared helpers for the new-thread proofs: the fixtures, a fixed clock, an in-memory record store… | Shared by this target's kept files; AP11 drops only its helpers for deleted parts (S8) | **keep** |  |
| `tests/notifications/main.rs` | 3 | The kept core ready-stock module's tests (0.0.15 T6). Push notifications are retired (0.0.17 ER4). | Only the `notifications` target, which proves core `notifications` (deleted) (S8) | **delete** |  |
| `tests/notifications/stock.rs` | 155 | PA6: source-fact classification, which T1's shape/arithmetic checks do not exercise. | Only the `notifications` target, which proves core `notifications` (deleted) (S8) | **delete** |  |
| `tests/send-harness/main.rs` | 188 | A store-level send harness. Test-only: never built into openwiz. | Only `tests/messaging` (its `send-harness` binary) and needs `FileStore` (S8) | **delete** |  |
| `tests/service/fixtures/engine_environment.py` | 40 | Synthetic installed manager -> service-fixture environment, never a supervisor. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/fixtures/t4-completion-approval.md` | 16 | Service proof | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/install_engine_app.rs` | 142 | T4: real updater + shared App client + T1 outcome sink, recording tools only. synthetic_assumptions: token… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/install_engine_app_support.rs` | 280 | Shared native App fixture; no live exchange or account operations. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/install_engine_loops.rs` | 163 | AC3: native loop consumer, actual scheduler, fresh processes and durable files. Synthetic immutable… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/install_engine_reads.rs` | 505 | IF5's embedded read composition, through the real service dispatch. All GitHub and CloudRoom responses are… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/install_engine_record_factory.rs` | 128 | Granted default factory seam: packaged config -> real App client -> T1 sink. Native recording endpoint and… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/install_engine_target.rs` | 104 | Existing configured target file boundary, with synthetic private documents. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l10_approval.rs` | 768 | LP1 production approval proofs. Every identity, record and check is synthetic. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l11_limits.rs` | 189 | Synthetic LP1/LP2: strict configuration projection at the planner/runner seam. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l11_limits/planner.rs` | 200 | Existing work consumes its own normal/urgent portions and total slots. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l11_limits/runner.rs` | 422 | Recording new-thread client; actual runner, Git definitions and durable stores. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l12_registration.rs` | 1272 | L12 production composition proofs; synthetic inputs only. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l3_capacity.rs` | 286 | Planner admission remains enforced at the executor's public seam. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l3_contract.rs` | 106 | The executor's strict reader and an independent schema checker agree. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l3_runner.rs` | 1202 | LP1: real executor, private Git checkout/state, fake room-cli and clock. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l4_events.rs` | 716 | LP3 injected-router proofs. Synthetic source, current fleet reads and sends; no production transport or… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l4_relay.rs` | 190 | The direct route and #694's check-in client use this same public store/key. All clients/providers here are… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l4_support.rs` | 316 | Service proof | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l4b_auth.rs` | 420 | Synthetic App boundary: fixed scopes, identity, isolated cache and child env. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l4b_composition.rs` | 313 | Production composition over synthetic GitHub documents and a fake room-cli. synthetic_assumptions: all API… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l4b_intake.rs` | 467 | LP3's production half, transport-independent (#805): GitHub deliveries -> L4's router, once. Every payload… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l4b_transport.rs` | 445 | Option A synthetic configuration and allowlist boundaries, never live. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l5b_observation.rs` | 337 | Synthetic LP4 regression: health must read a run while its executor owns Storage. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/l5b_watchdog.rs` | 576 | LP4 production health boundary on synthetic sources and private state only. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/main.rs` | 11 | OpenWiz 0.0.8 (spec #262, close the Mac for good): the always-on service's proofs, one file per ticket, so… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t2_bundle_pair.rs` | 925 | BX1 (#2098): CloudRoom runs one app as two mounts of the same AppImage file: the GUI on one mount, and its… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t2_docs.rs` | 137 | R3: the documented synthetic-server command must serve the recording fake. Red run (2026-11-01): selecting… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t2_locate.rs` | 802 | #267's fixture-only layout and marker checks. Ownership cases use synthetic metadata; the executable… | Proves the kept CloudRoom adapter's bundle location (`locate.rs`) only; no service code (S8) | **fold** | `tests/proof/t2_locate.rs` (a module of the `proof` target) |
| `tests/service/t2_process.rs` | 780 | Verified bundle calls through the same CLI/server dispatch as production. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t4_reader.rs` | 400 | Independent schema checker versus the service's strict public reader. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t4_service.rs` | 608 | C2: the real service dispatch, isolated fake bundle, real HTTP and local IPC. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t4_setup.rs` | 252 | Execute the documented setup blocks only against synthetic files and tools. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t4_unit.rs` | 57 | C2 fixture proof of the user unit's rules. Live kill/reboot belongs to T11. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t6_fixture.rs` | 725 | The real release program of this repository's clean HEAD, with build identity identity (#1253). Each pair… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t6_program.rs` | 50 | Copied into a disposable Git repository by the T6 process fixtures. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t6_update.rs` | 1787 | C5: synthetic repositories/processes only, never a live update. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t7_app.rs` | 463 | C6/C7 on synthetic fixtures. The shared client seam, never a live tick. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t7_deadline.rs` | 200 | R1: each public-client caller keeps its own budget during a shared refresh. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t7_fake_gh.rs` | 53 | The same Rust test executable supplies fake gh, without Python or Node. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t7_forms.rs` | 139 | Literal examples of every existing gh form, through the public service executor. These are transport… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t7_privacy.rs` | 245 | Only the recording fake deliberately saves the synthetic child credential in this one transcript. The App… | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t7_python.rs` | 24 | CI may install Python only after cargo test. The Rust proofs must not need it. | Only the `service` target and `crates/service`'s `[[test]]` entries (S8) | **delete** |  |
| `tests/service/t7_transport.rs` | 111 | Check the production curl config with a local HTTP fixture. Only this test substitutes the URL and TLS… | Kept: `crates/adapters/github/src/app.rs` compiles it as its `transport_tests` module; also embedded by `t6_fixture.rs` (deleted) (S8, C13) | **fold** | `crates/adapters/github/src/app_transport_tests.rs` (still `app.rs`'s `#[path]` test module) |
| `tests/web-api/a3_loopback.rs` | 210 | A3 (fixture part): the server listens on loopback only, and refuses any Host other than loopback or the… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/a4_no_mutation.rs` | 638 | A4: no mutation surface. Only GET on the three allowlisted routes; every other method is 405 and every… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/a5_bounds.rs` | 598 | A5: requests are bounded. Queries are parsed strictly against the core's caps; bodies, heads, targets and… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/a6_semantics.rs` | 312 | A6: inventory semantics are unchanged. For every 0.0.1 fixture scenario, each inventory and session body… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/a7_headers_and_logs.rs` | 359 | A7: nothing is cached or leaked. Every response, success or error, has no-store, the security headers and… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/a7_source_diagnostics.rs` | 1080 | A7 (continued): no room-cli diagnostic text (its stderr, and what it prints on stdout where JSON, a… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/a8_web_page.rs` | 1154 | A8 (#46): openwiz-server serves the web page, apps/web's static export, from one configured directory… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/attach_support.rs` | 369 | Helpers for the attachment routes (#16, B3): an in-process server with the send, new-thread and attachment… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/aw01_routes.rs` | 199 | AW1 (#16, B3): exactly the planned routes. The route table is A2's plus the three attachment routes: the… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/aw02_owner_and_cross_site.rs` | 237 | AW2 (#16, B3): owner only, and no cross-site write, for every attachment route, through the shared checks… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/aw03_bounds.rs` | 426 | AW3 (#16, B3): uploads are bounded (sheet B-9). A body over 25 MiB is refused before a byte of it is read;… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/aw03_streaming.rs` | 322 | AW3 and AW4 (#16, B3), after #16's answer (Q1, the orchestrator, 2026-10-31): **the store stages straight… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/aw04_same_operation.rs` | 567 | AW4 (#16, B3): the same operations. For every B1 and B2 fixture case, each attachment route's answer is… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/aw05_gate.rs` | 334 | AW5 (#16, B3), the server's half: **the gate is the core's, and the server's is the real one.** A request… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/c10_cockpit_cases.rs` | 477 | #535 (0.0.10 T2), CK1: GET /api/v1/cockpit returns what contracts/cockpit.v1.md says, on the fake gh, the… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/c10_cockpit_review.rs` | 479 | #535 self-review round 1 (Codex Sol helper), each finding's proof, red first: an unrecognized status, a… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/c10_cockpit_route.rs` | 275 | #535 (0.0.10 T2), CK1's route half: the cockpit read keeps every route's checks (Host, method, query,… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/c10_cockpit_support.rs` | 539 | #535 (0.0.10 T2): the cockpit route's fakes. Every value is synthetic. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/c3_binary.rs` | 238 | The shared server dispatch configures the fleet sources on recording fakes. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/c3_bounds.rs` | 267 | S3-7: fleet reads use the same bounded, uncached single-flight runner. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/c3_routes.rs` | 199 | S3-7 (#127): two read-only fleet routes, with the existing HTTP guards. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/c3_semantics.rs` | 325 | S3-7: CLI byte equality on synthetic GitHub answers. Only the hang fixture normalizes independently… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/c3_support.rs` | 166 | Reuse the existing fleet fake and generated A5 worlds, at the HTTP seam. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_decisions_bounds.rs` | 145 | EP3: source-clock freshness and the shared read runner, with held reads. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_decisions_guards.rs` | 155 | EP3: exact read forms and the existing HTTP guards protect the new read. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_decisions_records.rs` | 1421 | EP3: records returned through HTTP over the actual adapter and fake gh. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_decisions_review.rs` | 630 | First review round of #794: public HTTP/source regressions for R1–R3. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_decisions_routes.rs` | 130 | EP3: the decisions read uses the existing guarded HTTP seam. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_decisions_support.rs` | 242 | Synthetic GitHub shapes, including pagination headers; none is live evidence. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_plan_bounds.rs` | 337 | EP1 transport guards and shared-slot behavior, using private synthetic FIFOs. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_plan_graph.rs` | 142 | EP1 worked graph examples; expected answers are literal, independent paths. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_plan_partial.rs` | 177 | EP1 usable facts survive independent failed reads (audit regressions). | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_plan_reads.rs` | 328 | EP1 pagination, strict input, URL identity and source-clock proofs. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_plan_review.rs` | 479 | PR 788 correction proofs: the public plan HTTP seam, synthetic sources only. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_plan_routes.rs` | 149 | EP1: synthetic route proofs for the whole-repository plan. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_plan_states.rs` | 192 | EP1 state precedence and complete-input requirements at the HTTP seam. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/e11_plan_support.rs` | 149 | Synthetic GitHub response builders; no live IDs, bodies or accounts. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/fake.rs` | 27 | The shared proof fake, using the same program built once with optimization. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/http.rs` | 438 | Helpers: an in-process server over the fake room-cli, a raw HTTP/1.1 client, and a gated source that holds… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/lp6_loops_read.rs` | 244 | LP6 (#549): the loops read's fail-closed paths (openwiz_server::loops::read), on a synthetic private… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/lp6_loops_route.rs` | 241 | LP6 (#549): GET /api/v1/loops over HTTP, on a synthetic private checkout and state with explicit trusted… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/main.rs` | 166 | OpenWiz 0.0.2 ticket 1: proof tests for openwiz-server, written before the server. See… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/new_support.rs` | 498 | Helpers for the new-thread routes (#12, A2): a private fake room-cli and new-thread record per test, an… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/ready_stock.rs` | 980 | PA7: the real cockpit route retains unread project stock, never invents zero. Current tests predate the… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/send_support.rs` | 283 | Helpers for the send routes (#9): an in-process server with the send record and the fake room-cli of a… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/u01_new_routes.rs` | 139 | U1 (#12, A2): exactly the new routes. The route table is 0.0.3's plus the Cloud options and the status… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/u02_u03_owner_and_cross_site.rs` | 263 | U2 and U3 (#12, A2): the create and the new-thread preview take the send's guard unchanged (A-13, WS-1 to… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/u04_bounds.rs` | 301 | U4 (#12, A2): the create is bounded (A-14, as WS-12): one project, from the path; the send's body cap,… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/u05_same_operation.rs` | 361 | U5 (#12, A2): the same operation. For every #11 fixture case, each new route's answer is what the CLI… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/u06_u12_never_coalesced.rs` | 160 | U6 and U12 (#12, A2), the server's half: creates are never coalesced, and a repeat never creates twice. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/u09_u11_preview_and_status.rs` | 252 | U9 and U11 (#12, A2), the server's half. | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/w15_no_redispatch.rs` | 278 | W15 (#9): the built openwiz-server dispatches nothing when it starts, and a server killed during a send's… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/w1_one_mutation.rs` | 103 | W1 (#9): exactly one mutation route (A4 pins the route table); every other method on the send route is 405… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/w2_owner.rs` | 55 | W2 (#9): owner only, at the layer Jake chose (WS-1 (a), T): the tunnel's Access check. The server must… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/w3_cross_site.rs` | 312 | W3 (#9): cross-site requests are refused before anything is read, claimed or sent (write-security §4, C1… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/w4_bounds.rs` | 440 | W4 (#9): the send route is bounded (WS-12): one target from the path, a capped body with Content-Length,… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/w5_same_operation.rs` | 272 | W5 (#9): the same operation. For every case of the send fixtures, the route's answer is byte for byte what… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |
| `tests/web-api/w6_never_coalesced.rs` | 164 | W6 (#9): sends are never coalesced. Two sends with different op ids are two calls, even when identical… | Only the `web-api` test target, which proves the server (S8) | **delete** |  |

### Their contracts, docs and deployment

19 files: 7 delete, 0 fold, 12 keep.

| Path | Lines | What it does | Uses today (search) | Disposition | New home |
| --- | ---: | --- | --- | --- | --- |
| `contracts/attachment-mime-types.v1.md` | 20 | Attachment image MIME extensions, version 1 | Kept core attachment kinds (S9, D3) | **keep** |  |
| `contracts/attachment.v1.schema.json` | 381 | OpenWiz 0.0.4 attachments: one ready attachment's verified record (the root), its kind, its readiness and… | Kept core attachment types; `tests/attachments` parity and schema files (S9, D3) | **keep** |  |
| `contracts/cockpit.v1.md` | 213 | OpenWiz cockpit contract, version 1 (openwiz.cockpit.v1) | The server's cockpit route and its web page and tests (S9) | **delete** |  |
| `contracts/cockpit.v1.schema.json` | 928 | The read-only page-1 cockpit response. Unknown facts are explicit. See cockpit.v1.md for provenance,… | The cockpit route and `tests/checks/cockpit_schema_conformance.rs` (S9, C8) | **delete** |  |
| `contracts/messaging.v1.schema.json` | 1160 | OpenWiz 0.0.3 send: the report printed by openwiz send --json (the root), the request, the effects and the… | Kept core `messaging` record and report; `tests/messaging/structure.rs` (S9) | **keep** |  |
| `contracts/new-thread.v1.schema.json` | 1569 | OpenWiz 0.0.4 new threads (ClosedWiz#11): the report of a create (the root), and in $defs the request, the… | Kept core `new_thread` record and report; `tests/new-thread` schema files (S9) | **keep** |  |
| `contracts/plan.v1.md` | 234 | OpenWiz plan contract, version 1 (openwiz.plan.v1) | Kept: `github` adapter `plan.rs` builds this document; `tests/checks/plan_decisions_schema_conformance.rs` (S9, L1) | **keep** |  |
| `contracts/plan.v1.schema.json` | 570 | Contract only. See plan.v1.md for provenance, cross-record rules and action guards. Fixtures prove no live… | Kept: `github` adapter `plan.rs`; `tests/checks/plan_decisions_schema_conformance.rs` (S9, L1) | **keep** |  |
| `contracts/prompt.v1.schema.json` | 41 | OpenWiz 0.0.4's prompt payload, shared by send and new threads: the text and an ordered list of staged… | Kept core `prompt`; `tests/new-thread/schema_parity.rs` (S9) | **keep** |  |
| `contracts/service.v1.md` | 611 | OpenWiz service contract, version 1 (openwiz.service.v1) | Kept: it defines `openwiz.service-config.v1`, the owner-only `service/config.json` the kept `openwiz loop` reads for its operator, repository and project; the kept proofs `tests/loops/l6_config.rs:6` and `tests/cli-agent/process.rs:892` compile its config example. Its service-only sections are D6's (S9, C8, D6) | **keep** |  |
| `contracts/service.v1.schema.json` | 2767 | OpenWiz's always-on service (OpenWiz 0.0.8): its status report, config, state and GitHub records, told… | Kept: the kept loop reader compiles its `$defs.config` (`crates/store/src/loops/document.rs:93`, folding to `crates/cli/src/state/loops/`) (S9, D6) | **keep** |  |
| `contracts/setup.v1.md` | 97 | Resumable setup v1 | Kept: the setup tools follow its operations and state (`tools/install/setup/init.py`, `store.py`, `setup.py`); only its `GET /api/v1/setup` route goes (S9, C12) | **keep** |  |
| `contracts/setup.v1.schema.json` | 521 | OpenWiz resumable setup v1 | Kept with `setup.v1.md`: the setup tools' state; `tools/install/test_setup_api.mjs` checks the document (S9, C9) | **keep** |  |
| `contracts/web-api.v1.md` | 590 | OpenWiz web API, version 1 | The server, `apps/web` and `tests/web-api`; named in `AGENTS.md` (S9, C12) | **delete** |  |
| `deploy/pc/README.md` | 218 | PC service setup (T11) | The PC service unit and its setup; kept: `docs/github-app.md`, `tools/install/platform/test_runtime.py`, `tools/release/test_package.py` name it (S4, S9, C6, C9, C12) | **delete** |  |
| `deploy/pc/config.example.json` | 25 | Synthetic example of `service/config.json` (`openwiz.service-config.v1`) | Kept: the template existing installs' `service/config.json` was provisioned from (`deploy/pc/README.md:64`); the only checked-in example of the config `openwiz loop` reads (S9, D6) | **keep** |  |
| `deploy/pc/openwiz.service` | 16 | PC service deployment | The PC service unit and its setup; kept: `docs/github-app.md`, `tools/install/platform/test_runtime.py`, `tools/release/test_package.py` name it (S4, S9, C6, C9, C12) | **delete** |  |
| `docs/service-install.md` | 116 | Private local runtime | Installing the service; a search for its name finds no kept file (S9) | **delete** |  |
| `docs/web-access.md` | 281 | OpenWiz web access: setup guide and security model | Reaching the server from a browser; kept: `RELEASING.md` and `ci/select/map.json` name it (S9, C4, C12) | **delete** |  |
