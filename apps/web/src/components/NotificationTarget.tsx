import { useCallback, useEffect, useRef, useState } from 'react';
import { browserFetch } from '../api.ts';
import type { Failure } from '../api.ts';
import type { Received } from '../cockpit.ts';
import { targetIsFresh, targetObservation, targetReader } from '../notificationTarget.ts';
import type { DecisionReference, NotificationLanding, TargetResult } from '../notificationTarget.ts';
import { clockText } from '../present.ts';
import { FLEET_TIMING } from '../timing.ts';
import type { Timers, Visibility } from '../poller.ts';
import { Decisions } from './Decisions.tsx';
import { StatusGlyph } from './StatusMark.tsx';

type View = { target: TargetResult | null; received: Received | null; failure: Failure | null; reading: boolean };
const now = () => ({ mono: performance.now(), wall: Date.now() });
const UNREAD = 'This notification’s item could not be verified. Opening sends nothing.';
const WORDS: Record<TargetResult['state'], string> = {
  current: 'Exact item verified. Opening sends nothing.', changed: 'This item changed. Read the current decision before answering.',
  resolved: 'This item is resolved. Opening sends nothing.', missing: 'This item is unavailable. Opening sends nothing.',
  ambiguous: 'More than one source record matches. Opening sends nothing.', unread: UNREAD,
};

const timers: Timers = {
  setTimeout: (fn, ms) => window.setTimeout(fn, ms),
  clearTimeout: (handle) => { if (typeof handle === 'number') window.clearTimeout(handle); },
};
const visibility: Visibility = {
  hidden: () => document.visibilityState === 'hidden',
  subscribe: (fn) => { document.addEventListener('visibilitychange', fn); return () => document.removeEventListener('visibilitychange', fn); },
};

/** Only navigation and reads. The existing card remains the sole answer owner. */
export function NotificationTarget({ landing, onDismiss }: { landing: NotificationLanding; onDismiss: () => void }) {
  const token = landing.kind === 'target' ? landing.token : null;
  const [boundState, setBoundState] = useState<TargetResult['state'] | null>(null);
  const [view, setView] = useState<View>({ target: null, received: null, failure: null, reading: token !== null });
  const [, age] = useState(0);
  const reader = useRef<ReturnType<typeof targetReader> | null>(null);
  const observation = useRef<Received | null>(null);
  const boundReference = useRef<DecisionReference | null>(null);
  const omitted = useRef(false);
  const heading = useRef<HTMLHeadingElement | null>(null);
  useEffect(() => { heading.current?.focus(); }, [token]);
  useEffect(() => {
    if (token === null) return;
    const loop = targetReader({
      token, fetch: browserFetch, timers, visibility,
      // Revalidation keeps the last verified result until the new one arrives,
      // so an unchanged poll never unmounts the card and its unsent draft (R1).
      onReading: () => setView((v) => ({ ...v, reading: true })),
      deliver: (outcome) => {
        if (outcome.kind === 'ok') {
          const received = targetObservation(observation.current, outcome.envelope, now());
          observation.current = received;
          setView({ target: outcome.envelope, received, failure: null, reading: false });
        } else setView({ target: null, received: null, failure: outcome, reading: false });
      },
      onTimeout: () => setView({ target: null, received: null, failure: { kind: 'disconnected', cause: 'timeout', status: null }, reading: false }),
    });
    reader.current = loop;
    loop.start();
    return () => { loop.retire(); reader.current = null; };
  }, [token]);
  const resolveOmission = useCallback(() => {
    if (omitted.current) return;
    omitted.current = true;
    reader.current?.refresh();
  }, []);
  useEffect(() => {
    const target = view.target;
    const received = view.received;
    if (!target || !received || !targetIsFresh(target, received, now()) || target.freshness.state !== 'fresh') return;
    const current = now();
    const elapsed = Math.max(current.mono - received.mono, current.wall - received.wall);
    const remaining = FLEET_TIMING.staleAfterMs - (received.wall - target.freshness.snapshot_at.known) - elapsed + 1;
    const timeout = window.setTimeout(() => age((n) => n + 1), remaining);
    const visible = () => age((n) => n + 1);
    document.addEventListener('visibilitychange', visible);
    return () => { window.clearTimeout(timeout); document.removeEventListener('visibilitychange', visible); };
  }, [view]);

  const target = view.target;
  const fresh = target !== null && view.received !== null && targetIsFresh(target, view.received, now());
  const decision = target !== null && target.state === 'current' && fresh && 'decision' in target.reference ? target.reference.decision : null;
  if (decision && boundReference.current === null) boundReference.current = decision;
  const sameReference = decision === null || boundReference.current === null || JSON.stringify(decision) === JSON.stringify(boundReference.current);
  // A verified current target stays shown only within its own freshness age;
  // refusal, failure or a changed result replaces it and hides detail.
  const allowDetails = decision !== null && sameReference && view.failure === null;
  const effective = !sameReference ? 'changed' : target?.state === 'current' ? (decision ? boundState ?? 'unread' : 'unread') : target?.state ?? 'unread';
  const state = landing.kind === 'invalid' ? 'Invalid reference' : view.reading ? 'Reading' : view.failure?.kind === 'signed-out' ? 'Signed out'
    : view.failure?.kind === 'error' && view.failure.status === 403 ? 'Access refused'
    : view.failure?.kind === 'error' && view.failure.status === 404 ? 'Unavailable'
    : effective.charAt(0).toUpperCase() + effective.slice(1);
  const message = landing.kind === 'invalid' ? 'Notification reference refused. Opening sends nothing.' : view.reading ? 'Checking this exact item. Opening sends nothing.'
    : view.failure?.kind === 'signed-out' ? 'Sign in to read this notification. Opening sends nothing.'
    : state === 'Access refused' ? 'Access was refused. Opening sends nothing.' : state === 'Unavailable' ? 'This notification reference is unavailable. Opening sends nothing.'
    : WORDS[effective];
  const read = target && target.freshness.state !== 'unknown' ? `Read ${clockText(target.freshness.snapshot_at.known, new Date(now().wall))}.` : 'Read time unknown.';
  const refresh = () => {
    if (token === null || view.reading || reader.current?.inFlight) return;
    omitted.current = false;
    setView((v) => ({ ...v, reading: true }));
    reader.current?.refresh();
  };
  return (
    <section className="decisions" data-part="notification-target" data-state={state} data-ready={!view.reading ? 'true' : undefined}>
      <div className="notice">
        <header className="page-head"><h1 ref={heading} tabIndex={-1} className="disp m">Notification</h1></header>
        <div role="status" aria-live="polite">
          <p className="status-chip coverage-chip"><StatusGlyph tier={state === 'Current' ? 't2' : 't5'} /><span>{state}</span></p>
          <p className="notice-body">{message}</p>
          <p className="meta">{read}</p>
        </div>
        <div className="act">
          <button type="button" className="btn" data-part="notification-refresh" aria-disabled={view.reading || token === null} onClick={refresh}>Refresh</button>
          <button type="button" className="btn" onClick={onDismiss}>Dismiss</button>
        </div>
      </div>
      {boundReference.current ? <Decisions key={token} boundReference={boundReference.current} allowBoundDetails={allowDetails} onBoundState={setBoundState} onBoundResolve={resolveOmission} /> : null}
    </section>
  );
}
