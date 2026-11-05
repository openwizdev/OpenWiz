// The `openwiz.inventory.v1` envelope, as `contracts/inventory.v1.schema.json`
// defines it. One type per schema definition, named after it in PascalCase,
// with exactly the schema's property names: `npm run check` compares them.
// The web reads nothing else.

export const SCHEMA_ID = 'openwiz.inventory.v1';

export type Unknown = { unknown: string };
export type Fact<T> = { known: T } | Unknown;
export type FactString = Fact<string>;
export type FactBoolean = Fact<boolean>;
export type FactInteger = Fact<number>;

export type Source = {
  name: string;
  version: FactString;
  tested_version: string;
  version_tested: boolean;
};

export type Counts = {
  listed: number;
  unreadable: number;
  excluded_hidden: number;
  excluded_archived: number;
  hidden_read: boolean;
  archived_read: boolean;
  matched: number;
  offset: number;
  limit: number;
  shown: number;
};

export type Coverage = {
  state: 'complete' | 'partial';
  counts: Counts | null;
};

export type Freshness = { snapshot_at: number };

export const GAP_KINDS = [
  'untested_version',
  'command_failed',
  'timed_out',
  'budget_exhausted',
  'malformed',
  'missing_field',
  'wrong_type',
  'not_found',
] as const;

export type Gap = {
  kind: (typeof GAP_KINDS)[number];
  subject: string | null;
  detail: string;
};

export type Location = { kind: 'cloud' } | { kind: 'local'; machine: FactString };

export type Grouping =
  | { kind: 'project'; id: string; name: FactString }
  | { kind: 'ungrouped'; reason: string };

export type BoundedText = { text: string; truncated: boolean };

export type Recap = { kind: 'purpose_as_reported'; text: string; truncated: boolean } | { kind: 'no_recap_yet' };

export type FinalOutput = { kind: 'reported'; text: string; truncated: boolean } | { kind: 'no_final_output_yet' };

export type ReportedConfiguration = { model: FactString; effort: FactString };

export type Session = {
  id: string;
  title: FactString;
  provider: FactString;
  status: FactString;
  location: Fact<Location>;
  group: Grouping;
  parent: Fact<string | null>;
  hidden: FactBoolean;
  archived: FactBoolean;
  recap: Fact<Recap>;
  reported_configuration: ReportedConfiguration;
  updated_at: FactInteger;
  age_ms: FactInteger;
  /** #539: when the session started, only as room-cli reports it; optional. */
  started_at?: FactInteger;
};

export type Inventory = { sessions: Session[] };

export type SessionView = {
  session: Session;
  final_output: Fact<FinalOutput>;
  reported_error: Fact<BoundedText | null>;
};

export type Envelope<D = Inventory | SessionView> = {
  schema: typeof SCHEMA_ID;
  source: Source;
  coverage: Coverage;
  freshness: Freshness;
  gaps: Gap[];
  data: D;
};

/** The web API's error body (`contracts/web-api.v1.md`, "Error body"). */
export type ApiError = { error: { kind: string; message: string } };

// Runtime checks, exact to the schema: every required key, no other key, the
// right types and enums. A response that fails is not shown as data. The
// helpers are shared with src/messaging.ts.

export type Check = (v: unknown) => boolean;

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

export const exact =
  (shape: Record<string, Check>): Check =>
  (v) =>
    isObject(v) &&
    Object.keys(v).length === Object.keys(shape).length &&
    Object.entries(shape).every(([key, check]) => Object.hasOwn(v, key) && check(v[key]));

/**
 * `exact`, plus keys that may be absent (#16: the reports' optional
 * `attachments`, absent when there are none): every key is one of these, each
 * required one is there, and every one there passes its check.
 */
export const exactWith =
  (shape: Record<string, Check>, optional: Record<string, Check>): Check =>
  (v) =>
    isObject(v) &&
    Object.keys(v).every((key) => Object.hasOwn(shape, key) || Object.hasOwn(optional, key)) &&
    Object.entries(shape).every(([key, check]) => Object.hasOwn(v, key) && check(v[key])) &&
    Object.entries(optional).every(([key, check]) => !Object.hasOwn(v, key) || check(v[key]));

/** JSON Schema's oneOf: exactly one matches. */
export const oneOf =
  (...checks: Check[]): Check =>
  (v) =>
    checks.filter((check) => check(v)).length === 1;

export const str: Check = (v) => typeof v === 'string';
export const bool: Check = (v) => typeof v === 'boolean';
export const int: Check = (v) => typeof v === 'number' && Number.isSafeInteger(v);
export const count: Check = (v) => int(v) && (v as number) >= 0;
export const isNull: Check = (v) => v === null;
export const is =
  (...values: readonly unknown[]): Check =>
  (v) =>
    values.includes(v);
export const list =
  (check: Check): Check =>
  (v) =>
    Array.isArray(v) && v.every(check);

// Only private, fixed schema literals use cached metadata. Exported shape
// helpers above keep observing mutations to their callers' maps.
const fixedExact = (shape: Record<string, Check>): Check => {
  const entries = Object.entries(shape);
  return (v) =>
    isObject(v) &&
    Object.keys(v).length === entries.length &&
    entries.every(([key, check]) => Object.hasOwn(v, key) && check(v[key]));
};

const fixedWith = (shape: Record<string, Check>, optional: Record<string, Check>): Check => {
  const required = Object.entries(shape);
  const extra = Object.entries(optional);
  return (v) =>
    isObject(v) &&
    Object.keys(v).every((key) => Object.hasOwn(shape, key) || Object.hasOwn(optional, key)) &&
    required.every(([key, check]) => Object.hasOwn(v, key) && check(v[key])) &&
    extra.every(([key, check]) => !Object.hasOwn(v, key) || check(v[key]));
};

const unknownCheck = fixedExact({ unknown: (v) => str(v) && (v as string).length >= 1 });
export const fact = (check: Check): Check => oneOf(fixedExact({ known: check }), unknownCheck);

const sourceCheck = fixedExact({ name: str, version: fact(str), tested_version: str, version_tested: bool });
const countsCheck = fixedExact({
  listed: count,
  unreadable: count,
  excluded_hidden: count,
  excluded_archived: count,
  hidden_read: bool,
  archived_read: bool,
  matched: count,
  offset: count,
  limit: count,
  shown: count,
});
const coverageCheck = fixedExact({ state: is('complete', 'partial'), counts: oneOf(isNull, countsCheck) });
const freshnessCheck = fixedExact({ snapshot_at: int });
const gapCheck = fixedExact({ kind: is(...GAP_KINDS), subject: oneOf(isNull, str), detail: str });
const locationCheck = oneOf(fixedExact({ kind: is('cloud') }), fixedExact({ kind: is('local'), machine: fact(str) }));
const groupingCheck = oneOf(
  fixedExact({ kind: is('project'), id: str, name: fact(str) }),
  fixedExact({ kind: is('ungrouped'), reason: str }),
);
const recapCheck = oneOf(
  fixedExact({ kind: is('purpose_as_reported'), text: (v) => str(v) && [...(v as string)].length <= 120, truncated: bool }),
  fixedExact({ kind: is('no_recap_yet') }),
);
const finalOutputCheck = oneOf(fixedExact({ kind: is('reported'), text: str, truncated: bool }), fixedExact({ kind: is('no_final_output_yet') }));
const boundedTextCheck = fixedExact({ text: str, truncated: bool });
const sessionCheck = fixedWith({
  id: str,
  title: fact(str),
  provider: fact(str),
  status: fact(str),
  location: fact(locationCheck),
  group: groupingCheck,
  parent: fact(oneOf(isNull, str)),
  hidden: fact(bool),
  archived: fact(bool),
  recap: fact(recapCheck),
  reported_configuration: fixedExact({ model: fact(str), effort: fact(str) }),
  updated_at: fact(int),
  age_ms: fact(int),
}, { started_at: fact(int) });
const envelopeCheck = (data: Check): Check =>
  fixedExact({ schema: is(SCHEMA_ID), source: sourceCheck, coverage: coverageCheck, freshness: freshnessCheck, gaps: list(gapCheck), data });

const inventoryEnvelope = envelopeCheck(fixedExact({ sessions: list(sessionCheck) }));
const sessionViewEnvelope = envelopeCheck(
  fixedExact({ session: sessionCheck, final_output: fact(finalOutputCheck), reported_error: fact(oneOf(isNull, boundedTextCheck)) }),
);
const apiErrorCheck = fixedExact({ error: fixedExact({ kind: str, message: str }) });

/** An inventory envelope, or null when `json` is not exactly one. */
export function parseInventory(json: unknown): Envelope<Inventory> | null {
  return inventoryEnvelope(json) ? (json as Envelope<Inventory>) : null;
}

/** A session envelope (`show`), or null when `json` is not exactly one. */
export function parseSessionView(json: unknown): Envelope<SessionView> | null {
  return sessionViewEnvelope(json) ? (json as Envelope<SessionView>) : null;
}

/** The API's error body, or null when `json` is not exactly one. */
export function parseApiError(json: unknown): ApiError | null {
  return apiErrorCheck(json) ? (json as ApiError) : null;
}
