# OpenWiz fleet contract, version 1 (`openwiz.fleet.v1`)

The JSON that `openwiz fleets --json` and `openwiz fleet <spec> --json` print (OpenWiz 0.0.6, spec #107). Agents read it through the CLI; spec 2's tick and spec 3's fleets screen build against it. The schema is [`fleet.v1.schema.json`](fleet.v1.schema.json); this file adds the read model, the dependency table, the rules a schema can't express, the state table, where each field comes from, and examples.

**Status:** `openwiz fleets --json` (A4, #112) and `openwiz fleet <spec> --json` (A5, #113), including agent placement (A6, #114), are implemented on synthetic fixtures. Proofs: [fleets](../tests/fleet/a4_fleets.rs), [fleet](../tests/fleet/a5_fleet.rs), and [agents](../tests/fleet/a6_agents.rs). The original A2 contract proof predates #129's `envelope.orchestrator` field and reported 24 failed rows; it is not a current passing proof. Fixture proofs do not establish live behaviour: [A7 (#115)](https://github.com/jparker2006/ClosedWiz/issues/115) tracks the pending live check; [STATUS.md](../STATUS.md) tracks version acceptance.

**Always true:**
- **Read-only.** Both commands only read: GitHub through `gh`, and for `fleet`, CloudRoom through `room-cli`. Each read is on an allowlist.
- **Each fact is stored once, in its read record.** Every external read is a record in `reads`, holding what it read. Every other value points to a read by its id, or is worked out from reads, never copied. So two uses of one read can't disagree.
- **Unknown stays unknown.** A worked-out value is known only when every read it requires is complete; otherwise it names the reads it lacks. An unsuccessful read never becomes a confident value.
- **Merged means read back.** A ticket is `merged` only when its pull request's merge commit has been read back on the base branch. Never an approval, a ready pull request or a closed issue.
- **No private data** beyond what the thread list already shows: no thread content, no account names (so no repository owner and no comment authors), no full comment or issue bodies. T6 exposes only a selected question’s first line and its provenance (below). Owned paths and relies-on are the two template lines, as written.

## The two commands

| Command | `data.view` | What |
| --- | --- | --- |
| `openwiz fleets --json` | `fleets` | Every fleet in the repository, its tickets and blockers, its progress, and the "needs you" items. GitHub only: `sources.cloudroom` is `null` and no CloudRoom read is made |
| `openwiz fleet <spec> --json` | `fleet` | One fleet: its tickets and blockers, each ticket's state and builder, "needs you", and the project threads no verified chain places |

A **fleet** is a spec: an issue with sub-issues. Its **tickets** are those sub-issues; its **blockers** are the issues its tickets' blocked-by links name. Which specs `fleets` lists (open ones, a milestone's) is A4's choice of options; the shape is the same.

### HTTP answer target (#129)

Both HTTP fleet routes may add one top-level **`orchestrator`** field: the server's
`OPENWIZ_ORCHESTRATOR_THREAD_ID` (the same setting as B5), only after an allowlisted
CloudRoom target read confirms that exact thread exists within the response's run
budget. It is a string of 1–128 ASCII letters, digits, `_` or `-`, never starting
with `-`. When unset, invalid, not found or not confirmed, the field is **absent**,
never `null`; answering is unavailable. This server configuration is the authority
for the target; no title, builder or unplaced thread is substituted.

This optional HTTP metadata is the sole exception to the CLI list's GitHub-only
reads and the envelope's read-record rule: the CLI output remains unchanged, and
the field carries only the verified ID, with no thread content or diagnostics.
The schema accepts envelopes with or without it. Answer opens the existing
composer panel/sheet addressed to that ID, prefilled with the item's ticket and
spec when its draft is empty or contains only the bare answer template. Any other
text, and every unresolved attempt, stays.
Opening, refreshing or reloading never sends. The owner's send press uses the
existing preview, op ID, storage and honest-outcome guarantees. No approve button.

## Reading it

Readers use hand-written strict readers on B1's pattern (`crates/core/src/attachment.rs`, PR #88), never serde's derived ones:

- **An object** is read only from a JSON object with **exactly its keys, each once.** A missing key, an extra key or a **duplicate key** is refused. (A schema can't see duplicate keys, because a parsed value keeps one: the reader must refuse them.)
- **An enum** (a state, a kind, a verdict, a result) only from **one string in its list.** Never another spelling (`MERGED`, `in review`), never a number or a bool, never a **tagged object** such as `{"merged": null}` or `{"merged": {}}` (serde's external tagging).
- **A worked-out value** only in one of its forms (below), exactly one key: never the bare value, never two forms at once.
- **A list** only from a JSON array, **an object** only from a JSON object: a **positional array** in place of an object (`[902, "Synthetic ticket A1"]`) is refused.
- **Integers** only as JSON integers: no `1.0`, no `"1"`, no `true`. `NaN` and `Infinity` aren't JSON.
- `null` only where the schema has it.
- **The rules below are part of the contract.** A reader that checks only the schema must not rely on them.

OpenWiz never writes a duplicate key or `1.0`. A browser's `JSON.parse` can't see either (it keeps the last key, and has one number type), so a JavaScript reader that must refuse them needs its own parsing.

## Reads: where every fact is

**Every external read is a record** in the envelope's `reads`: `{"id": "r7", "kind": ..., <its subject>, "outcome": ...}`, its id `r` then digits. One record per thing read: no two with one kind and subject, no two with one id.

| `kind` | Subject | What it reads | Its value |
| --- | --- | --- | --- |
| `version` | `source`: `github` or `cloudroom` | `gh --version`, `room-cli --version` | The version, a string |
| `repository` | — | `gh repo view` | `{"name": ...}`, never the owner |
| `spec_list` | — | Which issues are specs (`fleets` only) | Their numbers, ascending |
| `issue` | `issue` | One issue's own fields: a spec's, a ticket's or a blocker's | `title`, `state` (GitHub's own: `open` or `closed`, never "merged"), `milestone` (`number` and `title`, or `null`), `labels` (as read, each once), and `owned_paths` and `relies_on` (the body's one `**Owned paths:**` and `**Relies on:**` line, as written after the label; `null` when there isn't exactly one, or it's empty); optional T6 `pending_question` provenance, described below |
| `sub_issues` | `spec` | A spec's sub-issues: its tickets | Their numbers, ascending; never the spec |
| `blocked_by` | `ticket` | A ticket's blocked-by links (GitHub's own, never the body's text) | Their numbers, ascending; never the ticket |
| `pr_discovery` | `issue` | The pull request that closes the issue, with its own fields | `null` (none does), [an open or merged pull request](#a-pull-request), or `{"state": "several", "numbers": [...]}` |
| `checks` | `pr` | An open pull request's checks: the latest run of each | `[{"name", "result"}]`, each name once; `result` is `pass`, `fail`, `pending`, `skipping` or `cancel` |
| `comments` | `pr` | An open pull request's comments | Its latest `VERDICT` comment, `{"verdict", "commit"}`, or `null` when there's none |
| `merge_readback` | `pr` | A merged pull request's merge commit, read back on its base | `true` when it's there |
| `projects` | — | The CloudRoom projects whose git remote is this repository (`fleet` only) | `[{"id", "name"}]`, each id once |
| `threads` | — | Those projects' threads, not archived (`fleet` only) | `[{"thread", "project", "kind": "cloud"}]` or, for a local thread, also its `branch` (the list's `environmentBranchName`, or `null`); each thread once |
| `workspace` | `thread` | One Cloud thread's branch (`room-cli cloud thread-workspace <id> --json`) | The branch, a string |

**An outcome** is one of:
- `{"state": "complete", "value": ...}`: read in full. A `null` value is a fact (no pull request closes it; no verdict), never "not read".
- `{"state": "partial", "gap": "truncated", "reason": ..., "value": [...]}`: a list read in part (fewer than GitHub's own total: `nodes` shorter than `totalCount`). The value is what was read. Only the six list kinds can be partial.
- `{"state": "failed", "gap": <kind>, "reason": ...}`: nothing usable, so **no value**. The kind is one of the inventory's eight (`untested_version`, `command_failed`, `timed_out`, `budget_exhausted`, `malformed`, `missing_field`, `wrong_type`, `not_found`).

The reason is OpenWiz's own words, never a tool's raw output. **The gaps are the reads whose outcome isn't complete,** and nothing else: there's no separate gap list to disagree with them.

### A pull request

`pr_discovery`'s value. A pull request is the issue's when its body closes it (`Closes #N`, read back as GitHub's closing reference; a `#N:` title alone doesn't count). Of those: exactly one merged pull request takes precedence over any open ones; with none merged, the one open one is its. Closed, unmerged pull requests are never its. **More than one open one, with none merged,** is `{"state": "several", "numbers": [...]}`, at least two numbers, ascending: none of them is its.

**Two or more merged pull requests** closing the issue are ambiguous, regardless of any open ones. In this case, `fleet` returns `several` with only the merged pull request numbers, ascending; none is its own, and the ticket's state is unknown. The `fleets` view instead fails the `pr_discovery` read with a `malformed` gap, so values requiring that read are unread. Neither view selects a pull request or counts the ticket as merged.

| Field | What |
| --- | --- |
| `number`, `draft`, `head_branch`, `base_branch` | GitHub's |
| `state` | `open` or `merged` (GitHub's word; `merged` alone never makes a ticket merged) |
| `head_commit` | The head commit: 40 lowercase hex digits |
| `closes` | The issues it closes (GitHub's closing references), ascending: always the issue whose `pr_discovery` gave it, and any others |
| `merge_commit`, `merged_at` | Merged only: the merge commit and when (ms) |

Its `checks` and `comments` are read only while it's open, and its `merge_readback` only once it's merged. **One pull request, one value:** when two issues' `pr_discovery` reads give the same pull request, they give it identically.

A **verdict** is the latest comment starting `VERDICT: ` (`review-ticket`'s first line, `VERDICT: <APPROVE or CHANGES> at <the commit, all 40 characters>`): `verdict` (`approve` or `changes`) and `commit`. It holds only for that commit: it's **on the head** when `commit` is the pull request's `head_commit`. Verdicts are pull request comments, not GitHub reviews.

**CI** is worked out from the checks: `failed` if any check failed or was cancelled; otherwise `pending` if any is pending; otherwise `passed` if any passed; otherwise `none` (no check, or all skipped).

## Values

Every value in `data` (besides `view`, and the numbers that name a fleet, ticket or blocker), and the envelope's `version`, `version_tested` and `coverage`, is one of two things:

- **A pointer:** the id of the one read the [dependency table](#what-each-value-requires) names for it, or `null` when that read doesn't apply (a ticket with no open pull request has no `ci`). A reader looks the fact up in `reads`. It's never a copy.
- **Worked out** from reads, in one of these forms:

| Form | Means | Where |
| --- | --- | --- |
| `{"known": v}` | Every read it requires is complete, and this is the value they give | Every worked-out value |
| `{"unread": ["r9", ...]}` | Not known: exactly the incomplete reads it requires, in the order of `reads` | Every worked-out value |
| `{"unknown": reason}` | Every read it requires is complete, and the state table doesn't settle it | A ticket's `state` only |
| `{"undefined": reason}` | Version 1 defines no read for it | A ticket's `reviewer` only |

`version_tested` and `coverage` are plain: `true` and `complete` only when every read they require is complete.

### What each value requires

**The one dependency table.** Each value and what it requires. `kind(param)` is the read of that kind whose subject is the parameter; `kind()` is a read with no subject; a plain name is another value of the table; `every read` is every record. The check evaluates from this table alone: it follows every edge, and refuses a row or an edge it doesn't support.

| Value | Requires |
| --- | --- |
| `source.version` | `version(source)` |
| `source.version_tested` | `source.version` |
| `repository` | `repository()` |
| `specs` | `spec_list()` |
| `fleet.issue` | `issue(spec)` |
| `fleet.tickets` | `sub_issues(spec)` |
| `fleet.progress` | `fleet.tickets`, `ticket.state` |
| `ticket.issue` | `issue(ticket)` |
| `ticket.blocked_by` | `blocked_by(ticket)` |
| `ticket.pr` | `pr_discovery(ticket)` |
| `ticket.ci` | `checks(open_pr)` |
| `ticket.review` | `comments(open_pr)` |
| `ticket.on_base` | `merge_readback(merged_pr)` |
| `ticket.state` | `ticket.issue`, `ticket.blocked_by`, `ticket.pr`, `ticket.ci`, `ticket.review`, `ticket.on_base`, `blocker.merged` |
| `ticket.builder` | `placements` |
| `blocker.issue` | `issue(blocker)` |
| `blocker.pr` | `pr_discovery(blocker)` |
| `blocker.on_base` | `merge_readback(merged_pr)` |
| `blocker.merged` | `blocker.pr`, `blocker.on_base` |
| `blocker.fleet` | `specs`, `fleet.tickets` |
| `projects` | `projects()` |
| `threads` | `threads()` |
| `thread.branch` | `threads`, `workspace(cloud_thread)` |
| `placements` | `projects`, `threads`, `fleet.tickets`, `ticket.pr`, `thread.branch` |
| `needs_you` | `specs`, `fleet.tickets`, `ticket.issue` |
| `unplaced` | `placements` |
| `coverage` | `every read` |

**Parameters:** `source`, `spec`, `ticket` and `blocker` are the value's own (the source, the spec's number, the ticket's or the blocker's number). `open_pr` and `merged_pr` are the number of the pull request its `pr_discovery` read gives, when that read is complete and the pull request is open, or merged; they read that `pr_discovery` read. `cloud_thread` is a thread's id when the thread list says it's a Cloud thread. **A read whose parameter doesn't apply is not required,** and its pointer is `null`.

**Requiring another value** requires it where it applies: the value's own (a ticket's `ticket.pr`), a fleet's tickets, a ticket's blockers, or else every one in the view. Those lists are values too, so a row that walks them names them: every fleet is `specs` (in `fleet <spec>`, the command's argument: no read), a fleet's tickets `fleet.tickets`, a ticket's blockers `ticket.blocked_by`, every thread `projects` and `threads` (the threads of those projects).

Two values aren't printed: `thread.branch` is the `workspace` read for a Cloud thread, and the thread list's `branch` for a local one; `placements` is [the verified chain](#a-tickets-agents-the-verified-chain) for every ticket at once, which each `builder` and `unplaced` read. `specs` is only in `fleets`; `projects`, `threads`, `thread.branch`, `placements`, `ticket.builder` and `unplaced` only in `fleet`.

### The rule

**A value's form follows from the table, mechanically:**
1. **A pointer** is the id of the read its row names, or `null` when its parameter doesn't apply (finding `pointer`).
2. **A worked-out value** is known exactly when every read it requires, through every edge, transitively, is complete. Otherwise it is `{"unread": [...]}`, naming exactly the incomplete ones. Every edge counts, even one the state table wouldn't consult for this ticket: a failed `blocked_by` read makes the state of a ticket with an open pull request unread too.
3. **A required read must be on the record.** One that's missing is reported at every value it reaches, exactly like a failed one: no `unread` list can name it. A producer that didn't make a read records it as failed (say, `budget_exhausted`), never leaves it out.
4. **Every record is required by some value** of the view; so a `fleets` view has no CloudRoom read.

This is the check's finding `reads`. The value rules (the state table, merged, the chain, the counts) are checked only on values that are known.

## The envelope

| Field | What |
| --- | --- |
| `schema` | Always `openwiz.fleet.v1` |
| `sources.github` | `gh`: `name`, `version` (a pointer to its `version` read), `tested_version` (the version last live-tested: evidence, never a gate) and `version_tested` (true exactly when the `version` read is complete and equals it) |
| `sources.cloudroom` | `room-cli`, the same four fields. `null` in `fleets` |
| `reads` | Every read, as above |
| `coverage.state` | `complete` exactly when every read is complete; otherwise `partial` |
| `freshness.snapshot_at` | When the reads started, in milliseconds |

## `fleets`: every fleet

`data`: `view`, `repository` and `specs` (pointers), `fleets`, `tickets`, `blockers` and `needs_you`. **No agents:** this view reads nothing from CloudRoom.

- **`fleets`:** one per number of the `spec_list` read's value, in its order: `spec`, `issue` and `tickets` (pointers to its `issue` and `sub_issues` reads) and `progress` (worked out).
- **`tickets`:** every ticket of every listed fleet, once, by number. Each: `number`; `issue`, `blocked_by`, `pr`, `ci`, `review` and `on_base` (pointers); and `state` (worked out: [the state table](#ticket-states)).
- **`blockers`:** every issue a listed ticket's `blocked_by` read names, once, by number, however many tickets it blocks: `number`; `issue`, `pr` and `on_base` (pointers); `fleet` and `merged` (worked out). A blocker that is also a ticket points at the same reads as that ticket.
- **`progress`:** how many of the fleet's tickets are in each state (`merged`, `ready`, `building`, `in_review`, `changes_requested`, `held`, `blocked`), how many are `unknown`, and `tickets`, their sum. "4 of 11 merged" is `merged` of `tickets`; "moving" is `building` + `in_review` + `changes_requested`. It is unread when the fleet's ticket list or any of its tickets' states is.
- **A blocker's `fleet`:** the spec of the listed fleet whose `sub_issues` read names it (the lowest, if several do), or `null` when none does.
- **A blocker's `merged`:** `true` only when its pull request is merged and its `merge_readback` is `true`; `false` when it has an open pull request, several, none, or a merge not found on its base.

## `fleet <spec>`: one fleet

`data`: `view`, `repository`, `projects` and `threads` (pointers), `fleet` (as above), `tickets`, `blockers`, `needs_you` and `unplaced`. Each ticket also has `builder` and `reviewer`.

### A ticket's agents: the verified chain

A thread is a ticket's **builder** only through every link of this chain: **the ticket → its pull request (`pr_discovery`) → that pull request's head branch → the one thread with that branch.** A thread's branch is its `workspace` read (a Cloud thread) or the thread list's `branch` (a local thread); the threads are those of `projects`. **A doubtful link places nothing:** a thread is placed only on the one ticket whose pull request (open or merged) has the thread's branch as its head branch, and only when that pull request closes that ticket alone. So **a thread is placed at most once,** and **a pull request that closes several tickets places nothing.**

`builder` is `{"known": <thread id>}`, or `{"known": null}` when no thread is placed: no pull request, several, no thread with its head branch, or a doubtful link (below). `null` means no thread is placed, never that none exists. A builder that hasn't opened its pull request yet can't be placed. Every builder requires every ticket's pull request and every thread's branch: any of them can make a link doubtful.

**No chain places a reviewer** (a reviewer doesn't push to the pull request's branch, and every verdict comment is by the owner's account). So `reviewer` is always `{"undefined": reason}` in version 1, and a reviewer's thread is listed in `unplaced`, like any thread no chain places.

### Needs you

`needs_you`: `kind`, `spec`, `ticket`, and the T6 question/risk facts described below, by spec, ticket, then kind, for each ticket of each fleet:
- **`needs_info`:** the ticket has the `needs-info` label (a builder's question);
- **`held`:** the ticket has the `held` label.

### Unplaced

`unplaced`: each thread of `threads` (in its order) that is no ticket's builder: `thread` (its id) and `reason`, the first that applies:

| `reason` | The thread |
| --- | --- |
| `no_branch` | Has no branch (a local thread whose list row has none) |
| `shared_branch` | Shares its branch with another listed thread: which one built it can't be told |
| `no_pull_request` | Has a branch that is the head branch of no ticket's pull request (a reviewer's thread, a thread whose pull request isn't open yet or isn't this fleet's) |
| `several_tickets` | Has a branch that is the head branch of more than one ticket's pull request: one pull request closing several tickets, or several pull requests from one branch |
| `several_issues` | Has a branch that is the head branch of one ticket's pull request, which also closes other issues |

It's unread when any read behind the placements is incomplete: a thread's branch, a pull request, the project or thread list, or the fleet's tickets.

## Ticket states

Worked out from the ticket's own reads and its blockers' `merged`, in this order; the first that matches wins. It's only worked out when every read `ticket.state` requires is complete; otherwise it's unread.

| # | When | `state` |
| --- | --- | --- |
| 1 | The pull request is merged and its `merge_readback` is `true` | `merged` |
| 2 | The issue's `state` is `closed` | unknown: closed without a merge read back |
| 3 | `labels` has `held` | `held` |
| 4 | The pull request is open, and its verdict is `changes` on its head | `changes_requested` |
| 5 | The pull request is open, and it's a draft or its CI isn't `passed` | `building` |
| 6 | The pull request is open (not a draft, CI passed, no `changes` on its head: waiting for a verdict, or approved and waiting for the merge) | `in_review` |
| 7 | No pull request, and `labels` has no ready label (`ready-for-agent` or `ready-for-human`) | unknown: not approved yet |
| 8 | No pull request, and a blocker's `merged` is `false` | `blocked` |
| 9 | No pull request, every blocker merged, and `labels` has `ready-for-agent` | `ready` |
| 10 | Anything else: several pull requests; a `ready-for-human` ticket whose blockers have all merged; a merge not found on its base | unknown, with the reason |

A ticket with an open pull request is `building`, `in_review` or `changes_requested` even while a blocker hasn't merged (its builder started early). A merged pull request read back makes it `merged` whatever its CI and verdict were.

**Holds.** A held ticket carries the `held` label: `plan-graph` adds it and takes the ready label off in one edit (#155, merged in #163), and rule 3 makes it `held`, with a "needs you" item. Rule 7 stays for a ticket with neither label: one not approved yet, or one held before #163 by taking its ready label off. The labels can't tell those apart, so it's unknown.

## Approval and authority

**Nothing in this output is authority to start or merge anything.** Not a `ready` state, not a `ready-for-agent` label, not an `approve` verdict: a label means sorted, not approved (`triage`), and who wrote a verdict comment can't be told: every comment is by the owner's account.

Approval has a fixed form, `plan-graph`'s (#99, `skills/plan-graph/SKILL.md`, "Is an approval current?"):
- A plan graph's approval is the spec's last comment starting `**Plan graph approved by`, with the user's exact words, a revision number, the table, a `Fingerprint:` line and the revision text.
- It is **current** only when the `Fingerprint:` line equals the SHA-256 of what `revision.sh <spec>` prints now (the spec's body, and each ticket's number, blockers, body and title). Any change to the plan makes it stale; labels, comments, states and merges don't.

Version 1 doesn't carry approvals. **Spec 2 must check the current approval itself**, by that protocol, before it starts or merges any ticket of a spec, and fail closed: no approval, a stale one, or one it can't read means nothing starts and nothing merges. A ticket's merge also needs the reviewer's own APPROVE naming that exact head and green CI, with the base unchanged (`docs/agents/fleet.md`, ADR 0008), which spec 2 must establish itself; this output's verdicts and checks are what was read, never the decision. If a later version carries approval evidence, it says how it was checked, and spec 2 still never infers it from a label or a verdict.

## Rules the schema can't express

Each has the finding id the check reports. A4 and A5 enforce them; a reader that checks only the schema must not rely on them.

| Id | Rule |
| --- | --- |
| `reads` | **The read rule** (above): a worked-out value is known exactly when every read it requires is complete, and otherwise names exactly the incomplete ones; every required read on the record; no two records for one read or with one id; no record that no value of the view requires |
| `pointer` | A pointer is the id of the read its row names, or `null` when that read doesn't apply |
| `members` | `fleets` is the `spec_list` read's numbers, in order; `tickets` every listed fleet's tickets, and `blockers` every listed ticket's blockers, each once, by number |
| `coverage` | `complete` exactly when every read is complete |
| `version_tested` | `true` exactly when the `version` read is complete and equals `tested_version` |
| `view_sources` | `sources.cloudroom` is `null` in `fleets` and an object in `fleet` |
| `progress` | A known `progress` counts the fleet's tickets by their states |
| `state` | A known or unknown `state` is what the state table gives |
| `merged` | A known `merged` is what its pull request and `merge_readback` give |
| `fleet` | A known `fleet` is the listed fleet whose tickets name it, or `null` |
| `chain` | A known `builder` is what the verified chain gives: the one thread placed on that ticket alone, or `null` |
| `needs_you` | A known `needs_you` is exactly the labelled tickets' items, in order |
| `unplaced` | A known `unplaced` is exactly the threads that are no ticket's builder, in the thread list's order, each with the first reason that applies |
| `several` | A `several` value has at least two numbers, ascending |
| `closes` | A pull request's `closes` names the issue whose `pr_discovery` gave it; two `pr_discovery` reads that give one pull request give it identically |
| `unique` | No label twice in an issue, no check name twice, no project id or thread twice |
| `order` | A spec list, sub-issue list, blocked-by list or `closes` is ascending, each number once |
| `self_block` | A ticket never blocks itself, and a spec is never one of its own sub-issues |

## Where each field comes from

Every field traces to an observed shape in A1's spike (#109, PR #135), or is marked. **observed:** read from that field as A1 recorded it. **derived:** worked out by OpenWiz from observed fields. **pointer:** the id of the read the dependency table names. **envelope:** OpenWiz's own, as `openwiz.inventory.v1`. **synthetic:** not observed; the last column says why. The check fails if a schema field is missing here or a row names no schema field.

| Field | Class | From | Not observed |
| --- | --- | --- | --- |
| `envelope.schema`, `envelope.sources`, `envelope.coverage`, `envelope.freshness`, `envelope.data`, `sources.github`, `sources.cloudroom` | envelope | `openwiz.inventory.v1`'s envelope, with one `source` per tool | — |
| `github_source.name`, `github_source.tested_version`, `github_source.version_tested`, `cloudroom_source.name`, `cloudroom_source.tested_version`, `cloudroom_source.version_tested` | envelope | The inventory's `source` | — |
| `github_source.version`, `cloudroom_source.version`, `fleets_view.repository`, `fleet_view.repository`, `fleets_view.specs`, `fleet_view.projects`, `fleet_view.threads`, `fleet.issue`, `fleet.tickets`, `ticket.issue`, `ticket_core.issue`, `ticket.blocked_by`, `ticket_core.blocked_by`, `ticket.pr`, `ticket_core.pr`, `ticket.ci`, `ticket_core.ci`, `ticket.review`, `ticket_core.review`, `ticket.on_base`, `ticket_core.on_base`, `blocker.issue`, `blocker.pr`, `blocker.on_base` | pointer | The id of the read its dependency-table row names | — |
| `coverage.state`, `freshness.snapshot_at` | envelope | `openwiz.inventory.v1` | — |
| `envelope.reads`, `read.id`, `read.kind`, `read.source`, `read.issue`, `read.spec`, `read.ticket`, `read.pr`, `read.thread`, `read.outcome` | derived | One record per read A1 made (its "What ran" list): `gh --version` (`gh version 2.100.0 (2026-09-03)`) and `room-cli --version` (`v132`), `gh repo view`, the spec list, `gh issue view`, a spec's `subIssues`, a ticket's `blockedBy`, `closingIssuesReferences` with the pull request (`gh pr view`), `gh pr checks`, the pull request's comments, REST `compare` (`status` `ahead` or `identical` with `behind_by` 0: the merge read back), `project list`, `thread list`, `cloud thread-workspace` | `merge_readback` `false`: both of A1's reads found the commit on `main` |
| `failed.state`, `failed.gap`, `failed.reason` | derived | Each read's exit status and answer: the inventory's eight failure kinds, and `truncated` for `nodes` fewer than `totalCount` (A1, "Issues": "a reader must compare `nodes` with `totalCount`, and call the answer partial when they differ") | A partial or failed read: every A1 read was complete |
| `unread.unread`, `unknown.unknown`, `undefined.undefined` | envelope | The forms of a value (above), after the inventory's `{"unknown": reason}` | — |
| `fleets_view.view`, `fleet_view.view` | envelope | OpenWiz's own tag | — |
| `fleets_view.fleets`, `fleet_view.fleet`, `fleet.spec` | observed | Issues with sub-issues: `subIssues` {`nodes`, `totalCount`}, `number` (A1, "Issues": `gh issue view`, `gh issue list --milestone`) | — |
| `issue.title`, `issue.state`, `issue.milestone`, `issue.labels`, `milestone.number`, `milestone.title` | observed | The issue's `title`, `state` (`OPEN`, lowercased), `milestone` {`number`, `title`, …} or `null` (on 0.0.4's #11), `labels[].name` (A1, "Issues", "Labels" and "Cross-version blockers") | `closed`: `CLOSED` was seen on pull requests, not on an issue; the `held` label (added by `plan-graph` since #163, after A1) |
| `issue.owned_paths`, `issue.relies_on` | observed | The body's `**Owned paths:**` and `**Relies on:**` lines (in 11 of 11 bodies; A1, "The ticket template") | — |
| `repository.name` | observed | `gh repo view --json nameWithOwner`, the part after `/` (A1, "What ran") | — |
| `project.id`, `project.name` | observed | `room-cli project list --json --include-personal`: `id`, `name`, and `gitRemoteUrl` (str or null) to match the repository (A1's `mac-output.json`; "2 projects have its GitHub remote") | — |
| `cloud_thread.thread`, `cloud_thread.project`, `cloud_thread.kind`, `local_thread.thread`, `local_thread.project`, `local_thread.kind`, `local_thread.branch` | observed | `room-cli thread list --json`: `id`, `projectId`, `archivedAt` (archived ones left out), `executionTarget` (`cloud`, or a local row with `environmentHostId`) and `environmentBranchName` (str on 65 local rows, null on every Cloud row) (A1, "CloudRoom") | — |
| `fleet.progress`, `progress.known`, `counts.tickets`, `counts.merged`, `counts.ready`, `counts.building`, `counts.in_review`, `counts.changes_requested`, `counts.held`, `counts.blocked`, `counts.unknown` | derived | The fleet's tickets' states | — |
| `fleets_view.needs_you`, `fleet_view.needs_you`, `needs_you.spec`, `needs_you.ticket` | derived | The tickets' labels | — |
| `needs_you.kind` | synthetic | `needs_info` from the `needs-info` label (it exists: A1, "Labels"); `held` from the `held` label (A1's Q3; `plan-graph` adds it since #163) | No `held` label was seen in A1 |
| `fleets_view.tickets`, `fleet_view.tickets`, `ticket.number`, `ticket_core.number` | observed | The spec's `subIssues.nodes[]` (A1, "Issues") | — |
| `ticket.state`, `ticket_core.state` | derived | The state table | — |
| `fleets_view.blockers`, `fleet_view.blockers`, `blocker.number` | observed | `blockedBy` {`nodes[]` {`number`, …}, `totalCount`} (A1, "Issues": 16 edges) | — |
| `blocker.fleet` | derived | The blocker's number against each listed fleet's `subIssues.nodes` | — |
| `blocker.merged` | derived | Its pull request and its merge read back | — |
| `open_pr.number`, `merged_pr.number`, `open_pr.draft`, `merged_pr.draft`, `open_pr.head_branch`, `merged_pr.head_branch`, `open_pr.base_branch`, `merged_pr.base_branch`, `open_pr.state`, `merged_pr.state` | observed | `gh pr view` and `gh pr list`: `number`, `isDraft`, `headRefName`, `baseRefName`, `state` (`OPEN`, `MERGED`); tied by `closingIssuesReferences[].number` (A1, "Pull requests" and "Linked issues"; A1's Q2) | — |
| `open_pr.closes`, `merged_pr.closes` | observed | `closingIssuesReferences[].number` (A1, "Linked issues") | A pull request closing several issues: none in A1 |
| `open_pr.head_commit`, `merged_pr.head_commit` | observed | `headRefOid` (A1, "Pull requests") | 40 hex is observed for `mergeCommit.oid` and `thread-workspace`'s `head`; for `headRefOid`, only its type |
| `merged_pr.merge_commit`, `merged_pr.merged_at` | observed | `mergeCommit.oid` (40 hex) and `mergedAt` (ISO, here in ms), present exactly when `MERGED` (A1: on all 68 pull requests) | — |
| `several_prs.state`, `several_prs.numbers` | synthetic | Two or more open pull requests with the issue's closing reference (`closingIssuesReferences`, A1) | Several open ones: no issue had two in A1 |
| `check.name` | observed | `gh pr checks <n> --json`: one row per check name, its latest run (A1, "Checks") | — |
| `check.result` | observed | The row's `bucket` (A1, "Checks") | `fail`, `skipping`, `cancel`: `gh`'s other buckets; only `pass` and `pending` were seen |
| `review.verdict`, `review.commit` | synthetic | Pull request comments (`comments[].body`, A1, "Pull requests"): on #131, 2 of 2 open with `APPROVE` or `CHANGES`, and 1 names the head commit (A1, "Comments and verdicts"). The line's form is decided by `review-ticket` (#101, merged): `VERDICT: <APPROVE or CHANGES> at <the head commit, all 40 characters>` | A comment in that form: A1 read the older lines, before #101 |
| `ticket.builder` | derived | The chain: the pull request's `headRefName` (unique over 68); a thread's branch (`cloud thread-workspace <id> --json`'s `branch`, equal to its git branch, A1's Q1 (a); or a local row's `environmentBranchName`); `closingIssuesReferences` | `thread-workspace`'s error shapes |
| `ticket.reviewer` | synthetic | No chain ties a reviewer to a pull request yet: every verdict comment is by the owner's account (`authorAssociation` `OWNER`, A1). So it is `undefined` in version 1 | The whole chain |
| `fleet_view.unplaced`, `unplaced.thread`, `unplaced.reason` | derived | The projects' threads that no chain places, and the first link that fails | `shared_branch`, `several_tickets`, `several_issues`: no thread, pull request or branch was shared in A1 |

## Examples

Originally generated for A2; its contract check rejects a differing example. Synthetic values only.

1. **`fleets`, complete:** fleets 901 (one ticket in each state) and 930. #902 is a ticket of 901 and blocks #932 of 930: one `blockers` entry, pointing at #902's own reads.
2. **`fleet 901`, complete:** the same fleet, with builders: five threads placed by the chain, two Cloud threads and one local one unplaced (their branches head no pull request).
3. **`fleet 930`, partial:** CloudRoom's version unreadable; #931's checks failed (its state unread); #932's blocker list truncated and its blocker #840 unreadable (its state unread); one thread's branch unreadable (every builder and `unplaced` unread).

```json
{
  "schema": "openwiz.fleet.v1",
  "sources": {"github": {"name": "gh", "version": "r1", "tested_version": "2.100.0", "version_tested": true}, "cloudroom": null},
  "reads": [
    {"id": "r1", "kind": "version", "source": "github", "outcome": {"state": "complete", "value": "2.100.0"}},
    {"id": "r2", "kind": "repository", "outcome": {"state": "complete", "value": {"name": "example-repo"}}},
    {"id": "r3", "kind": "spec_list", "outcome": {"state": "complete", "value": [901, 930]}},
    {
      "id": "r4",
      "kind": "issue",
      "issue": 901,
      "outcome": {
        "state": "complete",
        "value": {"title": "Synthetic spec one", "state": "open", "milestone": {"number": 7, "title": "0.9.1"}, "labels": ["spec"], "owned_paths": null, "relies_on": null}
      }
    },
    {"id": "r5", "kind": "sub_issues", "spec": 901, "outcome": {"state": "complete", "value": [902, 903, 904, 905, 906, 907, 908, 909, 910]}},
    {
      "id": "r6",
      "kind": "issue",
      "issue": 902,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A1",
          "state": "closed",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`contracts/example.v1.md`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r7", "kind": "blocked_by", "ticket": 902, "outcome": {"state": "complete", "value": []}},
    {
      "id": "r8",
      "kind": "pr_discovery",
      "issue": 902,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 951,
          "state": "merged",
          "draft": false,
          "head_branch": "room/syn-a1-0001",
          "head_commit": "1111111111111111111111111111111111111111",
          "base_branch": "main",
          "closes": [902],
          "merge_commit": "2222222222222222222222222222222222222222",
          "merged_at": 1793385000000
        }
      }
    },
    {"id": "r9", "kind": "merge_readback", "pr": 951, "outcome": {"state": "complete", "value": true}},
    {
      "id": "r10",
      "kind": "issue",
      "issue": 903,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A2",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/a2.rs`",
          "relies_on": "`contracts/example.v1.md`"
        }
      }
    },
    {"id": "r11", "kind": "blocked_by", "ticket": 903, "outcome": {"state": "complete", "value": [902]}},
    {
      "id": "r12",
      "kind": "pr_discovery",
      "issue": 903,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 952,
          "state": "open",
          "draft": false,
          "head_branch": "room/syn-a2-0002",
          "head_commit": "3333333333333333333333333333333333333333",
          "base_branch": "main",
          "closes": [903]
        }
      }
    },
    {"id": "r13", "kind": "checks", "pr": 952, "outcome": {"state": "complete", "value": [{"name": "build", "result": "pass"}, {"name": "test", "result": "pass"}]}},
    {"id": "r14", "kind": "comments", "pr": 952, "outcome": {"state": "complete", "value": {"verdict": "approve", "commit": "3333333333333333333333333333333333333333"}}},
    {
      "id": "r15",
      "kind": "issue",
      "issue": 904,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A3",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["needs-info", "ready-for-agent"],
          "owned_paths": "`crates/example/src/a3.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r16", "kind": "blocked_by", "ticket": 904, "outcome": {"state": "complete", "value": []}},
    {
      "id": "r17",
      "kind": "pr_discovery",
      "issue": 904,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 953,
          "state": "open",
          "draft": false,
          "head_branch": "room/syn-a3-0003",
          "head_commit": "4444444444444444444444444444444444444444",
          "base_branch": "main",
          "closes": [904]
        }
      }
    },
    {"id": "r18", "kind": "checks", "pr": 953, "outcome": {"state": "complete", "value": [{"name": "build", "result": "pass"}, {"name": "test", "result": "pass"}]}},
    {"id": "r19", "kind": "comments", "pr": 953, "outcome": {"state": "complete", "value": {"verdict": "changes", "commit": "4444444444444444444444444444444444444444"}}},
    {
      "id": "r20",
      "kind": "issue",
      "issue": 905,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A4",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/a4.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r21", "kind": "blocked_by", "ticket": 905, "outcome": {"state": "complete", "value": []}},
    {
      "id": "r22",
      "kind": "pr_discovery",
      "issue": 905,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 954,
          "state": "open",
          "draft": true,
          "head_branch": "room/syn-a4-0004",
          "head_commit": "5555555555555555555555555555555555555555",
          "base_branch": "main",
          "closes": [905]
        }
      }
    },
    {"id": "r23", "kind": "checks", "pr": 954, "outcome": {"state": "complete", "value": []}},
    {"id": "r24", "kind": "comments", "pr": 954, "outcome": {"state": "complete", "value": null}},
    {
      "id": "r25",
      "kind": "issue",
      "issue": 906,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A5",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/a5.rs`",
          "relies_on": "`contracts/example.v1.md`"
        }
      }
    },
    {"id": "r26", "kind": "blocked_by", "ticket": 906, "outcome": {"state": "complete", "value": [902]}},
    {"id": "r27", "kind": "pr_discovery", "issue": 906, "outcome": {"state": "complete", "value": null}},
    {
      "id": "r28",
      "kind": "issue",
      "issue": 907,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A6",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["held"],
          "owned_paths": "`crates/example/src/a6.rs`",
          "relies_on": "`contracts/example.v1.md`"
        }
      }
    },
    {"id": "r29", "kind": "blocked_by", "ticket": 907, "outcome": {"state": "complete", "value": []}},
    {"id": "r30", "kind": "pr_discovery", "issue": 907, "outcome": {"state": "complete", "value": null}},
    {
      "id": "r31",
      "kind": "issue",
      "issue": 908,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A7",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/a7.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r32", "kind": "blocked_by", "ticket": 908, "outcome": {"state": "complete", "value": [811, 812, 903]}},
    {"id": "r33", "kind": "pr_discovery", "issue": 908, "outcome": {"state": "complete", "value": null}},
    {
      "id": "r34",
      "kind": "issue",
      "issue": 909,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A8",
          "state": "closed",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/a8.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r35", "kind": "blocked_by", "ticket": 909, "outcome": {"state": "complete", "value": []}},
    {"id": "r36", "kind": "pr_discovery", "issue": 909, "outcome": {"state": "complete", "value": null}},
    {
      "id": "r37",
      "kind": "issue",
      "issue": 910,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A9",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/a9.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r38", "kind": "blocked_by", "ticket": 910, "outcome": {"state": "complete", "value": []}},
    {
      "id": "r39",
      "kind": "pr_discovery",
      "issue": 910,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 955,
          "state": "open",
          "draft": false,
          "head_branch": "room/syn-a9-0006",
          "head_commit": "6666666666666666666666666666666666666666",
          "base_branch": "main",
          "closes": [910]
        }
      }
    },
    {"id": "r40", "kind": "checks", "pr": 955, "outcome": {"state": "complete", "value": [{"name": "build", "result": "pass"}, {"name": "test", "result": "fail"}]}},
    {"id": "r41", "kind": "comments", "pr": 955, "outcome": {"state": "complete", "value": {"verdict": "changes", "commit": "7777777777777777777777777777777777777777"}}},
    {
      "id": "r42",
      "kind": "issue",
      "issue": 811,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket from 0.9.0",
          "state": "closed",
          "milestone": {"number": 6, "title": "0.9.0"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/old.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {
      "id": "r43",
      "kind": "pr_discovery",
      "issue": 811,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 801,
          "state": "merged",
          "draft": false,
          "head_branch": "room/syn-old-0801",
          "head_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "base_branch": "main",
          "closes": [811],
          "merge_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "merged_at": 1793385000000
        }
      }
    },
    {"id": "r44", "kind": "merge_readback", "pr": 801, "outcome": {"state": "complete", "value": true}},
    {
      "id": "r45",
      "kind": "issue",
      "issue": 812,
      "outcome": {
        "state": "complete",
        "value": {"title": "Synthetic ticket with no milestone", "state": "closed", "milestone": null, "labels": [], "owned_paths": null, "relies_on": null}
      }
    },
    {
      "id": "r46",
      "kind": "pr_discovery",
      "issue": 812,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 802,
          "state": "merged",
          "draft": false,
          "head_branch": "room/syn-old-0802",
          "head_commit": "cccccccccccccccccccccccccccccccccccccccc",
          "base_branch": "main",
          "closes": [812],
          "merge_commit": "dddddddddddddddddddddddddddddddddddddddd",
          "merged_at": 1793385000000
        }
      }
    },
    {"id": "r47", "kind": "merge_readback", "pr": 802, "outcome": {"state": "complete", "value": true}},
    {
      "id": "r48",
      "kind": "issue",
      "issue": 930,
      "outcome": {"state": "complete", "value": {"title": "Synthetic spec two", "state": "open", "milestone": null, "labels": ["spec"], "owned_paths": null, "relies_on": null}}
    },
    {"id": "r49", "kind": "sub_issues", "spec": 930, "outcome": {"state": "complete", "value": [931, 932]}},
    {
      "id": "r50",
      "kind": "issue",
      "issue": 931,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket B1",
          "state": "open",
          "milestone": null,
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/b1.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r51", "kind": "blocked_by", "ticket": 931, "outcome": {"state": "complete", "value": []}},
    {"id": "r52", "kind": "pr_discovery", "issue": 931, "outcome": {"state": "complete", "value": null}},
    {
      "id": "r53",
      "kind": "issue",
      "issue": 932,
      "outcome": {
        "state": "complete",
        "value": {"title": "Synthetic ticket B2", "state": "open", "milestone": null, "labels": ["ready-for-agent"], "owned_paths": null, "relies_on": null}
      }
    },
    {"id": "r54", "kind": "blocked_by", "ticket": 932, "outcome": {"state": "complete", "value": [902, 931]}},
    {"id": "r55", "kind": "pr_discovery", "issue": 932, "outcome": {"state": "complete", "value": null}}
  ],
  "coverage": {"state": "complete"},
  "freshness": {"snapshot_at": 1793437200000},
  "data": {
    "view": "fleets",
    "repository": "r2",
    "specs": "r3",
    "fleets": [
      {
        "spec": 901,
        "issue": "r4",
        "tickets": "r5",
        "progress": {"known": {"tickets": 9, "ready": 1, "building": 2, "in_review": 1, "changes_requested": 1, "merged": 1, "held": 1, "blocked": 1, "unknown": 1}}
      },
      {
        "spec": 930,
        "issue": "r48",
        "tickets": "r49",
        "progress": {"known": {"tickets": 2, "ready": 1, "building": 0, "in_review": 0, "changes_requested": 0, "merged": 0, "held": 0, "blocked": 1, "unknown": 0}}
      }
    ],
    "tickets": [
      {"number": 902, "issue": "r6", "blocked_by": "r7", "pr": "r8", "ci": null, "review": null, "on_base": "r9", "state": {"known": "merged"}},
      {"number": 903, "issue": "r10", "blocked_by": "r11", "pr": "r12", "ci": "r13", "review": "r14", "on_base": null, "state": {"known": "in_review"}},
      {"number": 904, "issue": "r15", "blocked_by": "r16", "pr": "r17", "ci": "r18", "review": "r19", "on_base": null, "state": {"known": "changes_requested"}},
      {"number": 905, "issue": "r20", "blocked_by": "r21", "pr": "r22", "ci": "r23", "review": "r24", "on_base": null, "state": {"known": "building"}},
      {"number": 906, "issue": "r25", "blocked_by": "r26", "pr": "r27", "ci": null, "review": null, "on_base": null, "state": {"known": "ready"}},
      {"number": 907, "issue": "r28", "blocked_by": "r29", "pr": "r30", "ci": null, "review": null, "on_base": null, "state": {"known": "held"}},
      {"number": 908, "issue": "r31", "blocked_by": "r32", "pr": "r33", "ci": null, "review": null, "on_base": null, "state": {"known": "blocked"}},
      {
        "number": 909,
        "issue": "r34",
        "blocked_by": "r35",
        "pr": "r36",
        "ci": null,
        "review": null,
        "on_base": null,
        "state": {"unknown": "closed on GitHub, and no merge was read back"}
      },
      {"number": 910, "issue": "r37", "blocked_by": "r38", "pr": "r39", "ci": "r40", "review": "r41", "on_base": null, "state": {"known": "building"}},
      {"number": 931, "issue": "r50", "blocked_by": "r51", "pr": "r52", "ci": null, "review": null, "on_base": null, "state": {"known": "ready"}},
      {"number": 932, "issue": "r53", "blocked_by": "r54", "pr": "r55", "ci": null, "review": null, "on_base": null, "state": {"known": "blocked"}}
    ],
    "blockers": [
      {"number": 811, "issue": "r42", "pr": "r43", "on_base": "r44", "fleet": {"known": null}, "merged": {"known": true}},
      {"number": 812, "issue": "r45", "pr": "r46", "on_base": "r47", "fleet": {"known": null}, "merged": {"known": true}},
      {"number": 902, "issue": "r6", "pr": "r8", "on_base": "r9", "fleet": {"known": 901}, "merged": {"known": true}},
      {"number": 903, "issue": "r10", "pr": "r12", "on_base": null, "fleet": {"known": 901}, "merged": {"known": false}},
      {"number": 931, "issue": "r50", "pr": "r52", "on_base": null, "fleet": {"known": 930}, "merged": {"known": false}}
    ],
    "needs_you": {"known": [{"kind": "needs_info", "spec": 901, "ticket": 904, "wording": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "link": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "asked_at": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "risk": {"unknown": "no explicit risk classification was reported"}}, {"kind": "held", "spec": 901, "ticket": 907, "wording": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "link": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "asked_at": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "risk": {"unknown": "no explicit risk classification was reported"}}]}
  }
}
```

```json
{
  "schema": "openwiz.fleet.v1",
  "sources": {
    "github": {"name": "gh", "version": "r1", "tested_version": "2.100.0", "version_tested": true},
    "cloudroom": {"name": "room-cli", "version": "r2", "tested_version": "v127", "version_tested": false}
  },
  "reads": [
    {"id": "r1", "kind": "version", "source": "github", "outcome": {"state": "complete", "value": "2.100.0"}},
    {"id": "r2", "kind": "version", "source": "cloudroom", "outcome": {"state": "complete", "value": "v132"}},
    {"id": "r3", "kind": "repository", "outcome": {"state": "complete", "value": {"name": "example-repo"}}},
    {
      "id": "r4",
      "kind": "issue",
      "issue": 901,
      "outcome": {
        "state": "complete",
        "value": {"title": "Synthetic spec one", "state": "open", "milestone": {"number": 7, "title": "0.9.1"}, "labels": ["spec"], "owned_paths": null, "relies_on": null}
      }
    },
    {"id": "r5", "kind": "sub_issues", "spec": 901, "outcome": {"state": "complete", "value": [902, 903, 904, 905, 906, 907, 908, 909, 910]}},
    {
      "id": "r6",
      "kind": "issue",
      "issue": 902,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A1",
          "state": "closed",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`contracts/example.v1.md`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r7", "kind": "blocked_by", "ticket": 902, "outcome": {"state": "complete", "value": []}},
    {
      "id": "r8",
      "kind": "pr_discovery",
      "issue": 902,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 951,
          "state": "merged",
          "draft": false,
          "head_branch": "room/syn-a1-0001",
          "head_commit": "1111111111111111111111111111111111111111",
          "base_branch": "main",
          "closes": [902],
          "merge_commit": "2222222222222222222222222222222222222222",
          "merged_at": 1793385000000
        }
      }
    },
    {"id": "r9", "kind": "merge_readback", "pr": 951, "outcome": {"state": "complete", "value": true}},
    {
      "id": "r10",
      "kind": "issue",
      "issue": 903,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A2",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/a2.rs`",
          "relies_on": "`contracts/example.v1.md`"
        }
      }
    },
    {"id": "r11", "kind": "blocked_by", "ticket": 903, "outcome": {"state": "complete", "value": [902]}},
    {
      "id": "r12",
      "kind": "pr_discovery",
      "issue": 903,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 952,
          "state": "open",
          "draft": false,
          "head_branch": "room/syn-a2-0002",
          "head_commit": "3333333333333333333333333333333333333333",
          "base_branch": "main",
          "closes": [903]
        }
      }
    },
    {"id": "r13", "kind": "checks", "pr": 952, "outcome": {"state": "complete", "value": [{"name": "build", "result": "pass"}, {"name": "test", "result": "pass"}]}},
    {"id": "r14", "kind": "comments", "pr": 952, "outcome": {"state": "complete", "value": {"verdict": "approve", "commit": "3333333333333333333333333333333333333333"}}},
    {
      "id": "r15",
      "kind": "issue",
      "issue": 904,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A3",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["needs-info", "ready-for-agent"],
          "owned_paths": "`crates/example/src/a3.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r16", "kind": "blocked_by", "ticket": 904, "outcome": {"state": "complete", "value": []}},
    {
      "id": "r17",
      "kind": "pr_discovery",
      "issue": 904,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 953,
          "state": "open",
          "draft": false,
          "head_branch": "room/syn-a3-0003",
          "head_commit": "4444444444444444444444444444444444444444",
          "base_branch": "main",
          "closes": [904]
        }
      }
    },
    {"id": "r18", "kind": "checks", "pr": 953, "outcome": {"state": "complete", "value": [{"name": "build", "result": "pass"}, {"name": "test", "result": "pass"}]}},
    {"id": "r19", "kind": "comments", "pr": 953, "outcome": {"state": "complete", "value": {"verdict": "changes", "commit": "4444444444444444444444444444444444444444"}}},
    {
      "id": "r20",
      "kind": "issue",
      "issue": 905,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A4",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/a4.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r21", "kind": "blocked_by", "ticket": 905, "outcome": {"state": "complete", "value": []}},
    {
      "id": "r22",
      "kind": "pr_discovery",
      "issue": 905,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 954,
          "state": "open",
          "draft": true,
          "head_branch": "room/syn-a4-0004",
          "head_commit": "5555555555555555555555555555555555555555",
          "base_branch": "main",
          "closes": [905]
        }
      }
    },
    {"id": "r23", "kind": "checks", "pr": 954, "outcome": {"state": "complete", "value": []}},
    {"id": "r24", "kind": "comments", "pr": 954, "outcome": {"state": "complete", "value": null}},
    {
      "id": "r25",
      "kind": "issue",
      "issue": 906,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A5",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/a5.rs`",
          "relies_on": "`contracts/example.v1.md`"
        }
      }
    },
    {"id": "r26", "kind": "blocked_by", "ticket": 906, "outcome": {"state": "complete", "value": [902]}},
    {"id": "r27", "kind": "pr_discovery", "issue": 906, "outcome": {"state": "complete", "value": null}},
    {
      "id": "r28",
      "kind": "issue",
      "issue": 907,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A6",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["held"],
          "owned_paths": "`crates/example/src/a6.rs`",
          "relies_on": "`contracts/example.v1.md`"
        }
      }
    },
    {"id": "r29", "kind": "blocked_by", "ticket": 907, "outcome": {"state": "complete", "value": []}},
    {"id": "r30", "kind": "pr_discovery", "issue": 907, "outcome": {"state": "complete", "value": null}},
    {
      "id": "r31",
      "kind": "issue",
      "issue": 908,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A7",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/a7.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r32", "kind": "blocked_by", "ticket": 908, "outcome": {"state": "complete", "value": [811, 812, 903]}},
    {"id": "r33", "kind": "pr_discovery", "issue": 908, "outcome": {"state": "complete", "value": null}},
    {
      "id": "r34",
      "kind": "issue",
      "issue": 909,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A8",
          "state": "closed",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/a8.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r35", "kind": "blocked_by", "ticket": 909, "outcome": {"state": "complete", "value": []}},
    {"id": "r36", "kind": "pr_discovery", "issue": 909, "outcome": {"state": "complete", "value": null}},
    {
      "id": "r37",
      "kind": "issue",
      "issue": 910,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket A9",
          "state": "open",
          "milestone": {"number": 7, "title": "0.9.1"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/a9.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r38", "kind": "blocked_by", "ticket": 910, "outcome": {"state": "complete", "value": []}},
    {
      "id": "r39",
      "kind": "pr_discovery",
      "issue": 910,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 955,
          "state": "open",
          "draft": false,
          "head_branch": "room/syn-a9-0006",
          "head_commit": "6666666666666666666666666666666666666666",
          "base_branch": "main",
          "closes": [910]
        }
      }
    },
    {"id": "r40", "kind": "checks", "pr": 955, "outcome": {"state": "complete", "value": [{"name": "build", "result": "pass"}, {"name": "test", "result": "fail"}]}},
    {"id": "r41", "kind": "comments", "pr": 955, "outcome": {"state": "complete", "value": {"verdict": "changes", "commit": "7777777777777777777777777777777777777777"}}},
    {
      "id": "r42",
      "kind": "issue",
      "issue": 811,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket from 0.9.0",
          "state": "closed",
          "milestone": {"number": 6, "title": "0.9.0"},
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/old.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {
      "id": "r43",
      "kind": "pr_discovery",
      "issue": 811,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 801,
          "state": "merged",
          "draft": false,
          "head_branch": "room/syn-old-0801",
          "head_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "base_branch": "main",
          "closes": [811],
          "merge_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "merged_at": 1793385000000
        }
      }
    },
    {"id": "r44", "kind": "merge_readback", "pr": 801, "outcome": {"state": "complete", "value": true}},
    {
      "id": "r45",
      "kind": "issue",
      "issue": 812,
      "outcome": {
        "state": "complete",
        "value": {"title": "Synthetic ticket with no milestone", "state": "closed", "milestone": null, "labels": [], "owned_paths": null, "relies_on": null}
      }
    },
    {
      "id": "r46",
      "kind": "pr_discovery",
      "issue": 812,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 802,
          "state": "merged",
          "draft": false,
          "head_branch": "room/syn-old-0802",
          "head_commit": "cccccccccccccccccccccccccccccccccccccccc",
          "base_branch": "main",
          "closes": [812],
          "merge_commit": "dddddddddddddddddddddddddddddddddddddddd",
          "merged_at": 1793385000000
        }
      }
    },
    {"id": "r47", "kind": "merge_readback", "pr": 802, "outcome": {"state": "complete", "value": true}},
    {"id": "r48", "kind": "projects", "outcome": {"state": "complete", "value": [{"id": "prj_syn_0001", "name": "Synthetic project"}]}},
    {
      "id": "r49",
      "kind": "threads",
      "outcome": {
        "state": "complete",
        "value": [
          {"thread": "thr_syn_0002", "project": "prj_syn_0001", "kind": "cloud"},
          {"thread": "thr_syn_0003", "project": "prj_syn_0001", "kind": "cloud"},
          {"thread": "thr_syn_0004", "project": "prj_syn_0001", "kind": "cloud"},
          {"thread": "thr_syn_0005", "project": "prj_syn_0001", "kind": "cloud"},
          {"thread": "thr_syn_0006", "project": "prj_syn_0001", "kind": "cloud"},
          {"thread": "thr_syn_0007", "project": "prj_syn_0001", "kind": "cloud"},
          {"thread": "thr_syn_0008", "project": "prj_syn_0001", "kind": "cloud"},
          {"thread": "thr_syn_0009", "project": "prj_syn_0001", "kind": "local", "branch": "room/syn-local-0009"}
        ]
      }
    },
    {"id": "r50", "kind": "workspace", "thread": "thr_syn_0002", "outcome": {"state": "complete", "value": "room/syn-a1-0001"}},
    {"id": "r51", "kind": "workspace", "thread": "thr_syn_0003", "outcome": {"state": "complete", "value": "room/syn-a2-0002"}},
    {"id": "r52", "kind": "workspace", "thread": "thr_syn_0004", "outcome": {"state": "complete", "value": "room/syn-a3-0003"}},
    {"id": "r53", "kind": "workspace", "thread": "thr_syn_0005", "outcome": {"state": "complete", "value": "room/syn-a4-0004"}},
    {"id": "r54", "kind": "workspace", "thread": "thr_syn_0006", "outcome": {"state": "complete", "value": "room/syn-a9-0006"}},
    {"id": "r55", "kind": "workspace", "thread": "thr_syn_0007", "outcome": {"state": "complete", "value": "room/syn-x-0007"}},
    {"id": "r56", "kind": "workspace", "thread": "thr_syn_0008", "outcome": {"state": "complete", "value": "room/syn-x-0008"}}
  ],
  "coverage": {"state": "complete"},
  "freshness": {"snapshot_at": 1793437200000},
  "data": {
    "view": "fleet",
    "repository": "r3",
    "projects": "r48",
    "threads": "r49",
    "fleet": {
      "spec": 901,
      "issue": "r4",
      "tickets": "r5",
      "progress": {"known": {"tickets": 9, "ready": 1, "building": 2, "in_review": 1, "changes_requested": 1, "merged": 1, "held": 1, "blocked": 1, "unknown": 1}}
    },
    "tickets": [
      {
        "number": 902,
        "issue": "r6",
        "blocked_by": "r7",
        "pr": "r8",
        "ci": null,
        "review": null,
        "on_base": "r9",
        "state": {"known": "merged"},
        "builder": {"known": "thr_syn_0002"},
        "reviewer": {"undefined": "no verified chain places a reviewer in version 1"}
      },
      {
        "number": 903,
        "issue": "r10",
        "blocked_by": "r11",
        "pr": "r12",
        "ci": "r13",
        "review": "r14",
        "on_base": null,
        "state": {"known": "in_review"},
        "builder": {"known": "thr_syn_0003"},
        "reviewer": {"undefined": "no verified chain places a reviewer in version 1"}
      },
      {
        "number": 904,
        "issue": "r15",
        "blocked_by": "r16",
        "pr": "r17",
        "ci": "r18",
        "review": "r19",
        "on_base": null,
        "state": {"known": "changes_requested"},
        "builder": {"known": "thr_syn_0004"},
        "reviewer": {"undefined": "no verified chain places a reviewer in version 1"}
      },
      {
        "number": 905,
        "issue": "r20",
        "blocked_by": "r21",
        "pr": "r22",
        "ci": "r23",
        "review": "r24",
        "on_base": null,
        "state": {"known": "building"},
        "builder": {"known": "thr_syn_0005"},
        "reviewer": {"undefined": "no verified chain places a reviewer in version 1"}
      },
      {
        "number": 906,
        "issue": "r25",
        "blocked_by": "r26",
        "pr": "r27",
        "ci": null,
        "review": null,
        "on_base": null,
        "state": {"known": "ready"},
        "builder": {"known": null},
        "reviewer": {"undefined": "no verified chain places a reviewer in version 1"}
      },
      {
        "number": 907,
        "issue": "r28",
        "blocked_by": "r29",
        "pr": "r30",
        "ci": null,
        "review": null,
        "on_base": null,
        "state": {"known": "held"},
        "builder": {"known": null},
        "reviewer": {"undefined": "no verified chain places a reviewer in version 1"}
      },
      {
        "number": 908,
        "issue": "r31",
        "blocked_by": "r32",
        "pr": "r33",
        "ci": null,
        "review": null,
        "on_base": null,
        "state": {"known": "blocked"},
        "builder": {"known": null},
        "reviewer": {"undefined": "no verified chain places a reviewer in version 1"}
      },
      {
        "number": 909,
        "issue": "r34",
        "blocked_by": "r35",
        "pr": "r36",
        "ci": null,
        "review": null,
        "on_base": null,
        "state": {"unknown": "closed on GitHub, and no merge was read back"},
        "builder": {"known": null},
        "reviewer": {"undefined": "no verified chain places a reviewer in version 1"}
      },
      {
        "number": 910,
        "issue": "r37",
        "blocked_by": "r38",
        "pr": "r39",
        "ci": "r40",
        "review": "r41",
        "on_base": null,
        "state": {"known": "building"},
        "builder": {"known": "thr_syn_0006"},
        "reviewer": {"undefined": "no verified chain places a reviewer in version 1"}
      }
    ],
    "blockers": [
      {"number": 811, "issue": "r42", "pr": "r43", "on_base": "r44", "fleet": {"known": null}, "merged": {"known": true}},
      {"number": 812, "issue": "r45", "pr": "r46", "on_base": "r47", "fleet": {"known": null}, "merged": {"known": true}},
      {"number": 902, "issue": "r6", "pr": "r8", "on_base": "r9", "fleet": {"known": 901}, "merged": {"known": true}},
      {"number": 903, "issue": "r10", "pr": "r12", "on_base": null, "fleet": {"known": 901}, "merged": {"known": false}}
    ],
    "needs_you": {"known": [{"kind": "needs_info", "spec": 901, "ticket": 904, "wording": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "link": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "asked_at": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "risk": {"unknown": "no explicit risk classification was reported"}}, {"kind": "held", "spec": 901, "ticket": 907, "wording": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "link": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "asked_at": {"unknown": "no unique newest needs-you or Needs you comment was found"}, "risk": {"unknown": "no explicit risk classification was reported"}}]},
    "unplaced": {
      "known": [
        {"thread": "thr_syn_0007", "reason": "no_pull_request"},
        {"thread": "thr_syn_0008", "reason": "no_pull_request"},
        {"thread": "thr_syn_0009", "reason": "no_pull_request"}
      ]
    }
  }
}
```

```json
{
  "schema": "openwiz.fleet.v1",
  "sources": {
    "github": {"name": "gh", "version": "r1", "tested_version": "2.100.0", "version_tested": true},
    "cloudroom": {"name": "room-cli", "version": "r2", "tested_version": "v127", "version_tested": false}
  },
  "reads": [
    {"id": "r1", "kind": "version", "source": "github", "outcome": {"state": "complete", "value": "2.100.0"}},
    {"id": "r2", "kind": "version", "source": "cloudroom", "outcome": {"state": "failed", "gap": "untested_version", "reason": "room-cli --version printed no version"}},
    {"id": "r3", "kind": "repository", "outcome": {"state": "complete", "value": {"name": "example-repo"}}},
    {
      "id": "r4",
      "kind": "issue",
      "issue": 930,
      "outcome": {"state": "complete", "value": {"title": "Synthetic spec two", "state": "open", "milestone": null, "labels": ["spec"], "owned_paths": null, "relies_on": null}}
    },
    {"id": "r5", "kind": "sub_issues", "spec": 930, "outcome": {"state": "complete", "value": [931, 932]}},
    {
      "id": "r6",
      "kind": "issue",
      "issue": 931,
      "outcome": {
        "state": "complete",
        "value": {
          "title": "Synthetic ticket B1",
          "state": "open",
          "milestone": null,
          "labels": ["ready-for-agent"],
          "owned_paths": "`crates/example/src/b1.rs`",
          "relies_on": "nothing"
        }
      }
    },
    {"id": "r7", "kind": "blocked_by", "ticket": 931, "outcome": {"state": "complete", "value": []}},
    {
      "id": "r8",
      "kind": "pr_discovery",
      "issue": 931,
      "outcome": {
        "state": "complete",
        "value": {
          "number": 961,
          "state": "open",
          "draft": false,
          "head_branch": "room/syn-b1-0011",
          "head_commit": "8888888888888888888888888888888888888888",
          "base_branch": "main",
          "closes": [931]
        }
      }
    },
    {"id": "r9", "kind": "checks", "pr": 961, "outcome": {"state": "failed", "gap": "command_failed", "reason": "the checks of pull request 961 couldn't be read"}},
    {"id": "r10", "kind": "comments", "pr": 961, "outcome": {"state": "complete", "value": null}},
    {
      "id": "r11",
      "kind": "issue",
      "issue": 932,
      "outcome": {
        "state": "complete",
        "value": {"title": "Synthetic ticket B2", "state": "open", "milestone": null, "labels": ["ready-for-agent"], "owned_paths": null, "relies_on": null}
      }
    },
    {
      "id": "r12",
      "kind": "blocked_by",
      "ticket": 932,
      "outcome": {"state": "partial", "gap": "truncated", "reason": "GitHub listed 2 of #932's 3 blockers", "value": [840, 931]}
    },
    {"id": "r13", "kind": "pr_discovery", "issue": 932, "outcome": {"state": "complete", "value": null}},
    {"id": "r14", "kind": "issue", "issue": 840, "outcome": {"state": "failed", "gap": "not_found", "reason": "#840 couldn't be read"}},
    {"id": "r15", "kind": "pr_discovery", "issue": 840, "outcome": {"state": "failed", "gap": "not_found", "reason": "#840 couldn't be read"}},
    {"id": "r16", "kind": "projects", "outcome": {"state": "complete", "value": [{"id": "prj_syn_0001", "name": "Synthetic project"}]}},
    {
      "id": "r17",
      "kind": "threads",
      "outcome": {
        "state": "complete",
        "value": [{"thread": "thr_syn_0011", "project": "prj_syn_0001", "kind": "cloud"}, {"thread": "thr_syn_0012", "project": "prj_syn_0001", "kind": "cloud"}]
      }
    },
    {"id": "r18", "kind": "workspace", "thread": "thr_syn_0011", "outcome": {"state": "complete", "value": "room/syn-b1-0011"}},
    {
      "id": "r19",
      "kind": "workspace",
      "thread": "thr_syn_0012",
      "outcome": {"state": "failed", "gap": "command_failed", "reason": "the branch of one project thread couldn't be read"}
    }
  ],
  "coverage": {"state": "partial"},
  "freshness": {"snapshot_at": 1793437200000},
  "data": {
    "view": "fleet",
    "repository": "r3",
    "projects": "r16",
    "threads": "r17",
    "fleet": {"spec": 930, "issue": "r4", "tickets": "r5", "progress": {"unread": ["r9", "r12", "r15"]}},
    "tickets": [
      {
        "number": 931,
        "issue": "r6",
        "blocked_by": "r7",
        "pr": "r8",
        "ci": "r9",
        "review": "r10",
        "on_base": null,
        "state": {"unread": ["r9"]},
        "builder": {"unread": ["r19"]},
        "reviewer": {"undefined": "no verified chain places a reviewer in version 1"}
      },
      {
        "number": 932,
        "issue": "r11",
        "blocked_by": "r12",
        "pr": "r13",
        "ci": null,
        "review": null,
        "on_base": null,
        "state": {"unread": ["r12", "r15"]},
        "builder": {"unread": ["r19"]},
        "reviewer": {"undefined": "no verified chain places a reviewer in version 1"}
      }
    ],
    "blockers": [
      {"number": 840, "issue": "r14", "pr": "r15", "on_base": null, "fleet": {"known": null}, "merged": {"unread": ["r15"]}},
      {"number": 931, "issue": "r6", "pr": "r8", "on_base": null, "fleet": {"known": 930}, "merged": {"known": false}}
    ],
    "needs_you": {"known": []},
    "unplaced": {"unread": ["r19"]}
  }
}
```

## Not in version 1

Open, for later tickets or Jake; none is guessed in the meantime:

1. **Reviewers.** No chain ties a reviewer thread to its pull request (above): `reviewer` is `undefined`. `review-ticket`'s report names the reviewer's harness, model and effort, not its thread.
2. **Tickets that match no state.** No pull request, every blocker merged, and no `ready-for-agent` label: a `ready-for-human` ticket (1 of 11 in #95), a `needs-triage` follow-up, a ticket not yet approved. Each is unknown with its reason (rules 7 and 10).
3. **A builder before its pull request opens** can't be placed: the chain starts at the pull request. Its ticket shows `ready`, and the thread is unplaced. Spec 2's record of builders it starts closes this.
4. **Escalations:** T6 adds selected pending-question wording and provenance from the ticket’s own comments, as described below; other comment forms remain unreported.
5. **Approval** isn't carried: see "Approval and authority". A fleet is any spec with sub-issues, approved or not.
6. **Holds made before #163** took the ready label off instead of adding `held`: rule 7 keeps such a ticket unknown, with no "needs you" item.
7. **Label names.** This contract uses the triage roles' names (`ready-for-agent`, `needs-info`, `held`). A project may name its labels differently (`docs/agents/triage-labels.md`); in ClosedWiz they're the same.
8. **Who wrote a verdict** can't be told: every comment is by the owner's account. Spec 2 must not take a comment alone as an approval to merge (ADR 0008).
9. **Partial summaries.** A worked-out value requires every read its row reaches, whatever the case: one failed read behind one ticket makes its fleet's `progress` unread, a failed thread branch makes every builder and `unplaced` unread, and a partial blocker list makes the state unread even when a blocker read is known not merged. The tickets still show what is known. A later version may define what a partial read still settles.
10. **Changes.** A change to a field, a row or a rule is a new version, `openwiz.fleet.v2`, or a revision recorded here; a changed contract holds the tickets that rely on it (ADR 0006).

## Needs you source enrichment (0.0.10 T6)

Revision for #539: both views enrich each Needs you item with four required
facts: `wording`, `link`, `asked_at`, and `risk`. Each fact is exactly
`{"known": value}` or `{"unknown": nonempty_reason}`; unknown facts do not
become known absence or a safe risk. Existing `kind`, `spec`, `ticket` and
ordering stay the same.

**Where the question is read.** Only `openwiz fleet <spec>` reads comments: its
per-issue `gh issue view` read requests `comments` along with its existing
fields, and gh pages through all of an issue's comments there. `openwiz fleets`
keeps its repository-wide issue list unchanged and reads no comments: on the
owner's repository (828 issues, 2026-11-06) that list took 9 s and 2.7 MB
without comments and 46 s and 8 MB with them, against the 30 s run budget. In
`fleets`, the three question facts are unknown with the reason "the fleets view
does not read comments; openwiz fleet <spec> reads the question". A later
revision may add a per-ticket comment read of its own.

**The question.** Only the ticket's own comments supply a question. The first
line must start with exactly `needs-you` or `Needs you`, with that case. Select
the newest matching comment by its `createdAt`, independently of response
order; preserve the entire first line, including its marker, as `wording`, its
`url` as `link`, and its timestamp in integer Unix milliseconds as `asked_at`.
Other lines, the ticket body/title and unmarked comments never supply wording.
If there is no matching comment, or no unique newest match, all three facts are
unknown ("no unique newest needs-you or Needs you comment was found").
Creation/update times of tickets or sessions never supply the asked time.

**The risk.** A known `risk` is one of `live`, `release`, `publish`, from
exactly that label, in both views. The current item kinds `held` and
`needs_info` supply no risk classification. With no explicit risk label, or
conflicting risk labels, risk is unknown; an absent label never means safe.
Wording, titles, bodies and other label spellings cannot classify risk. Risk
and question availability are independent.

**Provenance.** In `fleet`, an `issue` read may additionally contain
`pending_question`, exactly `{wording, link, asked_at}` with the selected first
line, nonempty URL and integer timestamp, or omit it when no unique question
was established. `needs_you` derives its three question facts from that record
alone. Full comment bodies, authors and reactions are not included in the
envelope. The existing strict wire rules apply to the requested comment
objects, including refusing duplicate, missing and extra keys (`minimizedReason`
may be a string or null). A malformed issue read remains failed/unread, never
an empty Needs you list.

No additional GitHub or CloudRoom write or automatic approval is introduced.
Fixture tests prove synthetic behavior only; live source behavior remains
unverified.
