// #537 (0.0.10 T4), CK3: the command bar's parser, a pure function over the
// page's own data, table-tested for every word, bad input included. `y` and
// `approve` act only on the item open on screen, bound to what was seen when
// it opened. Synthetic fixtures only (test/fixtures/cockpit/, #536's); a
// fixture test never proves live behaviour.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { bindingOf, needKey, readCockpitText } from '../../src/cockpit.ts';
import type { Cockpit, Need } from '../../src/cockpit.ts';
import { bindingLine, crumbs, follow, narrow, openKeys, run, scopeOf, shown, TOP } from '../../src/command.ts';
import type { Context, Opened, Scope } from '../../src/command.ts';

const T = 1_800_000_000_000;
const AT = { mono: 0, wall: T };

function load(name: 'target' | 'empty'): Cockpit {
  const r = readCockpitText(readFileSync(new URL(`../fixtures/cockpit/${name}.json`, import.meta.url), 'utf8'));
  assert.ok(r.ok, !r.ok ? r.why : '');
  return r.cockpit;
}

// #1877: synthetic sources already 69,999 ms old at assembly/receipt.
// Parse the wire response so receipt cannot silently refresh retained data.
function agedEmpty(): Cockpit {
  const doc = JSON.parse(readFileSync(new URL('../fixtures/cockpit/empty.json', import.meta.url), 'utf8'));
  for (const part of ['projects', 'needs_you', 'agents']) {
    doc[part].freshness.snapshot_at.known = T - 69_999;
  }
  const r = readCockpitText(JSON.stringify(doc));
  assert.ok(r.ok, !r.ok ? r.why : '');
  return r.cockpit;
}

const ATLAS: Scope = { project: 'prj_syn_atl1', fleet: null, ticket: null };
const LANTERN: Scope = { project: 'prj_syn_lan2', fleet: null, ticket: null };
const FLEET_901: Scope = { project: 'prj_syn_atl1', fleet: 901, ticket: null };
const TICKET_904: Scope = { project: 'prj_syn_atl1', fleet: 901, ticket: 904 };

function ctx(over: Partial<Context> = {}): Context {
  return { c: load('target'), received: AT, now: AT, machine: null, scope: TOP, open: null, answered: () => null, ...over };
}
const need = (c: Cockpit, ticket: number): Need => {
  const n = c.needs_you.items.find((x) => x.ticket === ticket);
  assert.ok(n, `no item #${ticket}`);
  return n;
};
/** The item as the bar opens it: its key and what it was bound to on screen. */
const opened = (c: Cockpit, ticket: number): Opened => {
  const n = need(c, ticket);
  const at = c.needs_you.items.indexOf(n);
  return { key: openKeys(c.needs_you.items)[at]!, ticket, binding: bindingOf(c, n) };
};
const said = (input: string, over: Partial<Context> = {}) => run(input, ctx(over)).line;
const words = (input: string, over: Partial<Context> = {}) => said(input, over)?.text;

const PARTIAL = 'this read is partial: more may exist';
const UNKNOWN = 'Unknown command. Try ls, cd, next, blockers, a number or y.';

test("CK3 command contracts preserve navigation, approval binding and honest scope", async (t) => {
  for (const [name, proof] of [
    ["CK3 ls: listing contracts keep scope, completeness and project provenance", (t) => {
      for (const [name, proof] of [
        // ── ls ──
        ['CK3 ls: the top lists each project with its agents and Needs you, and the unplaced last', () => {
          assert.deepEqual(said('ls'), {
            input: 'ls',
            tone: 'done',
            text: `3 projects · ${PARTIAL}`,
            items: ['Atlas · 3 agents · 2 need you', 'Lantern · 2 agents · 1 needs you', 'Orchard · 0 agents · 0 need you', 'Not placed · 1 agent · 1 needs you'],
          });
        }],
        ['CK3 ls: a project lists its fleets; a fleet its tickets; a ticket its agents and items', () => {
          assert.deepEqual(said('ls', { scope: ATLAS })?.items, ['#901 · 3 agents · 2 need you', 'Not placed · 1 agent · 1 needs you']);
          assert.equal(words('ls', { scope: ATLAS }), `1 fleet with running agents or Needs you in Atlas · ${PARTIAL}`);
          assert.deepEqual(said('ls', { scope: FLEET_901 })?.items, ['#904 · 1 agent · 1 needs you', '#905 · 1 agent · 0 need you', '#910 · 1 agent · 0 need you', '#907 · 0 agents · 1 needs you', 'Not placed · 1 agent · 0 need you']);
          assert.equal(words('ls', { scope: FLEET_901 }), `4 tickets with running agents or Needs you in Atlas / #901 · ${PARTIAL}`);
          assert.deepEqual(said('ls', { scope: TICKET_904 })?.items, ['Agent: sync queue · building', 'Agent: Research: tokenizers · state unknown', 'Item 1: needs_info']);
          assert.equal(words('ls', { scope: TICKET_904 }), `#904 in Atlas / #901 · ${PARTIAL}`);
        }],
        ['CK3 ls: a complete, fresh read says nothing about partial', () => {
          assert.equal(words('ls', { c: load('empty') }), '2 projects');
        }],
        ['CK3 ls: in a fleet, an agent whose project is unknown is not placed under a ticket number of this project', () => {
          const c = load('target');
          const stranger = structuredClone(c.agents.items[0]!);
          stranger.thread = 'thr_syn_0099';
          stranger.project = { unknown: 'synthetic: the session is not in a project group' };
          stranger.ticket = { known: 950 };
          c.agents.items.push(stranger);
          assert.deepEqual(said('ls', { c, scope: FLEET_901 })?.items, ['#904 · 1 agent · 1 needs you', '#905 · 1 agent · 0 need you', '#910 · 1 agent · 0 need you', '#907 · 0 agents · 1 needs you', 'Not placed · 2 agents · 0 need you']);
        }],
      ] as const) {
        t.diagnostic(name);
        proof();
      }
    }],
    ["CK3 cd: navigation contracts resolve names, IDs and parent scopes", (t) => {
      for (const [name, proof] of [
        // ── cd ──
        ['CK3 cd: a project by name, any case, or a unique prefix; a fleet or ticket by number, with or without #', () => {
          for (const input of ['cd atlas', 'cd Atlas', 'cd ATL', 'cd at', 'cd prj_syn_atl1']) {
            const r = run(input, ctx());
            assert.deepEqual(r.scope, ATLAS, input);
            assert.equal(r.open, null, `${input}: navigation closes the open item`);
            assert.equal(r.line?.text, 'Now in Atlas · 3 need you · 4 agents', input);
          }
          assert.deepEqual(run('cd #901', ctx()).scope, FLEET_901);
          assert.equal(words('cd #901'), 'Now in Atlas / #901 · 2 need you · 4 agents');
          assert.deepEqual(run('cd 904', ctx()).scope, TICKET_904);
          assert.equal(words('cd 904'), 'Now in Atlas / #901 / #904 · 1 needs you · 2 agents');
          assert.deepEqual(run('cd lantern', ctx({ scope: FLEET_901 })).scope, LANTERN, 'a project name works from anywhere');
          assert.deepEqual(run('cd 712', ctx({ scope: ATLAS })).scope, { project: 'prj_syn_lan2', fleet: 700, ticket: 712 }, 'a number not under this level is found everywhere');
        }],
        ['CK3 cd: ambiguous or unknown names change nothing and say why', () => {
          const c = load('target');
          c.projects.items.push({ id: 'prj_syn_atl9', name: { known: 'Atlas-web' }, orchestrator: c.projects.items[0]!.orchestrator });
          const amb = run('cd atl', ctx({ c, scope: LANTERN }));
          assert.deepEqual(amb, { line: { input: 'cd atl', tone: 'refused', text: '2 match: Atlas, Atlas-web', items: [] } });
          assert.deepEqual(run('cd atlas', ctx({ c })).scope, ATLAS, 'an exact name wins over a longer one');
          for (const input of ['cd x', 'cd 30', 'cd #999', 'cd /']) {
            const r = run(input, ctx({ scope: ATLAS }));
            assert.equal(r.scope, undefined, input);
            assert.equal(r.line?.tone, 'refused', input);
            assert.equal(r.line?.text, `No project, fleet or ticket called ${input.slice(3)}`, input);
          }
        }],
        ['CK3 cd ..: up one level at a time; at the top it says so and changes nothing', () => {
          assert.deepEqual(run('cd ..', ctx({ scope: TICKET_904 })).scope, FLEET_901);
          assert.deepEqual(run('cd ..', ctx({ scope: FLEET_901 })).scope, ATLAS);
          assert.deepEqual(run('cd ..', ctx({ scope: ATLAS })).scope, TOP);
          assert.equal(words('cd ..', { scope: ATLAS }), 'Now at the top · 4 need you · 6 agents');
          assert.deepEqual(run('cd ..', ctx()), { line: { input: 'cd ..', tone: 'refused', text: 'Already at the top', items: [] } });
          assert.deepEqual(run('cd', ctx({ scope: TICKET_904 })).scope, TOP, 'cd alone goes to the top');
        }],
        // ── review 2 (Codex, at 047e6f3e) ──
        ['CK3 cd: a project id works even when its name is unknown', () => {
          const c = load('target');
          c.projects.items[2]!.name = { unknown: 'synthetic: the name was not read' };
          assert.deepEqual(run('cd prj_syn_orc3', ctx({ c })).scope, { project: 'prj_syn_orc3', fleet: null, ticket: null });
          assert.equal(run('cd orc', ctx({ c })).line?.text, 'No project, fleet or ticket called orc', 'an unknown name never matches a word');
        }],
      ] as const) {
        t.diagnostic(name);
        proof();
      }
    }],
    ["CK3 selection: next and numbered items preserve eligibility and identity", (t) => {
      for (const [name, proof] of [
        ['CK3 next: source age plus time since receipt crosses the 70,000 ms boundary', () => {
          const c = agedEmpty();
          for (const [elapsed, expected] of [
            [1, 'Nothing needs you here'],
            [2, 'No items read here: this read is stale, so something may still need you'],
          ] as const) {
            assert.equal(words('next', { c, now: { mono: elapsed, wall: T + elapsed } }), expected, `${elapsed} ms since receipt`);
          }
        }],
        // ── next and numbers ──
        ['CK3 next: opens the oldest item in scope, bound to what is on screen', () => {
          const c = load('target');
          const r = run('next', ctx({ c }));
          assert.deepEqual(r.open, opened(c, 904));
          assert.equal(r.line?.text, 'Opened 1: #904, oldest waiting (12m)');
          assert.equal(words('next', { scope: LANTERN }), 'Opened 1: #712, oldest waiting (9m)');
          assert.equal(words('next', { scope: { project: 'prj_syn_atl1', fleet: 901, ticket: 907 } }), 'Opened 1: #907, waiting time not reported');
        }],
        ['CK3 next: none in scope says "Nothing needs you here" only when complete and fresh', () => {
          assert.deepEqual(run('next', ctx({ c: load('empty') })), { line: { input: 'next', tone: 'done', text: 'Nothing needs you here', items: [] } });
          const partial = load('empty');
          partial.needs_you.coverage = { state: 'partial', gaps: [{ project: null, kind: 'command_failed', detail: 'synthetic' }] };
          assert.equal(words('next', { c: partial }), 'No items read here: this read is partial, so something may still need you');
          assert.equal(words('next', { c: load('empty'), now: { mono: 70_001, wall: T + 70_001 } }), 'No items read here: this read is stale, so something may still need you');
          assert.equal(words('next', { scope: { project: 'prj_syn_orc3', fleet: null, ticket: null }, c: (() => {
            const c = load('target');
            c.needs_you.items = c.needs_you.items.filter((n) => 'known' in n.project);
            return c;
          })() }), 'No items read here: this read is partial, so something may still need you');
        }],
        ['CK3 numbers: a number opens that item; out of range and non-items are refused', () => {
          const c = load('target');
          const r = run('3', ctx({ c }));
          assert.deepEqual(r.open, opened(c, 907));
          assert.equal(r.line?.text, 'Opened 3: #907 (held)');
          assert.equal(words('1'), 'Opened 1: #904 (needs_info)');
          assert.deepEqual(run('2', ctx({ scope: FLEET_901 })).open?.ticket, 907, 'numbers count what is shown in scope');
          assert.deepEqual(run('7', ctx()), { line: { input: '7', tone: 'refused', text: 'No item 7 (4 shown)', items: [] } });
          assert.equal(words('99999999999999999999'), 'No item 99999999999999999999 (4 shown)');
          for (const input of ['0', '-1', '3.5', '03', '+2']) {
            assert.deepEqual(run(input, ctx()), { line: { input, tone: 'refused', text: `Not an item number: ${input}. Items are numbered from 1.`, items: [] } }, input);
          }
        }],
        ['CK3 numbers: identical unassigned items open as two distinct items', () => {
          const c = load('target');
          const twin = structuredClone(need(c, 31));
          c.needs_you.items.push(twin);
          const keys = openKeys(c.needs_you.items);
          assert.equal(new Set(keys).size, keys.length, 'every shown item has its own key');
          const four = run('4', ctx({ c })).open;
          const five = run('5', ctx({ c })).open;
          assert.ok(four && five);
          assert.notEqual(four.key, five.key);
          assert.equal(keys[3], four.key);
          assert.equal(keys[4], five.key);
        }],
      ] as const) {
        t.diagnostic(name);
        proof();
      }
    }],
    ["CK3 y: approval contracts preserve binding, eligibility and refusal", (t) => {
      for (const [name, proof] of [
        // ── y and approve ──
        ['CK3 y: with nothing open, nothing is sent and it says why', () => {
          for (const input of ['y', 'approve']) {
            assert.deepEqual(run(input, ctx()), { line: { input, tone: 'refused', text: 'Nothing sent. Open an item first (next or a number).', items: [] } });
          }
        }],
        ['CK3 y and approve: open the open item’s Yes, exactly as pressing Yes would; nothing else', () => {
          const c = load('target');
          for (const input of ['y', 'approve']) {
            const r = run(input, ctx({ c, open: opened(c, 904) }));
            assert.deepEqual(r.request, { key: needKey(need(c, 904)), choice: 'yes' }, input);
            assert.equal(r.open, undefined, `${input}: the item stays open`);
            assert.equal(r.line?.text, 'Yes opened on #904: press Send in its row to send it once.');
          }
          const risky = run('y', ctx({ c, open: opened(c, 712) }));
          assert.deepEqual(risky.request, { key: needKey(need(c, 712)), choice: 'yes' });
          assert.equal(risky.line?.text, 'Yes opened on #712: it’s a publish, so its row asks you to confirm twice before it sends once.');
        }],
        ['CK3 y: an item whose proposal, risk or project is unknown is never approved', () => {
          const c = load('target');
          assert.deepEqual(run('y', ctx({ c, open: opened(c, 907) })), { line: { input: 'y', tone: 'refused', text: 'Nothing sent. #907’s proposal isn’t readable here, so y can’t approve it. Answer it on GitHub.', items: [] } });
          assert.deepEqual(run('y', ctx({ c, open: opened(c, 31) })), { line: { input: 'y', tone: 'refused', text: 'Nothing sent. #31 isn’t assigned to a project here, so y can’t approve it.', items: [] } });
          const noRisk = load('target');
          need(noRisk, 904).risky = { unknown: 'synthetic: not classified' };
          assert.equal(run('y', ctx({ c: noRisk, open: opened(noRisk, 904) })).line?.text, 'Nothing sent. #904’s risk isn’t reported here, so y can’t approve it. Answer it on GitHub.');
        }],
        ['CK3 y: after the item changed, vanished, lost its target or went stale, nothing is sent and the binding clears', () => {
          const c = load('target');
          const was = opened(c, 904);
          const changed = load('target');
          need(changed, 904).wording = { known: 'Approve a different plan for #904?' };
          const gone = load('target');
          gone.needs_you.items = gone.needs_you.items.filter((n) => n.ticket !== 904);
          const noTarget = load('target');
          noTarget.projects.items[0]!.orchestrator.target = { known: null };
          const moved = load('target');
          moved.projects.items[0]!.orchestrator.target = { known: 'thr_syn_0009' };
          for (const [name, now] of [['changed', changed], ['gone', gone], ['no target', noTarget], ['another target', moved]] as const) {
            assert.deepEqual(run('y', ctx({ c: now, open: was })), { line: { input: 'y', tone: 'refused', text: 'Nothing sent. #904 changed since you opened it.', items: [] }, open: null }, name);
          }
          const later = { mono: 70_001, wall: T + 70_001 };
          assert.deepEqual(run('y', ctx({ c, open: was, now: later })), { line: { input: 'y', tone: 'refused', text: 'Nothing sent. #904 went stale since you opened it: refresh, then open it again.', items: [] }, open: null });
          assert.equal(run('y', ctx({ c, open: was, scope: LANTERN })).line?.text, 'Nothing sent. #904 changed since you opened it.', 'not on screen any more');
        }],
        ['CK3 y: an item that already has an answer is not opened again', () => {
          const c = load('target');
          const asked: string[] = [];
          const answered = (key: string, binding: string) => {
            asked.push(binding);
            return key === needKey(need(c, 904)) ? 'already has an answer (Yes · sent)' : null;
          };
          const r = run('y', ctx({ c, open: opened(c, 904), answered }));
          assert.deepEqual(r, { line: { input: 'y', tone: 'refused', text: 'Nothing sent. #904 already has an answer (Yes · sent).', items: [] } });
          assert.deepEqual(asked, [bindingOf(c, need(c, 904))], 'the record is read for the binding on screen, never only the item');
        }],
        ['CK3 y: the binding line spells out exactly what y would open, and only then', () => {
          const c = load('target');
          assert.equal(bindingLine('y', ctx({ c, open: opened(c, 904) })), 'y will answer Yes to #904 “Approve the plan for #904: offline sync queue?” · Atlas · you confirm with Send, then it sends once to the orchestrator');
          assert.equal(bindingLine(' approve ', ctx({ c, open: opened(c, 904) })), 'approve will answer Yes to #904 “Approve the plan for #904: offline sync queue?” · Atlas · you confirm with Send, then it sends once to the orchestrator');
          assert.equal(bindingLine('y', ctx({ c, open: opened(c, 712) })), 'y will answer Yes to #712 “Publish release Lantern v0.4?” · Lantern · a publish: you confirm twice, then it sends once to the orchestrator');
          assert.equal(bindingLine('y', ctx({ c, open: opened(c, 907) })), null);
          assert.equal(bindingLine('y', ctx({ c })), null);
          assert.equal(bindingLine('ls', ctx({ c, open: opened(c, 904) })), null);
          assert.equal(bindingLine('yy', ctx({ c, open: opened(c, 904) })), null);
        }],
        // ── review 1 (Codex, at 4b2d2792): the binding, once lost, stays lost; duplicates stay distinct ──
        ['CK3 y: a binding that changed, vanished or went stale stays invalid, even when the item changes back', () => {
          const c = load('target');
          const was = opened(c, 904);
          const changed = load('target');
          need(changed, 904).wording = { known: 'Approve a different plan for #904?' };
          const lost = follow(ctx({ c: changed, open: was }));
          assert.deepEqual(lost, { ...was, lost: 'changed' });
          assert.equal(follow(ctx({ c, open: lost })), lost, 'once lost, it stays lost');
          assert.deepEqual(run('y', ctx({ c, open: lost })), { line: { input: 'y', tone: 'refused', text: 'Nothing sent. #904 changed since you opened it.', items: [] }, open: null }, 'back to what it was: still refused');
          assert.equal(bindingLine('y', ctx({ c, open: lost })), null);
          const stale = follow(ctx({ c, open: was, now: { mono: 70_001, wall: T + 70_001 } }));
          assert.deepEqual(stale, { ...was, lost: 'stale' });
          assert.equal(run('y', ctx({ c, open: stale })).line?.text, 'Nothing sent. #904 went stale since you opened it: refresh, then open it again.');
          assert.deepEqual(follow(ctx({ c: (() => { const g = load('target'); g.needs_you.items = g.needs_you.items.filter((n) => n.ticket !== 904); return g; })(), open: was })), { ...was, lost: 'changed' });
          assert.equal(follow(ctx({ c, open: was })), was, 'unchanged: the same open item');
          assert.equal(follow(ctx({ c })), null);
        }],
      ] as const) {
        t.diagnostic(name);
        proof();
      }
    }],
    ["CK3 blockers: scope and incomplete reads stay explicit", (t) => {
      for (const [name, proof] of [
        ['CK3 blockers: source age plus time since receipt crosses the 70,000 ms boundary', () => {
          const c = agedEmpty();
          for (const [elapsed, expected] of [
            [1, 'Nothing blocking here among running agents and Needs you'],
            [2, 'No blockers read: this read is stale, so something may still block it'],
          ] as const) {
            assert.equal(words('blockers', { c, now: { mono: elapsed, wall: T + elapsed } }), expected, `${elapsed} ms since receipt`);
          }
        }],
        // ── blockers ──
        ['CK3 blockers: held and blocked tickets, then Needs you items, in scope', () => {
          const c = load('target');
          c.agents.items[1]!.state = { known: 'held' };
          c.agents.items[2]!.state = { known: 'blocked' };
          assert.deepEqual(said('blockers', { c, scope: ATLAS }), {
            input: 'blockers',
            tone: 'done',
            text: '5 blocking Atlas, among running agents and Needs you · this read is partial: more may block it',
            items: ['#905 held · Atlas / #901', '#910 blocked · Atlas / #901', '1: #904 needs_info · needs you', '2: #907 held · needs you', '3: #31 needs_info · needs you'],
          });
          assert.deepEqual(said('blockers', { c, scope: LANTERN })?.items, ['1: #712 publish · needs you', '2: #31 needs_info · needs you']);
        }],
        ['CK3 blockers: none says so only when complete and fresh; otherwise it says partial', () => {
          assert.equal(words('blockers', { c: load('empty') }), 'Nothing blocking here among running agents and Needs you');
          const partial = load('empty');
          partial.agents.coverage = { state: 'partial', gaps: [{ project: null, kind: 'command_failed', detail: 'synthetic' }] };
          assert.equal(words('blockers', { c: partial }), 'No blockers read: this read is partial, so something may still block it');
          assert.equal(words('blockers', { c: load('empty'), now: { mono: 70_001, wall: T + 70_001 } }), 'No blockers read: this read is stale, so something may still block it');
        }],
      ] as const) {
        t.diagnostic(name);
        proof();
      }
    }],
    // ── bad input ──
    ['CK3 bad input: empty does nothing; unknown words, capitals and extra words are refused; pasted lines are one bad command', () => {
      for (const input of ['', '   ', '\t']) assert.deepEqual(run(input, ctx()), { line: null }, JSON.stringify(input));
      for (const input of ['LS', 'Next', 'foo', 'yes', 'n', 'no', 'Y', '/', 'cd..']) {
        assert.deepEqual(run(input, ctx()), { line: { input, tone: 'refused', text: UNKNOWN, items: [] } }, input);
      }
      for (const input of ['ls x', 'next 2', 'y 904', 'approve all', 'blockers now']) {
        assert.deepEqual(run(input, ctx()).line?.text, `${input.split(' ')[0]} takes nothing after it.`, input);
      }
      const c = load('target');
      for (const input of ['ls\nnext', 'next\ny', 'y\r\n', 'cd atlas\ny']) {
        const r = run(input, ctx({ c, open: opened(c, 904) }));
        assert.deepEqual(r, { line: { input: input.replace(/\s+/g, ' ').trim(), tone: 'refused', text: 'One command at a time: pasted lines aren’t run.', items: [] } }, JSON.stringify(input));
      }
      const long = `cd ${'a'.repeat(300)}`;
      assert.deepEqual(run(long, ctx()), { line: { input: `${long.slice(0, 40)}…`, tone: 'refused', text: 'Too long for a command (303 characters).', items: [] } });
    }],
    // ── the scope the page shows ──
    ['CK3 scope: the project filter owns the project; a deeper scope holds only under it', () => {
      assert.deepEqual(scopeOf(null, TICKET_904), TOP);
      assert.deepEqual(scopeOf('prj_syn_lan2', TICKET_904), LANTERN);
      assert.deepEqual(scopeOf('prj_syn_atl1', TICKET_904), TICKET_904);
      assert.deepEqual(scopeOf('prj_syn_atl1', TOP), ATLAS);
      assert.deepEqual(crumbs(load('target'), TICKET_904), ['Atlas', '#901', '#904']);
      assert.deepEqual(crumbs(load('target'), TOP), []);
    }],
    ['CK3 narrow: a fleet or ticket narrows Needs you and the grid; unknowns are kept, never excluded as though known', () => {
      const c = load('target');
      const at = (scope: Scope) => shown({ c, scope, machine: null });
      assert.deepEqual(at(FLEET_901).needs.map((n) => n.ticket), [904, 907]);
      assert.deepEqual(at(FLEET_901).agents.map((a) => a.thread), ['thr_syn_0011', 'thr_syn_0012', 'thr_syn_0013', 'thr_syn_0031']);
      assert.deepEqual(at(TICKET_904).needs.map((n) => n.ticket), [904]);
      assert.deepEqual(at(TOP).needs.map((n) => n.ticket), [904, 712, 907, 31]);
      assert.deepEqual(narrow(c, TOP), c, 'the top narrows nothing');
      assert.deepEqual(narrow(c, FLEET_901).projects, c.projects, 'projects and targets are never narrowed');
    }],
  ] as const satisfies readonly (readonly [string, (context: import('node:test').TestContext) => void])[]) {
    t.diagnostic(name);
    await proof(t);
  }
});
