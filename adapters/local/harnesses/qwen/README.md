# qwen (Qwen Code)

Login: qwen's own login: a Qwen subscription sign-in in ~/.qwen/subscription_credentials.json, or an API key provider in ~/.qwen/settings.json or ~/.qwen/.env, chosen with /auth in an interactive qwen

Effort: none

The `qwen` row runs [Qwen Code](https://github.com/QwenLM/qwen-code) on the local driver. Every source below is the `v0.28.4` tag (commit `e8424c88ddd463c56602063efde57c328b917cd4`), the newest release when this row was written. Live check: #2526.

**Platforms: Linux only.** `qwen` can leave a detached hook supervisor that the driver's macOS stop may miss (the background process, below). macOS is claimed only after a live stop on macOS ends one, in #2526.

## Where the login lives

The driver never reads or passes a login. `qwen` finds its own, chosen with `/auth` in an interactive `qwen`:

- a Qwen subscription sign-in (auth type `qwen-subscription`), saved in `~/.qwen/subscription_credentials.json` ([activate-subscription.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/ui/auth/activate-subscription.ts#L30-L55), [subscription-session.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/core/src/qwen/subscription-session.ts#L75-L81));
- or an API key provider in `~/.qwen/settings.json` or `~/.qwen/.env` ([auth.md](https://github.com/QwenLM/qwen-code/blob/v0.28.4/docs/users/configuration/auth.md)).

The legacy Qwen OAuth sign-in (`qwen-oauth`, `~/.qwen/oauth_creds.json`) no longer works headless: `qwen` refuses it and says to run `/auth` and switch ([auth.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/auth.ts#L316-L322)). The `qwen auth` subcommands were removed and only print a notice ([auth.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/commands/auth.ts#L36-L54)), so `login_command` is `qwen, then /auth`.

Each refusal below ends a headless first turn at once with exit 1, as the stream-json `result` with `is_error: true` ([validateNonInterActiveAuth.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/validateNonInterActiveAuth.ts#L48-L76)). The row's `signed_out` has one pattern for each, so `start` says the harness is not signed in and names `qwen, then /auth`:

| `qwen` says | When | Source |
| --- | --- | --- |
| `No auth type is selected...` | no sign-in chosen | [validateNonInterActiveAuth.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/validateNonInterActiveAuth.ts#L26-L29) |
| `Qwen OAuth free tier was discontinued...` | the legacy `qwen-oauth` sign-in | [auth.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/auth.ts#L316-L322) |
| `Missing API key for OpenAI-compatible auth...` | an OpenAI-compatible provider with no key, with or without its own `envKey` | [auth.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/auth.ts#L287-L313) |
| `<NAME> environment variable not found...Please set it in your .env file or environment variables.` | an Anthropic, Gemini or Vertex provider with no key, with or without its own `envKey` | [auth.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/auth.ts#L246-L270) |
| `...Please re-authenticate with the correct type.` | `security.auth.enforcedType` names another sign-in | [validateNonInterActiveAuth.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/validateNonInterActiveAuth.ts#L33-L37) |
| `Your login credentials are no longer valid. Run /auth to sign in again.` | an expired subscription sign-in | [subscription-errors.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/core/src/qwen/subscription-errors.ts#L19-L20) |

These are `qwen`'s English messages. Most go through its translations ([auth.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/auth.ts#L298-L321)), so with another UI language a signed-out start is a generic harness failure, not a sign-in one. The expired-subscription line is printed by the first model request, not the sign-in check; live check #2526 should confirm it reaches the first turn's output.

## The commands

The driver chooses the session id (`{"chosen": "uuid"}`): `qwen` takes a new session's id with `--session-id`, and refuses one that is not a UUID ([config.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/config.ts#L821-L838)).

- Start: `qwen --output-format stream-json --session-id <uuid> --model <model> --approval-mode <mode> <prompt>`
- Wake: `qwen --output-format stream-json --resume <uuid> --model <model> --approval-mode <mode> <prompt>`
- Prerequisite for start and wake: chat recording on. Wake reopens the session that start saved, and `qwen` saves it only while `general.chatRecording` is `true`, its default ([settingsSchema.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/settingsSchema.ts#L787-L795), [config.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/config.ts#L3076-L3077)). With it `false` in the user's, the project's or the system `settings.json`, start runs, but every wake exits 1 with `No saved session found with ID <uuid>...` ([config.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/config.ts#L2426-L2433)), so the builder can't reopen its session or edit the same status note. That is not a sign-in failure, and the row doesn't match it as one. The row respects the user's choice and never passes `--chat-recording`; to use this row, set `general.chatRecording` back to `true` (or delete the `false`) in whichever `settings.json` sets it, then start again. Live check #2526 should cover both: a wake with recording on, and this exit with it off.
- Stop: the driver's own stop, which ends the whole process tree.

`--session-id` and `--resume` can't be used together ([config.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/config.ts#L821-L823)), so wake passes only `--resume`, as [headless.md](https://github.com/QwenLM/qwen-code/blob/v0.28.4/docs/users/features/headless.md) shows (`qwen --resume <id> -p ...`). The prompt is the one positional argument, which runs one-shot ([config.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/config.ts#L972-L981)); the row doesn't use `-p`, which `--help` marks deprecated ("Use the positional prompt instead", [top-level-options.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/top-level-options.ts#L175-L176)). `--output-format stream-json` is one of `text`, `json` and `stream-json` ([top-level-options.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/top-level-options.ts#L359-L364)).

## The modes

`--approval-mode` takes exactly `plan`, `default`, `auto-edit`, `auto` and `yolo` ([top-level-options.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/top-level-options.ts#L28-L34), [approval-mode.md](https://github.com/QwenLM/qwen-code/blob/v0.28.4/docs/users/features/approval-mode.md)). Each is a mode here, adding `--approval-mode <mode>`. `--yolo` is not used: `qwen` refuses it with `--approval-mode` ([config.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/config.ts#L802-L804)).

The table says what each mode allows interactively, and what it does in this row's turns. The row runs `qwen` headless with text input (the default `--input-format`, [top-level-options.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/top-level-options.ts#L353-L358)) and stream-json output, so no one can answer an approval request: nothing answers it on stdin, and only stream-json input lets a host answer through the protocol ([approval-mode.md](https://github.com/QwenLM/qwen-code/blob/v0.28.4/docs/users/features/approval-mode.md#L133-L145)). So `qwen` removes, unless an explicit allow rule keeps it, the tools a headless turn could only ask about ([config.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/config.ts#L2188-L2233)):

| Mode | Edits | Shell commands | Headless here: removed unless allowed |
| --- | --- | --- | --- |
| `yolo` | auto-approved | auto-approved, with no sandbox | none: every tool stays and runs |
| `auto-edit` | auto-approved | need approval | `run_shell_command`, `monitor` |
| `auto` | a model classifier decides | a model classifier decides | `run_shell_command`, `monitor`, `edit`, `write_file` |
| `default` | need approval | need approval | `run_shell_command`, `monitor`, `edit`, `write_file` |
| `plan` | read-only | not run | `run_shell_command`, `monitor`, `edit`, `write_file` |

An explicit allow rule (`permissions.allow` in the user's or the project's `settings.json`) keeps a tool, and then the mode and the permission rules decide each call: in `auto`, the classifier can still approve ordinary edits in the clone ([approval-mode.md](https://github.com/QwenLM/qwen-code/blob/v0.28.4/docs/users/features/approval-mode.md#L133-L145)). A builder must edit files and run shell commands (its status note is a `gh` call), so in `auto-edit`, `auto`, `default` or `plan` it needs the owner's own allow rules for those tools, or it can't do the ticket. The row adds none: it passes no `--allowed-tools` and widens no approval. The owner picks the mode and writes any allow rule.

**Trust.** With `security.folderTrust.enabled` on and the clone's folder not trusted, `qwen` downgrades `yolo`, `auto-edit` and `auto` to `default` and prints `Approval mode overridden to "default" because the current folder is not trusted.` ([config.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/config.ts#L1999-L2024)). Folder trust is off by default, which treats every folder as trusted. With it on, the owner trusts the folder the driver clones into (or a parent of it) before approving one of those three modes; otherwise every turn runs as `default`.

## The census check, resolved

**A plain run never starts `qwen serve`.** `serve` runs only as its own subcommand, `qwen serve` (listed in [cli.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/cli.ts#L82-L85)), or from `qwen daemon start` (`handleStart`), the only caller of `buildDaemonStartArgs`, which puts `serve` on the child's command line ([daemon.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/commands/daemon.ts#L607-L617), [daemon.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/commands/daemon.ts#L856-L871)). The row's start and wake name no subcommand, and the fake refuses `serve`. The detached self-update a session may start is only in the interactive UI's post-render prefetch ([startup-prefetch.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/startup/startup-prefetch.ts#L149-L163), called from [startInteractiveUI.tsx](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/ui/startInteractiveUI.tsx#L364)), never in a headless run.

**But a headless turn can leave a detached hook supervisor, so `daemon` names it.** When the user has a `StopFailure` hook configured and the model hits loop detection, the turn fires that hook without waiting ([client.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/core/src/core/client.ts#L1382-L1395)). A `StopFailure` hook runs under a supervisor that `qwen` spawns `detached` (its own session and process group), with stdin, stdout and stderr ignored, a private status pipe on fd 3, and `unref()`, so it outlives the turn ([hookRunner.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/core/src/hooks/hookRunner.ts#L1232-L1276)). On Linux the turn's supervisor is a subreaper, so the orphan stays in the tree and the driver's stop ends it. On macOS, a supervisor orphaned before the driver's next scan has left the turn's ancestry, process group and output file, and stop can miss it: that is the row contract's macOS limit, so the row holds on Linux only. The fake starts this supervisor in the same shape on every first turn (`setsid`, fds 0 to 2 on `/dev/null`, a status pipe on fd 3), `test_row.py` checks that shape, and the runner checks stop ends it. #2526 must exercise it: a live stop on Linux with a long `StopFailure` hook that has fired, and the same on macOS before macOS is claimed.

**The rest stays in the turn.** The tools a turn runs (monitors included, which `qwen` starts in their own process group, [llm.tsx](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/llm.tsx#L276-L278)) are processes of the turn, and the driver's stop ends them with its tree. So is the sleep inhibitor `qwen` holds while a turn streams or runs tools (`caffeinate` on macOS, `systemd-inhibit` on Linux where available): it is spawned not detached, with its output ignored, and stays in the turn's process group ([sleepInhibitor.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/core/src/services/sleepInhibitor.ts#L179-L195)).

**The approval-mode values** are the five above.

**Effort: none.** `qwen` 0.28.4 has no effort flag and no effort variable: the CLI's options list none ([top-level-options.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/top-level-options.ts)). Its one effort setting is `model.reasoningEffort` in `settings.json` (`low`, `medium`, `high`, `xhigh`, `max`, set with `/effort`), and "each provider maps and clamps this to what the active model supports (e.g. Gemini caps at \"high\")" ([settingsSchema.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/config/settingsSchema.ts#L1887-L1907), [modelConfigUtils.ts](https://github.com/QwenLM/qwen-code/blob/v0.28.4/packages/cli/src/utils/modelConfigUtils.ts#L462-L491)). The driver can't write the user's settings, and a value some models silently clamp is one the contract says a row must not claim. So `row.json` says `none`, and a start with an effort is refused, never run at a default.

## What the fake allows

`fake` takes only the row's start and wake lines above, with one of the five modes and a UUID session, and exits 2 on anything else. `test_row.py` labels its refusals by kind:

- **Not qwen's grammar:** an unknown mode, `--yolo` with `--approval-mode`, `--session-id` with `--resume`, a non-UUID id and an effort flag. `qwen` 0.28.4 refuses or lacks each.
- **Valid `qwen`, outside this row:** `-p` (deprecated but documented), no prompt, two prompts, text output, no `--model`, `serve` and `auth`. `qwen` takes these; the row never sends them, so the fake refuses them to catch a row that drifts.
- **A fixture rule:** a `--resume` prompt must start `You were woken` and a `--session-id` prompt must not. That is how the fake tells the driver's wake from its start, not `qwen`'s grammar.

It also checks that each documented line is taken, that each sign-in refusal above matches `signed_out`, that a wake with chat recording off is `qwen`'s missing-session exit and not a sign-in failure, the hook supervisor's detached shape, the modes and the README's headless table.

## Evidence

- `evidence/red.txt`: the runner on an empty row (`{}`), failing.
- `evidence/green.txt`: the runner on this row, passing.
- `evidence/round-1/`: review round 1, each finding's red run, committed before its fix, and its green run: `r1-*` (the sign-in refusals), `r2-*` (the hook supervisor), `r3-*` (chat recording) and `r4-*` (headless modes).
