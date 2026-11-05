# Terminal v1

The pinned integration boundary for 0.0.12 T3–T6, from spec #1092 and the
confirmed CLI grill C1–C5. **Contract only in T1:** no terminal executable,
visual dependencies, service start or live action is delivered by this file.
The existing [web API](web-api.v1.md), [decisions](decisions.v1.md) and
[CLI](cli.v1.md) contracts remain authoritative. Screens use the accepted M6
Observatory language: dark canvas/sheet/panel, purple live/selected state, gold
only for Needs you, and readable words/shapes without relying on colour.

## Entry and settings

`openwiz` with no arguments launches Home only with terminal stdin **and**
stdout. `openwiz ui` explicitly opens the same Home and requires both terminals;
non-TTY `ui` refuses with a handled usage error instead of waiting. Piped
no-argument use prints bounded usage and exits 2. Explicit commands and all
JSON requests never enter raw mode, prompt or launch the visual executable.
`ui --json` returns only the CLI contract's capability document (0), without
connection, discovery or screen setup. `ui --help` returns usage; combined
syntactic `--json` returns JSON help. No general command is made interactive.

The CLI locates its own executable with `current_exe`, then selects only
`<that directory>/openwiz-terminal` (platform executable suffix if applicable).
No shell, PATH search, current-directory candidate or alternative executable.
Forward only parsed visual settings as distinct arguments; wait for the child
and preserve its exit. Missing/unusable sibling is an explicit unavailable
error, never a fallback to a service or another program. T3 proves this through
a pseudo-terminal and controlled installed siblings, without a production
fixture environment variable. `ui` becomes a shipped catalogue entry only
with that dispatch and capability implementation.

| Setting | Source and rule |
| --- | --- |
| TCP destination | Always IPv4 `127.0.0.1`; no hostname/address/URL option, DNS lookup, proxy, tunnel, TLS or remote transport |
| Port | `ui --port N`, one decimal 1–65535, default existing server port 7370; implicit no-argument launch uses the default |
| Guarded Host | `ui --allowed-host NAME` once, otherwise owner's `OPENWIZ_SERVER_ALLOWED_HOST`; absent means read-only availability |
| Host validation | Exactly the server's configured-public-DNS-name rule: no scheme, path, port, IP or loopback name; reject malformed explicit settings |

These settings describe an **already running** local server. The terminal does
not install/start/embed it, run room-cli or gh, add routes or bypass its guards.
Normal agent CLI/backend dependency graphs exclude ratatui/crossterm. Only the
separate visual crate owns the approved pair and necessary locked transitives.
No normal server dependency is permitted by this interface.

Read requests may use `Host: 127.0.0.1:<port>`. Guarded requests (including the
POST new-thread preview) use only the locally configured allowed host, without
a port, while the TCP peer remains loopback. Send exactly one `Host`,
`Origin: https://<configured-host>`, `Sec-Fetch-Site: same-origin`,
`X-OpenWiz-Send: 1`, `Content-Type: application/json`, and correct UTF-8
`Content-Length`, as the API requires. Never infer a public host from a
response, decision, repository or thread. Missing allowed-host configuration
disables guarded actions/previews with an explanation; loopback reads still
work. Refusal, bad configuration or connection failure is visible, never
worked around by weakening headers, retrying a write or changing transport.

## Common bounded reads

Home independently reads decisions, fleets and inventory; Sessions uses the
inventory/session routes and Fleets uses the fleet list/detail routes. It must
work without the unfinished cockpit aggregate. Retain each part's source
coverage, gaps, age and last good snapshot. No answerable proposal is invented
from fleet held/needs-info labels. Only complete fresh empty required coverage
permits an empty Needs you claim; unavailable parts remain unavailable.

The shell owns lanes keyed by read kind and target: decisions, fleets,
inventory, session detail, fleet detail, cloud options, action preview and
operation status. At most one read per kind is in flight (even when selection
changes); at most two read requests overall use the server's existing read
capacity. Navigation/manual refresh coalesces to the latest pending read for
that lane, never an unbounded queue. A stale completion cannot replace a newer
selection or change a bound draft. Old requests retain their lane until
completion or the existing 70-second client hold limit; do not overlap them
by declaring the screen late at 45 seconds. Closing a screen stops further
automatic reads; its already dispatched write is not cancelled or replayed.

Use the existing client timing choices: inventory lists 10 seconds after a
settled read, session details 15 seconds; fleet lists/details 60 seconds, with
failure delays 60/120/240/300 seconds. Decisions use the same conservative
60-second cadence/backoff as fleets and their contract's oldest-required-source
70,000 ms freshness threshold. Inventory failure delays are
2/4/8/16/30 seconds; show late at 45 seconds and stale retained inventory at
30 seconds. Preserve server-provided source freshness rather than resetting it
to receipt time. Manual refresh can request an earlier read through the same
lane. Honor Retry-After within the existing backoff cap. These are client
bounds, not new server timing or safety limits.

Transport uses standard-library TCP and the existing serialization crates.
One HTTP/1.x request per connection, `Connection: close`, no redirects, implicit
proxy, compression, pipelining or automatic retry of a guarded POST. Apply
bounded framing and reads: existing 16 KiB/64-header response-head bounds,
32 MiB body ceiling (the source-reader ceiling), and an overall 70-second
connection/request deadline. Reject malformed/truncated/oversized, wrong-type,
unknown-variant and duplicate-key JSON rather than treating it as empty data.
Non-success HTTP replies retain their status and safe reason; they do not
become success envelopes. These are transport resource bounds; no existing
send/create/text/attachment allowance is increased.

## Shared action seam (T3 supplies; T4–T6 implement modules)

T3 owns the common types/transport, shell, registry and test-module wiring.
It pre-registers `actions/answer.rs`, `actions/send.rs`, and
`actions/new_thread.rs`, plus each module's fixture-test entrypoint. Each module
exports `register() -> Option<Box<dyn Action>>`; until implemented it returns
`None`. The shell displays that entry as unavailable and cannot submit its
placeholder. No later action builder needs to edit shared routing, manifests,
registry or harness. Availability means a complete fixture-proved
screen → existing-route path, not merely a menu label.

The following types are the common Rust-facing interface (not new HTTP schemas).
T3 may choose private storage/layout behind them; their meaning is fixed:

| Type | Required data/variants |
| --- | --- |
| `ActionId` | `Answer`, `Send`, `NewThread`; capability ids `answer`, `send`, `new_thread` |
| `ActionSeed` | `Answer(DecisionBinding)`, `Send { session_id }`, `NewThread { project_id }`; exact verified identity, never a display-name guess |
| `DecisionBinding` | Subject kind/number and comment id; request id/fingerprint; optional question id; exact displayed proposal/recommendation/context; explicit risk; source freshness/currentness; verified configured target with its own freshness |
| `SendInput` | Target id, exact UTF-8 text, Queue/Steer, op id, resume-paused-queue and accept-possible-duplicate acknowledgements; attachments empty in this visual version |
| `NewThreadInput` | Existing project id, offered explicit harness/model/effort, exact prompt, op id; attachments empty |
| `ActionInput` | `Open(ActionSeed)`, `Edit { field, value }`, `Preview`, `Confirm { press_id }`, `Cancel`, `RefreshStatus`, `Snapshot { generation, data }`, `Response { request_id, result }` |
| `ActionView` | Exact target, draft fields, effects/preview age, safe status/reason, available controls and outcome/operation identity; no raw terminal escape bytes |
| `ActionResult` | Current `ActionView` plus zero or one `ActionRequest`; opening/editing/navigation/refresh cannot return a dispatch request |
| `ActionRequest` | `SendPreview { target, mode }`, `Send(SendInput)`, `Lookup { target, op_id }`, `Options`, `NewPreview(NewThreadInput)`, `Create(NewThreadInput)`, `Status { op_id }` |
| `TransportResult` | `Report { http_status, body }` (validated existing schema), `Refused { http_status, reason }`, `FailedBeforeDispatch { reason }`, `UnknownAfterDispatch { reason }` |
| `Attempt` | Action/operation id, immutable bound request, optional decision binding, preview generation, confirmation stage, dispatch marker, outcome, last status; retained by the shell independently of the visible screen |

`Action` supplies `id() -> ActionId` and
`update(&mut self, ActionInput, &ActionContext) -> ActionResult`. `ActionContext` supplies
read snapshots/generations, connection capability and the shell-owned attempt;
it exposes no arbitrary process execution or arbitrary URL client. Input
field ids are action-specific: answer mode/own words; send text/mode/explicit
acknowledgements; new project/harness/model/effort/prompt. Unknown fields or
wrong variants refuse rather than mutate another action. API request bodies
are constructed from those typed inputs under the web API contract, not from
an unvalidated JSON blob or screen label. Existing DTOs may be reused where
they obey the same rules, without a dependency on the server.

| Request | Existing route and report |
| --- | --- |
| SendPreview | `GET /api/v1/sessions/{id}/preview?mode=queue|steer`, `openwiz.send-preview.v1` |
| Send (also Answer) | `POST /api/v1/sessions/{id}/messages`, `openwiz.messaging.v1` |
| Lookup | `GET /api/v1/sessions/{id}/messages/{op_id}`, `openwiz.send-lookup.v1` |
| Options | `GET /api/v1/cloud-options`, `openwiz.cloud-options.v1` |
| NewPreview | `POST /api/v1/projects/{id}/threads/preview`, `openwiz.new-thread-preview.v1` |
| Create | `POST /api/v1/projects/{id}/threads`, `openwiz.new-thread.v1` |
| Status | `GET /api/v1/new-threads/{op_id}`, `openwiz.new-thread-status.v1` |

The shell retains status lookups after navigation and executes only these
routes. Preview is never dispatch, even the guarded POST preview. It records
an attempt before its first dispatch, then marks it dispatched before handing
it to transport. Repeated/held keys cannot enqueue another dispatch. A new
`press_id` requires a distinct key press/release, not an auto-repeat event.
A confirmation binds the exact target, settings/mode/text, displayed effects,
preview generation and decision fingerprint/risk/target. Any change invalidates
it. Number keys select a displayed identity; they never act or silently rebind
a selection after a reorder.

## Outcomes, unresolved operations and restoration

State progression: editing → previewing → ready → confirming → dispatching →
accepted/created, refused/failed, uncertain or in-progress. Live/release/publish
decision records require a separate second explicit confirmation after the
first; ordinary is an explicit classification, and unknown risk disables
answering. Answers require current unanswered wording, fresh complete required
sources and fresh verified configured orchestrator target. Preserve own-words
bytes without trimming, prefixing, splitting or truncation. “Yes” sends the
exact supported recommendation reply; simplify and summary/spec/plan answers
follow the decisions contract. Only the orchestrator records the answer or
approval. Accepted/uncertain answer remains unresolved until its record changes.

An attempt that may have dispatched is locked, with the same op id and immutable
binding. Timeout, disconnect, terminal interruption or missing/malformed response
is uncertain; a later local failure never downgrades it to safe-to-resend. Status
refresh is read-only and bounded by the same lane: send/answer lookups are
explicit; new-thread status/start uses the existing client's maximum ten
automatic reads per attempt, then explicit checks. Do not
automatically POST again. Accepted/created is not completion/start. Keep requested
mode/settings separate from reported delivery/configuration/start stage.

The shell retains unresolved attempts across navigation and restores any saved
attempt metadata after restart only for display/status reads. Save the op id and
binding privately before dispatch if restart recovery is offered; no transcript
or live identifier belongs in repo fixtures/evidence. If recovery is unavailable,
say so and direct the owner to the existing status command with its shown op id;
never imply a retry is safe. Terminal restoration/restart never replays a write.
Refused-before-dispatch can unlock only with explicit editing/new confirmation;
existing op-id reuse and possible-duplicate rules remain the backend's authority.

Restore cursor, raw mode and alternate screen on normal quit, handled failure
and interruption. Sanitize control/bidi/invisible characters for display while
preserving draft bytes for the actual request. Narrow/very small screens retain
navigation and scrollable target/effects/outcome information; no clipped target
may be confirmed. T3–T6 prove the real event path against recording fixture HTTP
and actual fake-source server routes, with renders and PTY cleanup/dispatch
cases. Live acceptance is T7 under ADRs 0015/0016, never inferred from this
contract, screenshots or fixture tests.
