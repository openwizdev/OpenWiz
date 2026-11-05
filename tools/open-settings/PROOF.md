# #1280 proof plan

## #2408: plan-bound, journalled apply with recovery

G10 from rehearsal run 1 (review R4): `--apply` re-planned on its own, could
not be bound to a reviewed plan, and kept no record of a completed write, so
the cut-over runbook's settings step had no executable way back.

Claims (all fixture claims on the fake `gh`; none is a live result):

- AC1 / binding: apply without a saved plan, digest and new journal refuses.
  With them, it refuses before its first write on drift in any planned object
  (each of the five kinds), a changed, truncated or empty plan, a digest
  mismatch, a plan for another repository, a set runner variable and an
  existing journal. Owning tests: `test_apply_without_a_reviewed_plan_refuses`,
  `test_apply_refuses_before_its_first_write`; the plan's content:
  `test_saved_plan_records_every_write_with_its_prior_state`.
- AC2 / recovery: the fake fails the third of five writes (update, create,
  update, create, update), once before and once after it lands; separately the
  fake kills the tool after its fourth write lands, leaving an intent with no
  completion. Recovery restores the updated objects, deletes only the journal's
  creations, reads back the exact prior state, and a second run makes no write.
  A journal that does not match its plan refuses with no write. Owning tests:
  `test_failed_third_write_is_recovered_exactly_and_once`,
  `test_crash_after_an_intent_record_is_recovered`,
  `test_recovery_refuses_a_journal_that_does_not_match_its_plan`.
- AC3 / journal: every record is a complete line, written and synced before
  the next step (the kill test reads the records written before it); the
  journal and plan pass the shared privacy check with a literal list, carry no
  token from the environment, and are owner-only. The dry read writes no file
  and keeps its report keys; every earlier test still passes through the new
  two-step apply. Owning tests:
  `test_journal_is_complete_on_success_and_holds_no_secret_or_literal`,
  `test_dry_read_writes_no_file_and_its_report_is_unchanged`, and the 22
  existing tests.

### #2408 red run (before the change)

The current tool, on the fake `gh` failing its third write, applies without
any plan binding and leaves no record (synthetic world, scratch directory):

```text
$ python3 -I tools/open-settings/settings.py --apply
open-settings: PUT repos/openwizdev/openwiz/actions/permissions/fork-pr-contributor-approval: gh exited 1; stopped, no retry. Earlier writes may remain; rerun a read before any new apply.
exit 1
writes: [('POST', 'rulesets'), ('POST', 'rulesets'), ('PUT', 'actions/permissions/fork-pr-contributor-approval')]
files left: gh, state.json (no plan, no journal)
```

The new proofs, before the change:

```text
$ python3 -I tools/open-settings/test_settings.py Settings.test_apply_without_a_reviewed_plan_refuses
FAIL: test_apply_without_a_reviewed_plan_refuses (args=('--apply',))
AssertionError: 0 == 0   (exit 0: the bare apply wrote all five settings)
$ python3 -I tools/open-settings/test_settings.py Settings.test_failed_third_write_is_recovered_exactly_and_once
AssertionError: 2 != 0 : usage: settings.py [-h] [--apply] [--literals LITERALS] ...
FAILED (failures=2)   (no plan file can be saved, so nothing is recoverable)
$ python3 -I tools/open-settings/test_settings.py
Ran 30 tests in 11.243s
FAILED (failures=116, errors=1)
```

### #2408 review round 1 red run (at 2f82826be)

Each regression, run before its fix:

```text
$ python3 -I tools/open-settings/test_settings.py Settings.test_recovery_ignores_a_record_cut_inside_a_character
AssertionError: 1 != 0 : open-settings: journal is unreadable (UnicodeDecodeError). ...   (R1)
$ python3 -I tools/open-settings/test_settings.py Settings.test_private_literal_in_a_prior_object_refuses_before_it_is_saved
FAIL (key='labels') / FAIL (key='milestones'): AssertionError: 0 != 1   (R2: plan saved with the literal)
$ python3 -I tools/open-settings/test_settings.py Settings.test_null_descriptions_are_restored_exactly
AssertionError: '' is not None   (R3: null prior saved as empty text)
```

### #2408 review round 1 fixes

- R1: the journal is read as bytes; an unterminated tail is dropped before
  each complete record is strictly decoded.
  `test_recovery_ignores_a_record_cut_inside_a_character` (also: invalid UTF-8
  in a complete record refuses).
- R2: plan actions (values and priors) are privacy-checked before a plan is
  saved or applied; read-back text not already checked is checked before its
  completion record. `test_private_literal_in_a_prior_object_refuses_before_it_is_saved`,
  `test_private_literal_in_a_read_back_is_never_journalled` (red before the
  fix: `AssertionError: 0 != 1`, the apply succeeded with the literal journalled).
- R3: label and milestone readers return raw rows; `normal()` gives the
  comparison view. `test_null_descriptions_are_restored_exactly`.

```text
$ python3 -I tools/open-settings/test_settings.py
Ran 34 tests in 103.405s
OK
```

### #2408 scoped results (after the change)

```text
$ python3 -I tools/open-settings/test_settings.py
Ran 30 tests in 93.225s
OK
```

All 22 earlier tests pass unchanged except their `--apply` runs, which the test
helper now drives through the reviewed two-step path (save the plan, apply it
with its digest and a new journal); a failed or blocked dry read returns its own
result, as before. `git diff --check` passed. No Rust crate changed. Live
apply and recovery remain unverified: no live read, write or recovery ran.


## #1923: public milestone description

P5 / metadata: O1 classified the `0.0.X` milestone description as public only
after replacing its private quotation with the decision, date and private-record
pointer. The settings planner copied that description verbatim. The shared
checker correctly refused it; earlier tests proved refusal but never exercised
the required public description.

The owning command proof is
`Settings.test_polish_milestone_uses_public_description_in_read_and_reconciliation`:
plant a synthetic private quotation, require the literal public description in
the dry plan, preserve all other milestone fields and an unrelated description,
and require zero writes and unchanged state. On the fake API only, prove creation,
repair, read-back and repeat reconciliation. The pre-transfer read must still
produce its plan with the organization blocker. Existing private-metadata and
literal-list proofs must continue refusing unsafe proposals; additionally plant
a named literal in the authored description to prove this field is checked too.
These are fixture claims, never live settings or application evidence.

Failing-first command (before the planner correction):

```text
python3 -I tools/open-settings/test_settings.py Settings.test_polish_milestone_uses_public_description_in_read_and_reconciliation
AssertionError: 1 != 0 : open-settings: privacy checker refused proposed metadata or could not read its inputs. Earlier writes may remain; rerun a read before any new apply.
```

Both missing and existing target milestone cases failed on that refusal. The
pre-transfer case also failed because stderr held the same refusal rather than
returning its blocker-bearing JSON plan. Summary:

```text
Ran 1 test in 1.617s
FAILED (failures=3)
```

The synthetic source quoted invented decision words; no real quotation is in
the test or this log excerpt. The regression and output are committed before
the correction.

### #1923 scoped results

At implementation commit `5db83799ed47eb014499e65ae01d6af86233e341`, the same
regression passed (1 test, 7.671s), followed by the affected command suite:

```text
python3 -I tools/open-settings/test_settings.py
Ran 22 tests in 98.119s
OK
```

This includes existing planted-private-value and unreadable-literal refusals,
plus a named literal planted in the new public description: it still refuses
before reporting. `cargo fmt --check`, the scoped shared privacy scan with
required literals, and `git diff --check` passed. No Rust crate changed, so
crate clippy does not apply. No full workspace or browser suite ran locally.
Live settings remain unverified: only synthetic command tests and an offline
replay of saved metadata ran. No live read or application ran for this fix.


All fixtures are synthetic. No existing test owns this new command boundary.
The plausible break is a settings command declaring success on missing security
reads, writing in default read mode, dropping the queue on a repeated apply, or
accepting a successful write without verifying the resulting settings.

- P5 / read-only: run the command on a fake `gh`; compare the complete state and
  require zero mutating requests. Report every difference without applying it.
- P5 / settings: plant wrong rulesets, fork approval, labels and milestones;
  apply, inspect their persisted values independently, then reapply with no
  further writes. Both protected branch patterns require the four fixed checks.
- P5 / safety: runners or either runner variable at repository or inherited
  organization scope block all writes; unreadable/malformed/paginated data,
  ambiguous rulesets, failed writes and failed/mismatched read-backs stop.
- P12 / queue: main alone requires MERGE and all required checks; timeout is
  75 minutes (current fleet guidance), exceeding the ticket's 45-minute floor.
  Existing longer timeouts survive apply.
- Real dry read: save a redacted report and read outcomes in the private PR.
  No real apply, publication, cut-over or live product operation is authorized.

Evidence classes: fake command tests prove fixture behavior only. The real dry
read proves only settings observed then, never that application works live.
Red/green output and helper records belong in the private PR: this ticket owns
only `tools/open-settings/`, which will eventually be public.

## First red (before implementation)

`python3 -I tools/open-settings/test_settings.py Settings.test_read_is_read_only_and_reports_differences`
exited 1 against the initial command stub. It falsely reported no drift:

```text
AssertionError: Items in the second set but not the first:
'Merge queue'
'CI must pass'
'milestone:synthetic-version'
'fork approval'
'label:synthetic-label'
Ran 1 test
FAILED (failures=1)
```

## Scoped results

`python3 -I tools/open-settings/test_settings.py`:

```text
................
Ran 16 tests in 40.554s
OK
```

The cases cover each setting, create/update failures, ignored successful writes,
failed read-backs, repeat apply, pagination, safety blockers and the old address.
`cargo fmt --check` passed. No Rust crate changed, so crate clippy is inapplicable.
The privacy checker passed on this tool folder with its required private list.
Full workspace and browser suites were left to CI. Real dry-read evidence and
the helper record are retained in the private PR, not in this future public tree.

## Redirect regression (before correction)

P5/P12: a configured old address must still read and preserve the destination's
rulesets after the organization transfer. Existing old-address tests covered
only the pre-transfer personal account, with no rulesets; they missed the
canonical source name returned through GitHub's redirect.

`python3 -I tools/open-settings/test_settings.py Settings.test_old_address_redirect_preserves_compliant_rulesets`
failed in both read and apply mode against the previous implementation:

```text
AssertionError: 1 != 0 : open-settings: GET repos/jparker2006/OpenWiz/rulesets:
managed ruleset is inherited; cannot apply.
Ran 1 test
FAILED (failures=2)
```

The fixture had compliant repository-owned rulesets whose source was the final
public address. They were mistaken for inherited rulesets. No live apply ran.

## Proposed metadata privacy regression (before correction)

P5 and the open-development text contract: proposed label/milestone names,
titles and descriptions must pass the shared privacy checker before any write
or report. Existing settings fixtures contained clean metadata only.

`python3 -I tools/open-settings/test_settings.py Settings.test_private_source_metadata_is_refused_before_any_write_or_report`
failed on all ten planted read/apply cases before the correction (thread ids,
a CloudRoom id, a private email shape and an exact-words record):

```text
AssertionError: 0 != 1
Ran 1 test in 5.546s
FAILED (failures=10)
```

This is synthetic command evidence only. The planted strings are constructed
from pieces in the fixture so the test's source itself stays publishable.

## Correction results

Both regressions pass after resolving the validated canonical repository and
checking all proposed metadata through the shared privacy command before any
report or write. The private-literal option refuses unreadable or empty inputs.
The command uses stdin instead of temporary files, preserving read-only mode.

```text
python3 -I tools/open-settings/test_settings.py
...................
Ran 19 tests in 49.706s
OK
```

`cargo fmt --check`, the scoped privacy scan with required literals, and
`git diff --check` passed. No Rust crate was touched. No workspace or browser
suite, live apply or settings write ran. The separate CI deadline-test blocker
and the read-only diff self-review are recorded on the private ticket and PR.

## Review R1: required-check source bindings (red first)

P5: reconciling the four required contexts must retain each existing GitHub App
binding, both on an otherwise compliant ruleset (zero writes) and when correcting
other drift. A malformed or ambiguous binding must refuse before any write.
Previous fixtures covered only omitted/null integration IDs, so they missed a
policy replacement that silently removed a non-null source restriction.

After merging main, ran:

```text
python3 -I tools/open-settings/test_settings.py Settings.test_required_check_bindings_survive_noop_drift_and_reapply Settings.test_invalid_or_ambiguous_required_check_bindings_refuse_before_writes
Ran 2 tests in 12.649s
FAILED (failures=14)
```

The compliant bound fixture made one write instead of zero; correcting other
drift removed all four synthetic bindings. Invalid IDs and ambiguous check rows
were also accepted rather than refused. Tests and this red log precede the fix.

### R1 scoped results

At the correction commit, the two targeted regression tests passed, followed by
the affected command suite:

```text
python3 -I tools/open-settings/test_settings.py
.....................
Ran 21 tests in 52.331s
OK
```

`cargo fmt --check`, the scoped privacy scan with required literals and diff
checks passed after merging main. No crate changed in this correction, so crate
clippy is inapplicable. The read-only diff self-review passed; its report and
clean no-push record are retained in the private PR. This result proves fixture
behavior, not live application. Full workspace/browser suites remain in CI.
