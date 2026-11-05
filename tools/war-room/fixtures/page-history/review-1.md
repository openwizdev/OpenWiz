# First correction round

R1 and R2 came from independent review comment 6781922456 at
`3cdad96a56938fdb2e12f71e347903ae0466b443`. Both are medium findings.

R1's reproduction holds the older process at page replacement and starts a
second tick in a separate process. IPC barriers order both real publications.
The operating system's actual file lock is retained during the test. Before
the fix, history ends at 12:10 and the last page replacement restores 12:00.
After the fix, the shared page lock covers latest selection, rendering and
replacement, and both completed ticks leave the page equal to the latest sample.
The original serial and immutable-sample tests did not exercise publication
overlap. Every process/pipe is cleaned up under bounded waits.

R2's reproduction inserts a 09:00 balance sample before an existing 10:00–11:00
span worth 7 credits. Before the fix, that span changes from ordinal 1 to 2.
The correction derives metric/cohort and observation identities from native
endpoint timestamps and the full-balance/extra-only comparison basis. The same
span keeps its identities after backfill, and a changed comparison basis has
distinct identities. The original two-row proof covered its amount only.

`review-1-red.log` records both failures before implementation. The two owning
regressions then pass. All dates, balance records and timestamps are synthetic
assumptions. Original evidence and first-push receipt are retained. Each finding
is in correction round one with zero failed correction rounds and zero disputes.
