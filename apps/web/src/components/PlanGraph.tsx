// The plan graph page (0.0.11 U3, #653), drawn to the design target
// in the approved #647 structure: the blocking chain on top, each version's tickets
// in state columns with counts, hover or focus to preview a ticket's direct
// prerequisites and dependents, tap to pin that trace, and versions that fold
// keeping every count. Lists on the phone, the graph with rails on the PC.
//
// One read, `GET /api/v1/plan` (src/plan.ts), through its own single-flight
// lane, kept across navigation. Read only: a ticket opens its own GitHub
// issue or pull request, from the read's checked links, and nothing else.

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';

import { browserFetch, readPlanView, serverDone } from '../api.ts';
import type { Failure } from '../api.ts';
import { staleInMs } from '../cockpit.ts';
import type { Clock, Received } from '../cockpit.ts';
import type { Tier } from '../markers.ts';
import {
  chainTickets,
  COLUMN_ORDER,
  COLUMN_TITLES,
  countWords,
  emptyWords,
  groups,
  inColumn,
  issueLink,
  neighboursIn,
  prLink,
  provenance,
  relationTo,
  relationWords,
  stateWord,
  summary,
  titleOf,
  traceCounts,
  traceOf,
  yoursWords,
} from '../plan.ts';
import type { Column, Group, Plan, PlanOutcome, Provenance, Ticket, Trace } from '../plan.ts';
import { Lane, Poller } from '../poller.ts';
import type { Timers, Visibility } from '../poller.ts';
import { clockText } from '../present.ts';
import { FLEET_TIMING, TIMING } from '../timing.ts';
import type { Connection } from '../viewer.ts';
import { ChevronIcon } from './Icons.tsx';
import { ConnectionGlyph, Notice } from './Status.tsx';
import { StatusGlyph, StatusMark } from './StatusMark.tsx';

const timers: Timers = {
  setTimeout: (fn, ms) => window.setTimeout(fn, ms),
  clearTimeout: (handle) => {
    if (typeof handle === 'number') window.clearTimeout(handle);
  },
};

const visibility: Visibility = {
  hidden: () => document.visibilityState === 'hidden',
  subscribe: (onChange) => {
    document.addEventListener('visibilitychange', onChange);
    return () => document.removeEventListener('visibilitychange', onChange);
  },
};

const clockNow = (): Clock => ({ mono: performance.now(), wall: Date.now() });
/** The phone layout's width, as the shell's (styles: max-width 899px). */
const PHONE = '(max-width: 899px)';
/** The phone shows this many chain links before "Show N more links". */
const PHONE_LINKS = 4;

type Snapshot = { plan: Plan; received: Received };
type View = { last: Snapshot | null; failure: Failure | null; reading: boolean; seq: number };

/** The page-lifetime state, kept across navigation: one read lane, and the last snapshot shown. */
const kept: { lane: Lane | null; view: View | null } = { lane: null, view: null };

/** Re-renders when a fresh read turns stale on this clock, and when the page is shown again. */
function useAging(last: Snapshot | null): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!last) return;
    const ms = staleInMs(last.plan.freshness, last.plan.snapshot_at, last.received, clockNow());
    if (ms === null) return;
    const h = window.setTimeout(() => setTick((n) => n + 1), ms);
    return () => window.clearTimeout(h);
  }, [last]);
  useEffect(() => visibility.subscribe(() => setTick((n) => n + 1)), []);
}

/**
 * The page. `onLoops` is #549's seam: the shell's handler that shows the Loops
 * screen, which the phone reaches only from here (MD9 keeps five tabs). With
 * none, no Loops link is drawn.
 */
export function PlanGraph({ onConnection, onLoops }: { onConnection?: (c: Connection) => void; onLoops?: () => void }) {
  const [lane] = useState(() => (kept.lane ??= new Lane()));
  const [view, setView] = useState<View>(() => (kept.view ? { ...kept.view, reading: true } : { last: null, failure: null, reading: true, seq: 0 }));
  const poller = useRef<Poller<PlanOutcome> | null>(null);
  useAging(view.last);

  useEffect(() => {
    let current: View = kept.view ? { ...kept.view, reading: true } : { last: null, failure: null, reading: true, seq: 0 };
    const update = (next: View) => {
      current = next;
      kept.view = next;
      setView(next);
    };
    const loop = new Poller<PlanOutcome>({
      lane,
      intervalMs: FLEET_TIMING.intervalMs,
      timeoutMs: TIMING.requestTimeoutMs,
      holdMs: TIMING.laneHoldMs,
      backoffMs: FLEET_TIMING.backoffMs,
      timers,
      visibility,
      read: (signal) => {
        update({ ...current, reading: true });
        return readPlanView(browserFetch, signal);
      },
      settle: (o) => ({ ok: o.kind === 'ok', confirmed: o.kind === 'ok' || serverDone(o), retryAfterMs: o.kind === 'busy' ? o.retryAfterMs : null }),
      deliver: (o) => update(o.kind === 'ok' ? { last: { plan: o.envelope, received: clockNow() }, failure: null, reading: false, seq: current.seq + 1 } : { ...current, failure: o, reading: false }),
      onTimeout: () => update({ ...current, failure: { kind: 'disconnected', cause: 'timeout', status: null } }),
    });
    poller.current = loop;
    loop.start();
    return () => {
      loop.retire();
      poller.current = null;
    };
  }, [lane]);

  const now = clockNow();
  const last = view.last;
  const prov = last ? provenance(last.plan, last.received, now, (ms) => clockText(ms, new Date(now.wall))) : null;
  // Only a fresh read is live; stale or unknown freshness is not.
  const conn: Connection = view.failure?.kind ?? (last === null ? 'reading' : prov?.state === 'stale' || prov?.state === 'unknown' ? 'stale' : 'live');
  useEffect(() => onConnection?.(conn), [conn, onConnection]);

  return (
    <section className="plan" data-part="plan" data-snapshot-seq={view.seq} aria-labelledby="pl-title">
      {last && prov ? (
        <PlanBody onLoops={onLoops} plan={last.plan} received={last.received} now={now} prov={prov} reading={view.reading} failure={view.failure} onRetry={() => poller.current?.refresh()} />
      ) : (
        <>
          <header className="pl-head">
            <h1 id="pl-title" className="pl-page-title" tabIndex={-1}>Plan</h1>
            {onLoops ? <div className="pl-controls"><LoopsLink onLoops={onLoops} /></div> : null}
          </header>
          {view.failure ? (
            <div role="status"><Notice sessionState failure={view.failure} lastGoodAt={null} now={new Date(now.wall)} onRetry={() => poller.current?.refresh()} /></div>
          ) : (
            <div className="pl-loading" data-part="plan-loading">
              <p className="meta" role="status">reading the plan…</p>
              <div className="pl-skeleton" aria-hidden="true"><span /><span /><span /></div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

type BodyProps = { onLoops: (() => void) | undefined; plan: Plan; received: Received; now: Clock; prov: Provenance; reading: boolean; failure: Failure | null; onRetry: () => void };

function PlanBody({ onLoops, plan, received, now, prov, reading, failure, onRetry }: BodyProps) {
  const all = groups(plan);
  const [filter, setFilter] = useState<string | null>(null);
  // Folding: the PC starts with every version open, the phone with each folded (#647).
  const [openByDefault, setOpenByDefault] = useState(() => typeof window === 'undefined' || !window.matchMedia(PHONE).matches);
  const [overrides, setOverrides] = useState<ReadonlyMap<string, boolean>>(new Map());
  const [pinned, setPinned] = useState<number | null>(null);
  const [preview, setPreview] = useState<number | null>(null);
  const [chainOpen, setChainOpen] = useState(false);
  const [gapsOpen, setGapsOpen] = useState(false);
  const pinnedFrom = useRef<HTMLElement | null>(null);
  const shownFilter = filter !== null && all.some((g) => g.key === filter) ? filter : null;
  const isOpen = (key: string) => overrides.get(key) ?? openByDefault;
  const pinnedTrace = pinned === null ? null : traceOf(plan, pinned);
  const previewTrace = preview === null ? null : traceOf(plan, preview);
  // A pinned trace holds until cleared; with none, hover or focus previews one.
  const trace = pinnedTrace ?? previewTrace;
  const empty = emptyWords(plan, received, now);

  const clear = () => {
    const from = pinnedFrom.current;
    setPinned(null);
    setPreview(null);
    pinnedFrom.current = null;
    // Back to the ticket it was pinned from (or that ticket's card, if a filter or fold redrew it);
    // with none on screen, to the page's title, never to nowhere.
    const shown = (el: HTMLElement | null | undefined): el is HTMLElement => !!el && el.isConnected && el.getClientRects().length > 0;
    const again = pinned === null ? null : document.querySelector<HTMLElement>(`[data-card-ticket="${pinned}"]`);
    const target = shown(from) ? from : shown(again) ? again : document.getElementById('pl-title');
    target?.focus({ preventScroll: true });
  };
  const pin = (t: Ticket, from: HTMLElement) => {
    pinnedFrom.current = from;
    setPinned(t.number);
  };
  const reset = () => {
    setOpenByDefault(true);
    setOverrides(new Map());
    setFilter(null);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === 'Escape' && pinned !== null) {
      e.preventDefault();
      clear();
    }
  };
  const cardProps = { trace, pinned, onPin: pin, onPreview: setPreview };
  const shownGroups = shownFilter === null ? all : all.filter((g) => g.key === shownFilter);

  return (
    <div className="pl-body" onKeyDown={onKeyDown}>
      <header className="pl-head">
        <h1 id="pl-title" className="pl-page-title" tabIndex={-1}>Plan</h1>
        <div className="pl-controls">
          <label className="pl-filter">
            <span className="pl-filter-label">Version</span>
            <select value={shownFilter ?? ''} onChange={(e) => setFilter(e.target.value === '' ? null : e.target.value)}>
              <option value="">All versions</option>
              {all.map((g) => <option key={g.key} value={g.key}>{g.name}</option>)}
            </select>
          </label>
          <button type="button" className="btn" data-part="plan-reset" onClick={reset}>Reset</button>
          {onLoops ? <LoopsLink onLoops={onLoops} /> : null}
        </div>
        <div className="pl-prov" data-part="provenance" data-state={prov.state}>
          <p className={`status-chip coverage-chip${prov.partial ? ' is-partial' : ''}`} role="status">
            {prov.state === 'stale' || prov.state === 'unknown' ? <ConnectionGlyph connection="stale" /> : <StatusGlyph tier={prov.partial ? 't5' : 't2'} />}
            <span className="chip-state" data-part="provenance-words">{prov.words}</span>
            {reading ? <span className="meta"> · reading…</span> : null}
          </p>
          <p className="pl-summary meta" data-part="plan-summary">{summary(plan)}</p>
          {plan.coverage.state === 'partial' ? (
            <>
              <p className="pl-gap-summary" data-part="gap-summary">{plan.coverage.gaps.map((g, i) => <bdi key={i}>{i > 0 ? ' · ' : ''}{g.detail}</bdi>)}</p>
              <button type="button" className="btn quiet" aria-expanded={gapsOpen} onClick={() => setGapsOpen((o) => !o)}>Details <ChevronIcon open={gapsOpen} /></button>
              {gapsOpen ? <ul className="gaps" data-part="gaps">{plan.coverage.gaps.map((g, i) => <li key={i}><bdi>{`${g.kind} · ${g.detail}`}</bdi></li>)}</ul> : null}
            </>
          ) : null}
        </div>
      </header>
      <div role="status">{failure ? <Notice failure={failure} lastGoodAt={plan.freshness.state === 'unknown' ? null : plan.freshness.snapshot_at.known} now={new Date(now.wall)} onRetry={onRetry} /> : null}</div>
      {pinnedTrace ? <TraceBar trace={pinnedTrace} all={all} onClear={clear} /> : null}
      {empty !== null ? <p className="pl-empty" data-part="plan-empty">{empty}</p> : (
        <>
          <ChainStrip plan={plan} open={chainOpen} onOpen={() => setChainOpen(true)} card={cardProps} />
          <Versions groups={shownGroups} isOpen={isOpen} trace={trace} card={cardProps}
            onToggle={(key) => setOverrides((o) => new Map(o).set(key, !isOpen(key)))} />
        </>
      )}
    </div>
  );
}

/** Loops, from the plan (Jake's #549 approval: reached from Plan, never a sixth tab). */
function LoopsLink({ onLoops }: { onLoops: () => void }) {
  return <button type="button" className="btn" data-part="plan-loops" onClick={onLoops}>Loops</button>;
}

type CardProps = { trace: Trace | null; pinned: number | null; onPin: (t: Ticket, from: HTMLElement) => void; onPreview: (n: number | null) => void };

const TIERS: Readonly<Record<Column, Tier>> = { done: 't2', building: 't3', needs_you: 't1', waiting: 't4' };
const tierOf = (t: Ticket): Tier => ('known' in t.column ? TIERS[t.column.known] : 't5');

/** One ticket: its number, title, state word with its mark, ownership, and its relation to the trace. Press pins its trace. */
function Card({ t, card, extra, chain = false }: { t: Ticket; card: CardProps; extra?: ReactNode; chain?: boolean }) {
  const relation = relationTo(card.trace, t);
  const words = card.trace ? relationWords(card.trace, relation) : null;
  const yours = 'known' in t.yours ? (t.yours.known ? 'yours' : null) : 'owner unknown';
  const tier = tierOf(t);
  return (
    <button type="button" className={`pl-card ${tier}`} data-card-ticket={chain ? undefined : t.number} data-chain-ticket={chain ? t.number : undefined}
      data-relation={relation ?? undefined} aria-pressed={card.pinned === t.number}
      onClick={(e) => card.onPin(t, e.currentTarget)}
      onPointerEnter={() => card.onPreview(t.number)} onPointerLeave={() => card.onPreview(null)}
      onFocus={() => card.onPreview(t.number)} onBlur={() => card.onPreview(null)}>
      <span className="pl-num">#{t.number}</span>
      <span className="pl-card-title" data-part="ticket-title">{titleOf(t)}</span>
      <span className="pl-meta">
        <span className={`pl-mark ${tier}`}><StatusMark tier={tier} word={stateWord(t)} /></span>
        {yours !== null ? <span className="pl-yours" data-part="yours">{yours}</span> : null}
        {words !== null ? <span className="pl-rel" data-part="relation">{words}</span> : null}
      </span>
      {extra}
    </button>
  );
}

/** The pinned trace: what it waits on and what waits on it, across every version, folded or filtered; and its links. */
function TraceBar({ trace, all, onClear }: { trace: Trace; all: Group[]; onClear: () => void }) {
  const t = trace.ticket;
  const where = (x: Ticket) => all.find((g) => g.tickets.includes(x))?.name ?? null;
  const list = (f: Trace['waitsOn'], none: string) => ('known' in f
    ? f.known.tickets.length + f.known.missing.length === 0 ? <p className="meta">{none}</p> : <ul>
      {f.known.tickets.map((x) => <li key={x.number}><span className="pl-num">#{x.number}</span> <bdi>{titleOf(x)}</bdi>{where(x) !== null && where(x) !== where(t) ? <span className="meta"> · {where(x)}</span> : null}</li>)}
      {f.known.missing.map((n) => <li key={n}><span className="pl-num">#{n}</span> <span className="meta">not read</span></li>)}
    </ul>
    : <p className="meta">unknown ({f.unknown})</p>);
  const issue = issueLink(t);
  const pr = prLink(t);
  return (
    <section className="pl-trace" data-part="trace" aria-label={`Tracing #${t.number}`}>
      <div className="pl-trace-head">
        <p className="pl-trace-title"><span>Tracing </span><span className="pl-num">#{t.number}</span> <bdi>{titleOf(t)}</bdi> <span className="pl-trace-counts" data-part="trace-counts">— {traceCounts(trace)}</span></p>
        <button type="button" className="btn" data-part="clear-trace" onClick={onClear}>Clear trace</button>
      </div>
      <div className="pl-trace-detail">
        <div><h2 className="pl-trace-label">Waits on</h2>{list(trace.waitsOn, 'nothing')}</div>
        <div><h2 className="pl-trace-label">Waiting on it</h2>{list(trace.waitedOnBy, 'nothing')}</div>
        <p className="pl-links">
          {issue !== null ? <a className="btn" href={issue} target="_blank" rel="noopener noreferrer" data-part="open-issue">Open issue #{t.number}</a> : <span className="meta">issue link unknown</span>}
          {pr !== null ? <a className="btn" href={pr.url} target="_blank" rel="noopener noreferrer" data-part="open-pr">Open pull request #{pr.number}</a> : null}
        </p>
      </div>
    </section>
  );
}

/** The chain holding up the most work: root first, each link waiting on the one before. */
function ChainStrip({ plan, open, onOpen, card }: { plan: Plan; open: boolean; onOpen: () => void; card: CardProps }) {
  const c = plan.critical_chain;
  if (!('known' in c)) return <section className="pl-chain" data-part="chain"><h2 className="pl-section-title">Blocking chain</h2><p className="pl-chain-note" data-part="chain-unknown">Blocking chain unknown: {c.unknown}</p></section>;
  if (c.known === null) return <section className="pl-chain" data-part="chain"><h2 className="pl-section-title">Blocking chain</h2><p className="pl-chain-note" data-part="chain-none">Nothing is blocking</p></section>;
  const chain = c.known;
  const links = chainTickets(plan, chain);
  const more = Math.max(0, links.length - PHONE_LINKS);
  const holds = `${chain.blocked_count} ${chain.blocked_count === 1 ? 'ticket' : 'tickets'}`;
  return (
    <section className={`pl-chain${open ? ' is-open' : ''}`} data-part="chain" aria-labelledby="pl-chain-title">
      <h2 id="pl-chain-title" className="pl-section-title">Blocking chain <span className="pl-holds">holds {holds}</span></h2>
      <ol className="pl-chain-list" aria-label="Blocking chain, root first; each waits on the one before">
        {links.map((t, i) => (
          <li key={t.number} className={`pl-link${i >= PHONE_LINKS ? ' is-more' : ''}`}>
            {i > 0 ? <span className="pl-arrow" aria-hidden="true"><span className="pl-arrow-pc">←</span><span className="pl-arrow-phone">↑ waits on</span></span> : null}
            <Card t={t} card={card} chain extra={i === 0 ? <span className="pl-hold" data-part="holding">Holding {holds}</span> : null} />
          </li>
        ))}
      </ol>
      {more > 0 && !open ? <button type="button" className="btn pl-more" data-part="chain-more" onClick={onOpen}>Show {more} more {more === 1 ? 'link' : 'links'}</button> : null}
    </section>
  );
}

/** Each version: a header that folds, keeping its name and every count; open, its tickets by state. */
function Versions({ groups: shown, isOpen, trace, card, onToggle }: { groups: Group[]; isOpen: (key: string) => boolean; trace: Trace | null; card: CardProps; onToggle: (key: string) => void }) {
  const root = useRef<HTMLDivElement | null>(null);
  const openKeys = shown.filter((g) => isOpen(g.key)).map((g) => g.key).join();
  // As text, so the rails are measured again only when the edges themselves change.
  const edges = shown.flatMap((g) => g.tickets.flatMap((t) => ('known' in t.blockers ? t.blockers.known.map((prerequisite) => `${t.number}>${prerequisite}`) : []))).join(',');
  return (
    <section className="pl-versions" data-part="versions" aria-labelledby="pl-versions-title">
      <h2 id="pl-versions-title" className="pl-section-title pl-versions-title">Versions</h2>
      <div ref={root} className="pl-sheets">
        {shown.map((g) => <Sheet key={g.key} g={g} open={isOpen(g.key)} trace={trace} card={card} onToggle={() => onToggle(g.key)} />)}
        <Rails root={root} edges={edges} trace={trace} layout={`${openKeys}|${shown.length}`} />
      </div>
    </section>
  );
}

function Sheet({ g, open, trace, card, onToggle }: { g: Group; open: boolean; trace: Trace | null; card: CardProps; onToggle: () => void }) {
  const id = `pl-sheet-${g.key.replace(/[^a-z0-9]/gi, '-')}`;
  const near = trace && !open ? neighboursIn(trace, g) : null;
  const tags: string[] = [];
  if (trace && near) {
    if (near.dependents > 0) tags.push(`${near.dependents} ${near.dependents === 1 ? 'waits' : 'wait'} on #${trace.ticket.number}`);
    if (near.prerequisites > 0) tags.push(`#${trace.ticket.number} waits on ${near.prerequisites}`);
  }
  const columns: (Column | null)[] = g.counts.unknown > 0 ? [...COLUMN_ORDER, null] : [...COLUMN_ORDER];
  const counts = countWords(g.counts);
  return (
    <section className={`pl-sheet${open ? ' is-open' : ''}`} data-part="version" data-lane={g.key} aria-labelledby={`${id}-name`}>
      <h3 className="pl-sheet-head">
        <button type="button" className="pl-fold" aria-expanded={open} aria-controls={id} onClick={onToggle}>
          <ChevronIcon open={open} />
          <span id={`${id}-name`} className="pl-sheet-name" data-part="version-name">{g.name}</span>
          {tags.map((tag) => <span key={tag} className="pl-near" data-part="near">{tag}</span>)}
          <span className="pl-counts" data-part="counts">
            {counts.map((w, i) => <span key={w} className={i === 2 && g.counts.needs_you > 0 ? 'pl-count needs' : 'pl-count'}>{w}</span>)}
            <span className="pl-count pl-count-yours">{yoursWords(g.counts)}</span>
          </span>
        </button>
      </h3>
      {g.why !== null ? <p className="meta pl-why">{g.why}</p> : null}
      <div id={id} className="pl-columns" hidden={!open}>
        {g.tickets.length === 0 ? <p className="pl-none" data-part="no-tickets">No tickets</p> : columns.map((col) => {
          const list = inColumn(g, col);
          const title = col === null ? 'Unknown' : COLUMN_TITLES[col];
          const tier: Tier = col === null ? 't5' : TIERS[col];
          return (
            <div key={col ?? 'unknown'} className={`pl-column col-${col ?? 'unknown'}`} data-column={col ?? 'unknown'}>
              <h4 className="pl-column-title"><span className={`pl-mark ${tier}`} aria-hidden="true"><StatusGlyph tier={tier} /></span>{title} <span className="pl-column-count">{list.length}</span></h4>
              {list.length === 0 ? <p className="pl-none">None</p> : <ul className="pl-cards">{list.map((t) => <li key={t.number}><Card t={t} card={card} /></li>)}</ul>}
            </div>
          );
        })}
      </div>
    </section>
  );
}

type Rail = { key: string; d: string; traced: boolean };

/**
 * Neutral rails on the PC for every prerequisite edge whose two tickets are
 * open on screen, across versions too (the #647 graph); the trace's own edges
 * are drawn over them, stronger. Each arrowhead points at the prerequisite, as
 * the chain strip's arrows do. Folded or filtered-out neighbours are named in
 * the trace instead. Phones show none: relation words carry the trace.
 */
function Rails({ root, edges, trace, layout }: { root: { current: HTMLDivElement | null }; edges: string; trace: Trace | null; layout: string }) {
  const [rails, setRails] = useState<Rail[]>([]);
  const [size, setSize] = useState(0);
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setSize(Math.round(el.getBoundingClientRect().width * 10_000 + el.getBoundingClientRect().height)));
    observer.observe(el);
    return () => observer.disconnect();
  }, [root]);
  const traced = trace?.ticket.number ?? null;
  useLayoutEffect(() => {
    const el = root.current;
    if (!el || window.matchMedia(PHONE).matches) { setRails((old) => (old.length === 0 ? old : [])); return; }
    const box = el.getBoundingClientRect();
    const rects = new Map<number, { left: number; right: number; mid: number } | null>();
    const rect = (n: number) => {
      if (rects.has(n)) return rects.get(n) ?? null;
      const card = el.querySelector<HTMLElement>(`[data-card-ticket="${n}"]`);
      const r = card && !card.closest('[hidden]') ? card.getBoundingClientRect() : null;
      const out = r ? { left: r.left - box.left, right: r.right - box.left, mid: r.top - box.top + r.height / 2 } : null;
      rects.set(n, out);
      return out;
    };
    const base: Rail[] = [];
    const strong: Rail[] = [];
    for (const [dependent, prerequisite] of edges === '' ? [] : edges.split(',').map((e) => e.split('>').map(Number))) {
      if (dependent === undefined || prerequisite === undefined) continue;
      const from = rect(dependent);
      const to = rect(prerequisite);
      if (!from || !to) continue;
      let d: string;
      // From the waiting ticket to its prerequisite, which gets the arrowhead.
      if (to.right <= from.left) {
        const x = Math.round((to.right + from.left) / 2);
        d = `M${from.left} ${from.mid}H${x}V${to.mid}H${to.right + 2}`;
      } else if (to.left >= from.right) {
        const x = Math.round((from.right + to.left) / 2);
        d = `M${from.right} ${from.mid}H${x}V${to.mid}H${to.left - 2}`;
      } else {
        const x = Math.min(from.left, to.left) - 12;
        d = `M${from.left} ${from.mid}H${x}V${to.mid}H${to.left - 2}`;
      }
      const isTraced = traced !== null && (dependent === traced || prerequisite === traced);
      (isTraced ? strong : base).push({ key: `${dependent}>${prerequisite}`, d, traced: isTraced });
    }
    const next = [...base, ...strong];
    // Measured after every render (a refresh can move tickets between columns with the same edges);
    // set only when a rail changed, so this never loops.
    setRails((old) => (old.length === next.length && old.every((r, i) => r.key === next[i]?.key && r.d === next[i]?.d && r.traced === next[i]?.traced) ? old : next));
  });
  if (rails.length === 0) return null;
  return (
    <svg className="pl-rails" data-part="rails" aria-hidden="true">
      <defs>
        <marker id="pl-arrow" className="pl-arrowhead" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0 8 4 0 8Z" fill="currentColor" /></marker>
        <marker id="pl-arrow-traced" className="pl-arrowhead traced" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0 8 4 0 8Z" fill="currentColor" /></marker>
      </defs>
      {rails.map((r) => <path key={r.key} className={r.traced ? 'pl-rail traced' : 'pl-rail'} data-rail={r.key} data-traced={r.traced ? 'true' : undefined} d={r.d} fill="none" stroke="currentColor" strokeWidth={r.traced ? 2 : 1} markerEnd={r.traced ? 'url(#pl-arrow-traced)' : 'url(#pl-arrow)'} />)}
    </svg>
  );
}

/** The plan's navigation icon: a small dependency graph. */
export function PlanIcon() {
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="12" cy="5" r="2.5" /><circle cx="5" cy="19" r="2.5" /><circle cx="19" cy="19" r="2.5" /><path d="M12 7.5v4m0 0-5.5 5.3m5.5-5.3 5.5 5.3" /></svg>;
}
