# The roadmap generator

`roadmap.py` reads GitHub's milestones and writes the short public roadmap to a file; the release check runs it. Python 3 standard library and a logged-in `gh`. It reads the clone that holds the script by default, wherever you run it from; pass `--root /absolute/path/to/clone` to read another.

```sh
python3 tools/roadmap/roadmap.py --public ROADMAP.md  # write the short public roadmap to a file
python3 tools/roadmap/test.py                         # its tests, on a fake gh
```

`--public-repo OWNER/NAME` names where the `v<version>` tags are.

## What it reads

- A milestone titled exactly `N.N.N` is a **version**; `Infra` and `0.0.X` are lanes and are skipped; any other title stops the run.
- Its description's one **"You can …"** line is the outcome, and its one **"Done when …"** line is the live check. The first `#N` on that line is the live-check ticket. A missing or doubled line is reported, never guessed.
- A version's **state** is the highest with evidence: published (a `v<version>` tag), live-checked (the live-check ticket closed as completed), built (a `release-<version>` branch), building (a spec, an issue with sub-issues, in the milestone), else being grilled.
- **Now** is building, built and live-checked; **Next** is being grilled.

## The page

`--public` writes each Now and Next version's number, state and "You can …" line. Each line must use only plain punctuation, no token mixing letters and digits, and no capitalised word but `You`, `OpenWiz`, `CloudRoom`, `GitHub`, `Mac` and `PC`, or nothing is written. That guard is a backstop, not a privacy review.

## Exit status

| Status | Means |
| --- | --- |
| 0 | Written or already current |
| 1 | Stopped, nothing written: a failed or unexpected read, an unknown or doubled milestone title, a file it couldn't write, or a refused public line |
| 2 | Usage mistake, `--public` missing included |
| 3 | Written, with milestones listed on standard error (a missing or doubled line, or a live-check ticket that is a pull request) |
