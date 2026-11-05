# R5: zero-call recovery history

PR #2255's latest review (comment 6764122896) read
`f47baada8bec4aaf2183e1db934cc0f616dd7719`. R1–R4 were resolved there;
R5 is new and this is its first correction. No dispute or counter reset.

The reported live-labelled in-memory probes reproduced the false pass for
both `applied` and `uncertain` prior phases with zero cumulative calls.
Proof commit `27a11e2b6` precedes the fix: four standalone/embedded fixture
variants require the literal `phase_attempt_mismatch` code, and their
live-labelled probes must refuse success. `red-review-r5.log` retains all
eight intended failures. A positive test covers both `proposed` and `refused`
in each observed phase, standalone and embedded, without provider calls.

The existing guard now checks both observed phases. The contract explicitly
states that zero calls cannot establish either an applied or uncertain phase
in either recovery observation or the final inventory. No schema, operation
identity, effect/reconciliation rule or authorization is changed.

`python3 -I tools/install/test_install.py` passes all nine focused contract
tests and all nine outer installer tests; `green-review-r5.log` retains the
output. This includes the existing R1–R4 fixtures and four new R5 variants
(82 variants total). No assertion was removed or weakened. Diff whitespace
and owned-path checks pass. Cargo/rustfmt are unavailable locally; no Rust
crate changed and remaining checks are left to CI. No dependency was added.

Push uses the existing scoped-push Credits Rule confirmed by ticket comments
6760123218 and 6760189740: `--no-verify`, after the direct privacy/destination
adapter succeeds for the private ClosedWiz destination at the committed head.
That adapter's designated-private exemption supplies no public privacy proof.
The copied-tree hook failure and real-checkout index-reader evidence remain
preserved in the earlier evidence files. No hook or unowned path is edited.

This is synthetic contract-consistency evidence only. Independent exact-head
re-check, CI and all existing live/release gates remain separate. No helpers,
review, merge, labels, live effects or CI reruns are part of this correction.
