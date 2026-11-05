//! EP3: source-clock freshness and the shared read runner, with held reads.
use crate::{e11_decisions_support as s, fake::Fake, http};
use openwiz_core::{model::Timestamp, ops::Clock};
use openwiz_server::{Config, Limits};
use serde_json::json;
use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};

struct StepClock {
    first: AtomicBool,
    start: i64,
    end: i64,
}
impl Clock for StepClock {
    fn now(&self) -> Timestamp {
        Timestamp(if !self.first.swap(true, Ordering::SeqCst) {
            self.start
        } else {
            self.end
        })
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}

#[test]
fn e11_decisions_freshness_uses_oldest_source_time_and_a_controlled_clock() {
    for (index, end, state) in [
        (0, 1700000070000, "fresh"),
        (1, 1700000070001, "stale"),
        (2, 1699999999999, "unknown"),
    ] {
        let room = Fake::new(&format!("e11_clock_room_{index}"), "normal");
        let gh = s::fake(&format!("e11_clock_gh_{index}"), vec![]);
        let server = s::serve_with(
            &gh,
            &room,
            Config::default(),
            Ok(None),
            Arc::new(StepClock {
                first: AtomicBool::new(false),
                start: 1700000000000,
                end,
            }),
        );
        let value = server.get("/api/v1/decisions").json();
        s::check(&value);
        assert_eq!(value["snapshot_at"], json!(end));
        assert_eq!(value["freshness"]["state"], state);
        assert_eq!(value["orchestrator"]["freshness"]["state"], state);
        if state != "unknown" {
            assert_eq!(
                value["freshness"]["snapshot_at"],
                json!({"known":1700000000000_u64})
            );
        }
    }
}

#[test]
fn e11_decisions_shares_only_inflight_reads_and_retains_a_timed_out_runs_slot() {
    let room = Fake::new("e11_slots_room", "normal");
    let gh = s::fake("e11_slots_gh", vec![]);
    s::change(&gh, |v| {
        v["responses"].as_array_mut().unwrap().insert(
            0,
            json!({"argv":["repo","view","--json","nameWithOwner"],"hang":true}),
        )
    });
    let config = Config {
        limits: Limits {
            max_core_runs: 1,
            slot_wait: Duration::from_millis(50),
            // Recovery's fresh reads need room on a busy host (#2645):
            // scaled to one unheld decisions read timed now. Stay well below
            // the 15-second read timeout so the hang still holds at 504.
            request_deadline: crate::real_time::scaled(
                "e11_slots_deadline",
                Duration::from_secs(2),
                Duration::from_secs(10),
                || {
                    let room = Fake::new("e11_slots_calibrate_room", "normal");
                    let gh = s::fake("e11_slots_calibrate_gh", vec![]);
                    let clock = Arc::new(crate::fake::clock());
                    let server = s::serve_with(&gh, &room, Config::default(), Ok(None), clock);
                    assert_eq!(server.get("/api/v1/decisions").status, 200);
                },
            ),
            ..Limits::default()
        },
        ..Config::default()
    };
    let server = s::serve_with(&gh, &room, config, Ok(None), Arc::new(crate::fake::clock()));
    let addr = server.addr;
    let first = std::thread::spawn(move || http::get(addr, "/api/v1/decisions"));
    server.wait_for("fake read has started", |stats| {
        stats.core_runs == 1 && gh.hung_pid().is_some()
    });
    let second = std::thread::spawn(move || http::get(addr, "/api/v1/decisions"));
    server.wait_for("both callers share the held read", |stats| {
        stats.attached == 2
    });
    assert_eq!(first.join().unwrap().status, 504);
    assert_eq!(second.join().unwrap().status, 504);
    assert_eq!(server.server.stats().core_runs, 1);
    let busy = server.get("/api/v1/inventory");
    assert_eq!(busy.status, 503);
    assert_eq!(busy.header("Retry-After"), Some("5"));
    assert_eq!(gh.invocations().len(), 1);
    s::change(&gh, |v| {
        v["responses"].as_array_mut().unwrap().remove(0);
    });
    let pid: u32 = gh.hung_pid().unwrap().trim().parse().unwrap();
    assert!(
        std::process::Command::new("kill")
            .arg(pid.to_string())
            .status()
            .unwrap()
            .success()
    );
    server.wait_for(
        "held run finishes after its own child is stopped",
        |stats| stats.core_runs == 0,
    );
    for _ in 0..2 {
        assert_eq!(server.get("/api/v1/decisions").status, 200);
    }
    let repo: Vec<_> = ["repo", "view", "--json", "nameWithOwner"]
        .into_iter()
        .map(str::to_owned)
        .collect();
    assert_eq!(
        gh.invocations()
            .iter()
            .filter(|args| **args == repo)
            .count(),
        3
    );
}
