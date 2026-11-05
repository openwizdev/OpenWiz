//! One fleet's tickets, their states and "needs you" (A5, ClosedWiz#113):
//! the `openwiz fleet <spec>` view of `contracts/fleet.v1.md`, worked out
//! from GitHub's answers. No I/O: a [`GitHub`] source answers each read.
//!
//! [`fleet`] makes the reads, records each one once in `reads`, and works
//! every value out from them by the contract's rules:
//! - **the read rule:** a worked-out value is known exactly when every read
//!   it requires (the contract's dependency table, every edge) is complete;
//!   otherwise it names exactly the incomplete ones, in the order of
//!   `reads`;
//! - **the state table**, in its order, the first rule that matches wins;
//! - **merged means read back:** a ticket or blocker is merged only when its
//!   pull request is merged and its merge commit was read back on its base.
//!   An approval, a ready pull request or a closed issue never is.
//!
//! **One repository.** Every issue and pull request is this repository's:
//! a sub-issue or blocker in another repository fails its list's read, and a
//! pull request in another repository is never an issue's (it can't merge
//! into this repository's base). GitHub's address of each item tells which
//! repository it is in.
//!
//! **The agents** (`sources.cloudroom`, `projects`, `threads`, each Cloud
//! thread's `workspace`, each ticket's `builder`, and `unplaced`) come
//! through one seam, [`Agents`]: its reads, which [`fleet`] records where
//! the contract does, and its placements, worked out from the records.
//! The CLI passes `FleetAgents` (`crates/cli/src/fleet.rs`), which supplies
//! CloudRoom's live project, thread and Cloud workspace reads and the
//! verified placement chain. [`NotRead`] remains for tests and for reads
//! not yet made: it records them as failed ([`AGENTS_NOT_READ`]), so every
//! builder and `unplaced` is unread and nothing claims a thread.

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Mutex;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::thread;
use std::time::{Duration, Instant};

use super::model::{
    Blocker, Check, CheckResult, CloudRoomSource, Commit, Counts, Coverage, Envelope, Failed,
    Fleet, FleetView, Freshness, Gh, GitHubSource, Issue, IssueState, ListOutcome, MergedPr,
    NeedsYou, NeedsYouKind, NonEmpty, Number, Outcome, PrFields, Project, PullRequest, Read,
    ReadId, ReadKind, Repository, Review, Reviewer, RoomCli, SchemaId, SourceName, Sources, State,
    Thread, Ticket, TicketCore, TicketState, Truncated, Unplaced, Verdict, View, WorkedOut,
};
use crate::envelope::{Completeness, GapKind};
use crate::model::Timestamp;
use crate::ops::Clock;
use crate::source::SourceError;

/// At most this many GitHub reads run at once.
pub const MAX_CONCURRENT_READS: usize = 4;

/// The reason [`NotRead`] records for CloudRoom reads not made.
pub const AGENTS_NOT_READ: &str = "not read: a ticket's agents come with A6 (#114)";

/// Why `reviewer` is undefined in version 1.
pub const NO_REVIEWER_CHAIN: &str = "no verified chain places a reviewer in version 1";

/// The labels the state table reads.
pub const READY_FOR_AGENT: &str = "ready-for-agent";
pub const READY_FOR_HUMAN: &str = "ready-for-human";
pub const HELD: &str = "held";
pub const NEEDS_INFO: &str = "needs-info";

/// A read of GitHub, as the adapter answers it: facts only, each in
/// OpenWiz's model. Every read takes a deadline, which the core derives
/// from the run's budget.
pub trait GitHub: Send + Sync {
    /// `gh`'s version, as its version text gives it.
    fn version(&self, deadline: Instant) -> Result<String, SourceError>;
    /// This repository's name and address.
    fn repository(&self, deadline: Instant) -> Result<RepositoryAnswer, SourceError>;
    /// One issue: its own fields, its sub-issues, its blocked-by links and
    /// the pull requests GitHub says close it.
    fn issue(&self, number: Number, deadline: Instant) -> Result<IssueAnswer, SourceError>;
    /// Stock-only retention of the same issue read. Legacy providers cannot
    /// establish recorded-start absence and must keep it unknown.
    fn stock_issue(
        &self,
        number: Number,
        deadline: Instant,
    ) -> Result<(IssueAnswer, crate::model::Fact<bool>), SourceError> {
        self.issue(number, deadline).map(|i| {
            (
                i,
                crate::model::Fact::Unknown(
                    "Recorded-start evidence is not retained by this provider".into(),
                ),
            )
        })
    }
    /// One pull request of this repository.
    fn pull_request(&self, number: Number, deadline: Instant) -> Result<PrAnswer, SourceError>;
    /// An open pull request's checks: the latest run of each.
    fn checks(&self, pr: Number, deadline: Instant) -> Result<Vec<Check>, SourceError>;
    /// The pull request's comments that start `VERDICT: `, oldest first,
    /// each as written.
    fn verdict_comments(&self, pr: Number, deadline: Instant) -> Result<Vec<String>, SourceError>;
    /// Whether `commit` is on `base`: true when it is.
    fn on_base(
        &self,
        commit: &Commit,
        base: &NonEmpty,
        deadline: Instant,
    ) -> Result<bool, SourceError>;
}

/// This repository: its name, its owner and name (`owner/name`, which a
/// CloudRoom project's git remote must name), and GitHub's address of it,
/// which tells this repository's items from others'. Only `name` is ever
/// printed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RepositoryAnswer {
    pub name: NonEmpty,
    pub name_with_owner: NonEmpty,
    pub url: NonEmpty,
}

/// The CloudRoom side of the `fleet` view: the seam A6 (#114) fills, with
/// `room-cli`'s reads and the verified chain.
pub trait Agents: Send + Sync {
    /// Every CloudRoom read the view needs, for this repository (`None`:
    /// it couldn't be read), within `deadline`. A read not made is failed,
    /// never left out. It runs while GitHub is read.
    fn read(&self, repository: Option<&RepositoryAnswer>, deadline: Instant) -> AgentReads;
    /// Each ticket's `builder`, one per ticket of `tickets` in its order,
    /// and `unplaced`, worked out from the envelope's `reads` alone (the
    /// contract's `placements`).
    fn place(&self, spec: Number, tickets: &[Number], reads: &[Read]) -> Placed;
}

/// The CloudRoom reads, as their outcomes. [`fleet`] records `version`
/// second, after `gh`'s, and the others last, in this order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AgentReads {
    pub version: Outcome<NonEmpty>,
    pub projects: ListOutcome<Project>,
    pub threads: ListOutcome<Thread>,
    /// Each Cloud thread's branch, by thread, in the thread list's order.
    pub workspaces: Vec<(NonEmpty, Outcome<NonEmpty>)>,
}

/// What [`Agents::place`] works out.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Placed {
    /// One per ticket, in the tickets' order.
    pub builders: Vec<WorkedOut<Option<NonEmpty>>>,
    pub unplaced: WorkedOut<Vec<Unplaced>>,
}

/// Unread agents, used by tests and to initialise reads not yet made.
/// Nothing is read from CloudRoom. Its three reads are recorded as not
/// made ([`AGENTS_NOT_READ`]), so every builder and `unplaced` is unread,
/// naming them.
#[derive(Clone, Copy, Debug, Default)]
pub struct NotRead;

impl Agents for NotRead {
    fn read(&self, _repository: Option<&RepositoryAnswer>, _deadline: Instant) -> AgentReads {
        AgentReads {
            version: Outcome::Failed(agents_not_read()),
            projects: ListOutcome::Failed(agents_not_read()),
            threads: ListOutcome::Failed(agents_not_read()),
            workspaces: Vec::new(),
        }
    }

    /// Unread, naming exactly the incomplete reads `placements` requires:
    /// the project and thread lists, the fleet's tickets, every ticket's
    /// pull request and every Cloud thread's branch.
    fn place(&self, spec: Number, tickets: &[Number], reads: &[Read]) -> Placed {
        let requires: Requires = reads
            .iter()
            .filter(|read| match &read.kind {
                ReadKind::Projects { .. } | ReadKind::Threads { .. } => true,
                ReadKind::Workspace { .. } => true,
                ReadKind::SubIssues { spec: s, .. } => *s == spec,
                ReadKind::PrDiscovery { issue, .. } => tickets.contains(issue),
                _ => false,
            })
            .map(|read| read.id)
            .collect();
        let records = Records::new(reads);
        Placed {
            builders: tickets
                .iter()
                .map(|_| records.worked_out(&requires, || None))
                .collect(),
            unplaced: records.worked_out(&requires, Vec::new),
        }
    }
}

/// An issue or pull request GitHub links to, by its number and address.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Link {
    pub number: Number,
    pub url: String,
}

/// A list GitHub gives in pages: what it listed, and its own total.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ListAnswer {
    pub nodes: Vec<Link>,
    pub total: u64,
}

/// One issue, as read.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IssueAnswer {
    pub issue: Issue,
    pub sub_issues: ListAnswer,
    pub blocked_by: ListAnswer,
    /// The pull requests GitHub says close it, in any repository.
    pub closed_by: Vec<Link>,
}

/// One pull request, as read.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PrAnswer {
    pub number: Number,
    pub draft: bool,
    pub head_branch: NonEmpty,
    pub head_commit: Commit,
    pub base_branch: NonEmpty,
    pub state: PrState,
    /// The issues it closes (GitHub's closing references), in any
    /// repository.
    pub closes: Vec<Link>,
}

/// GitHub's state of a pull request.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PrState {
    Open,
    /// Closed without a merge: never an issue's.
    Closed,
    /// GitHub says merged; merged for OpenWiz only once read back.
    Merged {
        merge_commit: Commit,
        merged_at: Timestamp,
    },
}

/// What `openwiz fleet <spec>` asks for.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FleetRequest {
    pub spec: Number,
}

/// The versions last live-tested: evidence, never a gate.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TestedVersions<'a> {
    pub github: &'a str,
    pub cloudroom: &'a str,
}

/// `openwiz fleet <spec>`: one fleet, its tickets and blockers, worked out
/// from GitHub within `budget`. Always an envelope, complete or partial.
pub fn fleet(
    request: FleetRequest,
    github: &dyn GitHub,
    agents: &dyn Agents,
    tested: TestedVersions<'_>,
    clock: &dyn Clock,
    budget: Duration,
) -> Envelope {
    let snapshot_at = clock.now();
    let run = Run {
        github,
        agents,
        clock,
        deadline: clock.monotonic() + budget,
    };
    let answers = run.read_all(request.spec);
    Assembly::new(request.spec, &answers).envelope(agents, tested, snapshot_at)
}

/// Why a read has no answer.
#[derive(Clone, Debug, PartialEq, Eq)]
enum Miss {
    /// The source failed, or answered something OpenWiz doesn't read.
    Source(SourceError),
    /// The run's budget ran out before it was made.
    Budget,
}

type Answer<T> = Result<T, Miss>;

/// One run: its source, clock and deadline.
struct Run<'a> {
    github: &'a dyn GitHub,
    agents: &'a dyn Agents,
    clock: &'a dyn Clock,
    deadline: Instant,
}

/// Every answer, by what was read.
struct Answers {
    version: Answer<String>,
    repository: Answer<RepositoryAnswer>,
    issues: BTreeMap<Number, Answer<IssueAnswer>>,
    prs: BTreeMap<Number, Answer<PrAnswer>>,
    checks: BTreeMap<Number, Answer<Vec<Check>>>,
    verdicts: BTreeMap<Number, Answer<Vec<String>>>,
    on_base: BTreeMap<Number, Answer<bool>>,
    /// CloudRoom's, through [`Agents`].
    agents: AgentReads,
}

/// One read the run may make.
#[derive(Clone)]
enum Job {
    Version,
    Repository,
    Issue(Number),
    Pr(Number),
    Checks(Number),
    Verdicts(Number),
    /// A merged pull request's merge commit, on its base.
    OnBase(Number, Commit, NonEmpty),
}

/// What a [`Job`] gave.
enum Got {
    Version(Answer<String>),
    Repository(Answer<RepositoryAnswer>),
    Issue(Number, Answer<IssueAnswer>),
    Pr(Number, Answer<PrAnswer>),
    Checks(Number, Answer<Vec<Check>>),
    Verdicts(Number, Answer<Vec<String>>),
    OnBase(Number, Answer<bool>),
}

impl Run<'_> {
    /// A read, unless the budget is spent.
    fn call<T>(&self, read: impl FnOnce(Instant) -> Result<T, SourceError>) -> Answer<T> {
        if self.clock.monotonic() >= self.deadline {
            return Err(Miss::Budget);
        }
        read(self.deadline).map_err(Miss::Source)
    }

    fn job(&self, job: &Job) -> Got {
        let gh = self.github;
        match *job {
            Job::Version => Got::Version(self.call(|d| gh.version(d))),
            Job::Repository => Got::Repository(self.call(|d| gh.repository(d))),
            Job::Issue(n) => Got::Issue(n, self.call(|d| gh.issue(n, d))),
            Job::Pr(n) => Got::Pr(n, self.call(|d| gh.pull_request(n, d))),
            Job::Checks(n) => Got::Checks(n, self.call(|d| gh.checks(n, d))),
            Job::Verdicts(n) => Got::Verdicts(n, self.call(|d| gh.verdict_comments(n, d))),
            Job::OnBase(n, ref commit, ref base) => {
                Got::OnBase(n, self.call(|d| gh.on_base(commit, base, d)))
            }
        }
    }

    /// `jobs`, at most [`MAX_CONCURRENT_READS`] at once, in any order.
    fn parallel<J: Sync, T: Send>(&self, jobs: &[J], work: impl Fn(&J) -> T + Sync) -> Vec<T> {
        let next = AtomicUsize::new(0);
        let results: Vec<Mutex<Option<T>>> = jobs.iter().map(|_| Mutex::new(None)).collect();
        thread::scope(|scope| {
            for _ in 0..MAX_CONCURRENT_READS.min(jobs.len()) {
                scope.spawn(|| {
                    loop {
                        let i = next.fetch_add(1, Ordering::SeqCst);
                        let Some(job) = jobs.get(i) else { break };
                        let got = work(job);
                        *results[i].lock().unwrap_or_else(|p| p.into_inner()) = Some(got);
                    }
                });
            }
        });
        results
            .into_iter()
            .map(|r| {
                r.into_inner()
                    .unwrap_or_else(|p| p.into_inner())
                    .expect("every job ran")
            })
            .collect()
    }

    fn jobs(&self, jobs: &[Job], answers: &mut Answers) {
        for got in self.parallel(jobs, |job| self.job(job)) {
            match got {
                Got::Version(a) => answers.version = a,
                Got::Repository(a) => answers.repository = a,
                Got::Issue(n, a) => {
                    answers.issues.insert(n, a);
                }
                Got::Pr(n, a) => {
                    answers.prs.insert(n, a);
                }
                Got::Checks(n, a) => {
                    answers.checks.insert(n, a);
                }
                Got::Verdicts(n, a) => {
                    answers.verdicts.insert(n, a);
                }
                Got::OnBase(n, a) => {
                    answers.on_base.insert(n, a);
                }
            }
        }
    }

    /// Every read the view needs, in steps: each step's reads depend on the
    /// last's answers.
    fn read_all(&self, spec: Number) -> Answers {
        let mut answers = Answers {
            version: Err(Miss::Budget),
            repository: Err(Miss::Budget),
            issues: BTreeMap::new(),
            prs: BTreeMap::new(),
            checks: BTreeMap::new(),
            verdicts: BTreeMap::new(),
            on_base: BTreeMap::new(),
            agents: NotRead.read(None, self.deadline),
        };
        self.jobs(
            &[Job::Version, Job::Repository, Job::Issue(spec)],
            &mut answers,
        );
        // CloudRoom's reads, while GitHub is read.
        let repository = answers.repository.as_ref().ok().cloned();
        let (agents, mut answers) = thread::scope(|scope| {
            let agents = scope.spawn(|| self.agents.read(repository.as_ref(), self.deadline));
            let answers = self.read_github(spec, answers);
            (agents.join(), answers)
        });
        answers.agents = agents.unwrap_or_else(|panic| std::panic::resume_unwind(panic));
        answers
    }

    /// The GitHub reads after the first step: the tickets, their blockers,
    /// their pull requests, and those pull requests' reads.
    fn read_github(&self, spec: Number, mut answers: Answers) -> Answers {
        // The tickets, then their blockers that aren't read yet.
        let tickets = Members::of(spec, &answers).tickets;
        let unread = |answers: &Answers, numbers: &BTreeSet<Number>| -> Vec<Job> {
            numbers
                .iter()
                .filter(|n| !answers.issues.contains_key(*n))
                .map(|&n| Job::Issue(n))
                .collect()
        };
        let jobs = unread(&answers, &tickets.iter().copied().collect());
        self.jobs(&jobs, &mut answers);
        let blockers = Members::of(spec, &answers).blockers;
        let jobs = unread(&answers, &blockers);
        self.jobs(&jobs, &mut answers);

        // Every pull request of this repository that GitHub says closes a
        // ticket or a blocker.
        let members = Members::of(spec, &answers);
        let mut prs = BTreeSet::new();
        if let Ok(repository) = &answers.repository {
            for n in members.discovered() {
                if let Some(Ok(issue)) = answers.issues.get(&n) {
                    prs.extend(here(&issue.closed_by, repository, PULL));
                }
            }
        }
        let jobs: Vec<Job> = prs.into_iter().map(Job::Pr).collect();
        self.jobs(&jobs, &mut answers);

        // An open pull request's checks and verdict, for a ticket; a merged
        // one's merge read back, for a ticket or a blocker. Each once.
        let mut jobs = BTreeMap::new();
        for n in members.discovered() {
            match discover(n, &answers) {
                Ok(Some(PullRequest::Open(pr))) if members.tickets.contains(&n) => {
                    jobs.insert((pr.number, 0), Job::Checks(pr.number));
                    jobs.insert((pr.number, 1), Job::Verdicts(pr.number));
                }
                Ok(Some(PullRequest::Merged(pr))) => {
                    let n = pr.fields.number;
                    jobs.insert(
                        (n, 2),
                        Job::OnBase(n, pr.merge_commit, pr.fields.base_branch),
                    );
                }
                _ => {}
            }
        }
        let jobs: Vec<Job> = jobs.into_values().collect();
        self.jobs(&jobs, &mut answers);
        answers
    }
}

/// `/pull/` or `/issues/`: which kind of item an address names.
const PULL: &str = "pull";
const ISSUES: &str = "issues";

/// The numbers of `links` that are this repository's items of `kind`,
/// by their addresses.
fn here<'a>(
    links: &'a [Link],
    repository: &'a RepositoryAnswer,
    kind: &'a str,
) -> impl Iterator<Item = Number> + 'a {
    links
        .iter()
        .filter(move |link| is_here(link, repository, kind))
        .map(|link| link.number)
}

/// Whether `link` is exactly `<repository>/<kind>/<number>`.
fn is_here(link: &Link, repository: &RepositoryAnswer, kind: &str) -> bool {
    link.url == format!("{}/{kind}/{}", repository.url.as_str(), link.number)
}

/// Who is in the view: the spec's tickets, and their blockers.
struct Members {
    tickets: Vec<Number>,
    blockers: BTreeSet<Number>,
}

impl Members {
    fn of(spec: Number, answers: &Answers) -> Self {
        let tickets = match list(spec, answers, Relation::SubIssues) {
            ListRead::Read { numbers, .. } => numbers,
            ListRead::Failed(_) => Vec::new(),
        };
        let mut blockers = BTreeSet::new();
        for &t in &tickets {
            if let ListRead::Read { numbers, .. } = list(t, answers, Relation::BlockedBy) {
                blockers.extend(numbers);
            }
        }
        Self { tickets, blockers }
    }

    /// Every issue whose pull request the view reads: the tickets and the
    /// blockers.
    fn discovered(&self) -> BTreeSet<Number> {
        self.tickets
            .iter()
            .copied()
            .chain(self.blockers.iter().copied())
            .collect()
    }
}

/// A list relation of an issue.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Relation {
    SubIssues,
    BlockedBy,
}

/// A list read, as the contract records it.
enum ListRead {
    Read {
        numbers: Vec<Number>,
        /// `Some(reason)` when GitHub listed fewer than its own total.
        truncated: Option<String>,
    },
    Failed(Failed),
}

fn failed(gap: GapKind, reason: impl Into<String>) -> Failed {
    Failed {
        gap,
        reason: NonEmpty::new(reason).unwrap_or_else(|| NonEmpty::new("unreadable").expect("text")),
    }
}

/// The contract's gap for a failed source read.
fn gap_of(error: &SourceError) -> GapKind {
    match error {
        SourceError::NotFound { .. } => GapKind::NotFound,
        SourceError::TimedOut { .. } => GapKind::TimedOut,
        SourceError::Malformed { .. } | SourceError::InvalidId { .. } => GapKind::Malformed,
        SourceError::CommandFailed { .. } | SourceError::Unavailable { .. } => {
            GapKind::CommandFailed
        }
    }
}

/// `what couldn't be read` and why, in OpenWiz's words.
fn missed(miss: &Miss, what: &str) -> Failed {
    match miss {
        Miss::Source(error) => failed(gap_of(error), format!("{what} couldn't be read: {error}")),
        Miss::Budget => failed(
            GapKind::BudgetExhausted,
            format!("{what} wasn't read: the run's time ran out first"),
        ),
    }
}

/// The spec's sub-issues or a ticket's blockers, checked: this
/// repository's issues, each once, never the issue itself, ascending.
fn list(number: Number, answers: &Answers, relation: Relation) -> ListRead {
    let (noun, plural) = match relation {
        Relation::SubIssues => ("sub-issue", "sub-issues"),
        Relation::BlockedBy => ("blocker", "blockers"),
    };
    let issue = match answers.issues.get(&number) {
        Some(Ok(issue)) => issue,
        Some(Err(miss)) => return ListRead::Failed(missed(miss, &format!("#{number}"))),
        None => return ListRead::Failed(missed(&Miss::Budget, &format!("#{number}"))),
    };
    let repository = match &answers.repository {
        Ok(repository) => repository,
        Err(miss) => {
            let why = missed(miss, "this repository");
            return ListRead::Failed(failed(
                why.gap,
                format!(
                    "#{number}'s {plural} can't be told from other repositories' issues: {}",
                    why.reason.as_str()
                ),
            ));
        }
    };
    let answer = match relation {
        Relation::SubIssues => &issue.sub_issues,
        Relation::BlockedBy => &issue.blocked_by,
    };
    if answer.nodes.iter().any(|l| !is_here(l, repository, ISSUES)) {
        return ListRead::Failed(failed(
            GapKind::Malformed,
            format!(
                "#{number}'s {plural} include an issue of another repository; OpenWiz reads one \
                 repository"
            ),
        ));
    }
    let mut numbers: Vec<Number> = answer.nodes.iter().map(|l| l.number).collect();
    numbers.sort_unstable();
    if numbers.windows(2).any(|w| w[0] == w[1]) {
        return ListRead::Failed(failed(
            GapKind::Malformed,
            format!("GitHub listed one of #{number}'s {plural} twice"),
        ));
    }
    if numbers.contains(&number) {
        return ListRead::Failed(failed(
            GapKind::Malformed,
            format!("GitHub listed #{number} as its own {noun}"),
        ));
    }
    let listed = numbers.len() as u64;
    let truncated = match listed.cmp(&answer.total) {
        std::cmp::Ordering::Equal => None,
        std::cmp::Ordering::Less => Some(format!(
            "GitHub listed {listed} of #{number}'s {} {plural}",
            answer.total
        )),
        std::cmp::Ordering::Greater => {
            return ListRead::Failed(failed(
                GapKind::Malformed,
                format!(
                    "GitHub listed {listed} of #{number}'s {plural}, more than its total of {}",
                    answer.total
                ),
            ));
        }
    };
    ListRead::Read { numbers, truncated }
}

/// `pr_discovery` for issue `n`: the pull request of this repository that
/// GitHub says closes it, open or merged; `None`: none does. The merged one
/// if there is exactly one, otherwise the one open one when none is merged;
/// two or more open ones with none merged, or two or more merged ones, are
/// `several`, so none is its own. A closed, unmerged one is never its.
fn discover(n: Number, answers: &Answers) -> Result<Option<PullRequest>, Failed> {
    let issue = match answers.issues.get(&n) {
        Some(Ok(issue)) => issue,
        Some(Err(miss)) => return Err(missed(miss, &format!("#{n}"))),
        None => return Err(missed(&Miss::Budget, &format!("#{n}"))),
    };
    let repository = match &answers.repository {
        Ok(repository) => repository,
        Err(miss) => {
            let why = missed(miss, "this repository");
            return Err(failed(
                why.gap,
                format!(
                    "#{n}'s pull requests can't be told from other repositories': {}",
                    why.reason.as_str()
                ),
            ));
        }
    };
    let mut open = Vec::new();
    let mut merged = Vec::new();
    let mut numbers: Vec<Number> = here(&issue.closed_by, repository, PULL).collect();
    numbers.sort_unstable();
    numbers.dedup();
    for number in numbers {
        let pr = match answers.prs.get(&number) {
            Some(Ok(pr)) => pr,
            Some(Err(miss)) => return Err(missed(miss, &format!("pull request #{number}"))),
            None => return Err(missed(&Miss::Budget, &format!("pull request #{number}"))),
        };
        let fields = pr_fields(pr, repository)?;
        if !fields.closes.contains(&n) {
            return Err(failed(
                GapKind::Malformed,
                format!(
                    "GitHub says pull request #{number} closes #{n}, but its closing references \
                     don't name #{n}"
                ),
            ));
        }
        match &pr.state {
            PrState::Open => open.push(fields),
            PrState::Closed => {}
            PrState::Merged {
                merge_commit,
                merged_at,
            } => merged.push(MergedPr {
                fields,
                merge_commit: merge_commit.clone(),
                merged_at: *merged_at,
            }),
        }
    }
    let several = |numbers: Vec<Number>| Some(PullRequest::Several { numbers });
    Ok(match (merged.len(), open.len()) {
        (1, _) => merged.pop().map(PullRequest::Merged),
        (0, 0) => None,
        (0, 1) => open.pop().map(PullRequest::Open),
        (0, _) => several(open.iter().map(|p| p.number).collect()),
        _ => several(merged.iter().map(|p| p.fields.number).collect()),
    })
}

/// A pull request's own fields: the issues it closes are this
/// repository's, ascending, each once. One that also closes an issue of
/// another repository fails: `closes` can't name that issue, and without it
/// the pull request would look as if it closed its ticket alone.
fn pr_fields(pr: &PrAnswer, repository: &RepositoryAnswer) -> Result<PrFields, Failed> {
    if pr
        .closes
        .iter()
        .any(|link| !is_here(link, repository, ISSUES))
    {
        return Err(failed(
            GapKind::Malformed,
            format!(
                "pull request #{} also closes an issue of another repository; OpenWiz reads one \
                 repository",
                pr.number
            ),
        ));
    }
    let mut closes: Vec<Number> = here(&pr.closes, repository, ISSUES).collect();
    closes.sort_unstable();
    if closes.windows(2).any(|w| w[0] == w[1]) {
        return Err(failed(
            GapKind::Malformed,
            format!(
                "GitHub listed an issue twice among pull request #{}'s closing references",
                pr.number
            ),
        ));
    }
    Ok(PrFields {
        number: pr.number,
        draft: pr.draft,
        head_branch: pr.head_branch.clone(),
        head_commit: pr.head_commit.clone(),
        base_branch: pr.base_branch.clone(),
        closes,
    })
}

/// The latest verdict, from the comments that start `VERDICT: `: the last
/// one, in `review-ticket`'s form, or a failure when it isn't.
fn verdict(pr: Number, comments: &[String]) -> Result<Option<Review>, Failed> {
    let Some(latest) = comments.last() else {
        return Ok(None);
    };
    let line = latest.split('\n').next().unwrap_or_default();
    let line = line.strip_suffix('\r').unwrap_or(line);
    let parsed = line.strip_prefix("VERDICT: ").and_then(|rest| {
        let (word, commit) = rest.split_once(" at ")?;
        let verdict = match word {
            "APPROVE" => Verdict::Approve,
            "CHANGES" => Verdict::Changes,
            _ => return None,
        };
        Some(Review {
            verdict,
            commit: Commit::parse(commit)?,
        })
    });
    match parsed {
        Some(review) => Ok(Some(review)),
        None => Err(failed(
            GapKind::Malformed,
            format!(
                "pull request #{pr}'s latest VERDICT comment isn't review-ticket's form \
                 (VERDICT: APPROVE or CHANGES at a full commit)"
            ),
        )),
    }
}

/// Checks, each name once, by name.
fn checked(pr: Number, mut checks: Vec<Check>) -> Result<Vec<Check>, Failed> {
    checks.sort_by(|a, b| a.name.cmp(&b.name));
    if checks.windows(2).any(|w| w[0].name == w[1].name) {
        return Err(failed(
            GapKind::Malformed,
            format!("GitHub listed one check of pull request #{pr} twice"),
        ));
    }
    Ok(checks)
}

// ---------------------------------------------------------------------
// Working values out from the records. Public, so `fleets` (A4) and
// `fleet` share one state table, one read rule, one `merged` and one
// "needs you" (the orchestrator on #113, 2026-11-01).
// ---------------------------------------------------------------------

/// What a value requires: reads, by id.
pub type Requires = BTreeSet<ReadId>;

/// The reads of one envelope, by id: every worked-out value is worked out
/// from these alone.
pub struct Records<'a> {
    by_id: BTreeMap<ReadId, &'a Read>,
}

impl<'a> Records<'a> {
    pub fn new(reads: &'a [Read]) -> Self {
        Self {
            by_id: reads.iter().map(|r| (r.id, r)).collect(),
        }
    }

    /// The read with this id.
    pub fn get(&self, id: ReadId) -> Option<&'a Read> {
        self.by_id.get(&id).copied()
    }

    /// Whether the read is on the record and complete. A read that isn't
    /// on the record is reported like a failed one.
    pub fn complete(&self, id: ReadId) -> bool {
        let Some(read) = self.get(id) else {
            return false;
        };
        match &read.kind {
            ReadKind::Version { outcome, .. } | ReadKind::Workspace { outcome, .. } => {
                matches!(outcome, Outcome::Complete { .. })
            }
            ReadKind::Repository { outcome } => matches!(outcome, Outcome::Complete { .. }),
            ReadKind::Issue { outcome, .. } => matches!(outcome, Outcome::Complete { .. }),
            ReadKind::PrDiscovery { outcome, .. } => matches!(outcome, Outcome::Complete { .. }),
            ReadKind::Comments { outcome, .. } => matches!(outcome, Outcome::Complete { .. }),
            ReadKind::MergeReadback { outcome, .. } => {
                matches!(outcome, Outcome::Complete { .. })
            }
            ReadKind::SpecList { outcome }
            | ReadKind::SubIssues { outcome, .. }
            | ReadKind::BlockedBy { outcome, .. } => {
                matches!(outcome, ListOutcome::Complete { .. })
            }
            ReadKind::Checks { outcome, .. } => matches!(outcome, ListOutcome::Complete { .. }),
            ReadKind::Projects { outcome } => matches!(outcome, ListOutcome::Complete { .. }),
            ReadKind::Threads { outcome } => matches!(outcome, ListOutcome::Complete { .. }),
        }
    }

    /// The read rule: `{"known": value()}` when every read in `requires` is
    /// complete, otherwise exactly the incomplete ones, in id order (the
    /// order of `reads`).
    pub fn worked_out<T>(&self, requires: &Requires, value: impl FnOnce() -> T) -> WorkedOut<T> {
        let unread: Vec<ReadId> = requires
            .iter()
            .copied()
            .filter(|&id| !self.complete(id))
            .collect();
        if unread.is_empty() {
            WorkedOut::Known(value())
        } else {
            WorkedOut::Unread(unread)
        }
    }

    /// An `issue` read's value, when complete.
    pub fn issue(&self, id: ReadId) -> Option<&'a Issue> {
        match self.get(id).map(|r| &r.kind) {
            Some(ReadKind::Issue {
                outcome: Outcome::Complete { value },
                ..
            }) => Some(value),
            _ => None,
        }
    }

    /// A `sub_issues`, `blocked_by` or `spec_list` read's value: what was
    /// read, complete or partial.
    pub fn list(&self, id: ReadId) -> Option<&'a [Number]> {
        match self.get(id).map(|r| &r.kind) {
            Some(
                ReadKind::BlockedBy { outcome, .. }
                | ReadKind::SubIssues { outcome, .. }
                | ReadKind::SpecList { outcome },
            ) => match outcome {
                ListOutcome::Complete { value } | ListOutcome::Partial { value, .. } => Some(value),
                ListOutcome::Failed(_) => None,
            },
            _ => None,
        }
    }

    /// A `pr_discovery` read's value, when complete.
    pub fn pull_request(&self, id: ReadId) -> Option<&'a Option<PullRequest>> {
        match self.get(id).map(|r| &r.kind) {
            Some(ReadKind::PrDiscovery {
                outcome: Outcome::Complete { value },
                ..
            }) => Some(value),
            _ => None,
        }
    }

    /// A `checks` read's value, when complete.
    pub fn checks(&self, id: ReadId) -> Option<&'a [Check]> {
        match self.get(id).map(|r| &r.kind) {
            Some(ReadKind::Checks {
                outcome: ListOutcome::Complete { value },
                ..
            }) => Some(value),
            _ => None,
        }
    }

    /// A `comments` read's value (the latest verdict), when complete.
    pub fn review(&self, id: ReadId) -> Option<&'a Option<Review>> {
        match self.get(id).map(|r| &r.kind) {
            Some(ReadKind::Comments {
                outcome: Outcome::Complete { value },
                ..
            }) => Some(value),
            _ => None,
        }
    }

    /// A `merge_readback` read's value, when complete.
    pub fn on_base(&self, id: ReadId) -> Option<bool> {
        match self.get(id).map(|r| &r.kind) {
            Some(ReadKind::MergeReadback {
                outcome: Outcome::Complete { value },
                ..
            }) => Some(*value),
            _ => None,
        }
    }

    /// A `version` read's value, when complete.
    pub fn version(&self, id: ReadId) -> Option<&'a str> {
        match self.get(id).map(|r| &r.kind) {
            Some(ReadKind::Version {
                outcome: Outcome::Complete { value },
                ..
            }) => Some(value.as_str()),
            _ => None,
        }
    }

    /// Whether every read is complete: the envelope's coverage.
    pub fn coverage(&self) -> Completeness {
        if self.by_id.keys().all(|&id| self.complete(id)) {
            Completeness::Complete
        } else {
            Completeness::Partial
        }
    }
}

/// What CI says, worked out from the checks.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ci {
    /// A check failed or was cancelled.
    Failed,
    /// None failed, and one is still running.
    Pending,
    /// None failed or is running, and one passed.
    Passed,
    /// No check, or all skipped.
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

/// A ticket's pointers to its own reads: `ci`, `review` and `on_base` are
/// `None` when their pull request isn't open, or merged.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TicketReads {
    pub issue: ReadId,
    pub blocked_by: ReadId,
    pub pr: ReadId,
    pub ci: Option<ReadId>,
    pub review: Option<ReadId>,
    pub on_base: Option<ReadId>,
}

/// What a blocker's `merged` reads: its `pr_discovery`, and its merge
/// read back (`None` when its pull request isn't merged).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct BlockerReads {
    pub pr: ReadId,
    pub on_base: Option<ReadId>,
}

/// `blocker.merged` requires `blocker.pr` and `blocker.on_base`.
pub fn merged_requires(blocker: &BlockerReads) -> Requires {
    let mut requires = Requires::from([blocker.pr]);
    requires.extend(blocker.on_base);
    requires
}

/// A blocker's verified merge: `true` only when its pull request is merged
/// and its merge was read back on its base.
pub fn merged(records: &Records<'_>, blocker: &BlockerReads) -> WorkedOut<bool> {
    records.worked_out(&merged_requires(blocker), || {
        is_merged(records, blocker.pr, blocker.on_base)
    })
}

/// Merged and read back: GitHub's `merged` alone is never enough.
fn is_merged(records: &Records<'_>, pr: ReadId, on_base: Option<ReadId>) -> bool {
    matches!(records.pull_request(pr), Some(Some(PullRequest::Merged(_))))
        && on_base.and_then(|id| records.on_base(id)) == Some(true)
}

/// `ticket.state` requires the ticket's own reads, its pull request's, and
/// each of its blockers' `merged`.
pub fn state_requires(ticket: &TicketReads, blockers: &[BlockerReads]) -> Requires {
    let mut requires = Requires::from([ticket.issue, ticket.blocked_by, ticket.pr]);
    requires.extend(
        [ticket.ci, ticket.review, ticket.on_base]
            .into_iter()
            .flatten(),
    );
    for blocker in blockers {
        requires.extend(merged_requires(blocker));
    }
    requires
}

/// A ticket's state: the state table, only when every read it requires
/// is complete. `blockers` are the blockers its `blocked_by` read lists.
pub fn state(records: &Records<'_>, ticket: &TicketReads, blockers: &[BlockerReads]) -> State {
    match records.worked_out(&state_requires(ticket, blockers), || {
        state_table(records, ticket, blockers)
    }) {
        WorkedOut::Known(Ok(state)) => State::Known(state),
        WorkedOut::Known(Err(reason)) => State::Unknown(reason),
        WorkedOut::Unread(ids) => State::Unread(ids),
    }
}

/// The state table, in its order: the first rule that matches wins.
fn state_table(
    records: &Records<'_>,
    ticket: &TicketReads,
    blockers: &[BlockerReads],
) -> Result<TicketState, NonEmpty> {
    let unknown = |why: &str| Err(NonEmpty::new(why).expect("a reason"));
    let Some(issue) = records.issue(ticket.issue) else {
        return unknown("its issue couldn't be read");
    };
    let has = |label: &str| issue.labels.iter().any(|l| l.as_str() == label);
    let Some(pr) = records.pull_request(ticket.pr) else {
        return unknown("its pull request couldn't be read");
    };
    // 1. Merged, and read back on its base.
    if is_merged(records, ticket.pr, ticket.on_base) {
        return Ok(TicketState::Merged);
    }
    // 2. Closed on GitHub, with no merge read back.
    if issue.state == IssueState::Closed {
        return unknown("closed on GitHub, and no merge was read back");
    }
    // 3. Held.
    if has(HELD) {
        return Ok(TicketState::Held);
    }
    match pr {
        Some(PullRequest::Open(open)) => {
            let review = ticket
                .review
                .and_then(|id| records.review(id))
                .cloned()
                .flatten();
            let checks = ticket
                .ci
                .and_then(|id| records.checks(id))
                .unwrap_or_default();
            // 4. Changes asked for on its head.
            if review.is_some_and(|r| r.verdict == Verdict::Changes && r.commit == open.head_commit)
            {
                return Ok(TicketState::ChangesRequested);
            }
            // 5. A draft, or CI not passed.
            if open.draft || ci(checks) != Ci::Passed {
                return Ok(TicketState::Building);
            }
            // 6. Waiting for a verdict, or approved and waiting to merge.
            Ok(TicketState::InReview)
        }
        None => {
            // 7. Not approved yet.
            if !has(READY_FOR_AGENT) && !has(READY_FOR_HUMAN) {
                return unknown("no pull request, and no ready label: not approved yet");
            }
            // 8. A blocker not merged.
            if blockers
                .iter()
                .any(|b| !is_merged(records, b.pr, b.on_base))
            {
                return Ok(TicketState::Blocked);
            }
            // 9. Ready.
            if has(READY_FOR_AGENT) {
                return Ok(TicketState::Ready);
            }
            // 10.
            unknown("no pull request, every blocker merged, and ready for a human only")
        }
        // 10. Anything else.
        Some(PullRequest::Several { .. }) => {
            unknown("several pull requests close it, so none is its own")
        }
        Some(PullRequest::Merged(_)) => {
            unknown("its pull request is merged, but the merge wasn't found on its base")
        }
    }
}

/// How many tickets are in each state.
pub fn counts<'s>(states: impl IntoIterator<Item = &'s State>) -> Counts {
    let mut counts = Counts::default();
    for state in states {
        counts.tickets += 1;
        match state {
            State::Known(TicketState::Ready) => counts.ready += 1,
            State::Known(TicketState::Building) => counts.building += 1,
            State::Known(TicketState::InReview) => counts.in_review += 1,
            State::Known(TicketState::ChangesRequested) => counts.changes_requested += 1,
            State::Known(TicketState::Merged) => counts.merged += 1,
            State::Known(TicketState::Held) => counts.held += 1,
            State::Known(TicketState::Blocked) => counts.blocked += 1,
            State::Unknown(_) | State::Unread(_) => counts.unknown += 1,
        }
    }
    counts
}

/// A fleet's `progress`: its tickets by state. It requires the fleet's
/// ticket list (`tickets_read`) and every ticket's `state`.
pub fn progress(
    records: &Records<'_>,
    tickets_read: ReadId,
    tickets: &[(TicketReads, Vec<BlockerReads>)],
) -> WorkedOut<Counts> {
    let mut requires = Requires::from([tickets_read]);
    for (ticket, blockers) in tickets {
        requires.extend(state_requires(ticket, blockers));
    }
    records.worked_out(&requires, || {
        let states: Vec<State> = tickets
            .iter()
            .map(|(ticket, blockers)| state(records, ticket, blockers))
            .collect();
        counts(&states)
    })
}

/// "Needs you": for each ticket, in order, a `held` item for the `held`
/// label and a `needs_info` item for the `needs-info` label (by spec,
/// ticket, then kind, the kind by its name, as A2's `check.py` evaluates
/// the contract's rule). It requires
/// the reads that list the fleets and their tickets (`lists`) and each
/// ticket's `issue` read. `tickets` are `(spec, ticket, issue read)`, by
/// spec then ticket.
pub fn needs_you(
    records: &Records<'_>,
    lists: &Requires,
    tickets: &[(Number, Number, ReadId)],
) -> WorkedOut<Vec<NeedsYou>> {
    let mut requires = lists.clone();
    requires.extend(tickets.iter().map(|&(_, _, issue)| issue));
    records.worked_out(&requires, || {
        let mut items = Vec::new();
        for &(spec, ticket, issue) in tickets {
            let Some(issue) = records.issue(issue) else {
                continue;
            };
            // By kind's name, as the contract's check orders them.
            for (label, kind) in [
                (HELD, NeedsYouKind::Held),
                (NEEDS_INFO, NeedsYouKind::NeedsInfo),
            ] {
                if issue.labels.iter().any(|l| l.as_str() == label) {
                    items.push(super::fleets::needs_you_item(
                        kind,
                        spec,
                        ticket,
                        issue,
                        super::fleets::QUESTION_NOT_FOUND,
                    ));
                }
            }
        }
        items
    })
}

/// A blocker's `fleet`: the lowest spec, of `fleets` (each a spec and its
/// `sub_issues` read), whose tickets name it; `None` when none does. It
/// requires `lists`, the reads that list the fleets and their tickets.
pub fn blocker_fleet(
    records: &Records<'_>,
    lists: &Requires,
    fleets: &[(Number, ReadId)],
    blocker: Number,
) -> WorkedOut<Option<Number>> {
    records.worked_out(lists, || {
        fleets
            .iter()
            .filter(|(_, tickets)| records.list(*tickets).is_some_and(|t| t.contains(&blocker)))
            .map(|(spec, _)| *spec)
            .min()
    })
}

// ---------------------------------------------------------------------
// The `fleet <spec>` view: the records, then every value from them.
// ---------------------------------------------------------------------

/// The records, in the order of `reads`, and each one's id by its kind and
/// subject.
struct Assembly {
    spec: Number,
    reads: Vec<Read>,
    ids: Ids,
    tickets: Vec<Number>,
    blockers: Vec<Number>,
}

/// Each record's id, by its kind and subject.
#[derive(Default)]
struct Ids {
    github_version: Option<ReadId>,
    cloudroom_version: Option<ReadId>,
    repository: Option<ReadId>,
    issue: BTreeMap<Number, ReadId>,
    sub_issues: BTreeMap<Number, ReadId>,
    blocked_by: BTreeMap<Number, ReadId>,
    pr_discovery: BTreeMap<Number, ReadId>,
    checks: BTreeMap<Number, ReadId>,
    comments: BTreeMap<Number, ReadId>,
    merge_readback: BTreeMap<Number, ReadId>,
    projects: Option<ReadId>,
    threads: Option<ReadId>,
}

impl Assembly {
    fn new(spec: Number, answers: &Answers) -> Self {
        let members = Members::of(spec, answers);
        let mut assembly = Self {
            spec,
            reads: Vec::new(),
            ids: Ids::default(),
            tickets: members.tickets,
            blockers: members.blockers.into_iter().collect(),
        };
        assembly.record_all(answers);
        assembly
    }

    fn push(&mut self, kind: ReadKind) -> ReadId {
        let id = ReadId(u32::try_from(self.reads.len() + 1).expect("fewer reads than u32"));
        self.reads.push(Read { id, kind });
        id
    }

    /// Every record, in the contract's order: the versions, the repository,
    /// the spec, each ticket with its pull request's reads, each blocker
    /// that isn't a ticket, then CloudRoom's.
    fn record_all(&mut self, answers: &Answers) {
        let version = match &answers.version {
            Ok(text) => match NonEmpty::new(text.clone()) {
                Some(v) => Outcome::Complete { value: v },
                None => Outcome::Failed(failed(
                    GapKind::UntestedVersion,
                    "gh --version printed no version",
                )),
            },
            Err(miss) => {
                let why = missed(miss, "gh --version");
                Outcome::Failed(failed(GapKind::UntestedVersion, why.reason.as_str()))
            }
        };
        self.ids.github_version = Some(self.push(ReadKind::Version {
            source: SourceName::Github,
            outcome: version,
        }));
        self.ids.cloudroom_version = Some(self.push(ReadKind::Version {
            source: SourceName::Cloudroom,
            outcome: answers.agents.version.clone(),
        }));
        let repository = match &answers.repository {
            Ok(r) => Outcome::Complete {
                value: Repository {
                    name: r.name.clone(),
                },
            },
            Err(miss) => Outcome::Failed(missed(miss, "this repository")),
        };
        self.ids.repository = Some(self.push(ReadKind::Repository {
            outcome: repository,
        }));

        let spec = self.spec;
        self.record_issue(spec, answers);
        let outcome = list_outcome(list(spec, answers, Relation::SubIssues));
        let id = self.push(ReadKind::SubIssues { spec, outcome });
        self.ids.sub_issues.insert(spec, id);

        for t in self.tickets.clone() {
            self.record_issue(t, answers);
            let outcome = list_outcome(list(t, answers, Relation::BlockedBy));
            let id = self.push(ReadKind::BlockedBy { ticket: t, outcome });
            self.ids.blocked_by.insert(t, id);
            self.record_discovery(t, true, answers);
        }
        for b in self.blockers.clone() {
            if !self.tickets.contains(&b) {
                self.record_issue(b, answers);
                self.record_discovery(b, false, answers);
            }
        }

        let agents = &answers.agents;
        self.ids.projects = Some(self.push(ReadKind::Projects {
            outcome: agents.projects.clone(),
        }));
        self.ids.threads = Some(self.push(ReadKind::Threads {
            outcome: agents.threads.clone(),
        }));
        for (thread, outcome) in &agents.workspaces {
            self.push(ReadKind::Workspace {
                thread: thread.clone(),
                outcome: outcome.clone(),
            });
        }
    }

    /// An issue's own record, once.
    fn record_issue(&mut self, n: Number, answers: &Answers) {
        if self.ids.issue.contains_key(&n) {
            return;
        }
        let outcome = match answers.issues.get(&n) {
            Some(Ok(answer)) => Outcome::Complete {
                value: answer.issue.clone(),
            },
            Some(Err(miss)) => Outcome::Failed(missed(miss, &format!("#{n}"))),
            None => Outcome::Failed(missed(&Miss::Budget, &format!("#{n}"))),
        };
        let id = self.push(ReadKind::Issue { issue: n, outcome });
        self.ids.issue.insert(n, id);
    }

    /// An issue's `pr_discovery`, then its pull request's reads, each
    /// recorded once: checks and comments for a ticket's open one, the
    /// merge read back for a merged one.
    fn record_discovery(&mut self, n: Number, ticket: bool, answers: &Answers) {
        let found = discover(n, answers);
        let outcome = match &found {
            Ok(pr) => Outcome::Complete { value: pr.clone() },
            Err(why) => Outcome::Failed(why.clone()),
        };
        let id = self.push(ReadKind::PrDiscovery { issue: n, outcome });
        self.ids.pr_discovery.insert(n, id);
        match found {
            Ok(Some(PullRequest::Open(pr))) if ticket => {
                let pr = pr.number;
                if !self.ids.checks.contains_key(&pr) {
                    let what = format!("the checks of pull request #{pr}");
                    let outcome = match answers.checks.get(&pr) {
                        Some(Ok(checks)) => match checked(pr, checks.clone()) {
                            Ok(value) => ListOutcome::Complete { value },
                            Err(why) => ListOutcome::Failed(why),
                        },
                        Some(Err(miss)) => ListOutcome::Failed(missed(miss, &what)),
                        None => ListOutcome::Failed(missed(&Miss::Budget, &what)),
                    };
                    let id = self.push(ReadKind::Checks { pr, outcome });
                    self.ids.checks.insert(pr, id);
                }
                if !self.ids.comments.contains_key(&pr) {
                    let what = format!("the comments of pull request #{pr}");
                    let outcome = match answers.verdicts.get(&pr) {
                        Some(Ok(comments)) => match verdict(pr, comments) {
                            Ok(value) => Outcome::Complete { value },
                            Err(why) => Outcome::Failed(why),
                        },
                        Some(Err(miss)) => Outcome::Failed(missed(miss, &what)),
                        None => Outcome::Failed(missed(&Miss::Budget, &what)),
                    };
                    let id = self.push(ReadKind::Comments { pr, outcome });
                    self.ids.comments.insert(pr, id);
                }
            }
            Ok(Some(PullRequest::Merged(pr))) => {
                let pr = pr.fields.number;
                if !self.ids.merge_readback.contains_key(&pr) {
                    let what = format!("the merge of pull request #{pr}, on its base,");
                    let outcome = match answers.on_base.get(&pr) {
                        Some(Ok(there)) => Outcome::Complete { value: *there },
                        Some(Err(miss)) => Outcome::Failed(missed(miss, &what)),
                        None => Outcome::Failed(missed(&Miss::Budget, &what)),
                    };
                    let id = self.push(ReadKind::MergeReadback { pr, outcome });
                    self.ids.merge_readback.insert(pr, id);
                }
            }
            _ => {}
        }
    }

    /// The pointers of issue `n`'s pull request reads: `ci`, `review`,
    /// `on_base`, by its `pr_discovery` record.
    fn pr_pointers(
        &self,
        records: &Records<'_>,
        n: Number,
    ) -> (Option<ReadId>, Option<ReadId>, Option<ReadId>) {
        match records.pull_request(self.ids.pr_discovery[&n]) {
            Some(Some(PullRequest::Open(pr))) => (
                self.ids.checks.get(&pr.number).copied(),
                self.ids.comments.get(&pr.number).copied(),
                None,
            ),
            Some(Some(PullRequest::Merged(pr))) => (
                None,
                None,
                self.ids.merge_readback.get(&pr.fields.number).copied(),
            ),
            _ => (None, None, None),
        }
    }

    fn ticket_reads(&self, records: &Records<'_>, t: Number) -> TicketReads {
        let (ci, review, on_base) = self.pr_pointers(records, t);
        TicketReads {
            issue: self.ids.issue[&t],
            blocked_by: self.ids.blocked_by[&t],
            pr: self.ids.pr_discovery[&t],
            ci,
            review,
            on_base,
        }
    }

    fn blocker_reads(&self, records: &Records<'_>, b: Number) -> BlockerReads {
        BlockerReads {
            pr: self.ids.pr_discovery[&b],
            on_base: self.pr_pointers(records, b).2,
        }
    }

    /// A ticket's reads, and its blockers' (those its `blocked_by` read
    /// lists).
    fn with_blockers(&self, records: &Records<'_>, t: Number) -> (TicketReads, Vec<BlockerReads>) {
        let ticket = self.ticket_reads(records, t);
        let blockers = records
            .list(ticket.blocked_by)
            .unwrap_or_default()
            .iter()
            .map(|&b| self.blocker_reads(records, b))
            .collect();
        (ticket, blockers)
    }

    fn envelope(
        &self,
        agents: &dyn Agents,
        tested: TestedVersions<'_>,
        snapshot_at: Timestamp,
    ) -> Envelope {
        let records = Records::new(&self.reads);
        let spec = self.spec;
        let lists = Requires::from([self.ids.sub_issues[&spec]]);
        // Each builder and `unplaced`, from the records: the `placements`.
        let placed = agents.place(spec, &self.tickets, &self.reads);
        assert_eq!(
            placed.builders.len(),
            self.tickets.len(),
            "Agents::place gives one builder per ticket"
        );

        let ticket_reads: Vec<(TicketReads, Vec<BlockerReads>)> = self
            .tickets
            .iter()
            .map(|&t| self.with_blockers(&records, t))
            .collect();
        let tickets: Vec<Ticket> = self
            .tickets
            .iter()
            .zip(&ticket_reads)
            .zip(placed.builders)
            .map(|((&number, (reads, blockers)), builder)| Ticket {
                core: TicketCore {
                    number,
                    issue: reads.issue,
                    blocked_by: reads.blocked_by,
                    pr: reads.pr,
                    ci: reads.ci,
                    review: reads.review,
                    on_base: reads.on_base,
                    state: state(&records, reads, blockers),
                },
                builder,
                reviewer: Reviewer::Undefined(NonEmpty::new(NO_REVIEWER_CHAIN).expect("text")),
            })
            .collect();
        let fleets = [(spec, self.ids.sub_issues[&spec])];
        let blockers = self
            .blockers
            .iter()
            .map(|&b| {
                let reads = self.blocker_reads(&records, b);
                Blocker {
                    number: b,
                    issue: self.ids.issue[&b],
                    pr: reads.pr,
                    on_base: reads.on_base,
                    fleet: blocker_fleet(&records, &lists, &fleets, b),
                    merged: merged(&records, &reads),
                }
            })
            .collect();
        let needs: Vec<(Number, Number, ReadId)> = self
            .tickets
            .iter()
            .map(|&t| (spec, t, self.ids.issue[&t]))
            .collect();
        let github_version = self.ids.github_version.expect("recorded");
        let cloudroom_version = self.ids.cloudroom_version.expect("recorded");
        Envelope {
            schema: SchemaId::V1,
            sources: Sources {
                github: GitHubSource {
                    name: Gh::Gh,
                    version: github_version,
                    tested_version: tested.github.to_owned(),
                    version_tested: records.version(github_version) == Some(tested.github),
                },
                cloudroom: Some(CloudRoomSource {
                    name: RoomCli::RoomCli,
                    version: cloudroom_version,
                    tested_version: tested.cloudroom.to_owned(),
                    version_tested: records.version(cloudroom_version) == Some(tested.cloudroom),
                }),
            },
            reads: self.reads.clone(),
            coverage: Coverage {
                state: records.coverage(),
            },
            freshness: Freshness { snapshot_at },
            data: View::Fleet(FleetView {
                repository: self.ids.repository.expect("recorded"),
                projects: self.ids.projects.expect("recorded"),
                threads: self.ids.threads.expect("recorded"),
                fleet: Fleet {
                    spec,
                    issue: self.ids.issue[&spec],
                    tickets: self.ids.sub_issues[&spec],
                    progress: progress(&records, self.ids.sub_issues[&spec], &ticket_reads),
                },
                tickets,
                blockers,
                needs_you: needs_you(&records, &lists, &needs),
                unplaced: placed.unplaced,
            }),
        }
    }
}

/// A CloudRoom read not made, as recorded by [`NotRead`].
fn agents_not_read() -> Failed {
    failed(GapKind::BudgetExhausted, AGENTS_NOT_READ)
}

fn list_outcome(read: ListRead) -> ListOutcome<Number> {
    match read {
        ListRead::Read {
            numbers,
            truncated: None,
        } => ListOutcome::Complete { value: numbers },
        ListRead::Read {
            numbers,
            truncated: Some(reason),
        } => ListOutcome::Partial {
            gap: Truncated::Truncated,
            reason: NonEmpty::new(reason).expect("a reason"),
            value: numbers,
        },
        ListRead::Failed(why) => ListOutcome::Failed(why),
    }
}

/// The fleet's own failure, when its spec's sub-issue list couldn't be
/// read at all, so no ticket is known.
pub fn fleet_unreadable(envelope: &Envelope) -> Option<&Failed> {
    let View::Fleet(view) = &envelope.data else {
        return None;
    };
    envelope.reads.iter().find_map(|read| match &read.kind {
        ReadKind::SubIssues {
            outcome: ListOutcome::Failed(why),
            ..
        } if read.id == view.fleet.tickets => Some(why),
        _ => None,
    })
}
