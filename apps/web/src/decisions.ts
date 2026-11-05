// Decisions (0.0.11 U6, #656): `GET /api/v1/decisions`, read as
// contracts/decisions.v1.md says, and what each card may show and send.
//
// - **Read exactly.** Every object only with exactly its keys; enums only as
//   their strings; integers only as safe integers, written as integers; facts
//   only as `{known}` or `{unknown: nonempty}`. The text is parsed strictly
//   (src/fleets.ts's `parseJson`), so a key written twice or an integer
//   written `1.0` is refused. The contract's cross-record rules a page can
//   check (open items only, the server's order, answered ids in question
//   order, the plan's graph equal to its table) refuse the whole read.
// - **Order is the server's.** Nothing here re-orders; a round shows only its
//   unanswered questions, in their saved order.
// - **An answer is one send** through the composer's send path, worded from
//   the card, with request/revision context around `L4 yes`, `simplify L4`,
//   the exact own words, `confirm`,
//   `confirm spec #N`, `approve #N`, to the configured, verified orchestrator
//   target, and only when the item is current, its risk known, the read and
//   the target fresh. Nothing here sends: the page's owner presses.

import type { Failure } from './api.ts';
import { freshNow, NO_TARGET } from './cockpit.ts';
import type { Clock, Freshness, Received } from './cockpit.ts';
import type { StorageLike } from './composer.ts';
import type { Fact } from './envelope.ts';
import { parseJson } from './fleets.ts';
import { FLEET_TIMING } from './timing.ts';

export const DECISIONS_SCHEMA_ID = 'openwiz.decisions.v1';

// ── the shapes (contracts/decisions.v1.schema.json) ──

export type GapKind = 'untested_version' | 'command_failed' | 'timed_out' | 'budget_exhausted' | 'malformed' | 'missing_field' | 'wrong_type' | 'not_found' | 'truncated' | 'unsupported';
export type Gap = { kind: GapKind; detail: string };
export type Coverage = { state: 'complete' | 'partial'; gaps: Gap[] };
export type Risk = 'ordinary' | 'live' | 'release' | 'publish' | 'unknown';
export type Question = { id: string; decides: string; context: string; recommendation: string };
export type Ticket = { number: number; title: string; blockers: number[] };
export type Edge = { blocker: number; ticket: number };
type Common = { schema: typeof DECISIONS_SCHEMA_ID; id: string; status: 'open'; fingerprint: string; risk: Risk };
export type GrillRound = Common & { kind: 'grill_round'; grill_file: string; round: number; questions: Question[]; answered: string[] };
export type GrillConfirmation = Common & { kind: 'grill_confirmation'; grill_file: string; summary: string[] };
export type SpecConfirmation = Common & { kind: 'spec_confirmation'; spec: number; summary: string[]; headline: string; tickets: Ticket[]; graph: Edge[] };
export type PlanApproval = Common & { kind: 'plan_approval'; spec: number; summary: string[]; headline: string; tickets: Ticket[]; graph: Edge[] };
export type Request = GrillRound | GrillConfirmation | SpecConfirmation | PlanApproval;
export type Subject = { repository: string; kind: 'issue' | 'pull_request'; number: number };
export type Item = { comment_id: number; subject: Subject; created_at: number; updated_at: number; current: Fact<boolean>; request: Request };
export type Orchestrator = { coverage: Coverage; freshness: Freshness; target: Fact<string | null> };
export type Decisions = { schema: typeof DECISIONS_SCHEMA_ID; kind: 'response'; snapshot_at: number; coverage: Coverage; freshness: Freshness; orchestrator: Orchestrator; items: Item[] };
export type DecisionsOutcome = { kind: 'ok'; envelope: Decisions } | Failure;

// ── the reader ──

const GAP_KINDS: readonly GapKind[] = ['untested_version', 'command_failed', 'timed_out', 'budget_exhausted', 'malformed', 'missing_field', 'wrong_type', 'not_found', 'truncated', 'unsupported'];
const RISKS: readonly Risk[] = ['ordinary', 'live', 'release', 'publish', 'unknown'];
const ID = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;
const HEX64 = /^[0-9a-f]{64}$/;
const GRILL_FILE = /^docs\/grills\/[A-Za-z0-9][A-Za-z0-9_.-]*[.]md$/;
const THREAD = /^[A-Za-z0-9_][A-Za-z0-9_-]{0,127}$/;
/** A grill question's id: one or two capital topic letters and a positive counter (G1, PG12), as crates/server checks. */
const QUESTION_ID = /^[A-Z]{1,2}[1-9][0-9]*$/;
const COMMON = ['schema', 'id', 'status', 'fingerprint', 'risk', 'kind'] as const;

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
const matching = (re: RegExp) => (v: unknown, at: string): string => {
  const s = text(v, at);
  return re.test(s) ? s : refuse(at, 'not in the contract’s form');
};
const whole = (min: number) => (v: unknown, at: string): number => (typeof v === 'number' && Number.isSafeInteger(v) && v >= min ? v : refuse(at, `not an integer of at least ${min}`));
const time = whole(0);
const positive = whole(1);
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
function gap(v: unknown, at: string): Gap {
  const o = exact(v, at, ['kind', 'detail']);
  return { kind: oneOf(GAP_KINDS)(o.get('kind'), `${at}.kind`), detail: text(o.get('detail'), `${at}.detail`) };
}
function coverage(v: unknown, at: string): Coverage {
  const o = exact(v, at, ['state', 'gaps']);
  const state = oneOf(['complete', 'partial'] as const)(o.get('state'), `${at}.state`);
  const gaps = items(o.get('gaps'), `${at}.gaps`, gap);
  if ((state === 'complete') !== (gaps.length === 0)) refuse(at, state === 'complete' ? 'complete with gaps' : 'partial without a gap');
  return { state, gaps };
}
function freshness(v: unknown, at: string): Freshness {
  const o = exact(v, at, ['state', 'snapshot_at']);
  const state = oneOf(['fresh', 'stale', 'unknown'] as const)(o.get('state'), `${at}.state`);
  const snap = fact(time)(o.get('snapshot_at'), `${at}.snapshot_at`);
  if (state === 'unknown') return 'unknown' in snap ? { state, snapshot_at: snap } : refuse(at, 'unknown freshness with a known time');
  return 'known' in snap ? { state, snapshot_at: snap } : refuse(at, `${state} without a known time`);
}
function summary(v: unknown, at: string): string[] {
  const lines = items(v, at, (x, a) => (/[\r\n]/.test(text(x, a)) ? refuse(a, 'a line break inside a summary line') : text(x, a)));
  return lines.length >= 1 && lines.length <= 10 ? lines : refuse(at, 'not 1 to 10 lines');
}
function question(v: unknown, at: string): Question {
  const o = exact(v, at, ['id', 'decides', 'context', 'recommendation']);
  return { id: matching(QUESTION_ID)(o.get('id'), `${at}.id`), decides: text(o.get('decides'), `${at}.decides`), context: text(o.get('context'), `${at}.context`), recommendation: text(o.get('recommendation'), `${at}.recommendation`) };
}
function ticket(v: unknown, at: string): Ticket {
  const o = exact(v, at, ['number', 'title', 'blockers']);
  const t = { number: positive(o.get('number'), `${at}.number`), title: text(o.get('title'), `${at}.title`), blockers: items(o.get('blockers'), `${at}.blockers`, positive) };
  t.blockers.forEach((b, i) => {
    if (b === t.number) refuse(`${at}.blockers[${i}]`, 'a ticket blocking itself');
    if (i > 0 && !(t.blockers[i - 1]! < b)) refuse(`${at}.blockers[${i}]`, 'not unique and ascending');
  });
  return t;
}
function edge(v: unknown, at: string): Edge {
  const o = exact(v, at, ['blocker', 'ticket']);
  return { blocker: positive(o.get('blocker'), `${at}.blocker`), ticket: positive(o.get('ticket'), `${at}.ticket`) };
}

/** The plan's table, sorted by number, and its graph: exactly the table's edges, sorted, never a second graph. */
function plan(tickets: Ticket[], graph: Edge[], at: string): void {
  tickets.forEach((t, i) => {
    if (i > 0 && !(tickets[i - 1]!.number < t.number)) refuse(`${at}.tickets[${i}]`, 'not unique and sorted by number');
  });
  const want = tickets.flatMap((t) => t.blockers.map((b) => `${b}-${t.number}`));
  const have = graph.map((e) => `${e.blocker}-${e.ticket}`);
  const ordered = graph.every((e, i) => i === 0 || graph[i - 1]!.blocker < e.blocker || (graph[i - 1]!.blocker === e.blocker && graph[i - 1]!.ticket < e.ticket));
  if (!ordered || have.length !== want.length || !want.every((w) => have.includes(w))) refuse(`${at}.graph`, 'not exactly the table’s edges, sorted');
}

function request(v: unknown, at: string): Request {
  const kind = typeof v === 'object' && v !== null && !Array.isArray(v) ? new Map(Object.entries(v)).get('kind') : undefined;
  const keys: Record<Request['kind'], readonly string[]> = {
    grill_round: [...COMMON, 'grill_file', 'round', 'questions', 'answered'],
    grill_confirmation: [...COMMON, 'grill_file', 'summary'],
    spec_confirmation: [...COMMON, 'spec', 'summary', 'headline', 'tickets', 'graph'],
    plan_approval: [...COMMON, 'spec', 'summary', 'headline', 'tickets', 'graph'],
  };
  const k = oneOf(['grill_round', 'grill_confirmation', 'spec_confirmation', 'plan_approval'] as const)(kind, `${at}.kind`);
  const o = exact(v, at, keys[k]);
  if (o.get('schema') !== DECISIONS_SCHEMA_ID) refuse(`${at}.schema`, `not ${DECISIONS_SCHEMA_ID}`);
  if (o.get('status') !== 'open') refuse(`${at}.status`, 'a response item is open only');
  const common: Common = { schema: DECISIONS_SCHEMA_ID, id: matching(ID)(o.get('id'), `${at}.id`), status: 'open', fingerprint: matching(HEX64)(o.get('fingerprint'), `${at}.fingerprint`), risk: oneOf(RISKS)(o.get('risk'), `${at}.risk`) };
  if (k === 'grill_round') {
    const questions = items(o.get('questions'), `${at}.questions`, question);
    if (questions.length < 1 || questions.length > 3) refuse(`${at}.questions`, 'not 1 to 3 questions');
    const ids = questions.map((q) => q.id);
    if (new Set(ids).size !== ids.length) refuse(`${at}.questions`, 'a question id twice');
    const answered = items(o.get('answered'), `${at}.answered`, text);
    // Exactly the saved ids, unique and in question order; a fully answered round is resolved, never open.
    const inOrder = ids.filter((id) => answered.includes(id));
    if (inOrder.length !== answered.length || inOrder.some((id, i) => answered[i] !== id)) refuse(`${at}.answered`, 'not unique question ids in question order');
    if (answered.length === ids.length) refuse(`${at}.answered`, 'every question answered, yet open');
    return { ...common, kind: k, grill_file: matching(GRILL_FILE)(o.get('grill_file'), `${at}.grill_file`), round: positive(o.get('round'), `${at}.round`), questions, answered };
  }
  if (k === 'grill_confirmation') return { ...common, kind: k, grill_file: matching(GRILL_FILE)(o.get('grill_file'), `${at}.grill_file`), summary: summary(o.get('summary'), `${at}.summary`) };
  const tickets = items(o.get('tickets'), `${at}.tickets`, ticket);
  const graph = items(o.get('graph'), `${at}.graph`, edge);
  if (k === 'spec_confirmation' && (tickets.length > 0 || graph.length > 0)) refuse(`${at}.tickets`, 'a spec confirmation precedes its tickets');
  plan(tickets, graph, at);
  return { ...common, kind: k, spec: positive(o.get('spec'), `${at}.spec`), summary: summary(o.get('summary'), `${at}.summary`), headline: text(o.get('headline'), `${at}.headline`), tickets, graph };
}

function item(v: unknown, at: string): Item {
  const o = exact(v, at, ['comment_id', 'subject', 'created_at', 'updated_at', 'current', 'request']);
  const s = exact(o.get('subject'), `${at}.subject`, ['repository', 'kind', 'number']);
  const x: Item = {
    comment_id: positive(o.get('comment_id'), `${at}.comment_id`),
    subject: { repository: matching(/^[A-Za-z0-9][A-Za-z0-9-]*\/[A-Za-z0-9_.-]+$/)(s.get('repository'), `${at}.subject.repository`), kind: oneOf(['issue', 'pull_request'] as const)(s.get('kind'), `${at}.subject.kind`), number: positive(s.get('number'), `${at}.subject.number`) },
    created_at: time(o.get('created_at'), `${at}.created_at`),
    updated_at: time(o.get('updated_at'), `${at}.updated_at`),
    current: fact((x, a) => (typeof x === 'boolean' ? x : refuse(a, 'not a boolean')))(o.get('current'), `${at}.current`),
    request: request(o.get('request'), `${at}.request`),
  };
  // Where a request is posted: a grill round or summary on its grill's PR; a spec or plan request on its own spec issue.
  const r = x.request;
  const onPr = r.kind === 'grill_round' || r.kind === 'grill_confirmation';
  if (onPr !== (x.subject.kind === 'pull_request') || ((r.kind === 'spec_confirmation' || r.kind === 'plan_approval') && r.spec !== x.subject.number)) refuse(`${at}.subject`, 'not where this kind of request is posted');
  return x;
}

/** Contract order: creation time, repository, subject kind/number, comment id. Checked, never re-done. */
function before(a: Item, b: Item): boolean {
  if (a.created_at !== b.created_at) return a.created_at < b.created_at;
  if (a.subject.repository !== b.subject.repository) return a.subject.repository < b.subject.repository;
  if (a.subject.kind !== b.subject.kind) return a.subject.kind < b.subject.kind;
  if (a.subject.number !== b.subject.number) return a.subject.number < b.subject.number;
  return a.comment_id < b.comment_id;
}

function crossRecords(d: Decisions): void {
  const comments = new Set<string>();
  const ids = new Set<string>();
  d.items.forEach((x, i) => {
    const commentKey = JSON.stringify([x.subject.repository, x.comment_id]);
    const requestKey = JSON.stringify([x.subject.repository, x.request.id]);
    if (comments.has(commentKey)) refuse(`$.items[${i}]`, `comment ${x.comment_id} twice`);
    if (ids.has(requestKey)) refuse(`$.items[${i}].request.id`, `request ${x.request.id} twice`);
    comments.add(commentKey);
    ids.add(requestKey);
    const prev = d.items[i - 1];
    if (prev && !before(prev, x)) refuse(`$.items[${i}]`, 'not in the contract’s order');
  });
  for (const [at, cov, f] of [['$', d.coverage, d.freshness], ['$.orchestrator', d.orchestrator.coverage, d.orchestrator.freshness]] as const) {
    if (cov.state === 'partial' && cov.gaps.length === 0) refuse(`${at}.coverage`, 'partial without a gap');
    if (f.state === 'unknown') continue;
    const age = d.snapshot_at - f.snapshot_at.known;
    if (age < 0) refuse(`${at}.freshness`, 'a snapshot after assembly');
    if ((f.state === 'fresh') !== age <= FLEET_TIMING.staleAfterMs) refuse(`${at}.freshness`, `${f.state} does not match its age`);
  }
}

/** A `decisions.v1` response, read exactly; or where and why it was refused. */
export function readDecisions(json: unknown): { ok: true; decisions: Decisions } | { ok: false; why: string } {
  try {
    const o = exact(json, '$', ['schema', 'kind', 'snapshot_at', 'coverage', 'freshness', 'orchestrator', 'items']);
    if (o.get('schema') !== DECISIONS_SCHEMA_ID) refuse('$.schema', `not ${DECISIONS_SCHEMA_ID}`);
    if (o.get('kind') !== 'response') refuse('$.kind', 'not a response');
    const orch = exact(o.get('orchestrator'), '$.orchestrator', ['coverage', 'freshness', 'target']);
    const d: Decisions = {
      schema: DECISIONS_SCHEMA_ID,
      kind: 'response',
      snapshot_at: time(o.get('snapshot_at'), '$.snapshot_at'),
      coverage: coverage(o.get('coverage'), '$.coverage'),
      freshness: freshness(o.get('freshness'), '$.freshness'),
      orchestrator: {
        coverage: coverage(orch.get('coverage'), '$.orchestrator.coverage'),
        freshness: freshness(orch.get('freshness'), '$.orchestrator.freshness'),
        target: fact((x, a) => (x === null ? null : matching(THREAD)(x, a)))(orch.get('target'), '$.orchestrator.target'),
      },
      items: items(o.get('items'), '$.items', item),
    };
    crossRecords(d);
    return { ok: true, decisions: d };
  } catch (e) {
    if (e instanceof Refused) return { ok: false, why: e.message };
    throw e;
  }
}

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
export function readDecisionsText(text: string): { ok: true; decisions: Decisions } | { ok: false; why: string } {
  let json: unknown;
  try {
    json = plain(parseJson(text));
  } catch (e) {
    if (e instanceof Error) return { ok: false, why: `not strict JSON: ${e.message}` };
    throw e;
  }
  return readDecisions(json);
}

// ── the cards ──

/**
 * One answer slot: a grill question still unanswered, or a confirmation's
 * one action. Its key is the request (by subject, comment and id) and the
 * question, never a card's position on the page.
 */
export type Slot = { key: string; item: Item; question: Question | null };

/** The page's slots, in the server's order: a round's unanswered questions in their saved order; one per confirmation. */
export function slotsOf(d: Decisions): Slot[] {
  return d.items.flatMap((x): Slot[] => {
    const base = [x.subject.repository, x.subject.kind, x.subject.number, x.comment_id, x.request.id];
    const r = x.request;
    if (r.kind !== 'grill_round') return [{ key: JSON.stringify(base), item: x, question: null }];
    return r.questions.filter((q) => !r.answered.includes(q.id)).map((q) => ({ key: JSON.stringify([...base, q.id]), item: x, question: q }));
  });
}

export type Choice = 'yes' | 'simplify' | 'own' | 'confirm';

/** The answer segment alone, also used for concise action labels. Never trim own words. */
export function answerWords(s: Slot, choice: Choice, own = ''): string | null {
  const r = s.item.request;
  if (s.question !== null) {
    if (choice === 'yes') return `${s.question.id} yes`;
    if (choice === 'simplify') return `simplify ${s.question.id}`;
    return choice === 'own' ? own : null;
  }
  if (choice !== 'confirm') return null;
  if (r.kind === 'grill_confirmation') return 'confirm';
  if (r.kind === 'spec_confirmation') return `confirm spec #${r.spec}`;
  return r.kind === 'plan_approval' ? `approve #${r.spec}` : null;
}

/**
 * One existing send: a fixed-order, compact JSON context line, a blank line,
 * then the untouched answer through message EOF. No closing delimiter can
 * collide with answer text. This is message text, never request metadata.
 */
export function answerText(s: Slot, choice: Choice, own = ''): string | null {
  const answer = answerWords(s, choice, own);
  if (answer === null) return null;
  const { subject, comment_id, request: r } = s.item;
  const context = {
    subject: { repository: subject.repository, kind: subject.kind, number: subject.number },
    comment_id,
    request_id: r.id,
    request_kind: r.kind,
    fingerprint: r.fingerprint,
    ...(r.kind === 'grill_round' ? { grill_file: r.grill_file, round: r.round, question_id: s.question!.id }
      : r.kind === 'grill_confirmation' ? { grill_file: r.grill_file } : { spec: r.spec }),
  };
  return `openwiz decision answer v1\n${JSON.stringify(context)}\n\n${answer}`;
}

/** The risks that always ask twice. */
export const ASKS_TWICE: readonly Risk[] = ['live', 'release', 'publish'];
export const risky = (r: Risk): boolean => ASKS_TWICE.includes(r);

/** A risk's badge words. */
export function riskWords(r: Risk): string {
  return risky(r) ? `${r.charAt(0).toUpperCase()}${r.slice(1)} · asks twice` : r === 'unknown' ? 'Risk not classified' : 'Ordinary';
}

/** What a risky record's second confirmation asks. */
export function armNote(s: Slot, outgoing: string): string {
  const r = s.item.request;
  const what = r.risk === 'release' ? (r.kind === 'plan_approval' ? 'This approves a release.' : 'This is about a release.') : r.risk === 'publish' ? 'This is about a publish.' : 'This is about a live step.';
  return `${what} Send “${outgoing}” with request and revision context to the orchestrator?`;
}

/**
 * Everything the owner sees that an answer binds to: the subject, comment,
 * request (its id, fingerprint, risk and exact displayed proposal, without
 * its answer progress), the question and the verified target. A different
 * binding is a different answer: nothing made on one is sent for another.
 */
export function bindingOf(d: Decisions, s: Slot): string | null {
  const t = d.orchestrator.target;
  if (!('known' in t) || t.known === null) return null;
  const r = s.item.request;
  const proposal = r.kind === 'grill_round' ? { ...r, answered: [] } : r;
  return JSON.stringify([s.item.subject, s.item.comment_id, proposal, s.question, t.known]);
}

export type Actionable = { ok: true; target: string; risky: boolean; binding: string } | { ok: false; why: string };

/**
 * Whether a slot may be answered now, and to which thread: only with its
 * wording known current, its risk classified, the read fresh, and the
 * configured target verified (its check complete) and fresh.
 */
export function actionable(d: Decisions, s: Slot, received: Received, now: Clock): Actionable {
  const t = d.orchestrator.target;
  if (!('known' in t) || t.known === null || d.orchestrator.coverage.state !== 'complete') return { ok: false, why: NO_TARGET };
  const c = s.item.current;
  if (!('known' in c)) return { ok: false, why: `answer unavailable: current wording could not be verified (${c.unknown})` };
  if (!c.known) return { ok: false, why: 'answer unavailable: wording changed since it was read' };
  if (s.item.request.risk === 'unknown') return { ok: false, why: 'answer unavailable: its risk is not classified' };
  if (!freshNow(d.freshness, d.snapshot_at, received, now)) return { ok: false, why: 'answer unavailable: this read is not fresh; refresh it' };
  if (!freshNow(d.orchestrator.freshness, d.snapshot_at, received, now)) return { ok: false, why: 'answer unavailable: the orchestrator check is not fresh; refresh it' };
  const binding = bindingOf(d, s);
  return binding === null ? { ok: false, why: NO_TARGET } : { ok: true, target: t.known, risky: risky(s.item.request.risk), binding };
}

/** Only a complete, fresh, empty read may say nothing waits. */
export function nothingWaits(d: Decisions, received: Received, now: Clock): boolean {
  return d.items.length === 0 && d.coverage.state === 'complete' && freshNow(d.freshness, d.snapshot_at, received, now);
}

// ── a slot's own composer storage, and its receipt ──

/**
 * Each slot's answer keeps its own op id and attempts, apart from the
 * orchestrator's own message box and every other slot: the composer's tab
 * storage (src/composer.ts's `browserStorage`), under the slot's key.
 */
export function slotStorage(storage: StorageLike | null, key: string): StorageLike | null {
  if (storage === null) return null;
  const prefix = `openwiz.decisions.${encodeURIComponent(key)}.`;
  return {
    getItem: (k) => storage.getItem(prefix + k),
    setItem: (k, v) => storage.setItem(prefix + k, v),
    removeItem: (k) => storage.removeItem(prefix + k),
  };
}

/** An old slot has no repository binding. Never migrate its delivery identity
 * into either new slot, or mistake its uncertain outcome for an absent answer.
 * Inspect only: settlement must not erase or rebind these older bytes. */
export function legacyAnswerReason(storage: StorageLike | null, key: string): string | null {
  const unread = 'answer unavailable: earlier answer storage could not be checked';
  const unresolved = 'answer unavailable: an earlier unqualified answer record must be resolved before answering this repository';
  if (storage === null) return unread;
  try {
    const parts: unknown = JSON.parse(key);
    if (!Array.isArray(parts) || typeof parts[0] !== 'string') return unread;
    const prefix = `openwiz.decisions.${encodeURIComponent(JSON.stringify(parts.slice(1)))}.`;
    if (storage.getItem(prefix + 'receipt') !== null) return unresolved;
    // Native tab storage can enumerate composer records for an old target,
    // even when the currently configured orchestrator is a different target.
    if (!('key' in storage) || typeof storage.key !== 'function' || !('length' in storage)) return unread;
    const length = storage.length;
    if (typeof length !== 'number' || !Number.isSafeInteger(length) || length < 0) return unread;
    for (let i = 0; i < length; i++) {
      const name: unknown = storage.key(i);
      if (typeof name !== 'string') return unread;
      if (name.startsWith(prefix + 'openwiz.composer.')) return unresolved;
    }
    return null;
  } catch {
    return unread;
  }
}

/**
 * A slot's receipt, kept in its own storage before the send leaves and for
 * as long as the slot is in the read: the binding and target it was made
 * for, its exact text, when it was pressed, and its phase. A queued or sent
 * receipt stays after the composer has let go of its op id, so a reload
 * never offers the same answer again until the orchestrator saves it and the
 * slot leaves the read. A receipt for another binding never retries.
 */
export type Receipt = { binding: string; target: string; text: string; at: number; phase: 'pending' | 'queued' | 'sent' };

const RECEIPT = 'receipt';

export function readReceipt(storage: StorageLike | null): Receipt | null {
  try {
    const raw = storage?.getItem(RECEIPT) ?? null;
    const v: unknown = raw === null ? null : JSON.parse(raw);
    if (typeof v !== 'object' || v === null || Array.isArray(v)) return null;
    const o = new Map(Object.entries(v));
    const [binding, target, t, at, phase] = [o.get('binding'), o.get('target'), o.get('text'), o.get('at'), o.get('phase')];
    if (typeof binding !== 'string' || typeof target !== 'string' || typeof t !== 'string' || typeof at !== 'number') return null;
    return phase === 'pending' || phase === 'queued' || phase === 'sent' ? { binding, target, text: t, at, phase } : null;
  } catch {
    return null;
  }
}

/** True only when it is stored: the send leaves only after this. */
export function writeReceipt(storage: StorageLike | null, r: Receipt): boolean {
  if (storage === null) return false;
  try {
    storage.setItem(RECEIPT, JSON.stringify(r));
    const back = readReceipt(storage);
    return back?.phase === r.phase && back.text === r.text;
  } catch {
    return false;
  }
}

export function clearReceipt(storage: StorageLike | null): void {
  try {
    storage?.removeItem(RECEIPT);
  } catch {
    // A receipt that can't be cleared stays: it keeps the slot closed, never open.
  }
}
