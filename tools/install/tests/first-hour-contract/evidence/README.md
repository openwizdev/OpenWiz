# First-hour contract proof (#2200)

All values in the proof inputs are synthetic. This proves interface consistency
and CI test discovery only; no installed or live first-hour outcome is proven.

The original failing-first commit is
`fe05e136667b6c951f38868279b44ab93370c3e6`; its accept-all checker precedes the
implementation in `330d2a7e3b541071f2735db4c15e344c6dc6101e`.
`red-contract-replay.log` is a later replay of that original commit's files in
an isolated temporary directory: seven tests, 96 failed subtests, exit 1. It is
not presented as the original run's captured output. Temporary paths were
replaced with `<red-checkout>`; the failures and inputs are unchanged.

`red-ci-discovery.log` records the existing `release:install` command before
wiring. Its eight installer tests passed, but its output did not contain
`test_each_example_gives_exactly_its_codes`; asserting that the contract suite
was discovered failed. The focused contract suite passes independently at
`330d2a7e3b541071f2735db4c15e344c6dc6101e`. The CI-coverage ruling permits one
invocation block in `tools/install/test_install.py` (ticket comment 6760021177).

Helpers: none for the original work or this continuation; no swarm window.

The invocation block is committed at
`44f58eb2a1ce5e933b1546f3cdd82fbd43265978`. `scoped-checks.log` records passing
checks against that implementation (the earlier contract and static checks
cover unchanged files):

- Focused contract checks: seven tests passed.
- Web API contract reader: eight tests passed.
- Static checks: 132 tests passed, including fixture scan and the plan/decisions
  web API route-table reader.
- `cargo fmt --check`: exit 0. No Rust crate changed, so no crate-scoped clippy
  command is needed; the required pre-push hook separately runs its checks.
- `python3 -I tools/install/test_install.py`: seven contract tests visible in
  its log, then all nine outer tests passed. The same discovery assertion that
  failed before wiring now sees the named contract-test marker.

`failure-propagation.log` retains the final excerpt of the wrapper running the
actual current contract tests against the original accept-all checker in a
temporary copy. The child has 98 failed subtests (two more variants than the
original red commit); the installer wrapper itself fails and exits 1. This is
an intentional mutation, never a clean result.

Proof mapping:

| Ticket criterion | Contract/fixture evidence |
| --- | --- |
| Candidate, clock, waits/help, repository, seats, findings/gaps | Result schema, recording-complete example and missing/unknown/stale/missed-hour variants |
| Preserve work and reconcile effects after interruptions | Recovery schema, before/after inventories with unchanged content and operation ids; lost-reply, restart, rejected-update and lost-work variants |
| Refuse weak observations as readiness, approval or merge | Weak-evidence variants, browser-restart/tab-storage case and same-family reviewer case |
| No invalid or synthetic live success | Exact-code fixture tests, strict JSON negatives, non-live-pass and live-in-memory refusal tests |
| Existing owners and unresolved interfaces | Contract owner table and three gate definitions; producer/state mismatch variants |

The eleven interruption kinds define the shared interface; behavior for each
is for #2222/#2204 to implement and prove. The single shared web API addition
restates retention and recovery only. No route, authorization or storage
architecture is added. The schema and code accept only the documented shape;
cross-field evidence checks are intentionally additional to schema checks.

Checklist: strict parsing, exact codes, guard-negative cases, red-before-fix
history, failure propagation, independent expectations, owned paths and shared
sections checked. No dependency was added. Changelog disposition follows below.
All live, security/visual, spending, activation, cut-over and publication gates
remain separate. CI at the eventual PR head must still show `release:install`
running these seven tests before hand-back is complete.

## Continuation: retained-work hash kinds and push hold

The final checklist found that `work_item.content` allowed either length for
all kinds, so a 40-character value passed where the retained-work table requires
SHA-256. Existing fixtures only supplied the correct lengths. Two new variants
at `c4c66a8b8` use independently chosen incorrect literals for a setup-state
hash and a branch head. `red-work-hash-kinds.log` has four intended failures:
the exact-code assertions and their live-in-memory refusal assertions.
`e2c6d1f6ee91b610edbd219c77b0968cca6af0fe` constrains SHA-256 work hashes to
64 lowercase hex characters and Git commit/tree hashes to 40, using the existing
schema subset. No storage or authorization policy changes.

`final-scoped-checks.log` records the updated installer command (seven child
contract tests and nine outer tests pass), 13 affected fixture-scan tests, both
Git-index readers, and the required web typecheck/static checks. The earlier
web API contract tests, remaining static checks, format and clippy cover
unchanged Rust/source files. The fixture table now contains 54 variants.

The attempted push of `febcc05a48f7196f5c4d60947166fbe24a407613` was refused
by the installed pre-push hook. Format, workspace clippy and the classifier
checks passed. Its static-check command passed 130 tests, but two Git-index
readers failed because the copied tree has no Git metadata (`git ls-files
failed`, `git grep failed`). Both pass in the real checkout, including after
the final schema change. No bypass was used and no push succeeded.

Ticket question 6760141124 requests the orchestrator's ruling: either allow one
push after equivalent checks in the real Git checkout and route the hook fix
to its owner, or wait for that separately owned hook correction. The hook is
outside this ticket's paths and has not been edited. `needs-info` remains with
`ready-for-agent`. No ready PR exists and CI at the final head is unverified.
Resume on the same branch and preserve all commits; do not treat the earlier
`green` commit as a completed hand-back. After the push hold is resolved, update
the PR facts to the exact final head/tree and require CI's `release:install`
log to show the contract tests before review.


## Scoped-push disposition

The orchestrator answered the push-process question in ticket comment
6760189740, confirming the scoped-push Credits Rule already relayed by
6760123218. One push with `--no-verify` is authorized after affected checks and
the privacy/destination adapter pass; the hook itself remains unchanged. The
two Git-index readers already pass for the final implementation in the real
checkout (`final-scoped-checks.log`), so they were not repeated. Their recorded
code state is unchanged by the subsequent evidence-only commits.

`hook-copy-failure.log` retains the relevant copied-tree failure and successful
hook-step results. Its paths and process identifiers are omitted. This is an
execution-environment failure, not a clean hook run. The authorized push leaves
workspace checks and all required CI to PC CI. No Rust crate changed, so no new
workspace clippy run is required.

`changes/2200.md` is now owned by the standing ticket rule and records the
contract change without claiming a live outcome. This ticket and spec remain
unnumbered: no release or milestone has been selected here. The earlier
no-changelog disposition is superseded by this line.

The PR records the exact pushed head/tree and direct privacy/destination result.
Hand-back still requires passing CI at that head and the `release:install`
execution log showing the seven contract tests. Independent review, all live
and account authority, activation, spending, cut-over and publication remain
separate. No waiting process or helper is running.
