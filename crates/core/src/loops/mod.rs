use std::num::NonZeroU64;

pub use crate::fleet::model::NonEmpty;
pub use crate::messaging::OpId;

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
pub struct Budget {
    pub window_ms: NonZeroU64,
    pub max_agent_starts: usize,
}

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

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Run {
    pub id: OpId,
    pub loop_id: OpId,
    pub definition_revision: NonEmpty,
    pub wake: Occurrence,
    pub started_at_ms: u64,
    pub updated_at_ms: u64,
    pub priority: Priority,
    pub result: RunResult,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ActiveAgent {
    pub run_id: OpId,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
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
pub struct Snapshot {
    pub definitions: Vec<Definition>,
    pub runs: Vec<Run>,
    pub active_agents: Option<Vec<ActiveAgent>>,
}

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

pub mod marker;
mod planner;
pub use planner::plan;
