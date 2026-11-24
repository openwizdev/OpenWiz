use std::time::Instant;

use serde::Serialize;

use crate::attachment::PromptAttachment;
use crate::envelope::SourceInfo;
use crate::messaging::record::StoreError;
use crate::messaging::send::read_failure;
use crate::messaging::{InvalidRequest, OpId};
use crate::model::{Fact, Timestamp};
use crate::ops::{Clock, version_fact};
use crate::prompt::{
    ClaimOutcome, GateError, NoAttachments, OpKind, OpRef, ReadyPrompt, StagedAttachments,
    attachment_allowance, attachments_digest, gate, recorded,
};
use crate::source::SourceError;

use super::effects::{Effects, ProjectCandidate, effects_for, resolve_project};
use super::options::{Catalogue, NotOfferedField, cloud_options};
use super::outcome::{FailReason, Gap, Outcome, RefusalReason, SpawnReply, Status};
use super::record::{Claim, NewThreadRecord, NewThreadStore, RecordState};
use super::start::{ShownThread, StartView};
use super::{
    Binding, BindingField, NEW_THREAD_SCHEMA_ID, NewThreadRequest, ProjectRef, ProjectView,
    Settings, request_id,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SpawnRequest {
    pub project_id: String,
    pub provider: String,
    pub model: String,
    pub effort: String,
    pub request_id: String,
    pub prompt: ReadyPrompt,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ObservedThread {
    pub id: String,
    pub created_at: Fact<Timestamp>,
}

pub trait NewThreadClient: Send + Sync {
    fn name(&self) -> &str;

    fn tested_version(&self) -> &str;

    fn cli_levels(&self) -> &[&str];

    fn version(&self, deadline: Instant) -> Result<String, SourceError>;

    fn projects(&self, deadline: Instant) -> Result<Vec<ProjectCandidate>, SourceError>;

    fn catalogue(&self, deadline: Instant) -> Result<Catalogue, SourceError>;

    fn spawn(&self, spawn: &SpawnRequest, deadline: Instant) -> SpawnReply;

    fn show_thread(&self, thread_id: &str, deadline: Instant) -> Result<ShownThread, SourceError>;

    fn threads_since(
        &self,
        project_id: &str,
        since: Timestamp,
        deadline: Instant,
    ) -> Result<Vec<ObservedThread>, SourceError>;
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum NewThreadResult {
    Outcome {
        outcome: Outcome,
        replayed: bool,
        recovered: bool,
    },
    InProgress {
        state: Option<RecordState>,
    },
    ConflictingReuse {
        differs: Vec<BindingField>,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct NewThreadReport {
    pub schema: String,
    pub op_id: OpId,
    pub request_id: String,
    pub project_ref: ProjectRef,
    pub project: Option<ProjectView>,
    pub source: Option<SourceInfo>,
    pub requested: Settings,
    pub provider: Option<String>,
    pub status: Status,
    pub summary: String,
    pub result: NewThreadResult,
    pub effects: Option<Effects>,
    pub text_sha256: String,
    pub attachments_digest: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub attachments: Vec<PromptAttachment>,
    pub text_bytes: u64,
    pub gaps: Vec<Gap>,
    pub claimed_at: Option<Timestamp>,
    pub dispatching_at: Option<Timestamp>,
    pub finished_at: Option<Timestamp>,
    pub start: Option<StartView>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NewThreadError {
    Invalid(InvalidRequest),
    Store(StoreError),
}

struct Look {
    project: Option<ProjectView>,
    outcome: Result<(Effects, String), Outcome>,
    gaps: Vec<Gap>,
}

fn look(
    client: &dyn NewThreadClient,
    clock: &dyn Clock,
    request: &NewThreadRequest,
    deadline: Instant,
) -> Look {
    let mut look = Look {
        project: None,
        outcome: Err(Outcome::failed(FailReason::ProjectsNotRead)),
        gaps: vec![],
    };
    let projects = match client.projects(deadline) {
        Ok(projects) => projects,
        Err(e) => {
            look.gaps.push(Gap {
                subject: "project list".to_owned(),
                detail: read_failure("project list", &e),
            });
            return look;
        }
    };
    let project = match resolve_project(&request.project, &projects) {
        Ok(project) => project,
        Err(reason) => {
            look.outcome = Err(Outcome::refused(reason));
            return look;
        }
    };
    look.project = Some(project.clone());
    let read_at = clock.now();
    let options = cloud_options(client.catalogue(deadline), client.cli_levels(), read_at);
    let provider = match options.offered(&request.settings) {
        Ok(provider) => provider,
        Err(not) => {
            let reason = match not.field {
                NotOfferedField::Options => RefusalReason::NoOptions,
                NotOfferedField::Harness => RefusalReason::HarnessNotOffered,
                NotOfferedField::Model => RefusalReason::ModelNotOffered,
                NotOfferedField::Effort => RefusalReason::EffortNotOffered,
            };
            look.outcome = Err(Outcome::refused_because(reason, &not.text, not.offered));
            return look;
        }
    };
    look.outcome = Ok((effects_for(&project, read_at), provider));
    look
}

pub fn new_thread(
    client: &dyn NewThreadClient,
    store: &dyn NewThreadStore,
    clock: &dyn Clock,
    request: &NewThreadRequest,
) -> Result<NewThreadReport, NewThreadError> {
    new_thread_with(client, store, &NoAttachments, clock, request)
}

pub fn new_thread_with(
    client: &dyn NewThreadClient,
    store: &dyn NewThreadStore,
    attachments: &dyn StagedAttachments,
    clock: &dyn Clock,
    request: &NewThreadRequest,
) -> Result<NewThreadReport, NewThreadError> {
    request.validate().map_err(NewThreadError::Invalid)?;
    let mut deadline = clock.monotonic() + request.budget;
    let op = OpRef {
        kind: OpKind::NewThread,
        op_id: request.op_id.clone(),
    };

    let known = store.load(&request.op_id).map_err(NewThreadError::Store)?;
    let (binding, bound, mut ready) = match &known {
        Some(record) => {
            let ids = &request.prompt.attachments;
            match recorded(attachments, ids, &record.attachments, clock.now())
                .map_err(|e| gate_error(GateError::Store(e)))?
            {
                Some(list) => (Binding::new(request, attachments_digest(&list)), list, None),
                None => {
                    let binding = Binding::new(request, record.binding.attachments_digest.clone());
                    let mut differs = record.binding.differences(&binding);
                    differs.push(BindingField::Attachments);
                    return Ok(conflicting_reuse(request, &binding, &[], differs));
                }
            }
        }
        None => {
            let ready = pass_gate(attachments, request, &op, clock)?;
            (
                Binding::new(request, ready.attachments_digest()),
                ready.bound(),
                Some(ready),
            )
        }
    };
    let claimed = NewThreadRecord::claimed(
        request.op_id.clone(),
        binding.clone(),
        request.settings.clone(),
        &request.prompt.text,
        clock.now(),
    )
    .with_attachments(bound.clone());
    match store
        .claim(&claimed, clock.now())
        .map_err(NewThreadError::Store)?
    {
        Claim::Owned => {}
        Claim::Existing(record) | Claim::InProgress(record)
            if !record.binding.differences(&binding).is_empty() =>
        {
            let differs = record.binding.differences(&binding);
            return Ok(conflicting_reuse(request, &binding, &bound, differs));
        }
        Claim::Existing(record) => return Ok(from_record(&record, true, vec![])),
        Claim::InProgress(record) => {
            return Ok(in_progress(request, &binding, &bound, Some(&record)));
        }
        Claim::Pending => return Ok(in_progress(request, &binding, &bound, None)),
    }

    let ready = match ready.take() {
        Some(ready) => ready,
        None => match pass_gate(attachments, request, &op, clock) {
            Ok(ready) => ready,
            Err(e) => {
                let _ = store.withdraw(&request.op_id);
                return Err(e);
            }
        },
    };
    let ids = request.prompt.attachments.clone();
    match attachments.claim(&op, &ids, clock.now()) {
        Ok(ClaimOutcome::Claimed { .. }) => {}
        Ok(ClaimOutcome::Refused(refusal)) => {
            let _ = store.withdraw(&request.op_id);
            return Err(NewThreadError::Invalid(InvalidRequest(refusal.words())));
        }
        Err(e) => {
            let _ = store.withdraw(&request.op_id);
            return Err(NewThreadError::Store(StoreError(format!(
                "{e}; the attachments could not be claimed, so nothing was sent"
            ))));
        }
    }
    deadline += attachment_allowance(ready.total_bytes());
    let created = Dispatch {
        client,
        store,
        attachments,
        clock,
        request,
        op: &op,
        ready: &ready,
        deadline,
    }
    .run(claimed);
    store.release(&request.op_id);
    created
}

fn pass_gate(
    attachments: &dyn StagedAttachments,
    request: &NewThreadRequest,
    op: &OpRef,
    clock: &dyn Clock,
) -> Result<ReadyPrompt, NewThreadError> {
    gate(attachments, &request.prompt, op, clock.now()).map_err(gate_error)
}

fn gate_error(e: GateError) -> NewThreadError {
    match e {
        GateError::Refused(refusal) => NewThreadError::Invalid(InvalidRequest(refusal.words())),
        GateError::Store(e) => NewThreadError::Store(StoreError(format!(
            "{e}; the attachments could not be read, so nothing was sent"
        ))),
    }
}

struct Dispatch<'a> {
    client: &'a dyn NewThreadClient,
    store: &'a dyn NewThreadStore,
    attachments: &'a dyn StagedAttachments,
    clock: &'a dyn Clock,
    request: &'a NewThreadRequest,
    op: &'a OpRef,
    ready: &'a ReadyPrompt,
    deadline: Instant,
}

impl Dispatch<'_> {
    fn run(&self, mut record: NewThreadRecord) -> Result<NewThreadReport, NewThreadError> {
        let (source, version_gap) = read_source(self.client, self.deadline);
        record.source = Some(source);
        record.gaps.extend(version_gap);

        let look = look(self.client, self.clock, self.request, self.deadline);
        record.project = look.project;
        record.gaps.extend(look.gaps);
        let (effects, provider) = match look.outcome {
            Ok(found) => found,
            Err(outcome) => return self.finish(record, outcome),
        };
        record.effects = Some(effects.clone());
        record.provider = Some(provider.clone());
        if self.clock.monotonic() >= self.deadline {
            return self.finish(record, Outcome::failed(FailReason::BudgetExhausted));
        }

        let record = record.dispatching(self.clock.now());
        if let Err(e) = self.store.update(&record) {
            return Err(NewThreadError::Store(StoreError(format!(
                "{e}; the dispatching mark could not be written, so nothing was sent"
            ))));
        }
        let spawn = SpawnRequest {
            project_id: effects.project.id.clone(),
            provider,
            model: self.request.settings.model.clone(),
            effort: self.request.settings.effort.clone(),
            request_id: record.request_id.clone(),
            prompt: self.ready.clone(),
        };
        let (outcome, gaps) = Outcome::from_reply(self.client.spawn(&spawn, self.deadline));
        let outcome = outcome.with_attachments(self.ready.attachments.len());
        let mut record = record;
        record.gaps.extend(gaps);
        self.finish(record, outcome)
    }

    fn finish(
        &self,
        record: NewThreadRecord,
        outcome: Outcome,
    ) -> Result<NewThreadReport, NewThreadError> {
        let finished = record.finished(outcome, self.clock.now());
        let mut gaps = vec![];
        if let Err(e) = self.store.update(&finished) {
            gaps.push(Gap {
                subject: "new-thread record".to_owned(),
                detail: format!(
                    "the outcome could not be recorded ({e}); the record will recover as {}",
                    match record.state {
                        RecordState::Claimed => "failed (interrupted before dispatch)",
                        _ => "uncertain",
                    }
                ),
            });
        } else if !self.request.prompt.attachments.is_empty()
            && let Err(e) =
                self.attachments
                    .settle(self.op, &self.request.prompt.attachments, self.clock.now())
        {
            gaps.push(Gap {
                subject: "attachments".to_owned(),
                detail: format!(
                    "the attachments could not be settled after the outcome was recorded ({e}); \
                     the next sweep applies the retention rule"
                ),
            });
        }
        Ok(from_record(&finished, false, gaps))
    }
}

fn read_source(client: &dyn NewThreadClient, deadline: Instant) -> (SourceInfo, Option<Gap>) {
    let name = client.name();
    let tested = client.tested_version();
    let read = format!("{name} --version");
    let (version, version_tested) = version_fact(&read, tested, client.version(deadline));
    let gap = match &version {
        Fact::Unknown(why) => Some(Gap {
            subject: read,
            detail: why.clone(),
        }),
        Fact::Known(_) => None,
    };
    (
        SourceInfo {
            name: name.to_owned(),
            version,
            tested_version: tested.to_owned(),
            version_tested,
        },
        gap,
    )
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum PreviewVerdict {
    Ready { provider: String },
    Stopped { outcome: Outcome },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct NewThreadPreview {
    pub schema: String,
    pub op_id: OpId,
    pub request_id: String,
    pub project_ref: ProjectRef,
    pub project: Option<ProjectView>,
    pub source: SourceInfo,
    pub requested: Settings,
    pub verdict: PreviewVerdict,
    pub effects: Option<Effects>,
    pub text_sha256: String,
    pub attachments_digest: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub attachments: Vec<PromptAttachment>,
    pub text_bytes: u64,
    pub gaps: Vec<Gap>,
}

pub const PREVIEW_SCHEMA_ID: &str = "openwiz.new-thread-preview.v1";

pub fn preview_new_thread_with(
    client: &dyn NewThreadClient,
    attachments: &dyn StagedAttachments,
    clock: &dyn Clock,
    request: &NewThreadRequest,
) -> Result<NewThreadPreview, NewThreadError> {
    request.validate().map_err(NewThreadError::Invalid)?;
    let op = OpRef {
        kind: OpKind::NewThread,
        op_id: request.op_id.clone(),
    };
    let ready = pass_gate(attachments, request, &op, clock)?;
    let deadline = clock.monotonic() + request.budget;
    let (source, version_gap) = read_source(client, deadline);
    let look = look(client, clock, request, deadline);
    let mut gaps: Vec<Gap> = version_gap.into_iter().collect();
    gaps.extend(look.gaps);
    let (verdict, effects) = match look.outcome {
        Ok((effects, provider)) => (PreviewVerdict::Ready { provider }, Some(effects)),
        Err(outcome) => (PreviewVerdict::Stopped { outcome }, None),
    };
    let binding = Binding::new(request, ready.attachments_digest());
    Ok(NewThreadPreview {
        schema: PREVIEW_SCHEMA_ID.to_owned(),
        op_id: request.op_id.clone(),
        request_id: request_id(&request.op_id),
        project_ref: request.project.clone(),
        project: look.project,
        source,
        requested: request.settings.clone(),
        verdict,
        effects,
        text_sha256: binding.text_sha256,
        attachments_digest: binding.attachments_digest,
        attachments: ready.bound(),
        text_bytes: request.prompt.text.len() as u64,
        gaps,
    })
}

pub(crate) fn from_record(
    record: &NewThreadRecord,
    replayed: bool,
    extra_gaps: Vec<Gap>,
) -> NewThreadReport {
    let outcome = record.outcome.clone().unwrap_or_else(|| {
        Outcome::uncertain(crate::messaging::send::UncertainReason::InterruptedAfterDispatchMark)
    });
    let mut gaps = record.gaps.clone();
    gaps.extend(extra_gaps);
    NewThreadReport {
        schema: NEW_THREAD_SCHEMA_ID.to_owned(),
        op_id: record.op_id.clone(),
        request_id: record.request_id.clone(),
        project_ref: record.binding.project.clone(),
        project: record.project.clone(),
        source: record.source.clone(),
        requested: record.requested.clone(),
        provider: record.provider.clone(),
        status: outcome.status(),
        summary: summary(&record.requested, outcome.text()),
        result: NewThreadResult::Outcome {
            outcome,
            replayed,
            recovered: record.recovered,
        },
        effects: record.effects.clone(),
        text_sha256: record.binding.text_sha256.clone(),
        attachments_digest: record.binding.attachments_digest.clone(),
        attachments: record.attachments.clone(),
        text_bytes: record.text_bytes,
        gaps,
        claimed_at: Some(record.claimed_at),
        dispatching_at: record.dispatching_at,
        finished_at: record.finished_at,
        start: None,
    }
}

pub(crate) fn in_flight_report(record: &NewThreadRecord) -> NewThreadReport {
    let state = match record.state {
        RecordState::Claimed => "claimed",
        RecordState::Dispatching => "dispatching",
        RecordState::Finished => "finished",
    };
    NewThreadReport {
        status: Status::InProgress,
        summary: summary(
            &record.requested,
            &format!(
                "in progress: op {} is {state} by its process and has no outcome yet; no call \
                 was made here",
                record.op_id
            ),
        ),
        result: NewThreadResult::InProgress {
            state: Some(record.state),
        },
        finished_at: None,
        ..from_record(record, false, vec![])
    }
}

fn summary(requested: &Settings, words: &str) -> String {
    format!(
        "{} · {} · {} requested · {words}",
        requested.harness, requested.model, requested.effort
    )
}

fn refusal(
    request: &NewThreadRequest,
    binding: &Binding,
    bound: &[PromptAttachment],
    status: Status,
    words: String,
    result: NewThreadResult,
) -> NewThreadReport {
    NewThreadReport {
        schema: NEW_THREAD_SCHEMA_ID.to_owned(),
        op_id: request.op_id.clone(),
        request_id: request_id(&request.op_id),
        project_ref: request.project.clone(),
        project: None,
        source: None,
        requested: request.settings.clone(),
        provider: None,
        status,
        summary: summary(&request.settings, &words),
        result,
        effects: None,
        text_sha256: binding.text_sha256.clone(),
        attachments_digest: binding.attachments_digest.clone(),
        attachments: bound.to_vec(),
        text_bytes: request.prompt.text.len() as u64,
        gaps: vec![],
        claimed_at: None,
        dispatching_at: None,
        finished_at: None,
        start: None,
    }
}

fn conflicting_reuse(
    request: &NewThreadRequest,
    binding: &Binding,
    bound: &[PromptAttachment],
    differs: Vec<BindingField>,
) -> NewThreadReport {
    let names: Vec<&str> = differs.iter().map(|f| f.as_str()).collect();
    let words = format!(
        "refused: op {} is bound to a different {}; no call was made",
        request.op_id,
        names.join(", ")
    );
    refusal(
        request,
        binding,
        bound,
        Status::ConflictingReuse,
        words,
        NewThreadResult::ConflictingReuse { differs },
    )
}

fn in_progress(
    request: &NewThreadRequest,
    binding: &Binding,
    bound: &[PromptAttachment],
    record: Option<&NewThreadRecord>,
) -> NewThreadReport {
    let words = format!(
        "in progress: another process is creating op {}; no call was made here",
        request.op_id
    );
    let mut report = refusal(
        request,
        binding,
        bound,
        Status::InProgress,
        words,
        NewThreadResult::InProgress {
            state: record.map(|r| r.state),
        },
    );
    if let Some(record) = record {
        report.claimed_at = Some(record.claimed_at);
        report.dispatching_at = record.dispatching_at;
    }
    report
}
