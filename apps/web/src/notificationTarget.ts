import { parseJson } from './fleets.ts';
import { actionable, slotsOf } from './decisions.ts';
import type { Decisions, Item } from './decisions.ts';
import type { Clock, Received } from './cockpit.ts';
import { freshNow } from './cockpit.ts';
import { readNotificationTarget, serverDone } from './api.ts';
import type { Failure, FetchLike } from './api.ts';
import { Lane, Poller } from './poller.ts';
import type { Timers, Visibility } from './poller.ts';
import { FLEET_TIMING, TIMING } from './timing.ts';

/** A notification contains only an opaque lookup key, never a destination URL. */
export type NotificationLanding = { kind: 'none' } | { kind: 'invalid' } | { kind: 'target'; token: string };

function validToken(token: string): boolean {
  return token.length === 64 && /^[0-9a-f]+$/.test(token);
}

export function notificationToken(fragment: string): NotificationLanding {
  if (fragment === '') return { kind: 'none' };
  if (!fragment.startsWith('#')) return { kind: 'invalid' };
  if (!fragment.startsWith('#notification')) return { kind: 'none' };
  const token = fragment.slice('#notification='.length);
  return fragment.startsWith('#notification=') && validToken(token)
    ? { kind: 'target', token }
    : { kind: 'invalid' };
}

/** Validation precedes the request; encode/decode never turns a URL into a token. */
export function targetUrl(token: string): string | null {
  return validToken(token) ? `/api/v1/notifications/targets/${token}` : null;
}

type Subject = { kind: 'issue' | 'pull_request'; number: number };
export type DecisionReference = { repository: string; subject: Subject; comment_id: number; request_id: string; fingerprint: string };
export type IncidentReference = { repository: string; owner: string; source: 'service_health' | 'loop_watchdog'; subject: string; incident: string };
const OWNERS = ['decisions', 'service_health', 'loop_watchdog', 'event_router', 'fleet', 'inventory', 'plan', 'loops', 'service_update'] as const;
type SourceOwner = typeof OWNERS[number];
export type TargetReference = { decision: DecisionReference } | { incident: IncidentReference } | { event: { repository: string; source: SourceOwner; subject: string; event_id: string; revision: string } };
export type TargetResult = {
  reference: TargetReference;
  state: 'current' | 'changed' | 'resolved' | 'missing' | 'ambiguous' | 'unread';
  coverage: { state: 'complete' | 'partial'; gaps: { source: SourceOwner; reason: string }[] };
  freshness: { state: 'fresh' | 'stale'; snapshot_at: { known: number } } | { state: 'unknown'; snapshot_at: { unknown: string } };
};

function requireValue(ok: boolean): asserts ok {
  if (!ok) throw new Error('invalid notification target');
}

function object(value: unknown, keys: readonly string[]): Map<string, unknown> {
  requireValue(value instanceof Map);
  requireValue(value.size === keys.length && keys.every((key) => value.has(key)));
  return value;
}

function text(value: unknown, pattern?: RegExp): string {
  requireValue(typeof value === 'string' && value.length > 0);
  // Contract identifiers contain no line breaks.
  requireValue(!pattern || (!value.includes('\n') && pattern.test(value)));
  return value;
}

function choice<T extends string>(value: unknown, values: readonly T[]): T {
  const found = values.find((candidate) => candidate === value);
  requireValue(found !== undefined);
  return found;
}

function integer(value: unknown, minimum = 0): number {
  requireValue(typeof value === 'object' && value !== null && 'integer' in value && value.integer === true && 'value' in value);
  const n = value.value;
  requireValue(typeof n === 'number' && Number.isSafeInteger(n) && !Object.is(n, -0) && n >= minimum);
  return n;
}

const REPOSITORY = /^[a-z0-9][a-z0-9-]*\/[a-z0-9_.-]+$/;
const ID = /^[A-Za-z0-9_][A-Za-z0-9_-]{0,127}$/;

function reference(value: unknown): TargetReference {
  requireValue(value instanceof Map);
  const keys = [...value.keys()];
  requireValue(keys.length === 1);
  const tag = keys[0];
  if (tag === 'decision') {
    const o = object(object(value, ['decision']).get('decision'), ['repository', 'subject', 'comment_id', 'request_id', 'fingerprint']);
    const s = object(o.get('subject'), ['kind', 'number']);
    const fingerprint = text(o.get('fingerprint'));
    requireValue(validToken(fingerprint));
    return { decision: {
      repository: text(o.get('repository'), REPOSITORY),
      subject: { kind: choice(s.get('kind'), ['issue', 'pull_request']), number: integer(s.get('number'), 1) },
      comment_id: integer(o.get('comment_id'), 1), request_id: text(o.get('request_id'), /^[A-Za-z0-9][A-Za-z0-9_-]*$/), fingerprint,
    } };
  }
  if (tag === 'incident') {
    const o = object(object(value, ['incident']).get('incident'), ['repository', 'owner', 'source', 'subject', 'incident']);
    return { incident: {
      repository: text(o.get('repository'), REPOSITORY), owner: text(o.get('owner'), ID),
      source: choice(o.get('source'), ['service_health', 'loop_watchdog']), subject: text(o.get('subject'), ID), incident: text(o.get('incident'), ID),
    } };
  }
  const o = object(object(value, ['event']).get('event'), ['repository', 'source', 'subject', 'event_id', 'revision']);
  return { event: { repository: text(o.get('repository'), REPOSITORY), source: choice(o.get('source'), OWNERS), subject: text(o.get('subject'), ID), event_id: text(o.get('event_id'), ID), revision: text(o.get('revision'), ID) } };
}

/** Shape validation supplies no authority: currentness still requires source verification. */
export function readTargetText(body: string): TargetResult | null {
  try {
    const doc = object(parseJson(body), ['schema', 'record']);
    requireValue(doc.get('schema') === 'openwiz.notifications.v1');
    const result = object(object(doc.get('record'), ['target_result']).get('target_result'), ['reference', 'state', 'coverage', 'freshness']);
    const coverage = object(result.get('coverage'), ['state', 'gaps']);
    const coverageState = choice(coverage.get('state'), ['complete', 'partial']);
    const rawGaps = coverage.get('gaps');
    requireValue(Array.isArray(rawGaps));
    const gaps = rawGaps.map((value) => {
      const gap = object(value, ['source', 'reason']);
      return { source: choice(gap.get('source'), OWNERS), reason: text(gap.get('reason')) };
    });
    requireValue((gaps.length === 0) === (coverageState === 'complete'));
    const f = object(result.get('freshness'), ['state', 'snapshot_at']);
    const state = choice(f.get('state'), ['fresh', 'stale', 'unknown']);
    requireValue(state !== 'unknown' || coverageState === 'partial');
    const freshness: TargetResult['freshness'] = state === 'unknown'
      ? { state, snapshot_at: { unknown: text(object(f.get('snapshot_at'), ['unknown']).get('unknown')) } }
      : { state, snapshot_at: { known: integer(object(f.get('snapshot_at'), ['known']).get('known')) } };
    return { reference: reference(result.get('reference')), state: choice(result.get('state'), ['current', 'changed', 'resolved', 'missing', 'ambiguous', 'unread']), coverage: { state: coverageState, gaps }, freshness };
  } catch {
    return null;
  }
}

export type BoundDecision = { state: 'current'; item: Item; binding: string } | { state: Exclude<TargetResult['state'], 'current'>; needsResolution?: boolean };

/** Select by exact identity; a displayed proposal never silently rebinds. */
export function selectBoundDecision(reference: DecisionReference, decisions: Decisions, received: Received, now: Clock, pinned?: string): BoundDecision {
  // Local ids are unique only within a repository (#2150). Compare the source's
  // verified name in the reference's lowercase form; never substitute another.
  const ours = decisions.items.filter((item) => item.subject.repository.toLowerCase() === reference.repository);
  const matches = ours.filter((item) => item.comment_id === reference.comment_id);
  if (matches.length > 1 || ours.filter((item) => item.request.id === reference.request_id).length > 1) return { state: 'ambiguous' };
  const item = matches[0];
  if (!item) return { state: 'unread', needsResolution: decisions.coverage.state === 'complete' && freshNow(decisions.freshness, decisions.snapshot_at, received, now) };
  if (item.subject.kind !== reference.subject.kind || item.subject.number !== reference.subject.number
    || item.request.id !== reference.request_id || item.request.fingerprint !== reference.fingerprint) return { state: 'changed' };
  if ('known' in item.current && !item.current.known) return { state: 'changed' };
  if (decisions.coverage.state !== 'complete') return { state: 'unread' };
  const slot = slotsOf({ ...decisions, items: [item] })[0];
  if (!slot) return { state: 'resolved' };
  const act = actionable(decisions, slot, received, now);
  if (!act.ok) return { state: 'unread' };
  // Answer progress is lifecycle, not changed proposal wording. The existing
  // card owns every question's send id and receipt; this adds no answer state.
  const proposal = Object.fromEntries(Object.entries(item.request).filter(([key]) => key !== 'status' && key !== 'answered'));
  const binding = JSON.stringify([reference, proposal, act.target]);
  if (pinned !== undefined && binding !== pinned) return { state: 'changed' };
  return { state: 'current', item, binding };
}

export function targetIsFresh(target: TargetResult, received: Received, now: Clock): boolean {
  if (target.coverage.state !== 'complete' || target.freshness.state !== 'fresh') return false;
  const age = received.wall - target.freshness.snapshot_at.known;
  const mono = now.mono - received.mono;
  const wall = now.wall - received.wall;
  return age >= 0 && mono >= 0 && wall >= 0 && age + Math.max(mono, wall) <= FLEET_TIMING.staleAfterMs;
}

type TargetOutcome = { kind: 'ok'; envelope: TargetResult } | Failure;
const targetLane = new Lane();

/** Existing lane lifecycle for bound navigation, independent of React mounts. */
export function targetReader(o: { token: string; fetch: FetchLike; timers: Timers; visibility: Visibility; onReading(): void; deliver(result: TargetOutcome): void; onTimeout(): void }): Poller<TargetOutcome> {
  return new Poller({
    lane: targetLane,
    intervalMs: FLEET_TIMING.intervalMs, timeoutMs: TIMING.requestTimeoutMs, holdMs: TIMING.laneHoldMs,
    backoffMs: FLEET_TIMING.backoffMs, timers: o.timers, visibility: o.visibility,
    read: (signal) => { o.onReading(); return readNotificationTarget(o.fetch, o.token, signal); },
    settle: (result) => ({ ok: result.kind === 'ok', confirmed: result.kind === 'ok' || serverDone(result), retryAfterMs: result.kind === 'busy' ? result.retryAfterMs : null }),
    deliver: o.deliver, onTimeout: o.onTimeout,
  });
}

export function targetObservation(previous: Received | null, target: TargetResult, current: Clock): Received {
  if (!previous) return current;
  // A repeated/older source timestamp cannot restart its elapsed age. Only a
  // positively later source observed within this wall clock gets a new base.
  const f = target.freshness;
  return f.state !== 'unknown' && f.snapshot_at.known > previous.wall && f.snapshot_at.known <= current.wall
    && current.mono >= previous.mono && current.wall >= previous.wall ? current : previous;
}
