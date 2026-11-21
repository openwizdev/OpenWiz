mod support;

#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../support/schema.rs"]
mod schema;

#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../support/dirs.rs"]
mod dirs;

#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../support/forks.rs"]
mod forks;

#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../new-thread/pattern.rs"]
mod pattern;

mod parity;

mod ad_static;
