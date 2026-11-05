# Synthetic candidate examples

All scenario data here is invented. No pointer, build receipt, product hash, gate pass
or timestamp represents actual authority, a real build, live execution or a
published release. `synthetic-ready.json` is a structurally valid preparation
record. In real use its unresolvable evidence refuses. A fixture resolver may
simulate that evidence to exercise the positive path; it must never be enabled
in a live release command.

`refusals.json` is a table of independent mutations to that record. `patch` uses
JSON Pointer paths and replace/add/remove operations. `schema_valid` is the
structural expectation. `publication` and `reason` name the contract outcome and
illustrative violated rule, not a new CLI error vocabulary or a priority between
several violated rules. A changed candidate may also fail its digest first.
Consumers targeting a later semantic check must explicitly recompute derived
hashes and configure matching synthetic decision/evidence records in their own
fixtures; doing so never repairs a missing real decision or live result.

Before implementation, the proof plan is interface/schema/example review:

| Claim | Evidence in this ticket | Consumer proof still required |
| --- | --- | --- |
| P1 Two recorded decisions; no third human step | Nullable decisions; missing ship/changelog and invented approval cases; successor guidance review | RL2 refusal fixtures and RL5 actual decisions |
| P2 Public commit after verified cut-over | Fixed public repository/anchor; private-source and missing-cutover cases | RL2 ancestry/cutover refusals; RL5 O17 read-back |
| P3 All automatic gates required/current | CI/privacy/claims/smoke missing, failed, stale, fixture, dry-run and uncertain cases | RL2/RL3 gate and live-vs-fixture proofs |
| P4 Four explicit risk classes | Unknown/missing classification and one missing-live case per category | RL2/RL3 bounded risk checks; RL5 actual results |
| P5 Compiled, checked, approved and published bytes agree | Product interface, stale/wrong-target, changed notes/artifact/kit and uncertain-publication cases | RL4 collector/package proofs; RL2 read-backs; RL5 installed identity |
| P6 Original ship clock includes waits | Baseline has 120 seconds awaiting changelog after ship; reset-timer case | RL2 resume fixture; RL5 real elapsed report |
| P7 Ordered sections, single patches and combined releases | Baseline ordinary patch; combined and completed examples below | RL2 entry/order fixtures; RL5 real release |

For a combined shape, `synthetic-combined.json` retains separate sections for
0.0.6–0.0.12, newest first, and a smoke coverage row for every promise. For a
finished shape, `synthetic-installed.json` records a publication read-back and
normal update with matching identities. Its synthetic elapsed time is 900
seconds, including the 120-second approval wait. Neither is live evidence.

Validation uses existing tools only: parse strict JSON, compile the schema with
the already installed Ajv 2020 validator, validate all three complete shapes,
and apply every mutation to compare its structural verdict. Review semantic
refusals against the normative contract and P1–P7; no consumer code, product
suite, publication or live check is supplied here. The contract-first ticket's
proof is this review, as specified by RL1; consumers retain red-first tests.

`synthetic_assumptions`: keys, enum labels, the public repository name and fixed
public-history anchor are declarations from the future contract, not observed
room-cli responses. Versions, payloads, computed digest inputs, timestamps,
notes and receipt outcomes are invented; the two exact comment identities are
fabricated examples, never authority. Mutation names and illustrative reasons
use `synthetic_`; production keys and enum labels remain the contract's words.

The fixture scanner uses a separate named-key/label and synthetic-value allowlist
only for files directly in this directory. Nested/sibling directories keep their
existing rules. The global privacy patterns still apply, including decoded JSON
strings; only the two complete quoted example pointer tokens are recognized here.
Private IDs, credentials, other URLs, unapproved keys/values and malformed JSON
remain refused. Candidate JSON uses the existing strict reader before any generic
scenario dispatch, so duplicate keys (including escaped keys and nested objects)
cannot discard an earlier value, and naming a file `scenario.json` cannot switch
its rules. This synthetic provenance check does not replace schema validation
or prove that an example could authorize a real release.

A smoke coverage `pass` means the complete user flow for that included promise
was exercised end to end on the combined candidate, as the contract requires.
The synthetic rows model that result; they supply no actual live evidence.
A partial check or a promise label alone cannot satisfy the live gate.
