# Mistral Vibe (`vibe`) harness row

Login: vibe's own sign-in: a Mistral account sign-in done once in vibe, or an API key you keep in the OS keyring or in your own MISTRAL_API_KEY; the row never reads, sets or stores a key

Effort: none

The row for [Mistral Vibe](https://github.com/mistralai/mistral-vibe) on the local driver, built against [harness-row.md](../../harness-row.md). Sources are read only, in mistralai/mistral-vibe at commit [`e76235b2`](https://github.com/mistralai/mistral-vibe/tree/e76235b203b8965af584e88e69284bc704c31a1f) (version 3.1.4); no sign-up, sign-in or paid call.

| Move | Command line (`row.json`) |
| --- | --- |
| Start | `vibe --prompt <prompt> --output json --model <alias> <mode>` |
| Wake (same run) | `vibe -p <message> --resume <session id> <mode>` |
| Stop | the driver's stop: SIGTERM to the turn's process tree, then SIGKILL; `vibe -p` exits only after its app-server has |

Modes (`{mode}`): `auto-approve` is `--auto-approve`; `accept-edits` and `ask` are `--approval-policy accept-edits` and `--approval-policy ask`. In programmatic mode a tool call that would ask is denied, not prompted ([programmatic-mode.md](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/docs/programmatic-mode.md)). Wake passes the same mode, so a resumed turn keeps the approved permissions.

`--trust` is left out on purpose: it trusts the working directory for that run, which makes `vibe -p` load the project's own `.vibe/` config, agents, tools, hooks and MCP servers ([`cli.rs`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/cli-rust/src/cli.rs), `--trust`; [programmatic-mode.md](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/docs/programmatic-mode.md)). Whether a folder is trusted stays the user's choice in Vibe.

## The census fact: does `--resume <id>` hold in programmatic mode?

**Yes.** `--resume <id>` is a top-level option, not part of the agent-socket mode, and a plain `vibe -p … --resume <id>` continues the same saved session.

1. [`vibe/cli-rust/src/cli.rs`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/cli-rust/src/cli.rs) declares `--resume [SESSION_ID]` on the top-level `vibe` command beside `-p`/`--prompt`; only `--agent-socket` is hidden and experimental.
2. [`vibe/cli-rust/tests/units/headless_cli_flags.rs`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/cli-rust/tests/units/headless_cli_flags.rs), `headless_resume_with_an_id_reopens_that_session`: `vibe -p "go on" --resume abc` is a headless run on `HeadlessSession::Resume("abc")`; `--resume` without an id in programmatic mode is a usage error.
3. [`vibe/cli-rust/src/headless/open.rs`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/cli-rust/src/headless/open.rs): a headless `Resume(id)` opens the saved session with the app-server's `session/resume`, not a new one.
4. [`tests/e2e/test_programmatic_headless_contract.py`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/tests/e2e/test_programmatic_headless_contract.py), `_assert_resumable`, used by `test_stop_signal_stops_the_turn_and_its_tool_and_exits_three`: a plain `vibe -p` run, no agent socket, is stopped with SIGTERM, then `vibe -p "Carry on" --resume <session_id>` exits 0 under the same `session_id`.
5. [`docs/programmatic-mode.md`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/docs/programmatic-mode.md), outside the Agent Socket section: `--time-limit` says a stopped "session can be resumed with `--resume`" and that "SIGTERM stops a run the same way"; `--output` says that on a resumed session `json` "holds the whole session".

**Stop leaves nothing running.** The same page, Exit codes: "`vibe -p` exits only after its app-server process has, however the run ends", and SIGKILL takes the app-server with it. The SIGTERM test above also asserts the run's tool process is gone. The driver's stop ends the turn's whole process tree, and the row's check needs the background process its fake starts to be gone after stop.

**The session id.** `--output json` prints the run's history once, at the end, as one pretty-printed JSON array ([`headless_output.rs`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/cli-rust/src/headless_output.rs), `finalize`), and every entry carries `session_id` ([`_history_projection.py`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/app_server/_history_projection.py), `_history_fields`). That output is not one JSON object per line, so the row reads the id with a `pattern` on the entry's own `"session_id"` line, four spaces in as a pretty-printed array's entry keys are, so a nested object's `session_id` deeper in can't match, nor a quoted prompt, whose quotes JSON escapes. Until the first turn has printed it, wake refuses.

## Effort

**Form: `none`.** `row.json` has `"effort": "none: <why and source>"`, and `start` has no `{effort}`. Vibe has a reasoning option, `--thinking LEVEL` at start only ([programmatic-mode.md](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/docs/programmatic-mode.md), Options), but on some models it runs different levels the same without saying so, and HR1 says a row must not claim an effort its CLI silently ignores for some models.

- **The collapse.** For a model that takes a thinking token budget instead of an effort, Vibe maps the level through `THINKING_BUDGET_TOKENS`: `low` 4096, `medium` 16384, and `high`, `xhigh` and `max` all 32000 ([`completion_profile/reasoning.py`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/harness/runtimes/python/python/mistralai_vibe_local_harness/vibe/completion_profile/reasoning.py)). `claude-haiku-4-5` is one such model ([`completion_profile/known_models.py`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/harness/runtimes/python/python/mistralai_vibe_local_harness/vibe/completion_profile/known_models.py), `ReasoningControl.BUDGET_TOKENS`). A user who moves its effort from `high` to `max` gets the same run, and nothing reports it.
- **What a start with an effort does.** Any explicit effort, `off` included, is refused with the driver's D3 error before anything starts, and its `next` is exactly `this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default`. A start without an effort runs at the level Vibe's own config gives the model.
- **The driver's `version` answer** has a fixed schema with no per-row note (HR1, section 4); this README's `Effort: none` line is what it points at for this row.

## Errors

- **Not installed:** no `vibe` on `PATH`: the driver's D3 error, whose `next` says to install `vibe` and sign in to it yourself (install: `uv tool install --python 3.14 mistral-vibe`, [README](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/README.md)).
- **Not signed in:** `vibe -p` exits 1 with `Error: Missing MISTRAL_API_KEY environment variable for mistral provider`, or, when the keyring can't be read, `Error: Can't read MISTRAL_API_KEY from the system keyring for mistral provider (<error>). Unlock the system keyring or approve its prompt, or set the MISTRAL_API_KEY environment variable` (`vibe/core/config/models.py`, `MissingAPIKeyError`; `vibe/cli-rust/src/headless.rs`). The row's `signed_out` patterns match both, anchored to the whole `Error: ` line Vibe writes to stderr when a run fails ([`headless.rs`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/cli-rust/src/headless.rs)) (a successful run whose JSON history quotes the message, indented and in quotes, still starts). On either line `start` fails as `the harness is not signed in`, a D3 error whose `next` names the row's `login_command`, `vibe --setup`: Vibe's "Setup API key and exit" option, which opens its setup wizard with the Mistral sign-in and exits without a session ([`cli.rs`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/cli-rust/src/cli.rs), `--setup`; `vibe/cli-rust/src/main.rs`; `vibe/cli-rust/src/setup/wizard/sign_in.rs`). Setting `MISTRAL_API_KEY` in your own environment works too.

## Fake and tests

`fake` allows only the two command lines above and refuses (exit 2) any other, including `--thinking` anywhere and `--model` on `--resume`. `test_row.py` checks the not-installed error, that a successful history quoting both sign-in diagnostics still starts, that both real diagnostic lines read as signed out, that a start printing the full keyring line is not signed in and starts nothing, that every explicit effort (`low` to `max`, and `off`) is refused starting nothing, and that the session pattern reads the entry's own id, not a nested one; the kit's own signed-out check covers the missing-variable start. `evidence/` keeps the red and green runs, including those for review findings R1, R2 and R3. Every run had no-op stubs for the known agent CLIs first on `PATH`; no real agent CLI ran.
