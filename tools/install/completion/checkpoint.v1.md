# CP1 completion checkpoint v1

CP1 is a private spec comment written by the orchestrator after verifying the
current facts. Its complete body is one strict JSON object with schema
`openwiz.completion-checkpoint.v1`. The protected caller configuration pins the
repository, spec, immutable comment ID and SHA-256 of its exact UTF-8 body bytes.
Whitespace and every edit count. The orchestrator explicitly replaces the pin
when it makes a new checkpoint. The engine consumes this record.

The schema is [checkpoint.v1.schema.json](checkpoint.v1.schema.json). All objects
have exactly their declared keys, each once. Integers use JSON integer spelling.
Repository privacy is a JSON boolean. Identity patterns match the entire input,
including a strict end-of-input check. Unknown versions, enums, fields and
duplicate keys hold completion. Arrays with
record identities have unique identities and the orders specified below.

## Bindings

The checkpoint contains `schema`, `repository`, `spec`, `plan`, `candidate`,
`live` and `follow_ups`.

- `plan` pins the positive revision number, full revision-v2 text, its SHA-256
  fingerprint and the latest validated approval comment's ID/body hash. Preserve
  the existing `plan-graph/revision.sh` bytes, task-box normalization and approval
  validation. The text includes every planned ticket, title, body hash and native
  blocker, in the existing order. The verifier checks its digest, syntax and
  unique ascending ticket/blocker identities.
- `candidate` contains version, full source `head`, full `tree` and
  `build_sha256`, the SHA-256 of the exact reviewed build identity record.
  The immutable pin, checkpoint and freshly selected candidate must agree.
- `live` is an ascending list of required live-ticket references. Each pins
  `ticket`, `comment_id` and exact `body_sha256`. The current approved spec's
  requirements must independently match the protected caller requirements.
  For spec #1093, that requirement includes #1110 and every required native,
  access, lifecycle, credit and timed-fleet obligation from its approved kit.
- `follow_ups` lists every confirmed follow-up, ascending by ticket, including
  open sub-issues outside the approved plan and external issues marked as
  follow-ups of this spec's planned tickets. Each entry pins ticket,
  classification, complete sorted labels, state, sub-issue membership and
  archive evidence for sub-issue agents.
  Confirmed follow-ups have classification `polish` and the actual `polish`
  label. Newly discovered or unclassified issues require orchestrator judgment.

The checkpoint contains reviewed identities and sanitized dispositions. Private
source records retain the underlying evidence. Public output contains fixed
reason codes and recorded effect names only.

## Trusted reader interface

`verify_completion(reader, pin, effect)` is the callable verifier seam for T12.
It returns a fixed reason string. The supported effects are `spec_summary` and
`all_closed`. `CP1_verified` reports the check made by that invocation. Each
actual effect boundary must invoke the verifier again and retain all existing
tick, approval and operational guards.

The `pin` object has the `$defs.pin` schema. Its orchestrator identity and
checkpoint reference come from protected orchestrator-owned configuration.
The configured author and independently established writer role must both match.
Multiple agents can share a GitHub login, so author login alone is insufficient.
A role written inside the checkpoint body supplies no authority.

For each invocation, the verifier generates two independent random challenges.
For each challenge, `reader(nonce)` synchronously returns strict JSON for a newly
collected `$defs.observation` plus the matching `nonce`. It re-establishes all
bindings immediately before the caller's proposed effect. A cached verifier
result or pre-startup snapshot supplies no authority. Source failures and a stale
challenge hold completion.

T12 must provide the trusted reader at its genuinely allocated production
boundary. Its implementation must establish the following from independent
sources on every read.

- Read current repository privacy and the actual GitHub subject metadata.
- Run the existing complete current-plan/approval readers. Bind the latest
  validated approval comment ID/body hash and exact revision bytes. A saved
  approval pointer alone is insufficient.
- Read the current selected build identity from the pinned installed runtime.
- Enumerate all spec comments and identify every possible CP1 record, including
  escaped schema tokens. Include unrelated comments so duplicate/conflicting
  candidates remain detectable. Supply actual comment IDs, repository, subject,
  author, exact body and independently verified writer role.
- Read each pinned live record on its actual live-ticket subject. Establish the
  authorized live-runner role and validate its source-backed result against the
  approved kit. Project the result into `$defs.live_result`, including its
  exact candidate, `live_observation` evidence class, overall `passed` result,
  each required claim passed and an empty gaps list. Preserve the exact body
  hashed by the checkpoint. The synthetic format introduced here is a handoff
  contract for that projection. Any unavailable result validator remains held.
- Independently enumerate all follow-up membership and current classification,
  labels and issue state. Reconcile every current sub-issue against the complete
  plan. Include every unresolved outside-plan issue for judgment. A list copied
  from the checkpoint cannot establish current membership or labels.
- Read each planned builder's closed state and verified default-branch merge,
  each planned human ticket's independently verified completion, archive state
  and the current spec-summary record. A closed issue alone supplies no merge,
  human completion or live pass.

`comments`, `live` and `follow_ups` use `$defs.feed`. Each feed includes its exact
source total and every page. The first cursor is null, each next cursor matches
the following page, only the final next cursor is null, cursors never repeat and
the total equals the unique item count. The reader must verify source counts
and complete pagination before constructing this projection. A challenge echo
binds a response to a call. It relies on a trusted reader to establish freshness
and provenance. User-supplied JSON has recording authority only.

The reader performs no checkpoint authorship, acceptance decision or label edit.
It must stop when it cannot independently prove one of these facts. The module
supplies no network, credential, account, supervisor or native effect adapter.

## Completion conditions

Both effects require current matching CP1 evidence, verified planned builder
merges and completed planned human work. Open classified follow-ups can appear
in a recorded summary under #1021. The shipped v1 close conditions remain
additional requirements for `all_closed`, including recorded summary, closed
sub-issues, archived agents and zero open follow-ups. Planner parity remains
with its existing owner.

Ordinary approved work uses its existing route independently of CP1. The
verifier handles summary/close only. Approval, start, merge, live, secret,
account, spending, source, publication and acceptance authority retain their
existing owners and gates.

## Executable recording proof

Run `python3 -I tools/install/completion/test_checkpoint.py`. Required cases live
beside the implementation and use synthetic values. Run one saved synthetic
recording with `python3 -I tools/install/completion/checkpoint.py --recording FILE`.
The file contains `pin`, a sequence of `reads` and proposed `effects`. The
recording reader advances one observation per read, then repeats its last
observation to model an unchanged source. A null read simulates an unavailable
source. Only this offline reader inserts challenges into supplied observations.

`record_completion(reader, pin, effects)` verifies immediately before appending
each effect to an in-memory recording. It stops on the first hold and preserves
any already recorded effect. Its output always has `recording_only` equal to
true. Exit 0 means every proposed recording effect verified. Exit 5 means held.
The output has schema `openwiz.completion-recording.v1`, a fixed reason and the
exact list of effects recorded by this invocation.

Reasons are `CP1_verified`, `CP1_effect_scope`, `CP1_malformed`, `CP1_unreadable`,
`CP1_identity`, `CP1_checkpoint`, `CP1_plan`, `CP1_build`, `CP1_live`,
`CP1_follow_ups`, `CP1_planned_work` and `CP1_tick_conditions`.

Positive recording evidence establishes this verifier's synthetic behavior.
Production completion stays held at the existing controlled-tick refusal until
T12 obtains its allocation, connects the trusted reader at the actual effect
boundary and verifies that integration. Native operation and live acceptance
remain with the approved live kit and #1110.
