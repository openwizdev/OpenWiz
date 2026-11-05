// The plan graph page (0.0.11 U3, #653): `GET /api/v1/plan`, read as
// contracts/plan.v1.md says, and what the page may show with it.
//
// - **Read exactly.** Every object only with exactly its keys; enums only as
//   their strings; integers only as safe integers written as integers; facts
//   only as `{known}` or `{unknown: nonempty}`. The text is parsed strictly
//   (src/fleets.ts's `parseJson`), so a key written twice or `1.0` is refused.
//   The cross-record rules the page relies on are checked too: the contract's
//   order, one row per number, lane references that exist, inverse edges, and
//   issue and pull request links on one repository with their own numbers.
// - **Order is the server's.** Lanes and tickets keep the contract's order;
//   nothing here re-orders. A filter or a fold only narrows what is shown.
// - **Counts are of what was read.** A state column is the server's `column`;
//   an unknown one is counted apart and never coerced. "Yours" is counted
//   apart from the columns: owning a ticket is not needing to act on it.
// - **The chain and the trace use the whole plan,** whatever is folded or
//   filtered out (`dependents` is independent of filters).
// - **Read only.** Nothing here writes; a ticket opens only its own `url`.

import type { Failure } from './api.ts';
import { freshNow } from './cockpit.ts';
import type { Clock, Received } from './cockpit.ts';
import type { Fact, FactString, Unknown } from './envelope.ts';
import { parseJson } from './fleets.ts';
import { factText } from './present.ts';

export const PLAN_SCHEMA_ID = 'openwiz.plan.v1';

// ── the shapes (contracts/plan.v1.schema.json) ──

export type GapKind = 'untested_version' | 'command_failed' | 'timed_out' | 'budget_exhausted' | 'malformed' | 'missing_field' | 'wrong_type' | 'not_found' | 'truncated' | 'unsupported';
export type PlanGap = { kind: GapKind; detail: string };
export type Coverage = { state: 'complete'; gaps: [] } | { state: 'partial'; gaps: PlanGap[] };
export type Freshness = { state: 'fresh' | 'stale'; snapshot_at: { known: number } } | { state: 'unknown'; snapshot_at: Unknown };
export type LaneKind = 'version' | 'side_spec';
export type LaneRef = { kind: LaneKind; number: number };
export type Lane = { kind: LaneKind; number: number; title: FactString };
export type FleetState = 'merged' | 'ready' | 'building' | 'in_review' | 'changes_requested' | 'held' | 'blocked';
export type Column = 'done' | 'building' | 'waiting' | 'needs_you';
export type PullRequest = { number: number; url: string };
export type Ticket = {
  number: number;
  title: FactString;
  url: Fact<string>;
  spec: Fact<number | null>;
  lane: Fact<LaneRef | null>;
  state: Fact<FleetState>;
  column: Fact<Column>;
  labels: Fact<string[]>;
  yours: Fact<boolean>;
  blockers: Fact<number[]>;
  dependents: Fact<number[]>;
  pr: Fact<PullRequest | null>;
};
export type Chain = { root: number; blocked_count: number; path: number[] };
export type Plan = {
  schema: typeof PLAN_SCHEMA_ID;
  snapshot_at: number;
  coverage: Coverage;
  freshness: Freshness;
  lanes: Lane[];
  tickets: Ticket[];
  critical_chain: Fact<Chain | null>;
};
export type PlanOutcome = { kind: 'ok'; envelope: Plan } | Failure;

// ── the reader ──

const GAP_KINDS: readonly GapKind[] = ['untested_version', 'command_failed', 'timed_out', 'budget_exhausted', 'malformed', 'missing_field', 'wrong_type', 'not_found', 'truncated', 'unsupported'];
const STATES: readonly FleetState[] = ['merged', 'ready', 'building', 'in_review', 'changes_requested', 'held', 'blocked'];
const COLUMNS: readonly Column[] = ['done', 'building', 'waiting', 'needs_you'];
const KINDS: readonly LaneKind[] = ['version', 'side_spec'];
const ISSUE_URL = /^https:\/\/github[.]com\/([A-Za-z0-9][A-Za-z0-9_.-]*\/[A-Za-z0-9][A-Za-z0-9_.-]*)\/issues\/([1-9][0-9]*)$/;
const PULL_URL = /^https:\/\/github[.]com\/([A-Za-z0-9][A-Za-z0-9_.-]*\/[A-Za-z0-9][A-Za-z0-9_.-]*)\/pull\/([1-9][0-9]*)$/;

class Refused extends Error {}
type Obj = Map<string, unknown>;

const refuse = (at: string, why: string): never => {
  throw new Refused(`${at}: ${why}`);
};

function exact(v: unknown, at: string, keys: readonly string[]): Obj {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) return refuse(at, 'not an object');
  const o: Obj = new Map(Object.entries(v));
  if (o.size !== keys.length || !keys.every((k) => o.has(k))) return refuse(at, `keys are not exactly ${keys.join(', ')}`);
  return o;
}
const text = (v: unknown, at: string): string => (typeof v === 'string' && v !== '' ? v : refuse(at, 'not a nonempty string'));
const whole = (min: number) => (v: unknown, at: string): number => (typeof v === 'number' && Number.isSafeInteger(v) && v >= min ? v : refuse(at, `not an integer of at least ${min}`));
const time = whole(0);
const issue = whole(1);
const bool = (v: unknown, at: string): boolean => (typeof v === 'boolean' ? v : refuse(at, 'not a boolean'));
function oneOf<T extends string>(list: readonly T[]) {
  return (v: unknown, at: string): T => list.find((x) => x === v) ?? refuse(at, `not one of ${list.join(', ')}`);
}
function items<T>(v: unknown, at: string, read: (x: unknown, at: string) => T): T[] {
  return Array.isArray(v) ? v.map((x, i) => read(x, `${at}[${i}]`)) : refuse(at, 'not a list');
}
function fact<T>(read: (v: unknown, at: string) => T) {
  return (v: unknown, at: string): Fact<T> => {
    if (typeof v === 'object' && v !== null && 'known' in v) return { known: read(exact(v, at, ['known']).get('known'), `${at}.known`) };
    return { unknown: text(exact(v, at, ['unknown']).get('unknown'), `${at}.unknown`) };
  };
}
const nullable = <T,>(read: (v: unknown, at: string) => T) => (v: unknown, at: string): T | null => (v === null ? null : read(v, at));

/**
 * Whether `a` comes strictly before `b` in Unicode scalar order, which is the
 * server's order (Rust compares `String`s by their UTF-8 bytes, the same order).
 * JavaScript's `<` compares UTF-16 code units, which differs past U+FFFF.
 */
export function scalarBefore(a: string, b: string): boolean {
  const x = Array.from(a);
  const y = Array.from(b);
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const p = x[i]?.codePointAt(0) ?? 0;
    const q = y[i]?.codePointAt(0) ?? 0;
    if (p !== q) return p < q;
  }
  return x.length < y.length;
}

/** A list of unique values, each strictly after the one before (numbers ascending, strings in scalar order). */
function ascending<T extends number | string>(list: T[], at: string): T[] {
  list.forEach((x, i) => {
    const prev = list[i - 1];
    const before = typeof prev === 'string' && typeof x === 'string' ? scalarBefore(prev, x) : prev !== undefined && prev < x;
    if (i > 0 && !before) refuse(`${at}[${i}]`, 'not unique and ascending');
  });
  return list;
}
const issues = (v: unknown, at: string): number[] => ascending(items(v, at, issue), at);
const labels = (v: unknown, at: string): string[] => ascending(items(v, at, text), at);

function gap(v: unknown, at: string): PlanGap {
  const o = exact(v, at, ['kind', 'detail']);
  return { kind: oneOf(GAP_KINDS)(o.get('kind'), `${at}.kind`), detail: text(o.get('detail'), `${at}.detail`) };
}
function coverage(v: unknown, at: string): Coverage {
  const o = exact(v, at, ['state', 'gaps']);
  const state = oneOf(['complete', 'partial'] as const)(o.get('state'), `${at}.state`);
  const gaps = items(o.get('gaps'), `${at}.gaps`, gap);
  if (state === 'complete') return gaps.length === 0 ? { state, gaps: [] } : refuse(at, 'complete with gaps');
  return gaps.length > 0 ? { state, gaps } : refuse(at, 'partial without a gap');
}
function freshness(v: unknown, at: string): Freshness {
  const o = exact(v, at, ['state', 'snapshot_at']);
  const state = oneOf(['fresh', 'stale', 'unknown'] as const)(o.get('state'), `${at}.state`);
  const snap = fact(time)(o.get('snapshot_at'), `${at}.snapshot_at`);
  if (state === 'unknown') return 'unknown' in snap ? { state, snapshot_at: snap } : refuse(at, 'unknown freshness with a known time');
  return 'known' in snap ? { state, snapshot_at: snap } : refuse(at, `${state} without a known time`);
}
function laneRef(v: unknown, at: string): LaneRef {
  const o = exact(v, at, ['kind', 'number']);
  return { kind: oneOf(KINDS)(o.get('kind'), `${at}.kind`), number: issue(o.get('number'), `${at}.number`) };
}
function lane(v: unknown, at: string): Lane {
  const o = exact(v, at, ['kind', 'number', 'title']);
  return { kind: oneOf(KINDS)(o.get('kind'), `${at}.kind`), number: issue(o.get('number'), `${at}.number`), title: fact(text)(o.get('title'), `${at}.title`) };
}
function pr(v: unknown, at: string): PullRequest {
  const o = exact(v, at, ['number', 'url']);
  return { number: issue(o.get('number'), `${at}.number`), url: text(o.get('url'), `${at}.url`) };
}
function ticket(v: unknown, at: string): Ticket {
  const o = exact(v, at, ['number', 'title', 'url', 'spec', 'lane', 'state', 'column', 'labels', 'yours', 'blockers', 'dependents', 'pr']);
  return {
    number: issue(o.get('number'), `${at}.number`),
    title: fact(text)(o.get('title'), `${at}.title`),
    url: fact(text)(o.get('url'), `${at}.url`),
    spec: fact(nullable(issue))(o.get('spec'), `${at}.spec`),
    lane: fact(nullable(laneRef))(o.get('lane'), `${at}.lane`),
    state: fact(oneOf(STATES))(o.get('state'), `${at}.state`),
    column: fact(oneOf(COLUMNS))(o.get('column'), `${at}.column`),
    labels: fact(labels)(o.get('labels'), `${at}.labels`),
    yours: fact(bool)(o.get('yours'), `${at}.yours`),
    blockers: fact(issues)(o.get('blockers'), `${at}.blockers`),
    dependents: fact(issues)(o.get('dependents'), `${at}.dependents`),
    pr: fact(nullable(pr))(o.get('pr'), `${at}.pr`),
  };
}
function chain(v: unknown, at: string): Chain {
  const o = exact(v, at, ['root', 'blocked_count', 'path']);
  const path = items(o.get('path'), `${at}.path`, issue);
  const root = issue(o.get('root'), `${at}.root`);
  if (path.length === 0 || path[0] !== root) refuse(`${at}.path`, 'does not begin with the root');
  if (new Set(path).size !== path.length) refuse(`${at}.path`, 'repeats a ticket');
  return { root, blocked_count: time(o.get('blocked_count'), `${at}.blocked_count`), path };
}

const BUSY: readonly FleetState[] = ['building', 'in_review', 'changes_requested'];
const HOLDS = ['held', 'needs-info'];

/**
 * The cross-record rules this page relies on (contracts/plan.v1.md). A
 * contradiction refuses the whole response; a fact the rest of the response
 * cannot support is said as unknown instead (see `settle`).
 */
function crossRecords(p: Plan): void {
  const laneKey = (l: LaneRef) => `${l.kind}:${l.number}`;
  const order = (l: LaneRef) => (l.kind === 'version' ? 0 : 1);
  p.lanes.forEach((l, i) => {
    const prev = p.lanes[i - 1];
    if (prev && !(order(prev) < order(l) || (order(prev) === order(l) && prev.number < l.number))) refuse(`$.lanes[${i}]`, 'not in the contract\'s order');
  });
  // A source time after assembly is no established clock relationship: never fresh or stale.
  if (p.freshness.state !== 'unknown' && p.freshness.snapshot_at.known > p.snapshot_at) refuse('$.freshness', 'a source time after assembly');
  const lanes = new Set(p.lanes.map(laneKey));
  let repo: string | null = null;
  const sameRepo = (r: string, at: string) => {
    if (repo !== null && repo !== r) refuse(at, 'a link to another repository');
    repo = r;
  };
  const specLane = new Map<number, string>();
  p.tickets.forEach((t, i) => {
    const at = `$.tickets[${i}]`;
    const prev = p.tickets[i - 1];
    if (prev && !(prev.number < t.number)) refuse(at, 'not unique and in number order');
    if ('known' in t.lane && t.lane.known !== null && !lanes.has(laneKey(t.lane.known))) refuse(`${at}.lane`, 'names a lane that is not listed');
    // One spec, one lane: a ticket belongs to its parent spec's lane.
    if ('known' in t.spec && t.spec.known !== null && 'known' in t.lane && t.lane.known !== null) {
      const key = laneKey(t.lane.known);
      const seen = specLane.get(t.spec.known);
      if (seen !== undefined && seen !== key) refuse(`${at}.lane`, `spec #${t.spec.known} placed in two lanes`);
      specLane.set(t.spec.known, key);
    }
    if ('known' in t.url) {
      const m = ISSUE_URL.exec(t.url.known);
      if (!m || Number(m[2]) !== t.number) refuse(`${at}.url`, 'not this ticket\'s GitHub issue link');
      else sameRepo(m[1] ?? '', `${at}.url`);
    }
    if ('known' in t.pr && t.pr.known !== null) {
      const m = PULL_URL.exec(t.pr.known.url);
      if (!m || Number(m[2]) !== t.pr.known.number) refuse(`${at}.pr`, 'not this pull request\'s GitHub link');
      else sameRepo(m[1] ?? '', `${at}.pr`);
    }
    // Ownership is exactly the ready-for-human label; the column follows the contract's rules.
    const labels = 'known' in t.labels ? t.labels.known : null;
    // An unread label list leaves ownership unknown, never known either way.
    if (labels === null && 'known' in t.yours) refuse(`${at}.yours`, 'ownership known without its labels');
    if (labels && 'known' in t.yours && t.yours.known !== labels.includes('ready-for-human')) refuse(`${at}.yours`, 'not what its labels say');
  });
  // Edges: known lists are each other's inverse. A number not listed is a
  // prerequisite whose read failed: allowed only in a partial read, which then
  // cannot claim a chain (contract: "missing referenced node").
  const byNumber = new Map(p.tickets.map((t) => [t.number, t]));
  // A known column is exactly what the contract's ordered rules give from known facts.
  p.tickets.forEach((t, i) => {
    if (!('known' in t.column)) return;
    const want = columnOf(t, byNumber);
    if (want === null) refuse(`$.tickets[${i}].column`, 'known without the facts its rules need');
    else if (want !== t.column.known) refuse(`$.tickets[${i}].column`, `${t.column.known} where its facts give ${want}`);
  });
  p.tickets.forEach((t, i) => {
    for (const [name, list, other] of [['blockers', t.blockers, 'dependents'], ['dependents', t.dependents, 'blockers']] as const) {
      if (!('known' in list)) continue;
      for (const n of list.known) {
        const peer = byNumber.get(n);
        if (!peer) {
          if (p.coverage.state !== 'partial' || !('unknown' in p.critical_chain)) refuse(`$.tickets[${i}].${name}`, `names #${n}, which is not listed, in a read that claims it complete`);
          continue;
        }
        const back = peer[other];
        if ('known' in back && !back.known.includes(t.number)) refuse(`$.tickets[${i}].${name}`, `#${n} does not list #${t.number} back`);
      }
    }
  });
}

/**
 * The contract's column rules, in order, from positively known facts only;
 * `null` when a fact an earlier rule needs is unread (contracts/plan.v1.md,
 * "States, ownership and columns").
 */
function columnOf(t: Ticket, byNumber: ReadonlyMap<number, Ticket>): Column | null {
  const state = 'known' in t.state ? t.state.known : null;
  if (state === 'merged') return 'done';
  // Rule 1 must be excluded before any later rule: a known unmerged state, or no closing PR.
  const unmerged = (state !== null) || ('known' in t.pr && t.pr.known === null);
  if (!unmerged) return null;
  if (!('known' in t.labels)) return null;
  const labels = t.labels.known;
  if (labels.some((l) => HOLDS.includes(l))) return 'needs_you';
  if (state !== null && BUSY.includes(state)) return 'building';
  if (labels.includes('ready-for-human')) {
    // Rule 4: no closing PR, and every prerequisite verified merged.
    if (!('known' in t.pr)) return null;
    if (t.pr.known === null) {
      if (!('known' in t.blockers)) return null;
      // Each prerequisite: merged, not merged, or not established.
      const merged = t.blockers.known.map((n) => {
        const x = byNumber.get(n);
        if (!x) return null;
        if ('known' in x.state) return x.state.known === 'merged';
        return 'known' in x.column ? x.column.known === 'done' : null;
      });
      if (merged.every((m) => m === true)) return 'needs_you';
      if (!merged.includes(false)) return null;
    }
  }
  if (state === 'ready' || state === 'blocked') return 'waiting';
  return null;
}

const CYCLE = 'the plan\'s prerequisites form a cycle';
/**
 * Whether a ticket is positively verified merged: its known state first, else
 * its known column (done exactly when merged); `null` when neither is read.
 * The chain removes merged tickets whatever the display column says.
 */
const mergedNow = (t: Ticket): boolean | null => ('known' in t.state ? t.state.known === 'merged' : 'known' in t.column ? t.column.known === 'done' : null);
const finished = (t: Ticket): boolean => mergedNow(t) === true;
const before = (a: readonly number[], b: readonly number[]): boolean => {
  for (let i = 0; i < Math.min(a.length, b.length); i++) if (a[i] !== b[i]) return (a[i] ?? 0) < (b[i] ?? 0);
  return a.length < b.length;
};

/**
 * The contract's critical chain, from the whole plan: over unfinished tickets,
 * the root (every prerequisite merged) with the largest unfinished downstream
 * reach, then the longest onward path, then the smallest root; the path is a
 * longest onward path, numerically smallest on ties. `null` when nothing is
 * unfinished. `string` when it cannot be known: why.
 */
function chainOf(tickets: readonly Ticket[]): Chain | null | string {
  const byNumber = new Map(tickets.map((t) => [t.number, t]));
  const known = (f: Fact<number[]>): number[] | null => ('known' in f ? f.known : null);
  for (const t of tickets) {
    if (known(t.blockers) === null || known(t.dependents) === null) return 'a prerequisite list in this plan was not read';
    if (mergedNow(t) === null) return 'a ticket\'s merge state was not read';
    for (const b of known(t.blockers) ?? []) if (!byNumber.has(b)) return 'a referenced prerequisite was not read';
  }
  // Any cycle: no chain (contract: malformed).
  const mark = new Map<number, 1 | 2>();
  const cyclic = (n: number): boolean => {
    if (mark.get(n) === 2) return false;
    if (mark.get(n) === 1) return true;
    mark.set(n, 1);
    for (const b of known(byNumber.get(n)?.blockers ?? { unknown: '' }) ?? []) if (cyclic(b)) return true;
    mark.set(n, 2);
    return false;
  };
  for (const t of tickets) if (cyclic(t.number)) return CYCLE;
  const open = (n: number) => { const t = byNumber.get(n); return t !== undefined && !finished(t); };
  const onward = (n: number) => (known(byNumber.get(n)?.dependents ?? { unknown: '' }) ?? []).filter(open);
  const longest = new Map<number, number[]>();
  const pathFrom = (n: number): number[] => {
    const memo = longest.get(n);
    if (memo) return memo;
    let best: number[] = [];
    for (const d of onward(n)) {
      const p = pathFrom(d);
      if (p.length > best.length || (p.length === best.length && before(p, best))) best = p;
    }
    const out = [n, ...best];
    longest.set(n, out);
    return out;
  };
  const reach = (n: number): number => {
    const seen = new Set<number>();
    const todo = [n];
    for (let x = todo.pop(); x !== undefined; x = todo.pop()) for (const d of onward(x)) if (!seen.has(d)) { seen.add(d); todo.push(d); }
    return seen.size;
  };
  let pick: Chain | null = null;
  for (const t of tickets) {
    if (finished(t) || !(known(t.blockers) ?? []).every((b) => !open(b))) continue;
    const c = { root: t.number, blocked_count: reach(t.number), path: pathFrom(t.number) };
    if (!pick || c.blocked_count > pick.blocked_count || (c.blocked_count === pick.blocked_count && c.path.length > pick.path.length)) pick = c;
  }
  return pick;
}

/**
 * What the response can support, said honestly: complete dependents need every
 * prerequisite list read; a chain needs every list read, a real path and its
 * reach. Anything less becomes unknown, with its reason, never a guess.
 */
function settle(p: Plan): Plan {
  const tickets = p.tickets.some((t) => !('known' in t.blockers))
    ? p.tickets.map((t) => ('known' in t.dependents ? { ...t, dependents: { unknown: 'a prerequisite list in this plan was not read' } } : t))
    : p.tickets;
  const plan = { ...p, tickets };
  const c = p.critical_chain;
  if (!('known' in c)) return plan;
  // A named chain is kept only when it is exactly the chain this plan gives.
  const want = chainOf(tickets);
  if (want === CYCLE) {
    // The contract: a cycle is an unknown chain and a malformed gap, so the read is partial.
    const gaps = [...plan.coverage.gaps, { kind: 'malformed' as const, detail: want }];
    return { ...plan, coverage: { state: 'partial', gaps }, critical_chain: { unknown: want } };
  }
  if (typeof want === 'string') return { ...plan, critical_chain: { unknown: want } };
  const same = want === null ? c.known === null : c.known !== null && c.known.root === want.root && c.known.blocked_count === want.blocked_count && c.known.path.join() === want.path.join();
  if (same) return plan;
  return { ...plan, critical_chain: { unknown: want === null ? 'a chain was named in a plan with nothing unfinished' : c.known === null ? 'the plan has unfinished tickets but named no chain' : 'the named chain is not this plan\'s largest blocking chain' } };
}

/** A `plan.v1` response, read exactly; or where and why it was refused. */
export function readPlan(json: unknown): { ok: true; plan: Plan } | { ok: false; why: string } {
  try {
    const o = exact(json, '$', ['schema', 'snapshot_at', 'coverage', 'freshness', 'lanes', 'tickets', 'critical_chain']);
    if (o.get('schema') !== PLAN_SCHEMA_ID) refuse('$.schema', `not ${PLAN_SCHEMA_ID}`);
    const plan: Plan = {
      schema: PLAN_SCHEMA_ID,
      snapshot_at: time(o.get('snapshot_at'), '$.snapshot_at'),
      coverage: coverage(o.get('coverage'), '$.coverage'),
      freshness: freshness(o.get('freshness'), '$.freshness'),
      lanes: items(o.get('lanes'), '$.lanes', lane),
      tickets: items(o.get('tickets'), '$.tickets', ticket),
      critical_chain: fact(nullable(chain))(o.get('critical_chain'), '$.critical_chain'),
    };
    crossRecords(plan);
    return { ok: true, plan: settle(plan) };
  } catch (e) {
    if (e instanceof Refused) return { ok: false, why: e.message };
    throw e;
  }
}

/** A number the strict parse did not see written as a safe integer: no integer check accepts it. */
const NOT_AN_INTEGER = Object.freeze({ notAnInteger: true });

function plain(v: unknown): unknown {
  if (v instanceof Map) return Object.fromEntries([...v].map(([k, x]) => [k, plain(x)]));
  if (Array.isArray(v)) return v.map(plain);
  if (typeof v === 'object' && v !== null) {
    const n = new Map(Object.entries(v));
    return n.get('integer') === true ? n.get('value') : NOT_AN_INTEGER;
  }
  return v;
}

/** The response's text, parsed strictly and read exactly; or where and why it was refused. */
export function readPlanText(body: string): { ok: true; plan: Plan } | { ok: false; why: string } {
  let json: unknown;
  try {
    json = plain(parseJson(body));
  } catch (e) {
    if (e instanceof RangeError) return { ok: false, why: 'not strict JSON: nested too deep' };
    if (e instanceof Error) return { ok: false, why: `not strict JSON: ${e.message}` };
    throw e;
  }
  return readPlan(json);
}

// ── what the page shows ──

export const COLUMN_ORDER: readonly Column[] = ['done', 'building', 'needs_you', 'waiting'];
export const COLUMN_WORDS: Readonly<Record<Column, string>> = { done: 'done', building: 'building', needs_you: 'needs you', waiting: 'waiting' };
export const COLUMN_TITLES: Readonly<Record<Column, string>> = { done: 'Done', building: 'Building', needs_you: 'Needs you', waiting: 'Waiting' };

/** A lane's key, as the page names it (`version:6`, `side_spec:2500`). */
export const laneKey = (l: LaneRef): string => `${l.kind}:${l.number}`;

/** A lane's name: the milestone's title, or "Side spec #N <title>". */
export function laneName(l: Lane): string {
  return l.kind === 'version' ? factText(l.title) : `Side spec #${l.number} ${factText(l.title)}`;
}

/** The ticket's title as read, or its unknown reason. */
export const titleOf = (t: Ticket): string => factText(t.title);

/** Where a ticket is shown: its lane, outside this plan (a positively unparented prerequisite), or a lane that could not be read. */
export type Place = { kind: 'lane'; key: string } | { kind: 'outside' } | { kind: 'unknown'; why: string };
export function placeOf(t: Ticket): Place {
  if (!('known' in t.lane)) return { kind: 'unknown', why: t.lane.unknown };
  return t.lane.known === null ? { kind: 'outside' } : { kind: 'lane', key: laneKey(t.lane.known) };
}

export type Counts = Record<Column, number> & { unknown: number; yours: number; ownerUnknown: number; total: number };

/** One group of tickets: a lane, or the two groups no version counts. */
export type Group = { key: string; name: string; lane: Lane | null; tickets: Ticket[]; counts: Counts; why: string | null };

function count(tickets: readonly Ticket[]): Counts {
  const c: Counts = { done: 0, building: 0, needs_you: 0, waiting: 0, unknown: 0, yours: 0, ownerUnknown: 0, total: tickets.length };
  for (const t of tickets) {
    if ('known' in t.column) c[t.column.known]++;
    else c.unknown++;
    if (!('known' in t.yours)) c.ownerUnknown++;
    else if (t.yours.known) c.yours++;
  }
  return c;
}

/**
 * Every lane in the contract's order with its tickets in number order, then
 * "Outside this plan" and "Version unknown" when they have any. A lane with
 * no tickets is kept.
 */
export function groups(p: Plan): Group[] {
  const byLane = new Map<string, Ticket[]>(p.lanes.map((l) => [laneKey(l), []]));
  const outside: Ticket[] = [];
  const unknown: Ticket[] = [];
  for (const t of p.tickets) {
    const place = placeOf(t);
    if (place.kind === 'lane') byLane.get(place.key)?.push(t);
    else if (place.kind === 'outside') outside.push(t);
    else unknown.push(t);
  }
  const out: Group[] = p.lanes.map((l) => {
    const tickets = byLane.get(laneKey(l)) ?? [];
    return { key: laneKey(l), name: laneName(l), lane: l, tickets, counts: count(tickets), why: null };
  });
  if (outside.length > 0) out.push({ key: 'outside', name: 'Outside this plan', lane: null, tickets: outside, counts: count(outside), why: 'prerequisites with no spec in this plan' });
  if (unknown.length > 0) out.push({ key: 'unknown', name: 'Version unknown', lane: null, tickets: unknown, counts: count(unknown), why: 'their spec or version could not be read' });
  return out;
}

/** A group's tickets in one state column (`null`: the column is unknown). */
export function inColumn(g: Group, column: Column | null): Ticket[] {
  return g.tickets.filter((t) => ('known' in t.column ? t.column.known === column : column === null));
}

/** "4 done · 0 building · 1 needs you · 5 waiting", with unknown only when there is one. */
export function countWords(c: Counts): string[] {
  const words = COLUMN_ORDER.map((k) => `${c[k]} ${COLUMN_WORDS[k]}`);
  if (c.unknown > 0) words.push(`${c.unknown} unknown`);
  return words;
}
export function yoursWords(c: Counts): string {
  return `${c.yours} yours${c.ownerUnknown > 0 ? ` · ${c.ownerUnknown} owner unknown` : ''}`;
}

/** Lanes, versions and side specs, as the title row counts them. */
export function summary(p: Plan): string {
  const versions = p.lanes.filter((l) => l.kind === 'version').length;
  const side = p.lanes.length - versions;
  const n = (k: number, one: string, many: string) => `${k} ${k === 1 ? one : many}`;
  return [n(p.tickets.length, 'ticket', 'tickets'), n(versions, 'version', 'versions'), n(side, 'side spec', 'side specs')].join(' · ');
}

/** Trace: one ticket's direct prerequisites and dependents, from the whole plan; `missing`, numbers named but not read. */
export type Neighbours = { tickets: Ticket[]; missing: number[] };
export type Trace = { ticket: Ticket; waitsOn: Fact<Neighbours>; waitedOnBy: Fact<Neighbours> };
export function traceOf(p: Plan, n: number): Trace | null {
  const byNumber = new Map(p.tickets.map((t) => [t.number, t]));
  const t = byNumber.get(n);
  if (!t) return null;
  const pick = (list: Fact<number[]>): Fact<Neighbours> => ('known' in list
    ? { known: { tickets: list.known.flatMap((k) => byNumber.get(k) ?? []), missing: list.known.filter((k) => !byNumber.has(k)) } }
    : list);
  return { ticket: t, waitsOn: pick(t.blockers), waitedOnBy: pick(t.dependents) };
}

/** A ticket's relation to the traced one, in words: "selected", "prerequisite" or "waits on #N". */
export type Relation = 'selected' | 'prerequisite' | 'dependent' | null;
const has = (f: Fact<Neighbours>, t: Ticket) => 'known' in f && f.known.tickets.includes(t);
export function relationTo(trace: Trace | null, t: Ticket): Relation {
  if (!trace) return null;
  if (trace.ticket.number === t.number) return 'selected';
  if (has(trace.waitsOn, t)) return 'prerequisite';
  if (has(trace.waitedOnBy, t)) return 'dependent';
  return null;
}
export function relationWords(trace: Trace, r: Relation): string | null {
  return r === 'selected' ? 'selected' : r === 'prerequisite' ? 'prerequisite' : r === 'dependent' ? `waits on #${trace.ticket.number}` : null;
}

/** The trace's neighbours in one group, for a folded or filtered-out group's quiet tag. */
export function neighboursIn(trace: Trace, g: Group): { prerequisites: number; dependents: number } {
  const inGroup = (f: Fact<Neighbours>) => ('known' in f ? f.known.tickets.filter((t) => g.tickets.includes(t)).length : 0);
  return { prerequisites: inGroup(trace.waitsOn), dependents: inGroup(trace.waitedOnBy) };
}

/** "waits on 2 · 5 wait on it", with unknown said as unknown. */
export function traceCounts(trace: Trace): string {
  const size = (f: Neighbours) => f.tickets.length + f.missing.length;
  const before = 'known' in trace.waitsOn ? `waits on ${size(trace.waitsOn.known)}` : 'what it waits on is unknown';
  const n = 'known' in trace.waitedOnBy ? size(trace.waitedOnBy.known) : 0;
  const after = 'known' in trace.waitedOnBy ? `${n} ${n === 1 ? 'waits' : 'wait'} on it` : 'what waits on it is unknown';
  return `${before} · ${after}`;
}

/** The ticket's state word; an unknown column says so with its reason. */
export function stateWord(t: Ticket): string {
  return 'known' in t.column ? COLUMN_WORDS[t.column.known] : `unknown (${t.column.unknown})`;
}

/** The ticket's GitHub issue link, only as read and checked. */
export const issueLink = (t: Ticket): string | null => ('known' in t.url ? t.url.known : null);
export const prLink = (t: Ticket): PullRequest | null => ('known' in t.pr ? t.pr.known : null);

// ── freshness and the provenance chip ──

export type Provenance = { state: 'complete' | 'partial' | 'stale' | 'unknown'; partial: boolean; words: string };

/**
 * "Complete · read 09:00:14", "Partial · read … · N gaps", "Stale · read …",
 * "Stale · Partial · read … · N gaps"; freshness unknown said so. Coverage and
 * freshness are independent: a partial read stays partial (dashed) however old. Never gold.
 */
export function provenance(p: Plan, received: Received, now: Clock, clock: (ms: number) => string): Provenance {
  const fresh = freshNow(p.freshness, p.snapshot_at, received, now);
  const partial = p.coverage.state === 'partial';
  const read = p.freshness.state === 'unknown' ? `read time unknown (${p.freshness.snapshot_at.unknown})` : `read ${clock(p.freshness.snapshot_at.known)}`;
  const gaps = p.coverage.gaps.length;
  const gapWords = partial ? [`${gaps} ${gaps === 1 ? 'gap' : 'gaps'}`] : [];
  const state = p.freshness.state === 'unknown' ? 'unknown' : !fresh ? 'stale' : partial ? 'partial' : 'complete';
  const lead = state === 'unknown' ? ['Freshness unknown'] : state === 'stale' ? ['Stale'] : [];
  const cover = partial ? ['Partial'] : state === 'complete' ? ['Complete'] : [];
  return { state, partial, words: [...lead, ...cover, read, ...gapWords].join(' · ') };
}

/** The plan's empty-state words: "No plan yet" only when complete and fresh now. */
export function emptyWords(p: Plan, received: Received, now: Clock): string | null {
  if (p.lanes.length > 0 || p.tickets.length > 0) return null;
  if (p.coverage.state === 'partial') return 'No tickets read: this read is partial, so the plan may not be empty';
  if (p.freshness.state === 'unknown') return 'No tickets read: when this was read is unknown';
  if (!freshNow(p.freshness, p.snapshot_at, received, now)) return 'No tickets read: this read is stale';
  return 'No plan yet';
}

/** The chain's tickets, in root-to-downstream order. */
export function chainTickets(p: Plan, c: Chain): Ticket[] {
  const byNumber = new Map(p.tickets.map((t) => [t.number, t]));
  return c.path.flatMap((n) => byNumber.get(n) ?? []);
}
