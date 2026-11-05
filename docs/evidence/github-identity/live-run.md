# GI7 live run: a pull request pushed, opened and commented on as the App

Ticket #2549 (GI7 of spec #2537), after its build PR #2689 merged at `ae0030ad`
and the App was installed (GI6, #2548). Run 2026-11-14 by the ticket's builder,
following `skills/launch-fleet/SKILL.md`'s "GitHub identity" section exactly.
No token, key or installation id is recorded here.

## Steps

1. **Author from GitHub, plain `gh`:** `gh api user --jq '"\(.login) \(.id)"'`
   on today's account gave `jparker2006 85816763`, so
   `git config user.name jparker2006` and
   `git config user.email 85816763+jparker2006@users.noreply.github.com`.
2. **Mint:** `openwiz github token --repository jparker2006/ClosedWiz`
   (`target/release/openwiz` built from main) succeeded; the token stayed in
   one shell variable, never in `GH_TOKEN` for plain commands, a URL, an
   argument or a file.
3. **Push** this branch through `app_git push` (git's environment-reading
   credential helper), **open** the PR through `app gh pr create`, and post
   the first-push receipt through `app gh pr comment`.

## Observed before the push (2026-11-14T02:20Z)

- **The installation's own rate limit** (`app gh api rate_limit`, core):
  limit 5000, used 4, remaining 4996. Today's account at the same time
  (plain `gh api rate_limit`): limit 5000, used 1334. The App spends its own
  installation budget, not the user's.
- **The installation's coverage** (`app gh api /installation/repositories`):
  1 repository, `jparker2006/ClosedWiz`.

## Read back after the push (plain `gh api`, 2026-11-14T02:26Z)

- **First commit** `abd43151460459dc2b6d6e8c0f18af0526277d66`
  (`gh api repos/jparker2006/ClosedWiz/commits/<sha>`): author and committer
  both `jparker2006 <85816763+jparker2006@users.noreply.github.com>`;
  GitHub links both to the account `jparker2006`, so the commit counts on
  the user's graph once it lands on `main`.
- **Who pushed** (`gh api "repos/jparker2006/ClosedWiz/activity?ref=refs/heads/room/2549-live-run"`):
  `branch_creation` at 2026-11-14T02:26:09Z to `abd43151`, actor
  `openwiz[bot]`.
- **Who opened the PR** (`gh pr view 2882 --json author`): `app/openwiz`;
  body `Closes #2549`; label `no-changelog` added by `openwiz[bot]`
  (`issues/2882/events`).
- **The first-push receipt** (`issues/2882/comments`): posted by
  `openwiz[bot]` (type `Bot`):
  `First successful push: abd43151460459dc2b6d6e8c0f18af0526277d66 at 2026-11-14T02:26:09Z`.
- **The installation's rate limit** after these writes
  (`app gh api rate_limit`, core): limit 5000, used 5, remaining 4995.

The push ran the pre-push hook (fmt, clippy, the checks binary, the CI
classifier test): all 4 passed at `abd43151`.

## Still to come

The fleet reviews this PR, merges it as the App and appends the merge
read-back below. The graph credit is confirmed only after that merge.
