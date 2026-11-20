# Weekly skills-eval tick

Each week the loop turns last week's mistakes on GitHub into synthetic eval cases, scores them, and hands any fix or cut to the orchestrator as an ordinary ticket. `run.py` never starts a builder, reviewer, replay or live arm, never merges and never pays. Python standard library; its only program is `gh api`, used by `sources`, `tick` and `handoff`.

```sh
OPENWIZ_PRIVACY_LITERALS=<synthetic list> python3 -I tools/skills-eval/weekly/test_weekly.py   # offline proofs
python3 -I tools/skills-eval/weekly/run.py dry-run --out DIR      # a synthetic week: report.md and report.json
python3 -I tools/skills-eval/weekly/run.py loop-definition --prompt-file FILE   # the one loop create command
```

`collect.py` reads every page of the week's issue and pull request comments, inline review comments and reviews; any failed or partial read refuses the whole week. `run.tick` saves a prepared week, then commits cases, provenance and checkpoints in one atomic replacement, so a crash resumes without reading again. Evidence is `fake` (fixtures, zero cost) or `measured` (real E1 scores and costs, labelled `measured run`).

## Weekly runbook (#1363)

1. **Collect** the UTC week that ended at this Monday 00:00: `run.py sources --repo OWNER/NAME --week W` prints its records to the terminal only. Write a drafts file mapping **every** printed URL to `null` or `{incident, case}`: a synthetic E1 case, with no quotes or links.
2. **Tick:** `run.py tick --repo R --week W --state DIR --drafts FILE --report DIR`, adding `--experiments`, `--baseline`, `--evidence`, `--cuts` and `--tokens` files when their owners have them. An undecided URL, a bad draft or a read gap leaves the last checkpoint as it was and reports the gap.
3. **Baseline first.** New cases need a new baseline (`--baseline` is `{settings, score}`, or `{mode: "measured", settings, score}`). Failing cases route one `fix` per caught skill. Cuts wait for a passing result at the same cases hash and must compare cleanly with it under `E1.compare`; a passing cut routes one `cut` ticket.
4. **Stages.** `--experiments` holds each experiment's import summary. A changed experiment hash or completed stage refuses the tick: a new candidate is a new tag. Replay is proposed only after research and CF4 passed, live only after replay too. Anything not run prints `unobserved`, never zero.
5. **Route once.** Each action is recorded with a stable key in `weekly.json`. `run.py pending --state DIR` lists the queued ones; for each run `run.py handoff --state DIR --repo R --issue 1358 --key KEY` and nothing else. It posts one comment with a `weekly-handoff: KEY SHA256` line and a `payload:` line, unless that exact comment already exists; after a failed read it posts nothing. Never post a handoff by hand.
6. **Report.** Post `report.md` on spec #1358: cases added, pass and fail, actions, stages, blocked steps, tokens and gaps. If nothing is new, say so and archive the tick.

**State** lives in `private/evidence/skills-eval/e3/state/` on `main`, because each run is a fresh sandbox: `state.json` and `weekly.json` (never the lock files) land through the week's ordinary infra pull request. If last week's has not merged, report that and advance nothing.

**Starts.** `--starts` defaults to `deferred`: builder work waits behind CI priority periods and `fleet.sh overload`. Pass `allowed` only when the orchestrator's records say builder starts are open. Deferred actions stay pending under their keys until a later tick routes each once.

**Stop and resume:** `room-cli loop pause|resume|delete <id>`; the id stays in private orchestration state. Tick a missed week by hand with the same commands; a repeat is a no-op.

## Gaps

- No real weekly result yet: #1362's real baseline, cuts and token reports gate it; the measured path is proven only on synthetic E1 outputs.
- Required-text tokens are not measured (E1 reports bytes), so they print `unobserved`.
- Reviews are found through their pull request's `updated_at`; the reader and the handoff are proven on a fake `gh` only. The handoff marker doesn't check its author, so a full copy of a real handoff would count.
