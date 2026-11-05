// OpenWiz's app-shell worker (#1029). It only makes the installed app open:
//
// - It caches only the static shell: the pages `/` and `/setup`, the
//   manifest, and files under /_next/static/, /fonts/ and /icons/, each from
//   this origin, as the server answered them (200, not redirected).
// - It never handles anything else. The API (/api/...) and every request that
//   is not a GET pass straight to the network, so an answer about your
//   sessions is never stored or served from a cache, and a send, create,
//   upload or removal is never stored, queued, retried or replayed: offline,
//   it fails at once, as it would without a worker.
// - Pages come from the network first; the cached copy only when the network
//   fails, so the app can open and say it is offline. Hashed assets, fonts and
//   icons come from the cache first.
// - On install it stores `/` and the shell files that page names, so the
//   installed app opens offline from its first visit.
// - Notifications (#2035) only show and open. A push shows one generic
//   notification only for the exact minimal payload (notifications.v1's
//   ExternalPayload, as canonical JSON), keeping just its opaque token; any
//   other payload is ignored. A tap only opens this origin's
//   `/#notification=<token>`, where the authenticated cockpit re-reads the
//   item. Neither fetches, caches, stores, answers or replays anything.

const CACHE = 'openwiz-shell-v1';
const PAGES = ['/', '/setup'];
const ASSETS = /^\/(_next\/static|fonts|icons)\/[A-Za-z0-9._/-]+$/;

const isShell = (url) =>
  url.origin === self.location.origin &&
  url.search === '' &&
  (PAGES.includes(url.pathname) || url.pathname === '/manifest.webmanifest' || ASSETS.test(url.pathname));

// Stores a good answer for offline use, then returns it. Storing is best
// effort: if the cache can't be written (storage full or unavailable), the
// network's answer is still served, never an older copy or a failure.
async function keep(request, response) {
  if (response.ok && response.status === 200 && !response.redirected && response.type === 'basic') {
    try {
      const cache = await caches.open(CACHE);
      await cache.put(request, response.clone());
    } catch {
      // Not stored; served anyway.
    }
  }
  return response;
}

// The stored copy, or undefined. A failed read (storage unavailable) is a
// miss, so the network is still asked.
async function stored(request) {
  try {
    return await caches.match(request, { cacheName: CACHE });
  } catch {
    return undefined;
  }
}

async function networkFirst(request) {
  try {
    return await keep(request, await fetch(request));
  } catch (error) {
    const cached = await stored(request);
    if (cached) return cached;
    throw error;
  }
}

async function cacheFirst(request) {
  const cached = await stored(request);
  return cached ?? keep(request, await fetch(request));
}

// The shell files a page names: same-origin paths under /_next/static/, /fonts/ and /icons/.
const NAMED = /(?:src|href)="(\/(?:_next\/static|fonts|icons)\/[A-Za-z0-9._/-]+)"/g;

async function install() {
  const cache = await caches.open(CACHE);
  const page = await fetch('/', { cache: 'no-store' });
  if (page.status !== 200) throw new Error('the page did not load');
  const named = new Set([...(await page.clone().text()).matchAll(NAMED)].map((m) => m[1]));
  await cache.addAll([...named, '/manifest.webmanifest']);
  await cache.put('/', page);
}

self.addEventListener('install', (event) => {
  event.waitUntil(install().then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (!isShell(url)) return;
  const page = PAGES.includes(url.pathname) || url.pathname === '/manifest.webmanifest';
  event.respondWith(page ? networkFirst(request) : cacheFirst(request));
});

const TITLE = 'OpenWiz needs your attention';
const PAYLOAD = /^\{"title":"OpenWiz needs your attention","target_token":"([0-9a-f]{64})"\}$/;
const TOKEN = /^[0-9a-f]{64}$/;

// The token of an exact payload, or null. Anything else, including extra,
// reordered or repeated keys, is untrusted.
function payloadToken(data) {
  try {
    const match = data ? PAYLOAD.exec(data.text()) : null;
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

self.addEventListener('push', (event) => {
  const token = payloadToken(event.data);
  if (!token) return;
  event.waitUntil(self.registration.showNotification(TITLE, { tag: token, data: { token }, icon: '/icons/icon-192.png' }));
});

// Navigation only: the token is never a URL, origin, path or redirect.
async function openBound(token) {
  const url = new URL(`/#notification=${token}`, self.location.origin).href;
  const windows = await self.clients.matchAll({ type: 'window' });
  const own = windows.find((c) => new URL(c.url).origin === self.location.origin);
  if (own) {
    try {
      await own.focus();
      await own.navigate(url);
      return;
    } catch {
      // Not navigable: open the bound fragment instead.
    }
  }
  await self.clients.openWindow(url);
}

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const data = event.notification.data;
  const keys = data && typeof data === 'object' ? Object.keys(data) : [];
  if (keys.length !== 1 || keys[0] !== 'token' || typeof data.token !== 'string' || !TOKEN.test(data.token)) return;
  event.waitUntil(openBound(data.token));
});
