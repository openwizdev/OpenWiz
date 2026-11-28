# Context engine fixtures

All examples are invented. Run the offline proof from the repository root with
`python3 -I contracts/fixtures/context-engine/test_fixtures.py`.

`valid.json` names complete records. Each `broken.json` row changes one field of
its named valid record. A row with no `value` removes the field. Paths are arrays
of property names or zero-based array indices. These cases use the schema's
record shape only.

| Case | Valid record | Rule |
| --- | --- | --- |
| connector-default | `connector` | Only off is allowed. |
| missing-default | `connector` | The opt-in posture must be explicit. |
| write-scope | `connector` | Every requested scope is declared read-only. |
| no-source-plan | `connector` | The source plan is explicit. |
| attachment-content | `transcript` | An attachment carries only its source identifier. |
| transcript-author | `transcript` | A transcript always includes its author field. |
| transcript-timestamp | `transcript` | Timestamps use UTC date-time strings. |
| saved-action | `saved-post` | The source action must be repost, bookmark or like. |
| saved-post-link | `saved-post` | A saved post carries a link. |
| store-project | `store-layout` | The store refuses a Git work tree. |
| store-location | `store-layout` | The directory name is relative to OpenWiz data. |
| store-readable | `store-layout` | Files are owner-only. |
| store-traversable | `store-layout` | Directories are owner-only. |
| pillar-description | `pillars` | The owner supplies a description. |
| recap-citations | `recap` | A recap cites transcript items. |
| recap-period | `recap` | A recap fixes the period end. |
| done-proof | `done-link` | Done requires proof. |
| ambiguous-proof | `done-record` | Use one form of Done proof. |
| ticketed-issue | `ticketed` | Ticketed requires an issue link. |
| claimed-merge | `ticketed` | A stored claim cannot stand in for merge readback. |
| decide-question | `decide` | Decide requires a question. |
| decide-recommendation | `decide` | Decide requires a recommendation. |
| reply-draft | `reply` | Reply requires a draft. |
| reply-approval | `reply` | Reply uses one of the three approval statuses. |
| missing-reply-approval | `reply` | Reply explicitly records approval status. |
| engine-sent | `reply` | The engine never sends a reply. |
| numeric-sent-flag | `reply` | The sent flag must be boolean false. |
| drop-reason | `drop` | Drop requires a reason. |
| unresolved-no-state | `drop` | With no state the item is unresolved. |
| unresolved-two-states | `drop` | With two states the item is unresolved. |
| idea-home | `ideas` | Each idea has one home. |
| idea-home-kind | `ideas` | An idea belongs to a spec, ticket or grill. |
| idea-second-home | `ideas` | A second home is refused. |
| ideas-public | `ideas` | The ideas target is explicitly private. |

## Redaction

`redaction.json` gives the store an input as a list of string fragments and an
exact expected output. Join the fragments without a separator in memory only.
The schema rejects the joined input in the valid transcript's text field and
accepts the expected output. The store compares its own output byte for byte.
The key fixture has invented, unusable content.

The Ticketed record is valid in shape. For the ledger's merge-readback tests,
the same record is unresolved with an open or unread closing pull request and
resolved with a confirmed merged closing pull request.
