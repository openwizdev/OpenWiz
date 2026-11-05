//! The CloudRoom reads behind `openwiz fleet <spec>` (OpenWiz 0.0.6, A6,
//! ClosedWiz#114; `contracts/fleet.v1.md`, "Reads"): `room-cli`'s version,
//! the projects whose git remote is this repository, their threads, and
//! each Cloud thread's branch. Each returns its read's outcome in the
//! contract's model types; the read ids, the envelope and the chain itself
//! (`openwiz_core::fleet::agents::place`) are the core's and the caller's.
//!
//! Every call is one [`Invocation`] (`--version`, `project list --json
//! --include-personal`, `thread list --json --include-hidden`, `cloud
//! thread-workspace <id> --json`), run once by the adapter's one runner,
//! with no retry. A read
//! the run's deadline leaves no time for is not made: it is failed with
//! `budget_exhausted`, never left out.
//!
//! **Strict readers** (the contract, "Reading it"; B1's pattern): a
//! document that gives any key twice, at any depth, is refused whole, since
//! a plain `serde_json::Value` would silently keep the last. Each field read
//! is read with its observed type (A1's spike, `room-cli` v132, and v127's
//! capture), or the read fails: never a guess.
//! - `cloud thread-workspace`: a JSON object with **exactly** `branch`,
//!   `head` and `path`, each a string, the branch not empty (A1: "exactly
//!   these keys, strict types, and anything else is unknown").
//! - `project list` and `thread list`: an array of objects. Their many other
//!   keys are not read, as for `new`'s reads of the same lists; each key
//!   that is read must be there, of its type. A row that might be this
//!   repository's but can't be told fails the whole read.
//!
//! **The reason** of a failed read is OpenWiz's own words: never
//! `room-cli`'s output, not even its sanitized first line.

use std::collections::HashSet;
use std::time::Instant;

use openwiz_core::envelope::GapKind;
use openwiz_core::fleet::model::{Failed, ListOutcome, NonEmpty, Outcome, Project, Thread};
use openwiz_core::model::Fact;
use openwiz_core::ops::{NOT_READ_BUDGET, launch_failure_category, version_fact};
use openwiz_core::source::{SessionSource, SourceError};
use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::error::Category;
use serde_json::{Map, Value};

use crate::allowlist::{Invocation, ThreadId};
use crate::source::CloudRoomSource;
use crate::{TESTED_VERSION, process};

/// This repository, as `gh repo view --json nameWithOwner` prints it
/// (`owner/name`): what a project's git remote must name. Only the
/// repository's name is ever printed (the contract's `repository` read), so
/// the owner stays here.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Repository {
    owner_and_name: String,
}

/// The git remotes that name a GitHub repository: the same three as `new`'s
/// project check.
const REMOTE_PREFIXES: &[&str] = &[
    "https://github.com/",
    "ssh://git@github.com/",
    "git@github.com:",
];

impl Repository {
    /// `owner/name`: exactly two parts, each 1 to 100 ASCII letters, digits,
    /// `-`, `_` or `.`, and neither `.` nor `..`. Anything else is `None`.
    pub fn parse(name_with_owner: &str) -> Option<Self> {
        let part = |p: &str| {
            !p.is_empty()
                && p.len() <= 100
                && p != "."
                && p != ".."
                && p.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.'))
        };
        let (owner, name) = name_with_owner.split_once('/')?;
        (part(owner) && part(name)).then(|| Self {
            owner_and_name: name_with_owner.to_owned(),
        })
    }

    /// Whether `remote`, a project's `gitRemoteUrl`, is this repository: one
    /// of [`REMOTE_PREFIXES`], then exactly `owner/name`, with or without
    /// `.git`. GitHub's names are case-insensitive, so the comparison is too
    /// (A1's spike matched them lower-cased); nothing else is forgiven.
    pub fn is_remote(&self, remote: &str) -> bool {
        REMOTE_PREFIXES.iter().any(|prefix| {
            remote.strip_prefix(prefix).is_some_and(|path| {
                let path = path.strip_suffix(".git").unwrap_or(path);
                path.eq_ignore_ascii_case(&self.owner_and_name)
            })
        })
    }
}

/// What each read is called in a reason.
const VERSION_READ: &str = "room-cli --version";
const PROJECTS_READ: &str = "room-cli project list";
const THREADS_READ: &str = "room-cli thread list";
const WORKSPACE_READ: &str = "room-cli cloud thread-workspace";

/// The reason on a thread list not read because the project list wasn't.
pub const NOT_READ_NO_PROJECTS: &str = "not read: the projects couldn't be read";

/// `room-cli --version`: the `version` read whose subject is `cloudroom`.
/// A version that isn't `N.N.N` or `v<N>` fails, its text withheld, as the
/// inventory's does.
pub fn version(source: &CloudRoomSource, deadline: Instant) -> Outcome<NonEmpty> {
    if Instant::now() >= deadline {
        return Outcome::Failed(failed(GapKind::BudgetExhausted, NOT_READ_BUDGET));
    }
    match version_fact(VERSION_READ, TESTED_VERSION, source.version(deadline)).0 {
        Fact::Known(text) => match NonEmpty::new(text) {
            Some(value) => Outcome::Complete { value },
            None => Outcome::Failed(failed(
                GapKind::UntestedVersion,
                format!("{VERSION_READ} printed no version"),
            )),
        },
        Fact::Unknown(reason) => Outcome::Failed(failed(GapKind::UntestedVersion, reason)),
    }
}

/// `room-cli project list --json --include-personal`: the `projects` read,
/// the projects whose git remote is `repository`, in the list's order.
pub fn projects(
    source: &CloudRoomSource,
    repository: &Repository,
    deadline: Instant,
) -> ListOutcome<Project> {
    let invocation = Invocation::ProjectList { hidden: false };
    match run(source, &invocation, PROJECTS_READ, deadline)
        .and_then(|out| parse_projects(&out, repository))
    {
        Ok(value) => ListOutcome::Complete { value },
        Err(why) => ListOutcome::Failed(why),
    }
}

/// `room-cli thread list --json --include-hidden`: the `threads` read, the
/// threads of `projects` that aren't archived, in the list's order. Hidden
/// ones are read too: the contract leaves out only archived ones, and a
/// thread left out could neither be placed nor make a shared branch
/// doubtful (orchestrator, #114, 2026-11-01: "(a)"). When `projects`
/// isn't complete, its threads can't be told, so the list isn't read
/// ([`NOT_READ_NO_PROJECTS`]); when it is complete and empty, they are
/// none, and nothing is run.
pub fn threads(
    source: &CloudRoomSource,
    projects: &ListOutcome<Project>,
    deadline: Instant,
) -> ListOutcome<Thread> {
    let ListOutcome::Complete { value: projects } = projects else {
        return ListOutcome::Failed(failed(GapKind::BudgetExhausted, NOT_READ_NO_PROJECTS));
    };
    if projects.is_empty() {
        return ListOutcome::Complete { value: vec![] };
    }
    let invocation = Invocation::ThreadList {
        include_hidden: true,
        include_archived: false,
    };
    match run(source, &invocation, THREADS_READ, deadline)
        .and_then(|out| parse_threads(&out, projects))
    {
        Ok(value) => ListOutcome::Complete { value },
        Err(why) => ListOutcome::Failed(why),
    }
}

/// `room-cli cloud thread-workspace <thread> --json`: the `workspace` read,
/// one Cloud thread's branch. A thread id that isn't safe to pass as one
/// argument is never passed.
pub fn workspace(
    source: &CloudRoomSource,
    thread: &NonEmpty,
    deadline: Instant,
) -> Outcome<NonEmpty> {
    let Ok(id) = ThreadId::parse(thread.as_str()) else {
        return Outcome::Failed(failed(
            GapKind::Malformed,
            "not read: the thread id is not safe to pass to room-cli",
        ));
    };
    let invocation = Invocation::CloudThreadWorkspace(id);
    match run(source, &invocation, WORKSPACE_READ, deadline).and_then(|out| parse_workspace(&out)) {
        Ok(value) => Outcome::Complete { value },
        Err(why) => Outcome::Failed(why),
    }
}

/// Every CloudRoom read of one `fleet` run, in the order they are made.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Reads {
    pub version: Outcome<NonEmpty>,
    pub projects: ListOutcome<Project>,
    pub threads: ListOutcome<Thread>,
    /// One per Cloud thread of `threads`, in its order.
    pub workspaces: Vec<(NonEmpty, Outcome<NonEmpty>)>,
}

/// Makes every CloudRoom read `fleet` needs, one at a time: the version,
/// the projects, their threads, then each listed Cloud thread's branch.
/// Each read that the deadline leaves no time for is still returned,
/// failed with `budget_exhausted`.
pub fn read(source: &CloudRoomSource, repository: &Repository, deadline: Instant) -> Reads {
    let version = version(source, deadline);
    let projects = projects(source, repository, deadline);
    let threads = threads(source, &projects, deadline);
    let listed: &[Thread] = match &threads {
        ListOutcome::Complete { value } | ListOutcome::Partial { value, .. } => value,
        ListOutcome::Failed(_) => &[],
    };
    let workspaces = listed
        .iter()
        .filter_map(|row| match row {
            Thread::Cloud { thread, .. } => Some(thread),
            Thread::Local { .. } => None,
        })
        .map(|thread| (thread.clone(), workspace(source, thread, deadline)))
        .collect();
    Reads {
        version,
        projects,
        threads,
        workspaces,
    }
}

/// The projects of `project list --json --include-personal`'s stdout whose
/// `gitRemoteUrl` is `repository`. Every row must have `gitRemoteUrl` (a
/// string or null); a kept one, `id` (a non-empty string) and `name` (a
/// string). String ids must be unique across all rows, before filtering.
pub fn parse_projects(stdout: &[u8], repository: &Repository) -> Result<Vec<Project>, Failed> {
    let read = PROJECTS_READ;
    let mut kept: Vec<Project> = Vec::new();
    let mut seen = HashSet::new();
    for row in rows(stdout, read)? {
        let row = object(&row, read, "project")?;
        let remote = match row.get("gitRemoteUrl") {
            Some(Value::Null) => None,
            Some(Value::String(url)) => Some(url.as_str()),
            Some(_) => return Err(wrong(read, "project", "gitRemoteUrl")),
            None => return Err(missing(read, "project", "gitRemoteUrl")),
        };
        let matches = remote.is_some_and(|url| repository.is_remote(url));
        if let Some(id) = row.get("id").and_then(Value::as_str)
            && !seen.insert(id.to_owned())
        {
            let repeated = if matches && kept.iter().any(|p| p.id.as_str() == id) {
                "one of this repository's projects"
            } else {
                "one project"
            };
            return Err(failed(
                GapKind::Malformed,
                format!("{read} listed {repeated} twice"),
            ));
        }
        if !matches {
            continue;
        }
        let id = non_empty(row, read, "project", "id")?;
        let name = string(row, read, "project", "name")?.to_owned();
        kept.push(Project { id, name });
    }
    Ok(kept)
}

/// The threads of `thread list --json --include-hidden`'s stdout in
/// `projects`, not
/// archived. Every row must have `projectId` (a string). A row of
/// `projects` must also have:
/// - `id`: a string that is safe to pass to `room-cli`, listed once,
///   including archived rows;
/// - `archivedAt`: null, or an integer (archived: left out);
/// - `executionTarget` `cloud` (a Cloud thread), or no `executionTarget`
///   and a string `environmentHostId` (a local thread);
/// - for a local thread, `environmentBranchName`: a non-empty string, or
///   null (no branch). An empty one is no form OpenWiz knows, as for
///   `cloud thread-workspace`'s `branch`.
pub fn parse_threads(stdout: &[u8], projects: &[Project]) -> Result<Vec<Thread>, Failed> {
    let read = THREADS_READ;
    let mut kept: Vec<Thread> = Vec::new();
    let mut seen = HashSet::new();
    for row in rows(stdout, read)? {
        let row = object(&row, read, "thread")?;
        let project = string(row, read, "thread", "projectId")?;
        let Some(project) = projects.iter().find(|p| p.id.as_str() == project) else {
            continue;
        };
        let thread = non_empty(row, read, "thread", "id")?;
        if ThreadId::parse(thread.as_str()).is_err() {
            return Err(failed(
                GapKind::Malformed,
                format!("{read}: a thread id is not safe to pass to room-cli"),
            ));
        }
        if !seen.insert(thread.clone()) {
            return Err(failed(
                GapKind::Malformed,
                format!("{read} listed one thread twice"),
            ));
        }
        match row.get("archivedAt") {
            Some(Value::Null) => {}
            Some(Value::Number(at)) if at.is_i64() || at.is_u64() => continue,
            Some(_) => return Err(wrong(read, "thread", "archivedAt")),
            None => return Err(missing(read, "thread", "archivedAt")),
        }
        let project = project.id.clone();
        let row = match row.get("executionTarget") {
            Some(Value::String(target)) if target == "cloud" => Thread::Cloud { thread, project },
            Some(Value::String(_)) => {
                return Err(failed(
                    GapKind::Malformed,
                    format!("{read}: a thread's executionTarget is not one OpenWiz knows"),
                ));
            }
            Some(_) => return Err(wrong(read, "thread", "executionTarget")),
            None => {
                match row.get("environmentHostId") {
                    Some(Value::String(_)) => {}
                    Some(Value::Null) | None => {
                        return Err(failed(
                            GapKind::MissingField,
                            format!(
                                "{read}: a thread has no executionTarget and no environmentHostId"
                            ),
                        ));
                    }
                    Some(_) => return Err(wrong(read, "thread", "environmentHostId")),
                }
                let branch = match row.get("environmentBranchName") {
                    Some(Value::Null) => None,
                    Some(Value::String(_)) => {
                        Some(non_empty(row, read, "thread", "environmentBranchName")?)
                    }
                    Some(_) => return Err(wrong(read, "thread", "environmentBranchName")),
                    None => return Err(missing(read, "thread", "environmentBranchName")),
                };
                Thread::Local {
                    thread,
                    project,
                    branch,
                }
            }
        };
        kept.push(row);
    }
    Ok(kept)
}

/// The branch in `cloud thread-workspace <id> --json`'s stdout: a JSON
/// object with exactly `branch`, `head` and `path`, each a string once, the
/// branch not empty.
pub fn parse_workspace(stdout: &[u8]) -> Result<NonEmpty, Failed> {
    let read = WORKSPACE_READ;
    let document = json(stdout, read)?;
    let fields = object(&document, read, "workspace")?;
    for key in fields.keys() {
        if !matches!(key.as_str(), "branch" | "head" | "path") {
            return Err(failed(
                GapKind::Malformed,
                format!("{read} printed a key OpenWiz doesn't know"),
            ));
        }
    }
    for key in ["head", "path"] {
        string(fields, read, "workspace", key)?;
    }
    non_empty(fields, read, "workspace", "branch")
}

/// Runs one read, if the deadline leaves time to start it.
fn run(
    source: &CloudRoomSource,
    invocation: &Invocation,
    read: &str,
    deadline: Instant,
) -> Result<Vec<u8>, Failed> {
    if Instant::now() >= deadline {
        return Err(failed(GapKind::BudgetExhausted, NOT_READ_BUDGET));
    }
    process::run(source.program(), invocation, deadline).map_err(|error| match error {
        SourceError::TimedOut { after_ms } => failed(
            GapKind::TimedOut,
            format!("{read} timed out after {after_ms} ms"),
        ),
        SourceError::CommandFailed {
            exit_code: Some(code),
            ..
        } => failed(GapKind::CommandFailed, format!("{read} exited {code}")),
        SourceError::CommandFailed {
            exit_code: None, ..
        } => failed(
            GapKind::CommandFailed,
            format!("{read} ended without an exit code"),
        ),
        SourceError::Malformed { .. } => failed(
            GapKind::Malformed,
            format!("{read} printed more than OpenWiz reads"),
        ),
        SourceError::Unavailable { detail } => failed(
            GapKind::CommandFailed,
            match launch_failure_category(&detail) {
                Some(category) => format!("{read} could not be run ({category})"),
                None => format!("{read} could not be run"),
            },
        ),
        SourceError::NotFound { .. } | SourceError::InvalidId { .. } => {
            failed(GapKind::CommandFailed, format!("{read} failed"))
        }
    })
}

fn failed(gap: GapKind, reason: impl Into<String>) -> Failed {
    Failed {
        gap,
        reason: NonEmpty::new(reason).expect("every reason here has words"),
    }
}

fn missing(read: &str, row: &str, key: &str) -> Failed {
    failed(
        GapKind::MissingField,
        format!("{read}: a {row} has no {key}"),
    )
}

fn wrong(read: &str, row: &str, key: &str) -> Failed {
    failed(
        GapKind::WrongType,
        format!("{read}: a {row}'s {key} has an unexpected type"),
    )
}

/// `stdout` as JSON with no key given twice, at any depth.
fn json(stdout: &[u8], read: &str) -> Result<Value, Failed> {
    serde_json::from_slice::<Strict>(stdout)
        .map(|Strict(value)| value)
        .map_err(|e| match e.classify() {
            Category::Data => failed(GapKind::Malformed, format!("{read} gave a key twice")),
            Category::Io | Category::Syntax | Category::Eof => failed(
                GapKind::Malformed,
                format!("{read} printed something that is not JSON"),
            ),
        })
}

/// A JSON array's items.
fn rows(stdout: &[u8], read: &str) -> Result<Vec<Value>, Failed> {
    match json(stdout, read)? {
        Value::Array(rows) => Ok(rows),
        _ => Err(failed(
            GapKind::WrongType,
            format!("{read} printed something that is not a JSON list"),
        )),
    }
}

/// A JSON object: never an array in its place.
fn object<'a>(value: &'a Value, read: &str, row: &str) -> Result<&'a Map<String, Value>, Failed> {
    value.as_object().ok_or_else(|| {
        failed(
            GapKind::WrongType,
            format!("{read}: a {row} is not a JSON object"),
        )
    })
}

fn string<'a>(
    fields: &'a Map<String, Value>,
    read: &str,
    row: &str,
    key: &str,
) -> Result<&'a str, Failed> {
    match fields.get(key) {
        Some(Value::String(text)) => Ok(text),
        Some(_) => Err(wrong(read, row, key)),
        None => Err(missing(read, row, key)),
    }
}

fn non_empty(
    fields: &Map<String, Value>,
    read: &str,
    row: &str,
    key: &str,
) -> Result<NonEmpty, Failed> {
    NonEmpty::new(string(fields, read, row, key)?).ok_or_else(|| {
        failed(
            GapKind::Malformed,
            format!("{read}: a {row}'s {key} is empty"),
        )
    })
}

/// A JSON document read with no key given twice at any depth.
struct Strict(Value);

impl<'de> Deserialize<'de> for Strict {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_any(StrictVisitor).map(Strict)
    }
}

struct StrictVisitor;

impl<'de> Visitor<'de> for StrictVisitor {
    type Value = Value;

    fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("JSON with no key given twice")
    }

    fn visit_bool<E: de::Error>(self, b: bool) -> Result<Value, E> {
        Ok(Value::Bool(b))
    }

    fn visit_i64<E: de::Error>(self, n: i64) -> Result<Value, E> {
        Ok(Value::Number(n.into()))
    }

    fn visit_u64<E: de::Error>(self, n: u64) -> Result<Value, E> {
        Ok(Value::Number(n.into()))
    }

    fn visit_f64<E: de::Error>(self, n: f64) -> Result<Value, E> {
        serde_json::Number::from_f64(n)
            .map(Value::Number)
            .ok_or_else(|| E::custom("not a JSON number"))
    }

    fn visit_str<E: de::Error>(self, s: &str) -> Result<Value, E> {
        Ok(Value::String(s.to_owned()))
    }

    fn visit_string<E: de::Error>(self, s: String) -> Result<Value, E> {
        Ok(Value::String(s))
    }

    fn visit_unit<E: de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Value, A::Error> {
        let mut items = Vec::new();
        while let Some(Strict(item)) = seq.next_element()? {
            items.push(item);
        }
        Ok(Value::Array(items))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Value, A::Error> {
        let mut fields = Map::new();
        while let Some(key) = map.next_key::<String>()? {
            if fields.contains_key(&key) {
                return Err(de::Error::custom("a key given twice"));
            }
            let Strict(value) = map.next_value()?;
            fields.insert(key, value);
        }
        Ok(Value::Object(fields))
    }
}
