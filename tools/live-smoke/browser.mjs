// One bounded phone/desktop sitting. Returns observations, never a verdict.
// Uses the project's already-approved playwright-core; no package installation.
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

let browser;
try {
  const config = JSON.parse(await readFile(process.argv[2], 'utf8'));
  const require = createRequire(resolve(config.checkout, 'apps/web/package.json'));
  const { chromium } = require('playwright-core');
  const base = new URL(config.origin);
  if (base.protocol !== 'http:' || base.hostname !== '127.0.0.1' || base.username || base.password || base.pathname !== '/') throw Error();
  if (![0, 1].includes(config.max_writes)) throw Error();
  if (config.allowed_host && !/^[A-Za-z0-9.-]+$/.test(config.allowed_host)) throw Error();
  browser = await chromium.launch({ executablePath: config.chromium, timeout: 10_000 });
  const context = await browser.newContext({
    viewport: config.viewport, hasTouch: true, serviceWorkers: 'block',
    reducedMotion: 'reduce', locale: 'en-GB', timezoneId: 'UTC',
  });
  const requests = [];
  const responses = [];
  let errors = 0;
  let writes = 0;
  // Exact request allowlist, including the configured guarded Host. It prevents
  // a wrong-target POST before dispatch, rather than merely reporting it later.
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== base.origin) { errors++; return route.abort(); }
    if (url.pathname.startsWith('/api/')) {
      const entry = [request.method(), url.pathname + url.search];
      requests.push(entry);
      if (!config.allowed_requests.some(row => JSON.stringify(row) === JSON.stringify(entry))) {
        errors++;
        return route.abort();
      }
      if (request.method() !== 'GET' && ++writes > config.max_writes) {
        errors++;
        return route.abort();
      }
    } else if (request.method() !== 'GET') { errors++; return route.abort(); }
    // The PC sitting emulates the reviewed guarded host over loopback. Keep
    // the app's own custom header/body; don't manufacture them for the UI.
    const headers = { ...request.headers() };
    if (config.allowed_host) {
      headers.host = config.allowed_host;
      if (request.method() !== 'GET') {
        headers.origin = `https://${config.allowed_host}`;
        headers['sec-fetch-site'] = 'same-origin';
      }
    }
    return route.continue({ headers });
  });
  const page = await context.newPage();
  page.setDefaultTimeout(10_000);
  page.on('pageerror', () => errors++);
  page.on('response', response => {
    const url = new URL(response.url());
    if (url.pathname.startsWith('/api/')) responses.push([response.request().method(), url.pathname, response.status()]);
  });
  const facts = [];
  await page.goto(base.href, { waitUntil: 'domcontentloaded', timeout: 15_000 });
  for (const step of config.steps) {
    const locator = step.role
      ? page.getByRole(step.role, { name: step.name, exact: true })
      : step.selector ? page.locator(step.selector) : null;
    switch (step.kind) {
      case 'click': await locator.click(); break;
      case 'fill': await locator.fill(step.value); break;
      case 'press': await locator.press(step.value); break;
      case 'visible': await locator.waitFor({ state: 'visible' }); facts.push(true); break;
      case 'text': facts.push(await locator.innerText()); break;
      case 'attribute': facts.push(await locator.getAttribute(step.attribute)); break;
      case 'count': facts.push(await locator.count()); break;
      case 'offline': await context.setOffline(step.value); break;
      case 'viewport': await page.setViewportSize(step.value); break;
      default: throw Error();
    }
  }
  await context.close();
  console.log(JSON.stringify({ facts, requests, responses, errors,
    writes: requests.filter(([method]) => method !== 'GET').length }));
} catch {
  console.log(JSON.stringify({ unavailable: true }));
  process.exitCode = 3;
} finally {
  if (browser) await browser.close();
}
