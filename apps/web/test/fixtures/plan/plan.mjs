// The plan page proofs' site (#653): the page's static export, the scripted
// fake API for every other route, and `GET /api/v1/plan` answered from a
// document the proof can change between reads. Synthetic values only
// (README.md): target.json is the design target's content packet.

import { readFileSync } from 'node:fs';

import { openPage, pageIdle, waitFor } from '../../support/browser.mjs';
import { fakeApi, json } from '../../support/fake-api.mjs';
import { startSite } from '../../support/serve.mjs';

/** The packet's read time, 09:00:14 UTC, and the proofs' clock five seconds later. */
export const READ = Date.UTC(2027, 0, 15, 9, 0, 14);
export const START = new Date(READ + 5_000);

export const load = (name) => JSON.parse(readFileSync(new URL(`./${name}.json`, import.meta.url), 'utf8'));
export const target = () => load('target');

/** The source snapshot `ms` older than assembly, as the server would say it. */
export function aged(doc, ms) {
  const d = structuredClone(doc);
  d.freshness = { state: ms > 70_000 ? 'stale' : 'fresh', snapshot_at: { known: d.snapshot_at - ms } };
  return d;
}

/** The plan with nothing in it: no lanes, no tickets, no chain. */
export function emptyPlan(doc = target()) {
  return { ...structuredClone(doc), lanes: [], tickets: [], critical_chain: { known: null } };
}

/** One ticket of `doc`, to change in place. */
export const ticket = (doc, n) => doc.tickets.find((t) => t.number === n);

/**
 * A site whose plan route answers `fx.doc` (or `fx.reply`, when set) on each
 * read. `fx.reads` counts them; with `fx.holding`, reads wait for `fx.releaseReads()`.
 */
export async function planSite(doc = target()) {
  const api = fakeApi();
  const fx = { api, doc, reply: null, reads: 0, holding: false, held: [] };
  fx.releaseReads = () => {
    for (const answer of fx.held.splice(0)) answer();
  };
  const site = await startSite((req, res, url) => {
    if (url.pathname !== '/api/v1/plan') return api.handler(req, res, url);
    fx.reads++;
    const answer = () => {
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

/** Shows the plan page in `page` through the shell's navigation. */
export async function showPlan(page, { wait = true } = {}) {
  await waitFor(() => pageIdle(page), { what: 'the first reads consumed' });
  await page.getByRole('navigation', { name: 'Views', exact: true }).getByRole('button', { name: 'Plan', exact: true }).click();
  if (!wait) return;
  await waitFor(async () => (await page.locator('[data-part=plan]').getAttribute('data-snapshot-seq')) !== '0' || (await page.locator('[data-part=plan] [data-notice]').count()) > 0, { what: 'the plan read' });
  await waitFor(() => pageIdle(page), { what: 'the plan read consumed' });
}

/** `paused: false` lets the page's clock flow from START (axe needs its timers). */
export async function openPlan(browser, fx, viewport, { paused = true, wait = true } = {}) {
  const p = await openPage(browser, fx.site.origin, { clock: START, paused, stampReads: true, viewport });
  await showPlan(p.page, { wait });
  return p;
}

/** One version's sheet, by lane key (`version:6`, `side_spec:2500`). */
export const sheet = (page, key) => page.locator(`[data-part=version][data-lane="${key}"]`);
/** A ticket's card in the version sheets (not the chain strip). */
export const card = (page, n) => page.locator(`[data-card-ticket="${n}"]`);
/** A ticket's card in the chain strip. */
export const link = (page, n) => page.locator(`[data-chain-ticket="${n}"]`);

/** The resolved colour of a token, through the page's CSSOM. */
export const tokenColour = (page, token) => page.evaluate((t) => {
  const i = document.createElement('i');
  i.style.color = `var(${t})`;
  document.body.append(i);
  const c = getComputedStyle(i).color;
  i.remove();
  return c;
}, token);

const REPO = 'https://github.com/example-owner/example-plan';
/** A synthetic ticket row in `lane`, with its own issue link. */
export function row(number, title, lane, { state = 'ready', column = 'waiting', blockers = [], dependents = [], spec = lane.number, labels = ['ready-for-agent'], pr = null } = {}) {
  return { number, title: { known: title }, url: { known: `${REPO}/issues/${number}` }, spec: { known: spec }, lane: { known: lane }, state: { known: state }, column: { known: column }, labels: { known: labels }, yours: { known: labels.includes('ready-for-human') }, blockers: { known: blockers }, dependents: { known: dependents }, pr: { known: pr } };
}

/**
 * An otherwise finished plan (the target, every ticket merged) plus side spec
 * #2700 holding the waiting tickets `waits` names, each with its prerequisites:
 * `[[2701, []], [2702, [2701]]]`. Dependents are their exact inverse. The chain
 * is left for the proof to name.
 */
export function withGraph(waits, doc = finished()) {
  const d = structuredClone(doc);
  const lane = { kind: 'side_spec', number: 2700 };
  d.lanes.push({ ...lane, title: { known: 'Synthetic graph' } });
  for (const [n, blockers] of waits) {
    const dependents = waits.filter(([, bs]) => bs.includes(n)).map(([k]) => k);
    d.tickets.push(row(n, `Graph ticket ${n}`, lane, { state: blockers.length === 0 ? 'ready' : 'blocked', blockers, dependents }));
  }
  return d;
}

/** A straight line of `n` waiting tickets from #2701, alone in a finished plan, named as its chain: one link, or a long chain. */
export function withLine(n) {
  const numbers = Array.from({ length: n }, (_, i) => 2701 + i);
  const d = withGraph(numbers.map((k, i) => [k, i === 0 ? [] : [k - 1]]));
  d.critical_chain = { known: { root: 2701, blocked_count: n - 1, path: numbers } };
  return d;
}

/** Every ticket merged and done: an entirely finished plan, whose chain is known null. */
export function finished(doc = target()) {
  const d = structuredClone(doc);
  for (const t of d.tickets) {
    t.state = { known: 'merged' };
    t.column = { known: 'done' };
    t.labels = { known: ['ready-for-agent'] };
    t.yours = { known: false };
    t.pr = { known: { number: t.number + 1000, url: `${REPO}/pull/${t.number + 1000}` } };
  }
  d.critical_chain = { known: null };
  return d;
}
