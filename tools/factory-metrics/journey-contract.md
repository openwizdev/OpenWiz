# Ticket journey contract, version 1 (`closedwiz.journey.v1`)

One sanitized record of each ticket's journey, from grill to merge, that the
benches (EB2, #1385) and the CF4 skills eval (EB3 #1386, EB4 #1387) read
instead of parsing GitHub again. EB1 (#1384) owns it; `journey.py` implements
it and `test_journey.py` checks that they agree.

A journey is a fact record of what GitHub still shows. It never proves complete
history, an agent's activity or a real cost: **historical completeness is
unknown** in every document.

## 1. Commands

```sh
python3 -I tools/factory-metrics/journey.py collect --repo OWNER/REPO \
  --ticket N [--ticket N ...] [--usage DAILY.json ...] --out DIR
python3 -I tools/factory-metrics/journey.py check DIR/journeys.json
python3 -I tools/factory-metrics/journey.py bench DIR/journeys.json   # the bench's per-ticket facts
python3 -I tools/factory-metrics/journey.py cf4 DIR/journeys.json     # CF4's findings by kind, links apart
python3 -I tools/factory-metrics/test_journey.py
```

- **Reads GitHub only,** through `gh`, with fixed query documents (never a
  mutation) and REST GETs, like `metrics.py`, which it reuses: the PR and
  closing-link inventory (`collect_prs`), the strict JSON reader, pagination
  checks and the daily usage reader (`read_usage`). It never runs `room-cli`
  and never writes to GitHub.
- **The repository is only `--repo`** (#1279). Nothing names a fixed target.
- **`collect` writes one file,** `DIR/journeys.json`, in a new directory; it
  refuses an existing one. A read it can't trust (a failed `gh` call, invalid
  JSON, a repeated key, a GraphQL `errors` answer, a short or repeated page, a
  run count that changes between pages, a later page whose other fields differ
  from the first page's, a missing field (a nullable one too:
  a missing `parent` is never read as "no spec"), a wrong type, the same
  comment twice with different text, one run matching two collected PRs, two
  valid usage exports for one day) exits 1 and writes nothing. Bad arguments exit 2 before any read.
- **`check`** exits 0 when a file conforms to this contract, otherwise 1 with
  the first reason. `bench` and `cf4` check first, then print JSON.
- **The tickets are named:** a caller (EB2's day, from #1359's `factory.json`
  tickets; EB4's week) passes them. The collector does not choose a window.

## 2. What it reads

| Source | Read |
| --- | --- |
| PRs and their closing tickets | `metrics.collect_prs`: every PR page and closing-link page |
| Each ticket and its spec (the ticket's `parent`) | `ISSUE` query: dates, body (only for a `docs/grills/<name>.md` path), every comment page |
| Each ticket's label events | `LABELS` query: every `LABELED_EVENT` page |
| Each PR closing a named ticket | `PULL` query: dates, branch, base/head/merge commits, body (only for the experiment lines), every comment page |
| Each such PR's CI | REST `repos/R/actions/workflows/ci.yml/runs?branch=B&event=pull_request`, every page to `total_count`; for a run on attempt k > 1, `repos/R/actions/runs/ID/attempts/A` for A < k |
| Usage | Optional `--usage` files, each `metrics.py`'s daily CloudRoom usage export (its README), validated by the same reader |

Bodies are read in memory and dropped. **Never saved:** comment, issue or PR
bodies, transcripts, credentials, session content, thread identifiers, usage
thread keys, branch names. Saved: numbers, times, commits, kinds, counts and
source links. Source links live only in `sources`, apart from the facts.

## 3. The document

```json
{
  "schema": "closedwiz.journey.v1",
  "repo": "OWNER/REPO",
  "history": "unknown",
  "duplicates": 0,
  "specs": [],
  "tickets": [],
  "pull_requests": [],
  "daily_usage": [],
  "sources": {}
}
```

Every key is required, in the order shown, with no extras, at every level below. Times are UTC
`YYYY-MM-DDTHH:MM:SSZ`; commits are 40 lowercase hex characters. `duplicates`
counts identical repeated source items dropped (section 5). `sources` maps
`s1`, `s2`, ... to an `https://github.com/` link (a comment, an issue, a PR or
a workflow run); an event's `source` is one of those keys or `null`.

### Events

Every event is `{"id", "kind", "at", "source", "completeness"}` plus its kind's
own keys. `id` is `e1`, `e2`, ... once in the document. `at` is a time, and
`source` a key of `sources`, on every event but two: a `grill` has no time
(`at: null`), and a `fix_round` with no answers has neither (`at: null`,
`source: null`). `check` refuses any other null, so consumers never sort,
parse or follow one. `completeness` is:

- `complete`: the source item was never edited;
- `edited`: it was edited, so only its current text was read;
- `unknown`: no source item supplies it (a grill path has no time).

| Kind | Where | Its own keys |
| --- | --- | --- |
| `grill` | spec | `path`: each distinct `docs/grills/<name>.md` the spec's body names |
| `spec` | spec | none: the spec issue was opened |
| `plan_graph` | spec | `revision`: integer or `null`. A spec comment whose first line starts `**Plan graph approved` |
| `ticket` | ticket | none: the ticket was opened |
| `ready` | ticket | none: the first `ready-for-agent` label event |
| `builder_start` | ticket | none: a ticket comment whose first line is `launch-fleet: started` or `launch-fleet: start checked, branch <branch>` (one non-whitespace branch token), or starts with the legacy `launch-fleet: started, thread` or `launch-fleet: start checked, thread` (`launch-fleet` edits its claim into the first, then the second). Prose mentioning a record does not count. Its time is the claim's creation, so it is usually `edited` |
| `pr_opened` | PR | none |
| `ci_attempt` | PR | `run`: integer, `attempt`: integer, `head`: commit, `rerun`: `attempt > 1`, `conclusion`: string or `null` (not finished) |
| `verdict` | PR | `verdict`: `APPROVE` or `CHANGES`, `head`: commit or `null`, `independent`: boolean, `duplicate_of`: event id or `null` |
| `fix_round` | PR | `round`: integer from 1, `after`: the CHANGES verdict's id, `answers`: `[{"finding": "R1", "answer": "fixed" or "disputed"}]` |
| `merge` | PR | `commit`: commit or `null` |

A ticket's journey is its own events, its spec's events (shared, by `spec`)
and the events of every PR in its `pull_requests`.

### Specs: shared parent work

`{"spec", "events", "usage"}`. One entry for each spec named by a collected
ticket, **once** however many of its tickets are collected (`check` refuses a
spec or ticket listed twice), so parent work is
never charged to each ticket.

### Tickets

`{"ticket", "spec", "state", "pull_requests", "events", "gaps", "usage"}`.
`spec` is the parent issue number or `null`. `state`: `merged` (a closing PR
merged), `closed` (closed with no merged closing PR) or `open`.
`pull_requests`: the numbers of every PR that now closes it, each once; every
PR in the document that names a collected ticket is in that ticket's list, and
no other (an uncollected ticket on a PR has no entry). `gaps`: the
missing steps, from `no ready label`, `no builder start record`, `no pull
request`, `no merge`, `no spec`, `no grill path`, `no plan graph approval`.

### Pull requests

`{"number", "tickets", "state", "revisions", "experiment", "events",
"findings"}`. A PR closing several tickets is one entry, listing them all, so
its CI attempts and verdicts are counted once. `state`: `merged`, `closed`,
`open`. `revisions`: `{"base", "head", "merge"}` (commits; `merge` `null`
unless merged). These are the before and after revisions that CF4's results
and required-text reports (`tools/skills-eval/contract.md`, sections 6 and 7)
name by commit.

`experiment` is `null` (untagged) or `{"tag", "cf4"}`, read only from exact
lines of the PR description:

```text
Experiment: <tag>
CF4: settings <64 hex> cases <64 hex> code <64 hex> revision <40 hex>
```

`tag` matches `[a-z0-9][a-z0-9.-]{0,63}`. `cf4` is `null` or `{"settings_hash",
"cases_hash", "code_hash", "revision"}`: the CF4 results set's own manifest
fields. A malformed or repeated line is no tag: never a guessed one.

### Findings

Each finding raised by an independent verdict, **once per PR by its id**:
`{"id", "severity", "check", "kind", "kind_evidence", "raised_by",
"statuses"}`. `severity`: `high`, `medium`, `low`. `check`: `Standards`,
`Spec`, `Sweep`. `raised_by`: the verdict event that first listed it.
`statuses`: `[{"verdict": event id, "status": "resolved" | "withdrawn" |
"still open" | "disputed, kept" | "follow-up"}]`, in order.

**Kinds.** The vocabulary starts with the grill's examples (EB2, 2026-11-06):

| Kind | The grill's words |
| --- | --- |
| `missing-proof` | missing proof |
| `stale-docs` | stale docs |
| `spec-mismatch` | spec mismatch |
| `fail-open` | fail-open |
| `unknown` | no kind evidence |

A finding has a kind only from an explicit `Kind: <kind>` marker on its line in
the verdict. `kind_evidence` says which: `marker`, `no marker` or `unrecognised
marker`; the last two always give `unknown`. A kind is never inferred from the
words of a finding, and EB4 adds new kinds to this table by a contract change.

## 4. Review rounds and CI attempts

- **A verdict** is a PR comment whose first line starts `VERDICT: APPROVE` or
  `VERDICT: CHANGES`. It is **independent** only when that line is exactly
  `VERDICT: <APPROVE|CHANGES> at <40 hex>` and its next non-blank line starts
  `Full review by ` or `Re-check ` (the `review-ticket` report). Anything else
  is kept with `independent: false` and is not a review round: a builder's or
  helper's self-check never is.
- **A review round** is one independent verdict with `duplicate_of: null`. A
  second independent verdict whose whole text is identical to an earlier one
  (so the same verdict at the same head) is a duplicate post of that round and
  names it. A re-check at an unchanged head with a new report is a new round.
- **First-time approval:** a PR's first round says APPROVE. A PR with no round
  is unreviewed: its first-time approval is unknown, never false.
- **A fix round** follows each CHANGES round: `round` k is the k-th CHANGES
  round; `answers` are the builder's `R<n> fixed at <commit>` and `R<n>
  disputed` lines in PR comments after that verdict and before the next round.
  It is recorded even when no answer is found (`answers: []`, `at: null`).
  A PR has exactly one fix round for each CHANGES round, in order, with
  `after` naming it.
- **A CI attempt** is one attempt of one `ci.yml` pull-request run of the PR's
  branch. A run whose `pull_requests` lists PRs belongs only to those; a run
  that lists none belongs to the PR open on that branch when it was created.
  A run that would belong to two collected PRs fails the read. Its time is the
  attempt's start.
- **Order:** each list of events is in time order; an event with no time
  sorts at the time of the event it follows (a fix round, its verdict; a
  grill, first). Each `(run, attempt)` is one event in the whole document,
  and every attempt of one run is on the same PR, so a rerun is counted once,
  as its own attempt, for one PR.

## 5. Duplicates

The same comment, label event or run listed twice with identical content (a
page shift) is one source item; each dropped copy adds 1 to `duplicates`. The
same id with different content fails the read. A thread named in fleet records
on more than one ticket, or on a ticket and its spec, is attributed to none
(section 6). Consumers count PR-level facts once per PR number.

## 6. Credits and tokens

Every `usage` (on each spec and ticket) is a list of `{"provider", "unit",
"status", "value", "missing_days", "attribution"}`, one for each of `claude`
and `gpt` × `tokens`, `credits`, `usd`, in that order. `attribution` is always
`thread-record`: a usage row is tied to a ticket or spec only when its export
thread key equals a thread named in a `launch-fleet:` record on that ticket or
its PRs, or on that spec, and on no other collected ticket, PR or spec (a PR's
records name every ticket it closes). Matching happens in memory; neither key
is saved. A thread also named only on a ticket that was not collected is not
seen as shared: collect a spec's tickets together.

| `status` | `value` | Means |
| --- | --- | --- |
| `known` | the sum (a reported `0` is a known zero) | Every tied row reports this unit |
| `unknown` | `null` | A tied row leaves this unit unreported |
| `unattributed` | `null` | Valid exports cover its days, but no row is tied to it |
| `absent` | `null` | No valid export covers any of its days |

Its days are the UTC dates from its first to its last timed event (a
ticket's own and its PRs'; a spec's own). `missing_days` lists those without a valid export; a `known` value
with missing days is a lower bound. Every known value is also a lower bound
for helpers and threads no record names. Sandbox hours have no thread and are
never attributed. CF4's own eval-run usage (its
`openwiz.skills-eval.provider-tokens.v1` report: OpenRouter/DeepSeek tokens
and cost, `tools/skills-eval/contract.md` section 7) is the eval's spend, not a
ticket's: it never enters `usage` or `daily_usage`, and its tokens are never
added to Claude or GPT tokens.

`daily_usage` is, for each valid export, `{"date", "merged_prs", "totals"}`:
`totals` is `metrics.py`'s per-provider, per-unit `{"total", "per_merged_pr"}`
for `claude`, `gpt` and `sandbox`. **`per_merged_pr` is that day's ratio,
never a ticket's cost:** it divides all the day's usage by its merges, and is
`null` with no merges. Units are never added together or converted. An invalid
export appears as `{"date": null, "merged_prs": null, "totals": null}` and
covers no day.

## 7. Consumers

**`bench`** prints `{"schema": "closedwiz.journey.bench.v1", "tickets": [...]}`,
one row per ticket: `ticket`, `state`, `pull_requests`, `rounds`,
`first_time_approval` (`true`, `false` or `null`), `fix_rounds`,
`ci_attempts`, `reruns`, `ready_to_merged_hours` (`null` without both),
`findings` (`{kind: count}`), `usage` (`{"provider/unit": status}`), `gaps`.
PR facts are summed over the ticket's PRs. EB2 trends these by day and cohort.

**`cf4`** prints `{"schema": "closedwiz.journey.findings.v1", "findings":
[...], "by_kind": {...}, "provenance": {...}}`. Each finding is `{"key",
"kind", "severity", "check", "at"}` with a local key `F1`, `F2`, ...; it names
no PR, ticket or link. `provenance` maps each key to its verdict's source link,
as CF4's `provenance.json` keeps links apart from case inputs. `by_kind` counts
every kind in the vocabulary, zeros included. Only independent, non-duplicate
verdicts' findings count, once each. EB4 groups these by week; EB3 reads the
top kinds.

## 8. Proof

`test_journey.py` runs `journey.py` against `metrics.py`'s exact-call fake `gh`
(`fake-gh`) on synthetic worlds only: a complete journey, shared parent work,
several reviews and CI attempts, duplicate sources, malformed, partial and
paginated reads, missing history and unavailable cost attribution. Its
expected values are worked by hand in its docstring. `fixtures/journey/` holds
the conforming outputs, which `check`, `bench` and `cf4` also read. Fixture
results prove neither complete historical coverage nor real cost attribution.

## 9. EB5 outcome extension (`closedwiz.journey.outcomes.v1`)

EB5 (#2176) extends this interface with an **explicit sidecar**, not new keys in
`closedwiz.journey.v1`. `journey.py` continues to collect/check/export v1 unchanged.
Existing CF4 manifests and EB2 consumers remain readable. New consumers use
`experiment_contract.validate(bundle, journey_v1)`; the bundle's `journey` is:

```text
{schema: closedwiz.journey.outcomes.v1, journey_hash: SHA256, measurements: [...]}
```

`journey_hash` is SHA-256 of the v1 JSON serialized as UTF-8 with sorted keys,
compact separators and no nonfinite numbers. Both repository identities must
match. There is exactly one measurement per PR, in v1's PR order. PRs shared by
several tickets stay one measurement; assignments join through v1's ticket and
PR number lists. Source keys in this extension use the **bundle's** source map,
not v1's independently scoped map. Units remain hours, independent rounds and
attributable defect counts/rates; no combined score.

Each measurement has exactly `pr`, `first_push`, `merge`, `rounds`, `helpers`,
`defects`:

- `first_push`: `{status, at, kind, source, coverage}`. `observed` needs a UTC
  timestamp and sourced `builder-push-receipt` or `push-event` evidence, with
  `complete`/`partial` coverage. A receipt records the builder's first successful
  push, not every subsequent push. A historical event requires complete push
  coverage to establish that it was first; otherwise status is `unknown`.
  Unknown has null time/kind/source and `coverage: unknown`. PR creation,
  commit/author dates, a CI start and the first observed head are not substitutes.
  Repeat pushes and force updates never reset a previously established first push.
- `merge`: `{status, at, commit, source, read_at}`. `verified` binds the exact
  merged PR commit/time in v1 to a sourced read-back, at or after merge. `unknown`
  and `unmerged` have all four evidence fields null; `unmerged` cannot contradict
  a merged v1 PR. A v1 merge event alone does not assert read-back verification.
- `rounds`: the exact ordered ids of v1's independent, non-duplicate verdicts.
  `helpers`: the exact ordered ids of its non-independent verdict observations.
  Helpers and builder self-checks never enter independent rounds. This does not
  change the v1 verdict recognition or finding-kind vocabulary.
- `defects`: `{status, observed_until, events, resolutions}`. Status is `unknown`, `unmatured`
  or `mature`. Unknown follow-up ends at null; no zero-defect claim follows.
  Other states need a verified merge and coverage through the timestamp;
  maturity begins inclusively at merge + the experiment's frozen follow-up hours.
  Maturity describes coverage, not certainty of attribution.
- Each defect event is `{key, kind, at, attribution, source}`. `kind` is
  `main-red` or `later-defect-fix`; attribution is `attributable`, `unattributed`
  or `unknown`. Key is the canonical root cause for this merge; repeated CI
  failures and a later fix for the same root cause share one key, not two events.
  Events must fall inclusively within the frozen post-merge window and observed
  coverage. An explicit causal fix/merge link is required by the fixture's
  `explicit-causal-fix-link-v1` policy; chronology or a CI-selector escape alone
  does not establish skill attribution. Unknown attribution stays unknown.

`migrate_journey(v1)` validates with the existing v1 validator, preserves the
input and returns this sidecar with exact round/helper ids and **unknown** push,
merge verification and defect coverage. It never infers history. Future v1
snapshots have new hashes and must be bound explicitly, not silently substituted.
No v1 producer needs upgrading in EB5. EB6 (#2177) owns actual collection and
elapsed-hour/report arithmetic. The example push at 12:00 Jan 1 and verified
merge at 06:00 Jan 2 yields 18 hours; incomplete timing yields null in reports.
`ready_to_merged_hours` and builder-start time keep their own labels.

Attribution decisions can mature independently of follow-up coverage. Preserve
an original unknown event and append one sourced resolution
`{key, at, attribution, source}` for that canonical root key. Attribution becomes
`attributable` or `unattributed`, never a guessed zero; resolution time is no
earlier than the observation. A resolution may arrive after the collection
window without moving the event into a different window. Each unknown event can
be resolved once; known observations and prior resolutions cannot be rewritten.
The original event key is not appended twice. `defect_attributions(defects)`
projects a validated record's current attribution by canonical key for EB6/EB8;
it does not alter the original evidence or claim complete follow-up.

## 10. TL2 stage waits (`closedwiz.journey.stage-waits.v1`)

TL2 (#2337, spec #2185) measures the five stage goals of
[limits-contract.md](limits-contract.md) from the same collection, as an
**explicit sidecar**: `closedwiz.journey.v1`, `bench` without the new flag,
`cf4` and the EB5 outcomes stay as they were.

```sh
python3 -I tools/factory-metrics/journey.py collect --repo OWNER/REPO --ticket N ... \
  --stage-waits [--as-of YYYY-MM-DDTHH:MM:SSZ] --out DIR
python3 -I tools/factory-metrics/journey.py check DIR/journeys.json --stage-waits DIR/stage-waits.json
python3 -I tools/factory-metrics/journey.py bench DIR/journeys.json --stage-waits DIR/stage-waits.json \
  [--settings tools/factory-metrics/limits.conf]
```

**Reads.** Everything in section 2, plus, for each named ticket, every page of
two fixed queries: its `LABELED_EVENT`/`UNLABELED_EVENT` timeline, and its
current labels with every page of its native `blockedBy` issues (state and
close time). For each collected PR, one REST read of the repository activity
for its head branch (`repos/R/activity?ref=refs/heads/B&per_page=100`): every
push, with its time and before/after commits. CI completion is each attempt's
`updated_at` from the run reads section 2 already makes. Any untrusted read
fails the whole collection, as in section 1; nothing is written. `--as-of`
(default: now) is the read time for open intervals; a record later than it
refuses the collection. Branch names and refs are never saved.

**Evidence the clocks rest on.**

- **Start gates** (fleet-tick's frontier rule and `docs/agents/issue-tracker.md`):
  `ready-for-agent` on and none of `needs-info`, `needs-triage`,
  `ready-for-human`, `wontfix`, `held`, replayed from the label timeline, which
  must end at the current labels; the spec's **latest** `**Plan graph approved`
  comment, unedited, naming the ticket (`#N`), whose `Fingerprint: \`<sha256>\``
  line equals the SHA-256 of plan-graph's own `skills/plan-graph/revision.sh`
  output for the spec now (its read-only `gh issue view` reads, run once per
  spec with `GH_REPO` set to `--repo`); and every native blocker closed **and**
  closed by a merged PR in the PR inventory. An older, edited or other-ticket
  approval is `no plan approval`; a missing, different or unreadable fingerprint
  is `approval not current`. A ticket whose plan has changed since its start is
  therefore Unknown: the benchmark fails toward Unknown rather than claim a time. The gate opens at the last of these. A missing approval
  or blocker merge is Unknown; an open blocker keeps the gate shut.
- **Current head:** a head is current from the push that made it the branch tip
  to the next push. The pushes must chain from the branch's creation to the
  PR's head; any break, an empty answer or a full page of 100 is
  `head history incomplete`. CI start times are never used as push times.
- **Green CI:** while the latest started attempt on that head has completed
  successfully. A newer attempt makes it pending or red; a superseded
  attempt's late success never reopens it. Runs starting in the same recorded second
  can't be ordered (run ids are not start order): neither opens green, and a
  head with no other green window stays Unknown `ci order unknown`.
- **Valid approval:** an independent APPROVE (section 4) until the next
  independent verdict that is CHANGES or names another head.
- **Edited end records:** the endpoint happened between the comment's creation
  and its last edit (a claim is edited into a start only after it happens). The
  whole range must lie inside the window it ends, or the interval is Unknown
  with `edited record`. A result is reported only when both ends agree;
  otherwise it is Unknown with `edited record`. An edited *starting* record (a
  verdict, question or approval) is Unknown.

| Stage | Begins | Ends |
| --- | --- | --- |
| `builder_start` | The start gates open | The first builder start record (section 3) inside that open window |
| `reviewer_start` | A window where the head is current and green | The first `launch-fleet: review started`/`re-check sent <commit>` record for that head inside the window; a window holding only a `review starting` claim is unconfirmed, and a later window can still be confirmed |
| `merge` | A window where an approval is valid and its head current and green | The merge, inside the window, of that head |
| `fix_after_changes` | An independent CHANGES round | The push of a new head after the round, cited by a later, unedited `R<n> fixed at <commit>` answer whose `R<n>` the round lists as high or medium and not resolved, withdrawn or follow-up. The answer is kept as `support` |
| `builder_question_answer` | A ticket comment whose first line starts `Builder question:`, while `needs-info` is on | The first comment after it whose first line starts `Orchestrator ruling`, that cites the question's comment link, has words beyond that prefix, the link and any `Disposition:` line, and contains none of the deferral markers `investigation continues`, `still investigating`, `no decision`, `pending`, `deferred` (any case), before `needs-info` is next removed. An acknowledgement, a deferral, a bare status line or a ruling on something else is no answer |

**The sidecar** is `DIR/stage-waits.json`:

```text
{schema, repo, journey_hash, read_at, history: "unknown", holds: {"<ticket>": [[on, off|null], ...] | null},
 intervals: [...], sources: {s1: link, ...}}
```

`journey_hash` is the SHA-256 of the v1 document serialized with sorted keys and
compact separators; `check` refuses a sidecar bound to another journey. `holds`
are each collected ticket's `held` spans from its label timeline (`null` when
that history is incomplete). Each interval is `{key, stage, tickets,
pull_request, head, origin, start, clock_from, end, support, state, folded,
gaps}`. `start` and `end` are `{at, latest, source}` or `null` (`latest` differs
from `at` only for an edited end). `origin` is the comment id that begins a
question, fix or merge wait. `key` is built from immutable evidence and never
renamed by later history: `<stage>:t<ticket>` for a builder start,
`<stage>:t<ticket>:c<origin>` for a question, `<stage>:p<pr>:<head>:c<origin>`
for a fix, `<stage>:p<pr>:<head>:<window start or ->` for a reviewer start, and
`<stage>:p<pr>:<head>:c<origin>:<window start or ->` for a merge. `folded`
counts later records inside an interval already open (repeated starts,
overlapping questions or CHANGES rounds, extra approvals): they never open a
second interval or a second miss.

`state` is `ended`, `open` (no end yet; measured to `read_at`), `unknown`,
`gated` or `stale`. The clock (`clock_from`) restarts when a `held` label on
any of the interval's tickets is removed inside it: held time is never dispatch
delay. Held at its end or at `read_at` is `gated`; a ticket held before any
builder start is `gated` too, whether the hold kept `ready-for-agent` or
removed it after the gate had opened. A window that closes before its end (head
superseded, CI no longer green, approval revoked, PR closed) is `stale`. A
finished ticket or PR without the end record stays as Unknown in the
denominator. Gaps are exactly:

| Gap | Means |
| --- | --- |
| `label history incomplete` | The label replay disagrees with the current labels, or names a deleted label |
| `head history incomplete` | The PR branch's pushes do not chain from its creation to its head |
| `no plan approval` | The ticket has no spec, or its spec's latest plan graph approval is missing, edited or doesn't name the ticket |
| `approval not current` | That approval has no fingerprint, or it differs from plan-graph's current revision, or the revision can't be read |
| `blocker merge unverified` | A closed blocker has no merged PR closing it |
| `start record outside its gate` | The end record falls outside every window its gate was open |
| `edited record` | A starting record was edited, or an edited end straddles the goal |
| `reviewer start unconfirmed` | Only a `review starting` claim inside the window: the start's outcome is uncertain |
| `disputed without fix` | CHANGES answered only by disputes: no resulting fix to time |
| `no linked disposition` | `needs-info` was removed with no substantive, non-deferring ruling that cites the question |
| `no green completion time` | A success with no readable completion time, and no other green window |
| `ci order unknown` | The latest CI runs on the head started in the same recorded second, so which one decides can't be shown, and no other green window |
| `no end record` | The work finished (merged or closed) with no record of this stage's end |
| `no longer current` | `stale` |
| `held` | `gated` |

`check` recomputes every key from its interval's evidence, refuses repeated or
overlapping intervals of one stage, owner and head, and recomputes each
measured or gated interval's state and clock from `holds`. It binds every
interval to the hashed journey: a PR stage's head must be one the journey shows
for that PR; a fix or merge origin must be that PR's independent CHANGES or
APPROVE at that head; a start must be that head's CI run, push or approval; a
merge end that PR's merge; a fix end the push of another observed head; a
builder end one of that ticket's start records; and a question's start and
answer that ticket's comments. An endpoint naming a journey event (a builder
start record, the origin verdict, the merge) must carry that event's own time,
and a green time may not precede its CI run's start. `holds` come from label events the journey
does not carry, so `check` proves them consistent, not true; like every
journey file, the sidecar is as trustworthy as the collector that wrote it. A deleted comment or
label event is invisible: it can only make an interval Unknown or absent, and
history stays unknown. Only `launch-fleet` records count as builder or
reviewer starts. Earlier gate windows that closed before any builder start are
not measured.

**`bench --stage-waits`** checks both files, reads the settings once with
`limits.py` (default `limits.conf` beside the script; refusal exits 1) and adds
`stage_waits`, `closedwiz.journey.stage-bench.v1`:

```text
{schema, settings, read_at, authority: "none", stages: [...], waits: [...], misses: [key, ...], sources}
```

`settings` is the exact loaded limits object. Each wait is `{key, stage,
tickets, pull_request, wait_minutes, wait_range_minutes, limit_minutes, result,
start, end, support, folded, gaps}`, with `start`, `end` and `support` as source
keys. `wait_range_minutes` is `[earliest, latest]` for a measured interval;
`wait_minutes` is set only when the two agree. `result`: `missed` (more than
the goal even at the earliest end, ended or still open), `not missed` (ended
within the goal even at the latest end, inclusive), `pending` (open, within the
goal), or `unknown` (an edited end straddling the goal, or the interval's own
Unknown), `gated` or `stale`; only the first three are measured. Each stage
row is `{stage, limit_minutes, intervals, measured, results}`: `results` counts
every result, the denominators. An open miss keeps its key, so it is one miss
however often it is read.

**Consumers.** WR3 (#2347) projects these facts; TL3 (#2338), TL4 (#2339),
OB5 (#1480) and OB6 (#1481) read the same output through their existing
finite ops seams. A miss is a measured fact only: `authority` is always
`none`, and nothing here starts, tells, retires, merges or spends anything.
`test_journey.py`'s `StageWaits` cases prove it on synthetic worlds;
`fixtures/stage-waits/` holds the sanitized demonstration outputs.
