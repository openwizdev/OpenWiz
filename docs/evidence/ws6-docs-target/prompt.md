# Image generation prompts

The shared prompt was followed by the viewport direction below in each image generation call.

## Shared prompt

High-fidelity static OpenWiz docs article UI design target. Browser viewport edge to edge, no device frame. Match public openwiz.dev website design (warm near-black #1b1916, cream #f3eee8, muted warm beige #c8c0b8, coral #ff8f80 underlined links and selected accents, quiet #3a342e dividers, #221f1b inset panels, Geist sans and Geist Mono, rounded 8px controls, no gradients, no illustration). Header 'OpenWiz' small left, 'Docs' and 'Market' right. Search field with magnifier and placeholder 'Search docs'. Navigation has heading 'Pages', links 'Getting started', 'Preview a sample' selected, and 'Output reference'. The article starts with H1 'Preview a sample', paragraph 'Use a sample report to inspect the preview output.' Then H2 'Create a preview', text 'Run the sample preview.', a one-line inset code block displaying exactly 'sample preview', then H3 'Check the output', text 'Look for the report in' followed by inline monospace 'fixtures/synthetic/reports/preview/' which is allowed to wrap at slashes, then underlined coral link 'Output reference'. Give each heading its own visible scale and position. Keep article, path and command fully inside the reading column. Only these words appear, no annotations or decorations. Show the default blank query. Empty search state specified in the brief uses 'No pages match' and is not drawn.

## 390 CSS px

Portrait screenshot composed for a 390 CSS px wide viewport. Use 18px outer gutters. Stack header, full-width search field, collapsed Pages disclosure control with down chevron (hide its links), then article. Use 32/23/19px heading hierarchy and 16px body. Show all content including link. Keep compact readable spacing.

## 1440 CSS px

Wide landscape screenshot composed for a 1440 CSS px viewport. Center a 1240px shell. Search and Pages list in 240px left sidebar with vertical divider and article in a 680px reading column to its right. Keep generous space at right. Use 48/30/22px headings and 17px body. Show all content including link.
