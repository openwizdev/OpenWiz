//! LP6 (#549): `GET /api/v1/loops` over HTTP, on a synthetic private checkout
//! and state with explicit trusted context (contracts/web-api.v1.md, "Loops
//! view"). No `room-cli` is ever found: the source points at a missing program.
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_core::{model::Timestamp, ops::Clock};
use openwiz_server::{Config, ReadSources, Server, loops::Switching};
use openwiz_store::loops::{Context, Trust, storage::Storage};
use serde_json::Value;
use std::{
    fs,
    io::{Read, Write},
    net::{Shutdown, TcpStream},
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::{Path, PathBuf},
    process::Command,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
    time::{Duration, Instant},
};

const HOST: &str = "synthetic.openwiz.invalid";
/// 2027-01-15 09:20:00 UTC, synthetic.
const READ: i64 = 1_800_004_800_000;

struct ReadClock;
impl Clock for ReadClock {
    fn now(&self) -> Timestamp {
        Timestamp(READ)
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}
struct Trusted;
impl Trust for Trusted {
    fn verify(&self, _: &Path, repository: &str, project: &str) -> bool {
        repository == "synthetic-owner/synthetic-repo" && project == "prj_syn_example"
    }
    fn actor(&self) -> Option<String> {
        None
    }
}
fn git(root: &Path, args: &[&str]) {
    let out = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "git {args:?}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
}
struct Fixture {
    root: PathBuf,
    context: Context,
}
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "ow-lp6-http-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let (checkout, state) = (root.join("checkout"), root.join("state"));
        for p in [checkout.join("loops"), state.join("service")] {
            fs::DirBuilder::new()
                .recursive(true)
                .mode(0o700)
                .create(p)
                .unwrap();
        }
        fs::write(state.join("service/config.json"), "{}").unwrap();
        fs::set_permissions(
            state.join("service/config.json"),
            fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        git(&checkout, &["init", "-q", "--initial-branch=main"]);
        git(&checkout, &["config", "user.name", "Synthetic Builder"]);
        git(
            &checkout,
            &["config", "user.email", "synthetic@example.invalid"],
        );
        fs::write(
            checkout.join("loops/example.json"),
            include_str!("../../loops/example.json"),
        )
        .unwrap();
        git(&checkout, &["add", "loops"]);
        git(&checkout, &["commit", "-qm", "Synthetic definition"]);
        git(
            &checkout,
            &["update-ref", "refs/remotes/origin/main", "HEAD"],
        );
        git(
            &checkout,
            &[
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/main",
            ],
        );
        let context = Context {
            checkout,
            state,
            repository: "synthetic-owner/synthetic-repo".to_owned(),
            project: "prj_syn_example".to_owned(),
            trust: Some(Arc::new(Trusted)),
        };
        Self { root, context }
    }
    /// What a scheduler pass leaves behind: the private loop state.
    fn passed(&self) {
        drop(Storage::open(&self.context.state).unwrap());
    }
    fn serve(&self, switching: Option<Switching>) -> Server {
        openwiz_server::start_with_loop_switches(
            openwiz_server::bind(0).unwrap(),
            Config {
                allowed_host: Some(HOST.to_owned()),
                ..Config::default()
            },
            Arc::new(CloudRoomSource::new(self.root.join("never-room-cli"))),
            Arc::new(ReadClock),
            Arc::new(|_| {}),
            ReadSources::default(),
            switching,
        )
        .unwrap()
    }
    fn trusted(&self) -> Option<Switching> {
        Some(Switching {
            context: self.context.clone(),
        })
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}
fn request(server: &Server, method: &str, target: &str) -> (u16, String) {
    let mut stream = TcpStream::connect(server.local_addr()).unwrap();
    stream
        .set_read_timeout(Some(Duration::from_secs(15)))
        .unwrap();
    write!(stream, "{method} {target} HTTP/1.1\r\nHost: {HOST}\r\n\r\n").unwrap();
    stream.shutdown(Shutdown::Write).unwrap();
    let mut response = String::new();
    stream.read_to_string(&mut response).unwrap();
    (
        response.split_whitespace().nth(1).unwrap().parse().unwrap(),
        response,
    )
}
fn body(response: &str) -> Value {
    serde_json::from_str(response.split_once("\r\n\r\n").unwrap().1).unwrap()
}

#[test]
fn lp6_get_loops_serves_the_view_from_the_trusted_context() {
    let f = Fixture::new();
    f.passed();
    let server = f.serve(f.trusted());
    let (status, response) = request(&server, "GET", "/api/v1/loops");
    assert_eq!(status, 200, "{response}");
    assert!(
        response.contains("Content-Type: application/json"),
        "{response}"
    );
    let v = body(&response);
    let example: Value = serde_json::from_str(include_str!("../../loops/example.json")).unwrap();
    assert_eq!(v["schema"], "openwiz.loops-view.v1");
    assert_eq!(v["read_at_ms"], READ);
    assert_eq!(v["cost_window_ms"], 86_400_000);
    assert_eq!(v["loops"].as_array().unwrap().len(), 1);
    assert_eq!(v["loops"][0]["id"], example["id"]);
    assert_eq!(v["loops"][0]["last_run"], Value::Null);
}

#[test]
fn lp6_get_loops_refuses_without_context_or_state_never_an_empty_list() {
    let f = Fixture::new();
    let server = f.serve(None);
    let (status, response) = request(&server, "GET", "/api/v1/loops");
    assert_eq!(status, 503, "{response}");
    assert_eq!(body(&response)["error"]["kind"], "loops_unavailable");
    let server = f.serve(f.trusted());
    let (status, response) = request(&server, "GET", "/api/v1/loops");
    assert_eq!(status, 503, "{response}");
    assert_eq!(body(&response)["error"]["kind"], "loops_unavailable");
    assert_eq!(
        body(&response)["error"]["message"],
        "the scheduler has not run a pass yet"
    );
    assert!(
        !f.context.state.join("service/loops").exists(),
        "the read created loop state"
    );
}

pub(crate) fn lp6_get_loops_is_busy_while_a_pass_holds_the_state() {
    let f = Fixture::new();
    f.passed();
    let server = f.serve(f.trusted());
    let pass = Storage::open(&f.context.state).unwrap();
    let started = Instant::now();
    let (status, response) = request(&server, "GET", "/api/v1/loops");
    assert_eq!(status, 503, "{response}");
    assert_eq!(body(&response)["error"]["kind"], "loops_busy");
    assert!(response.contains("Retry-After: 5"), "{response}");
    assert!(
        started.elapsed() >= Duration::from_secs(5),
        "waited the five seconds first"
    );
    drop(pass);
    assert_eq!(request(&server, "GET", "/api/v1/loops").0, 200);
}

#[test]
fn lp6_get_loops_is_get_only_and_takes_no_query() {
    let f = Fixture::new();
    f.passed();
    let server = f.serve(f.trusted());
    let (status, response) = request(&server, "GET", "/api/v1/loops?all=1");
    assert_eq!(status, 400, "{response}");
    assert_eq!(body(&response)["error"]["kind"], "invalid_request");
    for method in ["POST", "PUT", "DELETE"] {
        let (status, response) = request(&server, method, "/api/v1/loops");
        assert_eq!(status, 405, "{method}: {response}");
        assert!(response.contains("Allow: GET"), "{response}");
    }
    let (status, _) = request(&server, "GET", "/api/v1/loops/");
    assert_eq!(status, 404, "a trailing slash is no route");
}
