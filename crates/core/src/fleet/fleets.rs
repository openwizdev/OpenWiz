//! Every fleet in a project, with its progress (A4, ClosedWiz#112): the
//! `fleets` view of `openwiz.fleet.v1` (`contracts/fleet.v1.md`), worked
//! out from what a [`FleetsSource`] answers. Like the rest of the core, no
//! I/O and no formatting: the GitHub adapter makes the calls and reads
//! their answers strictly; this file decides what they mean.
//!
//! **A fleet** is an open issue with at least one sub-issue (a spec): the
//! contract carries no approval in version 1, so it lists every one
//! (#112, question 2). Its tickets are its sub-issues; their blockers are
//! the issues their blocked-by links name.
//!
//! **The reads.** One issue list and one pull request list read the whole
//! repository, so the issue, sub-issue, blocked-by and pull request records
//! all come from two calls; only an open pull request's checks and
//! comments need separate calls. Merge readbacks share bounded ancestry batches. Those
//! run at most [`MAX_CONCURRENT_DETAIL_READS`] at once, and none starts
//! after the run's deadline: it is recorded as failed (`budget_exhausted`),
//! never left out.
//!
//! **The values** follow the contract's one dependency table: a worked-out
//! value is known exactly when every read it requires, through every edge,
//! is complete; otherwise it names exactly the incomplete ones, in the
//! order of `reads` ([`worked`]). Known values come from [`ticket_state`]
//! (the state table), [`merged`], [`ci`], [`verdict`], [`needs_you_kinds`]
//! and [`template_line`]. All are public, so the other fleet view uses the
//! same ones and never a copy (#112, question 1 (b)).
//!
//! **Which issue is which.** GitHub links issues by number and node id; a
//! sub-issue, a blocker or a closing reference can be in another
//! repository, with a number this one also has. So every link is checked
//! against this repository's issue list by both: a link the list doesn't
//! hold as the same issue (another repository's, or one a list cut short
//! leaves out) makes the read that named it fail, never a guess at another
//! issue's facts.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::Mutex;
use std::sync::atomic::{self, AtomicUsize};
use std::thread;
use std::time::{Duration, Instant};

use crate::envelope::{Completeness, GapKind};
use crate::limits::MAX_CONCURRENT_DETAIL_READS;
use crate::model::{Fact, Timestamp};
use crate::ops::{Clock, NOT_READ_BUDGET};

use super::model::{
    Blocker, Check, CheckResult, Commit, Counts, Coverage, Envelope, Failed, Fleet, FleetsView,
    Freshness, Gh, GitHubSource, Issue, IssueState, ListOutcome, MergedPr, Milestone, NeedsYou,
    NeedsYouKind, NeedsYouRisk, NonEmpty, Number, Outcome, PendingQuestion, PrFields, PullRequest,
    Read, ReadId, ReadKind, Repository, Review, SchemaId, SourceName, Sources, State, TicketCore,
    TicketState, Truncated, Verdict, View, WorkedOut,
};

/// The label a ticket is ready with, for an agent.
pub const READY_FOR_AGENT: &str = "ready-for-agent";
/// The label a ticket is ready with, for a person.
pub const READY_FOR_HUMAN: &str = "ready-for-human";
/// A builder's question.
pub const NEEDS_INFO: &str = "needs-info";
/// A held ticket (#155).
pub const HELD: &str = "held";

/// The most closing references `gh` reads for one pull request in a list,
/// so a pull request with this many may close more: gh v2.100.0 asks for
/// `closingIssuesReferences(first: 100)` (`api/query_builder.go`), and `pr
/// list` pages no further (only `pr view`'s finder does).
pub const MAX_CLOSING_REFERENCES: usize = 100;

/// An issue GitHub links to: its number and its node id, which tells this
/// repository's issue from another's with the same number.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Link {
    pub number: Number,
    pub id: NonEmpty,
}

/// A list of links as GitHub gives it: the ones it listed, and its own
/// total, which can be more.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Links {
    pub nodes: Vec<Link>,
    pub total: u64,
}

/// One issue of the issue list, with its links.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IssueRow {
    pub number: Number,
    pub id: NonEmpty,
    pub title: String,
    pub state: IssueState,
    pub milestone: Option<Milestone>,
    /// As read, in order.
    pub labels: Vec<NonEmpty>,
    /// Read only for its two template lines ([`template_line`]); never
    /// shown.
    pub body: String,
    pub sub_issues: Links,
    pub blocked_by: Links,
}

/// One issue comment as read; its full body is never printed in an envelope.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IssueComment {
    pub body: String,
    pub link: NonEmpty,
    pub asked_at: Timestamp,
}

/// Why the `fleets` view's Needs you items have no question facts: its one
/// repository-wide issue list does not read comments (#539: with comments it
/// outgrows the run budget). `openwiz fleet <spec>` reads them per ticket.
pub const QUESTION_NOT_READ: &str =
    "the fleets view does not read comments; openwiz fleet <spec> reads the question";

/// Why a ticket read with its comments has no question facts.
pub const QUESTION_NOT_FOUND: &str = "no unique newest needs-you or Needs you comment was found";

/// Select the newest comment whose first line starts with exactly
/// `needs-you` or `Needs you`. `comments` must be the issue's complete list
/// (`gh issue view --json comments` pages through all of them). A tie on
/// the newest time cannot establish one pending question.
pub fn pending_question(comments: &[IssueComment]) -> Option<PendingQuestion> {
    let mut marked: Vec<_> = comments
        .iter()
        .filter_map(|comment| {
            let line = comment.body.lines().next()?;
            (line.starts_with("needs-you") || line.starts_with("Needs you"))
                .then_some((comment, line))
        })
        .collect();
    marked.sort_by_key(|(comment, _)| comment.asked_at);
    let (latest, wording) = marked.pop()?;
    if marked
        .last()
        .is_some_and(|(previous, _)| previous.asked_at == latest.asked_at)
    {
        return None;
    }
    Some(PendingQuestion {
        wording: NonEmpty::new(wording)?,
        link: latest.link.clone(),
        asked_at: latest.asked_at,
    })
}

/// The same enriched item for both fleet views, based only on recorded
/// facts. `no_question` is the reason when the issue read has no question.
pub fn needs_you_item(
    kind: NeedsYouKind,
    spec: Number,
    ticket: Number,
    issue: &Issue,
    no_question: &str,
) -> NeedsYou {
    let (wording, link, asked_at) = match &issue.pending_question {
        Some(question) => (
            Fact::Known(question.wording.clone()),
            Fact::Known(question.link.clone()),
            Fact::Known(question.asked_at),
        ),
        None => (
            Fact::Unknown(no_question.to_owned()),
            Fact::Unknown(no_question.to_owned()),
            Fact::Unknown(no_question.to_owned()),
        ),
    };
    let risks: Vec<_> = issue
        .labels
        .iter()
        .filter_map(|label| match label.as_str() {
            "live" => Some(NeedsYouRisk::Live),
            "release" => Some(NeedsYouRisk::Release),
            "publish" => Some(NeedsYouRisk::Publish),
            _ => None,
        })
        .collect();
    let risk = match risks.as_slice() {
        [risk] => Fact::Known(*risk),
        [] => Fact::Unknown("no explicit risk classification was reported".to_owned()),
        _ => Fact::Unknown("risk classifications conflict".to_owned()),
    };
    NeedsYou {
        kind,
        spec,
        ticket,
        wording,
        link,
        asked_at,
        risk,
    }
}

/// One pull request of the pull request list.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PrRow {
    Open(PrFacts),
    Merged {
        facts: PrFacts,
        merge_commit: Commit,
        merged_at: Timestamp,
    },
    /// Closed without a merge: never an issue's pull request.
    Closed {
        number: Number,
    },
}

/// An open or merged pull request's own fields, and the issues it closes
/// (GitHub's closing references), as listed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PrFacts {
    pub number: Number,
    pub draft: bool,
    pub head_branch: NonEmpty,
    pub head_commit: Commit,
    pub base_branch: NonEmpty,
    pub closes: Vec<Link>,
}

/// Internal stock evidence from a PR-list read. Not serialized into the public
/// fleet envelope. Legacy providers retain an unknown title, never a false match.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StockPr {
    pub pr: PrRow,
    pub title: Fact<NonEmpty>,
}

/// A list read in one call, and whether it may be cut short: it came back
/// with as many rows as the call asks for, so there may be more.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Listed<T> {
    pub rows: Vec<T>,
    pub cut_short: bool,
}

/// The most distinct merge/base pairs in one ancestry read.
pub const MERGE_BATCH_SIZE: usize = 20;

/// What `fleets` reads, one method per call. Each answer is already read
/// strictly; a failure is a [`Failed`] in OpenWiz's own words.
pub trait FleetsSource: Sync {
    /// The version last live-tested: reported, never a gate.
    fn tested_version(&self) -> &str;
    /// The source's version, only as a recognised version text.
    fn version(&self, deadline: Instant) -> Result<NonEmpty, Failed>;
    /// The repository's name, never its owner.
    fn repository(&self, deadline: Instant) -> Result<Repository, Failed>;
    /// Every issue of the repository, open and closed.
    fn issues(&self, deadline: Instant) -> Result<Listed<IssueRow>, Failed>;
    /// Every pull request of the repository, open, merged and closed.
    fn pull_requests(&self, deadline: Instant) -> Result<Listed<PrRow>, Failed>;
    /// Same bounded PR list with title evidence retained for stock consumers.
    fn stock_pull_requests(&self, deadline: Instant) -> Result<Listed<StockPr>, Failed> {
        self.pull_requests(deadline).map(|listed| Listed {
            cut_short: listed.cut_short,
            rows: listed
                .rows
                .into_iter()
                .map(|pr| StockPr {
                    pr,
                    title: Fact::Unknown(
                        "PR-title evidence is not retained by this provider".to_owned(),
                    ),
                })
                .collect(),
        })
    }
    /// An open pull request's checks: the latest run of each.
    fn checks(&self, pr: Number, deadline: Instant) -> Result<Vec<Check>, Failed>;
    /// An open pull request's comment bodies, oldest first.
    fn comments(&self, pr: Number, deadline: Instant) -> Result<Vec<String>, Failed>;
    /// Whether a merged pull request's merge commit is on its base branch.
    fn on_base(&self, pr: &MergedPr, deadline: Instant) -> Result<bool, Failed>;
    /// Ancestry for a bounded chunk of distinct merge/base pairs, in input
    /// order. Sources without a bulk transport retain their existing reads.
    fn on_bases(&self, prs: &[MergedPr], deadline: Instant) -> Vec<Result<bool, Failed>> {
        prs.iter().map(|pr| self.on_base(pr, deadline)).collect()
    }
}

/// `openwiz fleets`: every fleet, read within `budget`.
pub fn fleets(source: &dyn FleetsSource, clock: &dyn Clock, budget: Duration) -> Envelope {
    let mut walk = Walk {
        source,
        clock,
        deadline: clock.monotonic() + budget,
        snapshot: clock.now(),
        reads: Vec::new(),
        ids: HashMap::new(),
        jobs: Vec::new(),
        issues: None,
        prs: None,
    };
    walk.run();
    walk.envelope()
}

// ---------------------------------------------------------------------
// The known values: the contract's rules, on complete reads only.

/// A pull request's CI, worked out from its checks.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ci {
    Failed,
    Pending,
    Passed,
    /// No check, or every one skipped.
    None,
}

/// CI from the checks: `failed` if any failed or was cancelled; otherwise
/// `pending` if any is pending; otherwise `passed` if any passed; otherwise
/// `none`.
pub fn ci(checks: &[Check]) -> Ci {
    let any = |r: &[CheckResult]| checks.iter().any(|c| r.contains(&c.result));
    if any(&[CheckResult::Fail, CheckResult::Cancel]) {
        Ci::Failed
    } else if any(&[CheckResult::Pending]) {
        Ci::Pending
    } else if any(&[CheckResult::Pass]) {
        Ci::Passed
    } else {
        Ci::None
    }
}

/// The latest comment starting [`VERDICT_PREFIX`] isn't in
/// `review-ticket`'s form.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct NotAVerdict;

/// What a comment starts with to be a verdict (`review-ticket`).
pub const VERDICT_PREFIX: &str = "VERDICT: ";

/// The latest verdict among a pull request's comment bodies, oldest
/// first: the latest one starting [`VERDICT_PREFIX`], whose first line must
/// be exactly `VERDICT: APPROVE at <commit>` or `VERDICT: CHANGES at
/// <commit>` (all 40 characters; a line may end `\r\n`). `Ok(None)`: no
/// comment starts so. `Err`: the latest one isn't in that form, so no
/// verdict can be told; an older one is never used instead.
pub fn verdict(bodies: &[String]) -> Result<Option<Review>, NotAVerdict> {
    let Some(latest) = bodies.iter().rev().find(|b| b.starts_with(VERDICT_PREFIX)) else {
        return Ok(None);
    };
    let line = latest.split('\n').next().unwrap_or_default();
    let line = line.strip_suffix('\r').unwrap_or(line);
    let rest = line.strip_prefix(VERDICT_PREFIX).ok_or(NotAVerdict)?;
    let (word, commit) = rest.split_once(" at ").ok_or(NotAVerdict)?;
    let verdict = match word {
        "APPROVE" => Verdict::Approve,
        "CHANGES" => Verdict::Changes,
        _ => return Err(NotAVerdict),
    };
    let commit = Commit::parse(commit).ok_or(NotAVerdict)?;
    Ok(Some(Review { verdict, commit }))
}

/// The text after `label` on the body's one line that starts with it
/// (`**Owned paths:**`, `**Relies on:**`), trimmed: `None` when no line or
/// more than one starts with it, or it's empty.
pub fn template_line(body: &str, label: &str) -> Option<NonEmpty> {
    let mut found = body
        .split('\n')
        .map(|l| l.strip_suffix('\r').unwrap_or(l))
        .filter_map(|l| l.strip_prefix(label));
    let first = found.next()?;
    if found.next().is_some() {
        return None;
    }
    NonEmpty::new(first.trim())
}

/// A blocker's `merged`, and the state table's rule 1: its pull request is
/// merged and its merge was read back on its base. Never an approval, a
/// ready pull request or a closed issue.
pub fn merged(pr: Option<&PullRequest>, on_base: Option<bool>) -> bool {
    matches!(pr, Some(PullRequest::Merged(_))) && on_base == Some(true)
}

/// A ticket's "needs you" kinds, from its labels, in the contract's
/// order of kinds ([`needs_you_word`]): `held` for `held`, then
/// `needs_info` for `needs-info`.
pub fn needs_you_kinds(issue: &Issue) -> Vec<NeedsYouKind> {
    let has = |name: &str| issue.labels.iter().any(|l| l.as_str() == name);
    [
        (HELD, NeedsYouKind::Held),
        (NEEDS_INFO, NeedsYouKind::NeedsInfo),
    ]
    .into_iter()
    .filter(|(label, _)| has(label))
    .map(|(_, kind)| kind)
    .collect()
}

/// A "needs you" kind's contract word. "Needs you" is by spec, ticket,
/// then kind, the kinds compared as these words (#297, R1).
pub fn needs_you_word(kind: NeedsYouKind) -> &'static str {
    match kind {
        NeedsYouKind::Held => "held",
        NeedsYouKind::NeedsInfo => "needs_info",
    }
}

/// The read rule: a worked-out value is known exactly when every read in
/// `requires` is complete; otherwise it names exactly the incomplete ones,
/// in the order of `reads` (whose ids are given in that order). Every id
/// in `requires` must be on the record.
pub fn worked<T>(
    reads: &[Read],
    requires: &BTreeSet<ReadId>,
    known: impl FnOnce() -> T,
) -> WorkedOut<T> {
    let unread: Vec<ReadId> = requires
        .iter()
        .copied()
        .filter(|id| !reads.iter().any(|r| r.id == *id && is_complete(&r.kind)))
        .collect();
    if unread.is_empty() {
        WorkedOut::Known(known())
    } else {
        WorkedOut::Unread(unread)
    }
}

/// Every fact a ticket's state is worked out from, each from a complete
/// read.
#[derive(Clone, Copy, Debug)]
pub struct StateFacts<'a> {
    pub issue: &'a Issue,
    /// The `pr_discovery` read's value.
    pub pr: Option<&'a PullRequest>,
    /// An open pull request's checks.
    pub checks: Option<&'a [Check]>,
    /// An open pull request's verdict: `Some(None)`, none.
    pub review: Option<Option<&'a Review>>,
    /// A merged pull request's merge read back.
    pub on_base: Option<bool>,
    /// Each blocker's `merged`.
    pub blockers_merged: &'a [bool],
}

/// The state table (`contracts/fleet.v1.md`, "Ticket states"), in its
/// order: the first rule that matches wins. Known or unknown, with its
/// reason.
pub fn ticket_state(f: &StateFacts) -> State {
    let labelled = |name: &str| f.issue.labels.iter().any(|l| l.as_str() == name);
    let unknown = |why: &str| State::Unknown(NonEmpty::new(why).expect("a reason"));
    // 1: a merge read back.
    if merged(f.pr, f.on_base) {
        return State::Known(TicketState::Merged);
    }
    // 2
    if f.issue.state == IssueState::Closed {
        return unknown("closed on GitHub, and no merge was read back");
    }
    // 3
    if labelled(HELD) {
        return State::Known(TicketState::Held);
    }
    if let Some(PullRequest::Open(pr)) = f.pr {
        let review = f.review.flatten();
        // 4
        if review.is_some_and(|r| r.verdict == Verdict::Changes && r.commit == pr.head_commit) {
            return State::Known(TicketState::ChangesRequested);
        }
        // 5
        if pr.draft || f.checks.is_none_or(|c| ci(c) != Ci::Passed) {
            return State::Known(TicketState::Building);
        }
        // 6
        return State::Known(TicketState::InReview);
    }
    match f.pr {
        None => {
            let ready = labelled(READY_FOR_AGENT) || labelled(READY_FOR_HUMAN);
            // 7
            if !ready {
                return unknown("no pull request, and no ready label: not approved yet");
            }
            // 8
            if f.blockers_merged.contains(&false) {
                return State::Known(TicketState::Blocked);
            }
            // 9
            if labelled(READY_FOR_AGENT) {
                return State::Known(TicketState::Ready);
            }
            // 10
            unknown("ready for a person, and every blocker merged: no state for it")
        }
        // 10
        Some(PullRequest::Several { .. }) => {
            unknown("several open pull requests close it: none of them is its")
        }
        Some(_) => unknown("its pull request merged, but the merge wasn't found on its base"),
    }
}

// ---------------------------------------------------------------------
// The walk: every read, in the order of `reads`.

/// One read's identity: its kind and subject. One record per key.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
enum Key {
    Version,
    Repository,
    SpecList,
    Issue(Number),
    SubIssues(Number),
    BlockedBy(Number),
    PrDiscovery(Number),
    Checks(Number),
    Comments(Number),
    MergeReadback(Number),
}

/// A per-pull-request read, made after the walk.
enum Job {
    Checks(Number),
    Comments(Number),
    OnBase(MergedPr),
}

struct Walk<'a> {
    source: &'a dyn FleetsSource,
    clock: &'a dyn Clock,
    deadline: Instant,
    snapshot: Timestamp,
    reads: Vec<Read>,
    ids: HashMap<Key, ReadId>,
    /// Each job's record, by index into `reads`.
    jobs: Vec<(usize, Job)>,
    issues: Option<Result<Issues, Failed>>,
    prs: Option<Result<Listed<PrRow>, Failed>>,
}

/// The issue list, by number.
struct Issues {
    rows: Vec<IssueRow>,
    by_number: HashMap<Number, usize>,
    cut_short: bool,
}

/// What a link is, against the issue list.
enum Whose {
    /// This repository's issue: the list holds it, with the same id.
    Ours,
    /// The list is cut short and doesn't hold it, so it can't be told.
    Unknown,
    /// Not this repository's issue.
    Foreign,
}

fn failed(gap: GapKind, reason: impl Into<String>) -> Failed {
    Failed {
        gap,
        reason: NonEmpty::new(reason).expect("a reason is never empty"),
    }
}

fn outcome<T>(result: Result<T, Failed>) -> Outcome<T> {
    match result {
        Ok(value) => Outcome::Complete { value },
        Err(f) => Outcome::Failed(f),
    }
}

impl Walk<'_> {
    fn run(&mut self) {
        let version = self.call(|s, d| s.version(d));
        self.push(
            Key::Version,
            ReadKind::Version {
                source: SourceName::Github,
                outcome: outcome(version),
            },
        );
        let repository = self.call(|s, d| s.repository(d));
        self.push(
            Key::Repository,
            ReadKind::Repository {
                outcome: outcome(repository),
            },
        );
        let issues = self.call(|s, d| s.issues(d)).and_then(index_issues);
        let specs = self.spec_list(&issues);
        self.issues = Some(issues);
        for spec in specs {
            self.fleet(spec);
        }
        self.run_jobs();
    }

    /// One sequential call, unless the budget has run out.
    fn call<T>(
        &self,
        f: impl FnOnce(&dyn FleetsSource, Instant) -> Result<T, Failed>,
    ) -> Result<T, Failed> {
        if self.clock.monotonic() >= self.deadline {
            return Err(failed(GapKind::BudgetExhausted, NOT_READ_BUDGET));
        }
        f(self.source, self.deadline)
    }

    fn push(&mut self, key: Key, kind: ReadKind) -> ReadId {
        let id = ReadId(u32::try_from(self.reads.len() + 1).expect("fewer reads than u32"));
        self.reads.push(Read { id, kind });
        self.ids.insert(key, id);
        id
    }

    fn has(&self, key: Key) -> bool {
        self.ids.contains_key(&key)
    }

    /// The `spec_list` record, and the specs it lists.
    fn spec_list(&mut self, issues: &Result<Issues, Failed>) -> Vec<Number> {
        let (outcome, specs) = match issues {
            Err(f) => (ListOutcome::Failed(f.clone()), Vec::new()),
            Ok(list) => {
                let mut specs: Vec<Number> = list
                    .rows
                    .iter()
                    .filter(|r| r.state == IssueState::Open && r.sub_issues.total > 0)
                    .map(|r| r.number)
                    .collect();
                specs.sort();
                let outcome = if list.cut_short {
                    ListOutcome::Partial {
                        gap: Truncated::Truncated,
                        reason: NonEmpty::new(format!(
                            "GitHub listed {} issues, the most one read asks for: there may be more",
                            list.rows.len()
                        ))
                        .expect("a reason"),
                        value: specs.clone(),
                    }
                } else {
                    ListOutcome::Complete {
                        value: specs.clone(),
                    }
                };
                (outcome, specs)
            }
        };
        self.push(Key::SpecList, ReadKind::SpecList { outcome });
        specs
    }

    fn fleet(&mut self, spec: Number) {
        self.issue_record(spec);
        let tickets = self.links_record(Key::SubIssues(spec), spec);
        for ticket in &tickets {
            self.ticket(ticket);
        }
        let mut blockers: BTreeMap<Number, Link> = BTreeMap::new();
        for ticket in &tickets {
            for blocker in self.listed_links(Key::BlockedBy(ticket.number), ticket.number) {
                blockers.entry(blocker.number).or_insert(blocker);
            }
        }
        for blocker in blockers.values() {
            self.blocker(blocker);
        }
    }

    fn ticket(&mut self, link: &Link) {
        self.issue_record(link.number);
        if !self.has(Key::BlockedBy(link.number)) {
            self.links_record(Key::BlockedBy(link.number), link.number);
        }
        self.pr_records(link, true);
    }

    fn blocker(&mut self, link: &Link) {
        self.issue_record(link.number);
        self.pr_records(link, false);
    }

    /// The issue list's row for `number`, or why it can't be had.
    fn row(&self, number: Number) -> Result<&IssueRow, Failed> {
        let list = match self.issues.as_ref().expect("the issue list is read first") {
            Ok(list) => list,
            Err(f) => return Err(f.clone()),
        };
        match list.by_number.get(&number) {
            Some(&i) => Ok(&list.rows[i]),
            None if list.cut_short => Err(failed(
                GapKind::BudgetExhausted,
                format!(
                    "#{number} isn't among the {} issues GitHub listed, the most one read asks for",
                    list.rows.len()
                ),
            )),
            None => Err(failed(
                GapKind::NotFound,
                format!("#{number} isn't one of this repository's issues"),
            )),
        }
    }

    fn whose(&self, link: &Link) -> Whose {
        let Some(Ok(list)) = &self.issues else {
            return Whose::Unknown;
        };
        match list.by_number.get(&link.number) {
            Some(&i) if list.rows[i].id == link.id => Whose::Ours,
            Some(_) => Whose::Foreign,
            None if list.cut_short => Whose::Unknown,
            None => Whose::Foreign,
        }
    }

    fn issue_record(&mut self, number: Number) {
        if self.has(Key::Issue(number)) {
            return;
        }
        let issue = self.row(number).and_then(issue_of);
        self.push(
            Key::Issue(number),
            ReadKind::Issue {
                issue: number,
                outcome: outcome(issue),
            },
        );
    }

    /// The `sub_issues` (`Key::SubIssues`) or `blocked_by` record of
    /// `owner`'s row, and the links it lists.
    fn links_record(&mut self, key: Key, owner: Number) -> Vec<Link> {
        let (what, whats) = match key {
            Key::SubIssues(_) => ("sub-issue", "sub-issues"),
            _ => ("blocker", "blockers"),
        };
        let links = self.row(owner).map(|row| match key {
            Key::SubIssues(_) => row.sub_issues.clone(),
            _ => row.blocked_by.clone(),
        });
        let result = links.and_then(|links| self.check_links(owner, &links, what, whats));
        let (outcome, listed) = match result {
            Err(f) => (ListOutcome::Failed(f), Vec::new()),
            Ok((links, None)) => (
                ListOutcome::Complete {
                    value: links.iter().map(|l| l.number).collect(),
                },
                links,
            ),
            Ok((links, Some(reason))) => (
                ListOutcome::Partial {
                    gap: Truncated::Truncated,
                    reason,
                    value: links.iter().map(|l| l.number).collect(),
                },
                links,
            ),
        };
        match key {
            Key::SubIssues(spec) => self.push(key, ReadKind::SubIssues { spec, outcome }),
            _ => self.push(
                key,
                ReadKind::BlockedBy {
                    ticket: owner,
                    outcome,
                },
            ),
        };
        listed
    }

    /// The links, ascending, and a reason when GitHub listed fewer than
    /// its total; or why they can't be taken.
    fn check_links(
        &self,
        owner: Number,
        links: &Links,
        what: &str,
        whats: &str,
    ) -> Result<(Vec<Link>, Option<NonEmpty>), Failed> {
        let mut nodes = links.nodes.clone();
        nodes.sort_by_key(|l| l.number);
        let malformed = |why: String| failed(GapKind::Malformed, why);
        if nodes.windows(2).any(|w| w[0].number == w[1].number) {
            return Err(malformed(format!(
                "GitHub listed one of #{owner}'s {whats} twice"
            )));
        }
        if nodes.iter().any(|l| l.number == owner) {
            return Err(malformed(format!(
                "GitHub listed #{owner} as its own {what}"
            )));
        }
        let listed = u64::try_from(nodes.len()).unwrap_or(u64::MAX);
        if listed > links.total {
            return Err(malformed(format!(
                "GitHub listed more of #{owner}'s {whats} than its own total"
            )));
        }
        // A link the list can't tell to be this repository's issue fails
        // the read: another repository's, or one a cut-short list doesn't
        // hold.
        for l in &nodes {
            let n = l.number;
            match self.whose(l) {
                Whose::Ours => {}
                Whose::Foreign => {
                    return Err(failed(
                        GapKind::NotFound,
                        format!("#{owner}'s {what} #{n} isn't one of this repository's issues"),
                    ));
                }
                Whose::Unknown => {
                    let listed = match &self.issues {
                        Some(Ok(list)) => list.rows.len(),
                        _ => 0,
                    };
                    return Err(failed(
                        GapKind::BudgetExhausted,
                        format!(
                            "#{owner}'s {what} #{n} isn't among the {listed} issues GitHub listed, the most one read asks for"
                        ),
                    ));
                }
            }
        }
        let cut = (listed < links.total).then(|| {
            NonEmpty::new(format!(
                "GitHub listed {listed} of #{owner}'s {} {whats}",
                links.total
            ))
            .expect("a reason")
        });
        Ok((nodes, cut))
    }

    /// The links a `sub_issues` or `blocked_by` record lists.
    fn listed_links(&self, key: Key, owner: Number) -> Vec<Link> {
        let Some(id) = self.ids.get(&key) else {
            return Vec::new();
        };
        let numbers = match &self.read(*id).kind {
            ReadKind::BlockedBy { outcome, .. } | ReadKind::SubIssues { outcome, .. } => {
                listed(outcome).to_vec()
            }
            _ => Vec::new(),
        };
        let links = self.row(owner).map(|row| match key {
            Key::SubIssues(_) => row.sub_issues.nodes.clone(),
            _ => row.blocked_by.nodes.clone(),
        });
        let links = links.unwrap_or_default();
        numbers
            .into_iter()
            .filter_map(|n| links.iter().find(|l| l.number == n).cloned())
            .collect()
    }

    /// The issue's `pr_discovery` record, and the reads its pull request
    /// needs: a ticket's open one its checks and comments, and any merged
    /// one its merge read back.
    fn pr_records(&mut self, link: &Link, ticket: bool) {
        if !self.has(Key::PrDiscovery(link.number)) {
            let pr = self.discover(link);
            self.push(
                Key::PrDiscovery(link.number),
                ReadKind::PrDiscovery {
                    issue: link.number,
                    outcome: outcome(pr),
                },
            );
        }
        let id = self.ids[&Key::PrDiscovery(link.number)];
        let pr = match &self.read(id).kind {
            ReadKind::PrDiscovery {
                outcome: Outcome::Complete { value: Some(pr) },
                ..
            } => pr.clone(),
            _ => return,
        };
        match pr {
            PullRequest::Open(fields) if ticket => {
                let n = fields.number;
                self.job(Key::Checks(n), Job::Checks(n));
                self.job(Key::Comments(n), Job::Comments(n));
            }
            PullRequest::Merged(merged) => {
                let n = merged.fields.number;
                self.job(Key::MergeReadback(n), Job::OnBase(merged));
            }
            _ => {}
        }
    }

    /// A per-pull-request record, read after the walk; until then (and if
    /// the budget runs out first), not read.
    fn job(&mut self, key: Key, job: Job) {
        if self.has(key) {
            return;
        }
        let not_read = || failed(GapKind::BudgetExhausted, NOT_READ_BUDGET);
        let kind = match job {
            Job::Checks(pr) => ReadKind::Checks {
                pr,
                outcome: ListOutcome::Failed(not_read()),
            },
            Job::Comments(pr) => ReadKind::Comments {
                pr,
                outcome: Outcome::Failed(not_read()),
            },
            Job::OnBase(ref merged) => ReadKind::MergeReadback {
                pr: merged.fields.number,
                outcome: Outcome::Failed(not_read()),
            },
        };
        self.push(key, kind);
        self.jobs.push((self.reads.len() - 1, job));
    }

    /// `pr_discovery`: the merged pull request that closes the issue, or
    /// else its one open one, or several open ones, or none. The pull
    /// request list is read once, when an issue first needs it.
    fn discover(&mut self, link: &Link) -> Result<Option<PullRequest>, Failed> {
        if self.prs.is_none() {
            self.prs = Some(self.call(|s, d| s.pull_requests(d)).and_then(unique_prs));
        }
        let list = match self.prs.as_ref().expect("just read") {
            Ok(list) => list,
            Err(f) => return Err(f.clone()),
        };
        let n = link.number;
        if list.cut_short {
            return Err(failed(
                GapKind::BudgetExhausted,
                format!(
                    "GitHub listed {} pull requests, the most one read asks for: one that closes #{n} may be missing",
                    list.rows.len()
                ),
            ));
        }
        if list.rows.iter().any(|r| match r {
            PrRow::Open(f) | PrRow::Merged { facts: f, .. } => {
                f.closes.len() >= MAX_CLOSING_REFERENCES
            }
            PrRow::Closed { .. } => false,
        }) {
            return Err(failed(
                GapKind::BudgetExhausted,
                format!(
                    "a pull request lists {MAX_CLOSING_REFERENCES} closing references, the most gh reads: one that closes #{n} may be missing"
                ),
            ));
        }
        let closes_it = |f: &PrFacts| f.closes.iter().any(|c| c.id == link.id);
        let merged: Vec<&PrRow> = list
            .rows
            .iter()
            .filter(|r| matches!(r, PrRow::Merged { facts, .. } if closes_it(facts)))
            .collect();
        let open: Vec<&PrFacts> = list
            .rows
            .iter()
            .filter_map(|r| match r {
                PrRow::Open(f) if closes_it(f) => Some(f),
                _ => None,
            })
            .collect();
        match (merged.as_slice(), open.as_slice()) {
            ([_, _, ..], _) => Err(failed(
                GapKind::Malformed,
                format!("more than one merged pull request closes #{n}"),
            )),
            (
                [
                    PrRow::Merged {
                        facts,
                        merge_commit,
                        merged_at,
                    },
                ],
                _,
            ) => Ok(Some(PullRequest::Merged(MergedPr {
                fields: self.pr_fields(facts, link)?,
                merge_commit: merge_commit.clone(),
                merged_at: *merged_at,
            }))),
            ([], []) => Ok(None),
            ([], [one]) => Ok(Some(PullRequest::Open(self.pr_fields(one, link)?))),
            ([], several) => {
                for facts in several {
                    self.pr_fields(facts, link)?;
                }
                let mut numbers: Vec<Number> = several.iter().map(|f| f.number).collect();
                numbers.sort();
                Ok(Some(PullRequest::Several { numbers }))
            }
            _ => unreachable!("only merged rows are in merged"),
        }
    }

    /// A pull request's fields, with what it closes, ascending: only when
    /// each closing reference is this repository's issue, once.
    fn pr_fields(&self, f: &PrFacts, link: &Link) -> Result<PrFields, Failed> {
        let p = f.number;
        let mut closes: Vec<Number> = Vec::new();
        for c in &f.closes {
            if !matches!(self.whose(c), Whose::Ours) || (c.id == link.id && c.number != link.number)
            {
                return Err(failed(
                    GapKind::Malformed,
                    format!(
                        "pull request #{p} closes an issue that can't be told to be this repository's"
                    ),
                ));
            }
            closes.push(c.number);
        }
        closes.sort();
        if closes.windows(2).any(|w| w[0] == w[1]) {
            return Err(failed(
                GapKind::Malformed,
                format!("pull request #{p} lists one closing reference twice"),
            ));
        }
        Ok(PrFields {
            number: p,
            draft: f.draft,
            head_branch: f.head_branch.clone(),
            head_commit: f.head_commit.clone(),
            base_branch: f.base_branch.clone(),
            closes,
        })
    }

    /// Runs the per-pull-request reads, at most
    /// [`MAX_CONCURRENT_DETAIL_READS`] at once; none starts after the
    /// deadline, and each one not read stays recorded as not read.
    fn run_jobs(&mut self) {
        enum Task {
            One(usize, Job),
            Merges(Vec<(Vec<usize>, MergedPr)>),
        }
        let mut tasks = Vec::new();
        let mut pairs: Vec<(Vec<usize>, MergedPr)> = Vec::new();
        let mut by_pair = HashMap::new();
        for (index, job) in std::mem::take(&mut self.jobs) {
            if let Job::OnBase(pr) = job {
                let key = (pr.fields.base_branch.clone(), pr.merge_commit.clone());
                let pair = *by_pair.entry(key).or_insert_with(|| {
                    pairs.push((Vec::new(), pr));
                    pairs.len() - 1
                });
                pairs[pair].0.push(index);
            } else {
                tasks.push(Task::One(index, job));
            }
        }
        for chunk in pairs.chunks(MERGE_BATCH_SIZE) {
            tasks.push(Task::Merges(chunk.to_vec()));
        }
        let next = AtomicUsize::new(0);
        let results: Vec<Mutex<Vec<(usize, ReadKind)>>> =
            tasks.iter().map(|_| Mutex::new(Vec::new())).collect();
        let (source, clock, deadline) = (self.source, self.clock, self.deadline);
        thread::scope(|scope| {
            for _ in 0..MAX_CONCURRENT_DETAIL_READS.min(tasks.len()) {
                scope.spawn(|| {
                    loop {
                        let i = next.fetch_add(1, atomic::Ordering::SeqCst);
                        let Some(task) = tasks.get(i) else { break };
                        if clock.monotonic() >= deadline {
                            continue;
                        }
                        let kinds = match task {
                            Task::One(index, job) => {
                                vec![(*index, read_job(source, job, deadline))]
                            }
                            Task::Merges(pairs) => {
                                let prs: Vec<_> = pairs.iter().map(|(_, pr)| pr.clone()).collect();
                                let mut answers = source.on_bases(&prs, deadline);
                                if answers.len() != prs.len() {
                                    answers = vec![
                                        Err(failed(
                                            GapKind::Malformed,
                                            "the ancestry batch did not answer each merge/base pair"
                                        ));
                                        prs.len()
                                    ];
                                }
                                let mut records = Vec::new();
                                for ((indices, _), answer) in pairs.iter().zip(answers) {
                                    for &index in indices {
                                        let ReadKind::MergeReadback { pr, .. } =
                                            self.reads[index].kind
                                        else {
                                            unreachable!("a merge readback's index")
                                        };
                                        records.push((
                                            index,
                                            ReadKind::MergeReadback {
                                                pr,
                                                outcome: outcome(answer.clone()),
                                            },
                                        ));
                                    }
                                }
                                records
                            }
                        };
                        *results[i].lock().unwrap_or_else(|p| p.into_inner()) = kinds;
                    }
                });
            }
        });
        for result in results {
            for (index, kind) in result.into_inner().unwrap_or_else(|p| p.into_inner()) {
                self.reads[index].kind = kind;
            }
        }
    }

    fn read(&self, id: ReadId) -> &Read {
        &self.reads[usize::try_from(id.0).expect("a read id") - 1]
    }
}

fn read_job(source: &dyn FleetsSource, job: &Job, deadline: Instant) -> ReadKind {
    match job {
        Job::Checks(pr) => ReadKind::Checks {
            pr: *pr,
            outcome: match source.checks(*pr, deadline).and_then(|c| unique_checks(*pr, c)) {
                Ok(value) => ListOutcome::Complete { value },
                Err(f) => ListOutcome::Failed(f),
            },
        },
        Job::Comments(pr) => ReadKind::Comments {
            pr: *pr,
            outcome: outcome(source.comments(*pr, deadline).and_then(|bodies| {
                verdict(&bodies).map_err(|NotAVerdict| {
                    failed(
                        GapKind::Malformed,
                        format!(
                            "the latest VERDICT comment on pull request #{pr} isn't review-ticket's form"
                        ),
                    )
                })
            })),
        },
        Job::OnBase(merged) => ReadKind::MergeReadback {
            pr: merged.fields.number,
            outcome: outcome(source.on_base(merged, deadline)),
        },
    }
}

/// Checks, each name once.
fn unique_checks(pr: Number, checks: Vec<Check>) -> Result<Vec<Check>, Failed> {
    let names: BTreeSet<&str> = checks.iter().map(|c| c.name.as_str()).collect();
    if names.len() != checks.len() {
        return Err(failed(
            GapKind::Malformed,
            format!("pull request #{pr} has two checks with one name"),
        ));
    }
    Ok(checks)
}

/// The pull request list, each number once, or it isn't taken at all: one
/// pull request listed twice, alike or not, can't be one value (#297, R2).
fn unique_prs(list: Listed<PrRow>) -> Result<Listed<PrRow>, Failed> {
    let mut numbers = BTreeSet::new();
    for row in &list.rows {
        let n = match row {
            PrRow::Open(f) | PrRow::Merged { facts: f, .. } => f.number,
            PrRow::Closed { number } => *number,
        };
        if !numbers.insert(n) {
            return Err(failed(
                GapKind::Malformed,
                "GitHub's pull request list named one pull request twice",
            ));
        }
    }
    Ok(list)
}

/// The issue list, indexed: each number and each id once, or it isn't
/// taken at all.
fn index_issues(list: Listed<IssueRow>) -> Result<Issues, Failed> {
    let mut by_number = HashMap::new();
    let mut ids = BTreeSet::new();
    for (i, row) in list.rows.iter().enumerate() {
        if by_number.insert(row.number, i).is_some() || !ids.insert(row.id.as_str()) {
            return Err(failed(
                GapKind::Malformed,
                "GitHub's issue list named one issue twice",
            ));
        }
    }
    Ok(Issues {
        by_number,
        cut_short: list.cut_short,
        rows: list.rows,
    })
}

/// An issue record's value: its fields, each label once.
fn issue_of(row: &IssueRow) -> Result<Issue, Failed> {
    let labels: BTreeSet<&str> = row.labels.iter().map(NonEmpty::as_str).collect();
    if labels.len() != row.labels.len() {
        return Err(failed(
            GapKind::Malformed,
            format!("#{} has one label twice", row.number),
        ));
    }
    Ok(Issue {
        title: row.title.clone(),
        state: row.state,
        milestone: row.milestone.clone(),
        labels: row.labels.clone(),
        owned_paths: template_line(&row.body, "**Owned paths:**"),
        relies_on: template_line(&row.body, "**Relies on:**"),
        pending_question: None,
    })
}

/// What a list outcome lists: its value, complete or partial.
fn listed<T>(outcome: &ListOutcome<T>) -> &[T] {
    match outcome {
        ListOutcome::Complete { value } | ListOutcome::Partial { value, .. } => value,
        ListOutcome::Failed(_) => &[],
    }
}

/// Whether a read is complete: its outcome neither partial nor failed.
pub fn is_complete(kind: &ReadKind) -> bool {
    fn done<T>(o: &Outcome<T>) -> bool {
        matches!(o, Outcome::Complete { .. })
    }
    fn all<T>(o: &ListOutcome<T>) -> bool {
        matches!(o, ListOutcome::Complete { .. })
    }
    match kind {
        ReadKind::Version { outcome, .. } | ReadKind::Workspace { outcome, .. } => done(outcome),
        ReadKind::Repository { outcome } => done(outcome),
        ReadKind::Issue { outcome, .. } => done(outcome),
        ReadKind::PrDiscovery { outcome, .. } => done(outcome),
        ReadKind::Comments { outcome, .. } => done(outcome),
        ReadKind::MergeReadback { outcome, .. } => done(outcome),
        ReadKind::SpecList { outcome }
        | ReadKind::SubIssues { outcome, .. }
        | ReadKind::BlockedBy { outcome, .. } => all(outcome),
        ReadKind::Checks { outcome, .. } => all(outcome),
        ReadKind::Projects { outcome } => all(outcome),
        ReadKind::Threads { outcome } => all(outcome),
    }
}

// ---------------------------------------------------------------------
// The view: pointers, and values worked out by the dependency table.

impl Walk<'_> {
    fn id(&self, key: Key) -> ReadId {
        self.ids[&key]
    }

    fn get(&self, key: Key) -> Option<&ReadKind> {
        self.ids.get(&key).map(|id| &self.read(*id).kind)
    }

    /// A worked-out value: known exactly when every read in `requires` is
    /// complete; otherwise the incomplete ones, in the order of `reads`.
    fn worked<T>(&self, requires: &BTreeSet<ReadId>, known: impl FnOnce() -> T) -> WorkedOut<T> {
        worked(&self.reads, requires, known)
    }

    /// The `pr_discovery` value, when complete.
    fn pr(&self, issue: Number) -> Option<Option<&PullRequest>> {
        match self.get(Key::PrDiscovery(issue))? {
            ReadKind::PrDiscovery {
                outcome: Outcome::Complete { value },
                ..
            } => Some(value.as_ref()),
            _ => None,
        }
    }

    /// The pointers of a `pr_discovery` read's pull request: `ci` and
    /// `review` for an open one (a ticket's only), `on_base` for a merged
    /// one.
    fn pr_pointers(&self, issue: Number) -> (Option<ReadId>, Option<ReadId>, Option<ReadId>) {
        match self.pr(issue) {
            Some(Some(PullRequest::Open(f))) => (
                self.ids.get(&Key::Checks(f.number)).copied(),
                self.ids.get(&Key::Comments(f.number)).copied(),
                None,
            ),
            Some(Some(PullRequest::Merged(m))) => (
                None,
                None,
                self.ids.get(&Key::MergeReadback(m.fields.number)).copied(),
            ),
            _ => (None, None, None),
        }
    }

    /// `blocker.merged`'s reads: its `pr_discovery`, and its merged pull
    /// request's merge read back.
    fn merged_requires(&self, blocker: Number) -> BTreeSet<ReadId> {
        let mut r = BTreeSet::from([self.id(Key::PrDiscovery(blocker))]);
        r.extend(self.pr_pointers(blocker).2);
        r
    }

    /// `blocker.merged`, from complete reads: merged and read back on its
    /// base.
    fn merged_known(&self, blocker: Number) -> bool {
        merged(self.pr(blocker).flatten(), self.on_base(blocker))
    }

    fn on_base(&self, issue: Number) -> Option<bool> {
        match self.get(Key::MergeReadback(match self.pr(issue)? {
            Some(PullRequest::Merged(m)) => m.fields.number,
            _ => return None,
        }))? {
            ReadKind::MergeReadback {
                outcome: Outcome::Complete { value },
                ..
            } => Some(*value),
            _ => None,
        }
    }

    fn blockers_of(&self, ticket: Number) -> Vec<Number> {
        match self.get(Key::BlockedBy(ticket)) {
            Some(ReadKind::BlockedBy { outcome, .. }) => listed(outcome).to_vec(),
            _ => Vec::new(),
        }
    }

    fn tickets_of(&self, spec: Number) -> Vec<Number> {
        match self.get(Key::SubIssues(spec)) {
            Some(ReadKind::SubIssues { outcome, .. }) => listed(outcome).to_vec(),
            _ => Vec::new(),
        }
    }

    /// `ticket.state`'s reads: the ticket's own, its pull request's, and
    /// each of its blockers' `merged`.
    fn state_requires(&self, ticket: Number) -> BTreeSet<ReadId> {
        let mut r = BTreeSet::from([
            self.id(Key::Issue(ticket)),
            self.id(Key::BlockedBy(ticket)),
            self.id(Key::PrDiscovery(ticket)),
        ]);
        let (ci, review, on_base) = self.pr_pointers(ticket);
        r.extend(ci.into_iter().chain(review).chain(on_base));
        for b in self.blockers_of(ticket) {
            r.extend(self.merged_requires(b));
        }
        r
    }

    fn state(&self, ticket: Number) -> State {
        if let WorkedOut::Unread(unread) = self.worked(&self.state_requires(ticket), || ()) {
            return State::Unread(unread);
        }
        let issue = match self.get(Key::Issue(ticket)) {
            Some(ReadKind::Issue {
                outcome: Outcome::Complete { value },
                ..
            }) => value,
            _ => unreachable!("its issue read is complete"),
        };
        let pr = self.pr(ticket).expect("its pr_discovery read is complete");
        let (ci_id, review_id, _) = self.pr_pointers(ticket);
        let checks = ci_id.and_then(|id| match &self.read(id).kind {
            ReadKind::Checks {
                outcome: ListOutcome::Complete { value },
                ..
            } => Some(value.as_slice()),
            _ => None,
        });
        let review = review_id.and_then(|id| match &self.read(id).kind {
            ReadKind::Comments {
                outcome: Outcome::Complete { value },
                ..
            } => Some(value.as_ref()),
            _ => None,
        });
        let merged: Vec<bool> = self
            .blockers_of(ticket)
            .into_iter()
            .map(|b| self.merged_known(b))
            .collect();
        ticket_state(&StateFacts {
            issue,
            pr,
            checks,
            review,
            on_base: self.on_base(ticket),
            blockers_merged: &merged,
        })
    }

    fn specs(&self) -> Vec<Number> {
        match self.get(Key::SpecList) {
            Some(ReadKind::SpecList { outcome }) => listed(outcome).to_vec(),
            _ => Vec::new(),
        }
    }

    /// `specs` and every fleet's `fleet.tickets`.
    fn fleet_lists_requires(&self) -> BTreeSet<ReadId> {
        let mut r = BTreeSet::from([self.id(Key::SpecList)]);
        r.extend(self.specs().into_iter().map(|s| self.id(Key::SubIssues(s))));
        r
    }

    fn progress(&self, spec: Number) -> WorkedOut<Counts> {
        let tickets = self.tickets_of(spec);
        let mut requires = BTreeSet::from([self.id(Key::SubIssues(spec))]);
        for t in &tickets {
            requires.extend(self.state_requires(*t));
        }
        self.worked(&requires, || {
            let mut c = Counts::default();
            for t in &tickets {
                c.tickets += 1;
                match self.state(*t) {
                    State::Known(TicketState::Ready) => c.ready += 1,
                    State::Known(TicketState::Building) => c.building += 1,
                    State::Known(TicketState::InReview) => c.in_review += 1,
                    State::Known(TicketState::ChangesRequested) => c.changes_requested += 1,
                    State::Known(TicketState::Merged) => c.merged += 1,
                    State::Known(TicketState::Held) => c.held += 1,
                    State::Known(TicketState::Blocked) => c.blocked += 1,
                    State::Unknown(_) => c.unknown += 1,
                    State::Unread(_) => unreachable!("every read it requires is complete"),
                }
            }
            c
        })
    }

    fn needs_you(&self) -> WorkedOut<Vec<NeedsYou>> {
        let mut requires = self.fleet_lists_requires();
        let pairs: Vec<(Number, Number)> = self
            .specs()
            .into_iter()
            .flat_map(|s| self.tickets_of(s).into_iter().map(move |t| (s, t)))
            .collect();
        requires.extend(pairs.iter().map(|(_, t)| self.id(Key::Issue(*t))));
        self.worked(&requires, || {
            let mut items = Vec::new();
            for (spec, ticket) in &pairs {
                let Some(ReadKind::Issue {
                    outcome: Outcome::Complete { value },
                    ..
                }) = self.get(Key::Issue(*ticket))
                else {
                    unreachable!("every ticket's issue read is complete")
                };
                for kind in needs_you_kinds(value) {
                    items.push(needs_you_item(
                        kind,
                        *spec,
                        *ticket,
                        value,
                        QUESTION_NOT_READ,
                    ));
                }
            }
            items.sort_by_key(|i| (i.spec, i.ticket, needs_you_word(i.kind)));
            items
        })
    }

    fn envelope(&self) -> Envelope {
        let specs = self.specs();
        let fleets = specs
            .iter()
            .map(|&spec| Fleet {
                spec,
                issue: self.id(Key::Issue(spec)),
                tickets: self.id(Key::SubIssues(spec)),
                progress: self.progress(spec),
            })
            .collect();
        let tickets: BTreeSet<Number> = specs.iter().flat_map(|s| self.tickets_of(*s)).collect();
        let blockers: BTreeSet<Number> =
            tickets.iter().flat_map(|t| self.blockers_of(*t)).collect();
        let fleet_lists = self.fleet_lists_requires();
        let data = FleetsView {
            repository: self.id(Key::Repository),
            specs: self.id(Key::SpecList),
            fleets,
            tickets: tickets
                .iter()
                .map(|&number| {
                    let (ci, review, on_base) = self.pr_pointers(number);
                    TicketCore {
                        number,
                        issue: self.id(Key::Issue(number)),
                        blocked_by: self.id(Key::BlockedBy(number)),
                        pr: self.id(Key::PrDiscovery(number)),
                        ci,
                        review,
                        on_base,
                        state: self.state(number),
                    }
                })
                .collect(),
            blockers: blockers
                .iter()
                .map(|&number| Blocker {
                    number,
                    issue: self.id(Key::Issue(number)),
                    pr: self.id(Key::PrDiscovery(number)),
                    on_base: self.pr_pointers(number).2,
                    fleet: self.worked(&fleet_lists, || {
                        specs
                            .iter()
                            .copied()
                            .find(|s| self.tickets_of(*s).contains(&number))
                    }),
                    merged: self
                        .worked(&self.merged_requires(number), || self.merged_known(number)),
                })
                .collect(),
            needs_you: self.needs_you(),
        };
        let version = self.id(Key::Version);
        let tested_version = self.source.tested_version().to_owned();
        let version_tested = matches!(
            &self.read(version).kind,
            ReadKind::Version { outcome: Outcome::Complete { value }, .. }
                if value.as_str() == tested_version
        );
        let complete = self.reads.iter().all(|r| is_complete(&r.kind));
        Envelope {
            schema: SchemaId::V1,
            sources: Sources {
                github: GitHubSource {
                    name: Gh::Gh,
                    version,
                    tested_version,
                    version_tested,
                },
                cloudroom: None,
            },
            reads: self.reads.clone(),
            coverage: Coverage {
                state: if complete {
                    Completeness::Complete
                } else {
                    Completeness::Partial
                },
            },
            freshness: Freshness {
                snapshot_at: self.snapshot,
            },
            data: View::Fleets(data),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ne(s: &str) -> NonEmpty {
        NonEmpty::new(s).unwrap()
    }

    #[test]
    fn a_template_line_is_the_one_line_that_starts_with_its_label() {
        let label = "**Owned paths:**";
        for (body, want) in [
            ("**Owned paths:** `a.rs`, `b/`", Some("`a.rs`, `b/`")),
            ("Intro\r\n**Owned paths:**  `a.rs` \r\nmore", Some("`a.rs`")),
            ("**Owned paths:**", None),
            ("**Owned paths:**   ", None),
            ("no such line", None),
            ("**Owned paths:** a\n**Owned paths:** b", None),
            (" **Owned paths:** indented", None),
            ("A **Owned paths:** mid-line", None),
            ("**Owned paths**: other form", None),
        ] {
            assert_eq!(
                template_line(body, label).as_ref().map(NonEmpty::as_str),
                want,
                "{body:?}"
            );
        }
    }

    #[test]
    fn a_verdict_is_the_latest_verdict_comment_in_its_exact_form() {
        let c = "4".repeat(40);
        let body = |s: &str| s.to_owned();
        let approve = Review {
            verdict: Verdict::Approve,
            commit: Commit::parse(&c).unwrap(),
        };
        let changes = Review {
            verdict: Verdict::Changes,
            ..approve.clone()
        };
        for (bodies, want) in [
            (vec![], Ok(None)),
            (vec![body("Synthetic note")], Ok(None)),
            (
                vec![body(&format!("VERDICT: APPROVE at {c}"))],
                Ok(Some(approve.clone())),
            ),
            (
                vec![body(&format!("VERDICT: APPROVE at {c}\r\nmore"))],
                Ok(Some(approve.clone())),
            ),
            (
                vec![
                    body(&format!("VERDICT: APPROVE at {c}")),
                    body("Synthetic later note"),
                    body(&format!("VERDICT: CHANGES at {c}\n\nfindings")),
                ],
                Ok(Some(changes.clone())),
            ),
            // The latest one is malformed: never an older one instead.
            (
                vec![
                    body(&format!("VERDICT: APPROVE at {c}")),
                    body(&format!("VERDICT: APPROVE at {}", &c[..7])),
                ],
                Err(NotAVerdict),
            ),
            (
                vec![body(&format!("VERDICT: approve at {c}"))],
                Err(NotAVerdict),
            ),
            (
                vec![body(&format!("VERDICT: APPROVE at {c} "))],
                Err(NotAVerdict),
            ),
            (
                vec![body(&format!("VERDICT: APPROVE {c}"))],
                Err(NotAVerdict),
            ),
            (
                vec![body(&format!("VERDICT: APPROVED at {c}"))],
                Err(NotAVerdict),
            ),
            (
                vec![body(&format!("VERDICT: CHANGES at {}", "A".repeat(40)))],
                Err(NotAVerdict),
            ),
            (vec![body(&format!(" VERDICT: APPROVE at {c}"))], Ok(None)),
            (vec![body(&format!("Verdict: APPROVE at {c}"))], Ok(None)),
        ] {
            assert_eq!(verdict(&bodies), want, "{bodies:?}");
        }
    }

    #[test]
    fn ci_is_the_worst_check() {
        let check = |r| Check {
            name: ne("syn-check"),
            result: r,
        };
        use CheckResult::*;
        for (results, want) in [
            (vec![], Ci::None),
            (vec![Skipping], Ci::None),
            (vec![Pass, Skipping], Ci::Passed),
            (vec![Pass, Pending], Ci::Pending),
            (vec![Pending, Fail], Ci::Failed),
            (vec![Pass, Cancel], Ci::Failed),
        ] {
            let checks: Vec<Check> = results.into_iter().map(check).collect();
            assert_eq!(ci(&checks), want, "{checks:?}");
        }
    }
}
