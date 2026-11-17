//! C5: synthetic repositories/processes only, never a live update.
use openwiz_service::update;
use std::path::Path;
#[path = "t6_fixture.rs"]
mod fixture;
#[path = "../fleet/schema.rs"]
mod schema;

#[test]
fn the_selected_loopback_port_survives_a_competing_listener_before_start() {
    let f = fixture::Fixture::new();
    let old = f.head();
    f.install_old(&old);
    // Force the competing bind into the selection-to-start gap. Keep it alive
    // until after readiness; no timing, load, or repeated port selection needed.
    let competitor = f.occupy_configured_port();
    let port = competitor.local_addr().unwrap().port();
    eprintln!("competing listener acquired the fixture's configured port");
    for _ in 0..2 {
        let running = f.start();
        let status = f.status();
        assert_eq!(status["service"]["build"], old);
        assert_ne!(status["server"]["port"], port);
        f.only_existing_http_listener(&running);
        f.reject_inbound_update();
        drop(running);
    }
    drop(competitor);
}

#[test]
fn install_and_start_do_not_race_unguarded_forks() {
    use std::{
        process::Command,
        sync::{
            Barrier,
            atomic::{AtomicBool, Ordering},
        },
    };

    let f = fixture::Fixture::new();
    let old = f.head();
    f.install_old(&old);
    let stop = AtomicBool::new(false);
    let ready = Barrier::new(5);
    let failures = std::thread::scope(|scope| {
        for _ in 0..4 {
            let (f, old, stop, ready) = (&f, &old, &stop, &ready);
            scope.spawn(move || {
                ready.wait();
                while !stop.load(Ordering::Relaxed) {
                    // Intentionally fork outside the fixture helpers, like
                    // direct test commands and System executors do.
                    let out = Command::new("git")
                        .args(["rev-parse", "HEAD"])
                        .current_dir(&f.repo)
                        .output()
                        .unwrap();
                    assert!(out.status.success());
                    assert_eq!(String::from_utf8(out.stdout).unwrap().trim(), *old);
                }
            });
        }
        ready.wait();
        let result = std::panic::catch_unwind(|| {
            let mut failures = 0;
            for _ in 0..1_000 {
                f.install_old(&old);
                match std::panic::catch_unwind(|| f.start()) {
                    Ok(running) => drop(running),
                    Err(_) => failures += 1,
                }
            }
            failures
        });
        stop.store(true, Ordering::Relaxed);
        result.unwrap()
    });
    assert_eq!(failures, 0, "service starts failed under unguarded forks");
}

#[test]
fn a_failed_gate_reaps_descendants_before_retaining_the_old_build() {
    let f = fixture::Fixture::new();
    fixture::file(
        &f.repo.join(".github/actions/docs-only/test.sh"),
        "sleep 120 &\necho $! > synthetic-child.pid.tmp\nmv synthetic-child.pid.tmp synthetic-child.pid\nexit 1\n",
    );
    let call = update::gate_call(
        Path::new("sh"),
        &[".github/actions/docs-only/test.sh"],
        &f.repo,
        &f.head(),
    )
    .unwrap();
    assert!(update::Executor::run(&update::System, &call).is_err());
    let pid = std::fs::read_to_string(f.repo.join("synthetic-child.pid"))
        .unwrap()
        .trim()
        .parse::<u32>()
        .unwrap();
    let until = std::time::Instant::now() + std::time::Duration::from_secs(2);
    let alive = loop {
        let value = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap_or_default();
        if value.is_empty() || value.split_whitespace().nth(2) == Some("Z") {
            break false;
        }
        if std::time::Instant::now() >= until {
            break true;
        }
        std::thread::park_timeout(std::time::Duration::from_millis(10));
    };
    if alive {
        let _ = std::process::Command::new("/bin/kill")
            .args(["-KILL", &pid.to_string()])
            .status();
    }
    assert!(!alive, "a descendant outlived a failed gate");
}

#[test]
fn fetch_and_build_failures_keep_the_old_selection_with_the_exact_failed_step() {
    use std::sync::Arc;
    struct Fail(&'static str);
    impl update::Executor for Fail {
        fn run(&self, call: &update::Call) -> Result<String, String> {
            if (self.0 == "fetch" && call.argv().iter().any(|a| a == "fetch"))
                || (self.0 == "build"
                    && call.program() == Path::new("npm")
                    && call.argv().first().is_some_and(|a| a == "ci"))
            {
                Err("synthetic failure".to_owned())
            } else {
                update::Executor::run(&update::System, call)
            }
        }
    }
    for step in ["fetch", "build"] {
        let f = fixture::Fixture::new();
        let old = f.head();
        let candidate = f.merge("pass");
        let updater = update::Updater::fixture(
            &f.root,
            &f.install,
            &f.repo,
            &old,
            f.sink(),
            Arc::new(Fail(step)),
        )
        .unwrap();
        let state = f.state();
        assert!(!updater.check(&state, 1000).unwrap());
        let value = state.lock().unwrap().snapshot()["update"].clone();
        assert_eq!(value["to"], candidate);
        assert_eq!(value["outcome"]["state"], "kept");
        assert_eq!(value["outcome"]["step"], step);
        assert_eq!(
            std::fs::read_link(f.install.join("current")).unwrap(),
            f.build(&old)
        );
        assert_eq!(f.records().len(), 1);
        assert!(
            !f.build(&candidate).join("source").exists(),
            "failed gate retained source/build caches"
        );
        contract_record(&f.records()[0], &value);
    }
}

#[test]
fn interrupted_build_and_test_recovery_discards_candidate_source_caches() {
    let f = fixture::Fixture::new();
    let old = f.head();
    let candidate = "ffffffffffffffffffffffffffffffffffffffff";
    f.install_old(&old);
    for (index, (phase, staged)) in [
        ("build", true),
        ("test", true),
        ("build", false),
        ("test", false),
    ]
    .into_iter()
    .enumerate()
    {
        let build = f.build(candidate);
        let source = build.join("source");
        if staged {
            fixture::directory(&source.join("target/debug"));
            fixture::directory(&source.join("apps/web/node_modules"));
            fixture::file(&source.join("Cargo.toml"), "synthetic checkout");
            fixture::file(&source.join("target/debug/cache"), "synthetic build cache");
            fixture::file(
                &source.join("apps/web/node_modules/cache"),
                "synthetic dependency cache",
            );
            fixture::file(&build.join("openwiz-service"), "synthetic staged program");
        } else if build.exists() {
            std::fs::remove_dir_all(&build).unwrap();
        }
        let at = 1000 + index as u64;
        fixture::file(
            &f.root.join("service/update-pending.json"),
            serde_json::json!({"at":at,"from":old,"to":candidate,"phase":phase,"record_claimed":false}).to_string(),
        );
        let running = f.start();
        let status = f.status();
        drop(running);
        assert!(
            !source.exists(),
            "interrupted {phase} retained source/caches"
        );
        assert_eq!(status["service"]["build"], old);
        assert_eq!(status["update"]["at"], at);
        assert_eq!(status["update"]["from"], old);
        assert_eq!(status["update"]["to"], candidate);
        assert_eq!(status["update"]["outcome"]["state"], "kept");
        assert_eq!(status["update"]["outcome"]["step"], phase);
        assert_eq!(
            std::fs::read_link(f.install.join("current")).unwrap(),
            f.build(&old)
        );
        assert_eq!(f.records().len(), index + 1);
        contract_record(&f.records()[index], &status["update"]);
        assert!(!f.root.join("service/update-pending.json").exists());
        assert_eq!(
            f.state().lock().unwrap().snapshot()["update"],
            status["update"]
        );
        if staged {
            assert_eq!(
                std::fs::read_to_string(build.join("openwiz-service")).unwrap(),
                "synthetic staged program"
            );
        } else {
            assert!(
                !build.exists(),
                "recovery created a missing candidate directory"
            );
        }
    }
}

#[test]
fn persistent_candidate_cleanup_failure_keeps_the_old_service_running() {
    use std::os::unix::fs::PermissionsExt;
    struct RestorePermissions(std::path::PathBuf);
    impl Drop for RestorePermissions {
        fn drop(&mut self) {
            std::fs::set_permissions(&self.0, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
    }
    let f = fixture::Fixture::new();
    let old = f.head();
    let candidate = "ffffffffffffffffffffffffffffffffffffffff";
    f.install_old(&old);
    let source = f.build(candidate).join("source");
    let blocked = source.join("target");
    fixture::directory(&blocked);
    fixture::file(&blocked.join("cache"), "synthetic persistent cache");
    let _restore = RestorePermissions(blocked.clone());
    std::fs::set_permissions(&blocked, std::fs::Permissions::from_mode(0o500)).unwrap();
    assert!(
        std::fs::remove_dir_all(&source).is_err(),
        "fixture must prevent cleanup"
    );
    for (index, phase) in ["build", "test"].into_iter().enumerate() {
        let at = 1000 + index as u64;
        fixture::file(
            &f.root.join("service/update-pending.json"),
            serde_json::json!({"at":at,"from":old,"to":candidate,"phase":phase,"record_claimed":false}).to_string(),
        );
        let running = f.start();
        let status = f.status();
        drop(running);
        assert_eq!(status["service"]["build"], old);
        assert_eq!(status["update"]["at"], at);
        assert_eq!(status["update"]["from"], old);
        assert_eq!(status["update"]["to"], candidate);
        assert_eq!(status["update"]["outcome"]["state"], "kept");
        assert_eq!(status["update"]["outcome"]["step"], phase);
        assert_eq!(
            std::fs::read_link(f.install.join("current")).unwrap(),
            f.build(&old)
        );
        assert_eq!(
            f.state().lock().unwrap().snapshot()["update"],
            status["update"]
        );
        assert!(!f.root.join("service/update-pending.json").exists());
        assert_eq!(f.records().len(), index + 1);
        contract_record(&f.records()[index], &status["update"]);
        assert!(
            blocked.join("cache").exists(),
            "cleanup failure must persist"
        );
        let restarted = f.start();
        let restarted_status = f.status();
        drop(restarted);
        assert_eq!(restarted_status["service"]["build"], old);
        assert_eq!(restarted_status["update"], status["update"]);
        assert_eq!(
            f.records().len(),
            index + 1,
            "restart duplicated the record"
        );
    }
    let diagnostics = std::fs::read_to_string(f.temp.join("process.log")).unwrap();
    assert_eq!(
        diagnostics
            .lines()
            .filter(|line| *line
                == "openwiz-service: candidate checkout and build cache cleanup did not finish")
            .count(),
        2
    );
}

#[test]
fn a_missing_queued_candidate_restores_the_old_service_instead_of_a_restart_loop() {
    let f = fixture::Fixture::new();
    let _occupied = f.occupy_configured_port();
    let old = f.head();
    f.install_old(&old);
    fixture::file(&f.root.join("service/update-pending.json"), serde_json::json!({
        "at":1000,"from":old,"to":"ffffffffffffffffffffffffffffffffffffffff","phase":"queued","record_claimed":false
    }).to_string());
    let restored = f.start();
    let status = f.status();
    assert_eq!(status["service"]["build"], old);
    assert_eq!(status["update"]["outcome"]["state"], "kept");
    assert_eq!(status["update"]["outcome"]["step"], "switch");
    drop(restored);
    assert_eq!(f.records().len(), 1);
    contract_record(&f.records()[0], &status["update"]);
}

#[test]
fn a_foreign_current_selection_cannot_start_an_update_or_handover() {
    let f = fixture::Fixture::new();
    let old = f.head();
    std::fs::remove_file(f.install.join("current")).unwrap();
    fixture::directory(&f.temp.join("synthetic-foreign"));
    std::os::unix::fs::symlink(f.temp.join("synthetic-foreign"), f.install.join("current"))
        .unwrap();
    let state = f.state();
    assert!(f.updater(&old).check(&state, 1000).is_err());
    assert!(f.executor.calls.lock().unwrap().is_empty());
    assert!(state.lock().unwrap().snapshot()["update"].is_null());
    assert_eq!(
        std::fs::read_link(f.install.join("current")).unwrap(),
        f.temp.join("synthetic-foreign")
    );
}

fn contract_record(body: &str, attempt: &serde_json::Value) {
    let value: serde_json::Value = serde_json::from_str(body.lines().nth(3).unwrap()).unwrap();
    let schema =
        serde_json::from_str(include_str!("../../contracts/service.v1.schema.json")).unwrap();
    assert!(schema::validate(&schema, &value).is_empty());
    for key in ["at", "from", "to", "outcome"] {
        assert_eq!(value[key], attempt[key]);
    }
    assert_eq!(value["kind"], "update");
}

#[test]
fn an_unknown_record_result_is_saved_and_never_blindly_posted_again() {
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    struct FailingGate;
    impl update::Executor for FailingGate {
        fn run(&self, call: &update::Call) -> Result<String, String> {
            if call.program() == Path::new("git") {
                update::Executor::run(&update::System, call)
            } else {
                Err("synthetic failing gate".to_owned())
            }
        }
    }
    let f = fixture::Fixture::new();
    let old = f.head();
    let candidate = f.merge("pass");
    let writes = Arc::new(AtomicUsize::new(0));
    let count = Arc::clone(&writes);
    let updater = update::Updater::fixture(
        &f.root,
        &f.install,
        &f.repo,
        &old,
        Arc::new(move |_, _| {
            count.fetch_add(1, Ordering::SeqCst);
            Err(update::RecordError::Uncertain)
        }),
        Arc::new(FailingGate),
    )
    .unwrap();
    let state = f.state();
    assert!(updater.check(&state, 1000).is_err());
    assert_eq!(state.lock().unwrap().snapshot()["update"]["to"], candidate);
    assert_eq!(f.pending()["record_claimed"], true);
    assert!(!updater.check(&state, 2000).unwrap());
    assert_eq!(writes.load(Ordering::SeqCst), 1);
}

#[test]
fn the_updater_keeps_other_jobs_and_cannot_use_a_personal_account_fallback() {
    use std::{
        num::NonZeroU64,
        sync::{
            Arc,
            atomic::{AtomicBool, AtomicUsize, Ordering},
        },
    };
    let f = fixture::Fixture::new();
    let config =
        serde_json::from_slice(&std::fs::read(f.root.join("service/config.json")).unwrap())
            .unwrap();
    let mut scheduler = openwiz_service::scheduler::Scheduler::default();
    let count = Arc::new(AtomicUsize::new(0));
    let ran = Arc::clone(&count);
    scheduler
        .register(
            "synthetic-other-ticket",
            NonZeroU64::new(1).unwrap(),
            move || {
                ran.fetch_add(1, Ordering::SeqCst);
            },
        )
        .unwrap();
    update::register(
        &f.root,
        &config,
        &f.head(),
        f.state(),
        &mut scheduler,
        Arc::new(AtomicBool::new(false)),
    )
    .unwrap();
    assert!(scheduler.poll(0).unwrap().is_empty());
    assert_eq!(scheduler.poll(299).unwrap(), ["synthetic-other-ticket"]);
    scheduler.wait("synthetic-other-ticket").unwrap();
    assert_eq!(
        scheduler.poll(300).unwrap(),
        ["synthetic-other-ticket", "self-update"]
    );
    scheduler.wait("synthetic-other-ticket").unwrap();
    scheduler.wait("self-update").unwrap();
    assert_eq!(count.load(Ordering::SeqCst), 2);
    assert!(f.records().is_empty());
    assert!(!f.root.join("service/clone").exists());
}

#[test]
fn a_changed_origin_or_symlinked_pending_journal_is_refused_before_fetching() {
    let f = fixture::Fixture::new();
    let old = f.head();
    let state = f.state();
    assert!(!f.updater(&old).check(&state, 1000).unwrap());
    let calls = f.executor.calls.lock().unwrap().len();
    let result = std::process::Command::new("git")
        .args([
            "remote",
            "set-url",
            "origin",
            "https://example.invalid/synthetic.git",
        ])
        .current_dir(f.root.join("service/clone"))
        .output()
        .unwrap();
    assert!(result.status.success());
    assert!(f.updater(&old).check(&state, 1000).is_err());
    assert_eq!(f.executor.calls.lock().unwrap().len(), calls + 1);
    let calls = f.executor.calls.lock().unwrap().len();
    fixture::file(&f.temp.join("synthetic-target"), "synthetic untouched");
    std::os::unix::fs::symlink(
        f.temp.join("synthetic-target"),
        f.root.join("service/update-pending.json"),
    )
    .unwrap();
    assert!(f.updater(&old).check(&state, 1000).is_err());
    assert_eq!(f.executor.calls.lock().unwrap().len(), calls);
    assert_eq!(
        std::fs::read_to_string(f.temp.join("synthetic-target")).unwrap(),
        "synthetic untouched"
    );
}

#[test]
fn cancelling_a_gate_stops_its_descendants_too() {
    use std::{
        sync::{
            Arc,
            atomic::{AtomicBool, Ordering},
        },
        time::{Duration, Instant},
    };
    let f = fixture::Fixture::new();
    fixture::file(
        &f.repo.join(".github/actions/docs-only/test.sh"),
        "sleep 120 &\necho $! > synthetic-child.pid.tmp\nmv synthetic-child.pid.tmp synthetic-child.pid\nwait\n",
    );
    let call = update::gate_call(
        Path::new("sh"),
        &[".github/actions/docs-only/test.sh"],
        &f.repo,
        &f.head(),
    )
    .unwrap();
    let cancel = Arc::new(AtomicBool::new(false));
    let stop = Arc::clone(&cancel);
    let run = std::thread::spawn(move || update::System.run_cancel(&call, &stop));
    let until = Instant::now() + Duration::from_secs(10);
    let path = f.repo.join("synthetic-child.pid");
    while !path.exists() {
        assert!(Instant::now() < until);
        std::thread::park_timeout(Duration::from_millis(10));
    }
    cancel.store(true, Ordering::SeqCst);
    assert!(run.join().unwrap().is_err());
    // The writer has stopped; the complete marker was published by rename.
    let pid = std::fs::read_to_string(&path)
        .unwrap()
        .trim()
        .parse::<u32>()
        .unwrap();
    let until = Instant::now() + Duration::from_secs(2);
    let alive = loop {
        let status = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap_or_default();
        if status.is_empty() || status.split_whitespace().nth(2) == Some("Z") {
            break false;
        }
        if Instant::now() >= until {
            break true;
        }
        std::thread::park_timeout(Duration::from_millis(10));
    };
    // Clean up this exact fixture PID even when the negative control fails.
    if alive {
        let _ = std::process::Command::new("/bin/kill")
            .args(["-KILL", &pid.to_string()])
            .status();
    }
    assert!(!alive, "a descendant outlived the cancelled gate");
}

#[test]
fn pending_journals_accept_only_the_exact_owned_shape() {
    let f = fixture::Fixture::new();
    let old = f.head();
    let pending = serde_json::json!({"at":1000,"from":old,"to":"ffffffffffffffffffffffffffffffffffffffff","phase":"queued","record_claimed":false});
    fixture::file(
        &f.root.join("service/update-pending.json"),
        pending.to_string(),
    );
    assert!(!f.updater(&old).check(&f.state(), 1000).unwrap());
    assert!(f.executor.calls.lock().unwrap().is_empty());
    for invalid in [
        format!("{{\"unexpected\":0,{}", &pending.to_string()[1..]),
        format!("{{\"at\":1000,{}", &pending.to_string()[1..]),
        "[]".to_owned(),
        pending.to_string().replace("1000", "1000.0"),
        pending
            .to_string()
            .replace("\"queued\"", "{\"queued\":null}"),
        " ".repeat(8192),
    ] {
        fixture::file(&f.root.join("service/update-pending.json"), invalid);
        assert!(f.updater(&old).check(&f.state(), 1000).is_err());
        assert!(f.executor.calls.lock().unwrap().is_empty());
    }
}

#[test]
fn an_unchanged_main_still_leaves_only_private_clone_files() {
    use std::os::unix::fs::PermissionsExt;
    fn inspect(path: &Path) {
        let meta = std::fs::symlink_metadata(path).unwrap();
        assert_eq!(meta.permissions().mode() & 0o077, 0, "{}", path.display());
        if meta.is_dir() {
            for child in std::fs::read_dir(path).unwrap() {
                inspect(&child.unwrap().path());
            }
        }
    }
    let f = fixture::Fixture::new();
    f.executor
        .loose_modes
        .store(true, std::sync::atomic::Ordering::SeqCst);
    assert!(!f.updater(&f.head()).check(&f.state(), 1000).unwrap());
    inspect(&f.root.join("service/clone"));
}

#[test]
fn a_candidate_that_exits_without_readiness_rolls_back_to_the_running_old_build() {
    let f = fixture::Fixture::new();
    let _occupied = f.occupy_configured_port();
    let old = f.head();
    f.install_old(&old);
    fixture::file(&f.repo.join("src/mode"), "fail");
    let candidate = f.merge("pass");
    let state = f.state();
    assert!(f.updater(&old).check(&state, 1000).unwrap());
    let mut unconfirmed = f.start();
    unconfirmed.exited();
    drop(unconfirmed);
    let restored = f.start();
    let status = f.status();
    assert_eq!(status["service"]["build"], old);
    assert_eq!(status["update"]["to"], candidate);
    assert_eq!(status["update"]["outcome"]["state"], "kept");
    assert_eq!(status["update"]["outcome"]["step"], "switch");
    assert_eq!(
        std::fs::read_link(f.install.join("current")).unwrap(),
        f.build(&old)
    );
    drop(restored);
    assert_eq!(f.records().len(), 1);
    contract_record(&f.records()[0], &status["update"]);
    assert!(f.records()[0].contains("; the switch failed:"));
    assert!(!f.records()[0].contains("switched from"));
}

#[test]
fn interrupted_candidate_selection_can_roll_back_or_confirm_on_restart() {
    let f = fixture::Fixture::new();
    let old = f.head();
    f.install_old(&old);
    let candidate = f.merge("pass");
    // Stage both compiled identities; the complete gate is covered separately.
    std::fs::remove_file(f.install.join("current")).unwrap();
    std::os::unix::fs::symlink(f.build(&candidate), f.install.join("current")).unwrap();
    f.install_old(&candidate);
    for (at, fails, saved) in [
        (1000, true, false),
        (2000, true, true),
        (3000, false, false),
    ] {
        // Recreate a crash after current was selected but before ready was saved.
        fixture::file(
            &f.root.join("service/update-pending.json"),
            serde_json::json!({"at":at,"from":old,"to":candidate,"phase":"launched","record_claimed":false}).to_string(),
        );
        std::fs::remove_file(f.install.join("current")).unwrap();
        std::os::unix::fs::symlink(f.build(&candidate), f.install.join("current")).unwrap();
        if saved {
            // A crash can also follow state.save but precede the ready journal.
            let state = f.state();
            let mut state = state.lock().unwrap();
            let mut next = state.snapshot().clone();
            next["update"] = serde_json::json!({"at":at,"from":old,"to":candidate,"outcome":{"state":"switched"}});
            state.save(next).unwrap();
        }
        let occupied = if fails {
            // HTTP binding happens after recovery; the watchdog dies on exit.
            let occupied = f.occupy_configured_port();
            fixture::file(&f.root.join("service/fixture-configured-port"), "");
            let mut unconfirmed = f.start();
            unconfirmed.exited();
            assert!(!unconfirmed.0.wait().unwrap().success());
            assert!(
                std::fs::read_to_string(f.temp.join("process.log"))
                    .unwrap()
                    .contains("cannot bind the configured loopback port")
            );
            assert_eq!(
                std::fs::read_link(f.install.join("current")).unwrap(),
                f.build(&old),
                "an unconfirmed candidate must leave the old build selected"
            );
            assert_eq!(f.pending()["phase"], "launched");
            assert!(f.records().is_empty());
            std::fs::remove_file(f.root.join("service/fixture-configured-port")).unwrap();
            Some(occupied)
        } else {
            None
        };
        let running = f.start();
        let status = f.status();
        if let Some(occupied) = &occupied {
            assert_ne!(
                status["server"]["port"],
                occupied.local_addr().unwrap().port()
            );
        }
        let expected = if fails { &old } else { &candidate };
        assert_eq!(status["service"]["build"], *expected);
        assert_eq!(status["update"]["at"], at);
        assert_eq!(status["update"]["from"], old);
        assert_eq!(status["update"]["to"], candidate);
        assert_eq!(
            status["update"]["outcome"]["state"],
            if fails { "kept" } else { "switched" }
        );
        if fails {
            assert_eq!(status["update"]["outcome"]["step"], "switch");
        }
        assert_eq!(
            std::fs::read_link(f.install.join("current")).unwrap(),
            f.build(expected)
        );
        let until = std::time::Instant::now() + std::time::Duration::from_secs(5);
        while f.records().len() != 1 {
            assert!(std::time::Instant::now() < until);
            std::thread::park_timeout(std::time::Duration::from_millis(10));
        }
        drop(running);
        let records = f.records();
        assert_eq!(records.len(), 1);
        contract_record(&records[0], &status["update"]);
        assert!(!f.root.join("service/update-pending.json").exists());
        std::fs::remove_file(f.root.join("service/fixture-records")).unwrap();
    }
}

#[test]
fn a_real_candidate_must_confirm_readiness_before_selection_or_switched() {
    let f = fixture::Fixture::new();
    let _occupied = f.occupy_configured_port();
    let old = f.head();
    f.install_old(&old);
    let running = f.start();
    assert_eq!(f.status()["service"]["build"], old);
    f.only_existing_http_listener(&running);
    f.reject_inbound_update();
    assert!(f.gate().is_empty());
    assert!(f.records().is_empty());
    let obsolete = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    fixture::directory(&f.build(obsolete).join("source/target"));
    let outside = f.temp.join("synthetic-outside");
    fixture::directory(&outside);
    fixture::file(&outside.join("keep"), "synthetic outside data");
    std::os::unix::fs::symlink(&outside, f.build(obsolete).join("source/link")).unwrap();
    let candidate = f.merge("pass");
    let state = f.state();
    // A fixed-gate rejection happens before the candidate readiness proof.
    assert!(
        f.updater(&old).check(&state, 1000).unwrap(),
        "candidate was not queued: update={}, gate={:?}, records={:?}",
        state.lock().unwrap().snapshot()["update"],
        f.gate(),
        f.records()
    );
    assert!(!f.build(&candidate).join("source").exists());
    assert_eq!(
        std::fs::read_link(f.install.join("current")).unwrap(),
        f.build(&old)
    );
    assert_eq!(f.status()["service"]["build"], old);
    assert!(f.records().is_empty());
    // The fixture models the existing unit's restart, never systemctl.
    drop(running);
    let candidate_process = f.start();
    let status = f.status();
    assert_eq!(status["service"]["build"], candidate);
    f.only_existing_http_listener(&candidate_process);
    assert_eq!(
        std::fs::read_link(format!("/proc/{}/fd/2", candidate_process.0.id())).unwrap(),
        f.temp.join("process.log"),
        "candidate diagnostics must remain attached to the service journal"
    );
    assert_eq!(
        status["update"]["outcome"],
        serde_json::json!({"state":"switched"})
    );
    assert_eq!(
        std::fs::read_link(f.install.join("current")).unwrap(),
        f.build(&candidate)
    );
    let mut builds: Vec<_> = std::fs::read_dir(f.root.join("service/builds"))
        .unwrap()
        .map(|entry| entry.unwrap().file_name().into_string().unwrap())
        .collect();
    builds.sort();
    let mut expected_builds = vec![old.clone(), candidate.clone()];
    expected_builds.sort();
    assert_eq!(builds, expected_builds);
    assert_eq!(
        std::fs::read_to_string(outside.join("keep")).unwrap(),
        "synthetic outside data"
    );
    let until = std::time::Instant::now() + std::time::Duration::from_secs(5);
    while f.records().len() != 1 {
        assert!(std::time::Instant::now() < until);
        std::thread::park_timeout(std::time::Duration::from_millis(10));
    }
    drop(candidate_process);
    let expected = format!("openwiz-service: update to {candidate}: switched from {old}");
    assert_eq!(f.records()[0].lines().next(), Some(expected.as_str()));
    contract_record(&f.records()[0], &status["update"]);
}

#[test]
fn a_failing_merge_is_kept_and_recorded_once_without_retrying_the_gate() {
    let f = fixture::Fixture::new();
    let old = f.head();
    f.install_old(&old);
    let _running = f.start();
    assert_eq!(f.status()["service"]["build"], old);
    let candidate = f.merge("fail");
    let state = f.state();
    assert!(!f.updater(&old).check(&state, 1000).unwrap());
    let attempt = state.lock().unwrap().snapshot()["update"].clone();
    assert_eq!(attempt["from"], old);
    assert_eq!(attempt["to"], candidate);
    assert_eq!(attempt["outcome"]["state"], "kept");
    assert_eq!(attempt["outcome"]["step"], "test");
    let records = f.records();
    assert_eq!(records.len(), 1);
    let expected = format!(
        "openwiz-service: update to {candidate}: kept {old}; the test failed: candidate build or acceptance command failed"
    );
    assert_eq!(records[0].lines().next(), Some(expected.as_str()));
    let data: serde_json::Value = serde_json::from_str(records[0].lines().nth(3).unwrap()).unwrap();
    assert_eq!(data["schema"], "openwiz.service-record.v1");
    assert_eq!(data["kind"], "update");
    assert_eq!(data["at"], 1000);
    assert_eq!(data["outcome"], attempt["outcome"]);
    contract_record(&records[0], &attempt);
    let calls = f.gate();
    assert!(!f.updater(&old).check(&state, 2000).unwrap());
    assert_eq!(f.gate(), calls);
    assert_eq!(f.records(), records);
    assert_eq!(f.status()["service"]["build"], old);
    assert_eq!(
        std::fs::read_link(f.install.join("current")).unwrap(),
        f.build(&old)
    );
    assert!(!f.build(&candidate).join("openwiz-service").exists());
    assert!(!f.build(&candidate).join("web").exists());
}

#[test]
fn a_topic_commit_is_never_selected_and_an_unsafe_clone_runs_no_command() {
    let f = fixture::Fixture::new();
    let old = f.head();
    f.git(&["checkout", "-qb", "synthetic-topic"]);
    fixture::file(&f.repo.join("synthetic-topic"), "synthetic unmerged");
    f.git(&["add", "."]);
    f.git(&["commit", "-qm", "synthetic unmerged topic"]);
    let state = f.state();
    assert!(!f.updater(&old).check(&state, 1000).unwrap());
    assert!(f.gate().is_empty());
    assert!(f.records().is_empty());
    assert!(state.lock().unwrap().snapshot()["update"].is_null());
    let calls = f.executor.calls.lock().unwrap().len();
    std::fs::set_permissions(
        f.root.join("service/clone"),
        <std::fs::Permissions as std::os::unix::fs::PermissionsExt>::from_mode(0o755),
    )
    .unwrap();
    assert!(f.updater(&old).check(&state, 1000).is_err());
    assert_eq!(f.executor.calls.lock().unwrap().len(), calls);
}

#[test]
fn a_passing_main_merge_is_staged_but_not_reported_as_running() {
    let f = fixture::Fixture::new();
    let old = f.head();
    let candidate = f.merge("pass");
    let state = f.state();
    assert!(f.updater(&old).check(&state, 1000).unwrap());
    assert!(state.lock().unwrap().snapshot()["update"].is_null());
    assert!(f.records().is_empty());
    let pending = f.pending();
    assert_eq!(pending["from"], old);
    assert_eq!(pending["to"], candidate);
    assert_eq!(pending["phase"], "queued");
    assert_eq!(
        f.gate(),
        vec![
            "sh .github/actions/docs-only/test.sh",
            "npm ci --ignore-scripts",
            "npm run build",
            "npm run typecheck",
            "npm run check",
            "cargo fmt --check",
            "cargo clippy --workspace --all-targets -- -D warnings",
            "cargo build --workspace",
            "cargo test --workspace",
            "cargo test -p openwiz-tests --test checks pending",
            "cargo build --release",
            "npm test"
        ]
    );
    assert!(f.build(&candidate).join("openwiz-service").is_file());
    assert!(f.build(&candidate).join("web/index.html").is_file());
}

/// #1060 (#1044): the service forks from many threads. A child forked while
/// this process holds a writable descriptor for the staged program keeps that
/// descriptor after the stager closes its own, and the identity check's exec
/// then fails with ETXTBSY: a good merge is not staged. A watcher stands in for
/// such a fork: it reopens for writing any writer of the staged program it sees
/// in this process, and holds it until the attempt ends. The gates are fakes;
/// Git and the identity exec are real. The program is padded so its copy lasts
/// long enough to be seen.
#[cfg(target_os = "linux")]
#[test]
fn a_concurrent_fork_cannot_keep_the_staged_program_busy() {
    use std::{
        fs,
        sync::{
            Arc,
            atomic::{AtomicBool, Ordering},
        },
    };
    struct Gates(String);
    impl update::Executor for Gates {
        fn run(&self, call: &update::Call) -> Result<String, String> {
            let args: Vec<_> = call.argv().iter().map(String::as_str).collect();
            match (call.program().to_str(), args.as_slice()) {
                (Some("npm"), ["run", "build"]) => {
                    fixture::directory(&call.directory().join("out"));
                    fixture::file(&call.directory().join("out/index.html"), "<html></html>");
                }
                (Some("cargo"), ["build", "--release"]) => {
                    let release = call.directory().join("target/release");
                    fixture::directory(&release);
                    let mut program = format!("#!/bin/sh\necho {}\nexit 0\n", self.0).into_bytes();
                    program.resize(program.len() + (64 << 20), b'#');
                    fixture::file(&release.join("openwiz-service"), program);
                }
                (Some("sh" | "npm" | "cargo"), _) => {}
                _ => return update::Executor::run(&update::System, call),
            }
            Ok(String::new())
        }
    }
    let f = fixture::Fixture::new();
    let old = f.head();
    let candidate = f.merge("pass");
    let staged = fs::canonicalize(&f.root)
        .unwrap()
        .join("service/builds")
        .join(&candidate)
        .join("openwiz-service");
    let done = Arc::new(AtomicBool::new(false));
    let watcher = {
        let done = Arc::clone(&done);
        std::thread::spawn(move || {
            // One inherited writer is enough; it stays open until joined.
            let mut held = None;
            while held.is_none() && !done.load(Ordering::SeqCst) {
                held = fs::read_dir("/proc/self/fd")
                    .unwrap()
                    .flatten()
                    .find_map(|fd| {
                        let fd = fd.path();
                        let info = fs::read_to_string(
                            Path::new("/proc/self/fdinfo").join(fd.file_name()?),
                        )
                        .ok()?;
                        let flags = info.lines().find_map(|l| l.strip_prefix("flags:"))?;
                        let writable = u32::from_str_radix(flags.trim(), 8).ok()? & 3 != 0;
                        (writable && fs::read_link(&fd).ok()? == staged)
                            .then(|| fs::OpenOptions::new().write(true).open(&fd).ok())?
                    });
            }
            held
        })
    };
    let updater = update::Updater::fixture(
        &f.root,
        &f.install,
        &f.repo,
        &old,
        f.sink(),
        Arc::new(Gates(candidate.clone())),
    )
    .unwrap();
    let state = f.state();
    let staged_ok = updater.check(&state, 1000).unwrap();
    done.store(true, Ordering::SeqCst);
    let inherited = watcher.join().unwrap().is_some();
    assert!(
        staged_ok,
        "a good merge was not staged (writer inherited by a concurrent fork: \
         {inherited}): {:?}",
        state.lock().unwrap().snapshot()["update"]
    );
    assert_eq!(f.pending()["phase"], "queued");
    assert!(
        !inherited,
        "this process held a writer for the staged program"
    );
}

#[test]
fn only_the_complete_fixed_gate_can_run() {
    let expected: &[(&str, &[&str])] = &[
        ("sh", &[".github/actions/docs-only/test.sh"]),
        ("npm", &["ci", "--ignore-scripts"]),
        ("npm", &["run", "build"]),
        ("npm", &["run", "typecheck"]),
        ("npm", &["run", "check"]),
        ("cargo", &["fmt", "--check"]),
        (
            "cargo",
            &[
                "clippy",
                "--workspace",
                "--all-targets",
                "--",
                "-D",
                "warnings",
            ],
        ),
        ("cargo", &["build", "--workspace"]),
        ("cargo", &["test", "--workspace"]),
        (
            "cargo",
            &["test", "-p", "openwiz-tests", "--test", "checks", "pending"],
        ),
        ("cargo", &["build", "--release"]),
        ("npm", &["test"]),
    ];
    assert_eq!(update::GATE.len(), 12);
    for (program, args) in expected {
        assert!(
            update::allows_gate(Path::new(program), args),
            "{program} {args:?}"
        );
        let mut extra = args.to_vec();
        extra.push("--synthetic-extra");
        assert!(!update::allows_gate(Path::new(program), &extra));
    }
    for (program, args) in [
        ("room-cli", vec!["thread", "tell", "thr_syn_0001"]),
        ("sh", vec!["-c", "synthetic arbitrary command"]),
        ("git", vec!["push", "origin", "main"]),
        ("cargo", vec!["test", "--no-default-features"]),
        ("/tmp/cargo", vec!["test", "--workspace"]),
        ("npm", vec!["install"]),
    ] {
        assert!(!update::allows_gate(Path::new(program), &args));
        assert!(!update::allows_command(Path::new(program), &args));
    }
    let git = [
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "protocol.ext.allow=never",
    ];
    for suffix in [
        vec!["push", "origin", "main"],
        vec!["fetch", "origin", "synthetic-topic"],
        vec!["checkout", "--detach", "--force", "--bad"],
        vec!["remote", "add", "origin", "ssh://example.invalid/synthetic"],
        vec!["-c", "core.sshCommand=synthetic"],
    ] {
        let mut args = git.to_vec();
        args.extend(suffix);
        assert!(!update::allows_command(Path::new("git"), &args));
    }
    assert!(!update::allows_command(
        Path::new("/bin/kill"),
        &["-KILL", "--", "-1"]
    ));
    assert!(!update::allows_command(
        Path::new("/tmp/arbitrary/openwiz-service"),
        &[]
    ));
}

#[test]
fn a_gate_does_not_inherit_service_state_or_unapproved_environment() {
    let f = fixture::Fixture::new();
    let result = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "gate_environment_child", "--nocapture"])
        .env("OW_T6_ENV_CHILD", "1")
        .env("OPENWIZ_STATE_DIR", &f.root)
        .env("XDG_STATE_HOME", f.temp.join("synthetic-state"))
        .env("SYNTHETIC_SERVICE_SECRET", "synthetic-secret")
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
fn gate_environment_child() {
    if std::env::var_os("OW_T6_ENV_CHILD").is_none() {
        return;
    }
    let f = fixture::Fixture::new();
    fixture::file(
        &f.repo.join(".github/actions/docs-only/test.sh"),
        r#"set -eu
test -z "${OPENWIZ_STATE_DIR+x}"
test -z "${XDG_STATE_HOME+x}"
test -z "${SYNTHETIC_SERVICE_SECRET+x}"
test -z "${OW_T6_ENV_CHILD+x}"
test -n "$PATH"
test -n "$HOME"
test "$LANG" = C.UTF-8
test "$GIT_TERMINAL_PROMPT" = 0
test "$GIT_CONFIG_NOSYSTEM" = 1
test "$CARGO_BUILD_JOBS" = 2
test "$CIRCLE_NODE_TOTAL" = 2
"#,
    );
    let call = update::gate_call(
        Path::new("sh"),
        &[".github/actions/docs-only/test.sh"],
        &f.repo,
        &f.head(),
    )
    .unwrap();
    assert!(
        update::Executor::run(&update::System, &call).is_ok(),
        "gate inherited service state or missed its explicit tool environment"
    );
}

// Keep the same open file description alive as a fork delayed before exec
// would. A private preload shim avoids unsafe Rust or a production test hook.
fn with_delayed_update_lock(test: &str) {
    use std::{
        io::Write,
        process::{Command, Stdio},
    };
    let dir = std::env::temp_dir().join(format!("ow-t6-lock-delay-{}", std::process::id()));
    fixture::directory(&dir);
    let library = dir.join("hold-lock.so");
    let mut compiler = Command::new("cc")
        .args([
            "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror", "-x", "c", "-", "-o",
        ])
        .arg(&library)
        .arg("-ldl")
        .stdin(Stdio::piped())
        .spawn()
        .unwrap();
    compiler
        .stdin
        .take()
        .unwrap()
        .write_all(
            br#"
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/file.h>
#include <unistd.h>
int flock(int fd, int operation) {
    static int retained = -1;
    int (*original)(int, int) = dlsym(RTLD_NEXT, "flock");
    if (!original) { errno = ENOSYS; return -1; }
    int result = original(fd, operation);
    if (result == 0 && operation == (LOCK_EX | LOCK_NB) && retained == -1) {
        char link[64], path[4096];
        snprintf(link, sizeof(link), "/proc/self/fd/%d", fd);
        ssize_t size = readlink(link, path, sizeof(path) - 1);
        if (size >= 0) {
            path[size] = 0;
            const char *suffix = "/service/update.lock";
            size_t length = strlen(suffix);
            if ((size_t)size >= length && strcmp(path + size - length, suffix) == 0) {
                retained = fcntl(fd, F_DUPFD_CLOEXEC, 0);
                if (retained == -1) return -1;
            }
        }
    }
    return result;
}
"#,
        )
        .unwrap();
    assert!(
        compiler.wait().unwrap().success(),
        "compile lock-delay fixture"
    );
    let output = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", test, "--nocapture"])
        .env("LD_PRELOAD", &library)
        .env("OW_T6_DELAYED_LOCK_CHILD", "1")
        .output()
        .unwrap();
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn a_definitely_unsent_record_retries_the_same_attempt_without_rebuilding() {
    if std::env::var_os("OW_T6_DELAYED_LOCK_CHILD").is_none() {
        with_delayed_update_lock(
            "a_definitely_unsent_record_retries_the_same_attempt_without_rebuilding",
        );
        return;
    }
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    struct FailingGate(Arc<AtomicUsize>);
    impl update::Executor for FailingGate {
        fn run(&self, call: &update::Call) -> Result<String, String> {
            if call.program() == Path::new("git") {
                update::Executor::run(&update::System, call)
            } else {
                self.0.fetch_add(1, Ordering::SeqCst);
                Err("synthetic failing gate".to_owned())
            }
        }
    }
    let f = fixture::Fixture::new();
    let old = f.head();
    f.merge("pass");
    let calls = Arc::new(AtomicUsize::new(0));
    let count = Arc::clone(&calls);
    let gates = Arc::new(AtomicUsize::new(0));
    let sink = f.sink();
    let updater = update::Updater::fixture(
        &f.root,
        &f.install,
        &f.repo,
        &old,
        Arc::new(move |issue, body| {
            if count.fetch_add(1, Ordering::SeqCst) == 0 {
                return Err(update::RecordError::Unsent);
            }
            sink(issue, body)
        }),
        Arc::new(FailingGate(Arc::clone(&gates))),
    )
    .unwrap();
    let state = f.state();
    assert_eq!(
        updater.check(&state, 1000).unwrap_err(),
        "update record was not sent; retry pending"
    );
    let lock_path = f.root.join("service/update.lock");
    assert_eq!(
        std::fs::read_dir("/proc/self/fd")
            .unwrap()
            .filter_map(|entry| std::fs::read_link(entry.unwrap().path()).ok())
            .filter(|path| path == &lock_path)
            .count(),
        1,
        "the delayed duplicate must still be open after check returns"
    );
    assert_eq!(
        f.pending()["record_claimed"],
        false,
        "definitely unsent delivery must remain retryable"
    );
    let saved = state.lock().unwrap().snapshot()["update"].clone();
    assert!(!updater.check(&state, 2000).unwrap());
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_eq!(f.records().len(), 1);
    contract_record(&f.records()[0], &saved);
    assert!(!f.root.join("service/update-pending.json").exists());
    assert!(!updater.check(&state, 3000).unwrap());
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    assert_eq!(
        gates.load(Ordering::SeqCst),
        1,
        "record retry rebuilt the candidate"
    );
}

#[test]
fn an_unclaimed_ready_record_is_delivered_after_a_process_restart() {
    let f = fixture::Fixture::new();
    let current = f.head();
    let previous = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    f.install_old(&current);
    let state = f.state();
    let result =
        serde_json::json!({"at":1000,"from":previous,"to":current,"outcome":{"state":"switched"}});
    let mut next = state.lock().unwrap().snapshot().clone();
    next["update"] = result.clone();
    state.lock().unwrap().save(next).unwrap();
    fixture::file(&f.root.join("service/update-pending.json"), serde_json::json!({"at":1000,"from":previous,"to":current,"phase":"ready","record_claimed":false}).to_string());
    let running = f.start();
    let status = f.status();
    assert_eq!(status["service"]["build"], current);
    assert_eq!(
        f.records().len(),
        1,
        "a ready but unclaimed record must be delivered on recovery"
    );
    contract_record(&f.records()[0], &result);
    assert!(!f.root.join("service/update-pending.json").exists());
    drop(running);
}

#[test]
fn pending_record_status_is_visible_and_disappears_after_confirmed_delivery() {
    let f = fixture::Fixture::new();
    let current = f.head();
    let previous = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    f.install_old(&current);
    let state = f.state();
    let result =
        serde_json::json!({"at":1000,"from":previous,"to":current,"outcome":{"state":"switched"}});
    let mut next = state.lock().unwrap().snapshot().clone();
    next["update"] = result.clone();
    state.lock().unwrap().save(next).unwrap();
    let pending = f.root.join("service/update-pending.json");
    let blocked = f.root.join("service/fixture-record-unsent");
    fixture::file(&blocked, "synthetic unsent request");
    fixture::file(&pending, serde_json::json!({"at":1000,"from":previous,"to":current,"phase":"ready","record_claimed":false}).to_string());
    let running = f.start();
    let status = f.status();
    assert_eq!(
        status["update_record"],
        serde_json::json!({"state":"retrying","reason":"Update record was not sent; delivery will retry on the next scheduled check"})
    );
    assert_eq!(status["update"], result);
    assert!(f.records().is_empty());
    assert_eq!(f.pending()["record_claimed"], false);
    std::fs::remove_file(blocked).unwrap();
    assert!(!f.updater(&current).check(&f.state(), 2000).unwrap());
    assert_eq!(f.records().len(), 1);
    contract_record(&f.records()[0], &result);
    assert!(f.status().get("update_record").is_none());
    drop(running);

    // A restarted process with an already-claimed write must only expose it.
    fixture::file(&pending, serde_json::json!({"at":1000,"from":previous,"to":current,"phase":"ready","record_claimed":true}).to_string());
    let restarted = f.start();
    let status = f.status();
    assert_eq!(
        status["update_record"],
        serde_json::json!({"state":"uncertain","reason":"Update record delivery is uncertain; reconcile the service issue before clearing the pending journal"})
    );
    assert_eq!(status["update"], result);
    assert!(!f.updater(&current).check(&f.state(), 3000).unwrap());
    assert_eq!(f.records().len(), 1);
    assert_eq!(f.pending()["record_claimed"], true);
    drop(restarted);
}

#[test]
fn status_record_object_has_only_the_approved_optional_shape() {
    use openwiz_service::document::{self, Document};
    let spec: serde_json::Value =
        serde_json::from_str(include_str!("../../contracts/service.v1.schema.json")).unwrap();
    let good: serde_json::Value = include_str!("../../contracts/service.v1.md")
        .lines()
        .filter_map(|line| serde_json::from_str::<serde_json::Value>(line).ok())
        .find(|value| value["schema"] == "openwiz.service-status.v1")
        .unwrap();
    assert!(document::read(Document::Status, &good.to_string()).is_ok());
    for (field, accepted) in [
        (
            serde_json::json!({"state":"retrying","reason":"Synthetic unsent record"}),
            true,
        ),
        (
            serde_json::json!({"state":"uncertain","reason":"Synthetic uncertain record"}),
            true,
        ),
        (serde_json::json!(null), false),
        (serde_json::json!([]), false),
        (
            serde_json::json!({"state":"sent","reason":"Synthetic record"}),
            false,
        ),
        (
            serde_json::json!({"state":{"retrying":null},"reason":"Synthetic record"}),
            false,
        ),
        (serde_json::json!({"state":"retrying"}), false),
        (serde_json::json!({"reason":"Synthetic record"}), false),
        (
            serde_json::json!({"state":"retrying","reason":false}),
            false,
        ),
        (
            serde_json::json!({"state":"retrying","reason":"Synthetic record","extra":true}),
            false,
        ),
    ] {
        let mut value = good.clone();
        value["update_record"] = field;
        assert_eq!(
            schema::validate(&spec, &value).is_empty(),
            accepted,
            "schema: {value}"
        );
        assert_eq!(
            document::read(Document::Status, &value.to_string()).is_ok(),
            accepted,
            "reader: {value}"
        );
    }
    let mut no_attempt = good.clone();
    no_attempt["update"] = serde_json::Value::Null;
    no_attempt["update_record"] =
        serde_json::json!({"state":"retrying","reason":"Synthetic record"});
    assert!(document::read(Document::Status, &no_attempt.to_string()).is_err());
    let mut duplicate = good.clone();
    duplicate["update_record"] =
        serde_json::json!({"state":"retrying","reason":"Synthetic record"});
    let duplicate = duplicate.to_string().replace(
        "\"state\":\"retrying\"",
        "\"state\":\"retrying\",\"state\":\"uncertain\"",
    );
    assert!(document::read(Document::Status, &duplicate).is_err());
    let mut state: serde_json::Value = include_str!("../../contracts/service.v1.md")
        .lines()
        .filter_map(|line| serde_json::from_str::<serde_json::Value>(line).ok())
        .find(|value| value["schema"] == "openwiz.service-state.v1")
        .unwrap();
    state["update_record"] = serde_json::json!({"state":"retrying","reason":"Synthetic record"});
    assert!(!schema::validate(&spec, &state).is_empty());
    assert!(document::read(Document::State, &state.to_string()).is_err());
}

#[test]
fn packaged_updates_stage_verified_products_without_source_build_calls() {
    use std::sync::Arc;
    struct Packages {
        source: String,
        root: std::path::PathBuf,
        calls: std::sync::Mutex<Vec<Vec<String>>>,
    }
    impl update::Executor for Packages {
        fn run(&self, call: &update::Call) -> Result<String, String> {
            self.calls.lock().unwrap().push(
                std::iter::once(call.program().to_string_lossy().into_owned())
                    .chain(call.argv().iter().cloned())
                    .collect(),
            );
            if call.program() == Path::new("python3") {
                if call.argv().get(1).map(String::as_str) == Some("discover") {
                    return Ok(serde_json::json!({"schema":"openwiz.package-candidate.v1",
                        "source":self.source,"version":"0.0.99",
                        "target":"x86_64-unknown-linux-gnu","manifest_sha256":"3".repeat(64)})
                    .to_string());
                }
                assert_eq!(call.argv().get(1).map(String::as_str), Some("stage"));
                let build = self.root.join("service/builds").join(&self.source);
                fixture::directory(&build.join("web"));
                fixture::file(&build.join("web/index.html"), "synthetic packaged web");
                fixture::file(&build.join("openwiz-service"), "synthetic program");
                return Ok(String::new());
            }
            assert_eq!(call.argv(), ["--update-build"]);
            Ok(format!("{}\n", self.source))
        }
    }
    let f = fixture::Fixture::new();
    let old = f.head();
    let candidate = "2".repeat(40);
    fixture::file(
        &f.install.join("channel.json"),
        "{\"schema\":\"openwiz.update-channel.v1\",\"channel\":\"packaged\"}\n",
    );
    fixture::directory(&f.build(&old).join("runtime"));
    fixture::file(
        &f.build(&old).join("runtime/pull.py"),
        "synthetic verified transport",
    );
    let packages = Arc::new(Packages {
        source: candidate.clone(),
        root: f.root.clone(),
        calls: Default::default(),
    });
    let updater = update::Updater::fixture(
        &f.root,
        &f.install,
        &f.repo,
        &old,
        f.sink(),
        packages.clone(),
    )
    .unwrap();
    assert!(updater.check(&f.state(), 1000).unwrap());
    let calls = packages.calls.lock().unwrap();
    assert_eq!(calls.len(), 3);
    assert_eq!(calls.iter().filter(|c| c[0] == "python3").count(), 2);
    assert!(
        calls
            .iter()
            .all(|c| !matches!(c[0].as_str(), "git" | "cargo" | "npm"))
    );
    assert_eq!(
        std::fs::read_link(f.install.join("current")).unwrap(),
        f.build(&old)
    );
    let journal: serde_json::Value =
        serde_json::from_slice(&std::fs::read(f.root.join("service/update-pending.json")).unwrap())
            .unwrap();
    assert_eq!(journal["to"], candidate);
    assert_eq!(journal["phase"], "queued");
    assert!(f.records().is_empty(), "queued is not switched");
    drop(calls);
    assert!(!updater.check(&f.state(), 2000).unwrap());
    assert_eq!(
        packages.calls.lock().unwrap().len(),
        3,
        "a queued handover is not restaged"
    );
}

#[test]
fn packaged_app_records_are_read_back_once_and_uncertainty_is_not_retried() {
    use std::sync::{Arc, Mutex};
    let calls = Arc::new(Mutex::new(Vec::<Vec<String>>::new()));
    let seen = calls.clone();
    let sink = update::app_record_sink(901, "synthetic-owner/synthetic-repo", Arc::new(move |call, _| {
        seen.lock().unwrap().push(call.argv().to_vec());
        if call.argv()[1] == "comment" {
            Ok(b"https://github.com/synthetic-owner/synthetic-repo/issues/901#issuecomment-123\n".to_vec())
        } else {
            Ok(serde_json::json!({"comments":[{"id":"synthetic-comment","author":null,
                "authorAssociation":"OWNER","body":"synthetic outcome","createdAt":"2030-01-01T00:00:00Z",
                "includesCreatedEdit":false,"isMinimized":false,"minimizedReason":"","reactionGroups":[],
                "url":"https://github.com/synthetic-owner/synthetic-repo/issues/901#issuecomment-123",
                "viewerDidAuthor":true}]}).to_string().into_bytes())
        }
    })).unwrap();
    assert_eq!(sink(901, "synthetic outcome"), Ok(()));
    assert_eq!(calls.lock().unwrap().len(), 2);
    assert_eq!(
        sink(902, "synthetic outcome"),
        Err(update::RecordError::Unsent)
    );
    assert_eq!(calls.lock().unwrap().len(), 2);
    let lost = update::app_record_sink(
        901,
        "synthetic-owner/synthetic-repo",
        Arc::new(|_, _| Err(update::RecordError::Uncertain)),
    )
    .unwrap();
    assert_eq!(
        lost(901, "synthetic outcome"),
        Err(update::RecordError::Uncertain)
    );
}

#[test]
fn packaged_transport_failure_records_kept_and_never_runs_a_source_gate() {
    use std::sync::Arc;
    struct Refuse;
    impl update::Executor for Refuse {
        fn run(&self, call: &update::Call) -> Result<String, String> {
            assert_eq!(call.program(), Path::new("python3"));
            if call.argv()[1] == "discover" {
                Ok(serde_json::json!({"schema":"openwiz.package-candidate.v1","source":"2".repeat(40),
                    "version":"0.0.99","target":"x86_64-unknown-linux-gnu","manifest_sha256":"3".repeat(64)}).to_string())
            } else {
                Err("synthetic corrupt archive".to_owned())
            }
        }
    }
    let f = fixture::Fixture::new();
    let old = f.head();
    fixture::file(
        &f.install.join("channel.json"),
        "{\"schema\":\"openwiz.update-channel.v1\",\"channel\":\"packaged\"}",
    );
    fixture::directory(&f.build(&old).join("runtime"));
    fixture::file(
        &f.build(&old).join("runtime/pull.py"),
        "synthetic transport",
    );
    let updater = update::Updater::fixture(
        &f.root,
        &f.install,
        &f.repo,
        &old,
        f.sink(),
        Arc::new(Refuse),
    )
    .unwrap();
    let state = f.state();
    assert!(!updater.check(&state, 1000).unwrap());
    let saved = state.lock().unwrap().snapshot()["update"].clone();
    assert_eq!(saved["outcome"]["state"], "kept");
    assert_eq!(saved["outcome"]["step"], "fetch");
    assert_eq!(
        std::fs::read_link(f.install.join("current")).unwrap(),
        f.build(&old)
    );
    assert_eq!(f.records().len(), 1);
    contract_record(&f.records()[0], &saved);
    assert!(!updater.check(&state, 2000).unwrap());
    assert_eq!(
        f.records().len(),
        1,
        "the failed candidate is not retried or recorded twice"
    );
}

#[path = "install_engine_app.rs"]
mod installed_engine_app;

#[test]
fn source_updater_fixture_can_compile_the_engine_outcome_reader() {
    let f = fixture::Fixture::new();
    // A source updater still builds the real copied CLI dependency. Exercise
    // that boundary without running its workspace-wide acceptance gate.
    for (package, unit_tests) in [("openwiz-cli", false), ("openwiz-service", true)] {
        let mut command = std::process::Command::new(env!("CARGO"));
        command
            .args(["check", "--offline", "-p", package, "--lib", "--target-dir"])
            .arg(f.temp.join("engine-reader-check"))
            .env("CARGO_BUILD_JOBS", "2")
            .current_dir(&f.repo);
        if unit_tests {
            command.arg("--tests");
        }
        let checked = command.output().unwrap();
        assert!(
            checked.status.success(),
            "{}",
            String::from_utf8_lossy(&checked.stderr)
        );
    }
}
