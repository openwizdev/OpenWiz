// PA6/PA7 synthetic client rendering. PC CI only; no real-phone/live claim.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { after, before, test } from 'node:test';
import { launchBrowser, DESKTOP, PHONE } from '../support/browser.mjs';
import { cockpitSite, openCockpit } from '../fixtures/cockpit/cockpit.mjs';
let browser;
before(async () => { browser = await launchBrowser(); });
after(async () => { await browser?.close(); });
const packet = () => JSON.parse(readFileSync(new URL('../fixtures/ready-stock/partial.json', import.meta.url), 'utf8'));
// Permission/capability environments must not gate queue visibility or trigger
// permission/delivery effects. The older case exercises absent setup only.
// These are browser-environment fixtures, not T4 preference/status integration.
function withDeliveryEnvironment(state) {
  return { newContext: async (options) => {
    const context = await browser.newContext(options);
    await context.addInitScript((state) => {
      window.__stockNotificationEffects = 0;
      if (state === 'unsupported') {
        Object.defineProperty(window, 'Notification', { value: undefined, configurable: true });
        return;
      }
      class SyntheticNotification {
        static permission = state === 'denied' ? 'denied' : state === 'failed' ? 'granted' : 'default';
        static requestPermission() { window.__stockNotificationEffects++; return Promise.reject(new Error('Synthetic permission effect')); }
        constructor() { window.__stockNotificationEffects++; if (state === 'failed') throw new Error('Synthetic delivery failure'); }
      }
      Object.defineProperty(window, 'Notification', { value: SyntheticNotification, configurable: true });
    }, state);
    return context;
  } };
}
for (const viewport of [PHONE, DESKTOP]) for (const delivery of ['off', 'unsupported', 'denied', 'failed']) {
    test(`partial stock stays visible with ${delivery} delivery environment at ${viewport.width}px`, async () => {
      // No delivery API is configured. Browser permission/capability is synthetic;
      // any permission request or display attempt is recorded and refused.
      const fx = await cockpitSite(packet());
      const p = await openCockpit(withDeliveryEnvironment(delivery), fx, viewport);
      try {
        const stock = p.page.locator('[data-part=ready-stock]');
        await stock.waitFor({ state: 'visible' });
        assert.match(await stock.innerText(), /Partial · totals unknown/);
        assert.match(await stock.innerText(), /3 ready · 2 running/);
        assert.match(await stock.innerText(), /2 unknown/);
        assert.match(await stock.innerText(), /Last good/);
        assert.match(await stock.innerText(), /PR-title evidence unavailable/);
        const width = await p.page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: innerWidth }));
        assert.ok(width.content <= width.viewport, JSON.stringify(width));
        assert.equal(await stock.locator('button, textarea, input').count(), 0, 'summary has no work or permission controls');
        assert.equal(fx.api.log.filter((r) => r.method !== 'GET').length, 0, 'no write effects');
        assert.equal(await p.page.evaluate(() => window.__stockNotificationEffects), 0, 'no permission request or notification effect');
        assert.deepEqual(p.errors, [], 'permission/capability state cannot break queue rendering');
      } finally { await p.close(); await fx.close(); }
    });
}
for (const viewport of [PHONE, DESKTOP]) {
  test(`unavailable stock preserves every opaque cockpit project at ${viewport.width}px`, async () => {
    const doc = packet(); doc.projects.items[1].id = 'zz.synthetic'; delete doc.ready_stock;
    const fx = await cockpitSite(doc);
    const p = await openCockpit(browser, fx, viewport);
    try {
      const stock = p.page.locator('[data-part=ready-stock]');
      await stock.waitFor({ state: 'visible' });
      assert.equal(await stock.locator('[data-stock-project]').count(), 2);
      assert.match(await stock.locator('[data-stock-project="zz.synthetic"]').innerText(), /Counts unknown/);
      assert.equal(fx.api.log.filter((r) => r.method !== 'GET').length, 0);
    } finally { await p.close(); await fx.close(); }
  });
}
