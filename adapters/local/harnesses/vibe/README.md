# Vibe (local runs)

Login: Vibe's own login: vibe --setup saves the key in the OS keyring, or in ~/.vibe/.env when no keyring is available, or you set MISTRAL_API_KEY yourself; the driver never reads or passes it

Effort: none

A harness row for the [local driver](../../README.md), in the shape of the [harness-row contract](../../harness-row.md). It runs [Mistral Vibe](https://github.com/mistralai/mistral-vibe) in programmatic mode on this machine only, and only when a start names `vibe`: no default changes. Every line below was read from `mistralai/mistral-vibe` at tag [`v3.1.5`](https://github.com/mistralai/mistral-vibe/tree/v3.1.5) (commit `fb7511a7`, the newest tag on 2026-11-28) and its docs there. Nothing was installed, run or signed in to. The row builds on the reviewed files of #2643 (for #2438): its effort finding, its untrusted clone, its keyring line and its app-server line come from there.

Live check: #3367

| Move | Command line (`row.json`) |
| --- | --- |
| Start | `vibe --prompt <prompt> --output streaming --model <alias> --auto-approve` |
| Wake (same run) | `vibe --prompt <prompt> --output streaming --resume <session id> --auto-approve` |
| Stop | the driver's stop: it ends the turn's process tree, Vibe's app-server included |

- **Start.** `--prompt` is programmatic mode: send one prompt, print the answer, exit ([`cli.rs`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/cli-rust/src/cli.rs), `prompt`; [`headless.rs`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/cli-rust/src/headless.rs)). It runs in the run's clone, the driver's working folder. `--output streaming` prints one JSON object per history entry ([`headless_output.rs`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/cli-rust/src/headless_output.rs); [programmatic-mode.md](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/docs/programmatic-mode.md), `--output`), and each entry carries `sessionId` ([`_history_projection.py`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/app_server/_history_projection.py)). The row reads the id from the first JSON line that has it.
- **No `--trust`.** An untrusted folder is not refused. Vibe only warns that the project's own configuration is ignored ([`headless_trust.rs`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/cli-rust/src/headless_trust.rs)). `--trust` would make the run load the clone's own `.vibe/` config, agents, hooks and MCP servers, so the row leaves it out and that stays the user's choice in Vibe.
- **Wake.** `--resume <id>` reopens the same saved session in programmatic mode; a bare `--resume` is a usage error there ([`cli.rs`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/cli-rust/src/cli.rs), `headless_session`). Wake passes no model: `--model` and `--thinking` are refused on a resume (`--model only applies to a new session`, `start_model`), and a resumed session restores the model it was pinned to on its first turn ([`_unified_harness_backend_adapter.py`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/app_server/_unified_harness_backend_adapter.py), `_persist_session_active_model`; Vibe's own test `test_active_model_is_pinned_on_first_turn_and_restored_on_resume` in [`test_configuration.py`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/tests/app_server/backend_contract/test_configuration.py)). So the session keeps its recorded model.
- **Stop.** `vibe -p` starts its app-server in its own process group (`process_group(0)` in [`server/child.rs`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/cli-rust/src/server/child.rs)) and exits only after it has ([programmatic-mode.md](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/docs/programmatic-mode.md), Exit codes). The row's `daemon` names it. The driver's stop ends the whole process tree, and the runner checks that the fake's stand-in for it is gone after stop. It stays a child of `vibe`, so this holds on Linux. The live check settles macOS.
- **Mode.** `auto-approve` passes `--auto-approve` (`--yolo` is its alias). In programmatic mode a tool call that would ask is denied, not prompted ([programmatic-mode.md](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/docs/programmatic-mode.md)), so a builder needs it.
- **Env:** none. The driver never sets `MISTRAL_API_KEY`.

## Model

`{model}` fills `--model <ALIAS>` as one whole argument: the alias of a model in the user's Vibe config or in the signed-in account's model catalog, "instead of `active_model` (new sessions only)" ([`cli.rs`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/cli-rust/src/cli.rs), `model`). Vibe's built-in aliases at v3.1.5 are `mistral-large-4-0` (its default) and `mistral-medium-3.5` ([`vibe_schema.py`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/core/config/vibe_schema.py), `DEFAULT_MODELS`).

Vibe does not fall back on a model it doesn't know: a session pick checks the alias first and fails the start, before any turn, with `Unknown model: <alias>. Available: <aliases>` ([`_unified_harness_backend_adapter.py`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/app_server/_unified_harness_backend_adapter.py), `_require_known_model`; [`server.py`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/app_server/server.py), `_apply_start_choices`). That is why the row has no `precheck`: Vibe refuses for itself, and it has no read-only command that lists models (its sessionless commands are `vibe update` and `vibe config schema`, [`cli.rs`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/cli-rust/src/cli.rs), [`config_command.rs`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/cli-rust/src/config_command.rs)). The fake refuses an empty or blank model.

## Effort

**Form: `none`.** `row.json` has `"effort": "none: <why and source>"`, and `start` has no `{effort}`. Vibe has `--thinking LEVEL`, at start only, but there is no read-only way to know whether a model takes the level, so the row can't keep the contract's rule that an effort is never silently ignored:

- **The level is sent as written, and the provider judges it.** `--thinking` takes `off`, `low`, `medium`, `high`, `xhigh`, `max` or any word, "sent as written" ([`cli.rs`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/cli-rust/src/cli.rs), `thinking`). Only Vibe's own requests are fit to a model's levels ([`completion_profile/reasoning.py`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/harness/runtimes/python/python/mistralai_vibe_local_harness/vibe/completion_profile/reasoning.py)). Vibe's own default models differ: `mistral-large-4-0` lists `low`, `medium`, `high`, and `mistral-medium-3.5` lists `off`, `high` ([`vibe_schema.py`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/core/config/vibe_schema.py)).
- **Off can be dropped.** For Mistral, `off` goes out only to a model known to reason ([`adapters/mistral.py`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/harness/runtimes/python/python/mistralai_vibe_local_harness/vibe/adapters/mistral.py), `reasoning_effort`).
- **Three levels collapse.** On a budget-token model (one Vibe knows is `claude-haiku-4-5`, [`known_models.py`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/harness/runtimes/python/python/mistralai_vibe_local_harness/vibe/completion_profile/known_models.py)), `THINKING_BUDGET_TOKENS` gives `high`, `xhigh` and `max` the same 32000 tokens (`reasoning.py`), and nothing reports it.
- **No precheck can tell.** Which models take which level lives in the user's config and the account's remote catalog, and Vibe has no read-only command that prints it (see Model).
- **A start with an effort** is refused with the driver's D3 error before anything starts, and its `next` is exactly `this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default`. A start without an effort runs at the level Vibe's config gives the model.

## Usage limits

`row.json`'s `limit` is `^Error: API error occurred: Status 429\b`. When a Mistral call answers 429, Vibe retries it itself (`_RETRYABLE_STATUSES` in [`adapters/_provider_failure.py`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/harness/runtimes/python/python/mistralai_vibe_local_harness/vibe/adapters/_provider_failure.py)). Once those retries are spent, the turn fails with the SDK's message, `API error occurred: Status 429. Body: <the provider's body>` (`SDKError` in `mistralai` 3.5.0, the version Vibe's [`uv.lock`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/uv.lock) pins, and `_message` in `_provider_failure.py`). Headless mode prints that on stderr as `Error: <message>` ([`headless.rs`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/cli-rust/src/headless.rs)) and exits 2 (`InfrastructureFailure`, [`run_export/model.rs`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/cli-rust/src/run_export/model.rs)). The line carries no reset time, so the driver waits its fixed minute and resumes once on the same session and model.

The interactive `Rate limits exceeded. Please wait a moment before trying again.` is the TUI's own text ([`event_handler.rs`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/cli-rust/src/event_handler.rs)) and never reaches programmatic mode. A refused payment (402) prints only the provider's own sentence, which Vibe's source doesn't fix, so the row has no pattern for it.

## Against boat.dev

Read from boat.dev's `boat prompt --help` at `boat 1.0.110` on 2026-11-28, provider `mistral` (Mistral Vibe):

| boat.dev offers | This row |
| --- | --- |
| model `mistral-large-4` (boat's default) | passed to `--model` as written. Vibe's built-in alias is `mistral-large-4-0`, so `mistral-large-4` runs only if the account's catalog lists that alias; otherwise Vibe refuses with `Unknown model` and starts nothing. Name `mistral-large-4-0` to be sure. |
| model `mistral-medium-3.5` | matches: a built-in Vibe alias. |
| model `mistral-small-4` | passed to `--model` as written: not a built-in alias at v3.1.5, so it runs only when the account's catalog lists it, and is refused plainly otherwise. |
| thinking `high` (boat's default) | not passed as an effort: the row's effort is `none` (see Effort). A start with no effort runs at Vibe's configured level, which is `high` for both built-in models, the same as boat's default. |
| thinking `none` | not passed: `--thinking off` can be dropped for a model Vibe doesn't know reasons (see Effort), so the row can't promise it. |
| `--fast`, `--ultrafast` | boat offers neither for `mistral`. |

On top of boat.dev, the row wakes the same session on its recorded model, waits out a 429 and resumes once, and names `vibe --setup` or `MISTRAL_API_KEY` when Vibe is not signed in. The live check (#3367) settles which catalog aliases the owner's account has.

## Signed out

Programmatic mode exits 1 with one of these on stderr:

- `Error: Missing MISTRAL_API_KEY environment variable for <provider> provider`;
- `Error: Can't read MISTRAL_API_KEY from the system keyring for <provider> provider (<error>). Unlock the system keyring or approve its prompt, or set the MISTRAL_API_KEY environment variable` ([`models.py`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/core/config/models.py), `MissingAPIKeyError`);
- `Error: You are not signed in to Mistral. Sign in and retry.` ([`_provider_credentials.py`](https://github.com/mistralai/mistral-vibe/blob/v3.1.5/vibe/app_server/_provider_credentials.py)).

`row.json` anchors each to that whole `Error: ` line, so a streamed answer that quotes one still starts. The `next` names `vibe --setup` and `MISTRAL_API_KEY`. The fake exits 2 if a key is placed on the command line. Vibe has no `--api-key` flag.

## Fake and tests

`fake` allows only the two lines above and exits 2 on any other: a key flag, `--trust`, `--thinking` anywhere, `--model` on a resume, a bare `--resume`, an empty or blank model, `--yolo`, another `--output`. It prints each signed-out line on request (`FAKE_CLI_SIGNED_OUT`), and Vibe's 429 line on request (`FAKE_CLI_LIMIT`). `test_row.py` checks the row's form, those refusals, the signed-out lines through the driver, that quoted lines still start, that every effort from `off` to `max` is refused with the fixed `next` and starts nothing, and AD2's limit end to end. In that check the first turn prints the 429 line, the driver logs one 60-second wait (its sleep stubbed), and resumes once with `--resume` on the same session, no `--model`, and the builder note on the same model. `evidence/` keeps the red and green runs. No test starts the real `vibe`. The runner puts no-op stubs for the known agent CLIs on `PATH`, with this folder's `fake` ahead of them.
