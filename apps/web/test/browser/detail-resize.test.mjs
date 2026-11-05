import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { launchBrowser, openPage, readDetail, readView, waitFor } from '../support/browser.mjs';
import { json } from '../support/fake-api.mjs';
import { fakeSite } from '../support/harness.mjs';
import { inventory, session, sessionView } from '../support/synthetic.ts';

let browser;
before(async () => { browser = await launchBrowser(); });
after(async () => { await browser?.close(); });

for (const long of [false, true]) for (const [from, to] of [[1440, 390], [1000, 899], [390, 1440], [899, 1000]]) {
  test(`detail retains control, selection and draft across ${from}→${to}${long ? ' with long output' : ''}`, async () => {
    const fx = await fakeSite();
    fx.api.setList(() => json(200, inventory([session(1)])));
    fx.api.setDetail(() => json(200, sessionView(session(1), long ? { finalOutput: { known: { kind: 'reported', text: 'Synthetic output line.\n'.repeat(120), truncated: false } } } : {})));
    const p = await openPage(browser, fx.site.origin, { viewport: { width: from, height: long ? 600 : 844 } });
    const row = p.page.locator('main [data-session-id="thr_web_0001"]');
    const close = p.page.locator('[data-part=detail] [aria-label="Sessions — close panel"]');
    const field = p.page.locator('[data-part=composer] textarea');
    const focused = (control) => control.evaluate((el) => el === document.activeElement);
    async function resize(width) {
      await p.page.setViewportSize({ width, height: long ? 600 : width === 1440 ? 900 : 844 });
      await waitFor(async () => (await readDetail(p.page))?.modal === (width < 900));
      await p.page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
      if (long) {
        const bounds = await p.page.evaluate(() => {
          const control = document.activeElement.getBoundingClientRect(), dialog = document.querySelector('[data-part=detail]').getBoundingClientRect();
          return { top: control.top, bottom: control.bottom, dialogTop: dialog.top, dialogBottom: dialog.bottom };
        });
        assert.ok(bounds.top >= bounds.dialogTop && bounds.bottom <= bounds.dialogBottom, `focused control stays visible: ${JSON.stringify(bounds)}`);
      }
    }
    async function open() {
      await row.focus();
      await p.page.keyboard.press('Enter');
      await waitFor(async () => (await readDetail(p.page))?.title === 'Synthetic web session 1');
      assert.equal(await focused(close), true, 'initial open focuses Close');
    }
    async function closed() {
      await waitFor(async () => (await readDetail(p.page)) === null);
      await waitFor(async () => (await row.getAttribute('aria-current')) === null);
      await waitFor(() => focused(row), { what: 'focus returns to the selected row' });
    }
    try {
      await waitFor(async () => (await readView(p.page)).groups.length === 1);
      await open();
      await field.focus();
      await p.page.keyboard.type('synthetic draft');
      await field.evaluate((el) => el.setSelectionRange(2, 9, 'backward'));
      const original = await field.elementHandle();
      await resize(to);
      assert.equal(await focused(original), true, 'the same message field retains focus');
      assert.equal(await field.inputValue(), 'synthetic draft');
      assert.deepEqual(await field.evaluate((el) => [el.selectionStart, el.selectionEnd, el.selectionDirection]), [2, 9, 'backward']);
      await p.page.keyboard.type('X');
      assert.equal(await field.inputValue(), 'syX draft', 'typing continues at the retained selection');
      const add = p.page.getByRole('button', { name: 'Add files', exact: true });
      await add.focus();
      await resize(from);
      assert.equal(await focused(add), true, 'another active control survives the reverse crossing');
      await resize(to);
      assert.equal(await focused(add), true);
      await close.focus();
      if (to < 900) {
        await p.page.keyboard.press('Tab');
        assert.equal(await focused(field), true, 'Tab advances within the modal sheet');
        await p.page.keyboard.press('Shift+Tab');
        assert.equal(await focused(close), true, 'Shift+Tab stays in the modal sheet');
        await row.focus();
        assert.equal(await focused(row), false, 'the background remains inert');
      } else {
        await row.focus();
        assert.equal(await focused(row), true, 'the desktop panel remains nonmodal');
      }
      await field.focus();
      await p.page.keyboard.press('Escape');
      await closed();
      await open();
      assert.equal(await field.inputValue(), 'syX draft', 'closing and reopening keeps the draft');
      await close.click();
      await closed();
      assert.equal(p.requests.filter((r) => r.method !== 'GET').length, 0, 'resizing never sends or creates');
      assert.deepEqual(p.errors, []);
    } finally {
      await p.close();
      await fx.close();
    }
  });
}
