# Scoped validation

Implementation commit: `86078fb1f7af767c6dfa7189395dae5fabe300f8`.

- `python3 -B tools/release/test.py`: 191 fixture tests passed in 65.081 seconds. Includes P9, entry generation, source/staged privacy refusals, fake publisher, backfill, claims, scans, and regression orchestration. Cargo/npm/node/gh are recording fakes; no product or browser suite runs.
- `python3 -I .github/actions/changelog/test_check.py`: 13 passed. Its sparse clone has no private directory or private blobs and runs the action's checks with a fake repository.
- `python3 -B tools/release/review_mutants.py`: all 10 mutations killed.
- `python3 -B tools/release/review_guard_mutants.py --only allowlist-tree committed-mode`: both mutations killed.
- `cargo fmt --check`: passed with Rust 1.99.1.
- Changed Python files parse; `git diff --check` passes.
- Clippy: no Rust crate touched. Full workspace and browser suites left to CI.

Every changed path is under tools/release/. No dependency, live run, public
repository write, release, tag or publishing occurred. The changelog action and
workflow needed no edits: their existing no-private-input fixture passed.

The checker integrates tree privacy only. Public CI/pre-push own history and PR
text checks. Named literals and live release behavior remain unverified here.
