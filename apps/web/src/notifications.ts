// Notification settings/status presentation only. Native permission, subscription
// and the durable round trip are supplied by #2035, never inferred here.
import { parseJson } from './fleets.ts';
import type { Failure } from './api.ts';

export const NOTIFICATION_CATEGORIES = [
  ['decision', 'Decisions', true], ['recovery_escalation', 'Factory needs you', true],
  ['ci_failed', 'CI failures', false], ['review_findings', 'Review findings', false],
  ['re_check', 'Review re-checks', false], ['merge', 'Merges', false],
  ['agent_complete', 'Agent completion', false], ['ready_stock_changed', 'Ready stock changes', false],
  ['loop_missed', 'Missed loops', false], ['loop_stuck', 'Stuck loops', false],
  ['loop_disabled', 'Loops disabled by failures', false], ['loop_run_changed', 'Loop run changes', false],
  ['recovery_changed', 'Recovery changes', false], ['service_update', 'Service updates', false],
  ['contract_changed', 'Contract changes', false], ['fleet_wait_changed', 'Fleet waiting changes', false],
] as const;
export type NotificationCategory = typeof NOTIFICATION_CATEGORIES[number][0];
export type NotificationCategories = Record<NotificationCategory, boolean>;
export type NotificationPreferences = { generation: number; enabled: boolean; categories: NotificationCategories };
export type NotificationPreferenceWrite = { operation_id: string; expected_generation: number; enabled: boolean; categories: NotificationCategories };
type CapabilityState = 'unavailable' | 'unsupported' | 'setup_required' | 'ready';
type Permission = 'unknown' | 'prompt' | 'granted' | 'denied' | 'revoked' | 'unsupported';
type SubscriptionState = 'absent' | 'ready' | 'revoked' | 'failed' | 'unsupported';
export type NotificationState = 'off' | 'unavailable' | 'unsupported' | 'setup_required' | 'permission_denied' | 'permission_revoked' | 'ready' | 'pending' | 'accepted' | 'failed' | 'uncertain';
type DispatchState = 'reserved' | 'submitting' | 'pending' | 'accepted' | 'failed' | 'uncertain' | 'cancelled';
type Fact<T> = { known: T } | { unknown: string };
export type NotificationStatus = {
  state: NotificationState; reason: string; next: string;
  preferences: NotificationPreferences;
  capability: { state: CapabilityState; permission: Permission; reason: string; next: string };
  subscription: { generation: number; state: SubscriptionState; reason: string; next: string };
  sources: { category: NotificationCategory; available: Fact<boolean>; reason: string }[];
  // Validate the entire wire dispatch, then discard its protected reference/token.
  latest: { state: DispatchState; updated_at: number; reason: string | null } | null;
  coverage: { state: 'complete' | 'partial'; gaps: { source: string; reason: string }[] };
  freshness: { state: 'fresh' | 'stale' | 'unknown'; snapshot_at: Fact<number> };
};
export function notificationDefaults(): NotificationPreferences {
  return { generation: 0, enabled: false, categories: {
    decision: true, recovery_escalation: true, ci_failed: false, review_findings: false,
    re_check: false, merge: false, agent_complete: false, ready_stock_changed: false,
    loop_missed: false, loop_stuck: false, loop_disabled: false, loop_run_changed: false,
    recovery_changed: false, service_update: false, contract_changed: false, fleet_wait_changed: false,
  } };
}
export function selectNotificationCategory(current: NotificationCategories, category: NotificationCategory, enabled: boolean): NotificationCategories {
  return { ...current, [category]: enabled };
}
const STATES = ['off', 'unavailable', 'unsupported', 'setup_required', 'permission_denied', 'permission_revoked', 'ready', 'pending', 'accepted', 'failed', 'uncertain'] as const;
const DISPATCH_STATES = ['reserved', 'submitting', 'pending', 'accepted', 'failed', 'uncertain', 'cancelled'] as const;
const SOURCES = ['decisions', 'service_health', 'loop_watchdog', 'event_router', 'fleet', 'inventory', 'plan', 'loops', 'service_update'] as const;
const refused = (): never => { throw new Error('Invalid notification document'); };
function object(v: unknown, keys: readonly string[]): Map<string, unknown> {
  if (!(v instanceof Map) || v.size !== keys.length || !keys.every((k) => v.has(k))) return refused();
  return v;
}
function text(v: unknown): string { return typeof v === 'string' && v.length > 0 ? v : refused(); }
function bool(v: unknown): boolean { return typeof v === 'boolean' ? v : refused(); }
function integer(v: unknown, minimum = 0): number {
  if (v === null || typeof v !== 'object') return refused();
  const o = new Map(Object.entries(v));
  const n = o.get('value');
  return o.get('integer') === true && typeof n === 'number' && n >= minimum ? n : refused();
}
function enumeration<const T extends readonly string[]>(v: unknown, values: T): T[number] {
  for (const value of values) if (v === value) return value;
  return refused();
}
function pattern(v: unknown, re: RegExp): string { const s = text(v); return re.test(s) ? s : refused(); }
const id = (v: unknown): string => pattern(v, /^[A-Za-z0-9_][A-Za-z0-9_-]{0,127}$/);
const repository = (v: unknown): string => pattern(v, /^[a-z0-9][a-z0-9-]*\/[a-z0-9_.-][a-z0-9_.-]*$/);
function fact<T>(v: unknown, read: (x: unknown) => T): Fact<T> {
  if (v instanceof Map && v.has('known')) return { known: read(object(v, ['known']).get('known')) };
  return { unknown: text(object(v, ['unknown']).get('unknown')) };
}
function list(v: unknown): unknown[] { return Array.isArray(v) ? v : refused(); }
function preference(v: unknown): NotificationPreferences {
  const p = object(v, ['generation', 'enabled', 'categories']);
  const c = object(p.get('categories'), NOTIFICATION_CATEGORIES.map(([key]) => key));
  const categories = notificationDefaults().categories;
  for (const [key] of NOTIFICATION_CATEGORIES) categories[key] = bool(c.get(key));
  return { generation: integer(p.get('generation')), enabled: bool(p.get('enabled')), categories };
}
function reference(v: unknown): void {
  if (!(v instanceof Map) || v.size !== 1) return refused();
  if (v.has('decision')) {
    const r = object(v.get('decision'), ['repository', 'subject', 'comment_id', 'request_id', 'fingerprint']);
    repository(r.get('repository')); integer(r.get('comment_id'), 1);
    pattern(r.get('request_id'), /^[A-Za-z0-9][A-Za-z0-9_-]*$/); pattern(r.get('fingerprint'), /^[0-9a-f]{64}$/);
    const s = object(r.get('subject'), ['kind', 'number']); enumeration(s.get('kind'), ['issue', 'pull_request']); integer(s.get('number'), 1);
  } else if (v.has('incident')) {
    const r = object(v.get('incident'), ['repository', 'owner', 'source', 'subject', 'incident']);
    repository(r.get('repository')); id(r.get('owner')); enumeration(r.get('source'), ['service_health', 'loop_watchdog']); id(r.get('subject')); id(r.get('incident'));
  } else {
    const r = object(object(v, ['event']).get('event'), ['repository', 'source', 'subject', 'event_id', 'revision']);
    repository(r.get('repository')); enumeration(r.get('source'), SOURCES); id(r.get('subject')); id(r.get('event_id')); id(r.get('revision'));
  }
}
function dispatch(v: unknown): NotificationStatus['latest'] {
  if (v === null) return null;
  const d = object(v, ['submission', 'state', 'group_state', 'reserved_at', 'updated_at', 'outcome']);
  const s = object(d.get('submission'), ['dispatch_id', 'group', 'preference_generation', 'subscription_generation', 'payload']);
  pattern(s.get('dispatch_id'), /^[0-9a-f]{32}$/); reference(s.get('group'));
  integer(s.get('preference_generation')); integer(s.get('subscription_generation'));
  const payload = object(s.get('payload'), ['title', 'target_token']);
  if (payload.get('title') !== 'OpenWiz needs your attention') return refused();
  pattern(payload.get('target_token'), /^[0-9a-f]{64}$/);
  const state = enumeration(d.get('state'), DISPATCH_STATES);
  enumeration(d.get('group_state'), ['open', 'closed']);
  const reserved = integer(d.get('reserved_at')); const updated_at = integer(d.get('updated_at'));
  if (updated_at < reserved) return refused();
  let reason: string | null = null;
  if (d.get('outcome') !== null) {
    const o = object(d.get('outcome'), ['state', 'reason']);
    const outcome = enumeration(o.get('state'), ['pending', 'accepted', 'failed', 'uncertain']);
    if (state !== outcome) return refused();
    reason = text(o.get('reason'));
  } else if (['pending', 'accepted', 'failed', 'uncertain'].includes(state)) return refused();
  return { state, updated_at, reason };
}
function status(v: unknown): NotificationStatus {
  const s = object(v, ['state', 'reason', 'next', 'preferences', 'capability', 'subscription', 'sources', 'latest', 'coverage', 'freshness']);
  const cap = object(s.get('capability'), ['state', 'permission', 'reason', 'next']);
  const sub = object(s.get('subscription'), ['generation', 'state', 'binding_id', 'reason', 'next']);
  if (sub.get('binding_id') !== null) id(sub.get('binding_id'));
  if (sub.get('state') === 'ready' && sub.get('binding_id') === null) return refused();
  const c = object(s.get('coverage'), ['state', 'gaps']);
  const coverage = { state: enumeration(c.get('state'), ['complete', 'partial']), gaps: list(c.get('gaps')).map((v) => { const g = object(v, ['source', 'reason']); return { source: enumeration(g.get('source'), SOURCES), reason: text(g.get('reason')) }; }) };
  if ((coverage.state === 'complete') !== (coverage.gaps.length === 0)) return refused();
  const f = object(s.get('freshness'), ['state', 'snapshot_at']);
  const freshness = { state: enumeration(f.get('state'), ['fresh', 'stale', 'unknown']), snapshot_at: fact(f.get('snapshot_at'), integer) };
  if ((freshness.state === 'unknown') !== ('unknown' in freshness.snapshot_at) || (freshness.state === 'unknown' && coverage.state === 'complete')) return refused();
  const sources = list(s.get('sources')).map((v) => {
    const o = object(v, ['category', 'available', 'reason']);
    const category = enumeration(o.get('category'), NOTIFICATION_CATEGORIES.map(([key]) => key));
    const available = fact(o.get('available'), bool);
    if ('unknown' in available && coverage.state === 'complete') return refused();
    return { category, available, reason: text(o.get('reason')) };
  });
  if (sources.length !== NOTIFICATION_CATEGORIES.length || new Set(sources.map((s) => s.category)).size !== NOTIFICATION_CATEGORIES.length) return refused();
  return { state: enumeration(s.get('state'), STATES), reason: text(s.get('reason')), next: text(s.get('next')), preferences: preference(s.get('preferences')),
    capability: { state: enumeration(cap.get('state'), ['unavailable', 'unsupported', 'setup_required', 'ready']), permission: enumeration(cap.get('permission'), ['unknown', 'prompt', 'granted', 'denied', 'revoked', 'unsupported']), reason: text(cap.get('reason')), next: text(cap.get('next')) },
    subscription: { generation: integer(sub.get('generation')), state: enumeration(sub.get('state'), ['absent', 'ready', 'revoked', 'failed', 'unsupported']), reason: text(sub.get('reason')), next: text(sub.get('next')) }, sources, latest: dispatch(s.get('latest')), coverage, freshness };
}
function document<T>(raw: string, key: string, read: (v: unknown) => T): T | null {
  try {
    const d = object(parseJson(raw), ['schema', 'record']);
    if (d.get('schema') !== 'openwiz.notifications.v1') return null;
    return read(object(d.get('record'), [key]).get(key));
  } catch { return null; }
}
export const parseNotificationStatus = (raw: string): NotificationStatus | null => document(raw, 'status', status);
export const parseNotificationPreferences = (raw: string): NotificationPreferences | null => document(raw, 'preferences', preference);

export const notificationStateWord = (state: NotificationState | DispatchState): string => ({ off: 'Delivery off', unavailable: 'Unavailable', unsupported: 'Unsupported', setup_required: 'Setup required', permission_denied: 'Permission denied', permission_revoked: 'Permission revoked', ready: 'Ready', reserved: 'Reserved', submitting: 'Uncertain', pending: 'Pending', accepted: 'Accepted', failed: 'Failed', uncertain: 'Uncertain', cancelled: 'Cancelled' })[state];
export function notificationFailureWords(failure: Failure): string {
  if (failure.kind === 'signed-out') return 'Sign in again through your authenticated cockpit, then refresh. No preference change was confirmed.';
  if (failure.status === 403) return 'Access denied. Restore owner access, then refresh. No preference change was confirmed.';
  if (failure.kind === 'disconnected') return 'Reconnect, then refresh to check saved preferences. A lost write reply is uncertain; do not repeat it automatically.';
  if (failure.kind === 'busy') return 'Service busy. Refresh when available; do not repeat an unresolved preference change.';
  return 'Notification state unavailable. Refresh to check saved preferences before changing them again.';
}
export function notificationReadTime(at: number): string {
  return Number.isFinite(new Date(at).getTime()) ? new Date(at).toISOString() : 'time outside display range';
}
/** Current prerequisites only; this never establishes phone receipt. */
export function notificationReady(s: NotificationStatus, now: number): boolean {
  return s.preferences.enabled && s.capability.state === 'ready' && s.capability.permission === 'granted'
    && s.subscription.state === 'ready' && s.freshness.state === 'fresh' && 'known' in s.freshness.snapshot_at
    && now >= s.freshness.snapshot_at.known && now - s.freshness.snapshot_at.known <= 70_000;
}

// #2035: the owner's explicit actions over the actual preference route. The
// page never prompts or subscribes (the checked sources cannot name the
// native APIs); Enable stays inert while capability is unavailable or
// unsupported, as it is until T2 #2033's observed binding lands.
export type NotificationAction = { kind: 'enable' } | { kind: 'disable' } | { kind: 'save'; categories: NotificationCategories };
/**
 * The one write for an explicit action against the status it was read from,
 * or null when it may not be made. A pending write with the same body keeps
 * its operation id (a lost reply is repeated only as the same operation);
 * anything else gets a new id. Never retried automatically.
 */
export function notificationWrite(s: NotificationStatus, action: NotificationAction, pending: NotificationPreferenceWrite | null, newId: () => string): NotificationPreferenceWrite | null {
  if (action.kind === 'enable' && (s.capability.state === 'unavailable' || s.capability.state === 'unsupported')) return null;
  const enabled = action.kind === 'enable' ? true : action.kind === 'disable' ? false : s.preferences.enabled;
  const categories = { ...(action.kind === 'save' ? action.categories : s.preferences.categories) };
  const same = !!pending && pending.expected_generation === s.preferences.generation && pending.enabled === enabled
    && NOTIFICATION_CATEGORIES.every(([key]) => pending.categories[key] === categories[key]);
  return { operation_id: same && pending ? pending.operation_id : newId(), expected_generation: s.preferences.generation, enabled, categories };
}
/** A kept pending write read back from this tab's storage, strictly, or null. */
export function readPendingWrite(raw: string | null): NotificationPreferenceWrite | null {
  if (raw === null) return null;
  try {
    const w = object(parseJson(raw), ['operation_id', 'expected_generation', 'enabled', 'categories']);
    const c = object(w.get('categories'), NOTIFICATION_CATEGORIES.map(([key]) => key));
    const categories = notificationDefaults().categories;
    for (const [key] of NOTIFICATION_CATEGORIES) categories[key] = bool(c.get(key));
    return { operation_id: pattern(w.get('operation_id'), /^[0-9a-f]{32}$/), expected_generation: integer(w.get('expected_generation')), enabled: bool(w.get('enabled')), categories };
  } catch { return null; }
}
