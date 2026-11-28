# Augment Auggie CLI (`auggie`)

Login: auggie's own login, saved by `auggie auth login` in ~/.augment/session.json

Effort: none

The Augment Auggie CLI as a harness row on the local driver ([the harness-row contract](../../harness-row.md)). Check your sign-in with `auggie auth status`. The row never reads, sets or stores a key, and never passes `--augment-session-json`.

- **Start:** `auggie --no-cloud -p --mode json --model <model> "<prompt>"`, in the run's worktree.
- **Wake (same run):** `auggie --session <id> --no-cloud -p --mode json --model <model> "<message>"`, in the same worktree.
- **Stop:** the driver ends the run's process tree. That holds on Linux; macOS waits on the live check (#2448), below.
- **Permission mode:** `full-access` only (below).
- **Cloud mode off:** both turns pass `--no-cloud`. Without it, 1.2.2 turns on cloud mode from a saved preference even when the command line has no `--cloud`, and streams the run to Augment's web UI, where it is visible and steerable. `--no-cloud` overrides `--cloud` and that saved state (`auggie --help` 1.2.2). The fake refuses a turn without it.

## The fact: does the JSON output name the session a wake needs?

**Yes.** Checked on Auggie CLI 1.2.2 (npm `@augmentcode/auggie@1.2.2`, commit `6f24c7b3`, built 2026-11-17), read only, signed out, with no paid call.

1. **The first line of `--mode json` output is the session header.** `auggie -p --mode json "<prompt>"` prints `{"type":"session","version":3,"id":"<uuid>","timestamp":"…","cwd":"…"}` as its first stdout line. It prints this before the model is called, so the line appears even on a run that then fails sign-in. The row's session is `{"json": ["id"]}`: the driver reads `id` from that first JSON line. A synthetic copy is in [evidence/fact-json-header.txt](evidence/fact-json-header.txt).
2. **`--session` takes a file path *or* an id.** `--help` and the [CLI reference](https://docs.augmentcode.com/cli/reference) both say `--session <path>  Use specific session file`. The 1.2.2 code treats the value as a path only when it contains `/` or `\` or ends in `.jsonl`. Otherwise the value is a session-id prefix, looked up first among the sessions saved for the current directory (`~/.augment/sessions-v2/<cwd>/`), then everywhere. A UUID has no `/` and doesn't end in `.jsonl`, so `--session <uuid>` opens that run's own session file. The row passes the id, which fits the contract's session-id pattern, never a path. An unknown id exits 1 with `No session found matching '<id>'`.
3. **A wake must run in the same worktree.** If an id is found only under another directory, 1.2.2 asks on the terminal whether to fork it. The driver wakes in the run's own worktree, so the id is found there and no fork happens.
4. **The session file is saved once the first assistant reply exists.** Before then, a wake finds no session and exits 1. The driver wakes only after the first turn has run.

Result: same-run wake holds, so the row is built.

## Stop leaves nothing running

`auggie -p` runs its indexing in a worker thread (`indexing-worker.mjs`, through `node:worker_threads`), inside the same process. `auggie daemon` is the cloud-agent daemon: the row never starts it, never passes `--cloud`, and passes `--no-cloud` on every turn. The bash tool starts background commands `detached`, in their own process group, so a run can leave one behind. The row declares that background process, its fake starts a stand-in for it, and the harness check requires it to be gone after stop.

- **Linux:** the driver's stop ends every process under the run, including ones that left their process group.
- **macOS:** not claimed yet. There, stop can't reach a process that leaves its turn's process group, closes or redirects its output, and is orphaned before the supervisor's next look ([the local driver's limit](../../README.md)). A detached background command can do exactly that. The row claims macOS only if the signed-in live check (#2448) runs there and its stop leaves nothing running.

## Not installed, not signed in

- **Not installed:** the driver's D3 error says `harness auggie is not installed here`, and its `next` says to install `auggie` and sign in yourself. The CLI's own install is `npm install -g @augmentcode/auggie`.
- **Not signed in:** 1.2.2 prints its session header, then `No API key found for unknown.` on stderr, and exits 1. `auggie auth status` prints `Not logged in.` and exits 1. The row's `signed_out` is `No API key found for `, and its `login_command` is `auggie auth login`. A signed-out start therefore fails with the D3 error `the harness is not signed in`, and its `next` names `auggie auth login`. The fake answers as 1.2.2 does when the runner sets `FAKE_CLI_SIGNED_OUT=1`, and the harness runner's signed-out check covers it. The red runs before HR1's revision 4 are in [evidence/red-signed-out.txt](evidence/red-signed-out.txt) and [evidence/red-signed-out-fields.txt](evidence/red-signed-out-fields.txt).

## Effort: none

The row's `effort` is `none`, because Auggie can drop an effort without an error.

- **The flag:** `--thinking <effort>` sets a reasoning effort the model supports, and `--model <pattern>:<effort>` is the shorthand. Known values are `off`, `minimal`, `low`, `medium`, `high` and `xhigh`. Each model takes only its own `selectableEffortLevels`, and only a few take `xhigh`. Sources: `auggie --help` 1.2.2, the [CLI reference](https://docs.augmentcode.com/cli/reference) and the 1.2.2 code.
- **The fallback:** at session start, 1.2.2 checks the effort against the chosen model. If the model can't take it, Auggie prints `Reasoning effort "<e>" is not supported by <provider>/<model>. Supported values: …. Using the model default.` on stderr and runs at the model default. It neither refuses nor exits non-zero, and a typo such as `--thinking hgih` gets the same fallback. Notes are in [evidence/fact-thinking-fallback.txt](evidence/fact-thinking-fallback.txt).
- **No check first:** the only list of a model's efforts is `auggie model list --json`, which needs sign-in and the network. This row has no `precheck`, the contract's read-only command before the first turn. Seeing the warning after the start is too late to "refuse and start nothing". The contract says a row must not claim an effort its CLI silently ignores for some models.
- **So:** once the local driver's `effort` start field is on, a start that carries an effort gets the driver's D3 refusal and starts nothing, with exactly this `next`: `this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default` (today the local driver's request check refuses any start that carries `effort` with `the input needs exactly repository, ticket, skill, harness, model`, and starts nothing either). A start without an effort runs at the model's default. If a later Auggie refuses an unsupported effort with a non-zero exit, the row can switch to an effort map through `--thinking {effort}`.

## Permission mode

Auggie has no sandbox and no permission mode. In `-p`, 1.2.2 runs every tool, including `bash`, without asking. The one exception is a tool the owner's own `toolPermissions` rules in `~/.augment/settings.json` deny: with no matching rule, the call is allowed. `--tools` limits only the built-in tools, while extension, MCP and subagent tools stay available, so the row offers no "read-only" mode it can't keep.

The row's one mode is `full-access`, which adds no arguments. Approving it means "Auggie may run any tool in the run's worktree, as your own settings allow". Any other mode is refused by the driver, and nothing starts.

## Sources

- `auggie --help`, version 1.2.2: [evidence/auggie-help-1.2.2.txt](evidence/auggie-help-1.2.2.txt).
- The Auggie CLI reference: https://docs.augmentcode.com/cli/reference (`--print`, `--mode json`, `--session <path>`, `--fork <path-or-id>`, `--thinking <effort>`).
- The 1.2.2 package's own code (`auggie-v2.mjs`): the session-argument resolver, the session header in JSON mode, the reasoning-effort check, the tool-permission rules and the indexing worker.

Synthetic: in this folder, `fake` is the only CLI. It answers in the command-line forms above.
