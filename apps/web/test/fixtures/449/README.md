# #449 proof plan

Fixture evidence only. `test/unit/v11-refresh.test.ts` runs P4 itself twice
against synthetic HTTP answers, isolating each child's results in a temporary
directory. The hook adds 2,000 bytes of valid JSON whitespace to the initial
load, then zero or 1,000 bytes to each refresh. It independently records the
actual response bodies and checks their declared Content-Length.

Claims: each size has exactly one initial load and 20 refreshes; planting
1,000 bytes raises P4's recorded mean by exactly 1,000; each mean equals the
20 actual refresh bodies' byte lengths, excluding the initial load. P6–P8's
existing assertions remain in the browser test. No performance target changes
and no live behaviour is claimed.

Run from `apps/web`: `node --test test/unit/v11-refresh.test.ts`.
`red.log` is the failing run committed before the fix.
