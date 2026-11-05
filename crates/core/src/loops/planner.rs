use super::*;
use std::collections::{BTreeMap, BTreeSet};

impl Snapshot {
    /// Plan delivered `(loop_id, event, event_id)` occurrences alongside schedules.
    /// Event checks share scheduled checks' capacity, priority and hold rules.
    /// Deliveries are observed at `now_ms`; ties use loop ID then event identity.
    /// Duplicate and already-recorded occurrences are not checked again, even
    /// across revisions. Unknown loops, mismatched wakes and invalid event IDs
    /// reject the whole pass. Save each admitted identity before any effect.
    /// An empty delivery list is equivalent to `plan`.
    pub fn plan_with_events(
        &self,
        delivered: &[(OpId, Event, NonEmpty)],
        now_ms: u64,
        limits: &Limits,
    ) -> Result<Plan, PlanError> {
        plan_delivered(self, delivered, now_ms, limits)
    }
}

/// Plan the next pass from supplied observations; never read time or do I/O.
pub fn plan(snapshot: &Snapshot, now_ms: u64, limits: &Limits) -> Result<Plan, PlanError> {
    snapshot.plan_with_events(&[], now_ms, limits)
}

fn plan_delivered(
    snapshot: &Snapshot,
    delivered: &[(OpId, Event, NonEmpty)],
    now_ms: u64,
    limits: &Limits,
) -> Result<Plan, PlanError> {
    validate(snapshot, now_ms, limits)?;
    let definitions: BTreeMap<_, _> = snapshot.definitions.iter().map(|d| (&d.id, d)).collect();
    let mut checks = Used::default();
    let mut agent_ids = BTreeSet::new();
    let mut work_pending = BTreeSet::new();
    for run in &snapshot.runs {
        if run.result == RunResult::Deferred
            && definitions.get(&run.loop_id).is_some_and(|d| {
                d.revision == run.definition_revision
                    && d.mode == Mode::Active
                    && d.budget.max_agent_starts > 0
            })
        {
            work_pending.insert(&run.loop_id);
        }
        if run.result == RunResult::Checking {
            checks.add(run.priority);
        }
        if matches!(
            run.result,
            RunResult::Dispatching { .. } | RunResult::Uncertain { .. }
        ) {
            agent_ids.insert(&run.id);
        }
    }
    if let Some(active) = &snapshot.active_agents {
        agent_ids.extend(active.iter().map(|a| &a.run_id));
    }
    let mut agents = Used::default();
    for run in &snapshot.runs {
        if agent_ids.contains(&run.id) {
            agents.add(run.priority);
        }
    }
    let mut charged: BTreeMap<OpId, usize> = BTreeMap::new();
    for run in &snapshot.runs {
        if let Some(definition) = definitions.get(&run.loop_id)
            && run.result.dispatch_at_ms().is_some_and(|at| {
                now_ms
                    .checked_sub(at)
                    .is_some_and(|age| age < definition.budget.window_ms.get())
            })
        {
            *charged.entry(run.loop_id.clone()).or_default() += 1;
        }
    }
    // A recorded late admission covers [original due, admission time].
    // Keep those ranges, rather than an update-time or global watermark:
    // a later run must not erase an earlier uncovered occurrence.
    let mut covered: BTreeMap<&OpId, Vec<(u64, u64)>> = BTreeMap::new();
    for run in &snapshot.runs {
        if let Occurrence::Scheduled { due_at_ms } = run.wake {
            covered
                .entry(&run.loop_id)
                .or_default()
                .push((due_at_ms, run.started_at_ms));
        }
    }
    for ranges in covered.values_mut() {
        ranges.sort_unstable();
    }
    let mut candidates = Vec::new();
    for definition in &snapshot.definitions {
        let ranges = covered.get(&definition.id).map_or(&[][..], Vec::as_slice);
        if let Some(at_ms) = next_scheduled(&definition.wake, ranges, now_ms) {
            candidates.push(Candidate {
                priority: definition.priority,
                at_ms,
                loop_id: definition.id.clone(),
                action: Action::Check {
                    loop_id: definition.id.clone(),
                    revision: definition.revision.clone(),
                    occurrence: Occurrence::Scheduled { due_at_ms: at_ms },
                },
            });
        }
    }
    let mut seen_events: BTreeSet<_> = snapshot
        .runs
        .iter()
        .filter(|r| matches!(r.wake, Occurrence::Event { .. }))
        .map(|r| (r.loop_id.clone(), r.wake.clone()))
        .collect();
    for (loop_id, event, event_id) in delivered {
        let occurrence = Occurrence::Event {
            event: *event,
            event_id: event_id.clone(),
        };
        let definition = definitions
            .get(loop_id)
            .filter(|d| valid_text(event_id) && matches_wake(&d.wake, &occurrence))
            .ok_or(PlanError::InvalidSnapshot)?;
        if seen_events.insert((loop_id.clone(), occurrence.clone())) {
            candidates.push(Candidate {
                priority: definition.priority,
                at_ms: now_ms,
                loop_id: loop_id.clone(),
                action: Action::Check {
                    loop_id: loop_id.clone(),
                    revision: definition.revision.clone(),
                    occurrence,
                },
            });
        }
    }
    for run in &snapshot.runs {
        if run.result == RunResult::Deferred {
            candidates.push(Candidate {
                priority: run.priority,
                at_ms: match run.wake {
                    Occurrence::Scheduled { due_at_ms } => due_at_ms,
                    Occurrence::Event { .. } => run.started_at_ms,
                },
                loop_id: run.loop_id.clone(),
                action: Action::Dispatch {
                    run_id: run.id.clone(),
                },
            });
        }
    }
    candidates.sort_by(|a, b| {
        (a.priority, a.at_ms, &a.loop_id, a.run_id())
            .cmp(&(b.priority, b.at_ms, &b.loop_id, b.run_id()))
            .then_with(|| a.occurrence().cmp(&b.occurrence()))
    });
    let runs: BTreeMap<_, _> = snapshot.runs.iter().map(|r| (&r.id, r)).collect();
    let mut out = Plan::default();
    for candidate in candidates {
        let definition = definitions.get(&candidate.loop_id).copied();
        let reason = match (&candidate.action, definition) {
            (_, None) => Some(HoldReason::DefinitionMissing),
            (_, Some(d)) if !d.enabled => Some(HoldReason::Disabled),
            (Action::Check { .. }, Some(_)) if work_pending.contains(&candidate.loop_id) => {
                Some(HoldReason::WorkPending)
            }
            (Action::Check { .. }, Some(_)) => (!checks.admit(candidate.priority, limits.checks))
                .then_some(HoldReason::CheckCapacity),
            (Action::Dispatch { run_id }, Some(d)) => {
                let run = runs[run_id];
                let charge = charged.entry(d.id.clone()).or_default();
                if run.definition_revision != d.revision {
                    Some(HoldReason::RevisionChanged)
                } else if d.mode == Mode::Shadow {
                    Some(HoldReason::Shadow)
                } else if *charge >= d.budget.max_agent_starts {
                    Some(HoldReason::Budget)
                } else if snapshot.active_agents.is_none() {
                    Some(HoldReason::AgentOccupancyUnknown)
                } else if !agents.admit(candidate.priority, limits.agents) {
                    Some(HoldReason::AgentCapacity)
                } else {
                    *charge += 1;
                    None
                }
            }
        };
        if let Some(reason) = reason {
            out.held.push(Held {
                action: candidate.action,
                reason,
            });
        } else {
            out.due.push(candidate.action);
        }
    }
    Ok(out)
}

/// Oldest uncovered occurrence, at most one per loop per pass (#544's
/// recorded policy). A saved admission coalesces the intervening ticks;
/// holding a proposal without saving a run never consumes them. Work is
/// bounded by the saved records, never by the number of missed periods.
fn next_scheduled(wake: &Wake, covered: &[(u64, u64)], now_ms: u64) -> Option<u64> {
    match *wake {
        Wake::Once { at_ms } => {
            (at_ms <= now_ms && !covered.iter().any(|(due, _)| *due == at_ms)).then_some(at_ms)
        }
        Wake::Interval {
            every_ms,
            anchor_ms,
        } => {
            let mut due = anchor_ms;
            for &(from, through) in covered {
                if from > due {
                    break;
                }
                if through >= due {
                    // due >= anchor and through >= due: subtraction is safe.
                    let until_next = every_ms.get() - (through - anchor_ms) % every_ms;
                    due = through.checked_add(until_next)?;
                }
            }
            (due <= now_ms).then_some(due)
        }
        Wake::Event { .. } => None,
    }
}

struct Candidate {
    priority: Priority,
    at_ms: u64,
    loop_id: OpId,
    action: Action,
}
impl Candidate {
    fn occurrence(&self) -> Option<&Occurrence> {
        match &self.action {
            Action::Check { occurrence, .. } => Some(occurrence),
            _ => None,
        }
    }
    fn run_id(&self) -> Option<&OpId> {
        match &self.action {
            Action::Dispatch { run_id } => Some(run_id),
            _ => None,
        }
    }
}
impl RunResult {
    /// The saved mark never comes from an outcome's later update time.
    pub fn dispatch_at_ms(self) -> Option<u64> {
        match self {
            Self::Dispatching { dispatch_at_ms }
            | Self::Created { dispatch_at_ms }
            | Self::NotCreated { dispatch_at_ms }
            | Self::Uncertain { dispatch_at_ms } => Some(dispatch_at_ms),
            _ => None,
        }
    }
}
#[derive(Default)]
struct Used {
    total: usize,
    normal: usize,
}
impl Used {
    fn add(&mut self, priority: Priority) {
        self.total += 1;
        self.normal += usize::from(priority == Priority::Normal);
    }
    fn admit(&mut self, priority: Priority, capacity: Capacity) -> bool {
        if self.total >= capacity.max
            || (priority == Priority::Normal
                && self.normal >= capacity.max.saturating_sub(capacity.urgent_reserve))
        {
            return false;
        }
        self.add(priority);
        true
    }
}

/// Reject ambiguous projections globally before admitting any effects.
fn validate(snapshot: &Snapshot, now_ms: u64, limits: &Limits) -> Result<(), PlanError> {
    if [limits.checks, limits.agents]
        .iter()
        .any(|c| c.urgent_reserve > c.max)
    {
        return Err(PlanError::InvalidLimits);
    }
    let mut definitions = BTreeMap::new();
    for d in &snapshot.definitions {
        if !valid_text(&d.revision) || definitions.insert(&d.id, d).is_some() {
            return Err(PlanError::InvalidSnapshot);
        }
    }
    let mut runs = BTreeMap::new();
    let mut occurrences = BTreeSet::new();
    for r in &snapshot.runs {
        let bad_occurrence = match &r.wake {
            Occurrence::Scheduled { due_at_ms } => *due_at_ms > r.started_at_ms,
            Occurrence::Event { event_id, .. } => !valid_text(event_id),
        };
        let bad_dispatch = r
            .result
            .dispatch_at_ms()
            .is_some_and(|at| at < r.started_at_ms || at > r.updated_at_ms);
        let bad_definition = definitions.get(&r.loop_id).is_some_and(|d| {
            d.revision == r.definition_revision
                && (d.priority != r.priority || !matches_wake(&d.wake, &r.wake))
        });
        if !valid_text(&r.definition_revision)
            || r.started_at_ms > r.updated_at_ms
            || r.updated_at_ms > now_ms
            || bad_occurrence
            || bad_dispatch
            || bad_definition
            || runs.insert(&r.id, r).is_some()
            || !occurrences.insert((&r.loop_id, &r.wake))
        {
            return Err(PlanError::InvalidSnapshot);
        }
    }
    let mut active = BTreeSet::new();
    for agent in snapshot.active_agents.iter().flatten() {
        if !active.insert(&agent.run_id)
            || !runs.get(&agent.run_id).is_some_and(|r| {
                matches!(
                    r.result,
                    RunResult::Created { .. }
                        | RunResult::Dispatching { .. }
                        | RunResult::Uncertain { .. }
                )
            })
        {
            return Err(PlanError::InvalidSnapshot);
        }
    }
    Ok(())
}
fn valid_text(text: &NonEmpty) -> bool {
    !text.as_str().trim().is_empty() && !text.as_str().contains('\0')
}
fn matches_wake(wake: &Wake, occurrence: &Occurrence) -> bool {
    match (wake, occurrence) {
        (Wake::Once { at_ms }, Occurrence::Scheduled { due_at_ms }) => at_ms == due_at_ms,
        (
            Wake::Interval {
                every_ms,
                anchor_ms,
            },
            Occurrence::Scheduled { due_at_ms },
        ) => due_at_ms
            .checked_sub(*anchor_ms)
            .is_some_and(|n| n % every_ms.get() == 0),
        (
            Wake::Event { event },
            Occurrence::Event {
                event: observed, ..
            },
        ) => event == observed,
        _ => false,
    }
}
