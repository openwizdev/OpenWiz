// The fleets list (#125, spec 3's C1): `openwiz fleets --json`
// (contracts/fleet.v1.md), read exactly, and what the list shows of it. Not
// wired to the page yet (C4 does that); src/components/Fleets.tsx draws it.
//
// The reader follows the contract's "Reading it": an object only with
// exactly its keys, each once (a key written twice is refused: JSON.parse
// would keep the last, so the text is parsed here); an integer only as a
// JSON integer (never `1.0`); an enum only as one string of its list; a
// worked-out value only in one of its forms; `null` only where the schema
// has it. It reads the schema (contracts/fleet.v1.schema.json), not the
// contract's other rules, so nothing below relies on them: a pointer that
// names no read, or a read of another kind or subject, shows as unknown, with
// why.

import { GAP_KINDS } from './envelope.ts';
import type { FleetEnvelope, Unplaced, Blocker, Check, Counts, FleetGap, FleetTicket, FleetView, Issue, Known, MergedPr, NeedsYou, OpenPr, PendingQuestion, Read, Review, SeveralPrs, Text, Thread, TicketState, Unread } from './fleetGraph.ts';
import type { Marker } from './markers.ts';
import { unknownText } from './present.ts';

// ── the shapes: the fleets view of the contract (the types are fleetGraph.ts's) ──

export type Fleet = FleetView['fleet'];
/** A ticket in the fleets view: the fleet view's, without its agents. */
export type FleetsTicket = Omit<FleetTicket, 'builder' | 'reviewer'>;
export type FleetsView = {
  view: 'fleets';
  repository: string;
  specs: string;
  fleets: Fleet[];
  tickets: FleetsTicket[];
  blockers: Blocker[];
  needs_you: { known: NeedsYou[] } | Unread;
};
type Source<N> = { name: N; version: string; tested_version: string; version_tested: boolean };
export type FleetsEnvelope = {
  orchestrator?: string;
  schema: 'openwiz.fleet.v1';
  sources: { github: Source<'gh'>; cloudroom: Source<'room-cli'> | null };
  reads: Read[];
  coverage: { state: 'complete' | 'partial' };
  freshness: { snapshot_at: number };
  data: FleetsView;
};

/** Where a text was refused (`$` for the whole text, otherwise the value's path), and why, in OpenWiz's words. */
export type Refusal = { at: string; why: string };
export type ReadResult = { ok: true; envelope: FleetsEnvelope } | { ok: false; refusal: Refusal };

// ── JSON, parsed strictly ──

/** A JSON number, and whether it was written as an integer JavaScript holds exactly. */
class JsonNumber {
  readonly value: number;
  readonly integer: boolean;
  constructor(value: number, integer: boolean) {
    this.value = value;
    this.integer = integer;
  }
}
type Json = null | boolean | string | JsonNumber | Json[] | JsonObject;
type JsonObject = Map<string, Json>;

class Refused extends Error {
  readonly at: string;
  constructor(at: string, why: string) {
    super(why);
    this.at = at;
  }
}

/** No contract value is nested deeper than this; a deeper text is refused before it can exhaust the stack. */
const MAX_DEPTH = 64;
const NUMBER = /-?(?:0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?/y;
const HEX4 = /[0-9a-fA-F]{4}/y;
const ESCAPES = new Map([
  ['"', '"'],
  ['\\', '\\'],
  ['/', '/'],
  ['b', '\b'],
  ['f', '\f'],
  ['n', '\n'],
  ['r', '\r'],
  ['t', '\t'],
]);

/** A string with a lone surrogate isn't text: refused, escaped or not. */
function wellFormed(s: string): boolean {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xdc00 && c <= 0xdfff) return false;
    if (c >= 0xd800 && c <= 0xdbff) {
      const next = s.charCodeAt(i + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
      i++;
    }
  }
  return true;
}

/** RFC 8259 JSON, one value, objects as Maps. A key written twice is refused at its path. */
export function parseJson(text: string): Json {
  let i = 0;
  const bad = (why: string): never => {
    throw new Refused('$', `not JSON: ${why} at character ${i}`);
  };
  const space = () => {
    for (let c = text.charCodeAt(i); c === 0x20 || c === 0x09 || c === 0x0a || c === 0x0d; c = text.charCodeAt(i)) i++;
  };
  const string = (): string => {
    i++; // the opening quote
    let out = '';
    for (;;) {
      if (i >= text.length) return bad('an unclosed string');
      const c = text.charCodeAt(i);
      if (c === 0x22) {
        i++;
        if (!wellFormed(out)) return bad('a lone surrogate');
        return out;
      }
      if (c < 0x20) return bad('a control character in a string');
      if (c !== 0x5c) {
        out += text.charAt(i);
        i++;
        continue;
      }
      const e = text.charAt(i + 1);
      const plain = ESCAPES.get(e);
      if (plain !== undefined) {
        out += plain;
        i += 2;
        continue;
      }
      HEX4.lastIndex = i + 2;
      if (e !== 'u' || !HEX4.test(text)) return bad('a bad escape');
      out += String.fromCharCode(parseInt(text.slice(i + 2, i + 6), 16));
      i += 6;
    }
  };
  const word = (w: string, v: Json): Json => {
    if (!text.startsWith(w, i)) return bad('an unexpected character');
    i += w.length;
    return v;
  };
  const value = (path: string, depth: number): Json => {
    if (depth > MAX_DEPTH) return bad('nested too deep');
    space();
    const c = text.charAt(i);
    if (c === '{') {
      i++;
      const o: JsonObject = new Map();
      space();
      if (text.charAt(i) === '}') {
        i++;
        return o;
      }
      for (;;) {
        space();
        if (text.charAt(i) !== '"') return bad('a key that isn\'t a string');
        const key = string();
        if (o.has(key)) throw new Refused(`${path}.${key}`, 'a key written twice');
        space();
        if (text.charAt(i) !== ':') return bad('no colon after a key');
        i++;
        o.set(key, value(`${path}.${key}`, depth + 1));
        space();
        const next = text.charAt(i);
        i++;
        if (next === '}') return o;
        if (next !== ',') return bad('no comma or end in an object');
      }
    }
    if (c === '[') {
      i++;
      const a: Json[] = [];
      space();
      if (text.charAt(i) === ']') {
        i++;
        return a;
      }
      for (;;) {
        a.push(value(`${path}[${a.length}]`, depth + 1));
        space();
        const next = text.charAt(i);
        i++;
        if (next === ']') return a;
        if (next !== ',') return bad('no comma or end in a list');
      }
    }
    if (c === '"') return string();
    if (c === 't') return word('true', true);
    if (c === 'f') return word('false', false);
    if (c === 'n') return word('null', null);
    NUMBER.lastIndex = i;
    const m = NUMBER.exec(text);
    if (m === null) return bad('an unexpected character');
    i += m[0].length;
    const n = Number(m[0]);
    if (!Number.isFinite(n)) return bad('a number too large');
    return new JsonNumber(n, m[1] === undefined && m[2] === undefined && Number.isSafeInteger(n));
  };
  const v = value('$', 0);
  space();
  if (i !== text.length) bad('more after the value');
  return v;
}

// ── the reader: the schema's shapes, exactly ──

type Reader<T> = (v: Json, at: string) => T;

function object(v: Json, at: string): JsonObject {
  if (!(v instanceof Map)) throw new Refused(at, 'not an object');
  return v;
}

/** The object, with exactly these keys: any other is refused first, then any missing. */
function exact(v: Json, at: string, keys: readonly string[]): JsonObject {
  const o = object(v, at);
  for (const k of o.keys()) if (!keys.includes(k)) throw new Refused(`${at}.${k}`, 'a key the contract doesn\'t have here');
  for (const k of keys) if (!o.has(k)) throw new Refused(`${at}.${k}`, 'a missing key');
  return o;
}

function field(o: JsonObject, at: string, key: string): Json {
  const v = o.get(key);
  if (v === undefined) throw new Refused(`${at}.${key}`, 'a missing key');
  return v;
}

/** `read(o's key)`, at its own path. */
const at = <T>(o: JsonObject, path: string, key: string, read: Reader<T>): T => read(field(o, path, key), `${path}.${key}`);

/** A string of at least `min` characters (code points, as the schema counts them). */
const text =
  (min = 0): Reader<string> =>
  (v, path) => {
    if (typeof v !== 'string') throw new Refused(path, 'not a string');
    if ([...v].length < min) throw new Refused(path, `shorter than ${min}`);
    return v;
  };

const integer =
  (min = Number.MIN_SAFE_INTEGER): Reader<number> =>
  (v, path) => {
    if (!(v instanceof JsonNumber) || !v.integer) throw new Refused(path, 'not a JSON integer');
    if (v.value < min) throw new Refused(path, `less than ${min}`);
    return v.value;
  };

const boolean: Reader<boolean> = (v, path) => {
  if (typeof v !== 'boolean') throw new Refused(path, 'not a bool');
  return v;
};

/** One string of its list, never another spelling or a tagged object. */
const oneOf =
  <const T extends string>(values: readonly T[]): Reader<T> =>
  (v, path) => {
    const found = values.find((x) => x === v);
    if (found === undefined) throw new Refused(path, `not one of ${values.join(', ')}`);
    return found;
  };

const list =
  <T>(item: Reader<T>): Reader<T[]> =>
  (v, path) => {
    if (!Array.isArray(v)) throw new Refused(path, 'not a list');
    return v.map((x, i) => item(x, `${path}[${i}]`));
  };

const nullable =
  <T>(read: Reader<T>): Reader<T | null> =>
  (v, path) =>
    v === null ? null : read(v, path);

const matching =
  (pattern: RegExp, what: string): Reader<string> =>
  (v, path) => {
    const s = text()(v, path);
    if (!pattern.test(s)) throw new Refused(path, `not ${what}`);
    return s;
  };

const readId = matching(/^r[0-9]+$/, 'a read id (r, then digits)');
const commit = matching(/^[0-9a-f]{40}$/, 'a commit (40 lowercase hex digits)');
const number = integer(1);
const count = integer(0);

/** The one key of a worked-out value's form, refused unless it is one of `forms`. */
function form<F extends string>(v: Json, path: string, forms: readonly F[]): [F, Json] {
  const o = object(v, path);
  const keys = [...o.keys()];
  const key = keys.length === 1 ? forms.find((f) => f === keys[0]) : undefined;
  if (key === undefined) throw new Refused(path, `not one of the forms ${forms.map((f) => `{"${f}": …}`).join(', ')}`);
  return [key, field(o, path, key)];
}

const unreadList = list(readId);

/** `{"known": v}` or `{"unread": [...]}`. */
const known =
  <T>(read: Reader<T>): Reader<{ known: T } | Unread> =>
  (v, path) => {
    const [f, inner] = form(v, path, ['known', 'unread']);
    return f === 'known' ? { known: read(inner, `${path}.known`) } : { unread: unreadList(inner, `${path}.unread`) };
  };

const failed = (o: JsonObject, path: string) => {
  exact(o, path, ['state', 'gap', 'reason']);
  return { state: 'failed' as const, gap: at(o, path, 'gap', oneOf(GAP_KINDS)), reason: at(o, path, 'reason', text(1)) };
};

/** A read's outcome: complete or failed. */
const outcome =
  <T>(value: Reader<T>) =>
  (v: Json, path: string) => {
    const o = object(v, path);
    if (at(o, path, 'state', oneOf(['complete', 'failed'])) === 'failed') return failed(o, path);
    exact(o, path, ['state', 'value']);
    return { state: 'complete' as const, value: at(o, path, 'value', value) };
  };

/** A list read's outcome: complete, partial (truncated) or failed. */
const listOutcome =
  <T>(item: Reader<T>) =>
  (v: Json, path: string) => {
    const o = object(v, path);
    const state = at(o, path, 'state', oneOf(['complete', 'partial', 'failed']));
    if (state === 'failed') return failed(o, path);
    if (state === 'complete') {
      exact(o, path, ['state', 'value']);
      return { state, value: at(o, path, 'value', list(item)) };
    }
    exact(o, path, ['state', 'gap', 'reason', 'value']);
    return { state, gap: at(o, path, 'gap', oneOf(['truncated'])), reason: at(o, path, 'reason', text(1)), value: at(o, path, 'value', list(item)) };
  };

/** #539: exactly `{wording, link, asked_at}`; absent, never null, when no question was established. */
const pendingQuestion: Reader<PendingQuestion> = (v, path) => {
  const o = exact(v, path, ['wording', 'link', 'asked_at']);
  return { wording: at(o, path, 'wording', text(1)), link: at(o, path, 'link', text(1)), asked_at: at(o, path, 'asked_at', integer()) };
};

const ISSUE_KEYS = ['title', 'state', 'milestone', 'labels', 'owned_paths', 'relies_on'] as const;

const issue: Reader<Issue> = (v, path) => {
  const o = exact(v, path, object(v, path).has('pending_question') ? [...ISSUE_KEYS, 'pending_question'] : ISSUE_KEYS);
  const question = o.has('pending_question') ? { pending_question: at(o, path, 'pending_question', pendingQuestion) } : {};
  return {
    ...question,
    title: at(o, path, 'title', text()),
    state: at(o, path, 'state', oneOf(['open', 'closed'])),
    milestone: at(
      o,
      path,
      'milestone',
      nullable((m, p) => {
        const mo = exact(m, p, ['number', 'title']);
        return { number: at(mo, p, 'number', number), title: at(mo, p, 'title', text()) };
      }),
    ),
    labels: at(o, path, 'labels', list(text(1))),
    owned_paths: at(o, path, 'owned_paths', nullable(text(1))),
    relies_on: at(o, path, 'relies_on', nullable(text(1))),
  };
};

const PR_KEYS = ['number', 'state', 'draft', 'head_branch', 'head_commit', 'base_branch', 'closes'] as const;

/** null, an open or a merged pull request, or several. */
const pullRequest: Reader<OpenPr | MergedPr | SeveralPrs | null> = (v, path) => {
  if (v === null) return null;
  const o = object(v, path);
  const state = at(o, path, 'state', oneOf(['open', 'merged', 'several']));
  if (state === 'several') {
    exact(o, path, ['state', 'numbers']);
    return { state, numbers: at(o, path, 'numbers', list(number)) };
  }
  exact(o, path, state === 'open' ? PR_KEYS : [...PR_KEYS, 'merge_commit', 'merged_at']);
  const pr = {
    number: at(o, path, 'number', number),
    draft: at(o, path, 'draft', boolean),
    head_branch: at(o, path, 'head_branch', text(1)),
    head_commit: at(o, path, 'head_commit', commit),
    base_branch: at(o, path, 'base_branch', text(1)),
    closes: at(o, path, 'closes', list(number)),
  };
  if (state === 'open') return { ...pr, state };
  return { ...pr, state, merge_commit: at(o, path, 'merge_commit', commit), merged_at: at(o, path, 'merged_at', integer()) };
};

const check: Reader<Check> = (v, path) => {
  const o = exact(v, path, ['name', 'result']);
  return { name: at(o, path, 'name', text(1)), result: at(o, path, 'result', oneOf(['pass', 'fail', 'pending', 'skipping', 'cancel'])) };
};

const review: Reader<Review> = (v, path) => {
  const o = exact(v, path, ['verdict', 'commit']);
  return { verdict: at(o, path, 'verdict', oneOf(['approve', 'changes'])), commit: at(o, path, 'commit', commit) };
};

const thread: Reader<Thread> = (v, path) => {
  const o = object(v, path);
  const kind = at(o, path, 'kind', oneOf(['cloud', 'local']));
  if (kind === 'cloud') {
    exact(o, path, ['thread', 'project', 'kind']);
    return { thread: at(o, path, 'thread', text(1)), project: at(o, path, 'project', text(1)), kind };
  }
  exact(o, path, ['thread', 'project', 'kind', 'branch']);
  return { thread: at(o, path, 'thread', text(1)), project: at(o, path, 'project', text(1)), kind, branch: at(o, path, 'branch', nullable(text(1))) };
};

const READ_KINDS = [
  'version',
  'repository',
  'spec_list',
  'issue',
  'sub_issues',
  'blocked_by',
  'pr_discovery',
  'checks',
  'comments',
  'merge_readback',
  'projects',
  'threads',
  'workspace',
] as const;

/** One read record, by its kind: exactly that kind's subject and outcome. */
export const readRecord: Reader<Read> = (v, path) => {
  const o = object(v, path);
  const kind = at(o, path, 'kind', oneOf(READ_KINDS));
  const keys = (...subject: string[]) => exact(o, path, ['id', 'kind', ...subject, 'outcome']);
  const id = () => at(o, path, 'id', readId);
  const result = <T>(read: (v: Json, path: string) => T) => at(o, path, 'outcome', read);
  switch (kind) {
    case 'version':
      keys('source');
      return { id: id(), kind, source: at(o, path, 'source', oneOf(['github', 'cloudroom'])), outcome: result(outcome(text(1))) };
    case 'repository':
      keys();
      return {
        id: id(),
        kind,
        outcome: result(
          outcome((r, p) => {
            const ro = exact(r, p, ['name']);
            return { name: at(ro, p, 'name', text(1)) };
          }),
        ),
      };
    case 'spec_list':
      keys();
      return { id: id(), kind, outcome: result(listOutcome(number)) };
    case 'issue':
      keys('issue');
      return { id: id(), kind, issue: at(o, path, 'issue', number), outcome: result(outcome(issue)) };
    case 'sub_issues':
      keys('spec');
      return { id: id(), kind, spec: at(o, path, 'spec', number), outcome: result(listOutcome(number)) };
    case 'blocked_by':
      keys('ticket');
      return { id: id(), kind, ticket: at(o, path, 'ticket', number), outcome: result(listOutcome(number)) };
    case 'pr_discovery':
      keys('issue');
      return { id: id(), kind, issue: at(o, path, 'issue', number), outcome: result(outcome(pullRequest)) };
    case 'checks':
      keys('pr');
      return { id: id(), kind, pr: at(o, path, 'pr', number), outcome: result(listOutcome(check)) };
    case 'comments':
      keys('pr');
      return { id: id(), kind, pr: at(o, path, 'pr', number), outcome: result(outcome(nullable(review))) };
    case 'merge_readback':
      keys('pr');
      return { id: id(), kind, pr: at(o, path, 'pr', number), outcome: result(outcome(boolean)) };
    case 'projects':
      keys();
      return {
        id: id(),
        kind,
        outcome: result(
          listOutcome((p, pp) => {
            const po = exact(p, pp, ['id', 'name']);
            return { id: at(po, pp, 'id', text(1)), name: at(po, pp, 'name', text()) };
          }),
        ),
      };
    case 'threads':
      keys();
      return { id: id(), kind, outcome: result(listOutcome(thread)) };
    case 'workspace':
      keys('thread');
      return { id: id(), kind, thread: at(o, path, 'thread', text(1)), outcome: result(outcome(text(1))) };
  }
};

const source =
  <N extends string>(name: N): Reader<Source<N>> =>
  (v, path) => {
    const o = exact(v, path, ['name', 'version', 'tested_version', 'version_tested']);
    return {
      name: at(o, path, 'name', oneOf([name])),
      version: at(o, path, 'version', readId),
      tested_version: at(o, path, 'tested_version', text()),
      version_tested: at(o, path, 'version_tested', boolean),
    };
  };

const TICKET_STATES = ['ready', 'building', 'in_review', 'changes_requested', 'merged', 'held', 'blocked'] as const satisfies readonly TicketState[];

const counts: Reader<Counts> = (v, path) => {
  const o = exact(v, path, ['tickets', ...TICKET_STATES, 'unknown']);
  const n = (key: string) => at(o, path, key, count);
  return {
    tickets: n('tickets'),
    ready: n('ready'),
    building: n('building'),
    in_review: n('in_review'),
    changes_requested: n('changes_requested'),
    merged: n('merged'),
    held: n('held'),
    blocked: n('blocked'),
    unknown: n('unknown'),
  };
};

const fleet: Reader<Fleet> = (v, path) => {
  const o = exact(v, path, ['spec', 'issue', 'tickets', 'progress']);
  return { spec: at(o, path, 'spec', number), issue: at(o, path, 'issue', readId), tickets: at(o, path, 'tickets', readId), progress: at(o, path, 'progress', known(counts)) };
};

const ticketState: Reader<FleetsTicket['state']> = (v, path) => {
  const [f, inner] = form(v, path, ['known', 'unread', 'unknown']);
  if (f === 'known') return { known: oneOf(TICKET_STATES)(inner, `${path}.known`) };
  if (f === 'unread') return { unread: unreadList(inner, `${path}.unread`) };
  return { unknown: text(1)(inner, `${path}.unknown`) };
};

const ticket: Reader<FleetsTicket> = (v, path) => {
  const o = exact(v, path, ['number', 'issue', 'blocked_by', 'pr', 'ci', 'review', 'on_base', 'state']);
  return {
    number: at(o, path, 'number', number),
    issue: at(o, path, 'issue', readId),
    blocked_by: at(o, path, 'blocked_by', readId),
    pr: at(o, path, 'pr', readId),
    ci: at(o, path, 'ci', nullable(readId)),
    review: at(o, path, 'review', nullable(readId)),
    on_base: at(o, path, 'on_base', nullable(readId)),
    state: at(o, path, 'state', ticketState),
  };
};

const blocker: Reader<Blocker> = (v, path) => {
  const o = exact(v, path, ['number', 'issue', 'pr', 'on_base', 'fleet', 'merged']);
  return {
    number: at(o, path, 'number', number),
    issue: at(o, path, 'issue', readId),
    pr: at(o, path, 'pr', readId),
    on_base: at(o, path, 'on_base', nullable(readId)),
    fleet: at(o, path, 'fleet', known(nullable(number))),
    merged: at(o, path, 'merged', known(boolean)),
  };
};

/** `{"known": v}` or `{"unknown": reason}`, the reason never empty. */
const fact =
  <T>(read: Reader<T>): Reader<Known<T>> =>
  (v, path) => {
    const [f, inner] = form(v, path, ['known', 'unknown']);
    return f === 'known' ? { known: read(inner, `${path}.known`) } : { unknown: text(1)(inner, `${path}.unknown`) };
  };

const needsYou: Reader<NeedsYou> = (v, path) => {
  const o = exact(v, path, ['kind', 'spec', 'ticket', 'wording', 'link', 'asked_at', 'risk']);
  return {
    kind: at(o, path, 'kind', oneOf(['needs_info', 'held'])),
    spec: at(o, path, 'spec', number),
    ticket: at(o, path, 'ticket', number),
    wording: at(o, path, 'wording', fact(text(1))),
    link: at(o, path, 'link', fact(text(1))),
    asked_at: at(o, path, 'asked_at', fact(integer())),
    risk: at(o, path, 'risk', fact(oneOf(['live', 'release', 'publish']))),
  };
};

/** The fleets view only: the fleet view (`openwiz fleet <spec>`) is another reader's. */
const fleetsView: Reader<FleetsView> = (v, path) => {
  const o = object(v, path);
  if (!o.has('view')) throw new Refused(`${path}.view`, 'a missing key');
  const view = at(o, path, 'view', oneOf(['fleets']));
  exact(o, path, ['view', 'repository', 'specs', 'fleets', 'tickets', 'blockers', 'needs_you']);
  return {
    view,
    repository: at(o, path, 'repository', readId),
    specs: at(o, path, 'specs', readId),
    fleets: at(o, path, 'fleets', list(fleet)),
    tickets: at(o, path, 'tickets', list(ticket)),
    blockers: at(o, path, 'blockers', list(blocker)),
    needs_you: at(o, path, 'needs_you', known(list(needsYou))),
  };
};

/** Shared strict envelope; each view chooses its data and CloudRoom reader. */
export const envelopeReader = <D, C>(data: Reader<D>, cloudroom: Reader<C>) => (v: Json, path: string) => {
  const value = object(v, path);
  const hasTarget = value.has('orchestrator');
  const o = exact(value, path, ['schema', 'sources', 'reads', 'coverage', 'freshness', 'data', ...(hasTarget ? ['orchestrator'] : [])]);
  const target = hasTarget ? at(o, path, 'orchestrator', text(1)) : null;
  if (target !== null && (target.length > 128 || !/^[A-Za-z0-9_][A-Za-z0-9_-]*$/.test(target))) throw new Refused(`${path}.orchestrator`, 'not a thread id');
  return {
    ...(target === null ? {} : { orchestrator: target }),
    schema: at(o, path, 'schema', oneOf(['openwiz.fleet.v1'] as const)),
    sources: at(o, path, 'sources', (s, p) => {
      const so = exact(s, p, ['github', 'cloudroom']);
      return { github: at(so, p, 'github', source('gh')), cloudroom: at(so, p, 'cloudroom', cloudroom) };
    }),
    reads: at(o, path, 'reads', list(readRecord)),
    coverage: at(o, path, 'coverage', (c, p) => ({ state: at(exact(c, p, ['state']), p, 'state', oneOf(['complete', 'partial'])) })),
    freshness: at(o, path, 'freshness', (f, p) => ({ snapshot_at: at(exact(f, p, ['snapshot_at']), p, 'snapshot_at', integer()) })),
    data: at(o, path, 'data', data),
  };
};

const envelope: Reader<FleetsEnvelope> = envelopeReader(fleetsView, nullable(source('room-cli')));

/** `openwiz fleets --json`'s text, exactly as the contract has it, or where and why it was refused. */
export function readFleets(text: string): ReadResult {
  try {
    return { ok: true, envelope: envelope(parseJson(text), '$') };
  } catch (e) {
    if (e instanceof Refused) return { ok: false, refusal: { at: e.at, why: e.message } };
    // A text deep enough to exhaust the stack anyway is refused like any other.
    if (e instanceof RangeError) return { ok: false, refusal: { at: '$', why: 'not JSON: nested too deep' } };
    throw e;
  }
}

/** Detail tickets add agents to the exact list ticket shape. */
const detailTicket: Reader<FleetTicket> = (v, path) => {
  const o = exact(v, path, ['number', 'issue', 'blocked_by', 'pr', 'ci', 'review', 'on_base', 'state', 'builder', 'reviewer']);
  const fields = new Map(o);
  fields.delete('builder');
  fields.delete('reviewer');
  return {
    ...ticket(fields, path),
    builder: at(o, path, 'builder', known(nullable(text(1)))),
    reviewer: at(o, path, 'reviewer', (r, p) => ({ undefined: at(exact(r, p, ['undefined']), p, 'undefined', text(1)) })),
  };
};

const unplaced: Reader<Unplaced> = (v, path) => {
  const o = exact(v, path, ['thread', 'reason']);
  return { thread: at(o, path, 'thread', text(1)), reason: at(o, path, 'reason', oneOf(['no_branch', 'shared_branch', 'no_pull_request', 'several_tickets', 'several_issues'])) };
};

const fleetView: Reader<FleetView> = (v, path) => {
  const o = exact(v, path, ['view', 'repository', 'projects', 'threads', 'fleet', 'tickets', 'blockers', 'needs_you', 'unplaced']);
  return {
    view: at(o, path, 'view', oneOf(['fleet'])),
    repository: at(o, path, 'repository', readId),
    projects: at(o, path, 'projects', readId),
    threads: at(o, path, 'threads', readId),
    fleet: at(o, path, 'fleet', fleet),
    tickets: at(o, path, 'tickets', list(detailTicket)),
    blockers: at(o, path, 'blockers', list(blocker)),
    needs_you: at(o, path, 'needs_you', known(list(needsYou))),
    unplaced: at(o, path, 'unplaced', known(list(unplaced))),
  };
};

const fleetEnvelope: Reader<FleetEnvelope> = envelopeReader(fleetView, source('room-cli'));

/** A strict detail response, optionally bound to the spec the caller asked for. */
export function readFleet(text: string, spec?: number): { ok: true; envelope: FleetEnvelope } | { ok: false; refusal: Refusal } {
  try {
    const envelope = fleetEnvelope(parseJson(text), '$');
    const ids = new Set<string>();
    for (const [i, read] of envelope.reads.entries()) {
      if (ids.has(read.id)) throw new Refused(`$.reads[${i}].id`, 'duplicate read id');
      ids.add(read.id);
    }
    if (spec !== undefined && envelope.data.fleet.spec !== spec) throw new Refused('$.data.fleet.spec', 'not the requested spec');
    return { ok: true, envelope };
  } catch (e) {
    if (e instanceof Refused) return { ok: false, refusal: { at: e.at, why: e.message } };
    if (e instanceof RangeError) return { ok: false, refusal: { at: '$', why: 'not JSON: nested too deep' } };
    throw e;
  }
}

// ── what the list shows ──

/** A word, a glyph and a tier's shape (docs/design-rules.md, "Markers"), and what it names or counts. */
export type FleetsMarker = Marker & { kind: 'needs_info' | 'held' | 'moving' | 'blocked' | 'unknown' };
/** A "needs you" item: what it needs, on which ticket, and from which fleet. */
/**
 * A "needs you" item: what it needs, on which ticket, and from which fleet.
 * #539: its question (the comment's first line, or unknown with why), the
 * comment's link and asked time (null when unknown for the question's own
 * reason, so it isn't said twice), and its labelled risk (unknown, never safe).
 */
export type NeedItem = { kind: NeedsYou['kind']; marker: FleetsMarker; ticket: number; title: Text; need: string; spec: number; fleet: Text; question: Text; link: Text | null; asked: Text | null; risk: Text };
/** A fleet's row: its spec's name, "N of M merged" (null when unknown), and its counts as markers. */
export type FleetRow = { spec: number; title: Text; merged: string | null; counts: FleetsMarker[] };
export type FleetsList = {
  snapshotAt: number;
  partial: boolean;
  /** Every read that isn't complete, in the order of reads: the contract's gaps. */
  gaps: FleetGap[];
  needsYou: { kind: 'items'; items: NeedItem[] } | { kind: 'unread'; marker: FleetsMarker };
  /** The spec list: read in full, in part, or not. */
  list: { kind: 'complete' } | { kind: 'partial'; reason: string } | { kind: 'unread'; marker: FleetsMarker };
  fleets: FleetRow[];
};

/**
 * Each marker's tier and glyph, the builder's proposal, Open for Jake (as
 * every tier is: docs/design-rules.md): "needs you" waits on you (t1, as
 * fleetGraph.ts's held); moving and blocked count fleetGraph.ts's t3 and t4
 * states; unknown and unread are unsure (t5).
 */
const MARKS = {
  needs_info: ['t1', '[!]'],
  held: ['t1', '[!]'],
  moving: ['t3', '[~]'],
  blocked: ['t4', '[‖]'],
  unknown: ['t5', '[?]'],
} as const;

const marker = (kind: FleetsMarker['kind'], word: string): FleetsMarker => ({ kind, tier: MARKS[kind][0], glyph: MARKS[kind][1], word });

/** What each kind of item needs, in the contract's terms (`needs_info`: a builder's question; `held`: docs/agents/fleet.md). */
const NEEDS = {
  needs_info: 'a builder\'s question waits for an answer',
  held: 'waits for your approval of a changed plan or contract',
} as const;

type Index = ReadonlyMap<string, Read | 'twice'>;

function indexOf(reads: readonly Read[]): Index {
  const m = new Map<string, Read | 'twice'>();
  for (const r of reads) m.set(r.id, m.has(r.id) ? 'twice' : r);
  return m;
}

function isKind<K extends Read['kind']>(r: Read, kind: K): r is Extract<Read, { kind: K }> {
  return r.kind === kind;
}

type Pointed<R> = { ok: true; read: R } | { ok: false; why: string };

/** The read a pointer names, only when it is the one its value needs: of its kind, and about its subject. */
function pointed<K extends Read['kind']>(idx: Index, id: string, kind: K, what: string, about: (r: Extract<Read, { kind: K }>) => boolean): Pointed<Extract<Read, { kind: K }>> {
  const r = idx.get(id);
  if (r === undefined) return { ok: false, why: `read ${id} isn't on the record` };
  if (r === 'twice') return { ok: false, why: `read ${id} is on the record twice` };
  if (!isKind(r, kind) || !about(r)) return { ok: false, why: `read ${id} isn't ${what}` };
  return { ok: true, read: r };
}

const unknownTitle = (why: string): Text => ({ text: unknownText(why), unknown: true });

/** Issue #n's title, from the issue read its pointer names; otherwise unknown, with why. */
function titleOf(idx: Index, id: string, n: number): Text {
  const p = pointed(idx, id, 'issue', `#${n}'s issue read`, (r) => r.issue === n);
  if (!p.ok) return unknownTitle(p.why);
  const o = p.read.outcome;
  return o.state === 'complete' ? { text: o.value.title, unknown: false } : unknownTitle(`unread: ${o.reason}`);
}

/** Why an unread value isn't known: each read it names, in its own words, once each. */
function whyUnread(idx: Index, ids: readonly string[]): string {
  const why = ids.map((id) => {
    const r = idx.get(id);
    if (r === undefined) return `read ${id} isn't on the record`;
    if (r === 'twice') return `read ${id} is on the record twice`;
    return r.outcome.state === 'complete' ? `read ${id} is complete, yet named unread` : r.outcome.reason;
  });
  return why.length === 0 ? 'no read named' : [...new Set(why)].join('; ');
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

function rowOf(f: Fleet, idx: Index): FleetRow {
  const title = titleOf(idx, f.issue, f.spec);
  if ('unread' in f.progress) return { spec: f.spec, title, merged: null, counts: [marker('unknown', `progress ${unknownText(`unread: ${whyUnread(idx, f.progress.unread)}`)}`)] };
  const c = f.progress.known;
  return {
    spec: f.spec,
    title,
    merged: `${c.merged} of ${c.tickets} merged`,
    // "Moving" is the contract's: building + in_review + changes_requested.
    counts: [marker('moving', `${c.building + c.in_review + c.changes_requested} moving`), marker('blocked', `${c.blocked} blocked`), ...(c.unknown > 0 ? [marker('unknown', `${c.unknown} unknown`)] : [])],
  };
}

function needsOf(view: Pick<FleetsView, 'needs_you' | 'tickets' | 'fleets'>, idx: Index): FleetsList['needsYou'] {
  const ny = view.needs_you;
  if ('unread' in ny) return { kind: 'unread', marker: marker('unknown', unknownText(`unread: ${whyUnread(idx, ny.unread)}`)) };
  return {
    kind: 'items',
    items: ny.known.map((item): NeedItem => {
      const t = view.tickets.find((x) => x.number === item.ticket);
      const f = view.fleets.find((x) => x.spec === item.spec);
      return {
        kind: item.kind,
        marker: marker(item.kind, item.kind),
        ticket: item.ticket,
        title: t === undefined ? unknownTitle(`#${item.ticket} isn't on the record as a ticket`) : titleOf(idx, t.issue, t.number),
        need: NEEDS[item.kind],
        ...questionOf(item),
        spec: item.spec,
        fleet: f === undefined ? unknownTitle(`#${item.spec} isn't on the record as a fleet`) : titleOf(idx, f.issue, f.spec),
      };
    }),
  };
}

/** UTC, to the minute: the time a question was asked, as its comment says; null outside a date's range. */
function askedText(ms: number): string | null {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return null;
  const two = (n: number) => String(n).padStart(2, '0');
  return `asked ${d.getUTCFullYear()}-${two(d.getUTCMonth() + 1)}-${two(d.getUTCDate())} ${two(d.getUTCHours())}:${two(d.getUTCMinutes())} UTC`;
}

/** #539: an item's question, link, asked time and risk, as reported; each unknown says why. */
function questionOf(item: NeedsYou): Pick<NeedItem, 'question' | 'link' | 'asked' | 'risk'> {
  const shown = (t: string): Text => ({ text: t, unknown: false });
  const unsure = (what: string, why: string): Text => ({ text: `${what} ${unknownText(why)}`, unknown: true });
  const sameWhy = (f: Known<unknown>) => 'unknown' in item.wording && 'unknown' in f && f.unknown === item.wording.unknown;
  return {
    question: 'known' in item.wording ? shown(item.wording.known) : unsure('question', item.wording.unknown),
    link: 'known' in item.link ? shown(item.link.known) : sameWhy(item.link) ? null : unsure('link', item.link.unknown),
    asked: 'unknown' in item.asked_at
      ? sameWhy(item.asked_at) ? null : unsure('asked', item.asked_at.unknown)
      : ((t) => (t === null ? unsure('asked', `the time ${item.asked_at.known} is out of range`) : shown(t)))(askedText(item.asked_at.known)),
    risk: 'known' in item.risk ? shown(`risk: ${item.risk.known}`) : unsure('risk', item.risk.unknown),
  };
}

function listOf(view: FleetsView, idx: Index): FleetsList['list'] {
  const p = pointed(idx, view.specs, 'spec_list', 'the spec list read', () => true);
  if (!p.ok) return { kind: 'unread', marker: marker('unknown', unknownText(p.why)) };
  const o = p.read.outcome;
  if (o.state === 'complete') return { kind: 'complete' };
  if (o.state === 'partial') return { kind: 'partial', reason: o.reason };
  return { kind: 'unread', marker: marker('unknown', unknownText(`unread: ${o.reason}`)) };
}

/** Everything the fleets list shows, from `openwiz fleets --json`, as reported: in its order, nothing filled in. */
export function fleetsList(envelope: FleetsEnvelope): FleetsList {
  const idx = indexOf(envelope.reads);
  const view = envelope.data;
  return {
    snapshotAt: envelope.freshness.snapshot_at,
    partial: envelope.coverage.state !== 'complete',
    gaps: envelope.reads.flatMap((r) => (r.outcome.state === 'complete' ? [] : [{ read: r.id, subject: subjectOf(r), gap: r.outcome.gap, reason: r.outcome.reason }])),
    needsYou: needsOf(view, idx),
    list: listOf(view, idx),
    fleets: view.fleets.map((f) => rowOf(f, idx)),
  };
}

/** The same reported owner decisions for a single fleet, in their reported order. */
export function fleetNeedsYou(envelope: FleetEnvelope): FleetsList['needsYou'] {
  return needsOf({ ...envelope.data, fleets: [envelope.data.fleet] }, indexOf(envelope.reads));
}
