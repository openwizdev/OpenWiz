//! The OpenWiz 0.0.4 attachment proof cases (AP), ClosedWiz#14. Each case
//! was written before the behaviour, and its first failing run is kept
//! in B1's phase 1 and phase 2 evidence records.
//!
//! **Phase 1** (the model in the core, no I/O): AP1 to AP3, AP10 and AP11's
//! schema half; `rules` holds the readiness, retention and free-disk rules.
//! **Phase 2** (staging in the store, `openwiz attachment add, ls, rm`):
//! AP4 to AP9, AP11's CLI half, AP12, AP2's store half and AP10 again; the
//! streaming SHA-256 staging hashes with (`sha256_stream`).
//!
//! **Fixtures only.** The synthetic files are written at test time into a
//! private directory outside the repository (never committed); nothing
//! calls `room-cli`, and fixture tests never prove CloudRoom's behaviour:
//! its limits and typing rules are source-read (#15's F4 to F7 and F26),
//! rechecked at the live check (AL2). `bench` runs the store and the CLI on
//! a private state directory, with a faked free-space measure and claim
//! source; `child` is this test binary run again as its own process (AP4
//! stops it at each staging step, AP6 measures its memory). `program` runs
//! the release `openwiz attachment` with the real free-space measure
//! (`/bin/df`, the one program the store may run: Jake, 2026-10-31, #14).

mod bench;
mod child;
mod support;

#[allow(dead_code)]
#[path = "../support/schema.rs"]
mod schema;

#[allow(dead_code)]
#[path = "../support/dirs.rs"]
mod dirs;

// Waiting out a forked child's copy of a file (#176).
#[allow(dead_code)]
#[path = "../support/forks.rs"]
mod forks;

// `pattern`, for the attachment schema only (Sol round 1, finding 3).
mod pattern;

mod ap01_kind;
mod ap02_limits;
mod ap03_safe_names;
mod ap04_ready;
mod ap05_originals;
mod ap06_streaming;
mod ap07_low_disk;
mod ap08_removal_expiry;
mod ap09_owner_only;
mod ap10_no_dispatch;
mod ap11_cli;
mod ap11_schema;
mod ap12_logs;
mod parity;
mod program;
mod rules;
mod sha256_stream;

// B2 (ClosedWiz#15): the rules and static checks of attachments in send
// and new_thread; their end-to-end proofs are in the messaging and
// new-thread targets, which share `staging`.
mod ad_static;
