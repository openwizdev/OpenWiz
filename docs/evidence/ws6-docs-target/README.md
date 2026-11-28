# Docs article targets

[Phone (390 CSS px)](target-390.png) · [Desktop (1440 CSS px)](target-1440.png) · [Image generation prompts](prompt.md)

The public WizSite styles at commit `7eed8be7868df91fad4d24701059b4143910d181` are the pinned taste source. Use the site's warm charcoal canvas, cream text, coral link underlines, quiet dividers, and Geist and Geist Mono. Reuse the site header, link treatments, focus styles and responsive gutters. [Site styles](https://github.com/openwizdev/WizSite/blob/7eed8be7868df91fad4d24701059b4143910d181/site.css) · [Font definitions](https://github.com/openwizdev/WizSite/blob/7eed8be7868df91fad4d24701059b4143910d181/tokens.css)

## Layout and synthetic article

At 1440 CSS px, center the site shell and place the search field and page list in a left rail beside the reading column. At 390 CSS px, stack the search field, collapsed **Pages** disclosure and article in one column. Opening **Pages** shows the same list in document flow. In both layouts, list **Getting started**, **Preview a sample** and **Output reference** and identify the current page visually and with `aria-current="page"`.

Use the same article at both widths. The sample command is invented for this design.

| Role | Copy |
| --- | --- |
| H1 | Preview a sample |
| Introduction | Use a sample report to inspect the preview output. |
| H2 | Create a preview |
| Paragraph | Run the sample preview. |
| Command block | `sample preview` |
| H3 under H2 | Check the output |
| Paragraph | Look for the report in `fixtures/synthetic/reports/preview/`. |
| Internal link | Output reference, linking to the corresponding synthetic docs page |

## Search states

- **Blank query** shows the page list in its default state. “Search docs” is the field's accessible name and placeholder. Clearing the query restores the page list.
- **Query with matches** shows linked page titles in the search area, with a matching excerpt where useful. On phone, show results directly under the input so they are available while the page list is collapsed. The current article stays visible below the controls.
- **Query with no matches** shows “No pages match” below the field, followed by “Try a different search or clear the field.” Keep the query editable and the page list available. Announce result counts and the empty state politely to assistive technology.
- **Search unavailable** leaves the article and page links usable. If search requires JavaScript, tell visitors with JavaScript disabled that they can browse the page list.

## Code containment

Let inline paths wrap at slash boundaries and allow a break within a segment when it would otherwise overflow. Keep command whitespace intact. When a command line is wider than its block, allow horizontal scrolling inside that block only. Make the overflow discoverable and reachable by keyboard. Allow the reading column and its children to shrink so the document itself stays within the viewport.

## Image review

Both ImageGen targets were inspected for readable H1, H2 and nested H3 hierarchy, visible search and page navigation, link treatment and containment of the code panel and path. Both use the same synthetic article. The phone target moves the path to its own line and omits the sentence-ending period. The desktop target includes the period and uses an active underline on the Docs nav item. The phone target omits that underline. Use the copy above and identify Docs as active at both widths. The generated wordmark, type sizes and spacing are approximate. The PNGs were resized proportionally to their target widths.

These images show the blank search state. #3519 owns browser layout and overflow checks for W7, and #3807 owns browser checks for page navigation and search. The parent spec tracks the W11 live check after implementation.

## Package proof

Run `python3 -I docs/evidence/ws6-docs-target/test_target.py` from the OpenWiz root. Before creating the brief, prompt and images, the two tests reported the missing brief and both missing targets. With the package in place, the same tests verify the pinned reference, shared copy, documented states, target links and PNG widths. The image review above records the visual checks.
