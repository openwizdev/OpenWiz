// Build identity without starting a process. Exported sources must supply it.
// #1148: self-contained, because tests build a copied CLI crate on its own.
use std::{
    env, fs,
    path::{Path, PathBuf},
};

// #1010: Cargo reruns the script on every build while a watched path is
// missing, so only paths that exist are watched.
fn watched(path: &Path) -> Option<String> {
    let text = fs::read_to_string(path).ok()?;
    println!("cargo:rerun-if-changed={}", path.display());
    Some(text)
}
// A loose ref, or else the nearest directory under `refs/` that holds where
// it would appear, so a ref written after this build still reruns it.
fn watched_ref(common: &Path, reference: &str) -> Option<String> {
    let path = common.join(reference);
    if let Some(text) = watched(&path) {
        return Some(text);
    }
    let refs = common.join("refs");
    let parent = path.ancestors().skip(1).find(|dir| dir.is_dir());
    if let Some(dir) = parent.filter(|dir| dir.starts_with(&refs)) {
        println!("cargo:rerun-if-changed={}", dir.display());
    }
    None
}
fn valid(commit: &str) -> bool {
    commit.len() == 40
        && commit
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn git_commit(root: &Path) -> Option<String> {
    let dot = root.join(".git");
    let dir = if dot.is_dir() {
        dot
    } else {
        let text = watched(&dot)?;
        root.join(text.trim().strip_prefix("gitdir: ")?)
    };
    let head = watched(&dir.join("HEAD"))?;
    let head = head.trim();
    if valid(head) {
        return Some(head.to_owned());
    }
    let reference = head.strip_prefix("ref: ")?;
    if !reference.starts_with("refs/") || reference.contains("..") {
        return None;
    }
    let common = watched(&dir.join("commondir"))
        .map(|v| dir.join(v.trim()))
        .unwrap_or(dir);
    if let Some(text) = watched_ref(&common, reference) {
        return Some(text.trim().to_owned()).filter(|v| valid(v));
    }
    watched(&common.join("packed-refs"))?
        .lines()
        .find_map(|line| {
            let (commit, name) = line.split_once(' ')?;
            (name == reference && valid(commit)).then(|| commit.to_owned())
        })
}
fn main() {
    println!("cargo:rerun-if-env-changed=OPENWIZ_SERVICE_BUILD");
    let root = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap()).join("../..");
    let commit = match env::var("OPENWIZ_SERVICE_BUILD") {
        Ok(value) if valid(&value) => Some(value),
        Ok(_) => panic!("OPENWIZ_SERVICE_BUILD must be a full lowercase commit"),
        Err(_) => git_commit(&root),
    };
    // A detached source export can still compile help/status. Starting it
    // requires the builder to have supplied the real commit; never guess one.
    println!(
        "cargo:rustc-env=OPENWIZ_SERVICE_BUILD={}",
        commit.as_deref().unwrap_or("unavailable")
    );
    // #1148: the canonical product identity (contracts/release-candidate.v1.md),
    // always set here so a caller's environment never supplies it; empty
    // when the source is unknown, which the identity query refuses.
    let product = match env::var("CARGO_PKG_NAME").unwrap().as_str() {
        "openwiz-cli" => "cli",
        other => panic!("no product identity for {other}"),
    };
    let identity = commit.as_deref().map_or_else(String::new, |source| {
        format!(
            "{{\"product\":\"{product}\",\"schema\":\"openwiz.product.v1\",\"source\":\"{source}\",\"target\":\"{}\",\"version\":\"{}\"}}",
            env::var("TARGET").unwrap(),
            env::var("CARGO_PKG_VERSION").unwrap()
        )
    });
    println!("cargo:rustc-env=OPENWIZ_PRODUCT_IDENTITY={identity}");
}
