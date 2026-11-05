import { useEffect, useId, useState } from 'react';
import type { Project, Received, Clock } from '../cockpit.ts';
import { freshNow, staleInMs } from '../cockpit.ts';
import type { Stock, ProjectStock, StockCoverage } from '../readyStock.ts';
import { stockCounts, stockWord, stockReadTime } from '../readyStock.ts';
import { StatusGlyph } from './StatusMark.tsx';

/** One read-only view over the cockpit snapshot; no delivery or work controls. */
export function ReadyStock({ stock, projects, assembledAt, received, disconnected = false }: {
  stock?: Stock; projects: Project[]; assembledAt: number; received: Received; disconnected?: boolean;
}) {
  const heading = useId();
  const [, tick] = useState(0);
  const now: Clock = { mono: typeof performance === 'undefined' ? received.mono : performance.now(), wall: Date.now() };
  useEffect(() => {
    if (!stock) return;
    const at = { mono: performance.now(), wall: Date.now() };
    const due = [stock.freshness, ...stock.projects.map((p) => p.freshness)].map((f) => staleInMs(f, assembledAt, received, at)).filter((ms): ms is number => ms !== null);
    const handles = [...new Set(due)].map((ms) => window.setTimeout(() => tick((n) => n + 1), ms));
    return () => { for (const h of handles) window.clearTimeout(h); };
  }, [stock, assembledAt, received]);
  const fresh = stock && freshNow(stock.freshness, assembledAt, received, now) && !disconnected;
  const known = stock && 'known' in stock.totals ? stock.totals.known : null;
  const title = !stock ? 'Unavailable' : disconnected ? 'Disconnected · last snapshot' : !fresh ? 'Stale or unread source' : stock.coverage.state === 'partial' ? 'Partial · totals unknown' : known ? stockWord(known.state) : 'Totals unknown';
  const name = (id: string) => { const p = projects.find((p) => p.id === id); return p && 'known' in p.name ? p.name.known : id; };
  return <section className="ck-agents" data-part="ready-stock" aria-labelledby={heading}>
    <h2 className="ck-title" id={heading}>Ready stock</h2>
    <p className="status-chip" role="status"><StatusGlyph tier={fresh && stock?.coverage.state === 'complete' ? 't2' : 't5'} />{title}</p>
    {stock ? <>
      <p className="meta">Factory · {known ? stockCounts(known) : 'Counts unknown'} · {stockReadTime(stock.freshness)}</p>
      <Gaps coverage={stock.coverage} />
      <div className="ck-groups">{stock.projects.map((p) => <ProjectRow key={p.project} p={p} name={name(p.project)} current={freshNow(p.freshness, assembledAt, received, now) && !disconnected} />)}</div>
    </> : <>
      <p className="meta">Ready stock is unavailable from this producer. Counts are unknown.</p>
      <div className="ck-groups">{projects.map((p) => <article key={p.id} data-stock-project={p.id}><h3 className="ck-group-title">{name(p.id)}</h3><p className="meta">Counts unknown · source time unknown</p></article>)}</div>
    </>}
    <p className="meta">Ticket builders are recorded starts or matching open PRs. Active sessions are shown separately below.</p>
  </section>;
}
function Gaps({ coverage }: { coverage: StockCoverage }) {
  return coverage.gaps.length ? <ul className="gaps">{coverage.gaps.map((g, i) => <li key={i}>{g.source} · {g.reason}</li>)}</ul> : null;
}
function ProjectRow({ p, name, current }: { p: ProjectStock; name: string; current: boolean }) {
  const c = 'known' in p.counts ? p.counts.known : null;
  const state = !current ? 'Stale or unread source' : p.coverage.state !== 'complete' ? 'Indeterminate · Partial' : c ? stockWord(c.state) : 'Counts unknown';
  return <article data-stock-project={p.project}>
    <h3 className="ck-group-title">{name}</h3>
    <p className="status-chip"><StatusGlyph tier={current && p.coverage.state === 'complete' ? 't2' : 't5'} />{state}</p>
    <p className="ck-wording">{c ? `${c.ready} ready · ${c.running} running` : 'Counts unknown'}</p>
    {c ? <p className="meta">{`${c.blocked} blocked · ${c.held} held · ${c.unapproved} unapproved · ${c.owner_wait} owner wait · ${c.capacity_wait} capacity wait · ${c.unknown} unknown`}</p> : null}
    <p className="meta">{stockReadTime(p.freshness)}</p>
    <Gaps coverage={p.coverage} />
    {p.last_good ? <p className="meta">Last good {new Date(p.last_good.snapshot_at).toISOString()} · {stockCounts(p.last_good.counts)}. Historical sample.</p> : null}
  </article>;
}
