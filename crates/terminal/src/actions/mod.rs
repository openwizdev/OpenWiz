//! The shared action seam (terminal contract, "Shared action seam"). T3 owns
//! these types, the transport and the shell's handling; the answer, send and
//! new-thread modules (T4, T5, T6) implement [`Action`] in their own files
//! only. Until a module's `register()` returns an action, the shell shows
//! that entry as unavailable and nothing can submit it.

pub mod answer;
pub mod new_thread;
pub mod send;

use serde_json::{Value, json};

pub use super::model;
use super::model::{Decisions, Fact, FleetDetail, Fleets, Freshness, Inventory, SessionDetail};

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActionId {
    Answer,
    Send,
    NewThread,
}

impl ActionId {
    pub const ALL: [ActionId; 3] = [ActionId::Answer, ActionId::Send, ActionId::NewThread];

    /// The capability id (`openwiz.terminal-capability.v1`'s `actions`).
    pub fn capability(self) -> &'static str {
        match self {
            ActionId::Answer => "answer",
            ActionId::Send => "send",
            ActionId::NewThread => "new_thread",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            ActionId::Answer => "Answer",
            ActionId::Send => "Message",
            ActionId::NewThread => "New thread",
        }
    }
}

/// One displayed decision, bound exactly as shown. Every field comes from
/// the decisions route's same response; nothing is guessed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DecisionBinding {
    pub repository: String,
    pub subject_kind: String,
    pub subject_number: u64,
    pub comment_id: u64,
    pub request_id: String,
    pub fingerprint: String,
    /// The question this binding answers, for a grill round; else `None`.
    pub question_id: Option<String>,
    /// The exact displayed proposal/context and recommendation lines.
    pub proposal: Vec<String>,
    pub recommendation: Vec<String>,
    /// The displayed question's context (grill rounds); empty otherwise.
    pub context: Vec<String>,
    /// The whole record as received.
    pub record: Value,
    /// `ordinary`, `live`, `release`, `publish` or `unknown`, as recorded.
    pub risk: String,
    pub current: Fact<bool>,
    pub source_freshness: Freshness,
    pub source_snapshot_at: Fact<i64>,
    pub generation: u64,
    /// The verified configured orchestrator target, with its own freshness.
    pub target: Fact<Option<String>>,
    pub target_freshness: Freshness,
    /// When the target was verified (the orchestrator's own source time).
    pub target_snapshot_at: Fact<i64>,
}

impl DecisionBinding {
    /// Stable request/question identity, independent of display position or
    /// refreshed source times. Changed wording is not a new answer slot.
    pub fn same_item(&self, other: &Self) -> bool {
        self.repository == other.repository
            && self.subject_kind == other.subject_kind
            && self.subject_number == other.subject_number
            && self.comment_id == other.comment_id
            && self.request_id == other.request_id
            && self.question_id == other.question_id
    }
}

// Seeds and snapshots are made once per open or read, never in a hot loop.
#[allow(clippy::large_enum_variant)]
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ActionSeed {
    Answer(DecisionBinding),
    Send { session_id: String },
    NewThread { project_id: String },
}

/// The core's own send mode (`Queue` or `Steer`), whose `as_str` gives the
/// web API's `mode` words: one definition, never spelled again here.
pub use openwiz_core::messaging::Mode;

/// A send (and an answer, which is one send). No attachments in this
/// visual version: the body always omits them.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SendInput {
    pub target: String,
    /// Exact bytes: never trimmed, prefixed, split or cleaned.
    pub text: String,
    pub mode: Mode,
    pub op_id: String,
    pub resume_paused_queue: bool,
    pub accept_possible_duplicate: bool,
}

/// A create (or its preview). Attachments are always `[]`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NewThreadInput {
    pub project_id: String,
    pub harness: String,
    pub model: String,
    pub effort: String,
    pub prompt: String,
    pub op_id: String,
}

/// The read snapshots an open action is told about after each refresh.
#[allow(clippy::large_enum_variant)]
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SnapshotData {
    Decisions(Decisions),
    Inventory(Inventory),
    Session(SessionDetail),
    Fleets(Fleets),
    Fleet(FleetDetail),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ActionInput {
    Open(ActionSeed),
    /// `field` is the action's own field id; unknown ids must be refused.
    Edit {
        field: String,
        value: String,
    },
    Preview,
    /// One distinct key press: never an auto-repeat.
    Confirm {
        press_id: u64,
    },
    Cancel,
    RefreshStatus,
    Snapshot {
        generation: u64,
        data: SnapshotData,
    },
    Response {
        request_id: u64,
        result: TransportResult,
    },
}

/// What the action shows. Every string is drawn through the sanitizer; no
/// raw terminal bytes reach the screen.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ActionView {
    pub title: String,
    /// The exact target, as bound.
    pub target: String,
    /// `(field id, label, value, editable)`, in order.
    pub fields: Vec<(String, String, String, bool)>,
    pub effects: Vec<String>,
    pub preview_age_ms: Option<i64>,
    pub status: String,
    pub reason: Option<String>,
    /// Key hints, such as `Ctrl-P preview`.
    pub controls: Vec<String>,
    pub outcome: Option<String>,
    pub op_id: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ActionResult {
    pub view: ActionView,
    pub request: Option<ActionRequest>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ActionRequest {
    SendPreview { target: String, mode: Mode },
    Send(SendInput),
    Lookup { target: String, op_id: String },
    Options,
    NewPreview(NewThreadInput),
    Create(NewThreadInput),
    Status { op_id: String },
}

impl ActionRequest {
    /// A write: the only requests that need a confirmation and an attempt.
    pub fn is_dispatch(&self) -> bool {
        matches!(self, ActionRequest::Send(_) | ActionRequest::Create(_))
    }

    pub fn op_id(&self) -> Option<&str> {
        match self {
            ActionRequest::Send(s) => Some(&s.op_id),
            ActionRequest::Create(c) | ActionRequest::NewPreview(c) => Some(&c.op_id),
            ActionRequest::Lookup { op_id, .. } | ActionRequest::Status { op_id } => Some(op_id),
            _ => None,
        }
    }

    /// Method, path, JSON body, and the report schema a `200` must carry.
    pub fn route(&self) -> (&'static str, String, Option<Value>, &'static str) {
        let seg = |s: &str| s.to_owned();
        match self {
            ActionRequest::SendPreview { target, mode } => (
                "GET",
                format!(
                    "/api/v1/sessions/{}/preview?mode={}",
                    seg(target),
                    mode.as_str()
                ),
                None,
                "openwiz.send-preview.v1",
            ),
            ActionRequest::Send(input) => (
                "POST",
                format!("/api/v1/sessions/{}/messages", seg(&input.target)),
                Some(json!({
                    "op_id": input.op_id,
                    "mode": input.mode.as_str(),
                    "text": input.text,
                    "resume_paused_queue": input.resume_paused_queue,
                    "accept_possible_duplicate": input.accept_possible_duplicate,
                })),
                "openwiz.messaging.v1",
            ),
            ActionRequest::Lookup { target, op_id } => (
                "GET",
                format!("/api/v1/sessions/{}/messages/{}", seg(target), seg(op_id)),
                None,
                "openwiz.send-lookup.v1",
            ),
            ActionRequest::Options => (
                "GET",
                "/api/v1/cloud-options".into(),
                None,
                "openwiz.cloud-options.v1",
            ),
            ActionRequest::NewPreview(input) => (
                "POST",
                format!(
                    "/api/v1/projects/{}/threads/preview",
                    seg(&input.project_id)
                ),
                Some(new_body(input)),
                "openwiz.new-thread-preview.v1",
            ),
            ActionRequest::Create(input) => (
                "POST",
                format!("/api/v1/projects/{}/threads", seg(&input.project_id)),
                Some(new_body(input)),
                "openwiz.new-thread.v1",
            ),
            ActionRequest::Status { op_id } => (
                "GET",
                format!("/api/v1/new-threads/{}", seg(op_id)),
                None,
                "openwiz.new-thread-status.v1",
            ),
        }
    }
}

fn new_body(input: &NewThreadInput) -> Value {
    json!({
        "op_id": input.op_id,
        "harness": input.harness,
        "model": input.model,
        "effort": input.effort,
        "text": input.prompt,
        "attachments": [],
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TransportResult {
    /// A `200` whose body is the route's existing report.
    Report { http_status: u16, body: Value },
    /// Any other status, with its safe reason.
    Refused { http_status: u16, reason: String },
    /// Nothing reached the server.
    FailedBeforeDispatch { reason: String },
    /// It may have reached the server: never safe to resend.
    UnknownAfterDispatch { reason: String },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stage {
    Editing,
    Previewing,
    Ready,
    Confirming,
    Dispatching,
    Settled,
}

/// A write attempt, kept by the shell apart from any screen. Once
/// `dispatched`, it is locked to its request and op id for good.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Attempt {
    pub action: ActionId,
    pub op_id: String,
    pub request: ActionRequest,
    pub decision: Option<DecisionBinding>,
    pub preview_generation: u64,
    pub stage: Stage,
    pub dispatched: bool,
    pub outcome: Option<TransportResult>,
    pub last_status: Option<TransportResult>,
    /// First fully matched terminal send report, retained independently of
    /// the original receipt and the latest (possibly failed) status read.
    pub confirmed_outcome: Option<Value>,
}

impl Attempt {
    /// Blocks another operation while dispatch/delivery remains unresolved.
    /// The original request stays immutable even after a settled delivery.
    pub fn locked(&self) -> bool {
        // Decision retirement is Answer-specific. The independently owned
        // message/create modules retain their existing per-attempt policy.
        if self.action != ActionId::Answer {
            return self.dispatched
                && !matches!(
                    self.outcome,
                    Some(TransportResult::FailedBeforeDispatch { .. })
                );
        }
        self.dispatched && !self.safe_to_reopen() && self.settled_send_report().is_none()
    }

    /// Positive evidence of no delivery, never a failed later status read.
    pub fn safe_to_reopen(&self) -> bool {
        matches!(
            self.outcome,
            Some(TransportResult::FailedBeforeDispatch { .. } | TransportResult::Refused { .. })
        ) || self.settled_send_report().is_some_and(|r| {
            matches!(
                r["status"].as_str(),
                Some("failed" | "conflicting_reuse" | "possible_duplicate_refused")
            )
        })
    }

    fn settled_send_report(&self) -> Option<&Value> {
        let ActionRequest::Send(input) = &self.request else {
            return None;
        };
        let original = self.outcome.as_ref().and_then(|result| match result {
            TransportResult::Report { body, .. } => Some(body),
            _ => None,
        });
        let latest = self.last_status.as_ref().and_then(|result| match result {
            TransportResult::Report { body, .. } => Some(body),
            _ => None,
        });
        [self.confirmed_outcome.as_ref(), original, latest]
            .into_iter()
            .flatten()
            .find_map(|body| {
                let report = if body["schema"] == "openwiz.send-lookup.v1" {
                    if body["op_id"].as_str() != Some(&input.op_id)
                        || body["target"].as_str() != Some(&input.target)
                        || body["result"]["kind"] != "recorded"
                    {
                        return None;
                    }
                    &body["result"]["report"]
                } else {
                    body
                };
                (send_report_matches(input, report)
                    && matches!(
                        report["status"].as_str(),
                        Some(
                            "accepted"
                                | "queued"
                                | "failed"
                                | "conflicting_reuse"
                                | "possible_duplicate_refused"
                        )
                    ))
                .then_some(report)
            })
    }

    /// Later lookup/connection failures cannot erase positive settlement.
    /// Validation uses this attempt's immutable request, never a screen label.
    pub fn retain_settlement(&mut self) {
        if self.action == ActionId::Answer && self.confirmed_outcome.is_none() {
            self.confirmed_outcome = self.settled_send_report().cloned();
        }
    }

    /// A fresh complete read can positively retire a decision's pending
    /// record. It does not settle or overwrite the send's delivery outcome.
    pub fn blocks_answer(&self, decisions: Option<&Decisions>, ages: Option<DecisionAges>) -> bool {
        if !self.locked() {
            return false;
        }
        if self.stage == Stage::Dispatching {
            return true;
        }
        let (Some(binding), Some(data), Some(ages)) = (&self.decision, decisions, ages) else {
            return true;
        };
        if data.coverage != model::Coverage::Complete
            || data.freshness != Freshness::Fresh
            || ages.sources_age_ms.is_none_or(|age| age > 70_000)
        {
            return true;
        }
        let mut records = data.items.iter().filter(|item| {
            item.repository == binding.repository
                && item.comment_id == binding.comment_id
                && item.subject_kind == binding.subject_kind
                && item.subject_number == binding.subject_number
                && item.id == binding.request_id
        });
        let Some(record) = records.next() else {
            return false;
        };
        if records.next().is_some() {
            return true;
        }
        !binding.question_id.as_ref().is_some_and(|q| {
            record.current == Fact::Known(true)
                && record.kind == "grill_round"
                && record.record["answered"]
                    .as_array()
                    .is_some_and(|answered| answered.iter().any(|id| id.as_str() == Some(q)))
        })
    }
}

/// Shared identity guard for display and lock retirement: a schema-valid
/// report for another operation must never settle this immutable request.
pub(super) fn send_report_matches(input: &SendInput, report: &Value) -> bool {
    let binding = openwiz_core::messaging::Binding::new(
        openwiz_core::model::SessionId(input.target.clone()),
        input.mode,
        &input.text,
    );
    let status = report["status"].as_str();
    let outcome_matches = match status {
        Some("accepted" | "queued" | "failed" | "uncertain") => {
            report["result"]["kind"] == "outcome"
                && report["result"]["delivery"]["kind"].as_str() == status
        }
        Some("in_progress" | "conflicting_reuse" | "possible_duplicate_refused") => {
            report["result"]["kind"].as_str() == status
        }
        _ => false,
    };
    report["schema"] == "openwiz.messaging.v1"
        && outcome_matches
        && report["op_id"].as_str() == Some(&input.op_id)
        && report["target"]["id"].as_str() == Some(&input.target)
        && report["requested_mode"].as_str() == Some(input.mode.as_str())
        && report["text_sha256"].as_str() == Some(&binding.text_sha256)
        && report["text_bytes"].as_u64() == Some(input.text.len() as u64)
}

/// What an action may read: snapshots, their generation, whether guarded
/// requests can be made, and the shell's attempt for it. No process, no
/// arbitrary URL.
/// Current ages, in milliseconds, of the decision sources (their oldest
/// required source) and of the orchestrator target's verification: each the
/// source-reported age at receipt plus the time since. `None`: unknown.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DecisionAges {
    pub sources_age_ms: Option<u64>,
    pub target_age_ms: Option<u64>,
}

pub struct ActionContext<'a> {
    pub generation: u64,
    /// The current decision ages, apart from the snapshot's own enums.
    pub decision_ages: Option<DecisionAges>,
    pub decisions: Option<&'a Decisions>,
    pub inventory: Option<&'a Inventory>,
    pub fleets: Option<&'a Fleets>,
    /// The owner configured an allowed host, so guarded requests can be made.
    pub guarded_available: bool,
    pub attempt: Option<&'a Attempt>,
}

pub trait Action: Send {
    fn id(&self) -> ActionId;
    fn update(&mut self, input: ActionInput, context: &ActionContext) -> ActionResult;
}

/// Every action module's registration, in [`ActionId::ALL`] order.
pub fn registry() -> Vec<(ActionId, Option<Box<dyn Action>>)> {
    vec![
        (ActionId::Answer, answer::register()),
        (ActionId::Send, send::register()),
        (ActionId::NewThread, new_thread::register()),
    ]
}
