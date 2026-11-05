# OpenWiz public site

Dark static landing and `/changelog` pages. No runtime package, API, server or external font service.

The page (#1352, chosen through a judged design hill-climb, 2026-11-06) is one screen plus a short scroll: the headline "User decides, agents do." and its lead; the main button, **Copy the prompt** (paste it into your agent to install OpenWiz), with **Star on GitHub** second; the intro animation; **Works today** (one line per published version, each linking to `/changelog/`); **Building next** (one line per planned version, none a link); and a footer. Less text is better.

The intro is "the factory in motion": a crisp dark OpenWiz window where one typed idea becomes a plan of five tickets, you approve it once, three agents build side by side, their pull requests merge, and it rests on the board, with a few hand-drawn notes over it. It is one ~6 s sequence that then holds: every change is a CSS animation declared at load (`style.css`, "The landing intro"), finite, and nothing in the stage loops, so seeking `document.getAnimations()` reproduces any frame; text switches opacity at once (only movement eases), so every frame meets contrast; reduced motion jumps every animation to its end, the rest frame. The stage is one labelled illustration (`role="img"`, its parts `aria-hidden`), with synthetic data only, and the caption under it says it is not released. It sits on a static, inline-SVG etching of a blue town at night (generated once by a small script kept with the build evidence; edit the SVG in place or regenerate it). `script.js` splits the typed idea into letters and loads the handwriting font (Virgil) only after the page and its text fonts are in, so it never slows the first paint; the notes show once it is ready.

Round 5 of the climb (#1436, 2026-11-06) kept that page and refined it: the etching is a framed print inside the page grid; the window's board puts each follow-up ticket under its parent (desktop) or indented under it (phone, below a 640 px stage), with the status chips and model names appearing only after the one approval; the caption is type on the night under the window; Works today and Building next are one index with a solid rail (shipped) and a dashed rail (planned); and the changelog uses the same index system (mono versions on a rail, readable dates, numbered notes). Ticket titles fit at every width from 320 to 1440 px, also with slightly wider glyphs (checked by Round 5's narrow-width capture proof, not by `npm test`).

The look follows the app's design language (direction A "Observatory" plus a ⌘K jump bar): a charcoal canvas, Geist for all text and Geist Mono only for commands, ids and versions, wiz purple for live and focus, and gold only on the one primary action and the illustration's "Approve plan". The ⌘K bar (also Ctrl+K or `/`) filters and jumps to the page's sections and pages; it reads nothing and stores nothing.

`tokens.css` is the app's `apps/web/styles/tokens.css`, byte for byte (from `room/design-hill-climb` at `56970e2e`), and the Geist fonts are the app's own files. Never edit it here: copy the app's file and update the pinned hash in `test/ci.test.mjs`, which also fails if the app's copy and this one differ. `fonts/Virgil.woff2` is Excalidraw's Virgil, byte for byte from `github.com/excalidraw/virgil` at `3d4c829d` (SHA-256 `9976295bfe709bdea64839a4d4e9a1d436dd6eb67538399a5a0e8b8fadbcf1cf`), under the SIL Open Font License 1.1 in `fonts/Virgil-OFL.txt` (its `LICENSE.md` at that commit; Reserved Font Name Virgil, so it is shipped unmodified).

```sh
# From the repository root: install the existing browser test tools once.
npm ci --ignore-scripts --prefix apps/web
cd apps/site
npm run build
npm test
```

Build output is `apps/site/dist/`: only the two pages, the app's shared design tokens (`tokens.css`), the site's CSS/JavaScript, the local Geist and Virgil fonts and their OFL licences. Tests reuse the repository's existing Playwright and axe packages in `apps/web`; there is no new dependency. Chromium defaults to `/usr/bin/chromium`; set `OPENWIZ_CHROMIUM` to use another installed executable.

Serve `dist/` as a static root. Both `/changelog` and `/changelog/` must resolve to `changelog/index.html`. All paths are relative to the domain root. A local preview:

```sh
python3 -m http.server 8800 --bind 127.0.0.1 --directory dist
```

CI does not run the site yet: its build and test steps change `.github/workflows/ci.yml`, which needs a workflow-capable push (the patch is in #645's pull request). Until then, run `npm run build`, `npm test` and `npm run test:ci` locally; `classify.sh` already routes `apps/site/` changes to `web-build` and `web-test`. Copy checks cover all main-page text (including hidden text), the illustration's own synthetic text and label, links, the exact prompt, Works today (published versions only, each to the changelog) and Building next (planned versions only, no links). Browser checks cover 390, 768 and 1440 CSS pixels, all axe rules, dark mode under a light preference, static reduced motion, the intro's contract (finite, ends by 6.5 s, nothing loops, opens on the idea, rests merged, keeps its size), keyboard and emulated touch navigation, the ⌘K palette (open, filter, jump, close, axe while open), focus, the prompt (copy, fallback selection, no sideways scroll), local resources and overflow.

The Geist `.woff2` fonts ship with `fonts/OFL.txt` and Virgil with `fonts/Virgil-OFL.txt`; keep both in any static export. Browser tests prove behavior on fixtures in Chromium, not physical touch devices, a screen reader or live product behavior.

Hosting is intended for Cloudflare Pages: build from the repository root with `npm --prefix apps/site run build`, output `apps/site/dist`. Deployment and publication require the maintainer's separate action and release checks. This folder does not deploy anything.

`npm run test:ci` checks the private repository's CI classification separately. It is not needed in a public export. The portable `npm test` uses only the exported site source and the existing `apps/web` test tools. Once the CI site step lands, it also runs the release checker's fixture suite, with the rust job's pinned CPython where the runner has no `python3`.

For a checked source export, include the ten runtime files plus `package.json`, `build.mjs`, `.gitignore`, `test/build.test.mjs`, `test/site.test.mjs` and `test/approved-copy.mjs`. Install the existing `apps/web` tools before testing, as above. The release checker runs the site's build and tests in the exact fresh exported clone and refuses missing tooling, failed commands or empty or missing export/browser suite summaries.

The release plan needs hash-bound claim reviews for `apps/site/index.html` and `apps/site/changelog/index.html`, including all prose, hidden text and SVG text. HTML status and evidence stay in the review so the approved visible copy is preserved. Markdown retains its public status-label and evidence rules. HTML evidence uses the same public document, fragment and live-observation checks. Meaning still requires independent export review.

New font assets need an exact `scan_exceptions` review with `rule: "site-font"`, the font's path and SHA-256, and `value: "apps/site/fonts/OFL.txt@<licence-sha256>"`. Only the two pinned Geist fonts and their exact included OFL licence are accepted; changing a font or licence requires a separately reviewed update to the gate. Missing, conflicting, stale or unused reviews fail. A site font already in the public base still needs that exact review and licence. Other binary assets retain the existing release policy. The SVG namespace URL and the licence URL require the existing exact, file-hash-bound `url` reviews; they are not added to the global host allowlist.

**Not yet in the release gate (follow-up, outside this folder):** Virgil (`apps/site/fonts/Virgil.woff2`, SHA-256 above) and its licence `apps/site/fonts/Virgil-OFL.txt` need a hash-pinned entry in `tools/release/scans.py`'s `SITE_FONTS` and a `site-font` review whose value names that licence, exactly like the Geist fonts. Until that lands, a public export that includes this page is refused by the gate, as it should be.

The site's root-relative links resolve inside `apps/site` and check targets/fragments. Ordinary Markdown evidence remains relative to the public export. Only the target's exact inert favicon data URI is allowed, on the two site pages; other data URIs and schemes are refused.
