// The decision cards' proofs' site (#656): the page's static export, the
// scripted fake API for every other route (the send, its preview and
// lookup), and `GET /api/v1/decisions` answered from a document the proof can
// change between reads. Synthetic values only (README.md).

import { readFileSync } from 'node:fs';

import { openPage, pageIdle, waitFor } from '../../support/browser.mjs';
import { fakeApi, json } from '../../support/fake-api.mjs';
import { startSite } from '../../support/serve.mjs';

/** The fixtures' assembly time, and the proofs' paused clock. */
export const T = 1_800_000_000_000;
export const START = new Date(T);
/** The fixtures' verified orchestrator target. */
export const TARGET = 'thr_syn_7c2e9a';

export const load = (name) => JSON.parse(readFileSync(new URL(`./${name}.json`, import.meta.url), 'utf8'));

/** Every known source snapshot `ms` older than assembly: stale past the contract's 70 s, as the server would say. */
export function aged(doc, ms) {
  const d = structuredClone(doc);
  for (const f of [d.freshness, d.orchestrator.freshness]) {
    if (f.state === 'unknown') continue;
    f.snapshot_at.known = d.snapshot_at - ms;
    f.state = ms > 70_000 ? 'stale' : 'fresh';
  }
  return d;
}

/**
 * A site whose decisions route answers `fx.doc` (or `fx.reply`, when set) on
 * each read. `fx.reads` counts them.
 */
export async function decisionsSite(doc = load('target')) {
  const api = fakeApi();
  const fx = { api, doc, reply: null, reads: 0 };
  const site = await startSite((req, res, url) => {
    if (url.pathname !== '/api/v1/decisions') return api.handler(req, res, url);
    fx.reads++;
    const reply = fx.reply ?? json(200, fx.doc);
    res.writeHead(reply.status, reply.headers);
    res.end(reply.body);
  });
  fx.site = site;
  fx.close = () => site.close();
  return fx;
}

/** Shows Decisions in `page` and waits until its read is consumed. */
export async function showDecisions(page) {
  await waitFor(() => pageIdle(page), { what: 'the first reads consumed' });
  await page.getByRole('navigation', { name: 'Views', exact: true }).getByRole('button', { name: /^Decisions/ }).click();
  await waitFor(async () => (await page.locator('[data-part=decisions]').getAttribute('data-snapshot-seq')) !== '0' || (await page.locator('[data-part=decisions] [data-notice]').count()) > 0, { what: 'the decisions read' });
  await waitFor(() => pageIdle(page), { what: 'the decisions read consumed' });
}

/** `paused: false` lets the page's clock flow from START. */
export async function openDecisions(browser, fx, viewport, { paused = true } = {}) {
  const p = await openPage(browser, fx.site.origin, { clock: START, paused, stampReads: true, viewport });
  await showDecisions(p.page);
  return p;
}

/** One card, by its comment id. */
export const card = (page, comment) => page.locator(`[data-part=decisions] [data-comment="${comment}"]`);
/** One answer slot: a grill question by id, or a confirmation card's one action. */
export const slot = (page, comment, question = null) => card(page, comment).locator(question === null ? '[data-part=slot]' : `[data-part=slot][data-question="${question}"]`);

/** Refreshes Decisions and waits for the new snapshot to be shown. */
export async function refresh(page) {
  const seq = Number(await page.locator('[data-part=decisions]').getAttribute('data-snapshot-seq'));
  await page.locator('[data-part=decisions-refresh]').click();
  await waitFor(async () => Number(await page.locator('[data-part=decisions]').getAttribute('data-snapshot-seq')) > seq, { what: 'the refreshed decisions' });
  await waitFor(() => pageIdle(page), { what: 'the refresh consumed' });
}

/** The send bodies the fake received, in order. */
export const sends = (fx) => fx.api.log.filter((e) => e.kind === 'send' && e.method === 'POST').map((e) => (e.body === undefined ? null : JSON.parse(e.body)));
