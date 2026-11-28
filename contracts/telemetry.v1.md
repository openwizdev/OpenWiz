# Telemetry contract, version 1

SE1 of the 0.2.0 privacy and security spec (#3456). This contract defines
what may leave the owner's machine. The [settings contract](settings.v1.md)
owns the field names and defaults. The egress audit (SE1b, #3962) and its
copies (SE2, #3458) use the same reason forms and settings rows below.

## Allowed requests

- **Owner-started requests.** A fleet the owner starts may make its GitHub
  reads and writes. A harness may make its own model calls for the work the
  owner started. A driver the owner turns on may make calls to its configured
  host for the owner's work. The install command and each update the owner
  accepts may make the requests needed to complete that operation. The
  settings file's `updates` value is `ask`. Each update needs the owner's yes.
- **Opt-in requests.** The owner must turn on the applicable row in the
  current settings file before the request can leave the machine. A missing
  settings file or missing row grants no opt-in. Each opt-in starts off, and
  turning one on leaves the others off.

An outbound request outside these allowances is a breach. An owner-started
operation can make the calls needed for its work. Any report about the
factory sent alongside that work still requires `telemetry`.

## User telemetry

The settings file's `telemetry` row is the only user-telemetry toggle. It
defaults to `false`. While it is off, the factory sends no user telemetry,
including the market's anonymous receipts and install reports, the value
meter's shared aggregates, and any other report about the owner, their
machine, their work or their factory. A feature setting, including
`share_aggregates` in the [value meter contract](value-meter.v1.md), cannot
authorize an outbound report on its own or serve as a second user-facing
telemetry toggle. Outbound value-meter aggregates use `opt-in: telemetry`.

The owner's aggregate page, docs, install-click and download counts come
from the hosting platform's analytics and hold no per-person data. These
site counters are not user telemetry. That classification covers the
owner's read of the aggregate counts and gives factory code no permission
to send a report.

## Egress allow-list reasons

```json
{
  "reason_forms": ["owner-started: <what>", "opt-in: <settings row>"],
  "opt_in_rows": {
    "telemetry": "user-telemetry",
    "channels.<channel>": "owner-notifications",
    "keys.<key>.on": "credential-use"
  }
}
```

The JSON block is the allow-list policy the audit and its copies read.
Use `owner-started: <what>` with a brief description of the operation the
owner starts. Use `opt-in: <settings row>` with the concrete settings row
that gates the request, substituting names using the settings contract's
object-key rules. The table below gives the conditions for each row.

| Settings row | What it permits |
| --- | --- |
| `telemetry` | User telemetry when `true`. Every user telemetry request uses this row. |
| `channels.<channel>` | Delivery of notifications to the owner's chosen channel when its row is `true`. The fixed cockpit row `channels.t3` is excluded. |
| `keys.<key>.on` | A call to the service for which the owner enabled that opt-in credential, when both `opt_in` and `on` are `true` on that key. |

For example, `owner-started: fleet reads GitHub` names the operation, and
`opt-in: channels.sample-channel` names the setting for one notification
channel. Non-local drivers are off in a new settings file. Their host calls
for the owner's work use an `owner-started` reason. The fixed `local`
default and `updates: ask` supply no opt-in reason.

## Fixtures

Run `python3 -I contracts/fixtures/telemetry/test_fixtures.py`. The check
reads the settings contract's new-file fixtures and validates two telemetry
settings files against the settings schema and rules. The first has every
opt-in off. In the second, the owner has turned on only `telemetry`. The
check also pins the two reason forms and rejects a second reporting row in
the egress policy. This is offline fixture evidence. The egress audit
and live network proof are follow-up work.
