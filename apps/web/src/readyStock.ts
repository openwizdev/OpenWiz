// Strict stock decoding and display only. No source, permission or work effects.
import type { Fact } from './envelope.ts';
import type { Freshness } from './cockpit.ts';
export type StockCounts = { ready: number; running: number; blocked: number; held: number; unapproved: number; owner_wait: number; capacity_wait: number; unknown: number; state: StockState };
export type StockState = 'fed' | 'low_stock' | 'running_dry' | 'no_builders' | 'indeterminate';
export type StockCoverage = { state: 'complete' | 'partial'; gaps: { source: string; reason: string }[] };
export type StockSample = { snapshot_at: number; counts: StockCounts };
export type ProjectStock = { project: string; coverage: StockCoverage; freshness: Freshness; counts: Fact<StockCounts>; last_good: StockSample | null };
export type Stock = { coverage: StockCoverage; freshness: Freshness; projects: ProjectStock[]; totals: Fact<StockCounts> };
const fail = (): never => { throw new Error('Invalid ready-stock projection'); };
function object(v: unknown, keys: string[]): Map<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return fail();
  const o = new Map(Object.entries(v));
  if (o.size !== keys.length || !keys.every((k) => o.has(k))) return fail();
  return o;
}
const text = (v: unknown): string => typeof v === 'string' && v.length > 0 ? v : fail();
const whole = (v: unknown): number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 ? v : fail();
function fact<T>(v: unknown, read: (x: unknown) => T): Fact<T> {
  if (v && typeof v === 'object' && Object.hasOwn(v, 'known')) return { known: read(object(v, ['known']).get('known')) };
  return { unknown: text(object(v, ['unknown']).get('unknown')) };
}
export const COUNT_KEYS = ['ready', 'running', 'blocked', 'held', 'unapproved', 'owner_wait', 'capacity_wait', 'unknown'] as const;
function counts(v: unknown): StockCounts {
  const o = object(v, [...COUNT_KEYS, 'state']);
  const c = { ready: whole(o.get('ready')), running: whole(o.get('running')), blocked: whole(o.get('blocked')), held: whole(o.get('held')), unapproved: whole(o.get('unapproved')), owner_wait: whole(o.get('owner_wait')), capacity_wait: whole(o.get('capacity_wait')), unknown: whole(o.get('unknown')) };
  const state: StockState = c.unknown > 0 ? 'indeterminate' : c.ready === 0 ? 'running_dry' : c.running === 0 ? 'no_builders' : BigInt(c.ready) >= 2n * BigInt(c.running) ? 'fed' : 'low_stock';
  if (o.get('state') !== state) return fail();
  return { ...c, state };
}
const SOURCES = ['decisions', 'service_health', 'loop_watchdog', 'event_router', 'fleet', 'inventory', 'plan', 'loops', 'service_update'];
function coverage(v: unknown): StockCoverage {
  const o = object(v, ['state', 'gaps']);
  const state = o.get('state');
  const list = o.get('gaps');
  if (!Array.isArray(list) || (state !== 'complete' && state !== 'partial')) return fail();
  const gaps = list.map((x) => {
    const g = object(x, ['source', 'reason']);
    if (!SOURCES.includes(text(g.get('source')))) return fail();
    return { source: text(g.get('source')), reason: text(g.get('reason')) };
  });
  if ((o.get('state') === 'complete') !== (gaps.length === 0)) return fail();
  return { state, gaps };
}
function freshness(v: unknown, assembled: number, cov: StockCoverage): Freshness {
  const o = object(v, ['state', 'snapshot_at']);
  const at = fact(o.get('snapshot_at'), whole);
  if (o.get('state') === 'unknown') {
    if (!('unknown' in at) || cov.state === 'complete') return fail();
    return { state: 'unknown', snapshot_at: at };
  }
  if (!('known' in at) || at.known > assembled) return fail();
  const state = assembled - at.known <= 70_000 ? 'fresh' : 'stale';
  if (o.get('state') !== state) return fail();
  return { state, snapshot_at: at };
}
export function readStock(v: unknown, assembled: number, projects: readonly string[]): Stock {
  const o = object(v, ['coverage', 'freshness', 'projects', 'totals']);
  const cov = coverage(o.get('coverage'));
  const fresh = freshness(o.get('freshness'), assembled, cov);
  const list = o.get('projects');
  if (!Array.isArray(list)) return fail();
  const seen = new Set<string>();
  const rows = list.map((x): ProjectStock => {
    const p = object(x, ['project', 'coverage', 'freshness', 'counts', 'last_good']);
    const id = text(p.get('project'));
    if (!/^[A-Za-z0-9_][A-Za-z0-9_-]{0,127}$/.test(id) || seen.has(id) || !projects.includes(id)) return fail();
    seen.add(id);
    const coverageP = coverage(p.get('coverage'));
    const freshP = freshness(p.get('freshness'), assembled, coverageP);
    const count = fact(p.get('counts'), counts);
    if (coverageP.state === 'complete' && ('unknown' in count || count.known.unknown > 0)) return fail();
    let last: StockSample | null = null;
    if (p.get('last_good') !== null) {
      const s = object(p.get('last_good'), ['snapshot_at', 'counts']);
      last = { snapshot_at: whole(s.get('snapshot_at')), counts: counts(s.get('counts')) };
      if (last.snapshot_at > assembled) return fail();
    }
    return { project: id, coverage: coverageP, freshness: freshP, counts: count, last_good: last };
  });
  if (seen.size !== projects.length) return fail();
  if (cov.state === 'complete' && rows.some((p) => p.coverage.state !== 'complete')) return fail();
  const totals = fact(o.get('totals'), counts);
  if ('known' in totals) {
    if (cov.state !== 'complete' || fresh.state !== 'fresh' || rows.some((p) => p.coverage.state !== 'complete' || p['freshness'].state !== 'fresh' || !('known' in p['counts']))) return fail();
    for (const key of COUNT_KEYS) {
      const sum = rows.reduce((n, p) => n + ('known' in p['counts'] ? BigInt(p['counts'].known[key]) : 0n), 0n);
      if (sum !== BigInt(totals.known[key])) return fail();
    }
  }
  // Factory age may never be newer than a required project's source age.
  if (fresh.state !== 'unknown' && rows.some((p) => p['freshness'].state === 'unknown' || p['freshness'].snapshot_at.known < fresh.snapshot_at.known)) return fail();
  return { coverage: cov, freshness: fresh, projects: rows, totals };
}
export const stockWord = (state: StockState): string => ({ fed: 'Fed', low_stock: 'Low stock', running_dry: 'Running dry', no_builders: 'No builders', indeterminate: 'Indeterminate' })[state];
export const stockCounts = (c: StockCounts): string => `${c.ready} ready · ${c.running} running · ${c.blocked} blocked · ${c.held} held · ${c.unapproved} unapproved · ${c.owner_wait} owner wait · ${c.capacity_wait} capacity wait · ${c.unknown} unknown`;

export function stockReadTime(f: Stock['freshness']): string {
  return f.state === 'unknown' ? 'source time unknown' : `source read ${new Date(f.snapshot_at.known).toISOString()}`;
}
