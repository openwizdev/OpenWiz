# Local CRM

A small CRM an agent can run on one machine. It stores people, companies, deals, activities and custom objects in a SQLite file. The command line and the MCP server speak JSON. Nothing in this folder calls Salesforce, HubSpot or any other network service.

It is separate from the Rust workspace. The workspace only approves `serde`, `serde_json` and `rustix`, and a new crate needs approval. This slice uses the Python standard library.

The database can hold notes about real people. Keep the file outside the git checkout.

## Run

```sh
python3 -I products/crm/test_crm.py
python3 -I products/crm/crm.py --db /tmp/openwiz-crm.sqlite init
python3 -I products/crm/crm.py --db /tmp/openwiz-crm.sqlite record-create \
  --object person --set name=Ada --set email=ada@example.com
python3 -I products/crm/crm.py --db /tmp/openwiz-crm.sqlite context --id rec_...
OPENWIZ_CRM_DB=/tmp/openwiz-crm.sqlite python3 -I products/crm/mcp.py
```

`--db` or `OPENWIZ_CRM_DB` chooses the file. `--actor` is stored on each change and defaults to `agent`. Every command prints one JSON object. `ok` is true and `result` holds the payload, or `ok` is false and `error.code` is one of `validation`, `unknown_object`, `unknown_field`, `not_found`, `conflict`, `object_mismatch` or `internal`.

## Commands

| Command | What it does |
| --- | --- |
| `init`, `schema` | Create the file and list objects and fields |
| `object-add`, `field-add` | Add a custom object or field |
| `record-create`, `record-get`, `record-update`, `record-delete`, `record-search` | Records. Search skips deleted rows. Get still returns them |
| `associate` | A labeled link from one record to another |
| `activity-log` | An activity linked to one or more records with the label `about` |
| `context` | The record, one hop of linked records, and recent changes |
| `ref-bind`, `ref-get` | Bind or find `provider` + object type + external id |

`record-update` and `record-delete` take `--if-revision`. Pass the `revision` from the record you read. A newer write is refused with `conflict`. Omit it only when a lost update is acceptable.

`record-search --query` is a case-insensitive match on text and select fields. `--where name=value` is exact, after the field type is applied. `--set` and `--where` are repeated `name=value` pairs.

Field types are `text`, `number`, `boolean`, `date` and `select`. A select field needs `--option` values that are themselves api names. Dates are `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SSZ`.

## MCP

`mcp.py` reads newline-delimited JSON-RPC on stdin and writes it on stdout. It accepts protocol versions `2024-11-05`, `2025-03-26` and `2025-06-18`. The tools are `crm_schema`, `crm_object_add`, `crm_field_add`, `crm_record_create`, `crm_record_update`, `crm_record_search`, `crm_record_context`, `crm_associate`, `crm_activity_log` and `crm_ref_bind`. A tool error is a result with `isError` true and the same JSON shape as the command line.

## Standard objects

`person` (name, email, role), `company` (name, domain), `deal` (name, stage, amount) and `activity` (kind, summary, body, happened_at, source). Stage is `new`, `qualifying`, `proposal`, `won` or `lost`. Activity kind is `note`, `email`, `meeting`, `call`, `slack`, `github`, `x` or `other`. Custom objects use the same record API.

External ids include the provider object type. HubSpot record ids are unique inside one object, so contact `1001` and company `1001` are different bindings.
