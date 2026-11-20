// Fixture model of GitHub's documented single-pending concurrency policy.
// This checks the committed expressions, not GitHub's live scheduler.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

const workflow = readFileSync(new URL('./ci.yml', import.meta.url), 'utf8');
const block = workflow.match(/^concurrency:\n((?:[ \t].*\n|\n)*)/m)?.[1];
assert.ok(block, 'workflow-level concurrency exists');
const group = block.match(/^  group: (.+)$/m)?.[1];
const cancel = block.match(/^  cancel-in-progress: \$\{\{ (.+) \}\}$/m)?.[1];
assert.ok(group);
assert.ok(cancel);

function policy(event, ref = 'refs/heads/main', number) {
  const github = { event_name: event, ref, event: { pull_request: { number } } };
  return {
    group: group.replace(/\$\{\{ (.+?) \}\}/g, (_, expression) =>
      runInNewContext(expression, { github }, { timeout: 100 })),
    cancel: runInNewContext(cancel, { github }, { timeout: 100 }),
  };
}

function scheduler() {
  const groups = new Map();
  const cancelled = [];
  return {
    groups, cancelled,
    enqueue(id, policy) {
      const state = groups.get(policy.group) ?? { running: null, pending: null };
      if (state.pending) cancelled.push(state.pending);
      state.pending = null;
      if (policy.cancel && state.running) {
        cancelled.push(state.running);
        state.running = null;
      }
      if (state.running) state.pending = id;
      else state.running = id;
      groups.set(policy.group, state);
    },
  };
}

test('The Rust lane reads the plan\'s planted output', () => {
  const changes = workflow.match(/^  changes:\n((?:    .*\n|\n)*)/m)?.[1];
  assert.match(changes, /^      planted: \$\{\{ steps\.plan\.outputs\.planted \}\}$/m);
  for (const lane of ['rust']) {
    const job = workflow.match(new RegExp(`^  ${lane}:\\n((?:    .*\\n|\\n)*)`, 'm'))?.[1];
    assert.ok(job, `${lane} job exists`);
    assert.match(job, /^    needs: changes$/m);
  }
});

test('nightly remains admitted when later main pushes arrive', () => {
  const queue = scheduler();
  queue.enqueue('push-running', policy('push'));
  queue.enqueue('prior-nightly', policy('schedule'));
  queue.enqueue('nightly', policy('schedule'));
  queue.enqueue('push-pending', policy('push'));
  queue.enqueue('push-latest', policy('push'));
  assert.notEqual(policy('schedule').group, policy('push').group);
  assert.ok(!queue.cancelled.includes('nightly'), 'nightly was replaced by a push');
  assert.deepEqual(queue.groups.get(policy('schedule').group), { running: 'prior-nightly', pending: 'nightly' });
});

test('new main pushes cancel obsolete main pushes without cancelling other refs', () => {
  const queue = scheduler();
  for (const id of ['running', 'pending', 'latest']) queue.enqueue(id, policy('push'));
  assert.deepEqual(queue.groups.get(policy('push').group), { running: 'latest', pending: null });
  assert.deepEqual(queue.cancelled, ['running', 'pending']);
  assert.equal(policy('push', 'refs/heads/release-synthetic').cancel, false);
  assert.equal(policy('schedule').cancel, false);
});

test('PR updates cancel obsolete work for that PR only', () => {
  const queue = scheduler();
  queue.enqueue('pr-7-old', policy('pull_request', 'refs/pull/7/merge', 7));
  queue.enqueue('pr-8', policy('pull_request', 'refs/pull/8/merge', 8));
  queue.enqueue('pr-7-new', policy('pull_request', 'refs/pull/7/merge', 7));
  assert.deepEqual(queue.cancelled, ['pr-7-old']);
  assert.equal(queue.groups.get(policy('pull_request', 'refs/pull/8/merge', 8).group).running, 'pr-8');
});

test('merge groups retain independent groups and do not cancel running work', () => {
  const first = policy('merge_group', 'refs/heads/gh-readonly-queue/main/pr-7');
  const second = policy('merge_group', 'refs/heads/gh-readonly-queue/main/pr-8');
  assert.notEqual(first.group, second.group);
  assert.notEqual(first.group, policy('schedule').group);
  assert.equal(first.cancel, false);
});

// #2412: the carriage guard step in the changes job, which ci requires.
test('the carriage guard runs on pull requests and merge groups and fails closed', () => {
  const changes = workflow.match(/^  changes:\n((?:    .*\n|\n)*)/m)?.[1];
  assert.ok(changes, 'changes job exists');
  const step = changes.match(/^      - name: The carriage guard\n((?:        .*\n)*)/m)?.[1];
  assert.ok(step, 'guard step is in the changes job');
  const condition = step.match(/^        if: (.+)$/m)?.[1];
  // GitHub's expression property reads are null-safe; model that with ?.
  const base = step.match(/^          BASE_SHA: \$\{\{ (.+) \}\}$/m)?.[1]?.replaceAll('.', '?.');
  for (const [event_name, event, sha] of [
    ['pull_request', { pull_request: { base: { sha: 'a'.repeat(40) } } }, 'a'.repeat(40)],
    ['merge_group', { merge_group: { base_sha: 'b'.repeat(40) } }, 'b'.repeat(40)],
  ]) {
    const github = { event_name, event };
    assert.equal(runInNewContext(condition, { github }, { timeout: 100 }), true, event_name);
    assert.equal(runInNewContext(base, { github }, { timeout: 100 }), sha, event_name);
  }
  assert.doesNotMatch(step, /continue-on-error/);
  assert.match(step, /^          python3 -I tools\/open-import\/test_guard\.py$/m);
  assert.match(step, /^          python3 -I tools\/open-import\/guard\.py "--base=\$BASE_SHA" --head=HEAD$/m);
  assert.ok(changes.indexOf('actions/checkout') < changes.indexOf('The carriage guard'), 'runs after the full checkout');
  assert.match(workflow.match(/^  ci:\n((?:    .*\n|\n)*)/m)?.[1] ?? '', /needs:[^\n]*changes/);
});

// #2931: the frozen old code check's own always-on workflow, frozen.yml.
// R1: GitHub runs the base's frozen.yml for pull_request_target, and every
// step runs the base's checker; the change is read only as Git data.
test('frozen.yml runs the base\'s frozen old code check on GitHub-hosted runners for every PR and merge group to main', () => {
  const frozen = readFileSync(new URL('./frozen.yml', import.meta.url), 'utf8');
  const on = frozen.match(/^on:\n((?:  .*\n|\n)*)/m)?.[1];
  assert.match(on, /^  pull_request_target:\n    branches: \[main\]\n/m);
  assert.doesNotMatch(on, /^  pull_request:/m);
  // A title edit can add or remove #1287's exception, so edited re-runs it.
  assert.match(on, /^    types: \[opened, synchronize, reopened, ready_for_review, edited\]$/m);
  assert.match(on, /^  merge_group:\n    types: \[checks_requested\]$/m);
  assert.match(frozen, /^permissions:\n  contents: read\n\n/m);
  const jobs = frozen.slice(frozen.indexOf('\njobs:\n'));
  assert.deepEqual([...jobs.matchAll(/^  ([a-z-]+):$/gm)].map((m) => m[1]), ['frozen']);
  // The ruleset's one required check after the cut-over: a fixed name, and a
  // literal GitHub-hosted image that outlives ClosedWiz's released runners.
  assert.match(jobs, /^    name: frozen$/m);
  assert.match(jobs, /^    runs-on: ubuntu-24\.04$/m);
  assert.doesNotMatch(frozen, /self-hosted|vars\.CI_|continue-on-error|^\s+if:|secrets\./m);
  const steps = jobs.split(/^      - /m).slice(1);
  assert.equal(steps.length, 4);
  for (const checkout of steps.slice(0, 2)) {
    assert.match(checkout, /^uses: actions\/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7\.0\.1$/m);
    assert.match(checkout, /^          persist-credentials: false$/m);
    assert.match(checkout, /^          filter: blob:none$/m);
  }
  // The trusted tools: the base's own checker, its proofs and this workflow.
  assert.match(steps[0], /^          path: \.frozen-tools$/m);
  assert.match(steps[0], /^          sparse-checkout: \|\n            \/tools\/open-import\/\n            \/\.github\/workflows\/frozen\.yml\n/m);
  // The change as data: full history, no tool of its own checked out.
  assert.match(steps[1], /^          path: candidate$/m);
  assert.match(steps[1], /^          fetch-depth: 0$/m);
  assert.match(steps[1], /^          sparse-checkout: \|\n            \/tools\/open-import\/paths\.json\n/m);
  // The base's list, added by content, so the check reads it at the base.
  assert.match(steps[2], /^        run: git -C candidate hash-object -w --no-filters "\$PWD\/\.frozen-tools\/tools\/open-import\/paths\.json"$/m);
  const expression = (step, key) => step.match(new RegExp(`^ {10}${key}: \\$\\{\\{ (.+) \\}\\}$`, 'm'))?.[1]?.replaceAll('.', '?.');
  const evaluate = (code, github) => runInNewContext(code, { github, vars: {} }, { timeout: 100 });
  const ref = 'refs/heads/gh-readonly-queue/main/pr-1287-' + 'c'.repeat(40);
  const pr = { event_name: 'pull_request_target', event: { pull_request: { base: { sha: 'a'.repeat(40) }, head: { sha: 'd'.repeat(40) }, title: '#1287: t' } } };
  const group = { event_name: 'merge_group', event: { merge_group: { base_sha: 'b'.repeat(40), head_sha: 'e'.repeat(40), head_ref: ref } } };
  for (const [github, base, head] of [[pr, 'a'.repeat(40), 'd'.repeat(40)], [group, 'b'.repeat(40), 'e'.repeat(40)]]) {
    assert.equal(evaluate(expression(steps[0], 'ref'), github), base, github.event_name);
    assert.equal(evaluate(expression(steps[1], 'ref'), github), head, github.event_name);
    assert.equal(evaluate(expression(steps[3], 'BASE_SHA'), github), base, github.event_name);
    assert.equal(evaluate(expression(steps[3], 'HEAD_SHA'), github), head, github.event_name);
  }
  // #1287's exception reads the PR title, or the merge group's queue ref; each
  // event supplies only its own, so a pull request cannot pose as a queue ref.
  assert.equal(evaluate(expression(steps[3], 'PR_TITLE'), pr), '#1287: t');
  assert.equal(evaluate(expression(steps[3], 'QUEUE_REF'), pr), undefined);
  assert.equal(evaluate(expression(steps[3], 'PR_TITLE'), group), undefined);
  assert.equal(evaluate(expression(steps[3], 'QUEUE_REF'), group), ref);
  assert.match(steps[3], /^          FROZEN_SINCE: \$\{\{ vars\.CLOSEDWIZ_FROZEN_SINCE \}\}$/m);
  assert.match(steps[3], /^        run: \|\n          python3 -I \.frozen-tools\/tools\/open-import\/test_frozen\.py\n          python3 -I \.frozen-tools\/tools\/open-import\/frozen\.py --repo=candidate "--base=\$BASE_SHA" "--head=\$HEAD_SHA"$/m);
  // Nothing from the change is run: every script runs only the base's tools.
  for (const run of frozen.matchAll(/^        run: .*(?:\n {10}.*)*/gm)) {
    for (const line of run[0].split('\n').filter((l) => /python3|\bsh\b|node/.test(l))) {
      assert.match(line, /\.frozen-tools\//, line);
    }
  }
});

// #744: which jobs run for each event, simulated over the committed job graph
// with GitHub's documented job rules: a job runs only when its needs finished
// and its `if:` holds, and an `if:` without a status function implies
// success(), which a skipped need fails. A full plan's outputs feed the lanes.
// catches: a condition that drops a required check (or the full suite) from
// pull_request or merge_group, where a skipped required check passes silently,
// and a main push that ignores the signed-map age decision.
function jobGraph(source) {
  const body = source.slice(source.indexOf('\njobs:\n') + 7);
  return new Map([...body.matchAll(/^  ([a-z][a-z0-9-]*):\n((?:    .*\n|\n)*)/gm)].map(([, name, block]) => {
    const needs = block.match(/^    needs: (?:\[(.*)\]|(.*))$/m);
    const condition = block.match(/^    if: (.+)$/m)?.[1].replace(/^\$\{\{ (.*) \}\}$/, '$1');
    return [name, { needs: needs ? (needs[1] ?? needs[2]).split(', ') : [], condition }];
  }));
}

function simulate(source, event_name, outputs = {}, initialResults = {}) {
  const graph = jobGraph(source);
  const results = { ...initialResults };
  const github = { event_name, ref: 'refs/heads/main', event: { merge_group: { base_ref: 'refs/heads/main' } } };
  const settle = (name) => {
    if (name in results) return results[name];
    const job = graph.get(name);
    assert.ok(job, `job ${name} exists`);
    // GitHub exposes a skipped step's missing output as an empty string.
    const needs = Object.fromEntries(job.needs.map((n) => [n, { result: settle(n),
      outputs: new Proxy(outputs[n] ?? {}, { get: (values, key) => values[key] ?? '' }),
    }]));
    const done = Object.values(needs).map((n) => n.result);
    const success = () => done.every((r) => r === 'success');
    const condition = job.condition ?? 'success()';
    const status = /\b(?:always|success|failure|cancelled)\(\)/.test(condition);
    // GitHub reads hyphenated names with a dot; JavaScript needs brackets.
    const code = (status ? condition : `success() && (${condition})`).replace(/\.([a-z]+(?:-[a-z]+)+)/g, "['$1']");
    const runs = runInNewContext(code, {
      github, needs, always: () => true, cancelled: () => false, success,
      // GitHub's contains(): a case-insensitive substring test on strings.
      contains: (a, b) => String(a).toLowerCase().includes(String(b).toLowerCase()),
      failure: () => done.includes('failure'),
    }, { timeout: 100 });
    return (results[name] = runs ? 'success' : 'skipped');
  };
  for (const name of graph.keys()) settle(name);
  return Object.keys(results).filter((name) => results[name] === 'success').sort();
}

// A full plan (every reason forces one on these events): every lane.
const FULL_PLAN = { changes: { rust: 'true', release: 'true', skills: '["image","launch-fleet"]',
  'skill-jobs': '["image"]', trace: 'false', planted: 'false' } };
// #743: launch-fleet and release retain their sharded jobs on a full run.
const FULL_SUITE = ['always', 'changes', 'ci', 'launch-fleet', 'release', 'rust', 'skills', 'web-test'];

test('PR, nightly and merge-group coverage stays full; main pushes follow the map-age decision', () => {
  // #1418: the owned-paths check runs beside the suite on pull requests only.
  assert.deepEqual(simulate(workflow, 'pull_request', FULL_PLAN), [...FULL_SUITE, 'owned-paths'].sort(), 'pull_request');
  assert.deepEqual(simulate(workflow, 'merge_group', FULL_PLAN), FULL_SUITE, 'merge_group');
  assert.deepEqual(simulate(workflow, 'schedule', FULL_PLAN), FULL_SUITE, 'nightly');
  assert.deepEqual(simulate(workflow, 'push', { changes: {} }), ['changes', 'main-light'], 'fresh map: no plan or heavy lanes');

  // The light check is format (privacy runs in privacy.yml on every main push).
  const light = workflow.match(/^  main-light:\n((?:    .*\n|\n)*)/m)?.[1] ?? '';
  assert.match(light, /^          cargo fmt --check$/m);
  const privacy = readFileSync(new URL('./privacy.yml', import.meta.url), 'utf8');
  for (const event of ['pull_request', 'merge_group', 'push']) {
    assert.deepEqual(simulate(privacy, event), ['privacy'], `privacy on ${event}`);
    assert.match(privacy.match(/^on:\n((?:  .*\n|\n)*)/m)?.[1] ?? '', new RegExp(`^  ${event}:`, 'm'));
  }
  // The simulator itself: a required check gated to pull requests only is
  // dropped from merge groups, and one gated off pushes stays on both.
  const ci = /^  ci:\n    needs: (.*)\n    if: .*$/m;
  const dropped = workflow.replace(ci, "  ci:\n    needs: $1\n    if: ${{ always() && github.event_name == 'pull_request' }}");
  assert.ok(!simulate(dropped, 'merge_group', FULL_PLAN).includes('ci'));
  const kept = workflow.replace(ci, "  ci:\n    needs: $1\n    if: ${{ always() && github.event_name != 'push' }}");
  assert.ok(simulate(kept, 'merge_group', FULL_PLAN).includes('ci'));
});

test('an unreadable main-map gate still schedules the final failure check', () => {
  // catches: a failed age read being reported as a successful light push.
  const ran = simulate(workflow, 'push', { changes: {} }, { changes: 'failure' });
  assert.deepEqual(ran, ['ci', 'main-light', 'web-test']);
});

test('main pushes with an old map run the traced full plan and sign; nightly signing stays unconditional', () => {
  const traced = { changes: { ...FULL_PLAN.changes, trace: 'true' } };
  assert.deepEqual(simulate(workflow, 'push', traced), [...FULL_SUITE, 'main-light'].sort(), '121-minute map: traced full run signs');
  assert.deepEqual(simulate(workflow, 'schedule', traced), [...FULL_SUITE].sort(), 'nightly still signs');
});
