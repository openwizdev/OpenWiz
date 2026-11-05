# WR4 synthetic proof plan

All paths, identities, links, dates, source shapes and values here are synthetic
assumptions. No source observation, billing, account completeness or real
allocation is claimed. The allocation fixture is an in-memory projection example,
not a native export format or a supported attribution source.

Claims and owning boundary proofs (`test_cost.py`, through suite compose/loads):

- Complete/partial/absent native journey daily usage and CI points retain their
  provider/unit/window/source values; absent allocation leaves all-in Unknown.
  A plausible bug would sum daily totals and CI estimates as attributed cost.
  Existing generic suite tests cannot detect such an adapter attribution error.
- Five allocation components cover two unique merged PRs: models $4, shared
  parent $2, helpers $1, sandbox $3, CI $2. Total $12 / 2 = $6 per PR.
  The shared charge covers both PRs once. Missing/unallocated components and
  zero merges leave Unknown. Overlapping component coverage, repeated charge
  IDs, foreign cohorts and non-USD amounts refuse rather than double count.
- Journey ticket and parent usage remain separate thread-record lower bounds;
  one PR closing two tickets never multiplies the shared parent or PR cohort.
  Daily USD/merge is labelled a UTC day ratio; credits/tokens/hours stay native.
  CI list-rate cost keeps its fixed-PST window, price dates and exclusions.
- Malformed source artifacts, source observations before their data, unsafe
  output provenance and duplicate JSON keys refuse. No tool or network is run.

Disjoint models rows of $1 and $3 must display one $4 component total with
two-of-two PR coverage, independent of row ordering. `red-disjoint.log` records
the initial one-row-only display before the aggregation fix.

The initial red log is committed before cost.py exists. Green logs are scoped
fixture results only. CI owns full suites; page rendering belongs to WR2.

## First correction proof plan: R1-R4

R1 owns the producer-independent rounding case: raw 1.2345674 over two merges
produces saved total 1.234567 and saved day ratio 0.617284. Re-dividing the
rounded total rejects valid native output. Preserve its total; the suite cannot
represent that rounded USD ratio as exact. Reject impossible rounded pairs.

R2 owns entity-specific UTC coverage: midday events require complete contributing
UTC days, from the spec's own events or a ticket and its linked PRs. Different
entity spans cannot share a document-wide window. Missing exports and entities
without dated usage cannot borrow another entity's window. The native fixture
now makes its synthetic entity timestamps explicit; original red logs remain.

R3 owns injected assembly: a sample at 00:00:00 can contain a source observed at
00:00:01 when assembled at 00:00:02. Observation after assembly still refuses.
R4 owns rejected exports: mixed valid/invalid native rows retain both valid daily
values and a visible prerequisite naming unknown rejected-export coverage.

All four are adapter boundary bugs absent from the original generic suite proof.
The new affected tests run red before these corrections; no live fact is claimed.
