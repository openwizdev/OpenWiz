import { useCallback, useEffect, useRef, useState } from 'react';
import { browserFetch, readNotificationStatus, writeNotificationPreferences } from '../api.ts';
import type { FetchLike, Failure } from '../api.ts';
import { browserStorage, newOpId } from '../composer.ts';
import { notificationWrite, readPendingWrite } from '../notifications.ts';
import type { NotificationAction, NotificationPreferenceWrite } from '../notifications.ts';
import { NOTIFICATION_CATEGORIES, notificationDefaults, notificationFailureWords, notificationReadTime, notificationReady, notificationStateWord, selectNotificationCategory } from '../notifications.ts';
import type { NotificationCategories, NotificationStatus } from '../notifications.ts';
import { StatusGlyph } from './StatusMark.tsx';

export type NotificationsProps = {
  status?: NotificationStatus | null;
  failure?: Failure | null;
  saving?: boolean;
  reading?: boolean;
  now?: number;
  // #2035 owns these effects and operation persistence. No default callback
  // performs a live read/write, native prompt, subscription or submission.
  onRefresh?: () => void;
  onSave?: (categories: NotificationCategories) => void;
  onDisable?: () => void;
  onEnable?: () => void;
};

/** Standalone settings; its failures never replace Needs you or ready stock. */
export function Notifications({ status = null, failure = null, saving = false, reading = false, now, onRefresh, onSave, onDisable, onEnable }: NotificationsProps) {
  const [choices, setChoices] = useState<NotificationCategories>(() => status?.preferences.categories ?? notificationDefaults().categories);
  const generation = status?.preferences.generation;
  const [, tick] = useState(0);
  const clock = now ?? Date.now();
  // Age the prerequisite claim even when the next status read never arrives.
  useEffect(() => {
    if (now !== undefined || !status || status.freshness.state !== 'fresh' || !('known' in status.freshness.snapshot_at)) return;
    const remaining = status.freshness.snapshot_at.known + 70_001 - Date.now();
    if (remaining <= 0 || remaining > 70_001) return;
    const timer = window.setTimeout(() => tick((n) => n + 1), remaining);
    return () => window.clearTimeout(timer);
  }, [status, now]);
  useEffect(() => { setChoices(status?.preferences.categories ?? notificationDefaults().categories); }, [generation]);
  const locked = !status || !!failure || saving || reading;
  const changed = !!status && NOTIFICATION_CATEGORIES.some(([key]) => choices[key] !== status.preferences.categories[key]);
  const fresh = !!status && status.freshness.state === 'fresh' && 'known' in status.freshness.snapshot_at
    && clock >= status.freshness.snapshot_at.known && clock - status.freshness.snapshot_at.known <= 70_000;
  const ready = !!status && !failure && notificationReady(status, clock);
  // A stale or contradictory "ready" report remains visibly unverified.
  const accepted = status?.state === 'accepted' && status.latest?.state === 'accepted';
  const word = status?.state === 'ready' && !ready ? 'Readiness unverified' : status?.state === 'accepted' && !accepted ? 'Acceptance unverified' : status ? notificationStateWord(status.state) : 'Unavailable';
  const enableAvailable = !!onEnable && !!status && !locked && fresh && status.capability.state !== 'unavailable' && status.capability.state !== 'unsupported';
  const latest = status?.latest;
  return <section className="notifications" data-part="notifications" aria-label="Notifications">
    <header className="nt-head">
      <div><p className="section-label">Your attention</p><h2>Notifications</h2><p className="meta">Choose what can interrupt you. Needs you and queue state stay visible in the cockpit.</p></div>
      <button className="btn" type="button" aria-disabled={!onRefresh || reading || saving} onClick={() => { if (onRefresh && !reading && !saving) onRefresh(); }}>Refresh status</button>
    </header>
    <div className="nt-status" aria-live="polite" aria-atomic="true">
      <p className="nt-word"><StatusGlyph tier={word === 'Ready' ? 't2' : 't5'} />{failure ? 'Last read · ' : ''}{word}</p>
      <p>{status?.reason ?? 'Integration unavailable. Notification capability and saved preferences have not been verified.'}</p>
      <p className="meta">{status?.next ?? 'Complete supported delivery setup before enabling notifications.'}</p>
      {status?.state === 'ready' ? <p className="meta">{ready ? 'Ready means prerequisites checked.' : 'Current prerequisites could not be verified. Refresh status.'} Phone receipt is unverified.</p> : null}
      {status?.state === 'accepted' ? <p className="meta">{accepted ? 'Accepted by the dispatch boundary.' : 'No bound accepted dispatch was read.'} Phone receipt is unverified.</p> : null}
      {failure ? <p className="nt-recovery">{notificationFailureWords(failure)}</p> : null}
      {reading ? <p className="meta">Reading notification status…</p> : null}
      {saving ? <p className="meta">Saving preferences… Keep this operation until its result is confirmed.</p> : null}
      {status ? <p className="meta">{status.coverage.state} coverage · {status.freshness.state === 'unknown' ? `source time unknown: ${'unknown' in status.freshness.snapshot_at ? status.freshness.snapshot_at.unknown : ''}` : `source read ${'known' in status.freshness.snapshot_at ? notificationReadTime(status.freshness.snapshot_at.known) : 'unknown'}${fresh ? '' : ' · stale or unverified'}`}</p> : null}
      {status && status.coverage.gaps.length > 0 ? <ul className="nt-gaps">{status.coverage.gaps.map((g, i) => <li key={i}>{g.source}: {g.reason}</li>)}</ul> : null}
    </div>
    {status ? <div className="nt-prerequisites">
      <div><h3>Capability · {status.capability.state.replaceAll('_', ' ')}</h3><p>Permission: {status.capability.permission}</p><p className="meta">{status.capability.reason} {status.capability.next}</p></div>
      <div><h3>Subscription · {status.subscription.state}</h3><p className="meta">{status.subscription.reason} {status.subscription.next}</p></div>
    </div> : null}
    {latest ? <div className="nt-dispatch" aria-live="polite">
      <p className="nt-word"><StatusGlyph tier="t5" />Last dispatch · {notificationStateWord(latest.state)}</p>
      <p>{latest.reason ?? (latest.state === 'submitting' ? 'Submission began; its outcome is not confirmed.' : 'No accepted dispatch result recorded.')}</p>
      <p className="meta">{latest.state === 'accepted' ? 'Accepted by the dispatch boundary. Phone receipt is unverified.' : ['pending', 'submitting', 'uncertain'].includes(latest.state) ? 'Do not resend. Check this operation’s recorded outcome after reconnecting.' : latest.state === 'failed' ? 'This attempt was positively refused. Check setup before a new eligible alert.' : 'No phone receipt is proven.'} Updated {notificationReadTime(latest.updated_at)}.</p>
    </div> : null}
    <div className="nt-delivery">
      <div><h3>Phone delivery</h3><p className="meta">{status ? status.preferences.enabled ? 'Enabled in saved preferences; setup and permission still apply.' : 'Off in saved preferences.' : 'Saved preferences unknown. Defaults shown below; delivery defaults off.'}</p></div>
      {status?.preferences.enabled ? <button className="btn" type="button" aria-disabled={locked || !onDisable} onClick={() => { if (!locked && onDisable) onDisable(); }}>Turn delivery off</button>
        : <button className="btn" type="button" aria-disabled={!enableAvailable} onClick={() => { if (enableAvailable && onEnable) onEnable(); }}>Enable notifications</button>}
      <p className="meta nt-boundary">Turning delivery or a category off stops future eligible submissions. An already submitted notification cannot be retracted. Saving choices approves no work.</p>
    </div>
    <fieldset className="nt-choices">
      <legend>Events to notify you about</legend>
      <p className="meta">Decisions and factory escalation default on; every other event defaults off. Delivery still requires your explicit enable action.</p>
      <div className="nt-category-grid">{NOTIFICATION_CATEGORIES.map(([key, label, defaultOn]) => {
        const source = status?.sources.find((s) => s.category === key);
        const available = source && 'known' in source.available ? source.available.known ? 'Available' : 'Unavailable' : 'Availability unknown';
        return <label key={key} className="nt-category">
          <input type="checkbox" checked={choices[key]} disabled={!status || !onSave} aria-disabled={locked || !onSave} onChange={(e) => { if (!locked && onSave) setChoices((current) => selectNotificationCategory(current, key, e.target.checked)); }} />
          <span><span className="nt-category-name">{label}</span><span className="meta">Default {defaultOn ? 'on' : 'off'} · {available}</span><span className="meta">{source?.reason ?? 'Source not verified.'}{source && 'unknown' in source.available ? ` ${source.available.unknown}` : ''}</span></span>
        </label>;
      })}</div>
    </fieldset>
    <div className="nt-save"><button className="btn" type="button" aria-disabled={locked || !onSave || !changed} onClick={() => { if (!locked && onSave && changed) onSave(choices); }}>Save event choices</button><p className="meta" role="status">{changed ? 'Unsaved event choices.' : status ? 'Showing saved event choices.' : 'Defaults only; saved choices have not been read.'}</p></div>
  </section>;
}

/**
 * #2035: the settings wired to the actual API. Unmounted until its App mount
 * line is approved. Reads status on mount and on Refresh; each explicit action
 * makes one preference write (Enable re-reads status first and stays inert
 * while capability is unavailable or unsupported). A failed write keeps its
 * operation for an identical repeat; nothing retries on its own.
 */
const PENDING = 'openwiz.notifications.pending';

/** A request deadline the API readers recognise: aborted with reason 'timeout'. */
function deadline(ms = 15_000): { signal: AbortSignal; done: () => void } {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort('timeout'), ms);
  return { signal: controller.signal, done: () => window.clearTimeout(timer) };
}

export function ConnectedNotifications({ fetchImpl = browserFetch }: { fetchImpl?: FetchLike }) {
  const active = useRef(false);
  const readVersion = useRef(0);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; readVersion.current++; };
  }, []);
  const [status, setStatus] = useState<NotificationStatus | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [reading, setReading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  // R1: the one unresolved preference operation (id and body only) is kept in
  // this tab's sessionStorage, saved before its PUT, cleared only when its
  // result is read, and repeated only by the owner's explicit retry.
  const [pending, setPending] = useState<NotificationPreferenceWrite | null>(() => {
    try { return readPendingWrite(browserStorage()?.getItem(PENDING) ?? null); } catch { return null; }
  });
  const read = useCallback(async (): Promise<NotificationStatus | null> => {
    const version = ++readVersion.current;
    setReading(true);
    const d = deadline();
    const r = await readNotificationStatus(fetchImpl, d.signal).finally(d.done);
    if (!active.current || version !== readVersion.current) return null;
    setReading(false);
    if (r === 'stopped') return null;
    if (r.kind !== 'ok') { setFailure(r); return null; }
    setFailure(null);
    setStatus(r.envelope);
    return r.envelope;
  }, [fetchImpl]);
  useEffect(() => { void read(); }, [read]);
  const settle = (write: NotificationPreferenceWrite) => {
    if (!active.current) return;
    const exact = JSON.stringify(write);
    try {
      const storage = browserStorage();
      if (storage?.getItem(PENDING) === exact) storage.removeItem(PENDING);
    } catch { /* retain a stale entry rather than risk deleting a successor */ }
    setPending((current) => JSON.stringify(current) === exact ? null : current);
  };
  const put = async (write: NotificationPreferenceWrite) => {
    if (!active.current) return;
    const storage = browserStorage();
    try {
      if (!storage) throw new Error('no storage');
      storage.setItem(PENDING, JSON.stringify(write));
    } catch {
      setNote('This change’s id can’t be saved in this tab (browser storage is full or off), so it was not sent.');
      return;
    }
    setNote(null);
    setPending(write);
    // A pre-write snapshot cannot update status, failure or reading state.
    readVersion.current++;
    setReading(false);
    setSaving(true);
    const d = deadline();
    const r = await writeNotificationPreferences(fetchImpl, write, d.signal).finally(d.done);
    if (!active.current) return;
    setSaving(false);
    if (r.kind !== 'ok') {
      // A generation conflict positively means this operation changed nothing.
      if (r.kind === 'error' && r.status === 409 && r.error?.kind === 'generation_conflict') settle(write);
      setFailure(r);
      return;
    }
    settle(write);
    // Show the saved choice now; if the follow-up read fails, its failure shows too.
    setStatus((s) => s ? { ...s, preferences: r.envelope } : s);
    await read();
  };
  const act = async (action: NotificationAction) => {
    if (pending) {
      setNote('An earlier change has no confirmed result yet. Retry the same change first; a different change waits until its result is read.');
      return;
    }
    const current = action.kind === 'enable' ? await read() : status;
    const write = current ? notificationWrite(current, action, pending, () => newOpId().slice('web-'.length)) : null; // ids are bare 32 hex
    if (!write) return;
    await put(write);
  };
  return <>
    <Notifications status={status} failure={failure} reading={reading} saving={saving}
      onRefresh={() => { void read(); }} onSave={(categories) => { void act({ kind: 'save', categories }); }}
      onDisable={() => { void act({ kind: 'disable' }); }} onEnable={() => { void act({ kind: 'enable' }); }} />
    {pending && !saving ? <div className="nt-save" aria-live="polite">
      <button className="btn" type="button" onClick={() => { void put(pending); }}>Retry the same change</button>
      <p className="meta">An earlier change has no confirmed result. Retrying repeats exactly that change once; nothing repeats it on its own.</p>
    </div> : null}
    {note ? <p className="meta" role="status">{note}</p> : null}
  </>;
}
