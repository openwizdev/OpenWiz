// EP2 (#653): trace. Hover or keyboard focus previews a ticket's direct
// prerequisites and dependents; a press pins it, with both counts and its
// neighbours named across folded and filtered-out versions; Escape and
// "Clear trace" return focus; a ticket opens only its own issue and pull
// request links; rails on the PC, relation words on the phone. The packet's
// trace (#2107: waits on #2105, #2106; #2108, #2109, #2307, #2405, #2606 wait
// on it) is the expected value. The page only reads GET /api/v1/plan.

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, PHONE, waitFor } from '../support/browser.mjs';
import { card, link, openPlan, planSite, sheet } from '../fixtures/plan/plan.mjs';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const relations = (page) => page.locator('[data-card-ticket][data-relation]').evaluateAll((els) => els.map((e) => [Number(e.dataset.cardTicket), e.dataset.relation, e.querySelector('[data-part=relation]')?.textContent ?? null]).sort((a, b) => a[0] - b[0]));
const PINNED = [
  [2105, 'prerequisite', 'prerequisite'],
  [2106, 'prerequisite', 'prerequisite'],
  [2107, 'selected', 'selected'],
  [2108, 'dependent', 'waits on #2107'],
  [2109, 'dependent', 'waits on #2107'],
  [2307, 'dependent', 'waits on #2107'],
  [2405, 'dependent', 'waits on #2107'],
  [2606, 'dependent', 'waits on #2107'],
];

test('EP2: hover and keyboard focus preview #2107\'s neighbours only; a pointer press moves nothing before its click', async () => {
  const fx = await planSite();
  const p = await openPlan(browser, fx, DESKTOP);
  const page = p.page;
  try {
    await card(page, 2107).hover();
    assert.deepEqual(await relations(page), PINNED, 'the preview names the direct neighbours');
    assert.equal(await page.locator('[data-part=trace]').count(), 0, 'a preview pins nothing');
    await page.mouse.move(0, 0);
    assert.deepEqual(await relations(page), [], 'leaving ends the preview');
    // Keyboard focus previews the same.
    await card(page, 2107).focus();
    assert.deepEqual(await relations(page), PINNED);
    await card(page, 2107).blur();
    // The press itself: every card's box is where it was before the press.
    const box = await card(page, 2108).boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    const before = await page.locator('[data-card-ticket]').evaluateAll((els) => els.map((e) => JSON.stringify(e.getBoundingClientRect())));
    await page.mouse.down();
    const pressed = await page.locator('[data-card-ticket]').evaluateAll((els) => els.map((e) => JSON.stringify(e.getBoundingClientRect())));
    assert.deepEqual(pressed, before, 'no reflow between hover, press and click');
    await page.mouse.up();
    assert.equal(await card(page, 2108).getAttribute('aria-pressed'), 'true');
  } finally {
    await p.close();
    await fx.close();
  }
});

for (const [name, viewport] of [['desktop', DESKTOP], ['phone', PHONE]]) {
  test(`EP2: a press pins #2107's trace, names both directions across folded and filtered versions, and Escape returns focus, at ${viewport.width}px`, async () => {
    const fx = await planSite();
    const p = await openPlan(browser, fx, viewport);
    const page = p.page;
    try {
      if (name === 'phone') await sheet(page, 'version:6').locator('.pl-fold').click();
      else for (const key of ['version:9', 'version:10', 'side_spec:2600']) await sheet(page, key).locator('.pl-fold').click();
      await card(page, 2107).click();
      assert.equal(await card(page, 2107).getAttribute('aria-pressed'), 'true', 'the selected state is announced');
      const bar = page.locator('[data-part=trace]');
      assert.equal(await bar.locator('.pl-trace-title').textContent(), 'Tracing #2107 Fleet controls — waits on 2 · 5 wait on it');
      assert.deepEqual(await bar.locator('ul').nth(0).locator('li').allTextContents(), ['#2105 Decision delivery', '#2106 Control vocabulary']);
      assert.deepEqual(await bar.locator('ul').nth(1).locator('li').allTextContents(), ['#2108 Retry safety', '#2109 Fleet smoke test', '#2307 Concurrency limits · 0.0.9 Loops', '#2405 Plan projection · 0.0.10 Cockpit', '#2606 Read-only graph · Side spec #2600 Access']);
      // Folded neighbours give their version row a quiet tag.
      for (const key of ['version:9', 'version:10', 'side_spec:2600']) assert.deepEqual(await sheet(page, key).locator('[data-part=near]').allTextContents(), ['1 waits on #2107'], key);
      assert.equal(await sheet(page, 'version:8').locator('[data-part=near]').count(), 0);
      // Shown neighbours say their relation in words (the phone's only trace).
      for (const [n, , words] of PINNED.filter(([n]) => n < 2200)) assert.equal(await card(page, n).locator('[data-part=relation]').textContent(), words, `#${n}`);
      // The chain strip's copies say it too.
      assert.equal(await link(page, 2105).locator('[data-part=relation]').textContent(), 'prerequisite');
      assert.equal(await link(page, 2405).locator('[data-part=relation]').textContent(), 'waits on #2107');
      // The filter narrows the lanes; the trace still uses the whole plan.
      await page.locator('[data-part=plan] select').selectOption({ label: '0.0.8 PC hub' });
      assert.equal(await bar.locator('[data-part=trace-counts]').textContent(), '— waits on 2 · 5 wait on it');
      assert.equal(await bar.locator('ul').nth(1).locator('li').count(), 5);
      await page.locator('[data-part=plan] select').selectOption({ label: 'All versions' });
      // Escape clears the trace and returns focus to the ticket it was pinned from.
      await card(page, 2107).focus();
      await page.keyboard.press('Escape');
      assert.equal(await bar.count(), 0);
      assert.equal(await card(page, 2107).getAttribute('aria-pressed'), 'false');
      assert.equal(await page.evaluate(() => document.activeElement?.dataset.cardTicket), '2107', 'focus returns');
      // "Clear trace" does the same.
      await card(page, 2105).click();
      await page.locator('[data-part=clear-trace]').click();
      assert.equal(await bar.count(), 0);
      assert.equal(await page.evaluate(() => document.activeElement?.dataset.cardTicket), '2105');
      // Its ticket folded away: Clear trace returns focus to the page's title, never to nowhere.
      await card(page, 2105).click();
      await sheet(page, 'version:6').locator('.pl-fold').click();
      await page.locator('[data-part=clear-trace]').click();
      assert.equal(await page.evaluate(() => document.activeElement?.id), 'pl-title');
    } finally {
      await p.close();
      await fx.close();
    }
  });
}

test('EP2: a ticket opens only its own GitHub issue and, when known, its pull request; the page only reads GET /api/v1/plan', async () => {
  const fx = await planSite();
  const p = await openPlan(browser, fx, DESKTOP);
  const page = p.page;
  try {
    await card(page, 2102).click();
    assert.equal(await page.locator('[data-part=open-issue]').getAttribute('href'), 'https://github.com/example-owner/example-plan/issues/2102');
    assert.equal(await page.locator('[data-part=open-issue]').textContent(), 'Open issue #2102');
    assert.equal(await page.locator('[data-part=open-pr]').getAttribute('href'), 'https://github.com/example-owner/example-plan/pull/3102');
    assert.equal(await page.locator('[data-part=open-pr]').textContent(), 'Open pull request #3102');
    assert.equal(await page.locator('[data-part=open-pr]').getAttribute('rel'), 'noopener noreferrer');
    await card(page, 2107).click();
    assert.equal(await page.locator('[data-part=open-issue]').getAttribute('href'), 'https://github.com/example-owner/example-plan/issues/2107');
    assert.equal(await page.locator('[data-part=open-pr]').count(), 0, 'no pull request: no link');
    const planReads = p.requests.filter((r) => new URL(r.url).pathname === '/api/v1/plan');
    assert.equal(planReads.length, 1, 'one read on this paused clock');
    assert.ok(planReads.every((r) => r.method === 'GET' && new URL(r.url).search === ''), 'an exact GET, no query');
    assert.deepEqual(p.requests.filter((r) => r.method !== 'GET').map((r) => r.url), [], 'nothing written');
    assert.deepEqual(p.errors, []);
  } finally {
    await p.close();
    await fx.close();
  }
});

test('EP2: on the PC, rails draw every open prerequisite edge (71 in the packet), across versions, arrowheads at prerequisites; the trace is drawn over them; folded sheets drop theirs; the phone draws none', async () => {
  const fx = await planSite();
  try {
    const p = await openPlan(browser, fx, DESKTOP);
    const page = p.page;
    try {
      const rails = page.locator('[data-part=rails] path[data-rail]');
      // The packet: 71 dependencies among 60 tickets, every version open on the PC.
      assert.equal(await rails.count(), 71, 'the whole graph, before any trace');
      assert.equal(await page.locator('[data-part=rails] path[data-traced]').count(), 0);
      for (const edge of ['2107>2105', '2107>2106', '2307>2107', '2405>2107', '2606>2107', '2409>2210']) {
        assert.equal(await page.locator(`[data-rail="${edge}"]`).count(), 1, `${edge}, across versions too`);
      }
      await card(page, 2107).click();
      const traced = page.locator('[data-part=rails] path[data-traced]');
      assert.deepEqual((await traced.evaluateAll((els) => els.map((e) => e.dataset.rail))).sort(), ['2107>2105', '2107>2106', '2108>2107', '2109>2107', '2307>2107', '2405>2107', '2606>2107']);
      assert.equal(await rails.count(), 71, 'the trace highlights; it removes nothing');
      // Each rail ends at its prerequisite's edge.
      const ends = await traced.evaluateAll((els) => els.map((e) => { const l = e.getTotalLength(); const pt = e.getPointAtLength(l); const box = e.ownerSVGElement.getBoundingClientRect(); return { rail: e.dataset.rail, x: pt.x + box.x, y: pt.y + box.y }; }));
      for (const end of ends) {
        const at = Number(end.rail.split('>')[1]);
        const box = await card(page, at).boundingBox();
        assert.ok(end.y >= box.y && end.y <= box.y + box.height && Math.min(Math.abs(end.x - box.x), Math.abs(end.x - box.x - box.width)) <= 4, `${end.rail} ends at #${at}`);
      }
      const gold = await page.evaluate(() => { const i = document.createElement('i'); i.style.color = 'var(--ow-color-attention)'; document.body.append(i); const c = getComputedStyle(i).color; i.remove(); return c; });
      const live = await page.evaluate(() => { const i = document.createElement('i'); i.style.color = 'var(--ow-color-live)'; document.body.append(i); const c = getComputedStyle(i).color; i.remove(); return c; });
      for (const colour of await page.locator('[data-part=rails] path').evaluateAll((els) => els.map((e) => getComputedStyle(e).color))) {
        assert.ok(colour !== gold && colour !== live, `rails are neutral: ${colour}`);
      }
      // Folding 0.0.9 drops its rails; its neighbour of #2107 is named on its row and in the trace.
      await sheet(page, 'version:9').locator('.pl-fold').click();
      assert.equal(await page.locator('[data-rail="2307>2107"]').count(), 0);
      assert.deepEqual(await sheet(page, 'version:9').locator('[data-part=near]').allTextContents(), ['1 waits on #2107']);
      assert.equal(await page.locator('[data-rail="2405>2107"]').count(), 1);
      assert.deepEqual(await page.locator('[data-part=trace] ul').nth(1).locator('li').allTextContents(), ['#2108 Retry safety', '#2109 Fleet smoke test', '#2307 Concurrency limits · 0.0.9 Loops', '#2405 Plan projection · 0.0.10 Cockpit', '#2606 Read-only graph · Side spec #2600 Access']);
    } finally {
      await p.close();
    }
    // A refresh that moves a ticket to another column, with the same edges: its rails follow it.
    const r = await openPlan(browser, fx, DESKTOP);
    try {
      const end = async () => r.page.locator('[data-rail="2204>2202"]').evaluate((e) => { const pt = e.getPointAtLength(e.getTotalLength()); const b = e.ownerSVGElement.getBoundingClientRect(); return { x: pt.x + b.x, y: pt.y + b.y }; });
      const near = async (n, pt) => { const b = await card(r.page, n).boundingBox(); return pt.y >= b.y && pt.y <= b.y + b.height && Math.min(Math.abs(pt.x - b.x), Math.abs(pt.x - b.x - b.width)) <= 4; };
      assert.ok(await near(2202, await end()), 'at #2202, building');
      const moved = structuredClone(fx.doc);
      Object.assign(moved.tickets.find((t) => t.number === 2202), { state: { known: 'merged' }, column: { known: 'done' } });
      const before = fx.doc;
      fx.doc = moved;
      const seq = await r.page.locator('[data-part=plan]').getAttribute('data-snapshot-seq');
      await r.page.clock.runFor(61_000);
      await waitFor(async () => (await r.page.locator('[data-part=plan]').getAttribute('data-snapshot-seq')) !== seq, { what: 'the refreshed plan' });
      assert.equal(await sheet(r.page, 'version:8').locator('[data-column=done] [data-card-ticket="2202"]').count(), 1, '#2202 moved to Done');
      await waitFor(async () => near(2202, await end()), { what: 'the rail at #2202\'s new place' });
      fx.doc = before;
    } finally {
      await r.close();
    }
    const q = await openPlan(browser, fx, PHONE);
    try {
      await sheet(q.page, 'version:6').locator('.pl-fold').click();
      await card(q.page, 2107).click();
      assert.equal(await q.page.locator('[data-part=rails]').count(), 0, 'no arrows on the phone');
      assert.equal(await card(q.page, 2108).locator('[data-part=relation]').textContent(), 'waits on #2107');
    } finally {
      await q.close();
    }
  } finally {
    await fx.close();
  }
});
