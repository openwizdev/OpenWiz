//! Starting builders and reviewers (OpenWiz 0.0.6 spec 2, B4,
//! ClosedWiz#120): one new Cloud thread through 0.0.4's `new_thread`, and
//! **never two for one start**, even if the tick crashes between the start
//! and its record, or the start times out.
//!
//! A **start** is what one agent is for ([`StartKey`]): a ticket's builder,
//! or a reviewer for one pull request at one head commit. Its **start
//! record** ([`StartRecord`]) is the grill's one exception to "no new state"
//! (Q2: "a small record of every builder it starts (like `send`'s records),
//! so a ticket can never get two builders"). It holds the start's attempts,
//! each with the `new_thread` op id it used and what came of it.
//!
//! The rule, in [`start_agent`], under the start's lock (atomic across
//! processes, so two ticks at once can't both start one):
//! - **Recorded before it's made** (#116): a new attempt and its op id are
//!   written, synced, before `new_thread` runs. Only then is the call made.
//! - **Reconciled before any retry** (#116): an attempt left pending (its
//!   tick stopped before recording what came of it) is first read through
//!   0.0.4's status read ([`new_thread_status`]): no `new_thread` record
//!   under its op id means nothing was sent, so the same op id is used
//!   again; Created is recorded and never started again; Refused or Failed
//!   (nothing created) allows a new attempt with a new op id.
//! - **An op id is adopted only with its own create** (review R1): a
//!   pending attempt's status counts only when its `new_thread` record is
//!   bound to this start (its project, harness, model, effort, brief and no
//!   attachments). One bound to anything else is another create, and
//!   `new_thread` sends nothing under it for this start, so the attempt is
//!   settled as not created, with no call; so is a call `new_thread` refuses
//!   as conflicting reuse.
//! - **An uncertain start is never retried** (sheet A-3, and the
//!   orchestrator on #120, Q3): 0.0.4's status read can't settle it, and
//!   `new_thread` never sends one op id twice. It stays uncertain, for a
//!   person to resolve in CloudRoom.
//! - **Never swapped** (`docs/agents/fleet.md`): a new attempt uses exactly
//!   the project, harness, model and effort the start was first recorded
//!   with. A new attempt with others is refused, with no call; a start
//!   already started or uncertain stays so, whatever the request says.
//!
//! The harness, model and effort come from the caller (fleet.md's builder
//! and reviewer rows), never from here. The prompt is the one-line brief
//! ([`brief`]). Like the rest of the core, this module does no I/O: the
//! record goes through a [`StartStore`] (the command's `state`), the reads and the
//! one write through a [`NewThreadClient`] (the adapter).

use std::time::Duration;

use serde::Serialize;

use crate::messaging::record::StoreError;
use crate::messaging::{InvalidRequest, OpId, sha256_hex};
use crate::model::Timestamp;
use crate::new_thread::operation::{
    NewThreadClient, NewThreadError, NewThreadReport, NewThreadResult, new_thread,
};
use crate::new_thread::outcome::{Gap, Outcome};
use crate::new_thread::record::NewThreadStore;
use crate::new_thread::status::{StatusResult, new_thread_status};
use crate::new_thread::{Binding, NEW_THREAD_BUDGET, NewThreadRequest, ProjectRef, Settings};
use crate::ops::Clock;
use crate::prompt::{PromptPayload, attachments_digest};

use super::model::{Commit, Number};

/// The schema id of a start record.
pub const START_RECORD_SCHEMA_ID: &str = "openwiz.start-record.v1";

/// What a start record's file id hashes before the start's key.
pub const START_ID_DOMAIN: &str = "openwiz.start.v1:";

/// The prefix of every start record's file id.
pub const START_ID_PREFIX: &str = "start-";

/// Which agent a start is for.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    Builder,
    Reviewer,
}

impl Role {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Builder => "builder",
            Self::Reviewer => "reviewer",
        }
    }
}

/// A GitHub repository, `owner/name`: the owner 1 to 39 ASCII letters,
/// digits or `-`, not starting with `-`; the name 1 to 100 ASCII letters,
/// digits, `.`, `_` or `-`, never `.` or `..`. GitHub's names ignore case,
/// so it is kept in lower case: one repository is one value however it is
/// spelled, and one ticket one start (review R2).
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(transparent)]
pub struct Repository(String);

impl Repository {
    pub fn parse(text: &str) -> Result<Self, InvalidRequest> {
        let valid = text.split_once('/').is_some_and(|(owner, name)| {
            (1..=39).contains(&owner.len())
                && !owner.starts_with('-')
                && owner
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-')
                && (1..=100).contains(&name.len())
                && name != "."
                && name != ".."
                && name
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
        });
        if valid {
            Ok(Self(text.to_ascii_lowercase()))
        } else {
            Err(InvalidRequest(
                "a repository is owner/name, as GitHub names them".to_owned(),
            ))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// What one start is for. It gets at most one agent.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct StartKey {
    repository: Repository,
    role: Role,
    /// The ticket (a builder's) or the pull request (a reviewer's).
    number: Number,
    /// The head commit a reviewer reviews; none for a builder.
    commit: Option<Commit>,
}

impl StartKey {
    /// The builder of ticket `ticket`.
    pub fn builder(repository: Repository, ticket: Number) -> Self {
        Self {
            repository,
            role: Role::Builder,
            number: ticket,
            commit: None,
        }
    }

    /// The reviewer of pull request `pull_request` at `commit`.
    pub fn reviewer(repository: Repository, pull_request: Number, commit: Commit) -> Self {
        Self {
            repository,
            role: Role::Reviewer,
            number: pull_request,
            commit: Some(commit),
        }
    }

    pub fn repository(&self) -> &Repository {
        &self.repository
    }

    pub fn role(&self) -> Role {
        self.role
    }

    pub fn number(&self) -> Number {
        self.number
    }

    pub fn commit(&self) -> Option<&Commit> {
        self.commit.as_ref()
    }

    /// The start record's file id: [`START_ID_PREFIX`] and the first 40 hex
    /// digits of the SHA-256 of [`START_ID_DOMAIN`] and the key, so any
    /// repository name gives a safe file name, and one key always the same.
    pub fn id(&self) -> OpId {
        let key = match &self.commit {
            None => format!(
                "{}:{}#{}",
                self.role.as_str(),
                self.repository.0,
                self.number
            ),
            Some(commit) => format!(
                "{}:{}#{}@{}",
                self.role.as_str(),
                self.repository.0,
                self.number,
                commit.as_str()
            ),
        };
        let digest = sha256_hex(format!("{START_ID_DOMAIN}{key}").as_bytes());
        OpId::parse(&format!("{START_ID_PREFIX}{}", &digest[..40]))
            .expect("a prefix and hex digits make an op id")
    }
}

/// The one-line brief, the same for every builder (`launch-fleet`, step 3)
/// and for every reviewer (step 4): everything about the work is in the
/// ticket, its spec and the skill, so the brief never drifts from them.
pub fn brief(key: &StartKey) -> String {
    match &key.commit {
        None => format!(
            "You are the builder for #{}. Read skills/build-ticket/SKILL.md and follow it.",
            key.number
        ),
        Some(commit) => format!(
            "You are the reviewer for pull request #{} at {}. Read skills/review-ticket/SKILL.md \
             and follow it.",
            key.number,
            commit.as_str()
        ),
    }
}

/// What came of one attempt.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum AttemptOutcome {
    /// Recorded before the call; what came of it is not recorded yet.
    Pending,
    /// `new_thread` created the thread: the start's one agent.
    Created { thread_id: String },
    /// Nothing was created (`new_thread` said Refused or Failed).
    NotCreated { status: NotCreated, words: String },
    /// Whether a thread was created can't be told. Never retried.
    Uncertain { words: String },
}

/// Which of `new_thread`'s outcomes created nothing.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NotCreated {
    Refused,
    Failed,
}

/// One attempt: its `new_thread` op id, when it was recorded, and what came
/// of it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Attempt {
    pub op_id: OpId,
    pub at: Timestamp,
    pub outcome: AttemptOutcome,
}

/// One start, as stored. Every attempt but the last created nothing.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct StartRecord {
    /// Always [`START_RECORD_SCHEMA_ID`].
    schema: String,
    /// Always [`StartKey::id`] of `key`.
    id: OpId,
    key: StartKey,
    /// The CloudRoom project every attempt starts in, by id.
    project_id: String,
    /// The harness, model and effort every attempt uses: never swapped.
    settings: Settings,
    /// Never empty.
    attempts: Vec<Attempt>,
}

impl StartRecord {
    /// A new record for `request`, with its first attempt pending.
    fn first(request: &StartRequest, op_id: OpId, now: Timestamp) -> Self {
        Self {
            schema: START_RECORD_SCHEMA_ID.to_owned(),
            id: request.key.id(),
            key: request.key.clone(),
            project_id: request.project_id.clone(),
            settings: request.settings.clone(),
            attempts: vec![Attempt {
                op_id,
                at: now,
                outcome: AttemptOutcome::Pending,
            }],
        }
    }

    pub fn id(&self) -> &OpId {
        &self.id
    }

    pub fn key(&self) -> &StartKey {
        &self.key
    }

    pub fn project_id(&self) -> &str {
        &self.project_id
    }

    pub fn settings(&self) -> &Settings {
        &self.settings
    }

    pub fn attempts(&self) -> &[Attempt] {
        &self.attempts
    }

    fn last(&self) -> &Attempt {
        self.attempts.last().expect("a start record has an attempt")
    }

    /// The same record, its last attempt settled with `outcome`.
    fn settled(&self, outcome: AttemptOutcome) -> Self {
        let mut record = self.clone();
        if let Some(last) = record.attempts.last_mut() {
            last.outcome = outcome;
        }
        record
    }

    /// The same record with a new pending attempt.
    fn retried(&self, op_id: OpId, now: Timestamp) -> Self {
        let mut record = self.clone();
        record.attempts.push(Attempt {
            op_id,
            at: now,
            outcome: AttemptOutcome::Pending,
        });
        record
    }

    /// A record from its parts, as the store reads them back, only when
    /// it agrees with itself: its id is its key's; the project id, the
    /// settings and the brief pass the rules a start's request does; it has
    /// an attempt, each with its own op id and a time of 0 or more; every
    /// attempt but the last created nothing; and a created thread's id is
    /// safe to pass. Why not, in OpenWiz's words, never the content.
    pub fn from_parts(
        id: OpId,
        key: StartKey,
        project_id: String,
        settings: Settings,
        attempts: Vec<Attempt>,
    ) -> Result<Self, String> {
        if id != key.id() {
            return Err("its id is not its key's".to_owned());
        }
        StartRequest::new(key.clone(), project_id.clone(), settings.clone())
            .validate()
            .map_err(|e| e.0)?;
        if attempts.is_empty() {
            return Err("it has no attempt".to_owned());
        }
        for (i, attempt) in attempts.iter().enumerate() {
            if attempts[..i].iter().any(|a| a.op_id == attempt.op_id) {
                return Err(format!("attempt {i}'s op id is given twice"));
            }
            if attempt.at.0 < 0 {
                return Err(format!("attempt {i}'s time is before 1970"));
            }
            let created_nothing = matches!(attempt.outcome, AttemptOutcome::NotCreated { .. });
            if i + 1 < attempts.len() && !created_nothing {
                return Err(format!(
                    "attempt {i} is not the last, so it must have created nothing"
                ));
            }
            if let AttemptOutcome::Created { thread_id } = &attempt.outcome
                && !safe_id(thread_id)
            {
                return Err(format!("attempt {i}'s thread id is not safe to pass"));
            }
        }
        Ok(Self {
            schema: START_RECORD_SCHEMA_ID.to_owned(),
            id,
            key,
            project_id,
            settings,
            attempts,
        })
    }
}

/// A thread or project id: 1 to 128 ASCII letters, digits, `_` or `-`, not
/// starting with `-`, as the adapter passes one.
pub fn safe_id(id: &str) -> bool {
    (1..=128).contains(&id.len())
        && !id.starts_with('-')
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

/// What locking a start found.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Locked {
    /// This process holds the start's lock; its record, read afresh under
    /// it, if one exists.
    Mine(Option<Box<StartRecord>>),
    /// Another live process holds it.
    Busy,
}

/// The durable, per-owner store of start records. The core never touches
/// storage itself.
///
/// Required of an implementation, as of `send`'s and `new_thread`'s
/// stores:
/// - [`lock`](Self::lock) is atomic across processes: while one caller
///   holds a start's lock, every other gets [`Locked::Busy`]; a process that
///   stops lets go of its locks;
/// - the record is read afresh once the lock is held, strictly (never
///   serde's derived readers), and only through
///   [`StartRecord::from_parts`];
/// - every write is synced before the call returns, and only the lock's
///   holder writes;
/// - records are readable by the owner only.
pub trait StartStore: Send + Sync {
    /// Takes `key`'s lock and reads its record under it.
    fn lock(&self, key: &StartKey) -> Result<Locked, StoreError>;

    /// Writes `record` in place of the old one, synced. Refused unless this
    /// process holds its key's lock.
    fn write(&self, record: &StartRecord) -> Result<(), StoreError>;

    /// Lets go of `key`'s lock.
    fn unlock(&self, key: &StartKey);

    /// `key`'s record, if one exists. **Never writes** and never locks.
    fn inspect(&self, key: &StartKey) -> Result<Option<StartRecord>, StoreError>;
}

/// One start: what it is for, where, and with which settings.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StartRequest {
    pub key: StartKey,
    /// The CloudRoom project the agent starts in, by id.
    pub project_id: String,
    /// The harness, model and effort: fleet.md's row for the key's role.
    pub settings: Settings,
    /// The budget of each `new_thread` call and status read.
    pub budget: Duration,
}

impl StartRequest {
    pub fn new(key: StartKey, project_id: impl Into<String>, settings: Settings) -> Self {
        Self {
            key,
            project_id: project_id.into(),
            settings,
            budget: NEW_THREAD_BUDGET,
        }
    }

    /// Everything that can be checked before anything is locked, read or
    /// sent: the project id (as the adapter passes one) and, through
    /// `new_thread`'s own rule, the settings and the brief.
    pub fn validate(&self) -> Result<(), InvalidRequest> {
        if !safe_id(&self.project_id) {
            return Err(InvalidRequest(
                "the project id is 1 to 128 ASCII letters, digits, _ or -, not starting with -"
                    .to_owned(),
            ));
        }
        // The op id plays no part in the check; the start's own id is one.
        self.new_thread(self.key.id()).validate()
    }

    /// The `new_thread` request of one attempt with `op_id`.
    fn new_thread(&self, op_id: OpId) -> NewThreadRequest {
        let mut request = NewThreadRequest::new(
            ProjectRef::Id(self.project_id.clone()),
            self.settings.clone(),
            PromptPayload::text(brief(&self.key)),
            op_id,
        );
        request.budget = self.budget;
        request
    }
}

/// A part of a start that a request may differ in.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum StartField {
    Project,
    Harness,
    Model,
    Effort,
}

/// What a start came to.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum StartOutcome {
    /// The start's one agent: created by this call (`by_this_call`), or
    /// found recorded or reconciled, with no call.
    Started {
        thread_id: String,
        by_this_call: bool,
    },
    /// Nothing was created. A later start makes a new attempt.
    NotStarted { words: String },
    /// Whether an agent was created can't be told. It is never retried: a
    /// person resolves it in CloudRoom.
    Uncertain { words: String },
    /// Another process is starting it right now. Nothing was done.
    InProgress,
    /// The request's project or settings differ from the ones the start
    /// was first recorded with. Nothing was done: never swapped.
    Conflicting { differs: Vec<StartField> },
}

/// The result of [`start_agent`].
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct StartReport {
    pub key: StartKey,
    /// The op id of the attempt the outcome concerns; none when nothing
    /// was looked at.
    pub op_id: Option<OpId>,
    pub outcome: StartOutcome,
    /// What could not be done, such as recording the outcome.
    pub gaps: Vec<Gap>,
}

/// Why a start could not be made. Nothing was sent.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StartError {
    /// The request is invalid.
    Invalid(InvalidRequest),
    /// A record could not be used.
    Store(StoreError),
    /// No op id could be made for a new attempt.
    OpId(String),
}

/// What [`start_agent`] does next for a start, worked out from its record
/// alone: the one decision, shared with [`preview_start`].
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Next {
    /// No attempt may be running: a new one, with a new op id.
    Attempt,
    /// The last attempt is pending: read its status first.
    Reconcile { op_id: OpId },
    /// Its agent exists: nothing to do.
    Started { op_id: OpId, thread_id: String },
    /// Its last attempt is uncertain: never retried.
    Uncertain { op_id: OpId, words: String },
    /// A new attempt would swap something: refused.
    Conflicting { differs: Vec<StartField> },
}

/// The next step for `request`, given its start record.
pub fn next_step(record: Option<&StartRecord>, request: &StartRequest) -> Next {
    let Some(record) = record else {
        return Next::Attempt;
    };
    let last = record.last();
    match &last.outcome {
        AttemptOutcome::Created { thread_id } => Next::Started {
            op_id: last.op_id.clone(),
            thread_id: thread_id.clone(),
        },
        AttemptOutcome::Uncertain { words } => Next::Uncertain {
            op_id: last.op_id.clone(),
            words: words.clone(),
        },
        AttemptOutcome::Pending => Next::Reconcile {
            op_id: last.op_id.clone(),
        },
        AttemptOutcome::NotCreated { .. } => match differences(record, request) {
            differs if differs.is_empty() => Next::Attempt,
            differs => Next::Conflicting { differs },
        },
    }
}

/// The parts of `request` that differ from the start `record` holds.
fn differences(record: &StartRecord, request: &StartRequest) -> Vec<StartField> {
    [
        (StartField::Project, record.project_id == request.project_id),
        (
            StartField::Harness,
            record.settings.harness == request.settings.harness,
        ),
        (
            StartField::Model,
            record.settings.model == request.settings.model,
        ),
        (
            StartField::Effort,
            record.settings.effort == request.settings.effort,
        ),
    ]
    .into_iter()
    .filter(|(_, same)| !same)
    .map(|(field, _)| field)
    .collect()
}

/// What [`start_agent`] would do next for `request`, from the record
/// alone: **read-only**, it never locks, writes, reads CloudRoom or calls
/// anything (for a dry run).
pub fn preview_start(starts: &dyn StartStore, request: &StartRequest) -> Result<Next, StoreError> {
    Ok(next_step(starts.inspect(&request.key)?.as_ref(), request))
}

/// Starts the agent `request` is for, unless its start already has one or
/// can't be told. See the module documentation for the rule.
pub fn start_agent(
    client: &dyn NewThreadClient,
    threads: &dyn NewThreadStore,
    starts: &dyn StartStore,
    clock: &dyn Clock,
    new_op_id: &dyn Fn() -> Result<OpId, String>,
    request: &StartRequest,
) -> Result<StartReport, StartError> {
    request.validate().map_err(StartError::Invalid)?;
    let Locked::Mine(record) = starts.lock(&request.key).map_err(StartError::Store)? else {
        return Ok(report(request, None, StartOutcome::InProgress, vec![]));
    };
    let record = record.map(|r| *r);
    let started = Start {
        client,
        threads,
        starts,
        clock,
        request,
    }
    .run(record, new_op_id);
    starts.unlock(&request.key);
    started
}

struct Start<'a> {
    client: &'a dyn NewThreadClient,
    threads: &'a dyn NewThreadStore,
    starts: &'a dyn StartStore,
    clock: &'a dyn Clock,
    request: &'a StartRequest,
}

impl Start<'_> {
    /// Under the lock, with the record read afresh.
    fn run(
        &self,
        record: Option<StartRecord>,
        new_op_id: &dyn Fn() -> Result<OpId, String>,
    ) -> Result<StartReport, StartError> {
        if let Some(r) = &record
            && r.key != self.request.key
        {
            return Err(StartError::Store(StoreError(
                "the start record holds another start".to_owned(),
            )));
        }
        let record = match next_step(record.as_ref(), self.request) {
            Next::Started { op_id, thread_id } => {
                let started = StartOutcome::Started {
                    thread_id,
                    by_this_call: false,
                };
                return Ok(report(self.request, Some(op_id), started, vec![]));
            }
            Next::Uncertain { op_id, words } => {
                let uncertain = StartOutcome::Uncertain { words };
                return Ok(report(self.request, Some(op_id), uncertain, vec![]));
            }
            Next::Conflicting { differs } => return Ok(self.conflicting(differs)),
            Next::Reconcile { op_id } => {
                let record = record.expect("a pending attempt has a record");
                let reconciled = self.reconcile(&record, &op_id)?;
                // Any call from here on uses exactly what was recorded.
                let differs = differences(&record, self.request);
                match reconciled {
                    Reconciled::Done(report) => return Ok(report),
                    Reconciled::NothingSent | Reconciled::NotCreated(_) if !differs.is_empty() => {
                        return Ok(self.conflicting(differs));
                    }
                    // Nothing was sent under this op id: it is used again.
                    Reconciled::NothingSent => return self.call(&record, op_id),
                    Reconciled::NotCreated(settled) => Some(settled),
                }
            }
            Next::Attempt => record,
        };
        // A new attempt, recorded before it's made, with an op id of its
        // own: one used before would make the record unreadable.
        let op_id = new_op_id().map_err(StartError::OpId)?;
        if let Some(r) = &record
            && r.attempts.iter().any(|a| a.op_id == op_id)
        {
            return Err(StartError::OpId(
                "the new op id was used before for this start".to_owned(),
            ));
        }
        let now = self.clock.now();
        let pending = match &record {
            None => StartRecord::first(self.request, op_id.clone(), now),
            Some(r) => r.retried(op_id.clone(), now),
        };
        self.starts.write(&pending).map_err(StartError::Store)?;
        self.call(&pending, op_id)
    }

    fn conflicting(&self, differs: Vec<StartField>) -> StartReport {
        report(
            self.request,
            None,
            StartOutcome::Conflicting { differs },
            vec![],
        )
    }

    /// 0.0.4's status read of the pending attempt `op_id`, before anything
    /// else is done for this start.
    fn reconcile(&self, record: &StartRecord, op_id: &OpId) -> Result<Reconciled, StartError> {
        let status = new_thread_status(
            self.client,
            self.threads,
            self.clock,
            op_id,
            self.request.budget,
        )
        .map_err(StartError::Store)?;
        let StatusResult::Recorded(found) = status.result else {
            return Ok(Reconciled::NothingSent);
        };
        if !binds(record, op_id, &found.report) {
            return Ok(Reconciled::Done(self.not_ours(record)));
        }
        let outcome = match found.report.result {
            NewThreadResult::Outcome { outcome, .. } => outcome,
            NewThreadResult::InProgress { .. } => {
                let in_progress = report(
                    self.request,
                    Some(op_id.clone()),
                    StartOutcome::InProgress,
                    vec![],
                );
                return Ok(Reconciled::Done(in_progress));
            }
            NewThreadResult::ConflictingReuse { .. } => {
                return Ok(Reconciled::Done(self.not_ours(record)));
            }
        };
        let (settled, started) = self.settle(record, op_id, &outcome, false);
        if let AttemptOutcome::NotCreated { .. } = settled.last().outcome {
            self.starts.write(&settled).map_err(StartError::Store)?;
            return Ok(Reconciled::NotCreated(settled));
        }
        Ok(Reconciled::Done(self.record_outcome(&settled, started)))
    }

    /// The one `new_thread` call of `op_id`, its attempt already recorded
    /// in `record`, and what came of it recorded after.
    fn call(&self, record: &StartRecord, op_id: OpId) -> Result<StartReport, StartError> {
        let made = new_thread(
            self.client,
            self.threads,
            self.clock,
            &self.request.new_thread(op_id.clone()),
        );
        let result = match made {
            Ok(made) => made.result,
            // Nothing was sent. The attempt stays pending, and the next
            // start reconciles it.
            Err(NewThreadError::Invalid(e)) => return Err(StartError::Invalid(e)),
            Err(NewThreadError::Store(e)) => return Err(StartError::Store(e)),
        };
        let outcome = match result {
            NewThreadResult::Outcome {
                outcome, replayed, ..
            } => (outcome, !replayed),
            NewThreadResult::InProgress { .. } => {
                let in_progress = StartOutcome::InProgress;
                return Ok(report(self.request, Some(op_id), in_progress, vec![]));
            }
            // An op id bound to another create: `new_thread` made no call.
            NewThreadResult::ConflictingReuse { .. } => return Ok(self.not_ours(record)),
        };
        let (settled, started) = self.settle(record, &op_id, &outcome.0, outcome.1);
        Ok(self.record_outcome(&settled, started))
    }

    /// The record with `op_id`'s attempt settled by `outcome`, and what the
    /// start came to.
    fn settle(
        &self,
        record: &StartRecord,
        op_id: &OpId,
        outcome: &Outcome,
        by_this_call: bool,
    ) -> (StartRecord, StartOutcome) {
        let words = outcome.text().to_owned();
        let (attempt, started) = match outcome {
            Outcome::Created { thread_id, .. } => (
                AttemptOutcome::Created {
                    thread_id: thread_id.clone(),
                },
                StartOutcome::Started {
                    thread_id: thread_id.clone(),
                    by_this_call,
                },
            ),
            Outcome::Refused { .. } | Outcome::Failed { .. } => {
                let status = if matches!(outcome, Outcome::Refused { .. }) {
                    NotCreated::Refused
                } else {
                    NotCreated::Failed
                };
                (
                    AttemptOutcome::NotCreated {
                        status,
                        words: words.clone(),
                    },
                    StartOutcome::NotStarted { words },
                )
            }
            Outcome::Uncertain { .. } => (
                AttemptOutcome::Uncertain {
                    words: words.clone(),
                },
                StartOutcome::Uncertain { words },
            ),
        };
        debug_assert_eq!(&record.last().op_id, op_id);
        (record.settled(attempt), started)
    }

    /// The last attempt's op id holds another create: nothing was sent for
    /// this start under it. Settled as not created, so the next start makes
    /// a new attempt with a new op id; nothing is taken from that create.
    fn not_ours(&self, record: &StartRecord) -> StartReport {
        let words = "its op id holds another start's create, so nothing was sent for this start \
                     under it; the next start uses a new op id"
            .to_owned();
        let settled = record.settled(AttemptOutcome::NotCreated {
            status: NotCreated::Failed,
            words: words.clone(),
        });
        self.record_outcome(&settled, StartOutcome::NotStarted { words })
    }

    /// Writes the settled record. If it can't be written, the attempt stays
    /// pending on disk, and the next start reconciles it first.
    fn record_outcome(&self, settled: &StartRecord, started: StartOutcome) -> StartReport {
        let mut gaps = vec![];
        if let Err(e) = self.starts.write(settled) {
            gaps.push(Gap {
                subject: "start record".to_owned(),
                detail: format!(
                    "what came of the start could not be recorded ({e}); the next start reads \
                     its status first"
                ),
            });
        }
        let op_id = settled.last().op_id.clone();
        report(self.request, Some(op_id), started, gaps)
    }
}

/// Whether the `new_thread` report of `op_id` is bound to this start: the
/// binding `new_thread` would give this start's request under that op id
/// (its project, settings, brief and no attachments), field by field.
fn binds(record: &StartRecord, op_id: &OpId, report: &NewThreadReport) -> bool {
    let request = StartRequest::new(
        record.key.clone(),
        record.project_id.clone(),
        record.settings.clone(),
    );
    let own = Binding::new(&request.new_thread(op_id.clone()), attachments_digest(&[]));
    report.project_ref == own.project
        && report.requested.harness == own.harness
        && report.requested.model == own.model
        && report.requested.effort == own.effort
        && report.text_sha256 == own.text_sha256
        && report.attachments_digest == own.attachments_digest
        && report.attachments.is_empty()
}

/// What reconciling a pending attempt found.
enum Reconciled {
    /// The start's outcome, with no call.
    Done(StartReport),
    /// No `new_thread` record has its op id: nothing was sent.
    NothingSent,
    /// Nothing was created: the record, settled, for a new attempt.
    NotCreated(StartRecord),
}

fn report(
    request: &StartRequest,
    op_id: Option<OpId>,
    outcome: StartOutcome,
    gaps: Vec<Gap>,
) -> StartReport {
    StartReport {
        key: request.key.clone(),
        op_id,
        outcome,
        gaps,
    }
}
