# War room record contract v1 (legacy)

`openwiz.war-room.v1` is one complete five-minute snapshot over the existing benches. New snapshots are [v2](contract.v2.md), which keeps every rule here and adds `health`; saved v1 samples are never rewritten, and both read through `suite.validate` and `suite.load` (`suite.schema_of` names the version, `suite.health` shows a v1 sample's health as unobserved).

## The boundary

`suite.py`, Python standard library:

- `compose(sample_at, providers=(), *, assembled_at=None)` fills every missing slot with its unavailable stub, validates the envelope and returns a copy (now v2). It runs no provider and reads no source.
- `validate(record)` raises `ValueError` on any refusal. `loads(wire)` and `load(path)` parse strict JSON (duplicate keys, nonfinite and overflowing numbers refuse) and validate.
- CLI: `check PATH|-` prints the validated snapshot (exit 0, or 1 with no stdout); `compose --at UTC [--assembled-at UTC] [--providers PATH]`; bad arguments exit 2. Neither saves history, runs tools or opens a socket.
- `python3 -I tools/collector/test_contract.py` proves it on the synthetic `fixtures/contract/` snapshots.

`record.schema.json` is the structural schema; its `x-providers` registry is the authoritative slot order and default prerequisites. The schema can't check identities, dates, coverage or arithmetic: **always call `validate`**. Neither checks the truth of a source hash or link; adapters validate their source first.

## The envelope

Exactly `schema`, `sample_id`, `sample_at`, `assembled_at`, `groups`, `providers`, with no undeclared key at any depth. Groups, always in this order: `throughput`, `stage_waits`, `board`, `ci`, `usage`, `decisions`. Slots, each exactly once in registry order: `activity`, `stage_waits`, `board`, `ci_bench`, `factory_metrics`, `journey`, `skills_eval`, `cost`, `credits`, `claude_usage`, `decisions`, `answer_time`, `rework`, `eb6`, `eb7`, `eb8`, `eb9`. An absent provider is `unavailable` with prerequisites and no metrics: a grey bench, never an empty success. A new bench outside these slots needs a decision.

`sample_at` and `sample_id` are the same UTC five-minute boundary. History keeps one immutable record per sample id: validate the whole envelope, then create it if absent; an identical duplicate is a no-op and a different one refuses. Never synthesise a missing sample.

## Every metric

Fields: `id`, `group`, `label`, `state`, `value`, `unit`, `native_unit`, `statistic`, `window`, `observed_at`, `fresh_until`, `freshness`, `source`, `evidence`, `sample`, `dimensions`, `interval`, `prerequisites`, and optional `rounding`. `(slot, id)` is the series; keep its meaning, unit, statistic, dimensions and window basis across samples, or start a new series.

- **Units** are explicit (count, hours, minutes, seconds, `usd`, credits, tokens, sandbox hours, ratio, percent, USD per merged PR, PRs an hour, robot-minutes per code run). `unit` equals `native_unit`: no conversion and no cross-unit sum. CI list prices are estimates, not invoices.
- **`window`** is the source's half-open `[since, until)` in UTC, with `timezone` `UTC` or `PST-fixed-UTC-08:00`. `observed_at` is when the source was read, at or after the window's end, never assembly time.
- **`source`** pins a repository-relative artifact path, its native schema and SHA-256; `evidence` holds GitHub links. No raw comments, transcripts, credentials, thread ids or usage keys anywhere.
- **`sample`** gives observed and expected counts (unknown expected is null), unique observation ids, and numerator and denominator. A numeric ratio needs a nonzero denominator equal to observed and the exact quotient. `ratio` may exceed 1; `proportion` and every percent may not. `usd_per_merged_pr` is a USD numerator over merged PRs. Median and p90 need observations.
- **`rounding`** only on ratio or proportion: `exact` (default), `half_up_0` (whole percent) or `half_up_1` (one decimal of a native ratio), and only when the source contract says so.
- **`dimensions`** keeps direction, source pool, source stage, ticket and cohort apart, each null when it doesn't apply; unknown direction is never assigned.
- **`interval`** is one native wait or answer with source-backed start and end, each at or before `observed_at`; unknown ends are null and never complete.

**States.** `known` needs a numeric value, complete coverage, source, window, evidence and no unmet prerequisite (a sourced zero is fine). `partial` needs prerequisites and may carry a labelled lower bound or null. `unavailable` has a null value and prerequisites. A provider is `known` only with all-known metrics, `partial` with prerequisites and at least one sourced metric, else `unavailable`. A source failure is projected as partial or unavailable, never omitted. A malformed provider refuses the whole composition.

**Freshness** comes only from the source's own validity bound (`fresh_until`): fresh until then, stale after, unknown without one. Stale values keep their old observation time and are labelled, never shown as current.

**Weekly comparisons** use two adjacent seven-day cohorts ending at the latest complete fixed-PST day, each interval counted once by its end. Missing samples are gaps, not zeros; changed limits, bases or thin cohorts give no faster or slower claim.
