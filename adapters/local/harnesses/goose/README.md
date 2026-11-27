# Goose (`goose`) harness row

Login: goose's own login: `goose configure` saves the provider and model in ~/.config/goose/config.yaml and the provider key in the system keyring (or ~/.config/goose/secrets.yaml without one)

Effort: none

You sign in yourself with `goose configure`: it picks the provider and model and stores the provider's key in your system keyring. The row never reads, sets or stores a key, and the driver passes none.

## The row

- **Start:** `goose run -n <uuid> --model <model> --output-format json -t <prompt>` in the run's workspace.
- **Wake (same run):** `goose run -n <uuid> --resume --model <model> --output-format json -t <prompt>`.
- **Session id:** chosen (`{"chosen": "uuid"}`). The driver makes a UUID, names the session with it at start, and resumes that name at every wake.
- **Stop:** the driver's own stop ends the run's process tree. `goose run` starts no server, but `daemon` declares one background process: goose's developer shell runs each command in a new process group, with stdin closed and stdout and stderr on goose's own pipes, and deliberately leaves work the command backgrounds (a dev server started with `&`) running after the shell exits ([`shell_process.rs`](https://github.com/aaif-goose/goose/blob/v1.60.2/crates/goose/src/agents/platform_extensions/developer/shell_process.rs) `wait`, [`shell.rs`](https://github.com/aaif-goose/goose/blob/v1.60.2/crates/goose/src/agents/platform_extensions/developer/shell.rs) `run_command` and its test `shell_does_not_hang_on_backgrounded_process`). On Linux the supervisor adopts that orphan as subreaper and stop ends it. On macOS it leaves the turn's process group and can be orphaned between the supervisor's looks, so stop can miss it.
- **Platforms:** Linux only. macOS waits for a live stop on macOS that ends a backgrounded shell command (the live check, #2499).
- **Env:** `GOOSE_MODE=auto`, over your own setting. A headless run in `approve` or `smart_approve` mode fails at its first tool call, so `auto` is the one mode a `goose run` turn can use.
- **Permission mode:** one mode, `auto`, which adds no arguments (goose's mode is the environment setting above, not a flag).
- **Not installed:** the driver refuses and starts nothing. **Not signed in:** `goose run` prints `error: No provider configured. Run 'goose configure' first.` (or the same for the model) and exits 1. A provider that is chosen but whose key is missing from the keyring and the environment fails the same way: goose prints `error: Error Configuration value not found: ANTHROPIC_API_KEY.` (the provider's key name, such as `OPENROUTER_API_KEY` or `DATABRICKS_TOKEN`), tells you to run `goose configure` again, and exits 1 ([`anthropic_def.rs`](https://github.com/aaif-goose/goose/blob/v1.60.2/crates/goose/src/providers/anthropic_def.rs) `from_env`, [`config/base.rs`](https://github.com/aaif-goose/goose/blob/v1.60.2/crates/goose/src/config/base.rs) `get_secret`, [`builder.rs`](https://github.com/aaif-goose/goose/blob/v1.60.2/crates/goose-cli/src/session/builder.rs) `build_session`). The row's `signed_out` patterns match these, so `start` fails with `the harness is not signed in` and its `next` names `goose configure`. Other setup failures, such as a missing non-key setting (`DATABRICKS_HOST`) or a keyring that can't be read, stay the driver's generic failure, which points at the run's log.
- **The fake:** `fake` takes only the two command lines above, with `GOOSE_MODE=auto`, and exits 2 on anything else. `test_row.py` checks that it refuses lines goose's docs don't allow, that a turn's command line is exactly the documented one, that the row's `GOOSE_MODE` wins over the user's, and that a start leaves a backgrounded shell command of goose's real shape (its own process group, its leader gone, stdin closed, output on pipes) that stop ends on Linux. The fake makes that process with `sh -c 'sleep 300 & echo $!'` in a new process group, as goose's shell does.

Live check: #2499

## The census check, resolved

**Does the session name accept a UUID, and does a named `run` exit when its task ends? Yes to both.** Sources, all read only, at tag [`v1.60.2`](https://github.com/aaif-goose/goose/tree/v1.60.2) of aaif-goose/goose:

1. [`crates/goose-cli/src/cli.rs`](https://github.com/aaif-goose/goose/blob/v1.60.2/crates/goose-cli/src/cli.rs) (`Identifier`): `-n, --name <NAME>` is a plain `Option<String>` with no value check, so a UUID is accepted as given. Its long help: "When used with --resume, will resume this specific session if it exists." `--session-id` needs `--resume`, so the row names the session instead.
2. Same file, `get_or_create_session_id`: without `--resume`, `-n` creates a new session and saves the name as user-provided (`user_provided_name`); with `--resume`, it finds the session whose name (or id) equals the name, and fails with `No session found with name ...` when there is none, so a wake never lands in another session.
3. [`crates/goose/src/session/session_manager.rs`](https://github.com/aaif-goose/goose/blob/v1.60.2/crates/goose/src/session/session_manager.rs) (`maybe_update_name`): goose's automatic session naming skips a session whose name the user set, so the UUID name stays.
4. `cli.rs` (`handle_run_command`): without `-s/--interactive`, `run` calls `session.headless(...)` once and returns; [`crates/goose-cli/src/session/mod.rs`](https://github.com/aaif-goose/goose/blob/v1.60.2/crates/goose-cli/src/session/mod.rs) (`headless`) processes the one message and ends. So a named `run` exits when its task ends.
5. [CLI commands](https://github.com/aaif-goose/goose/blob/v1.60.2/documentation/docs/guides/goose-cli-commands.md) (`run`): documents `-n, --name`, `-r, --resume`, `-t, --text`, `--model` and `--output-format` (`text`, `json` or `stream-json`).
6. `session/mod.rs` (`process_agent_response`): in a non-interactive run, a tool approval under `approve` or `smart_approve` ends the run with "Approve/SmartApprove modes require an interactive terminal. Use GooseMode::Auto for headless sessions." [`environment-variables.md`](https://github.com/aaif-goose/goose/blob/v1.60.2/documentation/docs/guides/environment-variables.md) documents `GOOSE_MODE` (`auto`, `approve`, `smart_approve`), and [`crates/goose/src/config/base.rs`](https://github.com/aaif-goose/goose/blob/v1.60.2/crates/goose/src/config/base.rs) (`get_param`) reads the environment before `config.yaml`.
7. [`crates/goose-cli/src/session/builder.rs`](https://github.com/aaif-goose/goose/blob/v1.60.2/crates/goose-cli/src/session/builder.rs): with no provider or model set, it prints `No provider configured. Run 'goose configure' first.` (or `No model configured...`) and exits 1. [`config-files.md`](https://github.com/aaif-goose/goose/blob/v1.60.2/documentation/docs/guides/config-files.md) puts the provider and model in `~/.config/goose/config.yaml` and keys in the system keyring, or `secrets.yaml` when the keyring is off.

No live test was run and nothing was signed in to: the live run is #2499. No test here runs the real `goose`: the tests use `fake`, with no-op stubs for every known agent CLI on `PATH`.

## Effort

**None.** goose's generic effort setting is `GOOSE_THINKING_EFFORT` (`off`, `low`, `medium`, `high` or `max`; [`providers.md`](https://github.com/aaif-goose/goose/blob/v1.60.2/documentation/docs/getting-started/providers.md), and `get_goose_thinking_effort` in [`config/base.rs`](https://github.com/aaif-goose/goose/blob/v1.60.2/crates/goose/src/config/base.rs)). When it is unset or doesn't parse, the same method falls back to legacy Claude settings (`CLAUDE_THINKING_TYPE`, `CLAUDE_THINKING_ENABLED`) and a Gemini one (`GEMINI3_THINKING_LEVEL`), and some model families take an effort suffix on the model name (below). None of these is always applied, and nothing says so:

- [`crates/goose-providers/src/ollama.rs`](https://github.com/aaif-goose/goose/blob/v1.60.2/crates/goose-providers/src/ollama.rs) (`reasoning_effort`) sends no effort for a model without thinking, and sends `max` as `high`. Its own test, `reasoning_effort_omits_level_for_models_without_thinking`, expects the effort to be dropped.
- `get_goose_thinking_effort` drops a `GOOSE_THINKING_EFFORT` value that doesn't parse (`.parse().ok()`) and falls back as above, without an error.
- For OpenAI Responses and xAI reasoning models, a model name ending in an effort word (such as `-high`) sets its own effort (`normalize_effort_suffix` in [`crates/goose-provider-types/src/model.rs`](https://github.com/aaif-goose/goose/blob/v1.60.2/crates/goose-provider-types/src/model.rs)), which the row can't see from the model id alone.

The harness-row contract says a row must not claim an effort its CLI silently ignores for some models, so the row says `"effort": "none: ..."`, and a start that carries an effort is refused and starts nothing.
