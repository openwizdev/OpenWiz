//! `ci/rust-tests.sh`, as #1260 changed it. The fixture release `openwiz`
//! (P10's, and the subprocess proofs') is built once, before any test
//! starts, on either of its paths, so no test binary's time includes the
//! release build; a failed build stops the step before a test runs (Q1). On
//! its one-command path the tests run with 8 test threads, since they
//! mostly wait on child processes, keeping #1253's main-only skips; and a
//! failed test run fails the step (Q3).
//!
//! Each case runs the real script with a fake `cargo` and `nproc` first on
//! `PATH` and, for the every-target-at-once path, a fake cgroup
//! (`RUST_TESTS_ROOT`). The fake `cargo` logs each call and runs nothing.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Command;

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

const PREBUILD: &str = "build --release --locked -p openwiz-tests --example openwiz";

/// Which path the script takes.
#[derive(Clone, Copy)]
enum Route {
    /// Fewer than 4 CPUs: one `cargo test --workspace`.
    OneCommand,
    /// 8 CPUs and a container that allows them: every target at once.
    AtOnce,
}

/// How a run goes: the release build's and the tests' exit codes, and
/// whether it is a pull request to `main`.
#[derive(Clone, Copy)]
struct Run {
    build_exit: i32,
    test_exit: i32,
    pull_request_to_main: bool,
}

const PLAIN: Run = Run {
    build_exit: 0,
    test_exit: 0,
    pull_request_to_main: false,
};

/// Runs `ci/rust-tests.sh` with the fakes. Returns (the script's exit code,
/// each cargo call).
fn run(case: &str, route: Route, how: Run) -> (Option<i32>, Vec<String>) {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join(format!("ci-prebuild-{case}"));
    let _ = fs::remove_dir_all(&dir);
    let bin = dir.join("bin");
    crate::dirs::private_dir_all(&bin).unwrap();
    let log = dir.join("cargo.log");
    let script = |name: &str, body: &str| {
        let file = bin.join(name);
        fs::write(&file, format!("#!/bin/sh\n{body}")).unwrap();
        fs::set_permissions(&file, fs::Permissions::from_mode(0o755)).unwrap();
    };
    script(
        "cargo",
        "printf '%s\\n' \"$*\" >> \"$FAKE_CARGO_LOG\"\n\
         case \"$1\" in build) exit \"$FAKE_BUILD_EXIT\" ;; test) exit \"$FAKE_TEST_EXIT\" ;; esac\n\
         exit 0\n",
    );
    let cpus = match route {
        Route::OneCommand => 2,
        Route::AtOnce => 8,
    };
    script("nproc", &format!("echo {cpus}\n"));
    // A cgroup v2 root that sets no limits: the at-once path's room.
    let fake_root = dir.join("root");
    let cgroup = fake_root.join("sys/fs/cgroup");
    crate::dirs::private_dir_all(&cgroup).unwrap();
    crate::dirs::private_dir_all(fake_root.join("proc/self")).unwrap();
    fs::write(cgroup.join("cgroup.controllers"), "cpu memory\n").unwrap();
    fs::write(fake_root.join("proc/self/cgroup"), "0::/\n").unwrap();
    let path_var = format!(
        "{}:{}",
        bin.display(),
        std::env::var("PATH").unwrap_or_default()
    );
    let mut command = Command::new("sh");
    command
        .arg("ci/rust-tests.sh")
        .current_dir(ROOT)
        .env("PATH", path_var)
        .env("RUST_TESTS_ROOT", &fake_root)
        .env("FAKE_CARGO_LOG", &log)
        .env("FAKE_BUILD_EXIT", how.build_exit.to_string())
        .env("FAKE_TEST_EXIT", how.test_exit.to_string())
        .env_remove("GITHUB_EVENT_NAME")
        .env_remove("GITHUB_BASE_REF");
    let mut command = command;
    if how.pull_request_to_main {
        command
            .env("GITHUB_EVENT_NAME", "pull_request")
            .env("GITHUB_BASE_REF", "main");
    }
    let out = command.output().expect("run ci/rust-tests.sh");
    let calls = fs::read_to_string(&log)
        .unwrap_or_default()
        .lines()
        .map(str::to_owned)
        .collect();
    (out.status.code(), calls)
}

#[test]
fn the_release_fixture_is_built_once_before_the_tests() {
    let (code, calls) = run("built", Route::OneCommand, PLAIN);
    assert_eq!(code, Some(0), "{calls:?}");
    assert_eq!(calls.len(), 2, "{calls:?}");
    assert_eq!(calls[0], PREBUILD, "first, the release fixture");
    assert!(
        calls[1].starts_with("test --workspace --locked"),
        "then the tests: {calls:?}"
    );
}

#[test]
fn a_failed_release_build_starts_no_test_on_either_path() {
    for (case, route) in [
        ("failed-one-command", Route::OneCommand),
        ("failed-at-once", Route::AtOnce),
    ] {
        let how = Run {
            build_exit: 7,
            ..PLAIN
        };
        let (code, calls) = run(case, route, how);
        assert_eq!(code, Some(7), "{case}: {calls:?}");
        assert_eq!(calls, [PREBUILD], "{case}: no test started");
    }
}

#[test]
fn the_one_command_path_runs_eight_test_threads() {
    let (code, calls) = run("threads", Route::OneCommand, PLAIN);
    assert_eq!(code, Some(0), "{calls:?}");
    assert_eq!(
        calls,
        [PREBUILD, "test --workspace --locked -- --test-threads=8"]
    );
}

#[test]
fn a_pull_request_to_main_keeps_the_main_only_skips_with_eight_threads() {
    let how = Run {
        pull_request_to_main: true,
        ..PLAIN
    };
    let (code, calls) = run("threads-pr", Route::OneCommand, how);
    assert_eq!(code, Some(0), "{calls:?}");
    assert_eq!(
        calls,
        [
            PREBUILD,
            "test --workspace --locked -- --test-threads=8 --exact \
             --skip a_candidate_that_exits_without_readiness_rolls_back_to_the_running_old_build \
             --skip a_failing_merge_is_kept_and_recorded_once_without_retrying_the_gate \
             --skip a_passing_main_merge_is_staged_but_not_reported_as_running \
             --skip a_real_candidate_must_confirm_readiness_before_selection_or_switched"
        ]
    );
}

#[test]
fn a_failed_test_run_fails_the_step() {
    let how = Run {
        test_exit: 101,
        ..PLAIN
    };
    let (code, calls) = run("tests-failed", Route::OneCommand, how);
    assert_eq!(code, Some(101), "{calls:?}");
    assert_eq!(calls.len(), 2, "{calls:?}");
}
