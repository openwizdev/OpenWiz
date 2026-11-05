# #2826 proof plan

- Jog compute prices: published list rates and second billing verified 2026-11-14 at https://usejog.com/docs/pricing/. jog-4vcpu $0.0024/min; jog-8vcpu $0.0044/min; jog-16vcpu $0.0088/min. Source observation, not an invoice.
- CLI fixture proof: two successful runs totalling 3 minutes, one failed job lasting 30 seconds, two merged PRs. At the 16-vCPU rate: window $0.0308, successful-code-run average $0.0132, window/merged PR $0.0154. Existing tests miss Jog labels and sub-minute Jog billing. Red must show unknown before the mapping and sourced rows exist.
- Report/chart proof: two adjacent synthetic daily windows at different costs show USD/merged PR and USD/code run beside time and capacity, and literal day-over-day changes. Zero merged PRs, missing prices, old points and missing calendar days stay unknown rather than divide by zero or bridge gaps. Existing chart proofs only own timing/capacity.
- Scope review: only tools/ci-bench; no runner settings, workflow, dependencies or CI changes. Infra change needs no product changelog.
- Backfill: use existing measure/backfill interfaces only. Inspect available run records before deciding whether the last seven complete fixed-PST days can be remeasured. Do not add a collection or publication path for this ticket.

Ticket has no parent, blockers, downstream tickets or named grill. No downstream seams required.
