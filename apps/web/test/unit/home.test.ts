// #1030: render the adopted Home at public component seams without a browser.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
import { inventory, session, T0 } from '../support/synthetic.ts';
import { fleetsEmpty, fleetsExample } from '../support/fleet-fixtures.ts';
import { readFleets } from '../../src/fleets.ts';

registerHooks({
  load(url, context, nextLoad) {
    if (!url.startsWith('file:') || !url.endsWith('.tsx')) return nextLoad(url, context);
    const file = fileURLToPath(url);
    const compilerOptions = { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, verbatimModuleSyntax: true };
    return { format: 'module', source: ts.transpileModule(readFileSync(file, 'utf8'), { fileName: file, compilerOptions }).outputText, shortCircuit: true };
  },
});
const { HomeLive } = await import('../../src/components/HomeLive.tsx');
const { Fleets } = await import('../../src/components/Fleets.tsx');
process.env['TZ'] = 'UTC';
const now = new Date(T0 + 30_000);
const noop = () => {};
const live = (envelope: ReturnType<typeof inventory> | null, stale = false) => renderToStaticMarkup(createElement(HomeLive, { envelope, stale, failure: null, now, onSelect: noop, onRetry: noop }));

test("Home Live preserves active rows, scope and honest empty states", async (t) => {
  for (const [name, proof] of [
    ['Home Live retains active rows, page scope, gap and freshness', () => {
      const html = live(inventory([
        session(1, { status: { known: 'active' } }), session(2),
        session(3, { status: { known: 'active' } }), session(4, { status: { unknown: 'not read' } }),
      ], { state: 'partial', limit: 4, matched: 12, gaps: [{ kind: 'timed_out', subject: null, detail: 'Synthetic unread source' }] }));
      assert.equal((html.match(/data-session-id=/g) ?? []).length, 2);
      assert.ok(html.includes('thr_web_0001') && html.includes('thr_web_0003'));
      assert.ok(!html.includes('thr_web_0002') && !html.includes('thr_web_0004'));
      assert.ok(html.includes('sessions 1–4 of 12'));
      assert.ok(html.includes('Synthetic unread source'));
      assert.ok(html.includes('partial') && html.includes('08:00:00'));
    }],
    ['Home Live distinguishes unread, fresh zero, partial zero and stale zero', () => {
      assert.ok(live(null).includes('reading sessions…'));
      assert.ok(live(inventory([])).includes('No active sessions</p>'));
      assert.ok(live(inventory([], { state: 'partial' })).includes('No active sessions listed in this snapshot'));
      assert.ok(live(inventory([]), true).includes('No active sessions listed in this snapshot'));
    }],
  ] as const) {
    t.diagnostic(name);
    await proof();
  }
});

test("Home Fleets preserves decision order and partial-zero honesty", async (t) => {
  for (const [name, proof] of [
    ['Home numbers existing decisions before fleets and retains status shapes', () => {
      const result = readFleets(fleetsExample());
      assert.ok(result.ok);
      const html = renderToStaticMarkup(createElement(Fleets, { home: true, envelope: result.envelope, now, fresh: true, gapsOpen: false, onToggleGaps: noop, onOpen: noop, onAnswer: noop }));
      assert.ok(html.includes('<ol class="rows numbered-needs">'));
      assert.equal((html.match(/data-need=/g) ?? []).length, 2);
      assert.ok(html.indexOf('data-part="needs-you"') < html.indexOf('Fleets at a glance'));
      assert.ok(html.includes('M9.5 9a2.5 2.5'));
      assert.ok(html.includes('data-kind="held"'));
    }],
    ['Home never calls a partial zero-decision snapshot Nothing needs you', () => {
      const doc = JSON.parse(fleetsEmpty());
      doc.coverage.state = 'partial';
      doc.reads[0].outcome = { state: 'failed', gap: 'command_failed', reason: 'Synthetic GitHub version unavailable' };
      doc.sources.github.version_tested = false;
      const result = readFleets(JSON.stringify(doc));
      assert.ok(result.ok);
      const html = renderToStaticMarkup(createElement(Fleets, { home: true, envelope: result.envelope, now, fresh: false, gapsOpen: false, onToggleGaps: noop, onOpen: noop, onAnswer: noop }));
      assert.ok(html.includes('No Needs you items read: the snapshot is partial'));
      assert.ok(!html.includes('Nothing needs you'));
    }],
  ] as const) {
    t.diagnostic(name);
    await proof();
  }
});
