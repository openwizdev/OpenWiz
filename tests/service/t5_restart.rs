//! The actual scheduler, stop flag and durable tick state, controlled clocks.
use super::*;
use openwiz_service::{scheduler::Scheduler, state::State, tick};
use serde_json::json;
use std::{
    num::NonZeroU64,
    sync::{Arc, Mutex, mpsc},
    thread,
};
pub(super) fn state(f: &Fixture) -> Arc<Mutex<State>> {
    DirBuilder::new()
        .mode(0o700)
        .create(f.0.join("service"))
        .unwrap();
    fs::write(f.0.join("service/config.json"), json!({
        "schema":"openwiz.service-config.v1","repository":{"owner":"synthetic-owner","name":"synthetic-repo"},
        "project":"prj_syn_1","orchestrator_thread":"thr_syn_1","service_issue":901,
        "github_app":{"app_id":1001,"installation_id":2002},"tick":{"every_s":2},"health":{"every_s":60},
        "server":{"port":7370,"allowed_host":null,"probe_timeout_s":RUN_BUDGET.as_secs()}
    }).to_string()).unwrap();
    fs::set_permissions(
        f.0.join("service/config.json"),
        fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    Arc::new(Mutex::new(State::load(&f.0, 1000).unwrap()))
}
#[test]
fn cooperative_restart_confirms_completion_and_saved_outcome_before_replacement() {
    let f = Fixture::new();
    let state = state(&f);
    let saved = state.clone();
    let calls = Arc::new(AtomicU64::new(0));
    let count = calls.clone();
    let (entered_tx, entered_rx) = mpsc::channel();
    let mut jobs = Scheduler::default();
    tick::register_with_control(
        &mut jobs,
        NonZeroU64::new(2).unwrap(),
        state.clone(),
        || 2000,
        move |flag| {
            let n = count.fetch_add(1, Ordering::SeqCst);
            entered_tx.send(n).unwrap();
            if n == 0 {
                while !flag.load(Ordering::SeqCst) {
                    thread::park_timeout(Duration::from_millis(1));
                }
            } else {
                assert_eq!(
                    saved.lock().unwrap().snapshot()["tick"]["last_ended"]["how"],
                    "stopped"
                );
            }
            Ok(())
        },
    )
    .unwrap();
    assert_eq!(jobs.poll(2).unwrap(), [tick::JOB]);
    assert_eq!(entered_rx.recv_timeout(RUN_BUDGET).unwrap(), 0);
    jobs.restart_tick(deadline()).unwrap();
    jobs.wait(tick::JOB).unwrap();
    assert_eq!(entered_rx.try_recv(), Ok(1));
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    let after = state.lock().unwrap().snapshot().clone();
    assert_eq!(
        after["tick"],
        json!({"running":null,"last_ended":{"started_at":2000,"ended_at":2000,"how":"finished"}})
    );
    assert_eq!(State::load(&f.0, 2000).unwrap().snapshot(), &after);
    assert!(
        jobs.poll(3).unwrap().is_empty(),
        "restart does not shift original cadence"
    );
}
#[test]
fn uncertain_stop_keeps_the_old_handle_and_cannot_overlap_or_replace_other_jobs() {
    let f = Fixture::new();
    let state = state(&f);
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release = Mutex::new(release_rx);
    let calls = Arc::new(AtomicU64::new(0));
    let count = calls.clone();
    let mut jobs = Scheduler::default();
    tick::register_with_control(
        &mut jobs,
        NonZeroU64::new(2).unwrap(),
        state,
        || 2000,
        move |_| {
            let n = count.fetch_add(1, Ordering::SeqCst);
            entered_tx.send(n).unwrap();
            if n == 0 {
                release.lock().unwrap().recv_timeout(RUN_BUDGET).unwrap();
            }
            Ok(())
        },
    )
    .unwrap();
    let (other_tx, other_rx) = mpsc::channel();
    jobs.register("synthetic-other", NonZeroU64::new(3).unwrap(), move || {
        other_tx.send(()).unwrap()
    })
    .unwrap();
    assert_eq!(jobs.poll(2).unwrap(), [tick::JOB]);
    assert_eq!(entered_rx.recv_timeout(RUN_BUDGET).unwrap(), 0);
    assert!(jobs.restart_tick(Instant::now()).is_err());
    assert_eq!(jobs.poll(3).unwrap(), ["synthetic-other"]);
    jobs.wait("synthetic-other").unwrap();
    assert_eq!(other_rx.try_recv(), Ok(()));
    assert!(jobs.poll(4).unwrap().is_empty());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    release_tx.send(()).unwrap();
    jobs.wait(tick::JOB).unwrap();
    jobs.restart_tick(deadline()).unwrap();
    jobs.wait(tick::JOB).unwrap();
    assert_eq!(entered_rx.try_recv(), Ok(1));
    assert!(jobs.poll(5).unwrap().is_empty());
    assert_eq!(jobs.poll(6).unwrap(), [tick::JOB, "synthetic-other"]);
    jobs.wait(tick::JOB).unwrap();
    jobs.wait("synthetic-other").unwrap();
    assert_eq!(entered_rx.try_recv(), Ok(2));
    assert_eq!(other_rx.try_recv(), Ok(()));
}
