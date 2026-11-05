// EP4 (#656, spec #648): a decision card's answer is one send through the
// existing send path (the core's preview, then the owner's press), worded
// from the card, with request/revision context and a verbatim answer segment, to the configured orchestrator thread. A risky record
// (live, release, publish) confirms twice. A double click, a held key, a lost
// answer with a retry, and a reload never make a second provider call. Every
// expected text and id is a synthetic literal from test/fixtures/decisions/.

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, PHONE, pageIdle, waitFor } from '../support/browser.mjs';
import { DROP } from '../support/fake-api.mjs';
import { DELIVERIES, outcome as result, report } from '../support/synthetic.ts';
import { card, decisionsSite, openDecisions, refresh, sends, showDecisions, slot, TARGET } from '../fixtures/decisions/decisions.mjs';

const GRILL = 9100001;
const SPEC = 9100002;
const PLAN = 9100003;
const SENT = 9100004;

// EP4/EP3 (#2259): literals from the saved synthetic requests, in the
// contract's fixed order. Payload extends from the blank line to message EOF.
const ROUND_HEADER = 'openwiz decision answer v1\n{"subject":{"repository":"synthetic-owner/synthetic-repo","kind":"pull_request","number":2731},"comment_id":9100001,"request_id":"dr_loops_r2","request_kind":"grill_round","fingerprint":"1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f","grill_file":"docs/grills/2030-01-15-loops.md","round":2,"question_id":"L4"}\n\n';
const L5_HEADER = ROUND_HEADER.replace('"question_id":"L4"', '"question_id":"L5"');
const SPEC_HEADER = 'openwiz decision answer v1\n{"subject":{"repository":"synthetic-owner/synthetic-repo","kind":"issue","number":2800},"comment_id":9100002,"request_id":"dr_spec_2800","request_kind":"spec_confirmation","fingerprint":"2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e","spec":2800}\n\n';
const PLAN_HEADER = 'openwiz decision answer v1\n{"subject":{"repository":"synthetic-owner/synthetic-repo","kind":"issue","number":2900},"comment_id":9100003,"request_id":"dr_plan_2900","request_kind":"plan_approval","fingerprint":"3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d","spec":2900}\n\n';
const SENT_HEADER = 'openwiz decision answer v1\n{"subject":{"repository":"synthetic-owner/synthetic-repo","kind":"issue","number":2790},"comment_id":9100004,"request_id":"dr_spec_2790","request_kind":"spec_confirmation","fingerprint":"4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c","spec":2790}\n\n';
const ROUND_YES = ROUND_HEADER + 'L4 yes';
const PLAN_APPROVE = PLAN_HEADER + 'approve #2900';
const SPEC_CONFIRM = SPEC_HEADER + 'confirm spec #2800';
const SENT_CONFIRM = SENT_HEADER + 'confirm spec #2790';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const button = (s, name) => s.getByRole('button', { name, exact: true });
const sendButton = (s) => s.locator('[data-part=send]');
const state = (s) => s.locator('[data-part=outcome]').getAttribute('data-state');
const settled = (fx) => fx.api.log.filter((e) => e.kind === 'send').every((e) => e.endedAt !== null);

/** Waits until the final Send is ready to press: the core's preview has been read. */
async function ready(page, s) {
  await waitFor(async () => (await sendButton(s).count()) === 1 && (await sendButton(s).getAttribute('aria-disabled')) === null, { what: 'Send ready' });
  await waitFor(() => pageIdle(page), { what: 'the preview consumed' });
}

/** Presses the final Send and waits for its answer. */
async function sendAndSettle(fx, page, s) {
  await ready(page, s);
  await sendButton(s).click();
  await waitFor(async () => (await state(s)) === 'sent', { what: 'sent' });
  await waitFor(() => settled(fx), { what: 'every send answered' });
}

test('EP4: Yes previews, then one press sends “L4 yes” once; a double click and a held Enter add no send (both widths)', async () => {
  for (const viewport of [DESKTOP, PHONE]) {
    const fx = await decisionsSite();
    const p = await openDecisions(browser, fx, viewport);
    try {
      const s = slot(p.page, GRILL, 'L4');
      assert.equal(await s.locator('[data-part=sends]').first().textContent(), 'Sends: L4 yes + request and revision context', 'each action shows its exact words');
      // A double click on Yes is one choice: its second click is no send.
      await button(s, 'Yes, sends L4 yes').dblclick();
      await ready(p.page, s);
      assert.equal(sends(fx).length, 0, 'choosing never sends');
      assert.equal(await s.locator('[data-part=outgoing]').textContent(), ROUND_YES);
      assert.equal(fx.api.log.filter((e) => e.kind === 'preview' && e.path === `/api/v1/sessions/${TARGET}/preview`).length, 1, 'the core’s preview, read once');
      assert.notEqual(await s.locator('[data-part=effect]').textContent(), '', 'what a send would do is shown');
      fx.api.hold('send');
      await sendButton(s).dblclick();
      await waitFor(() => fx.api.held('send') === 1, { what: 'one held send' });
      fx.api.release('send');
      await waitFor(async () => (await state(s)) === 'sent', { what: 'sent' });
      await waitFor(() => settled(fx), { what: 'every send answered' });
      assert.equal(sends(fx).length, 1);
      assert.equal(fx.api.calls.length, 1);
      assert.deepEqual([fx.api.calls[0].id, fx.api.calls[0].mode, fx.api.calls[0].text], [TARGET, 'queue', ROUND_YES]);
      assert.equal(await button(s, 'Yes, sends L4 yes').count(), 0, 'an answered question offers no second answer');
      assert.match(await s.locator('[data-part=sent]').textContent(), /^openwiz decision answer v1[\s\S]*\n\nL4 yes · sent \d\d:\d\d · waiting for the orchestrator to save it$/);
      assert.equal(await button(slot(p.page, GRILL, 'L5'), 'Yes, sends L5 yes').count(), 1, 'the other question keeps its own answer');
      assert.deepEqual(p.errors, []);
    } finally { await p.close(); await fx.close(); }
  }

  // A held Enter: its repeats never send, and a fresh press sends once.
  const fx = await decisionsSite();
  const p = await openDecisions(browser, fx, PHONE);
  try {
    const s = slot(p.page, GRILL, 'L4');
    await button(s, 'Simplify, sends simplify L4').focus();
    await p.page.keyboard.down('Enter');
    await ready(p.page, s);
    for (let i = 0; i < 8; i++) await p.page.keyboard.down('Enter');
    assert.equal(sends(fx).length, 0, 'the held key that chose Simplify is not its send');
    assert.equal(await sendButton(s).evaluate((b) => document.activeElement === b), true, 'the Send takes focus');
    await p.page.keyboard.up('Enter');
    await p.page.keyboard.down('Enter');
    await waitFor(async () => (await state(s)) === 'sent', { what: 'sent' });
    for (let i = 0; i < 8; i++) await p.page.keyboard.down('Enter');
    await p.page.keyboard.up('Enter');
    await waitFor(() => settled(fx), { what: 'every send answered' });
    assert.equal(sends(fx).length, 1);
    assert.deepEqual(fx.api.calls.map((c) => c.text), [ROUND_HEADER + 'simplify L4']);
  } finally { await p.close(); await fx.close(); }
});

test('EP4: own words are sent exactly as typed, byte for byte, inside request/revision context; empty or blank text sends nothing', async () => {
  const WORDS = '  Only on the PC hub for now.\nPhone stays quiet — für jetzt. \n\n';
  const fx = await decisionsSite();
  const p = await openDecisions(browser, fx, DESKTOP);
  try {
    const s = slot(p.page, GRILL, 'L5');
    await button(s, 'Own words').click();
    const field = s.getByRole('textbox', { name: 'Your words for L5' });
    assert.equal(await s.locator('[data-part=own-note]').textContent(), 'Your answer stays exactly as typed inside request and revision context');
    const sendWords = button(s, 'Send my words');
    assert.equal(await sendWords.isDisabled(), true, 'nothing typed, nothing to send');
    await field.fill(' \n\t ');
    assert.equal(await sendWords.isDisabled(), true, 'blank text is not an answer');
    await field.fill('');
    // Enter in the field is a new line; it never sends.
    await field.pressSequentially('  Only on the PC hub for now.');
    await p.page.keyboard.press('Enter');
    await field.pressSequentially('Phone stays quiet — für jetzt. ');
    await p.page.keyboard.press('Enter');
    await p.page.keyboard.press('Enter');
    assert.equal(await field.inputValue(), WORDS);
    assert.equal(sends(fx).length, 0, 'typing and Enter never send');
    await sendWords.click();
    await ready(p.page, s);
    assert.equal(await s.locator('[data-part=outgoing]').textContent(), L5_HEADER + WORDS, 'the exact outgoing words are shown');
    await sendAndSettle(fx, p.page, s);
    assert.equal(fx.api.calls.length, 1);
    assert.equal(fx.api.calls[0].text, L5_HEADER + WORDS, 'every byte typed, leading and trailing whitespace and newlines included; only the payload is the typed answer');
    assert.deepEqual(Buffer.from(fx.api.calls[0].text.slice(L5_HEADER.length)), Buffer.from(WORDS), 'UTF-8 answer recovered exactly');
    assert.equal(fx.api.calls[0].id, TARGET);
  } finally { await p.close(); await fx.close(); }
});

test('EP4: an own-words draft survives a re-read of the unchanged record; a changed record invalidates it and says so', async () => {
  const fx = await decisionsSite();
  const p = await openDecisions(browser, fx, DESKTOP);
  try {
    const s = slot(p.page, GRILL, 'L5');
    await button(s, 'Own words').click();
    await s.getByRole('textbox', { name: 'Your words for L5' }).fill('Keep it on the PC.');
    await refresh(p.page);
    assert.equal(await s.getByRole('textbox', { name: 'Your words for L5' }).inputValue(), 'Keep it on the PC.', 'a re-read keeps the draft');
    fx.doc = structuredClone(fx.doc);
    fx.doc.items[0].request.fingerprint = '6a'.repeat(32);
    await refresh(p.page);
    assert.equal(await s.locator('[data-part=changed]').textContent(), 'This changed — read again. Nothing sent.');
    assert.equal(await button(s, 'Send my words').count(), 0, 'no send survives the change');
    assert.equal(sends(fx).length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('EP4: a spec confirmation sends “confirm spec #2800” once; a release plan approval confirms twice, and Escape or Cancel go back', async () => {
  for (const viewport of [DESKTOP, PHONE]) {
    const fx = await decisionsSite();
    const p = await openDecisions(browser, fx, viewport);
    try {
      const spec = slot(p.page, SPEC);
      await button(spec, 'Confirm spec #2800, sends confirm spec #2800').click();
      await sendAndSettle(fx, p.page, spec);
      assert.deepEqual(fx.api.calls.map((c) => c.text), [SPEC_CONFIRM]);

      const plan = slot(p.page, PLAN);
      assert.equal(await card(p.page, PLAN).locator('[data-part=risk]').textContent(), 'Release · asks twice');
      const approve = button(plan, 'Approve #2900, sends approve #2900');
      await approve.dblclick();
      await waitFor(() => plan.locator('[data-part=armed]').count(), { what: 'the second confirmation' });
      assert.equal(await plan.locator('[data-part=arm-note]').textContent(), 'This approves a release. Send “approve #2900” with request and revision context to the orchestrator?');
      assert.equal(await sendButton(plan).count(), 0, 'one double click opens the second confirmation only');
      await p.page.keyboard.press('Escape');
      await waitFor(async () => (await approve.count()) === 1, { what: 'Escape goes back' });
      await waitFor(() => approve.evaluate((b) => document.activeElement === b), { what: 'focus back on Approve after Escape' });
      await approve.click();
      await button(plan, 'Cancel').click();
      assert.equal(await approve.count(), 1, 'Cancel goes back');
      await waitFor(() => approve.evaluate((b) => document.activeElement === b), { what: 'focus back on Approve after Cancel' });
      await approve.click();
      await button(plan, 'Yes, approve #2900').dblclick();
      await ready(p.page, plan);
      assert.equal(await sendButton(plan).textContent(), 'Send: confirmed twice');
      assert.equal(sends(fx).length, 1, 'two confirmations, then the send: nothing before it');
      await sendButton(plan).dblclick();
      await waitFor(async () => (await state(plan)) === 'sent', { what: 'sent' });
      await waitFor(() => settled(fx), { what: 'every send answered' });
      assert.deepEqual(fx.api.calls.map((c) => [c.id, c.text]), [[TARGET, SPEC_CONFIRM], [TARGET, PLAN_APPROVE]]);
    } finally { await p.close(); await fx.close(); }
  }
});

test('EP4: a lost answer is uncertain; after a reload, Try again replays the same op id: one provider call, and no second answer', async () => {
  const fx = await decisionsSite();
  fx.api.setSend((id, b) => ({ after: DROP, report: report(id, b.op_id, b.mode, b.text, result(DELIVERIES.sent)) }));
  const p = await openDecisions(browser, fx, PHONE);
  try {
    const s = () => slot(p.page, GRILL, 'L4');
    await button(s(), 'Yes, sends L4 yes').click();
    await ready(p.page, s());
    await sendButton(s()).click();
    await waitFor(async () => (await state(s())) === 'unknown', { what: 'uncertain' });
    assert.match(await s().locator('[data-part=outcome]').textContent(), /^Uncertain: it may or may not have been sent.*Nothing is sent again on its own\.$/);
    await p.page.clock.runFor(120_000);
    assert.equal(sends(fx).length, 1, 'no retry on its own');
    await p.page.reload();
    await showDecisions(p.page);
    await waitFor(async () => (await state(s())) === 'unknown', { what: 'still uncertain after the reload' });
    assert.equal(await button(s(), 'Yes, sends L4 yes').count(), 0, 'an unresolved answer is never offered again');
    assert.equal(await button(s(), 'Simplify, sends simplify L4').count(), 0, 'nor a different one for the same question');
    await s().locator('[data-part=send]', { hasText: 'Try again' }).click();
    await waitFor(async () => (await state(s())) === 'sent', { what: 'the replay settles it' });
    await waitFor(() => settled(fx), { what: 'every send answered' });
    assert.equal(sends(fx).length, 2);
    assert.equal(sends(fx)[1].op_id, sends(fx)[0].op_id, 'the same op id');
    assert.equal(sends(fx)[1].text, ROUND_YES);
    assert.equal(fx.api.calls.length, 1, 'one provider call');
    await p.page.reload();
    await showDecisions(p.page);
    assert.match(await s().locator('[data-part=sent]').textContent(), /^openwiz decision answer v1[\s\S]*\n\nL4 yes · sent \d\d:\d\d · waiting for the orchestrator to save it$/, 'a reload keeps the receipt until the record is saved');
    assert.equal(await button(s(), 'Yes, sends L4 yes').count(), 0, 'a reload never offers a sent answer again');
    assert.equal(sends(fx).length, 2);
  } finally { await p.close(); await fx.close(); }
});

test('EP4: two cards to the same orchestrator keep their own answers; a saved answer leaves the read and its question with it', async () => {
  const fx = await decisionsSite();
  const p = await openDecisions(browser, fx, DESKTOP);
  try {
    await button(slot(p.page, GRILL, 'L4'), 'Yes, sends L4 yes').click();
    await sendAndSettle(fx, p.page, slot(p.page, GRILL, 'L4'));
    await button(slot(p.page, SENT), 'Confirm spec #2790, sends confirm spec #2790').click();
    await sendAndSettle(fx, p.page, slot(p.page, SENT));
    assert.deepEqual(fx.api.calls.map((c) => c.text), [ROUND_YES, SENT_CONFIRM]);
    assert.equal(new Set(sends(fx).map((b) => b.op_id)).size, 2, 'one op id per answer');
    assert.equal(await button(slot(p.page, GRILL, 'L5'), 'Yes, sends L5 yes').count(), 1, 'L5 is still open');
    await p.page.reload();
    await showDecisions(p.page);
    assert.match(await slot(p.page, GRILL, 'L4').locator('[data-part=sent]').textContent(), /^openwiz decision answer v1[\s\S]*\n\nL4 yes · sent/);
    assert.match(await slot(p.page, SENT).locator('[data-part=sent]').textContent(), /^openwiz decision answer v1[\s\S]*\n\nconfirm spec #2790 · sent/);
    // The orchestrator saves L4: the read no longer offers it.
    fx.doc = structuredClone(fx.doc);
    fx.doc.items[0].request.answered = ['L3', 'L4'];
    await refresh(p.page);
    assert.equal(await slot(p.page, GRILL, 'L4').count(), 0, 'a saved question is gone');
    assert.equal(await card(p.page, GRILL).locator('[data-part=progress]').textContent(), '2 of 3 answered');
    assert.equal(sends(fx).length, 2);
  } finally { await p.close(); await fx.close(); }
});

test('EP4: a record or target that changes mid-confirmation cancels it: “This changed — read again. Nothing sent.”', async () => {
  for (const change of [
    (doc) => { doc.items[2].request.fingerprint = '7b'.repeat(32); },
    (doc) => { doc.orchestrator.target = { known: 'thr_syn_9f00aa' }; },
    (doc) => { doc.items.splice(2, 1); },
  ]) {
    const fx = await decisionsSite();
    const p = await openDecisions(browser, fx, DESKTOP);
    try {
      const plan = slot(p.page, PLAN);
      await button(plan, 'Approve #2900, sends approve #2900').click();
      await button(plan, 'Yes, approve #2900').click();
      await ready(p.page, plan);
      fx.doc = structuredClone(fx.doc);
      change(fx.doc);
      await refresh(p.page);
      if ((await plan.count()) === 1) {
        assert.equal(await plan.locator('[data-part=changed]').textContent(), 'This changed — read again. Nothing sent.');
        assert.equal(await sendButton(plan).count(), 0, 'no send survives the change');
      }
      assert.equal(sends(fx).length, 0);
    } finally { await p.close(); await fx.close(); }
  }
});

test('EP4: a live round asks twice for own words too, and sends them exactly; a publish confirmation asks twice', async () => {
  const fx = await decisionsSite();
  fx.doc = structuredClone(fx.doc);
  fx.doc.items[0].request.risk = 'live';
  fx.doc.items[1].request.risk = 'publish';
  const p = await openDecisions(browser, fx, PHONE);
  try {
    assert.equal(await card(p.page, GRILL).locator('[data-part=risk]').textContent(), 'Live · asks twice');
    const s = slot(p.page, GRILL, 'L5');
    await button(s, 'Own words').click();
    await s.getByRole('textbox', { name: 'Your words for L5' }).fill('Only on the PC hub.\n');
    await button(s, 'Send my words').click();
    assert.equal(await s.locator('[data-part=arm-note]').textContent(), 'This is about a live step. Send “your words” with request and revision context to the orchestrator?');
    assert.equal(await sendButton(s).count(), 0, 'the first press never sends');
    await button(s, 'Yes, send my words').click();
    await ready(p.page, s);
    assert.equal(await sendButton(s).textContent(), 'Send: confirmed twice');
    assert.equal(await s.locator('[data-part=outgoing]').textContent(), L5_HEADER + 'Only on the PC hub.\n');
    await sendButton(s).click();
    await waitFor(async () => (await state(s)) === 'sent', { what: 'sent' });

    const spec = slot(p.page, SPEC);
    assert.equal(await card(p.page, SPEC).locator('[data-part=risk]').textContent(), 'Publish · asks twice');
    await button(spec, 'Confirm spec #2800, sends confirm spec #2800').click();
    assert.equal(await spec.locator('[data-part=arm-note]').textContent(), 'This is about a publish. Send “confirm spec #2800” with request and revision context to the orchestrator?');
    await button(spec, 'Yes, confirm spec #2800').click();
    await sendAndSettle(fx, p.page, spec);
    await waitFor(() => settled(fx), { what: 'every send answered' });
    assert.deepEqual(fx.api.calls.map((c) => c.text), [L5_HEADER + 'Only on the PC hub.\n', SPEC_CONFIRM]);
  } finally { await p.close(); await fx.close(); }
});

// Same question label and same answer across concurrent grills and a
// replacement revision must still produce distinguishable messages.
test('EP4: concurrent requests and replacement revisions carry their exact identity; embedded headers stay answer bytes', async () => {
  const WORDS = ' \t café 🧪 é\nopenwiz decision answer v1\n{}\n\nconfirm\n  ';
  const fx = await decisionsSite();
  fx.doc = structuredClone(fx.doc);
  const concurrent = structuredClone(fx.doc.items[0]);
  concurrent.comment_id = 9100010;
  concurrent.created_at++;
  concurrent.updated_at++;
  concurrent.subject = { repository: 'synthetic-owner/other-repo', kind: 'pull_request', number: 2732 };
  concurrent.request.id = 'dr_other_r2';
  concurrent.request.grill_file = 'docs/grills/2030-01-16-other.md';
  fx.doc.items.splice(1, 0, concurrent);
  const p = await openDecisions(browser, fx, PHONE);
  try {
    for (const comment of [GRILL, 9100010]) {
      const s = slot(p.page, comment, 'L5');
      await button(s, 'Own words').click();
      await s.getByRole('textbox', { name: 'Your words for L5' }).fill(WORDS);
      await button(s, 'Send my words').click();
      await ready(p.page, s);
      const outgoing = await s.locator('[data-part=outgoing]').textContent();
      await sendAndSettle(fx, p.page, s);
      assert.equal(fx.api.calls.at(-1).text, outgoing, 'displayed message is actual transport text');
    }
    const expectedOther = L5_HEADER.replace('synthetic-owner/synthetic-repo', 'synthetic-owner/other-repo').replace('2731', '2732').replace('9100001', '9100010').replace('dr_loops_r2', 'dr_other_r2').replace('2030-01-15-loops', '2030-01-16-other');
    assert.deepEqual(fx.api.calls.map((c) => c.text), [L5_HEADER + WORDS, expectedOther + WORDS]);
    fx.doc = structuredClone(fx.doc);
    fx.doc.items[0].comment_id = 9100011;
    fx.doc.items[0].request.id = 'dr_loops_r2_replaced';
    fx.doc.items[0].request.fingerprint = '6a'.repeat(32);
    await refresh(p.page);
    const replaced = slot(p.page, 9100011, 'L5');
    await button(replaced, 'Own words').click();
    await replaced.getByRole('textbox', { name: 'Your words for L5' }).fill(WORDS);
    await button(replaced, 'Send my words').click();
    await ready(p.page, replaced);
    const expected = L5_HEADER.replace('9100001', '9100011').replace('dr_loops_r2', 'dr_loops_r2_replaced').replace('1f'.repeat(32), '6a'.repeat(32));
    assert.equal(await replaced.locator('[data-part=outgoing]').textContent(), expected + WORDS);
    await sendAndSettle(fx, p.page, replaced);
    assert.equal(fx.api.calls.length, 3);
    assert.equal(new Set(fx.api.calls.map((c) => c.text)).size, 3);
    for (const c of fx.api.calls) {
      const boundary = c.text.indexOf('\n\n');
      assert.notEqual(boundary, -1);
      assert.deepEqual(Buffer.from(c.text.slice(boundary + 2)), Buffer.from(WORDS), 'only first boundary counts; payload ends at EOF');
    }
    assert.equal(fx.api.calls[2].text, expected + WORDS);
    assert.equal(new Set(sends(fx).map((b) => b.op_id)).size, 3);
  } finally { await p.close(); await fx.close(); }
});

// EP4: context counts toward the existing HTTP body limit. The bare JSON
// body fits that cap; attribution crosses it and must refuse, never split.
// This fake-transport proof does not exercise the core’s smaller text limit.
test('EP4: an oversized contextual message is previewed whole and refused without a provider call', async () => {
  const WORDS = 'word '.repeat(19_800);
  const fx = await decisionsSite();
  const p = await openDecisions(browser, fx, PHONE);
  try {
    const s = slot(p.page, GRILL, 'L5');
    await button(s, 'Own words').click();
    await s.getByRole('textbox', { name: 'Your words for L5' }).fill(WORDS);
    await button(s, 'Send my words').click();
    await ready(p.page, s);
    assert.equal(await s.locator('[data-part=outgoing]').textContent(), L5_HEADER + WORDS);
    await sendButton(s).click();
    await waitFor(async () => await state(s) === 'not-sent', { what: 'size refusal' });
    const posts = fx.api.log.filter((e) => e.kind === 'send' && e.method === 'POST');
    assert.equal(posts.length, 1, 'no splitting or batching');
    assert.equal(posts[0].status, 413, 'existing body-size refusal');
    assert.equal(fx.api.calls.length, 0, 'nothing reaches provider');
    assert.equal(await s.locator('[data-part=outcome]').textContent(), 'Not sent: not-sent');
  } finally { await p.close(); await fx.close(); }
});
