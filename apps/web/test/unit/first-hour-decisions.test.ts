// #2514: decision availability at the exported firstHour boundary.
// Existing first-hour cases omit unavailable open requests and elapsed age.
// #2847: and the tab-storage refusal Decisions applies before availability.
// Synthetic fixtures prove presentation only, never live acceptance.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { readSetup } from '../../src/api.ts';
import { readDecisionsText, slotsOf } from '../../src/decisions.ts';
import { readFleet } from '../../src/fleets.ts';
import type { FirstHourProps } from '../../src/components/FirstHour.tsx';

registerHooks({ load(url, context, nextLoad) {
  if (!url.startsWith('file:') || !url.endsWith('.tsx')) return nextLoad(url, context);
  const file = fileURLToPath(url);
  const compilerOptions = { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, verbatimModuleSyntax: true };
  return { format: 'module', source: ts.transpileModule(readFileSync(file, 'utf8'), { fileName: file, compilerOptions }).outputText, shortCircuit: true };
} });
const { firstHour } = await import('../../src/components/FirstHour.tsx');
// This tab's storage, as Decisions reads it (window.sessionStorage). Readable
// and empty unless a #2847 case plants a refusal; each case restores it.
const values = new Map<string, string>();
const tabStorage = { get length() { return values.size; }, key: (i: number) => [...values.keys()][i] ?? null, getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => { values.set(k, v); }, removeItem: (k: string) => { values.delete(k); } };
const tab: { sessionStorage?: unknown } = { sessionStorage: tabStorage };
Object.assign(globalThis, { window: tab });
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
const stepOf = (p: FirstHourProps, id: 'idea' | 'approval', time?: { received: { mono: number; wall: number }; now: { mono: number; wall: number } }) => firstHour(p, time).steps.find((s) => s.id === id)!;
const parsedPlan = readDecisionsText(STATES.approval.decisions.text);
assert.ok(parsedPlan.ok);
if (!parsedPlan.ok) throw new Error('plan fixture refused');
const PLAN = parsedPlan.decisions;
const unavailable = (d: typeof PLAN, why: string) => {
  const p = { ...base(), decisions: { state: 'read' as const, value: d } };
  const s = stepOf(p, 'approval');
  assert.equal(s.word, 'unavailable');
  assert.equal(s.tier, 't5');
  assert.ok(s.detail.includes(why), s.detail);
  assert.match(s.next!, /Refresh/);
  assert.doesNotMatch(s.next!, /approve it there|Answer it in Decisions/);
  assert.equal(stepOf(p, 'idea').word, 'done', 'arrival is distinct from answerability');
};

const stale = { state: 'stale' as const, snapshot_at: { known: NOW - 71_000 } };
const unknown = { state: 'unknown' as const, snapshot_at: { unknown: 'Synthetic: source unavailable.' } };
const changed = (over: Partial<typeof PLAN.items[number]>) => ({ ...PLAN, items: [{ ...PLAN.items[0]!, ...over }] });
const target = (over: Partial<typeof PLAN.orchestrator>) => ({ ...PLAN, orchestrator: { ...PLAN.orchestrator, ...over } });
const cases: [string, typeof PLAN, string][] = [
  ['stale decisions', { ...PLAN, freshness: stale }, 'this read is not fresh'],
  ['unknown decision freshness', { ...PLAN, freshness: unknown }, 'this read is not fresh'],
  ['changed wording', changed({ current: { known: false } }), 'wording changed'],
  ['unknown wording', changed({ current: { unknown: 'Synthetic: wording unavailable.' } }), 'wording unavailable'],
  ['unknown risk', changed({ request: { ...PLAN.items[0]!.request, risk: 'unknown' } }), 'risk is not classified'],
  ['missing target', target({ target: { known: null } }), 'orchestrator'],
  ['unknown target', target({ target: { unknown: 'Synthetic: target unavailable.' } }), 'orchestrator'],
  ['partial target check', target({ coverage: { state: 'partial', gaps: [{ kind: 'timed_out', detail: 'Synthetic: target check timed out.' }] } }), 'orchestrator'],
  ['stale target check', target({ freshness: stale }), 'orchestrator check is not fresh'],
  ['unknown target freshness', target({ freshness: unknown }), 'orchestrator check is not fresh'],
];
for (const [name, d, why] of cases) test(`#2514: ${name} cannot invite an answer`, () => unavailable(d, why));

test('#2514: only actionable requests invite answers, including a known request in a partial list', () => {
  for (const d of [PLAN, GRILL, { ...PLAN, coverage: { state: 'partial' as const, gaps: [{ kind: 'timed_out' as const, detail: 'Synthetic: another comment unavailable.' }] } }]) {
    assert.equal(stepOf({ ...base(), decisions: { state: 'read', value: d } }, 'approval').word, 'your turn');
  }
});

for (const kind of ['source', 'orchestrator'] as const) test(`#2514: elapsed ${kind} freshness closes an open answer`, () => {
  const d = kind === 'source' ? PLAN : { ...PLAN, freshness: { state: 'fresh' as const, snapshot_at: { known: NOW } } };
  const p = { ...base(), decisions: { state: 'read' as const, value: d } };
  const received = { mono: 500, wall: NOW };
  assert.equal(stepOf(p, 'approval', { received, now: { mono: 68_500, wall: NOW + 68_000 } }).word, 'your turn');
  const s = stepOf(p, 'approval', { received, now: { mono: 69_500, wall: NOW + 69_000 } });
  assert.equal(s.word, 'unavailable');
  assert.match(s.detail, kind === 'source' ? /this read is not fresh/ : /orchestrator check is not fresh/);
  assert.match(s.next!, /Refresh/);
});

for (const [name, decisions] of [
  ['stale', { state: 'read', value: { ...EMPTY, freshness: stale } }],
  ['unknown freshness', { state: 'read', value: { ...EMPTY, freshness: unknown } }],
  ['partial', { state: 'read', value: { ...EMPTY, coverage: { state: 'partial', gaps: [{ kind: 'timed_out', detail: 'Synthetic: comment unavailable.' }] } } }],
  ['failed', { state: 'failed', why: 'Synthetic: decisions failed.', last: null }],
  ['failed with last empty', { state: 'failed', why: 'Synthetic: refresh failed.', last: EMPTY }],
  ['reading', { state: 'reading' }],
] as [string, FirstHourProps['decisions']][]) test(`#2514: ${name} empty decisions cannot grant an idea or no-approval claim`, () => {
  for (const fleet of [null, FLEET]) {
    const p = { ...base(), decisions, fleet: { state: 'read' as const, value: fleet } };
    const idea = stepOf(p, 'idea');
    assert.equal(idea.word, fleet ? 'done' : name === 'reading' ? 'reading' : 'unknown');
    const approval = stepOf(p, 'approval');
    assert.equal(approval.word, name === 'reading' ? 'not read' : 'unknown');
    assert.match(approval.next!, /Refresh/);
  }
});

test('#2514: elapsed empty read neither invites an idea nor claims no approval waits', () => {
  for (const fleet of [null, FLEET]) {
    const p = { ...base(), fleet: { state: 'read' as const, value: fleet } };
    const received = { mono: 500, wall: NOW };
    const fresh = { received, now: { mono: 68_500, wall: NOW + 68_000 } };
    assert.equal(stepOf(p, 'idea', fresh).word, fleet ? 'done' : 'your turn');
    assert.equal(stepOf(p, 'approval', fresh).word, fleet ? 'none waiting' : 'waiting');
    const aged = { received, now: { mono: 69_500, wall: NOW + 69_000 } };
    assert.equal(stepOf(p, 'idea', aged).word, fleet ? 'done' : 'unknown');
    const approval = stepOf(p, 'approval', aged);
    assert.equal(approval.word, 'unknown');
    assert.match(approval.next!, /Refresh/);
  }
});

for (const phase of ['pending', 'sent', 'queued'] as const) test(`#2514: ${phase} receipt remains distinct from saved approval when the read is stale`, () => {
  const key = JSON.stringify(['synthetic-owner/first-idea', 'issue', 2900, 9200003, 'dr_plan_2900']);
  const receipts = new Map([[key, { binding: 'synthetic-binding', target: 'thr_syn_orch01', text: 'approve #2900', at: NOW - 10_000, phase }]]);
  const s = stepOf({ ...base(), receipts, decisions: { state: 'read', value: { ...PLAN, freshness: stale } } }, 'approval');
  assert.equal(s.word, phase === 'pending' ? 'check first' : 'sent, not saved');
});

// #2847: Decisions' AnswerSlot refuses an answer while this tab's storage is
// unreadable or an earlier unqualified answer record exists for the slot; the
// guide must not invite that answer. Plausible bug: gating on actionable()
// alone. Before #2847 every case here read storage as empty or ignored it.
const PLAN_KEY = slotsOf(PLAN)[0]!.key;
const GRILL_KEY = slotsOf(GRILL)[0]!.key;
const LEGACY = (key: string) => `openwiz.decisions.${encodeURIComponent(JSON.stringify(JSON.parse(key).slice(1)))}.`;
const UNREAD = 'answer unavailable: earlier answer storage could not be checked';
const UNRESOLVED = 'answer unavailable: an earlier unqualified answer record must be resolved before answering this repository';
const refusals: [string, () => void, string][] = [
  ['no tab storage', () => { delete tab.sessionStorage; }, UNREAD],
  ['tab storage that refuses reads', () => { tab.sessionStorage = { ...tabStorage, length: 0, getItem: () => { throw new Error('Synthetic: storage refused.'); } }; }, UNREAD],
  ['an earlier unqualified receipt', () => { values.set(LEGACY(PLAN_KEY) + 'receipt', JSON.stringify({ binding: 'synthetic-unqualified-binding', target: 'thr_syn_legacy', text: 'Synthetic answer', at: NOW - 5_000, phase: 'sent' })); }, UNRESOLVED],
  ['an earlier unqualified composer record', () => { values.set(LEGACY(PLAN_KEY) + 'openwiz.composer.thr_syn_legacy', '{}'); }, UNRESOLVED],
];
for (const [name, plant, why] of refusals) test(`#2847: ${name} cannot invite an answer`, () => {
  plant();
  try {
    unavailable(PLAN, why);
  } finally {
    values.clear();
    tab.sessionStorage = tabStorage;
  }
  assert.equal(stepOf({ ...base(), decisions: { state: 'read', value: PLAN } }, 'approval').word, 'your turn', 'readable empty storage invites it again');
});

test('#2847: an earlier record refuses only its own slot', () => {
  values.set(LEGACY(GRILL_KEY) + 'receipt', JSON.stringify({ binding: 'synthetic-unqualified-binding', target: 'thr_syn_legacy', text: 'Synthetic answer', at: NOW - 5_000, phase: 'sent' }));
  try {
    assert.equal(stepOf({ ...base(), decisions: { state: 'read', value: PLAN } }, 'approval').word, 'your turn');
    assert.equal(stepOf({ ...base(), decisions: { state: 'read', value: GRILL } }, 'approval').word, 'unavailable');
  } finally {
    values.clear();
  }
});

test('#2847: this tab\'s own receipt still shows as sent, never saved, beside an earlier record', () => {
  values.set(LEGACY(PLAN_KEY) + 'receipt', '{}');
  try {
    const receipts = new Map([[PLAN_KEY, { binding: 'synthetic-binding', target: 'thr_syn_orch01', text: 'approve #2900', at: NOW - 10_000, phase: 'sent' as const }]]);
    assert.equal(stepOf({ ...base(), receipts, decisions: { state: 'read', value: PLAN } }, 'approval').word, 'sent, not saved');
  } finally {
    values.clear();
  }
});
