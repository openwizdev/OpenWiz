use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::process::Command;

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");
fn root() -> PathBuf {
    Path::new(ROOT).to_path_buf()
}

fn tracked() -> BTreeSet<String> {
    let out = Command::new("git")
        .arg("-C")
        .arg(root())
        .args(["ls-files", "-z"])
        .output()
        .expect("git ls-files runs");
    assert!(out.status.success(), "git ls-files failed");
    let paths = String::from_utf8(out.stdout).expect("Git paths are UTF-8");
    assert!(
        paths.is_empty() || paths.ends_with('\0'),
        "tracked-file list must be NUL-terminated"
    );
    let mut tracked = BTreeSet::new();
    for path in paths.split_terminator('\0') {
        assert!(!path.is_empty(), "tracked-file list has an empty path");
        assert!(
            tracked.insert(path.to_owned()),
            "duplicate tracked-file path"
        );
    }
    tracked
}

#[test]
fn no_product_evidence_is_tracked_for_export() {
    let paths = tracked();
    let evidence: Vec<_> = paths
        .iter()
        .filter(|path| {
            path.starts_with("crates/") && path.split('/').any(|part| part == "evidence")
        })
        .collect();
    assert!(
        evidence.is_empty(),
        "tracked product evidence: {evidence:?}"
    );
}
