// #829: synthetic fixtures at the public readFleet → fleetModel seam.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { fleetModel } from '../../src/fleetGraph.ts';
import { readFleet } from '../../src/fleets.ts';
import { contractExample } from '../support/fleet-graph-fixtures.ts';

test("Single-fleet read IDs preserve valid examples and reject duplicate identities", async (t) => {
  for (const [name, proof] of [
    ['single-fleet reader: unique read ids preserve the contract examples and their titles', () => {
      for (const example of [2, 3] as const) {
        const fixture = contractExample(example);
        const parsed = readFleet(JSON.stringify(fixture), fixture.data.fleet.spec);
        assert.ok(parsed.ok);
        assert.deepEqual(parsed.envelope, fixture);
        if (example === 2) {
          const model = fleetModel(parsed.envelope);
          assert.deepEqual(model.title, { text: 'Synthetic spec one', unknown: false });
          assert.deepEqual(model.tickets[0]?.title, { text: 'Synthetic ticket A1', unknown: false });
        }
      }
    }],
    ['single-fleet reader: refuses duplicate ids across fixture read kinds, even identical records', () => {
      const fixture = contractExample(2);
      for (const read of fixture.reads) {
        const duplicate = { ...fixture, reads: [...fixture.reads, read] };
        const parsed = readFleet(JSON.stringify(duplicate), fixture.data.fleet.spec);
        assert.equal(parsed.ok, false, `duplicate ${read.kind} id ${read.id} must be refused`);
        if (!parsed.ok) {
          assert.equal(parsed.refusal.at, `$.reads[${fixture.reads.length}].id`);
          assert.match(parsed.refusal.why, /duplicate read id/);
        }
      }
    }],
    ['single-fleet reader: refuses a duplicate id shared by different read kinds', () => {
      const fixture = contractExample(2);
      const repository = fixture.reads.find((read) => read.kind === 'repository');
      assert.ok(repository);
      fixture.reads.push({ id: repository.id, kind: 'projects', outcome: { state: 'complete', value: [] } });
      const parsed = readFleet(JSON.stringify(fixture), fixture.data.fleet.spec);
      assert.ok(!parsed.ok);
      assert.equal(parsed.refusal.at, `$.reads[${fixture.reads.length - 1}].id`);
      assert.match(parsed.refusal.why, /duplicate read id/);
    }],
  ] as const) {
    t.diagnostic(name);
    await proof();
  }
});

test("Single-fleet duplicate IDs reject conflicting fleet and ticket titles in either order", async (t) => {
  for (const subject of ['fleet', 'ticket'] as const) {
    for (const order of ['first', 'last'] as const) {
      const name = `single-fleet reader: refuses a conflicting ${subject} title with its duplicate ${order}`;
      const proof = () => {
        const fixture = contractExample(2);
        const id = subject === 'fleet' ? fixture.data.fleet.issue : fixture.data.tickets[0]?.issue;
        const originalIndex = fixture.reads.findIndex((read) => read.id === id);
        const original = fixture.reads[originalIndex];
        assert.ok(original?.kind === 'issue' && original.outcome.state === 'complete');
        const conflicting = {
          ...original,
          outcome: { state: 'complete' as const, value: { ...original.outcome.value, title: 'Conflicting title' } },
        };
        if (order === 'first') fixture.reads.unshift(conflicting);
        else fixture.reads.push(conflicting);
        const parsed = readFleet(JSON.stringify(fixture), fixture.data.fleet.spec);
        // Follow the caller's boundary: a refused envelope never reaches the model.
        const model = parsed.ok ? fleetModel(parsed.envelope) : null;
        assert.equal(model === null, true, 'ambiguous titles must not become a known fleet or ticket title');
        assert.ok(!parsed.ok);
        assert.equal(parsed.refusal.at, `$.reads[${order === 'first' ? originalIndex + 1 : fixture.reads.length - 1}].id`);
        assert.match(parsed.refusal.why, /duplicate read id/);
      };
      t.diagnostic(name);
      await proof();
    }
  }
});
