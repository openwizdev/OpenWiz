# Vibe (local runs)

Login: Vibe's own login: vibe --setup saves the key in the OS keyring, or in ~/.vibe/.env when no keyring is available, or you set MISTRAL_API_KEY yourself; the driver never reads or passes it

A harness row for the [local driver](../../README.md), in the shape of the [harness-row contract](../../harness-row.md). It runs the [Vibe CLI](https://docs.mistral.ai/vibe/code/cli/work-with-cli) in programmatic mode on this machine only. Every command line below was read from the Vibe docs and from `mistralai/mistral-vibe` `main` on 2026-11-26: nothing was installed, run or signed in to.

Effort: --thinking <level>, at start only

- **Start:** `vibe --prompt <prompt> --output streaming --model <model> --trust --auto-approve [--thinking <level>]`. `--prompt` is programmatic mode. `--trust` is required because a new clone is an untrusted directory and programmatic mode refuses it without `--trust` for that invocation. `--output streaming` prints one compact JSON object per completed history entry, and that entry carries `sessionId`.
- **Wake (same run):** `vibe --prompt <prompt> --output streaming --resume <session id> --trust --auto-approve`. `--model` and `--thinking` apply only to a new session (`--thinking only applies to a new session`, `--model only applies to a new session`), so a wake does not pass them.
- **Session:** reported. The server assigns the id. Streaming history entries expose it as `sessionId`. The row reads `sessionId` from the first JSON line that has it. `--output json` pretty-prints the whole transcript as one array, which the driver cannot read a session id from, so this row uses streaming.
- **Mode:** `auto-approve` passes `--auto-approve` (the `--yolo` alias is the same flag). Programmatic mode denies tool calls that need approval unless this flag is set. The narrower agents (`ask`, `accept-edits`, `smart-approve`) still ask, and a headless run cannot answer, so this row offers only `auto-approve`.
- **Env:** none. The driver does not set `MISTRAL_API_KEY`.
- **Signed out:** programmatic mode prints `Error: Missing MISTRAL_API_KEY environment variable for mistral provider` or `Error: You are not signed in to Mistral. Sign in and retry.` on stderr and exits 1. `row.json` anchors both patterns to that `Error: ` diagnostic line so streaming JSON messages quoting either phrase still pass. The user runs `vibe --setup`, or sets `MISTRAL_API_KEY`. The fake exits 2 if a key is placed on the command line. There is no `--api-key` flag.

## The census check

Read as text on 2026-11-26. No `vibe` binary was installed or run.

1. [Work with the CLI](https://docs.mistral.ai/vibe/code/cli/work-with-cli): `vibe --prompt`, `--max-turns`, `--output json`, and `--auto-approve` so programmatic mode can approve tool calls. Exit 1 means the run could not start.
2. [Agents](https://docs.mistral.ai/vibe/code/cli/agents): `--agent` values `ask`, `accept-edits`, `smart-approve`, `auto-approve`. The default `accept-edits` still asks before non-edit actions.
3. [API keys and profiles](https://docs.mistral.ai/vibe/code/cli/api-keys-profiles): the key is `MISTRAL_API_KEY` in the shell, in `~/.vibe/.env`, or in the OS keyring after `vibe --setup`.
4. [cli.rs](https://github.com/mistralai/mistral-vibe/blob/main/vibe/cli-rust/src/cli.rs): `--thinking` levels `off`, `low`, `medium`, `high`, `xhigh`, `max`, or a word the model lists, sent as written; new sessions only. `--resume` needs a session id in programmatic mode. `--trust` is per invocation. `--output` is `text`, `json` or `streaming`. `--auto-approve` is aliased to `--yolo`.
5. [config_values.py](https://github.com/mistralai/mistral-vibe/blob/main/vibe/config_values.py): `THINKING_LEVELS` is those six words. `xhigh` is accepted by the flag and offered by a model that lists it; the CLI still sends the word as written.
6. [headless_output.rs](https://github.com/mistralai/mistral-vibe/blob/main/vibe/cli-rust/src/headless_output.rs): streaming emits one JSON object per history entry. `json` pretty-prints an array.
7. [events.py](https://github.com/mistralai/mistral-vibe/blob/main/client-e2e/e2e/app_server/events.py) and [_history_projection.py](https://github.com/mistralai/mistral-vibe/blob/main/vibe/app_server/_history_projection.py): a streaming entry includes `sessionId`.
8. [models.py](https://github.com/mistralai/mistral-vibe/blob/main/vibe/core/config/models.py): `MissingAPIKeyError` says `Missing <env> environment variable for <provider> provider`. [_provider_credentials.py](https://github.com/mistralai/mistral-vibe/blob/main/vibe/app_server/_provider_credentials.py) says `You are not signed in to Mistral. Sign in and retry.` [headless.rs](https://github.com/mistralai/mistral-vibe/blob/fb7511a791f80516a57b06525707215b6a00ebd1/vibe/cli-rust/src/headless.rs#L73-L84) prints each headless error on stderr as `Error: <message>`.

No test starts the real `vibe` program. The row runner puts a no-op stub on `PATH` and this folder's `fake` ahead of it.
