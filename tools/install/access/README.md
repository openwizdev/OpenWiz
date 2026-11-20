# Phone-access verification

`access.py` checks an **existing** phone-access route to the owner's machine (a named Cloudflare Tunnel behind owner-only Access, or private Tailscale Serve) and records whether it is ready. It changes nothing at the provider, never calls CloudRoom and never starts a tunnel. Before running it, the installing agent shows the owner the provider, account and DNS effects, gets a separate yes, and configures the route through the provider's own interface.

Installed at `runtime/access/access.py`, beside `runtime/setup/store.py`; Python 3 only, plus `/usr/bin/openssl` for Cloudflare. Keep the plan and credential files as absolute paths to owner-only 0600 regular files outside every repository; never paste credential values anywhere.

```sh
A="python3 -I -B <runtime>/access/access.py"
$A configure --state-dir STATE --plan PLAN                          # preview, no provider reads
$A configure --state-dir STATE --plan PLAN --secrets CREDS --yes --operation ID   # check and record
$A status --state-dir STATE --operation ID                          # after a lost reply or restart
$A reconcile --state-dir STATE --plan ORIGINAL_PLAN --secrets CREDS --yes --operation ID --revision REV
python3 -I tools/install/access/test_access.py                     # offline proofs on fixtures/
```

Keep the preview's `operation_id` and `selection_revision`. Phase `applied` means the route check was recorded, not that the engine is ready; evidence expires after an hour or at the checked session's expiry. After a restart, run `status` first: it calls no provider. If the project selection changed while a check ran, `reconcile` the original plan first, then preview and confirm again.

## Plans

`openwiz.access-plan.v1`, every field required: `provider` (`cloudflare` or `tailscale`), an HTTPS DNS `host`, the loopback `port` and the `owner`'s email.

- **Cloudflare** adds `account`, `tunnel`, `application` and `team`. Credentials: `api_token` (read access to tunnels, Access applications and policies, zones and DNS) and three Access cookies: `owner`, `expired` and `foreign` (a different identity). Ready means a healthy remotely managed tunnel routing only that host to `http://127.0.0.1:<port>`, one self-hosted Access application with one owner-only Allow policy and nothing shadowing it, a proxied CNAME to the tunnel, every connector on the stored configuration, anonymous, expired and foreign requests refused before OpenWiz, and the owner's cookie reading this check's fresh code.
- **Tailscale** adds `tailnet`, `device` and a `foreign` identity. Credentials: `api_token` with device read and policy read and validation. Ready means an online, authorised owner device on that `.ts.net` host, private Serve forwarding only `/` to loopback on 443 with Funnel off, one owner-only ACL that the current-policy test accepts for the owner and denies for `foreign`, and the owner path reading this check's fresh code.

Anything else (a locally managed tunnel, another policy shape, a missing credential or field, an unreadable provider) leaves readiness unknown: never weaken a policy to get a verdict. Fixtures prove the verifier on synthetic providers, never a real account, phone or network.
