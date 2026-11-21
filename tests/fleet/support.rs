use std::ffi::OsString;
use std::fs;
use std::fs::DirBuilder;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Mutex, OnceLock};

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

pub const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/fixtures/github");

pub struct FakeGh {
    pub dir: PathBuf,
}

impl FakeGh {
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

    pub fn set_scenario(&self, scenario: &Path) {
        fs::write(
            self.dir.join("fake-gh.scenario"),
            scenario.to_str().expect("a UTF-8 path"),
        )
        .expect("write the scenario pointer");
    }

    pub fn program(&self) -> PathBuf {
        self.dir.join("gh")
    }

    pub fn invocations(&self) -> Vec<Vec<String>> {
        lines(&self.dir.join("gh-invocations.log"))
    }

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

pub type Run = fn(&[OsString], &mut dyn Write, &mut dyn Write) -> i32;

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

pub fn left_behind(dir: &Path) -> Vec<String> {
    let mut left: Vec<String> = fs::read_dir(dir)
        .expect("read the test directory")
        .map(|e| e.expect("entry").file_name().to_string_lossy().into_owned())
        .filter(|name| name != "room-cli" && name != "gh")
        .collect();
    left.sort();
    left
}
