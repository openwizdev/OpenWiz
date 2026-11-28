# OpenWiz 🧙‍♂️🪄

OpenWiz runs coding agents in fleets: the user approves a plan, and agents build, review and merge its tickets. This repository is the `openwiz` command, its adapters and the engine; the app is at [openwiz.dev/app](https://openwiz.dev/app). Words mean what [GLOSSARY.md](GLOSSARY.md) says. The wizard factory mark is 🧙‍♂️🪄. Where agents use it: [Fleet settings, The mark](docs/agents/fleet.md#the-mark).

## Start here

- If `.wizskills/` is missing, run `python3 -I tools/wizskills/install.py` from the root. It installs the pinned [WizSkills](https://github.com/openwizdev/WizSkills) release, so every `skills/<name>/SKILL.md` resolves.
- Once per clone, `git config core.hooksPath .githooks`: the pre-push hook runs the privacy check.
- The skills read the project's settings in [`docs/agents/`](docs/agents/). Change a skill in WizSkills and move the `wizskills.lock` pin, never here.

## Public and private

Everything on this repository is public; private records live in `jparker2006/ClosedWiz`. Before any public write, read the [public-writes card](docs/agents/public-writes.md); `python3 -I skills/launch-fleet/scripts/context.py <role>` prints it with your role's settings. Release, publishing, privacy-check and importer work also needs the full [open development contract](contracts/open-development.v1.md).

## Where things are

| Path | What |
| --- | --- |
| `crates/core` | The model and product rules: inventory, fleets, loops, messaging, new threads, attachments. No I/O; depends on no other crate here |
| `crates/adapters/cloudroom` | The `room-cli` allowlist (`src/allowlist.rs`) and the CloudRoom source; every `room-cli` call goes through it |
| `crates/adapters/github` | Fleets' GitHub reads and writes, through `gh` and its own allowlist |
| `crates/cli` | The `openwiz` program; `src/state/` is the owner's state directory |
| `kernel/` | The records and driver contracts, with their test kits |
| `adapters/template/` | A copyable minimal driver |
| `contracts/` | Versioned contracts and JSON schemas |
| `tests/` | Proof cases, checks, synthetic fixtures and the fake `room-cli` and `gh` |
| `tools/`, `ci/` | Release, install, privacy-check and CI tools; each folder's README says how to run it |
| `changes/` | One changelog line per product ticket ([`changes/README.md`](changes/README.md)) |
| `docs/adr/` | Hard-to-reverse decisions |

## Commands

```sh
cargo test --workspace   # all Rust proofs and checks, on the fake room-cli; scoped local checks: docs/agents/fleet.md
```

Rust 1.99.1 with `rustfmt` and `clippy`; there is deliberately no `rust-toolchain.toml`. CI runs the full set on every ready pull request.

- Never retarget a pull request: close it and open a new one against the other base. CI judges the base it ran with.

## Live work and approvals

- Outside the tests, `openwiz ls`, `show` and `fleet` read the live CloudRoom through the bundled `room-cli`: that is live work.
- Jake approves first: a new dependency, toolchain file or tool on the Mac; a change to the `room-cli` allowlist or an approved limit; any live `room-cli` read or Mac work outside an approved live kit. Releasing follows [ADR 0020](docs/adr/0020-release-on-demand.md); never force-push or rewrite a release.
- Each of these gates, with who approves it, is a row of the [Approval rules](docs/agents/fleet.md#approval-rules) table.
