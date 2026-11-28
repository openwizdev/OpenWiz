# cursor: Cursor CLI on the local driver

Login: agent's own login: `agent login` saves it locally (the macOS keychain, or ~/.config/cursor/auth.json on Linux), or the CURSOR_API_KEY the user set for the CLI; the driver never reads or passes it

Effort: none

Live check: #2478

The `cursor` harness row runs Cursor CLI (`agent`) as a builder through the user's own sign-in, under the [harness-row contract](../../harness-row.md). Everything here was read at **Cursor CLI 2026.11.22-e9042b2**, the version [`https://cursor.com/install`](https://cursor.com/install) installed on 2026-11-23, and from Cursor's CLI docs on that day. Its `--help` text was read from that package's own source (`index.js`), never by running the CLI.

## Commands

| Turn | Command line |
| --- | --- |
| Start | `agent --print --output-format stream-json --trust --model <model> <mode's arguments> <prompt>` |
| Wake | `agent --print --output-format stream-json --trust --resume <session id> --model <model> <mode's arguments> <prompt>` |
| Stop | the driver's own stop: it ends the turn's whole process tree |

- **Session id:** the first JSON line with a `session_id` key. In `stream-json` that is the `system`/`init` event, which the CLI prints once at the beginning of the session ([output format](https://cursor.com/docs/cli/reference/output-format#system-initialization)), so the id is known as soon as the run starts.
- **`--trust`:** print mode refuses a workspace the user hasn't trusted with `Workspace Trust Required` and exit 1, unless `--trust`, `--yolo` or `-f` is passed. The driver's clone is a new folder each run, so both lines pass `--trust` ([parameters](https://cursor.com/docs/cli/reference/parameters#global-options): "Trust the workspace without prompting (headless mode only)").
- **Signed out:** in print mode the CLI exits 1 with `Error: Authentication required. Please run 'agent login' first, or set CURSOR_API_KEY environment variable.`, or a server message followed by `Please run 'agent login' to authenticate.` The row's `signed_out` pattern matches the second form too, and `start` then names `agent login` ([authentication](https://cursor.com/docs/cli/reference/authentication#troubleshooting)).
- **Background process:** `agent` runs each shell tool command as its own detached process group under the turn (its bundled `shell-exec` module spawns each one with `detached: true`), and in print mode waits for background shells after its last message before it aborts them (the hidden `--background-shell-timeout` option's help). Stop ends them with the process tree; the fake simulates one such process.

## Modes

| Mode | Arguments | What it does |
| --- | --- | --- |
| `force` | `--force` | "Force allow commands unless explicitly denied": every action runs except what `permissions.deny` and team policies block ([headless](https://cursor.com/docs/cli/headless#file-modification-in-scripts)) |

No `allowlist` mode is offered: Cursor CLI 2026.11.22-e9042b2 has no flag to enforce `allowlist` over an effective `approvalMode: "unrestricted"` from user or merged project config, so omitting `--force` can still run every action in print mode ([headless](https://cursor.com/docs/cli/headless#file-modification-in-scripts), [configuration](https://cursor.com/docs/cli/reference/configuration#optional-fields)). Requiring explicit approval of `force` prevents an owner from approving `allowlist` and getting Run Everything silently.

## The census check: do `-p` and `--resume` work together?

**Yes.** `--print` and `--resume [chatId]` are both global options that "can be used with any command" ([parameters](https://cursor.com/docs/cli/reference/parameters#global-options)), and the CLI's source agrees: its one agent action reads `--resume <chatId>`, then starts the same `resume` session in print mode as interactively. Print mode refuses a resume only when that chat is running inside an `agent persist` session ("Chat … may still be running"), and this row never uses `agent persist`. A bare `--resume` with no id opens an interactive picker, so the wake line always passes the saved id. The census's `--output-format json` is not used: it prints `session_id` only in the one object at the end of a successful run ([output format](https://cursor.com/docs/cli/reference/output-format#json-format)), so a wake during a long first turn would find no session id.

## Effort

The row's effort is `none`. Cursor CLI 2026.11.22-e9042b2 has no effort flag and no effort environment setting: its options list none ([parameters](https://cursor.com/docs/cli/reference/parameters#global-options)), and its own `--model` help says "Parameterized models accept quoted bracket overrides, e.g. 'claude-opus-4-8[context=1m,effort=high,fast=false]'". Effort is part of some model ids, never a separate argument, so a fixed argument can't add it and a start with an effort is refused.

## The fake

`fake` parses the documented global options in any order, as `--name value` or `--name=value`, and exits 2 on anything else: an unknown option, a missing value, a value outside `--output-format`, `--mode` or `--sandbox`'s choices, a `-H` or `--header` value without a non-empty `Name: Value` header, `--stream-partial-output` without `stream-json`, `--resume` with `--continue`, or a bare `--resume` in print mode. It simulates only the start and wake above, exits 3 on any other documented command line (a subcommand, `--api-key`, or a run other than print mode with `stream-json`), and, without `--trust`, `--force` or `--yolo`, exits 1 as the real CLI does. `test_row.py` checks each of these.

Synthetic: `fake` is the only CLI here.
