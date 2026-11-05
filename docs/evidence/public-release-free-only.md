# Free-only release: no paid offer, no payment code (#2293)

PR6's review portion for spec #2194: does the release offer no paid OpenWiz
plan, and contain no payment code? The boundary is
[public-offer.v1](../../contracts/public-offer.v1.md); the decision is
[public-offer](../decisions/public-offer.md) (Jake, 2026-11-10, confirmed
2026-11-13: free only, Paid plans come later).
Private record: https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6763149732

**Result: no paid offer and no payment code found in the reviewed paths, at the
reviewed source. One copy discrepancy (#1109's upgrade wording) was found and
is fixed by this ticket.** Evidence class: code review by #2293's builder,
scripted search plus reading each hit. It is not the independent review: the
pull request's reviewer re-checks it, and #2206 binds it to the checked
candidate.

## What was reviewed

| | |
| --- | --- |
| Candidate | None exists yet: no `openwiz.release-candidate.v1` record has been produced (#2186's interface; candidates come after cut-over). This review is bound to source instead |
| Source | ClosedWiz `main` at commit `9f1d6c66e3606929a8ec2d5f82a981d0889fd501`, tree `8da665383cfde66021b82ceab4f8522b76e5c991`, then this pull request's head for the changed copy |
| Paths | `crates/`, `apps/web/src/`, `apps/web/package.json` and its lockfile, `apps/site/` (`index.html`, `script.js`, `changelog/`, `build.mjs`), `skills/`, `tools/install/`, `tools/release/public/`, `Cargo.toml`, `Cargo.lock` |
| Date | 2026-11-13 |

## Method

1. `git grep -I -i -E` at the commit above for: `stripe`, `paddle`,
   `lemon squeezy`, `braintree`, `chargebee`, `checkout`, `billing`,
   `subscription`, `entitlement`, `licence/license key|check|wall`, `paywall`,
   `trial`, `payment`, `invoice`, `credit card`, `price`, `pricing`,
   `per month`, `/month`, and `$` followed by a digit.
2. The same provider names in both lockfiles and manifests.
3. Each hit read in place and classified below.
4. `premium`, `paid`, `upgrade`, `paywall` and `licence` in the product,
   site and install paths, to find offer copy rather than code.

## Findings

| Term | Hits | What they are | Verdict |
| --- | --- | --- | --- |
| Payment providers | 0 | none in source, manifests or lockfiles | clear |
| `billing`, `payment`, `invoice`, `credit card`, `entitlement`, `paywall` | 0 | | clear |
| `checkout` | 350 | Git checkouts (loop configuration, update clone, skills) | clear |
| `subscription` | 105 | phone-alert push subscriptions (0.0.15 notifications); no plan or tier check gates them | clear: no alert paywall |
| `trial` | 11 | a numerical fit step (`hill-climb`) and "failures/trials" as attempts | clear |
| `$` and a digit | 427 | shell and regular-expression arguments | clear |
| `pricing` | 6 | CloudRoom's own pricing page (upstream), an engine rule against hardcoded pricing constants, a test of that rule | clear: upstream, not an OpenWiz price |
| `upgrade` copy | 4 places | #1109's site line, setup panel, install skill and install guide: "an upgrade buys a CloudRoom plan" | **discrepancy**: a CloudRoom purchase described as an OpenWiz upgrade. Fixed here |

The first-hour pages (`FirstHour.tsx`, #2223) already say "OpenWiz is free
now. Paid plans come later." No other paid-plan, price or trial copy was found.

## After this ticket

The site, setup panel, install skill, install guide and README say: OpenWiz is
free now. Paid plans come later. CloudRoom and model charges are separate and
not included. CloudRoom's page carries no referral, and the copy says referral
verification is unavailable. The same search on this pull request's head finds
no `upgrade` in visible copy; the remaining hits are the code identifier
`CLOUDROOM_UPGRADE` (pinned by `tests/checks/skills.rs`) and a code comment.

No payment code was found, so nothing is routed to another owner.

## Limits and gaps

- Source only: no built binary, package or release archive was inspected.
- Dependencies were checked by name in manifests and lockfiles, not by reading
  their code.
- A text search can miss payment logic that uses none of the words above;
  each hit was read, the rest of the code was not.
- Not bound to a release candidate (none exists); #2206 re-binds this to the
  checked candidate.
- Free local use and public code are not shown here: they stay with #2207's
  live run and #1257's cut-over proof.
- The paid trial is later work: nothing here demonstrates or needs one.
