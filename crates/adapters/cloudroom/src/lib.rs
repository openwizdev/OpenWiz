//! OpenWiz adapter for CloudRoom: reads sessions through the existing,
//! authenticated `room-cli` and translates them for the core, and makes
//! OpenWiz's two writes: `thread tell`, for `send` ([`messaging`]), and
//! `thread spawn`, for `new` ([`new_thread`], OpenWiz 0.0.4), which also
//! reads the Cloud catalogue with `cloud status`. [`fleet`] makes the
//! CloudRoom reads behind `openwiz fleet <spec>` (OpenWiz 0.0.6, A6): this
//! repository's projects, their threads, and each Cloud thread's branch.
//! OpenWiz 0.0.6 adds `thread archive`, for finished agents ([`archive`], #120).
//!
//! Every call runs with the CloudRoom thread-context variables removed from
//! its environment ([`is_scrubbed`], sheet A-15).
//!
//! Every read is one [`allowlist::Invocation`], run by `process` with a
//! 15-second timeout inside the run's deadline and no retry; [`source`]
//! translates the JSON of `room-cli` 0.43.1. Product rules (grouping,
//! visibility, paging, limits, completeness) are the core's.

pub mod allowlist;
pub mod archive;
pub mod fleet;
pub mod locate;
pub mod loops;
pub mod messaging;
pub mod new_thread;
mod process;
pub mod source;

pub use process::{KEPT_ENV, SCRUBBED_ENV, SCRUBBED_ENV_PREFIX, is_scrubbed};

/// The program the adapter runs.
pub const PROGRAM: &str = "room-cli";

/// The `room-cli` version the reads' live check ran against (0.0.1,
/// 2026-10-29). Reported, never a gate (#37): any other version is marked
/// untested. It is the reads' only (#200): `send` and `new` keep their
/// own, [`SEND_TESTED_VERSION`] and [`NEW_TESTED_VERSION`].
pub const TESTED_VERSION: &str = "v127";

/// The `room-cli` version a live `send` last passed with: none yet (#200),
/// as no send has run live, so a send reports every version as not
/// live-tested for sending, and its `tested_version` as `""`. Reported,
/// never a gate (#37). 0.0.3's live test (#10) sets it to the version it ran
/// with.
pub const SEND_TESTED_VERSION: Option<&str> = None;

/// The `room-cli` version a live `new` create last passed with: none yet
/// (#200), as no create has run live, so `new` reports every version as not
/// live-tested for new threads, and its `tested_version` as `""`. Reported,
/// never a gate (#37). 0.0.4's live test (#13) sets it to the version it
/// ran with.
pub const NEW_TESTED_VERSION: Option<&str> = None;
