import { FleetProgress } from './FleetProgress.tsx';
import { FleetNeed } from './Fleets.tsx';
import { fleetNeedsYou } from '../fleets.ts';
import type { OpenAnswer } from './NeedsYouAnswer.tsx';
import { StatusGlyph, StatusMark } from './StatusMark.tsx';
// One fleet (#126, spec 3's C2): its graph, drawn by our own code (pills in
// columns by step, arrows between them, each pill a word and a shape), or its
// tickets listed by state when the graph can't be drawn here; then each
// ticket with its state, pull request, CI, verdict, builder and reviewer.
// It keeps no state and reads nothing: C4 gives it the fleet, its width, and
// whether its gaps are open (as App.tsx keeps the inventory's).
//
// The page's CSP allows no inline style, so the graph is SVG drawn with
// presentation attributes, in the stylesheet's own colours (COLOURS).

import { BOX_H, BOX_W, fleetModel, layoutGraph } from '../fleetGraph.ts';
import type { Arrow, Box, BoxLabel, FleetEnvelope, Layout, StateMarker, TicketRow } from '../fleetGraph.ts';
import type { Tier } from '../markers.ts';
import { clockText } from '../present.ts';

export type FleetDetailProps = {
  envelope: FleetEnvelope;
  onAnswer?: OpenAnswer;
  /** The width the view has, in CSS pixels: the graph is drawn only when it fits. */
  width: number;
  now: Date;
  /** Opens an agent's thread. */
  onOpenThread: (thread: string) => void;
  /** Whether the gaps list is open, and its toggle's press. */
  gapsOpen: boolean;
  onToggleGaps: () => void;
};

/** Graph colours share the Observatory surface and status tokens. */
const COLOURS = {
  panel: 'var(--ow-color-panel)',
  gold: 'var(--ow-color-attention)',
  attentionTint: 'var(--ow-color-attention-tint)',
  wiz: 'var(--ow-color-live)',
  liveTint: 'var(--ow-color-live-tint)',
  ink: 'var(--ow-color-text-primary)',
  ink2: 'var(--ow-color-text-secondary)',
  ink3: 'var(--ow-color-text-tertiary)',
  edge: 'var(--ow-color-control-edge)',
} as const;

const LOOK: Record<Tier, { fill: string; stroke: string; dash: string | undefined; text: string }> = {
  t1: { fill: COLOURS.attentionTint, stroke: COLOURS.gold, dash: undefined, text: COLOURS.gold },
  t2: { fill: COLOURS.panel, stroke: COLOURS.edge, dash: undefined, text: COLOURS.ink },
  t3: { fill: COLOURS.liveTint, stroke: COLOURS.wiz, dash: undefined, text: COLOURS.wiz },
  t4: { fill: COLOURS.panel, stroke: COLOURS.edge, dash: undefined, text: COLOURS.ink2 },
  t5: { fill: COLOURS.panel, stroke: COLOURS.ink3, dash: '4 3', text: COLOURS.ink2 },
};
/** An arrowhead's length. */
const HEAD = 6;

/** A state as a word, a glyph and a tier's shape: the glyph is decoration, the word its name. */
function Mark({ marker }: { marker: StateMarker }) {
  return (
    <span className={`mk ${marker.tier}`} data-part="state" data-state={marker.kind} data-tier={marker.tier}>
      <StatusMark tier={marker.tier} word={marker.word} shape={marker.kind} />
    </span>
  );
}

/** One pill: shared status shape, mono ticket number, and uncut sans state/version words. */
function BoxView({ box, label, boxWidth }: { box: Box; label: BoxLabel | undefined; boxWidth: number }) {
  const m = label?.marker ?? { kind: 'unknown', tier: 't5', glyph: '[?]', word: 'unknown' };
  const look = LOOK[m.tier];
  const version = box.outside ? label?.label.slice(`#${box.number} · `.length) : undefined;
  const numberY = box.outside ? 20 : 26;
  return (
    <svg x={box.x} y={box.y} width={boxWidth} height={BOX_H} data-box={box.number} data-state={m.kind} data-tier={m.tier} data-outside={box.outside ? '' : undefined}>
      <rect x={0.75} y={0.75} width={boxWidth - 1.5} height={BOX_H - 1.5} rx={BOX_H / 2} fill={look.fill} stroke={look.stroke} strokeWidth={1} strokeDasharray={look.dash} />
      <svg x={12} y={numberY - 16} width={20} height={20} viewBox="0 0 24 24" data-part="glyph" aria-hidden="true" color={look.text}>
        <StatusGlyph tier={m.tier} shape={m.kind} />
      </svg>
      <text x={40} y={numberY} data-part="label" fill={look.text}>
        <tspan className="graph-ticket-id" unicodeBidi="isolate">#{box.number}</tspan>
        {version === undefined ? null : <tspan x={16} y={36} className="graph-version" unicodeBidi="isolate"> · {version}</tspan>}
      </text>
      <text x={16} y={box.outside ? 52 : 48} data-part="word" fill={look.text}>
        {m.kind === 'unknown' ? 'unknown' : m.word}
      </text>
    </svg>
  );
}

/** A curve across each gap between columns, and a straight line through each empty slot it passes. */
function ArrowView({ arrow: a, boxWidth }: { arrow: Arrow; boxWidth: number }) {
  const end = a.x2 - HEAD;
  const curve = (x1: number, y1: number, x2: number, y2: number) => `C ${(x1 + x2) / 2} ${y1} ${(x1 + x2) / 2} ${y2} ${x2} ${y2}`;
  let from = { x: a.x1, y: a.y1 };
  const steps: string[] = [];
  for (const v of a.via) {
    steps.push(curve(from.x, from.y, v.x, v.y), `L ${v.x + boxWidth} ${v.y}`);
    from = { x: v.x + boxWidth, y: v.y };
  }
  steps.push(curve(from.x, from.y, end, a.y2));
  return (
    <g data-arrow={`${a.from}-${a.to}`}>
      <path d={`M ${a.x1} ${a.y1} ${steps.join(' ')}`} fill="none" stroke={COLOURS.edge} strokeWidth={1} />
      <path d={`M ${a.x2} ${a.y2} L ${end} ${a.y2 - 4} L ${end} ${a.y2 + 4} Z`} fill={COLOURS.edge} />
    </g>
  );
}

/** Arrows first, so a box covers any arrow that passes behind it. */
function Graph({ spec, layout, labels, boxWidth }: { spec: number; layout: Extract<Layout, { kind: 'drawn' }>; labels: ReadonlyMap<number, BoxLabel>; boxWidth: number }) {
  return (
    <svg
      data-graph=""
      role="img"
      aria-label={`the graph of #${spec}: ${layout.boxes.length} boxes and ${layout.arrows.length} arrows; each ticket is listed below`}
      width={layout.width}
      height={layout.height}
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      fontFamily="var(--ow-font-sans)"
      fontSize={13}
    >
      {layout.arrows.map((a) => (
        <ArrowView key={`${a.from}-${a.to}`} arrow={a} boxWidth={boxWidth} />
      ))}
      {layout.boxes.map((b) => (
        <BoxView key={b.number} box={b} label={labels.get(b.number)} boxWidth={boxWidth} />
      ))}
    </svg>
  );
}

/**
 * A ticket: its number and title, then its facts, all wrapping as needed.
 * Not the session rows' classes: from 1200 px those lay a row out on one grid line.
 */
function TicketItem({ ticket: t, onOpenThread }: { ticket: TicketRow; onOpenThread: (thread: string) => void }) {
  const thread = 'thread' in t.builder ? t.builder.thread : null;
  return (
    <li className="said" data-ticket={t.number}>
      <div className={`title${t.title.unknown ? ' unknown' : ''}`} data-part="title-line">
        <span className="ticket-id">#{t.number}</span> <bdi data-part="title">{t.title.text}</bdi>
      </div>
      <div className="inv" data-part="facts">
        <Mark marker={t.marker} />
        <span className="effect" data-fact="pr">
          {t.pr}
        </span>
        {t.ci === null ? null : (
          <span className="effect" data-fact="ci">
            {t.ci}
          </span>
        )}
        {t.review === null ? null : (
          <span className="effect" data-fact="review">
            {t.review}
          </span>
        )}
        {t.waits === null ? null : (
          <span className="effect" data-fact="waits">
            {t.waits}
          </span>
        )}
        {thread === null ? (
          <span className="effect" data-fact="builder">
            {'text' in t.builder ? t.builder.text : null}
          </span>
        ) : (
          <button type="button" className="btn" data-thread={thread} onClick={() => onOpenThread(thread)}>
            <span>
              builder <bdi className="ticket-id">{thread}</bdi>
            </span>
          </button>
        )}
        <span className="effect" data-fact="reviewer">
          {t.reviewer}
        </span>
      </div>
    </li>
  );
}

/** Why the graph isn't drawn here, in words; null when it is. */
function notDrawn(layout: Layout | { kind: 'unread'; reason: string }): string | null {
  const below = 'its tickets are listed by state below';
  switch (layout.kind) {
    case 'drawn':
      return null;
    case 'too_wide':
      return `the graph needs ${layout.needed} px and this screen has ${layout.width} px: ${below}`;
    case 'loop':
      return `the graph isn't drawn: the blocked-by links loop through ${layout.numbers.map((n) => `#${n}`).join(', ')}; ${below}`;
    case 'unread':
      return `the graph isn't drawn: ${layout.reason}; ${below}`;
  }
}

/**
 * The fleet's coverage, as the page head's (design rule 10): `complete`, or
 * partial's dashed tag; with gaps, the tag sits in a 44 px toggle with its
 * caret.
 */
function Coverage({ partial, gaps, open, onToggle }: { partial: boolean; gaps: number; open: boolean; onToggle: () => void }) {
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

export function FleetDetail({ envelope, width, now, onOpenThread, gapsOpen, onToggleGaps, onAnswer }: FleetDetailProps) {
  const m = fleetModel(envelope);
  const needs = fleetNeedsYou(envelope);
  // Widen for long ids or outside versions rather than clipping a word. The
  // layout's existing width fallback remains the gate for drawing the graph.
  const boxWidth = m.graph.kind === 'input' ? Math.max(BOX_W, ...[...m.graph.labels].map(([number, label]) =>
    Math.max(String(number).length * 8 + 64, (label.label.length - `#${number} · `.length) * 8 + 32),
  )) : BOX_W;
  const layout = m.graph.kind === 'input' ? layoutGraph(m.graph.input, width, boxWidth) : m.graph;
  const why = notDrawn(layout);
  const item = (t: TicketRow) => <TicketItem key={t.number} ticket={t} onOpenThread={onOpenThread} />;
  return (
    <section className="fleet-detail" data-fleet={m.spec}>
      <header className="fleet-heading">
        <div>
          <h2 className="disp s">
            <span className="fleet-id">#{m.spec}</span> <bdi>{m.title.text}</bdi>
          </h2>
          <p className="meta">
            read {clockText(m.snapshotAt, now)} · <Coverage partial={m.partial} gaps={m.gaps.length} open={gapsOpen} onToggle={onToggleGaps} />
          </p>
        </div>
        <div className="fleet-completion">
          <p data-part="progress">{m.progress}</p>
          <FleetProgress counts={'known' in envelope.data.fleet.progress ? envelope.data.fleet.progress.known : null} />
        </div>
      </header>
      {gapsOpen && m.gaps.length > 0 ? (
        <ul className="gaps" data-part="gaps">
          {m.gaps.map((g) => (
            <li key={g.read}>
              <bdi>{`${g.gap} · ${g.read} ${g.subject} · ${g.reason}`}</bdi>
            </li>
          ))}
        </ul>
      ) : null}
      {needs.kind === 'unread' || needs.items.length > 0 ? (
        <section className="fleet-needs" data-part="needs-you">
          <h3 className="sec">Needs you</h3>
          {needs.kind === 'unread' ? (
            <p className={`mk ${needs.marker.tier}`} data-part="needs-you-empty" data-kind="unread">
              <StatusMark tier={needs.marker.tier} word={needs.marker.word} />
            </p>
          ) : (
            <ul className="rows">
              {needs.items.map((need) => <FleetNeed key={`${need.kind}-${need.ticket}-${need.spec}`} item={need} orchestrator={envelope.orchestrator} onAnswer={onAnswer} />)}
            </ul>
          )}
        </section>
      ) : null}
      <section className="fleet-graph">
        <h3 className="sec">graph</h3>
        {why !== null ? (
          <p className="effect" data-fallback={layout.kind}>
            {why}
          </p>
        ) : m.tickets.length === 0 ? (
          <p className="effect" data-fallback="empty">
            no tickets
          </p>
        ) : layout.kind === 'drawn' && m.graph.kind === 'input' ? (
          <Graph spec={m.spec} layout={layout} labels={m.graph.labels} boxWidth={boxWidth} />
        ) : null}
      </section>
      <section className="fleet-tickets">
        <h3 className="sec">tickets</h3>
        {m.groups.map((g) => (
          <section key={g.marker.kind} data-state-group={g.marker.kind}>
            <h4 className="kicker">
              <Mark marker={g.marker} /> <span className="fleet-group-count">{g.tickets.length}</span>
            </h4>
            <ul className="rows">{g.tickets.map(item)}</ul>
          </section>
        ))}
      </section>
    </section>
  );
}
