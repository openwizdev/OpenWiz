// Page 1 of the cockpit (0.0.10 T3, #536): Needs you on top, numbered in
// the server's order (oldest first), each answered right there; the agent
// grid below, by project and fleet, with the unplaced last; the project and
// machine filters; and the freshness line. One read, `GET /api/v1/cockpit`
// (src/cockpit.ts), through its own single-flight lane.
//
// An answer is one send through the composer's send path, as the orchestrator
// ruled on #536: the owner chooses Yes or No, sees what a send would do (the
// core's preview), and confirms; a risky item asks a second time first. Each
// item keeps its own op id and attempts (src/cockpit.ts's `itemStorage`), so a
// double click, a held key, a retry or a reload never sends twice. Nothing is
// sent but by the owner's press, and no result is retried on its own.

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { KeyboardEvent, MouseEvent } from 'react';

import { browserFetch, readCockpitView, serverDone } from '../api.ts';
import type { Failure } from '../api.ts';
import {
  actionable,
  agentGroups,
  agentNeedsYou,
  agentsShown,
  allGaps,
  bindingOf,
  choiceOf,
  clearRecord,
  answerText,
  armedLabel,
  itemStorage,
  machines,
  needKey,
  needsShown,
  nothingNeedsYou,
  freshNow,
  projectName,
  readRecord,
  staleInMs,
  writeRecord,
} from '../cockpit.ts';
import type { Agent, AnswerRecord, AnswerRequest, Choice, Clock, Cockpit as CockpitData, CockpitOutcome, Filter, Need, Received } from '../cockpit.ts';
import { crumbs, narrow, openKeys, scopeOf, TOP } from '../command.ts';
import type { Opened, Outcome, Scope } from '../command.ts';
import { browserStorage, Composers, EMPTY, isUnsettled, keyOf, locked, newOpId } from '../composer.ts';
import type { PreviewSaid, Press, StorageLike, ThreadState } from '../composer.ts';
import type { Tier } from '../markers.ts';
import { Lane, Poller } from '../poller.ts';
import type { Timers, Visibility } from '../poller.ts';
import { ageText, clockText, factText, unknownText } from '../present.ts';
import { FLEET_TIMING, TIMING } from '../timing.ts';
import type { Connection } from '../viewer.ts';
import { CommandBar, ScopeCrumbs } from './CommandBar.tsx';
import { ChevronIcon } from './Icons.tsx';
import { ConnectionGlyph, Notice } from './Status.tsx';
import { StatusGlyph, StatusMark } from './StatusMark.tsx';
import { ReadyStock } from './ReadyStock.tsx';

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

type Snapshot = { cockpit: CockpitData; received: Received };
type View = { last: Snapshot | null; failure: Failure | null; reading: boolean; seq: number };

/**
 * One item's answers: its own composer state and storage, apart from the
 * orchestrator's message box, and a signal for its record's changes.
 */
type ItemAnswers = { composers: Composers; storage: StorageLike | null; subscribe(fn: () => void): () => void; notify(): void; version(): number };

/**
 * The cockpit's page-lifetime state, kept across navigation (#1560's review,
 * R1 and R2): one read lane, so leaving and reopening the page never starts a
 * second read while one is out; the last snapshot shown; and one owner of
 * each item's answers, so a send made before leaving settles in the page
 * that is open when its answer comes.
 */
const kept: { lane: Lane | null; view: View | null; answers: Map<string, ItemAnswers> } = { lane: null, view: null, answers: new Map() };

function answersFor(key: string): ItemAnswers {
  const known = kept.answers.get(key);
  if (known) return known;
  const storage = itemStorage(browserStorage(), key);
  const listeners = new Set<() => void>();
  let version = 0;
  const made: ItemAnswers = {
    composers: new Composers({ fetch: browserFetch, storage, timers, newOpId: () => newOpId() }),
    storage,
    subscribe: (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    notify: () => {
      version++;
      for (const fn of [...listeners]) fn();
    },
    version: () => version,
  };
  kept.answers.set(key, made);
  return made;
}

/**
 * Re-renders when each fresh part turns stale on this clock, and every 30 s
 * while waiting ages count. Each part's timer is set once per snapshot, so the
 * age tick never moves it.
 */
function useAging(last: Snapshot | null): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!last) return;
    const c = last.cockpit;
    const now = clockNow();
    const parts = [c.projects.freshness, c.needs_you.freshness, c.agents.freshness, ...c.projects.items.map((p) => p.orchestrator.freshness)];
    const due = new Set(parts.map((f) => staleInMs(f, c.snapshot_at, last.received, now)).filter((ms): ms is number => ms !== null));
    const handles = [...due].map((ms) => window.setTimeout(() => setTick((n) => n + 1), ms));
    const ages = c.needs_you.items.some((n) => 'known' in n.age_ms) ? window.setInterval(() => setTick((n) => n + 1), 30_000) : null;
    return () => {
      for (const h of handles) window.clearTimeout(h);
      if (ages !== null) window.clearInterval(ages);
    };
  }, [last]);
  useEffect(() => visibility.subscribe(() => setTick((n) => n + 1)), []);
}

/**
 * The page. `onReply` opens the orchestrator's own message box, prefilled, for
 * a reply in the owner's words (C5's composer; it never sends by itself).
 * `request` is #537's seam: the command bar's `y` or `approve` opens the
 * item's answer exactly as pressing Yes would; the owner's press still sends.
 */
export function Cockpit({ onConnection, onReply, request = null }: { onConnection?: (c: Connection) => void; onReply?: (target: string, prefill: string) => void; request?: AnswerRequest | null }) {
  const [lane] = useState(() => (kept.lane ??= new Lane()));
  const [view, setView] = useState<View>(() => (kept.view ? { ...kept.view, reading: true } : { last: null, failure: null, reading: true, seq: 0 }));
  const [filter, setFilter] = useState<Filter>({ project: null, machine: null });
  const [gapsOpen, setGapsOpen] = useState(false);
  // The command bar's (#537): the scope under the project filter, the item it opened, and its one-shot answer request.
  const [deeper, setDeeper] = useState<Scope>(TOP);
  const [open, setOpen] = useState<Opened | null>(null);
  const [barRequest, setBarRequest] = useState<AnswerRequest | null>(null);
  const requests = useRef(0);
  const poller = useRef<Poller<CockpitOutcome> | null>(null);
  useAging(view.last);

  useEffect(() => {
    let current: View = kept.view ? { ...kept.view, reading: true } : { last: null, failure: null, reading: true, seq: 0 };
    const update = (next: View) => {
      current = next;
      kept.view = next;
      setView(next);
    };
    const loop = new Poller<CockpitOutcome>({
      lane,
      intervalMs: FLEET_TIMING.intervalMs,
      timeoutMs: TIMING.requestTimeoutMs,
      holdMs: TIMING.laneHoldMs,
      backoffMs: FLEET_TIMING.backoffMs,
      timers,
      visibility,
      read: (signal) => {
        update({ ...current, reading: true });
        return readCockpitView(browserFetch, signal);
      },
      settle: (o) => ({ ok: o.kind === 'ok', confirmed: o.kind === 'ok' || serverDone(o), retryAfterMs: o.kind === 'busy' ? o.retryAfterMs : null }),
      deliver: (o) => update(o.kind === 'ok' ? { last: { cockpit: o.envelope, received: clockNow() }, failure: null, reading: false, seq: current.seq + 1 } : { ...current, failure: o, reading: false }),
      onTimeout: () => update({ ...current, failure: { kind: 'disconnected', cause: 'timeout', status: null } }),
    });
    poller.current = loop;
    loop.start();
    // Leaving retires the loop: a read that is out keeps the lane until its answer or its bound.
    return () => {
      loop.retire();
      poller.current = null;
    };
  }, [lane]);

  const now = clockNow();
  const last = view.last;
  const c = last?.cockpit ?? null;
  const fresh = (f: CockpitData['projects']['freshness']) => (c && last ? freshNow(f, c.snapshot_at, last.received, now) : false);
  const stale = c !== null && ![c.projects.freshness, c.needs_you.freshness, c.agents.freshness].every(fresh);
  const conn: Connection = view.failure?.kind ?? (c === null ? 'reading' : stale ? 'stale' : 'live');
  useEffect(() => onConnection?.(conn), [conn, onConnection]);

  // A filter for a project or machine the latest read no longer has falls back to all.
  const projectIds = c?.projects.items.map((p) => p.id) ?? [];
  const machineList = c ? machines(c) : [];
  const shownFilter: Filter = {
    project: filter.project !== null && projectIds.includes(filter.project) ? filter.project : null,
    machine: filter.machine !== null && machineList.includes(filter.machine) ? filter.machine : null,
  };
  const scope = scopeOf(shownFilter.project, deeper);
  const scoped = c ? narrow(c, scope) : null;
  const onScope = (s: Scope) => {
    setFilter({ ...filter, project: s.project });
    setDeeper(s);
  };
  const onOutcome = (o: Outcome) => {
    if (o.scope !== undefined) onScope(o.scope);
    if (o.open !== undefined) setOpen(o.open);
    if (o.request !== undefined) setBarRequest({ ...o.request, seq: ++requests.current });
  };
  // A request is delivered once, in the render it is made: a row mounted later never replays it.
  useEffect(() => {
    if (barRequest !== null) setBarRequest(null);
  }, [barRequest]);

  return (
    <section className="cockpit" data-part="cockpit" data-snapshot-seq={view.seq}>
      <header className="page-head ck-head">
        <h1 className="disp m">Cockpit</h1>
        {c ? <ScopeCrumbs c={c} scope={scope} onClear={() => onOutcome({ line: null, scope: TOP, open: null })} /> : null}
        <div className="ck-filters" data-part="filters">
          <label className="ck-filter">
            <span className="ck-filter-label">Project</span>
            <select value={shownFilter.project ?? ''} onChange={(e) => setFilter({ ...filter, project: e.target.value === '' ? null : e.target.value })}>
              <option value="">All projects</option>
              {c?.projects.items.map((p) => <option key={p.id} value={p.id}>{projectName(c, p.id)}</option>)}
            </select>
          </label>
          <label className="ck-filter">
            <span className="ck-filter-label">Machine</span>
            <select value={shownFilter.machine ?? ''} disabled={machineList.length === 0} onChange={(e) => setFilter({ ...filter, machine: e.target.value === '' ? null : e.target.value })}>
              <option value="">All</option>
              {machineList.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            {machineList.length === 0 ? <span className="meta" data-part="machines-note">machines not reported yet</span> : shownFilter.machine !== null ? <span className="meta">rows whose machine is not reported stay in</span> : null}
          </label>
          <button type="button" className="btn" data-part="cockpit-refresh" aria-disabled={view.reading} onClick={() => poller.current?.refresh()}>Refresh</button>
        </div>
        {c && last ? <Freshness c={c} received={last.received} now={now} reading={view.reading} gapsOpen={gapsOpen} onToggle={() => setGapsOpen((o) => !o)} /> : <p className="meta" role="status">{view.reading ? 'reading…' : ''}</p>}
      </header>
      <div role="status">{view.failure ? <Notice failure={view.failure} lastGoodAt={c?.snapshot_at ?? null} now={new Date(now.wall)} onRetry={() => poller.current?.refresh()} /> : null}</div>
      {c && last ? (
        <>
          <NeedsYou c={scoped ?? c} received={last.received} now={now} filter={shownFilter} answersFor={answersFor} request={barRequest ?? request} open={open} where={scope.fleet === null ? undefined : crumbs(c, scope).join(' / ')} onReply={onReply} />
          <ReadyStock stock={c.ready_stock} projects={c.projects.items} assembledAt={c.snapshot_at} received={last.received} disconnected={view.failure !== null} />
          <Agents c={scoped ?? c} received={last.received} now={now} filter={shownFilter} />
          <CommandBar ctx={{ c, received: last.received, now, machine: shownFilter.machine, scope, open }} lost={filter.project !== null && shownFilter.project === null} onOutcome={onOutcome} />
        </>
      ) : null}
    </section>
  );
}

/** The freshness line: complete is quiet, partial is dashed, stale has the clock and the read time with seconds. Never gold. */
function Freshness({ c, received, now, reading, gapsOpen, onToggle }: { c: CockpitData; received: Received; now: Clock; reading: boolean; gapsOpen: boolean; onToggle: () => void }) {
  const parts = [c.projects, c.needs_you, c.agents];
  const partial = parts.some((p) => p.coverage.state === 'partial') || c.projects.items.some((p) => p.orchestrator.coverage.state === 'partial');
  const stale = !parts.every((p) => freshNow(p.freshness, c.snapshot_at, received, now));
  const times = parts.map((p) => (p.freshness.state === 'unknown' ? null : p.freshness.snapshot_at.known));
  const oldest = times.every((t): t is number => t !== null) ? Math.min(...times) : null;
  const gaps = allGaps(c);
  const unreadable = c.projects.items.filter((p) => gaps.some((g) => g.gap.project === p.id && g.part !== 'agents'));
  const read = oldest === null ? 'read time unknown' : `read ${clockText(oldest, new Date(now.wall))}`;
  const words = [stale ? 'Stale' : partial ? 'Partial' : 'Complete', read];
  if (partial) words.push(`${gaps.length} ${gaps.length === 1 ? 'gap' : 'gaps'}`);
  if (unreadable.length > 0) words.push(`${unreadable.length} ${unreadable.length === 1 ? 'project' : 'projects'} not fully read (${unreadable.map((p) => projectName(c, p.id)).join(', ')})`);
  return (
    <div className="ck-fresh" data-part="freshness" data-state={stale ? 'stale' : partial ? 'partial' : 'complete'}>
      <p className={`status-chip coverage-chip${partial ? ' is-partial' : ''}`} role="status">
        {stale ? <ConnectionGlyph connection="stale" /> : <StatusGlyph tier={partial ? 't5' : 't2'} />}
        <span className="chip-state" data-part="freshness-words">{words.join(' · ')}</span>
        {reading ? <span className="meta"> · reading…</span> : null}
      </p>
      {gaps.length > 0 ? (
        <button type="button" className="btn quiet" aria-expanded={gapsOpen} onClick={onToggle}>Details <ChevronIcon open={gapsOpen} /></button>
      ) : null}
      {gapsOpen && gaps.length > 0 ? (
        <ul className="gaps" data-part="gaps">
          {gaps.map((g, i) => <li key={i}><bdi>{`${g.part}${g.gap.project === null ? '' : ` · ${projectName(c, g.gap.project)}`} · ${g.gap.kind} · ${g.gap.detail}`}</bdi></li>)}
        </ul>
      ) : null}
    </div>
  );
}

function NeedsYou({ c, received, now, filter, answersFor, request, open, where, onReply }: { c: CockpitData; received: Received; now: Clock; filter: Filter; answersFor: (key: string) => ItemAnswers; request: AnswerRequest | null; open: Opened | null; where?: string; onReply?: (target: string, prefill: string) => void }) {
  const shown = needsShown(c, filter);
  const keys = openKeys(shown);
  const scope = where !== undefined ? ` in ${where}` : filter.project === null ? '' : ` in ${projectName(c, filter.project)}`;
  const part = c.needs_you;
  const freshList = freshNow(part.freshness, c.snapshot_at, received, now) && freshNow(c.projects.freshness, c.snapshot_at, received, now);
  const complete = part.coverage.state === 'complete' && c.projects.coverage.state === 'complete';
  let empty: string | null = null;
  if (shown.length === 0) {
    if (nothingNeedsYou({ ...c, needs_you: { ...part, items: shown } }, received, now)) empty = `Nothing needs you${scope}`;
    else if (!complete) empty = `No items read${scope}: this read is partial, so something may still need you`;
    else if (part.freshness.state === 'unknown') empty = `No items read${scope}: when this was read is unknown`;
    else empty = `None${scope} as of ${clockText(part.freshness.snapshot_at.known, new Date(now.wall))}: this read is stale`;
  }
  return (
    <section className="ck-needs" data-part="ck-needs-you" aria-labelledby="ck-needs-title">
      <h2 id="ck-needs-title" className="ck-title gold">Needs you <span className="ck-count" data-part="needs-count">{shown.length}</span></h2>
      <p className="meta">oldest first{!complete && shown.length > 0 ? ' · this read is partial: more may need you' : ''}{complete && !freshList && shown.length > 0 ? ' · stale: refresh before answering' : ''}</p>
      {empty !== null ? <p className="ck-empty" data-part="needs-empty" data-nothing={empty.startsWith('Nothing') ? 'true' : undefined}>{empty}</p> : (
        <ol className="ck-list">
          {shown.map((n, i) => {
            const key = needKey(n);
            return <NeedRow key={key ?? `unassigned:${i}`} n={n} position={i + 1} c={c} received={received} now={now} answers={key === null ? null : answersFor(key)} request={request} isOpen={open !== null && open.lost === undefined && open.key === keys[i]} onReply={onReply} />;
          })}
        </ol>
      )}
    </section>
  );
}

/** The item's project's known, non-null target, whatever its freshness. */
function knownTarget(c: CockpitData, n: Need): string | null {
  if (!('known' in n.project)) return null;
  const id = n.project.known;
  const t = c.projects.items.find((p) => p.id === id)?.orchestrator.target;
  return t && 'known' in t ? t.known : null;
}

type Step = { binding: string; choice: Choice; armed: boolean } | { changed: true } | null;

function NeedRow({ n, position, c, received, now, answers, request, isOpen = false, onReply }: { n: Need; position: number; c: CockpitData; received: Received; now: Clock; answers: ItemAnswers | null; request: AnswerRequest | null; isOpen?: boolean; onReply?: (target: string, prefill: string) => void }) {
  const act = actionable(c, n, received, now);
  const binding = bindingOf(c, n);
  const composers = answers?.composers ?? null;
  // The record changes with each answer's settlement, wherever it was made (one owner per item).
  useSyncExternalStore(
    (fn) => answers?.subscribe(fn) ?? (() => {}),
    () => answers?.version() ?? 0,
    () => 0,
  );
  const rec = answers ? readRecord(answers.storage) : null;
  // An answer already made is read under the target it was made for; a new answer, under the
  // current verified target it would be sent to (#1560's review, R3). Never one for the other.
  const subscribe = (fn: () => void) => composers?.subscribe(fn) ?? (() => {});
  const recTarget = rec?.target ?? null;
  const sRec = useSyncExternalStore(subscribe, () => (composers && recTarget !== null ? composers.get(recTarget) : EMPTY), () => EMPTY);
  const newTarget = act.ok ? act.target : knownTarget(c, n);
  const sNew = useSyncExternalStore(subscribe, () => (composers && newTarget !== null ? composers.get(newTarget) : EMPTY), () => EMPTY);
  const [step, setStep] = useState<Step>(null);
  const [preview, setPreview] = useState<{ key: string; target: string; said: PreviewSaid } | null>(null);
  const [unkept, setUnkept] = useState(false);
  const primary = useRef<HTMLButtonElement | null>(null);
  const outcome = useRef<HTMLParagraphElement | null>(null);
  const choice = useRef<HTMLButtonElement | null>(null);

  const recLocked = locked(sRec);
  const recDelivered = sRec.attempts.some((a) => a.result === 'queued' || a.result === 'sent');
  // The record for the item on screen, or for an earlier version of it (another binding).
  const mine = rec !== null && rec.binding === binding;
  // Still open, whatever the item shows now: never a second answer while one may be on its way.
  const open = rec !== null && (recLocked || (rec.phase === 'pending' && !(sRec.root !== null && !recDelivered)));
  const answeredHere = mine && (rec.phase !== 'pending' || (!recLocked && sRec.root === null));
  // What the row shows: the record's attempt while it is open or answers this item; otherwise the current target's.
  const s = open || mine ? sRec : sNew;
  const lockedNow = locked(s);
  const latest = s.attempts.length > 0 ? s.attempts[s.attempts.length - 1] : null;
  const offer = act.ok && !open && !answeredHere;

  const pending = step !== null && 'binding' in step ? step : null;
  const stale = pending !== null && (!act.ok || act.binding !== pending.binding || !offer);
  // A change disarms for good: the same proposal coming back needs a new choice.
  useEffect(() => {
    if (stale) setStep({ changed: true });
  }, [stale]);
  const changed = stale || (step !== null && 'changed' in step);
  const live = pending !== null && !changed ? pending : null;
  const retryable = act.ok && mine && recLocked && latest?.state === 'unknown';

  // #537's seam: a request for this item opens its answer as pressing Yes or No would.
  const key = needKey(n);
  const requested = request !== null && request.key === key ? request : null;
  useEffect(() => {
    if (requested && act.ok && offer) {
      setPreview(null);
      setStep({ binding: act.binding, choice: requested.choice, armed: !act.risky });
    }
    // Only a new request opens it.
  }, [requested?.seq]);

  // What a send would do: the core's preview, read (never sent) for a choice or a Try again.
  // The preview is of the exact target the press would send to: the current one for a new answer,
  // the record's own (the same, as its binding names it) for Try again.
  const previewTarget = live && act.ok ? act.target : retryable && rec ? rec.target : null;
  const previewKey = previewTarget === null ? null : live ? `choice:${live.binding}` : `retry:${binding}`;
  useEffect(() => {
    if (previewKey === null || composers === null || previewTarget === null) return;
    const ctl = new AbortController();
    void composers.preview(previewTarget, 'queue', ctl.signal).then((said) => {
      if (said) setPreview({ key: previewKey, target: previewTarget, said });
    });
    return () => ctl.abort('stop');
  }, [previewKey, composers, previewTarget]);

  // Each step's control takes focus, so a held key lands on it as a repeat, which never presses.
  // Leaving a step (Cancel, Escape, a change, a send) returns focus to the row, never to the page.
  const stepKey = live ? `${live.choice}:${live.armed}` : '';
  const lastStep = useRef('');
  useEffect(() => {
    if (stepKey !== '') primary.current?.focus();
    else if (lastStep.current !== '') {
      const a = document.activeElement;
      if (a === null || a === document.body || !a.isConnected) (choice.current ?? outcome.current)?.focus();
    }
    lastStep.current = stepKey;
  }, [stepKey]);

  const text = live && act.ok ? answerText(n, act.wording, live.choice) : null;
  // After each answer: the record follows what the core said. Delivered: kept as sent; refused or failed: gone, so the item can be answered again; anything else: left pending.
  const settleRecord = () => {
    if (!composers || !answers || !rec0.current) return;
    const r = rec0.current;
    const after = composers.get(r.target);
    const ok = after.attempts.find((a) => a.result === 'queued' || a.result === 'sent');
    if (ok && after.root === null) writeRecord(answers.storage, { ...r, phase: ok.result === 'queued' ? 'queued' : 'sent' });
    else if (!locked(after) && after.attempts.every((a) => a.result !== 'queued' && a.result !== 'sent')) clearRecord(answers.storage);
    answers.notify();
  };
  const rec0 = useRef<AnswerRecord | null>(null);
  rec0.current = rec;
  // The one send, on the owner's final press: the item's words to its own project's verified
  // orchestrator, its record saved first; or, for an attempt with no answer, the same attempt
  // again ("Try again"), so the core replays it instead of sending twice.
  const send = (p: Press) => {
    if (!composers || !answers || !act.ok) return;
    if (retryable) {
      outcome.current?.focus();
      void composers.press(act.target, p).then(settleRecord);
      return;
    }
    if (text === null || live === null || !offer || locked(composers.get(act.target))) return;
    const r: AnswerRecord = { binding: act.binding, target: act.target, text, phase: 'pending' };
    if (!writeRecord(answers.storage, r)) {
      setUnkept(true);
      return;
    }
    answers.notify();
    rec0.current = r;
    composers.edit(act.target, text);
    if (composers.get(act.target).draft !== text) {
      clearRecord(answers.storage);
      answers.notify();
      return;
    }
    setStep(null);
    void composers.press(act.target, p).then(settleRecord);
  };
  const deliberate = (e: MouseEvent) => e.detail <= 1;
  const choose = (e: MouseEvent, picked: Choice) => {
    if (!deliberate(e) || !act.ok) return;
    setPreview(null);
    setStep({ binding: act.binding, choice: picked, armed: !act.risky });
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.repeat && (e.key === 'Enter' || e.key === ' ')) e.preventDefault();
    if (e.key === 'Escape' && step !== null) setStep(null);
  };

  const blocked = composers && previewTarget !== null ? composers.blocked(previewTarget) : null;
  const noRecord = answers !== null && (answers.storage === null || unkept) ? 'this tab can’t keep the answer’s record (browser storage is full or off), so nothing is sent' : null;
  const gate = gateOf(preview && preview.key === previewKey && preview.target === previewTarget ? preview.said : null, blocked ?? noRecord);
  const meta = [
    'known' in n.project ? projectName(c, n.project.known) : 'Project unknown',
    `#${n.ticket}`,
    n.kind,
    `from spec #${n.spec}`,
  ];
  const age = 'known' in n.age_ms ? `waiting ${ageText(n.age_ms.known + Math.max(0, Math.min(now.mono - received.mono, now.wall - received.wall)))}` : 'waiting time not reported';
  const risky = 'known' in n.risky && n.risky.known;
  const unassigned = !('known' in n.project);
  const shownState = answeredHere && rec ? rec.phase : latest ? (latest.state === 'done' || latest.state === 'refused' ? (latest.result ?? latest.state) : latest.state) : 'none';
  const words = answeredHere && rec
    ? `Answered: ${choiceOf(rec.text)} · ${rec.phase === 'pending' ? 'its result wasn’t kept in this tab: it may have been sent' : rec.phase}`
    : latest && (lockedNow || !offer || latest.state === 'refused' || latest.result === 'failed' || latest.result === 'unsupported') ? outcomeWords(s, latest) : '';
  const earlier = rec !== null && !mine && open;
  return (
    <li className={`ck-need${risky ? ' is-risky' : ''}${unassigned ? ' is-unassigned' : ''}${isOpen ? ' is-open' : ''}`} data-ticket={n.ticket} data-spec={n.spec} data-kind={n.kind} data-position={position} data-open={isOpen ? 'true' : undefined} onKeyDown={onKeyDown}>
      <span className="ck-num" aria-hidden="true">{position}</span>
      <span className="ck-need-mark" aria-hidden="true"><StatusGlyph tier={unassigned ? 't5' : 't1'} shape={n.kind === 'needs_info' && !unassigned ? 'needs_info' : undefined} /></span>
      <div className="ck-need-body">
        <p className="ck-need-meta">{meta.map((m, i) => <span key={i}>{i > 0 ? ' · ' : ''}{m.startsWith('#') ? <span className="id">{m}</span> : <bdi>{m}</bdi>}</span>)}</p>
        <p className="ck-wording" data-part="wording">{'known' in n.wording ? <bdi>{n.wording.known}</bdi> : 'Proposal not readable here yet'}</p>
        <p className="meta ck-age">{age}{risky ? <span className="ck-risky" data-part="risky"> · Risky · confirms twice</span> : 'unknown' in n.risky ? ` · risk ${unknownText(n.risky.unknown)}` : ''}</p>
      </div>
      <div className="ck-act" data-part="answer">
        {changed ? <p className="effect" role="status" data-part="changed">This item changed. Nothing sent.</p> : null}
        {earlier ? <p className="effect" data-part="earlier">{`An answer to an earlier version of this item (${choiceOf(rec.text)}) is unresolved: it is never sent again for this one.`}</p> : null}
        <p ref={outcome} tabIndex={-1} className="ck-outcome" role="status" data-part="outcome" data-state={shownState}>{words}</p>
        {open ? (
          <div key="open" className="ck-buttons">
            {!act.ok ? <p className="effect ck-why" data-part="why"><Ids text={act.why} /></p> : null}
            {retryable ? <SendControl gate={{ ...gate, label: 'Try again', press: latest ? { mode: latest.mode, resumePausedQueue: latest.resumePausedQueue, acceptPossibleDuplicate: latest.acceptPossibleDuplicate } : gate.press, effect: gate.effect === null ? null : `${gate.effect} · the same message id: the core replays it, never a second send` }} idle onPress={send} /> : null}
            {latest && isUnsettled(latest.state) && composers && rec ? <button type="button" className="btn" onClick={() => void composers.check(rec.target, keyOf(latest)).then(settleRecord)}>Check again</button> : null}
          </div>
        ) : !act.ok ? (
          <p className="effect ck-why" data-part="why"><Ids text={act.why} /></p>
        ) : answeredHere ? null : live === null ? (
          <div key="choices" className="ck-buttons" data-part="choices">
            <button ref={choice} type="button" className="btn primary ck-yes" aria-label={`Yes to item ${position}, #${n.ticket}`} onClick={(e) => choose(e, 'yes')}>Yes</button>
            <button type="button" className="btn ck-no" aria-label={`No to item ${position}, #${n.ticket}`} onClick={(e) => choose(e, 'no')}>No</button>
            {onReply ? <button type="button" className="btn quiet" aria-label={`Reply to item ${position}, #${n.ticket}, in the orchestrator’s message box`} onClick={() => onReply(act.target, `Answer for ticket #${n.ticket} (spec #${n.spec}):\n\n`)}>Reply…</button> : null}
          </div>
        ) : !live.armed ? (
          <div key="armed" className="ck-buttons" data-part="armed">
            <button ref={primary} type="button" className="btn primary ck-arm" onClick={(e) => { if (deliberate(e)) setStep({ ...live, armed: true }); }}>{armedLabel(n, live.choice)}</button>
            <button type="button" className="btn quiet" onClick={() => setStep(null)}>Cancel</button>
            <p className="effect" data-part="arm-note">{`Press again to confirm. This is ${n.kind === 'live' || n.kind === 'release' || n.kind === 'publish' ? `a ${n.kind}` : 'risky'}; it confirms twice.`}</p>
          </div>
        ) : (
          <div key="confirm" className="ck-buttons" data-part="confirm">
            <SendControl buttonRef={primary} gate={{ ...gate, label: `Send ${live.choice === 'yes' ? 'Yes' : 'No'}${act.risky ? ': confirmed twice' : ''}` }} idle={!lockedNow} onPress={send} />
            <button type="button" className="btn quiet" onClick={() => setStep(null)}>Cancel</button>
          </div>
        )}
      </div>
    </li>
  );
}

function outcomeWords(s: ThreadState, a: ThreadState['attempts'][number]): string {
  switch (a.state) {
    case 'sending':
      return 'sending…';
    case 'checking':
      return 'checking…';
    case 'unknown': {
      const said = s.said.get(keyOf(a));
      const why = said?.kind === 'unknown' ? (said.cause === 'reload' ? 'the page reloaded before its answer came' : said.cause === 'timeout' ? 'no answer in time' : 'no answer came') : 'no answer came';
      return `Uncertain: it may or may not have been sent (${why}). Nothing is sent again on its own.`;
    }
    case 'uncertain':
      return 'Uncertain: the core could not tell whether it arrived. Nothing is sent again on its own.';
    case 'in-progress':
      return 'In progress: the core is still sending it.';
    case 'done':
      return a.result === 'sent' ? 'Sent' : a.result === 'queued' ? 'Queued' : `Not delivered: ${a.result ?? 'failed'}`;
    case 'refused':
      return `Not sent: ${a.result ?? 'refused'}`;
  }
}

type Gate = { label: string; press: Press; off: string | null; effect: string | null };

/** "No preview, no send" (rules 22, 25): the core's preview gates the final press, as the composer's does. */
function gateOf(said: PreviewSaid | null, blocked: string | null): Gate {
  const base: Gate = { label: 'Send', press: { mode: 'queue', resumePausedQueue: false, acceptPossibleDuplicate: false }, off: null, effect: null };
  const off = (why: string): Gate => ({ ...base, off: blocked ?? why });
  if (said === null) return off('reading what a send would do');
  if (said.kind === 'failed') return off(`what a send would do couldn’t be read (${said.why})`);
  const p = said.preview;
  if (p.status === 'refused') return off(p.refusal?.text ?? p.summary);
  // A paused queue needs the owner's explicit choice to resume it: that is the orchestrator's message box, not here.
  if (p.status !== 'ready') return off('the orchestrator’s queue appears paused: answer from its message box');
  const e = p.effects;
  const effect = e === null ? unknownText('not read') : 'known' in e.effect ? e.effect.known.text : unknownText(e.effect.unknown);
  return blocked ? { ...base, off: blocked, effect } : { ...base, effect };
}

/**
 * The cockpit's send button, under the same rules as the composer's (`npm
 * run check`: only a `SendControl` presses). One activation, one press: a
 * held key's repeat never presses, a double click's second click is not a
 * second press, and after a press it stays latched until a fresh activation.
 */
function SendControl({ gate, idle, onPress, buttonRef }: { gate: Gate; idle: boolean; onPress: (p: Press) => void; buttonRef?: { current: HTMLButtonElement | null } }) {
  const latched = useRef(false);
  const keys = useRef(new Set<string>());
  return (
    <div className="ck-send" data-action="send">
      <button
        ref={buttonRef}
        type="button"
        className="btn primary"
        data-part="send"
        aria-disabled={gate.off !== null || !idle ? 'true' : undefined}
        onKeyDown={(e) => {
          if (e.repeat) {
            e.preventDefault();
            return;
          }
          keys.current.add(e.key);
          latched.current = false;
        }}
        onKeyUp={(e) => {
          keys.current.delete(e.key);
          latched.current = false;
        }}
        onPointerDown={(e) => {
          if (e.detail <= 1) latched.current = false;
        }}
        onBlur={() => keys.current.clear()}
        onClick={(e) => {
          if (e.detail > 1) return;
          if (keys.current.size === 0) latched.current = false;
          if (latched.current || gate.off !== null || !idle) return;
          latched.current = true;
          onPress(gate.press);
        }}
      >
        {gate.label}
      </button>
      <p className="effect" data-part="effect">{gate.off ? <span className="why">can’t send: <bdi>{gate.off}</bdi></span> : <bdi>{gate.effect ?? ''}</bdi>}</p>
    </div>
  );
}

/** Text with each issue number (`#123`) in Geist Mono, as ids are; nothing else changes. */
function Ids({ text }: { text: string }) {
  return <>{text.split(/(#\d+)/).map((part, i) => (i % 2 === 1 ? <span key={i} className="id">{part}</span> : part))}</>;
}

const STATE_TIERS: Record<string, readonly [Tier, string | undefined]> = {
  building: ['t3', undefined],
  in_review: ['t4', 'in_review'],
  changes_requested: ['t4', 'changes_requested'],
  blocked: ['t4', 'blocked'],
  merged: ['t2', undefined],
  ready: ['t4', undefined],
  held: ['t4', undefined],
};

function Agents({ c, received, now, filter }: { c: CockpitData; received: Received; now: Clock; filter: Filter }) {
  const shown = agentsShown(c, filter);
  const groups = agentGroups(shown);
  const part = c.agents;
  const freshPart = freshNow(part.freshness, c.snapshot_at, received, now);
  const noStart = shown.every((a) => !('known' in a.started_at));
  // Time running only from a reported start: its age at assembly plus the time since receipt.
  const since = Math.max(0, Math.min(now.mono - received.mono, now.wall - received.wall));
  const running = (a: Agent): string | null => ('known' in a.started_at ? `running ${ageText(c.snapshot_at - a.started_at.known + since)} (from its reported start)` : noStart ? null : 'time running not reported');
  const empty = shown.length > 0 ? null : part.coverage.state === 'complete' && freshPart ? 'No agents running' : `No running agents in this read: it is ${part.coverage.state === 'partial' ? 'partial' : 'not fresh'}, so others may be running`;
  return (
    <section className="ck-agents" data-part="agents" aria-labelledby="ck-agents-title">
      <h2 id="ck-agents-title" className="ck-title">Agents <span className="ck-count" data-part="agents-count">{shown.length}</span></h2>
      <p className="meta">running now{noStart && shown.length > 0 ? ' · time running not reported yet' : ''}{part.coverage.state === 'partial' ? ' · partial: others may be running' : ''}</p>
      {empty !== null ? <p className="ck-empty" data-part="agents-empty">{empty}</p> : (
        <div className="ck-groups">
          {groups.map((g) => (
            <section key={g.key} className={`ck-group${g.fleet === null ? ' is-unplaced' : ''}`} data-group={g.fleet === null ? 'unplaced' : `${g.project ?? 'unknown'}:${g.fleet}`}>
              <h3 className="ck-group-title">
                <span className="ck-group-name">{g.fleet === null ? 'Not placed' : <>{g.project === null ? 'Project unknown' : <bdi>{projectName(c, g.project)}</bdi>} / <span className="id">#{g.fleet}</span></>}</span>
                <span className="ck-count">{g.agents.length}</span>
              </h3>
              <ul className="ck-rows">
                {g.agents.map((a) => <AgentRow key={a.thread} a={a} c={c} unplaced={g.fleet === null} running={running(a)} />)}
              </ul>
            </section>
          ))}
        </div>
      )}
    </section>
  );
}

function AgentRow({ a, c, unplaced, running }: { a: Agent; c: CockpitData; unplaced: boolean; running: string | null }) {
  const needs = agentNeedsYou(c, a);
  const [tier, shape] = 'known' in a.state ? (STATE_TIERS[a.state.known] ?? (['t5', undefined] as const)) : (['t3', undefined] as const);
  const word = 'known' in a.state ? a.state.known : unplaced ? 'active' : `active · state ${unknownText(a.state.unknown)}`;
  const l = a.location;
  const where = !('known' in l) ? `location ${unknownText(l.unknown)}` : l.known.kind === 'cloud' ? 'Cloud' : 'known' in l.known.machine ? `Local · ${l.known.machine.known}` : 'Local · machine not reported';
  return (
    <li className="ck-agent" data-thread={a.thread} data-needs-you={needs ? 'true' : undefined}>
      <span className="ck-agent-name">
        {unplaced ? <span className="ck-unplaced-mark" aria-hidden="true"><StatusGlyph tier="t5" /></span> : null}
        {'known' in a.ticket ? <span className="id">#{a.ticket.known}</span> : null}{' '}
        <bdi>{factText(a.title)}</bdi>
        {unplaced ? <span className="meta"><span className="id">{a.thread}</span> · {'known' in a.project ? <bdi>{projectName(c, a.project.known)}</bdi> : 'project unknown'} · no verified ticket link</span> : null}
      </span>
      {needs ? (
        <span className="ck-pill" data-part="needs-you-pill" data-tier="t1"><StatusMark tier="t1" word="needs you" /></span>
      ) : (
        <span className={`mk ${tier}`} data-part="status" data-tier={tier}><StatusMark tier={tier} word={word} shape={shape} /></span>
      )}
      <span className="ck-model"><bdi>{factText(a.model)}</bdi></span>
      <span className="ck-where" data-part="location">{where}{running ? <span className="ck-running" data-part="running">{running}</span> : null}</span>
    </li>
  );
}
