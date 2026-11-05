//! Synthetic jobs and a controlled monotonic clock; no live tools.
use openwiz_service::scheduler::Scheduler;
use std::num::NonZeroU64;
use std::sync::mpsc;

fn seconds(value: u64) -> NonZeroU64 {
    NonZeroU64::new(value).unwrap()
}

#[test]
fn registered_jobs_start_at_their_deadlines_without_catching_up_missed_runs() {
    let mut scheduler = Scheduler::default();
    let (tx, rx) = mpsc::channel();
    for (name, period) in [("synthetic-fast", 3), ("synthetic-slow", 5)] {
        let tx = tx.clone();
        scheduler
            .register(name, seconds(period), move || tx.send(name).unwrap())
            .unwrap();
    }
    for time in [0, 1, 2] {
        assert_eq!(scheduler.poll(time).unwrap(), Vec::<String>::new());
    }
    assert_eq!(scheduler.poll(3).unwrap(), ["synthetic-fast"]);
    scheduler.wait("synthetic-fast").unwrap();
    assert_eq!(rx.try_recv().unwrap(), "synthetic-fast");
    assert_eq!(scheduler.poll(4).unwrap(), Vec::<String>::new());
    assert_eq!(scheduler.poll(5).unwrap(), ["synthetic-slow"]);
    scheduler.wait("synthetic-slow").unwrap();
    assert_eq!(rx.try_recv().unwrap(), "synthetic-slow");
    assert_eq!(scheduler.poll(6).unwrap(), ["synthetic-fast"]);
    scheduler.wait("synthetic-fast").unwrap();
    assert_eq!(rx.try_recv().unwrap(), "synthetic-fast");
    // A delayed poll starts each overdue job just once, retaining cadence.
    assert_eq!(
        scheduler.poll(16).unwrap(),
        ["synthetic-fast", "synthetic-slow"]
    );
    scheduler.wait("synthetic-fast").unwrap();
    scheduler.wait("synthetic-slow").unwrap();
    let mut ran = [rx.try_recv().unwrap(), rx.try_recv().unwrap()];
    ran.sort();
    assert_eq!(ran, ["synthetic-fast", "synthetic-slow"]);
    assert!(rx.try_recv().is_err());
    assert!(scheduler.poll(17).unwrap().is_empty());
    assert_eq!(scheduler.poll(18).unwrap(), ["synthetic-fast"]);
    scheduler.wait("synthetic-fast").unwrap();
    assert_eq!(rx.try_recv().unwrap(), "synthetic-fast");
    assert!(rx.try_recv().is_err());
}

#[test]
fn a_held_job_never_overlaps_and_does_not_block_another_job() {
    let mut scheduler = Scheduler::default();
    let (started_tx, started_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release = std::sync::Mutex::new(release_rx);
    scheduler
        .register("held", seconds(2), move || {
            started_tx.send(()).unwrap();
            release.lock().unwrap().recv().unwrap();
        })
        .unwrap();
    let (tx, rx) = mpsc::channel();
    scheduler
        .register("other", seconds(3), move || tx.send(()).unwrap())
        .unwrap();
    assert_eq!(scheduler.poll(2).unwrap(), ["held"]);
    started_rx
        .recv_timeout(std::time::Duration::from_secs(5))
        .unwrap();
    assert_eq!(scheduler.poll(6).unwrap(), ["other"]);
    scheduler.wait("other").unwrap();
    assert_eq!(rx.try_recv(), Ok(()));
    assert!(started_rx.try_recv().is_err());
    release_tx.send(()).unwrap();
    scheduler.wait("held").unwrap();
    assert!(scheduler.poll(7).unwrap().is_empty());
    assert_eq!(scheduler.poll(8).unwrap(), ["held"]);
    release_tx.send(()).unwrap();
    scheduler.wait("held").unwrap();
    assert_eq!(started_rx.try_recv(), Ok(()));
    assert!(started_rx.try_recv().is_err());
}

#[test]
fn no_implicit_jobs_and_no_ambiguous_job_names() {
    let mut scheduler = Scheduler::default();
    assert!(scheduler.poll(10_000).unwrap().is_empty());
    scheduler.register("synthetic", seconds(1), || {}).unwrap();
    assert!(scheduler.register("synthetic", seconds(1), || {}).is_err());
    assert!(scheduler.register("", seconds(1), || {}).is_err());
}

#[test]
fn panicking_jobs_identify_the_registered_job_without_exposing_the_payload() {
    for (name, expected) in [
        (
            "synthetic-job-a",
            "scheduled job \"synthetic-job-a\" panicked",
        ),
        (
            "synthetic-job-b",
            "scheduled job \"synthetic-job-b\" panicked",
        ),
    ] {
        for reap_with_poll in [false, true] {
            let mut scheduler = Scheduler::default();
            scheduler
                .register(name, seconds(1), || panic!("synthetic-body-canary"))
                .unwrap();
            assert_eq!(scheduler.poll(1).unwrap(), [name]);
            let error = if reap_with_poll {
                let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
                loop {
                    match scheduler.poll(1) {
                        Err(error) => break error,
                        Ok(jobs) => assert!(jobs.is_empty()),
                    }
                    assert!(std::time::Instant::now() < deadline, "job did not finish");
                    std::thread::yield_now();
                }
            } else {
                scheduler.wait(name).unwrap_err()
            };
            assert_eq!(error.kind(), std::io::ErrorKind::Other);
            let detail = error.to_string();
            assert!(!detail.contains("synthetic-body-canary"));
            assert_eq!(detail, expected);
        }
    }
}

#[test]
fn panicking_job_identity_reaches_the_service_error_without_its_payload() {
    use std::{
        fs::{self, DirBuilder, OpenOptions},
        io::Write,
        net::TcpListener,
        os::unix::fs::{DirBuilderExt, OpenOptionsExt},
        path::PathBuf,
        thread,
        time::Duration,
    };

    struct Fixture(PathBuf);
    impl Drop for Fixture {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }

    for (name, expected) in [
        (
            "synthetic-job-a",
            "the registered-job scheduler failed: scheduled job \"synthetic-job-a\" panicked",
        ),
        (
            "synthetic-job-b",
            "the registered-job scheduler failed: scheduled job \"synthetic-job-b\" panicked",
        ),
    ] {
        let f =
            Fixture(std::env::temp_dir().join(format!("ow-1887-{}-{name}", std::process::id())));
        for path in [&f.0, &f.0.join("service"), &f.0.join("web")] {
            DirBuilder::new().mode(0o700).create(path).unwrap();
        }
        fs::write(f.0.join("web/index.html"), "synthetic page").unwrap();
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let config = serde_json::json!({
            "schema": "openwiz.service-config.v1",
            "repository": {"owner": "synthetic-owner", "name": "synthetic-repo"},
            "project": "prj_syn_0001", "orchestrator_thread": "thr_syn_0001",
            "service_issue": 901, "github_app": {"app_id": 1001, "installation_id": 2002},
            "tick": {"every_s": 300}, "health": {"every_s": 60},
            "server": {"port": listener.local_addr().unwrap().port(), "allowed_host": null, "probe_timeout_s": 10}
        });
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(f.0.join("service/config.json"))
            .unwrap();
        file.write_all(config.to_string().as_bytes()).unwrap();
        drop(file);
        let mut scheduler = Scheduler::default();
        scheduler
            .register(name, seconds(1), || panic!("synthetic-body-canary"))
            .unwrap();
        let (tx, rx) = mpsc::sync_channel(1);
        let root = f.0.clone();
        let runtime = thread::spawn(move || {
            tx.send(openwiz_service::runtime::run_with_binder(
                &root,
                &root.join("web"),
                &"a".repeat(40),
                scheduler,
                |_| Ok(listener),
            ))
            .unwrap();
        });
        // Only the synthetic job is due before this deadline; built-in jobs
        // remain idle, so no account, command source or live tool is reached.
        let error = rx
            .recv_timeout(Duration::from_secs(5))
            .expect("runtime did not return its scheduler failure")
            .unwrap_err();
        runtime.join().unwrap();
        assert!(!error.contains("synthetic-body-canary"));
        assert_eq!(error, expected);
    }
}

#[test]
fn a_job_registered_after_time_advanced_starts_one_period_later() {
    let mut scheduler = Scheduler::default();
    let (tx, rx) = mpsc::channel();
    assert!(scheduler.poll(10).unwrap().is_empty());
    scheduler
        .register("late", seconds(3), move || tx.send(()).unwrap())
        .unwrap();
    assert!(scheduler.poll(12).unwrap().is_empty());
    assert_eq!(scheduler.poll(13).unwrap(), ["late"]);
    scheduler.wait("late").unwrap();
    assert_eq!(rx.try_recv(), Ok(()));
    assert_eq!(rx.try_recv(), Err(mpsc::TryRecvError::Empty));
}

#[test]
fn a_late_registered_job_keeps_its_cadence_after_the_first_run() {
    let mut scheduler = Scheduler::default();
    let (tx, rx) = mpsc::channel();
    assert!(scheduler.poll(10).unwrap().is_empty());
    scheduler
        .register("late", seconds(3), move || tx.send(()).unwrap())
        .unwrap();
    assert_eq!(scheduler.poll(13).unwrap(), ["late"]);
    scheduler.wait("late").unwrap();
    assert_eq!(rx.try_recv(), Ok(()));
    assert_eq!(rx.try_recv(), Err(mpsc::TryRecvError::Empty));

    assert!(scheduler.poll(15).unwrap().is_empty());
    assert_eq!(scheduler.poll(16).unwrap(), ["late"]);
    scheduler.wait("late").unwrap();
    assert_eq!(rx.try_recv(), Ok(()));
    assert_eq!(rx.try_recv(), Err(mpsc::TryRecvError::Empty));
}
