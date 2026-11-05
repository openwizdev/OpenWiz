# Scale report v1 (`openwiz.scale-50.v1`)

Interface for #1228's baseline, #1229–#1231's comparisons and #1237's final proof.
`report.py REPORT [--compare CANDIDATE]` validates aggregates and refuses
incompatible comparisons. It executes no work. Python standard library only.
`fixtures/report-v1.json` is a literal example; `fixtures/workload-v1.json` fixes
the synthetic workload and its bounds.

## Identity and evidence

Objects have exactly the keys the reader lists, each once. JSON integers exclude
booleans; measurements are finite and nonnegative. Unknown schema, extra/missing/
duplicate keys, NaN and Infinity are errors. No account data, raw live responses,
tokens, prompts or real thread identifiers belong in reports.

| Field | Contract |
| --- | --- |
| `schema` | `openwiz.scale-50.v1`; incompatible changes require v2 |
| `evidence_class` | `fixture` or `live`; never compare across classes |
| `state` | `complete`, `partial`, `unknown`: describes stated route measurements, never live success |
| `workload` | `id`, SHA-256 `sha256` of exact workload bytes, integer `tickets`/`specs`, `arrival`, `role_policy` |
| `measurement_model` | `{files,sha256}`; consumed measuring/executor source hashes, distinct from the candidate; null only for partial/unknown evidence |
| `candidate` | Source/content identity `revision`, tool/version identity `tools`, configuration identity `config`; nonempty strings |
| `bounds` | Integer seconds `max_wall_s`, `virtual_duration_s`, `quiet_s`, `merge_s`; integer `max_active`, independent `rest_limit` requests/hour and `graphql_limit` points/hour |
| `coverage` | Nonempty list of `{route,mode,tickets,gaps}`; identify installed tick and active follower separately |
| `window` | Absolute integer epoch seconds `start_s`, `end_s` exclusive, ordered disjoint `active_intervals` |
| `gaps` | Explicit missing observations; required for partial/unknown; missing evidence grants no permission |

An interval is `{start_s,end_s,builders,reviewers}` on `[start_s,end_s)`, after
all recorded events at start. Counts come from explicit **recording-executor**
execution transitions: running receipts or later queue admission start an interval;
PR/fix/CI/verdict completion ends it. Accepted queued receipts and idle agents do
not count. A FIFO fixture scheduler admits at most 50 running agents across roles.
This is neither CPU utilization nor live LLM overlap. Both roles and a positive
interval at 50 must be observed. No product concurrency cap is introduced.

## Measurements and boundaries

`metrics` has exactly these fields:

| Field | Units and boundary |
| --- | --- |
| `tick_ms` | Wall milliseconds from subprocess launch through reap of `fleet.sh spec`; excludes follower actions, installed tick and builds |
| `starts` | Integer `{attempted,accepted,uncertain,refused}`; reconciles exactly; recording receipts never prove live execution |
| `event_action_s` | Virtual seconds from lifecycle eligibility to recorded action, including fixture admission waits |
| `review_queue_s` | Virtual seconds from PR with green CI to first reviewer execution, excluding queued receipts |
| `recheck_delay_s` | Virtual seconds from fixed head to reviewer execution after re-check |
| `merge_delay_s` | Virtual seconds from exact-head APPROVE/green CI to confirmed merge read-back |
| `ci_wait_s` | Virtual seconds from failed-CI PR opening to passing CI transition, separate from queues |
| `review_backlog_peak`, `recheck_backlog_peak` | Maximum eligible tickets awaiting corresponding action at any event boundary |
| `verified_merges`, `completed` | Confirmed merge/read-back count, never closed issues alone |
| `merges_per_hour` | Verified merges × 3,600 / observation seconds, including drain/idle ticks |
| `requests_per_ticket` | Underlying REST + GraphQL requests / completed tickets |
| `graphql_cost_per_ticket` | GraphQL points / completed tickets |

Duration distributions are `{p50,p95,samples}`, nearest rank
`sorted[ceil(n*p)-1]`, samples > 0, no interpolation. Wall samples vary between
reruns; literal fixtures and virtual lifecycle results do not. Absent distributions
are `null` only in partial/unknown reports with a gap. Zero is an observed zero.

Timing comes from fake transitions/effects. Quiet agents must be noticed within
1,800 virtual seconds; the merge bound is also 1,800 s. Explicit waits and
low-budget pauses stay visible. Repeated serialized spec wakes do not prove
overlapping claim elections.

## HTTP accounting and budgets

`budgets.rest`: `{requests,shared_requests,limit,remaining,reset_s}`.
`budgets.graphql`: `{requests,cost,shared_cost,limit,remaining,reset_s}`.
Counts and points are distinct integer units; reset is epoch seconds.
`live_limits` is `unknown` for fixtures. Limits/remaining describe only the
synthetic credential scope, never an assumed GitHub token allowance.

The transport records each page emitted by the existing fake, including internal
`gh api --paginate` pages. Revision `issue view` has explicit synthetic internal
GraphQL pages (7 items/page). CLI writes have explicit resolution/mutation
exchanges. These are executor assumptions, not observations of real gh internals.
Conditional reads still count. Page completeness uses fixture response cardinality
before expansion; deleting a recorded page fails.

Shared consumers emit REST requests and GraphQL cost every virtual tick without a
CLI call. Independent fixed reset-hour budgets include all consumers and writes.
Totals cover the run; remaining subtracts use in the final reset window. FA3's
original rolling 1,250-point guard stays as an additional independent check with
its original accounting. Synthetic headroom cannot establish live primary or
secondary limit safety. Retries are zero; uncertain/refused recovery is unexercised
and disclosed. Installed internal HTTP traffic is outside follower accounting.

## Comparison

Validate both reports; require complete measurements and identical schema,
evidence class, workload (hash/arrival/roles), bounds, measurement model and coverage. Reject changed
workload, missing observations or loosened limits. Candidate source/tools/config
may differ; expose all identity changes. Return tick p95-ms, REST-request and
GraphQL-cost deltas; other metrics remain in each report. No combined allowance or
synthetic-to-live speedup. Disclose topology/CI differences in config and gaps.
A fixture report cannot establish S1 live or S5 capacity, regardless of its state.

Additional metrics in v1: `accepted_starts_per_minute` is accepted receipts × 60 /
observation seconds. `http_per_tick` contains `rest_requests`, `graphql_requests`
and `graphql_cost`, each a nearest-rank distribution over spec checks including
that spec's follower writes at the same virtual time. Setup/revision traffic and
shared consumers are included in run totals, separately from these per-spec tick
distributions. Unknown budget values may be `null` only in partial/unknown
reports; a zero never stands in for an unavailable allowance. `live_limits` is
`observed` or `unknown`, and fixtures require `unknown`.

The trace freezes workload bytes/hash, bounds, source/installed-binary identities,
tool hashes and configuration before lifecycle execution. Replay uses only that
snapshot; it never substitutes the checkout's current workload or tools. A
complete report is emitted only after both FA3's original guards and the scale
checks pass. Complete reports require positive mixed-role target overlap;
partial reports retain missing observations. Comparisons additionally require the
same observation duration. All request events fall inside the exclusive window;
this workload observes 30 full 600-second cycles, including the final idle cycle.

Concurrent duplicate event wakes run through the real `fleet.sh wake` reader at
cycles 0 and 3. Their measured subprocess intervals must overlap. They defer to
the owning fleet; the timer performs lifecycle actions. This does not establish
concurrent claim/write safety. Ticket 1004 is externally held for the first
600 virtual seconds and cannot start until its fixture release. This external
fixture arrival changes only private fake state and performs no live label edit.
Shared charges must occur once per virtual cycle with the declared REST/GraphQL
mix; omission fails even when command offsets stay unchanged.


`measurement_model.files` maps relative repository source paths to lowercase
SHA-256 digests. Its `sha256` is SHA-256 of the UTF-8 JSON file map encoded with
sorted keys and compact separators (`,` and `:`). Missing, empty, malformed or
inconsistent model data cannot yield a complete report. The captured sources
include all load harness Python files, the reused `scripts/fixtures/gh.py` and
`revision.sh`, B5 executor, fixture CLI entrypoints and aggregate reader. These
bytes determine synthetic cost/page responses, approval reads and measurements.
A model change requires a new baseline; it is not an allowed candidate delta.
Candidate fleet-script and freshly built dispatcher identities may differ and
are reported separately. Runtime tool/config differences remain disclosed.

Legacy traces missing a model are replayable only as partial evidence with
`measurement_model: null`, never with a model reconstructed from today's files.
The checked-in baseline is regenerated from a new run with complete fingerprints.
The installed dispatcher is refreshed by the scoped incremental Cargo build on
every invocation, before selecting or hashing the example; build failure stops
execution rather than falling back to an existing artifact.

The installed seam selects the unique `openwiz` example executable from Cargo's
JSON `compiler-artifact` output, including configured target-triple directories,
and verifies it belongs to this checkout's explicit output directory. Missing or
ambiguous artifacts fail closed; an old guessed `target/debug` path is never used.
