# O4 / P4 fixture proof

All endpoints, records and identifiers in these tests and logs are synthetic.
No live product reads or writes. No dependencies added.

Claims and owning CLI proofs in `b5_public.rs`:

- Public writes contain no thread ids: scan every GitHub body through start,
  review, re-check, merge and finished. The old lifecycle proofs allowed ids.
- Both legacy and public records preserve reviewer lineage across commits,
  using private B4 state or exact title/branch lookup. Existing tests covered
  legacy records only.
- A quiet review is a look; an in-place give-up closes the entire original
  span, including later activity. No output or tell reaches that reviewer.
- Duplicate title matches, mismatched branches, private-state disagreement,
  orphan activity and unreadable starts yield look, with no writes.
- Helper titles and other projects cannot identify a builder.

Red: `cargo test -p openwiz-tests --test fleet b5_tick::public -- --nocapture --test-threads=2`.
See `red-records.log`, plus the first writer-only failure in `red-writer.log`.
Expected leak: the old started comment exposes its planted synthetic id.
These fixture tests do not establish live behaviour. Full suites belong to CI.

Policy reads at base b1f8894c7ce485852c6562c195a7cb61d0a391c5:
AGENTS.md 2b9ae846b0dd4fcb93625ae1566b448f8de0e28a;
docs/agents/fleet.md 99aaafc6905d691c80ad413370bb4cb1f3a8f3bd;
docs/agents/helpers.md 9a8628b0deabf3ed320b856af2f0117723fab15b.
The spec's missing grill was read from its historical commit 4249a4b8.

Helper: scout, title/branch lookup APIs and fixture gaps, at the base above.
19 items checked by the builder: 18 used, one ignored (local JSON classification
is documented explicitly here instead of inferred), zero found wrong.
Archived before check: clean #1272: nothing changed but the writes you named
(branches 0, comments 2).
Snapshot retained in private helper-check state.
Completed window retained in private helper-check state.

Further red-first cases:
- `red-approval.log`: public decision/pointer approvals were rejected by the old reader.
- `red-legacy-span.log`: an explicit legacy give-up incorrectly retired a newer reviewer.
- `red-audit.log`: three independently identified gaps reproduced through the CLI:
  appended give-up left a re-check alias blocking fresh review; conflicting checked
  branches bypassed branch verification; quoted decision words below the heading
  were accepted. Each has an owning `p4_` regression in `b5_public.rs`.

A second helper audited code and the checklist at
0694ee56df22326aee9a278d7dcd6357de6a0e3a: three items used, none ignored or wrong.
All three were checked by the builder and reproduced red before their fixes.
The helper was archived before its check: clean #1272: nothing changed but the
writes you named (branches 0, comments 2).
Snapshot retained in private helper-check state.
Completed window retained in private helper-check state.

Compatibility details:
- The repository name selects legacy compatibility; the fake defaults to the
  contract's private repository name and uses only recording synthetic endpoints.
  Public cases use a separate synthetic repository, public approvals and public records.
- GitHub-only due cannot look up a thread-free identity. It conservatively wakes
  tick, which checks CloudRoom and remains idle for a verified running builder.
  Legacy idle/superseded-approval behavior retains explicit legacy fixtures.
- Rust spawns still send no title and retain B4 private state. A skill-started
  titled agent can be found without that state. An unresolved public manual
  replacement remains a look. There is no new private map format or dependency.
- Re-check suppression excludes every record belonging to a retired reviewer.
  Legacy give-ups retain their explicit target across newer spans.

Validation:
- `cargo test -p openwiz-tests --test fleet b5_ -- --test-threads=2`:
  97 affected cases; 84 passed initially, 13 failures corrected. Full initial
  output is in `affected-initial.log`. Only those failures plus the new
  GitHub-only due proof were retried: 14 passed (`affected-retry.log`).
- The final run selects every `p4_` proof plus legacy archive order, fallback
  replacement and superseded-approval due: 15 passed (`final-tests.log`).
  This includes all three audit reproductions and the additional legacy span bug.
- `cargo fmt --check`: passed, no output.
- `cargo clippy -p openwiz-cli --all-targets -- -D warnings`: passed.
- `cargo clippy -p openwiz-tests --test fleet -- -D warnings`: passed.
  Both logs are here. Build jobs and test threads were capped at two.
- Owned-path, shared-line and diff checks passed. No workspace or browser suite,
  watcher, live product call, publication, settings change or new dependency.
  CI runs the full set on the private PR; no CI result is claimed here.

## CI follow-up 1: service executor fixture

CI run 42358503027 failed only the service t4b manual/scheduled tick executor
case: its initial legacy started record is under an unknown repository, so the
public reader refuses it and correctly makes no archive comment. The old fixture
expects a second comment. The failed CI job's other target summaries were read;
web-build/web-test passed per the CI notification.

Scoped reproduction at dc578890ad4601c98f61af2632581979432f6b68:
`CARGO_BUILD_JOBS=2 cargo test -p openwiz-service --test t4b-tick executor::manual_and_scheduled_ticks_have_identical_records_and_dry_run_gates -- --exact --nocapture`
failed with the same 1-versus-2 comment count (`ci1-red.log`).

The smallest fix is fixture-only: make that record thread-free, give its archived
synthetic builder the exact ticket title, and supply the matching project/thread
list responses. `ci1-fixture-proposal.patch` is a proposed diff, not applied.
It requires tests/service/t4b_executor.rs and tests/service/t4b_fake.rs, outside
O4's owned paths. Scope extension requested on the ticket before editing either.
No production change, suite run, watcher or new helper. No new PR head pushed.

CI follow-up 1 resolved after the exact fixture-only scope extension:
https://github.com/jparker2006/ClosedWiz/issues/1272#issuecomment-6705183980.
Applied the prepared migration in tests/service/t4b_executor.rs and t4b_fake.rs.
The production guard and authentication/token assertions are unchanged.

- `CARGO_BUILD_JOBS=2 cargo test -p openwiz-service --test t4b-tick -- --test-threads=2`:
  11 passed, including the previously failing manual/scheduled executor case
  (`ci1-green.log`).
- `cargo fmt --check`: passed, no output.
- `CARGO_BUILD_JOBS=2 cargo clippy -p openwiz-service --test t4b-tick -- -D warnings`:
  passed (`ci1-clippy-service.log`).
- No new helper, full workspace/browser suite or CI watcher. Main conflict check
  after fetching a60793be2 passed; no merge needed. CI will check the new head.

## Review R1: private builder branch contradiction

Merged origin/main first as requested (merge 74d49e81e); policy blobs for
AGENTS.md, fleet.md and helpers.md remain the same as recorded above.
Review: https://github.com/jparker2006/ClosedWiz/pull/1849#issuecomment-6705388189.

Claim: a public checked branch must constrain a builder retained from private
B4 state before any CI repair send. A mismatch or unread workspace must yield
look and no writes. Earlier wrong-branch coverage removed B4 state, hiding the
fallback path. Extended the existing owning ambiguity table with stored,
anonymous and unread branch cases, using a completed review and failing CI.

Red at the merged head: the existing CLI fixture emits ci_failed and sends to
the contradictory private builder instead of look. Output in `r1-red.log`;
command: `CARGO_BUILD_JOBS=2 cargo test -p openwiz-tests --test fleet p4_ambiguous_titles_and_disagreement_never_choose_an_agent -- --nocapture`.
Fixture evidence only; no live run or new helper.

R1 fix: the single selected builder is checked against the public checked branch
before actionable builder facts are assembled, even if its B4 identity has no
matching title. Both selected-identity validation and title-candidate filtering
use `branch_matches`; selected mismatch/unread yields look, while an unrelated
matching-title candidate on another branch is still filtered out.

The fake now reports each spawned synthetic builder's own ticket branch rather
than falling back to ticket 10's branch for every builder. The existing planted
private-branch write-refusal case explicitly reports that same planted workspace
branch, preserving its writer-privacy claim after branch validation.
The positive title-filter case now runs with and without B4 state and includes
an unrelated matching title on another branch. No helper or dependency added.

R1 validation on the final source tree:
- `CARGO_BUILD_JOBS=2 cargo test -p openwiz-tests --test fleet p4_ -- --test-threads=2`:
  12 passed (`r1-green-public.log`), including all three new stored-builder cases
  and the unrelated-branch positive control with/without B4 state.
- `CARGO_BUILD_JOBS=2 cargo test -p openwiz-tests --test fleet b5_ -- --skip b5_tick::public --test-threads=2`:
  90 other affected B5 cases passed (`r1-green-b5.log`), without repeating P4.
- `cargo fmt --check`: passed, no output.
- `cargo clippy -p openwiz-cli --all-targets -- -D warnings`: passed.
- `cargo clippy -p openwiz-tests --test fleet -- -D warnings`: passed.
  Clippy logs are `r1-clippy-cli.log` and `r1-clippy-tests.log`.
No full workspace/browser suite or watcher. No new helper or dependency.
