// #2849: a cockpit part is stale when either device clock says its read is
// older than 70 seconds, as src/viewer.ts's isStale. performance.now() can
// pause while a device sleeps (W3C hr-time#115), and the wall clock can be set
// back, so the two clocks diverge; existing cases only move them together.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { freshNow, staleInMs, type Freshness } from '../../src/cockpit.ts';

const assembledAt = 1_000_000;
const received = { mono: 5_000, wall: 9_000_000 };

const cases: { name: string; sourceAgeMs: number; mono: number; wall: number; fresh: boolean }[] = [
  { name: 'both clocks 70 s: fresh at the limit', sourceAgeMs: 0, mono: 70_000, wall: 70_000, fresh: true },
  { name: 'both clocks 71 s: stale', sourceAgeMs: 0, mono: 71_000, wall: 71_000, fresh: false },
  { name: 'monotonic paused in sleep (1 s), wall 71 s: stale', sourceAgeMs: 0, mono: 1_000, wall: 71_000, fresh: false },
  { name: 'wall set back (-5 s), monotonic 71 s: stale', sourceAgeMs: 0, mono: 71_000, wall: -5_000, fresh: false },
  { name: 'source age 2 s, monotonic 10 s, wall 68 s: fresh at the limit', sourceAgeMs: 2_000, mono: 10_000, wall: 68_000, fresh: true },
  { name: 'source age 2 s, monotonic 10 s, wall 69 s: stale', sourceAgeMs: 2_000, mono: 10_000, wall: 69_000, fresh: false },
];

for (const c of cases) {
  test(`freshNow: ${c.name}`, () => {
    const f: Freshness = { state: 'fresh', snapshot_at: { known: assembledAt - c.sourceAgeMs } };
    const now = { mono: received.mono + c.mono, wall: received.wall + c.wall };
    assert.equal(freshNow(f, assembledAt, received, now), c.fresh);
  });
}

// staleInMs schedules the re-render that shows the part stale: it must count
// the same longer clock, or the page keeps showing fresh past the limit.
const due: { name: string; mono: number; wall: number; ms: number | null }[] = [
  { name: 'both clocks 50 s: due in 20 s', mono: 50_000, wall: 50_000, ms: 20_001 },
  { name: 'monotonic paused (10 s), wall 50 s: due in 20 s', mono: 10_000, wall: 50_000, ms: 20_001 },
  { name: 'wall set back (-5 s), monotonic 50 s: due in 20 s', mono: 50_000, wall: -5_000, ms: 20_001 },
  { name: 'monotonic paused (10 s), wall 71 s: already stale', mono: 10_000, wall: 71_000, ms: null },
];

for (const c of due) {
  test(`staleInMs: ${c.name}`, () => {
    const f: Freshness = { state: 'fresh', snapshot_at: { known: assembledAt } };
    const now = { mono: received.mono + c.mono, wall: received.wall + c.wall };
    assert.equal(staleInMs(f, assembledAt, received, now), c.ms);
  });
}
