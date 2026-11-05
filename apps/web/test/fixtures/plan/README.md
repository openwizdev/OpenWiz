# Plan page fixtures (#653, 0.0.11 U3)

Synthetic only: no real issue, account, repository or time.

- `target.json`: the design target's content packet (the approved plan brief) as an `openwiz.plan.v1` response (`contracts/plan.v1.md`). Written by the original target generator from the approved #647 reference fixture: 6 lanes, 60 tickets, 71 dependencies, the chain #2104 → #2105 → #2107 → #2405 → #2407 → #2408 → #2409 → #2410 holding 22, read 09:00:14 UTC, complete and fresh. The script recomputes the chain by the contract's rules and checks it against the packet.
- `plan.mjs`: the proofs' site (the static export, the fake API, and the plan route answering a document each proof can change) and small helpers.

`synthetic_assumptions`: repository `example-owner/example-plan`; version lanes' milestone numbers 6, 8, 9, 10 and titles `0.0.6 Fleets` and the like; specs #2100–#2400 for the versions, #2500 and #2600 for the side specs; pull request numbers are the ticket's plus 1000; ownership is the `ready-for-human` label; a needs-you ticket with no pull request has an unknown fleet state (contract column rule 4).
