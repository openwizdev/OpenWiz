// The web proofs' runner (test/run-browser.mjs, #431, #1261): `npm test` runs
// the unit and browser files in one pool, longest first, so the unit files
// that start Chromium no longer run alone before the browser files start.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { copyFileSync, globSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import type { Socket } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { stripVTControlCharacters } from 'node:util';

type Plan = { order: string[]; missing: string[]; stale: string[] };
type RunnerModule = {
  plan(files: string[], table: string): Plan;
  webFiles(withUnit: boolean): string[];
  parseArgs(args: string[], files?: string[]): { withUnit: boolean; only?: string[] };
  soakSelected(args: { only?: string[] }, order: string[]): boolean;
};

const WEB_DIR = fileURLToPath(new URL('../../', import.meta.url));
const runner: RunnerModule = await import(String(new URL('../run-browser.mjs', import.meta.url)));

test("Web runner preserves pooled order, file selection, scripts and soak obligations", async (t) => {
  for (const [name, proof] of [
    ['runner: the time table takes unit and browser rows, and orders both in one pool, longest first', () => {
      assert.deepEqual(runner.plan(['test/browser/a.test.mjs'], 'file\tms\ntest/browser/a.test.mjs\t1\n'), {
        order: ['test/browser/a.test.mjs'], missing: [], stale: [],
      });
      const table = 'file\tms\ntest/browser/b.test.mjs\t100\ntest/unit/u.test.ts\t300\ntest/browser/a.test.mjs\t200\n';
      const { order, missing, stale } = runner.plan(['test/browser/a.test.mjs', 'test/browser/b.test.mjs', 'test/unit/u.test.ts', 'test/unit/new.test.ts'], table);
      assert.deepEqual(order, ['test/unit/u.test.ts', 'test/browser/a.test.mjs', 'test/browser/b.test.mjs', 'test/unit/new.test.ts']);
      assert.deepEqual(missing, ['test/unit/new.test.ts']);
      assert.deepEqual(stale, []);
      for (const bad of [
        'test/unit/u.test.mjs\t1', 'test/unit/../u.test.ts\t1', 'test/other/u.test.ts\t1', 'test/browser/b.test.ts\t1',
        'test/browser/a.test.mjs\t1\ntest/browser/a.test.mjs\t1',
        'test/browser/a.test.mjs\t1\ntest/browser/a.test.mjs\t2',
      ]) {
        assert.throws(() => runner.plan(['test/browser/a.test.mjs'], `file\tms\n${bad}\n`), /file-times\.tsv/, bad);
      }
    }],
    ['runner: with --with-unit it runs every unit and browser file, without it the browser files only; any other argument is refused', () => {
      const browser = globSync('test/browser/**/*.test.mjs', { cwd: WEB_DIR }).sort();
      const unit = globSync('test/unit/**/*.test.ts', { cwd: WEB_DIR }).sort();
      assert.ok(browser.length > 0 && unit.length > 0);
      assert.deepEqual(runner.webFiles(false).sort(), browser);
      assert.deepEqual(runner.webFiles(true).sort(), [...browser, ...unit].sort());
      assert.deepEqual(runner.parseArgs([]), { withUnit: false });
      assert.deepEqual(runner.parseArgs(['--with-unit']), { withUnit: true });
      for (const bad of [['--with-unit', '--with-unit'], ['--test-concurrency=4'], ['test/unit/api.test.ts']]) assert.throws(() => runner.parseArgs(bad), /takes no arguments but --with-unit and --only/, bad.join(' '));
    }],
    ['runner: --only runs just the selected files (#432), each one it would run, once; anything else is refused', () => {
      const files = ['test/browser/a.test.mjs', 'test/browser/b.test.mjs', 'test/unit/u.test.ts'];
      assert.deepEqual(runner.parseArgs(['--with-unit', '--only', 'test/unit/u.test.ts', 'test/browser/b.test.mjs'], files), { withUnit: true, only: ['test/browser/b.test.mjs', 'test/unit/u.test.ts'] });
      assert.deepEqual(runner.parseArgs(['--only', 'test/browser/a.test.mjs'], files), { withUnit: false, only: ['test/browser/a.test.mjs'] });
      const refused: [string[], RegExp][] = [
        [['--with-unit', '--only'], /--only needs at least one file/],
        [['--only', 'test/browser/c.test.mjs'], /not a file it runs/],
        [['--only', 'test/unit/u.test.ts'], /not a file it runs/],
        [['--with-unit', '--only', '../x.test.mjs'], /not a file it runs/],
        [['--with-unit', '--only', 'test/browser/a.test.mjs', 'test/browser/a.test.mjs'], /twice/],
        [['--only', 'test/browser/a.test.mjs', '--with-unit'], /not a file it runs/],
      ];
      for (const [args, why] of refused) assert.throws(() => runner.parseArgs(args, files.filter((f) => args.includes('--with-unit') || !f.startsWith('test/unit/'))), why, args.join(' '));
    }],
    ['runner: npm test runs the one pool; test:unit and test:browser stay for running either alone', () => {
      const scripts = JSON.parse(readFileSync(`${WEB_DIR}/package.json`, 'utf8')).scripts;
      assert.equal(scripts.test, 'node test/run-browser.mjs --with-unit');
      assert.equal(scripts['test:browser'], 'node test/run-browser.mjs');
      assert.match(scripts['test:unit'], /^node --test /);
    }],
    ['runner: the command runs four selected children with at most three processes alive (#1890)', async () => {
      // A cap of four used to pass every helper assertion above. Observe real
      // process lifetimes: socket arrivals alone can miss a late fourth worker.
      const dir = mkdtempSync(join(tmpdir(), 'openwiz-runner-'));
      const sockets: Socket[] = [];
      const server = createServer((socket) => {
        sockets.push(socket);
        // Hold the first three together, then drain all four. No timed release.
        if (sockets.length === 3) for (const s of sockets) s.end('release');
        else if (sockets.length > 3) socket.end('release');
      });
      let child: ReturnType<typeof spawn> | undefined;
      try {
        for (const sub of ['test/browser', 'test/support']) mkdirSync(join(dir, sub), { recursive: true });
        for (const file of ['run-browser.mjs', 'soak-skip.mjs']) copyFileSync(join(WEB_DIR, 'test', file), join(dir, 'test', file));
        writeFileSync(join(dir, 'test/support/paths.mjs'), `export const WEB_DIR = ${JSON.stringify(dir)};\n`);
        // Preparation only; scheduling, reporting and exit remain the real runner's.
        writeFileSync(join(dir, 'test/support/rust.mjs'), 'export function buildBinaries() {}\n');
        const trace = join(dir, 'processes.jsonl');
        writeFileSync(trace, '');
        const observer = join(dir, 'observe.mjs');
        // Observe successful OS spawns and exits, without replacing run() or
        // inspecting its options. Slow worker startup cannot hide a fourth PID.
        writeFileSync(observer, `
import { channel } from 'node:diagnostics_channel';
import { appendFileSync } from 'node:fs';
channel('child_process').subscribe(({ process: child }) => {
  child.once('spawn', () => appendFileSync(${JSON.stringify(trace)}, JSON.stringify(['start', child.pid]) + '\\n'));
  child.once('exit', () => appendFileSync(${JSON.stringify(trace)}, JSON.stringify(['exit', child.pid]) + '\\n'));
});
`);
        const address = join(dir, 'gate.sock');
        server.listen(address);
        await once(server, 'listening');
        const files = Array.from({ length: 4 }, (_, i) => `test/browser/synthetic${i}.test.mjs`);
        for (const file of files) writeFileSync(join(dir, file), `
import { test } from 'node:test';
import { createConnection } from 'node:net';
test(${JSON.stringify(file)}, () => new Promise((resolve, reject) => {
  const socket = createConnection(${JSON.stringify(address)});
  socket.on('error', reject);
  socket.setTimeout(10000, () => socket.destroy(new Error('gate did not release')));
  socket.on('data', () => { socket.end(); resolve(); });
}));
`);
        writeFileSync(join(dir, 'test/file-times.tsv'), 'file\tms\n' + files.map((file) => `${file}\t1\n`).join(''));
        const env = { ...process.env };
        for (const key of Object.keys(env)) if (key.startsWith('GITHUB_') || ['NODE_TEST_CONTEXT', 'NODE_OPTIONS'].includes(key)) delete env[key];
        child = spawn(process.execPath, ['--import', observer, 'test/run-browser.mjs', '--only', ...files], { cwd: dir, env, timeout: 20000, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
        let output = '';
        child.stdout!.setEncoding('utf8').on('data', (chunk) => { output += chunk; });
        child.stderr!.setEncoding('utf8').on('data', (chunk) => { output += chunk; });
        const [code, signal] = await once(child, 'close');
        output = stripVTControlCharacters(output);
        assert.equal(signal, null, output);
        assert.equal(code, 0, output);
        assert.equal(sockets.length, 4, 'all four children reached the gate');
        const active = new Set<number>();
        const starts: number[] = [], exits: number[] = [];
        let peak = 0;
        for (const line of readFileSync(trace, 'utf8').trim().split('\n')) {
          const [event, pid]: [string, number] = JSON.parse(line);
          if (event === 'start') {
            assert.equal(active.has(pid), false);
            active.add(pid);
            starts.push(pid);
            peak = Math.max(peak, active.size);
          } else {
            assert.equal(event, 'exit');
            assert.equal(active.delete(pid), true, 'only a started child exits');
            exits.push(pid);
          }
        }
        assert.equal(new Set(starts).size, 4, 'four distinct child processes');
        assert.equal(starts.length, 4);
        assert.deepEqual(exits.sort(), [...starts].sort(), 'all four processes completed');
        assert.equal(active.size, 0);
        for (const file of files) assert.ok(output.includes(`✔ ${file}`), output);
        assert.equal(peak, 3, 'three child processes at once, never four');
      } finally {
        if (child?.pid) { try { process.kill(-child.pid, 'SIGKILL'); } catch (e) { if ((e as NodeJS.ErrnoException).code !== 'ESRCH') throw e; } }
        for (const socket of sockets) socket.destroy();
        await new Promise<void>((resolve) => server.close(() => resolve()));
        rmSync(dir, { recursive: true, force: true });
      }
    }],
    ['runner: the soak counts as selected unless --only left its file out (#432, review R4 on #1579)', () => {
      const soak = 'test/browser/v7-soak.test.mjs';
      assert.equal(runner.soakSelected({}, ['test/browser/a.test.mjs']), true, 'a full run missing the soak still owes the soak');
      assert.equal(runner.soakSelected({}, [soak]), true);
      assert.equal(runner.soakSelected({ only: ['test/browser/a.test.mjs'] }, ['test/browser/a.test.mjs']), false);
      assert.equal(runner.soakSelected({ only: [soak] }, [soak]), true);
    }],
  ] as const) {
    t.diagnostic(name);
    await proof();
  }
});
