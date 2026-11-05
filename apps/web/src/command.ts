// The cockpit's command bar (0.0.10 T4, #537): a pure function over the
// page's own data. It reads nothing, stores nothing and sends nothing.
//
// - `ls` lists the current level; `cd <project|fleet|ticket>` narrows the
//   page, `cd ..` goes up; `next` opens the oldest item in scope; a number
//   opens that item; `blockers` lists what blocks the current level.
// - `y` and `approve` act only on the item open on screen, bound to what it
//   showed when it opened (cockpit.v1: project, spec, ticket, kind, wording,
//   risk and target). They return an `AnswerRequest` (#536's seam), which
//   opens the item's Yes exactly as pressing it would: its row's preview and
//   Send (twice for a risky item) still send, once.
// - One line in, one command: pasted lines are never split. Words are exact
//   and lower case; anything else is refused with what to try.
// - The scope narrows only: unknown projects, fleets and tickets stay in,
//   never excluded as though known (as src/cockpit.ts's filters do).

import { actionable, agentsShown, bindingOf, freshNow, NO_TARGET, needKey, needsShown, projectName } from './cockpit.ts';
import type { Agent, AnswerRequest, Clock, Cockpit, Need, Received } from './cockpit.ts';
import type { Fact } from './envelope.ts';
import { ageText, factText } from './present.ts';

/** Where the bar is: the top, a project, a fleet in it, or a ticket in that fleet. */
export type Scope = { project: string | null; fleet: number | null; ticket: number | null };
export const TOP: Scope = { project: null, fleet: null, ticket: null };

/**
 * The item open on screen: its identity, the binding it showed when it
 * opened (null while any part is unknown), and, once the item changed,
 * vanished or went stale, why that binding is lost. A lost binding never
 * comes back, even if the item does: open it again.
 */
export type Opened = { key: string; ticket: number; binding: string | null; lost?: 'changed' | 'stale' };

/**
 * What a command reads: the page's last snapshot and its clocks, the
 * machine filter, the scope, the open item, and why an item's own answer
 * record keeps it from a new answer for the binding on screen
 * (`answered(needKey, binding)`, words like "already has an answer (Yes ·
 * sent)"; null when nothing does).
 */
export type Context = { c: Cockpit; received: Received; now: Clock; machine: string | null; scope: Scope; open: Opened | null; answered(key: string, binding: string): string | null };

/** One output line: the command as typed (flattened), and what it did or why not. */
export type Line = { input: string; tone: 'done' | 'refused'; text: string; items: string[] };

/** A command's result: its line, and only the changes it makes. */
export type Outcome = { line: Line | null; scope?: Scope; open?: Opened | null; request?: Omit<AnswerRequest, 'seq'> };

const MAX_LENGTH = 200;
const UNKNOWN = 'Unknown command. Try ls, cd, next, blockers, a number or y.';
const RISKY_KINDS: readonly string[] = ['live', 'release', 'publish'];

// ── the scope ──

/** The scope the page shows: the project filter owns the project, and a deeper scope holds only under it. */
export function scopeOf(project: string | null, deeper: Scope): Scope {
  if (project === null) return TOP;
  return deeper.project === project ? deeper : { project, fleet: null, ticket: null };
}

const keeps = <T>(f: Fact<T>, v: T | null): boolean => v === null || !('known' in f) || f.known === v;

/** The response narrowed to a fleet or ticket (the project filter narrows projects). Projects and targets are never narrowed. */
export function narrow(c: Cockpit, scope: Scope): Cockpit {
  if (scope.fleet === null && scope.ticket === null) return c;
  const needs = c.needs_you.items.filter((n) => (scope.fleet === null || n.spec === scope.fleet) && (scope.ticket === null || n.ticket === scope.ticket));
  const agents = c.agents.items.filter((a) => keeps(a.fleet, scope.fleet) && keeps(a.ticket, scope.ticket));
  return { ...c, needs_you: { ...c.needs_you, items: needs }, agents: { ...c.agents, items: agents } };
}

/** Exactly what the page shows in `scope`: Needs you in its numbered order, and the grid's agents. */
export function shown(v: { c: Cockpit; scope: Scope; machine: string | null }): { needs: Need[]; agents: Agent[] } {
  const c = narrow(v.c, v.scope);
  const filter = { project: v.scope.project, machine: v.machine };
  return { needs: needsShown(c, filter), agents: agentsShown(c, filter) };
}

/** The breadcrumb's parts: the project's name, then `#fleet` and `#ticket`. */
export function crumbs(c: Cockpit, scope: Scope): string[] {
  if (scope.project === null) return [];
  const out = [projectName(c, scope.project)];
  if (scope.fleet !== null) out.push(`#${scope.fleet}`);
  if (scope.ticket !== null) out.push(`#${scope.ticket}`);
  return out;
}

const where = (c: Cockpit, scope: Scope): string => crumbs(c, scope).join(' / ');

/**
 * Each shown item's identity, in order: its contract key, or, unassigned, its
 * spec, ticket and kind with which of its identical twins it is (the contract
 * allows indistinguishable unassigned items), so two are never one.
 */
export function openKeys(needs: readonly Need[]): string[] {
  const seen = new Map<string, number>();
  return needs.map((n) => {
    const key = needKey(n);
    if (key !== null) return key;
    const base = JSON.stringify([null, n.spec, n.ticket, n.kind]);
    const k = (seen.get(base) ?? 0) + 1;
    seen.set(base, k);
    return k === 1 ? base : `${base}#${k}`;
  });
}

/** The open item as it stands in `ctx`: the same object while its binding holds; lost for good once it changed, vanished or went stale. */
export function follow(ctx: Context): Opened | null {
  const open = ctx.open;
  if (open === null || open.lost !== undefined) return open;
  const { needs } = shown(ctx);
  const at = openKeys(needs).indexOf(open.key);
  const n = needs[at];
  if (!n || bindingOf(ctx.c, n) !== open.binding) return { ...open, lost: 'changed' };
  if (!freshNow(ctx.c.needs_you.freshness, ctx.c.snapshot_at, ctx.received, ctx.now)) return { ...open, lost: 'stale' };
  return open;
}

// ── the words ──

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;
const counts = (needs: number, agents: number): string => `${plural(agents, 'agent', 'agents')} · ${plural(needs, 'needs you', 'need you')}`;
const flat = (input: string): string => {
  const s = input.replace(/\s+/g, ' ').trim();
  return s.length > 40 ? `${s.slice(0, 40)}…` : s;
};

function readState(ctx: Context): { complete: boolean; fresh: boolean; unknownTime: boolean } {
  const { c, received, now } = ctx;
  const parts = [c.projects, c.needs_you, c.agents];
  return {
    complete: parts.every((p) => p.coverage.state === 'complete'),
    fresh: parts.every((p) => freshNow(p.freshness, c.snapshot_at, received, now)),
    unknownTime: parts.some((p) => p.freshness.state === 'unknown'),
  };
}

/** Since receipt, on the shorter of the two clocks (as the row's waiting time). */
const since = (ctx: Context): number => Math.max(0, Math.min(ctx.now.mono - ctx.received.mono, ctx.now.wall - ctx.received.wall));

/**
 * Runs one line. Nothing here sends: `y` returns a request that opens the
 * item's Yes, and only the row's own Send sends.
 */
export function run(input: string, ctx: Context): Outcome {
  const typed = input.trim();
  if (typed === '') return { line: null };
  const said = (tone: Line['tone'], text: string, items: string[] = []): Line => ({ input: flat(input), tone, text, items });
  if (/[\r\n]/.test(input)) return { line: said('refused', 'One command at a time: pasted lines aren’t run.') };
  if (typed.length > MAX_LENGTH) return { line: said('refused', `Too long for a command (${typed.length} characters).`) };
  const [word = '', ...rest] = typed.split(/\s+/);
  const arg = rest.join(' ');
  const bare = (go: () => Outcome): Outcome => (arg === '' ? go() : { line: said('refused', `${word} takes nothing after it.`) });
  switch (word) {
    case 'ls':
      return bare(() => ({ line: ls(ctx, said) }));
    case 'cd':
      return cd(ctx, arg, said);
    case 'next':
      return bare(() => next(ctx, said));
    case 'blockers':
      return bare(() => ({ line: blockers(ctx, said) }));
    case 'y':
    case 'approve':
      return bare(() => yes(ctx, said));
  }
  if (/^[1-9]\d*$/.test(word) && arg === '') return number(ctx, word, said);
  if (/^[-+]?(\d+\.?\d*|\.\d+)$/.test(word) && arg === '') return { line: said('refused', `Not an item number: ${word}. Items are numbered from 1.`) };
  return { line: said('refused', UNKNOWN) };
}

type Say = (tone: Line['tone'], text: string, items?: string[]) => Line;

function ls(ctx: Context, said: Say): Line {
  const { c, scope } = ctx;
  const { needs, agents } = shown(ctx);
  const groups = new Map<string, { agents: number; needs: number }>();
  const unplaced = { agents: 0, needs: 0 };
  const add = (label: string | null, kind: 'agents' | 'needs') => {
    if (label === null) {
      unplaced[kind]++;
      return;
    }
    const g = groups.get(label) ?? { agents: 0, needs: 0 };
    g[kind]++;
    groups.set(label, g);
  };
  const state = readState(ctx);
  const note = !state.complete ? ' · this read is partial: more may exist' : !state.fresh ? ' · this read is stale' : '';
  let head: string;
  if (scope.ticket !== null) {
    const items = [
      ...agents.map((a) => `Agent: ${factText(a.title)} · ${'known' in a.state ? a.state.known : 'state unknown'}`),
      ...needs.map((n, i) => `Item ${i + 1}: ${n.kind}`),
    ];
    return said('done', `#${scope.ticket} in ${where(c, { ...scope, ticket: null })}${note}`, items);
  }
  if (scope.fleet !== null) {
    for (const a of agents) add('known' in a.project && 'known' in a.fleet && 'known' in a.ticket ? `#${a.ticket.known}` : null, 'agents');
    for (const n of needs) add('known' in n.project ? `#${n.ticket}` : null, 'needs');
    head = `${plural(groups.size, 'ticket', 'tickets')} with running agents or Needs you in ${where(c, scope)}`;
  } else if (scope.project !== null) {
    for (const a of agents) add('known' in a.project && 'known' in a.fleet ? `#${a.fleet.known}` : null, 'agents');
    for (const n of needs) add('known' in n.project ? `#${n.spec}` : null, 'needs');
    head = `${plural(groups.size, 'fleet', 'fleets')} with running agents or Needs you in ${where(c, scope)}`;
  } else {
    for (const p of c.projects.items) groups.set(projectName(c, p.id), { agents: 0, needs: 0 });
    for (const a of agents) add('known' in a.project ? projectName(c, a.project.known) : null, 'agents');
    for (const n of needs) add('known' in n.project ? projectName(c, n.project.known) : null, 'needs');
    head = plural(c.projects.items.length, 'project', 'projects');
  }
  const items = [...groups].map(([label, g]) => `${label} · ${counts(g.needs, g.agents)}`);
  if (unplaced.agents + unplaced.needs > 0) items.push(`Not placed · ${counts(unplaced.needs, unplaced.agents)}`);
  return said('done', `${head}${note}`, items);
}

/** Every fleet and ticket the read places in a known project, first seen first. */
function places(c: Cockpit): { scope: Scope; label: string; number: number }[] {
  const out = new Map<string, { scope: Scope; label: string; number: number }>();
  const put = (scope: Scope, number: number) => {
    const key = JSON.stringify(scope);
    if (!out.has(key)) out.set(key, { scope, label: where(c, scope), number });
  };
  for (const a of c.agents.items) {
    if (!('known' in a.project) || !('known' in a.fleet)) continue;
    put({ project: a.project.known, fleet: a.fleet.known, ticket: null }, a.fleet.known);
    if ('known' in a.ticket) put({ project: a.project.known, fleet: a.fleet.known, ticket: a.ticket.known }, a.ticket.known);
  }
  for (const n of c.needs_you.items) {
    if (!('known' in n.project)) continue;
    put({ project: n.project.known, fleet: n.spec, ticket: null }, n.spec);
    put({ project: n.project.known, fleet: n.spec, ticket: n.ticket }, n.ticket);
  }
  return [...out.values()];
}

const under = (s: Scope, level: Scope): boolean => (level.project === null || s.project === level.project) && (level.fleet === null || s.fleet === level.fleet);

function cd(ctx: Context, arg: string, said: Say): Outcome {
  const { c, scope } = ctx;
  const go = (to: Scope): Outcome => {
    const { needs, agents } = shown({ ...ctx, scope: to });
    const name = to.project === null ? 'at the top' : `in ${where(c, to)}`;
    return { line: said('done', `Now ${name} · ${plural(needs.length, 'needs you', 'need you')} · ${plural(agents.length, 'agent', 'agents')}`), scope: to, open: null };
  };
  if (arg === '') return go(TOP);
  if (arg === '..') {
    if (scope.ticket !== null) return go({ ...scope, ticket: null });
    if (scope.fleet !== null) return go({ ...scope, fleet: null });
    if (scope.project !== null) return go(TOP);
    return { line: said('refused', 'Already at the top') };
  }
  const lower = arg.toLowerCase();
  // An id matches any project; a word matches only a known name.
  const named = (match: (name: string) => boolean) => c.projects.items.filter((p) => p.id === arg || ('known' in p.name && match(p.name.known.toLowerCase())));
  let found: { scope: Scope; label: string }[];
  const num = /^#?(\d+)$/.exec(arg);
  if (num) {
    const n = Number(num[1]);
    const all = places(c).filter((p) => p.number === n);
    const here = all.filter((p) => under(p.scope, scope));
    found = [...(here.length > 0 ? here : all), ...named((name) => name === lower).map((p) => ({ scope: { project: p.id, fleet: null, ticket: null }, label: projectName(c, p.id) }))];
  } else {
    const exact = named((name) => name === lower);
    found = (exact.length > 0 ? exact : named((name) => name.startsWith(lower))).map((p) => ({ scope: { project: p.id, fleet: null, ticket: null }, label: projectName(c, p.id) }));
  }
  const [only] = found;
  if (found.length === 1 && only) return go(only.scope);
  if (found.length > 1) return { line: said('refused', `${found.length} match: ${found.map((f) => f.label).join(', ')}`) };
  return { line: said('refused', `No project, fleet or ticket called ${arg}`) };
}

function openOf(c: Cockpit, needs: readonly Need[], at: number): Opened | null {
  const n = needs[at];
  const key = openKeys(needs)[at];
  return n && key !== undefined ? { key, ticket: n.ticket, binding: bindingOf(c, n) } : null;
}

/** Why an empty list may not be empty: partial, stale or of unknown age; null when complete and fresh. */
function emptyWhy(ctx: Context): string | null {
  const s = readState(ctx);
  if (!s.complete) return 'this read is partial';
  if (!s.fresh) return s.unknownTime ? 'when this was read is unknown' : 'this read is stale';
  return null;
}

function next(ctx: Context, said: Say): Outcome {
  const { needs } = shown(ctx);
  const [first] = needs;
  if (!first) {
    const why = emptyWhy(ctx);
    return { line: why === null ? said('done', 'Nothing needs you here') : said('done', `No items read here: ${why}, so something may still need you`) };
  }
  const age = 'known' in first.age_ms ? `oldest waiting (${ageText(first.age_ms.known + since(ctx))})` : 'waiting time not reported';
  return { line: said('done', `Opened 1: #${first.ticket}, ${age}`), open: openOf(ctx.c, needs, 0) };
}

function number(ctx: Context, word: string, said: Say): Outcome {
  const { needs } = shown(ctx);
  const k = Number(word);
  const n = Number.isSafeInteger(k) ? needs[k - 1] : undefined;
  if (!n) return { line: said('refused', `No item ${word} (${needs.length} shown)`) };
  return { line: said('done', `Opened ${k}: #${n.ticket} (${n.kind})`), open: openOf(ctx.c, needs, k - 1) };
}

function yes(ctx: Context, said: Say): Outcome {
  const { c, open } = ctx;
  if (open === null) return { line: said('refused', 'Nothing sent. Open an item first (next or a number).') };
  const t = open.ticket;
  const now = follow(ctx);
  if (now?.lost === 'changed') return { line: said('refused', `Nothing sent. #${t} changed since you opened it.`), open: null };
  if (now?.lost === 'stale') return { line: said('refused', `Nothing sent. #${t} went stale since you opened it: refresh, then open it again.`), open: null };
  const { needs } = shown(ctx);
  const n = needs[openKeys(needs).indexOf(open.key)];
  if (!n) return { line: said('refused', `Nothing sent. #${t} changed since you opened it.`), open: null };
  if (!('known' in n.project)) return { line: said('refused', `Nothing sent. #${t} isn’t assigned to a project here, so y can’t approve it.`) };
  if (!('known' in n.wording)) return { line: said('refused', `Nothing sent. #${t}’s proposal isn’t readable here, so y can’t approve it. Answer it on GitHub.`) };
  if (!('known' in n.risky)) return { line: said('refused', `Nothing sent. #${t}’s risk isn’t reported here, so y can’t approve it. Answer it on GitHub.`) };
  const act = actionable(c, n, ctx.received, ctx.now);
  if (!act.ok) {
    if (act.why === NO_TARGET) return { line: said('refused', `Nothing sent. #${t}’s project has no verified orchestrator to send to.`) };
    return { line: said('refused', `Nothing sent. #${t} went stale since you opened it: refresh, then open it again.`), open: null };
  }
  const key = needKey(n) ?? open.key;
  const answer = ctx.answered(key, act.binding);
  if (answer !== null) return { line: said('refused', `Nothing sent. #${t} ${answer}.`) };
  const text = act.risky
    ? `Yes opened on #${t}: it’s ${RISKY_KINDS.includes(n.kind) ? `a ${n.kind}` : 'risky'}, so its row asks you to confirm twice before it sends once.`
    : `Yes opened on #${t}: press Send in its row to send it once.`;
  return { line: said('done', text), request: { key, choice: 'yes' } };
}

function blockers(ctx: Context, said: Say): Line {
  const { c, scope } = ctx;
  const { needs, agents } = shown(ctx);
  const items: string[] = [];
  for (const a of agents) {
    if (!('known' in a.state) || (a.state.known !== 'held' && a.state.known !== 'blocked')) continue;
    const at = 'known' in a.project && 'known' in a.fleet ? ` · ${where(c, { project: a.project.known, fleet: a.fleet.known, ticket: null })}` : '';
    items.push(`${'known' in a.ticket ? `#${a.ticket.known}` : factText(a.title)} ${a.state.known}${at}`);
  }
  needs.forEach((n, i) => items.push(`${i + 1}: #${n.ticket} ${n.kind} · needs you`));
  const s = readState(ctx);
  if (items.length === 0) {
    const why = emptyWhy(ctx);
    return said('done', why === null ? 'Nothing blocking here among running agents and Needs you' : `No blockers read: ${why}, so something may still block it`);
  }
  const level = scope.project === null ? 'all projects' : where(c, scope);
  const note = !s.complete ? ' · this read is partial: more may block it' : !s.fresh ? ' · this read is stale' : '';
  return said('done', `${items.length} blocking ${level}, among running agents and Needs you${note}`, items);
}

/**
 * The gold binding line, while the input is exactly `y` or `approve`: what
 * it would open, for which item and where. Null when it would open nothing.
 */
export function bindingLine(input: string, ctx: Context): string | null {
  const word = input.trim();
  if (word !== 'y' && word !== 'approve') return null;
  const r = run(word, ctx);
  const { needs } = shown(ctx);
  const n = r.request && ctx.open ? needs[openKeys(needs).indexOf(ctx.open.key)] : undefined;
  if (!n || !('known' in n.wording) || !('known' in n.project) || !('known' in n.risky)) return null;
  const confirm = n.risky.known ? `${RISKY_KINDS.includes(n.kind) ? `a ${n.kind}` : 'risky'}: you confirm twice` : 'you confirm with Send';
  return `${word} will answer Yes to #${n.ticket} “${n.wording.known}” · ${projectName(ctx.c, n.project.known)} · ${confirm}, then it sends once to the orchestrator`;
}
