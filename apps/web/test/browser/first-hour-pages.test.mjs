// First-hour pages. This file is shared: #2223 owns the synthetic
// component-state section below; #2205 adds the installed-page captures and
// assertions in its own section.

// ── #2223: the first-hour component on synthetic states ──
// The component (src/components/FirstHour.tsx) rendered from the existing
// readers' parse of each fixture state (test/fixtures/first-hour-pages/), with
// the app's own stylesheets, at 390 and 1440 CSS px. Each step's word and
// shape, the merge summary, the unavailable producers and the free-only copy
// are checked against literals; layout, 44 px targets and axe at both widths.
// Fixture proofs only: no installed page, live account or real merge.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { registerHooks } from 'node:module';
import { join } from 'node:path';
import { after, before, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

import { ALWAYS, NEVER, NOW, STATES, UNKNOWN_FLEETS } from '../fixtures/first-hour-pages/states.mjs';
import { DESKTOP, launchBrowser, PHONE } from '../support/browser.mjs';
import { axe } from '../support/harness.mjs';
import { WEB_DIR } from '../support/paths.mjs';

process.env['TZ'] = 'UTC';

// The test-only TSX loader statusMark.test.ts and fleetGraph.test.ts use.
registerHooks({
  load(url, context, nextLoad) {
    if (!url.startsWith('file:') || !url.endsWith('.tsx')) return nextLoad(url, context);
    const file = fileURLToPath(url);
    const compilerOptions = { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, verbatimModuleSyntax: true };
    return { format: 'module', source: ts.transpileModule(readFileSync(file, 'utf8'), { fileName: file, compilerOptions }).outputText, shortCircuit: true };
  },
});
const { FirstHour, firstHour } = await import('../../src/components/FirstHour.tsx');
const { readSetup } = await import('../../src/api.ts');
const { readDecisionsText } = await import('../../src/decisions.ts');
const { readFleet } = await import('../../src/fleets.ts');

const STEPS = ['install', 'connections', 'idea', 'approval', 'progress', 'merge'];

async function setupOf(text) {
  const r = await readSetup(async () => new Response(text, { status: 200, headers: { 'content-type': 'application/json' } }), new AbortController().signal);
  assert.equal(r.kind, 'ok', 'the setup fixture parses');
  return r.envelope;
}
function decisionsOf(text) {
  const r = readDecisionsText(text);
  assert.ok(r.ok, `the decisions fixture parses: ${r.why}`);
  return r.decisions;
}
function fleetOf(text) {
  if (text === null) return null;
  const r = readFleet(text);
  assert.ok(r.ok, `the fleet fixture parses: ${JSON.stringify(r.refusal)}`);
  return r.envelope;
}
/** A fixture lane as the component's lane, through the existing readers. */
async function lane(l, parse) {
  if (l.state === 'reading') return { state: 'reading' };
  if (l.state === 'failed') return { state: 'failed', why: l.why, last: l.last === null ? null : await parse(l.last) };
  return { state: 'read', value: await parse(l.text) };
}
async function propsOf(s) {
  return { now: NOW, setup: await lane(s.setup, setupOf), decisions: await lane(s.decisions, decisionsOf), fleet: await lane(s.fleet, fleetOf), receipts: new Map(s.receipts) };
}

// #2786 unit cases at the exported component-state boundary. The old
// fixtures combined partial decisions with failed fleets, masking the empty,
// complete-decisions fall-through. Each non-read fleet needs its own case.
for (const name of Object.keys(UNKNOWN_FLEETS)) for (const id of ['idea', 'approval']) {
  test(`#2786 unit: ${name} fleet keeps ${id} unknown`, async () => {
    const props = await propsOf(STATES[`fleet-${name}`]);
    const { steps } = firstHour(props);
    const s = steps.find((s) => s.id === id);
    assert.equal(s.word, 'unknown', `${id}: an unread fleet cannot establish the next action`);
    assert.equal(s.tier, 't5');
    assert.ok(s.detail.includes(name === 'reading' ? 'Reading the fleet…' : props.fleet.why));
    assert.equal(s.next, 'Refresh before giving it again.');
  });
}

test('#2786 unit: complete empty fleet still invites the first idea', async () => {
  const { steps } = firstHour(await propsOf(STATES.start));
  assert.equal(steps.find((s) => s.id === 'idea').word, 'your turn');
  assert.equal(steps.find((s) => s.id === 'approval').word, 'waiting');
});

test('#2786 unit: existing states retain their literal step expectations and merge provenance', async () => {
  for (const [name, state] of Object.entries(STATES)) {
    if (name.startsWith('fleet-')) continue;
    const model = firstHour(await propsOf(state));
    for (const s of model.steps) assert.deepEqual([s.word, s.tier], state.steps[s.id], `${name}: ${s.id}`);
  }
});

test('#2786 unit: merge repository labels its unavailable owner', async () => {
  const merged = firstHour(await propsOf(STATES.merged));
  assert.equal(merged.merge.repository, 'first-idea (owner unknown)');
});

// One loopback page per state: the rendered markup with the app's stylesheets and bundled fonts.
const pages = new Map();
for (const [name, s] of Object.entries(STATES)) pages.set(name, renderToStaticMarkup(createElement(FirstHour, await propsOf(s))));
const server = createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  const name = url.pathname.slice(1);
  if (pages.has(name)) {
    res.writeHead(200, { 'content-type': 'text/html' });
    return res.end(`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>First hour: ${name}</title><link rel="stylesheet" href="/styles/globals.css"><link rel="stylesheet" href="/styles/first-hour.css"><body><main style="padding:16px">${pages.get(name)}</main></body></html>`);
  }
  const file = url.pathname.startsWith('/fonts/') ? join(WEB_DIR, 'public', url.pathname) : url.pathname.startsWith('/styles/') ? join(WEB_DIR, url.pathname) : null;
  if (file === null || url.pathname.includes('..')) { res.writeHead(404); return res.end(); }
  try {
    const body = readFileSync(file);
    res.writeHead(200, { 'content-type': file.endsWith('.css') ? 'text/css' : 'font/woff2' });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
let browser;
let origin;
before(async () => {
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await launchBrowser();
});
after(async () => { await browser?.close(); server.close(); });

test('#2223: every first-hour state shows each step\'s word and shape, its merge summary, and only its own facts', async () => {
  const context = await browser.newContext({ viewport: DESKTOP });
  const page = await context.newPage();
  try {
    for (const [name, s] of Object.entries(STATES)) {
      await page.goto(`${origin}/${name}`);
      const steps = await page.locator('.fh-step').evaluateAll((els) => els.map((e) => ({ id: e.getAttribute('data-step'), tier: e.getAttribute('data-tier'), word: e.querySelector('.fh-state')?.textContent ?? null, glyph: e.querySelectorAll('.glyph svg').length })));
      assert.deepEqual(steps.map((x) => x.id), STEPS, `${name}: the six steps, in order`);
      for (const x of steps) {
        assert.deepEqual([x.word, x.tier], s.steps[x.id], `${name}: ${x.id}'s word and tier`);
        assert.equal(x.glyph, 1, `${name}: ${x.id} has one drawn shape beside its word`);
      }
      assert.equal(await page.locator('.fh-merge').getAttribute('data-merge'), s.merge, `${name}: the merge summary`);
      const text = await page.locator('.fh').evaluate((e) => e.textContent);
      for (const phrase of [...s.text, ...ALWAYS]) assert.ok(text.includes(phrase), `${name}: shows ${JSON.stringify(phrase)}`);
      for (const phrase of [...s.absent, ...NEVER]) assert.ok(!text.includes(phrase), `${name}: never shows ${JSON.stringify(phrase)}`);
      assert.equal(await page.locator('.fh-step[data-tier="t1"] .fh-next').count(), await page.locator('.fh-step[data-tier="t1"]').count(), `${name}: every step that needs the owner says what to do next`);
    }
  } finally {
    await context.close();
  }
});

test('#2223: the agents\' threads stay behind a disclosure until the owner opens it', async () => {
  const context = await browser.newContext({ viewport: PHONE });
  const page = await context.newPage();
  try {
    await page.goto(`${origin}/progress`);
    const threads = page.locator('.fh-step[data-step="progress"] details');
    assert.equal(await threads.count(), 1);
    assert.equal(await threads.getAttribute('open'), null, 'closed by default');
    assert.equal(await page.getByText('thr_syn_b2901').isVisible(), false, 'a thread id is hidden until chosen');
    await threads.locator('summary').click();
    assert.equal(await page.getByText('thr_syn_b2901').isVisible(), true, 'shown once the owner opens it');
  } finally {
    await context.close();
  }
});

for (const [width, viewport] of [['phone', PHONE], ['desktop', DESKTOP]]) {
  test(`#2223: every first-hour state at ${viewport.width}px: no sideways scroll, 44 px targets, bundled Geist, axe clean`, async () => {
    const context = await browser.newContext({ viewport, reducedMotion: 'reduce' });
    const page = await context.newPage();
    try {
      for (const name of Object.keys(STATES)) {
        await page.goto(`${origin}/${name}`);
        await page.evaluate(() => document.fonts.ready);
        const layout = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth, width: innerWidth,
          geist: document.fonts.check('14px Geist'),
          small: [...document.querySelectorAll('summary, button, a')].filter((e) => { const r = e.getBoundingClientRect(); return r.height < 44 || r.width < 44; }).map((e) => e.textContent),
        }));
        assert.ok(layout.scroll <= layout.width, `${name} at ${width}: no sideways scroll (${layout.scroll} > ${layout.width})`);
        assert.ok(layout.geist, `${name} at ${width}: Geist loaded`);
        assert.deepEqual(layout.small, [], `${name} at ${width}: every control at least 44 px`);
        assert.deepEqual(await axe(page), [], `${name} at ${width}: axe clean`);
      }
    } finally {
      await context.close();
    }
  });
}

// ── #2205: the installed first-hour pages ──
// The built app (out/) on the test server, with a fake web API answering the
// existing reads (GET /api/v1/setup, /decisions, /fleets, /fleets/{spec}) from
// the same synthetic states, opened at /#first-hour as an owner would. Each
// state's steps and merge summary must match #2223's literals; the mount's own
// rules are checked on top: an empty fleet list read only in part is unknown
// (never "no fleet yet"), a failed read is failed, a decision receipt this tab
// holds shows as sent, never saved, and the screen only reads. With
// OPENWIZ_FIRST_HOUR_CAPTURES=<dir>, every page is also saved at both widths
// (the private actual-page captures). Fixture proofs only: no live account,
// real merge or user's ability to continue.

const { mkdirSync } = await import('node:fs');
const { fakeApi, html, json } = await import('../support/fake-api.mjs');
const { fleetsEmpty, fleetsExample, fleetsListFailed } = await import('../support/fleet-fixtures.ts');
const { startSite } = await import('../support/serve.mjs');
const { waitFor } = await import('../support/browser.mjs');
const { inventory, session, sessionView } = await import('../support/synthetic.ts');
const { PLAN_SLOT } = await import('../fixtures/first-hour-pages/states.mjs');

const CAPTURES = process.env['OPENWIZ_FIRST_HOUR_CAPTURES'] ?? null;
const SPEC = 2900;
/** A fleets list naming only the fixtures' spec #2900. */
function oneFleet() {
  const doc = JSON.parse(fleetsExample());
  doc.data.fleets = doc.data.fleets.slice(0, 1);
  doc.data.fleets[0].spec = SPEC;
  return JSON.stringify(doc);
}
const answer = (res, r) => { res.writeHead(r.status, r.headers); res.end(r.body); };
const text = (t) => ({ status: 200, headers: json(200, null).headers, body: t });
const GONE = html(502, '<p>Bad gateway</p>');

/**
 * The installed cases: #2223's states the server can answer (a read that
 * fails answers 502; a read still pending is not a page state to capture, so
 * states with a lane still reading are left to #2223's section), plus the
 * mount's own partial-list case.
 */
const INSTALLED = {
  ...Object.fromEntries(Object.entries(STATES).filter(([name, s]) => name !== 'setup-failed' && [s.setup, s.decisions, s.fleet].every((l) => l.state !== 'reading')).map(([name, s]) => [name, {
    setup: text(s.setup.text), decisions: text(s.decisions.text),
    fleets: s.fleet.state === 'failed' ? text(oneFleet()) : s.fleet.text === null ? text(fleetsEmpty()) : text(oneFleet()),
    fleet: s.fleet.state === 'failed' ? GONE : s.fleet.text === null ? null : text(s.fleet.text),
    receipts: s.receipts, steps: s.steps, merge: s.merge,
  }])),
  // A setup read that fails on first open: there is no last report to keep.
  'setup-failed': { setup: GONE, decisions: text(STATES['setup-failed'].decisions.text), fleets: text(fleetsEmpty()), fleet: null, receipts: [],
    steps: { ...STATES['setup-failed'].steps }, merge: 'none' },
  // The spec list was not read: no fleet is listed, so progress and the merge are unknown, never "none yet".
  'fleet-list-partial': { setup: text(STATES.start.setup.text), decisions: text(STATES.progress.decisions.text), fleets: text(fleetsListFailed()), fleet: null, receipts: [],
    steps: { install: ['done', 't2'], connections: ['done', 't2'], idea: ['unknown', 't5'], approval: ['unknown', 't5'], progress: ['failed', 't1'], merge: ['unknown', 't5'] }, merge: 'unknown' },
};

/** Design rule 19: a synthetic capture carries a DEMO tag. Test-only, after every check. */
async function capture(page, file) {
  mkdirSync(CAPTURES, { recursive: true });
  await page.evaluate(() => {
    const tag = document.createElement('div');
    tag.textContent = 'DEMO · synthetic data';
    Object.assign(tag.style, { position: 'fixed', top: '4px', left: '50%', transform: 'translateX(-50%)', zIndex: '100', padding: '4px 12px', borderRadius: '9999px', background: 'var(--s3)', color: 'var(--ink)', font: 'var(--ow-type-caption)' });
    document.body.append(tag);
  });
  await page.screenshot({ path: join(CAPTURES, `${file}.png`), fullPage: true });
}

/**
 * Opens one installed case. `path`: where the page starts (`/#first-hour`, or
 * `/` to start elsewhere). `rows`: the session list's rows. `hold`: routes whose
 * answer waits until `release(route)`.
 */
async function installed(name, viewport, { path = '/#first-hour', rows = [], hold = [], decisions = null } = {}) {
  const c = INSTALLED[name];
  const api = fakeApi();
  api.setList(() => json(200, inventory(rows)));
  if (rows[0]) api.setDetail(() => json(200, sessionView(rows[0])));
  const seen = [];
  const held = new Map();
  let setupAnswer = c.setup;
  let decisionAnswer = decisions ?? c.decisions;
  const reply = (res, path, r) => (hold.includes(path) ? held.set(path, () => answer(res, r)) : answer(res, r));
  const site = await startSite((req, res, url) => {
    seen.push(`${req.method} ${url.pathname}`);
    if (url.pathname === '/api/v1/setup') return reply(res, url.pathname, setupAnswer);
    if (url.pathname === '/api/v1/decisions') return reply(res, url.pathname, decisionAnswer);
    if (url.pathname === '/api/v1/fleets') return reply(res, url.pathname, c.fleets);
    if (url.pathname === `/api/v1/fleets/${SPEC}` && c.fleet) return reply(res, url.pathname, c.fleet);
    return api.handler(req, res, url);
  });
  const release = (route) => { const go = held.get(route); assert.ok(go, `${route} is held`); held.delete(route); go(); };
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1, reducedMotion: 'reduce', serviceWorkers: 'block', timezoneId: 'UTC', locale: 'en-GB' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.clock.install({ time: NOW });
  // This tab's own receipts, where the decision slots keep them (src/decisions.ts's slotStorage).
  await page.addInitScript((receipts) => {
    for (const [key, r] of receipts) sessionStorage.setItem(`openwiz.decisions.${encodeURIComponent(key)}.receipt`, JSON.stringify(r));
  }, c.receipts);
  const close = async () => { await context.close(); await site.close(); };
  try {
    await page.goto(`${site.origin}${path}`);
    if (path === '/#first-hour' && hold.length === 0) {
      await page.locator('.fh').waitFor({ timeout: 15_000 });
      await page.locator('[data-part=first-hour-screen] [role=status]', { hasText: 'Read once.' }).waitFor({ timeout: 15_000 });
    }
    await page.evaluate(() => document.fonts.ready);
  } catch (e) {
    await close();
    throw e;
  }
  return { page, seen, errors, close, release, setSetup: (r) => { setupAnswer = r; }, setDecisions: (r) => { decisionAnswer = r; } };
}

test('#2205: the installed first hour shows each state\'s steps and a source-backed merge outcome, and only reads', async () => {
  assert.ok(INSTALLED['sent-not-saved'].receipts.some(([k]) => k === PLAN_SLOT), 'the sent-not-saved case holds the plan slot\'s receipt');
  for (const name of Object.keys(INSTALLED)) {
    const c = INSTALLED[name];
    const p = await installed(name, DESKTOP);
    try {
      const steps = await p.page.locator('.fh-step').evaluateAll((els) => els.map((e) => [e.getAttribute('data-step'), e.querySelector('.fh-state')?.textContent ?? null, e.getAttribute('data-tier')]));
      assert.deepEqual(steps, STEPS.map((id) => [id, ...c.steps[id]]), `${name}: each step's word and tier on the installed page`);
      assert.equal(await p.page.locator('.fh-merge').getAttribute('data-merge'), c.merge, `${name}: the merge summary`);
      if (c.merge !== 'verified') assert.equal(await p.page.getByText('Your first verified merge', { exact: true }).count(), 0, `${name}: no verified merge is claimed`);
      const shown = await p.page.locator('main').evaluate((e) => e.textContent);
      for (const phrase of NEVER) assert.ok(!shown.includes(phrase), `${name}: never shows ${JSON.stringify(phrase)}`);
      assert.ok(p.seen.every((r) => r.startsWith('GET ')), `${name}: only reads (${p.seen.join(', ')})`);
      for (const route of ['/api/v1/setup', '/api/v1/decisions', '/api/v1/fleets']) assert.equal(p.seen.filter((r) => r === `GET ${route}`).length, 1, `${name}: ${route} read once`);
      assert.deepEqual(p.errors, [], `${name}: no page errors`);
    } finally {
      await p.close();
    }
  }
});

test('#2205: Refresh reads again; the desktop sidebar reaches the first hour', async () => {
  const p = await installed('merged', DESKTOP);
  try {
    await p.page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await p.page.locator('[data-part=first-hour-screen] [role=status]', { hasText: 'Read once.' }).waitFor();
    assert.equal(p.seen.filter((r) => r === 'GET /api/v1/setup').length, 2, 'Refresh reads setup again');
    await p.page.getByRole('navigation', { name: 'Views', exact: true }).getByRole('button', { name: 'Sessions', exact: true }).click();
    assert.equal(await p.page.locator('.fh').count(), 0);
    await p.page.getByRole('navigation', { name: 'Views', exact: true }).getByRole('button', { name: 'First hour', exact: true }).click();
    await p.page.locator('.fh').waitFor();
    assert.equal(await p.page.getByRole('link', { name: 'Open setup', exact: true }).getAttribute('href'), '/setup');
  } finally {
    await p.close();
  }
});

for (const [width, viewport] of [['phone', PHONE], ['desktop', DESKTOP]]) {
  test(`#2205: a setup refresh that fails keeps the last report, marked out of date, at ${viewport.width}px`, async () => {
    const p = await installed('start', viewport);
    try {
      p.setSetup(GONE);
      await p.page.getByRole('button', { name: 'Refresh', exact: true }).click();
      await p.page.locator('.fh-step[data-step="install"][data-tier="t1"]').waitFor({ timeout: 15_000 });
      await p.page.locator('[data-part=first-hour-screen] [role=status]', { hasText: 'Read once.' }).waitFor({ timeout: 15_000 });
      const steps = await p.page.locator('.fh-step').evaluateAll((els) => els.map((e) => [e.getAttribute('data-step'), e.querySelector('.fh-state')?.textContent ?? null]));
      assert.deepEqual(steps, [['install', 'failed'], ['connections', 'unknown'], ['idea', 'unknown'], ['approval', 'waiting'], ['progress', 'waiting'], ['merge', 'waiting']]);
      const shown = await p.page.locator('.fh').evaluate((e) => e.textContent);
      for (const phrase of ['Nothing was changed by this read.', 'The last report is kept and may be out of date.']) assert.ok(shown.includes(phrase), `shows ${JSON.stringify(phrase)}`);
      assert.equal(await p.page.locator('.fh-step[data-step="idea"] .fh-next').textContent(), 'Refresh before giving it again.');
      assert.equal(await p.page.locator('.fh-merge').getAttribute('data-merge'), 'none');
      if (CAPTURES) await capture(p.page, `setup-refresh-failed-${width}`);
      // #2516: recovery needs a successful current setup read, not last.ready.
      p.setSetup(text(STATES.start.setup.text));
      await p.page.getByRole('button', { name: 'Refresh', exact: true }).click();
      await p.page.locator('.fh-step[data-step="connections"][data-tier="t2"]').waitFor();
      await p.page.locator('[data-part=first-hour-screen] [role=status]', { hasText: 'Read once.' }).waitFor();
      assert.equal(await p.page.locator('.fh-step[data-step="idea"] .fh-state').textContent(), 'your turn');
      assert.ok(p.seen.every((r) => r.startsWith('GET ')), 'recovery only reads');
    } finally {
      await p.close();
    }
  });
}

// #2516: independent reads can settle before setup. Do not prompt early.
for (const [width, viewport] of [['phone', PHONE], ['desktop', DESKTOP]]) {
  test(`#2516: pending setup keeps the installed first idea unavailable at ${width}`, async () => {
    const p = await installed('start', viewport, { hold: ['/api/v1/setup'] });
    try {
      await waitFor(() => p.seen.includes('GET /api/v1/setup'), { what: 'held setup read' });
      await p.page.locator('.fh-step[data-step="approval"] .fh-state', { hasText: 'waiting' }).waitFor();
      await p.page.locator('.fh-step[data-step="progress"] .fh-state', { hasText: 'waiting' }).waitFor();
      assert.equal(await p.page.locator('.fh-step[data-step="idea"] .fh-state').textContent(), 'reading');
      assert.equal(await p.page.locator('.fh-step[data-step="idea"] .fh-next').textContent(), 'Refresh before giving it again.');
      p.release('/api/v1/setup');
      await p.page.locator('[data-part=first-hour-screen] [role=status]', { hasText: 'Read once.' }).waitFor();
      assert.equal(await p.page.locator('.fh-step[data-step="idea"] .fh-state').textContent(), 'your turn');
      assert.ok(p.seen.every((r) => r.startsWith('GET ')), 'only reads');
    } finally {
      await p.close();
    }
  });
}

// R1 (#2785): the documented link, followed in the same tab, closes an open thread or launcher first.
for (const opened of ['thread', 'launcher']) {
  test(`#2205: following /#first-hour on the phone with a ${opened} open closes it and leaves the guide usable`, async () => {
    const p = await installed('start', PHONE, { path: '/', rows: [session(1)] });
    try {
      await p.page.locator('main [data-session-id]').first().waitFor({ timeout: 15_000 });
      if (opened === 'thread') await p.page.locator('main [data-session-id]').first().click();
      else await p.page.getByRole('navigation', { name: 'Views', exact: true }).getByRole('button', { name: 'New thread', exact: true }).click();
      await p.page.locator('[data-part=detail][open]').waitFor({ timeout: 15_000 });
      await p.page.evaluate(() => { window.location.hash = '#first-hour'; });
      await p.page.locator('.fh').waitFor({ timeout: 15_000 });
      await p.page.locator('[data-part=first-hour-screen] [role=status]', { hasText: 'Read once.' }).waitFor({ timeout: 15_000 });
      assert.equal(await p.page.locator('[data-part=detail][open]').count(), 0, `the ${opened} is closed`);
      await p.page.getByRole('button', { name: 'Refresh', exact: true }).click({ timeout: 5_000 });
      await p.page.locator('[data-part=first-hour-screen] [role=status]', { hasText: 'Read once.' }).waitFor({ timeout: 15_000 });
      assert.equal(p.seen.filter((r) => r === 'GET /api/v1/setup').length, 2, 'Refresh is reachable and reads again');
    } finally {
      await p.close();
    }
  });
}

// R2 (#2785): each request has its own deadline. A slow list must not shorten the detail read after it.
test('#2205: a slow fleet list leaves the fleet detail its own full deadline', async () => {
  const p = await installed('merged', DESKTOP, { hold: ['/api/v1/fleets', `/api/v1/fleets/${SPEC}`] });
  try {
    await waitFor(() => p.seen.includes('GET /api/v1/fleets'), { what: 'the fleet list read' });
    await p.page.clock.runFor(25_000);
    p.release('/api/v1/fleets');
    await waitFor(() => p.seen.includes(`GET /api/v1/fleets/${SPEC}`), { what: 'the fleet detail read' });
    await p.page.clock.runFor(25_000);
    p.release(`/api/v1/fleets/${SPEC}`);
    await p.page.locator('[data-part=first-hour-screen] [role=status]', { hasText: 'Read once.' }).waitFor({ timeout: 15_000 });
    const word = (id) => p.page.locator(`.fh-step[data-step="${id}"] .fh-state`).textContent();
    assert.equal(await word('progress'), 'building', 'the detail read was accepted, not timed out');
    assert.equal(await word('merge'), 'verified');
    assert.equal(await p.page.locator('.fh-merge').getAttribute('data-merge'), 'verified');
  } finally {
    await p.close();
  }
});

test('#2205: the phone keeps its five tabs and reaches the first hour from the command dialog', async () => {
  const p = await installed('start', PHONE);
  try {
    const tabs = p.page.getByRole('navigation', { name: 'Views', exact: true });
    assert.equal(await tabs.getByRole('button', { name: 'First hour', exact: true }).isVisible(), false, 'no sixth phone tab');
    await tabs.getByRole('button', { name: 'Sessions', exact: true }).click();
    assert.equal(await p.page.locator('.fh').count(), 0);
    await p.page.getByRole('button', { name: /^Search or jump to…/ }).filter({ visible: true }).first().click();
    await p.page.getByRole('option', { name: 'Go to First hour', exact: true }).click();
    await p.page.locator('.fh').waitFor({ timeout: 15_000 });
  } finally {
    await p.close();
  }
});

for (const [width, viewport] of [['phone', PHONE], ['desktop', DESKTOP]]) {
  test(`#2205: every installed first-hour page at ${viewport.width}px: no sideways scroll, 44 px targets, axe clean`, async () => {
    for (const name of Object.keys(INSTALLED)) {
      const p = await installed(name, viewport);
      try {
        const layout = await p.page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth, width: innerWidth,
          small: [...document.querySelectorAll(':is([data-part=first-hour-screen], .fh) :is(summary, button, a)')].filter((e) => { const r = e.getBoundingClientRect(); return r.height < 44 || r.width < 44; }).map((e) => e.textContent),
        }));
        assert.ok(layout.scroll <= layout.width, `${name} at ${width}: no sideways scroll (${layout.scroll} > ${layout.width})`);
        assert.deepEqual(layout.small, [], `${name} at ${width}: every first-hour control at least 44 px`);
        assert.deepEqual(await axe(p.page), [], `${name} at ${width}: axe clean`);
        if (CAPTURES) await capture(p.page, `${name}-${width}`);
      } finally {
        await p.close();
      }
    }
  });
}

// #2514: unavailable requests cannot invite answers, and a mounted guide
// ages without a new network response. All account data is synthetic.
for (const [width, viewport] of [['phone', PHONE], ['desktop', DESKTOP]]) {
  test(`#2514: unavailable open decisions explain recovery at ${width}`, async () => {
    const mutations = [
      ['this read is not fresh', (d) => { d.freshness = { state: 'stale', snapshot_at: { known: NOW - 71_000 } }; }],
      ['wording changed', (d) => { d.items[0].current = { known: false }; }],
      ['wording could not be verified', (d) => { d.items[0].current = { unknown: 'Synthetic: wording unavailable.' }; }],
      ['orchestrator', (d) => { d.orchestrator.target = { known: null }; }],
    ];
    for (const [why, mutate] of mutations) {
      const d = JSON.parse(STATES.approval.decisions.text);
      mutate(d);
      const p = await installed('approval', viewport, { decisions: text(JSON.stringify(d)) });
      try {
        const approval = p.page.locator('.fh-step[data-step="approval"]');
        assert.equal(await approval.locator('.fh-state').textContent(), 'unavailable');
        assert.ok((await approval.textContent()).includes(why));
        assert.match(await approval.locator('.fh-next').textContent(), /Refresh/);
        assert.doesNotMatch(await approval.textContent(), /approve it there|Answer it in Decisions/);
        assert.equal(await p.page.locator('.fh-step[data-step="idea"] .fh-state').textContent(), 'done');
        assert.ok(p.seen.every((r) => r.startsWith('GET ')));
        assert.deepEqual(p.errors, []);
      } finally { await p.close(); }
    }
  });

  for (const name of ['start', 'progress', 'approval']) {
    test(`#2514: elapsed ${name} decisions expire and Refresh recovers at ${width}`, async () => {
      const p = await installed(name, viewport);
      const word = (id) => p.page.locator(`.fh-step[data-step="${id}"] .fh-state`).textContent();
      try {
        const expected = name === 'start' ? ['your turn', 'waiting'] : name === 'progress' ? ['done', 'none waiting'] : ['done', 'your turn'];
        assert.deepEqual([await word('idea'), await word('approval')], expected);
        const before = [...p.seen];
        await p.page.clock.runFor(69_000);
        const expired = name === 'start' ? ['unknown', 'unknown'] : name === 'progress' ? ['done', 'unknown'] : ['done', 'unavailable'];
        assert.deepEqual([await word('idea'), await word('approval')], expired);
        assert.match(await p.page.locator('.fh-step[data-step="approval"] .fh-next').textContent(), /Refresh/);
        assert.deepEqual(p.seen, before, 'expiry changes guidance without a request');
        const now = await p.page.evaluate(() => Date.now());
        const fresh = JSON.parse(STATES[name].decisions.text);
        fresh.snapshot_at = now;
        fresh.freshness.snapshot_at.known = now - 2_000;
        fresh.orchestrator.freshness.snapshot_at.known = now - 2_000;
        p.setDecisions(text(JSON.stringify(fresh)));
        await p.page.getByRole('button', { name: 'Refresh', exact: true }).click();
        await p.page.locator('[data-part=first-hour-screen] [role=status]', { hasText: 'Read once.' }).waitFor();
        await waitFor(() => p.seen.filter((r) => r === 'GET /api/v1/decisions').length === 2, { what: 'second decisions read' });
        await p.page.locator('.fh-step[data-step="approval"] .fh-state', { hasText: expected[1] }).waitFor();
        assert.deepEqual([await word('idea'), await word('approval')], expected, 'new read recovers');
        assert.equal(p.seen.filter((r) => r === 'GET /api/v1/decisions').length, 2);
        assert.ok(p.seen.every((r) => r.startsWith('GET ')));
        assert.deepEqual(p.errors, []);
      } finally { await p.close(); }
    });
  }

  test(`#2514: late fleet completion cannot renew the decision receipt at ${width}`, async () => {
    const p = await installed('start', viewport, { hold: ['/api/v1/fleets'] });
    try {
      await p.page.locator('.fh-step[data-step="approval"] .fh-state', { hasText: 'unknown' }).waitFor();
      await p.page.clock.runFor(25_000);
      p.release('/api/v1/fleets');
      await p.page.locator('[data-part=first-hour-screen] [role=status]', { hasText: 'Read once.' }).waitFor();
      assert.equal(await p.page.locator('.fh-step[data-step="idea"] .fh-state').textContent(), 'your turn');
      await p.page.clock.runFor(44_000);
      assert.equal(await p.page.locator('.fh-step[data-step="idea"] .fh-state').textContent(), 'unknown');
      assert.equal(p.seen.filter((r) => r === 'GET /api/v1/decisions').length, 1);
      assert.ok(p.seen.every((r) => r.startsWith('GET ')));
    } finally { await p.close(); }
  });
}
