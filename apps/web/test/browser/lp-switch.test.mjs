// LP6 (#549), the loop switch on the fake API: one press is one
// `POST /api/v1/loops/{id}/on|off` with exactly `{}` and the send's headers;
// a press while it is out, a refresh or the page's own reads send nothing;
// each answer is shown as what it is (saved, refused, busy, unknown).

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, waitFor } from '../support/browser.mjs';
import { apiError, bare, json } from '../support/fake-api.mjs';
import { READ, loopsSite, openLoops, row, saved } from '../fixtures/loops/loops.mjs';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const sw = (page, id) => row(page, id).locator('[data-part=switch]');
const said = (page, id) => row(page, id).locator('[data-part=said]');

test('LP6: the switch sends once per press and shows the saved state', async () => {
  const fx = await loopsSite();
  let p = null;
  try {
    p = await openLoops(browser, fx, DESKTOP);
    const page = p.page;
    fx.holdSwitches = true;
    await sw(page, 'ci-watch-atlas').click();
    await waitFor(() => fx.switches.length === 1, { what: 'the switch request' });
    assert.equal(await sw(page, 'ci-watch-atlas').getAttribute('aria-disabled'), 'true');
    assert.equal(await said(page, 'ci-watch-atlas').innerText(), 'Switching off…');
    // Playwright waits for an aria-disabled control; the owner's browser does not, so press it anyway.
    await sw(page, 'ci-watch-atlas').click({ force: true });
    await sw(page, 'ci-watch-atlas').press('Enter');
    await page.locator('[data-part=loops-refresh]').click();
    await waitFor(() => fx.reads >= 2, { what: 'the refresh read' });
    assert.equal(fx.switches.length, 1, 'no second request while one is out, and none from a refresh');
    const [s] = fx.switches;
    assert.equal(s.method, 'POST');
    assert.equal(s.path, '/api/v1/loops/ci-watch-atlas/off');
    assert.equal(s.body, '{}');
    assert.equal(s.headers['x-openwiz-send'], '1');
    assert.equal(s.headers['content-type'], 'application/json');
    fx.releaseSwitches();
    await waitFor(async () => (await said(page, 'ci-watch-atlas').innerText()) === 'Off · saved 09:21', { what: 'the saved answer' });
    assert.equal(await sw(page, 'ci-watch-atlas').getAttribute('aria-checked'), 'false');
    // A read taken before the save still says on; the saved switch is shown until a later read.
    await page.locator('[data-part=loops-refresh]').click();
    await waitFor(() => fx.reads >= 3, { what: 'another read' });
    assert.equal(await sw(page, 'ci-watch-atlas').getAttribute('aria-checked'), 'false');
    // The page's own reads send nothing.
    await page.clock.runFor(130_000);
    assert.equal(fx.switches.length, 1);

    // A switched-off loop turns on with `/on`.
    fx.holdSwitches = false;
    await page.locator('[data-part=show-healthy]').click();
    await sw(page, 'huntr').click();
    await waitFor(async () => (await said(page, 'huntr').innerText()) === 'On · saved 09:21', { what: 'huntr on' });
    assert.equal(fx.switches.length, 2);
    assert.equal(fx.switches[1].path, '/api/v1/loops/huntr/on');
    assert.equal(await sw(page, 'huntr').getAttribute('aria-checked'), 'true');
  } finally { await p?.close(); await fx.close(); }
});

test('LP6: refused, busy, lost and unreadable answers are shown as such, and the switch is unchanged', async () => {
  const fx = await loopsSite();
  let p = null;
  const cases = [
    [() => apiError(409, 'switch_refused', 'loop repository or project identity is not verified'), 'Not switched: loop repository or project identity is not verified'],
    [() => apiError(503, 'switch_busy', 'a loop pass is running; retry the loop switch', { 'Retry-After': '5' }), 'Not switched: a loop pass is running. Press again in a few seconds.'],
    [() => 'drop', 'Switch unknown (the connection was lost before an answer): it may have been saved. Refresh to see.'],
    [(e) => saved(e.id, !e.on, READ + 60_000), 'Switch unknown (the answer could not be read): it may have been saved. Refresh to see.'],
    [() => json(500, { error: { kind: 'internal', message: 'synthetic' } }), 'Switch unknown (HTTP 500): it may have been saved. Refresh to see.'],
    // Review 1, R3: a success is only the complete saved event.
    [(e) => { const r = saved(e.id, e.on); const b = JSON.parse(r.body); delete b.definition_revision; return { ...r, body: JSON.stringify(b) }; }, 'Switch unknown (the answer could not be read): it may have been saved. Refresh to see.'],
    [(e) => { const r = saved(e.id, e.on); const b = JSON.parse(r.body); b.extra = true; return { ...r, body: JSON.stringify(b) }; }, 'Switch unknown (the answer could not be read): it may have been saved. Refresh to see.'],
    [(e) => { const r = saved(e.id, e.on); const b = JSON.parse(r.body); b.project = ' '; return { ...r, body: JSON.stringify(b) }; }, 'Switch unknown (the answer could not be read): it may have been saved. Refresh to see.'],
    // Review 2: the project must be a project id, as the store checks it.
    [(e) => { const r = saved(e.id, e.on); const b = JSON.parse(r.body); b.project = '!'; return { ...r, body: JSON.stringify(b) }; }, 'Switch unknown (the answer could not be read): it may have been saved. Refresh to see.'],
    // Review 2: the bodyless connection-cap 503 is not a loop pass.
    [() => bare(503, { 'Retry-After': '5' }), 'Not switched: the server was busy. Press again in a few seconds.'],
  ];
  try {
    p = await openLoops(browser, fx, DESKTOP);
    const page = p.page;
    for (const [i, [answer, words]] of cases.entries()) {
      fx.answer = answer;
      await sw(page, 'nightly-bench').click();
      await waitFor(async () => (await said(page, 'nightly-bench').innerText()) === words, { what: words });
      assert.equal(fx.switches.length, i + 1, 'one request per press');
      assert.equal(await sw(page, 'nightly-bench').getAttribute('aria-checked'), 'true', `unchanged after: ${words}`);
    }
  } finally { await p?.close(); await fx.close(); }
});

test('LP6: a later refused press keeps the last saved state shown (review 1, R2)', async () => {
  const fx = await loopsSite();
  let p = null;
  try {
    p = await openLoops(browser, fx, DESKTOP);
    const page = p.page;
    await sw(page, 'ci-watch-atlas').click();
    await waitFor(async () => (await said(page, 'ci-watch-atlas').innerText()) === 'Off · saved 09:21', { what: 'saved off' });
    fx.answer = () => apiError(503, 'switch_busy', 'a loop pass is running; retry the loop switch', { 'Retry-After': '5' });
    await sw(page, 'ci-watch-atlas').click();
    await waitFor(async () => (await said(page, 'ci-watch-atlas').innerText()).startsWith('Not switched'), { what: 'busy' });
    assert.equal(fx.switches.length, 2);
    assert.equal(fx.switches[1].path, '/api/v1/loops/ci-watch-atlas/on');
    assert.equal(await sw(page, 'ci-watch-atlas').getAttribute('aria-checked'), 'false', 'still the saved off');
  } finally { await p?.close(); await fx.close(); }
});

test('LP6: a read during a switch does not move the pressed switch (review 1, R6)', async () => {
  const fx = await loopsSite();
  let p = null;
  try {
    p = await openLoops(browser, fx, DESKTOP);
    const page = p.page;
    fx.holdSwitches = true;
    await sw(page, 'ci-watch-atlas').click();
    await waitFor(() => fx.switches.length === 1, { what: 'the switch request' });
    // A newer read says the loop is healthy now: it would move to the hidden healthy list.
    const healed = structuredClone(fx.doc);
    const loop = healed.loops.shift();
    loop.problem = null;
    loop.last_run = { ...loop.last_run, result: 'quiet', reason: null };
    healed.loops.splice(2, 0, loop); // first healthy by name: "CI watch: Atlas" < "Fleet check-in"
    fx.doc = healed;
    // A read arriving while the switch is out: a scripted click starts it and leaves focus where the owner left it.
    await page.evaluate(() => document.querySelector('[data-part=loops-refresh]').click());
    await waitFor(() => fx.reads >= 2, { what: 'the newer read' });
    await waitFor(async () => Number(await page.locator('[data-part=loops]').getAttribute('data-snapshot-seq')) >= 2, { what: 'the newer read delivered' });
    await page.waitForTimeout(100);
    assert.equal(await row(page, 'ci-watch-atlas').locator('[data-part=switch]').isVisible(), true, 'the pressed switch stays in place');
    assert.equal(await page.evaluate(() => document.activeElement?.closest('[data-loop]')?.getAttribute('data-loop')), 'ci-watch-atlas', 'focus stays on it');
    fx.releaseSwitches();
    await waitFor(async () => (await said(page, 'ci-watch-atlas').innerText()) === 'Off · saved 09:21', { what: 'saved' });
    // Review 2: once settled, the pressed loop has moved to the healthy group; it stays visible, with its answer and focus.
    await waitFor(async () => (await sw(page, 'ci-watch-atlas').isVisible()) && (await said(page, 'ci-watch-atlas').isVisible()), { what: 'the moved switch and its answer shown' });
    assert.equal(await page.evaluate(() => document.activeElement?.closest('[data-loop]')?.getAttribute('data-loop')), 'ci-watch-atlas', 'focus follows it');
    // Settled: the newer read is shown now.
    await waitFor(async () => (await page.locator('[data-part=problems] li[data-loop]').count()) === 2, { what: 'the newer read shown' });
  } finally { await p?.close(); await fx.close(); }
});

test('LP6: after a saved switch, the next run follows it even when the next read fails (review of #1717, R1)', async () => {
  const fx = await loopsSite();
  let p = null;
  try {
    p = await openLoops(browser, fx, DESKTOP);
    const page = p.page;
    fx.reply = apiError(503, 'loops_unavailable', 'synthetic read failure after save');
    const facts = (id) => row(page, id).locator('[data-part=facts]').innerText();
    await sw(page, 'ci-watch-atlas').click();
    await waitFor(async () => (await said(page, 'ci-watch-atlas').innerText()) === 'Off · saved 09:21', { what: 'saved off' });
    await waitFor(() => page.locator('[data-part=loops] [data-notice]').count(), { what: 'the failed read' });
    assert.equal(await facts('ci-watch-atlas'), 'every 10 min · off: no next run · last run 09:15: check failed · $0.00 in 24 h');
    await page.locator('[data-part=show-healthy]').click();
    await sw(page, 'huntr').click();
    await waitFor(async () => (await said(page, 'huntr').innerText()) === 'On · saved 09:21', { what: 'saved on' });
    assert.equal(await facts('huntr'), 'every 30 min · next run: awaiting a fresh read · last run 07:30: nothing to do · $0.12 in 24 h');
  } finally { await p?.close(); await fx.close(); }
});

