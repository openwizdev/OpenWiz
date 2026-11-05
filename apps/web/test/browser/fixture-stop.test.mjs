// #1308: stop() ends everything the fixture server started before it
// removes the server's directory. A fake room-cli still answering a read
// when the server stops writes beside its argv[0] in that directory, and
// the removal failed with ENOTEMPTY (V1's teardown, CI runs 41784650835 and
// 41997156155). No browser; synthetic responses only.

import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import { startFixtureServer } from '../support/rust.mjs';

/** A session id no other test asks for, so its fake is this test's own. */
const ID = `thr_syn_1308_${process.pid}`;

/** Each running fake room-cli asked to show ID, read from /proc. */
function fakesShowingId() {
  const found = [];
  for (const pid of readdirSync('/proc')) {
    if (!/^\d+$/.test(pid)) continue;
    let argv;
    try {
      argv = readFileSync(`/proc/${pid}/cmdline`, 'utf8').split('\0');
      const stat = readFileSync(`/proc/${pid}/stat`, 'utf8');
      // "pid (comm) state ...": an exited, unreaped fake (Z) writes nothing.
      if (stat[stat.lastIndexOf(')') + 2] === 'Z') continue;
    } catch {
      continue;
    }
    if (argv[0].endsWith('/room-cli') && argv.includes(ID)) found.push(`${pid}: ${argv.join(' ')}`);
  }
  return found;
}

test('stop() leaves no fake running and no directory, with a read still in flight', async () => {
  // The fake logs the call, then waits 5 s before it answers: still running at stop().
  const server = await startFixtureServer('normal', {
    responses: [{ argv: ['thread', 'show', ID, '--json'], stdout: '{}', delay_ms: 5_000 }],
  });
  const reply = fetch(`http://127.0.0.1:${server.port}/api/v1/sessions/${ID}`).catch((e) => e);
  const until = Date.now() + 10_000;
  while (!server.invocations().some((argv) => argv.includes(ID))) {
    assert.ok(Date.now() < until, `the fake never started: ${server.log()}`);
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  assert.equal(fakesShowingId().length, 1, 'the fake is running before stop()');
  await server.stop();
  assert.deepEqual(fakesShowingId(), [], 'a fake the server started outlived stop()');
  assert.deepEqual(server.invocations(), [], 'its directory is gone');
  await reply;
});

/** Each /proc entry as [pid, state, ppid, pgrp]; zombies included. */
function processes() {
  const found = [];
  for (const pid of readdirSync('/proc')) {
    if (!/^\d+$/.test(pid)) continue;
    let stat;
    try {
      stat = readFileSync(`/proc/${pid}/stat`, 'utf8');
    } catch {
      continue;
    }
    // "pid (comm) state ppid pgrp ...": comm may hold spaces or parentheses.
    const [state, ppid, pgrp] = stat.slice(stat.lastIndexOf(')') + 2).split(' ');
    found.push([Number(pid), state, Number(ppid), Number(pgrp)]);
  }
  return found;
}

/** The running (not zombie) members of process group `pgid`. */
const running = (pgid) => processes().filter(([, state, , pgrp]) => pgrp === pgid && state !== 'Z');

// R2 on #1369: the server is in its own process group, so the terminal's
// Ctrl+C (SIGINT to the test's group) no longer reaches it, and a test's
// `finally` never runs on a default SIGINT exit. An interrupted test
// process must still end its fixture servers, and still end by its signal.
for (const signal of ['SIGINT', 'SIGTERM']) {
  test(`a test process ended by ${signal} ends its fixture server and still ends by ${signal}`, async () => {
    const rust = new URL('../support/rust.mjs', import.meta.url).href;
    const script = `import { startFixtureServer } from ${JSON.stringify(rust)};
await startFixtureServer('normal');
process.stdout.write('ready\\n');
setInterval(() => {}, 1_000);`;
    // Its own group, as a terminal's foreground job is: the signal goes to the
    // group. Its own temporary directory, which the interrupted run can't remove.
    const tmp = mkdtempSync(join(tmpdir(), 'openwiz-fixture-stop-'));
    const run = spawn(process.execPath, ['--input-type=module', '-e', script], {
      detached: true,
      stdio: ['ignore', 'pipe', 'inherit'],
      env: { ...process.env, TMPDIR: tmp },
    });
    const exited = new Promise((resolve) => run.on('exit', (code, signal) => resolve({ code, signal })));
    let server;
    try {
      await new Promise((resolve, reject) => {
        let out = '';
        run.stdout.on('data', (chunk) => {
          out += chunk;
          if (out.includes('ready')) resolve();
        });
        exited.then((e) => reject(new Error(`the test process ended first: ${JSON.stringify(e)}`)));
      });
      const servers = processes().filter(([, state, ppid]) => ppid === run.pid && state !== 'Z');
      assert.equal(servers.length, 1, 'the test process started one server');
      server = servers[0][0];
      process.kill(-run.pid, signal);
      assert.deepEqual(await exited, { code: null, signal }, `the test process still ends by ${signal}`);
      const until = Date.now() + 5_000;
      while (running(server).length > 0 && Date.now() < until) await new Promise((resolve) => setTimeout(resolve, 10));
      assert.deepEqual(running(server), [], 'the fixture server, or a fake it started, outlived the test process');
    } finally {
      for (const pgid of [run.pid, server]) {
        try {
          if (pgid) process.kill(-pgid, 'SIGKILL');
        } catch {
          // Already gone.
        }
      }
      const until = Date.now() + 5_000;
      while (server && running(server).length > 0 && Date.now() < until) await new Promise((resolve) => setTimeout(resolve, 10));
      rmSync(tmp, { recursive: true, force: true });
    }
  });
}
