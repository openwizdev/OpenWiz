# Stall alarm

`alarm.py` is a script-only Local loop on the PC: each tick it reads the war room collector's `merges` and `open_prs` facts and the fleet loop's status, keeps its own alarm state, and prints one line per new stall. A quiet tick prints nothing (exit 0); alarm lines exit 1. An alarm still confirmed 30 minutes later prints one extra `JAKE:` line, once; recovery is silent and rearms it. It starts no agent and sends no message. `stalls.py` lists stalled tickets from one collector snapshot. Python 3 standard library.

```sh
python3 -B -I tools/stall-alarm/test.py                     # offline proofs (`Alarm`, `FlowStalls`, `CollectorFixtures` slices)
python3 tools/stall-alarm/alarm.py --repo OWNER/NAME --fleet-loop LOOP_ID --state STATE.json   # a real read
python3 -I tools/stall-alarm/stalls.py --input snapshot.json
```

The real read needs `tools/collector/collect_factory.py` beside it (or its absolute path in `STALL_ALARM_COLLECTOR`) with a logged-in `gh`, and the managed local `room-cli` (or an absolute `STALL_ALARM_ROOM_CLI`). Options: `--base` (default `main`, the default branch), `--check NAME` (repeatable, default `ci`), `--fleet-grace` seconds (default 600), `--deadline` to lower the 40-second read budget, `--now` for proofs.

## What fires

| Alarm | Fires when | Clears when |
| --- | --- | --- |
| Fleet loop | The loop is disabled, has a `last_error`, or its last run is older than its cron cadence plus grace (or it never ran) | It runs on time without error |
| No merges | Nothing merged into `--base` in the last hour while an open, ready PR has `APPROVE` at its head, every required check green and is mergeable | A merge, or no such PR |
| Idle agent | A PR's latest record or verdict is `findings sent`, `CI failure sent` or `re-check sent` at its current head and is 60 minutes old | A new head, a newer record or verdict, or the PR closes |
| Failed read | A source failed, timed out or returned partial or malformed data | That source reads cleanly again |

The cadence comes from the loop's cron: minute `*`, `*/N`, one minute or a list, with `*` in the other four fields; anything else fails the read.

## The stall rule (`stalls.py`)

A claimed, open, unmerged ticket is stalled when its last progress (commit, record, CI result or verdict) is 30 minutes or more before the read point. Its cause is the first match of `ci` (a pending run), `jake` (latest record asks the orchestrator, told the user, parked or needs approval), `limit` (builder fallback due, or an API budget under 10%), `stuck`, else `unknown`. An unreadable or incomplete history, including a claimed ticket with no pull request yet, is listed as `unknown` and makes the day's count null, never zero.

## State

Use one private persistent state file outside the checkout per repository, base, checks and fleet loop; never reuse one across repositories (it is refused). Losing it rearms alarms and loses their escalation age. Keep it across script updates.

## Installing the loop

Ask before installing: it is a live change. From a Local thread on the PC, in a checkout that stays at that path on reviewed commits, build the script (it embeds the alarm and finds the bundled CLI each tick):

```sh
cat > /tmp/stall-alarm-check.sh <<'SH'
#!/bin/sh
if [ -z "${STALL_ALARM_ROOM_CLI:-}" ]; then
  for STALL_ALARM_ROOM_CLI in /tmp/.mount_*/resources/app.asar.unpacked/node_modules/bb-app/host-daemon/dist/room-cli; do
    [ -x "$STALL_ALARM_ROOM_CLI" ] && break
  done
fi
export STALL_ALARM_ROOM_CLI
SH
printf ': "${STALL_ALARM_COLLECTOR:=%s}"\nexport STALL_ALARM_COLLECTOR\n' \
  "$PWD/tools/collector/collect_factory.py" >> /tmp/stall-alarm-check.sh
cat >> /tmp/stall-alarm-check.sh <<'SH'
exec python3 - --repo example-owner/example-repo --fleet-loop loop_fixture \
  --state "${STALL_ALARM_STATE:-$HOME/.local/state/stall-alarm/example-owner-example-repo.json}" <<'PY'
SH
cat tools/stall-alarm/alarm.py >> /tmp/stall-alarm-check.sh
printf '\nPY\n' >> /tmp/stall-alarm-check.sh
```

Then create the loop, on its own schedule, never from the fleet loop it watches:

```sh
for STALL_INSTALL_CLI in /tmp/.mount_*/resources/app.asar.unpacked/node_modules/bb-app/host-daemon/dist/room-cli; do
  [ -x "$STALL_INSTALL_CLI" ] && break
done
"$STALL_INSTALL_CLI" loop create --project project_fixture \
  --name 'stall alarm example-owner/example-repo' --host "$PC_HOST" \
  --cron '*/10 * * * *' --timezone UTC --script-file /tmp/stall-alarm-check.sh
```

After an upgrade, or to switch repository, rebuild the script and replace the loop's stored script, keeping (or, for a new repository, renaming) the state file. The orchestrator routes the output; `JAKE:` lines are escalations for Jake. No live delivery has been observed.
