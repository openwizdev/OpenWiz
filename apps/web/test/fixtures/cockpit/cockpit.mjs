// The cockpit proofs' site (#536): the page's static export, the scripted
// fake API for every other route (the send, its preview and lookup), and
// `GET /api/v1/cockpit` answered from a document the proof can change
// between reads. Synthetic values only (README.md).

import { readFileSync } from 'node:fs';

import { openPage, pageIdle, waitFor } from '../../support/browser.mjs';
import { fakeApi, json } from '../../support/fake-api.mjs';
import { startSite } from '../../support/serve.mjs';

/** The fixtures' assembly time, and the proofs' paused clock. */
export const T = 1_800_000_000_000;
export const START = new Date(T);

export const load = (name) => JSON.parse(readFileSync(new URL(`./${name}.json`, import.meta.url), 'utf8'));

const freshnessOf = (doc) => [doc.projects.freshness, doc.needs_you.freshness, doc.agents.freshness, ...doc.projects.items.map((p) => p.orchestrator.freshness)];

/** Every known source snapshot `ms` older than assembly: stale past the contract's 70 s, as the server would say. */
export function aged(doc, ms) {
  const d = structuredClone(doc);
  for (const f of freshnessOf(d)) {
    if (f.state === 'unknown') continue;
    f.snapshot_at.known = d.snapshot_at - ms;
    f.state = ms > 70_000 ? 'stale' : 'fresh';
  }
  return d;
}

/** The empty universe, but with one fleet source unread: partial, so never "Nothing needs you". */
export function partialEmpty() {
  const d = load('empty');
  d.needs_you.coverage = { state: 'partial', gaps: [{ project: 'prj_syn_lan2', kind: 'command_failed', detail: 'Synthetic fleet source could not be read' }] };
  return d;
}

/**
 * A site whose cockpit route answers `fx.doc` (or `fx.reply`, when set) on
 * each read. With `fx.holding`, a read is held until `fx.releaseReads()`:
 * the server's work goes on even when the page gives up on it, as a slow
 * read on the PC would. `fx.inFlight` and `fx.maxInFlight` count the
 * server's reads from arrival until answered.
 */
export async function cockpitSite(doc = load('target')) {
  const api = fakeApi();
  const fx = { api, doc, reply: null, reads: 0, holding: false, held: [], inFlight: 0, maxInFlight: 0 };
  fx.releaseReads = () => {
    for (const answer of fx.held.splice(0)) answer();
  };
  const site = await startSite((req, res, url) => {
    if (url.pathname !== '/api/v1/cockpit') return api.handler(req, res, url);
    fx.reads++;
    fx.inFlight++;
    fx.maxInFlight = Math.max(fx.maxInFlight, fx.inFlight);
    const answer = () => {
      fx.inFlight--;
      if (res.destroyed || res.writableEnded) return;
      const reply = fx.reply ?? json(200, fx.doc);
      res.writeHead(reply.status, reply.headers);
      res.end(reply.body);
    };
    if (fx.holding) fx.held.push(answer);
    else answer();
  });
  fx.site = site;
  fx.close = () => site.close();
  return fx;
}

/** Shows the cockpit in `page` and waits until its read is consumed. */
export async function showCockpit(page) {
  await waitFor(() => pageIdle(page), { what: 'the first reads consumed' });
  const tab = page.getByRole('navigation', { name: 'Views', exact: true }).getByRole('button', { name: 'Cockpit', exact: true });
  // On the phone (MD9) Cockpit is reached through the command dialog.
  if (await tab.isVisible()) await tab.click();
  else {
    await page.getByRole('button', { name: /^Search or jump to…/ }).filter({ visible: true }).first().click();
    await page.getByRole('combobox', { name: 'Search navigation' }).fill('Go to Cockpit');
    await page.keyboard.press('Enter');
  }
  await waitFor(async () => (await page.locator('[data-part=cockpit]').getAttribute('data-snapshot-seq')) !== '0' || (await page.locator('[data-part=cockpit] [data-notice]').count()) > 0, { what: 'the cockpit read' });
  await waitFor(() => pageIdle(page), { what: 'the cockpit read consumed' });
}

/** `paused: false` lets the page's clock flow from START (axe needs its timers). */
export async function openCockpit(browser, fx, viewport, { paused = true } = {}) {
  const p = await openPage(browser, fx.site.origin, { clock: START, paused, stampReads: true, viewport });
  await showCockpit(p.page);
  return p;
}

/** One Needs you row, by ticket. */
export const row = (page, ticket) => page.locator(`[data-part=ck-needs-you] li[data-ticket="${ticket}"]`);

/** Refreshes the cockpit and waits for the new snapshot to be shown. */
export async function refresh(page) {
  const seq = Number(await page.locator('[data-part=cockpit]').getAttribute('data-snapshot-seq'));
  await page.locator('[data-part=cockpit-refresh]').click();
  await waitFor(async () => Number(await page.locator('[data-part=cockpit]').getAttribute('data-snapshot-seq')) > seq, { what: 'the refreshed cockpit' });
  await waitFor(() => pageIdle(page), { what: 'the refresh consumed' });
}

/** The send bodies the fake received, in order. */
export const sends = (fx) => fx.api.log.filter((e) => e.kind === 'send' && e.method === 'POST').map((e) => (e.body === undefined ? null : JSON.parse(e.body)));
