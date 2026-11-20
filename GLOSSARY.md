# OpenWiz

OpenWiz runs many coding agents at once, organized into fleets, with the user deciding and OpenWiz doing the running. Each word means only what it says here.

## Work

**Version**: a small shippable step of a project, with at most five outcomes; done when all its work has merged and its live check has passed. On GitHub, a milestone. _Avoid_: release (a published version), sprint.

**Spec**: one coherent piece of a version, written after a grill; done when every ticket is done. On GitHub, a parent issue whose body is the spec. _Avoid_: PRD, epic.

**Ticket**: one unit of work under a spec, sized for one builder, declaring its owned paths and the tickets that block it; done only on a verified merge. On GitHub, a sub-issue of its spec. _Avoid_: task, story.

**Plan graph**: a spec's tickets and their blocking edges; the user approves it as a whole, and that approval launches its fleet. _Avoid_: backlog.

**Owned paths**: the files and folders a ticket may change; tickets running at once normally own disjoint paths. A small file marked `(shared)` may be shared when each ticket names and changes only its own lines; whichever merges second fixes the conflict.

**Real link**: a link whose reason names the behaviour the later ticket needs from the earlier one.

**File link**: a link whose reason says the two tickets only share files, and names them. The goal is zero.

**Contract-first ticket**: the small ticket a spec opens with, writing the shared shape (contract, types, schemas, fixtures, stubs) that later tickets fill in, with real links to them. Only a spec with no shared interface skips it.

**Startable share**: of the open approved tickets, those with no open blocker.

**Ready stock**: open approved tickets that can start, have no builder running, aren't held and aren't waiting on the user. The factory is fed while it is at least twice the builders running.

**Forward, sideways, backwards**: work that adds something a user can do (a version's tickets; outward work such as docs and launch counts too); work that makes the factory faster, cheaper or safer (CI, releases, tooling); work that hardens what shipped (bug fixes, missing tests, stale docs, review follow-ups).

**Verified merge**: a merge OpenWiz has read back from GitHub. Only this counts as merged; never an approval, a ready pull request or a closed issue.

## Agents

**Project**: one codebase with one repository, one orchestrator and any number of fleets.

**Orchestrator**: the one agent per project that grills with the user, plans, launches fleets, routes reviews and merges by the standing rules; it never builds or reviews. _Avoid_: manager, lead.

**Fleet**: the agents working one spec's plan graph, launched together when the user approves it; there is no artificial cap on their number or size. _Avoid_: swarm, team.

**Agent**: one CloudRoom thread doing one role for one ticket or fleet. _Avoid_: bot, worker.

**Builder**: the agent that builds one ticket on its own branch and opens its pull request; it never reviews or merges.

**Reviewer**: an independent agent that reviews a pull request at its exact head and approves it or asks for changes; it never edits.

## Decisions

**Grill**: a focused interview in rounds that settles a design before anything is written. Its exact answers stay private; decisions that are hard to reverse go in `docs/adr/`. _Avoid_: brainstorm.

**Skill**: a Markdown instruction file any agent, in any harness, invokes to do one step of the factory the same way every time.

**Standing approval**: a recorded, still-valid permission from the user that lets the orchestrator take a gated step without asking again. _Avoid_: blanket approval.

**Correction round**: one builder fix and one reviewer re-check. A pull request gets one review and one re-check; after that, an open security, privacy or data-loss blocker gets one fresh fix round and then waits for the user, and any other open blocker becomes a logged follow-up ([review loops](contracts/review-loops.v2.md)). _Avoid_: iteration, retry.

**Live check**: the short test of a version on the user's real account and machine, sized to its risk. _Avoid_: QA, acceptance run.

**huntr**: the skill and loop that find work nobody planned (bugs, flaky or missing tests, stale docs) and approve it themselves within the kinds the user approved; anything bigger goes to the user as a proposal. _Avoid_: found work, autonomous work.

## Ops records ([ops-dispatch v1](contracts/ops-dispatch.v1.md))

**Record claim**: admission of one immutable GitHub record through an atomic create-if-absent reference, scoped to a repository, spec, generation and operation. A duplicate refuses. It neither fences a later external effect nor replaces an approval.

**Generation**: a rising record-ownership number for one repository and spec; only complete claim history names the owner.

**Effect boundary**: the door that actually starts, delivers, releases a label or merges. Its own generation fencing must be shown separately; until then that effect stays disabled.

**Pending notification**: a durable operation intent bound to its approved revision or head, recipient role and operation key. Accepted, acknowledged and completed are separate states.

**Mechanical due detection**: finding candidate work from complete records and written rules. It supplies no judgment, permission or missing support; uncertain work is recorded or refused.
