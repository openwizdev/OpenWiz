# Combined main coverage, version 1 (`openwiz.ci-main-batch.v1`)

C6 of spec #2291 (#2313). This is a **contract and offline reference proof**,
not a batch scheduler, live result, merge service or permission to skip work.
The [schema](ci-main-batch.v1.schema.json) and rules below both apply.

Authority: Jake approved revision 1 on 2026-11-10, retaining complete batch
proof before replacement, every required check and full nightly runs
([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6764889159)).
No live, spending, App, paid-plan, ruleset or publication authority follows.

## Existing boundaries

Use `.github/workflows/ci.yml`'s existing `push` to `main` or `merge_group`
event and its persisted `openwiz.ci-selection.v1` plan. The existing
`.github/actions/docs-only/run.py` execution/stamp/finish boundary owns
full-work receipts; `gate.py` and the required `ci` result remain mandatory.
A schedule is still a separate full nightly run. Do not add an event, reason,
lane or field to [CI selection v1](ci-selection.v1.md) for this contract.

Use only the currently supported merge/admission mechanism, with independent
exact-head review, green required checks and the fleet's M1/base or queue rules.
This contract does not install or assume a queue. In private preparation the
ordinary supported merge followed by its full main push is sufficient for
**shadow observation**; it does not establish a supported replacement mechanism.
A queue result counts only if its tested commits and membership can be bound
exactly to the combined main range. Never substitute a PR head, reconstruct a
group by guess, or treat a different eventual merge commit as the tested head.

An unavailable queue or admission interface, necessary paid plan, changed
ruleset, new CI event/selection schema, service, transport or controller is a
**stop for Jake**: name the missing boundary, concrete proposal, required
permission/cost and conservative fallback. Do not implement it under C6/C7/C12.

## Identity and independent context

`batch` has repository (`owner/repo`), immutable `base`, combined tested `head`,
and ordered `members`. Every member has a positive `pull_request`, its immutable
PR `head`, resulting combined `merge` commit and that merge's main-line `parent`.
The first parent equals base; every next parent is the preceding merge; the last
merge equals head. No zero SHA, repeated PR/head/merge, empty batch, gap, overlap,
reordering or ambiguous association is accepted. This version represents only
ranges that can be completely accounted for by those merged members; other
commit shapes are unknown, never silently omitted.

`execution` identifies `.github/workflows/ci.yml`, exact run `id`, latest
`attempt`, `event` (`push` or `merge_group`), and `event_base`: the immutable
base of that actual workflow event, independently bound by complete event/run
association. For a push this is its `before`; for a merge group it is its
`base_sha`, using the existing selection contract. It must equal the batch base
or an intermediate member's merge, strictly before the combined tested head.
A PR head, a foreign or earlier out-of-range commit, the tested head itself, or
unknown event association cannot be an event base.

The durable `batch.base` and this event base have distinct meanings. For
checkpoint A, consecutive pushes A→B then B→C, and a superseded pending B run,
the full C run has event base B while the still-uncovered batch remains A→C.
Its full candidate inventory and complete receipts at C can cover both members;
no receipt for the superseded B run is needed. Shortening the batch to B→C would
leave a gap after checkpoint A and refuses. The pending membership is never
discarded just because another push arrived. A green result from a different
run, head or older attempt still cannot replace the current C execution.

The offline `coverage_refusals(raw, context)` reference seam in
[`ci/main-batch/test_contract.py`](../ci/main-batch/test_contract.py) compares the
receipt to an **independently read context**, never context derived from the
receipt itself. Context has exactly:

- `batch`: the complete, authenticated repository/commit/ordered member facts,
  read from the existing event and complete merge graph/PR associations;
- `previous_head`: last durably covered combined head, equal to this base;
- `execution`: current run/attempt/event/workflow and actual `event_base`, from
  complete event/run association, independently of the plan or coverage claim;
- `inventory`: every full-work test ID generated at this combined candidate by
  the trusted existing planner, including all always checks and skill suites;
- `required_checks`: the complete current required-check identities, including
  `ci` and any separate privacy or legacy protection check required by the
  repository. Each check's own current run/attempt must be independently bound.

Unknown repository/graph/checkpoint, truncated pages, missing/expired artifacts,
unreadable current attempts, an incomplete inventory or uncertain associations
refuse coverage. Never find a newest green first and infer its members. A reader
must recheck currentness before relying on a result, and reconcile durable
checkpoint/member/run facts after a restart. A duplicate observation is
idempotent; competing/overlapping checkpoint histories are unknown. C6 adds no
state writer, lock or controller. Live authentication and the durable reader are
C7's work; schema conformance alone never authenticates supplied evidence.

## Complete combined work

The coverage document contains exactly `schema`, `batch`, `execution`, `plan`,
`receipts`, `outcomes`, and `checks`. Strict JSON applies at every depth: missing,
extra and repeated keys, non-integer IDs, NaN and unknown versions refuse.

`plan` is the **exact UTF-8 JSON text** of `ci-selection.json`, preserving the
bytes hashed by existing execution receipts. It must pass CI selection v1's
schema and semantic rules, have `selection.mode = full`, branch `main`, head
matching `batch.head`, base matching the independently bound
`execution.event_base`, and the current execution's run/attempt/event. The
selection run's base remains the actual event base; never rewrite it to the
durable coverage checkpoint or accept it without independent association.
All builds and lanes run, with no skipped tests. The complete flattened plan
test inventory must equal
the independent candidate inventory. A self-consistent undersized plan is not
proof of full work. Selected PR greens, even their union, never substitute.

`receipts` reuse the executor's existing shape:
`{lane, tests, plan_sha256, run}`. `run` is the exact selection run object and the
digest is SHA-256 of the exact stored plan text. Expected receipts are `always`,
`rust`, `web`, the nonempty `site` and `release` groups of the selection's site
lane, each `skill:<name>`, `build:web_export`, and `prerequisite:toolkit` (full work
requires the toolkit). Every planned test belongs to its corresponding receipt,
each exactly once; build/toolkit receipts have empty test lists. Receipt order
and test order are immaterial. No foreign, stale or duplicate receipt counts.
The existing finish boundary remains authoritative for its actual job/matrix
results; a reader cannot fabricate a missing matrix member's receipt.

`outcomes` contain one `{name, result}` for `changes` and each expected receipt
name, all `success`. The observer normalizes actual current-attempt job/matrix
conclusions, never infers success from an artifact or a missing job. Failed,
cancelled, skipped, pending, unknown, duplicate or missing work is incomplete.

`checks` contain each required check's `{name, result, head, id, attempt}`,
all successful at the exact combined head and independently current identity.
`ci` belongs to the coverage execution; a separate privacy workflow has its
own run and attempt. A green `ci` is necessary, not a substitute for the other
required checks or the complete receipts. Keep every required safety, privacy,
product and protection check/name; this contract changes none of them.

The schema describes evidence, including non-success outcomes so readers can
report refusals honestly. Passing its shape alone does not mean complete.
The reference reader returns an empty refusal list only for **offline contract
conformance**. Neither that answer nor a `success` field opens the switch gate.

## Shadow proof, switch gate and rollback

The gate stays **closed by default**. Main per-push full runs and full nightly
runs stay active throughout C6, C7 and C11. This document defines no activation
flag or live authority field. C7 (#2314) implements the bounded shadow reader;
C11 (#2318) supplies separately authorized live evidence; C12 (#2319) alone owns
reviewed, separately gated admission integration. C13 (#2320) reports remaining
gaps and actual speed/cost evidence. No fixture is a live passing result.

Before any switch, all these prerequisites must be independently verified:

1. C7's reviewed implementation and **candidate-bound** finite proof kit identify
   one combined batch with multiple changes, exact base/head/members/attempt,
   authorized resources, maximum batches/members/pages/reads, time window,
   read-only observations, stop conditions and rollback. Kit preparation grants
   no account/workflow effect. No forced production failures, real API/billing
   exhaustion or destructive live test is allowed.
2. Offline proofs at that candidate demonstrate combined success, a failure
   visible only in combination, planted omitted work, failed/cancelled/missing
   results, overlapping ranges, a superseded pending push, stale attempts and
   restart/reconciliation. Every member remains pending until exact complete
   combined coverage exists. Independent review checks the full inventory and
   required-check coverage; PR greens cannot satisfy this gate.
3. C11 records Jake's separate scoped live authorization **before** effects,
   then reads back the exact combined live success with complete current
   receipts and a separate retained successful full nightly result. Bind both
   results, the proof kit, implementation commit, review and authorization by
   immutable candidate/result/private-record pointers. Record push, queue and
   result times plus actual runner/cost context using C4; unknowns stay gaps.
   Nightly uses the existing `schedule` full selection plan and its own
   run/attempt/head, complete inventory, receipts and required results. It is
   never a batch member or inferred from a push green.
4. C12 verifies the whole evidence chain at its exact reviewed candidate and
   the currently supported admission mechanism, including C3's durable
   overload pause. A pause stops new batches while admitted work finishes.
   Stale evidence, changed implementation/coverage, unproven combined or nightly
   work, review gaps or missing authority keep or restore per-push full work.

Rollback prerequisites are a reviewed way to restore ordinary main full-push
admission without dropping already pending changes, retained nightly scheduling,
and a durable last-covered checkpoint plus ordered pending members. Reconcile
all unfinished attempts after restart; never advance a checkpoint on partial
work, cancel coverage because newer work arrived, or reuse an old green.
Reversal changes neither required checks, review/M1/queue gates nor settings.
A rollback requiring another interface or authority is another stop for Jake.
C6 does not execute either a switch or rollback.

## Proof and compatibility

Run `python3 -I ci/main-batch/test_contract.py`. `complete.json` and
`expected.json` under `ci/main-batch/fixtures/contract/` are synthetic, unobserved
assumptions, with deliberately small representative full-work inventory.
They do not enumerate today's live work. `superseded-pending.json` and
`superseded-pending-expected.json` pin the two-member A→C batch with only the
complete B→C execution, retaining checkpoint A and independently observed event
base B. Refusals cover foreign/out-of-range/head/PR-head event bases, missing or
mismatched event association, and shortening that batch past the checkpoint.
The refusal cases mutate those examples while preserving independent expected
facts, including a planted undersized plan whose own receipts agree. The red logs in that folder precede
the validator fix in Git history.

Existing CI registers this suite as `release:ci2-batch-contract` in `plan.py`
and maps it to that command in `run.py`; registration/execution tests prove
full-plan discovery and failure propagation. No workflow, selection schema,
runner, dependency or product behavior changes. C7/C12 must implement this same
contract and compare against the trusted **candidate's** full inventory, not
freeze the small fixture's list into production. A new field/event or changed
meaning needs the normal approved contract revision and consumer holds.
