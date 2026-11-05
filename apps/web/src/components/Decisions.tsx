// Decisions (0.0.11 U6, #656): every open decision request as a card, read
// from `GET /api/v1/decisions` (contracts/decisions.v1.md), once a minute on
// the fleet pages' lane rules. A grill round shows each unanswered question
// (what it decides, its context, the recommendation) with Yes, Simplify and
// Own words; a summary, spec or plan shows its summary, headline, tickets and
// graph with one button.
//
// An answer is one send through the composer's send path, as cockpit page 1
// answers (#536): the owner chooses, sees the exact words and what a send
// would do (the core's preview), and presses Send. A risky record (live,
// release, publish) asks twice. Each answer slot keeps its own op id,
// attempts and receipt (src/decisions.ts's `slotStorage`), so a double click,
// a held key, a retry or a reload never sends twice, and a sent answer stays
// shown, never offered again, until the orchestrator saves it and the slot
// leaves the read. Nothing is sent on a load, a refresh or a reload.

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { KeyboardEvent, MouseEvent } from 'react';

import { browserFetch, readDecisionsView, serverDone } from '../api.ts';
import type { Failure } from '../api.ts';
import type { Clock, Received } from '../cockpit.ts';
import { freshNow, staleInMs } from '../cockpit.ts';
import { browserStorage, Composers, EMPTY, isUnsettled, keyOf, locked, newOpId } from '../composer.ts';
import type { PreviewSaid, Press, StorageLike, ThreadState } from '../composer.ts';
import { actionable, answerText, answerWords, armNote, bindingOf, clearReceipt, legacyAnswerReason, nothingWaits, readReceipt, risky, riskWords, slotsOf, slotStorage, writeReceipt } from '../decisions.ts';
import type { Choice, Decisions as DecisionsData, DecisionsOutcome, Item, Receipt, Slot } from '../decisions.ts';
import { Lane, Poller } from '../poller.ts';
import type { Timers, Visibility } from '../poller.ts';
import { selectBoundDecision } from '../notificationTarget.ts';
import type { BoundDecision, DecisionReference } from '../notificationTarget.ts';
import { clockText, unknownText } from '../present.ts';
import { FLEET_TIMING, TIMING } from '../timing.ts';
import type { Connection } from '../viewer.ts';
import { ChevronIcon } from './Icons.tsx';
import { ConnectionGlyph, Notice } from './Status.tsx';
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

const clockNow = (): Clock => ({ mono: performance.now(), wall: Date.now() });

type Snapshot = { decisions: DecisionsData; received: Received };
type View = { last: Snapshot | null; failure: Failure | null; reading: boolean; seq: number };

/** One slot's answers: its own composer state and storage, and a signal for its receipt's changes. */
/** `draft`: an unsent Own words text, memory only (never stored or sent), so a
 * card hidden while its source revalidates can restore it for the same binding. */
type SlotAnswers = { composers: Composers; storage: StorageLike | null; draft: { binding: string; text: string } | null; subscribe(fn: () => void): () => void; notify(): void; version(): number };

/**
 * The page's lifetime state, kept across navigation, as the cockpit's is:
 * one read lane, the last snapshot shown, and one owner of each slot's
 * answers, so a send made before leaving settles in the page open when its
 * answer comes. `receipts` signals any slot's receipt change, for the count.
 */
const kept: { lane: Lane | null; view: View | null; answers: Map<string, SlotAnswers>; receipts: number; listeners: Set<() => void> } = { lane: null, view: null, answers: new Map(), receipts: 0, listeners: new Set() };

function answersFor(key: string): SlotAnswers {
  const known = kept.answers.get(key);
  if (known) return known;
  const storage = slotStorage(browserStorage(), key);
  const listeners = new Set<() => void>();
  let version = 0;
  const made: SlotAnswers = {
    composers: new Composers({ fetch: browserFetch, storage, timers, newOpId: () => newOpId() }),
    storage,
    draft: null,
    subscribe: (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    notify: () => {
      version++;
      for (const fn of [...listeners]) fn();
      kept.receipts++;
      for (const fn of [...kept.listeners]) fn();
    },
    version: () => version,
  };
  kept.answers.set(key, made);
  return made;
}

/** Whether a slot's receipt says its answer for the binding on screen has been delivered: it then waits on the orchestrator, not the owner. */
function delivered(d: DecisionsData, s: Slot): boolean {
  const r = readReceipt(answersFor(s.key).storage);
  return r !== null && r.binding === bindingOf(d, s) && r.phase !== 'pending';
}

/** Re-renders when a fresh part turns stale on this clock. */
function useAging(last: Snapshot | null): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!last) return;
    const d = last.decisions;
    const now = clockNow();
    const due = new Set([d.freshness, d.orchestrator.freshness].map((f) => staleInMs(f, d.snapshot_at, last.received, now)).filter((ms): ms is number => ms !== null));
    const handles = [...due].map((ms) => window.setTimeout(() => setTick((n) => n + 1), ms));
    return () => {
      for (const h of handles) window.clearTimeout(h);
    };
  }, [last]);
  useEffect(() => visibility.subscribe(() => setTick((n) => n + 1)), []);
}

/** The page. `onCount` hears how many answers wait on the owner in the latest read (the navigation's count). */
export function Decisions({ onConnection, onCount, boundReference, onBoundState, allowBoundDetails = true, onBoundResolve }: { onConnection?: (c: Connection) => void; onCount?: (n: number) => void; boundReference?: DecisionReference; onBoundState?: (state: BoundDecision['state']) => void; allowBoundDetails?: boolean; onBoundResolve?: () => void }) {
  const [lane] = useState(() => (kept.lane ??= new Lane()));
  const [view, setView] = useState<View>(() => (kept.view ? { ...kept.view, reading: true } : { last: null, failure: null, reading: true, seq: 0 }));
  const [gapsOpen, setGapsOpen] = useState(false);
  const [boundRead, setBoundRead] = useState<Snapshot | null>(null);
  const boundBinding = useRef<string | undefined>(undefined);
  const boundKeys = useRef(new Set<string>());
  const receiptStatus = useRef<HTMLParagraphElement | null>(null);
  const poller = useRef<Poller<DecisionsOutcome> | null>(null);
  useAging(view.last);
  useSyncExternalStore(
    (fn) => {
      kept.listeners.add(fn);
      return () => kept.listeners.delete(fn);
    },
    () => kept.receipts,
    () => 0,
  );

  useEffect(() => {
    if (boundReference && !allowBoundDetails) { setBoundRead(null); return; }
    let current: View = kept.view ? { ...kept.view, reading: true } : { last: null, failure: null, reading: true, seq: 0 };
    const update = (next: View) => {
      current = next;
      if (next.last !== null && next.failure === null && !next.reading) setBoundRead(next.last);
      kept.view = next;
      setView(next);
    };
    const loop = new Poller<DecisionsOutcome>({
      lane,
      intervalMs: FLEET_TIMING.intervalMs,
      timeoutMs: TIMING.requestTimeoutMs,
      holdMs: TIMING.laneHoldMs,
      backoffMs: FLEET_TIMING.backoffMs,
      timers,
      visibility,
      read: (signal) => {
        update({ ...current, reading: true });
        return readDecisionsView(browserFetch, signal);
      },
      settle: (o) => ({ ok: o.kind === 'ok', confirmed: o.kind === 'ok' || serverDone(o), retryAfterMs: o.kind === 'busy' ? o.retryAfterMs : null }),
      deliver: (o) => update(o.kind === 'ok' ? { last: { decisions: o.envelope, received: clockNow() }, failure: null, reading: false, seq: current.seq + 1 } : { ...current, failure: o, reading: false }),
      onTimeout: () => update({ ...current, failure: { kind: 'disconnected', cause: 'timeout', status: null } }),
    });
    poller.current = loop;
    loop.start();
    return () => {
      loop.retire();
      poller.current = null;
    };
  }, [lane, boundReference, allowBoundDetails]);

  const now = clockNow();
  const last = view.last;
  // A bound landing never discloses a cached card before its authenticated
  // read, and access failure hides detail without discarding receipt owners.
  const d = last && (!boundReference || (allowBoundDetails && last === boundRead && view.failure === null)) ? last.decisions : null;
  const selected = boundReference && d && last ? selectBoundDecision(boundReference, d, last.received, now, boundBinding.current) : null;
  if (selected?.state === 'current') {
    if (boundBinding.current === undefined) boundBinding.current = selected.binding;
    if (d) for (const slot of slotsOf({ ...d, items: [selected.item] })) boundKeys.current.add(slot.key);
  }
  const needsResolution = selected?.state !== 'current' && selected?.needsResolution === true;
  useEffect(() => { if (needsResolution) onBoundResolve?.(); }, [needsResolution, onBoundResolve]);
  const boundState = selected?.state ?? 'unread';
  useEffect(() => { if (boundReference) onBoundState?.(boundState); }, [boundReference, boundState, onBoundState]);
  useEffect(() => {
    if (boundReference && (!allowBoundDetails || boundState !== 'current')
      && (document.activeElement === null || document.activeElement === document.body)) receiptStatus.current?.focus();
  }, [boundReference, allowBoundDetails, boundState]);
  const phases = [...boundKeys.current].flatMap((key) => { const receipt = readReceipt(answersFor(key).storage); return receipt ? [receipt.phase] : []; });
  const receiptWords = phases.includes('pending') ? 'An answer is unresolved. Its receipt is kept; nothing is sent again.'
    : phases.length > 0 ? 'An answer receipt is kept. Nothing is sent again.'
    : !allowBoundDetails ? 'Decision details are unavailable. Any stored answer receipt is kept; nothing is sent again.'
    : boundState !== 'current' ? `This notification’s decision is ${boundState}. Opening sends nothing.` : '';
  const slots = d ? slotsOf(d) : [];
  const waiting = d ? slots.filter((s) => !delivered(d, s)).length : null;
  const stale = d !== null && last !== null && !freshNow(d.freshness, d.snapshot_at, last.received, now);
  const conn: Connection = view.failure?.kind ?? (d === null ? 'reading' : stale ? 'stale' : 'live');
  useEffect(() => onConnection?.(conn), [conn, onConnection]);
  useEffect(() => {
    if (waiting !== null) onCount?.(waiting);
  }, [waiting, onCount]);

  return (
    <section className="decisions" data-part="decisions" data-snapshot-seq={view.seq}>
      {(!boundReference || allowBoundDetails) ? <header className="page-head dc-head">
        {boundReference ? <h2 className="disp m">Decision</h2> : <h1 className="disp m">Decisions</h1>}
        <button type="button" className="btn" data-part="decisions-refresh" aria-disabled={view.reading} onClick={() => poller.current?.refresh()}>Refresh</button>
        {d && last ? <Freshness d={d} received={last.received} now={now} reading={view.reading} gapsOpen={gapsOpen} onToggle={() => setGapsOpen((o) => !o)} /> : <p className="meta" role="status">{view.reading ? 'reading…' : ''}</p>}
        {d ? <Target d={d} /> : null}
      </header> : null}
      <div role="status">{(!boundReference || allowBoundDetails) && view.failure ? <Notice failure={view.failure} lastGoodAt={d?.snapshot_at ?? null} now={new Date(now.wall)} onRetry={() => poller.current?.refresh()} /> : null}</div>
      {boundReference ? <p ref={receiptStatus} className="effect ck-outcome" role="status" tabIndex={-1} data-part="bound-receipt">{receiptWords}</p> : null}
      {boundReference ? (
        selected?.state === 'current' && allowBoundDetails && d && last ? <Cards d={{ ...d, items: [selected.item] }} received={last.received} now={now} /> : null
      ) : d && last ? <Cards d={d} received={last.received} now={now} /> : null}
    </section>
  );
}

/** The freshness line: complete is quiet, partial is dashed, stale has the clock and the read time with seconds. Never gold. */
function Freshness({ d, received, now, reading, gapsOpen, onToggle }: { d: DecisionsData; received: Received; now: Clock; reading: boolean; gapsOpen: boolean; onToggle: () => void }) {
  const partial = d.coverage.state === 'partial';
  const stale = !freshNow(d.freshness, d.snapshot_at, received, now);
  const read = d.freshness.state === 'unknown' ? 'read time unknown' : `read ${clockText(d.freshness.snapshot_at.known, new Date(now.wall))}`;
  const gaps = [...d.coverage.gaps.map((g) => ({ part: 'decisions', g })), ...d.orchestrator.coverage.gaps.map((g) => ({ part: 'orchestrator', g }))];
  const words = [stale ? 'Stale' : partial ? 'Partial' : 'Complete', read];
  if (partial) words.push(`${d.coverage.gaps.length} ${d.coverage.gaps.length === 1 ? 'gap' : 'gaps'}`);
  return (
    <div className="ck-fresh" data-part="freshness" data-state={stale ? 'stale' : partial ? 'partial' : 'complete'}>
      <p className={`status-chip coverage-chip${partial ? ' is-partial' : ''}`} role="status">
        {stale ? <ConnectionGlyph connection="stale" /> : <StatusGlyph tier={partial ? 't5' : 't2'} />}
        <span className="chip-state" data-part="freshness-words">{words.join(' · ')}</span>
        {reading ? <span className="meta"> · reading…</span> : null}
      </p>
      {gaps.length > 0 ? <button type="button" className="btn quiet" aria-expanded={gapsOpen} onClick={onToggle}>Details <ChevronIcon open={gapsOpen} /></button> : null}
      {gapsOpen && gaps.length > 0 ? (
        <ul className="gaps" data-part="gaps">
          {gaps.map((x, i) => <li key={i}><bdi>{`${x.part} · ${x.g.kind} · ${x.g.detail}`}</bdi></li>)}
        </ul>
      ) : null}
    </div>
  );
}

/** Where answers go: the configured orchestrator thread, verified, or why there is none. */
function Target({ d }: { d: DecisionsData }) {
  const t = d.orchestrator.target;
  const words = 'known' in t ? (t.known === null ? 'No orchestrator thread is configured' : null) : `Orchestrator ${unknownText(t.unknown)}`;
  return (
    <p className="meta dc-target" data-part="target">
      {words ?? <>Answers go to <span className="id">{'known' in t ? t.known : ''}</span>{d.orchestrator.coverage.state === 'complete' ? ' · verified' : ' · not verified'}</>}
    </p>
  );
}

function Cards({ d, received, now }: { d: DecisionsData; received: Received; now: Clock }) {
  if (d.items.length === 0) {
    let empty: string;
    if (nothingWaits(d, received, now)) empty = 'Nothing waiting on you';
    else if (d.coverage.state !== 'complete') empty = 'No decisions read: this read is partial, so something may still wait on you';
    else if (d.freshness.state === 'unknown') empty = 'No decisions read: when this was read is unknown';
    else empty = `None as of ${clockText(d.freshness.snapshot_at.known, new Date(now.wall))}: this read is stale`;
    return <p className="ck-empty" data-part="decisions-empty" data-nothing={empty.startsWith('Nothing') ? 'true' : undefined}>{empty}</p>;
  }
  const slots = slotsOf(d);
  return (
    <ol className="dc-list">
      {d.items.map((x) => <Card key={JSON.stringify([x.subject.repository, x.comment_id])} d={d} item={x} slots={slots.filter((s) => s.item === x)} received={received} now={now} />)}
    </ol>
  );
}

const KIND_WORDS: Record<Item['request']['kind'], string> = {
  grill_round: 'Grill',
  grill_confirmation: 'Grill summary',
  spec_confirmation: 'Spec confirmation',
  plan_approval: 'Plan approval',
};

function Card({ d, item, slots, received, now }: { d: DecisionsData; item: Item; slots: Slot[]; received: Received; now: Clock }) {
  const r = item.request;
  const subject = `${item.subject.kind === 'pull_request' ? 'PR' : 'Issue'} #${item.subject.number}`;
  const where = r.kind === 'grill_round' || r.kind === 'grill_confirmation' ? `${r.grill_file} · ${subject}` : `Spec #${r.spec} · ${subject}`;
  const waits = slots.some((s) => !delivered(d, s));
  const current = item.current;
  return (
    <li className={`dc-card${waits ? ' is-open' : ''}`} data-comment={item.comment_id} data-kind={r.kind}>
      <header className="dc-card-head">
        <p className="dc-kind">
          {waits ? <span className="dc-mark" aria-hidden="true"><StatusGlyph tier="t1" /></span> : null}
          <span data-part="card-kind">{r.kind === 'grill_round' ? `Grill · round ${r.round}` : KIND_WORDS[r.kind]}</span>
          {waits ? <span className="dc-needs"> · needs you</span> : null}
        </p>
        <p className="meta" data-part="card-subject"><bdi>{where}</bdi></p>
        {risky(r.risk) || r.risk === 'unknown' ? <p className={`dc-risk${risky(r.risk) ? ' is-risky' : ''}`} data-part="risk">{riskWords(r.risk)}</p> : null}
        {r.kind === 'grill_round' ? <p className="meta" data-part="progress">{`${r.answered.length} of ${r.questions.length} answered`}</p> : null}
        {'known' in current ? (current.known ? null : <p className="meta dc-unverified" data-part="current">Wording changed since it was read</p>) : <p className="meta dc-unverified" data-part="current"><bdi>{`Current wording could not be verified (${current.unknown})`}</bdi></p>}
      </header>
      {r.kind === 'grill_round' ? (
        slots.map((s) => (
          <div key={s.key} className="dc-question" data-part="slot" data-question={s.question?.id}>
            <div className="dc-copy">
              <p className="dc-decides"><span className="id dc-qid" data-part="qid">{s.question?.id}</span> <bdi data-part="decides">{s.question?.decides}</bdi></p>
              <p className="dc-context" data-part="context">{s.question?.context}</p>
              <div className="dc-recommend">
                <p className="dc-label">Recommendation</p>
                <p data-part="recommendation">{s.question?.recommendation}</p>
              </div>
            </div>
            <AnswerSlot d={d} slot={s} received={received} now={now} />
          </div>
        ))
      ) : (
        <div className="dc-question" data-part="slot">
          <div className="dc-copy">
            <ol className="dc-summary" data-part="summary">{r.summary.map((line, i) => <li key={i}><bdi>{line}</bdi></li>)}</ol>
            {r.kind !== 'grill_confirmation' ? (
              <>
                <p className="dc-headline" data-part="headline">{`“${r.headline}”`}</p>
                {r.tickets.length === 0 ? <p className="meta" data-part="tickets-none">Tickets: not planned yet</p> : <Plan item={item} />}
              </>
            ) : null}
          </div>
          {slots.map((s) => <AnswerSlot key={s.key} d={d} slot={s} received={received} now={now} />)}
        </div>
      )}
    </li>
  );
}

/** The plan's ticket table and its graph, both from the record's own table and edges. */
function Plan({ item }: { item: Item }) {
  const r = item.request;
  if (r.kind !== 'plan_approval' && r.kind !== 'spec_confirmation') return null;
  return (
    <>
      <div className="dc-table-wrap">
        <table className="dc-table" data-part="tickets">
          <thead><tr><th scope="col">Ticket</th><th scope="col">Title</th><th scope="col">Blocked by</th></tr></thead>
          <tbody>
            {r.tickets.map((t) => (
              <tr key={t.number}>
                <td className="id">{`#${t.number}`}</td>
                <td><bdi>{t.title}</bdi></td>
                <td className="id">{t.blockers.length === 0 ? '—' : t.blockers.map((b) => `#${b}`).join(', ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="dc-graph" data-part="graph" aria-label="Plan graph: what waits on what">
        {r.graph.map((e) => <li key={`${e.blocker}-${e.ticket}`} data-edge={`${e.blocker}-${e.ticket}`}><span className="id">{`#${e.blocker}`}</span><span aria-label="before"> → </span><span className="id">{`#${e.ticket}`}</span></li>)}
      </ul>
    </>
  );
}

type Step = { binding: string; choice: Choice; text: string; armed: boolean } | { changed: true } | null;

/** One answer slot: its choices, its own words, its confirmation and its one send. */
function AnswerSlot({ d, slot, received, now }: { d: DecisionsData; slot: Slot; received: Received; now: Clock }) {
  const answers = answersFor(slot.key);
  const composers = answers.composers;
  const legacy = legacyAnswerReason(browserStorage(), slot.key);
  const act = legacy === null ? actionable(d, slot, received, now) : { ok: false as const, why: legacy };
  const binding = bindingOf(d, slot);
  useSyncExternalStore(answers.subscribe, answers.version, () => 0);
  const rec = readReceipt(answers.storage);
  // An answer already made is read under the target it was made for; a new answer, under the current verified target.
  const subscribe = (fn: () => void) => composers.subscribe(fn);
  const recTarget = rec?.target ?? null;
  const sRec = useSyncExternalStore(subscribe, () => (recTarget !== null ? composers.get(recTarget) : EMPTY), () => EMPTY);
  const newTarget = act.ok ? act.target : null;
  const sNew = useSyncExternalStore(subscribe, () => (newTarget !== null ? composers.get(newTarget) : EMPTY), () => EMPTY);
  const [step, setStep] = useState<Step>(null);
  // Restore an unsent draft only for the identical freshly verified binding.
  const [own, setOwnState] = useState<{ binding: string; text: string } | null>(() => (act.ok && answers.draft?.binding === act.binding ? answers.draft : null));
  const setOwn = (next: { binding: string; text: string } | null) => { answers.draft = next; setOwnState(next); };
  // A changed record cancels for good: a different verified binding drops it.
  useEffect(() => { if (act.ok && answers.draft !== null && answers.draft.binding !== act.binding) answers.draft = null; }, [act.ok, act.ok ? act.binding : null, answers]);
  const [preview, setPreview] = useState<{ key: string; target: string; said: PreviewSaid } | null>(null);
  const [unkept, setUnkept] = useState(false);
  const primary = useRef<HTMLButtonElement | null>(null);
  const outcome = useRef<HTMLParagraphElement | null>(null);
  const chosen = useRef<HTMLButtonElement | null>(null);
  const lastChoice = useRef<Choice>(slot.question === null ? 'confirm' : 'yes');

  const recLocked = locked(sRec);
  const recDelivered = sRec.attempts.some((a) => a.result === 'queued' || a.result === 'sent');
  const mine = rec !== null && rec.binding === binding;
  // Still open, whatever the slot shows now: never a second answer while one may be on its way.
  const open = rec !== null && (recLocked || (rec.phase === 'pending' && !(sRec.root !== null && !recDelivered)));
  const answeredHere = mine && (rec.phase !== 'pending' || (!recLocked && sRec.root === null));
  const s = open || mine ? sRec : sNew;
  const lockedNow = locked(s);
  const latest = s.attempts.length > 0 ? s.attempts[s.attempts.length - 1] : null;
  const offer = act.ok && !open && !answeredHere;

  const pending = step !== null && 'binding' in step ? step : null;
  const stalePending = pending !== null && (!act.ok || act.binding !== pending.binding || !offer);
  const staleOwn = own !== null && (!act.ok || act.binding !== own.binding);
  // A change cancels for good: the same record coming back needs a new choice.
  useEffect(() => {
    if (stalePending || staleOwn) {
      setStep({ changed: true });
      setOwn(null);
    }
  }, [stalePending, staleOwn]);
  const changed = stalePending || staleOwn || (step !== null && 'changed' in step);
  const live = pending !== null && !changed ? pending : null;
  const retryable = act.ok && mine && recLocked && latest?.state === 'unknown';

  const previewTarget = live && live.armed && act.ok ? act.target : retryable && rec ? rec.target : null;
  const previewKey = previewTarget === null ? null : live ? `choice:${live.binding}:${live.choice}` : `retry:${binding}`;
  useEffect(() => {
    if (previewKey === null || previewTarget === null) return;
    const ctl = new AbortController();
    void composers.preview(previewTarget, 'queue', ctl.signal).then((said) => {
      if (said) setPreview({ key: previewKey, target: previewTarget, said });
    });
    return () => ctl.abort('stop');
  }, [previewKey, composers, previewTarget]);

  // Each step's control takes focus, so a held key lands on it as a repeat, which never presses.
  // Leaving a step returns focus to the choice it came from, never to the page.
  const stepKey = live ? `${live.choice}:${live.armed}` : '';
  const lastStep = useRef('');
  useEffect(() => {
    if (stepKey !== '') primary.current?.focus();
    else if (lastStep.current !== '') {
      const a = document.activeElement;
      if (a === null || a === document.body || !a.isConnected) (chosen.current ?? outcome.current)?.focus();
    }
    lastStep.current = stepKey;
  }, [stepKey]);

  const rec0 = useRef<Receipt | null>(null);
  rec0.current = rec;
  // After each answer: the receipt follows what the core said. Delivered: kept as sent; refused or failed: gone, so the slot can be answered again; anything else: left pending.
  const settleReceipt = () => {
    if (!rec0.current) return;
    const r = rec0.current;
    const after = composers.get(r.target);
    const ok = after.attempts.find((a) => a.result === 'queued' || a.result === 'sent');
    if (ok && after.root === null) writeReceipt(answers.storage, { ...r, phase: ok.result === 'queued' ? 'queued' : 'sent' });
    else if (!locked(after) && after.attempts.every((a) => a.result !== 'queued' && a.result !== 'sent')) clearReceipt(answers.storage);
    answers.notify();
  };
  // The one send, on the owner's final press: the card's words to the verified orchestrator, its
  // receipt saved first; or, for an attempt with no answer, the same attempt again ("Try again").
  const send = (p: Press) => {
    if (!act.ok) return;
    if (retryable) {
      outcome.current?.focus();
      void composers.press(act.target, p).then(settleReceipt);
      return;
    }
    if (live === null || !live.armed || !offer || locked(composers.get(act.target))) return;
    const r: Receipt = { binding: act.binding, target: act.target, text: live.text, at: Date.now(), phase: 'pending' };
    if (!writeReceipt(answers.storage, r)) {
      setUnkept(true);
      return;
    }
    answers.notify();
    rec0.current = r;
    composers.edit(act.target, live.text);
    if (composers.get(act.target).draft !== live.text) {
      clearReceipt(answers.storage);
      answers.notify();
      return;
    }
    setStep(null);
    setOwn(null);
    void composers.press(act.target, p).then(settleReceipt);
  };
  const deliberate = (e: MouseEvent) => e.detail <= 1;
  const choose = (e: MouseEvent, picked: Choice) => {
    if (!deliberate(e) || !act.ok) return;
    const words = answerText(slot, picked, own?.text ?? '');
    if (words === null || (picked === 'own' && (own?.text ?? '').trim() === '')) return;
    lastChoice.current = picked;
    setPreview(null);
    setStep({ binding: act.binding, choice: picked, text: words, armed: !act.risky });
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.repeat && (e.key === 'Enter' || e.key === ' ')) e.preventDefault();
    if (e.key === 'Escape' && step !== null) setStep(null);
  };
  // A click on the confirmation's words leaves focus on the page: Escape still goes back, from there only.
  const stepOpen = step !== null;
  useEffect(() => {
    if (!stepOpen) return;
    const escape = (e: globalThis.KeyboardEvent) => {
      const a = document.activeElement;
      if (e.key === 'Escape' && (a === null || a === document.body)) setStep(null);
    };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  }, [stepOpen]);

  const blocked = previewTarget !== null ? composers.blocked(previewTarget) : null;
  const noRecord = answers.storage === null || unkept ? 'this tab can’t keep the answer’s receipt (browser storage is full or off), so nothing is sent' : null;
  const gate = gateOf(preview && preview.key === previewKey && preview.target === previewTarget ? preview.said : null, blocked ?? noRecord);
  const shownState = answeredHere && rec ? rec.phase : latest ? (latest.state === 'done' || latest.state === 'refused' ? (latest.result ?? latest.state) : latest.state) : 'none';
  const words = answeredHere && rec ? '' : latest && (lockedNow || !offer || latest.state === 'refused' || latest.result === 'failed' || latest.result === 'unsupported') ? outcomeWords(s, latest) : '';
  const earlier = rec !== null && !mine && open;
  const q = slot.question;
  const choices: { choice: Choice; label: string; className: string }[] = q !== null
    ? [{ choice: 'yes', label: 'Yes', className: 'btn primary dc-yes' }, { choice: 'simplify', label: 'Simplify', className: 'btn' }]
    : [{ choice: 'confirm', label: confirmLabel(slot), className: 'btn primary dc-yes' }];
  const refFor = (c: Choice) => (c === lastChoice.current ? chosen : undefined);
  return (
    <div className="dc-act" data-part="answer" onKeyDown={onKeyDown}>
      {changed ? <p className="effect" role="status" data-part="changed">This changed — read again. Nothing sent.</p> : null}
      {earlier ? <p className="effect" data-part="earlier">{`An answer to an earlier version of this (${rec.text}) is unresolved: it is never sent again for this one.`}</p> : null}
      {answeredHere && rec ? (
        <p className="dc-sent" data-part="sent">
          <span className="dc-sent-mark" aria-hidden="true"><StatusGlyph tier="t3" /></span>
          <bdi className="dc-sent-text">{rec.text}</bdi>
          {rec.phase === 'pending' ? ' · its result wasn’t kept in this tab: it may have been sent' : ` · ${rec.phase} ${clockText(rec.at, new Date(now.wall)).replace(/:\d\d$/, '')} · waiting for the orchestrator to save it`}
        </p>
      ) : null}
      <p ref={outcome} tabIndex={-1} className="ck-outcome" role="status" data-part="outcome" data-state={shownState}>{words}</p>
      {open ? (
        <div key="open" className="dc-buttons">
          {!act.ok ? <p className="effect ck-why" data-part="why">{act.why}</p> : null}
          {retryable ? <SendControl gate={{ ...gate, label: 'Try again', press: latest ? { mode: latest.mode, resumePausedQueue: latest.resumePausedQueue, acceptPossibleDuplicate: latest.acceptPossibleDuplicate } : gate.press, effect: gate.effect === null ? null : `${gate.effect} · the same message id: the core replays it, never a second send` }} idle onPress={send} /> : null}
          {latest && isUnsettled(latest.state) && rec ? <button type="button" className="btn" onClick={() => void composers.check(rec.target, keyOf(latest)).then(settleReceipt)}>Check again</button> : null}
        </div>
      ) : !act.ok ? (
        <p className="effect ck-why" data-part="why">{act.why}</p>
      ) : answeredHere ? null : live === null ? (
        <div key="choices" className="dc-buttons" data-part="choices">
          {choices.map((c) => {
            const out = answerWords(slot, c.choice) ?? '';
            return (
              <div key={c.choice} className="dc-choice">
                <button ref={refFor(c.choice)} type="button" className={c.className} aria-label={`${c.label}, sends ${out}`} onClick={(e) => choose(e, c.choice)}>{c.label}</button>
                <span className="meta" data-part="sends">{`Sends: ${out} + request and revision context`}</span>
              </div>
            );
          })}
          {q !== null ? (
            own === null ? (
              <div className="dc-choice">
                <button ref={refFor('own')} type="button" className="btn quiet" aria-expanded="false" onClick={() => { if (act.ok) setOwn({ binding: act.binding, text: '' }); }}>Own words</button>
              </div>
            ) : (
              <div className="dc-own" data-part="own">
                <label className="dc-label" htmlFor={`own-${slot.key}`}>{`Your words for ${q.id}`}</label>
                <textarea id={`own-${slot.key}`} className="dc-field" rows={3} value={own.text} onChange={(e) => setOwn({ ...own, text: e.target.value })} />
                <p className="meta" data-part="own-note">Your answer stays exactly as typed inside request and revision context</p>
                <button ref={refFor('own')} type="button" className="btn primary dc-yes" disabled={own.text.trim() === ''} onClick={(e) => choose(e, 'own')}>Send my words</button>
              </div>
            )
          ) : null}
        </div>
      ) : !live.armed ? (
        <div key="armed" className="dc-buttons dc-armed" data-part="armed">
          <p className="dc-arm-note" data-part="arm-note" role="status">{armNote(slot, live.choice === 'own' ? 'your words' : answerWords(slot, live.choice) ?? '')}</p>
          <p className="dc-outgoing" data-part="outgoing">{live.text}</p>
          <button ref={primary} type="button" className="btn primary dc-yes" onClick={(e) => { if (deliberate(e)) setStep({ ...live, armed: true }); }}>{live.choice === 'own' ? 'Yes, send my words' : `Yes, ${answerWords(slot, live.choice) ?? ''}`}</button>
          <button type="button" className="btn" onClick={(e) => { if (deliberate(e)) setStep(null); }}>Cancel</button>
        </div>
      ) : (
        <div key="confirm" className="dc-buttons" data-part="confirm">
          <p className="dc-label">Sends exactly:</p>
          <p className="dc-outgoing" data-part="outgoing">{live.text}</p>
          <SendControl buttonRef={primary} gate={{ ...gate, label: act.risky ? 'Send: confirmed twice' : 'Send' }} idle={!lockedNow} onPress={send} />
          <button type="button" className="btn quiet" onClick={(e) => { if (deliberate(e)) setStep(null); }}>Cancel</button>
        </div>
      )}
    </div>
  );
}

/** A confirmation's one button: what it confirms, named. */
function confirmLabel(s: Slot): string {
  const r = s.item.request;
  if (r.kind === 'grill_confirmation') return 'Confirm summary';
  if (r.kind === 'spec_confirmation') return `Confirm spec #${r.spec}`;
  return r.kind === 'plan_approval' ? `Approve #${r.spec}` : 'Confirm';
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
 * Decisions' send button, under the same rules as the composer's (`npm run
 * check`: only a `SendControl` presses). One activation, one press: a held
 * key's repeat never presses, a double click's second click is not a second
 * press, and after a press it stays latched until a fresh activation.
 */
function SendControl({ gate, idle, onPress, buttonRef }: { gate: Gate; idle: boolean; onPress: (p: Press) => void; buttonRef?: { current: HTMLButtonElement | null } }) {
  const latched = useRef(false);
  const keys = useRef(new Set<string>());
  return (
    <div className="ck-send" data-action="send">
      <button
        ref={buttonRef}
        type="button"
        className="btn primary dc-yes"
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
