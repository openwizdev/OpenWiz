// Render the shipped SVG component without a browser. Status identity must
// survive removing colour and styling, including states in the same tier.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
import { inventory, T0 } from '../support/synthetic.ts';

// Keep literal clock expectations independent of the host's time zone.
process.env['TZ'] = 'UTC';

// Same test-only TSX loader used by fleetGraph.test.ts.
registerHooks({
  load(url, context, nextLoad) {
    if (!url.startsWith('file:') || !url.endsWith('.tsx')) return nextLoad(url, context);
    const file = fileURLToPath(url);
    const compilerOptions = { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, verbatimModuleSyntax: true };
    return { format: 'module', source: ts.transpileModule(readFileSync(file, 'utf8'), { fileName: file, compilerOptions }).outputText, shortCircuit: true };
  },
});
const { StatusMark } = await import('../../src/components/StatusMark.tsx');
const { CoverageChip } = await import('../../src/components/Status.tsx');

const fleetStates = [
  ['needs_info', 't1'], ['held', 't1'], ['merged', 't2'], ['building', 't3'], ['in_review', 't3'],
  ['changes_requested', 't3'], ['ready', 't4'], ['blocked', 't4'], ['not_merged', 't4'], ['unknown', 't5'],
] as const;

test("Status presentation preserves glyph identity, literal words and snapshot seconds", async (t) => {
  for (const [name, proof] of [
    ['every fleet marker has a distinct drawn glyph without colour or its word', () => {
      const shapes = fleetStates.map(([shape, tier]) => {
        const html = renderToStaticMarkup(createElement(StatusMark, { shape, tier, word: shape }));
        assert.ok(html.includes(`data-part="word">${shape}</bdi>`), `reported ${shape} word is preserved`);
        const svg = html.match(/<svg\b[\s\S]*?<\/svg>/)?.[0];
        assert.ok(svg, `${shape} has a drawn icon`);
        return svg.replace(/class="[^"]*"/g, '');
      });
      assert.equal(new Set(shapes).size, fleetStates.length, 'each state keeps a distinct shape even within a shared tier');
    }],
    ['a novel reported word is preserved as text with an unknown icon', () => {
      const html = renderToStaticMarkup(createElement(StatusMark, { shape: 'unknown', tier: 't5', word: 'syn-novel-state' }));
      assert.ok(html.includes('data-part="word">syn-novel-state</bdi>'));
      assert.ok(html.includes('stroke-dasharray="3 3"'));
    }],
    ['list and detail coverage visibly distinguish snapshots within the same minute', () => {
      for (const detail of [false, true]) {
        const times = [1_000, 59_000].map((offset) => {
          const envelope = inventory([], { snapshotAt: T0 + offset });
          const html = renderToStaticMarkup(createElement(CoverageChip, { envelope, detail, now: new Date(T0 + 60_000) }));
          return html.match(/<time\b[^>]*>([^<]+)<\/time>/)?.[1];
        });
        assert.deepEqual(times, ['08:00:01', '08:00:59'], `${detail ? 'detail' : 'list'} shows seconds in visible time text`);
      }
    }],
  ] as const) {
    t.diagnostic(name);
    await proof();
  }
});
