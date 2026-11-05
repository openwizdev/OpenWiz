// Page 1 of the cockpit (0.0.10 T3, #536): `GET /api/v1/cockpit`, read as
// contracts/cockpit.v1.md says, and what the page may show and do with it.
//
// - **Read exactly.** Every object only with exactly its keys; enums only as
//   their strings; integers only as safe nonnegative integers, written as
//   integers; facts only as `{known}` or `{unknown: nonempty}`. The text is
//   parsed strictly (src/fleets.ts's `parseJson`), so a key written twice or
//   an integer written `1.0` is refused, as the contract's wire reader must.
// - **Order is the server's.** Needs you comes oldest first and the agents
//   in the contract's order; nothing here re-orders. Filters only narrow.
// - **Empty means empty** only when `projects` and `needs_you` are both
//   complete and fresh, and still fresh on this clock (CK5).
// - **An answer is one send** through the composer's send path (src/composer.ts),
//   with the item's own words, to its project's verified orchestrator, and
//   only when the project, the exact wording, the risk and a fresh target are
//   known (CK2). Nothing here sends: the page's owner presses.

import { readStock } from './readyStock.ts';
import type { Stock } from './readyStock.ts';
import type { Failure } from './api.ts';
import type { FactString, Fact, Unknown } from './envelope.ts';
import { parseJson } from './fleets.ts';
import { factText } from './present.ts';
import { FLEET_TIMING } from './timing.ts';
import type { StorageLike } from './composer.ts';

export const COCKPIT_SCHEMA_ID = 'openwiz.cockpit.v1';

// ── the shapes (contracts/cockpit.v1.schema.json) ──

export type GapKind = 'untested_version' | 'command_failed' | 'timed_out' | 'budget_exhausted' | 'malformed' | 'missing_field' | 'wrong_type' | 'not_found' | 'truncated' | 'unsupported';
export type CockpitGap = { project: string | null; kind: GapKind; detail: string };
export type Coverage = { state: 'complete' | 'partial'; gaps: CockpitGap[] };
export type Freshness = { state: 'fresh' | 'stale'; snapshot_at: { known: number } } | { state: 'unknown'; snapshot_at: Unknown };
export type Orchestrator = { coverage: Coverage; freshness: Freshness; target: Fact<string | null> };
export type Project = { id: string; name: FactString; orchestrator: Orchestrator };
export type NeedKind = 'needs_info' | 'held' | 'live' | 'release' | 'publish';
export type Need = { project: FactString; kind: NeedKind; spec: number; ticket: number; wording: FactString; age_ms: Fact<number>; risky: Fact<boolean> };
export type AgentState = 'merged' | 'ready' | 'building' | 'in_review' | 'changes_requested' | 'held' | 'blocked';
export type AgentLocation = { kind: 'cloud' } | { kind: 'local'; machine: FactString };
export type Agent = {
  thread: string;
  project: FactString;
  title: FactString;
  fleet: Fact<number>;
  ticket: Fact<number>;
  activity: 'active';
  model: FactString;
  state: Fact<AgentState>;
  location: Fact<AgentLocation>;
  started_at: Fact<number>;
};
export type Part<T> = { coverage: Coverage; freshness: Freshness; items: T[] };
export type Cockpit = { schema: typeof COCKPIT_SCHEMA_ID; snapshot_at: number; projects: Part<Project>; needs_you: Part<Need>; agents: Part<Agent>; ready_stock?: Stock };

// ── the reader ──

const GAP_KINDS: readonly GapKind[] = ['untested_version', 'command_failed', 'timed_out', 'budget_exhausted', 'malformed', 'missing_field', 'wrong_type', 'not_found', 'truncated', 'unsupported'];
const NEED_KINDS: readonly NeedKind[] = ['needs_info', 'held', 'live', 'release', 'publish'];
const RISKY_KINDS: readonly NeedKind[] = ['live', 'release', 'publish'];
const AGENT_STATES: readonly AgentState[] = ['merged', 'ready', 'building', 'in_review', 'changes_requested', 'held', 'blocked'];

class Refused extends Error {}
type Obj = Map<string, unknown>;

const refuse = (at: string, why: string): never => {
  throw new Refused(`${at}: ${why}`);
};

/** An object with exactly `keys`, as a map (no prototype lookups). */
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
const factString = fact(text);

function gap(v: unknown, at: string): CockpitGap {
  const o = exact(v, at, ['project', 'kind', 'detail']);
  const project = o.get('project');
  return { project: project === null ? null : text(project, `${at}.project`), kind: oneOf(GAP_KINDS)(o.get('kind'), `${at}.kind`), detail: text(o.get('detail'), `${at}.detail`) };
}
function coverage(v: unknown, at: string): Coverage {
  const o = exact(v, at, ['state', 'gaps']);
  const state = oneOf(['complete', 'partial'] as const)(o.get('state'), `${at}.state`);
  const gaps = items(o.get('gaps'), `${at}.gaps`, gap);
  if (state === 'complete' && gaps.length > 0) refuse(at, 'complete with gaps');
  return { state, gaps };
}
function freshness(v: unknown, at: string): Freshness {
  const o = exact(v, at, ['state', 'snapshot_at']);
  const state = oneOf(['fresh', 'stale', 'unknown'] as const)(o.get('state'), `${at}.state`);
  const snap = fact(time)(o.get('snapshot_at'), `${at}.snapshot_at`);
  if (state === 'unknown') return 'unknown' in snap ? { state, snapshot_at: snap } : refuse(at, 'unknown freshness with a known time');
  return 'known' in snap ? { state, snapshot_at: snap } : refuse(at, `${state} without a known time`);
}
function target(v: unknown, at: string): Fact<string | null> {
  return fact((x, a) => (x === null ? null : text(x, a)))(v, at);
}
function orchestrator(v: unknown, at: string): Orchestrator {
  const o = exact(v, at, ['coverage', 'freshness', 'target']);
  return { coverage: coverage(o.get('coverage'), `${at}.coverage`), freshness: freshness(o.get('freshness'), `${at}.freshness`), target: target(o.get('target'), `${at}.target`) };
}
function project(v: unknown, at: string): Project {
  const o = exact(v, at, ['id', 'name', 'orchestrator']);
  return { id: text(o.get('id'), `${at}.id`), name: factString(o.get('name'), `${at}.name`), orchestrator: orchestrator(o.get('orchestrator'), `${at}.orchestrator`) };
}
function need(v: unknown, at: string): Need {
  const o = exact(v, at, ['project', 'kind', 'spec', 'ticket', 'wording', 'age_ms', 'risky']);
  const n: Need = {
    project: factString(o.get('project'), `${at}.project`),
    kind: oneOf(NEED_KINDS)(o.get('kind'), `${at}.kind`),
    spec: issue(o.get('spec'), `${at}.spec`),
    ticket: issue(o.get('ticket'), `${at}.ticket`),
    wording: factString(o.get('wording'), `${at}.wording`),
    age_ms: fact(time)(o.get('age_ms'), `${at}.age_ms`),
    risky: fact((x, a) => (typeof x === 'boolean' ? x : refuse(a, 'not a boolean')))(o.get('risky'), `${at}.risky`),
  };
  if (RISKY_KINDS.includes(n.kind) && !('known' in n.risky && n.risky.known)) refuse(`${at}.risky`, `a ${n.kind} item is always risky`);
  return n;
}
function location(v: unknown, at: string): AgentLocation {
  const kind = typeof v === 'object' && v !== null && !Array.isArray(v) ? new Map(Object.entries(v)).get('kind') : undefined;
  if (kind === 'cloud') {
    exact(v, at, ['kind']);
    return { kind };
  }
  const o = exact(v, at, ['kind', 'machine']);
  if (o.get('kind') !== 'local') refuse(`${at}.kind`, 'not cloud or local');
  return { kind: 'local', machine: factString(o.get('machine'), `${at}.machine`) };
}
function agent(v: unknown, at: string): Agent {
  const o = exact(v, at, ['thread', 'project', 'title', 'fleet', 'ticket', 'activity', 'model', 'state', 'location', 'started_at']);
  return {
    thread: text(o.get('thread'), `${at}.thread`),
    project: factString(o.get('project'), `${at}.project`),
    title: factString(o.get('title'), `${at}.title`),
    fleet: fact(issue)(o.get('fleet'), `${at}.fleet`),
    ticket: fact(issue)(o.get('ticket'), `${at}.ticket`),
    activity: oneOf(['active'] as const)(o.get('activity'), `${at}.activity`),
    model: factString(o.get('model'), `${at}.model`),
    state: fact(oneOf(AGENT_STATES))(o.get('state'), `${at}.state`),
    location: fact(location)(o.get('location'), `${at}.location`),
    started_at: fact(time)(o.get('started_at'), `${at}.started_at`),
  };
}
function part<T>(v: unknown, at: string, read: (x: unknown, at: string) => T): Part<T> {
  const o = exact(v, at, ['coverage', 'freshness', 'items']);
  return { coverage: coverage(o.get('coverage'), `${at}.coverage`), freshness: freshness(o.get('freshness'), `${at}.freshness`), items: items(o.get('items'), `${at}.items`, read) };
}

/** -1, 0 or 1, for the contract's order: known values first, ascending; unknowns last. */
function cmpKnown<T extends string | number>(a: T | null, b: T | null): number {
  if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
  return a < b ? -1 : a > b ? 1 : 0;
}
const knownOf = <T>(f: Fact<T>): T | null => ('known' in f ? f.known : null);

/** Needs you's order: oldest known age first, unknown ages after; then project (unassigned last), spec, ticket, kind. */
function needOrder(a: Need, b: Need): number {
  const [x, y] = [knownOf(a.age_ms), knownOf(b.age_ms)];
  const age = x === null || y === null ? cmpKnown(x === null ? null : -x, y === null ? null : -y) : y - x;
  return age || cmpKnown(knownOf(a.project), knownOf(b.project)) || a.spec - b.spec || a.ticket - b.ticket || cmpKnown(a.kind, b.kind);
}
/** The grid's order: project, fleet, ticket (unknowns last), then thread id. */
function agentOrder(a: Agent, b: Agent): number {
  return cmpKnown(knownOf(a.project), knownOf(b.project)) || cmpKnown(knownOf(a.fleet), knownOf(b.fleet)) || cmpKnown(knownOf(a.ticket), knownOf(b.ticket)) || cmpKnown(a.thread, b.thread);
}

/**
 * The contract's cross-record rules a strict consumer checks (cockpit.v1.md,
 * "Schema and cross-record checks"): unique keys, project references that
 * resolve, gaps for every partial part, snapshots and starts not after
 * assembly, freshness as the 70 s rule says, and the lists in the contract's
 * order (checked, never re-done).
 */
function crossRecords(c: Cockpit): void {
  const ids = new Set<string>();
  c.projects.items.forEach((p, i) => {
    if (ids.has(p.id)) refuse('$.projects.items', `project ${p.id} twice`);
    const prev = c.projects.items[i - 1];
    if (prev && !(prev.id < p.id)) refuse(`$.projects.items[${i}]`, 'not in ascending id order');
    ids.add(p.id);
  });
  const resolves = (f: FactString, at: string) => {
    if ('known' in f && !ids.has(f.known)) refuse(at, `project ${f.known} is not in projects`);
  };
  const parts: [string, Coverage, Freshness][] = [
    ['$.projects', c.projects.coverage, c.projects.freshness],
    ['$.needs_you', c.needs_you.coverage, c.needs_you.freshness],
    ['$.agents', c.agents.coverage, c.agents.freshness],
    ...c.projects.items.map((p, i): [string, Coverage, Freshness] => [`$.projects.items[${i}].orchestrator`, p.orchestrator.coverage, p.orchestrator.freshness]),
  ];
  for (const [at, cov, f] of parts) {
    if (cov.state === 'partial' && cov.gaps.length === 0) refuse(`${at}.coverage`, 'partial without a gap');
    cov.gaps.forEach((g, i) => {
      if (g.project !== null && !ids.has(g.project)) refuse(`${at}.coverage.gaps[${i}].project`, `project ${g.project} is not in projects`);
    });
    if (f.state === 'unknown') continue;
    const age = c.snapshot_at - f.snapshot_at.known;
    if (age < 0) refuse(`${at}.freshness`, 'a snapshot after assembly');
    if ((f.state === 'fresh') !== age <= FLEET_TIMING.staleAfterMs) refuse(`${at}.freshness`, `${f.state} does not match its age`);
  }
  const keys = new Set<string>();
  c.needs_you.items.forEach((n, i) => {
    resolves(n.project, `$.needs_you.items[${i}].project`);
    const key = needKey(n);
    if (key !== null && keys.has(key)) refuse(`$.needs_you.items[${i}]`, 'an item twice');
    if (key !== null) keys.add(key);
    const prev = c.needs_you.items[i - 1];
    if (prev && needOrder(prev, n) > 0) refuse(`$.needs_you.items[${i}]`, 'not in the contract\'s order');
  });
  const threads = new Set<string>();
  const startBound = c.agents.freshness.state === 'unknown' ? c.snapshot_at : c.agents.freshness.snapshot_at.known;
  c.agents.items.forEach((a, i) => {
    resolves(a.project, `$.agents.items[${i}].project`);
    if (threads.has(a.thread)) refuse(`$.agents.items[${i}].thread`, `thread ${a.thread} twice`);
    threads.add(a.thread);
    if ('known' in a.started_at && a.started_at.known > startBound) refuse(`$.agents.items[${i}].started_at`, 'a start after its snapshot');
    const prev = c.agents.items[i - 1];
    if (prev && agentOrder(prev, a) > 0) refuse(`$.agents.items[${i}]`, 'not in the contract\'s order');
  });
}

/** A `cockpit.v1` response, read exactly; or where and why it was refused. */
export function readCockpit(json: unknown): { ok: true; cockpit: Cockpit } | { ok: false; why: string } {
  try {
    const hasStock = typeof json === 'object' && json !== null && Object.hasOwn(json, 'ready_stock');
    const o = exact(json, '$', ['schema', 'snapshot_at', 'projects', 'needs_you', 'agents', ...(hasStock ? ['ready_stock'] : [])]);
    if (o.get('schema') !== COCKPIT_SCHEMA_ID) refuse('$.schema', `not ${COCKPIT_SCHEMA_ID}`);
    const cockpit: Cockpit = {
      schema: COCKPIT_SCHEMA_ID,
      snapshot_at: time(o.get('snapshot_at'), '$.snapshot_at'),
      projects: part(o.get('projects'), '$.projects', project),
      needs_you: part(o.get('needs_you'), '$.needs_you', need),
      agents: part(o.get('agents'), '$.agents', agent),
    };
    if (hasStock) {
      try { cockpit.ready_stock = readStock(o.get('ready_stock'), cockpit.snapshot_at, cockpit.projects.items.map((p) => p.id)); }
      catch { refuse('$.ready_stock', 'invalid stock projection'); }
    }
    crossRecords(cockpit);
    return { ok: true, cockpit };
  } catch (e) {
    if (e instanceof Refused) return { ok: false, why: e.message };
    throw e;
  }
}

export type CockpitOutcome = { kind: 'ok'; envelope: Cockpit } | Failure;

/** A number the strict parse did not see written as a safe integer: no integer check accepts it. */
const NOT_AN_INTEGER = Object.freeze({ notAnInteger: true });

/** The strict parse's values as plain ones: its maps as objects, and only exact integers as numbers. */
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
export function readCockpitText(text: string): { ok: true; cockpit: Cockpit } | { ok: false; why: string } {
  let json: unknown;
  try {
    json = plain(parseJson(text));
  } catch (e) {
    if (e instanceof Error) return { ok: false, why: `not strict JSON: ${e.message}` };
    throw e;
  }
  return readCockpit(json);
}

// ── freshness on this clock ──

/** When the page received the response: the page's monotonic and wall clocks. */
export type Received = { mono: number; wall: number };
export type Clock = { mono: number; wall: number };

/**
 * Whether a part is fresh now: the server said fresh, and its source age at
 * assembly plus the time since receipt (the longer of the two clocks, as
 * src/viewer.ts's `isStale`: `performance.now()` can pause while a device
 * sleeps, and the wall clock can be set back) is still within the fleet
 * page's 70 seconds.
 */
export function freshNow(f: Freshness, assembledAt: number, received: Received, now: Clock): boolean {
  if (f.state !== 'fresh') return false;
  const atAssembly = Math.max(0, assembledAt - f.snapshot_at.known);
  const since = Math.max(0, now.mono - received.mono, now.wall - received.wall);
  return atAssembly + since <= FLEET_TIMING.staleAfterMs;
}

/** When a fresh part turns stale on this clock (ms from now), or null when it already is. */
export function staleInMs(f: Freshness, assembledAt: number, received: Received, now: Clock): number | null {
  if (!freshNow(f, assembledAt, received, now)) return null;
  const atAssembly = Math.max(0, assembledAt - (f.state === 'fresh' ? f.snapshot_at.known : 0));
  const since = Math.max(0, now.mono - received.mono, now.wall - received.wall);
  return FLEET_TIMING.staleAfterMs - atAssembly - since + 1;
}

/** CK5: "Nothing needs you" only when both parts are complete and fresh now, and the list is empty. */
export function nothingNeedsYou(c: Cockpit, received: Received, now: Clock): boolean {
  return (
    c.needs_you.items.length === 0 &&
    c.projects.coverage.state === 'complete' &&
    c.needs_you.coverage.state === 'complete' &&
    freshNow(c.projects.freshness, c.snapshot_at, received, now) &&
    freshNow(c.needs_you.freshness, c.snapshot_at, received, now)
  );
}

// ── Needs you: what an item may do ──

/** An item's identity: its known project, spec, ticket and kind (the contract's key), or null when unassigned. */
export function needKey(n: Need): string | null {
  return 'known' in n.project ? JSON.stringify([n.project.known, n.spec, n.ticket, n.kind]) : null;
}

export type Actionable = { ok: true; target: string; wording: string; risky: boolean; binding: string } | { ok: false; why: string };

export const NO_TARGET = 'answer unavailable: orchestrator not configured or not found';

/**
 * Everything the owner sees of an item that an answer binds to: project,
 * spec, ticket, kind, wording, risk and target. Null while any of them is
 * unknown. A different binding is a different item: nothing made on one is
 * ever sent for another.
 */
export function bindingOf(c: Cockpit, n: Need): string | null {
  if (!('known' in n.project) || !('known' in n.wording) || !('known' in n.risky)) return null;
  const projectId = n.project.known;
  const t = c.projects.items.find((x) => x.id === projectId)?.orchestrator.target;
  if (!t || !('known' in t) || t.known === null) return null;
  return JSON.stringify([projectId, n.spec, n.ticket, n.kind, n.wording.known, n.risky.known, t.known]);
}

/**
 * Whether Yes and No may be offered for `n`, and to which thread: only with
 * its project, exact wording and risk known, the list fresh, and its own
 * project's target verified (its check complete) and fresh.
 */
export function actionable(c: Cockpit, n: Need, received: Received, now: Clock): Actionable {
  if (!('known' in n.project)) return { ok: false, why: `project unknown (${n.project.unknown}); not assigned, so nothing can be answered here` };
  const projectId = n.project.known;
  const p = c.projects.items.find((x) => x.id === projectId);
  if (!p) return { ok: false, why: 'its project is not in this read; nothing can be answered here' };
  // No guessed link (cockpit.v1 has no repository URL; ops decision on #536): honest words and the issue number.
  if (!('known' in n.wording)) return { ok: false, why: `Yes and y need the exact proposal, which isn’t readable here yet: answer #${n.ticket} on GitHub` };
  if (!('known' in n.risky)) return { ok: false, why: `Yes and y need to know whether it is risky, which isn’t reported here yet: answer #${n.ticket} on GitHub` };
  if (!freshNow(c.needs_you.freshness, c.snapshot_at, received, now)) return { ok: false, why: 'answer unavailable: this list is not fresh; refresh it' };
  const t = p.orchestrator.target;
  if (!('known' in t) || t.known === null || p.orchestrator.coverage.state !== 'complete') return { ok: false, why: NO_TARGET };
  if (!freshNow(p.orchestrator.freshness, c.snapshot_at, received, now)) return { ok: false, why: 'answer unavailable: the orchestrator check is not fresh; refresh it' };
  const binding = bindingOf(c, n);
  return binding === null ? { ok: false, why: NO_TARGET } : { ok: true, target: t.known, wording: n.wording.known, risky: n.risky.known, binding };
}

/**
 * A request to open an item's answer, as pressing Yes or No would (#537's
 * `y` and `approve` seam): `key` is `needKey`, `seq` makes each request new.
 * It only opens the preview and confirm: the owner's press still sends.
 */
export type AnswerRequest = { key: string; choice: Choice; seq: number };

export type Choice = 'yes' | 'no';

/** The one message an answer sends: the item's own words and the owner's choice. */
export function answerText(n: Need, wording: string, choice: Choice): string {
  return `Answer for ticket #${n.ticket} (spec #${n.spec}, ${n.kind}): ${choice === 'yes' ? 'Yes' : 'No'}\n\nProposal: ${wording}`;
}

/** What a risky item's armed button says: the action, named. */
export function armedLabel(n: Need, choice: Choice): string {
  if (choice === 'no') return 'No: press again';
  return RISKY_KINDS.includes(n.kind) ? `Yes, ${n.kind} #${n.ticket}` : `Yes, risky #${n.ticket}`;
}

// ── an item's own composer storage ──

/**
 * Each item's answer keeps its own op id and attempts, apart from the
 * orchestrator's own message box: the composer's tab storage
 * (src/composer.ts's `browserStorage`), under the item's key.
 */
export function itemStorage(storage: StorageLike | null, key: string): StorageLike | null {
  if (storage === null) return null;
  const prefix = `openwiz.cockpit.${encodeURIComponent(key)}.`;
  return {
    getItem: (k) => storage.getItem(prefix + k),
    setItem: (k, v) => storage.setItem(prefix + k, v),
    removeItem: (k) => storage.removeItem(prefix + k),
  };
}

/**
 * An item's answer record, kept in its own storage before the send leaves
 * and until its result is known: the binding and target it was made for,
 * its text, and its phase. While a record is pending, or queued or sent for
 * the binding on screen, no new answer is offered; a record for another
 * binding never retries or replays.
 */
export type AnswerRecord = { binding: string; target: string; text: string; phase: 'pending' | 'queued' | 'sent' };

const RECORD = 'answer';

export function readRecord(storage: StorageLike | null): AnswerRecord | null {
  try {
    const raw = storage?.getItem(RECORD) ?? null;
    const v: unknown = raw === null ? null : JSON.parse(raw);
    if (typeof v !== 'object' || v === null || Array.isArray(v)) return null;
    const o = new Map(Object.entries(v));
    const [binding, target, t, phase] = [o.get('binding'), o.get('target'), o.get('text'), o.get('phase')];
    if (typeof binding !== 'string' || typeof target !== 'string' || typeof t !== 'string') return null;
    return phase === 'pending' || phase === 'queued' || phase === 'sent' ? { binding, target, text: t, phase } : null;
  } catch {
    return null;
  }
}

/** True only when it is stored: the send leaves only after this. */
export function writeRecord(storage: StorageLike | null, r: AnswerRecord): boolean {
  if (storage === null) return false;
  try {
    storage.setItem(RECORD, JSON.stringify(r));
    return readRecord(storage)?.phase === r.phase;
  } catch {
    return false;
  }
}

export function clearRecord(storage: StorageLike | null): void {
  try {
    storage?.removeItem(RECORD);
  } catch {
    // A record that can't be cleared stays: it keeps the item closed, never open.
  }
}

/** The owner's choice in a record's text. */
export function choiceOf(text: string): string {
  return /^Answer for ticket #\d+ \(spec #\d+, [a-z_]+\): (Yes|No)\n/.exec(text)?.[1] ?? 'an answer';
}

// ── filters and groups (narrowing only; never a re-order) ──

export type Filter = { project: string | null; machine: string | null };

/** A project filter keeps the project's items and every item whose project is unknown: they can't be excluded as though known. */
export function needsShown(c: Cockpit, f: Filter): Need[] {
  return c.needs_you.items.filter((n) => f.project === null || !('known' in n.project) || n.project.known === f.project);
}

/** The machines the inventory reported, in the order first seen. */
export function machines(c: Cockpit): string[] {
  const seen: string[] = [];
  for (const a of c.agents.items) {
    const l = a.location;
    if ('known' in l && l.known.kind === 'local' && 'known' in l.known.machine && !seen.includes(l.known.machine.known)) seen.push(l.known.machine.known);
  }
  return seen;
}

/** Whether an agent's machine is known not to be `machine`. Unknown machines stay in. */
function otherMachine(a: Agent, machine: string): boolean {
  const l = a.location;
  if (!('known' in l)) return false;
  if (l.known.kind === 'cloud') return true;
  return 'known' in l.known.machine && l.known.machine.known !== machine;
}

export function agentsShown(c: Cockpit, f: Filter): Agent[] {
  return c.agents.items.filter((a) => (f.project === null || !('known' in a.project) || a.project.known === f.project) && (f.machine === null || !otherMachine(a, f.machine)));
}

export type AgentGroup = { key: string; project: string | null; fleet: number | null; agents: Agent[] };

/**
 * The grid's groups: placed agents by project and fleet, in the order their
 * first row comes; every unplaced agent (no verified fleet) last, in one
 * "Not placed" group, never hidden.
 */
export function agentGroups(agents: readonly Agent[]): AgentGroup[] {
  const groups = new Map<string, AgentGroup>();
  const unplaced: Agent[] = [];
  for (const a of agents) {
    if (!('known' in a.fleet)) {
      unplaced.push(a);
      continue;
    }
    const project = 'known' in a.project ? a.project.known : null;
    const key = JSON.stringify([project, a.fleet.known]);
    const g = groups.get(key);
    if (g) g.agents.push(a);
    else groups.set(key, { key, project, fleet: a.fleet.known, agents: [a] });
  }
  return unplaced.length > 0 ? [...groups.values(), { key: 'unplaced', project: null, fleet: null, agents: unplaced }] : [...groups.values()];
}

/** Whether a Needs you item names this agent's ticket in its own project and fleet: the grid's gold marker. */
export function agentNeedsYou(c: Cockpit, a: Agent): boolean {
  if (!('known' in a.project) || !('known' in a.ticket) || !('known' in a.fleet)) return false;
  const [p, t, s] = [a.project.known, a.ticket.known, a.fleet.known];
  return c.needs_you.items.some((n) => 'known' in n.project && n.project.known === p && n.ticket === t && n.spec === s);
}

/** A project's name for headings: as reported, with its id's last 4 characters when another project shows the same name (G2). */
export function projectName(c: Cockpit, id: string): string {
  const p = c.projects.items.find((x) => x.id === id);
  if (!p) return id;
  const name = factText(p.name);
  const twins = c.projects.items.filter((x) => factText(x.name) === name).length;
  return twins > 1 ? `${name} ${id.slice(-4)}` : name;
}

/** Every gap of the response, once each, part by part. */
export function allGaps(c: Cockpit): { part: string; gap: CockpitGap }[] {
  const out: { part: string; gap: CockpitGap }[] = [];
  for (const [name, gaps] of [
    ['projects', c.projects.coverage.gaps],
    ['needs you', c.needs_you.coverage.gaps],
    ['agents', c.agents.coverage.gaps],
    ...c.projects.items.map((p) => [`orchestrator ${p.id}`, p.orchestrator.coverage.gaps] as const),
  ] as const) {
    for (const g of gaps) out.push({ part: name, gap: g });
  }
  return out;
}
