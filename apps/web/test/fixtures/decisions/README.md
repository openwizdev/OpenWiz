# Decisions fixtures (#656)

Synthetic `openwiz.decisions.v1` responses for the page proofs `test/browser/e11-decisions-*.test.mjs`. Every id, number, file, wording, fingerprint and thread is invented; times start at `1800000000000` (2027-01-15 08:00:00 UTC), the proofs' paused clock.

- `target.json`: the design target's content packet (the approved Decisions brief): a grill round on PR #2731 with L3 saved and L4, L5 open; spec #2800 to confirm; release plan #2900 to approve (asks twice); spec #2790, the one the proofs send first. Orchestrator target `thr_syn_7c2e9a`, verified, fresh.
- `summary.json`: one grill summary confirmation (sends `confirm`).
- `empty.json`: a complete, fresh, empty read: the only shape that may say "Nothing waiting on you".

**synthetic_assumptions:** `current: {known: true}` and the explicit risks are future shapes: today's decisions route returns every record's currentness as unknown (spec readiness review on #648), so a live read disables every answer. The fingerprints' repeated hex digits are format examples, not calculated revision fingerprints. L3's wording and spec #2790's are invented to fill the packet's round and sent row. `decisions.mjs` derives the stale variants from these files.
