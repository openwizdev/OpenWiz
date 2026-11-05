// CK3 (#537, spec #530): the command bar's reading words on the page. `cd`
// narrows Needs you and the grid (the project select agrees), `cd ..` goes up,
// `ls` and `blockers` list the level, numbers open items, and the scope
// survives a refresh until its project leaves the read. History is the
// page's memory only. Synthetic literals only (test/fixtures/cockpit/).

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, PHONE, pageIdle, waitFor } from '../support/browser.mjs';
import { cockpitSite, openCockpit, refresh, row, sends } from '../fixtures/cockpit/cockpit.mjs';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const bar = (page) => page.locator('[data-part=command-input]');
const lines = (page) => page.locator('[data-part=command-output] > li');
async function command(page, text) {
  await bar(page).fill(text);
  await bar(page).press('Enter');
  await waitFor(() => pageIdle(page), { what: `${text} consumed` });
}
const said = async (page) => (await lines(page).last().locator('[data-part=said]').textContent()) ?? '';
const items = (page) => lines(page).last().locator('.ck-bar-items > li').allTextContents();
const tickets = (page) => page.locator('[data-part=ck-needs-you] li[data-ticket]').evaluateAll((els) => els.map((e) => Number(e.getAttribute('data-ticket'))));
const groups = (page) => page.locator('[data-part=agents] [data-group]').evaluateAll((els) => els.map((e) => e.getAttribute('data-group')));
const crumbs = (page) => page.locator('[data-part=scope] li').allTextContents();
const projectSelect = (page) => page.locator('[data-part=filters] select').first();

test('CK3 cd: narrows Needs you and the grid by project, fleet and ticket; the breadcrumb and the select agree; cd .. and × go up (both widths)', async () => {
  for (const viewport of [DESKTOP, PHONE]) {
    const fx = await cockpitSite();
    const p = await openCockpit(browser, fx, viewport);
    try {
      assert.deepEqual(await tickets(p.page), [904, 712, 907, 31]);
      assert.equal(await p.page.locator('[data-part=scope]').count(), 0, 'no breadcrumb at the top');
      await command(p.page, 'cd atlas');
      assert.equal(await said(p.page), 'Now in Atlas · 3 need you · 4 agents');
      assert.deepEqual(await tickets(p.page), [904, 907, 31], 'the unassigned item stays: it can’t be excluded as though known');
      assert.deepEqual(await groups(p.page), ['prj_syn_atl1:901', 'unplaced']);
      assert.deepEqual(await crumbs(p.page), ['Cockpit', 'Atlas']);
      assert.equal(await projectSelect(p.page).inputValue(), 'prj_syn_atl1');
      await command(p.page, 'cd #901');
      assert.deepEqual(await tickets(p.page), [904, 907]);
      assert.deepEqual(await crumbs(p.page), ['Cockpit', 'Atlas', '#901']);
      await command(p.page, 'cd 904');
      assert.equal(await said(p.page), 'Now in Atlas / #901 / #904 · 1 needs you · 2 agents');
      assert.deepEqual(await tickets(p.page), [904]);
      assert.equal(await p.page.locator('[data-part=agents] li[data-thread]').count(), 2);
      await command(p.page, 'cd ..');
      assert.deepEqual(await crumbs(p.page), ['Cockpit', 'Atlas', '#901']);
      await command(p.page, 'cd nowhere');
      assert.equal(await said(p.page), 'No project, fleet or ticket called nowhere');
      assert.deepEqual(await crumbs(p.page), ['Cockpit', 'Atlas', '#901'], 'an unknown name changes nothing');
      await p.page.getByRole('button', { name: 'Clear the scope' }).click();
      assert.equal(await p.page.locator('[data-part=scope]').count(), 0);
      assert.equal(await projectSelect(p.page).inputValue(), '');
      assert.deepEqual(await tickets(p.page), [904, 712, 907, 31]);
      await command(p.page, 'cd ..');
      assert.equal(await said(p.page), 'Already at the top');
      assert.deepEqual(p.errors, []);
    } finally { await p.close(); await fx.close(); }
  }
});

test('CK3 ls, blockers and numbers: list the level and open items, in the page’s own numbering', async () => {
  const fx = await cockpitSite();
  fx.doc = structuredClone(fx.doc);
  fx.doc.agents.items[1].state = { known: 'held' };
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await command(p.page, 'ls');
    assert.equal(await said(p.page), '3 projects · this read is partial: more may exist');
    assert.deepEqual(await items(p.page), ['Atlas · 3 agents · 2 need you', 'Lantern · 2 agents · 1 needs you', 'Orchard · 0 agents · 0 need you', 'Not placed · 1 agent · 1 needs you']);
    await command(p.page, 'cd #901');
    await command(p.page, 'blockers');
    assert.equal(await said(p.page), '3 blocking Atlas / #901, among running agents and Needs you · this read is partial: more may block it');
    assert.deepEqual(await items(p.page), ['#905 held · Atlas / #901', '1: #904 needs_info · needs you', '2: #907 held · needs you']);
    await command(p.page, '2');
    assert.equal(await said(p.page), 'Opened 2: #907 (held)');
    assert.equal(await row(p.page, 907).getAttribute('data-open'), 'true');
    assert.equal(await row(p.page, 907).getAttribute('data-position'), '2', 'the bar’s number is the row’s');
    await command(p.page, '7');
    assert.equal(await said(p.page), 'No item 7 (2 shown)');
    for (const bad of ['0', '3.5', 'LS']) {
      await command(p.page, bad);
      assert.equal(await lines(p.page).last().getAttribute('data-tone'), 'refused', bad);
    }
    assert.equal(await lines(p.page).count(), 4, 'at most the last four lines');
    assert.equal(await row(p.page, 907).getAttribute('data-open'), 'true', 'bad input changes nothing');
    assert.equal(sends(fx).length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('CK3 scope: it survives a refresh; when its project leaves the read, the bar goes back to the top and says so', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await command(p.page, 'cd lantern');
    await refresh(p.page);
    assert.deepEqual(await crumbs(p.page), ['Cockpit', 'Lantern'], 'kept across a refresh');
    assert.deepEqual(await tickets(p.page), [712, 31]);
    fx.doc = structuredClone(fx.doc);
    fx.doc.projects.items = fx.doc.projects.items.filter((x) => x.id !== 'prj_syn_lan2');
    fx.doc.needs_you.items = fx.doc.needs_you.items.filter((n) => n.project.known !== 'prj_syn_lan2');
    fx.doc.agents.items = fx.doc.agents.items.filter((a) => a.project.known !== 'prj_syn_lan2');
    await refresh(p.page);
    await waitFor(async () => (await said(p.page)) === 'Back at the top: the project you were in isn’t in this read any more.', { what: 'the bar says so' });
    assert.equal(await p.page.locator('[data-part=scope]').count(), 0);
    assert.equal(await projectSelect(p.page).inputValue(), '');
    assert.deepEqual(await tickets(p.page), [904, 907, 31]);
  } finally { await p.close(); await fx.close(); }
});

test('CK3 history: the arrows recall earlier commands from this page’s memory; nothing is stored; a chip runs read-only words and only types y', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await command(p.page, 'ls');
    await command(p.page, 'next');
    await bar(p.page).press('ArrowUp');
    assert.equal(await bar(p.page).inputValue(), 'next');
    await bar(p.page).press('ArrowUp');
    assert.equal(await bar(p.page).inputValue(), 'ls');
    await bar(p.page).press('ArrowDown');
    assert.equal(await bar(p.page).inputValue(), 'next');
    await bar(p.page).press('ArrowDown');
    assert.equal(await bar(p.page).inputValue(), '');
    const stored = await p.page.evaluate(() => JSON.stringify([Object.entries(sessionStorage), Object.entries(localStorage)]));
    assert.ok(!stored.includes('"ls"') && !stored.includes('next'), `no command is stored: ${stored}`);
    await p.page.getByRole('button', { name: 'Run blockers' }).click();
    assert.match(await said(p.page), /^4 blocking all projects/);
    await p.page.getByRole('button', { name: 'Type y' }).click();
    assert.equal(await bar(p.page).inputValue(), 'y');
    assert.equal(await bar(p.page).evaluate((el) => document.activeElement === el), true);
    assert.equal(await p.page.locator('[data-part=ck-needs-you] [data-part=confirm]').count(), 0, 'the y chip only types');
    assert.equal(sends(fx).length, 0);
  } finally { await p.close(); await fx.close(); }
});
