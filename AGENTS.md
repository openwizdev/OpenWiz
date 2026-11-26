# OpenWiz

OpenWiz runs coding agents in fleets: the user approves a plan, and agents build, review and merge its tickets. This repository is the `openwiz` command, its adapters and the engine; the app is at [openwiz.dev/app](https://openwiz.dev/app). Words mean what [GLOSSARY.md](GLOSSARY.md) says.

## Start here

- If `.wizskills/` is missing, run `python3 -I tools/wizskills/install.py` from the root. It installs the pinned [WizSkills](https://github.com/openwizdev/WizSkills) release, so every `skills/<name>/SKILL.md` resolves.
- Once per clone, `git config core.hooksPath .githooks`: the pre-push hook runs the privacy check.
- The skills read the project's settings in [`docs/agents/`](docs/agents/). Change a skill in WizSkills and move the `wizskills.lock` pin, never here.

## Install OpenWiz

The install instruction is exactly this phrase:

> Install OpenWiz

A person says that to their coding agent (Claude Code, Codex, Cursor or another). That phrase is enough to start. Ask only where your agents run, and for a yes before each change the install shows. The repository is https://github.com/openwizdev/OpenWiz. You need Python 3.9 or later, `git` and `gh`.

1. Resolve the release:

```sh
curl -sS --proto '=https' -o /dev/null -w '%{redirect_url}\n' https://github.com/openwizdev/OpenWiz/releases/latest
```

The printed URL ends in `/tag/<tag>`. `<version>` is `<tag>` without the leading `v`. With no `/tag/` in the URL, GitHub has no Latest release: stop and say so. Use `<tag>` only when it matches `v[0-9]+\.[0-9]+\.[0-9]+`. Use `<commit>` only when it matches `[0-9a-f]{40}`. Any other value stops the install.

2. Read that release's install skill and follow it from the top in this session. Run the commands yourself.
   - `0.1.0`: the skill is https://github.com/openwizdev/WizSkills/blob/33eef93ba30cd8db256f6fe270e3ed28747a79bd/skills/install/SKILL.md and the command reference is [the 0.1.0 steps](docs/install.md#openwiz-010). Clone tag `v0.1.0`. When the skill cannot be read, follow those steps. This release's skill is that commit, not the `commit` in that tag's `wizskills.lock`.
   - Any other `<tag>`, including `v0.1.1`: set `$openwiz` to a new private temporary directory (`openwiz=$(mktemp -d)`), then clone that tag:

```sh
git clone --depth 1 --branch "$tag" -- https://github.com/openwizdev/OpenWiz "$openwiz"
```

     Read `wizskills.lock` in that clone. The skill is `https://github.com/openwizdev/WizSkills/blob/<commit>/skills/install/SKILL.md`, where `<commit>` is the lock's `commit`. The lock's `version` is that WizSkills release. The command reference is `docs/install.md` in the clone. When the skill cannot be read, follow that file and run each command yourself. The clone is already at `<tag>`. When the clone has no `wizskills.lock`, or the lock has no `commit`, stop and say so. The numbered steps in that guide expect build identity `0.1.1`. When `<version>` is not `0.1.1`, stop unless that guide expects `<version>`.

CloudRoom is optional. Its install and sign-in run only when the person picks CloudRoom.

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
