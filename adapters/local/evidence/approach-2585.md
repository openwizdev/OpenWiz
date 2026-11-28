# Approach note: #2585 (EF4 of #2471), local driver effort

## How effort is turned on

- **The field.** `effort` joins the driver's `START` fields as the one optional field (`^[a-z][a-z0-9-]{0,19}$`, driver v1). `read` takes a start with or without it; every other field stays required. `version`'s `can` gains `effort`, and nothing else changes in its answer.
- **One place decides.** HR1's hook `effort_of(harness, row, effort)` gives an effort's arguments and environment, or the refusal. It is extended to the built-ins with a small table of levels per CLI. `command(state, woken)` splices them into every turn, start and wake, from the saved request, so a wake runs at the start's effort.
  - `claude`: `claude -p <prompt> --model <model> --permission-mode <mode> --effort <level>`, for `low`, `medium`, `high`, `xhigh` and `max`. Claude Code's own `CLAUDE_CODE_EFFORT_LEVEL` outranks `--effort`, so the turn's environment also gets that variable set to the same level. Otherwise an exported value would silently win. `ultracode` is not passed: it is a mode that runs as `xhigh`, not an effort level.
  - `codex`: `codex exec -c model_reasoning_effort=<level> --model <model> --sandbox <mode> <prompt>`, for `low`, `medium`, `high`, `xhigh`, `max` and `ultra`.
  - Harness rows: unchanged HR1 behaviour. They follow their row's `effort` form: a mapped value adds its arguments or `env`, and `none` or an unlisted value is refused.
- **Refused before cloning.** With an effort, `program()` decides before it looks for the CLI, saves a run or clones. The refusal is the D3 error naming the harness and effort, with `next` exactly driver v1's refusal text. This covers an unlisted level for `claude` or `codex`, a row whose form is `none` or that lacks the value, and an unknown harness (no row folder). A broken row keeps its own row error, because the row must be fixed first.
- **The levels are checked against the CLI's help.** Each CLI's `--help` lines for its effort option, taken from its published CLI reference (never by running it), are kept as fixtures. A test needs the driver's level table to be exactly the levels those lines list.
- **README:** an `Effort:` line under the login line, then a table by harness. HR1's `version` hook points at that table, since `version` carries no note.

## Threats

1. **A flag the CLI silently ignores for some models.** Claude Code documents that a level the model doesn't support runs at the highest supported level below it, and that an org or settings cap can lower it. `CLAUDE_CODE_EFFORT_LEVEL` outranks `--effort` (closed by setting it too). Codex says its levels depend on the model. The driver passes exactly the level and can't see the model's own list. The README says so, and this is listed as a gap.
2. **An effort lost on wake or resume.** The effort is saved with the request, and every wake's command line is rebuilt from it. A test wakes a run and needs the flag on the wake turn.
3. **An unknown harness getting the legacy error.** With an effort, an unknown harness gets the effort refusal, not "use one of". Without an effort it keeps today's error.
4. **A level passed that the CLI doesn't list.** Only the fixture-checked levels are passed. Anything else is refused, with no near value substituted, no default and nothing cloned.

## What the fixture tests can and cannot prove

- They can prove these things on the synthetic `claude`, `codex` and `gh`:
  - each level reaches the fake CLI's argv, and the claude env var reaches the turn, at start and at wake;
  - the fake exits 2 on any flag form or level its fixture help doesn't list;
  - refusals start nothing and clone nothing;
  - `version` lists `effort`.
- They can't prove that real `claude` or `codex` honour the flag, or which levels a given model supports. No real `claude` or `codex` ever runs. The tests run with no-op stubs for every known agent CLI first on `PATH`, and the test's own fakes go ahead of them. The help lines come from each CLI's published reference, not from a binary, so the CLI versions are the reference pages' dates.
