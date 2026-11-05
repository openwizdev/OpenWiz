# OpenWiz fleet tick contract, version 1 (`openwiz.fleet-tick.v1`)

**OB1 / OB-A1 (#2187):** the separate
[ops record/claim contract](ops-dispatch.v1.md) is GitHub-first agent coordination,
with atomic create-if-absent claims per generation and operation. It is not this
private mechanical tick envelope and adds no wire field or Rust implementation.
Mechanical due detection supplies candidates; an agent must independently check
current authority/evidence. A ref claim does not fence a later external call.
All new ops start/delivery/recheck/hold-release/merge effects remain disabled
where their actual boundary is unavailable or unfenced; record/refusal
certification does not enable them or change existing tick behavior. P5 stays
Unverified; #2244 owns separate unstarted Local discovery. Every existing live,
review/CI/base/merge, activation, spending and publication gate remains.

What the fleet tick decides and does (OpenWiz 0.0.6, spec #116). `openwiz fleet tick --dry-run --json` prints the actions it would take; `openwiz fleet tick --json` reports attempted pending-start recoveries, then the actions planned from refreshed inputs, with what happened to each. The planner (B2, #118) returns exactly these actions; the executors (B3 #119, B4 #120) carry them out; the CLI (B5, #121) prints them. The schema is [`fleet-tick.v1.schema.json`](fleet-tick.v1.schema.json); this file adds the rules file, what each action means, does and records, the rules a schema can't express, and examples.

**Public records (O4, #1272):** GitHub comments follow the thread-free forms in
[open development v1](open-development.v1.md#fleet-records), including its
reviewer spans and ambiguity rule. Writers use those forms on both repositories.
Only the contract's private repository accepts legacy thread-carrying comments
and quoted approvals; any other or unknown repository requires public forms.
Public plan approvals keep the same revision text, fingerprint and table, with
a plain decision and the required private-comment pointer on the second line.
The local JSON action envelope is private execution data: its thread facts are
needed for dispatch and archiving and must never be copied to GitHub. Its schema
and dispatch facts are unchanged by this revision.

Thread resolution uses B4's private start records keyed by repository and ticket,
or repository, PR and original start commit. Public re-check records add commit
aliases in memory, pointing to that span's original start. A give-up retires all
aliases in the span, including records created after a claim later edited to a
give-up. The retired identity is kept only for fresh-review and archive facts;
its output is not read and no message is sent to it. Without a readable start,
activity is a `look`. Records are ordered by creation time, with comment id as
the tie-breaker; edit time updates activity, never lineage.

The fallback is the same repository project's exact builder title prefix or
reviewer title specified by open development v1. Hidden and archived threads are
included. Builders also match the checked branch, read through the existing
workspace command; an unread branch is a `look`. Duplicate matches or private
state disagreeing with titles are a `look`, never a selection. The Rust start
path continues to send **no title**: its own threads are resolved by B4 state,
while titled threads from the skill path can be found without that state.
A public fallback due record consumes the same one restart as a legacy record.
The existing manual replacement form is accepted only privately; an unsettled
public handover yields `look`, never a guessed replacement.

GitHub-only `fleet due` cannot resolve a thread-free identity without CloudRoom
or private starts. It emits a conservative candidate for `fleet tick` to settle;
it never invents an agent identity or performs a CloudRoom read.

**Revision #1196:** conditional builder/reviewer tables, selected start settings and one-time restart due items. The CLI prints this contract. Fixture proofs are in `tests/fleet/`.

**Always true:**
- **Every action cites its rule and carries the facts that justify it.** The rule is one id from [the action table](#the-actions); the facts are what the action acts on and what its rule found, as read. What a rule needs to be absent (no record yet, no open pull request, no verdict, no hold) is in its "When", not in its facts. Nothing in a tick is decided without a rule.
- **Only these actions, only these writes.** Each action's writes are listed below and nothing else: no branch deleted, nothing forced, no comment edited, nothing released or published (grill Q5, Q6; spec #116). A case no rule covers gets no action, or a `look` for an agent.
- **Fail closed.** An action is planned only when every fact it needs was read in full and every condition of its rule holds. An unread or doubtful fact plans nothing but a `look` (below): never a guess. If the rules file, the repository or the spec list can't be read, the tick plans nothing and prints no document (B5's exit status says why).
- **Authority is checked, never inferred.** A start or a merge needs the spec's current plan graph approval (fleet.v1's [Approval and authority](fleet.v1.md#approval-and-authority)), which the tick checks itself. A label, a `ready` state or an `approve` verdict alone never starts or merges anything.
- **No private data:** the facts are numbers, commits, labels, file paths, check names and results, thread ids and OpenWiz's own reasons. No comment, issue or thread content, and no account names.

## The document

### Reviewed-plan execution (revision #1892)

`openwiz fleet tick --expect-plan PATH [--json]` opts into a pre-effect
restriction. Save and review the complete `fleet tick --dry-run --json` document,
then pass that file. This adds no schema or action kind. Without this option,
the existing recovery and execution behavior is unchanged.

The file must be one strict `openwiz.fleet-tick.v1` JSON object, with mode
`dry_run`, exactly its fields and no duplicate keys at any depth. `planned_at`
must be a nonnegative integer in the unsigned 64-bit range; it is validated,
not compared to the later execution clock. Every other field must equal the
current typed planner's document: the complete ordered actions, including their
arguments, rules, facts and `planned` outcomes, the rules object and the default
branch. JSON object key order and whitespace are immaterial; array order is not.
Extra, missing, duplicated or reordered actions and changed arguments all refuse.

Before recovery can run, the restricted tick refuses if any repository start
record has a pending latest attempt. The dry-run preview never authorizes the
separate recovery plan. Otherwise the whole plan comparison completes before
the first action: a mismatch leaves no partial GitHub/CloudRoom write or local
state/lock write. Unreadable or invalid plan files also refuse. The restriction
never supplies authority; all existing action preconditions and rechecks still
apply, and execution uses only the compared ordered actions. Once the plan
matches, later executor failures retain their usual per-action outcomes.

Use the separate `--expect-plan PATH` form once, on execution only: no
`=value`, empty/non-UTF-8 path, `--dry-run` combination or `fleet due` form.
The next token is the path even when it resembles a flag. Argument errors
exit 2; an unreadable, invalid, mismatched or recovery-ineligible reviewed plan
exits 1. With a genuine `--json` option, refusal uses the existing
`openwiz.cli-error.v1` envelope; no fleet execution report is emitted.

Approval: Jake, 2026-11-07, EX1: the opt-in reviewed-plan restriction with no
default behavior or schema change ([private record](https://github.com/jparker2006/ClosedWiz/issues/1892#issuecomment-6712343375)).

### Envelope fields

| Field | What |
| --- | --- |
| `schema` | Always `openwiz.fleet-tick.v1` |
| `mode` | `dry_run` (`--dry-run`: nothing is written; every outcome is `planned`) or `run` (the actions were carried out; no outcome is `planned`) |
| `planned_at` | The clock the planner used, in milliseconds since 1970 |
| `default_branch` | The repository's default branch, as read: the only base the tick reviews or merges into |
| `rules` | [The rules file](#the-rules-file), as read |
| `actions` | Every action due, including attempted pending-start recoveries in run mode, in [order](#order); `[]` when nothing is due and no recovery was attempted |

**Silent when nothing is due** (S2-4): an empty `actions` list. Without `--json`, the tick prints only the `wake` and `needs_you` actions (one line each), **and one line for every action that did not end `done`.** Those lines' wording is B5's.

**A run never hides a fault (R5, #516):** without `--json`, an action whose outcome is `refused`, `failed` or `uncertain` prints `fleet #<spec>: #<ticket-or-spec> <rule> <state>: <reason>`, so a loop agent that runs `openwiz fleet tick` cannot mistake a write that keeps failing for a quiet tick. A recovered pending start is such an action: an unsuccessful recovery outcome is printed this way too, from the action recovery already attempted, without executing it again or repeating a confirmed start. A `wake` or `needs_you` that ends `done` keeps its judgment line; one that did not prints this line instead, never both. A dry run's actions are all `planned` and print no such line. The exit status is unchanged: the tick still exits 0 when it planned or ran, and the diagnostic lines, not the status, carry the fault.

## Reading it

Readers use hand-written strict readers, as for `openwiz.fleet.v1` ([Reading it](fleet.v1.md#reading-it)), never serde's derived ones:

- **An object** only from a JSON object with **exactly its keys, each once.** A missing, extra or **duplicate** key is refused.
- **An enum or a tag** (`mode`, `kind`, `rule`, an outcome's `state`, a role, a result, a verdict) only as **one string from its list.** Never another spelling (`Merge`, `dry-run`), never a number or a bool, never a **tagged object** such as `{"merge": null}`, `{"dry_run": {}}` or `{"planned": null}`.
- **A list** only from a JSON array, **an object** only from a JSON object: a **positional array** in place of an object (`["merge", "adr_0008", 930, 931]`) is refused.
- **Integers** only as JSON integers: no `1.0`, no `"1"`, no `true`. `NaN` and `Infinity` aren't JSON.
- `null` only where the schema has it.
- **The rules below are part of the contract.** A reader that checks only the schema must not rely on them.

## The rules file

The tick reads the project's rules from **`docs/agents/fleet.md` on the default branch**, in the format `setup` writes (`skills/setup/templates/fleet.md`, #97). Only the parts below are machine-readable; every other line is for people. They are read exactly as written here, and **anything else is refused:** a section missing or twice, a table missing, a header or separator row that differs, a row out of form, a value twice. A refused rules file means the tick plans nothing.

A section is the lines from its heading line, exactly as written (`## Builder`), to the next line starting `## `. Its table is its one block of consecutive lines starting `|`. A row's cells are split on `|` and trimmed, and every row of a table read here has exactly three; the first row is the header, the second the separator, each of its cells exactly `---`. `<value>` below is a **setting**: lowercase letters, digits, `.`, `_` and `-`, starting with a letter or digit, at most 128 (a narrower form of new-thread.v1's `setting`, so a template's `<id>` is refused).

| Section | Header row | Rows read | Into |
| --- | --- | --- | --- |
| `## Builder` | `` \| Setting \| Value \| `room-cli thread spawn` flag \| `` | Exactly three, in this order: first cells `Harness`, `Model`, `Effort`; third cells exactly `` `--provider <value>` ``, `` `--model <value>` ``, `` `--reasoning-level <value>` `` | `rules.builder`: `harness`, `model`, `effort` |
| `## Builder for small tickets` | The same | The same | `rules.builder_small` |
| `## Reviewer for Claude-built` | The same | The same | `rules.reviewer_claude`; harness must be `codex` |
| `## Reviewer for GPT-built` | The same | The same | `rules.reviewer_gpt`; harness must be `claude-code` |
| `## CI checks` | `\| Check \| Runs \| Required on \|` | One or more. First cell exactly `` `<name>` `` (letters, digits, `.`, `_` and `-`, starting with a letter or digit); third cell one or more `` `<branch>` `` (letters, digits, `.`, `_`, `-` and `/`, starting with a letter or digit, and maybe a final `*`), separated by `, `, each once | `rules.ci_checks`: `{"name", "required_on"}` each, in the table's order |
| `## Standing merge rules` | `\| Pull request \| Review \| Merged by, and when \|` | The one row whose first cell starts `A ticket in an approved plan graph` and whose third cell starts `The loop, as soon as the reviewer's APPROVE names that exact commit` | `rules.merge`: `adr_0008` when that row is there; `none` when no row is (every merge waits for the user, `setup`'s default) |

The display values (the second cells of the agent tables), the `Runs` column, the other merge rows (docs-only, grills, `release-*`) and every paragraph are not read. A `<branch>` in `Required on` may end in `*`, which matches any rest of a branch name (`release-*`); nothing else is a pattern.

- **Builder selection:** an exact `polish`, `huntr` or `proposal` label selects `builder_small`; every other ticket uses `builder`. These rules are complementary; ambiguous/unmatched classifications fall to `builder`. Each `frontier` action carries its selected `settings`.
- **Reviewer selection:** `first_review` and `fresh_review` carry `settings` from `reviewer_claude` or `reviewer_gpt`, using the ticket's unique `launch-fleet: start checked, branch <branch>` record. Its branch must equal the PR head branch; that exact thread's provider must be `claude-code` (Claude) or `codex` (GPT). Missing, malformed, conflicting, unread or unsupported observations yield `look`, never a reviewer start. Today's builder setting cannot establish an earlier builder's family. Existing reviewer re-checks keep their thread; unavailable reviewers wait, never swap families. Sonnet eligibility remains outside this tick (#588).
- **Claude plan-limit fallback:** for an approved, open, unheld agent ticket, a verified, unarchived Claude builder stopped (`idle` or `error`) with its own complete output/error containing a recognized limit line yields `wake/restart`, once per ticket. Recognized lines are exactly `Claude usage limit reached`, `You've hit your limit`, or `You've hit your limit · resets <nonempty reset text>`, after trimming. Generic errors do not qualify. The branch must match any open PR. Its facts contain `builder`, `branch`, and the small-ticket `settings`. Run mode saves `launch-fleet: builder fallback due, branch <branch>` before printing the due line. This durable record consumes the fallback; dry runs never consume it. The orchestrator carries out the restart on that branch; the tick starts no replacement itself. This rule never applies to reviewers. In the private compatibility form only, after a manual restart the orchestrator updates the original checked record to the replacement thread on the same branch and appends `Replacement: <id>` to the due comment. Only this consistent handover retires the original stored builder; conflicts yield `look`. A recorded replacement retains earlier code on the branch, so the builder family stays conflicting for new reviewer assignments: `first_review` and `fresh_review` yield `look: builder family unknown or conflicting`, with no spawn. The orchestrator or Jake chooses the reviewer explicitly.
- **The required checks of a pull request** are the `ci_checks` whose `required_on` matches its base branch, in the table's order. **CI is green on a head** when its base has at least one required check, each required check is on it with result `pass`, and no check on it is `fail`, `cancel` or `pending`.
- **The merge rule** is ADR 0008's, in full, under [`merge`](#merge). With `none`, the tick never merges.

## The review report

The tick reads two parts of `review-ticket`'s report (#101, "The report") and nothing else of it:

- **The verdict:** the pull request's latest comment whose first line starts `VERDICT: `, read as fleet.v1 reads it: exactly `VERDICT: APPROVE at <commit>` or `VERDICT: CHANGES at <commit>`, with all 40 characters. A latest `VERDICT:` line in any other form is a `look`, never a verdict.
- **The findings,** on a `CHANGES` report: each line that starts `- **R<n> [<severity>]** `. Its status is `disputed, kept` when the rest starts `disputed, kept:`, and still open after `<k>` rounds when it starts `still open after <k> rounds:`. A finding line in neither form is new, resolved, withdrawn or a follow-up, and needs no diagnosis. The ids come from these lines, never from the `Next:` line.

## Actions

Every action is `{"kind", "rule", "spec", "ticket", "facts", "outcome"}`:

- **`kind`:** one of the ticket's ten (#117): `start_builder`, `start_reviewer`, `send_findings`, `merge`, `close`, `hold`, `archive`, `log_refused_start`, `wake`, `needs_you`.
- **`rule`:** the rule it cites. Each rule belongs to one kind, and fixes the shape of `facts`.
- **`spec`:** the spec (fleet) the action is under. **`ticket`:** its ticket, or `null` for an action on the spec itself: always `null` for `all_closed`, `re_approve` and `spec_summary`, either for `look`, and never for the rest.
- **`facts`:** the facts that justify it, below.
- **`outcome`:** [what happened](#outcomes).

### The actions

| Kind | Rule | `ticket` | When (the rule's source) | Does |
| --- | --- | --- | --- | --- |
| `start_builder` | `frontier` | the ticket | The ticket is on the frontier: approved (its row in the spec's current plan graph approval says `ready-for-agent`); ready (open, the `ready-for-agent` label, no other triage label); unblocked (every blocker a verified merge); not started (no start in OpenWiz's records but ones settled with no thread, no open pull request); not held (no `held` label, and no contract hold due) (launch-fleet, "The frontier"; spec #116, stories 5 and 6) | Starts its builder |
| `start_reviewer` | `first_review` | the ticket | Its open pull request's head is a hand-back (its subject has the word `green`), CI is green on it, it has no verdict, and no reviewer was ever started on the pull request (launch-fleet, step 4, "Starting a review"; story 8) | Starts a reviewer |
| | `fresh_review` | the ticket | The same, but every reviewer started on it was given up on (`review given up <commit>: <why>`) (launch-fleet, step 4, "A quiet reviewer", 3) | Starts a new reviewer |
| | `re_check` | the ticket | The same, but a reviewer not given up on reviewed an earlier head (launch-fleet, step 4, "A re-check"; review-ticket, "Re-checks") | Asks that reviewer to re-check |
| `send_findings` | `review_findings` | the ticket | Its open pull request's head is a hand-back, CI is green on it, and the latest verdict is `CHANGES` on it (launch-fleet, step 4, "Findings"; spec #116, "Findings go to the builder through 0.0.3's `send`") | Tells the builder to fix or dispute |
| | `ci_failed` | the ticket | The head is a hand-back and a check on it failed or was cancelled (launch-fleet, `CI failed`) | Tells the builder CI failed |
| | `contract_changed` | the ticket | A merge changed a file its `Relies on` line names, and it is being built (launch-fleet, step 5, `note`; story 9) | Tells the builder which files changed |
| `merge` | `adr_0008` | the ticket | Every condition of [the merge rule](#merge) holds (ADR 0008; `fleet.md`, "Standing merge rules"; spec #116, "Merging") | Merges that exact head, and reads it back |
| `close` | `merged` | the ticket | Its pull request's merge is read back on the default branch, and the ticket is still open (launch-fleet, step 4, "Merging", 4) | Closes the ticket |
| | `all_closed` | `null` | Every ticket of the spec is closed and archived (no `finished` due), its summary is written, and no follow-up is open (launch-fleet, `close spec`) | Closes the spec |
| `hold` | `contract_hold` | the ticket | A merge changed a file its `Relies on` line names, and it has no builder yet (launch-fleet, step 5, `hold`; ADR 0006; story 9) | Holds it: the `held` label on, its ready label off |
| | `release` | the ticket | It still has the `held` label from the tick's own hold, and the user approved it again since (launch-fleet, `release`) | Takes the `held` label off |
| `archive` | `finished` | the ticket | The ticket is closed and has a recorded builder or reviewer, and either an agent is not archived or the final `launch-fleet: archived` record is missing; already-archived agents count as done (launch-fleet, `archive`; story 10) | Archives those agents |
| `log_refused_start` | `builder_refused` | the ticket | A builder start was refused, or failed with no thread made, and isn't logged yet (launch-fleet, step 3, 3) | Logs it on the ticket; the ticket stays on the frontier |
| | `reviewer_refused` | the ticket | The same for a reviewer start (launch-fleet, step 4, `review refused`) | Logs it on the pull request; the review waits |
| `wake` | `restart` | the ticket | A verified Claude builder reports its plan limit, and no fallback due record exists (revision #1196, above) | Records and prints one restart due item, keeping its branch |
| `wake` | `needs_info` | the ticket | It has the `needs-info` label and a question newer than the last time it was passed on (launch-fleet, `needs-info`; grill Q7) | An agent passes the question to the orchestrator |
| | `disputed` | the ticket | The latest verdict is `CHANGES` on the head, the report keeps a disputed finding (`disputed, kept`), and no `dispute asked <commit>` is there yet (review-ticket, "Re-checks", 2; grill Q7) | An agent asks the orchestrator for its diagnosis |
| | `diagnosis` | the ticket | The latest verdict is `CHANGES` on the head, a finding is still open after 2 or more rounds, and no `diagnosis asked <commit>` is there yet (review-ticket, 2 + 1; grill Q7) | An agent asks the orchestrator for its diagnosis, or, after a diagnosis round, to take it to the user |
| | `look` | the ticket, or `null` | Something can't be read in full, there are two of something, a start's outcome can't be settled, a reviewer is quiet (no verdict 30 minutes after its start or re-check), or a merge whose conditions held was blocked: the tick leaves the item alone (launch-fleet, `look`, `check review` and `merge blocked`; the orchestrator on #117, 2026-11-01: grill Q7's list is the normal flow's judgment items, and these the fail-closed case, for the orchestrator). One `look` per ticket (or spec) and tick, its reason naming every item | An agent looks, and records what it did in `launch-fleet`'s forms (a quiet reviewer: `review told again <commit>`, or `review given up <commit>: <why>` once it gives up and archives it), which later ticks read |
| `needs_you` | `held` | the ticket | The tick's `held for #<merged>` record is on the ticket (its `hold`), and no `needs you sent: held for #<merged>` yet: the pass or tick after the hold (launch-fleet, step 5) | Asks the user to re-approve it |
| | `re_approve` | `null` | A ticket of the spec could start, but its plan changed since the latest approval (launch-fleet, `re-approve`) | Asks the user to approve the plan as it now stands |
| | `person_ready` | the ticket | A `ready-for-human` ticket is approved, unblocked and not held (launch-fleet, `person`) | Tells the user it's theirs to do |
| | `spec_summary` | `null` | Every approved ticket of the spec is closed, and no summary is written yet (launch-fleet, `spec done`) | Writes the closing summary |

The `all_closed` and `spec_summary` rules retain v1's completion conditions; see [Changed from launch-fleet](#changed-from-launch-fleet) for their differences from #1021.

A `wake` is printed for an agent to act on (spec #116: "disputes and 2 + 1 diagnoses are printed for an agent"); a `needs_you` is written by the tick itself, in the orchestrator's thread and on the spec issue. Those two kinds are the only ones a quiet tick would print.

### Facts

The shared shapes:

| Name | Shape | What |
| --- | --- | --- |
| approval | `{"comment", "revision", "fingerprint"}` | The spec's latest plan graph approval (`plan-graph`'s `**Plan graph approved by` comment): its comment id, revision number and `Fingerprint:`. In `frontier`, `adr_0008`, `release` and `person_ready` it is **current**: the fingerprint is the SHA-256 of what `revision.sh <spec>` prints now |
| pr | `{"number", "head_commit", "base_branch"}` | The ticket's open pull request (fleet.v1's `pr_discovery`: the one open pull request that closes it), not a draft, at its head |
| merge | `{"number", "merge_commit"}` | A merged pull request and its merge commit, read back on the default branch |
| blocker | `{"number", "pr", "merge_commit"}` | A blocking issue with a verified merge: closed, and its pull request's merge commit read back on the default branch |
| check | `{"name", "result"}` | A check on the head: its latest run (fleet.v1's `checks` read); `result` is `pass`, `fail`, `pending`, `skipping` or `cancel` |
| verdict | `{"verdict", "commit", "comment"}` | The pull request's latest `VERDICT:` comment (review-ticket's first line): `approve` or `changes`, the commit it names, and its comment id |

Ids: a **comment** is GitHub's comment id (an integer); a **thread** is a CloudRoom thread id; a **start** is the op id of OpenWiz's own start record (B4; new-thread.v1's `op_id`); a **commit** is 40 lowercase hex digits, a **fingerprint** 64; a **finding** is a report's id, `R` and a number.

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

ADR 0008 in full: a ticket's pull request merges **only when every one of these holds**, and then the tick performs it. Any one missing, or unread, means no merge (S2-1).

1. **The rules file's merge rule is `adr_0008`.**
2. **Approval:** the ticket is in the spec's latest plan graph approval, and that approval is current (`facts.approval`).
3. **APPROVE on the head:** the pull request's latest verdict is `approve` and names its head commit (`facts.verdict.commit` is `facts.pr.head_commit`), and the reviewer's own thread shows that same line (`facts.reviewer`; launch-fleet, step 4, "Merging", 1). Every agent posts from the same GitHub account, so the comment alone never decides.
4. **CI green on the head:** as the rules file defines it (`facts.checks`).
5. **The base is unchanged:** the base CI ran against is the base branch's head now (`facts.base_commit`).
6. **Not a release line:** the base branch is the default branch, and no `release-*` branch. Release lines, publishing and anything live stay the user's (grill Q5; story 4).

### What each action writes

The tick's memory is GitHub, plus OpenWiz's own record of the agents it starts (B4). **An action is due until what ends it is there:** its record, or a state read back (the last column). **A record is written last,** once every write before it has succeeded, and been read back where the action says so; so an action interrupted or failed part way leaves no record, is due again, and repeats only the writes it can't find done (each of those is named below). Records are in `launch-fleet`'s forms ("Records") and always new comments: **the tick never edits or deletes a comment.** A `wake` writes nothing: the agent it wakes records what it did, in those forms, once it has done it. `<P>` is the pull request, `<commit>` its head.

| Rule | Writes, in order | Ended by |
| --- | --- | --- |
| `frontier` | B4's start record, then one `new_thread` with the action's selected `settings`, with no title and the brief `You are the builder for #<N>. Read skills/build-ticket/SKILL.md and follow it.`; then, for people, `launch-fleet: started` on the ticket | B4's start record: a start it records is never repeated; an uncertain one is reconciled (0.0.4's status read), or a `look`. The comment ends nothing, and one that fails isn't retried |
| `first_review`, `fresh_review` | B4's start record, then one `new_thread` with the action's selected `settings`, with no title and the brief `You are the reviewer for pull request #<P> at <commit>. Read skills/review-ticket/SKILL.md and follow it.`; then, for people, `launch-fleet: review started <commit>` on the pull request | B4's start record, as for `frontier` |
| `re_check` | One `send` to `facts.reviewer`: `Re-check pull request #<P> at <commit>: read skills/review-ticket/SKILL.md, Re-checks.` | `launch-fleet: re-check sent <commit>` on the pull request, after the send |
| `review_findings` | One `send` to `facts.builder`: `The review of pull request #<P> at <commit> asks for changes: read the report there. Fix or dispute each open finding, then hand back a new green head.` | `launch-fleet: findings sent <commit>` on the pull request, after the send |
| `ci_failed` | One `send` to `facts.builder`, naming the failed checks and the commit | `launch-fleet: CI failure sent <commit>` on the pull request, after the send |
| `contract_changed` | One `send` to `facts.builder`, naming the files and the pull request that changed them | `launch-fleet: noted #<merged>` on the ticket, after the send |
| `adr_0008` | `gh pr merge <P> --merge --match-head-commit <commit>`, with a body citing the rule, the approval and the verdict; the read back (`gh pr view <P> --json state,mergeCommit,headRefOid`: `MERGED`, the same head); then, for people, `launch-fleet: merged #<P> at <commit> by ADR 0008: approval revision <n> (comment <id>), APPROVE (comment <id>), CI green` on the ticket | The pull request merged, read back: the merge's own body names the rule, so the comment ends nothing. If the merge or its read back fails, `launch-fleet: merge blocked <commit>: <why>` on the pull request ends it for that head, and a `look` follows |
| `merged` | `launch-fleet: closed: merged in #<P> at <merge commit>` on the ticket, unless that comment is there already; then `gh issue close <N>`, read back (`gh issue view <N> --json state`) | **The ticket read back closed.** The comment ends nothing: a ticket still open is due again, and its comment isn't posted twice |
| `all_closed` | `launch-fleet: closed: every ticket is closed` on the spec, unless it's there already; then `gh issue close <spec>`, read back | **The spec read back closed,** as for `merged` |
| `contract_hold` | The `held` label on, then `ready_label` off: two edits, each read back, and one already so is done. The tick creates no label: without the project's `held` label the first edit fails | `launch-fleet: held for #<merged>: contract changed, re-approve. <files> changed in #<merged>.` on the ticket, after both edits |
| `release` | The `held` label off, read back | The label read back off |
| `finished` | `room-cli thread archive <id>` for each thread (one already archived counts as done) | `launch-fleet: archived` on the ticket, once all are |
| `builder_refused` | One comment, its own record | `launch-fleet: start refused: <reason> (start <start>)`, or `start failed:`, on the ticket |
| `reviewer_refused` | One comment, its own record | `launch-fleet: review refused <commit>: <reason> (start <start>)`, or `review failed <commit>: <reason> (start <start>)` (no thread: never a reviewer given up on), on the pull request |
| `needs_info` | Printed for an agent | The agent's `launch-fleet: asked the orchestrator` on the ticket, once it has passed the question on |
| `disputed` | Printed for an agent | The agent's `launch-fleet: dispute asked <commit>` on the pull request, once it has asked the orchestrator about every finding the action names |
| `diagnosis` | Printed for an agent | The agent's `launch-fleet: diagnosis asked <commit>` on the pull request, once it has asked the orchestrator about every finding the action names. Its own record, never the dispute's: one passed on never ends the other |
| `restart` | Under the builder start lock, re-read records and save the one fallback due comment, then print its branch and settings | The ticket's fallback due record; refused, failed or uncertain writes print no restart line |
| `look` | Printed for an agent | The agent's `launch-fleet: look: <reason>` on the ticket (a pull request's item too), or on the spec, once it has looked |
| `held` | One `send` to the orchestrator's thread (`Needs you: …`), and a comment on the spec starting `**Needs you:** #<N> is held for #<merged>`, unless it's there already | `launch-fleet: needs you sent: held for #<merged>` on the ticket, after both |
| `person_ready` | The same two writes, the comment starting `**Needs you:** #<N> is ready, and only you can do it` | `launch-fleet: told the user` on the ticket, after both |
| `re_approve` | The same two writes, the comment starting `**Needs you:** spec #<S> changed since revision <n>` | `launch-fleet: needs approval: changed since revision <n> (fingerprint now <its first 12 digits>)` on the spec, after both |
| `spec_summary` | One `send` to the orchestrator's thread; then the summary on the spec, in place of a `**Needs you:**` comment (as `launch-fleet` writes it) | The summary itself, `launch-fleet: spec summary: …`, posted last |

**Shared relay record (#546):** a relay is sent at most once per key (pull request, head and kind, scoped to its repository), and repeated only when its shared record is uncertain, such as a crash between send and outcome recording. The direct route and the tick's check-in consult the same durable `RelayStore` record before relaying; `RelayKey` and `RelayStore` are exported by `openwiz_service::events`, and the tick's consumer is #694. `RelayKey::op_id()` hashes the canonical repository, PR, head and relay kind with the `openwiz.fleet-relay.v1` domain into the existing private `sends/<op_id>.json` send record; both clients open the same OpenWiz state root. Its atomic claim and dispatch mark are synced before the provider call. A live in-progress record never permits another call; a stopped dispatch is uncertain, not failed or successful. The uncertainty exception does not request an automatic retry: these APIs return the saved outcome by default and never generate a new ID for a repeated hint. The table's post-send GitHub comments remain notifications; their absence cannot replace or bypass this shared record. A comment the table says "unless it's there already" is found by its first line and never posted twice. The orchestrator's thread is given to the tick (B5); `send` is 0.0.3's. Which writes go through which allowlisted command is B3's (GitHub: one comment, one label, one close or one merge per call, each read back) and B4's (CloudRoom).

### Order

In run mode, recovery actions appear first, in the order attempted, each with
its actual outcome. Recovery rechecks authority and reconciles pending starts
before the tick refreshes its inputs and makes the remaining plan. The actions
from that refreshed plan follow in the order below. A dry run performs no
recovery: an unresolved pending start remains a `look` with a `planned` outcome.

Actions are listed by `spec` ascending; within a spec, its spec-level actions (`ticket` `null`) last, the rest by `ticket` ascending; within a ticket (or the spec), by kind in the action table's order; within a kind, by rule in its order. A document has at most one action per kind and rule for each ticket, and at most one `start_builder` per ticket: **never two builders**. Each action stands alone: none needs another beside it. But **actions from one review report agree:** a ticket's `review_findings`, `disputed` and `diagnosis` in one document have the same `pr` and the same `verdict` (a ticket has one open pull request, and its latest verdict is one comment). A `contract_hold` and its `held` are never in one document, since the notification is due only once the hold's record is there.

## Outcomes

| `outcome` | Means |
| --- | --- |
| `{"state": "planned"}` | Due, not carried out: every action of a dry run, and only those |
| `{"state": "done"}` | Carried out, its writes read back where the action says so, and its record made |
| `{"state": "refused", "reason"}` | The tool refused before anything changed (CloudRoom refused a start; `gh` refused a merge whose head moved). **Nothing changed** |
| `{"state": "failed", "reason"}` | It didn't complete: one of its writes failed, and is known not to have happened. **The writes before it may have happened, and are known** (a close's reason comment posted, then the close not read back closed); nothing after it was tried. Its record isn't made, so it's due again, and a retry repeats only the writes it can't find done, as [What each action writes](#what-each-action-writes) says |
| `{"state": "uncertain", "reason"}` | Whether a write happened can't be told (a start that timed out). **Unknown stays unknown:** the next tick reconciles it (0.0.4's status read) before anything is retried, and a start that can't be settled is a `look`, never a retry |

The reason is OpenWiz's own words, never a tool's raw output.

## Where each fact comes from

| Facts | From |
| --- | --- |
| `title`, `labels`, a ticket's `Relies on` paths, `blockers`, a `pr`'s number, head and base, `checks`, a `verdict`'s verdict and commit, a `merge` and its read back | fleet.v1's reads (`issue`, `blocked_by`, `pr_discovery`, `checks`, `comments`, `merge_readback`) |
| `default_branch`, `subject`, `base_commit`, a verdict's `comment`, the approval, `fingerprint_now`, the `launch-fleet:` records, `files`, `question`, `findings`, `follow_ups` | GitHub reads fleet.v1 doesn't make: the spec's comments (`plan-graph`'s approval), `revision.sh`, the head commit, the base branch's head, comments and records, the files a merge changed, review reports. They join fleet.v1's allowlist of reads (B5) |
| `rules` | `docs/agents/fleet.md`, as [above](#the-rules-file) |
| `start`, `retry_after`, `builder`, `reviewer`, `given_up`, `threads` | OpenWiz's start records (B4) and the `launch-fleet:` records; `reviewer` in `adr_0008` also its thread's own output (`room-cli thread output`) |
| `reason`, `planned_at`, `outcome` | OpenWiz's own |

## Rules the schema can't express

Each has the finding id the check reports. The planner (B2) produces only documents that keep them; a reader that checks only the schema must not rely on them.

| Id | Rule |
| --- | --- |
| `mode` | In a `dry_run` every outcome is `planned`; in a `run` none is |
| `head` | A `verdict` in `adr_0008`, `review_findings`, `disputed` and `diagnosis` names its `pr`'s `head_commit`; a `re_check`'s `last_verdict` names another commit |
| `base` | Every `pr` has the document's `default_branch` as its base, and the default branch is no release line (it doesn't start `release-`) |
| `checks` | No check name twice. In `first_review`, `fresh_review`, `re_check`, `review_findings` and `adr_0008`, CI is green on the head (its base has a required check, each required check `pass`; none `fail`, `cancel` or `pending`); in `ci_failed`, at least one check is `fail` or `cancel` |
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

`approval` being current, `base_commit` being the base's head now, `reviewer`'s own output, the facts being as read, and every condition of each rule's "When": those the planner establishes from its reads (B2, B5), and B2's table tests prove; no document can show them.

## launch-fleet's lines

Every line of `launch-fleet`'s check (`skills/launch-fleet/scripts/fleet.sh`), and its action here:

| Line | Action |
| --- | --- |
| `start #N` | `start_builder`, `frontier` |
| `reconcile start #N`, `reconcile review #P` | None of its own: B4's status read settles an uncertain start before the tick plans; one it can't settle is a `look` |
| `check start #N` | Not in version 1 (below) |
| `review #P … first review`, `review #P … a fresh reviewer` | `start_reviewer`, `first_review` or `fresh_review` |
| `re-check #P` | `start_reviewer`, `re_check` |
| `check review #P` (a quiet reviewer) | `wake`, `look`: an agent tells it again or gives up on it, and records `review told again` or `review given up`; a fresh reviewer then follows by `fresh_review` |
| `CI failed #P` | `send_findings`, `ci_failed` |
| `findings #P` | `send_findings`, `review_findings`; and `wake`, `disputed` or `diagnosis` when the report says so, each until its agent records it (`dispute asked`, `diagnosis asked`) |
| `merge #P` | `merge`, `adr_0008`; then `close`, `merged`, if the ticket is still open |
| `archive #N` | `archive`, `finished` |
| `hold #N` | `hold`, `contract_hold`; once its record is there, `needs_you`, `held` |
| `note #N` | `send_findings`, `contract_changed` |
| `release #N` | `hold`, `release` |
| `needs-info #N` | `wake`, `needs_info` |
| `person #N` | `needs_you`, `person_ready` |
| `re-approve #S` | `needs_you`, `re_approve` |
| `spec done #S` | `needs_you`, `spec_summary` |
| `close spec #S` | `close`, `all_closed` |
| `look #N` | `wake`, `look` |

### Changed from launch-fleet

Where the tick does what `launch-fleet` does differently, and why:

| Change | Why |
| --- | --- |
| **Spec completion remains v1 behavior:** `all_closed` still waits for every sub-issue to close and its agents to be archived, the summary to be recorded, and no open follow-up. `spec_summary` requires closed approved tickets, not verified planned builder merges; it lists the `follow_ups` input plus every open unapproved sub-issue, classifying the latter as follow-ups without checking a `polish` label or body marker. Neither rule checks live-check evidence or labels follow-ups `polish` | #1021 changed `launch-fleet`: verified planned builder merges, completed planned human work and any required live-check pass permit completion; confirmed follow-ups go to `polish` and never block it, while unclassified sub-issues require judgment. V1 has no live-check evidence input and no per-sub-issue follow-up marker (an `Issue` carries no body; the `follow_ups` input lists marked external issues). The tick writes the summary and closes the spec itself ([What each action writes](#what-each-action-writes)), with no step that checks live-check evidence or classifies follow-ups. Until it has one, the orchestrator running `launch-fleet` must check the live-check evidence and classify and label follow-ups before a `spec_summary` or `all_closed` action is carried out. These documented differences grant no waiver of #1021's completion gates and do not claim planner parity |
| **No comment is ever edited.** A start is recorded in OpenWiz's own start records before it's made, not as a `launch-fleet: starting` claim edited on; every record is a new comment | B3: "Never delete a branch, force anything, or edit any comment"; spec #116: "A start is recorded before it's made, like `send`'s op ids" |
| **A merge also needs the spec's current approval** and the rules file's `adr_0008` row | Spec #116, "Merging": "the ticket belongs to a plan graph whose approval comment matches its current revision"; fleet.v1, "Approval and authority". `launch-fleet`'s `merge` line tests neither |
| **The required checks are the `Required on` column's,** for the pull request's base | `fleet.md`, "CI checks"; `fleet.sh` takes every check in the table |
| **New records:** `merged #<P> at <commit> by ADR 0008: …` on the ticket, `closed: …` before a close, `(start <start>)` at the end of a refused or failed start's record, `needs you sent: held for #<P>`, `dispute asked <commit>` and `diagnosis asked <commit>` | Spec #116: every merge "records which rule allowed it" (story 3), and "the rule cited in a comment"; `docs/agents/issue-tracker.md`: post the reason, then close; one record per start attempt, so each is logged once; and a notification, a dispute and a diagnosis each end with their own record, so a failure before one is retried, and one never ends another (the review of #304, R1 and R4) |
| **What ends an action is its own record, written last, or a state read back:** a close ends only when the issue reads back closed, never with its reason comment | A record written before its writes would hide a failed or interrupted one for good (the review of #304, R1 and R2) |
| **A hold is two label edits, and the tick creates no label** | B3's writes: one label per edit, each read back, and no label create |
| **One `look` per ticket (or spec) and tick,** recorded on the ticket even for its pull request's item | One action per kind and rule per ticket ([Order](#order)) |
| **Quiet reviewers and blocked merges are a `look`** for an agent; the agent tells the reviewer again or gives up on it | Telling a reviewer again needs its thread's output read and judged (below, "Not in version 1") |
| **Issues approved on their own** get no action | fleet.v1's fleets are specs; an issue outside any spec is in no fleet (below) |

## Examples

Synthetic values only. The check validates every `json` block here.

1. **A dry run with one action of every rule:** spec 960's tickets 961 to 978 (#970 held now, #978 held in an earlier tick, its notification due); spec 985, whose plan changed since its approval; spec 990, every ticket closed; spec 995, closed and archived, its summary written.
2. **A run:** three actions and what happened to each.

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

```json
{
  "schema": "openwiz.fleet-tick.v1",
  "mode": "run",
  "planned_at": 1793400300000,
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
      "outcome": {"state": "uncertain", "reason": "the start timed out"}
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
      "outcome": {"state": "done"}
    },
    {
      "kind": "archive", "rule": "finished", "spec": 960, "ticket": 972,
      "facts": {"threads": [{"thread": "syn-thread-b972", "role": "builder"}, {"thread": "syn-thread-r972", "role": "reviewer"}]},
      "outcome": {"state": "failed", "reason": "CloudRoom could not archive the thread"}
    }
  ]
}
```

## Not in version 1

Open, for later tickets or the user; none is guessed in the meantime:

1. **Checking a started builder is at work** (launch-fleet's `check start`): OpenWiz's start record and 0.0.4's status read say a thread started; whether it is working is not read.
2. **Quiet reviewers** are a `look` for an agent, not handled in code: telling a reviewer again needs its thread's output read and judged.
3. **Issues approved on their own** (`triage`'s `**Approved on its own by`) are not fleets in fleet.v1, so the tick plans nothing for them.
4. **Label names.** As in fleet.v1, the triage roles' names (`ready-for-agent`, `needs-info`, `held`, …), which are ClosedWiz's own; `docs/agents/triage-labels.md` is not read.
5. **The user deciding a finding** (still open in the round after the diagnosis) is the orchestrator's call, woken by `diagnosis`; the tick doesn't tell rounds after a diagnosis apart.
6. **Other merge rules.** Only ADR 0008's row is read; docs-only and grill merges stay the orchestrator's, and `release-*` the user's.
7. **Reaching agents another thread started.** A CloudRoom thread can tell and archive only the threads it started (`docs/grills/2026-10-31-fleets-at-scale.md`, its facts; ADR 0011), so a `send` or an archive aimed at an agent another tick or the orchestrator started may fail. Its outcome says so, it leaves no record, and the next tick plans it again.
8. **Changes.** A change to a field, a rule or a reading rule is a new version, `openwiz.fleet-tick.v2`, or a revision recorded here; a changed contract holds the tickets that rely on it (ADR 0006).
