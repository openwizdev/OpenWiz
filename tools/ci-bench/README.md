# The CI bench

The OpenWiz CI bench, `bench.py`, measures CI in **PRs an hour**, the headline of the historical CI spec (#330, ticket #332; grill C6 and its 10x amendment in PR #321), and charts every window against the 2026-11-01 baseline. The baseline's cohort and disclosed correction are recorded in the [private record](https://github.com/jparker2006/ClosedWiz/issues/332#issuecomment-6555791150).

```sh
python3 tools/ci-bench/bench.py collect --since 2026-11-02T00:00:00Z --until 2026-11-03T00:00:00Z --out DIR
python3 tools/ci-bench/bench.py measure DIR --robots 3 --label "after K3"
python3 tools/ci-bench/bench.py chart DIR [DIR...] --out CHARTS     # the baseline is always the first point
python3 tools/ci-bench/test.py                                       # its tests: fake gh, synthetic and baseline data
```

Python 3 (standard library only) and `gh`, logged in, run inside a clone (`gh` fills in `{owner}/{repo}` from `git remote`). It only reads GitHub: every call is `gh api <path>`, a GET. Nothing on the PC, nothing paid.

### Repository switch and the baseline gate (O1/O16)

The collectors already follow the clone through `gh`'s `{owner}/{repo}`
placeholders, including the factory GraphQL query. The publisher reads that
clone's `origin` (or the clone supplied with its existing `--repo` option) and
writes only `ci-benchmarks`. There is no fixed ClosedWiz collection target to
rewrite. The current private dashboard stays with its repository; after the
approved cut-over the target is `openwizdev/openwiz`.

O16's runbook must account for both O1 bench rows with the actual verified
merge of this repair and the following steps, never an inventory override:

| O1 row | Cut-over step | Read-back | Way back |
| --- | --- | --- | --- |
| `tools/ci-bench/README.md` | Select the approved public clone for collection and the publisher's source clone | Verify its `origin` and `gh` repository identity are `openwizdev/openwiz`; verify the publisher resolves that same origin | Stop public operations and retain the private clone and its dashboard |
| `tools/ci-bench/bench.py` | Before public charting or publication, supply an independently reviewed public aggregate baseline through the existing `--baseline DIR` on `chart`, `dashboard` and `publish.py` | Record the baseline's review pointer and exact aggregate digest, and check each command's selected baseline | Stop before output or publication if that baseline or its review is unavailable; retain the private baseline |

The persisted `closedwiz.ci-bench.v1` identity, private baseline bytes and
default path, and `--baseline` behavior stay unchanged. No raw private jobs or
baseline evidence is copied into the public tree, and no replacement baseline
is invented. The existing `daily.sh` pipeline does not pass a baseline override;
public daily operation remains gated until its baseline setup is separately
resolved and reviewed. These instructions authorize no collection, measurement,
render, schedule switch or publication. O16 still verifies merged handling and
records the runbook read-backs before accepting either inventory row.

## The three steps

| Step | Reads | Writes |
| --- | --- | --- |
| `collect` | The runs of `.github/workflows/ci.yml` created at or after `--since` and before `--until` that have completed; each run's jobs (its latest attempt), then the run again, which must still be the attempt, status and conclusion the list showed; the closed PRs into `main` | `DIR/window.json`, `DIR/jobs.jsonl` (one job a line, the baseline's shape), `DIR/merged.json` (the PRs merged in the window) |
| `measure` | `DIR`'s three files and `steps.tsv` | `DIR/point.json` (`closedwiz.ci-bench.v1`), and a summary on stdout |
| `chart` | Each window's `point.json`, the baseline's first (`--baseline`, default `private/evidence/infra-ci-scale/bench/baseline/`) | `CHARTS/prs-per-hour.svg`, `robot-minutes.svg`, `time-split.svg`, and `bench.md`: the three charts, PRs an hour first, and the tables behind them |

A read it can't trust stops it: a failed `gh` call, an answer that isn't JSON or repeats a key, a page short of its `total_count`, a run listed twice or not completed, a run that changed between the list and its jobs (a rerun: read the window again once it has finished), a field missing or of the wrong type, more than the API's 1,000 runs in one window (split it), a job that ran but ends before it starts, a CI step no row of `steps.tsv` matches (add its row first). It says `bench: <what>`, exits 1 and writes nothing. A bad command line exits 2 with the usage, before any call.

## What it counts

- **Successful code runs** (every window): push and `pull_request` runs that succeeded and in which `Run npm test`, `Run cargo test --workspace` or `Run npm run build` succeeded. Robot time is each job's whole time on its runner, started to completed; a job that never got a runner (none, and no steps) counts no time.
- **The reconstructed rule** (shown for the baseline only): runs in which `Run npm test` lasted more than 10 s, any event or conclusion, counting step durations only, with `The docs-only classifier` as setup. It is the 93-run rule that reproduces the baseline's first record, 10.34 robot-minutes per code PR, whose own script is lost. On the same data, successful code runs give 10.37: the correction, disclosed on every chart's page. The orchestrator settled both on #332.
- **PRs an hour of capacity** = robots × 60 ÷ robot-minutes per code run. `--robots` says how many robots the window had (the baseline: the PC's 3). A code run is not a PR (a PR can have several, and pushes to `main` are runs too): capacity says how many PRs an hour CI could take if each needed one code run.
- **Merged** = the PRs merged into `main` in the window, an hour at a time.
- **Each job splits into waiting, setup and running** (minutes per code run): waiting is created to started (0 for a job carried over from an earlier attempt, which GitHub shows starting before it was created); running is the tests and checks; setup is every other step and a job's time no step covers. `steps.tsv` names each step's category: web, rust, build, skills (running) or setup.
- **Queued to done:** a run's first job created to its last job done; median, nearest-rank p90 and max.

## The charts

Dark only, on GitHub's dark page (`#0d1117`). Jake, 2026-11-06: option B uses direct labels without axis numbers or gridlines ([private record](https://github.com/jparker2006/ClosedWiz/issues/1331#issuecomment-6674069137)). The dataviz skill's rules: its dark categorical steps, each chart's adjacent pairs checked against `#0d1117` with its `validate_palette.js` (all pass, every slot at least 3:1; checkpoint and palette evidence in the [private record](https://github.com/jparker2006/ClosedWiz/issues/1331#issuecomment-6674038293)); no axis numbers or gridlines, only a zero line, with each scale fitted to its own values; a label on every mark (the value at the point or the bar's tip, or inside a segment where it fits); the daily chart leads with the latest minutes per PR and PRs an hour, large, with the change from the day before (an arrow and words) and the gap to tonight's goal; tonight's goal is the only goal line, and the later goals and the 10× target are notes, never a stretched axis; a legend; a hover title on every mark; and `bench.md`'s tables with every number behind them. Static SVG.

## Gaps

- GitHub's answers are read by the fields the bench uses, each checked for its type; extra fields pass, as GitHub keeps adding them (the files the bench writes and reads back must hold exactly their keys).
- The benchmark workflow runs fixture proofs on changes to the bench or CI workflow; the main CI workflow stays unchanged.
- The latest attempt only: a rerun's earlier attempts are not counted, as in the baseline.
- Runs still in progress when `collect` reads are left out; read a window once it has finished.
- `--robots` is what you say: the bench can't tell how many robots served a window that mixed the PC's and GitHub's.

## Dashboard and daily publication (#1252)

Open the `ci-benchmarks` branch of the repository selected above.
Its README shows the Nov 1 baseline, latest window, staged goals, all daily and
checkpoint rows, and five charts. Minutes per PR is median queued-to-done per
successful code run, assuming one run per PR. Capacity remains robots × 60 /
robot-minutes per run. Actual merged throughput is shown separately.

```sh
python3 -I tools/ci-bench/bench.py check-steps
python3 -I tools/ci-bench/test.py
python3 -I tools/ci-bench/test_dashboard.py
python3 -I tools/ci-bench/test_publish.py
python3 -I tools/ci-bench/bench.py day-window
python3 -I tools/ci-bench/bench.py dashboard DIR [DIR...] --out DASHBOARD
# Explicit write: publish validated aggregate points and charts only.
python3 -I tools/ci-bench/publish.py --source DIR
```

`measure` adds an optional `cost` record to `point.json`; timing fields and
`chart`'s original interface stay the same. Historical v1 points remain
readable with unknown cost. New job records keep `runner_labels` from the jobs
API; old records have unknown kind. `prices.tsv` records compute and platform
USD/minute separately, source URLs and verification dates. Recognised labels
are the observed `closedwiz-pc` / self-hosted, standard GitHub Ubuntu x64 and
slim, Blacksmith's exact 2-vCPU Ubuntu 24.04 label, and Jog's exact
`jog-4vcpu`, `jog-8vcpu` and `jog-16vcpu` labels (before generic self-hosted). Other
kinds/sizes/prices
stay unknown. Add a sourced row before pricing a new SKU. `--prices FILE`
supports fixture tables.

Costs are **list-rate estimates**, before included/free minutes, not invoices.
GitHub-hosted jobs round up to a minute; Blacksmith estimates use the same
conservative unit. Jog jobs use their elapsed seconds / 60 as billed minutes.
[Jog publishes](https://usejog.com/docs/pricing/) $0.0024, $0.0044 and $0.0088
per minute for 4, 8 and 16 vCPU respectively, verified 2026-11-14; billing is
by the second. Free minutes and credits are not deducted. Window cost includes every collected
job, including failed,
docs-only and scheduled runs; cost/code run includes successful code runs only.
Only the latest attempt is collected, so rerun costs are understated; running
jobs are excluded. This is CI-compute cost only: other workflows (including
benchmark publication), storage, PC power/hardware/maintenance and provider
add-ons are excluded. PC compute is incremental provider spend ($0).
An unknown price makes the total unknown, never zero.

**USD/merged PR** divides all window CI spend by actual merged PRs, including
failed, docs-only and scheduled runs in the numerator. Zero merges makes this
ratio unknown. **USD/code run** averages successful code-run spend only, and
stays unknown with no successful code runs. These are different cohorts; the
merged ratio is not attributed spend for an individual PR. Both headline in
`bench.md`, the dashboard and the daily chart. Their day-over-day deltas are
absolute USD changes between adjacent full PST days; missing cost or a missing
day leaves the change unknown. The dashboard also shows USD by runner kind
using each point's recorded prices, preserving historical price provenance.

[GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
still lists self-hosted runners as free. The
[updated announcement](https://github.blog/changelog/2025-12-16-coming-soon-simpler-pricing-and-a-better-experience-for-github-actions/)
postpones the proposed $0.002/minute self-hosted platform fee. The table uses
$0 for that fee as checked on 2026-11-05; update it when operative docs change.
GitHub-hosted compute already includes platform cost; do not charge it twice.

The benchmark workflow runs fixture proofs on bench/CI-workflow PRs. At
**08:17 UTC** (00:17 fixed PST, UTC−08:00 all year), or on demand, its main-only
publication job measures the last full PST day. It uses the configured PC
runner (no provider charge), otherwise GitHub's cheapest hosted SKU,
`ubuntu-slim` ($0.002/minute). Its 15-minute budget is slim's platform limit;
a timeout fails visibly without publishing partial results. `python.sh` uses
Python on the image or the same checksum-pinned runtime CI already uses when
the PC image omits it. No project dependency.

After the workflow is on `main`, request a checkpoint:

```sh
gh workflow run ci-bench.yml -f since=2026-11-05T08:00:00Z \
  -f until=2026-11-05T22:00:00Z -f label='after #1251' -f robots=5
```

Supply all three checkpoint fields together; otherwise validation fails
before an API read. Blank inputs select the last full PST day. A local
on-demand run uses the same pipeline:

```sh
BENCH_SINCE=2026-11-05T08:00:00Z BENCH_UNTIL=2026-11-05T22:00:00Z \
  BENCH_LABEL='after #1251' BENCH_ROBOTS=5 sh tools/ci-bench/daily.sh
```

The publisher uses a separate temporary Git repository. Only `ci-benchmarks`
can be pushed. Each aggregate point goes under `windows/` with a deterministic
key of bounds and label; repeating a measurement updates it and preserves other
windows. Raw jobs, runner names and run/PR identifiers are never copied.
A day without successful code runs is recorded with cost and unknown timing
(`measure --allow-empty`), shown in the table and omitted from charts.
Checkpoints can overlap days; never sum their costs. Robots is an explicit
capacity assumption, not inferred from mixed providers.

Only the main-only publication job gets `contents: write`. It needs only
`GITHUB_TOKEN`. GitHub scopes it to the repository, not a branch: the job guard
and hardcoded publisher refspec limit writes in code; branch protections are
separate. Publications are serialized; a remote conflict stops rather than
force-pushing.

## Backfill every full PST day

```sh
# Defaults: Nov 1, 2026 through yesterday in fixed PST; never includes today.
python3 -I tools/ci-bench/bench.py backfill --out /tmp/ci-days --robots 5
# Publish all aggregate points in one commit; raw API records stay local.
python3 -I tools/ci-bench/publish.py --source /tmp/ci-days/*
```

`backfill` measures one point per 08:00–08:00 UTC day using the same successful
code-run cohort, price table and capacity formula as `measure`. Optional
`--start-day YYYY-MM-DD` and `--through-day YYYY-MM-DD` narrow the range;
`--now UTC_TIME` makes the bound reproducible. Future/partial days are refused
before API reads. Keep the output folder to resume a long collection: completed
points are validated against their exact day, label, robot assumption and
latency basis, then skipped without more reads. Failed days have no point and
are collected again. A reused point is a historical snapshot, not a new live
measurement; use a new output folder if earlier runs have since been rerun.
For retained raw records, existing `measure DIR --robots N --label TEXT
--allow-empty --allow-timing-gaps` reprices without API reads. Ordinary cached
`backfill` resume does not refresh prices. No new backfill mode is introduced.

The dashboard now **leads with `daily-metrics.svg`**: four aligned date plots for
median minutes/PR, PRs/hour of capacity, USD/merged PR and USD/code run, with tonight
(under 10 minutes / 25+ per hour), this week (3 / 80) and north-star (1 / 500) goal lines. Missing successful
code runs stay unknown and break the lines. Only complete fixed-PST points with
the new latency basis enter this chart; partial checkpoints and the old Nov 1
baseline stay in the reference tables and detailed charts. Thus the historic
baseline is not silently relabelled as the full Nov 1 calendar day.

New collections preserve workflow-run `created_at`. Their latency is **workflow
creation to last job completion**, a push-to-result proxy that includes waiting
before the first job exists. GitHub's historical run/jobs API does not supply
the actual push-event timestamp. Commit timestamps are not push timestamps;
`updated_at` is not used as a result time. The old baseline lacks run creation
and retains its original first-job-created latency. Daily capacity uses the
supplied `--robots` value consistently; 5 is an explicit comparison assumption,
not a claim that the historical mixed-hosted fleet had exactly five runners.

A cancelled Nov 1 run contains a job whose reported completion predates its
reported start. Backfill preserves such a non-successful run as a **timing gap**:
its duration is not invented, total window cost is unknown, and the unknown-job
count is shown. The successful-code cohort and its two metrics are unaffected.
`daily.sh` uses the same timing-gap handling for nightly and on-demand windows.
`measure --allow-timing-gaps` enables the same explicit behavior; ordinary
`measure` still refuses reversed durations. Reversed successful-run durations,
invalid timestamps and inconsistent run creation times still fail closed.

## Factory benches (#1359)

Four day-over-day benches of the whole factory, not only CI, on the same
dashboard and for the same full PST days:

```sh
python3 -I tools/ci-bench/bench.py factory --since T --until T --out DIR   # after collect, into the same DIR
python3 -I tools/ci-bench/test_factory.py
```

`factory` writes `DIR/factory.json`; `measure` then adds a `factory` record to
`point.json` (aggregates only) and refuses a history whose merged PRs differ
from `merged.json`. `daily.sh` and `backfill` run it for every day; a cached
backfill day measured before #1359 gets only the factory reads, then is
measured again from its kept jobs.

| Bench | Measures | Read from |
| --- | --- | --- |
| Throughput | Merged PRs a day; hours from a ticket's first `ready-for-agent` label (or, without one, its first `**Approved` record) to its first closing PR's merge, median and p90 | One literal GraphQL query (never a mutation): merged PRs into `main`, their comments, closing tickets, label events and ticket comments; first page of each nested list |
| Reviews | Share of reviewed merged PRs whose first `VERDICT:` comment says APPROVE; `VERDICT:` comments per reviewed PR | The same query |
| Main red and reruns | Minutes, within the day, that the newest-pushed finished green-or-red attempt of `main`'s push runs was red; reruns (attempt 2 on) that started in the day, by the attempt's own start, by cause, out of all attempts started in it | REST GETs: main's push runs from a day before (newest first, stopping at the first that had finished before the day), each attempt and its jobs; every `ci.yml` run created in the day or the 30 days before (GitHub reruns a run [up to 30 days after it](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs), so this is every run that can have a rerun in the day; a day per list, as one list holds at most 1,000), and for those updated in the day each attempt's start; failed jobs' logs (`gh api --allow-escape-sequences`, text classified and dropped) |
| Runner wait | Each job's created to started, median and p90, by the job's own creation, for every attempt's jobs that got a runner (a carried-over job counts once, in its own attempt); run time stays in the CI tables | Every attempt's own job list, for the day's runs and the look-back runs updated in the day; an attempt `collect` already read is reused from `jobs.jsonl` only by its identity (run, attempt and job ids, recorded by `collect`), so a run that finished or was rerun between the two reads is read again, never counted twice |

Rerun causes: **runner/network** when a failed job's log names a runner
shutdown or a network fault (the #1309 audit's errors: DNS, TLS, timeouts,
resets, HTTP 5xx); **flaky** when the rerun passed and every failed job's log
is readable and shows a failed test (`test result: FAILED`, a nonzero
`fail` count, Python's `FAILED (failures=…)`), as in #1308; **after a pass**
(a re-test) or **after a cancel** when the attempt before it passed or was
cancelled; otherwise, including expired logs, failures that are not all
failed tests and failures that failed again, **unknown**.

Unknown is never 0: no merged PR leaves the ratios unknown; a day whose start
has no known main state (nothing finished in the look-back) or a finished
attempt with no job times leaves main red unknown; a ticket with neither ready
record, or whose label history runs past one page, is an unknown ticket; a PR
whose comments run past one page without a verdict is an unknown review. PRs
that close no ticket of this repository are counted as unlinked. Each ticket
counts once a day, at its first merged closing PR.

`factory.json` keeps PR, ticket and run numbers locally (never published) and
no comment, log or thread text. No goal is set for these benches, so their
charts have no goal lines. Gaps: a merged PR updated while the history is read could move between
pages (the `merged.json` cross-check then refuses the day); a deleted approval
comment or a manually unlinked ticket is gone from history. The nightly publish job
has `issues: read` for ticket timelines (#1359). The look-back costs about one
list read per 100 runs over 31 days (about 100 reads a night at today's volume)
on top of `collect`'s. If the factory reads fail (a failed or refused read,
including the token's hourly allowance running out), `daily.sh` says so and still publishes the day's CI numbers, with
that day's factory benches unknown.

## Buckets (#1359, BN2)

`measure` also writes `point.json`'s `buckets`: the window cut into 1-hour and
6-hour buckets from its start (the last one clipped to its end), each with the
CI benches (`code_runs`, median minutes per PR, PRs an hour of capacity,
merged PRs) and, with `factory.json`, the whole factory record for that
bucket. Each value carries its sample size: code runs, merged PRs, tickets,
reviewed PRs (complete histories for rounds), main verdicts finished in the
bucket, attempts started in it (for reruns) or jobs (for runner wait). A code
run falls in the bucket of its creation, a rerun or attempt in that of its
start, a job in that of its creation and a PR in that of its merge; a ticket
counts once, in the bucket of its first closing merge that day; main red
counts the red minutes inside the bucket, carrying main's state in from
before it. Ready-to-merged and runner-wait p90s are shown beside their
medians. A day without buckets is drawn as unknown, breaking the lines, and
the hourly chart always shows the latest full day.

The dashboard adds `buckets.md` (every bucket of every full PST day, each
value as `value (n=…)`), `buckets-6h.svg` (all days) and `buckets-1h.svg` (the
latest full day). Thin buckets (n < 3) are hollow marks; unknown is never 0.
Days measured before the buckets read unknown; `backfill` adds buckets to a
cached day by reading its factory history again.

## Selector escapes (#1264)

```sh
python3 -I tools/ci-bench/bench.py escapes --since T --until T --out DIR   # after collect, into the same DIR
```

`escapes` writes `DIR/escapes.json`. `measure` then adds an `escapes` record to `point.json`: `count`, `attempts`, `failed_attempts` and `unknown`, counts only. The dashboard's day-by-day and checkpoint table shows it as **Selector escapes**. `daily.sh` runs it for every day. If its reads fail, that day's count is unknown, and the CI numbers are still published.

Each CI attempt belongs to the window it **started** in, as the reruns bench's attempts do. A rerun of a run from an earlier day counts on the day the rerun started.

It reads three things, each a GET:
- `main`'s push and nightly CI runs created in the window or the 30 days before it, one day per list (31 lists), and each earlier attempt of a rerun run that changed in the window;
- for each failed attempt that started in the window, the escape finder's run of the same name (`Selector escapes in CI run <id> attempt <k>`, from [`.github/workflows/ci-escapes.yml`](../../.github/workflows/ci-escapes.yml), created up to a day after the window ends);
- the issues updated since the window started.

The count is the number of distinct escapes in issues that `github-actions[bot]` opened with the finder's marker as their first line, for one of those failed attempts (the marker names the run and attempt that found it). An escape still counts when a rerun of its run later passed. Each escape is reported once, so it counts on exactly one day: the day the attempt that found it started. No failed attempt is **0**. A cancelled attempt needs no finder: it tested nothing, and the next full run tests the same commits.

The count is **unknown** (`count: null`, never 0) when any of these hold:
- an attempt that started in the window is still running;
- an attempt ended in anything but success, failure or a cancel (`timed_out`, none, or another);
- a failed attempt has no finder run;
- its newest finder run is still running or did not succeed. The finder fails on anything it can't judge, such as a missing plan before X5 (#1262), or a failure that names no test.

Windows measured without `escapes` show unknown. `backfill` does not read escapes.

## Shared journeys and tagged experiments (#1385)

The same nightly/on-demand workflow adds `point.json`'s optional `journey`
(`closedwiz.journey.trends.v1`) and links `journey-trends.md` from the dashboard,
with dark `journey-reviews.svg` and `journey-findings.svg`. Historical points
without journeys and wholly absent publication dates stay unknown and break
both charts' lines; render-only gap dates never add observed weekly coverage.
Existing CI, four factory benches, buckets,
selector escapes, PST bounds and Nov 1 backfill remain available.

```sh
python3 -I tools/ci-bench/test_trends.py
# Read-only GitHub collection, after factory, into the same local window:
python3 -I tools/ci-bench/trends.py collect DIR [--repo OWNER/REPO] [--usage DAILY.json]
# Offline: consume EB1's validated shared document, never parse verdicts again.
python3 -I tools/ci-bench/trends.py report DIR/journeys.json \
  --since 2026-11-01T08:00:00Z --until 2026-11-02T08:00:00Z \
  --out DIR/journey-report.json [--cf4-score RESULTS/score.json]
python3 -I tools/ci-bench/bench.py measure DIR --robots 5 --label '2026-11-01 PST' --allow-empty
```

`collect` uses EB1's `journey.py` and its existing repository-aware PR inventory
and usage reader. The caller selects the day's `factory.json` closing tickets
using EB1's complete, paginated closing-link inventory, plus currently linked
open PRs; EB1 reads their journeys. Open tickets without
PRs are not an inventory census. A shared PR counts once. Raw journeys and their
separate source links stay local; the publisher copies only validated aggregate
points and generated charts/tables. It never copies `journeys.json`, factory
history, score rows, identifiers or raw comments. Extra fields in a published
journey aggregate are refused.

Cohorts are labelled: merged within the window; **current linked open PRs at
collection**, not historical open counts; reviewed PRs from their union.
Unlinked PRs fall outside journey coverage. Sample sizes, unreviewed PRs,
unknown ready times (including tickets absent from an input document) and
edited/unknown PR events, including unanswered fix rounds, are shown. Only EB1 independent,
nonduplicate verdicts count as rounds. The older #1359 tables retain their
original verdict-based definition, explicitly separate from the new journey
cohorts. The 2026-11-06 grill snapshot is dated context, not a new measurement.

Finding kinds follow EB1's vocabulary and explicit markers. Open snapshots
repeat across days: never sum them into weekly incident counts. EB4 consumes
journey findings directly for deduplication. Ready-to-merge counts each ticket
at its first closing merge in the document; its missing ready label stays
unknown (the legacy factory bench still supports its approval-record fallback).

Credits keep Claude and GPT separate. Known attributed ticket credits are
lower bounds for recorded threads; shared parent work is excluded. Incomplete
attribution/usage days and tickets spanning several PRs leave credits/merged PR
unknown. UTC daily usage/merge ratios appear separately and are never relabelled
as PST-day or ticket costs. No usage export is required; absent exports leave
cost unknown. This adds no billing source or model-policy authority.

Week-over-week uses two nonoverlapping seven-day merged cohorts ending with the
latest full PST day, each with observed/expected days, PRs and reviewed samples.
Experiments use the journey's exact tag, base/head/merge revisions, CF4
settings/cases/code/revision markers and optional recorded score/result/schema
hashes. Supplied baseline scores at the base revision are retained even when
there is only one tagged experiment; case/repeat identities and scorer row
shapes are validated before a result is reported. Checkpoint experiments and
cohort tables are included while only full days feed weekly charts/arithmetic.
Each experiment compares seven full PST days before/after its merge
day, excluding the rollout day; unfinished windows remain visibly partial.
Only matching CF4 cases/settings/code/schema and the baseline revision can be
compared as one baseline. A marker alone says **not recorded**, never passing.
Optional scores distinguish passing, failed and unfinished; the scorer's
`incomplete` reason means unfinished even with an `end_turn` stop. No paid eval runs
here. Changed suites require a fresh baseline; observational trends establish
no causation. `trends.period`/`comparisons` and the aggregate report are EB4's
weekly-report seam; snapshots must not be summed as independent open cohorts.

A failed required journey read or proof stops before publication, preserving
the last good branch. #1359's existing exception remains: if factory collection
fails entirely, CI numbers still publish with factory and journey unknown.
The workflow retains its single schedule, main-only writer, permissions and
publication branch. No publication was run as part of this ticket. Old Nov 1
backfill evidence is reused; it is not relabelled as journey/live improvement.

## EB6 first-push timing and defect guards (#2177)

The existing journey collection now emits an explicit EB5 outcome sidecar and
includes its aggregate summary in the same `journey-report.json`, `point.json`
and `journey-trends.md`. Old points/reports without outcomes remain readable
as unknown outcome coverage. Existing charts, legacy factory metrics, selector
escapes, fixed-PST daily boundaries, checkpoint and Nov 1 backfill semantics
are unchanged. No new schedule, paid eval, billing source or publication grant.

```sh
python3 -I tools/ci-bench/trends.py collect DIR --repo OWNER/REPO
python3 -I tools/ci-bench/trends.py collect DIR --repo OWNER/REPO --defect-policy policy.json --previous PRIOR_DIR
python3 -I tools/ci-bench/trends.py report DIR/journeys.json --outcomes DIR/outcomes.json \
  --since 2030-01-01T08:00:00Z --until 2030-01-02T08:00:00Z --out DIR/journey-report.json
# Optional: validated, already recorded assignments from the same EB5 bundle.
# This reads records only; it cannot grant approval or assign work.
python3 -I tools/ci-bench/trends.py report DIR/journeys.json --outcomes DIR/outcomes.json \
  --experiment experiment.json --since 2030-01-01T08:00:00Z --until 2030-01-02T08:00:00Z \
  --out DIR/journey-report.json
```

Read the source procedure and evidence formats in
[factory-metrics/README.md](../factory-metrics/README.md#first-successful-push-receipt-2177).
First-push timing requires a sourced receipt (or retained complete historical
push evidence) and a verified merge; no PR-created/commit/CI proxy is used.
The primary unit is elapsed hours. Ready-to-merge remains the existing ticket
measure; builder-start-to-merge is a separately labelled PR measure using its
linked collected tickets' earliest known start. Neither substitutes for push.

Per-cohort tables retain all collected records, including open and closed PRs
and tickets with no PR. Assigned old/candidate coverage is shown only when a
validated shared experiment bundle is explicitly supplied, joined by ticket
and PR number, with identical sidecar, sources and defect policy. Missing
assignments stay not supplied. Shared PRs count once within each cohort; a PR
spanning arms is a confounding matter for EB8, never an independent pair.
This report does not reconstruct a historical census or choose eligible work.

Each timing/round distribution carries n, unknown count, mean, median, p90 and
sample SD (null below two observations). An aggregate numeric histogram retains
exact sufficient information to pool these statistics across full daily points.
Weekly/tagged tables do not average daily medians or SDs. Missing sidecar days
stay missing, snapshots of open/closed/assigned work are not added across days,
and incompatible frozen defect policies yield no pooled defect rate. The merge
day stays excluded from the existing before/after comparison. Baseline inputs
with insufficient or unavailable timing remain unknown; they cannot justify a
power calculation or a live launch. Trends remain observations, not causation.

Independent rounds come only from the existing journey verdict parser, with
identical reposts and helpers excluded. Missing reviews are unknown, not zero.
The defect table shows mature, immature and unknown follow-up, unresolved
attribution, observed attributable event lower bounds and affected/known-mature
PRs. Only mature PRs with no unresolved attribution enter the defect rate;
zero known-mature PRs yields null. Maturity does not settle attribution. Root
causes deduplicate across reruns and later fixes within the predeclared window;
a selector escape alone supplies no skill attribution. Coverage attestations
remain sourced assertions to review, not automatic guarantees of complete history.

All required source/sidecar reads and contract validation finish before writing
the report. A failed/partial read preserves the last good report/publication.
Only sanitized aggregate fields cross the existing strict publication reader;
raw journeys, sidecars, source links and identifiers remain local/private.
Fixture proofs demonstrate arithmetic, uncertainty and refusals. Exact-head
independent review and required CI remain merge gates. Real speed, live safety,
CF4 paid evidence, experiment activation and publication retain their own gates.
## CI2 actual push to complete required result (#2311)

This is a **separate offline metric**. Historical creation-to-last-job,
queued-to-done, CI1/X10 checkpoints and capacity estimates above keep their
original meanings. CI2 does not relabel them or claim those gains again.

```sh
python3 -I tools/ci-bench/required.py tools/ci-bench/fixtures/required/cohorts.json
python3 -I tools/ci-bench/test_required.py
# A separately authorized capture can later supply a private frozen bundle:
python3 -I tools/ci-bench/required.py /path/to/private/frozen-bundle.json
```

The standard-library CLI reads one bounded JSON file (at most 8 MiB), writes
only its report to stdout, and never invokes GitHub, publishes, starts jobs,
changes routing or updates account data. The existing benchmark `proof` job
runs its offline tests; its existing `tools/ci-bench/**` filter includes all
inputs. Publication, runner choice and cadence are unchanged. **No real
account collection is authorized here.** Live comparable before/after cohorts
remain Unverified until C13 (#2320) and its separate read authority.

The synthetic [example bundle](fixtures/required/cohorts.json) is the complete
input shape, `closedwiz.ci-required.v1`. Its data and normalized receipt shapes
are labelled in `synthetic_assumptions`, not a claim of observed GitHub output.
It includes:

- `frozen_at`, evidence class (`synthetic` or `observation`), named cohort windows,
  exact criteria (repository, event, workload, selection policy, all runners,
  and every required workflow/check), and an independently sourced membership
  export. Capture **all pushes satisfying the declared criteria**, including
  those with no run or result; freeze the membership before measuring it. Never
  enroll by success, runner price, job completion or a later green head. The
  analyzer validates declared membership, not the truth of its acquisition.
- Each observation's repository, immutable head, stable `push_event_id`, optional
  actual `push` receipt, supersession flag, optional combined `batch`, and **all workflow runs and
  attempts** for that push. A push receipt needs `kind: push-log|webhook`, its
  independent `source`, head and UTC `at`. No commit date or run-created proxy
  is accepted. Missing push evidence is `null`, not a fabricated timestamp;
  membership still retains the observation, with its enrollment independently
  established by the membership capture. `push_event_id` is the repository-scoped
  event identity from that independent capture, required even when the timestamp
  is unknown. Preserve it across sources and repeated exports; an observation id,
  source name or head alone is not an event identity. Duplicate captures of one
  event are refused even with disjoint receipts. Distinct pushes of the same head
  from the same source retain their distinct event identities and samples.
- Every run binds `run`, `attempt`, `head`, workflow and source. Its jobs repeat
  the exact head/run/attempt, each with id, name, status/conclusion, nullable UTC
  created/started/completed timestamps and nullable **actual** runner pool.
  Include other required workflows (for example privacy), non-required jobs,
  failed/cancelled runs and earlier attempts. `current` identifies the frozen
  current run/attempt per workflow; an old run or attempt cannot supply its receipt.
  The selected run must have the uniquely latest creation time across all exported
  run IDs of that workflow, then its latest attempt. Multiple run IDs with unknown
  ordering or a tied latest creation time are ambiguous and refused; run IDs and
  list order are not clock substitutes. Creation times must agree across attempts
  of one run. A single run with unknown creation time can still supply receipts;
  its creation time never substitutes for push time.
  Acquirers must compare current run/attempt again after reading jobs, refusing
  a changed snapshot. Configured `runs-on` labels are not observed runner use.
- Membership, run/attempt listings and each run's jobs use the same normalized
  complete-page envelope: `{source, total_count, pages}`; each page contains
  `{number, next, items}`. Pages are consecutively numbered from 1, `next` is
  true exactly before a subsequent page, and all item counts must equal the
  captured total. Preserve upstream next-link traversal and counts, including
  all pages/attempts and any other required workflows. Truncation, duplicates,
  foreign identities or inconsistent page metadata refuse the input. The CLI
  does not authenticate a source pointer or recover absent upstream evidence.
- `comparisons` reference named before/after cohorts and one cut id/change each.
  Criteria must match exactly; windows and sample counts are disclosed. A cut
  with an unknown latency has no reduction value. Cuts can reuse a cohort by
  reference, but improvements are **not additive**. C5 (#2312) can keep one
  record per cut with jobs/attempts, job records, checks and runner mix; no new
  scheduler, selection schema or CI gate is introduced.
- Optional `batch` carries id, base, combined head, ordered member heads and
  source for C7 (#2314)/C13. Its combined head must equal the observation head
  and last member. A batch contributes one observation, not one per member.
  This measures its combined-head push; it does not estimate time since its
  oldest member or certify C6's combined-work coverage/admission contract.

The report freezes the exact input bytes with SHA-256 and retains identity,
provenance, cohort membership, job records and required receipts for audit.
**Keep raw inputs and reports private**: they can contain real run, job, head,
repository and source identifiers. This command is not connected to the
aggregate-only publisher.

Timing starts only at evidenced push and ends at the last completed required
check in the current head/run/attempt set, after its workflows are terminal.
Every required check must exist with a terminal timestamp. Unknown start or
end remains null. The distribution includes complete terminal failures and
cancellations; outcome counts separately disclose success, failed, cancelled,
missing, unfinished and superseded. Superseded samples remain enrolled and
flagged; earlier attempts retain their outcome and job count. A workflow that
failed cannot look successful because one check succeeded. A passing result
is not inferred from missing, skipped, stale, failed or cancelled work.

Median is the ordinary median; p90 is nearest rank (`ceil(0.9 × n)`). Every
summary includes its known sample denominator. Cohort size and incomplete
outcomes remain beside timing; a reduction is unknown if either cohort has a
missing latency. The observational `timing_target_met` flag requires every
member successful, none superseded, all starts/ends known, median <600 seconds
and p90 <1200 seconds. It is never the CS1 live acceptance gate: `live_success`
remains `Unverified`, even for an input marked `observation`.

Queue time is job-created to actual start, separately from total push latency;
it includes scheduler/dependency effects. Only a job captured as `queued`, with
known creation and no start, establishes a censored lower bound at freeze.
An `in_progress` job with a missing start may already be allocated: its wait
remains unknown, with no lower bound. Other unknown waits are gaps, never zero. Job
counts include all exported jobs/attempts (including skipped and failed);
allocated counts and observed runner counts are separate. A run attempt or job
repeated across observations is refused rather than counted twice.

`cost` is one shared bill context, with its own id, coverage period, provenance,
evidence class, completeness and kind. Each of plan, seats, compute (all
providers), storage, App/read arrangement and other account consumption has
one amount in integer micro-USD and a source; an unknown amount is `null`,
never zero. Include in-flight/unbilled work and delayed usage in the capture's
completeness assessment. A list-price estimate or partial bill is disclosed
with **unknown whole-bill total**. Component sums are not invoice proof.
Cohort windows must fall within the bill context, whose periods need not be
identical to timing windows. There is no fabricated per-cut cost allocation:
every cut references the same bill id, counted once. Never sum these shared
bills or overlapping comparisons, or treat included/free capacity as a
success-only cohort. Unknown cost stays a gap; actual whole-bill completeness,
prices and any live speed/spend acceptance require C13's independent evidence.
