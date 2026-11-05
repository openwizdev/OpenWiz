import type { Failure } from '../api.ts';
import type { Envelope, Inventory } from '../envelope.ts';
import { statusMarker } from '../markers.ts';
import { factText, groupPage, pageRange } from '../present.ts';
import { SessionRow } from './Inventory.tsx';
import { ConnectionGlyph, CoverageChip, Notice } from './Status.tsx';

/** The active subset of the existing inventory page, in its presentation order. No independent read. */
export function HomeLive({ envelope, stale, failure, now, onSelect, onRetry }: {
  envelope: Envelope<Inventory> | null;
  stale: boolean;
  failure: Failure | null;
  now: Date;
  onSelect: (id: string) => void;
  onRetry: () => void;
}) {
  const groups = envelope ? groupPage(envelope.data.sessions) : [];
  const rows = groups.flatMap((g) => g.sessions
    .filter((s) => statusMarker(s.status).word === 'active')
    .map((session) => ({ session, project: g.group.kind === 'project' ? `${factText(g.group.name)}${g.suffix === null ? '' : ` · ${g.suffix}`}` : `ungrouped (${g.group.reason})` })));
  const range = envelope?.coverage.counts ? pageRange(envelope.coverage.counts) : null;
  const paged = range !== null && (range.previousOffset !== null || range.nextOffset !== null);
  const qualified = stale || failure !== null || envelope?.coverage.state === 'partial' || paged;
  return <section className="home-live" data-part="home-live" aria-labelledby="home-live-heading">
    <h2 id="home-live-heading" className="kicker">Live now</h2>
    <p className="meta home-live-scope">Active sessions on this listed page{paged ? ` · sessions ${range.first}–${range.last} of ${range.matched}` : ''}</p>
    <div className="inv">
      {envelope ? <CoverageChip envelope={envelope} now={now} /> : null}
      {stale ? <span className="status-chip" data-part="stale"><ConnectionGlyph connection="stale" /> stale</span> : null}
    </div>
    {envelope && envelope.gaps.length > 0 ? <ul className="gaps" data-part="gaps">{envelope.gaps.map((g, i) => <li key={i}><bdi>{g.kind}{g.subject === null ? null : <>{' · '}<span className="ref-id">{g.subject}</span></>}{` · ${g.detail}`}</bdi></li>)}</ul> : null}
    {failure ? <Notice failure={failure} lastGoodAt={envelope?.freshness.snapshot_at ?? null} now={now} onRetry={onRetry} /> : null}
    {rows.length > 0 ? <ul className="rows">{rows.map(({ session, project }) => <SessionRow key={session.id} session={session} project={project} selected={false} onSelect={onSelect} />)}</ul>
      : envelope ? <p className="meta">{qualified ? 'No active sessions listed in this snapshot' : 'No active sessions'}</p>
      : failure ? null : <p className="meta" role="status"><ConnectionGlyph connection="reading" /> reading sessions…</p>}
  </section>;
}
