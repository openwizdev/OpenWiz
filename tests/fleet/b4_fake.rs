use std::fs;
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_cli::state::StartFileStore;
use openwiz_core::fleet::model::{Commit, Number};
use openwiz_core::fleet::starts::{Repository, StartKey, StartRequest};
use openwiz_core::messaging::OpId;
use openwiz_core::new_thread::Settings;
use serde_json::{Value, json};

pub const NEW_THREAD: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/fixtures/room-cli-v127/new-thread"
);

pub const NORMAL: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/fixtures/room-cli-0.43.1/normal"
);

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

pub fn file(name: &str) -> String {
    let path = Path::new(NEW_THREAD).join(name);
    assert!(path.is_file(), "no fixture {path:?}");
    path.to_str().expect("utf-8").to_owned()
}

pub fn created() -> Value {
    json!({"any_spawn": true, "stdout_file": file("spawn-receipt-created.json"), "creates": true})
}

fn project_row(id: &str, name: &str, remote: Value) -> Value {
    json!({
        "id": id,
        "kind": "standard",
        "name": name,
        "gitRemoteUrl": remote,
        "createdAt": 1_699_100_600_000_i64,
        "updatedAt": 1_699_200_600_000_i64,
        "sources": [],
    })
}

fn defaults(catalogue: &Path) -> Vec<Value> {
    let projects = json!([project_row(
        PROJECT,
        "Synthetic project one",
        json!("https://github.com/synthetic-owner/synthetic-repo-0001.git"),
    )]);
    vec![
        json!({"argv": ["--version"], "stdout": "v127\n"}),
        json!({
            "argv": ["project", "list", "--json", "--include-personal"],
            "stdout": projects.to_string(),
        }),
        json!({
            "argv": ["project", "list", "--json", "--include-personal", "--hidden"],
            "stdout": "[]",
        }),
        json!({"argv": ["cloud", "status", "--json"], "stdout_file": catalogue}),
        created(),
        json!({
            "argv": ["thread", "show", THREAD, "--json"],
            "stdout_file": file("thread-show-active.json"),
        }),
    ]
}

fn catalogue() -> Value {
    let text = fs::read_to_string(file("cloud-status.json")).expect("the catalogue");
    let mut catalogue: Value = serde_json::from_str(&text).expect("JSON");
    for harness in catalogue["harnesses"].as_array_mut().expect("harnesses") {
        let model = match harness["id"].as_str() {
            Some("codex") => "gpt-6.1-sol",
            Some("claude-code") => "claude-opus-5-5",
            _ => continue,
        };
        harness["models"][0]["model"] = json!(model);
    }
    catalogue
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
    pub dir: PathBuf,
    pub state: PathBuf,
}

impl Fake {
    pub fn new(test: &str, responses: Vec<Value>) -> Self {
        let dir = Path::new(env!("CARGO_TARGET_TMPDIR"))
            .join("b4-fake")
            .join(test);
        let state = run_root().join(format!("{test}-state"));
        let _ = fs::remove_dir_all(&dir);
        let _ = fs::remove_dir_all(&state);
        private_dir(&dir);
        std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-room-cli"), dir.join("room-cli"))
            .expect("link the fake");
        fs::write(dir.join("fake-room-cli.state"), state.to_str().unwrap()).expect("state");
        fs::write(dir.join("catalogue.json"), catalogue().to_string()).expect("catalogue");
        let fake = Self { dir, state };
        fake.respond(responses);
        fake
    }

    pub fn respond(&self, mut responses: Vec<Value>) {
        responses.extend(defaults(&self.dir.join("catalogue.json")));
        let scenario = json!({
            "scenario": "own",
            "description": "A B4 test's own responses.",
            "extends": NORMAL,
            "synthetic_assumptions": ["Written by the test; every value is synthetic."],
            "responses": responses,
        });
        let own = self.dir.join("own");
        private_dir(&own);
        let file = own.join("scenario.json");
        fs::write(&file, serde_json::to_string_pretty(&scenario).unwrap()).expect("scenario");
        fs::write(
            self.dir.join("fake-room-cli.scenario"),
            file.to_str().unwrap(),
        )
        .expect("scenario pointer");
    }

    pub fn program(&self) -> PathBuf {
        self.dir.join("room-cli")
    }

    pub fn source(&self) -> CloudRoomSource {
        CloudRoomSource::new(self.program())
    }

    pub fn starts(&self) -> StartFileStore {
        StartFileStore::open(&self.state).expect("open the start record")
    }

    pub fn invocations(&self) -> Vec<Vec<String>> {
        let Ok(text) = fs::read_to_string(self.dir.join("invocations.log")) else {
            return vec![];
        };
        text.lines()
            .map(|l| serde_json::from_str(l).expect("a JSON line"))
            .collect()
    }

    fn counter(&self, name: &str) -> u64 {
        let path = self.dir.join(name);
        let Ok(mut file) = fs::File::open(&path) else {
            return 0;
        };
        file.lock_shared().expect("lock the counter");
        let mut text = String::new();
        std::io::Read::read_to_string(&mut file, &mut text).expect("read the counter");
        if text.is_empty() {
            0
        } else {
            text.parse().expect("a count")
        }
    }

    pub fn archive_count(&self) -> u64 {
        self.counter("archive-calls.count")
    }
}
