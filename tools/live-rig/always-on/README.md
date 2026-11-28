# Always-on live checks (#3355)

`live_check.py` runs one driver's real live check on an always-on Boat box, on a schedule, so a driver gets a live test without a person running it. Each run moves a dedicated checkout to `main`, runs the driver's offline tests, then the [driver kit](../../../kernel/driver-kit/README.md) against a throwaway ticket. It closes any pull request and deletes any branch that run opened for that ticket, then posts one receipt comment on #3355, but only when the result changed or a day has passed. Standard-library Python 3.9 or later, plus `git` and a signed-in `gh`. It writes nothing but that comment and the cleanup. It never merges, tags, releases or publishes.

```sh
python3 -I tools/live-rig/always-on/live_check.py --config <box.json> [--dry-run] [--force] [--note <file.md>]
python3 -I tools/live-rig/always-on/test_live_check.py    # its own tests: a fake kit, checkout and gh, nothing live
```

`--dry-run` runs everything and prints the receipt, but posts, closes and deletes nothing. `--force` posts even when nothing changed. `--note` adds a Markdown file at the end of that run's receipt, for a finding checked by hand. Exit 0: the offline tests and all five checks pass. 1: something failed. 2: the rig itself could not run, or its receipt was not posted.

## The box config

One JSON object. The first seven keys are required:

```json
{
  "driver": "hermes",
  "checkout": "~/.local/share/openwiz-live-rig/OpenWiz",
  "repo": "openwizdev/todo-demo",
  "ticket": 17,
  "harness": "hermes",
  "model": "gpt-6.2-sol",
  "receipts": "openwizdev/OpenWiz#3355",
  "tools": ["hermes", "codex"],
  "about": "Hermes set to `model.openai_runtime: codex_app_server`, so each turn runs in `codex app-server` on the Codex CLI's own ChatGPT login; no provider key"
}
```

`tools` are the CLIs whose `--version` each receipt records (default: the driver's name). `about` is one line on how the host is set up. Optional: `skill` (default `build-ticket`), `wait` (the kit's `--wait`, default 900), `kit_timeout` (default 3600 seconds, then the kit gets SIGINT, so it stops its run, and 60 seconds later SIGKILL) and `state` (default `~/.local/state/openwiz-live-rig/<driver>`).

## Setting up a box

1. Set up the host CLI so it runs under the driver's environment, which keeps only `HOME`, `PATH` and the like and never a token. Check with `env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin <cli> ...` before anything else. Never store a key for it: use a login the CLI keeps itself. Hermes on the #3355 box: `hermes config set model.provider openai`, `hermes config set model.default gpt-6.2-sol`, `hermes config set model.openai_runtime codex_app_server`. Each turn then runs in `codex app-server` on the Codex CLI's own login (`codex login status`).
2. Make one throwaway ticket on the demo repository, titled `Live check: <driver> driver`. Its body asks the builder only for its status note and says there is no code to change. Every run reuses it.
3. Clone a dedicated checkout. Each run moves it to `main` and refuses one with local changes. Install the runner beside it, outside the checkout, so a run never replaces the script it is running, and write the config:

   ```sh
   git clone https://github.com/openwizdev/OpenWiz.git ~/.local/share/openwiz-live-rig/OpenWiz
   install -m 0755 tools/live-rig/always-on/live_check.py ~/.local/share/openwiz-live-rig/live_check.py
   ```

4. Run it once by hand with `--dry-run` under the same bare environment cron gives. Then run it without `--dry-run`, which posts the first receipt and records it.
5. Add the user crontab entry. cron runs with no tokens in its environment, so `gh`, `git` and the host CLI use their own signed-in configuration:

   ```text
   PATH=/usr/local/bin:/usr/bin:/bin
   LANG=C.UTF-8
   17 */6 * * * /usr/bin/python3 -I "$HOME/.local/share/openwiz-live-rig/live_check.py" --config "$HOME/.config/openwiz-live-rig/hermes.json" >> "$HOME/.local/state/openwiz-live-rig/hermes/cron.log" 2>&1
   ```

## What a run keeps and posts

- **The receipt:** the driver's last commit and `main`, harness and model, the host CLI versions, the offline tests, each of the kit's five checks with pass or fail, its time and its offset from the kit's start, and every failing line exactly as the kit printed it. It ends with the cleanup and why it was posted. A run that could not get as far as the kit posts what stopped it. Before posting, the receipt goes through `tools/privacy-check/check.py`, and the home folder is shown as `~`. A refused receipt is not posted, and the next run tries again.
- **When:** the first run, then whenever the result changes, else the first run 23 hours or more after the last receipt, so about once a day. The result is the offline verdict, the kit's exit, and each check's verdict with its failure text, after run ids, note numbers and process ids are taken out.
- **Cleanup:** branches and open pull requests on the demo repository that the run opened: new since the run began, and naming the ticket's number in the branch or citing the ticket. Anything older, or about another ticket, is left alone. The agent's status notes stay on the ticket. The kit only counts the new one.
- **On the box:** `state.json` (the last receipt's result and link), `history.jsonl` (one line per run), `last-receipt.md`, and `cron.log`. A run that finds another still holding the lock does nothing.

## Limits

The rig runs whatever `main` holds, on a real model, about four times a day, so each run spends a little of the box's model login. The kit and the host CLI decide what one run costs. It sees only what the kit sees: processes on this machine, and the ticket's comments.
