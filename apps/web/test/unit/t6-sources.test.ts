// #539 (0.0.10 T6): the web readers accept exactly the new source facts, and
// the fleets model shows each one, or "unknown" with its reason. A "needs
// you" item's four facts (wording, link, asked_at, risk) are required; an
// issue read's pending_question and a session's started_at are optional.
// Synthetic values only; a fixture test never proves live behaviour.

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { parseInventory, parseSessionView } from '../../src/envelope.ts';
import type { Session } from '../../src/envelope.ts';
import { fleetsList, readFleet, readFleets } from '../../src/fleets.ts';
import { fleetsAnswered, fleetsExample, contractExamples } from '../support/fleet-fixtures.ts';
import { inventory, session, sessionView, T0 } from '../support/synthetic.ts';

const NOT_READ = 'the fleets view does not read comments; openwiz fleet <spec> reads the question';
const NO_RISK = 'no explicit risk classification was reported';

/** The contract's fleet view example (`openwiz fleet 901`), whose issue reads may carry a question. */
function fleetExample(): string {
  const text = contractExamples().find((t) => JSON.parse(t).data?.view === 'fleet' && JSON.parse(t).data.needs_you.known?.length > 0);
  if (text === undefined) throw new Error('contracts/fleet.v1.md has no fleet example with a "needs you" item');
  return text;
}

test("T6 fleet question facts preserve reported values and strict optional shape", async (t) => {
  for (const [name, proof] of [
    ['T6 reader: every contract example with "needs you" items is read, with the four facts as written', () => {
      const fleets = readFleets(fleetsExample());
      assert.ok(fleets.ok, JSON.stringify(!fleets.ok && fleets.refusal));
      const fleet = readFleet(fleetExample());
      assert.ok(fleet.ok, JSON.stringify(!fleet.ok && fleet.refusal));
      const [first] = 'known' in fleets.envelope.data.needs_you ? fleets.envelope.data.needs_you.known : [];
      assert.deepEqual(first, { kind: 'needs_info', spec: 901, ticket: 904, wording: { unknown: NOT_READ }, link: { unknown: NOT_READ }, asked_at: { unknown: NOT_READ }, risk: { unknown: NO_RISK } });
    }],
    ['T6 model: an unread question shows once, unknown with why, and an unreported risk is unknown, never safe', () => {
      const r = readFleets(fleetsExample());
      assert.ok(r.ok);
      const m = fleetsList(r.envelope);
      assert.ok(m.needsYou.kind === 'items');
      for (const item of m.needsYou.items) {
        assert.deepEqual(item.question, { text: `question unknown (${NOT_READ})`, unknown: true });
        assert.equal(item.link, null, 'the same reason is not repeated');
        assert.equal(item.asked, null, 'the same reason is not repeated');
        assert.deepEqual(item.risk, { text: `risk unknown (${NO_RISK})`, unknown: true });
      }
    }],
    ['T6 model: a known question shows its first line, link, asked time (UTC) and labelled risk as reported', () => {
      const r = readFleets(fleetsAnswered());
      assert.ok(r.ok, JSON.stringify(!r.ok && r.refusal));
      const m = fleetsList(r.envelope);
      assert.ok(m.needsYou.kind === 'items');
      const item = m.needsYou.items.find((i) => i.ticket === 907);
      assert.ok(item);
      assert.deepEqual(
        { question: item.question, link: item.link, asked: item.asked, risk: item.risk },
        {
          question: { text: 'Needs you: choose synthetic option B', unknown: false },
          link: { text: 'https://example.invalid/synthetic/issues/907#issuecomment-1', unknown: false },
          // 1793433600000 ms is 2026-10-31T08:00:00Z.
          asked: { text: 'asked 2026-10-31 08:00 UTC', unknown: false },
          risk: { text: 'risk: release', unknown: false },
        },
      );
    }],
    ['T6 reader: an issue read\'s pending_question is optional, and exact when present', () => {
      const doc = JSON.parse(fleetExample());
      const issueRead = doc.reads.find((r: { kind: string; outcome: { state: string } }) => r.kind === 'issue' && r.outcome.state === 'complete');
      const question = { wording: 'Needs you: synthetic', link: 'https://example.invalid/synthetic/issues/904#issuecomment-2', asked_at: 1793433600000 };
      issueRead.outcome.value.pending_question = question;
      const ok = readFleet(JSON.stringify(doc));
      assert.ok(ok.ok, JSON.stringify(!ok.ok && ok.refusal));
      const read = ok.envelope.reads.find((r) => r.id === issueRead.id);
      assert.deepEqual(read?.kind === 'issue' && read.outcome.state === 'complete' ? read.outcome.value.pending_question : null, question);

      const at = `$.reads[${doc.reads.indexOf(issueRead)}].outcome.value.pending_question`;
      for (const [name, bad, where] of [
        ['an extra key', { ...question, author: 'x' }, `${at}.author`],
        ['a missing link', { wording: question.wording, asked_at: question.asked_at }, `${at}.link`],
        ['an empty wording', { ...question, wording: '' }, `${at}.wording`],
        ['a time as a string', { ...question, asked_at: '1793433600000' }, `${at}.asked_at`],
        ['null for absent', null, at],
      ] as const) {
        issueRead.outcome.value.pending_question = bad;
        const r = readFleet(JSON.stringify(doc));
        assert.ok(!r.ok, name);
        assert.equal(r.refusal.at, where, name);
      }
    }],
  ] as const) {
    t.diagnostic(name);
    await proof();
  }
});

const started = (s: Session, startedAt: unknown): Session => ({ ...s, started_at: startedAt } as Session);

test('T6 inventory: a session\'s started_at is optional, read as a fact: known milliseconds or unknown with why', () => {
  const good = [
    session(1),
    started(session(2), { known: T0 - 3_600_000 }),
    started(session(3), { unknown: 'room-cli did not report a start time' }),
  ];
  const inv = inventory(good);
  assert.deepEqual(parseInventory(structuredClone(inv)), inv);
  for (const s of good) {
    const v = sessionView(s);
    assert.deepEqual(parseSessionView(structuredClone(v)), v);
  }
  for (const bad of [{ known: '1799910000000' }, { known: 1.5 }, { unknown: 7 }, { known: 1, unknown: 'x' }, null, 1799910000000]) {
    assert.equal(parseInventory(inventory([started(session(1), bad)])), null, JSON.stringify(bad));
    assert.equal(parseSessionView(sessionView(started(session(1), bad))), null, JSON.stringify(bad));
  }
});
