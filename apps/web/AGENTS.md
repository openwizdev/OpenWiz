# apps/web: the OpenWiz web viewer

A Next.js static export (Pages Router, `out/`), served same-origin under `/` by `openwiz-server`. It reads with `GET /api/v1/...`, and writes only on an owner's press: the send, the create, and an attachment's upload and removal ([contract](../../contracts/web-api.v1.md)). It shows only what the [envelope](../../contracts/inventory.v1.schema.json) and the core's reports carry.

- **Rules:** [docs/design-rules.md](docs/design-rules.md) for the look, markers, spacing and honesty.
- **Contract and fixture proofs:** [web API](../../contracts/web-api.v1.md) and `test/`. Fixture proofs do not establish live behaviour.
- **Toolchain:** Node 24.22.1, npm, `npm ci --ignore-scripts`. **Add no package without Jake.**
- **Never:** `dangerouslySetInnerHTML` or other HTML sinks, `fetch` or `XMLHttpRequest` outside `src/api.ts`, sorting or grouping rules beyond `src/present.ts` (G1), storage other than the composer's, the launcher's and the tray's `sessionStorage` (read in `src/composer.ts`), a send, a create or an upload outside an owner's press (#9: the composer, `docs/design-rules.md` rules 20–30; #12: the launcher, rules 31–40; #16: the tray, rules 41–50), a second prompt body, tray, panel or sheet, an image other than the tray's thumbnail of the owner's own file or the app's own icons, any service worker or manifest but the installable app's below. `npm run check` enforces these in `pages/` and `src/`.
- **Decision cards' own words (#656): exactly one exception to the one prompt body.** `src/components/Decisions.tsx` may render one plain `<textarea>`, a card's Own words field, bound to that card's question, its record and the verified orchestrator target. It has no tray, no attachments and no composer of its own: its exact text goes through the same `Composers.press` send, with the card's receipt in the composer's tab storage. `npm run check` allows exactly that file and `PromptBody.tsx`. See [design rule 54](docs/design-rules.md#decisions-656).
- **Feedback and sharing (#2292): exactly two exceptions.** Jake approved them (J28, recorded on #2292). `src/components/FeedbackShare.tsx` may render one plain `<textarea>`, the owner's chosen public feedback, with no tray, attachments, composer or send: its only effect is one clipboard write of the previewed handoff on Copy. `src/feedback.ts` may hold exactly one absolute URL literal, the share allowlist's `https://github.com/openwizdev/openwiz` ([feedback.v1](../../contracts/feedback.v1.md#sharing)). `npm run check` refuses any other `<textarea>` or URL literal, and `test/unit/feedback.test.ts` proves it on planted violations.
- **The installable app (#1029): exactly one exception.** Jake approved this exception ([private record, preserved 2026-11-07](https://github.com/jparker2006/ClosedWiz/issues/1277#issuecomment-6704800036)). `public/manifest.webmanifest`, the icons in `public/icons/`, the app-shell worker `public/sw.js` and its one registration, `public/sw-register.js`, linked from `pages/_document.tsx`. They stay in `public/`, outside the checked sources, which still may not touch `serviceWorker`, `caches` or storage. The worker caches only the static shell (`/`, `/setup`, the manifest, `/_next/static/`, `/fonts/`, `/icons/`); it never handles an API request or anything but a `GET`, so no answer about a session is stored and no send, create, upload or removal is ever queued, retried or replayed offline. No sync, messages or background fetch. Its one notification exception (#2035): a `push` shows one generic notification only for notifications.v1's exact minimal payload, and a `notificationclick` only opens this origin's `/#notification=<token>`; neither fetches, caches, stores, answers or replays anything, and the worker never subscribes. `test/unit/pwa.test.ts` proves it (P6, P9, P10). The notification settings' one storage exception (#2035 R1; [private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6848743936)): the pending notification-preference operation, its id and body only, may be kept in this tab's `sessionStorage` (through `src/composer.ts`'s `browserStorage()`), saved before the PUT, cleared only when its result is read, and repeated only by the owner's explicit "Retry the same change". No other storage, key or data.

| Path | What |
| --- | --- |
| `src/envelope.ts` | The envelope types (exactly the schema) and exact runtime checks |
| `src/api.ts` | The only requests. Every response becomes one outcome |
| `src/poller.ts`, `src/timing.ts` | One read per kind: the next starts when the server has answered, or after its bound. Capped backoff, paused while hidden. Provisional timings |
| `src/viewer.ts` | Presentation state only |
| `src/components/` | The page, list, detail and status pieces; the composer and the launcher, which share `PromptBody.tsx` |
| `src/launcher.ts`, `src/newthread.ts` | The launcher's presentation state and its one create (#12); the new-thread shapes it reads |
| `src/attachments.ts`, `src/components/AttachmentTray.tsx` | The one attachment tray (#16): each target's list, its one upload and removal, safe previews; rendered once, in `PromptBody.tsx` |
| `test/unit/`, `test/browser/` | The proofs V1–V11, W7–W13, U5, U7–U15 (#12), AW5–AW11 (#16) and the installable app's P1–P8 (#1029) |

```sh
npm ci --ignore-scripts && npm run build   # the static export in out/
npm run typecheck && npm run check         # tsc; the static checks and the spacing rule
npm test                                   # unit, then browser proofs (needs out/ and cargo)
```
