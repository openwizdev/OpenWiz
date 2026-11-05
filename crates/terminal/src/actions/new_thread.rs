//! One Cloud-thread draft, one explicit confirmation, at most one create.
//! Status checks never retry. The shell owns transport, guards and attempts.

use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use openwiz_core::messaging::{OpId, sha256_hex, validate_text};
use openwiz_core::new_thread::{Settings, request_id};
use openwiz_core::prompt::empty_attachments_digest;
use serde_json::Value;

use super::{
    Action, ActionContext, ActionId, ActionInput, ActionRequest, ActionResult, ActionSeed,
    ActionView, NewThreadInput, TransportResult,
};

pub fn register() -> Option<Box<dyn Action>> {
    Some(Box::new(NewThread::default()))
}

#[derive(Default)]
struct NewThread {
    draft: Option<NewThreadInput>,
    options: Option<Value>,
    ready: Option<NewThreadInput>,
    effects: Vec<String>,
    /// Latest successful operation/status read; separate from preview facts.
    status_lines: Vec<String>,
    revision: u64,
    pending: Option<(ActionRequest, u64)>,
    /// Set before returning Create; never cleared, including on refusal.
    attempted: bool,
    status: String,
    reason: Option<String>,
    outcome: Option<String>,
    /// Creation uncertainty cannot be downgraded by a missing/refused read.
    uncertain: bool,
}

fn string(v: &Value, key: &str) -> String {
    v.get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned()
}

fn rows<'a>(v: &'a Value, key: &str) -> &'a [Value] {
    v.get(key)
        .and_then(Value::as_array)
        .map_or(&[], Vec::as_slice)
}

fn gaps(label: &str, body: &Value) -> Vec<String> {
    rows(body, "gaps")
        .iter()
        .map(|gap| {
            format!(
                "{label}: {}: {}",
                string(gap, "subject"),
                string(gap, "detail")
            )
        })
        .collect()
}

fn new_op_id() -> String {
    static SEQUENCE: AtomicU64 = AtomicU64::new(0);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos());
    format!(
        "tui-new-{nanos:x}-{:x}-{:x}",
        std::process::id(),
        SEQUENCE.fetch_add(1, Ordering::Relaxed)
    )
}

impl NewThread {
    fn projects(context: &ActionContext) -> Vec<String> {
        let mut projects = Vec::new();
        if let Some(inventory) = context.inventory {
            for session in &inventory.sessions {
                if let Some((id, _)) = &session.project
                    && !projects.contains(id)
                {
                    projects.push(id.clone());
                }
            }
        }
        projects
    }

    fn choices(&self, field: &str, context: &ActionContext) -> Vec<String> {
        if field == "project" {
            return Self::projects(context);
        }
        let Some(options) = &self.options else {
            return vec![];
        };
        if options["state"]["kind"] != "offered" {
            return vec![];
        }
        let Some(draft) = &self.draft else {
            return vec![];
        };
        let harnesses = rows(options, "harnesses");
        if field == "harness" {
            return harnesses.iter().map(|h| string(h, "harness")).collect();
        }
        let Some(harness) = harnesses.iter().find(|h| h["harness"] == draft.harness) else {
            return vec![];
        };
        if field == "model" {
            return rows(harness, "models")
                .iter()
                .map(|m| string(m, "model"))
                .collect();
        }
        if field == "effort"
            && let Some(model) = rows(harness, "models")
                .iter()
                .find(|m| m["model"] == draft.model)
        {
            return rows(model, "efforts")
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect();
        }
        vec![]
    }

    fn invalid(&self, context: &ActionContext) -> Option<String> {
        if !context.guarded_available {
            return Some("No allowed host configured; creation and preview disabled".into());
        }
        let draft = self.draft.as_ref()?;
        if !Self::projects(context).contains(&draft.project_id) {
            return Some("Choose an existing project from the session inventory".into());
        }
        let Some(options) = &self.options else {
            return Some("Cloud options unavailable; Ctrl-R to read options".into());
        };
        if options["state"]["kind"] != "offered" {
            return Some(format!(
                "Cloud options unavailable: {}",
                string(&options["state"], "text")
            ));
        }
        for (field, chosen) in [
            ("harness", &draft.harness),
            ("model", &draft.model),
            ("effort", &draft.effort),
        ] {
            if chosen.is_empty() || !self.choices(field, context).contains(chosen) {
                return Some(format!(
                    "Choose an offered {field}; nothing is defaulted or substituted"
                ));
            }
        }
        validate_text(&draft.prompt).err().map(|e| e.to_string())
    }

    fn invalidate(&mut self) {
        self.revision += 1;
        self.ready = None;
        self.effects.clear();
        self.status = "changed: Ctrl-P to preview again".into();
        self.reason = None;
    }

    fn edit(&mut self, field: &str, value: String, context: &ActionContext) {
        if self.attempted {
            return;
        }
        let Some(draft) = &self.draft else {
            return;
        };
        let current = match field {
            "project" => &draft.project_id,
            "harness" => &draft.harness,
            "model" => &draft.model,
            "effort" => &draft.effort,
            "prompt" => &draft.prompt,
            _ => {
                self.reason = Some("Unknown new-thread field; nothing changed".into());
                return;
            }
        };
        // Choice rows accept Space to cycle, or exact typed/pasted ids.
        // Values are raw draft bytes, never labels or display substitutions.
        let value = if field != "prompt" && value == format!("{current} ") {
            let choices = self.choices(field, context);
            let next = choices
                .iter()
                .position(|c| c == current)
                .map_or(0, |i| (i + 1) % choices.len());
            choices.get(next).cloned().unwrap_or_default()
        } else {
            value
        };
        if current == &value {
            return;
        }
        self.invalidate();
        let draft = self.draft.as_mut().unwrap();
        match field {
            "project" => draft.project_id = value,
            "harness" => draft.harness = value,
            "model" => draft.model = value,
            "effort" => draft.effort = value,
            "prompt" => draft.prompt = value,
            _ => unreachable!(),
        }
        // Upstream choices invalidate unavailable downstream selections,
        // without selecting anything in their place.
        if field == "harness"
            && !self
                .choices("model", context)
                .contains(&self.draft.as_ref().unwrap().model)
        {
            self.draft.as_mut().unwrap().model.clear();
        }
        if matches!(field, "harness" | "model")
            && !self
                .choices("effort", context)
                .contains(&self.draft.as_ref().unwrap().effort)
        {
            self.draft.as_mut().unwrap().effort.clear();
        }
    }

    /// Full semantic binding, in addition to transport's whole-schema check.
    fn bound(report: &Value, draft: &NewThreadInput) -> bool {
        report["op_id"] == draft.op_id
            && OpId::parse(&draft.op_id).is_ok_and(|op| report["request_id"] == request_id(&op))
            && report["project_ref"]["kind"] == "id"
            && report["project_ref"]["value"] == draft.project_id
            && report["requested"]
                == serde_json::json!(Settings {
                    harness: draft.harness.clone(),
                    model: draft.model.clone(),
                    effort: draft.effort.clone(),
                })
            && report["text_sha256"] == sha256_hex(draft.prompt.as_bytes())
            && report["text_bytes"].as_u64() == Some(draft.prompt.len() as u64)
            && report["attachments_digest"] == empty_attachments_digest()
            && (report["project"].is_null() || report["project"]["id"] == draft.project_id)
            && (report["effects"].is_null()
                || report["effects"]["project"]["id"] == draft.project_id)
    }

    fn receive(&mut self, result: TransportResult) {
        let Some((request, revision)) = self.pending.take() else {
            return;
        };
        if matches!(request, ActionRequest::NewPreview(_)) && revision != self.revision {
            return;
        }
        match result {
            TransportResult::Report { body, .. } if body["schema"] == request.route().3 => {
                match request {
                    ActionRequest::Options => {
                        self.options = Some(body);
                        self.status = "editing: choose offered settings, then Ctrl-P".into();
                        self.reason = None;
                    }
                    ActionRequest::NewPreview(draft) => {
                        if !Self::bound(&body, &draft) {
                            self.reason = Some("Preview binding does not match this exact draft; creation disabled".into());
                            self.status = "preview refused".into();
                        } else if body["verdict"]["kind"] == "ready"
                            && body["project"]["id"] == draft.project_id
                            && !rows(&body["effects"], "effects").is_empty()
                        {
                            self.effects = rows(&body["effects"], "effects")
                                .iter()
                                .map(|e| string(e, "text"))
                                .collect();
                            self.effects.push(format!(
                                "Preview read at {}; inspect effects before confirming",
                                body["effects"]["read_at"]
                            ));
                            self.ready = Some(draft.clone());
                            self.status = "ready".into();
                            self.reason = None;
                        } else {
                            self.status = "preview stopped".into();
                            self.reason = Some(string(&body["verdict"]["outcome"], "text"));
                        }
                        if Self::bound(&body, &draft) {
                            self.effects.extend(gaps("Preview gap", &body));
                        }
                    }
                    ActionRequest::Create(draft) => {
                        if Self::bound(&body, &draft) {
                            self.report(&body, &body["start"]);
                        } else {
                            self.mark_uncertain(
                                "Create response binding does not match the attempt",
                            );
                        }
                    }
                    ActionRequest::Status { op_id } => {
                        if body["op_id"] != op_id {
                            self.reason = Some(
                                "Status is for a different operation; previous outcome retained"
                                    .into(),
                            );
                        } else if body["result"]["kind"] == "no_record" {
                            self.reason = Some("No record found; this does not prove nothing happened. Do not retry".into());
                        } else if let Some(draft) = &self.draft
                            && Self::bound(&body["result"]["report"], draft)
                        {
                            if self.report(&body["result"]["report"], &body["result"]["start"])
                                && !body["result"]["observations"].is_null()
                            {
                                let observations = &body["result"]["observations"];
                                self.status_lines.push(string(observations, "text"));
                                self.status_lines
                                    .extend(gaps("Observation gap", observations));
                            }
                        } else {
                            self.reason =
                                Some("Status binding differs; previous outcome retained".into());
                        }
                    }
                    _ => {}
                }
            }
            other => {
                let may_have_dispatched = matches!(
                    other,
                    TransportResult::UnknownAfterDispatch { .. } | TransportResult::Report { .. }
                );
                let reason = match other {
                    TransportResult::Refused {
                        http_status,
                        reason,
                    } => format!("HTTP {http_status}: {reason}"),
                    TransportResult::FailedBeforeDispatch { reason }
                    | TransportResult::UnknownAfterDispatch { reason } => reason,
                    TransportResult::Report { .. } => "Unexpected report schema".into(),
                };
                match request {
                    ActionRequest::Create(_) => {
                        // Even a pre-dispatch refusal ends this attempt. No
                        // retry affordance is exposed by this screen.
                        if may_have_dispatched {
                            self.mark_uncertain(&reason);
                        } else {
                            self.status = "refused/failed: nothing created by this request".into();
                            self.outcome = Some(self.status.clone());
                            self.reason = Some(reason);
                        }
                    }
                    ActionRequest::Status { .. } => {
                        self.reason = Some(format!(
                            "Status unavailable: {reason}; previous outcome retained"
                        ))
                    }
                    _ => {
                        self.ready = None;
                        self.status = "unavailable".into();
                        self.reason = Some(reason);
                        if matches!(request, ActionRequest::Options) {
                            self.options = None;
                        }
                    }
                }
            }
        }
    }

    fn mark_uncertain(&mut self, reason: &str) {
        self.uncertain = true;
        self.status = "uncertain".into();
        self.outcome =
            Some("Creation may have happened. Do not retry; Ctrl-R reads status only".into());
        self.reason = Some(reason.into());
    }

    fn report(&mut self, report: &Value, start: &Value) -> bool {
        let status = string(report, "status");
        // A refusal/failure on a later read cannot settle a possibly sent
        // create. Only its matching created record can establish creation.
        if self.uncertain && !matches!(status.as_str(), "created" | "uncertain" | "in_progress") {
            self.reason =
                Some("Later status did not resolve the uncertain attempt; do not retry".into());
            return false;
        }
        self.uncertain = matches!(status.as_str(), "uncertain" | "in_progress");
        self.status = status.clone();
        self.reason = None;
        self.outcome = Some(if status == "created" {
            "created: prompt recorded; started is a separate reported stage".into()
        } else {
            string(report, "summary")
        });
        self.status_lines.clear();
        let start =
            if !start.is_null() && start["thread_id"] == report["result"]["outcome"]["thread_id"] {
                start
            } else {
                &Value::Null
            };
        if status == "created" {
            self.status_lines.push(if start.is_null() {
                "Start: unknown; creation does not confirm start".into()
            } else {
                format!("Start: {}", string(&start["stage"], "text"))
            });
            self.status_lines.push(format!(
                "Created thread: {}",
                string(&report["result"]["outcome"], "thread_id")
            ));
            if !start.is_null() {
                if start["stage"]["kind"] == "start_failed" {
                    let error = &start["stage"]["last_error"];
                    self.status_lines.push(format!(
                        "Start: error {}",
                        error
                            .get("known")
                            .or_else(|| error.get("unknown"))
                            .and_then(Value::as_str)
                            .unwrap_or("not reported")
                    ));
                }
                self.status_lines
                    .push(format!("Reported: {}", string(&start["reported"], "label")));
                for setting in ["provider", "model", "effort"] {
                    self.status_lines.push(format!(
                        "Reported: {}",
                        string(&start["reported"][setting], "text")
                    ));
                }
            }
        }
        self.status_lines.extend(gaps("Create gap", report));
        self.status_lines.extend(gaps("Start gap", start));
        true
    }

    fn view(&self, context: &ActionContext) -> ActionView {
        let mut view = ActionView {
            title: "New Cloud thread".into(),
            status: self.status.clone(),
            reason: self
                .reason
                .clone()
                .or_else(|| (!self.attempted).then(|| self.invalid(context)).flatten()),
            effects: self
                .effects
                .iter()
                .chain(&self.status_lines)
                .cloned()
                .collect(),
            outcome: self.outcome.clone(),
            controls: if self.attempted {
                vec![
                    "Ctrl-R status (read only)".into(),
                    "Esc close".into(),
                    "PgUp/PgDn scroll".into(),
                ]
            } else {
                vec![
                    "Tab field; Space choice".into(),
                    "Ctrl-J newline".into(),
                    "Ctrl-P preview".into(),
                    "Ctrl-S create once".into(),
                    "Ctrl-R options".into(),
                    "Esc cancel".into(),
                    "PgUp/PgDn scroll".into(),
                ]
            },
            ..ActionView::default()
        };
        if let Some(draft) = &self.draft {
            view.target = draft.project_id.clone();
            view.op_id = Some(draft.op_id.clone());
            for (id, label, value) in [
                ("project", "project (Space)", &draft.project_id),
                ("harness", "harness (Space)", &draft.harness),
                ("model", "model (Space)", &draft.model),
                ("effort", "effort (Space)", &draft.effort),
                ("prompt", "first prompt", &draft.prompt),
            ] {
                view.fields
                    .push((id.into(), label.into(), value.clone(), !self.attempted));
            }
            if !self.attempted && self.ready.is_none() {
                for field in ["project", "harness", "model", "effort"] {
                    view.effects.push(format!(
                        "Offered {field}: {}",
                        self.choices(field, context).join(", ")
                    ));
                }
            }
        }
        if let Some(options) = &self.options {
            view.effects.push(format!(
                "Options read at {}; {} (source age unknown)",
                options["read_at"],
                string(options, "label")
            ));
            if !self.attempted && self.ready.is_none() {
                for unavailable in rows(options, "unavailable") {
                    view.effects.push(format!(
                        "{}: {}",
                        string(unavailable, "harness"),
                        string(unavailable, "text")
                    ));
                }
            }
        }
        if self.attempted {
            view.effects.push("Restart recovery is unavailable. Keep this op id; use openwiz new --status <op-id> --json after restart. Never retry creation".into());
        }
        view
    }
}

impl Action for NewThread {
    fn id(&self) -> ActionId {
        ActionId::NewThread
    }

    fn update(&mut self, input: ActionInput, context: &ActionContext) -> ActionResult {
        let mut request = None;
        match input {
            ActionInput::Open(ActionSeed::NewThread { project_id }) => {
                if !self.attempted {
                    self.invalidate();
                    self.draft = Some(NewThreadInput {
                        project_id,
                        harness: String::new(),
                        model: String::new(),
                        effort: String::new(),
                        prompt: String::new(),
                        op_id: new_op_id(),
                    });
                    self.options = None;
                    self.outcome = None;
                    self.status = "reading Cloud options".into();
                    if self.pending.is_none() {
                        request = Some(ActionRequest::Options);
                    }
                }
            }
            ActionInput::Open(_) => {
                self.reason = Some("Wrong action; new-thread draft unchanged".into())
            }
            ActionInput::Edit { field, value } => self.edit(&field, value, context),
            ActionInput::Preview if !self.attempted && self.pending.is_none() => {
                self.ready = None;
                self.effects.clear();
                self.reason = self.invalid(context);
                if self.reason.is_none()
                    && let Some(draft) = &self.draft
                {
                    request = Some(ActionRequest::NewPreview(draft.clone()));
                    self.status = "previewing; nothing created".into();
                }
            }
            ActionInput::Confirm { .. } if !self.attempted && self.pending.is_none() => {
                self.reason = self.invalid(context);
                if self.reason.is_none()
                    && self.ready.as_ref() == self.draft.as_ref()
                    && self.ready.is_some()
                {
                    self.attempted = true;
                    self.status = "dispatching; do not retry".into();
                    request = self.ready.take().map(ActionRequest::Create);
                } else if self.reason.is_none() {
                    self.reason =
                        Some("Preview this exact draft before confirming; nothing created".into());
                }
            }
            ActionInput::Cancel if !self.attempted => {
                self.invalidate();
                self.status = "cancelled; nothing created".into();
            }
            ActionInput::RefreshStatus if self.pending.is_none() => {
                if self.attempted {
                    request = self.draft.as_ref().map(|d| ActionRequest::Status {
                        op_id: d.op_id.clone(),
                    });
                } else {
                    self.invalidate();
                    request = Some(ActionRequest::Options);
                }
            }
            ActionInput::Response { result, .. } => self.receive(result),
            ActionInput::Snapshot { .. } if !self.attempted && self.invalid(context).is_some() => {
                self.ready = None;
            }
            _ => {}
        }
        if let Some(request) = &request {
            self.pending = Some((request.clone(), self.revision));
        }
        ActionResult {
            view: self.view(context),
            request,
        }
    }
}
