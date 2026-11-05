# Review loops contract, version 1 (`closedwiz.review-loops.v1`)

Spec #2454 (review loops that ship). This contract fixes the shapes the spec's
tickets build against: the four bench measures and their cohorts, the review
report's blocking and polish lines, the reviewer-question and
orchestrator-answer lines, the 1 + 1 `Next:` states and the orchestrator's
decision record, the watchdog's limits and event record, the 1.5-rounds target
and the rollback trigger. RL0 (#2455) writes it and the bench tool
[`tools/war-room/review_loops.py`](../tools/war-room/review_loops.py) that
checks and measures it; RL0b (#2571) runs it on the BEFORE cohort and
publishes the numbers. RL1 (#2456) puts the blocking rule into the
review-ticket skill, RL2 (#2457) the 1 + 1 rule into the live skills, docs and
router, RL3 (#2458) the watchdog into the router, and RL4 (#2459) runs the
AFTER bench and the comparison.

Every example below is synthetic: made-up PR and issue numbers, heads and
times. None is a live observation.

## Words

| Word | Meaning here |
| --- | --- |
| **Cohort** | The PRs one bench measures: merged to `main` inside its window, each counted once however many tickets it closes. |
| **Review round** | One independent, nonduplicate review verdict at a distinct PR head, unedited and posted before the merge, as the existing journey verdict reader (`journey.rounds_of`) and WR6's rework admission read it. |
| **Blocking finding** | A review finding that holds the merge. Under this contract only a finding with a `User path:` line or a `Risk:` line blocks. |
| **Polish finding** | Every other finding. It is filed as a polish issue in the same review and never holds the verdict. |
| **Blocking-grade finding** | For the BEFORE cohort, a `high` or `medium` finding (the old rule's blockers); for AFTER, a blocking finding. |
| **Real-user path** | A concrete case in which a named kind of user does something ordinary and something visible breaks for them. |
| **Unknown** | A value the inputs cannot establish. It is counted and shown, never read as zero or success. |

## Cohorts

- **BEFORE:** PRs merged to `main` in the half-open window
  `[2026-11-10T08:00:00Z, 2026-11-13T08:00:00Z)`: the three fixed-PST days
  2026-11-10 to 2026-11-12 (77 PRs had merged at planning). The window is
  fixed; every PR merged inside it belongs to the cohort.
- **AFTER:** PRs whose first review round starts after the last of RL1, RL2
  and RL3 has merged and RL3's router copy is installed, and which merge in
  the seven fixed-PST days that follow (`[D, D + 7 days)`, `D` the next
  08:00Z boundary after that install). A PR with a review round on each side
  of the install is **mixed-rule**: excluded from AFTER and counted.
- The cohort is named in a cohort record (below), read from GitHub once, and
  the bench never re-reads GitHub. A cohort PR missing from the journey or
  outcome inputs is listed in the bench output with why; it stays in the
  denominator.

## The four measures

Each measure prints its n (PRs or findings it could measure), its Unknown
count, and its coverage (n over the cohort size, or over the blocking-grade
findings). Distributions also print the mean, median and p90, using EB6's
`trends.distribution` on the exact values: the median is the middle value
(the mean of the two middle values for an even n), the p90 the nearest-rank
value.

1. **Review rounds per PR:** the number of distinct heads among a PR's review
   rounds. A PR with no admitted review round is Unknown, never zero rounds
   and never first-pass success. A reposted verdict (the journey reader's
   `duplicate_of`) and a second verdict at the same head count once.
2. **First-push-to-merge hours:** EB6's sourced first-push receipt to the
   verified merge, from the outcome sidecar's rows. No receipt is Unknown.
   **PR-opened-to-merge hours** is a separate, separately labelled figure for
   every PR with a recorded `pr_opened` event; it never substitutes for push
   timing.
3. **Real-user-path share:** blocking-grade findings that name a concrete
   real-user path, over all blocking-grade findings classified. A finding
   counts when an admitted review round raised it before the merge. BEFORE
   reports have no `User path:` line, so each BEFORE finding carries a
   recorded judgment (`basis: judgment`) with its report link, spot-checked by
   the ticket's reviewer. The journey reader inventories only the old
   `high`/`medium` grades, so AFTER's blocking findings are inventoried from
   the report inventory record (below): the new `[blocking]` findings of each
   admitted round's report. Each is classified from its line (`basis: line`).
   An inventoried finding with no classification is Unknown and stays out of
   the share. While any admitted round of a measured PR has no report in the
   record, the inventory is incomplete: the share and its coverage are `null`
   (unavailable) and the missing count is printed.
4. **Escaped defects:** bugs found after merge and attributed to a cohort PR,
   by EB6's predeclared defect policy, frozen once here and reused unchanged
   for AFTER. `bench` refuses an outcome sidecar on any other policy, and
   `compare` refuses a bench output on any other policy:

   ```json
   {"rule":"explicit-causal-fix-link-v1","followup_hours":72,"deduplication":"root-cause-per-merge","unknown_attribution":"retain-unknown"}
   ```

   The rate is mature PRs with an attributable defect over mature PRs with no
   unknown attribution (EB6's `outcome_cohort`). An immature PR (merged less
   than 72 hours before the read) or one with unknown follow-up stays out of
   the rate. No mature PR leaves the rate Unknown. BEFORE matures on
   2026-11-16 PST; RL4 re-reads it then.

**Watchdog events** (AFTER only): flags, restarts and asks per kind, and the
distinct PR heads they touched, from the watchdog event log. BEFORE has none:
the watchdog did not exist, so the BEFORE value is "not applicable", not zero.

## Records

All records are JSON; every key below is required and no other key is
accepted.

### Cohort record

```json
{"schema":"closedwiz.review-loops.cohort.v1","name":"before","since":"2030-01-01T08:00:00Z","until":"2030-01-04T08:00:00Z","base":"main","read_at":"2030-01-04T09:00:00Z","prs":[4201,4202,4203]}
```

`since < until <= read_at`; PR numbers are positive, unique and sorted. The
list is every PR merged to `base` inside the window at the read.

### Finding classification record

```json
{"schema":"closedwiz.review-loops.findings.v1","cohort":"before","findings":[{"pr":4201,"finding":"R1","severity":"high","report":"https://github.com/example/factory/pull/4201#issuecomment-9101","basis":"judgment","user_path":true,"why":"A user exporting twice loses the first export."}]}
```

One row per blocking-grade finding: `severity` is `high`, `medium` or
`blocking`; `report` is the review report's comment link; `user_path` is a
boolean; `why` is one short sanitized sentence. A row for a finding the
journey does not show, or a repeated `(pr, finding)`, refuses the bench. A
`line` row must name a new `[blocking]` finding of a report in the report
inventory, with that report's link and `user_path` true exactly when the
finding has a `User path:` line; any other `line` row refuses the bench.

### Report inventory record (AFTER)

```json
{"schema":"closedwiz.review-loops.reports.v1","cohort":"after","reports":[{"pr":4201,"round":"e17","text":"VERDICT: CHANGES at bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n\n- **R5 [blocking]** `src/export.rs:48` (Spec) An existing `cookbook.zip` is overwritten. Fix: open it with `create_new(true)`.\n  User path: a cook exports twice in one day; the second export silently replaces the first, and the first is lost.\n\nNext: the builder fixes or disputes R5 once, then one re-check.\n"}]}
```

One row per admitted review round (independent, nonduplicate, unedited,
pre-merge, as for rounds): `round` is the journey's verdict event id and
`text` the report's collected text. The report's `VERDICT` line must give
that round's verdict and full head; its link is the round's journey source.
A row for any other round, a repeated round, or a blocking finding id seen
twice in the PR refuses the bench. The text is read only for the inventory;
the bench prints none of it.

### Safety-escape record (AFTER only)

```json
{"schema":"closedwiz.review-loops.safety-escapes.v1","escapes":[{"pr":4201,"finding":"R3","risk":"privacy","defect":"https://github.com/example/factory/issues/4901"}]}
```

Each row is an escaped security, privacy or data-loss defect (`defect`, its
issue or run link) traced to a finding that was logged as polish. An empty
list is a recorded none; without the record `compare` counts none.

### Watchdog event record

One JSON object per line (JSONL), appended by the router's watchdog to a
private log:

```json
{"schema":"closedwiz.review-loops.watchdog.v1","at":"2030-01-02T10:15:00Z","pr":4201,"head":"4b1f0c9e2d7a5b3c8f6e1d0a9b2c4e7f5a3d1c08","kind":"no-review-start","action":"restart","since":"2030-01-02T10:00:00Z"}
```

`kind` is `no-review-start` or `no-verdict`; `action` is `flag`, `restart`
or `ask`; `since` is when the clock started (the head went green, or the
review started); `at` is the router pass that acted.

### Bench output (`closedwiz.review-loops.bench.v1`)

`review_loops.py bench` prints one sanitized aggregate: the cohort (name,
window, PR list, size and each missing PR with why), the input hashes, the
frozen defect policy, and the four measures plus the watchdog counts (`null`
for BEFORE), each with n, Unknown and coverage. `compare` prints BEFORE
against AFTER from two such outputs and refuses an output whose defect
policy is not the frozen one. No raw comment text, title or identity
other than PR numbers and finding ids is printed.

## The review report's lines

A finding line keeps today's form, `- **R<n> [<grade>]** ...`. The grades
are `blocking` and `polish`; the bench reads the old `high` and `medium` as
blocking-grade and `low` as polish, so old reports still parse.

- **A blocking finding** has, on the next line, exactly one of:

  ```md
  - **R1 [blocking]** `src/export.rs:48` (Spec) An existing `cookbook.zip` is overwritten. Fix: open it with `create_new(true)`.
    User path: a cook exports twice in one day; the second export silently replaces the first, and the first is lost.
  ```

  ```md
  - **R2 [blocking]** `src/server.rs:90` (Sweep) The token is written to the access log. Fix: drop the header from the log line.
    Risk: privacy: any reader of the log sees a live token.
  ```

  `User path:` names who does what, and what breaks. `Risk:` names
  `security`, `privacy` or `data loss`, then what is at risk.
- **A polish finding** ends with its polish issue, filed in the same review:

  ```md
  - **R3 [polish]** `src/cli.rs:30` (Sweep) The help says "zip archive file". Fix: say "export". Polish issue: #4302.
  ```

- **The verdict:** `CHANGES` while any blocking finding is open, otherwise
  `APPROVE`. Polish findings never hold it.

`review_loops.py check-report FILE` refuses a report whose blocking finding
has neither line, a polish finding without its `Polish issue: #<n>`, a verdict
that disagrees with the open blocking findings, or a `Next:` line outside the
states below.

## Reviewer question and orchestrator answer

A reviewer with a real question asks it on the PR's ticket instead of
guessing or blocking, adds the existing `needs-info` label beside
`ready-for-agent`, and ends its turn. The first lines are:

```md
Reviewer question: #4210 at 4b1f0c9e2d7a5b3c8f6e1d0a9b2c4e7f5a3d1c08
Does export refuse when the target is a folder, or only a file?
```

```md
Orchestrator answer: #4210 at 4b1f0c9e2d7a5b3c8f6e1d0a9b2c4e7f5a3d1c08
Both: the ticket's "existing destination" covers folders.
```

`#<n>` is the PR and the head is all 40 characters. A question with no later
answer for the same PR and head is **open**: the review waiting on it is not
stalled and is never restarted.

## 1 + 1: the `Next:` states

Each PR gets one review plus one re-check. The report's last paragraph is
exactly one of these lines (ids as `R1`, `R1 and R2` or `R1, R2 and R3`):

| State | When | Line |
| --- | --- | --- |
| `builder` | The review leaves blockers open | `Next: the builder fixes or disputes R1 and R2 once, then one re-check.` |
| `orchestrator` | The re-check leaves a blocker open | `Next: the orchestrator decides R1: fix once more, or log and merge.` |
| `final` | The check after a fix-once-more decision leaves it open | `Next: the orchestrator logs R1 and merges, or asks Jake for a security, privacy, live, spending or publishing call.` |
| `merge` | No blocker is open | `Next: none open. It merges by the project's merge rules.` |

The orchestrator's decision is one comment on the PR:

```md
**Orchestrator decision:** fix once more: R1 at 9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d. Why: the fix is one line and the path is real.
```

```md
**Orchestrator decision:** log and merge: R1 at 9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d. Polish issues: #4303. Why: the path needs a second export inside one second.
```

A logged blocker becomes a polish issue and the PR merges by the usual merge
rules. Jake is asked only for a security, privacy, live, spending or
publishing call.

## Watchdog

The router's five-minute pass:

- **N = 15 minutes:** an open PR green at its head with no review started 15
  minutes after it went green is flagged (`no-review-start`) and its review
  started.
- **M = 60 minutes:** a review started at a head with no verdict 60 minutes
  later is flagged (`no-verdict`) and restarted with a fresh reviewer.
- **One restart per head per kind.** A second stall of the same kind at the
  same head is flagged and asked of the orchestrator (`ask`), never given
  another reviewer.
- A review stopped at an audit gate, or waiting on an open reviewer question,
  is never restarted.
- Every flag, restart and ask appends exactly one event record.

## Target and rollback

- **Target:** AFTER's mean review rounds per PR at most **1.5**. `compare`
  says `met`, `not met`, or `unknown` when AFTER has no measured PR.
- **Rollback trigger:** `triggered` when AFTER's escaped-defect rate is above
  BEFORE's (both known), or any escaped security, privacy or data-loss defect
  traces to a finding logged as polish; `unknown` when either rate is Unknown
  and no such defect is recorded; otherwise `not triggered`. When triggered,
  the orchestrator reverts the blocking and 1 + 1 rule changes (RL1, RL2) and
  tells Jake; the watchdog stays.

## Gaps

Fixture tests prove the arithmetic, Unknown handling and refusals only. The
BEFORE numbers are a read-only observation of GitHub's surviving records,
with journey v1's unknown historical completeness; BEFORE's real-user-path
share is a recorded judgment, not a measured line.
