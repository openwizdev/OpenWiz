# One-tap driver install steps

The install runner calls these Python scripts in order, each with the same two
positional arguments, `<driver> <work-folder>`. The first is the driver name
from the owner's install request. The second is the path to the work folder
the runner creates for this install. Read and write the handoff files there.

1. `fetch.py` fetches the listed release and verifies its checksum, manifest,
   name and schema. A `listed` or `unverified` release needs a separate yes
   after the fetcher's warning. A `later` listing refuses with its reason.
2. `key.py` proceeds without asking if the listing needs no key. Otherwise it
   asks through the T3 secret card and the keys flow. A declined or timed-out
   card refuses. The key value stays out of arguments, output and handoff files.
3. `live_check.py` asks before spending money or starting a machine, then runs
   the kit once on a throwaway ticket. It records and stops everything it starts
   whether the kit passes or fails.

| Exit | Meaning |
| --- | --- |
| `0` | Step completed successfully. For the live check this requires five passing kit checks and successful cleanup. |
| `1` | Step refused, such as a declined approval, failed verification or failed kit check. |
| `2` | Step could not complete, such as invalid arguments or an I/O error. |

On exit 1 or 2, print one human-readable refusal line to stderr, with no key or
other secret. For a failing kit check, use its first failing line. An incomplete
kit gets its own one-line refusal. A missing script or any nonzero exit stops
the sequence. The runner reports the failure and cleans up recorded resources.

## Cleanup record

`started.json` is a UTF-8 JSON object with two arrays of string IDs, `runs`
and `machines`. Record each resource as soon as its ID is known, so that the
runner can recover after interruption. Retain the IDs for cleanup retries.
Stop runs before their machines. Cleanup treats an already stopped resource
as success. These IDs are synthetic.

```json
{"runs":["run-syn1"],"machines":["machine-syn1"]}
```

An absent record before any resource starts, or this empty record, requires
no cleanup. An unreadable record is an error.

```json
{"runs":[],"machines":[]}
```

## Kit output

`kit.txt` contains the kit's result lines in UTF-8, one per line. The live-check
step writes any result lines it obtained, even on failure. The five check
names must appear in kit order, with each line beginning `pass <check>:` for
the kit to count as 5 of 5.

```text
pass version: driver schema matches
pass start: run-syn1 started
pass wake: run-syn1 resumed
pass stop: run-syn1 stopped
pass token: no credential reached the driver
```

Four passing lines without the token check are incomplete.

```text
pass version: driver schema matches
pass start: run-syn1 started
pass wake: run-syn1 resumed
pass stop: run-syn1 stopped
```

The runner treats missing, incomplete or failing kit output as a failure even
if the step exits 0. Only the runner may request the settings change. After
all three successful steps and 5 of 5, it calls
`openwiz settings set drivers.<driver> on`. A failed settings write is an
install failure and triggers cleanup. On success, report the result, the five
kit lines and how to turn the driver off with
`openwiz settings set drivers.<driver> off`.

This interface grants no authority to run a step against a live host.
