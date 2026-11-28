# kiro-cli: Kiro CLI on the local driver

Login: Kiro CLI's own login: kiro-cli login stores it, or the user sets KIRO_API_KEY; the driver never reads or passes it

Effort: none

The `kiro-cli` harness row, under the [harness-row contract](../../harness-row.md). The program is `kiro-cli`. Facts below are from the [headless reference](https://kiro.dev/docs/cli/headless/), [session management](https://kiro.dev/docs/cli/chat/session-management/) and [authentication](https://kiro.dev/docs/getting-started/authentication/).

## Commands

The CLI chooses the session id, a UUID. With `--output-format stream-json`, headless V3 emits self-contained JSON Lines events on stdout, carrying Kiro's own `data.sessionId` ([headless](https://kiro.dev/docs/cli/headless/)). Reading `session` from the JSON path `["data", "sessionId"]` keeps wake on the started session's id even when the assistant quotes a `kiro-cli chat --resume-id <uuid>` command in its response.

| Turn | Command |
| --- | --- |
| Start | `kiro-cli chat --v3 --no-interactive --output-format stream-json --model <model> --trust-all-tools <prompt>` |
| Wake | `kiro-cli chat --v3 --no-interactive --output-format stream-json --resume-id <session> --model <model> --trust-all-tools <prompt>` |
| Stop | none of its own: the driver's stop ends the whole process tree |

`--no-interactive` is the headless flag. `--v3` names the harness, so the run does not follow the headless default and satisfies `--output-format stream-json` (V2/V3 only). `--model` pins the model for the run. `--resume-id` resumes that session. `--resume` resumes the newest matching session, so wake does not use it. The headless reference names no process that leaves the turn, so `daemon` is `none`.

## Modes

| Mode | Arguments | What it allows |
| --- | --- | --- |
| `trust-all-tools` | `--trust-all-tools` | Every tool call for this session, with nobody asked to approve |

A headless run has no user to approve a tool call. The reference's other flag, `--trust-tools`, takes a list of tool ids. This row offers only `trust-all-tools`.

## The census check, resolved

**Does a headless run resume the session id the CLI printed? Yes.**

1. With `--output-format stream-json`, Kiro CLI emits JSON Lines run events on stdout carrying `data.sessionId` ([headless](https://kiro.dev/docs/cli/headless/)). Session ids are UUIDs ([session management](https://kiro.dev/docs/cli/chat/session-management/)).
2. The headless flags table lists `--resume-id` as resume of a local or cloud session by that id ([headless](https://kiro.dev/docs/cli/headless/)).
3. The row's `session` reads `["data", "sessionId"]` from the stream-json output, and wake passes the captured id as its own `--resume-id` argument.
4. The fake prints a `runStarted` JSON line carrying `data.sessionId` as the UUID `00000000-0000-4000-8000-<its 12 hex digits>`, and maps that UUID back on a wake. It refuses a `--resume-id` that is not a full UUID.

## Effort

The headless reference lists `--effort` and says the supported levels depend on the selected model. It names no level that every model accepts, so the row does not pass the flag. A start that carries an effort is refused.

## Signed out

The `kiro-cli whoami` troubleshooting line for a missing login is a Not logged in error, and it says to login with `kiro-cli login` ([CLI commands](https://kiro.dev/docs/reference/cli-commands/)). Headless authentication is a stored login, or `KIRO_API_KEY` in the environment ([headless](https://kiro.dev/docs/cli/headless/), [authentication](https://kiro.dev/docs/getting-started/authentication/)). The row's `signed_out` pattern anchors to the standalone CLI diagnostic so ordinary response text mentioning `Not logged in` is not mistaken for a signed-out run. `start` then fails with `the harness is not signed in`. Its `next` names `kiro-cli login` and `KIRO_API_KEY`. The driver never reads the variable. The fake prints `Not logged in. Login with kiro-cli login.` when told it is signed out, and exits 2 when a login value is an argument.

No test starts the real `kiro-cli` program. The runner puts a refusing stub for each known agent CLI on `PATH`, with only this folder's `fake` ahead of them.
