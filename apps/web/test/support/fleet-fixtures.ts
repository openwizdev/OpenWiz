// Synthetic fleets for #125 (spec 3's C1): `openwiz fleets --json` as the
// contract's own example 1 prints it (contracts/fleet.v1.md, "Examples"),
// and variants of it, each kept to the contract's rules (checked by A2's
// C1's original contract checker). Synthetic values
// only. Plus the strict reader's table of good and bad texts.

import { readFileSync } from 'node:fs';

import type { Read } from '../../src/fleetGraph.ts';
import type { FleetsEnvelope } from '../../src/fleets.ts';
import { HOSTILE } from './synthetic.ts';

/** The examples' `freshness.snapshot_at`. */
export const SNAPSHOT_AT = 1793437200000;

const CONTRACT = new URL('../../../../contracts/fleet.v1.md', import.meta.url);

/** The contract's examples, as written: the text of each ```json block, in order. */
export function contractExamples(): string[] {
  return [...readFileSync(CONTRACT, 'utf8').matchAll(/```json\n([\s\S]*?)\n```/g)].map((m) => m[1] ?? '');
}

/** Example 1: `fleets`, complete. */
export function fleetsExample(): string {
  const text = contractExamples()[0];
  if (text === undefined) throw new Error('contracts/fleet.v1.md has no example 1');
  return text;
}

function edited(change: (doc: FleetsEnvelope) => void): string {
  const doc: FleetsEnvelope = JSON.parse(fleetsExample());
  change(doc);
  return JSON.stringify(doc);
}

function read(doc: FleetsEnvelope, id: string): Read {
  const r = doc.reads.find((x) => x.id === id);
  if (r === undefined) throw new Error(`example 1 has no read ${id}`);
  return r;
}

const failRead = (doc: FleetsEnvelope, id: string, reason: string) => {
  read(doc, id).outcome = { state: 'failed', gap: 'command_failed', reason };
};

function fleet(doc: FleetsEnvelope, spec: number) {
  const f = doc.data.fleets.find((x) => x.spec === spec);
  if (f === undefined) throw new Error(`example 1 has no fleet ${spec}`);
  return f;
}

function ticket(doc: FleetsEnvelope, number: number) {
  const t = doc.data.tickets.find((x) => x.number === number);
  if (t === undefined) throw new Error(`example 1 has no ticket ${number}`);
  return t;
}

/**
 * #955's checks (r40) failed: #910's state is unread, so #901's progress is
 * too. "Needs you" doesn't require them: it stays known.
 */
export function fleetsChecksFailed(): string {
  return edited((doc) => {
    failRead(doc, 'r40', 'the checks of pull request 955 couldn\'t be read');
    ticket(doc, 910).state = { unread: ['r40'] };
    fleet(doc, 901).progress = { unread: ['r40'] };
    doc.coverage = { state: 'partial' };
  });
}

/**
 * Partial everywhere it shows: the spec list read in part (r3), so "Needs
 * you" and every blocker's fleet are unread; #930's own issue unreadable
 * (r48), so its name is unknown; and #955's checks failed (r40), so #901's
 * progress is unread.
 */
export function fleetsPartial(): string {
  return edited((doc) => {
    read(doc, 'r3').outcome = { state: 'partial', gap: 'truncated', reason: 'GitHub listed 2 of 3 specs', value: [901, 930] };
    read(doc, 'r48').outcome = { state: 'failed', gap: 'not_found', reason: '#930 couldn\'t be read' };
    failRead(doc, 'r40', 'the checks of pull request 955 couldn\'t be read');
    ticket(doc, 910).state = { unread: ['r40'] };
    fleet(doc, 901).progress = { unread: ['r40'] };
    for (const b of doc.data.blockers) b.fleet = { unread: ['r3'] };
    doc.data.needs_you = { unread: ['r3'] };
    doc.coverage = { state: 'partial' };
  });
}

/** The spec list couldn't be read at all: no fleet is listed, and "Needs you" is unread. */
export function fleetsListFailed(): string {
  return edited((doc) => {
    doc.reads = doc.reads.slice(0, 3);
    failRead(doc, 'r3', 'the spec list couldn\'t be read');
    doc.data.fleets = [];
    doc.data.tickets = [];
    doc.data.blockers = [];
    doc.data.needs_you = { unread: ['r3'] };
    doc.coverage = { state: 'partial' };
  });
}

/** A complete read that lists no fleet. */
export function fleetsEmpty(): string {
  return edited((doc) => {
    doc.reads = doc.reads.slice(0, 3);
    read(doc, 'r3').outcome = { state: 'complete', value: [] };
    doc.data.fleets = [];
    doc.data.tickets = [];
    doc.data.blockers = [];
    doc.data.needs_you = { known: [] };
  });
}

/** Example 1, with hostile text in the titles it shows (the specs' and the "needs you" tickets'). */
export function fleetsHostile(): string {
  const titles = new Map([
    ['r4', HOSTILE.html],
    ['r48', HOSTILE.bidi],
    ['r15', HOSTILE.script],
    ['r28', HOSTILE.link],
  ]);
  return edited((doc) => {
    for (const r of doc.reads) {
      const title = titles.get(r.id);
      if (title !== undefined && r.kind === 'issue' && r.outcome.state === 'complete') r.outcome.value.title = title;
    }
  });
}

/** Example 1, with long, unbroken titles: for the renders and the overlap proof. */
export function fleetsLong(): string {
  return edited((doc) => {
    for (const r of doc.reads) {
      if (r.kind !== 'issue' || r.outcome.state !== 'complete') continue;
      if (r.id === 'r4') r.outcome.value.title = `Synthetic spec with a long name ${'that goes on '.repeat(8)}to the end`;
      if (r.id === 'r48') r.outcome.value.title = `Synthetic${'-unbroken'.repeat(16)}`;
    }
  });
}

/** Every good text the strict reader must take, by name. */
export function goodTexts(): [string, string][] {
  return [
    ['example 1', fleetsExample()],
    ['checks failed', fleetsChecksFailed()],
    ['partial', fleetsPartial()],
    ['list failed', fleetsListFailed()],
    ['empty', fleetsEmpty()],
    ['hostile', fleetsHostile()],
    ['long', fleetsLong()],
    ['example 1, whitespace-free', JSON.stringify(JSON.parse(fleetsExample()))],
    ['a known question and risk', fleetsAnswered()],
  ];
}

/**
 * #539: example 1 with #907's question and risk known, as `openwiz fleet
 * <spec>` would report them (the fleets view itself reads no comments).
 * Synthetic values only.
 */
export function fleetsAnswered(): string {
  return held907With((i) => {
    i['wording'] = { known: 'Needs you: choose synthetic option B' };
    i['link'] = { known: 'https://example.invalid/synthetic/issues/907#issuecomment-1' };
    i['asked_at'] = { known: 1793433600000 };
    i['risk'] = { known: 'release' };
  });
}

/** Example 1's #907 "needs you" item, as written (#539: with its four facts). */
function held907(): string {
  const m = /\{"kind": "held", "spec": 901, "ticket": 907, .*?"risk": \{"unknown": "[^"]*"\}\}/.exec(fleetsExample());
  if (m === null) throw new Error('example 1 has no #907 "needs you" item');
  return m[0];
}

/** Example 1 with #907's item changed by `change`, which must change it. */
function held907With(change: (item: Record<string, unknown>) => void): string {
  const item: Record<string, unknown> = JSON.parse(held907());
  change(item);
  return swap(held907(), JSON.stringify(item));
}

/** Example 1's text with `old` replaced once, exactly. */
function swap(old: string, now: string): string {
  const text = fleetsExample();
  const at = text.indexOf(old);
  if (at < 0 || text.indexOf(old, at + 1) >= 0) throw new Error(`not exactly once in example 1: ${old}`);
  return text.slice(0, at) + now + text.slice(at + old.length);
}

/**
 * One bad text: its name, the text, and where the reader must refuse it
 * (`$` for the whole text, otherwise the value's path). `schema`: A2's
 * strict reader and schema's verdict on the same text. It refuses every row
 * but two, each a deliberate difference: an integer JavaScript can't hold
 * exactly (the reader fails closed), and the fleet view (a contract
 * document, but not the fleets view this reader reads).
 */
export type BadText = { name: string; text: string; at: string; schema: 'refuses' | 'accepts' };

export function badTexts(): BadText[] {
  const bad = (name: string, text: string, at: string, schema: BadText['schema'] = 'refuses'): BadText => ({ name, text, at, schema });
  return [
    // Not one JSON value.
    bad('empty text', '', '$'),
    bad('trailing comma', swap('"view": "fleets",', '"view": "fleets",,'), '$'),
    bad('a comment', swap('"view": "fleets",', '"view": "fleets", /* c */'), '$'),
    bad('single quotes', swap('"view": "fleets"', '\'view\': "fleets"'), '$'),
    bad('two values', `${fleetsExample()} {}`, '$'),
    bad('a byte-order mark', `﻿${fleetsExample()}`, '$'),
    bad('NaN', swap('"snapshot_at": 1793437200000', '"snapshot_at": NaN'), '$'),
    bad('Infinity', swap('"snapshot_at": 1793437200000', '"snapshot_at": Infinity'), '$'),
    bad('a number too large for a float', swap('"snapshot_at": 1793437200000', '"snapshot_at": 1e999'), '$'),
    bad('a leading zero', swap('"snapshot_at": 1793437200000', '"snapshot_at": 01793437200000'), '$'),
    bad('a lone surrogate, escaped', swap('"Synthetic spec one"', '"Synthetic \\ud800 one"'), '$'),
    bad('a raw control character', swap('"Synthetic spec one"', '"Synthetic\tspec one"'), '$'),
    bad('nested a hundred deep', `${'['.repeat(100)}${']'.repeat(100)}`, '$'),
    // Exact keys, each once.
    bad('a duplicate key', swap('"view": "fleets",', '"view": "fleets", "view": "fleets",'), '$.data.view'),
    bad('a missing key', swap('"specs": "r3",', ''), '$.data.specs'),
    bad('an extra key', swap('"specs": "r3",', '"specs": "r3", "title": "x",'), '$.data.title'),
    bad('a key of another kind of read', swap('{"id": "r5", "kind": "sub_issues", "spec": 901,', '{"id": "r5", "kind": "sub_issues", "issue": 901,'), '$.reads[4].issue'),
    // Integers only as JSON integers.
    bad('an integer written 901.0', swap('"spec": 901,\n        "issue": "r4"', '"spec": 901.0,\n        "issue": "r4"'), '$.data.fleets[0].spec'),
    bad('an integer written 9.01e2', swap('"spec": 901,\n        "issue": "r4"', '"spec": 9.01e2,\n        "issue": "r4"'), '$.data.fleets[0].spec'),
    bad('an integer as a string', swap('"spec": 901,\n        "issue": "r4"', '"spec": "901",\n        "issue": "r4"'), '$.data.fleets[0].spec'),
    bad('an integer as a bool', swap('"spec": 901,\n        "issue": "r4"', '"spec": true,\n        "issue": "r4"'), '$.data.fleets[0].spec'),
    bad('a spec of 0', swap('"spec": 901,\n        "issue": "r4"', '"spec": 0,\n        "issue": "r4"'), '$.data.fleets[0].spec'),
    bad('a negative count', swap('"tickets": 2, "ready": 1', '"tickets": 2, "ready": -1'), '$.data.fleets[1].progress.known.ready'),
    bad('an integer past 2^53', swap('"snapshot_at": 1793437200000', '"snapshot_at": 9007199254740993'), '$.freshness.snapshot_at', 'accepts'),
    // An enum only as its one string.
    bad('a state spelled MERGED', swap('"state": {"known": "merged"}', '"state": {"known": "MERGED"}'), '$.data.tickets[0].state.known'),
    bad('a state as a tagged object', swap('"state": {"known": "merged"}', '"state": {"known": {"merged": null}}'), '$.data.tickets[0].state.known'),
    bad('a needs-you kind as a tagged object', swap('{"kind": "held", "spec": 901, "ticket": 907,', '{"kind": {"held": {}}, "spec": 901, "ticket": 907,'), '$.data.needs_you.known[1].kind'),
    // #539: a "needs you" item's four facts, each required and each a fact.
    bad('a needs-you item without its risk', held907With((i) => delete i['risk']), '$.data.needs_you.known[1].risk'),
    bad('a needs-you item with a key of its own', held907With((i) => (i['question'] = 'x')), '$.data.needs_you.known[1].question'),
    bad('a needs-you risk spelled safe', held907With((i) => (i['risk'] = { known: 'safe' })), '$.data.needs_you.known[1].risk.known'),
    bad('a needs-you asked time as a string', held907With((i) => (i['asked_at'] = { known: '1793437200000' })), '$.data.needs_you.known[1].asked_at.known'),
    bad('a needs-you wording, empty', held907With((i) => (i['wording'] = { known: '' })), '$.data.needs_you.known[1].wording.known'),
    bad('a needs-you fact with an empty reason', held907With((i) => (i['link'] = { unknown: '' })), '$.data.needs_you.known[1].link.unknown'),
    bad('a needs-you fact in both forms', held907With((i) => (i['wording'] = { known: 'x', unknown: 'y' })), '$.data.needs_you.known[1].wording'),
    bad('an unknown gap kind', swap('"outcome": {"state": "complete", "value": "2.100.0"}', '"outcome": {"state": "failed", "gap": "flaky", "reason": "x"}'), '$.reads[0].outcome.gap'),
    bad('a read of an unknown kind', swap('{"id": "r2", "kind": "repository"', '{"id": "r2", "kind": "repo"'), '$.reads[1].kind'),
    bad('another schema', swap('"schema": "openwiz.fleet.v1"', '"schema": "openwiz.fleet.v2"'), '$.schema'),
    // A list or an object only from its own JSON type.
    bad('a positional array for an object', swap(held907(), '["held", 901, 907]'), '$.data.needs_you.known[1]'),
    bad('an object for a list', swap('"fleets": [', '"fleets": {"0": [').replace(/\],\n {4}"tickets": \[/, ']},\n    "tickets": ['), '$.data.fleets'),
    // A worked-out value only in one of its forms, exactly one key.
    bad('a bare value for a worked-out one', swap('"progress": {"known": {"tickets": 2,', '"progress": {"tickets": 2,').replace('"unknown": 0}}\n      }', '"unknown": 0}\n      }'), '$.data.fleets[1].progress'),
    bad('two forms at once', swap('"state": {"known": "merged"}', '"state": {"known": "merged", "unread": ["r9"]}'), '$.data.tickets[0].state'),
    bad('an unknown form on progress', swap('"progress": {"known": {"tickets": 2,', '"progress": {"unknown": "x", "k": {"tickets": 2,'), '$.data.fleets[1].progress'),
    bad('an empty reason', swap('"state": {"unknown": "closed on GitHub, and no merge was read back"}', '"state": {"unknown": ""}'), '$.data.tickets[7].state.unknown'),
    // null only where the schema has it.
    bad('a null pointer', swap('"specs": "r3",', '"specs": null,'), '$.data.specs'),
    bad('a null title', swap('"title": "Synthetic spec one"', '"title": null'), '$.reads[3].outcome.value.title'),
    // Strings in their exact form.
    bad('a read id without digits', swap('"specs": "r3",', '"specs": "r",'), '$.data.specs'),
    bad('a read id of another form', swap('"specs": "r3",', '"specs": "x3",'), '$.data.specs'),
    bad('a read id with a newline', swap('"specs": "r3",', '"specs": "r3\\n",'), '$.data.specs'),
    bad('a commit in capitals', swap('"head_commit": "1111111111111111111111111111111111111111"', '"head_commit": "A111111111111111111111111111111111111111"'), '$.reads[7].outcome.value.head_commit'),
    bad('a commit of 39 digits', swap('"head_commit": "1111111111111111111111111111111111111111"', '"head_commit": "111111111111111111111111111111111111111"'), '$.reads[7].outcome.value.head_commit'),
    bad('empty owned paths', swap('"owned_paths": "`contracts/example.v1.md`"', '"owned_paths": ""'), '$.reads[5].outcome.value.owned_paths'),
    bad('an empty label', swap('"labels": ["needs-info", "ready-for-agent"]', '"labels": ["", "ready-for-agent"]'), '$.reads[14].outcome.value.labels[0]'),
    // Outcomes.
    bad('a partial read of a kind that is never a list', swap('"outcome": {"state": "complete", "value": "2.100.0"}', '"outcome": {"state": "partial", "gap": "truncated", "reason": "x", "value": "2.100.0"}'), '$.reads[0].outcome.state'),
    bad('a failed read with a value', swap('"outcome": {"state": "complete", "value": "2.100.0"}', '"outcome": {"state": "failed", "gap": "timed_out", "reason": "x", "value": "2.100.0"}'), '$.reads[0].outcome.value'),
    bad('a partial gap other than truncated', swap('{"id": "r3", "kind": "spec_list", "outcome": {"state": "complete", "value": [901, 930]}}', '{"id": "r3", "kind": "spec_list", "outcome": {"state": "partial", "gap": "timed_out", "reason": "x", "value": [901, 930]}}'), '$.reads[2].outcome.gap'),
    // Sources.
    bad('another tool\'s name', swap('"name": "gh"', '"name": "git"'), '$.sources.github.name'),
    bad('cloudroom as a bool', swap('"cloudroom": null', '"cloudroom": false'), '$.sources.cloudroom'),
    // The view.
    bad('the fleet view', contractExamples()[1] ?? '', '$.data.view', 'accepts'),
    bad('no view', swap('"view": "fleets",', ''), '$.data.view'),
  ];
}
