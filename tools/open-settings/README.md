# OpenWiz settings

Python 3.11+ and authenticated `gh` are the only runtime tools. Keep the sibling
`tools/privacy-check/` command in this checkout; no packages to install. Run from
any directory; every API path names its repository explicitly.

```sh
# O16's dry-read seam (no network writes or local state files):
python3 -I tools/open-settings/settings.py

# Until O20 transfers the repository, select its current address explicitly:
python3 -I tools/open-settings/settings.py --repo jparker2006/OpenWiz

# Save the dry read's plan for review (a new file; prints plan_digest):
python3 -I tools/open-settings/settings.py --plan-out <plan.json>

# O20's apply/read-back seam, only with separate live approval, bound to the
# reviewed plan and its digest, journalled to a new file:
python3 -I tools/open-settings/settings.py --apply --plan <plan.json> --digest <digest> --journal <journal.jsonl>

# The way back: undo exactly the journalled writes of that apply:
python3 -I tools/open-settings/settings.py --recover --plan <plan.json> --digest <digest> --journal <journal.jsonl>

# Synthetic command proofs, no network:
python3 -I tools/open-settings/test_settings.py
```

The single destination setting is `--repo`, default `openwizdev/openwiz`. Only
that address and its documented predecessor are accepted; the old address may
redirect to the final address. A validated redirect is resolved before ruleset
ownership checks, proposed requests and read-backs. The destination must be public with default
branch `main`. ClosedWiz is always a read-only source of labels and milestones.
A personal-account destination is readable but blocks apply: GitHub's merge
queue requires O20's organization transfer first.

Default mode prints JSON with `differences`, the proposed `plan` (including each
new value), `blockers`, and no applied changes. Exit 0 means the read completed
without blockers; differences may remain. Exit 1 means a failed request, invalid
read, blocker or failed read-back; 2 is usage error. Read failures go to stderr
and never become an empty list. Duplicate JSON keys, ambiguous managed rulesets,
missing bypass visibility, incomplete counted pagination, unexpected identity,
and unknown policy values refuse. Variable values and runner identities are
never printed. Output redirection is the caller's choice; keep real settings
reports in private evidence, outside the future public tool folder.

The complete proposed label and milestone text is checked by the shared privacy
command before any report or write. It reads the proposal from stdin; default
mode creates no temporary files. A missing checker, failed input or text refusal
stops before any mutation, including ruleset changes. `--literals PATH` adds the
private named-literals list and requires it to be readable and nonempty. Without
that option, only the checker's standard text rules run; `privacy_literals` in
the report states whether the list was supplied. Unquoted personal facts still
need the source metadata's private/public review, as the contract specifies.

## Reviewed plan, journal and recovery (#2408)

`--plan-out PATH` runs the ordinary dry read and also saves its plan file:
every planned write (setting, method, path, identity, new value, `created` or
`updated`) with the complete prior object it changes (`null` for a creation),
the resolved repository, and a SHA-256 `digest` of the whole plan, which the
report prints as `plan_digest`. The file is created owner-only and never
overwritten. Without `--plan-out` the dry read writes no file and its report is
unchanged.

`--apply` needs `--plan`, `--digest` and a new `--journal` path, and never
re-plans on its own. Before any write it refuses a truncated, malformed or
changed plan, a digest that differs from the one given, a plan for another
repository, an existing journal file, any blocker, and drift: it reads every
object again and recomputes the plan, which must equal the reviewed one
exactly, prior values included. Then, for each write in order, it syncs an
`intent` record to the journal, writes, reads the object back and syncs a
`completion` record (method, path, identity, prior value, new value, result).
A failed write, failed read-back or mismatch is recorded `unknown`, never
`done`, and stops. A complete run ends with an `end` record. Each record is one
JSON line synced to disk before the next step, so a crash leaves at most one
write whose outcome the journal does not hold, and its intent is already on
disk. The journal holds only plan values and read-back settings: no token,
variable value or runner identity. Every text value a plan file or journal
would keep (new values, complete prior objects and read-back objects) passes
the same privacy check and `--literals` list first; a refusal saves no plan,
and a refused read-back is recorded `unknown` without its value. Prior label
and milestone values are kept raw (a null description stays null), so
recovery restores them exactly; only the plan's comparison treats a null
description as empty text. Recovery ignores an unterminated last record, even
one cut inside a character; a complete record that is not UTF-8 refuses.

`--recover` takes the same plan, digest and the journal. It refuses a journal
that does not match the plan record by record (start record, order, every
field). Newest first, it re-reads each intended object, which also resolves
`unknown` records; it restores each updated object to its prior value,
deletes only objects the journal's plan shows as created and that exist (a
created ruleset or milestone replaced under another id is refused, not
deleted), and reads every intended object back equal to the plan's prior state.
Objects the apply never reached are not touched. A second recovery makes no
writes. Recovery keeps no journal of its own: it is safe to rerun, because it
decides every step from a fresh read. It reports `restored`, `removed`,
`unchanged` and how each unknown write resolved. It assumes nobody else
changed the same settings since the apply; a changed object that it would
restore is still restored to the plan's prior value.

## Apply guards

`--apply` performs all reads and validates the complete plan before its first
write. Registered self-hosted runners (offline included) or any effective
`CI_RUNS_ON`, `CI_RUST_RUNS_ON` or `CI_WEB_RUNS_ON` variable at repository or shared
organization scope block apply. They are reported, never removed automatically.
All target and source lists are paginated, including closed milestones. Every
write is followed by a fresh read that must match its proposed value; a complete
final read must show no remaining drift. A new plan read after it holds no
writes.
Requests have a 45-second timeout and are never retried. Apply is not a
transaction: if a write or read-back fails, earlier verified changes remain
until `--recover` undoes them from the journal.

The tool owns two named repository rulesets:

- **CI must pass**: active, branch patterns `refs/heads/main` and
  `refs/heads/release-*`, no exclusions or bypass actors; deletion and force
  pushes refused; required checks `web-build`, `rust`, `web-test` and `privacy`.
  Status checks require an up-to-date base and also apply to branch creation.
- **Merge queue**: active, only `refs/heads/main`, no bypass. Merge method
  `MERGE`, grouping `ALLGREEN`, build concurrency 5, one entry per merge, minimum
  one entry with no batching wait. Status timeout is 75 minutes, per current
  fleet guidance (above the ticket's 45-minute floor); longer existing timeouts
  survive reconciliation. The queue uses the checks required by CI must pass.

Named rulesets are reconciled in full. Other rulesets are left alone. A managed
name inherited from an organization/enterprise, or repeated under two ids,
refuses rather than guessing which one to change. Rule and check ordering does
not cause drift. Existing positive-integer GitHub App `integration_id` bindings
for the four required contexts are preserved, including while correcting other
drift. Omitted/null bindings remain unbound. Malformed IDs, missing contexts or
repeated contexts refuse before any write; reconciliation never silently drops
a required context's source restriction. Fork workflow approval is
`all_external_contributors`.

Labels match source names (case-insensitive identity), colors and descriptions;
milestones match source titles, descriptions, state and due dates. Source
milestone numbers are never used as target numbers. A missing entry is created;
an existing entry is updated, with null descriptions normalized to empty text
and null due dates clearing the old date. Target-only labels/milestones appear
separately in the report and are preserved, so no issue loses an assignment.
There is no deletion operation.

One reviewed public edit applies before comparison: milestone `0.0.X` uses an
authored description of its polish scope, decision date and private-record
pointer, instead of its private source quotation (O1's classification, #1923).
Its title, state and due date still follow the source. This description is a
deliberate public value; future wording changes require editing that value.
All other descriptions follow the source unchanged. The complete resulting
proposal still passes the same privacy check; an unsafe value or failed check
still refuses the report and every write. No generic quote stripping is used.

This proves settings, not the runners selected by workflow contents. A workflow
can still name an unsafe runner even with no variables or registrations; the
privacy checker and O18's live observations cover that separate contract.
No live apply, recovery or queue merge is proven by these fixture tests.

API sources: [rulesets](https://docs.github.com/en/rest/repos/rules),
[fork approval](https://docs.github.com/en/rest/actions/permissions#set-fork-pr-contributor-approval-permissions-for-a-repository),
[runners](https://docs.github.com/en/rest/actions/self-hosted-runners#list-self-hosted-runners-for-a-repository),
[variables](https://docs.github.com/en/rest/actions/variables),
[labels](https://docs.github.com/en/rest/issues/labels),
[milestones](https://docs.github.com/en/rest/issues/milestones), and
[gh pagination](https://cli.github.com/manual/gh_api).
