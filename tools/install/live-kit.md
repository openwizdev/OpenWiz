# 0.0.13 live kit: install line to a running first fleet

The bounded kit T8 (the version's live check) runs. **Preparing it performs nothing live.** No step here runs until Jake's one version-level kit OK for 0.0.13 is recorded and the earlier versions' live gates have passed (ADR 0016). This file grants no live, account, spending, release or publishing authority by being merged.

The kit's offline dry run and its result validator are `live-kit-test.py` beside this file: `python3 -I tools/install/live-kit-test.py` runs its proofs, `dry-run` walks every step with a simulated clock and no effect, and `validate <result.json> --candidate <candidate.json>` checks a recorded result. A passing dry run proves the kit's shape and its timer and result rules, never a live result.

## Candidate binding

Every result names exactly one candidate: `version` (`0.<minor>.<patch>`), `source` (the full 40-character lowercase commit), `tree` (the full 40-character lowercase tree) and `manifests`, the published manifest's SHA-256 for each of the three declared targets. The validator refuses a malformed identity, even when the result and the candidate file agree, and a result for any other candidate. Read the candidate's green fixture integration and this kit's passing dry run back before step K1.

## Steps

Each step is bounded. `read` steps change nothing; `write` steps act only on test-owned, disposable resources; `spend` steps may use Cloud Credits within the stated bound. Stop at the first step whose bound would be exceeded and record a gap.

| Step | Name | Effect | Bound |
| --- | --- | --- | --- |
| K1 | discovery | read | Read-only discovery of the actual hosts, release, CloudRoom, Loop and free-plan credit source; record what exists |
| K2 | fresh-host | write | One fresh disposable user account or machine per declared target; no prior OpenWiz state |
| K3 | install-line | write | Submit the public install line once to the chosen agent; start the timer at submission |
| K4 | setup | write | Setup on a disposable repository and existing test project only; App on that repository only |
| K5 | engine | spend | One engine for the test project; measure idle Cloud cost on a free account for the recorded window |
| K6 | first-fleet | spend | One newly grilled and approved plan of 4 to 7 tickets; at most 7 builders, test-owned threads only |
| K7 | fleet-running | read | Read back running builders until at least four of that plan run at once; stop the timer then |
| K8 | reviewed-ticket | write | One first-fleet ticket through the existing independent review and merge path |
| K9 | lifecycle | write | One engine restart or wake, one refused access case, one update, recovery and removal on disposable state |
| K10 | phone | read | One authenticated phone-emulated Chromium connection, cut and reconnect |
| K11 | cleanup | write | Stop only the kit's own threads, loops and disposable resources; keep the evidence |

## Timing definition

- **Start:** the wall-clock moment the install line is submitted to the agent (K3), in UTC milliseconds.
- **Stop:** the first moment at least four builders of the newly approved 4-to-7-ticket plan are running at the same time, read back from the fleet view (K7).
- **Elapsed** is stop minus start, exactly. Setup and approval waits and any help the user needed are inside it: they are recorded, never subtracted. The timer is never restarted; a second attempt is a new attempt, and the first attempt's result stands.
- **Pass** only when elapsed is an integer number of milliseconds under 600,000 (under 10 minutes) and the fleet really ran; exactly 600,000 ms is a miss. Anything else is a fail, and a step that could not run is a gap. A fixture or dry run never sets elapsed time.

## Result

One JSON object, `openwiz.live-kit-result.v1`, with exactly these fields:

- `candidate`: `version`, `source`, `tree`, `manifests` (target to SHA-256), matching the bound candidate;
- `attempt`: 1 for the timed attempt;
- `platform`: one declared target;
- `line_submitted_at_ms`, `fleet_running_at_ms` (null if never reached) and `elapsed_ms` (integer milliseconds, exactly stop minus start; null if never reached);
- `plan_tickets` (4 to 7) and `builders_concurrent` (the most running at once, at most `plan_tickets`);
- `waits` and `help`: lists of `{"kind", "ms"}` and `{"kind"}`, recorded and never subtracted;
- `choices`: `agents` and `engine`, each `cloud` or `local`;
- `credits`: `provenance` (`measured`, `estimated` or `unknown`) and `value` (null when unknown);
- `steps`: one entry per kit step, `{"step", "outcome"}` with `pass`, `fail` or `gap`;
- `outcome`: `pass`, `fail` or `gap`, and `reasons`: plain public sentences.

Values are sanitized aggregates and evidence classes only: no account names, thread or project ids, tokens, emails or transcripts. The validator refuses anything that looks like one.
