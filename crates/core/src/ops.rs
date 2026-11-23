use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::sync::Mutex;
use std::sync::atomic::{self, AtomicUsize};
use std::thread;
use std::time::{Duration, Instant};

use crate::envelope::{
    Completeness, Counts, Coverage, Envelope, Freshness, Gap, GapKind, SCHEMA_ID, SourceInfo,
};
use crate::limits::{
    DEFAULT_LIMIT, FIELD_MAX_CHARS, FINAL_OUTPUT_MAX_BYTES, MAX_CONCURRENT_DETAIL_READS, MAX_LIMIT,
    PURPOSE_MAX_CHARS, RUN_BUDGET, cap_field,
};
use crate::model::{
    BoundedText, Fact, FinalOutput, Grouping, Inventory, Location, ProjectId, Recap,
    ReportedConfiguration, Session, SessionId, SessionView, Timestamp,
};
use crate::source::{
    MachineRecord, Placement, ProjectRecord, Read, Rows, SessionDetailRecord, SessionRecord,
    SessionScope, SessionSource, SourceError,
};

pub trait Clock: Send + Sync {
    fn now(&self) -> Timestamp;

    fn monotonic(&self) -> Instant;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Detail {
    Short,
    Long,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ListRequest {
    pub detail: Detail,
    pub include_hidden: bool,
    pub include_archived: bool,
    pub limit: usize,
    pub offset: usize,
    pub budget: Duration,
}

impl Default for ListRequest {
    fn default() -> Self {
        Self {
            detail: Detail::Short,
            include_hidden: false,
            include_archived: false,
            limit: DEFAULT_LIMIT,
            offset: 0,
            budget: RUN_BUDGET,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ShowRequest {
    pub id: SessionId,
    pub budget: Duration,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OpError {
    ListFailed(SourceError),
    NotFound(SessionId),
    ShowFailed(SourceError),
    InvalidRequest(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct VersionRead {
    version: Fact<String>,
    tested: bool,
    gap: Option<Gap>,
}

pub fn is_version_text(text: &str) -> bool {
    let digits = |s: &str, max: usize| {
        !s.is_empty() && s.len() <= max && s.bytes().all(|b| b.is_ascii_digit())
    };
    if let Some(n) = text.strip_prefix('v') {
        return digits(n, 6);
    }
    let parts: Vec<&str> = text.split('.').collect();
    parts.len() == 3 && parts.iter().all(|p| digits(p, 4))
}

pub fn version_fact(
    read: &str,
    tested: &str,
    result: Result<String, SourceError>,
) -> (Fact<String>, bool) {
    match result {
        Ok(text) if is_version_text(&text) => {
            let is_tested = text == tested;
            (Fact::Known(text), is_tested)
        }
        Ok(_) => (
            Fact::Unknown(format!(
                "{read} printed text that is not a recognised version (withheld)"
            )),
            false,
        ),
        Err(e) => (
            Fact::Unknown(format!("{read} {}", version_failure(&e))),
            false,
        ),
    }
}

pub const VERSION_NOT_RECOGNISED: &str =
    "printed a version that is not N.N.N or v<N> (detail withheld)";

pub fn launch_failure_category(detail: &str) -> Option<&'static str> {
    match detail {
        "CloudRoom not running: room-cli could not be started (no bundled launcher and no \
         room-cli on PATH). Open the CloudRoom app once and sign in." => Some("no bundle"),
        "CloudRoom not running: room-cli could not be started (no running app identified). \
         Open the CloudRoom app once and sign in." => Some("no running app identified"),
        "CloudRoom not running: room-cli could not be started (ambiguous app bundles). \
         CloudRoom is mid-update (two running app mounts): restart CloudRoom to finish the \
         update, then try again." => Some("ambiguous bundle"),
        "CloudRoom not running: room-cli could not be started (unexpected bundle file)" => {
            Some("unexpected bundle")
        }
        "CloudRoom not running: room-cli could not be started (unreadable app bundle)" => {
            Some("unreadable bundle")
        }
        "room-cli could not be started" => Some("executable could not start"),
        _ => None,
    }
}

fn version_failure(error: &SourceError) -> String {
    match error {
        SourceError::CommandFailed {
            exit_code: Some(code),
            ..
        } => format!("exited {code} (detail withheld)"),
        SourceError::CommandFailed {
            exit_code: None, ..
        } => "ended without an exit code (detail withheld)".to_owned(),
        SourceError::TimedOut { after_ms } => format!("timed out after {after_ms} ms"),
        // PRIVACY: only OpenWiz's own fixed words are shown; any other detail is withheld.
        SourceError::Malformed { detail } if detail == VERSION_NOT_RECOGNISED => detail.clone(),
        SourceError::Malformed { .. } => "returned malformed output (detail withheld)".to_owned(),
        SourceError::Unavailable { detail } => match launch_failure_category(detail) {
            Some(category) => format!("could not be run ({category})"),
            None => "could not be run (detail withheld)".to_owned(),
        },
        SourceError::NotFound { .. } | SourceError::InvalidId { .. } => {
            "failed (detail withheld)".to_owned()
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Report<T> {
    pub envelope: Envelope<T>,
    pub shared_names: BTreeSet<ProjectId>,
}

pub const NOT_READ_SHORT: &str = "not read: ls without -l";

pub const NOT_READ_BUDGET: &str = "not read: budget";

pub fn list(
    source: &dyn SessionSource,
    clock: &dyn Clock,
    request: &ListRequest,
) -> Result<Envelope<Inventory>, OpError> {
    list_report(source, clock, request).map(|r| r.envelope)
}

pub fn show(
    source: &dyn SessionSource,
    clock: &dyn Clock,
    request: &ShowRequest,
) -> Result<Envelope<SessionView>, OpError> {
    show_report(source, clock, request).map(|r| r.envelope)
}

const STATUS_CONFLICT: &str = "session list returned conflicting status facts for this session id";

pub fn list_report(
    source: &dyn SessionSource,
    clock: &dyn Clock,
    request: &ListRequest,
) -> Result<Report<Inventory>, OpError> {
    if request.limit > MAX_LIMIT {
        return Err(OpError::InvalidRequest(format!(
            "--limit {} is above the cap of {MAX_LIMIT}",
            request.limit
        )));
    }
    let run = Run::start(source, clock, request.budget);
    let version = run.read_version();
    let scope = SessionScope {
        include_hidden: request.include_hidden,
        include_archived: request.include_archived,
    };
    let rows = source
        .list_sessions(scope, run.deadline)
        .map_err(|e| OpError::ListFailed(cap_error(e)))?;

    let mut gaps = Vec::new();
    let listed = rows.records.len() + rows.unreadable.len();
    let mut unreadable = rows.unreadable.len();
    gaps.extend(rows.unreadable);
    let mut seen: BTreeMap<SessionId, usize> = BTreeMap::new();
    let mut conflicted = BTreeSet::new();
    let mut kept: Vec<SessionRecord> = Vec::new();
    for record in rows.records {
        if record.id.0.is_empty() || record.id.0.chars().count() > FIELD_MAX_CHARS {
            unreadable += 1;
            gaps.push(gap(
                GapKind::Malformed,
                None,
                format!(
                    "{} returned a session id that is empty or longer than {FIELD_MAX_CHARS} characters",
                    source.read_name(Read::Sessions)
                ),
            ));
        } else if let Some(&index) = seen.get(&record.id) {
            if kept[index].status != record.status {
                kept[index].status = Fact::Unknown(STATUS_CONFLICT.to_owned());
                conflicted.insert(record.id.0.clone());
            }
            unreadable += 1;
            gaps.push(gap(
                GapKind::Malformed,
                Some(record.id.0.clone()),
                format!(
                    "{} returned this session id more than once; it is shown once",
                    source.read_name(Read::Sessions)
                ),
            ));
        } else {
            gaps.extend(record.problems.iter().cloned());
            seen.insert(record.id.clone(), kept.len());
            kept.push(record);
        }
    }
    for id in conflicted {
        gaps.push(gap(
            GapKind::Malformed,
            Some(id),
            STATUS_CONFLICT.to_owned(),
        ));
    }

    let (mut excluded_hidden, mut excluded_archived) = (0, 0);
    let mut matched = Vec::new();
    for record in kept {
        if record.hidden == Fact::Known(true) && !request.include_hidden {
            excluded_hidden += 1;
        } else if record.archived == Fact::Known(true) && !request.include_archived {
            excluded_archived += 1;
        } else {
            matched.push(record);
        }
    }
    matched.sort_unstable_by(sort_key);
    let matched_count = matched.len();
    let page: Vec<SessionRecord> = matched
        .into_iter()
        .skip(request.offset)
        .take(request.limit)
        .collect();

    let projects = run.projects(request.include_hidden, &mut gaps);
    let machines = run.machines(&mut gaps);

    let configurations: Vec<(ReportedConfiguration, Option<Timestamp>)> = match request.detail {
        Detail::Short => page
            .iter()
            .map(|_| (not_read(NOT_READ_SHORT.to_owned()), None))
            .collect(),
        Detail::Long => {
            let ids: Vec<SessionId> = page.iter().map(|r| r.id.clone()).collect();
            run.details(&ids)
                .into_iter()
                .zip(&ids)
                .map(|(outcome, id)| run.configuration(id, outcome, &mut gaps))
                .collect()
        }
    };
    let sessions: Vec<Session> = page
        .iter()
        .zip(configurations)
        .map(
            |(record, (configuration, detail_start))| match (&record.started_at, detail_start) {
                (Fact::Unknown(_), Some(at)) => build_session(
                    &SessionRecord {
                        started_at: Fact::Known(at),
                        ..record.clone()
                    },
                    configuration,
                    &projects,
                    &machines,
                    run.snapshot,
                ),
                _ => build_session(record, configuration, &projects, &machines, run.snapshot),
            },
        )
        .collect();
    let shared_names = shared_names(&projects, sessions.iter().map(|s| &s.group));
    let counts = Counts {
        listed: listed as u64,
        unreadable: unreadable as u64,
        excluded_hidden,
        excluded_archived,
        hidden_read: request.include_hidden,
        archived_read: request.include_archived,
        matched: matched_count as u64,
        offset: request.offset as u64,
        limit: request.limit as u64,
        shown: sessions.len() as u64,
    };
    Ok(Report {
        envelope: run.envelope(version, Some(counts), gaps, Inventory { sessions }),
        shared_names,
    })
}

pub fn show_report(
    source: &dyn SessionSource,
    clock: &dyn Clock,
    request: &ShowRequest,
) -> Result<Report<SessionView>, OpError> {
    let run = Run::start(source, clock, request.budget);
    let version = run.read_version();
    let detail = source
        .session_detail(&request.id, run.deadline)
        .map_err(|e| match e {
            SourceError::NotFound { .. } => OpError::NotFound(request.id.clone()),
            SourceError::InvalidId { id, detail } => OpError::InvalidRequest(cap_field(&format!(
                "{id} cannot be passed to {}: {detail}",
                source.name()
            ))),
            other => OpError::ShowFailed(cap_error(other)),
        })?;
    let mut gaps: Vec<Gap> = detail.session.problems.clone();
    let projects = run.projects(false, &mut gaps);
    let machines = run.machines(&mut gaps);
    let (final_output, reported_error) = run.output(&detail.session.id, &mut gaps);
    let configuration = ReportedConfiguration {
        model: cap_fact(&detail.model),
        effort: cap_fact(&detail.effort),
    };
    let session = build_session(
        &detail.session,
        configuration,
        &projects,
        &machines,
        run.snapshot,
    );
    let shared_names = shared_names(&projects, [&session.group]);
    let view = SessionView {
        session,
        final_output,
        reported_error,
    };
    Ok(Report {
        envelope: run.envelope(version, None, gaps, view),
        shared_names,
    })
}

fn sort_key(a: &SessionRecord, b: &SessionRecord) -> Ordering {
    let by_time = match (&a.updated_at, &b.updated_at) {
        (Fact::Known(x), Fact::Known(y)) => y.cmp(x),
        (Fact::Known(_), Fact::Unknown(_)) => Ordering::Less,
        (Fact::Unknown(_), Fact::Known(_)) => Ordering::Greater,
        (Fact::Unknown(_), Fact::Unknown(_)) => Ordering::Equal,
    };
    by_time.then_with(|| a.id.cmp(&b.id))
}

type Listed<T> = Result<T, String>;

struct Run<'a> {
    source: &'a dyn SessionSource,
    clock: &'a dyn Clock,
    deadline: Instant,
    snapshot: Timestamp,
}

enum Outcome {
    Read(Box<SessionDetailRecord>),
    Failed(SourceError),
    NotRead,
}

impl<'a> Run<'a> {
    fn start(source: &'a dyn SessionSource, clock: &'a dyn Clock, budget: Duration) -> Self {
        let deadline = clock.monotonic() + budget;
        Self {
            source,
            clock,
            deadline,
            snapshot: clock.now(),
        }
    }

    fn out_of_budget(&self) -> bool {
        self.clock.monotonic() >= self.deadline
    }

    fn name(&self, read: Read) -> &str {
        self.source.read_name(read)
    }

    fn describe(&self, read: Read, error: &SourceError) -> String {
        format!("{} {error}", self.name(read))
    }

    fn read_version(&self) -> VersionRead {
        let (version, tested) = version_fact(
            self.name(Read::Version),
            self.source.tested_version(),
            self.source.version(self.deadline),
        );
        let gap = match &version {
            Fact::Unknown(why) => Some(gap(GapKind::UntestedVersion, None, why.clone())),
            Fact::Known(_) => None,
        };
        VersionRead {
            version,
            tested,
            gap,
        }
    }

    fn projects(
        &self,
        include_hidden: bool,
        gaps: &mut Vec<Gap>,
    ) -> Listed<BTreeMap<ProjectId, Fact<String>>> {
        let rows = self.list(Read::Projects, gaps, |deadline| {
            self.source.list_projects(include_hidden, deadline)
        })?;
        let mut names = BTreeMap::new();
        let mut conflicted: BTreeSet<ProjectId> = BTreeSet::new();
        for ProjectRecord { id, name } in rows {
            if id.0.chars().count() > FIELD_MAX_CHARS {
                gaps.push(gap(
                    GapKind::Malformed,
                    Some(self.name(Read::Projects).to_owned()),
                    format!("a project id is longer than {FIELD_MAX_CHARS} characters"),
                ));
            } else {
                names
                    .entry(id.clone())
                    .and_modify(|previous| {
                        if *previous != name {
                            let why =
                                "project list returned conflicting name facts for this project id";
                            *previous = Fact::Unknown(why.to_owned());
                            conflicted.insert(id.clone());
                        }
                    })
                    .or_insert(name);
            }
        }
        for id in &conflicted {
            gaps.push(gap(
                GapKind::Malformed,
                Some(id.0.clone()),
                "project list returned conflicting name facts for this project id".to_owned(),
            ));
        }
        Ok(names
            .into_iter()
            .map(|(id, name)| (id, cap_fact(&name)))
            .collect())
    }

    fn machines(&self, gaps: &mut Vec<Gap>) -> Listed<BTreeMap<String, Fact<String>>> {
        let rows = self.list(Read::Machines, gaps, |deadline| {
            self.source.list_machines(deadline)
        })?;
        let mut names = BTreeMap::new();
        for MachineRecord { id, name } in rows {
            names
                .entry(id.clone())
                .and_modify(|previous| {
                    if *previous != name {
                        let why =
                            "machine list returned conflicting name facts for this machine id";
                        *previous = Fact::Unknown(why.to_owned());
                        gaps.push(gap(GapKind::Malformed, Some(id.clone()), why.to_owned()));
                    }
                })
                .or_insert(name);
        }
        Ok(names
            .into_iter()
            .map(|(id, name)| (id, cap_fact(&name)))
            .collect())
    }

    fn list<T>(
        &self,
        read: Read,
        gaps: &mut Vec<Gap>,
        call: impl FnOnce(Instant) -> Result<Rows<T>, SourceError>,
    ) -> Listed<Vec<T>> {
        let subject = Some(self.name(read).to_owned());
        if self.out_of_budget() {
            gaps.push(gap(
                GapKind::BudgetExhausted,
                subject,
                NOT_READ_BUDGET.to_owned(),
            ));
            return Err(format!("{} {NOT_READ_BUDGET}", self.name(read)));
        }
        match call(self.deadline) {
            Ok(rows) => {
                gaps.extend(rows.unreadable);
                Ok(rows.records)
            }
            Err(e) => {
                let why = self.describe(read, &e);
                gaps.push(gap(kind_of(&e), subject, why.clone()));
                Err(why)
            }
        }
    }

    fn details(&self, ids: &[SessionId]) -> Vec<Outcome> {
        let next = AtomicUsize::new(0);
        let results: Vec<Mutex<Option<Outcome>>> = ids.iter().map(|_| Mutex::new(None)).collect();
        thread::scope(|scope| {
            for _ in 0..MAX_CONCURRENT_DETAIL_READS.min(ids.len()) {
                scope.spawn(|| {
                    loop {
                        let i = next.fetch_add(1, atomic::Ordering::SeqCst);
                        let Some(id) = ids.get(i) else { break };
                        let outcome = if self.out_of_budget() {
                            Outcome::NotRead
                        } else {
                            match self.source.session_detail(id, self.deadline) {
                                Ok(detail) => Outcome::Read(Box::new(detail)),
                                Err(e) => Outcome::Failed(e),
                            }
                        };
                        *results[i].lock().unwrap_or_else(|p| p.into_inner()) = Some(outcome);
                    }
                });
            }
        });
        results
            .into_iter()
            .map(|r| {
                r.into_inner()
                    .unwrap_or_else(|p| p.into_inner())
                    .unwrap_or(Outcome::NotRead)
            })
            .collect()
    }

    fn configuration(
        &self,
        id: &SessionId,
        outcome: Outcome,
        gaps: &mut Vec<Gap>,
    ) -> (ReportedConfiguration, Option<Timestamp>) {
        match outcome {
            Outcome::Read(detail) => {
                let detail = *detail;
                gaps.extend(detail.session.problems);
                let started = match detail.session.started_at {
                    Fact::Known(at) => Some(at),
                    Fact::Unknown(_) => None,
                };
                (
                    ReportedConfiguration {
                        model: cap_fact(&detail.model),
                        effort: cap_fact(&detail.effort),
                    },
                    started,
                )
            }
            Outcome::Failed(e) => {
                let why = self.describe(Read::SessionDetail, &e);
                gaps.push(gap(kind_of(&e), Some(id.0.clone()), why.clone()));
                (not_read(cap_field(&why)), None)
            }
            Outcome::NotRead => {
                gaps.push(gap(
                    GapKind::BudgetExhausted,
                    Some(id.0.clone()),
                    NOT_READ_BUDGET.to_owned(),
                ));
                (not_read(NOT_READ_BUDGET.to_owned()), None)
            }
        }
    }

    fn output(
        &self,
        id: &SessionId,
        gaps: &mut Vec<Gap>,
    ) -> (Fact<FinalOutput>, Fact<Option<BoundedText>>) {
        let unknown = |why: String| (Fact::Unknown(why.clone()), Fact::Unknown(why));
        if self.out_of_budget() {
            gaps.push(gap(
                GapKind::BudgetExhausted,
                Some(id.0.clone()),
                format!("{} {NOT_READ_BUDGET}", self.name(Read::SessionOutput)),
            ));
            return unknown(NOT_READ_BUDGET.to_owned());
        }
        match self.source.session_output(id, self.deadline) {
            Ok(record) => {
                gaps.extend(record.problems);
                let output = match record.output {
                    Fact::Known(Some(text)) if !text.is_empty() => Fact::Known(
                        FinalOutput::Reported(BoundedText::bytes(&text, FINAL_OUTPUT_MAX_BYTES)),
                    ),
                    Fact::Known(_) => Fact::Known(FinalOutput::NoFinalOutputYet),
                    Fact::Unknown(why) => Fact::Unknown(cap_field(&why)),
                };
                let error = match record.error {
                    Fact::Known(error) => {
                        Fact::Known(error.map(|text| BoundedText::chars(&text, FIELD_MAX_CHARS)))
                    }
                    Fact::Unknown(why) => Fact::Unknown(cap_field(&why)),
                };
                (output, error)
            }
            Err(e) => {
                let why = self.describe(Read::SessionOutput, &e);
                gaps.push(gap(kind_of(&e), Some(id.0.clone()), why.clone()));
                unknown(cap_field(&why))
            }
        }
    }

    fn envelope<T>(
        &self,
        version: VersionRead,
        counts: Option<Counts>,
        gaps: Vec<Gap>,
        data: T,
    ) -> Envelope<T> {
        let mut gaps = gaps;
        gaps.extend(version.gap);
        let gaps = merge_gaps(gaps);
        let state = if gaps.is_empty() {
            Completeness::Complete
        } else {
            Completeness::Partial
        };
        Envelope {
            schema: SCHEMA_ID.to_owned(),
            source: SourceInfo {
                name: self.source.name().to_owned(),
                version: version.version,
                tested_version: self.source.tested_version().to_owned(),
                version_tested: version.tested,
            },
            coverage: Coverage { state, counts },
            freshness: Freshness {
                snapshot_at: self.snapshot,
            },
            gaps,
            data,
        }
    }
}

fn build_session(
    record: &SessionRecord,
    reported_configuration: ReportedConfiguration,
    projects: &Listed<BTreeMap<ProjectId, Fact<String>>>,
    machines: &Listed<BTreeMap<String, Fact<String>>>,
    snapshot: Timestamp,
) -> Session {
    let group = match (&record.project_id, projects) {
        (Fact::Known(id), Ok(names)) => match names.get(id) {
            Some(name) => Grouping::Project {
                id: id.clone(),
                name: name.clone(),
            },
            None => Grouping::Ungrouped {
                reason: cap_field(&format!(
                    "project {} is not in the project list read in this run",
                    id.0
                )),
            },
        },
        (Fact::Known(id), Err(why)) => Grouping::Ungrouped {
            reason: cap_field(&format!("project {} cannot be verified: {why}", id.0)),
        },
        (Fact::Unknown(why), _) => Grouping::Ungrouped {
            reason: cap_field(&format!("project unknown ({why})")),
        },
    };
    let location = match &record.placement {
        Fact::Known(Placement::Cloud) => Fact::Known(Location::Cloud),
        Fact::Known(Placement::Host(host)) => {
            let machine = match machines {
                Ok(names) => names.get(host).cloned().unwrap_or_else(|| {
                    Fact::Unknown(cap_field(&format!(
                        "host {host} is not in the machine list read in this run"
                    )))
                }),
                Err(why) => {
                    Fact::Unknown(cap_field(&format!("host {host} cannot be matched: {why}")))
                }
            };
            Fact::Known(Location::Local { machine })
        }
        Fact::Unknown(why) => Fact::Unknown(cap_field(why)),
    };
    let recap = match &record.purpose_text {
        Fact::Known(Some(text)) if !text.trim().is_empty() => Fact::Known(
            Recap::PurposeAsReported(BoundedText::chars(text, PURPOSE_MAX_CHARS)),
        ),
        Fact::Known(_) => Fact::Known(Recap::NoRecapYet),
        Fact::Unknown(why) => Fact::Unknown(cap_field(why)),
    };
    let parent = match &record.parent {
        Fact::Known(parent) => Fact::Known(parent.as_ref().map(|id| SessionId(cap_field(&id.0)))),
        Fact::Unknown(why) => Fact::Unknown(cap_field(why)),
    };
    let updated_at = match &record.updated_at {
        Fact::Known(at) => Fact::Known(*at),
        Fact::Unknown(why) => Fact::Unknown(cap_field(why)),
    };
    let age_ms = match &updated_at {
        Fact::Known(at) => match snapshot.0.checked_sub(at.0) {
            Some(age) => Fact::Known(age),
            None => Fact::Unknown(format!(
                "the update time {} is too far from the snapshot to give an age",
                at.0
            )),
        },
        Fact::Unknown(why) => Fact::Unknown(why.clone()),
    };
    let started_at = match &record.started_at {
        Fact::Known(at) if at.0 <= snapshot.0 => Fact::Known(*at),
        Fact::Known(at) => Fact::Unknown(format!(
            "the reported start time {} is after the snapshot",
            at.0
        )),
        Fact::Unknown(why) => Fact::Unknown(cap_field(why)),
    };
    Session {
        id: record.id.clone(),
        title: cap_fact(&record.title),
        provider: cap_fact(&record.provider),
        status: cap_fact(&record.status),
        location,
        group,
        parent,
        hidden: cap_reason(&record.hidden),
        archived: cap_reason(&record.archived),
        recap,
        reported_configuration,
        updated_at,
        age_ms,
        started_at,
    }
}

fn shared_names<'g>(
    projects: &Listed<BTreeMap<ProjectId, Fact<String>>>,
    groups: impl IntoIterator<Item = &'g Grouping>,
) -> BTreeSet<ProjectId> {
    let Ok(names) = projects else {
        return BTreeSet::new();
    };
    groups
        .into_iter()
        .filter_map(|group| match group {
            Grouping::Project { id, name } => {
                let sharing = names.values().filter(|other| *other == name).count();
                (sharing > 1).then(|| id.clone())
            }
            Grouping::Ungrouped { .. } => None,
        })
        .collect()
}

fn not_read(why: String) -> ReportedConfiguration {
    ReportedConfiguration {
        model: Fact::Unknown(why.clone()),
        effort: Fact::Unknown(why),
    }
}

fn gap(kind: GapKind, subject: Option<String>, detail: String) -> Gap {
    Gap {
        kind,
        subject,
        detail,
    }
}

fn kind_of(error: &SourceError) -> GapKind {
    match error {
        SourceError::NotFound { .. } => GapKind::NotFound,
        SourceError::InvalidId { .. } | SourceError::Malformed { .. } => GapKind::Malformed,
        SourceError::CommandFailed { .. } | SourceError::Unavailable { .. } => {
            GapKind::CommandFailed
        }
        SourceError::TimedOut { .. } => GapKind::TimedOut,
    }
}

fn merge_gaps(gaps: Vec<Gap>) -> Vec<Gap> {
    let mut merged: Vec<(GapKind, String, Vec<String>)> = Vec::new();
    let mut index: HashMap<(GapKind, String), (usize, HashSet<String>)> = HashMap::new();
    for Gap {
        kind,
        subject,
        detail,
    } in gaps
    {
        let (i, seen) = index.entry((kind, detail.clone())).or_insert_with(|| {
            merged.push((kind, detail, Vec::new()));
            (merged.len() - 1, HashSet::new())
        });
        if let Some(subject) = subject.filter(|s| seen.insert(s.clone())) {
            merged[*i].2.push(subject);
        }
    }
    merged
        .into_iter()
        .map(|(kind, detail, subjects)| Gap {
            kind,
            subject: match subjects.len() {
                0 => None,
                1 => Some(cap_field(&subjects[0])),
                n => Some(cap_field(&format!("{n} subjects: {}", subjects.join(", ")))),
            },
            detail: cap_field(&detail),
        })
        .collect()
}

fn cap_fact(fact: &Fact<String>) -> Fact<String> {
    match fact {
        Fact::Known(text) => Fact::Known(cap_field(text)),
        Fact::Unknown(why) => Fact::Unknown(cap_field(why)),
    }
}

fn cap_reason<T: Clone>(fact: &Fact<T>) -> Fact<T> {
    match fact {
        Fact::Known(value) => Fact::Known(value.clone()),
        Fact::Unknown(why) => Fact::Unknown(cap_field(why)),
    }
}

fn cap_error(error: SourceError) -> SourceError {
    match error {
        SourceError::NotFound { subject } => SourceError::NotFound {
            subject: cap_field(&subject),
        },
        SourceError::InvalidId { id, detail } => SourceError::InvalidId {
            id: cap_field(&id),
            detail: cap_field(&detail),
        },
        SourceError::CommandFailed { exit_code, detail } => SourceError::CommandFailed {
            exit_code,
            detail: cap_field(&detail),
        },
        SourceError::TimedOut { after_ms } => SourceError::TimedOut { after_ms },
        SourceError::Malformed { detail } => SourceError::Malformed {
            detail: cap_field(&detail),
        },
        SourceError::Unavailable { detail } => SourceError::Unavailable {
            detail: cap_field(&detail),
        },
    }
}
