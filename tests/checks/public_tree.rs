//! Public-tree promises from #1277: CI needs no private files, and every
//! public link in contracts, code, apps and tests uses OpenWiz's final address.

use std::fs;
use std::path::Path;
use std::process::Command;

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

#[test]
fn ci_needs_no_private_files() {
    let reads = fs::read_to_string(Path::new(ROOT).join(".github/actions/docs-only/ci-reads.txt"))
        .expect("CI's private-read list is readable");
    assert!(reads.trim().is_empty(), "CI still requires private files");
}

#[test]
fn public_files_use_the_final_openwiz_address() {
    let old = concat!("jparker2006/", "OpenWiz");
    // CI prunes files a job never reads from the worktree. Check the public
    // Git index so this guard still covers those files without requiring
    // deleted files (or build output) to exist on disk.
    let receipt = std::env::var_os("OPENWIZ_PUBLIC_TREE_RECEIPT");
    let commit = std::env::var_os("OPENWIZ_CHECKED_COMMIT");
    let (code, stdout) = if receipt.is_some() || commit.is_some() {
        // The hook scans its dedicated pushed-commit index before isolation.
        // Both inputs are mandatory here; a bad receipt cannot fall back to
        // the checkout, nor can an earlier commit's clear result be reused.
        let commit = commit
            .expect("public-tree receipt commit binding")
            .into_string()
            .expect("public-tree receipt commit is UTF-8");
        assert!(
            matches!(commit.len(), 40 | 64) && commit.bytes().all(|b| b.is_ascii_hexdigit()),
            "invalid public-tree receipt commit binding"
        );
        let bytes = fs::read(receipt.expect("missing public-tree receipt"))
            .expect("read public-tree receipt");
        let text = String::from_utf8(bytes).expect("public-tree receipt is UTF-8");
        assert!(text.ends_with('\0'), "unterminated public-tree receipt");
        let fields: Vec<_> = text.split_terminator('\0').collect();
        assert!(fields.len() >= 9, "incomplete public-tree receipt");
        assert_eq!(
            fields[0], "openwiz-public-tree-v1",
            "public-tree receipt version"
        );
        assert_eq!(fields[1], commit, "public-tree receipt commit mismatch");
        assert_eq!(
            fields[2], "git grep --cached -a -l -z -F -e",
            "public-tree receipt operation mismatch"
        );
        assert_eq!(fields[3], old, "public-tree receipt pattern mismatch");
        assert_eq!(
            &fields[4..8],
            &["contracts", "crates", "apps", "tests"],
            "public-tree receipt scopes mismatch"
        );
        assert!(matches!(fields[8], "0" | "1"), "public-tree receipt status");
        assert_eq!(
            fields[8] == "1",
            fields.len() == 9,
            "public-tree receipt status disagrees with matches"
        );
        let mut seen = std::collections::BTreeSet::new();
        for path in &fields[9..] {
            assert!(
                !path.is_empty()
                    && seen.insert(*path)
                    && fields[4..8].iter().any(|scope| {
                        path == scope
                            || path.strip_prefix(scope).is_some_and(|p| p.starts_with('/'))
                    }),
                "invalid public-tree receipt match"
            );
        }
        let stdout = if fields.len() == 9 {
            Vec::new()
        } else {
            format!("{}\0", fields[9..].join("\0")).into_bytes()
        };
        (Some(if fields[8] == "0" { 0 } else { 1 }), stdout)
    } else {
        let output = Command::new("git")
            .args([
                "grep",
                "--cached",
                "-a",
                "-l",
                "-z",
                "-F",
                "-e",
                old,
                "--",
                "contracts",
                "crates",
                "apps",
                "tests",
            ])
            .current_dir(ROOT)
            .output()
            .expect("scan the public Git index");
        (output.status.code(), output.stdout)
    };
    assert!(matches!(code, Some(0 | 1)), "git grep failed");
    assert!(
        code == Some(1),
        "old OpenWiz address in: {}",
        String::from_utf8_lossy(&stdout).replace('\0', "\n")
    );
}
