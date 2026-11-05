# First run — 2026-11-01

This example comes from the first overnight run while the skill was being specified. Read it as an evidence trail, not as permission to repeat endpoint access or as proof this written procedure has run.

The confirmed grill (commit `ac04601`) settled the six rules: bedtime invocation; day review and hunting; reproduction before filing; Terra-wide/Sol-judgment/fixes plus research; reversible small fixes within exact paths; report near 9 am and continue until done. Its later confirmation supersedes the research's earlier “open” status.

## A reproduced documentation finding

The docs hunt notes (commit `b5d02fa`) name main `7dddef4` and seven documents inspected. Six issues (#364–#369) were filed and read back with `overnight` and `needs-triage`. Each issue, rather than the notes alone, holds its command and red output.

For example, #368 compared the orchestration guide's export-spawn example against the Cloud endpoint's actual `thread spawn --help`. Its Python assertion failed because the documented `--parent-self` and `--project` flags were absent from that endpoint's usage. The failing comparison did not start a thread. It established a documentation mismatch, not a product-write failure. The suggested repair stayed in the one document and required ordinary small-fix triage before building.

The same notes marked running-agent counts, loop status and machine state **suspected, not filed**, since they needed endpoint observations the hunt did not obtain. Installed-plugin compatibility also remained unverified. A clean local build did not upgrade those suspicions to facts.

## Sessions and review corrections

The sessions hunt notes (commit `2f0f2b7`) report collecting GitHub comments, Actions runs and 56 available final builder/reviewer outputs. They explicitly distinguish active snapshots from finished sessions and keep raw outputs outside Git. That access was specific to that hunt; this example supplies no new access approval.

Its two filed findings were #370, a synthetic plugin-consumer reproduction of repository-relative command failures, and #371, a synthetic approval-table comparison showing a current fingerprint alone did not guarantee a launchable approval record. The fleet correctly failed closed. The proposed repair validated the posted approval record rather than weakening the start gate.

Repeated scope questions and policy concerns remained suspicions without an executable reproduction. Already-owned CI failures and review findings were linked instead of refiled. This is the deduplication and uncertainty boundary the skill preserves.

## Other reproduced first-run findings

The 0.0.6 bug hunt (commit `a5d9bf6`) filed #372 and #373 from fake-backed CLI reproductions: missing fleet-to-agent wiring, and a legitimate no-check CLI response that fixtures represented incorrectly. It rejected a truncation suspicion after checking the source tool's actual pagination behavior.

The skills/infra hunt (commit `8255e47`) filed #375 (an evidence check used moving main as a historical baseline) and #376 (a controlled archive-to-FIFO swap reproduced a cache-copy hang). A service crash-window concern remained unfiled because it had no executable reproduction. Both hunts kept changes to evidence only and put complete failing reproducers on the issues. Their passing subsystem tests did not erase the independently reproduced failures.

## Research incorporated

The research at `8dea428` contains primary-source citations and ten proposed improvements: a run contract; explicit session coverage; distinct hunt lanes; a candidate ledger; measured flake/docs evidence; routing by task/evidence; deduplication and claims; impact-based small-fix boundaries; durable progress and independent reporting; and a useful report with later evaluation.

The skill incorporates these as procedures, not measured performance claims. The research's suggested initial two-hunter rollout is not an approved cap and is not imposed. Its suggestion of Sol evaluation in a separate context preserves the project's required reviewer family and exact-head gate. Fixed trial limits, success scores and cost estimates from other projects are not imported.

Matt Pocock's `/repro` could not be verified at the inspected public tree. The research instead identifies public `retro`, `diagnosing-bugs` and other sources as related reading. Do not call this a `/repro` adaptation. Dream-cycle reports supply design ideas, not evidence of this repository's cost, quality or overnight success rate.
