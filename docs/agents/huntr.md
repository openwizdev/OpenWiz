# huntr settings

The `huntr` skill and its scripts read this file. The JSON block is parsed by `approve.mjs` and `lease.mjs`: keep it byte for byte unless Jake approves a change. Source: Jake, 2026-11-01: approval by risk tier, under his standing approval (#554; [private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)). Jake, 2026-11-06: the cap and priorities (HC1, HV1, PA2, PS1, PS2; [private record](https://github.com/jparker2006/ClosedWiz/issues/1457#issuecomment-6682983368)). Public reports carry no thread ids or private content.

## Tiers

| Tier | Work | Proof |
| --- | --- | --- |
| 0 | Report only: audits and findings, no change | Named audit/report command; no changed files or lines |
| 1 | Tests and docs: nothing the product runs changes, including missing tests and missing/stale docs | Spec/coverage or docs check at a public seam |
| 2 | Same behaviour, better inside: cleanups, faster code, faster tests, clearer errors | Every existing test passes unchanged; any speed claim also has a before-and-after measurement on the same machine |
| 3 | Behaviour fixes: bugs, flaky tests, security holes in our own code, accessibility faults | A failing test first, then the same test passing |

- **Maximum approved tier:** `max_tier` in the JSON, today **3**. Kind describes the work; it is not an allowlist. A kind that fits no tier is a **kind proposal** (kind, proposed tier, proof, three real examples) to Jake through the orchestrator, once. His approval is a comment on the switch issue whose first line starts `huntr kind approved:` and names the kind and tier. Never force uncertain work into a tier.
- **Tier 0** ends with the report to the orchestrator. Findings that need changes become separate tier 1–3 candidates.
- **Security** fixes are **proposals**: `needs-triage`, no `huntr` label, no approval, no exploit details anywhere public until the verified merge, and **two independent reviewers** with exact-head approvals. Keep the failing test private; the issue names a safe proof command and where its evidence is.
- **Speed** claims need before-and-after measurements on the **same machine**, and faster tests must still fail on a controlled planted break.
- **Size:** one problem per ticket, at most **200 changed lines** (additions + deletions over the whole PR diff, tests and evidence included). A batch shares one cap; split an oversized batch into PRs that each carry their own proof. Keep full logs in CI or private storage; commit a short summary with a log reference.

## Never-list

The room-cli allowlist, approved limits, contracts and schemas, dependencies and toolchain, CI workflows, actions and runner kit, skills and their registrations, `docs/agents/`, ADRs, grills, `AGENTS.md`, specs' issues, and paths owned by tickets being built or carrying an unresolved builder-start claim. Standalone issues only. Features, side specs, live work, releases, publishing and spending are proposals. Inside these limits be safe but liberal.

## Pace and priority

Every 30 minutes; at most 50 open huntr work tickets (`open_cap`). Approved fleets first. Two empty hunts in a row pause until the next calendar day in the project's timezone; an unavailable source is a gap, not an empty hunt.

Choose slices and file candidates in this order (HV1, PA2, PS1, PS2):

1. Factory, CI and throughput bugs, including tests slower than 10 seconds (tier 2) and contradictions that mislead agents. Merge-conflict hotspots are proposals only.
2. Correctness bugs in released features, including error messages and the truth of README, AGENTS.md and CHANGELOG; product performance as tier 2.
3. Privacy leaks in anything OpenWiz publishes: thread ids, personal paths, real names, live content.
4. Flaky tests.
5. Missing tests, refusal paths first.
6. Other docs and wording, only when they would mislead an agent.

Priority never overrides the never-list, tier proofs or the security hold.

## Models

| Role | Provider | Model | Effort |
| --- | --- | --- | --- |
| One controller per hunt | `codex` | `gpt-6.1-sol` | `xhigh` |
| Wide hunting and reruns | `codex` | `gpt-6.1-terra` | `high` |
| Change builder | `codex` | `gpt-6.1-sol` | `high` |

The controller proves every finding before the gate. Send one hunter per area and checklist category, with no artificial cap; record each slice's result or blocked gap. No silent model fallback. **Security-hunter exception (PS1):** when the provider's safety filter blocks Codex, run the security slice on Claude Code, Opus 5.5, High (`claude-code`, `claude-opus-5-5`, `high`) and record it. Change builders and reviewers otherwise follow `fleet.md`. Source: Jake, 2026-11-10 (HN2; [private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6768723249)).

## Switch, lease and record

- **Switch:** issue #394. The newest comment whose first line starts `huntr:` decides: `huntr: on` or `huntr: off`, optionally followed by a spaced dash and a reason. Anything else, absent or unreadable, is off. Off stops new hunts and approvals; existing builders continue.
- **Lease:** one controller at a time, by a self-generated run id (`lease.mjs id`), never a thread id. A lease lasts **45 minutes** from its last claim or renewal, in GitHub's comment times; a working controller checkpoints every **30 minutes**. Lease lines start `huntr lease:`, never `huntr:`. Exit 2 from `lease.mjs` always means: do not act as the controller.
- **Record:** #394 is the only report channel: checkpoints, final results, tier-0 audits, proposals and blockers. Each slice's latest manifest and result live there (`manifest.mjs`), split into numbered comments of at most **65,536** UTF-8 bytes and read back before the controller archives. Reuse a slice only for an identical plan and files with a clean PASS; never fall back to an older PASS over a newer failure. Slices that read changing inputs (CI, issues, live checks, measurements, flakes) always run.

## Hunting checklist

Questions to investigate, never permission to touch a protected path. Each finding records its exact proof command, environment and result at a public seam with synthetic inputs.

- **Speed (tier 2):** work that could overlap; repeated reads, I/O or network calls; avoidable allocations or copies; slow startup, builds or tests. Proof: same-machine before/after with identical results.
- **Size (tier 2):** dead code, unused options or files, duplicates, committed generated files. Proof: callers traced, unchanged tests pass. Removing a promised command is a proposal.
- **Correctness (tier 3):** unchecked errors or panics on input, boundary cases, unbounded waits or retries, races and leaked resources. Proof: a failing-first public-seam test.
- **Security and privacy (tier 3, proposals):** secrets or private data in logs, files or fixtures; command or path injection; trusting unvalidated tool output. Proof: a private failing-first test.
- **Contracts and docs:** docs or help text that disagree with the command (tier 1; tier 2 for text in code); missing docs (tier 1); contracts or schemas that drift from the code (tier 1; the edit is a proposal).
- **Tests:** untested claims, empty or duplicate tests (tier 1); flaky tests (tier 3, never hidden with retries); slow tests (tier 2).
- **Test audit (`test-audit`, tier 1):** a test that proves nothing its neighbours don't, by build-ticket's test rules. Proof: coverage within 2 percentage points on a fixed denominator, and every mutant a removed test kills is still killed. Proof cases, contract tests and the pending list's tests are only consolidated, never deleted.
- **Developer experience (tier 2):** unclear errors or names, with unchanged tests.

## Gate

From the consuming repository root, `node <installed-huntr>/scripts/approve.mjs <issue-number>` posts the one approval comment (exit 0) or refuses with a reason (exit 2, nothing posted). Only the gate posts this form:

```text
**Approved on its own by huntr, <date>, tier <tier>, kind <kind>:** under Jake's standing approval (ADR 0014).
Private record: <pointer to the ClosedWiz comment holding the standing approval>
```

The gate counts every other open `huntr` issue (49 allow the 50th), refuses paths owned by tickets being built or with an unresolved `launch-fleet: starting` claim, and refuses unreadable scope. Candidate paths are exact repository-relative files. Tier 1 files must be tests, fixtures or docs; tiers 2–3 may also touch code. A protected prefix always wins over a tier. A new limit-bearing file needs a settings change approved by Jake. The gate checks recorded intent; the controller checks the reproducer and the reviewer checks the actual diff, including any change to an approved limit.

```json
{
  "version": 2,
  "label": "huntr",
  "switch_issue": 394,
  "max_changed_lines": 200,
  "open_cap": 50,
  "groups": {
    "code": {
      "prefixes": [
        "crates/core/src/",
        "crates/cli/src/",
        "crates/adapters/cloudroom/src/",
        "crates/adapters/github/src/"
      ],
      "suffixes": [
        ".rs",
        ".ts",
        ".tsx",
        ".js",
        ".mjs",
        ".cjs"
      ],
      "root_suffixes": []
    },
    "tests": {
      "prefixes": [
        "tests/"
      ],
      "suffixes": [],
      "root_suffixes": []
    },
    "docs": {
      "prefixes": [
        "docs/"
      ],
      "suffixes": [],
      "root_suffixes": [
        ".md"
      ]
    }
  },
  "never_prefixes": [
    "crates/adapters/cloudroom/src/allowlist.rs",
    "crates/core/src/limits.rs",
    "crates/core/src/attachment.rs",
    "crates/core/src/messaging/mod.rs",
    "crates/core/src/messaging/reconcile.rs",
    "crates/core/src/new_thread/mod.rs",
    "crates/core/src/new_thread/start.rs",
    "crates/core/src/fleet/tickets.rs",
    "crates/core/src/fleet/fleets.rs",
    "crates/adapters/cloudroom/src/process.rs",
    "crates/adapters/github/src/process.rs",
    "crates/adapters/github/src/fleets.rs",
    "crates/adapters/github/src/writes.rs",
    "contracts/",
    ".github/workflows/",
    ".github/actions/",
    ".githooks/",
    "skills/",
    ".claude/",
    ".agents/",
    ".claude-plugin/",
    "tests/checks/skills.rs",
    "docs/agents/",
    "docs/adr/",
    "docs/grills/"
  ],
  "never_names": [
    "AGENTS.md",
    "CLAUDE.md",
    "Cargo.toml",
    "Cargo.lock",
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "bun.lock",
    "bun.lockb",
    "deno.json",
    "deno.jsonc",
    "deno.lock",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
    "Pipfile",
    "Pipfile.lock",
    "go.mod",
    "go.sum",
    "Gemfile",
    "Gemfile.lock",
    "composer.json",
    "composer.lock",
    "rust-toolchain",
    "rust-toolchain.toml",
    ".nvmrc",
    ".node-version",
    ".npmrc",
    "tsconfig.json"
  ],
  "never_name_prefixes": [
    "requirements",
    ".env",
    "next.config."
  ],
  "never_components": [
    ".git",
    ".cargo"
  ],
  "never_suffixes": [
    ".schema.json"
  ],
  "max_tier": 3,
  "tiers": {
    "0": [],
    "1": [
      "tests",
      "docs"
    ],
    "2": [
      "code",
      "tests",
      "docs"
    ],
    "3": [
      "code",
      "tests",
      "docs"
    ]
  }
}
```

## Finding issue form

Use each section exactly once and keep the full never-list declaration. Proof class is exactly `report` (0), `coverage-or-docs` (1), `unchanged-existing-tests` (2) or `failing-test-first` (3). Speed proof is `none`, or `Machine: <one machine>`, `Before: <measurement>`, `After: <measurement>`, a blank line and an `sh` fence with the comparison. Security fix must be `no` for approval; anything else is a proposal. Add the affected commit, safe failing output and acceptance criteria after the form.

````markdown
## Tier

3

## Kind

bug fix

## Product promises

No new features, contracts or dependencies.

## Proof class

failing-test-first

## Problem

One synthetic ordering defect.

## Proof

```sh
synthetic-repro --fixture ordering
```

## Speed proof

none

## Security fix

no

## Owned paths

- `crates/core/src/ops.rs`
- `tests/proof/p01_list.rs`

## Size

120 / 200 changed lines (added + deleted)

## Never-list

The never-list in docs/agents/huntr.md applies in full.
````

## Attack targets

| Target | Kind | Copy | Live rate | Files to |
| --- | --- | --- | --- | --- |
| `name:fetcher` | surface | `tests/red-team/fetcher/` | 0 | `openwizdev/OpenWiz` |
| `name:market-installs` | surface | `tests/red-team/market/` | 0 | `openwizdev/OpenWiz` |

## Attack models

| Role | Provider | Model | Effort |
| --- | --- | --- | --- |
| controller | `codex` | `gpt-6.1-sol` | `xhigh` |
| attacker | `codex` | `gpt-6.1-terra` | `high` |

The security-hunter exception (PS1) under Models applies: when the provider's safety filter blocks Codex, run that slice on `claude-code`, `claude-opus-5-5`, `high` and record it. No other fallback.

Attack record: `openwizdev/OpenWiz#4098`
