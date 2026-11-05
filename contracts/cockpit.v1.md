# OpenWiz cockpit contract, version 1 (`openwiz.cockpit.v1`)

The one read for page 1 of the cockpit (0.0.10, #530): `GET /api/v1/cockpit`. Its schema is [cockpit.v1.schema.json](cockpit.v1.schema.json). This ticket (#534) defines the contract only; #535 builds the route and #536 the page. CK1's contract proof is `tests/checks/cockpit_schema_conformance.rs`, using synthetic complete, partial, stale and empty responses. It proves no live behaviour.

**Source decision:** the orchestrator chose explicit known/unknown facts, without substitution; `y` and approve stay unavailable until wording and risk are known ([private record](https://github.com/jparker2006/ClosedWiz/issues/534#issuecomment-6564916205)). Current `fleet.v1` has only a Needs you item's `kind`, `spec` and `ticket`; `inventory.v1` has update time, not start time. Source enrichment is separate; this contract does not grant another read or write.

## Response

```text
response
  schema, snapshot_at
  projects   { coverage, freshness, items: [project { id, name, orchestrator }] }
  needs_you  { coverage, freshness, items: [need { project, kind, spec, ticket, wording, age_ms, risky }] }
  agents     { coverage, freshness, items: [agent { thread, project, title, fleet, ticket,
                                                 activity, model, state, location, started_at }] }

project.orchestrator { coverage, freshness, target }
coverage            { state: complete | partial, gaps: [{ project, kind, detail }] }
freshness           { state: fresh | stale | unknown, snapshot_at: Fact<time> }
Fact<T>             { known: T } | { unknown: nonempty reason }
```

All keys shown are required. Every object is closed: no extra, missing or repeated key; no positional arrays in place of objects. Enums are exact strings, never tagged objects. Integers are JSON integers, never strings, booleans or fractional numbers. Times and ages are nonnegative integer milliseconds; issue numbers are positive integers. Strings used for facts, ids, wording and reasons are nonempty. `null` occurs only in a gap's `project` and the known absence of an orchestrator target.

The schema checks the parsed shape. Duplicate keys and an integer written as `1.0` require a strict wire reader: JSON parsers can lose this distinction. Cross-record rules below are also required; passing the schema alone does not prove them. No producer/reader is built in T1.

## Projects and completeness

`projects.items` contains every project discovered on the PC hub, once by its CloudRoom project id, in ascending id order. Discovery uses the inventory's project read and the server's configured fleet sources; there is no repository owner, remote URL or filesystem path in this response. The current server has only the sources for its working-directory repository (`crates/server/src/fleets.rs`, `Fleets`), not an observed multi-project source registry. Do not claim complete cross-project coverage from that one source: projects without a reachable source stay visible with gaps. T1 defines no new configuration format. A project can have no active agents or no fleet. A missing fleet source, inaccessible project or incomplete discovery is a gap, never grounds to drop a known project. An empty inventory's session groups alone do **not** establish that no projects exist.

`needs_you` and `agents` are flat lists across those projects, with their own coverage and freshness. This preserves one global Needs you order and lets a client filter and group without another read. Each part's coverage includes discovery of its whole project universe. `complete` means all reads needed for that part and its required facts succeeded in full; `gaps` is then exactly `[]`. Otherwise it is `partial`, with at least one sanitized gap. No failed read, missing source or unsupported required fact becomes a confident empty list. Retain every usable item when other items or fields fail.

Gap kinds are the inventory's eight plus fleet's `truncated` and cockpit's `unsupported` (an upstream contract does not provide a required fact). `project` is the affected project id, or `null` for discovery/unassigned/global gaps. `detail` and unknown reasons are OpenWiz's own explanations, never raw tool diagnostics. Relevant upstream partial/failed reads and gaps must survive aggregation; coverage must not improve merely because some rows were usable. A fact unknown because its source cannot supply it produces an `unsupported` gap in that part. An unread or ambiguous placement also remains a gap; it does not erase an agent.

**“Nothing needs you” is permitted only when** `projects` and `needs_you` are both complete and fresh, `needs_you.items` is empty, and the client has not since marked either snapshot stale. Partial or stale emptiness says that no items were read or that no items were present as of that snapshot. A project/machine filter narrows a statement to that scope; it never makes global data complete. Target availability and agent coverage are separate from whether all Needs you items were read.

## Freshness

`response.snapshot_at` is the server's assembly time after its reads, not a rewritten source time. Each part's `freshness.snapshot_at` is the oldest snapshot required for that part, preserving upstream `freshness.snapshot_at`; the target uses the time of its configuration/target check. A newly assembled response does not refresh retained data.

With every required snapshot known, `state` is `fresh` when its age at assembly is at most **70,000 ms**, and `stale` when older. This reuses the existing fleet page's `FLEET_TIMING.staleAfterMs` (`apps/web/src/timing.ts`), not a new refresh interval. If a required snapshot is missing, or the clock relationship cannot be established, use `unknown` and a `snapshot_at` unknown reason. Known snapshots are never after assembly. Coverage and freshness are independent: a recent truncated read can be fresh and partial; a full old snapshot can be complete and stale.

A client continues to age each part after receipt using its existing wall/monotonic stale tracking, including the source age already present at assembly; fresh never lasts indefinitely because the JSON says `fresh`. A refresh failure keeps the previous snapshot time and marks its failure/staleness honestly. This contract adds no server cache, polling policy or live read permission. The stale fixture models retained data; it does not prove a cache exists.

## Needs you

For an item whose project is known, `(project.known, spec, ticket, kind)` is its unique key. `project` is a fact: a repository may match several CloudRoom projects, and fleets do not themselves attach a project to each Needs you item. Use a known project only when the server has a verified unambiguous mapping; otherwise preserve the item once as unassigned with an unknown reason and a gap. Never duplicate it into every matching project or pick the first match. Unassigned items cannot select a target or enable approve/y; they remain visible without claiming a durable actionable key. Do not deduplicate unassigned items from different repository sources merely because issue numbers match. `spec` is its fleet's spec issue number; `ticket` is its ticket issue number. Numbers are scoped to the project's repository, never joined across repositories. Current source kinds are `needs_info` and `held`, directly from `fleet.v1.data.needs_you` when known. An unread upstream Needs you value produces a gap; it must not be treated as `[]`.

`wording` is the exact proposal/question to present and bind an answer to. It is **unknown today**: `fleet.v1` excludes issue/comment bodies. A ticket title is not its pending proposal. `age_ms` is time waiting on this item as of its source snapshot; it is **unknown today**, never time since the ticket/session was last updated, time since polling began or time since first seen by the page. Known ages sort descending (oldest first); unknown ages follow, visibly unknown. Ties use known project id (unassigned last), spec number, ticket number, then kind, retaining source order for still-indistinguishable unassigned items. Display numbers are positions in the current list, not durable item ids or approvals.

`risky` is a fact, **unknown today** for `needs_info` and `held`: neither label classifies risk. A known false requires an explicit source classification, never a missing flag or a text heuristic. `live`, `release` and `publish` are reserved known risk kinds required by #530; no current fleet source emits them. Their only valid `risky` is `{ "known": true }` (enforced by the schema). Rich synthetic fixtures illustrate these future facts; they do not assert an existing producer. Any known-true risky item, of any kind, requires a second explicit confirmation before its send.

`approve` and `y` are unavailable unless its project association, exact wording and risk are known, the displayed proposal is fresh, and the project's orchestrator target is verified and fresh. `y` binds only to the exact item on screen: project, spec, ticket, kind, wording, risk and target seen. A changed or disappeared item/target invalidates that binding; navigation or a new list number never approves it. Answering uses the existing send operation, op id and one-send guarantee; the contract defines no approval write or automatic send. #536/#537 prove the page behaviour, including choosing/replying and confirming twice. The unknown facts remain visible and may be opened; no fabricated wording enables an action.

## Running agents

`agents.items` has every inventory session whose reported status is exactly `active`, once per thread id, ordered by known project id, known fleet number, known ticket number, then thread id; unknown grouping values sort last. `activity: "active"` records that positive running observation. An open branch, PR or a ticket state does not prove a running agent. Unknown/unrecognized inventory status or an incomplete session list makes agent coverage partial: never claim that no other agents are running. Known idle/error sessions are not running rows.

`project` is the inventory session's project grouping id; an ungrouped session keeps an unknown project reason and stays in the list. `fleet` and `ticket` come only from the verified thread → branch → PR → ticket → spec chain in `fleet.v1`. Missing, unread or ambiguous links stay unknown. No title parsing or CloudRoom parent relationship places an agent; reviewers/unplaced threads still appear. The client can group unknowns separately without hiding them.

`title`, `model` and `location` copy the inventory's session title, `reported_configuration.model` and location facts. Model means **reported configuration**, never the serving model. Location is `{known: {kind: "cloud"}}`, `{known: {kind: "local", machine: Fact<string>}}` or unknown. A local machine is shown only when inventory reports it; “Cloud” is an execution location, never a fabricated host/machine name. Do not infer PC/Mac from project names, branches or titles. A machine filter cannot exclude unknown-machine rows as though their machine were known.

`state` is the placed fleet ticket's state (`ready`, `building`, `in_review`, `changes_requested`, `merged`, `held`, `blocked`) or unknown, preserving the distinction from reported running activity. A merged ticket can still have a running agent until inventory says otherwise. `started_at` is **unknown today**: `inventory.v1` has no start time. Never substitute `updated_at`, inventory `age_ms`, or thread creation time. A future known start must be at or before its source snapshot. The client computes running duration only from a known start, labelled as such.

## Orchestrator target

Each project has its own `orchestrator` part; never reuse one project's target for another. `target` is the #129 `fleet.v1.orchestrator` target supplied by the server's `OPENWIZ_ORCHESTRATOR_THREAD_ID` configuration and checked to exist through the existing bounded target read. T1 does not change that field or invent a multi-project configuration format. If a project's source cannot provide a distinct verified target, it stays unavailable.

Use `{known: <thread id>}` only after that check. When the configured source has been read successfully and #129 omits its field (unset or not found), use `{known: null}`: no send target. When configuration/verification cannot be read or the source is unavailable, use unknown with partial coverage; do not mistake a failed check for known absence. An absent target never prevents reading or displaying the project. Target identity must remain scoped to its project through the send.

## Field sources

The conformance test checks this table against every schema property. **Inventory** means `openwiz.inventory.v1` and its existing project/session reads; **fleets** means `openwiz.fleet.v1`, including #129's server-configured target addition. “Unsupported today” explicitly means there is no current source: known rich fixture values are synthetic assumptions, available only after separately approved enrichment.

| Property | Source |
| --- | --- |
| `response.schema` | Contract constant `openwiz.cockpit.v1` |
| `response.snapshot_at` | Server clock at assembly after reads |
| `response.projects` | Server aggregation of inventory project discovery and configured fleet sources |
| `response.needs_you` | Server aggregation of each project's fleets Needs you values |
| `response.agents` | Server aggregation of inventory running sessions joined to fleet placements |
| `coverage.state` | Derived from all reads/facts needed by the enclosing part, including project discovery |
| `coverage.gaps` | Inventory/fleet gaps and unread reads, plus explicitly unsupported required facts |
| `gap.project` | Inventory project id/server source mapping; null when not assignable |
| `gap.kind` | Inventory/fleet failure class, or unsupported upstream fact |
| `gap.detail` | Server's sanitized explanation, never tool output |
| `freshness.state` | Derived from enclosing part's required source snapshots and assembly clock, using the existing 70-second fleet stale threshold |
| `freshness.snapshot_at` | Oldest required inventory/fleet snapshot or target check time; unknown if any required time is unavailable |
| `projects.coverage` | Completeness of all inventory project discovery/configured fleet-source reads, including project names |
| `projects.freshness` | Project discovery/source-mapping snapshot times |
| `projects.items` | Union of discovered project records, never just active-session groups |
| `needs_you.coverage` | Every project's fleet enumeration/Needs you reads and required item facts |
| `needs_you.freshness` | Every required project/fleet/Needs you source snapshot |
| `needs_you.items` | All usable `fleet.v1.data.needs_you` items, enriched only by an approved source |
| `agents.coverage` | Inventory enumeration/status/detail reads and fleet placement/state reads, plus unsupported required facts |
| `agents.freshness` | Every required inventory and fleet placement/state snapshot |
| `agents.items` | Inventory `data.sessions` filtered by positively known active status, preserving unplaced rows |
| `project.id` | Inventory project read/group id; fleet `projects` read id, scoped by the server's source mapping |
| `project.name` | Inventory project name fact or fleet `projects` read name; unknown if not read |
| `project.orchestrator` | The project's own configured fleet source's #129 target/check result |
| `orchestrator.coverage` | Completeness of reading this project's configuration and checking its target |
| `orchestrator.freshness` | Time of this project's configuration/target check |
| `orchestrator.target` | #129 `fleet.v1.orchestrator` from server `OPENWIZ_ORCHESTRATOR_THREAD_ID`, checked to exist; known null only after a successful source read omits it |
| `need.project` | Verified unambiguous mapping of this item's repository source to an inventory project; unknown when several projects match or mapping is unavailable |
| `need.kind` | Fleets Needs you kind: needs_info/held today; live/release/publish unsupported today, synthetic fixture assumptions only |
| `need.spec` | Fleets Needs you spec number |
| `need.ticket` | Fleets Needs you ticket number |
| `need.wording` | Unsupported today: fleets exclude issue/comment bodies; exact proposal source awaits approved enrichment |
| `need.age_ms` | Unsupported today: fleets do not report when an item began waiting |
| `need.risky` | Unsupported today for fleet label kinds; derived true for an explicitly sourced live/release/publish kind, never default false |
| `agent.thread` | Inventory session id |
| `agent.project` | Inventory session group project id, or unknown grouping reason |
| `agent.title` | Inventory session title fact |
| `agent.fleet` | Fleets verified placement chain's spec number, otherwise unknown |
| `agent.ticket` | Fleets verified placement chain's ticket number, otherwise unknown |
| `agent.activity` | Inventory session status known active; positive inclusion condition |
| `agent.model` | Inventory session reported_configuration.model fact |
| `agent.state` | Placed fleet ticket state; unread/unknown/unplaced becomes unknown with its reason |
| `agent.location` | Inventory session location fact |
| `agent.started_at` | Unsupported today: inventory has only updated_at/age_ms, never a start time |
| `cloud.kind` | Inventory known cloud execution location |
| `local.kind` | Inventory known local execution location |
| `local.machine` | Inventory local machine fact from its machine read; never inferred |
| `unknown.unknown` | Sanitized inventory/fleet reason or server explanation of an unsupported/unavailable fact |
| `known_string.known` | The enclosing field's positively read nonempty string, never a placeholder |
| `known_time.known` | The enclosing field's nonnegative millisecond snapshot, age or start fact; age/start unsupported today as described above |
| `known_issue.known` | Verified fleet placement's positive spec/ticket number |
| `known_boolean.known` | Explicit item's risk classification; no source for ordinary label kinds today |
| `known_state.known` | The placed fleet ticket's known state |
| `known_location.known` | Inventory's known location object |
| `known_target.known` | Verified server-configured target string, or null after successful source read establishes absence |

## Route

No query (including an empty `?`), body or server-side project/machine filter. Standard exact path, Host, method, framing, security headers, `Cache-Control: no-store` and sanitized route-only logging apply as in [web-api.v1.md](web-api.v1.md). Other methods receive `405`, `Allow: GET`; a HEAD response has no body or Content-Length. A complete, partial, stale or empty valid envelope is `200`; source failure is represented by gaps and unknowns, not a successful empty claim. Transport failures retain the existing API error envelope and statuses.

The existing shared two-read slots, five-second slot wait, forty-second request deadline and connection/source budgets apply. Identical in-flight cockpit reads share a result, while a subsequent request reads anew; neither single-flight nor an assembly timestamp hides an old source snapshot. Slot exhaustion is `503` with Retry-After; deadline expiry is `504`, and the unfinished read keeps its slot. This read never sends, stages, starts, approves, labels or merges anything.

## Schema and cross-record checks

The schema enforces required/closed objects, fact forms, enum forms, integer bounds, complete coverage's empty gap list, known timestamps for fresh/stale parts, unknown timestamps for unknown parts and true risk for live/release/publish items. The fixture mutation table includes malformed nested objects, every missing key and every extra key/positional-object substitution.

A producer/strict consumer must additionally check: unique project/thread/assigned-item keys; known project references resolve (or an item/agent project is explicitly unknown); issue joins stay within one project; verified placement; coverage includes all required reads/facts; partial coverage has a gap; snapshot/age/start consistency; actual freshness calculation; list ordering; risk classification provenance; and the no-approval conditions. T1's schema tests do not claim to enforce these data-dependent rules, duplicate wire keys, runtime sends or live completeness. Route and page tickets must prove their respective rules at the seams #530 names.

## Synthetic examples

The four named response fixtures are inline in `tests/checks/cockpit_schema_conformance.rs`; no test depends on private evidence that CI removes. `complete` uses two projects, local and Cloud running agents, a checked target and known absence, ordinary and risky Needs you. `partial` has unsupported proposal/risk/age/start fields, an unplaced running agent and a failed target check. `stale` retains old source snapshots; `empty` is a complete fresh empty universe. Additional partial/stale empty lists are accepted as shapes without granting an empty-state claim.

**synthetic_assumptions:** every identifier, title, model, machine and wording is invented. Rich wording, classification, waiting ages, known starts and release kinds are unobserved future shapes, not fields emitted by the current upstream contracts. The confirmed A decision specifically allows these illustrative known values while real producers use unknowns. No fixture is a live observation.

## Ready-stock extension (0.0.15 T1, contract only)

The optional response property `ready_stock` reserves `notifications::model::Stock`
for T6 (#2038), exactly `stock` in [notifications.v1](notifications.v1.md) and the
`notification_stock` definition in this schema. Existing required properties and
all other semantics are unchanged. Absence means the extension is unavailable,
never zero stock; old producers/responses remain valid. T1 mounts no route or UI.

The projection includes every configured project exactly once with current
known/unknown counts, coverage, oldest-source freshness and nullable last_good
sample. The factory totals require complete fresh discovery and required facts
for every project; partial/stale/unknown scope has unknown totals and visible
reasons/age. A missing project is retained with a gap. Last-good counts retain
their original time and never prove current fed/empty status. Freshness uses this
contract's existing 70,000 ms threshold, not assembly time. Count unknowns never
become zero. Source provenance and full-universe verification remain mandatory.

Use the existing plan-links approved-label universe and ticket builder measure,
plus plan/fleet's verified-merge requirement for closed blockers. Ready is open,
approved, startable, without builder/hold/owner wait/capacity refusal. Counts
partition remaining work into blocked, held, unapproved, owner_wait, capacity_wait
and unknown as notifications.v1 specifies. Running here counts recorded ticket
builders (even blocked builders); `agents.items` still counts only observed active
inventory and is not redefined. No private board or new scheduler is imported.

Known stock is fed at ready >= 2 * running for running > 0, low_stock below it,
running_dry at zero ready even with builders finishing. Positive ready with zero
builders is no_builders and shows the actual count; no reassuring ratio. Any
unclassified work is indeterminate. This summary remains readable with delivery
off/unsupported/denied/failed and makes no delivery or work effect. T6 proves the
source-to-API/client projection and aged/missing-source matrix.

Notification extension field sources (the existing source rows remain unchanged):

| Property | Source |
| --- | --- |
| `notification_coverage.gaps` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_coverage.state` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_freshness.snapshot_at` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_freshness.state` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_gap.reason` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_gap.source` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_project_stock.counts` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_project_stock.coverage` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_project_stock.freshness` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_project_stock.last_good` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_project_stock.project` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock.coverage` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock.freshness` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock.projects` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock.totals` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock_counts.blocked` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock_counts.capacity_wait` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock_counts.held` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock_counts.owner_wait` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock_counts.ready` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock_counts.running` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock_counts.state` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock_counts.unapproved` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock_counts.unknown` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock_sample.counts` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `notification_stock_sample.snapshot_at` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
| `response.ready_stock` | Verified configured-project plan/fleet facts, original source snapshot or explicit gap under notifications.v1; never notification permission |
