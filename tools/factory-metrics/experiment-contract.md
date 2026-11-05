# EB experiment contracts, version 1 (`openwiz.bottlenecks.v1`)

EB5 (#2176), spec #1383 revision 11. These are contract interfaces and synthetic
validation controls. They authorize no research, evaluation, replay dispatch,
live assignment, activation or publication. Live/spending gates, independent
review, required CI and verified merges remain separate. An evidence reference
is an assertion to verify, never permission to execute.

## Boundary and compatibility

```sh
python3 -I tools/factory-metrics/experiment_contract.py check \
  tools/factory-metrics/fixtures/bottlenecks-contract/accepted.json \
  --journey tools/factory-metrics/fixtures/journey/journeys.json
python3 -I tools/factory-metrics/test_experiment_contract.py
```

Python public seams: `validate(bundle, journey_v1)`, `validate_journey(v1)`,
`migrate_journey(v1)`, `defect_attributions(validated_defects)`, `validate_transition(before, after, before_journey_v1, after_journey_v1=None)`,
`validate_replay(replay, experiment, sources)`, `validate_preregistration(...)`,
`validate_usage(rows, sources)`, `validate_result(result, bundle)` and
`preregistration_digest(protocol)`. Success returns None; refusal raises
ValueError. `digest(value)` supplies canonical SHA-256, not an evidence verifier.
Canonical hashing uses Python JSON with `sort_keys=True`, `separators=(",", ":")`,
`ensure_ascii=True`, `allow_nan=False`, then UTF-8 and SHA-256.
The CLI check exits 0/1; bad arguments exit 2. Reads are explicit local files;
no network, program launch, state write, environment override or dependency.
Repeated JSON keys, nonfinite numbers, booleans as counts, missing/extra fields,
wrong versions and broken joins refuse. New objects do not depend on key order;
legacy v1 keeps its existing strict validator, including its ordering rules.

`execute(operation, ...)` always raises `UnavailableOperation`, including
`collect`, `research`, `paid_eval`, `run_replay`, `launch_live`, `activate` and
`publish`. CLI equivalents refuse before reading input. EB6 owns collection,
E2 (#1362) the candidate/CF4 handoff, EB7 (#2178) replay, EB8 (#2179) live work,
E3 (#1363) weekly checkpoints, EB3 (#1386) precheck binding and EB4 (#1387)
staged reports. Those owners implement behavior against these shapes; they do
not gain authority from a conforming record.

Existing journey v1 and CF4 v1 formats are unchanged. The journey extension is
[section 9 of journey-contract.md](journey-contract.md#9-eb5-outcome-extension-closedwizjourneyoutcomesv1).
CF4 references use its existing commit/tree, settings/cases/code/schema hashes,
case count, repetitions and all-runs-pass semantics. This contract neither
replaces CF4's manifest/scorer validation nor treats offline tests as paid runs.
Read the referenced artifacts at their pinned revisions; verify their bytes,
coverage and permissions before using them. No new paid baseline is implied.

## Envelope and joins

Every bundle contains exactly:

| Key | Value |
| --- | --- |
| `schema` | `openwiz.bottlenecks.v1` |
| `experiment` | immutable experiment below |
| `experiment_hash` | canonical SHA-256 of experiment |
| `cf4_runs` | append-only old/candidate CF4 result records; empty means not run |
| `journey` | `closedwiz.journey.outcomes.v1` sidecar bound to explicit v1 input |
| `assignments` | append-only assignment records, including unfinished tickets |
| `deviations` | append-only actual exposure/confounding records |
| `stages` | research/cf4/replay/live status and immutable artifact references |
| `replay` | replay record below, or null when unavailable |
| `preregistration` | complete numeric protocol below, or null when unprepared |
| `result` | live result below, or null when unobserved |
| `usage` | per-arm/total rows below, including explicit gaps |
| `sources` | map `s1`, `s2`, ... to this repository's GitHub evidence links |

Tag + repository + experiment hash identify a frozen experiment. Ticket/PR joins
use numbers in the bound journey, never titles, branch names or runtime ids.
Sources are apart from facts. No bodies, transcripts, answer text, credentials,
operational identities or private routing state enter these files. A public
approval source uses the existing private-record pointer convention. Hashes are
64 lowercase hex, commits/trees 40 lowercase hex; times UTC seconds ending Z.
Fixtures and their links are synthetic. Unknown and not run never mean zero.

## Immutable experiment, CF4 and stages

Experiment has exactly `tag`, `repo`, `frozen_at`, `arms`, `defect_policy`,
`settings_hash`, `change_kind`, `replay_settings`. Tag uses the existing EB1 tag
syntax. Change kind is skill/model/brief. Both `old` and `candidate` arms contain
`revision: {commit, tree}`, `build_hash`, `review_hash`, `brief_hash`, `cf4`.
Hashes pin skill/brief bytes at those immutable snapshots. Live family selection
and independent reviewer requirements remain the existing policy.

A frozen CF4 input reference contains `manifest_hash`, `settings_hash`,
`cases_hash`, `code_hash`, `schema_hash`, `revision: {commit, tree}`, `repeats`,
`case_count`. Both arms match settings/cases/code/schema hashes and positive
repetitions/case counts; revisions match their own arm snapshots. Changed
cases/settings/scorer/schema need a fresh compatible baseline, not a new label.

Observed results live separately in `cf4_runs.old` / `cf4_runs.candidate` lists.
Each append-only record has `{key, status, runs, passed, score_hash, at, source}`.
Key is unique within its arm; records are ordered by completion time. Status is
pass/fail/error. Pass requires runs = passed = repeats × case_count. Fail/error
retain their actual counts; missing runs never pass. An empty list means not run,
not a zero-cost pass. `score_hash` pins the separate scored artifact. Completing
an unchanged planned run adds evidence without changing the experiment identity.
A retry is a new record with its own key; old outcomes remain immutable.

Replay and preregistration use `cf4_refs: {old: key, candidate: key}` to bind exact
passing results, whose completion times precede their consuming stage. Thus a
CF4 completion cannot silently replace the compared skill/case/settings inputs.
`validate_cf4_runs` checks these result records; actual manifest and score byte
verification still belongs to the consumer at the existing CF4 seam.

`defect_policy` has `rule` (an explicit attribution rule identifier),
`followup_hours` (positive), `deduplication: root-cause-per-merge`,
`unknown_attribution: retain-unknown`. Freeze the actual causal-link rule and
follow-up before comparison. The fixture rule requires an explicit causal link
from the main failure/fix to the evaluated merge, never timing alone.

Replay settings have exactly `provider: codex`, `model` (nonempty), `effort`
(high/xhigh), `service_tier: default`, `tools: read-only-scoped`,
`context: first-review-only-v1`. `settings_hash` hashes those settings. The same
settings apply to both arms; this does not change live reviewer model policy.

Each named stage is `{status, artifact_hash, source, at}`. Status:
not_run/partial/pass/fail/stopped/inconclusive. Not run has null hash/source/time;
all other states retain a hashed artifact, completion timestamp and provenance. A summary is not its
artifact and does not itself satisfy a predecessor gate. Weekly owners retain
separate stage states and cannot rewrite a running experiment for a new week.

## Assignments and deviations

Assignment: `{ticket, arm, assigned_at, work_started_at, revision,
preregistration_hash}`. Odd ticket gets candidate, even gets old. Ticket must
exist in the bound journey. Assignment follows protocol review and separate
live approval, precedes any known builder start, and is before the horizon.
`work_started_at` is null before work, or a timestamp no earlier than assignment.
Work start can be filled from null to a timestamp once after assignment; that
observation can never be reset or changed. Assignment identity remains frozen.
Revision equals the frozen arm; protocol hash equals `preregistration_digest`.
Research, CF4 and replay stages must pass; both CF4 references must pass and the
replay must select candidate. This is deterministic parity, not randomization.

Deviation: `{ticket, kind, material, source, actual_revision}`. Kind:
revision-change/overlap/other. Revision changes require actual commit/tree;
others use null. Record deviations rather than changing assignment or dropping
slow/failed/unmerged work. Material confounding prevents an improvement verdict.

`validate_transition` validates each checkpoint against its own explicit journey
snapshot (the fourth argument defaults to the third for unchanged snapshots).
It preserves frozen experiment and protocol identity, previous assignment identities and known work-start observations,
deviations, CF4 run records and source bindings. Known builder starts are retained by ticket number and resolved v1 journey source
URL, preserving their earliest observed time. Local event ids/source keys may
renumber; the prior source may not disappear or acquire a later start time. New
assignments are checked against both retained starts and current observations.
Known tickets/PRs, established
first-push receipts, verified merges and recorded defect evidence cannot
vanish or reset; follow-up coverage cannot regress. Unknown defect attribution
can gain a separate append-only sourced resolution; original observations and
resolution history remain intact. Receiving live approval is
the only permitted change within an existing protocol, and a granted approval
cannot be rewritten. New assignments/evidence append only. Completed stage
references and terminal results, including harm/stops, remain immutable.

Replay input, cohort, rubric, history and review output hashes are frozen;
scoring adds arm-blind adjudication checkpoints without rewriting review output.
Complete/error/uncertain attempts cannot silently retry. A terminal replay report
is frozen once completed; new candidates start a separate experiment.

## Complete preregistration

Protocol has `registered_at`, `eligibility`, `primary`, `power`, `guards`,
`horizon`, `confidence`, `stopping`, `method_review`, `live_approval`,
`experiment_hash`, `cf4_refs`, `replay_hash`.
The experiment hash binds the exact repository, arms, revisions and frozen
inputs; the replay hash binds its completed candidate selection and CF4 refs.
Passed research and compatible CF4 evidence must predate replay start;
explicitly failed/unrun research cannot be replaced by a passing CF4 result.
Completed predecessor evidence must predate registration, review, approval and
assignment. A protocol cannot reuse an approval for a different candidate.
Eligibility and actual primary `statistic`, `test`, `unfinished`, `missing`
choices are nonempty. State exclusions, censoring, closed-unmerged handling,
missing timing and sensitivity analysis explicitly. Review the actual methods;
a validator cannot establish their statistical suitability from prose.

Power fields: `method: normal-mean-planning-v1`, `alpha`, `power`,
`effect_hours`, `baseline_sd_hours`, `baseline_n`, `baseline_unknown`,
`baseline_source`, `z_alpha`, `z_power`, `time_n_per_arm`, `min_n_per_arm`,
`assumptions`. Alpha/power lie strictly between 0 and 1; effect/SD are positive;
observed baseline n >= 2. Critical values must match the probabilities. This is
an explicitly labelled equal-variance normal planning approximation:

```text
z_alpha = Phi^-1(1-alpha/2); z_power = Phi^-1(power)
time_n_per_arm = ceil(2 * (z_alpha + z_power)^2 * SD_hours^2 / effect_hours^2)
min_n_per_arm >= max(time_n_per_arm, rounds minimum, defects minimum)
```

Each `guards.rounds`/`guards.defects` contains actual `test`, `margin: 0`,
positive `max_interval_width`, `min_n_per_arm >= 2`. The method reviewer checks
those numeric precision requirements and limitations for both guards, including
rare/zero events, not only the time approximation. A flat 15 merges is no rule.
Fixture arithmetic gives time n = 36 and guard-driven minimum = 72 per arm;
it is an invented example, not a reviewed live design or permission to launch.

Confidence equals 1-alpha. Horizon is fixed after registration. Stopping has
`main_red: any-attributable-event`, `rounds_multiplier: 2`, positive
`rounds_reference`, `reference_source`, positive `window_hours`, positive integer
`minimum_exposed`, `efficacy_peeking: false`. Doubled rounds means the mean
independent rounds over the predeclared rolling window against that fixed
reference, with the required exposure count. Both calculations are frozen;
stop on harm, never on a favorable interim estimate.

`method_review: {at, source}` follows registration. `live_approval` has
`status: granted|not_granted`, `at`, `source`; not granted has null evidence.
Granted follows method review. Approval is separately verified and bound to the
completed protocol; `preregistration_digest` excludes only this approval field,
so receiving approval cannot mutate the frozen analysis. Implementation/graph
approval never substitutes. Missing/unsuitable methods or inadequate guard
precision keep live work blocked under EB8 even if a JSON shape conforms.

## Uncertainty-bearing live results

Result: `{at, preregistration_hash, status, verdict, samples, effects, stops}`.
Status complete/stopped/inconclusive; verdict improved/harm/inconclusive.
Inconclusive status requires an inconclusive verdict; stopped requires harm and
stop evidence. Complete means a finished analysis, which may still be inconclusive. Each
arm's sample records nonnegative integers `assigned`, `merged`, `open`,
`closed_unmerged`, `unknown_timing`, `mature_defects`. Assigned equals the immutable
assignment count and merged + open + closed-unmerged; unknowns cannot disappear.
EB8 must verify observed categories against journey facts and estimate the
preregistered censoring/sensitivity analysis, not a completion-only average.

Effects time/rounds/defects each contain `{unit, old, candidate, delta, percent,
interval}`. Units hours/rounds/proportion, respectively. Delta = candidate-old;
percent = 100 × delta/old (null at a zero baseline). Interval is two finite bounds
containing the estimate. All five value fields are null for an unknown effect.
Defect rates lie in [0,1]. The downstream estimator owns interval calculation;
this validator checks shape, units, arithmetic and conservative decision bounds.

Improved requires a time interval wholly below zero, both guard intervals with
upper bound <= zero and width <= their frozen bounds, minimum samples, no timing
gaps, mature merged follow-up, and no material confounding. Guard harm with an
interval wholly above zero is retained. Missing/immature/underpowered/wide
results stay inconclusive; no significant harm is not a safety proof. Without a
safety stop, analysis cannot precede the horizon. EB8 must also prove that sample
coverage, actual methods and all assigned outcomes support those summaries.

Stops contain `{kind, arm, at, source, exposed, observed}`. Kind is main-red or
doubled-rounds; observed is attributable event count or the window's independent
round mean, respectively. Exposure cannot exceed assigned tickets at that time.
A main-red stop needs >=1 attributable event; the other needs minimum exposure
and observed >= 2 × reference (inclusive). Stops force stopped/harm. EB8 owns
source verification, window aggregation, event deduplication and safe resumption.

## Usage and proof limits

Each row is `{scope, provider, unit, status, value, coverage, attribution, source,
gaps}`. Scope old/candidate/total; provider codex/cloudroom/openrouter; units are
Codex tokens, CloudRoom credits/usd/sandbox_hours, or OpenRouter tokens/usd.
Every bundle lists Codex tokens and CloudRoom credits for both arms and total;
other included units also list all scopes, except sandbox hours, total only.
No field converts tokens, credits, money or time into one another.

Status known/unknown/unattributed/absent; only known has a finite nonnegative
value and source, with integer tokens. Coverage complete/partial/none;
attribution direct/shared/unavailable. Non-complete coverage has explicit gaps
from missing-export/shared-sandbox/no-attribution/not-run. Complete has none.
A known partial value is a lower bound. Shared usage is total only; never split
sandbox cost equally between arms. Totals cannot understate observed arm usage;
unknown totals stay unknown. Evidence exporters and attribution identities stay
outside repository artifacts. CF4's unrelated paid usage remains its own spend.

The fixtures prove compatibility, shapes and refusals, not real timing, catches,
model quality, savings or live safety. The independent interface review covers
all downstream seams; independent exact-head review and CI still gate merge.
