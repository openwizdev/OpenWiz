# IF7 synthetic providers

`provider.py` records management reads and current-policy validation. It refuses
all unknown requests and never delegates. `driver.py` injects these providers
into the collected production access tool; its optional wire goes only to the
test-owned loopback edge. Neither file is included in release assets.

## synthetic_assumptions

- Every owner, foreign identity, host, account, resource, credential, JWT claim,
  audience, timestamp and policy is synthetic. No account response was captured.
- Cloudflare Tunnel/configuration, application/list/policy envelopes follow the
  documented API shapes; list pagination is explicit. Locally managed tunnels,
  extra/shadow applications, broad policies and wrong origin validation are
  negative cases. JWTs are signed with the deliberately public, compromised
  RSA example in [RFC 7515 A.2](https://www.rfc-editor.org/rfc/rfc7515.html#appendix-A.2),
  solely for synthetic claims. Production OpenSSL verifies their signatures
  against the fixture team's recording JWKS, including rejection regressions.
  This example key must never authenticate any real service. It is not packaged.
- Zone/DNS inventories and connector configuration versions are synthetic
  documented shapes. Alternate-tunnel CNAMEs, stale/additional connectors,
  missing evidence and changes during probes cannot establish readiness.
- The loopback edge's identity/expiry checks model authentication before forwarding
  to the actual fixture server. For Tailscale they stand for network member
  contexts; real Tailscale does not authenticate HTTP requests with a cookie.
- Tailscale node/device, Serve and ACL shapes follow its documented API and Go
  types. Omitted false Expired/AllowFunnel fields are tested. The policy validator
  evaluates an array against its active fixture ACL; it never updates that ACL.
- No fixture can create a route, delegate to a live account or send real work.
  The browser journey's one send goes through the repository's recording fake
  room-cli, with a synthetic prompt and scratch operation store. Its lost reply,
  network cut and host restart must leave exactly one tell invocation.
- Provider configuration/policy tests do not establish native TLS, device,
  tailnet enforcement, account compatibility or radio behavior. These remain
  the version's separately authorized live check.
