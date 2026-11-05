// K1: snapshot-only navigation, keyboard access and focus in both app layouts.
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { DESKTOP, PHONE, launchBrowser, openPage, readDetail, readView, waitFor } from '../support/browser.mjs';
import { json } from '../support/fake-api.mjs';
import { axe, fakeSite } from '../support/harness.mjs';
import { inventory, session, sessionView } from '../support/synthetic.ts';

let browser;
before(async () => { browser = await launchBrowser(); });
after(async () => { await browser?.close(); });

for (const source of ['thread', 'launcher']) {
  test(`phone Sessions command closes the ${source} sheet at 390px`, async () => {
    const fx = await fakeSite();
    const row = session(1, { title: { known: 'Synthetic navigation thread' }, group: { kind: 'project', id: 'prj_syn_atlas', name: { known: 'Atlas' } } });
    fx.api.setList(() => json(200, inventory([row])));
    fx.api.setDetail(() => json(200, sessionView(row)));
    const p = await openPage(browser, fx.site.origin, { viewport: PHONE });
    const page = p.page;
    const sheet = page.locator('[data-part=detail]');
    const sessionRow = page.locator('main [data-session-id="thr_web_0001"]');
    try {
      await sessionRow.waitFor({ state: 'visible' });
      if (source === 'thread') {
        await sessionRow.click();
        await waitFor(async () => (await readDetail(page))?.title === 'Synthetic navigation thread');
      } else {
        await page.getByRole('button', { name: 'New thread', exact: true }).click();
        await page.locator('[data-part=launcher]').waitFor({ state: 'visible' });
      }
      assert.equal(await sheet.evaluate((el) => el.matches(':modal')), true);
      await sheet.getByRole('button', { name: 'Search or jump to…', exact: true }).click();
      const search = page.getByRole('dialog', { name: 'Search or jump to…', exact: true });
      await page.getByRole('combobox', { name: 'Search navigation' }).fill('Go to Sessions');
      await search.getByRole('option', { name: 'Go to Sessions', exact: true }).click();
      await waitFor(async () => await search.count() === 0);
      assert.equal(await sheet.evaluate((el) => el.open), false, 'Sessions closes the sheet');
      await sessionRow.click({ timeout: 2000 });
      await waitFor(async () => (await readDetail(page))?.title === 'Synthetic navigation thread');
      assert.equal(fx.api.calls.length, 0);
      assert.equal(fx.api.creates.length, 0);
      assert.equal(p.requests.filter((r) => r.method !== 'GET').length, 0, 'navigation never writes');
      assert.deepEqual(p.errors, []);
      assert.deepEqual(await p.csp(), []);
    } finally { await p.close(); await fx.close(); }
  });
}

for (const viewport of [DESKTOP, PHONE]) {
  test(`command navigation opens, filters, selects and closes at ${viewport.width}px`, async () => {
    const fx = await fakeSite();
    const rows = [
      session(1, { title: { known: 'Synthetic attachment test' }, status: { known: 'active' }, group: { kind: 'project', id: 'prj_syn_atlas', name: { known: 'Atlas' } } }),
      session(2, { title: { known: 'Synthetic release notes' }, status: { known: 'error' }, group: { kind: 'project', id: 'prj_syn_lantern', name: { known: 'Lantern' } } }),
    ];
    fx.api.setList(() => json(200, inventory(rows)));
    fx.api.setDetail((id) => json(200, sessionView(rows.find((s) => s.id === id))));
    const p = await openPage(browser, fx.site.origin, { viewport });
    const page = p.page;
    const search = page.getByRole('dialog', { name: 'Search or jump to…', exact: true });
    const input = page.getByRole('combobox', { name: 'Search navigation' });
    const focused = (el) => el.evaluate((node) => document.activeElement === node);
    try {
      await waitFor(async () => (await readView(page)).groups.length > 0);
      const original = await readView(page);
      const trigger = page.getByRole('button', { name: /^Search or jump to…/ }).filter({ visible: true });
      const beforeRequests = fx.api.log.length;
      await trigger.click();
      await input.waitFor({ state: 'visible' });
      assert.equal(await focused(input), true);
      assert.equal(await search.getAttribute('aria-modal'), 'true');
      const views = await search.getByRole('option').allTextContents();
      // Decisions (#656) adds its own destination when it lands.
      assert.equal(views.length, views.includes('Go to Decisions↵') ? 11 : 10, 'Home, First hour (#2205), existing views (Plan and Cockpit too, #653), each listed project, and listed sessions only');
      for (const v of ['Go to Plan↵', 'Go to Cockpit↵']) assert.ok(views.includes(v), v);
      assert.equal(await search.getByRole('option').first().textContent(), 'Go to Home↵', 'Home is the first destination');
      assert.equal(await search.getByRole('option', { name: 'New thread in Atlas', exact: true }).count(), 1);
      assert.equal(await search.getByRole('option', { name: 'New thread in Lantern', exact: true }).count(), 1);
      assert.equal(await search.locator('[data-part=status]').count(), 2, 'sessions reuse StatusMark with word and shape');
      assert.deepEqual(await axe(page), []);
      await input.fill('no such destination');
      assert.equal(await search.getByRole('option').count(), 0);
      assert.equal(await input.getAttribute('aria-activedescendant'), null);
      await page.keyboard.press('Enter');
      assert.equal(await search.isVisible(), true);
      await input.fill('synthetic');
      assert.equal(await search.getByRole('option').count(), 2);
      const firstId = await input.getAttribute('aria-activedescendant');
      await page.keyboard.press('ArrowDown');
      assert.notEqual(await input.getAttribute('aria-activedescendant'), firstId);
      assert.match(await search.getByRole('option', { selected: true }).innerText(), /Synthetic release notes/);
      await page.keyboard.press('ArrowUp');
      assert.equal(await input.getAttribute('aria-activedescendant'), firstId);
      await page.keyboard.press('Tab');
      assert.equal(await focused(page.getByRole('button', { name: 'Close search' })), true);
      await page.keyboard.press('Tab');
      assert.equal(await focused(input), true, 'focus is trapped');
      await page.keyboard.press('Escape');
      assert.equal(await search.count(), 0);
      assert.equal(await focused(trigger), true, 'Escape returns focus');
      assert.equal(fx.api.log.length, beforeRequests, 'opening and filtering add no requests');
      assert.deepEqual(await readView(page), original, 'search never changes the inventory');

      for (const shortcut of ['Control+k', 'Meta+k', '/']) {
        await page.keyboard.press(shortcut);
        await input.waitFor({ state: 'visible' });
        await page.keyboard.press('Escape');
        assert.equal(await focused(trigger), true);
      }
      await page.keyboard.press('/');
      await input.fill('synthetic');
      await page.keyboard.press('ArrowDown');
      await page.keyboard.press('Enter');
      await waitFor(async () => (await readDetail(page))?.title === 'Synthetic release notes');
      assert.equal(await search.count(), 0);
      const field = page.locator('[data-part=composer] textarea');
      await field.fill('draft');
      await field.press('/');
      assert.equal(await search.count(), 0, 'slash keeps typing in editors');
      const draft = await field.inputValue();
      await field.press('Control+k');
      await input.waitFor({ state: 'visible' });
      assert.equal(await focused(input), true, 'search works over the phone modal too');
      await page.keyboard.press('Escape');
      assert.equal(await focused(field), true);
      assert.equal((await readDetail(page)).title, 'Synthetic release notes', 'Escape only closes search');
      assert.equal(await field.inputValue(), draft);
      await field.press('Control+k');
      await input.fill('New thread in Lantern');
      await page.keyboard.press('Enter');
      await page.locator('[data-part=launcher]').waitFor({ state: 'visible' });
      assert.equal(await search.count(), 0, 'New thread opens the existing launcher');
      assert.equal(await page.locator('[data-part=detail]').getAttribute('data-launch'), 'prj_syn_lantern');
      if (viewport === PHONE) {
        const sheetSearch = page.locator('[data-part=detail]').getByRole('button', { name: 'Search or jump to…', exact: true });
        await sheetSearch.click();
        assert.equal(await focused(input), true);
        assert.deepEqual(await axe(page), [], 'search over the native modal is accessible');
        await page.keyboard.press('Escape');
        assert.equal(await focused(sheetSearch), true);
      }
      await page.keyboard.press('Control+k');
      await input.fill('Go to Fleets');
      await page.keyboard.press('Enter');
      await page.locator('[data-part=fleet-screen]').waitFor({ state: 'visible' });
      await page.keyboard.press('Control+k');
      await input.fill('Go to Sessions');
      await page.keyboard.press('Enter');
      await page.locator('main [data-session-id="thr_web_0001"]').waitFor({ state: 'visible' });
      assert.deepEqual((await readView(page)).groups, original.groups, 'navigation preserves grouping and order');
      assert.equal(fx.api.calls.length, 0);
      assert.equal(fx.api.creates.length, 0);
      assert.equal(p.requests.filter((r) => r.method !== 'GET').length, 0, 'commands never send or create');
      assert.deepEqual(p.errors, []);
      assert.deepEqual(await p.csp(), []);
    } finally { await p.close(); await fx.close(); }
  });
}
