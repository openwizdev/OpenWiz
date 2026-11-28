# Image-generation prompts

Mode: built-in image generation. Both calls used the [pinned mobile Market screenshot](https://github.com/openwizdev/WizSite/blob/7eed8be7868df91fad4d24701059b4143910d181/docs/evidence/speed/fonts/market-390x844.png) as the visual reference. Each prompt combines the common text with its viewport direction.

## Common text

Generate a high-fidelity flat browser-content UI design target for OpenWiz's Market page based on the attached public site screenshot as a style reference. Warm near-black #1b1916 canvas, subtle warm charcoal borders, ivory large bold sans headings, warm gray copy, coral primary buttons, no gradients or device frame. Use the existing top nav visual language. Header Market, labeled search Search listings with empty input, Category / All categories and Status / All statuses. Render the same synthetic packet in reading order: (1) Driver, Verified, "Lantern Workspace Synchronization and Receipt Archive", "Receipt: Nov 24, 2026", "0 installs", "Success rate unavailable", "Works on 2 factories", "Install in Wiz". (2) Driver, Unverified, "Paper Relay", "Receipt has expired", "Since Nov 20, 2026", "Receipt unavailable", "Install in Wiz". (3) Skill, Experimental, "Margin Notes", "Receipt unavailable", "Install in Wiz". (4) Service, Listed, "Quiet Queue", "Referral", "Sign up" link. Render a separately labeled example panel below the cards for the alternate zero-results state, retaining search/category/status context with Category Skill, Status Verified, "No listings match your filters", and "Clear filters". Use precise legible text, no ellipses, no invented metrics, no cut edges.

## Phone direction

Portrait 390 CSS px layout, single column with 18 px gutters. Use a very tall narrow canvas near 1:3 aspect ratio so, when raster is scaled to 390 px wide, body copy is at least 14 CSS px and controls are comfortably tappable. Wrap the long title and all details. Place each action below the card metadata, left aligned. Keep search and both filters above the cards and the alternate panel above the bottom margin.

## Desktop direction

Landscape 1440 CSS px layout, centered wide content with nav, horizontal controls and a two-column card grid read across each row, then alternate state.
