// Synthetic HTTP fixture for landing/screenshots and PC browser proofs only.
// No installed source authority, real authentication or phone claim.
import { readFileSync } from 'node:fs';
import { fakeApi, json } from '../../support/fake-api.mjs';
import { startSite } from '../../support/serve.mjs';

export const TOKEN = '1'.repeat(64);
export const TARGET = 'thr_syn_target';
export async function notificationSite({ state = 'current', risky = false, grill = false } = {}) {
  const now = Date.now();
  const doc = JSON.parse(readFileSync(new URL('./decisions.json', import.meta.url), 'utf8'));
  doc.snapshot_at = now;
  doc.freshness.snapshot_at.known = now - 1000;
  doc.orchestrator.freshness.snapshot_at.known = now - 1000;
  if (risky) doc.items[0].request.risk = 'live';
  // Synthetic open grill round on the same exact binding (#2036 R1 draft case).
  if (grill) {
    doc.items[0].subject.kind = 'pull_request';
    doc.items[0].request = { schema: 'openwiz.decisions.v1', kind: 'grill_round', id: 'synthetic-request', status: 'open', fingerprint: 'a'.repeat(64), risk: 'ordinary',
      grill_file: 'docs/grills/synthetic-choice.md', round: 1, questions: [{ id: 'G1', decides: 'Synthetic choice?', context: 'Synthetic context.', recommendation: 'Keep it narrow.' }], answered: [] };
  }
  const reference = { decision: { repository: 'synthetic-owner/synthetic-repo', subject: { kind: grill ? 'pull_request' : 'issue', number: 901 }, comment_id: 902, request_id: 'synthetic-request', fingerprint: 'a'.repeat(64) } };
  const result = { reference, state, coverage: state === 'unread' ? { state: 'partial', gaps: [{ source: 'decisions', reason: 'Independent source unavailable' }] } : { state: 'complete', gaps: [] }, freshness: state === 'unread' ? { state: 'unknown', snapshot_at: { unknown: 'Independent source unavailable' } } : { state: 'fresh', snapshot_at: { known: now - 1000 } } };
  const api = fakeApi();
  // targetGate: an optional promise that holds target replies (a slow read).
  const fx = { api, doc, result, now, targetReply: null, targetGate: null, decisionReply: null, targetReads: 0, decisionReads: 0, requests: [] };
  const site = await startSite(async (req, res, url) => {
    fx.requests.push({ path: url.pathname, method: req.method });
    let reply;
    if (url.pathname.startsWith('/api/v1/notifications/targets/')) {
      fx.targetReads++;
      if (fx.targetGate) await fx.targetGate;
      reply = fx.targetReply ?? (url.pathname === `/api/v1/notifications/targets/${TOKEN}` ? json(200, { schema: 'openwiz.notifications.v1', record: { target_result: fx.result } }) : json(404, { error: { kind: 'no_route', message: 'Reference unavailable' } }));
    } else if (url.pathname === '/api/v1/decisions') {
      fx.decisionReads++;
      reply = fx.decisionReply ?? json(200, fx.doc);
    } else return api.handler(req, res, url);
    res.writeHead(reply.status, reply.headers);
    res.end(reply.body);
  });
  return Object.assign(fx, { site, close: () => site.close() });
}
