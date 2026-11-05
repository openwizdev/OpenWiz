// Design hill-climb captures (2026-11-04): the built app (out/) on the run's
// design brief's synthetic content packet, the integrated screens and Home states at 390 x 844 and 1440 x 900 CSS px, full
// page, 1x, reduced motion, UTC: `node test/design-screens.mjs <new-out-dir>`.
// Writes <screen>/phone.png, <screen>/desktop.png and capture.json. Not a
// proof. Synthetic data only; nothing is live. Needs out/ (npm run build).

import { existsSync, mkdirSync, writeFileSync } from 'node:fs';

import { DESKTOP, launchBrowser, openPage, PHONE, readDetail, readView, waitFor } from './support/browser.mjs';
import { apiError, HANG, json } from './support/fake-api.mjs';
import { fakeApi } from './support/fake-api.mjs';
import { contractExample } from './support/fleet-graph-fixtures.ts';
import { fleetsEmpty, fleetsExample } from './support/fleet-fixtures.ts';
import * as nt from './support/newthread-synthetic.ts';
import { startSite } from './support/serve.mjs';
import { inventory, preview, session, sessionView, T0 } from './support/synthetic.ts';

const dir = process.argv[2];
if (!dir || existsSync(dir)) throw new Error('usage: node test/design-screens.mjs <new-out-dir> (the folder must not exist)');
const only = process.argv[3] ? process.argv[3].split(',') : null;
mkdirSync(dir, { recursive: true });

const MIN = 60_000;
const atlas = { kind: 'project', id: 'prj_syn_atlas', name: { known: 'Atlas' } };
const lantern = { kind: 'project', id: 'prj_syn_lantern', name: { known: 'Lantern' } };
const cfg = (model, effort) => ({ model: { known: model }, effort: { known: effort } });
const purpose = (text) => ({ known: { kind: 'purpose_as_reported', text, truncated: false } });
const local = (machine) => ({ known: { kind: 'local', machine: { known: machine } } });
const ago = (ms) => ({ updated_at: { known: T0 - ms }, age_ms: { known: ms } });

const S = [
  session(1, { id: 'sess-7f3a9c', title: { known: 'Fix flaky attachment upload test' }, status: { known: 'active' }, group: atlas, reported_configuration: cfg('gpt-6.1-sol', 'high'),
    recap: purpose("Find why the attachment upload test fails about one run in twenty and fix it without changing the tray's behaviour."), ...ago(2 * MIN) }),
  session(2, { id: 'sess-2b81d0', title: { known: 'Draft release notes for 0.4.0' }, provider: { known: 'claude-code' }, status: { known: 'idle' }, group: atlas, location: local('studio-pc'),
    reported_configuration: cfg('opus-5.5', 'medium'), recap: purpose('Draft the 0.4.0 release notes from the merged changes.'), ...ago(14 * MIN) }),
  session(3, { id: 'sess-c40e17', title: { known: 'Refactor poller backoff' }, status: { known: 'error' }, group: atlas, reported_configuration: cfg('gpt-6.1-terra', 'medium'),
    recap: purpose('Simplify the poller backoff without changing its bounds.'), ...ago(60 * MIN) }),
  session(4, { id: 'sess-9d2e55', title: { known: 'Cedar — documentation and compatibility verification' }, provider: { known: 'claude-code' }, status: { known: 'idle' }, group: atlas,
    parent: { known: 'sess-2b81d0' }, reported_configuration: cfg('sonnet-5.5', 'low'), recap: purpose('Check the docs against the 0.4.0 behaviour.'), ...ago(180 * MIN) }),
  session(5, { id: 'sess-51aa3e', title: { known: 'Audit landing page contrast' }, status: { known: 'active' }, group: lantern, reported_configuration: cfg('gpt-6.1-sol', 'medium'),
    recap: purpose('Measure every text pair on the landing page against AA.'), ...ago(10_000) }),
  session(6, { id: 'sess-e0f6b2', title: { known: 'Spike: offline cache for the app shell' }, provider: { known: 'claude-code' }, status: { known: 'idle' }, group: lantern, location: local('travel-mac'),
    reported_configuration: cfg('opus-5.5', 'high'), recap: purpose('Try an offline cache for the app shell; report, change nothing.'), ...ago(2 * 24 * 60 * MIN) }),
  session(7, { id: 'sess-0a7c33', title: { unknown: 'title field missing' }, status: { unknown: 'status field missing' }, group: lantern,
    recap: { unknown: 'not read' }, updated_at: { unknown: 'field missing' }, age_ms: { unknown: 'field missing' } }),
];
const GAPS = [{ kind: 'timed_out', subject: 'sess-0a7c33', detail: '1 session in Lantern could not be read (timed out after 15 s)' }];
const FINAL = 'Found it: the upload test raced the thumbnail decode. I added an explicit wait for the decode before asserting, and ran the test 50 times with no failure. Commit 3f9a2c1 on fix-upload-race.';

const site = async (listFn, fleetReply = null) => {
  let failedReads = false;
  const failed = () => apiError(502, 'read_failed', 'Synthetic: the server could not read this source');
  const api = fakeApi();
  api.setList((...args) => failedReads ? failed() : listFn(...args));
  api.setDetail((id) => {
    const s = S.find((r) => r.id === id) ?? S[0];
    const o = s.id === 'sess-7f3a9c' ? { finalOutput: { known: { kind: 'reported', text: FINAL, truncated: false } } }
      : s.id === 'sess-c40e17' ? { reportedError: { known: { text: 'Build failed: 2 tests in poller.spec failed', truncated: false } } } : {};
    return json(200, sessionView(s, o));
  });
  api.setPreview((id, mode) => json(200, preview(id, S.find((r) => r.id === id)?.status.known === 'active' ? 'busy' : 'idle', mode)));
  api.setOptions(() => json(200, nt.options()));
  // Synthetic assumption: the listed active s1 is the configured orchestrator.
  const fleetList = JSON.parse(fleetsExample());
  fleetList.orchestrator = S[0].id;
  const handler = (req, res, url) => {
    if (url.pathname === '/api/v1/fleets/901') {
      const reply = json(200, contractExample(2));
      res.writeHead(reply.status, reply.headers);
      return res.end(reply.body);
    }
    if (url.pathname === '/api/v1/fleets') {
      const reply = failedReads ? failed() : fleetReply ?? json(200, fleetList);
      if (reply === HANG) return;
      res.writeHead(reply.status, reply.headers);
      return res.end(reply.body);
    }
    return api.handler(req, res, url);
  };
  return { ...await startSite(handler), failReads: () => { failedReads = true; } };
};

const rowsShown = (page) => waitFor(async () => (await readView(page)).groups.length > 0, { what: 'rows' });
const openThread = async (page) => {
  await page.click('[data-session-id="sess-7f3a9c"]');
  await waitFor(async () => (await readDetail(page))?.title === 'Fix flaky attachment upload test', { what: 'detail' });
  const box = page.locator('[data-part=composer] textarea');
  await box.fill('Also check the removal test for the same race');
  const queue = page.locator('[data-part=composer] [data-part=queue], [data-part=composer] [data-part=send]').first();
  await waitFor(async () => (await queue.getAttribute('aria-disabled')) !== 'true', { what: 'queue ready' });
  await queue.click();
  await waitFor(async () => (await page.locator('[data-part=attempt]').count()) > 0, { what: 'sent' });
  await box.fill('Now run the whole tray suite once and report');
};
const openNew = async (page) => {
  await page.click('[aria-label="New thread in Atlas"]');
  await waitFor(async () => (await page.locator('dialog[open][data-launch] [data-part=launcher] select').first().locator('option').count()) > 1, { what: 'open launcher with options' });
  const box = page.locator('[data-part=launcher] textarea');
  await box.fill('Write a migration guide for the 0.4.0 config change');
};
const openFleets = async (page) => {
  await page.getByRole('button', { name: 'Fleets', exact: true }).first().click();
  await waitFor(async () => (await page.locator('[data-part=fleet-list] button[data-fleet]').count()) > 0, { what: 'fleet rows' });
};

const openFleetDetail = async (page) => {
  await openFleets(page);
  await page.locator('[data-part=fleet-list] button[data-fleet]').first().click();
  await waitFor(async () => (await page.locator('.fleet-detail[data-fleet="901"]').count()) > 0, { what: 'fleet detail' });
};

/** Home: its sidebar tab on the PC; on the phone (MD9) through the command dialog. */
const goHome = async (page) => {
  const tab = page.getByRole('button', { name: 'Home', exact: true });
  if (await tab.isVisible()) return tab.click();
  await page.getByRole('button', { name: /^Search or jump to…/ }).filter({ visible: true }).first().click();
  await page.getByRole('combobox', { name: 'Search navigation' }).fill('Go to Home');
  await page.keyboard.press('Enter');
};
const openHome = async (page) => {
  await goHome(page);
  await waitFor(() => page.locator('[data-part=needs-you] [data-ticket="904"]').count(), { what: 'Home decisions' });
};
const openHomeAnswer = async (page) => {
  await openHome(page);
  await page.getByRole('button', { name: 'Answer #904', exact: true }).click();
  await waitFor(() => page.locator('[data-part=composer][data-preview="ready"]').count(), { what: 'Home answer composer' });
};
const SCREENS = [
  { name: 'loading', list: () => HANG, wait: (page) => waitFor(async () => (await readView(page)).connection === 'reading', { what: 'loading' }) },

  { name: 'home-loading', list: () => HANG, fleetReply: HANG,
    wait: (page) => waitFor(async () => (await readView(page)).connection === 'reading', { what: 'loading inventory' }),
    act: async (page) => {
      await goHome(page);
      await waitFor(() => page.getByText('reading sessions…', { exact: true }).count(), { what: 'Home loading' });
    } },
  { name: 'home-empty', list: () => json(200, inventory([])), fleetReply: json(200, JSON.parse(fleetsEmpty())),
    wait: (page) => waitFor(async () => (await readView(page)).empty, { what: 'empty inventory' }),
    act: async (page) => {
      await goHome(page);
      await waitFor(() => page.getByText('Nothing needs you', { exact: true }).count(), { what: 'Home fresh zero' });
    } },
  { name: 'home-error', list: () => apiError(502, 'read_failed', 'Synthetic: the server could not read the sessions'),
    fleetReply: apiError(502, 'read_failed', 'Synthetic: the server could not read the fleets'),
    wait: (page) => waitFor(async () => (await readView(page)).notice !== null, { what: 'inventory error' }),
    act: async (page) => {
      await goHome(page);
      await waitFor(() => page.locator('[data-part=fleet-screen] > [role=status] [data-notice=error]').count(), { what: 'Home fleet error' });
    } },
  { name: 'home-stale', list: () => json(200, inventory(S, { state: 'partial', gaps: GAPS })),
    act: async (page, source) => {
      await openHome(page);
      source.failReads();
      await page.clock.runFor(70_001);
      await waitFor(() => page.locator('[data-part=home-live] [data-part=stale]').count(), { what: 'retained stale inventory' });
      await waitFor(() => page.locator('[data-part=fleet-screen] > .page-head [data-part=stale]').count(), { what: 'retained stale fleets' });
    } },
  { name: 'home', list: () => json(200, inventory(S, { state: 'partial', gaps: GAPS })), act: openHome },
  { name: 'home-live', viewportOnly: true, list: () => json(200, inventory(S, { state: 'partial', gaps: GAPS })), act: async (page) => {
    await openHome(page);
    await page.mouse.wheel(0, 1_200);
    await waitFor(async () => {
      const last = await page.locator('[data-part=home-live] .row').last().boundingBox();
      const tabs = await page.locator('.app-nav').boundingBox();
      return last.y + last.height <= (page.viewportSize().width < 900 ? tabs.y : page.viewportSize().height);
    }, { what: 'both live rows above the fixed phone tabs or desktop viewport edge' });
  } },
  { name: 'home-answer', list: () => json(200, inventory(S, { state: 'partial', gaps: GAPS })), act: openHomeAnswer },

  { name: 'sessions', list: () => json(200, inventory(S, { state: 'partial', gaps: GAPS })) },
  { name: 'thread', list: () => json(200, inventory(S, { state: 'partial', gaps: GAPS })), act: openThread },
  { name: 'new-thread', list: () => json(200, inventory(S, { state: 'partial', gaps: GAPS })), act: openNew },
  { name: 'fleets', list: () => json(200, inventory(S, { state: 'partial', gaps: GAPS })), act: openFleets },
  { name: 'fleet-detail', list: () => json(200, inventory(S, { state: 'partial', gaps: GAPS })), act: openFleetDetail },
  { name: 'empty', list: () => json(200, inventory([])), wait: (page) => waitFor(async () => (await readView(page)).empty, { what: 'empty' }) },
  { name: 'error', list: () => apiError(502, 'read_failed', 'Synthetic: the server could not read the sessions'), wait: (page) => waitFor(async () => (await readView(page)).notice !== null, { what: 'read error' }) },
];

const browser = await launchBrowser();
// Provenance only; never read by the capture script.
const manifest = { tool: 'apps/web/test/design-screens.mjs', packet: 'brief/content-packet.md', label: 'DEMO · synthetic data', synthetic: true, assumptions: ['The listed active s1 is the configured orchestrator for the fleet-list fixture.'], clock: new Date(T0 + 30_000).toISOString(), screens: [] };
let failed = 0;
for (const sc of SCREENS) {
  if (only && !only.includes(sc.name)) continue;
  mkdirSync(`${dir}/${sc.name}`);
  for (const [file, viewport] of [['phone', PHONE], ['desktop', DESKTOP]]) {
    const s = await site(sc.list, sc.fleetReply);
    const p = await openPage(browser, s.origin, { viewport, clock: T0 + 30_000 });
    try {
      await (sc.wait ?? rowsShown)(p.page);
      if (sc.act) await sc.act(p.page, s);
      await p.page.evaluate(async () => { await document.fonts.ready; await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))); });
      await p.page.evaluate(() => {
        const label = document.createElement('div');
        label.textContent = 'DEMO · synthetic data';
        label.setAttribute('data-capture-label', 'demo');
        label.setAttribute('popover', 'manual');
        Object.assign(label.style, { position: 'fixed', top: '4px', bottom: 'auto', left: '50%', right: 'auto', margin: '0', border: '0', transform: 'translateX(-50%)', padding: '2px 8px', borderRadius: '4px', background: '#17171c', color: '#fff', font: '10px sans-serif', pointerEvents: 'none' });
        // A capture-only top-layer label stays above modal and non-modal sheets.
        (document.querySelector('dialog[open]') ?? document.body).append(label);
        label.showPopover();
      });
      if (!await p.page.locator('[data-capture-label=demo]').evaluate((label) => label.matches(':popover-open'))) throw new Error('DEMO label is hidden');
      const modal = await p.page.evaluate(() => document.querySelector('dialog:modal') !== null);
      // A native modal is the viewport; record cropping explicitly in the manifest.
      // Only the DEMO label is added; reading-state scroll is recorded below.
      const size = await p.page.evaluate(() => ({ contentWidth: document.documentElement.scrollWidth, contentHeight: document.documentElement.scrollHeight, scrollX: window.scrollX, scrollY: window.scrollY }));
      const fullPage = !modal && !sc.viewportOnly;
      if (size.contentWidth > viewport.width) throw new Error(`horizontal overflow: ${size.contentWidth} > ${viewport.width}`);
      if (p.errors.length) throw new Error(`page error: ${p.errors[0]}`);
      await p.page.screenshot({ path: `${dir}/${sc.name}/${file}.png`, fullPage });
      const overflow = size.contentWidth > viewport.width;
      if (overflow) failed++;
      manifest.screens.push({ screen: sc.name, file: `${sc.name}/${file}.png`, viewport, fullPage, ...size, overflow, errors: p.errors.slice(0, 5) });

    } catch (e) {
      failed++;
      manifest.screens.push({ screen: sc.name, file: null, viewport, failure: String(e).slice(0, 300) });
    }
    await p.close();
    await s.close();
  }
}
await browser.close();
writeFileSync(`${dir}/capture.json`, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`design-screens: ${manifest.screens.length - failed} captures, ${failed} failed, in ${dir}`);
process.exit(failed ? 1 : 0);
