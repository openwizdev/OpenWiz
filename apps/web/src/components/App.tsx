import { HomeIcon, SessionsIcon, FleetsIcon, PlusIcon, ChevronIcon, FileIcon } from './Icons.tsx';
// The page: the header with the envelope's coverage, snapshot and gaps, the
// connection state, the list, and the detail (or, since #12, the launcher, in
// the same panel and sheet). All state is presentation state; every rule
// comes from the envelope and the core's answers.

import type { ReactNode } from 'react';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';

import { browserFetch, browserXhr, readDecisionsView, readFleetView, readFleetsView, readSetup, serverDone } from '../api.ts';
import type { Failure, SetupView } from '../api.ts';
import type { FleetEnvelope } from '../fleetGraph.ts';
import { fleetsList } from '../fleets.ts';
import type { FleetsEnvelope } from '../fleets.ts';
import { guardDrops, Uploads } from '../attachments.ts';
import { browserStorage, Composers, newOpId } from '../composer.ts';
import { readReceipt, slotsOf, slotStorage } from '../decisions.ts';
import type { Decisions as DecisionsRead, Receipt } from '../decisions.ts';
import { Launchers } from '../launcher.ts';
import { Lane, Poller } from '../poller.ts';
import type { Timers, Visibility } from '../poller.ts';
import { groupPage, factText, clockText } from '../present.ts';
import { FLEET_TIMING, TIMING } from '../timing.ts';
import { connection, isStale, listed, Viewer } from '../viewer.ts';
import type { Connection } from '../viewer.ts';
import { Cockpit } from './Cockpit.tsx';
import { ConnectedNotifications } from './Notifications.tsx';
import { PlanGraph, PlanIcon } from './PlanGraph.tsx';
import { Decisions } from './Decisions.tsx';
import { NotificationTarget } from './NotificationTarget.tsx';
import { notificationToken } from '../notificationTarget.ts';
import type { NotificationLanding } from '../notificationTarget.ts';
import { Loops, LoopsIcon } from './Loops.tsx';
import { Detail } from './Detail.tsx';
import { CommandNavigation, CommandTrigger } from './CommandNavigation.tsx';
import { HomeLive } from './HomeLive.tsx';
import { Fleets } from './Fleets.tsx';
import { FeedbackShare } from './FeedbackShare.tsx';
import { FirstHour } from './FirstHour.tsx';
import type { Lane as FirstHourLane } from './FirstHour.tsx';
import type { OpenAnswer } from './NeedsYouAnswer.tsx';
import { FleetDetail } from './FleetDetail.tsx';
import { Inventory, KeepPlace, groupAnchor } from './Inventory.tsx';
import type { LaunchProject } from './Launcher.tsx';
import { ConnectionGlyph, ConnectionPill, CoverageChip, Notice } from './Status.tsx';
import { StatusGlyph } from './StatusMark.tsx';

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

/** Re-renders when a snapshot turns stale, and when the page becomes visible again. */
function useStaleClock(last: { receivedAt: number; receivedWall: number } | null, staleAfterMs = TIMING.staleAfterMs): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!last) return;
    const ms = Math.min(last.receivedAt - performance.now(), last.receivedWall - Date.now()) + staleAfterMs + 1;
    if (ms <= 0) return;
    const t = window.setTimeout(() => setTick((n) => n + 1), ms);
    return () => window.clearTimeout(t);
  }, [last, staleAfterMs]);
  useEffect(() => visibility.subscribe(() => setTick((n) => n + 1)), []);
}

/** How many snapshots the list has shown: a hook for the proofs (`data-snapshot-seq`). */
function useSnapshotSeq(last: unknown): number {
  const seen = useRef<{ last: unknown; n: number }>({ last: null, n: 0 });
  if (last && last !== seen.current.last) seen.current = { last, n: seen.current.n + 1 };
  return seen.current.n;
}

function isFleetsEnvelope(envelope: FleetsEnvelope | FleetEnvelope): envelope is FleetsEnvelope {
  return envelope.data.view === 'fleets';
}

type FleetAnswer = { kind: 'ok'; envelope: FleetsEnvelope | FleetEnvelope } | Failure;
type FleetSnapshot = { envelope: FleetsEnvelope | FleetEnvelope; receivedAt: number; receivedWall: number };
type FleetState = { spec: number | null; last: FleetSnapshot | null; failure: Failure | null; reading: boolean; seq: number };
type FleetCache = { list: FleetState | null; detail: FleetState | null };

/** C1/C2 share a single read lane, even when this screen is left and reopened. */
function FleetScreen({ lane, saved, onOpenThread, onConnection, onAnswer, onTarget, home = false, live }: { home?: boolean; live?: ReactNode; lane: Lane; saved: { current: FleetCache }; onOpenThread: (id: string) => void; onConnection: (c: Connection) => void; onAnswer: OpenAnswer; onTarget: (id: string | null) => void }) {
  const [spec, setSpec] = useState<number | null>(null);
  const [state, setState] = useState<FleetState>(() => saved.current.list ? { ...saved.current.list, reading: true } : { spec: null, last: null, failure: null, reading: true, seq: 0 });
  const [gapsOpen, setGapsOpen] = useState(false);
  const [width, setWidth] = useState(0);
  const root = useRef<HTMLElement | null>(null);
  const poller = useRef<Poller<FleetAnswer> | null>(null);
  const returnTo = useRef<number | null>(null);
  const returnedRow = useRef<HTMLButtonElement | null>(null);
  const back = useRef<HTMLButtonElement | null>(null);
  const refresh = useRef<HTMLButtonElement | null>(null);
  const remembered = spec === null ? saved.current.list : saved.current.detail;
  const current = state.spec === spec ? state : remembered?.spec === spec ? { ...remembered, reading: true } : { spec, last: null, failure: null, reading: true, seq: 0 };
  const last = current.last;
  useStaleClock(last, FLEET_TIMING.staleAfterMs);
  const stale = last !== null && isStale(last, { mono: typeof performance === 'undefined' ? 0 : performance.now(), wall: Date.now() }, FLEET_TIMING.staleAfterMs);
  const conn: Connection = current.failure?.kind ?? (last === null ? 'reading' : stale ? 'stale' : 'live');
  useEffect(() => onConnection(conn), [conn, onConnection]);

  useEffect(() => {
    const key = spec === null ? 'list' : 'detail';
    const kept = saved.current[key];
    let view: FleetState = kept?.spec === spec ? { ...kept, reading: true } : { spec, last: null, failure: null, reading: true, seq: 0 };
    const update = (next: FleetState) => {
      view = next;
      saved.current[key] = next;
      // Revoke the answer target in the same React batch as the fleet snapshot.
      if (next.last) onTarget(next.last.envelope.orchestrator ?? null);
      setState(next);
    };
    update(view);
    setGapsOpen(false);
    const loop = new Poller<FleetAnswer>({
      lane,
      intervalMs: FLEET_TIMING.intervalMs,
      timeoutMs: TIMING.requestTimeoutMs,
      holdMs: TIMING.laneHoldMs,
      backoffMs: FLEET_TIMING.backoffMs,
      timers,
      visibility,
      read: (signal) => {
        update({ ...view, reading: true });
        return spec === null ? readFleetsView(browserFetch, signal) : readFleetView(browserFetch, spec, signal);
      },
      settle: (answer) => ({ ok: answer.kind === 'ok', confirmed: serverDone(answer), retryAfterMs: answer.kind === 'busy' ? answer.retryAfterMs : null }),
      deliver: (answer) => {
        // Move focus before the focused coverage toggle is removed by this answer.
        if (answer.kind === 'ok' && isFleetsEnvelope(answer.envelope)
          && document.activeElement === root.current?.querySelector('[data-part=fleets] button.cov')
          && fleetsList(answer.envelope).gaps.length === 0) {
          refresh.current?.focus();
        }
        update(answer.kind === 'ok'
          ? { spec, last: { envelope: answer.envelope, receivedAt: performance.now(), receivedWall: Date.now() }, failure: null, reading: false, seq: view.seq + 1 }
          : { ...view, failure: answer, reading: false });
      },
      onTimeout: () => update({ ...view, failure: { kind: 'disconnected', cause: 'timeout', status: null } }),
    });
    poller.current = loop;
    loop.start();
    return () => { loop.retire(); poller.current = null; };
  }, [lane, saved, spec]);

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const resize = () => setWidth(Math.floor(el.getBoundingClientRect().width));
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // A vertical pull at the top refreshes through the same lane as the button.
  // Native listeners allow cancelling the browser's own pull once we own it.
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    let start: { x: number; y: number } | null = null;
    let pulled = false;
    const reset = () => { start = null; pulled = false; };
    const begin = (e: TouchEvent) => {
      reset();
      const t = e.touches[0];
      if (window.scrollY === 0 && e.touches.length === 1 && t) start = { x: t.clientX, y: t.clientY };
    };
    const move = (e: TouchEvent) => {
      const t = e.touches[0];
      if (!start || !t || e.touches.length !== 1 || window.scrollY !== 0) { reset(); return; }
      const dy = t.clientY - start.y;
      const dx = Math.abs(t.clientX - start.x);
      pulled = dy >= 64 && dy > dx;
      if (pulled) e.preventDefault();
    };
    const end = () => { if (pulled) poller.current?.refresh(); reset(); };
    el.addEventListener('touchstart', begin, { passive: true });
    el.addEventListener('touchmove', move, { passive: false });
    el.addEventListener('touchend', end);
    el.addEventListener('touchcancel', reset);
    return () => {
      el.removeEventListener('touchstart', begin);
      el.removeEventListener('touchmove', move);
      el.removeEventListener('touchend', end);
      el.removeEventListener('touchcancel', reset);
    };
  }, []);

  // Keep focus at a named control when its fleet row gives way to the detail.
  useEffect(() => {
    if (spec !== null) back.current?.focus();
  }, [spec]);
  useEffect(() => {
    if (spec !== null || !last || returnTo.current === null) return;
    if (document.activeElement !== refresh.current) { returnTo.current = null; return; }
    const row = root.current?.querySelector<HTMLButtonElement>(`button[data-fleet="${returnTo.current}"]`);
    if (row) { row.focus(); returnedRow.current = row; returnTo.current = null; }
  }, [spec, last]);
  // Recover the latest fleet row's lost focus; a blur cancels until a row gains focus again.
  useEffect(() => {
    const row = returnedRow.current;
    if (spec !== null || !row || row.isConnected) return;
    returnedRow.current = null;
    if (document.activeElement === null || document.activeElement === document.body) refresh.current?.focus();
  }, [spec, last]);

  const envelope = last?.envelope;
  const now = new Date();
  return (
    <section ref={root} data-part="fleet-screen" className={home && spec === null ? 'home-overview' : undefined} data-snapshot-seq={current.seq}
      onFocusCapture={(e) => { if (e.target instanceof HTMLButtonElement && e.target.matches('button[data-fleet]')) returnedRow.current = e.target; }}
      onBlurCapture={(e) => { if (e.target === returnedRow.current) returnedRow.current = null; }}>
      <header className="page-head">
        <h1 className="disp m">{home && spec === null ? 'Home' : 'Fleets'}</h1>
        <div className="act">
          {spec !== null ? <button ref={back} type="button" className="btn" onClick={() => { refresh.current?.focus(); setSpec(null); }}>All fleets</button> : null}
          <button ref={refresh} type="button" className="btn" data-part="fleet-refresh" aria-disabled={current.reading} onClick={() => poller.current?.refresh()}>Refresh fleets</button>
        </div>
        {!home || spec !== null || current.reading || stale ? <p className="meta" role="status">{home && spec === null ? <ConnectionGlyph connection={current.reading ? 'reading' : 'stale'} /> : null}{current.reading ? 'reading…' : stale ? 'stale · pull down or refresh' : 'pull down to refresh'}</p> : null}
        {stale ? <span className="mod" data-part="stale">stale</span> : null}
      </header>
      <div role="status">{current.failure ? <Notice failure={current.failure} lastGoodAt={last?.envelope.freshness.snapshot_at ?? null} now={now} /> : null}</div>
      {envelope && isFleetsEnvelope(envelope) ? (
        <Fleets home={home} envelope={envelope} now={now} fresh={!stale && current.failure === null} gapsOpen={gapsOpen} onToggleGaps={() => setGapsOpen((o) => !o)} onOpen={(n) => { returnTo.current = n; setSpec(n); }} onAnswer={onAnswer} />
      ) : envelope ? (
        <FleetDetail envelope={envelope} onAnswer={onAnswer} width={width} now={now} onOpenThread={onOpenThread} gapsOpen={gapsOpen} onToggleGaps={() => setGapsOpen((o) => !o)} />
      ) : null}
      {home && spec === null ? live : null}
    </section>
  );
}

// ── #2205: the first-hour guidance's mount ──
// One read of setup, decisions and the first fleet when the screen opens, and
// again on Refresh; nothing is polled, sent or started here. A lane is `read`
// only from a parsed answer. An empty fleet list counts as "no fleet yet" only
// when the list was read in full; otherwise the fleet stays unknown.

/** A failed read, in words the guidance puts after its own label. */
function failedWhy(f: Failure): string {
  if (f.kind === 'signed-out') return 'your access session has expired. Sign in again.';
  if (f.kind === 'disconnected') return 'the server did not answer.';
  if (f.kind === 'busy') return 'the server was busy.';
  return f.error ? f.error.message : `the answer (HTTP ${f.status}) was not one OpenWiz can read.`;
}

type Answer<T> = { kind: 'ok'; envelope: T } | Failure | 'stopped';
const settled = <T,>(answer: Answer<T>, last: T | null): FirstHourLane<T> | null =>
  answer === 'stopped' ? null : answer.kind === 'ok' ? { state: 'read', value: answer.envelope } : { state: 'failed', why: failedWhy(answer), last };
const lastOf = <T,>(lane: FirstHourLane<T>): T | null => (lane.state === 'read' ? lane.value : lane.state === 'failed' ? lane.last : null);

/** One request with its own deadline, still stopped when the screen goes (`screen` aborts with 'stop'). */
type Read<T> = (signal: AbortSignal) => Promise<T>;
function timed<T>(screen: AbortSignal, read: Read<T>): Promise<T> {
  const own = new AbortController();
  const stop = () => own.abort('stop');
  if (screen.aborted) stop(); else screen.addEventListener('abort', stop);
  const timeout = window.setTimeout(() => own.abort('timeout'), TIMING.requestTimeoutMs);
  return read(own.signal).finally(() => { window.clearTimeout(timeout); screen.removeEventListener('abort', stop); });
}

/** The first fleet: the lowest spec the list reports, or null for a list read in full with no fleets. Each read has its own deadline. */
async function readFirstFleet(screen: AbortSignal): Promise<FirstHourLane<FleetEnvelope | null> | null> {
  const list = await timed(screen, (signal) => readFleetsView(browserFetch, signal));
  if (list === 'stopped') return null;
  if (list.kind !== 'ok') return { state: 'failed', why: failedWhy(list), last: null };
  const specs = list.envelope.data.fleets.map((f) => f.spec);
  if (specs.length === 0) {
    const read = fleetsList(list.envelope);
    return read.list.kind === 'complete' && !read.partial ? { state: 'read', value: null } : { state: 'failed', why: 'the fleet list was read only in part.', last: null };
  }
  const spec = Math.min(...specs);
  return settled(await timed(screen, (signal) => readFleetView(browserFetch, spec, signal)), null);
}

function FirstHourScreen({ onConnection }: { onConnection: (c: Connection) => void }) {
  const [setup, setSetup] = useState<FirstHourLane<SetupView>>({ state: 'reading' });
  const [decisions, setDecisions] = useState<FirstHourLane<DecisionsRead>>({ state: 'reading' });
  const [fleet, setFleet] = useState<FirstHourLane<FleetEnvelope | null>>({ state: 'reading' });
  const [revision, setRevision] = useState(0);
  const [reading, setReading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setReading(true);
    // A refresh keeps each last good value until its new answer arrives.
    setSetup((l) => (l.state === 'read' ? l : { state: 'reading' }));
    setDecisions((l) => (l.state === 'read' ? l : { state: 'reading' }));
    setFleet((l) => (l.state === 'read' ? l : { state: 'reading' }));
    const reads = [
      timed(controller.signal, (signal) => readSetup(browserFetch, signal)).then((a) => { const next = settled(a, null); if (next) setSetup((l) => next.state === 'failed' ? { ...next, last: lastOf(l) } : next); }),
      timed(controller.signal, (signal) => readDecisionsView(browserFetch, signal)).then((a) => { const next = settled(a, null); if (next) setDecisions((l) => next.state === 'failed' ? { ...next, last: lastOf(l) } : next); }),
      readFirstFleet(controller.signal).then((next) => { if (next) setFleet(next); }),
    ];
    void Promise.all(reads).then(() => { if (controller.signal.reason !== 'stop') setReading(false); });
    return () => controller.abort('stop');
  }, [revision]);
  // The sidebar's connection: reading, then live only when every read answered.
  const failure = [setup, decisions, fleet].some((l) => l.state === 'failed');
  useEffect(() => onConnection(reading ? 'reading' : failure ? 'error' : 'live'), [reading, failure, onConnection]);
  // This tab's own decision receipts, by slot key: a sent answer shows as sent, never saved.
  const receipts = new Map<string, Receipt>();
  if (decisions.state === 'read') {
    for (const slot of slotsOf(decisions.value)) {
      const receipt = readReceipt(slotStorage(browserStorage(), slot.key));
      if (receipt) receipts.set(slot.key, receipt);
    }
  }
  return (
    <>
      <header className="page-head" data-part="first-hour-screen">
        <h1 className="disp m">First hour</h1>
        <div className="act">
          <a className="btn" href="/setup">Open setup</a>
          <button type="button" className="btn" data-part="first-hour-refresh" aria-disabled={reading} onClick={() => { if (!reading) setRevision((n) => n + 1); }}>Refresh</button>
        </div>
        <p className="meta" role="status">{reading ? 'reading…' : 'Read once. Refresh to read again.'}</p>
      </header>
      <FirstHour now={Date.now()} setup={setup} decisions={decisions} fleet={fleet} receipts={receipts} />
    </>
  );
}

export function App() {
  const [notification, setNotification] = useState<NotificationLanding>({ kind: 'none' });
  const [commandOpen, setCommandOpen] = useState(false);
  const [screen, setScreen] = useState<'cockpit' | 'home' | 'sessions' | 'fleets' | 'plan' | 'decisions' | 'loops' | 'first-hour'>('sessions');
  const [decisionCount, setDecisionCount] = useState<number | null>(null);
  const [answerTarget, setAnswerTarget] = useState<string | null>(null);
  const answerFrom = useRef<HTMLElement | null>(null);
  const [fleetConnection, setFleetConnection] = useState<Connection>('reading');
  const [fleetLane] = useState(() => new Lane());
  // Bounded presentation cache survives switching back to Sessions.
  const fleetSnapshots = useRef<FleetCache>({ list: null, detail: null });
  const sessionsVisible = useRef(true);
  sessionsVisible.current = notification.kind === 'none' && ((screen !== 'fleets' && screen !== 'cockpit' && screen !== 'plan' && screen !== 'decisions' && screen !== 'loops' && screen !== 'first-hour') || answerTarget !== null);
  const [sessionVisibility] = useState<Visibility>(() => ({
    hidden: () => visibility.hidden() || !sessionsVisible.current,
    subscribe: (fn) => {
      const unsubscribe = visibility.subscribe(fn);
      window.addEventListener('openwiz-viewchange', fn);
      return () => { unsubscribe(); window.removeEventListener('openwiz-viewchange', fn); };
    },
  }));
  useEffect(() => { window.dispatchEvent(new Event('openwiz-viewchange')); }, [screen, answerTarget, notification.kind]);
  const [viewer] = useState(() => new Viewer({ fetch: browserFetch, timers, visibility: sessionVisibility, now: () => performance.now(), wall: () => Date.now() }, TIMING));
  const state = useSyncExternalStore(
    (onChange) => viewer.subscribe(onChange),
    () => viewer.getState(),
    () => viewer.getState(),
  );
  // One tray per target (#16), shared by the composer and the launcher through the one prompt body.
  const [uploads] = useState(
    () => new Uploads({ fetch: browserFetch, xhr: browserXhr, storage: browserStorage(), timers, urls: { create: (f) => URL.createObjectURL(f), revoke: (u) => URL.revokeObjectURL(u) } }),
  );
  const [composers] = useState(() => new Composers({ fetch: browserFetch, storage: browserStorage(), timers, newOpId: () => newOpId(), uploads }));
  const [launchers] = useState(() => new Launchers({ fetch: browserFetch, storage: browserStorage(), timers, newOpId: () => newOpId(), uploads }));
  const [launch, setLaunch] = useState<LaunchProject | null>(null);
  const [gapsOpen, setGapsOpen] = useState(false);
  const sessionsButton = useRef<HTMLButtonElement | null>(null);
  const coverageFocus = useRef<HTMLButtonElement | null>(null);
  const firstRows = useRef(false);
  const returnTo = useRef<string | null>(null);
  const sessionsHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const follow = () => {
      const landing = notificationToken(window.location.hash);
      setNotification(landing);
      // #2205: the first-hour guidance's own link, which docs/first-hour.md gives.
      if (window.location.hash === '#first-hour') setScreen('first-hour');
      if (landing.kind !== 'none' || window.location.hash === '#first-hour') { setCommandOpen(false); viewer.select(null); setLaunch(null); setAnswerTarget(null); answerFrom.current = null; }
    };
    follow();
    window.addEventListener('hashchange', follow);
    return () => window.removeEventListener('hashchange', follow);
  }, [viewer]);
  const clearNotification = () => {
    if (notification.kind === 'none') return;
    setNotification({ kind: 'none' });
    if (window.location.hash.startsWith('#notification')) window.history.replaceState(null, '', window.location.pathname + window.location.search);
  };
  const dismissNotification = () => { clearNotification(); requestAnimationFrame(() => sessionsButton.current?.focus()); };

  useEffect(() => {
    viewer.start();
    return () => viewer.stop();
  }, [viewer]);

  // A file dropped anywhere but a prompt body never opens in the browser; object URLs go with the page (#16).
  useEffect(() => {
    const unguard = guardDrops(window);
    const leave = () => uploads.unload();
    window.addEventListener('pagehide', leave);
    return () => {
      unguard();
      window.removeEventListener('pagehide', leave);
    };
  }, [uploads]);

  const { list, detail } = state;
  useStaleClock(list.last);
  useStaleClock(detail?.last ?? null);
  const seq = useSnapshotSeq(list.last);
  const clocks = { mono: typeof performance === 'undefined' ? 0 : performance.now(), wall: Date.now() };
  const now = new Date(clocks.wall);
  const conn = connection(list, clocks, TIMING.staleAfterMs);
  const envelope = list.last?.envelope ?? null;
  const stale = list.last !== null && isStale(list.last, clocks, TIMING.staleAfterMs);
  const gaps = envelope?.gaps ?? [];

  useEffect(() => {
    const was = coverageFocus.current;
    if (was && !was.isConnected) {
      coverageFocus.current = null;
      if (screen === 'sessions' && (document.activeElement === null || document.activeElement === document.body)) {
        sessionsButton.current?.focus();
      }
    }
  }, [envelope, screen]);

  useEffect(() => {
    if (!firstRows.current && envelope && envelope.data.sessions.length > 0) {
      firstRows.current = true;
      performance.mark('first-rows');
    }
  }, [envelope]);

  const select = (id: string) => {
    clearNotification();
    setAnswerTarget(null);
    answerFrom.current = null;
    setScreen('sessions');
    setLaunch(null);
    returnTo.current = id;
    viewer.select(id);
  };
  const openAnswer: OpenAnswer = (id, prefill) => {
    // Move an untouched template to this item; keep the owner's text.
    // The composer's edit guard also preserves every unresolved attempt.
    const draft = composers.get(id).draft;
    if (draft === '' || /^Answer for ticket #\d+ \(spec #\d+\):\n\n$/.test(draft)) composers.edit(id, prefill);
    answerFrom.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setLaunch(null);
    setAnswerTarget(id);
    viewer.select(id);
  };
  const openLaunch = (project: LaunchProject) => {
    clearNotification();
    setAnswerTarget(null);
    answerFrom.current = null;
    viewer.select(null);
    returnTo.current = null;
    setLaunch(project);
  };
  const closeDetail = () => {
    if (answerFrom.current !== null) {
      viewer.select(null);
      setAnswerTarget(null);
      const from = answerFrom.current;
      if (from.isConnected && !(from instanceof HTMLButtonElement && from.disabled)) from.focus();
      else document.querySelector<HTMLButtonElement>('[data-part=fleet-refresh]')?.focus();
      answerFrom.current = null;
      return;
    }
    // Focus goes back where the panel was opened from: the session's row, or the project's New thread.
    const id = launch ? launch.id : returnTo.current;
    const from = (el: HTMLElement) => (launch ? el.dataset['newThread'] : el.dataset['sessionId']);
    viewer.select(null);
    setLaunch(null);
    returnTo.current = null;
    for (const el of document.querySelectorAll<HTMLElement>(launch ? 'main [data-new-thread]' : 'main [data-session-id]')) {
      if (from(el) === id) {
        el.focus();
        return;
      }
    }
    const active = document.activeElement;
    if (active === null || active === document.body || active.closest('[data-part=detail]')) {
      sessionsButton.current?.focus();
    }
  };
  const isListed = (id: string) => envelope?.data.sessions.some((row) => row.id === id) ?? false;

  const projects = envelope ? groupPage(envelope.data.sessions).filter((g) => g.group.kind === 'project') : [];
  const showSessions = () => {
    clearNotification();
    if (answerFrom.current !== null) { viewer.select(null); setAnswerTarget(null); answerFrom.current = null; }
    setScreen('sessions');
  };
  const showOverview = (next: 'cockpit' | 'home' | 'fleets' | 'plan' | 'decisions' | 'loops' | 'first-hour') => {
    clearNotification();
    viewer.select(null); setLaunch(null); setAnswerTarget(null); answerFrom.current = null; setScreen(next);
  };
  const showHome = () => showOverview('home');
  const showFleets = () => showOverview('fleets');
  const showCockpit = () => showOverview('cockpit');
  const showPlan = () => showOverview('plan');
  const showDecisions = () => showOverview('decisions');
  /** The Loops screen (#549): the sidebar's item, and the seam the Plan screen (#653) calls for the phone. */
  const showLoops = () => showOverview('loops');
  const showFirstHour = () => showOverview('first-hour');
  const onNew = () => {
    const first = projects[0];
    if (first?.group.kind === 'project') {
      setScreen('sessions');
      openLaunch({ id: first.group.id, name: first.group.name, suffix: first.suffix });
    }
  };
  const awaitingSession = notification.kind === 'none' && screen === 'sessions' && !detail && !launch && !list.failure && (envelope?.data.sessions.length ?? 0) > 0;
  return (
    <div className={`app${screen === 'home' ? ' home-screen' : ''}${detail || launch ? ' panel-open' : ` mobile-identity${awaitingSession ? ' sessions-idle' : ''}`}`}>
      <aside className="sidebar" aria-label="OpenWiz">
        <div className="brand"><span className="logo-slot" aria-hidden="true" /><p className="wordmark">OpenWiz</p></div>
        <nav className="app-nav" aria-label="Views">
          <button type="button" className="nav-item nav-cockpit" aria-pressed={screen === 'cockpit'} onClick={showCockpit}><FleetsIcon /><span>Cockpit</span></button>
          <button type="button" className="nav-item nav-home" aria-pressed={screen === 'home'} onClick={showHome}><HomeIcon /><span>Home</span></button>
          <button ref={sessionsButton} type="button" className="nav-item" aria-pressed={screen === 'sessions' && !launch} onClick={showSessions}><SessionsIcon /><span>Sessions</span></button>
          <button type="button" className="nav-item" aria-pressed={screen === 'fleets'} onClick={showFleets}><FleetsIcon /><span>Fleets</span></button>
          <button type="button" className="nav-item nav-plan" aria-pressed={screen === 'plan'} onClick={showPlan}><PlanIcon /><span>Plan</span></button>
          <button type="button" className="nav-item nav-decisions" aria-pressed={screen === 'decisions'} onClick={showDecisions}><StatusGlyph tier="t4" shape="needs_info" /><span>Decisions</span>{decisionCount ? <>{' '}<span className="nav-count" data-part="decisions-count">{decisionCount}</span></> : null}</button>
          <button type="button" className="nav-item nav-loops" aria-pressed={screen === 'loops'} onClick={showLoops}><LoopsIcon /><span>Loops</span></button>
          <button type="button" className="nav-item nav-first-hour" aria-pressed={screen === 'first-hour'} onClick={showFirstHour}><FileIcon /><span>First hour</span></button>
          <button type="button" className="nav-item nav-new" aria-label="New thread" aria-pressed={launch !== null} disabled={projects.length === 0} onClick={onNew}><PlusIcon /><span className="desktop-new">New thread</span><span className="phone-new">New</span></button>
        </nav>
        {notification.kind === 'none' && projects.length > 0 ? <nav className="project-nav" aria-label="Projects"><h2 className="section-label">Projects</h2>{projects.map((g) => <a key={g.key} href={`#${groupAnchor(g.key)}`} onClick={() => { setScreen('sessions'); requestAnimationFrame(() => document.getElementById(groupAnchor(g.key))?.scrollIntoView({ block: 'start' })); }}><span className="project-symbol" aria-hidden="true" /><span>{g.group.kind === 'project' ? factText(g.group.name) : 'ungrouped'}</span><span className="project-count">{g.sessions.length}</span></a>)}</nav> : null}
        <footer className="connection-footer"><ConnectionPill connection={screen === 'sessions' ? conn : fleetConnection} read={screen === 'sessions' && envelope ? clockText(envelope.freshness.snapshot_at, now).replace(/:\d\d$/, '') : undefined} /></footer>
      </aside>
      <header className="mobile-top">{launch ? <span className="mobile-title">New thread</span> : !detail ? <div className="mobile-brand"><span className="logo-slot" aria-hidden="true" /><p className="wordmark">OpenWiz</p></div> : null}<CommandTrigger compact onOpen={() => setCommandOpen(true)} /></header>
      <main data-snapshot-seq={seq}>
        <CommandTrigger onOpen={() => setCommandOpen(true)} />
        {notification.kind !== 'none' ? <NotificationTarget key={notification.kind === 'target' ? notification.token : 'invalid'} landing={notification} onDismiss={dismissNotification} /> : screen === 'cockpit' ? <><Cockpit onConnection={setFleetConnection} onReply={openAnswer} /><ConnectedNotifications /></> : screen === 'plan' ? <PlanGraph onConnection={setFleetConnection} onLoops={showLoops} /> : screen === 'decisions' ? <Decisions onConnection={setFleetConnection} onCount={setDecisionCount} /> : screen === 'loops' ? <Loops onConnection={setFleetConnection} /> : screen === 'first-hour' ? <FirstHourScreen onConnection={setFleetConnection} /> : screen !== 'sessions' ? <FleetScreen key={screen} home={screen === 'home'} live={<HomeLive envelope={envelope} stale={stale} failure={list.failure} now={now} onSelect={select} onRetry={() => viewer.refresh()} />} lane={fleetLane} saved={fleetSnapshots} onOpenThread={select} onConnection={setFleetConnection} onAnswer={openAnswer} onTarget={(target) => setAnswerTarget((id) => id === target ? id : null)} /> : <>
        <header className="page-head">
          <h1 ref={sessionsHeading} className="disp m" tabIndex={-1}>Sessions</h1>
          {envelope ? (
            <div className="inv">
              {gaps.length > 0 ? (
                <button type="button" className="cov" aria-describedby="inventory-read" aria-expanded={gapsOpen} onFocus={(e) => { coverageFocus.current = e.currentTarget; }} onBlur={(e) => { if (document.activeElement !== e.currentTarget) coverageFocus.current = null; }} onClick={() => setGapsOpen((o) => !o)}>
                  <CoverageChip envelope={envelope} now={now} readDescriptionId="inventory-read"><ChevronIcon open={gapsOpen} /></CoverageChip>
                </button>
              ) : <CoverageChip envelope={envelope} now={now} />}
              {stale ? <span className="status-chip" data-part="stale"><ConnectionGlyph connection="stale" /> stale</span> : null}
            </div>
          ) : null}
          {envelope && gapsOpen && gaps.length > 0 ? (
            <ul className="gaps" data-part="gaps">
              {gaps.map((g, i) => (
                <li key={i}>
                  <bdi>{g.kind}{g.subject === null ? null : <>{' · '}<span className="ref-id">{g.subject}</span></>}{` · ${g.detail}`}</bdi>
                </li>
              ))}
            </ul>
          ) : null}
        </header>
        {envelope && !gapsOpen && gaps.length > 0 ? <p className="gap-summary">{gaps.map((g, i) => <bdi key={i}>{i > 0 ? ' · ' : ''}{g.detail}</bdi>)}</p> : null}
        <KeepPlace snapshot={list}>
          {list.failure ? <Notice sessionState failure={list.failure} lastGoodAt={envelope?.freshness.snapshot_at ?? null} now={now} onRetry={() => viewer.refresh()} /> : null}
          {envelope ? (
            <Inventory
              envelope={envelope}
              previousMatched={list.previousMatched}
              selectedId={detail?.id ?? null}
              launchId={launch?.id ?? null}
              fresh={!stale && list.failure === null}
              now={now}
              onSelect={select}
              onNewThread={openLaunch}
              onPage={(offset) => {
                // This named target stays mounted while the old page's controls disappear.
                sessionsHeading.current?.focus();
                viewer.goTo(offset);
                window.scrollTo(0, 0);
              }}
            />
          ) : list.failure ? null : (
            <p className="meta">reading…</p>
          )}
        </KeepPlace>
        </>}
        {screen === 'home' && notification.kind === 'none' ? <FeedbackShare /> : null}
      </main>
      {awaitingSession ? (
        <div className="session-placeholder">
          <p>Select a session to see its purpose, latest reply and message box.</p>
        </div>
      ) : null}
      <CommandNavigation open={commandOpen} onOpen={() => setCommandOpen(true)} onClose={() => setCommandOpen(false)}
        sessions={notification.kind === 'none' ? envelope?.data.sessions ?? [] : []}
        projects={notification.kind === 'none' ? projects.flatMap((g) => g.group.kind === 'project' ? [{ id: g.group.id, name: g.group.name, suffix: g.suffix }] : []) : []}
        onHome={showHome} onFirstHour={showFirstHour} onCockpit={showCockpit} onPlan={showPlan} onSessions={() => { viewer.select(null); setLaunch(null); showSessions(); }} onFleets={showFleets} onSession={select}
        onProject={(project) => { setScreen('sessions'); openLaunch(project); }} />
      <Detail
        detail={detail}
        launch={launch ? { project: launch, launchers, uploads, listed: isListed, snapshotAt: list.last?.receivedAt ?? 0, onShowThread: select } : null}
        listed={answerFrom.current !== null ? answerTarget !== null && detail?.id === answerTarget : listed(state)}
        stale={detail?.last ? isStale(detail.last, clocks, TIMING.staleAfterMs) : false}
        now={now}
        composers={composers}
        uploads={uploads}
        onSearch={() => setCommandOpen(true)}
        onClose={closeDetail}
      />
    </div>
  );
}
