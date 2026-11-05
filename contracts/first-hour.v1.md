# OpenWiz first-hour contract, version 1 (`openwiz.first-hour.v1`)

The shared acceptance, preservation and result interface for the first hour of
spec #2194 (ticket P1, #2200): a fresh user installs OpenWiz, connects it, gives
one small idea for their own repository, confirms its spec, approves its plan,
and sees a fleet build, independently review, check and merge the first pull
request, all within one hour. The schema is
[first-hour.v1.schema.json](first-hour.v1.schema.json). Synthetic examples are in
[tests/fixtures/first-hour/](../tests/fixtures/first-hour/README.md); the checks
are in `tools/install/tests/first-hour-contract/`.

**Contract only.** This is an evidence and state interface. It is not a setup
API, planner, engine, launcher, publisher or storage design. It adds no route,
method, header, bound or write authorization, and it changes no once-only rule
of [setup.v1](setup.v1.md), [web-api.v1](web-api.v1.md) or
[decisions.v1](decisions.v1.md). It grants no live, account, feedback-send,
spending, cut-over, ship or publication authority. Every claim PR1 to PR8 of
#2194 starts **Unverified**; a record that follows this contract proves only what
its proof class and evidence show.

## Documents

One document is one JSON object with `schema` equal to `openwiz.first-hour.v1`
and `kind` either `result` (one attempt at the whole first hour) or `recovery`
(one interruption case on its own, for the recovery component #2222 and the
installed journey #2204). Objects have exactly the schema's keys, each once: no
missing, extra or duplicate keys, no positional arrays, enums as plain strings,
integers as JSON integers, times as nonnegative millisecond integers. A strict
reader refuses duplicate keys and fractional spellings, which JSON Schema cannot.
`Fact` fields are `{"known": value}` or `{"unknown": "<reason>"}`; unknown is
never a failed read reported as known.

Both kinds carry:

| Field | Meaning |
| --- | --- |
| `verdict` | `pass`, `fail` or `unverified`, as [the verdict](#the-verdict) requires |
| `proof_class` | `fixture` (a hand-written synthetic example), `recording` (the recording-provider journey or fault providers, #2204/#2222) or `live` (an observation of the installed candidate, #2207) |
| `synthetic_assumptions` | What is invented. Nonempty exactly when the class is not `live` |
| `private_record` | `null`, or the [open-development pointer](open-development.v1.md#the-pointer) to the private comment holding the raw evidence. A `live` record needs one |
| `candidate` | `Fact` of the checked candidate: [install.v1](install.v1.md)'s `version`, `source`, `target`, plus the `manifest_sha256` the install verified. When #2186's release-candidate interface merges, #2207 binds this identity to it |

A `recovery` adds `case` ([one recovery case](#recovery-cases)). A `result` adds:

| Field | Meaning |
| --- | --- |
| `repository` | `Fact` of the owner's selected repository: `full_name` (`owner/name`) and `selected_by_owner: true`. The installer's optional demo is not this repository |
| `clock` | `started_at_ms`, `ended_at_ms` (each a `Fact`) and `limit_ms`, always `3600000` |
| `stages` | The ten [stages](#stages-and-evidence), once each, in their order |
| `builder`, `reviewer` | The [seats](#builder-and-reviewer-seats) actually used |
| `waits` | Every wait: `stage`, `kind` (`install`, `account`, `approval`, `queue`, `review`, `ci`, `other`), `started_at_ms`, `ended_at_ms`, `detail` |
| `help` | Every help given: `stage`, `at_ms`, `source` (`public_docs`, `product_message`, `owner`, `operator`, `private_instruction`, `prepared_plan`), `detail` |
| `retained_work` | The [work inventory](#retained-work) at the end |
| `operations` | Every [operation](#operations-and-effects), with its effect count |
| `interruptions` | Every [recovery case](#recovery-cases) the attempt went through |
| `findings` | Every [finding](#findings-gaps-and-gates) raised against this attempt |
| `gaps` | Each claim (`PR1` to `PR8`) still lacking evidence, with its reason |
| `gates` | The three [unresolved interface gates](#findings-gaps-and-gates) |
| `ten_minute_fleet` | The [separate ten-minute measure](#the-separate-ten-minute-measure) |

## The clock

The clock starts when the fresh user opens the public install instruction and
ends at GitHub's merge time of the first verified merge, read back. Elapsed time
is `ended_at_ms - started_at_ms`, and the hour holds when it is at most
`3600000`. Everything in between counts: download, install, account setup and
sign-in, choices, approvals, queues, help, review and CI. Nothing is subtracted
or paused; `waits` and `help` record where the time went, never a deduction.
Every wait and help time lies inside the clock. A missed hour fails PR1.

The attempt uses a genuinely new small idea on the owner's selected repository.
Help from a `prepared_plan` or a `private_instruction` (operator steps a new
user would not have) means the attempt does not measure the first hour; it stays
unproven, never a pass.

## The separate ten-minute measure

#1110's existing target, the first running fleet within ten minutes, keeps its
own definition and owner (`owner: 1110`). `state` is `met` (`elapsed_ms` at most
`600000`), `missed` (`elapsed_ms` above it) or `unmeasured` (`elapsed_ms` null).
It never decides the first-hour verdict, and the hour never decides it.

## Stages and evidence

A stage's `state` is `verified`, `missing`, `refused`, `unknown` or `failed`,
as in [setup.v1](setup.v1.md), plus `failed` for an attempted step that did not
succeed. `verified` needs at least one `evidence` item with the stage's
establishing basis; every evidence item has `basis`, `at_ms` and `detail`.

| Order | Stage | Established only by | Existing owner |
| --- | --- | --- | --- |
| 1 | `public_instruction` | `instruction_opened`: the public install instruction was opened; the clock starts here | #1109 |
| 2 | `install` | `install_result`: install.v1's result for the candidate | #1100, #1109 |
| 3 | `connections` | `setup_component_verified`: every prerequisite of the selected engine verified by setup.v1's current positive evidence | #1105, #1106, #1107 |
| 4 | `idea` | `idea_saved`: the fresh idea saved for the selected repository | #1108 |
| 5 | `spec_confirmation` | `decision_saved`: the saved confirmation (decisions.v1 resolved, current wording) | #1108 |
| 6 | `plan_approval` | `decision_saved`: the saved approval of the exact current plan revision | #1108 |
| 7 | `fleet` | `agents_running`: the approved plan's builders started | #1108, #1106 |
| 8 | `review` | `review_approve_exact_head`: an independent reviewer's APPROVE naming the pull request's head | ADR 0008 |
| 9 | `ci` | `ci_green_exact_head`: every required check green on that head | ADR 0008 |
| 10 | `merge` | `merge_read_back`: GitHub reads the pull request back as merged at the approved head | ADR 0008; the clock ends here |

**What an observation does not prove.** These never establish a stage or a
seat, and a record that marks one `verified` on them alone is refused:

| Observation (basis) | Shows | Never shows |
| --- | --- | --- |
| `cloudroom_reachable` | CloudRoom answered | a sign-in, a usable harness or account |
| `harness_listed` | a harness or model is in the catalogue | a usable login for it, the other harness, or a usable reviewer |
| `agents_running` | builders are running (the `fleet` stage only) | a review, green CI, a merge or the hour |
| `answer_accepted` | an answer's send was accepted | a saved confirmation or approval; only the orchestrator's saved record is one |
| `pr_closed` | the pull request is closed | a merge; only `merge_read_back` at the approved head is a verified merge |
| `tab_session_storage` (retained work) | a draft and its op ids are in that tab's sessionStorage: they survive a reload of that tab and a server restart while it stays open | retention once the tab or browser is closed, or any durable owner state |

## Builder and reviewer seats

Each seat records the actual `harness` (`codex` or `claude_code`), `model`,
`effort` and `location` (`cloud` or `local`) chosen through the existing choices,
whether it was `usable` (a state as above), its `evidence`, and every
`extra_prerequisites` item: an additional account or sign-in the seat needed,
explained to the owner before the plan starts. `usable: verified` needs
`harness_run_observed`: that account actually ran that harness in this attempt.
A listed harness, one harness's success, or reachable CloudRoom never makes the
other seat usable. The review is independent only when the reviewer's harness
differs from the builder's (ADR 0008's other-family rule: `codex` is the GPT
family, `claude_code` the Claude family). This promises no particular model and
exempts no single-provider plan from independent review.

## Retained work

A work item is `kind`, `id`, `content` and `basis`:

| Kind | `id` | `content` |
| --- | --- | --- |
| `draft` | the draft's opaque key | SHA-256 of the draft's exact UTF-8 bytes |
| `setup_state` | the setup record's name | SHA-256 of its saved canonical JSON |
| `branch` | the branch name | its head commit |
| `commit` | the commit id | its tree id |
| `pending_operation` | the operation id | its request fingerprint (setup.v1), unchanged by its phase |

`basis` says where the item was read: `owner_state_read_back` (the owner's
private state, read back), `repository_read_back` (the Git host, read back),
`provider_read_back` (the provider's exact resource) or `tab_session_storage`.

Within every work inventory, `(kind, id)` is unique. Within every operation
inventory, `operation_id` is unique. Duplicate observations, identical or
conflicting, are refused before comparison or effect counting; their order
never selects a winner. Across successive inventories, a commit's tree and a
pending intent's request fingerprint cannot change under the same identity.
Drafts, setup state and branch heads may evolve between interruptions; each
interruption still compares its own original and recovered content exactly.

## Recovery cases

A case is the `interruption`, the work inventory `before` and `after` it, the
`operations` it touched (each with `phase_before` and `phase_after`), and the
`explanation`. Every item `before` must appear `after` with the same `kind`,
`id` and `content`; a missing or changed item is **lost work**. Items may be
added. After a `browser_restart`, an item read only from `tab_session_storage`
is not proven retained.

An empty `before` inventory proves no preservation and is unproven. Every
observed operation needs its original `pending_operation` item in `before`,
binding its id and request fingerprint; every original pending item needs its
operation observation. `setup_interrupted`, `lost_reply` and `repeat_approval`
also need at least one operation observation. Other cases may have none when
no pending intent was involved, but still need original work. Missing evidence
never means that nothing happened. A missing or changed `after` item remains
lost work, rather than evidence of successful recovery.

| Interruption | What must hold afterwards |
| --- | --- |
| `revoked_access`, `refused_access` | Nothing takes effect past the refusal (setup.v1, web-api.v1's access rules); drafts and pending records stay; the owner is told to reconnect |
| `builder_unavailable`, `reviewer_unavailable` | No seat or plan is called ready; the missing account is explained before anything starts |
| `setup_interrupted` | setup.v1's operation id, fingerprint and proposal were persisted before any effect; resuming reuses that id |
| `lost_reply` | The operation stays `uncertain` until reconciled against the provider's exact resource; no second call before that |
| `browser_restart`, `process_restart` | Owner state, send and new-thread records and staged attachments stay; pending operations are reconciled by op id before anything else |
| `update_rejected` | install.v1: the last good build stays selected and all owner work remains |
| `removal_default` | install.v1: removal stops only this installation's runtime and keeps owner work; it is not remote credential revocation |
| `repeat_approval` | A repeated approval or answer reuses its op id and makes no second effect |

The `explanation` says `what_happened`, `took_effect` and the `next_action` that
is safe. `took_effect` is `yes` when the case counted any effect, otherwise
`unknown` when any of its operations is still `uncertain`, otherwise `no`; any
other value is refused.

This contract chooses no new storage. If a draft must survive a browser restart
and no existing owner interface keeps it, that retention stays unproven: #2222
proves it through an existing interface or stops for a scoped contract revision.

## Operations and effects

One operation is one owner intent: `operation_id` (32 lowercase hex, its first
op id), `kind` (setup.v1's `connect_app`, `prepare_project`, `activate_engine`,
`configure_access`; web-api.v1's `send` and `new_thread`; the fleet's
`start_agent` and `merge`), `phase` (setup.v1's `proposed`, `applied`,
`refused`, `uncertain`), `effect_count` (provider effects observed for it,
read back), `attempts` (provider calls for that intent across every op id derived
for it, such as a composer's `-q<n>` or a launcher's `-c<n>`; a replay the core
answers from its record is not a call) and `reconciliation` (`none` or
`provider_read_back`).

`attempts` is a nonnegative count. A proposal saved before its first provider
call has zero attempts, zero effects and phase `proposed`; a refusal before a
call can likewise have zero attempts/effects. Zero attempts cannot establish
an `applied` or `uncertain` phase in either recovery observation or the final
inventory. Persist-before-effect is represented without inventing a call.

- `effect_count` above 1 is a **duplicate effect**.
- `attempts` above 1 without `provider_read_back` is a **blind retry**: uncertainty
  is reconciled before any retry. The existing owner-acknowledged controls stay
  as they are; using one before reconciling is counted here, not forbidden.
- Leaving `uncertain` (to any phase) without `provider_read_back` **erases
  uncertainty**; a later refusal never settles it.
- `applied` needs an effect count of at least 1; `proposed` and `refused` need 0.
- An operation still `uncertain` at the end is unproven, never a pass.

In a result, interruptions are ordered observations followed by the final
`operations` inventory. Every touched intent must appear there with the same
id and kind. Its effect and attempt counts are cumulative and cannot decrease;
a successive recovery's `phase_before` must match the preceding `phase_after`.
The final row is compared against the last recovery observation, not treated
as an unrelated assertion. A missing final row is unproven. Uncertainty from
any observation persists until a later `provider_read_back` settles that same
intent, even if a later row claims a different phase. Such an unsupported
phase change is erased uncertainty and fails; omission cannot hide it.

## Findings, gaps and gates

A finding has `id`, `severity` (`blocker`, `high`, `medium`, `low`),
`work_loss`, `summary`, `owner` (the corrective ticket, or null until one is
filed) and `disposition` (`open`, `fixed`, `accepted_gap`). A blocker or a
work-loss finding that is not `fixed` fails the attempt: a known way to lose work
blocks launch and is never an accepted gap. Other limitations stay visible.

A gap names the claim (`PR1` to `PR8`) and why its evidence is missing. A gap
on PR1 or PR4 keeps the result unproven.

**The three unresolved interface gates.** Their decision tickets own their later
interfaces; this contract defines none of them: no CloudRoom installation
transport or provider call, no paid benefit, payment arrangement or entitlement
rule, and no feedback transport, recipient or sharing rule. The `paid_offer`
gate keeps its name and schema for the free-only release: settled, it records
that free-only copy and evidence were produced, never a paid offer, trial or
payment.

| Gate | Decision ticket | Today |
| --- | --- | --- |
| `cloudroom_setup` | #2201: David's agreement on automatic installation, sign-in and branding, and the usable-login evidence source | `unresolved` |
| `paid_offer` | #2202: the free-only friends-first release, agreed in [public-offer.v1](public-offer.v1.md): no paid offer or payment code, and Paid plans come later. Its one approved producer is #2293 (the free-only install, site and app copy and the no-paid-offer review); it settles no paid benefit, payment arrangement or trial, and needs no trial receipt | `unresolved` until #2293's verified merge; then `settled`, with producers `[2293]` |
| `feedback` | #2203: the feedback destination and transport, consent and public-only sharing, agreed in [feedback.v1](feedback.v1.md). Its one approved producer is #2292 (the `feedback` skill and the app's handoff and share) | `unresolved` until #2292's verified merge; then `settled`, with producers `[2292]` |

A gate is `unresolved` with no `producers`, or `settled` with its producer
tickets listed. An unresolved gate keeps the result unproven. A producer counts
only once it is added through a revised #2194 plan graph, under plan-graph's
change control and Jake's approval, as an exact native blocked-by link on every
consumer it affects (#2205, #2206 and #2207 at least), and only after its
verified merge, not its closure. The integrated acceptance (#2207) cannot run
before then, and this contract is revised to name the settled interfaces.

## The verdict

The checks sort what a record shows into three lists:

- **Problems** make the record itself refused: a schema error, stages out of
  order, a stage or seat `verified` on an observation that never establishes it,
  a clock that ends before it starts, a wait or help outside the clock, a
  synthetic label that does not match the proof class, a `live` record without a
  pointer, a non-`live` pass, a gate's producers that do not match its state, an
  inconsistent ten-minute measure, an effect count that does not match its phase,
  an inconsistent explanation, a pass with anything unproven, or failures
  reported as anything but `fail`.
- **Failures:** a missed hour, a stage that ends `failed` or `refused`, lost
  work, a duplicate effect, a blind retry, erased uncertainty, or an unfixed
  blocker or work-loss finding.
- **Unproven:** a class other than `live`, an unknown candidate, repository or
  clock, a stage not verified, a seat not usable, a reviewer of the builder's
  family, a prepared or private help, an operation still uncertain, retention
  shown only by tab storage after a browser restart, a PR1 or PR4 gap, or an
  unresolved gate.

The codes, for every consumer (#2204, #2222, #2207) to report exactly:

| Code | List | Given when |
| --- | --- | --- |
| `not_strict_json` | problem | the text is not strict JSON (duplicate key, fraction, constant) |
| `schema` | problem | the document does not match the schema; nothing else is checked |
| `stage_order` | problem | the stages are not the ten ids in their order |
| `stage_weak_evidence:<stage>` | problem | `verified` with no evidence of the stage's establishing basis |
| `seat_weak_evidence:<role>` | problem | `usable: verified` with no `harness_run_observed` |
| `stale_evidence:<stage or role>` | problem | the establishing evidence lies outside the clock |
| `clock_order` | problem | the clock ends before it starts |
| `outside_clock:<wait or help>:<index>` | problem | a wait or help lies outside the clock, or a wait ends before it starts |
| `synthetic_live` | problem | a `live` record with synthetic assumptions |
| `synthetic_unlabelled` | problem | a non-`live` record without them |
| `live_without_private_record` | problem | a `live` record without a pointer |
| `gate_producers:<gate>` | problem | a gate's producers do not match its state |
| `ten_minute_inconsistent` | problem | the ten-minute state does not match its elapsed time |
| `phase_effect_mismatch:<operation>` | problem | an effect count that does not match its phase |
| `phase_attempt_mismatch:<operation>` | problem | applied or uncertain with zero provider calls |
| `duplicate_work:<inventory>:<kind>:<id>` | problem | repeated work identity in one inventory, even with identical content |
| `duplicate_operation:<inventory>:<operation>` | problem | repeated intent identity in one operation inventory |
| `work_history_mismatch:<kind>:<id>` | problem | the same commit or pending intent has conflicting immutable content across inventories |
| `operation_history_mismatch:<operation>` | problem | an intent's kind, cumulative counts or successive phases contradict its prior observation |
| `explanation_inconsistent:<case>` | problem | `took_effect` is not what the case's operations show |
| `non_live_pass` | problem | a pass from a fixture or a recording |
| `unproven_pass` | problem | a pass with anything unproven |
| `failure_not_reported` | problem | a failure with a verdict other than `fail` |
| `hour_missed` | failure | elapsed time above `3600000` |
| `stage_failed:<stage>` | failure | a stage that ends `failed` or `refused` |
| `work_lost:<kind>:<id>` | failure | an item missing or changed after a case |
| `duplicate_effect:<operation>` | failure | an effect count above 1 |
| `blind_retry:<operation>` | failure | more than one attempt without `provider_read_back` |
| `uncertainty_erased:<operation>` | failure | leaving `uncertain` without `provider_read_back` |
| `open_blocking_finding:<finding>` | failure | a blocker or work-loss finding that is not `fixed` |
| `not_live` | unproven | a fixture or a recording |
| `candidate_unknown` | unproven | the candidate is unknown |
| `repository_unknown` | unproven | the repository is unknown |
| `clock_unknown` | unproven | either clock time is unknown |
| `stage_unverified:<stage>` | unproven | a stage `missing` or `unknown` |
| `seat_unusable:<role>` | unproven | a seat not `usable: verified` |
| `reviewer_not_independent` | unproven | the reviewer's harness is the builder's |
| `prepared_help` | unproven | help from a `prepared_plan` or a `private_instruction` |
| `operation_uncertain:<operation>` | unproven | an operation still `uncertain` at the end (in a `recovery`, after its case) |
| `recovery_work_missing:<case>` | unproven | no original work inventory to prove preservation |
| `recovery_operations_missing:<case>` | unproven | a setup interruption, lost reply or repeat approval has no operation observation |
| `recovery_operation_missing:<case>:<operation>` | unproven | an original pending item lacks its operation observation |
| `recovery_intent_missing:<case>:<operation>` | unproven | an observed operation lacks its original pending item and request fingerprint |
| `final_operation_missing:<operation>` | unproven | an intent touched during recovery is absent from the final inventory |
| `retention_unproven:<kind>:<id>` | unproven | an item read only from tab storage after a browser restart |
| `gap:<claim>` | unproven | a PR1 or PR4 gap |
| `gate_unresolved:<gate>` | unproven | a gate not `settled` with producers |

`verdict` must be `fail` when there is any failure; `pass` only for a `live`
record with a pointer, no synthetic assumptions, no failure and nothing
unproven; otherwise `unverified` (or `fail`, which a reviewer may always
choose). No fixture or recording is ever a live pass, and missing, invalid or
stale evidence is never success.

## Existing owners

Existing plans keep their work; this contract only names where each stage's
evidence comes from.

| Plan | Owns |
| --- | --- |
| #1093 (0.0.13) | Verified packages #1100 and #1102, connections #1105, engine #1106, authenticated access #1107, fresh idea #1108, install journey #1109, live proof and the ten-minute target #1110 |
| #1211 (0.0.14) | Machines, placement and the durable engine (#1214 to #1220, #1406); not a first-hour prerequisite |
| #1829 (0.0.15) | Phone alerts (#2033 to #2040); not part of the first hour |
| #1257 | Open development, privacy tooling (#1270, #1271), rehearsal, cut-over and public-factory proof (#1284 to #1286) |
| #2183 | Release on demand: candidate interface #2186, #1148, #1843, #1844 and the release #285 |

Within #2194: the recovery and recording component #2222 and the installed
journey #2204; the pages #2221, #2223 and #2205; the security reviews #2220 and
#2206; the timed live hour #2207; the first users #2208.

## Privacy

Public records carry synthetic or sanitized technical values only. Raw account,
machine and session evidence and exact decision words stay in ClosedWiz, reached
through `private_record`. Details and reasons are plain technical text: no
thread id, token, credential, prompt, transcript or private code.

## Proof limits

The schema checks parsed shape. The checks in
`tools/install/tests/first-hour-contract/` prove these cross-field rules on the
synthetic examples. Together they prove interface consistency only:
implementation, independent security and visual review, real time, usable live
logins and the live first hour remain Unverified until their own evidence.
