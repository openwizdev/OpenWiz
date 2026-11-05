// IF7: real setup-page route choices; fixture server, no accounts or writes.
// The old page only names alternatives and has no usable access guidance.
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { chmodSync, copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { createServer, request } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { PHONE, DESKTOP, launchBrowser, openPage, waitFor } from '../support/browser.mjs';
import { OUT_DIR, REPO_DIR, RESULTS_DIR } from '../support/paths.mjs';
import { buildBinaries } from '../support/rust.mjs';

test('IF7: packaged verification, policy/refusal, privacy and exact-operation recovery proofs', () => {
  execFileSync('python3', ['-I', '-B', join(REPO_DIR, 'tools/install/access/test_access.py')], { stdio: 'inherit' });
});

test('IF7: setup guides each authenticated route and recovery without activating or replaying work', async () => {
  buildBinaries();
  const root = mkdtempSync(join(tmpdir(), 'openwiz-access-page-'));
  chmodSync(root, 0o700);
  const child = spawn(join(REPO_DIR, 'target/debug/examples/openwiz-server'), ['--port', '0', '--web-root', OUT_DIR], {
    cwd: root,
    env: { PATH: '/usr/bin:/bin', HOME: root, OPENWIZ_STATE_DIR: root,
      OPENWIZ_FIXTURE_PROGRAM: join(root, 'no-room-cli') },
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  let log = '';
  child.stderr.on('data', (bytes) => { log += bytes; });
  let browser;
  try {
    await waitFor(() => /listening on http:\/\/127\.0\.0\.1:(\d+)/.exec(log), { what: 'fixture setup server' });
    const origin = /listening on (http:\/\/127\.0\.0\.1:\d+)/.exec(log)[1];
    browser = await launchBrowser();
    for (const [name, viewport] of [['phone', PHONE], ['desktop', DESKTOP]]) {
      const opened = await openPage(browser, origin, { path: '/setup', viewport });
      try {
        const { page, requests } = opened;
        await page.waitForSelector('[data-setup-ready="true"]');
        const access = page.locator('[data-setup-component="remote_access"]');
        await access.locator('summary').first().click();
        const route = access.getByLabel('Phone access route', { exact: true });
        assert.equal(await route.count(), 1, 'phone access needs a route choice, not just the alternatives named in prose');
        assert.match(await access.innerText(), /Cloudflare account/);
        assert.match(await access.innerText(), /managed domain/);
        assert.match(await access.innerText(), /No hidden purchase/);
        assert.match(await access.innerText(), /named tunnel/);
        assert.match(await access.innerText(), /owner-only Access/);
        assert.match(await access.innerText(), /all paths/);
        assert.match(await access.innerText(), /loopback/);
        assert.match(await access.innerText(), /unauthenticated, expired and foreign/);
        assert.match(await access.innerText(), /running tunnel alone is not ready/);
        assert.equal(await access.getByRole('heading', { name: 'Recovery', exact: true }).isVisible(), true);
        assert.match(await access.innerText(), /operation ID/);
        assert.match(await access.innerText(), /never resends/);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        await page.screenshot({ path: join(RESULTS_DIR, `install-access-${name}.png`), fullPage: true });
        await route.selectOption('tailscale');
        assert.match(await access.innerText(), /Tailscale account/);
        assert.match(await access.innerText(), /phone and engine host/);
        assert.match(await access.innerText(), /owner-only/);
        assert.match(await access.innerText(), /Funnel/);
        assert.match(await access.innerText(), /HTTPS/);
        assert.match(await access.innerText(), /unauthenticated, expired and foreign/);
        await page.getByRole('button', { name: 'Refresh', exact: true }).click();
        await page.waitForSelector('[data-setup-ready="true"]');
        assert.equal(await route.inputValue(), 'tailscale', 'refresh preserves the selected guidance');
        assert.equal(await access.locator('.setup-state').innerText(), 'unknown');
        await page.reload();
        await page.waitForSelector('[data-setup-ready="true"]');
        assert.deepEqual(requests.filter((r) => new URL(r.url).pathname.startsWith('/api/')).map((r) => [r.method, new URL(r.url).pathname]),
          [['GET', '/api/v1/setup'], ['GET', '/api/v1/setup'], ['GET', '/api/v1/setup']], 'choosing, refreshing and reloading guidance never sends or creates');
        assert.deepEqual(opened.errors, []);
        assert.deepEqual(await opened.csp(), []);
      } finally { await opened.close(); }
    }
  } finally {
    await browser?.close();
    const exited = new Promise((resolve) => child.once('exit', resolve));
    if (child.exitCode === null && child.signalCode === null) { child.kill('SIGTERM'); await exited; }
    rmSync(root, { recursive: true, force: true });
    rmSync(`${root}.fixture-bundles`, { recursive: true, force: true });
  }
});

// The edge is a test-only identity/network boundary, independent of the tool's
// policy readers. For Tailscale its identity labels represent network members;
// real Tailscale does not use these fixture cookies. No TLS/native claim here.
function ask(port, path, { method = 'GET', headers = {}, body = null } = {}) {
  return new Promise((resolve, reject) => {
    const call = request({ hostname: '127.0.0.1', port, path, method, headers }, (response) => {
      const chunks = [];
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('end', () => resolve({ status: response.statusCode, body: Buffer.concat(chunks).toString() }));
    });
    call.on('error', reject);
    call.end(body);
  });
}

async function accessHost(a) {
  const child = spawn(join(REPO_DIR, 'target/debug/examples/openwiz-server'), ['--port', '0', '--allowed-host', a.plan.host, '--web-root', OUT_DIR], {
    cwd: a.root, env: { PATH: '/usr/bin:/bin', HOME: a.root, OPENWIZ_STATE_DIR: a.state,
      OPENWIZ_FIXTURE_PROGRAM: join(a.root, 'bin/room-cli') }, stdio: ['ignore', 'ignore', 'pipe'],
  });
  let log = '';
  child.stderr.on('data', (bytes) => { log += bytes; });
  await waitFor(() => /listening on http:\/\/127\.0\.0\.1:(\d+)/.exec(log), { what: 'access fixture server' });
  return { port: Number(/listening on http:\/\/127\.0\.0\.1:(\d+)/.exec(log)[1]),
    async stop() { if (child.exitCode !== null || child.signalCode !== null) return; const exited = new Promise((resolve) => child.once('exit', resolve)); child.kill('SIGTERM'); await exited; } };
}

function tool(a, { operation = null, mode = 'normal', edge = null } = {}) {
  const args = ['-I', '-B', join(REPO_DIR, 'apps/web/test/fixtures/install-access/driver.py'),
    '--runtime', a.runtime, '--state', a.state, '--plan', join(a.root, 'plan.json'), '--secrets', join(a.root, 'secrets.json'), '--mode', mode,
    ...(operation ? ['--operation', operation] : []), ...(edge ? ['--edge', edge] : [])];
  // Async: probes must let this process's recording edge answer.
  return new Promise((resolve, reject) => {
    const child = spawn('python3', args, { cwd: a.root, env: { PATH: '/usr/bin:/bin' }, stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '', err = '';
    child.stdout.on('data', (bytes) => { out += bytes; });
    child.stderr.on('data', (bytes) => { err += bytes; });
    child.on('error', reject);
    child.on('close', (status) => resolve({ status, out, err, value: out ? JSON.parse(out) : null }));
  });
}

function accessAccount(root, provider) {
  mkdirSync(root, { mode: 0o700 });
  const state = join(root, 'state'), runtime = join(root, 'runtime');
  mkdirSync(join(runtime, 'access'), { recursive: true });
  mkdirSync(join(runtime, 'setup'));
  mkdirSync(join(root, 'bin'));
  // Production files only, laid out as collected into the release runtime.
  for (const file of ['access/access.py', 'setup/store.py']) copyFileSync(join(REPO_DIR, 'tools/install', file), join(runtime, file));
  symlinkSync(join(REPO_DIR, 'target/debug/fake-room-cli'), join(root, 'bin/room-cli'));
  writeFileSync(join(root, 'bin/fake-room-cli.scenario'), join(REPO_DIR, 'tests/fixtures/room-cli-0.43.1/send/scenario.json'));
  // The fixture factory owns synthetic values, shared with the Python proofs.
  execFileSync('python3', ['-I', '-B', '-c', `import sys,json; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from provider import selected,credentials; root=Path(sys.argv[2]); [(root/name).write_text(json.dumps(value)) for name,value in [('plan.json',selected(sys.argv[3])),('secrets.json',credentials(sys.argv[3]))]]`,
    join(REPO_DIR, 'apps/web/test/fixtures/install-access'), root, provider]);
  for (const name of ['plan.json', 'secrets.json']) chmodSync(join(root, name), 0o600);
  return { root, state, runtime, plan: JSON.parse(readFileSync(join(root, 'plan.json'))), secrets: JSON.parse(readFileSync(join(root, 'secrets.json'))) };
}

const tellCount = (a) => {
  let lines;
  try { lines = readFileSync(join(a.root, 'bin/invocations.log'), 'utf8').trim().split('\n').filter(Boolean); } catch { return 0; }
  return lines.map((line) => JSON.parse(line)).filter((argv) => argv[0] === 'thread' && argv[1] === 'tell').length;
};

test('IF7: real setup reads provider results; denied writes and reconnect/restart cannot replay pending work', async () => {
  buildBinaries();
  const temporary = mkdtempSync(join(tmpdir(), 'openwiz-access-journey-'));
  chmodSync(temporary, 0o700);
  const browser = await launchBrowser();
  try {
    for (const provider of ['cloudflare', 'tailscale']) {
      const a = accessAccount(join(temporary, provider), provider);
      let host = await accessHost(a), opened;
      const edgeState = { expired: false, foreignLeaks: false, dropReply: false, originWrites: 0 };
      const edge = createServer((incoming, outgoing) => {
        let claims = null;
        try {
          const cookie = /CF_Authorization=([^;]+)/.exec(incoming.headers.cookie ?? '')?.[1];
          claims = JSON.parse(Buffer.from(cookie.split('.')[1], 'base64url'));
        } catch { /* anonymous synthetic network context */ }
        const current = claims && claims.exp * 1000 > Date.now();
        const owner = current && claims.email === a.plan.owner;
        if (edgeState.expired || (!owner && !(edgeState.foreignLeaks && current))) {
          outgoing.writeHead(edgeState.expired ? 401 : current ? 403 : 401); outgoing.end('Synthetic access denial'); return;
        }
        if (incoming.method !== 'GET') edgeState.originWrites++;
        const upstream = request({ hostname: '127.0.0.1', port: host.port, path: incoming.url, method: incoming.method,
          headers: { ...incoming.headers, host: a.plan.host } }, (response) => {
          const chunks = [];
          response.on('data', (chunk) => chunks.push(chunk));
          response.on('end', () => {
            if (incoming.method === 'POST' && edgeState.dropReply) { edgeState.dropReply = false; incoming.socket.destroy(); return; }
            outgoing.writeHead(response.statusCode, response.headers); outgoing.end(Buffer.concat(chunks));
          });
        });
        upstream.on('error', () => { outgoing.writeHead(502); outgoing.end('Synthetic host offline'); });
        incoming.pipe(upstream);
      });
      await new Promise((resolve) => edge.listen(0, '127.0.0.1', resolve));
      const edgePort = edge.address().port, origin = `http://127.0.0.1:${edgePort}`;
      const cookie = (identity) => `CF_Authorization=${a.secrets[identity]}`;
      // Tailscale network identities use synthetic context labels here.
      if (provider === 'tailscale') {
        const now = Math.floor(Date.now() / 1000);
        const jwt = (email, exp) => `SyntheticHeader.${Buffer.from(JSON.stringify({ email, exp })).toString('base64url')}.SyntheticSignature`;
        Object.assign(a.secrets, { owner: jwt(a.plan.owner, now + 7200), expired: jwt(a.plan.owner, now - 7200), foreign: jwt(a.plan.foreign, now + 7200) });
      }
      const headers = { Host: a.plan.host, Origin: `https://${a.plan.host}`, 'Sec-Fetch-Site': 'same-origin', 'X-OpenWiz-Send': '1', 'Content-Type': 'application/json' };
      const body = JSON.stringify({ op_id: 'access-proof-pending', text: 'Synthetic pending work', mode: 'queue' });
      try {
        const preview = await tool(a);
        assert.equal(preview.status, 0, preview.err);
        const operation = preview.value.operation.operation_id;
        assert.equal(preview.value.operation.phase, 'proposed');
        const interrupted = await tool(a, { operation, mode: 'interrupt' });
        assert.notEqual(interrupted.status, 0);
        const read = async () => JSON.parse((await ask(host.port, '/api/v1/setup')).body);
        assert.equal((await read()).operations[0].phase, 'uncertain');
        opened = await openPage(browser, `http://127.0.0.1:${host.port}`, { path: '/setup', viewport: PHONE });
        const { page } = opened;
        await opened.context.addCookies([{ name: 'CF_Authorization', value: a.secrets.owner, url: origin }]);
        await page.goto(origin + '/setup');
        await page.waitForSelector('[data-setup-operation="configure_access"][data-setup-phase="uncertain"]');
        const access = page.locator('[data-setup-component="remote_access"]');
        await access.locator('summary').first().click();
        await access.getByLabel('Phone access route', { exact: true }).selectOption(provider);
        assert.equal(await access.getByLabel('Phone access route', { exact: true }).inputValue(), a.plan.provider,
          'the owner-selected guidance and the installing agent\'s exact private plan agree');
        for (const identity of ['anonymous', 'expired', 'foreign']) {
          for (const path of ['/api/v1/sessions/thr_syn_0001/messages', '/api/v1/projects/prj_syn_0001/threads']) {
            const payload = path.endsWith('/threads') ? JSON.stringify({ op_id: 'access-proof-denied-create', harness: 'codex', model: 'syn-codex-model-01', effort: 'high', text: 'Synthetic denied create', attachments: [] }) : body;
            const denied = await ask(edgePort, path, { method: 'POST', headers: { ...headers, ...(identity === 'anonymous' ? {} : { Cookie: cookie(identity) }) }, body: payload });
            assert.ok([401, 403].includes(denied.status));
          }
        }
        assert.equal(edgeState.originWrites, 0);
        assert.equal(tellCount(a), 0);
        edgeState.foreignLeaks = provider === 'cloudflare';
        const refused = await tool(a, { operation, mode: 'foreign', edge: origin });
        assert.equal(refused.value.observation.code, 'access_refused');
        assert.equal(refused.value.operation.phase, 'uncertain');
        edgeState.foreignLeaks = false;
        const unavailable = await tool(a, { operation, mode: 'offline' });
        assert.equal(unavailable.value.observation.code, 'access_unavailable');
        const expired = await tool(a, { operation, mode: 'expired' });
        assert.equal(expired.value.observation.code, 'access_expired');
        const verified = await tool(a, { operation, edge: origin });
        assert.equal(verified.status, 0, verified.err);
        assert.equal(verified.value.observation.code, `access_${provider}_verified`);
        assert.equal(verified.value.operation.operation_id, operation);
        await page.getByRole('button', { name: 'Refresh', exact: true }).click();
        await waitFor(async () => (await page.locator('[data-setup-component="remote_access"] .setup-state').innerText()) === 'verified');
        assert.equal((await read()).ready, false, 'phone verification cannot authorize an engine');
        // Each old HTTP guard remains effective behind the authenticated route.
        for (const override of [{ Origin: 'https://foreign.invalid' }, { 'X-OpenWiz-Send': '' }, { 'Content-Type': 'text/plain' }, { Host: 'foreign.invalid' }]) {
          const response = await ask(host.port, '/api/v1/sessions/thr_syn_0001/messages', { method: 'POST', headers: { ...headers, ...override }, body });
          assert.ok([403, 415, 421].includes(response.status));
        }
        assert.equal(tellCount(a), 0);
        edgeState.dropReply = true;
        await assert.rejects(ask(edgePort, '/api/v1/sessions/thr_syn_0001/messages', { method: 'POST', headers: { ...headers, Cookie: cookie('owner') }, body }));
        assert.equal(tellCount(a), 1, 'the lost reply still performed just one synthetic send');
        await opened.context.setOffline(true);
        await page.getByRole('button', { name: 'Refresh', exact: true }).click();
        await waitFor(async () => (await page.locator('main').getAttribute('data-setup-ready')) === 'false');
        await host.stop();
        host = await accessHost(a);
        await opened.context.setOffline(false);
        // A new page on the restarted host restores setup and reads the pending
        // operation; it has no code path that can replay the previous send.
        await page.goto(origin + '/setup');
        await page.waitForSelector('[data-setup-ready="true"]');
        assert.equal((await read()).operations[0].operation_id, operation);
        edgeState.expired = true;
        const expiredAfterRestart = await tool(a, { operation, mode: 'expired' });
        assert.equal(expiredAfterRestart.value.observation.code, 'access_expired');
        await page.getByRole('button', { name: 'Refresh', exact: true }).click();
        await waitFor(async () => (await page.locator('[role="status"]').innerText()).includes('expired'));
        assert.equal(await page.locator('main').getAttribute('data-setup-ready'), 'false');
        assert.equal((await ask(edgePort, '/api/v1/setup', { headers: { Cookie: cookie('owner') } })).status, 401);
        edgeState.expired = false;
        const current = await tool(a, { operation, edge: origin });
        assert.equal(current.value.observation.code, `access_${provider}_verified`);
        await page.getByRole('button', { name: 'Refresh', exact: true }).click();
        await page.waitForSelector('[data-setup-ready="true"]');
        const status = await ask(edgePort, '/api/v1/sessions/thr_syn_0001/messages/access-proof-pending', { headers: { Cookie: cookie('owner') } });
        assert.equal(status.status, 200);
        assert.equal(tellCount(a), 1);
        assert.deepEqual(opened.requests.filter((r) => new URL(r.url).pathname.startsWith('/api/') && r.method !== 'GET'), []);
        assert.deepEqual(opened.errors, []);
        assert.deepEqual(await opened.csp(), []);
        const state = readFileSync(join(a.state, 'setup/state.json'), 'utf8');
        for (const secret of Object.values(a.secrets)) assert.equal(state.includes(secret), false);
      } finally {
        await opened?.close(); await host.stop();
        await new Promise((resolve) => edge.close(resolve));
      }
    }
  } finally { await browser.close(); rmSync(temporary, { recursive: true, force: true }); }
});
