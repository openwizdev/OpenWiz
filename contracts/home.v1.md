# OpenWiz home contract, version 1 (`openwiz.home.v1`)

A factory has one **home** where Wiz and its scheduled loops run. This
contract defines the home and its state. It grants no authority, starts no
tasks and performs no live reads. All examples are synthetic.

## Machine

The owner chooses one always-on macOS or Linux machine. It runs `t3 up`
as a service with T3 Connect signed in, so the owner can reach Wiz from a
computer or phone. Boat is an opt-in host choice.

## Project

One T3 project points at the home checkout. The checkout's GitHub remote
is the project's tracker in T3. The owner's checkout is their private
records project. A user's checkout is their own OpenWiz project.

## The Wiz thread

Pin one thread titled exactly `Wiz` in the home project. Its harness,
model and effort come from the settings contract's
[`roles.orchestrator`](settings.v1.md#fields) row. A settings change
applies at the next Wiz session and leaves the current session running
with its original selection.

## Boot inputs

At the start of each session, read the home's handoff file (the handoff
skill's page) and the home state before any other inputs. A new session
can pick up from these files with an empty chat history.

## State

State lives in `.openwiz/home` in the home checkout.

| Path | Contents |
| --- | --- |
| `loops.json` | Installed loops keyed by loop id, with the T3 task id, schedule, loop file path and SHA-256 digest for each. |
| `<loop-id>/state.json` | The loop's own JSON data. The loop defines its fields. |
| `<loop-id>/ok.log` | A UTF-8 log with one LF-terminated acknowledgment per line. |

### Installed loop record

The manifest has `schema: openwiz.home.v1` and a `loops` object. Decode
JSON with duplicate-key rejection before validating the object. In
particular a repeated loop id is an error even when both entries agree.
Each loop id follows the [WizLoops id grammar](wizloops-loop.v1.md#fields)
and names one installed task. Each entry has these fields.

| Field | Meaning |
| --- | --- |
| `task_id` | The opaque T3 scheduled task id returned by T3. |
| `schedule` | The effective schedule of the installed task, as specified below. |
| `path` | A checkout-relative Markdown path under `loops/` with no empty, `.` or `..` components. Resolve the file inside that directory. |
| `sha256` | The 64 hexadecimal digits of the SHA-256 digest of the installed loop file's bytes. Writers use lowercase. |

Store the schedule T3 installed, with the server's time zone added for a
fixed-time task so the watchdog can resolve due times from files alone.

| `type` | Other schedule fields |
| --- | --- |
| `interval` | `everyMs`, the elapsed interval in milliseconds (at least 60000). |
| `fixed_time` | `timeOfDay` as `HH:MM`, optional `weekdays` (distinct integers from 0 for Sunday to 6 for Saturday, with omission meaning daily), and `timeZone` (the server's IANA zone, or `UTC`). |
| `once` | `runAt`, an RFC 3339 time with seconds and an explicit offset, as installed. |
| `webhook` | No other fields. |

For fixed-time and one-off tasks, use the most recent T3 scheduled
occurrence at or before the observation time as the latest due time.
Validate time zones and calendar dates when reading schedule values.

### Acknowledgment line

The run appends its line as its last step. Strip the terminating LF before
validating the line. The format uses one ASCII space between fields.

```text
<UTC time> <loop id> ok|quiet|recovered|failed <one-line why>
```

Use whole UTC seconds as `YYYY-MM-DDTHH:MM:SSZ` and reject impossible
calendar dates. The reason is nonblank text on one line, beginning with a
non-whitespace character. `ok` records a completed run with work and
`quiet` records a completed run with nothing to do. `recovered` records
a recovery attempt that returned and `failed` records a failure. Both
are diagnostic. A recovery attempt still needs an `ok` or `quiet` from
the loop itself to establish completion.

The [JSON Schema](home.v1.schema.json) checks the manifest object or a
single acknowledgment string. The [fixtures](fixtures/home/synthetic/scenarios.md)
include the manifest, valid and refused lines, and watchdog cases.

## Watchdog

Use the newest valid `ok` or `quiet` line for the loop at or before the
observation time. A T3 `lastRunStatus` of `succeeded` means dispatch
only and provides no completion time. A status of `failed` makes the
loop late even when it has a fresh acknowledgment.

- For an interval loop, no completion is late. With a completion, the
  loop is late once the elapsed time is strictly greater than twice its
  interval.
- For a fixed-time or one-off loop, a completion at or after its latest due time
  satisfies that occurrence. With no such completion the loop is late
  strictly after the due time plus 30 minutes. With no due occurrence
  yet, the time rule cannot make it late.
- A webhook loop has no clock deadline. A T3 failure still makes it late.

The watchdog makes at most one recovery run for a failure and files a
Needs-you card if the loop still fails to complete.

## Installed loops

Install each loop from a file in the home project's `loops/` directory
through WizLoops' T3 runner. Every run starts a fresh session. Install
`home-watchdog`, `settings-backup` and `update-check` on every home.
The settings backup uses the
[branch defined by the settings contract](settings.v1.md#where-the-file-lives).
Install `fleet-check` for each running fleet. The owner opts in to any
other loop.

## Chat

Only the owner writes to the Wiz thread and only Wiz answers. Agents
report through GitHub records and the driver's wake. A fleet, agent or
loop that needs the owner files a Needs-you card. Fleet callbacks and
loop chatter stay out of the Wiz thread.

## Updates

Wiz offers a verified release with its one-line changelog. The update
starts only after the owner's yes is recorded in the Wiz chat or the
feed. Use the installer update path that preserves drivers and settings.

## Server

T3's own `t3 up` is the home server. Local pages listen only on
`127.0.0.1`.
