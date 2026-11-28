# OpenWiz grill picker contract, version 1 (`openwiz.grill-picker.v1`)

The picker presents and submits one question at a time, including for older
grill rounds with several questions. A card and its answer are separate UTF-8
JSON objects. Both carry `schema: openwiz.grill-picker.v1`, a `kind` of `card`
or `answer`, and the same `context`. Validate against the
[Draft 2020-12 schema](grill-picker.v1.schema.json) with date-time format
checking enabled. Reject duplicate JSON object keys and strings that cannot
round-trip as UTF-8.

## Shared context

Copy `context` from the
[decisions v1 grill round answer locator](decisions.v1.md#response-risk-and-answers).
It contains the verified PR `subject` (repository, kind and number), the
`comment_id`, `request_id`, `request_kind` (`grill_round`), the existing request
`fingerprint`, relative `grill_file`, positive `round` and `question_id`. The
question ID is the saved label of one or two uppercase topic letters and a
positive counter. The full locator distinguishes the same question ID in
another grill, round, request or revision.

## Card

| Field | Rule |
| --- | --- |
| `text` | The saved question's exact, nonempty `decides` text. |
| `options` | A nonempty array in display order. Each option has a stable, case-sensitive `id`, nonempty `text` and a Boolean `recommended`. The first option represents the saved recommendation and is marked `true`. Every following option is marked `false`. Refuse a misplaced recommendation at validation. |
| `multi` | A required Boolean. `true` permits more than one choice. |
| `notes` | A required Boolean that permits an optional free-text note when `true`. |
| `other` | A required Boolean that permits a free-text choice when `true`. |

Check that option IDs are unique even when their labels differ. Keep the given
display order and require an explicit submission. A recommendation alone
supplies no answer.

## Answer

| Field | Rule |
| --- | --- |
| `chosen_option_ids` | Required array of distinct IDs from the matched card, in submitted order. May be empty when `other` is supplied. |
| `notes` | Optional string when the card permits it. An explicitly submitted empty string remains present. A note supplies no choice. |
| `other` | Optional nonempty string when the card permits it. Counts as one choice. |
| `at` | Submission time as an RFC 3339 date-time with uppercase `T` and UTC `Z`, with optional fractional seconds and seconds in the range 00–59. Retain the submitted value on read-back. |

Require at least one choice. A single-select card accepts either one option or
one Other choice. A multi-select card accepts any combination of its distinct
options and an allowed Other choice. Compare the answer context to the exact
matched card and check membership, choice count and field permissions against
that card before saving.

Preserve the UTF-8 bytes of each decoded `notes` and `other` string. Retain
leading and trailing whitespace, tabs, line endings, blank lines and Unicode
as submitted. Preserve field presence and the order of selected IDs. JSON
escaping may represent these same bytes in transit and storage.

## Existing grill records

Use the existing decisions v1 contextual answer framing. Its context line
uses the existing field order. Its answer segment is the compact picker
answer object, including its context. Escape non-ASCII characters in the
segment with JSON Unicode escapes so the payload fits on one physical line,
even for text containing Unicode line separators. Append no newline to the
segment. The existing grill records match extracts that segment byte for byte.

Before applying the answer, verify the existing private PR, saved source,
request fingerprint, round and unanswered question. Verify currentness, target
and risk under decisions v1, including second confirmation for live, release
or publish. Validate the extracted answer, including equality of its context
with the verified outer locator, against the exact card shown. A malformed,
ambiguous, stale, superseded, mismatched or unconfirmed submission settles
nothing.

Save the exact answer segment as one `> ` reply line under the matched question
in its saved round, followed by the record newline. For an older round with
multiple questions, associate that line with the question ID carried in the
payload and keep other replies intact. Read back by removing the quote prefix
and record newline, then decoding the JSON. Keep the existing `Settled:` and
`Open:` lists and private reply comment, with the saved reply verified before
advancing the request. After an uncertain write, reconcile against the saved
reply before retrying.

## Fixture proof

The [synthetic fixtures](fixtures/grill-picker/) pair accepted cards and
answers with single-rule breaks. The schema refuses structural breaks,
including a recommendation in the second position. The proof also checks
card-bound rules and round-trips a synthetic quoted reply against fixed
expected UTF-8 bytes.

Run `python3 -I contracts/fixtures/grill-picker/test_fixtures.py` with a Python
environment that has a Draft 2020-12 `jsonschema` validator. This exercises the schema and the record format on fixtures. The
recording and picker implementations verify their own live boundaries.
