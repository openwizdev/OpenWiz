# Fleet load: FA3's 100-ticket fake fleet and launch-fleet's carried helpers

WZ4 (#2634) moved these load tests here from `skills/launch-fleet/test/load/`,
unchanged in cases, so the skill stands alone in WizSkills: they drive
OpenWiz's own scale harness (`cargo`, `tests/`, `tools/scale-50`). They still
run the skill's real `fleet.sh` and fixtures at `skills/launch-fleet/scripts/`.

```sh
sh tools/fleet-load/ci.sh   # all of it, for CI (WZ12 wires it in)
python3 -I tools/fleet-load/test_carried.py
python3 -I tools/fleet-load/standalone/dry_run_report.py   # WZ-P3/P4 for launch-fleet
```

`test_carried.py` fails, naming the copy, when any file launch-fleet carries in
`scripts/carried/` (and its stage-bench fixture) differs from its ClosedWiz
source under `tools/`, is missing, or is unlisted. Change the source, then copy
it. `ci.sh` also runs `tools/review-relay/test_router.py`, which launch-fleet's
`test-loop.sh` used to run. `dry_run_report.py` runs the skills copy's dry run
and prints launch-fleet's standalone and privacy results; it exits 0 only when
both pass. `evidence/` holds its red run.

Two expectations follow the current `fleet.sh`, since these tests ran in no
CI: an event wake on an owned fleet prints only its `wake fleet #S` line (GI2,
#2544), and a back-off tick may make GI1's (#2543) cached-ETag REST probes
before its one GraphQL read. `transport.py` models the repository-privacy
question (#1273).

## FA3: 100-ticket fake fleet

Run the affected proof only (Python standard library, `sh`, `jq`, SHA-256 tools):

```sh
python3 -I tools/fleet-load/test.py --report /tmp/fa3-report.json
```

This runs the real `skills/launch-fleet/scripts/fleet.sh spec` across five
approved synthetic specs, each with 20 tickets. A fixed virtual clock advances
10 minutes per tick, with a ten-minute wall-clock deadline; no sleeping, background watcher or live endpoint is used.
Five tickets wait for a verified predecessor merge. GitHub records persist
between ticks; each spec retains its own fleet identity.

The skill follower consumes due lines, writes claims/outcomes, starts fake
builders and reviewers, routes CI failures/findings/re-checks, merges synthetic
PRs and archives agents. Five builders have no branch for 40 minutes; five
reviewers withhold their verdict until the 30-minute notice. Other builders
produce CI failures and review findings before completing. The fake CloudRoom
endpoint independently refuses operations on another fleet's child.

`fake.py` reuses the existing read-only `skills/launch-fleet/scripts/fixtures/gh.py`, adding only
file-backed writes and a recording fake `room-cli`. Every command is recorded
with its arguments, owner, time, status and synthetic GraphQL cost. Unknown
commands fail. Temporary state is private to each run and removed at exit.
The reader's parallel calls never rewrite the world. The workload's fake
writes are synchronous.

The checker asserts exact starts/merges/archives, expected spec ownership,
CI/approval before merges, completion before archives, findings and re-check counts,
blocked-ticket order, notices within 1,800 simulated seconds, and a rolling
1,250-point/hour GraphQL budget across all five fleets. Reported questions
must match recorded commands, and reported points must match returned fake
costs. A low-allowance tick must exit 0 with exactly one back-off line, no due
work and one GitHub read. REST command counts are recorded separately from
GraphQL cost; a command is **not** a measurement of underlying HTTP traffic.

Head-bound instructions retain their emitted SHA in review claims, agent
messages, merge arguments and scheduled verdicts. A review of A never approves
B merely because the PR changes before the verdict task runs. Each emitted
notification is reconciled with its recorded command/effect by action, PR,
ticket, SHA, owning fleet, exact recipient and tick, including command/metadata
consistency and exact multiplicity. Merge must precede archive in event order;
equal virtual timestamps do not weaken that rule.

The proof plants duplicate/missing starts, missed quiet builder/reviewer,
budget overrun, foreign-owner routing/starts, a missing or premature archive,
wrong reviewer coverage, wrong printed or actual same-fleet recipients/roles,
unaccounted command cost, an unsafe merge and same-tick premature archival in the observed
trace and requires each to fail with its specific claim. These mutations check
the checker; they do not pretend the fake endpoint or skill is production code.

For #1227 to extend this existing workload instead of making another one:

```sh
python3 -I tools/fleet-load/load.py --verify-report /tmp/fa3-report.json --plant duplicate
python3 -I tools/fleet-load/load.py --fleet /absolute/candidate/fleet.sh
```

The focused `HeadProof` cases change PR heads during reviews and dispatch stale
review/re-check/merge/notification instructions through the real recording fake.
The default command runs these with the load and verifier cases.

For a changed checker, replay the recorded workload without paying for another
load run:

```sh
python3 -I tools/fleet-load/test.py --verify-report /tmp/fa3-report.json LoadProof
```

Reports from the pre-review message format lack notification PR/ticket
identity; regenerate them instead of replaying them with this stricter checker.

`run(fleet=None)` returns `tickets`, `specs`, `events`, `ticks`, planted `quiet`
intervals, final synthetic world, the command-index interval for every check, and the candidate script's SHA-256. `verify`
checks that trace; `plant` corrupts an observed effect. `Workload` holds the
fixture/schedule/command seams. The report is an extension seam, not the
versioned performance-report contract that #1227 owns.

This is fixture evidence for S1–S4, not a live observation. The follower models
the skill's actions; it does not run an LLM or prove that an agent follows the
skill. Overlapping claim elections, takeover and post-check builder inactivity
remain covered elsewhere or unverified. Rust fleet-tick and underlying HTTP
pagination/REST allowance measurement belong to #1227. No workflow file is
owned here; the standalone invocation is ready for CI integration.

Synthetic assumptions: all ticket/spec/PR/commit/thread/loop identifiers, times,
work durations, findings and CI outcomes are invented. GitHub response shapes
reuse the existing fake. `_threads` and command events model a local fake
CloudRoom endpoint, not an observed CloudRoom response contract. The fake rate
limit has a fixed remaining balance; rolling usage is checked independently.

## #1227: bounded 50-agent baseline

The existing test invocation now uses the scale profile, retaining `verify` and
all original FA3 mutation proofs. Its FIFO **fixture schedule** admits at most 50 running recording agents
together; accepted queued receipts and idle work do not count as active. It advances up to 30 virtual timer
cycles without sleeping. This is no production fleet limit. Explicit execution intervals end when PR/fix/CI/verdict work completes; findings
and re-checks resume the appropriate agent through the same admission queue.

```sh
python3 -I tools/fleet-load/test.py \
  --report /tmp/fa3-scale-trace.json --scale-report /tmp/scale-baseline.json
python3 -I tools/scale-50/report.py /tmp/scale-baseline.json
python3 -I tools/scale-50/test_report.py
```

Every installed-tick invocation first refreshes the fixture CLI example with an incremental
`cargo build --locked -p openwiz-tests --example openwiz -j 2 --target-dir target` (project
dependencies only). This uses the real installed tick dispatcher and the existing
B5 recording executor on FA3's same initial 100 tickets/five specs. It verifies 95
eligible frontier actions and five blocked successors, with no writes or state
creation. This dry-run route is distinct from the follower's active lifecycle;
no installed write/lifecycle parity or installed HTTP measurement is claimed.

`transport.py` observes existing fake response pages and explicitly models CLI
internal exchanges (revision reads and writes). Shared consumers have separate
request events. REST requests and GraphQL requests/costs are independently
checked across reset windows. Live gh internals, allowances and secondary limits
remain unknown. See `tools/scale-50/report-format.md` for timing boundaries,
comparison refusal, synthetic assumptions and downstream seams.

Additional mutations remove an internal response page, exceed the HTTP cost
budget, omit a verified read-back or starve an eligible merge. All must fail by
name. The original duplicate, quiet-agent, GraphQL budget and head/owner/ordering
guards still run. Replay the extended recorded trace with the existing
`--verify-report ... LoadProof` option to inspect/report without another load run.
The standalone `load.py` keeps its legacy profile for existing FA3 consumers.

Duplicate event wakes run concurrently through `fleet.sh wake` at cycles 0 and 3;
their wall intervals must overlap and each must defer to the owning fleet with
only its one `wake fleet #S: room-cli loop run <loop>` line (GI2, #2544).
The timer performs the actions. One ticket is held for the first virtual cycle.
All shared-consumer charges and the original quiet-agent checks must pass before
an aggregate report can be complete. Trace identity is frozen before execution,
so replay never borrows workload/config/tool identity from the current checkout.

Candidate seam for #1229–#1231: `load.run(fleet=absolute_script, scaled=True)`
reuses this exact schedule and recording executors. `scale.report(trace)` verifies
FA3 safety and scale measurement before producing the v1 aggregate. #1228/#1237
consume `report.read(path)` and `report.compare(baseline, candidate)`; their live
kit/authority and final capacity validators remain their own work.


The frozen `measurement_model` names the load/transport/report sources, reused
GitHub cost/page executor, approval revision script, B5 executor and fixture
entrypoints by content hash. Comparisons require this model to match; candidate
fleet script/binary changes remain separate and are disclosed. Legacy traces
without these fingerprints produce partial reports with an unknown model and
cannot be compared. They are never retroactively assigned today's model.

Review regressions are part of the existing invocation. They can also run alone:
`python3 -I tools/fleet-load/test_seams.py`. The stale-build regression
uses a private, std-only Cargo fixture to prove source changes refresh an existing
example; the full workload separately exercises the real current dispatcher.

Cargo's `compiler-artifact.executable` selects the freshly built example; no
`target/debug` path is assumed. The source-change regression covers native
`CARGO_BUILD_TARGET`, `.cargo/config.toml` `build.target` and a separate ambient
target directory, with an old native artifact deliberately left in place.
