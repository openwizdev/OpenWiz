# OpenWiz

OpenWiz runs many coding agents at once, organized into fleets, across one project or many, with the user deciding and OpenWiz doing the running. Terms are settled in grills and recorded here as they are decided.

## Work

**Version**:
A small shippable step of a project, with at most five outcomes; done only when all its work has merged and its live check has passed. On GitHub it is a milestone.
_Avoid_: release (a release is a published version), sprint

**Spec**:
One coherent piece of a version, written after a grill; done only when every one of its tickets is done. On GitHub it is a parent issue whose body is the spec.
_Avoid_: PRD, epic

**Ticket**:
One unit of work under a spec, sized for one builder, declaring its owned paths and the tickets that block it; done only on a verified merge. On GitHub it is a sub-issue of its spec.
_Avoid_: task, story

**Plan graph**:
A spec's tickets together with their blocking edges; the user approves it as a whole, and that approval launches its fleet.
_Avoid_: backlog, ticket list

**Owned paths**:
The files and folders a ticket may change; tickets that run at the same time normally own disjoint paths. A small file marked `(shared)` in each ticket's Owned paths may be shared when each ticket specifies and changes only its own lines; those tickets run at once with no link for sharing the file, and whichever merges second fixes the merge conflict.

**Real link**:
A link whose reason line names the behaviour the later ticket needs from the earlier one. Real links stay, as long as they need to be.

**File link**:
A link whose reason line says the two tickets only share files, and names them. The goal is zero.

**Contract-first ticket**:
The one small ticket a spec opens with, which writes the future shape: the contract, types, schemas, fixtures, and stubs with tests that later tickets fill in. It blocks the tickets that rely on it, with real links naming what they use; only a spec with no shared interface skips it.

**Startable share**:
The tickets that can start (no open native blocker), of the open approved tickets.

**Ready stock**:
The open approved tickets that can start, have no builder running, aren't held and aren't waiting on the user. The factory is fed while the ready stock is at least twice the builders running.

**Forward**:
Work that adds something a user can do: a version's tickets. Outward work (users, landing, docs, launch) counts as forward for now.

**Sideways**:
Work that makes the factory itself faster, cheaper or safer: the side specs, such as CI, releases, scale and tooling.

**Backwards**:
Work that hardens what already shipped: bug fixes, missing tests, stale docs and review follow-ups, the polish queue.

**Verified merge**:
A merge that OpenWiz has read back from GitHub; only this, never an approval, a ready pull request or a closed issue, counts as merged.

## Agents

**Project**:
One codebase with one repository, one orchestrator and any number of fleets.

**Orchestrator**:
The one agent per project that grills with the user, plans, launches fleets, routes reviews and merges by the standing rules; it never builds or reviews.
_Avoid_: manager, lead

**Fleet**:
The agents working one spec's plan graph, launched together when the user approves it; a project runs any number of fleets at once, and there is no artificial cap on their size.
_Avoid_: swarm, team, crew

**Agent**:
One CloudRoom thread doing one role for one ticket or fleet.
_Avoid_: bot, worker

**Builder**:
The agent that builds one ticket on its own branch and opens its pull request; it never reviews or merges.

**Reviewer**:
An independent agent, from a different model family than the builder, that reviews a pull request at its exact head and approves it or requires changes; it never edits.

## Decisions

**Grill**:
A focused interview in rounds that settles a design before anything is written down; its answers are saved here and in `docs/adr/`.
_Avoid_: brainstorm, interview

**Skill**:
A Markdown instruction file that any agent, in any harness, can invoke to do one step of the factory the same way every time.

**Standing approval**:
A recorded, still-valid permission from the user that lets the orchestrator take a gated step without asking again.
_Avoid_: blanket approval

**Record claim**:
Admission of one immutable GitHub-first record using an atomic create-if-absent
reference, scoped to a repository, spec, generation and operation. A duplicate
reference refuses another admission. The claim does not fence a subsequent
external effect or replace an approval. See [ops record/claim v1](contracts/ops-dispatch.v1.md).

**Generation**:
A monotonically increasing record-ownership number for one repository/spec.
Only complete current claim history identifies the record owner. A generation
that an effect endpoint never enforces cannot exclude a stale external caller.

**Effect boundary**:
The actual door that performs a start, delivery, label release or merge. Its
generation and operation enforcement must be established separately from record
admission; an unavailable or unfenced ops effect stays disabled. P5 remains
Unverified under OB-A1.

**Pending notification**:
The durable operation intent itself, bound to its approved revision or head,
destination role and stable operation key. Transport acceptance, the intended
recipient's checked acknowledgement and verified completion are separate states.

**Mechanical due detection**:
Finding candidate work from complete records and written predicates. It does
not supply an agent's scope judgment, permission to act, or missing endpoint
support. Agents record/refuse uncertain or unsupported work and end the pass.

**Correction round**:
One builder fix and one reviewer re-check of one review finding; each finding gets two, then the orchestrator's diagnosis, then one more, then the user decides.
_Avoid_: iteration, retry

**Live check**:
The short test of a version on the user's real account and machine, sized to its risk, that a version needs before it is done.
_Avoid_: QA, acceptance run

**huntr**:
The skill and its loop that find work nobody planned (bugs, flaky tests, missing tests, stale docs) and approve it themselves, under the kinds the user approved once; anything bigger goes to the user as a proposal.
_Avoid_: found work, self-approved work, autonomous work
