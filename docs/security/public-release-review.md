# Public release security review

The App, credential and first-hour privacy review for the public release (spec #2194). It has two parts. #2220 owns the **Baseline** section below. #2206 owns the rest of this file: the final review bound to the checked candidate, every changed or new surface, and every disposition.

## Baseline: the existing App and access (#2220)

### Scope and source revision

This is an independent baseline assessment of the existing GitHub App and authenticated access at **source revision `aa170fa86d26a6cf4145e4efac37998ca292fe35`** of `main`. Both implementations are ancestors of that revision: #1105's merge `6988771d0816de537e74f7099e5bf68f1daa66ca` and #1107's merge `0f02ec0ead25a26892f8d95b06f4c74ebc2a5c22`.

What it covers:

- the App manifest and its tools (`tools/github-app/`);
- the setup check and its state (`tools/install/setup/`, `crates/store/src/setup.rs`, `crates/server/src/setup.rs`);
- the service App's token request (`crates/adapters/github/src/app.rs`), read only to compare token scope;
- the phone-access check (`tools/install/access/`).

This prepares #2206; it is not a launch verdict:

- It records findings and decides no disposition.
- A clean baseline is not a clean PR3 result.
- It makes no candidate, host or launch claim.
- It reviews no first-hour, setup-agreement, payment or feedback surface.
- It proposes no fix. #2206 routes each finding to its owner.

### Evidence classes

- **Code review:** the builder read the source at the revision above. Read-only helpers widened the search, and every item they reported was rechecked before it was used.
- **Fixture test:** `tools/install/tests/public-release-security/baseline/test_baseline.py`. It plants synthetic credentials, runs the existing tools through their public entry points against recording providers, and passes at this revision. Each case was shown to catch the break it exists for: eight planted breaks, each failing exactly the expected case, while the unbroken copy passes.
- **Scratch fixture runs:** two one-off runs of the existing tools with synthetic inputs (B-S1, B-A2), kept in private evidence. They are not CI cases.
- **Live observation:** none. No live account, host, provider or GitHub call was made. Nothing here proves live behaviour.

### What the baseline found

| Area | Assessment at this revision | Evidence |
| --- | --- | --- |
| Least App permissions | The manifest asks for Metadata read; Contents, Issues and Pull requests write; Checks and Actions read; and no webhook or events. That matches the service's writes: issue and pull request comments, labels, issue close and the merge. Admin, Workflows and Secrets are absent. Setup and the service refuse any other granted profile. | Code review |
| Chosen-repository isolation | The setup check refuses an all-repositories installation and asks for a proof token limited to the one chosen repository. The service's token request is also limited to one repository. The PC read-token tool is not (B-G1). | Code review; fixture test |
| App versus the agents' identities | The App check signs with the App's key alone; it never uses `gh` or `GH_TOKEN`. The agents' login check uses only `gh`, and refuses a bot. In every refused, revoked and expired App case, no App request carried the planted personal token, and `gh` received no App credential. | Code review; fixture test |
| Key and token storage | The App key and ids live in an owner-only state directory outside every repository. They are opened without following symlinks, and owner, mode, link count and size are checked. The key reaches OpenSSL only through an inherited file descriptor. Installation tokens are held in memory only. Hardening gaps: B-G3, B-G4, B-S1 and B-S3. | Code review; fixture test |
| Expiry and revocation | A removed installation is reported revoked and its recorded id is cleared. A rejected key, a suspended installation, a wrong repository, and an expired or over-long token are each refused. Phone access refuses a revoked provider token, an expired owner session, device or node, and a revoked device approval. Positive access evidence cannot outlive the credential it checked. Minted tokens are never revoked early (B-G2). | Code review; fixture test |
| Access and output refusals | Every planted refusal verified nothing, made no write, left its operation uncertain, sent each credential only to its own provider, and left no credential in the result, error text or state. The refusal cases were: anonymous, expired or foreign sessions reaching OpenWiz, Funnel exposure, and a policy that admits everyone. Crash paths also fail closed without leaking, but they bypass the fixed codes (B-A1). | Code review; fixture test |

### Fixture cases

| Case | Boundary | Planted cases |
| --- | --- | --- |
| `AccessBoundaries.test_refused_revoked_and_expired_routes_verify_nothing_and_confine_credentials` | #1107 `access.execute`, recording provider | 11: Cloudflare revoked token, anonymous, expired and foreign sessions reaching OpenWiz, expired owner session; Tailscale revoked token, expired device key, revoked device approval, expired node, Funnel on, policy admitting everyone |
| `AccessBoundaries.test_provider_answers_the_tool_cannot_parse_fail_closed_without_leaking` | #1107 `access.execute`, recording provider | 3: unrepresentable device expiry, deeply nested policy answer, truncated policy answer |
| `AppBoundaries.test_refused_revoked_and_expired_app_connections_keep_identities_apart` | #1105 `setup.py check`, loopback App API and fake `gh` | 7: installation removed, key rejected, suspended, all repositories, chosen repository not granted, token already expired, token outliving an hour |

### Findings for #2206

Severity:

- **High:** an unauthorized effect or credential leak reachable in the existing flow.
- **Medium:** a guard weaker than its documented promise, with a plausible path to wider access or false readiness.
- **Low:** hardening, owner-typed input, or a fail-closed misreport.
- **Info:** worth knowing; no defect claimed.

No High finding was found. Each owner below is the existing ticket that built the code.

| ID | Severity | Existing owner | Finding | Evidence |
| --- | --- | --- | --- | --- |
| B-G1 | Medium | #404 (`tools/github-app/mint-token.py`) | The PC read-token tool asks for read permissions but names no repository. It never checks the installation's repository selection either. Its token therefore reads every repository the installation covers, or all of the owner's repositories when the installation covers all. Its guide says it "downscopes", which is true of permissions only. The setup check and the service limit their tokens to the chosen repository. | Code review |
| B-G2 | Low | #404 (`mint-token.py`); #1105 (setup check) | A token is minted before it is checked. A refused token, and the setup check's proof token, are dropped but never revoked, so each stays valid at GitHub for up to an hour. | Code review |
| B-G3 | Low | #404 and #1105 (`tools/github-app/app.py`); #1105 (`tools/install/setup/setup.py`) | The App tools run `openssl` from `PATH` and pass it the private key's descriptor. The setup check falls back to `PATH` when `/usr/bin/openssl` is absent. The phone-access check always uses `/usr/bin/openssl` with an empty environment. | Code review |
| B-G4 | Low | #1105 (`tools/github-app/setup.py`, `app.py`) | The App key is written straight to its final name, not to a temporary file that is then renamed. A crash mid-write leaves a truncated key that blocks every later run, and GitHub's one-time conversion cannot be repeated. | Code review |
| B-G5 | Low | #404 and #1105 (`app.py`, `setup.py`) | The production tools accept `--api-base http://127.0.0.1:<port>`, described as for synthetic tests only. With it, a short-lived App JWT is sent in plain HTTP to whatever listens on that local port. The flag is typed by the owner. | Code review |
| B-S1 | Low | #1105 (`tools/install/setup/store.py`, `crates/store/src/setup.rs`) | The setup state promises that tokens and keys are refused by shape. Free-text fields accept any printable text, though: the operator name, effects and reasons. The store's check accepts a credential-shaped operator name (synthetic, 40 characters). It is repeated in the effects that `GET /api/v1/setup` returns. The value is typed by the owner. | Code review; scratch fixture run (accepted by the store) |
| B-S2 | Low | #1105 (`setup.py` `check_identity`, `check_project`) | A `gh` timeout or start failure is reported as signed out. A generic `gh` failure (exit 1) is reported as a refusal or as missing settings. The setup contract keeps unknown separate from refused and missing. Both fail closed. | Code review |
| B-S3 | Low | #1105 (`crates/store/src/setup.rs`) | The server compares the state file's owner with its directory's owner, not with the server's own user, and follows a symlinked state root. The Python store refuses both. Owner-only modes are still required. | Code review |
| B-A1 | Low | #1107 (`tools/install/access/access.py`) | Some provider answers escape the fixed codes: an unrepresentable expiry, deeply nested JSON and a truncated reply. The tool stops with a traceback, leaving `access_checking` and an uncertain operation until the next check. The access guide promises fixed public codes for provider errors. Fail-closed and no credential leak were proven by fixture. The expiry case was already reported in #1833. | Code review; fixture test |
| B-A2 | Low | #1107 (`access.py`) | The access observation is not bound to an operation or route. After a second route is checked at the same selection, `status --operation <first>` reports the second route's result. | Code review; scratch fixture run |
| B-A3 | Low | #1107 (`access.py`) | The Tailscale check runs `tailscale` from `PATH` with the inherited environment. A planted program could forge the local status and Serve answers. The provider API checks still apply. | Code review |
| B-A4 | Info | #1107 (`access.py`) | A revoked or denied provider token is labelled `access_expired`. The setup page's text for that code ("expired or unavailable") still tells the owner to sign in again. | Code review; fixture test |

### Gaps

- Every claim here holds only for revision `aa170fa86d26a6cf4145e4efac37998ca292fe35`. #2206 re-assesses every surface the candidate changes.
- GitHub's and the access providers' real behaviour is assumed from their documentation and the recording fixtures, never observed. That includes token revocation, Tailscale's current-policy test writing nothing, and session revocation delay.
- Not assessed here: the App's registration callbacks beyond their existing tests (`tools/github-app/test.py`); the server's log output; and the web page's rendering of setup text, which is #2206's output review.
- Who can reach `GET /api/v1/setup` depends on the owner's tunnel and Access set-up. This baseline assumes the existing documented model and does not verify it.
