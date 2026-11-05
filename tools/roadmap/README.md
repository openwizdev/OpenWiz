# The roadmap generator

`roadmap.py` writes where every version is from one source, GitHub's milestones (P2 of `docs/grills/2026-11-01-plan-and-ship.md`, spec #276, ticket #277). It rewrites only the marked, generated parts of two pages, and every other line stays hand-written:

- `docs/ROADMAP.md`: the Now and Next table, and its `mermaid` picture;
- `STATUS.md`: the version table, every version.

With `--public FILE` it writes only the short public roadmap to `FILE`: Now and Next, one line each.

```sh
python3 tools/roadmap/roadmap.py                      # rewrite the two pages' generated parts
python3 tools/roadmap/roadmap.py --public ROADMAP.md  # write the public roadmap to a file; the pages stay as they are
python3 tools/roadmap/test.py                         # its tests, on a fake gh
```

It needs Python 3 (standard library only) and `gh`, logged in, run inside a clone (`gh` finds the repository from `git remote`). Every read but the tags is of that clone, so to read another repository, run it in a clone of that one; its generated links then name that repository. The tags come from `--public-repo OWNER/NAME` (default `jparker2006/OpenWiz`, the public repository) (#1279). It only reads GitHub. Run it after every confirmed grill, plan graph approval and live check, and land what it changes as a docs-only pull request.

## What it reads

| From GitHub | Read as |
| --- | --- |
| Each milestone (REST, open and closed) | A **version** when its title is exactly `N.N.N`. `Infra` and `0.0.X` are **lanes**, never versions, and are left out. Any other title stops the run |
| A version's description | Its **"You can …"** line (the outcome) and its **"Done when …"** line (its live check): each a line of the description that starts with those words. None, or more than one, is listed and shown as missing, never guessed |
| The first `#N` on the "Done when …" line | Its **live-check ticket**, read by number wherever it is. No `#N` means the version can't read as live-checked |
| The milestone's issues | A **spec**: an issue with at least one sub-issue (its tickets) |
| `release-<version>` branches here | Its **release branch** |
| `v<version>` tags in the public repository (`--public-repo`, default `jparker2006/OpenWiz`) | Its **tag**, made by `release publish` |

A version's **state** is the highest one whose evidence exists:

| State | Evidence |
| --- | --- |
| published | its tag |
| live-checked | its live-check ticket, closed as completed |
| built | its release branch |
| building | a spec in its milestone, with at least one ticket |
| being grilled | none of these |

**Now** is building, built and live-checked; **Next** is being grilled. Published versions leave Now and Next, and stay in `STATUS.md`'s table.

## The pages

Each generated part sits between two marker lines, each exactly once in its page, the begin line before the end line, never overlapping another region:

```text
<!-- roadmap:now-next:begin -->   <!-- roadmap:now-next:end -->   docs/ROADMAP.md
<!-- roadmap:picture:begin -->    <!-- roadmap:picture:end -->    docs/ROADMAP.md
<!-- roadmap:versions:begin -->   <!-- roadmap:versions:end -->   STATUS.md
```

Edit the milestones, never the text between the markers: the next run writes it again.

## The public roadmap

`--public` writes only each Now and Next version's number, its state and its "You can …" line, under fixed headings: no done line, link, issue number, path, lane, published version or Later idea. Before it writes, each of those lines must be plainly public, or nothing is written:

- only letters, digits, spaces and `. , ; : ! ? ' " ( ) -` and `’ “ ” — – …`;
- no token that mixes letters and digits;
- no word with a capital letter in it but `You`, `OpenWiz`, `CloudRoom`, `GitHub`, `Mac` and `PC`.

A Now or Next version without exactly one "You can …" line stops it too. The guard can't see a private fact in plain lowercase words, so each line must be a public sentence by rule: the guard is a backstop, not a privacy review.

## Exit status

| Status | Means |
| --- | --- |
| 0 | Written, or already current. Each page's line says `updated` or `unchanged` |
| 1 | Stopped: a read failed or answered in a shape it didn't expect, a milestone title is unknown or doubled, a page's markers are wrong, a page couldn't be read or written, or `--public` refused a line. Nothing is written: every page is staged before any is replaced (should putting a staged page in place fail, it names the pages already written) |
| 2 | A usage mistake |
| 3 | Written, and some milestones are listed on standard error: a missing or doubled line, or a live-check ticket that is a pull request |

Running it twice in a row changes nothing.
