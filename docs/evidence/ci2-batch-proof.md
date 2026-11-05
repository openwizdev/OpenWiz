# CI2 C11: complete-batch and nightly live proof

**Status: C11's live observation is complete. Its independent coverage review
is this record's exact-head PR review, over the saved archive linked under
"Observation 2".** Observation 1 (below) failed: the kit's
authenticated reconcile refused, and the nightly receipt contents were not read.
Observation 2 (C11b, under "Observation 2" at the end) followed the reviewed
reader correction (#2443). Its single authenticated reconcile returned
`complete: true` for a two-member A→B→C batch with B's run superseded, and it
bound every receipt of the retained nightly. The switch gate stays closed:
C12 must verify this whole chain itself at its own candidate. The remaining
C4 unknowns are listed as gaps.

Evidence class: one separately authorized, read-only GitHub observation, plus
offline checks over the archived responses. Raw responses, the packet, context,
private reader state and billing rows stay private. This record publishes only
counts, public run/commit identities, hashes and private-record pointers.

## Authorization (AC1)

Jake granted C11's live authority on 2026-11-11: one live observation of a
complete combined main batch and the retained full nightly result, using C7's
kit, read-only from GitHub. Per-push full runs stay on. There is no spending,
runner opt-in or workflow change. The grant is recorded on
[#2318](https://github.com/jparker2006/ClosedWiz/issues/2318#issuecomment-6817291829).
The exact words are in the private grill record on
[#2402](https://github.com/jparker2006/ClosedWiz/pull/2402) (ND1). Both were read
back before the observation's first read. Planning reads before that (one main
run listing and PR searches) followed the ticket's recorded grant. The grant
names no expiry. This observation narrowed itself to one invocation inside the
kit's 10-minute ceiling.

No queue, purchase, ruleset, runner, setting, credential, dispatch, rerun,
cancellation or workflow change was made.

## Proof plan

| Claim (AC) | Evidence |
| --- | --- |
| Authority recorded before effects (AC1) | Ticket and private-record read-back above, before read 1 |
| One complete combined batch read back (AC2) | Kit's finite `shadow.py reconcile` at the clean candidate; independent GETs of graph, run, jobs and artifact |
| Offline combined-failure/missing proofs retained (AC2) | `test_shadow.py` and `test_batch_kit.py` at the candidate |
| Retained full nightly read back (AC3) | Schedule run, attempt jobs and selection artifact; plan inventory against the nightly head's planner |
| Per-push full runs stay; clocks/runners/cost recorded (AC4) | Main push run list; C4-style job clocks; partial billing read |
| Switch gate | Closed unless every item above is complete |

## Red: the kit's authenticated reconcile refuses

The kit's exact finite invocation ran once, at 2026-11-12T07:20:09Z, from a
clean checkout of the candidate `887124f2f45d6ad8c75d3bd52b1fceb0cc35374f`:

```sh
python3 -I ci/main-batch/shadow.py reconcile "$CI2_EVIDENCE/observation.json" "$CI2_EVIDENCE/context.json" "$CI2_EVIDENCE/state.json" --checkpoint "$CI2_CHECKPOINT"
```

It exited 1 with `complete: false`, `switch_authorized: false` and refusal
`GitHub read failed; no fallback or retry`. Private state kept checkpoint A
with both members pending. The failing read was
`branches/main/protection/required_status_checks`: main has no legacy branch
protection, so GitHub answers 404 `Branch not protected`. Its required checks
come only from the repository ruleset (`ci`, Actions application). The reader
treats that 404 as unreadable protection and stops, as the kit says it must.

Offline replay of the archived live responses (no further GitHub reads) pins
this: the refusal is the reader's 11th read, after five graph reads twice. With
only that one response replaced by an empty legacy set, the same archived facts
reconcile `complete: true`, cover C and leave no member pending. That replay is
a counterfactual over saved responses. Its second currentness pass reuses them,
so it is not a live result and does not open the gate.

## The observed batch (AC2)

| Binding | Value |
| --- | --- |
| Kit / implementation | `tools/ci2-live/batch-kit.md` blob `ed98ab66`, `ci/main-batch/shadow.py` blob `95ca0604`; both unchanged from C7's approved head `eb174f7d` ([APPROVE](https://github.com/jparker2006/ClosedWiz/pull/2372#issuecomment-6781311007)) |
| Candidate | `887124f2f45d6ad8c75d3bd52b1fceb0cc35374f`, tree `4c4f3bb3`, clean checkout |
| Checkpoint A | `3621f57cc8e6fda44e067f88b262e94db7009ecc`; its own full push run 43140833859 attempt 1 succeeded |
| Member 1 | #2386, head `3f71a526`, merge B `6ff0c623`, parent A, merged 03:02:09 |
| Member 2 | #2392, head `182fe832`, merge C `887124f2`, parent B, merged 05:26:22 |
| Execution | [43161398684](https://github.com/jparker2006/ClosedWiz/actions/runs/43161398684) attempt 1, `push`, `.github/workflows/ci.yml`; the only CI run at C |
| Event base | B, from check suite 116879089114's `before`, not from the packet |
| Required checks | Ruleset `ci` (Actions application 15368); suite application matches; no legacy protection |

All times are UTC on 2026-11-12. Both merge commits have exactly the two
parents above, and both PRs read back merged into `main` at those commits.

**Coverage.** The `main-shadow-1` artifact (one member, `observation.json`, not
expired) carries the exact full plan for run 43161398684 attempt 1 with base B
and head C. It says `complete: false`, as C7's capture always does. Its plan
lists 134 tests. That equals the 134-item inventory generated by the candidate's
own planner. It carries 13 receipts: `always`, `rust`, `web`, `site`, `release`,
six `skill:*`, `build:web_export` and `prerequisite:toolkit`. C6's
`coverage_refusals`, run offline over that packet and the independent context,
returns no refusal.

**Jobs.** The attempt has 19 job records (total 19, one page) and 16
allocated jobs. Fifteen succeeded: `changes`, `always`, `web-build`, `site`,
`release`, `rust-export (1)` with its toolkit step, `web-export`, six skill
jobs, `ci` and `web-test`. The sixteenth, `select-map`, ran after `ci` and
concluded `failure`. It is not a required check or a planned receipt, and the
run concluded success. `rust`, `web` and `toolkit-nightly` are skipped rows.

**Not shown live.** B's own push run (43145441768) also completed successfully
before C's run started, so B was not a superseded pending push. This batch is
two consecutive merges with one full run at C, observed as a shadow batch from
checkpoint A. The live window held no A→B→C shape with B's run superseded and C
complete, and creating one would need a push this authority does not cover. A
was never reconciled by the shadow reader. Its coverage is its own successful
full run, not a verified shadow checkpoint. The superseded-pending, combined-
failure, planted-omission, missing-result, overlap and restart cases stay
offline: `python3 -I ci/main-batch/test_shadow.py` (22 tests) and
`python3 -I tools/ci2-live/test_batch_kit.py` (2) pass at the candidate. They
ran after the live invocation, not before it as the kit says.

## The retained nightly (AC3)

| Binding | Value |
| --- | --- |
| Run | [43066350941](https://github.com/jparker2006/ClosedWiz/actions/runs/43066350941) attempt 1, `schedule`, head `5118113136a064ef8d14a308a3bc864f03b5cbb1`, success |
| Plan | `ci-selection-1`: mode `full`, reason `nightly`, base null, this run/attempt/head |
| Inventory | 132 planned tests equal the 132-item inventory from that head's own planner; no skipped tests |
| Jobs | 19 records, 17 allocated, all success (`select-map` too), including `toolkit-nightly` and the `ci`/`web-test` results; `rust`/`web` are skipped rows |
| Artifacts | 21, none expired, including all lane receipts and the live-check evidence |

The nightly is separate evidence. It is not a batch member and is not inferred
from any push green. Its head is not the batch head. Lane receipt contents were
not downloaded; only their presence and the jobs' results were read.

## Per-push runs, clocks, runners and cost (AC4)

Main per-push full runs stayed active. During the observation the next two
merges each had their own queued or pending push run.

| Clock / count | Batch run at C | Nightly |
| --- | --- | --- |
| Last member merged to `main` | 05:26:22 | n/a (schedule) |
| Run created | 05:26:25 | 2026-11-11 17:15:18 |
| `ci` completed | 06:29:08 | 2026-11-11 17:30:45 |
| `web-test` completed | 06:30:02 | 2026-11-11 17:30:53 |
| Job records / allocated | 19 / 16 | 19 / 17 |
| Queue (created→started), allocated only: median, p90 s | 125, 2846 | 69, 314 |
| Sum of allocated runner seconds | 7722 | 10376 |
| Observed runner pool | Self-hosted repository labels (names kept private) | The Namespace profile recorded in R1 |

Batch waits in seconds:
`2,2,3,6,40,52,72,107,143,187,293,385,2811,2841,2846,2892`.
Nightly waits: `1,3,3,11,11,12,13,15,69,69,120,180,180,238,298,314,433`.

The PR merge time is GitHub's merge onto `main`, not an independent push-event
receipt. From it, C's required `ci` result came 3766 s later. Member 1 waited
from 03:02:09, but its own run had already covered it. The reader's own C4
summary counts the three skipped rows' placeholder clocks as zero-second
waits (n 19, median 72). The table above excludes them, as R1 does.

Cost: the read-only billing-usage read for 2026-11 returned these repository
rows. 2026-11-11: Actions Linux 3 minutes, USD 0.018, and storage net 0.
2026-11-12: 1 minute, USD 0.006, and storage net 0. Self-hosted jobs carry no
GitHub minutes. Machine, Namespace and whole-bill cost are **Unknown**. This
observation spent nothing.

Resources: 29 authenticated GETs out of a 128 ceiling. 17 were direct reads,
11 were the reader's, and one was the billing read. One page per endpoint;
nothing was retried or polled. The window was 07:19:30–07:21:24 UTC.

Private archive (SHA-256): packet `observation.json` `24d310f5…6f3b`,
context `41b63450…3f6b`, candidate inventory `93b63aeb…4b4f`, nightly plan
`57e85382…491c`, reconcile report `aa2b1338…37e3`, private state
`fd3d636b…ab63`, all raw responses `753726a6…b55b`.

## Observation 1: switch gate closed

C12 cannot rely on observation 1. These gaps kept the gate closed:

1. **No authenticated complete reconcile.** The kit refused at the
   legacy-protection 404. A reader that treats `Branch not protected` as an
   empty legacy set needs its own reviewed change, outside this ticket. A new
   live invocation then needs its own authority, because this grant covered one.
2. **No superseded pending member live.** B had its own complete run. A was
   not a shadow-verified checkpoint.
3. **C4 gaps.** There is no independent push receipt and no whole bill. The
   reader's queue summary includes skipped placeholder clocks.
4. **Ordering.** The kit's offline preparation ran after, not before, the
   invocation. The counterfactual replay reused saved responses.

Main per-push full runs and full nightly runs remain the only coverage.

## Observation 1: what remained before C11 could complete

Each step needs its own authority; none is granted by this record.

1. A reviewed reader correction, in its own separately approved scope: an
   absent legacy protection (`Branch not protected`) reads as an empty legacy
   set, and the queue summary excludes skipped placeholder clocks.
2. Renewed scoped live authority from Jake for a new candidate-bound
   invocation, recorded before any read.
3. At a candidate containing that correction, run the kit's offline
   preparation first, then one authenticated `reconcile` that returns
   `complete: true`.
4. Read the retained nightly's receipt contents and bind each to its exact
   plan digest, inventory, run, attempt and required results.
5. Append the authority, review and result pointers here, with an independent
   coverage assessment. Only then can C11 be claimed complete.

All five steps are done. Steps 1 and 2 are #2443 and the C11b grant; steps 3
to 5 are observation 2, below.

## Observation 2 (C11b)

Evidence class: one separately authorized, read-only GitHub observation, plus
offline checks at the candidate and over the archived responses. The same
privacy split as observation 1 applies.

### Authority (AC1)

Jake renewed the scoped authority for **one more** observation on 2026-11-13:
a complete combined main batch and the retained full nightly, with C7's kit
plus the merged reader correction. It is read-only from GitHub. Per-push full
runs stay on. There is no spending, runner opt-in or workflow change. The grant
is recorded on
[#2318](https://github.com/jparker2006/ClosedWiz/issues/2318#issuecomment-6839833551),
and its exact words are in the private record that comment names. Orchestrator
rulings then set the observation's scope:

- [6840329836](https://github.com/jparker2006/ClosedWiz/issues/2318#issuecomment-6840329836):
  one owner.
- [6840368703](https://github.com/jparker2006/ClosedWiz/issues/2318#issuecomment-6840368703):
  the candidate-selection reads plus one reconcile together make one observation.
- [6840488718](https://github.com/jparker2006/ClosedWiz/issues/2318#issuecomment-6840488718):
  the first candidate was voided by the runner move.

The ticket was read back immediately before each set of reads (00:45:13 and
02:41:03 UTC). No other observation, branch or PR existed at either time.

No queue, purchase, ruleset, runner, setting, credential, dispatch, rerun,
cancellation or workflow change was made.

### Sequence

All times are UTC on 2026-11-13.

| When | What |
| --- | --- |
| 00:45:27–29 | Offline preparation at the first candidate `7df2880c` |
| 00:45:51–52 | Candidate selection: 3 GETs, one run list per head. C's run was still pending, so the kit's stop condition applied. That batch was later voided, not failed: both its runs were cancelled by the runner move ([6840488718](https://github.com/jparker2006/ClosedWiz/issues/2318#issuecomment-6840488718)) |
| 02:41:23–25 | Offline preparation at the clean candidate `057e0b21`, **before** any read of this batch: `python3 -I ci/main-batch/test_shadow.py` 24 OK, `python3 -I tools/ci2-live/test_batch_kit.py` 2 OK, `python3 -I ci/main-batch/test_contract.py` 13 OK. Candidate planner inventory: 134 |
| 02:41:48–02:42:13 | Independent context reads: run, run list, check suite, rules, legacy protection, PRs, artifact list and packet |
| 02:42:15–26 | **The single kit invocation** (exact command below): exit 0 |
| 02:42:26–02:44:18 | Nightly and C4 reads, then the billing read. Window closed |

```sh
python3 -I ci/main-batch/shadow.py reconcile "$CI2_EVIDENCE/observation.json" "$CI2_EVIDENCE/context.json" "$CI2_EVIDENCE/state.json" --checkpoint "$CI2_CHECKPOINT"
```

It ran from the clean candidate checkout. Evidence stayed outside it, and the
checkout was still clean afterwards.

### The observed batch (AC2)

| Binding | Value |
| --- | --- |
| Kit / implementation | `tools/ci2-live/batch-kit.md` blob `ed98ab66` (unchanged since C7), `ci/main-batch/shadow.py` blob `1eaedd7c` (#2443's approved head `851b6f94`, [APPROVE](https://github.com/jparker2006/ClosedWiz/pull/2443)) |
| Candidate C | `057e0b219a6ed4449c9d09da70379569530e70bc`, tree `d283168c`, clean checkout |
| Checkpoint A | `d4431b827a318ef729b68c6c2edfc6889ef83c0f` (#2441). Its own full push run 43347487196 attempt 1 succeeded (created 01:47:28, after the runner-move cutoff) |
| Member 1 | #2442, head `235f908a`, merge B `8bbd9f7a`, parent A, merged 02:10:01 |
| Member 2 | #2257, head `c0324156`, merge C `057e0b21`, parent B, merged 02:19:39 |
| Superseded B | B's own push run 43350197562 attempt 1 was **cancelled** when C was pushed. No B receipt was used |
| Execution | [43351370135](https://github.com/jparker2006/ClosedWiz/actions/runs/43351370135) attempt 1, `push`, `.github/workflows/ci.yml`, success; the only `ci.yml` run at C |
| Event base | B, from check suite 117391755366's `before` (application 15368), not from the packet |
| Required checks | Ruleset: `ci` only (Actions application 15368). Legacy protection answers 404 `Branch not protected`, which the corrected reader reads as an empty set |

Both merges have exactly the two parents above, in Git and through the API,
and both PRs read back merged into `main` at those commits.

**Reconcile result:** `complete: true`, `outcome: success`, no refusals,
`switch_authorized: false`. The reader authenticated the packet against run
43351370135 attempt 1's `main-shadow-1` artifact. It re-read the graph,
protections, run, jobs, Rust matrix, toolkit step and the required `ci` check
twice, and the facts were the same both times. Private state moved from
checkpoint A, with both members pending, to covered C with nothing pending.
This is the live A→B→C case with a superseded B that observation 1 could not
see.

**Coverage.** The covered document carries the exact full plan for that run
and attempt (`push_main`, base B, head C). Its 134 tests equal the candidate
planner's 134-item inventory. It has 13 receipts (`always`, `rust`, `web`,
`site`, `release`, six `skill:*`, `build:web_export`, `prerequisite:toolkit`)
holding 134 tests, each exactly once, and every receipt binds plan digest
`778f2d33…0ae2` and this run. There are 14 outcomes, all success. The one
required check is `ci`, success at C. C6's `coverage_refusals`, re-run offline
over the saved document and the independent context, returns none.

**Jobs.** The attempt has 19 job records (one page) and 16 allocated jobs, all
`success`, including `ci`, `web-test` and `select-map`. `rust`, `web` and
`toolkit-nightly` are skipped rows.

The offline cases (combined failure, planted omission, failed, cancelled and
missing results, overlap, superseded pending, stale attempt, restart) stay
covered by the 24 + 2 + 13 fixture tests above. This time they ran before the
invocation, at the candidate.

### The retained nightly (AC3)

| Binding | Value |
| --- | --- |
| Run | [43271573219](https://github.com/jparker2006/ClosedWiz/actions/runs/43271573219) attempt 1, `schedule`, `ci.yml`, head `19cd51ce919602d6389fbd6aa83b197fb6753993`, success; the newest schedule run |
| Plan | `ci-selection-1` / `ci-selection.json`: mode `full`, reason `nightly`, base null, this run/attempt/head; digest `dd223d49…a1b8` |
| Inventory | The plan's 134 tests equal the 134-item inventory from that head's own planner (clean checkout); no skipped tests |
| Receipts (contents read) | 12 lane artifacts: `always` 4, `release` 16, `site` 3, `web` 86, six `skill:*` 1 each, `build:web_export` 0, `prerequisite:toolkit` 0. Every one has exactly `lane tests plan_sha256 run`, digest `dd223d49…`, and the plan's exact run object |
| Rust | The `ci` job stamps the `rust` receipt itself from the `rust-ran-*` shares (`.github/workflows/ci.yml`, the step after `shard.py check`), so it is not a lane artifact. The single share `rust-ran-1-1` holds the plan's 19 Rust tests exactly, with no duplicates |
| Total | 115 + 19 = 134 tests, each once, no foreign test |
| Jobs | 19 records, 17 allocated, all success, including `toolkit-nightly`, `rust-export (1)`, `ci` and `web-test`; `rust`/`web` are skipped rows |
| Artifacts | 21, none expired, all associated with this run and head |

The nightly is separate evidence. It is not a batch member and is not inferred
from any push green. Its head differs from the batch head, and it ran before
the runner move.

### Per-push runs, clocks, runners and cost (AC4)

Main per-push full runs stayed active. A, B and C each got their own push
`ci.yml` run, and B's was cancelled only when C arrived. No run was dispatched,
rerun or cancelled by this observation.

| Clock / count | Batch run at C | Nightly |
| --- | --- | --- |
| Last member merged to `main` | 02:19:39 | n/a (schedule) |
| Run created | 02:19:42 | 2026-11-12 17:38:28 |
| `ci` completed | 02:33:33 | 2026-11-12 17:56:11 |
| `web-test` completed | 02:33:50 | 2026-11-12 17:56:30 |
| Last job completed | 02:33:52 | 2026-11-12 19:54:28 (`toolkit-nightly`) |
| Job records / allocated | 19 / 16 | 19 / 17 |
| Queue (created→started), allocated only: n, median, p90 s | 16, 7, 7 (the reader's own summary agrees) | 17, 25, 241 |
| Sum of allocated runner seconds | 2361 | 10584 |
| Observed runner pool | The new self-hosted pool after the runner move, plus the Namespace Rust profile (label names kept private) | Before the runner move |

Batch waits in seconds: `2,5,7,7,7,7,7,7,7,7,7,7,7,7,7,10`.
Nightly waits: `1,2,5,9,10,12,13,15,25,76,76,76,134,176,184,241,256`.

The merge time is GitHub's PR merge onto `main`, not an independent push-event
receipt. From it, C's required `ci` result came 834 s later. Member 1 waited
from 02:10:01 (1412 s); its own run never completed.

Cost: one read-only billing-usage read for 2026-11. Repository rows:

| Day | Actions Linux | Storage |
| --- | --- | --- |
| 2026-11-12 | 64 minutes, USD 0.384 | net 0 |
| 2026-11-13 (so far) | 17 minutes, USD 0.102 | net 0 |

These are day totals for GitHub-hosted minutes, not attributable to these
runs. Self-hosted jobs carry no GitHub minutes. Self-hosted, Namespace and
whole-bill cost are **Unknown**. This observation spent nothing.

Resources:

- 34 logged direct GETs: 3 for candidate selection and 31 in the window,
  including 1 billing read, 14 artifact downloads and 2 for the packet.
- The reader's own reads: 35 by its code path (5 graph reads, then 15 in each
  of its two facts passes). They were not separately logged.
- About 69 in total, against the kit's 128 ceiling.
- One page per endpoint. Nothing was retried or polled. The invocation took
  11 s, inside the 10-minute bound.

**Private archive:** the exact saved bytes are in the private record at
[`private/evidence/2318/c11b/` @ `763806f4`](https://github.com/jparker2006/ClosedWiz/tree/763806f468510afbfc41036df68d0d0daab790a9/private/evidence/2318/c11b).
They were committed afterwards, without re-observing (review R1 on #2482). Its
`README.md` maps each file. `sha256sum -c MANIFEST.sha256` there re-hashes all
105 files; the manifest itself is
`18a6a889195bf1036ca643f77cb5c90924bf0e4806478718e78bdd7ab1598d04`.

| File (under `observation/` unless noted) | SHA-256 |
| --- | --- |
| Packet `observation.json` (run 43351370135's `main-shadow-1`) | `13a049d0e560f6c471f74ec9dee977a1f8b0288cca75ec22dd404c1640e8a421` |
| Context `context.json` | `5a35611aa5abb9aeb7ac8a43205917ab0a6086db4ea2345dff86ba44048e4465` |
| Candidate (and nightly-head) inventory `inventory.json` | `f32962b206c6096482894618466d3cd5c28ad26b2345d7a1e4761e15579f3e16` |
| Reconcile report `reconcile-report.json` | `7889d5c39ca84436fc71c12c7368004ae89f8073c7fb5ed3e07825a7148107d4` |
| Private state after the reconcile `state.json` | `7ae313aa1e2bd40909d874189b0ca936a34109ce1215ffa9287e9e84550125cb` |
| Nightly plan artifact `nightly-zips/ci-selection-1.zip` | `1000e45ad5728bd7424ee6a109317824158850e2ac3e2b7176269e33cedf54e0` |
| Raw responses, downloads and read logs `all.sha256` | `c54209ad15d57a5e989aff13a4d3a512a81274da30401c94298ccaa604adb4ad` |
| Candidate selection `selection/manifest.sha256` | `d89b819cf3426976a580f760609a294132a1a64a38eaba2e1dd2de5c02a8c882` |

One file is withheld: the raw billing response. It also holds rows for
unrelated repositories, so only this repository's extract is kept. Its
SHA-256 (`f142f933…d3fa`) stays in `all.sha256` and the README.

### C11 acceptance and the switch gate

| AC | Result |
| --- | --- |
| AC1 authority before effects | Done: grant and rulings read back before each set of reads |
| AC2 one complete combined batch | Done: authenticated `complete: true` for A→C, both members, base, head, event base, attempt and every required check. The offline proofs were kept and run first |
| AC2/AC3 independent coverage review | This record's exact-head PR review over the saved archive above: the packet, context, report, state and nightly receipts can be re-hashed and replayed offline. The builder's own `coverage_refusals` re-run is not independent. C11 is complete only once that review has checked the saved bytes |
| AC3 retained full nightly | Done: plan, all receipt contents, inventory, run, attempt and required results bound |
| AC4 per-push runs, clocks, runners, cost | Per-push runs stayed on. Clocks, queue, runner seconds and pool were recorded; the gaps are below |

**The switch gate stays closed.** This record opens nothing. C12 (#2319) must
verify the whole chain at its own reviewed candidate and the supported
admission mechanism. Remaining gaps, plainly:

1. **Checkpoint A** is covered by its own successful full push run, not by an
   earlier shadow reconcile. C is now the first shadow-verified checkpoint. Its state is saved in
   the private archive above.
2. **C4:** there is no independent push-event receipt (merge time is the
   proxy), and no self-hosted, Namespace or whole-bill cost.
3. **Read accounting:** the reader's 35 reads are derived from its code, not
   logged.
4. **Nightly:** it is the newest retained one, from before the runner move. No
   nightly on the new pool has been observed.
5. **One batch, two members.** No merge queue or merge-group shape was
   observed, and none exists here.
