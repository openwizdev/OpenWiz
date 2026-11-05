//! Recording new-thread client; actual runner, Git definitions and durable stores.
use super::*;
use openwiz_adapter_cloudroom::new_thread::{CLI_REASONING_LEVELS, parse_catalogue};
use openwiz_core::{
    model::{Fact, Timestamp},
    new_thread::{
        effects::ProjectCandidate,
        operation::{NewThreadClient, ObservedThread, SpawnRequest},
        options::Catalogue,
        outcome::SpawnReply,
        start::ShownThread,
    },
    ops::Clock,
    source::SourceError,
};
use openwiz_service::loops::{Approval, Config, Runner, Services};
use openwiz_store::NewThreadFileStore;
use std::{
    fs,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::{Path, PathBuf},
    process::Command,
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
    },
    time::Instant,
};

struct FakeClock(AtomicU64);
impl Clock for FakeClock {
    fn now(&self) -> Timestamp {
        Timestamp(self.0.load(Ordering::SeqCst) as i64)
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}
#[derive(Default)]
struct RecordingClient {
    spawns: Mutex<Vec<SpawnRequest>>,
    reads: Mutex<Vec<String>>,
    status: Mutex<Option<String>>,
    uncertain: bool,
}
impl NewThreadClient for RecordingClient {
    fn name(&self) -> &str {
        "synthetic-client"
    }
    fn tested_version(&self) -> &str {
        "v127"
    }
    fn cli_levels(&self) -> &[&str] {
        CLI_REASONING_LEVELS
    }
    fn version(&self, _: Instant) -> Result<String, SourceError> {
        Ok("v127".into())
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
        parse_catalogue(include_bytes!(
            "../../fixtures/room-cli-v127/new-thread/cloud-status.json"
        ))
    }
    fn spawn(&self, request: &SpawnRequest, _: Instant) -> SpawnReply {
        let mut spawns = self.spawns.lock().unwrap();
        spawns.push(request.clone());
        if self.uncertain {
            return SpawnReply::Unclear {
                reason: openwiz_core::messaging::send::UncertainReason::TimedOut,
                gaps: vec![],
            };
        }
        SpawnReply::Created {
            thread_id: format!("thr_syn_{}", spawns.len()),
        }
    }
    fn show_thread(&self, thread: &str, _: Instant) -> Result<ShownThread, SourceError> {
        self.reads.lock().unwrap().push(thread.to_owned());
        let Some(status) = self.status.lock().unwrap().clone() else {
            return Err(SourceError::NotFound {
                subject: thread.into(),
            });
        };
        Ok(ShownThread {
            status: Fact::Known(status),
            last_error: Fact::Known(None),
            provider: Fact::Known("codex".into()),
            model: Fact::Known("syn-codex-model-01".into()),
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
        panic!("loop occupancy must not list descendants or unrelated threads")
    }
}
struct ExactApproval(Vec<(Value, String)>);
impl Approval for ExactApproval {
    fn verify(&self, definition: &Value, revision: &str) -> bool {
        self.0.iter().any(|(d, r)| d == definition && r == revision)
    }
}
struct Fixture {
    root: PathBuf,
    definitions: Vec<Value>,
    revisions: Vec<String>,
    clock: Arc<FakeClock>,
    client: Arc<RecordingClient>,
}
fn dir(path: &Path) {
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(path)
        .unwrap();
}
fn git(path: &Path, args: &[&str]) -> String {
    let out = Command::new("git")
        .current_dir(path)
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{args:?}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).unwrap().trim().into()
}
impl Fixture {
    fn new(count: usize, urgent: usize, uncertain: bool) -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "ow-l11-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::SeqCst)
        ));
        let checkout = root.join("checkout");
        dir(&checkout.join("loops"));
        dir(&root.join("state/service"));
        let file = root.join("state/service/config.json");
        fs::write(&file, config(APPROVED)).unwrap();
        fs::set_permissions(&file, fs::Permissions::from_mode(0o600)).unwrap();
        git(&checkout, &["init", "-q", "--initial-branch=main"]);
        git(&checkout, &["config", "user.name", "Synthetic Builder"]);
        git(
            &checkout,
            &["config", "user.email", "synthetic@example.invalid"],
        );
        let definitions = (0..count).map(|n| json!({
            "schema":"openwiz.loops.v1","kind":"definition","id":format!("loop-syn-{n:03}"),"name":"Synthetic loop","owner":"synthetic-owner",
            "wake":{"kind":"once","at_ms":1000},"check":{"argv":["/bin/sh","-c","printf finding"],"timeout_ms":1000},
            "action":{"project":{"kind":"id","value":"prj_syn_0001"},"harness":"codex","model":"syn-codex-model-01","effort":"high","brief":"Handle synthetic findings only."},
            "authority":{"approved_by":"synthetic-owner","approval_ref":"synthetic-confirmation","scope":"Synthetic findings only."},
            "budget":{"window_ms":1000,"max_agent_starts":1},"enabled":true,"mode":"active","priority":if n < urgent {"urgent"} else {"normal"}
        })).collect();
        let mut f = Self {
            root,
            definitions,
            revisions: vec![],
            clock: Arc::new(FakeClock(AtomicU64::new(1000))),
            client: Arc::new(RecordingClient {
                status: Mutex::new(Some("active".into())),
                uncertain,
                ..Default::default()
            }),
        };
        f.commit();
        f
    }
    fn commit(&mut self) {
        let checkout = self.root.join("checkout");
        for (n, d) in self.definitions.iter().enumerate() {
            fs::write(checkout.join(format!("loops/{n:03}.json")), d.to_string()).unwrap();
        }
        git(&checkout, &["add", "loops"]);
        git(&checkout, &["commit", "-qm", "Synthetic definitions"]);
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
        self.revisions = (0..self.definitions.len())
            .map(|n| {
                git(
                    &checkout,
                    &["rev-parse", &format!("HEAD:loops/{n:03}.json")],
                )
            })
            .collect();
    }
    fn runner(&self, limits: Option<Limits>, approval: bool) -> Runner {
        Runner::new(
            Config {
                checkout: self.root.join("checkout"),
                state: self.root.join("state"),
                limits,
            },
            Services {
                clock: self.clock.clone(),
                client: self.client.clone(),
                new_threads: Arc::new(NewThreadFileStore::open(&self.root.join("state")).unwrap()),
                approval: approval.then(|| {
                    Arc::new(ExactApproval(
                        self.definitions
                            .iter()
                            .cloned()
                            .zip(self.revisions.clone())
                            .collect(),
                    )) as Arc<dyn Approval>
                }),
            },
        )
    }
    fn spawns(&self) -> usize {
        self.client.spawns.lock().unwrap().len()
    }
    fn status(&self, value: Option<&str>) {
        *self.client.status.lock().unwrap() = value.map(str::to_owned);
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.root).unwrap();
    }
}

#[test]
fn runner_queues_two_hundred_and_keeps_original_occupancy() {
    let f = Fixture::new(200, 0, false);
    let limits = approved();
    let runner = f.runner(Some(limits), true);
    for _ in 0..5 {
        runner.pass().unwrap();
    }
    assert_eq!(f.spawns(), 12);
    let runs = runner.pass().unwrap();
    assert_eq!(f.spawns(), 12);
    assert_eq!(
        runs.iter()
            .filter(|r| r["result"]["kind"] == "deferred")
            .count(),
        6
    );
    // Without a complete observation, even free urgent slots remain held.
    f.status(None);
    runner.pass().unwrap();
    assert_eq!(f.spawns(), 12);
}
#[test]
fn runner_urgent_can_use_total_sixteen() {
    let f = Fixture::new(200, 200, false);
    let runner = f.runner(Some(approved()), true);
    for _ in 0..5 {
        runner.pass().unwrap();
    }
    assert_eq!(f.spawns(), 16);
    assert_eq!(
        runner
            .pass()
            .unwrap()
            .iter()
            .filter(|r| r["result"]["kind"] == "deferred")
            .count(),
        8
    );
    assert_eq!(f.spawns(), 16);
}
#[test]
fn runner_refuses_bad_limits_before_checks_or_dispatch() {
    let f = Fixture::new(1, 0, false);
    for bad in invalid_configs()
        .into_iter()
        .chain(invalid_records().into_iter().map(|r| config(&r)))
    {
        let limits = limits::read(bad.as_bytes()).ok();
        assert!(f.runner(limits, true).pass().is_err());
        assert_eq!(f.spawns(), 0);
        assert!(
            !f.root.join("state/service/loops/runs").exists()
                || fs::read_dir(f.root.join("state/service/loops/runs"))
                    .unwrap()
                    .next()
                    .is_none()
        );
    }
}
#[test]
fn runner_off_shadow_and_approval_still_gate_effects() {
    for mode in ["off", "shadow", "unapproved", "quiet"] {
        let mut f = Fixture::new(1, 0, false);
        match mode {
            "off" => f.definitions[0]["enabled"] = json!(false),
            "shadow" => f.definitions[0]["mode"] = json!("shadow"),
            "quiet" => f.definitions[0]["check"]["argv"] = json!(["/bin/true"]),
            _ => {}
        }
        if mode != "unapproved" {
            f.commit();
        }
        let runs = f
            .runner(Some(approved()), mode != "unapproved")
            .pass()
            .unwrap();
        assert_eq!(f.spawns(), 0);
        if mode == "shadow" {
            assert_eq!(runs[0]["result"]["kind"], "shadow");
        } else if mode == "quiet" {
            assert_eq!(runs[0]["result"]["kind"], "quiet");
        } else {
            assert!(runs.is_empty());
        }
    }
}
#[test]
fn runner_retirement_is_durable_per_original_run_and_thread() {
    for status in ["idle", "error"] {
        let mut f = Fixture::new(1, 0, false);
        f.definitions[0]["wake"] = json!({"kind":"interval","every_ms":500,"anchor_ms":1000});
        f.commit();
        let limits = approved();
        f.runner(Some(limits), true).pass().unwrap();
        assert_eq!(f.spawns(), 1);
        f.status(Some(status));
        f.runner(Some(limits), true).pass().unwrap();
        let reads = f.client.reads.lock().unwrap().len();
        f.status(Some("active"));
        f.clock.0.store(1500, Ordering::SeqCst);
        let runs = f.runner(Some(limits), true).pass().unwrap();
        assert_eq!(
            f.spawns(),
            1,
            "saved attempted start still spends this loop's rolling budget"
        );
        assert_eq!(
            f.client.reads.lock().unwrap().len(),
            reads,
            "retired original is never sampled again"
        );
        let deferred = runs
            .iter()
            .find(|r| r["result"]["kind"] == "deferred")
            .unwrap()["id"]
            .clone();
        f.clock.0.store(2000, Ordering::SeqCst);
        let runs = f.runner(Some(limits), true).pass().unwrap();
        assert_eq!(f.spawns(), 2);
        assert_eq!(
            runs.iter().find(|r| r["id"] == deferred).unwrap()["result"]["kind"],
            "created"
        );
        assert!(
            f.client
                .reads
                .lock()
                .unwrap()
                .iter()
                .all(|t| t == "thr_syn_1"),
            "only original loop threads are read"
        );
        f.runner(Some(limits), true).pass().unwrap();
        assert_eq!(
            f.client.reads.lock().unwrap().last().unwrap(),
            "thr_syn_2",
            "a new original run remains unsettled"
        );
    }
}
#[test]
fn runner_pending_starting_active_and_unknown_hold_slots() {
    for status in [
        Some("pending"),
        Some("starting"),
        Some("active"),
        None,
        Some("unknown-synthetic"),
    ] {
        let f = Fixture::new(200, 0, false);
        f.status(status);
        let runner = f.runner(Some(approved()), true);
        for _ in 0..6 {
            runner.pass().unwrap();
        }
        assert_eq!(
            f.spawns(),
            if matches!(status, Some("pending" | "starting" | "active")) {
                12
            } else {
                3
            }
        );
    }
}
#[test]
fn runner_uncertain_attempts_are_never_retried() {
    let f = Fixture::new(1, 0, true);
    let runner = f.runner(Some(approved()), true);
    let before = runner.pass().unwrap();
    assert_eq!(before[0]["result"]["kind"], "uncertain");
    assert_eq!(runner.pass().unwrap(), before);
    assert_eq!(f.spawns(), 1);
}
