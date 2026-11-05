// Ticket 1's openwiz-server, run over one of 0.0.1's fixture scenarios with
// a verified isolated bundle around the repository's fake room-cli, using
// the exact production dispatch. Synthetic data only.

import { execFileSync, spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { REPO_DIR, SCENARIOS_DIR } from './paths.mjs';

const SERVER = `${REPO_DIR}/target/debug/examples/openwiz-server`;
const FAKE = `${REPO_DIR}/target/debug/fake-room-cli`;

let built = false;

/** Builds the server and the fake once per test process (a no-op when current). */
export function buildBinaries() {
  if (built) return;
  execFileSync('cargo', ['build', '-q', '-p', 'openwiz-tests', '--example', 'openwiz-server', '--bin', 'fake-room-cli'], {
    cwd: REPO_DIR,
    stdio: 'inherit',
  });
  built = true;
}

/** Every 0.0.1 scenario that has a scenario.json. */
export function scenarios() {
  return readdirSync(SCENARIOS_DIR)
    .filter((name) => existsSync(join(SCENARIOS_DIR, name, 'scenario.json')))
    .sort();
}

/**
 * Starts openwiz-server on a free loopback port over `scenario`. With
 * `allowedHost` (#9 step 3), it also takes that host name, which is what lets
 * it send; its send record is a private directory.
 */
export async function startFixtureServer(scenario, { allowedHost = null, responses = null } = {}) {
  buildBinaries();
  const dir = mkdtempSync(join(tmpdir(), 'openwiz-web-'));
  symlinkSync(FAKE, join(dir, 'room-cli'));
  let file = join(SCENARIOS_DIR, scenario, 'scenario.json');
  if (responses) {
    // The test's own responses, tried before `scenario`'s, as tests/messaging's override does. Synthetic.
    mkdirSync(join(dir, 'own'));
    file = join(dir, 'own', 'scenario.json');
    const own = { scenario: 'own', description: 'A test’s own responses.', extends: join(SCENARIOS_DIR, scenario), synthetic_assumptions: ['Written by the test.'], responses };
    writeFileSync(file, JSON.stringify(own, null, 2));
  }
  writeFileSync(join(dir, 'fake-room-cli.scenario'), file);
  const args = ['--port', '0', ...(allowedHost ? ['--allowed-host', allowedHost] : [])];
  const child = spawn(SERVER, args, {
    cwd: dir,
    env: { PATH: '/usr/bin:/bin', OPENWIZ_FIXTURE_PROGRAM: join(dir, 'room-cli'), HOME: dir, OPENWIZ_STATE_DIR: join(dir, 'state') },
    stdio: ['ignore', 'ignore', 'pipe'],
    // Its own process group, with every fake room-cli it starts, so stop()
    // can end them all (#1308).
    detached: true,
  });
  // Out of the test's group, Ctrl+C no longer reaches it: end it if this
  // process ends first, from now on, startup included (R2 on #1369).
  if (child.pid !== undefined) track(child.pid);
  let stderr = '';
  const port = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`openwiz-server did not start: ${stderr}`)), 15_000);
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
      const m = /listening on http:\/\/127\.0\.0\.1:(\d+)/.exec(stderr);
      if (m) {
        clearTimeout(timer);
        resolve(Number(m[1]));
      }
    });
    child.on('exit', (code) => reject(new Error(`openwiz-server exited ${code}: ${stderr}`)));
  });
  return {
    port,
    /** The fake's invocations, one argument list per call. */
    invocations: () => {
      const file = join(dir, 'invocations.log');
      return existsSync(file) ? readFileSync(file, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l)) : [];
    },
    log: () => stderr,
    stop: async () => {
      // The server and everything it started, a hanging fake too. Each fake
      // writes beside its argv[0], in dir: one still answering a read made
      // the removal below fail with ENOTEMPTY (#1308).
      signalGroup(child.pid, 'SIGTERM');
      await new Promise((resolve) => (child.exitCode !== null || child.signalCode !== null ? resolve() : child.on('exit', resolve)));
      signalGroup(child.pid, 'SIGKILL');
      await groupGone(child.pid);
      active.delete(child.pid);
      rmSync(dir, { recursive: true, force: true });
      rmSync(`${dir}.fixture-bundles`, { recursive: true, force: true });
    },
  };
}

/** The process groups of the fixture servers started and not yet stopped. */
const active = new Set();
const SIGNALS = ['SIGINT', 'SIGTERM', 'SIGHUP'];

/** Adds `pgid` to `active`, and ends every active group if this process ends first. */
function track(pgid) {
  if (!process.listeners('exit').includes(endActive)) {
    process.on('exit', endActive);
    for (const signal of SIGNALS) process.on(signal, onSignal);
  }
  active.add(pgid);
}

/** Kills every active group, at once (an exit listener can't wait). */
function endActive() {
  for (const pgid of active) signalGroup(pgid, 'SIGKILL');
  active.clear();
}

/**
 * A signal that would have ended this process: end the active groups, then,
 * when no other listener handles it, end by it as before (its exit status).
 */
function onSignal(signal) {
  endActive();
  if (process.listenerCount(signal) > 1) return;
  process.removeListener('exit', endActive);
  for (const s of SIGNALS) process.removeListener(s, onSignal);
  process.kill(process.pid, signal);
}

/** Sends `signal` to process group `pgid`, unless no member is left. */
function signalGroup(pgid, signal) {
  try {
    process.kill(-pgid, signal);
  } catch (e) {
    if (e.code !== 'ESRCH') throw e;
  }
}

/**
 * Resolves once process group `pgid` has no running member, from /proc. A
 * member that has exited but is not yet reaped (state Z) writes nothing, so
 * it counts as gone. Fails after 10 s.
 */
async function groupGone(pgid) {
  const until = Date.now() + 10_000;
  for (;;) {
    const left = readdirSync('/proc').filter((pid) => {
      if (!/^\d+$/.test(pid)) return false;
      let stat;
      try {
        stat = readFileSync(`/proc/${pid}/stat`, 'utf8');
      } catch {
        return false;
      }
      // "pid (comm) state ppid pgrp ...": comm may hold spaces or parentheses.
      const [state, , pgrp] = stat.slice(stat.lastIndexOf(')') + 2).split(' ');
      return Number(pgrp) === pgid && state !== 'Z';
    });
    if (left.length === 0) return;
    if (Date.now() > until) throw new Error(`fixture server: process group ${pgid} still running: ${left.join(', ')}`);
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}
