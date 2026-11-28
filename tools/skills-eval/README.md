# Skills eval

A behaviour eval of every shipped skill: synthetic cases, the real skill text, fake GitHub, CloudRoom and process tools, and a scorer for the agent's actions, their order and its records. Rules: [contract.md](contract.md). Python 3 standard library only.

Offline checks run first and cost nothing. Pin the WizSkills commit with flags or the environment; a pin is a full 40-character commit in a full (not shallow) WizSkills checkout:

```sh
git clone https://github.com/openwizdev/WizSkills.git "$WIZSKILLS_CHECKOUT"
export WIZSKILLS_CHECKOUT WIZSKILLS_COMMIT=$(git -C "$WIZSKILLS_CHECKOUT" rev-parse origin/main)   # or --wizskills DIR --wizskills-commit SHA
python3 -I tools/skills-eval/test.py                                     # offline proofs (free; also checks the committed ledger when a pin is set)
python3 -I tools/skills-eval/eval.py check                               # cases, coverage, provenance, required text, controls and the ledger; needs OPENWIZ_PRIVACY_LITERALS (contract.md)
python3 -I tools/skills-eval/eval.py coverage                            # every ledger row with its cases and missing categories
python3 -I tools/skills-eval/eval.py ledger [--propose]                  # the ledger against the pin and every branch of the checkout
python3 -I tools/skills-eval/eval.py run --out "$RESULTS_DIR"            # check, then paid runs; refuses before any key while check fails
python3 -I tools/skills-eval/eval.py score "$RESULTS_DIR"                # exit 0 only if every case passed every repeat
python3 -I tools/skills-eval/eval.py compare "$SET_A" "$SET_B"           # refuses different settings or cases
python3 -I tools/skills-eval/eval.py tokens --results "$RESULTS_DIR" --out "$OUT_FILE"   # recorded provider usage (free)
python3 -I tools/skills-eval/eval.py token-diff "$BEFORE" "$AFTER"
python3 -I tools/skills-eval/parallel.py --out "$RESULTS_DIR" --env-file "$ENV_FILE"     # resume an existing results set, four cases at once
```

**The snapshot** is this repository at `--rev` (default `HEAD`) with WizSkills installed at the pin, as `tools/wizskills/install.py` lays it out: the pinned commit's `skills/` replaces this repository's `skills` link, and the whole pinned tree is under `.wizskills/`. The shipped skills are the ones the pinned `.claude-plugin/plugin.json` lists; `check` also accepts and requires case coverage for `observed-used` ledger rows. A results set (`manifest.json`, `score.json`, and provider usage reports) records both commits (`revision` and `wizskills`), and `parallel.py` verifies and resumes at the set's own WizSkills commit and tree. Without a pin, every command but `score`, `compare` and `token-diff` refuses with exit 2.

**The ledger** ([`ledger.json`](ledger.json)) has one row for every skill WizSkills has had. Each row's `status` is one of:

| Status | Meaning, at the pinned commit | Its other keys |
| --- | --- | --- |
| `shipped` | `skills/<name>/SKILL.md` is there and `plugin.json` lists it | none |
| `observed-used` | `skills/<name>/SKILL.md` is there, `plugin.json` doesn't list it, and a file loads it | `used_by`: a snapshot file that names `skills/<name>/` |
| `historical-only` | gone, but in the pinned commit's history | `last_seen`: a full commit in that history that has it |
| `branch-only` | never in that history; on a branch | `branch`, and `commit`: a full commit that has it |

`check` fails when a skill on the pin or in its history has no row, when a row's status doesn't match the pin, when the eval's cases, required-text map or not-applicable list names a skill with no row, and when a row that any committed version of `ledger.json` had is gone: rows are never removed, their status changes. The branch scan depends on which branches the checkout has, so it is in `ledger`, not in `check`: `ledger` also fails on a branch skill with no row, and on a branch-only row whose commit the checkout lacks. `ledger --propose` prints a row for every skill the ledger lacks. When you move the pin, run `ledger`, add what it proposes, and change the status of rows it names.

At WizSkills `main` (`d4f915cd6d02`) the ledger has 32 rows (23 shipped, 4 historical-only, 5 branch-only) and `check` reports 90 problems in the cases and the required-text map, so `run` refuses: those are #2362's.

| File | What |
| --- | --- |
| `cases/`, `provenance.json` | One synthetic case per file; each case's source |
| `required-text.json` | The files one load of each skill requires |
| `ledger.json` | One row for every skill WizSkills has had |
| `settings.json` | The frozen run settings |
| `fakeworld.py` | The fake-tool boundary |
| `score.py`, `records.py`, `cases.py` | Scoring, record checks, case checks |
| `driver.py` | One paid role run |
| `tokens.py` | Required-text bytes and recorded token usage |
