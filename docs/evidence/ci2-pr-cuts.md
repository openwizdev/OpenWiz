# CI2 small pull-request cuts

Evidence classes: offline fixture proof and the authorized R1 Actions observation
below. Actual-push latency, whole-bill cost and the CS1 speed target remain
**Unverified**.
No CI1 selection/build-reuse gain is counted again.

## Cut 1: share the site and release checkout on selected PRs

The ordinary selected PR plan keeps every site/release test. Its site work
executes first inside the release job, using that job's existing setup and
reader union. Separate `site` and `release` receipts still bind the exact plan,
head, run and attempt. Full plans keep the independent jobs, including main,
nightly, reruns, release branches, ready-for-review and every uncertain input.
Runner expressions, required check names and the selection contract stay intact.

### Proof plan, before implementation

| Claim | Owning proof / plausible break |
| --- | --- |
| One fewer executing job only for eligible selected PRs | `test_plan.py` selected site cut and `test_workflow.py` actual site/release job conditions; full-plan tests previously had no combined selected route |
| Every selected command runs once, failure stops the job | `test_execution.py` selected release case, recorded suite subprocesses; a combined executor could omit site work or swallow its failure |
| Each logical lane still has its own exact receipt | `test_lanes.py` selected combined stamp/final cases; a successful release job alone could conceal missing site work |
| Missing work, failure, cancellation, stale digest or foreign head/attempt refuses green | Selected final-result negative table, plus existing full/matrix negative cases |
| Always-run checks and all full fallbacks remain | Existing plan/execution/workflow cases, unchanged always inventory and event reasons; diff audit |
| Comparable cut counts/timing/cost remain honest | C4 offline analyzer over frozen synthetic inputs; live capture requires separate authority and cannot be inferred from fixture timing |

### Red record

All commands below ran before implementation, against the fresh-main source.
Only suite subprocesses were replaced by recording programs; no Cargo/npm suite
or live API was run.

| Command suffix (after `python3 -I .github/actions/docs-only/`) | Exit / intended failure |
| --- | --- |
| `test_plan.py Plans.test_selected_site_release_cut_keeps_every_planned_test` | 1: combined route absent (`AttributeError`) |
| `test_execution.py Execution.test_selected_release_executes_site_work_once_and_stops_on_either_failure` | 1: five subcases; executor ran only the release command, omitting all three site commands |
| `test_lanes.py Lanes.test_selected_site_and_release_need_both_receipts_in_one_job Lanes.test_selected_release_stamp_keeps_separate_site_and_release_receipts` | 1: two failures; `site: expected success, got 'skipped'`; only `release.json` stamped |
| `test_workflow.py Workflow.test_selected_site_cut_uses_one_job_but_full_runs_keep_both` | 1: standalone site job still ran; combined-route output absent |

Complete raw outputs stay private. This red record and the tests are committed
before the implementation.

### Measurements and remaining gates

The actual workflow job conditions, evaluated on the signed-map site-only
fixture, select the following work. This is an offline topology census, not a
claim about an observed GitHub run. The before source is the fresh-main base;
the red workflow proof demonstrates that it still selected both jobs.

| Item | Before | After |
| --- | --- | --- |
| Executing CI jobs | `changes`, `always`, `site`, `release`, `ci`, `web-test` (6) | Same except standalone `site` (5) |
| Other ordinary site-PR workflows | Privacy + Changelog (2) | Privacy + Changelog (2) |
| Executing total | 8 | 7 |
| Site commands | build, test, test:ci once each | Same, before release proofs in their checkout |
| Release commands/tests | Every selected release test | Same, no registration removed |
| Site/release receipt count | 2 | 2 |
| Duplicate site checkout/setup | 1 | 0 |
| Selected Rust/web tests or skill matrix members in this fixture | 0 | 0 |

The raw job-record count must also disclose skipped rows. Feeding the frozen
synthetic C4 input below to `tools/ci-bench/required.py` reports 8 records before
and 8 after, but 8 versus 7 allocated jobs. Each cohort has one synthetic sample
and three workflow attempts; both outcomes are unfinished because push/result
clocks are deliberately unknown. Queue denominators are zero, runner maps are
empty, whole-bill cost is null, and both timing reductions are null. Its input
SHA-256 is `0251b20530cb29956a0cccb82bd49767bfe7f5947c2969491590855bcc22dc76`.
Dummy allocation clocks exercise the counter only; they are not measured times.
Extract the JSON fence below without changing its terminal newline and invoke
`python3 -I tools/ci-bench/required.py <extracted-json>` to reproduce that report.

The offline executing-job example reaches seven. It does **not** establish a
5–7 raw-job/live-result target: counting the skipped site row still gives eight,
and actual API job enumeration/timing remains a separately authorized read.
This PR changes CI itself, forcing the existing full fallback and benchmark
proof; its own CI is not the representative selected-site cohort. Broader PRs
can still need extra builds, Rust shards, skills and other required workflows.
No broader reduction is inferred. Site work loses independent parallelism and
shares the release job's existing timeout; wall-clock improvement is unproved.

Affected checks: `test_plan.py` (16), `test_execution.py` (13), `test_lanes.py`
(8), `test_workflow.py` (16), `test_gate.py` (5) and `test_release_prune.py` (1)
passed. Updated output-writer/topology cases passed again after their proof was
strengthened. The four changed suites are already invoked by the existing
`.github/actions/docs-only/test.sh --always` registration. No new suite or
registration row is introduced. No Rust file changed; Rust fmt/clippy are not
affected checks (the optional `cargo fmt --check` attempt found no Cargo).
The original checkpoint collected no live cohort. The R1 collection below adds
observed jobs, queue/result clocks and partial runner/billing context; comparable
selected-site actual-push evidence and any causal speed gain remain unknown.
The target of 5–7 total jobs includes Privacy and Changelog and the legacy
`web-test` bridge; CI-only counts must not be presented as the total.

This is infrastructure work; no product changelog line is needed. Independent
exact-head review, required CI, M1, privacy/audit/no-push and correction gates
remain. C13 (#2320) consumes the cut evidence after its separately authorized
observations. No live kit, new selection schema, controller, dependency or
spending permission is introduced here.

### R1: authorized Actions collection, 2026-11-11

Evidence class: read-only GitHub Actions observation, separate from the synthetic
proof above. [The orchestrator's collection ruling](https://github.com/jparker2006/ClosedWiz/issues/2312#issuecomment-6789222810)
authorizes this capture and reporting the measured gap; it does not waive AC1,
change acceptance or discharge C13. No workflow, runner, account or billing
setting changed. Collection triggered no empty commit, workflow dispatch or
rerun; documentation delivery leaves configured CI to run normally.

**Enrollment and limits.** Freeze the ordinary `pull_request` run inventory
created in `[2026-11-11T00:00:00Z, 2026-11-11T06:54:00Z)`, before selecting by
outcome or runner. The Actions list has 113 records across two pages (100 + 13),
including 22 non-C5 CI runs. Read each one's attempt-specific selection artifact,
then count additions + deletions against its recorded base/head merge base.
The sole small control (<200 changed lines) is #2271 at `af5a76d0`: 24 changed
lines in two skill files. All other non-C5 candidates exceed 199 lines; failed
and cancelled candidates were retained in that scan. This is one small PR,
not a representative population or a census of pushes that produced no run.

The before-policy control uses main's plan at base `d8ed3eb4`. The after-policy
sample is #2371's reviewed head `20a5527a`, base `eac858a5`, using its existing
runs. "Before" and "after" identify policies, not nonoverlapping time windows:
the control ran later than this PR. An empty commit on #2371 would retain its
CI-changing full fallback and would not supply a selected-site workload.

For each immutable head, GET every Actions run (all events, no success filter),
every attempt from 1 through `run_attempt`, and all job pages. Both head lists
fit one page; every attempt's jobs fit one page and agree with `total_count`.
Read each run again after its jobs and each head's run list again after capture;
head/attempt/status/conclusion and membership were stable. All ten captured
attempts are attempt 1, completed and successful; no listed failed, cancelled,
active or missing attempt was omitted. Later pushes on the control branch are
outside its frozen head, not replacement samples. The scope cannot enumerate
pushes with no Actions record or authenticate independent push membership.

**Provenance.** GET paths are relative to `repos/jparker2006/ClosedWiz/`:
`actions/runs?event=pull_request&created=...&per_page=100&page=N`,
`actions/runs?head_sha=...&per_page=100&page=N`, `actions/runs/ID`,
`actions/runs/ID/attempts/K`, `actions/runs/ID/attempts/K/jobs`,
`actions/runs/ID/artifacts`, and `actions/artifacts/ID/zip`.
Control and candidate heads are respectively
`af5a76d06ec03ee3bf0efeb816d96ef636355d4d` and
`20a5527a020bbb48dfdf90e8824dc5d0ce6cfe44`.
Raw responses, headers, plans and billing stay private; this record omits
runner names/ids, account data, job ids, logs and unrelated billing rows.

| Frozen head | Freeze (UTC) | Raw capture SHA-256 |
| --- | --- | --- |
| before | 2026-11-11T07:01:08Z | `34060088b9a702b86ad8e8277de3ef0d1514f8239fb3532eaf70213307504ed4` |
| after | 2026-11-11T07:01:12Z | `b9115c79b68b372ff1d836b11fd1b8b956e5c1e4d51db8d0a7d77c3a1497fb81` |

All times below are UTC on 2026-11-11. "End" is last job completion for that
workflow attempt, not run `updated_at`. Records include skipped jobs;
allocated jobs require an actual non-null runner id and start.

| Policy | Run (attempt 1) | Workflow / event | Created | End | Records / allocated |
| --- | --- | --- | --- | --- | --- |
| before | [42968409633](https://github.com/jparker2006/ClosedWiz/actions/runs/42968409633) | CI / pull_request | 05:50:58 | 06:02:49 | 19 / 15 |
| before | [42968409638](https://github.com/jparker2006/ClosedWiz/actions/runs/42968409638) | Privacy / pull_request | 05:50:58 | 05:51:23 | 1 / 1 |
| before | [42968409678](https://github.com/jparker2006/ClosedWiz/actions/runs/42968409678) | Changelog / pull_request | 05:50:58 | 05:51:21 | 1 / 1 |
| before | [42968414087](https://github.com/jparker2006/ClosedWiz/actions/runs/42968414087) | Privacy / push | 05:51:00 | 05:51:39 | 1 / 1 |
| after | [42962170576](https://github.com/jparker2006/ClosedWiz/actions/runs/42962170576) | Privacy / push | 04:53:44 | 04:54:14 | 1 / 1 |
| after | [42962173130](https://github.com/jparker2006/ClosedWiz/actions/runs/42962173130) | CI / pull_request | 04:53:46 | 05:09:05 | 19 / 15 |
| after | [42962173167](https://github.com/jparker2006/ClosedWiz/actions/runs/42962173167) | CI benchmarks / pull_request | 04:53:46 | 04:55:19 | 2 / 1 |
| after | [42962173200](https://github.com/jparker2006/ClosedWiz/actions/runs/42962173200) | Changelog / pull_request | 04:53:46 | 04:54:11 | 1 / 1 |
| after | [42962173243](https://github.com/jparker2006/ClosedWiz/actions/runs/42962173243) | Privacy / pull_request | 04:53:46 | 04:54:15 | 1 / 1 |
| after | [42964804755](https://github.com/jparker2006/ClosedWiz/actions/runs/42964804755) | Changelog / pull_request | 05:17:38 | 05:18:02 | 1 / 1 |

**Work and retained checks.** The selection artifacts are
`ci-selection-1` 13832346690 (control) and 13829971962 (candidate).
Both record `selection.mode=full`; their entire `lanes` and `builds` values
compare equal. Both execute `changes`, `always`, `web-build`, `site`, `release`,
`rust-export (1)`, `web-export`, six skill matrix jobs, `ci` and `web-test`:
15 allocated CI jobs and 19 CI records each. `rust`, `web`, `toolkit-nightly`
and `select-map` are the four skipped CI rows. The candidate's benchmark adds
one successful `proof` and one skipped `publish`; its later Changelog event is
another real job, not silently collapsed into the first event.

Both plans retain `always:fmt`, `always:classifier`, `always:selector`,
`always:checks`, all full Rust/web/site/release work, six skill suites, and
separate site/release receipts. Privacy and Changelog also succeeded. The
control's saved selection diff lists 300 paths and `ci_change`/`unknown_path`
reasons despite the 24-line Git PR diff; it is a conservative full-run control,
not evidence of ordinary selected-site behavior. The candidate records
`ci_change`. No selected-site job reduction was executed by either sample.

| Required receipt | Control completed | Candidate completed |
| --- | --- | --- |
| `ci` | 06:02:41 | 05:05:15 |
| `web-test` | 06:02:49 | 05:09:05 |
| `privacy` (PR) | 05:51:23 | 04:54:15 |
| `privacy` (push) | 05:51:39 | 04:54:14 |
| `changelog` (first / latest) | 05:51:21 / same | 04:54:11 / 05:18:02 |

**Clocks and C4.** Queue is job-created to actual runner start, including
scheduler/dependency effects. Every allocated job has ordered clocks. Skipped
rows carry API placeholder starts, sometimes completion before creation; they
establish neither allocation nor a physical duration and remain in raw counts.
No skipped placeholder enters queue or runner time. The merged C4
`tools/ci-bench/required.py`'s `summary` computes the following ordinary median
and nearest-rank p90 from all allocated-job waits (not success-selected jobs):

| Observation | Before-policy control | After-policy candidate |
| --- | --- | --- |
| All workflow attempts at frozen head | 4 | 6 |
| All job records / allocated | 22 / 18 | 25 / 20 |
| Initial PR event workflows only, records / allocated | 21 / 17 | 23 / 18 |
| Queue seconds: known n, median, p90 | 18, 29.5, 126 | 20, 47, 224 |
| Sum of actual runner seconds, all workflows | 1551 | 1568 |
| Actual push time / push-to-required distribution | Unknown / n=0 | Unknown / n=0 |
| Latest required-result completion at freeze | 06:02:49 | 05:18:02 |
| Actual observed runner pool | Namespace profile, 18 allocations | Same profile, 20 allocations |

The exact sorted waits in seconds are:

- Control: `1,2,9,9,9,9,12,17,18,41,63,63,74,76,93,125,126,133`.
- Candidate: `3,10,10,10,10,10,11,11,11,42,52,77,78,126,126,159,206,224,228,348`.

All allocated jobs have a non-null actual runner assignment with observed label
`namespace-profile-closedwiz-rust`. This establishes the pool used, not its
hardware size, price or whether trial allowance remained. Configured `runs-on`
labels alone were not counted as observed allocation.

Actions metadata exposes no independent push receipt or stable push-event
identity. Neither commit time, run creation, check-suite id nor a run/head id
is substituted for it. An honest normalized Actions-only C4 input leaves
`push_event_id` and `push` null. Running
`python3 -I tools/ci-bench/required.py <private-actions-only-input>` exits 1 with
`required: nonempty ASCII text required` at the missing push identity.
Its input SHA-256 is
`972726a595a5c286f1b58851a2db46b95195df0df7f74be2d3e7710c783ef974`.
This is an acquisition limit, not a C4 bug: no validated observational C4
comparison/report or timing reduction is claimed. Even with identity supplied,
the different workloads cannot establish the selected-site cut. Absolute
required-result and job-queue clocks above are observations, not actual-push
latencies or proof of CS1.

**Readable billing context.** The read-only GitHub user billing-usage API for
`users/{owner}/settings/billing/usage?year=2026&month=11` was readable.
Its repository-filtered returned rows contain
2026-11-10 Actions Linux usage of 9729 minutes: gross USD 58.374, discount 0,
net USD 58.374. Its 2026-11-11 storage row is 0.867599437 GB-hours, gross and
discount USD 0.000291528, net 0. There is no returned November 11 compute row.
These are partial historical GitHub charges across the repository, not these
two samples' costs, a complete invoice, or Namespace spend. Do not add them to
any other shared bill. Both `actions/runs/ID/timing` responses contain empty
`billable` objects, which do not establish zero cost. Namespace plan/trial,
compute, storage, seats, App/read and in-flight/delayed consumption are not
established here. Per-cut cost, the whole-bill total and compliance with the
USD 60 ceiling remain Unknown; no list-rate or "free" assumption fills them.

**Measured gap for Jake (AC5).** Neither observed initial PR workload reaches
seven: the control needs 17 allocated jobs (10 above seven), and the candidate
18 (11 above). Counting skipped records gives 21 and 23 (14 and 16 above).
Counting every captured workflow at each head, including push Privacy and the
later Changelog, gives 18 and 20 allocations (11 and 13 above), and 22 and 25
records (15 and 18 above). CI alone is unchanged at 19 records / 15 allocations;
extra benchmark/Changelog events explain the head-total difference. These are
full-fallback gaps, not a measured failure or success of the selected-site cut.
No CI1 gain, causal speed gain, cost saving or broader topology reduction is
claimed. The original synthetic selected-site example remains 8 to 7 executing
jobs and 8 to 8 records. Its live counterpart and actual-push comparison remain
Unverified; AC1 and C13's separate live/acceptance gate are not waived.

**Scoped validation and correction lineage.** Before this documentation edit,
`python3 -I tools/ci-bench/test_required.py` passed all 21 tests; the real-input
refusal above and independent raw count/clock/plan checks were then recorded.
No production or test implementation changed. No workspace/browser suite,
CloudRoom read, workflow rerun, new runner, spend, review, label or merge was
performed. Helpers: zero. This is R1's first evidence-collection correction;
no dispute or extra correction has been used. The collection is complete
within the ruling; it does not assert R1's acceptance requirement is satisfied.

### C5-M: post-merge measurement on real PRs (#2391), 2026-11-12

Evidence class: read-only GitHub Actions observation after #2312 merged
(merge commit `7edce1aa`, 2026-11-12T01:47:05Z). Jake's C5-M decision
(2026-11-11, [private record](https://github.com/jparker2006/ClosedWiz/issues/2312#issuecomment-6811892462))
moved this measurement after merge. No workflow, runner, account or billing
setting changed; no empty commit, dispatch or rerun was triggered.

**Red record.** The merged C4 analyzer (#2311) was first run on the honest
Actions-only input for the after sample below (`push_event_id` and `push` null,
input SHA-256 `e751049c975b703630722a18b1c7d01e1af4af71c08dba868f4c0fa3d623293b`):
`python3 -I tools/ci-bench/required.py <private-input>` exits 1 with
`required: nonempty ASCII text required` at the missing push identity, as in R1.

**Where the cut can fire.** The merged `plan.py` shares the site checkout only
when `combine_site_release` holds: a `selected` plan whose site lane holds both
`site:` and `release:` tests. Site tests enter a selected plan only when the
changed paths require `build-site`. A plan without them was already one
`release` job before #2312, so the cut cannot change its topology.

**Inventory and enrolment.** Freeze the `pull_request` run inventory,
created from 2026-11-12T01:47:05Z, listed at 21:20Z: 327 records over 4 pages, 76 of
them CI. Read every completed CI run's attempt-specific `ci-selection` artifact
(60 present; runs cancelled before upload have none). Count additions + deletions
on GitHub's three-dot compare of each recorded base and head.

- **Cut-eligible** (selected plan with `site:` and `release:` tests): **0** of
  30 selected plans, at any size. `combine_site_release` was false at every
  post-merge run.
- **Ordinary small ready context**: per PR, its first post-merge attempt-1 CI
  run on a ready PR to `main` with <200 changed lines and no `ci_change` reason,
  enrolled by creation time before outcome. Timelines show no draft or base
  change for any of them. The first five are below; failed and cancelled runs
  stay enrolled. #2396 (draft) and later CI-changing #2404, #2418 and #2420 are
  not ordinary; #2413 and #2415 came after the fifth.

| Sample | PR / run (attempt 1) | Lines | Plan | CI outcome | CI records / allocated | All workflows at head: records / allocated |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | #2393 / [43155577381](https://github.com/jparker2006/ClosedWiz/actions/runs/43155577381) | 30 | selected, no site | cancelled (superseded) | 14 / 6 | 17 / 9 |
| 2 | #2394 / [43160721455](https://github.com/jparker2006/ClosedWiz/actions/runs/43160721455) | 23 | selected, no site | cancelled (superseded) | 14 / 8 | 17 / 11 |
| 3 | #2395 / [43160724205](https://github.com/jparker2006/ClosedWiz/actions/runs/43160724205) | 23 | selected, no site | success | 14 / 8 | 17 / 11 |
| 4 | #2402 / [43173682089](https://github.com/jparker2006/ClosedWiz/actions/runs/43173682089) | 15 | unknown (cancelled before its artifact) | cancelled (superseded) | 14 / 2 | 17 / 4 |
| 5 | #2403 / [43175424797](https://github.com/jparker2006/ClosedWiz/actions/runs/43175424797) | 174 | selected, no site | success | 14 / 8 | 21 / 13 |

#2402's first head has one changed grill file; its plan is unknown, and its
later head on the same branch was selected without site tests. Every known plan dispatches `site=false`,
`release=true`. A completed selected CI attempt allocates `changes`, `always`,
`web-build`, `release`, `rust-export (1)`, `web-export`, `ci` and `web-test`
(8) and records `rust`, `web`, `site`, `skills`, `toolkit-nightly` and
`select-map` as skipped (14 records). With PR Privacy and Changelog, an initial
PR event allocates 10 jobs; the push Privacy run makes 11.

**Provenance.** GET paths are relative to `repos/jparker2006/ClosedWiz/`:
`actions/runs?event=pull_request&created=>=...&per_page=100` (all pages),
`actions/runs/ID/artifacts`, `actions/artifacts/ID/zip`, `compare/BASE...HEAD`,
`issues/N/timeline`, `actions/runs?head_sha=...`, `actions/runs/ID`,
`actions/runs/ID/attempts/K` and `actions/runs/ID/attempts/K/jobs`. Each head's
run list and every attempt's jobs fit one page and match `total_count`; each
run was read again after its jobs, and each head's run list again after
capture, with no change. All 24 captured attempts are attempt 1. Raw responses,
plans and billing stay private; this record omits job ids, runner names and logs.
Capture frozen 2026-11-12T21:22:24Z, raw SHA-256
`14ae800eb82ca278ed19c2aed706c533fd9680ebe5d880048c21552ef5fed472`.

**Clocks and C4.** All five heads give 89 job records and 48 allocated jobs.
Queue (job created to actual start, allocated jobs only) has n=48, median 25.5,
p90 165 seconds, from C4's `summary`. Sorted waits:
`2,2,2,3,5,6,8,9,9,9,10,10,10,10,10,11,11,12,12,14,17,24,25,25,26,26,27,41,44,45,46,47,63,73,76,96,102,102,121,126,132,134,137,165,176,184,268,327`.
Observed pools: `namespace-profile-closedwiz-rust` 38 allocations and the
self-hosted small runner label 10. Required results: #2395 completed `ci` at
05:32:21 and `web-test` at 05:32:33; #2403 at 07:45:25 and 07:45:46. Each
superseded run ended `ci` and `web-test` as failure, never success. Actual push
time stays unknown: the repository Events API keeps only 300 events (oldest
2026-11-12T10:41:39Z) and returned out-of-order creation times, so it supplies
no push receipt for these heads. With diagnostic placeholder identities only,
the same input otherwise validates in C4 (5 samples, 2 success, 2 cancelled,
1 unfinished; push-to-required n=0); that run is not a result.

**Billing context.** The user billing-usage rows for this repository show
2026-11-12 GitHub-hosted Actions Linux 47 minutes, net USD 0.282, and storage
net 0. No sampled job used a GitHub-hosted runner, so these rows are other
work. Namespace and self-hosted cost, the whole bill and the USD 60 ceiling
remain Unknown.

**Result for Jake (AC: measured gap against 5–7 jobs).**

- **Cut reduction measured: none observed, because the cut never fired.**
  0 of 5 cut-eligible PRs; **5 more are needed**: small ready ordinary PRs
  whose selected plan needs `build-site`.
- **Gate:** no weakening observed. Every superseded attempt failed `ci`; both
  completed samples passed with every required check present. The cut's own
  code path ran on no PR, so its live safety is also unexercised.
- **Gap to 5–7 jobs:** a completed small selected PR's initial event allocates
  10 jobs (3 above seven) in 16 records (9 above). With the push Privacy run,
  11 allocations (4 above). Against R1's full-fallback control (17 allocated,
  21 records), that is 7 fewer allocations, from selection that predates
  #2312, not from this cut.
- **Push-to-required comparison: Pending.** #2391 requires it, and neither
  cohort has an independent push identity or time, so C4 produced no
  comparison. Queue times and absolute completion clocks do not replace it.
- **Revert:** not opened. Whether "no measured reduction" should trigger the
  revert when the cut has not yet applied is asked on #2391.

**Status: partial, not complete.** This record does not close #2391. The
ticket stays open for the 5 cut-eligible samples, the push-to-required
comparison (or an explicit acceptance change) and the revert disposition.
Timing reduction, cost saving and CS1 remain Unverified; C13's gate is separate.

### Frozen synthetic C4 input

No live identifiers, captured account records or real timing/cost claims.
The analyzer retains unknown push/result times and the incomplete bill.

```json
{"schema":"closedwiz.ci-required.v1","evidence":"synthetic","frozen_at":"2030-01-03T00:00:00Z","cohorts":[{"id":"before","since":"2030-01-01T00:00:00Z","until":"2030-01-02T00:00:00Z","criteria":{"event":"pull_request","workload":"site-only-selected","selection_policy":"ordinary-first-attempt","runner_policy":"all","required_checks":[{"workflow":"ci.yml","name":"ci"},{"workflow":"ci.yml","name":"web-test"},{"workflow":"privacy.yml","name":"privacy"},{"workflow":"changelog.yml","name":"changelog"}],"repository":"synthetic-owner/synthetic-repo"},"membership":{"source":"synthetic-complete-api-export","total_count":1,"pages":[{"number":1,"next":false,"items":["push-a"]}]}},{"id":"after","since":"2030-01-02T00:00:00Z","until":"2030-01-03T00:00:00Z","criteria":{"event":"pull_request","workload":"site-only-selected","selection_policy":"ordinary-first-attempt","runner_policy":"all","required_checks":[{"workflow":"ci.yml","name":"ci"},{"workflow":"ci.yml","name":"web-test"},{"workflow":"privacy.yml","name":"privacy"},{"workflow":"changelog.yml","name":"changelog"}],"repository":"synthetic-owner/synthetic-repo"},"membership":{"source":"synthetic-complete-api-export","total_count":1,"pages":[{"number":1,"next":false,"items":["push-b"]}]}}],"observations":[{"id":"push-a","push_event_id":"synthetic-event-a","repository":"synthetic-owner/synthetic-repo","head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","push":null,"superseded":false,"batch":null,"runs":{"source":"synthetic-complete-api-export","total_count":3,"pages":[{"number":1,"next":false,"items":[{"run":1,"attempt":1,"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","workflow":"ci.yml","current":true,"created_at":null,"status":"completed","conclusion":"success","source":"synthetic-run-receipt","jobs":{"source":"synthetic-complete-api-export","total_count":6,"pages":[{"number":1,"next":false,"items":[{"id":1000,"run":1,"attempt":1,"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","name":"changes","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-01T00:03:00Z","completed_at":null,"runner":null},{"id":1001,"run":1,"attempt":1,"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","name":"always","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-01T00:03:00Z","completed_at":null,"runner":null},{"id":1002,"run":1,"attempt":1,"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","name":"site","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-01T00:03:00Z","completed_at":null,"runner":null},{"id":1003,"run":1,"attempt":1,"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","name":"release","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-01T00:03:00Z","completed_at":null,"runner":null},{"id":1004,"run":1,"attempt":1,"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","name":"ci","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-01T00:03:00Z","completed_at":null,"runner":null},{"id":1005,"run":1,"attempt":1,"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","name":"web-test","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-01T00:03:00Z","completed_at":null,"runner":null}]}]}},{"run":22,"attempt":1,"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","workflow":"privacy.yml","current":true,"created_at":null,"status":"completed","conclusion":"success","source":"synthetic-run-receipt","jobs":{"source":"synthetic-complete-api-export","total_count":1,"pages":[{"number":1,"next":false,"items":[{"id":1012,"run":22,"attempt":1,"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","name":"privacy","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-01T00:03:00Z","completed_at":null,"runner":null}]}]}},{"run":23,"attempt":1,"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","workflow":"changelog.yml","current":true,"created_at":null,"status":"completed","conclusion":"success","source":"synthetic-run-receipt","jobs":{"source":"synthetic-complete-api-export","total_count":1,"pages":[{"number":1,"next":false,"items":[{"id":1013,"run":23,"attempt":1,"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","name":"changelog","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-01T00:03:00Z","completed_at":null,"runner":null}]}]}}]}]}},{"id":"push-b","push_event_id":"synthetic-event-b","repository":"synthetic-owner/synthetic-repo","head":"cccccccccccccccccccccccccccccccccccccccc","push":null,"superseded":false,"batch":null,"runs":{"source":"synthetic-complete-api-export","total_count":3,"pages":[{"number":1,"next":false,"items":[{"run":11,"attempt":1,"head":"cccccccccccccccccccccccccccccccccccccccc","workflow":"ci.yml","current":true,"created_at":null,"status":"completed","conclusion":"success","source":"synthetic-run-receipt","jobs":{"source":"synthetic-complete-api-export","total_count":6,"pages":[{"number":1,"next":false,"items":[{"id":1100,"run":11,"attempt":1,"head":"cccccccccccccccccccccccccccccccccccccccc","name":"changes","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-02T00:03:00Z","completed_at":null,"runner":null},{"id":1101,"run":11,"attempt":1,"head":"cccccccccccccccccccccccccccccccccccccccc","name":"always","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-02T00:03:00Z","completed_at":null,"runner":null},{"id":1102,"run":11,"attempt":1,"head":"cccccccccccccccccccccccccccccccccccccccc","name":"site","status":"completed","conclusion":"skipped","created_at":null,"started_at":null,"completed_at":null,"runner":null},{"id":1103,"run":11,"attempt":1,"head":"cccccccccccccccccccccccccccccccccccccccc","name":"release","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-02T00:03:00Z","completed_at":null,"runner":null},{"id":1104,"run":11,"attempt":1,"head":"cccccccccccccccccccccccccccccccccccccccc","name":"ci","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-02T00:03:00Z","completed_at":null,"runner":null},{"id":1105,"run":11,"attempt":1,"head":"cccccccccccccccccccccccccccccccccccccccc","name":"web-test","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-02T00:03:00Z","completed_at":null,"runner":null}]}]}},{"run":32,"attempt":1,"head":"cccccccccccccccccccccccccccccccccccccccc","workflow":"privacy.yml","current":true,"created_at":null,"status":"completed","conclusion":"success","source":"synthetic-run-receipt","jobs":{"source":"synthetic-complete-api-export","total_count":1,"pages":[{"number":1,"next":false,"items":[{"id":1112,"run":32,"attempt":1,"head":"cccccccccccccccccccccccccccccccccccccccc","name":"privacy","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-02T00:03:00Z","completed_at":null,"runner":null}]}]}},{"run":33,"attempt":1,"head":"cccccccccccccccccccccccccccccccccccccccc","workflow":"changelog.yml","current":true,"created_at":null,"status":"completed","conclusion":"success","source":"synthetic-run-receipt","jobs":{"source":"synthetic-complete-api-export","total_count":1,"pages":[{"number":1,"next":false,"items":[{"id":1113,"run":33,"attempt":1,"head":"cccccccccccccccccccccccccccccccccccccccc","name":"changelog","status":"completed","conclusion":"success","created_at":null,"started_at":"2030-01-02T00:03:00Z","completed_at":null,"runner":null}]}]}}]}]}}],"comparisons":[{"id":"cut-1","before":"before","after":"after","change":"synthetic-site-release-shared-checkout"}],"cost":{"id":"synthetic-bill","kind":"whole-bill","evidence":"synthetic","complete":false,"since":"2030-01-01T00:00:00Z","until":"2030-02-01T00:00:00Z","source":"synthetic-all-provider-billing-export","components":[{"category":"plan","microusd":null,"source":"synthetic-billing-component"},{"category":"seats","microusd":null,"source":"synthetic-billing-component"},{"category":"compute","microusd":null,"source":"synthetic-billing-component"},{"category":"storage","microusd":null,"source":"synthetic-billing-component"},{"category":"app","microusd":null,"source":"synthetic-billing-component"},{"category":"other","microusd":null,"source":"synthetic-billing-component"}]},"synthetic_assumptions":["Only synthetic topology counts; no live capture or inferred push/result clocks.","Allocation clocks are fixed dummy data solely to exercise C4 allocated-job counting.","After-cut site row is skipped; total API job records and executing jobs are separate.","No runner or billing observation; costs and timing gains must remain unknown."]}
```
