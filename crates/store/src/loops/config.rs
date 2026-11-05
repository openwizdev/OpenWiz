//! Switch context from private install configuration; no discovery process.
use super::{Context, Trust, document, paths, valid_actor};
use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
    sync::Arc,
};

fn read(state: &Path) -> Result<Value, String> {
    paths::inspect(state)?;
    let config = document::service_config(
        &fs::read_to_string(state.join("service/config.json"))
            .map_err(|_| "cannot read service configuration")?,
    )?;
    if config["operator"]
        .as_str()
        .is_none_or(|actor| !valid_actor(actor))
    {
        return Err(
            "service operator must be explicitly configured, nonblank and NUL-free".to_owned(),
        );
    }
    Ok(config)
}
fn repository(config: &Value) -> String {
    format!(
        "{}/{}",
        config["repository"]["owner"].as_str().unwrap(),
        config["repository"]["name"].as_str().unwrap()
    )
}
struct Installed {
    state: PathBuf,
    repository: String,
    project: String,
}
impl Trust for Installed {
    fn verify(&self, checkout: &Path, expected_repository: &str, project: &str) -> bool {
        read(&self.state).is_ok_and(|config| {
            repository(&config) == expected_repository
                && config["project"] == project
                && origin_matches(checkout, expected_repository)
        })
    }
    fn actor(&self) -> Option<String> {
        let config = read(&self.state).ok()?;
        (repository(&config) == self.repository && config["project"] == self.project)
            .then(|| config["operator"].as_str().unwrap().to_owned())
    }
}
/// The checkout is supplied locally by the caller (the working directory),
/// never by a switch request. Unknown Git layouts/origins refuse the write.
pub fn installed(checkout: &Path, state: &Path) -> Result<Context, String> {
    let config = read(state)?;
    Ok(Context {
        checkout: checkout.to_owned(),
        state: state.to_owned(),
        repository: repository(&config),
        project: config["project"].as_str().unwrap().to_owned(),
        trust: Some(Arc::new(Installed {
            state: state.to_owned(),
            repository: repository(&config),
            project: config["project"].as_str().unwrap().to_owned(),
        })),
    })
}
fn origin_matches(checkout: &Path, repository: &str) -> bool {
    let git = checkout.join(".git");
    if !fs::symlink_metadata(&git).is_ok_and(|meta| meta.is_dir() && !meta.file_type().is_symlink())
    {
        return false;
    }
    let path = git.join("config");
    if !fs::symlink_metadata(&path)
        .is_ok_and(|meta| meta.is_file() && !meta.file_type().is_symlink())
    {
        return false;
    }
    let Ok(config) = fs::read_to_string(path) else {
        return false;
    };
    let mut origin = false;
    let mut sections = 0;
    let mut urls = vec![];
    for line in config.lines().map(str::trim) {
        if line.is_empty() || line.starts_with(['#', ';']) {
            continue;
        }
        if line.starts_with('[') {
            let lower = line.to_ascii_lowercase();
            // A config construct that changes the origin's meaning is refused:
            // an include, or a `[url ...]` section, can rewrite the fetch URL.
            if !line.ends_with(']') || lower.starts_with("[include") || lower.starts_with("[url") {
                return false;
            }
            origin = false;
            if lower.starts_with("[remote") {
                // Section/key names are case-insensitive; Git remote names
                // are case-sensitive. Refuse unsupported alternate syntax.
                if !lower.starts_with("[remote \"") || !line.ends_with("\"]") {
                    return false;
                }
                let name = &line[9..line.len() - 2];
                if name.is_empty() || name.contains(['"', '\\']) {
                    return false;
                }
                origin = name == "origin";
                if origin {
                    sections += 1;
                }
            }
        } else {
            let Some((key, value)) = line.split_once('=') else {
                // A key/value line is required inside a remote section; a
                // section-less bare word is ignored as before.
                if origin {
                    return false;
                }
                continue;
            };
            let key = key.trim();
            // Rewrite keys change what a remote URL means, wherever they sit.
            if key.eq_ignore_ascii_case("insteadOf") || key.eq_ignore_ascii_case("pushInsteadOf") {
                return false;
            }
            if origin && key.eq_ignore_ascii_case("url") {
                urls.push(value.trim());
            }
        }
    }
    let [url] = urls.as_slice() else {
        return false;
    };
    sections == 1
        && [
            "https://github.com/",
            "ssh://git@github.com/",
            "git@github.com:",
        ]
        .iter()
        .any(|prefix| {
            url.strip_prefix(prefix).is_some_and(|path| {
                path.strip_suffix(".git")
                    .unwrap_or(path)
                    .eq_ignore_ascii_case(repository)
            })
        })
}
