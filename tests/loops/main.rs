//! LP5, the loop on/off switches through the store, the CLI and the HTTP
//! API, on a synthetic private checkout and state. These cross crates, so
//! they stay here; the core planner's tables (LP1, LP2) moved to
//! `crates/core/tests/loops/` (TV10, #812).
mod fixture;
mod l6_cli;
mod l6_config;
mod l6_switches;
