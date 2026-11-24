# Fleet settings

The fleet skills read this file. Keep every table's headings, columns and rows unchanged: scripts parse them. When a value changes, run the `setup` skill again or edit the row, and name the source.

## Models

Each role's model, under the [models contract](../../contracts/models.v1.md). The Builder starts each ticket and the Small builder each ticket with an exact `polish`, `huntr` or `proposal` label; the Orchestrator starts a spec's fleet thread. Every pull request is reviewed first by the Reviewer (`Opus 5.5 Medium`). Only when a Claude start is refused or stops on a positively reported usage limit does the fleet fall back to `Reviewer fall-back 1` (`Gemini 4 Neon, High`, through Antigravity, in a fresh thread that did not build the pull request), and only when Antigravity also refuses does it fall back to `Reviewer fall-back 2` (`Codex Sol 6.2 Medium`). The verdict names its reviewer's model and effort in its first lines (for example `reviewer: Neon High`). A review already started keeps its reviewer. The thread that built a pull request never reviews it. The next review goes back to Opus 5.5 Medium as soon as Claude has usage. Change a role with `openwiz models set` and commit it: agents started after it reaches `main` use it; an agent already started keeps its model.

| Role | Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- | --- |
| Orchestrator | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Builder | Antigravity | Gemini 4 Neon | Medium | `--provider antigravity --reasoning-level medium` |
| Reviewer | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| Small builder | follows Builder | | | |
| Fixer | follows Builder | | | |
| Reviewer fall-back 1 | Antigravity | Gemini 4 Neon | High | `--provider antigravity --reasoning-level high` |
| Reviewer fall-back 2 | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol --reasoning-level medium` |

Source: Jake, 2026-11-24 (#895: builders and fixers Gemini 4 Neon Medium through Antigravity; first-choice reviewer Opus 5.5 Medium; fall-back 1 Gemini 4 Neon High through Antigravity on positively reported Claude usage limit; fall-back 2 Codex Sol 6.2 Medium when Antigravity also refuses); earlier J255 (2026-11-19; [private record](https://github.com/jparker2006/ClosedWiz/issues/3065#issuecomment-7031528626)) and J119 (2026-11-15; [private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6906276883)).

**Kept for older skills:** the five tables below, from `## Builder` to `## Fixer`, are what the pinned WizSkills release reads. Keep them equal to this table (`openwiz models set` does; `openwiz models show` warns when they differ) until they go in #2205.

## Builder

One per ticket, on its own branch. It never reviews or merges. Tickets without an exact `polish`, `huntr` or `proposal` label use this table.

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Claude Code | `--provider claude-code` |
| Model | Opus 5.5 | `--model claude-opus-5-5` |
| Effort | Medium | `--reasoning-level medium` |

## Builder for small tickets

Tickets with an exact `polish`, `huntr` or `proposal` label use this table.

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Claude Code | `--provider claude-code` |
| Model | Opus 5.5 | `--model claude-opus-5-5` |
| Effort | Medium | `--reasoning-level medium` |

Codex runs at the default service tier: no fast mode, no `--service-tier` override. Source: Jake, 2026-11-05 and 2026-11-07 ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951); [private record](https://github.com/jparker2006/ClosedWiz/issues/1988#issuecomment-6712108296)).

## Reviewer for Claude-built

One per pull request, from the other model family than the builder (ADR 0008). It reviews the exact head and never edits. If it can't start, the review waits; it is never swapped for another model except along the recorded reviewer fall-back order in `## Models` when a start is refused or stops on a positively reported usage limit.

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Codex | `--provider codex` |
| Model | Sol 6.2 | `--model gpt-6.2-sol` |
| Effort | Medium | `--reasoning-level medium` |

## Reviewer for GPT-built

The builder's family comes from the ticket's branch-matching `launch-fleet: start checked` record and that exact thread's provider. Unknown or conflicting family waits.

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Claude Code | `--provider claude-code` |
| Model | Opus 5.5 | `--model claude-opus-5-5` |
| Effort | Medium | `--reasoning-level medium` |

Source: Jake, 2026-11-19 (J255: builders Opus 5.5 Medium, reviewers Codex Sol 6.2 Medium; [private record](https://github.com/jparker2006/ClosedWiz/issues/3065#issuecomment-7031528626)), 2026-10-30, 2026-11-01 and 2026-11-06 ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)). An agent already started keeps its model.

## Fixer

The fresh builder for the review-loops contract's one fresh round, of the original builder's family. An unknown or conflicting family waits.

| Builder family | Harness | Model | Effort | `room-cli thread spawn` flags |
| --- | --- | --- | --- | --- |
| Claude | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |
| GPT | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol --reasoning-level medium` |

Source: Jake, 2026-11-15 (J119; [private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6906276883)).

## Loop

How `launch-fleet` is woken; the loop and webhook identities stay in private orchestration state.

- **The safety net:** a full check every 30 minutes (`--cron '*/30 * * * *'`); every 10 minutes while GitHub's messages (the repository webhook) are off.
- **A spec's fleet thread:** one per approved spec (ADR 0011), checking its spec every 10 minutes (`--cron '*/10 * * * *'`).

## Supporting edits

Every ticket may make these edits beside its owned paths without asking:

1. **Its own rows in shared registries:** `tools/open-import/paths.json` and the CLI test catalogue in `tests/cli-agent/main.rs`.
2. **Its changelog line** as `changes/<ticket>.md`, whatever its owned paths name.
3. **Its own evidence folder,** `docs/evidence/<ticket>/`.
4. **Synthetic answers to test fakes its change breaks,** with no assertion change.
5. **Updates to byte-identical carried copies** of a file it owns.

Only its own rows and lines. The pull request lists each use with its kind and path, and the reviewer checks it. Still ask first for any contract or schema, workflow, dependency, protected guard, other ticket's logic, or anything outside these five kinds. Source: Jake, 2026-11-15 (J110; [private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6905144595)).

## Labels

The triage labels are in [triage-labels.md](triage-labels.md). A fleet adds `held` and `polish`:

| Label | Means | Put on by | Taken off by |
| --- | --- | --- | --- |
| `held` | The ticket is held: it waits for the user's approval of a changed plan or contract, and never starts while it has this label. It has no ready label while held | `plan-graph`, before it changes an approved plan; `launch-fleet`, when a merge changes a contract the ticket relies on | `plan-graph`, as it puts the ready label back once the new approval is recorded; `launch-fleet`'s `release` line, if it is still on after that |

The skill that holds a ticket first creates `held`, once, with the description "Held: waits for the user's approval". `polish` means a small follow-up in the polish backlog; it never blocks a spec. A spec closes when all its planned tickets have verified merges and its live check, if any, has passed. Source: Jake, 2026-10-31 and 2026-11-04 ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)).

## Test commands

- **Test budget:** at most 400 net new test lines per pull request in `tests/**`, `crates/*/tests/**`, `**/test_*.py`, `**/*_test.py`, `**/*.test.mjs`, `**/*.test.ts(x)` and `**/__tests__/**`. Offset the excess with deletions, or write `Test budget allowance: <N> lines. Why: <reason>` in the description. No CI step counts these lines: the reviewer checks the limit and any recorded allowance during review, on the exact head, and a pull request over the limit without an allowance gets a finding.
- **Locally,** run the red/green proof and only the tests your change can affect, plus `cargo fmt --check` and `cargo clippy -p <touched-crate> --all-targets -- -D warnings`. Never run the full workspace locally. CI runs the full set; its green result at the exact head is the hand-back gate. Source: Jake, 2026-11-03 ([private record](https://github.com/jparker2006/ClosedWiz/issues/1724#issuecomment-6697900652)).
- **One `cargo` command per checkout at a time.** A build can replace `target/debug/fake-room-cli` or `target/release/openwiz` under running tests. Run anything alongside in a separate worktree with its own `target/` (#195).

Rust 1.99.1 with `rustfmt` and `clippy`; there is no `rust-toolchain.toml`.

| # | Folder | Command | CI check |
| --- | --- | --- | --- |
| 2 | root | `cargo fmt --check` | `ci` |
| 3 | root | `cargo clippy --workspace --all-targets -- -D warnings` | `ci` |
| 4 | root | `cargo build --workspace` | `ci` |
| 5 | root | `cargo test --workspace` | `ci` |
| 6 | root | `cargo test -p openwiz-tests --test checks pending` | `ci` |
| 7 | root | `cargo build --release` | `ci` |

Source: [AGENTS.md, Commands](../../AGENTS.md#commands), and [the CI workflow](../../.github/workflows/ci.yml).

## CI checks

| Check | Runs | Required on |
| --- | --- | --- |
| `ci` | The saved plan, always-run checks, every selected lane and each selected skill suite must pass; failed, cancelled or missing work fails | `main`, `release-*` |

**Additional public check: `privacy` (O3).** It checks the public tree, commit range and PR text on every public pull request, merge group and push to `main`. OpenWiz's ruleset requires it on `main` and `release-*`, alongside the product checks named in the fleet table. The check-name migration belongs to #1262; its required `ci` check replaces the earlier product check names when that ticket lands. O7 preserves the table it receives, including that migration. O3 fixes its check name as `privacy`, verified in [PR #1846](https://github.com/jparker2006/ClosedWiz/pull/1846) at implementation pin `51e9b6b7791dcf9b077fd7163d1b4ad30990d23e`; O12 still applies and reads back the public ruleset. ClosedWiz preparation keeps the existing product-check table so current readers and fixtures keep working.

A draft fails the plan and `ci`; marking it ready starts a full run. Selection rules are in [the selection contract](../../contracts/ci-selection.v1.md). Source: [the workflow](../../.github/workflows/ci.yml) and the repository ruleset "CI must pass": no bypass, no force-push, no branch deletion.

## GitHub identity

Agents act on GitHub as the OpenWiz App, under [`openwiz.github-identity.v1`](../../contracts/github-identity.v1.md). Commits stay authored as Jake, with his GitHub noreply address.

| Setting | Value |
| --- | --- |
| App | OpenWiz, one for the factory, on selected repositories only (the contract's installations) |
| Key | The Cloudroom secret `OPENWIZ_GITHUB_APP_KEY`; the App id is `OPENWIZ_GITHUB_APP_ID` |
| Token | `openwiz github token --repository <owner/name> [--read]`, minted when needed, never stored |
| Fallback | No secret, no `openwiz` or a failed mint: today's account, said on stderr |
| Not as the App | Pushes that change `.github/workflows/`; Jake's approvals and settings |
| Record authors | `openwiz[bot]`, `jparker2006` |

Source: Jake, 2026-11-13 ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6844995843)).

## Approval rules

| Rule | Approver |
| --- | --- |
| Ask before publishing a release, a tag or a package | Jake |
| Ask before spending money or credits beyond the recorded limits | Jake |
| Ask before adding, reading or changing a secret | Jake |
| Ask before deleting user data | Jake |
| Ask before a cut-over | Jake |
| Ask before installing the repository webhook | Jake |
| Ask before adding a dependency, a toolchain file or a tool on the Mac | Jake |
| Ask before changing the `room-cli` allowlist or an approved limit | Jake |
| Ask before any live `room-cli` read or Mac work outside an approved live kit | Jake |
| Ask before shipping a release: Jake chooses when it ships | Jake |
| Ask before shipping a release whose exact changelog Jake has not approved | Jake |

For a release, the ship instruction and the exact changelog approval are the asks; ADR 0020 adds no other human step.

Source: the first six rows are the fleet's action gates; the next three are the "Jake approves first" list in [AGENTS.md, Live work and approvals](../../AGENTS.md#live-work-and-approvals); the last two are [ADR 0020](../adr/0020-release-on-demand.md). Jake, 2026-11-22 (spec #2273; [private record](https://github.com/jparker2006/ClosedWiz/issues/3065#issuecomment-7077657739)).

## Standing merge rules

| Pull request | Review | Merged by, and when |
| --- | --- | --- |
| A ticket in an approved plan graph (skill changes included) | The reviewer above, on its exact head | The loop, as soon as the reviewer's APPROVE names that exact commit and every required CI check is green on it, it has no conflict with `main`, and the base is checked by OpenWiz's merge queue. Without a queue, M1 applies: `main` has moved since that CI run only by merges that were themselves green; CI on `main` catches a bad combination, fixed forward. Then the merge is read back. The APPROVE is the merge decision; the loop performs it |
| Docs-only or evidence-only, outside any ticket (the handoff file, evidence) | None | The orchestrator, once CI is green |
| A grill, with the glossary terms and ADRs it settled | None | The orchestrator, once Jake confirms the grill's summary, or parks the grill, and CI is green |
| Anything to `release-*`, and every release | Ordinary development review/CI remain; no separate export review for the successor path | After verified O17 cut-over, agents execute the checked public-source release on Jake's actual ship instruction and exact changelog approval under ADR 0020; no third human release action. Before cut-over, no successor-path publication |

- **How a merge is done:** after `launch-fleet`'s admission check, `gh pr merge <N> --merge --match-head-commit <approved head>`, with a body naming the approval. Only `merged` at the approved head, read back, is a verified merge.
- **The merge queue checks the base** on OpenWiz: the approved head needs green required checks before queuing, and only the queue's passing result merges. No `--admin` bypass. A failed group means the builder merges `main` in and reruns affected checks.
- **Fixing a red `main`:** the orchestrator may file and approve one fix-forward issue whose only job is to make `main` pass again; it is built and reviewed like any ticket. Its approval comment opens `**Approved on its own by Jake, <date>:** under his standing approval for fixes to a red main`, with `Private record: <pointer>` on the next line.
- **Wording-only contract changes (C2):** the orchestrator, never a tick, may release a ticket held only because a contract it relies on was reworded, as `plan-graph`'s "A wording-only change (C2)" says. Any doubt goes to Jake.
- **Never retarget a pull request:** close it and open a new one against the other base. Never force-push.

Source: Jake, 2026-10-30, 2026-11-01 and 2026-11-05 (ADR 0008; [private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)); release rules in [ADR 0020](../adr/0020-release-on-demand.md).
