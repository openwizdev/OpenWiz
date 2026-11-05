// #2039: the actual installed service (the test-only `fixture-service`
// example's real dispatch) for the browser journey. Readers are the fake gh
// and room-cli; delivery is the example's recording boundary. The decisions,
// grill and config fixtures are shared with tests/notifications/journey.rs.
// Synthetic only; nothing leaves the machine.
import { execFileSync, spawn } from 'node:child_process';
import { copyFileSync, chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { request } from 'node:http';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { REPO_DIR } from '../../support/paths.mjs';

const SHARED = `${REPO_DIR}/tests/fixtures/notifications/journey`;
const TARGET = `${REPO_DIR}/target/debug`;
export const HOST = 'openwiz.example.com';
// Independently computed literal (the e11 decisions fixtures), not by the code.
export const CURRENT = '941019e2a769a93d10140f9924b4ce021a041c21f74cd72514a9f51306ad1aa4';
const GUARDS = { Origin: `https://${HOST}`, 'Sec-Fetch-Site': 'same-origin', 'X-OpenWiz-Send': '1', 'Content-Type': 'application/json' };

/** One fenced JSON block of the shared fixture README, by its info string. */
function fixture(name) {
  const readme = readFileSync(join(SHARED, 'README.md'), 'utf8');
  const start = '```json ' + name + '\n';
  const rest = readme.slice(readme.indexOf(start) + start.length);
  return rest.slice(0, rest.indexOf('\n```'));
}

let built = false;
function build() {
  if (built) return;
  for (const args of [['-p', 'openwiz-tests', '--bin', 'fake-room-cli', '--bin', 'fake-gh'], ['-p', 'openwiz-service', '--example', 'fixture-service']]) {
    execFileSync('cargo', ['build', '-q', ...args], { cwd: REPO_DIR, stdio: 'inherit' });
  }
  built = true;
}

function decisions(fingerprint) {
  const scenario = JSON.parse(fixture('journey-gh'));
  const record = { schema: 'openwiz.decisions.v1', kind: 'grill_round', id: 'synthetic-current', status: 'open', fingerprint, risk: 'ordinary',
    grill_file: 'docs/grills/synthetic-choice.md', round: 1,
    questions: [{ id: 'G1', decides: 'Synthetic choice?', context: 'Exact context 合成.', recommendation: 'Keep spaces. ' }], answered: [] };
  const rows = [{ id: 1001, body: `Synthetic prose.\n\`\`\`json\n${JSON.stringify(record)}\n\`\`\`\n`,
    issue_url: 'https://api.github.com/repos/synthetic-owner/synthetic-repo/issues/901', created_at: '1970-01-01T00:00:01Z', updated_at: '1970-01-01T00:00:02Z' }];
  for (const size of [1, 100]) {
    scenario.responses.push({ argv: ['api', '--include', `repos/{owner}/{repo}/issues/comments?per_page=${size}&sort=created&direction=desc&page=1`, '--jq', '[.[] | {id,body,issue_url,created_at,updated_at}]'],
      stdout: `HTTP/2.0 200 OK\r\n\r\n${JSON.stringify(rows)}` });
  }
  return scenario;
}

async function freePort() {
  const server = createServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  await new Promise((resolve) => server.close(resolve));
  return port;
}

function call(port, method, path, body = '') {
  return new Promise((resolve, reject) => {
    const req = request({ host: '127.0.0.1', port, method, path, headers: { Host: HOST, ...(body ? { ...GUARDS, 'Content-Length': Buffer.byteLength(body) } : {}) } }, (res) => {
      let text = '';
      res.on('data', (c) => { text += c; });
      res.on('end', () => resolve({ status: res.statusCode, text }));
    });
    req.on('error', reject);
    req.end(body);
  });
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(what, ready) {
  const limit = Date.now() + 60_000;
  for (;;) {
    const value = await ready();
    if (value) return value;
    if (Date.now() > limit) throw new Error(`timed out waiting for ${what}`);
    await wait(50);
  }
}

/** Starts the installed service, opts in through its real API and waits for the one recorded alert. */
export async function journeyService() {
  build();
  const root = mkdtempSync(join(tmpdir(), 'ow-web-journey-'));
  for (const dir of ['service', 'build/web', 'tools', 'journey']) mkdirSync(join(root, dir), { recursive: true, mode: 0o700 });
  writeFileSync(join(root, 'build/web/index.html'), '<html>synthetic</html>', { mode: 0o600 });
  copyFileSync(`${TARGET}/examples/fixture-service`, join(root, 'build/openwiz-service'));
  chmodSync(join(root, 'build/openwiz-service'), 0o700);
  symlinkSync(`${TARGET}/fake-room-cli`, join(root, 'tools/room-cli'));
  symlinkSync(`${TARGET}/fake-gh`, join(root, 'tools/gh'));
  writeFileSync(join(root, 'tools/fake-room-cli.scenario'), `${REPO_DIR}/tests/fixtures/room-cli-0.43.1/send/scenario.json`, { mode: 0o600 });
  writeFileSync(join(root, 'gh-scenario.json'), JSON.stringify(decisions(CURRENT)), { mode: 0o600 });
  writeFileSync(join(root, 'tools/fake-gh.scenario'), join(root, 'gh-scenario.json'), { mode: 0o600 });
  const port = await freePort();
  const config = JSON.parse(fixture('journey-config'));
  config.server.port = port;
  writeFileSync(join(root, 'service/config.json'), JSON.stringify(config), { mode: 0o600 });
  const child = spawn(join(root, 'build/openwiz-service'), [], {
    cwd: join(root, 'tools'),
    env: { OPENWIZ_STATE_DIR: root, HOME: root, PATH: `${join(root, 'tools')}:/usr/bin:/bin`,
      OPENWIZ_FIXTURE_PROGRAM: join(root, 'tools/room-cli'), OPENWIZ_FIXTURE_NOTIFICATION_JOURNEY: join(root, 'journey') },
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  let stderr = '';
  child.stderr.on('data', (c) => { stderr += c; });
  const exited = new Promise((resolve) => child.on('exit', resolve));
  const service = {
    port,
    allowedHost: HOST,
    stderr: () => stderr,
    call: (method, path, body) => call(port, method, path, body),
    submissions: () => (existsSync(join(root, 'journey/submissions.log')) ? readFileSync(join(root, 'journey/submissions.log'), 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l)) : []),
    tells: () => (existsSync(join(root, 'tools/tell-calls.count')) ? Number(readFileSync(join(root, 'tools/tell-calls.count'), 'utf8').trim()) : 0),
    async stop() {
      child.kill('SIGKILL');
      await exited;
      rmSync(root, { recursive: true, force: true });
    },
  };
  try {
    // The store exists after the first pass; a pass holds it briefly (503, Retry-After).
    await until('the installed notification store', async () => (await call(port, 'GET', '/api/v1/notifications/status').catch(() => ({ status: 0 }))).status === 200);
    const put = (path, body) => until(`${path} admitted`, async () => { const r = await call(port, 'PUT', path, body); return r.status === 503 ? null : r; });
    const doc = (record) => JSON.stringify({ schema: 'openwiz.notifications.v1', record });
    const categories = { decision: true, recovery_escalation: true };
    for (const name of ['ci_failed', 'review_findings', 're_check', 'merge', 'agent_complete', 'ready_stock_changed', 'loop_missed', 'loop_stuck', 'loop_disabled', 'loop_run_changed', 'recovery_changed', 'service_update', 'contract_changed', 'fleet_wait_changed']) categories[name] = false;
    const pref = await put('/api/v1/notifications/preferences', doc({ preference_write: { operation_id: '1'.repeat(32), expected_generation: 0, enabled: true, categories } }));
    if (pref.status !== 200) throw new Error(`preferences: ${pref.status} ${pref.text}`);
    const sub = await put('/api/v1/notifications/subscription', doc({ subscription_write: { operation_id: '2'.repeat(32), expected_generation: 0, binding_id: 'synthetic-binding' } }));
    if (sub.status !== 200) throw new Error(`subscription: ${sub.status} ${sub.text}`);
    const [first] = await until('one recorded alert', () => service.submissions().length > 0 && service.submissions());
    service.token = first.payload.target_token;
    return service;
  } catch (error) {
    await service.stop();
    throw new Error(`${error.message}\n${stderr}`);
  }
}
