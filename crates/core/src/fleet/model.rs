//! The `openwiz.fleet.v1` envelope as Rust types (A3, ClosedWiz#111): the
//! read records, their outcomes, the worked-out values, the ticket states
//! and the two views of `contracts/fleet.v1.md` and
//! `contracts/fleet.v1.schema.json`, which they match exactly. **Data
//! only**: printing them gives the contract's JSON; working the values out
//! (the read rule, the state table, merged, the verified chain) is A4's,
//! A5's and A6's.
//!
//! A value that can only be one string is a type with one value
//! ([`SchemaId`], [`Gh`], [`RoomCli`], [`Truncated`]); text that must not
//! be empty is a [`NonEmpty`], a commit a [`Commit`], a read's id a
//! [`ReadId`] and an issue or pull request number a [`Number`], so none can
//! hold a value the schema refuses.
//!
//! These types only print. Anything read from outside is read by a
//! hand-written strict reader, never a derived one (the contract, "Reading
//! it").

use std::num::NonZeroU64;

use serde::Serialize;

use crate::envelope::{Completeness, GapKind};
use crate::model::{Fact, Timestamp};

/// The schema id. See `contracts/fleet.v1.schema.json`.
pub const SCHEMA_ID: &str = "openwiz.fleet.v1";

/// An issue's or pull request's number: 1 or more.
pub type Number = NonZeroU64;

/// Text that is never empty.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(transparent)]
pub struct NonEmpty(String);

impl NonEmpty {
    /// `text`, unless it is empty.
    pub fn new(text: impl Into<String>) -> Option<Self> {
        let text = text.into();
        (!text.is_empty()).then_some(Self(text))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// A full commit id: 40 lowercase hex digits.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(transparent)]
pub struct Commit(String);

impl Commit {
    /// `id`, only when it is 40 lowercase hex digits.
    pub fn parse(id: &str) -> Option<Self> {
        let hex = id.len() == 40 && id.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'));
        hex.then(|| Self(id.to_owned()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// A read's id: printed as `r` and its number (`r7`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(into = "String")]
pub struct ReadId(pub u32);

impl From<ReadId> for String {
    fn from(id: ReadId) -> Self {
        format!("r{}", id.0)
    }
}

/// The envelope both commands print with `--json`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Envelope {
    pub schema: SchemaId,
    pub sources: Sources,
    /// Every external read, each fact once.
    pub reads: Vec<Read>,
    pub coverage: Coverage,
    pub freshness: Freshness,
    pub data: View,
}

/// [`SCHEMA_ID`], the one value of `schema`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum SchemaId {
    #[serde(rename = "openwiz.fleet.v1")]
    V1,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Sources {
    pub github: GitHubSource,
    /// `None` in the `fleets` view, which reads nothing from CloudRoom.
    pub cloudroom: Option<CloudRoomSource>,
}

/// `gh`: its version is reported, never a gate.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct GitHubSource {
    pub name: Gh,
    /// Its `version` read.
    pub version: ReadId,
    /// The version last live-tested: evidence, never a gate.
    pub tested_version: String,
    /// True exactly when the `version` read is complete and equals
    /// `tested_version`.
    pub version_tested: bool,
}

/// `gh`, the one value of `sources.github.name`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum Gh {
    #[serde(rename = "gh")]
    Gh,
}

/// `room-cli`: its version is reported, never a gate (#37).
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CloudRoomSource {
    pub name: RoomCli,
    /// Its `version` read.
    pub version: ReadId,
    pub tested_version: String,
    pub version_tested: bool,
}

/// `room-cli`, the one value of `sources.cloudroom.name`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum RoomCli {
    #[serde(rename = "room-cli")]
    RoomCli,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct Coverage {
    /// `Complete` exactly when every read is complete.
    pub state: Completeness,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct Freshness {
    /// When the reads started.
    pub snapshot_at: Timestamp,
}

/// One external read: its id, what was read, and its outcome.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Read {
    pub id: ReadId,
    #[serde(flatten)]
    pub kind: ReadKind,
}

/// What a read read: its `kind`, its subject, and its outcome, which holds
/// its one interpreted result. Only the six list kinds can be partial.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ReadKind {
    /// `gh --version` or `room-cli --version`.
    Version {
        source: SourceName,
        outcome: Outcome<NonEmpty>,
    },
    /// `gh repo view`: the name, never the owner.
    Repository { outcome: Outcome<Repository> },
    /// Which issues are specs (`fleets` only): their numbers, ascending.
    SpecList { outcome: ListOutcome<Number> },
    /// One issue's own fields: a spec's, a ticket's or a blocker's.
    Issue {
        issue: Number,
        outcome: Outcome<Issue>,
    },
    /// A spec's sub-issues: its tickets, ascending.
    SubIssues {
        spec: Number,
        outcome: ListOutcome<Number>,
    },
    /// A ticket's blocked-by links: its blockers, ascending.
    BlockedBy {
        ticket: Number,
        outcome: ListOutcome<Number>,
    },
    /// The pull request that closes the issue; `None`: none does.
    PrDiscovery {
        issue: Number,
        outcome: Outcome<Option<PullRequest>>,
    },
    /// An open pull request's checks, the latest run of each.
    Checks {
        pr: Number,
        outcome: ListOutcome<Check>,
    },
    /// An open pull request's latest verdict; `None`: none.
    Comments {
        pr: Number,
        outcome: Outcome<Option<Review>>,
    },
    /// Whether a merged pull request's merge commit is on its base.
    MergeReadback { pr: Number, outcome: Outcome<bool> },
    /// The CloudRoom projects whose git remote is this repository (`fleet`
    /// only).
    Projects { outcome: ListOutcome<Project> },
    /// Those projects' threads, not archived (`fleet` only).
    Threads { outcome: ListOutcome<Thread> },
    /// One Cloud thread's branch.
    Workspace {
        thread: NonEmpty,
        outcome: Outcome<NonEmpty>,
    },
}

/// Whose version a `version` read read.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceName {
    Github,
    Cloudroom,
}

/// A read that is complete, or failed with no value.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum Outcome<T> {
    /// Read in full. A `None` inside is a fact, never "not read".
    Complete {
        value: T,
    },
    Failed(Failed),
}

/// A list read: complete, read in part, or failed with no value.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum ListOutcome<T> {
    Complete {
        value: Vec<T>,
    },
    /// Fewer than GitHub's own total: the value is what was read.
    Partial {
        gap: Truncated,
        reason: NonEmpty,
        value: Vec<T>,
    },
    Failed(Failed),
}

/// `truncated`, the one gap of a partial read.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Truncated {
    Truncated,
}

/// Nothing usable was read: no value.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Failed {
    /// One of the inventory's eight.
    pub gap: GapKind,
    /// OpenWiz's own words, never a tool's raw output.
    pub reason: NonEmpty,
}

/// The GitHub repository's name, without its owner.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Repository {
    pub name: NonEmpty,
}

/// One issue's own fields.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Issue {
    pub title: String,
    /// GitHub's own: never "merged".
    pub state: IssueState,
    pub milestone: Option<Milestone>,
    /// As read, each once.
    pub labels: Vec<NonEmpty>,
    /// The body's one `**Owned paths:**` line, as written; `None` when
    /// there isn't exactly one, or it's empty.
    pub owned_paths: Option<NonEmpty>,
    /// The body's one `**Relies on:**` line, the same way.
    pub relies_on: Option<NonEmpty>,
    /// The selected pending comment's first line and provenance; no body.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pending_question: Option<PendingQuestion>,
}

/// Only the selected comment's first line, link and timestamp are printed.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct PendingQuestion {
    pub wording: NonEmpty,
    pub link: NonEmpty,
    pub asked_at: Timestamp,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IssueState {
    Open,
    Closed,
}

/// A version.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Milestone {
    pub number: Number,
    pub title: String,
}

/// `pr_discovery`'s value: the issue's open or merged pull request, or
/// several open ones, none of which is its.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum PullRequest {
    Open(PrFields),
    /// GitHub reports it merged; the issue is merged only when its
    /// `merge_readback` is true.
    Merged(MergedPr),
    /// Two or more open ones, ascending.
    Several {
        numbers: Vec<Number>,
    },
}

/// An open or merged pull request's own fields.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct PrFields {
    pub number: Number,
    pub draft: bool,
    pub head_branch: NonEmpty,
    pub head_commit: Commit,
    pub base_branch: NonEmpty,
    /// The issues it closes, ascending.
    pub closes: Vec<Number>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct MergedPr {
    #[serde(flatten)]
    pub fields: PrFields,
    pub merge_commit: Commit,
    pub merged_at: Timestamp,
}

/// One check's latest run.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Check {
    pub name: NonEmpty,
    pub result: CheckResult,
}

/// `gh pr checks`'s bucket.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CheckResult {
    Pass,
    Fail,
    Pending,
    Skipping,
    Cancel,
}

/// The latest `VERDICT: <APPROVE or CHANGES> at <the commit>` comment.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Review {
    pub verdict: Verdict,
    /// It holds only for this commit.
    pub commit: Commit,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Verdict {
    Approve,
    Changes,
}

/// A CloudRoom project whose git remote is this repository.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Project {
    pub id: NonEmpty,
    pub name: String,
}

/// One thread of those projects.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Thread {
    /// Its branch is its own `workspace` read.
    Cloud { thread: NonEmpty, project: NonEmpty },
    /// Its branch is the thread list's; `None`: none.
    Local {
        thread: NonEmpty,
        project: NonEmpty,
        branch: Option<NonEmpty>,
    },
}

/// A worked-out value: known only when every read it requires is complete.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkedOut<T> {
    Known(T),
    /// Not known: exactly the incomplete reads it requires, in the order of
    /// `reads`.
    Unread(Vec<ReadId>),
}

/// A ticket's state, worked out by the state table.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum State {
    Known(TicketState),
    Unread(Vec<ReadId>),
    /// Every read is complete, and the state table doesn't settle it.
    Unknown(NonEmpty),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TicketState {
    Ready,
    Building,
    InReview,
    ChangesRequested,
    /// Only a merge read back on its base.
    Merged,
    Held,
    Blocked,
}

/// A ticket's reviewer: version 1 defines no read that places one.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Reviewer {
    Undefined(NonEmpty),
}

/// `data`: one of the two views, by `view`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "view", rename_all = "snake_case")]
pub enum View {
    /// `openwiz fleets --json`.
    Fleets(FleetsView),
    /// `openwiz fleet <spec> --json`.
    Fleet(FleetView),
}

/// Every fleet, its tickets and blockers, and their counts. No agents.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct FleetsView {
    pub repository: ReadId,
    pub specs: ReadId,
    pub fleets: Vec<Fleet>,
    pub tickets: Vec<TicketCore>,
    pub blockers: Vec<Blocker>,
    pub needs_you: WorkedOut<Vec<NeedsYou>>,
}

/// One fleet's tickets, blockers and agents.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct FleetView {
    pub repository: ReadId,
    pub projects: ReadId,
    pub threads: ReadId,
    pub fleet: Fleet,
    pub tickets: Vec<Ticket>,
    pub blockers: Vec<Blocker>,
    pub needs_you: WorkedOut<Vec<NeedsYou>>,
    /// The project threads no verified chain places.
    pub unplaced: WorkedOut<Vec<Unplaced>>,
}

/// One spec: its `issue` and `sub_issues` reads, and its counts.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Fleet {
    pub spec: Number,
    pub issue: ReadId,
    pub tickets: ReadId,
    pub progress: WorkedOut<Counts>,
}

/// The fleet's tickets by state: `tickets` is the sum of the others.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
pub struct Counts {
    pub tickets: u64,
    pub ready: u64,
    pub building: u64,
    pub in_review: u64,
    pub changes_requested: u64,
    pub merged: u64,
    pub held: u64,
    pub blocked: u64,
    /// How many are `unknown`.
    pub unknown: u64,
}

/// One ticket in the `fleets` view: pointers to its reads, and its state.
/// A pointer is `None` when its read doesn't apply.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct TicketCore {
    pub number: Number,
    pub issue: ReadId,
    pub blocked_by: ReadId,
    pub pr: ReadId,
    pub ci: Option<ReadId>,
    pub review: Option<ReadId>,
    pub on_base: Option<ReadId>,
    pub state: State,
}

/// One ticket in the `fleet` view, with its agents.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Ticket {
    #[serde(flatten)]
    pub core: TicketCore,
    /// The thread the verified chain places; `Known(None)`: none is placed
    /// (never that none exists).
    pub builder: WorkedOut<Option<NonEmpty>>,
    pub reviewer: Reviewer,
}

/// An issue that blocks a ticket of the view: once, however many it
/// blocks.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Blocker {
    pub number: Number,
    pub issue: ReadId,
    pub pr: ReadId,
    pub on_base: Option<ReadId>,
    /// The spec of the fleet in this view whose tickets list it; `None`:
    /// none.
    pub fleet: WorkedOut<Option<Number>>,
    /// Its verified merge.
    pub merged: WorkedOut<bool>,
}

/// One "needs you" item.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct NeedsYou {
    pub kind: NeedsYouKind,
    pub spec: Number,
    pub ticket: Number,
    pub wording: Fact<NonEmpty>,
    pub link: Fact<NonEmpty>,
    pub asked_at: Fact<Timestamp>,
    pub risk: Fact<NeedsYouRisk>,
}

/// Explicit classification only. No label is not a known safe value.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NeedsYouRisk {
    Live,
    Release,
    Publish,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NeedsYouKind {
    /// The `needs-info` label: a builder's question.
    NeedsInfo,
    /// The `held` label.
    Held,
}

/// A thread no verified chain places, and the first reason that applies.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Unplaced {
    pub thread: NonEmpty,
    pub reason: UnplacedReason,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UnplacedReason {
    NoBranch,
    SharedBranch,
    NoPullRequest,
    SeveralTickets,
    SeveralIssues,
}
