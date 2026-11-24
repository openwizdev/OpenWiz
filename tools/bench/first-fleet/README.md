# The first-fleet bench

Times one first-fleet run, from the pasted install line to GitHub's merge time of the first fleet pull request, and prints the step table: each step's start, length, who it waited on and any failure, the total, and whether any step waited on a timer. It needs no change to the install skill. Standard library Python 3.9 or later.

```sh
B="python3 -I tools/bench/first-fleet/bench.py"
$B mark run/ install agent                      # as each step starts
$B mark run/ connect user --failure "gh lacked a scope"
$B report run/                                  # the table, in Markdown
$B report run/ --json                           # the same, as JSON
$B report run/ --no-github                      # a run that stopped before the spec was created
```

## The rules

1. **A clean machine:** a fresh user account with only Claude Code or Codex signed in, `gh` installed and signed in, Python 3.9 or later and `git`, and nothing from OpenWiz or CloudRoom.
2. **The clock starts** when the install line is pasted: mark `install` at that moment. A `preflight` mark before it is shown with a negative start and is not in the total.
3. **Mark each step as it starts,** with who it waits on. The steps, in road order: `preflight`, `install`, `setup check`, `skills copy`, `where`, `repo`, `connect`, `grill`, `models`, `host setting`, `plan`, `launch`, `build`, `review`, `merge`. Who it waits on: `user` (a question or a yes), `agent` (the agent working), `timer` (a scheduled wake) or `ci`. A step is marked again when it is redone. A step lasts until the next mark; the last until the clock stops.
4. **The clock stops** at GitHub's `mergedAt` of the first fleet pull request to merge: a pull request that closes one of the spec's tickets, matched by the issue's URL, so a same-number issue in another repository never counts. The setup pull request closes no ticket, so it never stops the clock. A step marked after that merge is outside the table, its timer waits and the total; the report lists it under `Marked after the clock stopped`. With no merged fleet pull request there is no total, and the report says why. A run that stopped before the spec was created (a failed `connect`, say) has no GitHub record: report it with `--no-github`, which refuses if any GitHub file is in the folder.
5. **Any `timer` wait is flagged** under `Timer waits`.
6. **Times are minutes:seconds** from the install line.

## The run folder

`mark` writes `steps.jsonl` there, one line per mark: `{"at": "<ISO 8601 time with a zone>", "step": ..., "waits_on": ..., "failure": ...}` (`failure` only when given; `--at` sets the time). After the run, record GitHub's own times into the same folder:

```sh
gh issue view <spec> --json number,createdAt > run/spec.json
for n in <each ticket of the spec>; do gh issue view $n --json number,createdAt,url; done > run/tickets.json
gh pr list --state all --json number,createdAt,mergedAt,closingIssuesReferences > run/prs.json
```

Each file holds one JSON array or JSON objects one after another. A malformed step log or GitHub file exits 2 and names the file and the bad line; nothing is printed on stdout.

## Tests

```sh
python3 -I tools/bench/first-fleet/test_bench.py
```

The fixture runs in `fixtures/` are synthetic: `merged` (every step, a failure, a pull request closing another repository's same-number issue that does not stop the clock), `timer` (timer waits flagged), `unmerged` (no total, and why) and `early` (stopped before the spec, reported with `--no-github`). Each holds the hand-written `expected.txt` the report must print.
