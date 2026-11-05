// W12: reuse. The composer renders inside #6's panel (desktop) and sheet
// (phone), after the final output in the same thread (or "no final output yet"). One
// dialog, no second panel, sheet or page: `npm run check` proves the source
// side (W12 there); this proves the rendered side.

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, PHONE, readDetail } from '../support/browser.mjs';
import { composerSite, openThread } from '../support/composer.mjs';

let browser;
before(async () => {
  browser = await launchBrowser();
});
after(() => browser.close());

const placement = (page) =>
  page.evaluate(() => {
    const c = document.querySelector('[data-part=composer]');
    return {
      dialogs: document.querySelectorAll('dialog').length,
      composers: document.querySelectorAll('[data-part=composer]').length,
      inDetail: !!c?.closest('dialog[data-part=detail]'),
      finalInScroll: !!c?.querySelector('.thread-scroll [data-field="final-output"]'),
      dockAfterScroll: c?.querySelector('.composer-dock')?.previousElementSibling?.className === 'thread-scroll',
      textareas: document.querySelectorAll('textarea').length,
    };
  });

for (const [name, viewport, modal] of [
  ['phone: in the bottom sheet', PHONE, true],
  ['desktop: in the side panel', DESKTOP, false],
]) {
  test(`${name}, after the final output in the same thread`, async () => {
    for (const finalOutput of [null, { known: { kind: 'no_final_output_yet' } }, { known: { kind: 'reported', text: 'Synthetic long reply.\n'.repeat(120), truncated: false } }]) {
      const { fx } = await composerSite({ finalOutput });
      const p = await openThread(browser, fx, 1, { viewport });
      try {
        assert.equal((await readDetail(p.page)).modal, modal);
        const where = await placement(p.page);
        assert.deepEqual(where, { dialogs: 1, composers: 1, inDetail: true, finalInScroll: true, dockAfterScroll: true, textareas: 1 });
        assert.equal(await p.page.locator('#composer-said').evaluate((el) => el.parentElement.className), 'thread-scroll', 'outcomes scroll above the message box');
        const field = p.page.locator('[data-part=draft]');
        const oneRow = (await field.boundingBox()).height;
        await field.fill('Synthetic line one\nSynthetic line two\nSynthetic line three');
        assert.ok((await field.boundingBox()).height > oneRow, 'the one-row message field grows with its text');
        await field.fill('');
        const dock = await p.page.locator('.composer-dock').boundingBox();
        assert.ok(dock.y + dock.height <= viewport.height, 'the message box stays within the viewport');
        const scroll = p.page.locator('.thread-scroll');
        await scroll.evaluate((el) => { el.scrollTop = el.scrollHeight; });
        assert.deepEqual(await p.page.locator('.composer-dock').boundingBox(), dock, 'reading never moves the dock');
        if (finalOutput?.known.kind === 'no_final_output_yet') assert.equal((await readDetail(p.page)).finalOutput, 'no final output yet');
      } finally {
        await p.close();
        await fx.close();
      }
    }
  });
}
