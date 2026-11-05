# Scoped hand-back checks

Implementation checked at `3c3afff3e`; the hand-back adds only run logs and this
record. Both red runs preceded their corrections in Git history.

- `python3 -I tools/war-room/test_cost.py`: PASS, 12 cases, including malformed
  input subcases and independent synthetic $12 / 2 arithmetic. `green.log`.
- `python3 -I tools/war-room/test_contract.py`: PASS, 18 cases. `green-contract.log`.
- Python AST parse of both changed Python files and `git diff --check`: PASS.
- Owned-path/shared-section, explicit Unknown, native units and timestamps,
  source hash binding, unique identities, refusal cases, synthetic privacy,
  unchanged dependencies and checklist review: checked. No source/private data
  is saved; no CLI/tool/network call is made by the adapter.
- No Rust crate changed. Optional `cargo fmt --check` could not start because
  Cargo is absent (exit 127). No install is authorized by this ticket. Required
  repository format/static/full-suite checks remain CI's responsibility.
- The legacy installed pre-push hook runs broad workspace Clippy/static suites.
  The push uses scoped equivalents plus its destination privacy adapter,
  omitting that broad hook invocation under the scoped-local-checks instruction.
  This is not a claim that the broad hook or CI passed locally.
- Helpers: 0. This small offline adapter was built and checked directly; no
  helper window, independent review or helper no-push result is claimed.
- Plan revision 2 fingerprint independently recomputed as
  `c6aab97475a340cc2373cacd24174f0878e3d3ecd3789ffbef36bd076afc3caf`;
  posted approval table/native links and all four actual Relies-on paths pass.
  Producer #2345's merge was read back; no competing WR4 builder branch/PR
  existed before the first write. No task/spec body changed.

Limits: fixture proof only. Native sources lack complete PR attribution;
all-in stays Unknown. Supplied observation bounds/source assertions cannot be
authenticated here. Synthetic allocation demonstrates no real source support.
CI2 bill/micro-USD support, live collection, billing, scheduling, page hosting,
publishing and installed behavior are outside this implementation. Independent
exact-head review and green CI remain required before merge.
