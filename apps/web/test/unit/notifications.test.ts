// PA5: notification status must remain honest at the real API/render boundary.
// Existing API/render tests have no notifications, so cannot catch optimistic
// receipt wording, missing categories or a stub advertising enablement.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
import { readNotificationStatus, readNotificationPreferences, writeNotificationPreferences } from '../../src/api.ts';
import { notificationDefaults, selectNotificationCategory } from '../../src/notifications.ts';
import type { FetchLike } from '../../src/api.ts';

registerHooks({ load(url, context, nextLoad) {
  if (!url.startsWith('file:') || !url.endsWith('.tsx')) return nextLoad(url, context);
  return { format: 'module', source: ts.transpileModule(readFileSync(fileURLToPath(url), 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, verbatimModuleSyntax: true } }).outputText, shortCircuit: true };
} });
const { Notifications } = await import('../../src/components/Notifications.tsx');
const categories = ['decision', 'recovery_escalation', 'ci_failed', 'review_findings', 're_check', 'merge', 'agent_complete', 'ready_stock_changed', 'loop_missed', 'loop_stuck', 'loop_disabled', 'loop_run_changed', 'recovery_changed', 'service_update', 'contract_changed', 'fleet_wait_changed'] as const;
const preferences = () => ({ generation: 0, enabled: false, categories: Object.fromEntries(categories.map((c) => [c, c === 'decision' || c === 'recovery_escalation'])) });
const status = () => ({
  state: 'off', reason: 'Delivery is off.', next: 'Enable only after setup is verified.', preferences: preferences(),
  capability: { state: 'unavailable', permission: 'unknown', reason: 'No verified transport.', next: 'Complete supported setup.' },
  subscription: { generation: 0, state: 'absent', binding_id: null, reason: 'No subscription.', next: 'Complete supported setup.' },
  sources: categories.map((category) => ({ category, available: { unknown: 'Source not verified' }, reason: 'Synthetic source unavailable' })),
  latest: null as any, coverage: { state: 'partial', gaps: [{ source: 'decisions', reason: 'Synthetic decisions unread' }] },
  freshness: { state: 'unknown', snapshot_at: { unknown: 'Source time unread' } },
});
function dispatch(state: string) {
  return { submission: { dispatch_id: 'a'.repeat(32), group: { incident: { repository: 'example/factory', owner: 'synowner', source: 'service_health', subject: 'synengine', incident: 'synincident' } }, preference_generation: 0, subscription_generation: 0, payload: { title: 'OpenWiz needs your attention', target_token: 'b'.repeat(64) } }, state, group_state: 'open', reserved_at: 1000, updated_at: 2000, outcome: ['reserved', 'submitting', 'cancelled'].includes(state) ? null : { state, reason: 'Synthetic boundary result' } };
}
const documentFor = (key: string, value: unknown) => JSON.stringify({ schema: 'openwiz.notifications.v1', record: { [key]: value } });
const response = (body: string, statusCode = 200, type = 'basic') => ({ status: statusCode, type, headers: { get: (key: string) => key === 'Content-Type' ? 'application/json' : null }, text: async () => body });
const signal = () => new AbortController().signal;
async function returned<T>(value: Promise<T | 'stopped'>): Promise<Exclude<T, 'stopped'>> {
  const result = await value; assert.notEqual(result, 'stopped'); return result as Exclude<T, 'stopped'>;
}
const decode = (s = status()) => returned(readNotificationStatus(async () => response(documentFor('status', s)), signal()));
const render = (props = {}) => renderToStaticMarkup(createElement(Notifications, props));

test('PA5 default mount has every default but advertises no capability or saved preferences', () => {
  const html = render();
  assert.match(html, /Notifications/);
  assert.match(html, /Saved preferences unknown/);
  assert.match(html, /Enable notifications/);
  assert.match(html, /Integration unavailable/);
  assert.equal((html.match(/type="checkbox"/g) ?? []).length, 16);
  assert.equal((html.match(/checked=""/g) ?? []).length, 2);
  assert.equal((html.match(/type="checkbox"[^>]*disabled=""/g) ?? []).length, 16);
  assert.doesNotMatch(html, /role="dialog"|delivered|displayed|target_token|synincident/);
});

test('PA5 strict replies and status matrix render actual outcomes, reasons and recovery', async () => {
  for (const state of ['off', 'unavailable', 'unsupported', 'setup_required', 'permission_denied', 'permission_revoked', 'ready', 'pending', 'accepted', 'failed', 'uncertain']) {
    const s = status(); s.state = state; s.reason = `Synthetic ${state} reason`; s.next = `Synthetic ${state} recovery`;
    if (state !== 'off') s.preferences.enabled = true;
    if (['ready', 'pending', 'accepted'].includes(state)) {
      s.capability = { state: 'ready', permission: 'granted', reason: 'Prerequisites checked', next: 'Keep connection available' };
      s.subscription = { generation: 1, state: 'ready', binding_id: 'synbinding' as any, reason: 'Binding verified', next: 'Keep connection available' };
      s.freshness = { state: 'fresh', snapshot_at: { known: 2000 } } as any;
    }
    if (['pending', 'accepted', 'failed', 'uncertain'].includes(state)) s.latest = dispatch(state);
    const r = await decode(s); assert.equal(r.kind, 'ok', state); if (r.kind !== 'ok') continue;
    const html = render({ status: r.envelope, now: 2000 });
    assert.ok(html.includes(s.reason) && html.includes(s.next), state);
    assert.match(html, /Synthetic source unavailable/);
    assert.match(html, /partial/);
    assert.doesNotMatch(html, /delivered|displayed|target_token|synbinding|synincident/);
    if (state === 'ready') assert.match(html, /Ready means prerequisites checked/);
    if (state === 'accepted') assert.match(html, /Accepted by the dispatch boundary/);
  }
  const s = status(); s.latest = dispatch('uncertain');
  const r = await decode(s); assert.equal(r.kind, 'ok'); if (r.kind !== 'ok') return;
  const html = render({ status: r.envelope, now: 3000 });
  assert.match(html, /Delivery off/); assert.match(html, /Uncertain/); assert.match(html, /Do not resend/);
});

test('every toggle is independent and a preference write never enables delivery implicitly', async () => {
  const base = notificationDefaults();
  assert.deepEqual(base, preferences());
  for (const category of categories) {
    const selected = selectNotificationCategory(base.categories, category, !base.categories[category]);
    assert.equal(selected[category], !base.categories[category]);
    for (const other of categories.filter((c) => c !== category)) assert.equal(selected[other], base.categories[other]);
    const calls: { url: string; init: RequestInit }[] = [];
    const write = { operation_id: 'c'.repeat(32), expected_generation: 0, enabled: false, categories: selected };
    const fetch: FetchLike = async (url, init) => { calls.push({ url, init }); return response(documentFor('preferences', { generation: 1, enabled: false, categories: selected })); };
    const result = await writeNotificationPreferences(fetch, write, signal());
    assert.equal(result.kind, 'ok');
    assert.equal(calls.length, 1); assert.equal(calls[0]?.url, '/api/v1/notifications/preferences');
    assert.deepEqual(JSON.parse(String(calls[0]?.init.body)), { schema: 'openwiz.notifications.v1', record: { preference_write: write } });
    assert.equal(calls[0]?.init.method, 'PUT'); assert.equal(calls[0]?.init.credentials, 'same-origin');
    assert.equal(calls[0]?.init.redirect, 'manual'); assert.equal(calls[0]?.init.cache, 'no-store');
    assert.equal(new Headers(calls[0]?.init.headers).get('X-OpenWiz-Send'), '1');
    assert.equal(new Headers(calls[0]?.init.headers).get('X-Requested-With'), 'XMLHttpRequest');
  }
});

test('malformed status/preference replies fail closed instead of inventing a working setup', async () => {
  const mutations = [
    (s: any) => { s.extra = true; }, (s: any) => { s.state = 'delivered'; },
    (s: any) => { s.preferences.categories.merge = 'false'; }, (s: any) => { delete s.preferences.categories.merge; },
    (s: any) => { s.sources.pop(); }, (s: any) => { s.sources[1] = s.sources[0]; },
    (s: any) => { s.sources[0].available = { known: 'yes' }; },
    (s: any) => { s.subscription.endpoint = 'https://synthetic.example/secret'; },
    (s: any) => { s.latest = dispatch('delivered'); },
  ];
  for (const mutate of mutations) { const s = status(); mutate(s); assert.equal((await decode(s)).kind, 'error'); }
  for (const raw of [documentFor('status', status()).replace('"state":"off"', '"state":"off","state":"ready"'), documentFor('status', status()).replace('"generation":0', '"generation":0.0'), documentFor('status', status()).replace('openwiz.notifications.v1', 'openwiz.notifications.v2')]) {
    assert.equal((await returned(readNotificationStatus(async () => response(raw), signal()))).kind, 'error');
  }
  assert.equal((await returned(readNotificationPreferences(async () => response(documentFor('preferences', preferences())), signal()))).kind, 'ok');
  assert.equal((await returned(readNotificationPreferences(async () => response(documentFor('status', status())), signal()))).kind, 'error');
});

test('expired/denied access and network failure stay local, retain prior outcomes and never replay a write', async () => {
  const s = status(); s.latest = dispatch('uncertain');
  const good = await decode(s); assert.equal(good.kind, 'ok'); if (good.kind !== 'ok') return;
  for (const code of [401, 403, 503]) {
    let calls = 0;
    const failure = await returned(readNotificationStatus(async () => { calls++; return response('', code); }, signal()));
    assert.equal(calls, 1); assert.notEqual(failure.kind, 'ok');
    const html = render({ status: good.envelope, failure, now: 3000 });
    assert.match(html, /Uncertain/); assert.match(html, /Last read/);
    if (code === 401) assert.match(html, /Sign in/);
    if (code === 403) assert.match(html, /Access denied/);
  }
  let calls = 0;
  const result = await writeNotificationPreferences(async () => { calls++; throw new Error('synthetic lost reply'); }, { operation_id: 'c'.repeat(32), expected_generation: 0, enabled: false, categories: notificationDefaults().categories }, signal());
  assert.equal(calls, 1); assert.equal(result.kind, 'disconnected');
  const html = render({ status: good.envelope, failure: { kind: 'disconnected', cause: 'network', status: null }, saving: true, now: 3000 });
  assert.match(html, /Reconnect/); assert.match(html, /Uncertain/);
  assert.match(html, /aria-live="polite"/);
});

test('readiness and acceptance stay unverified without current prerequisites and exact dispatch evidence', async () => {
  const s = status(); s.state = 'ready'; s.preferences.enabled = true;
  let r = await decode(s); assert.equal(r.kind, 'ok'); if (r.kind !== 'ok') return;
  assert.match(render({ status: r.envelope, now: 2000 }), /Readiness unverified/);
  s.capability = { state: 'ready', permission: 'granted', reason: 'Prerequisites checked', next: 'Keep connection available' };
  s.subscription = { generation: 1, state: 'ready', binding_id: 'synbinding' as any, reason: 'Binding verified', next: 'Keep connection available' };
  s.freshness = { state: 'fresh', snapshot_at: { known: 2000 } } as any;
  r = await decode(s); assert.equal(r.kind, 'ok'); if (r.kind !== 'ok') return;
  assert.match(render({ status: r.envelope, now: 72000 }), /Ready means prerequisites checked/);
  assert.match(render({ status: r.envelope, now: 72001 }), /Readiness unverified/);
  assert.match(render({ status: r.envelope, now: 1999 }), /Readiness unverified/);
  s.state = 'accepted';
  r = await decode(s); assert.equal(r.kind, 'ok'); if (r.kind !== 'ok') return;
  assert.match(render({ status: r.envelope, now: 2000 }), /Acceptance unverified/);
  s.state = 'ready'; s.subscription.binding_id = null;
  assert.equal((await decode(s)).kind, 'error');
});

test('native permission, subscription failures and retained dispatch phases have their own visible state', async () => {
  for (const permission of ['unknown', 'prompt', 'granted', 'denied', 'revoked', 'unsupported']) {
    const s = status(); s.capability.permission = permission;
    const r = await decode(s); assert.equal(r.kind, 'ok'); if (r.kind !== 'ok') continue;
    assert.ok(render({ status: r.envelope }).includes(`Permission: ${permission}`));
  }
  for (const state of ['absent', 'ready', 'revoked', 'failed', 'unsupported']) {
    const s = status(); s.subscription.state = state;
    if (state === 'ready') s.subscription.binding_id = 'synbinding' as any;
    const r = await decode(s); assert.equal(r.kind, 'ok'); if (r.kind !== 'ok') continue;
    assert.ok(render({ status: r.envelope }).includes(`Subscription · ${state}`));
  }
  for (const phase of ['reserved', 'submitting', 'pending', 'accepted', 'failed', 'uncertain', 'cancelled']) {
    const s = status(); s.latest = dispatch(phase);
    const r = await decode(s); assert.equal(r.kind, 'ok'); if (r.kind !== 'ok') continue;
    const html = render({ status: r.envelope });
    assert.match(html, /Last dispatch/); assert.match(html, /1970-01-01T00:00:02.000Z/);
    if (phase === 'submitting') assert.match(html, /Uncertain/);
    assert.doesNotMatch(html, /target_token|synincident|bbbbbbbb/);
  }
});

// Use T1's pinned examples as well as the UI-specific failure fixtures.
test('T1 named status/preference and dispatch examples cross the actual client seam', async () => {
  const readme = readFileSync(new URL('../../../../tests/fixtures/notifications/contract/README.md', import.meta.url), 'utf8');
  const fixtures = JSON.parse(readme.split('```json\n')[1]!.split('\n```')[0]!);
  const prefs = await returned(readNotificationPreferences(async () => response(JSON.stringify(fixtures.preferences)), signal()));
  assert.equal(prefs.kind, 'ok'); if (prefs.kind !== 'ok') return;
  assert.deepEqual(prefs.envelope, notificationDefaults());
  for (const name of ['dispatch', 'dispatch-reserved', 'dispatch-submitting', 'dispatch-pending', 'dispatch-failed', 'dispatch-uncertain', 'dispatch-cancelled']) {
    const doc = structuredClone(fixtures.status); doc.record.status.latest = fixtures[name].record.dispatch;
    const r = await returned(readNotificationStatus(async () => response(JSON.stringify(doc)), signal()));
    assert.equal(r.kind, 'ok', name); if (r.kind !== 'ok') continue;
    assert.match(render({ status: r.envelope }), /Last dispatch/);
  }
  for (const group of [
    { decision: fixtures.decision.record.source_fact.decision.binding },
    { incident: fixtures.incident.record.source_fact.incident.binding },
    { event: fixtures.event.record.source_fact.event.binding },
  ]) {
    const doc = structuredClone(fixtures.status); doc.record.status.latest = structuredClone(fixtures.dispatch.record.dispatch);
    doc.record.status.latest.submission.group = group;
    const r = await returned(readNotificationStatus(async () => response(JSON.stringify(doc)), signal()));
    assert.equal(r.kind, 'ok');
  }
});
