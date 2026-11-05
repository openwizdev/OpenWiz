//! A3 (ClosedWiz#111): the seams for seeing fleets, with no behaviour.
//!
//! - **The seams:** each file a later ticket owns exists and is declared, by
//!   one exact line, in a file only A3 owns, so A4, A5, A6 and spec 2's B3
//!   never edit the same file.
//! - **Dependency direction:** the new GitHub adapter crate depends on the
//!   core, and on no client and no other adapter; the core never depends on
//!   it. The CLI depends on it directly, so A4 and A5 never edit the CLI's
//!   manifest.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::Value;

const CORE: &str = "openwiz-core";
const GITHUB: &str = "openwiz-adapter-github";

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
}

/// Each later ticket's file, the file that declares it, and the exact line
/// there that does.
const SEAMS: &[(&str, &str, &str)] = &[
    // The core's fleet model (A4, A5, A6).
    (
        "crates/core/src/fleet/mod.rs",
        "crates/core/src/lib.rs",
        "pub mod fleet;",
    ),
    // The contract's model types, data only, that A4 and A5 build on.
    (
        "crates/core/src/fleet/model.rs",
        "crates/core/src/fleet/mod.rs",
        "pub mod model;",
    ),
    (
        "crates/core/src/fleet/fleets.rs",
        "crates/core/src/fleet/mod.rs",
        "pub mod fleets;",
    ),
    (
        "crates/core/src/fleet/tickets.rs",
        "crates/core/src/fleet/mod.rs",
        "pub mod tickets;",
    ),
    (
        "crates/core/src/fleet/agents.rs",
        "crates/core/src/fleet/mod.rs",
        "pub mod agents;",
    ),
    // The GitHub adapter (A4, A5, spec 2's B3).
    (
        "crates/adapters/github/src/allowlist.rs",
        "crates/adapters/github/src/lib.rs",
        "pub mod allowlist;",
    ),
    (
        "crates/adapters/github/src/fleets.rs",
        "crates/adapters/github/src/lib.rs",
        "pub mod fleets;",
    ),
    (
        "crates/adapters/github/src/tickets.rs",
        "crates/adapters/github/src/lib.rs",
        "pub mod tickets;",
    ),
    (
        "crates/adapters/github/src/writes.rs",
        "crates/adapters/github/src/lib.rs",
        "pub mod writes;",
    ),
    // The two commands (A4, A5).
    (
        "crates/cli/src/fleets.rs",
        "crates/cli/src/lib.rs",
        "pub mod fleets;",
    ),
    (
        "crates/cli/src/fleet.rs",
        "crates/cli/src/lib.rs",
        "pub mod fleet;",
    ),
    // The tests (A4, A5, A6, B3).
    (
        "tests/fleet/a4_fleets.rs",
        "tests/fleet/main.rs",
        "mod a4_fleets;",
    ),
    (
        "tests/fleet/a5_fleet.rs",
        "tests/fleet/main.rs",
        "mod a5_fleet;",
    ),
    (
        "tests/fleet/a6_agents.rs",
        "tests/fleet/main.rs",
        "mod a6_agents;",
    ),
    (
        "tests/fleet/b3_writes.rs",
        "tests/fleet/main.rs",
        "mod b3_writes;",
    ),
];

#[test]
fn every_later_tickets_file_exists_and_is_declared_once() {
    let mut missing = Vec::new();
    for (file, declared_in, line) in SEAMS {
        if !root().join(file).is_file() {
            missing.push(format!("{file} does not exist"));
        }
        let Ok(text) = fs::read_to_string(root().join(declared_in)) else {
            missing.push(format!("{declared_in} does not exist"));
            continue;
        };
        let count = text.lines().filter(|l| l.trim() == *line).count();
        if count != 1 {
            missing.push(format!("{declared_in} has {count} lines `{line}`, not 1"));
        }
    }
    assert!(
        missing.is_empty(),
        "the seams are not all there:\n{}",
        missing.join("\n")
    );
}

fn metadata() -> Value {
    let output = Command::new(env!("CARGO"))
        .args(["metadata", "--format-version", "1", "--locked", "--offline"])
        .args([
            "--filter-platform",
            String::from_utf8(
                Command::new("rustc")
                    .args(["--print", "host-tuple"])
                    .output()
                    .expect("rustc")
                    .stdout,
            )
            .expect("host")
            .trim(),
        ])
        .current_dir(root())
        .output()
        .expect("run cargo metadata");
    assert!(
        output.status.success(),
        "cargo metadata failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).expect("metadata is JSON")
}

/// Each workspace package's name and its manifest's path, from the root.
fn members(meta: &Value) -> BTreeMap<String, String> {
    let ids: BTreeSet<&str> = meta["workspace_members"]
        .as_array()
        .expect("workspace members")
        .iter()
        .map(|m| m.as_str().expect("member id"))
        .collect();
    let root = root().canonicalize().expect("root");
    meta["packages"]
        .as_array()
        .expect("packages")
        .iter()
        .filter(|p| ids.contains(p["id"].as_str().expect("id")))
        .map(|p| {
            let manifest = Path::new(p["manifest_path"].as_str().expect("manifest"));
            let relative = manifest.strip_prefix(&root).expect("inside the root");
            (
                p["name"].as_str().expect("name").to_owned(),
                relative.to_str().expect("UTF-8 path").to_owned(),
            )
        })
        .collect()
}

/// Package name to the names of its normal dependencies, resolved.
fn graph(meta: &Value) -> BTreeMap<String, BTreeSet<String>> {
    let names: BTreeMap<&str, &str> = meta["packages"]
        .as_array()
        .expect("packages")
        .iter()
        .map(|p| (p["id"].as_str().unwrap(), p["name"].as_str().unwrap()))
        .collect();
    meta["resolve"]["nodes"]
        .as_array()
        .expect("resolve nodes")
        .iter()
        .map(|node| {
            let deps = node["deps"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|d| {
                    d["dep_kinds"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .any(|k| k["kind"].is_null())
                })
                .map(|d| names[d["pkg"].as_str().unwrap()].to_owned())
                .collect();
            (names[node["id"].as_str().unwrap()].to_owned(), deps)
        })
        .collect()
}

fn reachable(graph: &BTreeMap<String, BTreeSet<String>>, from: &str) -> BTreeSet<String> {
    let mut seen = BTreeSet::new();
    let mut stack = vec![from.to_owned()];
    while let Some(next) = stack.pop() {
        for dep in graph.get(&next).into_iter().flatten() {
            if seen.insert(dep.clone()) {
                stack.push(dep.clone());
            }
        }
    }
    seen
}

#[test]
fn the_github_adapter_is_a_workspace_crate_beside_the_cloudroom_one() {
    let members = members(&metadata());
    assert_eq!(
        members.get(GITHUB).map(String::as_str),
        Some("crates/adapters/github/Cargo.toml"),
        "workspace members: {members:?}"
    );
}

#[test]
fn the_github_adapters_dependencies_point_inward() {
    let meta = metadata();
    let g = graph(&meta);
    assert!(
        g.contains_key(GITHUB),
        "{GITHUB} is not in the resolved graph"
    );
    let core = reachable(&g, CORE);
    assert!(
        !core.contains(GITHUB),
        "the core reaches {GITHUB}: {core:?}"
    );

    let github = reachable(&g, GITHUB);
    assert!(
        github.contains(CORE),
        "{GITHUB} implements the core's interfaces"
    );
    // Every other workspace crate is a client or another adapter.
    for (name, _) in members(&meta) {
        if name != CORE && name != GITHUB {
            assert!(
                !github.contains(&name),
                "{GITHUB} depends on {name}: {github:?}"
            );
        }
    }
}

#[test]
fn the_cli_depends_on_the_github_adapter_so_a4_and_a5_need_not_add_it() {
    let g = graph(&metadata());
    let cli = g
        .get("openwiz-cli")
        .expect("the CLI is in the resolved graph");
    assert!(
        cli.contains(GITHUB),
        "the CLI's direct dependencies: {cli:?}"
    );
}
