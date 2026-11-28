# Skills eval

A behaviour eval of every shipped skill: synthetic cases, the real skill text, fake GitHub, CloudRoom and process tools, and a scorer for the agent's actions, their order and its records. Rules: [contract.md](contract.md). Python 3 standard library only.

These run in this checkout:

```sh
python3 -I tools/skills-eval/test.py                                     # offline proofs (free)
python3 -I tools/skills-eval/eval.py score "$RESULTS_DIR"                # exit 0 only if every case passed every repeat
python3 -I tools/skills-eval/eval.py compare "$SET_A" "$SET_B"           # refuses different settings or cases
python3 -I tools/skills-eval/eval.py tokens --results "$RESULTS_DIR" --out "$OUT_FILE"   # recorded provider usage (free)
python3 -I tools/skills-eval/eval.py token-diff "$BEFORE" "$AFTER"
python3 -I tools/skills-eval/parallel.py --out "$RESULTS_DIR" --env-file "$ENV_FILE"     # resume an existing results set, four cases at once
```

`check`, `coverage`, `run` and `tokens --offline` read the shipped skills from a commit's `.claude-plugin/plugin.json` (`--rev`, default `HEAD`). The skills moved to WizSkills in #555: at `HEAD` they stop with a `TypeError`, and the last commit before #555 reports 104 problems (its private folders are not in the snapshot). They are unavailable in this checkout. `parallel.py` only resumes a results directory whose `manifest.json` a `run` already wrote.

`eval.py mentions --jev --skills DIR` is the one command that asks TypeSafe's Jev which docs a SKILL.md names that the keywords missed. It reads a WizSkills checkout, needs `OPENWIZ_JEV=1` and `TYPESAFE_API_KEY`, and sends a SKILL.md only when the keywords left a doc unresolved. `check` and `tokens --offline` never ask Jev.

| File | What |
| --- | --- |
| `cases/`, `provenance.json` | One synthetic case per file; each case's source |
| `required-text.json` | The files one load of each skill requires |
| `settings.json` | The frozen run settings |
| `fakeworld.py` | The fake-tool boundary |
| `score.py`, `records.py`, `cases.py` | Scoring, record checks, case checks |
| `driver.py` | One paid role run |
| `tokens.py` | Required-text bytes and recorded token usage |
