// CK3 (#537, spec #530): the command bar's `y` and `approve` act only on the
// item open on screen. `y` opens that item's Yes exactly as pressing it does
// (#536's answer), so the row's own Send still sends, once; a risky item
// arms first. With nothing open, after the item changed, or on an item whose
// proposal isn't readable, nothing is opened or sent, and the bar says why.
// The bar is not the ⌘K dialog: `/` and ⌘K still open that, and `:` focuses
// the bar. Synthetic literals only (test/fixtures/cockpit/).

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, PHONE, pageIdle, waitFor } from '../support/browser.mjs';
import { cockpitSite, openCockpit, refresh, row, sends } from '../fixtures/cockpit/cockpit.mjs';

const ATLAS = 'thr_syn_0001';
const YES_904 = 'Answer for ticket #904 (spec #901, needs_info): Yes\n\nProposal: Approve the plan for #904: offline sync queue?';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const bar = (page) => page.locator('[data-part=command-input]');
const lastLine = (page) => page.locator('[data-part=command-output] > li').last();
const sendButton = (page, ticket) => row(page, ticket).locator('[data-part=send]');
const state = (page, ticket) => row(page, ticket).locator('[data-part=outcome]').getAttribute('data-state');
const settled = (fx) => fx.api.log.filter((e) => e.kind === 'send').every((e) => e.endedAt !== null);

/** Types one command into the bar and runs it with Enter. */
async function command(page, text) {
  await bar(page).fill(text);
  await bar(page).press('Enter');
  await waitFor(() => pageIdle(page), { what: `${text} consumed` });
}
const said = async (page) => (await lastLine(page).locator('[data-part=said]').textContent()) ?? '';
const tone = (page) => lastLine(page).getAttribute('data-tone');
const steps = (page) => page.locator('[data-part=ck-needs-you] [data-part=confirm], [data-part=ck-needs-you] [data-part=armed]').count();

test('CK3 y: with nothing open nothing opens or sends, and the bar says why (both widths)', async () => {
  for (const viewport of [DESKTOP, PHONE]) {
    const fx = await cockpitSite();
    const p = await openCockpit(browser, fx, viewport);
    try {
      for (const word of ['y', 'approve']) {
        await command(p.page, word);
        assert.equal(await said(p.page), 'Nothing sent. Open an item first (next or a number).');
        assert.equal(await tone(p.page), 'refused');
      }
      assert.equal(await steps(p.page), 0, 'no row opened its answer');
      assert.equal(sends(fx).length, 0);
      assert.equal(fx.api.log.filter((e) => e.kind === 'preview').length, 0, 'not even a preview is read');
      assert.deepEqual(p.errors, []);
    } finally { await p.close(); await fx.close(); }
  }
});

test('CK3 y: next opens #904; the binding line spells out the send; y opens its Yes; its Send sends once, a held Enter adds none', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await command(p.page, 'next');
    assert.equal(await said(p.page), 'Opened 1: #904, oldest waiting (12m)');
    assert.equal(await row(p.page, 904).getAttribute('data-open'), 'true');
    assert.equal(await p.page.locator('[data-part=ck-needs-you] li[data-open]').count(), 1, 'one item open');
    await bar(p.page).fill('y');
    assert.equal(await p.page.locator('[data-part=binding]').textContent(), 'y will answer Yes to #904 “Approve the plan for #904: offline sync queue?” · Atlas · you confirm with Send, then it sends once to the orchestrator');
    // Enter held down on the bar: the first press opens Yes; its repeats land on Send, which ignores repeats.
    await p.page.keyboard.down('Enter');
    await waitFor(async () => (await sendButton(p.page, 904).count()) === 1, { what: 'the confirm step' });
    await waitFor(async () => (await sendButton(p.page, 904).getAttribute('aria-disabled')) === null, { what: 'Send ready' });
    await waitFor(() => pageIdle(p.page), { what: 'the preview consumed' });
    for (let i = 0; i < 8; i++) await p.page.keyboard.down('Enter');
    assert.equal(sends(fx).length, 0, 'y never sends; the held Enter is not the confirm');
    assert.equal(await sendButton(p.page, 904).evaluate((b) => document.activeElement === b), true, 'the row’s Send takes focus');
    assert.equal(await said(p.page), 'Yes opened on #904: press Send in its row to send it once.');
    assert.equal(await p.page.locator('[data-part=binding]').count(), 0, 'the input is cleared after running');
    await p.page.keyboard.up('Enter');
    await p.page.keyboard.down('Enter');
    await waitFor(async () => (await state(p.page, 904)) === 'sent', { what: 'sent' });
    for (let i = 0; i < 8; i++) await p.page.keyboard.down('Enter');
    await p.page.keyboard.up('Enter');
    await waitFor(() => settled(fx), { what: 'every send answered' });
    assert.equal(sends(fx).length, 1);
    assert.deepEqual([fx.api.calls[0].id, fx.api.calls[0].mode, fx.api.calls[0].text], [ATLAS, 'queue', YES_904]);
    // Answered: y again opens nothing.
    await command(p.page, 'y');
    assert.equal(await said(p.page), 'Nothing sent. #904 already has an answer (Yes · sent).');
    assert.equal(sends(fx).length, 1);
    // A new proposal on the same item is a new item: y may open its Yes, as the row offers it (review 1).
    fx.doc = structuredClone(fx.doc);
    fx.doc.needs_you.items[0].wording = { known: 'Approve the revised plan for #904?' };
    await refresh(p.page);
    await command(p.page, 'next');
    await command(p.page, 'y');
    assert.equal(await said(p.page), 'Yes opened on #904: press Send in its row to send it once.');
    await waitFor(async () => (await sendButton(p.page, 904).count()) === 1, { what: 'the new proposal’s confirm step' });
    assert.equal(sends(fx).length, 1, 'still one send until the owner confirms');
    assert.deepEqual(p.errors, []);
  } finally { await p.close(); await fx.close(); }
});

test('CK3 y: after the open item changed, nothing opens or sends, and the binding clears', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await command(p.page, 'next');
    const original = fx.doc;
    fx.doc = structuredClone(fx.doc);
    fx.doc.needs_you.items[0].wording = { known: 'Approve a different plan for #904?' };
    await refresh(p.page);
    assert.equal(await row(p.page, 904).getAttribute('data-open'), null, 'the change unbinds it at once');
    // Back to exactly what was opened: the binding stays lost (review 1, at 4b2d2792).
    fx.doc = original;
    await refresh(p.page);
    await bar(p.page).fill('y');
    assert.equal(await p.page.locator('[data-part=binding]').count(), 0, 'no binding line for a changed item');
    await bar(p.page).press('Enter');
    await waitFor(() => pageIdle(p.page), { what: 'y consumed' });
    assert.equal(await said(p.page), 'Nothing sent. #904 changed since you opened it.');
    assert.equal(await row(p.page, 904).getAttribute('data-open'), null, 'the binding cleared');
    assert.equal(await steps(p.page), 0);
    await command(p.page, 'y');
    assert.equal(await said(p.page), 'Nothing sent. Open an item first (next or a number).');
    assert.equal(sends(fx).length, 0);
    assert.equal(fx.api.log.filter((e) => e.kind === 'preview').length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('CK3 y: a risky item arms first in its row; y alone never confirms it', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await command(p.page, 'cd lantern');
    await command(p.page, 'next');
    assert.equal(await said(p.page), 'Opened 1: #712, oldest waiting (9m)');
    await command(p.page, 'y');
    assert.equal(await said(p.page), 'Yes opened on #712: it’s a publish, so its row asks you to confirm twice before it sends once.');
    await waitFor(async () => (await row(p.page, 712).locator('[data-part=armed]').count()) === 1, { what: 'armed: its first confirmation' });
    await command(p.page, 'y');
    assert.equal(await row(p.page, 712).locator('[data-part=armed]').count(), 1, 'a second y re-opens the first step, never the second');
    assert.equal(await row(p.page, 712).locator('[data-part=send]').count(), 0);
    assert.equal(sends(fx).length, 0);
  } finally { await p.close(); await fx.close(); }
});

test('CK3 y on the phone: #907’s proposal isn’t readable, so y is refused with the reason; the bar sits above the tabs', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, PHONE);
  try {
    await command(p.page, '3');
    assert.equal(await said(p.page), 'Opened 3: #907 (held)');
    await command(p.page, 'y');
    assert.equal(await said(p.page), 'Nothing sent. #907’s proposal isn’t readable here, so y can’t approve it. Answer it on GitHub.');
    assert.equal(await tone(p.page), 'refused');
    assert.equal(await lastLine(p.page).locator('.ck-bar-mark .status-icon.t5').count(), 1, 'the dashed ring, never red');
    assert.equal(await steps(p.page), 0);
    assert.equal(sends(fx).length, 0);
    // While typing, the tabs hide; once blurred, the bar is docked directly above them.
    assert.equal(await p.page.locator('.app-nav').isVisible(), false, 'tabs hidden while the bar has focus');
    await bar(p.page).press('Escape');
    assert.equal(await bar(p.page).evaluate((el) => document.activeElement === el), false, 'Escape blurs');
    const [b, nav] = await Promise.all([p.page.locator('[data-part=command-bar]').boundingBox(), p.page.locator('.app-nav').boundingBox()]);
    assert.ok(b && nav, 'both drawn');
    assert.ok(b.y + b.height <= nav.y, `the bar (bottom ${b.y + b.height}) ends above the tabs (top ${nav.y})`);
    assert.ok(nav.y - (b.y + b.height) <= 16, 'docked just above them');
    const field = await p.page.locator('.ck-bar-field').boundingBox();
    assert.ok(field && field.height >= 44, 'a 44 px target');
  } finally { await p.close(); await fx.close(); }
});

test('CK3 keys: `:` focuses the bar; `/` and ⌘K still open the navigation dialog, never the bar', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, DESKTOP);
  const dialog = p.page.getByRole('dialog');
  try {
    await p.page.locator('body').click({ position: { x: 4, y: 4 } });
    await p.page.keyboard.press(':');
    assert.equal(await bar(p.page).evaluate((el) => document.activeElement === el), true, '`:` focuses the bar');
    assert.equal(await bar(p.page).inputValue(), '', 'the `:` is not typed');
    await p.page.keyboard.type('/x');
    assert.equal(await bar(p.page).inputValue(), '/x', 'in the bar, `/` is text');
    assert.equal(await dialog.count(), 0);
    await bar(p.page).press('Escape');
    await p.page.keyboard.press('/');
    await waitFor(async () => (await dialog.count()) === 1, { what: 'the ⌘K dialog from /' });
    await p.page.keyboard.press('Escape');
    await waitFor(async () => (await dialog.count()) === 0, { what: 'closed' });
    await p.page.keyboard.press('Control+k');
    await waitFor(async () => (await dialog.count()) === 1, { what: 'the ⌘K dialog from Ctrl+K' });
    assert.equal(await dialog.locator('[data-part=command-input]').count(), 0, 'the dialog has no command bar');
    await p.page.keyboard.press('Escape');
    assert.deepEqual(p.errors, []);
  } finally { await p.close(); await fx.close(); }
});

test('CK3 paste (PR #1708 review, R1): pasted lines are one bad command, never run, even after the field strips the newline', async () => {
  const fx = await cockpitSite();
  const p = await openCockpit(browser, fx, DESKTOP);
  try {
    await p.page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: fx.site.origin });
    await command(p.page, 'next');
    for (const text of ['y\n', 'y\r\n', 'cd lantern\ny', 'ls\nnext']) {
      await p.page.evaluate((t) => navigator.clipboard.writeText(t), text);
      await bar(p.page).focus();
      await p.page.keyboard.press('Control+V');
      await waitFor(async () => (await said(p.page)) === 'One command at a time: pasted lines aren’t run.', { what: `${JSON.stringify(text)} refused` });
      assert.equal(await tone(p.page), 'refused');
      assert.equal(await bar(p.page).inputValue(), '', `${JSON.stringify(text)}: nothing inserted`);
      await bar(p.page).press('Enter');
      assert.equal(await said(p.page), 'One command at a time: pasted lines aren’t run.', 'Enter on the empty field runs nothing');
    }
    assert.equal(await steps(p.page), 0, 'no answer opened');
    assert.equal(await row(p.page, 904).getAttribute('data-open'), 'true', 'the open item and scope are unchanged');
    assert.equal(await p.page.locator('[data-part=scope]').count(), 0);
    assert.equal(sends(fx).length, 0);
    assert.equal(fx.api.log.filter((e) => e.kind === 'preview').length, 0);
    // A one-line paste is typed as usual, and runs only on Enter.
    await p.page.evaluate(() => navigator.clipboard.writeText('blockers'));
    await bar(p.page).focus();
    await p.page.keyboard.press('Control+V');
    assert.equal(await bar(p.page).inputValue(), 'blockers');
    assert.deepEqual(p.errors, []);
  } finally { await p.close(); await fx.close(); }
});
