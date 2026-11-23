use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::dirs::private_dir_all;

const TESTS: &str = env!("CARGO_MANIFEST_DIR");

struct Scratch(PathBuf);

impl Scratch {
    fn new(case: &str) -> Scratch {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = env::temp_dir().join(format!(
            "openwiz-build-script-{case}-{}-{nanos}",
            std::process::id()
        ));
        private_dir_all(&dir).unwrap();
        Scratch(dir)
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn clean(mut command: Command) -> Command {
    for (key, _) in env::vars_os() {
        let key = key.to_string_lossy().into_owned();
        let cargo_setting = key.starts_with("CARGO_") && key != "CARGO_HOME";
        if key.starts_with("GIT_") || cargo_setting || key == "OPENWIZ_SERVICE_BUILD" {
            command.env_remove(&key);
        }
    }
    command
}

fn git(dir: &Path, args: &[&str]) -> String {
    let mut command = clean(Command::new("git"));
    command
        .current_dir(dir)
        .args(["-c", "user.name=Synthetic Builder"])
        .args(["-c", "user.email=builder@example.invalid"])
        .args(["-c", "commit.gpgsign=false"])
        .args(args);
    let out = command.output().expect("run git");
    assert!(
        out.status.success(),
        "git {args:?}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).unwrap().trim().to_owned()
}

fn repo(scratch: &Scratch) -> PathBuf {
    let root = scratch.0.join("repo");
    let cli = root.join("crates/cli");
    private_dir_all(cli.join("src")).unwrap();
    let script = Path::new(TESTS).join("../crates/cli/build.rs");
    fs::copy(script, cli.join("build.rs")).unwrap();
    fs::write(
        cli.join("Cargo.toml"),
        "[package]\nname = \"openwiz-cli\"\nversion = \"0.0.0\"\nedition = \"2024\"\n\n[workspace]\n",
    )
    .unwrap();
    fs::write(
        cli.join("src/main.rs"),
        "fn main() {\n    print!(\"{}\", env!(\"OPENWIZ_SERVICE_BUILD\"));\n}\n",
    )
    .unwrap();
    fs::write(root.join(".gitignore"), "target/\n").unwrap();
    git(&scratch.0, &["init", "-q", "-b", "main", "repo"]);
    commit(&root, "first");
    root
}

fn commit(root: &Path, message: &str) {
    git(root, &["add", "-A"]);
    git(root, &["commit", "-q", "--allow-empty", "-m", message]);
}

fn build(root: &Path, target: &Path) -> bool {
    let cargo = env::var_os("CARGO").unwrap_or_else(|| "cargo".into());
    let mut command = clean(Command::new(cargo));
    command
        .current_dir(root.join("crates/cli"))
        .env("CARGO_TARGET_DIR", target)
        .args(["build", "-v", "--offline"]);
    let out = command.output().expect("run cargo");
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(out.status.success(), "cargo build: {stderr}");
    let ran = stderr.lines().any(|line| {
        line.trim_start().starts_with("Running") && line.contains("build-script-build")
    });
    let fresh = stderr
        .lines()
        .any(|line| line.trim_start().starts_with("Fresh openwiz-cli"));
    assert_ne!(ran, fresh, "neither ran nor fresh: {stderr}");
    ran
}

fn identity(target: &Path) -> String {
    let out = Command::new(target.join("debug/openwiz-cli"))
        .output()
        .expect("run the built program");
    String::from_utf8(out.stdout).unwrap()
}

fn builds_once(root: &Path, target: &Path) {
    let expected = git(root, &["rev-parse", "HEAD"]);
    build(root, target);
    assert_eq!(identity(target), expected, "the build identity");
    assert!(
        !build(root, target),
        "a second build with no changes reran the build script"
    );
}

#[test]
fn a_branch_build_reads_its_commit_and_a_second_build_does_nothing() {
    let scratch = Scratch::new("branch");
    let root = repo(&scratch);
    builds_once(&root, &scratch.0.join("target"));
}

#[test]
fn a_packed_branch_build_reads_its_commit_and_a_second_build_does_nothing() {
    let scratch = Scratch::new("packed");
    let root = repo(&scratch);
    git(&root, &["pack-refs", "--all"]);
    assert!(!root.join(".git/refs/heads/main").exists());
    builds_once(&root, &scratch.0.join("target"));
}

#[test]
fn a_detached_build_reads_its_commit_and_a_second_build_does_nothing() {
    let scratch = Scratch::new("detached");
    let root = repo(&scratch);
    commit(&root, "second");
    git(&root, &["checkout", "-q", "--detach", "HEAD~1"]);
    builds_once(&root, &scratch.0.join("target"));
}

#[test]
fn a_worktree_build_reads_its_commit_and_a_second_build_does_nothing() {
    let scratch = Scratch::new("worktree");
    let root = repo(&scratch);
    let tree = scratch.0.join("tree");
    git(
        &root,
        &[
            "worktree",
            "add",
            "-q",
            "-b",
            "side",
            tree.to_str().unwrap(),
        ],
    );
    commit(&tree, "on side");
    builds_once(&tree, &scratch.0.join("target"));
}

#[test]
fn a_ref_that_appears_after_the_first_build_rebuilds_with_the_new_commit() {
    let scratch = Scratch::new("appears");
    let root = repo(&scratch);
    let target = scratch.0.join("target");
    git(&root, &["pack-refs", "--all"]);
    builds_once(&root, &target);
    commit(&root, "second");
    assert!(root.join(".git/refs/heads/main").exists());
    assert!(
        build(&root, &target),
        "the new ref did not rerun the build script"
    );
    assert_eq!(identity(&target), git(&root, &["rev-parse", "HEAD"]));
}
