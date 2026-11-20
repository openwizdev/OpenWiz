# The test-value kit (#803)

The kit every group of the test-value campaign (spec #787) uses: the ledger
form, what a group's pull request carries, and the coverage method with its
script, `measure.py`. This README is the contract; a group that needs it
changed asks on its ticket.

The bar is the test rule (#687): a test protects a supported behaviour, a
contract others rely on or a safety invariant, adds something not already
covered, and names the bug it catches. Never mock-returns-stub, source
mirroring, compiler re-checks, quota tests or unreachable cases.

For cleanup wave #1141 (DL4), keep a test only for a **user-visible
behaviour**, a **contract another repository relies on**, or a **safety
gate** for privacy, security, data loss, money or release. Name the
reason and the specific behaviour, contract or gate in the ledger.

Measure test lines before and after each pass:

```sh
python3 -I tools/test-value/count.py BASE_COMMIT
python3 -I tools/test-value/count.py HEAD_COMMIT
```

The counter uses the budget guard's file classifier. It reports test
lines per area, their sum, and their percentage of all tracked text lines
at the requested commit (default `HEAD`). Git counts blank lines and a
final line without a newline, and excludes binary content. Use a Git
version that supports `--attr-source` so the requested commit supplies
the file attributes. Inline Rust test modules in otherwise unclassified
source files contribute only to the whole-tree total. A fixture contributes
to the test count when its path matches the same classifier.

Compare the rows your pass owns. The [CW1 baseline](evidence/cw1/baseline.json)
records the starting commit and totals for CW19's wave comparison.

## The pull request test-code budget (#1139)

Every pull request may add **400 net test lines** without an allowance:
added lines minus deleted lines, from the PR's common ancestor with its base
to its head. Product changes and evidence outside test paths do not count.
The counted paths are `tests/**`, `crates/*/tests/**`, `**/test_*.py`,
`**/*_test.py`, `**/*.test.mjs`, `**/*.test.ts`, `**/*.test.tsx` and
`**/__tests__/**` (including root-level matching files/folders); fixtures
and evidence count only where they sit under those paths.

Offset growth with deletions, or put one standalone line in the PR description:

```text
Test budget allowance: <N> lines. Why: <reason>
```

`N` is a nonnegative integer covering at least the overage above 400, not
necessarily the total growth: 500 net lines needs at least 100. The reason
must be nonempty; the ordinary reviewer judges whether it is justified.
An insufficient, malformed or duplicate allowance fails. Keep this line
separate from the PR's numbered Rulings section.

The single PR-only step in `ci.yml` runs the synthetic proofs and
`budget.py`; merge groups, pushes and schedules skip it. It reads Git and
the PR event's description, never product data or external services. Missing
or unreadable revisions, history, diffs or descriptions fail closed with a
message; binary test diffs refuse because their line growth is uncountable.
A GitHub null body is a readable empty description. Renames count both sides
by their paths; dirty working-tree files cannot affect the result.

```sh
python3 -I tools/test-value/test_budget.py
python3 -I tools/test-value/budget.py --base=BASE_SHA --head=HEAD_SHA --event=PR_EVENT_JSON
```

## The ledger

One row for **every test the group touches or reviews**, in the group's
evidence folder as `tools/test-value/evidence/cw<N>/ledger.md` (or
`tv<N>/ledger.md` for spec #787). A test is
named `path::name`: its file from the repository root and its function, with
any module path inside the file (`tests/fleet/a4_board.rs::board::orders_by_spec`).

| Test | Outcome | Keep reason | Keeper or gone reason | Catches |
| --- | --- | --- | --- | --- |
| `tests/fleet/board.rs::orders_by_spec` | kept | user-visible behaviour: the board displays specs in number order | itself | a board that displays specs in input order |
| `tests/fleet/board.rs::sorts_reverse_input` | deleted | | `tests/fleet/board.rs::orders_by_spec` | |
| `tests/fleet/fake.rs::help_mentions_fixture` | deleted | | internal fixture help text serves no user-visible behaviour, cross-repository contract or safety gate | |

(Synthetic rows: they show the form, not real tests.)

The four outcomes, and what each row must carry:

- **kept:** the test stays where it is. Give its keep reason, name
  `itself` as keeper and describe the bug in one line.
- **moved:** the test is kept at a new place, normally its crate's own
  `tests/` folder. Give its keep reason, new `path::name` and the bug.
- **merged:** its case now lives in another test, which checks it. Keeper:
  that test's `path::name`. Give its keep reason and the bug it catches.
- **deleted:** name an existing test by `path::name` that catches the
  same bug at the pull request's head, or explain why the tested behaviour
  falls outside all three keep reasons. If the behaviour was removed, name
  it and cite the issue, pull request or commit. Leave Keep reason and
  Catches empty.

A keeper is checked, not assumed: the reviewer can break the code the
deleted test guarded and see the keeper fail. "Covered elsewhere" without a
`path::name` is not a keeper.

## What a group's pull request carries

1. **The ledger**, as above, with a row for every test in the group.
2. **Coverage before and after**: `measure.py`'s two results (the JSON
   files, in the group's evidence folder) and the `compare` output in the
   description.
3. **Every drop explained**: each crate on the `drops:` line names the
   behaviour that no longer exists and where it went. A drop that can't be
   explained that way undoes the deletion that caused it.
4. **Size, count and time**: the `compare` lines for tests, size and seconds.
5. **Per new test**, `catches: <the bug>`; or `no new test: <why>`.
6. **Where tests live**: each kept test that exercises one crate moves to
   that crate's `tests/` folder; each one that stays in `tests/` has a
   one-line reason in its ledger row's Catches cell or beside the table.

## The coverage method

```sh
python3 -I tools/test-value/measure.py [--json FILE] TARGET...   # one group
python3 -I tools/test-value/measure.py --all --json-dir DIR       # each target of tests/, the baseline
python3 -I tools/test-value/measure.py compare BEFORE.json AFTER.json
python3 -I tools/test-value/test_measure.py                       # the script's own tests
```

`TARGET` is a `[[test]]` name of `openwiz-tests` (`fleet`) or
`PACKAGE:NAME` for a target in a crate's own `tests/` folder
(`openwiz-cli:fleet_detail`). A group's targets are measured together, in one
coverage report, so a group that moves tests lists its old and new targets
in the after run.

- **The tool:** `cargo-llvm-cov` 0.9.1 (LLVM source-based coverage), with
  rustup's `llvm-tools-preview` component. The script installs both itself
  when missing, into `${XDG_CACHE_HOME:-$HOME/.cache}/openwiz-test-value`; it
  is never a project dependency and touches no `Cargo.toml` or lock file. It
  needs `rustup`, Rust 1.99.1 and network access the first time.
- **The same toolchain:** each result records `rustc --version` and
  `cargo llvm-cov --version`; `compare` refuses two results whose toolchains
  differ.
- **The run:** the builds CI runs before its tests (`cargo build --workspace
  --bins`, and `ci/rust-tests.sh`'s fixture release `openwiz`), plus the debug
  fixture examples, then each
  target under `cargo test --locked -p PACKAGE --test NAME`, instrumented in
  its own folder, `target/test-value-cov/`. Binaries the tests run as child
  processes are instrumented too, so their lines count. A child a test starts
  with a cleared environment writes its raw profile into its working folder
  instead; the script moves each such new profile into the coverage folder
  after the target's run, so it counts too, and leaves any profile that was
  there before the run. A failed test stops the measure: a red run is never a
  number.
- **Prerequisites,** as for the tests themselves (`AGENTS.md`): zsh and a
  user other than root.
- **Line coverage** per workspace crate: covered and total lines from
  `cargo llvm-cov report --json --summary-only`, product sources only. The
  whole `openwiz-tests` package, and every crate's `tests/`, `examples/` and
  `benches/`, are test code and never count, so moving a test changes no
  number. Dependencies and the standard library never count. A crate's
  total depends on which of its functions the measured binaries contain, so
  it differs between targets: compare a group's before with its own after,
  never one target's numbers with another's, and never add targets' numbers
  up (measure a group's targets together instead).
- **Test count:** passed plus ignored, from every libtest result line.
- **Size:** the group's own Rust sources: every `.rs` file in this tree
  (outside `target/`) that rustc's dep-info for one of its test binaries
  lists, so a target's modules count whatever its entrypoint is called or
  where they live, and a file its targets share counts once; files, bytes
  and lines. Files the compiler never reads (another file in the folder, a
  module no `mod` line names, a fixture) are not size. A dep-info with no
  such file, or one missing the target's own entrypoint, stops the measure.
- **Run time:** the plain, uninstrumented `cargo test` of each target after
  its build, as CI runs it, in seconds. It is the one number that varies
  between runs, so it is reported, but outside the repeat check below; compare
  times only from the same machine.
- **Before and after:** measure the pull request's base commit in a separate
  worktree (`git worktree add ../before <base>`), never beside another Cargo
  command in the same checkout (`docs/agents/fleet.md`), then the head, on the
  same machine.
- **Repeatable:** on an unchanged tree, two runs print the same coverage,
  test count and size. The baseline below was measured twice to show it.
  The known exceptions are race branches whose execution depends on timing,
  1 or 2 lines under `loops`. A group whose drop is confined to those lines
  reruns its measure before calling the drop real (#892).

## The baseline

[`evidence/baseline/`](evidence/baseline/) holds one result for
every test target in `tests/`, measured before any group changed anything:
the campaign's starting numbers. Each group still measures its own before
at its pull request's base, since earlier groups move the numbers.

`unread_fixtures.py` and its test, when present, are TV2's (#804), not this kit's.
