// #2035 PA2/PA5 (client portion): the owner's explicit notification actions
// over the actual client calls. Node only: the connected wrapper is unmounted
// until its App mount line is approved (#2035 Q2 ruling), so this drives the
// wiring it uses, `notificationWrite`, with writeNotificationPreferences and a
// recording fetch.
//
// - D1: Enable is refused with no write while capability is unavailable or
//   unsupported (no permission prompt, no subscription: the checked sources
//   cannot name Notification or PushManager), and otherwise saves enabled true
//   against the read generation with the saved categories.
// - D2: Save sends every category with the current enable choice; Disable
//   sends enabled false with the saved categories.
// - D3: a lost reply keeps its operation: repeating the same body reuses its
//   id, a changed body or a newer generation gets a new one. Nothing retries
//   on its own.
// - D4 (rendered, J25): the cockpit mounts the connected settings, which read
//   the actual status route and show Unsupported; pressing Enable makes no
//   permission prompt, no push subscription and no preference write.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, openPage, pageIdle, waitFor } from '../support/browser.mjs';
import { fakeApi, json } from '../support/fake-api.mjs';
import { startSite } from '../support/serve.mjs';
import { showCockpit } from '../fixtures/cockpit/cockpit.mjs';

import { writeNotificationPreferences } from '../../src/api.ts';
import { notificationDefaults, notificationWrite, parseNotificationStatus } from '../../src/notifications.ts';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser?.close());

const fixture = (name) => readFileSync(new URL(`../fixtures/notifications-delivery/${name}`, import.meta.url), 'utf8');
const statusWith = (capability, enabled = false, generation = 3) => {
  const doc = JSON.parse(fixture('status.json'));
  doc.record.status.capability.state = capability;
  doc.record.status.preferences.enabled = enabled;
  doc.record.status.preferences.generation = generation;
  const parsed = parseNotificationStatus(JSON.stringify(doc));
  assert.ok(parsed, 'the synthetic status fixture is a valid document');
  return parsed;
};
let n = 0;
const ids = () => String(++n).padStart(32, '0');

test('D1: Enable writes nothing while capability is unavailable or unsupported, otherwise saves enabled true', () => {
  for (const capability of ['unavailable', 'unsupported']) {
    assert.equal(notificationWrite(statusWith(capability), { kind: 'enable' }, null, ids), null, capability);
  }
  for (const capability of ['setup_required', 'ready']) {
    const w = notificationWrite(statusWith(capability), { kind: 'enable' }, null, ids);
    assert.deepEqual({ ...w, operation_id: 'id' }, { operation_id: 'id', expected_generation: 3, enabled: true, categories: notificationDefaults().categories }, capability);
    assert.match(w.operation_id, /^[0-9a-f]{32}$/);
  }
  const src = readFileSync(new URL('../../src/notifications.ts', import.meta.url), 'utf8') + readFileSync(new URL('../../src/components/Notifications.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(src, /requestPermission|pushManager|subscribe\(/, 'no native prompt or subscription from the page');
});

test('D2: Save sends every category with the current choice; Disable sends enabled false', async () => {
  const on = statusWith('ready', true);
  const choices = { ...notificationDefaults().categories, merge: true, decision: false };
  const save = notificationWrite(on, { kind: 'save', categories: choices }, null, ids);
  assert.deepEqual([save.enabled, save.expected_generation, save.categories], [true, 3, choices]);
  const off = notificationWrite(on, { kind: 'disable' }, null, ids);
  assert.deepEqual([off.enabled, off.categories], [false, notificationDefaults().categories]);
  // Through the actual client call: one PUT carrying exactly this write.
  const calls = [];
  const result = await writeNotificationPreferences(async (url, init) => {
    calls.push({ url, init });
    return { status: 200, ok: true, type: 'basic', headers: { get: () => 'application/json' }, text: async () => JSON.stringify({ schema: 'openwiz.notifications.v1', record: { preferences: { generation: 4, enabled: false, categories: off.categories } } }) };
  }, off, AbortSignal.timeout(5000));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/v1/notifications/preferences');
  assert.equal(calls[0].init.method, 'PUT');
  assert.deepEqual(JSON.parse(calls[0].init.body), { schema: 'openwiz.notifications.v1', record: { preference_write: off } });
  assert.equal(result.kind, 'ok');
});

test('D3: a repeated identical action reuses its operation id; a changed one does not', () => {
  const on = statusWith('ready', true);
  const first = notificationWrite(on, { kind: 'disable' }, null, ids);
  const again = notificationWrite(on, { kind: 'disable' }, first, ids);
  assert.equal(again.operation_id, first.operation_id, 'same body after a lost reply: same operation');
  const changed = notificationWrite(on, { kind: 'save', categories: { ...on.preferences.categories, merge: true } }, first, ids);
  assert.notEqual(changed.operation_id, first.operation_id);
  const newer = notificationWrite(statusWith('ready', true, 4), { kind: 'disable' }, first, ids);
  assert.notEqual(newer.operation_id, first.operation_id, 'a newer generation is a new operation');
});

test('D4: the cockpit mounts the connected settings; Enable while unsupported prompts, subscribes and writes nothing', async () => {
  const api = fakeApi();
  const seen = { status: 0, writes: 0 };
  const site = await startSite(async (req, res, url) => {
    if (!url.pathname.startsWith('/api/v1/notifications/')) return api.handler(req, res, url);
    let reply;
    if (url.pathname === '/api/v1/notifications/status' && req.method === 'GET') { seen.status++; reply = json(200, JSON.parse(fixture('status.json'))); }
    else { seen.writes++; reply = json(409, { error: { kind: 'subscription_unavailable', message: 'Synthetic refusal' } }); }
    res.writeHead(reply.status, reply.headers);
    res.end(reply.body);
  });
  const p = await openPage(browser, site.origin, { stampReads: true });
  try {
    // Record every native prompt or subscription the page could make.
    await p.page.addInitScript(() => {
      window.__native = [];
      if (window.Notification) window.Notification.requestPermission = async () => { window.__native.push('requestPermission'); return 'default'; };
      if (window.PushManager) window.PushManager.prototype.subscribe = async () => { window.__native.push('subscribe'); throw new Error('synthetic'); };
    });
    await p.page.reload();
    await showCockpit(p.page);
    const section = p.page.locator('[data-part=notifications]');
    await waitFor(async () => (await section.locator('.nt-word').first().textContent())?.includes('Unsupported'), { what: 'connected status read' });
    assert.ok(seen.status >= 1, 'the actual status route was read');
    const enable = section.getByRole('button', { name: 'Enable notifications', exact: true });
    assert.equal(await enable.getAttribute('aria-disabled'), 'true');
    await enable.click({ force: true }); // a real click on the aria-disabled control
    await p.page.waitForTimeout(200);
    assert.deepEqual(await p.page.evaluate(() => window.__native), []);
    assert.equal(seen.writes, 0, 'no preference or subscription write');
    assert.equal(api.calls.length + api.creates.length, 0, 'no send or create');
  } finally { await p.close(); await site.close(); }
});

// R2 (review round 1): a successful Disable whose follow-up status read times
// out must show the saved Off choice and a visible reconnect failure, with
// the controls locked; never the stale Enabled text with no warning.
test('D5: Disable saved, then a timed-out status read: Off is shown with a failure and locked controls', async () => {
  const api = fakeApi();
  const enabled = JSON.parse(fixture('status.json'));
  enabled.record.status.preferences.enabled = true;
  const held = [];
  const seen = { status: 0, writes: 0, hang: false };
  const site = await startSite(async (req, res, url) => {
    if (!url.pathname.startsWith('/api/v1/notifications/')) return api.handler(req, res, url);
    if (url.pathname === '/api/v1/notifications/status' && req.method === 'GET') {
      seen.status++;
      if (seen.hang) { held.push(res); return; } // never answered: the read times out
      const reply = json(200, enabled);
      res.writeHead(reply.status, reply.headers);
      return res.end(reply.body);
    }
    seen.writes++;
    seen.hang = true;
    const saved = { ...enabled.record.status.preferences, generation: 4, enabled: false };
    const reply = json(200, { schema: 'openwiz.notifications.v1', record: { preferences: saved } });
    res.writeHead(reply.status, reply.headers);
    res.end(reply.body);
  });
  const p = await openPage(browser, site.origin, { stampReads: true, clock: new Date('2026-11-13T00:00:00Z'), paused: true });
  try {
    await showCockpit(p.page);
    const section = p.page.locator('[data-part=notifications]');
    await waitFor(async () => (await section.textContent())?.includes('Enabled in saved preferences'), { what: 'enabled status read' });
    await section.getByRole('button', { name: 'Turn delivery off', exact: true }).click({ force: true });
    await waitFor(async () => seen.writes === 1 && seen.status === 2, { what: 'write, then the follow-up read' });
    await p.page.clock.runFor(15_001); // the client's read deadline passes
    await waitFor(async () => (await section.textContent())?.includes('Reconnect, then refresh'), { what: 'visible timeout failure', timeout: 20_000 });
    const text = await section.textContent();
    assert.ok(text.includes('Off in saved preferences.'), 'the saved Off choice is shown');
    assert.ok(!text.includes('Enabled in saved preferences'), 'never the stale Enabled text');
    assert.equal(await section.getByRole('button', { name: 'Save event choices', exact: true }).getAttribute('aria-disabled'), 'true');
    assert.equal(seen.writes, 1, 'nothing repeated the write');
  } finally { for (const r of held) r.destroy(); await p.close(); await site.close(); }
});

// R1 (review round 1): an unresolved preference operation survives reloading
// the tab (which unmounts the settings, as leaving the cockpit does). Nothing replays it on its own; the
// owner's explicit "Retry the same change" repeats the identical id and body.
test('D6: a lost write reply keeps its operation across a reload; only an explicit retry repeats it, identically', async () => {
  const api = fakeApi();
  const writes = [];
  const site = await startSite(async (req, res, url) => {
    if (!url.pathname.startsWith('/api/v1/notifications/')) return api.handler(req, res, url);
    if (url.pathname === '/api/v1/notifications/status' && req.method === 'GET') {
      const reply = json(200, JSON.parse(fixture('status.json')));
      res.writeHead(reply.status, reply.headers);
      return res.end(reply.body);
    }
    let body = '';
    for await (const chunk of req) body += chunk;
    writes.push(JSON.parse(body));
    if (writes.length === 1) return res.destroy(); // the reply is lost
    const reply = json(200, { schema: 'openwiz.notifications.v1', record: { preferences: { ...writes[0].record.preference_write, generation: 4, operation_id: undefined, expected_generation: undefined } } });
    res.writeHead(reply.status, reply.headers);
    res.end(reply.body);
  });
  const p = await openPage(browser, site.origin, { stampReads: true });
  const section = p.page.locator('[data-part=notifications]');
  const retry = () => p.page.getByRole('button', { name: 'Retry the same change', exact: true });
  try {
    await showCockpit(p.page);
    await waitFor(async () => (await section.textContent())?.includes('Showing saved event choices'), { what: 'status read' });
    await section.getByRole('checkbox').nth(5).check({ force: true }); // Merges on
    await section.getByRole('button', { name: 'Save event choices', exact: true }).click({ force: true });
    await waitFor(async () => (await section.textContent())?.includes('Reconnect, then refresh'), { what: 'lost reply shown' });
    assert.equal(writes.length, 1);
    // R5: Refresh clears the failure at the unchanged generation, leaving
    // edited choices. Ordinary Save must not become a second retry action.
    await section.getByRole('button', { name: 'Refresh status', exact: true }).click();
    await waitFor(async () => !(await section.textContent()).includes('Reconnect, then refresh') && !(await section.textContent()).includes('Reading notification status…'), { what: 'Refresh read at the same generation' });
    const save = section.getByRole('button', { name: 'Save event choices', exact: true });
    assert.equal(await save.getAttribute('aria-disabled'), 'false', 'edited choices remain available after Refresh');
    await save.click();
    await waitFor(() => pageIdle(p.page), { what: 'ordinary Save gesture handled' });
    assert.equal(writes.length, 1, 'ordinary Save cannot repeat the pending operation');
    // Reload the tab: the settings unmount and remount, as leaving the cockpit does.
    await p.page.reload();
    await showCockpit(p.page);
    await waitFor(async () => (await retry().count()) === 1, { what: 'the kept operation offered for an explicit retry' });
    assert.equal(writes.length, 1, 'nothing replayed on its own after reload');
    await retry().click({ force: true });
    await waitFor(async () => writes.length === 2, { what: 'the explicit retry' });
    assert.deepEqual(writes[1], writes[0], 'the identical id and body');
    await waitFor(async () => (await retry().count()) === 0, { what: 'the settled operation cleared' });
  } finally { await p.close(); await site.close(); }
});

// R1, final round: D6 settles A before leaving. Keep A in flight instead:
// its retired component must not delete an unresolved successor B's receipt.
test('D7: a late reply after navigation cannot clear the next pending change or its reload retry', async () => {
  const api = fakeApi();
  const doc = JSON.parse(fixture('status.json'));
  const writes = [];
  let held;
  const answer = (res, preferences) => {
    const reply = json(200, { schema: 'openwiz.notifications.v1', record: { preferences } });
    res.writeHead(reply.status, reply.headers);
    res.end(reply.body);
  };
  const site = await startSite(async (req, res, url) => {
    if (!url.pathname.startsWith('/api/v1/notifications/')) return api.handler(req, res, url);
    if (req.method === 'GET') {
      const reply = json(200, doc);
      res.writeHead(reply.status, reply.headers);
      return res.end(reply.body);
    }
    let body = '';
    for await (const chunk of req) body += chunk;
    writes.push(JSON.parse(body));
    if (writes.length === 1) { held = res; return; }
    if (writes.length === 3) return res.destroy(); // B's result stays unresolved
    const w = writes.at(-1).record.preference_write;
    doc.record.status.preferences = { generation: w.expected_generation + 1, enabled: w.enabled, categories: w.categories };
    answer(res, doc.record.status.preferences);
  });
  const p = await openPage(browser, site.origin, { viewport: DESKTOP, stampReads: true, clock: new Date('2026-11-13T00:00:00Z'), paused: true });
  const section = p.page.locator('[data-part=notifications]');
  const retry = p.page.getByRole('button', { name: 'Retry the same change', exact: true });
  const stored = () => p.page.evaluate(() => JSON.parse(sessionStorage.getItem('openwiz.notifications.pending')));
  try {
    await showCockpit(p.page);
    await section.getByRole('checkbox').nth(5).check({ force: true });
    await section.getByRole('button', { name: 'Save event choices', exact: true }).click();
    await waitFor(() => !!held, { what: 'A held in flight' });
    const nav = p.page.getByRole('navigation', { name: 'Views', exact: true });
    await nav.getByRole('button', { name: 'Sessions', exact: true }).click();
    await waitFor(async () => await section.count() === 0, { what: 'settings unmounted' });
    // showCockpit waits for all requests; deliberately keep A outstanding here.
    await nav.getByRole('button', { name: 'Cockpit', exact: true }).click();
    await waitFor(async () => await retry.count() === 1 && (await section.textContent()).includes('Showing saved event choices'), { what: 'A restored after navigation' });
    await retry.click();
    await waitFor(async () => await retry.count() === 0 && await section.getByRole('checkbox').nth(5).isChecked(), { what: 'A retry confirmed' });
    assert.deepEqual(writes[1], writes[0], 'A retry keeps the exact operation');
    await section.getByRole('checkbox').nth(0).uncheck({ force: true });
    await section.getByRole('button', { name: 'Save event choices', exact: true }).click();
    await waitFor(async () => writes.length === 3 && (await section.textContent()).includes('Reconnect, then refresh'), { what: 'B unresolved' });
    assert.deepEqual(await stored(), writes[2].record.preference_write, 'B saved before the late reply');
    answer(held, doc.record.status.preferences);
    await waitFor(() => pageIdle(p.page), { what: 'late A reply consumed' });
    assert.deepEqual(await stored(), writes[2].record.preference_write, 'late A must preserve B');
    await p.page.reload();
    await showCockpit(p.page);
    assert.equal(await retry.count(), 1, 'B still offers retry after reload');
    assert.equal(writes.length, 3, 'reload sends nothing');
    await retry.click();
    await waitFor(async () => writes.length === 4 && await retry.count() === 0, { what: 'B explicit retry confirmed' });
    assert.deepEqual(writes[3], writes[2], 'B retry keeps its exact operation');
  } finally { held?.destroy(); await p.close(); await site.close(); }
});

// R4: D5 covers failed refreshes, not successful responses arriving out of
// order. An older initial GET must not replace a retry's confirmed choices.
test('D8: a delayed initial status read cannot overwrite a confirmed retry', async () => {
  const api = fakeApi();
  const old = JSON.parse(fixture('status.json'));
  const current = structuredClone(old);
  current.record.status.preferences.generation = 4;
  current.record.status.preferences.categories.merge = true;
  const pending = { operation_id: '00000000000000000000000000000008', expected_generation: 3, enabled: false, categories: current.record.status.preferences.categories };
  const writes = [];
  let held;
  let reads = 0;
  const answer = (res, doc) => {
    const reply = json(200, doc);
    res.writeHead(reply.status, reply.headers);
    res.end(reply.body);
  };
  const site = await startSite(async (req, res, url) => {
    if (!url.pathname.startsWith('/api/v1/notifications/')) return api.handler(req, res, url);
    if (req.method === 'GET') {
      if (++reads === 1) { held = res; return; }
      return answer(res, current);
    }
    let body = '';
    for await (const chunk of req) body += chunk;
    writes.push(JSON.parse(body));
    answer(res, { schema: 'openwiz.notifications.v1', record: { preferences: current.record.status.preferences } });
  });
  const p = await openPage(browser, site.origin, { viewport: DESKTOP, stampReads: true });
  const section = p.page.locator('[data-part=notifications]');
  const retry = p.page.getByRole('button', { name: 'Retry the same change', exact: true });
  try {
    await p.page.evaluate((write) => sessionStorage.setItem('openwiz.notifications.pending', JSON.stringify(write)), pending);
    await p.page.getByRole('navigation', { name: 'Views', exact: true }).getByRole('button', { name: 'Cockpit', exact: true }).click();
    await waitFor(async () => !!held && await retry.count() === 1, { what: 'restored pending A with initial GET held' });
    await retry.click();
    await waitFor(async () => reads === 2 && await retry.count() === 0 && await section.getByRole('checkbox').nth(5).isChecked(), { what: 'generation-4 Merge on confirmed' });
    await waitFor(() => p.page.locator('.notifications').getByText('Reading notification status…', { exact: true }).count().then((n) => n === 0), { what: 'follow-up read complete' });
    answer(held, old);
    await waitFor(() => pageIdle(p.page), { what: 'superseded initial response consumed' });
    assert.equal(await section.getByRole('checkbox').nth(5).isChecked(), true, 'Merge stays on after the superseded generation-3 read');
    assert.ok((await section.textContent()).includes('Showing saved event choices.'), 'confirmed choices stay saved');
    assert.ok(!(await section.textContent()).includes('Last read ·'), 'no failure introduced');
    assert.ok(!(await section.textContent()).includes('Reading notification status…'), 'read stays complete');
    assert.deepEqual(writes, [{ schema: 'openwiz.notifications.v1', record: { preference_write: pending } }], 'only the explicit retry was sent');
  } finally { held?.destroy(); await p.close(); await site.close(); }
});
