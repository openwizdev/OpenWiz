use std::fs;
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use openwiz_cli::state::StartFileStore;
use openwiz_core::fleet::model::{Commit, Number};
use openwiz_core::fleet::starts::{Repository, StartKey, StartRequest};
use openwiz_core::messaging::OpId;
use openwiz_core::new_thread::Settings;

pub const PROJECT: &str = "prj_syn_0001";
pub const THREAD: &str = "thr_syn_0021";

pub const REPOSITORY: &str = "synthetic-owner/synthetic-repo-0001";

pub const COMMIT: &str = "0123456789abcdef0123456789abcdef01234567";

pub const T0: i64 = 1_700_000_000_000;

pub fn repository() -> Repository {
    Repository::parse(REPOSITORY).expect("a repository")
}

pub fn number(n: u64) -> Number {
    Number::new(n).expect("1 or more")
}

pub fn op(id: &str) -> OpId {
    OpId::parse(id).expect("an op id")
}

pub fn settings(harness: &str, model: &str, effort: &str) -> Settings {
    Settings {
        harness: harness.to_owned(),
        model: model.to_owned(),
        effort: effort.to_owned(),
    }
}

pub fn builder_settings() -> Settings {
    settings("claude-code", "claude-opus-5-5", "xhigh")
}

pub fn reviewer_settings() -> Settings {
    settings("codex", "gpt-6.1-sol", "high")
}

pub fn builder(ticket: u64) -> StartRequest {
    StartRequest::new(
        StartKey::builder(repository(), number(ticket)),
        PROJECT,
        builder_settings(),
    )
}

pub fn reviewer(pr: u64) -> StartRequest {
    StartRequest::new(
        StartKey::reviewer(
            repository(),
            number(pr),
            Commit::parse(COMMIT).expect("a commit"),
        ),
        PROJECT,
        reviewer_settings(),
    )
}

fn run_root() -> &'static Path {
    static ROOT: OnceLock<PathBuf> = OnceLock::new();
    ROOT.get_or_init(|| {
        let parent = std::env::temp_dir().join("openwiz-b4-fake");
        private_dir(&parent);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_nanos());
        let root = parent.join(format!("{}-{nanos}", std::process::id()));
        private_dir(&root);
        root
    })
}

fn private_dir(dir: &Path) {
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(dir)
        .unwrap_or_else(|e| panic!("make {}: {e}", dir.display()));
    fs::set_permissions(dir, fs::Permissions::from_mode(0o700)).expect("private");
}

pub struct Fake {
    pub state: PathBuf,
}

impl Fake {
    pub fn new(test: &str) -> Self {
        let state = run_root().join(format!("{test}-state"));
        let _ = fs::remove_dir_all(&state);
        Self { state }
    }

    pub fn starts(&self) -> StartFileStore {
        StartFileStore::open(&self.state).expect("open the start record")
    }
}
