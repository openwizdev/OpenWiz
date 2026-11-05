// IF1/IF9 (#1109): the one install line's journey in Chromium. The actual
// install entry (tools/install/install) installs a synthetic release laid out
// as GitHub publishes it, `install open` serves that build's own setup page,
// and the page, at phone and desktop widths, shows the next step and the
// cost panel (#2293): OpenWiz is free now and paid plans come later, CloudRoom
// and model charges are separate, referral verification is unavailable and no
// referral is applied; no OpenWiz upgrade, price or trial is offered.
// Synthetic package only; no account, CloudRoom or GitHub call.
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { DESKTOP, PHONE, launchBrowser, openPage, waitFor } from '../support/browser.mjs';
import { OUT_DIR, REPO_DIR, RESULTS_DIR } from '../support/paths.mjs';
import { buildBinaries } from '../support/rust.mjs';

const TARGET = 'x86_64-unknown-linux-gnu';
const NAME = `openwiz-${TARGET}`;
const ENTRY = join(REPO_DIR, 'tools/install/install');
const FIXTURE = JSON.parse(readFileSync(join(REPO_DIR, 'apps/web/test/fixtures/install-journey/expected.json'), 'utf8'));
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');

async function freePort() {
  const socket = createServer();
  await new Promise((resolve, reject) => { socket.once('error', reject); socket.listen(0, '127.0.0.1', resolve); });
  const port = socket.address().port;
  await new Promise((resolve) => socket.close(resolve));
  return port;
}

/** The synthetic bundle, renamed to the release's published file names. */
function published(temporary) {
  const fixture = JSON.parse(execFileSync('python3', [join(REPO_DIR, 'tools/install/fixture_bundle.py'),
    '--output', join(temporary, 'bundle'), '--server', join(REPO_DIR, 'target/debug/examples/openwiz-server'),
    '--web', OUT_DIR], { encoding: 'utf8' }));
  const assets = join(temporary, 'downloads');
  mkdirSync(assets, { mode: 0o700 });
  const manifest = JSON.parse(readFileSync(fixture.manifest, 'utf8'));
  manifest.archive = `openwiz-${manifest.version}-${TARGET}.tar.gz`;
  copyFileSync(fixture.archive, join(assets, manifest.archive));
  const bytes = Buffer.from(JSON.stringify(manifest));
  writeFileSync(join(assets, `${NAME}.manifest.json`), bytes, { mode: 0o600 });
  writeFileSync(join(assets, `${NAME}.sha256`), `${sha(bytes)}  ${NAME}.manifest.json\n`, { mode: 0o600 });
  chmodSync(join(assets, manifest.archive), 0o600);
  return assets;
}

test('IF1/IF9/#2293: the install entry installs and opens setup; the cost panel says free now, paid plans later', async () => {
  buildBinaries();
  const temporary = mkdtempSync(join(tmpdir(), 'openwiz-install-journey-'));
  chmodSync(temporary, 0o700);
  const root = join(temporary, 'installed');
  const forbidden = join(temporary, 'room-cli');
  writeFileSync(forbidden, '#!/bin/sh\nprintf "unexpected call\\n" >> "$HOME/forbidden-calls"\nexit 1\n', { mode: 0o700 });
  const env = { ...process.env, HOME: temporary, OPENWIZ_FIXTURE_PROGRAM: forbidden, OPENWIZ_STATE_DIR: join(root, 'state') };
  const assets = published(temporary);
  const installed = JSON.parse(execFileSync('python3', ['-I', ENTRY, 'install', '--assets', assets, '--target', TARGET,
    '--root', root], { encoding: 'utf8', env }));
  assert.equal(installed.activated, true);
  const port = await freePort();
  const child = spawn('python3', ['-I', ENTRY, 'open', '--root', root, '--port', String(port)],
    { cwd: temporary, env, stdio: ['ignore', 'pipe', 'pipe'] });
  let diagnostic = '';
  let opened = '';
  child.stderr.on('data', (bytes) => { diagnostic += bytes; });
  child.stdout.on('data', (bytes) => { opened += bytes; });
  const browser = await launchBrowser();
  try {
    await waitFor(async () => {
      assert.equal(child.exitCode, null, diagnostic);
      return fetch(`http://127.0.0.1:${port}/setup`).then((r) => r.status === 200, () => false);
    }, { what: 'install open serves the installed setup' });
    assert.equal(JSON.parse(opened.split('\n')[0]).build, installed.build);
    for (const [name, viewport] of [['phone', PHONE], ['desktop', DESKTOP]]) {
      const p = await openPage(browser, `http://127.0.0.1:${port}`, { viewport, path: '/setup' });
      try {
        await p.page.locator('[data-setup-ready="true"]').waitFor();
        assert.equal(await p.page.getByRole('heading', { name: 'Set up OpenWiz', exact: true }).count(), 1);
        assert.match(await p.page.locator('main').innerText(), /No engine or agents have been started/);
        const cost = p.page.locator('[data-setup-cost]');
        assert.equal((await cost.innerText()).replace(/\s+/g, ' ').trim(), FIXTURE.upgrade);
        assert.equal(await cost.locator('a').count(), 0, 'the app makes no outbound link');
        assert.doesNotMatch(await cost.innerHTML(), /[?#&]|ref=|referral=/i, 'no referral code or parameter is guessed');
        assert.doesNotMatch(await p.page.locator('main').innerText(), /upgrad|\btrial|\$\s?[0-9]|per month|checkout|subscri/i,
          'no OpenWiz upgrade, price or trial on the setup page');
        const bounds = await p.page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: innerWidth }));
        assert.ok(bounds.width <= bounds.viewport, JSON.stringify(bounds));
        assert.deepEqual(p.errors, []);
        assert.ok(p.requests.filter((r) => new URL(r.url).pathname.startsWith('/api/')).every((r) =>
          r.method === 'GET' && new URL(r.url).pathname === '/api/v1/setup'), 'setup only reads');
        mkdirSync(RESULTS_DIR, { recursive: true });
        await p.page.screenshot({ path: join(RESULTS_DIR, `install-journey-${name}.png`), fullPage: true });
      } finally { await p.context.close(); }
    }
    assert.equal(existsSync(join(temporary, 'forbidden-calls')), false, 'no account reads or writes');
  } finally {
    await browser.close();
    if (child.exitCode === null) { child.kill('SIGTERM'); await new Promise((resolve) => child.once('exit', resolve)); }
    rmSync(temporary, { recursive: true, force: true });
  }
});
