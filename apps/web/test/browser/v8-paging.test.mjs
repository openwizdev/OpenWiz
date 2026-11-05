// V8: paging stays within the contract. Only `limit` and `offset` exist; the
// page sends `offset` alone (the core's default limit), never above the core's
// cap, and no cursor, revision or other parameter.

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, PHONE, launchBrowser, openPage, readDetail, readView, waitFor } from '../support/browser.mjs';
import { json } from '../support/fake-api.mjs';
import { fakeSite } from '../support/harness.mjs';
import { inventory, manyRows, session, sessionView } from '../support/synthetic.ts';

const all = manyRows(250);

let browser;
let fx;
before(async () => {
  browser = await launchBrowser();
  fx = await fakeSite();
  fx.api.setList((url) => {
    const offset = Number(url.searchParams.get('offset') ?? 0);
    return json(200, inventory(all.slice(offset, offset + 100), { offset, limit: 100, matched: all.length }));
  });
  fx.api.setDetail((id) => json(200, sessionView(session(Number(id.slice(-4))))));
});
after(async () => {
  await fx.close();
  await browser.close();
});

const ALLOWED_LIST_QUERIES = /^(|\?offset=(0|[1-9][0-9]*))$/;

for (const viewport of [PHONE, DESKTOP]) for (const count of [150, 250]) {
  test(`keyboard paging keeps named focus: ${viewport.width}px, ${count} sessions`, async () => {
    const site = await fakeSite();
    const rows = manyRows(count);
    site.api.setList((url) => {
      const offset = Number(url.searchParams.get('offset') ?? 0);
      return json(200, inventory(rows.slice(offset, offset + 100), { offset, limit: 100, matched: count }));
    });
    const p = await openPage(browser, site.site.origin, { viewport, clock: new Date('2030-01-15T09:00:00Z'), paused: true });
    try {
      await waitFor(async () => (await readView(p.page)).range === `1–100 of ${count}`);
      const heading = p.page.getByRole('heading', { name: 'Sessions', exact: true });
      const focused = () => heading.evaluate((el) => el === document.activeElement);
      const steps = count === 150 ? [['next', 100], ['previous', 0]] : [['next', 100], ['next', 200], ['previous', 100], ['previous', 0]];
      for (const [direction, offset] of steps) {
        site.api.hold('list');
        const control = p.page.locator(`[data-part=${direction}]`);
        await control.focus();
        assert.equal(await control.evaluate((el) => el === document.activeElement), true);
        await p.page.keyboard.press('Enter');
        await waitFor(() => site.api.held('list') === 1, { what: 'held page request' });
        assert.equal(await focused(), true, `${direction}: focus stays at Sessions while loading`);
        site.api.hold('list', false);
        site.api.release('list');
        await waitFor(async () => (await readView(p.page)).range === `${offset + 1}–${Math.min(offset + 100, count)} of ${count}`);
        assert.equal(await focused(), true, `${direction}: focus stays at Sessions after settlement`);
        assert.equal(await p.page.locator('[data-part=previous]').isDisabled(), offset === 0);
        assert.equal(await p.page.locator('[data-part=next]').isDisabled(), offset + 100 >= count);
        await p.page.keyboard.press('Tab');
        assert.equal(await p.page.locator('[data-new-thread]').first().evaluate((el) => el === document.activeElement), true, 'Tab enters the new page, after the top-level view controls');
      }
      site.api.hold('list');
      await p.page.locator('[data-part=next]').focus();
      await p.page.keyboard.press('Enter');
      await waitFor(() => site.api.held('list') === 1);
      await p.page.keyboard.press('Shift+Tab');
      // The command trigger now precedes Sessions in the shell’s tab order.
      const search = p.page.getByRole('button', { name: /Search or jump to…/ }).filter({ visible: true });
      assert.equal(await search.evaluate((el) => el === document.activeElement), true);
      site.api.hold('list', false);
      site.api.release('list');
      await waitFor(async () => (await readView(p.page)).range === `101–${Math.min(count, 200)} of ${count}`);
      assert.equal(await search.evaluate((el) => el === document.activeElement), true, 'late settlement does not steal focus after the user moves it');
      assert.equal(site.api.reads('list').length, steps.length + 2, 'one read per requested page');
      assert.deepEqual(p.errors, []);
    } finally {
      site.api.hold('list', false);
      site.api.release('list');
      await p.close();
      await site.close();
    }
  });
}

test('next, next, previous: offsets from the envelope\'s own counts, nothing else', async () => {
  const p = await openPage(browser, fx.site.origin);
  try {
    await waitFor(async () => (await readView(p.page)).range === '1–100 of 250', { what: 'page 1' });
    await p.page.click('[data-part=next]');
    await waitFor(async () => (await readView(p.page)).range === '101–200 of 250', { what: 'page 2' });
    await p.page.click('[data-part=next]');
    await waitFor(async () => (await readView(p.page)).range === '201–250 of 250', { what: 'page 3' });
    assert.equal(await p.page.$('[data-part=next]:not([disabled])'), null, 'no page past the end');
    await p.page.click('[data-part=previous]');
    await waitFor(async () => (await readView(p.page)).range === '101–200 of 250', { what: 'back to page 2' });
    await p.page.click('[data-session-id="thr_web_0150"]');
    await waitFor(async () => (await readDetail(p.page))?.title === 'Synthetic web session 150', { what: 'a detail' });

    const lists = fx.api.reads('list');
    const firstOfEach = [...new Set(lists.map((e) => e.search))];
    assert.deepEqual(firstOfEach, ['', '?offset=100', '?offset=200']);
    for (const e of fx.api.log) {
      assert.equal(e.method, 'GET');
      if (e.kind === 'list') assert.match(e.search, ALLOWED_LIST_QUERIES, `list query ${e.search}`);
      else if (e.kind === 'detail') {
        assert.equal(e.search, '', 'a detail read takes no query');
        assert.match(e.path, /^\/api\/v1\/sessions\/[A-Za-z0-9_-]{1,128}$/);
      } else if (e.kind === 'preview') {
        // #9 (contract revision 0.0.3): the open detail's composer reads the send preview; never a send.
        assert.match(e.search, /^\?mode=(queue|steer)$/);
        assert.match(e.path, /^\/api\/v1\/sessions\/[A-Za-z0-9_-]{1,128}\/preview$/);
      } else assert.fail(`a request outside the contract: ${e.path}`);
      assert.doesNotMatch(e.path + e.search, /cursor|revision|@r|limit|since|after/i);
      assert.equal(e.headers['x-requested-with'], 'XMLHttpRequest');
    }
  } finally {
    await p.close();
  }
});
