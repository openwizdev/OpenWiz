// Read-only setup contract at the actual web API client seam; no browser.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readSetup } from '../../apps/web/src/api.ts';

const example = () => ({ schema: 'openwiz.setup.v1', ready: false,
  components: ['cloudroom', 'harness', 'personal_github', 'github_app', 'project', 'engine', 'remote_access']
    .map((id) => ({ id, state: 'unknown', reason: 'Synthetic unverified prerequisite.', next: 'Ask your installing agent to verify it.' })),
  engine: 'unselected', cost: { provenance: 'unknown', credits: null, window_s: null, monthly_projection: null, free_allowance: null, reason: 'Cloud Credits have not been measured.' }, operations: [] });
async function read(body) {
  let calls = 0;
  const result = await readSetup(async (url, init) => {
    calls++;
    assert.equal(url, '/api/v1/setup');
    assert.equal(init.method, 'GET');
    assert.equal(init.body, undefined);
    assert.equal(init.cache, 'no-store');
    return { type: 'basic', status: 200, headers: { get: () => 'application/json' }, text: async () => body };
  }, new AbortController().signal);
  assert.equal(calls, 1);
  return result;
}

test('setup reader accepts independent unknowns and refuses malformed or falsely ready reports', async () => {
  assert.equal((await read(JSON.stringify(example()))).kind, 'ok');
  const wrong = [
    (v) => { v.extra = true; },
    (v) => { v.components[0].state = { verified: null }; },
    (v) => { v.components[0].state = 'ready'; },
    (v) => { v.components[0].id = 'harness'; },
    (v) => { delete v.components[0].next; },
    (v) => { v.cost.credits = 0; },
    (v) => { v.cost.provenance = 'measured'; v.cost.window_s = 0; },
    (v) => { v.ready = true; },
  ];
  for (const mutate of wrong) {
    const value = example();
    mutate(value);
    assert.equal((await read(JSON.stringify(value))).kind, 'error', JSON.stringify(value));
  }
  for (const text of [JSON.stringify(example()).replace('"ready":false', '"ready":false,"ready":false'),
    JSON.stringify(example()).replace('"ready":false', '"ready":false,"\\u0072eady":false'), '[]', '{']) {
    assert.equal((await read(text)).kind, 'error', text);
  }
});
