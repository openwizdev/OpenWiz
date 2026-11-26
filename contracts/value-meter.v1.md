# Value meter v1 (`openwiz.value-meter.v1`)

VM1 of spec #3289. This contract pins the opt-in config, the per-PR record, the
report, the anonymized aggregate, the unknown-versus-zero rules, and the HTML
section seam. VM2 through VM6, in WizRoom, build against it. Nothing here
reads GitHub, renders a page, or uploads telemetry.

**This contract grants nothing.** It authorizes no opt-in on a real account,
no GitHub read, no ledger read, and no telemetry upload. A fixture that passes
proves the documents agree, never that a meter has run.

Where this prose and [`value-meter.v1.schema.json`](value-meter.v1.schema.json)
disagree, the contract is wrong and must be fixed. Rules a schema cannot see
(duplicate keys, window arithmetic, and which states may be partial) are
stated here and checked by `contracts/fixtures/value-meter/test_fixtures.py`.

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
  "states": ["known", "partial", "unknown"]
}
```

Readers refuse a repeated JSON key, at any depth, before they apply the
schema. They also refuse a non-finite number (`NaN`, `Infinity`, `-Infinity`).
Those values are not in the fixtures; the proof builds them in memory.

## Config

`#/$defs/config`. The normalized object always carries every field. A file on
disk may omit a field; the reader fills the pin's default before validation.
`enabled` defaults to `false`. `share_aggregates` defaults to `false`.
`repos` defaults to `[]`. Both rates default to `null`.

| Field | Rule |
| --- | --- |
| `enabled` | Boolean. `false` means no GitHub read and no ledger read |
| `repos` | Zero or more `OWNER/NAME`, each once. Names are matched case-sensitively as written |
| `hours_per_merged_pr` | `null`, or a finite number strictly greater than 0. Never guessed |
| `hourly_rate_usd` | `null`, or a finite number strictly greater than 0. Never guessed |
| `share_aggregates` | Boolean. `true` is a second opt-in, and it does nothing unless `enabled` is also `true` |

`enabled: false` is a successful opted-out config, not an error. A missing
file is the same opted-out config. A zero or negative rate, a non-boolean
flag, a repo that is not `OWNER/NAME`, or a non-finite rate is a validation
error.

## Per-PR record

`#/$defs/pr_record`. One merged pull request, once. VM3 deduplicates a pull
request that closes several tickets and still emits one record.
`closing_ticket` is the lowest closing issue number in that same repository,
or `null` when it closes none.

| Field | Rule |
| --- | --- |
| `repository` | `OWNER/NAME` |
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

Each read is one configured repository: `status` is `complete` or
`incomplete`. A complete read has `reason: null`. An incomplete read has a
non-empty `reason` and contributes no invented zeros downstream. Records are
full `pr_record` documents. A repository whose read is incomplete is named
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

`money_saved_usd` also has `net_of_known_cost_usd` and `net_reason`. `value`
is the gross saving. The net is gross minus the sum of known `cost_usd` on
the pull requests in that window, and only when every one of those pull
requests has a known USD cost. Otherwise the net is `null` and `net_reason`
is non-empty. A null net is not stored as zero. When the net is a number,
`net_reason` is `null`.

### How each figure is computed

VM4 computes these. The contract only fixes the outcomes.

1. `merged_prs` is the count of merged pull requests in the half-open window
   when every configured repository's read for that window is `complete`,
   including `0` when the complete read is empty. Any incomplete read makes
   it `unknown` with `value: null`.
2. `hours_saved` is `merged_prs * hours_per_merged_pr` only when `merged_prs`
   is `known` and `hours_per_merged_pr` is configured. Otherwise `unknown`.
   A known count of `0` with a configured rate is `0`, which is measured.
3. `money_saved_usd` gross is `hours_saved * hourly_rate_usd` only when
   `hours_saved` is `known` and `hourly_rate_usd` is configured. Otherwise
   `unknown`. The net follows the rule above.
4. `cost_per_merged_pr_credits` and `cost_per_merged_pr_usd` are the mean over
   pull requests in the window whose amount is known. `partial` when
   `0 < known_count < total_count`. `known` when `known_count == total_count > 0`.
   `unknown` with `value: null` when `known_count == 0` or `merged_prs` is `0`
   or the window's read is incomplete. The reason for a complete empty window
   is `no merged pull requests in the window`.
5. `week_over_week` is one delta per headline. `total_count` is `2`.
   `known_count` is how many of the two weeks have a numeric value.
   `value` is this week minus last week. `direction` is `up` when the value
   is positive, `down` when negative, `flat` when zero, and `unknown` only
   when `state` is `unknown`. The money delta uses gross `value`, not the net.
   State is `unknown` when either week is `unknown`. State is `partial` when
   both weeks have a numeric value and either week is `partial`. State is
   `known` when both weeks are `known`.

An unmeasured, unreadable, or unconfigured figure is never stored as `0`.
The only zeros in a report are results of a complete measurement.

## Aggregate export

`#/$defs/aggregate`. Emitted only when normalized config has `enabled` and
`share_aggregates` both `true`. It carries `as_of`, `windows`, `metrics`, and
`week_over_week` in the same shapes as the report, and nothing else: no
`repository`, no pull request number, no title, no ticket number, no thread
id, no personal fact, and no reason text that contains those. Coverage stays
as `known_count` and `total_count`. VM2 runs the privacy scan on the
serialized object and refuses the export if that scan fails. This contract
does not define a transport. A future sink can read this object without a
second opt-in flag.

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
| `config-share.json` | The second opt-in, sharing on |
| `pr-record-known.json` | Known credits and USD |
| `pr-record-credits-only.json` | Known credits with USD still null |
| `pr-record-unknown.json` | Unknown cost, both amounts null, reason set |
| `collection-complete.json` | One complete read and one record |
| `report-opted-in.json` | Both weeks known, including a measured net |
| `report-opted-out.json` | Every metric unknown, no invented zero |
| `report-partial.json` | Hours unconfigured, partial credit cost, mixed deltas |
| `report-zero-merges.json` | Complete read, `merged_prs` 0, cost per PR unknown |
| `aggregate.json` | The same known weeks with no repository text |

Run:

```sh
python3 -I contracts/fixtures/value-meter/test_fixtures.py
python3 -I contracts/fixtures/value-meter/test_fixtures.py demo
```
