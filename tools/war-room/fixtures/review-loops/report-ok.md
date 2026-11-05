VERDICT: CHANGES at 4b1f0c9e2d7a5b3c8f6e1d0a9b2c4e7f5a3d1c08

Full review by Codex, Sol 6.1, Medium. CI green on this commit: build, test.

Intent: `pantry export` writes the whole cookbook to one zip file, and refuses to overwrite a file that is already there.

- **R1 [blocking]** `src/export.rs:48` (Spec) An existing `cookbook.zip` is overwritten. Fix: open it with `create_new(true)`.
  User path: a cook exports twice in one day; the second export silently replaces the first, and the first is lost.
- **R2 [blocking]** `src/server.rs:90` (Sweep) The token is written to the access log. Fix: drop the header from the log line.
  Risk: privacy: any reader of the log sees a live token.
- **R3 [polish]** `src/cli.rs:30` (Sweep) The help says "zip archive file". Fix: say "export". Polish issue: #4302.

Checked: Standards (`AGENTS.md`), Spec (#41, spec #38), full sweep.

Next: the builder fixes or disputes R1 and R2 once, then one re-check.
