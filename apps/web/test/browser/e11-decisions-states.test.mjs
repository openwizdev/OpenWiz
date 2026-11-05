// EP3/EP4 (#656, spec #648): what each decision card shows, and when it may
// not be answered. Cards come in the server's order, only unanswered grill
// questions are cards, and an answer is offered only with a fresh read, a
// known current record, a known risk and a fresh verified orchestrator
// target; otherwise one reason line, and nothing is sent. "Nothing waiting on
// you" only after a complete, fresh, empty read. Synthetic literals from
// test/fixtures/decisions/.

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, pageIdle, PHONE, waitFor } from '../support/browser.mjs';
import { json } from '../support/fake-api.mjs';
import { aged, card, decisionsSite, load, openDecisions, refresh, sends, slot, TARGET } from '../fixtures/decisions/decisions.mjs';

const GRILL = 9100001;
const SPEC = 9100002;
const PLAN = 9100003;

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const button = (s, name) => s.getByRole('button', { name, exact: true });
const why = (s) => s.locator('[data-part=why]').textContent();

test('EP3: cards in the server’s order; a round shows only its unanswered questions, each with what it decides, context and the recommendation', async () => {
  const fx = await decisionsSite();
  const p = await openDecisions(browser, fx, DESKTOP);
  try {
    const page = p.page;
    assert.deepEqual(await page.locator('[data-part=decisions] [data-comment]').evaluateAll((cs) => cs.map((c) => [c.dataset.comment, c.dataset.kind])), [
      ['9100001', 'grill_round'], ['9100002', 'spec_confirmation'], ['9100003', 'plan_approval'], ['9100004', 'spec_confirmation'],
    ]);
    const grill = card(page, GRILL);
    assert.equal(await grill.locator('[data-part=card-kind]').textContent(), 'Grill · round 2');
    assert.match(await grill.locator('[data-part=card-subject]').textContent(), /docs\/grills\/2030-01-15-loops\.md · PR #2731/);
    assert.equal(await grill.locator('[data-part=progress]').textContent(), '1 of 3 answered');
    assert.deepEqual(await grill.locator('[data-part=slot]').evaluateAll((ss) => ss.map((s) => s.dataset.question)), ['L4', 'L5'], 'the saved L3 is no card');
    const l4 = slot(page, GRILL, 'L4');
    assert.equal(await l4.locator('[data-part=qid]').textContent(), 'L4');
    assert.equal(await l4.locator('[data-part=decides]').textContent(), 'Should a loop pause itself after three failed runs in a row?');
    assert.equal(await l4.locator('[data-part=context]').textContent(), 'Today a failing loop keeps running every hour and posts the same error each time.');
    assert.equal(await l4.locator('[data-part=recommendation]').textContent(), 'Yes: pause after three failures in a row and tell you once.');

    const spec = card(page, SPEC);
    assert.equal(await spec.locator('[data-part=card-kind]').textContent(), 'Spec confirmation');
    assert.deepEqual(await spec.locator('[data-part=summary] li').allTextContents(), [
      'A loop that fails three runs in a row pauses itself.', 'You get one notice, not one per failure.', 'Resume is one press from the notice.', 'Paused loops show in the plan as waiting on you.',
    ]);
    assert.equal(await spec.locator('[data-part=summary]').evaluate((ol) => ol.tagName), 'OL', 'numbered lines');
    assert.equal(await spec.locator('[data-part=headline]').textContent(), '“Loops pause themselves when they keep failing, and tell you once.”');
    assert.equal(await spec.locator('[data-part=tickets-none]').textContent(), 'Tickets: not planned yet');

    const plan = card(page, PLAN);
    assert.equal(await plan.locator('[data-part=card-kind]').textContent(), 'Plan approval');
    assert.deepEqual(await plan.locator('[data-part=tickets] tbody tr').evaluateAll((rs) => rs.map((r) => [...r.cells].map((c) => c.textContent))), [
      ['#2901', 'Release notes', '—'], ['#2902', 'Build artifacts', '—'], ['#2903', 'Sign and verify', '#2902'], ['#2904', 'Publish release', '#2901, #2903'],
    ]);
    assert.deepEqual(await plan.locator('[data-part=graph] [data-edge]').evaluateAll((es) => es.map((e) => e.dataset.edge)), ['2901-2904', '2902-2903', '2903-2904'], 'the graph from the same edges');
    assert.match(await page.locator('[data-part=target]').textContent(), new RegExp(`Answers go to ${TARGET}`));
    assert.equal(await page.getByRole('navigation', { name: 'Views', exact: true }).locator('[data-part=decisions-count]').textContent(), '5', 'the count is the open questions and confirmations on the page');
    assert.deepEqual(p.errors, []);
  } finally { await p.close(); await fx.close(); }
});

test('EP4: a grill summary confirmation shows its numbered summary and sends “confirm” once', async () => {
  const fx = await decisionsSite(load('summary'));
  const p = await openDecisions(browser, fx, PHONE);
  try {
    const c = card(p.page, 9100005);
    assert.equal(await c.locator('[data-part=card-kind]').textContent(), 'Grill summary');
    assert.deepEqual(await c.locator('[data-part=summary] li').allTextContents(), ['Notices go to Decisions.', 'One notice per loop, not per failure.']);
    const s = slot(p.page, 9100005);
    await button(s, 'Confirm summary, sends confirm').click();
    await waitFor(async () => (await s.locator('[data-part=send]').getAttribute('aria-disabled')) === null, { what: 'Send ready' });
    await waitFor(() => pageIdle(p.page), { what: 'the preview consumed' });
    const outgoing = await s.locator('[data-part=outgoing]').textContent();
    await s.locator('[data-part=send]').click();
    await waitFor(async () => (await s.locator('[data-part=outcome]').getAttribute('data-state')) === 'sent', { what: 'sent' });
    assert.equal(outgoing, 'openwiz decision answer v1\n{"subject":{"repository":"synthetic-owner/synthetic-repo","kind":"pull_request","number":2740},"comment_id":9100005,"request_id":"dr_loops_summary","request_kind":"grill_confirmation","fingerprint":"5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b","grill_file":"docs/grills/2030-01-10-notices.md"}\n\nconfirm');
    assert.deepEqual(fx.api.calls.map((c) => [c.id, c.text]), [[TARGET, outgoing]]);
  } finally { await p.close(); await fx.close(); }
});

test('EP4: no target, unknown risk, changed or unverified wording and a stale read never offer an answer, and say why', async () => {
  const cases = [
    ['no target', (d) => { d.orchestrator.target = { known: null }; }, GRILL, 'L4', 'answer unavailable: orchestrator not configured or not found'],
    ['unknown target', (d) => { d.orchestrator.target = { unknown: 'Synthetic target check timed out' }; d.orchestrator.coverage = { state: 'partial', gaps: [{ kind: 'timed_out', detail: 'Synthetic target check timed out' }] }; }, SPEC, null, 'answer unavailable: orchestrator not configured or not found'],
    ['unknown risk', (d) => { d.items[1].request.risk = 'unknown'; }, SPEC, null, 'answer unavailable: its risk is not classified'],
    ['changed', (d) => { d.items[2].current = { known: false }; }, PLAN, null, 'answer unavailable: wording changed since it was read'],
    ['unverified', (d) => { d.items[0].current = { unknown: 'Synthetic grill file not read at its head' }; }, GRILL, 'L5', 'answer unavailable: current wording could not be verified (Synthetic grill file not read at its head)'],
    ['stale', (d) => Object.assign(d, aged(d, 80_000)), SPEC, null, 'answer unavailable: this read is not fresh; refresh it'],
  ];
  for (const [name, change, comment, question, reason] of cases) {
    const fx = await decisionsSite();
    fx.doc = structuredClone(fx.doc);
    change(fx.doc);
    const p = await openDecisions(browser, fx, PHONE);
    try {
      const s = slot(p.page, comment, question);
      assert.equal(await s.count(), 1, `${name}: the card stays visible`);
      assert.equal(await why(s), reason, name);
      assert.equal(await s.locator('button:not([disabled])').count(), 0, `${name}: no enabled answer`);
      assert.equal(sends(fx).length, 0);
      assert.equal(p.requests.filter((r) => r.method !== 'GET').length, 0, `${name}: nothing written`);
    } finally { await p.close(); await fx.close(); }
  }
});

test('EP4: a fresh read ages on this clock: past 70 s an open confirmation loses its authority', async () => {
  const fx = await decisionsSite();
  fx.doc = aged(fx.doc, 30_000);
  const p = await openDecisions(browser, fx, DESKTOP);
  try {
    const s = slot(p.page, SPEC);
    await button(s, 'Confirm spec #2800, sends confirm spec #2800').click();
    await waitFor(async () => (await s.locator('[data-part=send]').getAttribute('aria-disabled')) === null, { what: 'Send ready' });
    fx.reply = json(503, { error: { kind: 'busy', message: 'synthetic: busy' } });
    await p.page.clock.runFor(41_000);
    await waitFor(async () => (await s.locator('[data-part=send]').count()) === 0, { what: 'the Send withdrawn' });
    assert.equal(await s.locator('[data-part=changed]').textContent(), 'This changed — read again. Nothing sent.');
    assert.equal(await why(s), 'answer unavailable: this read is not fresh; refresh it');
    assert.equal(sends(fx).length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('EP3: “Nothing waiting on you” only after a complete, fresh, empty read; partial and stale say so instead', async () => {
  const fx = await decisionsSite(load('empty'));
  const p = await openDecisions(browser, fx, DESKTOP);
  try {
    const empty = p.page.locator('[data-part=decisions-empty]');
    assert.equal(await empty.textContent(), 'Nothing waiting on you');
    fx.doc = structuredClone(fx.doc);
    fx.doc.coverage = { state: 'partial', gaps: [{ kind: 'malformed', detail: 'Synthetic comment held a malformed decision record' }] };
    await refresh(p.page);
    assert.equal(await empty.textContent(), 'No decisions read: this read is partial, so something may still wait on you');
    assert.match(await p.page.locator('[data-part=freshness]').textContent(), /Partial · read \d\d:\d\d:\d\d · 1 gap/);
    fx.doc = aged(load('empty'), 80_000);
    await refresh(p.page);
    assert.match(await empty.textContent(), /^None as of \d\d:\d\d:\d\d: this read is stale$/);
    assert.match(await p.page.locator('[data-part=freshness]').textContent(), /^Stale · read \d\d:\d\d:\d\d/);
  } finally { await p.close(); await fx.close(); }
});

test('EP3: a malformed response is a failed read, never an empty list; the last good snapshot stays', async () => {
  const fx = await decisionsSite();
  const p = await openDecisions(browser, fx, DESKTOP);
  try {
    assert.equal(await card(p.page, GRILL).count(), 1);
    const good = fx.doc;
    for (const [n, bad] of [
      '{"schema":"openwiz.decisions.v1","schema":"openwiz.decisions.v1"}',
      JSON.stringify({ ...good, items: [{ ...good.items[0], request: { ...good.items[0].request, status: 'resolved' } }] }),
      JSON.stringify({ ...good, items: [good.items[1], good.items[0]] }),
      JSON.stringify({ ...good, items: [{ ...good.items[0], request: { ...good.items[0].request, answered: ['L4', 'L3'] } }] }),
      JSON.stringify({ ...good, items: [{ ...good.items[2], request: { ...good.items[2].request, graph: [] } }] }),
      // A question id is one or two capital topic letters and a positive counter (crates/server's question_id).
      ...['L0', 'l4', 'ABC4', 'L4\n', 'L04'].map((id) => JSON.stringify({ ...good, items: [{ ...good.items[0], request: { ...good.items[0].request, answered: [], questions: [{ ...good.items[0].request.questions[1], id }] } }] })),
      // A round or summary is on its grill's PR; a spec or plan request on its own spec issue.
      JSON.stringify({ ...good, items: [{ ...good.items[0], subject: { kind: 'issue', number: 2731 } }] }),
      JSON.stringify({ ...good, items: [{ ...good.items[1], subject: { kind: 'pull_request', number: 2800 } }] }),
      JSON.stringify({ ...good, items: [{ ...good.items[2], subject: { kind: 'issue', number: 2901 } }] }),
    ].entries()) {
      fx.reply = { status: 200, headers: { 'Content-Type': 'application/json' }, body: bad };
      const reads = fx.reads;
      const seq = await p.page.locator('[data-part=decisions]').getAttribute('data-snapshot-seq');
      // A refused 200 keeps the read lane until its hold ends (src/api.ts's serverDone), so the poller's own
      // next read is the one to wait for: the paused clock moves until the server sees it.
      for (let i = 0; i < 6 && fx.reads === reads; i++) {
        await p.page.clock.runFor(71_000);
        await waitFor(() => fx.reads > reads, { timeout: 1_500, what: 'a read' }).catch(() => {});
      }
      assert.ok(fx.reads > reads, 'the bad read was made');
      await waitFor(() => pageIdle(p.page), { what: 'the read consumed' });
      assert.equal(await p.page.locator('[data-part=decisions]').getAttribute('data-snapshot-seq'), seq, `case ${n} refused, never shown`);
      assert.ok((await p.page.locator('[data-part=decisions] [data-notice]').count()) > 0, 'the failed read is shown');
      assert.equal(await p.page.locator('[data-part=decisions-empty]').count(), 0, 'never an empty claim');
      assert.equal(await card(p.page, GRILL).count(), 1, 'the last good snapshot stays');
    }
    assert.equal(sends(fx).length, 0);
  } finally { await p.close(); await fx.close(); }
});
