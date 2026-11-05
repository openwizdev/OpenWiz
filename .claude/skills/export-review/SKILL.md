---
name: export-review
description: Prepare and check one public-source release candidate; after verified cut-over, agents ship only with actual ship and exact changelog decisions plus passing automatic gates.
---

# Check a public release candidate

[ADR 0020](../../../docs/adr/0020-release-on-demand.md) supersedes ADR 0019's
private export, standalone Sol export review and final-diff approval for the
future public-source path. Read the
[candidate contract](../../../contracts/release-candidate.v1.md), its schema and
[release tool guidance](../../../tools/release/README.md). The contract is an
interface for consumers still being built, not a claim the command already
supports it. Do not improvise missing command flags or use a legacy `--approval`
argument as decision evidence.

**Activation gate:** preparation can happen before cut-over, but shipping requires
verified O17 after O16 with their existing authorization, prerequisites and holds
intact. This skill authorizes neither step, no live run or publication now.
Development targets stay as configured until cut-over. Private-to-public release
copying remains stopped except specifically assigned O16 work. Never copy a
private commit/history into the public source. `release/openwiz/` stays frozen.

1. **Prepare one checked candidate.** Use the public repository's own history,
   a clean selected commit/build and complete matching products for all supported
   targets. Keep ordered individual changelog sections for every included version,
   including all seven for the settled 0.0.6–0.0.12 combined release. Bind exact
   UTF-8 notes, complete artifact/manifest/checksum/alias hashes, product provenance,
   kit scope and risk classification under the candidate digest. Ordinary
   development plan approval, code review, protected-source and merge CI remain.

2. **Resolve the two actual decisions.** Jake's ship instruction and approval
   of the exact changelog are the only human release actions; approval may precede
   ship. Verify the existing private decision comments, author, scope, current
   revision, hashes and candidate/notes bindings. A supplied flag, invented pointer
   or old decision for another candidate refuses. Store original ship time before
   effects. No export-plan, final-diff, mandatory Sol-export, mandatory hands-on/
   device or second publish instruction. Keep exact answers private; public
   records contain a decision summary, date and verified private-comment pointer.

3. **Require every automatic gate.** Resolve exact-candidate CI, full public
   source/history/artifact privacy, honest claim evidence and compiled-product
   verification. Require the combined live smoke to exercise every included promise
   end to end and run live checks for changed sending, thread creation, App
   permissions or spending.
   Use `live-quick-check` only within existing approved kit targets/counts,
   allowlists, App grants, host and spending. Unknown risk, unreadable/missing,
   failed, stale, fixture, dry-run or uncertain required evidence blocks. Keep
   known gaps explicit. Semantic claims and archive privacy checks remain;
   they are automatic release gates, not an additional human export approval.
   Use affected local proofs and existing free CI receipts; never run full
   workspace/browser suites locally to prove orchestration.

4. **Invalidate changed inputs.** Recompute bindings when source/build, notes,
   artifacts, kit or risk changes; refresh affected evidence/approval according
   to the contract. Recheck current external holds, permissions and gate inputs
   before each effect. Never patch checked bytes behind a passing report. Keep
   original ship time across resumes, completed steps and consumed attempts.
   Return blocked/incomplete with a reason when progress needs another event;
   no watcher, poll loop or sleep.

5. **Publish and read back when authorized.** Agents publish only after verified
   cut-over, both actual decisions and every required passing gate. Verify current
   immutable-release and required-check settings under their existing owners;
   this adds no new settings approval. Preserve protected-source/merge rules,
   no-force-push and version order. Read back the annotated tag/peeled public
   commit, exact approved notes, complete asset bytes/manifests/checksums/aliases
   and immutable pre-release state. Partial publication is incomplete. Inspect
   uncertain effects before any retry; never repeat a potentially consumed write
   automatically, move a published tag or rewrite a published entry. Historical
   backfill keeps its own explicit gate and original checked public commits.

6. **Verify user delivery and report.** Obtain the matching version/source/products
   through normal install/update on an already approved test machine. Stop the
   clock only after matching installation and remote publication verification.
   Include all time after the original ship instruction: changelog waits, queue,
   checks/builds, publication and download/update; report preparation separately.
   Under 30 minutes meets the light target; otherwise record a miss or block.
   This proves only that route/machine. Jake's device/hands-on feedback follows
   publication. Raw machine/account/live evidence stays private; publish only
   safe technical results and verified private-record pointers. No public thread IDs.
