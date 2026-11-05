// LP6 (#549), the loops page on the fake API: every loop the read returns is
// listed with its cadence, next run, last run and cost; problems first, in the
// server's order; the healthy loops one press away; empty, unavailable and
// malformed reads said as such. Expected words are literals from the fixture
// (test/fixtures/loops/README.md), never computed the way the page does.

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, PHONE, launchBrowser, pageIdle, waitFor } from '../support/browser.mjs';
import { apiError, json } from '../support/fake-api.mjs';
import { ids, load, loopsSite, openLoops, row } from '../fixtures/loops/loops.mjs';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const PROBLEMS = ['ci-watch-atlas', 'nightly-bench', 'review-router'];
const HEALTHY = ['fleet-check-in', 'merge-watcher-lantern', 'pc-health', 'release-reminder', 'huntr'];
const FACTS = {
  'ci-watch-atlas': 'every 10 min · next 09:25 · last run 09:15: check failed · $0.00 in 24 h',
  'nightly-bench': 'daily 02:00 · next tomorrow 02:00 · last run 02:00: agent thread creation unsure (not confirmed) · cost unknown',
  'review-router': 'on review posted · last run 08:51: check timed out · $0.42 in 24 h',
  'fleet-check-in': 'every 5 min · next 09:25 · last run 09:20: nothing to do · $1.84 in 24 h',
  'merge-watcher-lantern': 'every 1 h · next 09:40 · last run 08:40: agent thread created · $0.36 in 24 h',
  'pc-health': 'every 10 min · next 09:30 · last run 09:20: nothing to do · $0.00 in 24 h',
  'release-reminder': 'once, tomorrow 17:00 · next tomorrow 17:00 · not run yet · $0.00 in 24 h',
  huntr: 'every 30 min · off: no next run · last run 07:30: nothing to do · $0.12 in 24 h',
};
const text = (l) => l.innerText();

test('LP6: every loop is listed, problems first in the server order, the healthy ones one press away', async () => {
  const fx = await loopsSite();
  let p = null;
  try {
    p = await openLoops(browser, fx, DESKTOP);
    const page = p.page;
    assert.equal(await page.locator('[data-part=loops-count]').innerText(), '8');
    assert.equal(await page.locator('[data-part=loops-read]').innerText(), 'read 09:20:00 · 3 need a look · 5 healthy');
    assert.deepEqual(await ids(page, 'problems'), PROBLEMS);
    for (const id of PROBLEMS) assert.equal(await row(page, id).isVisible(), true, `${id} shown at once`);
    for (const id of HEALTHY) assert.equal(await row(page, id).isVisible(), false, `${id} is one press away`);
    const show = page.locator('[data-part=show-healthy]');
    assert.equal(await show.innerText(), 'Show 5 healthy loops');
    assert.equal(await show.getAttribute('aria-expanded'), 'false');
    await show.click();
    assert.equal(await show.getAttribute('aria-expanded'), 'true');
    assert.deepEqual(await ids(page, 'healthy'), HEALTHY);
    for (const [id, facts] of Object.entries(FACTS)) {
      assert.equal(await row(page, id).isVisible(), true, `${id} shown`);
      assert.equal(await text(row(page, id).locator('[data-part=facts]')), facts, id);
      assert.equal(await row(page, id).getAttribute('data-problem'), PROBLEMS.includes(id) ? load('target').loops.find((l) => l.id === id).problem : null, id);
      assert.equal(await row(page, id).locator('[data-part=switch]').getAttribute('aria-checked'), id === 'huntr' ? 'false' : 'true', id);
    }
    assert.equal(await text(row(page, 'ci-watch-atlas').locator('[data-part=reason]')), 'Check exited with status 2.');
    assert.equal(await text(row(page, 'nightly-bench').locator('[data-part=reason]')), "The create's outcome was not confirmed.");
    assert.equal(await row(page, 'review-router').locator('[data-part=reason]').count(), 0, 'no reason, none shown');
    assert.equal(await row(page, 'fleet-check-in').locator('[data-part=reason]').count(), 0, 'a healthy loop shows no reason');
    assert.equal(fx.switches.length, 0, 'reading never switches');
  } finally { await p?.close(); await fx.close(); }
});

test('LP6: on the phone the rows fit 390 px and Loops adds no tab', async () => {
  const fx = await loopsSite();
  let p = null;
  try {
    p = await openLoops(browser, fx, PHONE);
    const page = p.page;
    assert.deepEqual(await ids(page, 'problems'), PROBLEMS);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), PHONE.width, 'no sideways scroll');
    assert.equal(await page.locator('.app-nav .nav-loops').isVisible(), false, 'Loops is not in the phone tab bar');
    // Loops adds no phone tab: the visible tabs are exactly the nav's other buttons.
    const tabs = await page.locator('.app-nav button').evaluateAll((bs) => bs.map((b) => ({ loops: b.classList.contains('nav-loops'), shown: b.getClientRects().length > 0, name: b.innerText.trim().replace(/\s+/g, ' ') })));
    // MD9 (#653): the phone bar is exactly these five; Loops is never one of them.
    assert.deepEqual(tabs.filter((t) => t.shown).map((t) => t.name), ['Sessions', 'Fleets', 'Plan', 'Decisions', 'New'], 'MD9\'s phone bar, in order');
    assert.ok(tabs.filter((t) => t.loops).every((t) => !t.shown), 'Loops is hidden on the phone');
    assert.equal(tabs.filter((t) => t.loops).length, 1);
    const box = await row(page, 'ci-watch-atlas').locator('[data-part=switch]').boundingBox();
    assert.ok(box && box.height >= 44 && box.width >= 44, `switch target ${JSON.stringify(box)}`);
  } finally { await p?.close(); await fx.close(); }
});

test('LP6: an empty read says there are no loops; an unavailable one never does', async () => {
  const fx = await loopsSite(load('empty'));
  let p = null;
  try {
    p = await openLoops(browser, fx, DESKTOP);
    const page = p.page;
    assert.match(await page.locator('[data-part=loops-empty]').innerText(), /^No loops yet/);
    assert.equal(await page.locator('[data-part=loops] li[data-loop]').count(), 0);
  } finally { await p?.close(); await fx.close(); }

  const down = await loopsSite();
  down.reply = apiError(503, 'loops_unavailable', 'loop checkout must match its clean default branch');
  let q = null;
  try {
    q = await openLoops(browser, down, DESKTOP);
    const notice = q.page.locator('[data-part=loops] [data-notice]');
    assert.match(await notice.innerText(), /loops_unavailable: loop checkout must match its clean default branch/);
    assert.equal(await q.page.locator('[data-part=loops-empty]').count(), 0, 'unavailable is not "no loops"');
    assert.equal(await q.page.locator('[data-part=loops] li[data-loop]').count(), 0);
  } finally { await q?.close(); await down.close(); }
});

test('LP6: a read with a key written twice is refused, not shown', async () => {
  const fx = await loopsSite();
  const good = json(200, fx.doc);
  fx.reply = { ...good, body: good.body.replace('"read_at_ms": 1800004800000,', '"read_at_ms": 1800004800000,\n  "read_at_ms": 1800004800000,') };
  assert.notEqual(fx.reply.body, good.body);
  let p = null;
  try {
    p = await openLoops(browser, fx, DESKTOP);
    await waitFor(() => p.page.locator('[data-part=loops] [data-notice]').count(), { what: 'the refusal' });
    assert.equal(await p.page.locator('[data-part=loops] li[data-loop]').count(), 0);
    assert.ok(await pageIdle(p.page));
  } finally { await p?.close(); await fx.close(); }
});

test('LP6: views the contract does not allow are refused, not shown (review 1, R4)', async () => {
  const bad = {
    'a cost window other than 24 hours': (d) => { d.cost_window_ms = 1; },
    'healthy loops out of name order': (d) => { [d.loops[3], d.loops[4]] = [d.loops[4], d.loops[3]]; },
    'problems out of name order': (d) => { [d.loops[0], d.loops[1]] = [d.loops[1], d.loops[0]]; },
    'an interval wake with an event next run': (d) => { d.loops[3].next_run = { kind: 'event', event: 'github.workflow_run' }; },
    'an event wake with a timed next run': (d) => { d.loops[2].next_run = { kind: 'at', at_ms: 1_800_005_000_000 }; },
    'a NUL in a name': (d) => { d.loops[3].name = 'Fleet\u0000check-in'; },
    // Review 2: a next run must be classified by the read time and lie on the wake's schedule.
    'a past next run called "at"': (d) => { d.loops[3].next_run = { kind: 'at', at_ms: 0 }; },
    'a future next run called "due"': (d) => { d.loops[3].next_run = { kind: 'due', at_ms: 1_800_005_100_000 }; },
    'an interval next run off its schedule': (d) => { d.loops[3].next_run = { kind: 'at', at_ms: 1_800_005_100_001 }; },
    'a once next run at another time': (d) => { d.loops[6].next_run = { kind: 'at', at_ms: d.loops[6].wake.at_ms + 60_000 }; },
  };
  for (const [why, spoil] of Object.entries(bad)) {
    const doc = load('target');
    spoil(doc);
    const fx = await loopsSite(doc);
    let p = null;
    try {
      p = await openLoops(browser, fx, DESKTOP);
      assert.equal(await p.page.locator('[data-part=loops] [data-notice]').count(), 1, `${why}: refused`);
      assert.equal(await p.page.locator('[data-part=loops] li[data-loop]').count(), 0, `${why}: nothing shown`);
    } finally { await p?.close(); await fx.close(); }
  }
});

