# OpenWiz 0.2.0 GitHub-trending and real-user star plan

Status: **draft** (for owner review only; nothing is posted, scheduled or uploaded).

## Goal

Help developers arriving from the 0.2.0 launch understand OpenWiz in seconds, try it on their own machine, and star the repository only if they genuinely find it useful.

## Policy and hard rules

All star activity must come from real people acting on their own interest.

- **Allowed:** one plain, optional invitation to real users in places they already read OpenWiz (the README top, the GitHub release notes, and launch posts where the destination community's rules allow it).
- **Never allowed:**
  - Buying stars or paying for engagement.
  - Star-for-star trades, reciprocal star rings, or coordinated starring groups.
  - Automated starring, bot accounts, or scripts that star repositories.
  - Gating features, downloads, or support behind a star.
  - Asking for stars in channels whose rules forbid engagement requests (see [Launch post kit](../README.md): keep direct star and upvote requests out of every post file checked by `tools/launch/check_posts.py`).

Authority: [GitHub Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies) (which prohibit spam, inauthentic activity, and platform manipulation).

## Where real users are invited

| Surface | What it shows | Owner action |
| --- | --- | --- |
| `README.md` top | One-line pitch, demo visual (`docs/how-openwiz-works.png`), one-line install (`Install OpenWiz`), first-run command (`openwiz --help`), and one plain line inviting readers who find OpenWiz useful to star it. | Merge before launch day; swap in the 0.2.0 launch recording GIF once #3542 lands. |
| GitHub release notes (`v0.2.0`) | What 0.2.0 ships (verbatim from `CHANGELOG.md`), install link, and one closing line inviting readers who try it and find it useful to star the repo. | Owner reviews and publishes the GitHub release. |
| Launch posts (`docs/launch/0.2.0/`) | Link to `https://github.com/openwizdev/OpenWiz` and `https://openwiz.dev/app/`, inviting readers to try the release and share feedback — no direct ask for stars or upvotes inside post files. | Owner approves and posts each draft from their own account. |

## Verification before launch day

1. Run `python3 -I tools/docs-commands/docs_commands.py README.md` and confirm exit `0`.
2. Run `python3 -I tools/launch/check_posts.py docs/launch/0.2.0 --changelog CHANGELOG.md` once 0.2.0 post files are in place and confirm zero refusals.
3. Confirm the README top renders cleanly on GitHub (light and dark mode) with the pitch, demo visual, install phrase, first-run command, and star line visible above the fold.
