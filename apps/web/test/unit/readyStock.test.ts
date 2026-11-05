// PA6/PA7 client boundary: optional stock must decode without dropping cockpit.
// Existing cockpit tests cover only producers without the extension.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { readCockpitText } from '../../src/cockpit.ts';
const packet = () => JSON.parse(readFileSync(new URL('../fixtures/ready-stock/partial.json', import.meta.url), 'utf8'));

test('ready stock is decoded in the actual cockpit client and old producers remain valid', () => {
  const doc = packet();
  assert.equal(readCockpitText(JSON.stringify(doc)).ok, true);
  delete doc.ready_stock;
  assert.equal(readCockpitText(JSON.stringify(doc)).ok, true);
});

test('stock wire and source-universe violations cannot invent a healthy factory', () => {
  const mutations = [
    (d: any) => { d.ready_stock.extra = 1; },
    (d: any) => { delete d.ready_stock.projects[0].last_good; },
    (d: any) => { d.ready_stock.projects.pop(); },
    (d: any) => { d.ready_stock.projects.push(d.ready_stock.projects[0]); },
    (d: any) => { d.ready_stock.projects[0].project = 'unconfigured'; },
    (d: any) => { d.ready_stock.projects[0].counts.known.ready = -1; },
    (d: any) => { d.ready_stock.projects[0].counts.known.ready = '3'; },
    (d: any) => { d.ready_stock.projects[0].counts.known.state = 'fed'; },
    (d: any) => { d.ready_stock.projects[1].coverage = { state: 'partial', gaps: [] }; },
    (d: any) => { d.ready_stock.projects[1].last_good.snapshot_at = d.snapshot_at + 1; },
    (d: any) => { d.ready_stock.freshness.snapshot_at.known = d.snapshot_at + 1; },
    (d: any) => { d.ready_stock.projects[0].freshness.state = 'stale'; },
    (d: any) => { d.ready_stock.totals = d.ready_stock.projects[0].counts; },
    (d: any) => { d.ready_stock.coverage.gaps[0].source = 'invented'; },
  ];
  for (const mutate of mutations) { const d = packet(); mutate(d); assert.equal(readCockpitText(JSON.stringify(d)).ok, false); }
  const raw = JSON.stringify(packet());
  assert.equal(readCockpitText(raw.replace('"ready":3', '"ready":3.0')).ok, false);
  assert.equal(readCockpitText(raw.replace('"ready":3', '"ready":3,"ready":3')).ok, false);
});


test('source timestamp captions never advertise a freshness word that can age in place', async () => {
  const { stockReadTime } = await import('../../src/readyStock.ts');
  assert.equal(stockReadTime({ state: 'fresh', snapshot_at: { known: 0 } }), 'source read 1970-01-01T00:00:00.000Z');
});

test('opaque cockpit project IDs remain readable when the stock extension is unavailable', () => {
  const d = packet();
  d.projects.items[1].id = 'zz.synthetic';
  delete d.ready_stock;
  const read = readCockpitText(JSON.stringify(d));
  assert.equal(read.ok, true);
  if (read.ok) assert.equal(read.cockpit.projects.items[1]?.id, 'zz.synthetic');
});
