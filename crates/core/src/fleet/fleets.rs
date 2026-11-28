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

pub const READY_FOR_AGENT: &str = "ready-for-agent";
pub const READY_FOR_HUMAN: &str = "ready-for-human";
pub const NEEDS_INFO: &str = "needs-info";
pub const HELD: &str = "held";

pub const MAX_CLOSING_REFERENCES: usize = 100;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Link {
    pub number: Number,
    pub id: NonEmpty,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Links {
    pub nodes: Vec<Link>,
    pub total: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IssueRow {
    pub number: Number,
    pub id: NonEmpty,
    pub title: String,
    pub state: IssueState,
    pub milestone: Option<Milestone>,
    pub labels: Vec<NonEmpty>,
    pub body: String,
    pub sub_issues: Links,
    pub blocked_by: Links,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IssueComment {
    pub body: String,
    pub link: NonEmpty,
    pub asked_at: Timestamp,
}

pub const QUESTION_NOT_READ: &str =
    "the fleets view does not read comments; openwiz fleet <spec> reads the question";

pub const QUESTION_NOT_FOUND: &str = "no unique newest needs-you or Needs you comment was found";

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

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PrRow {
    Open(PrFacts),
    Merged {
        facts: PrFacts,
        merge_commit: Commit,
        merged_at: Timestamp,
    },
    Closed {
        number: Number,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PrFacts {
    pub number: Number,
    pub draft: bool,
    pub head_branch: NonEmpty,
    pub head_commit: Commit,
    pub base_branch: NonEmpty,
    pub closes: Vec<Link>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StockPr {
    pub pr: PrRow,
    pub title: Fact<NonEmpty>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Listed<T> {
    pub rows: Vec<T>,
    pub cut_short: bool,
}

pub const MERGE_BATCH_SIZE: usize = 20;

pub trait FleetsSource: Sync {
    fn tested_version(&self) -> &str;
    fn version(&self, deadline: Instant) -> Result<NonEmpty, Failed>;
    fn repository(&self, deadline: Instant) -> Result<Repository, Failed>;
    fn issues(&self, deadline: Instant) -> Result<Listed<IssueRow>, Failed>;
    fn pull_requests(&self, deadline: Instant) -> Result<Listed<PrRow>, Failed>;
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
    fn checks(&self, pr: Number, deadline: Instant) -> Result<Vec<Check>, Failed>;
    fn comments(&self, pr: Number, deadline: Instant) -> Result<Vec<String>, Failed>;
    fn on_base(&self, pr: &MergedPr, deadline: Instant) -> Result<bool, Failed>;
    fn on_bases(&self, prs: &[MergedPr], deadline: Instant) -> Vec<Result<bool, Failed>> {
        prs.iter().map(|pr| self.on_base(pr, deadline)).collect()
    }
}

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
        closing: Closing::default(),
    };
    walk.run();
    walk.envelope()
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ci {
    Failed,
    Pending,
    Passed,
    None,
}

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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct NotAVerdict;

pub const VERDICT_PREFIX: &str = "VERDICT: ";

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

pub fn merged(pr: Option<&PullRequest>, on_base: Option<bool>) -> bool {
    matches!(pr, Some(PullRequest::Merged(_))) && on_base == Some(true)
}

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

pub fn needs_you_word(kind: NeedsYouKind) -> &'static str {
    match kind {
        NeedsYouKind::Held => "held",
        NeedsYouKind::NeedsInfo => "needs_info",
    }
}

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

fn worked_in_place<T>(
    reads: &[Read],
    requires: &BTreeSet<ReadId>,
    known: impl FnOnce() -> T,
) -> WorkedOut<T> {
    let unread: Vec<ReadId> = requires
        .iter()
        .copied()
        .filter(|id| !complete_in_place(reads, *id))
        .collect();
    if unread.is_empty() {
        WorkedOut::Known(known())
    } else {
        WorkedOut::Unread(unread)
    }
}

fn complete_in_place(reads: &[Read], id: ReadId) -> bool {
    let at = usize::try_from(id.0).map_or(usize::MAX, |n| n.wrapping_sub(1));
    match reads.get(at) {
        Some(r) if r.id == id => is_complete(&r.kind),
        _ => reads.iter().any(|r| r.id == id && is_complete(&r.kind)),
    }
}

#[derive(Clone, Copy, Debug)]
pub struct StateFacts<'a> {
    pub issue: &'a Issue,
    pub pr: Option<&'a PullRequest>,
    pub checks: Option<&'a [Check]>,
    pub review: Option<Option<&'a Review>>,
    pub on_base: Option<bool>,
    pub blockers_merged: &'a [bool],
}

pub fn ticket_state(f: &StateFacts) -> State {
    let labelled = |name: &str| f.issue.labels.iter().any(|l| l.as_str() == name);
    let unknown = |why: &str| State::Unknown(NonEmpty::new(why).expect("a reason"));
    if merged(f.pr, f.on_base) {
        return State::Known(TicketState::Merged);
    }
    if f.issue.state == IssueState::Closed {
        return unknown("closed on GitHub, and no merge was read back");
    }
    if labelled(HELD) {
        return State::Known(TicketState::Held);
    }
    if let Some(PullRequest::Open(pr)) = f.pr {
        let review = f.review.flatten();
        if review.is_some_and(|r| r.verdict == Verdict::Changes && r.commit == pr.head_commit) {
            return State::Known(TicketState::ChangesRequested);
        }
        if pr.draft || f.checks.is_none_or(|c| ci(c) != Ci::Passed) {
            return State::Known(TicketState::Building);
        }
        return State::Known(TicketState::InReview);
    }
    match f.pr {
        None => {
            let ready = labelled(READY_FOR_AGENT) || labelled(READY_FOR_HUMAN);
            if !ready {
                return unknown("no pull request, and no ready label: not approved yet");
            }
            if f.blockers_merged.contains(&false) {
                return State::Known(TicketState::Blocked);
            }
            if labelled(READY_FOR_AGENT) {
                return State::Known(TicketState::Ready);
            }
            unknown("ready for a person, and every blocker merged: no state for it")
        }
        Some(PullRequest::Several { .. }) => {
            unknown("several open pull requests close it: none of them is its")
        }
        Some(_) => unknown("its pull request merged, but the merge wasn't found on its base"),
    }
}

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
    jobs: Vec<(usize, Job)>,
    issues: Option<Result<Issues, Failed>>,
    prs: Option<Result<Listed<PrRow>, Failed>>,
    closing: Closing,
}

#[derive(Default)]
struct Closing {
    overfull: bool,
    rows: HashMap<NonEmpty, (Vec<usize>, Vec<usize>)>,
}

fn closing(list: &Listed<PrRow>) -> Closing {
    let mut index = Closing::default();
    for (at, row) in list.rows.iter().enumerate() {
        let (facts, merged) = match row {
            PrRow::Open(f) => (f, false),
            PrRow::Merged { facts, .. } => (facts, true),
            PrRow::Closed { .. } => continue,
        };
        index.overfull |= facts.closes.len() >= MAX_CLOSING_REFERENCES;
        for c in &facts.closes {
            let (m, o) = index.rows.entry(c.id.clone()).or_default();
            let rows = if merged { m } else { o };
            if rows.last() != Some(&at) {
                rows.push(at);
            }
        }
    }
    index
}

struct Issues {
    rows: Vec<IssueRow>,
    by_number: HashMap<Number, usize>,
    cut_short: bool,
}

enum Whose {
    Ours,
    Unknown,
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

    fn discover(&mut self, link: &Link) -> Result<Option<PullRequest>, Failed> {
        if self.prs.is_none() {
            let prs = self.call(|s, d| s.pull_requests(d)).and_then(unique_prs);
            if let Ok(list) = &prs {
                self.closing = closing(list);
            }
            self.prs = Some(prs);
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
        if self.closing.overfull {
            return Err(failed(
                GapKind::BudgetExhausted,
                format!(
                    "a pull request lists {MAX_CLOSING_REFERENCES} closing references, the most gh reads: one that closes #{n} may be missing"
                ),
            ));
        }
        let (merged_at, open_at) = self
            .closing
            .rows
            .get(&link.id)
            .map_or((&[][..], &[][..]), |(m, o)| (m.as_slice(), o.as_slice()));
        let merged: Vec<&PrRow> = merged_at.iter().map(|&at| &list.rows[at]).collect();
        let open: Vec<&PrFacts> = open_at
            .iter()
            .filter_map(|&at| match &list.rows[at] {
                PrRow::Open(f) => Some(f),
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

fn listed<T>(outcome: &ListOutcome<T>) -> &[T] {
    match outcome {
        ListOutcome::Complete { value } | ListOutcome::Partial { value, .. } => value,
        ListOutcome::Failed(_) => &[],
    }
}

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

impl Walk<'_> {
    fn id(&self, key: Key) -> ReadId {
        self.ids[&key]
    }

    fn get(&self, key: Key) -> Option<&ReadKind> {
        self.ids.get(&key).map(|id| &self.read(*id).kind)
    }

    fn worked<T>(&self, requires: &BTreeSet<ReadId>, known: impl FnOnce() -> T) -> WorkedOut<T> {
        worked_in_place(&self.reads, requires, known)
    }

    fn pr(&self, issue: Number) -> Option<Option<&PullRequest>> {
        match self.get(Key::PrDiscovery(issue))? {
            ReadKind::PrDiscovery {
                outcome: Outcome::Complete { value },
                ..
            } => Some(value.as_ref()),
            _ => None,
        }
    }

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

    fn merged_requires(&self, blocker: Number) -> BTreeSet<ReadId> {
        let mut r = BTreeSet::from([self.id(Key::PrDiscovery(blocker))]);
        r.extend(self.pr_pointers(blocker).2);
        r
    }

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
fn scanned(list: &Listed<PrRow>, id: &NonEmpty) -> (Vec<usize>, Vec<usize>, bool) {
    let closes_it = |f: &PrFacts| f.closes.iter().any(|c| c.id == *id);
    let merged = list
        .rows
        .iter()
        .enumerate()
        .filter(|(_, r)| matches!(r, PrRow::Merged { facts, .. } if closes_it(facts)))
        .map(|(at, _)| at)
        .collect();
    let open = list
        .rows
        .iter()
        .enumerate()
        .filter(|(_, r)| matches!(r, PrRow::Open(f) if closes_it(f)))
        .map(|(at, _)| at)
        .collect();
    let overfull = list.rows.iter().any(|r| match r {
        PrRow::Open(f) | PrRow::Merged { facts: f, .. } => f.closes.len() >= MAX_CLOSING_REFERENCES,
        PrRow::Closed { .. } => false,
    });
    (merged, open, overfull)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ne(s: &str) -> NonEmpty {
        NonEmpty::new(s).unwrap()
    }

    struct Rng(u64);
    impl Rng {
        fn next(&mut self) -> u64 {
            self.0 ^= self.0 << 13;
            self.0 ^= self.0 >> 7;
            self.0 ^= self.0 << 17;
            self.0
        }
        fn below(&mut self, n: u64) -> u64 {
            self.next() % n
        }
    }

    fn read(id: u32, complete: bool) -> Read {
        Read {
            id: ReadId(id),
            kind: ReadKind::MergeReadback {
                pr: Number::new(u64::from(id) + 1).unwrap(),
                outcome: if complete {
                    Outcome::Complete { value: true }
                } else {
                    Outcome::Failed(failed(GapKind::Malformed, "synthetic"))
                },
            },
        }
    }

    #[test]
    fn worked_in_place_matches_the_scanning_worked_for_unique_ids() {
        let mut rng = Rng(0x9e37_79b9_7f4a_7c15);
        for case in 0..4000 {
            let len = rng.below(40) as u32;
            let mut reads: Vec<Read> = (1..=len).map(|id| read(id, rng.below(5) != 0)).collect();
            match case % 4 {
                0 => {}
                1 => reads.reverse(),
                2 => {
                    for r in &mut reads {
                        if rng.below(3) == 0 {
                            r.id = ReadId(r.id.0 + len + 3);
                        }
                    }
                }
                _ => {
                    for at in (1..reads.len()).rev() {
                        let other = rng.below(at as u64 + 1) as usize;
                        reads.swap(at, other);
                    }
                }
            }
            let requires: BTreeSet<ReadId> = (0..rng.below(8))
                .map(|_| ReadId(rng.below(u64::from(2 * len) + 6) as u32))
                .collect();
            assert_eq!(
                worked_in_place(&reads, &requires, || case),
                worked(&reads, &requires, || case),
                "case {case}: {reads:?} {requires:?}"
            );
        }
    }

    #[test]
    fn closing_matches_the_scan_of_every_pull_request() {
        let mut rng = Rng(0xd1b5_4a32_d192_ed03);
        for case in 0..2000 {
            let ids: Vec<NonEmpty> = (0..1 + rng.below(6))
                .map(|i| ne(&format!("I_syn{i}")))
                .collect();
            let rows: Vec<PrRow> = (0..rng.below(12))
                .map(|p| {
                    let number = Number::new(p + 1).unwrap();
                    let many = if rng.below(50) == 0 {
                        MAX_CLOSING_REFERENCES as u64
                    } else {
                        rng.below(4)
                    };
                    let facts = PrFacts {
                        number,
                        draft: false,
                        head_branch: ne("syn"),
                        head_commit: Commit::parse(&"a".repeat(40)).unwrap(),
                        base_branch: ne("main"),
                        closes: (0..many)
                            .map(|_| {
                                let i = rng.below(ids.len() as u64) as usize;
                                Link {
                                    number: Number::new(i as u64 + 1).unwrap(),
                                    id: ids[i].clone(),
                                }
                            })
                            .collect(),
                    };
                    match rng.below(3) {
                        0 => PrRow::Open(facts),
                        1 => PrRow::Merged {
                            facts,
                            merge_commit: Commit::parse(&"b".repeat(40)).unwrap(),
                            merged_at: Timestamp(1),
                        },
                        _ => PrRow::Closed { number },
                    }
                })
                .collect();
            let list = Listed {
                rows,
                cut_short: false,
            };
            let index = closing(&list);
            for id in ids.iter().chain([&ne("I_syn_missing")]) {
                let (merged, open) = index.rows.get(id).cloned().unwrap_or_default();
                assert_eq!(
                    (merged, open, index.overfull),
                    scanned(&list, id),
                    "case {case} {id:?}: {list:?}"
                );
            }
        }
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
