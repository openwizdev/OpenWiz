# First correction: R1-R4

Implementation: `57a92c991cf132a3e8fd4911b53d5a607ed913b3`. Red proof commit:
`16fb2f75a`; original feature/disjoint red evidence remains unchanged.

- R1: preserve independently rounded native totals; test a possible producer
  value within the separate rounding bounds before admitting a rounded pair.
  Genuinely inconsistent pairs refuse; an unrepresentable exact USD day ratio
  remains unavailable. The inferred arithmetic witness is never output.
- R2: reuse the producer UTC-day rule on spec events or ticket plus linked-PR
  events, intersect with valid export days, and retain missing-day prerequisites.
  Absent dated coverage cannot borrow another entity's window.
- R3: explicit `assembled_at` is passed to the existing suite compose seam;
  source observation and sample identity are preserved.
- R4: retain rejected-export count and unknown date/coverage as a source-level
  prerequisite while preserving valid daily observations.

Proof: `review-1-red.log` records four failures (R1/R3 errors and R2/R4 assertions)
before the implementation. `review-1-green.log`: all 16 cost cases pass.
`review-1-contract.log`: all 18 suite contract cases pass. Python AST and diff
checks pass. No Rust source changed and no full suite was run locally.

Scope: only WR4 owned paths and its two shared sections. No dependency, contract,
native source parser, collection, cost observation, attribution policy, CI rerun,
empty retry, agent start, loop or thread-setting change. All-in remains Unknown
for native sources. Existing synthetic completeness is arithmetic proof only.

Reviewer lineage: retained review-start 6781223604 and report 6781358825.
First correction attempt for each original ID; zero completed correction rounds
or disputes before this attempt. Completion/resolution requires the retained
independent reviewer's exact-head re-check and fresh required CI.

Installed hooks and destination/privacy tools remain unchanged; delivery must
pass them without a bypass. No passing delivery or fresh CI result is claimed
in this local proof record.

Checked source SHA-256:

- `tools/war-room/cost.py`: `7e381e9b81a18b44d09ef56cfbd11a99a0048cb5b3ac1c6c06a0a667d99c196d`.
- `tools/war-room/test_cost.py`: `a081e8c45a1796333e35cf3982431a593917dd6b1b5abde40e163bdfb170b358`.
- `tools/war-room/fixtures/cost/journey.json`: `1351d425e5cc97c8becc8beea64c24fe156b9e10e03ad5a08477bd2a1b420233`.
