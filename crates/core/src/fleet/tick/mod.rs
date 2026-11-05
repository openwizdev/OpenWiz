//! Pure fleet tick planning (B2, #118), following `contracts/fleet-tick.v1.md`.
//! All inputs are complete observations, supplied by B5; no I/O or implicit
//! source reads. Partial, failed or ambiguous observations must be `Unread`.
//! The planner checks authority and facts, never a precomputed ticket state.

mod rules;
pub use rules::{AgentRule, MergeRule, RequiredCheck, Rules};

mod action;
mod input;
pub use action::*;
pub use input::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PlanError {
    RepositoryUnread,
    SpecsUnread,
    InvalidSnapshot,
}

mod planner;
pub use planner::plan;
