# Mistral Vibe (`vibe`) harness row

Login: vibe's own sign-in: a Mistral account sign-in done once in vibe, or an API key you keep in the OS keyring or in your own MISTRAL_API_KEY; the row never reads, sets or stores a key

Effort: `--thinking low|medium|high|xhigh|max` at start only (vibe refuses `--thinking` on `--resume`); `off` is not taken

The row for [Mistral Vibe](https://github.com/mistralai/mistral-vibe) on the local driver, built against [harness-row.md](../../harness-row.md). Sources are read only, in mistralai/mistral-vibe at commit [`e76235b2`](https://github.com/mistralai/mistral-vibe/tree/e76235b203b8965af584e88e69284bc704c31a1f) (version 3.1.4); no sign-up, sign-in or paid call.

| Move | Command line (`row.json`) |
| --- | --- |
| Start | `vibe --prompt <prompt> --output json --model <alias> <mode> [--thinking <level>]` |
| Wake (same run) | `vibe -p <message> --resume <session id> <mode>` |
| Stop | the driver's stop: SIGTERM to the turn's process tree, then SIGKILL; `vibe -p` exits only after its app-server has |

Modes (`{mode}`): `auto-approve` is `--auto-approve`; `accept-edits` and `ask` are `--approval-policy accept-edits` and `--approval-policy ask`. In programmatic mode a tool call that would ask is denied, not prompted ([programmatic-mode.md](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/docs/programmatic-mode.md)). Wake passes the same mode, so a resumed turn keeps the approved permissions.

## The census fact: does `--resume <id>` hold in programmatic mode?

**Yes.** `--resume <id>` is a top-level option, not part of the agent-socket mode, and a plain `vibe -p … --resume <id>` continues the same saved session.

1. [`vibe/cli-rust/src/cli.rs`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/cli-rust/src/cli.rs) declares `--resume [SESSION_ID]` on the top-level `vibe` command beside `-p`/`--prompt`; only `--agent-socket` is hidden and experimental.
2. [`vibe/cli-rust/tests/units/headless_cli_flags.rs`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/cli-rust/tests/units/headless_cli_flags.rs), `headless_resume_with_an_id_reopens_that_session`: `vibe -p "go on" --resume abc` is a headless run on `HeadlessSession::Resume("abc")`; `--resume` without an id in programmatic mode is a usage error.
3. [`vibe/cli-rust/src/headless/open.rs`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/cli-rust/src/headless/open.rs): a headless `Resume(id)` opens the saved session with the app-server's `session/resume`, not a new one.
4. [`tests/e2e/test_programmatic_headless_contract.py`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/tests/e2e/test_programmatic_headless_contract.py), `_assert_resumable`, used by `test_stop_signal_stops_the_turn_and_its_tool_and_exits_three`: a plain `vibe -p` run, no agent socket, is stopped with SIGTERM, then `vibe -p "Carry on" --resume <session_id>` exits 0 under the same `session_id`.
5. [`docs/programmatic-mode.md`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/docs/programmatic-mode.md), outside the Agent Socket section: `--time-limit` says a stopped "session can be resumed with `--resume`" and that "SIGTERM stops a run the same way"; `--output` says that on a resumed session `json` "holds the whole session".

**Stop leaves nothing running.** The same page, Exit codes: "`vibe -p` exits only after its app-server process has, however the run ends", and SIGKILL takes the app-server with it. The SIGTERM test above also asserts the run's tool process is gone. The driver's stop ends the turn's whole process tree, and the row's check needs the background process its fake starts to be gone after stop.

**The session id.** `--output json` prints the run's history once, at the end, as one pretty-printed JSON array ([`headless_output.rs`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/cli-rust/src/headless_output.rs), `finalize`), and every entry carries `session_id` ([`_history_projection.py`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/app_server/_history_projection.py), `_history_fields`). That output is not one JSON object per line, so the row reads the id with a `pattern` on the entry's own `"session_id"` line (four spaces in, as a pretty-printed array's entries are); a prompt quoted in the output has its quotes escaped, so it can't match. Until the first turn has printed it, wake refuses.

## Effort

**Form: an effort map, `--thinking <level>` at start.** Vibe's reasoning-effort option is `--thinking LEVEL` ([programmatic-mode.md](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/docs/programmatic-mode.md), Options; `cli.rs`). It sends `reasoningEffort` with `session/start` for that session only, without saving it as the default ([`headless/config.rs`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/cli-rust/src/headless/config.rs); [`tests/units/headless_model.rs`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/cli-rust/tests/units/headless_model.rs), `the_thinking_level_is_picked_for_this_session_only`).

- **Start only.** `--thinking` (and `--model`) on `--resume` is a usage error, "--thinking only applies to a new session" (`cli.rs`; `headless_model.rs`, `thinking_on_a_saved_session_is_a_usage_error`). The session keeps its level: the app-server pins it at turn start "so a reopen does not read the host's" ([`_unified_harness_backend_adapter.py`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/vibe/app_server/_unified_harness_backend_adapter.py), `_persist_session_reasoning_effort`).
- **No `off`.** Vibe sends the user's level "as written: the provider says whether the model takes it", except `off`: a model known to have no reasoning gets no field, and one that cannot stop gets its lowest level, with no error ([`completion_profile/reasoning.py`](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/harness/runtimes/python/python/mistralai_vibe_local_harness/vibe/completion_profile/reasoning.py), module note and `request_reasoning`). So the row maps `low`, `medium`, `high`, `xhigh` and `max`, and an `off` effort, like any value it doesn't list, is refused with the contract's D3 error and starts nothing.
- **Unverified:** whether the Mistral API refuses a level a model lacks rather than ignoring it is the provider's behaviour, not Vibe's; the row's live check observes it. An agent profile or admin config that fixes the model's level makes Vibe refuse `--thinking` as a usage error (exit 1), not drop it.

## Errors

- **Not installed:** no `vibe` on `PATH`: the driver's D3 error, whose `next` says to install `vibe` and sign in to it yourself (install: `uv tool install --python 3.14 mistral-vibe`, [README](https://github.com/mistralai/mistral-vibe/blob/e76235b203b8965af584e88e69284bc704c31a1f/README.md)).
- **Not signed in:** `vibe -p` exits 1 with `Error: Missing MISTRAL_API_KEY environment variable for mistral provider` (`vibe/core/config/models.py`, `MissingAPIKeyError`; `vibe/cli-rust/src/headless.rs`). The driver's first-turn watch turns that into a D3 error whose `next` says to read the run's log, which names the missing sign-in, and start again. To sign in, run `vibe` once and sign in with your Mistral account, or set `MISTRAL_API_KEY` in your own environment.

## Fake and tests

`fake` allows only the two command lines above and refuses (exit 2) any other, including `--model` or `--thinking` on `--resume`. `test_row.py` checks the not-installed and not-signed-in errors, the refused `off`, and that the session pattern reads the real output's shape. `evidence/` keeps the red and green runs. Every run had no-op stubs for the known agent CLIs first on `PATH`; no real agent CLI ran.
