# Pi (`pi`)

Login: pi's own login, saved by `pi auth login <provider>` in ~/.pi/agent/auth.json, or a provider API-key variable you set yourself

Effort: none

Live check: #2458

Pi as a harness row on the local driver ([the harness-row contract](../../harness-row.md)). The driver never reads, passes or stores a login, and never passes `--api-key`: Pi finds its own credential in `~/.pi/agent/auth.json` (or under `PI_CODING_AGENT_DIR`), or in a provider variable such as `ANTHROPIC_API_KEY` that you set yourself ([providers.md](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/docs/providers.md)).

All facts below are from Pi 1.6.0: tag `v1.6.0` of [earendil-works/pi](https://github.com/earendil-works/pi/tree/v1.6.0), commit `faac5858`, `packages/coding-agent/package.json` version `1.6.0`. They were read from its docs, its `--help` text and its source. No Pi was installed or run, and nothing was signed in.

## Commands

- **Start:** `pi -p --mode json --session-id <uuid> --model <model> -- "<prompt>"`, in the run's worktree.
- **Wake (same run):** `pi --session-id <uuid> -p -- "<message>"`, in the same worktree. It passes no `--model`.
- **Stop:** the driver ends the run's process tree.
- **Session:** `{"chosen": "uuid"}`. The driver makes the id and passes it at start and at every wake.

`-p` runs the prompt and exits. `--mode json` writes JSONL events to stdout, so the first turn's log keeps every event. `--` ends option parsing, so a prompt can never be read as an option ([cli.md](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/docs/cli.md#invocation-and-output); `pi -p -- "- Summarize these points"` in the `--help` examples of [`src/cli/args.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/cli/args.ts)). The driver's prompts never start with `@`, which Pi reads as a file even after `--`. Wake passes no `--model`: the session restores the provider and model it recorded ([`src/core/sdk.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/core/sdk.ts) `createAgentSession`). Passing the model again would resolve its name afresh, and a bare name two signed-in providers share is then ambiguous, so the wake would fail while the recorded model still works ([`src/core/model-resolver.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/core/model-resolver.ts) `resolveCliModel`).

## The census check: resolved, nothing blocks

**1. The driver can pick the session id itself. Yes.**

- [cli.md, Sessions](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/docs/cli.md#session-options): `--session-id <id>` "Opens the current directory's existing session with the ID, or creates it otherwise. IDs accept letters, numbers, `.`, `_`, and `-`", and "Session IDs must start and end with a letter or number". A UUID fits.
- [`src/core/session-manager.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/core/session-manager.ts) `assertValidSessionId` checks `^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$`. [`src/main.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/main.ts) opens the session with that exact id stored for the current directory, and otherwise creates one with that id (with a warning on stderr). So the start creates the session, and a wake in the same worktree opens it again.
- `--session-id` can't be combined with `--session`, `--continue` or `--resume`, and the row passes none of them.

**2. No daemon. Pi starts no service. Its bash tool can leave a background command, which stop ends.**

- `pi -p` runs in one process ([`src/modes/print-mode.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/modes/print-mode.ts)). It starts no server or hub: RPC mode is a stdin/stdout protocol in the same process, and the row never selects it.
- The bash tool spawns each command `detached`, in its own process group ([`src/core/tools/bash.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/core/tools/bash.ts)). Pi kills a tracked command only while it runs (`killTrackedDetachedChildren` in [`src/utils/shell.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/utils/shell.ts)), so a command the model backgrounds (`cmd &`) can outlive the turn. MCP servers from `mcp.json` run in their own process group, which Pi ends when it closes ([`packages/mcp/src/transports/stdio.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/mcp/src/transports/stdio.ts)).
- So the row's `daemon` names that background command. Its fake starts a stand-in for it, and the harness check requires it to have ended after stop. The driver's stop ends every process under the run, including ones that left their process group. As the contract's section 7 says, that holds on Linux and the live check names the platform it ran on.

## Effort: none

Pi has a flag, `--thinking <level>` (`off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`), and a `--model <pattern>:<level>` shorthand ([cli.md, Models](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/docs/cli.md#model-options)). The row still declares `none`, because Pi drops an effort silently:

- cli.md says the level "is clamped to the model's capabilities". [`packages/ai/src/models.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/ai/src/models.ts) `clampThinkingLevel` swaps a level the model can't take for the nearest one it can. A model without reasoning takes only `off` (`getSupportedThinkingLevels`), so `--thinking high` runs with no thinking at all. Pi prints no warning and exits 0 ([`src/core/agent-session.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/core/agent-session.ts) `setThinkingLevel`).
- An unknown level is only a warning, and the run goes on at the default ([`src/cli/args.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/cli/args.ts)).
- The contract says a row must not claim an effort value its CLI silently ignores for some models. So once the local driver's `effort` start field is on, a start that carries an effort gets the driver's D3 refusal and starts nothing, with exactly this `next`: `this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default` (today the local driver's request check refuses any start carrying `effort` and starts nothing either). If a later Pi refuses a level the model can't take, the row can switch to an effort map through `--thinking {effort}`.

## Permission mode

Pi has no permission mode. It "does not ask for approval before every tool call" and has no built-in sandbox ([security.md](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/docs/security.md)). `--tools` limits the declared tools, but MCP and codemode tools stay reachable, so the row offers no "read-only" mode it can't keep.

The row's one mode is `full-access`, which adds no arguments. Approving it means "Pi may run any tool in the run's worktree". The row passes neither `--approve` nor `--no-approve`. In `-p` mode Pi can't show its project-trust prompt, so your own saved decision or `defaultProjectTrust` setting applies, and the default skips project `.pi` resources.

## Not signed in

Pi checks for a credential before the first model call. It exits 1 and writes one of these lines to stderr, as its own line ([`src/modes/print-mode.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/modes/print-mode.ts) prints a thrown error's message, [`src/modes/diagnostics-stderr.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/modes/diagnostics-stderr.ts) prints a startup error after `Error: `, in red only when colour is on; the messages are in [`src/core/agent-session.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/core/agent-session.ts), [`src/core/auth-guidance.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/core/auth-guidance.ts) and [`src/core/model-resolver.ts`](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/src/core/model-resolver.ts)):

- `No API key found for <provider>.`, when nothing is configured for the model's provider (`the selected model` when the provider is unknown), followed by a blank line and Pi's `/login` help;
- `Authentication failed for "<provider>". Credentials may have expired or network is unavailable. Run '/login <provider>' to re-authenticate.`, for an OAuth login it can't refresh;
- `Error: Model "<model>" is ambiguous across providers: <provider/model, ...>. No matching provider is authenticated. Use --provider or provider/model.`, for a model name several providers offer when none is signed in.

The row's `signed_out` matches those three whole lines, from the start of the line to its end. Every event Pi writes to stdout in `--mode json` is one JSON object on its own line, so the same words quoted in an assistant message or a tool's output sit inside a line that starts with `{` and never match. A signed-out start fails with the D3 error `the harness is not signed in`, and its `next` names `pi auth login <provider>` ([cli.md, Credential commands](https://github.com/earendil-works/pi/blob/v1.6.0/packages/coding-agent/docs/cli.md#credential-commands)). That command needs an interactive terminal, and the driver never runs it.

Synthetic: in this folder, `fake` is the only CLI. It accepts only the two command lines above, with a model that is not empty or blank (Pi's `--model` takes a pattern, and an empty one would skip choosing a model), its synthetic `--help` is its `HELP` text, and it exits 2 on anything else.
