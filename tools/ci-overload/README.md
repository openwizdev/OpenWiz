# Queue and API overload guard

CS5's finite observer reads one bounded snapshot of the orchestrator's existing
queue and rate-limit reads. It makes no network call, starts no controller,
cancels nothing and sends no message. Fixture results establish offline policy
only; C13 (#2320) owns the separately authorized live observation.

```sh
python3 -I tools/ci-overload/alarm.py --repository synthetic-owner/synthetic-repo \
  --input /absolute/private/observation.json --state /absolute/private/pause.json \
  --action merge-batch
```

The output is one JSON decision. Exit 0 admits that action, 1 refuses it, and 2
means invalid invocation. Errors never print input bodies, API responses or
credential material. `allowed` supplies no review, merge, messaging or live
authority. Every existing hold, required check and admission rule still applies.

## Inputs and source completeness

`fixtures/healthy.json` is the synthetic input example. An observation contains
exactly `repository`, `observed_at` (Unix seconds), `complete`, `queue` and
`budgets`. Objects reject duplicate/extra keys and wrong types. Reads are bounded
to 2 MiB and 10,000 jobs; exceeding either bound is unknown, never empty.

The caller normalizes its existing complete queue reads: `queue.complete` must
cover every current required job across all pages, runs and current attempts,
not just the first page, newest run or one runner pool. `jobs` has unique,
nonempty synthetic-style opaque ids, `required` booleans, `status` (`queued`,
`in_progress`, `completed`), `queued_at` and nullable `started_at`. Requiredness
comes from the existing required-check/selection inputs; a missing receipt is
not evidence that a job is optional. A queued job has no start timestamp.
Running duration never counts as queue waiting.

`budgets` contains both `rest` and `graphql`: each has `remaining`, `limit`,
`reset_at` and `retry_after` (an absolute backoff deadline, zero if none). These
are the actual shared budget pools for the reads, never per-agent allowances.
Keep primary reset and secondary Retry-After/backoff evidence from the existing
reader. A crossed reset requires a fresh observation; it does not refill quota
by arithmetic. Unknown backoff cannot be represented as zero.

`observed_at` covers all component reads; the caller must mark incomplete if a
page, required-job classification, budget or backoff could not be established.
Inputs must be current and repository-bound. The default maximum age is 60
seconds; `--max-age` lets the existing caller supply its freshness bound. This
is an input-validity check, not a new resume threshold. A caller assertion of
completeness is not authenticated live evidence. This ticket adds no API
collector, credential profile, transport or new schema to the fleet contracts.

## Decision and durable pause

| Observation | Decision |
| --- | --- |
| Oldest required queued job waits at least 300 seconds | alarm and pause |
| Either pool has remaining/limit strictly below 10% | alarm and pause |
| Oldest required queued job waits at least 900 seconds, or either pool is exhausted | escalation due and pause |
| Either pool has an active secondary backoff | alarm and pause |
| Missing, stale, partial, invalid or unreadable input/state | unknown and pause |

A known alarm/escalation survives an independent incomplete component; unknown
data never establishes healthy clearance. Waits use the oldest required queued
job across the complete input. Exact 10% alone is healthy; exact 300/900 seconds
triggers the corresponding threshold.

The state records the repository, pause start, cause, observation time and
evidence digest. Before taking the nonblocking state lock, each nonhealthy
observation atomically publishes an owner-only, fsynced record in
`<state>.pending/`. This journal retains triggers even when the lock is busy.
Every admission incorporates the journal under the state lock, preserving the
first trigger and upgrading only to a more severe trigger. It removes only
incorporated records after the pause's atomic, fsynced replacement; a crash
leaves either the journal or the durable pause. A later healthy snapshot cannot
erase either. Keep the journal alongside the state across restarts.

Journal input is bounded to 10,000 records and 2 MiB in total. Excess,
corrupt or unreadable records retain the journal and refuse new work, as does
corrupt state. Failed persistence or a busy lock also refuses. Nonregular
inputs are unknown; the guard never waits on a pipe or another invocation's
lock. Essential actions remain available on all these refusal paths.
Use one stable private state path per repository across orchestrator/fleet
invocations. The state must survive process and host restarts; never store the
only copy in a temporary directory. Provision its parent privately.

`merge-batch`, `automatic-refresh` and `nonessential-poll` are refused while
paused. `completion` and `reconciliation` remain allowed, including when data or
persistence is unknown, so admitted jobs and agents can finish. Those allowances
do not create fresh batch/refresh/poll authority. Keep their reads necessary and
bounded and honour the underlying reader's reset/backoff; no busy waiting.

There is **no resume/reset command and no automatic resumption**. Bring the
resumption disposition to Jake before enabling any resume path. Do not delete
or substitute the state to clear a pause.

`escalation: due_not_sent` means only that escalation is due. The orchestrator
uses its existing escalation channel only under its separate messaging authority.
Transport acceptance, recipient acknowledgement and work completion are separate
evidence. No delivery or acknowledgement is inferred here, and private response
payloads stay private. Offline tests never send a page.

## Proof

`python3 -I tools/ci-overload/test.py` owns the observer and fleet-action boundary
proofs. `python3 -I tools/ci-overload/test.py Fleet Scheduled` runs the fleet
slice, including source and bundled scheduled entrypoints. `loop.sh` checks
`automatic-refresh` before clone/fetch/checkout, then rechecks `nonessential-poll`
before its broad fleet read. Both checks use the invoking installation or pinned
bundle's observer and the same supplied observation/durable state; missing setup
refuses without an ungated fallback. The bundle retains its own observer after
the installation disappears or consumer helpers change. Necessary bounded
completion/reconciliation uses the existing `fleet.sh overload` action path and
is not a scheduled broad poll. Existing CI registers the complete suite as
`release:ci2-overload`, with planner and executor proofs for discovery and failure propagation.

Red-run summaries are committed before their fixes in this ticket's proof
commits. C12 (#2319) consumes the same `merge-batch` admission decision and
durable pause; C13 consumes the thresholds, recorded causes and honest
unsent-escalation result. No live overload or successful notification is claimed.
