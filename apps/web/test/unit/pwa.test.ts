// #1029 (spec #1022's D4, fixture portion): the app is installable. Over the
// static export (`out/`, as `npm run build` makes it) served the way
// openwiz-server serves it (test/support/serve.mjs, with the page's CSP) and
// the fake API, in Chromium:
//
// - P1: the manifest at `/manifest.webmanifest` names the app, starts and is
//   scoped at `/`, opens standalone, and every icon it names is a bundled PNG
//   of the size it claims (192 and 512, and a maskable 512);
// - P2: every exported page links the manifest, the touch icon and the one
//   registration script, `/sw-register.js`, from this origin;
// - P3: Chromium finds the page installable (no installability errors, the
//   manifest parsed without errors, no CSP violation), and the worker
//   `/sw.js` controls `/`;
// - P4: the worker's cache holds only the static shell: never an API answer;
// - P5: offline, the shell still opens but no API answer comes from the
//   worker; a write made offline fails and is never queued, retried or
//   replayed once the page is back online; online, a write passes the worker
//   untouched, exactly once;
// - P6: the worker listens only for install, activate, fetch and, for #2035,
//   push and notificationclick (no sync, message or background fetch), and the
//   registration script touches nothing but the worker;
// - P7 (#1301 R1): when storing a shell file fails (storage full or
//   unavailable), the worker still serves the answer the network gave, never
//   an older cached copy and never a failure;
// - P8 (#1301 R3): when reading the cache fails, the worker treats it as a
//   miss and serves the shell file from the network, fetched once;
// - P9 (#2035, PA4): a push shows one generic notification only for the exact
//   minimal payload; any other payload is ignored, with no fetch, cache or
//   storage use;
// - P10 (#2035, PA4): a tap only navigates to this origin's
//   `/#notification=<token>`; a malformed tap opens nothing and nothing is
//   fetched, answered or replayed.
//
// Every await of this file comes before its first test, or inside one.

import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runInNewContext } from 'node:vm';
import { after, before, test } from 'node:test';

import { chromium } from 'playwright-core';
import type { Browser, BrowserContext, Page } from 'playwright-core';

const WEB = join(import.meta.dirname, '..', '..');
const OUT = join(WEB, 'out');
const PUBLIC = join(WEB, 'public');
const CHROMIUM = process.env['OPENWIZ_CHROMIUM'] ?? '/usr/bin/chromium';

type LogEntry = { method: string; path: string; search: string };
type Site = { origin: string; log: LogEntry[]; close: () => Promise<void> };
type Harness = { fakeSite: () => Promise<{ site: Site; close: () => Promise<void> }> };

/** The static shell's paths: the only ones the worker may cache. */
const SHELL = (path: string) =>
  path === '/' ||
  path === '/setup' ||
  path === '/manifest.webmanifest' ||
  /^\/(_next\/static|fonts|icons)\/[A-Za-z0-9._/-]+$/.test(path);

const readOut = (rel: string) => readFileSync(join(OUT, rel));

/** A PNG's width and height, from its IHDR. */
function pngSize(bytes: Buffer): { width: number; height: number } {
  assert.equal(bytes.readUInt32BE(0), 0x89504e47, 'a PNG signature');
  assert.equal(bytes.toString('latin1', 12, 16), 'IHDR', 'IHDR first');
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

type Icon = { src: string; sizes: string; type: string; purpose?: string };
type Manifest = Record<string, unknown> & { icons: Icon[] };

// ── P1, P2: the exported files ──

test('P1: the manifest at the exact path names the app, opens standalone at /, and its icons are bundled PNGs of their sizes', () => {
  assert.ok(existsSync(join(OUT, 'index.html')), 'needs out/: run `npm run build` first');
  assert.ok(existsSync(join(PUBLIC, 'manifest.webmanifest')), 'apps/web/public/manifest.webmanifest exists');
  const manifest = JSON.parse(readOut('manifest.webmanifest').toString('utf8')) as Manifest;
  assert.equal(manifest['name'], 'OpenWiz');
  assert.equal(manifest['short_name'], 'OpenWiz');
  assert.equal(manifest['id'], '/');
  assert.equal(manifest['start_url'], '/');
  assert.equal(manifest['scope'], '/');
  assert.equal(manifest['display'], 'standalone');
  // The canvas token (styles/tokens.css, --ow-color-canvas): the launch splash matches the app.
  assert.equal(manifest['background_color'], '#0e0f11');
  assert.equal(manifest['theme_color'], '#0e0f11');
  const want = [
    { sizes: '192x192', purpose: 'any' },
    { sizes: '512x512', purpose: 'any' },
    { sizes: '512x512', purpose: 'maskable' },
  ];
  assert.deepEqual(
    manifest.icons.map((i) => ({ sizes: i.sizes, purpose: i.purpose ?? 'any' })),
    want,
  );
  for (const icon of manifest.icons) {
    assert.equal(icon.type, 'image/png', icon.src);
    assert.match(icon.src, /^\/icons\/[a-z0-9-]+\.png$/, `${icon.src}: a same-origin path under /icons/`);
    const { width, height } = pngSize(readOut(icon.src.slice(1)));
    assert.equal(`${width}x${height}`, icon.sizes, `${icon.src}: its real size`);
  }
  // Every bundled icon is one the shell names (the manifest or the touch icon): nothing stray.
  const named = new Set([...manifest.icons.map((i) => i.src), '/icons/apple-touch-icon.png']);
  for (const file of readdirSync(join(OUT, 'icons'))) assert.ok(named.has(`/icons/${file}`), `out/icons/${file} is named`);
  assert.deepEqual(pngSize(readOut('icons/apple-touch-icon.png')), { width: 180, height: 180 });
});

test('P2: every exported page links the manifest, the touch icon and the one registration script, from this origin', () => {
  for (const page of ['index.html', 'setup.html', '404.html']) {
    const html = readOut(page).toString('utf8');
    assert.match(html, /<link rel="manifest" href="\/manifest\.webmanifest"\/?>/, `${page}: the manifest link`);
    assert.match(html, /<link rel="apple-touch-icon" href="\/icons\/apple-touch-icon\.png"\/?>/, `${page}: the touch icon`);
    assert.match(html, /<meta name="theme-color" content="#0e0f11"\/?>/, `${page}: the theme colour`);
    const scripts = [...html.matchAll(/<script\b[^>]*\bsrc="([^"]+)"/g)].map((m) => m[1]);
    assert.equal(scripts.filter((s) => s === '/sw-register.js').length, 1, `${page}: one registration script`);
  }
});

// ── P3 to P5: in Chromium ──

let browser: Browser | null = null;
let harness: Harness | null = null;
before(async () => {
  browser = await chromium.launch({ executablePath: CHROMIUM });
  // A dynamic import: the support files are plain JavaScript, outside tsc's program.
  const spec: string = '../support/harness.mjs';
  harness = (await import(spec)) as Harness;
});
after(async () => {
  await browser?.close();
});

/**
 * A fresh site and a context that allows service workers (the other proofs
 * block them). `persistent`: a real profile in its own temporary directory,
 * as an installed app has (Chromium never offers to install from a private,
 * incognito context, which every other context is).
 */
async function open(persistent = false): Promise<{ site: Site; close: () => Promise<void>; context: BrowserContext; page: Page; violations: string[] }> {
  assert.ok(browser && harness, 'Chromium and the harness are ready');
  const fake = await harness.fakeSite();
  const site = fake.site;
  const options = { serviceWorkers: 'allow', viewport: { width: 390, height: 844 } } as const;
  let context: BrowserContext;
  let close = fake.close;
  if (persistent) {
    const profile = mkdtempSync(join(tmpdir(), 'openwiz-pwa-'));
    context = await chromium.launchPersistentContext(profile, { ...options, executablePath: CHROMIUM });
    close = async () => {
      await fake.close();
      rmSync(profile, { recursive: true, force: true });
    };
  } else {
    context = await browser.newContext(options);
  }
  const page = context.pages()[0] ?? (await context.newPage());
  const violations: string[] = [];
  page.on('console', (m) => {
    if (/Content Security Policy|Refused to/i.test(m.text())) violations.push(m.text());
  });
  await page.goto(`${site.origin}/`);
  return { site, close, context, page, violations };
}

/** Waits until the worker is active and controls this page. */
async function controlled(page: Page): Promise<{ scope: string; script: string }> {
  // Bounded, so a page with no worker fails here instead of waiting forever.
  const ready = await page.evaluate(async () => {
    const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), 10_000));
    const reg = await Promise.race([navigator.serviceWorker.ready, timeout]);
    return reg ? { scope: reg.scope, script: reg.active?.scriptURL ?? '' } : null;
  });
  assert.ok(ready, 'a service worker is active for the page within 10 s');
  if (!(await page.evaluate(() => navigator.serviceWorker.controller !== null))) await page.reload();
  assert.ok(await page.evaluate(() => navigator.serviceWorker.controller !== null), 'the worker controls the page');
  return ready;
}

/** Every URL path in the worker's caches. */
function cachedPaths(page: Page): Promise<string[]> {
  return page.evaluate(async () => {
    const paths: string[] = [];
    for (const name of await caches.keys()) {
      for (const req of await (await caches.open(name)).keys()) paths.push(new URL(req.url).pathname);
    }
    return paths.sort();
  });
}

test('P3: Chromium finds the app installable, with no CSP violation, and /sw.js controls /', { timeout: 60_000 }, async () => {
  const s = await open(true);
  try {
    const { scope, script } = await controlled(s.page);
    assert.equal(scope, `${s.site.origin}/`);
    assert.equal(script, `${s.site.origin}/sw.js`);
    const cdp = await s.context.newCDPSession(s.page);
    const manifest = (await cdp.send('Page.getAppManifest')) as { url: string; errors: unknown[] };
    assert.equal(manifest.url, `${s.site.origin}/manifest.webmanifest`);
    assert.deepEqual(manifest.errors, []);
    const { installabilityErrors } = (await cdp.send('Page.getInstallabilityErrors')) as { installabilityErrors: unknown[] };
    assert.deepEqual(installabilityErrors, []);
    assert.deepEqual(s.violations, []);
  } finally {
    await s.context.close();
    await s.close();
  }
});

test('P4: after the page has read the API, the cache holds only the static shell', { timeout: 60_000 }, async () => {
  const s = await open();
  try {
    await controlled(s.page);
    // The app's own reads, and one more, all through the worker that now controls the page.
    const before = s.site.log.length;
    await s.page.reload();
    await s.page.waitForSelector('.conn:not([data-connection="reading"])', { timeout: 20_000 });
    assert.equal(await s.page.evaluate(() => fetch('/api/v1/inventory').then((r) => r.status)), 200);
    assert.ok(s.site.log.slice(before).filter((e) => e.path.startsWith('/api/')).length >= 2, 'the controlled page read the API');
    const paths = await cachedPaths(s.page);
    assert.ok(paths.includes('/'), `the page is cached: ${paths.join(', ')}`);
    // Installed from the page's own HTML, before the worker controlled anything.
    const named = [...readOut('index.html').toString('utf8').matchAll(/(?:src|href)="(\/_next\/static\/[^"]+)"/g)].map((m) => m[1]);
    assert.ok(named.length > 3, 'the page names its scripts and styles');
    for (const asset of named) assert.ok(paths.includes(asset ?? ''), `${asset} is cached`);
    assert.deepEqual(paths.filter((p) => !SHELL(p)), [], 'nothing outside the shell is cached');
  } finally {
    await s.context.close();
    await s.close();
  }
});

test('P5: offline the shell opens, no API answer comes from the worker, and no write is queued, retried or replayed', { timeout: 60_000 }, async () => {
  const s = await open();
  try {
    await controlled(s.page);
    const fromWorker: string[] = [];
    s.page.on('response', (r) => {
      if (new URL(r.url()).pathname.startsWith('/api/') && r.fromServiceWorker()) fromWorker.push(r.url());
    });
    // Online: a write passes the worker untouched and reaches the server exactly once.
    const posts = () => s.site.log.filter((e) => e.method !== 'GET' && e.method !== 'HEAD');
    const status = await s.page.evaluate(() => fetch('/api/v1/sessions/thr_syn_pwa_online/messages', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then((r) => r.status));
    assert.ok(status >= 400, `the fake refuses the empty body: ${status}`);
    assert.equal(posts().length, 1, 'one write, once');

    await s.context.setOffline(true);
    await s.page.reload();
    assert.equal(await s.page.title(), 'OpenWiz', 'the shell opens offline');
    // The app itself runs offline, and says it can't reach the server.
    await s.page.waitForSelector('.conn[data-connection="disconnected"]', { timeout: 20_000 });
    const offline = await s.page.evaluate(() =>
      fetch('/api/v1/sessions/thr_syn_pwa_offline/messages', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(
        (r) => `answered ${r.status}`,
        () => 'failed',
      ),
    );
    assert.equal(offline, 'failed', 'a write made offline fails at once');
    const read = await s.page.evaluate(() => fetch('/api/v1/inventory').then((r) => `answered ${r.status}`, () => 'failed'));
    assert.equal(read, 'failed', 'a read made offline is never answered from a cache');

    // Back online: a later request reaches the server, and the offline write never does, before or with it.
    await s.context.setOffline(false);
    assert.equal(await s.page.evaluate(() => fetch('/api/v1/inventory?sentinel=1').then((r) => r.status)), 200);
    assert.equal(s.site.log.filter((e) => e.path === '/api/v1/inventory' && e.search === '?sentinel=1').length, 1, 'the later request arrived');
    assert.deepEqual(posts().map((e) => e.path), ['/api/v1/sessions/thr_syn_pwa_online/messages'], 'the offline write never reaches the server');
    assert.deepEqual(fromWorker, [], 'no API answer came from the worker');
  } finally {
    await s.context.close();
    await s.close();
  }
});

// ── P6: the worker's and the registration's source ──

test('P6: the worker listens only for install, activate, fetch, push and notificationclick, and the registration only registers /sw.js', () => {
  const worker = readOut('sw.js').toString('utf8');
  const events = [...worker.matchAll(/addEventListener\(\s*'([a-z]+)'/g)].map((m) => m[1]).sort();
  assert.deepEqual(events, ['activate', 'fetch', 'install', 'notificationclick', 'push']);
  // #2035: the notification events only show and open; P9 and P10 prove what they do.
  for (const banned of [/\bonsync\b|'sync'|periodicsync|backgroundfetch/i, /pushsubscriptionchange|pushManager|subscribe\(/i, /postMessage|'message'|BroadcastChannel/, /indexedDB|localStorage|importScripts/]) {
    assert.doesNotMatch(worker, banned);
  }
  const register = readOut('sw-register.js').toString('utf8');
  assert.match(register, /navigator\.serviceWorker\.register\('\/sw\.js', \{ scope: '\/' \}\)/);
  assert.doesNotMatch(register, /fetch\(|caches|Storage|indexedDB|postMessage/);
});

// ── P7: a failed cache write never costs the page the network's answer ──

/** A fake response, as the Cache API and fetch hand them over. */
type FakeResponse = { ok: boolean; status: number; redirected: boolean; type: string; body: string; clone: () => FakeResponse };
const response = (body: string): FakeResponse => {
  const r: FakeResponse = { ok: true, status: 200, redirected: false, type: 'basic', body, clone: () => r };
  return r;
};

/**
 * Runs the exported worker in a fresh context whose fetch answers `fresh`,
 * whose cache holds `cached` (by path) and whose cache writes all fail, as
 * with full or unavailable storage; with `readFails`, its cache reads fail
 * too. Returns what the worker answers for `path`, and how many fetches it made.
 */
async function withFailingCache(path: string, cached: Record<string, FakeResponse>, readFails = false): Promise<{ body: string; fetches: number }> {
  const ORIGIN = 'https://openwiz.example.invalid';
  const listeners = new Map<string, (event: unknown) => void>();
  const full = () => Promise.reject(new Error('QuotaExceededError (synthetic)'));
  let fetches = 0;
  const context = {
    URL,
    self: { location: { origin: ORIGIN }, addEventListener: (type: string, fn: (event: unknown) => void) => listeners.set(type, fn) },
    fetch: async () => {
      fetches++;
      return response(`fresh ${path}`);
    },
    caches: {
      open: full,
      match: async (req: { url: string }) => {
        if (readFails) throw new Error('UnknownError: storage (synthetic)');
        return cached[new URL(req.url).pathname];
      },
      keys: async () => [],
      delete: async () => true,
    },
  };
  runInNewContext(readOut('sw.js').toString('utf8'), context);
  const onFetch = listeners.get('fetch');
  assert.ok(onFetch, 'the worker listens for fetch');
  const handled: { answer?: Promise<FakeResponse> } = {};
  onFetch({ request: { method: 'GET', url: `${ORIGIN}${path}` }, respondWith: (p: Promise<FakeResponse>) => { handled.answer = p; } });
  assert.ok(handled.answer, `the worker handles ${path}`);
  const body = await handled.answer.then((r) => r.body, (e: Error) => `failed: ${e.message}`);
  return { body, fetches };
}

const answerWithFailingCache = async (path: string, cached: Record<string, FakeResponse>) => (await withFailingCache(path, cached)).body;

test('P7: when the cache write fails, the worker still serves the network\'s answer', async () => {
  // A page with an older copy cached gets the fresh page, not the stale one;
  // an asset or icon not cached yet gets the file, not a failure.
  const got = [
    await answerWithFailingCache('/', { '/': response('stale /') }),
    await answerWithFailingCache('/_next/static/chunks/app-synthetic.js', {}),
    await answerWithFailingCache('/icons/icon-192.png', {}),
  ];
  assert.deepEqual(got, ['fresh /', 'fresh /_next/static/chunks/app-synthetic.js', 'fresh /icons/icon-192.png']);
});

// ── P8: a failed cache read is a miss, never a failed load ──

test('P8: when reading the cache fails, the worker fetches the shell file once and serves it', async () => {
  const got = [
    await withFailingCache('/_next/static/chunks/app-synthetic.js', {}, true),
    await withFailingCache('/fonts/Geist-var.woff2', {}, true),
    await withFailingCache('/icons/icon-192.png', {}, true),
  ];
  assert.deepEqual(got, [
    { body: 'fresh /_next/static/chunks/app-synthetic.js', fetches: 1 },
    { body: 'fresh /fonts/Geist-var.woff2', fetches: 1 },
    { body: 'fresh /icons/icon-192.png', fetches: 1 },
  ]);
});

// ── P9, P10: notification receipt and tap (#2035) ──

const ORIGIN = 'https://openwiz.example.invalid';
const TOKEN = 'a'.repeat(63) + '1';
const exact = (token: string) => `{"title":"OpenWiz needs your attention","target_token":"${token}"}`;
type Effects = { shown: { title: string; options: Record<string, unknown> }[]; opened: string[]; navigated: string[]; focused: number; fetches: number; cache: number };

/** Runs public/sw.js with fakes that record every effect a notification event could have. */
function worker(windows: { url: string }[] = []): { fire: (type: string, event: Record<string, unknown>) => Promise<void>; effects: Effects } {
  const listeners = new Map<string, (event: unknown) => void>();
  const effects: Effects = { shown: [], opened: [], navigated: [], focused: 0, fetches: 0, cache: 0 };
  const touched = () => { effects.cache++; return Promise.reject(new Error('cache untouched by notifications')); };
  const clients = windows.map((w) => ({ ...w, focus: async () => { effects.focused++; return clients[0]; }, navigate: async (url: string) => { effects.navigated.push(url); return clients[0]; } }));
  const context = {
    URL,
    self: {
      location: { origin: ORIGIN },
      addEventListener: (type: string, fn: (event: unknown) => void) => listeners.set(type, fn),
      registration: { showNotification: async (title: string, options: Record<string, unknown>) => { effects.shown.push({ title, options }); } },
      clients: { matchAll: async () => clients, openWindow: async (url: string) => { effects.opened.push(url); return null; }, claim: async () => {} },
    },
    fetch: async () => { effects.fetches++; throw new Error('no fetch from a notification event'); },
    caches: { open: touched, match: touched, keys: touched, delete: touched },
  };
  runInNewContext(readFileSync(join(PUBLIC, 'sw.js'), 'utf8'), context);
  return {
    effects,
    fire: async (type, event) => {
      const fn = listeners.get(type);
      assert.ok(fn, `the worker listens for ${type}`);
      const waits: Promise<unknown>[] = [];
      fn({ ...event, waitUntil: (p: Promise<unknown>) => { waits.push(p); } });
      await Promise.all(waits);
    },
  };
}
const push = (text: string | null) => ({ data: text === null ? null : { text: () => text } });
const tap = (data: unknown) => {
  let closed = 0;
  return { event: { notification: { data, close: () => { closed++; } } }, closed: () => closed };
};

test('P9: a push shows one generic notification only for the exact minimal payload, and ignores every other payload', async () => {
  const w = worker();
  await w.fire('push', push(exact(TOKEN)));
  assert.deepEqual(w.effects.shown.map((s) => s.title), ['OpenWiz needs your attention']);
  const options = w.effects.shown[0]?.options ?? {};
  assert.deepEqual(JSON.parse(JSON.stringify(options['data'])), { token: TOKEN }, 'only the opaque token is kept, for the tap');
  assert.equal(options['body'], undefined, 'no wording beyond the generic title');
  const refused = [
    null, '', 'not json', exact(TOKEN.toUpperCase()), exact(TOKEN.slice(1)), exact(`${TOKEN}0`),
    `{"target_token":"${TOKEN}","title":"OpenWiz needs your attention"}`,
    `{"title":"Approve release now","target_token":"${TOKEN}"}`,
    `{"title":"OpenWiz needs your attention","target_token":"${TOKEN}","url":"https://evil.example/"}`,
    `{"title":"OpenWiz needs your attention","target_token":"${TOKEN}","target_token":"${'b'.repeat(64)}"}`,
    ` ${exact(TOKEN)}`, `[${exact(TOKEN)}]`,
  ];
  for (const text of refused) await w.fire('push', push(text));
  assert.equal(w.effects.shown.length, 1, 'malformed or untrusted payloads show nothing');
  assert.deepEqual([w.effects.fetches, w.effects.cache, w.effects.opened.length, w.effects.navigated.length], [0, 0, 0, 0], 'receipt fetches, caches, opens and answers nothing');
});

test('P10: a tap opens only this origin\'s /#notification=<token>, and a malformed tap opens nothing', async () => {
  const want = `${ORIGIN}/#notification=${TOKEN}`;
  // No open window: one new window at the bound fragment.
  const fresh = worker();
  const t1 = tap({ token: TOKEN });
  await fresh.fire('notificationclick', t1.event);
  assert.deepEqual([fresh.effects.opened, fresh.effects.navigated, t1.closed()], [[want], [], 1]);
  // An open app window on this origin is focused and navigated; another origin's window never is.
  const open = worker([{ url: 'https://other.example.invalid/' }, { url: `${ORIGIN}/` }]);
  await open.fire('notificationclick', tap({ token: TOKEN }).event);
  assert.deepEqual([open.effects.navigated, open.effects.focused, open.effects.opened], [[want], 1, []]);
  // Untrusted tap data: a URL, path, origin or wrong token opens nothing.
  const bad = worker([{ url: `${ORIGIN}/` }]);
  for (const data of [null, {}, { token: TOKEN.toUpperCase() }, { token: `${TOKEN}/../x` }, { token: TOKEN, url: 'https://evil.example/' }, { url: 'https://evil.example/' }, 'https://evil.example/', { token: 7 }]) {
    const t = tap(data);
    await bad.fire('notificationclick', t.event);
    assert.equal(t.closed(), 1, 'the notification is closed');
  }
  assert.deepEqual([bad.effects.opened, bad.effects.navigated, bad.effects.focused], [[], [], 0]);
  for (const w of [fresh, open, bad]) assert.deepEqual([w.effects.fetches, w.effects.cache, w.effects.shown.length], [0, 0, 0], 'a tap fetches, caches and answers nothing');
});
