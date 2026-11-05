//! Output-only typed actions. Kind is derived from the rule by the planner.
use super::super::model::{Check, Commit, NonEmpty, Number, Verdict};
use super::{AgentRule, Approval, Fingerprint, MergeFact, Rules};
use serde::Serialize;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Plan {
    pub schema: Schema,
    pub mode: Mode,
    pub planned_at: u64,
    pub default_branch: NonEmpty,
    pub rules: Rules,
    pub actions: Vec<Action>,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum Schema {
    #[serde(rename = "openwiz.fleet-tick.v1")]
    V1,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum Mode {
    #[serde(rename = "dry_run")]
    DryRun,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    StartBuilder,
    StartReviewer,
    SendFindings,
    Merge,
    Close,
    Hold,
    Archive,
    LogRefusedStart,
    Wake,
    NeedsYou,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Action {
    pub kind: Kind,
    pub spec: Number,
    pub ticket: Option<Number>,
    #[serde(flatten)]
    pub detail: Detail,
    pub outcome: Planned,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct Planned {
    pub state: PlannedState,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PlannedState {
    Planned,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct PrFact {
    pub number: Number,
    pub head_commit: Commit,
    pub base_branch: NonEmpty,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct VerdictFact {
    pub verdict: Verdict,
    pub commit: Commit,
    pub comment: Number,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct BlockerFact {
    pub number: Number,
    pub pr: Number,
    pub merge_commit: Commit,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct RetryFact {
    pub start: crate::messaging::OpId,
    pub state: NoThread,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NoThread {
    Refused,
    Failed,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ThreadFact {
    pub thread: NonEmpty,
    pub role: Role,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    Builder,
    Reviewer,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Finding {
    pub id: String,
    pub rounds: u64,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct SummaryMerge {
    pub ticket: Number,
    pub pr: Number,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "rule", content = "facts", rename_all = "snake_case")]
pub enum Detail {
    Frontier {
        settings: AgentRule,
        title: String,
        approval: Approval,
        labels: Vec<NonEmpty>,
        blockers: Vec<BlockerFact>,
        retry_after: Option<RetryFact>,
    },
    FirstReview {
        settings: AgentRule,
        pr: PrFact,
        subject: String,
        checks: Vec<Check>,
    },
    FreshReview {
        settings: AgentRule,
        pr: PrFact,
        subject: String,
        checks: Vec<Check>,
        given_up: Vec<NonEmpty>,
    },
    ReCheck {
        pr: PrFact,
        subject: String,
        checks: Vec<Check>,
        reviewer: NonEmpty,
        last_verdict: Option<VerdictFact>,
    },
    ReviewFindings {
        pr: PrFact,
        checks: Vec<Check>,
        verdict: VerdictFact,
        builder: NonEmpty,
    },
    CiFailed {
        pr: PrFact,
        subject: String,
        checks: Vec<Check>,
        builder: NonEmpty,
    },
    ContractChanged {
        merged: MergeFact,
        files: Vec<NonEmpty>,
        relies_on: Vec<NonEmpty>,
        builder: NonEmpty,
    },
    #[serde(rename = "adr_0008")]
    Adr0008 {
        approval: Approval,
        pr: PrFact,
        base_commit: Commit,
        verdict: VerdictFact,
        reviewer: NonEmpty,
        checks: Vec<Check>,
    },
    Merged {
        merged: MergeFact,
    },
    AllClosed {
        tickets: Vec<Number>,
    },
    ContractHold {
        merged: MergeFact,
        files: Vec<NonEmpty>,
        relies_on: Vec<NonEmpty>,
        ready_label: &'static str,
    },
    Release {
        hold: Number,
        approval: Approval,
    },
    Finished {
        threads: Vec<ThreadFact>,
    },
    BuilderRefused {
        start: crate::messaging::OpId,
        state: NoThread,
        reason: &'static str,
    },
    ReviewerRefused {
        pr: PrFact,
        start: crate::messaging::OpId,
        state: NoThread,
        reason: &'static str,
    },
    NeedsInfo {
        question: Number,
    },
    Disputed {
        pr: PrFact,
        verdict: VerdictFact,
        findings: Vec<String>,
    },
    Diagnosis {
        pr: PrFact,
        verdict: VerdictFact,
        findings: Vec<Finding>,
    },
    Restart {
        builder: NonEmpty,
        branch: NonEmpty,
        settings: AgentRule,
    },
    Look {
        reason: String,
    },
    Held {
        hold: Number,
        merged: MergeFact,
        files: Vec<NonEmpty>,
    },
    ReApprove {
        approval: Approval,
        fingerprint_now: Fingerprint,
    },
    PersonReady {
        title: String,
        approval: Approval,
        blockers: Vec<BlockerFact>,
    },
    SpecSummary {
        merged: Vec<SummaryMerge>,
        follow_ups: Vec<Number>,
    },
}

impl Detail {
    pub fn kind(&self) -> Kind {
        match self {
            Self::Frontier { .. } => Kind::StartBuilder,
            Self::FirstReview { .. } | Self::FreshReview { .. } | Self::ReCheck { .. } => {
                Kind::StartReviewer
            }
            Self::ReviewFindings { .. } | Self::CiFailed { .. } | Self::ContractChanged { .. } => {
                Kind::SendFindings
            }
            Self::Adr0008 { .. } => Kind::Merge,
            Self::Merged { .. } | Self::AllClosed { .. } => Kind::Close,
            Self::ContractHold { .. } | Self::Release { .. } => Kind::Hold,
            Self::Finished { .. } => Kind::Archive,
            Self::BuilderRefused { .. } | Self::ReviewerRefused { .. } => Kind::LogRefusedStart,
            Self::NeedsInfo { .. }
            | Self::Disputed { .. }
            | Self::Diagnosis { .. }
            | Self::Restart { .. }
            | Self::Look { .. } => Kind::Wake,
            Self::Held { .. }
            | Self::ReApprove { .. }
            | Self::PersonReady { .. }
            | Self::SpecSummary { .. } => Kind::NeedsYou,
        }
    }
    pub(crate) fn order(&self) -> usize {
        match self {
            Self::Frontier { .. } => 0,
            Self::FirstReview { .. } => 1,
            Self::FreshReview { .. } => 2,
            Self::ReCheck { .. } => 3,
            Self::ReviewFindings { .. } => 4,
            Self::CiFailed { .. } => 5,
            Self::ContractChanged { .. } => 6,
            Self::Adr0008 { .. } => 7,
            Self::Merged { .. } => 8,
            Self::AllClosed { .. } => 9,
            Self::ContractHold { .. } => 10,
            Self::Release { .. } => 11,
            Self::Finished { .. } => 12,
            Self::BuilderRefused { .. } => 13,
            Self::ReviewerRefused { .. } => 14,
            Self::NeedsInfo { .. } => 15,
            Self::Disputed { .. } => 16,
            Self::Diagnosis { .. } => 17,
            Self::Look { .. } => 18,
            Self::Held { .. } => 19,
            Self::ReApprove { .. } => 20,
            Self::PersonReady { .. } => 21,
            Self::SpecSummary { .. } => 22,
            Self::Restart { .. } => 23,
        }
    }
}
