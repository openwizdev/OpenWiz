// S3-6 (#129), fixture evidence: HTTP retries and provider calls are counted
// separately. All expected IDs/text come from synthetic literals.
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, openPage, pageIdle, PHONE, waitFor } from '../support/browser.mjs';
import { button, outcome, posts, readComposer, TEXT, type } from '../support/composer.mjs';
import { DROP, fakeApi, json } from '../support/fake-api.mjs';
import { contractExample } from '../support/fleet-graph-fixtures.ts';
import { fleetsExample } from '../support/fleet-fixtures.ts';
import { startSite } from '../support/serve.mjs';
import { DELIVERIES, inventory, outcome as result, preview, report, session, sessionView } from '../support/synthetic.ts';

const TARGET = 'thr_web_0002';
const PREFIX = 'Answer for ticket #904 (spec #901):\n\n';
const START = new Date('2027-01-15T08:00:00Z');
let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

async function site(target = TARGET) {
  const api = fakeApi();
  // The orchestrator need not be on the current inventory page.
  api.setList(() => json(200, inventory([session(1)])));
  api.setDetail((id) => json(200, sessionView(session(id === TARGET ? 2 : 1))));
  api.setPreview((id, mode) => json(200, preview(id, 'idle', mode)));
  const doc = JSON.parse(fleetsExample());
  if (target !== undefined) doc.orchestrator = target;
  const web = await startSite((req, res, url) => {
    if (!['/api/v1/fleets', '/api/v1/fleets/901'].includes(url.pathname)) return api.handler(req, res, url);
    const detail = contractExample(2);
    if (target !== undefined) detail.orchestrator = target;
    const reply = json(200, url.pathname === '/api/v1/fleets' ? doc : detail);
    res.writeHead(reply.status, reply.headers);
    res.end(reply.body);
  });
  return { api, site: web, doc, close: () => web.close() };
}
async function fleets(p) {
  await waitFor(() => pageIdle(p.page), { what: 'the page reads consumed' });
  await p.page.getByRole('button', { name: 'Fleets', exact: true }).click();
  await waitFor(() => p.page.locator('[data-part=needs-you] [data-ticket="904"]').count(), { what: 'needs you rows' });
}
async function open(fx, viewport = PHONE) {
  const p = await openPage(browser, fx.site.origin, { clock: START, paused: true, stampReads: true, viewport });
  await fleets(p);
  return p;
}
const answer = (page, ticket = 904) => page.getByRole('button', { name: `Answer #${ticket}`, exact: true });
async function answering(page) {
  assert.equal(await answer(page).count(), 1, 'each item offers Answer');
  await answer(page).click();
  await waitFor(async () => (await readComposer(page))?.target === TARGET && (await readComposer(page)).ready, { what: 'orchestrator composer' });
}
const sent = (tid, b) => ({ after: DROP, report: report(tid, b.op_id, b.mode, b.text, result(DELIVERIES.sent)) });

test('S3-6: each Answer opens the existing phone/desktop panel, prefilled, without sending; closing returns focus', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    const fx = await site();
    const p = await open(fx, viewport);
    try {
      await answering(p.page);
      const c = await readComposer(p.page);
      assert.equal(c.draft, PREFIX);
      assert.equal(c.off, null, 'verified orchestrator works outside the current inventory page');
      assert.equal(await p.page.locator('[data-part=composer]').count(), 1);
      assert.equal(await p.page.locator('dialog').count(), 1);
      assert.equal(await p.page.locator('[data-part=detail]').evaluate((d) => d.matches(':modal')), viewport === PHONE);
      assert.equal(posts(fx).length, 0);
      await p.page.getByRole('button', { name: 'Sessions — close panel', exact: true }).click();
      await waitFor(() => answer(p.page).evaluate((b) => document.activeElement === b), { what: 'focus returned to Answer' });
      await answer(p.page, 907).click();
      await waitFor(async () => (await readComposer(p.page))?.ready, { what: 'the next answer panel' });
      assert.equal((await readComposer(p.page)).draft, 'Answer for ticket #907 (spec #901):\n\n', 'another item replaces an untouched prefill');
      assert.equal(posts(fx).length, 0);
      assert.equal(await p.page.getByRole('button', { name: /approve/i }).count(), 0);
    } finally { await p.close(); await fx.close(); }
  }
});

// Fleet detail reuses the same owner decision and composer path as the list.
test('fleet detail: Answer preserves its prefill, no-send and return-focus behaviour at both widths', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    const fx = await site();
    const p = await open(fx, viewport);
    try {
      await p.page.locator('button[data-fleet="901"]').click();
      await waitFor(() => p.page.locator('.fleet-detail[data-fleet="901"]').count(), { what: 'fleet detail' });
      await waitFor(() => pageIdle(p.page), { what: 'fleet detail read consumed' });
      assert.equal(await p.page.getByRole('heading', { name: '#901 Synthetic spec one', exact: true }).count(), 1);
      assert.equal(await p.page.locator('.fleet-detail [data-part=progress]').textContent(), '1 of 9 merged');
      assert.deepEqual(await p.page.locator('[data-state-group]').evaluateAll((groups) => groups.map((g) => g.getAttribute('data-state-group'))), ['ready', 'building', 'in_review', 'changes_requested', 'merged', 'held', 'blocked', 'unknown']);
      assert.equal(await p.page.locator(viewport === PHONE ? '[data-fallback=too_wide]' : '[data-graph]').count(), 1);
      assert.equal(await p.page.evaluate(() => document.documentElement.scrollWidth), viewport.width);
      await answering(p.page);
      assert.equal((await readComposer(p.page)).draft, PREFIX);
      assert.equal(posts(fx).length, 0);
      await p.page.getByRole('button', { name: 'Sessions — close panel', exact: true }).click();
      await waitFor(() => answer(p.page).evaluate((b) => document.activeElement === b), { what: 'focus returned to Answer' });
      assert.deepEqual(await p.csp(), []);
      assert.deepEqual(p.errors, []);
    } finally { await p.close(); await fx.close(); }
  }
});

test('R1: a restored untouched prefill switches items, but an owner-edited draft survives', async () => {
  const fx = await site();
  const p = await open(fx);
  try {
    await answering(p.page);
    await p.page.reload();
    await fleets(p);
    await answer(p.page, 907).click();
    await waitFor(async () => (await readComposer(p.page))?.ready, { what: 'restored answer panel' });
    const next = 'Answer for ticket #907 (spec #901):\n\n';
    assert.equal((await readComposer(p.page)).draft, next, 'a reload does not make the old prefill an owner edit');
    await type(p.page, next + TEXT);
    await p.page.getByRole('button', { name: 'Sessions — close panel', exact: true }).click();
    await answering(p.page);
    assert.equal((await readComposer(p.page)).draft, next + TEXT, 'the owner’s text stays when answering another item');
    assert.equal(posts(fx).length, 0, 'switching items and reloading never send');
    await button(p.page, 'Send').click();
    await outcome(p.page, 'sent');
    assert.equal(posts(fx).length, 1);
    assert.equal(posts(fx)[0].text, next + TEXT);
    assert.equal(fx.api.calls.length, 1);
  } finally { await p.close(); await fx.close(); }
});

test('R1: an unresolved send of just the prefill keeps its text and op id on another item', async () => {
  const fx = await site();
  fx.api.setSend(sent);
  const p = await open(fx);
  try {
    await answering(p.page);
    await button(p.page, 'Send').click();
    await outcome(p.page, 'uncertain');
    await p.page.getByRole('button', { name: 'Sessions — close panel', exact: true }).click();
    await answer(p.page, 907).click();
    await waitFor(async () => (await readComposer(p.page))?.ready, { what: 'unresolved answer reopened' });
    const c = await readComposer(p.page);
    assert.equal(c.draft, PREFIX, 'an unresolved attempt remains bound to its original text');
    assert.equal(c.readOnly, true);
    await button(p.page, 'Try again').click();
    await outcome(p.page, 'sent');
    assert.equal(posts(fx).length, 2);
    assert.equal(posts(fx)[1].op_id, posts(fx)[0].op_id);
    assert.equal(posts(fx)[1].text, PREFIX);
    assert.equal(fx.api.calls.length, 1);
  } finally { await p.close(); await fx.close(); }
});

test('S3-6: double clicks and held keyboard sends dispatch one operation and preserve focus', async () => {
  const fx = await site();
  fx.api.hold('send');
  const p = await open(fx, DESKTOP);
  try {
    await answering(p.page);
    await type(p.page, PREFIX + TEXT);
    await button(p.page, 'Send').dblclick();
    await p.page.locator('[data-part=composer] textarea').press('Control+Enter');
    await waitFor(() => fx.api.held('send') === 1, { what: 'one held answer' });
    fx.api.release('send');
    await outcome(p.page, 'sent');
    assert.equal(posts(fx).length, 1);
    assert.equal(fx.api.calls.length, 1);
    assert.equal(fx.api.calls[0].id, TARGET);
    assert.equal(posts(fx)[0].text, PREFIX + TEXT);
    await type(p.page, PREFIX + 'A second deliberate draft');
    await button(p.page, 'Send').focus();
    await p.page.keyboard.down('Enter');
    await waitFor(() => fx.api.held('send') === 1, { what: 'the second draft held' });
    fx.api.release('send');
    await waitFor(() => posts(fx).length === 2 && fx.api.log.filter((e) => e.kind === 'send').every((e) => e.endedAt !== null), { what: 'two complete answer requests' });
    await outcome(p.page, 'sent');
    for (let i = 0; i < 8; i++) await p.page.keyboard.down('Enter');
    await p.page.clock.runFor(1_000);
    assert.equal(posts(fx).length, 2);
    assert.equal(fx.api.calls.length, 2, 'one call for each deliberately edited draft');
    assert.equal(await p.page.locator('[data-part=composer]').evaluate((c) => c.contains(document.activeElement)), true, 'focus stays in the composer');
    await p.page.keyboard.up('Enter');
  } finally { await p.close(); await fx.close(); }
});

test('S3-6: lost acknowledgement, fleet refresh, reload and copied-tab retries reuse the op id and one provider call', async () => {
  const fx = await site();
  fx.api.setSend(sent);
  const p = await open(fx);
  try {
    await answering(p.page);
    await type(p.page, PREFIX + TEXT);
    await button(p.page, 'Send').click();
    assert.equal((await outcome(p.page, 'uncertain')).draft, PREFIX + TEXT);
    await p.page.getByRole('button', { name: 'Sessions — close panel', exact: true }).click();
    await p.page.getByRole('button', { name: 'Refresh fleets', exact: true }).click();
    await waitFor(() => pageIdle(p.page), { what: 'fleet refresh consumed' });
    await answering(p.page);
    assert.equal((await readComposer(p.page)).draft, PREFIX + TEXT);
    assert.equal(posts(fx).length, 1, 'refresh and Answer never send');
    await p.page.reload();
    await fleets(p);
    await answering(p.page);
    const c = await outcome(p.page, 'uncertain');
    assert.equal(c.draft, PREFIX + TEXT);
    assert.equal(c.readOnly, true);
    const storage = await p.page.evaluate(() => Object.entries(sessionStorage));
    const copy = await p.context.newPage();
    await copy.addInitScript((rows) => { if (sessionStorage.length === 0) for (const [k, v] of rows) sessionStorage.setItem(k, v); }, storage);
    // The clock belongs to the context; the copied tab inherits its pause.
    await copy.goto(fx.site.origin);
    await waitFor(() => copy.locator('main [data-session-id]').count(), { what: 'copied tab inventory' });
    await copy.getByRole('button', { name: 'Fleets', exact: true }).click();
    await waitFor(() => copy.locator('[data-part=needs-you] [data-ticket="904"]').count(), { what: 'copied tab needs-you rows' });
    await answering(copy);
    await outcome(copy, 'uncertain');
    await button(p.page, 'Try again').click();
    await button(copy, 'Try again').click();
    await outcome(p.page, 'sent');
    await outcome(copy, 'sent');
    await waitFor(() => posts(fx).length === 3 && fx.api.log.filter((e) => e.kind === 'send').every((e) => e.endedAt !== null), { what: 'all replay responses' });
    assert.equal(new Set(posts(fx).map((b) => b.op_id)).size, 1);
    assert.equal(fx.api.calls.length, 1);
    assert.equal((await readComposer(p.page)).live, 'status');
  } finally { await p.close(); await fx.close(); }
});

test('C5: absent target or refused browser storage never sends', async () => {
  const fx = await site();
  delete fx.doc.orchestrator;
  const p = await open(fx);
  try {
    assert.equal(await answer(p.page).count(), 1);
    assert.equal(await answer(p.page).isDisabled(), true);
    assert.match(await p.page.locator('[data-part=needs-you]').textContent(), /orchestrator.*not configured|orchestrator.*not found/i);
    assert.equal(posts(fx).length, 0);
    fx.doc.orchestrator = TARGET;
    await p.page.getByRole('button', { name: 'Refresh fleets', exact: true }).click();
    await waitFor(() => pageIdle(p.page), { what: 'target read' });
    await p.page.addInitScript(() => { Storage.prototype.setItem = () => { throw new DOMException('quota', 'QuotaExceededError'); }; });
    await p.page.reload();
    await fleets(p);
    await answering(p.page);
    await type(p.page, TEXT);
    const c = await readComposer(p.page);
    assert.match(c.off, /can’t be saved/);
    await p.page.locator('[data-part=composer] textarea').press('Control+Enter');
    assert.equal(posts(fx).length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('C5: a refresh that withdraws the configured target disables the open answer', async () => {
  for (const listed of [false, true]) {
    const fx = await site();
    if (listed) fx.api.setList(() => json(200, inventory([session(1), session(2)])));
    const p = await open(fx, DESKTOP);
    try {
      await answering(p.page);
      await type(p.page, TEXT);
      // Observe every committed DOM state, including the one before passive effects.
      await p.page.evaluate(() => {
        window.__withdrawal = { enabledSend: false };
        const observer = new MutationObserver(() => {
          const answer = document.querySelector('[aria-label="Answer #904"]');
          const send = document.querySelector('[data-part=composer] [data-action=send] button');
          if (answer?.disabled && send && !send.disabled && send.getAttribute('aria-disabled') !== 'true') {
            window.__withdrawal.enabledSend = true;
          }
        });
        observer.observe(document.body, { attributes: true, childList: true, subtree: true });
        window.__withdrawal.observer = observer;
      });
      delete fx.doc.orchestrator;
      await p.page.getByRole('button', { name: 'Refresh fleets', exact: true }).click();
      await waitFor(() => pageIdle(p.page), { what: 'withdrawn target read consumed' });
      assert.equal(await answer(p.page).isDisabled(), true);
      assert.equal(await button(p.page, 'Send').isDisabled(), true, 'a previous snapshot is no longer authority to send');
      assert.equal(await p.page.evaluate(() => {
        window.__withdrawal.observer.disconnect();
        return window.__withdrawal.enabledSend;
      }), false, 'no committed withdrawn snapshot leaves Send enabled');
      await button(p.page, 'Send').click({ force: true });
      assert.equal(posts(fx).length, 0);
      await p.page.getByRole('button', { name: 'Sessions — close panel', exact: true }).click();
      await waitFor(() => p.page.getByRole('button', { name: 'Refresh fleets', exact: true }).evaluate((b) => document.activeElement === b), { what: 'focus returned to Refresh fleets' });
    } finally { await p.close(); await fx.close(); }
  }
});

test('C5: replacing the verified target disables the old open answer and preserves its draft', async () => {
  const fx = await site();
  const p = await open(fx, DESKTOP);
  try {
    await answering(p.page);
    await type(p.page, TEXT);
    assert.equal(await button(p.page, 'Send').isDisabled(), false);
    fx.doc.orchestrator = 'thr_web_0003';
    await p.page.getByRole('button', { name: 'Refresh fleets', exact: true }).click();
    await waitFor(async () => (await p.page.locator('[data-part=fleet-screen]').getAttribute('data-snapshot-seq')) === '2', { what: 'replacement target snapshot committed' });
    await waitFor(() => pageIdle(p.page), { what: 'replacement target read consumed' });
    assert.equal(await answer(p.page).isDisabled(), false, 'the replacement remains a valid answer target');
    assert.equal(await button(p.page, 'Send').isDisabled(), true, 'the old target loses authority');
    const c = await readComposer(p.page);
    assert.equal(c.target, TARGET);
    assert.equal(c.draft, TEXT);
    assert.equal(posts(fx).length, 0, 'refresh never sends');
    assert.equal(fx.api.calls.length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('C5: closing an answer whose item disappeared returns focus to Refresh fleets', async () => {
  const fx = await site();
  const p = await open(fx, DESKTOP);
  try {
    await answering(p.page);
    fx.doc.data.needs_you = { known: [] };
    await p.page.getByRole('button', { name: 'Refresh fleets', exact: true }).click();
    await waitFor(() => pageIdle(p.page), { what: 'removed item read consumed' });
    assert.equal(await answer(p.page).count(), 0);
    await p.page.getByRole('button', { name: 'Sessions — close panel', exact: true }).click();
    await waitFor(() => p.page.getByRole('button', { name: 'Refresh fleets', exact: true }).evaluate((b) => document.activeElement === b), { what: 'focus returned to Refresh fleets' });
    assert.equal(posts(fx).length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('clock setup: paused startup survives elapsed installation time and copied tabs inherit it', async () => {
  let context;
  const delayedSetup = {
    async newContext(options) {
      context = await browser.newContext(options);
      const newPage = context.newPage.bind(context);
      context.newPage = async () => {
        const page = await newPage();
        const install = page.clock.install.bind(page.clock);
        const pauseAt = page.clock.pauseAt.bind(page.clock);
        let paused = false;
        page.clock.pauseAt = async (...args) => {
          await pauseAt(...args);
          paused = true;
        };
        page.clock.install = async (...args) => {
          await install(...args);
          // Model elapsed setup time only while the fake clock is running.
          if (!paused) await page.clock.runFor(1_000);
        };
        return page;
      };
      return context;
    },
  };
  try {
    const p = await openPage(delayedSetup, 'about:blank', { path: '', clock: START, paused: true });
    assert.deepEqual(
      await p.page.evaluate(() => [Date.now(), performance.timeOrigin, performance.now()]),
      [START.getTime(), START.getTime(), 0],
    );
    await p.page.evaluate(() => {
      window.fired = false;
      setTimeout(() => { window.fired = true; }, 10);
    });
    await p.page.clock.runFor(9);
    assert.equal(await p.page.evaluate(() => window.fired), false);
    await p.page.clock.runFor(1);
    assert.equal(await p.page.evaluate(() => window.fired), true);
    assert.equal(await p.page.evaluate(() => Date.now()), START.getTime() + 10);
    const copy = await p.context.newPage();
    await copy.goto('about:blank');
    assert.equal(await copy.evaluate(() => Date.now()), START.getTime() + 10);
  } finally { await context?.close(); }
});
