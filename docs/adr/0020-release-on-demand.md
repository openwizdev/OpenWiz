# Release on demand from public source after cut-over

Status: accepted successor policy for the public-source path; implementation and
activation remain gated. Preparation can happen earlier. This ADR performs no
O16 rehearsal, O17 cut-over, live run, publication or change to their holds.

After verified open-development cut-over, Jake chooses when a release ships and
approves its exact changelog. Those are the only two human release actions;
changelog approval may precede ship. Agents prepare one checked public candidate,
collect required CI, privacy/claims and an agent-run combined live smoke that
exercises every included promise end to end, publish when all gates pass, then
verify the remote bytes and a matching normal user install/update. Sending, thread creation, App-permission and spending changes
also require their relevant bounded live results before shipping. Unknown risk
or missing/stale/uncertain evidence refuses. A caller's approval flag is not a
decision record. Ordinary development review, plan approval and merge CI remain.

The [candidate contract](../../contracts/release-candidate.v1.md) binds public
source provenance, compiled products, exact notes/artifacts, actual decisions,
receipts and original ship time. Target: strictly under 30 minutes from the
original ship instruction through verified install/update, including approval
waits, queueing, remaining checks/builds, publication and download time. Record
preparation separately. A blocked run stays incomplete; a slow run records a
miss. One light actual observation suffices; fixtures do not prove live timing.

This supersedes [ADR 0019](0019-agent-live-smoke-gates-publishing.md)'s private
export script, standalone Sol export review and final-diff approval for this
path. No export-plan, mandatory hands-on/device, second publish instruction or
per-step publishing approval returns as an extra human gate. Private-to-public
release copying stays stopped, except specifically assigned O16 work. The
historical `release/openwiz/RELEASING.md` remains frozen. Historical backfill
keeps its separate gate.

Keep ADR 0019's combined 0.0.6–0.0.12 release with separate sections, agent smoke
and post-publication feedback. [ADR 0016](0016-agents-run-live-tests.md) retains
approved kits, throwaway targets, counts, allowlists and spending bounds;
[ADR 0018](0018-live-checks-early-publish-in-order.md) retains early live checks and
strict publication order. No broader App grants, account effects, spending,
activation or machine authority is inferred from ship. Preserve immutable
releases, no-force-push, protected-source/merge rules and refusal of unsafe
retries after uncertain writes. Incomplete evidence returns a block without a
watcher, polling loop or sleep.

Source: Jake, 2026-11-10: confirmed public-source on-demand shipping after
cut-over, with ship and exact changelog approval as the only human release
actions, automatic gates, bounded risk checks and a light under-30-minute
ship-to-install observation ([private record](https://github.com/jparker2006/ClosedWiz/issues/2183#issuecomment-6757029416)).
