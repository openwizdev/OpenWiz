// #603: repeated detail interactions retain only the latest V11 samples.
// Observe production marks; never clear the timeline from the test.
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, openPage, PHONE, readDetail, waitFor } from '../support/browser.mjs';
import { json } from '../support/fake-api.mjs';
import { fakeSite } from '../support/harness.mjs';
import { inventory, manyRows, session, sessionView } from '../support/synthetic.ts';

const MARKS = ['detail-tap', 'detail-shown', 'detail-loaded'];
let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

for (const [layout, viewport] of [['phone', PHONE], ['desktop', DESKTOP]]) {
  test(`${layout}: 30 open/close cycles keep the latest detail marks and unrelated marks`, async () => {
    const fx = await fakeSite();
    fx.api.setList(() => json(200, inventory(manyRows(1), { matched: 1 })));
    fx.api.setDetail(() => json(200, sessionView(session(1))));
    let p;
    try {
      p = await openPage(browser, fx.site.origin, { viewport });
      await p.page.waitForSelector('main button[data-session-id]');
      const unrelated = await p.page.evaluate((names) => {
        window.__detailMarkSamples = Object.fromEntries(names.map((name) => [name, { count: 0, startTime: null }]));
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            const sample = window.__detailMarkSamples[entry.name];
            if (sample) { sample.count++; sample.startTime = entry.startTime; }
          }
        }).observe({ entryTypes: ['mark'] });
        return performance.mark('synthetic-unrelated').startTime;
      }, MARKS);
      for (let cycle = 1; cycle <= 30; cycle++) {
        await p.page.click('main button[data-session-id]');
        await waitFor(() => p.page.evaluate((n) => window.__detailMarkSamples['detail-loaded'].count === n, cycle), { what: 'this cycle loaded' });
        assert.equal((await readDetail(p.page))?.title, 'Synthetic web session 1');
        await p.page.keyboard.press('Escape');
        await waitFor(async () => (await readDetail(p.page)) === null, { what: 'detail closed' });
        const sample = await p.page.evaluate((names) => ({
          observed: window.__detailMarkSamples,
          retained: Object.fromEntries(names.map((name) => [name, performance.getEntriesByName(name, 'mark').map((entry) => entry.startTime)])),
          unrelated: performance.getEntriesByName('synthetic-unrelated', 'mark').map((entry) => entry.startTime),
        }), MARKS);
        for (const name of MARKS) {
          assert.equal(sample.observed[name].count, cycle, `${name}: one event per interaction`);
          assert.deepEqual(sample.retained[name], [sample.observed[name].startTime], `${name}: retain only this interaction's mark after cycle ${cycle}`);
        }
        const [tap, shown, loaded] = MARKS.map((name) => sample.retained[name][0]);
        assert.ok(tap <= shown && shown <= loaded, 'V11 can still measure tap-to-shown and tap-to-loaded');
        assert.deepEqual(sample.unrelated, [unrelated], 'unrelated instrumentation survives');
      }
      assert.deepEqual(p.errors, []);
    } finally {
      await p?.close();
      await fx.close();
    }
  });
}
