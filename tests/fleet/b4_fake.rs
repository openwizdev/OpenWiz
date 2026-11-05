//! B4's fakes (ClosedWiz#120): a private copy of the repository's fake
//! `room-cli` per test, a scenario the test writes, a private state
//! directory for the new-thread and start records, a fixed clock, and the
//! self-exec child that starts an agent as its own process, so a test can
//! crash it.
//!
//! **The scenario is written by the test**, not committed, as the
//! new-thread proofs do (`tests/new-thread/fake.rs`): a create needs a
//! project with a GitHub remote, which no committed fixture may hold. Every
//! value is synthetic. The committed stdout files of
//! `room-cli-v127/new-thread/` are served by absolute path; the catalogue
//! is that file with two of its synthetic model names changed to the
//! builder and reviewer models these tests start.

#![allow(dead_code)]

use std::fs;
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::sync::{Mutex, OnceLock};
use std::time::Instant;

use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_core::fleet::model::{Commit, Number};
use openwiz_core::fleet::starts::{
    Locked, Repository, StartKey, StartRecord, StartReport, StartRequest, StartStore, start_agent,
};
use openwiz_core::messaging::OpId;
use openwiz_core::messaging::record::StoreError;
use openwiz_core::model::Timestamp;
use openwiz_core::new_thread::Settings;
use openwiz_core::new_thread::outcome::Outcome;
use openwiz_core::new_thread::record::{Claim, NewThreadRecord, NewThreadStore};
use openwiz_core::ops::Clock;
use openwiz_store::{NewThreadFileStore, StartFileStore};
use serde_json::{Value, json};

/// The new-thread fixtures, served by absolute path.
pub const NEW_THREAD: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/fixtures/room-cli-v127/new-thread"
);

/// The 0.43.1 inventory scenario every B4 scenario extends (the thread
/// list a status read of an uncertain start reads).
pub const NORMAL: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/fixtures/room-cli-0.43.1/normal"
);

/// The project every start here is in, and the thread the default create
/// makes (the committed receipt's).
pub const PROJECT: &str = "prj_syn_0001";
pub const THREAD: &str = "thr_syn_0021";

/// A synthetic repository.
pub const REPOSITORY: &str = "synthetic-owner/synthetic-repo-0001";

/// A synthetic head commit.
pub const COMMIT: &str = "0123456789abcdef0123456789abcdef01234567";

/// The milliseconds the fixed clock always reads.
pub const T0: i64 = 1_700_000_000_000;

/// `now` is fixed; the monotonic clock is real, so timeouts work.
pub struct FixedClock;

impl Clock for FixedClock {
    fn now(&self) -> Timestamp {
        Timestamp(T0)
    }

    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}

pub fn repository() -> Repository {
    Repository::parse(REPOSITORY).expect("a repository")
}

pub fn number(n: u64) -> Number {
    Number::new(n).expect("1 or more")
}

pub fn op(id: &str) -> OpId {
    OpId::parse(id).expect("an op id")
}

pub fn settings(harness: &str, model: &str, effort: &str) -> Settings {
    Settings {
        harness: harness.to_owned(),
        model: model.to_owned(),
        effort: effort.to_owned(),
    }
}

/// A builder's settings here: Claude Code, Opus 5.5, XHigh (fleet.md's
/// builder row when #120 was planned). A start passes on whatever settings
/// its caller gives; nothing here depends on these.
pub fn builder_settings() -> Settings {
    settings("claude-code", "claude-opus-5-5", "xhigh")
}

/// A reviewer's settings here: Codex, Sol 6.1, High (fleet.md's reviewer
/// row when #120 was planned).
pub fn reviewer_settings() -> Settings {
    settings("codex", "gpt-6.1-sol", "high")
}

/// The builder of ticket `ticket`, in [`PROJECT`].
pub fn builder(ticket: u64) -> StartRequest {
    StartRequest::new(
        StartKey::builder(repository(), number(ticket)),
        PROJECT,
        builder_settings(),
    )
}

/// The reviewer of pull request `pr` at [`COMMIT`], in [`PROJECT`].
pub fn reviewer(pr: u64) -> StartRequest {
    StartRequest::new(
        StartKey::reviewer(
            repository(),
            number(pr),
            Commit::parse(COMMIT).expect("a commit"),
        ),
        PROJECT,
        reviewer_settings(),
    )
}

/// A committed new-thread stdout file, by absolute path.
pub fn file(name: &str) -> String {
    let path = Path::new(NEW_THREAD).join(name);
    assert!(path.is_file(), "no fixture {path:?}");
    path.to_str().expect("utf-8").to_owned()
}

/// A create that makes [`THREAD`].
pub fn created() -> Value {
    json!({"any_spawn": true, "stdout_file": file("spawn-receipt-created.json"), "creates": true})
}

/// A create CloudRoom refuses with a documented line: nothing is created.
pub fn refused() -> Value {
    json!({
        "any_spawn": true,
        "stderr": "Error: Failed to create thread: HTTP 400: This model is unavailable on Cloud",
        "exit": 1,
    })
}

fn project_row(id: &str, name: &str, remote: Value) -> Value {
    json!({
        "id": id,
        "kind": "standard",
        "name": name,
        "gitRemoteUrl": remote,
        "createdAt": 1_699_100_600_000_i64,
        "updatedAt": 1_699_200_600_000_i64,
        "sources": [],
    })
}

/// The responses every B4 scenario starts from: the version, the project
/// lists (one project, with a synthetic GitHub remote), the catalogue, one
/// create, and the new thread's `thread show`.
fn defaults(catalogue: &Path) -> Vec<Value> {
    let projects = json!([project_row(
        PROJECT,
        "Synthetic project one",
        json!("https://github.com/synthetic-owner/synthetic-repo-0001.git"),
    )]);
    vec![
        json!({"argv": ["--version"], "stdout": "v127\n"}),
        json!({
            "argv": ["project", "list", "--json", "--include-personal"],
            "stdout": projects.to_string(),
        }),
        json!({
            "argv": ["project", "list", "--json", "--include-personal", "--hidden"],
            "stdout": "[]",
        }),
        json!({"argv": ["cloud", "status", "--json"], "stdout_file": catalogue}),
        created(),
        json!({
            "argv": ["thread", "show", THREAD, "--json"],
            "stdout_file": file("thread-show-active.json"),
        }),
    ]
}

/// The committed catalogue, with the first model of `codex` and of
/// `claude-code` renamed to the reviewer and builder models above. Their
/// effort lists are the fixture's.
fn catalogue() -> Value {
    let text = fs::read_to_string(file("cloud-status.json")).expect("the catalogue");
    let mut catalogue: Value = serde_json::from_str(&text).expect("JSON");
    for harness in catalogue["harnesses"].as_array_mut().expect("harnesses") {
        let model = match harness["id"].as_str() {
            Some("codex") => "gpt-6.1-sol",
            Some("claude-code") => "claude-opus-5-5",
            _ => continue,
        };
        harness["models"][0]["model"] = json!(model);
    }
    catalogue
}

/// This test run's own directory under the system temp directory: records
/// must be outside every repository.
fn run_root() -> &'static Path {
    static ROOT: OnceLock<PathBuf> = OnceLock::new();
    ROOT.get_or_init(|| {
        let parent = std::env::temp_dir().join("openwiz-b4-fake");
        private_dir(&parent);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_nanos());
        let root = parent.join(format!("{}-{nanos}", std::process::id()));
        private_dir(&root);
        root
    })
}

fn private_dir(dir: &Path) {
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(dir)
        .unwrap_or_else(|e| panic!("make {}: {e}", dir.display()));
    fs::set_permissions(dir, fs::Permissions::from_mode(0o700)).expect("private");
}

/// A private fake `room-cli` and state directory for one test.
pub struct Fake {
    pub dir: PathBuf,
    pub state: PathBuf,
}

impl Fake {
    /// `responses` tried first, then the defaults, then the 0.43.1
    /// inventory.
    pub fn new(test: &str, responses: Vec<Value>) -> Self {
        let dir = Path::new(env!("CARGO_TARGET_TMPDIR"))
            .join("b4-fake")
            .join(test);
        let state = run_root().join(format!("{test}-state"));
        let _ = fs::remove_dir_all(&dir);
        let _ = fs::remove_dir_all(&state);
        private_dir(&dir);
        std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-room-cli"), dir.join("room-cli"))
            .expect("link the fake");
        fs::write(dir.join("fake-room-cli.state"), state.to_str().unwrap()).expect("state");
        fs::write(dir.join("catalogue.json"), catalogue().to_string()).expect("catalogue");
        let fake = Self { dir, state };
        fake.respond(responses);
        fake
    }

    /// Replaces the scenario: `responses` first, then the defaults.
    pub fn respond(&self, mut responses: Vec<Value>) {
        responses.extend(defaults(&self.dir.join("catalogue.json")));
        let scenario = json!({
            "scenario": "own",
            "description": "A B4 test's own responses.",
            "extends": NORMAL,
            "synthetic_assumptions": ["Written by the test; every value is synthetic."],
            "responses": responses,
        });
        let own = self.dir.join("own");
        private_dir(&own);
        let file = own.join("scenario.json");
        fs::write(&file, serde_json::to_string_pretty(&scenario).unwrap()).expect("scenario");
        fs::write(
            self.dir.join("fake-room-cli.scenario"),
            file.to_str().unwrap(),
        )
        .expect("scenario pointer");
    }

    pub fn program(&self) -> PathBuf {
        self.dir.join("room-cli")
    }

    pub fn source(&self) -> CloudRoomSource {
        CloudRoomSource::new(self.program())
    }

    pub fn threads(&self) -> NewThreadFileStore {
        NewThreadFileStore::open(&self.state).expect("open the new-thread record")
    }

    pub fn starts(&self) -> StartFileStore {
        StartFileStore::open(&self.state).expect("open the start record")
    }

    /// Starts `request` in this process, taking new op ids from `op_ids`
    /// in order (none left: the start fails).
    pub fn start(&self, request: &StartRequest, op_ids: &[&str]) -> StartReport {
        let left = Mutex::new(op_ids.iter().map(|id| op(id)).collect::<Vec<_>>());
        let next = || {
            let mut left = left.lock().unwrap();
            if left.is_empty() {
                Err("the test gave no more op ids".to_owned())
            } else {
                Ok(left.remove(0))
            }
        };
        start_agent(
            &self.source(),
            &self.threads(),
            &self.starts(),
            &FixedClock,
            &next,
            request,
        )
        .expect("a start report")
    }

    /// The start record of `request`, as stored, read back by the store.
    pub fn record(&self, request: &StartRequest) -> Option<StartRecord> {
        self.starts()
            .inspect(&request.key)
            .expect("a readable record")
    }

    /// The start record's file of `request`, as JSON.
    pub fn record_json(&self, request: &StartRequest) -> Value {
        let path = self
            .state
            .join("starts")
            .join(format!("{}.json", request.key.id()));
        let text = fs::read_to_string(&path).unwrap_or_else(|e| panic!("{path:?}: {e}"));
        serde_json::from_str(&text).expect("JSON")
    }

    /// The new-thread record of `op_id`, as JSON, if there is one.
    pub fn new_thread_record(&self, op_id: &str) -> Option<Value> {
        let path = self.state.join("new-threads").join(format!("{op_id}.json"));
        let text = fs::read_to_string(path).ok()?;
        Some(serde_json::from_str(&text).expect("JSON"))
    }

    /// Every argument list the fake received, in order.
    pub fn invocations(&self) -> Vec<Vec<String>> {
        let Ok(text) = fs::read_to_string(self.dir.join("invocations.log")) else {
            return vec![];
        };
        text.lines()
            .map(|l| serde_json::from_str(l).expect("a JSON line"))
            .collect()
    }

    /// Every `thread spawn` the fake received.
    pub fn spawns(&self) -> Vec<Vec<String>> {
        self.invocations()
            .into_iter()
            .filter(|a| a.get(1).is_some_and(|w| w == "spawn"))
            .collect()
    }

    fn counter(&self, name: &str) -> u64 {
        let path = self.dir.join(name);
        let Ok(mut file) = fs::File::open(&path) else {
            return 0;
        };
        file.lock_shared().expect("lock the counter");
        let mut text = String::new();
        std::io::Read::read_to_string(&mut file, &mut text).expect("read the counter");
        if text.is_empty() {
            0
        } else {
            text.parse().expect("a count")
        }
    }

    /// The spawn calls the fake accepted.
    pub fn spawn_count(&self) -> u64 {
        self.counter("spawn-calls.count")
    }

    /// The threads the fake's request-ID table created: the builders.
    pub fn threads_created(&self) -> u64 {
        self.counter("threads-created.count")
    }

    /// The archive calls the fake accepted.
    pub fn archive_count(&self) -> u64 {
        self.counter("archive-calls.count")
    }

    /// Runs [`child_process`] as its own process, starting `request` with
    /// `op_ids`, crashing at `crash`. Returns its output.
    pub fn child(&self, request: &StartRequest, op_ids: &[&str], crash: Crash) -> Output {
        let key = &request.key;
        let spec = json!({
            "program": self.program(),
            "state": self.state,
            "role": key.role().as_str(),
            "number": key.number().get(),
            "op_ids": op_ids,
            "crash": crash.as_str(),
        });
        Command::new(std::env::current_exe().expect("this test binary"))
            .args([
                "--exact",
                "b4_starts::fake::child_process",
                "--nocapture",
                "--test-threads=1",
                "-q",
            ])
            .env(CHILD_ENV, spec.to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .expect("run the child")
    }
}

/// Where the child stops by itself.
#[derive(Clone, Copy, Debug)]
pub enum Crash {
    /// Never by itself (the fake may still kill it).
    Never,
    /// Right after the start record's first write (the attempt, pending),
    /// before `new_thread` runs.
    AfterRecording,
    /// Right after `new_thread` has recorded the thread it created, before
    /// anything else: between the start and its record.
    AfterCreated,
}

impl Crash {
    fn as_str(self) -> &'static str {
        match self {
            Self::Never => "never",
            Self::AfterRecording => "after-recording",
            Self::AfterCreated => "after-created",
        }
    }
}

/// The variable that holds the child's spec.
pub const CHILD_ENV: &str = "OPENWIZ_B4_CHILD";

/// The start record's file store, stopping this process (`abort`) right
/// after its first write.
struct CrashingStore {
    inner: StartFileStore,
    writes: Mutex<u32>,
    crash: String,
}

impl StartStore for CrashingStore {
    fn lock(&self, key: &StartKey) -> Result<Locked, StoreError> {
        self.inner.lock(key)
    }

    fn write(&self, record: &StartRecord) -> Result<(), StoreError> {
        let mut writes = self.writes.lock().unwrap();
        *writes += 1;
        self.inner.write(record)?;
        if self.crash == "after-recording" && *writes == 1 {
            std::process::abort();
        }
        Ok(())
    }

    fn unlock(&self, key: &StartKey) {
        self.inner.unlock(key);
    }

    fn inspect(&self, key: &StartKey) -> Result<Option<StartRecord>, StoreError> {
        self.inner.inspect(key)
    }
}

/// The new-thread record's file store, stopping this process (`abort`)
/// right after it has recorded a created thread.
struct CrashingThreads {
    inner: NewThreadFileStore,
    crash: String,
}

impl NewThreadStore for CrashingThreads {
    fn claim(&self, record: &NewThreadRecord, now: Timestamp) -> Result<Claim, StoreError> {
        self.inner.claim(record, now)
    }

    fn update(&self, record: &NewThreadRecord) -> Result<(), StoreError> {
        self.inner.update(record)?;
        if self.crash == "after-created" && matches!(record.outcome, Some(Outcome::Created { .. }))
        {
            std::process::abort();
        }
        Ok(())
    }

    fn release(&self, op_id: &OpId) {
        self.inner.release(op_id);
    }

    fn inspect(&self, op_id: &OpId, now: Timestamp) -> Result<Option<NewThreadRecord>, StoreError> {
        self.inner.inspect(op_id, now)
    }

    fn withdraw(&self, op_id: &OpId) -> Result<(), StoreError> {
        self.inner.withdraw(op_id)
    }
    fn load(&self, op_id: &OpId) -> Result<Option<NewThreadRecord>, StoreError> {
        self.inner.load(op_id)
    }
}

/// The self-exec child: this test binary, run again as its own process,
/// starts one builder or reviewer the way a tick would, through the file
/// stores and the adapter. It runs only when [`CHILD_ENV`] holds its spec;
/// in a normal test run it returns at once.
#[test]
fn child_process() {
    let Ok(spec) = std::env::var(CHILD_ENV) else {
        return;
    };
    let spec: Value = serde_json::from_str(&spec).expect("the child's spec");
    let state = PathBuf::from(spec["state"].as_str().expect("state"));
    let n = spec["number"].as_u64().expect("number");
    let request = match spec["role"].as_str() {
        Some("builder") => builder(n),
        _ => reviewer(n),
    };
    let left = Mutex::new(
        spec["op_ids"]
            .as_array()
            .expect("op ids")
            .iter()
            .map(|id| op(id.as_str().expect("an op id")))
            .collect::<Vec<_>>(),
    );
    let next = || {
        let mut left = left.lock().unwrap();
        if left.is_empty() {
            Err("the test gave no more op ids".to_owned())
        } else {
            Ok(left.remove(0))
        }
    };
    let starts = CrashingStore {
        inner: StartFileStore::open(&state).expect("open the start record"),
        writes: Mutex::new(0),
        crash: spec["crash"].as_str().expect("crash").to_owned(),
    };
    let source = CloudRoomSource::new(spec["program"].as_str().expect("program"));
    let threads = CrashingThreads {
        inner: NewThreadFileStore::open(&state).expect("open the new-thread record"),
        crash: spec["crash"].as_str().expect("crash").to_owned(),
    };
    let started = start_agent(&source, &threads, &starts, &FixedClock, &next, &request);
    println!(
        "{}",
        serde_json::to_string(&started.map(|r| r.outcome).ok()).unwrap()
    );
}
