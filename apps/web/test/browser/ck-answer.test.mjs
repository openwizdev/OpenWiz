// CK2 (#536, spec #530): answering Needs you on page 1 of the cockpit, on the
// fake API. An answer is one send through the existing send path (the core's
// preview, then the owner's confirm), worded from the item, to its own
// project's orchestrator; a risky item confirms twice. A double click, a held
// key, a lost answer with a retry, and a reload never make a second provider
// call. Every expected text and id is a synthetic literal from
// test/fixtures/cockpit/.

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, PHONE, pageIdle, waitFor } from '../support/browser.mjs';
import { DROP, json } from '../support/fake-api.mjs';
import { DELIVERIES, outcome as result, report } from '../support/synthetic.ts';
import { aged, cockpitSite, openCockpit, refresh, row, sends, showCockpit } from '../fixtures/cockpit/cockpit.mjs';

const ATLAS = 'thr_syn_0001';
const LANTERN = 'thr_syn_0002';
const YES_904 = 'Answer for ticket #904 (spec #901, needs_info): Yes\n\nProposal: Approve the plan for #904: offline sync queue?';
const NO_904 = 'Answer for ticket #904 (spec #901, needs_info): No\n\nProposal: Approve the plan for #904: offline sync queue?';
const YES_712 = 'Answer for ticket #712 (spec #700, publish): Yes\n\nProposal: Publish release Lantern v0.4?';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const yes = (page, ticket) => row(page, ticket).getByRole('button', { name: /^Yes to item/ });
const no = (page, ticket) => row(page, ticket).getByRole('button', { name: /^No to item/ });
const sendButton = (page, ticket) => row(page, ticket).locator('[data-part=send]');
const state = (page, ticket) => row(page, ticket).locator('[data-part=outcome]').getAttribute('data-state');
const settled = (fx) => fx.api.log.filter((e) => e.kind === 'send').every((e) => e.endedAt !== null);

/** Waits until the final Send is ready to press: the core's preview has been read. */
async function ready(page, ticket) {
  await waitFor(async () => (await sendButton(page, ticket).count()) === 1 && (await sendButton(page, ticket).getAttribute('aria-disabled')) === null, { what: `#${ticket}'s Send ready` });
  await waitFor(() => pageIdle(page), { what: 'the preview consumed' });
}

test('CK2: Yes previews, then one confirm sends the item’s words once; a double click and a held Enter add no send (both widths)', async () => {
  for (const viewport of [DESKTOP, PHONE]) {
    const fx = await cockpitSite();
    const p = await openCockpit(browser, fx, viewport);
    try {
      // A double click on Yes is one choice: its second click is no confirm.
      await yes(p.page, 904).dblclick();
      await ready(p.page, 904);
      assert.equal(sends(fx).length, 0, 'choosing never sends');
      assert.equal(await sendButton(p.page, 904).textContent(), 'Send Yes');
      assert.equal(fx.api.log.filter((e) => e.kind === 'preview' && e.path === `/api/v1/sessions/${ATLAS}/preview`).length, 1, 'the core’s preview, read once');
      assert.notEqual(await row(p.page, 904).locator('[data-part=effect]').textContent(), '', 'what a send would do is shown');
      fx.api.hold('send');
      await sendButton(p.page, 904).dblclick();
      await waitFor(() => fx.api.held('send') === 1, { what: 'one held send' });
      fx.api.release('send');
      await waitFor(async () => (await state(p.page, 904)) === 'sent', { what: 'sent' });
      await waitFor(() => settled(fx), { what: 'every send answered' });
      assert.equal(sends(fx).length, 1);
      assert.equal(fx.api.calls.length, 1);
      assert.deepEqual([fx.api.calls[0].id, fx.api.calls[0].mode, fx.api.calls[0].text], [ATLAS, 'queue', YES_904]);
      assert.equal(await yes(p.page, 904).count(), 0, 'an answered item offers no second answer');
      assert.deepEqual(p.errors, []);
    } finally { await p.close(); await fx.close(); }
  }

  // A held Enter: its repeats never confirm, and a fresh press sends once.
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, PHONE);
  try {
    await no(p.page, 904).focus();
    await p.page.keyboard.down('Enter');
    await ready(p.page, 904);
    for (let i = 0; i < 8; i++) await p.page.keyboard.down('Enter');
    assert.equal(sends(fx).length, 0, 'the held key that chose No is not its confirm');
    assert.equal(await sendButton(p.page, 904).evaluate((b) => document.activeElement === b), true, 'the confirm takes focus');
    await p.page.keyboard.up('Enter');
    await p.page.keyboard.down('Enter');
    await waitFor(async () => (await state(p.page, 904)) === 'sent', { what: 'sent' });
    for (let i = 0; i < 8; i++) await p.page.keyboard.down('Enter');
    await p.page.keyboard.up('Enter');
    await waitFor(() => settled(fx), { what: 'every send answered' });
    assert.equal(sends(fx).length, 1);
    assert.deepEqual(fx.api.calls.map((c) => c.text), [NO_904]);
  } finally { await p.close(); await fx.close(); }
});

test('CK2: a risky item confirms twice; no double click counts as both, and Escape or Cancel disarms', async () => {
  for (const viewport of [DESKTOP, PHONE]) {
    const fx = await cockpitSite();
    const p = await openCockpit(browser, fx, viewport);
    try {
      assert.match(await row(p.page, 712).textContent(), /Risky · confirms twice/);
      await yes(p.page, 712).dblclick();
      await waitFor(() => row(p.page, 712).locator('[data-part=armed]').count(), { what: 'armed' });
      assert.equal(await row(p.page, 712).locator('[data-part=armed] button').first().textContent(), 'Yes, publish #712');
      assert.match(await row(p.page, 712).locator('[data-part=arm-note]').textContent(), /Press again to confirm\. This is a publish/);
      assert.equal(await sendButton(p.page, 712).count(), 0, 'one double click arms only');
      await p.page.keyboard.press('Escape');
      await waitFor(async () => (await yes(p.page, 712).count()) === 1, { what: 'Escape disarms' });
      await waitFor(() => yes(p.page, 712).evaluate((b) => document.activeElement === b), { what: 'focus back on Yes after Escape, never on the page' });
      await yes(p.page, 712).click();
      await row(p.page, 712).getByRole('button', { name: 'Cancel', exact: true }).click();
      assert.equal(await yes(p.page, 712).count(), 1, 'Cancel disarms');
      await waitFor(() => yes(p.page, 712).evaluate((b) => document.activeElement === b), { what: 'focus back on Yes after Cancel' });
      await yes(p.page, 712).click();
      await row(p.page, 712).locator('[data-part=armed] button').first().dblclick();
      await ready(p.page, 712);
      assert.equal(await sendButton(p.page, 712).textContent(), 'Send Yes: confirmed twice');
      assert.equal(sends(fx).length, 0, 'two confirmations, then the send: nothing before it');
      await sendButton(p.page, 712).dblclick();
      await waitFor(async () => (await state(p.page, 712)) === 'sent', { what: 'sent' });
      await waitFor(() => settled(fx), { what: 'every send answered' });
      assert.equal(fx.api.calls.length, 1);
      assert.deepEqual([fx.api.calls[0].id, fx.api.calls[0].text], [LANTERN, YES_712], 'to its own project’s orchestrator, never another’s');
    } finally { await p.close(); await fx.close(); }
  }
});

test('CK2: a lost answer is uncertain; after a reload, Try again replays the same op id: one provider call, and no second answer', async () => {
  const fx = await cockpitSite();
  fx.api.setSend((id, b) => ({ after: DROP, report: report(id, b.op_id, b.mode, b.text, result(DELIVERIES.sent)) }));
  const p = await openCockpit(browser, fx, PHONE);
  try {
    await yes(p.page, 904).click();
    await ready(p.page, 904);
    await sendButton(p.page, 904).click();
    await waitFor(async () => (await state(p.page, 904)) === 'unknown', { what: 'uncertain' });
    assert.match(await row(p.page, 904).locator('[data-part=outcome]').textContent(), /^Uncertain: it may or may not have been sent.*Nothing is sent again on its own\.$/);
    await p.page.clock.runFor(120_000);
    assert.equal(sends(fx).length, 1, 'no retry on its own');
    await p.page.reload();
    await showCockpit(p.page);
    await waitFor(async () => (await state(p.page, 904)) === 'unknown', { what: 'still uncertain after the reload' });
    assert.equal(await yes(p.page, 904).count(), 0, 'an unresolved answer is never offered again');
    await row(p.page, 904).locator('[data-part=send]', { hasText: 'Try again' }).click();
    await waitFor(async () => (await state(p.page, 904)) === 'sent', { what: 'the replay settles it' });
    await waitFor(() => settled(fx), { what: 'every send answered' });
    assert.equal(sends(fx).length, 2);
    assert.equal(sends(fx)[1].op_id, sends(fx)[0].op_id, 'the same op id');
    assert.equal(sends(fx)[1].text, YES_904);
    assert.equal(fx.api.calls.length, 1, 'one provider call');
    await p.page.reload();
    await showCockpit(p.page);
    assert.equal(await state(p.page, 904), 'sent');
    assert.equal(await row(p.page, 904).locator('[data-part=outcome]').textContent(), 'Answered: Yes · sent');
    assert.equal(await yes(p.page, 904).count(), 0, 'a reload never offers a sent answer again');
    assert.equal(sends(fx).length, 2);
  } finally { await p.close(); await fx.close(); }
});

test('CK2: an item or target that changes while armed disarms it: “This item changed. Nothing sent.”', async () => {
  for (const change of [
    (doc) => { doc.needs_you.items[0].wording = { known: 'Approve a different plan for #904?' }; },
    (doc) => { doc.projects.items[0].orchestrator.target = { known: 'thr_syn_0009' }; },
    (doc) => { doc.needs_you.items.splice(0, 1); },
  ]) {
    const fx = await cockpitSite();
    const p = await openCockpit(browser, fx, DESKTOP);
    try {
      await yes(p.page, 904).click();
      await ready(p.page, 904);
      fx.doc = structuredClone(fx.doc);
      change(fx.doc);
      await refresh(p.page);
      if ((await row(p.page, 904).count()) === 1) {
        assert.equal(await row(p.page, 904).locator('[data-part=changed]').textContent(), 'This item changed. Nothing sent.');
        assert.equal(await sendButton(p.page, 904).count(), 0, 'no confirm survives the change');
      }
      assert.equal(sends(fx).length, 0);
    } finally { await p.close(); await fx.close(); }
  }
});

test('CK2: unknown wording, an unassigned item, no target and a stale list never offer Yes, and say why', async () => {
  const fx = await cockpitSite();
  fx.doc = structuredClone(fx.doc);
  fx.doc.projects.items[1].orchestrator.target = { known: null };
  const p = await openCockpit(browser, fx, PHONE);
  try {
    assert.deepEqual(await p.page.locator('[data-part=ck-needs-you] li[data-ticket]').evaluateAll((rs) => rs.map((r) => [r.dataset.position, r.dataset.ticket])), [['1', '904'], ['2', '712'], ['3', '907'], ['4', '31']], 'numbered in the server’s order');
    assert.equal(await yes(p.page, 907).count(), 0);
    assert.equal(await row(p.page, 907).locator('[data-part=wording]').textContent(), 'Proposal not readable here yet');
    assert.equal(await row(p.page, 907).locator('[data-part=why]').textContent(), 'Yes and y need the exact proposal, which isn’t readable here yet: answer #907 on GitHub');
    assert.equal(await row(p.page, 907).locator('[data-part=why] .id').textContent(), '#907', 'the issue number, in mono');
    assert.equal(await row(p.page, 907).locator('[data-part=why] a, [data-part=why] button').count(), 0, 'no control without a destination');
    assert.equal(await yes(p.page, 31).count(), 0);
    assert.match(await row(p.page, 31).locator('[data-part=why]').textContent(), /^project unknown \(Synthetic repository matches 2 projects\); not assigned/);
    assert.equal(await yes(p.page, 712).count(), 0);
    assert.equal(await row(p.page, 712).locator('[data-part=why]').textContent(), 'answer unavailable: orchestrator not configured or not found');
    assert.equal(await yes(p.page, 904).count(), 1);
    fx.doc = aged(fx.doc, 80_000);
    await refresh(p.page);
    assert.equal(await yes(p.page, 904).count(), 0, 'a stale list is no authority to answer');
    assert.equal(await row(p.page, 904).locator('[data-part=why]').textContent(), 'answer unavailable: this list is not fresh; refresh it');
    assert.equal(sends(fx).length, 0);
    assert.equal(p.requests.filter((r) => r.method !== 'GET').length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('CK2: a fresh list ages on this clock: past 70 s the open confirm loses its authority', async () => {
  const fx = await cockpitSite();
  fx.doc = aged(fx.doc, 30_000);
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await yes(p.page, 904).click();
    await ready(p.page, 904);
    // No new read answers: the page's clock alone moves the source past 70 s.
    fx.reply = json(503, { error: { kind: 'busy', message: 'synthetic: busy' } });
    await p.page.clock.runFor(41_000);
    await waitFor(async () => (await sendButton(p.page, 904).count()) === 0, { what: 'the confirm withdrawn' });
    assert.equal(await row(p.page, 904).locator('[data-part=changed]').textContent(), 'This item changed. Nothing sent.');
    assert.equal(sends(fx).length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('CK2: an uncertain answer stays shown when the list turns stale, with no Try again until it is fresh', async () => {
  const fx = await cockpitSite();
  fx.api.setSend((id, b) => ({ after: DROP, report: report(id, b.op_id, b.mode, b.text, result(DELIVERIES.sent)) }));
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await yes(p.page, 904).click();
    await ready(p.page, 904);
    await sendButton(p.page, 904).click();
    await waitFor(async () => (await state(p.page, 904)) === 'unknown', { what: 'uncertain' });
    const fresh = fx.doc;
    fx.doc = aged(fresh, 80_000);
    await refresh(p.page);
    assert.equal(await state(p.page, 904), 'unknown', 'the attempt is still shown');
    assert.equal(await row(p.page, 904).locator('[data-part=why]').textContent(), 'answer unavailable: this list is not fresh; refresh it');
    assert.equal(await sendButton(p.page, 904).count(), 0, 'no Try again on a stale list');
    fx.doc = fresh;
    await refresh(p.page);
    assert.equal(await row(p.page, 904).locator('[data-part=send]', { hasText: 'Try again' }).count(), 1);
    assert.equal(sends(fx).length, 1);
  } finally { await p.close(); await fx.close(); }
});
