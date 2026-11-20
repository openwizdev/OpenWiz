# Backfill of B1 reason lines (#1640)

KN14's records kit (#1572, PR #1609) found 20 native blockers on 14 open tickets with no `## Links` reason line, which breaks records v1's rule B1 (`kernel/records.v1.md`). This record lists the one reason line added for each, in the [plan links contract](https://github.com/openwizdev/WizSkills/blob/a2993f47b8fd3d7853ee45e6c21feea708c70c02/contracts/plan-links.v1.md)'s form. Each line is worded from what its ticket and its blocker say.

## How each body was edited

1. The body was read through GraphQL, and its SHA-256 computed over its UTF-8 bytes.
2. The new body is the old one with only lines inserted: no line removed or changed. Before the write, the kit's own Links reader (`links()` in `kernel/records-kit/check.py` at PR #1609's head `1cef463`) found no B1 break in it. Every real line also has at least three words outside backticks, as the contract asks.
3. The body was written once, with GraphQL's `updateIssue`. Writes were at least 61 seconds apart, and each had one attempt.
4. The body was read back, and its SHA-256 matched the intended body's in every case.

The four EB tickets (#118, #435, #436, #440) already had a `## Links` section. The new line goes after its last link line. The ten wayfind tickets (#691 to #845) had no `## Links` section, so the backfill appends one at the end of the body: a blank line, `## Links`, a blank line, then the lines.

## Edits

| Ticket | Blocker | Line added | SHA-256 before | SHA-256 after | Written (UTC) |
| --- | --- | --- | --- | --- | --- |
| #118 | #117 | `- #117 real: EB3's precheck contract, builder self-check and CF4 hand-back gate that the promoted checks use` | `f5ac07a166245dc0298ab706fe1c4be28d929c24afa7ba2f5ec3489b27581425` | `8c281e2d457f1595b6e0474cf2bd7bcdcc25997c0a4e8a74fbec8a1ef9855d35` | 2026-11-20T01:09:14Z |
| #435 | #109 | `- #109 real: CF4-E2's research-derived candidate skill revisions and repeated passing CF4 evidence that the replay compares with the pinned old skill` | `d0915397dee63b9e3c2ded4f33072e5eae251ea611f5adbad9551cd707ae2f5c` | `b3624a7f78258222cfd67883acec50ac5b993020906a96c53362235dcd95e4c1` | 2026-11-20T01:10:15Z |
| #436 | #117 | `- #117 real: EB3's builder self-check and CF4 hand-back gate, preserved in both live skill sets` | `ed236f62fec9ca3e29f9d88ca1f9249edb64c9f5a3e02b1b0e90ef168a372152` | `df93ae7070e79d99c2902d70c390b408e2d4ff81b2e05e46f0c3516a05332aba` | 2026-11-20T01:11:17Z |
| #436 | #435 | `- #435 real: EB7's completed paired replay and the frozen review candidate it selects, with compatible CF4 evidence` | `ed236f62fec9ca3e29f9d88ca1f9249edb64c9f5a3e02b1b0e90ef168a372152` | `df93ae7070e79d99c2902d70c390b408e2d4ff81b2e05e46f0c3516a05332aba` | 2026-11-20T01:11:17Z |
| #440 | #436 | `- #436 real: EB8's reviewed preregistration, power calculation, pre-work assignment and fixed-horizon analysis that the huntr A/B reuses` | `cab5c9a1dd3dc2f8da8efeac7defcc898abee8f01602069599b5f1bbb9d2deed` | `f68d072c22d2a4770428abc70ac91fa9cd34d45634a8b4bbb60090311349f2b2` | 2026-11-20T01:12:18Z |
| #691 | #687 | `- #687 real: the test rule that decides what each group of tests protects and what to keep or cut` | `9d47c18f9f70147ae5ec5bcd02e56045f9d3f8ede781edc01e32d517c453c961` | `78a5aa06dde672363a943c4083763caf18cb856c5b52a54ba6511f13e6085aa9` | 2026-11-20T01:13:19Z |
| #691 | #690 | `- #690 real: the starting audits' findings that the walkthrough shows for each group` | `9d47c18f9f70147ae5ec5bcd02e56045f9d3f8ede781edc01e32d517c453c961` | `78a5aa06dde672363a943c4083763caf18cb856c5b52a54ba6511f13e6085aa9` | 2026-11-20T01:13:19Z |
| #694 | #697 | `- #697 real: where a System One decision model fits, including stuck-agent detection and stall-cause tagging` | `c4daff3d4bd7cb0a77d47b084127d4b734210b48c4cb3b98c9784eb4aea4e632` | `65d6d88b7e35543e31215e241ee3378cdd516c17fdf6c34ca16ffdb2febb54f3` | 2026-11-20T01:14:20Z |
| #694 | #948 | `- #948 real: the first-principles factory model of stages, work time and wait time that the flow lane builds on` | `c4daff3d4bd7cb0a77d47b084127d4b734210b48c4cb3b98c9784eb4aea4e632` | `65d6d88b7e35543e31215e241ee3378cdd516c17fdf6c34ca16ffdb2febb54f3` | 2026-11-20T01:14:20Z |
| #695 | #687 | `- #687 real: the test rule that the trim-tests skill and the checks proving a shorter skill still works follow` | `2e976e07081f71950c57c50ade0b07a7c7d125ecbccc66a3e149cf19cedfdba4` | `36c115ae4a48b77b9e0b8f4aa4ae16aac3e1ff11f7587dc2b480a2edcbc8e1c2` | 2026-11-20T01:15:22Z |
| #696 | #694 | `- #694 real: the definition of stalls and waits that the before benches record` | `bc2ffa6ee5f95edc4018511adfa1e8ef21352257efe573ed035cc2d62df753ed` | `d82b0b895d1dcdaa723be744ddc64f6abb51ef7bcc7e17f5bfb3cf531ae39e96` | 2026-11-20T01:16:24Z |
| #696 | #948 | `- #948 real: the first-principles factory model and top-line numbers that the bench measures break down from` | `bc2ffa6ee5f95edc4018511adfa1e8ef21352257efe573ed035cc2d62df753ed` | `d82b0b895d1dcdaa723be744ddc64f6abb51ef7bcc7e17f5bfb3cf531ae39e96` | 2026-11-20T01:16:24Z |
| #698 | #697 | `- #697 real: the research on where a System One decision model fits, with its pricing, data handling and accuracy measure, that the trial's approval rests on` | `075aac29cbec7170c703f0adf9e684e4da8f05cc5c581e6a848dd23a99b86c2a` | `33b3fac1a2583345184c0b41087f85cc76e3e2f2a4c599b7591df5569b13aa83` | 2026-11-20T01:17:25Z |
| #706 | #696 | `- #696 real: the before benches' measurement definitions that the experiments' before and after criteria coordinate with` | `19a352bdb5539dc784cc93e670d993ffc5cf94fe1ee020b9473a43c88fdd47fa` | `4940fef938442829b7123f1e5641e5ac00803c91f4b78520d1549589fd18ea82` | 2026-11-20T01:18:27Z |
| #836 | #840 | `- #840 real: the plan approval card and its one approval that the fast path keeps for small work` | `db4ea0e0f6fd50b122138a6ea7b182cfbf46260fa9a9ce69998964dfe2306d47` | `4dbea12a650dd4a5d8aab81afd022f0223482a0c5e4d496130edb2f8cce01e1f` | 2026-11-20T01:19:28Z |
| #837 | #833 | `- #833 real: the fences the factory can't loosen, among them the merge rule, that the page names as guarantees linked to their enforcing tests` | `e85ef7bd5d08ab1731384427de0fe8934ddd1c76e11d6fec89141bcdb1a11590` | `7c8a333b62615ebdcfae4378606b8cb23114373299d20331fc8991b8be506791` | 2026-11-20T01:20:29Z |
| #841 | #509 | `` - #509 real: the step-by-step path from the public site to a running factory, and what `openwiz init` sets up, that the one-paste onboarding runs `` | `50b435c3cb5b65b32fb00fe5d6bdbf2ba708d033f5681609dff4202c59186ec3` | `40d80526271c6336e745fc6a12d6b49ff2a74d59f249ded1773af1e8e401e45a` | 2026-11-20T01:21:31Z |
| #841 | #839 | `- #839 real: the marketplace listings of the skills that the pasted prompt installs` | `50b435c3cb5b65b32fb00fe5d6bdbf2ba708d033f5681609dff4202c59186ec3` | `40d80526271c6336e745fc6a12d6b49ff2a74d59f249ded1773af1e8e401e45a` | 2026-11-20T01:21:31Z |
| #845 | #834 | `- #834 real: the proof-carrying handbacks and computed done verdict that release sign-off reads` | `215e5232758539db9ed6c5417cda57f85d90cb7562e7b389d5db97dff4cd5f3e` | `8662ce09f4715e13a794fe1d75cd08cbf534799517f9fab9838042fb5f2df800` | 2026-11-20T01:22:32Z |
| #845 | #838 | `- #838 real: the reproduced, ranked review findings and recorded dismissals that the PR guides carry` | `215e5232758539db9ed6c5417cda57f85d90cb7562e7b389d5db97dff4cd5f3e` | `8662ce09f4715e13a794fe1d75cd08cbf534799517f9fab9838042fb5f2df800` | 2026-11-20T01:22:32Z |

20 lines on 14 tickets. A ticket with two lines got both in one write, so both rows give the same hashes.

## Diffs

The read-back body against the body before, for each ticket.

````diff
--- #118 before
+++ #118 after
@@ -27,6 +27,7 @@
 - #2176 real: the shared experiment stage, revision and outcome formats used without a parallel record system
 - #1385 real: the daily tagged experiment and week-over-week trend reports consumed by the weekly improvement result
 - #1386 real: the precheck input and result contract, builder self-check and CF4 hand-back gate that recurring findings supply with promoted checks
+- #117 real: EB3's precheck contract, builder self-check and CF4 hand-back gate that the promoted checks use
 
 ## Acceptance criteria
 
````

````diff
--- #435 before
+++ #435 after
@@ -25,6 +25,7 @@
 - #2234 real: the isolation, paired-scoring and checkpoint harness the real replay runs on
 - #2176 real: the frozen cohort, historical context, rubric, paired-result and credit-attribution interfaces
 - #1362 real: the sourced research-derived candidate revisions and compatible repeated CF4 passing evidence replay compares with the pinned old skill
+- #109 real: CF4-E2's research-derived candidate skill revisions and repeated passing CF4 evidence that the replay compares with the pinned old skill
 
 ## Acceptance criteria
 
````

````diff
--- #436 before
+++ #436 after
@@ -29,6 +29,8 @@
 - #2177 real: the sourced first-push timing, independent rounds, attributable defects and baseline variability the live analysis consumes
 - #2178 real: the completed paired backtest and selected frozen candidate with compatible CF4 evidence
 - #1386 real: the implemented builder self-check and compatible CF4 hand-back gate preserved in both live skill sets
+- #117 real: EB3's builder self-check and CF4 hand-back gate, preserved in both live skill sets
+- #435 real: EB7's completed paired replay and the frozen review candidate it selects, with compatible CF4 evidence
 
 ## Acceptance criteria
 
````

````diff
--- #440 before
+++ #440 after
@@ -22,6 +22,7 @@
 ## Links
 
 - #2179 real: the preregistered, power-based A/B method
+- #436 real: EB8's reviewed preregistration, power calculation, pre-work assignment and fixed-horizon analysis that the huntr A/B reuses
 
 ## Acceptance criteria
 
````

````diff
--- #691 before
+++ #691 after
@@ -1,3 +1,8 @@
 ## Question
 
 Walk the shared tests/ folder (about 143,600 lines across 327 files) with a picture: what each group protects, what the audits flag, and what to keep, cut, merge or simplify.
+
+## Links
+
+- #687 real: the test rule that decides what each group of tests protects and what to keep or cut
+- #690 real: the starting audits' findings that the walkthrough shows for each group
````

````diff
--- #694 before
+++ #694 after
@@ -1,3 +1,8 @@
 ## Question
 
 Define stalls and waits (unanswered questions, builders waiting on background jobs, limits, refusals, pauses) and how the war room charts them, so the flow lane has a before bench.
+
+## Links
+
+- #697 real: where a System One decision model fits, including stuck-agent detection and stall-cause tagging
+- #948 real: the first-principles factory model of stages, work time and wait time that the flow lane builds on
````

````diff
--- #695 before
+++ #695 after
@@ -1,3 +1,7 @@
 ## Question
 
 Plan the skills lane: rebuilding each skill on Matt Pocock's text where it applies (decided 2026-11-14), the deslop, trim-tests and tune-ci skills distilled from the audits, and the checks that prove a shorter skill still works. Starts after WizSkills v0.1.0 publishes.
+
+## Links
+
+- #687 real: the test rule that the trim-tests skill and the checks proving a shorter skill still works follow
````

````diff
--- #696 before
+++ #696 after
@@ -1,3 +1,8 @@
 ## Question
 
 Record each lane's before bench in the war room: credits per day, tokens per merged PR, CI minutes and wall-clock per PR, lines of code and test share, stalls, and the maintainer's minutes.
+
+## Links
+
+- #694 real: the definition of stalls and waits that the before benches record
+- #948 real: the first-principles factory model and top-line numbers that the bench measures break down from
````

````diff
--- #698 before
+++ #698 after
@@ -1,3 +1,7 @@
 ## Question
 
 A cheap, throwaway trial: over one day of real factory records, ask a System One decision model whether each agent was stuck and why, and compare with what actually happened. Runs only after the maintainer approves the vendor, key and spend, based on the research.
+
+## Links
+
+- #697 real: the research on where a System One decision model fits, with its pricing, data handling and accuracy measure, that the trial's approval rests on
````

````diff
--- #706 before
+++ #706 after
@@ -3,3 +3,7 @@
 Which credit and model-token savings hypotheses should receive the first bounded experiments, and what preserved behavior, review quality, throughput and measured before/after criteria would justify keeping each change?
 
 Use the findings from [Where do Cloudroom credits go?](https://github.com/openwizdev/openwiz/issues/688) and [Where do model tokens go, and why do limits hit?](https://github.com/openwizdev/openwiz/issues/689). Distinguish observed exposure from avoidable work, and gross token replay from quota usage or compute charges. Coordinate the measurement definitions with [Before benches for every lane](https://github.com/openwizdev/openwiz/issues/696); CI policy, component walkthroughs and System One adoption remain with their existing questions.
+
+## Links
+
+- #696 real: the before benches' measurement definitions that the experiments' before and after criteria coordinate with
````

````diff
--- #836 before
+++ #836 after
@@ -7,3 +7,7 @@
 Part and size: Graph · S. Sources: [BMAD](https://github.com/bmad-code-org/BMAD-METHOD/blob/e435a22574fe55722841086e5566420178b98df3/), [superpowers](https://github.com/obra/superpowers/blob/22f0b463e7a5e579904dd6211a520321035526f7/), [Claude Code](https://code.claude.com/docs/en/), [Spec Kit](https://github.com/github/spec-kit/blob/2ee2b1e8005905db05f5717300a469b3068b908f/).
 
 Approved for this map: private record [ClosedWiz #325](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6902655836).
+
+## Links
+
+- #840 real: the plan approval card and its one approval that the fast path keeps for small work
````

````diff
--- #837 before
+++ #837 after
@@ -7,3 +7,7 @@
 Part and size: Eyes (site) · S. Sources: [Anthropic's code-modernization plugin](https://github.com/anthropics/claude-plugins-official/blob/b5b01ac4f889fec0c4c6bb89f27ca7c8574473f6/plugins/code-modernization/README.md), [Capy pull requests](https://docs.capy.ai/pull-requests), [Jules](https://jules.google/docs/changelog/).
 
 Approved for this map: private record [ClosedWiz #325](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6902655836).
+
+## Links
+
+- #833 real: the fences the factory can't loosen, among them the merge rule, that the page names as guarantees linked to their enforcing tests
````

````diff
--- #841 before
+++ #841 after
@@ -9,3 +9,8 @@
 Part and size: Hands + Graph · M. Sources: [Fabro](https://github.com/fabro-sh/fabro), [Conductor](https://www.conductor.build/docs), [Factory Agent Readiness](https://docs.factory.com/agent-readiness/overview.md), [addyosmani/factory](https://github.com/addyosmani/factory), [Matt Pocock's skills](https://github.com/mattpocock/skills/blob/5863806dd4e15c63174bee4e7515a4256792ecfa/), [Gas City](https://github.com/gastownhall/gascity).
 
 Approved for this map: private record [ClosedWiz #325](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6902655836).
+
+## Links
+
+- #509 real: the step-by-step path from the public site to a running factory, and what `openwiz init` sets up, that the one-paste onboarding runs
+- #839 real: the marketplace listings of the skills that the pasted prompt installs
````

````diff
--- #845 before
+++ #845 after
@@ -7,3 +7,8 @@
 Part and size: Graph + Eyes · M. Sources: [Capy review](https://docs.capy.ai/review), [Devin Review](https://docs.devin.ai/work-with-devin/devin-review.md), [Factory Missions](https://docs.factory.com/missions/overview.md), [BMAD](https://github.com/bmad-code-org/BMAD-METHOD/blob/e435a22574fe55722841086e5566420178b98df3/), [Matt Pocock's skills](https://github.com/mattpocock/skills/blob/5863806dd4e15c63174bee4e7515a4256792ecfa/), [gstack](https://github.com/garrytan/gstack/blob/main/crew/docs/captain.md).
 
 Approved for this map: private record [ClosedWiz #325](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6902655836).
+
+## Links
+
+- #834 real: the proof-carrying handbacks and computed done verdict that release sign-off reads
+- #838 real: the reproduced, ranked review findings and recorded dismissals that the PR guides carry
````

## The kit's runs

`python3 -I kernel/records-kit/check.py --repo openwizdev/OpenWiz` at PR #1609's head `1cef46366140f893183d6eb25ecca5df3b7c5cc6`, one run before the edits and one after, both exit 1 because of breaks on other rules. Only the 14 tickets' lines are kept here.

Before: 20 B1 breaks, exactly the list in #1640.

```text
#118 B1: #117 has no reason line
#435 B1: #109 has no reason line
#436 B1: #117 has no reason line
#436 B1: #435 has no reason line
#440 B1: #436 has no reason line
#691 L3: its spec #685 lacks spec
#691 T1: ticket lacks ## Parent
#691 T1: ticket lacks ## What to build
#691 T1: ticket lacks ## Owned paths
#691 T1: ticket lacks ## Links
#691 T1: ticket lacks ## Acceptance criteria
#691 T1: ticket lacks ## Proof
#691 T1: ticket lacks **Relies on:**
#691 B1: #687 has no reason line
#691 B1: #690 has no reason line
#694 L3: its spec #685 lacks spec
#694 T1: ticket lacks ## Parent
#694 T1: ticket lacks ## What to build
#694 T1: ticket lacks ## Owned paths
#694 T1: ticket lacks ## Links
#694 T1: ticket lacks ## Acceptance criteria
#694 T1: ticket lacks ## Proof
#694 T1: ticket lacks **Relies on:**
#694 B1: #697 has no reason line
#694 B1: #948 has no reason line
#695 L3: its spec #685 lacks spec
#695 T1: ticket lacks ## Parent
#695 T1: ticket lacks ## What to build
#695 T1: ticket lacks ## Owned paths
#695 T1: ticket lacks ## Links
#695 T1: ticket lacks ## Acceptance criteria
#695 T1: ticket lacks ## Proof
#695 T1: ticket lacks **Relies on:**
#695 B1: #687 has no reason line
#696 L3: its spec #685 lacks spec
#696 T1: ticket lacks ## Parent
#696 T1: ticket lacks ## What to build
#696 T1: ticket lacks ## Owned paths
#696 T1: ticket lacks ## Links
#696 T1: ticket lacks ## Acceptance criteria
#696 T1: ticket lacks ## Proof
#696 T1: ticket lacks **Relies on:**
#696 B1: #694 has no reason line
#696 B1: #948 has no reason line
#698 L3: its spec #685 lacks spec
#698 T1: ticket lacks ## Parent
#698 T1: ticket lacks ## What to build
#698 T1: ticket lacks ## Owned paths
#698 T1: ticket lacks ## Links
#698 T1: ticket lacks ## Acceptance criteria
#698 T1: ticket lacks ## Proof
#698 T1: ticket lacks **Relies on:**
#698 B1: #697 has no reason line
#706 L3: its spec #685 lacks spec
#706 T1: ticket lacks ## Parent
#706 T1: ticket lacks ## What to build
#706 T1: ticket lacks ## Owned paths
#706 T1: ticket lacks ## Links
#706 T1: ticket lacks ## Acceptance criteria
#706 T1: ticket lacks ## Proof
#706 T1: ticket lacks **Relies on:**
#706 B1: #696 has no reason line
#836 L3: its spec #508 lacks spec
#836 T1: ticket lacks ## Parent
#836 T1: ticket lacks ## What to build
#836 T1: ticket lacks ## Owned paths
#836 T1: ticket lacks ## Links
#836 T1: ticket lacks ## Acceptance criteria
#836 T1: ticket lacks ## Proof
#836 T1: ticket lacks **Relies on:**
#836 B1: #840 has no reason line
#837 L3: its spec #508 lacks spec
#837 T1: ticket lacks ## Parent
#837 T1: ticket lacks ## What to build
#837 T1: ticket lacks ## Owned paths
#837 T1: ticket lacks ## Links
#837 T1: ticket lacks ## Acceptance criteria
#837 T1: ticket lacks ## Proof
#837 T1: ticket lacks **Relies on:**
#837 B1: #833 has no reason line
#841 L3: its spec #508 lacks spec
#841 T1: ticket lacks ## Parent
#841 T1: ticket lacks ## What to build
#841 T1: ticket lacks ## Owned paths
#841 T1: ticket lacks ## Links
#841 T1: ticket lacks ## Acceptance criteria
#841 T1: ticket lacks ## Proof
#841 T1: ticket lacks **Relies on:**
#841 B1: #509 has no reason line
#841 B1: #839 has no reason line
#845 L3: its spec #508 lacks spec
#845 T1: ticket lacks ## Parent
#845 T1: ticket lacks ## What to build
#845 T1: ticket lacks ## Owned paths
#845 T1: ticket lacks ## Links
#845 T1: ticket lacks ## Acceptance criteria
#845 T1: ticket lacks ## Proof
#845 T1: ticket lacks **Relies on:**
#845 B1: #834 has no reason line
#845 B1: #838 has no reason line
```

After: no B1 break. The ten wayfind tickets also lose their `T1: ticket lacks ## Links` line. All their other T1 lines stay, because these are wayfind questions, not plan-graph tickets.

```text
#691 L3: its spec #685 lacks spec
#691 T1: ticket lacks ## Parent
#691 T1: ticket lacks ## What to build
#691 T1: ticket lacks ## Owned paths
#691 T1: ticket lacks ## Acceptance criteria
#691 T1: ticket lacks ## Proof
#691 T1: ticket lacks **Relies on:**
#694 L3: its spec #685 lacks spec
#694 T1: ticket lacks ## Parent
#694 T1: ticket lacks ## What to build
#694 T1: ticket lacks ## Owned paths
#694 T1: ticket lacks ## Acceptance criteria
#694 T1: ticket lacks ## Proof
#694 T1: ticket lacks **Relies on:**
#695 L3: its spec #685 lacks spec
#695 T1: ticket lacks ## Parent
#695 T1: ticket lacks ## What to build
#695 T1: ticket lacks ## Owned paths
#695 T1: ticket lacks ## Acceptance criteria
#695 T1: ticket lacks ## Proof
#695 T1: ticket lacks **Relies on:**
#696 L3: its spec #685 lacks spec
#696 T1: ticket lacks ## Parent
#696 T1: ticket lacks ## What to build
#696 T1: ticket lacks ## Owned paths
#696 T1: ticket lacks ## Acceptance criteria
#696 T1: ticket lacks ## Proof
#696 T1: ticket lacks **Relies on:**
#698 L3: its spec #685 lacks spec
#698 T1: ticket lacks ## Parent
#698 T1: ticket lacks ## What to build
#698 T1: ticket lacks ## Owned paths
#698 T1: ticket lacks ## Acceptance criteria
#698 T1: ticket lacks ## Proof
#698 T1: ticket lacks **Relies on:**
#706 L3: its spec #685 lacks spec
#706 T1: ticket lacks ## Parent
#706 T1: ticket lacks ## What to build
#706 T1: ticket lacks ## Owned paths
#706 T1: ticket lacks ## Acceptance criteria
#706 T1: ticket lacks ## Proof
#706 T1: ticket lacks **Relies on:**
#836 L3: its spec #508 lacks spec
#836 T1: ticket lacks ## Parent
#836 T1: ticket lacks ## What to build
#836 T1: ticket lacks ## Owned paths
#836 T1: ticket lacks ## Acceptance criteria
#836 T1: ticket lacks ## Proof
#836 T1: ticket lacks **Relies on:**
#837 L3: its spec #508 lacks spec
#837 T1: ticket lacks ## Parent
#837 T1: ticket lacks ## What to build
#837 T1: ticket lacks ## Owned paths
#837 T1: ticket lacks ## Acceptance criteria
#837 T1: ticket lacks ## Proof
#837 T1: ticket lacks **Relies on:**
#841 L3: its spec #508 lacks spec
#841 T1: ticket lacks ## Parent
#841 T1: ticket lacks ## What to build
#841 T1: ticket lacks ## Owned paths
#841 T1: ticket lacks ## Acceptance criteria
#841 T1: ticket lacks ## Proof
#841 T1: ticket lacks **Relies on:**
#845 L3: its spec #508 lacks spec
#845 T1: ticket lacks ## Parent
#845 T1: ticket lacks ## What to build
#845 T1: ticket lacks ## Owned paths
#845 T1: ticket lacks ## Acceptance criteria
#845 T1: ticket lacks ## Proof
#845 T1: ticket lacks **Relies on:**
```

## Not changed

- The EB tickets' existing `## Links` lines still name the ClosedWiz numbers they were written with (for example #118's `#1386` line, which is EB3, now #117 here). Records v1's kit doesn't check `not_a_blocker`, and #1640 adds only the missing lines, so they stay as they were.
- No other byte of any body, and no label, blocker or comment, changed.
