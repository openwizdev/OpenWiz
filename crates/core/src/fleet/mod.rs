//! Fleets (OpenWiz 0.0.6, spec 1, ClosedWiz#107): the read model behind
//! `openwiz fleets` and `openwiz fleet <spec>`, the `openwiz.fleet.v1`
//! contract (`contracts/fleet.v1.md`). It joins what GitHub says with
//! CloudRoom's threads: project, fleet, ticket, agent.
//!
//! Like the rest of the core, it does no I/O and no formatting.
//!
//! [`model`] holds the contract's types, data only, which every ticket
//! builds on (A3, #111).
//!
//! **One file per ticket** (A3, #111, made the seams), so no two tickets
//! edit the same file. Each is empty until its ticket fills it:
//! - [`fleets`]: A4 (#112), every fleet and its progress;
//! - [`tickets`]: A5 (#113), one fleet's tickets and their states;
//! - [`agents`]: A6 (#114), a ticket's agents, tied only through the
//!   verified chain.
//! - [`starts`]: spec 2's B4 (#120), starting builders and reviewers, never two.

pub mod agents;
pub mod fleets;
pub mod model;
pub mod starts;
pub mod tickets;

pub mod tick;
