// The loops proofs' site (#549): the page's static export, the scripted fake
// API for every other route, `GET /api/v1/loops` answered from a document the
// proof can change between reads, and the two switch routes
// (`POST /api/v1/loops/{id}/on|off`) recorded and answered as the proof says.
// Synthetic values only (README.md).

import { readFileSync } from 'node:fs';

import { DESKTOP, openPage, pageIdle, waitFor } from '../../support/browser.mjs';
import { fakeApi, json } from '../../support/fake-api.mjs';
import { startSite } from '../../support/serve.mjs';

/** The proofs' paused clock: 2027-01-15 09:20:00 UTC, the fixtures' read time. */
export const READ = 1_800_004_800_000;
export const START = new Date(READ);

export const load = (name) => JSON.parse(readFileSync(new URL(`./${name}.json`, import.meta.url), 'utf8'));

/** The server's saved switch event for `id` set to `on` at `at` (contracts/web-api.v1.md). */
export const saved = (id, on, at = READ + 60_000) => json(200, { loop_id: id, definition_revision: 'a'.repeat(40), repository: 'synthetic-owner/synthetic-repo', project: 'prj_syn_example', enabled: on, actor: 'synthetic-operator', at_ms: at });

/**
 * A site whose loops route answers `fx.doc` (or `fx.reply`, when set). Each
 * switch request is kept in `fx.switches` ({ path, method, headers, body })
 * and answered by `fx.answer(entry)` (default: saved), or destroyed when it
 * returns 'drop'. With `fx.holdSwitches`, answers wait for `fx.releaseSwitches()`.
 */
export async function loopsSite(doc = load('target')) {
  const api = fakeApi();
  const fx = { api, doc, reply: null, reads: 0, switches: [], answer: null, holdSwitches: false, held: [] };
  fx.releaseSwitches = () => {
    for (const go of fx.held.splice(0)) go();
  };
  const site = await startSite((req, res, url) => {
    if (url.pathname === '/api/v1/loops') {
      fx.reads++;
      const reply = fx.reply ?? json(200, fx.doc);
      res.writeHead(reply.status, reply.headers);
      res.end(reply.body);
      return;
    }
    const sw = /^\/api\/v1\/loops\/([^/]+)\/(on|off)$/.exec(url.pathname);
    if (!sw) return api.handler(req, res, url);
    let body = '';
    req.setEncoding('utf8');
    req.on('data', (c) => { body += c; });
    req.on('end', () => {
      const entry = { path: url.pathname, id: sw[1], on: sw[2] === 'on', method: req.method, headers: req.headers, body };
      fx.switches.push(entry);
      const go = () => {
        const reply = fx.answer ? fx.answer(entry) : saved(entry.id, entry.on);
        if (reply === 'drop') return res.destroy();
        res.writeHead(reply.status, reply.headers);
        res.end(reply.body);
      };
      if (fx.holdSwitches) fx.held.push(go);
      else go();
    });
  });
  fx.site = site;
  fx.close = () => site.close();
  return fx;
}

const page_ = (page) => page.locator('[data-part=loops]');

/**
 * Opens the app, goes to Loops from the desktop sidebar and waits for its
 * read to be shown, then takes `viewport`. The phone has no Loops tab (MD9);
 * its way in is the Plan screen's (#653), so a phone proof starts on the PC.
 */
export async function openLoops(browser, fx, viewport = DESKTOP) {
  const p = await openPage(browser, fx.site.origin, { clock: START, paused: true, stampReads: true, viewport: DESKTOP });
  try {
    await waitFor(() => pageIdle(p.page), { what: 'the first reads consumed' });
    await p.page.getByRole('navigation', { name: 'Views', exact: true }).getByRole('button', { name: 'Loops', exact: true }).click({ timeout: 10_000 });
    await shown(p.page);
    if (viewport !== DESKTOP) await p.page.setViewportSize(viewport);
    return p;
  } catch (e) {
    // A page left open keeps the site's connections, and the site would never close.
    await p.close();
    throw e;
  }
}

/** Waits until the loops read is shown (or refused with a notice). */
export async function shown(page) {
  await waitFor(async () => (await page_(page).getAttribute('data-snapshot-seq')) !== '0' || (await page_(page).locator('[data-notice]').count()) > 0, { what: 'the loops read' });
  await waitFor(() => pageIdle(page), { what: 'the loops read consumed' });
}

/** One loop's row, by id. */
export const row = (page, id) => page.locator(`[data-part=loops] li[data-loop="${id}"]`);
/** The ids shown in a section, in order. */
export const ids = (page, part) => page.locator(`[data-part=${part}] li[data-loop]`).evaluateAll((ls) => ls.map((l) => l.getAttribute('data-loop')));
