// #2292: the feedback handoff and the OpenWiz share on Home, in Chromium, at
// phone and desktop widths (contracts/feedback.v1.md, "Two entry routes" and
// "Sharing"). A recording clipboard and every request the page makes:
// - the handoff is previewed exactly and copied once, only on Copy, with only
//   the chosen words; planted private-looking page state never enters it;
// - Cancel, an edit after the preview, a repeat and a refused share write
//   nothing; a refused clipboard says not copied;
// - nothing the feedback or share does makes a request: no POST, and no
//   request leaves the page's own origin;
// - copied, sent and acknowledged are shown as separate steps; the page never
//   says sent or shared.
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { DESKTOP, PHONE, launchBrowser, openPage, pageIdle, waitFor } from '../support/browser.mjs';
import { fakeApi, json } from '../support/fake-api.mjs';
import { fleetsExample } from '../support/fleet-fixtures.ts';
import { axe } from '../support/harness.mjs';
import { startSite } from '../support/serve.mjs';
import { inventory, session, sessionView, T0 } from '../support/synthetic.ts';

let browser;
before(async () => { browser = await launchBrowser(); });
after(async () => { await browser?.close(); });

const TOKEN = 'synthetic-token-000000';
const SECRET = '/home/synthetic-user/secret-project';
const TITLE = 'Plan page hides the approve button on a narrow phone';
const BODY = 'On a 360-pixel screen the approve button sits under the footer.';
const HANDOFF = [
  'Please send this as public feedback about OpenWiz with the OpenWiz feedback skill (openwiz:feedback).',
  'It becomes one public issue on openwizdev/openwiz, under my own GitHub login.',
  'Show me the exact preview first, and create nothing until I say yes.',
  '',
  `Title: ${TITLE}`,
  '',
  'Body:',
  BODY,
].join('\n');
const SHARE = 'Have a look at OpenWiz.\n\nhttps://github.com/openwizdev/openwiz';

async function fixture() {
  // Planted private-looking state the page holds: a session title and purpose.
  const rows = [session(1, { title: { known: `Fix ${TOKEN} leak` }, recap: { known: { kind: 'purpose_as_reported', text: `Work in ${SECRET}.`, truncated: false } } })];
  const api = fakeApi();
  api.setList(() => json(200, inventory(rows)));
  api.setDetail(() => json(200, sessionView(rows[0])));
  const site = await startSite((req, res, url) => {
    if (!url.pathname.startsWith('/api/v1/fleets')) return api.handler(req, res, url);
    const reply = json(200, JSON.parse(fleetsExample()));
    res.writeHead(reply.status, reply.headers); res.end(reply.body);
  });
  return site;
}

/** Replaces the clipboard with a recorder; `refuse` makes every write fail. Before Home mounts the copier. */
const recordClipboard = (page, refuse = false) => page.evaluate((refuse) => {
  window.__writes = [];
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (t) => { window.__writes.push(t); if (refuse) throw new Error('denied'); } } });
}, refuse);
const writes = (page) => page.evaluate(() => window.__writes);
const part = (page, name) => page.locator(`[data-part="${name}"]`);

async function goHome(page) {
  const tab = page.getByRole('navigation', { name: 'Views', exact: true }).getByRole('button', { name: 'Home', exact: true });
  if (await tab.isVisible()) await tab.click();
  else {
    await page.getByRole('button', { name: /^Search or jump to…/ }).filter({ visible: true }).first().click();
    await page.getByRole('combobox', { name: 'Search navigation' }).fill('Go to Home');
    await page.keyboard.press('Enter');
  }
  await waitFor(() => part(page, 'feedback').count(), { what: 'the feedback section on Home' });
  await waitFor(() => pageIdle(page), { what: 'all response bodies consumed' });
  // Closed, Home holds one button: no field, no heading of its own (Home's existing proof).
  assert.equal(await page.locator('main textarea, main input').count(), 0);
  assert.equal(await part(page, 'feedback').locator('h2').count(), 0);
  await part(page, 'feedback-open').click();
}

async function open(viewport, refuse = false) {
  const site = await fixture();
  const p = await openPage(browser, site.origin, { viewport, clock: T0 + 30_000, stampReads: true });
  await waitFor(() => p.page.locator('main [data-session-id]').count(), { what: 'the planted session listed' });
  await recordClipboard(p.page, refuse);
  await goHome(p.page);
  return { ...p, site, origin: site.origin, close: async () => { await p.page.context().close(); await site.close(); } };
}

for (const viewport of [DESKTOP, PHONE]) {
  test(`the handoff is previewed exactly and copied once, only on Copy, at ${viewport.width}px`, async () => {
    const p = await open(viewport);
    const { page } = p;
    try {
      const from = p.requests.length;
      assert.equal(await part(page, 'handoff-preview').count(), 0);
      await part(page, 'handoff-show').click({ force: true }); // pressed while refused
      assert.equal(await part(page, 'handoff-preview').count(), 0, 'empty feedback is not previewed');
      assert.equal(await part(page, 'handoff-result').textContent(), 'Write a one-line title.');
      await part(page, 'handoff-title').fill(TITLE);
      await part(page, 'handoff-body').fill(BODY);
      await part(page, 'handoff-show').click();
      assert.equal(await part(page, 'handoff-preview').textContent(), HANDOFF);
      assert.deepEqual(await writes(page), [], 'a preview writes nothing');
      await part(page, 'handoff-cancel').click();
      assert.equal(await part(page, 'handoff-preview').count(), 0);
      assert.deepEqual(await writes(page), [], 'Cancel writes nothing');
      await part(page, 'handoff-show').click();
      await part(page, 'handoff-body').fill(`${BODY} Also on tablets.`);
      assert.equal(await part(page, 'handoff-preview').count(), 0, 'an edit drops the preview');
      await part(page, 'handoff-body').fill(BODY);
      await part(page, 'feedback-close').click();
      assert.equal(await page.locator('main textarea').count(), 0, 'closed again');
      await part(page, 'feedback-open').click();
      assert.equal(await part(page, 'handoff-body').inputValue(), BODY, 'the words are kept while closed');
      await part(page, 'handoff-show').click();
      await part(page, 'handoff-copy').click();
      await waitFor(async () => (await part(page, 'handoff-result').getAttribute('data-phase')) === 'copied', { what: 'copied' });
      await part(page, 'handoff-copy').click({ force: true }); // a repeat press
      assert.deepEqual(await writes(page), [HANDOFF], 'exactly one write, of the previewed bytes');
      assert.equal(await part(page, 'handoff-result').textContent(), 'Handoff copied. Nothing has been sent: paste it to your own agent.');
      for (const w of await writes(page)) { assert.ok(!w.includes(TOKEN) && !w.includes(SECRET) && !w.includes('thr_web_')); }
      const stages = await part(page, 'feedback-stages').locator('li strong').allTextContents();
      assert.deepEqual(stages, ['Copied', 'Sent', 'Acknowledged']);
      const made = p.requests.slice(from);
      assert.deepEqual(made.filter((r) => r.method !== 'GET' || new URL(r.url).origin !== p.origin), [], 'no write and no request off the page\'s origin');
      assert.deepEqual(made.filter((r) => !new URL(r.url).pathname.startsWith('/api/v1/fleets') && !new URL(r.url).pathname.startsWith('/api/v1/inventory')), [], 'only the page\'s existing reads');
      assert.deepEqual(await axe(page), []);
      assert.deepEqual(p.errors, []);
    } finally { await p.close(); }
  });

  test(`a share copies exactly the previewed text and the one link, at ${viewport.width}px`, async () => {
    const p = await open(viewport);
    const { page } = p;
    try {
      const from = p.requests.length;
      await part(page, 'share-show').click();
      assert.equal(await part(page, 'share-preview').textContent(), SHARE);
      await part(page, 'share-cancel').click();
      assert.deepEqual(await writes(page), [], 'a cancelled share writes nothing');
      await part(page, 'share-text').fill(`See http://localhost:7370 ${TOKEN}`);
      await part(page, 'share-show').click({ force: true }); // pressed while refused
      assert.equal(await part(page, 'share-preview').count(), 0, 'a link in the text is refused');
      assert.match(await part(page, 'share-result').textContent(), /Leave out links and addresses/);
      await part(page, 'share-text').fill('Have a look at OpenWiz.');
      await part(page, 'share-show').click();
      await part(page, 'share-copy').click();
      await waitFor(async () => (await part(page, 'share-result').getAttribute('data-phase')) === 'copied', { what: 'copied' });
      assert.deepEqual(await writes(page), [SHARE]);
      assert.equal(await part(page, 'share-result').textContent(), 'Copied. Nothing was shared or sent.');
      assert.deepEqual(p.requests.slice(from).filter((r) => r.method !== 'GET' || new URL(r.url).origin !== p.origin), []);
    } finally { await p.close(); }
  });
}

test('a refused clipboard is reported as not copied', async () => {
  const p = await open(DESKTOP, true);
  const { page } = p;
  try {
    await part(page, 'share-show').click();
    await part(page, 'share-copy').click();
    await waitFor(async () => (await part(page, 'share-result').getAttribute('data-phase')) === 'not_copied', { what: 'not copied' });
    assert.equal(await part(page, 'share-result').textContent(), 'Not copied: the browser refused the clipboard. Nothing was sent.');
    assert.deepEqual(await writes(page), [SHARE], 'the one attempt, refused');
  } finally { await p.close(); }
});
