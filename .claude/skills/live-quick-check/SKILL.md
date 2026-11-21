---
name: live-quick-check
description: Collect candidate-bound combined smoke and risk receipts within an approved kit; keep fixture results and device gaps distinct from live evidence.
---

# Live quick check

[ADR 0020](../../../docs/adr/0020-release-on-demand.md) governs the future
public-source shipping path after verified O17 cut-over. Preparation may precede
it; no edit here runs O16/O17, clears their holds, activates policy or authorizes
live work/publication. Read the [candidate contract](../../../contracts/release-candidate.v1.md)
and the authority record the orchestrator supplies, or a verified private-record
decision pointer; without one, report the block. The confirmed
private record and existing approved kit remain the sources of actual authority.

**Release gate:** CI, privacy/claims, verified products and an agent-run live smoke
on the same combined build must pass; exercise every included version's promise
end to end.
Changed sending, thread creation, App permissions and spending also need their
relevant bounded live checks before publication. Unknown/missing risk or evidence
refuses. Jake's actual ship instruction and exact changelog approval are the only
human release actions for this path; no per-step live/publish prompt, export-plan,
final-diff, standalone Sol-export or mandatory hands-on/device gate. Ordinary
code review/CI remain. Hands-on feedback follows publication.

**Authority and host:** use only the existing approved kit on its approved host,
from the authorized Local agent. Obtain the actual private kit, observation
helpers, scope and standing-approval/revocation record through the orchestrator;
never reconstruct unavailable scripts or infer authority from a ship flag. Read-only
discovery stays within its separately recorded scope. Ship grants no additional
App permission, arbitrary target, allowance, paid run or activation. If the kit
or authority cannot be read and checked, report the block.

1. **Prepare and bind.** Live checks may start as soon as work is built under
   their existing authority (ADR 0018); shipping still waits for cut-over and
   the actual release decisions. Verify the exact prebuilt source/build and
   product/artifact hashes in a fresh private work directory; do not rebuild
   during the run. Bind the receipt to candidate/artifact/input/kit digests, kit
   scope and the complete user flow for each included version/promise. Changed
   inputs invalidate evidence
   as the contract specifies. A package stamp alone is not compiled identity.

2. **Restrict before effects.** Keep every write to the kit's own throwaway
   targets within existing counts, room-cli allowlist and spending bounds.
   Reuse fleet tick's complete reviewed-plan `--expect-plan` restriction before
   effects, including refusal of pending-start recovery; a check after execution
   cannot constrain it. Refuse if the restriction or any authority is uncertain.
   An approved kit covers its steps without another human prompt. No automatic
   retry: persist consumed attempts and completed steps, return incomplete on
   interruption, and resume only after current input checks and safe read-backs.

3. **Compare honestly.** Use the approved canonical hidden/archived snapshot and
   independent expected results. Judge only threads quiet before the run, excluding
   runner/orchestrator and owner activity (ADR 0009); do not publish their IDs.
   Unknown activity, unreadable counts, failed product calls or unexplained
   differences are incomplete, never pass. A reported room-cli version is not a
   gate. Fixture/dry-run results never satisfy a live gate.

4. **Produce receipts and stop.** Follow the contract's receipt fields: candidate,
   artifacts, complete input and kit digests; evidence class; start/finish;
   immutable private evidence hash/reference; per-promise outcomes and gaps.
   Exercise every included promise end to end on the combined candidate; a partial
   check cannot pass its coverage row. Record every applicable send/new/
   App-permission/spending check. Shared runs may yield separate gate receipts
   with separate input bindings. Save raw snapshots and machine/account evidence privately.
   Public results contain safe technical summaries and verified private-comment
   pointers, never exact answers, thread IDs or private file paths. Return pass,
   fail or incomplete with reasons. Never wait for CI, review, another agent or
   a decision using a watcher, poll loop or sleep.

5. **Keep device limits explicit.** The kit's phone/network steps may use approved
   headless emulation. WebKit and real radios stay unverified. Mac-only checks
   stay on the Mac within existing authority; their absence is recorded honestly.
   A required promise left unproved blocks its gate. Optional hands-on/device
   feedback follows publication and cannot become a new pre-publish human action.
