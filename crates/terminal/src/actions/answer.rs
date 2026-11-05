//! A numbered decision is an immutable proposal, never a row number at send
//! time. This module only returns the common preview/send/lookup requests;
//! the shell owns transport, distinct key presses and attempt retention.

use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use openwiz_core::messaging::{preview::PreviewReport, validate_text};
use serde_json::Value;

use super::model::{Coverage, Fact, Freshness};
use super::{
    Action, ActionContext, ActionId, ActionInput, ActionRequest, ActionResult, ActionSeed,
    ActionView, DecisionBinding, Mode, SendInput, TransportResult,
};

pub fn register() -> Option<Box<dyn Action>> {
    Some(Box::new(Answer::default()))
}

const FRESH_MS: u64 = 70_000;

#[derive(Clone, Copy, Default, PartialEq, Eq)]
enum ReplyKind {
    #[default]
    Yes,
    Simplify,
    OwnWords,
}
impl ReplyKind {
    fn label(self) -> &'static str {
        match self {
            Self::Yes => "yes",
            Self::Simplify => "simplify",
            Self::OwnWords => "own words",
        }
    }
}

struct Preview {
    report: PreviewReport,
    received: Instant,
}

#[derive(Default)]
struct Answer {
    binding: Option<DecisionBinding>,
    draft_op_id: String,
    kind: ReplyKind,
    words: String,
    preview: Option<Preview>,
    /// A queued/in-flight preview still has to settle after an edit/cancel.
    /// Its old response must never validate a newer draft's preview.
    pending_revision: Option<u64>,
    revision: u64,
    first_press: Option<u64>,
    last_press: u64,
    invalidated: bool,
    sent: Option<SendInput>,
    outcome: Option<String>,
    last_status: Option<String>,
    status: String,
    reason: Option<String>,
}

fn operation_id() -> String {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!(
        "answer-{nanos:x}-{:x}-{:x}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    )
}

impl Answer {
    fn invalidate_preview(&mut self) {
        self.revision = self.revision.wrapping_add(1);
        self.preview = None;
        self.first_press = None;
        self.status = "editing".into();
    }

    /// Recheck the same subject/comment/request/question and the entire
    /// proposal, even for plans whose fingerprint excludes headline/risk.
    /// A later fresh timestamp may renew eligibility, never change identity.
    fn eligible(&self, cx: &ActionContext) -> Result<(), String> {
        let b = self.binding.as_ref().ok_or("Select a decision first")?;
        if self.invalidated {
            return Err("The bound proposal or target changed/was removed. Reopen the displayed item; nothing was answered".into());
        }
        if !cx.guarded_available {
            return Err("No allowed host is configured; answering is unavailable".into());
        }
        let d = cx.decisions.ok_or("Decision coverage is unavailable")?;
        if d.coverage != Coverage::Complete || d.target_coverage != Coverage::Complete {
            return Err(
                "Decision or configured target coverage is incomplete; refresh before answering"
                    .into(),
            );
        }
        let ages = cx.decision_ages.ok_or("Source/target age is unknown")?;
        if d.freshness != Freshness::Fresh
            || d.target_freshness != Freshness::Fresh
            || ages.sources_age_ms.is_none_or(|a| a > FRESH_MS)
            || ages.target_age_ms.is_none_or(|a| a > FRESH_MS)
        {
            return Err(
                "Decision sources or verified target are stale/unknown; refresh before answering"
                    .into(),
            );
        }
        if d.target != b.target {
            return Err("The verified configured target changed; reopen the item".into());
        }
        let target = b
            .target
            .known()
            .and_then(Option::as_deref)
            .ok_or("No verified configured orchestrator target")?;
        if target.is_empty()
            || target.len() > 128
            || target.starts_with('-')
            || !target
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
        {
            return Err("The configured target is not a verified thread id".into());
        }
        let mut matches = d.items.iter().filter(|i| {
            i.repository == b.repository
                && i.comment_id == b.comment_id
                && i.subject_kind == b.subject_kind
                && i.subject_number == b.subject_number
        });
        let item = matches
            .next()
            .ok_or("The bound decision is no longer listed; nothing was answered")?;
        if matches.next().is_some()
            || item.id != b.request_id
            || item.fingerprint != b.fingerprint
            || item.record != b.record
            || item.risk != b.risk
        {
            return Err("The bound proposal, fingerprint or risk changed; reopen the item".into());
        }
        if item.current != Fact::Known(true) {
            return Err(
                "Current unanswered wording is false/unknown; refresh before answering".into(),
            );
        }
        if !matches!(b.risk.as_str(), "ordinary" | "live" | "release" | "publish") {
            return Err("Risk is unknown; answering is unavailable".into());
        }
        match b.question_id.as_deref() {
            Some(id) => {
                let q = item
                    .questions
                    .iter()
                    .find(|q| q.id == id)
                    .ok_or("This question is no longer unanswered")?;
                if b.proposal != [q.decides.clone()]
                    || b.context != [q.context.clone()]
                    || b.recommendation != [q.recommendation.clone()]
                    || item.kind != "grill_round"
                {
                    return Err("The displayed question/context/recommendation changed".into());
                }
            }
            None if item.kind == "grill_round" || item.wording != b.proposal => {
                return Err("The displayed proposal changed".into());
            }
            None => {}
        }
        self.reply()
            .and_then(|text| validate_text(&text).map_err(|e| e.to_string()))
    }

    fn reply(&self) -> Result<String, String> {
        let b = self.binding.as_ref().ok_or("Select a decision first")?;
        if self.kind == ReplyKind::OwnWords {
            return Ok(self.words.clone());
        }
        if let Some(q) = &b.question_id {
            return Ok(if self.kind == ReplyKind::Simplify {
                format!("simplify {q}")
            } else {
                format!("{q} yes")
            });
        }
        if self.kind == ReplyKind::Simplify {
            return Err(
                "Simplify is supported for grill questions; use own words for this confirmation"
                    .into(),
            );
        }
        match b.record.get("kind").and_then(Value::as_str) {
            Some("grill_confirmation") => Ok("confirm".into()),
            Some("spec_confirmation") => Ok(format!("confirm spec #{}", b.subject_number)),
            Some("plan_approval") => Ok(format!("approve #{}", b.subject_number)),
            _ => Err("Unsupported answer kind".into()),
        }
    }

    fn preview_ready(&self) -> Result<(), String> {
        let p = self
            .preview
            .as_ref()
            .ok_or("Preview the exact reply and effects with Ctrl-P first")?;
        let b = self.binding.as_ref().ok_or("Select a decision first")?;
        if Some(p.report.target.id.0.as_str()) != b.target.known().and_then(Option::as_deref)
            || p.report.requested_mode != Mode::Queue
        {
            return Err("The preview target or mode does not match the bound answer".into());
        }
        if p.report.status != openwiz_core::messaging::preview::PreviewStatus::Ready {
            return Err(p
                .report
                .refusal
                .as_ref()
                .map(|r| r.text.clone())
                .unwrap_or_else(|| "The send preview refused this answer".into()));
        }
        let e = p
            .report
            .effects
            .as_ref()
            .ok_or("The preview has no known effects")?;
        if e.read_age_ms < 0
            || e.read_age_ms as u128 + p.received.elapsed().as_millis() > FRESH_MS as u128
        {
            return Err("The effects preview is stale; preview again".into());
        }
        // This flow never silently opts into a paused queue or duplicate.
        if e.needs_acknowledgement {
            return Err("Paused queue requires acknowledgement; answer was not sent".into());
        }
        if !matches!(e.effect, openwiz_core::model::Fact::Known(_)) {
            return Err("The send effect is unknown".into());
        }
        Ok(())
    }

    fn view(&self, cx: &ActionContext) -> ActionView {
        let mut v = ActionView {
            title: "Answer Needs you".into(),
            op_id: (!self.draft_op_id.is_empty()).then(|| self.draft_op_id.clone()),
            status: self.status.clone(),
            reason: self.reason.clone(),
            outcome: self.outcome.clone(),
            controls: vec!["Space reply kind · Tab field · Ctrl-J newline · Ctrl-P preview".into(), "Ctrl-S confirm (then Ctrl-Y without release reporting) · Ctrl-R status · Esc cancel".into()],
            ..ActionView::default()
        };
        if let Some(b) = &self.binding {
            v.target = b
                .target
                .known()
                .and_then(Option::as_ref)
                .cloned()
                .unwrap_or_else(|| "unverified target".into());
            let editable = self.sent.is_none() && !cx.attempt.is_some_and(|a| a.locked());
            v.fields.push((
                "reply_kind".into(),
                "Reply kind".into(),
                if self.sent.is_some() {
                    "recorded message".into()
                } else {
                    self.kind.label().into()
                },
                editable,
            ));
            v.fields.push((
                "own_words".into(),
                "Own words".into(),
                self.words.clone(),
                editable && self.kind == ReplyKind::OwnWords,
            ));
            let reply = self.reply().unwrap_or_default();
            v.fields.push((
                "sends".into(),
                format!("Sends ({} B)", reply.len()),
                reply,
                false,
            ));
            v.effects.push(format!(
                "{} #{} · comment {} · request {}",
                b.subject_kind, b.subject_number, b.comment_id, b.request_id
            ));
            if b.question_id.is_some() {
                v.effects
                    .extend(b.proposal.iter().map(|s| format!("Proposal: {s}")));
            } else {
                if let Some(headline) = b.record.get("headline").and_then(Value::as_str) {
                    v.effects.push(format!("Headline: {headline}"));
                }
                if let Some(summary) = b.record.get("summary").and_then(Value::as_array) {
                    v.effects
                        .extend(summary.iter().enumerate().filter_map(|(i, line)| {
                            line.as_str().map(|line| format!("{}. {line}", i + 1))
                        }));
                }
            }
            v.effects
                .extend(b.context.iter().map(|s| format!("Context: {s}")));
            v.effects.extend(
                b.recommendation
                    .iter()
                    .map(|s| format!("Recommendation: {s}")),
            );
            v.effects.push("An answer message is not a saved answer or approved decision; only the orchestrator records it.".into());
            // Include every plan row/edge: the exact plan is part of approval.
            for key in ["tickets", "graph"] {
                if let Some(rows) = b.record.get(key).and_then(Value::as_array) {
                    for row in rows {
                        v.effects.push(format!("{key}: {row}"));
                    }
                }
            }
            v.effects.push(format!("Fingerprint: {}", b.fingerprint));
            let current = match cx
                .decisions
                .and_then(|d| {
                    d.items.iter().find(|i| {
                        i.repository == b.repository
                            && i.subject_kind == b.subject_kind
                            && i.subject_number == b.subject_number
                            && i.comment_id == b.comment_id
                            && i.id == b.request_id
                    })
                })
                .map(|i| &i.current)
            {
                Some(Fact::Known(true)) => "current",
                Some(Fact::Known(false)) => "changed",
                _ => "unknown",
            };
            v.effects
                .push(format!("Risk: {} · wording: {current}", b.risk));
            let age = |ms: Option<u64>| {
                ms.map(|n| format!("{n} ms"))
                    .unwrap_or_else(|| "unknown".into())
            };
            v.effects.push(format!(
                "At last input: sources {} · verified target {}",
                age(cx.decision_ages.and_then(|a| a.sources_age_ms)),
                age(cx.decision_ages.and_then(|a| a.target_age_ms))
            ));
        }
        if let Some(p) = &self.preview {
            v.effects.push(p.report.summary.clone());
            if let Some(e) = &p.report.effects {
                v.preview_age_ms =
                    Some(e.read_age_ms.saturating_add(
                        p.received.elapsed().as_millis().min(i64::MAX as u128) as i64,
                    ));
            }
        }
        if let Some(confirmed) = cx
            .attempt
            .filter(|a| self.sent.as_ref().is_some_and(|s| s.op_id == a.op_id))
            .and_then(|a| a.confirmed_outcome.as_ref())
        {
            v.effects.push(format!(
                "Confirmed outcome: {}",
                confirmed["status"].as_str().unwrap_or("unknown")
            ));
        }
        if let Some(status) = &self.last_status {
            v.effects.push(format!("Last status read: {status}"));
        }
        if let Some(s) = &self.sent {
            v.target = s.target.clone();
            v.op_id = Some(s.op_id.clone());
            v.effects
                .push("One send attempted; do not replay it.".into());
            v.effects.push(format!("No restart recovery here. Keep this op id: openwiz send {} --op-id {} --check --json. Restart never replays a write.", s.target, s.op_id));
        }
        v
    }

    fn describe(sent: &SendInput, result: &TransportResult) -> String {
        match result {
            TransportResult::Report { body, .. } => {
                let lookup = body["schema"] == "openwiz.send-lookup.v1";
                let target = if lookup {
                    body["target"].as_str()
                } else {
                    body["target"]["id"].as_str()
                };
                if body["op_id"].as_str() != Some(&sent.op_id) || target != Some(&sent.target) {
                    "uncertain: response identity does not match this operation".into()
                } else {
                    let report = if lookup {
                        &body["result"]["report"]
                    } else {
                        body
                    };
                    if lookup && body["result"]["kind"] != "recorded" {
                        format!(
                            "unresolved: {}",
                            body["summary"].as_str().unwrap_or("No recorded outcome")
                        )
                    } else {
                        if !super::send_report_matches(sent, report) {
                            "uncertain: report does not match the immutable answer".into()
                        } else {
                            format!(
                                "{}: {}",
                                report["status"].as_str().unwrap_or("unresolved"),
                                body["summary"].as_str().unwrap_or("No confirmed outcome")
                            )
                        }
                    }
                }
            }
            TransportResult::Refused {
                http_status,
                reason,
            } => format!("refused (HTTP {http_status}): {reason}"),
            TransportResult::FailedBeforeDispatch { reason } => {
                format!("failed before dispatch: {reason}")
            }
            TransportResult::UnknownAfterDispatch { reason } => format!("uncertain: {reason}"),
        }
    }

    fn sync_attempt(&mut self, attempt: &super::Attempt) {
        let Some(sent) = self.sent.as_ref().filter(|s| s.op_id == attempt.op_id) else {
            return;
        };
        // The shell records receipts and lookups by request kind before
        // delivery. Arrival order never decides which label gets a result.
        self.outcome = attempt.outcome.as_ref().map(|r| Self::describe(sent, r));
        self.last_status = attempt
            .last_status
            .as_ref()
            .map(|r| Self::describe(sent, r));
        self.status = if self.outcome.is_some() || self.last_status.is_some() {
            "locked; status reads only"
        } else {
            "dispatching; do not resend"
        }
        .into();
    }
}

impl Action for Answer {
    fn id(&self) -> ActionId {
        ActionId::Answer
    }

    fn update(&mut self, input: ActionInput, cx: &ActionContext) -> ActionResult {
        let mut request = None;
        if let ActionInput::Open(ActionSeed::Answer(binding)) = &input {
            // Open changes the displayed draft/operation. The shell retains
            // old preview jobs by their original draft id and discards them;
            // they must not occupy this pane's pending preview slot.
            self.pending_revision = None;
            if let Some(attempt) = cx.attempt.filter(|a| !a.safe_to_reopen()) {
                // Restore the exact immutable attempt for this item, or show
                // the earlier unresolved operation that blocks another item.
                if let (ActionRequest::Send(sent), Some(old)) =
                    (&attempt.request, &attempt.decision)
                {
                    self.invalidate_preview();
                    self.binding = Some(old.clone());
                    self.sent = Some(sent.clone());
                    self.draft_op_id = attempt.op_id.clone();
                    self.kind = ReplyKind::OwnWords;
                    self.words = sent.text.clone();
                    self.sync_attempt(attempt);
                    self.reason = Some(if old.same_item(binding) {
                        "This item already has an answer attempt. Status reads only; nothing was sent again"
                    } else { "An earlier answer remains unresolved. Check its status; nothing was sent" }.into());
                    return ActionResult {
                        view: self.view(cx),
                        request: None,
                    };
                }
            } else {
                // The shell selected no unresolved/same-item attempt, or a
                // positively refused one. Only an explicit Open starts over.
                self.sent = None;
                self.outcome = None;
                self.last_status = None;
            }
        }
        // Never reinterpret a dispatched operation as a new editable draft.
        let locked = self.sent.is_some() || cx.attempt.is_some_and(|a| a.locked());
        match input {
            ActionInput::Open(ActionSeed::Answer(b)) if !locked => {
                self.invalidate_preview();
                self.binding = Some(b);
                self.draft_op_id = operation_id();
                self.invalidated = false;
                self.kind = ReplyKind::Yes;
                self.words.clear();
                self.reason = None;
            }
            ActionInput::Edit { field, value } if !locked => {
                match field.as_str() {
                    "reply_kind" => {
                        let next = if value == format!("{} ", self.kind.label()) {
                            match (
                                self.kind,
                                self.binding
                                    .as_ref()
                                    .and_then(|b| b.question_id.as_ref())
                                    .is_some(),
                            ) {
                                (ReplyKind::Yes, true) => ReplyKind::Simplify,
                                (ReplyKind::Yes | ReplyKind::Simplify, _) => ReplyKind::OwnWords,
                                (ReplyKind::OwnWords, _) => ReplyKind::Yes,
                            }
                        } else {
                            match value.as_str() {
                                "yes" => ReplyKind::Yes,
                                "simplify"
                                    if self
                                        .binding
                                        .as_ref()
                                        .is_some_and(|b| b.question_id.is_some()) =>
                                {
                                    ReplyKind::Simplify
                                }
                                "own words" => ReplyKind::OwnWords,
                                _ => {
                                    self.reason =
                                        Some("Use Space to select a supported reply kind".into());
                                    return ActionResult {
                                        view: self.view(cx),
                                        request,
                                    };
                                }
                            }
                        };
                        self.kind = next;
                    }
                    "own_words" if self.kind == ReplyKind::OwnWords => self.words = value,
                    _ => {
                        self.reason = Some("Unknown or unavailable answer field".into());
                        return ActionResult {
                            view: self.view(cx),
                            request,
                        };
                    }
                }
                self.invalidate_preview();
                self.reason = None;
            }
            ActionInput::Preview if !locked && self.pending_revision.is_none() => {
                self.invalidate_preview();
                match self.eligible(cx) {
                    Ok(()) => {
                        self.pending_revision = Some(self.revision);
                        self.status = "previewing; nothing sent".into();
                        self.reason = None;
                        request = Some(ActionRequest::SendPreview {
                            target: self
                                .binding
                                .as_ref()
                                .unwrap()
                                .target
                                .known()
                                .unwrap()
                                .as_ref()
                                .unwrap()
                                .clone(),
                            mode: Mode::Queue,
                        });
                    }
                    Err(why) => self.reason = Some(why),
                }
            }
            ActionInput::Confirm { press_id } if !locked && press_id > self.last_press => {
                self.last_press = press_id;
                match self.eligible(cx).and_then(|()| self.preview_ready()) {
                    Err(why) => {
                        self.invalidate_preview();
                        self.status = "unavailable; nothing sent".into();
                        self.reason = Some(why);
                    }
                    Ok(())
                        if self.binding.as_ref().is_some_and(|b| b.risk != "ordinary")
                            && self.first_press.is_none() =>
                    {
                        self.first_press = Some(press_id);
                        self.status =
                            "confirmed 1 of 2; separate risky confirmation required".into();
                    }
                    Ok(()) => {
                        let send = SendInput {
                            target: self
                                .binding
                                .as_ref()
                                .unwrap()
                                .target
                                .known()
                                .unwrap()
                                .as_ref()
                                .unwrap()
                                .clone(),
                            text: self.reply().unwrap(),
                            mode: Mode::Queue,
                            op_id: self.draft_op_id.clone(),
                            resume_paused_queue: false,
                            accept_possible_duplicate: false,
                        };
                        self.sent = Some(send.clone());
                        self.status = "dispatching; do not resend".into();
                        self.reason = None;
                        request = Some(ActionRequest::Send(send));
                    }
                }
            }
            ActionInput::Response { result, .. } => {
                if !locked && let Some(revision) = self.pending_revision.take() {
                    if revision == self.revision {
                        if let TransportResult::Report { body, .. } = result {
                            match serde_json::from_value::<PreviewReport>(body) {
                                Ok(report) => {
                                    self.preview = Some(Preview {
                                        report,
                                        received: Instant::now(),
                                    });
                                    self.reason =
                                        self.eligible(cx).and_then(|()| self.preview_ready()).err();
                                    self.status = if self.reason.is_none() {
                                        "ready; nothing sent"
                                    } else {
                                        "unavailable; nothing sent"
                                    }
                                    .into();
                                }
                                Err(_) => self.reason = Some("Invalid preview report".into()),
                            }
                        } else {
                            self.reason = Some(match result {
                                TransportResult::Refused {
                                    http_status,
                                    reason,
                                } => format!("Preview unavailable (HTTP {http_status}): {reason}"),
                                TransportResult::FailedBeforeDispatch { reason }
                                | TransportResult::UnknownAfterDispatch { reason } => {
                                    format!("Preview unavailable: {reason}")
                                }
                                TransportResult::Report { .. } => "Invalid preview report".into(),
                            });
                        }
                    }
                } else if locked && let Some(attempt) = cx.attempt {
                    self.sync_attempt(attempt);
                }
            }
            ActionInput::Cancel if !locked => {
                self.invalidate_preview();
                self.status = "cancelled; nothing sent".into();
            }
            ActionInput::Snapshot { .. } if !locked => {
                if let Err(why) = self.eligible(cx) {
                    // Stale/incomplete reads can recover after a fresh read;
                    // a changed proposal/target must be explicitly reopened.
                    if let (Some(b), Some(d)) = (&self.binding, cx.decisions) {
                        self.invalidated |= d.target != b.target
                            || !d.items.iter().any(|i| {
                                i.repository == b.repository
                                    && i.comment_id == b.comment_id
                                    && i.subject_kind == b.subject_kind
                                    && i.subject_number == b.subject_number
                                    && i.record == b.record
                            });
                    }
                    self.invalidate_preview();
                    self.reason = Some(why);
                }
            }
            ActionInput::RefreshStatus if locked => {
                if let Some(s) = &self.sent {
                    request = Some(ActionRequest::Lookup {
                        target: s.target.clone(),
                        op_id: s.op_id.clone(),
                    });
                } else if let Some(a) = cx.attempt {
                    request = Some(ActionRequest::Lookup {
                        target: match &a.request {
                            ActionRequest::Send(s) => s.target.clone(),
                            _ => String::new(),
                        },
                        op_id: a.op_id.clone(),
                    });
                }
            }
            _ => {}
        }
        let mut view = self.view(cx);
        if !locked && view.reason.is_none() {
            view.reason = self.eligible(cx).err();
        }
        ActionResult { view, request }
    }
}
