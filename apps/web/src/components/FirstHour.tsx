// The first-hour journey guidance (#2223): install, connections, the first
// idea, its grill and approvals, the fleet's progress and the first verified
// merge, over the existing setup, decision and fleet reads. Display only: it
// reads no API itself, sends nothing and starts nothing; it inspects this
// tab's answer storage only as Decisions does, to refuse what it refuses (#2847). A step is shown
// done only from the read that establishes it; a sent answer is never a saved
// one, a count or a merged pull request is never a verified merge, and
// anything unread stays unknown. Sign-in, feedback and the offer stay
// unavailable until their producers are joined. #2205 mounts it.
import { useEffect, useState } from 'react';
import type { Clock, Received } from '../cockpit.ts';
import { staleInMs } from '../cockpit.ts';
import type { SetupView } from '../api.ts';
import type { Decisions, Receipt } from '../decisions.ts';
import { actionable, legacyAnswerReason, nothingWaits, slotsOf } from '../decisions.ts';
import { browserStorage } from '../composer.ts';
import type { FleetEnvelope, MergedPr } from '../fleetGraph.ts';
import { fleetModel } from '../fleetGraph.ts';
import type { Tier } from '../markers.ts';
import { clockText } from '../present.ts';
import { componentName, nextComponent, operationName } from '../setup.ts';
import { StatusGlyph } from './StatusMark.tsx';

/** One read as the page holds it: still reading, failed (with the last good value, if any), or read. */
export type Lane<T> = { state: 'reading' } | { state: 'failed'; why: string; last: T | null } | { state: 'read'; value: T };

export type FirstHourProps = {
  /** The page's clock (ms), for times shown. */
  now: number;
  setup: Lane<SetupView>;
  decisions: Lane<Decisions>;
  /** The decision slots' receipts this tab holds, by slot key (src/decisions.ts). */
  receipts: ReadonlyMap<string, Receipt>;
  /** The first fleet's read: `null` when there is no fleet yet. */
  fleet: Lane<FleetEnvelope | null>;
};

export type StepId = 'install' | 'connections' | 'idea' | 'approval' | 'progress' | 'merge';
export type Step = { id: StepId; tier: Tier; word: string; detail: string; next: string | null; facts: [string, string, boolean?][]; threads: string[] | null };
export type Merge =
  | { state: 'verified'; repository: string; pr: number; ticket: number; commit: string; base: string; mergedAt: number }
  | { state: 'unverified' | 'none' | 'unknown'; title: string; line: string };

const TITLES: Record<StepId, string> = {
  install: 'Install OpenWiz', connections: 'Connect your accounts', idea: 'Give your first idea',
  approval: 'Confirm the spec and approve the plan', progress: 'Watch the fleet build', merge: 'First verified merge',
};
const REVIEWER: [string, string] = ['Independent reviewer', 'unknown: setup checks one harness login, not a reviewer from the other family'];
const step = (id: StepId, tier: Tier, word: string, detail: string, next: string | null = null, facts: Step['facts'] = [], threads: string[] | null = null): Step => ({ id, tier, word, detail, next, facts, threads });
const waiting = (id: StepId, detail: string) => step(id, 't4', 'waiting', detail);
const notRead = (id: StepId) => step(id, 't5', 'not read', 'Not read yet.');

function spending(view: SetupView | null): [string, string] {
  const cost = view?.cost;
  const known = cost && cost.provenance !== 'unknown' ? `${cost.provenance}: ${cost.reason}` : 'unknown: no measured estimate';
  return ['Spending', `${known}. CloudRoom and model charges are separate`];
}

function connections(setup: FirstHourProps['setup']): Step {
  if (setup.state === 'reading') return step('connections', 't5', 'reading', 'Reading setup…');
  if (setup.state === 'failed') return step('connections', 't5', 'unknown', 'Not known until setup answers again.');
  const view = setup.value;
  const uncertain = view.operations.find((o) => o.phase === 'uncertain');
  if (uncertain) {
    return step('connections', 't1', 'check first', `${operationName(uncertain.kind)}: the reply was lost, so OpenWiz cannot tell whether it took effect.`,
      'Ask your installing agent to check this operation by its id before trying again. Do not start it again.',
      [['Took effect', 'unknown'], ['Operation', uncertain.operation_id, true]]);
  }
  const needed = view.components.filter((c) => c.id !== 'remote_access' && c.id !== 'engine');
  const refused = needed.find((c) => c.state === 'refused');
  if (refused) return step('connections', 't1', 'refused', refused.reason, `${refused.next} Your drafts stay.`, [['Took effect', 'no'], REVIEWER]);
  const next = nextComponent(view);
  if (next && next.state === 'missing') return step('connections', 't1', 'your turn', `Next: ${componentName(next.id)}. ${next.reason}`, next.next, [REVIEWER]);
  if (next) return step('connections', 't5', 'unknown', `${componentName(next.id)}: ${next.reason}`, next.next, [REVIEWER]);
  if (!view.ready) return step('connections', 't1', 'your turn', 'Connections verified. Choose where the engine runs next.', 'Nothing starts without your approval.', [REVIEWER]);
  return step('connections', 't2', 'done', 'Setup reports every connection verified.', null, [REVIEWER]);
}

/** The first open decision's step, or null when none is open. */
function openDecision(d: Decisions, receipts: FirstHourProps['receipts'], now: number, time: DecisionTime, cost: [string, string]): Step | null {
  for (const slot of slotsOf(d)) {
    const receipt = receipts.get(slot.key);
    const r = slot.item.request;
    const what = r.kind === 'plan_approval' ? `plan #${r.spec}` : r.kind === 'spec_confirmation' ? `spec #${r.spec}` : 'the grill';
    if (receipt && receipt.phase !== 'pending') {
      return step('approval', 't5', 'sent, not saved', `Your answer to ${what} was sent at ${clockText(receipt.at, new Date(now))}. A send is not a saved approval.`,
        'Wait for Decisions to show it saved. Do not send it again: this tab keeps the same answer.', [['Saved', 'not yet']]);
    }
    if (receipt) {
      return step('approval', 't5', 'check first', `Your answer to ${what} may have been sent: this tab did not keep its result.`,
        'Check Decisions before answering again.', [['Took effect', 'unknown']]);
    }
    // Decisions' own refusal (its AnswerSlot): this tab's storage first, then availability.
    const legacy = legacyAnswerReason(browserStorage(), slot.key);
    const act = legacy === null ? actionable(d, slot, time.received, time.now) : { ok: false as const, why: legacy };
    if (!act.ok) return step('approval', 't5', 'unavailable', act.why, 'Refresh, then check Decisions before answering. Your drafts stay.');
    const detail = r.kind === 'grill_round' ? `Grill round ${r.round} waits for your answers in Decisions.`
      : r.kind === 'grill_confirmation' ? 'Your grill summary waits for your confirmation in Decisions.'
        : r.kind === 'spec_confirmation' ? `Spec #${r.spec} waits for your confirmation in Decisions.`
          : `Plan #${r.spec} waits for your approval: ${r.tickets.length} tickets.`;
    const next = r.kind === 'plan_approval' ? 'Read the exact plan in Decisions, then approve it there. Approving the work does not approve spending.'
      : 'Answer it in Decisions. The spec and the plan are confirmed separately.';
    return step('approval', 't1', 'your turn', detail, next, [cost]);
  }
  return null;
}

/** The verified first merge: a ticket the fleet read reports merged (its merge read back), earliest first. */
function verifiedMerge(f: FleetEnvelope): Merge | null {
  const reads = new Map(f.reads.map((r) => [r.id, r]));
  const repository = reads.get(f.data.repository);
  const name = repository?.kind === 'repository' && repository.outcome.state === 'complete' ? repository.outcome.value.name : 'the repository';
  let first: Merge | null = null;
  for (const t of f.data.tickets) {
    if (!('known' in t.state) || t.state.known !== 'merged') continue;
    const pr = reads.get(t.pr);
    const back = t.on_base === null ? undefined : reads.get(t.on_base);
    if (pr?.kind !== 'pr_discovery' || pr.outcome.state !== 'complete' || pr.outcome.value?.state !== 'merged') continue;
    if (back?.kind !== 'merge_readback' || back.outcome.state !== 'complete' || back.outcome.value !== true) continue;
    const m: MergedPr = pr.outcome.value;
    if (first === null || (first.state === 'verified' && m.merged_at < first.mergedAt)) {
      first = { state: 'verified', repository: `${name} (owner unknown)`, pr: m.number, ticket: t.number, commit: m.merge_commit, base: m.base_branch, mergedAt: m.merged_at };
    }
  }
  return first;
}

/** A merged pull request whose ticket's merge is not read back. */
function unreadMerge(f: FleetEnvelope): MergedPr | null {
  const reads = new Map(f.reads.map((r) => [r.id, r]));
  for (const t of f.data.tickets) {
    if ('known' in t.state) continue;
    const pr = reads.get(t.pr);
    if (pr?.kind === 'pr_discovery' && pr.outcome.state === 'complete' && pr.outcome.value?.state === 'merged') return pr.outcome.value;
  }
  return null;
}

type DecisionTime = { received: Received; now: Clock };

/** The six steps and the merge summary, from the reads alone.
 * Without receipt clocks, count age from assembly conservatively. The mounted
 * component supplies its actual monotonic/wall receipt and current clocks.
 */
export function firstHour(p: FirstHourProps, time?: DecisionTime): { steps: Step[]; merge: Merge; repository: string | null } {
  const setupView = p.setup.state === 'read' ? p.setup.value : p.setup.state === 'failed' ? p.setup.last : null;
  const install = p.setup.state === 'reading' ? step('install', 't5', 'reading', 'Reading setup…')
    : p.setup.state === 'failed' ? step('install', 't1', 'failed', `OpenWiz did not answer the setup read: ${p.setup.why} Nothing was changed by this read.`, 'Check that OpenWiz is running, then Refresh.',
      p.setup.last ? [['Last report', 'The last report is kept and may be out of date.']] : [])
      : step('install', 't2', 'done', 'OpenWiz is installed and its server answered this page.');
  const conn = connections(p.setup);
  const connected = conn.word === 'done';
  const fleet = p.fleet.state === 'read' ? p.fleet.value : null;
  const d = p.decisions.state === 'read' ? p.decisions.value : null;
  const at = d?.snapshot_at ?? p.now;
  const decisionTime = time ?? { received: { mono: at, wall: at }, now: { mono: p.now, wall: p.now } };
  const empty = d !== null && nothingWaits(d, decisionTime.received, decisionTime.now);
  const fleetUnknown = p.fleet.state === 'read' ? null : p.fleet.state === 'failed' ? `The fleet read failed: ${p.fleet.why}` : 'Reading the fleet…';
  const open = d ? openDecision(d, p.receipts, p.now, decisionTime, spending(setupView)) : null;

  let idea: Step;
  if ((d && d.items.length > 0) || fleet) idea = step('idea', 't2', 'done', fleet && !open ? 'Your idea reached a fleet.' : 'Your idea reached the grill.');
  else if (p.decisions.state === 'reading') idea = step('idea', 't5', 'reading', 'Reading decisions…', 'Refresh before giving it again.');
  else if (!empty) idea = step('idea', 't5', 'unknown', p.decisions.state === 'failed' ? `Decisions could not be read: ${p.decisions.why}` : 'The decisions read was partial or stale, so OpenWiz cannot tell whether your idea arrived.', 'Refresh before giving it again.');
  else if (fleetUnknown) idea = step('idea', 't5', 'unknown', fleetUnknown, 'Refresh before giving it again.');
  else if (p.setup.state === 'reading') idea = step('idea', 't5', 'reading', 'Reading setup…', 'Refresh before giving it again.');
  else if (p.setup.state === 'failed') idea = step('idea', 't5', 'unknown', `Setup could not be read: ${p.setup.why}`, 'Refresh before giving it again.');
  else if (!connected) idea = waiting('idea', 'Give your idea once your connections are verified.');
  else idea = step('idea', 't1', 'your turn', 'In a thread on your project, give one small idea to the OpenWiz onboarding skill. It explains the steps, then asks a short grill.', 'Choose your repository when it asks. Nothing is created without your yes.');

  let approval: Step;
  if (p.decisions.state === 'reading') approval = step('approval', 't5', 'not read', 'Reading decisions…', 'Refresh, then check Decisions before answering.');
  else if (open) approval = open;
  else if (!empty) approval = step('approval', 't5', 'unknown', p.decisions.state === 'failed' ? `Decisions could not be read: ${p.decisions.why}` : 'The decisions read is partial or stale, so OpenWiz cannot tell whether an approval waits.', 'Refresh, then check Decisions before answering.');
  else if (fleetUnknown) approval = step('approval', 't5', 'unknown', fleetUnknown, 'Refresh before giving it again.');
  else if (fleet) approval = step('approval', 't4', 'none waiting', 'No confirmation or approval waits in Decisions.');
  else approval = waiting('approval', 'Waits for your idea.');

  let progress: Step;
  let merge: Step;
  let summary: Merge;
  if (p.fleet.state === 'reading') {
    progress = notRead('progress');
    merge = notRead('merge');
    summary = { state: 'unknown', title: 'Not read yet', line: 'Nothing here is a result until its read answers.' };
  } else if (p.fleet.state === 'failed') {
    progress = step('progress', 't1', 'failed', `The fleet read failed: ${p.fleet.why}`, 'Refresh. Work keeps running: nothing starts or stops from this page.');
    merge = step('merge', 't5', 'unknown', 'Not known until the fleet read answers.');
    summary = { state: 'unknown', title: 'Unknown', line: 'The fleet read failed, so a merge may or may not have happened.' };
  } else if (fleet === null) {
    progress = waiting('progress', 'Builders start only after you approve the exact plan.');
    merge = waiting('merge', 'Shown only when GitHub reads the merge back.');
    summary = { state: 'none', title: 'No verified merge yet', line: 'A count or a closed pull request is never shown as a verified merge.' };
  } else {
    const model = fleetModel(fleet);
    const threads = model.tickets.flatMap((t) => ('thread' in t.builder ? [`#${t.number} ${t.marker.word} · ${t.builder.thread}`] : []));
    const counts = 'known' in fleet.data.fleet.progress ? fleet.data.fleet.progress.known : null;
    if (counts) {
      const moving = (['building', 'in_review', 'ready'] as const).filter((k) => counts[k] > 0).map((k) => `${counts[k]} ${k.replace('_', ' ')}`).join(', ');
      const all = counts.tickets > 0 && counts.merged === counts.tickets;
      progress = step('progress', all ? 't2' : 't3', all ? 'all merged' : 'building', `${counts.merged} of ${counts.tickets} merged.${moving ? ` ${moving[0]?.toUpperCase()}${moving.slice(1)}.` : ''}`, null, [], threads.length ? threads : null);
    } else {
      progress = step('progress', 't5', 'unknown', 'Some fleet reads did not answer, so progress is unknown, not zero.', 'Refresh. Work keeps running: nothing starts or stops from this page.', [], threads.length ? threads : null);
    }
    const verified = verifiedMerge(fleet);
    const pending = verified ? null : unreadMerge(fleet);
    if (verified) {
      merge = step('merge', 't2', 'verified', 'Your first pull request merged, read back from GitHub.');
      summary = verified;
    } else if (pending) {
      merge = step('merge', 't5', 'not verified', `Pull request #${pending.number} is merged on GitHub, but its merge has not been read back on ${pending.base_branch}.`, 'Refresh. It is shown as verified only once the read-back answers.');
      summary = { state: 'unverified', title: 'Not verified yet', line: 'A merged pull request is not a verified merge until its merge commit is read back on its base.' };
    } else {
      merge = waiting('merge', 'Shown only when GitHub reads the merge back.');
      summary = { state: 'none', title: 'No verified merge yet', line: 'A count or a closed pull request is never shown as a verified merge.' };
    }
  }
  const repository = d?.items[0]?.subject.repository ?? null;
  return { steps: [install, conn, idea, approval, progress, merge], merge: summary, repository };
}

const clockNow = (): Clock => ({ mono: performance.now(), wall: Date.now() });

export function FirstHour(props: FirstHourProps) {
  // Keep receipt time with this lane, never with an unrelated parent render
  // (setup/fleet may finish much later). Refresh replaces the lane on success.
  const [kept, setKept] = useState(() => ({ lane: props.decisions, received: clockNow() }));
  let snapshot = kept;
  if (kept.lane !== props.decisions) {
    snapshot = { lane: props.decisions, received: clockNow() };
    setKept(snapshot);
  }
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (snapshot.lane.state !== 'read') return;
    const d = snapshot.lane.value;
    const due = [d.freshness, d.orchestrator.freshness]
      .map((f) => staleInMs(f, d.snapshot_at, snapshot.received, clockNow()))
      .filter((ms): ms is number => ms !== null);
    if (due.length === 0) return;
    const handle = window.setTimeout(() => setTick((n) => n + 1), Math.min(...due));
    return () => window.clearTimeout(handle);
  }, [snapshot, tick]);
  useEffect(() => {
    const changed = () => setTick((n) => n + 1);
    document.addEventListener('visibilitychange', changed);
    return () => document.removeEventListener('visibilitychange', changed);
  }, []);
  const now = clockNow();
  const { steps, merge, repository } = firstHour(props, { received: snapshot.received, now });
  return <section className="fh" aria-labelledby="fh-title" data-first-hour="">
    <header className="fh-head">
      <h2 id="fh-title">Your first hour</h2>
      <p>From install to your first verified merge{repository ? ` on ${repository}` : ''}. Each step shows only what OpenWiz has read.</p>
    </header>
    <ol className="fh-steps">{steps.map((s) => <li key={s.id} className="fh-step" data-step={s.id} data-tier={s.tier}>
      <span className="glyph" aria-hidden="true"><StatusGlyph tier={s.tier} /></span>
      <div className="fh-step-head"><h3>{TITLES[s.id]}</h3><span className="fh-state">{s.word}</span></div>
      <p>{s.detail}</p>
      {s.next && <p className="fh-next">{s.next}</p>}
      {s.facts.length > 0 && <dl className="fh-effect">{s.facts.map(([k, v, id]) => <div key={k}><dt>{k}</dt><dd>{id ? <span className="fh-id">{v}</span> : v}</dd></div>)}</dl>}
      {s.threads && <details><summary>Show the agents&apos; threads ({s.threads.length})</summary><ul>{s.threads.map((t) => <li key={t}>{t}</li>)}</ul></details>}
    </li>)}</ol>
    <section className="fh-merge" data-merge={merge.state} aria-label="First merge">
      {merge.state === 'verified'
        ? <><h3>Your first verified merge</h3><dl>
          <dt>Repository</dt><dd>{merge.repository}</dd>
          <dt>Pull request</dt><dd>#{merge.pr}, ticket #{merge.ticket}</dd>
          <dt>Merge commit</dt><dd><span className="fh-id">{merge.commit}</span></dd>
          <dt>Merged</dt><dd>{clockText(merge.mergedAt, new Date(props.now))}</dd>
          <dt>Verified</dt><dd>merge commit read back on {merge.base}</dd>
          <dt>First-hour time</dt><dd>unknown: OpenWiz has no record of when this attempt began</dd>
        </dl></>
        : <><h3>{merge.title}</h3><p>{merge.line}</p></>}
    </section>
    <aside className="fh-later" aria-label="Sign-in, feedback and cost">
      <h3>Sign-in, feedback and cost</h3>
      <ul><li>CloudRoom sign-in: Set up, CloudRoom step</li><li>Feedback and sharing: Home</li></ul>
      <p>OpenWiz is free now. Paid plans come later. CloudRoom and model charges are separate and not included.</p>
    </aside>
  </section>;
}
