## Contract and suite seam (WR1)

The [v1 contract](contract.md) and [record schema](record.schema.json) pin one
snapshot and the explicit unavailable provider slots for spec #2340.
Composition/checking is finite and offline; it starts no collector or schedule.

```sh
python3 -I tools/war-room/test_contract.py
python3 -I tools/war-room/suite.py check tools/war-room/fixtures/contract/known.json
python3 -I tools/war-room/suite.py compose --at 2030-01-02T12:00:00Z
```

Later adapters pass projected provider records to `compose`; history/page and
weekly consumers call `validate`/`load`. Missing providers stay visible with
their exact prerequisites. Source freshness, incomplete coverage and native
units survive assembly. Fixtures prove the seam only; live operation, access,
hosting, source completeness and actual category observations remain Unverified.

## Rework category (WR6)

`rework.py` projects existing, validated `closedwiz.journey.v1` bytes into the
`rework` provider accepted by `suite.compose`. It does not collect GitHub,
parse verdict text, run an eval or change a correction counter/recovery policy.

```sh
python3 -I tools/war-room/test_rework.py
python3 -I tools/war-room/rework.py tools/war-room/fixtures/rework/journeys.json \
  --source-path tools/war-room/fixtures/rework/journeys.json \
  --cohort merged-synthetic-day --pr 4201 --pr 4202 --pr 4203 --pr 4204 \
  --since 2030-01-02T00:00:00Z --until 2030-01-03T00:00:00Z \
  --observed-at 2030-01-03T00:00:00Z
```

The finite CLI prints one provider; it writes nothing. The callable seam is
`project(wire_bytes, *, source_path, cohort, merged_prs, since, until,
observed_at)`. Supply an independently named expected merged-PR inventory,
half-open UTC merge window and actual artifact read bound. `source_path` is a
sanitized repository-relative reference; SHA-256 binds the exact input bytes.
The suite checks the resulting source/unit/denominator arithmetic. Neither
hashes nor caller-supplied bounds certify source truth or complete history.

Each PR counts once, even when it closes several tickets. The existing journey
validator and `rounds_of` own independent/nonduplicate verdict identities;
WR6 never sums repeated per-ticket bench rows. Only unedited, pre-merge rounds
establish observed reviewed coverage and evidenced CHANGES. The displayed
CHANGES share divides PRs with at least one such CHANGES by observed reviewed
PRs, with both numerator/denominator and expected cohort retained. Reviewed
coverage separately divides reviewed PRs by evidenced merged PRs. Missing or
unprovable merges, edited/absent reviews and unanswered/edited fix rounds name
their prerequisites. No reviews means an Unknown share, not first-pass success.

Recorded fix rounds include unanswered rounds, once per source `(PR, round)`.
A separate count shows rounds with recorded unedited answers; an answer is not
proof of resolution. CI rerun attempts keep their native `(run, attempt)`
identity and appear as **CI rework**, separate from review corrections. Missing
CI records cannot establish zero total rework. Counts are observed lower
bounds; the observed-reviewed share is not an estimate of the missing cohort.

Journey v1 always has unknown historical completeness, so this provider never
claims known complete history, even with every requested PR present. No merged
denominator makes it unavailable. Source freshness remains unknown without a
source-owned validity bound. Page/history consumers can pass this provider to
the existing suite without a new record version. WR2 owns the separate journey
bench and skills-eval result/coverage slots: fixture/replay evidence stays in
those slots and cannot become actual independent review or live success here.
Existing first-time-approval and CF4 finding semantics are unchanged.

## Private page (WR2)

`page.py` renders one validated persisted suite record, in the six contracted
groups. It escapes text, allows only GitHub evidence links, has no script or
answer/send control, and shows source windows, timestamps, freshness, native
units, coverage and grey prerequisites. The bench inventory includes all four
additional categories and EB6–EB9 without asserting their experiments ran.
The HTML is a local file with owner-only permissions, separate from immutable
history. It is not an authenticated service, a deployed page or proof of access.

`history.read_all(root)` is WR7 #2351's read seam: chronologically sorted,
validated `openwiz.war-room.v1` records from `root/samples/*.json`. Missing
five-minute boundaries stay absent. `history.latest(root)` selects the maximum
sample identity, so old arrivals never regress latest. `history.save(root,
record)` validates the entire record before a durable create-if-absent; identical
duplicates are idempotent and different payloads for one identity refuse.
Temporary interrupted writes are not readable samples. There is no retention
cutoff or rolling deletion. Malformed saved history refuses preparation rather
than silently omitting its gaps. History records and page files are mode 0600;
the samples directory is mode 0700. Select a private parent directory too.

Concurrent processes publishing the same resolved page path share a persistent
owner-only lock file beside the HTML. Each publisher selects the latest sample,
renders and atomically replaces the page while holding that lock. Closing the
lock descriptor releases it after success or failure. Keep the lock file so
future publishers coordinate through the same inode.

## Source selection (WR2)

`sources.select(root, selections, at, previous=None)` reads **only explicit local
files**. It runs no collector, GitHub command, eval, usage read, scheduler or
server. A selection is an array of exact objects:

```json
[{"kind":"ci_bench","slot":"ci_bench","path":"synthetic/point.json","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","observed_at":"2030-01-02T12:00:00Z","evidence":["https://github.com/synthetic-owner/work/issues/4001"]}]
```

All values in this example are synthetic assumptions. The root contains already
obtained source artifacts. `path` is a relative path under it (symlink escapes
refuse); SHA-256 binds the exact bytes. `observed_at` must be the independently
established source observation/read bound, never file mtime or a substituted
tick clock. Selection metadata asserts provenance; WR2 cannot establish its
truth or recover a source's unknown history. Evidence links require review.
Native path-based validators read a private temporary copy of those pinned
bytes, avoiding a second read of a replaced artifact.

| Kind / slot | Selected existing source | Projection / limitation |
| --- | --- | --- |
| `ci_bench` | `point.json`, existing `bench.read_point` | Completed-window merges, capacity assumption, native minutes and separate list-rate estimate; no current pool count or invoice |
| `factory_metrics` | Existing daily `report.json`, strict native JSON/type readers | UTC all-base merge/day/hour counts and separate provider/unit totals; recorded idleness/history remains partial |
| `journey` | `journeys.json`, existing `journey.validate` / `bench` | Recorded ticket ready-to-first-merge hours; historical coverage remains unknown; no new verdict parser |
| `skills_eval` | Existing `score.json`, `trends.cf4_results` | Source-linked partial/null score readiness; a native time window and manifest/coverage binding are still required for numeric projection; no eval or transcript read |
| `credits` | Board `credits.jsonl`, `board.read_credits` / `spent` | Consecutive sampled credit drops with fixed-PST spans; partial approximations, not daily billing |
| `claude_usage` | Existing complete daily owner export, `metrics.read_usage` | Claude tokens, credits and USD stay separate; unreported units stay Unknown; usage keys are dropped |
| `board_graph` / `board` | Existing plan-links graph, native offline `--graph` checker and board measures/states | Source-linked partial/null points and ticket states; no copied title/body or invented numeric window |
| `board_history` / `board` | Existing board history or selected run-row fragment, native row validator | Latest native point timestamp retained, with partial/null measures; no fabricated historical interval |
| `decisions` | Existing structured decisions response, strict reader and native schema checker | Read-only request kind/currentness/source link, with partial/null value and actual source time; raw wording, target IDs and request keys are dropped |
| `projected` / any existing slot | Sanitized provider from its owning adapter | Passes the same suite/privacy/link checks; later WR3–WR8 providers need no page/schema change |

The native adapters copy selected numeric facts and fixed labels, never raw
comments, transcripts, diagnostics, credentials, thread identifiers or usage
keys. The additional text guard reuses the existing privacy rules and refuses
credential/id forms. Sanitizing a projected provider remains its producer's
responsibility; this pattern guard is not a claim to recognize every secret or
personal fact. Only sanitized providers belong in this preparation input.

The [WR2 point-observation disposition](https://github.com/jparker2006/ClosedWiz/issues/2346#issuecomment-6781074763)
authorizes the existing suite's partial/null representation: numeric value and
native window remain null, while the actual source timestamp, source hash/link
and explicit point-window prerequisite survive persistence. A representation
the validator cannot admit stays unavailable. Decisions require an exactly
representable oldest-source timestamp; unknown or subsecond precision is never
rounded into a fabricated source time. This preparation provides no answer
control or authority. Completed-window sources retain their native intervals.

Failed/partial artifact reads retain last good numeric evidence with explicit
partial state and prerequisite, preserving the original source observation,
window and validity bound. Omitted formerly selected providers are incomplete,
too. No source validity bound means unknown freshness, not five-minute freshness.
Missing direction evidence remains unclassified/grey; source metadata is never
used to reconstruct historical direction. Current CI/direction collection
belongs to WR8, and the other categories remain with their existing owners.

## Five-minute invocation (WR2)

```sh
python3 -I tools/war-room/test_page_history.py
python3 -I tools/war-room/main.py --at 2030-01-02T12:00:00Z \
  --source-root /tmp/synthetic-sources --selection /tmp/synthetic-selection.json \
  --history /tmp/private-war-room --page /tmp/private-war-room/page.html
```

This finite command floors the injected UTC time to a five-minute boundary,
composes every provider slot, atomically saves one complete envelope, renders
the latest saved sample and exits. A repeated boundary reuses the immutable
sample without reading providers again; a different payload supplied directly
to history for that identity refuses. A new out-of-order boundary is retained,
but its source fallback uses only older history. A page-write failure can be
repaired with the same tick after restart, without resampling. No missing
boundary is synthesized. The HTML reloads the same file every 300 seconds;
that reload creates no measurement. An external authorized caller may inject
ticks into `main.tick(at, history_root, page_path, read_providers)`; this ticket
does not install or run one. Actual five-minute operation remains Unverified.

Credit span identities use their native start/end timestamps and comparison
basis (`full-balance` or `extra-only`). Backfilling older samples preserves each
unchanged span's metric, cohort and observation identities. Subsequent samples
use these identities while retained historical records keep their original bytes.

Red logs and the rendered synthetic page/screenshot are in
`fixtures/page-history/`. They are offline fixture evidence, not a live result.

## Answer-time category (WR5)

`answer_time.project` returns the existing `answer_time` provider for
`suite.compose`; WR2's generic page/history consumer can use that slot without
another record format. It performs no source reads, saves no replies and starts
no tools, clocks or schedules. Run its synthetic category proof with:

```sh
python3 -I tools/war-room/test_answer_time.py
```

The selected cohort is recorded requests in the explicit half-open source window
`[since, until)`, with a separately supplied source observation bound. Unknown
request times remain in the named cohort's denominator. Every request retains
one stable sanitized identity, ticket, interval, source reference and prerequisite.
Completed intervals have native seconds; open/unknown intervals have null values
and endpoints where unproved. The answered share uses **all recorded requests**,
with expected coverage separately nullable; open and unknown/censored counts stay
visible. Identical duplicates count once; conflicting identities refuse. No
median over only completed requests is presented as the whole cohort's latency.

The call takes sanitized in-memory request/disposition facts **after the source
owner's validation and artifact-binding checks**. These facts are not a new wire
schema, source authority or persistent answer store. `source` uses the suite's
existing path/schema/SHA-256 shape; `window`, `observed_at`, `cohort`, `expected`
and `history` pin the selection and its coverage. Request facts contain exactly
`id`, `at`, `reference`, `completeness`, `ticket`; disposition facts contain
`request` (the exact request reference), `kind`, `at`, `reference`, `completeness`.
The fixture documents these **synthetic assumptions**, not observed native fields.
No body or response text is an input. Only independently sourced, linked,
unchanged substantive dispositions with ordered, observed times can close a pair.
Sent/accepted notifications, label removal and resolved status cannot do so.
Edited/deleted or missing provenance and ambiguous answers remain censored;
syntactic validity cannot establish provenance truth or complete history.

For an already measured identical interval, `timings` accepts the **existing
suite metric shape**, preserving its source, sample, native value/unit, window
and observation time rather than computing another wait. Interval identity,
endpoints and independent evidence must match. This leaves reuse for WR3 after
the actual TL2 producer exists; it declares no TL2 native fields or parser.
Conflicting non-null request/timing ticket identities refuse reuse; null ticket
attribution stays unknown and does not replace the source's native fact.

Current wider-source readiness uses `answer_time.unavailable()`: decisions v1
exposes open requests without substantive-answer timestamps; fleet notifications
prove delivery only; journey v1 has no answer interval and history is unknown.
TL2's actual producer/contract is still a prerequisite. A caller must not invent
a disposition from these records or represent the synthetic fact shape as a
supported endpoint. The known 420-second example proves projection only. Wider
source availability, actual answer latency, complete history, private access,
hosting and operation remain **Unverified**.

## Cost category (WR4)

`cost.py` exposes `project(sample_at, *, journey=None, ci=None,
synthetic_allocation=None, assembled_at=None) -> provider` for the existing `cost` slot. Pass its
result to `suite.compose`; WR2 can render/save the resulting ordinary metrics
without a new record version. This finite projection invokes no tools or source
collector. Run its synthetic proof with:

```sh
python3 -I tools/war-room/test_cost.py
```

A journey selection and a CI selection each contain `path`, `source_path`,
`observed_at` and `evidence`. `path` names an explicitly selected local journey
JSON file or CI `point.json`; `source_path` is its sanitized repository-relative
artifact identity. The caller supplies the independently established observation
bound and sanitized GitHub evidence links. The adapter hashes the exact selected
bytes, uses the existing `journey.validate` or `bench.read_point` validator, and
checks the whole output through the suite. It cannot authenticate a supplied
observation/evidence assertion. Native event/window ends must not exceed that
observation. `assembled_at` is an explicit injected assembly time, defaulting
to the sample boundary when omitted. It permits observations after the tick
through that assembly time without changing source timestamps or the sample.
No new freshness timeout is invented.

Journey `daily_usage` reuses the factory usage reader's UTC totals and native
six-decimal day ratios. Independent producer rounding of the total and raw
quotient is validated against their rounding bounds, with the existing producer
checking a possible raw value; no unrounded value is retained or invented as an
observation. Claude/GPT USD, credits and tokens, and sandbox hours
remain separate series. Day ratios divide **all daily work** by the day's merges,
across all base branches; they are never PR attribution. Non-USD ratios keep the
native unit with an explicit per-merge label. An unrepresentable rounded USD
quotient is unavailable with its prerequisite, rather than silently rounded into
an exact suite ratio. No merges leaves the ratio unavailable. Ticket and shared
parent usage are separate **thread-record lower bounds**: missing days, helpers,
unrecorded work, sandbox/CI and history gaps remain explicit. Shared parents and
PR identities are each counted once in the selected journey document. Lower
bounds use each entity's contributing full UTC export days: a spec's own timed
events, or a ticket plus its linked PRs, under the existing journey day rule.
Observation and assembly times never extend those usage windows. Missing export
days remain prerequisites; absent dated entity coverage makes the unplaceable
amount unavailable. A rejected-export sentinel retains a source prerequisite
with its rejected count and unknown date/coverage alongside valid daily values.

CI window USD remains a **list-rate estimate**, with source window, price
verification dates and exclusions. Latest-attempt completed CI jobs do not cover
other workflows, reruns, storage or the whole bill. Native UTC windows and full
fixed-PST day boundaries are retained. CI2 micro-USD bill context has no adapter
here; it supplies no complete cohort allocation or conversion authority.

None of those native sources provides complete all-in attribution. The `all-in`
metric therefore stays unavailable (grey/Unknown), naming the exact missing
models, shared-parent, helper, sandbox and CI allocations and the unique merged
cohort prerequisite. Known daily values and lower bounds remain visible beside
it. Unknown units and zero denominators never become zero cost.

`synthetic_allocation` is an **in-memory worked example only**, shown in
[fixtures/cost/allocation.json](fixtures/cost/allocation.json). It accepts only
`evidence_class: synthetic` and cannot be combined with native selections. Each
USD charge already belongs wholly to its stated PR subset; the adapter invents
no allocation rule. Disjoint rows of each component cover one named merged-PR
cohort, and every charge identity occurs once globally. Overlapping coverage,
foreign/repeated PRs, mismatched windows, unknown components and other currencies
refuse. A missing/null/incomplete component leaves all-in Unknown. Component
coverage is reported separately from the merged denominator. Its derived source
hash binds the canonical normalized example facts, including each row's source
assertions; it is not a claimed native export identity. Synthetic completeness
proves only arithmetic ($12 / 2 = $6), never real attribution or invoice coverage.

## TL stage consumer (WR3)

`stage_waits.py` projects the merged producers into the existing `stage_waits`
slot through `suite.compose`; WR2's tick saves it and draws it on the page with
no new record format. It reads three explicit local files once each: TL2's
`journeys.json`, its bound `stage-waits.json` sidecar and a TL1 `limits.conf`.
TL2's `validate_stage_waits` and TL1's `limits.read` check them first, and TL2's
own `stage_bench` computes every wait, result and miss: this file adds no timer,
settings owner, source parser, recovery or effect.

```sh
python3 -I tools/war-room/stage_waits.py --at UTC_TIME --root DIR --journey journeys.json \
  --sidecar stage-waits.json --settings limits.conf --settings-evidence URL \
  --cohort-since UTC_TIME --settings-read-at UTC_TIME   # prints a projected provider
python3 -I tools/war-room/test_stage_waits.py
```

The printed provider is a `projected` source for `sources.select`. Per stage it
shows the loaded limit (`limit:<stage>`, TL1 source), the interval denominator
(`intervals:<stage>`) and one count per TL2 result (`missed`, `not-missed`,
`pending`, `unknown`, `gated`, `stale`), all partial because TL2 history is
unknown. Each interval is one `wait:<key>` metric with TL2's endpoints, ticket,
PR and source links; each TL2 miss is one `miss:<key>`. Ids are TL2 keys
lowercased. The value is TL2's wait, timed from its clock with held time
excluded, so it can be shorter than the interval's endpoints. An ended wait with
one exact end is known; an open wait or an edited end keeps TL2's lower bound as
partial; Unknown, gated and stale stay grey with TL2's own gap, never a miss.
A miss on a PR shared by several tickets has no single ticket: it counts once,
and each ticket gets a non-counting `miss-ticket:<key>:t<N>` reference (partial,
null value) with that ticket and the same interval. A missing or refused
journey, sidecar or settings file makes the whole slot unavailable with that
prerequisite; it is never read as unlimited or zero.

Times and windows come only from their own sources. Waits and misses are
observed at TL2's `read_at`, each over its own span from its TL2 start to that
read. TL2 chooses no collection window, so the counts and limits use
`[--cohort-since, read_at)`, the caller's established start for the tickets it
named; without it, or when a TL2 record falls before it, they stay grey. Limits
are observed at `--settings-read-at`, the caller's read of the settings, and
stay grey when that time is missing or earlier than TL2's read.

The proofs use TL2's own demonstration fixture and vary only the settings, so
each stage is seen at, below and above its limit. They prove the projection,
not live waits: collection, complete history and operation stay Unverified.

## Current CI and throughput source projection (WR8)

`activity.project(at, *, repo, read_started_at, source_path, pools=(),
ci_read=None, pr_read=None, ticket_read=None)` returns `(provider, observation)`.
The second value is canonical sanitized JSON **bytes**; retain them unchanged at
`source_path` alongside the provider before passing it to `suite.compose`.
Every metric's source hash binds those bytes. Source paths must meet the suite's
relative-path contract. No source is called unless its reader is injected.

The existing supported seams are `bench.gh` for CI REST GETs,
`metrics.collect_prs` for all PR/closing-link pages, and `metrics.graphql` for the
additive fixed closing-ticket metadata query. These are adapter capabilities,
not activation instructions. The new CI helper uses `bench.pages`,
`runner_kind`, `read_prices` and `costs`; historical collection, daily/journey
queries, billing and publication are unchanged. Read bounds are caller-supplied
actual source bounds, never assembly time; there is no invented freshness TTL.

Current CI observes **ci.yml only**, including active runs created before today.
It requires complete run/job enumeration, equal bracketing reads and stable
attempt/status identity. The reused reader's 1,000-item limit is explicit: an
unbounded repository history above it stays grey pending a complete supported
source observation; no history is silently dropped. Exact pool selectors are
those already recognized by the CI bench; `closedwiz-pc` takes precedence over
its generic `self-hosted` tag. Conflicting selectors, unsupported extra labels,
missing labels/status, carried-over attempts and partial/duplicate pages make
counts Unknown. A missing runner says nothing about queue or pool. Selected
pools do not assert a complete runner inventory. Equal reads cannot establish
an atomic GitHub snapshot or recover changes between observations.

Throughput is this UTC calendar hour/day **so far**, over factory metrics'
all-base-branch merged cohort. It joins actual same-repository closing tickets,
using the board's Polish -> version milestone -> side-group precedence. One PR
counts once when all its linked directions agree; conflicting/unlinked/missing
metadata remains Unknown. Labels are fully paginated. Classification is
explicitly **current ticket metadata**, never historical direction evidence.
At the exact hour/day boundary the empty interval is unavailable. Complete empty
lists without a native source evidence link also stay grey rather than inventing
an evidence identity for zero. Neither titles nor raw labels/errors are retained.

CI cost is separately labelled a **partial-day list-rate estimate** for the latest
completed ci.yml runs created today. Running jobs, earlier attempts, other
workflows, storage, PC hardware/power and add-ons are excluded. The existing
per-job rounding, USD rates and their verification dates survive in the bound
observation. It is neither billing nor all-in PR allocation; the separate billing
metric stays grey pending complete day-specific existing billing evidence.

```sh
python3 -B -I tools/war-room/test_activity.py
```

The fake-gh source-to-suite proofs cover counts, pagination, attempts, exact
pools, direction joins, duplicates, scope, privacy and calendar boundaries.
Fixtures establish offline behavior only. No source collection, scheduling,
installation, hosting, access rule, account operation or publication is activated.

## Publish (WR9)

Jake bookmarks **<https://github.com/jparker2006/ClosedWiz/tree/war-room>**: a
branch `war-room`, never `main`, holding `war-room.png` (the page, 1200 px),
`war-room-phone.png` (the same page in one 400 px column, drawn at 2x, which a
phone narrower than 700 px shows instead through the README's `<picture>`, as
the board does), `samples/` (WR2's immutable five-minute envelopes) and a
`README.md` with the time of the last good render, the pictures and a
Benches table: every slot, its state and how many of its values are measured,
as text a phone reads natively.

- **The job:** [`.github/workflows/war-room.yml`](../../.github/workflows/war-room.yml),
  beside `board.yml`, on GitHub-hosted `ubuntu-24.04` for all three jobs, never
  `vars.CI_RUNS_ON`. A pull request runs `proof` (`test_publish.py`) and a
  `preview` (tick and draw on an empty history, no publish). A dispatched or
  scheduled run from `main` is the `publish` job alone: `publish.sh` runs
  `test_publish.py` first, then `publish.py publish`. Only `publish` has
  `contents: write`, it pushes only `refs/heads/war-room`, and the
  `war-room-publication` concurrency group serialises it.
- **Default off:** `publish` runs only when the repository variable
  `WAR_ROOM_PUBLISH` is `on`, so after merge neither the backup cron nor a
  dispatch publishes or spends a minute. Activation is the orchestrator's
  step: `gh variable set WAR_ROOM_PUBLISH --body on --repo jparker2006/ClosedWiz`
  (and `--body off` to stop). Pull request proof and preview are unaffected.
- **One run:** check out `war-room`, refuse any entry that is not a plain file
  with the page's own names (a link, an executable or anything else), and any
  sample ever changed, removed or renamed in its history, merge resolutions
  included; copy the saved samples into a
  private history, run one `main.tick` at the run time (floored to its
  five-minute boundary; a repeated boundary reuses its sample), draw both
  pictures with chromium, privacy-scan every file to publish, then commit only
  added samples and push without force. A failed test, read, render, scan or
  push publishes nothing, so the page keeps its last good state and time. A
  selected artifact that is missing or fails its hash or validation is a failed
  read here: WR2's partial-evidence fallback is kept for `main.py`, but a
  publication refuses rather than advance the last good render.
- **Two cadences:** collection every five minutes, publication every hour.
  `publish.py collect --remote URL --at UTC [--source-root DIR --selection FILE]`
  runs the same tick without drawing and commits only the new sample to
  `war-room` (a boundary already saved commits nothing). The hourly publish
  carries every collected sample forward unchanged and renders the latest; a
  boundary that was not collected stays absent. Both push without force, so
  when they meet, the later push fails and publishes nothing; the next run
  carries on.
- **Privacy scan:** every sample is validated with `sources.safe_record`; the
  README, each sample and the page the pictures are drawn from pass the
  existing privacy checker and the credential/thread-id guard; pictures must be
  PNGs. A pattern guard cannot recognise every private fact: sources must
  arrive sanitized, as the suite contract requires.
- **The pictures (#2565):** each value's card shows its label, value, state,
  window, freshness, statistic and dimensions, so cards that share a label stay
  apart; its provenance, interval, prerequisites and evidence links are left
  out of the pictures (they stay in its published sample), and each bench's
  own prerequisite stays. A picture taller than 65,000 device px (CSS height times
  scale) is refused as too tall, and a zero height as no picture. The full
  gathered page of 2026-11-13 was 57,625 CSS px with those details, so the
  2x phone picture was refused on every main publish. Chromium draws with
  enough tile memory to paint the whole picture: by default it left a tall,
  dense page blank below about 46,700 px.
- **Sources:** `publish.sh REMOTE [--source-root DIR --selection FILE]` takes
  the WR2 selection. The workflow selects none yet, so every bench shows
  Unavailable with its prerequisite until an approved collection supplies
  selected artifacts on the runner.
- **The loops (the orchestrator activates them; nothing here creates them):**
  two script-only CloudRoom loops, which print nothing and so start no agent
  unless a run fails. The collector runs in its loop sandbox's ClosedWiz
  checkout and spends no Actions minutes; the hourly loop dispatches the
  workflow:

  ```sh
  room-cli loop create --name 'War room collect' --cron '*/5 * * * *' --timezone UTC --new-thread \
    --script 'python3 -I tools/war-room/publish.py collect --remote https://github.com/jparker2006/ClosedWiz.git --at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null 2>&1 || echo "War room collection failed"' \
    --prompt 'The War room five-minute collection failed. Read the error, report it, change nothing.'
  room-cli loop create --name 'War room hourly' --cron '37 * * * *' --timezone UTC --new-thread \
    --script 'gh workflow run war-room.yml --repo jparker2006/ClosedWiz --ref main >/dev/null 2>&1 || echo "War room dispatch failed"' \
    --prompt 'The War room hourly dispatch failed. Read the error, report it, change nothing.'
  ```

  Give each only the GitHub credential its script needs (`--secrets`): the
  collector pushes `war-room`, the hourly loop dispatches. Add the selection
  arguments to the collector once an approved collection supplies artifacts.
  The thin backup cron, `37 */6 * * *`, keeps the page within six hours if the
  hourly loop stops.
- **Cost basis, per run:** one GitHub-hosted Linux job of about a minute,
  billed per job rounded up to the minute at the list rate in
  [`tools/ci-bench/prices.tsv`](../ci-bench/prices.tsv) (`github-hosted`,
  $0.006/minute, verified 2026-11-05): 24 dispatched plus 4 backup runs is about
  28 minutes, about $0.17 a day before any included minutes. A pull request
  run is two jobs. Each publish also adds pictures to the branch's history:
  about 11 MB for the full gathered page of 2026-11-13 (#2565), against about
  1.5 MB for the synthetic page (the board adds about 1 MB).
  The five-minute collection runs in a CloudRoom sandbox, not on Actions; each
  collected sample adds about 4 KB to the branch.
- **Gaps:** live collection, publish, dispatch, both loops and Jake's view on a
  real phone are Unverified until activation; the virtual-time proof shows an
  hour's twelve boundaries surviving publication, not a live hour.

```sh
python3 -I tools/war-room/test_publish.py
python3 -I tools/war-room/publish.py preview --out /tmp/war-room --at 2030-01-02T12:03:00Z
```

Red runs (first and review round 1), green runs and a synthetic render (`synthetic/`) are in
`fixtures/publish/`: offline fixture evidence, not a live result.

## Weekly report (WR7)

`weekly.py` compares two adjacent seven-day stage cohorts from retained history,
as the contract's weekly seam says: `[end-14d, end-7d)` and `[end-7d, end)`,
`end` the latest fixed-PST day boundary (08:00 UTC) at or before `--at`. It reads
only `history.read_all(ROOT)` and an optional local recorded-changes file, and
prints the report; it writes nothing, opens no socket, starts no program, reads
no clock and runs no collector, eval or schedule.

```sh
python3 -I tools/war-room/test_weekly.py
python3 -I tools/war-room/weekly.py --history DIR --at UTC_TIME \
  [--changes tools/war-room/fixtures/weekly/changes.json] [--format json|markdown]
```

The callable seam is `report(records, at, changes=())`; it validates every
record itself and refuses differing payloads for one sample identity. Each week
shows observed/expected samples (2016), its gaps and seven fixed-PST days (288
each). Per stage it shows samples carrying stage data, the loaded limits, the
source windows with their own `UTC` labels, the wait basis, and interval counts:
completed, open (censored), unknown endpoint and conflicting; expected is null,
because the stage source does not establish its complete cohort.

Each native interval id counts once across all its five-minute snapshots, in
the week of its source-backed end; open and unknown waits are counted in the
week of their last snapshot and never become values. Snapshots that disagree
about one interval make it conflicting. Waits pool into ci-bench's exact
`trends.distribution` (n, mean, median, p90, sample SD, histogram).

`change` is `faster`, `slower` or `unchanged` (latest against previous median)
only when there is no reason against it: every sample present in both weeks,
stage data in each, one known limit, basis and source window that match across
the weeks (skills-eval's like-with-like rule), n >= 3 completed waits in each
week (ci-bench's thin rule), and no open, unknown or conflicting wait.
Otherwise it is `unknown`, with each reason listed. No threshold is added.

Recorded changes are exact `{"at", "label", "evidence"}` objects: a UTC time,
a short label in a plain character set that passes the privacy checker, and
GitHub source links. Limit and source-window changes read from history are
listed too. Each is placed in its week beside the comparisons, marked
`temporal only`: no change is claimed as a cause. Changes outside both weeks
are counted, not shown.

Proofs generate synthetic histories in virtual time (`fixtures/weekly/`);
`red-first.log` is the failing-first run. They prove the comparison on saved
facts, not live weekly results, source completeness or any operation.

## Live sources (WR10)

The hourly publish job now gathers the real sources before it ticks. It runs
`publish.sh REMOTE --gather OWNER/REPO RUN_URL`, so the Publish section's "the
workflow selects none yet" no longer holds. `gather.py` writes a private
temporary source root and one selection in WR2's `sources.select` form. Each
artifact is pinned by sha256, its observed time and its evidence. The publish
then runs with `--source-root` and `--selection`, unchanged.

```sh
python3 -I tools/war-room/test_gather.py
python3 -I tools/war-room/gather.py --remote URL --repo OWNER/REPO --run-url RUN_URL --out NEW_DIR \
  [--pool LABEL ...] [--journeys journeys.json --cohort cohort.json] [--answer-time provider.json]
```

| Card | Source, read only | Observed time and evidence |
| --- | --- | --- |
| Board | `history.jsonl` on `board`, checked by the board's own row validator. The latest row's six counts are **partial**, in the board's daily window (`[PST day start, min(commit, next PST day))`), each a level at the sample time. The startable percent and fed ratio need ticket identities from a `graph.json` of the same read, so without one they stay Unknown with that prerequisite | The `board` commit's time and link |
| Credits | `credits.jsonl` on `board`, through WR2's native `credits` adapter | The `board` commit's time and link |
| CI bench | The `windows/*/point.json` on `ci-benchmarks` with the latest `until`, through WR2's `ci_bench` adapter | The `ci-benchmarks` commit's time and link |
| Current activity | WR8's `activity.project` with the existing `bench.gh`, `metrics.collect_prs` and `metrics.graphql` readers. `ci.yml`'s whole run history is over the API's 1000-item limit, so its run list is read bounded (`gather.current_runs`): the active runs, one status at a time, and the completed runs created this UTC day, the only runs WR8 uses. Each listing keeps `bench.pages`' checks; a run listed twice or under another status refuses the CI counts. Its observation bytes are kept beside its provider. Pools default to `closedwiz-pc` and `ubuntu-24.04` | The read's end, and this run's link |
| Ticket journeys, rework, cost | `journey.py`'s `collect` for the tickets closed by the merged cohort, then WR6 `rework.project` and WR4 `cost.project` (journeys and the CI point). The cohort is the PRs merged in the latest complete UTC hour that has a merged PR closing a ticket, looking back up to 6 hours | The read's end, and this run's link |
| Answer time | WR5's own projection when one is supplied, otherwise `answer_time.unavailable()` and its exact prerequisites. No recorded-answer source exists yet | This run's link |

- **One card, one reason.** Each source is read through the same `sources.select`
  the publish runs. If a source is missing, unreadable or invalid, it is not
  selected. Its card gets a projected unavailable provider naming the source and
  its prerequisite, never a bare Unavailable, and the other cards keep their
  values. The WR9 publish still refuses any selected source that fails, and
  gather selects only sources that passed.
- **Privacy.** Every gathered artifact passes the existing privacy checker and
  the credential and thread-id guard (`publish.text_scan`) as it is written, and
  again before the selection is written: its bytes, then every JSON string
  literal (keys included) as it decodes, so an escape such as `\u0067` hides
  nothing. A string that cannot decode is a hit too. One hit refuses the whole gather, so
  nothing is selected or published. The board graph's ticket text is used only
  in memory and never written. The publish's own scan of every published file is
  unchanged.
- **Reads only.** `board` and `ci-benchmarks` are fetched (depth 1) and never
  pushed. The `gh` reads are GETs and fixed GraphQL queries. The publish job adds
  `actions`, `issues` and `pull-requests` read scopes for them and still
  pushes only `refs/heads/war-room`. It stays on GitHub-hosted `ubuntu-24.04`,
  and its timeout cap rises from 10 to 15 minutes. No dependency, runner,
  secret or loop is added.
- **Drawing.** A full gathered page is tall: the synthetic one is about 28,000
  CSS px on a desktop. `publish.draw` bounds the drawn picture, CSS height times
  its scale, at 65,000 device px, so the 2x phone picture binds at 32,500 CSS px.
  A taller or unmeasured page publishes nothing. `test_gather.py` publishes the
  full synthetic selection with the real chromium at both widths.
- **Gaps.** Board counts are point levels in a source-owned daily window, not
  measured intervals. The journey cohort covers a few hours, not a day. The CI
  bench shows its latest published window, which can be days old, and its
  observed time says so. Live values, the extra job time per run and the
  phone view stay Unverified until the post-merge publish run.

Red and green runs are in `fixtures/gather/`, which also holds the synthetic
`history.jsonl`, `credits.jsonl` and `cohort.json`. The test builds the
`board` and `ci-benchmarks` branches from these files, the page-history graph
and the cost CI point. It reuses WR8's synthetic gh, WR6's journeys and WR5's
pairs. All of these are offline fixture evidence, not a live result.

## Review loops bench (RL0)

`review_loops.py` measures the [review-loops contract](../../contracts/review-loops.v1.md)
(spec #2454) from already collected inputs: a cohort record, the EB6
collection's `journeys.json` and `outcomes.json`, the per-finding
classifications and, for AFTER, the watchdog event log. It reads no GitHub,
starts nothing and writes only what `project --out` names.

```sh
python3 -I tools/war-room/test_review_loops.py
python3 -I tools/war-room/review_loops.py check-report tools/war-room/fixtures/review-loops/report-ok.md
python3 -I tools/war-room/review_loops.py bench --cohort cohort.json --journey journeys.json \
  --outcomes outcomes.json --findings findings.json [--reports reports.json] \
  [--watchdog events.jsonl] > bench.json
python3 -I tools/war-room/review_loops.py compare before.json after.json [--safety-escapes escapes.json]
python3 -I tools/war-room/review_loops.py project bench.json --journey journeys.json \
  --source-path SANITIZED/journeys.json --bench-path SANITIZED/bench.json \
  --observed-at UTC --evidence https://github.com/OWNER/REPO/issues/N --out DIR
```

- **bench** prints each measure with n, Unknown and coverage, plus mean,
  median and p90 where they apply, the cohort's PR list and each missing PR
  with why. Rounds are distinct heads among the journey reader's independent,
  nonduplicate, unedited pre-merge verdicts (WR6's admission); a PR with none
  is Unknown. Push timing and defects come from EB6's outcome rows and
  `outcome_cohort`: no receipt is Unknown, immature PRs stay out of the rate.
  PR-opened-to-merge hours are labelled separately and never replace push
  timing. Only the contract's frozen 72-hour defect policy is accepted. A
  judgment classification must name a high or medium journey finding and its
  exact report link; a line classification must name a new blocking finding
  of an admitted round's report in `--reports`. A round without its report
  leaves the share unavailable.
- **check-report** refuses a blocking finding with neither a `User path:` nor
  a `Risk:` line, a polish finding without its `Polish issue: #<n>`, a verdict
  that disagrees with the open blockers, and a `Next:` line outside the 1 + 1
  states. It exits 0 with `report ok`, or 1 with one problem per line.
- **compare** prints BEFORE against AFTER for every measure, the 1.5-rounds
  target (`met`, `not met`, `unknown`) and the rollback trigger
  (`triggered`, `not triggered`, `unknown`), for RL4.
- **project** writes the `rework` provider (WR6's own projection plus rounds
  per PR and the real-user-path share) and the `eb6` provider (push and
  opened-to-merge hours, the escaped-defect rate, immature and unknown
  follow-up PRs), with a `projected` WR2 selection for `publish.py collect`.
  Every metric stays partial: journey history is unknown.

The suite's evidence links accept a run, not a run-attempt URL, so WR6's
projection refuses a journey whose CI sources cite `/attempts/N`.
Fixtures in `fixtures/review-loops/` reuse EB6's own journey fixture and are
synthetic; `red-first.log` records the missing seam before the module, and
`red-assertions.log` each acceptance proof failing at its own assertion with
its one rule undone, and `red-review-r1.log` review round 1's proofs (R1 to
R3) red before their fix. `rework-outcomes.json` is a synthetic 72-hour EB6
sidecar over WR6's three-PR rework journey (one defect in three mature PRs). The BEFORE run (RL0b, #2571) keeps its bundle private in
`private/evidence/review-loops/before/`.
