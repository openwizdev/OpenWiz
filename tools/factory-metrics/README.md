# Daily factory numbers (#566)

```sh
python3 tools/factory-metrics/metrics.py --date 2026-11-01 \
  --repo OWNER/REPO --out /tmp/factory-2026-11-01
python3 tools/factory-metrics/test.py
```

Python 3 standard library and `gh` only. Give `gh` the GitHub App's token with
`GH_TOKEN` when available; normal `gh` authentication also works. No token is
accepted as a command-line argument or printed. Run for a completed UTC day.
No loop is installed. The tool never writes to GitHub or runs `room-cli`.
The repository is only `--repo`: to read another one, pass it (#1279).

**Ticket journeys (#1384):** `journey.py` collects one sanitized record per
ticket, from grill to merge, for the benches and the CF4 eval, reusing this
tool's reads and usage reader; see [journey-contract.md](journey-contract.md).
`python3 -I tools/factory-metrics/test_journey.py` runs its proofs.

It prints the morning report and writes **only aggregates**, `report.json`,
`report.md` (including the chart's data table) and `factory.svg`, in a new output
directory. It refuses an existing directory. The chart has two aligned panels,
independent scales, and exact values on every bar. It uses blue `#0072B2` and
vermillion `#D55E00`, plus labels and spatial separation. Colour-blindness
validation is not yet available; the colours are not claimed as validated.

## What the numbers mean

- **Merged PRs:** every PR in the repository whose `mergedAt` falls in the
  half-open UTC day, across **all base branches**. There are 24 hourly buckets,
  including zeros; the day's average is total / 24.
- **Recorded idle agent-minutes:** a `launch-fleet:` record starting with
  `findings sent`, `CI failure sent`, `merge blocked` or `review started`
  starts a gap. The next fleet record on the same PR or one of its linked
  same-repository closing tickets ends it. A PR gap is also capped at its
  merge or closure; a ticket gap is capped at the merge of a PR that closes
  it. The earliest endpoint wins, so starts after completion count no minutes.
  Closing an unmerged PR does not complete its ticket. The tool
  reads all surviving comments to find carry-in before midnight, and clips
  open gaps at the day's end. It splits minutes over the hours they occupy.
  Simultaneous gaps on different tickets add, so an hour can exceed 60 minutes.
  A PR closing multiple tickets starts **one** gap, with all its tickets named.
  Ordinary comments, new commits and CI results are not fleet records.
  Merges and PR closures stop gaps even when no fleet record follows them.
  PRs without closing tickets are explicitly named as unlinked PRs.
- **Biggest recorded stall:** the longest single gap **within the day**, with
  its closing tickets (or its unlinked PR), start kind and clipped endpoints.
  Ties sort by time, then ticket. `stalls` in the JSON keeps every gap.
- **Costs:** the same day's source-reported usage, separately by provider and
  unit; each known total / merged PR count is also printed. This ratio divides
  all work that day by merges that day; it does **not** attribute that work to
  those PRs. Tokens, credits, hours and minutes are never added to each other
  or converted to money. The factory USD total is available only when every
  component reports USD. A missing component makes that total **unknown**.
  With no merged PRs the ratios are unknown, even for known zero usage.

**Historical completeness is unknown.** A surviving edited comment exposes its
current body, creation and last-update times, not its previous bodies. The tool
orders records by the later of creation and update, then comment ID, and reports
comments whose update precedes creation. It cannot recover a start overwritten
by `review failed` or a deleted comment. Linking uses current closing issue
references, including manually linked issues; the history of those links is
unavailable. Cross-repository links are ignored. Missing fleet records include
work in progress: this measure does not prove actual agent idleness or capture
every silent loop outage. Never present it as complete historical idle time.

## Read-only sources

| Source | Read | Unavailable behavior |
| --- | --- | --- |
| PRs and linked tickets | Fixed GraphQL **queries**, no mutation; all PR pages and all closing-issue pages | Exit 1, no report |
| Fleet records | REST GET, every page of repository issue comments (PR conversation comments share this endpoint); no `since` filter | Exit 1, no report |
| GitHub Actions | Repository owner type, then daily billing usage summary filtered by UTC year/month/day, repository and product `Actions` | Unknown minutes and USD, with reason; still report other sources |
| Claude/GPT model usage and cloud sandbox hours | Optional complete daily owner-supplied export, below | Unknown for each source, with reason; no probing other threads or the Mac |

The GraphQL requests use HTTP POST, as `gh api graphql` normally does, but the
only two query documents are literal constants; neither can perform a mutation.
The REST calls explicitly use GET. All subprocess arguments are arrays, with no
shell. Failed reads, invalid JSON, duplicate keys, partial GraphQL answers,
repeated cursors, duplicate PRs/comments/links and invalid required types fail
rather than quietly dropping records. JSON responses stay in memory, and raw
comment bodies, thread IDs and provider responses are never saved. Error output
never copies an upstream error body.

Actions uses **reported hosted billing minutes** (`grossQuantity`) and **net
USD** (`netAmount`, after discounts), not job elapsed time, a guessed runner
classification or a calculated price. Self-hosted PC runners are free and do
not contribute hosted billing minutes. The response must confirm the exact
requested day. Every item must name `Actions` (case-insensitive) and have a
nonempty string unit. Only `minutes` rows (case-insensitive) contribute to
minutes; **all Actions rows contribute their net USD**, including artifact/cache
storage and other Actions charges. Storage quantities are never converted to
minutes or priced by the tool. A malformed row or another product is unknown.
An explicitly empty daily summary reports zero. Billing can lag.
An App installation token may read the repository and fail to read user billing;
that cost source stays unknown, never a monthly or account-wide substitute.

Primary contracts: [issue comments](https://docs.github.com/en/rest/issues/comments),
[GraphQL pull requests](https://docs.github.com/en/graphql/reference/objects#pullrequest),
[GraphQL pagination](https://docs.github.com/en/graphql/guides/using-pagination-in-the-graphql-api),
[GitHub CLI API](https://cli.github.com/manual/gh_api),
[daily billing usage summary](https://docs.github.com/en/rest/billing/usage), and
[Actions runner billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
The user billing summary requires Plan read permission; organization billing
requires Administration read. Repo reads require Pull requests, Issues read.
GitHub's billing endpoints are preview and can change; unknown is intentional.

## Optional daily CloudRoom usage export

The cloud CLI exposes no daily usage/billing endpoint here. A caller with a
read-only daily usage source can supply `--usage /path/to/daily-usage.json`.
This is the tool's **interchange format**, not a claimed `room-cli` response.
Use day-specific deltas from the source, never lifetime counters or estimated
prices. `complete: true` is the caller's assertion that the export covers all
factory threads and cloud time in this repository for that UTC day. Do not use
it for partial samples. The tool validates the format; it cannot verify that
assertion or the provenance of this export.

All keys shown are required, with no extras. Each provider has a list of unique
threads, with nonnegative integer `tokens`, numeric `credits` and numeric `usd`;
any unreported unit is `null`. Sandbox `hours` and `usd` likewise accept null.
An empty provider list explicitly means no usage. A missing unit on **any**
thread keeps that provider's entire unit total unknown. Invalid, unreadable,
wrong-day or incomplete exports make all CloudRoom costs unknown with a reason.
The source file is never modified or copied. Output uses anonymous per-provider
ordinals; it never persists the supplied thread keys. Do not commit real exports.

Synthetic example:

```json
{
  "date": "2030-01-02",
  "complete": true,
  "claude": [
    {"thread": "synthetic-a", "tokens": 1000, "credits": 2, "usd": 1},
    {"thread": "synthetic-b", "tokens": 2000, "credits": 4, "usd": 2}
  ],
  "gpt": [{"thread": "synthetic-c", "tokens": 6000, "credits": 9, "usd": 6}],
  "sandbox": {"hours": 6, "usd": 3}
}
```

## Proof

`test.py` runs the public CLI against an exact-call fake `gh`, in isolated
private temporary directories, with synthetic records only. Its worked example
is independent arithmetic: 3 merges (01:15, 02:20, 04:30) / 24 = 0.125 per hour; gaps
10 + 45 + 20 + 90 + 10 = 175 minutes; biggest gap ticket #14 at 90 minutes;
$3 Claude + $6 GPT + $3 sandbox + $0.60 Actions = $12.60, or $4.20 per merge.
The completion regressions cap PR and ticket gaps at merge/closure, including
carry-in and stale starts after completion. Mixed billing regressions add a
synthetic $0.90 storage charge to $0.60 of hosted minutes: Actions stays at
12 minutes and $1.50, with $13.50/day and $4.50/merge for the whole factory.
It checks source failure as unknown, midnight clipping, linking, all three kinds
of pagination, tokens inherited without exposure, malformed input and SVG/table
values. Its build evidence is kept in the private record; tests read no private
evidence and need no Mac, live CloudRoom data or credentials.

Exit 0: metrics reported (cost sources may be unknown). Exit 1: untrustworthy
inventory/records or local I/O failure. Exit 2: bad arguments, before any read.
`FACTORY_METRICS_PY=/path/to/variant.py python3 tools/factory-metrics/test.py`
runs the proofs against a variant for a negative check.

## First-successful-push receipt (#2177)

Before the first push, choose a private durable `receipt_file` outside the
checkout and record its path in private resumable state. Run the normal push
with the existing hooks and approvals. Immediately after it succeeds, capture
its completion time and pushed head once. A failed push records nothing.

<!-- EB6 capture -->
```sh
git push origin HEAD &&
push_at=$(date -u +%Y-%m-%dT%H:%M:%SZ) &&
push_head=$(git rev-parse HEAD) &&
printf 'First successful push: %s at %s\n' "$push_head" "$push_at" > "$receipt_file"
```

Keep that receipt across retries and restarts; never replace its timestamp on
subsequent pushes, force updates or review fixes. After opening the ticket's
PR, set `pr` to its number and post that captured file on the PR, then read the
comment back. Before retrying a failed comment write, read the PR's comments;
reuse an identical existing receipt rather than posting again. Keep any
unposted receipt privately if PR creation fails. Never reconstruct a lost
receipt from PR creation, commit dates, CI starts or the current head.

<!-- EB6 receipt -->
```sh
gh pr comment "$pr" --body-file "$receipt_file"
```

The exact single-line receipt is a sourced builder observation with partial
historical coverage, not a GitHub push-event timestamp. Only unedited receipts
are collected; conflicting first-push timestamps stay unknown. A missing or
unavailable receipt remains unknown. Historical surviving receipts use the
same rules; GitHub's truncated event feed, PR-created time and commit timestamps
cannot establish complete first-push history and are never substituted.
No receipt establishes live improvement, experiment assignment or merge authority.

## Outcome sidecar and explicit defect evidence (#2177)

`collect --with-outcomes` also writes `outcomes.json`; ordinary v1 collection,
checking, bench and CF4 output stay unchanged. The local export contains exactly
`journey` (EB5's `closedwiz.journey.outcomes.v1` sidecar), `sources` (its separate
source map), and `defect_policy` (null until predeclared). The journey hash binds
the exact v1 file. `bench journeys.json --outcomes outcomes.json` adds per-PR
outcome rows, retaining open/closed/unmerged PRs, independent rounds, unknown
attribution and follow-up. `outcome_rows` is the EB8 seam; it assigns no work.

`collect --previous DIR` validates that directory's two files and retains
established push/merge/defect observations even if their source disappears from
a later read. It refuses removed known tickets/PRs, changed merge facts or
conflicting first-push assertions. Keep the prior source evidence privately.
Coverage and attribution resolutions append; they cannot regress or reset.

Declare the EB5 defect policy before collection/comparison with
`--defect-policy FILE` (also on `trends.py collect`): `rule` is
`explicit-causal-fix-link-v1`, `followup_hours` is positive, `deduplication` is
`root-cause-per-merge`, `unknown_attribution` is `retain-unknown`. Resumption
requires the same policy. This is neither live approval nor preregistration.
No policy means unknown defect follow-up, never zero defects.

A source curator records these exact one-line JSON forms in comments on the
causing PR, using synthetic examples here. `policy` is EB5's canonical digest of
the predeclared policy. The record is an explicit causal assertion, independently
reviewable through its source; the collector cannot establish causality itself.
The root is the defect issue number, shared by a main failure, reruns and its
later fix. A later fix alone or a CI-selector escape is not a skill defect.

```text
EB defect: {"policy":"<64 hex>","root":4901,"at":"2030-01-02T07:00:00Z","attribution":"unknown","evidence":"https://github.com/example/factory/actions/runs/7901","kind":"main-red","caused_by":4201}
EB defect: {"policy":"<64 hex>","root":4901,"at":"2030-01-02T09:00:00Z","attribution":"unknown","evidence":"https://github.com/example/factory/issues/4901","kind":"later-defect-fix","caused_by":4201}
EB attribution: {"policy":"<64 hex>","root":4901,"at":"2030-01-06T06:00:00Z","attribution":"attributable","evidence":"https://github.com/example/factory/pull/4201#issuecomment-8901"}
EB follow-up: {"policy":"<64 hex>","observed_until":"2030-01-04T06:00:00Z"}
```

A main-red citation may name a run or an exact `/attempts/N` URL. Collection
verifies the run id, attempt number, main branch, push event, CI workflow and
original run timestamp. A run-only citation reads historical attempts in order
and retains the earliest verified failure/timed-out attempt's URL in the source
map alongside the run and causal comment. A successful later rerun cannot erase
that failed attempt. A pinned citation must identify that exact failed attempt;
it cannot fall back to a different one. Failed, missing, mismatched or incomplete
historical-attempt reads refuse collection. No run/attempt identity is guessed.
The attempt endpoint is [GitHub's read-only workflow-attempt API](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run-attempt).
A later fix needs a merged closing PR for its root issue
in the existing complete PR inventory. Neither chronology nor either citation
alone supplies attribution: `attributable` requires the causal source to
explicitly attribute the defect to this evaluated skill change; when that
judgment is unavailable the curator records `unknown`, later resolved with a
separate append-only attribution comment. `unattributed` is an explicit negative
judgment, not missing evidence. Different judgments cannot overwrite an event.
Repeated observations count one root per merge. Before its first export the
canonical observation prefers a verified main-red signal over a later fix,
then the earliest observation within that kind (source URL breaks ties),
independently of comment reporting order. A sourced attribution resolution may
cite either verified causal observation of that same root; the original unknown
attribution is retained and the resolution appends separately.

Resumed collection never rewrites an exported event. If a root already exported
as a later fix gains a newly verified main-red signal, collection refuses before
writing: the append-only contract cannot silently discard or replace that harm
signal. Keep the last good artifacts and ask on the ticket for the contract
owner's disposition; only its approved representation can resolve that case.
No contract field or attribution policy is changed here.

Only events in the inclusive merge-to-merge-plus-followup window enter this
merge's defect guard. Later resolutions may settle attribution after that
window without relocating the original event. Edited/malformed evidence,
failed citations or changed policy refuse the collection before output.
The follow-up comment attests audited source coverage under that exact policy;
it must be no later than comment creation. No such attestation means coverage
unknown even if reads succeeded. Maturity starts inclusively at the frozen
window end; it does not settle unknown attribution. Attestations are evidence
to inspect, not an automatic claim that surviving GitHub history is complete.

JSON decimal follow-up hours (for example `48.0` and `48.5`) retain the contract's
positive-number semantics through collect, bench/report read-back and resume.
The validated policy is normalized only at the EB5 numeric call/comparison
boundary; source hashes, frozen policy identity and invalid-value refusals stay
in force.

## Stage-limit settings and reader (#2336)

Edit the five assignments in [limits.conf](limits.conf), in minutes, then read
the settings used without changing code:

```sh
python3 -I tools/factory-metrics/limits.py
python3 -I tools/factory-metrics/limits.py --settings /tmp/synthetic-limits.conf
python3 -I tools/factory-metrics/test_limits.py
```

The JSON reports all five loaded values under `minutes`, with schema
`closedwiz.factory-limits.v1`. Python consumers call `limits.py`'s `read(path)`;
see [limits-contract.md](limits-contract.md) for the exact grammar and interface.
Missing, malformed, duplicate or unknown settings refuse the whole read; the
CLI exits 1 with empty stdout. No fallback or unlimited interval is implied.
This settings seam is for the downstream journey benchmark and finite ops
consumers; stage-wait measurement belongs to #2337. Reading settings performs
no GitHub/CloudRoom action and grants no authority to start, replace or merge.

## Stage waits against the limits (#2337)

Benchmark the five stage waits from the same journey collection, then read
them against the current settings:

```sh
python3 -I tools/factory-metrics/journey.py collect --repo OWNER/REPO --ticket N --stage-waits --out DIR
python3 -I tools/factory-metrics/journey.py bench DIR/journeys.json --stage-waits DIR/stage-waits.json
python3 -I tools/factory-metrics/journey.py bench DIR/journeys.json --stage-waits DIR/stage-waits.json \
  --settings /tmp/synthetic-limits.conf
```

`collect --stage-waits` adds two read-only queries per ticket (label history;
current labels and native blockers) and one read of each PR branch's push
activity, and writes `DIR/stage-waits.json` beside the unchanged
`journeys.json`. `bench --stage-waits` adds `stage_waits`: each interval's
observed wait (or its range, when an end record was edited), its limit,
`missed`/`not missed`/`pending` or why it is `unknown`, `gated` or `stale`, its
ticket and source links, and per-stage denominators. Edit `limits.conf` and
rerun `bench` to see the same waits against new goals; nothing is re-collected.
Use `--as-of` on `collect` for a fixed read time. Limits: only records GitHub
still shows count, so history stays unknown; clocks start only at evidenced
gates (plan approval, merged blockers, pushed and green heads, valid
approvals); held time restarts the clock; missing or unproved endpoints stay
Unknown. The output holds links and numbers only, and a miss authorizes no
action. Endpoint rules and the vocabulary are in
[journey-contract.md](journey-contract.md), section 10;
[fixtures/stage-waits/](fixtures/stage-waits) is a synthetic, sanitized
demonstration.
