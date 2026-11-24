# copilot (GitHub Copilot CLI)

Login: copilot's own login, saved by `copilot login` in the system credential store, or in plain text under ~/.copilot/ (or $COPILOT_HOME) when there is no store

Effort: none

Live check: #2469

The `copilot` harness row on the local driver, under the [harness-row contract](../../harness-row.md). The driver never reads or passes this login: it lives only in copilot's own store, and the user signs in with `copilot login` on their own machine. Signed out, `copilot -p` prints `Error: No authentication information found.` and exits 1, so `start` fails with `the harness is not signed in` and names `copilot login`.

## Commands

The driver picks the session id (`{"chosen": "uuid"}`), saves it, and passes it at start and at every wake.

- **Start:** `copilot -p <prompt> --output-format json --session-id <uuid> --model <model> <mode>`. A `--session-id` that matches no session and is a valid UUID creates a new session with that id.
- **Wake:** `copilot -p <prompt> --session-id <uuid> <mode>`. The same `--session-id` resumes that session, which keeps its model.
- **Stop:** the driver's own stop, which ends the whole process tree.

## Modes

In a `-p` run copilot can't ask, so it denies any tool request that no allow rule approves. The owner approves one of these:

| Mode | Adds | What it allows |
| --- | --- | --- |
| `allow-all-tools` | `--allow-all-tools` | Every tool without asking; file access stays inside the clone and the system temp directory, and URLs keep their checks |
| `allow-all` | `--allow-all` | `--allow-all-tools --allow-all-paths --allow-all-urls` |

Deny rules, organization policy and `permissions.disableBypassPermissionsMode` still win over both.

## Effort (J318)

`Effort: none`. GitHub Copilot CLI v1.0.114 has `--reasoning-effort` (`low`, `medium`, `high`, `xhigh`, `max`), but which levels apply depends on the model, and copilot leaves a level the selected model doesn't offer unapplied: it writes a warning to its own output and runs the turn anyway (upstream [changelog](https://github.com/github/copilot-cli/blob/a9b36a75fd67e99da321b0088202dd7c19c3c492/changelog.md#L2259), 1.0.88 and 1.0.110). The driver doesn't return that warning to the caller, so the row can't promise that a requested level takes effect, and the harness-row contract's section 4 then requires `none`. The row passes no effort flag at start or wake, and a start that carries an effort is a D3 refusal that starts nothing, with the contract's fixed `next`.

## Background process

None (`daemon` is `none`). copilot v1.0.114 can start a detached `copilot --agent rem-agent -p … --yolo --silent` memory pass as a session shuts down, but in that version's `cli-main.js` (in the [`@github/copilot-linux-x64` 1.0.114 package](https://www.npmjs.com/package/@github/copilot-linux-x64/v/1.0.114), read as files) the shutdown callback that starts it is registered only by the interactive UI. The `-p` prompt-mode path this row's start and wake take never registers it. The fake starts no background process, and the live check (#2469) still runs the real stop.

## The census check, resolved

The census needed nothing blocking (the driver picks the UUID), only the permission flags for `modes` and the effort setting. Resolved from GitHub Copilot CLI v1.0.114 (`@github/copilot` 1.0.114, build `780b7b25939`), read as files and never run:

- **Permission flags:** `--allow-all-tools` ("Allow all tools to run automatically without confirmation. Non-interactive mode cannot ask, so it denies tool requests that no allow rule … approves") and `--allow-all` / `--yolo` ("equal --allow-all-tools --allow-all-paths --allow-all-urls"), in v1.0.114's `copilot --help` and `copilot help permissions` text, and the [command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options).
- **Effort:** `--effort=LEVEL`, `--reasoning-effort=LEVEL` ("Set the reasoning effort level (`low`, `medium`, `high`, `xhigh`, `max`)") in the [command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options); added in 1.0.4, with `--effort` as its alias in 1.0.10; a level the model does not offer gets a warning, not silence: "The warning for an unsupported --reasoning-effort value is no longer lost when the session's model changes while the CLI is starting" (1.0.110), and "a level the selected model does not offer is reported and left unapplied" (1.0.88), all in the [changelog](https://github.com/github/copilot-cli/blob/a9b36a75fd67e99da321b0088202dd7c19c3c492/changelog.md#L2259). A level left unapplied with a warning the caller never sees is what section 4 of the contract rules out, so the row declares `none`.
- **Session:** `--session-id ID` resumes a matching session, or "a new session is created only when the value is a valid UUID" ([command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options); 1.0.51 in the [changelog](https://github.com/github/copilot-cli/blob/main/changelog.md)).
- **Output:** `--output-format json` gives JSONL, one record per line ([command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options)).
- **Login:** "an authentication token is stored securely in the system credential store. If a credential store is not found, the token is stored in a plain text configuration file under `~/.copilot/` (or the directory specified by `COPILOT_HOME` if set)" ([command reference, `copilot login`](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference)).
- **Source:** [github/copilot-cli](https://github.com/github/copilot-cli), whose npm package is [`@github/copilot`](https://www.npmjs.com/package/@github/copilot/v/1.0.114).

`fake` accepts only the start and wake lines above, with those modes and no effort flag, and exits 2 on anything outside that row grammar. `test_row.py` checks both. Most refused lines are documented copilot syntax that this row doesn't use (`--output-format text`, `--resume`, `--reasoning-effort`). Two are shapes copilot doesn't accept at all: a top-level `--yes` and a stray positional argument.
