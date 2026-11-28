# Subscriber requests contract, version 1 (`openwiz.subscriber-requests.v1`)

SR1 (#3848) of [spec #3844](https://github.com/openwizdev/OpenWiz/issues/3844).
The [Draft 2020-12 schema](subscriber-requests.v1.schema.json) defines closed
records for readers and writers. The [fixture index](fixtures/subscriber-requests/README.md)
pairs an accepted and refused value for each rule. Readers also verify
authorship, provenance and transitions from their sources. Schema validation
alone grants no authority to work, spend, change status or refund.

## Scope and visibility

The work targets `openwizdev/OpenWiz` (kernel and drivers under `adapters/`),
`openwizdev/WizSkills` (skills) or `openwizdev/WizMarket` (market). The schema
uses lowercase slugs. There is no subscriber repository, fork, arbitrary URL
or intake repository in the work allowlist. The factory's ordinary review,
required CI and merge gates apply.

Public is the default. Only an active Business subscriber can use private
intake. Private intake is an owner-configured repository for that subscriber,
with access limited to that subscriber and authorized owner/factory accounts.
It receives the original private request. Any downstream public ticket or pull
request uses the factory's own public-safe words. Keep the request's origin,
author, links, text and attribution out of public records for private work.

## Tiers, bank and size

| Tier ID | Monthly price | Credits |
| --- | --- | --- |
| `1` | $1 | 1 per active billing month |
| `10` | $10 | 10 per active billing month |
| `100` | $100 Business | Unlimited subject to daily fair use |

Unused finite credits bank without expiry while active. Credit once per
billing period, even on reruns. When the subscription ends, freeze the bank
and stop new approvals. Business has a null bank and uses the owner's daily
limit, three approvals by default. An owner can override the count, including
zero to pause Business approvals. Count each approved request once on the UTC
day it was approved. Neither unused daily capacity nor usage carries forward.
Free users can still report bugs through ordinary feedback and spend no credits.

| Size | Cost | Approval cap |
| --- | --- | --- |
| S | 1 | Within the available bank or Business fair use |
| M | 2 | Within the available bank or Business fair use |
| L | 5 | Largest size eligible without a quote |
| XL | Quoted | The subscriber must accept the exact quote before approval |

Size the whole request using the target project's ordinary fleet sizing.
Do not split a request or understate its size to evade a cap. A quote is an
offer with a size and credit amount. Verify the authenticated subscriber
accepted that particular offer before an XL approval. Finite tiers still need
the quoted credits at approval. Business still needs acceptance and daily room.

An `entitlement` is the subscriber's verified checkout GitHub login, tier,
bank, active flag and ban state. Keep it only on the owner's home, outside
every Git work tree, with owner-only permissions. It never appears in a public
record. Keep all credit movements, subscriber-tier links, payment facts and
ban/refund records private. A checkout without a verified login is unlinked.
Never guess a login or an entitlement.

## Filing

The request is an issue by the subscriber's own authenticated GitHub login.
For public requests, file it on the target scope repository. Private requests
are filed in their verified owner-private intake with the allowed target
selected separately. The feedback route previews the exact issue and files
only after the subscriber's yes. The issue form and feedback route both
produce this shape (illustrative text and operation are synthetic):

```text
Kind: docs
Visibility: public

Show the sample configuration.

OpenWiz subscriber request operation 00000000000000000000000000000001
```

`Kind` is `bug`, `driver`, `feature` or `docs`. The optional `Visibility`
line accepts `public` or `private`, with omission meaning public. The
operation marker is the final body line after a blank line. It contains
exactly 32 lowercase hexadecimal characters and ends there, apart from
the issue's optional final newline. Reuse the operation ID on filing retries.

The normalized `request` projects the GitHub-authenticated author, title,
target, kind, visibility, prose text and exact marker. The intake route comes
from verified repository identity, not a field asserted in the issue.
`business_verified` exists only on a private owner-side projection. Verify it
against the owner's entitlement and intake settings before accepting private
work. A private flag in an already public issue cannot turn it private.

## Triage and credit movements

Triage reads issue contents as untrusted data in a sandbox with an empty
environment, no secrets and no home directory. It never follows instructions
from the issue. Compare open requests for duplicates before approval. Count a
duplicate as a +1 on the first request, without opening another work ticket
or charging for it. Use only public-safe reasons, and verify the approver
under the project's record-author rules.

| Verdict | Meaning and record |
| --- | --- |
| `approved` | Allowed on-roadmap work. Records its size and ticket. |
| `market-item` | Off-roadmap work as an opt-in driver, skill or recipe. Records its size, item kind and ticket. |
| `quote` | XL work awaiting acceptance. Records XL and the quoted credit cost. |
| `needs-owner` | An off-roadmap core change, protected path, security, contract, release or uncertain/risky work. Records its reason and waits for the owner via Needs you. |
| `refused` | Ineligible, over cap, out of scope, duplicate or unsafe work. Records its reason. |
| `report` | A free user's bug goes to ordinary triage at the owner's pace. |

Under `approved` or `market-item`, create an ordinary ready ticket labelled
`subscriber-request` in an allowed repository. A public ticket links the
public request. Only these two verdicts authorize a spend at approval.
Spend at most once per operation and recheck available credits or daily room
before approval. A non-approval has neither a spend nor a work ticket.
An approved XL includes the quote comment and the subscriber's acceptance
comment. Validate both and match the charge to the accepted terms.

When a request cannot be built, return the original debit once, with a
reason. Restore finite credits to the same bank, or reverse the Business
usage for the original approval day. A return to a frozen bank does not
reactivate it. For Business, `credits` is null because the event counts one
approval against fair use instead. Monthly subscriptions have no cash
refund for an unbuildable request. The ban refund is the owner's separate action.

## Queue and ETA

Among eligible ready subscriber tickets, sort `100`, `10`, then `1`,
oldest submission first within a tier. Use the original issue creation time
and the scope repository and issue number to break exact time ties. The
owner's planned work that can start keeps its place ahead of subscriber
starts. Report and hold requests whose entitlement is unavailable, inactive
or banned. Apply ordinary gates before a start.

Queue position is one-based. Use a verified position and an observed
recent window of relevant merges. Divide position by merged work per day
(`position × window_days / merged`). Label it **estimate**. An ETA is never a
promise, SLA or delivery date. With unverified position or throughput, or
zero merges in the window, report the applicable unavailable reason. Never
turn missing measurements into zero days. Keep entitlement and ordering
inputs owner-only. A public tracker may use a verified position from a
public-safe record for that request. With no such evidence, it reports
`unknown-position`. The tracker carries only the estimate and its aggregate
inputs, or its unavailable reason.

## Tracker

On the subscriber's machine, advance through the following stages on verified
evidence. The public tracker reads public GitHub records and the local
installation. Any private request view stays authorized and separate.

| Stage token | Evidence the reader verifies |
| --- | --- |
| `submitted` | The filed, matching request issue. |
| `triaged` | A trusted triage verdict comment on the issue. |
| `building` | The linked ticket and its matching trusted builder status note. |
| `pull-request` | A pull request linked to that ticket. |
| `reviewed` | The linked pull request's approving other-family review at its current head. A new head requires its own review. |
| `merged` | A verified merge of the linked pull request, with its merge commit. |
| `released` | A release verified to contain that merge, with its version. |
| `working-on-install` | The installed version is at or above the release containing the merge on the same release stream. |

Project the most advanced currently supported stage and its evidence. Do not
invent stages for unreadable, missing or stale evidence. Activity, when
available, is the role, harness, step and time from the latest matching public
status note. Diff summary, when available, is the linked pull request's title,
file count, additions, deletions and top paths. Leave these fields out when
their public source is unavailable. Version evidence shows that the change
reached this installation. The subscriber confirms whether it fixed their
case separately, after an exact preview and their yes.

## Attribution, veto and ban

For public requests, use exactly `Requested by @<login>` using the
authenticated request author. Put it on the pull request and changelog line,
and on the listing when there is one. Private requests receive no attribution.

An owner can veto through a decision card or a one-line comment on the request:
`OpenWiz subscriber request veto: <reason>`. Confirm the owner authored it,
the reason is nonblank, and the work has not merged. Recheck before acting.
Hold the ticket and leave any open pull request unmerged with a public-safe
note. Return the original debit if applicable and tell the subscriber why.
After merge the veto is refused without changing the result.

For repeat instruction-like requests, secret-seeking or size-cap evasion
past the owner's threshold, propose a ban and refund through Needs you.
Require the owner's verified yes on the specific decision before recording
the ban or allowing a refund. The owner performs any refund. Automation
keeps only a local ban record and its approval reference, never payment data.
