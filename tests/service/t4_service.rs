//! C2: the real service dispatch, isolated fake bundle, real HTTP and local IPC.
#![cfg(target_os = "linux")]
#[path = "../fleet/schema.rs"]
mod schema;

use serde_json::{Value, json};
use std::fs::{self, DirBuilder};
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::os::unix::fs::{DirBuilderExt, PermissionsExt, symlink};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{
    Mutex, OnceLock,
    atomic::{AtomicU64, Ordering},
};
use std::time::{Duration, Instant};

// Copying an executable and forking share a lock: a child cannot inherit
// a still-writable copy descriptor before its exec (ETXTBSY on Linux).
static EXECUTION: Mutex<()> = Mutex::new(());

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../..");
const CONTRACT: &str = include_str!("../../contracts/service.v1.md");

fn binaries() -> (PathBuf, PathBuf) {
    static BUILT: OnceLock<(PathBuf, PathBuf)> = OnceLock::new();
    BUILT
        .get_or_init(|| {
            for args in [
                vec!["build", "-p", "openwiz-tests", "--bin", "fake-room-cli"],
                vec![
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
            )
        })
        .clone()
}

fn private_dir(path: &Path) {
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(path)
        .unwrap();
}
fn private_file(path: &Path, body: impl AsRef<[u8]>) {
    fs::write(path, body).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
}
fn config(port: u16) -> Value {
    let mut value: Value = CONTRACT
        .lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .find(|v| v["schema"] == "openwiz.service-config.v1")
        .unwrap();
    value["server"]["port"] = json!(port);
    value
}

struct Fixture {
    root: PathBuf,
    port: u16,
}
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "ow-t4-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        private_dir(&root.join("service"));
        private_dir(&root.join("build/web"));
        private_dir(&root.join("tools"));
        private_file(
            &root.join("build/web/index.html"),
            "<html>synthetic service page</html>",
        );
        let (service, fake) = binaries();
        {
            let _guard = EXECUTION.lock().unwrap();
            fs::copy(service, root.join("build/openwiz-service")).unwrap();
            fs::set_permissions(
                root.join("build/openwiz-service"),
                fs::Permissions::from_mode(0o700),
            )
            .unwrap();
        }
        symlink(fake, root.join("tools/room-cli")).unwrap();
        private_file(
            &root.join("tools/fake-room-cli.scenario"),
            Path::new(ROOT)
                .join("tests/fixtures/room-cli-0.43.1/normal/scenario.json")
                .to_str()
                .unwrap(),
        );
        let port = TcpListener::bind(("127.0.0.1", 0))
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        private_file(&root.join("service/config.json"), config(port).to_string());
        Self { root, port }
    }
    fn command(&self) -> Command {
        let mut cmd = Command::new(self.root.join("build/openwiz-service"));
        let environment = self.root.join("runtime-environment.json");
        if environment.exists() {
            let value: Value = serde_json::from_slice(&fs::read(environment).unwrap()).unwrap();
            cmd.env_clear();
            for (key, value) in value.as_object().unwrap() {
                cmd.env(key, value.as_str().unwrap());
            }
            cmd.current_dir(self.root.join("foreign-checkout"));
        }
        cmd.env("OPENWIZ_STATE_DIR", &self.root)
            .env("OPENWIZ_ORCHESTRATOR_THREAD_ID", "thr_syn_0002")
            .env(
                "PATH",
                std::env::join_paths(std::iter::once(self.root.join("tools")).chain(
                    std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default()),
                ))
                .unwrap(),
            )
            .env("OPENWIZ_FIXTURE_PROGRAM", self.root.join("tools/room-cli"))
            .env(
                "OPENWIZ_FIXTURE_JOB_LOG",
                self.root.join("synthetic-job.log"),
            );
        cmd
    }
    fn output(&self, args: &[&str]) -> std::process::Output {
        let _guard = EXECUTION.lock().unwrap();
        if args.first() == Some(&"status") {
            Command::new(env!("CARGO_BIN_EXE_openwiz-service"))
                .env("OPENWIZ_STATE_DIR", &self.root)
                .args(args)
                .output()
                .unwrap()
        } else {
            self.command().args(args).output().unwrap()
        }
    }
    fn start(&mut self) -> Running {
        'attempt: for attempt in 0..5 {
            let mut child = Running({
                let _guard = EXECUTION.lock().unwrap();
                self.command()
                    .stdout(Stdio::null())
                    .stderr(fs::File::create(self.root.join("stderr.log")).unwrap())
                    .spawn()
                    .unwrap()
            });
            let until = Instant::now() + Duration::from_secs(15);
            loop {
                if let Some(code) = child.0.try_wait().unwrap() {
                    let stderr = fs::read_to_string(self.root.join("stderr.log")).unwrap();
                    if attempt < 4
                        && code.code() == Some(1)
                        && stderr == "openwiz-service: cannot bind the configured loopback port\n"
                    {
                        self.port = TcpListener::bind(("127.0.0.1", 0))
                            .unwrap()
                            .local_addr()
                            .unwrap()
                            .port();
                        let path = self.root.join("service/config.json");
                        let mut value: Value =
                            serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
                        value["server"]["port"] = json!(self.port);
                        private_file(&path, value.to_string());
                        continue 'attempt;
                    }
                    panic!(
                        "service exited {code}: {}",
                        fs::read_to_string(self.root.join("stderr.log")).unwrap()
                    );
                }
                if self.root.join("service/status.sock").exists() {
                    let out = self.output(&["status", "--json"]);
                    if out.status.success() {
                        return child;
                    }
                }
                assert!(Instant::now() < until, "service never became ready");
                std::thread::sleep(Duration::from_millis(10));
            }
        }
        unreachable!("startup returns or fails on the fifth attempt")
    }
    fn status(&self) -> Value {
        let out = self.output(&["status", "--json"]);
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        serde_json::from_slice(&out.stdout).unwrap()
    }
    fn request(&self, method: &str, path: &str, host: &str) -> (u16, String) {
        let mut stream = TcpStream::connect(("127.0.0.1", self.port)).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(10)))
            .unwrap();
        write!(
            stream,
            "{method} {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
        )
        .unwrap();
        let mut out = String::new();
        stream.read_to_string(&mut out).unwrap();
        (
            out.split_whitespace().nth(1).unwrap().parse().unwrap(),
            out.split_once("\r\n\r\n").unwrap().1.to_owned(),
        )
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.root).unwrap();
    }
}
struct Running(Child);
impl Drop for Running {
    fn drop(&mut self) {
        let _ = self.0.kill();
        self.0.wait().unwrap();
    }
}

#[path = "install_engine_commands.rs"]
mod install_engine_commands;
#[path = "install_engine_reads.rs"]
mod install_engine_reads;

#[test]
fn embedded_api_page_status_and_single_owner_use_the_real_dispatch() {
    let mut f = Fixture::new();
    let original_config = fs::read(f.root.join("service/config.json")).unwrap();
    let absent = f.output(&["status", "--json"]);
    assert_eq!(absent.status.code(), Some(1));
    assert!(absent.stdout.is_empty());
    assert_eq!(fs::read_dir(f.root.join("service")).unwrap().count(), 1);
    assert_eq!(
        openwiz_service::runtime::status(&f.root).unwrap_err(),
        "service is not answering"
    );
    // Status must retain safe metadata diagnostics without exposing config
    // contents or repairing the owner's file. Exercise the composed boundary.
    let config_path = f.root.join("service/config.json");
    private_file(&config_path, "synthetic-config-secret");
    fs::set_permissions(&config_path, fs::Permissions::from_mode(0o644)).unwrap();
    assert_eq!(
        openwiz_service::runtime::status(&f.root).unwrap_err(),
        "service/config.json: must not be open to group or others"
    );
    for args in [&["status"][..], &["status", "--json"][..]] {
        let out = f.output(args);
        assert_eq!(out.status.code(), Some(1));
        assert!(out.stdout.is_empty());
        assert_eq!(
            String::from_utf8(out.stderr).unwrap(),
            "openwiz-service: service/config.json: must not be open to group or others\n"
        );
    }
    assert_eq!(fs::read(&config_path).unwrap(), b"synthetic-config-secret");
    use std::os::unix::fs::MetadataExt;
    assert_eq!(fs::metadata(&config_path).unwrap().mode() & 0o777, 0o644);
    assert_eq!(fs::read_dir(f.root.join("service")).unwrap().count(), 1);
    private_file(&config_path, &original_config);
    // A local runtime-path refusal is safe too; a response from a socket is
    // still untrusted and must retain the generic unavailable diagnostic.
    let socket_path = f.root.join("service/status.sock");
    let listener = std::os::unix::net::UnixListener::bind(&socket_path).unwrap();
    fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o644)).unwrap();
    assert_eq!(
        openwiz_service::runtime::status(&f.root).unwrap_err(),
        "service/status.sock: must be a private socket owned by the service's user"
    );
    fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o600)).unwrap();
    let response = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .write_all(b"{\"synthetic-status-secret\":true}")
            .unwrap();
    });
    assert_eq!(
        openwiz_service::runtime::status(&f.root).unwrap_err(),
        "service is not answering"
    );
    response.join().unwrap();
    fs::remove_file(&socket_path).unwrap();
    let running = f.start();
    // Account only for the fixture's port rewrite, retaining the comparison
    // against every other field of the pre-start config.
    let mut original_config: Value = serde_json::from_slice(&original_config).unwrap();
    original_config["server"]["port"] = json!(f.port);
    let original_config = original_config.to_string().into_bytes();
    let status = f.status();
    let contract: Value =
        serde_json::from_str(include_str!("../../contracts/service.v1.schema.json")).unwrap();
    assert_eq!(schema::validate(&contract, &status), Vec::<String>::new());
    assert_eq!(status["schema"], "openwiz.service-status.v1");
    assert_eq!(status["tick"], json!({"running":null,"last_ended":null}));
    assert_eq!(status["server"]["port"], f.port);
    assert!(status["server"]["running"]["since"].as_u64().is_some());
    assert_eq!(status["last_pass"], Value::Null);
    assert_eq!(status["incidents"], json!([]));
    assert_eq!(status["update"], Value::Null);
    let build = status["service"]["build"].as_str().unwrap();
    let expected = {
        let _guard = EXECUTION.lock().unwrap();
        Command::new("git")
            .args(["rev-parse", "HEAD"])
            .current_dir(ROOT)
            .output()
            .unwrap()
    };
    assert!(expected.status.success());
    assert_eq!(build, String::from_utf8(expected.stdout).unwrap().trim());
    assert_eq!(build.len(), 40);
    assert!(
        build
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    );
    assert!(status["service"]["since"].as_u64().unwrap() <= status["at"].as_u64().unwrap());
    let state = fs::read(f.root.join("service/state.json")).unwrap();
    let plain = f.output(&["status"]);
    assert!(plain.status.success());
    assert!(!plain.stdout.is_empty());
    assert_eq!(fs::read(f.root.join("service/state.json")).unwrap(), state);
    assert_eq!(
        fs::read(f.root.join("service/config.json")).unwrap(),
        original_config
    );
    let host = format!("127.0.0.1:{}", f.port);
    let job = f.root.join("synthetic-job.log");
    let until = Instant::now() + Duration::from_secs(10);
    while fs::read(&job).ok().as_deref() != Some(b"synthetic job started\n".as_slice()) {
        assert!(
            Instant::now() < until,
            "registered fixture job never started"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(fs::read(&job).unwrap(), b"synthetic job started\n");
    // The job holds its worker indefinitely; HTTP and status must still answer.
    assert_eq!(f.status()["service"]["since"], status["service"]["since"]);
    let (code, health) = f.request("GET", "/api/v1/health", &host);
    assert_eq!(code, 200);
    assert!(health.contains("openwiz-server"));
    assert_eq!(
        f.request("GET", "/api/v1/health", "openwiz.example.com").0,
        200,
        "the configured allowed host must reach the embedded API"
    );
    assert_eq!(
        f.request("GET", "/", &host),
        (200, "<html>synthetic service page</html>".to_owned())
    );
    assert_eq!(
        f.request("GET", "/api/v1/health", "unapproved.example.com")
            .0,
        421
    );
    assert_eq!(
        f.request("POST", "/api/v1/sessions/thr_syn_0001/messages", &host)
            .0,
        421
    );
    let (code, inventory) = f.request("GET", "/api/v1/inventory", &host);
    assert_eq!(code, 200);
    assert_eq!(
        serde_json::from_str::<Value>(&inventory).unwrap()["schema"],
        "openwiz.inventory.v1"
    );
    let calls = fs::read_to_string(f.root.join("tools/invocations.log")).unwrap();
    let mut calls: Vec<Value> = calls
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    calls.sort_by_key(Value::to_string);
    let mut expected = vec![
        json!(["--version"]),
        json!(["machine", "list", "--json"]),
        json!(["project", "list", "--json", "--include-personal"]),
        json!(["thread", "list", "--json"]),
    ];
    expected.sort_by_key(Value::to_string);
    assert_eq!(calls, expected);
    let duplicate = f.output(&[]);
    assert_eq!(duplicate.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&duplicate.stderr).contains("already running"));
    assert_eq!(f.status()["service"]["since"], status["service"]["since"]);
    drop(running);
    let out = f.output(&["status", "--json"]);
    assert_eq!(out.status.code(), Some(1));
    assert!(out.stdout.is_empty());
    assert!(String::from_utf8_lossy(&out.stderr).contains("service is not answering"));
    assert_eq!(fs::read(f.root.join("service/state.json")).unwrap(), state);
    // A killed process leaves its socket behind; the next owner recovers it.
    let restarted = f.start();
    assert_eq!(
        f.status()["tick"],
        json!({"running":null,"last_ended":null})
    );
    drop(restarted);
}

#[test]
fn startup_recovers_a_stopped_tick_and_an_interrupted_try_without_dispatch() {
    let mut f = Fixture::new();
    let state = json!({"schema":"openwiz.service-state.v1","next_incident":2,
      "tick":{"running":{"started_at":1000},"last_ended":null},"last_pass":null,"update":null,
      "incidents":[{"id":"i1","check":"server","opened_at":900,"broken":{"state":"broken","what":"refused"},"healthy_since":null,
      "tries":{"first":{"at":900,"outcome":null,"comment":null},"second":null},"needs_you":null}]});
    private_file(&f.root.join("service/state.json"), state.to_string());
    let running = f.start();
    let status = f.status();
    assert_eq!(status["tick"]["running"], Value::Null);
    assert_eq!(status["tick"]["last_ended"]["started_at"], 1000);
    assert_eq!(status["tick"]["last_ended"]["how"], "stopped");
    assert!(status["tick"]["last_ended"]["ended_at"].as_u64().unwrap() >= 1000);
    assert_eq!(
        status["incidents"][0]["tries"]["first"]["outcome"],
        json!({"state":"interrupted"})
    );
    assert!(!f.root.join("tools/invocations.log").exists());
    use std::os::unix::fs::MetadataExt;
    assert_eq!(
        fs::metadata(f.root.join("service/state.json"))
            .unwrap()
            .mode()
            & 0o777,
        0o600
    );
    assert_eq!(
        fs::metadata(f.root.join("service/status.sock"))
            .unwrap()
            .mode()
            & 0o777,
        0o600
    );
    drop(running);
}

#[test]
fn malformed_config_state_and_help_never_start_or_read_a_tool() {
    let f = Fixture::new();
    let help = {
        let _guard = EXECUTION.lock().unwrap();
        Command::new(env!("CARGO_BIN_EXE_openwiz-service"))
            .arg("--help")
            .env("OPENWIZ_STATE_DIR", f.root.join("absent"))
            .output()
            .unwrap()
    };
    assert!(help.status.success());
    assert!(String::from_utf8_lossy(&help.stdout).contains("status"));
    for bad in ["localhost", "127.0.0.1", "bad/host"] {
        let mut value = config(f.port);
        value["server"]["allowed_host"] = json!(bad);
        private_file(&f.root.join("service/config.json"), value.to_string());
        let out = f.output(&[]);
        assert_eq!(out.status.code(), Some(1));
        assert!(String::from_utf8_lossy(&out.stderr).contains("server.allowed_host"));
        assert!(!f.root.join("service/status.sock").exists());
        assert!(!f.root.join("service/state.json").exists());
    }
    private_file(
        &f.root.join("service/config.json"),
        config(f.port).to_string(),
    );
    private_file(
        &f.root.join("service/state.json"),
        "{\"synthetic-secret\":true}",
    );
    let out = f.output(&[]);
    assert_eq!(out.status.code(), Some(1));
    let error = String::from_utf8_lossy(&out.stderr);
    assert!(error.contains("service/state.json"));
    assert!(!error.contains("synthetic-secret"));
    assert!(!f.root.join("tools/invocations.log").exists());
}

#[test]
fn startup_retries_when_the_selected_port_is_taken() {
    let mut f = Fixture::new();
    let occupied = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    f.port = occupied.local_addr().unwrap().port();
    let mut expected_config = config(f.port);
    expected_config["health"]["every_s"] = json!(67);
    private_file(
        &f.root.join("service/config.json"),
        expected_config.to_string(),
    );
    let running = f.start();
    assert_ne!(f.port, occupied.local_addr().unwrap().port());
    assert_eq!(f.status()["server"]["port"], f.port);
    expected_config["server"]["port"] = json!(f.port);
    assert_eq!(
        fs::read(f.root.join("service/config.json")).unwrap(),
        expected_config.to_string().into_bytes()
    );
    let host = format!("127.0.0.1:{}", f.port);
    assert_eq!(f.request("GET", "/api/v1/health", &host).0, 200);
    drop(running);
}

fn stub_service(f: &Fixture, stderr: &str, exit: u8) {
    let _guard = EXECUTION.lock().unwrap();
    private_file(
        &f.root.join("build/openwiz-service"),
        format!(
            "#!/bin/sh\nprintf 'attempt\\n' >> \"$OPENWIZ_STATE_DIR/attempts.log\"\nprintf '%s\\n' '{stderr}' >&2\nexit {exit}\n"
        ),
    );
    fs::set_permissions(
        f.root.join("build/openwiz-service"),
        fs::Permissions::from_mode(0o700),
    )
    .unwrap();
}

fn startup_failure(f: &mut Fixture) -> String {
    let panic = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| f.start()))
        .err()
        .expect("startup unexpectedly succeeded");
    if let Some(message) = panic.downcast_ref::<String>() {
        message.clone()
    } else {
        panic.downcast_ref::<&str>().unwrap().to_string()
    }
}

#[test]
fn startup_stops_after_five_bind_refusals_with_the_last_stderr() {
    let mut f = Fixture::new();
    let refusal = "openwiz-service: cannot bind the configured loopback port";
    stub_service(&f, refusal, 1);
    assert_eq!(
        startup_failure(&mut f),
        format!("service exited exit status: 1: {refusal}\n")
    );
    assert_eq!(
        fs::read_to_string(f.root.join("attempts.log")).unwrap(),
        "attempt\n".repeat(5)
    );
}

#[test]
fn startup_fails_immediately_on_every_other_exit() {
    for (stderr, exit) in [
        ("openwiz-service: service is already running", 1),
        (
            "openwiz-service: cannot bind the configured loopback port\nextra failure",
            1,
        ),
        (
            "openwiz-service: cannot bind the configured loopback port",
            2,
        ),
        (
            "openwiz-service: cannot bind the configured loopback port",
            0,
        ),
        ("", 1),
    ] {
        let mut f = Fixture::new();
        stub_service(&f, stderr, exit);
        let original_config = fs::read(f.root.join("service/config.json")).unwrap();
        assert_eq!(
            startup_failure(&mut f),
            format!("service exited exit status: {exit}: {stderr}\n")
        );
        assert_eq!(
            fs::read_to_string(f.root.join("attempts.log")).unwrap(),
            "attempt\n"
        );
        assert_eq!(
            fs::read(f.root.join("service/config.json")).unwrap(),
            original_config
        );
    }
}
