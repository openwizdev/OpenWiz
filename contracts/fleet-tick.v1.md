# OpenWiz fleet tick contract, version 1 (`openwiz.fleet-tick.v1`)

What the fleet tick decides. `openwiz fleet tick --dry-run --json` prints the actions due; the planner (`crates/core/src/fleet/tick/`) returns exactly these actions and the CLI (`crates/cli/src/fleet_tick.rs`) prints them. Nothing executes them: the executing tick and its `--expect-plan` restriction were retired in 0.0.17 (#800), and the agents running `launch-fleet` act. `openwiz fleet due --github-only` is a GitHub-only candidate check; it never reads CloudRoom or invents an agent identity, and the agent it wakes settles each candidate. The schema is [`fleet-tick.v1.schema.json`](fleet-tick.v1.schema.json); this file adds the rules file, what each action means, the rules a schema can't express, and an example. GitHub-first agent coordination is the separate [ops-dispatch v1](ops-dispatch.v1.md), not this envelope.

**Always true:**
- **Every action cites its rule and carries the facts that justify it.** The rule is one id from [the action table](#the-actions); the facts are what the action acts on and what its rule found, as read. What a rule needs to be absent (no record yet, no open pull request, no verdict, no hold) is in its "When", not in its facts.
- **Only these actions.** A case no rule covers gets no action, or a `look` for an agent.
- **Fail closed.** An action is planned only when every fact it needs was read in full and every condition of its rule holds. An unread or doubtful fact plans nothing but a `look`. If the rules file, the repository or the spec list can't be read, the tick plans nothing and prints no document (the exit status says why).
- **Authority is checked, never inferred.** A start or a merge needs the spec's current plan graph approval (fleet.v1's [Approval and authority](fleet.v1.md#approval-and-authority)), which the tick checks itself. A label, a `ready` state or an `approve` verdict alone never starts or merges anything.
- **Records come only from record authors.** A comment counts as a record or a verdict only when one of the rules file's record authors wrote it (#718); every other comment, and one with no author, is dropped before any record reader or the verdict is read.
- **The envelope is private.** Its thread ids are needed for dispatch and archiving and are never copied to GitHub. GitHub comments use the thread-free forms of [open development v1](open-development.v1.md#fleet-records).

## Threads

Thread resolution uses OpenWiz's private start records (`crates/core/src/fleet/starts.rs`), keyed by repository and ticket, or repository, pull request and original start commit. Public re-check records add commit aliases in memory, pointing to that span's original start. A give-up retires all aliases in the span, including records created after a claim later edited to a give-up; the retired identity is kept only for fresh-review and archive facts. Without a readable start, activity is a `look`. Records are ordered by creation time, with comment id as the tie-breaker; edit time updates activity, never lineage.

The fallback is the same repository project's exact builder title prefix or reviewer title that open development v1 specifies. Hidden and archived threads are included. Builders also match the checked branch, read through the workspace command; an unread branch is a `look`. Duplicate matches, or private state disagreeing with titles, are a `look`, never a selection. A public fallback due record consumes the same one restart as a legacy record; an unsettled public handover is a `look`, never a guessed replacement.

## The document

| Field | What |
| --- | --- |
| `schema` | Always `openwiz.fleet-tick.v1` |
| `mode` | `dry_run`: nothing is written, and every outcome is `planned`. The schema's `run` belonged to the retired executing tick; the CLI never prints it |
| `planned_at` | The clock the planner used, in milliseconds since 1970 |
| `default_branch` | The repository's default branch, as read: the only base the tick reviews or merges into |
| `rules` | [The rules file](#the-rules-file), as read |
| `actions` | Every action due, in [order](#order); `[]` when nothing is due |

Without `--json`, the tick prints only the judgment items, one line each; nothing when none is due.

Readers use strict hand-written readers, as for fleet.v1 ([Reading it](fleet.v1.md#reading-it)): exact keys each once, enums and tags only as one string from their list (never a tagged object such as `{"planned": null}`), no positional arrays, integers only as JSON integers, and `null` only where the schema has it. The rules below are part of the contract.

## The rules file

The tick reads the project's rules from **`docs/agents/fleet.md` on the default branch**. Only the parts below are machine-readable; every other line is for people. They are read exactly as written here, and **anything else is refused:** a section missing or twice, a table missing, a header or separator row that differs, a row out of form, a value twice. A refused rules file means the tick plans nothing.

A section is the lines from its heading line, exactly as written (`## Builder`), to the next line starting `## `. Its table is its one block of consecutive lines starting `|`. A row's cells are split on `|` and trimmed, and every row of a table read here has exactly three; the first row is the header, the second the separator, each of its cells exactly `---`. `<value>` below is a **setting**: lowercase letters, digits, `.`, `_` and `-`, starting with a letter or digit, at most 128 (a narrower form of new-thread.v1's `setting`, so a template's `<id>` is refused).

| Section | Header row | Rows read | Into |
| --- | --- | --- | --- |
| `## Builder` | `` \| Setting \| Value \| `room-cli thread spawn` flag \| `` | Exactly three, in this order: first cells `Harness`, `Model`, `Effort`; third cells exactly `` `--provider <value>` ``, `` `--model <value>` ``, `` `--reasoning-level <value>` `` | `rules.builder`: `harness`, `model`, `effort` |
| `## Builder for small tickets` | The same | The same | `rules.builder_small` |
| `## Reviewer for Claude-built` | The same | The same | `rules.reviewer_claude`; harness must be `codex` |
| `## Reviewer for GPT-built` | The same | The same | `rules.reviewer_gpt`; harness must be `claude-code` |
| `## CI checks` | `\| Check \| Runs \| Required on \|` | One or more. First cell exactly `` `<name>` `` (letters, digits, `.`, `_` and `-`, starting with a letter or digit); third cell one or more `` `<branch>` `` (letters, digits, `.`, `_`, `-` and `/`, starting with a letter or digit, and maybe a final `*`), separated by `, `, each once | `rules.ci_checks`: `{"name", "required_on"}` each, in the table's order |
| `## Standing merge rules` | `\| Pull request \| Review \| Merged by, and when \|` | The one row whose first cell starts `A ticket in an approved plan graph` and whose third cell starts `The loop, as soon as the reviewer's APPROVE names that exact commit` | `rules.merge`: `adr_0008` when that row is there; `none` when no row is (every merge waits for the user) |
| `## GitHub identity` | Not read | Exactly one row whose line starts `\|`, spaces, `Record authors`, spaces, `\|`, read as launch-fleet reads it: nothing after its value cell, and that whole cell one or more `` `<login>` `` (letters and digits, single `-` between them, maybe a final `[bot]`) separated by commas. No row, an empty cell, a malformed or extra entry, or two rows refuse the rules file | The record authors, compared case-insensitively |

The display values (the second cells of the agent tables), the `Runs` column, the other merge rows and every paragraph are not read. A `<branch>` in `Required on` may end in `*`, which matches any rest of a branch name (`release-*`); nothing else is a pattern.

- **Builder selection:** an exact `polish`, `huntr` or `proposal` label selects `builder_small`; every other ticket uses `builder`. Each `frontier` action carries its selected `settings`.
- **Reviewer selection:** `first_review` and `fresh_review` carry `settings` from `reviewer_claude` or `reviewer_gpt`, using the ticket's unique `launch-fleet: start checked, branch <branch>` record. Its branch must equal the pull request's head branch, and that exact thread's provider must be `claude-code` (Claude) or `codex` (GPT). Anything missing, malformed, conflicting, unread or unsupported is a `look`, never a reviewer start. Today's builder setting never establishes an earlier builder's family. Re-checks keep their reviewer thread.
- **Claude plan-limit fallback:** for an approved, open, unheld agent ticket, a verified, unarchived Claude builder stopped (`idle` or `error`) whose own complete output or error contains a recognized limit line is due `wake`/`restart`, once per ticket. The recognized lines are exactly `Claude usage limit reached`, `You've hit your limit`, or `You've hit your limit · resets <nonempty reset text>`, after trimming. The branch must match any open pull request. Its durable record, `launch-fleet: builder fallback due, branch <branch>`, consumes the fallback; a dry run never consumes it. The tick starts no replacement, and the rule never applies to reviewers. In the private form only, after a manual restart the orchestrator updates the original checked record to the replacement thread on the same branch and appends `Replacement: <id>` to the due comment; only this consistent handover retires the original builder, and conflicts are a `look`. A replacement keeps earlier code on the branch, so the builder family stays conflicting: `first_review` and `fresh_review` are `look: builder family unknown or conflicting`.
- **The required checks of a pull request** are the `ci_checks` whose `required_on` matches its base branch, in the table's order. **CI is green on a head** when its base has at least one required check, each required check is on it with result `pass`, and no check on it is `fail`, `cancel` or `pending`.
- **The merge rule** is ADR 0008's, in full, under [Merge](#merge). With `none`, the tick never merges.

## The review report

The tick reads two parts of a review report and nothing else of it:

- **The verdict:** the pull request's latest comment whose first line starts `VERDICT: `, read as fleet.v1 reads it: exactly `VERDICT: APPROVE at <commit>` or `VERDICT: CHANGES at <commit>`, with all 40 characters. A latest `VERDICT:` line in any other form is a `look`, never a verdict.
- **The findings,** on a `CHANGES` report: each line that starts `- **R<n> [<severity>]** `, the severity `high`, `medium` or `low`. Its status is `disputed, kept` when the rest starts `disputed, kept:`, and still open after `<k>` rounds when it starts `still open after <k> rounds:`. A finding line in neither form needs no diagnosis. The ids come from these lines, never from the `Next:` line.

## Actions

Every action is `{"kind", "rule", "spec", "ticket", "facts", "outcome"}`:

- **`kind`:** one of `start_builder`, `start_reviewer`, `send_findings`, `merge`, `close`, `hold`, `archive`, `log_refused_start`, `wake`, `needs_you`.
- **`rule`:** the rule it cites. Each rule belongs to one kind, and fixes the shape of `facts`.
- **`spec`:** the spec (fleet) the action is under. **`ticket`:** its ticket, or `null` for an action on the spec itself: always `null` for `all_closed`, `re_approve` and `spec_summary`, either for `look`, and never for the rest.
- **`facts`:** the facts that justify it, below.
- **`outcome`:** always `{"state": "planned"}`.

### The actions

| Kind | Rule | `ticket` | When | Means |
| --- | --- | --- | --- | --- |
| `start_builder` | `frontier` | the ticket | The ticket is on the frontier: approved (its row in the spec's current plan graph approval says `ready-for-agent`); ready (open, the `ready-for-agent` label, no other triage label); unblocked (every blocker a verified merge); not started (no start in OpenWiz's records but ones settled with no thread, no open pull request); not held (no `held` label, and no contract hold due) | Start its builder |
| `start_reviewer` | `first_review` | the ticket | Its open pull request's head is a hand-back (its subject has the word `green`), CI is green on it, it has no verdict, and no reviewer was ever started on the pull request | Start a reviewer |
| | `fresh_review` | the ticket | The same, but every reviewer started on it was given up on (`review given up <commit>: <why>`) | Start a new reviewer |
| | `re_check` | the ticket | The same, but a reviewer not given up on reviewed an earlier head | Ask that reviewer to re-check |
| `send_findings` | `review_findings` | the ticket | Its open pull request's head is a hand-back, CI is green on it, and the latest verdict is `CHANGES` on it | Tell the builder to fix or dispute |
| | `ci_failed` | the ticket | The head is a hand-back and a check on it failed or was cancelled | Tell the builder CI failed |
| | `contract_changed` | the ticket | A merge changed a file its `Relies on` line names, and it is being built | Tell the builder which files changed |
| `merge` | `adr_0008` | the ticket | Every condition of [the merge rule](#merge) holds | Merge that exact head, and read it back |
| `close` | `merged` | the ticket | Its pull request's merge is read back on the default branch, and the ticket is still open | Close the ticket |
| | `all_closed` | `null` | Every ticket of the spec is closed and archived (no `finished` due), its summary is written, and no follow-up is open | Close the spec |
| `hold` | `contract_hold` | the ticket | A merge changed a file its `Relies on` line names, and it has no builder yet (ADR 0006) | Hold it: the `held` label on, its ready label off |
| | `release` | the ticket | It still has the `held` label from the tick's own hold, and the user approved it again since | Take the `held` label off |
| `archive` | `finished` | the ticket | The ticket is closed and has a recorded builder or reviewer, and either an agent is not archived or the final `launch-fleet: archived` record is missing; already-archived agents count as done | Archive those agents |
| `log_refused_start` | `builder_refused` | the ticket | A builder start was refused, or failed with no thread made, and isn't logged yet | Log it on the ticket; the ticket stays on the frontier |
| | `reviewer_refused` | the ticket | The same for a reviewer start | Log it on the pull request; the review waits |
| `wake` | `restart` | the ticket | A verified Claude builder reports its plan limit, and no fallback due record exists (above) | Record and print one restart due item, keeping its branch |
| | `needs_info` | the ticket | It has the `needs-info` label and a question newer than the last time it was passed on | An agent passes the question to the orchestrator |
| | `disputed` | the ticket | The latest verdict is `CHANGES` on the head, the report keeps a disputed finding (`disputed, kept`), and no `dispute asked <commit>` is there yet | An agent asks the orchestrator for its diagnosis |
| | `diagnosis` | the ticket | The latest verdict is `CHANGES` on the head, a finding is still open after 2 or more rounds (the review and its re-check of the [1 + 1 rule](review-loops.v2.md)), and no `diagnosis asked <commit>` is there yet | An agent asks the orchestrator to decide it |
| | `look` | the ticket, or `null` | Something can't be read in full, there are two of something, a start's outcome can't be settled, a reviewer is quiet (no verdict 30 minutes after its start or re-check), or a merge whose conditions held was blocked. One `look` per ticket (or spec) and tick, its reason naming every item | An agent looks, and records what it did in `launch-fleet`'s forms (`review told again <commit>`, or `review given up <commit>: <why>`), which later ticks read |
| `needs_you` | `held` | the ticket | The tick's `held for #<merged>` record is on the ticket, and no `needs you sent: held for #<merged>` yet | Ask the user to re-approve it |
| | `re_approve` | `null` | A ticket of the spec could start, but its plan changed since the latest approval | Ask the user to approve the plan as it now stands |
| | `person_ready` | the ticket | A `ready-for-human` ticket is approved, unblocked and not held | Tell the user it's theirs to do |
| | `spec_summary` | `null` | Every approved ticket of the spec is closed, and no summary is written yet | Write the closing summary |

**Spec completion is narrower than launch-fleet's.** `all_closed` waits for every sub-issue to close, its agents to be archived, the summary to be recorded and no open follow-up. `spec_summary` requires closed approved tickets, not verified planned merges, and lists the `follow_ups` input plus every open unapproved sub-issue as follow-ups. Neither reads live-check evidence or labels follow-ups `polish`, so the orchestrator checks the live-check evidence and classifies follow-ups before acting on either; neither waives launch-fleet's completion gates.

### Facts

The shared shapes:

| Name | Shape | What |
| --- | --- | --- |
| approval | `{"comment", "revision", "fingerprint"}` | The spec's latest plan graph approval (`plan-graph`'s `**Plan graph approved by` comment): its comment id, revision number and `Fingerprint:`. In `frontier`, `adr_0008`, `release` and `person_ready` it is **current**: the fingerprint is the SHA-256 of what `revision.sh <spec>` prints now |
| pr | `{"number", "head_commit", "base_branch"}` | The ticket's open pull request (fleet.v1's `pr_discovery`: the one open pull request that closes it), not a draft, at its head |
| merge | `{"number", "merge_commit"}` | A merged pull request and its merge commit, read back on the default branch |
| blocker | `{"number", "pr", "merge_commit"}` | A blocking issue with a verified merge: closed, and its pull request's merge commit read back on the default branch |
| check | `{"name", "result"}` | A check on the head: its latest run (fleet.v1's `checks` read); `result` is `pass`, `fail`, `pending`, `skipping` or `cancel` |
| verdict | `{"verdict", "commit", "comment"}` | The pull request's latest `VERDICT:` comment: `approve` or `changes`, the commit it names, and its comment id |

Ids: a **comment** is GitHub's comment id (an integer); a **thread** is a CloudRoom thread id; a **start** is the op id of OpenWiz's own start record (new-thread.v1's `op_id`); a **commit** is 40 lowercase hex digits, a **fingerprint** 64; a **finding** is a report's id, `R` and a number.

Each rule's `facts`, every key required:

| Rule | `facts` |
| --- | --- |
| `frontier` | `settings` (selected builder), `title` (the ticket's), `approval`, `labels` (the ticket's, as read), `blockers` (every one, ascending; `[]` for none), `retry_after` (`null`, or the ticket's last start, settled with no thread: `{"start", "state": "refused" or "failed"}`) |
| `first_review` | `settings` (reviewer selected from builder family), `pr`, `subject` (the head commit's subject), `checks` (every check on the head) |
| `fresh_review` | `settings`, `pr`, `subject`, `checks`, `given_up` (the reviewer threads given up on, in the order they were started; at least one) |
| `re_check` | `pr`, `subject`, `checks`, `reviewer` (the thread to ask), `last_verdict` (its latest verdict, on an earlier commit, or `null`) |
| `review_findings` | `pr`, `checks`, `verdict` (`changes` on the head), `builder` (its thread) |
| `ci_failed` | `pr`, `subject`, `checks`, `builder` |
| `contract_changed` | `merged` (the merge that changed them), `files` (the changed files it relies on, ascending), `relies_on` (its `Relies on` line's paths, as written), `builder` |
| `adr_0008` | `approval`, `pr`, `base_commit` (the base CI ran against: the base branch's head now), `verdict` (`approve` on the head), `reviewer` (the thread whose own output shows that verdict line), `checks` |
| `merged` | `merged` (its pull request's merge) |
| `all_closed` | `tickets` (every ticket of the spec, ascending, all closed) |
| `contract_hold` | `merged`, `files`, `relies_on`, `ready_label` (`ready-for-agent`, or `ready-for-human` for a person's ticket) |
| `release` | `hold` (the comment of the tick's `held for` record), `approval` (current, newer than the hold) |
| `finished` | `threads` (each `{"thread", "role": "builder" or "reviewer"}`, builder first, then reviewers in the order they were started; at least one) |
| `builder_refused` | `start`, `state` (`refused` or `failed`), `reason` (OpenWiz's own words) |
| `reviewer_refused` | `pr`, `start`, `state`, `reason` |
| `needs_info` | `question` (the comment id of the ticket's latest comment that isn't a record) |
| `disputed` | `pr`, `verdict` (`changes` on the head), `findings` (the ids `disputed, kept`, ascending; at least one) |
| `diagnosis` | `pr`, `verdict` (`changes` on the head), `findings` (each `{"id", "rounds"}`, ascending by id, `rounds` 2 or more; at least one) |
| `restart` | `builder` (the stopped thread), `branch` (the same branch), `settings` (small-ticket builder) |
| `look` | `reason` (OpenWiz's own words: what can't be read or settled) |
| `held` | `hold` (the comment of the tick's `held for` record), `merged`, `files` (as that record names them) |
| `re_approve` | `approval` (the latest, now stale), `fingerprint_now` (the SHA-256 of what `revision.sh <spec>` prints now) |
| `person_ready` | `title`, `approval`, `blockers` |
| `spec_summary` | `merged` (each merged ticket's `{"ticket", "pr"}`, ascending by ticket), `follow_ups` (for the user to approve or drop: the spec's open sub-issues outside its plan, and the open issues whose body starts `Follow-up of #<ticket> (spec #<spec>)`, ascending) |

### Merge

ADR 0008 in full: a ticket's pull request is due to merge **only when every one of these holds**. Any one missing, or unread, means no merge.

1. **The rules file's merge rule is `adr_0008`.**
2. **Approval:** the ticket is in the spec's latest plan graph approval, and that approval is current (`facts.approval`).
3. **APPROVE on the head:** the pull request's latest verdict is `approve` and names its head commit (`facts.verdict.commit` is `facts.pr.head_commit`), and the reviewer's own thread shows that same line (`facts.reviewer`).
4. **CI green on the head:** as the rules file defines it (`facts.checks`).
5. **The base is unchanged:** the base CI ran against is the base branch's head now (`facts.base_commit`).
6. **Not a release line:** the base branch is the default branch, and no `release-*` branch. Release lines, publishing and anything live stay the user's.

### Order

Actions are listed by `spec` ascending; within a spec, its spec-level actions (`ticket` `null`) last, the rest by `ticket` ascending; within a ticket (or the spec), by kind in the action table's order; within a kind, by rule in its order. A document has at most one action per kind and rule for each ticket, and at most one `start_builder` per ticket: **never two builders**. A ticket's `review_findings`, `disputed` and `diagnosis` in one document have the same `pr` and the same `verdict`. A `contract_hold` and its `held` are never in one document. A dry run performs no recovery: an unresolved pending start stays a `look`.

## Where each fact comes from

| Facts | From |
| --- | --- |
| `title`, `labels`, a ticket's `Relies on` paths, `blockers`, a `pr`'s number, head and base, `checks`, a `verdict`'s verdict and commit, a `merge` and its read back | fleet.v1's reads (`issue`, `blocked_by`, `pr_discovery`, `checks`, `comments`, `merge_readback`) |
| `default_branch`, `subject`, `base_commit`, a verdict's `comment`, the approval, `fingerprint_now`, the `launch-fleet:` records, `files`, `question`, `findings`, `follow_ups` | GitHub reads fleet.v1 doesn't make: the spec's comments, `revision.sh`, the head commit, the base branch's head, comments and records, the files a merge changed, review reports |
| `rules` | `docs/agents/fleet.md`, as [above](#the-rules-file) |
| `start`, `retry_after`, `builder`, `reviewer`, `given_up`, `threads` | OpenWiz's start records and the `launch-fleet:` records; `reviewer` in `adr_0008` also its thread's own output (`room-cli thread output`) |
| `reason`, `planned_at`, `outcome` | OpenWiz's own |

## Rules the schema can't express

The planner produces only documents that keep them; a reader that checks only the schema must not rely on them.

| Id | Rule |
| --- | --- |
| `mode` | In a `dry_run` every outcome is `planned` |
| `head` | A `verdict` in `adr_0008`, `review_findings`, `disputed` and `diagnosis` names its `pr`'s `head_commit`; a `re_check`'s `last_verdict` names another commit |
| `base` | Every `pr` has the document's `default_branch` as its base, and the default branch is no release line (it doesn't start `release-`) |
| `checks` | No check name twice. In `first_review`, `fresh_review`, `re_check`, `review_findings` and `adr_0008`, CI is green on the head; in `ci_failed`, at least one check is `fail` or `cancel` |
| `merge_rule` | A `merge` only when `rules.merge` is `adr_0008` |
| `green` | A `subject` has the word `green` (any case, a whole word) |
| `labels` | A `frontier` ticket's labels have `ready-for-agent`, and none of `needs-info`, `needs-triage`, `ready-for-human`, `wontfix` or `held` |
| `newer` | A `release`'s approval is newer than its hold (a higher comment id) |
| `relies_on` | Every one of `files` matches a path of `relies_on` (a path ending `/` matches everything under it; `*` matches within one folder) |
| `rules` | `rules.ci_checks` names each check once, each with its `required_on` branches once, and a `*` only as a branch's last character |
| `order` | Every list the facts table calls ascending is ascending, each item once (finding ids by their number); `labels`, `given_up` and `threads` name each item once, and `threads` has at most one builder, first; `fingerprint_now` differs from the approval's |
| `nonempty` | `given_up`, `threads`, the `findings` of a `disputed` or `diagnosis`, the `tickets` of an `all_closed`, `rules.ci_checks` and each check's `required_on` have at least one item |
| `actions` | The document's actions are in [order](#order), at most one per kind and rule for each ticket (or spec); a spec with an `all_closed` has no other action; a ticket with a `contract_hold` has no `start_builder`, and no `held` for the same merge; a ticket's `review_findings`, `disputed` and `diagnosis` have the same `pr` and `verdict` |
| `one_approval` | Within one spec, every current `approval` is the same one (the spec's latest). A spec with a `re_approve` has no `frontier`, `adr_0008`, `release` or `person_ready`: a stale plan starts and merges nothing |

The approval being current, `base_commit` being the base's head now, `reviewer`'s own output, the facts being as read, and every condition of each rule's "When" are established by the planner from its reads; no document can show them.

## Examples

Synthetic values only.

1. **A dry run with one action of every rule:** spec 960's tickets 961 to 978 (#970 held now, #978 held in an earlier tick, its notification due); spec 985, whose plan changed since its approval; spec 990, every ticket closed; spec 995, closed and archived, its summary written.

```json
{
  "schema": "openwiz.fleet-tick.v1",
  "mode": "dry_run",
  "planned_at": 1793400000000,
  "default_branch": "main",
  "rules": {
    "builder": {"harness": "claude-code", "model": "claude-opus-5-5", "effort": "xhigh"},
    "builder_small": {"harness": "codex", "model": "gpt-6.1-sol", "effort": "high"},
    "reviewer_claude": {"harness": "codex", "model": "gpt-6.1-sol", "effort": "high"},
    "reviewer_gpt": {"harness": "claude-code", "model": "claude-opus-5-5", "effort": "high"},
    "ci_checks": [
      {"name": "web-build", "required_on": ["main", "release-*"]},
      {"name": "rust", "required_on": ["main", "release-*"]},
      {"name": "web-test", "required_on": ["main", "release-*"]}
    ],
    "merge": "adr_0008"
  },
  "actions": [
    {
      "kind": "start_builder", "rule": "frontier", "spec": 960, "ticket": 961,
      "facts": {
        "settings": {"harness": "claude-code", "model": "claude-opus-5-5", "effort": "xhigh"},
        "title": "Synthetic ticket B1",
        "approval": {"comment": 5990, "revision": 3, "fingerprint": "bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000"},
        "labels": ["ready-for-agent"],
        "blockers": [{"number": 950, "pr": 1950, "merge_commit": "9500000000000000000000000000000000000000"}],
        "retry_after": {"start": "syn-start-961-1", "state": "refused"}
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "start_reviewer", "rule": "first_review", "spec": 960, "ticket": 962,
      "facts": {
        "settings": {"harness": "codex", "model": "gpt-6.1-sol", "effort": "high"},
        "pr": {"number": 1962, "head_commit": "9620000000000000000000000000000000000000", "base_branch": "main"},
        "subject": "Synthetic B2: green",
        "checks": [{"name": "web-build", "result": "pass"}, {"name": "rust", "result": "pass"}, {"name": "web-test", "result": "pass"}]
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "start_reviewer", "rule": "fresh_review", "spec": 960, "ticket": 963,
      "facts": {
        "settings": {"harness": "codex", "model": "gpt-6.1-sol", "effort": "high"},
        "pr": {"number": 1963, "head_commit": "9630000000000000000000000000000000000000", "base_branch": "main"},
        "subject": "Synthetic B3: green",
        "checks": [{"name": "web-build", "result": "pass"}, {"name": "rust", "result": "pass"}, {"name": "web-test", "result": "pass"}],
        "given_up": ["syn-thread-r963-1"]
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "start_reviewer", "rule": "re_check", "spec": 960, "ticket": 964,
      "facts": {
        "pr": {"number": 1964, "head_commit": "9640000000000000000000000000000000000002", "base_branch": "main"},
        "subject": "Synthetic B4: R1 fixed, green",
        "checks": [{"name": "web-build", "result": "pass"}, {"name": "rust", "result": "pass"}, {"name": "web-test", "result": "pass"}],
        "reviewer": "syn-thread-r964",
        "last_verdict": {"verdict": "changes", "commit": "9640000000000000000000000000000000000001", "comment": 5964}
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "send_findings", "rule": "review_findings", "spec": 960, "ticket": 965,
      "facts": {
        "pr": {"number": 1965, "head_commit": "9650000000000000000000000000000000000000", "base_branch": "main"},
        "checks": [{"name": "web-build", "result": "pass"}, {"name": "rust", "result": "pass"}, {"name": "web-test", "result": "pass"}],
        "verdict": {"verdict": "changes", "commit": "9650000000000000000000000000000000000000", "comment": 5965},
        "builder": "syn-thread-b965"
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "wake", "rule": "disputed", "spec": 960, "ticket": 965,
      "facts": {
        "pr": {"number": 1965, "head_commit": "9650000000000000000000000000000000000000", "base_branch": "main"},
        "verdict": {"verdict": "changes", "commit": "9650000000000000000000000000000000000000", "comment": 5965},
        "findings": ["R2"]
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "wake", "rule": "diagnosis", "spec": 960, "ticket": 965,
      "facts": {
        "pr": {"number": 1965, "head_commit": "9650000000000000000000000000000000000000", "base_branch": "main"},
        "verdict": {"verdict": "changes", "commit": "9650000000000000000000000000000000000000", "comment": 5965},
        "findings": [{"id": "R1", "rounds": 2}]
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "send_findings", "rule": "ci_failed", "spec": 960, "ticket": 966,
      "facts": {
        "pr": {"number": 1966, "head_commit": "9660000000000000000000000000000000000000", "base_branch": "main"},
        "subject": "Synthetic B6: green",
        "checks": [{"name": "web-build", "result": "pass"}, {"name": "rust", "result": "fail"}, {"name": "web-test", "result": "pass"}],
        "builder": "syn-thread-b966"
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "send_findings", "rule": "contract_changed", "spec": 960, "ticket": 967,
      "facts": {
        "merged": {"number": 1950, "merge_commit": "9500000000000000000000000000000000000000"},
        "files": ["contracts/example.v1.md"],
        "relies_on": ["contracts/example.v1.*"],
        "builder": "syn-thread-b967"
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "merge", "rule": "adr_0008", "spec": 960, "ticket": 968,
      "facts": {
        "approval": {"comment": 5990, "revision": 3, "fingerprint": "bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000"},
        "pr": {"number": 1968, "head_commit": "9680000000000000000000000000000000000000", "base_branch": "main"},
        "base_commit": "5000000000000000000000000000000000000000",
        "verdict": {"verdict": "approve", "commit": "9680000000000000000000000000000000000000", "comment": 5968},
        "reviewer": "syn-thread-r968",
        "checks": [{"name": "web-build", "result": "pass"}, {"name": "rust", "result": "pass"}, {"name": "web-test", "result": "pass"}]
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "close", "rule": "merged", "spec": 960, "ticket": 969,
      "facts": {"merged": {"number": 1969, "merge_commit": "9690000000000000000000000000000000000000"}},
      "outcome": {"state": "planned"}
    },
    {
      "kind": "hold", "rule": "contract_hold", "spec": 960, "ticket": 970,
      "facts": {
        "merged": {"number": 1950, "merge_commit": "9500000000000000000000000000000000000000"},
        "files": ["contracts/example.v1.md"],
        "relies_on": ["contracts/example.v1.*", "docs/agents/fleet.md"],
        "ready_label": "ready-for-agent"
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "hold", "rule": "release", "spec": 960, "ticket": 971,
      "facts": {
        "hold": 5971,
        "approval": {"comment": 5990, "revision": 3, "fingerprint": "bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000"}
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "archive", "rule": "finished", "spec": 960, "ticket": 972,
      "facts": {"threads": [{"thread": "syn-thread-b972", "role": "builder"}, {"thread": "syn-thread-r972", "role": "reviewer"}]},
      "outcome": {"state": "planned"}
    },
    {
      "kind": "log_refused_start", "rule": "builder_refused", "spec": 960, "ticket": 973,
      "facts": {"start": "syn-start-973-1", "state": "refused", "reason": "CloudRoom refused the model"},
      "outcome": {"state": "planned"}
    },
    {
      "kind": "log_refused_start", "rule": "reviewer_refused", "spec": 960, "ticket": 974,
      "facts": {
        "pr": {"number": 1974, "head_commit": "9740000000000000000000000000000000000000", "base_branch": "main"},
        "start": "syn-start-r974-1",
        "state": "failed",
        "reason": "the start was interrupted before it was sent"
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "wake", "rule": "needs_info", "spec": 960, "ticket": 975,
      "facts": {"question": 5975},
      "outcome": {"state": "planned"}
    },
    {
      "kind": "wake", "rule": "look", "spec": 960, "ticket": 976,
      "facts": {"reason": "more than one open pull request closes it"},
      "outcome": {"state": "planned"}
    },
    {
      "kind": "needs_you", "rule": "person_ready", "spec": 960, "ticket": 977,
      "facts": {
        "title": "Synthetic live check",
        "approval": {"comment": 5990, "revision": 3, "fingerprint": "bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000bbbb0000"},
        "blockers": [{"number": 950, "pr": 1950, "merge_commit": "9500000000000000000000000000000000000000"}]
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "needs_you", "rule": "held", "spec": 960, "ticket": 978,
      "facts": {
        "hold": 5978,
        "merged": {"number": 1950, "merge_commit": "9500000000000000000000000000000000000000"},
        "files": ["contracts/example.v1.md"]
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "needs_you", "rule": "re_approve", "spec": 985, "ticket": null,
      "facts": {
        "approval": {"comment": 5101, "revision": 1, "fingerprint": "dddd0000dddd0000dddd0000dddd0000dddd0000dddd0000dddd0000dddd0000"},
        "fingerprint_now": "eeee0000eeee0000eeee0000eeee0000eeee0000eeee0000eeee0000eeee0000"
      },
      "outcome": {"state": "planned"}
    },
    {
      "kind": "needs_you", "rule": "spec_summary", "spec": 990, "ticket": null,
      "facts": {"merged": [{"ticket": 991, "pr": 1991}, {"ticket": 992, "pr": 1992}], "follow_ups": [993]},
      "outcome": {"state": "planned"}
    },
    {
      "kind": "close", "rule": "all_closed", "spec": 995, "ticket": null,
      "facts": {"tickets": [996, 997]},
      "outcome": {"state": "planned"}
    }
  ]
}
```

## Not in version 1

Open, for later tickets or the user; none is guessed in the meantime:

1. **Whether a started builder is at work:** a start record says a thread started, not that it is working.
2. **Quiet reviewers** are a `look` for an agent: telling a reviewer again needs its thread's output read and judged.
3. **Issues approved on their own** are not fleets in fleet.v1, so the tick plans nothing for them.
4. **Label names** are the triage roles' names (`ready-for-agent`, `needs-info`, `held`, …); `docs/agents/triage-labels.md` is not read.
5. **The user deciding a finding** after its diagnosis is the orchestrator's call, woken by `diagnosis`; the tick doesn't tell rounds after a diagnosis apart.
6. **Other merge rules.** Only ADR 0008's row is read; docs-only and grill merges stay the orchestrator's, and `release-*` the user's.
7. **Changes.** A change to a field, a rule or a reading rule is a new version, `openwiz.fleet-tick.v2`, or a revision recorded here; a changed contract holds the tickets that rely on it (ADR 0006).
