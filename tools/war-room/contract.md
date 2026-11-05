# War room record and suite contract v1

WR1 (#2345), spec #2340. `openwiz.war-room.v1` is one complete snapshot
envelope over existing benches, **not** a new collector or source authority.
Only synthetic/offline preparation is proved here. Source availability,
complete history, five-minute operation, private hosting and live results remain
Unverified. No schedule, endpoint, deployment, publication, access rule, paid
evaluation, stage setting, recovery action or additional benchmark is supplied.

## One boundary

`suite.py` uses Python's standard library. Public calls:

- `compose(sample_at, providers=(), *, assembled_at=None) -> dict`: takes already
  projected provider objects, fills every missing slot with its explicit
  unavailable stub, validates the entire envelope and returns an independent
  copy. It invokes no provider and reads no source artifact.
- `validate(record) -> None`: strict shape and semantic check; raises
  `ValueError` on refusal. Does not mutate its input.
- `loads(wire) -> dict` / `load(path) -> dict`: strict JSON plus validation.
  Duplicate keys at every depth, nonfinite constants and overflowing numbers
  refuse. No key normalization or silent last-write-wins behavior.
- CLI `check PATH` (or `check -` for stdin) prints the validated snapshot, exits
  0; invalid/unreadable input exits 1 with sanitized stderr and no stdout.
  `compose --at UTC_TIME [--assembled-at UTC_TIME] [--providers PATH]` reads only
  an explicit local array of projected provider objects. Bad arguments exit 2.
  Neither command saves history, runs tools, uses a clock or opens a socket.

`record.schema.json` is the structural JSON Schema (draft 2020-12). Its
`x-providers` registry is the authoritative slot order, allowed groups and
default readiness prerequisites used by composition. The stdlib checker
evaluates the schema's local references, nullable alternatives, exact objects,
types, enums, constants, patterns, array bounds/uniqueness and numeric bounds.
Schema conformance alone cannot prove cross-field identities, calendar dates,
source freshness, coverage or arithmetic; **always call `validate`**. Neither
checker verifies the bytes or truth asserted by a source hash/evidence link.
Adapters must first use the existing source's own validator and verify its
artifact binding; the suite does not parse native source records again.

## Fixed presentation and named slots

The envelope has exactly `schema`, `sample_id`, `sample_at`, `assembled_at`,
`groups`, `providers`. All objects at every depth require their declared
required keys and refuse undeclared keys. Only a metric's documented `rounding`
field is optional. Groups are always in this order, even with no observations:

| Group | Contents |
| --- | --- |
| `throughput` | Hour/day merged PRs by forward/sideways/backwards direction |
| `stage_waits` | Observed waits, source-owned limits and ticket-linked misses |
| `board` | Existing board measures and bench inventory/readiness, including rework |
| `ci` | Current running/queued jobs per exact pool, cost today and cost readiness |
| `usage` | Credits and Claude usage, separately by provider/unit/window |
| `decisions` | Sanitized pending decisions and answer-latency readiness |

Every snapshot includes these slots **once in the registry order**. An absent
provider is unavailable, has nonempty prerequisites and an empty metric list;
this is a visible grey bench, never a successful empty result.

| Slot | Source / later owner |
| --- | --- |
| `activity` | Existing CI/factory/board projection, WR8 #2352; throughput and current CI |
| `stage_waits` | Actual merged TL1/TL2 contracts, WR3 #2347 |
| `board` | Existing plan-links graph/measures/history, WR2 #2346 |
| `ci_bench` | Existing points/trends, WR2; completed-window capacity/timing and list-rate estimates |
| `factory_metrics` | Existing daily factory artifacts, WR2; UTC all-base-branch merge/usage semantics |
| `journey` | Validated existing journey/bench artifacts, WR2; incomplete history stays explicit |
| `skills_eval` | Existing manifests/scores/coverage, WR2; no eval is run |
| `cost` | All-in merged-PR cost readiness, WR4 #2348 |
| `credits` | Existing board credit samples/history, WR2; partial samples stay partial |
| `claude_usage` | Existing usage artifacts or owner-supplied day export, WR2; no assumed endpoint |
| `decisions` | Structured decisions discovery, WR2; no raw questions/replies or answer action |
| `answer_time` | Source-linked substantive dispositions, WR5 #2349 |
| `rework` | Journey independent nonduplicate review/fix facts, WR6 #2350 |
| `eb6` | #2177 sourced first-push timing/defects, awaiting actual measured artifacts |
| `eb7` | #2178 frozen-cohort paired replay, awaiting actual result and separate gates |
| `eb8` | #2179 bounded live experiment, awaiting separate go-ahead/result |
| `eb9` | #2192 huntr/settings A/B, retained hold and separate artifact gates |

These inventory stubs assert no status change for those owners. WR2 renders
generic metrics/readiness even before WR3–WR8 exist. Later owners supply their
slot through `compose`; adding projected metrics within an existing slot does
not change the envelope version or require a new page/collector. No raw native
record or arbitrary extension object is accepted. A truly new bench/interface
outside the confirmed eight points requires a decision.

## Every displayed value

Each metric carries `id`, `group`, `label`, `state`, `value`, `unit`,
`native_unit`, `statistic`, `window`, `observed_at`, `fresh_until`, `freshness`,
`source`, `evidence`, `sample`, `dimensions`, `interval`, `prerequisites`.
An optional `rounding` field declares source-owned ratio arithmetic (below);
omission means `exact`, without rewriting the record or source value.
The schema fixes all nested fields/types. Metric ids are unique within a slot;
the full series identity is `(slot, id)`. Preserve its meaning, unit, statistic,
dimensions and source-window basis across samples; changed basis is a new
series or an explicit noncomparable history, never an apparent speedup.

- Units are explicit: count, hours, minutes, seconds, USD (`usd`), credits,
  tokens, sandbox hours, ratio, percent, USD/merged PR, PRs/hour, robot-minutes/code-run. The
  adapter preserves the native unit in both unit fields; the suite refuses a
  mismatch and performs no conversion or cross-unit sum. CI capacity is not
  observed merged throughput. CI list prices remain estimates, not invoices.
- `window` is the half-open native source interval `[since, until)` in UTC
  timestamps, with `timezone` preserving `UTC` or `PST-fixed-UTC-08:00`. Never
  relabel a UTC daily usage ratio as a PST day or an hour. `observed_at` is the
  actual artifact/source read bound, at/after window end, never assembly time.
- `source` pins a sanitized repository-relative artifact path, native schema
  identity and SHA-256. `evidence` contains source links (GitHub issue/PR,
  comment, run or commit); references are assertions for independent checking,
  not authority. No raw comments, transcripts, credentials, runtime/thread ids
  or usage keys belong in any field. Producers must sanitize their labels,
  prerequisites and identities; page consumers still escape all untrusted text.
- `sample` names observed/expected cohort sizes, unique sanitized observation
  identities, and nullable numerator/denominator. Observed equals identity
  count. Unknown expected coverage is null. Ratios with numeric values require
  a nonzero denominator equal to observed and the independently checkable
  quotient, with only the source rounding explicitly declared below (times 100
  for percent). A `ratio` statistic in native `ratio` units is a general ratio:
  its integer numerator can exceed the denominator, as ready stock can exceed
  running builders. A `proportion` statistic in `ratio` or `percent` units has
  an integer numerator <= denominator. Percent values are always bounded
  proportions, including the existing `ratio` statistic with `percent` units.
  `usd_per_merged_pr` uses a numeric USD numerator and a merged PR denominator,
  with the `ratio` statistic. WR4 owns that allocation and derived source value;
  the suite only checks its quotient, with no conversion of credits or other
  units. Median/p90 cannot have an empty observed distribution. This is coverage,
  not a confidence score.
- `rounding` applies only to `ratio`/`proportion`. `exact` (the default) retains
  quotient validation; it cannot accept a rounded replacement as an exact
  value. `half_up_0` applies only to `percent` and validates a whole percent
  rounded half up. `half_up_1` applies only to native `ratio` units and validates
  one decimal rounded half up. Both use the source numerator/denominator and
  exact integer remainders, including ties; no broad tolerance is added to
  admit rounded results. Unknown modes, a mode on another statistic and
  incompatible mode/unit combinations refuse. USD-per-PR remains exact.
  A producer may declare rounding only when its source contract specifies it,
  never to excuse a mismatched value or alter the source basis.
- `dimensions` keeps direction, exact source pool, source stage, ticket and
  cohort separate; each is nullable when inapplicable. Direction unknown is not
  assigned to another direction. Pools/stages are source-owned names, not an
  inference from a runner or an invented TL stage vocabulary. Ticket-linked
  misses are individual metrics with a ticket and source evidence; limits,
  observed waits and miss counts have distinct ids/units, not a composite score.
- `interval`, when available, names one stable native wait/answer observation
  with source-backed start/end. Unknown/open endpoints are null and cannot be
  known complete. This is a **War room projection**, not a declaration of TL2
  native fields. Each populated endpoint requires `observed_at` and must be at
  or before it; later assembly cannot establish a later source event. Ordering
  and open/null rules still apply. The same native interval id survives repeated
  snapshots.

Native board projection examples from `contracts/plan-links.v1.md` preserve the
source's values and counts; no adapter is implemented here:

| Measure | Numerator / denominator | Unit | Statistic | Rounding | Value |
| --- | --- | --- | --- | --- | --- |
| Fed ratio | 3 ready / 1 running | `ratio` | `ratio` | `half_up_1` | 3.0 |
| Fed ratio | 1 ready / 3 running | `ratio` | `ratio` | `half_up_1` | 0.3 |
| Startable percent | 2 startable / 3 approved | `percent` | `proportion` | `half_up_0` | 67 |

The source's zero-denominator result stays unavailable/null, never zero. A share
such as rework uses `proportion`, not the unbounded stock-ratio semantics.

`known` requires a numeric value, complete expected/observed sample coverage,
source/window/time/evidence and no unmet prerequisites. An explicit sourced
known zero is allowed. `partial` requires prerequisites and can retain a
labelled numeric lower bound or null total; it never implies full coverage.
`unavailable` requires null value and prerequisites. A provider's state cannot
hide incomplete metrics: known needs nonempty all-known metrics; partial needs
prerequisites and at least one non-unavailable metric with a source, observation
time and nonempty evidence; a partial label alone is not an observation.
Unavailable cannot contain available metrics. A sourced zero observation or
sourced partial/null total remains valid; a wholly unobserved provider must use
explicit unavailable states.
Malformed supplied providers refuse the whole composition. A source failure
must be projected explicitly as partial/unavailable; omission never means zero.

Freshness is separate from numerical knowledge. `fresh_until` is nullable and
must come from the selected source's validity contract, not a new suite timeout.
With no validity bound, freshness is unknown. Otherwise it is fresh through
that bound, stale afterwards; the validator checks against `assembled_at`.
Known historical values may remain saved when stale, with their old observation
time. Stale/unknown freshness must be labelled (grey for unavailable current
observations), never shown as a current complete count or silently refreshed.

## Conservative category prerequisites

- **Stages:** WR3 waits for **both verified merges** of #2336/#2337, reads their
  actual contracts and consumes measured waits and loaded limits. WR1 supplies
  no TL2 native field names, limit numbers, timers, settings or recovery logic.
- **All-in PR cost:** complete, nonduplicated USD allocation to one named
  merged-PR cohort, including shared-parent work, helpers, sandbox and CI, is
  required. Each component is counted once. Missing/unallocated parts or no
  merged denominator leave all-in Unknown. Daily usage/merge ratios, journey
  thread-record lower bounds and CI estimates remain separately labelled;
  credits/tokens/hours cannot become USD. No allocation rule is invented here.
- **Answer time:** a recorded request starts the interval; only an independently
  sourced, linked substantive orchestrator disposition ends it. Sent/accepted
  notifications, removed needs-info and resolved JSON status alone are not
  evidence of an answer. Open, edited/deleted or unprovable intervals remain
  censored/Unknown with coverage. Reuse TL2's fact when it is the same interval.
- **Rework:** use validated journey independent, nonduplicate CHANGES and fix
  rounds once per PR, with a named merged cohort and reviewed coverage. Missing
  reviews never mean first-pass success. CI reruns remain separate CI rework.
  CF4/finding semantics and all correction counters remain source-owned.

These are provider admission obligations, not computations WR1 implements.
The generic validator checks the record/denominator, not the provenance truth
of an all-in allocation, substantive disposition or independent review.

## Five-minute persistence seam (WR2)

`sample_at` and `sample_id` are the same canonical UTC boundary, second zero
and minute divisible by five. WR2 floors its injected tick time to this boundary;
assembly is at/after it. Sampling identity never replaces native source times.
One repository's selected history has one immutable record per sample id.

WR2 must validate the **entire** envelope before atomic create-if-absent
persistence; publish no subset of its metrics or partial file. Complete snapshot
means a structurally complete envelope, including all explicit unavailable
states, not a claim that all sources are ready. Identical duplicates are
idempotent; a differing payload for an existing id refuses, never overwrites.
Out-of-order new samples cannot regress the latest pointer. Interrupted writes
leave no readable sample. Retain historical samples/gaps and last good evidence;
do not synthesize missing samples or change old timestamps. Persistence,
concurrency, crash and restart behavior belongs to WR2, not this validator.

## Weekly history seam (WR7)

Use two adjacent **nonoverlapping seven-day stage cohorts**, ending at the end
of the latest complete fixed-PST day: `[end-14 days, end-7 days)` and
`[end-7 days, end)`. Fixed PST boundaries are 08:00 UTC; retain source UTC/PST
labels. Assign each completed native stage interval once by its source-backed
end, deduplicate its identity across five-minute snapshots; open/censored waits
and unknown endpoints are reported separately, never completed zero waits.

Expected retained five-minute samples are 2016 per seven-day week, distinct
from the number of independent intervals. Report observed/expected sample/day
coverage and per-stage observed/expected interval counts where ascertainable;
unknown expected intervals are null. Missing samples/history remain gaps, never
healthy zeros. Compare only compatible units, limits, source windows and stage
basis, with sample sizes. Changed limits/basis, thin cohorts or incomplete
history cannot produce a confident faster/slower claim. Do not add a new
minimum-sample policy or threshold; reuse the selected source's comparison
semantics and show their limitations. Recorded changes retain source links
beside timing comparisons, with no causal claim. WR7 owns comparison arithmetic
and any deduplication proof after the actual TL producers are available.

## Synthetic proof

`fixtures/contract/known.json` has 3 PRs in a UTC hour; `partial.json` adds a
two-of-four reviewed cohort whose overall rework value is null;
`unavailable.json` contains only named grey stubs. All dates, paths, links,
hashes, source schemas, identities and observations are synthetic assumptions;
the repeated hashes assert no real source bytes or capability. No fixture is a
live observation. `test_contract.py` owns the boundary cases and CLI round trip.
`red-first.log` records the missing seam before its implementation commit.
`review-1-red.log` records R1–R4 before their corrections: native board ratio and
rounding support, source-bound interval endpoints and observed partial readiness.
