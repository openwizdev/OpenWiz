// CK5 (#536, spec #530): empty means empty. "Nothing needs you" appears only
// when projects and Needs you are both complete and fresh, and still fresh on
// this page's clock; partial, stale, unknown-time and failed reads never say
// it, and a project filter narrows the claim without making the data complete.

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, PHONE, waitFor } from '../support/browser.mjs';
import { json } from '../support/fake-api.mjs';
import { aged, cockpitSite, load, openCockpit, partialEmpty, refresh } from '../fixtures/cockpit/cockpit.mjs';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const empty = (page) => page.locator('[data-part=ck-needs-you] [data-part=needs-empty]');
const nothing = async (page) => (await page.getByText('Nothing needs you', { exact: false }).count()) > 0;

async function emptyText(doc, viewport = PHONE) {
  const fx = await cockpitSite(doc);
  const p = await openCockpit(browser, fx, viewport);
  try {
    return { text: await empty(p.page).textContent(), nothing: await nothing(p.page) };
  } finally { await p.close(); await fx.close(); }
}

test('CK5: only a complete, fresh, empty read says “Nothing needs you”', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    assert.deepEqual(await emptyText(load('empty'), viewport), { text: 'Nothing needs you', nothing: true });
  }
});

test('CK5: partial, stale and unknown-time empty reads never say it', async () => {
  const partial = await emptyText(partialEmpty());
  assert.equal(partial.nothing, false);
  assert.equal(partial.text, 'No items read: this read is partial, so something may still need you');
  const stale = await emptyText(aged(load('empty'), 120_000));
  assert.equal(stale.nothing, false);
  assert.equal(stale.text, 'None as of 07:58:00: this read is stale');
  const projectsPartial = load('empty');
  projectsPartial.projects.coverage = { state: 'partial', gaps: [{ project: null, kind: 'truncated', detail: 'Synthetic project discovery was cut short' }] };
  assert.equal((await emptyText(projectsPartial)).nothing, false, 'an incomplete project universe is not an empty one');
  const unknownTime = load('empty');
  unknownTime.needs_you.freshness = { state: 'unknown', snapshot_at: { unknown: 'Synthetic source time unavailable' } };
  const u = await emptyText(unknownTime);
  assert.equal(u.nothing, false);
  assert.equal(u.text, 'No items read: when this was read is unknown');
});

test('CK5: a fresh empty read stops saying it once it ages past 70 s on this clock, and a failed read never says it', async () => {
  const fx = await cockpitSite(aged(load('empty'), 50_000));
  const p = await openCockpit(browser, fx, PHONE);
  try {
    assert.equal(await nothing(p.page), true);
    fx.reply = json(503, { error: { kind: 'busy', message: 'synthetic: busy' } });
    await p.page.clock.runFor(21_000);
    await waitFor(async () => !(await nothing(p.page)), { what: 'the claim withdrawn' });
    assert.equal(await empty(p.page).textContent(), 'None as of 07:59:10: this read is stale');
  } finally { await p.close(); await fx.close(); }

  const down = await cockpitSite();
  down.reply = json(503, { error: { kind: 'busy', message: 'synthetic: busy' } });
  const q = await openCockpit(browser, down, PHONE);
  try {
    assert.equal(await q.page.locator('[data-part=cockpit] [data-notice]').count(), 1);
    assert.equal(await nothing(q.page), false);
    assert.equal(await empty(q.page).count(), 0);
  } finally { await q.close(); await down.close(); }
});

test('CK5: a project filter narrows the claim, never completes it; unassigned items stay in every filter', async () => {
  const fx = await cockpitSite(load('empty'));
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    const project = p.page.locator('[data-part=filters] select').first();
    await project.selectOption('prj_syn_atl1');
    assert.equal(await empty(p.page).textContent(), 'Nothing needs you in Atlas');
    fx.doc = partialEmpty();
    await refresh(p.page);
    assert.equal(await empty(p.page).textContent(), 'No items read in Atlas: this read is partial, so something may still need you');
    assert.equal(await nothing(p.page), false);
    fx.doc = load('target');
    await refresh(p.page);
    await project.selectOption('prj_syn_lan2');
    assert.deepEqual(await p.page.locator('[data-part=ck-needs-you] li[data-ticket]').evaluateAll((rs) => rs.map((r) => [r.dataset.position, r.dataset.ticket])), [['1', '712'], ['2', '31']], 'numbers are positions in the narrowed list; the unassigned item stays');
    assert.equal(await nothing(p.page), false);
  } finally { await p.close(); await fx.close(); }
});
