# OpenWiz web: design rules

The OpenWiz app's look: the **Observatory** shell with **⌘K**, landed as M6 (#1027) under the Design spec (#1022) and its confirmed design decisions (DA2 and DA5). It replaces the v1 terminal look (the cockpit grill's K6). The honesty and behaviour rules began as the UI owner's v1 handoff (`DESIGN-RULES.md`, SHA-256 `7dbde2af…7fbbd`) and still bind. Settled rules: don't reopen them while building. Anything marked **Open for Jake** is decided on the working site.

The app shows only what the envelope carries ([`contracts/inventory.v1.schema.json`](../../../contracts/inventory.v1.schema.json)), read through the web API ([`contracts/web-api.v1.md`](../../../contracts/web-api.v1.md)), and writes only on an owner's press: the send, the create, and an attachment's upload and removal. A rule here never adds a field, a read or a rule of the core's.

## The thesis

A calm, dark, real app, polished like a professional team's and copying no one: quiet by default, loud only where the owner is needed.

- **ASCII only as art; monospace only for ids and hashes; every status = word + icon + shape.** No bracketed ASCII status markers, prompt underscores, ASCII boxes or monospace labels anywhere in the interface. ASCII, dither and stipple may appear only as artwork in brand moments (empty states, loading, the landing page), never as chrome or as a status.
- **Status is drawn.** Every status glyph is an inline SVG icon beside the core's word. A text character is never a status glyph.
- **[`styles/tokens.css`](../styles/tokens.css) is the source** of every colour, type, spacing, radius, elevation, motion and layout value. This page names tokens and their jobs; it never restates or overrides a value. A size no token has belongs to its screen's stylesheet, scoped to that screen.
- **Dark only.** No light mode.
- **Gold means Needs you; purple means live, selected and focus.** Lakers purple is brand only; greys carry everything else. No red or green.
- **Geist for every interface and reading text; Geist Mono only for ids and hashes** (a thread id, a fleet or ticket id, a project id's suffix). Both are bundled.

## The Observatory shell and ⌘K

**Desktop (900 px and wider):** a persistent sidebar (`sidebar-width`) on the canvas holds the logo slot and wordmark, the Views (Home, Sessions, Fleets, New thread), the Projects anchors with their counts, and the connection footer. Each screen sits on one soft main sheet beside it, edged by a 1 px `color-divider` hairline. Sessions is a split view: while idle the list fills the sheet beside a narrow quiet companion pane (`companion-width`: 320 px, under a third of a narrow split). Opening a thread or launcher returns the list to `list-width`, giving the reading pane its room. From 900 to 1100 px the stylesheet narrows the sidebar and list widths so the thread stays usable; the token file is unchanged.

**Phone (below 900 px):** a compact top bar (`top-bar-height` plus `safe-top`) shows the logo slot and wordmark, or the open screen's title, and the search trigger. The Views become four safe-area-aware bottom tabs (`tab-bar-height` plus `safe-bottom`): Home, Sessions, Fleets and New. Home and Sessions sit directly on the canvas, edge to edge, with 16 px row insets. A thread, the launcher and a session's details open as a full-height sheet.

Project anchors and counts come from `groupPage` for the current inventory page. They navigate only. The shell's New thread opens the first listed project's existing launcher; without a project it is disabled.

**⌘K.** ⌘K or Ctrl+K anywhere, `/` outside a text field, or the "Search or jump to…" trigger opens one command dialog. Typing filters its destinations: Go to Home, Go to Sessions, Go to Fleets, New thread in a project (which opens that project's launcher and never creates), and each listed session by its title, with its status mark. The arrow keys move, Enter goes, and Escape closes and returns focus to the control that opened it. **It navigates only:** it never sends, creates, starts, resumes or messages anything.

## Observatory app components (round 2b, V5)

`StatusMark` renders inline SVG shapes with the verbatim status word supplied by `Marker`: active has an orbiting dot, idle a hollow ring, error a gold diamond, other/unknown a dashed ring ([Markers](#markers-five-tiers-told-apart-by-shape)). Reduced motion stops the orbit. This replaces all rendered ASCII markers, including outcomes and attachments. `Ui.tsx` supplies primary, secondary and quiet buttons, section labels and soft panels; icons share a 1.5 px stroke. Selected rows use the purple selection surface plus a purple edge; an error row's gold edge takes that edge's place, selected or not. Coverage, snapshot time, the gap summary and disclosure remain visible and honest. Retry uses the existing inventory poller lane and keeps its snapshot.

## Integrated Observatory screens (M3-T2)

The accepted command navigation, thread dock, New thread setup and Fleets panels share the existing shell, buttons, StatusMark and token values. The command dialog stays available over the phone’s existing thread or launcher dialog; Escape restores the active control and preserves the draft. The thread’s sticky header controls sit inside its reading scroll area, making that area keyboard accessible without adding a stop between Close and the message field. Screen-specific reading, prompt and progress layouts stay scoped to their owning screen. Superseded composer action rules and duplicate mobile layout overrides are removed. No shared token value changes.

## Coverage and freshness (R4-S2)

Sessions and thread reads use compact provenance chips: SVG shape, state word, and the full visible read time including seconds (also retained on the time element's title). The sidebar's connection footer uses the same shapes and words, with its read time to the minute. Chips have no fill. Complete stays quiet (shape and words only, no outline); Partial has a dashed control-edge outline and secondary text, never gold. On Sessions the chip shares the title's line, at its right. The existing coverage disclosure keeps its accessible name, 44 px target, focus behavior and gap details. The gap summary stays visible while collapsed; thread gaps remain fully expanded. Connection icons distinguish live, stale, disconnected, signed out, busy, reading and error in greyscale. No shared token values change.

## Sessions empty and read-error states (R4-E1)

Sessions uses a centered soft panel, a neutral icon tile and a single title for its existing empty and read-error states. The reported error reason and last-snapshot line stay visible; Retry uses the shared purple primary button and the same read lane. All empty variants and First page keep their words and behavior. No New thread action is invented without a project. This treatment is scoped to Sessions; thread and fleet states keep their existing presentation. Shared token values are unchanged.

The desktop Sessions view gives the idle list everything but a narrow companion column (`companion-width`: 320 px, or under a third of the split from 900 to about 1200 px), 8 px apart, as an open thread's sheet sits. With no session or launcher open, the companion pane (no fill, a 1 px `color-divider` outline, full height) shows only the hint explaining what selecting a session reveals, as a top-aligned empty state: `type-body` in `text-tertiary`, left-aligned at the pane's 24 px inset, its first line on the search field's centre line, with a 240 px measure so it breaks at the comma. The sidebar footer also carries connection information only; neither surface has decorative line art. It is omitted while the list is empty, reading without a snapshot, or failed, and hidden below 900 px; opening a thread or launcher restores `list-width` and the existing reading layout. The companion's width has its own layout token.

Integration test markup notes (M4; full-time expectations restored for #1027 review R1):

- `test/browser/design-pass.test.mjs`: the contrast selector targets the chip that owns the dashed outline and includes its full read time with seconds; added checks keep gap text visible while collapsed.
- `test/browser/v6-states.test.mjs`: the snapshot expectation requires the full last-good read time with seconds; added checks keep every connection state clear of phone search.
- `test/support/expect.mjs`: the shared detail expectation requires the chip's full visible timestamp, including seconds.

## Fleet detail (R5-F2)

The fleet's id and title lead its detail, beside the reported merged count and a thin neutral progress track. Needs you reuses the list's reported decisions and Answer action, including its unavailable explanation and composer focus return. The graph uses the shared SVG status shapes and the existing layout; when it cannot fit or be read, its exact explanation stays visible. Tickets use the model's state groups at both widths, keeping each status word, fact and builder control. Long facts wrap; reviewer uncertainty stays quiet. All layout rules are scoped to fleet detail, and shared token values are unchanged.

## Accepted screen integration (M5)

The message dock keeps attach, staged files and its send buttons on one action row, followed by the core's effect words and read ages in one wrapping hint line. The thread header keeps the status inline with its title, wraps metadata as whole items and shows the id in Geist Mono. Session metadata flows evenly without a status slot; its inline marker shares the text baseline, and a changed status replaces the metadata run atomically so adjacent facts do not slide independently on refresh; empty and error panels fit their content. Desktop thread Close retains a 32 px hover surface inside a 44 × 44 px button. Shared tokens are unchanged.

Integration test markup notes (accepted commits; no assertions weakened):

- `test/support/composer.mjs`: read action effects from their new shared hint line, retaining the unsettled-control fallback.
- `test/browser/design-pass.test.mjs`: retain the accepted checks for inline status, whole metadata items, mono id and phone controls.
- `test/browser/c5_answer.test.mjs`: retain the accepted detail fixture and checks for Answer prefill, no send and focus return at both widths.
- `test/unit/fleetGraph.test.ts`: scope ticket selectors to the ticket section, expect the accepted state grouping on desktop and count the shared SVG glyphs.
- `test/design-screens.mjs`: retain the accepted synthetic fleet-detail screen and its detail response.

## Fleet graph (R7-GR)

Only the fleet detail graph changes: rounded pills use the shared StatusMark glyph, ticket ids in Geist Mono and full sans state words. Outside-blocker versions sit on their own quiet line; long ids or versions widen the layout rather than clipping. The existing dependency order, arrow direction, hooks and fallback explanations stay intact. Neutral 1 px connectors and additional vertical space keep paths and pills distinct; gold stays on owner-needed nodes. Shared tokens are unchanged.

`test/unit/fleetGraph.test.ts` updates literal pill coordinates and the resulting width-fallback text and SVG dimensions. Assertions retain exact geometry, fit, direction, ordering and greyscale checks.

## Tokens

[`styles/tokens.css`](../styles/tokens.css) is the shared Observatory + ⌘K foundation, and the only place its values live: read a value there, never from this page. **Exception (#1451):** the list screens' values (`color-divider`, `color-fleet-numeral`, `color-progress-track`, `type-row`, `type-section`, `type-page-label`, `type-meta`, `tracking-section`, `tracking-page`, `tracking-heading`, `tracking-title`, `tracking-row`, `font-features`, `font-features-data`, `id-size`, `list-width`, `companion-width`) live in the first `:root` of `globals.css`, because `apps/site` copies `tokens.css` byte for byte; they move into `tokens.css` when the landing's copy is retuned with it. Import it before consumer styles; the app imports it first in `globals.css`. Keep CSS in `styles/`. The `--ow-` namespace is reusable by the landing page, which must also serve the bundled `/fonts/Geist-var.woff2` and `/fonts/GeistMono-var.woff2` (licences in `public/fonts/`). No remote styles or fonts: the static export retains `style-src 'self'` and `font-src 'self'`.

Prefer tonal grouping and space. Quiet lists (Home, Sessions) separate rows with 1 px `color-divider` hairlines. Search, Refresh fleets, New thread and secondary buttons use the same subtle hairline and `radius-6`; their text or icon identifies the action, with a visible purple keyboard focus ring. Search has no resting fill. Key caps keep `color-hairline`. Gold is reserved for needs-you content; Lakers purple is brand only. Never use red or green. Text roles and live/gold foregrounds work on all eight dark surfaces; solid gold uses only `color-on-attention`. Brand and hairline are not text colours. Type tokens are `font` shorthands, and every line height is a multiple of 4. The shorthand resets font features, so one pinned rule gives every element `font-features` (the landing's `ss01`); a role that shows times, counts, reads or facts sets `--ow-font-features: var(--ow-font-features-data)`, which adds tabular figures (`tnum`) to it and everything inside it. Existing `font-variant-numeric: tabular-nums` declarations stay valid.

| Token (`--ow-` prefix) | Job |
| --- | --- |
| `color-canvas` | App backdrop and sidebar. |
| `color-sheet` | Main content sheet above the canvas. |
| `color-panel` | Raised reading panels and composer. |
| `color-overlay` | Menus and the command dialog. |
| `color-hover` | Neutral hover feedback. |
| `color-selected` | Soft purple selection surface; pair with a shape. |
| `color-hairline` | Subtle boundary only where a control needs one; not its sole identifying edge. |
| `color-divider` | 1 px white-alpha hairline between quiet-list rows and sections, sheet and quiet-control edges; never text or a control's sole identifying edge. |
| `color-fleet-numeral` | Home fleet count and merged-progress digits: a neutral step above their words, below title ink. |
| `color-progress-track` | Opaque dark fleet-progress track; primary text colour draws the completed segment. |
| `color-control-edge` | Identifying control edge; at least 3:1 on every dark surface. |
| `color-text-primary` | Titles and main content on dark surfaces. |
| `color-text-secondary` | Supporting copy and labels on dark surfaces. |
| `color-text-tertiary` | Quiet helpers, ids and placeholders on dark surfaces; still AA. Desktop Home and Sessions facts use secondary text. |
| `color-live` | Live status, current location and purple accents. |
| `color-live-tint` | Quiet background for live status. |
| `color-attention` | Only an item or action that needs the owner. |
| `color-attention-tint` | Quiet background for attention content. |
| `color-on-attention` | Readable dark text on a solid gold fill. |
| `color-brand` | Lakers purple for brand artwork only; never status or body text. |
| `color-focus-ring` | Visible keyboard focus on dark surfaces (the live colour). |
| `hairline-pattern` | Kept for compatibility; the app draws no dotted rules (its `--hair` alias is `none`). No new decorative dividers. |
| `font-sans` | Bundled Geist for all interface and reading text. |
| `font-mono` | Bundled Geist Mono for ids and hashes only. |
| `type-caption` | Captions and quiet annotations; Home and Sessions use this on phones. |
| `type-meta` | Desktop Home and Sessions facts and captions: regular 13 px on a 20 px line. |
| `type-label` | Control and section labels. |
| `type-body` | Default interface copy. |
| `type-body-reading` | Purpose, replies and longer reading. |
| `type-row` | Compact session and fleet row titles. |
| `type-section` | Quiet secondary headings: Home sections and Sessions project names. |
| `type-page-label` | Home's page name as a quiet header label (15 px medium), so Needs you is Home's first and largest heading. |
| `type-title` | Decision row and panel titles. |
| `type-heading` | Section headings. |
| `type-page` | Page headings. |
| `type-display` | Prominent thread or display headings. |
| `tracking-page` | Tight negative tracking for 24 px page titles and the wordmark. |
| `tracking-heading` | 20 px section headings (Needs you). |
| `tracking-title` | Slight tightening for 16 px decision titles. |
| `tracking-section` | Slight tightening for 15 px secondary headings. |
| `tracking-row` | Neutral tracking from 14 px down: row titles, labels, captions. |
| `font-features` | The landing's Geist features (`ss01`, its tailless a), pinned on every element. |
| `font-features-data` | `font-features` plus tabular figures, for every time, count, read and fact. |
| `id-size` | An id's size: one step (2 px, at least 11 px) under the text it precedes. |
| `numerals-tabular` | Stable numeric columns via font-variant-numeric. |
| `space-0` | No spacing. |
| `space-4` | Tight inline spacing. |
| `space-8` | Related items. |
| `space-12` | Compact control interiors. |
| `space-16` | Standard component interiors. |
| `space-24` | Sections and roomy interiors. |
| `space-32` | Major content groups. |
| `space-48` | Large layout separation. |
| `radius-6` | Compact controls and small tiles. |
| `radius-8` | Panels and standard controls. |
| `radius-12` | Main sheets and overlays. |
| `radius-full` | Pills, rings and round icon tiles. |
| `shadow-sheet` | First elevation; use with the sheet tone. |
| `shadow-panel` | Second elevation; use with the raised panel tone. |
| `shadow-overlay` | Highest elevation; use with the overlay tone. |
| `motion-fast` | Small hover and focus transitions. |
| `motion-standard` | Normal state changes. |
| `motion-slow` | Panel and dialog transitions. |
| `ease-out` | The single settling curve; no bounce. |
| `orbit-period` | Calm live-dot orbit; static under reduced motion. |
| `sidebar-width` | Desktop navigation column. |
| `list-width` | Desktop sessions list beside an open thread or launcher. |
| `companion-width` | Narrow desktop Sessions companion beside the idle list. |
| `touch-target` | Minimum interactive width and height. |
| `top-bar-height` | Compact top bar, before the safe-area inset. |
| `tab-bar-height` | Phone tab bar, before the safe-area inset. |
| `safe-top` | Top device inset; add to layout sizing when needed. |
| `safe-right` | Right device inset. |
| `safe-bottom` | Bottom device inset for tabs and composer. |
| `safe-left` | Left device inset. |
| `legacy-detail-width` | Kept from the screen migration; the app no longer reads it. |
| `legacy-detail-width-wide` | Kept from the screen migration; the app no longer reads it. |

Motion consumers must use the duration tokens and the single ease-out curve. Under `prefers-reduced-motion: reduce`, the token file sets all three durations and the orbit period to zero: no transitions or orbit motion. Safe-area tokens are device insets, not additions to the spacing scale; add them to bar sizes and docked controls where needed. Elevation uses three tones with optional matching shadows, never extra divider chrome.

WCAG 2 contrast, computed from the exact opaque sRGB values in `tokens.css`: linearize each channel (`c / 12.92` for `c ≤ 0.04045`, otherwise `((c + 0.055) / 1.055)^2.4`), then `L = 0.2126R + 0.7152G + 0.0722B`; ratio = `(lighter L + 0.05) / (darker L + 0.05)`. Values are rounded to two decimals only after testing the unrounded ratio. No opacity is applied to text. The table records the colour values as they landed with M6 (#1027); a change to a colour token recomputes it in the same change. `test/unit/contrast.test.ts` enforces the 4.5:1 text and 3:1 shape floors from the stylesheets themselves.

| Surface | Primary | Secondary | Tertiary | Live / focus | Gold | Control edge |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `color-canvas` | 15.91:1 | 10.14:1 | 7.71:1 | 7.05:1 | 11.09:1 | 4.93:1 |
| `color-sheet` | 14.91:1 | 9.50:1 | 7.23:1 | 6.60:1 | 10.39:1 | 4.62:1 |
| `color-panel` | 13.86:1 | 8.83:1 | 6.72:1 | 6.14:1 | 9.66:1 | 4.30:1 |
| `color-overlay` | 12.44:1 | 7.93:1 | 6.03:1 | 5.51:1 | 8.67:1 | 3.86:1 |
| `color-hover` | 11.29:1 | 7.19:1 | 5.47:1 | 5.00:1 | 7.87:1 | 3.50:1 |
| `color-selected` | 12.62:1 | 8.04:1 | 6.12:1 | 5.59:1 | 8.80:1 | 3.91:1 |
| `color-live-tint` | 13.33:1 | 8.50:1 | 6.46:1 | 5.91:1 | 9.29:1 | 4.13:1 |
| `color-attention-tint` | 12.18:1 | 7.76:1 | 5.91:1 | 5.40:1 | 8.49:1 | 3.78:1 |

`color-on-attention` on `color-attention`: **10.65:1**. Minimum text contrast across dark surfaces is **5.00:1** (live on hover); tertiary text is at least **5.47:1**, and control edges at least **3.50:1**. Hairlines are supplementary and cannot identify a control alone. Avoid putting dark-surface text roles on solid accent fills.

Existing `globals.css` variables remain compatibility aliases (no selector or behaviour change):

| Existing variable | Shared token |
| --- | --- |
| `--canvas` | `--ow-color-canvas` |
| `--s1` | `--ow-color-sheet` |
| `--s2` | `--ow-color-panel` |
| `--s3` | `--ow-color-overlay` |
| `--line` | `--ow-color-hairline` |
| `--line-2` | `--ow-color-control-edge` |
| `--ink` | `--ow-color-text-primary` |
| `--ink-2` | `--ow-color-text-secondary` |
| `--ink-3` | `--ow-color-text-tertiary` |
| `--gold` | `--ow-color-attention` |
| `--wiz` | `--ow-color-live` |
| `--brand` | `--ow-color-brand` |
| `--on-light` | `--ow-color-on-attention` |
| `--sans` | `--ow-font-sans` |
| `--mono` | `--ow-font-mono` |
| `--safe-b` | `--ow-safe-bottom` |
| `--hair` | `none` (no token): the remaining dotted-rule consumers draw nothing |

## Colour

1. **Status never depends on colour.** Every status shows the core's own **word**, a drawn **icon** and a **shape**. Check every screen in greyscale. The owner is colourblind.
2. **Each colour has one job:**

   | Colour | Tokens | Job |
   | --- | --- | --- |
   | Gold | `color-attention`, `color-attention-tint` | You're needed: Needs you, the owner's action there, and a status that stopped for you (t1) |
   | Wiz purple | `color-live`, `color-live-tint`, `color-selected`, `color-focus-ring` | Live, now, selected, you are here, and the focus ring |
   | Lakers purple | `color-brand` | Brand only: the logo slot and brand artwork |
   | Greys | The surface and text tokens | Everything else |

   **No red or green.**
3. **Dark only.** Observatory's roles are in [Tokens](#tokens), and their values in `tokens.css`. These supersede the v1 palette.
4. **WCAG AA is the floor:** 4.5:1 for every text role, 3:1 for identifying control edges and status shapes on their surfaces.

## Markers: five tiers, told apart by shape

Every status renders through `StatusMark`: a drawn SVG icon (`aria-hidden`, 1.5 px stroke) and the core's word. The tier sets the shape; colour only repeats it.

| Tier | Icon (shape) | Colour |
| --- | --- | --- |
| t1 stopped | Solid filled diamond | Gold |
| t2 your move | Rounded square with a check | Primary text |
| t3 moving | Ring with a filled core and an orbiting dot (the orbit stops under reduced motion) | Live purple |
| t4 quiet | Hollow ring | Secondary text |
| t5 unsure | Dashed ring | Secondary text |

Fleet states draw their own icons on these tiers: needs info a diamond with a question mark, blocked a rounded square with pause bars, in review and changes requested a ring with a forward or a back chevron, and not merged a ring with a bar. Legacy text glyphs still carried in the marker data (`markers.ts`, `fleets.ts`, `AttachmentTray.tsx`) are never rendered.

- **The word is the core's status, as reported, word for word.**
- An unknown status is `unknown (reason)`, with the core's reason word for word, in t5's dashed ring.
- A word without a decided tier renders as t5. Never guess.
- The icon is decorative (`aria-hidden`). The word is the accessible name.
- **The word is shown whole.** A long one wraps; it is never cut with `…`.
- **The icon keeps a fixed slot** before the word (a session row's left gutter), so the title and the word stay put when the tier changes.
- **Modifiers are never statuses of their own:** `partial` is the coverage chip's dashed outline and `stale` the connection's clock ring, each with its word.

**Open for Jake: the tier for each status word.** The handoff's vocabulary (`needs_you`, `building`, `PR-ready` and so on) is the future controller's, not `room-cli`'s. The 0.43.1 fixtures carry `active`, `idle` and `error`. The builder's proposal, until Jake decides:

| Word | Tier | Icon |
| --- | --- | --- |
| `active` | t3 | Orbiting ring |
| `idle` | t4 | Hollow ring |
| `error` | t1 | Gold diamond |
| Every other word | t5 | Dashed ring |

## Layout

5. **Quiet lists: one calm sheet of hairline-separated rows. No bordered cards.**
   - **Session rows** are full-width square rows separated by 1 px `color-divider` hairlines; hover and selection change the surface tone. Each project's heading is sticky on the sheet's tone (the canvas on a phone), with a hairline under it. Project names use `type-section` with `tracking-section` in secondary ink: 15 px semibold, distinct from metadata. A `space-32` break on desktop (`space-24` on phone) before each following project separates groups while the heading stays attached to its rows; the New thread action retains its 44 px target.
   - **Each row:** the status icon (a 20 px shape in a fixed 24 px slot) in a left gutter; the title and age on the first line, the age a right-aligned tabular column with a reserved desktop width; the status word, the session facts and an ungrouped row's reason on a quiet line under it. A missing age's explanation wraps as a whole item when possible; long explanations still break safely. On desktop the metadata and age use `type-meta` in secondary ink, with status colours retained. The 20 px metadata line replaces the smaller caption's `space-4` top gap; the age is centred on the title line, keeping short rows at 64 px. The same content appears at both widths. Phone rows keep their 44 px minimum target and compact spacing; the coverage summary leads straight into the project heading.
   - **The selected row** has the `color-selected` surface and a 2 px live-purple edge at its left, never only a tint; an error row has a gold edge in that place instead. No indent: every title keeps its column (Jake, 2026-10-30).
   - **Group headings** show the project name as reported: never re-cased.
   - **Twin names (G2, Jake, 2026-10-30):** when two headings on one page share a name, each ends with its project id's last 4 characters (`· 0004`). Only then.
6. **Phone and desktop show the same content:**
   - **Phone:** a full-height sheet for a thread, the launcher and details.
   - **Desktop (≥ 900 px):** beside the list, in the split view.
7. **Spacing:**
   - Only the `space-*` scale for margin, padding and gap.
   - Touch targets are at least `touch-target`; only Home's Answer and Refresh fleets draw smaller, on a pointer-driven desktop ([Home](#home-the-quiet-list-hill-climb-a)). The top bar is `top-bar-height`.
   - Line heights are multiples of 4.
   - Enforced by the spacing check (`npm run check`).
8. **Type:**
   - Geist for every interface and reading text, through the `type-*` tokens.
   - Geist Mono only for ids and hashes (`#904`, a session id in a gap line, a twin heading's suffix): the `ref-id` class (and the heading's `gid`) sets them in tertiary text, regular weight, at `id-size`, on the baseline of the words they precede.
   - One weight per role: 600 for page and section headings, 500 for titles and labels (Home's page name is a label: `type-page-label`), 400 for metadata and ids. Home fleet count and merged-progress digits use 500 within their regular-weight words. Tracking tightens with size (`tracking-page`, `tracking-heading`, `tracking-title`, `tracking-section`) and is neutral (`tracking-row`) from 14 px down.
   - Headings use `type-section`, `type-heading`, `type-page` and `type-display`; no condensed or light display face.
   - **A page's first answer is its largest heading.** On Home that is Needs you, so the page name steps down to `type-page-label` in a header row; on Sessions the list itself is the answer, so its name keeps `type-page` above the 15 px project names.
   - Tabular figures for every time, count, read and fact (`font-features-data`); titles and reading text keep proportional figures. Titles wrap with `text-wrap: pretty`, so no word is left alone on a line.
   - Desktop Home and Sessions use `type-meta` (13 px, 20 px line) for session facts, ages, waiting and source lines, counts, snapshot, scope and gap captions. Information uses secondary grey; composer helpers, ids and the idle companion hint stay tertiary. The companion hint and Answer helper also use the larger desktop type. Phone captions keep `type-caption` and their existing colours, with Home fleet numerals lifted to `color-fleet-numeral`. Existing colour tokens are unchanged.
   - The fonts are bundled in `public/fonts/` with their licence (`OFL.txt`). Never load a font from a CDN.
9. **Less text.** One short line per item. No intro paragraphs: the only explanatory copy is in designed empty, error and companion states. Details are one tap away.

## Honesty

10. **Every list carries the envelope's coverage, snapshot freshness and gaps.** Complete and fresh stay quiet; anything else gets its own word and shape.
    - Partial always has its dashed coverage chip. With gaps, the chip sits in a 44 px disclosure toggle with a drawn chevron, and the gap summary stays visible while it is collapsed.
11. **"No sessions" appears only after a complete, successful, fresh read** that matched nothing.
12. **Ungrouped sessions stay visible, with the core's reason word for word.** Never guess their project.
13. **Archived is never success.**
14. **Stale, partial, disconnected, signed out and each core error each have their own word and shape.**
    - Disconnected shows the last good snapshot time.
    - Stale data is never shown as fresh.

## Behaviour

15. **Listing, inspecting and navigating are read-only.** They never wake, start, resume or message anything; nor do the shell's views and anchors or ⌘K. The composer ([below](#the-composer-9)), the launcher's Start thread ([below](#the-launcher-12)) and the attachment tray's uploads and removals ([below](#the-attachment-tray-16)) are the only controls that act, and only when the owner presses them.
16. **The web holds presentation state only:** the scroll position, the open sheet or panel, the selected session, the current page, the last good snapshot, each thread's composer state (rule 26) and each project's launcher draft (rule 36).
    - Grouping, ordering, visibility, truncation, unknowns, coverage and freshness come from the envelope. `groupPage` only puts the page's rows under their headings: groups in the order their first row appears, rows in the page's order (G1, as `openwiz ls` prints them).
    - The web never re-sorts or fills them in.
17. **Session text is untrusted.**
    - Titles, purposes, final output, reasons and messages render as plain text only.
    - Each is isolated for bidirectional text.
18. **Wizard artwork:** a placeholder logo slot only, until Jake supplies the approved asset. **Never draw, trace or imitate the wizard.**
19. **Label anything synthetic as DEMO** (fixtures, test screenshots).

## The composer (#9)

One text message to the open thread: `openwiz send`, through `POST /api/v1/sessions/{id}/messages` ([contract](../../../contracts/web-api.v1.md#sending-the-one-write)). The core decides every effect and outcome; the composer shows them.

20. **Placement:** in the existing thread panel and sheet, with one message dock pinned below the scrolling Purpose, Latest reply and Sent from here outcomes (including "no final output yet"). On phone the dock sits above the safe area; its one-row message field grows with text, Add files is an icon with the same accessible name, and the core’s effect and age lines stay visible in one wrapping hint line under the actions. Never a page, panel or sheet of its own (W12, checked by `npm run check`).
21. **One target: the open thread,** from the path only. Drafts are kept per thread id. Switching threads never sends to another thread, and an answer lands on its own thread. A thread no longer listed on this page can't be sent to: the buttons are disabled, with "can't send: …" saying why.
22. **The button names the action,** with the core's effect line and "effect read N ago" in the hint line under it, all from the core's preview, before pressing:

    | The core's preview | Buttons |
    | --- | --- |
    | `starts_turn` (idle) | **Send** |
    | `queues_behind_turn` (a running turn) | **Queue** (the default, first) and **Steer** (explicit), each with its own preview's line |
    | Needs acknowledgement (a queue that appears paused) | **Send and resume queue**, with the core's "resumes the paused queue; N queued messages may run after this one" on its own line, in ink. The only way the resume flag is set |
    | Refused (archived, hidden, not found, …) | **Send**, disabled, with the core's reason |
    | Anything else | **Queue**, with the core's words, or `unknown (…)` when the core's preview says the effect is unknown |
    | No preview (not read yet, or the read failed) | Disabled: "can't send: what a send would do couldn't be read (…)". **No preview, no send** (Sol round 1) |

    The preview is read again on each refresh of the thread and after each answer. When the buttons or lines change while there is a draft, a `· changed` tag says so. The request carries the pressed button's mode; nothing changes it after the press. The composer says whether its preview has answered (`data-preview`: `loading`, `ready` or `failed`), for the proofs.
23. **Outcomes: the delivery is the marker, the requested mode is in the line.** The line is the core's summary (`Steer requested · queued: waiting on an interaction`), never re-worded. Each outcome is a word, a drawn icon and a shape (`OutcomeGlyph`, on the [Markers](#markers-five-tiers-told-apart-by-shape) tiers), told apart in greyscale (W9):

    | Word | Icon (shape) |
    | --- | --- |
    | `sent` | Rounded square with a check, primary text (t2) |
    | `queued` | Rounded square with a clock |
    | `failed` | Solid gold diamond (t1) |
    | `unsupported` | Triangle with a slash |
    | `uncertain` | Dashed ring (t5) |
    | `not sent`, `signed out` | Hollow grey ring (t4) |
    | `sending`, `checking`, `in progress` | Live-purple ring with an orbiting dot (t3) |

    "Sent" is the provider accepting the message, never the work being done.
24. **Never say "not sent" without proof** (sheet WS-8). Only Access's `401` or redirect, or OpenWiz's own refusal before the core (its JSON `400`, `403`, `404`, `405`, `408`, `411`, `413`, `415`, `421`, or its `503`), is "not sent". A `200` is the core's report. Everything else, including no answer within 45 s, is **uncertain**.
    - **Every attempt is shown, in order, and nothing is selected or hidden** (Sol rounds 1 to 3). A row per attempt: its requested mode and its outcome, as a word and a shape, in the core's words. Each row changes only on its own answers: a refusal or failure of one attempt never touches another, and a refused retry says "this attempt was refused (…); the earlier send is still uncertain". The rows stay until the draft is sent and a new one starts, or the owner presses Forget it.
    - **The rows are one polite live region** (`role="status"`): a change in any row is announced, and focus never moves.
25. **Unsettled attempts** keep the text fixed (read-only, with a dashed edge). Each unsettled row has its own **Check again** (a lookup of that attempt; it never sends; a text-and-time match stays uncertain), and a row with no answer has **Try again** (the same attempt, the same op id: sent at most once). Under the rows:
    - **Send again** (after an uncertain attempt): the next attempt, saying it may duplicate the earlier send.
    - **Forget it** forgets the draft's attempts, not their numbers: every number used so far, in every mode, answered or not, is retired (and stored) first, so the next send is a new attempt and nothing is ever sent again under a forgotten op id. The text stays.
    - **Focus stays put** (Sol's final round). While a request is out, every control stays where it is, disabled with `aria-disabled` (a natively disabled button loses focus in Chromium), so a control pressed from the keyboard keeps focus while it waits and after. A focused control that goes away (its row settled, or the draft's buttons gave way to its attempts) leaves focus on the message field: a fixed, named place, never the page's body.
    - **One `SendControl` for every send button** (Send, Queue, Steer, Try again, Send again, Send anyway), editable or fixed alike: one gate (the thread listed, this tab's storage working, a usable preview for its mode), with the core's effect line, or "can't send: …", and its own preview's age beside it (each preview's age counts from when that preview arrived). `npm run check` refuses a send from anywhere else (only a `SendControl`'s press, or the keyboard's, which takes the same gate). **One activation, one press:** a held key's auto-repeat never presses a `SendControl` again, and after a press it stays latched until a fresh activation (a new key press or release, a new pointer down, or a click with no key held, as assistive technology clicks). A listing or storage reason also shows above the controls.
26. **Text and op ids.**
    - **Op ids are derived, never minted on events** (Sol round 2). A draft gets one random root id (`web-` and 32 hex digits) with its first text, stored at once. Attempt n in a mode is `<root>-q<n>` or `<root>-s<n>`, and its successor is n + 1. A mode's next number moves past n only when attempt n's own record arrives (an outcome, uncertain, in progress) or a conflicting reuse shows n is taken, and only ever to n + 1, so a lookup or a repeated report never allocates an id, and copied tabs agree. Double clicks, a repeated keyboard send, retries, reloads and a tab duplicated before or after a send all send the same op id, and the core replays. A fresh tab with the same text gets its own root, and the core's in-flight guard covers that. Queued or sent, with nothing else unresolved: the text and the root are gone (the rows stay on screen, in memory, until a new draft starts).
    - **Store, then send.** Nothing is sent unless its attempt is stored first. When this tab's storage is full or off, sending is disabled: "can't send: the message id can't be saved in this tab (browser storage is full or off)".
    - **Store the minimum** (sheet WS-7, WS-10): this tab's `sessionStorage` holds the draft, its root id, the next attempt numbers and its attempts (each with its state and a one-word result), and nothing once the message is queued or sent. Reports stay in memory, so after a reload a row says only how it stood when the page loaded, and Check again reads its record.
27. **Keyboard:** Ctrl+Enter (⌘+Enter) presses the first button; Enter alone is a new line. The message field is labelled "message", and the outcome is a status region.
28. **Text, and the one tray (#16).** The message field is text; files go through the one attachment tray ([below](#the-attachment-tray-16)). A pasted file path is text; a paste of files alone is refused, with words (no clipboard paste; a paste that also carries text pastes only its text); a dropped file is attached.
29. **Refreshes never touch the composer:** never the draft, the focus, the caret or a shown outcome, and never a send, a retry or a check (W11).
30. **State race.** Effects are read before the press, and the thread can change between that read and the dispatch: an idle thread can become busy, a steer can end up queued, someone can pause or resume the queue, the thread can fail or be archived. The composer shows the effects as read, with their age, and then the outcome the provider reported. It never claims an effect it did not observe.

## The launcher (#12)

One new Cloud thread in one existing project: `openwiz new --yes`, through `POST /api/v1/projects/{id}/threads` ([contract](../../../contracts/web-api.v1.md#creating-the-second-write)). The core decides every option, effect, outcome and start stage; the launcher shows them. **Open for Jake (A-10, A-11):** these rules are the builder's first pass; Jake refines them hands-on on the working site.

31. **Placement:** a **New thread** action at the end of each project heading (a quiet caption-size text action, 44 px tall; never on the ungrouped heading); the shell's New thread and ⌘K's New thread in a project open the same launcher. It opens in the panel and the sheet, in place of a session's details, never a page, panel or sheet of its own (U14, checked by `npm run check`). While it is open, its heading's action turns live purple and underlined, as the selected row has its edge. Close returns focus to where the launcher was opened from.
32. **Fixed facts, shown once:** the project, as its heading shows it, and **Cloud**. Nothing to choose there.
33. **Harness, model and effort: three large controls, in that order** (native selects at least 44 px tall, in `type-body`), each showing its choice in words.
    - **Nothing is preselected** (A-10). An empty control says what to do in its own words (`choose a harness`, `choose a harness first`), never only a colour.
    - Only the core's offered options are listed. An unavailable harness is listed with the core's reason, and can't be chosen.
    - **Switching the harness** keeps the model and effort only where the new harness offers them; otherwise they become visibly empty, with a dashed-tag note saying why. Nothing is ever substituted. Options read again (Refresh options, or after a "not offered" refusal) empty a choice they no longer offer, the same way; a failed options read empties nothing.
    - **What is sent is always what is shown** (Sol #157 R2). A chosen value the current options don't list stays in its control, saying why (`· options not read`, `· not offered now`). While an attempt is unresolved its settings are fixed, under "requested for this attempt; fixed while it may have created a thread", whatever the options say now; the options' failure is its own line.
    - The section is **requested settings**, with the options' read time and the core's words: "as reported by CloudRoom; it may answer from a saved copy".
34. **The prompt is the one prompt body** (`PromptBody`, shared with the composer), with the one attachment tray (#16): a dropped file is attached, a paste of files alone refused, with words; a pasted path is text. Ctrl+Enter (⌘+Enter) presses Start thread, once per key press.
35. **Effects before pressing:** "what Start thread does" lists the core's effect lines, word for word, from its preview (`POST …/threads/preview`, which never creates), with "effects read N ago". **No preview, no start:** Start thread is disabled, with "can't start: …" in words, until the three settings, a prompt and the core's ready preview for exactly those settings are there. A create the core would stop says why before pressing.
36. **One button, Start thread** (A-11). The request carries exactly the shown settings and prompt. Op ids are derived, never minted on events: the draft's root (`web-` and 32 hex digits) with its first text, attempt n is `<root>-c<n>`, stored in this tab's `sessionStorage` before the request leaves, with the draft and settings (WS-7, WS-10). Double presses, a held key, Try again, a reload and a copied tab all send the one op id: the core replays (U12).
37. **Created opens the new thread's details** in the same panel or sheet: **created**, in the core's words, and the **start stage** on its own line, with its read time; the **requested** settings beside the **reported configuration**, under the core's label, each reported setting in the core's words, a difference in bold ink. **Show thread** opens its details and composer once the list has it; until then it says it appears at the next refresh.
38. **Outcomes: a word, a drawn icon and a shape**, the composer's set (rule 23): created the checked rounded square, failed the gold diamond, uncertain the dashed ring, refused, not created and signed out the hollow grey ring, creating and checking the orbiting purple ring. The word is the core's status where it gave one. The outcome is one polite live region.
39. **Never "not created" without proof** (WS-8, as A-13 keeps it): only Access's `401` or redirect, or OpenWiz's own refusal before the core. Everything else unanswered is **uncertain**: the prompt, settings and op id stay, fixed, across a reload. After no answer, **Try again** sends the same op id (created at most once). **A refused Try again lowers nothing** (Sol #157 R1): the earlier answer, its word and its shape stay, and the refusal is a line of its own, "this Try again was refused (…); the earlier create is still uncertain". **Refresh status** reads the record (`GET /api/v1/new-threads/{op_id}`) and never creates; observations of threads seen since are shown as observations only. **Start over** is the owner's explicit new attempt (a new op id), and says it may make a second thread. There is no retry (A-3).
40. **Refreshes never touch the launcher:** never the draft, the settings, the focus, the caret or a shown outcome, and never a create. The page's refresh may read the status of an unresolved attempt, or a created thread's start, at most ten times (A-9's bound); then only Refresh status.

## The attachment tray (#16)

Files and images for a send or a new thread's first prompt: uploaded to the owner's controller first (`POST /api/v1/attachments`, [contract](../../../contracts/web-api.v1.md#attachments-revision-004-16)), then sent with the press, by id. The core decides every kind, limit, floor and retention; the tray shows them. **Open for Jake (#16's design loop):** these rules are the builder's first pass; Jake refines them hands-on on the working site.

41. **One tray, in the one prompt body,** under the text field, in the composer and the launcher alike (AW8, checked by `npm run check`). Never a page, panel, sheet or second tray. Each target has its own list (a thread, or a project's launcher): switching never moves an attachment.
42. **Adding:** **Add files** (a 44 px button over a hidden `<input type="file" multiple>`, phone and desktop), or a drop on the prompt body (desktop). A dropped folder is refused, with "Folders aren't supported yet." A drop anywhere else on the page never opens the file. While an attempt may have been sent, the tray is fixed, as the text is, and says so.
43. **Each row:** a thumbnail (24 px in the message dock) or a drawn file icon, the name as plain text (bidi-isolated, cut in the middle so its end and extension show), the size, the readiness, and **Remove** (a 44 px button with a drawn close icon, named "Remove <name>"). **Retry** only on a failed file the browser still has.
44. **Readiness: a word, a drawn icon and a shape**, the composer's outcome shapes (rule 23), never colour alone:

    | State | Word | Icon (shape) |
    | --- | --- | --- |
    | Selected | `on this device` | Hollow grey ring |
    | Uploading | `uploading to your controller` (and a percentage) | Live-purple ring with an orbiting dot |
    | Ready | `ready on your controller` | Rounded square with a check |
    | Failed | `failed`, with the core's words (or "connection lost", "signed out") | Solid gold diamond |
    | Gone (after a reload) | `gone`, with why | Dashed ring |

    Selected never says uploaded; ready only after the server's ready answer.
45. **The gate, mirrored.** Every send or start button is off while any attachment is not ready, saying why ("2 attachments not ready"). The server's gate is the real one. With attachments, **Steer** is replaced by one line: "Steer can't carry attachments: Queue them, or remove them to Steer".
46. **Safe previews.** A thumbnail is the owner's own chosen file, through an object URL, drawn only when its first bytes are PNG, JPEG, GIF or WebP and the server reported it an image. SVG, HTML and everything else get a glyph, never markup. Object URLs are revoked on removal, on hand-over and on unload. No server answer is ever an image (the page's CSP gains `img-src blob:` only).
47. **One line about metadata (B-10)** whenever an image is attached, in a dotted tag: "sent unchanged, including any location data". With files and images both, one meta line: "the agent gets files first, then images".
48. **Uploads start when a file is added**, two at a time, and never again by themselves: Retry is the owner's, and it never sends anything.
49. **After an outcome** the tray empties and says "N attachments handed to CloudRoom" (a created thread's details say the same). Never "delivered" or "read". A failed or uncertain send or create keeps its attachments.
50. **After a reload,** a ready attachment comes back from the server's list, with "preview not available after reload"; anything that wasn't ready is gone, with why, and offers Remove. The tray never claims a file is still in the browser.



## Home: the quiet list (hill-climb A)

Home is one sheet of three hairline-ruled lists: Needs you, Fleets at a glance, Live now. The type hierarchy is deliberate: **Needs you** is the page's first and largest heading, `type-heading` with `tracking-heading` in primary text (Jake's pick, #1451); `type-title` for decision titles, `type-row` for fleet and session titles, and `type-meta` for desktop metadata (`type-caption` on phones). The other two section headings use `type-section` (15 px semibold, 20 px line height) with `tracking-section` in secondary text, shared with Sessions project names. Wide Home uses a minimum 32 px heading-and-coverage band (44 px when its disclosure needs a touch target), with `space-4` before its list; phone Live now keeps a `space-4` gap to its scope line. The smaller gap below and the larger section break above bind each heading to its content. Desktop search aligns with the Home lists' outer edges.

**The page head is a header, not a heading.** The `h1` Home keeps its role and words but is drawn as a quiet label: `type-page-label` with `tracking-section` in secondary ink, vertically centred on Refresh fleets' line (a 32 px row on desktop, 44 px on a phone, the button's target). On desktop it sits `space-12` under the search bar, so search, page name and Refresh fleets read as one header band, and a `space-32` break follows before Needs you; on a phone a `space-16` break follows. Reading and stale lines wrap under the row. **Sessions keeps `type-page`:** it has no Needs you, and its list is the page's answer, so its name stays the heading over the 15 px project names (and keeps the phone's 28 px and desktop's 32 px heading heights).

**Needs you** is a numbered inbox: each decision is one row group with its number in a quiet key cap (tabular), the ticket id in Geist Mono (`ref-id`) before its title, the waiting and source line in secondary ink on desktop, the Answer's effect in tertiary ink, the status shape and word, and the gold Answer. On a wide Home (900 px and wider, no panel open) the status and Answer sit on the right, vertically centred on one line, so the status word shares the Answer label's baseline; on a phone and beside an open panel the status word sits on the title's baseline, and Answer sits under the text at 44 px. A pointer-driven desktop (`pointer: fine`) draws Answer and Refresh fleets 32 px tall; touch keeps 44 px. Home's decision rows carry no gold edge: gold stays on the Answer and the attention shapes. Desktop decision captions use `type-meta`, with no extra row gap: the 20 px lines supply their breathing room and keep the rows compact. Phone decision rows keep their caption type, helper beside Answer and compact vertical insets; Fleets at a glance follows at `space-24`, and Live now at `space-16`, keeping the first screen purposeful.

**Fleets at a glance** rows are compact: on a wide Home (1200 px and wider, no panel open; between 900 and 1199 px they stay stacked so the title keeps its width) one line of title, counts (16 px shapes), a crisp 3 px progress line on a dark `color-progress-track` track, and the merged words. Count and merged-progress digits are medium-weight tabular Geist in `color-fleet-numeral`, slightly brighter than their regular-weight words; ids stay quiet Geist Mono. Desktop counts occupy three aligned columns across fleet rows, with the unknown column empty when absent. On a phone the row keeps two text lines: title and merged progress, then counts, with the thin progress track between them; beside an open panel the progress line also runs under the title. The completed segment uses primary text colour; zero remains an empty track. **Live now** uses the Sessions row; its scope, read and gap captions use secondary ink and `type-meta` on desktop, with the phone caption treatment retained. Home's empty and unread states are one ruled line, never a boxed panel. The Fleets screen keeps its spaced panels.

## Fleets (#128)

Observatory fleet rows use soft panels, the reported “N of M merged” words and a dark native progress track with a crisp primary-text completed segment. Counts retain their StatusMark shapes and words. Needs you stays first, with a gold edge and an enabled gold Answer action; an unavailable Answer keeps its disabled treatment and reason. Fleet details use the same panel system, and the graph uses shared surface, live and attention tokens with solid or dashed state shapes. Phone rows wrap without clipping; coverage remains quiet and visible. Shared token values are unchanged.

51. **Reach fleets through the page's Fleets control.** Needs you stays first in
    the list, then C1's fleet rows. A fleet opens C2's drawn graph and tickets;
    a graph wider than the available content falls back to its state groups.
    All fleets returns to the row, and a builder opens the existing session
    panel or sheet. States retain their words, drawn icons and shapes.
52. **Read the visible view once a minute.** List and detail share one read lane,
    including navigation away and back: the old request answers or reaches
    its bound before another starts. Hidden views start no reads; returning
    starts one. Automatic retries wait at least a minute, with capped backoff.
    Refresh fleets and one downward pull at the top use that same lane;
    repeated refreshes during a read add no requests. A short, horizontal,
    cancelled or multi-touch gesture never refreshes.
53. **A failed read keeps the last snapshot and says why.** Late, disconnected,
    signed out, busy and error keep their word and shape. A snapshot becomes
    visibly stale after 70 seconds without a new answer (a minute plus transit
    margin), measured on both device clocks. Only a successful fresh read can
    say No fleets or Nothing needs you. A refresh never sends a message.

## Decisions (#656)

54. **Own words is a card's field, not a second prompt body.** A grill question's Own words opens one plain text field in its card (the one `<textarea>` outside `PromptBody`, checked by `npm run check`): no tray, no attachments, no draft outside the card. The words go out exactly as typed, through the same send (`Composers.press`), after the card's preview and press like Yes and Simplify, bound to the card's record, question and verified orchestrator target. A changed record or target drops the field and says so. Live, release and publish records ask twice, own words included.

M6 integration: `v9-layout`, `detail-resize`, `design-pass`, `w13-inert`, `u14-u15-launcher` and `c5_answer` keep their assertions and expect “Sessions — close panel”, which includes the phone’s visible “Sessions” label and describes the action.

## Notification settings and status (#2230)

Notifications sit after the cockpit content; a delivery failure never replaces Needs you or ready stock. All sixteen event choices remain visible, including unavailable sources and their reasons. Decisions and recovery escalation default on; delivery and all optional events default off. Without a verified preference read, label the choices as defaults and saved preferences as unknown. Without integration callbacks, controls stay visible and disabled; a stub never offers working enablement.

Status keeps capability, native permission, subscription, source coverage/time and last dispatch distinct. Ready means current prerequisites checked, accepted means dispatch acceptance only, and neither proves phone receipt. An off preference retains pending/uncertain outcomes. Expired authentication, denied access, stale reads and reconnect keep the previous outcome visibly unverified and provide a next step. Never replay a write or resend an uncertain dispatch on refresh/reconnect.

The settings use Observatory type, colour and spacing tokens, one column on phone and two event columns on desktop, labelled controls with at least 44 px targets, and SVG shapes beside status words. Controls remain mounted while saving; outcomes use polite live regions. The explicit enable callback, native permission/subscription, durable operation persistence and real API wiring belong to #2035. Saving category choices never implicitly enables delivery or approves work; disabling cannot retract an effect already submitted.
