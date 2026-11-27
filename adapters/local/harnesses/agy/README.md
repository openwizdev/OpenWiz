# Antigravity CLI (agy)

Login: Antigravity CLI's own sign-in, saved in the OS keyring by an interactive `agy` session, or GEMINI_API_KEY with modelProvider gemini that you set yourself; the row never reads, sets or stores a key

A harness row for the [local driver](../../README.md), in the shape of the [harness-row contract](../../harness-row.md). It runs [Antigravity CLI](https://antigravity.google/docs/cli/headless) on this machine in headless mode. Every fact below is read from Antigravity CLI 1.5.14, the version the official installer's Linux manifest named on 2026-11-23, and from its docs read the same day. Nothing was installed, run or signed in to.

Effort: `--effort low`, `--effort medium`, `--effort high`, `--effort xhigh` or `--effort max`, at start and again at each wake

## Where the login lives

`agy` keeps its own sign-in. An interactive `agy` session signs you in once (a browser, or a pasted code over SSH), and saves the token in the OS keyring: Apple Keychain, Linux Secret Service over D-Bus, or Windows Credential Manager ([Authenticate](https://antigravity.google/docs/install.md), "Local silent keyring sign-in"). Headless runs use that saved sign-in ([Headless mode](https://antigravity.google/docs/cli/headless.md), the note under "Run a single prompt"). The other way in is your own Gemini API key: set `"modelProvider": "gemini"` in `~/.gemini/antigravity-cli/settings.json` and export `GEMINI_API_KEY` yourself; the key alone does nothing ([Authenticate](https://antigravity.google/docs/install.md), "Using a Gemini API key"). The driver never reads or passes a login: it adds only `AGY_CLI_DISABLE_AUTO_UPDATE=true` to the turn's environment.

## The commands

- **Start:** `agy -p <prompt> --output-format stream-json --model <model> <mode's arguments> [--effort <level>]`.
- **Wake (same run):** `agy -p <prompt> --conversation <session> --output-format stream-json --model <model> <mode's arguments> [--effort <level>]`. The approved mode's arguments, the model and the effort go again on every wake, since each `agy -p` is a new process and its flags last one invocation.
- **Session:** reported. `agy` picks the conversation id (a UUID), and there is no flag to choose it. With `--output-format stream-json`, the stream's first line is an `init` event whose top-level `conversation_id` names it; the row reads `{"json": ["conversation_id"]}` from that line. `--conversation <id>` resumes it ([Headless mode](https://antigravity.google/docs/cli/headless.md), "Streaming JSON" and "Continue a conversation").
- **Env:** `AGY_CLI_DISABLE_AUTO_UPDATE=true`, so no turn starts the background self-updater ([Troubleshooting](https://antigravity.google/docs/cli/troubleshooting.md), "Resolve self-updater locks and failures"; the name is in the 1.5.14 binary's strings).
- **Stop:** the driver's own stop, which ends the run's whole process tree (the next section).
- **Permission modes:** approve one for `agy` as for a built-in harness ([Execution modes](https://antigravity.google/docs/cli/modes.md), [CLI reference](https://antigravity.google/docs/cli/reference.md), "Command-line flags"):
  - `auto` passes `--mode=auto`: workspace edits and safe commands run without asking. It needs the terminal sandbox and a personal account; where it isn't available, headless `agy` warns and runs in `default` mode.
  - `accept-edits` passes `--mode=accept-edits`: workspace edits run; terminal commands still need approval, which a headless run can't get, so they are soft-denied.
  - `dangerously-skip-permissions` passes `--dangerously-skip-permissions`: every tool call is approved.
  - `settings` passes nothing, so your own `agentMode` and `permissions` in `~/.gemini/antigravity-cli/settings.json` decide.

### Why stream-json and not json

The drivers census named `--output-format json`. That envelope is "one JSON object printed on completion" ([Headless mode](https://antigravity.google/docs/cli/headless.md), "Output formats"), so its `conversation_id` would reach the driver only when the first turn ends. The kit wakes a run as soon as its builder note appears, while the first turn still runs, and the driver refuses a wake until it knows the session id. `stream-json` prints the same id at once, in the `init` event that opens the stream, so the row uses it.

## The census check: does stop end the language server?

**Yes, by the driver's own stop.** The census expected `agy` to start a language-server child. In 1.5.14 there is no separate language-server program to start:

1. The installer ([`install.sh`](https://antigravity.google/cli/install.sh)) downloads one archive per platform from its manifest and copies one file out of it, `antigravity`, to `~/.local/bin/agy`. The 1.5.14 Linux x64 archive (checksum checked against the manifest) holds that one file and nothing else.
2. That binary's own Go package paths carry the language server: `jetski/language_server/language_server`, its `(*Server)` methods and its HTTPS server are compiled into `agy` itself, beside the CLI's own `cli/...` packages. The only separate `language_server_linux_x64` path in it belongs to a remote-SSH init script for the IDE, which `agy -p` never runs.
3. The CLI's changelog speaks of "its language server" failing as a part of the CLI: 1.1.14 "Fixed the CLI exiting silently when its language server failed at startup or during execution; failures are now logged to the terminal and exit with a non-zero status" ([Changelog](https://antigravity.google/docs/changelog.md), Antigravity CLI).

What a turn can still start lives under it: stdio MCP servers, the agent's terminal commands, daemon tasks such as dev servers, and `/swarm` workers. 1.2.9 says headless runs no longer leave "daemon background processes running after exit", and the binary prints `terminating %d background task(s) and %d daemon task(s) on exit`; those are the CLI's own clean-up when it exits normally. The driver doesn't rely on it: its stop ends the whole process tree of the run, including a process that left the turn's process group on Linux. So the row declares this in `daemon`, and its fake starts a language-server stand-in that is the hard case, double-forked into its own session with its output closed, which the runner must find ended after stop.

That the docs and the binary's text show no separate language-server process is read, not watched. The live check (`Live check` below) is where a person sees, on their own machine, that nothing of `agy` is left running after stop. As the contract sets, the row claims only the platforms that check runs on.

## The effort fact

`agy` takes effort as a flag, and a level the model doesn't offer fails the run instead of being dropped, so the row passes the user's effort in the contract's first form:

1. [Headless mode](https://antigravity.google/docs/cli/headless.md), "Select a model, effort, or agent" and its flag reference: `--effort` sets "Reasoning effort: `low`, `medium`, `high`, `xhigh`, or `max` (depending on the model)"; headless mode "doesn't silently fall back when `--model` names an unknown model. It exits non-zero with an `ERROR` status".
2. [Effort command](https://antigravity.google/docs/cli/commands/effort.md): the five levels; `--effort` "applies only to the current invocation and doesn't change the default saved in your settings"; a valid level the model doesn't offer is refused with the levels it has (`<model> has no "max" effort (available: low, medium, high)`).
3. The 1.5.14 binary carries the messages `Invalid effort %q (valid: %s)`, `%s has no %q effort (available: %s)` and, on the headless path, `invalid model selection (--model %q --effort %q): %w`, beside an `EffortUnsupportedError` type.

So `effort` maps each of `low`, `medium`, `high`, `xhigh` and `max` to `--effort <level>`. `{effort}` sits in both start and wake, because the flag lasts one invocation, and the driver passes the start's effort again at each wake. Any other effort is refused before anything starts, with the contract's fixed `next`. Open: what `--effort` does on a model with a fixed reasoning budget, such as Orchestrator ("the CLI reports that effort isn't adjustable for the current model", read for `/effort`), is not written for the flag; the live check runs without an effort.

## Not installed, not signed in

- `agy` not on `PATH`: the driver's D3 error `harness agy is not installed here`. The installer is `curl -fsSL https://antigravity.google/cli/install.sh | bash` ([Getting started](https://antigravity.google/docs/getting-started.md)); it puts `agy` in `~/.local/bin`.
- Not signed in: a headless run "that isn't already authenticated exits with an `authentication required` error instead of hanging" ([Headless mode](https://antigravity.google/docs/cli/headless.md)); the 1.5.14 binary's line is `Error: authentication required. Run '%s' to log in.` The row's `signed_out` pattern matches that line, so `start` fails with the driver's D3 error `the harness is not signed in`, whose `next` names the row's `login_command`, `agy`: run it once, interactively, to sign in.

## Tests

```sh
python3 -I adapters/local/test_harnesses.py    # finds this row: the contract, the kit's five checks with ./fake, the session, env, background-process and effort checks, then test_row.py
```

`fake` is a synthetic `agy`: it allows only the documented headless lines in the row's order (exit 2 on any other), needs `AGY_CLI_DISABLE_AUTO_UPDATE=true`, prints its conversation id in a stream-json `init` event, starts a language-server stand-in, and answers as a signed-out `agy` does when the runner asks. `test_row.py` checks the fake's refusals, not installed, not signed in, each mode's exact command line, the wake's `--conversation` line, the env, and each effort level at start and wake.

Live check: #2552
