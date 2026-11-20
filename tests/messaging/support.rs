//! Shared helpers for the messaging proofs: the fake `room-cli` set to a
//! send scenario, its call counters and the messaging schema.

#![allow(dead_code)]

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_core::messaging::send::SendRequest;
use openwiz_core::messaging::{Mode, OpId};
use openwiz_core::model::{SessionId, Timestamp};
use openwiz_core::ops::Clock;
use serde_json::{Value, json};

/// The fixed wall-clock time the fixtures are written against.
pub const T0: Timestamp = Timestamp(1_700_000_600_000);

pub struct FixedClock(pub Timestamp);

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

/// A clock that starts at [`T0`] and advances by `step_ms` on every read, so
/// a read and the work worked out right after it (the read age) are separated
/// by exactly `step_ms`. Without it the fixed clock makes every age `0`, and
/// a formatter that printed a constant `0s` would pass (#932, R1).
pub struct AdvancingClock {
    next: std::sync::atomic::AtomicI64,
    step_ms: i64,
}

impl AdvancingClock {
    pub fn new(step_ms: i64) -> Self {
        Self {
            next: std::sync::atomic::AtomicI64::new(T0.0),
            step_ms,
        }
    }
}

impl Clock for AdvancingClock {
    fn now(&self) -> Timestamp {
        let at = self
            .next
            .fetch_add(self.step_ms, std::sync::atomic::Ordering::Relaxed);
        Timestamp(at)
    }

    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}

pub const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/fixtures/room-cli-0.43.1");
pub const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

/// The `send` scenario's directory.
pub fn send_fixtures() -> PathBuf {
    Path::new(FIXTURES).join("send")
}

pub fn op(id: &str) -> OpId {
    OpId::parse(id).unwrap_or_else(|e| panic!("op id {id}: {e}"))
}

pub fn sid(id: &str) -> SessionId {
    SessionId(id.to_owned())
}

/// The budget for a request whose call hangs (#1260): it ends the call, with
/// room for the reads before it.
pub const HANG_BUDGET: Duration = Duration::from_secs(1);

/// Runs `check` on every item, a few at a time (#1260): for rows that share
/// nothing and mostly wait on child processes. A row's panic fails the test.
pub fn at_once<T: Send>(items: Vec<T>, check: impl Fn(T) + Sync) {
    let items = Mutex::new(items.into_iter());
    std::thread::scope(|scope| {
        for _ in 0..4 {
            scope.spawn(|| {
                loop {
                    let next = items.lock().unwrap_or_else(|p| p.into_inner()).next();
                    let Some(item) = next else { break };
                    check(item);
                }
            });
        }
    });
}

/// A request with a short budget, so a hung call ends in seconds.
pub fn request(target: &str, mode: Mode, text: &str, op_id: &str) -> SendRequest {
    let mut r = SendRequest::new(sid(target), text, op(op_id));
    r.mode = mode;
    r.budget = Duration::from_secs(3);
    r
}

/// A tell response for `target` in `mode`, matching any text.
pub fn tell_response(target: &str, mode: &str, rest: Value) -> Value {
    let mut response = json!({
        "argv": ["thread", "tell", target, "--mode", mode, "--json", "--"],
        "any_text": true,
    });
    for (k, v) in rest.as_object().expect("an object") {
        response[k] = v.clone();
    }
    response
}

/// `stdout_file` set to a file of the `send` scenario.
pub fn receipt(file: &str) -> Value {
    json!({ "stdout_file": send_fixtures().join(file).to_str().expect("utf-8") })
}

/// This test run's own directory under the system temp directory,
/// `openwiz-messaging-tests/<process id>-<nanoseconds>`, made once per
/// process. Send records must be outside any repository (M10), so they are
/// not under the target directory; and two suites running at once on one
/// machine must never share them, or one wipes the other's claim mid-test.
/// `private_dir` fails rather than reuse a directory that already exists, so
/// this is never another run's; it is private to its owner, and a planted
/// symlink in place of the shared parent is refused.
pub fn run_root() -> &'static Path {
    static ROOT: OnceLock<PathBuf> = OnceLock::new();
    ROOT.get_or_init(|| {
        let parent = std::env::temp_dir().join("openwiz-messaging-tests");
        crate::dirs::private_dir_all(&parent).expect("create the messaging tests' temp dir");
        let planted = fs::symlink_metadata(&parent).map_or(true, |m| !m.is_dir());
        assert!(!planted, "{parent:?} is not a plain directory");
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |d| d.as_nanos());
        let root = parent.join(format!("{}-{nanos}", std::process::id()));
        crate::dirs::private_dir(&root).expect("create this run's own temp dir");
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).expect("make it private");
        root
    })
}

/// A private fake `room-cli` and send-record directory for one test.
pub struct SendFake {
    pub dir: PathBuf,
    pub state: PathBuf,
}

impl SendFake {
    /// `scenario` is a directory under `tests/fixtures/room-cli-0.43.1/`.
    pub fn new(test: &str, scenario: &str) -> Self {
        let fake = Self::bare(test);
        fake.set_scenario(&Path::new(FIXTURES).join(scenario).join("scenario.json"));
        fake
    }

    /// The `send` scenario with `responses` tried first.
    pub fn with(test: &str, responses: Vec<Value>) -> Self {
        let fake = Self::bare(test);
        fake.override_responses(responses);
        fake
    }

    fn bare(test: &str) -> Self {
        let base = Path::new(env!("CARGO_TARGET_TMPDIR")).join("send-fake");
        let dir = base.join(test);
        // The send record must be outside any repository (M10), and the
        // target directory may be inside this one.
        let state = run_root().join(format!("{test}-state"));
        let _ = fs::remove_dir_all(&dir);
        let _ = fs::remove_dir_all(&state);
        crate::dirs::private_dir_all(&dir).expect("create fake dir");
        std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-room-cli"), dir.join("room-cli"))
            .expect("link fake room-cli");
        fs::write(
            dir.join("fake-room-cli.state"),
            state.to_str().expect("utf-8 path"),
        )
        .expect("write state pointer");
        Self { dir, state }
    }

    fn set_scenario(&self, file: &Path) {
        assert!(file.is_file(), "no scenario {file:?}");
        fs::write(
            self.dir.join("fake-room-cli.scenario"),
            file.to_str().expect("utf-8 path"),
        )
        .expect("write scenario pointer");
    }

    /// Writes this test's own scenario, extending `send`, and points the
    /// fake at it.
    pub fn override_responses(&self, responses: Vec<Value>) {
        self.override_scenario("send", responses);
    }

    /// Writes this test's own scenario, extending `parent`.
    pub fn override_scenario(&self, parent: &str, responses: Vec<Value>) {
        let own = self.dir.join("own");
        crate::dirs::private_dir_all(&own).expect("own scenario dir");
        let parent = Path::new(FIXTURES).join(parent);
        let scenario = json!({
            "scenario": "own",
            "description": "A test's own responses.",
            "extends": parent.to_str().expect("utf-8"),
            "synthetic_assumptions": ["Written by the test."],
            "responses": responses,
        });
        let file = own.join("scenario.json");
        fs::write(&file, serde_json::to_string_pretty(&scenario).unwrap()).expect("scenario");
        self.set_scenario(&file);
    }

    pub fn program(&self) -> PathBuf {
        self.dir.join("room-cli")
    }

    pub fn source(&self) -> CloudRoomSource {
        CloudRoomSource::new(self.program())
    }

    /// Every argument list the fake received, in order.
    pub fn invocations(&self) -> Vec<Vec<String>> {
        let Ok(text) = fs::read_to_string(self.dir.join("invocations.log")) else {
            return vec![];
        };
        text.lines()
            .map(|l| serde_json::from_str(l).expect("log line is JSON"))
            .collect()
    }

    /// Every `thread tell` the fake received.
    pub fn tells(&self) -> Vec<Vec<String>> {
        self.invocations()
            .into_iter()
            .filter(|a| a.get(1).is_some_and(|w| w == "tell"))
            .collect()
    }

    /// The cross-process tell counter: calls the fake accepted.
    pub fn tell_count(&self) -> u64 {
        crate::counter::read(&self.dir.join("tell-calls.count"))
    }
}

/// Best-effort clean-up: a test that passed removes its own send records;
/// one that failed keeps them for diagnosis. Only this run's directory is
/// touched.
impl Drop for SendFake {
    fn drop(&mut self) {
        if !std::thread::panicking() {
            let _ = fs::remove_dir_all(&self.state);
        }
    }
}

/// The Unix permission bits of `path`.
pub fn mode_of(path: &Path) -> u32 {
    fs::metadata(path).expect("metadata").permissions().mode() & 0o777
}

// The schema.

pub const MESSAGING_SCHEMA: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../contracts/messaging.v1.schema.json"
);

pub fn messaging_schema() -> Value {
    serde_json::from_str(&fs::read_to_string(MESSAGING_SCHEMA).expect("schema")).expect("JSON")
}

/// Validates `value` against `$defs/<def>` of the messaging schema.
pub fn validate_def(def: &str, value: &Value) -> Vec<String> {
    let mut schema = messaging_schema();
    schema["$ref"] = json!(format!("#/$defs/{def}"));
    crate::schema::validate(&schema, value)
}

/// Validates a report (the schema's root).
pub fn validate_report(value: &Value) -> Vec<String> {
    crate::schema::validate(&messaging_schema(), value)
}

/// Every string in `value`, recursively.
pub fn strings(value: &Value, out: &mut Vec<String>) {
    match value {
        Value::String(s) => out.push(s.clone()),
        Value::Array(items) => items.iter().for_each(|v| strings(v, out)),
        Value::Object(map) => map.iter().for_each(|(k, v)| {
            out.push(k.clone());
            strings(v, out)
        }),
        _ => {}
    }
}
