# Agent-native CRM

This file is a draft spec body. [ADR 0004](../adr/0004-github-layout-for-versions-specs-tickets.md) says the live spec is a parent issue, and a file in the repository was considered and rejected for that job. The draft is here so the research, the cut and the first slice can be reviewed together. It should be copied into a parent issue, and this file removed or reduced to a pointer, once that issue exists.

The notes behind the design are in [docs/research/crm-guide-notes.md](../research/crm-guide-notes.md). The first slice is [products/crm](../../products/crm/README.md).

## Problem Statement

OpenWiz needs a CRM with two users, and they are the same product.

OpenWiz itself needs to remember people and organizations it deals with: users, contributors, partners, and leads such as a university application or work in an outside repository. The factory already keeps its process on GitHub. It does not keep the relationship around that work: who the person is, which organization they belong to, what was last said, and what should happen next.

The other user is an agent building or operating some other product. That agent needs a CRM it can call the way it calls a tool: create and search records, log what just happened, and read the linked context back in one response. Today that agent is pointed at Salesforce or HubSpot. Those systems are powerful and they are a poor fit for an agent. The schema belongs to an admin and drifts. A read of one record is not the context. A write is a business action that can fire rules the agent cannot see. Quotas are shared, errors are ambiguous, and the integration user does not see the CRM the admin sees. The research notes collect those limits from the Ampersand guide and from the vendor docs.

A spreadsheet, or a pile of notes in a repository, fails the test the guide starts from. Several roles add columns, two rows disagree about the owner, and nobody can say what changed.

## Solution

Build one local-first CRM whose records are the product, and whose callers are agents.

The working name in the request was the goat CRM. This draft calls it the agent-native CRM. The public name is an open decision.

### Who it is for

- OpenWiz, tracking users, contributors, partners and leads. A lead might be a university application or an outside repository. Those are records and associations, not special tables.
- Other agents, through a skill that tells them to use this CRM for their own relationships. One data model, one tool surface, a separate database per workspace. OpenWiz's own database is just the first workspace.

People use it by asking an agent. The agent uses the command line or MCP. A human user interface is later.

### Data model

Four standard objects, plus custom objects that use the same API:

| Object | Required fields | What it is |
| --- | --- | --- |
| `person` | `name` | A person. Optional `email` and `role` |
| `company` | `name` | An organization. Optional `domain` |
| `deal` | `name`, `stage` | A potential commitment. Stage is `new`, `qualifying`, `proposal`, `won` or `lost`. Optional `amount` |
| `activity` | `kind`, `summary` | Something that happened. Kind is `note`, `email`, `meeting`, `call`, `slack`, `github`, `x` or `other` |

Custom objects and custom fields are metadata. Field types are `text`, `number`, `boolean`, `date` and `select`. Adding a field does not migrate a table. A required field cannot be added once records exist, because old rows would already violate it.

Associations are directed and labeled (`works_at`, `about`). They are not a lookup column hidden inside the record. An activity log creates the activity and links it with `about`.

Every record has an integer `revision`. An update or delete may pass the revision it read. If the record has moved, the write is refused. That is the optimistic lock the guide lists as the spreadsheet's first failure. Callers that omit it accept a lost update.

Every create, update, delete and association appends a change row with the actor and the time. Deleted records stay, with `deleted_at` set. Search hides them. Get and context still return them.

An external binding is `provider` + object type + external id. HubSpot ids are unique per object, so the type is part of the key. The binding is idempotent for the same record and a conflict for a different one. The slice stores the binding. It does not call the provider.

`context` is the read agents should prefer. It returns the record, one hop of linked records with their fields, and the recent changes. That is the guide's "reading is reconstructing the graph," done locally so the agent does not issue a fan-out of gets.

### Agent surface

The slice's surface is the contract for this cut:

- Command line: `python3 -I products/crm/crm.py --db PATH ...`, one JSON object on stdout. Commands are `init`, `schema`, `object-add`, `field-add`, `record-create`, `record-get`, `record-update`, `record-delete`, `record-search`, `associate`, `activity-log`, `context`, `ref-bind` and `ref-get`.
- MCP: `python3 -I products/crm/mcp.py` with `OPENWIZ_CRM_DB` set. Newline-delimited JSON-RPC. Tools match the commands: `crm_schema`, `crm_object_add`, `crm_field_add`, `crm_record_create`, `crm_record_update`, `crm_record_search`, `crm_record_context`, `crm_associate`, `crm_activity_log`, `crm_ref_bind`.
- Errors an agent can branch on: `validation`, `unknown_object`, `unknown_field`, `not_found`, `conflict`, `object_mismatch`, `internal`.

A later skill, in the skills sense, is a short instruction file that tells any agent to call these tools, to read `context` before it writes, and to pass `if_revision` when it updates. The skill is not in this slice.

### Sync and import

Not in the slice. The design, when a later ticket builds it, is offline-first and then read-only:

1. Accept a fixture shaped like a Salesforce describe plus records, or a HubSpot properties list plus records. No network.
2. Map provider fields onto our fields only when the mapping names both sides. Unmapped fields are kept on the record as custom fields, not dropped silently and not guessed.
3. Upsert by the external binding. Write a checkpoint the caller can resume. A run that stops must say how far it got.
4. A live read of Salesforce or HubSpot waits for an explicit approval. It uses describe or the properties API first, stores the schema it saw, and treats a later describe change as drift to report, not as a surprise failure on write.
5. Subscriptions come after backfill. Salesforce Change Data Capture and HubSpot webhooks both deliver a hint. The connector hydrates the record, then writes it here. Gap events and webhook retries are checkpoints, not new kinds of record.
6. Writes back to a provider are a separate, later decision. Each writable field has a rule: who may write it, whether a blank overwrites, and whether a rejected row fails the batch or is reported beside the rows that landed. The slice does not write to a provider, and it does not deploy code into a customer org.

### Activity capture

Not in the slice, except that an agent can already log an activity with a source and a time. Later capture from Slack, email, GitHub and X creates a proposed activity with the source, the external id of the message, and the records it seems to concern. A rule or a person confirms it before it is treated as fact. Capture that writes straight into the CRM will record the wrong person and then automate on that mistake.

### What would make it better than the incumbents

Better for an agent, not a claim that this replaces a sales team's Salesforce.

| Today | This CRM |
| --- | --- |
| Salesforce and HubSpot schemas are whatever the admin saved, and two customers do not match | The same API creates a custom object and a person. Schema is a tool result |
| A read returns one row. Context is a fan-out the agent has to invent | `context` returns the record and one hop |
| HubSpot ids collide across objects. Pipedrive field keys are per-account hashes | External identity includes the object type, and our own field names are stable api names |
| Writes from an integration are hard to undo and easy to lose against a human edit | Partial update, a revision check, and a change row that names the actor |
| Attio enriched fields cannot be overwritten, and the agent is not told why in a uniform way | Every refusal is a code and a message. Nothing is silently corrected |
| Twenty is the closest open model, and it is a workspace product with its own server | This slice is one file an agent can open, with no account and no token |
| Close, Pipedrive and Folk each pick a different place for "the company" and "the process" | People and companies are facts. A deal stage is the process in the first cut. Attio-style lists, where the same person sits on several processes with different fields, are a later decision rather than a premature table |

The slice is not best-in-class yet. It has no pipelines as their own object, no permissions, no dedupe beyond the external binding, no full-text index, and no multi-hop query. Those are sequenced below so the first cut stays something an agent can run and a test can prove.

### MVP cut

The MVP is the slice in `products/crm`:

- SQLite file, standard objects, custom objects and fields, labeled associations, activities, change history, revision check, external bindings.
- The command line and the MCP server above.
- Tests in `products/crm/test_crm.py`, synthetic data only.

The MVP does not import, sync, capture, authenticate, or send a request. It does not add a Rust dependency.

### Roadmap

1. **This slice.** Local graph, agent surface, tests.
2. **Offline import.** Fixture files for a Salesforce-shaped and a HubSpot-shaped export. Idempotent upsert, stored mapping, checkpoint. Still no network.
3. **Process.** Pipeline and stage as data, required fields per stage, and a duplicate hint when email or domain matches. Decide whether a list, in the Attio sense, is a real object or whether a deal is enough.
4. **Skill.** The instruction file agents follow, plus any missing tool the skill cannot express with the current surface.
5. **Read-only connectors.** Salesforce and HubSpot, one installation each, after an explicit live-read approval. Schema cache, backfill checkpoint, hydrate-on-event. No write back.
6. **Capture.** GitHub first, then Slack, email and X, as proposed activities with provenance.
7. **Write-back.** Explicit per-field rules and a batch policy. Error categories mapped before the agent sees a provider body.
8. **Many installations.** One record per customer connection: auth health, schema version, checkpoint, last error. Region boundaries if a later product stores customer data in more than one place.

Each of 2 through 8 is its own spec or a ticket under this one, with its own proof. This draft does not pretend they are built.

## Changelog headline

An agent can store people, companies, deals and activities in a local CRM and read a record back with the records linked to it.

## User Stories

- An OpenWiz agent can record a person, the organization they belong to, and the last activity, and can read that context back in one call.
- An OpenWiz agent can represent a lead, such as a university application or an outside repository, as a deal or a custom object linked to a person, without a code change.
- A builder agent can add a field or an object at runtime and then write records through the same commands it uses for a person.
- A builder agent can refuse to overwrite a record when the revision it read is no longer current.
- A builder agent can bind a Salesforce or HubSpot id, including the object type, so a later import does not create a second row and does not merge two objects that share a number.
- Another agent's skill can point at a different database and use the same tools.

## Implementation Decisions

- The slice lives in `products/crm` and is not a Cargo workspace member. The workspace's approved crates are `serde`, `serde_json` and `rustix`. SQLite comes from the Python standard library, which adds no dependency. A Rust port waits on an approval for a new crate.
- Records are rows in one table. Field definitions and JSON values implement custom fields. The standard objects are seeded rows, not special code paths.
- Associations are their own rows. The first cut is one hop. Deeper queries are a later ticket.
- Activities are records. Capture sources are a field, not a new object per channel.
- The command line and MCP call the same store. MCP is newline-delimited JSON-RPC for the protocol versions named in the README. Tool failures are results with `isError` set, using the same error codes as the command line.
- The database path is chosen by the caller. The repository does not contain a database. Real relationship data stays out of git.
- No network library is imported. A test scans the package for that.
- `products/crm` is outside the paths the changelog check treats as non-product. There is no ticket number for a `changes/<ticket>.md` line yet. See Further Notes.

## Testing Decisions

- `python3 -I products/crm/test_crm.py` is the proof for this slice. It uses the standard library's test runner and temporary databases.
- Fixtures are synthetic. Mail addresses use `example.com`. No test opens a socket, and no test reads a secret.
- The store tests cover required fields, unknown fields, custom fields, partial update, revision conflict, select and number coercion, custom objects, association, activity rollback when a link is missing, soft delete, object mismatch, and external ids that collide across HubSpot object types.
- The surface tests run the command line and the MCP server as processes and check the JSON they print.
- Later import and connector tickets need their own fixtures. A passing test here does not prove a live Salesforce or HubSpot read. Connector work also needs the live check below, and an approval before the first live call.

## Live check

This slice does not touch a person's machine, account, or CRM. There is nothing to live-check until a connector ticket exists. That ticket's live check is a read of one approved installation, compared with the checkpoint the connector claims, and it does not include a write to the provider unless that write was itself approved.

## Proof

The slice is proven by `python3 -I products/crm/test_crm.py` and by the commands in [products/crm/README.md](../../products/crm/README.md). The proof is local and synthetic. The research claims in the notes are proven by the linked pages, not by this test.

## Out of Scope

- A live client for Salesforce, HubSpot, Slack, email, GitHub or X.
- OAuth, tokens, webhooks, Change Data Capture and any code deployed into a customer org.
- A web application, permissions, reporting, or a pipeline engine.
- Dedupe beyond the external binding, full-text search, and queries deeper than one hop.
- Hosting a multi-tenant service, region routing, and billing.
- Changing the OpenWiz command, the fleet records, or the Rust workspace.
- Treating this draft file as the live spec. ADR 0004 still holds.

## Further Notes

Open decisions:

- Confirm or rewrite this draft, then make it a parent issue. Until then the file contradicts ADR 0004 on purpose, as a review copy.
- The public name.
- Whether OpenWiz's own relationships and an agent product's relationships are two databases of this model, or whether they must be one database. This draft says two databases, one model.
- Whether a deal stage is enough, or whether Attio-style lists are required so one person can sit on a contributor process and an applicant process with different fields.
- Whether the implementation stays in Python or moves into Rust after a crate is approved.
- Which lead sources are in the first real workspace: contributors, partners, university applications, outside repositories.
- Who may approve a live read, and which installation is the first one. The factory rules already say a live read waits for approval.
- Whether high-risk fields are proposed by the agent and confirmed before they land, even in this CRM, or whether a passed revision is enough.
- How the changelog check should treat `products/crm`. The path is a product path, and there is no ticket number to name in `changes/`. The honest line waits on a ticket. Exempting it needs an explicit decision, because the changelog rule says the no-changelog label is not a way to skip a product change.
