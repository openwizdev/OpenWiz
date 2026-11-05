// #449: exercise P4 itself, including the actual HTTP answers, with the
// same 1000-byte refresh plant that the old measurement missed.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const web = fileURLToPath(new URL('../../', import.meta.url));
const hook = fileURLToPath(new URL('../fixtures/449/refresh-hook.mjs', import.meta.url));
const { NODE_TEST_CONTEXT: _context, ...env } = process.env;

test('P4 measures refresh reply bytes and detects 1000 extra bytes per answer', () => {
  const measurements: number[][] = [];
  const answers: number[][] = [];
  for (const padding of [0, 1000]) {
    const dir = mkdtempSync(join(tmpdir(), 'v11-refresh-'));
    try {
      execFileSync(process.execPath, ['--import', hook, '--test', '--test-name-pattern=^P4,', 'test/browser/v11-perf.test.mjs'], {
        cwd: web,
        env: { ...env, V11_PROOF_DIR: dir, V11_PROOF_PADDING: String(padding) },
        timeout: 120_000,
        stdio: 'pipe',
      });
      const result = JSON.parse(readFileSync(join(dir, 'v11-perf.json'), 'utf8'));
      const measured = [6, 100, 200].map((rows) => result.refresh[`${rows} rows`].bytesPerRefresh);
      measurements.push(measured);
      const expected = [0, 1, 2].map((i) => {
        const bytes: number[] = JSON.parse(readFileSync(join(dir, `answers-${i}.json`), 'utf8'));
        assert.equal(bytes.length, 21, 'one initial load and exactly 20 refresh answers');
        return bytes.slice(1).reduce((sum, n) => sum + n, 0) / 20;
      });
      answers.push(expected);
      console.log({ padding, measured, expected });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }
  assert.deepEqual(measurements[1]!.map((n, i) => n - measurements[0]![i]!), [1000, 1000, 1000]);
  assert.deepEqual(measurements, answers, 'P4 must record the mean of the actual refresh answers, excluding the initial load');
});
