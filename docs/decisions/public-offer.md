# Decision: the friends-first release is free only

**Approved on its own by Jake, 2026-11-10; confirmed 2026-11-13.** The
friends-first public release is free only: OpenWiz runs on the user's own
machines for $0 a month, with public code, no paid offer and no payment code.
Public copy says Paid plans come later. The proposed $50 a month with a
seven-day trial stays later work, to be decided from what early users ask for.
CloudRoom and model charges stay separate.

- 2026-11-10, option (c) of the P3 choice. Private record: https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6763149732
- 2026-11-13, confirmation that the release stays free only for now. Private record: https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6845243425

Both private records were read back on 2026-11-13 and hold the exact words; this
page paraphrases them. The site's implementation note moved with the site to WizSite (#1264).

## What was decided

| Question | Answer now |
| --- | --- |
| Is the first public release free? | Yes: $0 a month on the user's own machines, no licence wall. |
| Is the code public? | Yes, through the open-development route; proven by its cut-over evidence, not here. |
| Is there a paid offer or trial? | No. Copy says Paid plans come later. |
| Is there payment code? | No, not even a stub. |
| Are CloudRoom and model charges included? | No. They stay separate. |
| What happens to $50 a month and a seven-day trial? | Kept as a later proposal, never shown as available. |

## Left open for later paid work

None of these is settled, and nothing in this release may assume an answer:
the paid benefits; trial start and end, renewal, cancellation and access; the
payment arrangement and provider; and a safe test arrangement that makes no
real charge. A later decision, informed by early users, settles them before any
paid implementation, sale or trial check. No payment provider is chosen and no
charge is authorized by this decision.

## Clauses this removes from the release

The spec (#2194) was revised to match, and its earlier launch clauses no longer
apply:

- the launch paid version, its price and its trial (Solution, user story 10, and
  the free and paid implementation paragraph);
- the review of paid benefits and price/trial, and the bounded trial checks (PR6
  evidence, the live check's free/trial sentence);
- the payment arrangement as launch work (Out of Scope).

PR6 now asks only for truthful free use, public code, no paid offer or payment
code, the later-plans copy and separate upstream charges.

## Existing copy that disagrees

Reviewed on 2026-11-13 against `main`:

| Where | What it says now | What it should say |
| --- | --- | --- |
| #1109 (install journey), What to build | OpenWiz is free and an upgrade purchases CloudRoom | OpenWiz is free; CloudRoom and model purchases are optional and separate; Paid plans come later |
| #1109, acceptance: product and site upgrade CTAs | Upgrade CTAs explain the CloudRoom purchase | No OpenWiz upgrade CTA; any CloudRoom link is an upstream purchase with the verified owner-supplied referral, or says verification is unavailable |
| [first-hour evidence](../../tools/install/tests/first-hour/README.md#evidence-and-validation), the `paid_offer` gate | Decided by this ticket as paid benefits, payment arrangement and trial; `unresolved` | The same gate and schema, settled by the free-only decision and its verified producer |

No shipped product, site, install guide or skill copy mentions a paid OpenWiz
plan, price or trial today; the gaps above are in planned work. This review read
those files' text only. It is not the candidate-bound no-paid-offer and
no-payment-code review, which stays with the follow-up below.

## Handoff to planning

The copy and evidence follow-up is already in the approved #2194 graph:

- **#2293** (free-only launch copy and first-hour offer evidence) applies the
  copy above after #1109 and the first-hour contract's owner finish, keeps the
  `paid_offer` gate and schema with its free-only producer, and reviews the named
  candidate for no paid offer or payment code. It does not edit #1109.
- #2293 is blocked by #1109, #2200 and #2202, and is an exact native blocker of
  the installed proof, pages, security review and integrated acceptance (#2204,
  #2205, #2206 and #2207). Integrated acceptance cannot run before it merges.

No new ticket is needed. This decision alone proves no part of PR6, removes no
other gate and demonstrates no trial.
