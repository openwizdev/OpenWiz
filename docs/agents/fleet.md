# Fleet settings

Every fleet in this project starts from these settings. Development work, tickets, pull requests and merges target **OpenWiz**, at `openwizdev/openwiz`. **ClosedWiz** remains private and holds grills, exact words, live evidence, machine details and orchestration state, under the [open development contract](../../contracts/open-development.v1.md). Historical ClosedWiz links identify the private record; they are not development targets. These settings are preparation in ClosedWiz until the separately approved cut-over; they do not claim the move, queue or public checks are live. Jake, 2026-11-07: approved revision 2 for preparation, with separate approval at each publish step ([private record](https://github.com/jparker2006/ClosedWiz/issues/1257#issuecomment-6704439350)).

The fleet skills read this file instead of naming any project's agents, commands or rules. Each value names its source; when a source changes, run the `setup` skill again (or edit the line by hand) so the two agree. Keep the machine-read table headings, columns and agent rows unchanged.

## Builder

One per ticket. Every ticket without an exact `polish`, `huntr` or `proposal` label uses this table. It builds on its own branch and never reviews or merges.

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Claude Code | `--provider claude-code` |
| Model | Opus 5.5 | `--model claude-opus-5-5` |
| Effort | High | `--reasoning-level high` |

## Builder for small tickets

Tickets with any of the exact labels `polish`, `huntr` or `proposal` use this table. The rules are complementary; ambiguous or unmatched classifications use `## Builder`. Small tickets use Codex Sol 6.1, High; everything else uses Claude Code, Opus 5.5, High.

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Codex | `--provider codex` |
| Model | Sol 6.1 | `--model gpt-6.1-sol` |
| Effort | High | `--reasoning-level high` |

Source: Jake, 2026-11-05: default builders use Claude Code, Opus 5.5, High, with Haiku helpers; the other family reviews ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)).

Small-ticket override: Jake, 2026-11-06: small or mechanical tickets use Codex Sol 6.1, High; the main builder profile remains Opus 5.5, High ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)).

Codex service tier: builders, reviewers, helpers and hunters use Sol 6.1 at High, or XHigh for hard work, at the default service tier. Do not enable fast mode; omit `--service-tier` overrides. Source: Jake, 2026-11-07: use Sol High or XHigh and turn off Codex fast mode, superseding the 2026-11-04 fast-mode rule ([private record](https://github.com/jparker2006/ClosedWiz/issues/1988#issuecomment-6712108296)). (A sentence, not a table row: the fleet tick's planner reads these tables strictly.)

**Rust dispatch limitation (#1465):** `AgentRule` and start `Settings` have no service-tier field, and the `ThreadSpawn` argument builder emits no service-tier argument. Rust-dispatched Codex starts depend on endpoint defaults. Effective tiers of existing threads are unverified; this settings change does not establish their tier or change them.

**Claude plan-limit fallback (#1196):** only a Claude builder with a verified branch and a positively reported Claude usage-limit stop gets one `restart` due item, using `## Builder for small tickets` and keeping that branch. With these settings, the restart selects Codex Sol 6.1, High, matching Jake's FB1 approval on [#1330](https://github.com/jparker2006/ClosedWiz/issues/1330#issuecomment-6673930927). This restores FB1's selection but does not finish #1330's separately approved dedicated fallback table and once-per-ticket restart proof. The tick records `launch-fleet: builder fallback due, branch <branch>` before printing it; the orchestrator performs the restart. That record consumes the ticket's single fallback; a dry run writes nothing. A reviewer never takes this fallback: its review waits for the selected family. A recorded builder replacement retains earlier code on the branch, so its family remains conflicting for new reviewer assignments. First and fresh reviews yield `look`, without starting a reviewer; the orchestrator or Jake chooses the reviewer explicitly.

## Reviewer for Claude-built

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Codex | `--provider codex` |
| Model | Sol 6.1 | `--model gpt-6.1-sol` |
| Effort | High | `--reasoning-level high` |

## Reviewer for GPT-built

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Claude Code | `--provider claude-code` |
| Model | Opus 5.5 | `--model claude-opus-5-5` |
| Effort | High | `--reasoning-level high` |

Source: Jake's #1196 approval above, with ADR 0008's other-family rule. Builders started before a settings switch keep their model; their actual provider selects the reviewer. A review already started keeps its reviewer.

## Reviewer

One per pull request, from a different model family than the builder. It reviews the exact head and never edits. If it can't be started, the review waits: it is never swapped for another model.

**Rust fleet tick (#1196):** first and fresh reviews use the appropriate strict family table above. Unknown or conflicting builder family yields `look`, with no reviewer start. The Sonnet small/low-risk selection below stays outside the Rust tick (#588).

**Small, low-risk reviews (#568, BN3):** use Claude Sonnet 5.5, High, for qualifying PRs. For a new reviewer assignment to a GPT-built PR, apply these assignments instead of the Opus default above. This selects a reviewer only where the standing merge rules require one; it does not add reviews to their no-review cases.

- **Small, low-risk GPT-built PR:** `--provider claude-code --model claude-sonnet-5-5 --reasoning-level high`.
- **Every other GPT-built PR, including unknown inputs:** `--provider claude-code --model claude-opus-5-5 --reasoning-level high`.

- **Small means additions + deletions < 200** (199 qualifies; 200 does not). Count the entire PR diff against its base, including tests, evidence and generated files, not its last commit, an estimate on the ticket or only selected paths. Read the PR's `additions`, `deletions`, full changed-file list and diff at the head being assigned; verify the head and base have not changed during the read. A binary diff or unavailable/non-numeric count cannot establish smallness.
- **Low-risk means either** the ticket has the exact `huntr` label, exactly one `## Tier` section containing only `0`, `1` or `2`, and a matching tier in huntr's gate approval comment (the approval form in `docs/agents/huntr.md`, #554); **or** the PR is docs only: every changed path is `README.md`, `STATUS.md`, `GLOSSARY.md`, or a Markdown (`.md`) file under `docs/` outside `docs/agents/`, `docs/adr/` and `docs/grills/`. Match repository-relative paths, with no empty, `.` or `..` components; on a rename both old and new paths must qualify. A mixed docs/code PR is not docs only. CI's docs-only classifier and a PR's labels alone do not establish this path test. Do not infer a tier from the title or kind; legacy huntr tickets without a recorded tier need the docs-only route or keep Opus.
- **Missing, unreadable, truncated or conflicting inputs select Opus** whenever they prevent establishing smallness or eligibility through at least one low-risk route. The smaller reviewer needs a complete, consistent diff and positive evidence of one of the two low-risk routes. A known non-docs PR without a tier is Opus; a complete docs-only diff needs no huntr tier. Tier 3 does not qualify through the huntr route. A failed Sonnet start waits for Sonnet, as the no-silent-fallback rule above requires.
- **Family comes first.** Never give a Claude-built PR a Claude reviewer: its reviewer remains Codex, Sol 6.1, High under `## Reviewer for Claude-built`. This rule does not change the #330 Codex reviewer assignment for Claude builders; GPT builders use the assignments above. A review already started keeps its reviewer. An unknown builder family cannot be assigned until it is known; Opus is only the risk fallback after the GPT family is established.
- **Builder family source.** Use the ticket's public `launch-fleet: start checked, branch <branch>` record: its branch must match the PR's head branch. Resolve the exact builder through private state or CloudRoom by the ticket title and branch, as the open development contract specifies, then read that exact thread's provider with `room-cli`. `codex` means GPT; `claude-code` means Claude. Private-repository readers also accept the legacy `launch-fleet: start checked, thread <id>, branch <branch>` record; no public writer uses it. Do not infer family from today's builder settings, the ticket's title or the branch name: builders started before a switch keep their model. If the record or thread/provider read is missing, unreadable or conflicting, or shows any other provider, the family stays unknown and reviewer assignment waits; Opus is not a family fallback. Never include a thread id in a public diagnostic or helper log.

Source: Jake, 2026-11-01: Sonnet reviews small low-risk GPT-built tickets under the stated size and tier/docs criteria; Opus reviews the rest, with the other-family rule unchanged ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)). Huntr's tier meanings are in [ADR 0014](../adr/0014-huntr-approves-by-risk-tier.md); missing markers disable the huntr route and never authorize an inferred tier.

Source: Jake, 2026-10-30: the selected reviewer is never silently swapped. Jake, 2026-11-01: reviewer effort is High ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)).

**Spec #330 (CI at fleet scale), an override for its tickets only:** builders are Claude Code, Opus 5.5, High (helpers Haiku 5.5, High), and reviewers are Codex, Sol 6.1, High (`--provider codex --model gpt-6.1-sol --reasoning-level high`; reviewer helpers Sol 6.1, High), so the reviewer is still the other family. A Codex Sol reviewer started for a #330 ticket is its named reviewer. Jake, 2026-11-01: retain this explicit pair for the CI spec ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)).

**Spec #1257 (Open development), per-ticket override:** builders default to Claude Code, Opus 5.5, High, reviewed by Codex, Sol 6.1, High. The small or mechanical tickets O8, O9, O10, O11 and O19 (#1276–#1279 and #1287) use Codex, Sol 6.1, High builders and Claude Code, Opus 5.5, High reviewers. Every other agent-built ticket in revision 2 uses the default pair; O17 (#1285) is Jake's cut-over step. These ticket assignments override the generic small-review selection; an agent already assigned keeps its model. Helpers follow the builder/reviewer family profiles below. Jake, 2026-11-07: revision 2 retains the per-ticket pairs ([private record](https://github.com/jparker2006/ClosedWiz/issues/1257#issuecomment-6704439350)); the original assignment detail is in the [private record](https://github.com/jparker2006/ClosedWiz/issues/1257#issuecomment-6672180411).

**Spec #2537 (the factory's own GitHub identity), an override for its tickets only:** builders are Claude Code, Opus 5.5, Medium (`--provider claude-code --model claude-opus-5-5 --reasoning-level medium`), and reviewers are Codex, Sol 6.1, High (`--provider codex --model gpt-6.1-sol --reasoning-level high`), so the reviewer is still the other family. GI6 (#2548) is Jake's own step. An agent already assigned keeps its model. Jake, 2026-11-13: approved with revision 1 of the plan graph ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6844995843)).

**Spec #2619 (the repository renames), an override for its tickets only:** builders are Claude Code, Opus 5.5, Medium (`--provider claude-code --model claude-opus-5-5 --reasoning-level medium`), and reviewers are Codex, Sol 6.1, High (`--provider codex --model gpt-6.1-sol --reasoning-level high`), so the reviewer is still the other family. RN4 and RN6 (#2624, #2626) are agent steps under Jake's direction. An agent already assigned keeps its model. Jake, 2026-11-13: approved with revision 1 of the plan graph ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6848396003)).

**Spec #2622 (WizSkills), an override for its tickets only:** builders are Claude Code, Opus 5.5, Medium (`--provider claude-code --model claude-opus-5-5 --reasoning-level medium`), and reviewers are Codex, Sol 6.1, High (`--provider codex --model gpt-6.1-sol --reasoning-level high`), so the reviewer is still the other family. WZ8 (#2629) and WZ10 (#2638) are Jake's own steps; the export review uses the export-review skill's own reviewer. An agent already assigned keeps its model. Jake, 2026-11-13: approved with revision 1 of the plan graph ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6848396003)).

## Builder helpers

A builder's swarm: cheap helpers that find things and do chores for it (search the code, run and read tests, draft tests). The builder keeps every judgment and writes every line. Each helper is a CloudRoom thread the builder starts; how to start, brief, check and archive one is in [helpers.md](helpers.md).

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Claude Code | `--provider claude-code` |
| Model | Haiku 5.5 | `--model claude-haiku-5-5` |
| Effort | High | `--reasoning-level high` |

Source for Claude builder helpers: Jake, 2026-11-05: Claude Code, Haiku 5.5, High ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)).

Codex builders instead use Codex, Sol 6.1, High (`--provider codex --model gpt-6.1-sol --reasoning-level high`). Jake, 2026-11-06: this supersedes the Terra helper setting ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)).

## Reviewer helpers

A reviewer's swarm: helpers that check one part each (one finding, which they try to reproduce; one lens; one group of acceptance criteria). The reviewer keeps every judgment and posts the one report. Reviewers of Claude-built pull requests use Codex, Sol 6.1, High helpers, at the default service tier as above. How to start, brief, check and archive one is in [helpers.md](helpers.md).

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Codex | `--provider codex` |
| Model | Sol 6.1 | `--model gpt-6.1-sol` |
| Effort | High | `--reasoning-level high` |

Reviewers of GPT-built pull requests instead use Claude Code, Haiku 5.5, High (`--provider claude-code --model claude-haiku-5-5 --reasoning-level high`), so the review stays in another family than the build, helpers included (Jake, 2026-11-05: Claude helpers stay in the reviewer's family; [private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)).

Source: Jake, 2026-11-06: Sol High replaces Terra for Codex helpers, including #330. GPT-built pull requests keep the other-family Claude reviewer and Haiku helper profiles ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)).

## Swarm size

How many helpers each side starts for a ticket, to begin with. The build and review skills size the swarm from the ticket.

| Ticket | Builder helpers | Reviewer helpers |
| --- | --- | --- |
| Small | about 1–3 | about 1–3 |
| Medium | about 3–8 | about 3–8 |
| Large | about 8–15 | about 8–15 |

- **By the work's independent pieces:** about one helper for each piece that can be done on its own, such as an area of the owned paths, a group of acceptance criteria, a slow command to run, or a finding to check.
- **A starting point, never a cap:** a ticket with more independent pieces gets more helpers. A limit comes only after a real problem, as for builders ([ADR 0002](../adr/0002-no-artificial-cap-on-builders.md)).

Source: Jake, 2026-10-31: size the swarm by independent pieces, with the table as a starting point and no artificial cap; adjust for actual resource limits ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)).

## Loop

**Overload pause (CS5, #2310):** the orchestrator checks the bounded queue and
both REST/GraphQL pools through `fleet.sh overload` before new merge-batch
admission, automatic refreshes and nonessential polling. Alarm at oldest required
queued-job wait >=5 minutes or either remaining/limit <10%; escalation to Jake
is due at >=15 minutes or either pool's exhaustion, under separate messaging
authority only. Honour reset/secondary backoff. Missing, stale or incomplete
observations cannot clear a pause. Share one durable private repository-scoped
state path; preserve the cause/evidence and never auto-resume. Jake must settle
resumption before that path is enabled. Let admitted jobs/agents and necessary
completion/reconciliation finish; cancel nothing and bypass no existing gate.
See `tools/ci-overload/README.md`; fixture proofs send no notification and prove
no live alarm or delivery.

How `launch-fleet` is woken in this project. The loop identities and webhook details stay in ClosedWiz's private orchestration state. Public records carry no thread id.

| Setting | Value |
| --- | --- |
| GitHub's messages | A repository webhook to the wake loop's address (`room-cli loop create --webhook --new-thread`): `application/json`, no secret, events `issues`, `issue_comment`, `pull_request`, `pull_request_review`, `check_suite` and `workflow_run` (GitHub's documentation names the second for GitHub Actions runs, and doesn't say whether they send the first). Added only with Jake's yes; until then, off |
| The safety net | A full check every 30 minutes (`--cron '*/30 * * * *'`); every 10 minutes while GitHub's messages are off |
| A spec's fleet thread | One per approved spec (ADR 0011, #192), started by the orchestrator as its own child when Jake approves the spec's plan graph, with the agent the safety net runs (`room-cli loop list`). Its own loop wakes that same thread: `launch-fleet #<spec> <owner>/<repo>`, `--same-thread`, its spec's check every 10 minutes (`--cron '*/10 * * * *'`, `loop.sh` with `FLEET_SPEC`) |

- **A wake reads only what its messages name** (`fleet.sh wake`), and costs none of GitHub's hourly allowance to send. A webhook loop takes no script, so each batch of messages starts a tick; the skill has it end at once when nothing is due.
- **Lines that come due with time** (a claim with no outcome after 10 minutes, a builder or reviewer quiet for 30), a spec's own lines when no message names the spec, and anything a message missed are found by the safety net, up to 30 minutes later.
- **A spec with a fleet thread is that thread's alone.** Once its public `launch-fleet: fleet active` record is on the spec (its thread and loop identities stay in private state), the safety net and the wakes print nothing about it, and the fleet thread's own loop checks it every 10 minutes: a tick the wake loop starts couldn't reach the agents the fleet thread started. So its lines wait up to 10 minutes, not for GitHub's messages. How a fleet thread starts, takes over and moves a running fleet over is in `launch-fleet`'s "Fleet threads".

Source: Jake, 2026-11-01: webhook wakes handle named work immediately, with a slower safety net; per-spec fleets own their work and retain their own scheduled wakes. Jake, 2026-10-31: one retained fleet thread per spec ([ADR 0011](../adr/0011-one-fleet-thread-per-spec.md); [private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)). Switching the actual loops/webhook is a gated cut-over step, not an effect of editing these settings.

**Agent GitHub reads (C10, #2317; Assumption A1).** One switch: the shared installation read route is on only when the installation's credentials are configured through C9's protected provisioning (`<state>/service/github-reads/installation.json`, [C8's reader](../../tools/github-reads/README.md)). Off, every reader keeps its `gh` reads unchanged. On, the readers below go through C8's `read.py` for the explicit `GH_REPO`, and a missing helper or a missing, expired or revoked installation refuses the read: nothing falls back to `gh` or the personal quota. **Routed:** `fleet.sh`'s `repos/<REPO>` REST reads (open issues, issue details, comments and blockers, the two settings files, pull requests and their files, branch refs, nightly commit comments, and repository privacy), as authority reads bound to the check's start (`--max-age 60`); the `where-are-we` collector's three lists, as display reads (`--max-age 60`). **Not routed (gaps for Jake):** G1 `fleet.sh`'s GraphQL, whose fragments and connections C8's grammar refuses; G2 its issue search (`search/issues`, outside `repos/<REPO>/`); G4 `plan-graph`'s `revision.sh`, other skills' scripts, agents' own `gh` reads, and every write and Git push, which keep their identity; G5 the bundled safety-net loop, whose own sandbox shares no state; G6 GI1's unchanged-spec account probe (`user`), which C8's repository-only scope cannot express and which stays on `gh`; G7 nightly-workflow reads (`repos/<REPO>/actions/workflows/*`), which keep `gh` so an absent workflow (HTTP 404) still skips only the nightly check. C8's non-200 outcome support remains a follow-up before C13. G3: a routed list whose later pages GitHub names `repositories/<id>` refuses as a whole, never truncated. A refused installation privacy read stops the check. Unreadable issue comments instead become incomplete history and a look for that issue, without personal-quota fallback. A routed read is one input to the unchanged approval, hold, review, merge and C3 pause rules. Installation and live rollout keep their own recorded authority (C9, C13). Proof: `tools/github-reads/test_consumers.py` (`release:ci2-read-consumers`), fixtures only.

**Finite ops passes (#1456, preparation).** Every wake, the PC's primary and an independent standby, is one bounded pass through `loop.sh --pass`: it does its due work, records each outcome and ends, with no watcher, waiting poll loop or sleep left behind. A failed, stopped or over-age pass is reported and kept pending until acknowledged. Only the current generation's owner acts; project and spec ticks share each operation key, and every effect goes through OB3's boundary, where starts, deliveries, hold releases and merges stay disabled under OB-A1. Spec #2185, revisions 7/8 (Jake, 2026-11-12; [private record](https://github.com/jparker2006/ClosedWiz/issues/2185#issuecomment-6815747648)).

**Independent standby and wakes.** The standby runs outside the PC's failure domain, as a Cloud thread woken by its own scheduled loop, reading GitHub only; builders and reviewers read their pending records on GitHub on their own wakes. Takeover is an admitted next-generation claim, never a timeout. This plan is Unverified: #2244 discovers the access and OB8 (#2190) alone installs or activates it.

**Delegated ops authority and daily audit.** Narrow same-intent path requests are evaluated by the ops agent under the `narrow-grant` rule instead of a blanket escalation; contract, interface, dependency, workflow, scope, live and spending cases, and anything unreadable, still go to the orchestrator. The orchestrator audits every grant daily from its saved cursor and keeps grills, planning and real exceptions.

## Labels

The triage labels and their names here are in [triage-labels.md](triage-labels.md). A fleet uses `held` for approval holds and `polish` for small follow-ups:

| Label | Means | Put on by | Taken off by |
| --- | --- | --- | --- |
| `held` | The ticket is held: it waits for the user's approval of a changed plan or contract, and never starts while it has this label. It has no ready label while held | `plan-graph`, before it changes an approved plan; `launch-fleet`, when a merge changes a contract the ticket relies on | `plan-graph`, as it puts the ready label back once the new approval is recorded; `launch-fleet`'s `release` line, if it is still on after that |

The skill that holds a ticket first creates the label, once, with the description "Held: waits for the user's approval".

The `polish` label means Small follow-up in the polish backlog; never blocks a spec. `launch-fleet` puts it on open low review follow-ups when it writes a spec's closing summary; it stays while they wait in that backlog. Create it once if missing. A spec closes when all its planned tickets have verified merges (planned human work is complete) and its live check, if it has one, has passed; open follow-ups never hold it open. Jake, 2026-11-04: this is the spec completion rule ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)).

Source: Jake, 2026-10-31: held tickets carry `held` without a ready label so the fleet can distinguish a hold from missing approval ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)). Both plan and contract holds use it.

## Test commands

Locally, a builder runs the red/green proof and only the tests its change can affect, plus `cargo fmt --check` and `cargo clippy -p <touched-crate> --all-targets -- -D warnings` for the crates it touched. Never run the full workspace or browser suites locally. After a failure, fix it and rerun only the failed checks. Open the ready pull request once these scoped local checks pass; CI runs the full suites below, and its passing result at the exact head is the hand-back gate. Reviewers review the diff and CI's results, reproducing only specific findings. Exact-head review and M1 stay unchanged.

Source: Jake, 2026-11-03: run affected tests locally and leave the full set to CI; reaffirmed 2026-11-06 ([private record](https://github.com/jparker2006/ClosedWiz/issues/1724#issuecomment-6697900652)).

The product CI command reference, distributed across the planned lanes; the public privacy check is additional, as listed below. Rust 1.99.1 with `rustfmt` and `clippy` (there is no `rust-toolchain.toml`), and Node 24.22.1.

**Only one `cargo` command may run per checkout at a time.** While tests or builds run, run no second Cargo command in that checkout, including a mutation script or another proof that invokes Cargo. A build can replace `target/debug/fake-room-cli` (which the tests' fake `room-cli` symlinks use), `target/release/openwiz` or `target/debug/openwiz-server` while tests are using them, causing a transient missing-binary failure. Anything that runs beside those checks must use a separate worktree with its own `target/`; never share a target directory between those worktrees, including through `CARGO_TARGET_DIR`. Source: #195, from #176's diagnosis of #146's report 2.

| # | Folder | Command | CI check |
| --- | --- | --- | --- |
| 1 | root | `sh .github/actions/docs-only/test.sh` | `ci` |
| 2 | `apps/web` | `npm ci --ignore-scripts` | `ci` |
| 3 | `apps/web` | `npm run build` | `ci` |
| 4 | `apps/web` | `npm run typecheck` | `ci` |
| 5 | `apps/web` | `npm run check` | `ci` |
| 6 | root | `cargo fmt --check` | `ci` |
| 7 | root | `cargo clippy --workspace --all-targets -- -D warnings` | `ci` |
| 8 | root | `cargo build --workspace` | `ci` |
| 9 | root | `cargo test --workspace` | `ci` |
| 10 | root | `cargo test -p openwiz-tests --test checks pending` | `ci` |
| 11 | root | `cargo build --release` | `ci` |
| 12 | `apps/web` | `npm test` (its browser files 3 at a time, longest first: `test/run-browser.mjs`, #431) | `ci` |

Only selected export consumers wait for the web build (3). A full run includes A8 and the browser tests that read `apps/web/out`; tests without that prerequisite can start after the plan. `npm test` drives a Chromium: `/usr/bin/chromium`, or the one `OPENWIZ_CHROMIUM` names.

Source: [AGENTS.md, Commands](../../AGENTS.md#commands), and [the CI workflow](../../.github/workflows/ci.yml), which owns the current job steps. The Chromium: [`apps/web/test/support/browser.mjs`](../../apps/web/test/support/browser.mjs).

## CI checks

In ClosedWiz, `CI_SMALL_RUNS_ON` routes `changes`, `always`, `select-map`, `ci` and the legacy `web-test` bridge to a separate runner pool; unset, it falls back to `CI_WEB_RUNS_ON` and then the existing default, while long web/skill jobs keep `CI_WEB_RUNS_ON`, Rust jobs keep `CI_RUST_RUNS_ON`, and fork PRs always use `ubuntu-24.04`.

| Check | Runs | Required on |
| --- | --- | --- |
| `ci` | The saved plan, always-run checks, every selected lane and each selected skill suite must pass; failed, cancelled or missing work fails | `main`, `release-*` |

**Additional public check: `privacy` (O3).** It checks the public tree, commit range and PR text on every public pull request and push, including merge groups. OpenWiz's ruleset requires it on `main` and `release-*`, alongside the product checks named in the fleet table. The check-name migration belongs to #1262; its required `ci` check replaces the earlier product check names when that ticket lands. O7 preserves the table it receives, including that migration. O3 fixes its check name as `privacy`, verified in [PR #1846](https://github.com/jparker2006/ClosedWiz/pull/1846) at implementation pin `51e9b6b7791dcf9b077fd7163d1b4ad30990d23e`; O12 still applies and reads back the public ruleset. ClosedWiz preparation keeps the existing product-check table so current readers and fixtures keep working.

- **Every required product check and the additional public privacy check must pass** before anything merges to `main` or a `release-*` branch: the ruleset "CI must pass" has no bypass, and also refuses force-pushes and branch deletion. It does not require a pull request: sending every change to those branches through one is this project's standing procedure.
- **`ci` must pass** before merge. The orchestrator switches the ruleset once at X5's merge, from `web-build`, `rust` and `web-test` to `ci`, and reads it back. This documentation does not establish that the live transition happened. The ruleset's no-bypass, deletion and non-fast-forward rules and the PR procedure are unchanged. The temporary `web-test` bridge follows `ci` so the migration PR also satisfies the old required name.
- **A draft fails the plan and `ci`.** Marking it ready starts a full run.
- **Selection is computed once** in `changes`, using the classifier and the signed K15 map with K16 prerequisites. The plan lists every run/skip and reason. The always-run set covers format, classifier/selector tests, architecture, privacy and static checks. A skill-only change can run just that set and its skill suite. Unknown paths, empty/failed diffs, untrusted maps, stale events, reruns, release bases, main pushes, nightly runs and merge groups cannot narrow coverage. Lanes read the saved plan. Only a selected export consumer waits for the web build.
- **Main keeps a full run on every push.** The batch switch gate, `ci/main-batch/admit.py` (C12, #2319), checks the C11 combined-batch and nightly proof, the code it was proved on and the overload pause. Its answer stays `per-push-full` until Jake names a supported admission mechanism; nightly full runs and every required check stay.

Source: [the workflow](../../.github/workflows/ci.yml), [the legacy classifier](../../.github/actions/docs-only/classify.sh), [the selection contract](../../contracts/ci-selection.v1.md), spec #1256 and X5 #1262. The orchestrator owns the live product required-check transition and read-back; O3 supplies the fixed public privacy check and O12 applies and reads back the public ruleset. Until those preparations and cut-over finish, these public requirements are not a claim about deployed settings. Merge policy and agent assignments are unchanged.

OpenWiz's required **CI must pass** ruleset covers `main` and `release-*`, requires every check in the table, has no bypass, and refuses force-pushes and deletion. Every change goes through a pull request. There are **no self-hosted runners** on OpenWiz; jobs use GitHub's standard hosted runners. `CI_RUNS_ON` and `CI_RUST_RUNS_ON` stay unset. Pull requests from forks need approval before CI for **every outside contributor**. These are the required public settings, applied and read back by O12; this document does not activate them.

## GitHub identity

The agents act on GitHub as the OpenWiz App, under [`openwiz.github-identity.v1`](../../contracts/github-identity.v1.md); [`launch-fleet`'s "GitHub identity"](../../skills/launch-fleet/SKILL.md#github-identity) says how. Builders push and open pull requests, reviewers comment, and managers comment, label and merge as the App, each with a token minted when needed (`--read` for reads). Commits stay authored and committed as Jake, with his GitHub noreply address read from GitHub. Jake keeps his own account for his own actions.

| Setting | Value |
| --- | --- |
| App | OpenWiz, one for the factory, on selected repositories only (the contract's installations) |
| Key | The Cloudroom secret `OPENWIZ_GITHUB_APP_KEY`; the App id is `OPENWIZ_GITHUB_APP_ID` |
| Token | `openwiz github token --repository <owner/name> [--read]`, minted when needed, never stored |
| Fallback | No secret, no `openwiz` or a failed mint: today's account, said on stderr |
| Not as the App | Pushes that change `.github/workflows/`; Jake's approvals and settings |

The App merges only under the standing merge rules below. A repository rule that refuses its merge stops for Jake; nobody bypasses it. Until Jake installs the App (GI6, #2548), every mint fails and the fleet runs as today's account. Source: Jake, 2026-11-13: approved with revision 1 of spec #2537's plan graph ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6844995843)).

## Standing merge rules

| Pull request | Review | Merged by, and when |
| --- | --- | --- |
| A ticket in an approved plan graph (skill changes included) | The reviewer above, on its exact head | The loop, as soon as the reviewer's APPROVE names that exact commit and every required CI check is green on it, it has no conflict with `main`, and the base is checked by OpenWiz's merge queue. Without a queue, M1 applies: `main` has moved since that CI run only by merges that were themselves green; CI on `main` catches a bad combination, fixed forward. Then the merge is read back. The APPROVE is the merge decision; the loop performs it |
| Docs-only or evidence-only, outside any ticket (`STATUS.md`, the handoff file, evidence) | None | The orchestrator, once CI is green |
| A grill, with the glossary terms and ADRs it settled | None | The orchestrator, once Jake confirms the grill's summary, or parks the grill, and CI is green |
| Anything to `release-*`, and every release | Ordinary development review/CI remain; no separate export review for the successor path | After verified O17 cut-over, agents execute the checked public-source release on Jake's actual ship instruction and exact changelog approval under ADR 0020; no third human release action. Before cut-over, no successor-path publication |

- **In one line:** docs-only and evidence-only changes by the orchestrator (the handoff page, a grill once Jake confirms it, and the ADRs he confirmed with it) merge on green CI without a reviewer; everything else follows ADR 0008.
- **Fixing a red `main` (standing approval):** when `main`'s push CI is red, the orchestrator may file and approve, on its own, one fix-forward issue whose only job is to make `main` build and pass again (no other change), with exact owned paths; it is built and reviewed like any ticket (the other family reviews; ADR 0008 merges it). Jake, 2026-11-01: the orchestrator may approve this narrow fix-forward work ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)). Its approval comment opens `**Approved on its own by Jake, <date>:** under his standing approval for fixes to a red main`, followed by `Private record: <pointer>` on the next line, pointing to the comment holding that standing approval.
- **Wording-only contract changes (standing approval, C2):** a ticket held because a merge only reworded a contract it relies on (no change to a route, field, status, header, bound, limit, write rule or approval rule) is assessed and released by the orchestrator, never a tick, without Jake's re-approval, only when every contract change its new approval covers is wording-only, as `plan-graph`'s "A wording-only change (C2)" says, and any doubt or ticket edit still goes to Jake; Jake, 2026-11-05: the orchestrator may release wording-only contract holds under C2 ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)).
- **Release approval policy:** after verified O17 cut-over, [ADR 0020](../adr/0020-release-on-demand.md) makes Jake's ship instruction and exact changelog approval the only human release actions. Preparation can happen earlier. Agent-run combined smoke, applicable send/new/App-permission/spending live results, CI and privacy/claims remain automatic candidate-bound gates within approved kits; no export-plan/final-diff/standalone Sol-export, mandatory device or per-step publish approval. Ordinary development plan/review/CI and merge rules remain; O16/O17 prerequisites, holds and separate cut-over authorization stay intact. No broader live, activation, spending or historical-backfill authority is granted.
- **How a merge is done:** once `launch-fleet`'s admission check lets it in (the merge step's step 3: with a queue, the queue checks the base; without one, the base rule in the table above), `gh pr merge <N> --merge --match-head-commit <approved head>`, so only the approved commit can merge, with a body naming the approval it relies on. Then read it back with the one query in `launch-fleet`'s merge step (the pull request's state, head and place in the merge queue): only `merged`, at the approved head, is a verified merge.
- **On OpenWiz, the merge queue checks the base.** Every merge to `main` at `openwizdev/openwiz` goes through GitHub's merge queue, including the orchestrator's. The approved head must have green required checks before queuing; the queue re-tests its merge group on the latest `main` with any requests ahead of it. Every required check, privacy included, must run on `merge_group` under the same name. Only the queue's passing result permits the merge. No `--admin` bypass. The queue writes the merge commit message, so the public `merge queued` record names the approval. A failed group removes the request; record `merge blocked`, and the builder merges `main` in before rerunning affected checks. Queue method: **Merge**; keep a status-check timeout long enough for the full CI path (at least 75 minutes for the documented 15-minute web build plus 60-minute Rust budgets). O12 applies and reads it back; O20 and O18 verify the move and live queue separately.
- **Without a queue** (including preparation on the private ClosedWiz repository): M1 remains the base rule in the table. The same command merges at once only after the admission check, exact-head review and all required checks pass, then the merge is read back. ClosedWiz stays private; its existing work continues there until cut-over.
- **Keep old addresses working.** No repository named OpenWiz is ever made again under `jparker2006`: it would break the old web, git, API and release-download redirects after O20 moves OpenWiz to `openwizdev/openwiz`. Preparation does not perform that transfer.
- **A pull request is never retargeted:** close it and open a new one against the other base. Nothing is ever force-pushed.

Source: Jake, 2026-10-30: plans authorize ticket merges after exact-head review and green CI; the loop performs the merge ([ADR 0008](../adr/0008-openwiz-merges-tickets-jake-approves-plans.md); [private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)). Jake, 2026-11-01: M1 is the standing base rule without a queue ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)). Jake, 2026-11-07: revision 2 prepares OpenWiz at the organization address with the queue and redirect protection, while the transfer and cut-over each retain a separate approval ([private record](https://github.com/jparker2006/ClosedWiz/issues/1257#issuecomment-6704439350)).
