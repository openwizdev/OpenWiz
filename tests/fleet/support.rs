//! The fakes for the fleet tests (A3, ClosedWiz#111), for every ticket's
//! tests to use: the fake `gh`, a directory with both fakes first on
//! `PATH`, the release `openwiz`, and a command's `run` in-process. A
//! ticket that needs more writes it in its own file, never here.

#![allow(dead_code)]

use std::ffi::OsString;
use std::fs;
use std::fs::DirBuilder;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Mutex, OnceLock};

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

/// The GitHub fixtures: one folder per ticket (`fleets/` for A4,
/// `tickets/` for A5), one scenario folder in each.
pub const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/fixtures/github");

/// A private directory with the fake `gh` (`tests/fake-gh/main.rs`) set to
/// one scenario file.
pub struct FakeGh {
    pub dir: PathBuf,
}

impl FakeGh {
    /// `test` names the directory, so each test has its own; `scenario` is
    /// the scenario file's path.
    pub fn new(test: &str, scenario: &Path) -> Self {
        let dir = Path::new(env!("CARGO_TARGET_TMPDIR"))
            .join("fake-gh")
            .join(test);
        let _ = fs::remove_dir_all(&dir);
        DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(&dir)
            .expect("create the fake's directory");
        std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-gh"), dir.join("gh"))
            .expect("link the fake gh");
        let fake = Self { dir };
        fake.set_scenario(scenario);
        fake
    }

    /// Points this fake at another scenario file.
    pub fn set_scenario(&self, scenario: &Path) {
        fs::write(
            self.dir.join("fake-gh.scenario"),
            scenario.to_str().expect("a UTF-8 path"),
        )
        .expect("write the scenario pointer");
    }

    /// The fake, by its absolute path.
    pub fn program(&self) -> PathBuf {
        self.dir.join("gh")
    }

    /// Every argument list the fake received, in order.
    pub fn invocations(&self) -> Vec<Vec<String>> {
        lines(&self.dir.join("gh-invocations.log"))
    }

    /// For each call, in order, the names of its `GH_*` and `GITHUB_*`
    /// variables, sorted.
    pub fn environments(&self) -> Vec<Vec<String>> {
        lines(&self.dir.join("gh-environment.log"))
    }

    /// The process id of a fake that hung, once it has written it.
    pub fn hung_pid(&self) -> Option<String> {
        fs::read_to_string(self.dir.join("gh-hang.pid")).ok()
    }
}

fn lines(path: &Path) -> Vec<Vec<String>> {
    let Ok(text) = fs::read_to_string(path) else {
        return vec![];
    };
    text.lines()
        .map(|l| serde_json::from_str(l).expect("a log line is a JSON list of strings"))
        .collect()
}

/// What `main.rs` calls for a command: its arguments after the command
/// name, stdout and stderr; its exit code.
pub type Run = fn(&[OsString], &mut dyn Write, &mut dyn Write) -> i32;

/// Runs a command's `run` in-process: (exit code, stdout, stderr).
pub fn in_process(run: Run, args: &[&str]) -> (i32, String, String) {
    let args: Vec<OsString> = args.iter().map(OsString::from).collect();
    let (mut out, mut err) = (Vec::new(), Vec::new());
    let code = run(&args, &mut out, &mut err);
    (
        code,
        String::from_utf8(out).expect("UTF-8 stdout"),
        String::from_utf8(err).expect("UTF-8 stderr"),
    )
}

/// Builds the release `openwiz` once per test run, as P10 does.
pub fn openwiz_release() -> PathBuf {
    static BUILT: OnceLock<PathBuf> = OnceLock::new();
    static LOCK: Mutex<()> = Mutex::new(());
    let _guard = LOCK.lock().unwrap_or_else(|p| p.into_inner());
    BUILT
        .get_or_init(|| {
            let target = Path::new(env!("CARGO_TARGET_TMPDIR"))
                .parent()
                .expect("the target directory")
                .to_path_buf();
            let cargo = std::env::var("CARGO").unwrap_or_else(|_| "cargo".to_owned());
            let build = Command::new(cargo)
                .args(["build", "--release", "--locked", "-p", "openwiz-tests"])
                .args(["--example", "openwiz", "--target-dir"])
                .arg(&target)
                .current_dir(ROOT)
                .output()
                .expect("run cargo build --release");
            assert!(
                build.status.success(),
                "cargo build --release failed:\n{}",
                String::from_utf8_lossy(&build.stderr)
            );
            target.join("release").join("examples").join("openwiz")
        })
        .clone()
}

/// A private directory for `test` holding `room-cli` and `gh`, linked to
/// the two fakes with no scenario, so any call either gets is logged and
/// refused; and a `PATH` with it first.
pub fn fakes_on_path(test: &str) -> (PathBuf, String) {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR"))
        .join("fakes-on-path")
        .join(test);
    let _ = fs::remove_dir_all(&dir);
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&dir)
        .expect("create the test directory");
    std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-room-cli"), dir.join("room-cli"))
        .expect("link the fake room-cli");
    std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-gh"), dir.join("gh"))
        .expect("link the fake gh");
    let path = format!(
        "{}:{}",
        dir.display(),
        std::env::var("PATH").unwrap_or_default()
    );
    (dir, path)
}

/// What a run left in a [`fakes_on_path`] directory besides the two links:
/// the fakes' logs, if either was called.
pub fn left_behind(dir: &Path) -> Vec<String> {
    let mut left: Vec<String> = fs::read_dir(dir)
        .expect("read the test directory")
        .map(|e| e.expect("entry").file_name().to_string_lossy().into_owned())
        .filter(|name| name != "room-cli" && name != "gh")
        .collect();
    left.sort();
    left
}
