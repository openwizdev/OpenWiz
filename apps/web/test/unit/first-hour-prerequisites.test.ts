// #2516: fixture proofs at the exported firstHour presentation boundary.
// Existing fleet cases omit unavailable setup with a last-ready report and
// positive work evidence in another lane. No fixture establishes live work.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { readSetup } from '../../src/api.ts';
import { readDecisionsText } from '../../src/decisions.ts';
import { readFleet } from '../../src/fleets.ts';
import type { FirstHourProps } from '../../src/components/FirstHour.tsx';

registerHooks({ load(url, context, nextLoad) {
  if (!url.startsWith('file:') || !url.endsWith('.tsx')) return nextLoad(url, context);
  const file = fileURLToPath(url);
  const compilerOptions = { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, verbatimModuleSyntax: true };
  return { format: 'module', source: ts.transpileModule(readFileSync(file, 'utf8'), { fileName: file, compilerOptions }).outputText, shortCircuit: true };
} });
const { firstHour } = await import('../../src/components/FirstHour.tsx');
// Load the existing synthetic fixture module at runtime, as other unit tests
// load .mjs support, without adding JavaScript files to the app's typecheck.
const { NOW, STATES } = await import(new URL('../fixtures/first-hour-pages/states.mjs', import.meta.url).href);
const setup = await readSetup(async () => new Response(STATES.start.setup.text, { headers: { 'content-type': 'application/json' } }), new AbortController().signal);
assert.notEqual(setup, 'stopped');
if (setup === 'stopped') throw new Error('setup fixture stopped');
assert.equal(setup.kind, 'ok');
if (setup.kind !== 'ok') throw new Error('setup fixture refused');
const empty = readDecisionsText(STATES.start.decisions.text);
const grill = readDecisionsText(STATES.grill.decisions.text);
const fleet = readFleet(STATES.progress.fleet.text);
assert.ok(empty.ok && grill.ok && fleet.ok, 'existing fixtures parse');
if (!empty.ok || !grill.ok || !fleet.ok) throw new Error('work fixture refused');
const READY = setup.envelope;
const EMPTY = empty.decisions;
const GRILL = grill.decisions;
const FLEET = fleet.envelope;
const base = (): FirstHourProps => ({ now: NOW, setup: { state: 'read', value: READY }, decisions: { state: 'read', value: EMPTY }, fleet: { state: 'read', value: null }, receipts: new Map() });
const idea = (p: FirstHourProps) => firstHour(p).steps.find((s) => s.id === 'idea')!;
const WHY = 'Synthetic: prerequisite unavailable.';

// Each unavailable prerequisite is isolated: all other lanes positively
// establish the fresh-user case. A last-ready/empty report cannot grant it.
const unavailable: [string, Partial<FirstHourProps>, string][] = [
  ['setup reading', { setup: { state: 'reading' } }, 'reading'],
  ['setup failed without a last report', { setup: { state: 'failed', why: WHY, last: null } }, 'unknown'],
  ['setup failed after ready', { setup: { state: 'failed', why: WHY, last: READY } }, 'unknown'],
  ['setup failed after not ready', { setup: { state: 'failed', why: WHY, last: { ...READY, ready: false } } }, 'unknown'],
  ['decisions reading', { decisions: { state: 'reading' } }, 'reading'],
  ['decisions failed without a last report', { decisions: { state: 'failed', why: WHY, last: null } }, 'unknown'],
  ['decisions failed after empty', { decisions: { state: 'failed', why: WHY, last: EMPTY } }, 'unknown'],
  ['fleet reading', { fleet: { state: 'reading' } }, 'unknown'],
  ['fleet failed without a last report', { fleet: { state: 'failed', why: WHY, last: null } }, 'unknown'],
  ['fleet failed with a last report', { fleet: { state: 'failed', why: WHY, last: FLEET } }, 'unknown'],
];
for (const [name, lanes, word] of unavailable) test(`#2516: ${name} keeps the first idea unavailable`, () => {
  const s = idea({ ...base(), ...lanes });
  assert.equal(s.word, word);
  assert.equal(s.tier, 't5');
  assert.equal(s.next, 'Refresh before giving it again.');
});

test('#2516: only current ready setup and fresh complete empty decisions with a successful no-fleet read invite the idea', () => {
  assert.equal(idea(base()).word, 'your turn');
  const notReady = { ...READY, ready: false };
  assert.equal(idea({ ...base(), setup: { state: 'read', value: notReady } }).word, 'waiting');
  for (const decisions of [
    { ...EMPTY, coverage: { state: 'partial' as const, gaps: [{ kind: 'timed_out' as const, detail: WHY }] } },
    { ...EMPTY, freshness: { state: 'stale' as const, snapshot_at: { known: NOW - 60_000 } } },
  ]) {
    assert.equal(idea({ ...base(), decisions: { state: 'read', value: decisions } }).word, 'unknown');
  }
});

// Positive work in a successful read stays visible when another read is
// unavailable. Failed lanes still retain #2786's unknown-state contract.
const positive: [string, Partial<FirstHourProps>][] = [
  ['current fleet while decisions read', { decisions: { state: 'reading' }, fleet: { state: 'read', value: FLEET } }],
  ['current fleet while setup fails', { setup: { state: 'failed', why: WHY, last: READY }, fleet: { state: 'read', value: FLEET } }],
  ['current fleet while decisions fail', { decisions: { state: 'failed', why: WHY, last: null }, fleet: { state: 'read', value: FLEET } }],
  ['current grill while setup fails', { setup: { state: 'failed', why: WHY, last: READY }, decisions: { state: 'read', value: GRILL } }],
  ['current grill while fleet fails', { decisions: { state: 'read', value: GRILL }, fleet: { state: 'failed', why: WHY, last: null } }],
];
for (const [name, lanes] of positive) test(`#2516: ${name} preserves known idea arrival`, () => {
  const s = idea({ ...base(), ...lanes });
  assert.equal(s.word, 'done');
  assert.equal(s.tier, 't2');
  assert.equal(firstHour({ ...base(), ...lanes }).merge.state, lanes.fleet?.state === 'failed' ? 'unknown' : 'none');
});
