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

test('main pushes retain the running run and coalesce pending pushes to latest', () => {
  const queue = scheduler();
  for (const id of ['running', 'pending', 'latest']) queue.enqueue(id, policy('push'));
  assert.deepEqual(queue.groups.get(policy('push').group), { running: 'running', pending: 'latest' });
  assert.deepEqual(queue.cancelled, ['pending']);
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
