# OpenWiz states contract, version 1 (`openwiz.states.v1`)

NY2 (#3731 of #3713) defines the common input to Tracks, Map, Kanban, agent cards
and the agent directory. The read-only producer (#3732) publishes the snapshot.
The launch-fleet ping helper (#3735) uses the names and comment form below.

## Snapshot

One producer owns `.openwiz/states.v1.json` in the home checkout. Each run writes
one complete UTF-8 JSON document to a temporary file in the same directory and
atomically renames it over the destination. A failed write leaves the previous
document intact. Readers open only the destination and require the exact
`schema` value. Arrays are present even when empty. Unknown keys, duplicate
object keys and unknown enum values refuse the document.

| Field | Value |
| --- | --- |
| `schema` | `openwiz.states.v1` |
| `read_at` | Time the read finished, in UTC RFC 3339 with a trailing `Z` |
| `budget` | `limit` is the maximum GitHub requests per run, and `used` counts requests attempted, including pages, retries and failures. `0 <= used <= limit`. An unfinished read at the limit is unavailable. |
| `tickets` | One row per ticket number in the home checkout's tracker repository |
| `agents` | One row per derived name across the snapshot |
| `tracks` | One row per readable spec in the tracker, keyed by its issue number |
| `unavailable` | One row for each unreadable source affecting an entry or membership list |

A track's `tickets` and `agents` reference rows in the same snapshot, by number
and name respectively. Tickets belong to their GitHub parent spec. Agents
belong to their ticket's spec, or to the spec in their fleet name. A track's
`needs_owner` contains existing Needs you card IDs whose GitHub sources belong
to the spec, its tickets or their pull requests. Use the card ID as issued by
the card source. Keep an empty track for a readable spec with no readable
memberships. Report unreadable memberships separately in `unavailable`.

Each unavailable row has `kind` (`snapshot`, `track`, `ticket` or `agent`),
`ref` (`*` for a snapshot, the decimal spec or ticket number, or the agent
name), `source` and a one-line `reason`. If the unread facts could change an
entry's value, omit the entry and report its unavailable row. A failed or
partial page, an unknown record needed to resolve a state, ambiguous evidence
and exhausted requests are unreadable. An empty, fully read source is evidence
of absence. Keep independent rows that can be proved, and surface unavailable
rows even when their collection is empty. Use a safe reason in words without
copying raw service errors or comment bodies.

## Sources and precedence

Use the public GitHub records in [records v1](records.v1.md), the public
`launch-fleet:` records and exact-head verdicts defined by
[fleet tick v1](fleet-tick.v1.md), [review loops v2](review-loops.v2.md) and the
launch-fleet records table. Use native issue and pull request state, parent and
blocker links, closing references, labels and their events, public comments,
and current-head checks. Only comments by configured record authors count as
fleet records or verdicts. Order comments by creation time and numeric
comment ID. An edit updates the record in place. Compare the full head SHA and
repository when joining checks, verdicts and deliveries to a pull request.

A verified merge is a closing pull request GitHub reports as merged into that
repository's default branch. Apply the
[plan link rules](plan-links.v1.md) when distinguishing hard blockers from
file context. Use verified merges for hard blockers, including the fleet's
existing explicit completion rule for human tickets. Ignore an unlinked pull
request. Select the unique verified closing merge, or the unique open closing
pull request if there is no verified merge. If the applicable set has more
than one entry, report the ticket and any dependent agent rows as unavailable.

For a non-draft pull request use the
[fleet tick check rules](fleet-tick.v1.md#the-rules-file).
Missing required results in a successful, complete read are pending. A failed
or cancelled current-head check is failing. Green requires the required checks
to pass and no failed, cancelled or pending check. A verdict at an older head
is history. Never combine that verdict with new checks to report merge.

## Ticket states

A ticket has `number`, `spec`, `version` (the GitHub milestone title),
`title`, `blockers` (native blocker issue numbers in the tracker, including
file context), `state`, `problem` and `pull_request`. A pull request
reference is `{repo, number, merged_at}`. It is null when there is no selected
pull request. `merged_at` is GitHub's merge time on a verified merge and
null otherwise. Count merged pull requests by distinct repository and number,
using `merged_at` to assign each to its week.

Choose the first applicable row. Blockers and holds still supply a problem
on active tickets.

| State | Deciding records |
| --- | --- |
| `merged` | Verified merge of the selected closing pull request, whether or not the issue is still open. |
| `closed` | Native closed issue with no verified merge. Includes completed human work, duplicates and issues closed as not planned. |
| `fix` | Open non-draft closing pull request with a failing current-head check or the latest trusted `VERDICT: CHANGES` on the current head. The draft flag takes precedence while the builder is editing a draft. |
| `ci` | Open non-draft closing pull request whose current-head checks are pending. |
| `review` | Open non-draft closing pull request with green current-head checks. Includes waiting for a reviewer, re-check or merge, with or without a current-head `APPROVE`. |
| `building` | Trusted live `launch-fleet: started` or `start checked, branch <branch>` on the ticket, or a linked open draft. A checked branch must match the linked pull request when one exists. A start claim without confirmation does not move the ticket. |
| `waiting` | No active work above, and `held`, `needs-info`, an unsettled hard blocker, or neither ready label on the open issue. |
| `ready` | Open issue with `ready-for-agent` or `ready-for-human`, with no active work above, hold, question or unsettled hard blocker. The label informs the display. Starting still uses fleet admission. |

On an open ticket choose one `problem` in the following order. It is
`{kind, reason}`, with a nonempty public sentence identifying the evidence
in words, or null when none applies. Terminal tickets use null.

| Problem | Deciding records |
| --- | --- |
| `held` | `held` label. Use a public ordering, manual, live or contract hold reason from the fleet record when readable. The label alone supports a generic reason. A current-head `merge blocked` record also supports a hold until cleared. |
| `blocked` | One or more unsettled hard blockers, including a trusted unresolved `waiting for #<B>` record for one. Name the blocker and the condition it must meet. |
| `failing` | Failing current-head checks or a current-head `CHANGES` verdict on an open non-draft pull request. Name the failed check or the review's requested changes in public words. |
| `stale` | A trusted `review given up` with no replacement for the current head, or an unresolved current-head `merge main asked` after a stale re-test. Use the recorded cause. The age of a wake or read is insufficient evidence. |

## Agents and stable names

An agent row has `name`, `role`, `ticket`, `pull_request`, `state`,
`since` and `record`. Roles are `builder`, `reviewer`, `fixer` and
`fleet`. Fleet rows have null ticket and pull request. Builder rows use the
ticket number and selected pull request if known. Reviewers and fixers carry
the ticket number and their pull request reference. `record` identifies the
native source that moved the agent into its state. It has `kind`, `repo` and
`number` (issue or pull request number), with a numeric `id` for a
`comment`, `label` event or `check`. `issue` and `pull_request` point to
those native records, with no `id`. `since` is the UTC time of the deciding
record or state transition, such as a check's completion or a comment's edit
from claim to confirmation. A wake, repeated observation or reminder that
keeps the same state does not reset it.

| Role | Name and identity anchor |
| --- | --- |
| Builder | `builder-<ticket>` from the issue. It keeps this name through a resume, takeover or ordinary fixes on the same assignment. |
| Reviewer | `reviewer-<pr>-<round>` from the pull request. Round 1 is the first `review started` span. Increment for each subsequent distinct start, ordered by creation time and comment ID. An unresolved initial or replacement `review starting` claim is the next round. Refused and withdrawn claims create no span. `re-check sent` and `review told again` belong to the existing reviewer even on a new commit. `review given up` retires that span. If an overwritten start leaves ambiguous public lineage, the affected names are unavailable. |
| Fixer | `fixer-<pr>-<round>` uses the fix round from the trusted PR record. Round 1 is the ordinary `findings sent` round. The original builder handles it under its existing builder name. Round 2 is the separately assigned fresh round, reserved by `fresh starting` and confirmed by `findings sent <commit>: fresh round started, branch <branch>`. The claim and its edit keep the same identity. The final check is a re-check of the existing reviewer. |
| Fleet | `fleet-<spec>` from the spec's `fleet active, loop fleet-<spec>` record. Fresh wakes use the same name. |

Numbers use positive decimal digits without leading zeroes. A PR's number is
from its own repository. If two distinct assignments would produce the
same displayed name (for example, same-numbered PRs in different
repositories), both are unavailable for lookup by that name. Never reuse a
name to route to the other repository.

Apply the first applicable row to an assignment that has evidence above.
Ticket phase alone does not create an agent. The one exception is a queued
builder on a ticket with an actionable ready label, as stated in the table.

| State | Deciding records |
| --- | --- |
| `done` | Verified PR merge, PR closure for its reviewer or fixer, ticket closure or `archived` for its builder, or spec closure for its fleet. `review given up` retires that reviewer and a confirmed fresh-round start retires the original builder on the PR. A failed fresh start ends its queued assignment. |
| `merge` | Builder, assigned fixer or reviewer on a green head with a trusted current-head `APPROVE`, including an applicable `merge queued` record. Use the verdict or the queue record that established the state. |
| `fix` | Builder or active fixer on a failing head or a current-head `CHANGES`, or a trusted ordinary findings delivery or confirmed fresh-round start. The reviewer who issued current-head `CHANGES` is also in `fix` while waiting for the changed head. |
| `review` | The applicable reviewer start or `re-check sent`; or green checks on the current head of an assigned builder or fixer. A re-check supersedes the previous round's verdict on the new head. |
| `ci` | Pending checks on the current non-draft PR head of an assigned builder or fixer. Use the check or native PR event establishing the pending head. |
| `building` | Live `started` or `start checked` for the builder, and `fleet active` for a fleet whose spec is still open. |
| `queued` | `starting` or an eligible `ready-for-agent` label event for a builder with no confirmed start. `review starting` for an initial or replacement reviewer, and `fresh starting` for a fixer, pending their confirmed start. |

If the same span continues across several heads, older-head checks, findings
and queue records cannot choose a current state. A fresh start in response to
older-head findings still identifies the fixer assigned to the new head.
An active reviewer can wait for the next head while CI runs. Keep its
previous decision's `fix` state until the trusted re-check record moves it
to `review`.

## Ping comment

Post this exact plain-text body with LF separators and no trailing newline.
`wiz` names the owner's proxy. An agent sends its own derived name. Send to
exactly one agent name. Post on a builder's ticket, a reviewer or fixer's
pull request, or a fleet's spec issue. Resolve that name and the record
location before posting.

```text
openwiz:ping v1
Sender: wiz
Target: reviewer-9201-1
Message: Can you share an ETA for the review?
```

The message is one nonblank line of ordinary text. Refuse a credential or key,
account identifier, transcript, any form of the word `claim`, or an instruction
to claim, start, stop or otherwise control work. These exclusions apply to
meaning as well as syntax. A mention, second target, unknown or ambiguous
name, misplaced record or additional line refuses delivery. The schema's
`#/$defs/ping` checks the wire form and common forbidden forms. The helper
also checks message content, verifies a trusted sender and the exact location
of the target, and requires a currently reachable agent of that identity.

The fleet forwards the message only to the named running agent. It records a
confirmed delivery by appending `Delivered: <UTC RFC 3339 timestamp>` to the
same comment. Use the comment's repository and immutable ID as the delivery key.
Any wake seeing that marker skips it. Serialize forwarding per key and keep
unconfirmed delivery outcomes for reconciliation. Retry only after confirming
the message was never delivered, including after an interrupted wake.
Pings only carry messages. Claims, leases and all start and stop decisions
continue to use their existing records.

## Fixture proof

The [schema](agent-states.v1.schema.json) and
[fixtures](fixtures/agent-states/) are synthetic. `states.json` pairs normalized
GitHub inputs with expected snapshot rows and `rounds.json` follows agent
identities across wakes. For each case, apply its `github_defaults` and read
omitted collection inputs as complete and empty. `pings.json` gives the
valid and refused comment bodies for the helper. Run
`python3 -I contracts/fixtures/agent-states/test_fixtures.py` with Python's
`jsonschema` available. Producer and delivery behavior use these fixtures in
their own proofs.
