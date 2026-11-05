// H0: synthetic browser evidence for local Home navigation, source honesty,
// one fleet lane/cache, and the existing composer owner-press gate.
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { DESKTOP, PHONE, launchBrowser, openPage, pageIdle, readDetail, waitFor } from '../support/browser.mjs';
import { button, outcome, posts, readComposer, type } from '../support/composer.mjs';
import { apiError, fakeApi, json } from '../support/fake-api.mjs';
import { contractExample } from '../support/fleet-graph-fixtures.ts';
import { fleetsEmpty, fleetsExample, fleetsLong, fleetsPartial } from '../support/fleet-fixtures.ts';
import { axe } from '../support/harness.mjs';
import { startSite } from '../support/serve.mjs';
import { inventory, preview, session, sessionView, T0 } from '../support/synthetic.ts';

let browser;
before(async () => { browser = await launchBrowser(); });
after(async () => { await browser?.close(); });
const TARGET = 'thr_web_0001';
const PREFIX = 'Answer for ticket #904 (spec #901):\n\n';
const rows = [
  session(1, { status: { known: 'active' } }),
  session(2),
  session(3, { status: { known: 'active' }, group: { kind: 'project', id: 'prj_web_0002', name: { known: 'Synthetic second project' } } }),
  session(4, { status: { known: 'error' } }),
];
async function fixture() {
  const api = fakeApi();
  const data = { fleets: JSON.parse(fleetsExample()), list: inventory(rows), fail: false, hold: false };
  data.fleets.orchestrator = TARGET; // Synthetic existing listed session; no new operation or contract.
  api.setList(() => data.fail ? apiError(502, 'read_failed', 'Synthetic inventory failure') : json(200, data.list));
  api.setDetail((id) => json(200, sessionView(rows.find((s) => s.id === id) ?? rows[0])));
  api.setPreview((id, mode) => json(200, preview(id, 'busy', mode)));
  const reads = [], held = [];
  let active = 0, maximum = 0;
  const site = await startSite((req, res, url) => {
    if (!url.pathname.startsWith('/api/v1/fleets')) return api.handler(req, res, url);
    reads.push(url.pathname);
    active++; maximum = Math.max(maximum, active);
    const send = () => {
      const reply = data.fail ? apiError(502, 'read_failed', 'Synthetic fleet failure') : json(200, url.pathname === '/api/v1/fleets' ? data.fleets : contractExample(2));
      res.writeHead(reply.status, reply.headers); res.end(reply.body, () => { active--; });
    };
    if (data.hold) held.push(send); else send();
  });
  return { api, data, site, reads, maximum: () => maximum, release: () => { data.hold = false; for (const send of held.splice(0)) send(); }, close: () => site.close() };
}
const idle = (page) => waitFor(() => pageIdle(page), { what: 'all response bodies consumed' });
const nav = (page, name) => page.getByRole('navigation', { name: 'Views', exact: true }).getByRole('button', { name, exact: true });
const answer = (page, ticket = 904) => page.getByRole('button', { name: `Answer #${ticket}`, exact: true });
/** Home: its tab where the bar shows it; on the phone (MD9) through the command dialog. */
async function goHome(page) {
  if (await nav(page, 'Home').isVisible()) return nav(page, 'Home').click();
  await page.getByRole('button', { name: /^Search or jump to…/ }).filter({ visible: true }).first().click();
  await page.getByRole('combobox', { name: 'Search navigation' }).fill('Go to Home');
  await page.keyboard.press('Enter');
}
async function home(p) {
  await goHome(p.page);
  await waitFor(() => p.page.locator('[data-part=needs-you] [data-ticket="904"]').count(), { what: 'Home decisions' });
  await idle(p.page);
}
async function open(fx, viewport = DESKTOP, paused = true) {
  const p = await openPage(browser, fx.site.origin, { viewport, clock: T0 + 30_000, paused, stampReads: true });
  await waitFor(() => p.page.locator('main [data-session-id]').count());
  await idle(p.page);
  return p;
}
for (const viewport of [DESKTOP, PHONE]) {
  test(`Home navigation, active subset, fleet detail and single composer at ${viewport.width}px`, async () => {
    const fx = await fixture(); const p = await open(fx, viewport, false); const page = p.page;
    try {
      assert.equal(await page.getByRole('heading', { name: 'Sessions', exact: true }).count(), 1, 'Sessions is still the initial entry');
      const destinations = await page.locator('.app-nav button').evaluateAll((bs) => bs.map((b) => b.getAttribute('aria-label') ?? b.innerText.trim().replace(/\s+/g, ' ')));
      assert.deepEqual(destinations, ['Cockpit', 'Home', 'Sessions', 'Fleets', 'Plan', 'Decisions', 'Loops', 'First hour', 'New thread']);
      if (viewport === PHONE) {
        const tabs = await page.locator('.app-nav button').evaluateAll((bs) => bs.filter((b) => b.getClientRects().length > 0).map((b) => b.innerText.trim().replace(/\s+/g, ' ')));
        assert.deepEqual(tabs, ['Sessions', 'Fleets', 'Plan', 'Decisions', 'New'], 'MD9: Cockpit, Home and Loops only off the phone bar');
      }
      await page.keyboard.press('Control+k');
      assert.equal(await page.getByRole('option').first().textContent(), 'Go to Home↵');
      await page.keyboard.press('Enter');
      await waitFor(() => page.locator('[data-part=needs-you] [data-ticket="904"]').count());
      await idle(page);
      assert.equal(await page.locator('.app-nav .nav-home').getAttribute('aria-pressed'), 'true');
      assert.equal(await page.locator('.session-placeholder').count(), 0);
      assert.equal(await page.locator('[data-part=detail][open]').count(), 0);
      assert.equal(await page.locator('textarea').count(), 0, 'Home adds no prompt body');
      assert.deepEqual(await page.locator('main h2').allTextContents(), ['Needs you', 'Fleets at a glance', 'Live now']);
      assert.deepEqual(await page.locator('[data-part=needs-you] ol [data-ticket]').evaluateAll((rs) => rs.map((r) => r.dataset.ticket)), ['904', '907']);
      assert.deepEqual(await page.locator('[data-part=home-live] [data-session-id]').evaluateAll((rs) => rs.map((r) => r.dataset.sessionId)), [TARGET, 'thr_web_0003']);
      assert.equal(await page.locator('[data-part=fleet-list] button[data-fleet]').count(), 2);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), viewport.width);
      if (viewport === PHONE) {
        await page.mouse.wheel(0, 1_200);
        await waitFor(async () => {
          const heading = await page.locator('#home-live-heading').boundingBox();
          const last = await page.locator('[data-part=home-live] .row').last().boundingBox();
          const tabs = await page.locator('.app-nav').boundingBox();
          return heading.y >= 56 && last.y + last.height <= tabs.y;
        }, { what: 'Live now heading and both rows readable above fixed tabs after normal scrolling' });
      }
      assert.deepEqual(await axe(page), []);
      for (const b of await page.locator('.app-nav button').filter({ visible: true }).all()) {
        const rect = await b.boundingBox(); assert.ok(rect.width >= 44 && rect.height >= 44);
      }
      assert.equal(p.requests.filter((r) => r.method !== 'GET').length, 0);
      await page.locator('[data-part=home-live] [data-session-id="thr_web_0003"]').click();
      await waitFor(async () => (await readDetail(page))?.id === 'thr_web_0003');
      assert.equal(await nav(page, 'Sessions').getAttribute('aria-pressed'), 'true');
      await page.getByRole('button', { name: 'Sessions — close panel', exact: true }).click();
      await home(p);
      await page.locator('[data-part=fleet-list] button[data-fleet="901"]').click();
      await waitFor(() => page.locator('.fleet-detail[data-fleet="901"]').count());
      assert.equal(await page.getByRole('heading', { name: '#901 Synthetic spec one', exact: true }).count(), 1);
      await page.getByRole('button', { name: 'All fleets', exact: true }).click();
      await idle(page);
      await answer(page).click();
      await waitFor(async () => (await readComposer(page))?.ready);
      assert.equal((await readComposer(page)).target, TARGET);
      assert.equal((await readComposer(page)).draft, PREFIX);
      assert.equal(await page.locator('textarea').count(), 1);
      await type(page, PREFIX + 'Synthetic: retain this answer.');
      await page.getByRole('button', { name: 'Sessions — close panel', exact: true }).click();
      assert.equal(await answer(page).evaluate((b) => document.activeElement === b), true);
      await answer(page, 907).click();
      await waitFor(async () => (await readComposer(page))?.ready);
      assert.equal((await readComposer(page)).draft, PREFIX + 'Synthetic: retain this answer.');
      assert.equal(posts(fx).length, 0, 'navigation, Answer, typing and switching decisions never send');
      assert.equal(fx.api.calls.length, 0);
      await button(page, 'Queue').click();
      await outcome(page, 'sent');
      assert.equal(posts(fx).length, 1);
      assert.equal(posts(fx)[0].text, PREFIX + 'Synthetic: retain this answer.');
      assert.equal(posts(fx)[0].mode, 'queue');
      assert.equal(fx.api.calls.length, 1);
      assert.equal(fx.api.calls[0].id, TARGET);
      assert.deepEqual(await p.csp(), []); assert.deepEqual(p.errors, []);
    } finally { await p.close(); await fx.close(); }
  });
}

test('Home and Fleets retain the same snapshot and lane through a held read, polling and visibility', async () => {
  const fx = await fixture(); const p = await open(fx); const page = p.page;
  try {
    await home(p);
    fx.data.hold = true;
    await page.getByRole('button', { name: 'Refresh fleets', exact: true }).click();
    await waitFor(() => fx.reads.length === 2);
    await nav(page, 'Fleets').click();
    assert.equal(await page.locator('[data-part=fleet-list] button[data-fleet]').count(), 2, 'cached list is immediately retained');
    await goHome(page);
    for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'Refresh fleets', exact: true }).dispatchEvent('click');
    await page.clock.runFor(50_000);
    assert.equal(fx.reads.length, 2, 'both views wait for the held fleet read');
    fx.release(); await waitFor(() => fx.reads.length === 3); await idle(page);
    assert.equal(fx.maximum(), 1);
    await page.clock.runFor(59_999); assert.equal(fx.reads.length, 3);
    await page.clock.runFor(1); await waitFor(() => fx.reads.length === 4); await idle(page);
    await page.evaluate(() => { Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' }); document.dispatchEvent(new Event('visibilitychange')); });
    await page.clock.runFor(120_000); assert.equal(fx.reads.length, 4);
    await page.evaluate(() => { Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' }); document.dispatchEvent(new Event('visibilitychange')); });
    await waitFor(() => fx.reads.length === 5); await idle(page);
    assert.equal(fx.maximum(), 1);
    assert.equal(p.requests.filter((r) => r.method !== 'GET').length, 0);
  } finally { fx.release(); await p.close(); await fx.close(); }
});

test('Home keeps partial, paginated, unread and failed source qualifications, then fresh zero', async () => {
  const fx = await fixture();
  fx.data.fleets = JSON.parse(fleetsPartial());
  fx.data.list = inventory(rows, { state: 'partial', offset: 4, limit: 4, matched: 20, gaps: [{ kind: 'timed_out', subject: null, detail: 'Synthetic gap: one session unread' }] });
  const p = await open(fx); const page = p.page;
  try {
    await goHome(page); await waitFor(() => page.locator('[data-part=needs-you-empty]').count()); await idle(page);
    assert.equal(await page.locator('[data-part=needs-you-empty]').getAttribute('data-kind'), 'unread');
    assert.match(await page.locator('[data-part=home-live]').innerText(), /Active sessions on this listed page · sessions 5–8 of 20/);
    assert.match(await page.locator('[data-part=home-live]').innerText(), /Partial · 1 gap.*read/s);
    assert.match(await page.locator('[data-part=home-live]').innerText(), /Synthetic gap: one session unread/);
    assert.match(await page.locator('[data-part=fleet-list]').innerText(), /partial list:/);
    assert.match(await page.locator('[data-part=fleet-list]').innerText(), /unread/);
    assert.equal(await page.getByText('Nothing needs you', { exact: true }).count(), 0);
    fx.data.fail = true;
    await page.getByRole('button', { name: 'Refresh fleets', exact: true }).click();
    await waitFor(() => page.locator('[data-part=fleet-screen] > [role=status] [data-notice=error]').count());
    await page.clock.runFor(70_001); await idle(page);
    await waitFor(() => page.locator('[data-part=home-live] [data-notice=error]').count());
    assert.equal(await page.locator('[data-part=fleet-list] button[data-fleet]').count(), 2);
    assert.equal(await page.locator('[data-part=home-live] [data-session-id]').count(), 2);
    assert.equal(await page.locator('[data-part=home-live] [data-part=stale]').count(), 1);
    assert.equal(await page.locator('[data-part=fleet-screen] > .page-head [data-part=stale]').count(), 1);
    fx.data.fail = false;
    fx.data.fleets = JSON.parse(fleetsEmpty());
    fx.data.fleets.coverage.state = 'partial';
    fx.data.fleets.reads[0].outcome = { state: 'failed', gap: 'command_failed', reason: 'Synthetic GitHub version unavailable' };
    fx.data.fleets.sources.github.version_tested = false;
    await page.getByRole('button', { name: 'Refresh fleets', exact: true }).click(); await idle(page);
    await waitFor(() => page.getByText('No Needs you items read: the snapshot is partial', { exact: true }).count());
    fx.data.fleets = JSON.parse(fleetsEmpty()); fx.data.list = inventory([]);
    await page.getByRole('button', { name: 'Refresh fleets', exact: true }).click();
    await page.locator('[data-part=home-live]').getByRole('button', { name: 'Retry', exact: true }).click();
    await idle(page);
    await waitFor(() => page.getByText('Nothing needs you', { exact: true }).count());
    assert.equal(await page.getByText('No active sessions', { exact: true }).count(), 1);
    assert.equal(p.requests.filter((r) => r.method !== 'GET').length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('Home wraps long and missing fields and does not truncate active rows; absent orchestrator cannot write', async () => {
  const fx = await fixture();
  fx.data.fleets = JSON.parse(fleetsLong());
  fx.data.list = inventory(Array.from({ length: 12 }, (_, i) => session(i + 1, { status: { known: 'active' }, title: i === 0 ? { unknown: 'synthetic missing title' } : { known: `Synthetic ${'unbroken'.repeat(24)} ${i}` } })));
  const p = await open(fx, PHONE, false); const page = p.page;
  try {
    await home(p);
    assert.equal(await page.locator('[data-part=home-live] [data-session-id]').count(), 12);
    assert.match(await page.locator('[data-part=home-live] [data-part=title]').first().textContent(), /unknown \(synthetic missing title\)/);
    assert.equal(await answer(page).isDisabled(), true);
    assert.match(await page.locator('[data-part=needs-you]').textContent(), /orchestrator not configured or not found/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), PHONE.width);
    assert.deepEqual(await axe(page), []);
    await nav(page, 'Sessions').click(); await goHome(page); await idle(page);
    await page.reload(); await idle(page);
    assert.equal(await page.getByRole('heading', { name: 'Sessions', exact: true }).count(), 1);
    assert.equal(p.requests.filter((r) => r.method !== 'GET').length, 0);
  } finally { await p.close(); await fx.close(); }
});

// Review R1 (#1739): from 900 px the fleet titles keep a readable width. Between 900 and 1199 px the
// rows stay stacked; from 1200 px each fleet is one line (title, counts, progress, merged).
test('Home fleet rows keep a readable title width at 900, 1200 and 1440 px', async () => {
  for (const [width, oneLine] of [[900, false], [1200, true], [1440, true]]) {
    const fx = await fixture(); const p = await open(fx, { width, height: 900 }, false); const page = p.page;
    try {
      await home(p);
      const geometry = await page.locator('[data-part=fleet-list] .fleet-row').evaluateAll((list) => list.map((row) => {
        const title = row.querySelector('[data-part=title]').getBoundingClientRect();
        return { title: title.width, titleHeight: title.height, row: row.getBoundingClientRect().height };
      }));
      assert.ok(geometry.length >= 2, `${width}px: fleet rows`);
      for (const g of geometry) {
        assert.ok(g.title >= 160, `${width}px: title gets ${g.title}px`);
        assert.ok(g.titleHeight <= 24, `${width}px: title wraps to ${g.titleHeight}px`);
        assert.ok(oneLine ? g.row <= 64 : g.row <= 112, `${width}px: row is ${g.row}px tall`);
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width);
    } finally { await p.close(); await fx.close(); }
  }
});
