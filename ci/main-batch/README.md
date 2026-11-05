# Combined-main shadow observation (C7)

The [C6 contract](../../contracts/ci-main-batch.v1.md) is authoritative.
The implementation adds no admission mechanism. Main full per-push and nightly
runs, every required check, independent review and M1 remain mandatory.

Two finite stages implement the invocation disposition on #2314,
comment 6777332857:

1. After the existing `run.py finish` boundary, `shadow.py capture` saves exact
   plan text, the existing full-work receipts, the actual event binding and Rust
   matrix shares. It rechecks finish inputs, but always reports incomplete:
   `ci` and its legacy bridge have not yet reached terminal results. The
   workflow uploads only `observation.json` as `main-shadow-<attempt>`.
2. The separately invoked `shadow.py reconcile` authenticates the packet through
   the existing `gh api` GET transport and that current attempt's artifact. It
   compares an independently acquired C6 context with fresh repository, merge/PR,
   current execution, job/matrix, toolkit and required-check facts. It validates
   C6 coverage and repeats reads before advancing private local coverage. No
   automated completion job or polling is installed. Live invocation requires
   C11's separate authority; preparation and fixture passes grant none.

Both appended workflow steps are non-authoritative: a capture/upload failure
leaves the existing full-work result unchanged and coverage incomplete. The
upload runs only after successful capture; no artifact can imply terminal
success. The offline proof evaluates both actual workflow conditions for main,
merge-group, nightly, PR and release contexts, including finish/capture failure.

The standalone entrypoint requires a clean checkout at the combined tested
head, and generates its full inventory from that candidate's trusted planner.
It refuses an undersized self-consistent plan, an old attempt, incomplete pages,
unknown associations, missing/expired artifacts, a missing matrix member,
pending/failed/cancelled checks, changed required-check identities or overlapping
checkpoint history. This bounded version recognizes ordinary two-parent main
merges; other merge shapes or unsupported protections remain unknown. It never
guesses membership from the newest successful run. A later B→C push can cover
pending A→C only with both ordered members retained and a complete result at C.

Private local state retains the checkpoint, pending members and last complete
C6 document. It uses a nonblocking local lock and atomic fsync/replace. It never
locks, admits or changes GitHub work. Replays independently revalidate facts;
partial results retain the covered checkpoint and pending membership. A failed
state write or busy lock is a failure, never a successful observation. Archive
the context, packet and raw paginated API evidence privately under C11. Publish
only sanitized counts and result/private-record pointers.

The report includes a C4-compatible batch identity and job-queue summary. Its
actual push-to-required duration and whole bill stay unknown without C4's
independent evidence. Workflow creation is not push time; no speed/spend target
or live success is established by these fixtures. A separate current required
workflow is included in the observed job clocks. Nightly is separate evidence,
never a member of a push batch or inferred from a batch green.

Run `python3 -I ci/main-batch/test_shadow.py`. This includes the offline
`tools/ci2-live/test_batch_kit.py` tests and is the single command registered as
`release:ci2-batch-shadow` in the existing planner/executor. Red logs precede
implementation in Git. `fixtures/shadow/github.json` and the reused C6 fixtures
are synthetic, unobserved API assumptions with a deliberately small inventory;
they do not describe any real account or enumerate today's production tests.
`ci-before.sha256` pins the unchanged workflow outside C7's appended steps.
Their `synthetic_assumptions` are ordinary two-parent merges, GitHub Actions
application identity, representative required checks, complete current REST
responses, toolkit steps and two Rust shares; all clocks/runners/IDs are made up.
The attempt-specific jobs endpoint supplies the attempt binding even on API
versions whose job objects omit `run_attempt`; an exposed conflicting attempt
is refused. Unknown job-created times remain missing timing evidence.

The [candidate-bound C11 kit](../../tools/ci2-live/batch-kit.md) names the finite
later invocation, its proposed read/resource ceilings, authorization, separate
nightly receipt, stop conditions and rollback prerequisites. Nothing here opens
the C12 switch gate, changes a permission, installs a controller or authorizes a
live experiment. See the official GitHub [workflow jobs](https://docs.github.com/en/rest/actions/workflow-jobs),
[workflow runs](https://docs.github.com/en/rest/actions/workflow-runs) and
[artifact](https://docs.github.com/en/rest/actions/artifacts) API references;
successful documentation checks are not live endpoint observations.
