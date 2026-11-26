# cursor-agent: the Cursor CLI on the local driver

Login: Cursor CLI's own login: agent login stores it in the system keyring, or an owner-only file when no keyring is available, or the user sets CURSOR_API_KEY; the driver never reads or passes it

Effort: none

The `cursor-agent` harness row, under the [harness-row contract](../../harness-row.md). The program is `agent`. Facts below are from the [Cursor CLI parameters reference](https://cursor.com/docs/cli/reference/parameters), the [output format reference](https://cursor.com/docs/cli/reference/output-format), the [authentication reference](https://cursor.com/docs/cli/reference/authentication) and [Using Headless CLI](https://cursor.com/docs/cli/headless).

## Commands

The CLI chooses the session id. Print mode writes one JSON object, and the row reads `session_id` from the first JSON line that has it.

| Turn | Command |
| --- | --- |
| Start | `agent -p --output-format json --model <model> --force <prompt>` |
| Wake | `agent -p --output-format json --resume <session_id> --model <model> --force <prompt>` |
| Stop | none of its own: the driver's stop ends the whole process tree |

`-p` (`--print`) is print mode for scripts. `--output-format json` works only with print mode and, on success, prints one JSON object whose `session_id` is the session. `--resume` takes that chat id. `--model` selects the model. Wake passes the same id the start turn reported, so the next turn continues that chat.

## Modes

| Mode | Arguments | What it allows |
| --- | --- | --- |
| `force` | `--force` | Every action, including ones that would otherwise need approval, except what `permissions.deny` and team policy block |

Print mode cannot stop to ask. Without `--force`, writes outside the workspace and commands that need approval are rejected. Headless runs in an untrusted workspace fail unless `--trust` or `--force` is passed. This row offers only `force`. `plan` and `ask` do not do the edits a fleet turn makes, and `--api-key` is never an argument: the user signs in with `agent login` or sets `CURSOR_API_KEY` in the environment.

## The census check, resolved

**Does print mode resume a chat id the CLI itself reported? Yes.**

1. `-p` and `--resume` are both global options, and global options apply to any command ([parameters](https://cursor.com/docs/cli/reference/parameters)).
2. `--resume [chatId]` resumes that chat. The overview shows `agent --resume="chat-id-here"` ([overview](https://cursor.com/docs/cli/overview)).
3. With `--print` and `--output-format json`, a successful run prints one object that includes `session_id` ([output format](https://cursor.com/docs/cli/reference/output-format)). The row's `session` is `{"json": ["session_id"]}`, so wake passes that id to `--resume`.

## Effort

**Effort: none. This host can't set effort.** The parameters reference lists no effort flag. Reasoning effort in the interactive `/model` picker, and a fast or high-effort model slug passed to `--model`, are not a flag this row can add without dropping the user's effort. A start that carries an effort is refused.

## Signed out

The authentication reference's troubleshooting line for a missing login is `Not authenticated`. `start` then fails with `the harness is not signed in`. Its `next` names `agent login` and `CURSOR_API_KEY`. The driver never reads the variable. The fake prints `Not authenticated` when told it is signed out, and exits 2 on `--api-key`.

No test starts the real `agent` or `cursor-agent` program. The runner puts a refusing stub for each known agent CLI on `PATH`, with only this folder's `fake` ahead of them.
