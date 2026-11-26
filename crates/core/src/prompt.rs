use std::fmt;
use std::time::Duration;

use serde::Serialize;

use crate::attachment::{
    Claim, DeleteReason, FailReason, Kind, PromptAttachment, Retention, StagedAttachment, Stored,
    retention,
};
use crate::messaging::record::StoreError;
use crate::messaging::{InvalidRequest, OpId, sha256_hex, validate_text};
use crate::model::Timestamp;

pub use crate::attachment::AttachmentId;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct PromptPayload {
    pub text: String,
    pub attachments: Vec<AttachmentId>,
}

impl PromptPayload {
    pub fn text(text: impl Into<String>) -> Self {
        Self {
            text: text.into(),
            attachments: vec![],
        }
    }

    pub fn validate(&self) -> Result<(), InvalidRequest> {
        validate_text(&self.text)?;
        for (i, id) in self.attachments.iter().enumerate() {
            if self.attachments[..i].contains(id) {
                return Err(InvalidRequest(format!(
                    "attachment {} is listed twice; nothing was claimed, read or sent",
                    id.as_str()
                )));
            }
        }
        Ok(())
    }

    pub fn text_sha256(&self) -> String {
        sha256_hex(self.text.as_bytes())
    }
}

const EMPTY_HEADER: &str = "openwiz.prompt.attachments.v1\n";

const ATTACHMENTS_HEADER: &str = "openwiz.prompt.attachments.v2\n";

pub fn attachments_digest(attachments: &[PromptAttachment]) -> String {
    if attachments.is_empty() {
        return empty_attachments_digest();
    }
    let mut canonical = String::from(ATTACHMENTS_HEADER);
    for a in attachments {
        canonical.push_str(&format!(
            "{} {} {} {}\n",
            a.sha256.as_str(),
            a.size_bytes,
            kind_label(a.kind),
            a.name.as_str()
        ));
    }
    sha256_hex(canonical.as_bytes())
}

pub fn empty_attachments_digest() -> String {
    sha256_hex(EMPTY_HEADER.as_bytes())
}

fn kind_label(kind: Kind) -> &'static str {
    match kind {
        Kind::Image => "image",
        Kind::File => "file",
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReadyPrompt {
    pub text: String,
    pub attachments: Vec<StagedAttachment>,
}

impl ReadyPrompt {
    pub fn text(text: impl Into<String>) -> Self {
        Self {
            text: text.into(),
            attachments: vec![],
        }
    }

    pub fn bound(&self) -> Vec<PromptAttachment> {
        self.attachments
            .iter()
            .map(|a| a.attachment.clone())
            .collect()
    }

    pub fn attachments_digest(&self) -> String {
        attachments_digest(&self.bound())
    }

    pub fn dispatch_order(&self) -> Vec<StagedAttachment> {
        let files = self
            .attachments
            .iter()
            .filter(|a| a.attachment.kind == Kind::File);
        let images = self
            .attachments
            .iter()
            .filter(|a| a.attachment.kind == Kind::Image);
        files.chain(images).cloned().collect()
    }

    pub fn total_bytes(&self) -> u64 {
        self.attachments
            .iter()
            .map(|a| a.attachment.size_bytes)
            .fold(0, u64::saturating_add)
    }
}

pub fn attachment_allowance(total_bytes: u64) -> Duration {
    Duration::from_secs(total_bytes.div_ceil(ALLOWANCE_BYTES_PER_SECOND))
}

pub const ALLOWANCE_BYTES_PER_SECOND: u64 = 1024 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize)]
pub enum OpKind {
    #[serde(rename = "messaging")]
    Send,
    #[serde(rename = "new_thread")]
    NewThread,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize)]
pub struct OpRef {
    pub kind: OpKind,
    pub op_id: OpId,
}

impl fmt::Display for OpRef {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.kind {
            OpKind::Send => write!(f, "send op {}", self.op_id),
            OpKind::NewThread => write!(f, "new thread op {}", self.op_id),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Lookup {
    Ready {
        staged: StagedAttachment,
        ready_at: Timestamp,
        claim: Option<(OpRef, Claim)>,
    },
    NotFound,
    Failed(FailReason),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Problem {
    NotFound,
    Failed(FailReason),
    Expired,
    InUse { op: OpRef, claim: Claim },
}

impl Problem {
    pub fn words(&self) -> String {
        match self {
            Self::NotFound => {
                "not found: it was never staged here, or it was removed or expired".to_owned()
            }
            Self::Failed(reason) => format!("not ready: {}", reason.message()),
            Self::Expired => "expired: it was ready for more than 24 hours unsent".to_owned(),
            Self::InUse { op, claim } => {
                let state = match claim {
                    Claim::Dispatching => "is being sent",
                    Claim::Accepted => "has been sent",
                    Claim::Uncertain => "is uncertain",
                    Claim::Failed | Claim::Unclaimed => "uses it",
                };
                format!("in use: {op} {state}; stage the file again for a new operation")
            }
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AttachmentProblem {
    pub id: AttachmentId,
    pub problem: Problem,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Refusal {
    pub problems: Vec<AttachmentProblem>,
}

impl Refusal {
    pub fn words(&self) -> String {
        let each: Vec<String> = self
            .problems
            .iter()
            .map(|p| format!("attachment {} is {}", p.id.as_str(), p.problem.words()))
            .collect();
        format!(
            "{}; nothing was sent, and the text and the other attachments are kept as they were",
            each.join("; ")
        )
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GateError {
    Refused(Refusal),
    Store(StoreError),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ClaimOutcome {
    Claimed { new: Vec<AttachmentId> },
    Refused(Refusal),
}

pub trait StagedAttachments: Send + Sync {
    fn look_up(&self, id: &AttachmentId, now: Timestamp) -> Result<Lookup, StoreError>;

    fn claim(
        &self,
        op: &OpRef,
        ids: &[AttachmentId],
        now: Timestamp,
    ) -> Result<ClaimOutcome, StoreError>;

    fn unclaim(&self, op: &OpRef, ids: &[AttachmentId]) -> Result<(), StoreError>;

    fn settle(&self, op: &OpRef, ids: &[AttachmentId], now: Timestamp) -> Result<(), StoreError>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct NoAttachments;

impl StagedAttachments for NoAttachments {
    fn look_up(&self, _id: &AttachmentId, _now: Timestamp) -> Result<Lookup, StoreError> {
        Ok(Lookup::NotFound)
    }

    fn claim(
        &self,
        _op: &OpRef,
        ids: &[AttachmentId],
        _now: Timestamp,
    ) -> Result<ClaimOutcome, StoreError> {
        if ids.is_empty() {
            return Ok(ClaimOutcome::Claimed { new: vec![] });
        }
        Ok(ClaimOutcome::Refused(Refusal {
            problems: ids
                .iter()
                .map(|id| AttachmentProblem {
                    id: id.clone(),
                    problem: Problem::NotFound,
                })
                .collect(),
        }))
    }

    fn unclaim(&self, _op: &OpRef, _ids: &[AttachmentId]) -> Result<(), StoreError> {
        Ok(())
    }

    fn settle(
        &self,
        _op: &OpRef,
        _ids: &[AttachmentId],
        _now: Timestamp,
    ) -> Result<(), StoreError> {
        Ok(())
    }
}

pub fn claimable(
    op: &OpRef,
    current: Option<&(OpRef, Claim)>,
    age: Duration,
) -> Result<(), Problem> {
    let claim = match current {
        Some((owner, _)) if owner == op => return Ok(()),
        Some((owner, claim @ (Claim::Dispatching | Claim::Accepted | Claim::Uncertain))) => {
            return Err(Problem::InUse {
                op: owner.clone(),
                claim: *claim,
            });
        }
        Some((_, claim)) => *claim,
        None => Claim::Unclaimed,
    };
    match retention(Stored::Ready { claim, age }) {
        Retention::Delete(DeleteReason::Expired) => Err(Problem::Expired),
        _ => Ok(()),
    }
}

pub fn age(now: Timestamp, at: Timestamp) -> Duration {
    Duration::from_millis(now.0.saturating_sub(at.0).max(0).unsigned_abs())
}

pub fn gate(
    attachments: &dyn StagedAttachments,
    payload: &PromptPayload,
    op: &OpRef,
    now: Timestamp,
) -> Result<ReadyPrompt, GateError> {
    let mut staged = Vec::with_capacity(payload.attachments.len());
    let mut problems = Vec::new();
    for id in &payload.attachments {
        let problem = match attachments.look_up(id, now).map_err(GateError::Store)? {
            Lookup::NotFound => Problem::NotFound,
            Lookup::Failed(reason) => Problem::Failed(reason),
            Lookup::Ready {
                staged: ready,
                ready_at,
                claim,
            } => {
                if ready.attachment.id != *id {
                    Problem::Failed(FailReason::Unreadable)
                } else {
                    match claimable(op, claim.as_ref(), age(now, ready_at)) {
                        Ok(()) => {
                            staged.push(ready);
                            continue;
                        }
                        Err(problem) => problem,
                    }
                }
            }
        };
        problems.push(AttachmentProblem {
            id: id.clone(),
            problem,
        });
    }
    if !problems.is_empty() {
        return Err(GateError::Refused(Refusal { problems }));
    }
    Ok(ReadyPrompt {
        text: payload.text.clone(),
        attachments: staged,
    })
}

pub fn recorded(
    attachments: &dyn StagedAttachments,
    ids: &[AttachmentId],
    record: &[PromptAttachment],
    now: Timestamp,
) -> Result<Option<Vec<PromptAttachment>>, StoreError> {
    let mut found = Vec::with_capacity(ids.len());
    for id in ids {
        if let Some(kept) = record.iter().find(|a| a.id == *id) {
            found.push(kept.clone());
            continue;
        }
        match attachments.look_up(id, now)? {
            Lookup::Ready { staged, .. } if staged.attachment.id == *id => {
                found.push(staged.attachment);
            }
            _ => return Ok(None),
        }
    }
    Ok(Some(found))
}

pub fn handed_over(count: usize) -> String {
    let noun = if count == 1 {
        "attachment"
    } else {
        "attachments"
    };
    format!(", with {count} {noun} handed to CloudRoom. {NOT_REPORTED}")
}

pub const NOT_REPORTED: &str = "Delivery to the agent's machine is not reported";
