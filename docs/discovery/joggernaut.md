# Joggernaut skills and the Jog runner

Read on 2026-11-28 for [OpenWiz #3707](https://github.com/openwizdev/OpenWiz/issues/3707). The [research spec](https://github.com/openwizdev/OpenWiz/issues/3703) admits only permissively licensed code for adoption. The [CI spec](https://github.com/openwizdev/OpenWiz/issues/3524) already chose Jog for private repositories and planned an opt-in market entry. That decision stands.

## Joggernaut skills

The public repository is [`usejog/joggernaut`](https://github.com/usejog/joggernaut). This note reads commit [`f829f71a8ee7c567f452184d2dabc84e9a138d2b`](https://github.com/usejog/joggernaut/commit/f829f71a8ee7c567f452184d2dabc84e9a138d2b). The licence text is SPDX `MIT` and requires its copyright and permission notice to accompany copies or substantial portions. The public release history and the Nov 28 commit show recent maintenance. An ongoing support commitment is unverified. [Pinned licence](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/LICENSE) · [Releases](https://github.com/usejog/joggernaut/releases)

### Fit for a builder or fixer

| When | What to take |
| --- | --- |
| A red check passes on rerun or changes with order or load | Use `ci-flaky-tests` to reproduce the intermittent failure and fix its cause. Preserve the test and its assertions, and keep retry, sleep, and skip changes out of the fix. For a reproducible red check, the builder's existing failed-log and local-reproduction path remains the first step. [Flaky-test skill](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/skills/ci-flaky-tests/SKILL.md) · [Build-ticket CI recovery](https://github.com/openwizdev/WizSkills/blob/cf2abfe13020661b47c47adb71afa993caaf16bf/skills/build-ticket/references/review.md) |
| PRs wait on CI and the cause is unclear | Use the read-only `ci-diagnose` method to separate queue time, setup, and execution and rank the causes by time lost. The upstream skill deliberately excludes debugging a deterministic red build. [Diagnosis skill](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/skills/ci-diagnose/SKILL.md) |
| A known part of CI dominates the wait | Use `ci-slow-tests` for per-test or per-shard timings, `ci-cache` for missing or ineffective caches, and `ci-workflow` for repeated setup or serial dependencies. Keep these as references for scoped fixes. [Slow tests](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/skills/ci-slow-tests/SKILL.md) · [Cache](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/skills/ci-cache/SKILL.md) · [Workflow](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/skills/ci-workflow/SKILL.md) |
| A fixer needs to prove a speed change | Use `ci-measure` to compare at least five comparable runs per side and check that the same tests ran by name. With insufficient comparable runs, report provisional evidence. The upstream `ci-guard` idea of moving cheap checks before a push is useful background. Hook installation and CI round caps are outside the proposed adaptation. [Measurement](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/skills/ci-measure/SKILL.md) · [Guard](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/skills/ci-guard/SKILL.md) |

### WizSkills and WizMarket

The upstream skills have a `SKILL.md` per folder. Their `license`, `compatibility`, and nested `metadata` fields fall outside WizSkills' one-line `name`, `description`, and `version` rules. Adapt the material into a standalone WizSkills package with agent metadata and the MIT notice. Keep the runner-independent advice and fixture-based measurement. The upstream live path uses an authenticated `gh`. The proposed first version should read saved or synthetic evidence. [Upstream skill form](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/skills/ci-diagnose/SKILL.md) · [WizSkills form](https://github.com/openwizdev/WizSkills/blob/cf2abfe13020661b47c47adb71afa993caaf16bf/skills/README.md) · [Pinned licence](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/LICENSE)

Upstream evaluations use synthetic planted cases. Their documented limits include static workflow checks and output-text checks, and the public results table has no rows at this pin. OpenWiz improvement and passage of its skills gate are unverified. The follow-up needs its own cases and the [base/head non-regression and ship gate](https://github.com/openwizdev/OpenWiz/issues/3443). A skipped result supplies no pass. [Upstream eval design](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/evals/README.md) · [Results at the pin](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/RESULTS.md)

List the adapted skill as an opt-in WizMarket `skill` through WizSkills. Use the actual gate result for the card's status, including `experimental` and its result line when the eval or gate has not passed. [Market categories, status and install rules](https://github.com/openwizdev/OpenWiz/issues/3384) · [Skills quality gate](https://github.com/openwizdev/OpenWiz/issues/3443)

> **Joggernaut CI triage.** Reproduce flaky checks, diagnose slow GitHub Actions runs, and compare similar runs while checking that the same tests ran. The skill reads saved CI evidence and leaves each workflow change to a separate decision.

### Proposed follow-up ticket

#### Title

Add opt-in Joggernaut CI triage for red-CI fixers

#### Parent

[Skills quality gate, OpenWiz #3443](https://github.com/openwizdev/OpenWiz/issues/3443). The listing handoff belongs to [WizMarket, OpenWiz #3384](https://github.com/openwizdev/OpenWiz/issues/3384).

#### What to build

In WizSkills, add a standalone `ci-triage` skill adapted from the pinned MIT material above. The builder's CI recovery guide can offer it when an owner opts in, after the exact failing run is identified. Offer an intermittent-failure reproduction path and a slow-CI diagnosis and measurement path. Read saved run and test evidence. If a required run or test list is missing, name the gap and leave the conclusion unverified. Preserve existing checks, permissions, and ticket scope. Leave changes to runner routing, workflows, hooks, and branch protection to their owning tickets. Hand the listing copy and gate result to the WizMarket maintainer for its own listing ticket.

#### Proposed owned paths

- `skills/ci-triage/` and `evals/cases/ci-triage/` in WizSkills.
- The new skill's rows in the WizSkills skill inventory and plugin manifest, and the opt-in reference in `skills/build-ticket/references/review.md`, subject to the follow-up plan's approval.

#### Acceptance criteria

- The new skill passes the WizSkills structural checks and carries the pinned attribution and MIT notice.
- Fixture cases distinguish repeatable failure, intermittence, and queue or execution time. They verify that the skill leaves workflows and checks intact.
- A faster candidate with a missing test or incomparable runs cannot receive a verified improvement verdict. A fixture run needs no key or network.
- The base/head gate uses the same settings and reports the actual result. The default skill set and market status follow #3443, including the rule for skipped runs.
- The skill appears only as an explicit choice in the red-CI guide. A skipped or declined choice leaves the ordinary fixer path available.

#### Proof

Run the WizSkills structural checks, the new skill's offline fixtures, and the gate on a planted missing-test regression. Record the gate result for the market handoff.

**Verdict** — adopt. Adapt the pinned MIT methods for opt-in diagnosis and verification in the WizSkills red-CI handoff. The package-form mismatch and missing OpenWiz evidence make the structural checks and skills gate part of the follow-up. [Pinned licence](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/LICENSE) · [Skills quality gate](https://github.com/openwizdev/OpenWiz/issues/3443)

## Jog runner

Jog documents a hosted Ubuntu 24.04 runner for GitHub Actions on private repositories. It describes one Jog runner label per job, a repository-scoped GitHub App selection, prepaid compute billed by run time, and exclusions for public repositories, macOS, Windows, ARM, and GPU jobs. Its sizing advice applies after jobs run on Jog. Product speed or savings on OpenWiz and eligibility for a public-repository fallback are unverified here. The public-repository exclusion should be visible in any listing. [Setup](https://usejog.com/docs/) · [Runners and limits](https://usejog.com/docs/runners/) · [Pricing](https://usejog.com/docs/pricing/) · [Runner sizing advice](https://usejog.com/docs/agents/)

The [vendor's public repositories](https://github.com/orgs/usejog/repositories) and its [runner documentation](https://usejog.com/docs/runners/) identify no public runner repository. A runner commit, a pinned licence file, and a code licence SPDX identifier are therefore unverified. The vendor publishes an image and tool inventory and service terms that reserve rights in Jog. A public runner release history, maintenance cadence, and support commitment are unverified. Joggernaut's MIT licence applies to its own repository. [Terms and privacy](https://usejog.com/legal/) · [Joggernaut licence](https://github.com/usejog/joggernaut/blob/f829f71a8ee7c567f452184d2dabc84e9a138d2b/LICENSE)

For the opt-in `ci` listing already planned by #3524, keep the card link-only and show setup and current pricing. [CI listing plan](https://github.com/openwizdev/OpenWiz/issues/3524) · [Market link-only rule](https://github.com/openwizdev/OpenWiz/issues/3384)

> **Jog.** Hosted Linux runners for eligible private GitHub Actions repositories. An owner selects repositories in Jog's GitHub App and loads prepaid credits, then chooses one Jog label in the job's `runs-on`. New organisations may have to wait for access. [Setup](https://usejog.com/docs/) · [Pricing](https://usejog.com/docs/pricing/)

**Verdict** — no. RX4 proposes no new Jog listing because it could not identify a public runner repository to pin under the research rule. The separately planned link-only CI listing and the existing private-repository decision remain with #3524. [Research rule](https://github.com/openwizdev/OpenWiz/issues/3703) · [CI listing plan](https://github.com/openwizdev/OpenWiz/issues/3524)
