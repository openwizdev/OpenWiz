# Sculptor, `sculpt`

Login: the harness's own login on this machine (for example the Claude CLI Sculptor runs); sculpt fetches its backend session token itself, and the driver never reads or passes a login

A harness row for the [local driver](../../README.md), in the shape of the [harness-row contract](../../harness-row.md). It runs [Sculptor's `sculpt` CLI](https://github.com/imbue-ai/sculptor/blob/sculptor-v0.50.0/docs/specs/SPEC.md) against the local Sculptor the user already has running. The driver never starts that backend, never sets its port, and never reads or passes a login or a session token.

Effort: none

- **Start:** `sculpt agent create --prompt <prompt> --model <model> --json`. The mode adds no arguments.
- **Wake (same agent):** `sculpt agent send <session> <prompt> --model <model> --follow`. `--model` is passed again; an explicit `--model` wins over the agent's current model.
- **Session:** the agent id, read from the indented `"id"` line of `agent create --json` (see [the census check](#the-census-check-the-agent-runs-outside-the-drivers-process-tree)).
- **Stop:** `sculpt agent delete <session> -y`, then the driver's process-tree kill. Delete is what ends the agent. The tree kill does not reach the backend the agent runs in.
- **Effort:** none: a start that carries an effort is refused and starts nothing (see [the effort fact](#the-effort-fact)).
- **Permission mode:** `default` passes nothing. `sculpt agent create` has no permission-mode flag; the agent runs as whichever harness the Sculptor app last used (Claude, Pi, Terminal, or a registered terminal agent). Approve `default` for `sculpt`.
- **Login:** the driver never reads, sets, or passes a login. `sculpt` fetches its own backend session token. The model provider login, when the harness needs one, is that harness's own (for example the Claude CLI Sculptor runs).

The backend must already be running at `http://localhost:5050`, or at `http://localhost:$SCULPT_API_PORT` when that variable is set. `agent create` also needs a workspace: export `SCULPT_WORKSPACE_ID` yourself, or the command errors. The row does not pass `--workspace`, `--base-url`, a token, or `SCULPT_API_PORT`. The user's environment is inherited; the row's `env` is empty, so it never sets those.

## The version read

Read on 2026-11-26, as text only (no install, no run, no sign-in):

- **Tag:** [`sculptor-v0.50.0`](https://github.com/imbue-ai/sculptor/tree/sculptor-v0.50.0), commit [`c081562e`](https://github.com/imbue-ai/sculptor/commit/c081562eecc3d19a5a5ad8cd2bf4cf2a69747132).
- **CLI:** [`tools/sculpt/sculpt/commands/agent.py`](https://github.com/imbue-ai/sculptor/blob/sculptor-v0.50.0/tools/sculpt/sculpt/commands/agent.py) (`create`, `send`, `delete`, `interrupt`).
- **Spec:** [`docs/specs/SPEC.md`](https://github.com/imbue-ai/sculptor/blob/sculptor-v0.50.0/docs/specs/SPEC.md), section 8 (the CLI), section 7.3 (the chat effort selector), section 7.10 (the Agent settings defaults).

What they give for the row's arguments:

1. `agent create` takes `--prompt`/`-p`, `--model`/`-m`, and `--json`. With `--json` it prints `AgentCreateOutput` via `model_dump_json(indent=2)` and returns. `agent create` has no `--follow`, so that process exits while the agent keeps running in the backend. With no `--prompt`, `--model` is an error (`--model has no effect without --prompt`). An empty or blank `--model` is not a model name: `resolve_prompt_models` in [`_harness_helpers.py`](https://github.com/imbue-ai/sculptor/blob/sculptor-v0.50.0/tools/sculpt/sculpt/commands/_harness_helpers.py) accepts a Claude family or model id (`haiku`, `sonnet`, `opus`, `fable`, or `claude-opus-5-5`), or a Pi catalog model when the harness is Pi. There is no effort flag in this file.
2. `agent send` takes the agent id and the message as positionals, plus `--model`/`-m` and `--follow`/`-f`. The docstring on `_resolve_send_model` says an explicit `--model` wins; otherwise the agent's current model is reused.
3. `agent delete` takes the agent id and `--yes`/`-y`. Without `-y`, `--json` fails with "Confirmation required: pass --yes/-y to delete"; without `--json` it prompts. The row's stop always passes `-y`, so it does not prompt.
4. `agent interrupt` takes the agent id. Its docstring is "Interrupt a running agent." It does not delete.

## The census check: the agent runs outside the driver's process tree

**Yes. The agent runs in Sculptor's own backend, on localhost, not in `sculpt`'s process tree. `sculpt agent delete <id> -y` is what ends it. Interrupt does not.**

The CLI talks to the same local server as the desktop app ([SPEC.md section 8](https://github.com/imbue-ai/sculptor/blob/sculptor-v0.50.0/docs/specs/SPEC.md)). [`tools/sculpt/sculpt/auth.py`](https://github.com/imbue-ai/sculptor/blob/sculptor-v0.50.0/tools/sculpt/sculpt/auth.py) sets `DEFAULT_PORT = 5050` and `get_default_base_url()` returns `http://localhost:{SCULPT_API_PORT or 5050}`. `get_authenticated_client` calls `get_session_token` and sends that token itself; the caller passes no token. [`tools/sculpt/sculpt/session.py`](https://github.com/imbue-ai/sculptor/blob/sculptor-v0.50.0/tools/sculpt/sculpt/session.py) reads `x-session-token` out of the backend's `Set-Cookie`.

Delete and interrupt are different requests:

- [`DELETE /api/v1/workspaces/{workspace_id}/agents/{agent_id}`](https://github.com/imbue-ai/sculptor/blob/sculptor-v0.50.0/sculptor/sculptor/web/app.py) calls `task_service.delete_task`. In [`base_implementation.py`](https://github.com/imbue-ai/sculptor/blob/sculptor-v0.50.0/sculptor/sculptor/services/task_service/base_implementation.py), a RUNNING task is marked `is_deleting` and its `shutdown_event` is set; an idle task is finalized deleted immediately. The runner in [`run_agent/v1.py`](https://github.com/imbue-ai/sculptor/blob/sculptor-v0.50.0/sculptor/sculptor/tasks/handlers/run_agent/v1.py) sees the shutdown event, pushes `StopAgentUserMessage`, then after 10 seconds terminates the agent and after another 10 seconds raises `AgentHardKilled`. [`process_manager.py`](https://github.com/imbue-ai/sculptor/blob/sculptor-v0.50.0/sculptor/sculptor/agents/default/claude_code_sdk/process_manager.py) escalates that shutdown to SIGTERM, then SIGKILL, on the process group.
- [`POST .../interrupt`](https://github.com/imbue-ai/sculptor/blob/sculptor-v0.50.0/sculptor/sculptor/web/app.py) only posts `InterruptProcessUserMessage`. It does not delete the task.

The agent id is a `TaskID`. [`primitives/ids.py`](https://github.com/imbue-ai/sculptor/blob/sculptor-v0.50.0/sculptor/sculptor/primitives/ids.py) sets `class TaskID` with `tag = "tsk"`, so the id is `tsk_` plus the TypeID suffix. That form fits the driver's session grammar.

**Why a pattern, not a JSON key path.** `agent create --json` prints indented JSON (`indent=2`). The contract's `{"json": ["id"]}` reads only a line that `json.loads` as an object, and an indented dump puts `{` on its own line and `"id"` on the next, so the path never sees `id`. The row's pattern is `"id": "([A-Za-z0-9._:-]{1,100})"`, which matches the id line and not `"workspace_id"`.

Stop is one argument list, `sculpt agent delete {session} -y`. The driver's process-tree kill still runs after it, and a failing delete does not skip that kill. The tree kill cannot reach the backend: the backend was already running before the turn, outside the turn's process tree. The row's `daemon` is `none`, because `sculpt` itself leaves no child for the runner's background-process check. `test_row.py` is what proves the stand-in backend ended, and that only `agent delete -y` ends it.

The fake stands in for that backend. On `agent create` it starts a session outside the turn's process tree (through the runner's hub when the runner sets one, otherwise a detached process) and records that process's start time. `agent interrupt` and `agent send` leave it running, and refuse when it is not that same live process. `agent delete <id> -y` ends it, and only it: a recorded pid whose start time no longer matches is left alone. A second delete, an interrupt, or a send after that exits 2. The driver never starts the stand-in and never sees a token.

The check holds with the row: start prints the id, wake sends it, and stop's delete is the command that ends the backend session. The live check records a real machine.

## The effort fact

`sculpt` can't set effort on a start, so the row declares effort none, as `row.json` says: `"effort": "none: sculpt agent create and send have no effort flag at sculptor-v0.50.0 (imbue-ai/sculptor tools/sculpt/sculpt/commands/agent.py); effort is the app chat selector (SPEC.md 7.3), not a CLI flag"`.

1. `agent create` and `agent send` in `tools/sculpt/sculpt/commands/agent.py` at `sculptor-v0.50.0` have no effort, reasoning, or thinking flag. SPEC.md section 8's CLI table does not list one.
2. SPEC.md section 7.3 describes the chat UI's effort selector (Low, Medium, High, Extra High, Max). Section 7.10 says Settings → Agent sets the default model, fast mode, and effort level for new agents. Those are app settings, not a flag this row can pass, and the levels are not a CLI vocabulary.

Leave the effort empty for `sculpt`. A start that carries an effort is a D3 error that starts nothing, with this `next`: "this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default".

## Not installed

`sculpt` not on `PATH`: the driver's D3 error `harness sculpt is not installed here`, whose `next` says to install sculpt and sign in to it yourself. There is no `signed_out` line on this row: a missing backend or a failed token fetch is a connection or session error from `sculpt`, not one stable "not signed in" line.

## Tests

```sh
python3 -I adapters/local/test_harnesses.py    # finds this row; the contract, the kit's five checks with ./fake, the session, env, background-process and effort checks, then test_row.py
```

`fake` is a synthetic `sculpt`. It allows only the row's command lines: `agent create` with `--prompt`/`-p`, `--model`/`-m`, and `--json`; `agent send` with the agent id, the message, `--model`/`-m`, and `--follow`/`-f`; `agent delete` with the agent id and `-y`/`--yes`; and `agent interrupt` with the agent id. Each flag at most once, and each value not an option. A prompt or model that is empty or blank is refused. Anything else exits 2, including `--effort`, `--reasoning`, `sculpt run`, and `agent delete` without `-y`. `test_row.py` checks not installed, that create starts a backend outside the process that exits, that interrupt and delete-without-`-y` leave it and delete `-y` ends it, that interrupt, send, and a second delete then exit 2, the exact start and wake command lines, the id read from the indented `"id"` line, that stop runs `agent delete <id> -y` while the turn still runs and that this ends a backend the turn's process tree does not hold, the fake's refusals, that delete ends only the named session, that a delete whose recorded start time does not match kills nothing, that the session pattern's first match is the agent id and not `workspace_id`, and each effort level refused with the fixed `next`.

The row is not tied to one operating system: stop is a CLI command, not a claim that the process tree can reach the backend. The platforms it holds on are the ones its live check runs on.

Live check: #2563
