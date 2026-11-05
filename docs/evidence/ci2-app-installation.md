# C9 receipt: the OpenWiz GitHub App installation (GI6)

C9 (#2316, spec #2291) is satisfied by GI6 (#2548, spec #2537), as Jake approved in J20: the factory's one OpenWiz App is the scoped, installation-authenticated identity C9 asked for. Read back on 2026-11-14 between 01:44Z and 02:10Z, by GitHub's API, with the App's own key. Sanitized: no key, token, code or private reply appears here.

## Authorization

- Jake approved folding C9 into this App (J20), the App's public setting (item 19), the one-time key paste (J27) and the GI6 install steps, and performed every account action himself: creating the App, generating its key, pasting it into Cloudroom's secret prompt, making it public and installing it. Private records: [J20](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6844905705), [item 19](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6846504649), [J27](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6848292112).
- Agents only prepared the steps and read the results back.

## The App

| What | Read back |
| --- | --- |
| App | `openwiz` (id 5752387), owner `openwizdev`, created 2026-11-14 00:16:35Z |
| Visibility | public: GitHub's API serves it to a reader who is not signed in |
| Permissions | metadata read; contents, issues, pull requests write; checks, actions read (exactly `contracts/github-identity.v1.md`) |
| Events and webhook | none (no events; the webhook was registered inactive) |

## Installations (selected repositories only)

| Installation | Account | Repositories |
| --- | --- | --- |
| 181783591 | `jparker2006` | `jparker2006/ClosedWiz` |
| 181779211 | `openwizdev` | `openwizdev/openwiz`, `openwizdev/WizPlugins`, `openwizdev/WizSkills` |

Both installations carry exactly the contract's permissions. `openwizdev/WizSkills` was selected at the orchestrator's request for WZ9; the contract does not list it yet, and #2850 adds it. No other repository is in scope.

## Authentication, expiry and revocation

- Tokens are installation tokens minted from the App key (never an App user token). A token asked for with only `metadata` and `contents` read, for `jparker2006/ClosedWiz` alone, was granted exactly that, read the repository (200), was refused a write (403), and lasted 3600 seconds by its `expires_at`.
- Revoking it (`DELETE /installation/token`, 204) took effect at once: the same token was then refused (401).
- The key can be rotated or revoked on the App's settings page (generate a new private key, delete the old one); every token minted from a deleted key stops within its hour.

## Key handling

- The key reached the agent only through Cloudroom's own secret prompt, as the PEM file Jake downloaded. It was checked with `openssl rsa -check`, stored as the contract's one line of base64 in an owner-only file (mode 0600, folder 0700) in the fleet's sandbox, and the delivered file was deleted. GitHub accepted a JWT signed with it as App 5752387. Public-key SHA-256: `a75acad6cc187a9d62e49e19e413147acba57cc53fe9a5d3e8ad908c047c4a02`.
- Gap: Cloudroom has no agent-side secret store yet (GI4's assumption A1), so the key lives in that one sandbox; other sandboxes need it delivered the same way.

## Cost

GitHub Apps and their installation tokens carry no charge. C9's contribution to the $60 whole bill is $0; nothing was purchased.

## Gaps and deviations

- GI4's agent setup (`tools/github-app/setup.py`) serves its page on `127.0.0.1`, which a phone cannot open. The App was therefore created from GitHub's URL-parameter link with the contract's exact profile, and its key was generated on GitHub and pasted once (J27's path), not converted by the setup. The read-back above is the check.
- The App was first registered for its owner account only; Jake made it public before the `jparker2006` installation. The first read of the visibility was wrong (a web-page check instead of the API), and is corrected here.
