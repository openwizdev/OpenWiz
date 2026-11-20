# Fleet load

A fake 100-ticket fleet that runs launch-fleet's real `skills/launch-fleet/scripts/fleet.sh` against a recording GitHub and CloudRoom, on a virtual clock, and checks that it stays safe and within its API budget. Five synthetic specs of 20 tickets, 10 virtual minutes a tick, no sleeping and no live endpoint. Python standard library, `sh`, `jq` and SHA-256 tools; the installed-tick and timing parts also build the fixture CLI with Cargo.

```sh
sh tools/fleet-load/ci.sh                         # the full suite, CI's release:fleet-load (900 s workload, 60 s a command)
python3 -I tools/fleet-load/test_carried.py       # copies carried from WizSkills: missing, unlisted or drifted
python3 -I tools/fleet-load/test_seams.py         # review regressions alone
python3 -I tools/fleet-load/test.py --report /tmp/fa3.json [--scale-report /tmp/scale.json]
python3 -I tools/fleet-load/test.py --verify-report /tmp/fa3.json LoadProof   # replay a saved trace with the current checker
python3 -I tools/fleet-load/load.py --fleet /abs/candidate/fleet.sh            # the workload on a candidate script
python3 -I tools/fleet-load/load.py --verify-report /tmp/fa3.json --plant duplicate
python3 -I tools/fleet-load/scale-50/report.py /tmp/scale.json                 # the 50-agent report
```

## What it checks

- Exact starts, merges and archives per spec; CI green and approval before every merge; archive after merge; findings and re-checks routed to the right agent of the owning fleet; blocked tickets wait for their predecessor's merge.
- Quiet builders (no branch for 40 minutes) and reviewers are noticed within 30 virtual minutes.
- A rolling 1,250-point-an-hour GraphQL budget across all five fleets; a low-allowance tick backs off with one line and one read.
- Head-bound instructions: a review of one head never approves the next.
- The scale profile admits at most 50 running fake agents at once (a fixture schedule, not a fleet limit), and duplicate event wakes defer to the owning fleet.

Each check has a planted failure (`--plant`, and the mutation tests) that must fail by name. Old reports without notification identity or the frozen `measurement_model` can't be replayed or compared: regenerate them.

## Measuring

```sh
cargo build --locked -p openwiz-tests --example openwiz -j 2
taskset -c 0-3 python3 -I tools/fleet-load/measure_load.py --report /tmp/cost.json --trace /tmp/trace.json
python3 -I tools/fleet-load/measure_probes.py --report /tmp/probes.json \
  [--baseline OLD/fleet.sh --baseline-report /tmp/probes-before.json]
```

`measure_load.py` reports wall and CPU time per tick (GNU time needed); run it alone. `measure_probes.py` counts `gh` processes, GraphQL commands, requests and points, REST pages and 304s across cold, unchanged, changed and expired ticks; with `--baseline` every tick must cost no more than the baseline's.

All of it is fixture evidence: it models the skill's actions without an LLM, and proves no live HTTP cost, latency, secondary limit or CloudRoom response shape. See [scale-50/report-format.md](scale-50/report-format.md) for the report's fields and comparison rules.
