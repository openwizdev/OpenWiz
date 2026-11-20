Login: stays on your machine

# Pane driver

A [driver v1](../../kernel/driver.v1.md) that runs each builder in its own Pane, through your own `runpane` CLI and the [Pane](https://runpane.com) app on your computer. A Pane is a git worktree on its own branch, with tabs; each run is one Pane with one agent tab. One Python file, standard library only. Runs are saved in `$OPENWIZ_PANE_STATE` (default `~/.local/state/openwiz-pane`), owner-only.

**Pane's desktop app, or its daemon (`runpane install daemon`), must be running.** The `runpane` CLI talks to it, and it runs the agents. Without it, every command refuses with Pane's own next step.

| Command | What it does in Pane |
| --- | --- |
| `start` | Finds the repository you saved in Pane under the GitHub repository's name (`runpane repos list`). Then `runpane panes create --repo <its id> --name openwiz-<run> --agent <harness> --tool-command "<program> --model <model>" --prompt <the ticket and skill> --source agent --wait-ready`. It answers once Pane has seen the agent's input box and delivered the prompt. If the agent never gets ready, it closes the tab and archives the new Pane before refusing. |
| `wake` | `runpane panels submit --panel <the run's tab>`: the same agent, in the same tab, reads its ticket again and edits its own status note. A stopped run is never woken. |
| `stop` | `runpane panels close --force` closes the tab, which ends its agent even mid-turn. Then `runpane panes archive --remove-worktree` removes the Pane and its worktree. Pane always keeps the local branch. When Pane only reports commits not yet pushed, the driver archives anyway (`--force`), because those commits stay on that branch. When the worktree holds uncommitted work, the driver never forces it away. The run stays stopped, and the error names the worktree. Commit or discard that work, then stop again to archive it. |

`version` adds `many-at-once` to `can`: Pane runs many Panes side by side.

The tab is opened with `--source agent`, because Pane lets an agent close only a tab an agent opened.

## Before the first run (yours to do)

The driver never touches a login (driver v1, N1 to N3). It calls `runpane` with your environment unchanged, and passes no key, token or password anywhere. Your agents sign in on this machine, as they do in Pane itself.

1. Install Pane and its `runpane` CLI, and open the app (or run `runpane install daemon`).
2. Save your checkout of the repository in Pane under the GitHub repository's name: `runpane repos add --path <checkout> --name <name>`. A start refuses when no saved repository, or more than one, has that name.
3. Sign in, yourself, to each agent you use, and to `gh`, so the agent can post its status note.
4. `harness` is one of Pane's agents: `claude`, `codex`, `cursor` (it runs `cursor-agent`), `opencode` or `pi`. `model` goes to that program's `--model` flag, quoted. Pane's docs give a terminal agent its model this way.

The driver adds no permission flag. Each agent runs with your own settings for it, and Pane shows you any permission prompt it asks.

Pane is licensed AGPL-3.0. This driver only runs the `runpane` program you installed, as a separate program; it copies none of Pane's code.

## The kit

```sh
python3 -I kernel/driver-kit/kit.py --driver adapters/pane/driver \
  --repo <owner>/<throwaway> --ticket <n> --harness claude --model <model>
python3 -I adapters/pane/test_driver.py      # the fixture tests, on a synthetic runpane CLI
```

`fixtures/bin/runpane` is a synthetic `runpane` CLI, written for these tests. Its JSON answers follow the shapes `runpane help` and its published JSON schemas name (runpane 2.4.246). No answer in it was observed on a live Pane; the live check on the real host is the proof.

It plays Pane and its agents. It keeps its Panes in the JSON file `FAKE_PANE_STATE`. `panes create` starts the tab's agent, a `sleep` that inherits the caller's environment and ends when its tab closes, and, when the prompt names a skill, posts one builder status note in the kit's local tracker (`KIT_TRACKER`); each `panels submit` edits that note. It takes only the flags the driver passes and exits 2 on any other. Its settings:

| Variable | What it plants |
| --- | --- |
| `FAKE_PANE_REPOS` | Comma-separated saved repository names (default `site`) |
| `FAKE_PANE_FAIL` | Comma-separated commands that fail: `create`, `submit`, `close`, `archive`, `repos` |
| `FAKE_PANE_DOWN` | Set: the Pane app and its daemon are not running, so every command fails |
| `FAKE_PANE_READY` | `no`: the tab's command exits before its agent's input box is ready |
| `FAKE_PANE_DIRTY` | `uncommitted` or `unpushed`: what archive's safety check finds in the worktree |
| `FAKE_PANE_CALLS` | A file each call's arguments are appended to, one JSON array per line |
