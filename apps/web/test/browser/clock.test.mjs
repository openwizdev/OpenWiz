// #607 CI regression: setup advancement must not make a paused clock
// target the past. All pages and clock values here are synthetic.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { launchBrowser, openPage } from '../support/browser.mjs';

test('paused page clocks survive setup advancement and keep exact dates and timer boundaries', async () => {
  const browser = await launchBrowser();
  // Keep the running-clock advancement regression and inject a controlled
  // setup delay after an early clock read, independent of machine load.
  let setupRead;
  const advancingBrowser = {
    async newContext(options) {
      const context = await browser.newContext(options);
      const install = context.clock.install.bind(context.clock);
      const pauseAt = context.clock.pauseAt.bind(context.clock);
      let paused = false;
      context.clock.pauseAt = async (...args) => {
        await pauseAt(...args);
        paused = true;
        // Read the paused clock during installation, before any later setup
        // calls replay. A slow runner can separate those replay steps.
        setupRead = await context.addInitScript(() => { Date.now(); });
      };
      context.clock.install = async (...args) => {
        await install(...args);
        if (!paused) await context.clock.runFor(1000);
      };
      const newPage = context.newPage.bind(context);
      context.newPage = async () => {
        const page = await newPage();
        // Controlled setup delay, not a wait for application readiness.
        await delay(250);
        return page;
      };
      return context;
    },
  };
  try {
    for (const [input, expected] of [
      [0, 0],
      [-1000, -1000],
      [new Date('2027-01-15T08:00:00Z'), 1_800_000_000_000],
      ['2020-01-01T00:00:00Z', 1_577_836_800_000],
    ]) {
      const p = await openPage(advancingBrowser, 'data:text/html,<title>Synthetic clock</title>', { path: '', clock: input, paused: true });
      try {
        assert.equal(await p.page.evaluate(() => Date.now()), expected);
        assert.deepEqual(
          await p.page.evaluate(() => [performance.timeOrigin, performance.now()]),
          [expected, 0],
        );
        // The injected read models startup only; later navigations should
        // replay the timer advances without this setup instrumentation.
        await setupRead.dispose();
        await p.page.evaluate(() => {
          window.fired = 0;
          setTimeout(() => window.fired++, 1000);
        });
        await p.page.clock.runFor(999);
        assert.deepEqual(await p.page.evaluate(() => [Date.now(), window.fired]), [expected + 999, 0]);
        await p.page.clock.runFor(1);
        assert.deepEqual(await p.page.evaluate(() => [Date.now(), window.fired]), [expected + 1000, 1]);
        await p.page.reload();
        assert.equal(await p.page.evaluate(() => Date.now()), expected + 1000);
      } finally {
        await p.close();
      }
    }
  } finally {
    await browser.close();
  }
});

// R1: no page script reads the clock before the controlled delay. It must
// pause during document startup, including future runFor logs on reload.
for (const origin of ['data:text/html,<title>Synthetic late clock</title>', 'about:blank']) {
  test(`paused clocks keep exact ticks when the first navigated-document read is late (${origin})`, async () => {
    const browser = await launchBrowser();
    const start = 1_800_000_000_000;
    try {
      const p = await openPage(browser, origin, { path: '', clock: start, paused: true });
      try {
        await delay(350);
        assert.deepEqual(
          await p.page.evaluate(() => [Date.now(), performance.timeOrigin, performance.now()]),
          [start, start, 0],
        );
        await p.page.evaluate(() => {
          window.fired = 0;
          setTimeout(() => window.fired++, 1000);
        });
        await p.page.clock.runFor(999);
        assert.deepEqual(await p.page.evaluate(() => [Date.now(), performance.now(), window.fired]), [start + 999, 999, 0]);
        await p.page.clock.runFor(1);
        assert.deepEqual(await p.page.evaluate(() => [Date.now(), performance.now(), window.fired]), [start + 1000, 1000, 1]);
        await p.page.reload();
        await delay(350);
        assert.deepEqual(
          await p.page.evaluate(() => [Date.now(), performance.timeOrigin, performance.now()]),
          [start + 1000, start, 1000],
        );
        const copy = await p.context.newPage();
        await copy.goto(origin);
        await delay(350);
        assert.deepEqual(
          await copy.evaluate(() => [Date.now(), performance.timeOrigin, performance.now()]),
          [start + 1000, start, 1000],
        );
      } finally {
        await p.close();
      }
    } finally {
      await browser.close();
    }
  });
}
