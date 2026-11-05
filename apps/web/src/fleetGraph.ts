// One fleet's view (#126, spec 3's C2): the shapes of `openwiz fleet <spec>
// --json` it reads (contracts/fleet.v1.md), what the view shows of them, and
// the graph's layout. Not wired to the page yet (C4 does that, through a
// reader that checks the JSON); these types are the contract's, for the
// fleet view.

import type { Tier } from './markers.ts';
import { unknownText } from './present.ts';

// ── the contract's shapes (contracts/fleet.v1.schema.json) ──

export type GapKind = 'untested_version' | 'command_failed' | 'timed_out' | 'budget_exhausted' | 'malformed' | 'missing_field' | 'wrong_type' | 'not_found';
export type Failed = { state: 'failed'; gap: GapKind; reason: string };
export type Outcome<T> = { state: 'complete'; value: T } | Failed;
/** The six list kinds can also be read in part. */
export type ListOutcome<T> = { state: 'complete'; value: T[] } | { state: 'partial'; gap: 'truncated'; reason: string; value: T[] } | Failed;

export type Milestone = { number: number; title: string };
/** #539: the selected question's first line and provenance, only on an issue read of `openwiz fleet <spec>`. */
export type PendingQuestion = { wording: string; link: string; asked_at: number };
export type Issue = { title: string; state: 'open' | 'closed'; milestone: Milestone | null; labels: string[]; owned_paths: string | null; relies_on: string | null; pending_question?: PendingQuestion };
export type OpenPr = { number: number; state: 'open'; draft: boolean; head_branch: string; head_commit: string; base_branch: string; closes: number[] };
export type MergedPr = {
  number: number;
  state: 'merged';
  draft: boolean;
  head_branch: string;
  head_commit: string;
  base_branch: string;
  closes: number[];
  merge_commit: string;
  merged_at: number;
};
export type SeveralPrs = { state: 'several'; numbers: number[] };
export type Check = { name: string; result: 'pass' | 'fail' | 'pending' | 'skipping' | 'cancel' };
export type Review = { verdict: 'approve' | 'changes'; commit: string };
export type Project = { id: string; name: string };
export type Thread = { thread: string; project: string; kind: 'cloud' } | { thread: string; project: string; kind: 'local'; branch: string | null };

export type Read =
  | { id: string; kind: 'version'; source: 'github' | 'cloudroom'; outcome: Outcome<string> }
  | { id: string; kind: 'repository'; outcome: Outcome<{ name: string }> }
  | { id: string; kind: 'spec_list'; outcome: ListOutcome<number> }
  | { id: string; kind: 'issue'; issue: number; outcome: Outcome<Issue> }
  | { id: string; kind: 'sub_issues'; spec: number; outcome: ListOutcome<number> }
  | { id: string; kind: 'blocked_by'; ticket: number; outcome: ListOutcome<number> }
  | { id: string; kind: 'pr_discovery'; issue: number; outcome: Outcome<OpenPr | MergedPr | SeveralPrs | null> }
  | { id: string; kind: 'checks'; pr: number; outcome: ListOutcome<Check> }
  | { id: string; kind: 'comments'; pr: number; outcome: Outcome<Review | null> }
  | { id: string; kind: 'merge_readback'; pr: number; outcome: Outcome<boolean> }
  | { id: string; kind: 'projects'; outcome: ListOutcome<Project> }
  | { id: string; kind: 'threads'; outcome: ListOutcome<Thread> }
  | { id: string; kind: 'workspace'; thread: string; outcome: Outcome<string> };

export type Unread = { unread: string[] };
export type TicketState = 'ready' | 'building' | 'in_review' | 'changes_requested' | 'merged' | 'held' | 'blocked';
export type Counts = Record<TicketState | 'tickets' | 'unknown', number>;
export type FleetTicket = {
  number: number;
  issue: string;
  blocked_by: string;
  pr: string;
  ci: string | null;
  review: string | null;
  on_base: string | null;
  state: { known: TicketState } | Unread | { unknown: string };
  builder: { known: string | null } | Unread;
  reviewer: { undefined: string };
};
export type Blocker = {
  number: number;
  issue: string;
  pr: string;
  on_base: string | null;
  fleet: { known: number | null } | Unread;
  merged: { known: boolean } | Unread;
};
/** A fact as the contract writes it: known, or unknown with a reason. */
export type Known<T> = { known: T } | { unknown: string };
export type NeedsRisk = 'live' | 'release' | 'publish';
/** #539: each item's question (from the ticket's own comment) and its labelled risk, or why not. */
export type NeedsYou = { kind: 'needs_info' | 'held'; spec: number; ticket: number; wording: Known<string>; link: Known<string>; asked_at: Known<number>; risk: Known<NeedsRisk> };
export type Unplaced = { thread: string; reason: 'no_branch' | 'shared_branch' | 'no_pull_request' | 'several_tickets' | 'several_issues' };
export type FleetView = {
  view: 'fleet';
  repository: string;
  projects: string;
  threads: string;
  fleet: { spec: number; issue: string; tickets: string; progress: { known: Counts } | Unread };
  tickets: FleetTicket[];
  blockers: Blocker[];
  needs_you: { known: NeedsYou[] } | Unread;
  unplaced: { known: Unplaced[] } | Unread;
};
type Source<N> = { name: N; version: string; tested_version: string; version_tested: boolean };
export type FleetEnvelope = {
  orchestrator?: string;
  schema: 'openwiz.fleet.v1';
  sources: { github: Source<'gh'>; cloudroom: Source<'room-cli'> };
  reads: Read[];
  coverage: { state: 'complete' | 'partial' };
  freshness: { snapshot_at: number };
  data: FleetView;
};

// ── what the view shows ──

/** A ticket's state, a blocker's merge (`not_merged`), or `unknown` (unknown or unread). */
export type MarkerKind = TicketState | 'not_merged' | 'unknown';
/** A word, a glyph and a tier's shape (docs/design-rules.md, "Markers"). */
export type StateMarker = { kind: MarkerKind; tier: Tier; glyph: string; word: string };

export type Text = { text: string; unknown: boolean };
export type TicketRow = {
  number: number;
  title: Text;
  marker: StateMarker;
  pr: string;
  ci: string | null;
  review: string | null;
  waits: string | null;
  builder: { thread: string } | { text: string };
  reviewer: string;
};
export type StateGroup = { marker: StateMarker; tickets: TicketRow[] };
/** A box's first line (`#126`, or an outside blocker's `#16 · 0.0.4`) and its marker. */
export type BoxLabel = { label: string; marker: StateMarker };
export type FleetGraph = { kind: 'input'; input: GraphInput; labels: ReadonlyMap<number, BoxLabel> } | { kind: 'unread'; reason: string };
/** A read that isn't complete (the contract's gaps): its id, what it read (`kind(param)`), its gap and its own reason. */
export type FleetGap = { read: string; subject: string; gap: string; reason: string };
export type FleetModel = {
  spec: number;
  title: Text;
  progress: string;
  snapshotAt: number;
  partial: boolean;
  /** Every read that isn't complete, in the order of reads: why the fleet is partial. */
  gaps: FleetGap[];
  graph: FleetGraph;
  /** In the view's order, beside a drawn graph. */
  tickets: TicketRow[];
  /** The same tickets grouped by state, in the contract's order of states, when the graph isn't drawn. */
  groups: StateGroup[];
};

/**
 * Each kind's tier and glyph: the builder's proposal, Open for Jake, as the
 * session words' are (docs/design-rules.md, "Markers"). By the tiers'
 * meanings: held waits on you (t1); merged is done and read back (t2); the
 * three the contract counts as moving are t3; the rest are quiet (t4);
 * unknown and unread are unsure (t5). Every kind has its own glyph.
 */
const MARKERS: Record<MarkerKind, readonly [Tier, string]> = {
  held: ['t1', '[!]'],
  merged: ['t2', '[✓]'],
  building: ['t3', '[~]'],
  in_review: ['t3', '[>]'],
  changes_requested: ['t3', '[<]'],
  ready: ['t4', '[ ]'],
  blocked: ['t4', '[‖]'],
  not_merged: ['t4', '[-]'],
  unknown: ['t5', '[?]'],
};
/** The contract's states, in its order (its `ticket_state`). */
const TICKET_STATES: readonly string[] = ['ready', 'building', 'in_review', 'changes_requested', 'merged', 'held', 'blocked'];
const isTicketState = (word: string): word is TicketState => TICKET_STATES.includes(word);
/** The list by state: the contract's order, then unknown. */
const BY_STATE: readonly MarkerKind[] = [...TICKET_STATES.filter(isTicketState), 'unknown'];

const marker = (kind: MarkerKind, word: string): StateMarker => ({ kind, tier: MARKERS[kind][0], glyph: MARKERS[kind][1], word });

type Reads = ReadonlyMap<string, Read>;
const index = (reads: readonly Read[]): Reads => new Map(reads.map((r) => [r.id, r]));

function isKind<K extends Read['kind']>(r: Read, kind: K): r is Extract<Read, { kind: K }> {
  return r.kind === kind;
}

/** The read a pointer names, only when it is of the kind its value needs. */
function find<K extends Read['kind']>(reads: Reads, id: string, kind: K): Extract<Read, { kind: K }> | null {
  const r = reads.get(id);
  return r !== undefined && isKind(r, kind) ? r : null;
}

type Got<T> = { ok: true; value: T } | { ok: false; why: string };

/** A read's value when it was read in full; otherwise why not, in its own words. A partial list is never a value. */
function got<K extends Read['kind']>(reads: Reads, id: string, kind: K): Got<Extract<Extract<Read, { kind: K }>['outcome'], { state: 'complete' }>['value']> {
  const outcome = find(reads, id, kind)?.outcome;
  if (outcome === undefined) return { ok: false, why: `the ${kind} read ${id} isn't on the record` };
  return outcome.state === 'complete' ? { ok: true, value: outcome.value } : { ok: false, why: outcome.reason };
}

const unread = (why: string) => unknownText(`unread: ${why}`);

/** What an unread value lacks: each of its reads' own reasons, once each, in order. */
function whyUnread(reads: Reads, ids: readonly string[]): string {
  const why = ids.map((id) => {
    const o = reads.get(id)?.outcome;
    return o === undefined ? `read ${id} isn't on the record` : o.state === 'complete' ? `read ${id} is complete, yet named unread` : o.reason;
  });
  return why.length === 0 ? 'no read named' : [...new Set(why)].join('; ');
}

/** A word outside the contract's list is unsure (t5), word for word: never guessed. */
function stateMarker(state: FleetTicket['state'], reads: Reads): StateMarker {
  if ('known' in state) return marker(isTicketState(state.known) ? state.known : 'unknown', state.known);
  return marker('unknown', 'unknown' in state ? unknownText(state.unknown) : unread(whyUnread(reads, state.unread)));
}

function mergeMarker(merged: Blocker['merged'] | undefined, reads: Reads): StateMarker {
  if (merged === undefined) return marker('unknown', unknownText('not on the record as a blocker'));
  if ('known' in merged) return merged.known ? marker('merged', 'merged') : marker('not_merged', 'not merged');
  return marker('unknown', unread(whyUnread(reads, merged.unread)));
}

/** A ticket's state as a word, a glyph and a tier. */
export function ticketMarker(state: FleetTicket['state'], reads: readonly Read[]): StateMarker {
  return stateMarker(state, index(reads));
}

/** A blocker's merge as a word, a glyph and a tier. */
export function blockerMarker(merged: Blocker['merged'], reads: readonly Read[]): StateMarker {
  return mergeMarker(merged, index(reads));
}

function titleOf(reads: Reads, id: string, number: number): Text {
  const read = find(reads, id, 'issue');
  if (read !== null && read.issue !== number) return { text: unread(`read ${id} isn't #${number}'s issue read`), unknown: true };
  const issue = got(reads, id, 'issue');
  return issue.ok ? { text: issue.value.title, unknown: false } : { text: unread(issue.why), unknown: true };
}

function prText(t: FleetTicket, reads: Reads): string {
  const pr = got(reads, t.pr, 'pr_discovery');
  if (!pr.ok) return `PR ${unread(pr.why)}`;
  const v = pr.value;
  if (v === null) return 'no PR';
  if (v.state === 'several') return `several PRs: ${v.numbers.map((n) => `#${n}`).join(', ')}`;
  if (v.state === 'open') return `PR #${v.number} open${v.draft ? ' · draft' : ''}`;
  if (t.on_base === null) return `PR #${v.number} merged · its merge not read back`;
  const back = got(reads, t.on_base, 'merge_readback');
  return `PR #${v.number} merged · ${!back.ok ? `on its base ${unread(back.why)}` : back.value ? 'on its base' : 'not found on its base'}`;
}

/** The contract's CI: failed if any check failed or was cancelled; else pending if any is; else passed if any passed; else none. */
function ciText(id: string | null, reads: Reads): string | null {
  if (id === null) return null;
  const checks = got(reads, id, 'checks');
  if (!checks.ok) return `CI ${unread(checks.why)}`;
  const any = (...results: Check['result'][]) => checks.value.some((c) => results.includes(c.result));
  return `CI ${any('fail', 'cancel') ? 'failed' : any('pending') ? 'pending' : any('pass') ? 'passed' : 'none'}`;
}

/** The latest verdict, and whether it is on the pull request's head: it holds only for its own commit. */
function reviewText(t: FleetTicket, reads: Reads): string | null {
  if (t.review === null) return null;
  const review = got(reads, t.review, 'comments');
  if (!review.ok) return `verdict ${unread(review.why)}`;
  if (review.value === null) return 'no verdict';
  const pr = got(reads, t.pr, 'pr_discovery');
  const head = pr.ok && pr.value !== null && pr.value.state === 'open' ? pr.value.head_commit : null;
  const where = head === null ? 'its head unknown' : review.value.commit === head ? 'on its head' : 'not on its head';
  return `verdict ${review.value.verdict} at ${review.value.commit.slice(0, 7)} · ${where}`;
}

/** Resolve a blocker's outcome only when the pointer names this ticket's read. */
function blockedBy(t: FleetTicket, reads: Reads): Got<ListOutcome<number>> {
  const read = find(reads, t.blocked_by, 'blocked_by');
  if (read === null) return { ok: false, why: `the blocked_by read ${t.blocked_by} isn't on the record` };
  if (read.ticket !== t.number) return { ok: false, why: `read ${t.blocked_by} isn't #${t.number}'s blocked_by read` };
  return { ok: true, value: read.outcome };
}

/**
 * What a ticket waits on: each blocker and whether it is merged; an outside
 * blocker with its version too, so the row says which version holds it up
 * when the graph isn't drawn.
 */
function waitsText(t: FleetTicket, reads: Reads, blockers: ReadonlyMap<number, Blocker>, own: ReadonlySet<number>): string | null {
  const read = blockedBy(t, reads);
  if (!read.ok) return `waits on ${unread(read.why)}`;
  const outcome = read.value;
  if (outcome.state === 'failed') return `waits on ${unread(outcome.reason)}`;
  const each = outcome.value.map((n) => {
    const b = blockers.get(n);
    const version = own.has(n) ? '' : ` (${versionText(versionOf(b, reads))})`;
    return `#${n}${version} ${mergeMarker(b?.merged, reads).word}`;
  });
  if (outcome.state === 'complete') return each.length === 0 ? null : `waits on ${each.join(', ')}`;
  return `waits on ${[...each, 'and more'].join(', ')} (partly read: ${outcome.reason})`;
}

/** An outside blocker's version: its milestone's title, or none; or why it isn't known. */
type Version = { known: string | null } | { unknown: string };

function versionOf(b: Blocker | undefined, reads: Reads): Version {
  if (b === undefined) return { unknown: 'not on the record as a blocker' };
  const issue = got(reads, b.issue, 'issue');
  return issue.ok ? { known: issue.value.milestone?.title ?? null } : { unknown: `unread: ${issue.why}` };
}

/** In a box: the version alone, `no version` or `version unknown` (its row says why). */
const versionLabel = (v: Version): string => ('unknown' in v ? 'version unknown' : (v.known ?? 'no version'));
/** In a ticket's row: `version 0.8.4`, `no version`, or `version unknown (why)`. */
const versionText = (v: Version): string => ('unknown' in v ? `version ${unknownText(v.unknown)}` : v.known === null ? 'no version' : `version ${v.known}`);

/**
 * The graph's boxes and arrows, only when every arrow can be read: the
 * fleet's ticket list and each ticket's blockers, in full. A box per ticket,
 * in the view's order, and per blocker that isn't one (an outside blocker,
 * labelled with its version), in the blockers' order.
 */
function graphOf(view: FleetView, reads: Reads, blockers: ReadonlyMap<number, Blocker>, own: ReadonlySet<number>): FleetGraph {
  const list = got(reads, view.fleet.tickets, 'sub_issues');
  if (!list.ok) return { kind: 'unread', reason: `the fleet's tickets weren't all read (${list.why})` };
  const outside = view.blockers.map((b) => b.number).filter((n) => !own.has(n));
  const edges: Edge[] = [];
  for (const t of view.tickets) {
    const read = blockedBy(t, reads);
    if (!read.ok) return { kind: 'unread', reason: `#${t.number}'s blockers weren't all read (${read.why})` };
    const waits = read.value;
    if (waits.state !== 'complete') return { kind: 'unread', reason: `#${t.number}'s blockers weren't all read (${waits.reason})` };
    for (const n of waits.value) {
      edges.push({ from: n, to: t.number });
      if (!own.has(n) && !outside.includes(n)) outside.push(n);
    }
  }
  const labels = new Map<number, BoxLabel>();
  for (const t of view.tickets) labels.set(t.number, { label: `#${t.number}`, marker: stateMarker(t.state, reads) });
  for (const n of outside) labels.set(n, { label: `#${n} · ${versionLabel(versionOf(blockers.get(n), reads))}`, marker: mergeMarker(blockers.get(n)?.merged, reads) });
  const nodes = [...view.tickets.map((t) => ({ number: t.number, outside: false })), ...outside.map((n) => ({ number: n, outside: true }))];
  return { kind: 'input', input: { nodes, edges }, labels };
}

/** What a read read, as the contract writes it: `kind(param)`, or `kind()` with none. */
function subjectOf(r: Read): string {
  switch (r.kind) {
    case 'version':
      return `version(${r.source})`;
    case 'issue':
    case 'pr_discovery':
      return `${r.kind}(${r.issue})`;
    case 'sub_issues':
      return `sub_issues(${r.spec})`;
    case 'blocked_by':
      return `blocked_by(${r.ticket})`;
    case 'checks':
    case 'comments':
    case 'merge_readback':
      return `${r.kind}(${r.pr})`;
    case 'workspace':
      return `workspace(${r.thread})`;
    case 'repository':
    case 'spec_list':
    case 'projects':
    case 'threads':
      return `${r.kind}()`;
  }
}

/** The contract's gaps: the reads whose outcome isn't complete, and nothing else. */
const gapsOf = (reads: readonly Read[]): FleetGap[] =>
  reads.flatMap((r) => (r.outcome.state === 'complete' ? [] : [{ read: r.id, subject: subjectOf(r), gap: r.outcome.gap, reason: r.outcome.reason }]));

/** Everything one fleet's view shows, from `openwiz fleet <spec> --json`, as reported: nothing is filled in. */
export function fleetModel(envelope: FleetEnvelope): FleetModel {
  const reads = index(envelope.reads);
  const view = envelope.data;
  const blockers = new Map(view.blockers.map((b) => [b.number, b]));
  const own = new Set(view.tickets.map((t) => t.number));
  const tickets = view.tickets.map(
    (t): TicketRow => ({
      number: t.number,
      title: titleOf(reads, t.issue, t.number),
      marker: stateMarker(t.state, reads),
      pr: prText(t, reads),
      ci: ciText(t.ci, reads),
      review: reviewText(t, reads),
      waits: waitsText(t, reads, blockers, own),
      builder:
        'unread' in t.builder
          ? { text: `builder ${unread(whyUnread(reads, t.builder.unread))}` }
          : t.builder.known === null
            ? { text: 'no builder placed' }
            : { thread: t.builder.known },
      reviewer: `reviewer undefined (${t.reviewer.undefined})`,
    }),
  );
  const progress = view.fleet.progress;
  return {
    spec: view.fleet.spec,
    title: titleOf(reads, view.fleet.issue, view.fleet.spec),
    progress: 'known' in progress ? `${progress.known.merged} of ${progress.known.tickets} merged` : `progress ${unread(whyUnread(reads, progress.unread))}`,
    snapshotAt: envelope.freshness.snapshot_at,
    partial: envelope.coverage.state !== 'complete',
    gaps: gapsOf(envelope.reads),
    graph: graphOf(view, reads, blockers, own),
    tickets,
    groups: BY_STATE.map((kind) => ({ marker: marker(kind, kind), tickets: tickets.filter((t) => t.marker.kind === kind) })).filter((g) => g.tickets.length > 0),
  };
}

// ── the layout ──

/** The size of one box and the gaps between them, in CSS pixels. */
export const BOX_W = 160;
export const BOX_H = 64;
export const GAP_X = 24;
export const GAP_Y = 16;

/** A box: one issue, `outside` when it blocks a ticket but isn't one of the fleet's. */
export type GraphNode = { number: number; outside: boolean };
/** An arrow: `from` blocks `to` (its blocked-by link). */
export type Edge = { from: number; to: number };
export type GraphInput = { nodes: readonly GraphNode[]; edges: readonly Edge[] };

export type Box = { number: number; outside: boolean; column: number; row: number; x: number; y: number };
/**
 * From the middle of the blocker's right edge to the middle of the blocked
 * box's left edge, through `via`: the middle of the left edge of an empty
 * slot in each column it skips.
 */
export type Arrow = { from: number; to: number; x1: number; y1: number; via: { x: number; y: number }[]; x2: number; y2: number };

export type Layout =
  | { kind: 'drawn'; boxes: Box[]; arrows: Arrow[]; width: number; height: number }
  | { kind: 'too_wide'; columns: number; needed: number; width: number }
  | { kind: 'loop'; numbers: number[] };

/**
 * Boxes in columns by step, or why the graph isn't drawn. A box's column is
 * one past its deepest blocker's (none: the first). In a column, outside
 * blockers come first, then the fleet's tickets, each in the input's order,
 * then the empty slots that arrows skipping that column pass through, so no
 * arrow passes behind a box.
 * A loop of blocked-by links has no steps: it is refused, with every issue on
 * it. A graph wider than `width` is too wide: the caller lists it instead.
 */
export function layoutGraph(input: GraphInput, width: number, boxWidth = BOX_W): Layout {
  const blockers = new Map<number, number[]>();
  for (const e of input.edges) blockers.set(e.to, [...(blockers.get(e.to) ?? []), e.from]);
  const column = new Map<number, number>();
  const remaining = new Map(input.nodes.map((n) => [n.number, (blockers.get(n.number) ?? []).length]));
  const outgoing = new Map<number, number[]>();
  for (const e of input.edges) {
    let targets = outgoing.get(e.from);
    if (targets === undefined) { targets = []; outgoing.set(e.from, targets); }
    targets.push(e.to);
  }
  const ready: number[] = [];
  const pendingDepth = new Map<number, number>();
  // Seed each issue once, even for repeated node ids. Rows still use input order.
  for (const [number, count] of remaining) {
    if (count === 0) { column.set(number, 0); ready.push(number); }
  }
  for (const from of ready) {
    for (const to of outgoing.get(from) ?? []) {
      const count = remaining.get(to);
      if (count === undefined) continue;
      const nextDepth = Math.max(pendingDepth.get(to) ?? 0, (column.get(from) ?? 0) + 1);
      pendingDepth.set(to, nextDepth);
      remaining.set(to, count - 1);
      if (count === 1) { column.set(to, nextDepth); ready.push(to); }
    }
  }
  const unplaced = input.nodes.filter((n) => !column.has(n.number));
  if (unplaced.length > 0) return { kind: 'loop', numbers: onLoops(unplaced, input.edges) };

  const columns = input.nodes.reduce((c, n) => Math.max(c, (column.get(n.number) ?? 0) + 1), 0);
  const needed = columns === 0 ? 0 : columns * boxWidth + (columns - 1) * GAP_X;
  if (needed > width) return { kind: 'too_wide', columns, needed, width };

  const rows = new Map<number, number>();
  const filled: number[] = [];
  for (const n of [...input.nodes.filter((m) => m.outside), ...input.nodes.filter((m) => !m.outside)]) {
    const c = column.get(n.number) ?? 0;
    rows.set(n.number, filled[c] ?? 0);
    filled[c] = (filled[c] ?? 0) + 1;
  }
  const boxes = input.nodes.map((n): Box => {
    const c = column.get(n.number) ?? 0;
    const r = rows.get(n.number) ?? 0;
    return { number: n.number, outside: n.outside, column: c, row: r, x: c * (boxWidth + GAP_X), y: r * (BOX_H + GAP_Y) };
  });
  const at = new Map(boxes.map((b) => [b.number, b]));
  // An arrow that skips columns takes the next empty slot in each one between, below its boxes.
  const arrows = input.edges.map((e): Arrow => {
    const a = at.get(e.from);
    const b = at.get(e.to);
    const via: Arrow['via'] = [];
    for (let c = (a?.column ?? 0) + 1; c < (b?.column ?? 0); c++) {
      via.push({ x: c * (boxWidth + GAP_X), y: (filled[c] ?? 0) * (BOX_H + GAP_Y) + BOX_H / 2 });
      filled[c] = (filled[c] ?? 0) + 1;
    }
    return { from: e.from, to: e.to, x1: (a?.x ?? 0) + boxWidth, y1: (a?.y ?? 0) + BOX_H / 2, via, x2: b?.x ?? 0, y2: (b?.y ?? 0) + BOX_H / 2 };
  });
  const depth = filled.reduce((d, f) => Math.max(d, f), 0);
  return { kind: 'drawn', boxes, arrows, width: needed, height: depth === 0 ? 0 : depth * BOX_H + (depth - 1) * GAP_Y };
}

/**
 * The issues on a loop, in the input's order: of those no step could place,
 * each whose blocked-by links lead back to itself (its own loop, or a link to
 * itself). What only waits on a loop, or only blocks one, or sits between
 * two, is on none.
 */
function onLoops(unplaced: readonly GraphNode[], edges: readonly Edge[]): number[] {
  const blocks = new Map<number, number[]>();
  for (const e of edges) blocks.set(e.from, [...(blocks.get(e.from) ?? []), e.to]);
  const returns = (start: number): boolean => {
    const seen = new Set<number>();
    const next = [...(blocks.get(start) ?? [])];
    for (let n = next.pop(); n !== undefined; n = next.pop()) {
      if (n === start) return true;
      if (seen.has(n)) continue;
      seen.add(n);
      next.push(...(blocks.get(n) ?? []));
    }
    return false;
  };
  return unplaced.map((n) => n.number).filter(returns);
}
