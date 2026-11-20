# OpenWiz

OpenWiz runs coding agents in fleets: the user approves a plan, and agents build, review and merge its tickets. This repository is the `openwiz` command, its adapters and the engine; the app is at [openwiz.dev/app](https://openwiz.dev/app). Words mean what [GLOSSARY.md](GLOSSARY.md) says.

## Start here

- If `.wizskills/` is missing, run `python3 -I tools/wizskills/install.py` from the root. It installs the pinned [WizSkills](https://github.com/openwizdev/WizSkills) release, so every `skills/<name>/SKILL.md` resolves.
- Once per clone, `git config core.hooksPath .githooks`: the pre-push hook runs the privacy check.
- The skills read the project's settings in [`docs/agents/`](docs/agents/). Change a skill in WizSkills and move the `wizskills.lock` pin, never here.

## Public and private

- This repository and everything on it (files, commits, branches, issues, pull requests, comments) is public. The private repository `jparker2006/ClosedWiz` keeps grills, exact decision words, live evidence, machine details and orchestration state.
- Never put in a public record: a thread id, anyone's exact words from a decision, credentials, real identifiers or personal facts, or live session content. Fixtures and examples are synthetic.
- A public decision gives who decided, the date, the decision in plain words and a `[private record](https://github.com/jparker2006/ClosedWiz/issues/<N>#issuecomment-<C>)` link to the comment holding the words.
- The full rules are the [open development contract](contracts/open-development.v1.md). The `build-ticket` skill says when to read it; release, publish, privacy-check and importer work always needs it.

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
| `release/openwiz/` | The frozen 0.0.0 documents: never change them, and they are not current |

## Commands

```sh
cargo test --workspace   # all Rust proofs and checks, on the fake room-cli; scoped local checks: docs/agents/fleet.md
```

Rust 1.99.1 with `rustfmt` and `clippy`; there is deliberately no `rust-toolchain.toml`. CI runs the full set on every ready pull request.

- In CI every code run deletes `private/` except the files in [ci-reads.txt](.github/actions/docs-only/ci-reads.txt). A test that reads a new file there needs its row; never write one that passes when the file is missing.
- Never retarget a pull request: close it and open a new one against the other base. CI judges the base it ran with.

## Live work and approvals

- Outside the tests, `openwiz ls`, `show` and `fleet` read the live CloudRoom through the bundled `room-cli`: that is live work.
- Jake approves first: a new dependency, toolchain file or tool on the Mac; a change to the `room-cli` allowlist or an approved limit; any live `room-cli` read or Mac work outside an approved live kit. Releasing follows [ADR 0020](docs/adr/0020-release-on-demand.md); never force-push or rewrite a release.
