# CI selection record fixtures

Synthetic plans for the CI selection record, [`openwiz.ci-selection.v1`](../../contracts/ci-selection.v1.md) (#1405). `ci/escapes/test.py` checks that every file in `valid/` matches [the schema](../../contracts/ci-selection.v1.schema.json) and keeps the contract's rules beyond it, and that every case in [`invalid/cases.json`](invalid/cases.json) is refused, for its reason. Every run id, commit, pull request number and path is synthetic; the lists of tests are short samples (a real plan names every test). They prove the record's shape, never a live run.

Later tickets read them: X5 (#1262) writes plans of these shapes, X6 (#1264) runs the escape finder's tests on them, and X8 (#1266) balances the Rust lane's `rust:test:` and `rust:lib:` ids.

Run: `python3 -I ci/escapes/test.py Plans`.

## Valid

Each full-run file is named for the reason that selects everything; together they hold every reason code, every event and every pull request action.

| File | The plan |
| --- | --- |
| `valid/full-push-main.json` | A push to `main`: `push_main`, no diff read |
| `valid/full-nightly.json` | The nightly run: `nightly`, no base, no diff read |
| `valid/full-rerun.json` | A pull request's second attempt: `rerun`, kept as `ci-selection-2` |
| `valid/full-release-branch.json` | A pull request into `release-0.0.14`: `release_branch` |
| `valid/full-merge-group.json` | A merge group: `merge_group`, no pull request number |
| `valid/full-unknown-path.json` | A pull request with a path the map doesn't know: `unknown_path`, naming it |
| `valid/full-ci-change.json` | A pull request that changes the CI workflow: `ci_change`, naming it |
| `valid/full-empty-diff.json` | A pull request whose diff is empty: `empty_diff` |
| `valid/full-failed-diff.json` | A pull request whose diff could not be read: `failed_diff`, with `diff.error` |
| `valid/full-selector-error.json` | A pull request whose selector failed: `selector_error`, with its error |
| `valid/full-ready-for-review.json` | A pull request just marked ready for review: `ready_for_review` |
| `valid/full-stale-event.json` | A pull request whose event's base is not its live base (retargeted): `stale_event`, no diff read |
| `valid/full-doubts-together.json` | A third attempt into a release branch, with a CI change and an unknown path: four reasons at once |
| `valid/selected-skill-only.json` | A skill-only pull request, reopened: the always-run set and `launch-fleet`'s lane run; every other lane is skipped, with its reason |
| `valid/selected-mixed.json` | A mixed pull request (a server file and a `plan-graph` script): the Rust lane runs two tests and skips three, each with its reason; `plan-graph`'s lane runs one part and skips the other |
| `valid/selected-docs-only.json` | A docs-only pull request: only the always-run set runs |
| `valid/selected-before-rerun.json` | The first attempt of `full-rerun`'s run: a selected plan, for the reads' stale-plan case |

## Invalid

[`invalid/cases.json`](invalid/cases.json) holds the invalid plans as one table of cases (#1485), each named for the file it once was. Each case is a valid plan with one planted break: its `base` (a file in `valid/`), its edit, and `why`, the reason it is refused. "Schema" means the schema refuses it; "Rule n" means the schema accepts it and the contract's rule n refuses it.

An edit is JSON pointers: `drop` removes each one's member, then `set` writes each one's value (a last `-` appends to a list). [`invalid/expand.py`](invalid/expand.py)'s `plan(name)` gives a case's plan as the text a run would keep, two-space indented, as `valid/` is. A `raw` case can't be a parsed plan plus one edit, so it stays a file beside the table: `invalid/duplicate-key.json` (Rule 1: a lane's `decision` written twice). `ci/escapes/test.py` refuses any other file there.

## Reads

How X6 (#1264) finds a merged pull request's plan, as the contract's "Reading a merged pull request's plan" says, on synthetic runs. Each case is a pull request number, its head at merge, the CI runs GitHub would list (each run's `id`, `workflow`, `event`, `head_sha`, the `pull_requests` GitHub associates with it, and each attempt's artifacts, named for the fixture file each holds) and the `expected` answer: the run and attempt whose plan holds, or `"unknown"`. The check runs the contract's lookup on each one; X6's reader must give the same answers.

| File | The case |
| --- | --- |
| `reads/one-run.json` | One run of the pull request: its plan |
| `reads/shared-head-newer-run-of-another-pr.json` | Two pull requests share the head commit, and the other's run is newer: still this pull request's own run |
| `reads/shared-head-newer-run-association-missing.json` | As above, but the newer same-head run has no `pull_requests` at all, so it might be this pull request's: unknown, never the older plan |
| `reads/shared-head-newer-run-association-null.json` | The same with `pull_requests` `null`: unknown |
| `reads/shared-head-newer-run-empty-association.json` | The newer same-head run's `pull_requests` is a readable empty list, so it isn't this pull request's: the older run's plan |
| `reads/rerun-last-attempt.json` | A rerun: the last attempt's plan |
| `reads/stale-plan-in-rerun-artifact.json` | The rerun's `ci-selection-2` holds the first attempt's plan: unknown |
| `reads/newest-run-plan-missing.json` | The newest run has no plan, an older one has: unknown, never the older plan |
| `reads/plan-refused.json` | The plan breaks a rule: unknown |
| `reads/plan-of-another-run.json` | The artifact holds another run's plan for the same pull request and head: unknown |
| `reads/no-associated-run.json` | A run at that head that GitHub associates with no pull request: unknown |
| `reads/other-workflow-or-event.json` | Runs of another workflow, or of a push: unknown |
| `reads/no-run.json` | No run at all: unknown |
