# OpenCode (`opencode`)

Login: opencode's own login, saved by `opencode auth login` in ~/.local/share/opencode/auth.json, or a provider API-key variable you set yourself

Effort: none

Live check: #2464

OpenCode as a harness row on the local driver ([the harness-row contract](../../harness-row.md)). The driver never reads, passes or stores a login. OpenCode finds its own credential: `opencode auth login` saves it in `auth.json` under its data folder (`$XDG_DATA_HOME/opencode`, so `~/.local/share/opencode` by default), or it reads a provider variable such as `ANTHROPIC_API_KEY` that you set yourself ([cli.mdx, auth](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/web/src/content/docs/cli.mdx#auth); [`src/auth/index.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/auth/index.ts)). At 1.19.6 `opencode.db` in the same folder holds sessions, not the login ([`core/src/database/database.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/core/src/database/database.ts)).

## The version

Every fact here is from OpenCode **1.19.6**: tag `v1.19.6` of [anomalyco/opencode](https://github.com/anomalyco/opencode/tree/v1.19.6), commit `f4e363c8`, `packages/opencode/package.json` version `1.19.6`, which builds the `opencode` program. They were read from its docs and its source. `opencode run --help` prints the yargs options of [`src/cli/cmd/run.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/cli/cmd/run.ts), and the row's flags were read from there. No OpenCode was installed or run, and nothing was signed in.

The row holds for OpenCode 1.x only. OpenCode 2.x (`v2.0.0` onwards, built from `packages/cli`) is a different `run`: it uses the shared background service when one is already up ([`packages/cli/src/commands/handlers/run.ts` at v2.4.0](https://github.com/anomalyco/opencode/blob/v2.4.0/packages/cli/src/commands/handlers/run.ts)), and it has no `--variant`. The dev-branch [commands.mdx](https://github.com/anomalyco/opencode/blob/dev/services/site/src/docs/content/cli/commands.mdx) and [server](https://opencode.ai/docs/server/) docs describe 2.x. The live check must run 1.19.6 (`npm i -g opencode-ai@1.19.6`; `opencode --version` prints `1.19.6`).

## Commands

- **Start:** `opencode run --format json --model <provider/model> [--auto] -- "<prompt>"`, in the run's worktree.
- **Wake (same run):** `opencode run --session <sessionID> --format json --model <provider/model> [--auto] -- "<message>"`, in the same worktree.
- **Stop:** the driver ends the run's process tree.
- **Session:** `{"json": ["sessionID"]}`. With `--format json`, every event `run` prints is one JSON line `{"type": ..., "timestamp": ..., "sessionID": "ses_...", ...}` (`emit` in [`run.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/cli/cmd/run.ts)). The first is `step_start`, or `error` when the prompt fails; both carry the run's own session id. Ids are `ses_` and 26 letters and digits ([`src/id/id.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/id/id.ts)).

`--model` takes `provider/model` (`pick` in `run.ts`), so the run's model must be written that way. Wake passes the same model again, so the session stays on it. `--` ends option parsing (the CLI sets yargs' `populate--`, [`src/index.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/index.ts), and `run` reads `args["--"]`), so a prompt is never read as an option. `run` joins its message words with spaces and wraps a word that holds a space in double quotes, so the model sees the driver's one-argument prompt in quotes; the words are unchanged. `--session` with an unknown id prints `Session not found` and exits 1.

## The census check: resolved, nothing blocks

**Does `run` start the shared background service and leave it running? No. At 1.19.6 it neither starts nor joins one.**

- Without `--attach`, `run` builds its SDK client on an in-process `fetch` that calls `Server.Default().app.fetch` directly, with the base URL `http://opencode.internal`. It opens no port and starts no server process. The command's own note says so: "the default path runs an in-process server and needs the project instance" ([`run.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/cli/cmd/run.ts), `RunCommand` and the end of its handler). `--port` is declared but `run` never reads it.
- `run` talks to a server someone else started only with `--attach <url>`, which the docs offer to skip MCP cold boots ([cli.mdx, run](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/web/src/content/docs/cli.mdx#run)). The row never passes `--attach`, and its fake refuses it. So a server the user started themselves is never used, and no flag or variable is needed to keep the run in-process: that is the default.
- The update check, which may install in the background, runs only in the TUI's worker ([`src/cli/tui/worker.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/cli/tui/worker.ts)), never in `run`. The `opencode` launcher runs the platform binary as its child with `spawn` ([`bin/opencode`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/bin/opencode)), so both are in the turn's tree.

**What `run` does start, and how stop ends it.** OpenCode's shell tool starts each command `detached` on Linux and macOS ([`src/tool/shell.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/tool/shell.ts) `cmd`), and its process spawner makes every child detached unless told otherwise ([`core/src/cross-spawn-spawner.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/core/src/cross-spawn-spawner.ts)), which LSP servers and local MCP servers use too. A detached Node child is in its own session. OpenCode kills those groups when it closes its scopes, but a command the model backgrounds, or a child of a run that is killed, can outlive the turn. So the row's `daemon` names them. Its fake starts a stand-in the way the real ones start: double-forked into its own session, with its output closed (the library's Linux service). The runner needs it to have ended after stop. The driver's stop ends every process under the run, including ones that left its process group; as the contract's section 7 says, that holds on Linux, and the live check names the platform it ran on.

## Effort: none

OpenCode 1.19.6 has a flag, `run --variant <name>`: "model variant (provider-specific reasoning effort, e.g., high, max, minimal)" ([`run.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/cli/cmd/run.ts); [cli.mdx, run](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/web/src/content/docs/cli.mdx#run)). The row still declares `none`, because OpenCode drops a variant silently:

- The request takes `model.variants[variant]` and merges it into the call's options; a variant the model doesn't list gives `undefined`, which merges as nothing (`mergeOptions` and `prepare` in [`src/session/llm/request.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/session/llm/request.ts)). Neither `run` nor the prompt checks the name first ([`src/session/prompt.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/session/prompt.ts)). So `--variant high` on a model without a `high` variant, such as one without reasoning, runs at the default with no warning and exits 0.
- The variant names are per provider and model ([`src/provider/transform.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/provider/transform.ts) `variants`), so no fixed effort map holds for every model.
- The contract says a row must not claim an effort value its CLI silently ignores for some models. So a start that carries an effort gets the driver's D3 refusal and starts nothing, with exactly this `next`: `this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default`. If a later 1.x refuses an unknown variant, the row can switch to an effort map through `--variant {effort}`.

## Permission modes

`run` denies the `question`, `plan_enter` and `plan_exit` permissions for the session it creates, and answers every other permission request with a reject, unless `--auto` is set, which answers `once` ([`run.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/cli/cmd/run.ts), the `permission.asked` branch). The default agent allows every tool and asks only for a doom loop, a path outside the worktree and `.env` files ([`src/agent/agent.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/agent/agent.ts)); your own `permission` config changes that.

- `auto` adds `--auto`: "auto-approve permissions that are not explicitly denied". Approving it means OpenCode may run any tool your config doesn't deny.
- `configured` adds nothing: your config's `allow` rules run, and anything that would ask is rejected.

## Not signed in

The row has no `signed_out`. OpenCode 1.19.6 has no message that means only "not signed in": a provider with no credential is left out of the provider list, so its model fails as `Model not found: <provider>/<model>`, the same error as a mistyped model (a provider joins the list only with a key from its variable or `auth.json`, and `getModel` fails with `ProviderModelNotFoundError` for one that isn't there: [`src/provider/provider.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/provider/provider.ts); the message is in [`src/cli/error.ts`](https://github.com/anomalyco/opencode/blob/v1.19.6/packages/opencode/src/cli/error.ts)). A pattern for it would send a user with a typo to sign in. A signed-out first turn fails as the driver's generic first-turn failure, and you sign in with `opencode auth login` yourself; the driver never runs it.

Synthetic: in this folder, `fake` is the only CLI. It accepts only the two command lines above, its synthetic `--help` is its `HELP` text, and it exits 2 on anything else. `test_row.py` checks those refusals.
