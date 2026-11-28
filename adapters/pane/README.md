# Pane driver

Login: stays on your machine
Effort: passed as harness options via `runpane panes create --tool-command`.

| Harness | Effort setting |
| --- | --- |
| `claude` | `--effort <level>` for low, medium, high, and max. The terminal command also sets `CLAUDE_CODE_EFFORT_LEVEL` to the same value. Some models take `xhigh` as listed below. |
| `codex` | `-c model_reasoning_effort=<level>` for low, medium, high, and xhigh. Some models take `max` or `ultra` as listed below. |
| `cursor` | can't (Cursor selects reasoning through model variants) |
| `opencode` | can't (OpenCode's variants are defined per model and can map to different settings) |
| `pi` | can't (Pi can clamp the requested level to the model's capabilities) |

The driver accepts effort for these explicit model IDs. Claude Code or Codex may apply managed settings on the machine running the tab.

- Claude Code accepts the table's levels for `claude-opus-4-6` and `claude-sonnet-4-6`. These models also accept `xhigh`: `claude-opus-4-7`, `claude-opus-4-8`, `claude-opus-5`, `claude-opus-5-5`, `claude-sonnet-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-fable-5`, `claude-fable-5-1`, and `claude-fable-5-2`.
- Codex accepts the table's levels for `gpt-5.5`. It also accepts `max` for `gpt-5.6-luna` and `gpt-6-luna`, and both `max` and `ultra` for `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-6-sol`, `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6.1-terra`, `gpt-6.2-sol`, and `gpt-6.2-astra`.

A [driver v1](../../kernel/driver.v1.md) that runs each builder in its own Pane, through your own `runpane` CLI and the [Pane](https://runpane.com) app on your computer. A Pane is a git worktree on its own branch, with tabs; each run is one Pane with one agent tab. One Python file, standard library only. **Platforms:** Linux and macOS, Python 3.9 or later, wherever Pane runs; its fixture tests run on Linux (they check their own fake agents through `/proc`). Runs are saved in `$OPENWIZ_PANE_STATE` (default `~/.local/state/openwiz-pane`), owner-only.

**Pane's desktop app, or its daemon (`runpane install daemon`), must be running for `start`, `wake` and `stop`.** The `runpane` CLI talks to it, and it runs the agents. Without it, those commands refuse and say to open the Pane app. `version` and `schema` need nothing.

| Command | What it does in Pane |
| --- | --- |
| `start` | Finds the one checkout saved in Pane (`runpane repos list`) whose `origin` remote is exactly that GitHub repository: every fetch and push URL, as your own `git remote get-url --all [--push] origin` resolves them (includes, `insteadOf` and `pushurl` applied, nothing contacted; git gets only `PATH`, `HOME`, `XDG_CONFIG_HOME`, `LANG` and `LC_ALL` from your environment, never a token or key). A fork of another owner, or a checkout whose URLs disagree, never matches. Then `runpane panes create --repo <its id> --name openwiz-<run> --agent <harness> --tool-command "<program> --model <model>" --prompt <the ticket and skill> --source agent --wait-ready`. It answers once Pane has seen the agent's input box and delivered the prompt. When Pane queues setup (`setupQueue` with a Pane id and no tab yet), the driver saves the Pane id, polls `runpane panels list --pane <id>` for the agent tab, and waits on `runpane panels wait --panel <id> --for ready`. If the agent never gets ready or a queued Pane times out before opening a tab, it closes any opened tab and archives the Pane before refusing (also when Pane answers that failure with `ok: false`); if cleanup cannot be confirmed, the run stays unstopped with its saved Pane id so `stop` can finish cleaning it up. If `panes create` does not answer in time, the run is not marked stopped: its outcome is unknown, and the error names the run to stop. |
| `wake` | `runpane panels submit --panel <the run's tab>`: the same agent, in the same tab, reads its ticket again and edits its own status note. A stopped run, or one whose start never finished, is never woken. |
| `stop` | For a run whose `panes create` never answered or stayed queued without a tab, `runpane panes list` checks whether Pane `openwiz-<run>` (or the saved Pane id) is still active and `runpane panels list` looks for its one agent tab. If that Pane is already absent or archived, nothing is running; if it is still queued with no agent tab yet, `stop` answers `stopped` only once `runpane panes archive --remove-worktree` succeeds, and otherwise refuses while keeping the run recoverable. If the lookup cannot tell, stop refuses and the run stays recoverable: it does not answer `stopped`. Otherwise `runpane panels close --force` closes the tab, which ends its agent even mid-turn. Then `runpane panes archive --remove-worktree` removes the Pane and its worktree; Pane keeps the local branch. The driver never forces an archive. When Pane refuses it, for example because the worktree holds work not yet committed or pushed, the driver keeps the Pane `openwiz-<run>` and its worktree on disk and still answers `stopped`: the agent has ended. Push or discard that work; a later stop of the same run tries the archive again, and also answers `stopped`. A tab Pane could not close also makes stop answer an error. |

`version` adds `many-at-once` and `effort` to `can`. Pane runs many Panes side by side. For a start with effort, the driver adds the setting from the table to the terminal command. It refuses an unlisted harness, model, or level before contacting Pane or saving a run. A start without effort uses the harness default.

Each `runpane` call waits up to 100 seconds, or `OPENWIZ_PANE_RUNPANE_SECONDS` when that is a whole number from 1 to 100. A call that does not answer has an unknown outcome, and the driver does not call that run stopped.

The tab is opened with `--source agent`, because Pane lets an agent close only a tab an agent opened.

## Before the first run (yours to do)

The driver never touches a login (driver v1, N1 to N3). It calls `runpane` with your environment unchanged, gives `git` only its five non-secret settings, and passes no key, token or password anywhere. Your agents sign in on this machine, as they do in Pane itself.

1. Install Pane and its `runpane` CLI, and open the app (or run `runpane install daemon`).
2. Save your checkout of the repository in Pane: `runpane repos add --path <checkout>`. Its `origin` remote must be the GitHub repository (`https://github.com/<owner>/<name>` or `git@github.com:<owner>/<name>`). A start refuses when no saved checkout, or more than one, has that origin.
3. Sign in, yourself, to each agent you use, and to `gh`, so the agent can post its status note.
4. `harness` is one of Pane's agents: `claude`, `codex`, `cursor` (it runs `cursor-agent`), `opencode` or `pi`. `model` goes to that program's `--model` flag, quoted. Pane's docs give a terminal agent its model this way. A field holding a login, token or key shape (every shape the driver kit knows, and Google API keys, anywhere in the field) is refused before anything starts, and never echoed.

The driver adds no permission flag. Each agent runs with your own settings for it, and Pane shows you any permission prompt it asks.

Pane is licensed AGPL-3.0. This driver only runs the `runpane` program you installed, as a separate program; it copies none of Pane's code.

## The kit

The fixture tests run only on the synthetic `runpane`, with nothing real on their PATH, and cost nothing:

```sh
python3 -I adapters/pane/test_driver.py
```

**Live check only.** The kit command below starts a real agent in your real Pane, on your real agent account. Each run is one start and one wake of that agent, so it uses that agent's paid model usage or subscription allowance. It also creates and then archives a Pane and its worktree in the repository you name. Run it only for the live check, by hand, on a throwaway repository and ticket:

```sh
python3 -I kernel/driver-kit/kit.py --driver adapters/pane/driver \
  --repo <owner>/<throwaway> --ticket <n> --harness claude --model <model>
```

`fixtures/bin/runpane` is a synthetic `runpane` CLI, written for these tests. Its JSON answers follow the shapes `runpane help` and its published JSON schemas name (runpane 2.4.246). No answer in it was observed on a live Pane; the live check on the real host is the proof.

It plays Pane and its agents. It keeps its Panes in the JSON file `FAKE_PANE_STATE`. `panes create` starts a synthetic agent process with the tool command's arguments and records the parsed effort in the panel state. The process inherits the caller's environment and ends when its tab closes. When the prompt names a skill, the fake posts one builder status note in the kit's local tracker (`KIT_TRACKER`). Each `panels submit` edits that note. It takes only the flags the driver passes and exits 2 on any other. Its failure texts carry the word `synthetic`, so a test can show that the driver's errors keep only Pane's error code and its own fixed text. Its settings:

| Variable | What it plants |
| --- | --- |
| `FAKE_PANE_REPOS` | Comma-separated `owner/name` checkouts Pane has saved, each saved under its name with that GitHub repository as its `origin` (default `example/site`) |
| `FAKE_PANE_DOWN` | Set: the Pane app and its daemon are not running, so every command fails |
| `FAKE_PANE_READY` | `no`: the tab's command exits before its agent's input box is ready |
| `FAKE_PANE_DIRTY` | `uncommitted` or `unpushed`: what archive's safety check finds in the worktree |
| `FAKE_PANE_CALLS` | A file each call's arguments are appended to, one JSON array per line |
| `FAKE_PANE_HANG` | `create`: the Pane and its agent are saved, then `panes create` never answers. `before-create`: `panes create` never answers and saves nothing. `list`: `panes list` never answers. `wait`: `panels wait` never answers |
| `FAKE_PANE_HOST` | Hostname used for synthetic checkout `origin` URLs (default `github.com`) |
| `FAKE_PANE_QUEUE` | Non-negative integer `N` (queued Pane opens its tab after `N` `panels list` polls) or `never` (stays queued until `FAKE_PANE_QUEUE_FINISH` is set) |
| `FAKE_PANE_QUEUE_LOCK` | Set: archiving a queued Pane is refused with `setup-in-progress` |
| `FAKE_PANE_QUEUE_FINISH` | Set: `panels list` finishes a queued Pane's setup and opens its agent tab |
