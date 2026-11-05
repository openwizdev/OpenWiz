//! #535 (0.0.10 T2): the cockpit route's fakes. Every value is synthetic.
//!
//! - GitHub: the fake `gh` on the A4 `fleets/complete` scenario, inlined and
//!   edited per test (labels, failing reads), plus the `repo view` answer the
//!   fleet detail source reads for the repository's owner and name.
//! - CloudRoom inventory: the proofs' scripted source.
//! - CloudRoom fleet reads (the repository's projects, threads and Cloud
//!   branches): an in-process `Agents` that returns the reads a test sets.
//! - The orchestrator target check: the fake `room-cli` behind the send
//!   configuration (`thread show`), as #129 and the decisions route use it.
//!
//! synthetic_assumptions: no shape here is a new observation; each is an
//! existing fixture's or the existing core types'.
#![allow(dead_code)]

use std::fs;
use std::path::Path;
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use openwiz_adapter_github::decisions::GitHubDecisions;
use openwiz_adapter_github::{fleets::GitHubFleets, tickets::Tickets};
use openwiz_core::envelope::GapKind;
use openwiz_core::fleet::agents;
use openwiz_core::fleet::model::{
    Failed, ListOutcome, NonEmpty, Number, Outcome, Project, Read, Thread,
};
use openwiz_core::fleet::tickets::{AgentReads, Agents, Placed, RepositoryAnswer};
use openwiz_core::model::{Fact, ProjectId, SessionId, Timestamp};
use openwiz_core::ops::Clock;
use openwiz_core::source::{
    MachineRecord, OutputRecord, Placement, ProjectRecord, Rows, SessionDetailRecord,
    SessionRecord, SessionScope, SessionSource, SourceError,
};
use openwiz_server::{Config, Decisions, Fleets, Limits, ReadSources};
use serde_json::{Value, json};

use crate::fake::{ScriptedSource, T0, scripted_record};
use crate::http::{Response, TestServer};
use crate::msg::SendFake;
use crate::support::{FIXTURES, FakeGh};

pub const ROUTE: &str = "/api/v1/cockpit";
pub const P1: &str = "prj_syn_0001";
pub const P2: &str = "prj_syn_0002";
pub const TARGET: &str = "thr_syn_0011";
/// The `fleets/complete` scenario's repository.
pub const NAME_WITH_OWNER: &str = "syn-owner/syn-example-repo";
/// The fleet page's existing stale threshold (`apps/web/src/timing.ts`).
pub const STALE_AFTER_MS: i64 = 70_000;

// ---------------------------------------------------------------------
// The schema.

pub fn schema() -> Value {
    serde_json::from_str(include_str!("../../contracts/cockpit.v1.schema.json")).unwrap()
}

/// The body validates against `cockpit.v1.schema.json`.
pub fn check(body: &Value) {
    let schema = schema();
    assert!(crate::pattern::lint(&schema).is_empty());
    let errors = crate::pattern::validate(&schema, body);
    assert!(errors.is_empty(), "{errors:?}\n{body:#}");
}

pub fn gaps(part: &Value) -> Vec<Value> {
    part["coverage"]["gaps"].as_array().unwrap().clone()
}

/// A gap with this project, kind and a detail containing `needle`.
pub fn has_gap(part: &Value, project: Option<&str>, kind: &str, needle: &str) -> bool {
    gaps(part).iter().any(|g| {
        g["project"] == json!(project)
            && g["kind"] == kind
            && g["detail"].as_str().unwrap().contains(needle)
    })
}

pub fn complete() -> Value {
    json!({"state": "complete", "gaps": []})
}

pub fn fresh(at: i64) -> Value {
    json!({"state": "fresh", "snapshot_at": {"known": at}})
}

pub fn stale(at: i64) -> Value {
    json!({"state": "stale", "snapshot_at": {"known": at}})
}

pub fn agent<'a>(body: &'a Value, thread: &str) -> &'a Value {
    body["agents"]["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|a| a["thread"] == thread)
        .unwrap_or_else(|| panic!("no agent {thread}: {body:#}"))
}

pub fn project<'a>(body: &'a Value, id: &str) -> &'a Value {
    body["projects"]["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|p| p["id"] == id)
        .unwrap_or_else(|| panic!("no project {id}: {body:#}"))
}

pub fn threads(body: &Value) -> Vec<String> {
    body["agents"]["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a["thread"].as_str().unwrap().to_owned())
        .collect()
}

pub fn ids(body: &Value) -> Vec<String> {
    body["projects"]["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| p["id"].as_str().unwrap().to_owned())
        .collect()
}

pub fn unknown(fact: &Value) -> bool {
    fact.as_object().is_some_and(|o| {
        o.len() == 1
            && o["unknown"]
                .as_str()
                .is_some_and(|reason| !reason.is_empty())
    })
}

// ---------------------------------------------------------------------
// GitHub.

/// The `fleets/complete` scenario with its listed files inlined, then
/// `edit`ed: `(scenario, issues, prs)`. Adds the fleet detail source's
/// repository answer (A5's `repo view` form).
pub fn gh(name: &str, edit: impl FnOnce(&mut Value, &mut Vec<Value>, &mut Vec<Value>)) -> FakeGh {
    let dir = Path::new(FIXTURES).join("fleets/complete");
    let mut scenario: Value =
        serde_json::from_str(&fs::read_to_string(dir.join("scenario.json")).unwrap()).unwrap();
    let read = |file: &str| -> Vec<Value> {
        serde_json::from_str(&fs::read_to_string(dir.join(file)).unwrap()).unwrap()
    };
    let (mut issues, mut prs) = (read("issues.json"), read("prs.json"));
    // Merged pull requests need the ancestry batch answers A4 writes in its
    // own test; the cockpit's cases need no merge, so they have none.
    prs.retain(|pr| pr["state"] != "MERGED");
    edit(&mut scenario, &mut issues, &mut prs);
    let responses = scenario["responses"].as_array_mut().unwrap();
    for response in responses.iter_mut() {
        let Some(file) = response.get("stdout_file").and_then(Value::as_str) else {
            continue;
        };
        let rows = match file {
            "issues.json" => &issues,
            "prs.json" => &prs,
            other => panic!("unexpected listed file {other}"),
        };
        let text = Value::from(rows.clone()).to_string();
        let object = response.as_object_mut().unwrap();
        object.remove("stdout_file");
        object.insert("stdout".into(), Value::from(text));
    }
    // No verdict comment on any open pull request (A4 writes its own).
    for pr in prs.iter().filter(|pr| pr["state"] == "OPEN") {
        responses.push(json!({
            "argv": ["pr", "view", pr["number"].to_string(), "--json", "comments",
                "--jq", "[.comments[].body]"],
            "stdout": "[]",
        }));
    }
    responses.push(json!({
        "argv": ["repo", "view", "--json", "nameWithOwner,url"],
        "stdout": json!({
            "nameWithOwner": NAME_WITH_OWNER,
            "url": "https://example.invalid/syn-owner/syn-example-repo",
        }).to_string(),
    }));
    let fake = FakeGh::new(name, &dir.join("scenario.json"));
    let path = fake.dir.join("cockpit-scenario.json");
    fs::write(&path, scenario.to_string()).unwrap();
    fake.set_scenario(&path);
    fake
}

/// Drop every Needs you label (`needs-info`, `held`): the fixture then has
/// nothing waiting on the owner.
pub fn no_needs(_: &mut Value, issues: &mut Vec<Value>, _: &mut Vec<Value>) {
    for issue in issues {
        let labels = issue["labels"].as_array_mut().unwrap();
        labels.retain(|l| l["name"] != "needs-info" && l["name"] != "held");
    }
}

pub fn add_label(issues: &mut [Value], number: u64, name: &str) {
    let issue = issues.iter_mut().find(|i| i["number"] == number).unwrap();
    issue["labels"].as_array_mut().unwrap().push(json!({
        "color": "synthetic", "description": "Synthetic label",
        "id": format!("syn-label-{name}"), "name": name,
    }));
}

/// The repository-wide issue list fails, as `fleets/issue-list-fails`.
pub fn issue_list_fails(scenario: &mut Value, _: &mut Vec<Value>, _: &mut Vec<Value>) {
    let responses = scenario["responses"].as_array_mut().unwrap();
    let list = responses
        .iter_mut()
        .find(|r| r["argv"][0] == "issue" && r["argv"][1] == "list")
        .unwrap();
    *list = json!({"argv": list["argv"].clone(), "exit": 1,
        "stderr": "SYNTHETIC_PRIVATE_DIAGNOSTIC: could not list issues\n"});
}

// ---------------------------------------------------------------------
// CloudRoom.

fn ne(text: &str) -> NonEmpty {
    NonEmpty::new(text).unwrap()
}

/// The CloudRoom fleet reads for the repository, as a test sets them.
pub struct Room {
    pub reads: Mutex<AgentReads>,
    /// The `owner/name` each read was asked for.
    pub asked: Mutex<Vec<Option<String>>>,
    /// Runs inside each read, after it is asked.
    pub during: Mutex<Option<Box<dyn Fn() + Send + Sync>>>,
}

impl Room {
    /// The repository's projects, and its threads with each Cloud
    /// thread's branch: `(thread, project, Some(branch))` is a Cloud thread,
    /// `(thread, project, None)` a local one without a branch.
    pub fn new(projects: &[&str], threads: &[(&str, &str, Option<&str>)]) -> Arc<Self> {
        let projects = projects
            .iter()
            .map(|id| Project {
                id: ne(id),
                name: format!("Synthetic fleet project {id}"),
            })
            .collect();
        let listed = threads
            .iter()
            .map(|(thread, project, branch)| match branch {
                Some(_) => Thread::Cloud {
                    thread: ne(thread),
                    project: ne(project),
                },
                None => Thread::Local {
                    thread: ne(thread),
                    project: ne(project),
                    branch: None,
                },
            })
            .collect();
        let workspaces = threads
            .iter()
            .filter_map(|(thread, _, branch)| {
                branch.map(|b| (ne(thread), Outcome::Complete { value: ne(b) }))
            })
            .collect();
        Arc::new(Self {
            reads: Mutex::new(AgentReads {
                version: Outcome::Complete { value: ne("v127") },
                projects: ListOutcome::Complete { value: projects },
                threads: ListOutcome::Complete { value: listed },
                workspaces,
            }),
            asked: Mutex::new(Vec::new()),
            during: Mutex::new(None),
        })
    }

    /// Gives a listed local thread a branch, as the thread list reports it.
    pub fn local_branch(&self, thread: &str, branch: &str) {
        let mut reads = self.reads.lock().unwrap();
        let ListOutcome::Complete { value } = &mut reads.threads else {
            panic!("the thread list is complete");
        };
        for row in value {
            if let Thread::Local {
                thread: t,
                branch: b,
                ..
            } = row
                && t.as_str() == thread
            {
                *b = Some(ne(branch));
            }
        }
    }

    pub fn fail_projects(&self) {
        self.reads.lock().unwrap().projects = ListOutcome::Failed(Failed {
            gap: GapKind::CommandFailed,
            reason: ne("synthetic: the project list failed"),
        });
    }
}

/// Shares the test's handle on the reads with the server.
pub struct RoomAgents(pub Arc<Room>);

impl Agents for RoomAgents {
    fn read(&self, repository: Option<&RepositoryAnswer>, _deadline: Instant) -> AgentReads {
        let room = &self.0;
        room.asked
            .lock()
            .unwrap()
            .push(repository.map(|r| r.name_with_owner.as_str().to_owned()));
        if let Some(during) = room.during.lock().unwrap().as_ref() {
            during();
        }
        room.reads.lock().unwrap().clone()
    }

    fn place(&self, spec: Number, tickets: &[Number], reads: &[Read]) -> Placed {
        let placements = agents::place(spec, reads).expect("a recorded placement");
        Placed {
            builders: tickets.iter().map(|&t| placements.builder(t)).collect(),
            unplaced: placements.unplaced(),
        }
    }
}

/// One inventory session: `status`, its project, Cloud or a local machine
/// host, and a known start time.
pub fn session(n: usize, status: &str, project: &str, host: Option<&str>) -> SessionRecord {
    SessionRecord {
        status: Fact::Known(status.to_owned()),
        project_id: Fact::Known(ProjectId(project.to_owned())),
        placement: Fact::Known(match host {
            None => Placement::Cloud,
            Some(host) => Placement::Host(host.to_owned()),
        }),
        started_at: Fact::Known(Timestamp(T0.0 - 3_600_000 - n as i64)),
        ..scripted_record(n)
    }
}

pub fn projects(ids: &[&str]) -> Vec<ProjectRecord> {
    ids.iter()
        .enumerate()
        .map(|(i, id)| ProjectRecord {
            id: ProjectId((*id).to_owned()),
            name: Fact::Known(format!("Synthetic project {}", i + 1)),
        })
        .collect()
}

pub fn machine() -> MachineRecord {
    MachineRecord {
        id: "mch_syn_0001".to_owned(),
        name: Fact::Known("Synthetic machine one".to_owned()),
    }
}

/// The inventory of `records`, in projects `P1` and `P2`, with one machine.
pub fn inventory(records: Vec<SessionRecord>) -> ScriptedSource {
    ScriptedSource::with_records(records)
        .with_projects(projects(&[P1, P2]))
        .with_machines(vec![machine()])
}

/// A source whose project list fails; everything else is `inner`'s.
pub struct NoProjects(pub ScriptedSource);

impl SessionSource for NoProjects {
    fn name(&self) -> &str {
        self.0.name()
    }
    fn tested_version(&self) -> &str {
        self.0.tested_version()
    }
    fn version(&self, d: Instant) -> Result<String, SourceError> {
        self.0.version(d)
    }
    fn list_sessions(
        &self,
        s: SessionScope,
        d: Instant,
    ) -> Result<Rows<SessionRecord>, SourceError> {
        self.0.list_sessions(s, d)
    }
    fn list_projects(&self, _h: bool, _d: Instant) -> Result<Rows<ProjectRecord>, SourceError> {
        Err(SourceError::CommandFailed {
            exit_code: Some(1),
            detail: "SYNTHETIC_PRIVATE_DIAGNOSTIC".to_owned(),
        })
    }
    fn list_machines(&self, d: Instant) -> Result<Rows<MachineRecord>, SourceError> {
        self.0.list_machines(d)
    }
    fn session_detail(
        &self,
        id: &SessionId,
        d: Instant,
    ) -> Result<SessionDetailRecord, SourceError> {
        self.0.session_detail(id, d)
    }
    fn session_output(&self, id: &SessionId, d: Instant) -> Result<OutputRecord, SourceError> {
        self.0.session_output(id, d)
    }
}

/// A wall clock a test moves; monotonic time is real, as reads wait.
pub struct StepClock(pub AtomicI64);

impl StepClock {
    pub fn at(t: Timestamp) -> Arc<Self> {
        Arc::new(Self(AtomicI64::new(t.0)))
    }
    pub fn advance(&self, ms: i64) {
        self.0.fetch_add(ms, Ordering::SeqCst);
    }
}

impl Clock for StepClock {
    fn now(&self) -> Timestamp {
        Timestamp(self.0.load(Ordering::SeqCst))
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}

/// The target check's fake `room-cli`: the `send` scenario, which shows
/// `TARGET`, with `responses` tried first.
pub fn messenger(name: &str, responses: Vec<Value>) -> SendFake {
    SendFake::with(name, responses)
}

pub fn target_not_found() -> Value {
    json!({"argv": ["thread", "show", TARGET, "--json"], "exit": 1,
        "stderr": "Error: HTTP 404: Thread not found"})
}

pub fn target_fails() -> Value {
    json!({"argv": ["thread", "show", TARGET, "--json"], "exit": 1,
        "stderr": "SYNTHETIC_PRIVATE_DIAGNOSTIC\n"})
}

// ---------------------------------------------------------------------
// The server.

pub struct Setup {
    pub source: Arc<dyn SessionSource>,
    pub gh: FakeGh,
    pub room: Arc<Room>,
    pub messenger: Option<SendFake>,
    /// The server's configured target (`OPENWIZ_ORCHESTRATOR_THREAD_ID`,
    /// as `openwiz-server` reads it at start).
    pub target: Option<Result<Option<String>, ()>>,
    pub clock: Arc<dyn Clock>,
    pub limits: Limits,
    pub fleets: bool,
}

impl Setup {
    pub fn new(source: impl SessionSource + 'static, gh: FakeGh, room: Arc<Room>) -> Self {
        Self {
            source: Arc::new(source),
            gh,
            room,
            messenger: None,
            target: Some(Ok(None)),
            clock: Arc::new(crate::fake::clock()),
            limits: Limits::default(),
            fleets: true,
        }
    }

    pub fn target(mut self, messenger: SendFake, target: Option<&str>) -> Self {
        self.messenger = Some(messenger);
        self.target = Some(Ok(target.map(str::to_owned)));
        self
    }

    pub fn serve(&self) -> TestServer {
        let config = match &self.messenger {
            Some(m) => crate::send_support::send_config(m, self.limits.clone()),
            None => Config {
                limits: self.limits.clone(),
                ..Config::default()
            },
        };
        let fleets = self.fleets.then(|| Fleets {
            list: Arc::new(GitHubFleets::with_program(self.gh.program())),
            detail: Arc::new(Tickets::new(self.gh.program())),
            agents: Arc::new(RoomAgents(self.room.clone())),
        });
        let decisions = self.target.clone().map(|target| Decisions {
            github: GitHubDecisions::with_program(self.gh.program()),
            target,
        });
        let listener = openwiz_server::bind(0).unwrap();
        let log = Arc::new(Mutex::new(Vec::new()));
        let lines = log.clone();
        let server = openwiz_server::start_with_read_sources(
            listener,
            config,
            self.source.clone(),
            self.clock.clone(),
            Arc::new(move |line| lines.lock().unwrap().push(line.to_owned())),
            ReadSources {
                fleets,
                plan: None,
                decisions,
            },
        )
        .unwrap();
        TestServer {
            addr: server.local_addr(),
            server,
            log,
        }
    }
}

/// `GET /api/v1/cockpit`: a schema-valid `200`.
pub fn read(server: &TestServer) -> Value {
    let response: Response = server.get(ROUTE);
    assert_eq!(response.status, 200, "{}", response.text());
    crate::c3_routes::headers(&response);
    let body = response.json();
    check(&body);
    body
}

pub fn wait(ms: u64) {
    std::thread::sleep(Duration::from_millis(ms));
}
