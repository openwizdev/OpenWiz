// #126 (spec 3's C2): one fleet's drawn graph and its tickets, on fixtures:
// S3-3 (states read without colour) and S3-4 (a graph too wide for a phone
// is listed by state), in Chromium, with the page's own stylesheet; and the
// model, on the contract's own examples.
//
// The layout: boxes in columns by step, one box per issue, arrows from each
// blocker to what it blocks (across versions too, never behind a box), loops
// refused, and the graph drawn only where it fits. Every expected position is worked out by
// hand from the pill size (160 × 64) and the gaps (24 across, 16 down): a
// column is 184 px from the next, a row 80 px.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { after, before, test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright-core';
import type { Browser, Page } from 'playwright-core';
import { createElement, isValidElement } from 'react';
import type { ReactNode } from 'react';
import ts from 'typescript';

import { blockerMarker, fleetModel, layoutGraph, ticketMarker } from '../../src/fleetGraph.ts';
import type { Box, FleetEnvelope, FleetTicket, GraphInput, MarkerKind, Read, TicketRow } from '../../src/fleetGraph.ts';
import { readFleet } from '../../src/fleets.ts';
import { contractExample, everyStateFleet, SNAPSHOT_AT, specThreeFleet, syntheticFleet } from '../support/fleet-graph-fixtures.ts';
import { HOSTILE } from '../support/synthetic.ts';
import { token } from '../support/style-tokens.ts';

// FleetDetail.tsx is JSX, which Node's type stripping can't read: the
// TypeScript compiler turns it into JavaScript as it loads (test only).
// Every await of this file comes before its first test: a test registered
// before an await starts early, and a run of only those never ends.
registerHooks({
  load(url, context, nextLoad) {
    if (!url.startsWith('file:') || !url.endsWith('.tsx')) return nextLoad(url, context);
    const file = fileURLToPath(url);
    const compilerOptions = { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, verbatimModuleSyntax: true };
    return { format: 'module', source: ts.transpileModule(readFileSync(file, 'utf8'), { fileName: file, compilerOptions }).outputText, shortCircuit: true };
  },
});
const { FleetDetail } = await import('../../src/components/FleetDetail.tsx');
const { renderToStaticMarkup } = await import('react-dom/server');

type Png = { width: number; height: number; data: Uint8Array };
type Mask = { width: number; height: number; mask: Uint8Array };
const png: { decodePng(b: Buffer): Png; inkMask(p: Png): Mask; maskDifference(a: Mask, b: Mask): number } = await import(String(new URL('../support/png.mjs', import.meta.url)));
const { PAGE_CSP }: { PAGE_CSP: string } = await import(String(new URL('../support/serve.mjs', import.meta.url)));

/** V2's threshold: two shapes are told apart when their colourless masks differ in at least this many pixels. */
const DISTINCT_PIXELS = 20;
const PHONE = { width: 390, height: 844 };
const DESKTOP = { width: 1440, height: 900 };
const NOW = new Date(SNAPSHOT_AT + 60_000);
const WEB = new URL('../../', import.meta.url);
const html = (body: string) =>
  `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>DEMO</title><link rel="stylesheet" href="/globals.css"></head><body><main>${body}</main></body></html>`;

let browser: Browser | null = null;
before(async () => {
  browser = await chromium.launch({ executablePath: process.env['OPENWIZ_CHROMIUM'] ?? '/usr/bin/chromium' });
});
after(async () => {
  await browser?.close();
});

const tickets = (...numbers: number[]) => numbers.map((number) => ({ number, outside: false }));
const outside = (...numbers: number[]) => numbers.map((number) => ({ number, outside: true }));
const edges = (...pairs: [number, number][]) => pairs.map(([from, to]) => ({ from, to }));

test("Graph layout contracts: columns, arrows, loops and width boundaries", async (t) => {
  for (const [name, proof] of [
    ['layout: a box\'s column is one past its deepest blocker\'s; a ticket with no blockers is in the first', () => {
      // 1 blocks 2, 3 and 4; 2 and 3 block 4; 5 waits on nothing.
      const input: GraphInput = { nodes: tickets(1, 2, 3, 4, 5), edges: edges([1, 2], [1, 3], [2, 4], [3, 4], [1, 4]) };
      assert.deepEqual(layoutGraph(input, 1000), {
        kind: 'drawn',
        boxes: [
          { number: 1, outside: false, column: 0, row: 0, x: 0, y: 0 },
          { number: 2, outside: false, column: 1, row: 0, x: 184, y: 0 },
          { number: 3, outside: false, column: 1, row: 1, x: 184, y: 80 },
          { number: 4, outside: false, column: 2, row: 0, x: 368, y: 0 },
          { number: 5, outside: false, column: 0, row: 1, x: 0, y: 80 },
        ],
        arrows: [
          { from: 1, to: 2, x1: 160, y1: 32, via: [], x2: 184, y2: 32 },
          { from: 1, to: 3, x1: 160, y1: 32, via: [], x2: 184, y2: 112 },
          { from: 2, to: 4, x1: 344, y1: 32, via: [], x2: 368, y2: 32 },
          { from: 3, to: 4, x1: 344, y1: 112, via: [], x2: 368, y2: 32 },
          // It skips column 1: it passes through that column's next empty slot (row 2).
          { from: 1, to: 4, x1: 160, y1: 32, via: [{ x: 184, y: 192 }], x2: 368, y2: 32 },
        ],
        width: 528,
        height: 224,
      });
    }],
    ['layout: cross-version arrows: each outside blocker is one box in the first column, above the tickets, with an arrow to each ticket it blocks', () => {
      // #961 and #962 wait on #610 (another fleet); #963 on #516 (another
      // version), #612 and #613; #964 on #961, #962, #963 and #516 again.
      const input: GraphInput = {
        nodes: [...tickets(961, 962, 963, 964), ...outside(516, 610, 612, 613)],
        edges: edges([610, 961], [610, 962], [516, 963], [612, 963], [613, 963], [961, 964], [962, 964], [963, 964], [516, 964]),
      };
      assert.deepEqual(layoutGraph(input, 1000), {
        kind: 'drawn',
        boxes: [
          { number: 961, outside: false, column: 1, row: 0, x: 184, y: 0 },
          { number: 962, outside: false, column: 1, row: 1, x: 184, y: 80 },
          { number: 963, outside: false, column: 1, row: 2, x: 184, y: 160 },
          { number: 964, outside: false, column: 2, row: 0, x: 368, y: 0 },
          { number: 516, outside: true, column: 0, row: 0, x: 0, y: 0 },
          { number: 610, outside: true, column: 0, row: 1, x: 0, y: 80 },
          { number: 612, outside: true, column: 0, row: 2, x: 0, y: 160 },
          { number: 613, outside: true, column: 0, row: 3, x: 0, y: 240 },
        ],
        arrows: [
          { from: 610, to: 961, x1: 160, y1: 112, via: [], x2: 184, y2: 32 },
          { from: 610, to: 962, x1: 160, y1: 112, via: [], x2: 184, y2: 112 },
          { from: 516, to: 963, x1: 160, y1: 32, via: [], x2: 184, y2: 192 },
          { from: 612, to: 963, x1: 160, y1: 192, via: [], x2: 184, y2: 192 },
          { from: 613, to: 963, x1: 160, y1: 272, via: [], x2: 184, y2: 192 },
          { from: 961, to: 964, x1: 344, y1: 32, via: [], x2: 368, y2: 32 },
          { from: 962, to: 964, x1: 344, y1: 112, via: [], x2: 368, y2: 32 },
          { from: 963, to: 964, x1: 344, y1: 192, via: [], x2: 368, y2: 32 },
          { from: 516, to: 964, x1: 160, y1: 32, via: [{ x: 184, y: 272 }], x2: 368, y2: 32 },
        ],
        width: 528,
        height: 304,
      });
    }],
    ['layout: an outside blocker and an unblocked ticket share the first column, outside first', () => {
      const input: GraphInput = { nodes: [...tickets(31, 32), ...outside(9)], edges: edges([9, 32]) };
      assert.deepEqual(layoutGraph(input, 1000), {
        kind: 'drawn',
        boxes: [
          { number: 31, outside: false, column: 0, row: 1, x: 0, y: 80 },
          { number: 32, outside: false, column: 1, row: 0, x: 184, y: 0 },
          { number: 9, outside: true, column: 0, row: 0, x: 0, y: 0 },
        ],
        arrows: [{ from: 9, to: 32, x1: 160, y1: 32, via: [], x2: 184, y2: 32 }],
        width: 344,
        height: 144,
      });
    }],
    ['layout: an arrow that skips columns passes through an empty slot in each column between, never behind a box', () => {
      const g = fleetModel(specThreeFleet()).graph;
      assert.ok(g.kind === 'input');
      const layout = layoutGraph(g.input, 896);
      assert.ok(layout.kind === 'drawn');
      // #615 (another version) blocks #966, four columns on: rows 5, 2 and 1 are the first free ones in columns 1, 2 and 3.
      assert.deepEqual(
        layout.arrows.find((a) => a.from === 615)?.via,
        [
          { x: 184, y: 432 },
          { x: 368, y: 192 },
          { x: 552, y: 112 },
        ],
      );
      assert.equal(layout.height, 544);
      for (const a of layout.arrows) {
        // Every hop between points crosses exactly one gap between columns, never a column...
        const xs = [a.x1, ...a.via.flatMap((v) => [v.x, v.x + 160]), a.x2];
        for (let i = 0; i + 1 < xs.length; i += 2) assert.equal((xs[i + 1] ?? 0) - (xs[i] ?? 0), 24, `${a.from}→${a.to} crosses a column`);
        // ...and each slot it passes through holds no box.
        for (const v of a.via) {
          const hit: Box[] = layout.boxes.filter((b) => b.x === v.x && b.y === v.y - 32);
          assert.deepEqual(hit, [], `${a.from}→${a.to} passes behind a box`);
        }
      }
    }],
    ['layout: a loop is refused, naming exactly the tickets on it, whatever the width', () => {
      // 1 → 2 → 3 → 1, with 4 waiting on the loop and 5 apart from it.
      const loop: GraphInput = { nodes: tickets(1, 2, 3, 4, 5), edges: edges([1, 2], [2, 3], [3, 1], [3, 4]) };
      assert.deepEqual(layoutGraph(loop, 1000), { kind: 'loop', numbers: [1, 2, 3] });
      assert.deepEqual(layoutGraph(loop, 100), { kind: 'loop', numbers: [1, 2, 3] });
      // A ticket that blocks itself.
      assert.deepEqual(layoutGraph({ nodes: tickets(6, 7), edges: edges([6, 7], [7, 7]) }, 1000), { kind: 'loop', numbers: [7] });
      // A loop fed by a blocker from another version.
      const fed: GraphInput = { nodes: [...tickets(1, 2, 3), ...outside(90)], edges: edges([90, 1], [1, 2], [2, 1], [2, 3]) };
      assert.deepEqual(layoutGraph(fed, 1000), { kind: 'loop', numbers: [1, 2] });
      // Two loops, both named.
      const two: GraphInput = { nodes: tickets(1, 2, 3, 4, 5), edges: edges([1, 2], [2, 1], [3, 4], [4, 3], [2, 5]) };
      assert.deepEqual(layoutGraph(two, 1000), { kind: 'loop', numbers: [1, 2, 3, 4] });
      // Two loops and a bridge (Sol's R1 on #186): 3 waits on the first loop and blocks the second, but is on neither.
      const bridged: GraphInput = { nodes: tickets(1, 2, 3, 4, 5), edges: edges([1, 2], [2, 1], [2, 3], [3, 4], [4, 5], [5, 4]) };
      assert.deepEqual(layoutGraph(bridged, 1000), { kind: 'loop', numbers: [1, 2, 4, 5] });
      // The same, the other way round: 3 blocks the first loop and waits on the second.
      const back: GraphInput = { nodes: tickets(1, 2, 3, 4, 5), edges: edges([1, 2], [2, 1], [3, 1], [4, 3], [4, 5], [5, 4]) };
      assert.deepEqual(layoutGraph(back, 1000), { kind: 'loop', numbers: [1, 2, 4, 5] });
      // A ticket on a loop that also blocks itself, and one that only blocks itself: each named once.
      assert.deepEqual(layoutGraph({ nodes: tickets(1, 2, 3), edges: edges([1, 2], [2, 1], [2, 2], [2, 3], [3, 3]) }, 1000), { kind: 'loop', numbers: [1, 2, 3] });
    }],
    ['layout: drawn only where it fits; otherwise too wide, with what it needs', () => {
      const chain = (n: number): GraphInput => ({
        nodes: tickets(...Array.from({ length: n }, (_, i) => i + 1)),
        edges: Array.from({ length: n - 1 }, (_, i) => ({ from: i + 1, to: i + 2 })),
      });
      // Three columns need 3 × 160 + 2 × 24 = 528 px.
      assert.deepEqual(layoutGraph(chain(3), 527), { kind: 'too_wide', columns: 3, needed: 528, width: 527 });
      assert.equal(layoutGraph(chain(3), 528).kind, 'drawn');
      // A 390 px phone, inside the page's 16 px margins (358 px): two columns (344 px) fit, three don't.
      assert.equal(layoutGraph(chain(2), 358).kind, 'drawn');
      assert.deepEqual(layoutGraph(chain(3), 358), { kind: 'too_wide', columns: 3, needed: 528, width: 358 });
      // A 1440 px desktop, in the page's 960 px column with its 32 px margins (896 px): five columns (896 px) fit, six (1080 px) don't.
      assert.equal(layoutGraph(chain(5), 896).kind, 'drawn');
      assert.deepEqual(layoutGraph(chain(6), 896), { kind: 'too_wide', columns: 6, needed: 1080, width: 896 });
      // One box needs its own width; no boxes, nothing.
      assert.deepEqual(layoutGraph(chain(1), 160), {
        kind: 'drawn',
        boxes: [{ number: 1, outside: false, column: 0, row: 0, x: 0, y: 0 }],
        arrows: [],
        width: 160,
        height: 64,
      });
      assert.deepEqual(layoutGraph({ nodes: [], edges: [] }, 358), { kind: 'drawn', boxes: [], arrows: [], width: 0, height: 0 });
    }],
  ] as const) {
    t.diagnostic(name);
    await proof();
  }
});

// ── what the view shows, from the contract's own examples ──

const REVIEWER = 'reviewer undefined (no verified chain places a reviewer in version 1)';
const NONE = { text: 'no builder placed' };
const row = (number: number, title: string, marker: [string, string, string, string], pr: string, rest: Partial<TicketRow> = {}): TicketRow => ({
  number,
  title: { text: title, unknown: false },
  marker: { kind: marker[0] as MarkerKind, tier: marker[1] as TicketRow['marker']['tier'], glyph: marker[2], word: marker[3] },
  pr,
  ci: null,
  review: null,
  waits: null,
  builder: NONE,
  reviewer: REVIEWER,
  ...rest,
});

const EXAMPLE_2_TICKETS: TicketRow[] = [
  row(902, 'Synthetic ticket A1', ['merged', 't2', '[✓]', 'merged'], 'PR #951 merged · on its base', { builder: { thread: 'thr_syn_0002' } }),
  row(903, 'Synthetic ticket A2', ['in_review', 't3', '[>]', 'in_review'], 'PR #952 open', {
    ci: 'CI passed',
    review: 'verdict approve at 3333333 · on its head',
    waits: 'waits on #902 merged',
    builder: { thread: 'thr_syn_0003' },
  }),
  row(904, 'Synthetic ticket A3', ['changes_requested', 't3', '[<]', 'changes_requested'], 'PR #953 open', {
    ci: 'CI passed',
    review: 'verdict changes at 4444444 · on its head',
    builder: { thread: 'thr_syn_0004' },
  }),
  row(905, 'Synthetic ticket A4', ['building', 't3', '[~]', 'building'], 'PR #954 open · draft', { ci: 'CI none', review: 'no verdict', builder: { thread: 'thr_syn_0005' } }),
  row(906, 'Synthetic ticket A5', ['ready', 't4', '[ ]', 'ready'], 'no PR', { waits: 'waits on #902 merged' }),
  row(907, 'Synthetic ticket A6', ['held', 't1', '[!]', 'held'], 'no PR'),
  row(908, 'Synthetic ticket A7', ['blocked', 't4', '[‖]', 'blocked'], 'no PR', { waits: 'waits on #811 (version 0.9.0) merged, #812 (no version) merged, #903 not merged' }),
  row(909, 'Synthetic ticket A8', ['unknown', 't5', '[?]', 'unknown (closed on GitHub, and no merge was read back)'], 'no PR'),
  row(910, 'Synthetic ticket A9', ['building', 't3', '[~]', 'building'], 'PR #955 open', {
    ci: 'CI failed',
    review: 'verdict changes at 7777777 · not on its head',
    builder: { thread: 'thr_syn_0006' },
  }),
];
const ticket = (n: number): TicketRow => EXAMPLE_2_TICKETS.find((t) => t.number === n) ?? assert.fail(`#${n}`);
const heading = (kind: string, tier: string, glyph: string) => ({ kind, tier, glyph, word: kind });

test('model: the contract\'s example 2 (fleet 901): every ticket as reported, in the view\'s order', () => {
  const m = fleetModel(contractExample(2));
  assert.deepEqual(
    { spec: m.spec, title: m.title, progress: m.progress, snapshotAt: m.snapshotAt, partial: m.partial },
    { spec: 901, title: { text: 'Synthetic spec one', unknown: false }, progress: '1 of 9 merged', snapshotAt: 1793437200000, partial: false },
  );
  assert.deepEqual(m.tickets, EXAMPLE_2_TICKETS);
});

for (const [subject, number, title] of [
  ['ticket', 902, 'Synthetic ticket A1'],
  ['fleet', 901, 'Synthetic spec one'],
] as const) {
  test(`model: title provenance for ${subject} #${number} after readFleet accepts a wrong-subject issue pointer`, () => {
    const e = contractExample(2);
    const titleFrom = (model: ReturnType<typeof fleetModel>) => subject === 'ticket' ? model.tickets[0]?.title : model.title;
    const normal = readFleet(JSON.stringify(e), 901);
    assert.ok(normal.ok);
    assert.deepEqual(titleFrom(fleetModel(normal.envelope)), { text: title, unknown: false });

    const target = subject === 'ticket' ? e.data.tickets[0] : e.data.fleet;
    const other = e.data.tickets[1];
    assert.ok(target && other);
    assert.equal(other.number, 903);
    target.issue = other.issue;
    const parsed = readFleet(JSON.stringify(e), 901);
    assert.ok(parsed.ok, 'the strict reader accepts this schema-valid inconsistent fixture');
    const model = fleetModel(parsed.envelope);
    const actual = titleFrom(model);
    assert.equal(actual?.unknown, true, 'a wrong-subject title must stay unknown');
    assert.deepEqual(actual, { text: `unknown (unread: read r10 isn't #${number}'s issue read)`, unknown: true });
    assert.deepEqual(model.tickets[1]?.title, { text: 'Synthetic ticket A2', unknown: false });
  });
}

for (const outcome of [
  { state: 'complete', value: [] },
  { state: 'complete', value: [902] },
  { state: 'partial', gap: 'truncated', reason: 'only one foreign blocker read', value: [902] },
  { state: 'failed', gap: 'timed_out', reason: 'foreign blockers timed out' },
] satisfies Extract<Read, { kind: 'blocked_by' }>['outcome'][]) {
  test(`model: blocker provenance rejects another ticket's ${outcome.state} read with ${outcome.state === 'failed' ? 'no' : outcome.value.length} blockers`, () => {
    const e = syntheticFleet(901, [{ number: 902, state: 'blocked', blockedBy: [904] }, { number: 903, state: 'ready' }], [{ number: 904, version: '0.9.0', merged: false }]);
    const model = () => {
      const parsed = readFleet(JSON.stringify(e), 901);
      assert.ok(parsed.ok, 'the public reader accepts this schema-valid fixture');
      return fleetModel(parsed.envelope);
    };
    const control = model();
    assert.ok(control.graph.kind === 'input');
    assert.deepEqual(control.graph.input.edges, [{ from: 904, to: 902 }]);
    assert.equal(control.tickets[0]?.waits, 'waits on #904 (version 0.9.0) not merged');
    assert.equal(control.tickets[1]?.waits, null);
    const target = e.data.tickets[0];
    const other = e.data.tickets[1];
    assert.ok(target && other);
    const read = e.reads.find((r) => r.id === other.blocked_by);
    assert.ok(read?.kind === 'blocked_by');
    read.outcome = outcome;
    target.blocked_by = other.blocked_by;
    const actual = model();
    assert.equal(actual.graph.kind, 'unread', 'a wrong-ticket blocker read cannot prove a complete graph');
    assert.equal(actual.tickets[0]?.waits, `waits on unknown (unread: read ${other.blocked_by} isn't #902's blocked_by read)`);
  });
}

for (const [outcome, waits] of [
  [{ state: 'complete', value: [] }, null],
  [{ state: 'complete', value: [904] }, 'waits on #904 (version 0.9.0) not merged'],
  [{ state: 'partial', gap: 'truncated', reason: 'only one blocker read', value: [904] }, 'waits on #904 (version 0.9.0) not merged, and more (partly read: only one blocker read)'],
  [{ state: 'failed', gap: 'timed_out', reason: 'blockers timed out' }, 'waits on unknown (unread: blockers timed out)'],
] satisfies [Extract<Read, { kind: 'blocked_by' }>['outcome'], string | null][]) {
  test(`model: blocker provenance preserves the same ticket's ${outcome.state} read with ${outcome.state === 'failed' ? 'no' : outcome.value.length} blockers`, () => {
    const e = syntheticFleet(901, [{ number: 902, state: 'blocked', blockedBy: [904] }], [{ number: 904, version: '0.9.0', merged: false }]);
    const read = e.reads.find((r) => r.kind === 'blocked_by' && r.ticket === 902);
    assert.ok(read?.kind === 'blocked_by');
    read.outcome = outcome;
    const parsed = readFleet(JSON.stringify(e), 901);
    assert.ok(parsed.ok);
    const actual = fleetModel(parsed.envelope);
    assert.equal(actual.tickets[0]?.waits, waits);
    if (outcome.state === 'complete') {
      assert.ok(actual.graph.kind === 'input');
      assert.deepEqual(actual.graph.input.edges, waits === null ? [] : [{ from: 904, to: 902 }]);
    } else {
      assert.deepEqual(actual.graph, { kind: 'unread', reason: `#902's blockers weren't all read (${outcome.reason})` });
    }
  });
}

test('model: listed by state, the contract\'s order of states, each ticket once, unknown last', () => {
  const m = fleetModel(contractExample(2));
  assert.deepEqual(m.groups, [
    { marker: heading('ready', 't4', '[ ]'), tickets: [ticket(906)] },
    { marker: heading('building', 't3', '[~]'), tickets: [ticket(905), ticket(910)] },
    { marker: heading('in_review', 't3', '[>]'), tickets: [ticket(903)] },
    { marker: heading('changes_requested', 't3', '[<]'), tickets: [ticket(904)] },
    { marker: heading('merged', 't2', '[✓]'), tickets: [ticket(902)] },
    { marker: heading('held', 't1', '[!]'), tickets: [ticket(907)] },
    { marker: heading('blocked', 't4', '[‖]'), tickets: [ticket(908)] },
    { marker: heading('unknown', 't5', '[?]'), tickets: [ticket(909)] },
  ]);
});

test('model: the graph of example 2: one box per ticket and per outside blocker, labelled with its version; an arrow per blocked-by link', () => {
  const g = fleetModel(contractExample(2)).graph;
  assert.equal(g.kind, 'input');
  if (g.kind !== 'input') return;
  assert.deepEqual(g.input, {
    nodes: [...tickets(902, 903, 904, 905, 906, 907, 908, 909, 910), ...outside(811, 812)],
    edges: edges([902, 903], [902, 906], [811, 908], [812, 908], [903, 908]),
  });
  assert.deepEqual(
    [...g.labels].map(([n, b]) => [n, b.label, b.marker.kind]),
    [
      [902, '#902', 'merged'],
      [903, '#903', 'in_review'],
      [904, '#904', 'changes_requested'],
      [905, '#905', 'building'],
      [906, '#906', 'ready'],
      [907, '#907', 'held'],
      [908, '#908', 'blocked'],
      [909, '#909', 'unknown'],
      [910, '#910', 'building'],
      [811, '#811 · 0.9.0', 'merged'],
      [812, '#812 · no version', 'merged'],
    ],
  );
});

test('model: the contract\'s example 3 (fleet 930, partial): unknowns stay unknown, each with its reads\' own reasons', () => {
  const m = fleetModel(contractExample(3));
  const checks = 'the checks of pull request 961 couldn\'t be read';
  const branch = 'builder unknown (unread: the branch of one project thread couldn\'t be read)';
  assert.deepEqual(
    { title: m.title, progress: m.progress, partial: m.partial, graph: m.graph },
    {
      title: { text: 'Synthetic spec two', unknown: false },
      progress: `progress unknown (unread: ${checks}; GitHub listed 2 of #932's 3 blockers; #840 couldn't be read)`,
      partial: true,
      graph: { kind: 'unread', reason: '#932\'s blockers weren\'t all read (GitHub listed 2 of #932\'s 3 blockers)' },
    },
  );
  const rows = [
    row(931, 'Synthetic ticket B1', ['unknown', 't5', '[?]', `unknown (unread: ${checks})`], 'PR #961 open', {
      ci: `CI unknown (unread: ${checks})`,
      review: 'no verdict',
      builder: { text: branch },
    }),
    row(932, 'Synthetic ticket B2', ['unknown', 't5', '[?]', 'unknown (unread: GitHub listed 2 of #932\'s 3 blockers; #840 couldn\'t be read)'], 'no PR', {
      waits: 'waits on #840 (version unknown (unread: #840 couldn\'t be read)) unknown (unread: #840 couldn\'t be read), #931 not merged, and more (partly read: GitHub listed 2 of #932\'s 3 blockers)',
      builder: { text: branch },
    }),
  ];
  assert.deepEqual(m.tickets, rows);
  assert.deepEqual(m.groups, [{ marker: heading('unknown', 't5', '[?]'), tickets: rows }]);
});

/** Contract example 2 with its GitHub version read failed (Sol's R3 on #186): a gap no ticket's row reaches. */
const VERSION_FAILED = 'synthetic GitHub version read failed';
function versionReadFailed(): FleetEnvelope {
  const e = contractExample(2);
  const r1 = e.reads.find((r) => r.id === 'r1');
  assert.ok(r1?.kind === 'version' && r1.source === 'github' && e.sources.github.version === 'r1');
  r1.outcome = { state: 'failed', gap: 'command_failed', reason: VERSION_FAILED };
  e.sources.github.version_tested = false;
  e.coverage.state = 'partial';
  return e;
}

test('gaps: every read that isn\'t complete, in the order of reads, with its subject, gap and own reason; none when every read is (R3)', () => {
  const failed = fleetModel(versionReadFailed());
  assert.equal(failed.partial, true);
  assert.deepEqual(failed.gaps, [{ read: 'r1', subject: 'version(github)', gap: 'command_failed', reason: VERSION_FAILED }]);
  // Nothing else carries it: without the gaps, the partial tag couldn't say why.
  assert.ok(!JSON.stringify({ ...failed, gaps: [] }).includes(VERSION_FAILED), 'only the gaps carry the version read\'s reason');
  assert.deepEqual(fleetModel(contractExample(3)).gaps, [
    { read: 'r2', subject: 'version(cloudroom)', gap: 'untested_version', reason: 'room-cli --version printed no version' },
    { read: 'r9', subject: 'checks(961)', gap: 'command_failed', reason: 'the checks of pull request 961 couldn\'t be read' },
    { read: 'r12', subject: 'blocked_by(932)', gap: 'truncated', reason: 'GitHub listed 2 of #932\'s 3 blockers' },
    { read: 'r14', subject: 'issue(840)', gap: 'not_found', reason: '#840 couldn\'t be read' },
    { read: 'r15', subject: 'pr_discovery(840)', gap: 'not_found', reason: '#840 couldn\'t be read' },
    { read: 'r19', subject: 'workspace(thr_syn_0012)', gap: 'command_failed', reason: 'the branch of one project thread couldn\'t be read' },
  ]);
  assert.deepEqual(fleetModel(contractExample(2)).gaps, []);
  // Each kind's subject, as the contract writes a read: kind(param), or kind() with none.
  const one = (read: Read) => fleetModel({ ...contractExample(2), reads: [read] }).gaps.map((g) => g.subject);
  const no = { state: 'failed', gap: 'timed_out', reason: 'synthetic' } as const;
  assert.deepEqual(
    [
      one({ id: 'r1', kind: 'repository', outcome: no }),
      one({ id: 'r1', kind: 'spec_list', outcome: no }),
      one({ id: 'r1', kind: 'sub_issues', spec: 9, outcome: no }),
      one({ id: 'r1', kind: 'comments', pr: 9, outcome: no }),
      one({ id: 'r1', kind: 'merge_readback', pr: 9, outcome: no }),
      one({ id: 'r1', kind: 'projects', outcome: no }),
      one({ id: 'r1', kind: 'threads', outcome: { state: 'partial', gap: 'truncated', reason: 'synthetic', value: [] } }),
    ],
    [['repository()'], ['spec_list()'], ['sub_issues(9)'], ['comments(9)'], ['merge_readback(9)'], ['projects()'], ['threads()']],
  );
});

test('markers: each state is its word, a glyph and a tier; every kind has its own glyph; unknowns keep their reasons', () => {
  const reads: Read[] = [{ id: 'r1', kind: 'checks', pr: 9, outcome: { state: 'failed', gap: 'timed_out', reason: 'the checks timed out' } }];
  const table = [
    ticketMarker({ known: 'held' }, reads),
    ticketMarker({ known: 'merged' }, reads),
    ticketMarker({ known: 'building' }, reads),
    ticketMarker({ known: 'in_review' }, reads),
    ticketMarker({ known: 'changes_requested' }, reads),
    ticketMarker({ known: 'ready' }, reads),
    ticketMarker({ known: 'blocked' }, reads),
    blockerMarker({ known: false }, reads),
    ticketMarker({ unknown: 'a reason' }, reads),
  ];
  assert.deepEqual(table, [
    { kind: 'held', tier: 't1', glyph: '[!]', word: 'held' },
    { kind: 'merged', tier: 't2', glyph: '[✓]', word: 'merged' },
    { kind: 'building', tier: 't3', glyph: '[~]', word: 'building' },
    { kind: 'in_review', tier: 't3', glyph: '[>]', word: 'in_review' },
    { kind: 'changes_requested', tier: 't3', glyph: '[<]', word: 'changes_requested' },
    { kind: 'ready', tier: 't4', glyph: '[ ]', word: 'ready' },
    { kind: 'blocked', tier: 't4', glyph: '[‖]', word: 'blocked' },
    { kind: 'not_merged', tier: 't4', glyph: '[-]', word: 'not merged' },
    { kind: 'unknown', tier: 't5', glyph: '[?]', word: 'unknown (a reason)' },
  ]);
  assert.equal(new Set(table.map((m) => m.glyph)).size, table.length);
  assert.deepEqual(blockerMarker({ known: true }, reads), { kind: 'merged', tier: 't2', glyph: '[✓]', word: 'merged' });
  assert.deepEqual(ticketMarker({ unread: ['r1'] }, reads), { kind: 'unknown', tier: 't5', glyph: '[?]', word: 'unknown (unread: the checks timed out)' });
  assert.deepEqual(blockerMarker({ unread: ['r1', 'r7'] }, reads), {
    kind: 'unknown',
    tier: 't5',
    glyph: '[?]',
    word: 'unknown (unread: the checks timed out; read r7 isn\'t on the record)',
  });
});

test('model: a pointer to no read, or to the wrong kind, and a blocker off the record, are unknown, never guessed', () => {
  const e = contractExample(2);
  const at = (n: number) => e.data.tickets.find((t) => t.number === n) ?? assert.fail(`#${n}`);
  at(905).pr = 'r999';
  at(903).ci = 'r6';
  const r32 = e.reads.find((r) => r.id === 'r32');
  assert.ok(r32?.kind === 'blocked_by' && r32.outcome.state === 'complete');
  r32.outcome.value = [77, 811, 812, 903];
  const m = fleetModel(e);
  const shown = (n: number) => m.tickets.find((t) => t.number === n) ?? assert.fail(`#${n}`);
  assert.equal(shown(905).pr, 'PR unknown (unread: the pr_discovery read r999 isn\'t on the record)');
  assert.equal(shown(905).review, 'no verdict');
  assert.equal(shown(903).ci, 'CI unknown (unread: the checks read r6 isn\'t on the record)');
  assert.equal(
    shown(908).waits,
    'waits on #77 (version unknown (not on the record as a blocker)) unknown (not on the record as a blocker), #811 (version 0.9.0) merged, #812 (no version) merged, #903 not merged',
  );
  assert.ok(m.graph.kind === 'input');
  assert.deepEqual(m.graph.labels.get(77), { label: '#77 · version unknown', marker: { kind: 'unknown', tier: 't5', glyph: '[?]', word: 'unknown (not on the record as a blocker)' } });
  // A fleet whose ticket list wasn't read in full has no graph.
  const f = contractExample(2);
  const r5 = f.reads.find((r) => r.id === 'r5');
  assert.ok(r5?.kind === 'sub_issues');
  r5.outcome = { state: 'failed', gap: 'timed_out', reason: 'the sub-issues of #901 timed out' };
  assert.deepEqual(fleetModel(f).graph, { kind: 'unread', reason: 'the fleet\'s tickets weren\'t all read (the sub-issues of #901 timed out)' });
});

test('model: blockers from other versions are labelled with their version, none, or unknown', () => {
  const g = fleetModel(everyStateFleet()).graph;
  assert.ok(g.kind === 'input');
  assert.deepEqual(
    [690, 691, 692].map((n) => [n, g.labels.get(n)?.label, g.labels.get(n)?.marker.word]),
    [
      [690, '#690 · 0.9.0', 'merged'],
      [691, '#691 · no version', 'not merged'],
      [692, '#692 · version unknown', 'unknown (unread: #692 couldn\'t be read)'],
    ],
  );
});

/** specThreeFleet's waits, from its fixture: its outside blockers' versions, as its boxes label them. */
const SPEC_THREE_WAITS: [number, string][] = [
  [961, 'waits on #610 (version 0.8.6) merged'],
  [962, 'waits on #610 (version 0.8.6) merged'],
  [963, 'waits on #516 (version 0.8.4) not merged, #612 (version 0.8.6) not merged, #613 (version 0.8.6) not merged'],
  [964, 'waits on #516 (version 0.8.4) not merged, #961 not merged, #962 not merged, #963 not merged'],
  [965, 'waits on #509 (version 0.8.3) merged, #964 not merged'],
  [966, 'waits on #615 (version 0.8.6) not merged, #622 (version 0.8.6) not merged, #965 not merged'],
];

test('waits: each outside blocker in a ticket\'s row names its version too, none, or unknown with why, as its box does (R2); the fleet\'s own tickets don\'t', () => {
  const waits = (e: FleetEnvelope) => fleetModel(e).tickets.flatMap((t) => (t.waits === null ? [] : [[t.number, t.waits]]));
  assert.deepEqual(waits(everyStateFleet()), [
    [707, 'waits on #690 (version 0.9.0) merged, #691 (no version) not merged'],
    [709, 'waits on #692 (version unknown (unread: #692 couldn\'t be read)) unknown (unread: #692 couldn\'t be read)'],
  ]);
  assert.deepEqual(waits(specThreeFleet()), SPEC_THREE_WAITS);
});

// ── the rendered view: the page's own stylesheet and fonts, under its CSP, in Chromium ──

/**
 * The view in a page like the app's: its stylesheet, fonts and CSP, inside
 * `<main>`, given the width `<main>` leaves at this viewport: 358 px at 390
 * (16 px margins), 896 px at 1440 (a 960 px column, 32 px margins).
 */
async function fleetPage(viewport: { width: number; height: number }, envelope: FleetEnvelope, gapsOpen = false): Promise<{ page: Page; width: number; markup: string; close: () => Promise<void> }> {
  assert.ok(browser, 'Chromium is running');
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1, reducedMotion: 'reduce' });
  const page = await context.newPage();
  let markup = '';
  await page.route('http://fleet.test/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/') return route.fulfill({ status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8', 'Content-Security-Policy': PAGE_CSP }, body: html(markup) });
    if (path === '/tokens.css') return route.fulfill({ status: 200, contentType: 'text/css', body: readFileSync(new URL('styles/tokens.css', WEB)) });
    if (path === '/globals.css') return route.fulfill({ status: 200, contentType: 'text/css', body: readFileSync(new URL('styles/globals.css', WEB)) });
    if (/^\/fonts\/[A-Za-z-]+\.woff2$/.test(path)) return route.fulfill({ status: 200, contentType: 'font/woff2', body: readFileSync(new URL(`public${path}`, WEB)) });
    return route.fulfill({ status: 404, body: '' });
  });
  await page.addInitScript({ content: "window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));" });
  await page.goto('http://fleet.test/');
  const width = await page.evaluate(() => {
    const main = document.querySelector('main');
    const s = main ? getComputedStyle(main) : null;
    return main && s ? main.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight) : 0;
  });
  markup = renderToStaticMarkup(createElement(FleetDetail, { envelope, width, now: NOW, onOpenThread: () => {}, gapsOpen, onToggleGaps: () => {} }));
  await page.goto('http://fleet.test/');
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  return { page, width, markup, close: () => context.close() };
}

const cspViolations = (page: Page): Promise<unknown> => page.evaluate('window.__csp');
const noSidewaysScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
const fallback = (page: Page) => page.$$eval('[data-fallback]', (els) => els.map((e) => [e.getAttribute('data-fallback'), e.textContent]));
const groupsShown = (page: Page) =>
  page.$$eval('[data-state-group]', (els) => els.map((g) => [g.getAttribute('data-state-group'), [...g.querySelectorAll('[data-ticket]')].map((t) => Number(t.getAttribute('data-ticket')))]));

test('blocker provenance: a wrong-ticket read shows unread waits and the list fallback at phone and desktop widths', async () => {
  const e = syntheticFleet(901, [{ number: 902, state: 'blocked', blockedBy: [904] }, { number: 903, state: 'ready' }], [{ number: 904, version: '0.9.0', merged: false }]);
  const target = e.data.tickets[0];
  const other = e.data.tickets[1];
  assert.ok(target && other);
  target.blocked_by = other.blocked_by;
  const parsed = readFleet(JSON.stringify(e), 901);
  assert.ok(parsed.ok);
  for (const viewport of [PHONE, DESKTOP]) {
    const p = await fleetPage(viewport, parsed.envelope);
    try {
      assert.deepEqual(await fallback(p.page), [['unread', `the graph isn't drawn: #902's blockers weren't all read (read ${other.blocked_by} isn't #902's blocked_by read); its tickets are listed by state below`]]);
      assert.equal(await p.page.locator('svg[data-graph]').count(), 0);
      assert.equal(await p.page.locator('[data-ticket="902"] [data-fact="waits"]').textContent(), `waits on unknown (unread: read ${other.blocked_by} isn't #902's blocked_by read)`);
      assert.equal(await p.page.locator('[data-ticket="903"] [data-fact="waits"]').count(), 0);
      assert.deepEqual(await groupsShown(p.page), [['ready', [903]], ['blocked', [902]]]);
      assert.ok(await noSidewaysScroll(p.page));
      assert.deepEqual(await cspViolations(p.page), []);
    } finally {
      await p.close();
    }
  }
});

test('S3-4: at 390 px a graph too wide for the screen is listed by state, saying why; at 1440 px it is drawn, and fits', async () => {
  const phone = await fleetPage(PHONE, specThreeFleet());
  try {
    assert.equal(phone.width, 358);
    assert.equal(await phone.page.locator('svg[data-graph]').count(), 0);
    assert.deepEqual(await fallback(phone.page), [['too_wide', 'the graph needs 896 px and this screen has 358 px: its tickets are listed by state below']]);
    assert.deepEqual(await groupsShown(phone.page), [
      ['building', [962]],
      ['in_review', [961]],
      ['held', [966]],
      ['blocked', [963, 964, 965]],
    ]);
    // The graph is hidden, so each row says which version holds it up (R2), in the list's order.
    const shownWaits = await phone.page.$$eval('.fleet-tickets [data-ticket]', (els) => els.map((t) => [Number(t.getAttribute('data-ticket')), t.querySelector('[data-fact=waits]')?.textContent ?? null]));
    assert.deepEqual(shownWaits, [962, 961, 966, 963, 964, 965].map((n) => SPEC_THREE_WAITS.find(([m]) => m === n) ?? assert.fail(`#${n}`)));
    assert.equal(await noSidewaysScroll(phone.page), true);
    const targets = await phone.page.$$eval('[data-thread]', (els) => els.map((e) => [e.getAttribute('data-thread'), e.getBoundingClientRect().height]));
    assert.deepEqual(targets, [
      ['thr_syn_0962', 44],
      ['thr_syn_0961', 44],
    ]);
    assert.deepEqual(await cspViolations(phone.page), []);
  } finally {
    await phone.close();
  }

  const desktop = await fleetPage(DESKTOP, specThreeFleet());
  try {
    assert.equal(desktop.width, 896);
    assert.deepEqual(await desktop.page.$$eval('svg[data-graph]', (els) => els.map((g) => [g.getAttribute('width'), g.getAttribute('height')])), [['896', '544']]);
    assert.equal(await desktop.page.locator('[data-box]').count(), 13);
    assert.equal(await desktop.page.locator('[data-arrow]').count(), 14);
    assert.deepEqual(await fallback(desktop.page), []);
    assert.deepEqual(await groupsShown(desktop.page), [
      ['building', [962]],
      ['in_review', [961]],
      ['held', [966]],
      ['blocked', [963, 964, 965]],
    ]);
    assert.deepEqual(await desktop.page.$$eval('.fleet-tickets [data-ticket]', (els) => els.map((t) => Number(t.getAttribute('data-ticket')))), [962, 961, 966, 963, 964, 965]);
    const fits = await desktop.page.evaluate(() => {
      const main = document.querySelector('main')?.getBoundingClientRect();
      const svg = document.querySelector('svg[data-graph]')?.getBoundingClientRect();
      return main !== undefined && svg !== undefined && svg.right <= main.right - 32;
    });
    assert.equal(fits, true);
    assert.equal(await noSidewaysScroll(desktop.page), true);
    assert.deepEqual(await cspViolations(desktop.page), []);
  } finally {
    await desktop.close();
  }
});

test('gaps: a partial fleet\'s tag is a 44 px toggle with its caret, opening the list of its gaps; a complete one says complete (R3, design rule 10)', async () => {
  const closed = await fleetPage(PHONE, versionReadFailed());
  try {
    const toggle = closed.page.getByRole('button', { name: 'partial · 1 gap', exact: true });
    assert.equal(await toggle.count(), 1, 'the partial tag is a button named by its gaps');
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
    assert.equal((await toggle.boundingBox())?.height, 44);
    assert.deepEqual(await closed.page.$$eval('button.cov [data-part=coverage]', (els) => els.map((e) => [e.className, e.textContent])), [['tag dashed', 'partial · 1 gap']]);
    assert.deepEqual(await closed.page.$$eval('button.cov [aria-hidden=true]', (els) => els.map((e) => e.textContent)), ['▾']);
    assert.equal(await closed.page.locator('[data-part=gaps]').count(), 0);
    assert.deepEqual(await cspViolations(closed.page), []);
  } finally {
    await closed.close();
  }
  const open = await fleetPage(PHONE, versionReadFailed(), true);
  try {
    const toggle = open.page.getByRole('button', { name: 'partial · 1 gap', exact: true });
    assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
    assert.deepEqual(await open.page.$$eval('button.cov [aria-hidden=true]', (els) => els.map((e) => e.textContent)), ['▴']);
    assert.deepEqual(await open.page.$$eval('ul.gaps[data-part=gaps] li', (els) => els.map((e) => e.textContent)), [`command_failed · r1 version(github) · ${VERSION_FAILED}`]);
    assert.equal(await noSidewaysScroll(open.page), true);
  } finally {
    await open.close();
  }
  const six = await fleetPage(PHONE, contractExample(3), true);
  try {
    assert.equal(await six.page.getByRole('button', { name: 'partial · 6 gaps', exact: true }).count(), 1);
    assert.equal(await six.page.locator('ul.gaps[data-part=gaps] li').count(), 6);
  } finally {
    await six.close();
  }
  const complete = await fleetPage(PHONE, contractExample(2), true);
  try {
    assert.deepEqual(await complete.page.$$eval('[data-part=coverage]', (els) => els.map((e) => [e.className, e.textContent])), [['', 'complete']]);
    assert.equal(await complete.page.locator('button.cov, [data-part=gaps]').count(), 0);
  } finally {
    await complete.close();
  }
  // Its press asks the caller to open or close it: the view keeps no state.
  let toggled = 0;
  const pressed = elements(FleetDetail({ envelope: versionReadFailed(), width: 358, now: NOW, onOpenThread: () => {}, gapsOpen: false, onToggleGaps: () => toggled++ }));
  const press = pressed.find((e) => e.type === 'button' && e.props['className'] === 'cov')?.props['onClick'];
  assert.equal(typeof press, 'function');
  Reflect.apply(press as () => void, undefined, []);
  assert.equal(toggled, 1);
});

test('tickets: each title on its own line, its facts below it and apart, at 390 and 1440 px; a builder\'s button reads "builder <thread>"', async () => {
  for (const [viewport, threads] of [
    [PHONE, ['builder thr_syn_0962', 'builder thr_syn_0961']],
    [DESKTOP, ['builder thr_syn_0962', 'builder thr_syn_0961']],
  ] as const) {
    const p = await fleetPage(viewport, specThreeFleet());
    try {
      const bad = await p.page.$$eval('.fleet-tickets [data-ticket]', (tickets) =>
        tickets.flatMap((t) => {
          const n = t.getAttribute('data-ticket');
          const title = t.querySelector('[data-part=title-line]')?.getBoundingClientRect();
          const facts = [...(t.querySelector('[data-part=facts]')?.children ?? [])].map((e) => e.getBoundingClientRect());
          if (!title || facts.length === 0) return [`#${n}: no title line or facts`];
          const out = title.bottom > (facts[0]?.top ?? 0) ? [`#${n}: its title and facts share a line`] : [];
          for (let i = 1; i < facts.length; i++) {
            const [a, b] = [facts[i - 1], facts[i]];
            if (a && b && Math.abs(a.top - b.top) < 2 && b.left - a.right < 4) out.push(`#${n}: facts ${i - 1} and ${i} touch`);
          }
          return out;
        }),
      );
      assert.deepEqual(bad, [], `at ${viewport.width} px`);
      assert.deepEqual(await p.page.$$eval('[data-thread]', (els) => els.map((e) => (e instanceof HTMLElement ? e.innerText : ''))), threads);
    } finally {
      await p.close();
    }
  }
});

/**
 * Each marker's greyscale mask, with every word and label replaced by the
 * same text, so only its glyph and shape are left; and its colours.
 */
type Rect = { x: number; y: number; width: number; height: number };

async function markerShapes(page: Page, selector: string, clip: (box: Rect) => Rect) {
  await page.evaluate(() => {
    document.documentElement.style.filter = 'grayscale(1)';
    for (const w of document.querySelectorAll('[data-part=word]')) w.textContent = 'state';
    for (const l of document.querySelectorAll('[data-part=label]')) l.textContent = '#000';
    for (const f of document.querySelectorAll('[data-ticket] [data-part=facts] > :not([data-part=state])')) if (f instanceof HTMLElement || f instanceof SVGElement) f.style.visibility = 'hidden';
  });
  const shapes = new Map<string, { tier: string; colours: string; mask: Mask }>();
  for (const el of await page.locator(selector).all()) {
    const kind = (await el.getAttribute('data-state')) ?? '';
    if (shapes.has(kind)) continue;
    await el.evaluate((e) => e.scrollIntoView({ block: 'center' }));
    const box = await el.boundingBox();
    assert.ok(box, `a ${kind} marker is shown`);
    const colours = await el.evaluate((e) =>
      [e, ...e.querySelectorAll(':scope > rect, :scope > text')].map((x) => {
        const s = getComputedStyle(x);
        return [s.color, s.backgroundColor, s.fill, s.stroke].join(' ');
      }).join(' | '),
    );
    // Whole pixels, so every clip of one size is that size.
    const at = { x: Math.round(box.x), y: Math.round(box.y), width: Math.round(box.width), height: Math.round(box.height) };
    shapes.set(kind, { tier: (await el.getAttribute('data-tier')) ?? '', colours, mask: png.inkMask(png.decodePng(await page.screenshot({ clip: clip(at) }))) });
  }
  return shapes;
}

/** Every pair differs by shape alone; states in one tier also share colours. */
function compareShapes(shapes: Map<string, { tier: string; colours: string; mask: Mask }>) {
  const kinds = [...shapes.keys()];
  const diffs: Record<string, number> = {};
  let sameTier = 0;
  for (let i = 0; i < kinds.length; i++) {
    for (let j = i + 1; j < kinds.length; j++) {
      const a = shapes.get(kinds[i] ?? '');
      const b = shapes.get(kinds[j] ?? '');
      assert.ok(a && b);
      assert.equal(a.mask.width * a.mask.height, b.mask.width * b.mask.height, 'every clip is the same size');
      if (a.tier === b.tier) {
        assert.equal(a.colours, b.colours, `${kinds[i]} and ${kinds[j]} share ${a.tier}, so their colours are the same`);
        sameTier++;
      }
      const d = png.maskDifference(a.mask, b.mask);
      diffs[`${kinds[i]}-${kinds[j]}`] = d;
      assert.ok(d >= DISTINCT_PIXELS, `${kinds[i]} (${a.tier}) and ${kinds[j]} (${b.tier}) look the same in greyscale (${d} px differ)`);
    }
  }
  return { compared: Object.keys(diffs).length, sameTier, diffs };
}

test('S3-3: in greyscale, every two states differ by glyph and shape alone, in the graph and in the list', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    const p = await fleetPage(viewport, everyStateFleet());
    try {
      assert.equal(await p.page.locator('svg[data-graph]').count(), 1, 'the graph is drawn');
      const boxes = await markerShapes(p.page, '[data-box]', (b) => b);
      assert.deepEqual([...boxes.keys()], ['ready', 'building', 'in_review', 'changes_requested', 'merged', 'held', 'blocked', 'unknown', 'not_merged']);
      // 9 kinds in 5 tiers: t3 and t4 hold three each, so 36 pairs, 6 in one tier.
      const graph = compareShapes(boxes);
      assert.deepEqual([graph.compared, graph.sameTier], [36, 6]);
      const listed = await markerShapes(p.page, '.fleet-tickets [data-ticket] [data-part=state]', (b) => ({ x: b.x - 8, y: b.y - 4, width: 112, height: 28 }));
      assert.deepEqual([...listed.keys()], ['ready', 'building', 'in_review', 'changes_requested', 'merged', 'held', 'blocked', 'unknown']);
      // 8 kinds (a blocker's "not merged" is only in a box): 28 pairs, 4 in one tier.
      const list = compareShapes(listed);
      assert.deepEqual([list.compared, list.sameTier], [28, 4]);
      console.log(`greyscale mask differences at ${viewport.width}px:`, JSON.stringify({ graph: graph.diffs, list: list.diffs }));
      assert.deepEqual(await cspViolations(p.page), []);
    } finally {
      await p.close();
    }
  }
});

test('words: every box and marker shows its word, with its glyph hidden from screen readers; ticket text is plain text, isolated', async () => {
  const e = syntheticFleet(800, [
    { number: 801, state: 'ready', title: HOSTILE.html },
    { number: 802, state: 'blocked', title: HOSTILE.bidi, blockedBy: [801] },
  ], [], HOSTILE.script);
  const p = await fleetPage(DESKTOP, e);
  try {
    assert.deepEqual(await p.page.$$eval('[data-box] [data-part=word]', (els) => els.map((w) => w.textContent)), ['ready', 'blocked']);
    assert.deepEqual(await p.page.$$eval('[data-ticket] [data-part=state] [data-part=word]', (els) => els.map((w) => w.textContent)), ['ready', 'blocked']);
    assert.deepEqual(await p.page.$$eval('[data-part=glyph]', (els) => els.map((g) => g.getAttribute('aria-hidden'))), ['true', 'true', 'true', 'true', 'true', 'true']);
    assert.deepEqual(await p.page.$$eval('[data-ticket] bdi[data-part=title]', (els) => els.map((t) => t.textContent)), [HOSTILE.html, HOSTILE.bidi]);
    assert.equal(await p.page.locator('h2 bdi').textContent(), HOSTILE.script);
    assert.equal(await p.page.locator('img, script, b').count(), 0);
    assert.equal(await p.page.evaluate('window.__pwned'), undefined);
  } finally {
    await p.close();
  }
});

test('agents: a placed builder is a 44 px button that opens its thread; the reviewer says why none is placed', () => {
  const opened: string[] = [];
  const shown = elements(FleetDetail({ envelope: contractExample(2), width: 896, now: NOW, onOpenThread: (t) => opened.push(t), gapsOpen: false, onToggleGaps: () => {} }));
  const buttons = shown.filter((e) => e.type === 'button');
  assert.deepEqual(
    buttons.map((b) => [b.props['data-thread'], b.props['className']]),
    ['thr_syn_0005', 'thr_syn_0006', 'thr_syn_0003', 'thr_syn_0004', 'thr_syn_0002'].map((t) => [t, 'btn']),
  );
  const press = buttons.find((b) => b.props['data-thread'] === 'thr_syn_0004')?.props['onClick'];
  assert.equal(typeof press, 'function');
  Reflect.apply(press as () => void, undefined, []);
  assert.deepEqual(opened, ['thr_syn_0004']);
  const reviewers = shown.filter((e) => e.props['data-fact'] === 'reviewer').map((e) => e.props['children']);
  assert.deepEqual(reviewers, Array(9).fill(REVIEWER));
});

/** Every element FleetDetail renders, its own components called through (they keep no state). */
function elements(node: ReactNode): { type: unknown; props: Record<string, unknown> }[] {
  if (Array.isArray(node)) return node.flatMap((n: ReactNode) => elements(n));
  if (!isValidElement<Record<string, unknown>>(node)) return [];
  if (typeof node.type === 'function') return elements(Reflect.apply(node.type, undefined, [node.props]));
  return [{ type: node.type, props: node.props }, ...elements(node.props['children'] as ReactNode)];
}

test('look: the graph\'s boxes and arrows draw only with the stylesheet\'s own colours', async () => {
  const expected = ['gold', 'ink', 'ink-2', 'ink-3', 'line-2', 'ow-color-attention-tint', 'ow-color-live-tint', 's2', 'wiz'];
  const rgb = (hex: string) => `rgb(${[1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(', ')})`;
  const tokens = new Map(expected.map((name) => [rgb(token(name)), name]));
  const p = await fleetPage(DESKTOP, everyStateFleet());
  try {
    const used = await p.page.$$eval('svg[data-graph] rect, svg[data-graph] text, svg[data-graph] path', (els) =>
      els.flatMap((e) => {
        const s = getComputedStyle(e);
        return [s.fill, s.stroke].filter((c) => c !== 'none');
      }),
    );
    assert.ok(used.length > 0, 'the graph draws');
    assert.deepEqual([...new Set(used.map((c) => tokens.get(c) ?? `not a token: ${c}`))].sort(), expected);
  } finally {
    await p.close();
  }
});

test('"no tickets" only after the fleet\'s ticket list was read in full and is empty; an unread one says why', () => {
  const empty = syntheticFleet(600, []);
  const shown = renderToStaticMarkup(createElement(FleetDetail, { envelope: empty, width: 358, now: NOW, onOpenThread: () => {}, gapsOpen: false, onToggleGaps: () => {} }));
  assert.match(shown, /<p class="effect" data-fallback="empty">no tickets<\/p>/);
  const sub = empty.reads.find((r) => r.kind === 'sub_issues');
  assert.ok(sub?.kind === 'sub_issues');
  sub.outcome = { state: 'failed', gap: 'timed_out', reason: 'the sub-issues of #600 timed out' };
  const unread = renderToStaticMarkup(createElement(FleetDetail, { envelope: empty, width: 358, now: NOW, onOpenThread: () => {}, gapsOpen: false, onToggleGaps: () => {} }));
  assert.doesNotMatch(unread, /no tickets/);
  assert.match(unread, /data-fallback="unread">the graph isn&#x27;t drawn: the fleet&#x27;s tickets weren&#x27;t all read \(the sub-issues of #600 timed out\)/);
});

test('markers: an unread value that names no read still says it is unread', () => {
  assert.deepEqual(ticketMarker({ unread: [] }, []), { kind: 'unknown', tier: 't5', glyph: '[?]', word: 'unknown (unread: no read named)' });
});

test('markers: a state word outside the contract\'s list is unsure (t5, [?]), shown word for word, never guessed', () => {
  for (const word of ['in review', 'MERGED', 'not_merged', HOSTILE.bidi]) {
    const state: FleetTicket['state'] = JSON.parse(JSON.stringify({ known: word }));
    assert.deepEqual(ticketMarker(state, []), { kind: 'unknown', tier: 't5', glyph: '[?]', word }, word);
  }
});
