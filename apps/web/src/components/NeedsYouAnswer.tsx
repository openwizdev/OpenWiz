// C5: opens the one existing composer. It never sends or owns draft state.
import type { NeedItem } from '../fleets.ts';

export type OpenAnswer = (id: string, prefill: string) => void;

export function NeedsYouAnswer({ item, orchestrator, onAnswer }: { item: NeedItem; orchestrator?: string; onAnswer?: OpenAnswer }) {
  if (onAnswer === undefined) return null;
  const available = orchestrator !== undefined;
  return (
    <div className="act">
      <button type="button" className="btn" aria-label={`Answer #${item.ticket}`} disabled={!available} onClick={() => {
        if (orchestrator !== undefined) onAnswer?.(orchestrator, `Answer for ticket #${item.ticket} (spec #${item.spec}):\n\n`);
      }}>Answer</button>
      <p className="effect">{available ? 'opens the orchestrator’s composer; keeps any existing draft' : 'answer unavailable: orchestrator not configured or not found'}</p>
    </div>
  );
}
