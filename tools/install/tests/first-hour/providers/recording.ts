// The recording and fault provider for the first hour's browser-state fault
// cases (#2222, contracts/first-hour.v1.md, "Recovery cases").
//
// It stands where OpenWiz's loopback server and its core stand for the web
// page: the send (`POST /api/v1/sessions/{id}/messages`), its lookup, the
// create (`POST /api/v1/projects/{id}/threads`), its status read and the Cloud
// options, as contracts/web-api.v1.md names them. It keeps the core's
// once-only rule as the M and N proofs show it (crates/core): one record per
// op id in the owner's state directory, a repeat of the same op id is answered
// from that record and never calls the provider again, and only a new op id
// is a new provider call. It counts, per owner intent (an op id's 32-hex
// root), every provider call and every effect, and logs every request, so a
// fault case observes effects and retries rather than the page's internals.
//
// Faults are queued for the next write and model what the contract's
// interruptions do at this seam: Access signing the owner out (a redirect,
// before OpenWiz), OpenWiz refusing before the core, a reply lost after the
// effect, and the server process stopping after the effect (its records are
// owner state and survive `restart`). Every value is synthetic; the answers
// are the web proofs' own synthetic shapes, which the page's exact parsers
// read and the real server's answers are proven against.

import { createHash } from 'node:crypto';

import type { FetchLike, ResponseLike } from '../../../../../apps/web/src/api.ts';
import type { Options } from '../../../../../apps/web/src/newthread.ts';
import * as nt from '../../../../../apps/web/test/support/newthread-synthetic.ts';
import { DELIVERIES, lookup, outcome, report } from '../../../../../apps/web/test/support/synthetic.ts';

/** One owner intent's kind, as the first-hour contract names web-api.v1's two writes. */
export type IntentKind = 'send' | 'new_thread';

/** What a fault does to the next write it applies to. */
export type Fault =
  /** Access signs the owner out: a redirect before OpenWiz. No record, no call. */
  | 'signed_out'
  /** OpenWiz's own refusal before the core (its JSON error). No record, no call. */
  | 'refused'
  /** The core records the write and the provider makes the effect; the reply never reaches the page. */
  | 'lose_reply'
  /** As `lose_reply`, then the server process stops: every request fails until `restart`. */
  | 'stop_after_effect';

/** One owner-state record: the core's claim of one op id, kept across a restart. */
export type Rec = { opId: string; intent: string; kind: IntentKind; fingerprint: string; textSha256: string; report: unknown };

/** One request as it reached the provider. */
export type Logged = { method: string; url: string; body: unknown; answered: 'reply' | 'lost' | 'down' | 'signed_out' | 'refused' };

const sha = (text: string): string => createHash('sha256').update(text, 'utf8').digest('hex');

/** An op id's owner intent: the 32 hex digits of its root (`web-<hex>-q<n>`, `-s<n>`, `-c<n>`). */
export function intentOf(opId: string): string {
  const m = /^web-([0-9a-f]{32})-[qsc][1-9][0-9]*$/.exec(opId);
  if (!m) throw new Error(`not a derived web op id: ${opId}`);
  return m[1]!;
}

/** The canonical JSON of a value: keys sorted, no spaces (setup.v1's fingerprint form). */
function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`;
  if (v !== null && typeof v === 'object') {
    return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canonical((v as Record<string, unknown>)[k])}`).join(',')}}`;
  }
  return JSON.stringify(v);
}

/**
 * An intent's request fingerprint, in setup.v1's form: SHA-256 of the kind and
 * the canonical request. Its request is what the owner asked for, the same
 * under every op id derived for it: the target and the text of a send; the
 * project, the three settings and the prompt of a create.
 */
export function fingerprint(kind: IntentKind, request: Record<string, string>): string {
  return sha(canonical({ kind, request }));
}

export const sendRequest = (target: string, text: string) => ({ target, text });
export const createRequest = (project: string, b: { harness: string; model: string; effort: string; text: string }) => ({ project, harness: b.harness, model: b.model, effort: b.effort, text: b.text });

const SEND = /^\/api\/v1\/sessions\/([^/]+)\/messages$/;
const LOOKUP = /^\/api\/v1\/sessions\/([^/]+)\/messages\/([^/]+)$/;
const CREATE = /^\/api\/v1\/projects\/([^/]+)\/threads$/;
const STATUS = /^\/api\/v1\/new-threads\/([^/]+)$/;
const OPTIONS = '/api/v1/cloud-options';

function reply(status: number, value: unknown): ResponseLike {
  const body = JSON.stringify(value);
  return { type: 'basic', status, headers: { get: (n: string) => (n.toLowerCase() === 'content-type' ? 'application/json' : null) }, text: async () => body };
}
const REDIRECT: ResponseLike = { type: 'opaqueredirect', status: 0, headers: { get: () => null }, text: async () => '' };
const REFUSAL = { error: { kind: 'synthetic_refused', message: 'synthetic: refused before the core; nothing was sent' } };

/** The recording provider, with its fault queue. One instance is one owner's OpenWiz, across restarts. */
export class RecordingProvider {
  /** Owner state: the core's records by op id. Survives `restart`; a browser restart never touches it. */
  readonly records = new Map<string, Rec>();
  /** Provider calls per intent: each new op id the core claims is one. A replay is not a call. */
  readonly calls = new Map<string, number>();
  /** Provider effects per intent: messages delivered, threads created. */
  readonly effects = new Map<string, number>();
  /** Reads of the core's exact record per intent (lookups, status reads, replays of the same op id): the reconciliation. */
  readonly reads = new Map<string, number>();
  readonly log: Logged[] = [];
  /** What `GET /api/v1/cloud-options` answers: the harnesses whose accounts are usable now. */
  options: Options = nt.options();
  private faults: Fault[] = [];
  private down = false;
  private threads = 0;

  /** Queues a fault for the next write (send or create). */
  fault(f: Fault): void {
    this.faults.push(f);
  }

  /** The server process starts again: owner-state records are kept, nothing in flight is. */
  restart(): void {
    this.down = false;
  }

  get stopped(): boolean {
    return this.down;
  }

  /** The provider's exact resource for an intent, read back: its records, in claim order. */
  readBack(intent: string): Rec[] {
    return [...this.records.values()].filter((r) => r.intent === intent);
  }

  readonly fetch: FetchLike = async (url, init) => {
    const method = init.method ?? 'GET';
    const body: unknown = typeof init.body === 'string' ? JSON.parse(init.body) : null;
    const entry: Logged = { method, url, body, answered: 'reply' };
    this.log.push(entry);
    if (this.down) {
      entry.answered = 'down';
      throw new TypeError('Failed to fetch');
    }
    if (method === 'POST' && (SEND.test(url) || CREATE.test(url))) return this.write(url, body as Record<string, unknown>, entry);
    let m: RegExpExecArray | null;
    if (method === 'GET' && (m = LOOKUP.exec(url))) {
      const [id, opId] = [decodeURIComponent(m[1]!), decodeURIComponent(m[2]!)];
      this.count(this.reads, intentOf(opId));
      const rec = this.records.get(opId);
      return reply(200, lookup(id, opId, (rec?.report ?? null) as Parameters<typeof lookup>[2]));
    }
    if (method === 'GET' && (m = STATUS.exec(url))) {
      const opId = decodeURIComponent(m[1]!);
      this.count(this.reads, intentOf(opId));
      const rec = this.records.get(opId);
      return reply(200, nt.status(opId, (rec?.report ?? null) as Parameters<typeof nt.status>[1]));
    }
    if (method === 'GET' && url === OPTIONS) return reply(200, this.options);
    throw new Error(`the recording provider has no route for ${method} ${url}`);
  };

  private count(map: Map<string, number>, intent: string): void {
    map.set(intent, (map.get(intent) ?? 0) + 1);
  }

  private write(url: string, body: Record<string, unknown>, entry: Logged): ResponseLike {
    const fault = this.faults.shift() ?? null;
    if (fault === 'signed_out') {
      entry.answered = 'signed_out';
      return REDIRECT;
    }
    if (fault === 'refused') {
      entry.answered = 'refused';
      return reply(403, REFUSAL);
    }
    const opId = String(body['op_id']);
    const send = SEND.exec(url);
    const known = this.records.get(opId);
    let answer: unknown;
    if (known) {
      // The core answers a repeat of the same op id from its record: no call, no effect. That answer is the
      // record read back by its op id (web-api.v1: the only safe repeat), so it reconciles the intent.
      this.count(this.reads, known.intent);
      answer = replayed(known.report);
    } else {
      const intent = intentOf(opId);
      this.count(this.calls, intent);
      this.count(this.effects, intent);
      const text = String(body['text']);
      if (send) {
        const id = decodeURIComponent(send[1]!);
        const mode = body['mode'] === 'steer' ? 'steer' : 'queue';
        answer = report(id, opId, mode, text, outcome(DELIVERIES.sent));
        this.records.set(opId, { opId, intent, kind: 'send', fingerprint: fingerprint('send', sendRequest(id, text)), textSha256: sha(text), report: answer });
      } else {
        const project = decodeURIComponent(CREATE.exec(url)![1]!);
        const b = body as nt.CreateBody;
        const thread = `thr_web_9${String(++this.threads).padStart(3, '0')}`;
        answer = nt.report(project, b, nt.OUTCOMES.created(thread), nt.start(thread, 'waiting_to_start', b));
        this.records.set(opId, { opId, intent, kind: 'new_thread', fingerprint: fingerprint('new_thread', createRequest(project, b)), textSha256: sha(text), report: answer });
      }
    }
    if (fault === 'lose_reply' || fault === 'stop_after_effect') {
      entry.answered = 'lost';
      if (fault === 'stop_after_effect') this.down = true;
      throw new TypeError('Failed to fetch');
    }
    return reply(200, answer);
  }
}

function replayed(r: unknown): unknown {
  const x = r as { result: { kind: string } };
  return x.result.kind === 'outcome' ? { ...x, result: { ...x.result, replayed: true } } : x;
}

/**
 * A tab's sessionStorage: kept across a reload of that tab and a server
 * restart (the same object), and across a browser restart only when the
 * browser restores the tab (`restored`). A closed tab without restoration is
 * an empty one: #2492's scope, not shown here as retained.
 */
export class TabStorage {
  private readonly items = new Map<string, string>();
  getItem(k: string): string | null {
    return this.items.get(k) ?? null;
  }
  setItem(k: string, v: string): void {
    this.items.set(k, v);
  }
  removeItem(k: string): void {
    this.items.delete(k);
  }
  key(i: number): string | null {
    return [...this.items.keys()][i] ?? null;
  }
  get length(): number {
    return this.items.size;
  }
  /** The browser's session restore: a copy of every item, in a new tab. */
  restored(): TabStorage {
    const t = new TabStorage();
    for (const [k, v] of this.items) t.setItem(k, v);
    return t;
  }
}
