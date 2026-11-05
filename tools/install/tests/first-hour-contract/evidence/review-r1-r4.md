# First correction round: R1–R4

Review: PR #2255 comment 6761877988, at
`65cc002359cd52adb7d9d33f6793f09307b81e24`. All four findings are new; this
is their first correction round. No dispute, diagnosis or counter reset.

The observable contract is the public first-hour validator report, not the
implementation's call shape. Existing fixtures miss these plausible bugs:

- R1: empty or incomplete original work/intent observations make the preservation
  loops vacuously succeed. New standalone recovery variants must be unproven,
  and must still refuse success when labelled live in memory.
- R2: dropping an uncertain intent from the final inventory hides its unresolved
  outcome. Missing or contradictory final records and inconsistent successive
  transitions must not settle it. A later resource read-back must still be able
  to resolve it; a positive sequential case proves that path.
- R3: duplicate keys in arrays silently select the last observation. Work and
  intent duplicates must be refused in either order; repeated immutable work
  and operation identities across snapshots must be compared explicitly.
- R4: a persisted proposal before its first provider call has zero calls and
  zero effects. Result and recovery examples must accept that honest shape;
  an applied or uncertain zero-call outcome must remain inconsistent.

Twenty-four variants extend the existing synthetic fixture table with literal
expected problem/failure/unproven codes. A focused standalone-recovery test
exercises the same report boundary after adding a synthetic live label in
memory; it supplies no live evidence. Expected codes are written independently
of the checker. The red run in `red-review-r1-r4.log` has 41 intended failures
across eight tests. It is committed before the fixes.

No effect is attempted or retried. This correction concerns contract consistency
and synthetic validation only. Existing live, interface-decision, independent
review and exact-head CI gates remain separate. Helpers: none.


## Correction and checks

Implementation: `c57a14b32d7781ac47359a2c5a368e69e904f633` (subsequent hand-back
commit adds only this evidence).

- R1: missing original work, pending intent fingerprints or required operation
  observations now produce explicit unproven codes. A nonempty original
  inventory with lost recovered items still fails as work loss.
- R2: every recovery intent joins the final inventory by identity. Missing final
  rows remain unproven, unresolved outcomes stay uncertain until resource
  read-back, and kind/count/phase contradictions refuse the record. A later
  reconciled observation passes the positive sequential fixture.
- R3: every work/operation inventory rejects duplicate keys before comparison
  or effect counting. Opposite-order fixtures produce the same refusal.
  Successive intent phases and cumulative counts are compared; immutable
  pending fingerprints and commit trees cannot change across snapshots.
  Mutable drafts/setup/branches are compared at each recovery boundary, not
  frozen across legitimate owner edits between interruptions.
- R4: both operation shapes permit zero calls. A persisted proposed operation
  with zero calls/effects is representable without fabricating a provider call;
  applied/uncertain zero-call outcomes are inconsistent.

The prior `operation-left-uncertain` variant also now reports
`operation_history_mismatch`: its final zero-effect observation contradicts the
original case's applied effect. Its uncertainty remains visible. The expected
problem is strengthened to reflect that contradiction, rather than ignoring
history or removing the negative case.

Validation on the tested code state:

- `python3 -I tools/install/test_install.py`: all 8 focused contract tests logged
  and passing, then all 9 outer installer tests pass (review-r1-r4-install.log).
  The existing fixture table now holds 3 examples and 78 variants.
- `cargo test -p openwiz-tests --test checks fixture_scan`: 13 pass
  (review-r1-r4-fixture-scan.log).
- `cargo fmt --check`: exit 0; no output. No Rust crate changed, so no clippy.
- The exact reviewer reproductions now refuse R1's empty recovery, R2's omitted
  uncertain intent and R3's conflicting duplicate. R4's honest zero-call setup
  proposal has no schema or cross-field problem (review-r1-r4-reproductions.log).
- Diff whitespace/owned-path and shared-section checks pass. No new dependency,
  hook edit, workspace/static full suite, browser suite or live command.

The scoped-push Credits Rule applies to the correction's push: run the direct
privacy/destination adapter and document `--no-verify`; preserve remote changes
before pushing. The final pushed head/tree and destination result belong in
PR #2255's updated facts. Full CI, including the install lane's 8 focused tests
at the new head, and an independent exact-head re-check remain pending. All
four IDs are addressed in correction round 1, subject to reviewer verification.
