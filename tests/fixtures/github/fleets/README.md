# `openwiz fleets` fixtures (A4, ClosedWiz#112)

Synthetic `gh` answers for the fake `gh` (`tests/fake-gh/main.rs`), read by `tests/fleet/a4_fleets.rs`. Every value is synthetic. The shapes are `gh` 2.100.0's, as A1's spike observed them (A1, #109); each scenario's `synthetic_assumptions` names what wasn't observed.

- `complete/`: the contract's example 1 (`contracts/fleet.v1.md`) as `gh` would print it, with four values renamed because the fixture scan holds no such value (the repository, the specs' label and the two check names). Also an open issue with no sub-issues, a closed spec, a closed pull request and one that closes nothing: none of them is a fleet's or a ticket's.
- The others extend `complete/` and change one answer each: a failed, malformed or hung `gh pr checks`; a blocker list cut short; a blocker from another repository; a failed `gh pr list` or `gh issue list`; a malformed issue list; an unreadable version.

**Not here:** a pull request's comments (a `VERDICT` line has no form in the fixture scan) and a compare that is neither `ahead` nor `identical`. The tests write those answers, as one more scenario that extends one of these.

`complete/`'s JSON was written once by a throwaway script from the example's facts; the files are the record.
