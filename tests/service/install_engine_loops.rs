//! AC3: native loop consumer, actual scheduler, fresh processes and durable files.
//! Synthetic immutable definitions, positive fixture-only approval and fake client.
use super::capacity::{occupancy_reads, reported_status};
use super::*;

fn history(f: &Fixture) -> Vec<Value> {
    openwiz_store::loops::storage::Storage::open(&f.state)
        .unwrap()
        .runs()
        .unwrap()
}

fn wake(f: &Fixture, at: u64) {
    let output = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "installed_engine_loops::scheduled_loop_process",
            "--nocapture",
        ])
        .env("OPENWIZ_IF5_LOOP_ROOT", &f.root)
        .env("OPENWIZ_IF5_LOOP_AT", at.to_string())
        .stdin(std::process::Stdio::null())
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        output.stderr.is_empty(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn scheduled_loop_process() {
    let Some(root) = std::env::var_os("OPENWIZ_IF5_LOOP_ROOT") else {
        return;
    };
    let root = PathBuf::from(root);
    let checkout = root.join("checkout");
    let state = root.join("state");
    let definition =
        serde_json::from_slice(&fs::read(checkout.join("loops/loop.json")).unwrap()).unwrap();
    let at = std::env::var("OPENWIZ_IF5_LOOP_AT")
        .unwrap()
        .parse()
        .unwrap();
    // Parent owns the fixture and cleanup. Every child reconstructs all runner,
    // approval, scheduler, client, store and clock objects from persisted inputs.
    let fixture = std::mem::ManuallyDrop::new(Fixture {
        root,
        state,
        definition,
        clock: Arc::new(FakeClock {
            now: AtomicU64::new(at),
            base: Instant::now(),
            timeout_marker: checkout.join("timeout-ready"),
        }),
        checkout,
    });
    let mut scheduler = openwiz_service::scheduler::Scheduler::default();
    fixture
        .runner()
        .register(&mut scheduler, std::num::NonZeroU64::new(1).unwrap())
        .unwrap();
    assert!(scheduler.poll(0).unwrap().is_empty());
    assert_eq!(scheduler.poll(1).unwrap(), ["loops.v1"]);
    scheduler.wait("loops.v1").unwrap();
}

#[test]
fn occupancy_is_sampled_once_in_each_fresh_scheduled_pass() {
    for status in ["pending", "starting", "active", "synthetic-unknown-status"] {
        let f = Fixture::new("printf finding");
        wake(&f, 1000);
        let first = history(&f);
        assert_eq!(first.len(), 1);
        assert_eq!(first[0]["result"]["kind"], "created");
        reported_status(&f, status);
        for _ in 0..2 {
            let before = occupancy_reads(&f);
            wake(&f, 1000);
            assert_eq!(occupancy_reads(&f) - before, 1, "{status}");
            assert_eq!(history(&f), first);
            assert_eq!(f.spawns().len(), 1);
        }
    }
}

#[test]
fn terminal_occupancy_stays_retired_after_scheduled_process_restart() {
    for status in ["idle", "error"] {
        let mut f = Fixture::new("printf finding");
        f.definition["wake"] = json!({"kind":"interval","every_ms":500,"anchor_ms":1000});
        f.definition["budget"]["max_agent_starts"] = json!(10);
        f.commit();
        wake(&f, 1000);
        let original = history(&f).remove(0);
        reported_status(&f, status);
        let before = occupancy_reads(&f);
        wake(&f, 1000);
        assert_eq!(occupancy_reads(&f) - before, 1);
        let settled = occupancy_reads(&f);
        reported_status(&f, "synthetic-unknown-status");
        wake(&f, 1500);
        assert_eq!(
            occupancy_reads(&f),
            settled,
            "{status}: retired run is not sampled again"
        );
        assert_eq!(f.spawns().len(), 2, "settlement frees capacity");
        assert_eq!(
            history(&f).iter().find(|run| run["id"] == original["id"]),
            Some(&original)
        );
        // The fake reuses its thread ID. Retirement belongs to the old run;
        // the replacement occurrence still occupies capacity across restart.
        wake(&f, 2000);
        assert_eq!(occupancy_reads(&f) - settled, 1);
        assert_eq!(f.spawns().len(), 2);
    }
}

#[test]
fn scheduled_stdout_byte_bound_refuses_oversize_before_finding_or_dispatch() {
    for mode in ["active", "shadow"] {
        for text in ["x".repeat(16385), "é".repeat(8193)] {
            let mut f = Fixture::new(&format!("printf '{text}'"));
            f.definition["mode"] = json!(mode);
            f.commit();
            wake(&f, 1000);
            let runs = history(&f);
            assert_eq!(runs.len(), 1);
            assert_eq!(runs[0]["result"]["kind"], "check_failed");
            assert!(runs[0]["result"].get("finding").is_none());
            assert_eq!(f.spawns().len(), 0);
            let saved = fs::read(f.state.join(format!(
                "service/loops/runs/{}.json",
                runs[0]["id"].as_str().unwrap()
            )))
            .unwrap();
            assert!(saved.len() < 1024, "bounded failure record");
            assert_eq!(serde_json::from_slice::<Value>(&saved).unwrap(), runs[0]);
            wake(&f, 1000);
            assert_eq!(history(&f), runs);
            assert_eq!(f.spawns().len(), 0);
        }
    }
    for text in ["x".repeat(16384), "é".repeat(8192)] {
        let mut f = Fixture::new(&format!("printf '{text}'"));
        f.definition["mode"] = json!("shadow");
        f.commit();
        wake(&f, 1000);
        let runs = history(&f);
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0]["result"], json!({"kind":"shadow","finding":text}));
        assert_eq!(f.spawns().len(), 0);
    }
}
