# CI selection record fixtures

Synthetic plans for the CI selection record, [`openwiz.ci-selection.v1`](../../contracts/ci-selection.v1.md) (#1405). `tests/checks/ci_selection.rs` checks that every file in `valid/` matches [the schema](../../contracts/ci-selection.v1.schema.json) and keeps the contract's rules beyond it, and that every file in `invalid/` is refused, for the reason below. Every run id, commit, pull request number and path is synthetic; the lists of tests are short samples (a real plan names every test). They prove the record's shape, never a live run.

Later tickets read them: X5 (#1262) writes plans of these shapes, X6 (#1264) runs the escape finder's tests on them, and X8 (#1266) balances the Rust lane's `rust:test:` and `rust:lib:` ids.

Run: `cargo test -p openwiz-tests --test checks ci_selection`.

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

Each file is a valid plan with one planted break. "Schema" means the schema refuses it; "Rule n" means the schema accepts it and the contract's rule n refuses it.

| File | What it breaks |
| --- | --- |
| `invalid/action-missing.json` | Rule 3: a pull request run without its action |
| `invalid/action-on-push.json` | Rule 3: a push with a pull request action |
| `invalid/always-skipped.json` | Schema: the always-run lane is skipped |
| `invalid/base-all-zeros.json` | Rule 3: an all-zero base commit |
| `invalid/base-branch-other.json` | Rule 3: a run into a branch other than `main` or `release-*` |
| `invalid/diff-read-without-paths.json` | Schema: a read diff with no path |
| `invalid/duplicate-key.json` | Rule 1: a lane's `decision` written twice |
| `invalid/empty-diff-reason-on-read-diff.json` | Rule 5: `empty_diff` with a diff that was read |
| `invalid/empty-diff-unnamed.json` | Rule 5: an empty diff without `empty_diff` |
| `invalid/extra-field.json` | Schema: a field the record doesn't have |
| `invalid/failed-diff-unnamed.json` | Rule 5: a failed diff without `failed_diff` |
| `invalid/full-lane-skipped.json` | Schema: a full run skips a lane |
| `invalid/full-reason-unknown.json` | Schema: a reason code the contract doesn't have |
| `invalid/full-test-skipped.json` | Schema: a full run skips a test |
| `invalid/full-web-export-skipped.json` | Schema: a full run skips the web export |
| `invalid/full-without-reason.json` | Schema: a full run with no reason |
| `invalid/head-not-a-sha.json` | Schema: a head that is not a commit |
| `invalid/lane-extra.json` | Schema: a lane the contract doesn't have |
| `invalid/lane-missing.json` | Schema: the web lane left out |
| `invalid/lane-unknown-decision.json` | Schema: a decision other than run or skip |
| `invalid/nightly-on-pull-request.json` | Rule 4: `nightly` on a pull request |
| `invalid/not-read-without-event.json` | Rule 5: a diff not read with no event that selects everything |
| `invalid/pull-request-number-missing.json` | Rule 3: a pull request run without its number |
| `invalid/pull-request-number-on-push.json` | Rule 3: a push with a pull request number |
| `invalid/pull-request-without-base.json` | Rule 3: a pull request run without a base |
| `invalid/push-main-unnamed.json` | Rule 4: a push to `main` without `push_main` (and a `merge_group` that didn't happen) |
| `invalid/push-to-release.json` | Rule 4: a push into a release branch |
| `invalid/ready-for-review-on-synchronize.json` | Rule 4: `ready_for_review` on a `synchronize` run |
| `invalid/ready-for-review-unnamed.json` | Rule 4: a `ready_for_review` run without `ready_for_review` |
| `invalid/reason-twice.json` | Rule 9: `unknown_path` given twice |
| `invalid/release-branch-unnamed.json` | Rule 4: a run into a release branch without `release_branch` |
| `invalid/rerun-on-first-attempt.json` | Rule 4: `rerun` on a first attempt |
| `invalid/rerun-unnamed.json` | Rule 4: a second attempt without `rerun` |
| `invalid/run-without-tests.json` | Schema: a running lane with no test |
| `invalid/rust-test-unknown-kind.json` | Rule 7: a Rust test id of a kind the contract doesn't have |
| `invalid/selected-empty-diff.json` | Schema: a selected run without a read diff |
| `invalid/selected-on-push.json` | Schema: a selected push |
| `invalid/selected-ready-for-review.json` | Schema: a selected run just marked ready for review |
| `invalid/selected-release-branch.json` | Schema: a selected run into a release branch |
| `invalid/selected-rerun.json` | Schema: a selected second attempt |
| `invalid/skill-test-of-another-skill.json` | Rule 7: a skill lane runs another skill's test |
| `invalid/skill-twice.json` | Rule 8: one skill with two lanes |
| `invalid/skip-blank-reason.json` | Schema: a skipped lane with an empty reason |
| `invalid/skip-without-reason.json` | Schema: a skipped lane with no reason |
| `invalid/skipped-test-without-reason.json` | Schema: a skipped test with no reason |
| `invalid/store-wrong-attempt.json` | Rule 2: a second attempt's plan kept as `ci-selection-1` |
| `invalid/store-wrong-file.json` | Schema: the plan kept in another file |
| `invalid/test-in-another-lane.json` | Rule 7: a Rust test in the web lane |
| `invalid/test-twice.json` | Rule 6: one test both run and skipped |
| `invalid/test-without-name.json` | Rule 7: a test id with an empty name |
| `invalid/unknown-path-not-in-diff.json` | Rule 5: `unknown_path` names a path that didn't change |
| `invalid/unknown-path-without-diff.json` | Rule 5: `unknown_path` with no diff read |
| `invalid/web-export-skip-without-reason.json` | Schema: the web export skipped with no reason |
| `invalid/wrong-schema.json` | Schema: another version's name |

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
