# Recurring-finding candidates

EB4-P (#2233). A stdlib-only library for #1387's future weekly promotion hook.
No collector, evaluator, persistence, command runner or loop is started here.

```python
# Load promote.py with importlib.util (the parent directory contains a hyphen).
result = promote.propose(journey_v1, start="2030-01-01T08:00:00Z",
                         end="2030-01-08T08:00:00Z", tag="synthetic-skill-r1",
                         prior=previous_proposal_ids)
```

`propose` accepts an explicit journey v1 object, a seven-day UTC half-open
interval `[start,end)`, the existing experiment-tag syntax and an optional
list/tuple of previous proposal IDs. It validates the journey through EB5's
existing v1 validator. Invalid inputs raise `ValueError`; no partial output is
returned. Inputs are not modified. Week selection belongs to the caller; the
existing PST boundary is supplied as UTC (midnight PST is 08:00Z).

Each `(PR number, finding id)` counts once, at its first raising independent,
nonduplicate CHANGES verdict. Findings raised on APPROVE do not count. Status
mentions, re-checks, duplicate verdicts and tickets sharing a PR add no findings.
The existing journey validator refuses helper findings presented as independent
observations. Unknown kinds remain in `counts` and never produce a candidate;
unrecognized markers must already have been normalized to `unknown` by the
journey producer. No kind is guessed from text.

The returned object contains:

- `week`: the explicit start/end; `history`: the journey's retained `unknown`.
- `counts`: one count for every existing kind, including zero and unknown.
- `candidates`: one per recognized kind with at least three distinct findings.
  Each has `id`, `kind`, `count`, an `experiment: {tag}` label, a `check` in
  EB3-C's `{id, kind, check, instruction}` form, and a synthetic CF4 `case`.
- `provenance`: candidate ID → separate `{pr, finding, source}` rows. Source
  links and historical facts never enter the self-check or case input.

The proposal ID hashes repository, week and kind using EB5's canonical digest.
It is independent of tag, source/event numbering, input order and growing counts.
Repeating an input returns the same proposal, never multiple copies. Supplying
that ID in `prior` suppresses it, even if the count or proposed tag changes.
The caller must retain IDs in its existing checkpoint before enacting a proposal;
this pure function provides no cross-process persistence or concurrency lock.
Those weekly crash/resume/no-duplicate-PR responsibilities remain #1387's.

The tag is a proposal label using EB's existing syntax, not a frozen experiment
bundle or an assertion that any stage passed. #1387 joins actual stage artifacts
under EB5's existing contract. A new candidate must not mutate running arms.
Cases remain candidates here, outside the shipped `cases/` suite and provenance
registry. Their controls exercise the existing scorer; they are not model runs.
Adopting a case requires review and a fresh compatible CF4 baseline. No paid
result, future improvement or saving is established. Rule/contract edits stop
for approval; independent exact-head review, required CI and verified merge
remain mandatory. Live, spending and activation gates are unchanged.

Run the synthetic seam proofs:

```sh
python3 -I tools/skills-eval/promotions/test_promotions.py
```

No new dependency or Rust crate is involved.
