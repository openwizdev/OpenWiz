//! A ticket's builder and reviewer threads, tied only through the verified
//! chain: thread, branch, pull request, `Closes #N` (A6, ClosedWiz#114;
//! `contracts/fleet.v1.md`, "A ticket's agents: the verified chain" and
//! "Unplaced").
//!
//! [`place`] works the chain out for every ticket of one fleet at once,
//! from the envelope's read records, and nothing else: **the ticket → its
//! pull request (`pr_discovery`) → that pull request's head branch → the
//! one thread with that branch.** A thread's branch is its `workspace` read
//! (a Cloud thread) or the thread list's `branch` (a local one), compared
//! byte for byte: a near miss is no match, and a branch's name never ties
//! it to a ticket by itself. **A doubtful link places nothing:** a thread is
//! placed only on the one ticket whose pull request (open or merged) has
//! the thread's branch as its head branch, only when that pull request
//! closes that ticket alone, and only when no other listed thread has that
//! branch. So a thread is placed at most once.
//!
//! **The read rule** (`fleet.v1.md`, "The rule"): every builder and
//! `unplaced` require the projects, the threads, the fleet's tickets, each
//! ticket's pull request and each Cloud thread's branch. When any of those
//! reads is incomplete, every one of them is unread, naming exactly the
//! incomplete ones in the order of `reads`. A required read missing from the
//! record, or on it twice, is refused ([`RecordError`]): the producer must
//! record a read it didn't make as failed.
//!
//! **No chain places a reviewer** ([`reviewer`]): a reviewer doesn't push to
//! the pull request's branch, and every verdict comment is by the owner's
//! account.

use super::model::{
    ListOutcome, MergedPr, NonEmpty, Number, Outcome, PullRequest, Read, ReadKind, Reviewer,
    Thread, Unplaced, UnplacedReason, WorkedOut,
};

/// Why every ticket's `reviewer` is undefined in version 1.
pub const REVIEWER_REASON: &str = "no verified chain places a reviewer in version 1";

/// A ticket's reviewer: always undefined in version 1.
pub fn reviewer() -> Reviewer {
    Reviewer::Undefined(NonEmpty::new(REVIEWER_REASON).expect("the reason is not empty"))
}

/// The verified chain for every ticket of one fleet at once: what each
/// `builder` and `unplaced` read (`fleet.v1.md`'s `placements`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Placements {
    chain: WorkedOut<Chain>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct Chain {
    /// Each placed thread, and the one ticket it is placed on.
    builders: Vec<(Number, NonEmpty)>,
    /// Every other listed thread, in the thread list's order.
    unplaced: Vec<Unplaced>,
}

impl Placements {
    /// `ticket`'s builder: the one thread the chain places on it, or
    /// `Known(None)` when none is placed (never that none exists).
    pub fn builder(&self, ticket: Number) -> WorkedOut<Option<NonEmpty>> {
        match &self.chain {
            WorkedOut::Known(chain) => WorkedOut::Known(
                chain
                    .builders
                    .iter()
                    .find(|(placed_on, _)| *placed_on == ticket)
                    .map(|(_, thread)| thread.clone()),
            ),
            WorkedOut::Unread(ids) => WorkedOut::Unread(ids.clone()),
        }
    }

    /// The listed threads that are no ticket's builder, in the thread
    /// list's order, each with the first reason that applies.
    pub fn unplaced(&self) -> WorkedOut<Vec<Unplaced>> {
        match &self.chain {
            WorkedOut::Known(chain) => WorkedOut::Known(chain.unplaced.clone()),
            WorkedOut::Unread(ids) => WorkedOut::Unread(ids.clone()),
        }
    }
}

/// A read the placements require, by its kind and subject.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Needed {
    Projects,
    Threads,
    /// The fleet's tickets.
    SubIssues(Number),
    /// A ticket's pull request.
    PrDiscovery(Number),
    /// A Cloud thread's branch.
    Workspace(NonEmpty),
}

/// The record breaks the read rule, so nothing is placed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RecordError {
    /// A required read isn't on the record (the producer must record a read
    /// it didn't make as failed).
    Missing(Needed),
    /// A required read is on the record more than once: which one holds
    /// can't be told.
    Repeated(Needed),
}

/// The placements of fleet `spec`, worked out from the envelope's `reads`
/// alone.
pub fn place(spec: Number, reads: &[Read]) -> Result<Placements, RecordError> {
    let found = Found::on(spec, reads)?;
    let mut unread: Vec<usize> = found.required.clone();
    unread.retain(|&at| !is_complete(&reads[at].kind));
    unread.sort_unstable();
    unread.dedup();
    // The chain is worked out only from complete reads: `chain` gives
    // nothing when one isn't, so an incomplete read can never show as a
    // fact (no branch, no pull request).
    let chain = match found.chain() {
        Some(chain) if unread.is_empty() => WorkedOut::Known(chain),
        _ => WorkedOut::Unread(unread.iter().map(|&at| reads[at].id).collect()),
    };
    Ok(Placements { chain })
}

/// The reads the chain requires, each found once on the record.
struct Found<'a> {
    /// Where each required read is in `reads`.
    required: Vec<usize>,
    /// Each ticket's pull request read, in the ticket list's order.
    prs: Vec<(Number, &'a Outcome<Option<PullRequest>>)>,
    /// Each listed thread and its branch, in the thread list's order.
    threads: Vec<(&'a NonEmpty, Branch<'a>)>,
}

/// Where a thread's branch is.
enum Branch<'a> {
    /// The thread list's own (a local thread).
    Listed(Option<&'a NonEmpty>),
    /// Its `workspace` read (a Cloud thread).
    Workspace(&'a Outcome<NonEmpty>),
}

impl<'a> Found<'a> {
    fn on(spec: Number, reads: &'a [Read]) -> Result<Self, RecordError> {
        let mut required = Vec::new();

        let (at, tickets) = one(reads, Needed::SubIssues(spec), |kind| match kind {
            ReadKind::SubIssues { spec: s, outcome } if *s == spec => Some(outcome),
            _ => None,
        })?;
        required.push(at);
        let mut prs = Vec::new();
        for &ticket in listed(tickets) {
            let (at, pr) = one(reads, Needed::PrDiscovery(ticket), |kind| match kind {
                ReadKind::PrDiscovery { issue, outcome } if *issue == ticket => Some(outcome),
                _ => None,
            })?;
            required.push(at);
            prs.push((ticket, pr));
        }

        let (at, _) = one(reads, Needed::Projects, |kind| match kind {
            ReadKind::Projects { outcome } => Some(outcome),
            _ => None,
        })?;
        required.push(at);
        let (at, listed_threads) = one(reads, Needed::Threads, |kind| match kind {
            ReadKind::Threads { outcome } => Some(outcome),
            _ => None,
        })?;
        required.push(at);
        let mut threads = Vec::new();
        for row in listed(listed_threads) {
            match row {
                Thread::Local { thread, branch, .. } => {
                    threads.push((thread, Branch::Listed(branch.as_ref())));
                }
                Thread::Cloud { thread, .. } => {
                    let need = Needed::Workspace(thread.clone());
                    let (at, branch) = one(reads, need, |kind| match kind {
                        ReadKind::Workspace { thread: t, outcome } if t == thread => Some(outcome),
                        _ => None,
                    })?;
                    required.push(at);
                    threads.push((thread, Branch::Workspace(branch)));
                }
            }
        }

        Ok(Self {
            required,
            prs,
            threads,
        })
    }

    /// The chain, from complete reads only: `None` when a ticket's pull
    /// request or a thread's branch isn't complete.
    fn chain(&self) -> Option<Chain> {
        // Each ticket's pull request's head branch and the issues it closes,
        // when it has one open or merged pull request.
        let mut heads: Vec<(Number, &str, &[Number])> = Vec::new();
        for (ticket, pr) in &self.prs {
            let Outcome::Complete { value: pr } = pr else {
                return None;
            };
            if let Some(PullRequest::Open(fields) | PullRequest::Merged(MergedPr { fields, .. })) =
                pr
            {
                heads.push((
                    *ticket,
                    fields.head_branch.as_str(),
                    fields.closes.as_slice(),
                ));
            }
        }
        let mut branches: Vec<Option<&str>> = Vec::new();
        for (_, branch) in &self.threads {
            branches.push(match branch {
                Branch::Listed(branch) => branch.map(NonEmpty::as_str),
                Branch::Workspace(Outcome::Complete { value }) => Some(value.as_str()),
                Branch::Workspace(Outcome::Failed(_)) => return None,
            });
        }

        let mut chain = Chain {
            builders: Vec::new(),
            unplaced: Vec::new(),
        };
        for (i, (thread, _)) in self.threads.iter().enumerate() {
            let reason = match branches[i] {
                None => UnplacedReason::NoBranch,
                Some(branch) if shared(&branches, i, branch) => UnplacedReason::SharedBranch,
                Some(branch) => {
                    let headed: Vec<&(Number, &str, &[Number])> = heads
                        .iter()
                        .filter(|(_, head, _)| *head == branch)
                        .collect();
                    match headed.as_slice() {
                        [] => UnplacedReason::NoPullRequest,
                        [(ticket, _, closes)] if *closes == [*ticket] => {
                            chain.builders.push((*ticket, (*thread).clone()));
                            continue;
                        }
                        // It closes other issues too (or, against the
                        // contract, doesn't name its own ticket): doubtful.
                        [_] => UnplacedReason::SeveralIssues,
                        _ => UnplacedReason::SeveralTickets,
                    }
                }
            };
            chain.unplaced.push(Unplaced {
                thread: (*thread).clone(),
                reason,
            });
        }
        Some(chain)
    }
}

/// Whether another listed thread than the `i`th has `branch`.
fn shared(branches: &[Option<&str>], i: usize, branch: &str) -> bool {
    branches
        .iter()
        .enumerate()
        .any(|(j, other)| j != i && *other == Some(branch))
}

/// The one read on the record that `pick` recognises: where it is, and its
/// outcome. None is [`RecordError::Missing`]; more than one,
/// [`RecordError::Repeated`].
fn one<'a, T>(
    reads: &'a [Read],
    need: Needed,
    pick: impl Fn(&'a ReadKind) -> Option<&'a T>,
) -> Result<(usize, &'a T), RecordError> {
    let mut found = reads
        .iter()
        .enumerate()
        .filter_map(|(at, read)| pick(&read.kind).map(|outcome| (at, outcome)));
    match (found.next(), found.next()) {
        (Some(only), None) => Ok(only),
        (None, _) => Err(RecordError::Missing(need)),
        (Some(_), Some(_)) => Err(RecordError::Repeated(need)),
    }
}

/// What a list read listed: all of it, or the part read. A failed read
/// lists nothing, so it requires nothing it would have listed.
fn listed<T>(outcome: &ListOutcome<T>) -> &[T] {
    match outcome {
        ListOutcome::Complete { value } | ListOutcome::Partial { value, .. } => value,
        ListOutcome::Failed(_) => &[],
    }
}

/// Whether a read is complete: read in full.
fn is_complete(kind: &ReadKind) -> bool {
    fn whole<T>(outcome: &Outcome<T>) -> bool {
        matches!(outcome, Outcome::Complete { .. })
    }
    fn whole_list<T>(outcome: &ListOutcome<T>) -> bool {
        matches!(outcome, ListOutcome::Complete { .. })
    }
    match kind {
        ReadKind::Version { outcome, .. } => whole(outcome),
        ReadKind::Repository { outcome } => whole(outcome),
        ReadKind::SpecList { outcome } => whole_list(outcome),
        ReadKind::Issue { outcome, .. } => whole(outcome),
        ReadKind::SubIssues { outcome, .. } => whole_list(outcome),
        ReadKind::BlockedBy { outcome, .. } => whole_list(outcome),
        ReadKind::PrDiscovery { outcome, .. } => whole(outcome),
        ReadKind::Checks { outcome, .. } => whole_list(outcome),
        ReadKind::Comments { outcome, .. } => whole(outcome),
        ReadKind::MergeReadback { outcome, .. } => whole(outcome),
        ReadKind::Projects { outcome } => whole_list(outcome),
        ReadKind::Threads { outcome } => whole_list(outcome),
        ReadKind::Workspace { outcome, .. } => whole(outcome),
    }
}
