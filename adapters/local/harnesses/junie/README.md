# JetBrains Junie CLI (`junie`)

Login: Junie's own sign-in: the JetBrains account you sign in to in an interactive `junie` (kept under ~/.junie), or JUNIE_API_KEY set in your own environment; the row never reads, sets or stores a key

Effort: none

This is the harness row for [JetBrains Junie CLI](https://junie.jetbrains.com/docs/junie-cli.html), as the [harness-row contract](../../harness-row.md) shapes it. Every fact below was read from Junie CLI **26.9.7** (build 3110.7, the `@jetbrains/junie` 3110.7.0 package and GitHub release 3110.7) without a sign-in, a key or a paid call. `evidence/help-26.9.7.txt` is that build's `junie --version` and `junie --help`.

## Commands

| Move | Command |
| --- | --- |
| Start | `junie --skip-update-check --output-format json --model <model> --task "<prompt>"` |
| Wake (same run) | `junie --skip-update-check --output-format json --session-id <id> --resume --model <model> --task "<message>"` |
| Stop | the driver ends the run's whole process tree |

`--skip-update-check` keeps a turn from fetching a Junie update as it starts ("Useful for CI or automation", `junie --help`).

## The census check: where the wake's session id comes from

**Resolved: the JSON output names it, so the row's `session` is `{"json": ["sessionId"]}`.** The driver reads `sessionId` from the start turn's output and wakes with `--session-id <id> --resume`. The driver can't choose the id up front.

1. `junie --help` (26.9.7): `--session-id=<text>  Id of the previously executed session to follow up`; `--resume  Resume the last session (or the session specified by --session-id)`; `--output-format=<text>  Output format: text, json, json-stream`.
2. The [CLI reference](https://junie.jetbrains.com/docs/parameters.html): `--session-id` is to "resume a previous session ... If none is provided, a new session ID is generated." Junie makes the id; the caller doesn't pass in a new one.
3. JetBrains' own GitHub Action, [JetBrains/junie-github-action](https://github.com/JetBrains/junie-github-action) at `01609521de2e2d5cff40d778508dcb9e2d2713f7`, runs `junie --output-format="json" --json-output-file=...` and reads the result as `CliOutput { sessionId?: string; errors?: string[]; taskName?: string; result?: string; ... }` (`src/github/junie/types/junie.ts`).
4. The 26.9.7 build's JSON output type (`api/CliOutput`) holds `sessionId`, `taskName`, `result`, `changes`, `errors` and `llmUsage`.

In `json` mode Junie prints that one line when the turn ends, so the id is known once the start turn is done. A wake before then is refused by the driver and starts nothing. The fake prints `{"sessionId": ...}` the same way, as one JSON line.

## Permission mode

**The one mode is `allow-all`, which adds no argument.** A headless Junie run approves every action, and nothing narrows it:

- `junie --help`: `--brave  Turns on Brave Mode (interactive only)`. There is no other permission flag.
- The 26.9.7 build's headless host (`hosts/batch/JunieHostBatch.runTask`) always passes `HumanInLoopSettings.AllowAll` to the run, with no branch.

So an owner who approves Junie approves a run that can run commands and edit files without asking. The mode's name says so. An owner who approves any other mode for `junie` gets the driver's refusal, and nothing starts.

## Effort

**Resolved: none.** The row's `effort` is `"none: ..."`. A start that names an effort gets a D3 error and starts nothing. Its `next` is `this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default`. Junie has an `--effort` flag, but a headless run can drop an effort without an error, and the row can't check first.

1. `junie --help` (26.9.7): `--effort=<text>  Effort level to use. Possible values: low, medium, high.`
2. The [CLI reference](https://junie.jetbrains.com/docs/parameters.html) and [Model selection](https://junie.jetbrains.com/docs/junie-cli-model-selection.html) (both dated 21 November 2026) say `--effort` (env `JUNIE_EFFORT`) "Fails with an error listing the model's supported efforts if the value is unsupported or blank. Requires `--model` ...".
3. The 26.9.7 build's own bundled docs (`bundled-agents/junie-cli-docs.md`): `--effort <level>` sets "the default effort level for new sessions".
4. The 26.9.7 build's code for a headless run: the effort string goes unchecked into the run's model context. The agent applies it through `EffortLevel.forModelOrDefault(<effort>, <model>, ...)`, which falls back to the model's default effort for a level the model doesn't support. The only check that throws, `Effort '<x>' is not supported for model '<m>'`, is in the interactive model picker. The build has no "requires `--model`" check either.

- The error the docs describe is in newer builds only. Junie 26.11.2 (build 4100.11, a GitHub release, not the npm `latest` here) refuses `--effort` without `--model` before sign-in. Its check on the level runs only after sign-in, so it is unverified here, and it still applies effort through the same `forModelOrDefault` call.
- The levels a model takes depend on the signed-in account's model list, which a headless run can't list without starting a turn.
- To take effort later: pin a build whose headless run refuses an unsupported level, prove that on a signed-in CLI, then map `low`, `medium` and `high` to `--effort <level>`.

## Background process

**None: `daemon` is `none`.** Junie has a gateway worker (`junie --gateway`, stopped with `junie --gateway-stop`; "a headless gateway worker that executes gateway commands (e.g. cron jobs)", `junie --help`), which it can launch as a detached process (`--__run-gateway`). In the 26.9.7 build, a run starts it only when the build's `loopsEnabled` setting is on. The release build (`configuration/env/JunieCliRelease`) leaves it at the default, off. A signed-out `--task` run left no process running.

## Not installed, not signed in

- **Not installed:** the driver refuses because `junie` isn't on `PATH`, and its `next` says to install Junie and sign in.
- **Not signed in:** a signed-out `junie --output-format json --task "..."` prints `{"errors":["Cannot find authorization. Please authenticate before running Junie."]}`, with no `sessionId`, and **exits 0**. This was seen with a throwaway home folder and no key. The row's `signed_out` pattern matches that line, so even at exit 0 the driver fails the start with `the harness is not signed in`. Its `next` says to sign in with the row's `login_command`, `junie`: an interactive `junie` opens Junie's sign-in on its welcome screen ([Quickstart](https://junie.jetbrains.com/docs/junie-cli.html), step 3). The fake answers signed out the same way.

## Live check

The row merges only after its live check records 5 of 5 on a real signed-in Junie (contract section 7).
