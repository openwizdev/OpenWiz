// PA4: only the opaque same-origin shell fragment may select a target.
// A supplied URL/encoded binding could otherwise redirect navigation or disclose
// source detail before authentication; existing decisions tests never parse taps.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { notificationToken, targetUrl } from '../../src/notificationTarget.ts';
import type { DecisionReference, TargetResult } from '../../src/notificationTarget.ts';

const token = '0123456789abcdef'.repeat(4);

test('PA4 accepts only an exact opaque shell fragment, with no URL decoding', () => {
  assert.deepEqual(notificationToken(''), { kind: 'none' });
  assert.deepEqual(notificationToken('#decisions'), { kind: 'none' });
  assert.deepEqual(notificationToken(`#notification=${token}`), { kind: 'target', token });
  for (const input of [
    '#notification=', `#notification=${token.toUpperCase()}`, `#notification=${token}0`,
    `#notification=${token.slice(1)}`, `#notification=${token.slice(1)}\n`, `#notification=${token}&next=/`,
    `#notification=${token}?`, `#notification=${token}#decisions`,
    `#notification=%30${token.slice(1)}`, `#notification=${token}\n`,
    `#notification=https://foreign.example/#notification=${token}`,
    `https://foreign.example/#notification=${token}`, `/#notification=${token}`,
    `#notification=${token}&notification=${token}`, `#notification=${token.replace('0', '０')}`,
  ]) assert.deepEqual(notificationToken(input), { kind: 'invalid' }, input);
});

test('PA4 target URLs cannot carry a supplied origin, path or query', () => {
  assert.equal(targetUrl(token), `/api/v1/notifications/targets/${token}`);
  for (const bad of ['', `https://foreign.example/${token}`, `../${token}`, `${token}?`, `${token}/`, `${token.slice(1)}\n`, token.toUpperCase()]) {
    assert.equal(targetUrl(bad), null, bad);
  }
});

// TargetResult is a bound reference plus source state, never authority to send.
const binding: { decision: DecisionReference } = {
  decision: {
    repository: 'synthetic-owner/synthetic-repo', subject: { kind: 'issue', number: 901 },
    comment_id: 902, request_id: 'synthetic-request', fingerprint: 'a'.repeat(64),
  },
};
const target: TargetResult = {
  reference: binding, state: 'current', coverage: { state: 'complete', gaps: [] },
  freshness: { state: 'fresh', snapshot_at: { known: 1234 } },
};
const envelope = (value: unknown) => JSON.stringify({ schema: 'openwiz.notifications.v1', record: { target_result: value } });

test('PA4 target reads preserve exact references, source state and original age', async () => {
  const { readTargetText } = await import('../../src/notificationTarget.ts');
  for (const state of ['current', 'changed', 'resolved', 'missing', 'ambiguous', 'unread']) {
    const expected = { ...target, state };
    assert.deepEqual(readTargetText(envelope(expected)), expected);
  }
  const incident = { ...target, reference: { incident: { repository: 'synthetic-owner/synthetic-repo', owner: 'synthetic-engine', source: 'service_health', subject: 'server', incident: 'synthetic-incident' } } };
  assert.deepEqual(readTargetText(envelope(incident)), incident);
  const unread = { ...target, state: 'unread', coverage: { state: 'partial', gaps: [{ source: 'decisions', reason: 'Source unavailable' }] }, freshness: { state: 'unknown', snapshot_at: { unknown: 'Source unavailable' } } };
  assert.deepEqual(readTargetText(envelope(unread)), unread);
  const epoch = { ...target, freshness: { state: 'fresh', snapshot_at: { known: 0 } } };
  assert.deepEqual(readTargetText(envelope(epoch)), epoch);
});

test('PA4 malformed target envelopes never become current source facts', async (t) => {
  const { readTargetText } = await import('../../src/notificationTarget.ts');
  const valid = envelope(target);
  // Unsigned wire times must reject -0; unavailable source time must have a
  // coverage gap. The earlier shape table missed both semantic distinctions.
  const invalidCases = [
    valid.replace('"state":"current"', '"state":"current","state":"resolved"'),
    valid.replace('"number":901', '"number":901,"number":901'),
    valid.replace('"number":901', '"number":901.0'),
    valid.replace('"number":901', '"number":9.01e2'),
    valid.replace('"number":901', '"number":0'),
    valid.replace('"number":901', '"number":9007199254740993'),
    valid.replace('"comment_id":902', '"comment_id":-1'),
    valid.replace('"repository":"synthetic-owner/synthetic-repo"', '"repository":"https://foreign.example/repo"'),
    valid.replace('"request_id":"synthetic-request"', '"request_id":"-request"'),
    valid.replace('"current"', '{"current":null}'),
    valid.replace('"current"', '"future"'),
    valid.replace('"schema":', '"extra":true,"schema":'),
    envelope({ ...target, extra: true }), envelope({ ...target, reference: [] }),
    envelope({ ...target, coverage: { state: 'partial', gaps: [] } }),
    envelope({ ...target, coverage: { state: 'complete', gaps: [{ source: 'decisions', reason: 'Unread' }] } }),
    envelope({ ...target, freshness: { state: 'unknown', snapshot_at: { known: 1234 } } }),
    valid.replace('"known":1234', '"known":-0'),
    envelope({ ...target, freshness: { state: 'unknown', snapshot_at: { unknown: 'Source unavailable' } } }),
  ];
  for (const [index, invalid] of invalidCases.entries()) {
    await t.test(`invalid target ${index + 1}`, () => assert.equal(readTargetText(invalid), null, invalid));
  }
});

// PA5: access failures must not return an injected private target body. This
// extends the existing API boundary tests only for notification resolution.
test('PA5 notification resolution withholds detail on access refusal and foreign redirects', async () => {
  const { readNotificationTarget } = await import('../../src/api.ts');
  const { FakeFetch, json } = await import('./support.ts');
  for (const response of [json(401, JSON.parse(envelope(target))), json(403, JSON.parse(envelope(target))), { ...json(200, JSON.parse(envelope(target))), type: 'opaqueredirect' }]) {
    const f = new FakeFetch();
    const pending = readNotificationTarget(f.fetch, token, new AbortController().signal);
    f.reply(response);
    const result = await pending;
    assert.notEqual(result, 'stopped');
    assert.ok(result !== 'stopped' && result.kind !== 'ok');
    assert.equal(Object.hasOwn(result, 'envelope'), false);
    assert.equal(f.urls.length, 1);
  }
});

test('PA4 notification read returns its strict result and makes no request for an invalid token', async () => {
  const { readNotificationTarget } = await import('../../src/api.ts');
  const { FakeFetch, json } = await import('./support.ts');
  const f = new FakeFetch();
  assert.deepEqual(await readNotificationTarget(f.fetch, 'https://foreign.example', new AbortController().signal), { kind: 'error', status: 400, error: null });
  assert.equal(f.urls.length, 0);
  const pending = readNotificationTarget(f.fetch, token, new AbortController().signal);
  f.reply(json(200, JSON.parse(envelope(target))));
  assert.deepEqual(await pending, { kind: 'ok', envelope: target });
  assert.deepEqual(f.urls, [`/api/v1/notifications/targets/${token}`]);
});

// Exact card selection and a displayed proposal's immutability belong to this
// boundary. List-position selection or binding only the fingerprint would miss
// reordering and unchanged-fingerprint wording/risk/target edits.
test('PA4 bound card selection follows identity and never the next list position', async () => {
  const { readFileSync } = await import('node:fs');
  const { readDecisionsText } = await import('../../src/decisions.ts');
  const { selectBoundDecision } = await import('../../src/notificationTarget.ts');
  const parsed = readDecisionsText(readFileSync(new URL('../fixtures/notification-target/decisions.json', import.meta.url), 'utf8'));
  if (!parsed.ok) assert.fail(parsed.why);
  const d = parsed.decisions;
  const received = { mono: 0, wall: 10_000 };
  const now = { mono: 0, wall: 10_000 };
  const first = selectBoundDecision(binding.decision, d, received, now);
  assert.equal(first.state, 'current');
  if (first.state !== 'current') assert.fail('exact synthetic current item');
  assert.equal(first.item.comment_id, 902);
  const other = structuredClone(d.items[0]!);
  other.comment_id = 900;
  other.request.id = 'synthetic-other';
  const reordered = { ...d, items: [other, ...d.items] };
  const selected = selectBoundDecision(binding.decision, reordered, received, now, first.binding);
  assert.equal(selected.state, 'current');
  if (selected.state !== 'current') assert.fail('exact item after reorder');
  assert.equal(selected.item.comment_id, 902);
  assert.equal(selectBoundDecision(binding.decision, { ...d, items: [other] }, received, now, first.binding).state, 'unread');
  assert.equal(selectBoundDecision(binding.decision, { ...d, items: [...d.items, ...d.items] }, received, now, first.binding).state, 'ambiguous');
  for (const mutate of [
    (x: typeof d) => { x.items[0]!.request.risk = 'release'; },
    (x: typeof d) => { const r = x.items[0]!.request; if (r.kind === 'spec_confirmation') r.summary = ['Changed synthetic wording.']; },
    (x: typeof d) => { x.orchestrator.target = { known: 'thr_syn_replacement' }; },
    (x: typeof d) => { x.items[0]!.request.fingerprint = 'b'.repeat(64); },
  ]) {
    const changed = structuredClone(d);
    mutate(changed);
    assert.equal(selectBoundDecision(binding.decision, changed, received, now, first.binding).state, 'changed');
  }
  assert.equal(selectBoundDecision(binding.decision, d, received, { mono: 70_001, wall: 80_001 }, first.binding).state, 'unread');
  const unknown = structuredClone(d);
  unknown.items[0]!.current = { unknown: 'Independent source unavailable' };
  assert.equal(selectBoundDecision(binding.decision, unknown, received, now).state, 'unread');
});

// #2150: local comment/request ids are unique only within a repository. A
// selector keyed by local ids alone would count another configured
// repository's equal ids as a duplicate, or substitute its record.
test('PA4 bound card selection is qualified by the reference repository', async () => {
  const { readFileSync } = await import('node:fs');
  const { readDecisionsText } = await import('../../src/decisions.ts');
  const { selectBoundDecision } = await import('../../src/notificationTarget.ts');
  const parsed = readDecisionsText(readFileSync(new URL('../fixtures/notification-target/decisions.json', import.meta.url), 'utf8'));
  if (!parsed.ok) assert.fail(parsed.why);
  const d = parsed.decisions;
  const received = { mono: 0, wall: 10_000 };
  const foreign = structuredClone(d.items[0]!);
  foreign.subject.repository = 'synthetic-other/synthetic-repo';
  const both = { ...d, items: [foreign, ...d.items] };
  const selected = selectBoundDecision(binding.decision, both, received, received);
  assert.equal(selected.state, 'current');
  if (selected.state !== 'current') assert.fail('exact repository item');
  assert.equal(selected.item.subject.repository, 'synthetic-owner/synthetic-repo');
  // Only the other repository's equal ids: never a substitute.
  assert.equal(selectBoundDecision(binding.decision, { ...d, items: [foreign] }, received, received).state, 'unread');
  // The source's verified canonical case still names the same repository.
  const canonical = structuredClone(d);
  canonical.items[0]!.subject.repository = 'Synthetic-Owner/Synthetic-Repo';
  assert.equal(selectBoundDecision(binding.decision, canonical, received, received).state, 'current');
});

test('PA4 bound target age is never refreshed by elapsed-clock disagreement', async () => {
  const { targetIsFresh } = await import('../../src/notificationTarget.ts');
  const result: TargetResult = { ...target, state: 'current', freshness: { state: 'fresh', snapshot_at: { known: 9000 } } };
  const received = { mono: 0, wall: 10_000 };
  assert.equal(targetIsFresh(result, received, { mono: 69_000, wall: 79_000 }), true);
  assert.equal(targetIsFresh(result, received, { mono: 69_001, wall: 79_001 }), false);
  assert.equal(targetIsFresh(result, received, { mono: 70_000, wall: 10_000 }), false);
  assert.equal(targetIsFresh(result, received, { mono: 0, wall: 80_001 }), false);
  assert.equal(targetIsFresh(result, received, { mono: -1, wall: 10_000 }), false);
  assert.equal(targetIsFresh({ ...result, freshness: { state: 'fresh', snapshot_at: { known: 10_001 } } }, received, received), false);
});

test('PA4 an open-list omission stays unread and requires exact lifecycle resolution', async () => {
  const { readFileSync } = await import('node:fs');
  const { readDecisionsText } = await import('../../src/decisions.ts');
  const { selectBoundDecision } = await import('../../src/notificationTarget.ts');
  const parsed = readDecisionsText(readFileSync(new URL('../fixtures/notification-target/decisions.json', import.meta.url), 'utf8'));
  if (!parsed.ok) assert.fail(parsed.why);
  const empty = { ...parsed.decisions, items: [] };
  const received = { mono: 0, wall: 10_000 };
  assert.equal(selectBoundDecision(binding.decision, empty, received, received).state, 'unread');
  const partial = { ...empty, coverage: { state: 'partial' as const, gaps: [{ kind: 'not_found' as const, detail: 'Independent source unavailable' }] } };
  assert.equal(selectBoundDecision(binding.decision, partial, received, received).state, 'unread');
  assert.equal(selectBoundDecision(binding.decision, empty, received, { mono: 70_001, wall: 80_001 }).state, 'unread');
});

test('PA4 target replacements and unconfirmed failures keep the shared read lane', async () => {
  const { targetReader } = await import('../../src/notificationTarget.ts');
  const { FakeClock, FakeFetch, FakeVisibility, json, settle } = await import('./support.ts');
  for (const lost of [false, true]) {
    const clock = new FakeClock();
    const f = new FakeFetch();
    const visibility = new FakeVisibility();
    const options = { fetch: f.fetch, timers: clock, visibility, onReading: () => {}, deliver: () => {}, onTimeout: () => {} };
    const first = targetReader({ ...options, token });
    const second = targetReader({ ...options, token: '2'.repeat(64) });
    try {
      first.start(); await settle();
      assert.equal(f.urls.length, 1);
      first.retire();
      if (lost) { f.fail(); await settle(); }
      second.start(); await settle();
      assert.equal(f.urls.length, 1, 'replacement cannot overtake unfinished server work');
      if (lost) {
        await clock.advance(69_999);
        assert.equal(f.urls.length, 1);
        await clock.advance(1);
      } else { f.reply(json(200, JSON.parse(envelope(target)))); await settle(); }
      assert.deepEqual(f.urls, [`/api/v1/notifications/targets/${token}`, `/api/v1/notifications/targets/${'2'.repeat(64)}`]);
      f.reply(json(200, JSON.parse(envelope(target)))); await settle();
    } finally { first.stop(); second.stop(); await settle(); }
  }
});

test('PA4 repeated source timestamps keep their first monotonic observation', async () => {
  const { targetObservation, targetIsFresh } = await import('../../src/notificationTarget.ts');
  const previous = { mono: 0, wall: 10_000 };
  const repeated: TargetResult = { ...target, freshness: { state: 'fresh', snapshot_at: { known: 9000 } } };
  const current = { mono: 60_000, wall: 10_000 };
  const observed = targetObservation(previous, repeated, current);
  assert.deepEqual(observed, previous);
  assert.equal(targetIsFresh(repeated, observed, { mono: 70_001, wall: 10_000 }), false);
  const updated: TargetResult = { ...target, freshness: { state: 'fresh', snapshot_at: { known: 11_000 } } };
  assert.deepEqual(targetObservation(previous, updated, { mono: 2000, wall: 12_000 }), { mono: 2000, wall: 12_000 });
});
