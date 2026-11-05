# Guided phone-access verification

The setup page's Phone access disclosure explains the named Cloudflare Tunnel
plus owner-only Access route and offers private Tailscale Serve. Prerequisites,
effects, costs needing confirmation and recovery remain visible before any
account or network change. Neither this tool nor selecting the page's guidance
creates, activates, purchases or publishes anything.

The installing agent first shows the proposed provider/account/DNS effects and
gets the owner's separate authorization. It configures the selected route using
that provider's supported interface. Then this packaged tool verifies the
**existing exact resource**, without changing it. It never invokes CloudRoom,
sends work, creates a thread, rewrites an ACL or starts a tunnel. The Tailscale
current-policy validation POST tests policy; it is not the policy update API.

Installed entry: `runtime/access/access.py`, with `runtime/setup/store.py` beside
it in the same verified bundle. No source checkout, Cargo, Node or extra Python
package is required. Cloudflare verification uses setup's existing
`/usr/bin/openssl` prerequisite for RS256 verification; it never searches PATH.
An unavailable verifier leaves readiness unknown. The local Tailscale CLI is a
prerequisite of that route.
Keep the plan and credential JSON files in an owner-only directory outside all
repositories, as absolute paths, regular 0600 files with no symlink or hard
link. Provision credentials through protected setup; never paste their values
into a prompt, command, URL, log, repository or issue.

Preview (provider reads: zero):

```sh
python3 -I -B <runtime>/access/access.py configure --state-dir <private-state> --plan <private-plan.json>
```

The result holds `operation.operation_id`, fingerprint, effects and
`selection_revision`. Keep all of them. Confirm that exact preview explicitly:

```sh
python3 -I -B <runtime>/access/access.py configure --state-dir <private-state> --plan <private-plan.json> --secrets <private-credentials.json> --yes --operation <operation-id>
```

Each confirmation rechecks current authorization, the same resource and refusal
before recording readiness. Read-only provider errors become fixed public codes;
no provider body, key or cookie is persisted or printed. Output phase `applied`
means the route check was recorded, not that the engine or factory is ready.
A later failed check invalidates the positive observation while retaining the
setup effect. Evidence expires under the setup report's existing one-hour rule,
or at the checked owner-session/device expiry, whichever is earlier.

After a lost reply or host restart, read the record first:

```sh
python3 -I -B <runtime>/access/access.py status --state-dir <private-state> --operation <operation-id>
```

Status makes no provider call and creates no state. Repeating confirmation reads
the same provider resource; there is no resource-create call to repeat. Keep
uncertainty until that exact resource can be checked. An unanswered or denied
check never erases an uncertain operation. If project selection changed while a
check was in flight, reconcile the original plan and its saved revision first:

```sh
python3 -I -B <runtime>/access/access.py reconcile --state-dir <private-state> --plan <original-private-plan.json> --secrets <private-credentials.json> --yes --operation <operation-id> --revision <saved-selection-revision>
```

That observation remains bound to the original selection, so it cannot verify
the new one. Then preview and confirm for the current selection. A newer-started
check or a changed selection prevents the old check from publishing readiness.
Never resend pending work on reconnect: preserve its draft and op id, and read
its own send/create status. This access tool never touches those records.

## Supported plans and checks

Plan schema is exactly `openwiz.access-plan.v1`. All fields are mandatory, no
unknown or duplicate fields. Common fields: `provider` (`cloudflare` or
`tailscale`), one lowercase HTTPS DNS `host`, integer loopback `port`, and the
owner's email `owner`. No IP, loopback name, path or quick-tunnel hostname.

Cloudflare adds `account` (32 lowercase hex), `tunnel` and `application` (UUIDs),
and `team` (team slug). Credentials have exactly `api_token`, `owner`, `expired`
and `foreign`. The latter three are private Access JWT cookies: current owner,
expired owner, and a current different identity. They are never API arguments.
The API token needs read access to Tunnel configurations/connections, Access
applications/policies, the account's zones and their DNS records.
Missing credentials leave readiness unknown; do not weaken policy to obtain a
foreign session. A missing account/domain remains a prerequisite, not permission
to purchase either.

The verifier supports a healthy **remotely managed named tunnel** with exactly
one HTTPS hostname routed to `http://127.0.0.1:<port>` and a final 404 rule.
Origin-side Access is required for the exact team and application's audience.
The account's full application list must show no covering/shadow application;
pagination or an unreadable list stays unknown. The application is self-hosted
for all paths, with exactly one Allow policy including only the owner and no
Bypass/Service Auth/Everyone rule. It checks configuration before and after
probes. The complete zone inventory must identify one active full zone in the
selected account, whose exact proxied CNAME maps the host to the selected
`<tunnel-id>.cfargotunnel.com`. Every returned connector must have connections
and report the exact stored configuration version. Missing fields, stale
connectors, alternate tunnels, unsupported routing and changes during probes
leave readiness unknown. These are authenticated API observations, not a
native network-enforcement claim. A locally managed tunnel can still follow the manual guide, but this
automated verifier cannot establish its running configuration and refuses to
mark it ready. A tunnel process alone is never positive evidence.

Anonymous, expired-owner and foreign sessions must get 401/403 before OpenWiz,
including on the two write paths. Probe requests are **GET only**, so even a
broken edge cannot dispatch a send or create. Redirects are not accepted as
verified refusal, and an OpenWiz JSON error means the request reached the origin.
A current owner cookie must read the real setup schema and this operation's
fresh verification code from this private state. The code is never sent in a
probe, so another host or stale state copy cannot simply echo it. Before any
probe counts, all three cookies must have valid RS256 signatures from the
selected team's HTTPS signing-key endpoint, that team's issuer, the selected
application's exact audience, app-token type and the intended email identity.
Only the expired-owner context may be expired; future issuance/not-before,
unknown keys, invalid signatures and wrong-team/application tokens stay unknown.
The verifier supports RSA keys of 2048, 3072 or 4096 bits with exponent 65537.
No token-supplied key or URL is trusted. Access and cloudflared still enforce
authentication on the serving route.

Tailscale adds `tailnet`, `device` (stable node id) and a different `foreign`
identity for the current-policy deny test. Credentials have only `api_token`,
with device-read and current-policy-read/validation permission. It requires a
Running/Online, authorized, unexpired owner device whose name matches the
HTTPS `.ts.net` hostname; background private Serve forwards only `/` to
loopback on HTTPS 443, with Funnel off and no extra foreground/service route.
The supported policy is one explicit owner-only IPv4:443 ACL, optionally tests;
other policy shapes remain unverified rather than being interpreted loosely.
The read-only validation API tests **the current policy using an array**, with
owner accept and foreign deny. A 200 body can contain failures and is refused.
Device approval/expiry gates establish the authenticated network prerequisite;
Tailscale does not use HTTP cookies to authenticate tailnet members. The owner
path must also return this operation's fresh verification code from setup, and configuration is checked again afterward.

These are provider configuration, current-policy and request observations.
Fixtures prove the verifier, edge refusal and operation recovery on synthetic
providers; they do not prove real accounts, native clients, TLS configuration,
phones or radios. The final version live check verifies actual enforcement on
the selected host. An unavailable/malformed provider, unsupported configuration
or expired authorization never establishes phone readiness.

## Proof registration and references

`apps/web/test/browser/install-access.test.mjs` runs the focused Python proofs,
the actual setup page and installed tool against recording provider/edge
fixtures. The existing browser runner discovers this file; the CI classifier
retains `tools/install/` and `apps/web/`. Required fixtures are under
`apps/web/test/fixtures/install-access/`, never optional private evidence. The
collector packages only `access.py`, never tests or recording providers.

Sources checked 2026-11-07: [Cloudflare JWT validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/),
[DNS routing](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/dns/),
[connector versions](https://developers.cloudflare.com/api/resources/zero_trust/subresources/tunnels/subresources/cloudflared/subresources/connections/methods/get/),
[Cloudflare origin parameters](https://developers.cloudflare.com/tunnel/reference/origin-parameters/),
[Cloudflare Tunnel API](https://developers.cloudflare.com/api/resources/zero_trust/subresources/tunnels/subresources/cloudflared/),
[Tailscale API](https://tailscale.com/docs/reference/tailscale-api),
[Tailscale current-policy validation client](https://github.com/tailscale/tailscale/blob/main/client/tailscale/acl.go),
[CLI peer status](https://github.com/tailscale/tailscale/blob/main/ipn/ipnstate/ipnstate.go)
and [Serve configuration](https://github.com/tailscale/tailscale/blob/main/ipn/serve.go).
Provider API/CLI shapes in fixtures are explicitly synthetic assumptions based
on these references, not captured live responses.
