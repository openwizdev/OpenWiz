# Market search design targets

[Phone at 390 CSS px](phone.png) · [Desktop at 1440 CSS px](desktop.png) · [Generation prompts](prompt.md)

The public [Market screenshot](https://github.com/openwizdev/WizSite/blob/7eed8be7868df91fad4d24701059b4143910d181/docs/evidence/speed/fonts/market-390x844.png) and [site stylesheet](https://github.com/openwizdev/WizSite/blob/7eed8be7868df91fad4d24701059b4143910d181/site.css) pin the site's visual language. Use the existing navigation, warm near-black background, ivory typography, muted borders, coral primary action and visibly underlined text links. Keep status readable as text in every state.

## Shared synthetic packet

Every name, date and metric below is fixture data. The order within Driver comes from fixture rank, with Lantern first. Read left to right across desktop rows and top to bottom on the phone.

| Category | Listing and ID | Status | Receipt and metrics | Action |
| --- | --- | --- | --- | --- |
| Driver | Lantern Workspace Synchronization and Receipt Archive (`lantern-workspace`) | Verified | Receipt: Nov 24, 2026. 0 installs. Success rate unavailable. Works on 2 factories. | Install in Wiz |
| Driver | Paper Relay (`paper-relay`) | Unverified. Receipt has expired. Since Nov 20, 2026. | Receipt unavailable. Counts and rate absent. | Install in Wiz |
| Skill | Margin Notes (`margin-notes`) | Experimental | Receipt unavailable. Counts and rate absent. | Install in Wiz |
| Service (illustrative link-only category) | Quiet Queue (`quiet-queue`) | Listed. Referral. | Receipt, counts and rate absent. | [Sign up](https://example.com/quiet-queue) |

## States for implementation

- Default shows all listings. Reading order is site navigation, Market, Search listings, Category, Status, then results. At 390 px, the long title wraps and each card fits the viewport. At 1440 px, the controls align above a two-column grid.
- Text search uses name, summary and tags. A nonempty example is a query for Paper Relay. Category Driver returns both drivers in fixture rank order. Status Experimental returns Margin Notes.
- Category Skill plus Status Verified yields zero matches. Keep the selected filters visible and replace the results with “No listings match your filters” and a “Clear filters” link. The bottom panel in each image illustrates this alternate state.
- Category and status choices are links to built filter pages, including when JavaScript is off. With JavaScript off, explain that search requires JavaScript.
- “Install in Wiz” copies the exact line for its card, for example `Wiz, install lantern-workspace from WizMarket`, and shows “Paste this into your Wiz chat”. Quiet Queue has a sign-up link and a visible Referral label.
- Render absent metrics as unavailable wherever surfaced. Preserve a reported zero as “0 installs”; it gives no basis for a success percentage.

## Review

Both images were generated with the built-in image tool and resized proportionally to the target widths. The targets are for owner review in [#3515](https://github.com/openwizdev/OpenWiz/issues/3515) and [#3806](https://github.com/openwizdev/OpenWiz/issues/3806). Those tickets own browser behavior and viewport screenshots.

The visual review checked filter and action labels, all listing names, the real zero, missing receipt copy, the unverified reason and date, the referral link, reading order and clipping. Use the packet and states above for implementation details and exact copy.

### Known image differences

- Both images carry an introduction adapted from the current Market. The phone also adds an explanatory sentence in the alternate panel. Both rasters say “Sign In” where the public reference says “Sign in”. Their generated navigation icons and badge colors approximate the existing style.
- Both rasters show select-like arrows on the filters and omit clipboard confirmation and JavaScript-off copy. Implement the link and state behavior described above.
