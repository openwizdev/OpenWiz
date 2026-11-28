# Leaderboard fixtures

Fixtures for [`openwiz.leaderboard.v1`](../../leaderboard.v1.md). Every handle,
repository and count here is synthetic.

Run the proof from the repository root:

```sh
python3 -I contracts/fixtures/leaderboard/test_fixtures.py
```

A file name's first word names what it holds: `opt-in` an opt-in record,
`score` a score record, `board` a board file, `bans` the ban list, and `case`
a score rule case. A case is a test wrapper, not a document anyone writes: its
`input` is a scorer input and its `claimed` is a score record. The test scores
the input by the rule and fails the case when the claim differs.
`broken/expect.json` names the error each broken fixture must produce.

| Rule | What it fixes | Valid | Broken |
| --- | --- | --- | --- |
| R1 | `joined` only after a yes | `valid/opt-in-joined.json` | `broken/opt-in-joined-after-no.json` |
| R2 | leaving keeps its time | `valid/opt-in-left.json` | `broken/opt-in-left-without-time.json` |
| R3 | only an approving review at the exact head, by another model family, counts | `valid/case-review.json` | `broken/case-review-same-family.json` |
| R4 | size weights S 1, M 2, L 4 by changed lines | `valid/case-size-weights.json` | `broken/case-size-100-as-m.json` |
| R5 | the daily cap of 12 points | `valid/case-daily-cap.json` | `broken/case-daily-cap-ignored.json` |
| R6 | half weight for a solo repository | `valid/case-solo-half.json` | `broken/case-solo-full.json` |
| R7 | nothing counts twice | `valid/case-counted-once.json` | `broken/case-counted-twice.json` |
| R8 | the score record holds the listed fields and nothing else | `valid/score.json` | `broken/score-with-repository.json` |
| R9 | board rows ranked by points, ties broken by handle | `valid/board.json` | `broken/board-tie-out-of-order.json` |
| R10 | a ban names a handle and a date | `valid/bans.json` | `broken/bans-without-date.json` |
| R11 | the reserved `boost` and `board` fields stay empty | `valid/score-reserved-null.json` | `broken/score-boost-set.json` |

`red-run.txt` is the proof's first run, against a schema that accepted
anything, before the contract was written.
