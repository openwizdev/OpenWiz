// IF1/IF9: actual offline installer and installed server. Synthetic package only.
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { DESKTOP, PHONE, launchBrowser, openPage, waitFor } from '../support/browser.mjs';
import { OUT_DIR, REPO_DIR } from '../support/paths.mjs';
import { buildBinaries } from '../support/rust.mjs';

async function freePort() {
  const socket = createServer();
  await new Promise((resolve, reject) => { socket.once('error', reject); socket.listen(0, '127.0.0.1', resolve); });
  const port = socket.address().port;
  await new Promise((resolve) => socket.close(resolve));
  return port;
}

test('IF1/IF9: install synthetic release, open real setup at phone/desktop widths with no account calls', async () => {
  buildBinaries();
  const temporary = mkdtempSync(join(tmpdir(), 'openwiz-installed-'));
  chmodSync(temporary, 0o700);
  const root = join(temporary, 'installed');
  const forbidden = join(temporary, 'room-cli');
  writeFileSync(forbidden, '#!/bin/sh\nprintf "unexpected call\\n" >> "$HOME/forbidden-calls"\nexit 1\n', { mode: 0o700 });
  const fixture = JSON.parse(execFileSync('python3', [join(REPO_DIR, 'tools/install/fixture_bundle.py'),
    '--output', join(temporary, 'release'), '--server', join(REPO_DIR, 'target/debug/examples/openwiz-server'),
    '--web', OUT_DIR], { encoding: 'utf8' }));
  const port = await freePort();
  const child = spawn('python3', [join(REPO_DIR, 'tools/install/install.py'), '--manifest', fixture.manifest,
    '--manifest-sha256', fixture.checksum, '--archive', fixture.archive, '--root', root,
    '--target', 'x86_64-unknown-linux-gnu', '--serve', '--port', String(port)], {
    cwd: temporary,
    env: { ...process.env, HOME: temporary, OPENWIZ_FIXTURE_PROGRAM: forbidden, OPENWIZ_STATE_DIR: join(root, 'state') },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let diagnostic = '';
  child.stderr.on('data', (bytes) => { diagnostic += bytes; });
  child.stdout.resume();
  const browser = await launchBrowser();
  try {
    await waitFor(async () => {
      assert.equal(child.exitCode, null, diagnostic);
      return fetch(`http://127.0.0.1:${port}/setup`).then((r) => r.status === 200, () => false);
    }, { what: 'the actual installer opens its installed setup' });
    for (const viewport of [PHONE, DESKTOP]) {
      const p = await openPage(browser, `http://127.0.0.1:${port}`, { viewport, path: '/setup' });
      try {
        await p.page.locator('[data-setup-ready="true"]').waitFor();
        assert.equal(await p.page.getByRole('heading', { name: 'Set up OpenWiz', exact: true }).count(), 1);
        assert.equal(await p.page.locator('[data-setup-component]').count(), 7);
        assert.match(await p.page.locator('main').innerText(), /No engine or agents have been started/);
        assert.match(await p.page.locator('main').innerText(), /Cloud Credits have not been measured/);
        await p.page.locator('[data-setup-component="cloudroom"] summary').click();
        assert.equal(await p.page.getByText('CloudRoom has not been checked.', { exact: true }).isVisible(), true);
        await p.page.getByRole('button', { name: 'Refresh', exact: true }).click();
        await waitFor(() => p.responses.filter((r) => r.path === '/api/v1/setup').length === 2, { what: 'one setup refresh response' });
        await p.page.locator('[data-setup-ready="true"]').waitFor();
        const bounds = await p.page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: innerWidth }));
        assert.ok(bounds.width <= bounds.viewport, JSON.stringify(bounds));
        assert.deepEqual(p.errors, []);
        assert.deepEqual(await p.page.evaluate(() => window.__csp), []);
        assert.ok(p.requests.filter((r) => new URL(r.url).pathname.startsWith('/api/')).every((r) =>
          r.method === 'GET' && new URL(r.url).pathname === '/api/v1/setup'));
      } finally { await p.context.close(); }
    }
    const alternate = await fetch(`http://127.0.0.1:${port}/setup/`);
    assert.equal(alternate.status, 200);
    assert.equal(alternate.headers.get('cache-control'), 'no-store');
    assert.equal(existsSync(join(temporary, 'forbidden-calls')), false, 'no account reads or writes');
    assert.equal(readFileSync(join(root, 'channel.json'), 'utf8'), '{"schema":"openwiz.update-channel.v1","channel":"packaged"}\n');
  } finally {
    await browser.close();
    if (child.exitCode === null) { child.kill('SIGTERM'); await new Promise((resolve) => child.once('exit', resolve)); }
    rmSync(temporary, { recursive: true, force: true });
  }
});
