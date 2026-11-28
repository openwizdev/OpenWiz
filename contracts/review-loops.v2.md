# Review loops contract, version 2 (`openwiz.review-loops.v2`)

Spec #885 (builders rule instead of stalling, and the fix loop is capped).
This contract fixes the shapes the spec's tickets build against: the
builder's ruling line, the reviewer's mark for each ruling, the re-check and
final-check outcomes, the logged blocker and the four v2 `Next:` states. BR1
(#886) writes it and teaches `check-report` in
[`tools/war-room/review_loops.py`](https://github.com/openwizdev/OpenWiz/blob/8880e7b7bbe6932e177cd5b2532e692231d66b0c/tools/war-room/review_loops.py) to
enforce it. BR3 (#888) puts the ruling line into the build skill, BR4 (#889)
the marks and outcomes into the review skill, and BR5 (#890) the `Next:`
routing into the fleet skill.

Version 1 ([review-loops.v1.md](review-loops.v1.md)) is not edited and stays
valid: the bench, its cohorts and its AFTER comparison read it, and
`check-report` still accepts every v1 report.

Every example below is synthetic: made-up PR and issue numbers, heads and
paths. None is a live observation.

## What v2 keeps from v1

- **Words:** blocking finding, polish finding, real-user path and Unknown mean
  what v1's table says.
- **The finding lines:** `- **R<n> [blocking]** ...` with exactly one
  `User path:` or `Risk:` (`security`, `privacy` or `data loss`) line, and
  `- **R<n> [polish]** ... Polish issue: #<n>.`, as v1 pins them. What blocks
  is unchanged.
- **The verdict:** `CHANGES` while any blocking finding is open, otherwise
  `APPROVE`. A logged blocker is not open.
- **One review plus one re-check,** and the reviewer question and
  orchestrator answer lines, as in v1.
- **The `builder` and `merge` `Next:` lines,** word for word.
- **The decision record's form,** used only to relay Jake's answer to a
  parked finding (below).
- **The bench, cohorts, records, watchdog, target and rollback:** v1 only. v2
  adds no record and changes no measure.

What v2 drops: v1's `orchestrator` and `final` `Next:` states. A report that
uses any v2 form below never uses them.

## The ruling line

A builder decides what stays inside its ticket's intent and logs each
decision as a **ruling** in a `## Rulings` section of its pull request
description: one numbered line per ruling, numbered from 1 with no gap, or
exactly `none`.

```md
## Rulings

1. Export refuses a folder destination as well as a file. Why: the ticket's "existing destination" covers both. Cost if wrong: low: a cook who meant to export into a folder picks a file name instead.
2. The refusal exits with status 2. Why: the CLI contract keeps 3 for network errors. Cost if wrong: high: a script that waits for status 3 misses the refusal and deletes its only copy.
```

```md
## Rulings

none
```

Each line is `<n>. <what it decided>. Why: <why>. Cost if wrong: <level>: <what breaks>.`,
where `<level>` is `high` or `low`. The level is the builder's own reading of
the cost; BR5 reads it to send an overturned high-cost ruling to Jake.

## The reviewer's mark

Each report marks every ruling in the description at the head it read,
exactly once, after its findings:

```md
- **Ruling 1** upheld: the ticket's "existing destination" covers folders.
- **Ruling 2** overturned as R4: the CLI contract gives every refusal status 3.
```

```md
Rulings: none.
```

`upheld` keeps the ruling. `overturned as R<n>` makes it the report's
finding `R<n>`, graded by the existing rule (blocking with its `User path:`
or `Risk:` line, or polish with its polish issue) and fixed or filed like any
finding. Two rulings never name the same finding. `Rulings: none.` is the
mark when the description has none; it never stands beside a ruling mark.

## The outcomes

The first review leaves its open blockers to the builder, as in v1. After
that:

- **At the re-check,** a blocker with a `Risk:` line still open goes to **one
  fresh fix round**: one new builder of the original builder's family, on a
  stronger profile, for that one round. Every other blocker still open is
  **logged** by the reviewer as a follow-up issue, and the report approves
  when no `Risk:` blocker is open.
- **At the final check,** after the fresh round, a `Risk:` blocker still
  open **parks** as a decision for Jake. Any other open blocker is logged, as
  at the re-check.
- A finding the review or re-check first raises follows the same rules; a
  re-check still opens no new narrow cases. A fresh round never resets the
  one review plus one re-check, and a pull request gets at most one.

A **logged blocker** keeps its line and says where it went. The follow-up
issue is the existing form, titled `Follow-up of #<ticket> (spec #<spec>)`
and labelled for triage; its number is required:

```md
- **R1 [blocking]** still open after 1 round: a second export still replaces the first. Logged as follow-up #4310.
  User path: a cook exports twice in one day; the second export silently replaces the first, and the first is lost.
```

`Logged as follow-up #<n>` logs a blocker only as its status (the text
right after the finding's id) or as the last sentence of its first line.
The same words anywhere else (quoted in a finding, a `User path:` or its
evidence) log nothing, and the blocker stays open. v1's log forms
(`logged as polish`, `follow-up`, `Polish issue:`) never close a blocker in
a v2 report.

In a report that uses any v2 form, every open or logged blocker restates its
`User path:` or `Risk:` line, so the outcome can be read from the report
alone. A `Risk:` blocker is never logged: it goes to the fresh round or
parks.

## The `Next:` states

The report's last paragraph is exactly one of these lines (ids as `R1`,
`R1 and R2` or `R1, R2 and R3`):

| State | When | Line |
| --- | --- | --- |
| `builder` | The review leaves blockers open | `Next: the builder fixes or disputes R1 and R2 once, then one re-check.` |
| `fresh` | The re-check leaves a `Risk:` blocker open | `Next: a fresh, stronger builder fixes R2 once, then one final check.` |
| `park` | The final check leaves a `Risk:` blocker open | `Next: park R2 as a decision for Jake.` |
| `merge` | No blocker is open | `Next: none open. It merges by the project's merge rules.` |

`fresh` and `park` name exactly the open blockers, and each has a `Risk:`
line: every other open blocker was logged. `builder` names exactly the open
blockers; `merge` names none.

## Jake's answer to a parked finding

The orchestrator relays Jake's answer as v1's decision record, naming the
parked finding and the head it parked at. This is the record's only use in
v2:

```md
**Orchestrator decision:** log and merge: R2 at 9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d. Polish issues: #4312. Why: Jake's answer to the parked finding: the log never leaves the machine.
```

## The check

`review_loops.py check-report FILE [--description PR]` applies v1's checks to
every report and, to a report that uses any v2 form (a ruling mark,
`Rulings: none.`, a logged blocker, or a `fresh` or `park` line) or is
checked against a description with a `## Rulings` section, these too. A
description with no such section lists no ruling. It refuses:

- a ruling mark that is malformed, repeated, or leaves a gap in the numbers;
  `Rulings: none.` beside a mark; an overturned ruling whose finding is not
  in the report, or two rulings that name one finding;
- with `--description`, a `## Rulings` section that breaks the ruling line,
  or any ruling it lists that the report leaves unmarked, or a mark for a
  ruling it does not list;
- a logged blocker with no follow-up issue number, a logged polish finding,
  or a logged `Risk:` blocker;
- a blocker closed by v1's `logged as polish`, `follow-up` or `Polish issue:`
  status (and, for a `Risk:` blocker, that it was logged at all);
- an open or logged blocker without its `User path:` or `Risk:` line;
- a `fresh` or `park` line that names a blocker with no `Risk:` line, or that
  does not name exactly the open blockers;
- v1's `orchestrator` or `final` line.

Without `--description`, a report with no ruling marks passes; the check
cannot see a ruling it was not shown.

## Gaps

`check-report` reads one report, and the description when it is given. It
cannot tell a re-check from a final check, so it cannot see a second fresh
round or a park sent straight from the re-check; the fleet's routing (BR5)
keeps one fresh round per pull request. It does not judge whether a mark,
a ruling's cost level or a logged blocker's grade is right: the reviewer and
the orchestrator do. Fixture tests prove the check's refusals only; no live
report has used v2.
