// IF4/IF5 (#1105): the actual setup tool, server and page on a plain consumer.
// Recording fakes only: the installed openwiz CLI, the agent's gh login and
// GitHub's App API on 127.0.0.1. Synthetic data and disposable keys only.
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { createPublicKey, verify } from 'node:crypto';
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { createServer as createNetServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { DESKTOP, PHONE, launchBrowser, openPage, waitFor } from '../support/browser.mjs';
import { OUT_DIR, REPO_DIR, RESULTS_DIR } from '../support/paths.mjs';
import { buildBinaries } from '../support/rust.mjs';

const FIXTURE = join(REPO_DIR, 'apps/web/test/fixtures/install-connections');
// The collector ships these as runtime/setup/ (tools/release/build_products.py, #1105 R9).
const SOURCES = join(REPO_DIR, 'tools/install/setup');
const SERVER = join(REPO_DIR, 'target/debug/examples/openwiz-server');
const REPO = 'synthetic-owner/synthetic-consumer';
const PROFILE = { metadata: 'read', contents: 'write', issues: 'write', pull_requests: 'write', checks: 'read', actions: 'read' };
const READ_ONLY = Object.fromEntries(Object.keys(PROFILE).map((k) => [k, 'read']));
const TOKEN = 'ghs_SyntheticInstallationToken0000000000000001';
const PERSONAL = 'gho_SyntheticPersonalToken00000000000000000002';

async function freePort() {
  const socket = createNetServer();
  await new Promise((resolve, reject) => { socket.once('error', reject); socket.listen(0, '127.0.0.1', resolve); });
  const port = socket.address().port;
  await new Promise((resolve) => socket.close(resolve));
  return port;
}

/** GitHub's App API, recording every request. `app` steers its answers. */
async function fakeGitHub(publicKey) {
  const app = { installations: [{ id: 2002, owner: 'synthetic-owner', permissions: PROFILE, selection: 'selected', suspended: false }],
    repositories: { 2002: [REPO] }, keyRejected: false, mint: {}, holdMint: null };
  const requests = [];
  const server = createServer((request, response) => {
    let body = '';
    request.on('data', (chunk) => { body += chunk; });
    request.on('end', async () => {
      requests.push({ method: request.method, path: request.url, headers: request.headers, body });
      const reply = (status, value) => { response.writeHead(status, { 'content-type': 'application/json' }); response.end(JSON.stringify(value)); };
      const [header, payload, signature] = (request.headers.authorization ?? '').replace(/^Bearer /, '').split('.');
      const signed = header && verify('sha256', Buffer.from(`${header}.${payload}`), publicKey, Buffer.from(signature ?? '', 'base64url'));
      if (!signed || app.keyRejected || JSON.parse(Buffer.from(payload, 'base64url')).iss !== '1001') return reply(401, { message: 'synthetic: bad credentials' });
      if (request.method === 'GET' && request.url === '/app/installations') {
        return reply(200, app.installations.map((i) => ({ id: i.id, app_id: 1001, account: { login: i.owner },
          permissions: i.permissions, repository_selection: i.selection, suspended_at: i.suspended ? '2026-11-06T00:00:00Z' : null })));
      }
      const mint = request.url.match(/^\/app\/installations\/([0-9]+)\/access_tokens$/);
      if (request.method === 'POST' && mint) {
        const installation = app.installations.find((i) => String(i.id) === mint[1]);
        if (!installation) return reply(404, { message: 'synthetic: not found' });
        const asked = JSON.parse(body);
        const name = asked.repositories?.[0];
        if (!(app.repositories[installation.id] ?? []).includes(`synthetic-owner/${name}`)) return reply(422, { message: 'synthetic: no access' });
        const granted = Object.entries(asked.permissions).every(([k, v]) => installation.permissions[k] === v || (v === 'read' && installation.permissions[k] === 'write'));
        if (!granted) return reply(422, { message: 'synthetic: permissions not granted' });
        if (app.holdMint) await app.holdMint;
        return reply(201, { ...{ token: TOKEN, expires_at: new Date(Date.now() + 3_600_000).toISOString().replace(/\.[0-9]+Z$/, 'Z'),
          permissions: asked.permissions, repository_selection: installation.selection,
          repositories: [{ full_name: `synthetic-owner/${name}` }] }, ...app.mint });
      }
      reply(404, { message: 'synthetic: unexpected route' });
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  return { app, requests, base: `http://127.0.0.1:${server.address().port}`, close: () => new Promise((resolve) => server.close(resolve)) };
}

function account(root) {
  mkdirSync(root, { mode: 0o700 });
  const state = join(root, 'state');
  // The fakes' own folder is first on PATH: its `gh` is the agent's login.
  const bin = FIXTURE;
  const runtime = join(root, 'build/runtime');
  mkdirSync(state, { mode: 0o700 });
  // The pinned packaged runtime: its build record and the briefed skills.
  for (const skill of ['setup', 'grill', 'plan-graph', 'launch-fleet']) {
    mkdirSync(join(runtime, 'skills', skill), { recursive: true });
    writeFileSync(join(runtime, 'skills', skill, 'SKILL.md'), `---\nname: ${skill}\n---\nsynthetic\n`);
  }
  writeFileSync(join(runtime, 'openwiz-build.txt'), `openwiz.package.v1\n0.0.13\n${'3'.repeat(40)}\nx86_64-unknown-linux-gnu\n`);
  // The installed build, as the collector lays it out: the setup tool in
  // runtime/setup/ and the openwiz CLI beside runtime/. Run from there, outside
  // the source tree, the tool finds both by itself.
  mkdirSync(join(runtime, 'setup'));
  for (const name of ['setup.py', 'store.py']) copyFileSync(join(SOURCES, name), join(runtime, 'setup', name));
  copyFileSync(join(FIXTURE, 'fake-openwiz'), join(root, 'build/openwiz'));
  chmodSync(join(root, 'build/openwiz'), 0o700);
  const scenario = { cloudroom: 'ok', repository: REPO, identity: 'person', settings: true,
    issue: { number: 7, state: 'open' }, threads: { thr_synthetic_answer: 'prj_synthetic' },
    harnesses: [{ harness: 'claude-code', provider: 'claude-code', models: [{ model: 'synthetic-model', efforts: ['high'] }], attachments: null, steer: null }] };
  writeFileSync(join(root, 'scenario.json'), JSON.stringify(scenario));
  return { root, state, bin, runtime, scenario, calls: join(root, 'calls.jsonl'),
    save() { writeFileSync(join(root, 'scenario.json'), JSON.stringify(this.scenario)); } };
}

function connectApp(a) {
  // A preconnected App: its key and ID as tools/github-app/setup.py saves them.
  const dir = join(a.state, 'service/app');
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  chmodSync(join(a.state, 'service'), 0o700);
  execFileSync('openssl', ['genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', join(dir, 'private-key.pem')], { stdio: 'ignore' });
  chmodSync(join(dir, 'private-key.pem'), 0o600);
  writeFileSync(join(dir, 'app.json'), '{"app_id":1001}', { mode: 0o600 });
  return readFileSync(join(dir, 'private-key.pem'), 'utf8');
}

// Asynchronous: the fake GitHub API answers from this same process.
async function tool(a, args) {
  const child = spawn('python3', ['-I', '-B', join(a.runtime, 'setup/setup.py'), ...args, '--state-dir', a.state], {
    cwd: a.root,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { PATH: `${a.bin}:/usr/bin:/bin`, HOME: a.root, GH_TOKEN: PERSONAL,
      SYNTHETIC_SCENARIO: join(a.root, 'scenario.json'), SYNTHETIC_CALLS: a.calls },
  });
  const result = { stdout: '', stderr: '' };
  child.stdout.on('data', (bytes) => { result.stdout += bytes; });
  child.stderr.on('data', (bytes) => { result.stderr += bytes; });
  const timer = setTimeout(() => child.kill('SIGKILL'), 60_000);
  result.status = await new Promise((resolve) => child.once('close', resolve));
  clearTimeout(timer);
  a.outputs = (a.outputs ?? '') + result.stdout + result.stderr;
  return result;
}

const check = (a, github) => tool(a, ['check', '--api-base', github.base]);
const prepareArgs = (a, repository = REPO) => ['prepare', '--repository', repository, '--project', 'prj_synthetic', '--operator', 'synthetic-owner',
  '--service-issue', '7', '--answer-thread', 'thr_synthetic_answer', '--harness', 'claude-code',
  '--model', 'synthetic-model', '--effort', 'high'];

async function startServer(a) {
  const port = await freePort();
  const child = spawn(SERVER, ['--web-root', OUT_DIR, '--port', String(port)], {
    env: { ...process.env, HOME: a.root, OPENWIZ_STATE_DIR: a.state, OPENWIZ_FIXTURE_PROGRAM: join(a.root, 'no-room-cli') },
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  child.stderr.resume();
  const url = `http://127.0.0.1:${port}`;
  await waitFor(() => fetch(`${url}/api/v1/setup`).then((r) => r.status === 200, () => false), { what: 'the setup server' });
  return { url, child, stop: () => { child.kill('SIGTERM'); return new Promise((resolve) => child.once('exit', resolve)); } };
}

async function report(server) {
  const body = await (await fetch(`${server.url}/api/v1/setup`)).text();
  const value = JSON.parse(body);
  return { body, value, states: Object.fromEntries(value.components.map((c) => [c.id, c.state])),
    reason: (id) => value.components.find((c) => c.id === id).reason };
}

function secretsAbsent(haystacks, key) {
  const needles = [TOKEN, PERSONAL, ...key.split('\n').filter((line) => line.length > 20 && !line.startsWith('-----'))];
  for (const [name, text] of Object.entries(haystacks)) {
    for (const needle of needles) assert.equal(text.includes(needle), false, `${name} holds a credential`);
  }
}

test('IF4/IF5: empty and preconnected consumer reach independently verified readiness; refusals cannot mark ready', async () => {
  buildBinaries();
  for (const name of ['setup.py', 'store.py']) assert.ok(existsSync(join(SOURCES, name)), `the setup tool's ${name} exists`);
  const temporary = mkdtempSync(join(tmpdir(), 'openwiz-connections-'));
  chmodSync(temporary, 0o700);
  const a = account(join(temporary, 'consumer'));
  let github = null;
  let server = null;
  const browser = await launchBrowser();
  try {
    // A plain consumer: no OpenWiz sources and no skills checkout.
    assert.deepEqual(readdirSync(join(FIXTURE, 'consumer')).sort(), ['README.md', 'docs']);
    server = await startServer(a);

    // Empty account: nothing selected, no App. CloudRoom is reused, not reconnected.
    github = await fakeGitHub(null);
    assert.equal((await check(a, github)).status, 0, a.outputs);
    let r = await report(server);
    // Review R5 (re-check): an inventory read alone never verifies CloudRoom (contracts/setup.v1.md).
    assert.deepEqual(r.states, { cloudroom: 'unknown', harness: 'missing', personal_github: 'missing',
      github_app: 'missing', project: 'missing', engine: 'missing', remote_access: 'unknown' });
    assert.equal(r.value.ready, false);
    assert.deepEqual(github.requests, [], 'no App API call without an App');
    await github.close();

    // Project settings: proposed with effects first, applied only with its own id.
    const PREPARE = prepareArgs(a);
    const preview = await tool(a, PREPARE);
    assert.equal(preview.status, 0, preview.stderr);
    const proposed = JSON.parse(preview.stdout);
    assert.equal(proposed.phase, 'proposed');
    assert.match(proposed.operation_id, /^[0-9a-f]{32}$/);
    assert.ok(proposed.effects.some((e) => /synthetic-owner\/synthetic-consumer/.test(e)), proposed.effects.join('\n'));
    r = await report(server);
    assert.deepEqual(r.value.operations.map((o) => [o.kind, o.phase]), [['prepare_project', 'proposed']]);
    assert.equal(r.states.project, 'missing', 'a proposal saves nothing');
    assert.notEqual((await tool(a, [...PREPARE, '--yes', '--operation', '0'.repeat(32)])).status, 0, 'a foreign id applies nothing');
    assert.notEqual((await tool(a, [...PREPARE.slice(0, -2), '--effort', 'low', '--yes', '--operation', proposed.operation_id])).status, 0,
      'a changed request needs a new preview');
    const applied = await tool(a, [...PREPARE, '--yes', '--operation', proposed.operation_id]);
    assert.equal(applied.status, 0, applied.stderr);
    assert.equal(JSON.parse(applied.stdout).phase, 'applied');
    // Reload/retry reuses the id and adds no second operation.
    assert.equal(JSON.parse((await tool(a, PREPARE)).stdout).operation_id, proposed.operation_id);
    assert.equal((await tool(a, [...PREPARE, '--yes', '--operation', proposed.operation_id])).status, 0);
    r = await report(server);
    assert.deepEqual(r.value.operations.map((o) => [o.kind, o.phase]), [['prepare_project', 'applied']]);
    assert.equal(r.states.project, 'unknown', 'saved settings alone are not verified');

    // Preconnected App: the check finds and verifies its installation itself.
    const key = connectApp(a);
    github = await fakeGitHub(createPublicKey(key));
    assert.equal((await check(a, github)).status, 0, a.outputs);
    r = await report(server);
    // Review R5: a catalogue listing (possibly a saved copy) never verifies a harness login.
    assert.deepEqual(r.states, { cloudroom: 'unknown', harness: 'unknown', personal_github: 'verified',
      github_app: 'verified', project: 'verified', engine: 'missing', remote_access: 'unknown' }, r.body);
    assert.equal(r.value.ready, false, 'no engine is selected, so the factory is not ready');
    assert.match(r.reason('harness'), /saved copy; that harness's login is not proven/);
    assert.match(r.reason('cloudroom'), /answered a live read, but no check here proves your CloudRoom login/);
    const state = JSON.parse(readFileSync(join(a.state, 'setup/state.json'), 'utf8'));
    assert.deepEqual(state.app, { app_id: 1001, installation_id: 2002 }, 'the installation id is captured');
    const mints = github.requests.filter((q) => q.method === 'POST');
    assert.equal(mints.length, 1);
    assert.deepEqual(JSON.parse(mints[0].body), { repositories: ['synthetic-consumer'], permissions: PROFILE });
    assert.ok(github.requests.every((q) => !JSON.stringify(q).includes(PERSONAL)), 'no personal token reaches the App API');

    // The page shows the same independent states at phone and desktop widths.
    for (const viewport of [PHONE, DESKTOP]) {
      const p = await openPage(browser, server.url, { viewport, path: '/setup' });
      try {
        await p.page.locator('[data-setup-ready="true"]').waitFor();
        for (const [id, value] of Object.entries(r.states)) {
          assert.equal(await p.page.locator(`[data-setup-component="${id}"] .setup-state`).innerText(), value);
        }
        await p.page.locator('[data-setup-component="github_app"] summary').click();
        assert.match(await p.page.locator('[data-setup-component="github_app"]').innerText(), /selected repositor/);
        mkdirSync(RESULTS_DIR, { recursive: true });
        await p.page.screenshot({ path: join(RESULTS_DIR, `install-connections-${viewport.width}.png`), fullPage: true });
        const bounds = await p.page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: innerWidth }));
        assert.ok(bounds.width <= bounds.viewport, JSON.stringify(bounds));
        assert.deepEqual(p.errors, []);
        assert.ok(p.requests.filter((q) => new URL(q.url).pathname.startsWith('/api/')).every((q) =>
          q.method === 'GET' && new URL(q.url).pathname === '/api/v1/setup'), 'the page makes no write');
        secretsAbsent({ page: await p.page.content() }, key);
      } finally { await p.context.close(); }
    }

    // Each refusal is independent and cannot mark anything ready.
    const refusals = [
      ['read-only App', () => { github.app.installations[0].permissions = READ_ONLY; }, 'github_app', 'refused', /write/],
      ['all repositories', () => { github.app.installations[0].selection = 'all'; }, 'github_app', 'refused', /only selected/],
      ['wrong repository', () => { github.app.repositories[2002] = ['synthetic-owner/another-repo']; }, 'github_app', 'refused', /selected repository/],
      ['revoked installation', () => { github.app.installations = []; }, 'github_app', 'refused', /removed or revoked/],
      ['suspended installation', () => { github.app.installations[0].suspended = true; }, 'github_app', 'refused', /suspended/],
      ['rejected or expired key', () => { github.app.keyRejected = true; }, 'github_app', 'refused', /key/],
      ['unavailable model', () => { a.scenario.harnesses[0].models = [{ model: 'other-model', efforts: ['high'] }]; }, 'harness', 'refused', /does not offer/],
      ['bot agent identity', () => { a.scenario.identity = 'bot'; }, 'personal_github', 'refused', /App or bot/],
      ['identity without push', () => { a.scenario.identity = 'read_only'; }, 'personal_github', 'refused', /cannot push/],
      ['signed-out identity', () => { a.scenario.identity = 'signed_out'; }, 'personal_github', 'missing', /No GitHub login/],
      ['closed service issue', () => { a.scenario.issue.state = 'closed'; }, 'project', 'refused', /service record issue/],
      ['no fleet settings', () => { a.scenario.settings = false; }, 'project', 'missing', /setup skill/],
      ['answer target elsewhere', () => { a.scenario.threads = { thr_synthetic_answer: 'prj_syn_other' }; }, 'project', 'refused', /answer target/],
      ['CloudRoom unreadable', () => { a.scenario.cloudroom = 'down'; }, 'cloudroom', 'unknown', /could not be read/],
      // Review R5: a partial inventory (a supporting read failed) proves no connection.
      ['partial CloudRoom read', () => { a.scenario.cloudroom = 'partial'; }, 'cloudroom', 'unknown', /only in part/],
      // Review R2: headings alone, or the setup skill's unfilled template, are not settings.
      ['empty fleet settings', () => { a.scenario.settings = 'empty'; }, 'project', 'missing', /setup skill/],
      ['unfilled settings template', () => { a.scenario.settings = 'template'; }, 'project', 'missing', /setup skill/],
      // Review R2 (re-check): merge-table scaffolding is no rule; every builder table counts.
      ['merge table without a rule', () => { a.scenario.settings = 'merge-scaffold'; }, 'project', 'missing', /setup skill/],
      ['unfilled small-ticket builder', () => { a.scenario.settings = 'small-builder'; }, 'project', 'missing', /setup skill/],
      // Security R1: a token answer is proof only with a usable token and a current expiry.
      ['mint without token', () => { github.app.mint = { token: undefined }; }, 'github_app', 'unknown', /token answer/],
      ['empty token', () => { github.app.mint = { token: '' }; }, 'github_app', 'unknown', /token answer/],
      ['malformed token', () => { github.app.mint = { token: 'not a token!' }; }, 'github_app', 'unknown', /token answer/],
      ['mint without expiry', () => { github.app.mint = { expires_at: undefined }; }, 'github_app', 'unknown', /token answer/],
      ['expired token', () => { github.app.mint = { expires_at: '2020-01-01T00:00:00Z' }; }, 'github_app', 'unknown', /token answer/],
      ['implausible expiry', () => { github.app.mint = { expires_at: '2099-01-01T00:00:00Z' }; }, 'github_app', 'unknown', /token answer/],
      ['malformed expiry', () => { github.app.mint = { expires_at: '2026-13-01T00:00:00Z' }; }, 'github_app', 'unknown', /token answer/],
    ];
    const baseline = JSON.stringify(github.app);
    const scenario = JSON.stringify(a.scenario);
    for (const [name, change, component, expected, reason] of refusals) {
      github.app = Object.assign(github.app, JSON.parse(baseline));
      a.scenario = JSON.parse(scenario);
      change();
      a.save();
      assert.equal((await check(a, github)).status, 0, `${name}: ${a.outputs}`);
      r = await report(server);
      assert.equal(r.states[component], expected, `${name}: ${r.body}`);
      assert.match(r.reason(component), reason, name);
      assert.equal(r.value.ready, false, name);
      for (const other of ['cloudroom', 'harness', 'personal_github', 'github_app', 'project']) {
        // gh is also how project settings are read, and openwiz how harnesses are.
        const shared = { 'CloudRoom unreadable': ['harness', 'project'], 'signed-out identity': ['project'] }[name] ?? [];
        if (other !== component && !shared.includes(other)) {
          assert.equal(r.states[other], ['harness', 'cloudroom'].includes(other) ? 'unknown' : 'verified', `${name} leaves ${other} independent`);
        }
      }
    }

    // Security R2: a local key failure replaces an earlier verified result.
    github.app = Object.assign(github.app, JSON.parse(baseline));
    a.scenario = JSON.parse(scenario);
    a.save();
    const pem = join(a.state, 'service/app/private-key.pem');
    for (const [name, broken, restore] of [
      ['unsafe key', () => chmodSync(pem, 0o644), () => chmodSync(pem, 0o600)],
      ['missing key', () => renameSync(pem, `${pem}.away`), () => renameSync(`${pem}.away`, pem)],
    ]) {
      assert.equal((await check(a, github)).status, 0, a.outputs);
      assert.equal((await report(server)).states.github_app, 'verified', name);
      broken();
      assert.equal((await check(a, github)).status, 0, `${name}: ${a.outputs}`);
      r = await report(server);
      assert.equal(r.states.github_app, 'refused', `${name}: ${r.body}`);
      assert.match(r.reason('github_app'), /key/, name);
      for (const other of ['personal_github', 'project']) assert.equal(r.states[other], 'verified', `${name} leaves ${other}`);
      assert.equal(r.states.harness, 'unknown', `${name} leaves the harness`);
      assert.equal(r.states.cloudroom, 'unknown', `${name} leaves CloudRoom`);
      restore();
    }

    // Security R3: an older check finishing last never overwrites a newer result.
    let release;
    github.app.holdMint = new Promise((resolve) => { release = resolve; });
    const posted = github.requests.filter((q) => q.method === 'POST').length;
    const older = check(a, github);
    await waitFor(() => github.requests.filter((q) => q.method === 'POST').length === posted + 1, { what: "the older check's held token request" });
    github.app.holdMint = null;
    github.app.keyRejected = true;
    assert.equal((await check(a, github)).status, 0, a.outputs);
    assert.equal((await report(server)).states.github_app, 'refused');
    release();
    const late = await older;
    assert.equal(late.status, 7, `the superseded check saves nothing: ${late.stdout}${late.stderr}`);
    r = await report(server);
    assert.equal(r.states.github_app, 'refused', r.body);
    assert.match(r.reason('github_app'), /rejected the App's key/);
    github.app.keyRejected = false;

    // Reconnect: a new installation after revocation is captured; nothing is duplicated.
    github.app = Object.assign(github.app, JSON.parse(baseline));
    github.app.installations[0].id = 3003;
    github.app.repositories = { 3003: [REPO] };
    a.scenario = JSON.parse(scenario);
    a.save();
    assert.equal((await check(a, github)).status, 0, a.outputs);
    r = await report(server);
    assert.equal(r.states.github_app, 'verified', r.body);
    assert.deepEqual(JSON.parse(readFileSync(join(a.state, 'setup/state.json'), 'utf8')).app, { app_id: 1001, installation_id: 3003 });
    assert.equal(r.value.operations.length, 1);
    assert.ok(github.requests.every((q) => q.method === 'GET' || /\/access_tokens$/.test(q.path)), 'only reads and token mints');

    // A changed selection makes earlier evidence stale until it is checked again.
    const reselect = prepareArgs(a, 'synthetic-owner/another-repo');
    const other = await tool(a, reselect);
    assert.equal((await tool(a, [...reselect, '--yes', '--operation', JSON.parse(other.stdout).operation_id])).status, 0);
    r = await report(server);
    for (const id of ['cloudroom', 'harness', 'personal_github', 'github_app', 'project']) assert.equal(r.states[id], 'unknown', `${id} after reselection`);

    // Review R1: returning to an earlier selection is a new, explicit proposal.
    const back = await tool(a, PREPARE);
    assert.equal(back.status, 0, back.stderr);
    const returning = JSON.parse(back.stdout);
    assert.equal(returning.phase, 'proposed');
    assert.notEqual(returning.operation_id, proposed.operation_id);
    const stale = await tool(a, [...PREPARE, '--yes', '--operation', proposed.operation_id]);
    assert.notEqual(stale.status, 0, 'the old applied operation never reports the newer selection as done');
    assert.match(stale.stderr, /selection has changed/);
    assert.equal(JSON.parse(readFileSync(join(a.state, 'setup/state.json'), 'utf8')).project.repository, 'synthetic-owner/another-repo');
    assert.equal((await tool(a, [...PREPARE, '--yes', '--operation', returning.operation_id])).status, 0);
    assert.equal(JSON.parse(readFileSync(join(a.state, 'setup/state.json'), 'utf8')).project.repository, REPO);

    // Credential privacy: output, state, server body and every recorded argument.
    const files = {};
    for (const name of readdirSync(join(a.state, 'setup'))) files[`setup/${name}`] = readFileSync(join(a.state, 'setup', name), 'utf8');
    secretsAbsent({ outputs: a.outputs, calls: readFileSync(a.calls, 'utf8'), report: r.body, ...files,
      requests: JSON.stringify(github.requests.map((q) => ({ ...q, headers: { ...q.headers, authorization: '' } }))) }, key);
    assert.ok(readFileSync(a.calls, 'utf8').split('\n').filter(Boolean).every((line) => {
      const argv = JSON.parse(line);
      return ['gh', 'openwiz'].includes(argv[0]) && !argv.some((arg) => /BEGIN|token|Bearer/i.test(arg));
    }), 'only read arguments');
  } finally {
    await browser.close();
    if (github) await github.close().catch(() => {});
    if (server) await server.stop();
    rmSync(temporary, { recursive: true, force: true });
  }
});
