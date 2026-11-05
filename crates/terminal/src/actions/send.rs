//! One bound message, using only the shell's guarded transport and attempt.
//! Draft edits invalidate preview; a dispatched attempt only offers lookup.
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use openwiz_core::messaging::lookup::{LookupReport, LookupResult};
use openwiz_core::messaging::preview::{PreviewReport, PreviewStatus};
use openwiz_core::messaging::send::{SendReport, Status};
use openwiz_core::messaging::{sha256_hex, validate_text};
use openwiz_core::model::Fact;
use serde_json::Value;

use super::{
    Action, ActionContext, ActionId, ActionInput, ActionRequest, ActionResult, ActionSeed,
    ActionView, Mode, SendInput, TransportResult,
};

pub fn register() -> Option<Box<dyn Action>> {
    Some(Box::new(Composer::default()))
}

enum Pending {
    Preview(u64),
    Send,
    Lookup,
}

#[derive(Default)]
struct Composer {
    target: String,
    text: String,
    mode: Mode,
    resume: bool,
    duplicate: bool,
    revision: u64,
    preview: Option<PreviewReport>,
    pending: Option<Pending>,
    bound: Option<SendInput>,
    sent: bool,
    // Only a transport failure positively known to precede dispatch.
    can_edit: bool,
    status: String,
    reason: Option<String>,
    outcome: Option<String>,
}

fn op_id() -> String {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let time = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!(
        "tui-{time:x}-{:x}-{:x}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    )
}

fn escaped(s: &str) -> String {
    s.escape_debug().to_string()
}

fn ticked(yes: bool) -> String {
    if yes { "[x]" } else { "[ ]" }.into()
}

impl Composer {
    fn invalidate(&mut self) {
        self.revision = self.revision.wrapping_add(1);
        self.preview = None;
        self.bound = None;
        self.status = "editing".into();
        self.reason = Some("Changed: Ctrl-P to preview again; nothing was sent".into());
        self.outcome = None;
    }

    fn edit(&mut self, field: &str, value: &str) {
        if self.sent && !self.can_edit {
            self.reason = Some("Attempt locked; Ctrl-R only checks its status".into());
            return;
        }
        match field {
            "text" => {
                // The shell appends/pops the displayed value. Apply that edit
                // to the exact bytes, rather than adopting escaped display text.
                let shown = escaped(&self.text);
                if let Some(append) = value.strip_prefix(&shown) {
                    if append.is_empty() {
                        return;
                    }
                    self.text.push_str(append);
                } else if shown
                    .char_indices()
                    .next_back()
                    .is_some_and(|(i, _)| &shown[..i] == value)
                {
                    self.text.pop();
                } else {
                    self.reason = Some("Text edit did not match the displayed draft".into());
                    return;
                }
            }
            "mode" if value == format!("{} ", self.mode.requested()) => {
                self.mode = match self.mode {
                    Mode::Queue => Mode::Steer,
                    Mode::Steer => Mode::Queue,
                };
                self.resume = false;
                self.duplicate = false;
            }
            "resume_paused_queue" if value == format!("{} ", ticked(self.resume)) => {
                self.resume = !self.resume
            }
            "accept_possible_duplicate" if value == format!("{} ", ticked(self.duplicate)) => {
                self.duplicate = !self.duplicate
            }
            _ => {
                self.reason = Some("Unknown field or unsupported edit; nothing changed".into());
                return;
            }
        }
        self.sent = false;
        self.can_edit = false;
        self.invalidate();
    }

    fn send_input(&self) -> SendInput {
        SendInput {
            target: self.target.clone(),
            text: self.text.clone(),
            mode: self.mode,
            op_id: op_id(),
            resume_paused_queue: self.resume,
            accept_possible_duplicate: self.duplicate,
        }
    }

    fn report_matches(&self, r: &SendReport) -> bool {
        self.bound.as_ref().is_some_and(|b| {
            r.target.id.0 == b.target
                && r.op_id.as_str() == b.op_id
                && r.requested_mode == b.mode
                && r.text_bytes == b.text.len() as u64
                && r.text_sha256 == sha256_hex(b.text.as_bytes())
                && r.attachments.is_empty()
                && r.attachments_digest.is_none()
        })
    }

    fn apply_report(&mut self, body: Value, lookup: bool) {
        let Ok(r) = serde_json::from_value::<SendReport>(body) else {
            self.bad_answer(lookup);
            return;
        };
        if !self.report_matches(&r) {
            self.bad_answer(lookup);
            return;
        }
        // A later unsuccessful lookup must not lower an unresolved outcome.
        if lookup
            && matches!(self.status.as_str(), "uncertain" | "in_progress")
            && !matches!(
                r.status,
                Status::Accepted
                    | Status::Queued
                    | Status::Uncertain
                    | Status::InProgress
                    | Status::Failed
            )
        {
            self.reason = Some("Lookup did not establish delivery; attempt remains locked".into());
            return;
        }
        self.can_edit = false;
        self.status = serde_json::to_value(r.status)
            .ok()
            .and_then(|v| v.as_str().map(str::to_owned))
            .unwrap_or_else(|| "uncertain".into());
        self.reason = Some(r.summary);
        self.outcome = Some(match r.status {
            Status::Accepted => "accepted by provider; work not completed".into(),
            Status::Queued => "queued by provider; work not completed".into(),
            Status::Uncertain => "uncertain; may have been sent; no resend".into(),
            Status::InProgress => "in_progress; attempt locked; no resend".into(),
            Status::Failed => "failed; no automatic retry".into(),
            Status::PossibleDuplicateRefused => {
                "possible_duplicate_refused; no send; no automatic retry".into()
            }
            Status::ConflictingReuse => "conflicting_reuse; operation binding differs".into(),
        });
    }

    fn bad_answer(&mut self, lookup: bool) {
        if !lookup {
            self.status = "uncertain".into();
        }
        self.reason =
            Some("Response did not match the bound attempt; keep locked and check status".into());
    }

    fn response(&mut self, result: TransportResult) {
        let Some(pending) = self.pending.take() else {
            return;
        };
        match pending {
            Pending::Preview(revision) => {
                if revision != self.revision {
                    return;
                }
                match result {
                    TransportResult::Report { body, .. } => {
                        let report = serde_json::from_value::<PreviewReport>(body);
                        match report {
                            Ok(p)
                                if p.target.id.0 == self.target
                                    && p.requested_mode == self.mode =>
                            {
                                self.status = match p.status {
                                    PreviewStatus::Refused => "refused",
                                    _ if p.effects.is_none() => "refused",
                                    _ if p
                                        .effects
                                        .as_ref()
                                        .is_some_and(|e| e.needs_acknowledgement)
                                        && !self.resume =>
                                    {
                                        "needs_acknowledgement"
                                    }
                                    _ => "ready",
                                }
                                .into();
                                self.reason = p.refusal.as_ref().map(|r| r.text.clone());
                                self.preview = Some(p);
                            }
                            _ => {
                                self.status = "refused".into();
                                self.reason = Some(
                                    "Preview target or mode did not match; nothing was sent".into(),
                                );
                            }
                        }
                    }
                    TransportResult::Refused { reason, .. }
                    | TransportResult::FailedBeforeDispatch { reason }
                    | TransportResult::UnknownAfterDispatch { reason } => {
                        self.status = "refused".into();
                        self.reason = Some(reason);
                    }
                }
            }
            Pending::Send | Pending::Lookup => {
                let lookup = matches!(pending, Pending::Lookup);
                match result {
                    TransportResult::Report { body, .. } if !lookup => {
                        self.apply_report(body, false)
                    }
                    TransportResult::Report { body, .. } => {
                        match serde_json::from_value::<LookupReport>(body) {
                            Ok(r) if self.bound.as_ref().is_some_and(|b| r.target.0 == b.target && r.op_id.as_str() == b.op_id) => match r.result {
                                LookupResult::Recorded { report } => self.apply_report(serde_json::to_value(report).unwrap_or(Value::Null), true),
                                LookupResult::NoRecord => self.reason = Some("no_record in this store; attempt stays locked, no resend".into()),
                                LookupResult::OtherTarget => self.reason = Some("other_target in this store; attempt stays locked, no resend".into()),
                            },
                            _ => self.bad_answer(true),
                        }
                    }
                    TransportResult::Refused { reason, .. } => {
                        if !lookup {
                            self.status = "refused".into();
                        }
                        self.reason = Some(reason);
                    }
                    TransportResult::FailedBeforeDispatch { reason } => {
                        if !lookup {
                            self.status = "failed".into();
                            self.can_edit = true;
                        }
                        self.reason = Some(reason);
                    }
                    TransportResult::UnknownAfterDispatch { reason } => {
                        if !lookup {
                            self.status = "uncertain".into();
                        }
                        self.reason = Some(reason);
                    }
                }
            }
        }
    }

    fn view(&self) -> ActionView {
        let mut effects = Vec::new();
        if let Some(p) = &self.preview {
            if let Some(e) = &p.effects {
                effects.push(match &e.effect {
                    Fact::Known(v) => v.text.clone(),
                    Fact::Unknown(why) => format!("Unknown effect: {why}"),
                });
                effects.push(match &e.paused_queue {
                    Fact::Known(v) => v.text.clone(),
                    Fact::Unknown(why) => format!("Paused queue unknown: {why}"),
                });
                // This view is cached between inputs. Name the server's
                // snapshot age rather than claim a frozen value is current.
                effects.push(format!("source read at {} (Unix ms)", e.read_at.0));
                effects.push(format!(
                    "reported age {}ms (preview snapshot)",
                    e.read_age_ms
                ));
            }
            effects.extend(p.gaps.iter().map(|g| format!("Gap: {}", g.detail)));
        }
        effects.push("Restart recovery unavailable; keep op id for CLI lookup".into());
        ActionView {
            title: "Message · preview, then confirm once".into(),
            target: self.target.clone(),
            fields: vec![
                (
                    "text".into(),
                    "text (escaped)".into(),
                    escaped(&self.text),
                    !self.sent || self.can_edit,
                ),
                (
                    "bytes".into(),
                    "UTF-8 bytes".into(),
                    self.text.len().to_string(),
                    false,
                ),
                (
                    "mode".into(),
                    "mode · Space".into(),
                    self.mode.requested().into(),
                    !self.sent || self.can_edit,
                ),
                (
                    "resume_paused_queue".into(),
                    "resume queue".into(),
                    ticked(self.resume),
                    !self.sent || self.can_edit,
                ),
                (
                    "accept_possible_duplicate".into(),
                    "allow duplicate".into(),
                    ticked(self.duplicate),
                    !self.sent || self.can_edit,
                ),
            ],
            effects,
            preview_age_ms: None,
            status: self.status.clone(),
            reason: self.reason.clone(),
            controls: if self.can_edit {
                vec![
                    "Edit to begin a new attempt".into(),
                    "Ctrl-R lookup".into(),
                    "Esc back".into(),
                ]
            } else if self.sent {
                vec!["Ctrl-R lookup (read only)".into(), "Esc back".into()]
            } else {
                vec![
                    "Tab field · Space toggle".into(),
                    "Ctrl-P preview".into(),
                    "Ctrl-S confirm".into(),
                    "Esc cancel".into(),
                    "PgUp/PgDn scroll".into(),
                ]
            },
            outcome: self.outcome.clone(),
            op_id: self.bound.as_ref().map(|b| b.op_id.clone()),
        }
    }
}

impl Action for Composer {
    fn id(&self) -> ActionId {
        ActionId::Send
    }

    fn update(&mut self, input: ActionInput, context: &ActionContext) -> ActionResult {
        let mut request = None;
        match input {
            ActionInput::Open(ActionSeed::Send { session_id }) => {
                if let Some(attempt) = context.attempt.filter(|a| a.locked()) {
                    if let ActionRequest::Send(b) = &attempt.request {
                        self.target = b.target.clone();
                        self.text = b.text.clone();
                        self.mode = b.mode;
                        self.resume = b.resume_paused_queue;
                        self.duplicate = b.accept_possible_duplicate;
                        self.bound = Some(b.clone());
                        self.sent = true;
                        self.can_edit = false;
                        if self.status.is_empty() {
                            self.status = "uncertain".into();
                        }
                        self.reason =
                            Some("Retained attempt; check status instead of sending again".into());
                    }
                } else if self.sent && self.can_edit && self.target == session_id {
                    self.reason =
                        Some("Nothing reached the server; edit to begin a new attempt".into());
                } else {
                    self.sent = false;
                    self.can_edit = false;
                    if self.target != session_id {
                        self.resume = false;
                        self.duplicate = false;
                    }
                    self.target = session_id;
                    self.invalidate();
                }
            }
            ActionInput::Open(_) => self.reason = Some("This action needs a chosen session".into()),
            ActionInput::Edit { field, value } => self.edit(&field, &value),
            ActionInput::Preview if !self.sent && self.pending.is_none() => {
                self.preview = None;
                if !context.guarded_available {
                    self.status = "refused".into();
                    self.reason = Some("No allowed host configured; sending unavailable".into());
                } else if let Err(e) = validate_text(&self.text) {
                    self.status = "editing".into();
                    self.reason = Some(e.to_string());
                } else {
                    self.bound = Some(self.send_input());
                    self.pending = Some(Pending::Preview(self.revision));
                    self.status = "previewing".into();
                    self.reason = None;
                    request = Some(ActionRequest::SendPreview {
                        target: self.target.clone(),
                        mode: self.mode,
                    });
                }
            }
            ActionInput::Confirm { .. }
                if !self.sent
                    && self.pending.is_none()
                    && self.status == "ready"
                    && context.guarded_available =>
            {
                if let Some(bound) = &self.bound {
                    self.sent = true;
                    self.status = "dispatching".into();
                    self.reason = Some("One request; never automatically retried".into());
                    self.pending = Some(Pending::Send);
                    request = Some(ActionRequest::Send(bound.clone()));
                }
            }
            ActionInput::Cancel if !self.sent => self.invalidate(),
            ActionInput::RefreshStatus if self.sent && self.pending.is_none() => {
                if let Some(b) = &self.bound {
                    request = Some(ActionRequest::Lookup {
                        target: b.target.clone(),
                        op_id: b.op_id.clone(),
                    });
                    self.pending = Some(Pending::Lookup);
                }
            }
            ActionInput::Response { result, .. } => self.response(result),
            // Snapshots/navigation never modify a draft or submit anything.
            _ => {}
        }
        ActionResult {
            view: self.view(),
            request,
        }
    }
}
