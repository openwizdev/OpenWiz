//! Planner admission remains enforced at the executor's public seam.
use super::*;
struct ExactApprovals(Vec<Value>);
impl Approval for ExactApprovals {
    fn verify(&self, definition: &Value, revision: &str) -> bool {
        revision.len() == 40 && self.0.contains(definition)
    }
}
pub(super) fn reported_status(f: &Fixture, status: &str) {
    let path = f.root.join("fake/scenario.json");
    let mut scenario: Value = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
    let fixture = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures/room-cli-v127/new-thread/thread-show-active.json");
    let mut shown: Value = serde_json::from_str(&fs::read_to_string(fixture).unwrap()).unwrap();
    shown["thread"]["status"] = json!(status);
    let response = scenario["responses"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|r| r["argv"][1] == "show")
        .unwrap();
    response.as_object_mut().unwrap().remove("stdout_file");
    response["stdout"] = json!(shown.to_string());
    fs::write(path, scenario.to_string()).unwrap();
}
#[test]
fn shared_agent_capacity_keeps_the_urgent_reserve() {
    let f = Fixture::new("printf finding");
    let mut urgent = f.definition.clone();
    urgent["id"] = json!("loop-urgent");
    urgent["priority"] = json!("urgent");
    fs::write(f.checkout.join("loops/urgent.json"), urgent.to_string()).unwrap();
    f.commit();
    let mut config = f.config();
    let limits = config.limits.as_mut().unwrap();
    limits.checks = Capacity {
        max: 2,
        urgent_reserve: 0,
    };
    limits.agents = Capacity {
        max: 1,
        urgent_reserve: 1,
    };
    let mut services = f.services(f.store());
    services.approval = Some(Arc::new(ExactApprovals(vec![f.definition.clone(), urgent])));
    let runner = Runner::new(config, services);
    let runs = runner.pass().unwrap();
    assert_eq!(runs.len(), 2);
    assert_eq!(
        runs.iter().find(|r| r["loop_id"] == "loop-urgent").unwrap()["result"]["kind"],
        "created"
    );
    assert_eq!(
        runs.iter()
            .find(|r| r["loop_id"] == "loop-synthetic")
            .unwrap()["result"]["kind"],
        "deferred"
    );
    assert_eq!(f.spawns().len(), 1);
    assert_eq!(runner.pass().unwrap(), runs);
    assert_eq!(f.spawns().len(), 1);
}
#[test]
fn rolling_budget_dispatches_the_same_deferred_run_when_it_opens() {
    let mut f = Fixture::new("printf finding");
    f.definition["wake"] = json!({"kind":"interval","every_ms":500,"anchor_ms":1000});
    f.definition["budget"]["window_ms"] = json!(1000);
    f.commit();
    reported_status(&f, "idle");
    let runner = f.runner();
    assert_eq!(runner.pass().unwrap().len(), 1);
    assert_eq!(f.spawns().len(), 1);
    f.clock.now.store(1500, Ordering::SeqCst);
    let runs = runner.pass().unwrap();
    assert_eq!(runs.len(), 2);
    let deferred = runs
        .iter()
        .find(|r| r["result"]["kind"] == "deferred")
        .unwrap()
        .clone();
    assert_eq!(f.spawns().len(), 1);
    f.clock.now.store(2000, Ordering::SeqCst);
    let after = runner.pass().unwrap();
    assert_eq!(after.len(), 2);
    assert_eq!(f.spawns().len(), 2);
    let resumed = after.iter().find(|r| r["id"] == deferred["id"]).unwrap();
    assert_eq!(resumed["started_at_ms"], 1500);
    assert_eq!(resumed["result"]["dispatch_at_ms"], 2000);
    assert_eq!(resumed["result"]["kind"], "created");
}
#[test]
fn unread_agent_occupancy_never_becomes_zero() {
    let mut f = Fixture::new("printf finding");
    f.definition["wake"] = json!({"kind":"interval","every_ms":500,"anchor_ms":1000});
    f.definition["budget"]["max_agent_starts"] = json!(10);
    f.commit();
    let runner = f.runner();
    assert_eq!(runner.pass().unwrap().len(), 1);
    reported_status(&f, "synthetic-unknown-status");
    f.clock.now.store(1500, Ordering::SeqCst);
    let runs = runner.pass().unwrap();
    assert_eq!(runs.len(), 2);
    assert_eq!(
        runs.iter()
            .filter(|r| r["result"]["kind"] == "deferred")
            .count(),
        1
    );
    assert_eq!(f.spawns().len(), 1);
}

pub(super) fn occupancy_reads(f: &Fixture) -> usize {
    fs::read_to_string(f.root.join("fake/invocations.log"))
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str::<Vec<String>>(line).unwrap())
        .filter(|argv| argv.get(1).is_some_and(|arg| arg == "show"))
        .count()
}

#[test]
fn occupancy_is_sampled_once_per_pass() {
    for status in ["pending", "starting", "active", "synthetic-unknown-status"] {
        let f = Fixture::new("printf finding");
        let runner = f.runner();
        let runs = runner.pass().unwrap();
        reported_status(&f, status);
        let before = occupancy_reads(&f);
        assert_eq!(runner.pass().unwrap(), runs);
        assert_eq!(occupancy_reads(&f) - before, 1, "{status}");
    }
}

#[test]
fn occupancy_settlement_survives_restart_and_unreadable_history() {
    struct CapacityClock(Arc<FakeClock>);
    impl Clock for CapacityClock {
        fn now(&self) -> Timestamp {
            self.0.now()
        }
        fn monotonic(&self) -> Instant {
            Instant::now()
        }
    }
    for status in ["idle", "error"] {
        let mut f = Fixture::new("printf finding");
        f.definition["wake"] = json!({"kind":"interval","every_ms":500,"anchor_ms":1000});
        f.definition["budget"]["max_agent_starts"] = json!(10);
        f.definition["check"]["timeout_ms"] = json!(openwiz_core::limits::RUN_BUDGET.as_millis());
        f.commit();
        // Keep scheduled time controlled, but give each process a fresh deadline.
        let runner = || {
            let mut services = f.services(f.store());
            services.clock = Arc::new(CapacityClock(f.clock.clone()));
            Runner::new(f.config(), services)
        };
        let created = runner().pass().unwrap().remove(0);
        assert_eq!(created["result"]["kind"], "created", "{created}");
        reported_status(&f, status);
        assert_eq!(runner().pass().unwrap(), vec![created.clone()]);
        let before = occupancy_reads(&f);
        reported_status(&f, "synthetic-unknown-status");
        f.clock.now.store(1500, Ordering::SeqCst);
        let runs = runner().pass().unwrap();
        assert_eq!(occupancy_reads(&f), before, "{status} stays retired");
        assert_eq!(f.spawns().len(), 2, "settled history frees capacity");
        assert_eq!(
            runs.iter().find(|r| r["id"] == created["id"]),
            Some(&created)
        );
        let next = runs.iter().find(|r| r["started_at_ms"] == 1500).unwrap();
        assert_eq!(next["result"]["kind"], "created", "{next}");
        let settled: Value =
            serde_json::from_slice(&fs::read(f.state.join("service/loops/settled.json")).unwrap())
                .unwrap();
        let old_id = created["id"].as_str().unwrap();
        assert_eq!(settled, json!({old_id: created["result"]["thread_id"]}));
        // The fixture reuses a thread ID: settlement belongs to the old run.
        f.clock.now.store(2000, Ordering::SeqCst);
        runner().pass().unwrap();
        assert_eq!(occupancy_reads(&f) - before, 1);
        assert_eq!(f.spawns().len(), 2, "new run is still unsettled");
    }
}

#[test]
fn occupancy_of_reconciled_receipt_is_sampled_once() {
    let mut f = Fixture::new("printf finding");
    f.definition["wake"] = json!({"kind":"interval","every_ms":500,"anchor_ms":1000});
    f.definition["budget"]["max_agent_starts"] = json!(10);
    f.commit();
    let runner = f.runner_with(Arc::new(CrashAtReceipt {
        store: NewThreadFileStore::open(&f.state).unwrap(),
        after_save: true,
    }));
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| runner.pass())).is_err());
    drop(runner);
    f.clock.now.store(1500, Ordering::SeqCst);
    let before = occupancy_reads(&f);
    let runs = f.runner().pass().unwrap();
    assert_eq!(
        runs.iter()
            .filter(|r| r["result"]["kind"] == "created")
            .count(),
        1
    );
    assert_eq!(
        runs.iter()
            .filter(|r| r["result"]["kind"] == "deferred")
            .count(),
        1
    );
    assert_eq!(occupancy_reads(&f) - before, 1);
    assert_eq!(f.spawns().len(), 1);
}

#[test]
fn occupancy_read_failure_holds_dispatch_and_later_idle_recovers() {
    let mut f = Fixture::new("printf finding");
    f.definition["wake"] = json!({"kind":"interval","every_ms":500,"anchor_ms":1000});
    f.definition["budget"]["max_agent_starts"] = json!(10);
    f.commit();
    f.runner().pass().unwrap();
    let path = f.root.join("fake/scenario.json");
    let mut scenario: Value = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
    let show = scenario["responses"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|r| r["argv"][1] == "show")
        .unwrap();
    show["exit"] = json!(1);
    fs::write(&path, scenario.to_string()).unwrap();
    f.clock.now.store(1500, Ordering::SeqCst);
    let before = occupancy_reads(&f);
    let runs = f.runner().pass().unwrap();
    assert_eq!(occupancy_reads(&f) - before, 1);
    assert_eq!(
        runs.iter()
            .filter(|r| r["result"]["kind"] == "deferred")
            .count(),
        1
    );
    assert_eq!(f.spawns().len(), 1);
    scenario["responses"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|r| r["argv"][1] == "show")
        .unwrap()["exit"] = json!(0);
    fs::write(path, scenario.to_string()).unwrap();
    reported_status(&f, "idle");
    f.runner().pass().unwrap();
    assert_eq!(f.spawns().len(), 2);
}

#[test]
fn occupancy_sidecar_refuses_corrupt_or_unrelated_settlement() {
    for case in ["[]", "null", "{", "unknown", "thread", "type", "duplicate"] {
        let f = Fixture::new("printf finding");
        let run = f.runner().pass().unwrap().remove(0);
        let id = run["id"].as_str().unwrap();
        let bad = match case {
            "unknown" => json!({"unknown-run":"thr_syn_0021"}).to_string(),
            "thread" => json!({id:"thr_syn_other"}).to_string(),
            "type" => json!({id:true}).to_string(),
            "duplicate" => format!("{{\"{id}\":\"thr_syn_0021\",\"{id}\":\"thr_syn_0021\"}}"),
            _ => case.to_owned(),
        };
        let path = f.state.join("service/loops/settled.json");
        fs::write(&path, &bad).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        assert!(f.runner().pass().is_err(), "{bad}");
        assert_eq!(f.spawns().len(), 1);
    }
}

#[test]
fn occupancy_sidecar_requires_private_regular_storage() {
    for case in ["symlink", "hardlink", "public", "directory"] {
        let f = Fixture::new("printf finding");
        f.runner().pass().unwrap();
        let path = f.state.join("service/loops/settled.json");
        let other = f.root.join("other.json");
        fs::write(&other, "{}").unwrap();
        fs::set_permissions(&other, fs::Permissions::from_mode(0o600)).unwrap();
        match case {
            "symlink" => symlink(other, &path).unwrap(),
            "hardlink" => fs::hard_link(other, &path).unwrap(),
            "public" => {
                fs::write(&path, "{}").unwrap();
                fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
            }
            _ => private_dir(&path),
        }
        assert!(f.runner().pass().is_err(), "{case}");
        assert_eq!(f.spawns().len(), 1);
    }
}
