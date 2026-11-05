import type { Counts } from '../fleetGraph.ts';

/** The reported merged count, drawn as a quiet track beside its existing words. */
export function FleetProgress({ counts }: { counts: Counts | null }) {
  if (counts === null) return null;
  return <progress className="fleet-progress" value={counts.merged} max={Math.max(1, counts.tickets)} aria-hidden="true" />;
}
