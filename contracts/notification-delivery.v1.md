# Notification delivery: observed binding v1 (#2033)

This contract records what discovery actually observed about phone notification delivery. It is the input T4 may build on. **Today it binds nothing:** every element below is unsupported or unverified, so T4 has no positive transport binding and must not start transport work from it. A later discovery replaces it with a new version.

**Source:** the bounded read-only discovery of 2026-11-13 (`docs/spikes/0.0.15-notifications.md`), over the engine's loopback address. Its notification status read refused with `503 state_unavailable`, and the run stopped there.

| Element | Status | Basis |
| --- | --- | --- |
| Status route | **Present; refuses** | `GET /api/v1/notifications/status` answers `503` `{"error":{"kind":"state_unavailable","message":…}}` while protected notification state is unavailable. It admitted no effect |
| Transport invocation and protocol | **Unverified** | No capability was reported; the worker (`/sw.js`) was not read |
| Subscription and key ownership | **Unverified** | No subscription state was readable; none was created |
| Permission state | **Unverified** | No browser context was evaluated; no prompt was shown |
| Outcomes (delivered, failed, uncertain) | **Unverified** | No outcome status was readable |
| Navigation on tap and closed-cockpit display | **Unverified** | Not observable over loopback; needs the phone (T8) |
| Install metadata (manifest scope, start URL, display) | **Unverified** | `/manifest.webmanifest` was not read |
| Online address, Access login, owner-only open | **Unverified until T8** | Loopback reads reach only the engine on its own host |

**Rules for consumers:**
- Treat every row except the status route as unsupported. Show "unavailable" or "unknown", never "on" or "delivered".
- `state_unavailable` is an honest refusal, not a transport. It must keep admitting no effect.
- A positive binding needs a new discovery under a fresh OK, with a selected engine, its protected notification state, and the worker and manifest reads completed.
