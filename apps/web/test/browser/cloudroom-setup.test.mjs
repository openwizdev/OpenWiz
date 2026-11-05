// PR2 (#2201): setup's CloudRoom step on the real setup tool, server and page.
// Recording fakes only: CloudRoom's launcher is a shell script answering
// synthetic `room-cli cloud status --json` fixtures, and install records are
// planted synthetic files. Nothing is downloaded, installed or signed in.
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createServer as createNetServer } from 'node:net';
import { arch, platform, tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { DESKTOP, PHONE, launchBrowser, openPage, waitFor } from '../support/browser.mjs';
import { OUT_DIR, REPO_DIR, RESULTS_DIR } from '../support/paths.mjs';
import { buildBinaries } from '../support/rust.mjs';

const TOOL = join(REPO_DIR, 'tools/install/cloudroom');
const FIXTURE = join(REPO_DIR, 'apps/web/test/fixtures/cloudroom-setup');
const SERVER = join(REPO_DIR, 'target/debug/examples/openwiz-server');
const POWERED_BY = 'Powered by CloudRoom';
// This host's own answer when nothing is installed: CI's Linux x64 has a
// checkable installer; any other platform has none.
const SUPPORTED = (platform() === 'linux' && arch() === 'x64') || (platform() === 'darwin' && arch() === 'arm64');

test('PR2: the CloudRoom tool proofs (install, reuse, integrity, interruption, lost reply, login, sign-in)', () => {
  execFileSync('python3', ['-I', '-B', join(TOOL, 'test_cloudroom.py')], { stdio: 'inherit' });
});

async function freePort() {
  const socket = createNetServer();
  await new Promise((resolve, reject) => { socket.once('error', reject); socket.listen(0, '127.0.0.1', resolve); });
  const port = socket.address().port;
  await new Promise((resolve) => socket.close(resolve));
  return port;
}

// Each scenario: what is on the host, what CloudRoom's launcher answers, and
// the state and reason the step must show.
const SCENARIOS = [
  { name: 'not-installed', state: SUPPORTED ? 'missing' : 'refused', reason: SUPPORTED ? /not installed/ : /platform/ },
  { name: 'reused', appimage: true, state: 'unknown', reason: /existing CloudRoom installation is reused/ },
  { name: 'install-uncertain', record: 'install-uncertain.json', state: 'unknown', reason: /did not report back/ },
  { name: 'install-failed', record: 'install-failed.json', state: 'unknown', reason: /install failed/ },
  { name: 'install-declined', record: 'install-declined.json', state: 'refused', reason: /declined/ },
  { name: 'checksum-mismatch', record: 'install-checksum-mismatch.json', state: 'refused', reason: /published checksum/ },
  { name: 'login-missing', appimage: true, launcher: 'cloud-signed-out.json', state: 'missing', reason: /no signed-in account/ },
  { name: 'login-unknown', appimage: true, launcher: 'cloud-signing-in.json', state: 'unknown', reason: /no current login evidence/ },
  { name: 'login-verified', appimage: true, launcher: 'cloud-signed-in.json', state: 'verified', reason: /reports a signed-in account now/ },
];

function plant(root, scenario) {
  const home = join(root, 'home');
  const state = join(root, 'state');
  rmSync(home, { recursive: true, force: true });
  mkdirSync(join(home, '.local/bin'), { recursive: true, mode: 0o700 });
  rmSync(join(state, 'cloudroom'), { recursive: true, force: true });
  if (scenario.appimage) {
    mkdirSync(join(home, 'Applications'));
    writeFileSync(join(home, 'Applications/Cloudroom.AppImage'), 'existing synthetic copy');
    chmodSync(join(home, 'Applications/Cloudroom.AppImage'), 0o755);  // launchable, as an installed copy is
  }
  if (scenario.launcher) {
    const launcher = join(home, '.local/bin/room-cli');
    writeFileSync(launcher, `#!/bin/sh\necho "$*" >> '${join(root, 'calls.log')}'\ncat '${join(TOOL, 'fixtures', scenario.launcher)}'\n`);
    chmodSync(launcher, 0o700);
  }
  if (scenario.record) {
    mkdirSync(join(state, 'cloudroom'), { recursive: true, mode: 0o700 });
    copyFileSync(join(FIXTURE, scenario.record), join(state, 'cloudroom/install.json'));
    chmodSync(join(state, 'cloudroom/install.json'), 0o600);
  }
  return { home, state };
}

test('PR2: one CloudRoom sign-in screen shows every state honestly, with its powered-by line, at phone and desktop widths', async () => {
  buildBinaries();
  const root = mkdtempSync(join(tmpdir(), 'openwiz-cloudroom-page-'));
  chmodSync(root, 0o700);
  // The collector's layout: the setup tool beside the CloudRoom tool, outside the repository.
  const runtime = join(root, 'build/runtime');
  for (const [from, to] of [['tools/install/setup/setup.py', 'setup/setup.py'], ['tools/install/setup/store.py', 'setup/store.py'],
    ['tools/install/cloudroom/cloudroom.py', 'cloudroom/cloudroom.py']]) {
    mkdirSync(join(runtime, to, '..'), { recursive: true });
    copyFileSync(join(REPO_DIR, from), join(runtime, to));
  }
  const state = join(root, 'state');
  mkdirSync(state, { mode: 0o700 });
  const port = await freePort();
  const server = spawn(SERVER, ['--web-root', OUT_DIR, '--port', String(port)], {
    env: { PATH: '/usr/bin:/bin', HOME: root, OPENWIZ_STATE_DIR: state, OPENWIZ_FIXTURE_PROGRAM: join(root, 'no-room-cli') },
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  server.stderr.resume();
  const origin = `http://127.0.0.1:${port}`;
  let browser;
  try {
    await waitFor(() => fetch(`${origin}/api/v1/setup`).then((r) => r.status === 200, () => false), { what: 'the setup server' });
    browser = await launchBrowser();
    for (const scenario of SCENARIOS) {
      const { home } = plant(root, scenario);
      const check = execFileSync('python3', ['-I', '-B', join(runtime, 'setup/setup.py'), 'check', '--state-dir', state],
        { cwd: root, env: { PATH: '/usr/bin:/bin', HOME: home }, stdio: ['ignore', 'pipe', 'inherit'] });
      assert.ok(JSON.parse(check).results.cloudroom.startsWith('cloudroom_'), scenario.name);
      for (const [width, viewport] of [['phone', PHONE], ['desktop', DESKTOP]]) {
        const opened = await openPage(browser, origin, { path: '/setup', viewport });
        try {
          const { page, requests } = opened;
          await page.waitForSelector('[data-setup-ready="true"]');
          const step = page.locator('[data-setup-component="cloudroom"]');
          assert.equal(await step.locator('.setup-state').innerText(), scenario.state, `${scenario.name} ${width}`);
          await step.locator('summary').first().click();
          const text = await step.innerText();
          assert.match(text, scenario.reason, `${scenario.name} ${width}: ${text}`);
          // One sign-in screen, on the CloudRoom step, in its state.
          assert.equal(await page.locator('[data-cloudroom-setup]').count(), 1);
          assert.equal(await step.locator('[data-cloudroom-setup]').getAttribute('data-cloudroom-setup'), scenario.state);
          assert.equal(await step.getByRole('heading', { name: 'CloudRoom sign-in', exact: true }).isVisible(), true);
          // Signed in only on the verified login read; never for unknown, failed or uncertain.
          assert.equal(/reports you are signed in/.test(text), scenario.state === 'verified', `${scenario.name}: ${text}`);
          assert.equal(/installed|reused/.test(await step.locator('.setup-state').innerText()), false);
          assert.match(text, scenario.state === 'verified' ? /Nothing to do/ : /OpenWiz never asks for, sees or stores your CloudRoom password or token/);
          // The contract's powered-by line, exactly once, on the CloudRoom step only.
          const line = page.getByText(POWERED_BY, { exact: true });
          assert.equal(await line.count(), 1);
          assert.equal(await step.getByText(POWERED_BY, { exact: true }).isVisible(), true);
          assert.equal((await page.locator('body').innerText()).split(POWERED_BY).length - 1, 1);
          // The main flow stays in OpenWiz: no password field, no outside link or request.
          assert.equal(await page.locator('input[type="password"]').count(), 0);
          assert.equal(await step.locator('a[href]').count(), 0);
          assert.deepEqual(requests.filter((r) => !r.url.startsWith(origin)).map((r) => r.url), []);
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
          if (scenario.name === 'login-missing' || scenario.name === 'login-verified') {
            await step.screenshot({ path: join(RESULTS_DIR, `cloudroom-setup-${scenario.name}-${width}.png`) });
          }
        } finally { await opened.context.close(); }
      }
    }
    assert.equal(existsSync(join(root, 'calls.log')), true);
  } finally {
    await browser?.close();
    server.kill('SIGTERM');
    await new Promise((resolve) => server.once('exit', resolve));
    rmSync(root, { recursive: true, force: true });
  }
});
