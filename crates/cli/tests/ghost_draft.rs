#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../../../tests/support/schema.rs"]
mod schema;

#[path = "../src/ghost/draft.rs"]
mod draft;

use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{Value, json};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace root")
        .to_path_buf()
}

fn scratch(label: &str) -> PathBuf {
    static N: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let n = N.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let dir = std::env::temp_dir().join(format!("ghost-draft-{label}-{}-{n}", std::process::id()));
    fs::create_dir_all(&dir).expect("scratch dir");
    dir
}

fn install_harness(dir: &Path) -> PathBuf {
    let dest = dir.join("harness");
    fs::copy(repo_root().join("tests/fake-harness/draft-harness"), &dest).expect("copy harness");
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(&dest, fs::Permissions::from_mode(0o755)).expect("chmod harness");
    dest
}

fn read_json(rel: &str) -> Value {
    let path = repo_root().join(rel);
    let text = fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("json {}: {e}", path.display()))
}

fn pack_bytes() -> Vec<u8> {
    fs::read(repo_root().join("contracts/fixtures/ghost/context-pack.json")).expect("pack")
}

fn settings(cli: &str) -> Vec<u8> {
    serde_json::to_vec(&json!({"cli": cli})).expect("settings")
}

fn schema_errors(def_name: &str, value: &Value) -> Vec<String> {
    let mut root = read_json("contracts/ghost.v1.schema.json");
    root.as_object_mut().expect("schema object").insert(
        "$ref".to_owned(),
        Value::String(format!("#/$defs/{def_name}")),
    );
    schema::validate(&root, value)
}

struct Engine {
    next: u64,
    to: std::io::PipeWriter,
    lines: mpsc::Receiver<String>,
    serve: Option<thread::JoinHandle<std::io::Result<()>>>,
}

impl Engine {
    fn start(settings_json: &[u8], pack: &[u8]) -> Self {
        let (reader, to) = std::io::pipe().expect("pipe");
        let (from, writer) = std::io::pipe().expect("pipe");
        let settings_json = settings_json.to_vec();
        let pack = pack.to_vec();
        let serve = thread::spawn(move || {
            draft::serve(&settings_json, &pack, BufReader::new(reader), writer)
        });
        let (tx, lines) = mpsc::channel();
        thread::spawn(move || {
            let mut buf = BufReader::new(from);
            loop {
                let mut line = String::new();
                match buf.read_line(&mut line) {
                    Ok(0) | Err(_) => break,
                    Ok(_) => {
                        if tx.send(line).is_err() {
                            break;
                        }
                    }
                }
            }
        });
        Self {
            next: 1,
            to,
            lines,
            serve: Some(serve),
        }
    }

    fn request(&mut self, route: &str, body: &Value) -> Value {
        let id = format!("req-{}", self.next);
        self.next += 1;
        let line = serde_json::to_string(&json!({"id": id, "route": route, "body": body}))
            .expect("request");
        writeln!(self.to, "{line}").expect("write request");
        self.to.flush().expect("flush request");
        let reply = self
            .lines
            .recv_timeout(Duration::from_secs(10))
            .unwrap_or_else(|_| panic!("no stdio reply for {route}"));
        serde_json::from_str(reply.trim()).unwrap_or_else(|e| panic!("reply json {e}: {reply}"))
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        let _ = self.to.flush();
        // Closing the pipe end is the drop of `to` after this function replaces it.
        let _ = std::mem::replace(&mut self.to, std::io::pipe().expect("pipe").1);
        if let Some(handle) = self.serve.take() {
            let _ = handle.join();
        }
    }
}

fn calls(log: &Path) -> Vec<String> {
    fs::read_to_string(log)
        .unwrap_or_default()
        .lines()
        .filter(|line| line.starts_with("call\t"))
        .map(str::to_owned)
        .collect()
}

fn wait_calls(log: &Path, n: usize) -> Vec<String> {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let found = calls(log);
        if found.len() >= n {
            return found;
        }
        if Instant::now() > deadline {
            panic!("harness log stayed at {} call(s), wanted {n}", found.len());
        }
        thread::sleep(Duration::from_millis(20));
    }
}

struct Release(PathBuf);

impl Drop for Release {
    fn drop(&mut self) {
        let _ = fs::write(&self.0, b"");
    }
}

fn asking() -> Value {
    json!({
        "session_id": "thr_syn_demo_01",
        "agent": "orchestrator",
        "turns": [{
            "role": "agent",
            "text": "Approve #42 and take all recs for J1?",
            "asks_user": true
        }]
    })
}

#[test]
fn asking_turn_precomputes_one_harness_call() {
    let dir = scratch("precompute");
    let cli = install_harness(&dir);
    fs::write(dir.join("notes.txt"), b"keep").expect("sentinel");
    let hold = PathBuf::from(format!("{}.hold", cli.display()));
    fs::write(&hold, b"").expect("hold");
    let go = PathBuf::from(format!("{}.go", cli.display()));
    let mut engine = Engine::start(&settings(cli.to_str().expect("utf8")), &pack_bytes());
    let _release = Release(go.clone());
    let turns = engine.request("turns", &asking());
    assert_eq!(
        turns["status"], 200,
        "an asking turn did not queue a precomputed draft"
    );
    assert_eq!(turns["body"]["draft_queued"], true);
    assert!(
        schema_errors("turns_response", &turns["body"]).is_empty(),
        "turns response left the contract: {:?}",
        schema_errors("turns_response", &turns["body"])
    );
    assert!(
        !go.exists(),
        "the harness was released before the turns reply"
    );
    let started = wait_calls(&PathBuf::from(format!("{}.log", cli.display())), 1);
    assert_eq!(
        started.len(),
        1,
        "the asking turn did not start exactly one harness call"
    );
    assert!(
        started[0].contains("\tok\t"),
        "the harness did not receive the pack and the thread: {}",
        started[0]
    );
    assert!(started[0].contains("rev=ctx-syn-0001"), "{}", started[0]);
    assert!(
        started[0].contains("turn=Approve #42 and take all recs for J1?"),
        "{}",
        started[0]
    );
    assert!(
        started[0].contains("\tnet=0"),
        "the harness opened a socket: {}",
        started[0]
    );
    assert!(started[0].starts_with(&format!("call\t{}", cli.display())));

    fs::write(&go, b"").expect("go");
    let draft = engine.request(
        "draft",
        &json!({"session_id": "thr_syn_demo_01", "surface": "openwiz-app"}),
    );
    assert_eq!(draft["status"], 200, "draft was not returned");
    assert_eq!(draft["body"]["draft"]["precomputed"], true);
    assert_eq!(
        draft["body"]["draft"]["text"],
        "J1 all recs, approve #42 and merge."
    );
    assert!(schema_errors("draft_response", &draft["body"]).is_empty());
    let again = engine.request(
        "draft",
        &json!({"session_id": "thr_syn_demo_01", "surface": "cli"}),
    );
    assert_eq!(again["body"]["draft"]["id"], draft["body"]["draft"]["id"]);
    assert_eq!(
        again["body"]["draft"]["text"],
        draft["body"]["draft"]["text"]
    );
    let other = engine.request(
        "draft",
        &json!({"session_id": "thr_syn_other", "surface": "other"}),
    );
    assert_eq!(other["status"], 200);
    assert!(other["body"]["draft"].is_null());
    let log = calls(&PathBuf::from(format!("{}.log", cli.display())));
    assert_eq!(
        log.len(),
        1,
        "a later draft started another harness call: {log:?}"
    );
    assert_eq!(fs::read(dir.join("notes.txt")).expect("sentinel"), b"keep");
}

#[test]
fn a_turn_that_does_not_ask_spawns_nothing() {
    let dir = scratch("quiet");
    let cli = install_harness(&dir);
    let mut engine = Engine::start(&settings(cli.to_str().expect("utf8")), &pack_bytes());
    let mut body = asking();
    body["turns"][0]["asks_user"] = json!(false);
    let turns = engine.request("turns", &body);
    assert_eq!(turns["status"], 200);
    assert_eq!(turns["body"]["draft_queued"], false);
    let draft = engine.request(
        "draft",
        &json!({"session_id": "thr_syn_demo_01", "surface": "openwiz-app"}),
    );
    assert_eq!(draft["status"], 200);
    assert!(draft["body"]["draft"].is_null());
    assert!(calls(&PathBuf::from(format!("{}.log", cli.display()))).is_empty());
}

#[test]
fn harness_failure_is_not_retried_or_sent() {
    let dir = scratch("fail");
    let cli = install_harness(&dir);
    fs::write(format!("{}.fail", cli.display()), b"").expect("fail");
    let mut engine = Engine::start(&settings(cli.to_str().expect("utf8")), &pack_bytes());
    let turns = engine.request("turns", &asking());
    assert_eq!(turns["status"], 200);
    assert_eq!(turns["body"]["draft_queued"], true);
    let _ = wait_calls(&PathBuf::from(format!("{}.log", cli.display())), 1);
    let draft = engine.request(
        "draft",
        &json!({"session_id": "thr_syn_demo_01", "surface": "t3-code"}),
    );
    assert_eq!(draft["status"], 503);
    assert_eq!(draft["body"]["refusal"]["code"], "unavailable");
    let again = engine.request(
        "draft",
        &json!({"session_id": "thr_syn_demo_01", "surface": "bb-plugin"}),
    );
    assert_eq!(again["status"], 503);
    assert_eq!(
        calls(&PathBuf::from(format!("{}.log", cli.display()))).len(),
        1
    );
}

#[test]
fn bad_requests_are_refused_and_do_not_spawn() {
    let dir = scratch("bad");
    let cli = install_harness(&dir);
    let log = PathBuf::from(format!("{}.log", cli.display()));
    let mut engine = Engine::start(&settings(cli.to_str().expect("utf8")), &pack_bytes());
    let cases = [
        (
            r#"{"id":"req-x","id":"req-y","route":"turns","body":{}}"#,
            400,
            "invalid_request",
        ),
        (
            r#"{"id":"req-x","route":"turns","body":{"session_id":"thr_syn_demo_01","agent":"orchestrator","turns":[],"extra":true}}"#,
            400,
            "invalid_request",
        ),
        (
            r#"{"id":"req-x","route":"pair","body":{}}"#,
            404,
            "unknown_route",
        ),
        (
            r#"{"id":"req-x","route":"nope","body":{}}"#,
            400,
            "invalid_request",
        ),
    ];
    for (line, status, code) in cases {
        writeln!(engine.to, "{line}").expect("write");
        engine.to.flush().expect("flush");
        let reply = engine
            .lines
            .recv_timeout(Duration::from_secs(10))
            .expect("reply");
        let value: Value = serde_json::from_str(reply.trim()).expect("json");
        assert_eq!(value["status"], status, "{line} -> {value}");
        assert_eq!(value["body"]["refusal"]["code"], code, "{value}");
    }
    let event = read_json("contracts/fixtures/ghost/messages.json")["feedback_request"].clone();
    let feedback = engine.request("feedback", &event);
    assert_eq!(feedback["status"], 501);
    assert_eq!(feedback["body"]["refusal"]["code"], "not_implemented");
    assert!(
        calls(&log).is_empty(),
        "a refused request spawned the harness"
    );

    let mut relative = Engine::start(&settings("claude"), &pack_bytes());
    let refused = relative.request("turns", &asking());
    assert_eq!(refused["status"], 503);
    assert_eq!(refused["body"]["refusal"]["code"], "unavailable");
    assert!(calls(&log).is_empty());
}

#[test]
fn inner_egress() {
    if std::env::var("GHOST_DRAFT_INNER").ok().as_deref() != Some("egress") {
        return;
    }
    let dir = std::env::current_dir().expect("cwd");
    fs::write(dir.join("notes.txt"), b"keep").expect("sentinel");
    let sockets = || {
        let mut found = Vec::new();
        if let Ok(dir) = fs::read_dir("/proc/self/fd") {
            for entry in dir.flatten() {
                if let Ok(target) = fs::read_link(entry.path()) {
                    let text = target.to_string_lossy().into_owned();
                    if text.starts_with("socket:") {
                        found.push(text);
                    }
                }
            }
        }
        found.sort();
        found
    };
    let before = sockets();
    let cli = install_harness(&dir);
    let mut relative = Engine::start(&settings("claude"), &pack_bytes());
    let refused = relative.request("turns", &asking());
    assert_eq!(
        refused["status"], 503,
        "a relative cli name was not refused"
    );
    drop(relative);
    let mut engine = Engine::start(&settings(cli.to_str().expect("utf8")), &pack_bytes());
    let turns = engine.request("turns", &asking());
    assert_eq!(turns["status"], 200);
    assert_eq!(turns["body"]["draft_queued"], true);
    let draft = engine.request(
        "draft",
        &json!({"session_id": "thr_syn_demo_01", "surface": "openwiz-app"}),
    );
    assert_eq!(draft["status"], 200);
    assert_eq!(draft["body"]["draft"]["precomputed"], true);
    let log = calls(&PathBuf::from(format!("{}.log", cli.display())));
    assert_eq!(log.len(), 1, "{log:?}");
    assert!(log[0].starts_with(&format!("call\t{}", cli.display())));
    assert!(log[0].contains("\tnet=0"), "{}", log[0]);
    assert!(!dir.join("canary-hit").exists(), "another program ran");
    assert_eq!(fs::read(dir.join("notes.txt")).expect("sentinel"), b"keep");
    let names: Vec<_> = fs::read_dir(&dir)
        .expect("dir")
        .map(|e| e.expect("entry").file_name().to_string_lossy().into_owned())
        .collect();
    for name in &names {
        assert!(
            name == "notes.txt"
                || name == "harness"
                || name == "harness.log"
                || name == "canary"
                || name.starts_with("canary-"),
            "unexpected file {name}"
        );
    }
    assert_eq!(sockets(), before, "the engine opened a socket");
    drop(engine);
}

#[test]
fn configured_cli_only_and_nothing_written_or_sent() {
    let dir = scratch("egress");
    let canary = dir.join("canary");
    fs::create_dir(&canary).expect("canary dir");
    for name in [
        "curl", "wget", "gh", "ssh", "nc", "claude", "codex", "python3", "openwiz", "sh",
    ] {
        let path = canary.join(name);
        fs::write(
            &path,
            "#!/bin/sh\nprintf '%s\\n' \"$0\" >> \"$HOME/canary-hit\"\n",
        )
        .expect("canary");
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).expect("chmod");
    }
    let exe = std::env::current_exe().expect("exe");
    let status = Command::new(&exe)
        .arg("--exact")
        .arg("inner_egress")
        .arg("--test-threads=1")
        .arg("--nocapture")
        .current_dir(&dir)
        .env("PATH", &canary)
        .env("HOME", &dir)
        .env("TMPDIR", &dir)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .env("GHOST_DRAFT_INNER", "egress")
        .stdin(Stdio::null())
        .status()
        .expect("spawn inner");
    assert!(status.success(), "inner egress case failed: {status}");
    assert!(
        !dir.join("canary-hit").exists(),
        "a program other than the configured cli ran"
    );
    assert_eq!(fs::read(dir.join("notes.txt")).expect("sentinel"), b"keep");
}
