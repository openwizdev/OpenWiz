# Value meter v1 (`openwiz.value-meter.v1`)

VM1 of spec #3289. This contract pins the opt-in config, the per-PR record, the
report, the anonymized aggregate, the unknown-versus-zero rules, and the HTML
section seam. VM2 through VM6, in WizRoom, build against it. Nothing here
reads GitHub, renders a page, or uploads telemetry.

**This contract grants nothing.** It authorizes no opt-in on a real account,
no GitHub read, no ledger read, and no telemetry upload. A fixture that passes
proves the documents agree, never that a meter has run.

Where this prose and [`value-meter.v1.schema.json`](value-meter.v1.schema.json)
disagree, the contract is wrong and must be fixed. Rules a schema cannot see (duplicate keys,
case-insensitive repository and `(repository, pull_request)` uniqueness, records belonging to `reads`,
empty-source-list unconfigured behavior, window arithmetic, `known_count` against `total_count`,
how many weeks are numeric, cost-state coverage, a delta `total_count` of 2, the subtraction of the two
weeks, the derived delta state, and direction against the sign of the value) are stated here and checked
by `contracts/fixtures/value-meter/test_fixtures.py`.

## The pin

```json
{
  "schema": "openwiz.value-meter.v1",
  "authority": {"live": false, "github_read": false, "telemetry_upload": false},
  "defaults": {
    "enabled": false,
    "repos": [],
    "hours_per_merged_pr": null,
    "hourly_rate_usd": null,
    "share_aggregates": false
  },
  "windows": {
    "timezone": "fixed-PST",
    "offset": "-08:00",
    "boundary_utc": "08:00:00Z",
    "this_week": "[end-7d, end)",
    "last_week": "[end-14d, end-7d)"
  },
  "metrics": [
    "merged_prs",
    "hours_saved",
    "money_saved_usd",
    "cost_per_merged_pr_credits",
    "cost_per_merged_pr_usd"
  ],
  "partial_only": ["cost_per_merged_pr_credits", "cost_per_merged_pr_usd"],
  "states": ["known", "partial", "unknown"],
  "aggregate_reasons": [
    "unconfigured_repos",
    "unconfigured_rate",
    "incomplete_read",
    "no_merged_prs",
    "no_known_cost",
    "partial_cost_coverage",
    "upstream_unknown",
    "week_unknown",
    "week_partial"
  ]
}
```

Readers refuse a repeated JSON key, at any depth, before they apply the
schema. They also refuse a non-finite number (`NaN`, `Infinity`, `-Infinity`).
Those values are not in the fixtures; the proof builds them in memory.

## Config

`#/$defs/config`. The normalized object always carries every field. A file on
disk may omit a field and may write repository names in any ASCII case
(`OWNER/NAME`, matching `^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$`).
Before validation, the reader fills the pin's defaults, normalizes every
repository name to canonical lowercase (`owner/name`), and deduplicates `repos`
case-insensitively (preserving first-seen order).
`enabled` defaults to `false`. `share_aggregates` defaults to `false`.
`repos` defaults to `[]`. Both rates default to `null`.

| Field | Rule |
| --- | --- |
| `enabled` | Boolean. `false` means no GitHub read and no ledger read |
| `repos` | Zero or more canonical lowercase `owner/name` entries, each once. On disk any ASCII case is accepted; the reader lowercases and deduplicates case-insensitively before validation |
| `hours_per_merged_pr` | `null`, or a finite number strictly greater than 0. Never guessed |
| `hourly_rate_usd` | `null`, or a finite number strictly greater than 0. Never guessed |
| `share_aggregates` | Boolean. `true` is a second opt-in, and it does nothing unless `enabled` is also `true` |

`enabled: false` is a successful opted-out config, not an error. A missing
file is the same opted-out config. An enabled config with `repos: []`
(including a file containing only `{"enabled": true}`) is valid and
**unconfigured**: no GitHub read runs, and every report figure stays `unknown`
with `value: null`, never `0`. A zero or negative rate, a non-boolean
flag, a repo that is not `OWNER/NAME`, or a non-finite rate is a validation
error.

## Per-PR record

`#/$defs/pr_record`. One merged pull request, once. VM3 deduplicates pull
requests by `(repository, pull_request)` case-insensitively (storing
`repository` in canonical lowercase `owner/name`), so a pull request that closes
several tickets or appears under two case spellings of the same repository on
disk emits one record and contributes once.
`closing_ticket` is the lowest closing issue number in that same repository,
or `null` when it closes none.

| Field | Rule |
| --- | --- |
| `repository` | Canonical lowercase `owner/name` |
| `pull_request` | Integer greater than 0 |
| `merged_at` | UTC timestamp `YYYY-MM-DDTHH:MM:SSZ` |
| `closing_ticket` | Integer greater than 0, or `null` |
| `cost_credits` | Nonnegative finite number, or `null` |
| `cost_usd` | Nonnegative finite number, or `null` |
| `cost_status` | `known` or `unknown` |
| `cost_reason` | Non-empty string when unknown, otherwise `null` |

`cost_status` follows the newest `launch-fleet: cost` line for that pull
request. `cost unknown` or `total unknown` is `unknown`: both amounts are
`null` and `cost_reason` says why. A known line carries `cost_credits`.
`cost_usd` stays `null` when no USD projection was supplied; that does not
make the credit cost unknown. A known line with a null credit cost is invalid.

## Collection

`#/$defs/collection`. VM3 returns this object: `reads` plus `records`.

Each read is one configured repository in canonical lowercase `owner/name`, at
most once case-insensitively: `status` is `complete` or `incomplete`. A
complete read has `reason: null`. An incomplete read has a non-empty `reason`
and contributes no invented zeros downstream. Records are full `pr_record`
documents, at most one per `(repository, pull_request)` pair case-insensitively,
and every record's `repository` must appear in `reads`. An empty `reads: []`
(with `records: []`) represents an unconfigured source list (`repos: []`), not
a completed read of zero merges. A repository whose read is incomplete is named
only here, in the local collection, never in an aggregate.

## Report

`#/$defs/report`. `schema` is `openwiz.value-meter.v1`, `kind` is `report`,
`opted_in` is boolean, and `as_of` is the UTC instant the report was built.

### Windows

Fixed PST is UTC−8 all year, the same day boundary as
[`plan-links.v1`](plan-links.v1.md): `08:00:00Z`. Daylight time is not used.
`end` is the latest `08:00:00Z` at or before `as_of`.

| Window | Interval |
| --- | --- |
| `this_week` | `[end-7d, end)` |
| `last_week` | `[end-14d, end-7d)` |

Both bounds are `08:00:00Z`. A merge at exactly `end` is outside this week. A
merge at exactly `end-7d` is inside this week and outside last week. The two
windows are adjacent and the same length. Opted-out reports still carry these
bounds: choosing them uses the clock, not a GitHub read.

### Metrics

Every headline metric has `state`, `value`, `known_count`, `total_count`, and
`reason`.

| `state` | `value` | `reason` |
| --- | --- | --- |
| `known` | finite number | `null` |
| `partial` | finite number | non-empty |
| `unknown` | `null` | non-empty |

`partial` is allowed only on `cost_per_merged_pr_credits` and
`cost_per_merged_pr_usd`. `merged_prs`, `hours_saved`, and `money_saved_usd`
are `known` or `unknown`.

`known_count` and `total_count` are integers `>= 0`, and `known_count` is
never greater than `total_count`. For a cost metric, `known` requires
`known_count == total_count` and `total_count > 0`. `partial` requires
`0 < known_count < total_count`. `known_count == 0` is `unknown`, not a zero
cost.

`merged_prs` `value`, when known, is a nonnegative integer. A numeric
`hours_saved`, gross `money_saved_usd`, or cost-per-pull-request `value` is
nonnegative. The net is the only money figure that may be negative.

`money_saved_usd` also has `net_of_known_cost_usd` and `net_reason`. `value`
is the gross saving. The net is that gross minus the sum of `cost_usd` on
the pull requests in the window. It is a finite number only when the gross
is known, the window contains at least one pull request, and every one of
those pull requests has a known USD cost. That number may be negative when
the cost exceeds the gross. Otherwise the net is `null` and `net_reason` is
non-empty. A null net is not stored as zero. When the net is a number,
`net_reason` is `null`. A complete window with no merged pull request keeps
a null net, because there is no USD cost to subtract.

### How each figure is computed

VM4 computes these. The contract only fixes the outcomes.

1. `merged_prs` is the count of merged pull requests in the half-open window
   only when at least one repository is configured (`len(repos) >= 1`, so
   `reads` is non-empty) and every configured repository's read for that
   window is `complete`, counting each `(repository, pull_request)` once
   case-insensitively. Under that condition, an empty complete read produces
   `0` (`state: "known"`). When `repos` is empty (`[]`), the meter is
   unconfigured: no GitHub read runs, and `merged_prs` (and every downstream
   headline metric and week-over-week delta) stays `unknown` with `value: null`
   and a non-empty reason (for example `no repositories configured`), never
   `0`. Any incomplete read likewise makes `merged_prs` `unknown` with
   `value: null`.
2. `hours_saved` is `merged_prs * hours_per_merged_pr` only when `merged_prs`
   is `known` and `hours_per_merged_pr` is configured. Otherwise `unknown`.
   A known count of `0` with a configured rate is `0`, which is measured.
3. `money_saved_usd` gross is `hours_saved * hourly_rate_usd` only when
   `hours_saved` is `known` and `hourly_rate_usd` is configured. Otherwise
   `unknown`. The net follows the rule above.
4. `cost_per_merged_pr_credits` and `cost_per_merged_pr_usd` are the mean over
   pull requests in the window whose amount is known. `partial` when
   `0 < known_count < total_count`. `known` when `known_count == total_count > 0`.
   `unknown` with `value: null` when `known_count == 0`, `merged_prs` is `0`,
   `repos` is empty, or the window's read is incomplete. The reason for a
   complete empty window of at least one configured repository is
   `no merged pull requests in the window`.
5. `week_over_week` is one delta per headline. `total_count` is `2`.
   `known_count` is how many of the two weeks have a numeric value,
   including a measured `0`. One numeric week and one unknown week is
   `known_count` 1. `value` is this week minus last week. `direction` is `up` when the value
   is positive, `down` when negative, `flat` when zero, and `unknown` only
   when `state` is `unknown`. The money delta uses gross `value`, not the net.
   State is `unknown` when either week is `unknown`. State is `partial` when
   both weeks have a numeric value and either week is `partial`. State is
   `known` when both weeks are `known`.

An unmeasured, unreadable, or unconfigured figure is never stored as `0`.
The only zeros in a report are results of a complete measurement over at least
one configured repository.

## Aggregate export

`#/$defs/aggregate`. Emitted only when normalized config has `enabled` and
`share_aggregates` both `true`. It carries `as_of`, `windows`, `metrics`, and
`week_over_week` with the same numeric and state rules as the report, and
nothing else: no `repository`, no pull request number, no title, no ticket
number, no thread id, no personal fact, and no local diagnostic text.

The exporter (VM2) MUST NOT copy free-form local `reason` or `net_reason` text
from the local report into an aggregate. Every non-null `reason` and
`net_reason` in an aggregate must be replaced with one of the fixed, allowlisted
`#/$defs/aggregate_reason` codes pinned above:

| Code | Meaning |
| --- | --- |
| `unconfigured_repos` | `repos` is empty; no source repositories configured |
| `unconfigured_rate` | `hours_per_merged_pr` or `hourly_rate_usd` is unset |
| `incomplete_read` | At least one configured repository read was incomplete |
| `no_merged_prs` | Complete read over configured repositories found zero merged PRs |
| `no_known_cost` | Merged PRs exist in the window, none with known cost in that unit |
| `partial_cost_coverage` | Only a strict subset of merged PRs had known cost in that unit |
| `upstream_unknown` | Derived metric or net is unknown because an upstream figure is unknown |
| `week_unknown` | Week-over-week delta is unknown because at least one week is unknown |
| `week_partial` | Week-over-week delta is partial because both weeks are numeric and at least one is partial |

Coverage stays as `known_count` and `total_count`. VM2 also runs the privacy
scan on the serialized object and refuses the export if that scan fails. This
contract does not define a transport. A future sink can read this object
without a second opt-in flag.

## HTML section seam

WizRoom VM5 implements this function. The contract pins the call, not the CSS.

```text
render_section(report) -> str
```

- The argument is one `#/$defs/report` object.
- The result is one HTML fragment whose root element is `<section class="value-meter">`.
- The fragment contains no `<html`, no `<head`, no `<body`, and no `<script>`.
- Text taken from the report, including every `reason`, is escaped.
- `opted_in: false` explains that telemetry is off, that opting in reads the
  configured repositories locally, and that `share_aggregates` is a separate
  opt-in. It does not show a headline as `0`.
- A metric with `state: "unknown"` or `value: null` is shown as unknown,
  with its reason. It is not shown as `0`.
- A `partial` cost metric shows its value and `known_count of total_count known`.
- A `known` metric may show `0` only when `value` is `0`.

`render_page` is VM5's standalone page. It is not a second schema.

## Fixtures

[`fixtures/value-meter/`](fixtures/value-meter/) holds synthetic documents
only. Valid files live in `valid/`. Invalid files live in `invalid/`.
`invalid/expect.json` names the error each invalid document must produce.
`invalid/repeated-key.json` is refused before the schema, because a JSON
object cannot repeat a key.

| Valid file | What it locks |
| --- | --- |
| `config-opted-in.json` | Enabled, one synthetic repo, both rates set, sharing off |
| `config-opted-out.json` | The default-off object |
| `config-enabled-no-repos.json` | Enabled with an empty source list (valid and unconfigured) |
| `config-share.json` | The second opt-in, sharing on |
| `pr-record-known.json` | Known credits and USD |
| `pr-record-credits-only.json` | Known credits with USD still null |
| `pr-record-unknown.json` | Unknown cost, both amounts null, reason set |
| `collection-complete.json` | One complete read and one record |
| `collection-empty.json` | Empty source list (`reads: []`, `records: []`), unconfigured |
| `report-opted-in.json` | Both weeks known, including a measured net |
| `report-opted-out.json` | Every metric unknown, no invented zero |
| `report-unconfigured-repos.json` | Enabled with empty `repos: []`, every metric unknown |
| `report-partial.json` | Hours unconfigured, partial credit cost, mixed deltas |
| `report-zero-merges.json` | Complete read over configured repo, `merged_prs` 0, cost per PR unknown, net null |
| `aggregate.json` | The same known weeks with no repository text |
| `aggregate-partial.json` | Partial and unknown weeks using allowlisted aggregate reasons only |

Run:

```sh
python3 -I contracts/fixtures/value-meter/test_fixtures.py
python3 -I contracts/fixtures/value-meter/test_fixtures.py demo
```
