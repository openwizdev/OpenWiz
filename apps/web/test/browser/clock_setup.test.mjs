// CI repair proof: synthetic local page, real Playwright clock, explicit
// virtual advancement at the install/pause boundary; no wall-time race.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { launchBrowser, openPage } from '../support/browser.mjs';

const START = Date.parse('2027-01-15T08:00:00Z');

for (const clock of [new Date(START), START, '2027-01-15T08:00:00Z']) {
  test(`paused setup tolerates an advanced clock and preserves timer control (${typeof clock})`, async (t) => {
    const browser = await launchBrowser();
    t.after(() => browser.close());
    const site = createServer((_req, res) => {
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end('<!doctype html><script>window.bootAt=Date.now();window.fired=0;setTimeout(()=>window.fired++,1000)</script>');
    });
    t.after(() => new Promise((resolve) => site.close(resolve)));
    await new Promise((resolve) => site.listen(0, '127.0.0.1', resolve));
    const advancedBrowser = {
      async newContext(options) {
        const context = await browser.newContext(options);
        const newPage = context.newPage.bind(context);
        context.newPage = async () => {
          const page = await newPage();
          const pauseAt = page.clock.pauseAt.bind(page.clock);
          let paused = false;
          page.clock.pauseAt = async (...args) => {
            await pauseAt(...args);
            paused = true;
          };
          for (const name of ['install', 'setFixedTime']) {
            const original = page.clock[name].bind(page.clock);
            page.clock[name] = async (...args) => {
              await original(...args);
              // Elapsed setup time advances only a running clock.
              if (!paused) await page.clock.runFor(60_000);
            };
          }
          return page;
        };
        return context;
      },
    };
    const p = await openPage(advancedBrowser, `http://127.0.0.1:${site.address().port}`, { clock, paused: true });
    assert.deepEqual(await p.page.evaluate(() => [window.bootAt, Date.now(), window.fired]), [START, START, 0]);
    await p.page.clock.runFor(999);
    assert.deepEqual(await p.page.evaluate(() => [Date.now(), window.fired]), [START + 999, 0]);
    await p.page.clock.runFor(1);
    assert.deepEqual(await p.page.evaluate(() => [Date.now(), window.fired]), [START + 1000, 1]);
    assert.deepEqual(await p.page.evaluate(() => [Date.now(), window.fired]), [START + 1000, 1], 'round trips do not advance a paused clock');
    await p.close();
  });
}
