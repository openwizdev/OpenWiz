//! `GET /api/v1/cockpit` (#535, 0.0.10 T2): the cockpit's one read,
//! `openwiz.cockpit.v1` (`contracts/cockpit.v1.md`), assembled from reads
//! the server already makes, never a new one:
//!
//! - the inventory (`ls`'s core operation) and its project list: the project
//!   universe and the running agents, with each running agent's detail read
//!   (`ls -l`'s) for its reported model and start time;
//! - the configured fleet source (`openwiz fleets`'s core operation), its
//!   repository and its CloudRoom projects, threads and Cloud branches (the
//!   reads `openwiz fleet <spec>` makes): Needs you, and each agent's place
//!   through the core's verified chain;
//! - #129's configured orchestrator target, checked through the existing
//!   bounded target read (`thread show`).
//!
//! A failed or missing read is a gap and an unknown, never an empty claim;
//! every detail and reason is OpenWiz's own words, never a tool's output.
//! The read sends, stages, starts, approves, labels and merges nothing.

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Mutex;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::thread;
use std::time::Instant;

use openwiz_core::envelope::GapKind;
use openwiz_core::fleet::agents;
use openwiz_core::fleet::fleets::{
    QUESTION_NOT_READ, fleets as read_fleets, needs_you_item, needs_you_kinds,
};
use openwiz_core::fleet::model::{
    Envelope as FleetEnvelope, ListOutcome as Listing, NeedsYou, NeedsYouKind, Number,
    Outcome as Single, Read, ReadId, ReadKind, State, Thread, UnplacedReason, View, WorkedOut,
};
use openwiz_core::fleet::tickets::AgentReads;
use openwiz_core::limits::{FIELD_MAX_CHARS, MAX_CONCURRENT_DETAIL_READS, MAX_LIMIT, RUN_BUDGET};
use openwiz_core::messaging::send::Messenger;
use openwiz_core::model::{Fact, Grouping, Inventory, Location, Session, SessionId};
use openwiz_core::ops::{self, Clock, Detail, ListRequest, Report};
use openwiz_core::source::{
    MachineRecord, OutputRecord, ProjectRecord, Read as SourceRead, Rows, SessionDetailRecord,
    SessionRecord, SessionScope, SessionSource, SourceError,
};
use serde_json::{Value, json};

use crate::api;
use crate::fleets::Fleets;
use crate::http::Reply;

pub(crate) const ROUTE: &str = "/api/v1/cockpit";

/// The fleet page's existing stale threshold (`FLEET_TIMING.staleAfterMs`,
/// `apps/web/src/timing.ts`): the contract adds no interval of its own.
const FRESH_FOR_MS: i64 = 70_000;

/// The server's configured target, as `openwiz-server` reads
/// `OPENWIZ_ORCHESTRATOR_THREAD_ID` at start (`Decisions::target`): `Ok(None)`
/// is unset, `Err` unreadable.
pub(crate) type Configured = Result<Option<String>, ()>;

/// The read: always a `200` envelope; source failures are gaps.
pub(crate) fn run(
    source: &dyn SessionSource,
    fleets: Option<&Fleets>,
    stock: Option<&dyn crate::ready_stock::StockSource>,
    stock_history: &crate::ready_stock::History,
    configured: Option<&Configured>,
    messenger: Option<&dyn Messenger>,
    clock: &dyn Clock,
) -> Reply {
    // Without a server-supplied configuration, the target is the one #129's
    // fleet routes read from the environment at request time.
    let from_env;
    let configured = match configured {
        Some(configured) => configured,
        None => {
            from_env = match std::env::var("OPENWIZ_ORCHESTRATOR_THREAD_ID") {
                Ok(id) => Ok(Some(id)),
                Err(std::env::VarError::NotPresent) => Ok(None),
                Err(std::env::VarError::NotUnicode(_)) => Err(()),
            };
            &from_env
        }
    };
    let deadline = clock.monotonic() + RUN_BUDGET;
    let stock_reads = fleets.map(|f| crate::fleets::StockReads::new(f.list.as_ref(), clock));
    let (inventory, github, mapping) = thread::scope(|scope| {
        let github = stock_reads.as_ref().map(|reader| {
            scope.spawn(move || {
                let budget = deadline.saturating_duration_since(clock.monotonic());
                read_fleets(reader, clock, budget)
            })
        });
        let mapping =
            fleets.map(|f| scope.spawn(|| map(f, configured, messenger, clock, deadline)));
        let inventory = read_inventory(source, clock, deadline);
        (inventory, github.map(join), mapping.map(join))
    });
    let now = clock.now().0;
    let mut body = assemble(&inventory, github.as_ref(), mapping.as_ref(), now);
    let scoped = mapping
        .as_ref()
        .and_then(|m| m.reads.as_ref())
        .and_then(|r| match &r.projects {
            Listing::Complete { value } if value.len() == 1 => Some(value[0].id.as_str()),
            _ => None,
        });
    // Stock enumeration depends on both actual project-list sources, without
    // inheriting unrelated orchestrator/target or fleet-content limitations.
    let mut stock_projects = body["projects"].clone();
    let mut project_times = vec![
        inventory
            .projects
            .as_ref()
            .ok()
            .map(|_| inventory.projects_at),
    ];
    let mapping_complete = match mapping.as_ref() {
        None => true,
        Some(m) => {
            let listed = m.reads.as_ref().map(|r| &r.projects);
            project_times.push(match listed {
                Some(Listing::Complete { .. } | Listing::Partial { .. })
                    if m.repository.is_ok() =>
                {
                    Some(m.at)
                }
                _ => None,
            });
            m.repository.is_ok() && matches!(listed, Some(Listing::Complete { .. }))
        }
    };
    stock_projects["coverage"]["state"] = json!(if inventory.projects.is_ok()
        && inventory.project_gaps.is_empty()
        && mapping_complete
    {
        "complete"
    } else {
        "partial"
    });
    let installed =
        fleets
            .zip(stock_reads.as_ref())
            .map(|(f, reads)| crate::ready_stock::Installed {
                reads,
                github: f.detail.as_ref(),
                project: scoped,
                repository: mapping.as_ref().and_then(|m| m.stock_repository.as_deref()),
                clock,
            });
    let stock = stock.or_else(|| {
        installed
            .as_ref()
            .map(|s| s as &dyn crate::ready_stock::StockSource)
    });
    let stock_read = crate::ready_stock::read(&stock_projects, stock, deadline);
    // All source reads have now finished. Reassemble age-sensitive cockpit
    // metadata at this same final clock value as the stock projection.
    let now = clock.now().0;
    body = assemble(&inventory, github.as_ref(), mapping.as_ref(), now);
    stock_projects["freshness"] = freshness(&project_times, now);
    let stock_now = u64::try_from(now).unwrap_or(0);
    let retained = stock_history.retained_projects(&stock_projects, stock_now);
    // A retained identity supplies navigation/display context only. It cannot
    // carry a current count or an old answer target through failed discovery.
    for (id, name) in retained {
        let reason = crate::ready_stock::MISSING_PROJECT;
        let gap = json!({"project":id,"kind":"missing_field","detail":reason});
        let project = json!({"id":id,"name":name,"orchestrator":{
            "coverage":{"state":"partial","gaps":[gap.clone()]},
            "freshness":{"state":"unknown","snapshot_at":unknown(reason)},
            "target":unknown(reason),
        }});
        body["projects"]["items"]
            .as_array_mut()
            .unwrap()
            .push(project.clone());
        stock_projects["items"]
            .as_array_mut()
            .unwrap()
            .push(project);
        for part in ["projects", "needs_you", "agents"] {
            body[part]["coverage"]["state"] = json!("partial");
            body[part]["coverage"]["gaps"]
                .as_array_mut()
                .unwrap()
                .push(gap.clone());
        }
        stock_projects["coverage"]["state"] = json!("partial");
    }
    for part in [&mut body["projects"], &mut stock_projects] {
        part["items"]
            .as_array_mut()
            .unwrap()
            .sort_by(|a, b| a["id"].as_str().cmp(&b["id"].as_str()));
    }
    if let Some(read) = stock_read
        && let Some(stock) =
            crate::ready_stock::assemble(&stock_projects, read, stock_now, stock_history)
    {
        body["ready_stock"] = serde_json::to_value(stock).expect("stock serializes");
    }
    api::pretty(&body).map_or_else(
        || api::error(500, "internal", "the result could not be written"),
        api::ok,
    )
}

/// A read's result; a panic stays a panic (the run's `500`).
fn join<T>(handle: thread::ScopedJoinHandle<'_, T>) -> T {
    handle
        .join()
        .unwrap_or_else(|panic| std::panic::resume_unwind(panic))
}

// ---------------------------------------------------------------------
// The reads.

struct InventoryRead {
    /// The inventory's own project list, and when it was read.
    projects: Result<Vec<ProjectRecord>, &'static str>,
    project_gaps: Vec<GapKind>,
    projects_at: i64,
    /// `ls`, or the kind of its failure.
    list: Result<Listed, &'static str>,
    /// Each running session's detail read.
    details: BTreeMap<SessionId, Result<SessionDetailRecord, &'static str>>,
}

fn read_inventory(
    source: &dyn SessionSource,
    clock: &dyn Clock,
    deadline: Instant,
) -> InventoryRead {
    let projects_at = clock.now().0;
    let (projects, project_gaps) = match source.list_projects(false, deadline) {
        Ok(rows) => (
            Ok(rows.records),
            rows.unreadable.into_iter().map(|g| g.kind).collect(),
        ),
        Err(e) => (Err(source_kind(&e)), Vec::new()),
    };
    let list = list_all(source, clock, deadline);
    let running: Vec<SessionId> = match &list {
        Ok(listed) => listed
            .sessions
            .iter()
            .filter(|s| active(s))
            .map(|s| s.id.clone())
            .collect(),
        Err(_) => Vec::new(),
    };
    InventoryRead {
        projects,
        project_gaps,
        projects_at,
        list,
        details: details(source, &running, deadline),
    }
}

/// Every session of the inventory, hidden and archived included, read
/// page by page through `ls`'s core operation within the run's deadline.
struct Listed {
    sessions: Vec<Session>,
    /// The inventory's own gaps, by kind.
    gaps: Vec<GapKind>,
    /// The oldest page's snapshot.
    snapshot: i64,
    /// Not every page was read, or the list changed between pages.
    truncated: bool,
}

/// The run's one enumeration: each list read is made once and every page
/// reuses it, so pages can't repeat or skip a session that moved between
/// independent reads. Detail and output reads pass through.
struct OneRead<'a> {
    inner: &'a dyn SessionSource,
    version: Mutex<Option<Result<String, SourceError>>>,
    sessions: Mutex<Option<Result<Rows<SessionRecord>, SourceError>>>,
    projects: Mutex<Option<Result<Rows<ProjectRecord>, SourceError>>>,
    machines: Mutex<Option<Result<Rows<MachineRecord>, SourceError>>>,
}

fn once<T: Clone>(
    slot: &Mutex<Option<Result<T, SourceError>>>,
    read: impl FnOnce() -> Result<T, SourceError>,
) -> Result<T, SourceError> {
    lock(slot).get_or_insert_with(read).clone()
}

impl SessionSource for OneRead<'_> {
    fn name(&self) -> &str {
        self.inner.name()
    }
    fn tested_version(&self) -> &str {
        self.inner.tested_version()
    }
    fn read_name(&self, read: SourceRead) -> &str {
        self.inner.read_name(read)
    }
    fn version(&self, deadline: Instant) -> Result<String, SourceError> {
        once(&self.version, || self.inner.version(deadline))
    }
    fn list_sessions(
        &self,
        scope: SessionScope,
        deadline: Instant,
    ) -> Result<Rows<SessionRecord>, SourceError> {
        once(&self.sessions, || self.inner.list_sessions(scope, deadline))
    }
    fn list_projects(
        &self,
        include_hidden: bool,
        deadline: Instant,
    ) -> Result<Rows<ProjectRecord>, SourceError> {
        once(&self.projects, || {
            self.inner.list_projects(include_hidden, deadline)
        })
    }
    fn list_machines(&self, deadline: Instant) -> Result<Rows<MachineRecord>, SourceError> {
        once(&self.machines, || self.inner.list_machines(deadline))
    }
    fn session_detail(
        &self,
        id: &SessionId,
        deadline: Instant,
    ) -> Result<SessionDetailRecord, SourceError> {
        self.inner.session_detail(id, deadline)
    }
    fn session_output(
        &self,
        id: &SessionId,
        deadline: Instant,
    ) -> Result<OutputRecord, SourceError> {
        self.inner.session_output(id, deadline)
    }
}

fn list_all(
    source: &dyn SessionSource,
    clock: &dyn Clock,
    deadline: Instant,
) -> Result<Listed, &'static str> {
    // Every page reads the same enumeration, with the same scope and
    // project flag on every page.
    let one = OneRead {
        inner: source,
        version: Mutex::new(None),
        sessions: Mutex::new(None),
        projects: Mutex::new(None),
        machines: Mutex::new(None),
    };
    let source: &dyn SessionSource = &one;
    let mut listed: Option<Listed> = None;
    let mut seen = BTreeSet::new();
    let (mut offset, mut first_matched) = (0usize, None);
    loop {
        // The run's one deadline: never a new budget per page.
        let request = ListRequest {
            detail: Detail::Short,
            include_hidden: true,
            include_archived: true,
            limit: MAX_LIMIT,
            offset,
            budget: deadline.saturating_duration_since(clock.monotonic()),
        };
        let report: Report<Inventory> = match ops::list_report(source, clock, &request) {
            Ok(report) => report,
            Err(e) => {
                let kind = match e {
                    ops::OpError::ListFailed(e) | ops::OpError::ShowFailed(e) => source_kind(&e),
                    ops::OpError::NotFound(_) => "not_found",
                    ops::OpError::InvalidRequest(_) => "malformed",
                };
                return match listed {
                    None => Err(kind),
                    Some(mut listed) => {
                        listed.truncated = true;
                        Ok(listed)
                    }
                };
            }
        };
        let envelope = report.envelope;
        let (shown, matched) = envelope
            .coverage
            .counts
            .as_ref()
            .map_or((0, 0), |c| (c.shown, c.matched));
        let page = listed.get_or_insert(Listed {
            sessions: Vec::new(),
            gaps: Vec::new(),
            snapshot: envelope.freshness.snapshot_at.0,
            truncated: false,
        });
        page.snapshot = page.snapshot.min(envelope.freshness.snapshot_at.0);
        page.gaps.extend(envelope.gaps.iter().map(|g| g.kind));
        for session in envelope.data.sessions {
            if seen.insert(session.id.clone()) {
                page.sessions.push(session);
            }
        }
        if *first_matched.get_or_insert(matched) != matched {
            page.truncated = true;
        }
        offset += usize::try_from(shown).unwrap_or(usize::MAX);
        if shown == 0 || offset as u64 >= matched {
            break;
        }
        if Instant::now() >= deadline {
            page.truncated = true;
            break;
        }
    }
    // Belt and braces: every matched session must have been collected once.
    if let (Some(listed), Some(matched)) = (listed.as_mut(), first_matched)
        && listed.sessions.len() as u64 != matched
    {
        listed.truncated = true;
    }
    listed.ok_or("budget_exhausted")
}

fn active(session: &Session) -> bool {
    matches!(&session.status, Fact::Known(status) if status == "active")
}

/// `ls -l`'s detail reads, for the running sessions only, as many at once.
fn details(
    source: &dyn SessionSource,
    ids: &[SessionId],
    deadline: Instant,
) -> BTreeMap<SessionId, Result<SessionDetailRecord, &'static str>> {
    let next = AtomicUsize::new(0);
    let read = Mutex::new(BTreeMap::new());
    thread::scope(|scope| {
        for _ in 0..MAX_CONCURRENT_DETAIL_READS.min(ids.len()) {
            scope.spawn(|| {
                while let Some(id) = ids.get(next.fetch_add(1, Ordering::SeqCst)) {
                    let outcome = if Instant::now() >= deadline {
                        Err("budget_exhausted")
                    } else {
                        source
                            .session_detail(id, deadline)
                            .map_err(|e| source_kind(&e))
                    };
                    lock(&read).insert(id.clone(), outcome);
                }
            });
        }
    });
    read.into_inner().unwrap_or_else(|p| p.into_inner())
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|p| p.into_inner())
}

/// The fleet source's repository, its CloudRoom reads, then the target.
struct Mapping {
    /// When the repository and its CloudRoom reads were made.
    at: i64,
    /// The repository read's failure kind, if it failed.
    repository: Result<(), &'static str>,
    reads: Option<AgentReads>,
    stock_repository: Option<String>,
    target: Checked,
}

struct Checked {
    at: i64,
    target: Target,
}

enum Target {
    Known(String),
    /// The configuration was read and names no thread, or the thread is not
    /// found: no send target.
    Absent,
    Failed(&'static str, &'static str),
}

fn map(
    fleets: &Fleets,
    configured: &Configured,
    messenger: Option<&dyn Messenger>,
    clock: &dyn Clock,
    deadline: Instant,
) -> Mapping {
    let at = clock.now().0;
    let (repository, reads, stock_repository) = match fleets.detail.repository(deadline) {
        Ok(repository) => (
            Ok(()),
            Some(fleets.agents.read(Some(&repository), deadline)),
            Some(repository.name.as_str().to_owned()),
        ),
        Err(e) => (Err(source_kind(&e)), None, None),
    };
    let checked_at = clock.now().0;
    Mapping {
        at,
        repository,
        reads,
        stock_repository,
        target: Checked {
            at: checked_at,
            target: verify_target(configured, messenger, deadline),
        },
    }
}

/// #129's check: the exact configured id, read back through the existing
/// bounded target read. A failed check is never absence.
fn verify_target(
    configured: &Configured,
    messenger: Option<&dyn Messenger>,
    deadline: Instant,
) -> Target {
    let id = match configured {
        Err(()) => {
            return Target::Failed(
                "malformed",
                "the configured orchestrator target could not be read",
            );
        }
        Ok(None) => return Target::Absent,
        Ok(Some(id)) => SessionId(id.clone()),
    };
    let Some(messenger) = messenger else {
        return Target::Failed(
            "command_failed",
            "no reader is configured to verify the orchestrator target",
        );
    };
    if messenger.check_target_id(&id).is_err() {
        return Target::Failed(
            "malformed",
            "the configured orchestrator target is not a valid thread id",
        );
    }
    match messenger.read_target(&id, deadline) {
        Ok(record) if record.id == id => Target::Known(id.0),
        Ok(_) => Target::Failed(
            "malformed",
            "the orchestrator target check read another thread",
        ),
        Err(SourceError::NotFound { .. }) => Target::Absent,
        Err(e) => Target::Failed(
            source_kind(&e),
            "the configured orchestrator target could not be verified",
        ),
    }
}

// ---------------------------------------------------------------------
// The assembly.

/// Gaps of one part, each once, in the order found.
#[derive(Clone, Default)]
struct Gaps(Vec<(Option<String>, &'static str, String)>);

impl Gaps {
    fn add(&mut self, project: Option<&str>, kind: &'static str, detail: impl Into<String>) {
        let gap = (project.map(str::to_owned), kind, detail.into());
        if !self.0.contains(&gap) {
            self.0.push(gap);
        }
    }

    fn extend(&mut self, other: &Gaps) {
        for (project, kind, detail) in &other.0 {
            self.add(project.as_deref(), kind, detail.clone());
        }
    }

    fn coverage(&self) -> Value {
        let gaps: Vec<Value> = self
            .0
            .iter()
            .map(|(project, kind, detail)| {
                json!({"project": project, "kind": kind, "detail": detail})
            })
            .collect();
        json!({"state": if gaps.is_empty() { "complete" } else { "partial" }, "gaps": gaps})
    }
}

/// The oldest required snapshot's freshness at `now`; any unknown required
/// snapshot, or one after assembly, is unknown.
fn freshness(snapshots: &[Option<i64>], now: i64) -> Value {
    let unknown_ = |why: &str| json!({"state": "unknown", "snapshot_at": unknown(why)});
    if snapshots.iter().any(Option::is_none) {
        return unknown_("a required source snapshot is not known");
    }
    let Some(oldest) = snapshots.iter().flatten().copied().min() else {
        return unknown_("no source snapshot was read");
    };
    if snapshots.iter().flatten().any(|&at| at < 0 || at > now) {
        return unknown_("a source snapshot is not before assembly");
    }
    let state = if now - oldest <= FRESH_FOR_MS {
        "fresh"
    } else {
        "stale"
    };
    json!({"state": state, "snapshot_at": {"known": oldest}})
}

fn known(value: impl Into<Value>) -> Value {
    json!({ "known": value.into() })
}

fn unknown(reason: &str) -> Value {
    json!({ "unknown": reason })
}

/// A nonempty string within the field cap, or why not.
fn text(fact: &Fact<String>, missing: &str) -> Result<String, String> {
    match fact {
        Fact::Known(text) if !text.is_empty() && text.chars().count() <= FIELD_MAX_CHARS => {
            Ok(text.clone())
        }
        Fact::Known(text) if text.is_empty() => Err(format!("{missing}: reported empty")),
        Fact::Known(_) => Err(format!("{missing}: reported too long")),
        Fact::Unknown(_) => Err(missing.to_owned()),
    }
}

fn gap_kind(kind: GapKind) -> &'static str {
    match kind {
        GapKind::UntestedVersion => "untested_version",
        GapKind::CommandFailed => "command_failed",
        GapKind::TimedOut => "timed_out",
        GapKind::BudgetExhausted => "budget_exhausted",
        GapKind::Malformed => "malformed",
        GapKind::MissingField => "missing_field",
        GapKind::WrongType => "wrong_type",
        GapKind::NotFound => "not_found",
    }
}

fn source_kind(error: &SourceError) -> &'static str {
    match error {
        SourceError::NotFound { .. } => "not_found",
        SourceError::InvalidId { .. } | SourceError::Malformed { .. } => "malformed",
        SourceError::TimedOut { .. } => "timed_out",
        SourceError::CommandFailed { .. } | SourceError::Unavailable { .. } => "command_failed",
    }
}

/// A fleet read's name in a detail: its contract kind, in words.
fn read_name(read: &Read) -> String {
    serde_json::to_value(&read.kind)
        .ok()
        .and_then(|v| v["kind"].as_str().map(|k| k.replace('_', " ")))
        .unwrap_or_else(|| "fleet".to_owned())
}

/// Gaps for every incomplete read, named by `project`.
fn read_gaps(reads: &[Read], project: Option<&str>, gaps: &mut Gaps) {
    for read in reads {
        let name = read_name(read);
        match incomplete(&read.kind) {
            Some(Incomplete::Failed(kind)) => {
                gaps.add(
                    project,
                    gap_kind(kind),
                    format!("the fleet {name} read failed"),
                );
            }
            Some(Incomplete::Truncated) => {
                gaps.add(
                    project,
                    "truncated",
                    format!("the fleet {name} read was truncated"),
                );
            }
            None => {}
        }
    }
}

enum Incomplete {
    Failed(GapKind),
    Truncated,
}

fn incomplete(kind: &ReadKind) -> Option<Incomplete> {
    fn one<T>(outcome: &Single<T>) -> Option<Incomplete> {
        match outcome {
            Single::Complete { .. } => None,
            Single::Failed(failed) => Some(Incomplete::Failed(failed.gap)),
        }
    }
    fn list<T>(outcome: &Listing<T>) -> Option<Incomplete> {
        match outcome {
            Listing::Complete { .. } => None,
            Listing::Partial { .. } => Some(Incomplete::Truncated),
            Listing::Failed(failed) => Some(Incomplete::Failed(failed.gap)),
        }
    }
    match kind {
        ReadKind::Version { outcome, .. } | ReadKind::Workspace { outcome, .. } => one(outcome),
        ReadKind::Repository { outcome } => one(outcome),
        ReadKind::Issue { outcome, .. } => one(outcome),
        ReadKind::PrDiscovery { outcome, .. } => one(outcome),
        ReadKind::Comments { outcome, .. } => one(outcome),
        ReadKind::MergeReadback { outcome, .. } => one(outcome),
        ReadKind::SpecList { outcome }
        | ReadKind::SubIssues { outcome, .. }
        | ReadKind::BlockedBy { outcome, .. } => list(outcome),
        ReadKind::Checks { outcome, .. } => list(outcome),
        ReadKind::Projects { outcome } => list(outcome),
        ReadKind::Threads { outcome } => list(outcome),
    }
}

/// The CloudRoom reads as the fleet envelope records them, numbered after
/// `after`, so the core's chain can read them beside GitHub's.
fn room_reads(reads: &AgentReads, after: u32) -> Vec<Read> {
    let mut kinds = vec![
        ReadKind::Projects {
            outcome: reads.projects.clone(),
        },
        ReadKind::Threads {
            outcome: reads.threads.clone(),
        },
    ];
    kinds.extend(
        reads
            .workspaces
            .iter()
            .map(|(thread, outcome)| ReadKind::Workspace {
                thread: thread.clone(),
                outcome: outcome.clone(),
            }),
    );
    kinds
        .into_iter()
        .zip(after + 1..)
        .map(|(kind, id)| Read {
            id: ReadId(id),
            kind,
        })
        .collect()
}

/// What the fleet source says about the projects whose git remote is its
/// repository.
enum Sourced {
    /// No fleet source is configured.
    None,
    /// The repository or its projects couldn't be read.
    Unread(&'static str),
    /// The repository's projects, and whether the list is complete.
    Listed(Vec<(String, String)>, bool),
}

impl Sourced {
    fn covers(&self, project: &str) -> Option<bool> {
        match self {
            Self::Listed(projects, _) => Some(projects.iter().any(|(id, _)| id == project)),
            Self::None => Some(false),
            Self::Unread(_) => None,
        }
    }

    /// The one project the source belongs to, or why there is none.
    fn single(&self) -> Result<&str, &'static str> {
        match self {
            Self::None => Err("no fleet source is configured"),
            Self::Unread(_) => Err("the fleet source's projects could not be read"),
            Self::Listed(_, false) => Err("the fleet source's project list was truncated"),
            Self::Listed(projects, true) => match projects.as_slice() {
                [(id, _)] => Ok(id),
                [] => Err("no project's git remote is the fleet source's repository"),
                _ => Err("the fleet source's repository matches several projects"),
            },
        }
    }
}

const NO_SOURCE: &str = "no fleet source is configured for this project";

fn assemble(
    inventory: &InventoryRead,
    github: Option<&FleetEnvelope>,
    mapping: Option<&Mapping>,
    now: i64,
) -> Value {
    let sessions: &[Session] = match &inventory.list {
        Ok(listed) => &listed.sessions,
        Err(_) => &[],
    };

    // The fleet source's projects.
    let mut discovery = Gaps::default();
    let sourced = match mapping {
        None => Sourced::None,
        Some(Mapping {
            repository: Err(kind),
            ..
        }) => {
            discovery.add(
                None,
                kind,
                "the fleet source's repository could not be read",
            );
            Sourced::Unread(kind)
        }
        Some(Mapping { reads: None, .. }) => Sourced::Unread("command_failed"),
        Some(Mapping {
            reads: Some(reads), ..
        }) => {
            let listed = |rows: &[openwiz_core::fleet::model::Project]| {
                rows.iter()
                    .map(|p| (p.id.as_str().to_owned(), p.name.clone()))
                    .collect()
            };
            match &reads.projects {
                Listing::Complete { value } => Sourced::Listed(listed(value), true),
                Listing::Partial { value, .. } => {
                    discovery.add(
                        None,
                        "truncated",
                        "the fleet source's project list was truncated",
                    );
                    Sourced::Listed(listed(value), false)
                }
                Listing::Failed(failed) => {
                    let kind = gap_kind(failed.gap);
                    discovery.add(
                        None,
                        kind,
                        "the fleet source's project list could not be read",
                    );
                    Sourced::Unread(kind)
                }
            }
        }
    };

    // The project universe: the inventory's project list, the fleet
    // source's projects and every verified session group.
    // Each project's names, from the first of three sources that names it:
    // the inventory's project list, its verified session groups, the fleet
    // source's project list. Two names in one source are a conflict.
    let mut tiers: [BTreeMap<String, BTreeSet<String>>; 3] = Default::default();
    let mut name = |tier: usize, id: &str, found: Option<String>| {
        let names = tiers[tier].entry(id.to_owned()).or_default();
        names.extend(found.filter(|n| !n.is_empty() && n.chars().count() <= FIELD_MAX_CHARS));
    };
    match &inventory.projects {
        Ok(records) => {
            for record in records {
                name(0, &record.id.0, text(&record.name, "").ok());
            }
            for kind in &inventory.project_gaps {
                discovery.add(
                    None,
                    gap_kind(*kind),
                    "the inventory project list had an unreadable row",
                );
            }
        }
        Err(kind) => discovery.add(None, kind, "the inventory project list could not be read"),
    }
    if let Sourced::Listed(projects, _) = &sourced {
        for (id, found) in projects {
            name(2, id, Some(found.clone()));
        }
    }
    for session in sessions {
        if let Grouping::Project { id, name: found } = &session.group {
            name(1, &id.0, text(found, "").ok());
        }
    }
    let ids: BTreeSet<&String> = tiers.iter().flat_map(BTreeMap::keys).collect();
    let mut universe: BTreeMap<String, Result<String, &'static str>> = BTreeMap::new();
    for id in ids {
        let names = tiers
            .iter()
            .filter_map(|tier| tier.get(id))
            .find(|names| !names.is_empty());
        let found = match names.map(|n| n.iter().collect::<Vec<_>>()).as_deref() {
            Some([one]) => Ok((*one).clone()),
            Some(_) => {
                discovery.add(
                    Some(id),
                    "malformed",
                    "the project's name conflicts between its records",
                );
                Err("the project's reported names conflict")
            }
            None => {
                discovery.add(Some(id), "missing_field", "the project's name was not read");
                Err("the project's name was not read")
            }
        };
        universe.insert(id.clone(), found);
    }
    for id in universe.keys() {
        if sourced.covers(id) == Some(false) {
            discovery.add(Some(id), "unsupported", NO_SOURCE);
        }
    }
    let mut discovered = vec![
        inventory
            .projects
            .as_ref()
            .ok()
            .map(|_| inventory.projects_at),
    ];
    if let Some(mapping) = mapping {
        discovered.push(matches!(sourced, Sourced::Listed(..)).then_some(mapping.at));
    }

    // The fleet reads, named by the source's one project when it has one.
    let single = sourced.single();
    let scope = single.ok();
    let mut fleet_gaps = Gaps::default();
    let view = github.and_then(|envelope| match &envelope.data {
        View::Fleets(view) => Some(view),
        View::Fleet(_) => None,
    });
    match github {
        None => fleet_gaps.add(None, "unsupported", "no fleet source is configured"),
        Some(envelope) => {
            read_gaps(&envelope.reads, scope, &mut fleet_gaps);
            if fleet_gaps.0.is_empty()
                && envelope.coverage.state != openwiz_core::envelope::Completeness::Complete
            {
                fleet_gaps.add(scope, "unsupported", "the fleets view was incomplete");
            }
        }
    }
    let fleet_snapshot = github.map(|e| e.freshness.snapshot_at.0);

    let target_project = target_project(mapping, &sourced, sessions);
    let projects: Vec<Value> = universe
        .iter()
        .map(|(id, found)| {
            json!({
                "id": id,
                "name": found.as_ref().map_or_else(|why| unknown(why), |n| known(n.clone())),
                "orchestrator": orchestrator(id, mapping, &sourced, target_project, now),
            })
        })
        .collect();

    let needs = needs_you(github, view, single, fleet_snapshot);
    let mut needs_gaps = discovery.clone();
    needs_gaps.extend(&fleet_gaps);
    needs_gaps.extend(&needs.1);
    if view.is_some_and(|v| matches!(v.needs_you, WorkedOut::Unread(_))) && fleet_gaps.0.is_empty()
    {
        needs_gaps.add(
            scope,
            "unsupported",
            "Needs you was not worked out from complete reads",
        );
    }
    let mut needs_at = discovered.clone();
    needs_at.push(fleet_snapshot);
    // A project without a fleet source has no Needs you snapshot.
    if universe.keys().any(|id| sourced.covers(id) != Some(true)) {
        needs_at.push(None);
    }

    let placements = placements(github, mapping);
    let mut agent_gaps = discovery.clone();
    agent_gaps.extend(&fleet_gaps);
    if let Some(Mapping {
        reads: Some(reads), ..
    }) = mapping
    {
        read_gaps(&room_reads(reads, 0), scope, &mut agent_gaps);
        if let Single::Failed(failed) = &reads.version {
            agent_gaps.add(
                scope,
                gap_kind(failed.gap),
                "the fleet source's room-cli version read failed",
            );
        }
    }
    let agents = running(inventory, view, &placements, &sourced, &mut agent_gaps);
    let mut agents_at = discovered.clone();
    agents_at.push(inventory.list.as_ref().ok().map(|listed| listed.snapshot));
    if let Some(mapping) = mapping {
        agents_at.push(fleet_snapshot);
        agents_at.push(mapping.reads.as_ref().map(|_| mapping.at));
    }
    // A running agent in a project without a fleet source has no placement
    // snapshot.
    let unsourced = agents.iter().any(|a| {
        a["project"]["known"]
            .as_str()
            .is_some_and(|p| sourced.covers(p) == Some(false))
    });
    if unsourced {
        agents_at.push(None);
    }

    json!({
        "schema": "openwiz.cockpit.v1",
        "snapshot_at": now,
        "projects": {
            "coverage": discovery.coverage(),
            "freshness": freshness(&discovered, now),
            "items": projects,
        },
        "needs_you": {
            "coverage": needs_gaps.coverage(),
            "freshness": freshness(&needs_at, now),
            "items": needs.0,
        },
        "agents": {
            "coverage": agent_gaps.coverage(),
            "freshness": freshness(&agents_at, now),
            "items": agents,
        },
    })
}

/// The project the configured target belongs to: the source's one project,
/// or, when its repository matches several, the target thread's own
/// verified inventory project among them. Never a guess.
fn target_project<'a>(
    mapping: Option<&Mapping>,
    sourced: &'a Sourced,
    sessions: &[Session],
) -> Option<&'a str> {
    // The target thread's own verified inventory project, if it is listed.
    let group = match &mapping?.target.target {
        Target::Known(thread) => sessions
            .iter()
            .find(|s| s.id.0 == *thread)
            .and_then(|s| match &s.group {
                Grouping::Project { id, .. } => Some(id.0.as_str()),
                Grouping::Ungrouped { .. } => None,
            }),
        _ => None,
    };
    if let Ok(project) = sourced.single() {
        // Positive evidence of another project contradicts the mapping.
        return group.is_none_or(|g| g == project).then_some(project);
    }
    let Sourced::Listed(projects, true) = sourced else {
        return None;
    };
    projects
        .iter()
        .find(|(p, _)| Some(p.as_str()) == group)
        .map(|(p, _)| p.as_str())
}

fn orchestrator(
    project: &str,
    mapping: Option<&Mapping>,
    sourced: &Sourced,
    target_project: Option<&str>,
    now: i64,
) -> Value {
    let mut gaps = Gaps::default();
    let unavailable = |gaps: &mut Gaps, kind: &'static str, why: &str| {
        gaps.add(Some(project), kind, why);
        json!({"coverage": gaps.coverage(), "freshness": freshness(&[None], now), "target": unknown(why)})
    };
    let Some(mapping) = mapping else {
        return unavailable(&mut gaps, "unsupported", NO_SOURCE);
    };
    match sourced.covers(project) {
        Some(false) => return unavailable(&mut gaps, "unsupported", NO_SOURCE),
        None => {
            let kind = match sourced {
                Sourced::Unread(kind) => kind,
                _ => "command_failed",
            };
            return unavailable(
                &mut gaps,
                kind,
                "this project's fleet source could not be mapped",
            );
        }
        Some(true) => {}
    }
    let checked = |target: Value| json!({"coverage": Gaps::default().coverage(), "freshness": freshness(&[Some(mapping.target.at)], now), "target": target});
    match &mapping.target.target {
        // No send target for any of the source's projects.
        Target::Absent => checked(known(Value::Null)),
        Target::Known(id) if target_project == Some(project) => checked(known(id.clone())),
        Target::Failed(kind, why) if target_project.is_none_or(|p| p == project) => {
            unavailable(&mut gaps, kind, why)
        }
        _ => unavailable(
            &mut gaps,
            "unsupported",
            "the configured orchestrator target is not verified as this project's",
        ),
    }
}

/// Needs you, and the gaps for its unsupported or unread facts.
fn needs_you(
    github: Option<&FleetEnvelope>,
    view: Option<&openwiz_core::fleet::model::FleetsView>,
    single: Result<&str, &'static str>,
    snapshot: Option<i64>,
) -> (Vec<Value>, Gaps) {
    let mut gaps = Gaps::default();
    let scope = single.ok();
    let items: Vec<NeedsYou> = match (github, view.map(|v| &v.needs_you)) {
        (Some(envelope), Some(WorkedOut::Unread(_))) => usable(envelope),
        (_, Some(WorkedOut::Known(items))) => items.clone(),
        _ => return (Vec::new(), gaps),
    };
    if let (Err(why), false) = (single, items.is_empty()) {
        gaps.add(
            None,
            "unsupported",
            format!("Needs you items have no verified project: {why}"),
        );
    }
    let mut rows: Vec<(Option<i64>, Value)> = items
        .iter()
        .map(|item| {
            let wording = match &item.wording {
                Fact::Known(w) => known(w.as_str()),
                Fact::Unknown(_) => {
                    gaps.add(
                        scope,
                        "unsupported",
                        "a Needs you item's wording is not supplied by the fleets view",
                    );
                    unknown("the question's wording was not read")
                }
            };
            let age = match (&item.asked_at, snapshot) {
                (Fact::Known(at), Some(snapshot)) if at.0 >= 0 && at.0 <= snapshot => {
                    Some(snapshot - at.0)
                }
                _ => {
                    gaps.add(
                        scope,
                        "unsupported",
                        "a Needs you item's age is not supplied by the fleets view",
                    );
                    None
                }
            };
            let risky = match &item.risk {
                Fact::Known(_) => known(true),
                Fact::Unknown(_) => {
                    gaps.add(
                        scope,
                        "unsupported",
                        "a Needs you item has no explicit risk classification",
                    );
                    unknown("no explicit risk classification was reported")
                }
            };
            let row = json!({
                "project": single.map_or_else(unknown, known),
                "kind": match item.kind {
                    NeedsYouKind::NeedsInfo => "needs_info",
                    NeedsYouKind::Held => "held",
                },
                "spec": item.spec.get(),
                "ticket": item.ticket.get(),
                "wording": wording,
                "age_ms": age.map_or_else(|| unknown("when it was asked is not known"), known),
                "risky": risky,
            });
            (age, row)
        })
        .collect();
    order(&mut rows);
    (rows.into_iter().map(|(_, row)| row).collect(), gaps)
}

/// When one fleet's reads are incomplete the view works Needs you out for
/// none: keep every item whose own reads are complete (a listed ticket of a
/// fleet, and that ticket's issue), with the core's own rules. The
/// incomplete reads are the fleet read gaps.
fn usable(envelope: &FleetEnvelope) -> Vec<NeedsYou> {
    let View::Fleets(view) = &envelope.data else {
        return Vec::new();
    };
    let issue = |ticket: Number| {
        envelope.reads.iter().find_map(|r| match &r.kind {
            ReadKind::Issue {
                issue,
                outcome: Single::Complete { value },
            } if *issue == ticket => Some(value),
            _ => None,
        })
    };
    let mut items = Vec::new();
    for fleet in &view.fleets {
        let tickets = envelope.reads.iter().find_map(|r| match &r.kind {
            ReadKind::SubIssues {
                spec,
                outcome: Listing::Complete { value } | Listing::Partial { value, .. },
            } if *spec == fleet.spec => Some(value),
            _ => None,
        });
        for &ticket in tickets.into_iter().flatten() {
            let Some(issue) = issue(ticket) else { continue };
            for kind in needs_you_kinds(issue) {
                items.push(needs_you_item(
                    kind,
                    fleet.spec,
                    ticket,
                    issue,
                    QUESTION_NOT_READ,
                ));
            }
        }
    }
    items
}

/// Needs you's order: oldest known age first, unknown ages after; then
/// known project (unassigned last), spec, ticket and kind. The sort is
/// stable, so still-indistinguishable items keep their source order.
fn order(rows: &mut [(Option<i64>, Value)]) {
    rows.sort_by(|(a, x), (b, y)| {
        let age = match (a, b) {
            (Some(a), Some(b)) => b.cmp(a),
            (Some(_), None) => std::cmp::Ordering::Less,
            (None, Some(_)) => std::cmp::Ordering::Greater,
            (None, None) => std::cmp::Ordering::Equal,
        };
        let project = |v: &Value| v["project"]["known"].as_str().map(str::to_owned);
        age.then_with(|| match (project(x), project(y)) {
            (Some(p), Some(q)) => p.cmp(&q),
            (Some(_), None) => std::cmp::Ordering::Less,
            (None, Some(_)) => std::cmp::Ordering::Greater,
            (None, None) => std::cmp::Ordering::Equal,
        })
        .then_with(|| x["spec"].as_u64().cmp(&y["spec"].as_u64()))
        .then_with(|| x["ticket"].as_u64().cmp(&y["ticket"].as_u64()))
        .then_with(|| x["kind"].as_str().cmp(&y["kind"].as_str()))
    });
}

/// Each thread the core's verified chain places, per fleet; and whether
/// every fleet's placement was worked out from complete reads.
struct Placements {
    placed: BTreeMap<String, BTreeSet<(Number, Number)>>,
    complete: bool,
    /// Each listed thread's project, as the fleet's thread list reports it.
    projects: BTreeMap<String, String>,
    /// Threads the chain leaves unplaced because a link is ambiguous (a
    /// shared branch, a pull request closing several tickets or issues).
    ambiguous: BTreeSet<String>,
}

fn placements(github: Option<&FleetEnvelope>, mapping: Option<&Mapping>) -> Placements {
    let mut placements = Placements {
        placed: BTreeMap::new(),
        complete: false,
        projects: BTreeMap::new(),
        ambiguous: BTreeSet::new(),
    };
    let (
        Some(envelope),
        Some(Mapping {
            reads: Some(room), ..
        }),
    ) = (github, mapping)
    else {
        return placements;
    };
    if let Listing::Complete { value } | Listing::Partial { value, .. } = &room.threads {
        for row in value {
            let (Thread::Cloud { thread, project }
            | Thread::Local {
                thread, project, ..
            }) = row;
            placements
                .projects
                .insert(thread.as_str().to_owned(), project.as_str().to_owned());
        }
    }
    let View::Fleets(view) = &envelope.data else {
        return placements;
    };
    let specs_read = envelope.reads.iter().any(|r| {
        matches!(
            &r.kind,
            ReadKind::SpecList {
                outcome: Listing::Complete { .. }
            }
        )
    });
    let after = envelope.reads.iter().map(|r| r.id.0).max().unwrap_or(0);
    let mut reads = envelope.reads.clone();
    reads.extend(room_reads(room, after));
    let mut complete = specs_read;
    for fleet in &view.fleets {
        let tickets = reads.iter().find_map(|r| match &r.kind {
            ReadKind::SubIssues {
                spec,
                outcome: Listing::Complete { value },
            } if *spec == fleet.spec => Some(value.clone()),
            _ => None,
        });
        let (Some(tickets), Ok(placed)) = (tickets, agents::place(fleet.spec, &reads)) else {
            complete = false;
            continue;
        };
        for ticket in tickets {
            match placed.builder(ticket) {
                WorkedOut::Known(Some(thread)) => {
                    placements
                        .placed
                        .entry(thread.as_str().to_owned())
                        .or_default()
                        .insert((fleet.spec, ticket));
                }
                WorkedOut::Known(None) => {}
                WorkedOut::Unread(_) => complete = false,
            }
        }
        if let WorkedOut::Known(unplaced) = placed.unplaced() {
            for row in unplaced {
                if matches!(
                    row.reason,
                    UnplacedReason::SharedBranch
                        | UnplacedReason::SeveralTickets
                        | UnplacedReason::SeveralIssues
                ) {
                    placements.ambiguous.insert(row.thread.as_str().to_owned());
                }
            }
        }
    }
    placements.complete = complete;
    placements
}

/// The running agents: inventory sessions whose status is exactly
/// `active`, joined to their verified fleet placement.
fn running(
    inventory: &InventoryRead,
    view: Option<&openwiz_core::fleet::model::FleetsView>,
    placements: &Placements,
    sourced: &Sourced,
    gaps: &mut Gaps,
) -> Vec<Value> {
    let listed = match &inventory.list {
        Ok(listed) => listed,
        Err(kind) => {
            gaps.add(None, kind, "the session list could not be read");
            return Vec::new();
        }
    };
    for kind in &listed.gaps {
        gaps.add(None, gap_kind(*kind), "an inventory read was incomplete");
    }
    if listed.truncated {
        gaps.add(None, "truncated", "the session list was not read in full");
    }
    let snapshot = openwiz_core::model::Timestamp(listed.snapshot);
    let mut rows: Vec<Value> = Vec::new();
    for session in &listed.sessions {
        let project = match &session.group {
            Grouping::Project { id, .. } => Some(id.0.as_str()),
            Grouping::Ungrouped { .. } => None,
        };
        match &session.status {
            Fact::Known(status) if status == "active" => {
                if project.is_none() {
                    gaps.add(
                        None,
                        "missing_field",
                        "a running session's project was not verified",
                    );
                }
            }
            Fact::Known(status) if status == "idle" || status == "error" => continue,
            Fact::Known(_) => {
                gaps.add(
                    project,
                    "unsupported",
                    "a session's status is not a recognized running or stopped state",
                );
                continue;
            }
            Fact::Unknown(_) => {
                gaps.add(project, "missing_field", "a session's status was not read");
                continue;
            }
        }
        let detail = inventory.details.get(&session.id);
        let model = match detail {
            Some(Ok(record)) => {
                for problem in &record.session.problems {
                    gaps.add(
                        project,
                        gap_kind(problem.kind),
                        "a running session's detail read was incomplete",
                    );
                }
                text(&record.model, "the reported model was not read").inspect_err(|_| {
                    gaps.add(
                        project,
                        "missing_field",
                        "a running session's reported model was not read",
                    );
                })
            }
            Some(Err(kind)) => {
                gaps.add(
                    project,
                    kind,
                    "a running session's detail could not be read",
                );
                Err("the session detail could not be read".to_owned())
            }
            None => {
                gaps.add(
                    project,
                    "budget_exhausted",
                    "a running session's detail was not read",
                );
                Err("the session detail was not read".to_owned())
            }
        };
        let model = model.map_or_else(|why| unknown(&why), known);
        let started = match (&session.started_at, detail) {
            (Fact::Known(at), _) => Some(at.0),
            (_, Some(Ok(record))) => match record.session.started_at {
                Fact::Known(at) if at <= snapshot && at.0 >= 0 => Some(at.0),
                _ => None,
            },
            _ => None,
        };
        let started_at = started.map_or_else(
            || {
                gaps.add(
                    project,
                    "unsupported",
                    "the source reported no start time for a running agent",
                );
                unknown("the source reported no start time")
            },
            known,
        );
        let title = text(&session.title, "the title was not reported").map_or_else(
            |why| {
                gaps.add(
                    project,
                    "missing_field",
                    "a running session's title was not read",
                );
                unknown(&why)
            },
            known,
        );
        let location = match &session.location {
            Fact::Known(Location::Cloud) => known(json!({"kind": "cloud"})),
            Fact::Known(Location::Local { machine }) => known(json!({
                "kind": "local",
                "machine": text(machine, "the machine was not reported").map_or_else(
                    |why| {
                        gaps.add(project, "missing_field", "a running local session's machine was not reported");
                        unknown(&why)
                    },
                    known,
                ),
            })),
            Fact::Unknown(_) => {
                gaps.add(
                    project,
                    "missing_field",
                    "a running session's location was not read",
                );
                unknown("the location was not reported")
            }
        };
        let (fleet, ticket, state) = place(&session.id.0, project, view, placements, sourced, gaps);
        rows.push(json!({
            "thread": session.id.0,
            "project": project.map_or_else(|| unknown("the session's project was not verified"), known),
            "title": title,
            "fleet": fleet,
            "ticket": ticket,
            "activity": "active",
            "model": model,
            "state": state,
            "location": location,
            "started_at": started_at,
        }));
    }
    // By project, fleet and ticket (unknowns last), then thread.
    let key = |row: &Value| {
        let last = |v: &Value| (v.get("known").is_none(), v["known"].clone().to_string());
        (
            last(&row["project"]),
            row["fleet"]["known"].as_u64().is_none(),
            row["fleet"]["known"].as_u64(),
            row["ticket"]["known"].as_u64().is_none(),
            row["ticket"]["known"].as_u64(),
            row["thread"].as_str().unwrap_or_default().to_owned(),
        )
    };
    rows.sort_by_key(key);
    rows
}

/// An agent's fleet, ticket and the ticket's state: only from the verified
/// chain, never a title.
fn place(
    thread: &str,
    project: Option<&str>,
    view: Option<&openwiz_core::fleet::model::FleetsView>,
    placements: &Placements,
    sourced: &Sourced,
    gaps: &mut Gaps,
) -> (Value, Value, Value) {
    let unplaced = |why: &str| (unknown(why), unknown(why), unknown(why));
    // Two reads that disagree on the thread's project place nothing.
    if let (Some(inventory), Some(listed)) = (project, placements.projects.get(thread))
        && inventory != listed
    {
        gaps.add(
            project,
            "malformed",
            "a running agent's project differs between the inventory and the fleet's thread list",
        );
        return unplaced("the thread's project differs between reads");
    }
    // An ambiguous link in any fleet makes the placement doubtful, even
    // when another fleet's chain places the thread: it places nothing.
    if placements.ambiguous.contains(thread) {
        gaps.add(
            project,
            "unsupported",
            "a running agent's placement is ambiguous",
        );
        return unplaced("the verified chain is ambiguous for this thread");
    }
    let places = placements.placed.get(thread);
    match places.map(|p| p.iter().collect::<Vec<_>>()).as_deref() {
        Some([(spec, ticket)]) => {
            let state = view
                .and_then(|v| v.tickets.iter().find(|t| t.number == *ticket))
                .map_or(Err("the ticket's state was not read"), |t| match &t.state {
                    State::Known(state) => {
                        serde_json::to_value(state).map_err(|_| "the ticket's state is unknown")
                    }
                    State::Unread(_) => Err("the ticket's state was not read"),
                    State::Unknown(_) => Err("the ticket's state is unknown"),
                });
            // A required fact the fleet can't supply: never complete.
            let state = state.map_or_else(
                |why| {
                    gaps.add(
                        project,
                        "unsupported",
                        "a placed running agent's ticket state is not known",
                    );
                    unknown(why)
                },
                known,
            );
            (known(spec.get()), known(ticket.get()), state)
        }
        Some(_) => {
            gaps.add(
                project,
                "unsupported",
                "a running agent is placed on several tickets",
            );
            unplaced("the verified chain places this thread on several tickets")
        }
        None if project.is_some_and(|p| sourced.covers(p) == Some(false)) => {
            unplaced("this thread's project has no fleet source")
        }
        // Unknown required facts: a gap, even when every read was complete.
        None if placements.complete => {
            gaps.add(
                project,
                "unsupported",
                "a running agent is not placed by any verified chain",
            );
            unplaced("no verified chain places this thread")
        }
        None => {
            gaps.add(
                project,
                "unsupported",
                "a running agent's fleet placement was not read",
            );
            unplaced("the fleet placement was not read")
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(
        age: Option<i64>,
        project: Option<&str>,
        spec: u64,
        ticket: u64,
        kind: &str,
    ) -> (Option<i64>, Value) {
        (
            age,
            json!({"project": project.map_or_else(|| unknown("x"), known), "spec": spec, "ticket": ticket, "kind": kind}),
        )
    }

    /// The contract's order, on synthetic rows: known ages oldest first,
    /// then unknown ages; ties by project (unassigned last), spec, ticket,
    /// kind; unassigned twins keep their source order.
    #[test]
    fn needs_you_order_is_the_contracts() {
        let mut rows = vec![
            row(None, None, 1, 2, "held"),
            row(Some(5), Some("prj_syn_b"), 9, 9, "held"),
            row(None, Some("prj_syn_a"), 3, 1, "needs_info"),
            row(Some(50), Some("prj_syn_b"), 9, 9, "held"),
            row(None, Some("prj_syn_a"), 3, 1, "held"),
            row(None, None, 1, 2, "held"),
            row(Some(5), Some("prj_syn_a"), 9, 9, "held"),
            row(None, Some("prj_syn_a"), 2, 7, "held"),
        ];
        rows[5].1["marker"] = json!("second");
        order(&mut rows);
        let got: Vec<(Option<i64>, Value, u64, u64, String, bool)> = rows
            .iter()
            .map(|(age, v)| {
                (
                    *age,
                    v["project"].clone(),
                    v["spec"].as_u64().unwrap(),
                    v["ticket"].as_u64().unwrap(),
                    v["kind"].as_str().unwrap().to_owned(),
                    v.get("marker").is_some(),
                )
            })
            .collect();
        let (a, b, none) = (known("prj_syn_a"), known("prj_syn_b"), unknown("x"));
        assert_eq!(
            got,
            vec![
                (Some(50), b.clone(), 9, 9, "held".to_owned(), false),
                (Some(5), a.clone(), 9, 9, "held".to_owned(), false),
                (Some(5), b, 9, 9, "held".to_owned(), false),
                (None, a.clone(), 2, 7, "held".to_owned(), false),
                (None, a.clone(), 3, 1, "held".to_owned(), false),
                (None, a, 3, 1, "needs_info".to_owned(), false),
                (None, none.clone(), 1, 2, "held".to_owned(), false),
                (None, none, 1, 2, "held".to_owned(), true),
            ]
        );
    }

    #[test]
    fn freshness_uses_the_oldest_snapshot_and_the_fleet_threshold() {
        assert_eq!(
            freshness(&[Some(100), Some(30)], 70_030),
            json!({"state": "fresh", "snapshot_at": {"known": 30}})
        );
        assert_eq!(
            freshness(&[Some(30)], 70_031),
            json!({"state": "stale", "snapshot_at": {"known": 30}})
        );
        // R8 (self-review 1): any required snapshot after assembly, not only
        // the oldest, makes it unknown.
        for snapshots in [
            vec![Some(30), None],
            vec![Some(70_031)],
            vec![],
            vec![Some(30), Some(70_031)],
        ] {
            assert_eq!(
                freshness(&snapshots, 70_030)["state"],
                "unknown",
                "{snapshots:?}"
            );
        }
    }
}
