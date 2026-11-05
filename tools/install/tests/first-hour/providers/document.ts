// One first-hour `recovery` document per fault case (contracts/first-hour.v1.md,
// "Recovery cases"), built from what the case observed, and its codes, as
// #2200's checks give them (`codes.py`, which loads
// tools/install/tests/first-hour-contract/check.py by path). Nothing here
// decides an outcome: the checks do, from the observations.

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

import type { RecordingProvider } from './recording.ts';

export type Interruption =
  | 'revoked_access'
  | 'refused_access'
  | 'builder_unavailable'
  | 'reviewer_unavailable'
  | 'setup_interrupted'
  | 'lost_reply'
  | 'browser_restart'
  | 'process_restart'
  | 'update_rejected'
  | 'removal_default'
  | 'repeat_approval';
export type Basis = 'owner_state_read_back' | 'repository_read_back' | 'provider_read_back' | 'tab_session_storage';
export type Phase = 'proposed' | 'applied' | 'refused' | 'uncertain';
export type Work = { kind: 'draft' | 'setup_state' | 'branch' | 'commit' | 'pending_operation'; id: string; content: string; basis: Basis };
export type Transition = { operation_id: string; kind: 'send' | 'new_thread'; phase_before: Phase; phase_after: Phase; effect_count: number; attempts: number; reconciliation: 'none' | 'provider_read_back' };
export type Explanation = { what_happened: string; took_effect: 'yes' | 'no' | 'unknown'; next_action: string };
export type Codes = { problems: string[]; failures: string[]; unproven: string[] };

export const sha256 = (text: string): string => createHash('sha256').update(text, 'utf8').digest('hex');

/** A draft's exact UTF-8 bytes, by its opaque key, where it was read. */
export const draft = (id: string, text: string, basis: Basis): Work => ({ kind: 'draft', id, content: sha256(text), basis });

/** A draft read back as the provider's exact record of it once sent: the digest of the text it delivered. */
export const delivered = (id: string, textSha256: string): Work => ({ kind: 'draft', id, content: textSha256, basis: 'provider_read_back' });

/** A pending owner intent: its operation id and request fingerprint, where it was read. */
export const pending = (intent: string, fingerprint: string, basis: Basis): Work => ({ kind: 'pending_operation', id: intent, content: fingerprint, basis });

/**
 * One intent's observation across the case: its phases as the page showed
 * them before and after, and the provider's own counts: effects, calls and
 * whether its exact record was read back.
 */
export function observed(p: RecordingProvider, intent: string, kind: Transition['kind'], phaseBefore: Phase, phaseAfter: Phase): Transition {
  return {
    operation_id: intent,
    kind,
    phase_before: phaseBefore,
    phase_after: phaseAfter,
    effect_count: p.effects.get(intent) ?? 0,
    attempts: p.calls.get(intent) ?? 0,
    reconciliation: (p.reads.get(intent) ?? 0) > 0 ? 'provider_read_back' : 'none',
  };
}

export const ASSUMPTIONS = [
  "Synthetic recording-provider fault case at the web page's state seam (#2222): every id, text and digest is invented; the provider models the core's once-only send and new-thread records.",
  'No installed candidate, CloudRoom, GitHub account or browser was observed: this proves behaviour at the contract seam only; #2204 reruns it on the installed journey.',
];

/** The recovery document for one case. A recording is never a pass: its verdict is unverified, or fail when it shows a failure. */
export function recovery(interruption: Interruption, before: Work[], after: Work[], operations: Transition[], explanation: Explanation, verdict: 'unverified' | 'fail' = 'unverified') {
  return {
    schema: 'openwiz.first-hour.v1',
    kind: 'recovery',
    verdict,
    proof_class: 'recording',
    synthetic_assumptions: ASSUMPTIONS,
    private_record: null,
    candidate: { unknown: 'no installed candidate: a recording at the browser-state seam' },
    case: { interruption, before, after, operations, explanation },
  };
}

const CODES = fileURLToPath(new URL('./codes.py', import.meta.url));

/** The first-hour checks' codes for each document, in order (one Python run). */
export function codes(documents: readonly unknown[]): Codes[] {
  const out = execFileSync('python3', ['-I', '-B', CODES, 'check'], { input: JSON.stringify(documents), encoding: 'utf8' });
  return JSON.parse(out) as Codes[];
}

/** The owner-state cases (setup and install), run through their existing Python interfaces: each document and its codes. */
export function ownerCases(): { name: string; document: unknown; codes: Codes; observed: Record<string, unknown> }[] {
  const out = execFileSync('python3', ['-I', '-B', CODES, 'owner-cases'], { encoding: 'utf8' });
  return JSON.parse(out) as { name: string; document: unknown; codes: Codes; observed: Record<string, unknown> }[];
}
