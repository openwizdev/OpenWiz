import { Button, SoftPanel } from './Ui.tsx';
import type { ReactNode } from 'react';
import { StatusGlyph, StatusMark } from './StatusMark.tsx';
// Status as a word and a shape: the session marker (V2), the connection pill
// and the notice that says what went wrong (V6). Session text is plain text,
// isolated for bidirectional text (V3).

import type { Failure } from '../api.ts';
import type { Envelope, FactString } from '../envelope.ts';
import { statusMarker } from '../markers.ts';
import { clockText } from '../present.ts';
import type { Connection } from '../viewer.ts';

export function Marker({ status }: { status: FactString }) {
  const m = statusMarker(status);
  return (
    <span className={`mk ${m.tier}`} data-part="status" data-tier={m.tier}>
      <StatusMark tier={m.tier} word={m.word} />
    </span>
  );
}

const CONNECTION_WORDS: Record<Connection, string> = {
  reading: 'reading',
  live: 'live',
  stale: 'stale',
  disconnected: 'disconnected',
  'signed-out': 'signed out',
  busy: 'busy',
  error: 'error',
};

/** A single quiet chip family for the provenance of a read and its connection. */
export function CoverageChip({ envelope, now, detail = false, readDescriptionId, children }: { envelope: Envelope<unknown>; now: Date; detail?: boolean; readDescriptionId?: string; children?: ReactNode }) {
  const partial = envelope.coverage.state === 'partial';
  const gaps = envelope.gaps.length;
  const word = partial ? `partial · ${gaps} ${gaps === 1 ? 'gap' : 'gaps'}` : 'complete';
  const at = clockText(envelope.freshness.snapshot_at, now);
  const read = <time data-field={detail ? 'snapshot' : undefined} data-part={detail ? undefined : 'snapshot'} title={clockText(envelope.freshness.snapshot_at, now)}>{at}</time>;
  const icon = <StatusGlyph tier={partial ? 't5' : 't2'} />;
  const className = `status-chip coverage-chip${partial ? ' is-partial' : ''}`;
  if (detail) return <dl className={className}>
    <dt className="chip-label">coverage</dt>
    <dd data-field="coverage">{icon}<span className="chip-state" data-part="detail-coverage">{envelope.coverage.state}</span>{partial ? ` · ${gaps} ${gaps === 1 ? 'gap' : 'gaps'}` : null}</dd>
    <dt className="chip-label">snapshot</dt>
    <dd className="chip-read">· read {read}</dd>
  </dl>;
  return <span className={className}>
    {icon}<span className="chip-state" data-part="coverage">{word}</span>
    <span className="chip-read" id={readDescriptionId} aria-hidden={readDescriptionId ? true : undefined}>· read {read}</span>
    {children}
  </span>;
}

export function ConnectionGlyph({ connection }: { connection: Connection }) {
  if (connection === 'live') return <StatusGlyph tier="t3" />;
  return <svg className="status-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {connection === 'stale' ? <><circle cx="12" cy="12" r="8" /><path d="M12 7v5l3 2" /></>
      : connection === 'signed-out' ? <><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" /></>
      : connection === 'error' ? <><path d="m12 3 9 9-9 9-9-9Z" /><path d="M12 8v5M12 16h.01" /></>
      : connection === 'disconnected' ? <><path d="M8 5v5m8-5v5M6 10h12v2a6 6 0 0 1-6 6v3M3 3l18 18" /></>
      : connection === 'busy' ? <><path d="M6 3h12M6 21h12M7 3v4l10 10v4M17 3v4L7 17v4" /></>
      : <circle cx="12" cy="12" r="8" strokeDasharray="3 3" />}
  </svg>;
}

export function ConnectionPill({ connection, read }: { connection: Connection; read?: string }) {
  return (
    <p className="conn status-chip" data-connection={connection} role="status">
      <span className="shape" aria-hidden="true"><ConnectionGlyph connection={connection} /></span>
      <span className="word">{connection === 'live' ? 'Connected' : CONNECTION_WORDS[connection]}</span>
      {read ? <span className="connection-read chip-read">· read {read}</span> : null}
    </p>
  );
}

function why(f: Failure): string {
  switch (f.kind) {
    case 'signed-out':
      return 'your sign-in has expired';
    case 'disconnected':
      if (f.cause === 'timeout') return 'can’t reach OpenWiz on your Mac: no answer in time';
      if (f.cause === 'gateway') return `can’t reach OpenWiz on your Mac: HTTP ${f.status ?? ''} from the network`;
      return 'can’t reach OpenWiz on your Mac';
    case 'busy':
      return 'the server is busy; retrying';
    case 'error':
      return `unexpected response (HTTP ${f.status})`;
  }
}

const TITLES: Record<Failure['kind'], string> = {
  'signed-out': 'Signed out',
  disconnected: 'Disconnected',
  busy: 'Busy',
  error: 'Error',
};

/** What went wrong, in the server's or the core's own words when it gave any, and the last good snapshot. */
export function Notice({ failure, lastGoodAt, now, onRetry, sessionState = false }: { failure: Failure; lastGoodAt: number | null; now: Date; onRetry?: () => void; sessionState?: boolean }) {
  const words = (failure.kind === 'error' || failure.kind === 'busy') && failure.error ? failure.error : null;
  return (
    <SoftPanel className={`notice${sessionState ? ' session-state' : ''}`} data-notice={failure.kind}>
      {sessionState ? <span className="session-state-tile" aria-hidden="true"><span className="shape" /></span> : null}
      <p className="notice-head">
        {sessionState ? null : <span className="shape" aria-hidden="true" />} <b>{TITLES[failure.kind]}</b>
      </p>
      <p className="notice-body">
        {words ? (
          <>
            <code>{words.kind}</code>: <bdi>{words.message}</bdi>
          </>
        ) : (
          why(failure)
        )}
      </p>
      <p className="meta">{lastGoodAt === null ? 'no snapshot yet' : `last good snapshot ${clockText(lastGoodAt, now)}`}</p>
      {onRetry && failure.kind !== 'signed-out' ? <Button variant={sessionState ? 'primary' : 'secondary'} onClick={onRetry}>Retry</Button> : null}
      {failure.kind === 'signed-out' ? (
        <a className="btn" href="/">
          Sign in again
        </a>
      ) : null}
    </SoftPanel>
  );
}
