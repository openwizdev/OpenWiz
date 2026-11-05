// The only module that makes requests: same origin, `/api/v1/...`; GET, and
// the POSTs (below): the send, the create, the new-thread preview, which only
// reads, the upload (#16) and the loop switch (#549); and one DELETE, the removal of a staged copy.
// It turns every response into one outcome, so the page can tell signed out,
// disconnected, busy and the core's own errors apart (V6).

import { parseNotificationStatus, parseNotificationPreferences } from './notifications.ts';
import type { NotificationStatus, NotificationPreferences, NotificationPreferenceWrite } from './notifications.ts';

import { parseApiError } from './envelope.ts';
import type { ApiError, Envelope } from './envelope.ts';
import { readCockpitText } from './cockpit.ts';
import { readPlanText } from './plan.ts';
import type { Plan } from './plan.ts';
import type { Cockpit } from './cockpit.ts';
import { readDecisionsText } from './decisions.ts';
import type { Decisions } from './decisions.ts';
import { readFleet, readFleets } from './fleets.ts';
import { readLoopsText } from './loops.ts';
import type { LoopsView } from './loops.ts';
import { readTargetText, targetUrl } from './notificationTarget.ts';
import type { TargetResult } from './notificationTarget.ts';
import type { FleetsEnvelope } from './fleets.ts';
import type { FleetEnvelope } from './fleetGraph.ts';

export type ErrorBody = ApiError['error'];

export type Failure =
  | { kind: 'signed-out'; status: number | null }
  | { kind: 'disconnected'; cause: 'network' | 'timeout' | 'gateway'; status: number | null }
  | { kind: 'busy'; status: number; retryAfterMs: number | null; error: ErrorBody | null }
  /** A JSON error from the server or the core, or (error null) a response that is none of the above. */
  | { kind: 'error'; status: number; error: ErrorBody | null };

export type Outcome<D> = { kind: 'ok'; envelope: Envelope<D> } | Failure;

/** What `read` needs of a fetch response. */
export interface ResponseLike {
  readonly type: string;
  readonly status: number;
  readonly headers: { get(name: string): string | null };
  text(): Promise<string>;
}

export type FetchLike = (url: string, init: RequestInit) => Promise<ResponseLike>;

/** Why the page aborted a read: its own timeout, or it no longer wants it. */
export type AbortReason = 'timeout' | 'stop';

export const REQUEST_HEADERS: Readonly<Record<string, string>> = {
  Accept: 'application/json',
  // Cloudflare Access answers an expired sub-request with 401 when it carries
  // this header (approval sheet A-6), instead of redirecting it.
  'X-Requested-With': 'XMLHttpRequest',
};

/** The browser's fetch. The only use of it in the app. */
export const browserFetch: FetchLike = (url, init) => fetch(url, init);

/** The list route. `offset` is the only query the page sends; the core's default limit applies. */
export function inventoryUrl(offset: number): string {
  return Number.isSafeInteger(offset) && offset > 0 ? `/api/v1/inventory?offset=${offset}` : '/api/v1/inventory';
}

/** The detail route. The id is one encoded path segment, so it can never add a path or a query. */
export function sessionUrl(id: string): string {
  return `/api/v1/sessions/${encodeURIComponent(id)}`;
}

/** One read. `'stopped'` when the page aborted it with reason `'stop'`. */
export async function read<D>(
  fetchImpl: FetchLike,
  url: string,
  parse: (json: unknown) => Envelope<D> | null,
  signal: AbortSignal,
): Promise<Outcome<D> | 'stopped'> {
  return readText(fetchImpl, url, (body) => {
    const json = parseJson(body);
    return json === undefined ? null : parse(json);
  }, signal);
}

/** Read raw text so a strict contract reader can detect duplicate keys. */
async function readText<E>(fetchImpl: FetchLike, url: string, parse: (body: string) => E | null, signal: AbortSignal): Promise<{ kind: 'ok'; envelope: E } | Failure | 'stopped'> {
  let res: ResponseLike;
  let body = '';
  try {
    res = await fetchImpl(url, {
      method: 'GET',
      headers: REQUEST_HEADERS,
      credentials: 'same-origin',
      redirect: 'manual',
      cache: 'no-store',
      signal,
    });
    if (res.type !== 'opaqueredirect') body = await res.text();
  } catch {
    if (signal.aborted) return signal.reason === 'timeout' ? { kind: 'disconnected', cause: 'timeout', status: null } : 'stopped';
    return { kind: 'disconnected', cause: 'network', status: null };
  }
  return classify(res, body, parse);
}

function classify<E>(res: ResponseLike, body: string, parse: (body: string) => E | null): { kind: 'ok'; envelope: E } | Failure {
  // Access redirects an expired session to its sign-in page; `redirect: 'manual'` makes that opaque.
  if (res.type === 'opaqueredirect') return { kind: 'signed-out', status: null };
  const status = res.status;
  // Access answers an expired sub-request with 401 (approval sheet A-6). A 403
  // is a refusal that signing in again would not fix, so it is not "signed out".
  if (status === 401) return { kind: 'signed-out', status };
  const isJson = (res.headers.get('Content-Type') ?? '').toLowerCase().startsWith('application/json');
  if (status === 200) {
    const envelope = isJson ? parse(body) : null;
    return envelope ? { kind: 'ok', envelope } : { kind: 'error', status, error: null };
  }
  const json = isJson ? parseJson(body) : undefined;
  const error = json === undefined ? null : (parseApiError(json)?.error ?? null);
  // The server's own 503 is its JSON error, or bodyless past both connection
  // caps. A 503 with a page of its own is the network's.
  if (status === 503 && (error || body.trim() === '')) {
    return { kind: 'busy', status, retryAfterMs: retryAfterMs(res.headers.get('Retry-After')), error };
  }
  if (error) return { kind: 'error', status, error };
  // Not the server's JSON: the tunnel's or the network's own error page.
  if (status >= 500) return { kind: 'disconnected', cause: 'gateway', status };
  return { kind: 'error', status, error: null };
}

/** The fleets list has no query; the server uses its configured repository. */
export function fleetsUrl(): string {
  return '/api/v1/fleets';
}

export function readFleetsView(fetchImpl: FetchLike, signal: AbortSignal): Promise<{ kind: 'ok'; envelope: FleetsEnvelope } | Failure | 'stopped'> {
  return readText(fetchImpl, fleetsUrl(), (text) => {
    const parsed = readFleets(text);
    return parsed.ok ? parsed.envelope : null;
  }, signal);
}

/** The cockpit's one read (#536, contracts/cockpit.v1.md): no query; read strictly, so a key written twice or `1.0` is refused. */
export function cockpitUrl(): string {
  return '/api/v1/cockpit';
}

export function readCockpitView(fetchImpl: FetchLike, signal: AbortSignal): Promise<{ kind: 'ok'; envelope: Cockpit } | Failure | 'stopped'> {
  return readText(fetchImpl, cockpitUrl(), (text) => {
    const read = readCockpitText(text);
    return read.ok ? read.cockpit : null;
  }, signal);
}

/** The plan graph page's one read (#653, contracts/plan.v1.md): no query; read strictly, so a key written twice or `1.0` is refused. */
export function planUrl(): string {
  return '/api/v1/plan';
}

export function readPlanView(fetchImpl: FetchLike, signal: AbortSignal): Promise<{ kind: 'ok'; envelope: Plan } | Failure | 'stopped'> {
  return readText(fetchImpl, planUrl(), (text) => {
    const read = readPlanText(text);
    return read.ok ? read.plan : null;
  }, signal);
}

/** The decisions read (#656, contracts/decisions.v1.md): no query; read strictly, so a key written twice or `1.0` is refused. */
export function decisionsUrl(): string {
  return '/api/v1/decisions';
}

export function readDecisionsView(fetchImpl: FetchLike, signal: AbortSignal): Promise<{ kind: 'ok'; envelope: Decisions } | Failure | 'stopped'> {
  return readText(fetchImpl, decisionsUrl(), (text) => {
    const read = readDecisionsText(text);
    return read.ok ? read.decisions : null;
  }, signal);
}

/** A spec is one decimal path segment, never a query or an executable URL. */
export function fleetUrl(spec: number): string {
  return `${fleetsUrl()}/${encodeURIComponent(String(spec))}`;
}

export function readFleetView(fetchImpl: FetchLike, spec: number, signal: AbortSignal): Promise<{ kind: 'ok'; envelope: FleetEnvelope } | Failure | 'stopped'> {
  return readText(fetchImpl, fleetUrl(spec), (text) => {
    const parsed = readFleet(text, spec);
    return parsed.ok ? parsed.envelope : null;
  }, signal);
}

/**
 * Whether the server is known to be done with a read, so that the next read
 * may start without two running on the Mac (V4). It is, when openwiz-server
 * answered (an envelope, or its own error, except a 504: "a run past [the
 * deadline] keeps its slot until the core returns"), or when Access answered
 * at the edge (401, its redirect, a 403), before the request reached the Mac.
 * Not when the network failed or answered with a page of its own: the request
 * may have reached the server, which may still be running it.
 */
export function serverDone(o: Failure | { kind: 'ok' }): boolean {
  switch (o.kind) {
    case 'ok':
    case 'signed-out':
      return true;
    case 'busy':
      // Only the server's own JSON 503, or its bodyless refusal: no run started.
      return true;
    case 'error':
      return o.error !== null ? o.error.kind !== 'deadline' : o.status === 403;
    case 'disconnected':
      return false;
  }
}

function parseJson(body: string): unknown {
  try {
    return JSON.parse(body);
  } catch {
    return undefined;
  }
}

function retryAfterMs(value: string | null): number | null {
  return value !== null && /^[0-9]{1,6}$/.test(value.trim()) ? Number(value.trim()) * 1000 : null;
}

// ── Sending (contracts/web-api.v1.md, "Sending (the one write)") ──
// The one write and its two reads. Each answer is handed back as it came;
// src/composer.ts says what it means (WS-8). Nothing here retries.

export type SendBody = {
  op_id: string;
  mode: 'queue' | 'steer';
  text: string;
  resume_paused_queue: boolean;
  accept_possible_duplicate: boolean;
  /** The ready ids, in the owner's order (#16); absent when there are none, as 0.0.3 sent it. */
  attachments?: string[];
};

/** One answer, as it came: Access's redirect, a response, or none. */
export type Answer =
  | { kind: 'redirect' }
  /** `json` is undefined when the body is not JSON; `empty` when there was no body at all. */
  | { kind: 'response'; status: number; json: unknown; empty: boolean }
  | { kind: 'network' }
  | { kind: 'timeout' }
  | { kind: 'stopped' };

export const SEND_HEADERS: Readonly<Record<string, string>> = {
  ...REQUEST_HEADERS,
  'Content-Type': 'application/json',
  // WS-4's custom header: no cross-site form or simple request carries it.
  'X-OpenWiz-Send': '1',
};

/** The send route. The target is the path's one encoded segment, and only that. */
export function messagesUrl(id: string): string {
  return `${sessionUrl(id)}/messages`;
}

export function previewUrl(id: string, mode: 'queue' | 'steer'): string {
  return `${sessionUrl(id)}/preview?mode=${mode}`;
}

export function lookupUrl(id: string, opId: string): string {
  return `${messagesUrl(id)}/${encodeURIComponent(opId)}`;
}

async function answer(fetchImpl: FetchLike, url: string, init: RequestInit, signal: AbortSignal): Promise<Answer> {
  let res: ResponseLike;
  let body = '';
  try {
    res = await fetchImpl(url, { ...init, credentials: 'same-origin', redirect: 'manual', cache: 'no-store', signal });
    if (res.type === 'opaqueredirect') return { kind: 'redirect' };
    body = await res.text();
  } catch {
    if (signal.aborted) return signal.reason === 'timeout' ? { kind: 'timeout' } : { kind: 'stopped' };
    return { kind: 'network' };
  }
  const json = (res.headers.get('Content-Type') ?? '').toLowerCase().startsWith('application/json') ? parseJson(body) : undefined;
  return { kind: 'response', status: res.status, json, empty: body.trim() === '' };
}

/** The one method name for every POST, kept here so no other module can make one. */
const POST = 'POST';

/** The send: `POST /api/v1/sessions/{id}/messages`. Called once per press; never retried here. */
export function postMessage(fetchImpl: FetchLike, id: string, body: SendBody, signal: AbortSignal): Promise<Answer> {
  return answer(fetchImpl, messagesUrl(id), { method: POST, headers: SEND_HEADERS, body: JSON.stringify(body) }, signal);
}

// ── Creating (contracts/web-api.v1.md, "Creating (the second write)") ──
// The create, its preview, and two reads. The same headers as the send (A-13
// keeps WS-4's checks unchanged). Each answer is handed back as it came;
// src/launcher.ts says what it means. Nothing here retries.

/** A create's body, and the preview's: `attachments` are the ready ids, in the owner's order (#16). */
export type ThreadBody = { op_id: string; harness: string; model: string; effort: string; text: string; attachments: string[] };

export function optionsUrl(): string {
  return '/api/v1/cloud-options';
}

/** The create route. The project is the path's one encoded segment, and only that. */
export function threadsUrl(projectId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/threads`;
}

export function newThreadUrl(opId: string): string {
  return `/api/v1/new-threads/${encodeURIComponent(opId)}`;
}

/** The create: `POST /api/v1/projects/{id}/threads`. Called once per press; never retried here. */
export function postThread(fetchImpl: FetchLike, projectId: string, body: ThreadBody, signal: AbortSignal): Promise<Answer> {
  return answer(fetchImpl, threadsUrl(projectId), { method: POST, headers: SEND_HEADERS, body: JSON.stringify(body) }, signal);
}

/** The new-thread preview: a POST only because it carries the prompt. It reads; it never creates. */
export function postThreadPreview(fetchImpl: FetchLike, projectId: string, body: ThreadBody, signal: AbortSignal): Promise<Answer> {
  return answer(fetchImpl, `${threadsUrl(projectId)}/preview`, { method: POST, headers: SEND_HEADERS, body: JSON.stringify(body) }, signal);
}

/** A read: the preview or the lookup. Never sends. */
export function getAnswer(fetchImpl: FetchLike, url: string, signal: AbortSignal): Promise<Answer> {
  return answer(fetchImpl, url, { method: 'GET', headers: REQUEST_HEADERS }, signal);
}

// ── Loop switches (contracts/web-api.v1.md, `POST /api/v1/loops/{name}/off|on`, #548, #549) ──
// Local loop state only. The send's headers and guards; the body is exactly
// `{}`: the server takes identity, operator and time only from its own
// configuration. Each answer is handed back as it came; src/loops.ts says
// what it means. Nothing here retries.

/** The loops page's one read (#549, `GET /api/v1/loops`): no query; read strictly, so a key written twice or `1.0` is refused. */
export function loopsUrl(): string {
  return '/api/v1/loops';
}

export function readLoopsView(fetchImpl: FetchLike, signal: AbortSignal): Promise<{ kind: 'ok'; envelope: LoopsView } | Failure | 'stopped'> {
  return readText(fetchImpl, loopsUrl(), (text) => {
    const read = readLoopsText(text);
    return read.ok ? read.view : null;
  }, signal);
}

/** A loop's id as loops.v1 shapes it, so it is one path segment with nothing to encode or decode. */
export function isLoopId(id: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(id);
}

/** The switch route. src/loops.ts sends only ids that pass `isLoopId`. */
export function loopSwitchUrl(id: string, on: boolean): string {
  return `/api/v1/loops/${encodeURIComponent(id)}/${on ? 'on' : 'off'}`;
}

/** A switch: `POST /api/v1/loops/{id}/on|off` with `{}`. Called once per press; never retried here. */
export function postLoopSwitch(fetchImpl: FetchLike, id: string, on: boolean, signal: AbortSignal): Promise<Answer> {
  return answer(fetchImpl, loopSwitchUrl(id, on), { method: POST, headers: SEND_HEADERS, body: '{}' }, signal);
}

// ── Attachments (contracts/web-api.v1.md, "Attachments", #16) ──
// The upload, the list and the removal. Each answer is handed back as it came;
// src/attachments.ts says what it means. Nothing here retries, and no route
// returns a file's bytes: a thumbnail is the browser's own copy.

export function attachmentsUrl(): string {
  return '/api/v1/attachments';
}

/** One staged attachment's removal route. The id is the path's one encoded segment. */
export function attachmentUrl(id: string): string {
  return `${attachmentsUrl()}/${encodeURIComponent(id)}`;
}

/** The upload's headers: the send's checks, a raw body (B-9: never multipart), and the name in its own header. */
export const UPLOAD_HEADERS: Readonly<Record<string, string>> = {
  ...REQUEST_HEADERS,
  'Content-Type': 'application/octet-stream',
  'X-OpenWiz-Send': '1',
};

/** The header that carries the file's name, percent-encoded UTF-8. */
export const NAME_HEADER = 'X-OpenWiz-Name';

/** What an upload needs of `XMLHttpRequest`: the one request with progress. */
export interface XhrLike {
  open(method: string, url: string): void;
  setRequestHeader(name: string, value: string): void;
  send(body: Blob): void;
  abort(): void;
  timeout: number;
  readonly status: number;
  readonly responseText: string;
  getResponseHeader(name: string): string | null;
  readonly upload: { onprogress: ((e: ProgressEvent) => unknown) | null };
  onload: ((e: ProgressEvent) => unknown) | null;
  onerror: ((e: ProgressEvent) => unknown) | null;
  ontimeout: ((e: ProgressEvent) => unknown) | null;
  onabort: ((e: ProgressEvent) => unknown) | null;
}

export type XhrFactory = () => XhrLike;

/** The browser's XMLHttpRequest. The only use of it in the app: uploads, for their progress. */
export const browserXhr: XhrFactory = () => new XMLHttpRequest();

/** An upload in flight: its answer, and a way to stop it (the owner's Remove). */
export type Upload = { answer: Promise<Answer>; abort(): void };

/**
 * One upload: `POST /api/v1/attachments`, the file's bytes as they are. Called
 * once per file the owner adds or retries; never retried here. `timeoutMs`
 * beyond the server's deadline: no answer by then is `timeout`.
 */
export function postAttachment(xhr: XhrFactory, file: Blob, name: string, onProgress: (sent: number) => void, timeoutMs: number): Upload {
  const req = xhr();
  let stopped = false;
  const answer = new Promise<Answer>((resolve) => {
    req.open(POST, attachmentsUrl());
    for (const [k, v] of Object.entries(UPLOAD_HEADERS)) req.setRequestHeader(k, v);
    req.setRequestHeader(NAME_HEADER, encodeURIComponent(name));
    req.timeout = timeoutMs;
    req.upload.onprogress = (e) => onProgress(e.loaded);
    req.onload = () => {
      const text = req.responseText;
      const json = (req.getResponseHeader('Content-Type') ?? '').toLowerCase().startsWith('application/json') ? parseJson(text) : undefined;
      // A cross-origin redirect (Access's sign-in page) never loads: it is an error, below.
      resolve({ kind: 'response', status: req.status, json, empty: text.trim() === '' });
    };
    req.onerror = () => resolve(stopped ? { kind: 'stopped' } : { kind: 'network' });
    req.ontimeout = () => resolve({ kind: 'timeout' });
    req.onabort = () => resolve({ kind: 'stopped' });
    req.send(file);
  });
  return {
    answer,
    abort: () => {
      stopped = true;
      req.abort();
    },
  };
}

/** The removal's headers: the send's checks, and no body. */
export const REMOVE_HEADERS: Readonly<Record<string, string>> = { ...REQUEST_HEADERS, 'X-OpenWiz-Send': '1' };

/** One removal: `DELETE /api/v1/attachments/{id}`. Called once per Remove of a ready copy; never retried here. */
export function deleteAttachment(fetchImpl: FetchLike, id: string, signal: AbortSignal): Promise<Answer> {
  return answer(fetchImpl, attachmentUrl(id), { method: 'DELETE', headers: REMOVE_HEADERS }, signal);
}

// Setup is a separate read-only report, never an account or engine action.
export type SetupComponentId = 'cloudroom' | 'harness' | 'personal_github' | 'github_app' | 'project' | 'engine' | 'remote_access';
export type SetupComponent = { id: SetupComponentId; state: 'verified' | 'missing' | 'refused' | 'unknown'; reason: string; next: string };
export type SetupView = {
  schema: 'openwiz.setup.v1'; ready: boolean; components: SetupComponent[];
  engine: 'unselected' | 'cloud' | 'local';
  cost: { provenance: 'unknown' | 'measured' | 'estimated'; credits: number | null; window_s: number | null; monthly_projection: number | null; free_allowance: number | null; reason: string };
  operations: { operation_id: string; kind: 'connect_app' | 'prepare_project' | 'activate_engine' | 'configure_access'; phase: 'proposed' | 'applied' | 'refused' | 'uncertain'; fingerprint: string; effects: string[]; reason: string }[];
};
type SetupJsonObject = { schema?: unknown; ready?: unknown; components?: unknown; engine?: unknown; cost?: unknown; operations?: unknown; id?: unknown; state?: unknown; reason?: unknown; next?: unknown; provenance?: unknown; credits?: unknown; window_s?: unknown; monthly_projection?: unknown; free_allowance?: unknown; operation_id?: unknown; kind?: unknown; phase?: unknown; fingerprint?: unknown; effects?: unknown };
const setupObject = (v: unknown): v is SetupJsonObject => typeof v === 'object' && v !== null && !Array.isArray(v);
const setupText = (v: unknown): v is string => typeof v === 'string' && v.length > 0;
const setupNumber = (v: unknown): v is number | null => v === null || (typeof v === 'number' && Number.isFinite(v) && v >= 0);
function setupKeys(v: object, keys: string[]): boolean {
  const actual = Object.keys(v);
  return actual.length === keys.length && actual.every((key) => keys.includes(key));
}
/** JSON.parse alone loses repeated keys. Inspect decoded keys before using it. */
function setupUniqueKeys(text: string): boolean {
  const stack: (Set<string> | null)[] = [];
  for (let at = 0; at < text.length; at++) {
    const c = text[at];
    if (c === '{') stack.push(new Set());
    else if (c === '[') stack.push(null);
    else if (c === '}' || c === ']') stack.pop();
    else if (c === '"') {
      const start = at;
      for (at++; at < text.length; at++) {
        if (text[at] === '\\') at++;
        else if (text[at] === '"') break;
      }
      let next = at + 1;
      while (next < text.length && /\s/.test(text[next] ?? '')) next++;
      if (text[next] === ':') {
        const key = parseJson(text.slice(start, at + 1));
        const keys = stack.at(-1);
        if (typeof key !== 'string' || !keys || keys.has(key)) return false;
        keys.add(key);
      }
    }
  }
  return true;
}
function parseSetupText(text: string): SetupView | null {
  if (!setupUniqueKeys(text)) return null;
  const v = parseJson(text);
  if (!setupObject(v) || !setupKeys(v, ['schema', 'ready', 'components', 'engine', 'cost', 'operations']) || v.schema !== 'openwiz.setup.v1' || typeof v.ready !== 'boolean' || !Array.isArray(v.components) || v.components.length !== 7 || !Array.isArray(v.operations)) return null;
  if (v.engine !== 'unselected' && v.engine !== 'cloud' && v.engine !== 'local') return null;
  const components: SetupComponent[] = [];
  const seen = new Set<string>();
  for (const item of v.components) {
    if (!setupObject(item) || !setupKeys(item, ['id', 'state', 'reason', 'next']) || !setupText(item.reason) || !setupText(item.next)) return null;
    const id = item.id;
    if (id !== 'cloudroom' && id !== 'harness' && id !== 'personal_github' && id !== 'github_app' && id !== 'project' && id !== 'engine' && id !== 'remote_access') return null;
    if (seen.has(id)) return null;
    seen.add(id);
    const state = item.state;
    if (state !== 'verified' && state !== 'missing' && state !== 'refused' && state !== 'unknown') return null;
    components.push({ id, state, reason: item.reason, next: item.next });
  }
  if (v.ready && (v.engine === 'unselected' || components.some((component) => component.id !== 'remote_access' && component.state !== 'verified'))) return null;
  const c = v.cost;
  if (!setupObject(c) || !setupKeys(c, ['provenance', 'credits', 'window_s', 'monthly_projection', 'free_allowance', 'reason']) || !setupText(c.reason) || !setupNumber(c.credits) || !setupNumber(c.window_s) || !setupNumber(c.monthly_projection) || !setupNumber(c.free_allowance)) return null;
  if (c.provenance !== 'unknown' && c.provenance !== 'measured' && c.provenance !== 'estimated') return null;
  if (c.provenance === 'unknown' && (c.credits !== null || c.window_s !== null || c.monthly_projection !== null || c.free_allowance !== null)) return null;
  if (c.window_s !== null && c.window_s === 0) return null;
  if (c.provenance === 'measured' && (c.window_s === null || c.window_s === 0)) return null;
  const operations: SetupView['operations'] = [];
  for (const op of v.operations) {
    if (!setupObject(op) || !setupKeys(op, ['operation_id', 'kind', 'phase', 'fingerprint', 'effects', 'reason']) || typeof op.operation_id !== 'string' || !/^[0-9a-f]{32}$/.test(op.operation_id) || typeof op.fingerprint !== 'string' || !/^[0-9a-f]{64}$/.test(op.fingerprint) || !setupText(op.reason) || !Array.isArray(op.effects)) return null;
    if (op.kind !== 'connect_app' && op.kind !== 'prepare_project' && op.kind !== 'activate_engine' && op.kind !== 'configure_access') return null;
    if (op.phase !== 'proposed' && op.phase !== 'applied' && op.phase !== 'refused' && op.phase !== 'uncertain') return null;
    const effects: string[] = [];
    for (const effect of op.effects) { if (!setupText(effect)) return null; effects.push(effect); }
    if (effects.length === 0) return null;
    operations.push({ operation_id: op.operation_id, kind: op.kind, phase: op.phase, fingerprint: op.fingerprint, effects, reason: op.reason });
  }
  return { schema: v.schema, ready: v.ready, components, engine: v.engine, cost: { provenance: c.provenance, credits: c.credits, window_s: c.window_s, monthly_projection: c.monthly_projection, free_allowance: c.free_allowance, reason: c.reason }, operations };
}
export function readSetup(fetchImpl: FetchLike, signal: AbortSignal): Promise<{ kind: 'ok'; envelope: SetupView } | Failure | 'stopped'> {
  return readText(fetchImpl, '/api/v1/setup', parseSetupText, signal);
}

/** Exact bound-item read only; receiving a notification is never an answer. */
export async function readNotificationTarget(fetchImpl: FetchLike, token: string, signal: AbortSignal): Promise<{ kind: 'ok'; envelope: TargetResult } | Failure | 'stopped'> {
  const url = targetUrl(token);
  return url === null ? { kind: 'error', status: 400, error: null } : readText(fetchImpl, url, readTargetText, signal);
}

// Notification preference/status calls (#2230); #2035 supplies the real UI
// integration. These functions never request permission or register subscriptions.
export function readNotificationStatus(fetchImpl: FetchLike, signal: AbortSignal): Promise<{ kind: 'ok'; envelope: NotificationStatus } | Failure | 'stopped'> {
  return readText(fetchImpl, '/api/v1/notifications/status', parseNotificationStatus, signal);
}
export function readNotificationPreferences(fetchImpl: FetchLike, signal: AbortSignal): Promise<{ kind: 'ok'; envelope: NotificationPreferences } | Failure | 'stopped'> {
  return readText(fetchImpl, '/api/v1/notifications/preferences', parseNotificationPreferences, signal);
}
/** One explicit owner's operation; the caller retains its id/body. No retry. */
export async function writeNotificationPreferences(fetchImpl: FetchLike, write: NotificationPreferenceWrite, signal: AbortSignal): Promise<{ kind: 'ok'; envelope: NotificationPreferences } | Failure> {
  let res: ResponseLike;
  let body = '';
  try {
    res = await fetchImpl('/api/v1/notifications/preferences', { method: 'PUT', headers: SEND_HEADERS, credentials: 'same-origin', redirect: 'manual', cache: 'no-store', signal,
      body: JSON.stringify({ schema: 'openwiz.notifications.v1', record: { preference_write: write } }) });
    if (res.type !== 'opaqueredirect') body = await res.text();
  } catch {
    return { kind: 'disconnected', cause: signal.aborted ? 'timeout' : 'network', status: null };
  }
  return classify(res, body, parseNotificationPreferences);
}
