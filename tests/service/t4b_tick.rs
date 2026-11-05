//! T4b: the service's real scheduler/status edge, synthetic files only.
#![cfg(target_os = "linux")]
use openwiz_service::{runtime, state::State};
use serde_json::{Value, json};
use std::{
    fs::{self, DirBuilder},
    net::TcpListener,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::atomic::{AtomicU64, Ordering},
    time::{Duration, Instant},
};

#[path = "t4b_executor.rs"]
mod executor;
#[path = "t4b_schedule.rs"]
mod schedule;

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "openwiz-t4b-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        for dir in [&root, &root.join("service"), &root.join("web")] {
            DirBuilder::new().mode(0o700).create(dir).unwrap();
        }
        fs::write(root.join("web/index.html"), "synthetic page").unwrap();
        let fixture = Self(root);
        fs::write(
            fixture.0.join("service/config.json"),
            fixture.config(7370).to_string(),
        )
        .unwrap();
        fs::set_permissions(
            fixture.0.join("service/config.json"),
            fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        fixture
    }
    fn config(&self, port: u16) -> Value {
        json!({
            "schema":"openwiz.service-config.v1",
            "repository":{"owner":"synthetic-owner","name":"synthetic-repo"},
            "project":"prj_syn_0001","orchestrator_thread":"thr_syn_0001",
            "service_issue":901,"github_app":{"app_id":1001,"installation_id":2002},
            "tick":{"every_s":1},"health":{"every_s":60},
            "server":{"port":port,"allowed_host":null,"probe_timeout_s":10}
        })
    }
    fn state(&self) -> State {
        State::load(&self.0, 1000).unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
struct Process(Child);
impl Drop for Process {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
fn service_process() {
    let Some(root) = std::env::var_os("OPENWIZ_T4B_PROCESS_ROOT") else {
        return;
    };
    let root = PathBuf::from(root);
    runtime::run(
        &root,
        &root.join("web"),
        &"a".repeat(40),
        openwiz_service::scheduler::Scheduler::default(),
    )
    .unwrap();
}

#[test]
fn scheduled_app_failure_is_visible_through_running_service_status() {
    let f = Fixture::new();
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let config = f.config(listener.local_addr().unwrap().port());
    drop(listener);
    let path = f.0.join("service/config.json");
    fs::write(&path, config.to_string()).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
    // No App key exists: this must be a failed tick, with no live call.
    let mut process = Process(
        Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "service_process", "--nocapture"])
            .env("OPENWIZ_T4B_PROCESS_ROOT", &f.0)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap(),
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        assert!(process.0.try_wait().unwrap().is_none(), "service exited");
        if let Ok(report) = runtime::status(&f.0)
            && !report["tick"]["last_ended"].is_null()
        {
            assert!(report["tick"]["running"].is_null());
            let ended = &report["tick"]["last_ended"];
            assert_eq!(ended["how"], "failed");
            assert!(ended["ended_at"].as_u64().unwrap() >= ended["started_at"].as_u64().unwrap());
            assert!(report["update"].is_null(), "updater state preserved");
            break;
        }
        assert!(
            Instant::now() < deadline,
            "scheduled tick never published a failed outcome"
        );
        std::thread::park_timeout(Duration::from_millis(5));
    }
}
