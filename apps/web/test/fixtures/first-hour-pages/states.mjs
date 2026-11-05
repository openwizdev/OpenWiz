// The first-hour component's synthetic states (#2223). Each state is the text
// the existing reads would answer (setup.v1, decisions.v1, fleet.v1), any
// decision receipts this tab holds, and what the guidance must show. Every
// repository, number, id and time is invented. Expectations are literals,
// written from the targets in private/design/public-release/first-hour/
// first-hour-states/, never computed the way the component computes them.

/** The fixtures' clock: 2027-01-15 08:00:00 UTC. Tests run with TZ=UTC. */
export const NOW = 1_800_000_000_000;
export const REPO = 'synthetic-owner/first-idea';
export const OP = '3f2a9c41d07b4e58a6c2190b7d3e5f11';
export const MERGE_COMMIT = '9b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c';

// ── setup.v1 ──

const COMPONENTS = ['cloudroom', 'harness', 'personal_github', 'github_app', 'project', 'engine', 'remote_access'];
const component = (id, state = 'verified', reason = `Synthetic: ${id} ${state}.`, next = `Synthetic: nothing to do for ${id}.`) => ({ id, state, reason, next });
const UNKNOWN_COST = { provenance: 'unknown', credits: null, window_s: null, monthly_projection: null, free_allowance: null, reason: 'No measured usage yet.' };

/** A setup report: every component verified unless `over` says otherwise. */
function setup({ over = {}, engine = 'local', operations = [] } = {}) {
  const components = COMPONENTS.map((id) => over[id] ?? component(id, id === 'remote_access' ? 'missing' : 'verified'));
  const ready = engine !== 'unselected' && components.every((c) => c.id === 'remote_access' || c.state === 'verified');
  return JSON.stringify({ schema: 'openwiz.setup.v1', ready, components, engine, cost: UNKNOWN_COST, operations });
}

const SETUP_READY = setup();
const SETUP_APP_MISSING = setup({ over: { github_app: component('github_app', 'missing', 'The OpenWiz GitHub App is not installed.', 'Ask your installing agent to install the App on the one repository you choose.') } });
const SETUP_APP_REFUSED = setup({ over: { github_app: component('github_app', 'refused', `GitHub refused the App's access to ${REPO}.`, 'Grant the App access to that repository, then Refresh.') } });
const SETUP_UNCERTAIN = setup({ engine: 'unselected', over: { engine: component('engine', 'unknown', 'The engine activation reply was lost.', 'Check the operation before trying again.') },
  operations: [{ operation_id: OP, kind: 'activate_engine', phase: 'uncertain', fingerprint: 'a'.repeat(64), effects: ['Start the local engine'], reason: 'The reply was lost.' }] });

// ── decisions.v1 ──

const fresh = { state: 'fresh', snapshot_at: { known: NOW - 2_000 } };
const complete = { state: 'complete', gaps: [] };
const item = (comment_id, number, request) => ({ comment_id, subject: { kind: request.kind === 'grill_round' || request.kind === 'grill_confirmation' ? 'pull_request' : 'issue', number, repository: REPO }, created_at: NOW - 60_000, updated_at: NOW - 60_000, current: { known: true },
  request: { schema: 'openwiz.decisions.v1', id: request.id, status: 'open', fingerprint: String(comment_id % 10).repeat(64), risk: 'ordinary', ...request } });
function decisions(items, coverage = complete) {
  return JSON.stringify({ schema: 'openwiz.decisions.v1', kind: 'response', snapshot_at: NOW, coverage, freshness: fresh,
    orchestrator: { coverage: complete, freshness: fresh, target: { known: 'thr_syn_orch01' } }, items });
}
const GRILL = item(9200001, 2899, { id: 'dr_grill_r1', kind: 'grill_round', grill_file: 'docs/grills/2027-01-15-first-idea.md', round: 1, answered: [],
  questions: [{ id: 'Q1', decides: 'Should the first change be a README badge?', context: 'Synthetic.', recommendation: 'Yes.' }] });
const TICKETS = [2901, 2902, 2903, 2904].map((number) => ({ number, title: `Synthetic ticket ${number}`, blockers: [] }));
const PLAN = item(9200003, 2900, { id: 'dr_plan_2900', kind: 'plan_approval', spec: 2900, summary: ['Add a synthetic badge.'], headline: 'A synthetic first idea.', tickets: TICKETS, graph: [] });
const NO_DECISIONS = decisions([]);
const PARTIAL_DECISIONS = decisions([], { state: 'partial', gaps: [{ kind: 'timed_out', detail: 'Synthetic: the comment read timed out.' }] });
/** The plan card's slot key, as src/decisions.ts's slotsOf makes it. */
export const PLAN_SLOT = JSON.stringify([REPO, 'issue', 2900, 9200003, 'dr_plan_2900']);
const SENT = { binding: 'synthetic-binding', target: 'thr_syn_orch01', text: 'approve #2900', at: NOW - 115_000, phase: 'sent' };

// ── fleet.v1 ──

const SOURCES = { github: { name: 'gh', version: 'r1', tested_version: '2.100.0', version_tested: true }, cloudroom: { name: 'room-cli', version: 'r2', tested_version: 'v132', version_tested: true } };
const ok = (value) => ({ state: 'complete', value });
const failed = (reason) => ({ state: 'failed', gap: 'command_failed', reason });
const REVIEWER = { undefined: 'no verified chain places a reviewer in version 1' };
const openPr = (n, ticket) => ({ number: n, state: 'open', draft: false, head_branch: `room/syn-${ticket}`, head_commit: String(n % 10).repeat(40), base_branch: 'main', closes: [ticket] });
const mergedPr = (n, ticket) => ({ ...openPr(n, ticket), state: 'merged', merge_commit: MERGE_COMMIT, merged_at: NOW - 780_000 });

/**
 * A fleet for spec 2900 with tickets 2901-2904. `states` gives each ticket's
 * state (`null` for unread); `merged` is the merged ticket (PR #12), whose
 * read-back is `readback` (true, or a failed read).
 */
function fleet({ states, merged = null, readback = true }) {
  const reads = [
    { id: 'r1', kind: 'version', source: 'github', outcome: ok('2.100.0') },
    { id: 'r2', kind: 'version', source: 'cloudroom', outcome: ok('v132') },
    { id: 'r3', kind: 'repository', outcome: ok({ name: 'first-idea' }) },
    { id: 'r4', kind: 'issue', issue: 2900, outcome: ok({ title: 'A synthetic first idea', state: 'open', milestone: null, labels: ['spec'], owned_paths: null, relies_on: null }) },
    { id: 'r5', kind: 'sub_issues', spec: 2900, outcome: ok([2901, 2902, 2903, 2904]) },
    { id: 'r6', kind: 'projects', outcome: ok([{ id: 'prj_syn_0001', name: 'Synthetic project' }]) },
    { id: 'r7', kind: 'threads', outcome: ok([{ thread: 'thr_syn_b2901', project: 'prj_syn_0001', kind: 'cloud' }, { thread: 'thr_syn_b2902', project: 'prj_syn_0001', kind: 'cloud' }, { thread: 'thr_syn_b2903', project: 'prj_syn_0001', kind: 'cloud' }]) },
  ];
  const tickets = [];
  const counts = { ready: 0, building: 0, in_review: 0, changes_requested: 0, merged: 0, held: 0, blocked: 0, tickets: 4, unknown: 0 };
  let unread = false;
  for (const [at, number] of [2901, 2902, 2903, 2904].entries()) {
    const id = (k) => `r${number}${{ i: 1, b: 2, p: 3, m: 4 }[k]}`;
    const state = states[at];
    reads.push({ id: id('i'), kind: 'issue', issue: number, outcome: ok({ title: `Synthetic ticket ${number}`, state: 'open', milestone: null, labels: ['ready-for-agent'], owned_paths: null, relies_on: null }) });
    reads.push({ id: id('b'), kind: 'blocked_by', ticket: number, outcome: ok([]) });
    const pr = number === merged ? mergedPr(12, number) : state === 'ready' ? null : openPr(10 + at, number);
    reads.push({ id: id('p'), kind: 'pr_discovery', issue: number, outcome: ok(pr) });
    let onBase = null;
    if (number === merged) {
      onBase = id('m');
      reads.push({ id: onBase, kind: 'merge_readback', pr: 12, outcome: readback === true ? ok(true) : failed('the merge of pull request 12 could not be read back') });
    }
    const builder = at < 3 ? { known: `thr_syn_b${number}` } : { known: null };
    tickets.push({ number, issue: id('i'), blocked_by: id('b'), pr: id('p'), ci: null, review: null, on_base: onBase, state: state === null ? { unread: [onBase ?? id('p')] } : { known: state }, builder, reviewer: REVIEWER });
    if (state === null) unread = true; else counts[state]++;
  }
  const failedReads = reads.filter((r) => r.outcome.state !== 'complete').map((r) => r.id);
  return JSON.stringify({ schema: 'openwiz.fleet.v1', sources: SOURCES, reads, coverage: { state: failedReads.length ? 'partial' : 'complete' }, freshness: { snapshot_at: NOW - 3_000 },
    data: { view: 'fleet', repository: 'r3', projects: 'r6', threads: 'r7', fleet: { spec: 2900, issue: 'r4', tickets: 'r5', progress: unread ? { unread: failedReads.length ? failedReads : ['r29013'] } : { known: counts } },
      tickets, blockers: [], needs_you: { known: [] }, unplaced: { known: [] } } });
}

const BUILDING = fleet({ states: ['building', 'building', 'in_review', 'ready'] });
const ONE_MERGED = fleet({ states: ['merged', 'building', 'in_review', 'ready'], merged: 2901 });
const NOT_READ_BACK = fleet({ states: [null, 'building', 'in_review', 'ready'], merged: 2901, readback: 'failed' });

// ── the states ──

const read = (text) => ({ state: 'read', text });
const reading = { state: 'reading' };
const W = 'waiting';

// #2786: a partial empty fleet list is a failed lane from #2205's mount,
// with its source reason retained; it never establishes that no fleet exists.
export const UNKNOWN_FLEETS = {
  reading: { state: 'reading' },
  failed: { state: 'failed', why: 'Synthetic: the fleet read timed out.', last: null },
  partial: { state: 'failed', why: 'the fleet list was read only in part.', last: null },
  'failed-with-last': { state: 'failed', why: 'Synthetic: the fleet refresh failed.', last: BUILDING },
};

/**
 * Each state: its inputs, then `steps` (each step's id → [shown word, tier]),
 * `merge` (the summary's data-merge), `text` (phrases it must show) and
 * `absent` (phrases it must not).
 */
export const STATES = {
  start: { setup: read(SETUP_READY), decisions: read(NO_DECISIONS), fleet: read(null), receipts: [],
    steps: { install: ['done', 't2'], connections: ['done', 't2'], idea: ['your turn', 't1'], approval: [W, 't4'], progress: [W, 't4'], merge: [W, 't4'] }, merge: 'none',
    text: ['give one small idea to the OpenWiz onboarding skill', 'Nothing is created without your yes.', 'Independent reviewer'], absent: ['verified merge on'] },
  ...Object.fromEntries(Object.entries(UNKNOWN_FLEETS).map(([name, fleet]) => [`fleet-${name}`, {
    setup: read(SETUP_READY), decisions: read(NO_DECISIONS), fleet, receipts: [],
    steps: { install: ['done', 't2'], connections: ['done', 't2'], idea: ['unknown', 't5'], approval: ['unknown', 't5'],
      progress: name === 'reading' ? ['not read', 't5'] : ['failed', 't1'], merge: name === 'reading' ? ['not read', 't5'] : ['unknown', 't5'] },
    merge: 'unknown', text: [name === 'reading' ? 'Reading the fleet…' : fleet.why, 'Refresh before giving it again.'], absent: ['your turn', 'Your idea reached a fleet.'],
  }])),
  loading: { setup: reading, decisions: reading, fleet: reading, receipts: [],
    steps: { install: ['reading', 't5'], connections: ['reading', 't5'], idea: ['reading', 't5'], approval: ['not read', 't5'], progress: ['not read', 't5'], merge: ['not read', 't5'] }, merge: 'unknown',
    text: ['Nothing here is a result until its read answers.'], absent: ['done', 'your turn'] },
  'setup-failed': { setup: { state: 'failed', why: 'Synthetic: the server did not answer.', last: SETUP_READY }, decisions: read(decisionsWith(GRILL)), fleet: read(null), receipts: [],
    steps: { install: ['failed', 't1'], connections: ['unknown', 't5'], idea: ['done', 't2'], approval: ['your turn', 't1'], progress: [W, 't4'], merge: [W, 't4'] }, merge: 'none',
    text: ['Synthetic: the server did not answer.', 'Nothing was changed by this read.', 'The last report is kept and may be out of date.'], absent: [] },
  'connections-missing': { setup: read(SETUP_APP_MISSING), decisions: read(NO_DECISIONS), fleet: read(null), receipts: [],
    steps: { install: ['done', 't2'], connections: ['your turn', 't1'], idea: [W, 't4'], approval: [W, 't4'], progress: [W, 't4'], merge: [W, 't4'] }, merge: 'none',
    text: ['Next: OpenWiz GitHub App', 'The OpenWiz GitHub App is not installed.', 'install the App on the one repository you choose'], absent: [] },
  'connections-refused': { setup: read(SETUP_APP_REFUSED), decisions: read(NO_DECISIONS), fleet: read(null), receipts: [],
    steps: { install: ['done', 't2'], connections: ['refused', 't1'], idea: [W, 't4'], approval: [W, 't4'], progress: [W, 't4'], merge: [W, 't4'] }, merge: 'none',
    text: [`GitHub refused the App's access to ${REPO}.`, 'Grant the App access to that repository, then Refresh.', 'Took effect', 'Your drafts stay.'], absent: [] },
  'setup-recovery': { setup: read(SETUP_UNCERTAIN), decisions: read(NO_DECISIONS), fleet: read(null), receipts: [],
    steps: { install: ['done', 't2'], connections: ['check first', 't1'], idea: [W, 't4'], approval: [W, 't4'], progress: [W, 't4'], merge: [W, 't4'] }, merge: 'none',
    text: ['Activate engine: the reply was lost', OP, 'Do not start it again.'], absent: [] },
  grill: { setup: read(SETUP_READY), decisions: read(decisionsWith(GRILL)), fleet: read(null), receipts: [],
    steps: { install: ['done', 't2'], connections: ['done', 't2'], idea: ['done', 't2'], approval: ['your turn', 't1'], progress: [W, 't4'], merge: [W, 't4'] }, merge: 'none',
    text: ['Grill round 1 waits for your answers in Decisions.', 'CloudRoom and model charges are separate'], absent: [] },
  approval: { setup: read(SETUP_READY), decisions: read(decisionsWith(PLAN)), fleet: read(null), receipts: [],
    steps: { install: ['done', 't2'], connections: ['done', 't2'], idea: ['done', 't2'], approval: ['your turn', 't1'], progress: [W, 't4'], merge: [W, 't4'] }, merge: 'none',
    text: ['Plan #2900 waits for your approval: 4 tickets.', 'Approving the work does not approve spending.'], absent: ['approved and saved'] },
  'sent-not-saved': { setup: read(SETUP_READY), decisions: read(decisionsWith(PLAN)), fleet: read(null), receipts: [[PLAN_SLOT, SENT]],
    steps: { install: ['done', 't2'], connections: ['done', 't2'], idea: ['done', 't2'], approval: ['sent, not saved', 't5'], progress: [W, 't4'], merge: [W, 't4'] }, merge: 'none',
    text: ['Your answer to plan #2900 was sent at 07:58:05.', 'A send is not a saved approval.', 'Do not send it again'], absent: ['your turn'] },
  progress: { setup: read(SETUP_READY), decisions: read(NO_DECISIONS), fleet: read(BUILDING), receipts: [],
    steps: { install: ['done', 't2'], connections: ['done', 't2'], idea: ['done', 't2'], approval: ['none waiting', 't4'], progress: ['building', 't3'], merge: [W, 't4'] }, merge: 'none',
    text: ['0 of 4 merged', "Show the agents' threads (3)", 'thr_syn_b2901', 'No confirmation or approval waits in Decisions.'], absent: ['approved and saved'] },
  'progress-unknown': { setup: read(SETUP_READY), decisions: read(PARTIAL_DECISIONS), fleet: { state: 'failed', why: 'Synthetic: the fleet read timed out.', last: null }, receipts: [],
    steps: { install: ['done', 't2'], connections: ['done', 't2'], idea: ['unknown', 't5'], approval: ['unknown', 't5'], progress: ['failed', 't1'], merge: ['unknown', 't5'] }, merge: 'unknown',
    text: ['Synthetic: the fleet read timed out.', 'nothing starts or stops from this page'], absent: ['0 of 4'] },
  'merge-unverified': { setup: read(SETUP_READY), decisions: read(NO_DECISIONS), fleet: read(NOT_READ_BACK), receipts: [],
    steps: { install: ['done', 't2'], connections: ['done', 't2'], idea: ['done', 't2'], approval: ['none waiting', 't4'], progress: ['unknown', 't5'], merge: ['not verified', 't5'] }, merge: 'unverified',
    text: ['Pull request #12 is merged on GitHub, but its merge has not been read back on main.', 'progress is unknown, not zero'], absent: ['Your first verified merge', MERGE_COMMIT] },
  merged: { setup: read(SETUP_READY), decisions: read(NO_DECISIONS), fleet: read(ONE_MERGED), receipts: [],
    steps: { install: ['done', 't2'], connections: ['done', 't2'], idea: ['done', 't2'], approval: ['none waiting', 't4'], progress: ['building', 't3'], merge: ['verified', 't2'] }, merge: 'verified',
    text: ['Your first verified merge', '1 of 4 merged', '#12', 'ticket #2901', MERGE_COMMIT, '07:47:00', 'read back on main', 'First-hour time', 'no record of when this attempt began', 'first-idea (owner unknown)'], absent: [] },
};

function decisionsWith(...items) { return decisions(items); }

/** Shown in every state: what stays unavailable until its producer is joined. */
export const ALWAYS = ['Sign-in, feedback and cost', 'CloudRoom sign-in: Set up, CloudRoom step', 'Feedback and sharing: Home', 'OpenWiz is free now. Paid plans come later.', 'CloudRoom and model charges are separate and not included.'];
/** Never shown in any state: no paid offer, price or payment. */
export const NEVER = ['$', 'per month', 'trial', 'Upgrade', 'Buy', 'Subscribe', 'checkout', 'payment'];
