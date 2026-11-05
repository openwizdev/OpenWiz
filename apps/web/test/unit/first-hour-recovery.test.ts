// #2222 (P12 of #2194, PR4 at the contract seam): the first hour's fault cases.
//
// Each case drives the page's existing state owners (the composer, the
// launcher, a decision slot's composer storage and receipt) or the existing
// owner-state tools (setup's access check, the installer) through the
// recording and fault providers in tools/install/tests/first-hour/providers/,
// then compares the owner's work before and after: drafts by their exact
// bytes, the pending intents' ids and request fingerprints, and the
// provider's own effect and call counts. Every comparison is a first-hour
// `recovery` document (contracts/first-hour.v1.md, "Recovery cases"); #2200's
// checks give its codes, and each case's expected codes are written here by
// hand from the contract. A recording is never a pass: `not_live` and
// `candidate_unknown` stay in every one.
//
// Scope (J13, 2026-11-13): drafts are kept within the same tab (reload) and
// across a server restart through the tab's sessionStorage. After a browser
// restart they are reported as `retention_unproven`, never as retained; the
// owner's records are read back from owner state. Synthetic values only.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { Composers, keyOf } from '../../src/composer.ts';
import type { Press, ThreadState } from '../../src/composer.ts';
import { readDecisions, readReceipt, slotsOf, slotStorage, answerText, bindingOf, writeReceipt } from '../../src/decisions.ts';
import { Launchers } from '../../src/launcher.ts';
import type { LaunchState } from '../../src/launcher.ts';
import * as nt from '../support/newthread-synthetic.ts';
import { FakeClock, settle as flush } from './support.ts';
import type { FetchLike } from '../../src/api.ts';
import type { Options } from '../../src/newthread.ts';

// The providers live in tools/install/tests/first-hour/providers/ (#2222's owned path), which CI's
// web-build job prunes before `next build` type-checks this file (classify.sh gives tools/install/ to
// the rust and web-test jobs only; the web-test lanes that run this test keep it). So they are loaded
// at run time, not resolved by tsc, and typed here by the part of their interface this test uses.
type Basis = 'owner_state_read_back' | 'repository_read_back' | 'provider_read_back' | 'tab_session_storage';
type Phase = 'proposed' | 'applied' | 'refused' | 'uncertain';
type Interruption = 'revoked_access' | 'refused_access' | 'builder_unavailable' | 'reviewer_unavailable' | 'setup_interrupted' | 'lost_reply' | 'browser_restart' | 'process_restart' | 'update_rejected' | 'removal_default' | 'repeat_approval';
type Work = { kind: 'draft' | 'setup_state' | 'branch' | 'commit' | 'pending_operation'; id: string; content: string; basis: Basis };
type Transition = { operation_id: string; kind: 'send' | 'new_thread'; phase_before: Phase; phase_after: Phase; effect_count: number; attempts: number; reconciliation: 'none' | 'provider_read_back' };
type Explanation = { what_happened: string; took_effect: 'yes' | 'no' | 'unknown'; next_action: string };
type Codes = { problems: string[]; failures: string[]; unproven: string[] };
type Doc = { case: { interruption: Interruption } };
type Rec = { opId: string; intent: string; kind: 'send' | 'new_thread'; fingerprint: string; textSha256: string };
type Logged = { method: string; url: string; body: unknown };
type Fault = 'signed_out' | 'refused' | 'lose_reply' | 'stop_after_effect';
interface Provider {
  readonly fetch: FetchLike;
  readonly records: Map<string, Rec>;
  readonly calls: Map<string, number>;
  readonly effects: Map<string, number>;
  readonly reads: Map<string, number>;
  readonly log: Logged[];
  options: Options;
  readonly stopped: boolean;
  fault(f: Fault): void;
  restart(): void;
  readBack(intent: string): Rec[];
}
interface Tab {
  getItem(k: string): string | null;
  setItem(k: string, v: string): void;
  removeItem(k: string): void;
  key(i: number): string | null;
  readonly length: number;
  restored(): Tab;
}
type DocumentModule = {
  sha256(text: string): string;
  draft(id: string, text: string, basis: Basis): Work;
  delivered(id: string, textSha256: string): Work;
  pending(intent: string, fingerprint: string, basis: Basis): Work;
  observed(p: Provider, intent: string, kind: Transition['kind'], before: Phase, after: Phase): Transition;
  recovery(i: Interruption, before: Work[], after: Work[], ops: Transition[], e: Explanation, verdict?: 'unverified' | 'fail'): Doc;
  codes(documents: readonly unknown[]): Codes[];
  ownerCases(): { name: string; document: unknown; codes: Codes; observed: Record<string, unknown> }[];
};
type RecordingModule = {
  RecordingProvider: new () => Provider;
  TabStorage: new () => Tab;
  fingerprint(kind: 'send' | 'new_thread', request: Record<string, string>): string;
  sendRequest(target: string, text: string): Record<string, string>;
  createRequest(project: string, b: { harness: string; model: string; effort: string; text: string }): Record<string, string>;
};
const PROVIDERS = new URL('../../../../tools/install/tests/first-hour/providers/', import.meta.url);
const { codes, delivered, draft, observed, ownerCases, pending, recovery, sha256 } = (await import(new URL('document.ts', PROVIDERS).href)) as DocumentModule;
const { createRequest, fingerprint, RecordingProvider, sendRequest, TabStorage } = (await import(new URL('recording.ts', PROVIDERS).href)) as RecordingModule;
type RecordingProvider = Provider;
type TabStorage = Tab;

const THREAD = 'thr_web_0001';
const PROJECT = 'prj_web_0001';
const TEXT = 'Synthetic first-hour message: keep these exact bytes ✓';
const PROMPT = 'Synthetic first-hour prompt: build the small idea';
const QUEUE: Press = { mode: 'queue', resumePausedQueue: false, acceptPossibleDuplicate: false };
const BUILDER = { harness: 'codex', model: 'syn-codex-model-01', effort: 'high' };
const REVIEWER = { harness: 'claude-code', model: 'syn-claude-model-01', effort: 'high' };
/** Every recording's own unproven codes: not live, and no installed candidate. */
const RECORDING = ['candidate_unknown', 'not_live'];
const CLEAN = (extra: string[] = []): Codes => ({ problems: [], failures: [], unproven: [...RECORDING, ...extra].sort() });

let roots = 0;
const mint = () => `web-${(0xf1000 + ++roots).toString(16).padStart(32, '0')}`;
const intent = (root: string | null) => {
  assert.ok(root, 'the draft has its root id');
  return root.slice(4);
};
const COMPOSER_KEY = `composer:${THREAD}`;
const LAUNCHER_KEY = `launcher:${PROJECT}`;

function page(p: RecordingProvider, storage: TabStorage) {
  const deps = { fetch: p.fetch, storage, timers: new FakeClock(), newOpId: mint };
  return { composers: new Composers(deps), launchers: new Launchers(deps) };
}

/** The phase the composer shows for its newest attempt, in the contract's words. */
function sendPhase(s: ThreadState): Phase {
  const a = s.attempts[s.attempts.length - 1];
  if (!a) return 'proposed';
  if (a.state === 'done') return a.result === 'queued' || a.result === 'sent' ? 'applied' : 'refused';
  return a.state === 'refused' ? 'refused' : 'uncertain';
}

/** The phase the launcher shows for its current attempt. */
function createPhase(s: LaunchState): Phase {
  if (s.created) return 'applied';
  if (s.pending) return 'uncertain';
  return s.said ? 'refused' : 'proposed';
}

/** The composer's work as the tab holds it, or, once sent, as the provider's exact record holds it. */
function sendWork(s: ThreadState, p: RecordingProvider, id: string, basis: Work['basis'] = 'tab_session_storage'): Work[] {
  if (s.root !== null) return [draft(COMPOSER_KEY, s.draft, basis), pending(intent(s.root), fingerprint('send', sendRequest(id, s.draft)), basis)];
  const rec = [...p.records.values()].find((r) => r.kind === 'send');
  return rec ? [delivered(COMPOSER_KEY, rec.textSha256), pending(rec.intent, rec.fingerprint, 'provider_read_back')] : [];
}

/** The launcher's work as the tab holds it, or, once created, as the provider's exact record holds it. */
function createWork(s: LaunchState, p: RecordingProvider): Work[] {
  if (s.root !== null) {
    const work = [draft(LAUNCHER_KEY, s.draft, 'tab_session_storage')];
    return s.pending || s.said ? [...work, pending(intent(s.root), fingerprint('new_thread', createRequest(PROJECT, { ...s.choice, text: s.draft })), 'tab_session_storage')] : work;
  }
  const rec = [...p.records.values()].find((r) => r.kind === 'new_thread');
  return rec ? [delivered(LAUNCHER_KEY, rec.textSha256), pending(rec.intent, rec.fingerprint, 'provider_read_back')] : [];
}

function writeLauncher(l: Launchers, settings: typeof BUILDER, options = nt.options()): void {
  l.edit(PROJECT, PROMPT);
  for (const f of ['harness', 'model', 'effort'] as const) l.choose(PROJECT, f, settings[f], options);
}

const posts = (p: RecordingProvider) => p.log.filter((e) => e.method === 'POST').map((e) => (e.body as { op_id: string }).op_id);

type Case = { name: string; interruption: Interruption; run: () => Promise<{ document: Doc; expect: Codes }> };

const CASES: Case[] = [
  {
    name: 'revoked access: Access signs the owner out; nothing is sent, the draft and its id stay, and reconnecting sends it once',
    interruption: 'revoked_access',
    run: async () => {
      const p = new RecordingProvider();
      const storage = new TabStorage();
      const { composers } = page(p, storage);
      composers.edit(THREAD, TEXT);
      const before = sendWork(composers.get(THREAD), p, THREAD);
      p.fault('signed_out');
      await composers.press(THREAD, QUEUE);
      const refused = composers.get(THREAD);
      assert.equal(refused.attempts[0]?.result, 'signed-out', 'the owner is told they are signed out');
      assert.equal(p.calls.size, 0, 'nothing reached the provider');
      const phaseBefore = sendPhase(refused);
      // Signed in again, in the same tab after a reload: the same draft, root and unused attempt number.
      const again = page(p, storage).composers;
      assert.equal(again.get(THREAD).draft, TEXT);
      await again.press(THREAD, QUEUE);
      const root = refused.root!;
      assert.deepEqual(posts(p), [`${root}-q1`, `${root}-q1`], 'the refused number was unused, so the same op id is sent');
      const ops = [observed(p, intent(root), 'send', phaseBefore, sendPhase(again.get(THREAD)))];
      return {
        document: recovery('revoked_access', before, sendWork(again.get(THREAD), p, THREAD), ops, {
          what_happened: 'Access signed the owner out before OpenWiz; nothing was sent. The draft and its id stayed; after signing in, the same message id was sent once.',
          took_effect: 'yes',
          next_action: 'Nothing to repeat: the message was sent once.',
        }),
        expect: CLEAN(),
      };
    },
  },
  {
    name: 'refused access: OpenWiz refuses a create before the core; the prompt, settings and id stay, and the next create is the same op id, once',
    interruption: 'refused_access',
    run: async () => {
      const p = new RecordingProvider();
      const storage = new TabStorage();
      const { launchers } = page(p, storage);
      writeLauncher(launchers, BUILDER);
      const root = launchers.get(PROJECT).root!;
      p.fault('refused');
      await launchers.create(PROJECT);
      const refused = launchers.get(PROJECT);
      assert.equal(refused.said?.kind, 'not-created', 'the owner is told nothing was created');
      assert.equal(refused.pending, null);
      const before = [draft(LAUNCHER_KEY, PROMPT, 'tab_session_storage'), pending(intent(root), fingerprint('new_thread', createRequest(PROJECT, { ...BUILDER, text: PROMPT })), 'tab_session_storage')];
      assert.deepEqual(createWork(refused, p), before, 'the refusal kept the prompt, settings and id');
      const again = page(p, storage).launchers;
      assert.deepEqual(again.get(PROJECT).choice, BUILDER);
      await again.create(PROJECT);
      assert.deepEqual(posts(p), [`${root}-c1`, `${root}-c1`]);
      const ops = [observed(p, intent(root), 'new_thread', createPhase(refused), createPhase(again.get(PROJECT)))];
      return {
        document: recovery('refused_access', before, createWork(again.get(PROJECT), p), ops, {
          what_happened: 'OpenWiz refused the create before the core: nothing was created and the prompt, settings and id stayed. The next create used the same op id and created one thread.',
          took_effect: 'yes',
          next_action: 'Nothing to repeat: one thread was created.',
        }),
        expect: CLEAN(),
      };
    },
  },
  {
    name: 'builder unavailable: the builder harness is no longer offered; its setting is emptied with why, nothing starts, and the prompt stays',
    interruption: 'builder_unavailable',
    run: async () => {
      const p = new RecordingProvider();
      const { launchers } = page(p, new TabStorage());
      writeLauncher(launchers, BUILDER);
      const before = createWork(launchers.get(PROJECT), p);
      // The builder's account is no longer usable: CloudRoom stops offering its harness.
      p.options = nt.options(undefined, { harnesses: nt.options().harnesses.filter((h) => h.harness !== 'codex') });
      const read = await launchers.options(new AbortController().signal);
      assert.equal(read?.kind, 'ok');
      launchers.reconcile(PROJECT, read?.kind === 'ok' ? read.options : null);
      const s = launchers.get(PROJECT);
      assert.match(s.note ?? '', /codex isn’t offered now: choose a harness/);
      await launchers.create(PROJECT);
      assert.deepEqual(posts(p), [], 'nothing starts without an offered builder');
      return {
        document: recovery('builder_unavailable', before, createWork(launchers.get(PROJECT), p), [], {
          what_happened: 'The builder harness is no longer offered, so its setting was emptied and the reason shown; nothing was started.',
          took_effect: 'no',
          next_action: 'Sign in to the builder harness again, or choose an offered one, then start.',
        }),
        expect: CLEAN(),
      };
    },
  },
  {
    name: 'reviewer unavailable: only the builder’s family is offered; the reviewer seat cannot be chosen, nothing starts, and the prompt stays',
    interruption: 'reviewer_unavailable',
    run: async () => {
      const p = new RecordingProvider();
      const { launchers } = page(p, new TabStorage());
      // The reviewer's account can't be confirmed: CloudRoom lists its harness as unavailable, and offers only the builder's family.
      p.options = nt.options(undefined, {
        harnesses: nt.options().harnesses.filter((h) => h.harness === 'codex'),
        unavailable: [{ harness: 'claude-code', reason: 'catalogue_not_reported', text: 'unavailable (catalogue not reported)' }],
      });
      const read = await launchers.options(new AbortController().signal);
      const offered = read?.kind === 'ok' ? read.options : null;
      assert.deepEqual(offered?.unavailable.map((u) => u.harness), ['claude-code'], 'the missing reviewer is shown before anything starts');
      launchers.edit(PROJECT, PROMPT);
      launchers.choose(PROJECT, 'harness', REVIEWER.harness, offered);
      const s = launchers.get(PROJECT);
      assert.deepEqual(s.choice, { harness: '', model: '', effort: '' }, 'no reviewer setting is substituted');
      assert.match(s.note ?? '', /claude-code isn’t offered now: choose a harness/);
      const before = createWork(s, p);
      await launchers.create(PROJECT);
      assert.deepEqual(posts(p), [], 'nothing starts without an offered reviewer');
      return {
        document: recovery('reviewer_unavailable', before, createWork(launchers.get(PROJECT), p), [], {
          what_happened: 'The reviewer’s harness is not offered, so no reviewer setting could be chosen; nothing was started.',
          took_effect: 'no',
          next_action: 'Sign in to the other harness family for the reviewer, then start.',
        }),
        expect: CLEAN(),
      };
    },
  },
  {
    name: 'lost reply, then a same-tab reload: the send stays uncertain until its own record is read, and is never sent twice',
    interruption: 'lost_reply',
    run: async () => {
      const p = new RecordingProvider();
      const storage = new TabStorage();
      const { composers } = page(p, storage);
      composers.edit(THREAD, TEXT);
      const before = sendWork(composers.get(THREAD), p, THREAD);
      p.fault('lose_reply');
      await composers.press(THREAD, QUEUE);
      const lost = composers.get(THREAD);
      assert.equal(lost.attempts[0]?.state, 'unknown', 'no answer: it may have been sent');
      // The tab reloads: the draft, its id and the unresolved attempt come back as they were.
      const reloaded = page(p, storage).composers;
      const back = reloaded.get(THREAD);
      assert.deepEqual([back.draft, back.root, back.attempts.map((a) => a.state)], [TEXT, lost.root, ['unknown']]);
      assert.deepEqual(sendWork(back, p, THREAD), before, 'same-tab reload keeps the exact draft and pending id');
      const phaseBefore = sendPhase(back);
      await reloaded.check(THREAD, keyOf(back.attempts[0]!));
      assert.equal(reloaded.get(THREAD).attempts[0]?.result, 'sent', 'its own record settled it');
      assert.equal(posts(p).length, 1, 'no second send');
      const ops = [observed(p, intent(lost.root), 'send', phaseBefore, sendPhase(reloaded.get(THREAD)))];
      return {
        document: recovery('lost_reply', before, sendWork(reloaded.get(THREAD), p, THREAD), ops, {
          what_happened: 'The send’s reply was lost; after a reload the message stayed uncertain until its own record was read, which showed it was sent once.',
          took_effect: 'yes',
          next_action: 'Nothing to repeat: the message was sent once.',
        }),
        expect: CLEAN(),
      };
    },
  },
  {
    name: 'lost reply on a create, then a same-tab reload: Refresh status reads its record; no second create',
    interruption: 'lost_reply',
    run: async () => {
      const p = new RecordingProvider();
      const storage = new TabStorage();
      const { launchers } = page(p, storage);
      writeLauncher(launchers, BUILDER);
      p.fault('lose_reply');
      await launchers.create(PROJECT);
      const lost = launchers.get(PROJECT);
      assert.equal(lost.pending?.state, 'unknown');
      const before = createWork(lost, p);
      const reloaded = page(p, storage).launchers;
      assert.deepEqual(createWork(reloaded.get(PROJECT), p), before, 'same-tab reload keeps the prompt, settings and pending id');
      const phaseBefore = createPhase(reloaded.get(PROJECT));
      await reloaded.check(PROJECT);
      assert.ok(reloaded.get(PROJECT).created, 'its own record shows the thread');
      assert.equal(posts(p).length, 1, 'no second create');
      const ops = [observed(p, intent(lost.root), 'new_thread', phaseBefore, createPhase(reloaded.get(PROJECT)))];
      return {
        document: recovery('lost_reply', before, createWork(reloaded.get(PROJECT), p), ops, {
          what_happened: 'The create’s reply was lost; after a reload Refresh status read its own record, which showed one thread created.',
          took_effect: 'yes',
          next_action: 'Nothing to repeat: open the created thread.',
        }),
        expect: CLEAN(),
      };
    },
  },
  {
    name: 'server restart: records in owner state and the open tab’s drafts stay; each pending intent is reconciled by its op id before anything else',
    interruption: 'process_restart',
    run: async () => {
      const p = new RecordingProvider();
      const storage = new TabStorage();
      const { composers, launchers } = page(p, storage);
      composers.edit(THREAD, TEXT);
      writeLauncher(launchers, BUILDER);
      const sendRoot = composers.get(THREAD).root!;
      const createRoot = launchers.get(PROJECT).root!;
      // The server stops just after the send's effect; a create pressed while it is down never arrives.
      p.fault('stop_after_effect');
      await composers.press(THREAD, QUEUE);
      await launchers.create(PROJECT);
      assert.ok(p.stopped);
      const before = [...sendWork(composers.get(THREAD), p, THREAD), ...createWork(launchers.get(PROJECT), p)];
      const phases = [sendPhase(composers.get(THREAD)), createPhase(launchers.get(PROJECT))];
      assert.deepEqual(phases, ['uncertain', 'uncertain']);
      // A check while it is down settles nothing and sends nothing.
      await composers.check(THREAD, keyOf(composers.get(THREAD).attempts[0]!));
      assert.equal(composers.get(THREAD).attempts[0]?.state, 'unknown');
      p.restart();
      await composers.check(THREAD, keyOf(composers.get(THREAD).attempts[0]!));
      await launchers.check(PROJECT);
      assert.match(launchers.get(PROJECT).checked ?? '', /no record of this create yet/);
      assert.deepEqual(posts(p), [`${sendRoot}-q1`, `${createRoot}-c1`], 'reconciling made no write');
      // With no record of it, Try again repeats the same op id: the core creates once.
      await launchers.create(PROJECT);
      assert.deepEqual(posts(p), [`${sendRoot}-q1`, `${createRoot}-c1`, `${createRoot}-c1`]);
      const ops: Transition[] = [
        observed(p, intent(sendRoot), 'send', phases[0]!, sendPhase(composers.get(THREAD))),
        observed(p, intent(createRoot), 'new_thread', phases[1]!, createPhase(launchers.get(PROJECT))),
      ];
      return {
        document: recovery('process_restart', before, [...sendWork(composers.get(THREAD), p, THREAD), ...createWork(launchers.get(PROJECT), p)], ops, {
          what_happened: 'The server stopped after the send took effect and before the create arrived. After it restarted, the send’s record showed it sent once; the create had no record, so the same op id was tried again and created one thread.',
          took_effect: 'yes',
          next_action: 'Nothing to repeat: one message was sent and one thread created.',
        }),
        expect: CLEAN(),
      };
    },
  },
  {
    name: 'browser restart: the owner’s records are read back and reconciled first; tab-only drafts are reported as retention_unproven, not retained',
    interruption: 'browser_restart',
    run: async () => {
      const p = new RecordingProvider();
      const storage = new TabStorage();
      const { composers, launchers } = page(p, storage);
      composers.edit(THREAD, TEXT);
      writeLauncher(launchers, BUILDER);
      p.fault('lose_reply');
      await composers.press(THREAD, QUEUE);
      const sendRoot = composers.get(THREAD).root!;
      const before = [...sendWork(composers.get(THREAD), p, THREAD), ...createWork(launchers.get(PROJECT), p)];
      const phaseBefore = sendPhase(composers.get(THREAD));
      // The browser restarts and restores the tab (its own session restore, not an OpenWiz guarantee).
      const restarted = page(p, storage.restored());
      const back = restarted.composers.get(THREAD);
      await restarted.composers.check(THREAD, keyOf(back.attempts[0]!));
      assert.equal(posts(p).length, 1, 'reconciling first sent nothing again');
      const rec = p.readBack(intent(sendRoot))[0]!;
      const after = [
        // The send's record is owner state, read back by op id.
        ...sendWork(restarted.composers.get(THREAD), p, THREAD).map((w) => (w.kind === 'pending_operation' ? pending(rec.intent, rec.fingerprint, 'owner_state_read_back') : w)),
        // The unsent launcher draft exists only in the restored tab's storage.
        ...createWork(restarted.launchers.get(PROJECT), p),
      ];
      const ops = [observed(p, intent(sendRoot), 'send', phaseBefore, sendPhase(restarted.composers.get(THREAD)))];
      return {
        document: recovery('browser_restart', before, after, ops, {
          what_happened: 'After the browser restarted, the send’s record was read back first and showed it sent once. The unsent prompt was found only in the restored tab’s storage, which does not prove it is kept.',
          took_effect: 'yes',
          next_action: 'Check the unsent prompt before starting it; keep a copy of drafts you can’t lose.',
        }),
        expect: CLEAN([`retention_unproven:draft:${LAUNCHER_KEY}`]),
      };
    },
  },
  {
    name: 'repeat approval: a double press, a lost reply, a reload and Try again reuse one op id; one answer reaches the orchestrator',
    interruption: 'repeat_approval',
    run: async () => {
      const p = new RecordingProvider();
      const storage = new TabStorage();
      const doc = JSON.parse(readFileSync(new URL('../fixtures/decisions/target.json', import.meta.url), 'utf8'));
      const read = readDecisions(doc);
      assert.ok(read.ok);
      const slot = slotsOf(read.decisions)[0]!;
      const target = (read.decisions.orchestrator.target as { known: string }).known;
      const text = answerText(slot, 'yes')!;
      const slotTab = () => slotStorage(storage, slot.key);
      const answers = () => new Composers({ fetch: p.fetch, storage: slotTab(), timers: new FakeClock(), newOpId: mint });
      const a = answers();
      assert.ok(writeReceipt(slotTab(), { binding: bindingOf(read.decisions, slot)!, target, text, at: 1, phase: 'pending' }));
      a.edit(target, text);
      const root = a.get(target).root!;
      // The receipt's opaque key: a digest of the slot's key (the schema's id form has no room for its JSON).
      const receiptKey = `receipt:${sha256(slot.key).slice(0, 32)}`;
      const before = [draft(receiptKey, readReceipt(slotTab())!.text, 'tab_session_storage'), pending(intent(root), fingerprint('send', sendRequest(target, text)), 'tab_session_storage')];
      p.fault('lose_reply');
      // A double press: the second finds the first out, and sends nothing.
      const first = a.press(target, QUEUE);
      await a.press(target, QUEUE);
      await first;
      await flush();
      const reloaded = answers();
      const back = reloaded.get(target);
      assert.equal(back.attempts[0]?.state, 'unknown');
      const phaseBefore = sendPhase(back);
      // Try again: the same attempt, so the core answers from its record.
      await reloaded.press(target, QUEUE);
      assert.deepEqual(posts(p), [`${root}-q1`, `${root}-q1`], 'the repeat reused the op id');
      assert.equal(reloaded.get(target).attempts[0]?.result, 'sent');
      // Once sent, the draft is done: a further press sends nothing.
      await reloaded.press(target, QUEUE);
      assert.equal(posts(p).length, 2);
      assert.equal(readReceipt(slotTab())?.text, text, 'the receipt keeps the exact answer while it waits on the orchestrator');
      const rec = p.readBack(intent(root))[0]!;
      const after = [draft(receiptKey, readReceipt(slotTab())!.text, 'tab_session_storage'), pending(rec.intent, rec.fingerprint, 'provider_read_back')];
      const ops = [observed(p, intent(root), 'send', phaseBefore, sendPhase(reloaded.get(target)))];
      return {
        document: recovery('repeat_approval', before, after, ops, {
          what_happened: 'The answer was pressed twice and its reply was lost; after a reload, Try again reused the same message id and the core answered from its record: one answer was sent.',
          took_effect: 'yes',
          next_action: 'Nothing to repeat: wait for the orchestrator to save the answer.',
        }),
        expect: CLEAN(),
      };
    },
  },
];

test('#2222: browser-state fault cases keep drafts, identities and work, with no duplicate effect or blind retry', async (t) => {
  const runs: { name: string; document: unknown; expect: Codes }[] = [];
  for (const c of CASES) {
    const r = await c.run();
    assert.equal(r.document.case.interruption, c.interruption);
    runs.push({ name: c.name, ...r });
  }
  const got = codes(runs.map((r) => r.document));
  for (const [i, r] of runs.entries()) {
    t.diagnostic(`#2222: ${r.name}`);
    assert.deepEqual(got[i], r.expect, `${r.name}: ${JSON.stringify(r.document)}`);
  }
});

test('#2222: owner-state fault cases keep setup state, operation identities and the last good build', () => {
  const results = new Map(ownerCases().map((r) => [r.name, r]));
  const setup = results.get('setup_interrupted');
  assert.ok(setup);
  // The id, fingerprint and proposal were saved before any provider read; the resume reused that id and wrote nothing.
  assert.deepEqual(setup.observed, { calls_before_apply: 0, lost_reply_returned: false, same_operation_id: true, resumed_phase: 'applied', operations_saved: 1, provider_writes: 0 });
  assert.deepEqual(setup.codes, CLEAN());
  const update = results.get('update_rejected');
  assert.ok(update);
  assert.deepEqual(update.observed, { update_refused: 'archive size mismatch', last_good_selected: true, update_build_absent: true });
  assert.deepEqual(update.codes, CLEAN());
});

test('#2222: the checks refuse the fault cases’ known ways to fail', () => {
  // The providers' comparisons have teeth: each change below is a way to lose work, duplicate an effect or retry blindly.
  const op = (o: Partial<Transition> = {}): Transition => ({ operation_id: 'f'.repeat(32), kind: 'send', phase_before: 'uncertain', phase_after: 'applied', effect_count: 1, attempts: 1, reconciliation: 'provider_read_back', ...o });
  const work = [draft(COMPOSER_KEY, TEXT, 'tab_session_storage'), pending('f'.repeat(32), fingerprint('send', sendRequest(THREAD, TEXT)), 'tab_session_storage')];
  const explain = (took_effect: 'yes' | 'no' | 'unknown') => ({ what_happened: 'Synthetic.', took_effect, next_action: 'Synthetic.' });
  const cases: [string, unknown, Codes][] = [
    ['a changed draft is lost work', recovery('lost_reply', work, [draft(COMPOSER_KEY, `${TEXT}!`, 'tab_session_storage'), work[1]!], [op()], explain('yes'), 'fail'),
      { problems: [], failures: [`work_lost:draft:${COMPOSER_KEY}`], unproven: RECORDING }],
    ['a second effect is a duplicate', recovery('lost_reply', work, work, [op({ effect_count: 2, attempts: 2 })], explain('yes'), 'fail'),
      { problems: [], failures: [`duplicate_effect:${'f'.repeat(32)}`], unproven: RECORDING }],
    ['a second call without reading the record is a blind retry', recovery('lost_reply', work, work, [op({ attempts: 2, reconciliation: 'none' })], explain('yes'), 'fail'),
      { problems: [], failures: [`blind_retry:${'f'.repeat(32)}`, `uncertainty_erased:${'f'.repeat(32)}`], unproven: RECORDING }],
  ];
  const got = codes(cases.map((c) => c[1]));
  for (const [i, [name, , expect]] of cases.entries()) assert.deepEqual(got[i], expect, name);
});
