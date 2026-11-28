# UI kits for openwiz.dev and WizBar

Read on 2026-11-28 for RX6. An adopt verdict covers the specific code named below. Listing-only means a public design reference with zero code copied and no WizMarket listing proposed. The home specs are openwiz.dev (#3513) and WizBar (#3467). Browser behaviour, accessibility and fit in the OpenWiz surfaces are unverified until the proposed checks run. [RX6](https://github.com/openwizdev/OpenWiz/issues/3709) · [Research spec](https://github.com/openwizdev/OpenWiz/issues/3703) · [openwiz.dev spec](https://github.com/openwizdev/OpenWiz/issues/3513) · [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

## HorizonX

The public code is in `Mdx2025/horizonx-ui` at `5cce4d30514c0eb1a571e9236f2da6cc0b1d8d09`. Its licence is SPDX `MIT` and requires keeping the copyright and permission notices with copies or substantial portions. The site's premium App UI Kit Collection is sold under its own commercial terms. The MIT verdict covers the public badge file. Rights to redistribute premium source or the CDN image used in the card example under MIT are unverified. [Repository](https://github.com/Mdx2025/horizonx-ui) · [Commit](https://github.com/Mdx2025/horizonx-ui/commit/5cce4d30514c0eb1a571e9236f2da6cc0b1d8d09) · [Pinned licence](https://github.com/Mdx2025/horizonx-ui/blob/5cce4d30514c0eb1a571e9236f2da6cc0b1d8d09/LICENSE) · [Premium kit](https://horizonx.so/explore/app-ui-kit-collection) · [Terms](https://horizonx.so/terms) · [Card source](https://github.com/Mdx2025/horizonx-ui/blob/5cce4d30514c0eb1a571e9236f2da6cc0b1d8d09/components/card.html)

The public Badge works as a small text label with a faint status tint. The dot variant keeps the word next to the dot, so the status still reads without colour. The premium Agent Monitor advertises an action timeline and checkpoint restore, two examples of putting operator tasks inside a dashboard. For the static market, the small badge is the useful piece because the listing's name, receipts and reason still have room to read. [Badge source](https://github.com/Mdx2025/horizonx-ui/blob/5cce4d30514c0eb1a571e9236f2da6cc0b1d8d09/components/badge.html) · [Agent Monitor overview](https://horizonx.so/explore/app-ui-kit-collection) · [Market spec](https://github.com/openwizdev/OpenWiz/issues/3513)

### Proposed follow-up ticket

#### Title

Use a compact status label on the openwiz.dev market

#### Parent

[openwiz.dev #3513, WS2 and WS3](https://github.com/openwizdev/OpenWiz/issues/3513)

#### What to build

In WizSite, adapt the pinned `components/badge.html` text-and-dot markup for the status on the market index and listing pages. Translate the styles to existing site CSS tokens, keep the status as text, treat the dot as decorative, and carry the upstream MIT notice with the adaptation. Render the label from the saved index with the existing static page generation. [Badge source](https://github.com/Mdx2025/horizonx-ui/blob/5cce4d30514c0eb1a571e9236f2da6cc0b1d8d09/components/badge.html) · [Pinned licence](https://github.com/Mdx2025/horizonx-ui/blob/5cce4d30514c0eb1a571e9236f2da6cc0b1d8d09/LICENSE) · [Market spec](https://github.com/openwizdev/OpenWiz/issues/3513)

#### Acceptance criteria

Each status is readable without colour or JavaScript, and the `unverified` reason and date remain visible. The label uses the site's contrast checks and fits at 390 px. It uses local CSS and adds zero dependencies or external assets. [Market spec](https://github.com/openwizdev/OpenWiz/issues/3513)

#### Proof

Build and test both page types with synthetic listings covering the supported statuses. Inspect the render at 390 and 1440 px, with JavaScript disabled and using the site's contrast check. [Market spec](https://github.com/openwizdev/OpenWiz/issues/3513)

**Verdict** — adopt. The public MIT badge is small enough to carry into the existing static renderer and keeps status visible in words. [Badge source](https://github.com/Mdx2025/horizonx-ui/blob/5cce4d30514c0eb1a571e9236f2da6cc0b1d8d09/components/badge.html) · [Pinned licence](https://github.com/Mdx2025/horizonx-ui/blob/5cce4d30514c0eb1a571e9236f2da6cc0b1d8d09/LICENSE) · [Market spec](https://github.com/openwizdev/OpenWiz/issues/3513)

## beUI

The public repository is `starc007/ui-components` at `521c9d6eae5d9e958b6d91cbeafe61514fe25c55`, with SPDX `MIT` and notice retention. The site presents a React catalogue and a separate Pro offer. Pro reuse rights are unverified here. [Site](https://beui.dev/) · [Repository](https://github.com/starc007/ui-components) · [Commit](https://github.com/starc007/ui-components/commit/521c9d6eae5d9e958b6d91cbeafe61514fe25c55) · [Pinned licence](https://github.com/starc007/ui-components/blob/521c9d6eae5d9e958b6d91cbeafe61514fe25c55/LICENSE)

The Animated Toast Stack opens on focus as well as hover or tap and exposes a pause hook so a notice can stay up while someone reads it. The motion rules preserve opacity and colour cues under reduced motion and gate decorative hover effects on hover capability. For the market's copy action, the useful detail is keeping feedback by the control long enough to read. The stack imports `motion/react`, and the site only needs feedback on one button. [Toast source](https://github.com/starc007/ui-components/blob/521c9d6eae5d9e958b6d91cbeafe61514fe25c55/components/motion/animated-toast-stack.tsx) · [Countdown hook](https://github.com/starc007/ui-components/blob/521c9d6eae5d9e958b6d91cbeafe61514fe25c55/components/motion/animated-toast-stack/use-animated-toast-stack.ts) · [Motion rules](https://github.com/starc007/ui-components/blob/521c9d6eae5d9e958b6d91cbeafe61514fe25c55/CONTRIBUTING.md) · [Market spec](https://github.com/openwizdev/OpenWiz/issues/3513)

### Proposed follow-up ticket

#### Title

Make Install in Wiz clipboard feedback readable at the button

#### Parent

[openwiz.dev #3513, WS2 and WS3](https://github.com/openwizdev/OpenWiz/issues/3513)

#### What to build

Write original inline feedback at the market and listing pages' Install in Wiz control. Show the paste instruction after a successful copy and a selectable install line if the clipboard rejects the copy. Keep feedback visible under reduced motion and preserve keyboard focus. Use beUI's reading-time and reduced-motion behaviours as design references. [Motion rules](https://github.com/starc007/ui-components/blob/521c9d6eae5d9e958b6d91cbeafe61514fe25c55/CONTRIBUTING.md) · [Market spec](https://github.com/openwizdev/OpenWiz/issues/3513)

#### Acceptance criteria

Success and failure are announced in text at the focused control. Repeated use still copies the exact install line. Add zero beUI code or runtime dependencies. [Market spec](https://github.com/openwizdev/OpenWiz/issues/3513)

#### Proof

Exercise clipboard success and rejection with a synthetic listing and verify the exact clipboard contents, visible status, keyboard focus and reduced-motion states. [Market spec](https://github.com/openwizdev/OpenWiz/issues/3513)

**Verdict** — listing-only. Focus-aware feedback is a useful reference for one static-site control. The React stack carries behaviour and dependencies beyond that control. [Toast source](https://github.com/starc007/ui-components/blob/521c9d6eae5d9e958b6d91cbeafe61514fe25c55/components/motion/animated-toast-stack.tsx) · [Market spec](https://github.com/openwizdev/OpenWiz/issues/3513)

## BoardUI

The public repository is `BoardUI/boardui` at `c87984b6bb7cb691a1cd560e9ae2a75a7ffb6c89`, with SPDX `MIT` and notice retention. The repository distinguishes its public components from the Pro catalogue. Pro reuse rights are unverified here. [Site](https://www.boardui.com/) · [Repository](https://github.com/BoardUI/boardui) · [Commit](https://github.com/BoardUI/boardui/commit/c87984b6bb7cb691a1cd560e9ae2a75a7ffb6c89) · [Pinned licence](https://github.com/BoardUI/boardui/blob/c87984b6bb7cb691a1cd560e9ae2a75a7ffb6c89/LICENSE) · [Catalogue at the pin](https://github.com/BoardUI/boardui/blob/c87984b6bb7cb691a1cd560e9ae2a75a7ffb6c89/README.md)

Notification Center groups events, shows category counts beside the tabs and gives each row a timestamp and status. That puts the useful details in the row before an owner opens anything. The implementation also includes React-specific controls, internal read state and action callbacks, which would duplicate parts of the shared WizBar model if brought over as a component. [Notification Center source](https://github.com/BoardUI/boardui/blob/c87984b6bb7cb691a1cd560e9ae2a75a7ffb6c89/components/application/notification-center/notification-center.tsx) · [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

### Proposed follow-up ticket

#### Title

Make WizBar's Needs you list easier to scan by time

#### Parent

[WizBar #3467, shared board core and WB1](https://github.com/openwizdev/OpenWiz/issues/3467)

#### What to build

Use BoardUI's grouped notification rows as a visual reference. In WizPlugins' shared board view, put an available event timestamp beside the existing status text and show a date group heading when the view model supplies a usable timestamp. Preserve the feed's ordering and existing action rules, and render untimed cards with the existing missing-data treatment. [Notification Center source](https://github.com/BoardUI/boardui/blob/c87984b6bb7cb691a1cd560e9ae2a75a7ffb6c89/components/application/notification-center/notification-center.tsx) · [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

#### Acceptance criteria

Across surfaces, matching fixtures still give the same card IDs, order, counts and labels. Dates aid scanning at phone and panel widths. Add zero BoardUI code or notification state. [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

#### Proof

Run WB1 conformance with timed and untimed synthetic items, then compare the rendered rows at 390 and 1440 px. [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

**Verdict** — listing-only. Study the timestamp and grouping hierarchy and implement it from WizBar's own view data. [Notification Center source](https://github.com/BoardUI/boardui/blob/c87984b6bb7cb691a1cd560e9ae2a75a7ffb6c89/components/application/notification-center/notification-center.tsx) · [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

## Originkit

The public repository found is the Vellum plugin `vellum-ai/originkit` at `d27526a2e2e728fd2c0c13b28021ade6908211a7`, with SPDX `MIT` for the plugin. Its README describes a bundled metadata index and component source fetched on demand with an Originkit key. A separate public component-source repository, commit and SPDX identifier for the gallery code are unverified. Originkit's account documentation says its redistribution restriction on components and templates applies to every plan. [Repository](https://github.com/vellum-ai/originkit) · [Commit](https://github.com/vellum-ai/originkit/commit/d27526a2e2e728fd2c0c13b28021ade6908211a7) · [Pinned plugin licence](https://github.com/vellum-ai/originkit/blob/d27526a2e2e728fd2c0c13b28021ade6908211a7/LICENSE) · [Plugin README at the pin](https://github.com/vellum-ai/originkit/blob/d27526a2e2e728fd2c0c13b28021ade6908211a7/README.md) · [Account and billing](https://www.originkit.dev/docs/account-billing) · [Licensing policy](https://www.originkit.dev/docs/licensing)

Single Glass Keyboard gives a keycap a hollow WebGL glass body and coloured fringes. Coverflow Gallery tilts neighbouring slides in perspective around the current slide. Both establish a visual motif through a single object or interaction. The specified install, search, and Needs you flows have little use for 3D keycaps or image browsing. [Single Glass Keyboard](https://www.originkit.dev/components/single-glass-keyboard) · [Coverflow Gallery](https://www.originkit.dev/components/coverflowgallery) · [openwiz.dev spec](https://github.com/openwizdev/OpenWiz/issues/3513) · [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

**Verdict** — no. The gallery has unverified component-source licensing, and the examples fit decorative or gallery use. [Plugin README at the pin](https://github.com/vellum-ai/originkit/blob/d27526a2e2e728fd2c0c13b28021ade6908211a7/README.md) · [Licensing policy](https://www.originkit.dev/docs/licensing) · [openwiz.dev spec](https://github.com/openwizdev/OpenWiz/issues/3513) · [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

## Bencho

The public repository is `cabralorenzo/bencho` at `2702ce8f983519794a9268bb61abd8c282b66fa7`, with SPDX `MIT` for the free blocks reviewed. The licence carries the usual notice requirement, excludes the name, goat mark and site photos, and points to separate third-party notices. The site publishes separate terms for Pro. [About](https://bencho.dev/about) · [Repository](https://github.com/cabralorenzo/bencho) · [Commit](https://github.com/cabralorenzo/bencho/commit/2702ce8f983519794a9268bb61abd8c282b66fa7) · [Pinned licence](https://github.com/cabralorenzo/bencho/blob/2702ce8f983519794a9268bb61abd8c282b66fa7/LICENSE) · [Third-party notices](https://github.com/cabralorenzo/bencho/blob/2702ce8f983519794a9268bb61abd8c282b66fa7/THIRD_PARTY.md) · [Site licence](https://bencho.dev/licence)

Step Player fills each step before moving to the next. Context Meter highlights an individual segment in a stacked bar or dot field. Both make a progression or part-to-whole relationship legible. The Step Player pattern could inform the order of dated proof on a market listing, although a timer would imply progress the saved receipts do not measure. [Step Player](https://github.com/cabralorenzo/bencho/blob/2702ce8f983519794a9268bb61abd8c282b66fa7/blocks/step-player/README.md) · [Context Meter](https://github.com/cabralorenzo/bencho/blob/2702ce8f983519794a9268bb61abd8c282b66fa7/blocks/context-meter/README.md) · [Listing spec](https://github.com/openwizdev/OpenWiz/issues/3513)

### Proposed follow-up ticket

#### Title

Make dated market receipts scan as a sequence

#### Parent

[openwiz.dev #3513, WS3](https://github.com/openwizdev/OpenWiz/issues/3513)

#### What to build

Use Step Player's progression as a visual reference for an original, static, ordered evidence list in the WizSite listing template. Show each receipt's date and link from the saved index. Use explicit labels for dates and preserve the listing's actual status and receipt links. [Step Player](https://github.com/cabralorenzo/bencho/blob/2702ce8f983519794a9268bb61abd8c282b66fa7/blocks/step-player/README.md) · [Listing spec](https://github.com/openwizdev/OpenWiz/issues/3513)

#### Acceptance criteria

A reader can distinguish zero, one and several saved receipts, including with JavaScript off. The list shows only real evidence dates and links from the saved index. Add zero Bencho source, playback, or inferred completion states. [Listing spec](https://github.com/openwizdev/OpenWiz/issues/3513)

#### Proof

Build fixture listing pages with zero, one and several receipts. Check date and link text and compare desktop and phone renders at 1440 and 390 px. [Listing spec](https://github.com/openwizdev/OpenWiz/issues/3513)

**Verdict** — listing-only. Borrow the visual idea of sequencing for dated receipts. The timed React block models a different kind of progress. [Step Player](https://github.com/cabralorenzo/bencho/blob/2702ce8f983519794a9268bb61abd8c282b66fa7/blocks/step-player/README.md) · [Listing spec](https://github.com/openwizdev/OpenWiz/issues/3513)

## Transitions

The public repository is `Jakubantalik/transitions.dev` at `15df2cefb93a839cbaaa08968a144e908cd0e3af`. The pinned file gives the recipes and skills a custom terms grant that allows use in end products and restricts redistribution of the library. SPDX identifier `LicenseRef-Transitions-dev` is a local reference for that custom text. A standard SPDX identifier for the recipes is unverified. The same file applies SPDX `MIT` to specified tooling directories and reserves rights in the site design and branding. [Site](https://transitions.dev/) · [Repository](https://github.com/Jakubantalik/transitions.dev) · [Commit](https://github.com/Jakubantalik/transitions.dev/commit/15df2cefb93a839cbaaa08968a144e908cd0e3af) · [Pinned licence](https://github.com/Jakubantalik/transitions.dev/blob/15df2cefb93a839cbaaa08968a144e908cd0e3af/LICENSE) · [Site terms](https://transitions.dev/terms.html)

Panel Reveal uses a short vertical slide, fade and blur for content that arrives inside an existing surface. Modal Open/Close scales its layer and exits faster than it enters. Both include a reduced-motion treatment. A short state change could help WizBar readers keep their place in an expanded card, while leaving the status itself legible without motion. [Pinned panel recipe](https://github.com/Jakubantalik/transitions.dev/blob/15df2cefb93a839cbaaa08968a144e908cd0e3af/cli/free/panel-reveal.md) · [Pinned modal example](https://github.com/Jakubantalik/transitions.dev/blob/15df2cefb93a839cbaaa08968a144e908cd0e3af/transitions/modal-open-close/index.html) · [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

### Proposed follow-up ticket

#### Title

Keep context when a WizBar card opens

#### Parent

[WizBar #3467, shared board core and WB2/WB3](https://github.com/openwizdev/OpenWiz/issues/3467)

#### What to build

Write an original CSS opacity transition for a card's detail disclosure in WizPlugins' shared HTML board view, using the Transitions demo as a design reference. Use native disclosure semantics and the board theme. Keep the summary trigger in place and use an immediate state change when reduced motion is requested. [Panel demo](https://transitions.dev/transitions/panel-reveal/) · [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

#### Acceptance criteria

The summary works by keyboard, focus stays usable, and the same detail content is available with or without motion. Add zero upstream code, agent tooling, or runtime dependencies. [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

#### Proof

Check keyboard open and close, focus, and both motion preferences in the browser and panel using synthetic board cards. Run WB1 conformance for their unchanged data. [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

**Verdict** — listing-only. The disclosure behaviour is worth studying. The recipes' custom licence falls outside the research spec's permissive list. [Pinned licence](https://github.com/Jakubantalik/transitions.dev/blob/15df2cefb93a839cbaaa08968a144e908cd0e3af/LICENSE) · [Research spec](https://github.com/openwizdev/OpenWiz/issues/3703) · [Panel demo](https://transitions.dev/transitions/panel-reveal/)

## affectUI

The public repository is `flohoeller/affectui` at `d9b627b3a979321423af2aa4be1fb6b9f34dc3b4`, with SPDX `MIT` and notice retention. Decision Inbox and Tool Call Card have free source in the pinned tree. Pro reuse rights are unverified here. [Site](https://www.affectui.com/) · [Repository](https://github.com/flohoeller/affectui) · [Commit](https://github.com/flohoeller/affectui/commit/d9b627b3a979321423af2aa4be1fb6b9f34dc3b4) · [Pinned licence](https://github.com/flohoeller/affectui/blob/d9b627b3a979321423af2aa4be1fb6b9f34dc3b4/LICENSE) · [Catalogue at the pin](https://github.com/flohoeller/affectui/blob/d9b627b3a979321423af2aa4be1fb6b9f34dc3b4/README.md)

Decision Inbox uses one count above tightly spaced rows with a title and a line of context. Tool Call Card gives the call one scannable line with status and elapsed time, and keeps the arguments and result behind a disclosure. Both put the operator's next decision up front. The Inbox's count and row styling fit Needs you. Its in-component answering and dismissal flow would give a read-only surface the wrong controls. [Decision Inbox source](https://github.com/flohoeller/affectui/blob/d9b627b3a979321423af2aa4be1fb6b9f34dc3b4/components/decision-inbox-clean.tsx) · [Tool Call Card source](https://github.com/flohoeller/affectui/blob/d9b627b3a979321423af2aa4be1fb6b9f34dc3b4/components/tool-call-card-clean.tsx) · [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

### Proposed follow-up ticket

#### Title

Give WizBar's Needs you count and rows a clearer hierarchy

#### Parent

[WizBar #3467, shared board core and WB1](https://github.com/openwizdev/OpenWiz/issues/3467)

#### What to build

In WizPlugins' shared board view, adapt the pinned Decision Inbox CSS for the count header, thin row separators, title and supporting text. Apply the styles to existing board markup and theme tokens and carry the MIT notice with the adapted CSS. Use board-core data for every count and label and retain the board's existing action handling and read-only surfaces' tell Wiz affordance. [Decision Inbox source](https://github.com/flohoeller/affectui/blob/d9b627b3a979321423af2aa4be1fb6b9f34dc3b4/components/decision-inbox-clean.tsx) · [Pinned licence](https://github.com/flohoeller/affectui/blob/d9b627b3a979321423af2aa4be1fb6b9f34dc3b4/LICENSE) · [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

#### Acceptance criteria

The count and all rows stay legible with long titles at 390 px. Empty and populated views match board-core results on every surface. The adaptation adds no React component, new runtime dependency or write action. [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

#### Proof

Run WB1 conformance on empty, single and multi-card fixtures and inspect dark renders at 390 and 1440 px, including a long title and an existing tell Wiz row. [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

**Verdict** — adopt. The pinned MIT Inbox stylesheet offers a small presentation change that can use the existing board data and actions. [Decision Inbox source](https://github.com/flohoeller/affectui/blob/d9b627b3a979321423af2aa4be1fb6b9f34dc3b4/components/decision-inbox-clean.tsx) · [Pinned licence](https://github.com/flohoeller/affectui/blob/d9b627b3a979321423af2aa4be1fb6b9f34dc3b4/LICENSE) · [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)

## What the redesign should take

- On openwiz.dev, keep each status alongside its reason, keep copy feedback by the button, and lay dated receipts out in a sequence. [HorizonX badge](https://github.com/Mdx2025/horizonx-ui/blob/5cce4d30514c0eb1a571e9236f2da6cc0b1d8d09/components/badge.html) · [beUI Toast Stack](https://github.com/starc007/ui-components/blob/521c9d6eae5d9e958b6d91cbeafe61514fe25c55/components/motion/animated-toast-stack.tsx) · [Bencho Step Player](https://github.com/cabralorenzo/bencho/blob/2702ce8f983519794a9268bb61abd8c282b66fa7/blocks/step-player/README.md) · [openwiz.dev spec](https://github.com/openwizdev/OpenWiz/issues/3513)
- In WizBar, make the Needs you count and row titles easy to scan, show available time context, and keep disclosure motion tied to what the owner opened. [affectUI Decision Inbox](https://github.com/flohoeller/affectui/blob/d9b627b3a979321423af2aa4be1fb6b9f34dc3b4/components/decision-inbox-clean.tsx) · [BoardUI Notification Center](https://github.com/BoardUI/boardui/blob/c87984b6bb7cb691a1cd560e9ae2a75a7ffb6c89/components/application/notification-center/notification-center.tsx) · [Transitions Panel Reveal](https://transitions.dev/transitions/panel-reveal/) · [WizBar spec](https://github.com/openwizdev/OpenWiz/issues/3467)
