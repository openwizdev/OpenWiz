# The app, the skills and the kernel ship as a matched set

**Status: proposed** (D1-D3 below wait on Jake's word).

On 2026-11-24 the app at openwiz.dev/app showed contradictions on a real
factory: a spec was "9 of 11 done" and had "no tickets" in the same view. The
cause that day was the app's own read, which went over GitHub's per-query
limit (fixed in openwizdev/WizSite#236). But nothing stops the same garbage
from coming back through version drift. The kernel pins WizSkills
(`wizskills.lock`). The app pins its reader to a hand-copied
`contracts/app-records.v1.md` and hand-written fixtures. A user's repository
says nothing about which skills wrote its records. Each part is tested only
against itself.

## Decision

1. **One manifest per OpenWiz release.** `release-manifest.json` sits at the
   OpenWiz root and is attached to every GitHub release. It pins three things:
   the kernel version; the WizSkills version, commit and tree (copied from
   `wizskills.lock`; CI refuses a mismatch); and the **records contract**
   version that this kernel and those skills write. The records contract
   covers every record the app reads: status notes (`openwiz:status v<N>`),
   decision records (`openwiz.decisions.v<N>`), plan links, labels and the
   `docs/agents/fleet.md` rows the app reads.
2. **Records carry their version, and so does the repository (D1).** Every
   record already names its own version, and a reader never guesses at an
   unknown one. On top of that, `setup` writes a `## OpenWiz` table to
   `docs/agents/fleet.md` with `OpenWiz`, `WizSkills` and `Records contract`
   rows, and updates it on every skills update. The app reads those rows to
   say what wrote the repository.
3. **The app reads every supported version, or says one clear thing (D2).**
   The app supports the records contract of the current release and the one
   before it. A repository on any other version, or with no rows, gets one
   banner, "This repository's records were written by WizSkills X (records
   vN); this app reads vA-vB. Update your skills: `openwiz update`", and its
   records show as unknown. Never as empty, done or a guess.
4. **The records contract has its own whole-number version (D3).** It bumps
   only on a breaking change, independent of kernel semver. Changes go
   expand, then contract: the app ships a reader for vN+1 before any release
   writes it, and drops vN-1 only when no supported release writes it.
5. **Golden fixtures come from the real writers.** WizSkills CI runs its own
   writers (status notes, decision requests, plan links, setup's `fleet.md`)
   into `fixtures/records/v<N>/` and attaches them to each WizSkills release.
   No fixture is written by hand. WizSite CI downloads the fixtures of every
   supported manifest and replays them through the app's browser harness. The
   OpenWiz release candidate refuses a manifest whose fixtures fail in the
   deployed app.

## Consequences

- One update path: `openwiz update` moves the kernel, the skills and the
  repository's rows together. The app tells a stale repository to run it.
- A skills change that alters a record fails WizSite CI before it can ship.
- Hand-written app fixtures stay only for the app's own failure cases (GitHub
  limits, partial reads), not for the record shapes.

## Open: one ask to Jake

- **D1** Where a repository says what wrote it: rows in `docs/agents/fleet.md`
  (recommended; setup already owns that file) or a new `.openwiz/manifest.json`.
- **D2** The support window: current and previous records contract
  (recommended), or every version forever.
- **D3** Records-contract versioning: its own whole number, bumped only on
  breaking changes (recommended), or tied to the OpenWiz version.

Source: P0 brief from the orchestrator, 2026-11-24 (Jake's call to pin the
three parts); private record to follow on Jake's word.
