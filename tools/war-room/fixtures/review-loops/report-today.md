VERDICT: CHANGES at 4b1f0c9e2d7a5b3c8f6e1d0a9b2c4e7f5a3d1c08

Full review by Codex, Sol 6.1, Medium. CI green on this commit: build, test.

Intent: `pantry export` writes the whole cookbook to one zip file, and refuses to overwrite a file that is already there.

- **R1 [high]** `src/export.rs:48` (Spec) An existing `cookbook.zip` is overwritten without a word, so the user loses their last export; the ticket says export refuses. Fix: open the file with `create_new(true)`, and exit with status 3 when it exists.
  Shows the break: `touch cookbook.zip && pantry export; echo $?` printed `0`; the ticket needs `3`, with the file unchanged. Rerun at this commit: same.
- **R2 [medium]** `tests/export.rs:12` (Standards) The test now skips `.webp` photos, which relaxes the "every file is exported" check; the ticket didn't ask for it. Fix: drop the skip.
- **R4 [low]** `src/cli.rs:30` (Sweep) The help says "zip archive file", where the glossary's word is "export". Fix: "Write the cookbook as one export (a zip file)." Follow-up: #58.

Checked: Standards (`AGENTS.md`, `docs/agents/`, ADR 0002), Spec (#41, spec #38), full sweep.

Next: the builder fixes R1 and R2, or disputes any of them once. R4 doesn't block.
