// #2039 PA4/PA6 client leg of the integrated journey, in PC CI: the static
// export over the actual installed service (the test-only fixture-service's
// real dispatch). Its alert comes from the service's own recording delivery,
// not from a fake API. Fake gh/room-cli readers; synthetic data only. This is
// no proof of live delivery, phone display or real authentication.
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, openPage, pageIdle, PHONE, waitFor } from '../support/browser.mjs';
import { startSite } from '../support/serve.mjs';
import { journeyService } from '../fixtures/notifications-journey/service.mjs';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const landing = (page) => page.locator('[data-part=notification-target]');
const card = (page) => page.locator('[data-comment="1001"]');
const writes = (site) => site.log.filter((e) => e.method !== 'GET' && e.method !== 'HEAD');

async function open(site, token, viewport) {
  const p = await openPage(browser, site.origin, { path: `/#notification=${token}`, viewport, stampReads: true });
  await waitFor(async () => (await landing(p.page).getAttribute('data-state')) === 'Current', { what: 'the exact current item', timeout: 30_000 });
  await waitFor(() => pageIdle(p.page), { what: 'navigation reads consumed', timeout: 30_000 });
  return p;
}

test('PA4 a recorded alert opens its exact current card; opening and reloading send nothing; one explicit answer sends once', async () => {
  const service = await journeyService();
  const site = await startSite({ port: service.port, allowedHost: service.allowedHost });
  try {
    for (const viewport of [PHONE, DESKTOP]) {
      const p = await open(site, service.token, viewport);
      try {
        assert.deepEqual(await p.page.locator('[data-comment]').evaluateAll((items) => items.map((i) => i.dataset.comment)), ['1001']);
        await p.page.reload();
        await waitFor(async () => (await landing(p.page).getAttribute('data-state')) === 'Current', { what: 'current after reload', timeout: 30_000 });
        assert.equal(await card(p.page).count(), 1);
        assert.deepEqual(p.errors, []);
      } finally { await p.close(); }
    }
    assert.deepEqual(writes(site), [], 'receipt, navigation and reload are reads only');
    assert.equal(service.tells(), 0);

    const p = await open(site, service.token, PHONE);
    try {
      const c = card(p.page);
      await c.getByRole('button', { name: /^Yes/ }).click();
      const send = c.locator('[data-part=send]');
      await waitFor(async () => (await send.count()) === 1 && (await send.getAttribute('aria-disabled')) === null, { what: 'Send ready', timeout: 30_000 });
      await send.dblclick();
      await waitFor(async () => (await c.locator('[data-part=outcome]').getAttribute('data-state')) === 'sent', { what: 'sent', timeout: 30_000 });
      assert.match(await c.locator('[data-part=sent]').textContent(), /^openwiz decision answer v1\n/);
      await p.page.reload();
      await waitFor(() => pageIdle(p.page), { what: 'reload consumed', timeout: 30_000 });
      assert.equal(service.tells(), 1, 'a double click and a reload never send twice');
      assert.equal(writes(site).filter((e) => e.path === '/api/v1/sessions/thr_syn_0001/messages').length, 1);
      assert.deepEqual(writes(site).filter((e) => !e.path.endsWith('/messages')), [], 'no other write');
      assert.equal(service.submissions().length, 1, 'the answer creates no alert');
    } finally { await p.close(); }
  } finally {
    await site.close();
    await service.stop();
  }
});
