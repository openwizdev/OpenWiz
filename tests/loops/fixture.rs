use openwiz_cli::state::loops::{Context, Trust};
use serde_json::{Value, json};
use std::{
    fs,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::{Path, PathBuf},
    process::Command,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
};

pub struct Trusted;
impl Trust for Trusted {
    fn verify(&self, _: &Path, repository: &str, project: &str) -> bool {
        repository == "synthetic-owner/synthetic-repo" && project == "prj_syn_example"
    }
    fn actor(&self) -> Option<String> {
        Some("synthetic-operator".to_owned())
    }
}
pub struct Fixture {
    pub root: PathBuf,
    pub context: Context,
    pub definition: Value,
}
pub fn git(root: &Path, args: &[&str]) {
    let out = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "git {args:?}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
}
impl Fixture {
    pub fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "ow-l6-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let checkout = root.join("checkout");
        let state = root.join("state");
        for p in [checkout.join("loops"), state.join("service")] {
            fs::DirBuilder::new()
                .recursive(true)
                .mode(0o700)
                .create(p)
                .unwrap();
        }
        fs::write(state.join("service/config.json"), "{}").unwrap();
        fs::set_permissions(
            state.join("service/config.json"),
            fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        git(&checkout, &["init", "-q", "--initial-branch=main"]);
        git(&checkout, &["config", "user.name", "Synthetic Builder"]);
        git(
            &checkout,
            &["config", "user.email", "synthetic@example.invalid"],
        );
        let mut definition: Value =
            serde_json::from_str(include_str!("../../loops/example.json")).unwrap();
        definition["enabled"] = json!(true);
        let f = Self {
            root,
            context: Context {
                checkout,
                state,
                repository: "synthetic-owner/synthetic-repo".to_owned(),
                project: "prj_syn_example".to_owned(),
                trust: Some(Arc::new(Trusted)),
            },
            definition,
        };
        f.commit();
        f
    }
    pub fn commit(&self) {
        fs::write(
            self.context.checkout.join("loops/example.json"),
            self.definition.to_string(),
        )
        .unwrap();
        git(&self.context.checkout, &["add", "loops"]);
        git(
            &self.context.checkout,
            &["commit", "-qm", "Synthetic definition"],
        );
        git(
            &self.context.checkout,
            &["update-ref", "refs/remotes/origin/main", "HEAD"],
        );
        git(
            &self.context.checkout,
            &[
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/main",
            ],
        );
    }
    pub fn saved(&self) -> Value {
        serde_json::from_str(
            &fs::read_to_string(self.context.state.join("service/loops/enabled.json")).unwrap(),
        )
        .unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}
