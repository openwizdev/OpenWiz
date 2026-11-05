// The loops page (#549): `GET /api/v1/loops`, read exactly as
// contracts/web-api.v1.md's "Loops view" says, the words each row shows, and
// the switch.
//
// - **Read exactly.** Every object with exactly its keys, enums only as their
//   strings, integers only as safe nonnegative integers written as integers.
//   The text is parsed strictly (src/fleets.ts's `parseJson`): a key written
//   twice or `1.0` is refused.
// - **Order is the server's:** problems first, then by name. Nothing here
//   re-orders; the page only splits the list where the problems end.
// - **The switch:** one owner's press is one `POST /api/v1/loops/{id}/on|off`
//   (#548), its answer shown as it is: saved, busy, refused, signed out or
//   unknown. Never retried, never sent from a refresh, an effect or a timer.

import { isLoopId, postLoopSwitch } from './api.ts';
import type { Answer, FetchLike } from './api.ts';
import { parseApiError } from './envelope.ts';
import { parseJson } from './fleets.ts';

export const LOOPS_SCHEMA_ID = 'openwiz.loops-view.v1';

// ── the shape (contracts/web-api.v1.md, "Loops view") ──

export type LoopEvent = 'github.pull_request_review' | 'github.workflow_run' | 'github.check_suite' | 'github.issue_comment';
export type Wake = { kind: 'interval'; every_ms: number; anchor_ms: number } | { kind: 'once'; at_ms: number } | { kind: 'event'; event: LoopEvent };
export type NextRun = { kind: 'at' | 'due'; at_ms: number } | { kind: 'event'; event: LoopEvent } | { kind: 'none'; why: 'off' | 'done' };
export type RunResult = 'checking' | 'quiet' | 'check_failed' | 'check_timed_out' | 'shadow' | 'deferred' | 'dispatching' | 'created' | 'not_created' | 'refused' | 'uncertain';
export type Problem = 'check_failed' | 'check_timed_out' | 'not_created' | 'refused' | 'uncertain';
export type LastRun = { started_at_ms: number; updated_at_ms: number; result: RunResult; reason: string | null };
export type Cost = { kind: 'known'; usd_micros: number } | { kind: 'unknown'; reason: string };
export type Loop = {
  id: string;
  name: string;
  owner: string;
  mode: 'shadow' | 'active';
  enabled: boolean;
  wake: Wake;
  next_run: NextRun;
  last_run: LastRun | null;
  cost: Cost;
  problem: Problem | null;
};
export type LoopsView = { schema: typeof LOOPS_SCHEMA_ID; read_at_ms: number; cost_window_ms: number; loops: Loop[] };

// ── the reader ──

const EVENTS: readonly LoopEvent[] = ['github.pull_request_review', 'github.workflow_run', 'github.check_suite', 'github.issue_comment'];
const RESULTS: readonly RunResult[] = ['checking', 'quiet', 'check_failed', 'check_timed_out', 'shadow', 'deferred', 'dispatching', 'created', 'not_created', 'refused', 'uncertain'];
const PROBLEMS: readonly Problem[] = ['check_failed', 'check_timed_out', 'not_created', 'refused', 'uncertain'];

class Refused extends Error {}
type Obj = Map<string, unknown>;
const refuse = (at: string, why: string): never => {
  throw new Refused(`${at}: ${why}`);
};
const kindOf = (v: unknown): unknown => (v instanceof Map ? v.get('kind') : undefined);
/** An object with exactly `keys`, as a map (no prototype lookups). */
function exact(v: unknown, at: string, keys: readonly string[]): Obj {
  if (!(v instanceof Map)) return refuse(at, 'not an object');
  const o: Obj = new Map([...v].map(([k, x]) => [String(k), x]));
  if (o.size !== keys.length || !keys.every((k) => o.has(k))) return refuse(at, `keys are not exactly ${keys.join(', ')}`);
  return o;
}
const text = (v: unknown, at: string): string => (typeof v === 'string' && v.trim() !== '' && !v.includes('\u0000') ? v : refuse(at, 'not a nonblank string without NUL'));
/** A strictly parsed integer: `{integer: true, value}` from `parseJson`. */
function whole(min: number) {
  return (v: unknown, at: string): number => {
    const n = typeof v === 'object' && v !== null && !(v instanceof Map) ? new Map(Object.entries(v)) : null;
    const value = n?.get('integer') === true ? n.get('value') : undefined;
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= min ? value : refuse(at, `not an integer of at least ${min}`);
  };
}
const time = whole(0);
const bool = (v: unknown, at: string): boolean => (typeof v === 'boolean' ? v : refuse(at, 'not true or false'));
function oneOf<T extends string>(list: readonly T[]) {
  return (v: unknown, at: string): T => list.find((x) => x === v) ?? refuse(at, `not one of ${list.join(', ')}`);
}

function wake(v: unknown, at: string): Wake {
  switch (kindOf(v)) {
    case 'interval': {
      const o = exact(v, at, ['kind', 'every_ms', 'anchor_ms']);
      return { kind: 'interval', every_ms: whole(1)(o.get('every_ms'), `${at}.every_ms`), anchor_ms: time(o.get('anchor_ms'), `${at}.anchor_ms`) };
    }
    case 'once':
      return { kind: 'once', at_ms: time(exact(v, at, ['kind', 'at_ms']).get('at_ms'), `${at}.at_ms`) };
    case 'event':
      return { kind: 'event', event: oneOf(EVENTS)(exact(v, at, ['kind', 'event']).get('event'), `${at}.event`) };
    default:
      return refuse(at, 'not a wake');
  }
}

function nextRun(v: unknown, at: string): NextRun {
  const kind = kindOf(v);
  if (kind === 'at' || kind === 'due') return { kind, at_ms: time(exact(v, at, ['kind', 'at_ms']).get('at_ms'), `${at}.at_ms`) };
  if (kind === 'event') return { kind, event: oneOf(EVENTS)(exact(v, at, ['kind', 'event']).get('event'), `${at}.event`) };
  if (kind === 'none') return { kind, why: oneOf(['off', 'done'] as const)(exact(v, at, ['kind', 'why']).get('why'), `${at}.why`) };
  return refuse(at, 'not a next run');
}

function lastRun(v: unknown, at: string): LastRun | null {
  if (v === null) return null;
  const o = exact(v, at, ['started_at_ms', 'updated_at_ms', 'result', 'reason']);
  const started = time(o.get('started_at_ms'), `${at}.started_at_ms`);
  const updated = time(o.get('updated_at_ms'), `${at}.updated_at_ms`);
  if (updated < started) refuse(`${at}.updated_at_ms`, 'before started_at_ms');
  const reason = o.get('reason');
  return { started_at_ms: started, updated_at_ms: updated, result: oneOf(RESULTS)(o.get('result'), `${at}.result`), reason: reason === null ? null : text(reason, `${at}.reason`) };
}

function cost(v: unknown, at: string): Cost {
  if (kindOf(v) === 'known') return { kind: 'known', usd_micros: time(exact(v, at, ['kind', 'usd_micros']).get('usd_micros'), `${at}.usd_micros`) };
  if (kindOf(v) === 'unknown') return { kind: 'unknown', reason: text(exact(v, at, ['kind', 'reason']).get('reason'), `${at}.reason`) };
  return refuse(at, 'not a cost');
}

const LOOP_KEYS = ['id', 'name', 'owner', 'mode', 'enabled', 'wake', 'next_run', 'last_run', 'cost', 'problem'] as const;

function loop(v: unknown, at: string): Loop {
  const o = exact(v, at, LOOP_KEYS);
  const id = text(o.get('id'), `${at}.id`);
  if (!isLoopId(id)) refuse(`${at}.id`, 'not a loop id');
  const last = lastRun(o.get('last_run'), `${at}.last_run`);
  const problem = o.get('problem') === null ? null : oneOf(PROBLEMS)(o.get('problem'), `${at}.problem`);
  // The contract's rule: the problem is the last run's result, when it is one.
  const expected = last !== null && PROBLEMS.some((p) => p === last.result) ? last.result : null;
  if (problem !== expected) refuse(`${at}.problem`, 'does not match the last run');
  const enabled = bool(o.get('enabled'), `${at}.enabled`);
  const next = nextRun(o.get('next_run'), `${at}.next_run`);
  const w = wake(o.get('wake'), `${at}.wake`);
  if ((next.kind === 'none' && next.why === 'off') !== !enabled) refuse(`${at}.next_run`, 'does not match the switch');
  // On, an event wake runs on its event; a timed wake has a time, or is done.
  if (enabled && (w.kind === 'event') !== (next.kind === 'event')) refuse(`${at}.next_run`, 'does not match the wake');
  if (next.kind === 'event' && w.kind === 'event' && next.event !== w.event) refuse(`${at}.next_run.event`, 'not the wake\'s event');
  if (next.kind === 'at' || next.kind === 'due') {
    if (w.kind === 'once' && next.at_ms !== w.at_ms) refuse(`${at}.next_run.at_ms`, 'not the wake\'s time');
    if (w.kind === 'interval' && (next.at_ms < w.anchor_ms || (next.at_ms - w.anchor_ms) % w.every_ms !== 0)) refuse(`${at}.next_run.at_ms`, 'not on the wake\'s schedule');
  }
  return {
    id,
    name: text(o.get('name'), `${at}.name`),
    owner: text(o.get('owner'), `${at}.owner`),
    mode: oneOf(['shadow', 'active'] as const)(o.get('mode'), `${at}.mode`),
    enabled,
    wake: w,
    next_run: next,
    last_run: last,
    cost: cost(o.get('cost'), `${at}.cost`),
    problem,
  };
}

/** Compares by Unicode code points, as the server orders names: negative, zero or positive. */
function codePoints(a: string, b: string): number {
  const x = [...a];
  const y = [...b];
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const d = (x[i]?.codePointAt(0) ?? 0) - (y[i]?.codePointAt(0) ?? 0);
    if (d !== 0) return d;
  }
  return x.length - y.length;
}

/** The response's text, parsed strictly and read exactly; or where and why it was refused. */
export function readLoopsText(body: string): { ok: true; view: LoopsView } | { ok: false; why: string } {
  try {
    const o = exact(parseJson(body), '$', ['schema', 'read_at_ms', 'cost_window_ms', 'loops']);
    if (o.get('schema') !== LOOPS_SCHEMA_ID) refuse('$.schema', `not ${LOOPS_SCHEMA_ID}`);
    const list = o.get('loops');
    if (!Array.isArray(list)) return refuse('$.loops', 'not a list');
    const loops = list.map((x, i) => loop(x, `$.loops[${i}]`));
    const ids = new Set(loops.map((l) => l.id));
    if (ids.size !== loops.length) refuse('$.loops', 'an id is listed twice');
    // Problems first, as the contract orders them; a problem after a healthy loop is refused.
    // The contract's order: problems first, then by name (code points), then id.
    loops.forEach((l, i) => {
      const before = loops[i - 1];
      if (before === undefined) return;
      const group = Number(before.problem === null) - Number(l.problem === null);
      const order = group !== 0 ? group : codePoints(before.name, l.name) || codePoints(before.id, l.id);
      if (order >= 0) refuse(`$.loops[${i}]`, 'not in the contract\'s order');
    });
    const readAt = time(o.get('read_at_ms'), '$.read_at_ms');
    loops.forEach((l, i) => {
      const n = l.next_run;
      if ((n.kind === 'at' && n.at_ms <= readAt) || (n.kind === 'due' && n.at_ms > readAt)) refuse(`$.loops[${i}].next_run`, 'not classified by the read time');
    });
    const window = whole(1)(o.get('cost_window_ms'), '$.cost_window_ms');
    if (window !== DAY_MS) refuse('$.cost_window_ms', 'not 24 hours');
    return { ok: true, view: { schema: LOOPS_SCHEMA_ID, read_at_ms: readAt, cost_window_ms: window, loops } };
  } catch (e) {
    if (e instanceof Error) return { ok: false, why: e.message };
    throw e;
  }
}

// ── what a row says ──

const two = (n: number) => String(n).padStart(2, '0');
/** Device-local `HH:MM`; "tomorrow HH:MM"; else the date. */
export function whenText(epochMs: number, now: Date): string {
  const d = new Date(epochMs);
  const hm = `${two(d.getHours())}:${two(d.getMinutes())}`;
  if (d.toDateString() === now.toDateString()) return hm;
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (d.toDateString() === tomorrow.toDateString()) return `tomorrow ${hm}`;
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} ${hm}`;
}

const EVENT_WORDS: Record<LoopEvent, string> = {
  'github.pull_request_review': 'on review posted',
  'github.workflow_run': 'on CI run',
  'github.check_suite': 'on checks finished',
  'github.issue_comment': 'on comment',
};

const DAY_MS = 86_400_000;
function periodText(ms: number): string {
  for (const [unit, size] of [['d', DAY_MS], ['h', 3_600_000], ['min', 60_000], ['s', 1_000]] as const) {
    if (ms % size === 0) return `${ms / size} ${unit}`;
  }
  return `${ms} ms`;
}

/** What wakes it: "every 10 min", "daily 02:00", "once, tomorrow 17:00", "on review posted". */
export function cadenceText(w: Wake, now: Date): string {
  switch (w.kind) {
    case 'interval':
      if (w.every_ms === DAY_MS) {
        const d = new Date(w.anchor_ms);
        return `daily ${two(d.getHours())}:${two(d.getMinutes())}`;
      }
      return `every ${periodText(w.every_ms)}`;
    case 'once':
      return `once, ${whenText(w.at_ms, now)}`;
    case 'event':
      return EVENT_WORDS[w.event];
  }
}

/** The next run, or null when the cadence already says it (an event wake). */
export function nextText(n: NextRun, now: Date): string | null {
  switch (n.kind) {
    case 'at':
      return `next ${whenText(n.at_ms, now)}`;
    case 'due':
      return `due since ${whenText(n.at_ms, now)}`;
    case 'event':
      return null;
    case 'none':
      return n.why === 'off' ? 'off: no next run' : 'done';
  }
}

const RESULT_WORDS: Record<RunResult, string> = {
  checking: 'checking now',
  quiet: 'nothing to do',
  check_failed: 'check failed',
  check_timed_out: 'check timed out',
  shadow: 'found work (shadow: no agent)',
  deferred: 'found work, waiting to create an agent thread',
  dispatching: 'creating an agent thread',
  created: 'agent thread created',
  not_created: 'agent thread not created',
  refused: 'refused before creating an agent thread',
  uncertain: 'agent thread creation unsure (not confirmed)',
};

export function lastText(l: LastRun | null, now: Date): string {
  return l === null ? 'not run yet' : `last run ${whenText(l.started_at_ms, now)}: ${RESULT_WORDS[l.result]}`;
}

/** "$0.42 in 24 h", "<$0.01 in 24 h", "cost unknown". */
export function costText(c: Cost, windowMs: number): string {
  if (c.kind === 'unknown') return 'cost unknown';
  const window = windowMs === DAY_MS ? 'in 24 h' : `in ${periodText(windowMs)}`;
  if (c.usd_micros > 0 && c.usd_micros < 10_000) return `<$0.01 ${window}`;
  return `$${(c.usd_micros / 1_000_000).toFixed(2)} ${window}`;
}

// ── the switch ──

/** The server waits up to 30 s for a running pass before `switch_busy`; this leaves room for that answer. */
export const SWITCH_TIMEOUT_MS = 45_000;

/** What one press of a loop's switch came to. */
export type Switched =
  /** The request is out; the switch takes no other press until it is answered. */
  | { kind: 'sending'; on: boolean }
  /** The server saved it: the switch event's own state and time. */
  | { kind: 'saved'; on: boolean; atMs: number }
  /** Nothing was saved; press again later. `pass`: `503 switch_busy`, a loop pass is running; otherwise the server's connection cap. */
  | { kind: 'busy'; pass: boolean }
  /** Refused before saving (a guard, `409 switch_refused`, `503 switch_unavailable`): nothing was saved. */
  | { kind: 'refused'; why: string }
  | { kind: 'signed-out' }
  /** No readable answer: it may or may not have been saved. The next read of the loops shows which. */
  | { kind: 'unknown'; why: string };

/** Statuses the server answers before anything is saved, with its JSON error (or 503 with no body). */
const NOT_SAVED = new Set([400, 403, 404, 405, 408, 409, 411, 413, 415, 421, 503]);

const SAVED_KEYS = ['loop_id', 'definition_revision', 'repository', 'project', 'enabled', 'actor', 'at_ms'];

/** The saved event, when the 200's body is exactly this loop's switch to `on` (contracts/web-api.v1.md). */
function savedAt(json: unknown, id: string, on: boolean): number | null {
  if (typeof json !== 'object' || json === null || Array.isArray(json)) return null;
  const o = new Map(Object.entries(json));
  if (o.size !== SAVED_KEYS.length || !SAVED_KEYS.every((k) => o.has(k))) return null;
  const nonblank = (v: unknown) => typeof v === 'string' && v.trim() !== '' && !v.includes('\u0000');
  const revision = o.get('definition_revision');
  const repository = o.get('repository');
  const project = o.get('project');
  const at = o.get('at_ms');
  const ok =
    o.get('loop_id') === id &&
    o.get('enabled') === on &&
    typeof revision === 'string' && /^([0-9a-f]{40}|[0-9a-f]{64})$/.test(revision) &&
    typeof repository === 'string' && /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository) &&
    typeof project === 'string' && /^(?!-)[A-Za-z0-9_-]{1,128}$/.test(project) &&
    nonblank(o.get('actor')) &&
    typeof at === 'number' && Number.isSafeInteger(at) && at >= 0;
  return ok ? at : null;
}

/** What an answer to a switch of loop `id` to `on` means. */
export function switchAnswer(a: Answer, id: string, on: boolean): Switched {
  switch (a.kind) {
    case 'redirect':
      return { kind: 'signed-out' };
    case 'network':
    case 'stopped':
      return { kind: 'unknown', why: 'the connection was lost before an answer' };
    case 'timeout':
      return { kind: 'unknown', why: 'no answer in time' };
    case 'response': {
      if (a.status === 401) return { kind: 'signed-out' };
      if (a.status === 200) {
        const at = savedAt(a.json, id, on);
        return at === null ? { kind: 'unknown', why: 'the answer could not be read' } : { kind: 'saved', on, atMs: at };
      }
      const error = parseApiError(a.json)?.error ?? null;
      if (a.status === 503 && (error?.kind === 'switch_busy' || (error === null && a.empty))) return { kind: 'busy', pass: error !== null };
      if (NOT_SAVED.has(a.status) && error !== null) return { kind: 'refused', why: error.message };
      return { kind: 'unknown', why: `HTTP ${a.status}` };
    }
  }
}

export type SwitchDeps = { fetch: FetchLike };

/** Every loop's switch on the page, and the one place a switch is sent. */
export class LoopSwitches {
  private readonly deps: SwitchDeps;
  private readonly states = new Map<string, Switched>();
  private readonly saved = new Map<string, { on: boolean; atMs: number }>();
  private readonly listeners = new Set<() => void>();
  private changes = 0;

  constructor(deps: SwitchDeps) {
    this.deps = deps;
  }

  get(id: string): Switched | null {
    return this.states.get(id) ?? null;
  }

  /** The last switch the server saved for `id`, kept through later presses that were not saved. */
  confirmed(id: string): { on: boolean; atMs: number } | null {
    return this.saved.get(id) ?? null;
  }

  /** Whether any switch is out. */
  sending(): boolean {
    return [...this.states.values()].some((s) => s.kind === 'sending');
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Changes so far, for `useSyncExternalStore`. */
  version(): number {
    return this.changes;
  }

  /** The one switch: loop `id` to `on`, once. A press while one is out sends nothing. */
  async turn(id: string, on: boolean): Promise<void> {
    if (this.states.get(id)?.kind === 'sending') return;
    if (!isLoopId(id)) {
      this.set(id, { kind: 'refused', why: 'not a loop id, so nothing was sent' });
      return;
    }
    this.set(id, { kind: 'sending', on });
    const control = new AbortController();
    const timer = setTimeout(() => control.abort('timeout'), SWITCH_TIMEOUT_MS);
    try {
      this.set(id, switchAnswer(await postLoopSwitch(this.deps.fetch, id, on, control.signal), id, on));
    } finally {
      clearTimeout(timer);
    }
  }

  private set(id: string, state: Switched): void {
    this.states.set(id, state);
    if (state.kind === 'saved') this.saved.set(id, { on: state.on, atMs: state.atMs });
    this.changes++;
    for (const listener of this.listeners) listener();
  }
}
