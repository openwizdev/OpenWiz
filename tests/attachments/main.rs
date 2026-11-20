//! The kept OpenWiz 0.0.4 attachment proof cases (AP), ClosedWiz#14: the
//! core attachment and prompt rules that the start record's prompt digest
//! binds, and the allowlist's one `attachment_args` (D3 of
//! `docs/cleanup/app-table.md`). AP1, AP2's model half, AP3 and the core's
//! other rules are in its own `attachment` target
//! (`crates/core/tests/attachment/`, #810). The attachment store and
//! `openwiz attachment` went in #1264, with their cases.
//!
//! **Fixtures only.** Nothing calls `room-cli`, and fixture tests never
//! prove CloudRoom's behaviour.

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

// `pattern`, the shared schema keywords (one copy, in the new-thread target).
#[allow(dead_code)]
#[path = "../new-thread/pattern.rs"]
mod pattern;

mod ap10_no_dispatch;
mod ap11_schema;
mod parity;

// B2 (ClosedWiz#15): the rules and static checks of attachments in send
// and new_thread.
mod ad_static;
