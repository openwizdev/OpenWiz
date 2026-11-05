# #1845 proof

Evidence class: documentation contract checks, not live observations.

- RP1: agents must see the live smoke gate, post-publication hands-on feedback,
  pre-publication risky-write checks, standing approval and honest device gaps.
  `adr0019_live_smoke_and_hands_on_timing` owns that contract.
- RP2: the export instructions must gate one combined build and retain each
  included version's changelog section. `adr0019_combined_release_gate` owns it.
- RP3: agents must run the automatic allowlist, scan and claim checks, read a
  publishable report, get one Sol review, then one final approval bound to the
  exact export. `adr0019_automatic_export_and_one_final_approval` owns it.

Plausible regression: an agent follows the old per-step human go, per-version
acceptance or separate plan-approval instructions and blocks the combined
release. Existing portable-skill installation checks do not read these two
local skills. Check the operative instruction paragraphs, not scattered words
in citations. Write these checks before changing the instructions; keep their
failing run here and commit it before the fix.

ADR 0019 and the confirmed releasing grill were read from PR #1832 at
1f0fe85c72e9f49066751463d9e2493126bae83c (not on the starting main).
No public release, live call, tag or release-branch push is part of this proof.

Policy reads at starting main:
- AGENTS.md: 2b9ae846b0dd4fcb93625ae1566b448f8de0e28a
- docs/agents/fleet.md: 99aaafc6905d691c80ad413370bb4cb1f3a8f3bd
- docs/agents/helpers.md: 9a8628b0deabf3ed320b856af2f0117723fab15b

Helper: one read-only spec tracer at
b1f8894c7ce485852c6562c195a7cb61d0a391c5; six stale-instruction pointers,
independently read and used all six, ignored zero, found wrong zero. Archived.
Snapshot: retained in private helper state.
Window: retained in private helper state.
Result: clean #1845: nothing changed but the writes you named (branches 0, comments 4).

No dependencies added or changed. No later-ticket seams.

CI-readability slice: `adr0019_release_skills_are_kept_for_rust_checks`
checks both skill paths at the real classifier boundary: they must select
`web-build rust` and must not appear in Rust's prune list. The old classifier
returns `none`; the failing run is `1845-ci-red.log`. The exact one-row classifier
fix was granted in #1845 comment 6705163465 and is now applied above the
general unread row. No other classifier or skip rule is changed; O9
empty-list compatibility and X5 workflow/sparse retention remain with their
owning tickets. No assertions in the committed retention proof were widened.
