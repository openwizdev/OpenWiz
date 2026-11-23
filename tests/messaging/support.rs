use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::{SystemTime, UNIX_EPOCH};

pub const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/fixtures/room-cli-0.43.1");
pub const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

pub fn run_root() -> &'static Path {
    static ROOT: OnceLock<PathBuf> = OnceLock::new();
    ROOT.get_or_init(|| {
        let parent = std::env::temp_dir().join("openwiz-messaging-tests");
        crate::dirs::private_dir_all(&parent).expect("create the messaging tests' temp dir");
        let planted = fs::symlink_metadata(&parent).map_or(true, |m| !m.is_dir());
        assert!(!planted, "{parent:?} is not a plain directory");
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |d| d.as_nanos());
        let root = parent.join(format!("{}-{nanos}", std::process::id()));
        crate::dirs::private_dir(&root).expect("create this run's own temp dir");
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).expect("make it private");
        root
    })
}

pub struct SendFake {
    pub dir: PathBuf,
    pub state: PathBuf,
}

impl SendFake {
    pub fn new(test: &str, scenario: &str) -> Self {
        let fake = Self::bare(test);
        fake.set_scenario(&Path::new(FIXTURES).join(scenario).join("scenario.json"));
        fake
    }

    fn bare(test: &str) -> Self {
        let base = Path::new(env!("CARGO_TARGET_TMPDIR")).join("send-fake");
        let dir = base.join(test);
        let state = run_root().join(format!("{test}-state"));
        let _ = fs::remove_dir_all(&dir);
        let _ = fs::remove_dir_all(&state);
        crate::dirs::private_dir_all(&dir).expect("create fake dir");
        std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-room-cli"), dir.join("room-cli"))
            .expect("link fake room-cli");
        fs::write(
            dir.join("fake-room-cli.state"),
            state.to_str().expect("utf-8 path"),
        )
        .expect("write state pointer");
        Self { dir, state }
    }

    fn set_scenario(&self, file: &Path) {
        assert!(file.is_file(), "no scenario {file:?}");
        fs::write(
            self.dir.join("fake-room-cli.scenario"),
            file.to_str().expect("utf-8 path"),
        )
        .expect("write scenario pointer");
    }

    pub fn program(&self) -> PathBuf {
        self.dir.join("room-cli")
    }

    pub fn tell_count(&self) -> u64 {
        crate::counter::read(&self.dir.join("tell-calls.count"))
    }
}

impl Drop for SendFake {
    fn drop(&mut self) {
        if !std::thread::panicking() {
            let _ = fs::remove_dir_all(&self.state);
        }
    }
}
