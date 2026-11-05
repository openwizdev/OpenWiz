// #125 (spec 3's C1): the fleets list, on fixtures. The strict reader of
// `openwiz fleets --json` (contracts/fleet.v1.md, "Reading it"), on a table
// of good and bad texts; S3-2, what the list shows of each fleet and "needs
// you" item, in its model and on the page; S3-1, "needs you" always first;
// and S3-3, states told apart without colour. The page proofs run in
// Chromium, with the app's own stylesheet, fonts and CSP, at 390 and 1440 px.
//
// Every await of this file comes before its first test: a test registered
// before an await starts early, and a run of only those never ends.

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { chromium } from 'playwright-core';
import type { Browser, Page } from 'playwright-core';

import { fleetsList, readFleets } from '../../src/fleets.ts';
import type { FleetsEnvelope } from '../../src/fleets.ts';
import type { FleetsProps } from '../../src/components/Fleets.tsx';
import {
  badTexts,
  fleetsChecksFailed,
  fleetsEmpty,
  fleetsAnswered,
  fleetsExample,
  fleetsHostile,
  fleetsListFailed,
  fleetsLong,
  fleetsPartial,
  goodTexts,
  SNAPSHOT_AT,
} from '../support/fleet-fixtures.ts';
import { DESKTOP, elements, Fleets, fleetsPage, PHONE } from '../support/fleets-page.ts';
import { NO_QUESTION } from '../support/fleet-graph-fixtures.ts';
import { HOSTILE } from '../support/synthetic.ts';

// The times the list shows are the device's: the proofs read them in UTC.
process.env['TZ'] = 'UTC';

type Png = { width: number; height: number; data: Uint8Array };
type Mask = { width: number; height: number; mask: Uint8Array };
const png: { decodePng(b: Buffer): Png; inkMask(p: Png): Mask; maskDifference(a: Mask, b: Mask): number } = await import(String(new URL('../support/png.mjs', import.meta.url)));
const { axe }: { axe(page: Page, tags?: string[]): Promise<unknown[]> } = await import(String(new URL('../support/harness.mjs', import.meta.url)));

test("Fleet list reader preserves exact good texts and rejects malformed and deep input", async (t) => {
  for (const [name, proof] of [
    ['reader: takes every good text, the contract\'s example 1 among them, as exactly the JSON it is', () => {
      const rows = goodTexts();
      assert.equal(rows.length, 9);
      for (const [name, text] of rows) {
        const r = readFleets(text);
        assert.ok(r.ok, `${name}: refused at ${r.ok ? '' : `${r.refusal.at} (${r.refusal.why})`}`);
        // These texts have no duplicate key and no 1.0, so JSON.parse reads them faithfully.
        assert.deepEqual(r.envelope, JSON.parse(text), name);
      }
    }],
    ['reader: refuses every bad text, at the value that breaks the contract', () => {
      const rows = badTexts();
      assert.equal(rows.length, 59);
      const wrong: string[] = [];
      for (const b of rows) {
        const r = readFleets(b.text);
        if (r.ok) wrong.push(`${b.name}: taken`);
        else if (r.refusal.at !== b.at) wrong.push(`${b.name}: refused at ${r.refusal.at} (${r.refusal.why}), not ${b.at}`);
      }
      assert.deepEqual(wrong, []);
    }],
    ['reader: a hundred thousand brackets deep is refused, never a crash', () => {
      const r = readFleets(`${'['.repeat(100_000)}${']'.repeat(100_000)}`);
      assert.equal(r.ok, false);
      assert.equal(r.ok ? null : r.refusal.at, '$');
    }],
  ] as const) {
    t.diagnostic(name);
    await proof();
  }
});

// ── S3-2: each row is exactly what spec 1 reports, with unknowns as unknown ──
// Every expected value is a literal from the contract's example 1 (its
// counts, titles and "needs you" items) or from the fixture's own edit.

const envelopeOf = (text: string): FleetsEnvelope => {
  const r = readFleets(text);
  if (!r.ok) throw new Error(`fixture refused at ${r.refusal.at}: ${r.refusal.why}`);
  return r.envelope;
};
const known = (text: string) => ({ text, unknown: false });
const unknown = (text: string) => ({ text, unknown: true });
const mk = (kind: string, tier: string, glyph: string, word: string) => ({ kind, tier, glyph, word });
const NEEDS_INFO = 'a builder\'s question waits for an answer';
const HELD = 'waits for your approval of a changed plan or contract';

// #539: the fleets view reads no comments; no risk label is reported. Each unknown says why, once.
const UNASKED = {
  question: unknown('question unknown (the fleets view does not read comments; openwiz fleet <spec> reads the question)'),
  link: null,
  asked: null,
  risk: unknown('risk unknown (no explicit risk classification was reported)'),
};

test("Fleet list model preserves reported rows and honest partial and empty states", async (t) => {
  for (const [name, proof] of [
    ['S3-2 model: example 1: "needs you" items, then one row per fleet, as the contract reports them', () => {
      assert.deepEqual(fleetsList(envelopeOf(fleetsExample())), {
        snapshotAt: SNAPSHOT_AT,
        partial: false,
        gaps: [],
        needsYou: {
          kind: 'items',
          items: [
            { kind: 'needs_info', marker: mk('needs_info', 't1', '[!]', 'needs_info'), ticket: 904, title: known('Synthetic ticket A3'), need: NEEDS_INFO, spec: 901, fleet: known('Synthetic spec one'), ...UNASKED },
            { kind: 'held', marker: mk('held', 't1', '[!]', 'held'), ticket: 907, title: known('Synthetic ticket A6'), need: HELD, spec: 901, fleet: known('Synthetic spec one'), ...UNASKED },
          ],
        },
        list: { kind: 'complete' },
        fleets: [
          // 901: 9 tickets, 1 merged; moving is building 2 + in_review 1 + changes_requested 1; 1 blocked; #909 unknown.
          { spec: 901, title: known('Synthetic spec one'), merged: '1 of 9 merged', counts: [mk('moving', 't3', '[~]', '4 moving'), mk('blocked', 't4', '[‖]', '1 blocked'), mk('unknown', 't5', '[?]', '1 unknown')] },
          // 930: 2 tickets, none merged or moving; #932 blocked; no unknown, so no unknown count.
          { spec: 930, title: known('Synthetic spec two'), merged: '0 of 2 merged', counts: [mk('moving', 't3', '[~]', '0 moving'), mk('blocked', 't4', '[‖]', '1 blocked')] },
        ],
      });
    }],
    ['S3-2 model: a partial answer: every gap, an unread spec name and progress, and "needs you" unread, never guessed', () => {
      assert.deepEqual(fleetsList(envelopeOf(fleetsPartial())), {
        snapshotAt: SNAPSHOT_AT,
        partial: true,
        gaps: [
          { read: 'r3', subject: 'spec_list()', gap: 'truncated', reason: 'GitHub listed 2 of 3 specs' },
          { read: 'r40', subject: 'checks(955)', gap: 'command_failed', reason: 'the checks of pull request 955 couldn\'t be read' },
          { read: 'r48', subject: 'issue(930)', gap: 'not_found', reason: '#930 couldn\'t be read' },
        ],
        needsYou: { kind: 'unread', marker: mk('unknown', 't5', '[?]', 'unknown (unread: GitHub listed 2 of 3 specs)') },
        list: { kind: 'partial', reason: 'GitHub listed 2 of 3 specs' },
        fleets: [
          { spec: 901, title: known('Synthetic spec one'), merged: null, counts: [mk('unknown', 't5', '[?]', 'progress unknown (unread: the checks of pull request 955 couldn\'t be read)')] },
          { spec: 930, title: unknown('unknown (unread: #930 couldn\'t be read)'), merged: '0 of 2 merged', counts: [mk('moving', 't3', '[~]', '0 moving'), mk('blocked', 't4', '[‖]', '1 blocked')] },
        ],
      });
    }],
    ['S3-2 model: a failed read of an open pull request\'s checks leaves "needs you" known and only #901\'s progress unread', () => {
      const m = fleetsList(envelopeOf(fleetsChecksFailed()));
      assert.equal(m.needsYou.kind, 'items');
      assert.deepEqual(m.fleets.map((f) => [f.spec, f.merged, f.counts.map((c) => c.word)]), [
        [901, null, ['progress unknown (unread: the checks of pull request 955 couldn\'t be read)']],
        [930, '0 of 2 merged', ['0 moving', '1 blocked']],
      ]);
    }],
    ['S3-2 model: the spec list unreadable: no fleet, and both the list and "needs you" say why', () => {
      const m = fleetsList(envelopeOf(fleetsListFailed()));
      assert.deepEqual([m.partial, m.gaps, m.needsYou, m.list, m.fleets], [
        true,
        [{ read: 'r3', subject: 'spec_list()', gap: 'command_failed', reason: 'the spec list couldn\'t be read' }],
        { kind: 'unread', marker: mk('unknown', 't5', '[?]', 'unknown (unread: the spec list couldn\'t be read)') },
        { kind: 'unread', marker: mk('unknown', 't5', '[?]', 'unknown (unread: the spec list couldn\'t be read)') },
        [],
      ]);
    }],
    ['S3-2 model: a complete read that lists no fleet: no items, no rows, and the list complete', () => {
      const m = fleetsList(envelopeOf(fleetsEmpty()));
      assert.deepEqual([m.partial, m.gaps, m.needsYou, m.list, m.fleets], [false, [], { kind: 'items', items: [] }, { kind: 'complete' }, []]);
    }],
  ] as const) {
    t.diagnostic(name);
    await proof();
  }
});

/** Example 1, edited past the contract's rules: the reader takes it (the schema allows it), and the list must not rely on them. */
const broken = (change: (doc: FleetsEnvelope) => void): FleetsEnvelope => {
  const doc = envelopeOf(fleetsExample());
  change(doc);
  return doc;
};

test("Fleet list model preserves read provenance, unknowns and envelope order", async (t) => {
  for (const [name, proof] of [
    ['S3-2 model: a pointer that names no read, or a read of another kind or issue, shows as unknown with why, never as a value', () => {
      const m = fleetsList(
        broken((doc) => {
          const [one, two] = doc.data.fleets;
          if (!one || !two) throw new Error('example 1 has two fleets');
          one.issue = 'r999'; // no such read
          two.issue = 'r49'; // #930's sub_issues read, not an issue read
          doc.data.specs = 'r2'; // the repository read, not the spec list
          doc.data.tickets = doc.data.tickets.map((t) => (t.number === 904 ? { ...t, issue: 'r4' } : t)); // #901's issue read, not #904's
        }),
      );
      assert.deepEqual(m.fleets.map((f) => f.title), [unknown('unknown (read r999 isn\'t on the record)'), unknown('unknown (read r49 isn\'t #930\'s issue read)')]);
      assert.deepEqual(m.list, { kind: 'unread', marker: mk('unknown', 't5', '[?]', 'unknown (read r2 isn\'t the spec list read)') });
      assert.deepEqual(m.needsYou.kind === 'items' ? m.needsYou.items.map((i) => [i.ticket, i.title, i.fleet]) : null, [
        [904, unknown('unknown (read r4 isn\'t #904\'s issue read)'), unknown('unknown (read r999 isn\'t on the record)')],
        [907, known('Synthetic ticket A6'), unknown('unknown (read r999 isn\'t on the record)')],
      ]);
    }],
    ['S3-2 model: a read id on the record twice, a ticket or fleet not on the record, and an unread list naming no incomplete read, each say so', () => {
      const m = fleetsList(
        broken((doc) => {
          doc.reads.push({ id: 'r48', kind: 'issue', issue: 930, outcome: { state: 'complete', value: { title: 'Another title', state: 'open', milestone: null, labels: [], owned_paths: null, relies_on: null } } });
          doc.data.needs_you = { known: [{ kind: 'needs_info', spec: 999, ticket: 998, ...NO_QUESTION }] };
          const [one] = doc.data.fleets;
          if (one) one.progress = { unread: ['r5', 'r777'] };
        }),
      );
      assert.deepEqual(m.fleets.map((f) => [f.title, f.counts.map((c) => c.word)]), [
        [known('Synthetic spec one'), ['progress unknown (unread: read r5 is complete, yet named unread; read r777 isn\'t on the record)']],
        [unknown('unknown (read r48 is on the record twice)'), ['0 moving', '1 blocked']],
      ]);
      assert.deepEqual(m.needsYou, {
        kind: 'items',
        items: [{ kind: 'needs_info', marker: mk('needs_info', 't1', '[!]', 'needs_info'), ticket: 998, title: unknown('unknown (#998 isn\'t on the record as a ticket)'), need: NEEDS_INFO, spec: 999, fleet: unknown('unknown (#999 isn\'t on the record as a fleet)'),
          question: unknown('question unknown (no unique newest needs-you or Needs you comment was found)'), link: null, asked: null, risk: unknown('risk unknown (no explicit risk classification was reported)') }],
      });
    }],
    ['S3-2 model: rows and items keep the envelope\'s order, never re-sorted', () => {
      const m = fleetsList(
        broken((doc) => {
          doc.data.fleets = [...doc.data.fleets].reverse();
          if ('known' in doc.data.needs_you) doc.data.needs_you = { known: [...doc.data.needs_you.known].reverse() };
        }),
      );
      assert.deepEqual(m.fleets.map((f) => f.spec), [930, 901]);
      assert.deepEqual(m.needsYou.kind === 'items' ? m.needsYou.items.map((i) => i.ticket) : null, [907, 904]);
    }],
  ] as const) {
    t.diagnostic(name);
    await proof();
  }
});

// ── the page: S3-1, S3-2 and S3-3 in Chromium ──

/** V2's threshold: two shapes are told apart when their colourless masks differ in at least this many pixels. */
const DISTINCT_PIXELS = 20;
const NOW = new Date(SNAPSHOT_AT + 60_000);

let browser: Browser | null = null;
before(async () => {
  browser = await chromium.launch({ executablePath: process.env['OPENWIZ_CHROMIUM'] ?? '/usr/bin/chromium' });
});
after(async () => {
  await browser?.close();
});

const props = (text: string, more: Partial<FleetsProps> = {}): FleetsProps => ({
  envelope: envelopeOf(text),
  now: NOW,
  fresh: true,
  gapsOpen: false,
  onToggleGaps: () => {},
  onOpen: () => {},
  ...more,
});

async function shown(viewport: { width: number; height: number }, text: string, more: Partial<FleetsProps> = {}) {
  assert.ok(browser, 'Chromium is running');
  return fleetsPage(browser, viewport, props(text, more));
}

/** The list as the page shows it: its sections and headings in order, each item and row, and its states. */
function readList(page: Page) {
  return page.evaluate(() => {
    const root = document.querySelector('[data-part=fleets]');
    if (!root) return null;
    const text = (el: Element | null) => (el ? el.textContent : null);
    const mark = (el: Element) => ({ kind: el.getAttribute('data-kind'), tier: el.getAttribute('data-tier'), glyph: text(el.querySelector('.glyph')), word: text(el.querySelector('.word')) });
    const block = (sel: string) => {
      const el = root.querySelector(sel);
      return el ? { kind: el.getAttribute('data-kind'), text: text(el), states: [...el.querySelectorAll('[data-part=state]')].map(mark) } : null;
    };
    return {
      sections: [...root.children].map((c) => c.getAttribute('data-part')),
      headings: [...root.querySelectorAll('h2')].map(text),
      needs: [...root.querySelectorAll('[data-part=needs-you] [data-need]')].map((b) => ({
        kind: b.getAttribute('data-need'),
        ticket: b.getAttribute('data-ticket'),
        spec: b.getAttribute('data-spec'),
        title: text(b.querySelector('[data-part=title]')),
        states: [...b.querySelectorAll('[data-part=state]')].map(mark),
        need: text(b.querySelector('[data-part=need]')),
        from: text(b.querySelector('[data-part=from]')),
        question: text(b.querySelector('[data-part=question]')),
        asked: text(b.querySelector('[data-part=asked]')),
        link: text(b.querySelector('[data-part=link]')),
        risk: text(b.querySelector('[data-part=risk]')),
      })),
      needsEmpty: block('[data-part=needs-you-empty]'),
      coverage: text(root.querySelector('[data-part=coverage]')),
      snapshot: text(root.querySelector('[data-part=snapshot]')),
      gaps: [...root.querySelectorAll('[data-part=gaps] li')].map(text),
      listPartial: text(root.querySelector('[data-part=list-partial]')),
      rows: [...root.querySelectorAll('[data-part=fleet-list] [data-fleet]')].map((b) => ({
        spec: b.getAttribute('data-fleet'),
        title: text(b.querySelector('[data-part=title]')),
        unknownTitle: b.querySelector('[data-part=title]')?.classList.contains('unknown') ?? null,
        progress: text(b.querySelector('[data-part=progress]')),
        states: [...b.querySelectorAll('[data-part=state]')].map(mark),
      })),
      fleetsEmpty: block('[data-part=fleets-empty]'),
    };
  });
}

const st = (kind: string, tier: string, _glyph: string, word: string) => ({ kind, tier, glyph: '', word });
const EXAMPLE_ROWS = [
  { spec: '901', title: '#901 Synthetic spec one', unknownTitle: false, progress: '1 of 9 merged', states: [st('moving', 't3', '[~]', '4 moving'), st('blocked', 't4', '[‖]', '1 blocked'), st('unknown', 't5', '[?]', '1 unknown')] },
  { spec: '930', title: '#930 Synthetic spec two', unknownTitle: false, progress: '0 of 2 merged', states: [st('moving', 't3', '[~]', '0 moving'), st('blocked', 't4', '[‖]', '1 blocked')] },
];
// #539: the fleets view reads no comments, so each question is unknown with why; no risk label is reported.
const NOT_ASKED = { question: 'question unknown (the fleets view does not read comments; openwiz fleet <spec> reads the question)', asked: null, link: null, risk: 'risk unknown (no explicit risk classification was reported)' };
const EXAMPLE_NEEDS = [
  { kind: 'needs_info', ticket: '904', spec: '901', title: '#904 Synthetic ticket A3', states: [st('needs_info', 't1', '[!]', 'needs_info')], need: NEEDS_INFO, from: 'from #901 Synthetic spec one', ...NOT_ASKED },
  { kind: 'held', ticket: '907', spec: '901', title: '#907 Synthetic ticket A6', states: [st('held', 't1', '[!]', 'held')], need: HELD, from: 'from #901 Synthetic spec one', ...NOT_ASKED },
];

test('S3-2 page: example 1 at 390 and 1440 px: each "needs you" item and fleet row exactly as the contract reports it', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    const p = await shown(viewport, fleetsExample());
    try {
      assert.deepEqual(await readList(p.page), {
        sections: ['needs-you', 'fleet-list'],
        headings: ['Needs you', 'Fleets'],
        needs: EXAMPLE_NEEDS,
        needsEmpty: null,
        coverage: 'complete',
        snapshot: 'snapshot 09:00:00',
        gaps: [],
        listPartial: null,
        rows: EXAMPLE_ROWS,
        fleetsEmpty: null,
      });
      assert.equal(await p.page.locator('[data-part=state] .glyph svg').count(), await p.page.locator('[data-part=state]').count(), 'each state has an inline SVG');
      assert.deepEqual(await p.csp(), []);
    } finally {
      await p.close();
    }
  }
});

test('T6 Home (#539, R2): each need\'s description, its question facts and its answer never overlap, and the facts stay apart, at 390 and 1440 px', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    for (const [name, text] of [['unknown facts', fleetsExample()], ['known, wrapping facts', fleetsAnswered()]] as const) {
      const p = await shown(viewport, text, { home: true, onAnswer: () => {} });
      try {
        // App.tsx puts Home's fleet list in `.home-overview`, which its stylesheet lays out.
        const rows = await p.page.evaluate(() => {
          const home = document.createElement('section');
          home.className = 'home-overview';
          const main = document.querySelector('main');
          if (!main) return null;
          home.append(...main.childNodes);
          main.append(home);
          const box = (el: Element | null) => {
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return { x: r.x, y: r.y, w: r.width, h: r.height };
          };
          return [...document.querySelectorAll('[data-part=needs-you] [data-need]')].map((row) => ({
            ticket: row.getAttribute('data-ticket'),
            description: box(row.querySelector('[data-part=reason]')),
            facts: box(row.querySelector('[data-part=question-facts] > .reason')),
            answer: box(row.querySelector('.act')),
            factsText: (row.querySelector('[data-part=question-facts]') as HTMLElement | null)?.innerText ?? null,
          }));
        });
        assert.ok(rows && rows.length === 2, `${name}: two needs`);
        type Box = { x: number; y: number; w: number; h: number };
        const overlap = (a: Box, b: Box) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
        for (const r of rows) {
          const at = `${name} at ${viewport.width} px, #${r.ticket}`;
          assert.ok(r.description && r.facts && r.answer, `${at}: every part is shown`);
          assert.ok(r.facts.h > 0 && r.description.h > 0, `${at}: both texts have height`);
          for (const [a, b, what] of [[r.description, r.facts, 'description and facts'], [r.description, r.answer, 'description and answer'], [r.facts, r.answer, 'facts and answer']] as const) {
            assert.ok(!overlap(a, b), `${at}: ${what} overlap: ${JSON.stringify([a, b])}`);
          }
          // Each fact is apart from the next: by its separator, or on its own line on a phone.
          assert.match(r.factsText ?? '', /\)( · |\n)risk|B( · |\n)asked/, `${at}: facts run together: ${r.factsText}`);
        }
      } finally {
        await p.close();
      }
    }
  }
});

test('T6 page (#539): a known question shows its first line, asked time, link and risk as plain text, at 390 and 1440 px', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    const p = await shown(viewport, fleetsAnswered());
    try {
      const list = await readList(p.page);
      assert.deepEqual(list?.needs[1], {
        ...EXAMPLE_NEEDS[1],
        question: 'Needs you: choose synthetic option B',
        asked: 'asked 2026-10-31 08:00 UTC',
        link: 'https://example.invalid/synthetic/issues/907#issuecomment-1',
        risk: 'risk: release',
      });
      assert.deepEqual(list?.needs[0], EXAMPLE_NEEDS[0], 'the other item keeps its unknowns');
      assert.equal(await p.page.locator('[data-part=needs-you] a').count(), 0, 'a reported link is text, never a link');
      assert.deepEqual(await p.csp(), []);
    } finally {
      await p.close();
    }
  }
});

test('S3-2 page: a partial answer shows every gap behind a 44 px toggle, the partial list, and each unknown with why', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    const p = await shown(viewport, fleetsPartial(), { gapsOpen: true });
    try {
      assert.deepEqual(await readList(p.page), {
        sections: ['needs-you', 'fleet-list'],
        headings: ['Needs you', 'Fleets'],
        needs: [],
        needsEmpty: { kind: 'unread', text: ' unknown (unread: GitHub listed 2 of 3 specs)', states: [st('unknown', 't5', '[?]', 'unknown (unread: GitHub listed 2 of 3 specs)')] },
        coverage: 'partial · 3 gaps',
        snapshot: 'snapshot 09:00:00',
        gaps: [
          'truncated · r3 spec_list() · GitHub listed 2 of 3 specs',
          'command_failed · r40 checks(955) · the checks of pull request 955 couldn\'t be read',
          'not_found · r48 issue(930) · #930 couldn\'t be read',
        ],
        listPartial: 'partial list: GitHub listed 2 of 3 specs',
        rows: [
          { spec: '901', title: '#901 Synthetic spec one', unknownTitle: false, progress: null, states: [st('unknown', 't5', '[?]', 'progress unknown (unread: the checks of pull request 955 couldn\'t be read)')] },
          { spec: '930', title: '#930 unknown (unread: #930 couldn\'t be read)', unknownTitle: true, progress: '0 of 2 merged', states: [st('moving', 't3', '[~]', '0 moving'), st('blocked', 't4', '[‖]', '1 blocked')] },
        ],
        fleetsEmpty: null,
      });
      const toggle = await p.page.locator('[data-part=fleets] button.cov').boundingBox();
      assert.ok(toggle && toggle.height >= 44, `the gaps toggle is ${toggle?.height} px tall`);
      assert.equal(await p.page.locator('[data-part=fleets] button.cov').getAttribute('aria-expanded'), 'true');
    } finally {
      await p.close();
    }
  }
  // Closed, the gaps aren't listed, and the toggle says so.
  const closed = await shown(PHONE, fleetsPartial());
  try {
    assert.deepEqual((await readList(closed.page))?.gaps, []);
    assert.equal(await closed.page.locator('[data-part=fleets] button.cov').getAttribute('aria-expanded'), 'false');
  } finally {
    await closed.close();
  }
});

test('S3-2 page: "No fleets" and "Nothing needs you" only after a complete, fresh read; otherwise as of its time, or unread with why', async () => {
  const cases: [string, string, boolean, unknown, unknown][] = [
    ['empty, fresh', fleetsEmpty(), true, { kind: 'none', text: 'Nothing needs you', states: [] }, { kind: 'none', text: 'No fleets', states: [] }],
    ['empty, not fresh', fleetsEmpty(), false, { kind: 'none', text: 'Nothing needed you as of 09:00:00', states: [] }, { kind: 'none', text: 'No fleets as of 09:00:00', states: [] }],
    [
      'list unreadable',
      fleetsListFailed(),
      true,
      { kind: 'unread', text: ' unknown (unread: the spec list couldn\'t be read)', states: [st('unknown', 't5', '[?]', 'unknown (unread: the spec list couldn\'t be read)')] },
      { kind: 'unread', text: ' unknown (unread: the spec list couldn\'t be read)', states: [st('unknown', 't5', '[?]', 'unknown (unread: the spec list couldn\'t be read)')] },
    ],
  ];
  for (const [name, text, fresh, needsEmpty, fleetsEmptyShown] of cases) {
    const p = await shown(PHONE, text, { fresh });
    try {
      const list = await readList(p.page);
      assert.deepEqual([list?.needsEmpty, list?.fleetsEmpty, list?.rows, list?.needs], [needsEmpty, fleetsEmptyShown, [], []], name);
    } finally {
      await p.close();
    }
  }
});

test('S3-1: "needs you" is always first: the first section and heading, above every fleet, in every state, at 390 and 1440 px', async () => {
  const fixtures: [string, string][] = [
    ['example 1', fleetsExample()],
    ['checks failed', fleetsChecksFailed()],
    ['partial', fleetsPartial()],
    ['list failed', fleetsListFailed()],
    ['empty', fleetsEmpty()],
    ['long', fleetsLong()],
  ];
  let checked = 0;
  for (const viewport of [PHONE, DESKTOP]) {
    for (const [name, text] of fixtures) {
      for (const fresh of [true, false]) {
        const p = await shown(viewport, text, { fresh, gapsOpen: true });
        try {
          const order = await p.page.evaluate(() => {
            const root = document.querySelector('[data-part=fleets]');
            const top = (el: Element | null | undefined) => (el ? el.getBoundingClientRect().top : null);
            const needs = root?.querySelector('[data-part=needs-you]');
            const rows = [...(root?.querySelectorAll('[data-part=fleet-list] [data-fleet]') ?? [])];
            const items = [...(needs?.querySelectorAll('[data-need]') ?? [])];
            return {
              first: root?.firstElementChild?.getAttribute('data-part') ?? null,
              heading: root?.querySelector('h2')?.textContent ?? null,
              needsTop: top(needs),
              listTop: top(root?.querySelector('[data-part=fleet-list]')),
              lowestItem: items.reduce((m, i) => Math.max(m, i.getBoundingClientRect().bottom), -Infinity),
              highestRow: rows.reduce((m, r) => Math.min(m, r.getBoundingClientRect().top), Infinity),
              items: items.length,
            };
          });
          const where = `${name} (${fresh ? 'fresh' : 'not fresh'}) at ${viewport.width} px`;
          assert.equal(order.first, 'needs-you', where);
          assert.equal(order.heading, 'Needs you', where);
          assert.ok(order.needsTop !== null && order.listTop !== null && order.needsTop < order.listTop, `${where}: "needs you" is above the fleets`);
          assert.ok(order.lowestItem <= order.highestRow, `${where}: every item is above every fleet row`);
          checked++;
        } finally {
          await p.close();
        }
      }
    }
  }
  assert.equal(checked, 24);
});

type Rect = { x: number; y: number; width: number; height: number };

/** Where every state is clipped: around the stage's spot (16, 8), wide enough for any with its word replaced. */
const CLIP: Rect = { x: 8, y: 4, width: 112, height: 28 };

/**
 * Each kind of state's greyscale mask, with every word replaced by the same
 * text, so only its glyph and shape are left; and its colours, so two kinds
 * in one tier can be shown to share them. Each is drawn alone, as a copy of
 * the page's own element at one whole-pixel spot on the canvas: states that
 * sit at different sub-pixel offsets in their rows would differ by
 * anti-aliasing alone, and pass however alike they look.
 */
async function stateShapes(page: Page) {
  await page.evaluate(() => {
    document.documentElement.style.filter = 'grayscale(1)';
    for (const w of document.querySelectorAll('[data-part=state] .word')) w.textContent = 'state';
  });
  const shapes = new Map<string, { tier: string; colours: string; mask: Mask }>();
  for (const el of await page.locator('[data-part=fleets] [data-part=state]').all()) {
    const kind = (await el.getAttribute('data-kind')) ?? '';
    if (shapes.has(kind)) continue;
    const drawn = await el.evaluate((e) => {
      const stage = document.createElement('div');
      stage.setAttribute('data-stage', '');
      Object.assign(stage.style, { position: 'fixed', left: '0', top: '0', zIndex: '100', display: 'flex', padding: '8px 16px', width: '240px', background: '#0e0f11' });
      const copy = e.cloneNode(true);
      stage.append(copy);
      document.body.append(stage);
      const b = copy instanceof Element ? copy.getBoundingClientRect() : null;
      const s = copy instanceof Element ? getComputedStyle(copy) : null;
      const before = copy instanceof Element ? getComputedStyle(copy, '::before') : null;
      return {
        box: b ? { x: b.x, y: b.y, width: b.width, height: b.height } : null,
        colours: s && before ? [s.color, s.backgroundColor, s.boxShadow, before.borderStyle, before.borderColor, before.boxShadow].join(' | ') : '',
      };
    });
    assert.ok(drawn.box, `a ${kind} state is shown`);
    assert.deepEqual([drawn.box.x, drawn.box.y], [16, 8], `${kind} is drawn at the stage's whole-pixel spot`);
    // One clip for every state, so two of different widths are compared over the same pixels (a glyph the
    // bundled font lacks comes from the system's, whose width varies by machine). Each fits in it, with
    // the 6 px its tier's box hangs outside its text.
    const right = drawn.box.x + drawn.box.width + 6;
    const bottom = drawn.box.y + drawn.box.height;
    assert.ok(right <= CLIP.x + CLIP.width && bottom <= CLIP.y + CLIP.height, `${kind} fits the clip (right ${right}, bottom ${bottom})`);
    shapes.set(kind, { tier: (await el.getAttribute('data-tier')) ?? '', colours: drawn.colours, mask: png.inkMask(png.decodePng(await page.screenshot({ clip: CLIP }))) });
    await page.evaluate(() => document.querySelector('[data-stage]')?.remove());
  }
  return shapes;
}

test('S3-3: in greyscale, every two states differ by glyph and shape alone, at 390 and 1440 px', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    // #904 and #907 need you (t1), #930's counts are moving (t3) and blocked (t4), #901's progress is unread (t5).
    const p = await shown(viewport, fleetsChecksFailed());
    try {
      const shapes = await stateShapes(p.page);
      assert.deepEqual([...shapes].map(([kind, s]) => [kind, s.tier]), [
        ['needs_info', 't1'],
        ['held', 't1'],
        ['unknown', 't5'],
        ['moving', 't3'],
        ['blocked', 't4'],
      ]);
      const kinds = [...shapes.keys()];
      const diffs: Record<string, number> = {};
      for (let i = 0; i < kinds.length; i++) {
        for (let j = i + 1; j < kinds.length; j++) {
          const a = shapes.get(kinds[i] ?? '');
          const b = shapes.get(kinds[j] ?? '');
          assert.ok(a && b);
          assert.deepEqual([a.mask.width, a.mask.height], [b.mask.width, b.mask.height], `${kinds[i]} and ${kinds[j]}: every clip is the same size`);
          if (a.tier === b.tier) {
            // One tier keeps one colour; its states still need distinct shapes.
            assert.equal(a.colours, b.colours, `${kinds[i]} and ${kinds[j]} share ${a.tier}, so their colours are the same`);
          }
          const d = png.maskDifference(a.mask, b.mask);
          diffs[`${kinds[i]}-${kinds[j]}`] = d;
          assert.ok(d >= DISTINCT_PIXELS, `${kinds[i]} (${a.tier}) and ${kinds[j]} (${b.tier}) look the same in greyscale (${d} px differ)`);
        }
      }
      assert.equal(Object.keys(diffs).length, 10);
      console.log(`greyscale mask differences at ${viewport.width}px:`, JSON.stringify(diffs));
    } finally {
      await p.close();
    }
  }
});

test('S3-3: no accessibility violation (axe, WCAG 2.2 AA, contrast included), at 390 and 1440 px', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    for (const [name, text] of [
      ['example 1', fleetsExample()],
      ['partial, gaps open', fleetsPartial()],
      ['list failed', fleetsListFailed()],
    ] as const) {
      const p = await shown(viewport, text, { gapsOpen: true });
      try {
        assert.deepEqual(await axe(p.page), [], `${name} at ${viewport.width} px`);
      } finally {
        await p.close();
      }
    }
  }
});

test('layout: in every row, no state overlaps another, the title or a separator, nothing scrolls sideways, and every press is 44 px tall', async () => {
  for (const viewport of [PHONE, DESKTOP]) {
    for (const [name, text] of [
      ['example 1', fleetsExample()],
      ['partial', fleetsPartial()],
      ['long titles', fleetsLong()],
    ] as const) {
      const p = await shown(viewport, text, { gapsOpen: true });
      try {
        const found = await p.page.evaluate(() => {
          const problems: string[] = [];
          const r = (el: Element) => el.getBoundingClientRect();
          // A tier's box hangs 6 px outside its text.
          const hang = (b: DOMRect) => ({ left: b.left - 6, right: b.right + 6, top: b.top, bottom: b.bottom });
          const meet = (a: { left: number; right: number; top: number; bottom: number }, b: { left: number; right: number; top: number; bottom: number }) =>
            a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
          for (const row of document.querySelectorAll('[data-part=fleets] .row')) {
            const id = row.getAttribute('data-fleet') ?? row.getAttribute('data-ticket');
            const states = [...row.querySelectorAll('[data-part=state]')].map((s) => hang(r(s)));
            // The title, the progress, and each separator's dot (its ink, not the spaces around it).
            const dots = [...row.querySelectorAll('[data-part=sep]')].flatMap((sep) => {
              const node = sep.firstChild;
              const at = node?.textContent?.indexOf('·') ?? -1;
              if (!node || at < 0) return [];
              const range = document.createRange();
              range.setStart(node, at);
              range.setEnd(node, at + 1);
              return [range.getBoundingClientRect()];
            });
            const texts = [...[...row.querySelectorAll('[data-part=title], [data-part=progress]')].map((t) => r(t)), ...dots];
            for (let i = 0; i < states.length; i++) {
              const a = states[i];
              if (!a) continue;
              for (let j = i + 1; j < states.length; j++) {
                const b = states[j];
                if (b && meet(a, b)) problems.push(`${id}: states ${i} and ${j} overlap`);
              }
              for (const t of texts) if (meet(a, t)) problems.push(`${id}: state ${i} overlaps the title, the progress or a separator`);
            }
            if (r(row).height < 44) problems.push(`${id}: ${r(row).height} px tall`);
          }
          for (const b of document.querySelectorAll('[data-part=fleets] button')) if (r(b).height < 44) problems.push(`a button is ${r(b).height} px tall`);
          if (document.documentElement.scrollWidth > window.innerWidth) problems.push(`scrolls sideways: ${document.documentElement.scrollWidth} > ${window.innerWidth}`);
          return problems;
        });
        assert.deepEqual(found, [], `${name} at ${viewport.width} px`);
      } finally {
        await p.close();
      }
    }
  }
});

test('inert: hostile titles are plain text, each isolated for bidi; nothing runs, loads or links', async () => {
  const p = await shown(PHONE, fleetsHostile());
  try {
    const list = await readList(p.page);
    assert.deepEqual(list?.needs.map((n) => n.title), [`#904 ${HOSTILE.script}`, `#907 ${HOSTILE.link}`]);
    assert.deepEqual(list?.needs.map((n) => n.from), [`from #901 ${HOSTILE.html}`, `from #901 ${HOSTILE.html}`]);
    assert.deepEqual(list?.rows.map((r) => r.title), [`#901 ${HOSTILE.html}`, `#930 ${HOSTILE.bidi}`]);
    const page = await p.page.evaluate(() => {
      const root = document.querySelector('[data-part=fleets]');
      return {
        elements: [...(root?.querySelectorAll('*') ?? [])].filter((e) => !e.closest('.glyph[aria-hidden="true"]')).map((e) => e.tagName.toLowerCase()).filter((t) => !['div', 'section', 'h2', 'p', 'ul', 'li', 'button', 'span', 'bdi'].includes(t)),
        isolated: [...(root?.querySelectorAll('[data-part=title], [data-part=from]') ?? [])].every((t) => t.querySelector('bdi') !== null),
        pwned: 'Reflect' in window && Reflect.has(window, '__pwned'),
      };
    });
    assert.deepEqual(page, { elements: ['progress', 'progress'], isolated: true, pwned: false });
    assert.deepEqual(await p.page.locator('progress').evaluateAll((els) => els.map((e) => [e.getAttribute('value'), e.getAttribute('max'), e.getAttribute('aria-hidden')])), [['1', '9', 'true'], ['0', '2', 'true']], 'only the two reported progress tracks are added');
    assert.equal(await p.page.locator('[data-part=title] svg, [data-part=from] svg').count(), 0, 'no SVG can come from hostile title text');
    assert.deepEqual(await p.csp(), []);
    assert.deepEqual(p.page.context().pages().length, 1);
  } finally {
    await p.close();
  }
});

test('presses: a fleet row opens its fleet and the gaps toggle asks its caller; nothing else can be pressed, "needs you" items included', () => {
  const opened: number[] = [];
  let toggled = 0;
  const tree = elements(Fleets(props(fleetsPartial(), { onOpen: (spec) => opened.push(spec), onToggleGaps: () => toggled++ })));
  const buttons = tree.filter((e) => e.type === 'button');
  assert.deepEqual(buttons.map((b) => b.props['data-fleet'] ?? b.props['className']), ['cov', 901, 930]);
  for (const b of buttons) Reflect.apply(b.props['onClick'] as () => void, undefined, []);
  assert.deepEqual([opened, toggled], [[901, 930], 1]);

  // An item says what it needs; answering it is C5's, and nothing here acts on it.
  const all = elements(Fleets(props(fleetsExample())));
  assert.deepEqual(all.filter((e) => e.type === 'button').map((b) => b.props['data-fleet']), [901, 930]);
  assert.deepEqual(all.filter((e) => e.props['data-need'] !== undefined).map((e) => [e.type, e.props['onClick'] ?? null]), [
    ['div', null],
    ['div', null],
  ]);
  assert.deepEqual(all.filter((e) => ['a', 'input', 'select', 'textarea', 'form', 'img'].includes(String(e.type))), []);
});
