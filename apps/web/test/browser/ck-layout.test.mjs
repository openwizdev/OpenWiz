// CK4 (#536, spec #530): page 1 against the design target
// at 390 and 1440 CSS px, on the
// target's synthetic scene (test/fixtures/cockpit/target.json). Layout checks
// here; the screenshots themselves are reviewed: with OPENWIZ_CK_SHOTS=<dir>
// this proof also writes <dir>/{phone,desktop}.png.

import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, PHONE } from '../support/browser.mjs';
import { axe } from '../support/harness.mjs';
import { cockpitSite, openCockpit, row } from '../fixtures/cockpit/cockpit.mjs';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const SHOTS = process.env.OPENWIZ_CK_SHOTS ?? null;

for (const [name, viewport] of [['desktop', DESKTOP], ['phone', PHONE]]) {
  test(`CK4: the cockpit's order, groups, markers, filters and freshness at ${viewport.width}px`, async () => {
    const fx = await cockpitSite();
    const p = await openCockpit(browser, fx, viewport, { paused: false });
    const page = p.page;
    try {
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), viewport.width, 'no sideways scroll');
      const needs = await page.locator('#ck-needs-title').boundingBox();
      const agents = await page.locator('#ck-agents-title').boundingBox();
      assert.ok(needs.y < agents.y, 'Needs you on top, the grid below');
      assert.equal(await page.locator('#ck-needs-title').textContent(), 'Needs you 4');
      assert.equal(await page.locator('#ck-agents-title').textContent(), 'Agents 6');

      // Freshness: partial is said, with its gaps and the projects not fully read; never gold.
      const fresh = page.locator('[data-part=freshness]');
      assert.equal(await fresh.getAttribute('data-state'), 'partial');
      assert.equal(await fresh.locator('[data-part=freshness-words]').textContent(), 'Partial · read 08:00:00 · 5 gaps · 2 projects not fully read (Atlas, Orchard)');
      assert.notEqual(await fresh.locator('.status-chip').evaluate((el) => getComputedStyle(el).color), await page.evaluate(() => { const i = document.createElement('i'); i.style.color = 'var(--ow-color-attention)'; document.body.append(i); const c = getComputedStyle(i).color; i.remove(); return c; }), 'the freshness line is never gold');

      // The machine filter offers only "All" until the inventory reports machines (#530).
      const machine = page.locator('[data-part=filters] select').nth(1);
      assert.equal(await machine.isDisabled(), true);
      assert.equal(await page.locator('[data-part=machines-note]').textContent(), 'machines not reported yet');

      // The grid: by project and fleet, the unplaced last and never hidden.
      assert.deepEqual(await page.locator('.ck-group').evaluateAll((gs) => gs.map((g) => [g.dataset.group, g.querySelectorAll('[data-thread]').length])), [['prj_syn_atl1:901', 3], ['prj_syn_lan2:700', 2], ['unplaced', 1]]);
      assert.deepEqual(await page.locator('.ck-group-title').evaluateAll((hs) => hs.map((h) => h.textContent)), ['Atlas', 'Lantern', 'Orchard', 'Atlas / #9013', 'Lantern / #7002', 'Not placed1']);
      assert.deepEqual(await page.locator('[data-needs-you=true]').evaluateAll((rs) => rs.map((r) => r.dataset.thread)), ['thr_syn_0011', 'thr_syn_0021']);
      // t1: the grid's needs-you marker is solid gold with dark text.
      const pill = await page.locator('[data-thread=thr_syn_0011] [data-part=needs-you-pill]').evaluate((el) => {
        const s = getComputedStyle(el);
        // The tokens, resolved by the browser (CSSOM, which the page's CSP allows).
        const probe = document.createElement('i');
        probe.style.backgroundColor = 'var(--ow-color-attention)';
        probe.style.color = 'var(--ow-color-on-attention)';
        document.body.append(probe);
        const t = getComputedStyle(probe);
        const out = { bg: s.backgroundColor, fg: s.color, gold: t.backgroundColor, ink: t.color };
        probe.remove();
        return out;
      });
      const tokens = pill;
      assert.equal(pill.bg, tokens.gold, 'solid gold fill');
      assert.equal(pill.fg, tokens.ink, 'dark text on gold');
      assert.equal(await page.locator('[data-thread=thr_syn_0013] [data-part=location]').textContent(), 'Local · machine not reported');
      assert.equal(await page.locator('[data-thread=thr_syn_0011] [data-part=location]').textContent(), 'Cloud');
      assert.equal(await page.locator('[data-part=running]').count(), 0, 'no start reported, no time running');
      assert.equal(await page.locator('#ck-agents-title + .meta').textContent(), 'running now · time running not reported yet · partial: others may be running');

      // Big buttons on Needs you only: at least the touch target.
      for (const b of await row(page, 904).locator('button').all()) {
        const r = await b.boundingBox();
        assert.ok(r.height >= 44 && r.width >= 44, `a Needs you button is ${r.width}x${r.height}`);
      }
      for (const b of await page.locator('.app-nav button').filter({ visible: true }).all()) {
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
        // The risky item armed: its button names the action and asks again.
        await row(page, 712).getByRole('button', { name: /^Yes to item/ }).click();
        await row(page, 712).locator('[data-part=armed]').waitFor();
        await row(page, 712).scrollIntoViewIfNeeded();
        await page.screenshot({ path: join(SHOTS, `${name}-armed.png`) });
      }
    } finally { await p.close(); await fx.close(); }
  });
}

test('CK4: time running comes only from a reported start, labelled; the rest say it is not reported', async () => {
  const fx = await cockpitSite();
  fx.doc = structuredClone(fx.doc);
  fx.doc.agents.items[0].started_at = { known: fx.doc.snapshot_at - 600_000 };
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    assert.equal(await p.page.locator('[data-thread=thr_syn_0011] [data-part=running]').textContent(), 'running 10m (from its reported start)');
    assert.equal(await p.page.locator('[data-thread=thr_syn_0012] [data-part=running]').textContent(), 'time running not reported');
    assert.equal(await p.page.locator('#ck-agents-title + .meta').textContent(), 'running now · partial: others may be running');
  } finally { await p.close(); await fx.close(); }
});
