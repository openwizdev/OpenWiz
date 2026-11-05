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

## Candidate review (#2206)

### Verdict

**PR3 stays Unverified.** No High finding and no known work-loss path was found in the surfaces below. Still, this is not a launch pass:

- no built candidate exists to bind;
- both Medium findings (C-G1, #2868 in 0.0.16; B-G1, #2856) are routed but not yet fixed and re-reviewed;
- no live observation was made;
- host-side key and token storage on a selected host was not observed.

Each gap is listed under [Gaps](#gaps-1).

### Candidate and evidence classes

- **Source:** ClosedWiz `main` at commit `0a7cb93ceb295618e617e166fbed785cf5502dd0`, tree `f44fce80a6adf7568a0807354b5b1e1e09bfeb90`. That is the merge of #2838, which descends from every native blocker's verified merge: #2201, #2204, #2205, #2220, #2292 and #2293.
- **Build identity: unknown.** No `openwiz.release-candidate.v1` record exists, and there is no `openwizdev/openwiz` source, built manifest or `manifest_sha256` to bind. Under first-hour.v1 this is `candidate_unknown`. The record has to be bound again, by #2207 or a later re-review, once a checked candidate exists. Every claim below holds for the source revision above only.
- **Code review:** the builder read the source at that revision and diffed it against P10's revision `aa170fa86d26a6cf4145e4efac37998ca292fe35`. Five read-only helpers widened the search, one per surface. Every item cited below was rechecked by the builder before use.
- **Fixture test:** `tools/install/tests/public-release-security/test_candidate.py`, 8 cases with 30 planted cases, all passing at this revision. Each case was shown to catch the break it exists for: ten planted breaks, each failing exactly its expected cases, while the unbroken copy passes (private evidence).
- **Scratch fixture runs:** one-off runs behind C-G2, C-F2 and C-F3. They are kept in private evidence and are not CI cases.
- **Live observation:** none. No account, host, provider, CloudRoom or GitHub call was made.

### Surfaces changed since the baseline

| Surface | Change since P10's revision | Assessment | Evidence |
| --- | --- | --- | --- |
| App manifest and registration (#2545, #2546) | `"public": true`. Every registration is public, including each new user's own App, because the product runtime ships the same manifest. Agent mode writes the key only to the secret, by stdin | Permissions are unchanged: Metadata read; Contents, Issues and Pull requests write; Checks and Actions read; no webhook. Who may install the App widens (C-G1, C-G2) | Code review |
| `openwiz github token` (#2547) | New: it mints from the CloudRoom secret, resolves the installation from the repository, and scopes the token to one repository | The key and JWT reach helpers only by descriptor or stdin. The token goes only to stdout and nothing stores it. Failures are fixed sentences. Any installation whose account owns the repository is accepted (C-G1). An answer with selection `all` is accepted when it lists one repository (C-G3) | Code review; its own Rust tests |
| PC read token `mint-token.py --repository` (#2315) | New downscope to the named repositories, with an exact check of the answer | Refused, revoked, expired, wider, foreign, write-granting and lost answers print no token, store none and send no personal login to the App API. Without `--repository` the old unscoped path remains (B-G1) | Fixture test |
| CloudRoom install, reuse and sign-in (#2201) | New tool, its 13 setup codes, the sign-in screen and two pinned `room-cli` calls | Every program is absolute and the environment is fixed. The installer is checked against the published digest before any effect, and nothing is ever placed over an existing installation. The account and sign-in link are never printed, saved or shown, and only the code reaches setup state. Lost, refused and contradictory login reads never verify. Hardening: C-C1 to C-C4 | Fixture test; code review |
| Feedback and sharing (#2292) | New skill helper and the app's handoff and share | The exact preview binds title, body, destination, login, id and operation. Refusal makes no create call. A lost reply stays uncertain and is never resent. An App installation token is refused as a login. Only the previewed bytes are sent. Planted context and tokens reach no request, output or record. Limits: C-F1 to C-F4 | Fixture test; code review |
| Free-only copy (#2293) | New install, site and app copy | A search of the whole tree at this revision found no payment provider, billing, checkout, entitlement, licence key, price constant or trial code, and no paid offer in copy. "Paid plans come later" and CloudRoom's separate plans are stated (C-O1, C-O2) | Code review |
| Setup store, server and pages (#2201, #2205) | 13 CloudRoom rows in the server's fixed code table, and the first-hour pages | The server logs only method, route template, status and time, never a body. The pages never ask the user to paste a token. Free text still accepts credential-shaped values (B-S1, C-S1) | Code review |
| Phone access (#1107) | `access.py` unchanged | Baseline findings unchanged | Code review |

### The baseline bound to this candidate

| Baseline finding | At this candidate |
| --- | --- |
| B-G1 (Medium) | Routed: #2856. **Partly fixed.** The shared read helper always passes `--repository`, and the tool then checks the exact answer. Without `--repository`, `mint-token.py` still mints an unscoped read token, and `docs/github-app.md`'s manual command omits it. Still Medium |
| B-G2 (Low) | Routed: #2870. Still present. The new token command also drops refused tokens without revoking them |
| B-G3 (Low) | Routed: #2871. Still present in `tools/github-app/app.py` and the setup check's fallback. The new Rust command uses `/usr/bin/openssl` and `/usr/bin/curl` with a cleared environment |
| B-G4 (Low) | Routed: #2872. Changed. Agent mode writes no key file. Host mode's `save_file` removes a partial key on a Python error, but a crash mid-write still leaves a truncated key |
| B-G5 (Low) | Routed: #2873. Still present |
| B-S1 (Low) | Still present, and widened by C-S1. Routed with C-S1: #2865 |
| B-S2, B-S3 (Low) | Still present. Routed: B-S2 #2874, B-S3 #2875 |
| B-A1 to B-A4 | Unchanged: `access.py` is unchanged. B-A1's expiry case is already reported in #1833. Routed: B-A1 #2876, B-A2 #2877, B-A3 #2878. B-A4 is Info |

### New fixture cases

| Case | Boundary | Planted cases |
| --- | --- | --- |
| `CloudRoomBoundary.test_lost_refused_and_contradictory_login_reads_never_verify_or_leak` | #2201 `cloudroom.py status`, the tool's recording host | 9: lost reply (timeout), failed read, truncated answer, duplicate key, signed out with planted error text, still signing in, account plus signed out, self-hosted, account with an extra field |
| `CloudRoomBoundary.test_a_verified_login_is_reported_by_code_only` | the same | 1: planted account id and email |
| `CloudRoomBoundary.test_sign_in_opens_the_planted_link_once_and_never_repeats_it` | `cloudroom.py sign-in` | 1: planted sign-in nonce |
| `CloudRoomBoundary.test_lost_or_refused_sign_in_replies_open_nothing_and_leak_nothing` | the same | 6: lost reply, truncated answer, another host, plain HTTP, user part, extra field |
| `FeedbackBoundary.test_an_app_installation_token_is_never_a_feedback_login` | #2292 `feedback.py`, a recording `gh` that answers by credential | 1: an App installation token as the login, with planted context |
| `FeedbackBoundary.test_a_lost_create_reply_stays_uncertain_and_sends_only_the_previewed_bytes` | the same | 1: dropped create reply, then a repeated yes and a new preview, with planted login and context |
| `MintBoundary.test_the_exact_answer_prints_the_token_and_its_expiry_only` | #2315 `mint-token.py --repository`, loopback App API | 1: positive control |
| `MintBoundary.test_refused_revoked_expired_wider_and_lost_answers_print_no_token` | the same | 10: revoked, key rejected, not granted, lost reply, expired, over an hour, all repositories, a foreign repository too, another repository, write granted |

### Findings

Severity follows the baseline's scale. **Owner** is the existing ticket that built the code. **Corrective ticket** is the exact ticket that will fix it. The orchestrator filed them as standalone follow-ups, and Jake decided C-G1 (J48, 2026-11-14). A finding is **routed** once it has a decision and an exact corrective ticket. Its fix still needs an independent re-review at an exact candidate before it counts as fixed.
Private record: https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6869926983

| ID | Severity | Owner | Finding | Evidence | Disposition |
| --- | --- | --- | --- | --- | --- |
| B-G1 | Medium | #404 | As bound above: the unscoped PC read token remains without `--repository` | Code review | Routed: #2856 |
| C-G1 | Medium | #2546 (manifest); #2547 (token command); #1105 (product registration) | The App is public for every registration, including each new user's own App. One user needs no public App. The token command, `mint-token.py` and the setup check accept any installation of the App whose account owns the named repository. The identity contract's "our factory uses only the installations it names" is not enforced in code. Its text still says the manifest is private | Code review (`crates/adapters/github/src/app.rs` `installation_for`; `tools/github-app/manifest.json`) | Routed: decided under J48 (2026-11-14): in 0.0.16 each user's own App is private by default, installable only on its owner's account, and the factory's App stays public. Corrective ticket #2868 (0.0.16) |
| C-G2 | Low | #1105 (`tools/install/setup/setup.py` `check_app`) | The setup check reads only the first page of `GET /app/installations`. With a public App, a full first page of other accounts' installations makes a valid installation read as revoked and clears its recorded id. This fails closed and causes a false refusal | Scratch fixture run (30 other-account installations: `app_revoked`, id cleared) | Routed: #2857 |
| C-G3 | Low | #2547 | The token answer is accepted with `repository_selection: "all"`. The exact one-repository list check still applies | Code review | Routed: #2879 |
| C-C1 | Low | #2201 | On Linux, a launchable `~/Downloads/Cloudroom*.AppImage` counts as installed. Sign-in then launches it with no checksum. The contract documents this | Code review | Routed: #2858 |
| C-C2 | Low | #2201 | macOS trust is `codesign --verify --deep --strict` with no designated requirement for CloudRoom's signing team. Any validly signed app passes, and the only anchor is the release's own digest | Code review | Routed: #2859 |
| C-C3 | Low | #2201 | `http.client.HTTPException` (for example an incomplete read) is not an `OSError`. It escapes the fixed refusal with a traceback. A confirm's record stays `installing` and then reads as uncertain, so it fails closed | Code review | Routed: #2860 |
| C-C4 | Info | #2201 | The one-time sign-in link is an argument to `/usr/bin/xdg-open` or `/usr/bin/open`, so it is briefly visible to other local users in the process table | Code review | Accepted limitation: never printed or saved |
| C-F1 | Low | #2292 | Consent rests on the agent. `preview` returns the `preview_id` that `send` accepts, so one agent run can preview and send with no user turn between. The skill tells the agent to wait for the user's next turn. The helper cannot observe one | Code review | Routed: #2861 |
| C-F2 | Low | #2292 (`feedback.py`, `apps/web/src/feedback.ts`) | The share-text check misses a bare host and path, such as `github.com/<owner>/<repo>` with no scheme. User-chosen share text can carry a repository identifier, which the contract forbids | Scratch fixture run | Routed: #2862 |
| C-F3 | Low | #2292 | Titles and bodies accept bidirectional overrides and zero-width characters, so the preview can read differently from what GitHub stores | Scratch fixture run | Routed: #2863 |
| C-F4 | Low | #2292 | The helper passes its whole environment to `gh` found on `PATH`. A `GH_TOKEN` there silently overrides the keyring login, and the contract's refusal for more than one candidate account is not coded. Mitigations: the preview shows the login, and an App installation token is refused | Code review; fixture test | Routed: #2864 |
| C-S1 | Low | #1105 (`tools/install/setup/store.py`, `crates/store/src/setup.rs`) | Besides B-S1's free text, the harness, model and effort settings accept a credential-shaped value, and the setup effects render it. The values are typed by the owner | Code review | Routed: #2865 |
| C-S2 | Info | #1107 | A pending access check's one-time verification code is in its operation reason. That reason is shown by `GET /api/v1/setup` and the page while the check is uncertain. The access guide intends this | Code review | Accepted limitation |
| C-O1 | Info | #2293 | The site presents the install line as available. The same page lists install as "Building next", and install is not yet verified live. This is PR6 copy, not a security finding | Code review | Routed to #2207's live check |
| C-O2 | Low | #2293 | The free-only evidence is bound to an older revision, not to this candidate. This record's search at the candidate found no payment code | Code review | Fixed for this source revision by this record; re-run at a built candidate |

**Every finding is routed.** C-G3 goes to #2879. The carried baseline Lows are routed in the table above (#2870 to #2878). B-A4, C-C4 and C-S2 are Info or accepted limitations, and C-O1 is routed to #2207.

**Work loss (PR4).** No known work-loss path was found in these surfaces. CloudRoom never overwrites or removes an existing installation. Feedback keeps every draft and never erases uncertainty. B-G4's truncated key loses App setup, not user work. #2204's recovery behaviour was reviewed only where it crosses these security boundaries.

### Gaps

- The build identity is unknown (above). Every claim holds only for source revision `0a7cb93ceb295618e617e166fbed785cf5502dd0`.
- Key and token storage and access on a selected host was reviewed in code only. No selected host was observed. That includes CloudRoom's delivery of `OPENWIZ_GITHUB_APP_KEY` and which agent processes can read it.
- GitHub's and CloudRoom's real behaviour is assumed from their documentation and the recording fakes, never observed. That includes installation-token refusal of `GET /user`, public-App installation listing and pagination, and the sign-in link's lifetime.
- The server's `GET /api/v1/setup` and the web pages were read, not run, for this record. Their own suites run in CI.
- `test_candidate.py` is registered in CI as `release:security-candidate`: one row each in `.github/actions/docs-only/run.py` and `plan.py`, approved by Jake under J49 (2026-11-14).
- Not reviewed: the feedback receiver (#2557), and the live first hour (#2207).
