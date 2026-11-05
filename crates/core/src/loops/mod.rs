//! Pure planning for `loops.v1` (L2, #544). These typed projections are
//! supplied after strict contract decoding; they are not a wire reader.
//! The executor verifies approval, applies durable off/on state to `enabled`,
//! and resolves each revision to the immutable definition before projecting.
//! A plan authorizes no effect: save each identity before checking or sending.
//!
//! Scheduled catch-up is oldest first, one new run per loop per pass. A late
//! run retains its original due time and coalesces later scheduled ticks
//! through `started_at_ms`; later outcome updates do not move that boundary.
//! The same saved records prevent replay after a restart. Deferred dispatches
//! reuse existing runs. Current-revision active work with a positive start
//! budget holds later checks while Deferred; permanent dispatch holds (old
//! revision, shadow or zero budget) permit checks under the shared limit.
//! Held ticks coalesce when the next check is admitted.

use std::num::NonZeroU64;

pub use crate::fleet::model::NonEmpty;
pub use crate::messaging::OpId;

/// Urgent work may use the shared reserve, but never exceed the total limit.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Priority {
    Urgent,
    Normal,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Shadow,
    Active,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Event {
    PullRequestReview,
    WorkflowRun,
    CheckSuite,
    IssueComment,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Wake {
    Interval {
        every_ms: NonZeroU64,
        anchor_ms: u64,
    },
    Once {
        at_ms: u64,
    },
    Event {
        event: Event,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Occurrence {
    Scheduled { due_at_ms: u64 },
    Event { event: Event, event_id: NonEmpty },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
/// Attempted starts in (now - window_ms, now], charged from the saved
/// dispatch mark even when the final outcome is uncertain or not_created.
pub struct Budget {
    pub window_ms: NonZeroU64,
    pub max_agent_starts: usize,
}

/// Only fields used by planning; action, authority and check arguments are
/// deliberately left with the validated definition in the executor.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Definition {
    pub id: OpId,
    pub revision: NonEmpty,
    pub wake: Wake,
    pub enabled: bool,
    pub mode: Mode,
    pub priority: Priority,
    pub budget: Budget,
}

/// Result projections retain dispatch time across every outcome update.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RunResult {
    Checking,
    Quiet,
    CheckFailed,
    CheckTimedOut,
    Shadow,
    Deferred,
    Dispatching { dispatch_at_ms: u64 },
    Created { dispatch_at_ms: u64 },
    NotCreated { dispatch_at_ms: u64 },
    Refused,
    Uncertain { dispatch_at_ms: u64 },
}

/// One current record per run, not an append-only history of its updates.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Run {
    pub id: OpId,
    pub loop_id: OpId,
    pub definition_revision: NonEmpty,
    pub wake: Occurrence,
    /// Check admission: coalesces missed interval ticks through this time.
    pub started_at_ms: u64,
    pub updated_at_ms: u64,
    /// Taken from this run's immutable definition, even after its removal.
    pub priority: Priority,
    pub result: RunResult,
}

/// Positive evidence of an agent still in flight, keyed by its run.
/// A historical `created` result alone does not establish this observation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ActiveAgent {
    pub run_id: OpId,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
/// At most `max` in flight, and at most `max - urgent_reserve` normal.
/// Urgent work can use any free slot; normal work never borrows the reserve.
pub struct Capacity {
    pub max: usize,
    pub urgent_reserve: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Limits {
    pub checks: Capacity,
    pub agents: Capacity,
}

#[derive(Clone, Debug, PartialEq, Eq)]
/// One complete snapshot: definitions and one latest record for every run
/// needed for occurrence deduplication, in-flight work and rolling budgets.
/// A partial record read must never be projected as an empty/shorter list.
pub struct Snapshot {
    pub definitions: Vec<Definition>,
    pub runs: Vec<Run>,
    /// A complete current observation, not a list of all historical creations.
    /// None means unread: hold dispatches rather than assuming zero agents.
    /// Saved dispatching/uncertain runs also occupy slots until reconciled;
    /// an observation of the same run is counted only once.
    pub active_agents: Option<Vec<ActiveAgent>>,
}

/// The executor allocates and saves an id for a Check; a Dispatch reuses
/// the existing run identity. Neither is permission to skip write gates.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Action {
    Check {
        loop_id: OpId,
        revision: NonEmpty,
        occurrence: Occurrence,
    },
    Dispatch {
        run_id: OpId,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HoldReason {
    Disabled,
    /// Current-revision active work with a positive budget is still Deferred.
    WorkPending,
    CheckCapacity,
    AgentCapacity,
    AgentOccupancyUnknown,
    Budget,
    RevisionChanged,
    DefinitionMissing,
    Shadow,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Held {
    pub action: Action,
    pub reason: HoldReason,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Plan {
    pub due: Vec<Action>,
    pub held: Vec<Held>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PlanError {
    InvalidLimits,
    InvalidSnapshot,
}

mod planner;
pub use planner::plan;
