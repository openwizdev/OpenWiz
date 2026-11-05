# Ops inbox (#1481, OB6)

GitHub is the inbox. Every message the fleet routes (a CI failure, findings,
an answer, a contract note, a resume, a recheck) is first recorded as one
[ops-dispatch v1](../../contracts/ops-dispatch.v1.md) `intent` comment on the
ticket or pull request, bound to repository, ticket/PR, current approval and
head, destination role, opaque assignment, evidence and a stable operation key.
That record is the pending item; there is no second queue to lose. Transport,
the recipient's acknowledgement and completion are separate records. A message
is context, never authority: OB3's boundary keeps every delivery disabled under
OB-A1, and nothing here starts, tells, merges or writes.

Two pieces, both standard-library Python:

| File | Does |
| --- | --- |
| [`inbox.py`](inbox.py) (here) | Reads one conversation's ops records through `relay.py`'s existing `Reader` (REST pagination, route checks, ETags) and comment validation, unchanged. Any failed or partial page keeps the caller's cursor and returns no records. A `json` fence (at any indentation, closed or not) is an ops-record candidate when its decoded `schema` is the ops schema, JSON escapes included, or when it fails to decode yet names the schema. A candidate that fails the strict reader (an unterminated or indented fence, malformed JSON, another repository/subject, or a `created_at` that disagrees with its comment's own creation time) is a gap, and any gap makes the whole read incomplete: original cursor, no records. Other JSON, and prose that only mentions the schema, are not ops records. The relay keeps only the comment fields it reads, so this adapter widens that list by `created_at` on its **own** private copy of `relay.py`; the relay process, its state and its fields are untouched. |
| [`skills/launch-fleet/scripts/inbox.py`](../../skills/launch-fleet/scripts/inbox.py) | The pure inbox layer: recheck and findings intents, recipient pull/ACK, finite wakes, measures and the two missed-goal routes. No I/O. |

```sh
python3 -I tools/review-relay/test_inbox.py              # adapter, on the relay's own synthetic world and fake gh
python3 -I skills/launch-fleet/scripts/test-inbox.py     # inbox layer
python3 -I tools/review-relay/inbox.py --repo OWNER/REPO --kind pull_request --number N   # a live read: ask first
```

## Rechecks go to the recorded reviewer

`recheck(view)` returns one `delivery` intent to `reviewer` when the PR's latest
`VERDICT` (CHANGES or APPROVE) names an older head and required CI is green at
the current head. Its assignment is `review-span-<start comment>`: the span the
public `launch-fleet: review started` record opened, read as `records.py`
reads spans. The key covers PR, head, prior verdict and assignment.

- An identical recorded intent, or a legacy `re-check sent <head>` in the span, is a duplicate: never a second item.
- Only the latest verdict counts; one from before the current span's start is not that reviewer's to recheck.
- A given-up span is refused (`reviewer retired`); no start, a record before any start, a thread id in public or a reused comment id is refused (`ambiguous reviewer`). A fresh reviewer is not this ticket's to start.
- An intent under an older approval is not reused: the current approval keys a new item with its own sequence.

`findings(view)` sends the latest CHANGES at the current head to the builder's
assignment. Destination and assignment keep findings and rechecks apart.

## The recipient pulls and acknowledges

On its own finite wake, the builder or reviewer runs `wake(view, recipient,
assignment, own, source)`: it reads every ops record on its ticket and PRs,
checks them strictly and lists its items in sequence order, then ends.

| Item state | When |
| --- | --- |
| `reconcile` | Transport or completion is uncertain. It stays visible even when superseded, and blocks later items |
| `acknowledged` | An `ack` for this key, intent, assignment and sequence **that this recipient wrote** (`own`: its own record ids, kept privately). Another same-account comment, or accepted transport, is not an ACK |
| `complete` | A `completed` completion record |
| `superseded` | A superseding completion, a changed head or approval, or (for a builder/reviewer item bound to a verdict) a newer verdict |
| `recorded` | The next item to act on |
| `deferred` | A later item behind an unresolved one anywhere in the same ticket/approval, whatever its destination |

A failed or partial read, any record bound to another repository, spec or
ticket, conflicting record identities, or a sequence that is not exactly 1..n
for the ticket/approval returns no items and the start cursor. Ordering spans
every destination: another recipient's earlier item settles only by its ACK
listed in `verified_acks` (that recipient's own-output ids, verified
independently and kept privately), or by a completed/superseded outcome.
`acknowledge(...)` builds the `ack` only for the next `recorded` item, with the
head the recipient read. A dropped, duplicated or reordered push changes
nothing: a fresh agent with no sender state reads the same items.

`recovery(wakes)` says `pull usable (synthetic)` only for a complete wake from
an `independent` source that found items; an idle inbox, a partial read or a
PC-sourced wake is `unverified`. Live recovery during PC unreachability is
OB8's to prove.

## Measures and missed goals

`measure(...)` reports recheck delay (from the green head's eligibility to the
reviewer's own bound ACK) and the oldest pending item's age, both excluding the
union of held intervals once (malformed intervals refuse), with
`eligible/measured/open/unknown` denominators. Only an own ACK binding the
intent's recipient, assignment, sequence and head, or a completed/superseded
completion, settles an item; uncertain, refused, disabled or unverified
non-execution outcomes stay pending.

`due(settings, bench, intents, decisions)` reads the TL1 settings and refuses a
TL2 stage bench that was read with other settings or claims authority. For each
missed `fix_after_changes` or `builder_question_answer` wait it names the
existing role (builder / orchestrator) and the existing durable item's key, or
a gap saying one must be recorded first. Only a `delivery` intent with the
verified context's repository, spec and approval, the wait's ticket, subject,
head and origin comment, and the owner's assignment counts. A fix or answer is done only with the
bench's evidenced end source; delivery or escalation never is. A question the
ops agent judged to need a new decision is marked for Jake. Helper dispatch on a
missed stage is #2338's; initial starts are #1480's.

## Not proven here

Fixtures prove the reading, keying, ordering and refusal rules only. Delivery
stays disabled. Private routing from assignment to a thread stays in private
state (`records.py`). Selected-reviewer own-output authentication, independent
live wakes, PC-outage recovery and P5 remain Unverified until #2244 and OB8.
