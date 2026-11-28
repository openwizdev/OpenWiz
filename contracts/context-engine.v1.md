# OpenWiz context engine contract v1 (`openwiz.context-engine.v1`)

CE1 of spec #3737. The [schema](context-engine.v1.schema.json) defines eight
JSON record shapes for the store, connectors, ledger, and closer. The
[offline fixtures](fixtures/context-engine/README.md) use invented sources,
authors, paths, and messages. This contract grants no access or permission to send.

Every record has `schema: "openwiz.context-engine.v1"` and one `kind` from the
sections below. Every listed field is required. Readers reject duplicate keys
before schema validation and reject unknown fields in records and nested objects.
A slug starts with a lowercase letter and uses up to 64 lowercase letters,
digits, or hyphens. Opaque IDs keep the source's value and contain no control
characters. Links use HTTPS and carry no credentials. Times use
`YYYY-MM-DDTHH:MM:SS[.fraction]Z` in UTC. Consumers also check actual calendar
dates, local permissions and paths, and referenced records or service facts.
Schema validity alone is a shape check.

## Connector manifest

`id` identifies the connector. `source` is the stable source slug on its records.
`scopes` lists the source's exact permission names with `access: "read"` on each.
A connector without service scopes uses an empty array. Verify the named scopes
are read-only at the source before using them. `requirements.account` and
`requirements.plan` describe access and plan requirements separately. Use
`"none"` where there is no requirement. Only `default: "off"` is valid. The owner
opts in to each connector and supplies any sign-in through their own secret store.

~~~json
{
  "schema": "openwiz.context-engine.v1",
  "kind": "connector-manifest",
  "id": "synthetic-connector",
  "source": "synthetic-chat",
  "scopes": [{"name": "history", "access": "read"}],
  "default": "off",
  "requirements": {"account": "Synthetic account", "plan": "none"}
}
~~~

## Transcript

`source`, `conversation`, and `message_id` identify a message. Conversation and
message IDs are opaque. `author` is the display text the source shows. Preserve
empty source author text. `time` is the source's time in UTC. `text` holds all the
source text, with only the redactions below. `attachments` is an array of source
references, each an object containing only the attachment's opaque `id`. Use an
empty array for none. Attachment bytes, inline data, and downloaded copies stay
out of the record and store.

~~~json
{
  "schema": "openwiz.context-engine.v1",
  "kind": "transcript",
  "source": "synthetic-chat",
  "conversation": "conversation-7",
  "message_id": "message-2",
  "author": "Synthetic Reader",
  "time": "2031-01-02T03:04:05Z",
  "text": "First line.\nSecond line.",
  "attachments": [{"id": "attachment-1"}]
}
~~~

## Saved post

`source` and the opaque `post_id` identify the post. `link` is the post's source
link. `author`, `time`, and `text` follow the transcript rules. `action` records
what the owner already did and is exactly `repost`, `bookmark`, or `like`. If
the source reports several actions on one post, write one record per action
with identity `(source, post_id, action)`. The connector only reads these actions.

~~~json
{
  "schema": "openwiz.context-engine.v1",
  "kind": "saved-post",
  "source": "synthetic-social",
  "post_id": "post-5",
  "link": "https://posts.example.invalid/5",
  "author": "Synthetic Writer",
  "time": "2031-01-02T03:04:05.125Z",
  "text": "An invented idea.",
  "action": "bookmark"
}
~~~

## Local store and redaction

Resolve `<context>` as `context/` under the owner's OpenWiz data directory.
Use the [existing state-directory resolution](../crates/cli/src/state/mod.rs)
for that directory. The store
contains `transcripts/`, `saved-posts/`, `recaps/`, `ledger/`, and
`pillars.json`. The first four hold one JSON record per file. Use the lowercase
SHA-256 of the UTF-8 compact JSON array of record identity strings as the
filename, plus `.json`. Array separators have no spaces. Write non-ASCII characters
as UTF-8 and escape only double quotes and backslashes in identity strings. The identity for a transcript and a saved post is given
above. A recap uses `(pillar, period.start, period.end)` and a ledger item uses
its single `id`. Using digests keeps source identifiers out of file paths.

Before writing, check the resolved directory and write destination against Git
work trees, including linked worktrees and symlink-resolved locations. Refuse a
location within a work tree and report the work tree. Refuse if location or
permissions cannot be checked. The context directory and its subdirectories are
owned by the current owner with mode `0700`. Data files are owner-only `0600`
from creation. Check existing directories and files before using them. The
`store-layout` fixture describes the required layout with `directory: "context"`,
`in_work_tree: false`, `directory_mode: "0700"`, and `file_mode: "0600"`. Those
fields express the required facts for the fixture. The store checks the real
filesystem each time and does not rely on a declaration. The store makes no
network calls. It has no telemetry, upload, or sync.

~~~json
{
  "schema": "openwiz.context-engine.v1",
  "kind": "store-layout",
  "directory": "context",
  "in_work_tree": false,
  "directory_mode": "0700",
  "file_mode": "0600"
}
~~~

Run redaction before any record is written. The schema's four named shape
definitions supply the patterns. Replace only the matched secret material.

| Shape definition | Secret material | Replacement |
| --- | --- | --- |
| `standalone-token-shape` | Entire known GitHub or Slack token | `[redacted:token]` |
| `authorization-token-shape` | Captured value of an Authorization Bearer header | `[redacted:token]` |
| `private-key-shape` | Entire PEM private-key block, including the boundary lines | `[redacted:key]` |
| `password-shape` | Captured quoted value of a password, passwd, or pwd assignment | `[redacted:password]` |

Handle complete key blocks and password assignments before matching tokens
inside them. Keep the Bearer prefix and password key, separator, and quotes.
Leave line breaks outside a replaced block and all unmatched text byte for byte.
Keep prior redaction markers. The schema refuses known shapes in persisted
text fields. It cannot compare output to source text to prove that all other
bytes were preserved. The store's redaction tests compare exact before and after
text using the supplied vectors.

## Pillars and recaps

The `pillars` object maps owner-chosen slugs to `name` and `description`. An
empty object means the owner has defined none. There are no built-in pillars.

~~~json
{
  "schema": "openwiz.context-engine.v1",
  "kind": "pillars",
  "pillars": {"synthetic-garden": {"name": "Synthetic garden", "description": "Invented planting work."}}
}
~~~

A recap references an existing `pillar` by slug. Its `period` has UTC `start`
(inclusive) and `end` (exclusive), with start before end. Write one per pillar
and period. Keep the full contextual write-up in `text`. The nonempty
`citations` array gives the `source`, `conversation`, and `message_id` of
each transcript item drawn on. The closer verifies the pillar and cited items
exist in the local store. Recaps stay alongside the transcripts.

~~~json
{
  "schema": "openwiz.context-engine.v1",
  "kind": "recap",
  "pillar": "synthetic-garden",
  "period": {"start": "2031-01-01T00:00:00Z", "end": "2031-01-08T00:00:00Z"},
  "text": "The synthetic seeds arrived, and the group discussed their watering schedule.",
  "citations": [{"source": "synthetic-chat", "conversation": "conversation-7", "message_id": "message-2"}]
}
~~~

## Item ledger

Keep one `ledger-item` per stable opaque `id`. Its `state` is a single object of
exactly one of these kinds.

| State | Required fields besides `kind` |
| --- | --- |
| `Done` | `proof` with one `link` to evidence or one opaque `record` identifying saved evidence |
| `Ticketed` | `issue`, the GitHub issue link |
| `Decide` | `question` and `recommendation` as nonempty text |
| `Reply` | Nonempty `draft`, `approval` of `pending`, `approved`, or `declined`, and boolean `sent_by_engine: false` |
| `Drop` | Nonempty `reason` |

A missing state, several states, or a state with a missing or invalid field is
unresolved. Count it and keep its item identifier for the closer. Even a valid
Ticketed state remains unresolved until a read-only check confirms a closing
pull request merged. An open, absent, or unreadable merge is unresolved.
Approval records the owner's disposition of a draft. The engine sends nothing
even for an approved draft.

~~~json
{
  "schema": "openwiz.context-engine.v1",
  "kind": "ledger-item",
  "id": "item-1",
  "state": {"kind": "Done", "proof": {"link": "https://github.com/synthetic-owner/synthetic-work/issues/1"}}
}
~~~

~~~json
{
  "schema": "openwiz.context-engine.v1",
  "kind": "ledger-item",
  "id": "item-2",
  "state": {"kind": "Done", "proof": {"record": "proof-2"}}
}
~~~

~~~json
{
  "schema": "openwiz.context-engine.v1",
  "kind": "ledger-item",
  "id": "item-3",
  "state": {"kind": "Ticketed", "issue": "https://github.com/synthetic-owner/synthetic-work/issues/3"}
}
~~~

~~~json
{
  "schema": "openwiz.context-engine.v1",
  "kind": "ledger-item",
  "id": "item-4",
  "state": {"kind": "Decide", "question": "Water today?", "recommendation": "Wait until morning."}
}
~~~

~~~json
{
  "schema": "openwiz.context-engine.v1",
  "kind": "ledger-item",
  "id": "item-5",
  "state": {"kind": "Reply", "draft": "Synthetic draft.", "approval": "pending", "sent_by_engine": false}
}
~~~

~~~json
{
  "schema": "openwiz.context-engine.v1",
  "kind": "ledger-item",
  "id": "item-6",
  "state": {"kind": "Drop", "reason": "Synthetic duplicate."}
}
~~~

## Ideas

Write one `ideas` file per scroller `run_id`, with the `version` it targets
(`major.minor.patch`) and `target_visibility: "private"`. Each item has the
original saved post's `saved_post` link and the `idea` in plain text. One
`home` object carries its `kind` of `spec`, `ticket`, or `grill` and the
`link` to that spec, ticket, or grill question for the stated version. An
empty array records a run with no ideas. The writer verifies the home belongs
to the current version and reads back that the explicitly selected repository
belongs to the owner and is private before writing there. An unknown visibility
or owner refuses. The visibility field alone grants nothing. Keep transcripts,
saved-post records, and recaps out of the ideas file. The scroller opens
nothing and never posts or reacts.

~~~json
{
  "schema": "openwiz.context-engine.v1",
  "kind": "ideas",
  "run_id": "run-7",
  "version": "0.2.0",
  "target_visibility": "private",
  "ideas": [
    {"saved_post": "https://posts.example.invalid/5", "idea": "Record the seed order.", "home": {"kind": "spec", "link": "https://github.com/synthetic-owner/synthetic-work/issues/6"}},
    {"saved_post": "https://posts.example.invalid/6", "idea": "Add a watering check.", "home": {"kind": "ticket", "link": "https://github.com/synthetic-owner/synthetic-work/issues/7"}},
    {"saved_post": "https://posts.example.invalid/7", "idea": "Ask about planting dates.", "home": {"kind": "grill", "link": "https://github.com/synthetic-owner/synthetic-work/issues/8#issuecomment-9"}}
  ]
}
~~~
