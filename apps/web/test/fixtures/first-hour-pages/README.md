# First-hour component states (#2223)

Synthetic inputs for `test/browser/first-hour-pages.test.mjs`'s component-state
section. `states.mjs` holds, for each first-hour state, the text the existing
reads would answer (`openwiz.setup.v1`, `openwiz.decisions.v1`,
`openwiz.fleet.v1`), any decision receipts the tab holds, and the literal words,
shapes and phrases the guidance must (and must not) show. The test parses every
text through the app's own readers (`readSetup`, `readDecisionsText`,
`readFleet`), so a fixture the product would refuse fails the test.

Every repository, number, thread id, commit and time is invented. These prove
presentation on fixtures only: not an installed page, a live account, a usable
login or a real merge. The states follow the reviewed targets in the private
`first-hour-states/` design folder.

- `red.txt`: the failing-first run, before the component existed.
