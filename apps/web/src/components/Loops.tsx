// The loops page (0.0.9 L7, #549): every OpenWiz loop with its cadence, next
// run, last run, 24-hour cost and switch. Problems first, in the server's
// order; the healthy loops one press away. One read, `GET /api/v1/loops`
// (src/loops.ts), through its own single-flight lane. A switch is sent only
// by the owner's press (src/loops.ts's `LoopSwitches.turn`), once, and its
// answer is shown as it is.

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';

import { browserFetch, readLoopsView, serverDone } from '../api.ts';
import type { Failure } from '../api.ts';
import { cadenceText, costText, lastText, LoopSwitches, nextText, whenText } from '../loops.ts';
import type { Loop, LoopsView, Switched } from '../loops.ts';
import { Lane, Poller } from '../poller.ts';
import type { Timers, Visibility } from '../poller.ts';
import { clockText } from '../present.ts';
import { FLEET_TIMING, TIMING } from '../timing.ts';
import type { Connection } from '../viewer.ts';
import { ChevronIcon } from './Icons.tsx';
import { Notice } from './Status.tsx';
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

type View = { last: LoopsView | null; failure: Failure | null; reading: boolean; seq: number };

/** Kept across navigation: one read lane, the last view, and the switches' answers. */
const kept: { lane: Lane | null; view: View | null; loops: LoopSwitches | null; healthyOpen: boolean } = { lane: null, view: null, loops: null, healthyOpen: false };

/** The Loops view's icon: two arrows in a circle. */
export function LoopsIcon() {
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 11a8 8 0 0 0-14.3-4.9L4 8" /><path d="M4 4v4h4" /><path d="M4 13a8 8 0 0 0 14.3 4.9L20 16" /><path d="M20 20v-4h-4" /></svg>;
}

export function Loops({ onConnection }: { onConnection?: (c: Connection) => void }) {
  const [lane] = useState(() => (kept.lane ??= new Lane()));
  const [loops] = useState(() => (kept.loops ??= new LoopSwitches({ fetch: browserFetch })));
  const [view, setView] = useState<View>(() => (kept.view ? { ...kept.view, reading: true } : { last: null, failure: null, reading: true, seq: 0 }));
  const [healthyOpen, setHealthyOpen] = useState(kept.healthyOpen);
  const poller = useRef<Poller<Awaited<ReturnType<typeof readLoopsView>>> | null>(null);
  useSyncExternalStore((fn) => loops.subscribe(fn), () => loops.version());

  useEffect(() => {
    let current: View = kept.view ? { ...kept.view, reading: true } : { last: null, failure: null, reading: true, seq: 0 };
    const update = (next: View) => {
      current = next;
      kept.view = next;
      setView(next);
    };
    const loop = new Poller<Awaited<ReturnType<typeof readLoopsView>>>({
      lane,
      intervalMs: FLEET_TIMING.intervalMs,
      timeoutMs: TIMING.requestTimeoutMs,
      holdMs: TIMING.laneHoldMs,
      backoffMs: FLEET_TIMING.backoffMs,
      timers,
      visibility,
      read: (signal) => {
        update({ ...current, reading: true });
        return readLoopsView(browserFetch, signal);
      },
      settle: (o) => (o === 'stopped' ? { ok: false, confirmed: false } : { ok: o.kind === 'ok', confirmed: o.kind === 'ok' || serverDone(o), retryAfterMs: o.kind === 'busy' ? o.retryAfterMs : null }),
      deliver: (o) => {
        if (o === 'stopped') return;
        update(o.kind === 'ok' ? { last: o.envelope, failure: null, reading: false, seq: current.seq + 1 } : { ...current, failure: o, reading: false });
      },
      onTimeout: () => update({ ...current, failure: { kind: 'disconnected', cause: 'timeout', status: null } }),
    });
    poller.current = loop;
    loop.start();
    return () => {
      loop.retire();
      poller.current = null;
    };
  }, [lane]);

  // While a switch is out, the rows stay as they were when it was pressed, so
  // a newer read never moves or hides the pressed switch (or its focus).
  const frozen = useRef<LoopsView | null>(null);
  if (!loops.sending()) frozen.current = null;
  else frozen.current ??= view.last;
  const v = frozen.current ?? view.last;
  // Once the switch settles, its loop may have moved (a newer read healed it):
  // keep it, its answer and the owner's focus in view, opening the healthy list if it went there.
  const pressed = useRef<string | null>(null);
  const settledHealthy = !loops.sending() && pressed.current !== null && (v?.loops.some((l) => l.id === pressed.current && l.problem === null) ?? false);
  useEffect(() => {
    const id = pressed.current;
    if (id === null || loops.sending()) return;
    if (settledHealthy && !healthyOpen) {
      kept.healthyOpen = true;
      setHealthyOpen(true);
      return;
    }
    pressed.current = null;
    const lost = document.activeElement === null || document.activeElement === document.body;
    const target = document.querySelector<HTMLElement>(`[data-loop="${id}"] [data-part=switch]`);
    if (lost && target) target.focus();
  });
  const conn: Connection = view.failure?.kind ?? (v === null ? 'reading' : 'live');
  useEffect(() => onConnection?.(conn), [conn, onConnection]);
  const now = new Date();
  const problems = v?.loops.filter((l) => l.problem !== null) ?? [];
  const healthy = v?.loops.filter((l) => l.problem === null) ?? [];
  const toggleHealthy = () => {
    kept.healthyOpen = !healthyOpen;
    setHealthyOpen(!healthyOpen);
  };
  // A saved switch is shown until a read taken after it says otherwise; then that read reads a fresh state.
  const onSwitch = (l: Loop, on: boolean) => {
    pressed.current = l.id;
    void loops.turn(l.id, on).then(() => {
      if (loops.get(l.id)?.kind === 'saved') poller.current?.refresh();
    });
  };

  return (
    <section className="loops" data-part="loops" data-snapshot-seq={view.seq}>
      <header className="page-head lp-head">
        <div>
          <h1 className="lp-title disp m">Loops{v ? <span className="lp-count" data-part="loops-count">{v.loops.length}</span> : null}</h1>
          <p className="meta" data-part="loops-read" role="status">
            {v ? `read ${clockText(v.read_at_ms, now)} · ${problems.length} need a look · ${healthy.length} healthy` : view.reading ? 'reading…' : ''}
          </p>
        </div>
        <button type="button" className="btn" data-part="loops-refresh" aria-disabled={view.reading} onClick={() => poller.current?.refresh()}>Refresh</button>
      </header>
      <div role="status">{view.failure ? <Notice failure={view.failure} lastGoodAt={v?.read_at_ms ?? null} now={now} onRetry={() => poller.current?.refresh()} /> : null}</div>
      {v && v.loops.length === 0 ? <p className="lp-empty" data-part="loops-empty">No loops yet: the default branch defines none under <code>loops/</code>.</p> : null}
      {v && v.loops.length > 0 ? (
        <>
          <section className="lp-group" data-part="problems" aria-labelledby="lp-problems">
            <h2 id="lp-problems" className={`lp-section${problems.length > 0 ? ' gold' : ''}`}>Need a look <span className="lp-count">{problems.length}</span></h2>
            <p className="meta">{problems.length > 0 ? 'latest run failed or unsure' : 'Nothing needs a look: every latest run went through.'}</p>
            {problems.length > 0 ? <ul className="lp-list">{problems.map((l) => <Row key={l.id} l={l} v={v} now={now} said={loops.get(l.id)} confirmed={loops.confirmed(l.id)} onSwitch={onSwitch} />)}</ul> : null}
          </section>
          <section className="lp-group" data-part="healthy" aria-labelledby="lp-healthy">
            <h2 id="lp-healthy" className="lp-section">Healthy <span className="lp-count">{healthy.length}</span></h2>
            {healthy.length > 0 ? (
              <>
                <button type="button" className="lp-show" data-part="show-healthy" aria-expanded={healthyOpen} aria-controls="lp-healthy-list" onClick={toggleHealthy}>
                  <span>{healthyOpen ? 'Hide healthy loops' : `Show ${healthy.length} healthy loop${healthy.length === 1 ? '' : 's'}`}</span><ChevronIcon open={healthyOpen} />
                </button>
                <ul id="lp-healthy-list" className="lp-list" hidden={!healthyOpen}>{healthy.map((l) => <Row key={l.id} l={l} v={v} now={now} said={loops.get(l.id)} confirmed={loops.confirmed(l.id)} onSwitch={onSwitch} />)}</ul>
              </>
            ) : <p className="meta">none</p>}
          </section>
        </>
      ) : null}
    </section>
  );
}

/** What a row's switch shows: the read's state, or the last saved switch when it is newer than the read. */
function shownOn(l: Loop, v: LoopsView, confirmed: { on: boolean; atMs: number } | null): boolean {
  return confirmed !== null && confirmed.atMs >= v.read_at_ms ? confirmed.on : l.enabled;
}

function saidText(said: Switched | null, now: Date): string {
  switch (said?.kind) {
    case undefined:
      return '';
    case 'sending':
      return said.on ? 'Switching on…' : 'Switching off…';
    case 'saved':
      return `${said.on ? 'On' : 'Off'} · saved ${whenText(said.atMs, now)}`;
    case 'busy':
      return said.pass ? 'Not switched: a loop pass is running. Press again in a few seconds.' : 'Not switched: the server was busy. Press again in a few seconds.';
    case 'refused':
      return `Not switched: ${said.why}`;
    case 'signed-out':
      return 'Not switched: signed out. Sign in again, then press again.';
    case 'unknown':
      return `Switch unknown (${said.why}): it may have been saved. Refresh to see.`;
  }
}

function Row({ l, v, now, said, confirmed, onSwitch }: { l: Loop; v: LoopsView; now: Date; said: Switched | null; confirmed: { on: boolean; atMs: number } | null; onSwitch: (l: Loop, on: boolean) => void }) {
  const on = shownOn(l, v, confirmed);
  const sending = said?.kind === 'sending';
  const tier = l.problem !== null ? 't1' : !on ? 't5' : l.last_run?.result === 'created' || l.last_run?.result === 'dispatching' || l.last_run?.result === 'checking' ? 't3' : 't4';
  // A saved switch newer than the read outdates its next run: off has none; on waits for a fresh read to schedule it.
  const switched = confirmed !== null && confirmed.atMs >= v.read_at_ms;
  const next = !switched ? nextText(l.next_run, now) : !on ? 'off: no next run' : l.wake.kind === 'event' ? null : 'next run: awaiting a fresh read';
  const facts = [cadenceText(l.wake, now), next, lastText(l.last_run, now), costText(l.cost, v.cost_window_ms)].filter((x): x is string => x !== null);
  return (
    <li className={`lp-row${l.problem !== null ? ' is-problem' : ''}`} data-loop={l.id} data-problem={l.problem ?? undefined}>
      <span className="lp-mark" aria-hidden="true"><StatusGlyph tier={tier} /></span>
      <div className="lp-body">
        <h3 className="lp-name"><bdi>{l.name}</bdi>{l.mode === 'shadow' ? <span className="lp-mode meta"> · shadow: checks only</span> : null}</h3>
        <p className="lp-facts meta" data-part="facts">{facts.join(' · ')}</p>
        {l.problem !== null && l.last_run?.reason ? <p className="lp-reason meta" data-part="reason"><bdi>{l.last_run.reason}</bdi></p> : null}
      </div>
      <div className="lp-switch-cell">
        <button type="button" role="switch" className="lp-switch" data-part="switch" aria-checked={on} aria-label={`${l.name}: ${on ? 'on' : 'off'}`} aria-disabled={sending} onClick={() => { if (!sending) onSwitch(l, !on); }}>
          <span className="lp-switch-word" aria-hidden="true">{on ? 'On' : 'Off'}</span><span className="lp-pill" aria-hidden="true"><span className="lp-knob" /></span>
        </button>
        <p className="lp-said meta" data-part="said" aria-live="polite">{saidText(said, now)}</p>
      </div>
    </li>
  );
}
