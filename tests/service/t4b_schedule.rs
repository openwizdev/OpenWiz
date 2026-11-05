//! Controlled-clock fixture proofs through the registered job and status API.
use super::*;
use openwiz_service::{scheduler::Scheduler, state, tick};
use std::{
    num::NonZeroU64,
    sync::{Arc, Mutex, mpsc},
};

fn report(state: &Arc<Mutex<State>>, now: u64) -> Value {
    state::status(
        state.lock().unwrap().snapshot(),
        &"a".repeat(40),
        1000,
        7370,
        None,
        now,
    )
    .unwrap()
}

#[test]
fn failure_waits_for_next_schedule_and_other_jobs_keep_running() {
    let f = Fixture::new();
    let state = Arc::new(Mutex::new(f.state()));
    let clock = Arc::new(AtomicU64::new(2000));
    let calls = Arc::new(AtomicU64::new(0));
    let mut scheduler = Scheduler::default();
    let (now, count) = (clock.clone(), calls.clone());
    tick::register_with(
        &mut scheduler,
        NonZeroU64::new(3).unwrap(),
        state.clone(),
        move || now.load(Ordering::SeqCst),
        move || {
            if count.fetch_add(1, Ordering::SeqCst) == 0 {
                Err("synthetic failure".into())
            } else {
                Ok(())
            }
        },
    )
    .unwrap();
    let (tx, rx) = mpsc::channel();
    scheduler
        .register("synthetic-other", NonZeroU64::new(2).unwrap(), move || {
            tx.send(()).unwrap()
        })
        .unwrap();
    assert!(scheduler.poll(1).unwrap().is_empty());
    assert_eq!(scheduler.poll(2).unwrap(), ["synthetic-other"]);
    scheduler.wait("synthetic-other").unwrap();
    assert_eq!(rx.try_recv(), Ok(()));
    assert_eq!(scheduler.poll(3).unwrap(), [tick::JOB]);
    scheduler.wait(tick::JOB).unwrap();
    assert_eq!(
        report(&state, 2000)["tick"],
        json!({"running":null,"last_ended":{"started_at":2000,"ended_at":2000,"how":"failed"}})
    );
    for at in [3, 4, 5] {
        let jobs = scheduler.poll(at).unwrap();
        assert!(!jobs.iter().any(|s| s == tick::JOB));
    }
    scheduler.wait("synthetic-other").unwrap();
    assert_eq!(rx.try_recv(), Ok(()));
    assert!(rx.try_recv().is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    clock.store(5000, Ordering::SeqCst);
    assert_eq!(scheduler.poll(6).unwrap(), [tick::JOB, "synthetic-other"]);
    scheduler.wait(tick::JOB).unwrap();
    scheduler.wait("synthetic-other").unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_eq!(
        report(&state, 5000)["tick"],
        json!({"running":null,"last_ended":{"started_at":5000,"ended_at":5000,"how":"finished"}})
    );
    assert_eq!(
        State::load(&f.0, 5000).unwrap().snapshot(),
        state.lock().unwrap().snapshot()
    );
    assert!(scheduler.poll(6).unwrap().is_empty());
    assert_eq!(calls.load(Ordering::SeqCst), 2);
}

#[test]
fn held_tick_reports_running_never_overlaps_and_keeps_concurrent_state() {
    let f = Fixture::new();
    let state = Arc::new(Mutex::new(f.state()));
    let (started_tx, started_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release = Mutex::new(release_rx);
    let clock = Arc::new(AtomicU64::new(2000));
    let now = clock.clone();
    let mut scheduler = Scheduler::default();
    tick::register_with(
        &mut scheduler,
        NonZeroU64::new(2).unwrap(),
        state.clone(),
        move || now.load(Ordering::SeqCst),
        move || {
            started_tx.send(()).unwrap();
            release
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(5))
                .unwrap();
            Ok(())
        },
    )
    .unwrap();
    assert_eq!(scheduler.poll(2).unwrap(), [tick::JOB]);
    started_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    assert_eq!(
        report(&state, 2000)["tick"],
        json!({"running":{"started_at":2000},"last_ended":null})
    );
    let saved: Value =
        serde_json::from_slice(&fs::read(f.0.join("service/state.json")).unwrap()).unwrap();
    assert_eq!(saved["tick"]["running"], json!({"started_at":2000}));
    {
        let mut state = state.lock().unwrap();
        let mut value = state.snapshot().clone();
        value["next_incident"] = json!(7);
        state.save(value).unwrap();
    }
    assert!(scheduler.poll(20).unwrap().is_empty());
    assert!(started_rx.try_recv().is_err());
    clock.store(3000, Ordering::SeqCst);
    release_tx.send(()).unwrap();
    scheduler.wait(tick::JOB).unwrap();
    assert_eq!(
        report(&state, 3000)["tick"],
        json!({"running":null,"last_ended":{"started_at":2000,"ended_at":3000,"how":"finished"}})
    );
    assert_eq!(state.lock().unwrap().snapshot()["next_incident"], 7);
    assert!(scheduler.poll(21).unwrap().is_empty());
    assert_eq!(scheduler.poll(22).unwrap(), [tick::JOB]);
    started_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    release_tx.send(()).unwrap();
    scheduler.wait(tick::JOB).unwrap();
    assert!(started_rx.try_recv().is_err());
}

#[test]
fn initial_state_save_failure_dispatches_nothing() {
    let f = Fixture::new();
    let state = Arc::new(Mutex::new(f.state()));
    let before = state.lock().unwrap().snapshot().clone();
    let calls = Arc::new(AtomicU64::new(0));
    let count = calls.clone();
    let mut scheduler = Scheduler::default();
    tick::register_with(
        &mut scheduler,
        NonZeroU64::new(1).unwrap(),
        state.clone(),
        || 2000,
        move || {
            count.fetch_add(1, Ordering::SeqCst);
            Ok(())
        },
    )
    .unwrap();
    fs::remove_file(f.0.join("service/state.json")).unwrap();
    DirBuilder::new()
        .mode(0o700)
        .create(f.0.join("service/state.json"))
        .unwrap();
    assert_eq!(scheduler.poll(1).unwrap(), [tick::JOB]);
    scheduler.wait(tick::JOB).unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(*state.lock().unwrap().snapshot(), before);
}

#[test]
fn failed_completion_save_recovers_before_the_next_scheduled_dispatch() {
    let f = Fixture::new();
    let state = Arc::new(Mutex::new(f.state()));
    let clock = Arc::new(AtomicU64::new(2000));
    let calls = Arc::new(AtomicU64::new(0));
    let (started_tx, started_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release = Mutex::new(release_rx);
    let root = f.0.clone();
    let count = calls.clone();
    let now = clock.clone();
    let mut scheduler = Scheduler::default();
    tick::register_with(
        &mut scheduler,
        NonZeroU64::new(3).unwrap(),
        state.clone(),
        move || now.load(Ordering::SeqCst),
        move || {
            if count.fetch_add(1, Ordering::SeqCst) == 0 {
                fs::rename(
                    root.join("service/state.json"),
                    root.join("service/saved.json"),
                )
                .unwrap();
                DirBuilder::new()
                    .mode(0o700)
                    .create(root.join("service/state.json"))
                    .unwrap();
                return Err("synthetic tick failure".into());
            }
            started_tx.send(()).unwrap();
            release
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(5))
                .unwrap();
            Ok(())
        },
    )
    .unwrap();
    assert_eq!(scheduler.poll(3).unwrap(), [tick::JOB]);
    scheduler.wait(tick::JOB).unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        report(&state, 2000)["tick"]["running"],
        json!({"started_at":2000})
    );
    assert!(scheduler.poll(5).unwrap().is_empty());
    fs::remove_dir(f.0.join("service/state.json")).unwrap();
    fs::rename(
        f.0.join("service/saved.json"),
        f.0.join("service/state.json"),
    )
    .unwrap();
    clock.store(5000, Ordering::SeqCst);
    assert_eq!(scheduler.poll(6).unwrap(), [tick::JOB]);
    started_rx
        .recv_timeout(Duration::from_secs(2))
        .expect("next schedule did not recover the completed tick");
    let tick = report(&state, 5000)["tick"].clone();
    assert_eq!(
        tick,
        json!({"running":{"started_at":5000},"last_ended":{"started_at":2000,"ended_at":2000,"how":"failed"}})
    );
    let saved: Value =
        serde_json::from_slice(&fs::read(f.0.join("service/state.json")).unwrap()).unwrap();
    assert_eq!(saved["tick"], tick, "recover and persist before dispatch");
    release_tx.send(()).unwrap();
    scheduler.wait(tick::JOB).unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_eq!(
        report(&state, 5000)["tick"]["last_ended"]["how"],
        "finished"
    );
}
