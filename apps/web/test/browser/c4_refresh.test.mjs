// #128 proof plan (fixture evidence, never a live claim):
// S3-5: the shipped page reads each visible fleet view after 60,000 ms;
// hidden time starts no reads; a held read, navigation, repeated Refresh and
// pull gestures never overlap. Controls and notices prove errors honestly.
// Navigation: C1/C2 render the contract examples through the real api.ts seam,
// and a builder button opens the existing session detail. V/W are regression
// evidence, run by the full set. All clocks, payloads and requests are owned
// by the test. Automatic timing expectations are literal 60,000 ms.
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, openPage, pageIdle, PHONE, readDetail, waitFor } from '../support/browser.mjs';
import { apiError, fakeApi, json } from '../support/fake-api.mjs';
import { contractExample } from '../support/fleet-graph-fixtures.ts';
import { fleetsEmpty, fleetsExample, fleetsListFailed, fleetsPartial } from '../support/fleet-fixtures.ts';
import { startSite } from '../support/serve.mjs';
import { session, sessionView } from '../support/synthetic.ts';

const START = new Date('2027-01-15T08:00:00Z');
let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

// Fleet responders stay here: #128 owns c4_* tests, not the shared fake API.
export async function fleetSite() {
  const api = fakeApi();
  api.setDetail(() => json(200, sessionView(session(2))));
  const reads = [];
  const held = [];
  let hold = false;
  let respond = (path) => path === '/api/v1/fleets'
    ? { ...json(200, null), body: fleetsExample() }
    : json(200, contractExample(path.endsWith('/930') ? 3 : 2));
  let active = 0;
  let maximum = 0;
  const site = await startSite((req, res, url) => {
    if (!url.pathname.startsWith('/api/v1/fleets')) return api.handler(req, res, url);
    const entry = { path: url.pathname, headers: req.headers, ended: false };
    reads.push(entry);
    active++;
    maximum = Math.max(maximum, active);
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      active--;
      entry.ended = true;
    };
    res.on('close', finish);
    const send = () => {
      if (res.destroyed) return;
      const reply = respond(url.pathname);
      res.writeHead(reply.status, reply.headers);
      res.end(reply.body, finish);
    };
    if (hold) held.push(send); else send();
  });
  return { site, reads, maximum: () => maximum, hold: (v) => { hold = v; },
    respond: (fn) => { respond = fn; },
    release: () => { for (const send of held.splice(0)) send(); },
    close: () => site.close(),
  };
}

async function openFleets(fx, viewport = PHONE) {
  const p = await openPage(browser, fx.site.origin, { clock: START, paused: true, stampReads: true, viewport, hasTouch: true });
  await waitFor(() => pageIdle(p.page), { what: 'initial session read' });
  assert.equal(await p.page.getByRole('button', { name: 'Fleets', exact: true }).isVisible(), true, 'the page offers fleets navigation');
  await p.page.getByRole('button', { name: 'Fleets', exact: true }).click();
  await waitFor(() => fx.reads.length === 1, { what: 'the fleet list request' });
  await idle(p.page);
  return p;
}
const idle = (page) => waitFor(() => pageIdle(page), { what: 'every response consumed and its timers scheduled' });

// #844 proof plan (synthetic browser evidence): at both public viewports,
// clearing gaps hands the focused coverage toggle to Refresh fleets; focus
// moved before the refresh or while its answer waits stays on Sessions.
// Hold the automatic read and wait for its DOM commit, not elapsed real time.
for (const viewport of [PHONE, DESKTOP]) {
  for (const outcome of ['cleared', 'retained', 'failed']) {
    for (const moved of ['never', 'before refresh', 'during refresh']) {
      test(`C4 #844: coverage ${outcome} with focus moved ${moved} at ${viewport.width}px`, async () => {
        const fx = await fleetSite();
        fx.respond(() => ({ ...json(200, null), body: fleetsPartial() }));
        const p = await openFleets(fx, viewport);
        try {
          const toggle = p.page.locator('[data-part=fleets] button.cov');
          const sessions = p.page.getByRole('button', { name: 'Sessions', exact: true });
          await toggle.focus();
          await p.page.keyboard.press('Enter');
          await waitFor(async () => (await toggle.getAttribute('aria-expanded')) === 'true', { what: 'expanded coverage' });
          assert.equal(await toggle.evaluate((el) => el === document.activeElement), true);
          if (moved === 'before refresh') await sessions.focus();
          fx.respond(() => outcome === 'failed' ? apiError(502, 'read_failed', 'Synthetic fleet failure') : { ...json(200, null), body: outcome === 'cleared' ? fleetsExample() : fleetsPartial() });
          fx.hold(true);
          await p.page.clock.runFor(60_000);
          await waitFor(() => fx.reads.length === 2, { what: 'held automatic fleet refresh' });
          if (moved === 'during refresh') await sessions.focus();
          fx.hold(false); fx.release();
          await idle(p.page);
          await waitFor(async () => outcome === 'failed' ? p.page.locator('[data-notice=error]').isVisible() : (await p.page.locator('[data-part=fleet-screen]').getAttribute('data-snapshot-seq')) === '2', { what: 'fleet refresh committed' });
          assert.equal(await toggle.count(), outcome === 'cleared' ? 0 : 1);
          const expected = moved === 'never' ? 'Refresh fleets' : 'Sessions';
          const control = moved === 'never' && outcome !== 'cleared' ? toggle : p.page.getByRole('button', { name: expected, exact: true });
          assert.equal(await control.evaluate((el) => el === document.activeElement), true, 'focus stays on the coverage toggle or its named destination');
          assert.equal(fx.reads.length, 2, 'exactly one automatic refresh');
          assert.equal(fx.maximum(), 1);
          assert.deepEqual(await p.csp(), []);
          assert.deepEqual(p.errors, []);
        } finally { await p.close(); await fx.close(); }
      });
    }
  }
}

const stamps = (page) => page.evaluate(() => window.__reads.filter((r) => r.path.startsWith('/api/v1/fleets')));
const setHidden = (page, hidden) => page.evaluate((h) => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => h ? 'hidden' : 'visible' });
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => h });
  document.dispatchEvent(new Event('visibilitychange'));
}, hidden);
async function choose(page, spec = 901) {
  await page.click(`button[data-fleet="${spec}"]`);
  await waitFor(() => page.locator(`section[data-fleet="${spec}"]`).count(), { what: `fleet ${spec}` });
  await idle(page);
}
async function pull(page, { x = 100, y = 160, dx = 0, dy = 100, cancel = false } = {}) {
  await page.evaluate(({ x, y, dx, dy, cancel }) => {
    const el = document.querySelector('[data-part="fleet-screen"]');
    const touch = (clientX, clientY) => new Touch({ identifier: 1, target: el, clientX, clientY });
    el.dispatchEvent(new TouchEvent('touchstart', { bubbles: true, touches: [touch(x, y)] }));
    el.dispatchEvent(new TouchEvent('touchmove', { bubbles: true, cancelable: true, touches: [touch(x + dx, y + dy)] }));
    el.dispatchEvent(new TouchEvent(cancel ? 'touchcancel' : 'touchend', { bubbles: true, changedTouches: [touch(x + dx, y + dy)] }));
  }, { x, y, dx, dy, cancel });
}

test('C4 navigation uses C1 and C2, including phone fallback, wide graph and builder thread', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    const fx = await fleetSite();
    const p = await openFleets(fx, viewport);
    try {
      assert.equal(await p.page.locator('[data-part=fleets] > section').first().getAttribute('data-part'), 'needs-you');
      assert.equal(await p.page.locator('button[data-fleet]').count(), 2);
      await choose(p.page);
      assert.equal(await p.page.locator(viewport === PHONE ? '[data-fallback=too_wide]' : '[data-graph]').count(), 1);
      await p.page.click('[data-thread]');
      await waitFor(async () => (await readDetail(p.page))?.title === 'Synthetic web session 2', { what: 'builder session in the existing detail' });
      assert.deepEqual(await p.csp(), []);
      assert.deepEqual(p.errors, []);
      assert.ok(p.requests.filter((r) => new URL(r.url).pathname.startsWith('/api/v1/fleets')).every((r) => r.method === 'GET'));
    } finally { await p.close(); await fx.close(); }
  }
});

test('S3-5: list and detail refresh exactly after 60 seconds from the consumed answer', async () => {
  const fx = await fleetSite();
  const p = await openFleets(fx);
  try {
    for (const detail of [false, true]) {
      if (detail) await choose(p.page);
      const n = fx.reads.length;
      await p.page.clock.runFor(59_999);
      await idle(p.page);
      assert.equal(fx.reads.length, n, 'no early automatic read');
      await p.page.clock.runFor(1);
      await waitFor(() => fx.reads.length === n + 1, { what: 'minute refresh' });
      await idle(p.page);
      const log = await stamps(p.page);
      assert.equal(log.at(-1).at - log.at(-2).at, 60_000);
      assert.equal(log.at(-1).path, detail ? '/api/v1/fleets/901' : '/api/v1/fleets');
    }
    assert.equal(fx.maximum(), 1);
  } finally { await p.close(); await fx.close(); }
});

test('S3-5: hidden reads pause; returning starts exactly one, including while a read is held', async () => {
  const fx = await fleetSite();
  const p = await openFleets(fx);
  try {
    await setHidden(p.page, true);
    await p.page.clock.runFor(3_600_000);
    assert.equal(fx.reads.length, 1);
    fx.hold(true);
    await setHidden(p.page, false);
    await waitFor(() => fx.reads.length === 2, { what: 'one read on return' });
    await setHidden(p.page, true);
    await p.page.clock.runFor(30_000);
    await setHidden(p.page, false);
    await p.page.getByRole('button', { name: 'Refresh fleets', exact: true }).dispatchEvent('click');
    await pull(p.page);
    assert.equal(fx.reads.length, 2);
    fx.hold(false); fx.release(); await idle(p.page);
    await setHidden(p.page, true);
    await p.page.clock.runFor(3_600_000);
    assert.equal(fx.reads.length, 2);
    await setHidden(p.page, false);
    await waitFor(() => fx.reads.length === 3, { what: 'one new read' });
    await idle(p.page);
    assert.equal(fx.reads.length, 3);
    assert.equal(fx.maximum(), 1);
  } finally { await p.close(); await fx.close(); }
});

test('S3-5: held refresh, fleet navigation and repeated refresh share one lane', async () => {
  const fx = await fleetSite();
  const p = await openFleets(fx);
  try {
    fx.hold(true);
    await p.page.getByRole('button', { name: 'Refresh fleets', exact: true }).click();
    await waitFor(() => fx.reads.length === 2, { what: 'held list refresh' });
    await p.page.click('button[data-fleet="901"]');
    await p.page.clock.runFor(50_000);
    assert.equal(fx.reads.length, 2, 'the detail waits for the old list read, even after its late notice');
    fx.hold(false); fx.release();
    await waitFor(() => fx.reads.length === 3, { what: 'detail after list settles' });
    await idle(p.page);
    assert.equal(fx.reads[2].path, '/api/v1/fleets/901');
    assert.equal(await p.page.locator('section[data-fleet="901"]').count(), 1);
    fx.hold(true);
    await p.page.getByRole('button', { name: 'Refresh fleets', exact: true }).click();
    await waitFor(() => fx.reads.length === 4, { what: 'held detail refresh' });
    // Inject duplicate activations even though the mounted control is aria-disabled.
    for (let i = 0; i < 3; i++) await p.page.getByRole('button', { name: 'Refresh fleets', exact: true }).dispatchEvent('click');
    await pull(p.page);
    await p.page.getByRole('button', { name: 'All fleets', exact: true }).click();
    assert.equal(fx.reads.length, 4);
    fx.hold(false); fx.release();
    await waitFor(() => fx.reads.length === 5, { what: 'list after detail settles' });
    await idle(p.page);
    assert.equal(fx.reads[4].path, '/api/v1/fleets');
    assert.equal(fx.maximum(), 1);
  } finally { await p.close(); await fx.close(); }
});

// #525 fixture proof: a 100 px two-finger pull at the top adds no fleets read.
// This fails when both touch-count guards are removed from the built page.
test('S3-5: a two-finger pull never refreshes', async () => {
  const fx = await fleetSite();
  const p = await openFleets(fx);
  try {
    await p.page.evaluate(() => {
      window.scrollTo(0, 0);
      const el = document.querySelector('[data-part="fleet-screen"]');
      const touches = (y) => [1, 2].map((identifier) => new Touch({ identifier, target: el, clientX: 100 + identifier * 40, clientY: y }));
      el.dispatchEvent(new TouchEvent('touchstart', { bubbles: true, touches: touches(160) }));
      el.dispatchEvent(new TouchEvent('touchmove', { bubbles: true, cancelable: true, touches: touches(260) }));
      el.dispatchEvent(new TouchEvent('touchend', { bubbles: true, touches: [], changedTouches: touches(260) }));
    });
    await idle(p.page);
    assert.equal((await stamps(p.page)).length, 1, 'two-finger pull starts no fleet request in the page');
    assert.equal(fx.reads.length, 1, 'two-finger pull adds no fleet read');
  } finally { await p.close(); await fx.close(); }
});

test('S3-5: a pull refreshes once; horizontal, short, cancelled and scrolled gestures do not', async () => {
  const fx = await fleetSite();
  const p = await openFleets(fx);
  try {
    for (const gesture of [{ dy: 20 }, { dx: 180, dy: 90 }, { cancel: true }]) await pull(p.page, gesture);
    assert.equal(fx.reads.length, 1);
    await pull(p.page);
    await waitFor(() => fx.reads.length === 2, { what: 'one pull read' });
    await idle(p.page);
    await choose(p.page);
    await p.page.evaluate(() => window.scrollTo(0, 180));
    assert.ok(await p.page.evaluate(() => window.scrollY > 0));
    await pull(p.page);
    assert.equal(fx.reads.length, 3, 'no pull refresh away from the top');
    await p.page.evaluate(() => window.scrollTo(0, 0));
    await pull(p.page);
    await waitFor(() => fx.reads.length === 4, { what: 'detail pull read' });
    await idle(p.page);
    assert.equal(fx.maximum(), 1);
  } finally { await p.close(); await fx.close(); }
});

// #631 fixture proof: each manual refresh must consume its own response and
// render its exact failure word before checking the retained rows and moving
// the paused clock. Compare repeated normal and OPENWIZ_CPU_THROTTLE=4 runs;
// pageIdle alone proves body consumption, not React's DOM commit.
test('C4 retains the last snapshot with honest failure words and never retries faster than a minute', async () => {
  const fx = await fleetSite();
  const p = await openFleets(fx);
  try {
    for (const [reply, word] of [
      [apiError(503, 'busy', 'Synthetic busy', { 'Retry-After': '5' }), 'busy'],
      [apiError(502, 'read_failed', 'Synthetic fleet read failed'), 'error'],
      [json(401, {}), 'signed-out'],
      [{ ...json(200, null), body: '{"schema":"openwiz.fleet.v1","schema":"duplicate"}' }, 'error'],
    ]) {
      fx.respond(() => reply);
      const before = fx.reads.length;
      await p.page.getByRole('button', { name: 'Refresh fleets', exact: true }).click();
      await waitFor(() => fx.reads.length === before + 1 && fx.reads.at(-1).ended, { what: 'this refresh response' });
      await idle(p.page);
      await waitFor(async () => (await p.page.locator('[data-connection]').getAttribute('data-connection')) === word, { what: `rendered ${word} connection` });
      assert.equal(await p.page.locator('[data-connection]').getAttribute('data-connection'), word);
      assert.equal(await p.page.locator('button[data-fleet]').count(), 2, 'old rows remain');
      const n = fx.reads.length;
      // Hold any unexpected automatic read while advancing the paused clock.
      fx.hold(true);
      await p.page.clock.runFor(59_999);
      assert.equal((await stamps(p.page)).length, n, 'no early automatic request starts in the page');
      assert.equal(fx.reads.length, n, 'failed reads do not hammer GitHub');
      fx.hold(false); fx.release();
    }
  } finally { await p.close(); await fx.close(); }
});


for (const viewport of [PHONE, DESKTOP]) {
  test(`C4: returning to the fleet list keeps focus on a named control while its read waits (${viewport.width}px)`, async () => {
    const fx = await fleetSite();
    const p = await openFleets(fx, viewport);
    try {
      await choose(p.page);
      fx.hold(true);
      await p.page.getByRole('button', { name: 'All fleets', exact: true }).click();
      assert.equal(await p.page.evaluate(() => document.activeElement?.getAttribute('data-fleet')), '901', 'the retained row is already available for focus');
      fx.hold(false); fx.release(); await idle(p.page);
      assert.equal(await p.page.evaluate(() => document.activeElement?.getAttribute('data-fleet')), '901');
    } finally { await p.close(); await fx.close(); }
  });
}

// #720: observe the rendered replacement, not just the consumed HTTP body.
// These existing synthetic envelopes remove the cached row on a successful
// response, either with complete empty data or an honestly partial snapshot.
for (const viewport of [PHONE, DESKTOP]) {
  for (const [snapshot, body] of [['empty', fleetsEmpty], ['partial', fleetsListFailed]]) {
    for (const [move, keys, row] of [['stay', [], '901'], ['next', ['Tab'], '930'], ['back', ['Tab', 'Shift+Tab'], '901'], ['sessions', [], null]]) {
      test(`C4 return focus: removed row, ${snapshot}, move=${move} (${viewport.width}px)`, async () => {
        const fx = await fleetSite();
        const p = await openFleets(fx, viewport);
        try {
          await choose(p.page);
          fx.hold(true);
          await p.page.getByRole('button', { name: 'All fleets', exact: true }).click();
          await waitFor(() => fx.reads.length === 3, { what: 'held list return' });
          assert.equal(await p.page.evaluate(() => document.activeElement?.getAttribute('data-fleet')), '901');
          if (move === 'sessions') await p.page.getByRole('button', { name: 'Sessions', exact: true }).focus();
          for (const key of keys) await p.page.keyboard.press(key);
          if (row) assert.equal(await p.page.evaluate(() => document.activeElement?.getAttribute('data-fleet')), row);
          fx.respond(() => ({ ...json(200, null), body: body() }));
          fx.hold(false); fx.release();
          await waitFor(() => p.page.locator('[data-part=fleets-empty]').count(), { what: 'rendered list without the cached row' });
          await idle(p.page);
          assert.equal(await p.page.locator('button[data-fleet]').count(), 0);
          const target = p.page.getByRole('button', { name: move === 'sessions' ? 'Sessions' : 'Refresh fleets', exact: true });
          assert.equal(await target.evaluate((el) => document.activeElement === el), true, 'the named control owns focus');
          assert.equal(fx.reads.length, 3);
          assert.equal(fx.maximum(), 1);
          assert.deepEqual(p.errors, []);
        } finally { await p.close(); await fx.close(); }
      });
    }
  }
}

test('C4: returning to a list whose next read fails retains its last snapshot', async () => {
  const fx = await fleetSite();
  const p = await openFleets(fx);
  try {
    await choose(p.page);
    fx.respond(() => apiError(502, 'read_failed', 'Synthetic failed return'));
    await p.page.getByRole('button', { name: 'All fleets', exact: true }).click();
    await idle(p.page);
    assert.equal(await p.page.locator('[data-notice=error]').count(), 1);
    assert.equal(await p.page.locator('button[data-fleet]').count(), 2);
  } finally { await p.close(); await fx.close(); }
});

test('C4: a delayed list response never takes focus after the user moved it', async () => {
  const fx = await fleetSite();
  const p = await openFleets(fx);
  try {
    await choose(p.page);
    fx.hold(true);
    await p.page.getByRole('button', { name: 'All fleets', exact: true }).click();
    await waitFor(() => fx.reads.length === 3, { what: 'held list return' });
    await p.page.getByRole('button', { name: 'Sessions', exact: true }).focus();
    fx.hold(false); fx.release(); await idle(p.page);
    assert.equal(await p.page.evaluate(() => document.activeElement?.textContent), 'Sessions');
  } finally { await p.close(); await fx.close(); }
});

test('C4: leaving and reopening fleets waits for its old read and retains its last snapshot', async () => {
  const fx = await fleetSite();
  const p = await openFleets(fx);
  try {
    fx.hold(true);
    await p.page.getByRole('button', { name: 'Refresh fleets', exact: true }).click();
    await waitFor(() => fx.reads.length === 2, { what: 'held fleet refresh' });
    await p.page.getByRole('button', { name: 'Sessions', exact: true }).click();
    await p.page.getByRole('button', { name: 'Fleets', exact: true }).click();
    await p.page.clock.runFor(50_000);
    assert.equal(fx.reads.length, 2, 'reopening waits for the original read');
    fx.respond(() => apiError(502, 'read_failed', 'Synthetic failed screen return'));
    fx.hold(false); fx.release();
    await waitFor(() => fx.reads.length === 3, { what: 'one read on reopening' });
    await idle(p.page);
    assert.equal(fx.maximum(), 1);
    assert.equal(await p.page.locator('[data-notice=error]').count(), 1);
    assert.equal(await p.page.locator('button[data-fleet]').count(), 2, 'the earlier list stays visible');
  } finally { await p.close(); await fx.close(); }
});
