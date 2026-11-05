// Synthetic `openwiz fleet <spec> --json` envelopes for #126's proofs: the
// contract's own examples (contracts/fleet.v1.md, read as written), and
// fleets built from a short description. Every value is synthetic.

import { readFileSync } from 'node:fs';

import type { Blocker, Counts, FleetEnvelope, FleetTicket, Read, TicketState } from '../../src/fleetGraph.ts';

const CONTRACT = new URL('../../../../contracts/fleet.v1.md', import.meta.url);

/** The contract's examples 2 (`fleet 901`, complete) and 3 (`fleet 930`, partial), parsed from its JSON blocks. */
export function contractExample(n: 2 | 3): FleetEnvelope {
  const blocks = [...readFileSync(CONTRACT, 'utf8').matchAll(/```json\n([\s\S]*?)\n```/g)].map((m) => m[1] ?? '');
  if (blocks.length !== 3) throw new Error(`the contract has ${blocks.length} JSON examples, not 3`);
  const example: FleetEnvelope = JSON.parse(blocks[n - 1] ?? '');
  if (example.data.view !== 'fleet') throw new Error(`example ${n} is not a fleet view`);
  return example;
}

/** A ticket: its state as reported, its blockers, and its builder's thread (none by default). */
export type SynTicket = {
  number: number;
  title?: string;
  state: TicketState | 'unknown' | 'unread';
  blockedBy?: number[];
  builder?: string;
};
/** A blocker from outside the fleet: its version (a milestone's title, none, or unread) and whether its merge was read back. */
export type SynOutside = { number: number; title?: string; version: string | null | 'unread'; merged: boolean | 'unread' };

export const SNAPSHOT_AT = 1793437200000;
const REVIEWER = { undefined: 'no verified chain places a reviewer in version 1' };
const hex = (n: number) => String(n % 10).repeat(40);
/** A read without its id (which `add` gives it), for each kind. */
type NoId<R> = R extends unknown ? Omit<R, 'id'> : never;

/**
 * A complete `fleet <spec>` envelope (but for the `unread` states and
 * outside blockers asked for): each ticket's reads match its state, as the
 * contract's state table works it out.
 */
export function syntheticFleet(spec: number, tickets: SynTicket[], outsiders: SynOutside[] = [], specTitle = `Synthetic spec ${spec}`): FleetEnvelope {
  const reads: Read[] = [];
  const add = (read: NoId<Read>): string => {
    const id = `r${reads.length + 1}`;
    reads.push({ id, ...read });
    return id;
  };
  add({ kind: 'version', source: 'github', outcome: { state: 'complete', value: '2.100.0' } });
  add({ kind: 'version', source: 'cloudroom', outcome: { state: 'complete', value: 'v132' } });
  const repository = add({ kind: 'repository', outcome: { state: 'complete', value: { name: 'example-repo' } } });
  const specIssue = add({
    kind: 'issue',
    issue: spec,
    outcome: { state: 'complete', value: { title: specTitle, state: 'open', milestone: { number: 7, title: '0.9.1' }, labels: ['spec'], owned_paths: null, relies_on: null } },
  });
  const subIssues = add({ kind: 'sub_issues', spec, outcome: { state: 'complete', value: tickets.map((t) => t.number) } });

  const outsideReads = new Map<number, Blocker>();
  for (const o of outsiders) {
    const pr = 4000 + o.number;
    const issue = add({
      kind: 'issue',
      issue: o.number,
      outcome:
        o.version === 'unread'
          ? { state: 'failed', gap: 'not_found', reason: `#${o.number} couldn't be read` }
          : {
              state: 'complete',
              value: {
                title: o.title ?? `Synthetic blocker ${o.number}`,
                state: o.merged === true ? 'closed' : 'open',
                milestone: o.version === null ? null : { number: 3, title: o.version },
                labels: ['ready-for-agent'],
                owned_paths: null,
                relies_on: null,
              },
            },
    });
    const prRead = add({
      kind: 'pr_discovery',
      issue: o.number,
      outcome:
        o.merged === 'unread'
          ? { state: 'failed', gap: 'not_found', reason: `#${o.number} couldn't be read` }
          : {
              state: 'complete',
              value:
                o.merged === true
                  ? { number: pr, state: 'merged', draft: false, head_branch: `room/syn-old-${o.number}`, head_commit: hex(o.number), base_branch: 'main', closes: [o.number], merge_commit: hex(o.number + 3), merged_at: SNAPSHOT_AT - 86_400_000 }
                  : null,
            },
    });
    const onBase = o.merged === true ? add({ kind: 'merge_readback', pr, outcome: { state: 'complete', value: true } }) : null;
    outsideReads.set(o.number, {
      number: o.number,
      issue,
      pr: prRead,
      on_base: onBase,
      fleet: { known: null },
      merged: o.merged === 'unread' ? { unread: [prRead] } : { known: o.merged },
    });
  }
  const unreadMerge = new Map([...outsideReads].map(([n, b]) => [n, 'unread' in b.merged ? b.merged.unread : []]));

  const rows: FleetTicket[] = [];
  const merged = new Map<number, boolean>();
  for (const t of tickets) {
    const pr = 5000 + t.number;
    const branch = `room/syn-${t.number}`;
    const open = ['building', 'in_review', 'changes_requested', 'unread'].includes(t.state);
    const issue = add({
      kind: 'issue',
      issue: t.number,
      outcome: {
        state: 'complete',
        value: {
          title: t.title ?? `Synthetic ticket ${t.number}`,
          state: t.state === 'unknown' || t.state === 'merged' ? 'closed' : 'open',
          milestone: { number: 7, title: '0.9.1' },
          labels: t.state === 'held' ? ['held'] : ['ready-for-agent'],
          owned_paths: `\`crates/example/src/t${t.number}.rs\``,
          relies_on: 'nothing',
        },
      },
    });
    const blockedBy = add({ kind: 'blocked_by', ticket: t.number, outcome: { state: 'complete', value: t.blockedBy ?? [] } });
    const prRead = add({
      kind: 'pr_discovery',
      issue: t.number,
      outcome: {
        state: 'complete',
        value:
          t.state === 'merged'
            ? { number: pr, state: 'merged', draft: false, head_branch: branch, head_commit: hex(t.number), base_branch: 'main', closes: [t.number], merge_commit: hex(t.number + 1), merged_at: SNAPSHOT_AT - 3_600_000 }
            : open
              ? { number: pr, state: 'open', draft: t.state === 'building', head_branch: branch, head_commit: hex(t.number), base_branch: 'main', closes: [t.number] }
              : null,
      },
    });
    let ci: string | null = null;
    let review: string | null = null;
    let onBase: string | null = null;
    if (open) {
      ci = add({
        kind: 'checks',
        pr,
        outcome:
          t.state === 'unread'
            ? { state: 'failed', gap: 'command_failed', reason: `the checks of pull request ${pr} couldn't be read` }
            : { state: 'complete', value: t.state === 'building' ? [] : [{ name: 'build', result: 'pass' }] },
      });
      const verdict = t.state === 'in_review' ? 'approve' : t.state === 'changes_requested' ? 'changes' : null;
      review = add({ kind: 'comments', pr, outcome: { state: 'complete', value: verdict === null ? null : { verdict, commit: hex(t.number) } } });
    }
    if (t.state === 'merged') onBase = add({ kind: 'merge_readback', pr, outcome: { state: 'complete', value: true } });
    merged.set(t.number, t.state === 'merged');
    rows.push({
      number: t.number,
      issue,
      blocked_by: blockedBy,
      pr: prRead,
      ci,
      review,
      on_base: onBase,
      state:
        t.state === 'unknown'
          ? { unknown: 'closed on GitHub, and no merge was read back' }
          : t.state === 'unread'
            ? { unread: [...(t.blockedBy ?? []).flatMap((n) => unreadMerge.get(n) ?? []), ci ?? ''] }
            : { known: t.state },
      builder: { known: t.builder ?? null },
      reviewer: REVIEWER,
    });
  }

  const blockers: Blocker[] = [];
  const blockerNumbers = [...new Set(tickets.flatMap((t) => t.blockedBy ?? []))].sort((a, b) => a - b);
  for (const n of blockerNumbers) {
    const ticket = rows.find((r) => r.number === n);
    const outside = outsideReads.get(n);
    if (ticket) {
      blockers.push({ number: n, issue: ticket.issue, pr: ticket.pr, on_base: ticket.on_base, fleet: { known: spec }, merged: { known: merged.get(n) ?? false } });
    } else if (outside) blockers.push(outside);
    else throw new Error(`#${n} blocks a ticket but is neither a ticket nor an outside blocker`);
  }

  const builders = tickets.flatMap((t) => (t.builder ? [{ thread: t.builder, branch: `room/syn-${t.number}` }] : []));
  const projects = add({ kind: 'projects', outcome: { state: 'complete', value: [{ id: 'prj_syn_0001', name: 'Synthetic project' }] } });
  const threads = add({ kind: 'threads', outcome: { state: 'complete', value: builders.map((b) => ({ thread: b.thread, project: 'prj_syn_0001', kind: 'cloud' as const })) } });
  for (const b of builders) add({ kind: 'workspace', thread: b.thread, outcome: { state: 'complete', value: b.branch } });

  const counts: Counts = { tickets: tickets.length, ready: 0, building: 0, in_review: 0, changes_requested: 0, merged: 0, held: 0, blocked: 0, unknown: 0 };
  for (const t of tickets) {
    if (t.state === 'unknown') counts.unknown++;
    else if (t.state !== 'unread') counts[t.state]++;
  }
  const unreadStates = rows.flatMap((r) => ('unread' in r.state ? r.state.unread : []));

  return {
    schema: 'openwiz.fleet.v1',
    sources: {
      github: { name: 'gh', version: 'r1', tested_version: '2.100.0', version_tested: true },
      cloudroom: { name: 'room-cli', version: 'r2', tested_version: 'v132', version_tested: true },
    },
    reads,
    coverage: { state: reads.every((r) => r.outcome.state === 'complete') ? 'complete' : 'partial' },
    freshness: { snapshot_at: SNAPSHOT_AT },
    data: {
      view: 'fleet',
      repository,
      projects,
      threads,
      fleet: { spec, issue: specIssue, tickets: subIssues, progress: unreadStates.length > 0 ? { unread: unreadStates } : { known: counts } },
      tickets: rows,
      blockers,
      needs_you: { known: tickets.filter((t) => t.state === 'held').map((t) => ({ kind: 'held' as const, spec, ticket: t.number, ...NO_QUESTION })) },
      unplaced: { known: [] },
    },
  };
}

/** #539: a "needs you" item's four facts, unknown as `openwiz fleet` reports them without a question. */
const NO_QUESTION_WHY = 'no unique newest needs-you or Needs you comment was found';
export const NO_QUESTION = {
  wording: { unknown: NO_QUESTION_WHY },
  link: { unknown: NO_QUESTION_WHY },
  asked_at: { unknown: NO_QUESTION_WHY },
  risk: { unknown: 'no explicit risk classification was reported' },
} as const;

/**
 * The shape of a real spec's graph, with synthetic numbers: three tickets
 * wait on blockers from other fleets and versions, the fourth on them, the
 * fifth on the fourth and an older ticket, the last on the fifth and two
 * more. Five columns: drawn on a desktop, listed on a phone.
 */
export function specThreeFleet(): FleetEnvelope {
  return syntheticFleet(
    960,
    [
      { number: 961, state: 'in_review', blockedBy: [610], builder: 'thr_syn_0961', title: 'Synthetic ticket C1' },
      { number: 962, state: 'building', blockedBy: [610], builder: 'thr_syn_0962', title: 'Synthetic ticket C2' },
      { number: 963, state: 'blocked', blockedBy: [516, 612, 613], title: 'Synthetic ticket C3' },
      { number: 964, state: 'blocked', blockedBy: [516, 961, 962, 963], title: 'Synthetic ticket C4' },
      { number: 965, state: 'blocked', blockedBy: [509, 964], title: 'Synthetic ticket C5' },
      { number: 966, state: 'held', blockedBy: [615, 622, 965], title: 'Synthetic ticket C6' },
    ],
    [
      { number: 509, version: '0.8.3', merged: true },
      { number: 516, version: '0.8.4', merged: false },
      { number: 610, version: '0.8.6', merged: true },
      { number: 612, version: '0.8.6', merged: false },
      { number: 613, version: '0.8.6', merged: false },
      { number: 615, version: '0.8.6', merged: false },
      { number: 622, version: '0.8.6', merged: false },
    ],
    'Synthetic spec C',
  );
}

/**
 * One ticket in each state, and outside blockers merged, not merged and
 * unread: every marker the view can show. Two columns, so it is drawn even
 * on a phone.
 */
export function everyStateFleet(): FleetEnvelope {
  return syntheticFleet(
    700,
    [
      { number: 701, state: 'ready' },
      { number: 702, state: 'building', builder: 'thr_syn_0702' },
      { number: 703, state: 'in_review', builder: 'thr_syn_0703' },
      { number: 704, state: 'changes_requested', builder: 'thr_syn_0704' },
      { number: 705, state: 'merged', builder: 'thr_syn_0705' },
      { number: 706, state: 'held' },
      { number: 707, state: 'blocked', blockedBy: [690, 691] },
      { number: 708, state: 'unknown' },
      { number: 709, state: 'unread', blockedBy: [692] },
    ],
    [
      { number: 690, version: '0.9.0', merged: true },
      { number: 691, version: null, merged: false },
      { number: 692, version: 'unread', merged: 'unread' },
    ],
  );
}
