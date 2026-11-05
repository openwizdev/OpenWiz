# Notification and ready-stock contract v1

`openwiz.notifications.v1`, 0.0.15 T1 (#2032), spec #1829. The strict schema is
[notifications.v1.schema.json](notifications.v1.schema.json). The usable core
interfaces are `notifications::model` and `notifications::boundary`. Named
synthetic examples live in `tests/fixtures/notifications/contract/README.md`.
This is an interface, not an installed notification path. PA1–PA7 have interface
fixture proof only; PA8, actual phone display and live delivery remain Unverified.

## Records and strict reading

Every document is exactly `{schema: "openwiz.notifications.v1", record: {name: value}}`.
There is exactly one named record: `source_fact`, `preferences`, `preference_write`,
`subscription`, `subscription_write`, `capability`, `dispatch`, `status`, `stock`,
`target_result`, `submission` or `delivery_outcome`. Source facts and references
are similarly one-key `decision`, `incident` or `event` objects. These are tagged
records, not the alternative tagged-object spelling of a string enum.

Every schema-listed property is required except the explicitly optional extension
mounts in service/cockpit. Objects are maps only, with every key exactly once;
no positional objects, unknown fields or duplicate keys at any depth. String enums
accept only exact strings. Numbers are unsigned JSON integers, not strings,
booleans, negatives or wire spellings such as `1.0`. Issue/comment numbers are
positive. Times are epoch milliseconds. Reasons are nonempty, sanitized public
text. Identifiers use the schema's ASCII grammar. Repository identity is the
canonical lowercase `owner/name`, resolved by the configured source, never a URL.
Fingerprints/tokens are 64 lowercase hex; effect operation ids are 32 lowercase
hex. Schema validation cannot detect duplicate wire keys or prove source authority.

`Document` has a strict map reader and round-trip serializer. After decoding, call
`Document::check` for local consistency (coverage, times, counts, outcome agreement,
unique project/category membership). Source readers must additionally verify
provenance, identities, lifecycle order, freshness arithmetic and full enumeration.
Do not treat a deserialized value, a schema pass or a fixture's `current: true` as
that verification. The schema's freshness alternatives enforce timestamp shape;
the source clock and semantic checks still decide whether that timestamp is fresh.

## Source facts, eligibility and category catalogue

Preferences start at generation 0, delivery `enabled: false`. Every category has
its own required boolean; `decision` and `recovery_escalation` alone default true.
That selection is not permission to deliver. Unsupported sources retain their
category, toggle and explicit unavailable reason. Enabling one never installs a
source, prompts permission on visit, approves work or changes recovery policy.

The fixed catalogue is below. The reason column describes the unavailable case;
producers publish the actual sanitized reason in `status.sources`, exactly once
per category, including disabled categories. Source availability is a known/unknown
fact; unknown is never available. T1's constructor marks every binding unavailable.
T3 supplies verified source bindings; it must retain any gap it cannot close.

| Category | Default | Owning facts and identity | Unavailable reason |
| --- | --- | --- | --- |
| decision | on | Existing decisions reader: configured repository, GitHub subject/comment, request id, fingerprint; all four structured request kinds | Independent saved wording/current proposal or configured answer-target verification unavailable; the current route explicitly reports this gap |
| recovery_escalation | on | Existing recovery owner: stable engine-state owner, source, subject, incident, explicit `needs_you`/owner escalation | No explicit owning escalation; active repair, unread health or watchdog fault alone is insufficient |
| ci_failed | off | Existing event router's independently current repository/PR/head/CI fact, not webhook delivery id | CI facts unread, current head/ownership unknown or production intake unavailable |
| review_findings | off | Existing router's current repository/PR/head/findings record | Findings/current head or owner cannot be verified |
| re_check | off | Existing router's repository/PR/head/re-check fact | Current re-check identity or ownership unavailable |
| merge | off | Existing fleet/plan GitHub merge readback, exact repository/PR/merge commit | PR closed or event hint alone supplies no verified merge |
| agent_complete | off | Explicit terminal completion from the owning builder/loop record, bound to its run/ticket/revision | Inactive/missing inventory or a created thread alone proves no completed work; no authoritative terminal fact available |
| ready_stock_changed | off | T6 projection over plan/fleet/approval facts, previous and current complete fresh snapshots | Project enumeration, verified blockers, ownership or prior complete stock unavailable |
| loop_missed | off | Existing loop watchdog `Missed`, loop id and due occurrence | Missing history/next due or production observation unavailable |
| loop_stuck | off | Existing watchdog `Stuck`, loop id, run id and immutable timeout | Run history or original definition timeout unavailable |
| loop_disabled | off | Existing watchdog `DisabledByFailures` with positive provenance | Off plus historical failures does not prove failure-disable provenance |
| loop_run_changed | off | Existing loop run id, definition revision and recorded result transition | Current immutable run/definition or result unavailable; thread creation is not completion |
| recovery_changed | off | Existing health owner, subject/incident and positively observed repair/recovery transition | An absent/dropped record or unread check does not prove recovery |
| service_update | off | Existing service update record, exact candidate/from/to/outcome and saved operation | Update result or candidate identity unread/unresolved |
| contract_changed | off | Existing fleet tick's bound contract-change/hold fact and proposed revision | Current contract/revision read unavailable |
| fleet_wait_changed | off | Existing fleet tick's explicit held/needs-info/re-approval/person-ready/diagnosis state, exact ticket/revision | Waiting reason or marked comment missing/ambiguous; labels alone prove no decision wording |

All optional events use `EventFact` with a stable `EventRef`: repository, owning
source, subject, source event/occurrence id and revision. Its category must match
the catalogue's owner. A source transition's stable id is reused on duplicate or
replayed observations; poll time, transport delivery id and list position are not
logical event identities. CI/review use the router's canonical PR/head/kind key;
loop events use immutable run/occurrence identity; merge uses verified merge commit.
No raw webhook grants authority. If no positively bound stable event identity
exists, publish unavailable rather than invent one. Categories are a closed list,
not a general rule language; new categories require a contract change.

Default decision eligibility requires `state: open`, `current: {known: true}`,
known explicit risk, complete fresh source/target checks, and an unanswered
current request under decisions.v1. Source subject/comment identity is GitHub
metadata, never request-supplied JSON. Re-read exact saved wording, question,
summary/headline, risk, fingerprint and configured answer target. Unknown, stale,
resolved, superseded or ambiguous requests are ineligible, not absent.

Default recovery eligibility requires `state: escalated` and
`owner_escalated: {known: true}` from the existing recovery owner, complete fresh
facts and the same current incident. Reuse service.v1's existing two-tries/Needs
you rule, including its existing no-fix cases. The loop watchdog's pure faults
supply no independent escalation policy. A single failed check, active repair,
source outage or a stopped engine cannot be relabelled unrecoverable by a notifier.
Optional recovery changes never bypass this default escalation rule.

For every category, T3 policy also requires current owner enable/category choice,
current permission, a ready subscription and an available observed delivery
boundary. Unknown facts stay visible in status and Needs you. The transport
boundary performs no policy or recovery decision of its own.

## Group identity and lifecycle

Decision logical identity is `(repository, subject.kind, subject.number,
request_id, fingerprint)`. The reference additionally binds `comment_id` for
exact navigation. Copying the same request to another comment is ambiguity to
report, not a second alert. Incident identity is `(repository, owner, source,
subject, incident)`; `owner` identifies the durable recovery-state namespace,
not a process id. This prevents state-local incident `i1` in another installation
from collapsing into this incident. Replaced fleet threads retain their owner's
incident. Optional events group by category and their stable EventRef tuple.

Persist group identity before any dispatch; duplicate, late and replayed facts,
concurrent passes and restarts reuse it. Use an unambiguous canonical tuple or
length-delimited/domain-separated hash, never concatenation with ambiguous
separators. `group_state` is open or closed. Resolution, supersession or positive
recovery closes the old group permanently; a late open observation cannot reopen
it. A genuinely different fingerprint/request or new owner incident is distinct.
Do not expire tombstones in a way that permits replay. A preference generation or
subscription change does not create a new logical alert or erase an unresolved
attempt. Changing wording/risk/target invalidates eligibility even if a source's
fingerprint has not changed. T3 owns those durable source-order/currentness rules.

## Delivery effect and durable journal

`Submission` contains dispatch id, bound reference, preference and subscription
generations and the minimal external payload. The installed engine, not an open
page or permanent AI notifier, calls `DeliveryBoundary::submit` at most once for
one reserved attempt. T4 supplies an adapter only from T2's positively observed
binding and separately approved exceptions. T1 adds no production transport,
subscription provider, command, dependency or CloudRoom allowlist expansion.

T3 must serialize preference/subscription mutations and admission under the same
protected per-owner lock/transaction. Under that lock: read group/attempt and
current sources, independently recheck currentness, read both generations and all
prerequisites; atomically reserve an id plus exact payload/binding/generations and
sync it durably. A failed read/lock/save makes zero submissions. Before crossing
the submit boundary, re-read eligibility and both generations, cancel an untouched
reservation if changed/disabled/revoked, then durably mark `submitting`. Submit
while holding admission serialization so disable cannot overtake this boundary.
A generation change never authorizes reuse of an older admitted payload.

| From | Next | Required evidence/effect |
| --- | --- | --- |
| no attempt | reserved | Unique group reservation committed and synced; no external effect yet |
| reserved | cancelled | Currentness, enable/category, permission, subscription or generation recheck failed; zero submission |
| reserved | submitting | Recheck passed and submitting mark synced before the one call |
| submitting | pending / accepted / failed / uncertain | Exact boundary reply persisted under the same dispatch id |
| pending | accepted / failed / uncertain | Bound provider result, never inferred from silence |
| submitting / pending / uncertain | accepted / failed | Independent exact-operation reconciliation; a later unrelated refusal is insufficient |
| accepted / failed / cancelled | none | Terminal for this attempt; duplicate observations do not submit it again |

`pending` means the boundary acknowledges a still-unsettled attempt; `accepted`
means only dispatch acceptance. `failed` requires positive evidence that this
attempt was not accepted. Lost reply, timeout, crash after the submitting mark,
unread reconciliation or failed outcome persistence is `uncertain`. Restart may
continue an untouched reserved item only after full recheck; a submitting record
recovers as uncertain, never as unsent. No blind retry of pending/uncertain and no
uncertain-to-failed downgrade except bound reconciliation. Record uncertainty even
when a later call is refused. The transition table is usable as
`DispatchState::permits`; T3 proves persistence/concurrency/crash behaviour.

Disabling commits a higher preference generation, cancels unsubmitted reservations
and prevents every later admission. A submission already across the serialized
boundary may complete and cannot be retracted. The response and status explain
that limit. Revoking/removing a subscription has the same admission rule. An
uncertain in-flight outcome survives disable/restart. Preferences/subscription
writes never answer a question, start work, merge, recover or send CloudRoom text.

`UnavailableDelivery` returns failed/no attempt and has no I/O; its capability
is unavailable. `RecordingDelivery` records in memory and returns only explicitly
scripted fixture replies; exhaustion is uncertain. It always reports unavailable
capability, so it cannot masquerade as an installed provider. No state means
received/displayed on a phone, answered, or completed agent work.

## Capability, preferences and honest status

Capability states: unavailable (binding not installed/unknown), unsupported
(positively unsupported), setup_required, ready. Permission: unknown, prompt,
granted, denied, revoked, unsupported. A native permission prompt occurs only on
the owner's explicit enable gesture, never install/visit/refresh. Saving enabled
true alone neither prompts nor proves permission. Subscription is absent, ready,
revoked, failed or unsupported; only ready has a currently verified protected
binding. Keep generation and safe reason/next step across refresh/restart.

Status is off, unavailable, unsupported, setup_required, permission_denied,
permission_revoked, ready, pending, accepted, failed or uncertain. Off reflects
the current preference while `latest` retains any prior/in-flight dispatch.
Ready means current prerequisite verification, not receipt. Preserve source
coverage/freshness separately and never hide Needs you or stock for delivery
failure. `Status::unavailable` is off, binding unavailable, subscription absent,
all category sources unknown, no last dispatch and no fabricated snapshot.

## Privacy and authenticated navigation

Only `ExternalPayload {title: "OpenWiz needs your attention", target_token}` crosses
the provider boundary. The opaque token is a random/unpredictable 64-hex lookup
key; it carries no request wording, repository/subject/incident ids, target thread,
prompt, transcript, credential, endpoint or key. Persist its exact reference in
protected owner state before dispatch; never log the token. It is a reference,
not authorization. Subscription endpoints/keys and binding material remain only
in protected owner state, never API output, process arguments, logs or Git.

A worker accepts only this exact payload and constructs the same-origin shell
fragment `/#notification=<token>`; no supplied URL, origin, path or redirect is
trusted. T5 resolves `GET /api/v1/notifications/targets/<token>` only after existing
owner authentication. Re-read the exact reference, report current/changed/resolved/
missing/ambiguous/unread, then fetch detail through existing authenticated routes.
A guessed/unknown token reveals no detail. Missing or unavailable references
never select the next list item. Unknown access state refuses detail. Receiving,
opening, dismissing and repeating only navigate; zero answers/work effects.

The T5 target-resolution HTTP interface is pinned here: exact
`GET /api/v1/notifications/targets/<token>`, no body or query (including `?`).
The token is exactly 64 lowercase hex. An authenticated mapped reference returns
200 `Document {record: {target_result: TargetResult}}` for current, changed,
resolved, missing, ambiguous or unread source state. Missing/expired token mapping
returns 404 `no_route` without detail; malformed token/query is 400
`invalid_request`, GET body is 400 `bad_request`, other methods are 405 with
`Allow: GET`. HEAD has no body or Content-Length. Existing Host/framing, shared
read-slot/deadline rules apply: busy 503 with Retry-After and deadline 504. Owner
access refusal/expiry is 401/403 before reading detail or any effect. All replies
use the existing API error envelope/security headers, application/json, no-store,
no CORS, no Set-Cookie, and no API cache. Log only the sanitized route
`/api/v1/notifications/targets/*`, never a token/reference or credentials. These
are bound-navigation interface rules for T5; T1's shared web-api addition remains
limited to preference/subscription/status routes. The same-origin shell fragment
needs no server query exception. This GET has zero answer/start/merge/recovery or
delivery effects, including on refresh/reorder/reconnect.

An explicit answer uses the existing decisions card, fresh verified wording/risk/
question/target binding, existing send id and once-only receipt. Live, release and
publish retain distinct second confirmation. An incident opens its owning status,
never becomes an approval or a recovery action. The worker retains shell-only
caching, no API cache, background answer, queued write or replay on reconnect.

## Ready stock and source coverage

`Stock` is independent of all notification choices. It contains all configured
projects once by stable project id, each with coverage, oldest-source freshness,
known/unknown current counts and optional last-good sample. Totals are known only
for complete fresh project enumeration and complete fresh required project facts;
otherwise totals are unknown with reasons and gaps. A last-good sample retains
its original time/counts and does not refresh current data. Never turn unread
counts into zero or drop a missing configured project. A missing project prevents
a complete factory-wide conclusion even when other projects are healthy.

Counts partition open tickets into ready, running, blocked, held, unapproved,
owner_wait, capacity_wait and unknown; no ticket appears twice. Count known
builders first using plan-links' recorded start/open matching PR measure, even
if their ticket is now blocked. This is a ticket measure; it does not replace
cockpit.agents' positively observed active-inventory measure. For remaining work,
use unapproved, held, owner wait, blocker, capacity and ready in that precedence;
if a required classification fact is unread, use unknown, never a lower bucket.
Closed tickets without verified merge are unknown where their disposition affects
the classification. Human-ready/needs-info count owner wait. Held is not ready.

Ready requires open approved work under plan-links' approved-label universe, no
builder, no hold/owner wait and startability verified from the existing plan/fleet
facts. An open native blocker prevents it; a closed blocker must additionally
have verified merge evidence under fleet/plan rules. Capacity wait requires a
positive current capacity refusal from the owning scheduler/placement source,
not a locally invented cap; absent capacity information is unknown if needed.
T1 adds no scheduler or private-board dependency. T6 owns projection and joins.

For known counts, unknown > 0 makes state indeterminate. Otherwise ready == 0 is
running_dry even while builders finish. With ready > 0 and running == 0 state is
no_builders and the actual ready count is shown, no reassuring ratio. For positive
running, ready >= 2 * running is fed, otherwise low_stock. Equality is fed.
Worked examples: (ready 4, running 2) fed; (3,2) low_stock; (0,2) running_dry;
(3,0) no_builders; (0,0) running_dry. Blocked/held/unapproved/owner/capacity counts
never inflate ready. No product “fed/empty factory” claim from partial/stale data.

Coverage is complete exactly with no gaps; partial requires a gap. Freshness uses
the oldest required source snapshot, fresh only at age <=70,000 ms as in cockpit/
plan; future/missing timestamps are unknown plus gaps. Assembly time, event time,
comment update time and first-seen time cannot replace source snapshots. Stale
last-good data remains visibly aged. Local type checks cannot prove the source
universe; T6's API/client proofs must verify enumeration and these joins.

## Extension seams and registration ownership

| Ticket | Seam and narrow shared mounts |
| --- | --- |
| T3 #2034 | `model::{SourceFact,Preferences,Reference,Dispatch,Status}`, `boundary::DeliveryBoundary`; adds core `policy`/`grouping` module lines, store notification module, installed notification job/source/store/API injection; adds tests `policy`/`durable` module lines |
| T4 #2035 | Observed adapter implementing DeliveryBoundary; only its factory line in service runtime, capability/subscription injection, explicit permission and declared worker events; separate from T3 job registration |
| T5 #2036 | `Reference`, protected token mapping, `TargetResult`, authenticated target GET and existing card reuse; no provider choice or second answer API |
| T6 #2038 | `model::{Stock,ProjectStock,StockCounts}`, optional cockpit ready_stock mount; adds core `stock` and tests `stock` module lines; no private orchestration board import |
| T7 #2039 | Named fixtures and notifications test target; adds tests `journey` module line and candidate-bound offline live-kit result validation |

T1 registers only core `pub mod notifications`, `notifications::{model,boundary}`,
the Cargo `notifications` test target and its `mod contract`. Future module files
and declarations are added together by their owners, never ignored missing tests.
There are no pending ignore markers. Existing contract fields remain unchanged;
service/cockpit notification extensions are optional and absent in old producers.
