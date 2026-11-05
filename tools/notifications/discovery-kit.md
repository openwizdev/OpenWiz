# 0.0.15 notification discovery kit — offline preparation

This is T2-P #2228's preparation for #2033, revised by T2-K #2507 for local
reads (Jake's J16 decision, 2026-11-13), not a live runner or permission to
read an endpoint/device. **Current state: blocked, actual inputs unknown.**
Only the offline commands below are available now. No provider is selected.

#2033 owns completing a private plan, the saved/read-back version-level OK,
execution, `docs/spikes/0.0.15-notifications.md` and the observed delivery binding.
Read that ticket's entire current gate thread before proposing or running it.
Its independent discovery/person/access/provider hold remains controlling;
PG1/graph approval and a newer contract approval do not release it. Preserve
spending, dependency, activation, publication/cut-over, exact-head review, CI
and M1 gates separately. No existing standing rule substitutes for that OK.

## Prepare without probing

Use existing private records supplied to #2033 to name the exact engine host,
owner account, installed candidate version/head/tree, the origin (either the
engine host's own loopback address or the authenticated HTTPS origin, below),
existing curl executable and, for HTTPS only, existing protected access-cookie
file. Name the
exact already-open, owner-authenticated browser context/device if available.
Do not discover these by connecting, reading a device, exporting cookies,
logging in, installing a tool or changing access during this preparation.
If the records are insufficient, ask on #2033; leave the plan blocked.

Copy the following template into an owner-only directory **outside Git**. Replace
whole JSON values, with no shell expansion. Real hosts/accounts, paths, cookies,
context ids, approval evidence and raw results never belong in this document or
public evidence. Nulls deliberately refuse. Synthetic fixture acceptance is not
proof that any actual endpoint or capability exists.

```discovery-plan
{
  "schema": "openwiz.notification-discovery-plan.v1",
  "version": "0.0.15",
  "candidate": {"version": "0.0.15", "head": null, "tree": null},
  "engine_host": null,
  "account": null,
  "origin": null,
  "curl": null,
  "cookie_file": null,
  "bounds": {
    "elapsed_s": 300, "request_s": 10, "response_bytes": 65536,
    "requests": 5, "browser_reads": 1, "retries": 0
  },
  "effects": {
    "permission_prompts": 0, "subscriptions": 0, "notifications": 0,
    "cloudroom_sends": 0, "cloudroom_starts": 0, "restarts": 0,
    "purchases": 0, "access_changes": 0, "credential_changes": 0
  },
  "reads": [
    "/api/v1/health", "/api/v1/setup", "/api/v1/notifications/status",
    "/sw.js", "/manifest.webmanifest"
  ],
  "browser": {
    "availability": "unknown", "host": null, "account": null,
    "context": null, "gap": null
  },
  "privacy": "owner-only-no-raw-output",
  "stop": "first-refusal-no-retry"
}
```

`browser.availability` must become `available` with the named existing host,
account and context and a null gap, or `unavailable` with those three fields null
and a concrete gap. Unknown refuses; unavailable skips the browser read and
keeps phone evidence Unverified. The cookie input is a file path, never cookie
content.

`origin` takes one of two forms; nothing else validates:

- **Loopback (J16):** exactly `http://127.0.0.1:<port>` or `http://[::1]:<port>`,
  the engine's own local address read on the engine host itself, with a literal
  port 1 to 65535 and no user info, path, query or fragment. `cookie_file` must
  be `null`. `localhost`, any other host name or address, and any encoded or
  alternative spelling of a loopback address refuse, as does a cookie file.
- **HTTPS:** an exact `https://` origin with its existing protected
  access-cookie file, unchanged from T2-P #2228.

The online (Access) address, Access login and the owner-only authenticated open
stay **Unverified until T8 #2040**. A loopback read reaches only the engine on
its own host: it establishes no phone, remote or background-delivery claim, and
no claim about the online address or its access control. The loopback form
reads no cookie and approves no cookie file, Access login or export.

This bounded curl variant requires an existing POSIX command/access
path: if the selected installation cannot use it, stop for a revised kit, rather
than exporting credentials, inventing a command or weakening authentication.

Run only these **offline** commands from the checkout:

```sh
python3 -I tools/notifications/test_discovery_kit.py
python3 -I tools/notifications/test_discovery_kit.py --check /private/run/discovery-plan.json
```

The example private filename is synthetic. Tests use synthetic inputs only;
`--check` reads only the explicitly supplied local JSON. Neither command probes
paths, resolves hosts, reads cookies or runs a plan. Exit 2 means refused, with
no input echoed. Exit 0 reports `offline_valid_for_review`, a canonical JSON
SHA-256, counts, `live_authority: false` and `phone_display: Unverified`.
Validation proves structure, not installed identity, command safety on the target,
endpoint support, approval authenticity or live behaviour. It never fetches the
approval record. The pinned kit and this limitation must accompany the digest.

## Approval packet for #2033, before the first live read

Attach the completed plan and the five exact argv arrays below privately for
manual review. The validator accepts no arbitrary command field and has no
execution mode.
Bind the exact kit commit, plan digest, installed candidate, hosts/accounts,
existing authentication context, these bounds and every step below to the OK.
Save Jake's version-level approval in a private comment and read it back, along
with #2033's fresh gate dispositions. Validate the same unchanged bytes again.
An offline pass supplies no approval. Any changed command, host, account,
candidate, scope, count or kit revision requires an updated packet and OK.

Existing private records must already establish the selected executable's help/
provenance, the HTTPS form's cookie file ownership and the origin-to-engine/account
mapping (for loopback, that the reads run on the named engine host itself). An
unknown command/capability refuses; this kit adds no help, filesystem or device
probe to discover them. Run only with the reviewed environment,
without proxy/CA overrides, curl configuration or injected credentials. No
install, account creation, credential export or extra provisioning is included.
A live read itself may leave normal server access logs; that privacy boundary
must be covered by the OK. Do not run on an unapproved host to validate access.

## Exact read-only steps after that OK — #2033 only

For each route below, once, in order, the reviewed argv is:

```text
[curl, "--disable", "--silent", "--show-error", "--request", "GET",
 "--proto", "=https", "--max-redirs", "0", "--connect-timeout", "5",
 "--max-time", "10", "--max-filesize", "65536",
 "--write-out", "%{stderr}status=%{http_code} type=%{content_type} bytes=%{size_download}\n",
 "--cookie", cookie_file, "--url", origin + route]
```

For a loopback `origin` (`cookie_file` is `null`), the reviewed argv is the same
except `--proto =http` and no `--cookie`:

```text
[curl, "--disable", "--silent", "--show-error", "--request", "GET",
 "--proto", "=http", "--max-redirs", "0", "--connect-timeout", "5",
 "--max-time", "10", "--max-filesize", "65536",
 "--write-out", "%{stderr}status=%{http_code} type=%{content_type} bytes=%{size_download}\n",
 "--url", origin + route]
```

Use the HTTPS argv only with an HTTPS origin and the loopback argv only with a
loopback origin; never mix them. Every other flag, bound, effect counter, step,
stop rule and privacy rule below is the same for both forms.

Here `curl`, `cookie_file` and `origin` are the exact private plan values, not
shell variables or an invitation to interpolate a shell command. Do not add
`--location`, `--insecure`, verbose/header tracing, a request body, another method
or retry. Capture the body on stdout and status/type/size metadata plus errors on stderr
only in owner-only files, never shared logs. Check both the process exit and
HTTP status/type; curl exit zero alone does not mean HTTP success.

| Step / exact route | Read and interpretation |
| --- | --- |
| 1 `/api/v1/health` | Bind reported installed service version to the selected candidate using existing private install provenance. A version string alone proves no commit/tree. |
| 2 `/api/v1/setup` | Record independent engine/access prerequisites. Missing/refused/unknown stays so; local readiness never means phone readiness. This route must create no state or provider process. |
| 3 `/api/v1/notifications/status` | Record actual capability/permission/subscription/outcome status only. Off/unavailable/unsupported/failed/uncertain remains explicit. A documented route may be absent; absence stops this run and is a limitation, never a fabricated working binding. |
| 4 `/sw.js` | Inspect installed worker bytes, declared push/click handling and shell-only caching. Do not execute/evaluate the fetched code, register or update a worker. Compare with candidate provenance. |
| 5 `/manifest.webmanifest` | Inspect installed app scope/start URL/display metadata. Metadata or worker code alone proves no supported installed-phone delivery. |

At most **five HTTP requests**, one at a time, **10 seconds and 64 KiB per
response**, **300 seconds total** including the optional browser read. A failed,
timed-out or uncertain request consumes its slot; no retry. Stop rather than
truncate an oversized response and call it evidence. Redirects/login pages,
401/403, non-success status, unexpected type/shape, a candidate/access mismatch,
unread source, changed gate or need for any effect stops the run. Do not follow
an authentication redirect or test a different endpoint/account to repair it.

If `browser.availability` is available and its device portion is explicitly
covered by the OK, evaluate the following expression **once**, for at most
10 seconds, only in the exact existing authenticated context at the approved
origin. Use existing browser tooling; no new tab/navigation, reload, refresh,
network fetch, permission prompt, service-worker registration or subscription.
If tooling cannot bound this evaluation, stop and revise the kit.

```javascript
JSON.stringify({notification:typeof Notification==="undefined"?"unsupported":Notification.permission,push:typeof PushManager!=="undefined",worker:!!navigator.serviceWorker?.controller,standalone:matchMedia("(display-mode: standalone)").matches})
```

This reads feature/permission/install indicators only. Do not call
`requestPermission`, `subscribe`, `getSubscription`, `showNotification`, update,
unregister, or any send/start API. Never collect an endpoint, key or token.
An available emulated browser is labelled **emulated**, not actual phone proof.
No actual device interaction is authorized by standing LV1 alone.

## Stop, record gaps, hand over

There are **zero** permission prompts, subscription changes, submissions,
CloudRoom sends/starts, service restarts, purchases or access/credential changes.
No permanent notifier, scheduler, polling agent, watcher or page refresh is
created. Finish the bounded pass and end the turn; do not wait awake for a gate.
Stop on the first refusal or uncertainty; retain partial evidence without rerun.

Keep raw evidence owner-only (directory 0700, files 0600), outside public Git.
Never log cookies, auth headers, subscription endpoints/keys, private text or
browser context ids. Record sanitized route labels, counts, elapsed times,
candidate match/mismatch and explicit gaps in #2033's spike record; keep the
private approval/plan pointer separate from public technical summaries. Close
only tooling opened by this pass; none is needed here. Do not delete existing
cookies, subscriptions or other owner resources as cleanup.

#2033 must separately report installed app/configuration provenance, authenticated
access/refusal boundary, permission/subscription capability, engine-to-delivery
interface, feasibility with the cockpit closed and actual-phone availability.
These five reads and capability expression can establish **limitations**, but
cannot submit a notification, prove authenticated tap/refusal end to end, or
observe closed-cockpit display. An unsupported/insufficient interface stays
unsupported/Unverified and does not unblock T4 #2035. If discovering a sufficient
binding needs another read or any effect/provider/account/dependency/access
choice, return for a revised kit/explicit decision; never guess or buy a service.

PA5/PA8 here are **offline kit-integrity fixture proof only**. Documentation,
emulation, feature presence, ready state and dispatch acceptance never mean
phone receipt. #2040 retains candidate-bound live smoke and actual supported
phone background-display/tap evidence; unavailable device coverage stays
Unverified. ADR 0018 permits live checks alongside earlier versions, while
publication remains ordered and separately authorized. Native Mac coverage
keeps its existing gate. This kit activates, publishes and cuts over nothing.
