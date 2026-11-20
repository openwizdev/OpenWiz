# Selector escapes

`escapes.py` finds **selector escapes** (#1264, X6 of spec #1256, H5): a test that a merged pull request's CI plan skipped, and that then fails on a full run of CI on `main`. Each one is a selector bug. Its fix names the missing reader in the path table (`classify.sh` in [`.github/actions/docs-only/`](../../.github/actions/docs-only/classify.sh), #1486), with a planted case.

```sh
python3 -I ci/escapes/escapes.py find --run <CI run id> --attempt <k> [--summary FILE]
python3 -I ci/escapes/test.py     # its tests: the contract's fixtures, synthetic runs and a fake gh
```

Python 3 (standard library only) and `gh`. [`.github/workflows/ci-escapes.yml`](../../.github/workflows/ci-escapes.yml) runs `find` once for each failed attempt of a push or nightly run of CI on `main`, with read access plus `issues: write`. It runs `main`'s own copy of the finder, never a pull request's code. On a pull request that touches the finder or the plan's contract, it runs the tests instead.

## What it does

1. **The failed attempt:** it reads that attempt itself (`actions/runs/<id>/attempts/<k>`), never the run's later state. It must be a completed, failed `push` or `schedule` attempt of `.github/workflows/ci.yml` on `main`. Anything else exits 2, after one read.
2. **Its failing tests,** from that attempt's failed jobs. Only the `Run cargo test --workspace` step names tests, using `ci/rust-tests.sh`'s authenticated control lines: `rust-tests-frame:<nonce> <control>`. The wrapper generates a fresh 256-bit random nonce, clears any inherited value, and never exports it or passes it to an invocation. Its begin/end markers, invocation headers, exit statuses, timings and peak-memory trailer all carry that nonce. Each control line starts on a fresh line even after unterminated output.

   The finder reads exactly one complete run and reconciles every authenticated header and status in the wrapper's order. It scans the whole job for conflicting frames; GitHub groups and public `rust-tests:` labels in invocation output never define a boundary. Missing, malformed, foreign, duplicate or truncated frames make the whole log unknown with no test ids. Legacy logs without nonce framing are also unknown.

   A cargo hint (`to rerun pass -p <package> --lib` / `--test <target>`) counts only inside an authenticated section whose own exit status failed. In the `crates` section only a `--lib` hint counts, and in a target's section only `--test <that target>`. A counted hint becomes `rust:lib:<package>` or `rust:test:<target>`, as the [contract's test ids](../../contracts/ci-selection.v1.md#test-ids) say. A passing section's hints, and the output of the alongside suite (the skills' tests), never count. Any other failure is unknown:
   - another failed step, or a cancelled job;
   - the suite beside it failing;
   - a doc test;
   - a hint for another target;
   - a failed section with no hint;
   - output that isn't in the wrapper's authenticated shape;
   - a log that can't be read (by `gh`, or by `ci/rust-tests.sh`), that is cut short, or that names no test.
3. **The pull requests merged since the last green full run:** the newest push or nightly run of CI on `main`, by creation, with an attempt that succeeded and ended (its last job's completion) before this failed attempt started. A run that goes green later proves nothing about this failure. Its attempts are read newest first. For the failed run itself, only the attempts before this one count. If no such run is found, the result is unknown. It reads `compare/<green head>...<failed head>`, walks `main`'s first parents and takes each merge commit's one merged pull request.
4. **Each one's plan,** exactly as the contract's ["Reading a merged pull request's plan"](../../contracts/ci-selection.v1.md#where-a-run-keeps-its-plan) says. The plan is checked against the schema and rules 1 to 9, the same verdicts `tests/checks/ci_selection.rs` gives every fixture in [`ci/selection/`](../selection/README.md), and the same answers for its 13 read cases.
5. **The verdict, per failing test.** A plan that skipped it (the test, or its whole lane) makes an **escape**. A test every plan ran is an ordinary red `main`: not an escape. A plan it can't read or bind, or a plan that names no such test, makes it **unknown**.
6. **The report:** one issue per escape, labelled `needs-triage`. Each issue names the test, the pull request, the plan's skip reason and the plan's changed paths (the path table missed a reader of one of them). Its first line is `<!-- openwiz.ci-escape.v1 run=<CI run> attempt=<k> pr=<n> test=<id> -->`, naming the attempt that found it; only the first line counts, as a path quoted below it could hold the same text. Before opening one, the finder reads the issues updated since the last green run. If an issue that `github-actions[bot]` opened already has that pull request and test, the finder opens nothing new, so each escape is reported once. Paths and reasons are put in code spans, so they can't mention anyone or add markup.
7. **The summary** goes to the run page and stdout, starting with `Result: escapes (n)`, `Result: none` or `Result: unknown`. When anything is unknown, the run fails (exit 1), so it is never read as "no escape". Escapes it did find are still reported.

The issues are the escape record. The CI bench's daily count of them (`bench.py escapes`) retired with the bench (#827); the war room's collector does not count escapes.

## Seams

- **X5 (#1262):** `TEST_STEPS` in `escapes.py`. When X5's lanes name their failing tests the way cargo does, their test steps join this set. Until then, every other step's failure is unknown. Until X5 keeps plans, every pull request's plan is missing too, so every failed full run is unknown.

## Gaps

- Never run live. `workflow_run` only fires from `main`'s copy after merge. These are proven on synthetic runs only, never observed: the issue writes, GitHub's answers to these reads (`compare`, `commits/<sha>/pulls`, the artifacts list and zip), and the run name the bench binds by.
- Without `--no-fail-fast`, cargo stops at the first failing target. Tests after it are not judged until a later run.
- Only `ci/rust-tests.sh`'s current output is read. When its lines change, the finder's tests (which run the real script on a fake cargo, on both paths) fail first.
- A first-parent commit on `main` with no merged pull request (a direct push) makes the run unknown.
- Runs are serialised (`concurrency: ci-escapes`). GitHub keeps one pending run and cancels an older pending one, so the bench shows that CI run's count as unknown.
- A deleted escape issue is reported again by the next red full run.
