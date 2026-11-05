//! Injectable, transport-independent delivery effect. No I/O here.
//! The installed runtime owns reservation, locking, rechecks and persistence.
use super::model::{Capability, DeliveryOutcome, OutcomeState, Submission, Text};
use std::collections::VecDeque;

pub trait DeliveryBoundary {
    /// Prerequisites only; never evidence of phone receipt.
    fn capability(&self) -> Capability;
    /// One already-reserved attempt. No automatic retry is allowed.
    fn submit(&mut self, request: &Submission) -> DeliveryOutcome;
}

/// Production default until a positively observed binding is installed.
#[derive(Default)]
pub struct UnavailableDelivery;
impl DeliveryBoundary for UnavailableDelivery {
    fn capability(&self) -> Capability {
        Capability::unavailable()
    }
    fn submit(&mut self, _request: &Submission) -> DeliveryOutcome {
        DeliveryOutcome {
            state: OutcomeState::Failed,
            reason: Text::new("No delivery attempted: notification transport is unavailable")
                .unwrap(),
        }
    }
}

/// Synthetic seam only. Results must be supplied explicitly by the fixture.
/// An empty script returns uncertainty, never invented transport success.
pub struct RecordingDelivery {
    submissions: Vec<Submission>,
    replies: VecDeque<DeliveryOutcome>,
}
impl RecordingDelivery {
    pub fn new(replies: Vec<DeliveryOutcome>) -> Self {
        Self {
            submissions: vec![],
            replies: replies.into(),
        }
    }
    pub fn submissions(&self) -> &[Submission] {
        &self.submissions
    }
}
impl DeliveryBoundary for RecordingDelivery {
    fn capability(&self) -> Capability {
        Capability::unavailable()
    }
    fn submit(&mut self, request: &Submission) -> DeliveryOutcome {
        self.submissions.push(request.clone());
        self.replies.pop_front().unwrap_or_else(|| DeliveryOutcome {
            state: OutcomeState::Uncertain,
            reason: Text::new("Synthetic recording boundary has no scripted outcome").unwrap(),
        })
    }
}
