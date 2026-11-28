# Leaderboard v1 (`openwiz.leaderboard.v1`)

LD1 of spec #4009. This contract fixes the opt-in record, the shipped-work
score rule, the score record a factory publishes, the board file, the ban list
and two reserved fields. The scorer (LD3), the opt-in (LD4), the publisher
(LD5) and both boards (LD6, LD7) build against it.

**This contract grants nothing.** It publishes nothing, asks no one to join and
reads no repository. The privacy sign-off (LD2) reviews exactly what the board
shows before anyone is asked. A fixture that passes proves the documents agree
with this contract, never that a scorer or board has run.

Where this prose and [`leaderboard.v1.schema.json`](leaderboard.v1.schema.json)
disagree, the contract is wrong and must be fixed. Rules a schema cannot see
(time order, the score rule's arithmetic, the board's order, repeated handles)
are stated here and checked by
[`fixtures/leaderboard/test_fixtures.py`](fixtures/leaderboard/test_fixtures.py).
The [fixtures' README](fixtures/leaderboard/README.md) lists one valid and one
broken fixture per rule.

## The pin

```json
{
  "schema": "openwiz.leaderboard.v1",
  "sizes": {"S": [0, 100], "M": [101, 500], "L": [501, null]},
  "weights": {"S": 1, "M": 2, "L": 4},
  "daily_cap_points": 12,
  "day": "UTC calendar day of merged_at",
  "solo_repository_multiplier": 0.5,
  "published": ["version", "handle", "period", "pull_requests", "points", "by_size"],
  "reserved": ["boost", "board"]
}
```

Every document carries `"version": "openwiz.leaderboard.v1"`. Times are UTC,
written `YYYY-MM-DDTHH:MM:SSZ`; days are `YYYY-MM-DD`. A handle is a GitHub
login's shape: 1 to 39 letters, digits or single inner hyphens. Handles compare
without case.

## Opt-in record

Kept on the user's machine and never published; where it lives belongs to the
opt-in (LD4). Fields: `version`, `answer` (`yes` or `no`), `asked` (when the
question was answered), `handle`, `joined` and `left`.

- **R1, joined only after a yes.** With `answer: "no"`, `handle`, `joined` and
  `left` are all `null`, and nothing about the user is ever published. With
  `answer: "yes"`, `joined` is the time of the yes, no earlier than `asked`, and
  `handle` is the handle the user picked; setup offers their GitHub login as the
  default.
- **R2, leaving keeps its time.** `left` is `null` while joined. Leaving sets
  `left` to the time the user left, no earlier than `joined`; a left factory
  publishes nothing more and its published record is removed (LD5). Joining
  again writes a new yes with a new `joined` and `left: null`.

## Scorer input

The factory's own records, gathered on its machine by the scorer (LD3) for one
period. It holds repository names and never leaves the machine. Each entry of
`pull_requests` has `repository` (`owner/name`), `number`, `merged_at` (`null`
when not merged), `head` (the merged head commit), `builder_family`,
`additions`, `deletions`, `repository_facts` (`owners`, `other_contributors`,
`stars`, `forks`) and `reviews`, each with `state`, `commit` and `family`
(`null` when the factory cannot tell the reviewer's model family).

## Score rule

Apply these steps, in order, to the scorer input. A reader can do it by hand.

1. Keep a pull request only if `merged_at` is not `null` and its UTC day falls
   inside the period, both ends included.
2. **R7, nothing counts twice.** A pull request is its repository, compared
   without case, and its number. Keep only its first entry; a pull request also
   counts in one period only, the one its merge falls in.
3. **R3, the review rule.** It counts only with a review whose `state` is
   `APPROVED`, whose `commit` equals `head` exactly, and whose `family` is not
   `null` and differs from `builder_family`. A same-family approval, an
   approval of an older commit, a comment or a change request does not count.
4. **R4, size weights.** Changed lines are `additions + deletions`.
   S is 0 to 100 changed lines and weighs 1 point.
   M is 101 to 500 changed lines and weighs 2 points.
   L is 501 or more changed lines and weighs 4 points.
   So 100 lines is S, 101 is M, 501 is L.
5. **R6, half weight.** A repository with exactly one owner and no other
   contributors, stars or forks (`owners` 1, the other three 0) counts at half:
   S 0.5, M 1, L 2. One star, fork or other contributor makes it full weight.
6. **R5, the daily cap.** Add each counted pull request's points to its merge's
   UTC day. A day gives at most 12 points; the period's `points` is the sum of
   its days. Four L pull requests merged on one day give 12 points, not 16.

`pull_requests` is how many pull requests passed steps 1 to 4, `by_size` how
many of them were S, M and L, and `points` the capped sum. Points are always a
multiple of 0.5. The cap lowers `points`, never the counts.

## Score record

What a joined factory publishes (LD5), and the only thing it publishes.

- **R8, the listed fields and nothing else.** `version`, `handle`, `period`
  (`from` and `to` days), `pull_requests`, `points` and `by_size` (`S`, `M`,
  `L`), plus the reserved fields below. Never a repository name, path, title,
  branch or code; the schema refuses any other field. `by_size` adds up to
  `pull_requests`, and `points` is no more than the counted sizes' weights and
  no more than 12 for each day of the period.

## Board file

- **R9, ranked rows, ties by handle.** `version`, `built` (when the board was
  built), `period` and `rows`: score records for that period, highest `points`
  first, equal points in handle order (lowercase, byte order). A row's position
  is its rank. A handle appears at most once, and never a banned one.

## Ban list

- **R10, a ban names a handle and a date.** `version` and `bans`: each ban is
  the `handle` the owner removed and the `date` of the ban. A handle appears at
  most once. A banned handle is left out of every board.

## Reserved fields

- **R11, reserved and empty.** A score record may carry `boost` and `board` for
  the 0.2.x boost tag and boards. In v1 they are unused: either absent or
  `null`, and any other value is refused.
