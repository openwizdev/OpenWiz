// EP4's screens (#656): Decisions against the design target
// at 390 and
// 1440 CSS px, in the target's state: L4 untouched, L5 in own words, #2900 at
// its second confirmation, #2790 sent. Layout, touch targets, axe, CSP and
// gold-only-for-the-owner checks here; the screenshots themselves are
// reviewed: with OPENWIZ_E11_SHOTS=<dir> this proof also writes
// <dir>/{phone,desktop}.png.

import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, pageIdle, PHONE, waitFor } from '../support/browser.mjs';
import { axe } from '../support/harness.mjs';
import { card, decisionsSite, openDecisions, slot } from '../fixtures/decisions/decisions.mjs';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const SHOTS = process.env.OPENWIZ_E11_SHOTS ?? null;
const button = (s, name) => s.getByRole('button', { name, exact: true });

for (const [name, viewport] of [['desktop', DESKTOP], ['phone', PHONE]]) {
  test(`EP4: Decisions in the target's state at ${viewport.width}px: no sideways scroll, 44 px targets, axe clean`, async () => {
    const fx = await decisionsSite();
    const p = await openDecisions(browser, fx, viewport, { paused: false });
    const page = p.page;
    try {
      // #2790 sent, waiting for the orchestrator to save it.
      const sent = slot(page, 9100004);
      await button(sent, 'Confirm spec #2790, sends confirm spec #2790').click();
      await waitFor(async () => (await sent.locator('[data-part=send]').getAttribute('aria-disabled')) === null, { what: 'Send ready' });
      await sent.locator('[data-part=send]').click();
      await waitFor(() => sent.locator('[data-part=sent]').count(), { what: 'the sent row' });
      // L5 in own words; #2900 at its second confirmation.
      const l5 = slot(page, 9100001, 'L5');
      await button(l5, 'Own words').click();
      await l5.getByRole('textbox', { name: 'Your words for L5' }).fill('Only on the PC hub for now. Phone stays quiet.');
      const plan = slot(page, 9100003);
      await button(plan, 'Approve #2900, sends approve #2900').click();
      await waitFor(() => plan.locator('[data-part=armed]').count(), { what: 'the second confirmation' });
      const outgoing = await plan.locator('[data-part=outgoing]').textContent();
      assert.ok(outgoing.startsWith('openwiz decision answer v1\n'), 'second confirmation shows generated context');
      assert.ok(outgoing.includes('\"request_id\":\"dr_plan_2900\"'));
      assert.ok(outgoing.endsWith('\n\napprove #2900'));
      assert.equal(await button(plan, 'Yes, approve #2900').count(), 1, 'confirmation keeps a concise accessible action');
      await waitFor(() => pageIdle(page), { what: 'idle' });
      await page.evaluate(() => window.scrollTo(0, 0));

      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), viewport.width, 'no sideways scroll');
      const cards = await page.locator('[data-part=decisions] [data-comment]').all();
      for (const c of cards) {
        const r = await c.boundingBox();
        assert.ok(r.width <= 960, `a card is ${r.width} px wide; at most 960`);
        assert.ok(r.x >= 0 && r.x + r.width <= viewport.width, 'a card fits the screen');
      }
      for (const b of await page.locator('[data-part=decisions] [data-comment] button').all()) {
        if (!(await b.isVisible())) continue;
        const r = await b.boundingBox();
        assert.ok(r.height >= 44 && r.width >= 44, `an answer button is ${r.width}x${r.height}`);
      }
      // The plan's ticket table never widens the page: it scrolls in its card.
      const table = await card(page, 9100003).locator('[data-part=tickets]').boundingBox();
      assert.ok(table.x >= 0 && table.x + table.width <= viewport.width);
      // Gold is only for what waits on the owner: each open card's edge and its primary answer.
      const gold = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--ow-color-attention').trim());
      // Rule 5: no bordered cards; the edge is an inset rail, as Needs you's.
      const probe = await page.evaluate((g) => { const d = document.createElement('div'); d.style.color = g; document.body.append(d); const c = getComputedStyle(d).color; d.remove(); return c; }, gold);
      const rail = (comment) => card(page, comment).evaluate((c) => getComputedStyle(c).boxShadow);
      assert.ok((await rail(9100002)).includes(probe), 'an open card has the gold edge');
      assert.equal((await rail(9100004)).includes(probe), false, 'a sent card waits on the orchestrator, not the owner: no gold edge');
      assert.equal(await card(page, 9100002).evaluate((c) => getComputedStyle(c).borderLeftStyle), 'none', 'no bordered card');
      for (const tab of ['Sessions', 'Fleets', 'Decisions']) {
        assert.equal(await page.getByRole('navigation', { name: 'Views', exact: true }).getByRole('button', { name: new RegExp(`^${tab}`) }).isVisible(), true, `${tab} is reachable`);
      }
      for (const b of await page.locator('.app-nav button').all()) {
        if (!(await b.isVisible())) continue;
        const r = await b.boundingBox();
        assert.ok(r.height >= 44 && r.width >= 44, `a tab is ${r.width}x${r.height}`);
      }
      assert.deepEqual(await axe(page), []);
      assert.deepEqual(await p.csp(), []);
      assert.deepEqual(p.errors, []);
      if (SHOTS) {
        mkdirSync(SHOTS, { recursive: true });
        // Design rule 19: anything synthetic is labelled DEMO. Test-only, after every check above.
        await page.evaluate(() => {
          const tag = document.createElement('div');
          tag.textContent = 'DEMO · synthetic data';
          Object.assign(tag.style, { position: 'fixed', top: '4px', left: '50%', transform: 'translateX(-50%)', zIndex: '100', padding: '4px 12px', borderRadius: '9999px', background: 'var(--s3)', color: 'var(--ink)', font: 'var(--ow-type-caption)' });
          document.body.append(tag);
        });
        await page.screenshot({ path: join(SHOTS, `${name}.png`) });
        await page.screenshot({ path: join(SHOTS, `${name}-full.png`), fullPage: true });
      }
    } finally { await p.close(); await fx.close(); }
  });
}
