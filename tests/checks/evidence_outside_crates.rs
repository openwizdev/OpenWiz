//! #780 and #1277: product crates carry no build evidence into a public
//! tree. Private archival completeness belongs to the private record, so
//! these public checks require only the product tree and its Git index.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");
fn root() -> PathBuf {
    Path::new(ROOT).to_path_buf()
}

/// The crate names with an `evidence/` folder on disk.
fn evidence_folders() -> Vec<String> {
    let mut out = Vec::new();
    for entry in fs::read_dir(root().join("crates")).expect("crates/") {
        let entry = entry.expect("crates/ entry");
        if entry.file_type().expect("type").is_dir() && entry.path().join("evidence").is_dir() {
            out.push(entry.file_name().to_string_lossy().into_owned());
        }
    }
    out.sort();
    out
}

/// The Git-tracked files, one relative path each. The pre-push hook supplies
/// the pushed commit's NUL-delimited manifest before cutting off Git access.
/// A supplied manifest must be readable; never fall back to another tree.
fn tracked() -> BTreeSet<String> {
    let bytes = if let Some(manifest) = std::env::var_os("OPENWIZ_TRACKED_FILES") {
        let bytes = fs::read(manifest).expect("read tracked-file manifest");
        assert!(!bytes.is_empty(), "empty tracked-file manifest");
        bytes
    } else {
        let out = Command::new("git")
            .arg("-C")
            .arg(root())
            .args(["ls-files", "-z"])
            .output()
            .expect("git ls-files runs");
        assert!(out.status.success(), "git ls-files failed");
        out.stdout
    };
    let paths = String::from_utf8(bytes).expect("Git paths are UTF-8");
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
fn no_product_crate_keeps_an_evidence_folder() {
    assert_eq!(
        evidence_folders(),
        Vec::<String>::new(),
        "move build evidence out of the product crates and update its links"
    );
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
