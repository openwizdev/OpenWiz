//! #2039 PA1-PA7: the integrated notification journey through the actual
//! installed service. The real dispatch (`fixture-service`, the test-only
//! example) runs with its HTTP API, scheduler, protected store and loopback
//! decisions read. Only these are injected: the fake `gh` and `room-cli`
//! readers on PATH, synthetic state, and a recording delivery boundary. That
//! boundary is the one fixture substitution, for T4's still-unsupported Web Push.
//! Fixture tests prove behaviour on fixtures only, never live or phone delivery.
#![cfg(target_os = "linux")]
use openwiz_core::notifications::model::*;
use openwiz_store::notifications::document;
use serde_json::{Value, json};
use std::fs;
use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::os::unix::fs::{DirBuilderExt, PermissionsExt, symlink};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{
    OnceLock,
    atomic::{AtomicU64, Ordering},
};
use std::time::{Duration, Instant};

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");
const FIXTURES: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/fixtures/notifications/journey"
);
const HOST: &str = "openwiz.example.com";
const GUARDS: &str = "Origin: https://openwiz.example.com\r\nSec-Fetch-Site: same-origin\r\nX-OpenWiz-Send: 1\r\nContent-Type: application/json\r\n";
// Independently computed with Python hashlib over the decisions contract's
// canonical JSON (the e11 fixtures' literals); never by the code under test.
const CURRENT: &str = "941019e2a769a93d10140f9924b4ce021a041c21f74cd72514a9f51306ad1aa4";
const CHANGED: &str = "a362c2cc752a0ee9f7be29ef3fdf2f29286ae9b8a2611e68515ffe8f51a4bf49";
const FIRST: &str = "27234f8810be4235c8b6bf45176f1a1e2c6006e44570a2eff939f0cf11877540";

fn binaries() -> &'static (PathBuf, PathBuf, PathBuf) {
    static BUILT: OnceLock<(PathBuf, PathBuf, PathBuf)> = OnceLock::new();
    BUILT.get_or_init(|| {
        for args in [
            &[
                "build",
                "-p",
                "openwiz-tests",
                "--bin",
                "fake-room-cli",
                "--bin",
                "fake-gh",
            ][..],
            &[
                "build",
                "-p",
                "openwiz-service",
                "--example",
                "fixture-service",
            ],
        ] {
            let out = Command::new(env!("CARGO"))
                .args(args)
                .current_dir(ROOT)
                .output()
                .unwrap();
            assert!(
                out.status.success(),
                "{}",
                String::from_utf8_lossy(&out.stderr)
            );
        }
        let target = Path::new(env!("CARGO_TARGET_TMPDIR"))
            .parent()
            .unwrap()
            .join("debug");
        (
            target.join("examples/fixture-service"),
            target.join("fake-room-cli"),
            target.join("fake-gh"),
        )
    })
}

/// One fenced JSON block of the shared fixture README, by its info string.
fn fixture(name: &str) -> String {
    let readme = fs::read_to_string(Path::new(FIXTURES).join("README.md")).unwrap();
    let start = format!("```json {name}\n");
    let rest = &readme[readme.find(&start).unwrap() + start.len()..];
    rest[..rest.find("\n```").unwrap()].to_owned()
}

/// Places the executable `src` at `dst`, owner-only. A separate `cp` process
/// writes it, so this process never holds a writable descriptor for it: a
/// child another journey forks meanwhile would inherit one until its exec and
/// keep the file busy, so launching it would fail with ETXTBSY (#2799, as
/// #2583, #2559 and #1754).
fn place(src: &Path, dst: &Path) {
    // `cp` would copy into a directory and succeed (#2721, #2731).
    assert!(!dst.is_dir(), "{} is a directory", dst.display());
    let out = Command::new("cp")
        .arg("--")
        .arg(src)
        .arg(dst)
        .stdin(Stdio::null())
        .output()
        .expect("cp runs");
    assert!(
        out.status.success(),
        "cp {}: {}",
        dst.display(),
        String::from_utf8_lossy(&out.stderr)
    );
    fs::set_permissions(dst, fs::Permissions::from_mode(0o700)).unwrap();
}
fn private_dir(path: &Path) {
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(path)
        .unwrap();
}
fn private_file(path: &Path, body: impl AsRef<[u8]>) {
    fs::write(path, body).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
}
fn until(what: &str, mut ready: impl FnMut() -> bool) {
    let limit = Instant::now() + Duration::from_secs(60);
    while !ready() {
        assert!(Instant::now() < limit, "timed out waiting for {what}");
        std::thread::park_timeout(Duration::from_millis(50));
    }
}

/// The decisions comment page and saved grill the fake `gh` answers with.
fn decisions(records: &[Value]) -> Value {
    let rows: Vec<Value> = records
        .iter()
        .enumerate()
        .map(|(i, record)| {
            json!({"id": 1001 + i as u64,
                "body": format!("Synthetic prose.\n```json\n{record}\n```\n"),
                "issue_url": "https://api.github.com/repos/synthetic-owner/synthetic-repo/issues/901",
                "created_at": "1970-01-01T00:00:01Z", "updated_at": "1970-01-01T00:00:02Z"})
        })
        .collect();
    let mut scenario: Value = serde_json::from_str(&fixture("journey-gh")).unwrap();
    let total = rows.len() as u64;
    let page = |size: u64, rows: &[Value]| {
        // GitHub's last-page link, as the e11 fixtures give it, when paged.
        let link = if total > size {
            format!(
                "Link: <https://api.github.com/repos/synthetic-owner/synthetic-repo/issues/comments?per_page={size}&sort=created&direction=desc&page={}>; rel=\"last\"\r\n",
                total.div_ceil(size)
            )
        } else {
            String::new()
        };
        json!({"argv": ["api", "--include",
            format!("repos/{{owner}}/{{repo}}/issues/comments?per_page={size}&sort=created&direction=desc&page=1"),
            "--jq", "[.[] | {id,body,issue_url,created_at,updated_at}]"],
            "stdout": format!("HTTP/2.0 200 OK\r\n{link}\r\n{}", json!(rows))})
    };
    let first: Vec<Value> = rows.iter().take(1).cloned().collect();
    let responses = scenario["responses"].as_array_mut().unwrap();
    responses.push(page(1, &first));
    responses.push(page(100, &rows));
    scenario
}
fn request(id: &str, fingerprint: &str, status: &str) -> Value {
    json!({"schema":"openwiz.decisions.v1", "kind":"grill_round", "id":id,
        "status":status, "fingerprint":fingerprint, "risk":"ordinary",
        "grill_file":"docs/grills/synthetic-choice.md", "round":1,
        "questions":[{"id":"G1", "decides":"Synthetic choice?", "context":"Exact context 合成.", "recommendation":"Keep spaces. "}],
        "answered":[]})
}

struct Running(Child);
impl Drop for Running {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

/// One isolated installed service: state directory, tools and journey files.
struct Service {
    root: PathBuf,
    port: u16,
    running: Option<Running>,
}
impl Service {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "ow-journey-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        for dir in ["service", "build/web", "tools", "journey"] {
            private_dir(&root.join(dir));
        }
        private_file(&root.join("build/web/index.html"), "<html>synthetic</html>");
        let (service, room, gh) = binaries();
        place(service, &root.join("build/openwiz-service"));
        symlink(room, root.join("tools/room-cli")).unwrap();
        symlink(gh, root.join("tools/gh")).unwrap();
        private_file(
            &root.join("tools/fake-room-cli.scenario"),
            Path::new(ROOT)
                .join("tests/fixtures/room-cli-0.43.1/send/scenario.json")
                .to_str()
                .unwrap(),
        );
        private_file(
            &root.join("tools/fake-gh.scenario"),
            root.join("gh-scenario.json").to_str().unwrap(),
        );
        let mut service = Self {
            root,
            port: 0,
            running: None,
        };
        service.set_decisions(&[request("synthetic-current", CURRENT, "open")]);
        service.configure();
        service
    }
    fn configure(&mut self) {
        self.port = TcpListener::bind(("127.0.0.1", 0))
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        let mut config: Value = serde_json::from_str(&fixture("journey-config")).unwrap();
        config["server"]["port"] = json!(self.port);
        private_file(&self.root.join("service/config.json"), config.to_string());
    }
    fn set_decisions(&self, records: &[Value]) {
        private_file(
            &self.root.join("gh-scenario.json"),
            decisions(records).to_string(),
        );
    }
    fn start(&mut self) {
        let mut child = {
            Command::new(self.root.join("build/openwiz-service"))
                .env_clear()
                .env("OPENWIZ_STATE_DIR", &self.root)
                .env("HOME", &self.root)
                .env(
                    "PATH",
                    format!("{}:/usr/bin:/bin", self.root.join("tools").display()),
                )
                .env("OPENWIZ_FIXTURE_PROGRAM", self.root.join("tools/room-cli"))
                .env(
                    "OPENWIZ_FIXTURE_NOTIFICATION_JOURNEY",
                    self.root.join("journey"),
                )
                .current_dir(self.root.join("tools"))
                .stdout(Stdio::null())
                .stderr(fs::File::create(self.root.join("stderr.log")).unwrap())
                .spawn()
                .unwrap()
        };
        let limit = Instant::now() + Duration::from_secs(60);
        while self.pass().is_none() {
            if let Some(code) = child.try_wait().unwrap() {
                panic!("service exited {code}: {}", self.stderr());
            }
            assert!(Instant::now() < limit, "no pass: {}", self.stderr());
            std::thread::park_timeout(Duration::from_millis(50));
        }
        self.running = Some(Running(child));
    }
    fn stderr(&self) -> String {
        fs::read_to_string(self.root.join("stderr.log")).unwrap_or_default()
    }
    fn stop(&mut self) {
        self.running = None;
    }
    /// The service's own published status: last completed pass time.
    fn pass(&self) -> Option<u64> {
        let out = Command::new(self.root.join("build/openwiz-service"))
            .env_clear()
            .env("OPENWIZ_STATE_DIR", &self.root)
            .args(["status", "--json"])
            .output()
            .ok()?;
        let status: Value = serde_json::from_slice(&out.stdout).ok()?;
        status["notifications"]["last_pass_at"]["known"].as_u64()
    }
    /// Waits for a pass that started after this call: everything observed
    /// before it has been read and admitted.
    fn next_pass(&self) {
        let before = self.pass().unwrap_or(0);
        until("a later notification pass", || {
            self.pass().is_some_and(|at| at > before + 1)
        });
    }
    fn http(&self, method: &str, path: &str, body: &str, headers: &str) -> (u16, String) {
        let mut stream = TcpStream::connect(("127.0.0.1", self.port)).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(45)))
            .unwrap();
        write!(
            stream,
            "{method} {path} HTTP/1.1\r\nHost: {HOST}\r\nContent-Length: {}\r\n{headers}\r\n{body}",
            body.len()
        )
        .unwrap();
        stream.shutdown(Shutdown::Write).unwrap();
        let mut raw = String::new();
        stream.read_to_string(&mut raw).unwrap();
        let (head, body) = raw.split_once("\r\n\r\n").unwrap();
        (
            head.split_whitespace().nth(1).unwrap().parse().unwrap(),
            body.to_owned(),
        )
    }
    fn get(&self, path: &str) -> Value {
        // A pass holds the protected store: status answers 503 with
        // Retry-After, and a client reads again. Bounded, like a client.
        let mut tries = 0;
        let (status, body) = loop {
            let (status, body) = self.http("GET", path, "", "");
            tries += 1;
            if status != 503 || tries == 100 {
                break (status, body);
            }
            std::thread::park_timeout(Duration::from_millis(20));
        };
        assert_eq!(status, 200, "{path}: {body}");
        serde_json::from_str(&body).unwrap()
    }
    fn put(&self, path: &str, record: Record) -> (u16, Value) {
        let body = serde_json::to_string(&document(record)).unwrap();
        let (status, body) = self.http("PUT", path, &body, GUARDS);
        (status, serde_json::from_str(&body).unwrap_or(Value::Null))
    }
    fn preferences(&self, op: char, generation: u64, enabled: bool) {
        let (status, body) = self.put(
            "/api/v1/notifications/preferences",
            Record::PreferenceWrite(PreferenceWrite {
                operation_id: OperationId::new(op.to_string().repeat(32)).unwrap(),
                expected_generation: generation,
                enabled,
                categories: Toggles::defaults(),
            }),
        );
        assert_eq!(status, 200, "{body}");
    }
    fn subscribe(&self, op: char, generation: u64) {
        let (status, body) = self.put(
            "/api/v1/notifications/subscription",
            Record::SubscriptionWrite(SubscriptionWrite {
                operation_id: OperationId::new(op.to_string().repeat(32)).unwrap(),
                expected_generation: generation,
                binding_id: Id::new("synthetic-binding").unwrap(),
            }),
        );
        assert_eq!(status, 200, "{body}");
    }
    /// What the recording boundary received, in order.
    fn submissions(&self) -> Vec<Value> {
        fs::read_to_string(self.root.join("journey/submissions.log"))
            .unwrap_or_default()
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect()
    }
    fn tells(&self) -> u64 {
        fs::read_to_string(self.root.join("tools/tell-calls.count"))
            .map(|n| n.trim().parse().unwrap())
            .unwrap_or(0)
    }
    /// Zero CloudRoom starts and zero GitHub writes (merges included).
    fn no_work_effects(&self) {
        let room = fs::read_to_string(self.root.join("tools/invocations.log")).unwrap_or_default();
        assert!(!room.contains("\"spawn\""), "{room}");
        let gh = fs::read_to_string(self.root.join("tools/gh-invocations.log")).unwrap_or_default();
        for write in ["POST", "PATCH", "PUT", "DELETE", "merge"] {
            assert!(!gh.contains(&format!("\"{write}\"")), "{write}: {gh}");
        }
    }
    fn answer(&self, op: &str) -> (u16, Value) {
        // The existing card's message, written independently from the
        // decisions contract (#2272); the journey adds no answer system.
        let text = format!(
            "openwiz decision answer v1\n{}\n\nKeep spaces.",
            json!({"subject":{"repository":"synthetic-owner/synthetic-repo","kind":"pull_request","number":901},
                "comment_id":1001,"request_id":"synthetic-current","request_kind":"grill_round",
                "fingerprint":CURRENT,"grill_file":"docs/grills/synthetic-choice.md","round":1})
        );
        let body = json!({"op_id": op, "mode": "queue", "text": text,
            "resume_paused_queue": false, "accept_possible_duplicate": false})
        .to_string();
        let (status, body) = self.http(
            "POST",
            "/api/v1/sessions/thr_syn_0001/messages",
            &body,
            GUARDS,
        );
        (status, serde_json::from_str(&body).unwrap_or(Value::Null))
    }
}
impl Drop for Service {
    fn drop(&mut self) {
        self.running = None;
        let _ = fs::remove_dir_all(&self.root);
    }
}
fn decision_reference(request: &str, comment: u64, fingerprint: &str) -> Value {
    json!({"decision": {"repository":"synthetic-owner/synthetic-repo",
        "subject":{"kind":"pull_request","number":901},
        "comment_id":comment,"request_id":request,"fingerprint":fingerprint}})
}

/// PA1/PA3/PA4: opt-in, one grouped alert across repeats and restart, its tap
/// opens the exact current item, and only an explicit answer sends, once.
#[test]
fn journey_current_decision_to_recorded_alert_to_bound_item_to_one_answer() {
    let mut service = Service::new();
    service.start();
    // Before opt-in: the current decision is read, and nothing is submitted.
    service.next_pass();
    service.stock_stays_visible_and_unproven();
    assert!(service.submissions().is_empty());
    service.preferences('1', 0, true);
    service.subscribe('2', 0);
    until("one recorded submission", || {
        !service.submissions().is_empty()
    });
    service.next_pass();
    let submissions = service.submissions();
    assert_eq!(submissions.len(), 1, "{submissions:?}");
    let first = &submissions[0];
    assert_eq!(
        first["group"],
        decision_reference("synthetic-current", 1001, CURRENT)
    );
    // The external payload is minimal: a generic title and an opaque token.
    let payload = first["payload"].as_object().unwrap();
    assert_eq!(payload.len(), 2);
    let token = payload["target_token"].as_str().unwrap().to_owned();
    assert!(!first.to_string().contains("Synthetic choice"));
    let status = service.get("/api/v1/notifications/status");
    assert_eq!(status["record"]["status"]["state"], "accepted", "{status}");

    // The tap: the bound reference opens exactly this current item.
    let target = service.get(&format!("/api/v1/notifications/targets/{token}"));
    let result = &target["record"]["target_result"];
    assert_eq!(
        result["reference"],
        decision_reference("synthetic-current", 1001, CURRENT)
    );
    assert_eq!(result["state"], "current", "{target}");
    // Receipt, navigation and preference writes caused no work effect, and
    // the queue view is the same with delivery on.
    service.stock_stays_visible_and_unproven();
    assert_eq!(service.tells(), 0);
    service.no_work_effects();

    // Repeats and one restart keep the one logical alert.
    service.next_pass();
    service.stop();
    service.start();
    service.next_pass();
    assert_eq!(service.submissions().len(), 1);
    let again = service.get(&format!("/api/v1/notifications/targets/{token}"));
    assert_eq!(again["record"]["target_result"]["state"], "current");

    // One explicit answer through the existing guarded send; the same input
    // (double tap or reload reuses its op id) cannot send twice.
    let op = "web-0123456789abcdef0123456789abcdef-q1";
    let (status, body) = service.answer(op);
    assert_eq!(status, 200, "{body}");
    let (status, body) = service.answer(op);
    assert!(status == 200 || status == 409, "{status}: {body}");
    assert_eq!(service.tells(), 1);
    service.no_work_effects();
}

impl Service {
    /// PA6/PA7: the cockpit shows ready stock whatever the notification
    /// choices. Here its fleet reads are unread, so every project's counts stay
    /// unknown and coverage partial: never an empty or fed factory.
    fn stock_stays_visible_and_unproven(&self) {
        let cockpit = self.get("/api/v1/cockpit");
        let stock = &cockpit["ready_stock"];
        assert_eq!(stock["coverage"]["state"], "partial", "{stock}");
        let projects = stock["projects"].as_array().unwrap();
        assert!(!projects.is_empty());
        for project in projects {
            assert!(project["counts"]["unknown"].is_string(), "{project}");
            assert!(project["last_good"].is_null());
        }
    }
    fn reply(&self, reply: Option<&str>) {
        let path = self.root.join("journey/reply");
        match reply {
            Some(reply) => private_file(&path, reply),
            None => {
                let _ = fs::remove_file(path);
            }
        }
    }
    fn unsubscribe(&self, op: char, generation: u64) {
        let body = serde_json::to_string(&document(Record::SubscriptionWrite(SubscriptionWrite {
            operation_id: OperationId::new(op.to_string().repeat(32)).unwrap(),
            expected_generation: generation,
            binding_id: Id::new("synthetic-binding").unwrap(),
        })))
        .unwrap();
        let (status, body) = self.http(
            "DELETE",
            "/api/v1/notifications/subscription",
            &body,
            GUARDS,
        );
        assert_eq!(status, 200, "{body}");
    }
    fn target_state(&self, submission: &Value) -> Value {
        let token = submission["payload"]["target_token"].as_str().unwrap();
        self.get(&format!("/api/v1/notifications/targets/{token}"))["record"]["target_result"]
            ["state"]
            .clone()
    }
    fn status(&self) -> Value {
        self.get("/api/v1/notifications/status")["record"]["status"]["state"].clone()
    }
}

/// PA3/PA4/PA5 and AC2: a lost reply is never retried; a changed proposal is a
/// new alert and its old reference cannot answer; disable and revoke stop
/// submissions; reconnect never replays; refused access changes nothing.
#[test]
fn journey_lost_reply_change_disable_revoke_reconnect_and_refusal_never_retry() {
    let mut service = Service::new();
    service.start();
    service.reply(Some("uncertain"));
    service.preferences('1', 0, true);
    service.subscribe('2', 0);
    until("the first submission", || service.submissions().len() == 1);
    service.next_pass();
    assert_eq!(service.status(), "uncertain");
    service.stop();
    service.start();
    service.next_pass();
    assert_eq!(
        service.submissions().len(),
        1,
        "an uncertain reply is never resent"
    );

    // A changed proposal supersedes the first request: a new logical alert.
    service.reply(None);
    service.set_decisions(&[
        request("synthetic-current", CURRENT, "superseded"),
        request("synthetic-open", CHANGED, "open"),
    ]);
    until("the changed proposal's alert", || {
        service.submissions().len() == 2
    });
    let submissions = service.submissions();
    assert_eq!(
        submissions[1]["group"],
        decision_reference("synthetic-open", 1002, CHANGED)
    );
    assert_ne!(
        submissions[0]["payload"]["target_token"],
        submissions[1]["payload"]["target_token"]
    );
    assert_eq!(service.target_state(&submissions[0]), "resolved");
    assert_eq!(service.target_state(&submissions[1]), "current");

    // Revoked, then disabled: a new current decision is read but not submitted.
    service.unsubscribe('3', 1);
    service.set_decisions(&[
        request("synthetic-current", CURRENT, "superseded"),
        request("synthetic-open", CHANGED, "open"),
        request("synthetic-first", FIRST, "open"),
    ]);
    service.next_pass();
    service.next_pass();
    assert_eq!(service.submissions().len(), 2);
    service.preferences('4', 1, false);
    service.next_pass();
    assert_eq!(service.status(), "off");
    service.preferences('5', 2, true);
    service.next_pass();
    assert_eq!(service.submissions().len(), 2, "still revoked");

    // Refused access: wrong origin or host changes nothing and reveals nothing.
    let write = serde_json::to_string(&document(Record::SubscriptionWrite(SubscriptionWrite {
        operation_id: OperationId::new("6".repeat(32)).unwrap(),
        expected_generation: 2,
        binding_id: Id::new("synthetic-binding").unwrap(),
    })))
    .unwrap();
    let foreign = GUARDS.replace("openwiz.example.com", "foreign.example.com");
    let (status, _) = service.http(
        "PUT",
        "/api/v1/notifications/subscription",
        &write,
        &foreign,
    );
    assert_eq!(status, 403);
    let (status, body) = service.http("PUT", "/api/v1/notifications/subscription", &write, "");
    assert_eq!(status, 403, "{body}");
    service.next_pass();
    assert_eq!(service.submissions().len(), 2);

    // Reconnect: only the still-open, current third request is submitted.
    service.subscribe('7', 2);
    until("the reconnected alert", || service.submissions().len() == 3);
    service.next_pass();
    let submissions = service.submissions();
    assert_eq!(submissions.len(), 3, "no replay of the earlier alerts");
    assert_eq!(
        submissions[2]["group"],
        decision_reference("synthetic-first", 1003, FIRST)
    );
    assert_eq!(service.tells(), 0);
    service.no_work_effects();
}

/// AC2: a crash during submission, and concurrent owner input. The interrupted
/// dispatch stays unresolved and is never resent; concurrent stale writes and
/// a doubled answer each take effect once.
#[test]
fn journey_crash_at_submission_and_concurrent_input_take_effect_once() {
    let mut service = Service::new();
    service.start();
    // Two concurrent enables at the same generation: exactly one applies.
    let results: Vec<u16> = std::thread::scope(|scope| {
        let a = scope.spawn(|| enable(&service, '1'));
        let b = scope.spawn(|| enable(&service, '2'));
        vec![a.join().unwrap(), b.join().unwrap()]
    });
    let mut sorted = results.clone();
    sorted.sort();
    assert_eq!(sorted[0], 200, "{results:?}");
    assert_ne!(sorted[1], 200, "{results:?}");
    service.reply(Some("crash"));
    service.subscribe('3', 0);
    let running = service.running.as_mut().unwrap();
    let limit = Instant::now() + Duration::from_secs(60);
    while running.0.try_wait().unwrap().is_none() {
        assert!(
            Instant::now() < limit,
            "the boundary never crashed the service"
        );
        std::thread::park_timeout(Duration::from_millis(50));
    }
    assert_eq!(service.submissions().len(), 1);
    service.running = None;
    service.reply(None);
    service.start();
    service.next_pass();
    service.next_pass();
    assert_eq!(
        service.submissions().len(),
        1,
        "an interrupted submission is never resent"
    );
    assert_eq!(service.status(), "uncertain");
    let target = service.target_state(&service.submissions()[0]);
    assert_eq!(target, "current");

    // A doubled explicit answer sends once.
    let op = "web-0123456789abcdef0123456789abcdef-q2";
    std::thread::scope(|scope| {
        let a = scope.spawn(|| service.answer(op).0);
        let b = scope.spawn(|| service.answer(op).0);
        let (a, b) = (a.join().unwrap(), b.join().unwrap());
        assert!(a == 200 || b == 200, "{a} {b}");
    });
    assert_eq!(service.tells(), 1);
    service.no_work_effects();
}

fn enable(service: &Service, op: char) -> u16 {
    service
        .put(
            "/api/v1/notifications/preferences",
            Record::PreferenceWrite(PreferenceWrite {
                operation_id: OperationId::new(op.to_string().repeat(32)).unwrap(),
                expected_generation: 0,
                enabled: true,
                categories: Toggles::defaults(),
            }),
        )
        .0
}

/// R1/R2: taps waiting for the protected store (held here as a pass holds it)
/// never take the core-run slots the pass's own decisions recheck needs, and a
/// tap that outlives its request deadline is 504, never a missing 404.
#[test]
fn journey_taps_waiting_on_the_store_never_starve_the_recheck_and_time_out_as_504() {
    let mut service = Service::new();
    service.start();
    service.preferences('1', 0, true);
    service.subscribe('2', 0);
    until("one recorded submission", || {
        service.submissions().len() == 1
    });
    let token = service.submissions()[0]["payload"]["target_token"]
        .as_str()
        .unwrap()
        .to_owned();
    let unknown = "e".repeat(64);
    let store = openwiz_store::notifications::Store::new(&service.root);
    let held = loop {
        match store.lock() {
            Ok(locked) => break locked,
            Err(_) => std::thread::park_timeout(Duration::from_millis(5)),
        }
    };
    std::thread::scope(|scope| {
        let taps: Vec<_> = [&token, &unknown]
            .into_iter()
            .map(|t| {
                let service = &service;
                scope.spawn(move || {
                    let started = Instant::now();
                    let (status, body) =
                        service.http("GET", &format!("/api/v1/notifications/targets/{t}"), "", "");
                    (status, body, started.elapsed())
                })
            })
            .collect();
        // Both taps are now waiting on the held store. The recheck's route
        // still gets a core-run slot at once.
        std::thread::park_timeout(Duration::from_millis(500));
        let started = Instant::now();
        let (status, body) = service.http("GET", "/api/v1/decisions", "", "");
        assert_eq!(status, 200, "{body}");
        assert!(
            started.elapsed() < Duration::from_secs(4),
            "{:?}",
            started.elapsed()
        );
        for tap in taps {
            let (status, body, elapsed) = tap.join().unwrap();
            assert_eq!(status, 504, "{body}");
            assert!(elapsed >= Duration::from_secs(29), "{elapsed:?}");
        }
    });
    drop(held);
    let target = service.get(&format!("/api/v1/notifications/targets/{token}"));
    assert_eq!(target["record"]["target_result"]["state"], "current");
}

/// Descriptors of this process open for writing on `path`'s file, or
/// `None` while no file is there.
fn writers(path: &Path) -> Option<usize> {
    use std::os::unix::fs::MetadataExt;
    let (fds, infos) = (Path::new("/proc/self/fd"), Path::new("/proc/self/fdinfo"));
    let target = fs::metadata(path).ok()?;
    let held = fs::read_dir(fds)
        .unwrap()
        .filter_map(|fd| {
            let fd = fd.ok()?.file_name();
            let file = fs::metadata(fds.join(&fd)).ok()?;
            let info = fs::read_to_string(infos.join(&fd)).ok()?;
            let flags = info.lines().find_map(|l| l.strip_prefix("flags:"))?;
            let access = u32::from_str_radix(flags.trim(), 8).unwrap() & 3;
            (file.dev() == target.dev() && file.ino() == target.ino() && access != 0).then_some(())
        })
        .count();
    Some(held)
}
/// An owner-only scratch directory for one placement proof, removed when
/// dropped, even by a failing proof.
struct Scratch(PathBuf);
impl Scratch {
    fn new(prefix: &str) -> Self {
        let dir = std::env::temp_dir().join(format!("{prefix}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        private_dir(&dir);
        Self(dir)
    }
}
impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

/// #2799 (as #2583, #2559, #1754): each journey places its service binary
/// while the other journeys fork. While a large program is placed, this
/// process must never hold a writer for the placed file: a child forked then
/// would keep it busy, and launching it would fail with ETXTBSY, as #2771's
/// run did at `start`. The placed program then launches.
#[test]
fn placing_the_service_leaves_no_writer_a_concurrent_fork_could_inherit() {
    let dir = Scratch::new("ow-journey-place");
    let source = dir.0.join("source");
    let program = dir.0.join("placed");
    // A runnable script, padded past `exit` so its copy takes a while.
    let mut text = b"#!/bin/sh\nprintf 'PLACED\\n'\nexit 0\n#".to_vec();
    text.resize(64 << 20, b'x');
    private_file(&source, &text);
    drop(text);
    let (mut seen, mut held) = (0, 0);
    std::thread::scope(|scope| {
        let placing = scope.spawn(|| place(&source, &program));
        while !placing.is_finished() {
            if let Some(writers) = writers(&program) {
                seen += 1;
                held = held.max(writers);
            }
        }
        placing.join().unwrap();
    });
    assert!(seen > 0, "the copy was never observed mid-way");
    assert_eq!(
        held, 0,
        "mid-copy, this process held a writable descriptor for the placed \
         executable: a child forked then keeps it busy (ETXTBSY)"
    );
    let run = Command::new(&program).output().unwrap();
    assert!(run.status.success(), "{run:?}");
    assert_eq!(run.stdout, b"PLACED\n");
}
/// #2799 (as #2731, #2721): a directory at the exact destination is refused,
/// instead of `cp` placing the program inside that directory and reporting
/// success.
#[test]
fn placing_onto_a_directory_destination_is_refused() {
    let dir = Scratch::new("ow-journey-place-dir");
    let source = dir.0.join("source");
    private_file(&source, "#!/bin/sh\nexit 0\n");
    let destination = dir.0.join("placed");
    private_dir(&destination);
    let placed = std::panic::catch_unwind(|| place(&source, &destination));
    assert!(
        placed.is_err(),
        "a directory destination was accepted; the program landed inside it"
    );
    assert_eq!(fs::read_dir(&destination).unwrap().count(), 0);
}
