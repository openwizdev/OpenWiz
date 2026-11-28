# Feed contract, version 1 (`openwiz.feed.v1`)

Spec #3408 (the feed and Needs-you pings, with WizBar in T3), ticket FD2
(#3410). This contract fixes the home feed file, every card kind, the
GitHub record that creates and resolves each kind, the four `openwiz:*-v1`
comment forms, and the one-ping rule with its ledger.
[`feed.v1.schema.json`](feed.v1.schema.json) pins the JSON shapes;
[`fixtures/feed/`](fixtures/feed/) holds synthetic fixtures for every kind,
comment form, resolution rule, ping case and refusal.

Producer: `feed/` in WizPlugins (FD5). Consumers: the shared board core
(FD3) and T3 WizBar host (FD1), the Needs-you ping skill (FD7), the setting
proposal helper (FD9), and the comment writers in the budgets, keys and
driver roster specs.

It builds on [`settings.v1.md`](settings.v1.md) (#3376: writable settings
paths, account labels, key rows and drivers),
[`plan-links.v1.md`](plan-links.v1.md) (native blockers),
[`../kernel/records.v1.md`](../kernel/records.v1.md) (labels, status notes,
host names and B2 blocker completion), [`decisions.v1.md`](decisions.v1.md),
[`review-loops.v2.md`](review-loops.v2.md) and
[`release-candidate.v1.md`](release-candidate.v1.md), changing none of them.

**This contract grants nothing.** It authorizes no GitHub read or write, no
setting change, no merge, no release, no key write and no push
notification. Passing fixtures prove only that the contract, schema and
rules agree on synthetic data, never that any producer, board or push route
is live. Every example is synthetic: `syn-owner/syn-app`, labels like
`work` and `codex-work`, made-up numbers and hashes.

## Agents' channel and the feed file

Every card comes from a GitHub record (an issue, a pull request or an
issue/PR comment). Agents talk only through GitHub records and the driver's
wake: never through direct messages to the owner's Wiz or Needs you thread,
and no card is ever built from chat text or local logs.

- **The file:** `.openwiz/feed.v1.json` in the owner's home checkout. It is
  one strict UTF-8 JSON object; repeated keys or unknown fields anywhere
  refuse the whole file.
- **Atomic single producer:** one feed producer (FD5) writes the file whole
  and atomically (write temp file in the same directory, fsync, rename) and
  never writes to GitHub.
- **Unavailable, never zero:** if `.openwiz/feed.v1.json` is missing,
  broken or fails validation, readers show the feed as unavailable rather
  than empty. Inside a valid file, every source the producer could not read
  appears in `unavailable` with its reason; `unavailable` is always present
  (`[]` when every source succeeded). Fixture: `unavailable-source.json`.

## Fields

A UTC time is `YYYY-MM-DDTHH:MM:SSZ`. No extra field is allowed anywhere.

| Field | Type | Rule |
| --- | --- | --- |
| `schema` | const `"openwiz.feed.v1"` | Always `"openwiz.feed.v1"` |
| `read_at` | UTC time | When the producer finished reading this snapshot |
| `budget` | object | Request budget for this producer run |
| `budget.used` | integer >= 0 | Requests used in this run; must be `<= budget.allowed` |
| `budget.allowed` | integer >= 1 | Fixed request ceiling for this run |
| `cards` | array of cards | Zero or more cards; every `id` is unique within `cards` |
| `cards[].id` | string | Stable across runs, derived from the GitHub record as the Card kinds table fixes |
| `cards[].kind` | enum (8 kinds) | One of the eight kinds in the Card kinds table |
| `cards[].needs_owner` | boolean | `true` only while open and waiting on the owner; always `false` when resolved or scroll-only |
| `cards[].title` | single-line string (1..240) | The GitHub record's own public title; never chat text or private data |
| `cards[].link` | GitHub HTTPS URL | Direct URL to the issue, pull request or `#issuecomment-<id>` matching `record` |
| `cards[].record` | object | The GitHub record the card came from |
| `cards[].record.repository` | `owner/name` | GitHub repository holding the record |
| `cards[].record.number` | integer >= 1 | Issue or pull request number |
| `cards[].record.comment_id` | integer >= 1 or `null` | Comment id for comment-backed cards; `null` for `pr-ready-to-merge` and issue-level `blocker` cards |
| `cards[].since` | UTC time | When the triggering GitHub record appeared; must be `<= read_at` |
| `cards[].resolved_at` | UTC time or `null` | `null` while open; UTC time when resolved (`since <= resolved_at <= read_at`) |
| `unavailable` | array of objects | Required (`[]` when none); sources the producer could not read |
| `unavailable[].source` | single-line string (1..240) | Unreadable source name (for example `syn-owner/syn-app:pulls`) |
| `unavailable[].reason` | single-line string (1..240) | Public reason the source could not be read |

## Card kinds

Each kind has one GitHub source and one resolution. `<repo>` is
`<owner>/<name>`, `<n>` is the issue or pull request number, `<cid>` is
`record.comment_id` and `<sha>` is the 40-character lowercase head commit.

| Kind | Needs owner | Card id | GitHub source | Resolution |
| --- | --- | --- | --- | --- |
| `spec-to-approve` | `true` while open | `spec:<repo>#<n>:<cid>` | The latest public spec or plan approval-request comment (`decisions.v1.md`) by a record author on an open `spec` issue with no owner decision after it | An owner approval or decline comment for that request is posted after `<cid>`, or the spec issue closes |
| `pr-ready-to-merge` | `true` while open | `pr:<repo>#<n>@<sha>` | An open, non-draft, unmerged pull request with a reviewer `APPROVE` verdict (`review-loops.v2.md`) and green required checks at exact head `<sha>` and no standing merge grant | The pull request merges or closes, `<sha>` moves, a required check fails, or a standing merge grant covers it |
| `release` | `true` while open | `release:<repo>#<n>:<cid>` | A public ship-go request comment by a record author on an open release-candidate issue or pull request (`release-candidate.v1.md`) waiting for the owner's ship decision | The owner posts the ship-go or hold decision for that candidate, the release tag publishes, or the issue closes |
| `key-needed` | `true` while open | `key:<repo>#<n>:<cid>` | A valid `openwiz:key-needed v1` comment by a record author on an open issue or pull request | The named key has a non-null `set_at >= since` in `.openwiz/settings.json`, or the issue closes |
| `setting-proposal` | `true` while open | `setting:<repo>#<n>:<cid>` | A valid `openwiz:setting-proposal v1` comment by a record author on an open issue or pull request | The proposal comment is answered by the owner (or by Wiz recording the owner's Yes/No answer), or the issue closes |
| `blocker` | `true` only when waiting on the owner; otherwise `false` | `blocker:<repo>#<n>` (or `blocker:<repo>#<n>:<cid>` for a live `asking` note) | An open approved ticket with an uncompleted native GitHub blocker (`plan-links.v1.md`, `kernel/records.v1.md` B1/B2), a `ready-for-human` or `needs-info` label, or a live `asking` status-note comment | Every native blocker closes as `COMPLETED` (never `NOT_PLANNED` or `DUPLICATE`, per B2) and all owner waits clear, or the ticket closes |
| `quota-switch` | `false` always | `quota:<repo>#<n>:<cid>` | A valid `openwiz:quota-switch v1` comment by a record author on an open issue or pull request | The comment's `resets_at` UTC time passes (`read_at >= resets_at`), or the issue closes |
| `driver-suggestion` | `false` always | `driver:<repo>#<n>:<cid>` | A valid `openwiz:driver-suggestion v1` comment by a record author on an open issue or pull request | The suggested driver is `true` in `.openwiz/settings.json`, the owner dismisses the suggestion, or the issue closes |

**Blocker ownership.** A `blocker` card sets `needs_owner: true` only when
it waits on the owner: a person's ticket (`ready-for-human`, either the
ticket itself or its open native blocker), or a question addressed to the
owner (`needs-info` or a live `asking` status-note comment per
[`kernel/records.v1.md`](../kernel/records.v1.md)). A ticket blocked only
on another agent's ticket sets `needs_owner: false` (scroll-only).
Fixtures: `blocker-needs-owner.json`, `blocker-scroll-only.json`.

**Resolution leaves Needs you.** When a card's resolution holds, its
`resolved_at` becomes the resolution's UTC time (`since <= resolved_at <= read_at`)
and its `needs_owner` becomes `false`. The Needs-you view shows only cards
with `needs_owner: true` and `resolved_at: null`, so a resolved card leaves
Needs you immediately and never pings. Fixtures:
`resolved-leaves-needs-you.json`, `resolution/cases.json`.

## Comment forms

Each form is posted by a record author on an open issue or pull request.
Line 1 is the exact marker; the lines below give its fields in exact order,
`key: value`, each once, with no extra fields, blank lines or trailing text
(CRLF reads as LF; one optional final LF). Any `openwiz:` comment outside
these forms (and `openwiz:status v1`) is refused (`unknown-marker.txt`).

### `openwiz:setting-proposal v1`

```text
openwiz:setting-proposal v1
path: roles.builder.effort
current: medium
proposed: high
reason: Two builds stalled on medium effort and passed on high.
role: orchestrator
```

- `path`: one writable path from [`settings.v1.md`](settings.v1.md#fields):
  `roles.<role>[.<harness|model|effort|account|fallback>]`,
  `accounts.<label>.<harness|host|reserved|profile[.variable|.folder]>`,
  `hosts.home.<orchestrator|builder|reviewer>`, `hosts.overflow[.host]`,
  `hosts.max_agents`, `hosts.projects.<owner/name>`, `drivers.<driver>`,
  `budgets.<lane>[.<amount|unit|by>]`, `keys.<key>.<store|entry|on>`,
  `channels.<channel>` (`<channel> != t3`), or `telemetry`. Fixed and
  managed fields (`schema`, `channels.t3`, `updates`, `version`,
  `changed_at`, `changed_by`, `history`, `hosts.overflow.serves`,
  `keys.<key>.opt_in`, `keys.<key>.set_at`, `keys.<key>.value`) and unknown
  paths are refused (`setting-proposal-unknown-path.txt`,
  `setting-proposal-fixed-path.txt`).
- `current`, `proposed`: single-line values; `proposed` must differ from
  `current` (`setting-proposal-noop.txt`).
- `reason`: one-line explanation, no private data
  (`setting-proposal-email.txt`).
- `role`: `orchestrator`, `builder`, `fixer`, `reviewer`, `small_builder`
  or `fleet`.
- Posting this comment writes nothing to `.openwiz/settings.json`; only the
  owner's Yes makes Wiz apply it through `openwiz settings`.

### `openwiz:key-needed v1`

```text
openwiz:key-needed v1
key: devin
```

- `key`: a key label (`settings.v1.md` label rule: 1 to 32 letters, digits,
  `-` or `_`), never a key value (`key-needed-key-shaped.txt`). No `value`
  or extra field is allowed (`key-needed-with-value.txt`).

### `openwiz:quota-switch v1`

```text
openwiz:quota-switch v1
role: reviewer
from: codex:gpt-6.2-sol:medium:codex-work
to: codex:vendor/demo:medium:codex-work
resets_at: 2026-11-28T16:00:00Z
```

- `role`: `orchestrator`, `builder`, `fixer`, `reviewer` or `small_builder`.
- `from`, `to`: `<harness>:<model>:<effort>:<account-label>`, colon-joined
  so `models.v1` ids containing `/` (such as `vendor/demo`) parse
  unambiguously. `to` must differ from `from`
  (`quota-switch-same-choice.txt`), and `<account-label>` is an owner label
  from `settings.v1.md`, never an account id
  (`quota-switch-account-id.txt`).
- `resets_at`: UTC time (`quota-switch-bad-reset.txt`).

### `openwiz:driver-suggestion v1`

```text
openwiz:driver-suggestion v1
driver: boat
reason: home full
listing: https://openwiz.dev/market/drivers/boat
```

- `driver`: a driver name as `kernel/records.v1.md` section 6 names a host.
- `reason`: exactly `home full` or `quota out`
  (`driver-suggestion-bad-reason.txt`).
- `listing`: public HTTPS WizMarket listing URL
  (`driver-suggestion-non-https.txt`).

## Ping rule and ledger

Only open (`resolved_at: null`) cards with `needs_owner: true` ping.
Scroll-only cards and resolved cards never ping. Each card `id` pings **at
most once, ever**: a second sighting of a card `id` already in the ledger
produces no ping.

The ledger lives at `pinged.json` in the home checkout's `.openwiz/home` folder,
written atomically with shape `openwiz.feed-pinged.v1`
(`#/$defs/ping_ledger` in `feed.v1.schema.json`):

```json
{
  "schema": "openwiz.feed-pinged.v1",
  "pinged": {
    "pr:syn-owner/syn-app#42@1111111111111111111111111111111111111111": "2026-11-28T09:16:00Z"
  }
}
```

It holds **ids and times only**: no titles, URLs, chat text, keys, emails
or account identifiers. Entries stay in `pinged` even after a card resolves
so a reopened record with the same `id` never pings twice. Fixtures:
`ping/valid-ledger.json`, `ping/invalid-ledger-extra-field.json`,
`ping/invalid-ledger-bad-id.json`, `ping/cases.json`.

## Privacy

No key or token value, account or thread identifier, email address, user
home path or chat text may appear in any card, `unavailable` entry, comment
form or ledger entry. Every free string in `feed.v1.schema.json` enforces
`#/$defs/no_private`, and structured ids/links enforce
`#/$defs/no_private_id`. Card fixtures: `card-key-shaped.json`,
`card-email.json`, `card-account-id.json`.

## Rules

Every feed refusal has a fixture in
[`invalid/expect.json`](fixtures/feed/invalid/expect.json), marked `schema`
when JSON Schema 2020-12 refuses it directly or `rule` when the cross-field
check (`rule_errors` in `test_fixtures.py`) refuses it:

1. **Needs-owner open invariant (schema):** open cards of the five
   needs-owner kinds require `needs_owner: true`
   (`release-not-needs-owner.json`, `key-needed-not-needs-owner.json`);
   scroll-only kinds always require `needs_owner: false`
   (`quota-switch-needs-owner.json`, `driver-suggestion-needs-owner.json`).
2. **Resolved leaves Needs you (schema):** any card with non-null
   `resolved_at` requires `needs_owner: false`
   (`resolved-still-needs-owner.json`).
3. **Kind-specific id, link and `comment_id` (schema):** comment-backed
   kinds require a positive integer `comment_id` and matching id/link
   (`spec-to-approve-no-comment-id.json`,
   `setting-proposal-no-comment-id.json`); `pr-ready-to-merge` requires
   `pr:<repo>#<n>@<40-hex-sha>` and `comment_id: null`
   (`pr-ready-to-merge-bad-id.json`).
4. **Unavailable required and closed objects (schema):** `unavailable` is
   required (`missing-unavailable.json`) and unknown fields anywhere are
   refused (`unknown-field.json`).
5. **Privacy (schema):** key shapes, emails and account ids are refused on
   cards (`card-key-shaped.json`, `card-email.json`, `card-account-id.json`)
   and comment forms.
6. **Cross-field consistency (rule):** `budget.used <= budget.allowed`
   (`budget-over-allowed.json`); every card `id` is unique
   (`duplicate-card-id.json`); each card's `id` and `link` match its
   `record` (`blocker-bad-link.json`); and `since <= resolved_at <= read_at`
   (`resolved-before-since.json`).

## The fixtures

```sh
python3 -I contracts/fixtures/feed/test_fixtures.py
```

It validates every valid and invalid feed fixture, both blocker states, all
four valid and twelve invalid comment forms, sixteen resolution transitions
across all eight kinds, the one-ping ledger and second-sighting rule, the
Fields and Card kinds tables against the schema, and the synthetic-only
privacy scan. Its red run is in `evidence/red.txt`.

## Gaps

- The fixtures prove the contract, schema and rules agree on synthetic
  data; they prove no live producer, board or push route. FD5, FD3 and FD7
  run these fixtures in their own tests.
- Checking whether a comment author is a repository record author or owner,
  or whether a standing merge grant exists, depends on live repository
  configuration and is enforced by the producer (FD5), not this static
  schema.
