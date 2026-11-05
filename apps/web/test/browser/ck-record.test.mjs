// CK2's answer record (#536, the self-review's findings on efd706a0): an
// answer is bound to the item it was made for. The record is kept before the
// send leaves, so a tab that can't keep it sends nothing, and a reload never
// offers a second answer; an unresolved answer is never retried for a changed
// proposal or another target; a change disarms for good; a new proposal on an
// answered item can be answered; Try again needs the core's preview; focus
// never falls to the page while a send is out; Reply opens the orchestrator's
// message box without sending. Synthetic literals only.

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, PHONE, pageIdle, waitFor } from '../support/browser.mjs';
import { readComposer } from '../support/composer.mjs';
import { DROP, json } from '../support/fake-api.mjs';
import { DELIVERIES, outcome as result, preview, report, session, sessionView } from '../support/synthetic.ts';
import { cockpitSite, openCockpit, refresh, row, sends, showCockpit } from '../fixtures/cockpit/cockpit.mjs';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const yes = (page, ticket = 904) => row(page, ticket).getByRole('button', { name: /^Yes to item/ });
const sendButton = (page, ticket = 904) => row(page, ticket).locator('[data-part=send]');
const tryAgain = (page, ticket = 904) => row(page, ticket).locator('[data-part=send]', { hasText: 'Try again' });
const state = (page, ticket = 904) => row(page, ticket).locator('[data-part=outcome]').getAttribute('data-state');
const lost = (id, b) => ({ after: DROP, report: report(id, b.op_id, b.mode, b.text, result(DELIVERIES.sent)) });
const sent = (id, b) => json(200, report(id, b.op_id, b.mode, b.text, result(DELIVERIES.sent)));

async function ready(page, ticket = 904) {
  await waitFor(async () => (await sendButton(page, ticket).count()) === 1 && (await sendButton(page, ticket).getAttribute('aria-disabled')) === null, { what: `#${ticket}'s Send ready` });
  await waitFor(() => pageIdle(page), { what: 'the preview consumed' });
}
async function answerYes(page, ticket = 904) {
  await yes(page, ticket).click();
  await ready(page, ticket);
  await sendButton(page, ticket).click();
}
const settled = (fx) => fx.api.log.filter((e) => e.kind === 'send').every((e) => e.endedAt !== null);

/** In the page: this tab's storage refuses the cockpit's answer records after `allowed` writes (the composer's own still work). */
function refuseRecords(allowed) {
  let writes = 0;
  const set = Storage.prototype.setItem;
  Storage.prototype.setItem = function (k, v) {
    if (/^openwiz\.cockpit\..*\.answer(ed)?$/.test(k) && writes++ >= allowed) throw new DOMException('quota', 'QuotaExceededError');
    return set.call(this, k, v);
  };
}

test('R1: a tab that can’t keep its result still never offers a sent answer again after a reload', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, PHONE);
  try {
    await p.page.addInitScript(refuseRecords, 1);
    await p.page.evaluate(refuseRecords, 1);
    await answerYes(p.page);
    await waitFor(() => fx.api.calls.length === 1 && settled(fx), { what: 'one send' });
    // The page has read the send's answer (not only the server sent it) before the reload,
    // or the reload can abort it first and leave it uncertain (CI, 77a6a1c8).
    await waitFor(async () => /^Answered: Yes/.test(await row(p.page, 904).locator('[data-part=outcome]').textContent()) && (await pageIdle(p.page)), { what: 'the answer read by the page' });
    assert.equal(await state(p.page), 'pending', 'its result could not be kept, so the record stays pending');
    await p.page.reload();
    await showCockpit(p.page);
    assert.equal(await yes(p.page).count(), 0, 'no second answer after a reload');
    assert.match(await row(p.page, 904).locator('[data-part=outcome]').textContent(), /^Answered: Yes/);
    assert.equal(fx.api.calls.length, 1);
  } finally { await p.close(); await fx.close(); }
});

test('R1: when the record can’t be kept before the send, nothing is sent, and the row says why', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, PHONE);
  try {
    await p.page.evaluate(refuseRecords, 0);
    await answerYes(p.page);
    await waitFor(async () => /can’t keep/.test(await row(p.page, 904).locator('[data-part=effect]').textContent()), { what: 'the reason shown' });
    await p.page.clock.runFor(1_000);
    assert.equal(sends(fx).length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('R2, R3: an unresolved answer is never retried for a changed proposal, and stays shown under its own target', async () => {
  for (const change of [
    (doc) => { doc.needs_you.items[0].wording = { known: 'Synthetic: a completely different proposal?' }; doc.needs_you.items[0].risky = { known: true }; },
    (doc) => { doc.projects.items[0].orchestrator.target = { known: 'thr_syn_0009' }; },
  ]) {
    const fx = await cockpitSite();
    fx.api.setSend(lost);
    const p = await openCockpit(browser, fx, DESKTOP);
    try {
      await answerYes(p.page);
      await waitFor(async () => (await state(p.page)) === 'unknown', { what: 'uncertain' });
      fx.doc = structuredClone(fx.doc);
      change(fx.doc);
      await refresh(p.page);
      assert.equal(await state(p.page), 'unknown', 'the old attempt stays shown');
      assert.equal(await tryAgain(p.page).count(), 0, 'no Try again for another binding');
      assert.equal(await yes(p.page).count(), 0, 'no second answer while one may be on its way');
      assert.equal(await row(p.page, 904).locator('[data-part=earlier]').count(), 1);
      assert.equal(sends(fx).length, 1);
    } finally { await p.close(); await fx.close(); }
  }
});

test('R4: a change disarms for good: the proposal coming back needs a new choice', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await yes(p.page).click();
    await ready(p.page);
    const original = fx.doc;
    fx.doc = structuredClone(original);
    fx.doc.needs_you.items[0].wording = { known: 'Synthetic: a changed proposal?' };
    await refresh(p.page);
    fx.doc = original;
    await refresh(p.page);
    assert.equal(await sendButton(p.page).count(), 0, 'the old confirm never returns');
    assert.equal(await row(p.page, 904).locator('[data-part=changed]').textContent(), 'This item changed. Nothing sent.');
    assert.equal(await yes(p.page).count(), 1, 'a new choice is offered');
    assert.equal(sends(fx).length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('R5: a new proposal on an answered item can be answered without a reload', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await answerYes(p.page);
    await waitFor(async () => (await state(p.page)) === 'sent', { what: 'sent' });
    assert.equal(await yes(p.page).count(), 0);
    fx.doc = structuredClone(fx.doc);
    fx.doc.needs_you.items[0].wording = { known: 'Synthetic: and the follow-up plan?' };
    await refresh(p.page);
    assert.equal(await yes(p.page).count(), 1, 'the new proposal is a new question');
    await answerYes(p.page);
    await waitFor(() => fx.api.calls.length === 2 && settled(fx), { what: 'the second answer' });
    assert.notEqual(fx.api.calls[1].op_id, fx.api.calls[0].op_id);
    assert.match(fx.api.calls[1].text, /Proposal: Synthetic: and the follow-up plan\?$/);
  } finally { await p.close(); await fx.close(); }
});

test('R6: Try again after a reload waits for the core’s preview, and a refused preview keeps it off', async () => {
  const fx = await cockpitSite();
  fx.api.setSend(lost);
  const p = await openCockpit(browser, fx, PHONE);
  try {
    await answerYes(p.page);
    await waitFor(async () => (await state(p.page)) === 'unknown', { what: 'uncertain' });
    fx.api.setPreview((id, mode) => json(200, preview(id, 'refused', mode)));
    const before = fx.api.log.filter((e) => e.kind === 'preview').length;
    await p.page.reload();
    await showCockpit(p.page);
    await waitFor(() => fx.api.log.filter((e) => e.kind === 'preview').length > before && pageIdle(p.page), { what: 'a preview read after the reload' });
    assert.equal(await tryAgain(p.page).getAttribute('aria-disabled'), 'true', 'a refused preview keeps Try again off');
    await tryAgain(p.page).click({ force: true });
    assert.equal(sends(fx).length, 1);
    fx.api.setPreview((id, mode) => json(200, preview(id, 'idle', mode)));
    fx.api.setSend(sent);
    await p.page.reload();
    await showCockpit(p.page);
    await waitFor(async () => (await tryAgain(p.page).getAttribute('aria-disabled')) === null, { what: 'Try again on a ready preview' });
    await tryAgain(p.page).click();
    await waitFor(async () => (await state(p.page)) === 'sent', { what: 'the replay settles it' });
    assert.equal(new Set(sends(fx).map((b) => b.op_id)).size, 1);
    assert.equal(fx.api.calls.length, 1);
  } finally { await p.close(); await fx.close(); }
});

test('R8: while a send is out, focus stays on the row, never the page', async () => {
  const fx = await cockpitSite();
  fx.api.hold('send');
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await yes(p.page).click();
    await ready(p.page);
    await sendButton(p.page).focus();
    await p.page.keyboard.press('Enter');
    await waitFor(() => fx.api.held('send') === 1, { what: 'one held send' });
    await waitFor(() => p.page.evaluate(() => document.activeElement?.closest('li[data-ticket="904"]') !== null && document.activeElement !== document.body), { what: 'focus inside the row' });
    fx.api.release('send');
    await waitFor(async () => (await state(p.page)) === 'sent', { what: 'sent' });
  } finally { await p.close(); await fx.close(); }
});

test('Reply opens the orchestrator’s own message box, prefilled, and sends nothing', async () => {
  const fx = await cockpitSite();
  fx.api.setDetail((id) => json(200, sessionView(session(1, { id }))));
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await row(p.page, 904).getByRole('button', { name: /^Reply to item 1/ }).click();
    await waitFor(async () => (await readComposer(p.page))?.target === 'thr_syn_0001' && (await readComposer(p.page)).ready, { what: 'the orchestrator composer' });
    assert.equal((await readComposer(p.page)).draft, 'Answer for ticket #904 (spec #901):\n\n');
    assert.equal(sends(fx).length, 0);
  } finally { await p.close(); await fx.close(); }
});
