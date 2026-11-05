# Ops dispatch discovery — OB1 (#2187)

2026-11-10. **Record/claim/refusal contract prepared under revision 3; external
capabilities remain Unknown.** Preparation targets ClosedWiz. No cut-over,
activation, live acceptance or publication is authorized by this report.
Earlier discovery/amendment requests below are retained as historical evidence;
the current bounded delivery is described in the revision 3 section. Independent
exact-head review and CI still gate the delivered contract.

## Authority and method

At the initial checkpoint, spec #2185 revision 1 matched its approved revision-v2 bytes and
fingerprint `6ebc7cea7438b006af89a173b8a8b415cb8e787d78c21501f1f5ed5dbfb41abf`.
Its approval is recorded in the [private approval record](https://github.com/jparker2006/ClosedWiz/issues/2185#issuecomment-6757843666).
The confirmed grill is the immutable PR #2181 head named by that spec.

The initial discovery followed the [standing read-only permission](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951):
allowed help/version and listed inventory/output reads, launcher/client source
reads, at most 200 calls, 20 sessions by ID and 30 minutes. Host source inspection
used `room-cli mac run` without `--write`, with the required PATH prefix, and
returned structure only. No credential/configuration file was read. The PC
endpoint calls require a Local thread there; this cloud builder did not launch
one or treat host access as permission to bypass that restriction.

That initial spike made no dispatch, tell, relabel, merge, loop/configuration change,
new-access request or spending probe. Builder bookkeeping and the separately
authorized checklist helper are outside the spike and establish no endpoint
capability. No session was read by ID for discovery.

## Observed capability matrix

“Advertised” means CLI help, “source” means inspected code, and “Unknown” means
the required capability has not been established. None is live acceptance.

| Required capability | Observation and evidence class | Limit / certification |
| --- | --- | --- |
| Cloud starts | Cloud CLI help advertises provider/model/effort and child starts, shared sandboxes and top-level starts. | No start was attempted as discovery. Help exposes no operation-key/generation or request-ID outcome-lookup interface. Deduplication and lost-reply reconciliation are **Unknown**, not disproved by absent flags. |
| Cross-tick and cross-machine ownership/access | Cloud thread help describes child output, child lifecycle and target/parent tells. Existing launch-fleet instructions explicitly describe parent-only output/tell access. | A fresh tick/standby reaching another owner's builder or reviewer is **Unknown**. No existing agent was messaged or replaced to test it. Historical instructions are not a new reachability observation. |
| Independent wakes | Cloud loop help advertises scheduled fresh-thread/same-thread runs, webhook wakes and operation while the paired machine is off. | This is an advertised interface only. No loop was installed, read for secrets or activated; existing recipient/standby access and wake independence during an outage remain **Unknown**. |
| Reviewer evidence | Existing merge policy requires the selected reviewer's own output at the exact head. Cloud help exposes child output. | Authenticated reviewer output from a fresh non-parent/standby is **Unknown**. A shared-account APPROVE comment is insufficient. |
| Spawn reconciliation | The existing Rust adapter emits a request ID; its executor uses durable local start state and explicit uncertain outcomes. | Repository source, not an observation that the current endpoint accepts/deduplicates this shape. Cloud help differs; endpoint parity and cross-machine outcome lookup are **Unknown**. |
| Dispatch fencing | No generation/operation-key enforcement interface was identified in cloud help or the bounded host launcher/client source inspection. | **Unknown**. The effect must reject an old executor resumed after its last check; a lease comment, local lock or pre-call recheck does not establish that. |
| Release fencing | Existing release paths apply policy and GitHub label effects. | No enforcing external generation check was established. Relabeling was not probed. **Unknown**, including partial-outcome reconciliation. |
| Merge fencing | Existing merge paths verify current authority, reviewer output, CI and base conditions. | No externally enforced repository merge generation was established. No merge was attempted. **Unknown**; exact-head checks alone do not fence a superseded owner. |
| Git-reference claim storage (later bounded probe) | One throwaway reference: create succeeded, duplicate create failed, forward updates succeeded, backward update failed, delete/absence verified. | Observed ref semantics only. Non-force is not an expected-old-SHA comparison; external effect-generation enforcement remains **Unknown**. |

Cloud help reported `cloudroom 0.1.104 (a8fe970947ba)`. Its executable is a native
binary; its help is not source inspection of the server. Host inspection found
multiple packaged client candidates with two distinct content hashes, without
establishing which running server they serve. No generation/request-ID/operation
key literal was found in those candidates. That lexical result cannot establish
absence of server-side support. Machine paths and structural output stay in the
private discovery evidence; no live identities or session content are included
here.

## Later Git-reference disposition and probe

The [orchestrator disposition](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6758635998),
[ops relay](https://github.com/jparker2006/ClosedWiz/issues/2187#issuecomment-6759130075)
and subsequent user assignment authorized only bounded throwaway ref operations
under `refs/heads/ow-fence-test/` in ClosedWiz, with deletion afterwards. This is
separate narrow write authority, not an extension of the CloudRoom read-only
standing permission. It grants no dispatch, release, merge, access, wake or
reviewer-authentication authority. The approved full plan revision still matches
revision 1; this disposition does not silently change its guarantees.

[GitHub's reference API documentation](https://docs.github.com/en/rest/git/refs#update-a-reference)
lists `sha` and `force` as update body fields: non-force checks ancestry, without
an expected-old-SHA field. The bounded probe used three existing commits in a
known A→B→C chain, one newly named ref and no new Git objects:

| Step | Actual observation |
| --- | --- |
| Initial absence | GET returned 404. |
| Create at A | POST returned 201. |
| Duplicate create at B | POST returned 422, reference already exists; read-back remained A. |
| Advance to B | PATCH with `force:false` returned 200. |
| Caller remembering A submits C after B | PATCH with `force:false` returned 200; read-back was C. No old-SHA or generation condition was submitted. |
| Backward update to A | PATCH with `force:false` returned 422, not a fast-forward; read-back remained C. |
| Cleanup | DELETE returned 204; GET returned 404. |

Total: 12 API calls, six mutation attempts, one ref deleted and absence read
back. The retained private plan, runner and receipt are under the owned
discovery evidence path. No CloudRoom call, pre-existing-ref change, new object,
loop, helper, STATUS edit or permissions change was part of this probe.

The observation disproves the proposed equivalence between a non-forced update
and comparing the current ref to a caller's expected old SHA. It does not test
concurrent ownership or prove that every ref-based coordination design fails:
incompatible commit ancestry can reject competing ref updates. Even exclusive
claim admission is only admission to that reference. No observed mechanism
couples it atomically to each later dispatch, label-release or merge effect.

Unexercised failure trace: owner G1 records an intent/check and pauses before
the actual effect; G2 takes over the ref; G1 resumes its already-authorized
external call. A ref check alone supplies no demonstrated rejection by that
other endpoint. This is a protocol gap identified by reasoning, not a live
stale-owner experiment. Those external effects were neither authorized nor
performed by this probe. P5/P7 are not certified.

Likewise, reading thread state before retry requires a discovered, complete,
operation-bound outcome lookup and proof of non-execution; no such guarantee
was established here. Pending GitHub records do not wake an idle recipient or
establish access independent of the unavailable hub. Neither refs nor
shared-account comments authenticate the selected reviewer's own output.
These requirements remain **Unknown**, as do independent access/wakes and
uncertain-spawn recovery. P3–P5/P7 live evidence still belongs to OB8 under its
separate permission gates.

## Revision 3 bounded delivery

The [scope answer](https://github.com/jparker2006/ClosedWiz/issues/2187#issuecomment-6759946483)
and [revision 3 approval](https://github.com/jparker2006/ClosedWiz/issues/2185#issuecomment-6759925592)
resolve the contract-delivery scope under OB-A1. The complete current revision
was reread through checked REST transport using the existing approval-table and
revision scripts during GraphQL exhaustion; bytes match the approved text and
fingerprint `fcb2c9fd5dc8fa6422cfcd0f848b0dfb3018bc2a9d00b12ba0a6c4fba3540f54`.

The [ops contract](../../contracts/ops-dispatch.v1.md), schema, synthetic examples
and offline handlers now specify durable intent/pending notification, exact
envelope/grant material, monotone record generations, per-generation/operation
create-if-absent admission, outcomes/ACK/completion, full ON1 cutoff/holds, audit
cursors and finite refusal results. Malformed/ambiguous/stale inputs refuse;
all new unfenced effects stay disabled even after a successful reference claim.
No new probe, endpoint observation or production dispatch is part of delivery.

The retained capability matrix is unchanged in evidence class. It does not
establish external fencing, complete outcome lookup, independent wakes/access
or reviewer authentication. #2244 owns only the unstarted Local discovery in
its separate `local/` evidence directory. P5 remains Unverified; P3–P5/P7 live
evidence and all enablement permissions remain gated. The contract's consumer
ownership table checks all seven downstream path envelopes against these
bounded record/refusal interfaces; it certifies no unavailable behavior. The
mechanical tick schema retains its fields and current behavior, with a pointer
distinguishing agent judgment from mechanical due detection; no Rust parity is
claimed.

## Historical downstream path fit and amendment request

The following assessment preceded OB-A1/revision 3. Its scope question is now
answered for bounded contract delivery, while its external capability gaps
remain unresolved. It is not a new hold or request to repeat discovery.

The approved owned paths were read for all seven consumers:

| Consumer | What it needs | Result against discovered boundary |
| --- | --- | --- |
| #2188 OB2 | Envelope/grant/invalidation/audit record contract | Contract remains deferred; supporting authority must supplement, never change, the approved plan fingerprint. |
| #2189 OB3 | Actual effect admission and reconciliation | Its new `effects.py` and tests can implement a client wrapper, but no evidence establishes an external door that checks its generation. External endpoint enforcement edits are not among its owned paths. Amendment needed before claiming sufficiency. |
| #1456 OB4 | Independent finite wakes and private routing | Scripts/configuration preparation cannot establish access to non-child agents or independence from an unavailable hub. Discover or amend access before implementation. |
| #1480 OB5 | Fenced starts and lost-reply lookup | No current endpoint start deduplication/lookup contract established. Do not synthesize a successful endpoint. |
| #1481 OB6 | Ordered durable inbox, recipient wake/ack and reviewer continuity | GitHub persistence alone does not establish recipient wake or authenticated cross-owner output. |
| #2112 OB7 | Fenced release, inclusive cutoff and complete hold history | A pre-effect GitHub read cannot substitute for actual effect-boundary fencing. Preserve every unrelated hold and unresolved partial outcome. |
| #2190 OB8 | Observed interfaces for separately authorized bounded acceptance | No outage/access/fencing/live result certified; P3–P5/P7 live claims remain Unverified. |

Recommendation for the orchestrator: identify the existing enforcing endpoint
and authorize bounded inspection from its permitted execution context. If it
has no sufficient interface, use hold-first plan amendment to name the actual
endpoint enforcement owner, exact source paths, monotone-generation and stable
operation lookup semantics, and independent reviewer/recipient access and wake
doors. Obtain any required interface/access/dependency permissions before that
work. Do not substitute a new broker or advisory client token without approval.
If only preparation within current paths is approved, keep unsupported effects
blocked and remove any availability/completion claim through an approved replan.

The Git-reference proposal does not close this path gap. Smallest hold-first
amendment for #325 to resolve: distinguish ref-backed coordination from the
still-disabled effect doors in #2185/#2187/#2189, and name an explicit enforcing
prerequisite before consumer implementation/certification. That prerequisite
must identify the existing execution component, its actual owner and exact
source paths; the atomic generation/operation admission and uncertain-outcome
lookup for dispatch/release/merge; and the independently reachable recipient
wake and selected-reviewer output routes with their permitted execution
contexts. Endpoint source paths and a sufficient existing mechanism are still
unknown, so a ready-to-approve external file list cannot honestly be supplied
from this probe. Merely widening the client's `effects.py` ownership would not
establish enforcement outside that client. Do not add a broker, credential,
service or access right by inference. If those mechanisms cannot be named within
existing authority, keep the effects blocked and take the concrete interface/
permission/scope change through the existing reapproval gates. A reduced
coordination-only scope would also require explicit plan reapproval; it cannot
count as completion of the current guarantees.

## Claim/proof status

| OB1 acceptance criterion | Evidence now | Remaining proof |
| --- | --- | --- |
| Observed permitted-door matrix | Retained help/source/ref observations, this matrix and revision 3 boundary | External fencing remains Unknown; unstarted outcome/access discovery belongs to #2244; independent exact-head report review still required. |
| Verify authority and bounds | Initial standing read-only approval, then separate narrow throwaway-ref permission and retained receipt | Ref writes stay separately classified; no dispatch/release/merge or CloudRoom effect was probed. |
| Complete versioned fields/transitions/interfaces/routing | Ops schema/contract and strict record/refusal handlers under revision 3 | Source authentication and actual runtime integrations remain with consumers; no callable effect is enabled. |
| Crash/duplicate/stale/grant/ack/cutoff fixtures | Red-first skill-local synthetic conformance proofs | Fixtures prove record/refusal semantics only, not recovery, wake/access, ACK authenticity or P5. |
| Preserve standing rules; check downstream paths | Contract consumer matrix, glossary/tick distinction and current revision 3 fingerprint | Exact-head review and CI gate this bounded contract; actual effect enablement retains all other prerequisites. |

The future proof must cover P1/P2 envelope, exact grant and audit schemas; P3/P4
intent/claim/transport/recipient acknowledgement/completion/supersession and
finite-resume outcomes; P5 stale generation and uncertain effects; P6 inclusive
ON1 cutoff/hold races; P7 all protected authority gates; and P8 finite record/end
outcomes. Each needs independent literal expectations and red-first failures at
the approved external-record/handler seam. Synthetic capabilities must be
labelled assumptions and cannot certify discovery or live recovery.

No Rust/mechanical-tick parity is claimed. Agent judgment may assess an approved
grant or ON1 evidence; mechanical due detection and current Rust effect paths
retain their existing contracts. C2 and red-main assessment remain
orchestrator-only; CT1 and factory-skill authority remain bounded. Approval
currentness, native verified blockers, exact-head other-family review, 2 + 1,
green CI, M1/re-test, merge read-back, dependencies, live/machine, activation,
spending, cut-over, release and publication gates remain unchanged.
