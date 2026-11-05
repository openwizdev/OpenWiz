// V9: layout. A bottom sheet at phone widths and a side panel at desktop
// widths, 44-point targets, a visible focus, keyboard use on desktop, and
// screen-reader names for every status and for the sheet or panel.

import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, openPage, pageIdle, PHONE, readDetail, readView, waitFor } from '../support/browser.mjs';
import { composerSite, id, openThread } from '../support/composer.mjs';
import { html, json } from '../support/fake-api.mjs';
import { axe, fakeSite } from '../support/harness.mjs';
import { RESULTS_DIR } from '../support/paths.mjs';
import { inventory, manyRows, session, sessionView, statusSessions, T0 } from '../support/synthetic.ts';

let browser;
let fx;
before(async () => {
  browser = await launchBrowser();
  fx = await fakeSite();
  fx.api.setList(() =>
    json(200, inventory([...statusSessions(), ...manyRows(30, 10)], { state: 'partial', matched: 300, limit: 100, gaps: [{ kind: 'timed_out', subject: null, detail: 'machine list timed out' }] })),
  );
  fx.api.setDetail((id) => json(200, sessionView(session(Number(id.slice(-4))))));
});
after(async () => {
  await fx.close();
  await browser.close();
});

async function ready(viewport) {
  const p = await openPage(browser, fx.site.origin, { viewport });
  await waitFor(async () => (await readView(p.page)).groups.length > 0, { what: 'rows' });
  return p;
}

async function open(p, id = 'thr_web_0002') {
  await p.page.click(`[data-session-id="${id}"]`);
  await waitFor(async () => (await readDetail(p.page))?.title?.startsWith('Synthetic'), { what: 'the detail' });
}

const rect = (page, sel) => page.$eval(sel, (el) => el.getBoundingClientRect().toJSON());

test('phone: a modal bottom sheet', async () => {
  const p = await ready(PHONE);
  try {
    await open(p);
    const d = await readDetail(p.page);
    assert.equal(d.modal, true);
    const r = await rect(p.page, '[data-part=detail]');
    assert.ok(Math.abs(r.bottom - PHONE.height) <= 1, `at the bottom (${r.bottom})`);
    assert.ok(Math.abs(r.left) <= 1 && Math.abs(r.width - PHONE.width) <= 1, 'full width');
    assert.ok(Math.abs(r.height - PHONE.height) <= 1, 'a full phone view');
  } finally {
    await p.close();
  }
});

test('desktop: a side panel on the right, with the list still usable', async () => {
  const p = await ready(DESKTOP);
  try {
    await open(p);
    const d = await readDetail(p.page);
    assert.equal(d.modal, false);
    const r = await rect(p.page, '[data-part=detail]');
    assert.ok(Math.abs(r.right - (DESKTOP.width - 12)) <= 1, `on the right (${r.right})`);
    assert.ok(Math.abs(r.width - 776) <= 1, `a panel width (${r.width})`);
    await open(p, 'thr_web_0003');
    assert.equal((await readDetail(p.page)).id, 'thr_web_0003', 'another row opens in the same panel');
    const list = await rect(p.page, '[data-session-id="thr_web_0001"]');
    assert.ok(list.right <= r.left + 1, 'the panel does not cover the rows');
  } finally {
    await p.close();
  }
});

test('the switch is at 900 px', async () => {
  for (const [width, modal] of [
    [899, true],
    [900, false],
  ]) {
    const p = await ready({ width, height: 800 });
    try {
      await open(p);
      assert.equal((await readDetail(p.page)).modal, modal, `${width}px`);
    } finally {
      await p.close();
    }
  }
});

async function smallTargets(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll('button, a[href], summary, [tabindex]:not([tabindex="-1"]), input, select, textarea')]
      .filter((el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
      })
      .map((el) => ({ el: el.outerHTML.slice(0, 80), r: el.getBoundingClientRect() }))
      .filter(({ r }) => r.width < 44 || r.height < 44)
      .map(({ el, r }) => `${el} ${Math.round(r.width)}x${Math.round(r.height)}`),
  );
}

test('every touch target is at least 44 × 44', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    const p = await ready(viewport);
    try {
      await p.page.click('[data-part=coverage]');
      assert.deepEqual(await smallTargets(p.page), [], `list at ${viewport.width}px`);
      await open(p);
      assert.deepEqual(await smallTargets(p.page), [], `detail at ${viewport.width}px`);
    } finally {
      await p.close();
    }
  }
});

test('keyboard: Tab to a row, Enter opens, focus moves in, Escape closes, focus returns', async () => {
  for (const viewport of [DESKTOP, PHONE]) {
    const p = await ready(viewport);
    try {
      let row = null;
      for (let i = 0; i < 40 && !row; i++) {
        await p.page.keyboard.press('Tab');
        row = await p.page.evaluate(() => document.activeElement?.dataset?.sessionId ?? null);
      }
      assert.ok(row, 'a row is reachable by Tab');
      const ring = await p.page.evaluate(() => {
        const s = getComputedStyle(document.activeElement);
        return { style: s.outlineStyle, width: parseFloat(s.outlineWidth) };
      });
      assert.ok(ring.style !== 'none' && ring.width >= 2, `a visible focus ring (${JSON.stringify(ring)})`);
      await p.page.keyboard.press('Enter');
      await waitFor(async () => (await readDetail(p.page))?.id === row, { what: 'the detail by keyboard' });
      const inside = await p.page.evaluate(() => !!document.activeElement?.closest('[data-part=detail]'));
      assert.ok(inside, 'focus moves into the sheet or panel');
      await p.page.keyboard.press('Escape');
      await waitFor(async () => (await readDetail(p.page)) === null, { what: 'Escape closes' });
      const back = await p.page.evaluate(() => document.activeElement?.dataset?.sessionId ?? null);
      assert.equal(back, row, 'focus returns to the row');
    } finally {
      await p.close();
    }
  }
});

test('keyboard: coverage refresh recovers only a removed toggle’s focus', async (t) => {
  for (const viewport of [PHONE, DESKTOP]) {
    for (const [coverage, otherFocus, keepGaps, windowBlur = false] of [
      ['complete', false, false], ['partial', false, false],
      ['complete', true, false], ['partial', false, true],
      ['complete', false, false, true], ['complete', true, false, true],
    ]) {
      await t.test(`${viewport.width}px ${coverage}, other ${otherFocus}, gaps ${keepGaps}, window blur ${windowBlur}`, async () => {
        const site = await fakeSite();
        const gaps = [{ kind: 'timed_out', subject: null, detail: 'synthetic gap' }];
        site.api.setList(() => json(200, inventory([session(1)], { state: 'partial', gaps })));
        const p = await openPage(browser, site.site.origin, { viewport, clock: new Date(T0 + 300_000), paused: true, stampReads: true });
        try {
          await waitFor(async () => (await readView(p.page)).groups.length === 1 && await pageIdle(p.page), { what: 'initial partial inventory' });
          const toggle = p.page.getByRole('button', { name: 'partial · 1 gap', exact: true });
          await toggle.focus();
          await p.page.keyboard.press('Enter');
          assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
          const other = p.page.getByRole('button', { name: 'New thread in Synthetic web project one', exact: true });
          if (otherFocus) await other.focus();
          if (windowBlur) {
            const active = otherFocus ? other : toggle;
            await active.evaluate((el) => el.addEventListener('blur', () => { el.dataset.windowBlur = 'true'; }, { once: true }));
            await (await p.context.newCDPSession(p.page)).send('Emulation.setFocusEmulationEnabled', { enabled: false });
            await (await p.context.newPage()).bringToFront();
            await waitFor(() => p.page.evaluate(() => !document.hasFocus() && document.visibilityState === 'visible'), { what: 'visible window blur' });
            assert.equal(await active.getAttribute('data-window-blur'), 'true');
            assert.equal(await active.evaluate((el) => el === document.activeElement), true);
          }
          site.api.setList(() => json(200, inventory([session(1)], { state: coverage, gaps: keepGaps ? gaps : [] })));
          await p.page.clock.runFor(10_000);
          await waitFor(async () => site.api.reads('list').length === 2 && await pageIdle(p.page), { what: 'automatic inventory refresh' });
          await waitFor(async () => (await readView(p.page)).coverage === (keepGaps ? 'partial · 1 gap' : coverage === 'complete' ? 'complete' : 'partial · 0 gaps'), { what: 'refreshed coverage rendered' });
          if (windowBlur) await p.page.bringToFront();
          assert.equal(await p.page.locator('button.cov').count(), keepGaps ? 1 : 0);
          const expected = otherFocus ? other : keepGaps ? toggle : p.page.getByRole('button', { name: 'Sessions', exact: true });
          assert.equal(await expected.evaluate((el) => el === document.activeElement), true, `named focus at ${viewport.width}px (${coverage}, other focus ${otherFocus}, gaps retained ${keepGaps})`);
          if (!otherFocus) {
            const ring = await expected.evaluate((el) => ({ visible: el.matches(':focus-visible'), width: parseFloat(getComputedStyle(el).outlineWidth) }));
            assert.equal(ring.visible, true);
            assert.ok(ring.width >= 2);
          }
        } finally {
          await p.close();
          await site.close();
        }
      });
    }
  }
});

test('keyboard: selecting a second desktop session focuses its open panel and Escape returns to that row', async () => {
  const site = await fakeSite();
  site.api.setList(() => json(200, inventory([session(1), session(2)])));
  site.api.setDetail((id) => json(200, sessionView(session(Number(id.slice(-4))))));
  const p = await openPage(browser, site.site.origin, { viewport: DESKTOP });
  const activeRow = () => p.page.evaluate(() => document.activeElement?.dataset?.sessionId ?? null);
  async function tabTo(id, key) {
    for (let i = 0; i < 40 && (await activeRow()) !== id; i++) await p.page.keyboard.press(key);
    assert.equal(await activeRow(), id, `${id} is reachable by ${key}`);
  }
  try {
    await waitFor(async () => (await readView(p.page)).groups.length > 0, { what: 'two-session list' });
    await tabTo('thr_web_0001', 'Tab');
    await p.page.keyboard.press('Enter');
    await waitFor(async () => (await readDetail(p.page))?.title === 'Synthetic web session 1', { what: 'first detail' });
    assert.equal(await p.page.locator('[data-part=detail] button[aria-label="Sessions — close panel"]').evaluate((el) => el === document.activeElement), true);
    await tabTo('thr_web_0002', 'Shift+Tab');
    assert.equal((await readDetail(p.page)).id, 'thr_web_0001', 'the first panel stays open while accessing the list');
    await p.page.keyboard.press('Enter');
    await waitFor(async () => (await readDetail(p.page))?.title === 'Synthetic web session 2', { what: 'second detail' });
    assert.equal((await readDetail(p.page)).modal, false, 'the second panel stays nonmodal');
    assert.equal(await p.page.locator('[data-part=detail] button[aria-label="Sessions — close panel"]').evaluate((el) => el === document.activeElement), true, 'selection moves focus into the already-open panel');
    await p.page.keyboard.press('Escape');
    await waitFor(async () => (await readDetail(p.page)) === null, { what: 'Escape closes the second panel' });
    await waitFor(async () => (await activeRow()) === 'thr_web_0002', { what: 'the close event restores the selected row' });
    assert.equal(await activeRow(), 'thr_web_0002', 'focus returns to the selected second row');
    assert.equal(await p.page.locator('main [data-session-id]').count(), 2, 'both session rows remain present');
  } finally {
    await p.close();
    await site.close();
  }
});

test('keyboard: switching to Fleets keeps focus there after details close', async () => {
  const p = await ready(DESKTOP);
  try {
    await open(p);
    await p.page.evaluate(() => {
      window.__detailClosed = false;
      document.querySelector('[data-part=detail]').addEventListener('close', () => {
        queueMicrotask(() => { window.__detailClosed = true; });
      }, { once: true });
    });
    const fleets = p.page.getByRole('button', { name: 'Fleets', exact: true });
    await fleets.focus();
    await p.page.keyboard.press('Enter');
    await waitFor(() => p.page.evaluate(() => window.__detailClosed), { what: 'detail close event handled' });
    assert.equal(await readDetail(p.page), null, 'the detail closes on navigation');
    assert.equal(await fleets.getAttribute('aria-pressed'), 'true', 'Fleets is selected');
    assert.equal(await fleets.evaluate((el) => document.activeElement === el), true, 'focus stays on Fleets');
    await p.page.keyboard.press('Enter');
    assert.equal(await fleets.getAttribute('aria-pressed'), 'true', 'another Enter keeps Fleets selected');
  } finally {
    await p.close();
  }
});

for (const viewport of [PHONE, DESKTOP]) {
  for (const close of ['Escape', 'Close']) {
    for (const rows of ['present', 'removed', 'empty']) {
      test(`close focus: ${rows} row, ${close}, ${viewport.width}px`, async () => {
        const { fx, state } = await composerSite();
        const p = await openThread(browser, fx, 2, { viewport, paused: true, stampReads: true });
        try {
          await waitFor(() => pageIdle(p.page), { what: 'initial reads consumed' });
          state.sessions = rows === 'present' ? [session(1), session(2), session(3)] : rows === 'removed' ? [session(1), session(3)] : [];
          await p.page.clock.runFor(10_000);
          await waitFor(async () => {
            const view = await readView(p.page);
            return JSON.stringify(view.groups.flatMap((g) => g.rows.map((r) => r.id)).sort()) === JSON.stringify(state.sessions.map((s) => s.id).sort());
          }, { what: 'refreshed rows' });
          await waitFor(async () => (await readDetail(p.page))?.noLongerListed === (rows !== 'present'), { what: 'refreshed detail listing state' });
          if (close === 'Escape') await p.page.keyboard.press('Escape');
          else await p.page.getByRole('button', { name: 'Sessions — close panel', exact: true }).click();
          // Native close runs before the parent's onClose clears the selected id.
          await waitFor(async () => (await p.page.locator('[data-part=detail]').getAttribute('data-session-id')) === null, { what: 'close handler finished' });
          assert.equal(await readDetail(p.page), null, 'detail is closed');
          const target = rows === 'present'
            ? p.page.locator(`main [data-session-id="${id(2)}"]`)
            : p.page.getByRole('button', { name: 'Sessions', exact: true });
          assert.equal(await target.evaluate((el) => document.activeElement === el), true, rows === 'present' ? 'focus returns to the original row' : 'focus returns to Sessions');
          assert.deepEqual(p.errors, [], 'no browser errors');
        } finally {
          await p.close();
          await fx.close();
        }
      });
    }
  }
}

test('screen-reader names: every row says its status word; the sheet or panel is named', async () => {
  const p = await ready(PHONE);
  try {
    const tree = await p.page.locator('main').ariaSnapshot();
    // Each row's own accessible name has its own status word (F9).
    for (const [id, word] of [
      ['thr_web_0001', 'error'],
      ['thr_web_0002', 'active'],
      ['thr_web_0003', 'idle'],
      ['thr_web_0004', 'syn-other'],
      ['thr_web_0005', 'unknown (missing field status)'],
    ]) {
      const name = await p.page.locator(`[data-session-id="${id}"]`).ariaSnapshot();
      assert.match(name, /^- button "/, `${id} is a button`);
      assert.ok(name.includes(` ${word}"`) || name.includes(` ${word} `), `${id}'s name has "${word}": ${name}`);
    }
    assert.doesNotMatch(tree, /\[~\]|\[x\]|\[-\]|\[\?\]/, 'the glyphs are not read out');
    await open(p);
    const name = await p.page.$eval('[data-part=detail]', (d) => document.getElementById(d.getAttribute('aria-labelledby') ?? '')?.textContent);
    assert.equal(name, 'Synthetic web session 2');
    mkdirSync(RESULTS_DIR, { recursive: true });
    writeFileSync(`${RESULTS_DIR}/v9-aria-list.txt`, `${tree}\n`);
    writeFileSync(`${RESULTS_DIR}/v9-aria-detail.txt`, `${await p.page.locator('[data-part=detail]').ariaSnapshot()}\n`);
  } finally {
    await p.close();
  }
});

test('axe finds no violation: list, gaps, sheet, panel and a failure state', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    const p = await ready(viewport);
    try {
      assert.deepEqual(await axe(p.page), [], `list at ${viewport.width}px`);
      await p.page.click('[data-part=coverage]');
      assert.deepEqual(await axe(p.page), [], `gaps at ${viewport.width}px`);
      await open(p);
      assert.deepEqual(await axe(p.page), [], `detail at ${viewport.width}px`);
    } finally {
      await p.close();
    }
  }
  const down = await fakeSite();
  down.api.setList(() => html(530, 'error code: 1033'));
  const q = await openPage(browser, down.site.origin, { viewport: PHONE });
  try {
    await waitFor(async () => (await readView(q.page)).connection === 'disconnected', { what: 'disconnected' });
    assert.deepEqual(await axe(q.page), [], 'disconnected');
  } finally {
    await q.close();
    await down.close();
  }
});
