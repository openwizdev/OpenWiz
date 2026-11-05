// PA4/PA5 client fixture journey. PC CI only; synthetic API currentness and
// access scripts do not establish installed authority or real phone behavior.
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { DESKTOP, launchBrowser, openPage, pageIdle, PHONE, waitFor } from '../support/browser.mjs';
import { DROP, json } from '../support/fake-api.mjs';
import { DELIVERIES, outcome, report } from '../support/synthetic.ts';
import { notificationSite, TARGET, TOKEN } from '../fixtures/notification-target/site.mjs';
// #2272: the existing card sends one contextual message. Literal, written
// independently from the decisions contract; never built by the code under test.
const MESSAGE = 'openwiz decision answer v1\n{"subject":{"repository":"synthetic-owner/synthetic-repo","kind":"issue","number":901},"comment_id":902,"request_id":"synthetic-request","request_kind":"spec_confirmation","fingerprint":"' + 'a'.repeat(64) + '","spec":901}\n\nconfirm spec #901';
let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());
const landing = (page) => page.locator('[data-part=notification-target]');
const card = (page) => page.locator('[data-comment="902"]');
async function opened(fx, viewport = PHONE) {
  const p = await openPage(browser, fx.site.origin, { path: `/#notification=${TOKEN}`, viewport, clock: new Date(fx.now), paused: true, stampReads: true });
  await waitFor(async () => (await landing(p.page).getAttribute('data-ready')) === 'true', { what: 'exact target resolution' });
  await waitFor(() => pageIdle(p.page), { what: 'navigation reads consumed' });
  return p;
}

test('PA4 landing selects exactly one stable card; refresh/reorder/missing never substitute, both widths', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    const fx = await notificationSite();
    const p = await opened(fx, viewport);
    try {
      await card(p.page).waitFor({ state: 'visible' });
      const heading = await landing(p.page).getByRole('heading', { name: 'Notification', exact: true }).boundingBox();
      assert.ok(heading && heading.x >= 16, 'phone content keeps the accepted inset');
      assert.deepEqual(await p.page.locator('[data-comment]').evaluateAll((items) => items.map((item) => item.dataset.comment)), ['902']);
      const other = structuredClone(fx.doc.items[0]);
      other.comment_id = 900; other.request.id = 'synthetic-other';
      fx.doc.items.unshift(other);
      await p.page.locator('[data-part=decisions-refresh]').click();
      await waitFor(() => pageIdle(p.page), { what: 'reordered read consumed' });
      assert.equal(await p.page.locator('[data-comment="900"]').count(), 0);
      assert.equal(await card(p.page).count(), 1);
      fx.doc.items = [other];
      fx.result.state = 'missing';
      await p.page.locator('[data-part=decisions-refresh]').click();
      await waitFor(async () => (await landing(p.page).getAttribute('data-state')) === 'Missing', { what: 'missing exact card' });
      assert.equal(await p.page.locator('[data-comment]').count(), 0);
      assert.equal(fx.api.calls.length, 0);
      assert.equal(fx.api.creates.length, 0);
      assert.deepEqual(p.errors, []);
    } finally { await p.close(); await fx.close(); }
  }
});

test('PA4 changed/resolved/missing/ambiguous/unread references never fetch another card or perform work', async () => {
  for (const state of ['changed', 'resolved', 'missing', 'ambiguous', 'unread']) {
    const fx = await notificationSite({ state });
    const p = await opened(fx);
    try {
      assert.equal(await landing(p.page).getAttribute('data-state'), state[0].toUpperCase() + state.slice(1));
      assert.equal(await p.page.locator('[data-comment]').count(), 0);
      assert.equal(fx.decisionReads, 0);
      await p.page.reload();
      await waitFor(async () => (await landing(p.page).getAttribute('data-ready')) === 'true', { what: 'reloaded exact target' });
      await landing(p.page).getByRole('button', { name: 'Dismiss', exact: true }).click();
      assert.equal(await landing(p.page).count(), 0);
      assert.equal(fx.api.calls.length, 0);
      assert.equal(fx.api.creates.length, 0);
    } finally { await p.close(); await fx.close(); }
  }
});

test('PA5 denied/expired access hides cached details; reconnect reads without sending', async () => {
  const fx = await notificationSite();
  const p = await opened(fx);
  try {
    await card(p.page).waitFor({ state: 'visible' });
    for (const status of [401, 403]) {
      fx.targetReply = json(status, { schema: 'openwiz.notifications.v1', record: { target_result: fx.result } });
      await landing(p.page).locator('[data-part=notification-refresh]').click();
      await waitFor(async () => (await landing(p.page).getAttribute('data-state')) === (status === 401 ? 'Signed out' : 'Access refused'), { what: 'access refusal' });
      assert.equal(await p.page.locator('[data-comment]').count(), 0);
      assert.equal(await p.page.getByText('Keep the synthetic sample narrow.', { exact: true }).count(), 0);
      fx.targetReply = null;
      await landing(p.page).locator('[data-part=notification-refresh]').click();
      await card(p.page).waitFor({ state: 'visible' });
    }
    assert.equal(fx.api.calls.length, 0);
    assert.equal(fx.api.creates.length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('PA4 a separately explicit risky answer uses the existing card and sends exactly once across reload', async () => {
  const fx = await notificationSite({ risky: true });
  const p = await opened(fx);
  try {
    const c = card(p.page);
    await c.waitFor({ state: 'visible' });
    await c.getByRole('button', { name: 'Confirm spec #901, sends confirm spec #901', exact: true }).click();
    await c.locator('[data-part=arm-note]').waitFor({ state: 'visible' });
    assert.equal(await c.locator('[data-part=arm-note]').textContent(), 'This is about a live step. Send “confirm spec #901” with request and revision context to the orchestrator?');
    assert.equal(fx.api.calls.length, 0);
    await c.getByRole('button', { name: 'Yes, confirm spec #901', exact: true }).click();
    const send = c.locator('[data-part=send]');
    await waitFor(async () => (await send.getAttribute('aria-disabled')) === null, { what: 'existing guarded preview' });
    await send.dblclick();
    await waitFor(async () => (await c.locator('[data-part=outcome]').getAttribute('data-state')) === 'sent', { what: 'existing once-only answer outcome' });
    assert.deepEqual(fx.api.calls.map((call) => [call.id, call.text]), [[TARGET, MESSAGE]]);
    await p.page.reload();
    await card(p.page).waitFor({ state: 'visible' });
    await waitFor(() => pageIdle(p.page), { what: 'reloaded receipt lookup consumed' });
    assert.equal(fx.api.calls.length, 1);
    assert.equal(fx.api.creates.length, 0);
  } finally { await p.close(); await fx.close(); }
});


test('PA5 unresolved answer receipt survives refused access and reconnect without replay', async () => {
  const fx = await notificationSite();
  fx.api.setSend((id, body) => ({ after: DROP, report: report(id, body.op_id, body.mode, body.text, outcome(DELIVERIES.sent)) }));
  const p = await opened(fx);
  try {
    await card(p.page).waitFor({ state: 'visible' });
    await card(p.page).getByRole('button', { name: 'Confirm spec #901, sends confirm spec #901', exact: true }).click();
    const send = card(p.page).locator('[data-part=send]');
    await waitFor(async () => (await send.getAttribute('aria-disabled')) === null, { what: 'guarded preview' });
    await send.click();
    await waitFor(async () => (await card(p.page).locator('[data-part=outcome]').getAttribute('data-state')) === 'unknown', { what: 'unresolved answer' });
    const postCount = () => fx.api.log.filter((entry) => entry.kind === 'send' && entry.method === 'POST').length;
    assert.equal(postCount(), 1);
    fx.targetReply = json(401, { error: { kind: 'signed_out', message: 'Synthetic access expired' } });
    await landing(p.page).locator('[data-part=notification-refresh]').click();
    await waitFor(async () => (await landing(p.page).getAttribute('data-state')) === 'Signed out', { what: 'hidden detail after refusal' });
    assert.equal(await card(p.page).count(), 0);
    fx.targetReply = null;
    await landing(p.page).locator('[data-part=notification-refresh]').click();
    await card(p.page).waitFor({ state: 'visible' });
    await p.page.reload();
    await card(p.page).waitFor({ state: 'visible' });
    await waitFor(() => pageIdle(p.page), { what: 'reconnected receipt read' });
    assert.equal(postCount(), 1);
    assert.deepEqual(fx.api.calls.map((call) => [call.id, call.text]), [[TARGET, MESSAGE]]);
  } finally { await p.close(); await fx.close(); }
});

test('PA4 expiry keeps a pending receipt surface and focus without private detail or replay', async () => {
  const fx = await notificationSite();
  fx.api.hold('send');
  const p = await opened(fx);
  try {
    await card(p.page).waitFor({ state: 'visible' });
    await card(p.page).getByRole('button', { name: 'Confirm spec #901, sends confirm spec #901', exact: true }).click();
    const send = card(p.page).locator('[data-part=send]');
    await waitFor(async () => (await send.getAttribute('aria-disabled')) === null, { what: 'guarded preview' });
    await send.click();
    await waitFor(async () => (await card(p.page).locator('[data-part=outcome]').getAttribute('data-state')) === 'sending', { what: 'pending answer' });
    await p.page.clock.runFor(71_001);
    const receipt = p.page.locator('[data-part=bound-receipt]');
    await receipt.waitFor({ state: 'visible' });
    assert.equal(await p.page.evaluate(() => document.activeElement?.getAttribute('data-part')), 'bound-receipt');
    assert.equal(await card(p.page).count(), 0);
    assert.equal(await p.page.getByText('Keep the synthetic sample narrow.', { exact: true }).count(), 0);
    assert.equal(fx.api.log.filter((entry) => entry.kind === 'send' && entry.method === 'POST').length, 1);
  } finally { fx.api.release('send'); await p.close(); await fx.close(); }
});

// R1: an ordinary automatic target poll with unchanged responses must not
// unmount the bound card and destroy an unsent Own words draft.
test('PA4 an unsent Own words draft survives an unchanged automatic target refresh, with zero sends', async () => {
  const fx = await notificationSite({ grill: true });
  const p = await opened(fx);
  try {
    const slot = card(p.page).locator('[data-part=slot][data-question="G1"]');
    await slot.getByRole('button', { name: 'Own words', exact: true }).click();
    const field = slot.getByRole('textbox', { name: 'Your words for G1' });
    await field.fill('Keep this carefully typed answer.');
    const reads = fx.targetReads;
    await p.page.clock.runFor(60_001);
    await waitFor(() => fx.targetReads > reads, { what: 'automatic target refresh' });
    await waitFor(async () => (await landing(p.page).getAttribute('data-state')) === 'Current', { what: 'refreshed current target' });
    await waitFor(() => pageIdle(p.page), { what: 'refresh consumed' });
    assert.equal(await field.count(), 1, 'the draft editor stays mounted');
    assert.equal(await field.inputValue(), 'Keep this carefully typed answer.');
    assert.equal(fx.api.calls.length, 0);
    assert.equal(fx.api.log.filter((entry) => entry.kind === 'send' && entry.method === 'POST').length, 0);
    assert.deepEqual(p.errors, []);
  } finally { await p.close(); await fx.close(); }
});

// R1 (re-check): a slow but successful automatic refresh may outlast the old
// result's age, hiding the card. The unsent draft must come back once the same
// exact binding is verified fresh again, and nothing is sent.
test('PA4 an unsent Own words draft returns after a slow unchanged refresh crosses expiry, with zero sends', async () => {
  const fx = await notificationSite({ grill: true });
  const p = await opened(fx);
  try {
    const slot = card(p.page).locator('[data-part=slot][data-question="G1"]');
    await slot.getByRole('button', { name: 'Own words', exact: true }).click();
    const field = slot.getByRole('textbox', { name: 'Your words for G1' });
    await field.fill('Keep this carefully typed answer.');
    let release;
    fx.targetGate = new Promise((resolve) => { release = resolve; });
    const reads = fx.targetReads;
    await p.page.clock.runFor(60_001);
    await waitFor(() => fx.targetReads > reads, { what: 'held automatic target refresh' });
    await p.page.clock.runFor(12_000);
    await waitFor(async () => (await card(p.page).count()) === 0, { what: 'expired card hidden' });
    // The same exact binding, freshly observed by both independent reads.
    const at = fx.now + 72_000;
    fx.result.freshness.snapshot_at.known = at;
    fx.doc.snapshot_at = at;
    fx.doc.freshness.snapshot_at.known = at;
    fx.doc.orchestrator.freshness.snapshot_at.known = at;
    fx.targetGate = null;
    release();
    await card(p.page).waitFor({ state: 'visible' });
    await waitFor(() => pageIdle(p.page), { what: 're-verification consumed' });
    assert.equal(await field.count(), 1, 'the unsent draft editor is restored');
    assert.equal(await field.inputValue(), 'Keep this carefully typed answer.');
    assert.equal(fx.api.calls.length, 0);
    assert.equal(fx.api.log.filter((entry) => entry.kind === 'send' && entry.method === 'POST').length, 0);
    assert.deepEqual(p.errors, []);
  } finally { await p.close(); await fx.close(); }
});
