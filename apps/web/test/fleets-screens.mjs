// Renders DEMO-labelled screenshots of the fleets list (#125) on synthetic
// fleets, each state at 390 and 1440 px, for review:
// `node test/fleets-screens.mjs [out-dir]`. Not a proof. Synthetic data only.
// The list in a page like the app's (test/support/fleets-page.ts): it isn't
// wired into the page yet (C4 does that).

import { mkdirSync } from 'node:fs';

import { chromium } from 'playwright-core';

import { readFleets } from '../src/fleets.ts';
import { fleetsChecksFailed, fleetsEmpty, fleetsExample, fleetsHostile, fleetsListFailed, fleetsLong, fleetsPartial, SNAPSHOT_AT } from './support/fleet-fixtures.ts';
import { DESKTOP, fleetsPage, PHONE } from './support/fleets-page.ts';
import { RESULTS_DIR } from './support/paths.mjs';

process.env.TZ = 'UTC';
const dir = process.argv[2] ?? `${RESULTS_DIR}/fleets-screens`;
mkdirSync(dir, { recursive: true });

const STATES = [
  { name: 'complete', text: fleetsExample() },
  { name: 'complete-greyscale', text: fleetsExample(), grey: true },
  { name: 'checks-failed', text: fleetsChecksFailed() },
  { name: 'partial-gaps-open', text: fleetsPartial(), gapsOpen: true },
  { name: 'list-failed', text: fleetsListFailed() },
  { name: 'empty', text: fleetsEmpty() },
  { name: 'empty-not-fresh', text: fleetsEmpty(), fresh: false },
  { name: 'long-titles', text: fleetsLong() },
  { name: 'hostile-titles', text: fleetsHostile() },
];

/** A DEMO ribbon, added outside the page's CSP, so no screenshot passes for real data. */
const demo = (page) =>
  page.evaluate(() => {
    const r = document.createElement('div');
    r.textContent = 'DEMO · SYNTHETIC DATA · NOTHING IS LIVE';
    Object.assign(r.style, {
      position: 'fixed', left: '0', right: '0', bottom: '0', zIndex: '100', padding: '4px 16px', textAlign: 'center',
      background: '#552583', color: '#e8eaed', font: '600 10px/16px GeistMono, monospace', letterSpacing: '.08em',
    });
    document.body.append(r);
  });

const browser = await chromium.launch({ executablePath: process.env.OPENWIZ_CHROMIUM ?? '/usr/bin/chromium' });
let made = 0;
try {
  for (const s of STATES) {
    const r = readFleets(s.text);
    if (!r.ok) throw new Error(`${s.name}: refused at ${r.refusal.at}: ${r.refusal.why}`);
    for (const viewport of [PHONE, DESKTOP]) {
      const p = await fleetsPage(browser, viewport, {
        envelope: r.envelope,
        now: new Date(SNAPSHOT_AT + 60_000),
        fresh: s.fresh ?? true,
        gapsOpen: s.gapsOpen ?? false,
        onToggleGaps: () => {},
        onOpen: () => {},
      });
      try {
        if (s.grey) await p.page.evaluate(() => (document.documentElement.style.filter = 'grayscale(1)'));
        await demo(p.page);
        await p.page.screenshot({ path: `${dir}/${s.name}-${viewport.width}.png`, fullPage: true });
        made++;
      } finally {
        await p.close();
      }
    }
  }
} finally {
  await browser.close();
}
if (made !== STATES.length * 2) throw new Error(`made ${made} of ${STATES.length * 2} renders`);
console.log(`fleets-screens: ${made} renders in ${dir}`);
