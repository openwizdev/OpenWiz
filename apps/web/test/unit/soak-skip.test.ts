// The soak off the PR path (#1261, folding K13 #430). On a pull request's
// first run against main only, the runner passes OPENWIZ_SKIP_SOAK=1 to the
// test processes, and the soak, the one test that reads it, skips itself;
// every other run (a rerun, a release branch's pull request, a push to main,
// the nightly run, a local `npm test`) runs it. No name pattern skips
// anything, so no other test, nested or not, can be skipped by a title it
// happens to share (review R1). The coverage check: after each run, exactly
// the soak was skipped on such a pull request, and nothing at all otherwise.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { globSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

type Env = Record<string, string | undefined>;
type Entry = { file: string; name: string; nesting: number; skip: boolean };
type SkipModule = {
  SOAK_FILE: string;
  SOAK_ENV: string;
  skipSoak(env: Env): boolean;
  checkSkips(tests: Entry[], skipping: boolean, soakSelected?: boolean): void;
};
type Options = { files: string[]; env: Env; testSkipPatterns?: unknown; testNamePatterns?: unknown };
type RunnerModule = { runOptions(order: string[], env: Env): Options };

const WEB_DIR = fileURLToPath(new URL('../../', import.meta.url));
const skip: SkipModule = await import(String(new URL('../soak-skip.mjs', import.meta.url)));
const runner: RunnerModule = await import(String(new URL('../run-browser.mjs', import.meta.url)));

const SOAK_TITLE = 'soak: 2 simulated hours, then failures, then a hidden hour';
const SOL3_TITLE = 'a server retry hint far in the future is capped at the backoff cap (Sol 3)';
const PR: Env = { GITHUB_EVENT_NAME: 'pull_request', GITHUB_RUN_ATTEMPT: '1', GITHUB_BASE_REF: 'main' };

test("Soak selection contracts: event gates, flag isolation and complete reporting", async (t) => {
  for (const [name, proof] of [
    ['soak skip: only a pull request’s first run against main skips the soak; reruns, release PRs, pushes, nightly and local runs keep it', () => {
      assert.equal(skip.skipSoak(PR), true);
      const keeps: [string, Env][] = [
        ['a rerun (attempt 2)', { ...PR, GITHUB_RUN_ATTEMPT: '2' }],
        ['attempt 10', { ...PR, GITHUB_RUN_ATTEMPT: '10' }],
        ['no attempt', { ...PR, GITHUB_RUN_ATTEMPT: undefined }],
        ['an empty attempt', { ...PR, GITHUB_RUN_ATTEMPT: '' }],
        ['a malformed attempt', { ...PR, GITHUB_RUN_ATTEMPT: '01' }],
        ['a padded attempt', { ...PR, GITHUB_RUN_ATTEMPT: ' 1' }],
        ['a release branch’s pull request', { ...PR, GITHUB_BASE_REF: 'release-0.1' }],
        ['a base like main', { ...PR, GITHUB_BASE_REF: 'main-null' }],
        ['no base', { ...PR, GITHUB_BASE_REF: undefined }],
        ['a push to main', { GITHUB_EVENT_NAME: 'push', GITHUB_RUN_ATTEMPT: '1', GITHUB_BASE_REF: '' }],
        ['the nightly run', { GITHUB_EVENT_NAME: 'schedule', GITHUB_RUN_ATTEMPT: '1' }],
        ['workflow_dispatch', { ...PR, GITHUB_EVENT_NAME: 'workflow_dispatch' }],
        ['pull_request_target', { ...PR, GITHUB_EVENT_NAME: 'pull_request_target' }],
        ['merge_group', { ...PR, GITHUB_EVENT_NAME: 'merge_group' }],
        ['another spelling', { ...PR, GITHUB_EVENT_NAME: 'PULL_REQUEST' }],
        ['a local npm test', {}],
      ];
      for (const [what, env] of keeps) assert.equal(skip.skipSoak(env), false, what);
    }],
    ['soak skip: the runner sets the flag for the test processes only when it skips, removes an inherited one otherwise, and passes no name pattern', () => {
      const order = ['test/browser/v7-soak.test.mjs', 'test/browser/v1-faithful.test.mjs'];
      const pr = runner.runOptions(order, { ...PR, PATH: '/usr/bin' });
      assert.deepEqual(pr.files, order);
      assert.equal(pr.env[skip.SOAK_ENV], '1');
      assert.equal(pr.env['PATH'], '/usr/bin');
      for (const env of [{ ...PR, GITHUB_RUN_ATTEMPT: '2' }, { GITHUB_EVENT_NAME: 'push' }, {}]) {
        const full = runner.runOptions(order, { ...env, [skip.SOAK_ENV]: '1' });
        assert.equal(skip.SOAK_ENV in full.env, false, JSON.stringify(env));
      }
      for (const o of [pr, runner.runOptions(order, {})]) {
        assert.equal(o.testSkipPatterns, undefined);
        assert.equal(o.testNamePatterns, undefined);
      }
    }],
    ['soak skip: the flag is read by the soak alone, in its own options', () => {
      const readers = globSync('test/**/*.{mjs,ts}', { cwd: WEB_DIR }).filter((f) => readFileSync(join(WEB_DIR, f), 'utf8').includes(skip.SOAK_ENV)).sort();
      assert.deepEqual(readers, ['test/browser/v7-soak.test.mjs', 'test/soak-skip.mjs', 'test/unit/soak-skip.test.ts']);
      const soak = readFileSync(join(WEB_DIR, skip.SOAK_FILE), 'utf8');
      assert.equal(soak.split(skip.SOAK_ENV).length - 1, 1, 'the soak file reads it once');
      const line = soak.split('\n').find((l) => l.includes(skip.SOAK_ENV)) ?? '';
      assert.match(line, /^test\(`soak: \$\{HOURS\} simulated hours, then failures, then a hidden hour`, \{ /, 'on the soak’s own test() line');
    }],
    ['coverage check: on a skipping run exactly the soak was skipped; on any other run nothing was, and the soak ran', () => {
      const soak = { file: skip.SOAK_FILE, name: SOAK_TITLE, nesting: 0, skip: false };
      const sol3 = { file: skip.SOAK_FILE, name: SOL3_TITLE, nesting: 0, skip: false };
      const other = { file: 'test/browser/v9-layout.test.mjs', name: 'soak: synthetic same title', nesting: 1, skip: false };
      skip.checkSkips([{ ...soak, skip: true }, sol3, other], true);
      skip.checkSkips([soak, sol3, other], false);
      const bad: [string, Entry[], boolean][] = [
        ['a second skip on a pull request', [{ ...soak, skip: true }, sol3, { ...other, skip: true }], true],
        ['the Sol 3 test skipped', [{ ...soak, skip: true }, { ...sol3, skip: true }], true],
        ['the soak not skipped on a pull request', [soak, sol3], true],
        ['the soak missing on a pull request', [sol3], true],
        ['the soak nested', [{ ...soak, nesting: 1, skip: true }, sol3], true],
        ['the soak in another file', [{ ...soak, file: 'test/browser/v7-other.test.mjs', skip: true }, sol3], true],
        ['the soak skipped on a full run', [{ ...soak, skip: true }, sol3], false],
        ['another test skipped on a full run', [soak, sol3, { ...other, skip: true }], false],
        ['the soak missing on a full run', [sol3, other], false],
        ['the soak twice on a full run', [soak, soak, sol3], false],
        ['nothing reported', [], false],
      ];
      for (const [what, tests, skipping] of bad) assert.throws(() => skip.checkSkips(tests, skipping), /soak skip/, what);
    }],
    ['coverage check: a run whose selection left the soak’s file out (#432) skipped nothing and reported no soak; with the file selected, every rule above holds', () => {
      const soak = { file: skip.SOAK_FILE, name: SOAK_TITLE, nesting: 0, skip: false };
      const sol3 = { file: skip.SOAK_FILE, name: SOL3_TITLE, nesting: 0, skip: false };
      const other = { file: 'test/browser/v9-layout.test.mjs', name: 'a proof', nesting: 0, skip: false };
      skip.checkSkips([other], true, false);
      skip.checkSkips([other], false, false);
      skip.checkSkips([{ ...soak, skip: true }, sol3, other], true, true);
      skip.checkSkips([soak, sol3, other], false, true);
      const bad: [string, Entry[], boolean, boolean][] = [
        ['a skip with the soak not selected', [{ ...other, skip: true }], true, false],
        ['a skip on a full run with the soak not selected', [{ ...other, skip: true }], false, false],
        ['the soak reported though not selected', [soak, other], false, false],
        ['the soak skipped though not selected', [{ ...soak, skip: true }, other], true, false],
        ['the soak missing though selected', [sol3, other], true, true],
        ['the soak not skipped on a pull request, selected', [soak, sol3], true, true],
      ];
      for (const [what, tests, skipping, selected] of bad) assert.throws(() => skip.checkSkips(tests, skipping, selected), /soak skip/, what);
    }],
  ] as const) {
    t.diagnostic(name);
    await proof();
  }
});

test('soak skip: through the runner’s options on a pull request (npm test and test:browser alike), a second top-level "soak: " test and a nested one still run, and fail', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'openwiz-soak-skip-'));
  try {
    const file = join(dir, 'collision.test.mjs');
    writeFileSync(file, [
      "import assert from 'node:assert/strict';",
      "import { test } from 'node:test';",
      `test('the flag reaches the test process', () => assert.equal(process.env.${skip.SOAK_ENV}, '1'));`,
      "test('soak: a second top-level proof', () => assert.fail('planted top-level'));",
      "test('a proof with subtests', async (t) => { await t.test('soak: a nested proof', () => assert.fail('planted nested')); });",
      '',
    ].join('\n'));
    // node:test refuses run() inside a test file, so a child process (without this one's test context) drives it;
    // forceExit off there, or it would exit before printing what it saw.
    const driver = [
      `const { run } = await import('node:test');`,
      `const { runOptions } = await import(${JSON.stringify(String(new URL('../run-browser.mjs', import.meta.url)))});`,
      `const seen = [];`,
      `const s = run({ ...runOptions([${JSON.stringify(file)}], ${JSON.stringify(PR)}), concurrency: 1, forceExit: false });`,
      `s.on('test:pass', (d) => seen.push({ name: d.name, ok: true, skip: Boolean(d.skip) }));`,
      `s.on('test:fail', (d) => seen.push({ name: d.name, ok: false, skip: Boolean(d.skip) }));`,
      `for await (const _ of s);`,
      `process.stdout.write(JSON.stringify(seen));`,
    ].join('\n');
    // A file, not `node -e`: run() hands its own process's flags to the test processes.
    writeFileSync(join(dir, 'driver.mjs'), driver);
    const { NODE_TEST_CONTEXT: _context, ...env } = process.env;
    const seen: { name: string; ok: boolean; skip: boolean }[] = JSON.parse(execFileSync(process.execPath, [join(dir, 'driver.mjs')], { cwd: WEB_DIR, env, encoding: 'utf8' }));
    const by = (name: string) => seen.filter((s) => s.name === name);
    assert.deepEqual(by('soak: a second top-level proof'), [{ name: 'soak: a second top-level proof', ok: false, skip: false }]);
    assert.deepEqual(by('the flag reaches the test process'), [{ name: 'the flag reaches the test process', ok: true, skip: false }]);
    assert.deepEqual(by('soak: a nested proof'), [{ name: 'soak: a nested proof', ok: false, skip: false }]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
