# OpenWiz

## What this is

OpenWiz is developed in the public repository `openwizdev/OpenWiz`; ClosedWiz stays private for exact decision words, grills, live evidence, machine details and orchestration state. These instructions are prepared in ClosedWiz until the separately approved cut-over; this edit activates nothing. See the [open development contract](contracts/open-development.v1.md). OpenWiz 0.0.1 is one outcome: a read-only Rust inventory of real CloudRoom sessions, read through `room-cli`.

**Build and acceptance are separate.** The 0.0.1 inventory, 0.0.3 send, 0.0.4 new-thread and attachment flows are implemented. 0.0.5 was accepted with recorded gaps ([#106](https://github.com/jparker2006/ClosedWiz/issues/106#issuecomment-6550891204)). Check [STATUS.md](STATUS.md) and each version's acceptance record for its current gates; fixture tests alone never prove live behaviour.

Always true:
- **Private.** No personal context, transcripts, credentials, live session content or real identifiers in any file. Fixtures are synthetic only.
- **Two writes: `send` and `new`.** OpenWiz never launches or merges anything, and starts nothing but the one new thread `openwiz new --yes` asks for. Its writes are:
  - `openwiz send`: one text message to one existing session, through `room-cli thread tell <id> --mode queue|steer --json -- <text>` (documented, not observed; the argument shape must be rechecked on the owner's endpoint before any live send);
  - `openwiz new --yes` (0.0.4, #11): one new Cloud thread in one existing project, through `room-cli thread spawn --project <id> --machine cloud --provider <p> --model <m> --reasoning-level <l> --request-id <rid> --json --prompt <text>` (its flags observed in spike run 3's help, the call itself never run). Without `--yes`, `new` only reads and shows the effects. There is no retry (sheet A-3).
  - **Attachments (0.0.4, #15, sheet B-1 to B-10)** ride on those two writes and add no other call: `--file <path>` and `--image <path>`, only with a staged copy's absolute path (B-7), after `--json` and before the text's `--` or `--prompt`, built only by the allowlist's `attachment_args`. `send` and `new` take them as `--attach <path>` (staged first, as `openwiz attachment add` does) and `--attachment <id>`. Every one must be ready, or nothing is read or sent; Steer can't carry them; the op id binds them; an accepted outcome's staged copies are deleted once it is recorded. `room-cli` uploads each file to CloudRoom, which keeps its own copy (B-1): that is part of the write. Never a separate upload (`project attachment upload`).

  Every `room-cli` call must come from the allowlist in `crates/adapters/cloudroom/src/allowlist.rs`. **The `room-cli` version is not a gate**, for `send`, `new` and the reads (#37; version policy, recorded 2026-11-07: report the version without making it a gate; [private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)): it is reported, and every other safeguard still applies. Live effects require the existing scoped kit authority; the future public-source release path follows ADR 0020 after verified cut-over, without per-step prompts or wider permissions.
- **Proof first.** A claim without its evidence stays Unverified. Tests never prove live behaviour.
- **Frozen:** the 0.0.0 files under `release/openwiz/` never change.

**Current status, in plain English:** [STATUS.md](STATUS.md). Keep it current after every real change.

## Where things are

| Path | What |
| --- | --- |
| `crates/core` (`openwiz-core`) | The inventory model, the honest envelope, the `SessionSource` interface, and the `list`/`show` operations. Depends on no other crate here |
| `crates/adapters/cloudroom` | The `room-cli` allowlist and the CloudRoom `SessionSource`. Depends on the core |
| `crates/cli` (`openwiz-cli`, program `openwiz`) | Parses commands and prints results. Depends on the core and the adapter |
| `crates/server` (`openwiz-server`) | The loopback HTTP API and optional static web export. It serves inventory/session/health reads, send and new-thread preview/status/write routes, and local attachment staging/list/removal; see [contracts/web-api.v1.md](contracts/web-api.v1.md). std-only HTTP. Depends on the core and the adapter; only `openwiz-service` embeds it (#269, approved one-process exception) |
| `apps/web` | The static web app (Next.js static export) over the HTTP API, including inventory, send, new-thread and attachment flows; see [apps/web/AGENTS.md](apps/web/AGENTS.md) |
| `skills/` | The fleet skills (0.0.5), any agent in any harness: one folder each, installed through `.claude-plugin/`, linked from `.claude/skills/` and `.agents/skills/`, checked by `tests/checks/skills.rs`: see [skills/README.md](skills/README.md) |
| `contracts/web-api.v1.md` | The web API: routes, parameters, statuses, headers and bounds |
| `contracts/inventory.v1.schema.json` | The `openwiz.inventory.v1` JSON envelope |
| `tests/proof/` | Proof cases P1 to P12, one module each |
| `tests/web-api/` | The web API's proof tests A3 to A8 and its contract check |
| `tests/checks/` | Dependency direction, the fixture scan, schema conformance, the pending list |
| `tests/fixtures/` | Synthetic `room-cli` 0.43.1 responses, with their provenance in its `README.md` |
| `tests/fake-room-cli/` | The fake `room-cli` the tests run |
| Pull request proof records | Red run, dependencies, review results and gaps; private evidence remains in ClosedWiz, linked by private-record comment pointers |

Dependencies point inward: `cli → adapter → core`, `cli → core`, and the same for `server`. The core never depends on an adapter or a client.

## Commands

Rust 1.99.1 with `rustfmt` and `clippy`, and zsh (`sudo apt-get install -y zsh`): the new-thread proofs run printed commands in it and fail without it, so it is required, like Rust and Node 24.22.1. There is deliberately no `rust-toolchain.toml`.

```sh
cargo build --workspace
cargo test --workspace                                         # P1-P12, M1-M18, N1-N19, AP1-AP12, A3-A8 and the checks, on the fake room-cli only; about 40 s (two 15-second timeout proofs, and a release build). A8 needs apps/web/out (npm run build, below) and fails without it
cargo test -p openwiz-tests --test messaging                   # M1-M18 only: send, on the fake room-cli and a private state directory; and #15's AD proofs for send, and B-8's memory measurement (Linux)
cargo test -p openwiz-tests --test new-thread                  # N1-N19 only: new, new --status and models, on the fake room-cli and a private state directory; and #15's AD proofs for new
cargo test -p openwiz-tests --test attachments                 # AP1-AP12 only: the attachment model, staging and attachment add, ls, rm, in a private state directory; no room-cli. AP6 measures memory through /proc (Linux), and AP5 needs a user other than root; and #15's rules and static checks (AD8, AD11)
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test -p openwiz-tests --test checks pending              # the pending markers match tests/pending-ticket-2.txt (empty after ticket 2)
cargo build --release                                          # target/release/openwiz
cargo run -q -p openwiz-cli -- --help                          # usage, sort order, send and new (with --attach and --attachment), models, attachment and exit codes; reads nothing
cargo test -p openwiz-tests --test web-api                     # the web API proofs (A3-A7, with A7's planted room-cli diagnostics; A8, the web page, over apps/web/out) on the fake room-cli; about 30 s (15-second timeout cases)
cargo run -q -p openwiz-server -- --help                       # the server's usage; reads nothing
cd apps/web && npm ci --ignore-scripts && npm run build         # the web app's static export (apps/web/out); Node 24.22.1
cd apps/web && npm run typecheck && npm run check               # the web app's tsc and static checks (V1, V3, V10, spacing)
cd apps/web && npm test                                         # the web proofs V1-V11 on fixtures and ticket 1's server, the browser files 3 at a time, longest first (test/run-browser.mjs, #431); needs out/ and cargo
```

**CI** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml), #1262) writes one [selection record](contracts/ci-selection.v1.md) in `changes`. Every run executes format, classifier/selector proofs and the cheap architecture/privacy/static checks. The selected Rust, web, site, release and individual skill jobs start independently; only export consumers wait for `apps/web/out`. Each lane reads the persisted plan, and `ci` requires every planned job and individual matrix receipt to pass. Failed, cancelled or missing work fails. The orchestrator changes the ruleset's required checks to `ci` at merge and reads it back; the temporary `web-test` bridge follows `ci` during that transition.

Only a ready PR's first ordinary attempt against `main`, with current live base/head and a trusted measured map, can narrow coverage. Nightly runs, reruns, release branches, merge groups, ready-for-review, stale events, unknown paths, empty/failed diffs and selector doubts run everything. A push to `main` runs only `main-light` (format; `privacy.yml` also checks it), because the merge queue already ran the full suite on that merge (Jake, 2026-11-15, #744); the nightly run stays full, and is the run that signs the map and refreshes the trusted caches; a manual dispatch from `main` also signs the map, and a dispatch from any other ref signs nothing (#783). A draft fails. Before a lane runs it prunes its legacy classifier reader's unused files and `private/` outside [ci-reads.txt](.github/actions/docs-only/ci-reads.txt); a newly required file needs its reader row. Hosted fork routing, guarded setup and trusted cache writes remain as #1265 defined them. Tests use synthetic fixtures and no application secrets. The classifier retains `.claude/skills/export-review/SKILL.md` and `.claude/skills/live-quick-check/SKILL.md` for its Rust reader; other local skill entrypoints remain skippable.

- **Never retarget a PR; close it and open a new one against the other base.** CI judges a PR against the base it ran with, and changing the base starts no new run.
- **Every code run deletes the rest of `private/` first.** A test that must read another file there fails in CI until that file is added to `ci-reads.txt`. A test that reads such a file only if it exists, or finds its cases by walking a directory under `private/`, would instead pass without it: don't write one.

`sh .github/actions/docs-only/test.sh` checks the classifier, diff/event guard, prune/checkout, Rust runner, plan, dispatch and final-job boundary. The Rust lane uses `ci/rust-tests.sh --only` for the exact planned IDs, retaining its cgroup-aware concurrency and sequential fallback. The checks binary runs once in the always lane; by hand, `cargo test --workspace` remains the full command.

`openwiz-server` listens on `127.0.0.1` only (`--port`, default 7370) and serves the static web export only with `--web-root DIR` (normally `apps/web/out`). Like `openwiz`, it can perform **live reads** through the verified bundled `room-cli`, never one found on `PATH`, including for inventory, session, fleet detail, send preview, `GET /api/v1/cloud-options`, new-thread preview and new-thread status requests. The health route, send lookup and attachment routes make no `room-cli` call. Its send and create routes perform live writes when used, subject to the configured host and request checks. The host check is not authentication. Access control is the tunnel's and Access's (see [contracts/web-api.v1.md](contracts/web-api.v1.md#host-dns-rebinding-defence)). Ask Jake first. Never put it behind a tunnel or a public hostname without his approval.

`openwiz ls`, `openwiz show`, `openwiz models`, `openwiz fleet <spec>`, `openwiz new` without `--yes` and `openwiz new --status` run the verified bundled `room-cli`, never one found on `PATH`. Outside the tests that is a **live read**: ask Jake first. `openwiz send` and `openwiz new --yes` outside the tests are **live writes**, with or without attachments (each attached file is uploaded to CloudRoom by `room-cli`): never without Jake's go-ahead. In-process tests inject an absolute fake program. Subprocess tests run the test-only fixture CLI/server examples with an isolated bundle around the fake (`OPENWIZ_FIXTURE_PROGRAM` is read only by those fixture entrypoints), and point `OPENWIZ_STATE_DIR` (the send and new-thread records and the staged attachments) at a private test directory. The production binaries have no fixture environment or feature bypass.

`openwiz attachment add`, `ls` and `rm` never run `room-cli` and send nothing: they copy files the owner names into the attachment store in the owner's state directory (`attachments/`, owner-only), list them and delete them. Outside the tests that changes only that directory. `add` runs one other program, `/bin/df -P -k <state dir>` with `LC_ALL=C` only, for the 1 GiB free-disk floor, and stages nothing if it fails (Jake, 2026-10-31, #14: P8(a)'s one exception); separately, [Jake approved macOS App signing](https://github.com/jparker2006/ClosedWiz/issues/1102#issuecomment-6672035698) to run only absolute `/usr/bin/python3 -I -c <compiled-in reviewed security.py> inspect|sign <private root>`, with `.env_clear()`, no `PATH`, fallback or production override (2026-11-05; this adds no store program). The tests use a private state directory and synthetic files they write themselves.

`apps/site`: `npm run build` exports the public landing and `/changelog` to `dist/`; `npm test` checks the export and browser proofs (uses the existing `apps/web` test tools and Chromium).

## Doing the work

- **Install the pre-push hook first,** once per clone: `git config core.hooksPath .githooks`. Each push then runs format and the fast checks on the commit it sends, and stops on a mistake ([.githooks/pre-push](.githooks/pre-push)).
- One ticket attempt, one owner, one branch. Stay inside the ticket's owned paths.
- **Live tests and spikes (ADR 0015).** Full live tests run on the PC (the always-on CloudRoom hub), from a Local thread there. Under ADR 0016, an approved live kit covers its own steps without per-step prompts; use only its throwaway test threads within approved counts, allowlist and spending. ADR 0020's future public-source release path retains this scope; it creates no live authority before verified cut-over.
  A quick Mac check is optional feedback after publication under ADR 0020, not another pre-publish human gate. Any separately authorized check records the version, result and limits; no Mac installation or access is authorized by this paragraph.
  The Mac-only checks stay on the Mac: the Mac's fixed `room-cli` location, adding the Mac to the PC's CloudRoom, and the Mac shut for a day.
  The standing approval for read-only discovery spikes covers the PC as well as the Mac.
  **Live spike first.** For a live claim, run a read-only discovery spike on the machine the claim concerns before writing procedures or fixture tests, under the recorded standing approval ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)). Record what is really there. See [ADR 0015](docs/adr/0015-live-tests-on-the-pc.md).
- Write the proof first: define each claim and its evidence, write the test, run it red, keep private evidence in ClosedWiz and reference it by a private-record comment pointer.
- **Fail closed:** anything that guards a write or read path uses an allowlist, never a blocklist. Size each live gate to its risk, and put all of a version's approvals on one sheet.
- A test for later behaviour is `#[ignore = "pending: ticket N"]` and listed in `tests/pending-ticket-2.txt`. No other `#[ignore]`.
- Only `serde` and `serde_json`. Record every locked crate in that ticket's `dependencies.md`.
- New fixture values must be synthetic. Label every shape that was not observed in the scenario's `synthetic_assumptions`.
- Keep the core free of I/O and formatting, the adapter free of product rules, and the CLI thin.

## Done means verified

- All four commands above pass. The pending list is exact.
- Each claim names its evidence class: fixture test, live observation, or independent review.
- The builder hands over the exact branch, head and tree, test results, the red run, internal review results and gaps.
- The 1 + 1 rule: each pull request gets one review plus one re-check; after it, an open security, privacy or data-loss blocker gets one fresh, stronger fix round and then parks for Jake, and any other open blocker is logged as a follow-up and the pull request merges ([review-loops contract](contracts/review-loops.v2.md)). A review binds only to the head it read.

## Ask Jake first

- Any new dependency, toolchain file or tool on the Mac.
- Any live `room-cli` read, or anything on the Mac, outside an already approved scoped kit (only via `room-cli mac run`; no new install or machine authority). The exception is read-only discovery spikes within the recorded standing approval ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)); machine paths remain private.
- Changing the allowlist, the approved limits, or the `release/openwiz/` files.
- Merging follows the standing development merge rules. After verified O17 cut-over, public-source releasing follows [ADR 0020](docs/adr/0020-release-on-demand.md): Jake's actual ship instruction and exact changelog approval are the only human release actions; agents execute candidate-bound CI, privacy/claims, product verification, combined smoke and applicable send/new/App-permission/spending live checks within existing kit authority. No export-plan/final-diff/standalone Sol-export, mandatory device or per-step publish approval. Before cut-over, no successor-path publication; O16/O17 authorization, prerequisites and holds remain. Historical backfill stays separately gated. Never force-push or rewrite immutable releases.

## Read when relevant

- [workflow.md](release/openwiz/docs/workflow.md): PDD; this frozen 0.0.0 doc keeps the old 2 + 1 wording, and the live 1 + 1 rule is in the skills ([proof-driven development](release/openwiz/docs/workflow.md#proof-driven-development), [failure and rework](release/openwiz/docs/workflow.md#failure-and-rework)).
- [architecture.md](release/openwiz/docs/architecture.md): layout and dependency direction.
- [RELEASING.md](release/openwiz/RELEASING.md): versions, export review, what a release may claim.
- [tests/fixtures/README.md](tests/fixtures/README.md): where the 0.43.1 shapes come from.
- Machine details and access instructions stay in ClosedWiz; consult its private record only when authorized work needs them.
- Standing discovery approval: Jake, 2026-10-27, extended 2026-11-01, permits the recorded read-only discovery spikes ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)); release installs and other live work retain their gates.
- [Fleet settings](docs/agents/fleet.md) and [helper settings](docs/agents/helpers.md): public work and merges on OpenWiz, with handoff and runtime identities kept in ClosedWiz or CloudRoom. Public records carry neither thread ids nor exact decision words.
- Rust: [API Guidelines](https://rust-lang.github.io/api-guidelines/), [Clippy](https://doc.rust-lang.org/clippy/), [rustfmt](https://rust-lang.github.io/rustfmt/).
