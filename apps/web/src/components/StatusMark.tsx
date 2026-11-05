import type { ReactNode } from 'react';
import type { Tier } from '../markers.ts';
/** Every state has a shape as well as its word. Live motion stops under reduced motion. */
export function StatusGlyph({ tier, shape }: { tier: Tier; shape?: string }) {
  if (shape === 'needs_info' || shape === 'in_review' || shape === 'changes_requested' || shape === 'blocked' || shape === 'not_merged') return <svg className={`status-icon ${tier}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
    {shape === 'needs_info' ? <><path d="m12 3 9 9-9 9-9-9Z" strokeLinejoin="round" /><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4M12 16h.01" strokeLinecap="round" /></>
      : shape === 'in_review' ? <><circle cx="12" cy="12" r="8" /><path d="m10 8 4 4-4 4" /></>
      : shape === 'changes_requested' ? <><circle cx="12" cy="12" r="8" /><path d="m14 8-4 4 4 4" /></>
      : shape === 'blocked' ? <><rect x="4" y="4" width="16" height="16" rx="4" /><path d="M9 8v8M15 8v8" /></>
      : <><circle cx="12" cy="12" r="8" /><path d="M8 12h8" /></>}
  </svg>;
  return <svg className={`status-icon ${tier}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
    {tier === 't1' ? <path d="m12 4 8 8-8 8-8-8Z" fill="currentColor" strokeLinejoin="round" /> : tier === 't3' ? <><circle cx="12" cy="12" r="9" opacity=".65" /><circle cx="12" cy="12" r="4" fill="currentColor" stroke="none" /><g className="orbit"><circle cx="18.4" cy="5.6" r="2.5" fill="currentColor" stroke="none" /></g></> : tier === 't2' ? <><rect x="4" y="4" width="16" height="16" rx="4" /><path d="m7 12 4 4 6-7" /></> : <circle cx="12" cy="12" r="8" strokeDasharray={tier === 't5' ? '3 3' : undefined} />}
  </svg>;
}
export function OutcomeGlyph({ shape }: { shape: string }) {
  const tier = shape === 'failed' ? 't1' : shape === 'sent' ? 't2' : shape === 'moving' ? 't3' : shape === 'not-sent' ? 't4' : 't5';
  if (shape === 'queued' || shape === 'unsupported') return <svg className="status-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">{shape === 'queued' ? <><rect x="4" y="4" width="16" height="16" rx="4" /><path d="M8 12h8M12 8v4l3 3" /></> : <><path d="m12 3 9 17H3L12 3Z" /><path d="m8 16 8-8" /></>}</svg>;
  return <StatusGlyph tier={tier} />;
}
export function StatusMark({ tier, word, shape }: { tier: Tier; word: ReactNode; shape?: string }) {
  return <><span className="glyph" data-part="glyph" aria-hidden="true"><StatusGlyph tier={tier} shape={shape} /></span>{' '}<bdi className="word" data-part="word">{word}</bdi></>;
}
