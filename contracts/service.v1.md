# OpenWiz service contract, version 1 (`openwiz.service.v1`)

The shapes of OpenWiz's always-on service on the owner's PC (OpenWiz 0.0.8, spec #262): its status report, its health checks and their fixes, the two-tries rule and the one "Needs you" item, the GitHub record each fix writes, the self-update's record, and its config and state directory. The schema is [`service.v1.schema.json`](service.v1.schema.json). This file adds the check table, the rules a schema can't express, the record forms and examples.

**Status:** T1 (#265) defines the contract; T4 (#269)'s fixture service prints `openwiz.service-status.v1` through `openwiz-service status --json`. Live acceptance remains unverified. T3 (#268) plans from it, T4 (#269) runs the service and prints its status, T5 (#270) carries out the fixes and writes the records, T6 (#271) owns the clone and the builds, and T7 (#272) the App's key. The original T1 proof checked the examples below, good and bad tables, and the check table; current fixture consumers are in `tests/service/`.

**Always true:**
- **OpenWiz's own only.** A check observes, and a fix touches, only OpenWiz's own loops, its own fleet threads, its own tick and its own server. No other loop, thread or project is ever touched (spec #262: "It never touches loops, threads or projects that aren't OpenWiz's").
- **One fix per check, from a fixed list.** A check has at most one fix, and each fix uses only its fixed allowlisted effects (TK1 below adds exact-loop pause before the in-process tick restart). No fix is made up at run time.
- **Two tries, then one "Needs you" (legacy checks).** Each fix is tried at most twice per incident. Then the incident becomes one "Needs you" item, and the check stays quiet about it until the incident ends.
- **Every action has a record on GitHub:** each try of a fix, each "Needs you", and each self-update attempt. A record is one new comment in the form below. Records are never edited (#119: the GitHub writes never edit a comment).
- **Unknown stays unknown.** A check that can't read its subject observes `unknown`. That counts no try, heals nothing and ends nothing.
- **Private.** The state directory is owner-only. The App's private key is read only from its file, and never appears in the status, a record, a log, an error or a process's arguments. The installation token is held in memory only.

## The documents

| `schema` | What | Where |
| --- | --- | --- |
| `openwiz.service-status.v1` | The status report: what is running, the tick's runs, the server, the last health pass, the open incidents and the last self-update | Printed by `openwiz-service status --json` (T4) |
| `openwiz.service-config.v1` | The service's config | `service/config.json` in the state directory, written by Jake's setup (T11) and never by the service |
| `openwiz.service-state.v1` | The service's own memory: its tick's runs, its last health pass, its incidents and its last self-update | `service/state.json` in the state directory, written only by the service |
| `openwiz.service-record.v1` | The data of one GitHub record | The `json` block of the record's comment |

The schema is one `oneOf` of the four, told apart by `schema`.

## Reading it

Readers use hand-written strict readers on B1's pattern (`crates/core/src/attachment.rs`, PR #88), never serde's derived ones:

- **An object** is read only from a JSON object with **exactly its keys, each once.** A missing key, an extra key or a **duplicate key** is refused. A schema can't see duplicate keys, because a parsed value keeps only one, so the reader must refuse them.
- **An enum** (a check, a way of being broken, a fix, a gap) is read only from **one string in its list.** Never another spelling (`Paused`, `timed out`), never a number or a bool, and never a **tagged object** such as `{"paused": null}` (serde's external tagging).
- **A list** is read only from a JSON array, and **an object** only from a JSON object. A **positional array** in place of an object (`["i3", "server"]`) is refused.
- **Integers** are read only as JSON integers: no `1.0`, no `"1"`, no `true`. `NaN` and `Infinity` aren't JSON.
- `null` is read only where the schema has it.
- **The rules below are part of the contract.** The schema alone can't check them, so a reader checks them too.

Times are integer milliseconds since the Unix epoch (`at`, `since`, `*_at`). Durations are integer seconds (`*_s`). Ids follow the CloudRoom adapter's rule: 1 to 128 ASCII letters, digits, `_` or `-`, not starting with `-`.

## The checks

A **health pass** runs every `health.every_s` seconds (config). It runs each check once, `cloudroom` first, and gives one **result** for each subject.

| Check | Subject | Observes | Broken when (`what`) | Fix | Record on | "Needs you" when |
| --- | --- | --- | --- | --- | --- | --- |
| `loop` | Each of OpenWiz's loops (below), by its id | Its state in `room-cli loop list` | `paused`: the loop is paused | `resume_loop`: `room-cli loop resume <id>`, a new allowlisted write (T5) | The service issue | At a broken pass after its second try |
| `tick` | The service's tick | The service's own tick runs | `stalled`: a run is still going when the next run is due, `tick.every_s` after it started | `restart_tick`: stop that run, then start a new one | The service issue | At a broken pass after its second try |
| `fleet_thread` | Each open spec whose GitHub records name its fleet thread (ADR 0011; FA2, #192, writes that record), by the spec's number | That thread in `room-cli thread show <id>` | `not_found`: CloudRoom says there is no such thread; `archived`: it is archived | `take_over_fleet_thread`: start a new fleet thread for the spec, which takes over from the spec's GitHub records as FA2's fleet threads do | The spec issue | At a broken pass after its second try |
| `server` | The service's server | `GET http://127.0.0.1:<server.port>/api/v1/health` | `refused`: the connection is refused; `timed_out`: no full answer within `server.probe_timeout_s`; `wrong_answer`: an answer that isn't `200` with the health body naming `openwiz-server` (`contracts/web-api.v1.md`) | `restart_server`: stop the service's server, then start it again with the same config | The service issue | At a broken pass after its second try |
| `cloudroom` | The PC's CloudRoom | Whether the CloudRoom adapter finds the running app's `room-cli` (T2, #267) | `not_running`: it finds none, or can't tell which | None: no allowlisted command starts the app | The service issue | At its incident's second broken pass |
| `watchdog` | OpenWiz `loops.v1` identities and exact problems | Independent persisted admissions, immutable limits and explicit failure-disable provenance | `missed`: oldest unadmitted scheduled occurrence is strictly past; `stuck`: check admission is strictly past its immutable time limit; `disabled_by_failures`: authoritative positive evidence | None: report only; no restart or switch | The service issue | Immediately on a new or changed exact problem |

**OpenWiz's loops** are the loops whose name starts `launch-fleet ` and has the configured repository, `<owner>/<name>`, as one of its words, split at each space. That is the name `launch-fleet` gives its loop (step 1: `launch-fleet <owner>/<repo>`). The words are compared exactly, case included, so the config writes the repository as the loops' names do. Every other loop is never a subject: it is never resumed, and it never shows in a result or a record (#265, Q4). With the repository `synthetic-owner/synthetic-repo`:

| Loop name | OpenWiz's? |
| --- | --- |
| `launch-fleet synthetic-owner/synthetic-repo` | Yes |
| `launch-fleet synthetic-owner/synthetic-repo (PC hub)` | Yes |
| `launch-fleet #900 synthetic-owner/synthetic-repo` | Yes |
| `launch-fleet synthetic-owner/other-repo` | No: another repository |
| `launch-fleet synthetic-owner/synthetic-repo-2` | No: no word is the repository |
| `launch-fleet synthetic-owner/Synthetic-Repo` | No: the case differs |
| `Launch-fleet synthetic-owner/synthetic-repo` | No: it doesn't start `launch-fleet ` |
| `nightly launch-fleet synthetic-owner/synthetic-repo` | No: it doesn't start `launch-fleet ` |
| `launch-fleet` | No: it has no repository |

### TK1: takeover by the service tick (additive)

Jake's TK1 approval and its integration ruling on #270 add service-tick takeover beside the legacy new-fleet-thread outcome. For this path no fleet agent is created, no thread id is invented, and no loop is created or deleted. The existing registered Rust tick uses the repository's `docs/agents/fleet.md` settings through its normal checked reads.

Before acting, re-read the complete open-spec list and the spec's complete ordered comments. The latest `launch-fleet: fleet thread <thread>, loop <loop>` first line must still name the dead thread and one literal checked loop id. Verify that the thread is absent or archived in the configured project, then verify the exact loop's repository ownership. An unread list, changed record, live/foreign thread or ambiguous identity permits no takeover write.

The optional `retired_loops` field in `openwiz.service-state.v1` and `openwiz.service-status.v1` is an array of records with exactly these fields (older state documents may omit it):

```json
{"owner":"service_tick","spec":900,"thread":"thr_syn_old","loop":"loop_syn_old","phase":"pause_pending","at":1700000000000}
```

`spec` is the open spec, `thread` and `loop` are the exact old ownership record, `at` is when the durable intent was saved. Each loop id occurs once. `owner` is always `service_tick`. `phase` advances monotonically:

1. `pause_pending`: save this reservation together with the due try, before the pause. This is an intent, not a claim of successful retirement.
2. `paused`: `room-cli loop pause <loop> --json`, followed by a fresh complete `loop list --json`, confirmed the same owned loop paused. A command timeout or exit alone cannot confirm it. Save this phase before requesting the replacement tick. An already paused owned loop needs no second pause.
3. `active`: the runtime confirmed completion of the old service tick and started its replacement. Save this phase atomically with the successful try outcome. An uncertain stop/start never becomes active and permits no overlapping replacement. All due retirement pauses are prepared before one shared tick replacement; a simultaneous stalled-tick repair cannot bypass an unconfirmed pause.

The planner never resumes any loop reserved in these records, including after a crash, an incident ending, a changed loop name or a service restart. Full-list ambiguity still stays unread. Other loops keep their existing rules. A saved intent is retained on failed/interrupted attempts: unknown effects are not undone by an automatic resume. Before a later effect, revalidate the latest GitHub ownership and the configured project again. Reusing an existing exact binding can reconcile a confirmed paused loop without a second pause; a different binding for the same loop is refused.

A saved `pause_pending` reservation also fences that spec at every service-tick action dispatch boundary, including normal scheduled runs, pending-start recovery and an already-running tick. The check reads shared durable authority again before dispatch. Other specs continue; an action already dispatched retains its normal readback and outcome recording. Confirming the pause permits dispatch again. Reload preserves the fence.

Stalled-tick repair refreshes the current run after external observations and before planning and saving a try. Its runtime request carries the expected process-local worker generation, separate from the public start timestamp. The scheduler owner compares that generation before requesting a stop: a completed or changed run causes no stop or replacement. Deliberate TK1 replacement remains a separate request with the confirmed-pause prerequisite.

Successful TK1 takeover has this additional `takeover_outcome` shape, on the existing fix record on the spec:

```json
{"state":"done","owner":"service_tick","retired_loop":"loop_syn_old"}
```

It never includes a new `thread` field. Its first-line outcome is exactly `done, service tick owns the fleet, retired loop <loop>`. In saved state it must match an active retirement record for the incident's spec and that exact retired loop. The retirement record preserves its original old thread even if the same spec's incident later observes a different dead thread; historical outcomes are never rebound to that newer thread. The legacy `{"state":"done","thread":"thr_syn_new"}` remains readable. Failed/interrupted outcomes, two tries and one Needs you, outcome-before-comment ordering, exact comment readback and saved notification ids retain their existing rules. An active retirement record makes that exact old fleet binding healthy; a later ownership record must be evaluated on its own merits. The service tick's own check still detects a stalled service tick.

**Unknown and unread.** Only `loop` and `fleet_thread` read through `room-cli`, so only they can be unknown:

- When `room-cli loop list` can't be read in full, or the open specs' GitHub records can't, that check gives one `unread` result, with no subject, in place of its subjects' results.
- When one subject can't be read (a `thread show` that fails), its result is `unknown`.
- While CloudRoom isn't running, `loop` is `unread` and every `fleet_thread` result is `unknown`, each with the gap `cloudroom_not_running`.

The other three checks observe the service itself, its server and the adapter's search, so they are always known.

### A result

```json
{"check": "server", "observed": {"state": "broken", "what": "timed_out"}}
```

- `check`, and the subject's fields: `loop` has `loop` (`id` and `name`); `fleet_thread` has `spec` (its issue number) and `thread` (the fleet thread's id, as its records name it). `tick`, `server` and `cloudroom` have none.
- `observed` is one of:
  - `{"state": "healthy"}`;
  - `{"state": "broken", "what": <one of the check's ways above>}`. A `tick` also has `run_started_at`: when the stalled run started;
  - `{"state": "unknown", "gap": <gap>, "reason": <OpenWiz's own words>}`, for `loop` and `fleet_thread` only.
- An `unread` result is `{"check": "loop" or "fleet_thread", "unread": {"gap": <gap>, "reason": ...}}`.

A **gap** is one of the inventory's eight (`untested_version`, `command_failed`, `timed_out`, `budget_exhausted`, `malformed`, `missing_field`, `wrong_type`, `not_found`) or `cloudroom_not_running`. A reason is OpenWiz's own words, never a tool's raw output.

## LP4: the independent loops watchdog

The `watchdog` check runs in the existing registered health job, independently
of the loop scheduler. It reads existing private loop state without acquiring
`service/loops/run.lock`, creating files, executing checks or changing switches.
Two complete matching reads of the strict run index, run records and audited
switches are required; missing, incomplete, malformed or changing state is
unknown. The projection also fences current definitions and state while reading
immutable definition blobs. A held scheduler pass cannot prevent this read.
The trusted installation binds the checkout to the configured repository and
project; unavailable identity is unknown. An embedding may supply an equivalent
complete authoritative observation source through `Health::with_watchdog_source`.

The service has no failure-disable producer today. Off plus old failures is
never evidence of `disabled_by_failures`; production preserves that category as
unknown. No automatic-disable threshold, new limits, repair, or activation is
introduced. Current on/off state controls scheduled expectations, but an
already admitted checking run remains observable when off or removed. A check's
limit comes from its recorded immutable definition, never today's definition
or its update time. Scheduled coverage uses original due time through admission,
including late admissions; held proposals consume no occurrence.

These are explicit exceptions to the legacy two-tries/one-hour lifecycle:

- A problem's identity is its `loop_id` and the entire `broken` object. Missed
  has `due_at_ms`; stuck has `run_id`, `started_at_ms`, `timeout_ms`; failure-disabled
  has no additional fields. `state` is `broken`; `what` names the variant.
- A new exact problem immediately opens a `watchdog` incident and saves one
  notification intent. It has no repair tries, `healthy_since` is always null,
  and `needs_you` is non-null with `at == opened_at`. Changing a due time, run,
  start or immutable limit creates a new problem. Identical evidence is quiet.
- Positive healthy evidence clears its problem immediately. Recurrence then
  opens a fresh incident and notification operation. Unknown categories,
  missing loops and an unread snapshot retain previous problems; absence is
  never proof of recovery. There is no one-hour heal for this check.
- One aggregate health result has exactly `check: watchdog`, `open` (problem
  objects with `loop_id`, `broken`), `unknown` (objects with `loop_id`, `kind`),
  and `snapshot_unknown` (boolean). `kind` is missed, stuck or disabled_by_failures.
  Open problems match the active watchdog incidents. Lists have no duplicates.
- State and status may have optional `watchdog_deliveries`: saved watchdog
  incidents whose notification delivery is pending. Older documents may omit
  it. The saved body, incident and operation identity survive problem recovery,
  changes and restart; a matching active incident must have identical fields.
  Delivery finishes only after exact comment readback and an accepted/queued
  send outcome. These pending rows do not keep healed problems open. Ambiguous
  effects stay pending; they never authorize a duplicate POST or a new send id.

Watchdog incidents use the shared `iN` counter. Pending delivery ids are unique
and below `next_incident` in state, even when their incident has healed.
Distinct problems never share a notification operation id, including pending
rows for healed problems. Their records are `needs_you` with `loop_id` and
`broken`, without `tries`.
They use the existing no-fix first-line form and service-issue/orchestrator
routes. These fixture proofs establish wiring, not live acceptance.

## Incidents and the two-tries rule

An **incident** is one subject's fault, from its first broken result to its end. A subject has at most one open incident. Its id is `i` and then a number, the state's `next_incident`, which then goes up by one.

Each pass, for each result, in this order:

1. **Broken, and no open incident:** open one (`opened_at` is now). The fix's first try is due. A check with no fix has nothing due.
2. **Broken, and an open incident:** clear its `healthy_since`. Then:
   - if the fix has fewer than two tries, and its last try has its outcome, the next try is due;
   - if it has its two tries, each with its outcome (or the check has no fix), and there's no "Needs you" yet, **one "Needs you" is due**;
   - if it already has its "Needs you", **nothing is due**: the check stays quiet about it.
3. **Healthy, and an open incident:** set `healthy_since` to now if it isn't set. **The incident ends** at the first healthy pass at least one hour (3,600 s) after `healthy_since`. So a fault that comes back within the hour is the same incident, with the tries it already had.
4. **Unknown, or unread:** nothing changes. No try is due, nothing heals and nothing ends.
5. **A subject that is gone** (a loop no longer in `loop list`, or no longer OpenWiz's; a spec that closed, or whose records no longer name a fleet thread): its open incident ends. This holds only when that check's list was read in full, never on `unread`.

An incident that ends is dropped from the state, with no record. A fix's try counts once it is due and saved, whatever its outcome. A try is judged by the next pass, never by the command's own exit.

**Save before you act.** A due try is saved in the state, with its `outcome` `null`, before its command runs. Once the command returns, its outcome is saved, then its record is written, then the record's comment id is saved. A crash at any point never gives a third try, or a second record of one try. At start, a try still saved with `outcome` `null` becomes `{"state": "interrupted"}`: the service stopped before it learned how the try went. A due "Needs you" is likewise saved, with its `send` op id, before its comment and its message.

### A fix that is due

What the planner (T3) returns for one try:

```json
{"fix": "restart_server", "incident": "i3", "try": 1}
```

`fix`, `incident` and `try` (`1` or `2`), and the subject's fields: `resume_loop` has `loop`, and `take_over_fleet_thread` has `spec` and `thread` (the one that is gone). Each fix belongs to one check, as the table says, and `cloudroom` has none.

### Its outcome

- `{"state": "done"}`: the command succeeded, and, where its write is read back, the read-back agrees. `take_over_fleet_thread`'s is `{"state": "done", "thread": <the new fleet thread's id>}`.
- `{"state": "failed", "gap": <gap>, "reason": ...}`: the command refused or failed. `timed_out` says only that it didn't answer in time, never that it had no effect.
- `{"state": "interrupted"}`: the service stopped before it learned how the try went.

## Records

**Every try of a fix, every "Needs you" and every self-update attempt writes one new comment** on GitHub, as the service's GitHub App (T7). Its body is exactly:

````text
<the first line>

```json
<the record, one line of JSON>
```
````

The record is `openwiz.service-record.v1`. Its first line is worked out from the record alone, by the table below, so the two can't disagree. The service's GitHub App writes this public projection on both repositories. A fleet record carries `spec`, never the old `thread`; a successful legacy takeover projects its outcome to `{"state":"done"}`, including inside either Needs-you try. The service-tick outcome retains its owner and exact retired-loop receipt. Private service state/status retain their operational identities and legacy outcomes; public tests create synthetic state and read this public schema, never private files.

Before posting or notifying, the service validates the decoded record against the public schema and checks the complete body (decoded JSON strings included) for thread tokens. An intact unsafe frozen body is quarantined from POST and notification, retained privately with its original operation identity, and reported as pending. Other deliveries, repairs and incident healing continue. Invalid journal ownership, structure or checksum remains an error. Reconciliation may confirm an old claim only by unique exact readback of its original body, even when that body is no longer eligible for new public delivery; it never POSTs or notifies. No body or delivery identity is rewritten. This changes no retry or retirement safeguard.

**Where:** a `fleet_thread` record goes on its spec's issue (`spec`). Every other record goes on the **service issue**: one standing issue, named in the config (`service_issue`), that Jake creates in T11's setup. A "Needs you" also goes to the orchestrator's thread (config `orchestrator_thread`) as one message through `send`'s write (`room-cli thread tell`), with this text: the comment's first line with its `**Needs you:**` turned into `Needs you:`, then ` Recorded on #<issue>.`.

### The first line

`<subject>` and `<broken>` come from the record's check, subject and `broken`, and an update's fields from its record:

| Check | `<subject>` |
| --- | --- |
| `loop` | `the loop <id> (<name>)` |
| `tick` | `the tick` |
| `fleet_thread` | `the fleet thread of #<spec>` |
| `server` | `the server` |
| `cloudroom` | `CloudRoom` |
| `watchdog` | `the OpenWiz loop <loop_id>` |

| `what` | `<broken>` |
| --- | --- |
| `paused` | `is paused` |
| `stalled` | `is stalled` |
| `not_found` | `is gone (not found)` |
| `archived` | `is gone (archived)` |
| `refused` | `is down (refused)` |
| `timed_out` | `is down (timed out)` |
| `wrong_answer` | `is down (wrong answer)` |
| `not_running` | `is not running` |
| `missed` | `missed its check at <due_at_ms>` |
| `stuck` | `has stuck run <run_id> (started <started_at_ms>, limit <timeout_ms> ms)` |
| `disabled_by_failures` | `was switched off by failures` |

| Record | First line |
| --- | --- |
| A try that is `done` | `openwiz-service: incident <incident>: <subject> <broken>; try <try> of 2, <fix words>: done` |
| A takeover that is `done` | `openwiz-service: incident <incident>: <subject> <broken>; try <try> of 2, take it over: done` |
| A try that `failed` | `openwiz-service: incident <incident>: <subject> <broken>; try <try> of 2, <fix words>: failed (<gap>): <reason>` |
| A try `interrupted` | `openwiz-service: incident <incident>: <subject> <broken>; try <try> of 2, <fix words>: interrupted` |
| A "Needs you" after two tries | `**Needs you:** incident <incident>: <subject> <broken>; OpenWiz tried twice and couldn't fix it.` |
| A "Needs you" with no fix | `**Needs you:** incident <incident>: <subject> <broken>; OpenWiz has no fix for it.` |
| An update that `switched` | `openwiz-service: update to <to>: switched from <from>` |
| An update that `kept` the old build | `openwiz-service: update to <to>: kept <from>; the <step> failed: <reason>` |

| Fix | `<fix words>` |
| --- | --- |
| `resume_loop` | `resume it` |
| `restart_tick` | `restart it` |
| `take_over_fleet_thread` | `take it over` |
| `restart_server` | `restart it` |

### The record

- `{"schema": "openwiz.service-record.v1", "kind": "fix", "at", "incident", "check", <the subject's fields>, "broken", "fix", "try", "outcome"}`: one try. `broken` is the broken observation that made it due; `outcome` is never `null` here.
- `{"schema": "openwiz.service-record.v1", "kind": "needs_you", "at", "incident", "check", <the subject's fields>, "broken", "tries"}`: the "Needs you". `tries` holds the two tries it made, `first` and `second`, each `{"at", "outcome"}`. `cloudroom`'s and `watchdog`'s have no `tries`.
- `{"schema": "openwiz.service-record.v1", "kind": "update", "at", "from", "to", "outcome"}`: one self-update attempt (below).

The optional private `decision_repositories` setting names exact `public` and
`private` `{owner, name}` roles, with the same repository syntax as `repository`.
They must differ case-insensitively. The decisions reader verifies both names
and their visibility against GitHub before reading either role; unavailable
reads remain partial. With no setting/file it uses cwd's single repository.
An unreadable or malformed configured pair never falls back. This setting is
read by both server entry points and activates no migration or publication.
Repository role names must be ordinary path components; `.` and `..` are refused.
Settings are read at server startup; restart after an approved setting change.

## The status report

`openwiz-service status --json`:

- `at`: when the report was made.
- `service`: what is running. `build` is the commit its programs were built from (40 lowercase hex digits), and `since` is when it started.
- `tick`: `running` is `null` or the run going now (`{"started_at"}`). `last_ended` is `null` or the last run that ended: `started_at`, `ended_at`, and `how`, which is `finished` (it exited 0), `failed` (it exited otherwise) or `stopped` (the service stopped it: `restart_tick`, or the service itself stopping).
- `server`: `port`, and `running`: `null` or `{"since"}`.
- `last_pass`: `null` before the first health pass; otherwise `at`, `results` (one for each subject, or an `unread`), `fixes` (the fixes it made due) and `needs_you` (the incidents it made a "Needs you" due for).
- `incidents`: every open incident, as the state has it.
- `update`: `null` before the first self-update attempt; otherwise the last one (below).
- `update_record` is optional and status-only: `{"state", "reason"}` while that saved update attempt has a pending record. `state` is `retrying` when no request was sent and delivery will retry on the next scheduled check, or `uncertain` when delivery is unconfirmed and held without reposting. `reason` is OpenWiz's own explanation. It requires a non-null `update` and is omitted once delivery is confirmed; it never changes the historical attempt or the state/record formats.

## The state

`service/state.json`, `openwiz.service-state.v1`: `next_incident`, `tick`, `last_pass` and `update` as in the status, and `incidents`. Each incident has:

- `id`, `check`, the subject's fields, `opened_at`;
- `broken`: its latest broken observation. The subject's fields are those of the same result, so a `fleet_thread` incident names the fleet thread last found gone;
- `healthy_since`: `null`, or when it was first seen healthy since it was last broken;
- `tries` (not for `cloudroom`): `first` and `second`, each `null` or `{"at", "outcome", "comment"}`. `outcome` is `null` only while its command runs; `comment` is `null` until the record's comment id is saved;
- `needs_you`: `null`, or `{"at", "op_id", "comment"}`: `op_id` is the `send` op id of its message (1 to 64 ASCII letters, digits, `_` or `-`, starting with a letter or digit), so a retry never sends it twice; `comment` is `null` until its comment id is saved.

At start, a tick run the state still shows as running was stopped with the service: it is saved as ended, `stopped`.

## The self-update

T6 (#271). The service updates itself only by pulling (spec #262): it fetches `main` from GitHub into `service/clone/`, builds that commit into `service/builds/<commit>/`, runs the test suite there, and switches to the new build only when the tests pass. Nothing on GitHub or elsewhere pushes into the PC, and it never updates before Jake first switches the service on (T11). How often it looks, and which tests it runs, are T6's.

Each attempt writes one record on the service issue, and the status and the state show the last one: `{"at", "from", "to", "outcome"}`. `from` is the build that was running, and `to` the commit of `main` it tried (each 40 lowercase hex digits). `outcome` is one of:

- `{"state": "switched"}`: the new build passed its tests, and now runs;
- `{"state": "kept", "step", "reason"}`: the old build still runs. `step` is where the attempt failed: `fetch`, `build`, `test` or `switch`.

## The config

`service/config.json`, `openwiz.service-config.v1`:

| Field | What |
| --- | --- |
| `repository` | `owner` and `name`: the GitHub repository the fleets run on |
| `project` | OpenWiz's CloudRoom project on the PC, by id: where a takeover starts its fleet thread |
| `operator` | Optional explicit local operator identity, a nonempty string set at install for the single owner. Omission preserves existing service reads. Both loop switch writes require a nonblank, NUL-free value and refuse when it is absent or invalid. Rechecked from this private config on each switch; never a repository owner, definition owner or HTTP identity |
| `orchestrator_thread` | The orchestrator's thread, by id: where a "Needs you" message goes |
| `service_issue` | The service issue's number (Records, "Where") |
| `github_app` | `app_id` and `installation_id`: OpenWiz's GitHub App (T7). Ids, not secrets. The key is a file (below) |
| `loops` | Optional `{approvals, limits}` composition using the LP1 trusted approval and loop-only capacity records below. Both records are required for loop admission; absence enables no loop execution. |
| `tick` | `every_s`: the tick's schedule |
| `events` | Optional `{ "hook_id": 4101 }` (synthetic example): the existing repository webhook's positive integer id. Absent means no intake job and no delivery reads; a present malformed object refuses config. The intake polls every ten seconds through the configured App, using only the approved delivery list and detail GETs; it never lists hooks or reads hook configuration |
| `health` | `every_s`: the health pass's schedule |
| `server` | `port` (1 to 65535), `allowed_host` (`null`, or the one public host name, as `openwiz-server --allowed-host` takes it), and `probe_timeout_s` (how long the `server` check waits for the health route). The server always serves the web page, from the running build's `web/` (`openwiz-server --web-root`) |

Every duration is at least 1 second. The service refuses to start, and says which rule failed, when its config doesn't read: a schema failure, a port above 65535, or an `allowed_host` the server refuses. It never guesses a value.

### L12: production loop registration

When `loops` is present, it has exactly `approvals` and `limits`, using the
unchanged LP1 sections below. Both must be explicitly installed and valid.
Absence registers no loop job. The service reuses `tick.every_s` as the Runner
polling period and the watchdog's current-directory checkout binding, verified
against the configured repository/project. The existing operator prerequisite
of that binding is retained. Runner still requires its clean default-branch
checkout and exact immutable definitions; no new checkout setting or cadence
fallback is introduced. These reused inputs and the service-owned integration
test target were confirmed on 2026-11-10 ([disposition](https://github.com/jparker2006/ClosedWiz/issues/2264#issuecomment-6781050283)).

The composition supplies the existing CloudRoom adapter, clock and new-thread
file store under the same private state root. It uses the actual L10 verifier
and L11 limits reader, with both inputs checked again at every existing Runner
approval boundary before checks and dispatch. A changed installation identity,
scheduling input, unsafe/unreadable record or invalid loop input refuses loop
admission. No approval/limit fixture injection, default authority or alternate
spawn route exists. Saved run identities, receipt reconciliation, uncertain
outcomes, shadow behavior and per-loop budgets remain the Runner's own.

Base service configuration retains every existing strict shape, integer,
duplicate-key and startup rule. The service's base config reader validates
those rules independently of the optional loop admission record. The same base
validation applies to updater construction and pending recovery, including
already-parsed values. Full loop shape/policy validation remains explicit at
loop registration and effect admission.
Invalid/missing loop approvals or limits do not prevent independent tick,
health, update, server or event-intake operation. Invalid complete JSON or
unsafe/missing base configuration still triggers the pre-existing refusal.
A loop refusal reports only fixed diagnostics. Saturation stays inside the
loop planner; it is never a fleet, descendant, worker or spending limit.

Registration is synthetic-fixture verified preparation. It installs no trusted
records, starts no deployed service, executes no real definition and activates
or moves no real loop. #550 and #551 retain every production-merge, shadow-day,
switch, deletion, live, spending, review, CI and release gate; #2379 consumes
this registration rather than adding a second one.

### LP1: required loop-only capacities

LP1 approves the following required `loops.limits` record in the setup-written,
owner-only `service/config.json`. These are explicit installed inputs, never
inferred defaults. A different policy needs Jake's approval ([private
record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6760457138),
2026-11-10; [approved revision 4](https://github.com/jparker2006/ClosedWiz/issues/541#issuecomment-6760692103)).

```json
{"checks":{"max":4,"urgent_reserve":1},"agents":{"max":16,"urgent_reserve":4}}
```

The standalone schema definitions are `loop_limits`, `loop_check_capacity` and
`loop_agent_capacity`. Every field is required, an integer in the reader's
unsigned machine range, with exactly the keys shown, each once. Service integer
syntax excludes fractional and exponent notation even for mathematical integers;
JSON Schema's integer type alone does not enforce that syntax. The reader also
rejects duplicate keys before projection, including enclosing `loops`/`limits`
keys. Missing, unreadable, malformed, overflowing or invalid input supplies no
capacities and admits no loop check or agent. Each reserve must be between zero
and its maximum; only the approved values above pass policy validation. There
is no environment override, fallback file or inferred value.

The maxima include their reserves: at most three normal checks and twelve normal
original loop agents. Urgent work may use any free slots up to four checks and
sixteen original agents in total. Normal work never borrows reserved slots.
Existing rolling per-loop budgets, saved attempted-start charges and uncertain
outcomes still apply. Unsettled dispatches and pending/starting/active original
loop agents occupy slots; unknown occupancy holds dispatch. Idle/error retirement
remains durable per run/thread. Later activity on a retired thread and spawned
descendants are never counted as original-loop occupancy.

These capacities are a safety fuse solely on loop-started checks and original
loop agents. They never limit fleet builders, reviewers, planners or their
children, the factory or OpenWiz as a whole, and are not a spending cap
([ADR 0002](../docs/adr/0002-no-artificial-cap-on-builders.md)). There is no
loop-count ceiling. Approval, off/shadow/on, API, allowlist and live gates remain.

L11 exposes `openwiz_service::loops::limits::read` over supplied service-config
bytes. Its caller must preserve protected file access and full enclosing config
validation, and hold loop admission on any error. This adds only record definitions
under `$defs`: enclosing config registration and runtime composition belong to
L12. It installs no values, starts no service or check, and activates nothing.

### Existing webhook delivery intake

Option A (#805) reads the first page of up to 100 existing deliveries, then
fetches details for the four routing event kinds in `loops.v1`. The documented
REST shapes are synthetic assumptions until a separately gated endpoint
observation: https://docs.github.com/en/rest/repos/webhooks . The numeric delivery
id selects the detail; the GUID is the stable event id, including redeliveries.
Headers, destination URLs and responses are discarded; payloads are transient,
never logs or state. The existing owner-only hashed intake claims and shared
relay send records prevent repeated effects, including across restarts.

Only the two approved delivery forms are used: no cursor, hook listing,
redelivery, webhook mutation or personal-login fallback. More deliveries than
fit the first page, a failed read, a crash after claiming, or unread ownership
leave work to the independent fleet check-in. Polling makes no completeness or
live latency claim. The existing read/run deadlines and output bounds apply.
Event intake uses a separate fixed token profile: `metadata`, `contents`,
`issues`, `pull_requests`, `checks`, `actions` and `repository_hooks`, each
`read`. The returned permission map must match exactly and identify only the
configured repository. Missing, extra or wrong scope/identity refuses before
execution; there is no ordinary-profile or personal-login fallback. Ordinary
tick/health token requests and caches keep their existing profile, so event
permission refusal does not disable that safety net.

Configuring a hook does not prove App Webhooks read permission, the real hook-id
value, or endpoint compatibility; each stays Unverified until evidenced. This
contract authorizes no live activation or retirement of the safety-net tick.

## The state directory

The state directory is the one the store already uses: `$OPENWIZ_STATE_DIR`, when non-empty, must be absolute and takes precedence. Otherwise, an absolute `$HOME` is required, even when `$XDG_STATE_HOME` is absolute. On macOS, the store uses `~/Library/Application Support/openwiz` and ignores `$XDG_STATE_HOME`. On other platforms, it uses `$XDG_STATE_HOME/openwiz` when `$XDG_STATE_HOME` is absolute, else `~/.local/state/openwiz`. Here, `~` means `$HOME`. It is owner-only (0700) and never inside a repository (`crates/store`). The service's files are in `service/`, beside the CLI's and the server's own records, which are unchanged:

| Path, under the state directory | Mode | What | Written by |
| --- | --- | --- | --- |
| `service/` | 0700 | The service's own directory | Jake's setup (T11) |
| `service/config.json` | 0600 | The config | Jake's setup, never the service |
| `service/state.json` | 0600 | The state, replaced atomically (written to a temporary file, synced, renamed) | The service only |
| `service/app/` | 0700 | The GitHub App's directory | Jake's setup |
| `service/app/private-key.pem` | 0600 | The App's private key. Only the App's signing reads it (T7); it is never copied, printed or logged | Jake's setup, never the service |
| `service/clone/` | 0700 | The self-update's own clone of the repository, fetched from GitHub only (T6) | The self-update |
| `service/builds/` | 0700 | One directory for each built commit, named by its full commit (T6): its programs, and its web page in `web/` | The self-update |
| `sends/`, `new-threads/`, `attachments/` | As today | The CLI's and the server's records, unchanged | As today |

The service refuses to start (fail closed), and says which path, when `service/`, `config.json`, `state.json`, `app/`, the key, `clone/` or `builds/` is a symlink, isn't owned by the service's user, or is open to group or others. Every directory it creates is 0700, every file 0600, and every program it builds 0700.

## Where it comes from

| Part | Source | Class |
| --- | --- | --- |
| `room-cli loop list`, `loop resume <id>`; a loop is paused after 3 failed runs in a row | `room-cli loop --help` (CloudRoom's own help, read for #265) | Documented, not observed |
| A loop's id, name and paused state in `loop list` | No fixture and no observation yet: the help names no fields. The id rule here is assumed; T5 checks it against a real `loop list` before any live call | **Synthetic** |
| `room-cli thread show <id>` answering "not found" | The PC check: `HTTP 404: Thread not found` (the original PC discovery check) | Observed |
| A thread's `archivedAt` field | The 0.43.1 fixtures (`tests/fixtures/room-cli-0.43.1/`): the field is observed, but `thread show` of an archived thread is not (its scenario's `synthetic_assumptions`) | The field observed; an archived thread **synthetic** |
| The bundled `room-cli`, and its path changing at each start | The PC check, and spec #262 | Observed |
| `GET /api/v1/health` and its body | `contracts/web-api.v1.md`, `crates/server` | Contract |
| The fleet thread, its records and its takeover | ADR 0011, FA2 (#192, not built yet) | Decided, not built |
| `launch-fleet <owner>/<repo>`, and `**Needs you:**` on an issue with `Needs you:` to the orchestrator | `skills/launch-fleet/SKILL.md`, steps 1 and 6 | The skill |
| The state directory's root and owner-only rule | `crates/store` (`default_state_dir`, `Store::open`) | Code |
| Where records go, CloudRoom's "Needs you", when an incident ends, which loops are OpenWiz's | The orchestrator's answers on #265 (Q1 to Q4: "rec is good on all four") | Decided |
| The self-update's record, and the last one in the status and the state | The orchestrator's answer on #265 (Q5: "(a)") | Decided |

## Rules the schema can't express

Each is part of the contract. `check.py` checks the ones its examples can show.

- **S1** One result for each subject in a pass: no two for one loop id or one spec, one each for `tick`, `server` and `cloudroom`, and an `unread` check has no other result.
- **S2** A legacy subject has at most one open incident; LP4 uses one per exact watchdog problem. Incident ids are distinct, and each is below `next_incident`.
- **S3** An incident's `second` try is set only after its `first`, and a try's `at` is at or after `opened_at`.
- **S4** Except LP4's immediate watchdog intent, a "Needs you" comes only after both tries (or, with no fix, at the second broken pass), and only once per incident.
- **S5** A record's first line is the one the table gives for its JSON.
- **S6** `since`, `started_at` and `opened_at` are never after the report's or record's `at`; `ended_at` is never before `started_at`.
- **S7** A `fixes` or `needs_you` entry of `last_pass` names an open incident, in `incidents`: an incident ends only at a pass, and never in the pass that makes something due for it.
- **S8** The status's running build follows its last update: `service.build` is the update's `to` when it `switched`, and its `from` when it was `kept`.

## Examples

All values are synthetic.

The config:

```json
{"schema": "openwiz.service-config.v1", "repository": {"owner": "synthetic-owner", "name": "synthetic-repo"}, "project": "prj_syn_0001", "orchestrator_thread": "thr_syn_0001", "service_issue": 901, "github_app": {"app_id": 1001, "installation_id": 2002}, "tick": {"every_s": 300}, "health": {"every_s": 60}, "server": {"port": 7370, "allowed_host": "openwiz.example.com", "probe_timeout_s": 10}}
```

A status report with everything healthy:

```json
{"schema": "openwiz.service-status.v1", "at": 1767225900000, "service": {"build": "0123456789abcdef0123456789abcdef01234567", "since": 1767225000000}, "tick": {"running": null, "last_ended": {"started_at": 1767225600000, "ended_at": 1767225640000, "how": "finished"}}, "server": {"port": 7370, "running": {"since": 1767225001000}}, "last_pass": {"at": 1767225880000, "results": [{"check": "cloudroom", "observed": {"state": "healthy"}}, {"check": "loop", "loop": {"id": "loop_syn_0001", "name": "launch-fleet synthetic-owner/synthetic-repo"}, "observed": {"state": "healthy"}}, {"check": "tick", "observed": {"state": "healthy"}}, {"check": "fleet_thread", "spec": 900, "thread": "thr_syn_0201", "observed": {"state": "healthy"}}, {"check": "server", "observed": {"state": "healthy"}}], "fixes": [], "needs_you": []}, "incidents": [], "update": {"at": 1767224990000, "from": "fedcba9876543210fedcba9876543210fedcba98", "to": "0123456789abcdef0123456789abcdef01234567", "outcome": {"state": "switched"}}}
```

A status report with two incidents: the server is down and has had its second try, and a fleet thread was taken over and is healthy again, but less than an hour ago:

```json
{"schema": "openwiz.service-status.v1", "at": 1767229500000, "service": {"build": "0123456789abcdef0123456789abcdef01234567", "since": 1767225000000}, "tick": {"running": null, "last_ended": {"started_at": 1767229200000, "ended_at": 1767229260000, "how": "finished"}}, "server": {"port": 7370, "running": {"since": 1767229441000}}, "last_pass": {"at": 1767229440000, "results": [{"check": "cloudroom", "observed": {"state": "healthy"}}, {"check": "loop", "loop": {"id": "loop_syn_0001", "name": "launch-fleet synthetic-owner/synthetic-repo"}, "observed": {"state": "healthy"}}, {"check": "tick", "observed": {"state": "healthy"}}, {"check": "fleet_thread", "spec": 900, "thread": "thr_syn_0202", "observed": {"state": "healthy"}}, {"check": "server", "observed": {"state": "broken", "what": "timed_out"}}], "fixes": [{"fix": "restart_server", "incident": "i4", "try": 2}], "needs_you": []}, "incidents": [{"id": "i3", "check": "fleet_thread", "spec": 900, "thread": "thr_syn_0201", "opened_at": 1767229320000, "broken": {"state": "broken", "what": "archived"}, "healthy_since": 1767229380000, "tries": {"first": {"at": 1767229320000, "outcome": {"state": "done", "thread": "thr_syn_0202"}, "comment": 7001}, "second": null}, "needs_you": null}, {"id": "i4", "check": "server", "opened_at": 1767229380000, "broken": {"state": "broken", "what": "timed_out"}, "healthy_since": null, "tries": {"first": {"at": 1767229380000, "outcome": {"state": "done"}, "comment": 7002}, "second": {"at": 1767229440000, "outcome": {"state": "done"}, "comment": 7003}}, "needs_you": null}], "update": {"at": 1767224990000, "from": "fedcba9876543210fedcba9876543210fedcba98", "to": "0123456789abcdef0123456789abcdef01234567", "outcome": {"state": "switched"}}}
```

The state behind it, a moment later, with CloudRoom not running:

```json
{"schema": "openwiz.service-state.v1", "next_incident": 6, "tick": {"running": null, "last_ended": {"started_at": 1767229200000, "ended_at": 1767229260000, "how": "finished"}}, "last_pass": {"at": 1767229500000, "results": [{"check": "cloudroom", "observed": {"state": "broken", "what": "not_running"}}, {"check": "loop", "unread": {"gap": "cloudroom_not_running", "reason": "CloudRoom is not running, so its loops can't be read"}}, {"check": "tick", "observed": {"state": "healthy"}}, {"check": "fleet_thread", "spec": 900, "thread": "thr_syn_0202", "observed": {"state": "unknown", "gap": "cloudroom_not_running", "reason": "CloudRoom is not running, so the thread can't be read"}}, {"check": "server", "observed": {"state": "healthy"}}], "fixes": [], "needs_you": []}, "incidents": [{"id": "i3", "check": "fleet_thread", "spec": 900, "thread": "thr_syn_0201", "opened_at": 1767229320000, "broken": {"state": "broken", "what": "archived"}, "healthy_since": 1767229380000, "tries": {"first": {"at": 1767229320000, "outcome": {"state": "done", "thread": "thr_syn_0202"}, "comment": 7001}, "second": null}, "needs_you": null}, {"id": "i4", "check": "server", "opened_at": 1767229380000, "broken": {"state": "broken", "what": "timed_out"}, "healthy_since": 1767229500000, "tries": {"first": {"at": 1767229380000, "outcome": {"state": "done"}, "comment": 7002}, "second": {"at": 1767229440000, "outcome": {"state": "done"}, "comment": 7003}}, "needs_you": null}, {"id": "i5", "check": "cloudroom", "opened_at": 1767229500000, "broken": {"state": "broken", "what": "not_running"}, "healthy_since": null, "needs_you": null}], "update": {"at": 1767224990000, "from": "fedcba9876543210fedcba9876543210fedcba98", "to": "0123456789abcdef0123456789abcdef01234567", "outcome": {"state": "switched"}}}
```

A try's record, on the service issue:

````text
openwiz-service: incident i4: the server is down (timed out); try 1 of 2, restart it: done

```json
{"schema": "openwiz.service-record.v1", "kind": "fix", "at": 1767229381000, "incident": "i4", "check": "server", "broken": {"state": "broken", "what": "timed_out"}, "fix": "restart_server", "try": 1, "outcome": {"state": "done"}}
```
````

A takeover's record, on spec #900:

````text
openwiz-service: incident i3: the fleet thread of #900 is gone (archived); try 1 of 2, take it over: done

```json
{"schema": "openwiz.service-record.v1", "kind": "fix", "at": 1767229330000, "incident": "i3", "check": "fleet_thread", "spec": 900, "broken": {"state": "broken", "what": "archived"}, "fix": "take_over_fleet_thread", "try": 1, "outcome": {"state": "done"}}
```
````

A failed try's record, on the service issue:

````text
openwiz-service: incident i6: the loop loop_syn_0001 (launch-fleet synthetic-owner/synthetic-repo) is paused; try 2 of 2, resume it: failed (command_failed): room-cli refused to resume the loop

```json
{"schema": "openwiz.service-record.v1", "kind": "fix", "at": 1767230000000, "incident": "i6", "check": "loop", "loop": {"id": "loop_syn_0001", "name": "launch-fleet synthetic-owner/synthetic-repo"}, "broken": {"state": "broken", "what": "paused"}, "fix": "resume_loop", "try": 2, "outcome": {"state": "failed", "gap": "command_failed", "reason": "room-cli refused to resume the loop"}}
```
````

A "Needs you" after two tries, on the service issue:

````text
**Needs you:** incident i4: the server is down (timed out); OpenWiz tried twice and couldn't fix it.

```json
{"schema": "openwiz.service-record.v1", "kind": "needs_you", "at": 1767229561000, "incident": "i4", "check": "server", "broken": {"state": "broken", "what": "timed_out"}, "tries": {"first": {"at": 1767229380000, "outcome": {"state": "done"}}, "second": {"at": 1767229440000, "outcome": {"state": "done"}}}}
```
````

Its message to the orchestrator's thread: `Needs you: incident i4: the server is down (timed out); OpenWiz tried twice and couldn't fix it. Recorded on #901.`

A "Needs you" with no fix, on the service issue:

````text
**Needs you:** incident i5: CloudRoom is not running; OpenWiz has no fix for it.

```json
{"schema": "openwiz.service-record.v1", "kind": "needs_you", "at": 1767229561000, "incident": "i5", "check": "cloudroom", "broken": {"state": "broken", "what": "not_running"}}
```
````

Its message to the orchestrator's thread: `Needs you: incident i5: CloudRoom is not running; OpenWiz has no fix for it. Recorded on #901.`

A self-update that kept the old build, on the service issue:

````text
openwiz-service: update to 89abcdef0123456789abcdef0123456789abcdef: kept 0123456789abcdef0123456789abcdef01234567; the test failed: cargo test --workspace failed in the clone

```json
{"schema": "openwiz.service-record.v1", "kind": "update", "at": 1767232800000, "from": "0123456789abcdef0123456789abcdef01234567", "to": "89abcdef0123456789abcdef0123456789abcdef", "outcome": {"state": "kept", "step": "test", "reason": "cargo test --workspace failed in the clone"}}
```
````

## Not in version 1

- A fault that keeps coming back more than an hour apart: each time is a new incident, with its own two tries.
- Any check of the Mac, or of a thread that isn't a fleet thread (builders and reviewers are their fleet thread's to watch, ADR 0011).
- Starting CloudRoom, or anything outside the four fixes.

## Packaged update channel (0.0.13 T1)

Absent explicit owner installation metadata, the source pull/build/test channel
above stays unchanged. `channel.json` in the private installation root selects
`packaged` explicitly, using `openwiz.update-channel.v1`. Unknown/duplicate
metadata fails closed. The published release index, target manifest, archive
and SHA256SUMS come only from the fixed OpenWiz GitHub release endpoint, through
bounded transport. This is outbound pull-only; no webhook, upload, publication
or source-build gate. [install.v1.md](install.v1.md) defines integrity, targets,
immutable asset layout and staging. It does not establish a signed publisher.

Both channels retain the same private lock, current-selection validation,
full source identity, outcome records, pending journal, exact candidate identity
check and health-confirmed handover/recovery. Packaged candidates stage all
programs, web and runtime under service/builds/<source>; they never invoke
Cargo/npm or silently adopt another channel. Invalid/unavailable artifacts keep
the last-good selection. Setup/connection/engine effects follow
[setup.v1.md](setup.v1.md); this channel never marks those prerequisites ready.

TK1 delivery durability: a private immutable claim binds the spec issue and exact comment body before a POST, and an atomically saved receipt holds the confirmed comment id. Claims outlive their incidents. Even after one-hour healing or a restart, an unresolved claim remains reported and is reconciled only by a unique exact GitHub readback; it is never POSTed again. Other health checks and incident healing continue while delivery is pending.

## Notification job and protected state (0.0.15 T1, contract only)

The optional `notifications: {every_s}` configuration extension reserves one
bounded job in the existing installed scheduler. `every_s` is positive integer
seconds. Absence leaves notifications unavailable with zero delivery/work effects;
it never opts in, prompts permission or creates a subscription. There is no second
scheduler, permanent AI notifier or external command. T3 adds only this job's
registration/lifecycle; T4 separately supplies only its observed delivery factory.
Existing tick, watchdog, intake, recovery limits and owner namespaces are retained.
Current binaries need not accept this future configuration until T3 integrates it.

Optional `notifications` in service status/state is exactly
`{state, preference_generation, last_pass_at: Fact<ms>, reason}`. State words are
the notification status words; last_pass_at is the last actual completed source
pass or explicit unknown, never a fabricated current time. This public summary
contains no subscriptions, tokens, keys, endpoint or internal path. Existing
required fields are unchanged; old documents remain valid. The accompanying
schema adds only notification definitions and these three optional references.

T3 stores preferences, subscription generations/protected binding references,
group tombstones, exact dispatch journal and token/reference mappings under
`service/notifications/` in the existing owner-only state root (directory 0700,
files 0600; strict parsing, existing no-symlink/no-other-owner discipline). The
binding's endpoint/key material is separately protected owner state supplied by
T4's observed adapter; never config JSON, API output, Git, args or diagnostics.
A missing store/binding is unavailable, not a successful empty history or implicit
enable. Atomic replacement, durable sync-before-submit and per-owner serialized
admission follow [notifications.v1](notifications.v1.md). Failed storage/validation
refuses submission. Preference/subscription handlers and the job share that lock.
Persist the submitting mark before the one effect; crash/lost reply resumes as
uncertain with the original id and never retries blindly. Disable waits for any
admitted submission boundary, commits its higher generation, then stops future
admissions; previously submitted notifications cannot be retracted.

The job consumes independently current decisions, the existing health owner's
explicit incident escalation and available optional source transitions. It may
forward verified facts from already-owned intake/health projections, but adds no
new transport, second escalation policy or authority inferred from event hints.
Unread data stays a gap. A stopped engine has no functioning submission path and
cannot promise to notify about its own outage. The default adapter is
`UnavailableDelivery`, and all delivery/queue/Needs-you visibility stays honest.

The installed API injects the same protected store/context and exact source
readers, not a second in-memory settings system. T3 owns source/job/store/API
registration; T4 owns capability/binding adapter injection and factory only; T5
owns authenticated exact-token resolution. Receipt/navigation/preferences cause
no existing send/start/merge/recovery effect. T3/T4 must prove this across restart,
concurrency, disabled/revoked admission and outcome persistence failures. T1's
recording seam is fixture evidence only and creates no installed runtime.


### Public fleet ownership discovery (open development)

The latest `launch-fleet: fleet active, loop <id>` record binds the spec's exact
loop. Resolve its thread using the existing repository-bound private fleet map:
`{"repo":"owner/name","threads":{"fleet:<spec>":"<thread>"}}`.
The service reads `service/fleet-map.json` within its private state directory.
Configure the existing fleet writers' absolute `LAUNCH_FLEET_STATE` setting to
that same file; the service never discovers a map through process-global state. The file is an
owner-only regular file with one link. A missing, malformed, unsafe,
wrong-repository or unresolved map is an unread check, never an absent fleet.
The map is re-read when ownership is revalidated for takeover. The service
builds the old thread-bound representation only in memory for the existing
exact-loop adapter; it is never a public record. Retirement remains bound to
the exact repository/spec/thread/loop, with all existing pause and readback guards.
Legacy thread-bearing ownership records require positively verified private
GitHub metadata; an unknown or public repository refuses them.

### LP1: trusted loop approvals

The required `loops.approvals` record is an array of exact bindings under
`service/config.json`, written only by Jake's setup after verifying explicit
approval of the entire binding in the referenced private GitHub comment.
A merged definition, its own authority strings, a URL's syntax or this schema
never establish approval. This subsection supplies only the approvals fragment
(`$defs.loop_approvals`); L12 owns enclosing config validation and runtime
registration. It changes no existing service-start or independent job rule.

Each record has exactly these keys, each once:

| Field | Binding |
| --- | --- |
| `repository` | Exact configured `{owner, name}`; ordinary repository name, not `.` or `..` |
| `project` | Exact configured CloudRoom project id, with the existing service id syntax |
| `loop_id` | Definition `id`, with the existing loops op-id syntax |
| `definition_revision` | Immutable Git blob object id, 40 or 64 lowercase hexadecimal characters |
| `sha256` | 64 lowercase hex digits: SHA-256 of the exact blob bytes, including whitespace and final newline |
| `approved_by` | Exact definition `authority.approved_by`; nonblank and NUL-free |
| `scope` | Exact definition `authority.scope`; nonblank and NUL-free |
| `approval_ref` | Exact definition `authority.approval_ref`: canonical `https://github.com/<owner>/<repo>/issues/<positive issue>#issuecomment-<positive comment>` or the corresponding `/pull/` URL; no leading zeroes, query, credentials or extra suffix |

Setup verifies the private comment and its approval; the service does no GitHub
fetch to infer trust. The verifier rereads the protected setup configuration at
each existing Approval boundary, including shadow checks and immediately before
dispatch. It compares all fields to pinned installation identity and the actual
immutable blob, checks the definition's complete parsed value against that blob,
and requires action project `{kind: "id", value: <configured project>}`. It never
resolves a display name, substitutes a personal project or hashes reserialized
JSON. The blob digest binds the entire trigger, check, action and off switch.

The local checkout must have exactly one origin URL matching the configured
repository in one of the already supported GitHub remote forms (HTTPS, SSH URL,
or `git@github.com:`; optional `.git`, GitHub case-insensitive remote identity).
Only the existing allowlisted local Git reads are used. Clean default-branch
and immutable-definition checks remain the Runner's responsibility unchanged.

Missing, unreadable, unsafe, malformed or duplicate-key configuration refuses
verification. Missing/extra fields, wrong types, conflicting installations,
duplicate or conflicting `(repository, project, loop_id, definition_revision)`
bindings, or any mismatch refuse it too. Duplicate repository identities compare
case-insensitively; record-to-installation fields compare exactly. An empty
array approves nothing. Multiple explicitly approved revisions may coexist.
Removal takes effect on the next verification; there is no approval cache,
fallback file, environment override or allow-all mode. Diagnostics contain only
fixed refusal words, never the private binding or comment content.

This is solely authority for loop-started checks and original loop agents.
LP1 never limits fleet builders, reviewers, planners or their descendants, the
factory or OpenWiz overall, and is not a spending cap (ADR 0002). Existing
rolling budgets, saved attempted-start charges, unknown occupancy, shadow,
off/on, new-thread and run-record boundaries remain. L12 still owns production
composition; installation, activation, live/shadow-day work, spending, review,
CI, M1 and release/publishing retain every existing gate. Fixture proof does
not establish installed trust or live acceptance.
