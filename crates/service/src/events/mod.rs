//! Injected GitHub hints -> fresh fleet facts -> existing send operation.
//!
//! This seam has no production transport, webhook parser or default job. It
//! neither starts agents nor implements #805's transport. Callers supply
//! complete, strictly read fleet facts and the shared RelayStore backing.
pub mod intake;
mod relay;
use openwiz_core::fleet::model::{CheckResult, Commit, Number, PrFields};
use openwiz_core::fleet::starts::Repository;
use openwiz_core::fleet::tick::{self, Detail, Observed, PrInput, Rules, Snapshot, TicketFacts};
use openwiz_core::messaging::OpId;
use openwiz_core::messaging::lookup::{self, LookupResult};
use openwiz_core::messaging::record::SendStore;
use openwiz_core::messaging::send::{self, Messenger, SendReport, SendRequest, Status};
use openwiz_core::model::SessionId;
use openwiz_core::ops::Clock;
pub use relay::{RelayKey, RelayKind, RelayStore};
use std::collections::BTreeSet;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EventKind {
    PullRequestReview,
    WorkflowRun,
    CheckSuite,
    IssueComment,
}

/// Normalized data from an already trusted source, never event-body commands.
/// CI hints may name several PRs. Event IDs do not establish current facts.
#[derive(Clone, Debug)]
pub struct Event {
    pub repository: Repository,
    pub event_id: String,
    pub kind: EventKind,
    pub pull_requests: Vec<Number>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EventError {
    SourceUnavailable,
    InvalidHint,
}

pub trait EventSource {
    /// Return the next available hint, or None when drained; never wait for a
    /// periodic fleet check. Transport authentication/decoding is upstream.
    fn next(&mut self) -> Result<Option<Event>, EventError>;
}

pub struct Current {
    pub repository: Repository,
    pub snapshot: Snapshot,
}

#[derive(Clone, Copy, Debug)]
pub struct ReadError;

pub trait FleetReader: Send + Sync {
    /// Read current PR/head, owner starts and relay records, scoped to this
    /// repository. Missing/partial facts remain Unread in the tick snapshot.
    fn read_current(&self, repository: &Repository, pr: Number) -> Result<Current, ReadError>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CheckInReason {
    FactsUnread,
    OwnershipUnknown,
    DispatchUnresolved,
}

#[derive(Debug)]
pub enum RouteResult {
    Quiet,
    /// The existing send report preserves accepted/queued/uncertain, replay
    /// and recovery separately. It never claims the agent completed work.
    Send(Box<SendReport>),
    /// A handoff result for the caller; this never invents another recipient.
    CheckIn(CheckInReason),
}

pub struct Router<'a> {
    pub repository: &'a Repository,
    pub rules: &'a Rules,
    pub facts: &'a dyn FleetReader,
    pub messenger: &'a dyn Messenger,
    /// RelayStore::records(), or an injected SendStore with the same contract.
    pub sends: &'a dyn SendStore,
    pub clock: &'a dyn Clock,
}

pub type Routes = Vec<(Number, RouteResult)>;

/// One immediate source-to-router step, exposed by the service entry point.
pub fn route_next(
    router: &Router<'_>,
    source: &mut dyn EventSource,
) -> Result<Option<Routes>, EventError> {
    let Some(event) = source.next()? else {
        return Ok(None);
    };
    if &event.repository != router.repository
        || event.event_id.trim().is_empty()
        || event.event_id.contains('\0')
    {
        return Err(EventError::InvalidHint);
    }
    Ok(Some(
        event
            .pull_requests
            .into_iter()
            .collect::<BTreeSet<_>>()
            .into_iter()
            .map(|pr| (pr, router.route_pr(pr)))
            .collect(),
    ))
}

impl Router<'_> {
    /// Reconcile one PR from fresh facts even if its event was lost. This
    /// callable seam and #694's check-in client share RelayKey/RelayStore.
    pub fn route_pr(&self, number: Number) -> RouteResult {
        let Ok(mut current) = self.facts.read_current(self.repository, number) else {
            return RouteResult::CheckIn(CheckInReason::FactsUnread);
        };
        if &current.repository != self.repository {
            return RouteResult::CheckIn(CheckInReason::FactsUnread);
        }
        let Ok(now) = u64::try_from(self.clock.now().0) else {
            return RouteResult::CheckIn(CheckInReason::FactsUnread);
        };
        // The planner suppresses a Look already logged by the check-in. The
        // router still needs to see that guard, so clear only those in-memory
        // notification markers; no source record is edited or written.
        if let Observed::Complete(fleets) = &mut current.snapshot.fleets {
            for fleet in fleets {
                if let Observed::Complete(facts) = &mut fleet.facts {
                    facts.records.looked.clear();
                    for ticket in &mut facts.tickets {
                        if let Observed::Complete(facts) = &mut ticket.facts {
                            facts.records.looked.clear();
                        }
                    }
                }
            }
        }
        let (spec, ticket, facts, fields) = match placement(&current.snapshot, number) {
            Ok(placement) => placement,
            Err(reason) => return RouteResult::CheckIn(reason),
        };
        if fields.closes != [ticket] {
            return RouteResult::CheckIn(CheckInReason::OwnershipUnknown);
        }
        let Ok(plan) = tick::plan(&current.snapshot, self.rules, now) else {
            return RouteResult::CheckIn(CheckInReason::FactsUnread);
        };
        for action in plan.actions {
            if action.spec != spec || action.ticket != Some(ticket) {
                continue;
            }
            let (target, message, relay_kind) = match action.detail {
                Detail::CiFailed {
                    pr,
                    checks,
                    builder,
                    ..
                } => {
                    let failed = checks
                        .iter()
                        .filter(|c| matches!(c.result, CheckResult::Fail | CheckResult::Cancel))
                        .map(|c| c.name.as_str())
                        .collect::<Vec<_>>()
                        .join(", ");
                    let message = format!(
                        "CI failed for pull request #{number} at {} ({failed}). Read the failed job log, fix it, and hand back a new green head.",
                        pr.head_commit.as_str()
                    );
                    (builder, message, RelayKind::CiFailed)
                }
                Detail::ReviewFindings { pr, builder, .. } => (
                    builder,
                    format!(
                        "The review of pull request #{number} at {} asks for changes: read the report there. Fix or dispute each open finding, then hand back a new green head.",
                        pr.head_commit.as_str()
                    ),
                    RelayKind::ReviewFindings,
                ),
                Detail::ReCheck { pr, reviewer, .. } => (
                    reviewer,
                    format!(
                        "Re-check pull request #{number} at {}: read skills/review-ticket/SKILL.md, Re-checks.",
                        pr.head_commit.as_str()
                    ),
                    RelayKind::ReCheck,
                ),
                Detail::Look { .. } => return RouteResult::CheckIn(CheckInReason::FactsUnread),
                Detail::FirstReview { .. } | Detail::FreshReview { .. } => {
                    return RouteResult::CheckIn(CheckInReason::OwnershipUnknown);
                }
                _ => continue,
            };
            let active = if !matches!(relay_kind, RelayKind::ReCheck) {
                facts
                    .builder
                    .as_ref()
                    .is_some_and(|b| b.thread == target && !b.archived)
            } else {
                facts.reviewers.iter().any(|r| {
                    r.pr == number && r.agent.thread == target && !r.agent.archived && !r.given_up
                })
            };
            if !active {
                return RouteResult::CheckIn(CheckInReason::OwnershipUnknown);
            }
            // Both clients consult the same durable record for this key.
            let op_id = self.op_id(number, &fields.head_commit, relay_kind);
            match self.recorded(&op_id) {
                Ok(Some(report)) => return RouteResult::Send(report),
                Ok(None) => {}
                Err(reason) => return RouteResult::CheckIn(reason),
            }
            let request = SendRequest::new(SessionId(target.as_str().into()), message, op_id);
            return match send::send(self.messenger, self.sends, self.clock, &request) {
                Ok(report) => RouteResult::Send(Box::new(report)),
                Err(_) => RouteResult::CheckIn(CheckInReason::DispatchUnresolved),
            };
        }
        // External post-send records and later CI details cannot settle our
        // own unknown outcome. Expose the saved report without any provider
        // call, even if that relay is no longer planned by the check-in.
        for relay in [
            RelayKind::CiFailed,
            RelayKind::ReviewFindings,
            RelayKind::ReCheck,
        ] {
            match self.recorded(&self.op_id(number, &fields.head_commit, relay)) {
                Ok(Some(report))
                    if matches!(report.status, Status::Uncertain | Status::InProgress) =>
                {
                    return RouteResult::Send(report);
                }
                Ok(_) => {}
                Err(reason) => return RouteResult::CheckIn(reason),
            }
        }
        if facts.builder.as_ref().is_none_or(|b| b.archived) {
            RouteResult::CheckIn(CheckInReason::OwnershipUnknown)
        } else {
            RouteResult::Quiet
        }
    }

    fn op_id(&self, number: Number, head: &Commit, relay: RelayKind) -> OpId {
        RelayKey::new(self.repository.clone(), number, head.clone(), relay).op_id()
    }

    fn recorded(&self, op_id: &OpId) -> Result<Option<Box<SendReport>>, CheckInReason> {
        let record = self
            .sends
            .load(op_id)
            .map_err(|_| CheckInReason::DispatchUnresolved)?;
        let Some(record) = record else {
            return Ok(None);
        };
        let report = lookup::lookup(
            Some(self.sends),
            self.clock,
            &record.binding.target,
            op_id,
            self.messenger.tested_version(),
        )
        .map_err(|_| CheckInReason::DispatchUnresolved)?;
        match report.result {
            LookupResult::Recorded { report } => Ok(Some(report)),
            LookupResult::NoRecord => Ok(None),
            LookupResult::OtherTarget => Err(CheckInReason::DispatchUnresolved),
        }
    }
}

/// A doubtful placement anywhere in the supplied snapshot cannot establish
/// that a PR has just one owner. No title/branch/display-owner fallback.
fn placement(
    snapshot: &Snapshot,
    number: Number,
) -> Result<(Number, Number, &TicketFacts, &PrFields), CheckInReason> {
    let Observed::Complete(fleets) = &snapshot.fleets else {
        return Err(CheckInReason::FactsUnread);
    };
    let mut found = None;
    for fleet in fleets {
        let Observed::Complete(facts) = &fleet.facts else {
            return Err(CheckInReason::FactsUnread);
        };
        for ticket in &facts.tickets {
            let Observed::Complete(facts) = &ticket.facts else {
                return Err(CheckInReason::FactsUnread);
            };
            let fields = match &facts.pr {
                Some(PrInput::Open(pr)) => &pr.fields,
                Some(PrInput::Merged(merged)) => &merged.pr.fields,
                Some(PrInput::Several(prs)) if prs.contains(&number) => {
                    return Err(CheckInReason::OwnershipUnknown);
                }
                _ => continue,
            };
            if fields.number == number
                && found
                    .replace((fleet.spec, ticket.number, facts, fields))
                    .is_some()
            {
                return Err(CheckInReason::OwnershipUnknown);
            }
        }
    }
    found.ok_or(CheckInReason::OwnershipUnknown)
}
