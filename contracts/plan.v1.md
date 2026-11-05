# OpenWiz plan contract, version 1 (`openwiz.plan.v1`)

The repository-wide plan read for the cockpit's plan graph page, `GET /api/v1/plan`
(0.0.11, #648, U1 #651). Its schema is [plan.v1.schema.json](plan.v1.schema.json).
**Contract only:** U2 builds the source/route and U3 the page. Inline synthetic
conformance cases are in `tests/checks/plan_decisions_schema_conformance.rs`.
They prove parsed shapes, not a graph calculation or live completeness.

Authority: the confirmed plan graph decisions, E1–E3, the approved build target,
and the precise contract ruling on #651
([private record](https://github.com/jparker2006/ClosedWiz/issues/651#issuecomment-6575677837)).
This preserves the largest-blocking-reach direction; it changes no spec or ticket body.

## Response and reading

```text
response { schema, snapshot_at, coverage, freshness, lanes, tickets, critical_chain }
lane     { kind: version | side_spec, number, title: Fact<string> }
ticket   { number, title: Fact<string>, url: Fact<issue URL>,
           spec: Fact<issue number | null>, lane: Fact<lane_ref | null>,
           state: Fact<fleet state>, column: Fact<done | building | waiting | needs_you>,
           labels: Fact<string[]>, yours: Fact<boolean>,
           blockers: Fact<issue number[]>, dependents: Fact<issue number[]>,
           pr: Fact<{ number, url: PR URL } | null> }
lane_ref { kind: version | side_spec, number }
chain    { root, blocked_count, path: [issue number] }
Fact<T>  { known: T } | { unknown: nonempty reason }
critical_chain: Fact<chain | null>
```

All shown keys are required, including each fact wrapper's one key. Every object
has exactly its declared keys, each once; no extra/missing/duplicate keys or
positional arrays. Enums are exact strings, never tagged objects. Issue and
milestone numbers are positive integers; times and counts are nonnegative integer
milliseconds/counts. Strings are nonempty. `null` means a positively established
absence only where the schema permits it; it never means a failed read.

The schema checks parsed shape, required/closed objects, enum strings, basic
bounds, unique scalar lists, coverage and freshness forms. A strict wire reader
also rejects duplicate keys at every depth and numbers spelled as `1.0` in an
integer slot. JSON Schema's mathematical integer definition and ordinary parsed
JSON cannot establish that spelling requirement. Cross-record rules below remain
mandatory even when schema validation succeeds.

## Universe and lanes

One response covers the server's working-directory repository. It never joins
issue numbers across repositories. Read GitHub milestones (open and closed),
specs (issues with sub-issues, open and closed), their tickets, labels and native
blocked-by links. Enumerate every page and check GitHub totals before claiming
complete coverage. Retain empty milestone lanes and side specs with no currently
visible usable tickets; no active-only, current-version or open-only filter.

A version lane's `number` is its milestone number and `title` its milestone title.
A side-spec lane's `number` is its unmilestoned spec issue number and `title` its
spec title. `(kind, number)` is the lane key. A ticket belongs to its parent spec's
milestone lane, or that parent's side-spec lane, regardless of whether the ticket
itself has an inconsistent milestone. Never assign a ticket by title parsing.

`tickets` contains every spec's sub-issues plus referenced external prerequisites,
recursively, once per issue number. An external prerequisite whose successfully
read parent is absent has known-null `spec` and `lane`; it remains available to
trace and to the chain. A missing or ambiguous parent read instead yields unknown
facts and a gap. An external ticket with a parent uses that parent's lane, adding
its lane if needed. Keep every usable row after another read fails. A partial
enumeration or missing required fact makes coverage partial, never a confident
empty universe. Descendants of a ticket outside the enumerated plan are not
invented: completeness and reach are scoped to this repository plan universe.

Lanes sort by kind (`version` first), then number; tickets sort by number.
Blockers, dependents and known labels are unique and ascending (labels by exact
string). A blocker is GitHub's native blocked-by relation, never body text. A
complete `dependents` list is exactly the inverse of the complete blocker lists
throughout the universe, independent of page filters/folding. If inverse edges
cannot be established in full, retain the row but make that fact unknown.

`url` comes from the issue's GitHub link; a known `pr` comes from the ticket's
closing-PR discovery, never its title. Known URLs must be canonical HTTPS
`github.com/<owner>/<repo>/issues/<number>` or `/pull/<number>` with the correct
number and this repository. Their schema patterns reject credentials, query,
fragment, traversal and other hosts; the producer/consumer must also check the
repository and number. They support the approved ticket/PR navigation; no account
objects, transcripts, environment paths, issue bodies or tool diagnostics are
returned. A successfully read absence of a closing PR is known null; an unread
or ambiguous discovery is unknown. Existing `fleet.v1` output remains unchanged.

## States, ownership and columns

`state` preserves [fleet.v1's state table](fleet.v1.md#ticket-states), including
its precedence, required input reads, verified merge readback and unknown states.
Closed without a verified merge is unknown, never done. No PR, all prerequisites
merged and `ready-for-human` still has unknown fleet state. A branch, PR or state
does not prove a running agent. U2 must use the same facts to derive these values;
this contract grants no different merge/start authority.

`yours` is true exactly when the complete label read contains `ready-for-human`.
It is independent of waiting or actionability; an unread label list makes it
unknown. It is never inferred from an assignee, title, live-test wording or colour.

Derive `column` in this order, using positively known facts:

1. A verified `merged` state: `done`.
2. `held` or `needs-info` in the complete label list: `needs_you`.
3. `building`, `in_review` or `changes_requested`: `building`.
4. No closing PR, `ready-for-human`, and every prerequisite verified merged:
   `needs_you`, while retaining its unknown fleet `state`.
5. `ready` or `blocked`: `waiting`.
6. Otherwise unknown, with a reason; never coerce an unknown into waiting/done.

All facts needed to distinguish earlier rules must be known before using a later
one. A page counts state columns separately from ownership, shows unknown rows
explicitly, and never colours every Jake-owned or waiting ticket as actionable.

## Critical chain

Use the dependency graph over unfinished tickets: positively verified merged
tickets are removed from its blocking graph. A candidate root is an unfinished
ticket with no unfinished prerequisites (all its prerequisites positively verified
merged, or none). This means a ready blocking gate, not necessarily fleet's
`ready` state. Count the distinct unfinished tickets reachable downstream from
that root; diamonds count each descendant once and exclude the root.

Choose the largest `blocked_count`; ties choose the longest onward path, then
the smallest numeric root. `path` begins with the root and follows prerequisite
→ dependent edges along a longest onward path. Ties between paths use the
lexicographically smallest numeric issue sequence. A chain with a single root
has zero descendants. An entirely finished or empty plan has known-null chain.
The strip is read as root ← dependent ← dependent because its arrows point back
to prerequisites, as in the target; `path` remains in root-to-downstream order.

Every listed ticket's prerequisites and merge status, and the full enumeration,
are required for a confident maximum. Any incomplete prerequisite/state read,
missing referenced node or cycle produces an unknown chain and a sanitized gap
(`malformed` for a cycle). Retain usable lanes/tickets. No partial subgraph is
advertised as the global maximum. The fixtures' `902 → 942`, reach 1, is a worked
example; computing the algorithm, ties, cycles and incomplete reads belongs to
U2's route proofs, not these schema checks.

## Coverage and freshness

`coverage` is `{state: complete, gaps: []}` or `{state: partial, gaps: [gap, ...]}`;
`gap` has `kind` and nonempty sanitized `detail`. Kinds reuse cockpit's ten:
`untested_version`, `command_failed`, `timed_out`, `budget_exhausted`, `malformed`,
`missing_field`, `wrong_type`, `not_found`, `truncated`, `unsupported`. Include
all required read/derivation failures. Unknown fleet state after complete reads
is an honest result, not itself a coverage failure; an unavailable required read
is a gap. No raw error output or source bodies enter a gap/unknown reason.

`response.snapshot_at` is assembly time. `freshness.snapshot_at` is the oldest
required source snapshot, preserved when old data is retained. It is a known
nonnegative millisecond time for `fresh` or `stale`; it is an unknown reason when
`state` is `unknown`. With every required time known and not after assembly,
`fresh` means age ≤70,000 ms and `stale` means older, as in `cockpit.v1`.
Missing times or an unestablished clock relationship are unknown. Coverage and
freshness are independent; assembling or refreshing never renews an old snapshot.
Clients continue to age source data after receipt. Complete fresh emptiness is
the only basis for an unqualified empty-plan claim; stale or partial emptiness
states its limit. This contract adds no polling interval or server result cache.

## Route and proof limits

One exact `GET /api/v1/plan`; no query (even `?`), request body or server-side
filter. Standard API Host, framing, method, security headers, `no-store` and
sanitized route-only logging apply. Other methods: `405`, `Allow: GET`; HEAD
has neither body nor Content-Length. Valid complete, partial, stale and empty
envelopes are `200`; source failures remain explicit gaps, not invented empty
success. Existing transport-error envelopes/statuses, shared two read slots,
five-second slot wait, forty-second request deadline and source budgets apply.
Identical in-flight reads may share a result; a later request reads anew. Slot
exhaustion is `503` with Retry-After; deadline expiry is `504`, with its unfinished
run retaining its slot. Read GitHub through the read-only App token when configured;
no send, stage, start, answer, label, approve, merge or GitHub write.

U2/U3 must additionally prove universe/ordering, parent placement, inverse edges,
URL repository/number checks, state and column derivation, ownership provenance,
merge readback, freshness math, graph uniqueness/DAG/ties/maximum reach, and honest
partial/empty displays. The schema cannot verify those cross-record facts.
Synthetic fixtures invent every identifier, title, URL and time; no live source
shape or account behaviour is claimed (`synthetic_assumptions`).

## Field sources

One row per declared property; inline fact fields retain the enclosing field’s source.

| Property | Source |
| --- | --- |
| `chain.blocked_count` | Number of distinct unfinished downstream descendants of the chosen root, excluding itself |
| `chain.path` | A longest root-to-dependent path; numeric lexicographic ties |
| `chain.root` | Chosen unfinished root with all prerequisites verified merged, or none |
| `coverage.gaps` | All incomplete required reads/derivations; empty exactly for complete coverage |
| `coverage.state` | Completeness of every required read and derived fact for this part |
| `fact_issue_or_null.known` | Positively read issue number or positively established absence |
| `fact_issues.known` | Complete unique ascending issue-number list for the enclosing relation |
| `fact_string.known` | The enclosing field’s positively read nonempty exact string |
| `freshness.snapshot_at` | Oldest required source snapshot, or explicit unknown when unavailable |
| `freshness.snapshot_at.known` | Nonnegative oldest required source time, never rewritten as assembly time |
| `freshness.state` | Oldest required source snapshot and assembly clock, using the existing 70,000 ms threshold |
| `gap.detail` | Sanitized explanation of the required failed/incomplete read or derivation |
| `gap.kind` | Existing inventory/fleet/cockpit failure classification |
| `lane.kind` | GitHub milestone versus a spec with no milestone |
| `lane.number` | GitHub milestone number for version; spec issue number for side_spec |
| `lane.title` | Milestone title or unmilestoned spec title, preserving unknown reads |
| `lane_ref.kind` | The verified parent spec milestone association, not a ticket-title inference |
| `lane_ref.number` | The owning milestone number or unmilestoned parent spec issue number |
| `pr.number` | The discovered closing pull request number |
| `pr.url` | GitHub PR URL checked for this repository and that PR number |
| `response.coverage` | Milestone/spec/ticket/prerequisite discovery and required fact-read results |
| `response.critical_chain` | Largest unfinished downstream reach, then longest onward path and numeric ties, or null/unknown as specified |
| `response.critical_chain.known` | Positive known result of: Largest unfinished downstream reach, then longest onward path and numeric ties, or null/unknown as specified |
| `response.freshness` | Oldest required GitHub plan snapshot |
| `response.lanes` | Every GitHub milestone and unmilestoned spec, including closed/empty lanes |
| `response.schema` | Contract constant openwiz.plan.v1 |
| `response.snapshot_at` | Server clock after assembling required reads |
| `response.tickets` | Union of all spec sub-issues and recursively referenced external blockers |
| `ticket.blockers` | Native GitHub blocked-by links, not body text, unique ascending numbers |
| `ticket.column` | The ordered column mapping in this contract, using positively known state/labels/prerequisites |
| `ticket.column.known` | Positive known result of: The ordered column mapping in this contract, using positively known state/labels/prerequisites |
| `ticket.dependents` | Exact inverse of all complete blocker lists over the enumerated universe |
| `ticket.labels` | The full GitHub issue label read; no inferred labels |
| `ticket.labels.known` | Positive known result of: The full GitHub issue label read; no inferred labels |
| `ticket.lane` | Verified parent spec milestone or side-spec lane; null only for positively unparented external blockers |
| `ticket.lane.known` | Positive known result of: Verified parent spec milestone or side-spec lane; null only for positively unparented external blockers |
| `ticket.number` | GitHub sub-issue or blocked-by reference number, unique in this repository |
| `ticket.pr` | Closing-PR discovery; known null after successful absence, unknown for failed/ambiguous discovery |
| `ticket.pr.known` | Positive known result of: Closing-PR discovery; known null after successful absence, unknown for failed/ambiguous discovery |
| `ticket.spec` | Verified parent issue number; null after successful absence, unknown after unread/ambiguous association |
| `ticket.state` | Existing fleet.v1 state table and all its required reads, including verified merge readback |
| `ticket.state.known` | Positive known result of: Existing fleet.v1 state table and all its required reads, including verified merge readback |
| `ticket.title` | The ticket issue read, never a fabricated title for a missing issue |
| `ticket.url` | GitHub issue URL, checked for this repository and the exact ticket number |
| `ticket.url.known` | Positive known result of: GitHub issue URL, checked for this repository and the exact ticket number |
| `ticket.yours` | True exactly when complete labels contain ready-for-human; independent of state |
| `ticket.yours.known` | Positive known result of: True exactly when complete labels contain ready-for-human; independent of state |
| `unknown.unknown` | Sanitized explanation of an unavailable fact; never raw tool output |
