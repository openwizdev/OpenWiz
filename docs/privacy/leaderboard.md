# Leaderboard privacy review

This review covers the 0.2.0 board on openwiz.dev and in the factory room
([#4009](https://github.com/openwizdev/OpenWiz/issues/4009)). It checks the
[leaderboard contract](../../contracts/leaderboard.v1.md) against the
[zero-telemetry contract](../../contracts/telemetry.v1.md). It reviews the
proposed data flow. The publisher and board builds still need their own
proofs.

## Score record fields

The factory computes the score locally. The table accounts for every JSON
key and value the score schema allows, including optional fields.

| Score field | Bytes sent in the score JSON | Public board and privacy check |
| --- | --- | --- |
| `version` | Fixed string `openwiz.leaderboard.v1`. | Used for validation. It identifies the format and carries no user or work data. |
| `handle` | The chosen handle, with the GitHub login offered as the default. | Shown on both boards. It identifies the entry and may identify the person. Disclose it before the yes. |
| `period` | Object containing the UTC date bounds. | Shown as board context. It describes the reporting window. |
| `period.from` | First UTC day, inclusive. | Shown as the start of the reporting window. No individual merge time is exposed. |
| `period.to` | Last UTC day, inclusive. | Shown as the end of the reporting window. No individual merge time is exposed. |
| `pull_requests` | Integer count of qualifying merged pull requests. | Shown as an aggregate. It reveals activity volume and requires consent. |
| `points` | Numeric weighted and capped score. | Shown as an aggregate. It reveals scored activity and requires consent. |
| `by_size` | Object containing three aggregate counts. | Shown as counts by size. The breakdown requires consent. |
| `by_size.S` | Integer count of qualifying small pull requests. | Shown as a count. Individual changes and line totals stay local. |
| `by_size.M` | Integer count of qualifying medium pull requests. | Shown as a count. Individual changes and line totals stay local. |
| `by_size.L` | Integer count of qualifying large pull requests. | Shown as a count. Individual changes and line totals stay local. |
| `boost` | Reserved. The schema allows absence or the JSON literal `null`. Omit it in 0.2.0. | Hidden. No payment or boost information is sent. |
| `board` | Reserved. The schema allows absence or the JSON literal `null`. Omit it in 0.2.0. | Hidden. No extra board membership is sent. |

Rank is derived from row order, with tied scores sorted by handle. The
board builder adds the build timestamp and assembles the rows under the
common period and format version. The period and build time can appear
above the rows. Format version is for readers. Rank and build time are
public board output and are absent from the factory's score upload. The
room highlights the user's row locally. Keep the user's local score and
highlight state out of any shared room payload.

## Outbound requests

A scheduled score is a report about the factory's work, including when
GitHub hosts it. The telemetry contract requires `opt-in: telemetry` for
each automatic report. A recorded leaderboard yes is separate consent
for making the data public. Both must be in effect before publication.
Missing settings, a missing answer, a no, or a recorded leave grants
no permission to publish. Turning telemetry off stops future reports.
Leaving also removes the existing entry.

| Operation | Application payload and visible metadata | Check against the telemetry rules |
| --- | --- | --- |
| Create or update the public GitHub gist | The score JSON above, including its keys, values and JSON syntax. The API envelope carries the public visibility flag and a fixed generic filename. Any required description must be fixed and generic. GitHub associates the gist with the signed-in GitHub account and adds gist and revision IDs and timestamps. | Allow only with a current leaderboard yes and `telemetry: true`. The public GitHub login remains visible even if the handle differs. Avoid any factory-specific name in the filename or description. |
| Register once in WizMarket | The chosen handle in `boards/members/<handle>.json`, the handle and gist ID in the file, and Git and pull request metadata, including the publishing account, target repository, ref, commit and PR text. | This is an additional public write about the factory. Gate it on both consents. Keep refs and text generic apart from the handle and removal target needed by the operation. Resolve the conflict with the score-only promise before signup. |
| Leave | An authenticated request identifying the gist to delete and a WizMarket change removing the registration path, with the same Git and PR metadata as registration. | The owner starts this cleanup explicitly. Allow it with telemetry off. Send no new score or registration. |
| Read the public board | Site builds fetch registration files and gists by their public locators. A room fetching the board sends the public board address and ordinary request metadata. | The site build runs outside the factory. A room fetch must be part of the owner-started board view, with no local handle, score or join state in the request. |

GitHub sees the API or Git request, authentication needed for the operation
and ordinary connection metadata such as the source IP. Credentials
belong only in authentication to GitHub. They must stay out of the gist,
registration and PR text. There is no OpenWiz ingestion endpoint.

Keep the opt-in answer, its timestamps, and the scorer's source records
on the machine. This excludes repository names and paths, PR titles and
numbers, branches, commit IDs, code, review details, model families and
repository facts from the score and registration. No receipts, install
reports, identifiers for analytics or other reports belong to this flow.
The publisher is still proposed. Before sign-off, its offline tests must
capture the actual requests and verify the complete payloads, including
the GitHub envelope, registration and cleanup metadata.

## Signup wording

This is the exact proposed wording for the GitHub gist and WizMarket
registration design, pending resolution of the findings below.

> Join the public OpenWiz leaderboard? If you choose Yes and telemetry is on, anyone can see your chosen handle, rank, points, pull request counts by size, and scoring dates on openwiz.dev and in the factory room. Your GitHub login is visible on the public gist, and WizMarket publicly links your handle to that gist. You can leave at any time. Leaving removes your entry from the board after it refreshes. Copies or public GitHub history may remain. Choosing No keeps your factory off the leaderboard.

Show **Yes** highlighted and **No** beside it. Each is one explicit action.
Skipping or dismissing the prompt keeps the factory unjoined. A visual
highlight grants no consent. The choice must leave the telemetry setting
alone. The wording discloses the additional GitHub identity and
registration link and explains that yes alone cannot start publication.
Re-review the exact text if the publication design changes.

## Leaving

One owner-started leave action stops future uploads, deletes the public
gist and starts removal of the WizMarket registration. Keep publication
disabled throughout cleanup. Retry failed cleanup without republishing.
Both boards must drop the entry on refresh when its registration is gone
or its gist is unavailable. A pending removal PR is still pending cleanup.
Deleting the live sources cannot recall copies, caches, or Git and pull
request history. Prove the two-board removal on the next build in the
parent spec's live check.

## Changes required before signup

1. Require a current leaderboard yes and `telemetry: true` for score
   uploads and registration. Prove zero publish calls on a missing
   consent, no, leave, or telemetry switched off. Prove that the signup
   choice leaves telemetry untouched and cleanup works with telemetry off.
2. Reconcile the score-only publication rule with the public GitHub login
   and the additional WizMarket registration, including its handle, gist
   ID and public history. Remove the extra exposure or revise the approved
   publication scope and review the exact signup text against that scope.
3. Verify the actual outbound payloads and the board rendering against
   this inventory. Verify deletion of the gist, completion of registration
   removal, and disappearance from both boards on refresh.

**Sign-off withheld. Complete the changes above before asking anyone to join.**
