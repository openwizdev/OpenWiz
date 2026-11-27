use std::fmt;

use serde::{Deserialize, Serialize};

use crate::attachment::PromptAttachment;
use crate::envelope::SourceInfo;
use crate::model::{Fact, Timestamp};

use super::effects::Effects;
use super::reconcile::Observation;
use super::send::{Delivery, FailReason, SendGap, UncertainReason};
use super::{Binding, OpId};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecordState {
    Claimed,
    Dispatching,
    Finished,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SendRecord {
    pub schema: String,
    pub op_id: OpId,
    pub binding: Binding,
    pub text: Option<String>,
    pub text_bytes: u64,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub attachments: Vec<PromptAttachment>,
    pub state: RecordState,
    pub target_title: Option<Fact<String>>,
    #[serde(default)]
    pub source: Option<SourceInfo>,
    pub effects: Option<Effects>,
    pub delivery: Option<Delivery>,
    pub gaps: Vec<SendGap>,
    pub observations: Vec<Observation>,
    pub recovered: bool,
    pub claimed_at: Timestamp,
    pub dispatching_at: Option<Timestamp>,
    pub finished_at: Option<Timestamp>,
}

impl SendRecord {
    pub fn claimed(op_id: OpId, binding: Binding, text: &str, now: Timestamp) -> Self {
        Self {
            schema: super::RECORD_SCHEMA_ID.to_owned(),
            op_id,
            binding,
            text: Some(text.to_owned()),
            text_bytes: text.len() as u64,
            attachments: vec![],
            state: RecordState::Claimed,
            target_title: None,
            source: None,
            effects: None,
            delivery: None,
            gaps: vec![],
            observations: vec![],
            recovered: false,
            claimed_at: now,
            dispatching_at: None,
            finished_at: None,
        }
    }

    pub fn with_attachments(self, attachments: Vec<PromptAttachment>) -> Self {
        Self {
            attachments,
            ..self
        }
    }

    pub fn dispatching(&self, now: Timestamp) -> Self {
        Self {
            state: RecordState::Dispatching,
            dispatching_at: Some(now),
            ..self.clone()
        }
    }

    pub fn finished(&self, delivery: Delivery, now: Timestamp) -> Self {
        let delivered = matches!(
            delivery,
            Delivery::Queued { .. } | Delivery::Accepted { .. }
        );
        Self {
            text: if delivered { None } else { self.text.clone() },
            state: RecordState::Finished,
            delivery: Some(delivery),
            finished_at: Some(now),
            ..self.clone()
        }
    }
}

pub fn recover(record: &SendRecord, now: Timestamp) -> SendRecord {
    let delivery = match record.state {
        RecordState::Finished => return record.clone(),
        RecordState::Claimed => Delivery::failed(FailReason::InterruptedBeforeDispatch),
        RecordState::Dispatching => {
            Delivery::uncertain(UncertainReason::InterruptedAfterDispatchMark)
        }
    };
    SendRecord {
        recovered: true,
        ..record.finished(delivery, now)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Claim {
    Owned,
    Existing(SendRecord),
    InProgress(SendRecord),
    Pending,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StoreError(pub String);

impl fmt::Display for StoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

pub trait SendStore: Send + Sync {
    fn load(&self, op_id: &OpId) -> Result<Option<SendRecord>, StoreError>;

    fn claim(&self, record: &SendRecord, now: Timestamp) -> Result<Claim, StoreError>;

    fn update(&self, record: &SendRecord) -> Result<(), StoreError>;

    fn release(&self, op_id: &OpId);

    fn uncertain_matching(
        &self,
        binding: &Binding,
        except: &OpId,
        now: Timestamp,
    ) -> Result<Vec<SendRecord>, StoreError>;

    fn in_flight_matching(
        &self,
        binding: &Binding,
        except: &OpId,
        now: Timestamp,
    ) -> Result<Vec<SendRecord>, StoreError>;

    fn inspect(&self, op_id: &OpId, now: Timestamp) -> Result<Option<SendRecord>, StoreError>;

    fn withdraw(&self, op_id: &OpId) -> Result<(), StoreError>;
}
