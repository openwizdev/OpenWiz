# Always-on driver live checks

`run.py` runs one driver's real live check on a schedule, on an always-on box, and posts a receipt on a tracking issue ([#3355](https://github.com/openwizdev/OpenWiz/issues/3355)). Each run uses a fresh clone of `main` and does the same four things:

1. Runs the driver's offline tests: `python3 -I adapters/<driver>/test_driver.py`.
2. Installs the WizSkills release pinned in `wizskills.lock` in its own folder, and links its skills into the harness's user skills folder (`~/.claude/skills`, or `~/.codex/skills` for Codex). It never replaces an entry it didn't make.
3. Runs the [driver kit](../../../kernel/driver-kit/README.md) on the live test ticket: `python3 -I kernel/driver-kit/kit.py --driver adapters/<driver>/driver --repo <repo> --ticket <n> --harness <h> --model <m>`.
4. Cleans up and posts. It stops any driver run left going, deletes the run's work folders, and marks the run's builder note `stopped (live check ended)` (through launch-fleet's `status.py`). It closes any new pull request titled `#<n>:` and deletes any new branch named `<n>-…` or `…/<n>-…`, the shapes build-ticket uses. It reports any other branch that appeared and leaves it alone. Then it posts one receipt. The receipt holds the commit, harness and model, the offline tests, the five checks with pass or fail and their timings, the kit's exact failure lines, and what it cleaned up. A receipt is posted only when the result changes or 24 hours have passed since the last one, and only after `tools/privacy-check/check.py` passes it.

It never merges, tags, releases or publishes, and it reads no key. The harness uses the sign-ins already on the box, and `gh` uses the box's login. Python 3.9 or later, standard library only. State is kept in `~/.local/share/openwiz-live/<driver>/`, owner-only: `posted.json`, `last.json`, `runs.jsonl` (one line per run), `receipts/` and `cron.log`.

## The test ticket

The test ticket is one open issue in the demo repository, titled `Live check: <driver> driver`, and it is reused for every run. build-ticket claims a ticket (and so posts the note the kit waits for) only when `ticket.py read` prints `ready: yes`. So the ticket has:

- the `ready-for-agent` label;
- an `## Owned paths` bullet, here a file no other ticket owns;
- a record author's `launch-fleet: started` comment, posted by hand: no fleet runs this ticket;
- a body telling the builder there is nothing to build. On a start it writes its note `working`, and on a wake it edits that note. It makes no branch, commit or pull request.

The openclaw check uses [openwizdev/todo-demo#16](https://github.com/openwizdev/todo-demo/issues/16). If an earlier note was left `asking`, `run.py` takes `needs-info` off the ticket before the next run. Each run leaves one stopped builder note there, and the kit reads every comment each time it polls. Once the ticket gets long, close it, open a new one set up the same way, and change `--ticket` in the cron line.

## Set up a box (openclaw)

1. Install `acpx` at the version the driver's evidence names, `npm install -g acpx@0.22.0`. Then sign in to the harness yourself: `claude` (or `codex`), and `gh`. The driver itself needs nothing else. It uses acpx, never the OpenClaw gateway.
2. Copy `run.py` to `~/.local/share/openwiz-live/run.py`, so the schedule doesn't depend on a checkout.
3. Run it once by hand with `--no-post`, read the receipt in `receipts/`, then post it with `--post-last`.
4. Add the schedule with `crontab -e`. This line runs it every 6 hours. On Boat, the box's sign-ins live in `/run/ascii-secrets/env.sh`, which cron doesn't load, so the line loads it first. It reads that file at run time and copies nothing from it.

```sh
17 */6 * * * . /run/ascii-secrets/env.sh 2>/dev/null; PATH=/usr/local/bin:/usr/bin:/bin; export PATH; /usr/bin/python3 -I "$HOME/.local/share/openwiz-live/run.py" --driver openclaw --repo openwizdev/todo-demo --ticket 16 --harness claude --model claude-opus-5-5 --receipts openwizdev/OpenWiz#3355 >> "$HOME/.local/share/openwiz-live/openclaw/cron.log" 2>&1
```

A run holds a lock, so a slow run is never doubled. It exits 0 only on 5 of 5 pass. If no sign-in reaches it, or the ticket is closed or has lost its label, the receipt says `blocked:` and names what to fix.

## Options

`--driver` (default `openclaw`; any `adapters/<driver>` with a `test_driver.py`), `--repo`, `--ticket`, `--harness`, `--model`, `--skill` (default `build-ticket`), `--wait` (the kit's seconds per step, default 900), `--receipts owner/repo#N`, `--every` (the hours the receipt names, default 6), `--root` (default `~/.local/share/openwiz-live`), `--no-post`, `--post-last`. For a driver other than openclaw, `run.py` keeps that driver's own state where the driver says, and can't clear its work folders. Add the driver's state variable to `DRIVER_STATE` first.
