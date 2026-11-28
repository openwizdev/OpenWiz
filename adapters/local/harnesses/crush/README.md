# Crush (`crush`) harness row

Login: Crush's own login: `crush login` saves it in ~/.local/share/crush/crush.json (or $XDG_DATA_HOME/crush/crush.json)

Effort: none

You sign in yourself with `crush login` (Hyper by default; `crush login copilot`, `openai` or `grok` for the others), or set a provider key in your own environment or `~/.config/crush/crush.json`. The row never reads, sets or stores a key. `CRUSH_GLOBAL_DATA` moves the login file when set.

## The row

- **Start:** `crush run --quiet --verbose --model <model> --yolo -- <prompt>` in the run's workspace.
- **Wake (same run):** `crush run --quiet --verbose --session <id> --model <model> --yolo -- <prompt>`.
- **Model:** passed to `--model` unchanged, provider-qualified ids included. Name the provider in full, such as `openrouter/anthropic/claude-sonnet-4.6` for OpenRouter's default (`default_large_model_id` `anthropic/claude-sonnet-4.6` in [`internal/providers/configs/openrouter.json`](https://github.com/charmbracelet/catwalk/blob/v3.2.9/internal/providers/configs/openrouter.json#L7), the catalog Crush `v0.102.0` pins). Crush reads a first segment that names a configured provider as a filter ([`internal/app/provider.go`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/app/provider.go#L15-L26), `parseModelStr`). So with Anthropic configured too, `anthropic/claude-sonnet-4.6` looks for `claude-sonnet-4.6` in Anthropic's catalog, where the id is `claude-sonnet-4-6` ([`anthropic.json`](https://github.com/charmbracelet/catwalk/blob/v3.2.9/internal/providers/configs/anthropic.json)), and the run fails with `large model "claude-sonnet-4.6" not found`. Driver v1 takes `/`-separated ids since MG1 (#2904).
- **Session id:** reported, in the `pattern` form. With `--verbose`, Crush logs the new run's own id to stderr before the first turn: `INFO  Created session for non-interactive run session_id=<uuid>`. The driver reads it from the run's log, which holds the turn's stderr. A wake logs `Continuing session ...`, which the pattern doesn't match. The row never uses `crush session last` (below).
- **Stop:** the driver's own stop ends the run's process tree. `daemon` is `none`: `crush run` starts no server.
- **Env:** `CRUSH_CLIENT_SERVER=0`, so a turn never attaches to a Crush server it didn't start, even when your own environment turns that mode on.
- **Permission mode:** one mode, `yolo`, which passes `--yolo` (`-y`). `crush run` auto-approves every tool request of its own session (`internal/app/app.go`, `AutoApproveSession`). Without `--yolo` that includes commands Crush's block list calls dangerous. With one `--yolo` they are refused (`internal/agent/tools/bash.go`, `RefusesDangerous`). `-yy` turns the block list off, so the row doesn't offer it. No `crush run` flag asks before acting, so `yolo` is the safest form a headless run has.
- **Not installed:** the driver refuses with `install crush on this machine and sign in to it yourself, then start again`. **Not signed in:** `crush run` exits 1 with `No providers configured - please run 'crush' to set up a provider interactively.` on stderr. The row's `signed_out` pattern matches that line, so the driver's first-turn watch ends the run with `the harness is not signed in`, and its `next` says to sign in with the row's `login_command`, `crush login`.
- **The fake:** `fake` takes only the two command lines above, logs the session line to stderr, attaches to an outside server when `CRUSH_CLIENT_SERVER` is true (Go's `strconv.ParseBool`), and prints that signed-out line on stderr and exits 1 when the runner sets `FAKE_CLI_SIGNED_OUT`. With `FAKE_CRUSH_PROVIDERS` (the configured providers, such as `openrouter,anthropic`), it matches `--model` as `parseModelStr` does against each provider's Sonnet 4.6 catalog entry, and exits 1 with Crush's `large model "<id>" not found` when nothing or more than one model matches. `test_row.py` checks not installed, not signed in, the env override, that stop leaves nothing, and that `openrouter/anthropic/claude-sonnet-4.6` reaches `--model` unchanged and runs on start and wake with both OpenRouter and Anthropic configured.

## Sources

All read only, at tag [`v0.102.0`](https://github.com/charmbracelet/crush/tree/v0.102.0) of charmbracelet/crush, plus its release binary's `--help`:

- [`internal/cmd/run.go`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/cmd/run.go)
- [`internal/cmd/root.go`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/cmd/root.go)
- [`internal/cmd/session.go`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/cmd/session.go)
- [`internal/db/sql/sessions.sql`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/db/sql/sessions.sql)
- [`internal/config/load.go`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/config/load.go)
- [`internal/app/app.go`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/app/app.go)
- [`internal/agent/coordinator.go`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/agent/coordinator.go)
- [`internal/agent/tools/bash.go`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/agent/tools/bash.go)
- [`internal/permission/permission.go`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/permission/permission.go)
- [`internal/shell/exec_unix.go`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/shell/exec_unix.go)
- [`internal/agent/tools/mcp/process_unix.go`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/agent/tools/mcp/process_unix.go)
- [`internal/cmd/login.go`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/cmd/login.go)
- [`internal/app/provider.go`](https://github.com/charmbracelet/crush/blob/v0.102.0/internal/app/provider.go)
- [`pkg/catwalk/provider.go`](https://github.com/charmbracelet/catwalk/blob/v3.2.9/pkg/catwalk/provider.go), [`internal/providers/configs/openrouter.json`](https://github.com/charmbracelet/catwalk/blob/v3.2.9/internal/providers/configs/openrouter.json) and [`internal/providers/configs/anthropic.json`](https://github.com/charmbracelet/catwalk/blob/v3.2.9/internal/providers/configs/anthropic.json) in charmbracelet/catwalk `v3.2.9`, the model catalog Crush `v0.102.0` pins

The observed lines below come from one fact check made by hand, before this row was built, with the checksum-verified release binary, a throwaway home folder, no sign-in and a local fake OpenAI-compatible endpoint (no account, no network, no paid call). No test here runs the real `crush`: the tests use `fake`, with no-op stubs for every known agent CLI on `PATH`.

## The open fact: is `crush session last --json` safe for parallel runs?

**No, not in general. The row doesn't use it.**

Sources (charmbracelet/crush at tag `v0.102.0`, commit `c62fa02`, read only; and the release's own `crush_0.102.0_Linux_x86_64.tar.gz`, checksum-verified):

1. `crush session last --help`: "Show the last updated session." `internal/cmd/session.go` (`runSessionLast`) opens the data directory's database and returns the first row of `ListSessions`, which `internal/db/sql/sessions.sql` orders by `updated_at DESC`. It names whichever session in that database changed last, not the caller's run.
2. The database lives in the data directory: `internal/config/load.go` uses the closest `.crush` folder up to the git worktree root, so each clone gets its own `<clone>/.crush/crush.db` by default. But `--data-dir`, the `CRUSH_DATA_DIR` environment variable (also in `load.go`) or the `options.data_directory` setting can point several clones at one database.
3. Observed with the release binary and a local fake OpenAI-compatible endpoint (no account, no network): two runs started 0.7 s apart in one data directory; `crush session last --json` read during the first run named the second run's session. Two runs at once in two separate default clones each read back their own id.

So `session last` is only right when nothing else shares the data directory, which the row can't check. Instead the row reads the run's own id:

4. `internal/app/app.go` (`RunNonInteractive`) creates the session and logs `slog.Info("Created session for non-interactive run", "session_id", sess.ID)` before the agent starts; `internal/cmd/run.go` sends logs to stderr when `-v/--verbose` is given. Observed: `INFO  Created session for non-interactive run session_id=<uuid>`. That line is in the run's own output, so parallel runs can't mix it up.
5. `crush run --session <id>` continues that session (`run.go`, `resolveSessionID`); observed: the wake logged `Continuing session for non-interactive run session_id=<same uuid>`.

Stop: `crush run` attaches to a Crush server only when `CRUSH_CLIENT_SERVER` is true and a server is already running, and never starts one itself (`run.go`: "a one-shot run should not leave a detached server behind"); the row sets `CRUSH_CLIENT_SERVER=0`. The shell commands Crush runs get their own session (`internal/shell/exec_unix.go`, `Setsid`) and MCP servers their own process group (`internal/agent/tools/mcp/process_unix.go`, `Setpgid`), but both stay children of the run, so ending the run's process tree ends them.

Not signed in: `crush run` exits 1 with `No providers configured - please run 'crush' to set up a provider interactively.` (observed).

## Effort

**None.** Crush has a flag for it, but it can drop or replace the level without an error, and the row can't check first without reading the user's Crush config, which also holds their provider keys. So the row says `"effort": "none: ..."`, and a start that carries an effort is refused and starts nothing.

Sources, charmbracelet/crush `v0.102.0`:

- `crush run --help`: "`--reasoning-effort` Reasoning effort for the model (e.g. low, medium, high). Levels depend on the model; unsupported values are rejected with the accepted values listed". `internal/app/app.go` (`overrideReasoningEffort`) checks the level against the model's listed levels (`internal/config/config.go`, `ValidateReasoningEffort`) and logs `Overriding reasoning effort for non-interactive run ... reasoning_effort=<level>`.
- But the level actually sent is decided later, in `internal/agent/coordinator.go` (`getProviderOptions`, `effectiveReasoningEffort`): any `reasoning_effort`, `effort`, `reasoning` or `thinking_config` already in the model's or provider's `provider_options` (the user's config, or Crush's model catalog) wins over the flag. A model whose catalog `reasoning.thinking` is `never` gets no effort at all. Gemini 2 models get a fixed thinking budget instead of the level, and MiniMax models on OpenCode Go/Zen get `thinking: adaptive` instead. Options that fail to parse are dropped. None of these is an error.
- Observed with the release binary and a local fake OpenAI-compatible endpoint that records each request (no account, no network). Every run used `crush run --reasoning-effort high`, exited 0 and logged `reasoning_effort=high`. The agent's request carried `"reasoning_effort": "high"` with a plain model; `"low"` when the user's config had `"provider_options": {"reasoning_effort": "low"}`; and no effort at all for a model marked `"thinking": "never"` that still listed levels.
- Only an unlisted level is refused: `crush run --reasoning-effort high` on a model with no levels exits 1 with `Model "fake-model" does not support reasoning effort.`
