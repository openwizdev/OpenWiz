# WizSkills' own check (WZ7, #2632)

WizSkills checks itself without ClosedWiz ([contract](../../../contracts/wizskills.v1.md),
"Package layout and checks"). This folder is the source; the copy places it.

| Here | In the WizSkills tree |
| --- | --- |
| `check/run.py` | `check/run.py` |
| `ci.yml` | `.github/workflows/ci.yml` |
| `test_check.py`, `red-run.txt` | not copied: ClosedWiz's proofs of this folder |

```sh
python3 check/run.py                                   # in a WizSkills tree: exit 0 pass, 1 fail, 2 arguments
python3 -I tools/skills-copy/package-check/test_check.py  # here: synthetic trees only
```

`check/run.py` checks the tree holding its `check/` folder, needs Python 3.11+
and `sh`, and reads no network, secret or file outside that tree. It runs all
three parts, even after a failure, and fails if any part fails or is missing:

1. **The skill rules,** as `skills/README.md` states them: one finding per line,
   `rules: <rule> <file>[:<line>]: <reason>`, with `rule` one of `layout`,
   `frontmatter`, `codex`, `notice`, `links`, `symlink`, `manifest`. Every folder
   in `skills/` is a carried skill; the manifest lists exactly those, sorted.
   The source-line skills are listed in `SOURCE_LINES`; every other skill
   carries Matt Pocock's notice. Link findings never echo the link target.
2. **The standalone check:** `python3 -I check/standalone.py <root>`, exit 0
   for a pass. A missing `check/standalone.py` fails.
3. **Each skill's own suites,** `SUITES`: the list `ci/select/skills.py` runs,
   without its one ClosedWiz tool (`tools/review-relay/test_inbox.py`).
   `test_check.py` fails if the two lists drift. A suite whose file is missing
   fails. Suites run from the root with `GH_TOKEN` and `GITHUB_TOKEN` removed.

The workflow runs `python3 check/run.py` on every push and pull request, with
`contents: read`, no secret, no expression and a pinned checkout without
persisted credentials. The image suite uses the hosted runner's Node.

## Seams

- **WZ3 (#2631)** places `check/run.py` and `ci.yml` at the paths above.
- **WZ2 (#2630)** provides the standalone scanner; the copy places it at
  `check/standalone.py` with the interface in step 2.
