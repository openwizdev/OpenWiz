// #129: the optional, server-verified target at the public fleet API seam.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { readFleet, readFleets } from '../../src/fleets.ts';
import { contractExamples } from '../support/fleet-fixtures.ts';

const cases = [
  ['thr_syn_0001', true], ['_syn', true], ['A', true], ['a'.repeat(128), true],
  ['', false], ['-syn', false], ['a'.repeat(129), false], ['syn/other', false],
  ['syn?x', false], [' syn', false], ['syn\n', false], ['syné', false],
  [null, false], [4, false], [true, false], [{ thread: 'thr_syn_0001' }, false], [[], false],
];

test('C5: schema and both strict readers agree on the optional orchestrator ID table', () => {
  const schema = JSON.parse(readFileSync(new URL('../../../../contracts/fleet.v1.schema.json', import.meta.url), 'utf8'));
  const field = schema.$defs.envelope.properties.orchestrator;
  assert.ok(field, 'the contract declares the orchestrator field');
  assert.equal(field.type, 'string');
  assert.equal(schema.$defs.envelope.required.includes('orchestrator'), false);
  for (const [i, example] of contractExamples().entries()) {
    const read = i === 0 ? readFleets : readFleet;
    assert.equal(read(example).ok, true, 'existing CLI envelopes stay valid');
    for (const [id, expected] of cases) {
      const doc = { ...JSON.parse(example), orchestrator: id };
      const schemaSays = typeof id === 'string' && id.length >= field.minLength && id.length <= field.maxLength && new RegExp(field.pattern, 'u').test(id);
      assert.equal(schemaSays, expected, JSON.stringify(id));
      const result = read(JSON.stringify(doc));
      assert.equal(result.ok, expected, JSON.stringify(id));
      if (result.ok) assert.deepEqual(result.envelope, doc);
    }
    assert.equal(read(example.replace('"schema":', '"orchestrator":"thr_syn_0001","orchestrator":"thr_syn_0002","schema":')).ok, false, 'duplicate target is refused');
  }
});

/*
#129 full validation. This hand-back addition is a log only; executable code is unchanged.
{
  "head": "4716f874d5b9d42a104940e0d7fe6632319640dc",
  "privatePruned": true,
  "commands": [
    {
      "folder": ".",
      "command": "sh .github/actions/docs-only/test.sh",
      "exit": 0,
      "seconds": 5.4
    },
    {
      "folder": "apps/web",
      "command": "npm ci --ignore-scripts",
      "exit": 0,
      "seconds": 4.7
    },
    {
      "folder": "apps/web",
      "command": "npm run build",
      "exit": 0,
      "seconds": 11.9
    },
    {
      "folder": "apps/web",
      "command": "npm run typecheck",
      "exit": 0,
      "seconds": 2.9
    },
    {
      "folder": "apps/web",
      "command": "npm run check",
      "exit": 0,
      "seconds": 1.5
    },
    {
      "folder": ".",
      "command": "cargo fmt --check",
      "exit": 0,
      "seconds": 0.8
    },
    {
      "folder": ".",
      "command": "cargo clippy --workspace --all-targets -- -D warnings",
      "exit": 0,
      "seconds": 1.6
    },
    {
      "folder": ".",
      "command": "cargo build --workspace",
      "exit": 0,
      "seconds": 1.3
    },
    {
      "folder": ".",
      "command": "cargo test --workspace",
      "exit": 0,
      "seconds": 130.4
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
      "seconds": 2.3
    },
    {
      "folder": "apps/web",
      "command": "npm test",
      "exit": 0,
      "seconds": 254.9
    }
  ]
}
*/
