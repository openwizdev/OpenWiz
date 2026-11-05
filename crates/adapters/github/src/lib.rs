//! OpenWiz adapter for GitHub (OpenWiz 0.0.6, spec 1, ClosedWiz#107): reads
//! a repository's specs, tickets and pull requests through the existing,
//! authenticated `gh`, and translates them for the core's fleet model.
//! Product rules are the core's.
//!
//! Every call must be an [`allowlist::Invocation`]: only an argument list
//! that one module's part of the allowlist allows can build one. The one
//! runner, [`process::run`], runs nothing else.
//!
//! **One file per ticket** (A3, #111, made the seams), each declaring its
//! own part of the allowlist: [`fleets`] (A4, #112), [`tickets`] (A5,
//! #113) and [`writes`] (spec 2's B3, #119). Every part is empty until its
//! ticket fills it, so nothing is allowed yet and the adapter runs no `gh`.

pub mod allowlist;
pub mod app;
pub mod decisions;
pub mod events;
pub mod fleets;
pub mod plan;
pub mod process;
pub mod tickets;
pub mod writes;

/// The program the adapter runs.
pub const PROGRAM: &str = "gh";

pub mod tick;
