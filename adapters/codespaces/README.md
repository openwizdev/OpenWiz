# GitHub Codespaces driver
Login: held by GitHub

Effort: the host can't set it (the driver doesn't take driver v1's optional `effort` field, so every run uses the harness's default effort, and a `start` that names an effort is refused and creates nothing)

**Status:** not built yet. At main this folder holds only this README, with no `driver`, `test_driver.py` or `fixtures/`, so the commands below don't run yet.

A [driver v1](../../kernel/driver.v1.md) that runs each builder in its own [GitHub Codespaces](https://docs.github.com/en/codespaces) codespace, on your own GitHub account, through your own signed-in `gh` CLI. One Python file, standard library only. **Platforms:** Linux and macOS, Python 3.9 or later. Runs are saved in `$OPENWIZ_CODESPACES_STATE` (default `~/.local/state/openwiz-codespaces`), owner-only. A run's id is the driver's own: `cs-` and a random hex id.

| Command | What it does in Codespaces |
| --- | --- |
| `start` | First the pre-checks, before anything is created: `gh auth status` must show the `codespace` scope, and `gh api /user/codespaces/secrets` must list one of the harness's secret names (below), with `repository` in that secret's repository list (`/user/codespaces/secrets/<NAME>/repositories`). Only secret names and repository lists are read, never a value. If either check fails, `start` refuses with one line naming the fix, and creates nothing. Then `gh codespace create -R <repository> --default-permissions --display-name openwiz-<ticket> --idle-timeout 240m --retention-period 72h`, with `-m "$OPENWIZ_CODESPACES_MACHINE"` when that is set; the codespace name it prints is saved with the run. One `gh codespace ssh -c <name> -- <command>` installs the WizSkills release OpenWiz pins (`wizskills.lock`) in the codespace, the way the boat driver installs the pinned release, and leaves the run's mark in the codespace's home folder (`~/.openwiz/runs/<run>`). The same command installs the harness with `npm install -g` (`@anthropic-ai/claude-code` or `@openai/codex`, unpinned), but only when the codespace doesn't have it already. Then the first turn: a local `gh codespace ssh -c <name> -- <harness command>`, which first goes to `/workspaces/<repository's name>` when the codespace has that folder. For `claude` the command is `claude -p --dangerously-skip-permissions --model <model> --session-id <uuid>`. For `codex` it is `codex exec --json --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check -m <model>`, and the thread id it prints is saved. A headless turn can't answer a permission prompt, and the codespace is the run's own sandbox, so the turn runs without them. If any step after the create fails, `start` stops the new codespace before it refuses. |
| `wake` | Refused after a driver `stop`, and for an unknown run (driver v1, D5). While the last turn still runs, nothing: that agent is awake and reads the ticket itself. Otherwise one `gh codespace ssh` checks the run's mark in the codespace's home folder. That ssh also starts a codespace GitHub stopped for idleness, and the home folder (with the mark, `~/.claude` and `~/.codex`) survives a stop. Then a new local `gh codespace ssh` turn with `claude -p --resume <uuid>` or `codex exec resume <id>` (same flags as the first turn): the same agent, with its memory. A rebuild of the codespace loses its home folder, and with it the harness's session: the wake then refuses with one line, and the run needs a new `start`. |
| `stop` | Marks the run as stopping and saves it, ends every local process the turns started, then runs `gh codespace stop -c <name>`, so the codespace stops billing compute. If that command fails, the stop still passes when `gh codespace list` shows the codespace stopped or gone. Stopping a run that is already stopped answers again (driver v1, D6). The stopped codespace's disk stays until GitHub deletes it, 72 hours after it stopped (the retention period); `gh codespace delete -c <name>` deletes it sooner. |

GitHub stops a codespace after 240 minutes without activity (the idle timeout set at `start`). Each turn is a local `gh codespace ssh` under the driver's own supervisor, so the driver answers at once and `stop` reaches every process the turn started. Locking, saving a run before starting anything for it, and the supervisor follow the [boat driver](../boat/README.md): a wake and a stop take turns, and no run is left with two agents or with one left running.

**No key in, no diagnostic out.** The driver never reads, passes or prints a key (driver v1, N1 to N3). The harness's login reaches the codespace as a Codespaces user secret that GitHub puts in the codespace's environment, where the harness reads it. No command the driver sends into the codespace names that secret, or uses `env`, `printenv`, `export`, `declare` or a bare `set`. A failed `gh` command answers fixed words that name the failure and its fix; `gh`'s own text never reaches the driver's answer.

`version` adds `many-at-once` and `own-sandbox` to `can`: every run gets its own codespace.

## Before the first run (yours to do)

1. Install the [`gh` CLI](https://cli.github.com) and sign in to it yourself (`gh auth login`).
2. Give `gh` the `codespace` scope: `gh auth refresh -h github.com -s codespace`. `start` checks it.
3. **Set the harness's login as a Codespaces secret, by name,** for each repository you build. You type the value into `gh` yourself, at its prompt:
   - for `claude`: `gh secret set CLAUDE_CODE_OAUTH_TOKEN --user --repos <owner/name>` (or `ANTHROPIC_API_KEY` in its place, for an API key);
   - for `codex`: `gh secret set CODEX_API_KEY --user --repos <owner/name>`.

   `--user` makes it a Codespaces secret of your own account, and `--repos` is the list of repositories whose codespaces get it: name every repository you build, comma-separated (`--repos owner/one,owner/two`). Leave out `--body`, so the value is typed at the prompt and never lands in your shell's history. The driver reads only the secret's name and its repository list, never its value.

   **Taking the login back.** Deleting the secret (`gh secret delete <NAME> --user`) stops GitHub from giving it to codespaces from then on. It can't take it back from a codespace that already has it: GitHub puts the secret into that codespace's environment, so the agent running there may still hold the login. To cut off access, `stop` every run that uses it, and revoke or rotate the login where it was issued: with Anthropic for `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`, with OpenAI for `CODEX_API_KEY`.

`harness` is `claude` or `codex`, the two whose secrets are named above; `start` refuses any other harness before it creates anything.

**Machine:** `$OPENWIZ_CODESPACES_MACHINE` is passed to `gh codespace create -m` unchanged. It must be a plain machine name, such as `basicLinux32gb`; `start` refuses anything else before it creates a codespace. When it is unset, no `-m` is passed. `gh api /repos/<owner/name>/codespaces/machines` lists the machine types a repository can use.

**Costs:** Codespaces bills compute, while a codespace runs, and storage, while it exists (stopped included), to your own GitHub account, or takes them from its monthly free quota. `stop` ends the compute; the storage lasts until the codespace is deleted, by the 72-hour retention period or by `gh codespace delete -c <name>`.

**Effort:** runs use the harness's default effort, because the driver doesn't take driver v1's optional `effort` field. A `start` that names an effort is refused, so an effort is never dropped silently. The refusal creates nothing, and its `next` is: `this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default`. Each prompt tells the agent to write its status note's model as `<model> default effort`. This line follows the driver: when the driver takes an effort, the `Effort:` line above names the flag.

**Not yet checked live:** whether the codespace's own `GITHUB_TOKEN` lets the agent post its status note and push its branch, and whether an open `gh codespace ssh` turn keeps the codespace from idling out. The live check answers both.

## The kit

```sh
python3 -I kernel/driver-kit/kit.py --driver adapters/codespaces/driver \
  --repo <owner>/<throwaway> --ticket <n> --harness claude --model <model>
python3 -I adapters/codespaces/test_driver.py      # the fixture tests, on a synthetic gh CLI
```

The kit run creates a real codespace on your account, which costs money; `gh codespace delete -c <name>` it afterwards. `fixtures/bin/gh` is a synthetic `gh` CLI (`auth status`, `api /user/codespaces/secrets`, `codespace create`, `ssh`, `stop` and `list`), whose `ssh` runs a synthetic harness locally.
