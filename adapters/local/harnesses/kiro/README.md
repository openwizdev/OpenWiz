# Kiro CLI (local runs)

Login: Kiro CLI's own sign-in on this machine, `kiro-cli login`, or KIRO_API_KEY that you set in your own environment (paid tiers); the row never reads, sets or stores a key

A harness row for the [local driver](../../README.md), in the shape of the [harness-row contract](../../harness-row.md). It runs [Kiro CLI](https://kiro.dev/docs/cli/) on this machine only; cloud sessions (`--cloud`) are out of scope.

Effort: none

- **Start:** `kiro-cli chat --v3 --no-interactive --output-format stream-json --model <model> <mode's arguments> <prompt>`.
- **Wake (same run):** the same, with `--resume-id <session>` after `stream-json`, and the approved mode's arguments again, so a resumed turn keeps the approved permissions.
- **Session:** reported. Kiro picks the session id (a UUID; [Session management](https://kiro.dev/docs/cli/chat/session-management/)) and there is no flag to choose it. Kiro's stream-json records carry it as `"sessionId"` (documented for the `runError` record); the row reads the first non-null one with the pattern `"sessionId":"(...)"`. That a successful run's first records carry it is unverified until the live check (openwizdev/OpenWiz#2452).
- **Stop:** the driver ends the run's process tree, the V3 engine subprocess included. The row never runs `--delete-session`, so the session stays on this machine.
- **Effort:** none: a start that carries an effort is refused and starts nothing (see [the effort fact](#the-effort-fact)).
- **Permission modes:** `trust-all-tools` passes `--trust-all-tools`. `permissions-yaml` passes nothing, so only your own `~/.kiro/settings/permissions.yaml` rules decide, and a headless run denies every tool call those rules don't allow. Approve one of these for `kiro` as for a built-in harness.

## The open fact: can a headless run use the browser sign-in?

**Yes.** A headless run (`--no-interactive`) uses an active `kiro-cli login` session first, and `KIRO_API_KEY` only when no such session is active. So a user signed in with `kiro-cli login` needs no key, and `KIRO_API_KEY` is the way in where nobody can sign in (CI, or a machine with no browser and no device flow).

Sources, read on 2026-11-22, read only (no sign-up, sign-in or paid call):

1. [Authentication](https://kiro.dev/docs/getting-started/authentication/), "Authentication precedence": "When multiple credentials are available, Kiro CLI uses this precedence order: Active browser session (from `kiro-cli login`), `KIRO_API_KEY` environment variable, No credentials - CLI prompts you to sign in." The same page's "Remote machine authentication (CLI)" gives the device flow for machines that cannot open a browser.
2. [Headless mode](https://kiro.dev/docs/cli/headless/), "Authentication": "Headless mode requires an API key set as the `KIRO_API_KEY` environment variable." Read with source 1, this is the CI case (no browser session on the runner), not a refusal of the browser session: the precedence rule above is for the whole CLI.
3. Kiro CLI 3.5.0's own answer, the stable Linux build from the official installer's manifest (checksum checked), run signed out with an empty home folder: `kiro-cli chat --v3 --no-interactive --output-format stream-json "hi"` exits 1 and prints ``{"type":"runError","data":{"sessionId":null,"stage":"auth","message":"Not logged in. Set the KIRO_API_KEY environment variable or run `kiro-cli login` first."}}``. The headless run names both ways in. It leaves no process running.
4. `kiro-cli chat --help` (3.5.0): `--resume-id <SESSION_ID>` "Resume a specific conversation by session ID"; `--output-format stream-json` gives "The run's ACP events as JSON Lines on stdout"; `-d, --delete-session <SESSION_ID>` deletes a saved session (never used here).

The fact does not go against the row: the wake resumes the same session by id (`--resume-id`, sources 2 and 4), and the stop ends the run's process tree, which holds every process a local run starts (`kiro-cli serve`, the persistent server, is a separate command the row never runs).

## The effort fact

Kiro CLI has a reasoning-effort flag, `--effort <level>`, but it can drop the level without an error, so the row declares effort none. Sources, read on 2026-11-22, read only:

1. [Reasoning effort](https://kiro.dev/docs/models/effort/): the levels are `low`, `medium`, `high`, `xhigh` and `max`; "To set the initial effort level when you start a session, use the `--effort` flag"; "Not all models support every level"; "In V3, `--effort` and `--model` apply only to the session Kiro starts with and aren't saved as defaults."
2. [Headless mode](https://kiro.dev/docs/cli/headless/), "Agent selection" and its flags table: "Pass `--effort <level>` to set the reasoning effort for a non-interactive run. Supported levels depend on the selected model. In V3, the flag applies only to the session Kiro starts and does not change the saved per-model default."
3. `kiro-cli chat --help` (3.5.0): `--effort <EFFORT>` "Initial effort level (e.g. low, medium, high, xhigh, max)".
4. Kiro CLI 3.5.0's own binary carries the message `[warn] failed to set effort '<level>'` beside its effort request to the engine, the same warn-and-continue the Headless mode page documents for `--model` ("If Kiro cannot set the requested model, it writes a warning to stderr and continues the run"). A level the model doesn't take is dropped with a warning, not an error.
5. No check-first: `kiro-cli chat --list-models --format json` needs a sign-in (run signed out, it prints only Kiro's "Not logged in" line), and the [CLI commands reference](https://kiro.dev/docs/reference/cli-commands/) documents no per-model effort levels in its output.

So the row takes effort in the contract's second form: `"effort": "none: kiro-cli's --effort warns and runs on when the model can't take the level, with no documented check first (kiro.dev/docs/cli/headless, kiro.dev/docs/models/effort, kiro-cli 3.5.0)"`. A start that carries an effort is a D3 error that starts nothing, and its `next` is: "this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default". A run without one uses the model's own default. The flag comes back once Kiro fails a run on a level it can't set, or documents a way to read a model's levels before the run.

## Not installed, not signed in

- `kiro-cli` not on `PATH`: the driver's D3 error `harness kiro is not installed here`, whose `next` says to install kiro-cli and sign in to it yourself, then start again. Kiro's installer is `curl -fsSL https://cli.kiro.dev/install | bash` ([Installation](https://kiro.dev/docs/cli/setup/)).
- Not signed in: Kiro prints ``Not logged in. Set the KIRO_API_KEY environment variable or run `kiro-cli login` first.`` on stderr and a `runError` record with `"stage":"auth"` in its stream-json output, and exits 1. The row's `signed_out` pattern, `"type":"runError".*"stage":"auth"`, matches that record (Kiro's documented error record, [Headless mode](https://kiro.dev/docs/cli/headless/), "Error records"), so `start` fails with the driver's D3 error `the harness is not signed in`, whose `next` names the row's `login_command`, `kiro-cli login`. Where nobody can sign in, set `KIRO_API_KEY` in your own environment instead.

## Tests

```sh
python3 -I adapters/local/test_harnesses.py    # finds this row; the contract, the kit's five checks with ./fake, the session, env, background-process and effort checks, then test_row.py
```

`fake` is a synthetic `kiro-cli`: it allows only Kiro's documented headless and resume command lines (exit 2 on any other), prints its session id in a stream-json event, starts a background process for its V3 engine, and, with `KIRO_FAKE_SIGNED_OUT=1`, answers as a signed-out kiro-cli 3.5.0 does. `test_row.py` checks not installed, not signed in, each mode's exact command line, and each Kiro effort level refused with the fixed `next`. The live check, with a real signed-in Kiro CLI, is a person's ticket (openwizdev/OpenWiz#2452).
