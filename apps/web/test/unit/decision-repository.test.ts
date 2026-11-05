import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
import { readDecisions, slotsOf } from '../../src/decisions.ts';

// Render the actual card tree without a browser. The loader exposes the
// existing pure Cards component only to this test; its body is unchanged.
registerHooks({ load(url, context, nextLoad) {
  if (!url.startsWith('file:') || !url.endsWith('.tsx')) return nextLoad(url, context);
  const file = fileURLToPath(url);
  let source = readFileSync(file, 'utf8');
  if (file.endsWith('/components/Decisions.tsx')) source += '\nexport { Cards };\n';
  return { format: 'module', source: ts.transpileModule(source, { fileName: file, compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, verbatimModuleSyntax: true } }).outputText, shortCircuit: true };
} });
// The extra export exists in this loader only, not the production module.
const { Cards } = await import('../../src/components/Decisions.tsx') as unknown as { Cards: (props: Record<string, unknown>) => ReturnType<typeof createElement> };

function pair() {
  const doc = JSON.parse(readFileSync(new URL('../fixtures/decisions/target.json', import.meta.url), 'utf8'));
  const first = structuredClone(doc.items[0]);
  first.subject.repository = 'synthetic-public/work';
  first.current = { known: true };
  const second = structuredClone(first);
  second.subject.repository = 'synthetic-records/archive';
  doc.items = [first, second];
  const read = readDecisions(doc);
  assert.ok(read.ok);
  return read.decisions;
}

test('rendered decision cards retain distinct React identities for equal local IDs', () => {
  const d = pair();
  const now = { wall: d.snapshot_at, mono: 0 };
  const tree = Cards({ d, received: now, now });
  const children = (tree.props as { children: { key: string }[] }).children;
  assert.equal(children.length, 2);
  assert.equal(new Set(children.map(x => x.key)).size, 2);
});

test('legacy unqualified receipts and composer operations block both repositories without rebinding', () => {
  const values = new Map<string, string>();
  const storage = { get length() { return values.size; }, key: (i: number) => [...values.keys()][i] ?? null, getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => { values.set(k, v); }, removeItem: (k: string) => { values.delete(k); } };
  Object.assign(globalThis, { window: { sessionStorage: storage } });
  const d = pair();
  const slot = slotsOf(d)[0];
  assert.ok(slot);
  const legacyKey = JSON.stringify(JSON.parse(slot.key).slice(1));
  const prefix = `openwiz.decisions.${encodeURIComponent(legacyKey)}.`;
  const now = { wall: d.snapshot_at, mono: 0 };
  for (const phase of ['pending', 'queued', 'sent', 'composer', 'unread']) {
    values.clear();
    if (phase === 'composer') values.set(prefix + 'openwiz.composer.thr_syn_legacy', JSON.stringify({ root: 'web-' + 'b'.repeat(32), draft: 'Synthetic exact answer', next: { queue: 2, steer: 1 }, attempts: [] }));
    else if (phase !== 'unread') values.set(prefix + 'receipt', JSON.stringify({ binding: 'synthetic-unqualified-binding', target: 'thr_syn_legacy', text: 'Synthetic exact answer', at: 1000, phase }));
    const before = [...values];
    const getItem = storage.getItem;
    if (phase === 'unread') storage.getItem = () => { throw new Error('synthetic storage refusal'); };
    const html = renderToStaticMarkup(createElement(Cards, { d, received: now, now }));
    storage.getItem = getItem;
    assert.equal((html.match(/data-part="choices"/g) ?? []).length, phase === 'unread' ? 0 : 2, 'only positively unaffected questions remain answerable');
    assert.equal((html.match(/answer unavailable:.*?earlier/gi) ?? []).length, phase === 'unread' ? 4 : 2, phase);
    assert.deepEqual([...values], before, 'legacy operation and receipt bytes are immutable');
  }
  values.clear();
  const html = renderToStaticMarkup(createElement(Cards, { d, received: now, now }));
  assert.equal((html.match(/data-part="choices"/g) ?? []).length, 4, 'an empty readable legacy namespace permits new answers');
});

test('decision slots distinguish equal local identities from different repositories', () => {
  const doc = JSON.parse(readFileSync(new URL('../fixtures/decisions/target.json', import.meta.url), 'utf8'));
  const first = structuredClone(doc.items[0]);
  first.subject.repository = 'synthetic-public/work';
  const second = structuredClone(first);
  second.subject.repository = 'synthetic-records/archive';
  doc.items = [first, second];
  const read = readDecisions(doc);
  assert.equal(read.ok, true, JSON.stringify(read));
  if (!read.ok) return;
  const slots = slotsOf(read.decisions);
  assert.equal(slots.length, 4); // two unanswered questions in each independent request
  assert.equal(new Set(slots.map(s => s.key)).size, 4);
  for (const bad of ['', 'bad/repo/extra', 'space name/repo']) {
    const invalid = structuredClone(doc);
    invalid.items[0].subject.repository = bad;
    assert.equal(readDecisions(invalid).ok, false);
  }
});
