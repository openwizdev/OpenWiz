# OpenWiz records contract, version 1 (`openwiz.records.v1`)

An index over every GitHub and repository record form the app (`openwiz.dev/app`) reads today, together with the app's support window (D2) and the records-contract versioning rule (D3). Version 1 changes no existing record shape: each record form keeps its own contract and its own marker version.

**Contract first** (#3138, MS0 of spec #3137). Downstream consumers: MS1 (#3139) generates golden fixtures for every record form listed here from the real WizSkills writers into `fixtures/records/v1/`; MS2 (#3140) writes and checks the `## OpenWiz` rows in `docs/agents/fleet.md`; MS4 (#3142) reads those rows in the app and enforces the D2 support window; MS5 (#3143) replays every supported release's golden fixtures through the app in WizSite CI.

Authority: ADR 0021 (`docs/adr/0021-app-skills-kernel-ship-as-a-matched-set.md`). Jake, 2026-11-24: approved D1-D3 for 0.1.2 ([private record](https://github.com/jparker2006/ClosedWiz/issues/3065#issuecomment-7139385706)).

## Indexed record forms (v1)

Every record form the app reads today belongs to records contract `v1`. Each carries its own marker or versioned shape; an unknown marker version in any record reads as unknown, never as empty, zero, done or a guess.

| Record form | Own marker / version | Where it lives | Source contract | What the app reads |
| --- | --- | --- | --- | --- |
| Status note | `<!-- openwiz:status v1 -->` (`openwiz:status v1`) | Issue comments by a record author | [`kernel/records.v1.md`](../kernel/records.v1.md) section 2 (`openwizdev/WizSkills` `contracts/agent-status.v1.md`) | `agent` (`builder`, `reviewer`, `fleet`), `state` (`working`, `asking`, `done`, `stopped`), `harness`, `model`, `skills`, `step`, `time`; live claim and lease rules |
| Decision request | JSON fenced block with `"schema": "openwiz.decisions.v1"` | Issue or pull request comments by a record author | [`decisions.v1.md`](decisions.v1.md) (`openwiz.decisions.v1`) | `kind` (`grill_round`, `grill_confirmation`, `spec_confirmation`, `plan_approval`), `id`, `status`, `fingerprint`, `risk`, and each variant's required fields |
| Decision answer | First line `openwiz decision answer v1` | Issue or pull request comments by the signed-in owner | `openwizdev/WizSite` `contracts/app-records.v1.md` (`openwiz.app-records.v1`) and [`decisions.v1.md`](decisions.v1.md) | Context JSON line and answer segment written and reconciled by the app |
| Plan links | `## Links` section (`openwiz.plan-links.v1`) | Ticket issue bodies, paired with GitHub native `blockedBy` links | [`plan-links.v1.md`](plan-links.v1.md) (`openwiz.plan-links.v1`) and [`kernel/records.v1.md`](../kernel/records.v1.md) section 4 | `- #<n> real: <behaviour>`, `- #<n> file: <paths>`, long form `<owner>/<repo>#<n>`, or `none` |
| Labels | `openwiz:records v1` labels | Open spec and ticket issues | [`kernel/records.v1.md`](../kernel/records.v1.md) section 1 | `spec`, `ready-for-agent`, `ready-for-human`, `needs-info`, `held`, and `wayfind:map` (excluded from Specs). No agent-progress label (`building`, `in-review`, `merged`, etc.) is ever set or read (L1) |
| Fleet OpenWiz rows | `## OpenWiz` table (`v1`) | `HEAD:docs/agents/fleet.md` | [`fleet.v1.md`](fleet.v1.md#openwiz-rows) | `OpenWiz`, `WizSkills` and `Records contract` rows identifying the set that wrote the repository's records (D1) |
| Fleet record authors | `## GitHub identity` table (`Record authors` row, `v1`) | `HEAD:docs/agents/fleet.md` | `docs/agents/fleet.md` (`## GitHub identity`) | Allowed comment authors for status notes and decision records (`openwiz[bot]`, owner login) |
| Fleet models | `## Models` table (`openwiz.models.v1`) and legacy `## Builder`..`## Fixer` tables | `HEAD:docs/agents/fleet.md` | [`models.v1.md`](models.v1.md) (`openwiz.models.v1`) | Role choices (`Orchestrator`, `Builder`, `Reviewer`, `Small builder`, `Fixer`) and follow rules |
| Models-offered snapshot | JSON object with `"schema": "openwiz.models-offered.v1"` | `HEAD:docs/agents/models-offered.json` (optional) | [`models.v1.md`](models.v1.md) ("The offered-models snapshot") | `read_at`, `label`, `state`, `harnesses`, `unavailable`, and `recommended` choices shown on the Models page |
| Grill file | No own marker; pinned by current shape as records `v1` (`# Grill: ` title, LF-only, ascending `## Round <N>` or `## Summary` / `## Summary, corrected` headings, first line `Risk: <ordinary\|live\|release\|publish>`) | `docs/grills/<name>.md` (grill pull request head or default branch) | [`decisions.v1.md`](decisions.v1.md) ("Independent grill risk locator") and `openwizdev/WizSite` `contracts/app-records.v1.md` | Latest `## Round <N>` (1–3 `**<id> - <decides>** <context>` + `➡️ <recommendation>` questions and `Risk:`) or `## Summary` (1–10 numbered lines and `Risk:`) checked against decision requests |
| Spec and ticket templates | No own marker; pinned by current shape as records `v1` (`## ` ATX section headings in issue bodies outside code blocks) | Open spec and ticket issue bodies | [`kernel/records.v1.md`](../kernel/records.v1.md) section 3 | Spec `## Changelog headline` (first non-empty line, checked against decision request `headline`) and the spec/ticket template sections (`## Problem Statement`..`## Further Notes` on specs; `## Parent`..`## Proof` and `**Relies on:**` on tickets) |
| Narrated-spec video comment | No own marker; pinned by current shape as records `v1` (`[Watch the narrated spec](https://...)` on line 1, one blank line, then `Steering by comment is off for now: tell your orchestrator what to change (stop, reset, or anything else).` or `Comment here to steer: stop, reset, or anything else.`) | Spec issue comments by a record author (separate comment, never in the spec body) | `openwizdev/WizSkills` `skills/to-spec/SKILL.md` ("4. Make the steering video") and `skills/to-spec/scripts/animatic.mjs` (`link`); `openwizdev/WizSite` `contracts/app-records.v1.md` and `app/pages/queue.js` | Latest matching comment by a record author (highest comment id) for the Queue spec card's HTTPS video player URL (`video.url`) |

Alongside these records, the app reads GitHub's own native state directly as [`kernel/records.v1.md`](../kernel/records.v1.md) section 5 defines: sub-issues, native `blockedBy` links, closing pull request references (state, draft, review decision, commit check rollup), and issue `state` / `stateReason` (`COMPLETED` vs `NOT_PLANNED` or `DUPLICATE`).

## Support window (D2)

The app holds one supported-versions table containing the **current** records-contract version and the **previous** records-contract version. While `v1` is the first and only version, the supported range is `v1` (`[1]`); once `v2` is introduced, the window is `v1`–`v2` (`[1, 2]`), and in general `[current - 1, current]`.

1. **Inside the window.** A repository whose `docs/agents/fleet.md` `## OpenWiz` table parses cleanly and carries a `Records contract` version inside the app's supported-versions table is read normally, with no update banner.
2. **Outside the window or missing rows.** A repository whose `Records contract` version is outside the window (older, newer, or invalid such as `v0`), or whose `docs/agents/fleet.md` lacks `## OpenWiz` or has a missing or malformed row, shows **exactly one** update banner:
   - names the repository's WizSkills version (or `unknown` / absent when missing or unreadable) and its records-contract version (or `unknown` / absent when missing or unreadable);
   - names the app's supported range (for example `v1` or `v1-v2`);
   - tells the user how to update: `openwiz update`.
3. **Unknown stays unknown.** When a repository is outside the support window or its `## OpenWiz` rows are missing or malformed, its records show as **unknown**, never as empty, zero, done or a guess.

## Versioning rule (D3)

1. **Whole-number version.** The records contract has its own positive whole-number version (`1`, `2`, `3`, …; written `v1`, `v2`, `v3`, … in `docs/agents/fleet.md` and `1`, `2`, `3`, … as `records_contract` in [`release-manifest.json`](release-manifest.v1.md)). It is independent of OpenWiz and WizSkills semver.
2. **Breaking changes only.** The version bumps only on a breaking change to an indexed record form. Additive, backwards-compatible changes that older readers handle safely do not bump it.
3. **Expand, then contract.**
   - **Expand:** the app ships a reader for `vN+1` while continuing to read `vN` (both inside the D2 window).
   - **Write:** only after the app supports `vN+1` does a WizSkills and OpenWiz release begin writing `vN+1` and stamping `Records contract: vN+1`.
   - **Contract:** the app drops `vN-1` only when no supported OpenWiz release writes `vN-1`.

## Golden fixtures

Golden fixtures for records contract `v<N>` live under `fixtures/records/v<N>/` in `openwizdev/WizSkills` (#3139). They are generated only by running the real WizSkills writers on synthetic inputs—never written by hand—and attached to each WizSkills release as one archive named with the records-contract version (`v<N>`). WizSite CI (#3143) reads the current and previous OpenWiz [release manifests](release-manifest.v1.md), fetches the matching WizSkills golden archives and replays every record through the app's browser harness.
