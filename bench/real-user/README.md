# The real-user journey bench

One command takes a fresh user's road from an empty public repository to the first merged fleet pull request, then checks every app page against GitHub. Standard library Python 3.9 or later, `gh` signed in with the `repo` and `delete_repo` scopes, a coding agent, and a WizSite checkout for its page checker (`scripts/live-check.mjs`, from openwizdev/OpenWiz#3145) with its dependencies installed.

```sh
python3 -I bench/real-user/journey.py --agent 'claude -p --dangerously-skip-permissions' --wizsite ../WizSite
```

## What it does

1. **Creates** a throwaway public repository, `<you>/openwiz-bench-<UTC time>`, with a README (`--owner` picks another account).
2. **Starts the clock and hands the agent the public install line,** `Install OpenWiz from github.com/openwizdev/OpenWiz`, in a fresh clone, asking it to onboard the repository to a first small fleet with default answers. The prompt is the agent command's last argument.
3. **Stops the clock** at GitHub's `mergedAt` of the first merged pull request that closes one of this repository's issues; the setup pull request closes none, so it never counts. It checks every `--poll` seconds (60) for up to `--timeout` seconds (4 hours) from the start.
4. **Runs the page checker** on the repository against openwiz.dev/app (`--prod`), handing it the `gh` token only through its environment.
5. **Removes the repository:** deletes it, or archives it when the delete is refused. This runs even when an earlier step failed.
6. **Writes the row** `| Real-user | Before | Now | Pages | Run |` into `docs/bench.md` (`--bench-file`): Before is the previous row's Now, Now is the time (minutes:seconds) or `no merge`. It replaces only that row.

It prints the repository, the time to the first merged PR, each page's PASS or FAIL line, how the repository was removed and the row. Exit 0 means a fleet pull request merged, every page agreed and the repository is gone; 1 means one of those did not happen (the output says which); 2 is a bad fixture.

## Dry runs and tests

`--dry-run DIR` answers every command from `DIR/calls.json` on a virtual clock and logs each command it ran to `DIR/ran.jsonl`; nothing touches GitHub. The fixtures in `fixtures/` are synthetic: `merged` (a first merge, with an earlier pull request closing another repository's issue that does not count), `archived` (a refused delete that archives, and a page that disagrees) and `unmerged` (no merge before the timeout). Each holds the hand-written `expected.txt` the run must print.

```sh
python3 -I bench/real-user/journey.py --dry-run bench/real-user/fixtures/merged --owner example --agent fake-agent --wizsite /wizsite --bench-file /tmp/bench.md
python3 -I bench/real-user/test_journey.py
```
