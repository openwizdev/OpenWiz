# OpenWiz web access: setup guide and security model

How an owner can reach their own `openwiz-server` from their own browsers, across networks, with only them let in. **Placeholders only:** `<openwiz-hostname>`, `<your-domain>`, `<team-name>`, `<owner-email>`, `<aud-tag>`, `<tunnel-name>`, `<port>`, `<web-dir>`. Never commit real values.

**Status.** The access path below (Cloudflare Tunnel plus Access) is OpenWiz 0.0.2's, decided by the owner and checked live on one installation (A1 and A3, 2026-10-30). The **send route** (OpenWiz 0.0.3, #9), the **new-thread routes** (OpenWiz 0.0.4, #12) and the **attachment routes** (OpenWiz 0.0.4, #16) are proven on fixtures only and have never sent, created or uploaded anything live: run the write checks in [Check it before using it](#check-it-before-using-it) on your installation before any real send, create or upload, and send, create or upload nothing without the owner's go-ahead.

## Choose phone access in setup

Open `/setup`, expand **Phone access**, and choose **Cloudflare Tunnel + Access**
or **Tailscale**. These choices show instructions; they do not create an account,
change DNS, activate a tunnel or authorize a write. Phone readiness is independent
of the local connections and engine. A running tunnel is insufficient evidence.

For Cloudflare, you need a Cloudflare account, a domain managed there, Zero Trust,
and `cloudflared` on the engine host. Review the effects before approving them:
one named tunnel, DNS for its HTTPS hostname, an Access application covering all
paths with only the owner allowed, and origin-side Access validation. Cloudflare
handles traffic at its edge, including prompts and attachments. The configuration
below keeps the server on loopback. No quick tunnel or weakened request guard.
Cloudflare documents [origin-side Access validation](https://developers.cloudflare.com/tunnel/reference/origin-parameters/).

If you lack an account or domain, stop here or choose Tailscale. Obtain explicit
approval before any account, domain or paid-plan purchase; no hidden purchase is
part of installation. Check current provider terms rather than assuming a free
allowance from this guide.

For Tailscale, sign in on both the phone and engine host. Use private
[Tailscale Serve with HTTPS](https://tailscale.com/docs/features/tailscale-serve)
to the loopback server, keep Funnel off, and configure
[access rules](https://tailscale.com/docs/features/access-control/acls) for only
the owner and the selected engine host. Tailscale's default allow-all policy
does not establish owner-only access. A managed domain is not required; review
the permissions and any cost of enabling HTTPS first. Configure the server's
allowed host as that HTTPS hostname and preserve the existing host, origin,
content-type, custom-header, request-id and once-only write checks.

Before reporting either route ready, verify that the owner can read the page
and that unauthenticated, expired and foreign identities cannot reach the
origin or any allowed write. Run the write refusals with synthetic recording
executors, under the applicable testing approval. Merely getting an OpenWiz
refusal is not proof of edge authentication: the request already reached the
server. Native/provider operation and real-account readiness remain separate
live evidence.

After an expired or denied session, sign in again. After network loss or a host
restart, restore the same authenticated route and recheck it before relying on
phone readiness. Keep the draft and operation ID. Read the operation's status
to reconcile a lost reply; do not replay a send or create on reconnect. A later
denial does not establish that an earlier uncertain write never happened.
Refreshing setup only reads the report.

The packaged verifier is `runtime/access/access.py`. Ask the installing agent
to [preview its effects and verify the configured route](../tools/install/access/README.md)
with an owner-only plan and protected credential files, then refresh setup.
It records a durable `configure_access` operation and checks the same resource
after a lost reply; it creates or activates nothing. Automated Cloudflare
verification supports remotely managed named tunnels. It authenticates each
probe cookie's signature, team and app audience, checks that the hostname's
proxied DNS record selects that tunnel, and checks every connector's loaded
configuration version before and after probes. Missing evidence stays unknown;
signature checks use setup's existing `/usr/bin/openssl` prerequisite. The locally managed
recipe below remains a manual route whose running configuration this verifier
cannot establish. Tailscale verification checks current device authorization,
private Serve and the active owner-only policy using the provider's read-only
deny test. Actual network/client enforcement remains a separate live check.

## Security model

- **One owner per installation.** The server reads the owner's sessions through the owner's own `room-cli` login on the owner's own Mac. Nothing is shared or hardcoded.
- **The server listens on `127.0.0.1` only.** Nothing on the LAN can reach it, and no inbound port is opened anywhere.
- **Two writes: the owner's send and the owner's create.** `POST /api/v1/sessions/{id}/messages` sends one text message to one existing thread through the core's `send`, exactly as `openwiz send` does (`contracts/web-api.v1.md`, "Sending"). `POST /api/v1/projects/{id}/threads` creates one new Cloud thread in one existing project through the core's `new_thread`, exactly as `openwiz new --yes` does ([Creating a thread](#creating-a-thread-the-second-write), "Creating" in the contract). Both may carry **attachments**: files the owner uploaded first, by their ids. Two more requests change only the Mac's own disk, never CloudRoom: `POST /api/v1/attachments` copies one file the owner chose in the browser to the Mac, and `DELETE /api/v1/attachments/{id}` deletes one such copy ([Uploading attachments](#uploading-attachments-the-upload-addendum)). Every other route is a `GET` that never sends, creates or uploads, except the new-thread preview, a `POST` only because it carries the prompt, which claims and creates nothing. There is no retry, launch, approval or other write route, and no route that returns an uploaded file.
- **Identity is checked by the tunnel, not the server** (owner decision WS-1 (a)): Access at the edge, then `cloudflared`'s `originRequest.access` check before anything reaches the Mac. The server never reads an Access header or cookie.
- **A send, a create, an upload or a removal must come from the site's own page:** the configured host name in `Host` (never loopback), `Origin: https://<openwiz-hostname>`, `Sec-Fetch-Site: same-origin`, `X-OpenWiz-Send: 1`, and the body's own type (`Content-Type: application/json` for a send or a create, `application/octet-stream` for an upload, none for a removal). No CORS header is ever sent. So another site's page in your browser cannot send, create, upload or remove, and a page opened on `http://127.0.0.1:<port>` cannot either. **Without `--allowed-host` there is no send, create, upload or removal at all**, and `--allowed-host` must be your public host name: the server refuses to start with a loopback name (`localhost`, `*.localhost`) or an IP address.
- **Only the owner gets through,** because Cloudflare Access sits in front of the one public hostname, and the tunnel can refuse requests without a valid Access token.
- **The server refuses foreign `Host` headers** (`421`), which stops DNS-rebinding pages from reading it. This is not authentication.
- **Trust boundary (new with the send):** any process on the Mac can reach the loopback server, just as it can run `openwiz` or `room-cli`, and it can forge every header above, so **any process on the Mac, of any user, can send, create threads, and upload and remove attachments, as the owner through the server.** On a single-user Mac that is the reach the owner's own processes already have through `openwiz send`, `openwiz new --yes` and `openwiz attachment` (owner decision WS-9: accepted and recorded; A-13 extends it to creates, B-9 to uploads). Do not run it on a Mac shared with other users or untrusted local services. Browsers on the Mac can make it read, but cannot read its answers (no CORS).
- **One send record.** The server opens the same send record as `openwiz send` (`$OPENWIZ_STATE_DIR`, else the owner's default state directory), so the CLI and the web share op-id claims: an op id is sent at most once, from either. Run the server as the owner, with the same environment as the CLI.
- **The message text** is never logged, never in an error, and never in an answer (only its SHA-256 and length). While the call runs (up to 15 s) it is an argument of `room-cli thread tell`, so other processes on the Mac can see it in the process list (WS-13).
- **Privacy:** TLS ends at Cloudflare's edge. Session titles, purposes and final output pass through Cloudflare in the clear, and so does **every message you send, every new thread's prompt and every file you upload** from the web page (owner decision WS-11: accepted, as A-2 extended; A-13 extends it to new-thread prompts, B-1 and B-9 to uploaded files). Files go unchanged, with whatever metadata they hold (B-10). Decide whether you accept that before you set this up.
- **Not used:** Quick Tunnels (`trycloudflare.com`). They have a random, changing hostname and no Access application in front.

## Creating a thread (the second write)

**The creation addendum** (owner decision A-13; written before any route code, as A-13 requires). OpenWiz 0.0.4 adds one write, `POST /api/v1/projects/{id}/threads`: the core's `new_thread`, as `openwiz new … --yes --json`. The full shape is in `contracts/web-api.v1.md`, "Creating".

Source: Jake, 2026-10-30: A-13 requires the creation addendum before implementing its routes ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).

**The WS decisions apply unchanged** (0.0.3's sheet, WS-1 to WS-14). Nothing about the guard is new; only what a forged write costs is.

| Decision | For a create |
| --- | --- |
| WS-1 (a) | The owner is checked by the tunnel: Access at the edge, then `cloudflared`'s `originRequest.access`. The server never reads an Access header or cookie |
| WS-4 | Checked before anything is read, claimed or created: `Origin: https://<openwiz-hostname>`, `Sec-Fetch-Site: same-origin`, `Content-Type: application/json`, and the custom header, `X-OpenWiz-Send: 1` (WS-4's name, kept: one header for every `POST`, so the page sends one set of headers). No CORS |
| WS-5 | The Access cookie is `SameSite=Lax`: recorded, never relied on |
| WS-6 | Only the configured public host name may create; never a loopback `Host`. Without `--allowed-host` there is no create |
| WS-7 | The page makes the op id (`web-<32 hex>-c<n>`) with the draft, stores it before the request leaves, and reuses it on every repeat, reload and tab. The core binds it to the project, harness, model, effort and the text's SHA-256: the same op id is created at most once, and with anything else it is refused as conflicting reuse |
| WS-8 | The launcher says **not created** only when the answer proves the request never reached the core (Access's `401` or redirect, or OpenWiz's own refusal before the core). Every other unanswered request is **uncertain** |
| WS-9 | Any process on the Mac can create through the loopback server, as it can run `openwiz new --yes`. Accepted on a single-user Mac |
| WS-10 | The prompt, op id, project, settings and hash are never logged: one line of method, route template, status and time |
| WS-11 | The prompt passes Cloudflare's edge in the clear, like every message sent from the page (A-13: WS-11's consent extends to new-thread prompts) |
| WS-12 | One project, from the path. Body at most 99 328 bytes, strict JSON, a 40 s deadline, and the core run is never cancelled; **one create at a time** (A-14), apart from the sends and reads |
| WS-13 | The prompt is an argument of `room-cli thread spawn` for up to 15 s, visible in the process list, as with `openwiz new` |
| WS-14 | A prompt starting with `-` gets no rule of the route's own: the adapter passes it as `--prompt`'s one argument, last (inferred, not observed for `spawn`: the live check's dash prompt, L-3) |

**What a forged create costs.** A forged send messages a thread the owner already has. A forged create costs more, in one of the owner's existing `standard` projects with a GitHub remote (A-5):

- **a new Cloud sandbox,** woken and cloned from the project's default branch on GitHub;
- **a copy of the project's `.env` files** from the Mac into that sandbox, with whatever secrets they hold;
- **one Cloud agent from the owner's plan,** running with full permissions inside its sandbox, on a prompt and with a harness, model and effort the forger chose (only combinations CloudRoom offers);
- **the Mac kept awake** until the start is confirmed.

These are the effects the core shows before pressing (the preview, below), so the owner sees them for every real create too. Nothing outside that one project is touched: no new project, no Local thread, no other thread.

**Who could forge one, and what stops them:**

- **Anyone on the internet:** Access at the edge and `cloudflared`'s check at the origin; a request without the owner's Access session never reaches the Mac.
- **Another site's page in the owner's signed-in browser:** WS-4 (`Origin`, `Sec-Fetch-Site`, the custom header and the JSON content type) refuses it before any read. A cross-site form or simple request can't carry the custom header or the JSON type, and a cross-origin `fetch` that does is preflighted and gets no CORS answer. WS-5's `Lax` cookie is a second, unrelied-on layer.
- **A page served from loopback:** WS-6 refuses any create whose `Host` is not the public host name (`421`).
- **A replay of a captured request:** the same op id with the same body replays the recorded outcome, with no call; the same op id with anything else is conflicting reuse. A replay under a new op id is a new create, and only a request that already passes Access as the owner, or a process on the Mac (WS-9), can make one.
- **A process on the Mac:** not stopped (WS-9). It could equally run `openwiz new --yes` or `room-cli` itself.

**No retry and no automatic second create** (sheet A-3). An uncertain create stays uncertain, and the owner resolves it in CloudRoom. The page's **Refresh status** is a `GET` of the record (`GET /api/v1/new-threads/{op_id}`): it never creates. A repeat of the same op id (a double press, a reload, a second tab, Try again after no answer) is created at most once.

**The preview is a `POST`, but never a write.** `POST /api/v1/projects/{id}/threads/preview` is the core's `preview_new_thread`, as `openwiz new … --json` without `--yes`: the reads a create makes (the version, the project list, the catalogue) and the effects above, so the launcher shows them before pressing. It is a `POST` only because the prompt is too long for a URL. It takes the same body and passes the same WS-4 and WS-6 checks as the create, claims nothing, writes no record and never calls `spawn`.

## Uploading attachments (the upload addendum)

**The upload addendum** (owner decision B-9; written before any route code, as B-9 requires). OpenWiz 0.0.4 lets the page attach files to a send or a new thread. The full shapes are in `contracts/web-api.v1.md`, "Attachments".

Source: Jake, 2026-10-30: B-9 requires the upload addendum before implementing its routes ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).

| Route | Same as | What it does |
| --- | --- | --- |
| `POST /api/v1/attachments` | `openwiz attachment add <file> --json` | Copies one file the owner chose in the browser to the Mac's attachment store, and verifies it there |
| `GET /api/v1/attachments` | `openwiz attachment ls --json` | The staged attachments: names, sizes, kinds, hashes and states. **Never their bytes** |
| `DELETE /api/v1/attachments/{id}` | `openwiz attachment rm <id> --json` | Deletes one staged copy, unless an operation may still use it (B-6) |
| The send and the create | `--attachment <id>` | `attachments`: a list of staged ids, through the core's one gate (B2): every one ready and free, or nothing is sent or created |

**What "ready" means.** An upload copies the bytes to the controller (the Mac) and verifies them there; `ready` means only that. It sends nothing to CloudRoom and starts nothing. The bytes reach CloudRoom only when the owner presses Send, Queue or Start thread with that attachment.

**The WS decisions apply unchanged** (0.0.3's sheet, WS-1 to WS-14). B-9 only adds the upload's own body and bounds.

| Decision | For the attachment routes |
| --- | --- |
| WS-1 (a) | The owner is checked by the tunnel: Access at the edge, then `cloudflared`'s `originRequest.access`. The server never reads an Access header or cookie |
| WS-4 | An upload and a removal are checked before anything is read, staged or deleted: `Origin: https://<openwiz-hostname>`, `Sec-Fetch-Site: same-origin`, `X-OpenWiz-Send: 1`, and no CORS. **An upload's body is raw:** `Content-Type: application/octet-stream`, exactly, and never `multipart/form-data` or any other type (`415`). The file's name travels in one header, `X-OpenWiz-Name`, percent-encoded. A removal has no body. The list is a `GET`, like every read |
| WS-5 | The Access cookie is `SameSite=Lax`: recorded, never relied on |
| WS-6 | Only the configured public host name may upload or remove; never a loopback `Host` (`421`). Without `--allowed-host` there is no upload or removal |
| WS-7 | An upload has no op id: each one is a new copy under a new id (`att-` and 32 random hex digits, the store's). A repeated upload costs disk space, never a send. The page keeps the draft's ids, with its text, in this tab's storage, and sends them with the send's or the create's op id, which binds them (B2) |
| WS-8 | The tray says **ready** only after the server's ready answer. An upload whose answer never came is **failed (connection lost)**: the page can't know whether a copy became ready on the Mac. If one did, nothing claims it, and it becomes eligible for cleanup 24 hours after it became ready (B-2); deletion waits for an attachment operation to sweep the store |
| WS-9 | Any process on the Mac can upload, list and remove through the loopback server, as it can run `openwiz attachment`. Accepted on a single-user Mac |
| WS-10 | Never logged: the file's name, bytes, size, SHA-256, kind or id. One line of method, route template, status and time. No store error reaches an answer (it can carry a path) |
| WS-11 | The bytes pass Cloudflare's edge in plaintext (B-1's consent; below) |
| WS-12 | An upload's body is at most **25 MiB** (26 214 400 bytes: the core's per-file limit, the largest provider limit), with `Content-Length` (`411` without; `413` over, before a byte is read; `Transfer-Encoding` refused). **2 uploads at a time**, apart from the sends, creates and reads, each waiting up to 5 s for a slot, then `503`. **110 s** from the end of the head for the whole upload (B-9: under Cloudflare's 125 s). Streamed in 64 KiB pieces, never held whole. The send's and the create's bounds are unchanged: their 99 328-byte body now carries the text and the ids together |
| WS-13 | No `room-cli` call: an upload runs `/bin/df` for the free-space check; the list and a removal run no subprocesses. The bytes reach `room-cli` later, as a staged path (B-7) |
| WS-14 | The file's name is the owner's, untrusted text: never a path the server opens or a directory it writes into. It must be one file name (1 to 1 024 bytes, no `/` or NUL, not `.` or `..`; `400` otherwise). The core makes the staged name; the original is shown only as plain text |

**Threats, and what stops each:**

- **Bodies up to 25 MiB.** The cap is checked on `Content-Length` before a byte is read. A body is never read past its `Content-Length`; one that ends early stages nothing. Memory stays at 64 KiB pieces.
- **Slow uploads.** The 110 s deadline covers the whole body; a body still arriving then is `408`, and its partial copy is deleted. A slow upload holds one of the two upload slots meanwhile, never a send, create or read slot: two slow uploads can delay a third by up to 110 s, and nothing else.
- **Many uploads at once.** 2 at a time (B-9). The page itself uploads at most 2 at a time; a third request waits up to 5 s, then gets `503`, and nothing is staged. Connections stay capped at 32.
- **Filling the disk.** The store checks the 1 GiB free-disk floor (B-3) against the upload's size on its first bytes, before it writes anything (`failed (low disk)`); the body streams straight into the store's staging, with no other file. An unclaimed ready copy becomes eligible for cleanup after 24 hours (B-2). Attachment uploads, lists and removals sweep the store when they reach it; there is no background cleanup. Idle time or a server restart alone does not delete an expired copy. Copies whose operation is dispatching or uncertain are kept (B-6), including after recovery. **Stagings at once never spend the same room:** each measures the free space and reserves its size in one locked step, counting what every other staging in progress still needs, so two uploads (or an upload and `openwiz attachment add`) can't together cross the floor; a stopped one's reservation goes with it. There is no count cap (decided): the floor limits new staging, while the time-to-live makes unclaimed copies eligible for a later sweep.
- **Bytes are never served back.** No route returns an attachment's bytes: the upload answers with the store's record (id, name, size, kind, SHA-256), the list with the records, a removal with what it removed. So an uploaded HTML or SVG file can never run as a page of this origin, where a script could send and create, and no page can make the server echo content. **Thumbnails come from the browser's own copy** of the file the owner just chose (an object URL), only for PNG, JPEG, GIF and WebP detected from its first bytes; the page's CSP gains `img-src blob:` for them, and nothing else. After a reload there is no preview.
- **Cross-site uploads (CSRF for a binary body).** A cross-site form can post only `multipart/form-data`, `text/plain` or `application/x-www-form-urlencoded`, and never a custom header. The server accepts only `application/octet-stream` with `X-OpenWiz-Send: 1`, after `Origin` and `Sec-Fetch-Site`; another origin's `fetch` with those headers is preflighted and gets no CORS answer. A `DELETE` can't come from a form at all.
- **Cloudflare.** A 100 MB request-body limit on the Free and Pro plans, and a 125 s proxy read timeout: Cloudflare's documentation, read 2026-10-23, **not observed here** (rechecked at the live check, F23). 25 MiB is under the first and 110 s under the second, so OpenWiz refuses first, with its own reason. **Cloudflare terminates HTTPS at its edge, so it can process the file bytes in plaintext there.** The connections on each side are encrypted, and the bytes never cross the internet in plaintext. Add no body logging, WAF body inspection or caching rule to the hostname (step 3).
- **Access expiring mid-upload.** Access and `cloudflared` check the session when a request starts, so an upload that started signed in finishes (documented, not observed). The next request gets Access's `401`, and the tray shows **failed (signed out)**; the draft, its text and its ready ids stay, and nothing is sent.
- **A lost connection mid-upload.** The server stops reading, deletes the partial copy and stages nothing. The page shows **failed (connection lost)**, with Retry (only while the browser still has the file) and Remove. It never retries by itself, and a retry never sends anything.
- **What a forged request costs.** A forged upload costs disk space (25 MiB at most each); an unclaimed copy can remain beyond its 24-hour expiry until an attachment operation sweeps it. It can't send or create. A forged removal deletes a copy the owner hasn't sent; one that an operation is sending, or may have sent, is refused (B-6). A forged send or create with attachment ids goes through the core's one gate: every id must be ready and free.

**Metadata (B-10).** Files go unchanged, with whatever they carry: a photo's location, camera and time, a document's author. Nothing strips it. The tray says so in one line whenever an image is attached: "sent unchanged, including any location data".

**What this addendum changes in this guide:** the status, the security model (the routes, the headers, the trust boundary and privacy), this section, the checks before use, and what a browser sees.

## What you need

- A Mac that runs `room-cli` (the version OpenWiz tests against) and is awake when you want to look.
- A domain in your Cloudflare account (`<your-domain>`), on the Free plan.
- Cloudflare Zero Trust (the Free plan covers up to 50 users at the time of writing; check current pricing).
- `cloudflared` on the Mac.

## Steps

Do each account step yourself. Keep every credential on the Mac or in Cloudflare.

1. **Build and run the server on the Mac** from the reviewed head:

   ```sh
   cargo build --release -p openwiz-server
   target/release/openwiz-server --port <port> --allowed-host <openwiz-hostname> --web-root <web-dir>
   ```

   or set `OPENWIZ_SERVER_ALLOWED_HOST=<openwiz-hostname>` instead of the flag. It prints `listening on http://127.0.0.1:<port> (loopback only, with the web page)`. Check: `curl -H 'Host: 127.0.0.1:<port>' http://127.0.0.1:<port>/api/v1/health`, then `curl -sI -H 'Host: 127.0.0.1:<port>' http://127.0.0.1:<port>/` (`200`, `text/html`).

   **`<web-dir>` is the web page:** `apps/web/out`, built from the same reviewed head with `cd apps/web && npm ci --ignore-scripts && npm run build` (in Cloud: no Node.js on the Mac), copied to the Mac, and checked there against the SHA-256 list recorded with the build: `cd <web-dir> && find . -type f | LC_ALL=C sort | xargs shasum -a 256`. The server reads `<web-dir>` once, at start, and serves it from memory: **restart it after copying a new build.** It refuses to start if anything in `<web-dir>` is a symlink, a hard link, a hidden file (such as Finder's `.DS_Store`: delete it) or a file type the page does not use; the message names the rule. Without `--web-root` the API works alone and every other path is `404`.

   For the first checks, run the test-only fixture server against the repository's fake `room-cli`. It shares production dispatch and injects an isolated fake CloudRoom bundle. **GitHub is separate:** five fixture routes still use `gh` from the server's `PATH`, in its working repository, with its inherited login context: `GET /api/v1/fleets` and `GET /api/v1/fleets/{spec}` (`repo view`), `GET /api/v1/plan` (`repo view --json nameWithOwner,url`), `GET /api/v1/decisions` (`repo view --json nameWithOwner`) and `GET /api/v1/cockpit` (`repo view` plus `issue list`), the same sources `contracts/web-api.v1.md` documents. Fake `room-cli` and scratch state alone do not isolate those reads. With the first recipe, stay on **Sessions**: selecting **Fleets** or **Home**, opening a fleet, polling or refreshing those screens can request the fleet endpoints; **Plan** can request `/api/v1/plan`; **Decisions** can request `/api/v1/decisions`; and **Cockpit** can request `/api/v1/cockpit` and the fleet endpoints. For any of these checks, use the separate recording-`gh` launch below.

   Use an absolute, private `<scratch-dir>` outside any repository for the fixture's state and fake executables; the fake `room-cli` finds its scenario beside its own executable path:

   ```sh
   cargo build -p openwiz-tests --example openwiz-server --bin fake-room-cli
   mkdir -m 700 -p "<scratch-dir>" && ln -s "$PWD/target/debug/fake-room-cli" "<scratch-dir>/room-cli"
   printf '%s\n' "$PWD/tests/fixtures/room-cli-0.43.1/normal/scenario.json" > "<scratch-dir>/fake-room-cli.scenario"
   OPENWIZ_FIXTURE_PROGRAM="<scratch-dir>/room-cli" OPENWIZ_STATE_DIR="<scratch-dir>" "<repo>/target/debug/examples/openwiz-server" --port <port> --allowed-host <openwiz-hostname> --web-root "<web-dir>"
   ```

   Fake `room-cli` supplies the CloudRoom reads for inventory (`/api/v1/inventory`), session detail and send preview (`/api/v1/sessions/{id}` and `/api/v1/sessions/{id}/preview`), and Cloud options (`/api/v1/cloud-options`); send/create dispatch, new-thread previews and the CloudRoom observations in new-thread status (`/api/v1/new-threads/{op_id}`) also use that fake. Unsupported scenario calls fail locally. Inventory answers hold only `thr_syn_` ids and "Synthetic" titles. `OPENWIZ_STATE_DIR` keeps fixture send/create records and staged attachments in `<scratch-dir>`, separate from the owner's normal state; status lookups read those records, and attachment routes operate on that local store.

   **For GitHub-backed checks** (Fleets, Home, Plan, Decisions and Cockpit): stop the first fixture server, keep its scratch directory, and use this launch instead. It puts a recording `gh` first in `PATH`; that executable refuses every call locally and never delegates to real `gh`:

   ```sh
   mkdir -m 700 -p "<scratch-dir>/bin"
   cat > "<scratch-dir>/bin/gh" <<'SH'
   #!/bin/sh
   printf '%s\n' "$*" >> "<scratch-dir>/gh.calls"
   exit 1
   SH
   chmod 700 "<scratch-dir>/bin/gh"
   PATH="<scratch-dir>/bin:$PATH" OPENWIZ_FIXTURE_PROGRAM="<scratch-dir>/room-cli" OPENWIZ_STATE_DIR="<scratch-dir>" "<repo>/target/debug/examples/openwiz-server" --port <port> --allowed-host <openwiz-hostname> --web-root "<web-dir>"
   ```

   GitHub-backed requests (Fleets, Home, Plan, Decisions, Cockpit) with this recording `gh` produce gaps or read failures, not successful synthetic GitHub data; calls are recorded in `<scratch-dir>/gh.calls`. For successful checks of those screens, replace it with a `gh` that returns synthetic responses and never delegates to real `gh`. `OPENWIZ_FIXTURE_PROGRAM` affects only the fixture executable's CloudRoom source, never GitHub. The production server uses the verified bundled CloudRoom launcher and real `gh`; this recipe grants no live-read approval.

2. **Create the Zero Trust organisation** (`<team-name>`, team domain `<team-name>.cloudflareaccess.com`) and choose an identity provider: the built-in one-time PIN by email, or an IdP you already use.

3. **Create an Access application** (self-hosted) for `<openwiz-hostname>`, all paths, with one **Allow** policy that includes only `<owner-email>`. No Bypass or Service Auth rules. Note its audience tag (`<aud-tag>`). Choose the session length (default 24 hours). Set the application's cookie **`SameSite` to Lax** (WS-5: a cross-site `POST` then carries no Access cookie; recorded, never relied on). Access answers an expired session with `401` instead of a redirect when a background request carries `X-Requested-With: XMLHttpRequest`; the web page always sends it, so it can tell "signed out" from "disconnected". Add no request logging or WAF body inspection to the hostname: the bodies are your messages.

4. **Create a named tunnel** (`<tunnel-name>`), locally managed, following Cloudflare's [create a locally-managed tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/):

   ```sh
   cloudflared tunnel login                                   # opens a browser; pick <your-domain>; saves a certificate in ~/.cloudflared/
   cloudflared tunnel create <tunnel-name>                    # prints <tunnel-id>; writes ~/.cloudflared/<tunnel-id>.json (the credentials)
   cloudflared tunnel route dns <tunnel-name> <openwiz-hostname>   # a proxied DNS record for the hostname
   ```

   Save this as `~/.cloudflared/config.yml` (or elsewhere, passed with `--config`). It routes only `<openwiz-hostname>` to the loopback server and requires Access at the origin:

   ```yaml
   tunnel: <tunnel-id>
   credentials-file: <home>/.cloudflared/<tunnel-id>.json
   ingress:
     - hostname: <openwiz-hostname>
       service: http://127.0.0.1:<port>
       originRequest:
         access:
           required: true
           teamName: <team-name>
           audTag:
             - <aud-tag>
     - service: http_status:404
   ```

   Do not route any other hostname or service through this tunnel. Check the file with `cloudflared tunnel ingress validate`, then start the tunnel (with the server already running):

   ```sh
   cloudflared tunnel run <tunnel-name>
   ```

   The certificate and the credentials file stay on the Mac. Never copy them into a repository, an issue or a chat. Never run `cloudflared` at debug log level: it could log requests.

5. **Decide how the server and `cloudflared` keep running** (for example `launchd` agents), and whether the Mac may sleep.

## Check it before using it

- **Loopback only:** `lsof -nP -iTCP:<port> -sTCP:LISTEN` shows only `127.0.0.1:<port>`; from another LAN device, `http://<mac-lan-address>:<port>/` is refused.
- **Unauthenticated:** from another network with no session, every route of `https://<openwiz-hostname>` gives the Access login or a denial, never JSON; the same with a forged or expired token.
- **Not the owner:** a second identity outside the policy is denied.
- **The send, from outside** (with the fake `room-cli`, which counts every `thread tell`): from another network with no session, a request valid in every other respect (`Origin`, `Sec-Fetch-Site`, `Content-Type`, `X-OpenWiz-Send`, a synthetic probe text) to `https://<openwiz-hostname>/api/v1/sessions/<id>/messages` must get the Access login or a denial, **never OpenWiz JSON**: OpenWiz JSON there, even a refusal, means a request reached the server without Access. Signed in, a send from another origin, without `X-OpenWiz-Send`, or as a plain form must be refused (`403` or `415`), and on the Mac, `curl -X POST -H 'Host: 127.0.0.1:<port>' …` must be `421`. The fake's tell count must stay 0.
- **The create, from outside** (with the fake `room-cli`, which counts every `thread spawn`): from another network with no session, a create valid in every other respect (`Origin`, `Sec-Fetch-Site`, `Content-Type`, `X-OpenWiz-Send`, a synthetic prompt and offered settings) to `https://<openwiz-hostname>/api/v1/projects/<id>/threads` must get the Access login or a denial, **never OpenWiz JSON**. Signed in, a create from another origin, without `X-OpenWiz-Send`, or as a plain form must be refused (`403` or `415`), and on the Mac, `curl -X POST -H 'Host: 127.0.0.1:<port>' …/threads` must be `421`. The fake's spawn count must stay 0.
- **The upload, from outside** (with the fake `room-cli` and the same `<scratch-dir>` as the fixture's state directory): from another network with no session, a synthetic upload valid in every other respect (`Origin`, `Sec-Fetch-Site`, `X-OpenWiz-Send`, `Content-Type: application/octet-stream`, `X-OpenWiz-Name`) to `https://<openwiz-hostname>/api/v1/attachments` must get the Access login or a denial, **never OpenWiz JSON**. Signed in, an upload from another origin, without `X-OpenWiz-Send`, or as a `multipart/form-data` form must be refused (`403` or `415`), and on the Mac, `curl -X POST -H 'Host: 127.0.0.1:<port>' …/attachments` must be `421`. The scratch store's `attachments/` must stay empty.
- Only then switch the server from the fake `room-cli` to the real one. **The first real send needs the owner's go-ahead** (#10's live check), and so do **the first real create and the first real upload** (#13's).

## What a browser sees

- Signed in, Mac awake: the web page, and JSON from the API.
- Session expired: the Access login (a page load), or a `401` / blocked redirect (a background request).
- Mac asleep, server or tunnel stopped: Cloudflare's error page for the hostname.
- A send whose answer never arrives (the network dropped, the server stopped): the page cannot know whether it was sent. It shows **uncertain**, keeps the text, and checks the op id with the lookup route; sending again with the same op id is never a second send.
- A create whose answer never arrives: the same. The launcher shows **uncertain**, keeps the prompt, settings and op id (in this tab's storage, across a reload), and reads the record with **Refresh status**; a repeat of the same op id is never a second thread.
- An upload whose answer never arrives (the network dropped, the session expired): the tray shows **failed (connection lost)** or **failed (signed out)**, keeps the draft, and offers Retry while it still has the file. Nothing is sent, and nothing retries by itself.
