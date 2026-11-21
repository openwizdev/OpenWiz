//! The scripted in-process source, a fixed clock and the list helpers the
//! inventory tests share: `openwiz-core`'s own tests here, and the proof
//! cases in `tests/proof`, which include this file (#805). It uses only
//! `openwiz-core` and the standard library.

#![allow(
    dead_code,
    reason = "included by more than one test target, and each uses only part of it"
)]

use std::collections::BTreeSet;
use std::sync::Mutex;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::thread;
use std::time::{Duration, Instant};

use openwiz_core::envelope::{Counts, Envelope, Gap, GapKind};
use openwiz_core::model::{Fact, Inventory, ProjectId, Session, SessionId, Timestamp};
use openwiz_core::ops::{self, Clock, Detail, ListRequest, OpError};
use openwiz_core::source::{
    MachineRecord, OutputRecord, Placement, ProjectRecord, Rows, SessionDetailRecord,
    SessionRecord, SessionScope, SessionSource, SourceError,
};

/// The fixed snapshot time the fixtures are written against.
pub const T0: Timestamp = Timestamp(1_700_000_600_000);

pub struct FixedClock(pub Timestamp);

/// A fixed wall clock. Deadlines still need real monotonic time, because
/// the reads they bound really wait.
impl Clock for FixedClock {
    fn now(&self) -> Timestamp {
        self.0
    }

    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}

pub fn clock() -> FixedClock {
    FixedClock(T0)
}

pub fn long() -> ListRequest {
    ListRequest {
        detail: Detail::Long,
        ..ListRequest::default()
    }
}

pub fn ids(envelope: &Envelope<Inventory>) -> Vec<String> {
    envelope
        .data
        .sessions
        .iter()
        .map(|s| s.id.0.clone())
        .collect()
}

pub fn id_set(envelope: &Envelope<Inventory>) -> BTreeSet<String> {
    ids(envelope).into_iter().collect()
}

pub fn session<'a>(envelope: &'a Envelope<Inventory>, id: &str) -> &'a Session {
    envelope
        .data
        .sessions
        .iter()
        .find(|s| s.id.0 == id)
        .unwrap_or_else(|| panic!("{id} is not in the result"))
}

pub fn has_gap(gaps: &[Gap], kind: GapKind, needle: &str) -> bool {
    gaps.iter().any(|g| {
        g.kind == kind
            && (g.subject.as_deref().unwrap_or("").contains(needle) || g.detail.contains(needle))
    })
}

pub fn unknown_reason<T: std::fmt::Debug>(fact: &Fact<T>) -> &str {
    match fact {
        Fact::Unknown(reason) => {
            assert!(!reason.trim().is_empty(), "an unknown must carry a reason");
            reason
        }
        Fact::Known(v) => panic!("expected unknown, got known {v:?}"),
    }
}

/// An in-process source with `n` synthetic sessions, for exact control of
/// paging, concurrency and timing.
pub struct ScriptedSource {
    pub records: Vec<SessionRecord>,
    pub detail_delay: Duration,
    in_flight: AtomicUsize,
    pub max_in_flight: AtomicUsize,
    pub detail_calls: Mutex<Vec<String>>,
    pub deadlines: Mutex<Vec<Instant>>,
    /// What `version` reports. Default `v127`.
    pub version: String,
    /// The project list. A test may change it between runs of one source.
    pub projects: Mutex<Vec<ProjectRecord>>,
    /// The machine list. Default empty.
    pub machines: Vec<MachineRecord>,
    /// Model and effort from every `session_detail`.
    pub configuration: (Fact<String>, Fact<String>),
    /// What every `session_output` returns.
    pub output: OutputRecord,
    /// Detail reads of these ids fail with the given error.
    pub failing_details: Vec<(String, SourceError)>,
}

pub fn scripted_project() -> ProjectRecord {
    ProjectRecord {
        id: ProjectId("prj_syn_0001".to_owned()),
        name: Fact::Known("Synthetic project one".to_owned()),
    }
}

pub fn scripted_record(n: usize) -> SessionRecord {
    SessionRecord {
        id: SessionId(format!("thr_syn_{n:04}")),
        project_id: Fact::Known(ProjectId("prj_syn_0001".to_owned())),
        title: Fact::Known(format!("Synthetic session {n}")),
        provider: Fact::Known("codex".to_owned()),
        status: Fact::Known("idle".to_owned()),
        hidden: Fact::Known(false),
        archived: Fact::Known(false),
        parent: Fact::Known(None),
        placement: Fact::Known(Placement::Cloud),
        purpose_text: Fact::Known(Some(format!("Synthetic purpose {n}."))),
        // Distinct times, so any sensible order is total.
        updated_at: Fact::Known(Timestamp(T0.0 - 1_000 * n as i64)),
        started_at: Fact::Unknown("room-cli did not report a start time".to_owned()),
        problems: vec![],
    }
}

impl ScriptedSource {
    pub fn new(n: usize) -> Self {
        Self::with_records((1..=n).map(scripted_record).collect())
    }

    pub fn with_records(records: Vec<SessionRecord>) -> Self {
        Self {
            records,
            detail_delay: Duration::ZERO,
            in_flight: AtomicUsize::new(0),
            max_in_flight: AtomicUsize::new(0),
            detail_calls: Mutex::new(vec![]),
            deadlines: Mutex::new(vec![]),
            version: "v127".to_owned(),
            projects: Mutex::new(vec![scripted_project()]),
            machines: vec![],
            configuration: (
                Fact::Known("synthetic-model-a".to_owned()),
                Fact::Known("high".to_owned()),
            ),
            output: OutputRecord {
                output: Fact::Known(Some("Synthetic final output.".to_owned())),
                error: Fact::Known(None),
                problems: vec![],
            },
            failing_details: vec![],
        }
    }

    pub fn with_delay(mut self, delay: Duration) -> Self {
        self.detail_delay = delay;
        self
    }

    pub fn with_version(mut self, version: &str) -> Self {
        self.version = version.to_owned();
        self
    }

    pub fn with_projects(self, projects: Vec<ProjectRecord>) -> Self {
        self.set_projects(projects);
        self
    }

    /// Replaces the project list, for the next run of this same source.
    pub fn set_projects(&self, projects: Vec<ProjectRecord>) {
        *self.projects.lock().unwrap() = projects;
    }

    pub fn with_machines(mut self, machines: Vec<MachineRecord>) -> Self {
        self.machines = machines;
        self
    }

    pub fn with_configuration(mut self, model: Fact<String>, effort: Fact<String>) -> Self {
        self.configuration = (model, effort);
        self
    }

    pub fn with_output(mut self, output: OutputRecord) -> Self {
        self.output = output;
        self
    }

    pub fn with_failing_detail(mut self, id: &str, error: SourceError) -> Self {
        self.failing_details.push((id.to_owned(), error));
        self
    }

    fn failure(&self, id: &SessionId) -> Option<SourceError> {
        let (_, error) = self.failing_details.iter().find(|(f, _)| *f == id.0)?;
        self.detail_calls.lock().unwrap().push(id.0.clone());
        Some(error.clone())
    }

    pub fn detail_ids(&self) -> BTreeSet<String> {
        self.detail_calls.lock().unwrap().iter().cloned().collect()
    }

    fn note_deadline(&self, deadline: Instant) {
        self.deadlines.lock().unwrap().push(deadline);
    }

    fn detail_read<T>(
        &self,
        id: &SessionId,
        deadline: Instant,
        make: impl FnOnce() -> T,
    ) -> Result<T, SourceError> {
        self.note_deadline(deadline);
        self.detail_calls.lock().unwrap().push(id.0.clone());
        let now = self.in_flight.fetch_add(1, Ordering::SeqCst) + 1;
        self.max_in_flight.fetch_max(now, Ordering::SeqCst);
        let finish = Instant::now() + self.detail_delay;
        let result = if finish > deadline {
            thread::sleep(deadline.saturating_duration_since(Instant::now()));
            Err(SourceError::TimedOut {
                after_ms: self.detail_delay.as_millis() as u64,
            })
        } else {
            thread::sleep(self.detail_delay);
            Ok(make())
        };
        self.in_flight.fetch_sub(1, Ordering::SeqCst);
        result
    }

    fn record(&self, id: &SessionId) -> Result<SessionRecord, SourceError> {
        self.records
            .iter()
            .find(|r| &r.id == id)
            .cloned()
            .ok_or(SourceError::NotFound {
                subject: id.0.clone(),
            })
    }
}

impl SessionSource for ScriptedSource {
    fn name(&self) -> &str {
        "room-cli"
    }

    fn tested_version(&self) -> &str {
        "v127"
    }

    fn version(&self, deadline: Instant) -> Result<String, SourceError> {
        self.note_deadline(deadline);
        Ok(self.version.clone())
    }

    fn list_sessions(
        &self,
        _scope: SessionScope,
        deadline: Instant,
    ) -> Result<Rows<SessionRecord>, SourceError> {
        self.note_deadline(deadline);
        Ok(Rows {
            records: self.records.clone(),
            unreadable: vec![],
        })
    }

    fn list_projects(
        &self,
        _include_hidden: bool,
        deadline: Instant,
    ) -> Result<Rows<ProjectRecord>, SourceError> {
        self.note_deadline(deadline);
        Ok(Rows {
            records: self.projects.lock().unwrap().clone(),
            unreadable: vec![],
        })
    }

    fn list_machines(&self, deadline: Instant) -> Result<Rows<MachineRecord>, SourceError> {
        self.note_deadline(deadline);
        Ok(Rows {
            records: self.machines.clone(),
            unreadable: vec![],
        })
    }

    fn session_detail(
        &self,
        id: &SessionId,
        deadline: Instant,
    ) -> Result<SessionDetailRecord, SourceError> {
        let session = self.record(id)?;
        if let Some(error) = self.failure(id) {
            return Err(error);
        }
        let (model, effort) = self.configuration.clone();
        self.detail_read(id, deadline, || SessionDetailRecord {
            session,
            model,
            effort,
        })
    }

    fn session_output(
        &self,
        id: &SessionId,
        deadline: Instant,
    ) -> Result<OutputRecord, SourceError> {
        self.record(id)?;
        if let Some(error) = self.failure(id) {
            return Err(error);
        }
        let output = self.output.clone();
        self.detail_read(id, deadline, || output)
    }
}

/// Lists through the core with a scripted source and the fixed clock.
pub fn list_scripted(
    source: &ScriptedSource,
    request: &ListRequest,
) -> Result<Envelope<Inventory>, OpError> {
    ops::list(source, &clock(), request)
}

/// The counts reconcile: every listed row is unreadable, excluded or
/// matched, and the page shows `min(limit, matched - offset)` of them.
pub fn reconcile(c: &Counts) {
    assert_eq!(
        c.listed,
        c.unreadable + c.excluded_hidden + c.excluded_archived + c.matched,
        "listed must equal unreadable + excluded + matched: {c:?}"
    );
    let expected_shown = c.limit.min(c.matched.saturating_sub(c.offset));
    assert_eq!(
        c.shown, expected_shown,
        "shown must be min(limit, matched - offset): {c:?}"
    );
}
