//! The kept OpenWiz 0.0.3 messaging proofs (ClosedWiz#8): M12, the
//! allowlist's `thread tell` shape, which the engine's loop messages use.
//! `openwiz send` and its cases went in #1264.
//!
//! Every case runs against the repository's fake `room-cli`. **Nothing is
//! sent live**, and fixture tests never prove live behaviour.
//!
//! `structure` holds the checks that are not one M case: a core without
//! I/O.

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

// Reading the fake's call counters (#176).
#[allow(dead_code)]
#[path = "../support/counter.rs"]
mod counter;

mod m12_allowlist;
mod structure;
