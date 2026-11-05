import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const path = new URL('./ci-safety-watch.yml', import.meta.url);

test('freshness watchdog is hourly, independent, read-only and bounded', () => {
  const workflow = readFileSync(path, 'utf8');
  assert.match(workflow, /^    - cron: '41 \* \* \* \*'/m);
  assert.match(workflow, /^permissions:\n  actions: read\n\n/m);
  assert.match(workflow, /^  group: ci-safety-watch$/m);
  assert.match(workflow, /^  cancel-in-progress: false$/m);
  assert.match(workflow, /^    timeout-minutes: 5$/m);
  assert.doesNotMatch(workflow, /^    needs:/m);
  assert.match(workflow, /^          GH_TOKEN: \$\{\{ github.token \}\}$/m);
});

test('freshness check accepts fresh completion and alerts on missing, stale or unreadable evidence', () => {
  const workflow = readFileSync(path, 'utf8');
  const script = workflow.split('        run: |\n')[1]?.replace(/^          /gm, '');
  assert.ok(script, 'operative shell step exists');
  const dir = mkdtempSync(join(tmpdir(), 'ci-safety-test-'));
  try {
    writeFileSync(join(dir, 'gh'), `#!/usr/bin/env node
const { spawnSync } = require('node:child_process');
const args = process.argv.slice(2);
const endpoint = args.find(a => a.startsWith('repos/'));
const runs = endpoint === 'repos/synthetic/project/actions/workflows/ci.yml/runs';
if (!runs && !/^repos\\/synthetic\\/project\\/actions\\/runs\\/101\\/(?:attempts\\/[12]\\/)?jobs$/.test(endpoint)) process.exit(99);
// Keep the original read-only API scope controls; do not prescribe the jq logic.
const expected = runs
  ? ['api', '--method', 'GET', endpoint, '-f', 'event=schedule', '-f', 'branch=main', '-f', 'status=success', '-f', 'per_page=1']
  : ['api', '--method', 'GET', endpoint, '-f', 'per_page=100'];
if (JSON.stringify(args.slice(0, -2)) !== JSON.stringify(expected) || args.at(-2) !== '--jq') {
  console.error('unexpected read'); process.exit(99);
}
if (process.env.API_ERROR === (runs ? 'runs' : 'jobs')) { console.error('synthetic API failure'); process.exit(1); }
// Supply raw snapshots; the workflow's actual jq expression makes the decision.
const result = spawnSync('/usr/bin/jq', ['-r', args[args.indexOf('--jq') + 1]], {
  input: runs ? process.env.RUNS_JSON : process.env.JOBS_JSON, encoding: 'utf8',
});
process.stdout.write(result.stdout ?? '');
process.stderr.write(result.stderr ?? '');
process.exit(result.status ?? 99);
`, { mode: 0o755 });
    writeFileSync(join(dir, 'date'), `#!/bin/sh
if [ "$*" = '-u +%s' ]; then echo 1793966400; else exec /usr/bin/date "$@"; fi
`, { mode: 0o755 });
    // Fixed clock: 2026-11-06 12:00 UTC. All timestamps and IDs are synthetic.
    const run = { id: 101, run_attempt: 1, status: 'completed', conclusion: 'success' };
    const job = (completed, attempt = 1, status = 'completed', conclusion = 'success') =>
      ({ id: 201, run_id: 101, run_attempt: attempt, status, conclusion, completed_at: completed });
    const fresh = '2026-11-06T11:59:00Z';
    const stale = '2026-11-05T05:59:59Z';
    const cases = [
      ['fresh', '2026-11-06T11:59:00Z', '101', '', 0, /completed within/],
      ['late nightly within scheduling allowance', '2026-11-05T09:00:01Z', '101', '', 0, /completed within/],
      ['exactly 24 hours', '2026-11-05T12:00:00Z', '101', '', 0, /completed within/],
      ['just inside 30-hour window', '2026-11-05T06:00:01Z', '101', '', 0, /completed within/],
      ['exactly 30 hours', '2026-11-05T06:00:00Z', '101', '', 1, /::error::No successful scheduled CI safety run completed in the last 30 hours/],
      ['stale', '2026-11-05T05:59:59Z', '101', '', 1, /::error::No successful scheduled CI/],
      ['missing run', '', '', '', 1, /::error::No successful scheduled CI safety run exists/],
      ['zero jobs', '', '101', '', 1, /::error::The scheduled safety run has no successful jobs/],
      ['future completion', '2026-11-06T12:00:01Z', '101', '', 1, /::error::No successful scheduled CI/],
      ['bad timestamp', 'invalid', '101', '', 1, /invalid date/],
      ['runs API failure', '', '101', 'runs', 1, /synthetic API failure/],
      ['jobs API failure', '', '101', 'jobs', 1, /synthetic API failure/],
    ].map(([name, completed, runId, apiError, status, output]) =>
      [name, apiError, status, output, runId ? [run] : [], completed ? [job(completed)] : []]);
    cases.push(
      ['rerun in progress', '', 1, /::error::/, [run],
        [job(fresh, 2), job(null, 2, 'in_progress', null)]],
      ['rerun failed', '', 1, /::error::/, [run],
        [job(fresh, 2), job(fresh, 2, 'completed', 'failure')]],
      ['stale selected attempt with fresh rerun', '', 1, /::error::/, [run],
        [job(stale), job(fresh, 2)]],
      ['successful second attempt', '', 0, /completed within/, [{ ...run, run_attempt: 2 }],
        [job(fresh, 2)]],
      ['missing attempt', '', 1, /::error::/, [{ ...run, run_attempt: null }], [job(fresh)]],
    );
    const failures = [];
    for (const [name, apiError, status, output, runs, jobs] of cases) {
      const result = spawnSync('bash', ['-e', '-c', script], {
        encoding: 'utf8',
        timeout: 5000,
        env: { ...process.env, PATH: `${dir}:${process.env.PATH}`, GH_REPO: 'synthetic/project',
          RUNS_JSON: JSON.stringify({ workflow_runs: runs }),
          JOBS_JSON: JSON.stringify({ total_count: jobs.length, jobs }), API_ERROR: apiError },
      });
      try {
        assert.equal(result.status, status, `${name}: ${result.stdout}${result.stderr}`);
        assert.match(`${result.stdout}${result.stderr}`, output, name);
      } catch (error) {
        failures.push(error.message);
      }
    }
    assert.deepEqual(failures, []);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
