//! L12 production composition proofs; synthetic inputs only.
use serde_json::{Value, json};

#[path = "../support/schema.rs"]
#[allow(dead_code)]
mod schema;

fn config() -> Value {
    json!({
        "schema":"openwiz.service-config.v1",
        "repository":{"owner":"synthetic-owner","name":"synthetic-repo"},
        "project":"prj_syn_0001", "orchestrator_thread":"thr_syn_0001",
        "service_issue":901, "github_app":{"app_id":1001,"installation_id":2002},
        "tick":{"every_s":300}, "health":{"every_s":60},
        "server":{"port":7370,"allowed_host":null,"probe_timeout_s":10}
    })
}

fn loop_config() -> Value {
    let mut config = config();
    config["loops"] = json!({
        "approvals":[{
            "repository":{"owner":"synthetic-owner","name":"synthetic-repo"},
            "project":"prj_syn_0001", "loop_id":"loop-synthetic",
            "definition_revision":"a".repeat(40), "sha256":"0".repeat(64),
            "approved_by":"Synthetic approver", "scope":"Synthetic effects only.",
            "approval_ref":"https://github.com/synthetic-private/records/issues/901#issuecomment-7001"
        }],
        "limits":{"checks":{"max":4,"urgent_reserve":1},"agents":{"max":16,"urgent_reserve":4}}
    });
    config
}

// C1: L10/L11 fragment tests cannot detect a missing enclosing loops member.
#[test]
fn enclosing_schema_accepts_complete_loop_config_and_keeps_base_strict() {
    let contract: Value =
        serde_json::from_str(include_str!("../../contracts/service.v1.schema.json")).unwrap();
    assert!(schema::lint(&contract).is_empty());
    for valid in [config(), loop_config()] {
        let errors = schema::validate(&contract, &valid);
        assert!(
            errors.is_empty(),
            "valid service composition refused: {errors:?}"
        );
    }
    let valid = loop_config();
    for key in ["approvals", "limits"] {
        let mut missing = valid.clone();
        missing["loops"].as_object_mut().unwrap().remove(key);
        assert!(
            !schema::validate(&contract, &missing).is_empty(),
            "accepted missing {key}"
        );
    }
    for pointer in ["/loops", "/loops/approvals", "/loops/limits"] {
        for malformed in [Value::Null, json!(true), json!("synthetic")] {
            let mut bad = valid.clone();
            *bad.pointer_mut(pointer).unwrap() = malformed;
            assert!(
                !schema::validate(&contract, &bad).is_empty(),
                "accepted malformed {pointer}"
            );
        }
    }
    for pointer in [
        "",
        "/loops",
        "/loops/limits",
        "/loops/limits/checks",
        "/tick",
        "/server",
    ] {
        let mut extra = valid.clone();
        extra.pointer_mut(pointer).unwrap()["unexpected"] = json!(true);
        assert!(
            !schema::validate(&contract, &extra).is_empty(),
            "accepted extra field at {pointer}"
        );
    }
    for key in [
        "repository",
        "project",
        "tick",
        "health",
        "server",
        "github_app",
    ] {
        let mut missing = valid.clone();
        missing.as_object_mut().unwrap().remove(key);
        assert!(
            !schema::validate(&contract, &missing).is_empty(),
            "accepted missing base {key}"
        );
    }
}

#[test]
fn complete_config_retains_the_existing_verified_watchdog_checkout_binding() {
    let f = Fixture::new("shadow", ":");
    let context = openwiz_store::loops::config::installed(&f.checkout, &f.state)
        .expect("complete L12 config must preserve existing installed checkout binding");
    assert!(context.trust.unwrap().verify(
        &f.checkout,
        "synthetic-owner/synthetic-repo",
        "prj_syn_0001"
    ));
}

use std::{
    fs,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::{Path, PathBuf},
    process::Command,
    sync::atomic::{AtomicU64, Ordering},
};

fn private_dir(path: &Path) {
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(path)
        .unwrap();
}
fn private_file(path: &Path, bytes: impl AsRef<[u8]>) {
    fs::write(path, bytes).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
}
fn git(root: &Path, args: &[&str]) -> String {
    let out = Command::new("git")
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_CONFIG_SYSTEM", "/dev/null")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).unwrap().trim().to_owned()
}
struct Fixture {
    root: PathBuf,
    checkout: PathBuf,
    state: PathBuf,
    config: Value,
}
impl Fixture {
    fn new(mode: &str, script: &str) -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "ow-l12-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let checkout = root.join("checkout");
        let state = root.join("state");
        private_dir(&checkout.join("loops"));
        private_dir(&state.join("service"));
        git(&checkout, &["init", "-q", "--initial-branch=main"]);
        git(&checkout, &["config", "user.name", "Synthetic Builder"]);
        git(
            &checkout,
            &["config", "user.email", "synthetic@users.noreply.github.com"],
        );
        git(
            &checkout,
            &[
                "config",
                "remote.origin.url",
                "https://github.com/synthetic-owner/synthetic-repo.git",
            ],
        );
        let definition = json!({"schema":"openwiz.loops.v1","kind":"definition","id":"loop-synthetic","name":"Synthetic loop","owner":"synthetic-owner",
            "wake":{"kind":"once","at_ms":1000},"check":{"argv":["/bin/sh","-c",format!("printf x >> check-ran; {script}")],"timeout_ms":10000},
            "action":{"project":{"kind":"id","value":"prj_syn_0001"},"harness":"codex","model":"synthetic-model","effort":"high","brief":"Handle synthetic findings only."},
            "authority":{"approved_by":"Synthetic approver","approval_ref":"https://github.com/synthetic-private/records/issues/901#issuecomment-7001","scope":"Synthetic effects only."},
            "budget":{"window_ms":60000,"max_agent_starts":1},"enabled":true,"mode":mode,"priority":"normal"});
        let bytes = definition.to_string();
        fs::write(checkout.join("loops/loop.json"), &bytes).unwrap();
        git(&checkout, &["add", "loops"]);
        git(&checkout, &["commit", "-qm", "Synthetic loop"]);
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
        let revision = git(&checkout, &["rev-parse", "HEAD:loops/loop.json"]);
        let mut config = loop_config();
        config["operator"] = json!("Synthetic operator");
        config["tick"]["every_s"] = json!(2);
        config["loops"]["approvals"][0]["definition_revision"] = json!(revision);
        config["loops"]["approvals"][0]["sha256"] =
            json!(openwiz_core::messaging::sha256_hex(bytes.as_bytes()));
        let f = Self {
            root,
            checkout,
            state,
            config,
        };
        f.save(&f.config);
        f
    }
    fn save(&self, config: &Value) {
        private_file(&self.state.join("service/config.json"), config.to_string());
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.root).unwrap();
    }
}

#[test]
fn runtime_process() {
    let Some(root) = std::env::var_os("OPENWIZ_L12_PROCESS_ROOT") else {
        return;
    };
    let root = PathBuf::from(root);
    block_default_cloudroom_discovery(&root);
    if std::env::var("OPENWIZ_L12_PENDING_RECOVERY").as_deref() == Ok("yes") {
        install_update_recording(&root);
    }
    let mut jobs = openwiz_service::scheduler::Scheduler::default();
    let marker = root.join("other-job");
    jobs.register(
        "synthetic-independent",
        std::num::NonZeroU64::new(1).unwrap(),
        move || {
            fs::write(&marker, "ran").unwrap();
        },
    )
    .unwrap();
    let result = openwiz_service::runtime::run_with_health_sources(
        &root,
        &root.join("web"),
        &"a".repeat(40),
        jobs,
        |_| std::net::TcpListener::bind(("127.0.0.1", 0)),
        openwiz_service::health::Sources {
            room: openwiz_adapter_cloudroom::source::CloudRoomSource::new(
                "/synthetic/unreachable-room",
            ),
            github: openwiz_adapter_github::process::Executor::program(root.join("gh")),
        },
    );
    fs::write(root.join("runtime-error"), format!("{result:?}")).unwrap();
}
struct Process(std::process::Child);
impl Drop for Process {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn command_sources(f: &Fixture) {
    fs::write(f.state.join("room"), "#!/bin/sh\nprintf '[]\\n'\n").unwrap();
    fs::set_permissions(f.state.join("room"), fs::Permissions::from_mode(0o700)).unwrap();
    fs::write(f.state.join("gh"), r#"#!/usr/bin/python3
import json,sys,pathlib
a=sys.argv[1:]
with (pathlib.Path(__file__).parent/'gh-calls').open('a') as log: log.write(json.dumps(a)+'\n')
if a[:2]==['repo','view']:
 print(json.dumps({'defaultBranchRef':{'name':'main'},'nameWithOwner':'synthetic-owner/synthetic-repo','url':'https://github.invalid/synthetic-owner/synthetic-repo'}))
elif a[:2]==['issue','list'] or (a[0]=='api' and '/deliveries?' in a[1]): print('[]')
else: sys.exit(2)
"#).unwrap();
    fs::set_permissions(f.state.join("gh"), fs::Permissions::from_mode(0o700)).unwrap();
}

// C2/C7: only the actual runtime invocation can catch an omitted registration.
#[test]
fn actual_runtime_registers_trusted_shadow_checks_and_keeps_independent_jobs() {
    runtime_case("shadow");
}
#[test]
fn actual_runtime_keeps_independent_jobs_with_refused_and_saturated_loops() {
    for scenario in ["refused", "saturated", "absent"] {
        runtime_case(scenario);
    }
}
fn runtime_case(scenario: &str) {
    let mut f = Fixture::new(
        if scenario == "shadow" {
            "shadow"
        } else {
            "active"
        },
        "printf finding",
    );
    if scenario == "saturated" {
        f.add_loops(13);
        let mut seed = openwiz_service::scheduler::Scheduler::default();
        assert_eq!(
            f.register(
                &mut seed,
                Arc::new(RecordingClient {
                    unknown_reply: true,
                    ..Default::default()
                })
            ),
            Ok(true)
        );
        for at in [2, 4, 6, 8, 10] {
            run_jobs(&mut seed, at);
        }
        assert_eq!(
            f.runs()
                .iter()
                .filter(|r| r["result"]["kind"] == "uncertain")
                .count(),
            12
        );
    }
    private_dir(&f.state.join("web"));
    fs::write(f.state.join("web/index.html"), "Synthetic page").unwrap();
    command_sources(&f);
    let mut config = f.config.clone();
    config["tick"]["every_s"] = json!(1);
    config["health"]["every_s"] = json!(1);
    if matches!(scenario, "refused" | "recovery") {
        config["loops"]["limits"]["agents"]["max"] = json!(0);
    }
    if scenario == "absent" {
        config.as_object_mut().unwrap().remove("loops");
    }
    f.save(&config);
    let stderr = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(f.state.join("runtime-stderr"))
        .unwrap();
    let program = if scenario == "recovery" {
        prepare_update_installation(&f, true)
    } else {
        std::env::current_exe().unwrap()
    };
    let mut child = Process(
        Command::new(program)
            .args(["--exact", "runtime_process", "--nocapture"])
            .current_dir(&f.checkout)
            .env("OPENWIZ_L12_PROCESS_ROOT", &f.state)
            .env(
                "OPENWIZ_L12_PENDING_RECOVERY",
                if scenario == "recovery" { "yes" } else { "" },
            )
            .env("HOME", f.root.join("synthetic-home"))
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(stderr)
            .spawn()
            .unwrap(),
    );
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(12);
    loop {
        assert!(
            child.0.try_wait().unwrap().is_none(),
            "runtime exited: {:?}",
            fs::read_to_string(f.state.join("runtime-error"))
        );
        let loop_ready = match scenario {
            "shadow" => {
                openwiz_store::loops::storage::read_snapshot(&f.state).is_ok_and(|snapshot| {
                    snapshot.runs.len() == 1 && snapshot.runs[0]["result"]["kind"] == "shadow"
                })
            }
            "saturated" => fs::read(f.state.join("service/loops/admission.json"))
                .ok()
                .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
                .is_some_and(|value| value["at_ms"].as_u64().is_some_and(|at| at > 1000)),
            _ => !f.checkout.join("check-ran").exists(),
        };
        if let Ok(status) = openwiz_service::runtime::status(&f.state)
            && f.state.join("other-job").exists()
            && !status["last_pass"].is_null()
            && !status["tick"]["last_ended"].is_null()
            && loop_ready
        {
            assert_eq!(
                fs::read(f.checkout.join("check-ran"))
                    .unwrap_or_default()
                    .len(),
                match scenario {
                    "shadow" => 1,
                    "saturated" => 13,
                    _ => 0,
                }
            );
            use std::io::{Read, Write};
            let mut stream = std::net::TcpStream::connect((
                "127.0.0.1",
                status["server"]["port"].as_u64().unwrap() as u16,
            ))
            .unwrap();
            stream
                .set_read_timeout(Some(std::time::Duration::from_secs(2)))
                .unwrap();
            stream
                .write_all(
                    format!("GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n",status["server"]["port"].as_u64().unwrap()).as_bytes(),
                )
                .unwrap();
            let mut response = String::new();
            stream.read_to_string(&mut response).unwrap();
            assert!(response.starts_with("HTTP/1.1 200"));
            if scenario == "recovery" {
                assert_eq!(status["update"]["outcome"]["state"], "kept");
                assert_eq!(status["update"]["outcome"]["step"], "fetch");
                assert_eq!(
                    fs::read_to_string(f.state.join("update-records"))
                        .unwrap()
                        .lines()
                        .count(),
                    1
                );
                assert!(!f.state.join("service/update-pending.json").exists());
                assert!(!f.state.join("service/loops").exists());
                assert!(
                    !f.state.join("update-calls").exists(),
                    "recovery must not retry the pending fetch"
                );
            }
            break;
        }
        assert!(
            std::time::Instant::now() < deadline,
            "registered loop check or independent service job never completed: status={:?}; marker={}; independent={}; stderr={:?}",
            openwiz_service::runtime::status(&f.state),
            f.checkout.join("check-ran").exists(),
            f.state.join("other-job").exists(),
            fs::read_to_string(f.state.join("runtime-stderr"))
        );
        std::thread::park_timeout(std::time::Duration::from_millis(5));
    }
    drop(child);
    if scenario == "shadow" {
        let snapshot = openwiz_store::loops::storage::read_snapshot(&f.state).unwrap();
        assert_eq!(snapshot.runs.len(), 1);
        assert_eq!(snapshot.runs[0]["result"]["kind"], "shadow");
        assert!(snapshot.runs[0]["result"].get("op_id").is_none());
    } else if scenario == "saturated" {
        assert_eq!(
            f.runs()
                .iter()
                .filter(|r| r["result"]["kind"] == "uncertain")
                .count(),
            12
        );
        assert_eq!(
            f.runs()
                .iter()
                .filter(|r| r["result"]["kind"] == "deferred")
                .count(),
            1
        );
    }
}

use openwiz_core::{
    model::{Fact, Timestamp},
    new_thread::{
        effects::ProjectCandidate,
        operation::{NewThreadClient, ObservedThread, SpawnRequest},
        options::{Catalogue, CatalogueHarness, CatalogueModel},
        outcome::SpawnReply,
        start::ShownThread,
    },
    ops::Clock,
    source::SourceError,
};
use std::{
    sync::{Arc, Mutex},
    time::Instant,
};
struct FixedClock;
impl Clock for FixedClock {
    fn now(&self) -> Timestamp {
        Timestamp(1000)
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}
#[derive(Default)]
struct RecordingClient {
    starts: Mutex<Vec<SpawnRequest>>,
    unknown_reply: bool,
    catalogue_refused: bool,
    revoke: Option<PathBuf>,
    invalidate_limits: Option<PathBuf>,
}
impl NewThreadClient for RecordingClient {
    fn name(&self) -> &str {
        "synthetic"
    }
    fn tested_version(&self) -> &str {
        "synthetic"
    }
    fn cli_levels(&self) -> &[&str] {
        &["high"]
    }
    fn version(&self, _: Instant) -> Result<String, SourceError> {
        Ok("synthetic".into())
    }
    fn projects(&self, _: Instant) -> Result<Vec<ProjectCandidate>, SourceError> {
        Ok(vec![ProjectCandidate {
            id: "prj_syn_0001".into(),
            name: Fact::Known("Synthetic project".into()),
            kind: Fact::Known("standard".into()),
            github_remote: Fact::Known(true),
        }])
    }
    fn catalogue(&self, _: Instant) -> Result<Catalogue, SourceError> {
        if let Some(path) = &self.invalidate_limits {
            let mut config: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
            config["loops"]["limits"]["agents"]["max"] = json!(0);
            private_file(path, config.to_string());
        }
        if let Some(path) = &self.revoke {
            fs::remove_file(path).unwrap();
        }
        Ok(Catalogue {
            ready: !self.catalogue_refused,
            harnesses: Some(vec![CatalogueHarness {
                id: "codex".into(),
                provider: Some("codex".into()),
                attachments: None,
                steer: None,
                models: Some(vec![CatalogueModel {
                    model: "synthetic-model".into(),
                    reasoning_levels: vec!["high".into()],
                }]),
            }]),
        })
    }
    fn spawn(&self, request: &SpawnRequest, _: Instant) -> SpawnReply {
        self.starts.lock().unwrap().push(request.clone());
        if self.unknown_reply {
            SpawnReply::Unclear {
                reason: openwiz_core::messaging::send::UncertainReason::TimedOut,
                gaps: vec![],
            }
        } else {
            SpawnReply::Created {
                thread_id: "thr_syn_created".into(),
            }
        }
    }
    fn show_thread(&self, _: &str, _: Instant) -> Result<ShownThread, SourceError> {
        Ok(ShownThread {
            status: Fact::Known("active".into()),
            last_error: Fact::Known(None),
            provider: Fact::Known("codex".into()),
            model: Fact::Known("synthetic-model".into()),
            effort: Fact::Known("high".into()),
            problems: vec![],
        })
    }
    fn threads_since(
        &self,
        _: &str,
        _: Timestamp,
        _: Instant,
    ) -> Result<Vec<ObservedThread>, SourceError> {
        Ok(vec![])
    }
}
impl Fixture {
    fn register(
        &self,
        jobs: &mut openwiz_service::scheduler::Scheduler,
        client: Arc<RecordingClient>,
    ) -> Result<bool, String> {
        openwiz_service::loops::production::register_with_sources(
            &self.state,
            &self.config,
            jobs,
            openwiz_service::loops::production::Sources {
                checkout: self.checkout.clone(),
                client,
                clock: Arc::new(FixedClock),
            },
        )
    }
    fn runs(&self) -> Vec<Value> {
        openwiz_store::loops::storage::read_snapshot(&self.state)
            .unwrap()
            .runs
    }
}
fn run_jobs(jobs: &mut openwiz_service::scheduler::Scheduler, elapsed: u64) -> Vec<String> {
    let started = jobs.poll(elapsed).unwrap();
    for name in &started {
        jobs.wait(name).unwrap();
    }
    started
}

// C3/C4/C6: the real production reader/store, with virtual scheduler time.
#[test]
fn production_composition_preserves_quiet_shadow_created_and_uncertain_across_restart() {
    for (mode, script, lost, expected, starts) in [
        ("active", ":", false, "quiet", 0),
        ("shadow", "printf finding", false, "shadow", 0),
        ("active", "printf finding", false, "created", 1),
        ("active", "printf finding", true, "uncertain", 1),
    ] {
        let f = Fixture::new(mode, script);
        let client = Arc::new(RecordingClient {
            unknown_reply: lost,
            ..Default::default()
        });
        for _restart in 0..2 {
            let mut jobs = openwiz_service::scheduler::Scheduler::default();
            assert_eq!(f.register(&mut jobs, client.clone()), Ok(true));
            assert!(run_jobs(&mut jobs, 1).is_empty());
            assert_eq!(run_jobs(&mut jobs, 2), ["loops.v1"]);
            let runs = f.runs();
            assert_eq!(runs.len(), 1);
            assert_eq!(runs[0]["result"]["kind"], expected);
            assert_eq!(fs::read(f.checkout.join("check-ran")).unwrap(), b"x");
            assert_eq!(client.starts.lock().unwrap().len(), starts);
            if starts == 1 {
                use openwiz_core::{messaging::OpId, new_thread::record::NewThreadStore};
                let id = OpId::parse(runs[0]["result"]["op_id"].as_str().unwrap()).unwrap();
                let store = openwiz_store::NewThreadFileStore::open(&f.state).unwrap();
                let receipt = store.inspect(&id, Timestamp(1000)).unwrap().unwrap();
                assert_eq!(receipt.op_id, id);
                assert!(receipt.outcome.is_some());
            }
        }
    }
}

#[test]
fn production_refuses_catalogue_gate_and_revocation_during_preview() {
    for scenario in ["catalogue", "revoke", "limits"] {
        let f = Fixture::new("active", "printf finding");
        let client = Arc::new(RecordingClient {
            catalogue_refused: scenario == "catalogue",
            revoke: (scenario == "revoke").then(|| f.state.join("service/config.json")),
            invalidate_limits: (scenario == "limits").then(|| f.state.join("service/config.json")),
            ..Default::default()
        });
        let mut jobs = openwiz_service::scheduler::Scheduler::default();
        assert_eq!(f.register(&mut jobs, client.clone()), Ok(true));
        run_jobs(&mut jobs, 2);
        assert_eq!(f.runs()[0]["result"]["kind"], "refused");
        assert_eq!(client.starts.lock().unwrap().len(), 0);
    }
}

// A cached limits reader or a misplaced gate on the scheduler would miss this.
#[test]
fn refusing_loop_inputs_before_and_after_registration_preserves_other_jobs() {
    let f = Fixture::new("active", "printf finding");
    let mut cases = vec![config()];
    for key in ["approvals", "limits"] {
        let mut bad = f.config.clone();
        bad["loops"].as_object_mut().unwrap().remove(key);
        cases.push(bad);
    }
    for (pointer, value) in [
        ("/project", json!("prj_syn_foreign")),
        ("/repository/name", json!("other-repo")),
        ("/tick/every_s", json!(3)),
        ("/loops/limits/checks/max", json!(5)),
        ("/loops/limits/agents/max", json!(0)),
        ("/loops/approvals/0/sha256", json!("f".repeat(64))),
        ("/loops/approvals/0/project", json!("prj_syn_foreign")),
        (
            "/loops/approvals/0/definition_revision",
            json!("b".repeat(40)),
        ),
    ] {
        let mut bad = f.config.clone();
        *bad.pointer_mut(pointer).unwrap() = value;
        cases.push(bad);
    }
    let mut duplicate = f.config.clone();
    duplicate["loops"]["approvals"]
        .as_array_mut()
        .unwrap()
        .push(f.config["loops"]["approvals"][0].clone());
    cases.push(duplicate);
    for after in [false, true] {
        for bad in &cases {
            f.save(&f.config);
            let client = Arc::new(RecordingClient::default());
            let mut jobs = openwiz_service::scheduler::Scheduler::default();
            if after {
                assert_eq!(f.register(&mut jobs, client.clone()), Ok(true));
            }
            f.save(bad);
            assert!(
                openwiz_service::document::read(
                    openwiz_service::document::Document::Config,
                    &bad.to_string()
                )
                .is_ok(),
                "loop refusal became a base config gate"
            );
            if !after {
                let _ = f.register(&mut jobs, client.clone());
            }
            let calls = Arc::new(AtomicU64::new(0));
            let worker = calls.clone();
            jobs.register(
                "independent-fleet-route",
                std::num::NonZeroU64::new(1).unwrap(),
                move || {
                    // This independent service job has no loop admission guard.
                    worker.fetch_add(1, Ordering::SeqCst);
                },
            )
            .unwrap();
            run_jobs(&mut jobs, 2);
            assert_eq!(calls.load(Ordering::SeqCst), 1);
            assert!(!f.checkout.join("check-ran").exists());
            assert_eq!(client.starts.lock().unwrap().len(), 0);
        }
    }
}

// Store-reader allocation 6781147444: strict L10 spellings, reached through
// real installation binding rather than a test-only pattern API.
#[test]
fn installed_binding_refuses_invalid_approval_patterns() {
    let f = Fixture::new("shadow", ":");
    for (pointer, values) in [
        (
            "/loops/approvals/0/repository/name",
            vec![
                json!("."),
                json!(".."),
                json!("bad/name"),
                json!("bad name"),
            ],
        ),
        (
            "/loops/approvals/0/approved_by",
            vec![json!(" "), json!("\u{2000}\t"), json!("x\0y")],
        ),
        (
            "/loops/approvals/0/scope",
            vec![json!("\u{3000}"), json!("\0")],
        ),
        (
            "/loops/approvals/0/approval_ref",
            vec![
                json!("https://github.com/synthetic-private/records/issues/01#issuecomment-1"),
                json!("https://github.com/synthetic-private/records/issues/1#issuecomment-0"),
                json!("https://github.com/synthetic-private/../issues/1#issuecomment-1"),
                json!(
                    "https://github.com/synthetic-private/records/issues/1#issuecomment-1?token=synthetic"
                ),
                json!("https://user@github.com/synthetic-private/records/pull/1#issuecomment-1"),
                json!("https://github.com/synthetic-private/records/pull/1#issuecomment-1/suffix"),
            ],
        ),
    ] {
        for value in values {
            let mut bad = f.config.clone();
            *bad.pointer_mut(pointer).unwrap() = value;
            f.save(&bad);
            assert!(
                openwiz_store::loops::config::installed(&f.checkout, &f.state).is_err(),
                "accepted malformed {pointer}"
            );
        }
    }
    for url in [
        "https://github.com/synthetic-private/.records/pull/1#issuecomment-1",
        "https://github.com/synthetic-private/.../issues/1#issuecomment-1",
        "https://github.com/synthetic-private/.../pull/1#issuecomment-1",
    ] {
        let mut valid = f.config.clone();
        valid["loops"]["approvals"][0]["approval_ref"] = json!(url);
        f.save(&valid);
        assert!(openwiz_store::loops::config::installed(&f.checkout, &f.state).is_ok());
    }
}

#[test]
fn duplicate_unsafe_unreadable_and_changed_inputs_admit_no_check() {
    for case in [
        "duplicate",
        "missing",
        "symlink",
        "mode",
        "dirty",
        "nondefault",
        "changed",
    ] {
        let f = Fixture::new("active", "printf finding");
        let client = Arc::new(RecordingClient::default());
        let mut jobs = openwiz_service::scheduler::Scheduler::default();
        assert_eq!(f.register(&mut jobs, client.clone()), Ok(true));
        let path = f.state.join("service/config.json");
        match case {
            "duplicate" => private_file(
                &path,
                f.config
                    .to_string()
                    .replace("\"loops\":", "\"loops\":{},\"loops\":"),
            ),
            "missing" => fs::remove_file(&path).unwrap(),
            "symlink" => {
                fs::rename(&path, f.root.join("copy")).unwrap();
                std::os::unix::fs::symlink(f.root.join("copy"), &path).unwrap();
            }
            "mode" => fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap(),
            "dirty" => fs::write(f.checkout.join("loops/loop.json"), "{}").unwrap(),
            "nondefault" => {
                git(
                    &f.checkout,
                    &[
                        "commit",
                        "--allow-empty",
                        "-qm",
                        "Synthetic unmerged checkout",
                    ],
                );
            }
            "changed" => {
                let mut definition: Value =
                    serde_json::from_slice(&fs::read(f.checkout.join("loops/loop.json")).unwrap())
                        .unwrap();
                definition["name"] = json!("Changed synthetic loop");
                fs::write(f.checkout.join("loops/loop.json"), definition.to_string()).unwrap();
                git(&f.checkout, &["add", "loops"]);
                git(&f.checkout, &["commit", "-qm", "Changed synthetic loop"]);
                git(
                    &f.checkout,
                    &["update-ref", "refs/remotes/origin/main", "HEAD"],
                );
            }
            _ => unreachable!(),
        }
        run_jobs(&mut jobs, 2);
        assert!(
            !f.checkout.join("check-ran").exists(),
            "check ran for {case}"
        );
        assert_eq!(client.starts.lock().unwrap().len(), 0);
    }
}

impl Fixture {
    fn add_loops(&mut self, total: usize) {
        let definition: Value =
            serde_json::from_slice(&fs::read(self.checkout.join("loops/loop.json")).unwrap())
                .unwrap();
        for n in 1..total {
            let mut d = definition.clone();
            d["id"] = json!(format!("loop-synthetic-{n:02}"));
            fs::write(
                self.checkout.join(format!("loops/loop-{n:02}.json")),
                d.to_string(),
            )
            .unwrap();
        }
        git(&self.checkout, &["add", "loops"]);
        git(&self.checkout, &["commit", "-qm", "Synthetic loop set"]);
        git(
            &self.checkout,
            &["update-ref", "refs/remotes/origin/main", "HEAD"],
        );
        for n in 1..total {
            let path = format!("loops/loop-{n:02}.json");
            let mut record = self.config["loops"]["approvals"][0].clone();
            record["loop_id"] = json!(format!("loop-synthetic-{n:02}"));
            record["definition_revision"] =
                json!(git(&self.checkout, &["rev-parse", &format!("HEAD:{path}")]));
            record["sha256"] = json!(openwiz_core::messaging::sha256_hex(
                &fs::read(self.checkout.join(path)).unwrap()
            ));
            self.config["loops"]["approvals"]
                .as_array_mut()
                .unwrap()
                .push(record);
        }
        self.save(&self.config);
    }
}

// C7: actual durable fleet/new-thread routes keep admitting original work and
// descendants beyond loop capacity, with the loop pool saturated or refused.
#[test]
fn loop_saturation_and_refusal_do_not_cap_fleet_or_descendant_routes() {
    use openwiz_core::{
        fleet::{
            model::{Commit, Number},
            starts::{Repository, StartKey, StartOutcome, StartRequest, start_agent},
        },
        messaging::OpId,
        new_thread::{NewThreadRequest, ProjectRef, Settings, operation::new_thread},
        prompt::PromptPayload,
    };
    for saturated in [false, true] {
        let mut f = Fixture::new("active", "printf finding");
        let client = Arc::new(RecordingClient::default());
        let mut jobs = openwiz_service::scheduler::Scheduler::default();
        if saturated {
            f.add_loops(13);
            assert_eq!(f.register(&mut jobs, client.clone()), Ok(true));
            for elapsed in [2, 4, 6, 8, 10] {
                run_jobs(&mut jobs, elapsed);
            }
            let runs = f.runs();
            assert_eq!(runs.len(), 13);
            assert_eq!(
                runs.iter()
                    .filter(|r| r["result"]["kind"] == "created")
                    .count(),
                12
            );
            assert_eq!(
                runs.iter()
                    .filter(|r| r["result"]["kind"] == "deferred")
                    .count(),
                1
            );
        } else {
            let mut invalid = f.config.clone();
            invalid["loops"]["limits"]["agents"]["max"] = json!(0);
            f.save(&invalid);
            assert!(f.register(&mut jobs, client.clone()).is_err());
        }
        let before = client.starts.lock().unwrap().len();
        let threads = openwiz_store::NewThreadFileStore::open(&f.state).unwrap();
        let starts = openwiz_store::StartFileStore::open(&f.state).unwrap();
        let settings = Settings {
            harness: "codex".into(),
            model: "synthetic-model".into(),
            effort: "high".into(),
        };
        for n in 0..10 {
            let repo = Repository::parse("synthetic-owner/synthetic-repo").unwrap();
            let key = if n < 5 {
                StartKey::builder(repo, Number::new(900 + n).unwrap())
            } else {
                StartKey::reviewer(
                    repo,
                    Number::new(900 + n).unwrap(),
                    Commit::parse(&"a".repeat(40)).unwrap(),
                )
            };
            let request = StartRequest::new(key, "prj_syn_0001", settings.clone());
            let report = start_agent(
                client.as_ref(),
                &threads,
                &starts,
                &FixedClock,
                &|| Ok(OpId::parse(&format!("synthetic-fleet-{n}")).unwrap()),
                &request,
            )
            .unwrap();
            assert!(matches!(
                report.outcome,
                StartOutcome::Started {
                    by_this_call: true,
                    ..
                }
            ));
        }
        for role in ["planner", "child"] {
            for n in 0..4 {
                let request = NewThreadRequest::new(
                    ProjectRef::Id("prj_syn_0001".into()),
                    settings.clone(),
                    PromptPayload::text(format!("Synthetic {role} work.")),
                    OpId::parse(&format!("synthetic-{role}-{n}")).unwrap(),
                );
                new_thread(client.as_ref(), &threads, &FixedClock, &request).unwrap();
            }
        }
        assert_eq!(client.starts.lock().unwrap().len() - before, 18);
        if saturated {
            run_jobs(&mut jobs, 12);
            assert_eq!(
                client.starts.lock().unwrap().len(),
                30,
                "the deferred loop must remain held"
            );
        }
    }
}

#[test]
fn restarted_composition_reconciles_interrupted_check_without_running_it_again() {
    let f = Fixture::new("active", ":");
    let client = Arc::new(RecordingClient::default());
    let mut jobs = openwiz_service::scheduler::Scheduler::default();
    assert_eq!(f.register(&mut jobs, client.clone()), Ok(true));
    run_jobs(&mut jobs, 2);
    let mut interrupted = f.runs().remove(0);
    interrupted["result"] = json!({"kind":"checking"});
    {
        let storage = openwiz_store::loops::storage::Storage::open(&f.state).unwrap();
        storage.save_run(&interrupted).unwrap();
    }
    let mut restarted = openwiz_service::scheduler::Scheduler::default();
    assert_eq!(f.register(&mut restarted, client.clone()), Ok(true));
    run_jobs(&mut restarted, 2);
    let runs = f.runs();
    assert_eq!(runs.len(), 1);
    assert_eq!(runs[0]["result"]["kind"], "check_failed");
    assert_eq!(fs::read(f.checkout.join("check-ran")).unwrap(), b"x");
    assert_eq!(client.starts.lock().unwrap().len(), 0);
}

#[test]
fn update_and_existing_event_intake_remain_scheduled_when_loops_refuse_or_saturate() {
    use openwiz_service::{events::intake, scheduler::Scheduler, state::State};
    use std::sync::atomic::AtomicBool;
    for saturated in [false, true] {
        let mut f = Fixture::new("active", "printf finding");
        command_sources(&f);
        f.config["events"] = json!({"hook_id":4101});
        f.save(&f.config);
        let mut jobs = Scheduler::default();
        if saturated {
            f.add_loops(13);
            assert_eq!(
                f.register(
                    &mut jobs,
                    Arc::new(RecordingClient {
                        unknown_reply: true,
                        ..Default::default()
                    })
                ),
                Ok(true)
            );
            for at in [2, 4, 6, 8, 10] {
                run_jobs(&mut jobs, at);
            }
        } else {
            let mut invalid = f.config.clone();
            invalid["loops"]["limits"]["agents"]["max"] = json!(0);
            f.save(&invalid);
            assert!(
                f.register(&mut jobs, Arc::new(RecordingClient::default()))
                    .is_err()
            );
            // Both independent registrations consume the same refused loop config.
            f.config = invalid;
        }
        let state = Arc::new(Mutex::new(State::load(&f.state, 1000).unwrap()));
        let restart = Arc::new(AtomicBool::new(false));
        openwiz_service::update::register(
            &f.state,
            &f.config,
            &"a".repeat(40),
            state,
            &mut jobs,
            restart.clone(),
        )
        .unwrap();
        assert_eq!(
            intake::register_with_sources(
                &f.state,
                &f.config,
                &mut jobs,
                openwiz_service::tick::Sources {
                    room: openwiz_adapter_cloudroom::source::CloudRoomSource::new(
                        f.state.join("room")
                    ),
                    github: openwiz_adapter_github::process::Executor::program(f.state.join("gh")),
                },
                Arc::new(FixedClock)
            ),
            Ok(true)
        );
        let mut due = run_jobs(&mut jobs, 310);
        due.sort();
        assert_eq!(
            due,
            if saturated {
                vec!["github-events", "loops.v1", "self-update"]
            } else {
                vec!["github-events", "self-update"]
            }
        );
        let calls: Vec<Value> = fs::read_to_string(f.state.join("gh-calls"))
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect();
        assert_eq!(calls.len(), 1);
        assert!(
            calls[0][1]
                .as_str()
                .unwrap()
                .ends_with("/hooks/4101/deliveries?per_page=100")
        );
        assert!(
            !restart.load(Ordering::SeqCst),
            "missing App key must retain the old build"
        );
    }
}

// Fixture entrypoints must refuse system discovery even if a broken guard
// unexpectedly reaches the default client; explicit recording sources remain.
fn block_default_cloudroom_discovery(root: &Path) {
    use openwiz_adapter_cloudroom::locate::{self, Discovery, LauncherMetadata};
    locate::install(Discovery::fixed(root.join("no-real-room-cli"), |_| {
        LauncherMetadata { uid: 0, mode: 0 }
    }))
    .unwrap();
}

// R1: use the updater's existing recording seams, not a missing-key refusal.
// Each embedding is a separate fixture process so global injection cannot leak.
struct UpdateRecording(PathBuf);
impl openwiz_service::update::Executor for UpdateRecording {
    fn run(&self, call: &openwiz_service::update::Call) -> Result<String, String> {
        use std::io::Write;
        let mut log = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.0.join("update-calls"))
            .unwrap();
        writeln!(log, "{}", serde_json::to_string(call.argv()).unwrap()).unwrap();
        let args: Vec<_> = call.argv().iter().map(String::as_str).collect();
        match args.get(4..).unwrap_or_default() {
            ["remote", "get-url", "origin"] => {
                Ok("https://github.com/synthetic-owner/synthetic-repo.git\n".into())
            }
            ["ls-remote", "--exit-code", "origin", "refs/heads/main"] => {
                Ok(format!("{}\trefs/heads/main\n", "b".repeat(40)))
            }
            [
                "fetch",
                "--no-tags",
                "--no-recurse-submodules",
                "origin",
                "+refs/heads/main:refs/heads/main",
            ] => Err("Synthetic fetch refusal.".into()),
            _ => panic!("unexpected recording update call"),
        }
    }
}
fn install_update_recording(root: &Path) {
    use std::io::Write;
    let records = root.to_owned();
    openwiz_service::update::install_records(Arc::new(move |issue, body| {
        assert_eq!(issue, 901);
        let mut out = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(records.join("update-records"))
            .unwrap();
        writeln!(out, "{}", serde_json::to_string(body).unwrap()).unwrap();
        Ok(())
    }))
    .unwrap();
    openwiz_service::update::install_executor(Arc::new(UpdateRecording(root.to_owned()))).unwrap();
}
fn prepare_update_installation(f: &Fixture, pending: bool) -> PathBuf {
    let build = f.state.join("service/builds").join("a".repeat(40));
    let install = f.root.join("synthetic-home/.local/lib/openwiz");
    private_dir(&build);
    private_dir(&install);
    private_dir(&f.state.join("service/clone"));
    let program = build.join("openwiz-service");
    // Only this copying process opens the executable for writing. Concurrent
    // fixture forks cannot inherit a writable descriptor from this test process.
    assert!(
        Command::new("cp")
            .arg(std::env::current_exe().unwrap())
            .arg(&program)
            .status()
            .unwrap()
            .success()
    );
    fs::set_permissions(&program, fs::Permissions::from_mode(0o700)).unwrap();
    std::os::unix::fs::symlink(&build, install.join("current")).unwrap();
    if pending {
        private_file(&f.state.join("service/update-pending.json"),json!({
            "at":1000,"from":"a".repeat(40),"to":"b".repeat(40),"phase":"fetch","record_claimed":false
        }).to_string());
    }
    program
}
#[test]
fn r1_scheduled_update_process() {
    let Some(root) = std::env::var_os("OPENWIZ_L12_SCHEDULED_UPDATE") else {
        return;
    };
    let root = PathBuf::from(root);
    block_default_cloudroom_discovery(&root);
    install_update_recording(&root);
    let config = openwiz_service::document::read(
        openwiz_service::document::Document::Config,
        &fs::read_to_string(root.join("service/config.json")).unwrap(),
    )
    .unwrap();
    let state = Arc::new(Mutex::new(
        openwiz_service::state::State::load(&root, 1000).unwrap(),
    ));
    let mut jobs = openwiz_service::scheduler::Scheduler::default();
    let restart = Arc::new(std::sync::atomic::AtomicBool::new(false));
    assert!(openwiz_service::loops::production::register(&root, &config, &mut jobs).is_err());
    openwiz_service::update::register(
        &root,
        &config,
        &"a".repeat(40),
        state.clone(),
        &mut jobs,
        restart.clone(),
    )
    .unwrap();
    assert_eq!(run_jobs(&mut jobs, 300), ["self-update"]);
    let saved = state.lock().unwrap();
    assert_eq!(
        saved.snapshot()["update"]["outcome"]["state"],
        "kept",
        "R1: malformed loops must not prevent independent update construction/progress"
    );
    assert_eq!(saved.snapshot()["update"]["outcome"]["step"], "fetch");
    assert_eq!(saved.snapshot()["update"]["to"], "b".repeat(40));
    assert!(!restart.load(Ordering::SeqCst));
    assert_eq!(
        fs::read_to_string(root.join("update-records"))
            .unwrap()
            .lines()
            .count(),
        1
    );
    assert_eq!(
        fs::read_to_string(root.join("update-calls"))
            .unwrap()
            .lines()
            .count(),
        3
    );
}
#[test]
fn r1_scheduled_update_progresses_with_malformed_loop_limits() {
    let f = Fixture::new("active", "printf finding");
    let mut invalid = f.config.clone();
    invalid["loops"]["limits"]["agents"]["max"] = json!(0);
    f.save(&invalid);
    let program = prepare_update_installation(&f, false);
    let out = Command::new(program)
        .args(["--exact", "r1_scheduled_update_process", "--nocapture"])
        .current_dir(&f.checkout)
        .env("OPENWIZ_L12_SCHEDULED_UPDATE", &f.state)
        .env("HOME", f.root.join("synthetic-home"))
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "scheduled update fixture failed:\n{}\n{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(!f.checkout.join("check-ran").exists());
    assert!(!f.state.join("service/loops").exists());
}
#[test]
fn r1_pending_recovery_retains_http_health_tick_with_malformed_loop_limits() {
    runtime_case("recovery");
}
