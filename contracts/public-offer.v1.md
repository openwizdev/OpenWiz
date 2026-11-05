# Public offer v1

`openwiz.public-offer.v1` is the offer the friends-first public release makes.
It is a boundary, not an interface: it defines no price field, plan, entitlement,
trial state, payment provider or licence check, and none may be added under this
version.

Decision: Jake chose a free-only friends-first release on 2026-11-10 and
confirmed it on 2026-11-13 (#2202). The exact words stay private; see
[the decision record](../docs/decisions/public-offer.md).

## What this release offers

- **Free on the user's own machines.** OpenWiz costs $0 a month to run on the
  user's own machines. Free use sits behind no licence wall.
- **Public code.** The code is public, through the open-development route
  ([open-development.v1](open-development.v1.md)). This contract does not prove
  that route; its own cut-over evidence does.
- **No paid offer.** The release sells nothing, shows no price as available, and
  starts no trial. Nothing in the product, site, install guide or packaged skills
  asks for a card or offers an upgrade to an OpenWiz plan.
- **No payment code.** The release contains no checkout, billing, entitlement,
  trial, renewal, cancellation or payment-provider code, and no stub of one.

## What public copy says

Where copy mentions paying for OpenWiz, it says exactly: **Paid plans come
later.** It presents no price, trial or paid benefit as available.

Alerts, remote access, managed machines and support are examples of what paid
plans might include, never entitlements. This release puts no alert behind a
paywall, and copy promises no hosted or managed service that does not exist.

## Upstream charges stay separate

CloudRoom and model-provider charges are not part of OpenWiz and are not
included in it; copy that mentions them says they are separate. A CloudRoom purchase is never described as an OpenWiz
upgrade. A referral link appears only where the owner has supplied it and it has
been verified; otherwise copy says verification is unavailable, and no referral
is guessed. Cost estimates follow [setup.v1](setup.v1.md)'s rules: verified
current evidence, never a hardcoded pricing promise.

## Later paid work

A proposal of $50 a month with a seven-day trial is kept as later work. It is
not an offer, and nothing in this release may present it as available. Before
any paid implementation, sale or trial check, a later decision informed by early
users' requests settles:

- the paid benefits;
- trial start and end, renewal, cancellation and access after either;
- the payment arrangement and provider;
- a safe test arrangement that performs no real charge.

That decision gets its own spec, contract version and approved plan. Until then
none of these is chosen, and no ticket plans speculative billing code.

## Consumers

- **First-hour offer gate.** [first-hour.v1](first-hour.v1.md) keeps its
  `paid_offer` gate and schema. Its free-only meaning and producer are set by
  the approved copy and evidence follow-up (#2293), not by this contract. This
  decision alone settles no gate and proves no PR6 evidence.
- **Copy.** The site, install guide, packaged install skill and web app copy
  follow this contract through the same follow-up, which also replaces the older
  explanation that an upgrade purchases CloudRoom.
- **Evidence.** PR6's free-use, public-code, no-paid-offer and no-payment-code
  claims stay Unverified until checked on the named candidate.
