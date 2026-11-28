# API check for a new driver

Before writing the driver, read the vendor's own CLI or API documentation.
For each finding, record the source URL and the date you read it. This is a
documentation check. Leave live runs to [the live-check ticket](https://github.com/openwizdev/OpenWiz/issues/3491).

Under [driver v1](../../kernel/driver.v1.md), find how to start one agent on
one ticket, wake that same agent and stop everything its run started. Record
the exact CLI commands or HTTP methods and paths, the IDs each call uses,
and the field or command that distinguishes a running turn from a finished
one. Name each operation that starts a machine or incurs charges, including
what stops billing.

Check the vendor's own signed-in CLI first (N2). If a key-taking HTTP API is
the only route, record it and use driver v1's key helper (N4). The key host
is registered through its approved WizMarket listing as specified in
[#3005](https://github.com/openwizdev/OpenWiz/issues/3005). Keep credentials
out of the record. [Driver v1 login rules](../../kernel/driver.v1.md#2-logins).

## Ticket comment

Post one plain-text comment on the driver ticket before any code. Its first
line is exactly `openwiz:api-check v1`. Its second line is `result: pass`
when all three operations are documented and programmable, or
`result: later: <one-line reason>` when a required operation is missing.
Add one finding per line in the order shown below. Include its source URL
and read date. For a missing operation, cite the vendor page you checked and
say what is missing. A `later` result goes in the driver's WizMarket listing
with the reason, and the driver waits there.
[Driver roster spec](https://github.com/openwizdev/OpenWiz/issues/3474).

### Synthetic pass

```text
openwiz:api-check v1
result: pass
start: examplectl run create --repo <owner/repo> --ticket <number> returns <run-id> — https://example.com/cli#create (read 2026-01-01)
wake: examplectl run resume <run-id> resumes the same agent — https://example.com/cli#resume (read 2026-01-01)
stop: examplectl run stop <run-id> ends the turn and deletes its machine — https://example.com/cli#stop (read 2026-01-01)
running: examplectl run status <run-id> reports turn=running while the agent works — https://example.com/cli#status (read 2026-01-01)
cost: create starts a billed machine, resume can start another billed turn, and stop ends billing — https://example.com/billing (read 2026-01-01)
login: the vendor's own signed-in examplectl CLI supports all three operations (N2) — https://example.com/cli#login (read 2026-01-01)
```

### Synthetic later

```text
openwiz:api-check v1
result: later: the vendor offers no programmable stop
start: POST /v1/runs with repository and ticket returns <run-id> — https://example.org/api#create-run (read 2026-01-01)
wake: POST /v1/runs/<run-id>/resume resumes the same agent — https://example.org/api#resume-run (read 2026-01-01)
stop: the API lists no stop operation and the dashboard is the only way to stop the run — https://example.org/api#run-operations (read 2026-01-01)
running: GET /v1/runs/<run-id> returns turnState=running while the agent works — https://example.org/api#get-run (read 2026-01-01)
cost: starting provisions a billed machine and the dashboard stop ends billing — https://example.org/pricing#machines (read 2026-01-01)
login: the vendor documents a key-taking HTTP API and no signed-in CLI, so the key helper would be required (N4) — https://example.org/api#authentication (read 2026-01-01)
```
