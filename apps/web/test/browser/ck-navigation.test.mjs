// The review of #1560 (R1-R3, at 4edce8f7): the cockpit keeps one read lane
// and one owner of its answers across navigation, and a new answer always
// previews the target it will send to. Synthetic literals only.

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, openPage, pageIdle, waitFor } from '../support/browser.mjs';
import { apiError, json } from '../support/fake-api.mjs';
import { preview } from '../support/synthetic.ts';
import { cockpitSite, openCockpit, refresh, row, sends, START } from '../fixtures/cockpit/cockpit.mjs';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const nav = (page, name) => page.getByRole('navigation', { name: 'Views', exact: true }).getByRole('button', { name, exact: true });
const yes = (page) => row(page, 904).getByRole('button', { name: /^Yes to item/ });
const sendButton = (page) => row(page, 904).locator('[data-part=send]');
const state = (page) => row(page, 904).locator('[data-part=outcome]').getAttribute('data-state');
async function ready(page) {
  await waitFor(async () => (await sendButton(page).count()) === 1 && (await sendButton(page).getAttribute('aria-disabled')) === null, { what: 'Send ready' });
  await waitFor(() => pageIdle(page), { what: 'the preview consumed' });
}

test('R1: leaving and reopening the cockpit during a held read starts no second read until the first is answered', async () => {
  const fx = await cockpitSite();
  fx.holding = true;
  const p = await openPage(browser, fx.site.origin, { clock: START, paused: true, stampReads: true, viewport: DESKTOP });
  try {
    await waitFor(() => pageIdle(p.page), { what: 'the first reads consumed' });
    await nav(p.page, 'Cockpit').click();
    await waitFor(() => fx.inFlight === 1, { what: 'the held cockpit read' });
    for (let i = 0; i < 3; i++) {
      await nav(p.page, 'Sessions').click();
      await nav(p.page, 'Cockpit').click();
    }
    await p.page.clock.runFor(5_000);
    assert.equal(fx.reads, 1, 'no second read while the first is out');
    assert.equal(fx.maxInFlight, 1);
    fx.holding = false;
    fx.releaseReads();
    await waitFor(async () => (await row(p.page, 904).count()) === 1, { what: 'the cockpit shown' });
    assert.equal(fx.maxInFlight, 1);
  } finally { await p.close(); await fx.close(); }
});

test('R2: an answer sent before leaving settles in the reopened cockpit; a refusal leaves it answerable', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    fx.api.hold('send');
    fx.api.setSend(() => apiError(403, 'forbidden_origin', 'synthetic: refused before the core'));
    await yes(p.page).click();
    await ready(p.page);
    await sendButton(p.page).click();
    await waitFor(() => fx.api.held('send') === 1, { what: 'the held send' });
    await nav(p.page, 'Sessions').click();
    await nav(p.page, 'Cockpit').click();
    await waitFor(async () => (await row(p.page, 904).count()) === 1, { what: 'the cockpit reopened' });
    fx.api.release('send');
    await waitFor(async () => (await state(p.page)) === 'not-sent', { what: 'the refusal shown in the reopened cockpit' });
    await refresh(p.page);
    assert.equal(await yes(p.page).count(), 1, 'answerable again');
    await yes(p.page).click();
    await ready(p.page);
    assert.equal(await sendButton(p.page).getAttribute('aria-disabled'), null, 'a fresh answer can send');
  } finally { await p.close(); await fx.close(); }
});

test('R3: after an answer to one target, a new answer previews the new target it will send to; a refused preview there sends nothing', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await yes(p.page).click();
    await ready(p.page);
    await sendButton(p.page).click();
    await waitFor(async () => (await state(p.page)) === 'sent', { what: 'sent to A' });
    fx.doc = structuredClone(fx.doc);
    fx.doc.projects.items[0].orchestrator.target = { known: 'thr_syn_0009' };
    fx.api.setPreview((id, mode) => json(200, preview(id, id === 'thr_syn_0009' ? 'refused' : 'idle', mode)));
    await refresh(p.page);
    const before = fx.api.log.filter((e) => e.kind === 'preview').length;
    await yes(p.page).click();
    await waitFor(() => fx.api.log.filter((e) => e.kind === 'preview').length > before && pageIdle(p.page), { what: 'the new preview' });
    assert.deepEqual(fx.api.log.filter((e) => e.kind === 'preview').slice(before).map((e) => e.path), ['/api/v1/sessions/thr_syn_0009/preview'], 'the preview is of the new target');
    assert.equal(await sendButton(p.page).getAttribute('aria-disabled'), 'true', 'B refuses, so Send is off');
    await sendButton(p.page).click({ force: true });
    assert.equal(sends(fx).length, 1);
    assert.deepEqual(fx.api.calls.map((c) => c.id), ['thr_syn_0001']);
  } finally { await p.close(); await fx.close(); }
});
