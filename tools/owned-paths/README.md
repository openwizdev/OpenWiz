# Owned paths (#1418)

CI fails a pull request that edits a file outside its ticket's owned paths, so the reviewer doesn't have to catch it by reading.

```sh
python3 tools/owned-paths/check.py --pr N                    # a pull request, as CI checks it
python3 tools/owned-paths/check.py --ticket N [--base REF]   # this branch, before you push (default base origin/main)
python3 -I tools/owned-paths/test_check.py                   # its proofs, on synthetic fixtures and a fake gh
```

It reads GitHub only through `gh api graphql`. In CI it is the `owned-paths` job in `.github/workflows/ci.yml`, with the workflow's own read token.

## What covers a file

- **The linked tickets' `## Owned paths`** for this repository, parsed as build-ticket's `ticket.py` parses them: each bullet's backticked paths, bound to its `` in `owner/name` `` qualifier or else to the ticket's repository. Shared and annotated bullets count as owned. A path ending in `/`, or naming a folder, covers everything under it; `*` matches within one folder, `**` across folders.
- **The standing supporting-edit rule** in `docs/agents/fleet.md` (read at the pull request's base, never its head): the backticked paths of its numbered kinds, with `<ticket>` read as the linked ticket's number.
- **An `F4 supporting edit granted` comment** on the ticket or the pull request from a record author (the `Record authors` row of `docs/agents/fleet.md`'s `## GitHub identity` table): every backticked path after the marker, unless the grant names only other repositories.

A file none of these covers fails the check, named with the ticket. Move it out, or ask on the ticket for a grant that names the path in backticks. Prose a check can't read (a bullet with no backticked path, "and its schema") covers nothing.

## Linked tickets

GitHub's closing references, and `Closes`, `Fixes`, `Resolves` or `Part of` followed by `#N`, `owner/name#N` or the issue's URL. Only this repository's issues are checked; a ticket in another repository is noted. A pull request that links no ticket, or only issues without an `## Owned paths` section, passes with a note.

The job runs on the pull request's own events (opened, pushed, reopened, ready for review). Editing the body or adding a grant starts no run: re-run the job.
