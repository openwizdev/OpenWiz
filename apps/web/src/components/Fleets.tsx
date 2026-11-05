import { FleetProgress } from './FleetProgress.tsx';
import type { Counts } from '../fleetGraph.ts';
import { ChevronIcon } from './Icons.tsx';
import { StatusGlyph, StatusMark } from './StatusMark.tsx';
// The fleets list (#125, spec 3's C1): "Needs you" at the very top, each item
// saying what it needs and from which fleet; then one row per fleet, with its
// spec's name, "N of M merged", and how many tickets are moving or blocked.
// Every state is a word, a glyph and a shape; unknowns and partial answers
// say why. It keeps no state and reads nothing: C4 gives it the fleets,
// whether the read is fresh, and whether its gaps are open (as App.tsx keeps
// the inventory's), and opens a fleet on a press.

import { fleetsList } from '../fleets.ts';
import type { FleetRow, FleetsEnvelope, FleetsMarker, NeedItem } from '../fleets.ts';
import type { FleetGap, Text } from '../fleetGraph.ts';
import { clockText } from '../present.ts';
import { NeedsYouAnswer } from './NeedsYouAnswer.tsx';
import type { OpenAnswer } from './NeedsYouAnswer.tsx';

export type FleetsProps = {
  home?: boolean;
  envelope: FleetsEnvelope;
  now: Date;
  /** A complete, successful, fresh read: only then "No fleets" and "Nothing needs you" (design rule 11). */
  fresh: boolean;
  /** Whether the gaps list is open, and its toggle's press. */
  gapsOpen: boolean;
  onToggleGaps: () => void;
  /** Opens a fleet's own view (C2's), by its spec. */
  onOpen: (spec: number) => void;
  onAnswer?: OpenAnswer;
};

/** Presentation only: preserve the reported text, isolating digits for numeric emphasis. */
function numerals(text: string) {
  return text.split(/(\d+)/).map((part, i) => i % 2 ? <span className="fleet-numeral" key={i}>{part}</span> : part);
}

/** A state as a word, a glyph and a tier's shape: the glyph is decoration, the word its name. */
function Mark({ marker, numeric = false }: { marker: FleetsMarker; numeric?: boolean }) {
  return (
    <span className={`mk ${marker.tier}`} data-part="state" data-kind={marker.kind} data-tier={marker.tier}>
      <StatusMark tier={marker.tier} word={numeric ? numerals(marker.word) : marker.word} shape={marker.kind} />
    </span>
  );
}

/** An issue's number and title, cut to fit as a session's; an unknown one in italic, with why. */
function Title({ number, title }: { number: number; title: Text }) {
  return (
    <span className={`title${title.unknown ? ' unknown' : ''}`} data-part="title">
      <span className="ref-id">#{number}</span> <bdi>{title.text}</bdi>
    </span>
  );
}

/** A "needs you" item: its ticket, what it needs, and from which fleet. It shows; answering it is C5's. */
export function FleetNeed({ item, orchestrator, onAnswer }: { item: NeedItem; orchestrator?: string; onAnswer?: OpenAnswer }) {
  return (
    <li>
      <div className="row" data-need={item.kind} data-ticket={item.ticket} data-spec={item.spec}>
        <span className="row-top">
          <Title number={item.ticket} title={item.title} />
        </span>
        <span className="row-meta">
          <Mark marker={item.marker} />
          <span className="reason" data-part="reason">
            <span data-part="need">{item.need}</span>
            <span data-part="sep" aria-hidden="true">
              {' · '}
            </span>
            <span data-part="from">
              from <span className="ref-id">#{item.spec}</span> <bdi>{item.fleet.text}</bdi>
            </span>
          </span>
        </span>
        <span className="row-meta" data-part="question-facts">
          <span className="reason">
            <span className={item.question.unknown ? 'unknown' : undefined} data-part="question"><bdi>{item.question.text}</bdi></span>
            {item.asked === null ? null : <><span data-part="sep" aria-hidden="true">{' · '}</span><span className={item.asked.unknown ? 'unknown' : undefined} data-part="asked">{item.asked.text}</span></>}
            {item.link === null ? null : <><span data-part="sep" aria-hidden="true">{' · '}</span><span className={item.link.unknown ? 'unknown' : undefined} data-part="link"><bdi>{item.link.text}</bdi></span></>}
            <span data-part="sep" aria-hidden="true">{' · '}</span>
            <span className={item.risk.unknown ? 'unknown' : undefined} data-part="risk">{item.risk.text}</span>
          </span>
        </span>
        <NeedsYouAnswer item={item} orchestrator={orchestrator} onAnswer={onAnswer} />
      </div>
    </li>
  );
}

/**
 * A fleet's row: its title and "N of M merged" on the first line, its counts
 * on the second, in the row's reason slot, so from 1200 px they sit under
 * the title instead of sharing the 128 px status column. A press opens it.
 */
function Row({ row, progress, onOpen }: { row: FleetRow; progress: Counts | null; onOpen: (spec: number) => void }) {
  return (
    <li>
      <button type="button" className="row fleet-row" data-fleet={row.spec} onClick={() => onOpen(row.spec)}>
        <span className="row-top">
          <Title number={row.spec} title={row.title} />
          {row.merged === null ? null : (
            <span className="age" data-part="progress">
              {numerals(row.merged)}
            </span>
          )}
        </span>
        <FleetProgress counts={progress} />
        <span className="row-meta">
          <span className="reason" data-part="counts">
            {row.counts.map((c, i) => (
              <span key={c.kind}>
                {i > 0 ? (
                  // Wide enough that a tier's box, hanging 6 px outside its text, keeps clear of the dot.
                  <span data-part="sep" aria-hidden="true">
                    {' \u00a0·\u00a0 '}
                  </span>
                ) : null}
                <Mark marker={c} numeric={progress !== null} />
              </span>
            ))}
          </span>
        </span>
      </button>
    </li>
  );
}

/**
 * The envelope's coverage, as the page head's (design rule 10): `complete`,
 * or partial's dashed tag; with gaps, the tag sits in a 44 px toggle with its
 * caret.
 */
function Coverage({ home = false, partial, gaps, open, onToggle }: { home?: boolean; partial: boolean; gaps: number; open: boolean; onToggle: () => void }) {
  if (home) {
    const chip = <span className={`status-chip coverage-chip${partial ? ' is-partial' : ''}`}><StatusGlyph tier={partial ? 't5' : 't2'} /><span data-part="coverage">{partial ? `partial · ${gaps} ${gaps === 1 ? 'gap' : 'gaps'}` : 'complete'}</span>{gaps > 0 ? <ChevronIcon open={open} /> : null}</span>;
    return gaps > 0 ? <button type="button" className="cov" aria-label="Fleet coverage details" aria-expanded={open} onClick={onToggle}>{chip}</button> : chip;
  }
  if (gaps === 0) {
    return partial ? (
      <span className="tag dashed" data-part="coverage">
        partial · 0 gaps
      </span>
    ) : (
      <span data-part="coverage">complete</span>
    );
  }
  return (
    <button type="button" className="cov" aria-expanded={open} onClick={onToggle}>
      <span className={partial ? 'tag dashed' : undefined} data-part="coverage">
        {partial ? `partial · ${gaps} ${gaps === 1 ? 'gap' : 'gaps'}` : 'complete'}
      </span>
      <span aria-hidden="true">{open ? '▴' : '▾'}</span>
    </button>
  );
}

function Gaps({ gaps }: { gaps: FleetGap[] }) {
  return (
    <ul className="gaps" data-part="gaps">
      {gaps.map((g) => (
        <li key={g.read}>
          <bdi>{`${g.gap} · ${g.read} ${g.subject} · ${g.reason}`}</bdi>
        </li>
      ))}
    </ul>
  );
}

export function Fleets({ home = false, envelope, now, fresh, gapsOpen, onToggleGaps, onOpen, onAnswer }: FleetsProps) {
  const m = fleetsList(envelope);
  const asOf = clockText(m.snapshotAt, now);
  const needs = m.needsYou;
  const list = m.list;
  const NeedsList = home ? 'ol' : 'ul';
  return (
    <div data-part="fleets">
      <section data-part="needs-you">
        <h2 className="kicker">Needs you</h2>
        {needs.kind === 'unread' ? (
          <div className="empty" data-part="needs-you-empty" data-kind="unread">
            <Mark marker={needs.marker} />
          </div>
        ) : needs.items.length === 0 ? (
          <div className="empty" data-part="needs-you-empty" data-kind="none">
            <p className="body">{home && m.partial ? 'No Needs you items read: the snapshot is partial' : fresh ? 'Nothing needs you' : `Nothing needed you as of ${asOf}`}</p>
          </div>
        ) : (
          <NeedsList className={`rows${home ? ' numbered-needs' : ''}`}>
            {needs.items.map((item) => (
              <FleetNeed key={`${item.kind}-${item.ticket}-${item.spec}`} item={item} orchestrator={envelope.orchestrator} onAnswer={onAnswer} />
            ))}
          </NeedsList>
        )}
      </section>
      <section data-part="fleet-list">
        <h2 className="kicker">{home ? 'Fleets at a glance' : 'Fleets'}</h2>
        <p className="inv">
          <Coverage home={home} partial={m.partial} gaps={m.gaps.length} open={gapsOpen} onToggle={onToggleGaps} />
          <span aria-hidden="true">·</span>
          <span data-part="snapshot">snapshot {asOf}</span>
        </p>
        {gapsOpen && m.gaps.length > 0 ? <Gaps gaps={m.gaps} /> : null}
        {list.kind === 'partial' ? (
          <p className="inv">
            <span className="tag dashed" data-part="list-partial">
              partial list: <bdi>{list.reason}</bdi>
            </span>
          </p>
        ) : null}
        {list.kind === 'unread' ? (
          <div className="empty" data-part="fleets-empty" data-kind="unread">
            <Mark marker={list.marker} />
          </div>
        ) : m.fleets.length === 0 ? (
          <div className="empty" data-part="fleets-empty" data-kind={list.kind === 'complete' ? 'none' : 'none-partial'}>
            <p className="body">{list.kind === 'partial' ? 'No fleets read: the list is partial' : fresh ? 'No fleets' : `No fleets as of ${asOf}`}</p>
          </div>
        ) : null}
        {m.fleets.length > 0 ? (
          <ul className="rows">
            {m.fleets.map((row) => {
              const progress = envelope.data.fleets.find((f) => f.spec === row.spec)?.progress;
              return <Row key={row.spec} row={row} progress={progress && 'known' in progress ? progress.known : null} onOpen={onOpen} />;
            })}
          </ul>
        ) : null}
      </section>
    </div>
  );
}
