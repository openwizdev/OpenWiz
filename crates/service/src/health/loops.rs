//! LP4's pure watchdog planner. No scheduler, I/O, persistence or notification
//! delivery. Inputs must come from independently verified observations; this
//! module supplies no production observer or failure-disable policy.
use openwiz_core::messaging::OpId;
use std::{collections::BTreeSet, num::NonZeroU64};

/// Unknown is never equivalent to a healthy observation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Evidence<T> {
    Known(T),
    Unknown,
}

/// An in-progress check, with its original admission time and the time limit
/// from its immutable definition. An update time cannot extend that limit.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Checking {
    pub run_id: OpId,
    pub started_at_ms: u64,
    pub timeout_ms: NonZeroU64,
}

/// A typed projection, not a wire format. Each Known field must be complete
/// for this loop. Missing/partial history or an unavailable immutable timeout
/// must be Unknown, never an empty list. A held scheduler proposal is not an
/// admission and must not advance next_due_at_ms.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Observation {
    pub loop_id: OpId,
    /// Oldest unadmitted scheduled occurrence. None means no scheduled check
    /// is expected (e.g. event wake, completed once, or deliberately off).
    pub next_due_at_ms: Evidence<Option<u64>>,
    pub checking: Evidence<Vec<Checking>>,
    /// Positive provenance is required. Off plus historical failures is not
    /// evidence of this state. No threshold or off-reason inference is made.
    pub disabled_by_failures: Evidence<bool>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Kind {
    Missed,
    Stuck,
    DisabledByFailures,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Fault {
    Missed {
        due_at_ms: u64,
    },
    Stuck {
        run_id: OpId,
        started_at_ms: u64,
        timeout_ms: NonZeroU64,
    },
    DisabledByFailures,
}
impl Fault {
    pub fn kind(&self) -> Kind {
        match self {
            Self::Missed { .. } => Kind::Missed,
            Self::Stuck { .. } => Kind::Stuck,
            Self::DisabledByFailures => Kind::DisabledByFailures,
        }
    }
}

/// Identity is the loop and exact problem, never the time it was observed.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Problem {
    pub loop_id: OpId,
    pub fault: Fault,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Unknown {
    pub loop_id: OpId,
    pub kind: Kind,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Plan {
    /// Current known problems plus prior problems whose evidence is unknown.
    pub open: Vec<Problem>,
    /// Newly observed or changed problems only. These are planned items, not
    /// delivery receipts; durable notification integration is not implemented.
    pub needs_you: Vec<Problem>,
    pub unknown: Vec<Unknown>,
    /// The observation list itself was unavailable, even if no prior loop is known.
    pub snapshot_unknown: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PlanError {
    InvalidObservation,
}

/// Compare supplied observations with prior planner output. Strictly past a
/// due time or check limit is a problem; exactly on the boundary is not past.
/// Known healthy evidence clears a problem immediately in this pure view.
/// An unread list is Evidence::Unknown, not Known(&[]). Absent loops are
/// unknown, not proof of removal. All output is deterministic.
/// Caller-owned prior state makes repeats quiet; this is not a durable ledger.
pub fn plan(
    observations: Evidence<&[Observation]>,
    before: &[Problem],
    now_ms: u64,
) -> Result<Plan, PlanError> {
    let snapshot_unknown = matches!(observations, Evidence::Unknown);
    let observations = match observations {
        Evidence::Known(seen) => seen,
        Evidence::Unknown => &[],
    };
    let mut seen_ids = BTreeSet::new();
    let mut run_ids = BTreeSet::new();
    for seen in observations {
        if !seen_ids.insert(&seen.loop_id) {
            return Err(PlanError::InvalidObservation);
        }
        if let Evidence::Known(checks) = &seen.checking {
            for check in checks {
                if check.started_at_ms > now_ms || !run_ids.insert(&check.run_id) {
                    return Err(PlanError::InvalidObservation);
                }
            }
        }
    }
    let mut open = BTreeSet::new();
    let mut unknown = BTreeSet::new();
    for seen in observations {
        let mut add = |fault| {
            open.insert(Problem {
                loop_id: seen.loop_id.clone(),
                fault,
            });
        };
        let mut unread = |kind| {
            unknown.insert(Unknown {
                loop_id: seen.loop_id.clone(),
                kind,
            });
        };
        match seen.next_due_at_ms {
            Evidence::Known(Some(due_at_ms)) if due_at_ms < now_ms => {
                add(Fault::Missed { due_at_ms });
            }
            Evidence::Unknown => unread(Kind::Missed),
            Evidence::Known(_) => {}
        }
        match &seen.checking {
            Evidence::Known(checks) => {
                for check in checks {
                    if now_ms.saturating_sub(check.started_at_ms) > check.timeout_ms.get() {
                        add(Fault::Stuck {
                            run_id: check.run_id.clone(),
                            started_at_ms: check.started_at_ms,
                            timeout_ms: check.timeout_ms,
                        });
                    }
                }
            }
            Evidence::Unknown => unread(Kind::Stuck),
        }
        match seen.disabled_by_failures {
            Evidence::Known(true) => add(Fault::DisabledByFailures),
            Evidence::Unknown => unread(Kind::DisabledByFailures),
            Evidence::Known(false) => {}
        }
    }
    for problem in before {
        let unread = Unknown {
            loop_id: problem.loop_id.clone(),
            kind: problem.fault.kind(),
        };
        if !seen_ids.contains(&problem.loop_id) {
            unknown.insert(unread.clone());
        }
        if unknown.contains(&unread) {
            open.insert(problem.clone());
        }
    }
    let previous: BTreeSet<_> = before.iter().cloned().collect();
    Ok(Plan {
        needs_you: open.difference(&previous).cloned().collect(),
        open: open.into_iter().collect(),
        unknown: unknown.into_iter().collect(),
        snapshot_unknown,
    })
}
