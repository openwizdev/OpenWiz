//! Synthetic LP4 regression: health must read a run while its executor owns Storage.
use openwiz_core::{
    loops::{Capacity, Limits},
    model::Timestamp,
    ops::Clock,
};
use openwiz_service::{
    health::loops::{self, Evidence, Fault},
    loops::{Approval, Config, Runner, Services},
};
use openwiz_store::NewThreadFileStore;
use serde_json::{Value, json};
use std::{
    fs,
    num::NonZeroU64,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    process::Command,
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
        mpsc,
    },
    time::{Duration, Instant},
};

struct Fixture(PathBuf);
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn dir(p: &Path) {
    super::dirs::private_dir_all(p).unwrap();
}
fn git(p: &Path, args: &[&str]) {
    let out = Command::new("git")
        .current_dir(p)
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
}
struct Approved;
impl Approval for Approved {
    fn verify(&self, _: &Value, _: &str) -> bool {
        true
    }
}
struct ClockBarrier {
    entered: mpsc::SyncSender<()>,
    release: Mutex<mpsc::Receiver<()>>,
    once: AtomicU64,
}
impl Clock for ClockBarrier {
    fn now(&self) -> Timestamp {
        Timestamp(1000)
    }
    fn monotonic(&self) -> Instant {
        if self.once.fetch_add(1, Ordering::SeqCst) == 0 {
            self.entered.send(()).unwrap();
            self.release
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(30))
                .unwrap();
        }
        Instant::now()
    }
}
#[test]
fn l5b_stuck_run_is_read_while_pass_owns_storage() {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let fixture = Fixture(std::env::temp_dir().join(format!(
        "ow-l5b-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::SeqCst)
    )));
    let checkout = fixture.0.join("checkout");
    let state = fixture.0.join("state");
    dir(&checkout.join("loops"));
    dir(&state.join("service"));
    fs::write(state.join("service/config.json"), "{}").unwrap();
    fs::set_permissions(
        state.join("service/config.json"),
        fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    let definition = json!({"schema":"openwiz.loops.v1","kind":"definition","id":"loop-synthetic","name":"Synthetic loop","owner":"synthetic-owner","wake":{"kind":"once","at_ms":1000},"check":{"argv":["/bin/true"],"timeout_ms":100},"action":{"project":{"kind":"id","value":"prj_syn_0001"},"harness":"codex","model":"synthetic-model","effort":"high","brief":"Handle synthetic work only."},"authority":{"approved_by":"synthetic-owner","approval_ref":"synthetic-confirmation","scope":"Synthetic work."},"budget":{"window_ms":60000,"max_agent_starts":0},"enabled":true,"mode":"shadow","priority":"normal"});
    fs::write(checkout.join("loops/example.json"), definition.to_string()).unwrap();
    git(&checkout, &["init", "-q", "--initial-branch=main"]);
    git(&checkout, &["config", "user.name", "Synthetic Builder"]);
    git(
        &checkout,
        &["config", "user.email", "synthetic@example.invalid"],
    );
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
    let (entered, started) = mpsc::sync_channel(1);
    let (release, resume) = mpsc::sync_channel(1);
    let runner = Runner::new(
        Config {
            checkout: checkout.clone(),
            state: state.clone(),
            limits: Some(Limits {
                checks: Capacity {
                    max: 1,
                    urgent_reserve: 0,
                },
                agents: Capacity {
                    max: 0,
                    urgent_reserve: 0,
                },
            }),
        },
        Services {
            clock: Arc::new(ClockBarrier {
                entered,
                release: Mutex::new(resume),
                once: AtomicU64::new(0),
            }),
            // /bin/false is an absolute fake: any unexpected client call is refused.
            client: Arc::new(openwiz_adapter_cloudroom::source::CloudRoomSource::new(
                "/bin/false",
            )),
            new_threads: Arc::new(NewThreadFileStore::open(&state).unwrap()),
            approval: Some(Arc::new(Approved)),
        },
    );
    let pass = std::thread::spawn(move || runner.pass());
    started.recv_timeout(Duration::from_secs(30)).unwrap();
    let read = openwiz_service::loops::observe(&checkout, &state, 1101);
    let still_locked = openwiz_store::loops::storage::Storage::open(&state).is_err();
    release.send(()).unwrap();
    pass.join().unwrap().unwrap();
    assert!(
        still_locked,
        "fixture must retain the scheduler lock during observation"
    );
    let observations = read.expect("watchdog read must remain independent of the scheduler lock");
    assert_eq!(observations[0].disabled_by_failures, Evidence::Unknown);
    let plan = loops::plan(Evidence::Known(&observations), &[], 1101).unwrap();
    assert_eq!(plan.needs_you.len(), 1);
    assert!(
        matches!(&plan.needs_you[0].fault, Fault::Stuck { started_at_ms:1000, timeout_ms, .. } if *timeout_ms == NonZeroU64::new(100).unwrap())
    );
}

#[test]
fn l5b_removed_check_retains_its_immutable_timeout_and_partial_state_is_unknown() {
    for remove_subtree in [false, true] {
        removed_check_fixture(remove_subtree);
    }
}
fn removed_check_fixture(remove_subtree: bool) {
    let fixture = Fixture(std::env::temp_dir().join(format!(
        "ow-l5b-removed-{}-{remove_subtree}",
        std::process::id()
    )));
    let checkout = fixture.0.join("checkout");
    let state = fixture.0.join("state");
    dir(&checkout.join("loops"));
    dir(&state.join("service"));
    fs::write(state.join("service/config.json"), "{}").unwrap();
    fs::set_permissions(
        state.join("service/config.json"),
        fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    // A watchdog read on absent state must neither create state nor infer health.
    assert!(openwiz_store::loops::storage::read_snapshot(&state).is_err());
    assert!(!state.join("service/loops").exists());
    let mut definition: Value =
        serde_json::from_str(include_str!("../../loops/example.json")).unwrap();
    definition["enabled"] = json!(true);
    definition["wake"] = json!({"kind":"once","at_ms":1000});
    definition["check"]["timeout_ms"] = json!(100);
    fs::write(checkout.join("loops/example.json"), definition.to_string()).unwrap();
    fs::write(checkout.join("loops/README.md"), "Synthetic fixture.").unwrap();
    git(&checkout, &["init", "-q", "--initial-branch=main"]);
    git(&checkout, &["config", "user.name", "Synthetic Builder"]);
    git(
        &checkout,
        &["config", "user.email", "synthetic@example.invalid"],
    );
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
    let revision = openwiz_store::loops::repository::Repository(checkout.clone())
        .current()
        .unwrap()[0]
        .revision
        .clone();
    let run = json!({"schema":"openwiz.loops.v1","kind":"run","id":"run-synthetic","loop_id":"loop-syn-reminder","definition_revision":revision,"wake":{"kind":"once","due_at_ms":1000},"started_at_ms":1000,"updated_at_ms":1000,"cost":{"kind":"unknown","reason":"Synthetic fixture."},"result":{"kind":"checking"}});
    let storage = openwiz_store::loops::storage::Storage::open(&state).unwrap();
    let initial = openwiz_service::loops::observe(&checkout, &state, 1001).unwrap();
    assert_eq!(initial[0].next_due_at_ms, Evidence::Known(Some(1000)));
    let on_boundary = loops::plan(Evidence::Known(&initial), &[], 1000).unwrap();
    assert!(on_boundary.needs_you.is_empty());
    storage.save_run(&run).unwrap();
    let mut off = serde_json::Map::new();
    off.insert("loop-syn-reminder".into(), json!(false));
    storage.save_switches(&off).unwrap();
    let disabled = openwiz_service::loops::observe(&checkout, &state, 1100).unwrap();
    assert_eq!(disabled[0].next_due_at_ms, Evidence::Known(None));
    assert_eq!(disabled[0].disabled_by_failures, Evidence::Unknown);
    assert_eq!(
        loops::plan(Evidence::Known(&disabled), &[], 1100)
            .unwrap()
            .needs_you
            .len(),
        0,
        "the admitted check has not exceeded its limit before removal"
    );
    drop(storage);
    if remove_subtree {
        git(&checkout, &["rm", "-r", "loops"]);
    } else {
        git(&checkout, &["rm", "loops/example.json"]);
    }
    git(&checkout, &["commit", "-qm", "Remove synthetic definition"]);
    git(
        &checkout,
        &["update-ref", "refs/remotes/origin/main", "HEAD"],
    );
    if remove_subtree {
        assert!(
            openwiz_store::loops::repository::Repository(checkout.clone())
                .current()
                .is_err(),
            "the scheduler reader must retain its missing-subtree refusal"
        );
    }
    let observed = openwiz_service::loops::observe(&checkout, &state, 1101)
        .unwrap_or_else(|why| panic!("removed subtree={remove_subtree}: {why}"));
    let plan = loops::plan(Evidence::Known(&observed), &[], 1101).unwrap();
    assert_eq!(
        plan.needs_you.len(),
        1,
        "a removed definition cannot hide its still-running check"
    );
    assert!(
        matches!(&plan.needs_you[0].fault,Fault::Stuck{run_id,timeout_ms,..} if run_id.as_str()=="run-synthetic" && timeout_ms.get()==100)
    );
    let storage = openwiz_store::loops::storage::Storage::open(&state).unwrap();
    let mut terminal = run.clone();
    terminal["result"] = json!({"kind":"quiet"});
    storage.save_run(&terminal).unwrap();
    drop(storage);
    let recovered = openwiz_service::loops::observe(&checkout, &state, 1101).unwrap();
    assert!(
        loops::plan(Evidence::Known(&recovered), &plan.open, 1101)
            .unwrap()
            .open
            .is_empty()
    );
    if remove_subtree {
        // An absent path on an unverified default branch is still unread.
        git(
            &checkout,
            &["update-ref", "refs/remotes/origin/main", "HEAD~1"],
        );
        assert!(openwiz_service::loops::observe(&checkout, &state, 1101).is_err());
        git(
            &checkout,
            &["update-ref", "refs/remotes/origin/main", "HEAD"],
        );
        // A committed blob named loops is malformed, not an absent subtree.
        fs::write(checkout.join("loops"), "Synthetic non-tree loop root.").unwrap();
        git(&checkout, &["add", "loops"]);
        git(
            &checkout,
            &["commit", "-qm", "Synthetic malformed loop root"],
        );
        git(
            &checkout,
            &["update-ref", "refs/remotes/origin/main", "HEAD"],
        );
        assert!(openwiz_service::loops::observe(&checkout, &state, 1101).is_err());
        git(&checkout, &["rm", "loops"]);
        git(
            &checkout,
            &["commit", "-qm", "Restore absent synthetic loop root"],
        );
        git(
            &checkout,
            &["update-ref", "refs/remotes/origin/main", "HEAD"],
        );
        // A configuration/identity read failure must not become known empty.
        git(&checkout, &["config", "synthetic.unreviewed", "true"]);
        assert!(openwiz_service::loops::observe(&checkout, &state, 1101).is_err());
        git(&checkout, &["config", "--unset", "synthetic.unreviewed"]);
        assert!(openwiz_service::loops::observe(&checkout, &state, 1101).is_ok());
        // A genuine Git blob-read failure is not positive root absence.
        let blob = run["definition_revision"].as_str().unwrap();
        let object = checkout
            .join(".git/objects")
            .join(&blob[..2])
            .join(&blob[2..]);
        let saved = fs::read(&object).unwrap();
        fs::remove_file(&object).unwrap();
        assert!(openwiz_service::loops::observe(&checkout, &state, 1101).is_err());
        fs::write(object, saved).unwrap();
        assert!(openwiz_service::loops::observe(&checkout, &state, 1101).is_ok());
    }
    // Index-before-record admission must be refused as incomplete, not healthy.
    let index = state.join("service/loops/index.json");
    fs::write(&index, "[\"run-synthetic\",\"run-missing\"]").unwrap();
    assert!(openwiz_service::loops::observe(&checkout, &state, 1101).is_err());
}
