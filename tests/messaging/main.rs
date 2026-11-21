mod support;

#[path = "../support/dirs.rs"]
mod dirs;

#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../support/forks.rs"]
mod forks;

#[path = "../support/counter.rs"]
mod counter;

mod m12_allowlist;
