// #128 fixture proof at the public API seam. Expected shapes come from the
// contract's literal examples, never from the parser under test.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as api from '../../src/api.ts';
import { contractExamples, fleetsExample } from '../support/fleet-fixtures.ts';

const detail = contractExamples()[1];
const other = contractExamples()[2];
const signal = () => new AbortController().signal;
function response(body, { status = 200, type = 'application/json' } = {}) {
  return async () => ({ type: 'basic', status, headers: { get: (key) => key === 'Content-Type' ? type : null }, text: async () => body });
}

test('C4 API readers preserve contract list/detail examples and use only same-origin GETs', async () => {
  assert.equal(typeof api.readFleetView, 'function', 'the API has a validated fleet-detail reader');
  for (const [spec, body] of [[null, fleetsExample()], [901, detail], [930, other]]) {
    const calls = [];
    const read = async (url, init) => { calls.push({ url, init }); return response(body)(); };
    const s = signal();
    const result = spec === null ? await api.readFleetsView(read, s) : await api.readFleetView(read, spec, s);
    assert.equal(result.kind, 'ok');
    assert.deepEqual(result.envelope, JSON.parse(body));
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, spec === null ? '/api/v1/fleets' : `/api/v1/fleets/${spec}`);
    assert.deepEqual(calls[0].init, { method: 'GET', headers: api.REQUEST_HEADERS, credentials: 'same-origin', redirect: 'manual', cache: 'no-store', signal: s });
  }
});

test('C4 detail refuses wrong views, mismatched spec, duplicate keys, noninteger syntax and malformed fields', async () => {
  assert.equal(typeof api.readFleetView, 'function', 'the API has a validated fleet-detail reader');
  const edit = (fn) => { const value = JSON.parse(detail); fn(value); return JSON.stringify(value); };
  const bad = [
    ['list view', fleetsExample()],
    ['another spec', other],
    ['array', `[${detail}]`],
    ['duplicate key', detail.replace('"schema":', '"schema":"openwiz.fleet.v1","schema":')],
    ['floating integer', detail.replace('"spec": 901', '"spec": 901.0')],
    ['exponent integer', detail.replace('"spec": 901', '"spec": 901e0')],
    ['extra key', edit((d) => { d.extra = true; })],
    ['missing builder', edit((d) => { delete d.data.tickets[0].builder; })],
    ['null cloudroom', edit((d) => { d.sources.cloudroom = null; })],
    ['tagged enum', edit((d) => { d.data.tickets[0].state = { known: { building: null } }; })],
    ['wrong reviewer', edit((d) => { d.data.tickets[0].reviewer = { undefined: 4 }; })],
    ['wrong unplaced', edit((d) => { d.data.unplaced = { known: [{ thread: 'synthetic', reason: 'maybe' }] }; })],
  ];
  for (const [name, body] of bad) {
    assert.notEqual(body, detail, `${name}: the mutation changed the fixture`);
    const result = await api.readFleetView(response(body), 901, signal());
    assert.equal(result.kind, 'error', name);
  }
  const html = await api.readFleetView(response(detail, { type: 'text/html' }), 901, signal());
  assert.equal(html.kind, 'error', 'JSON carried as HTML is refused');
  const listDuplicate = fleetsExample().replace('"schema":', '"schema":"openwiz.fleet.v1","schema":');
  assert.equal((await api.readFleetsView(response(listDuplicate), signal())).kind, 'error');
});

/*
#128 final validation log; this hand-back change adds no executable code.
{
  "head": "553e86e6105ef3861bac582d90e10ca3139d5580",
  "privatePruned": true,
  "commands": [
    {
      "folder": ".",
      "command": "sh .github/actions/docs-only/test.sh",
      "exit": 0,
      "seconds": 6.0
    },
    {
      "folder": "apps/web",
      "command": "npm ci --ignore-scripts",
      "exit": 0,
      "seconds": 4.6
    },
    {
      "folder": "apps/web",
      "command": "npm run build",
      "exit": 0,
      "seconds": 13.3
    },
    {
      "folder": "apps/web",
      "command": "npm run typecheck",
      "exit": 0,
      "seconds": 3.5
    },
    {
      "folder": "apps/web",
      "command": "npm run check",
      "exit": 0,
      "seconds": 1.7
    },
    {
      "folder": ".",
      "command": "cargo fmt --check",
      "exit": 0,
      "seconds": 0.9
    },
    {
      "folder": ".",
      "command": "cargo clippy --workspace --all-targets -- -D warnings",
      "exit": 0,
      "seconds": 16.1
    },
    {
      "folder": ".",
      "command": "cargo build --workspace",
      "exit": 0,
      "seconds": 23.4
    },
    {
      "folder": ".",
      "command": "cargo test --workspace",
      "exit": 0,
      "seconds": 167.4
    },
    {
      "folder": ".",
      "command": "cargo test -p openwiz-tests --test checks pending",
      "exit": 0,
      "seconds": 0.1
    },
    {
      "folder": ".",
      "command": "cargo build --release",
      "exit": 0,
      "seconds": 5.7
    },
    {
      "folder": "apps/web",
      "command": "npm test",
      "exit": 0,
      "seconds": 247.4
    }
  ],
  "webTestCounts": [
    146,
    204
  ],
  "c4Proofs": "12 passed; fake clock and synthetic fixtures only",
  "schemaCrosscheck": [
    "914 cases: detail reader agrees with the schema plus fleet.v1.md view_sources rule.",
    "2 cases are schema-valid but refused by the documented fleet source rule (CloudRoom must be an object)."
  ],
  "helpers": [
    {
      "role": "scout",
      "head": "9f1caaf050916001c2e0cbc62985dfaf346c03b1",
      "used": 10,
      "ignored": 0,
      "wrong": 0,
      "result": "interfaces and missing detail reader verified"
    },
    {
      "role": "spec tracer / precedent finder",
      "head": "9f1caaf050916001c2e0cbc62985dfaf346c03b1",
      "used": 8,
      "ignored": 0,
      "wrong": 0,
      "result": "S3-5 seams and harness gaps verified"
    },
    {
      "role": "checklist auditor",
      "head": "22077ee27ad46cdfe7c1c2872f2dc0f4e15d3d11",
      "used": 2,
      "ignored": 0,
      "wrong": 0,
      "result": "both findings reproduced red and fixed"
    }
  ],
  "helperChecks": [
    "clean #128: nothing changed but the writes you named (branches 0, comments 2)",
    "clean #128: nothing changed but the writes you named (branches 0, comments 7)"
  ],
  "gaps": "No live account, real phone gesture or live fleet check. Existing 70-second lane bound retained."
}
*/
