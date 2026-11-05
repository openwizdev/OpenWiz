//! 0.0.12 T3 (#1098): the visual terminal app through its production shell,
//! real loopback HTTP client, ratatui's test backend and pseudo-terminals,
//! against a recording fixture server and synthetic responses only.
//! `answer`, `send` and `new_thread` are the action tickets' entrypoints
//! (T4, T5, T6): each replaces only its own file.

#[allow(dead_code)]
#[path = "../support/dirs.rs"]
mod dirs;
#[path = "../fleet/schema.rs"]
mod fleet_schema;
#[allow(dead_code)]
#[path = "../new-thread/pattern.rs"]
mod pattern;
#[allow(dead_code)]
#[path = "../support/schema.rs"]
mod schema;

mod fixtures;
mod pty;
mod render;
mod review;
mod seam;
mod shell;
mod support;
mod transport;

mod answer;
mod new_thread;
mod send;
