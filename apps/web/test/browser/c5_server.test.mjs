// C5 HTTP target verification, against the real server and recorded fakes.
// Every environment and scenario is private to this child server.
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { get } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { before, test } from 'node:test';

import { REPO_DIR, SCENARIOS_DIR } from '../support/paths.mjs';

const TARGET = 'thr_syn_0001';
before(() => execFileSync('cargo', ['build', '-q', '-p', 'openwiz-tests', '--example', 'openwiz-server', '--bin', 'fake-room-cli', '--bin', 'fake-gh'], { cwd: REPO_DIR, stdio: 'inherit' }));

async function server(target, response = { stdout: JSON.stringify({ thread: { id: TARGET, archivedAt: null } }) }) {
  const dir = mkdtempSync(join(tmpdir(), 'openwiz-c5-'));
  symlinkSync(`${REPO_DIR}/target/debug/fake-room-cli`, join(dir, 'room-cli'));
  symlinkSync(`${REPO_DIR}/target/debug/fake-gh`, join(dir, 'gh'));
  const gh = join(dir, 'gh.json');
  const issue = { blockedBy: { nodes: [], totalCount: 0 }, body: 'Synthetic spec', closedByPullRequestsReferences: [], comments: [], labels: [], milestone: null, state: 'OPEN', subIssues: { nodes: [], totalCount: 0 }, title: 'Synthetic spec' };
  writeFileSync(gh, JSON.stringify({ extends: `${REPO_DIR}/tests/fixtures/github/fleets/complete`, synthetic_assumptions: ['Synthetic empty detail spec.'], responses: [
    { argv: ['issue', 'list', '--state', 'all', '--limit', '1000', '--json', 'blockedBy,body,id,labels,milestone,number,state,subIssues,title'], stdout: '[]' },
    { argv: ['repo', 'view', '--json', 'nameWithOwner,url'], stdout: JSON.stringify({ nameWithOwner: 'syn-owner/syn-example-repo', url: 'https://github.com/syn-owner/syn-example-repo' }) },
    { argv: ['issue', 'view', '901', '--json', 'blockedBy,body,closedByPullRequestsReferences,comments,labels,milestone,state,subIssues,title'], stdout: JSON.stringify(issue) },
  ] }));
  writeFileSync(join(dir, 'fake-gh.scenario'), gh);
  const room = join(dir, 'room.json');
  writeFileSync(room, JSON.stringify({ extends: join(SCENARIOS_DIR, 'normal'), synthetic_assumptions: ['Synthetic target verification response.'], responses: [{ argv: ['thread', 'show', TARGET, '--json'], ...response }] }));
  writeFileSync(join(dir, 'fake-room-cli.scenario'), room);
  const env = { PATH: `${dir}:/usr/bin:/bin`, OPENWIZ_FIXTURE_PROGRAM: join(dir, 'room-cli'), HOME: dir, OPENWIZ_STATE_DIR: join(dir, 'unused-state') };
  if (target !== undefined) env.OPENWIZ_ORCHESTRATOR_THREAD_ID = target;
  const child = spawn(`${REPO_DIR}/target/debug/examples/openwiz-server`, ['--port', '0'], { cwd: dir, env, stdio: ['ignore', 'ignore', 'pipe'] });
  let stderr = '';
  try {
    const port = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('C5 server failed to listen')), 15_000);
      child.stderr.on('data', (chunk) => {
        stderr += chunk;
        const match = /listening on http:\/\/127\.0\.0\.1:(\d+)/.exec(stderr);
        if (match) { clearTimeout(timeout); resolve(Number(match[1])); }
      });
      child.on('error', (e) => { clearTimeout(timeout); reject(e); });
      child.on('exit', () => { clearTimeout(timeout); reject(new Error(stderr)); });
    });
    return { dir, port, log: () => stderr, calls: () => existsSync(join(dir, 'invocations.log')) ? readFileSync(join(dir, 'invocations.log'), 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [], close: async () => {
      if (child.exitCode === null) { child.kill('SIGTERM'); await new Promise((resolve) => child.once('exit', resolve)); }
      rmSync(dir, { recursive: true, force: true });
    } };
  } catch (e) {
    child.kill('SIGTERM');
    await new Promise((resolve) => child.exitCode !== null ? resolve() : child.once('exit', resolve));
    rmSync(dir, { recursive: true, force: true });
    throw e;
  }
}
function request(port, path) {
  return new Promise((resolve, reject) => {
    get({ hostname: '127.0.0.1', port, path }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (s) => { body += s; });
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body, doc: JSON.parse(body) }));
    }).on('error', reject);
  });
}

test('C5: both HTTP fleet views expose only the configured, positively verified target', async () => {
  const fx = await server(TARGET);
  try {
    for (const path of ['/api/v1/fleets', '/api/v1/fleets/901']) {
      const r = await request(fx.port, path);
      assert.equal(r.status, 200, r.body);
      assert.equal(r.doc.orchestrator, TARGET);
      assert.equal(r.headers['cache-control'], 'no-store');
      assert.equal(r.doc.data.view, path.endsWith('/901') ? 'fleet' : 'fleets');
    }
    // With no in-flight request left, the fake's synchronous invocation log
    // is final: every read below completed before its response was consumed.
    assert.equal(fx.calls().filter((a) => a.join(' ') === `thread show ${TARGET} --json`).length, 2);
    assert.ok(fx.calls().every((a) => !a.includes('tell') && !a.includes('spawn')));
    assert.equal(existsSync(join(fx.dir, 'unused-state')), false);
  } finally { await fx.close(); }
});

test('C5: unset, invalid, absent, malformed, mismatched and failed targets are omitted, never guessed or echoed', async () => {
  const cases = [
    [undefined, null, false], ['', null, false], ['--bad', null, false], ['synthetic/private', null, false], ['syné', null, false],
    [TARGET, { stdout: '{}' }, true],
    [TARGET, { stdout: '{"thread":{}}' }, true],
    [TARGET, { stdout: '{"thread":{"id":null}}' }, true],
    [TARGET, { stdout: '{"thread":{"id":"thr_syn_0002"}}' }, true],
    [TARGET, { stdout: 'not JSON' }, true],
    [TARGET, { exit: 1, stderr: 'Error: HTTP 404: Thread not found\n' }, true],
    [TARGET, { exit: 1, stderr: 'SYNTHETIC_PRIVATE_DIAGNOSTIC\n' }, true],
  ];
  for (const [id, response, shouldRead] of cases) {
    const fx = await server(id, response ?? undefined);
    try {
      const r = await request(fx.port, '/api/v1/fleets');
      assert.equal(r.status, 200, r.body);
      assert.equal(Object.hasOwn(r.doc, 'orchestrator'), false, JSON.stringify(id));
      assert.equal(fx.calls().some((a) => a[0] === 'thread' && a[1] === 'show'), shouldRead);
      assert.equal((r.body + fx.log()).includes('SYNTHETIC_PRIVATE_DIAGNOSTIC'), false);
      assert.equal(existsSync(join(fx.dir, 'unused-state')), false);
    } finally { await fx.close(); }
  }
});
