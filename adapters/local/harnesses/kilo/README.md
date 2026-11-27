# Kilo Code CLI (`kilo`) harness row

Login: kilo's own login, saved by `kilo auth login` under ~/.local/share/kilo (auth.json)

Effort: none

This row never reads, sets or stores a key: a run uses whatever `kilo auth login` saved. Not installed: the driver refuses before anything starts (`install kilo on this machine and sign in to it yourself, then start again`). Not signed in: when the model needs a login Kilo doesn't have, the first turn prints Kilo's own error and exits. The row's `signed_out` patterns match Kilo's signed-out lines (Kilo CLI v7.8.32): `authentication token may be missing or expired` (a 401, `packages/opencode/src/provider/error.ts`), `Kilo credentials are required` (`packages/opencode/src/kilocode/cloud/auth.ts`), and the gateway code `PAID_MODEL_AUTH_REQUIRED` ("You need to sign in to use this model", [`packages/opencode/src/kilocode/kilo-errors.ts`](https://github.com/Kilo-Org/kilocode/blob/v7.8.32/packages/opencode/src/kilocode/kilo-errors.ts), lines 26-27), which arrives in the JSON error line's `responseBody`. The other gateway code, `PROMOTION_MODEL_LIMIT_REACHED`, is not matched: Kilo's own text for it is "You need to sign up to keep going" and "... Or come back later" (the same file, lines 28-29 and 40-41). That is the free-model usage limit, which also clears with time, so it stays a plain `the harness failed`, and its `next` points at the log, not at `kilo auth login`. The driver then refuses with `the harness is not signed in`, and its `next` names the row's `login_command`, `kilo auth login`. With no login, Kilo may still run its free models; then nothing is signed out.

## Commands

- **Start:** `kilo run --format json --model {model} {mode} {prompt}`. Every JSON event line carries `sessionID`, so the session is `{"json": ["sessionID"]}`, read from the run's log. `{model}` is Kilo's `provider/model`.
- **Wake (same run):** `kilo run --format json --session {session} --model {model} {mode} {prompt}`.
- **Stop:** Under [HR1](../../harness-row.md#1-the-row), the driver guarantees cleanup of the run's process tree on Linux. On macOS, a detached persistent background process Kilo starts may outlive stop if it is orphaned before the supervisor records it and its output is closed or redirected. [Live check #2443](https://github.com/openwizdev/OpenWiz/issues/2443) covers the platform claim. The row sets `KILO_NO_DAEMON=1` to keep turns off the user's daemon.
- **Modes:** `default` adds nothing: a plain headless `kilo run` rejects every permission ask, so the run does only what needs no ask. `auto` adds `--auto`, which approves every ask the user's Kilo config doesn't deny ("dangerous!" in Kilo's help). Kilo's hidden `--yolo` and `--dangerously-skip-permissions` aren't mapped.

## The census check: does `kilo run` use the background daemon, and does stop leave it running?

Settled from Kilo CLI v7.8.32's own source, docs and `--help`. Everything here was read only: no sign-in, no model call.

1. `kilo run` **never starts** a daemon, but it **attaches to one that is already running**. When `--attach` isn't given, its handler calls `KiloRunDaemon.attach`. If `DaemonClient.maybe()` finds a healthy daemon, the whole turn runs on that daemon's server. Only when it finds none does it boot an embedded in-process server. Sources: [`packages/opencode/src/cli/cmd/run.ts`](https://github.com/Kilo-Org/kilocode/blob/v7.8.32/packages/opencode/src/cli/cmd/run.ts) (lines 1197-1218) and [`packages/opencode/src/kilocode/cli/cmd/run.ts`](https://github.com/Kilo-Org/kilocode/blob/v7.8.32/packages/opencode/src/kilocode/cli/cmd/run.ts) (`KiloRunDaemon.attach`).
2. Only `kilo daemon [start|restart]` and `kilo console` start a daemon. It is a detached `kilo serve`, recorded in `~/.local/state/kilo/daemon.json` ([cli-runtime docs, "Daemon lifecycle"](https://github.com/Kilo-Org/kilocode/blob/v7.8.32/packages/kilo-docs/pages/contributing/architecture/cli-runtime.md#daemon-lifecycle)).
3. The opt-out is the `KILO_NO_DAEMON` environment variable. When it is set, `DaemonClient.enabled()` is false and no client attaches ([`packages/opencode/src/kilocode/daemon/client.ts`](https://github.com/Kilo-Org/kilocode/blob/v7.8.32/packages/opencode/src/kilocode/daemon/client.ts); the same docs table, "Opt-out").
4. `kilo run --help` (v7.8.32) lists `-s, --session` ("session id to continue") and `--format json` ("raw JSON events"). Each event is written with the run's `sessionID` (`emit` in `run.ts`).
5. Kilo can spawn a detached persistent background process with piped output. Its lifetime can extend past the Kilo CLI's exit. [Kilo background-process source](https://github.com/Kilo-Org/kilocode/blob/v7.8.32/packages/opencode/src/kilocode/background-process/index.ts#L974-L983)

**Answer.** By default a run uses the daemon only when the user already runs one, and then the turn's work happens inside the user's daemon. Ending the run's process tree wouldn't end that work, and stopping the daemon would end the user's other sessions. So the row sets `KILO_NO_DAEMON=1`. Every turn runs on its own embedded server inside the run's process tree, and the user's daemon stays untouched. The run starts no daemon of its own, so stop leaves none running. Sessions live in Kilo's local database (`~/.local/share/kilo/kilo.db`), so `--session <id>` on the embedded server wakes the same run.

The fake models both sides: without `KILO_NO_DAEMON` it hands its work to the runner's already-running hub, which stop never reaches; with it, the fake starts its stand-in background process under the turn.

## Effort

The row takes form (b): `"effort": "none: ..."`. Any start that carries an effort is a D3 refusal that starts nothing, with `next` exactly `this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default`.

- **The flag exists:** `kilo run --help` (v7.8.32) lists `--variant` ("model variant (provider-specific reasoning effort, e.g., high, max, minimal)").
- **Kilo's per-model behaviour:** variants belong to each model. Kilo applies `model.variants[variant]` and adds nothing when the chosen model doesn't define that variant ([`packages/opencode/src/session/llm/request.ts`](https://github.com/Kilo-Org/kilocode/blob/v7.8.32/packages/opencode/src/session/llm/request.ts), lines 98-101). The values every reasoning provider shares are `low`, `medium` and `high` (`WIDELY_SUPPORTED_EFFORTS` in `packages/opencode/src/provider/transform.ts`); others exist only for some models. Passing the flag unchecked would be a silent fallback, which the harness-row contract forbids.
- **Why not check it first:** this row has no `precheck` yet, the contract's read-only command before the first turn.
- **How a later `precheck` row field could check it:** `kilo models <provider> --verbose` is read-only, needs no sign-in and makes no model call. It prints each model as `<provider>/<model>`, then its JSON, including `variants` ([`packages/opencode/src/cli/cmd/models.ts`](https://github.com/Kilo-Org/kilocode/blob/v7.8.32/packages/opencode/src/cli/cmd/models.ts)). A signed-out run on an empty home listed every model with its `variants`. With a `precheck`, this row can check the effort against that list and map it to `--variant {effort}`.

## Synthetic

`fake` is the only CLI here. Its `HELP` text restates what it allows. Its fixtures are synthetic.
