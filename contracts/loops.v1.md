# loops.v1

The definition of an OpenWiz loop and the record of one run. Schema:
[`loops.v1.schema.json`](loops.v1.schema.json), draft 2020-12, title and
`schema` field `openwiz.loops.v1`. The root accepts exactly one definition
or run record. LP1's contract half (#543); execution is not implemented by
this contract.

```text
definition -> wake -> limited check -> empty stdout: quiet
                                   -> nonempty stdout: shadow, defer, or agent
run record: identity + occurrence + check result + dispatch outcome + cost
```

This contract follows spec #541 and the confirmed 0.0.9 grill (PR #320,
`189a8d70a5269299312877c663d2e08b44abed71`, L1–L9). Run records are kept in
OpenWiz's private state directory, separate from the repository's definitions.
The always-on service that executed loops went in #1264; the pure planner
(`crates/core/src/loops/`) and `openwiz loop on|off` follow this contract. Check findings are never automatically
published to GitHub. The grill's L2 settlement leaves those record details
to the spec; its earlier unconfirmed summary is not a storage decision.
No publication or live action is authorized by this document.

## Reading the shape

All objects have exactly the schema's required keys, each once. Readers
reject duplicate keys before conversion to a JSON object; positional
arrays, additional keys, wrong types and unknown variants are refused.
Enums are plain strings. Nothing is silently defaulted. Times are
nonnegative integer milliseconds since the Unix epoch; durations are
positive integer milliseconds. No machine-local timezone is inferred.

`id`, `loop_id` and `op_id` reuse new-thread's 1–64 character ASCII op-id
shape. Names, owners, revisions, reasons and authority text must contain a
non-whitespace character and no NUL; they have no new length limit.
`definition_revision` identifies the exact immutable definition read
(e.g. its Git commit), not whichever version is now on the default branch.
A schema pass establishes structure, not approval or execution safety.

## Definition (`kind: "definition"`)

Definitions live in the project's default branch, one JSON file per loop
under `loops/`. An executor reads those definitions, not an agent's
unmerged proposal. IDs are unique within a project; changing the file name
keeps its identity when `id` stays the same. Duplicate IDs are an error.

| Field | Meaning |
| --- | --- |
| `schema`, `kind` | `openwiz.loops.v1`, `definition` |
| `id`, `name`, `owner` | Stable loop ID, display name, responsible owner |
| `wake` | One of the trigger objects below |
| `check` | `argv`: nonempty array of nonempty, NUL-free argument strings; `timeout_ms`: positive time limit |
| `action` | Explicit `project`, `harness`, `model`, `effort`, `brief` for the existing new-thread write |
| `authority` | `approved_by`, `approval_ref`, `scope`: who approved, where that approval is recorded, exactly what effects and targets it permits |
| `budget` | Positive `window_ms`, nonnegative integer `max_agent_starts` |
| `enabled` | Initial off/on state; `false` admits no checks or actions |
| `mode` | `shadow` runs the check and records what would act; `active` may dispatch within its authority and budget |
| `priority` | `normal` or `urgent`; the planner uses this for shared capacity reserved for urgent work |

### Wakes

| `wake.kind` | Other keys | Meaning |
| --- | --- | --- |
| `interval` | `every_ms`, `anchor_ms` | Due at `anchor_ms + n * every_ms`, for nonnegative integer `n`; positive period, nonnegative anchor |
| `once` | `at_ms` | One occurrence at this nonnegative time, including reminders |
| `event` | `event` | One GitHub event type: `github.pull_request_review`, `github.workflow_run`, `github.check_suite` or `github.issue_comment` |

These four types cover review, CI and comment routing. The fleet's
CloudRoom webhook also receives `issues` and `pull_request` lifecycle
events (see [fleet settings](../docs/agents/fleet.md#loop)); `github.issues`
and `github.pull_request` are not accepted by this version of `loops.v1`.
The loop contract is not the webhook's full subscription list. A loop
depending on either extra type cannot move in unchanged: supporting it
requires an explicit contract and reader change first.

The run's `wake` records the scheduled time as `due_at_ms` for interval and
once triggers, or the event type and stable `event_id` for an event trigger.
A late check keeps its original due time; wall-clock observation time is
not an occurrence ID. Duplicate deliveries keep the same event identity.
Missed-time admission, ordering and shared-limit planning belong to L2;
the record must retain the occurrence whichever policy admitted it.

GitHub event routing (L4) uses the fleet's ownership records to find the
builder or reviewer; it never treats a loop's `owner` display string as a
thread ID. A duplicate or late event must not repeat a settled effect;
unknown ownership returns to the fleet check-in. Receiving an event does
not authorize starting a replacement agent or guessing its destination.

### Check and action

The check runs in the checked-out project root, with each `argv` element
passed unchanged. There is no implicit shell; a definition that needs one
names it in `argv`. Checks decide whether work is due; agent effects belong
to the approved action. The time limit includes waiting for process exit
and reading output. A nonzero exit, invalid UTF-8, NUL output or a timeout
never starts an agent, even if stdout also contains text. Stderr is not a
wake signal and must not be copied into public status.

For an event wake, the signal means only "run the check now". The event
type, `event_id` and payload are not injected into the check's arguments,
environment, stdin or a file; stdin provides EOF. The check reads the
authoritative state it needs itself, within its approved scope, and prints
any context the action needs as its finding. The run's event identity is
occurrence bookkeeping, not an implicit check input. The action prompt
receives only the brief and finding described below, with no separately
injected event identity or payload.

Stdout is limited to 16 KiB (16,384 bytes), including in shadow mode. The
executor reads at most that limit plus one byte to detect excess; excess
output stops the check as `check_failed`, with no finding stored and no
agent started. It need not wait for exit or EOF to reject excess output.

On a successful exit, zero stdout bytes means `quiet`. Any nonempty valid
stdout, including whitespace, means work; it is the run's `finding`.
Shadow records that finding without dispatch. A disabled loop admits
nothing new; off does not undo an effect or kill an existing thread.
Runtime off/on state is durable in OpenWiz's private state and must survive restarts
and default-branch refreshes; `enabled` initializes a previously unseen
loop. L6's off/on writes operate only on these OpenWiz loop identities.

The action reuses [`new-thread.v1.schema.json`](new-thread.v1.schema.json):
`project` is its project reference, the three settings are its `setting`,
and `brief` is its prompt text (nonblank, no NUL, at most 16 KiB UTF-8).
Those rules are copied in the loops schema and checked for exact parity.
The `maxUtf8Bytes` companion keyword enforces bytes; standard JSON Schema
only enforces `maxLength` characters. Standard validators must be paired
with this byte check. No attachments are specified by a loop definition.

The executor constructs the existing new-thread request with that project
and those settings, a prompt containing the brief and finding as separate
instruction/data sections, an empty attachments list, and one saved op ID
for this run. The complete prompt must pass new-thread validation before
any dispatch. Output is data, never a command or fresh authority. All
existing new-thread gates, receipts and uncertainty rules still apply;
this contract adds no alternate spawn route or retry permission.

### Authority, budget and switching

A new loop is proposed by an agent and confirmed once by Jake (L8); its
trigger, allowed effects and off switch are part of that approval. The
`authority` object records the approval and its scope. Nonempty strings do
not prove it exists: activation must verify the referenced approval covers
the exact definition. Changes outside that approval need confirmation
again. A reminder notifies or runs only the one action approved when set
(L5). No inferred authority, template delegation or new numeric loop cap.

The budget bounds attempted agent starts in a rolling `window_ms`, counted
from the saved `dispatch_at_ms` mark, preserved across result updates.
Dispatches that become uncertain or confirm no creation still
consume admission; quiet, shadow and refused-before-dispatch runs consume
none. `max_agent_starts: 0` permits checks but no agent. Shared check/agent
concurrency limits and the urgent reserve apply in addition; neither a
per-loop budget nor urgent priority bypasses them. These are admission
limits, not a claim to meter or cap a provider's monetary bill. Observed
cost is reported separately, with unknown preserved.

For shared agent capacity (L2), the executor samples each unsettled created
run once per pass, after receipt reconciliation and checks, immediately
before dispatch planning. `pending`, `starting` and `active` occupy capacity;
a failed read or any other status leaves occupancy unknown and holds
dispatch. An observed `idle` or `error` retires that run from occupancy,
durably keyed by its run and thread identities in private state.
Later passes and restarts do not read retired runs again. This
retires only the loop's original work: later activity on that thread is
outside this loop admission accounting. The created receipt, budget charge
and unknown outcome rules remain unchanged.

## Run (`kind: "run"`)

One record per admitted occurrence; updates preserve the run ID and
occurrence. Claim and save the identity before the check; save the dispatch
op ID before sending. A resumed or repeated run reuses these identities.
A failed save authorizes no dispatch. Reconciliation of the existing
new-thread record, not another spawn, settles an uncertain dispatch.

| Field | Meaning |
| --- | --- |
| `schema`, `kind` | `openwiz.loops.v1`, `run` |
| `id`, `loop_id`, `definition_revision` | Run identity, owning loop, exact definition used |
| `wake` | Original scheduled occurrence or delivered event identity (above) |
| `started_at_ms`, `updated_at_ms` | Check admission and latest record update; update time cannot precede start |
| `cost` | `{ "kind": "known", "usd_micros": 0 }` or `{ "kind": "unknown", "reason": "Not reported." }`; nonnegative integer millionths of USD, never an estimate silently called known |
| `result` | Exactly one object in the table below; all listed fields required |

| `result.kind` | Other keys | What is known |
| --- | --- | --- |
| `checking` | none | Check is admitted/in progress; no dispatch |
| `quiet` | none | Check succeeded with empty stdout; no agent |
| `check_failed` | `reason` | Check failed; no agent |
| `check_timed_out` | none | Check exceeded its limit; no agent |
| `shadow` | `finding` | Work found; shadow mode prevented dispatch |
| `deferred` | `finding`, `reason` | Work found; admission held (budget, shared capacity, off switch); no dispatch |
| `dispatching` | `finding`, `op_id`, `dispatch_at_ms` | Dispatch identity and time saved; a crash may leave creation uncertain |
| `created` | `finding`, `op_id`, `dispatch_at_ms`, `thread_id` | Existing new-thread receipt confirmed creation; does not prove agent start, completion or task success |
| `not_created` | `finding`, `op_id`, `dispatch_at_ms`, `reason` | Existing new-thread outcome confirms refusal or failure with no creation; the saved dispatch mark still consumes admission |
| `refused` | `finding`, `reason` | Before dispatch, a gate refused the action; no create was attempted |
| `uncertain` | `finding`, `op_id`, `dispatch_at_ms`, `reason` | A create was attempted but its outcome is not confirmed; never described as failure/no effect |

`checking` progresses to a check outcome or a work result. Work can remain
deferred or progress to a saved `dispatching` mark; that mark settles as
`created`, `not_created` or `uncertain`. The dispatch timestamp is never
replaced by a later update time and cannot precede check admission. A
confirmed creation is never downgraded by a later failed read. Agent start and reported configuration remain the
existing new-thread status view keyed by `op_id`; the watchdog can inspect
that view independently. No fabricated zero cost, missing thread called
created, or quiet run with an agent field.

Cross-record rules (unique identities, approval verification, matching
wake/revision to its definition, monotonic update times, valid transitions,
and budget accounting) are executor/planner requirements. JSON Schema
cannot prove them. Likewise a reader must reject duplicate JSON keys
before validation; validating an already-collapsed object cannot detect
them. L1 tests prove structural schema conformance and rule parity only,
not these runtime guards, scheduler behaviour, event delivery or a live run.

## Proof

`cargo test -p openwiz-tests --test checks loops_schema` drives synthetic
valid and invalid definitions and run records through the existing
pattern-aware schema checker with a loops-only mathematical-integer check,
including missing check limits, absent authority, bad types and enum forms, unknown keys, every run-result branch,
UTF-8 brief boundaries and the explicit synthetic example. The schema is
linted so no unsupported keyword can silently pass. Its red runs are kept
in the private L1 evidence record.
