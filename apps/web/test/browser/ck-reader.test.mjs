// CK1's page half (#536): the cockpit reads `cockpit.v1` exactly. The text is
// parsed strictly, so a key written twice or an integer written `1.0` is
// refused (the orchestrator's ruling on #536), as are a missing or extra key,
// a wrong enum, a complete part with gaps and a risky kind not known risky.
// A refused response shows the error, never its rows or "Nothing needs you".

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { readCockpitText } from '../../src/cockpit.ts';
import { launchBrowser, PHONE } from '../support/browser.mjs';
import { cockpitSite, load, openCockpit } from '../fixtures/cockpit/cockpit.mjs';

const TARGET = JSON.stringify(load('target'));

test('CK1 (page reader): every fixture is read; each malformed text is refused, naming where', () => {
  for (const name of ['target', 'empty']) assert.equal(readCockpitText(JSON.stringify(load(name))).ok, true, name);
  const edit = (fn) => {
    const d = load('target');
    fn(d);
    return JSON.stringify(d);
  };
  const cases = [
    ['a key written twice', TARGET.replace('"schema":"openwiz.cockpit.v1"', '"schema":"openwiz.cockpit.v1","schema":"openwiz.cockpit.v1"'), /written twice/],
    ['an integer written 1.0', TARGET.replace('"ticket":904', '"ticket":904.0'), /needs_you\.items\[0\]\.ticket/],
    ['an exponent', TARGET.replace('"ticket":904', '"ticket":9.04e2'), /ticket/],
    ['a time as a string', TARGET.replace(`"snapshot_at":1800000000000,`, `"snapshot_at":"1800000000000",`), /\$\.snapshot_at/],
    ['an extra key', edit((d) => { d.needs_you.items[0].extra = 1; }), /needs_you\.items\[0\]: keys/],
    ['a missing key', edit((d) => { delete d.agents.items[0].started_at; }), /agents\.items\[0\]: keys/],
    ['a positional array for an object', edit((d) => { d.agents.items[0].location = ['cloud']; }), /location/],
    ['a wrong enum', edit((d) => { d.needs_you.items[0].kind = 'approve'; }), /kind: not one of/],
    ['complete with gaps', edit((d) => { d.agents.coverage = { state: 'complete', gaps: d.agents.coverage.gaps }; }), /complete with gaps/],
    ['a publish item not known risky', edit((d) => { d.needs_you.items[1].risky = { known: false }; }), /always risky/],
    ['fresh without a known time', edit((d) => { d.agents.freshness = { state: 'fresh', snapshot_at: { unknown: 'x' } }; }), /fresh without a known time/],
    ['an empty unknown reason', edit((d) => { d.needs_you.items[2].wording = { unknown: '' }; }), /wording\.unknown/],
    ['a project twice', edit((d) => { d.projects.items.push(d.projects.items[0]); }), /project prj_syn_atl1 twice/],
    ['another schema', edit((d) => { d.schema = 'openwiz.cockpit.v2'; }), /\$\.schema/],
    // The contract's cross-record rules (cockpit.v1.md, "Schema and cross-record checks").
    ['an item twice', edit((d) => { d.needs_you.items.splice(1, 0, structuredClone(d.needs_you.items[0])); }), /an item twice/],
    ['a thread twice', edit((d) => { d.agents.items.splice(1, 0, structuredClone(d.agents.items[0])); }), /thread thr_syn_0011 twice/],
    ['a project that does not resolve', edit((d) => { d.needs_you.items[0].project = { known: 'prj_syn_none' }; }), /prj_syn_none is not in projects/],
    ['an agent project that does not resolve', edit((d) => { d.agents.items[0].project = { known: 'prj_syn_none' }; }), /prj_syn_none is not in projects/],
    ['a gap project that does not resolve', edit((d) => { d.agents.coverage.gaps[0].project = 'prj_syn_none'; }), /prj_syn_none is not in projects/],
    ['partial without a gap', edit((d) => { d.needs_you.coverage = { state: 'partial', gaps: [] }; }), /partial without a gap/],
    ['a snapshot after assembly', edit((d) => { d.needs_you.freshness.snapshot_at.known = d.snapshot_at + 1; }), /a snapshot after assembly/],
    ['fresh, but older than 70 s', edit((d) => { d.agents.freshness.snapshot_at.known = d.snapshot_at - 70_001; }), /fresh does not match its age/],
    ['stale, but within 70 s', edit((d) => { d.agents.freshness = { state: 'stale', snapshot_at: { known: d.snapshot_at } }; }), /stale does not match its age/],
    ['a start after its snapshot', edit((d) => { d.agents.items[0].started_at = { known: d.snapshot_at + 1 }; }), /a start after its snapshot/],
    ['Needs you out of order', edit((d) => { d.needs_you.items.reverse(); }), /not in the contract's order/],
    ['agents out of order', edit((d) => { d.agents.items.reverse(); }), /not in the contract's order/],
    ['projects out of order', edit((d) => { d.projects.items.reverse(); }), /not in ascending id order/],
  ];
  for (const [what, text, where] of cases) {
    const r = readCockpitText(text);
    assert.equal(r.ok, false, what);
    assert.match(r.why, where, what);
  }
});

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

test('CK1 (page reader): a response with a key written twice shows the error, never its rows', async () => {
  const fx = await cockpitSite();
  fx.reply = { status: 200, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', Connection: 'close' }, body: TARGET.replace('"ticket":904', '"ticket":904,"ticket":905') };
  const p = await openCockpit(browser, fx, PHONE);
  try {
    assert.equal(await p.page.locator('[data-part=cockpit] [data-notice=error]').count(), 1);
    assert.equal(await p.page.locator('[data-part=ck-needs-you]').count(), 0);
    assert.equal(await p.page.getByText('Nothing needs you').count(), 0);
  } finally { await p.close(); await fx.close(); }
});
