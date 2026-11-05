//! Operator comes from install config, not a definition or HTTP caller.
use super::l6_switches::{Fixture, git};
use serde_json::{Value, json};
use std::fs;
pub(super) fn config(f: &Fixture) -> Value {
    let mut config = include_str!("../../contracts/service.v1.md")
        .lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .find(|v| v["schema"] == "openwiz.service-config.v1")
        .unwrap();
    config["project"] = json!(f.context.project);
    config["repository"] = json!({"owner":"synthetic-owner","name":"synthetic-repo"});
    config["operator"] = json!("synthetic-installed-operator");
    config
}
#[test]
fn installed_operator_and_project_are_read_from_private_config_and_rechecked() {
    let f = Fixture::new();
    git(
        &f.context.checkout,
        &[
            "remote",
            "add",
            "origin",
            "https://github.com/synthetic-owner/synthetic-repo.git",
        ],
    );
    let path = f.context.state.join("service/config.json");
    let mut configured = config(&f);
    fs::write(&path, configured.to_string()).unwrap();
    let context = openwiz_store::loops::config::installed(&f.context.checkout, &f.context.state)
        .expect("configured operator must be usable");
    let off = context.switch("loop-syn-reminder", false, 1000).unwrap();
    assert_eq!(off["actor"], "synthetic-installed-operator");
    let before = f.saved();
    configured["operator"] = json!(null);
    fs::write(&path, configured.to_string()).unwrap();
    assert!(context.switch("loop-syn-reminder", true, 2000).is_err());
    assert_eq!(f.saved(), before);
}

#[test]
fn missing_invalid_duplicate_or_foreign_install_context_never_switches() {
    let f = Fixture::new();
    let path = f.context.state.join("service/config.json");
    git(
        &f.context.checkout,
        &[
            "remote",
            "add",
            "origin",
            "https://github.com/synthetic-owner/synthetic-repo.git",
        ],
    );
    for actor in [
        json!(null),
        json!(false),
        json!(""),
        json!(" "),
        json!("\0"),
        json!({"name":"caller"}),
    ] {
        let mut value = config(&f);
        value["operator"] = actor;
        fs::write(&path, value.to_string()).unwrap();
        assert!(
            openwiz_store::loops::config::installed(&f.context.checkout, &f.context.state).is_err()
        );
    }
    let mut value = config(&f);
    value.as_object_mut().unwrap().remove("operator");
    fs::write(&path, value.to_string()).unwrap();
    assert!(
        openwiz_store::loops::config::installed(&f.context.checkout, &f.context.state).is_err()
    );
    let duplicate = config(&f)
        .to_string()
        .replacen("{", "{\"operator\":\"synthetic-other\",", 1);
    fs::write(&path, duplicate).unwrap();
    assert!(
        openwiz_store::loops::config::installed(&f.context.checkout, &f.context.state).is_err()
    );
    let float = config(&f)
        .to_string()
        .replace("\"every_s\":300", "\"every_s\":300.0");
    assert_ne!(float, config(&f).to_string());
    fs::write(&path, float).unwrap();
    assert!(
        openwiz_store::loops::config::installed(&f.context.checkout, &f.context.state).is_err()
    );
    for (key, other) in [
        ("project", json!("prj_syn_foreign")),
        (
            "repository",
            json!({"owner":"synthetic-owner","name":"other-repo"}),
        ),
    ] {
        let mut value = config(&f);
        value[key] = other;
        fs::write(&path, value.to_string()).unwrap();
        let context =
            openwiz_store::loops::config::installed(&f.context.checkout, &f.context.state).unwrap();
        assert!(context.switch("loop-syn-reminder", false, 1000).is_err());
    }
    fs::write(&path, config(&f).to_string()).unwrap();
    git(
        &f.context.checkout,
        &[
            "remote",
            "set-url",
            "origin",
            "https://github.com/synthetic-owner/foreign-repo.git",
        ],
    );
    let context =
        openwiz_store::loops::config::installed(&f.context.checkout, &f.context.state).unwrap();
    assert!(context.switch("loop-syn-reminder", false, 1000).is_err());
    assert!(!f.context.state.join("service/loops").exists());
}

#[test]
fn installed_origin_requires_one_exact_existing_github_remote() {
    let f = Fixture::new();
    fs::write(
        f.context.state.join("service/config.json"),
        config(&f).to_string(),
    )
    .unwrap();
    git(
        &f.context.checkout,
        &[
            "remote",
            "add",
            "origin",
            "https://github.com/synthetic-owner/synthetic-repo.git",
        ],
    );
    let context =
        openwiz_store::loops::config::installed(&f.context.checkout, &f.context.state).unwrap();
    for (n, url) in [
        "https://github.com/synthetic-owner/synthetic-repo.git",
        "ssh://git@github.com/synthetic-owner/synthetic-repo",
        "git@github.com:synthetic-owner/synthetic-repo.git",
    ]
    .iter()
    .enumerate()
    {
        git(&f.context.checkout, &["remote", "set-url", "origin", url]);
        assert!(
            context
                .switch("loop-syn-reminder", false, 1000 + n as u64)
                .is_ok()
        );
    }
    let before = f.saved();
    for url in [
        "https://github.com/synthetic-owner/synthetic-repo-extra.git",
        "https://github.com/synthetic-owner/synthetic-repo.git/",
        "https://github.com.evil.invalid/synthetic-owner/synthetic-repo.git",
        "file:///synthetic-owner/synthetic-repo",
    ] {
        git(&f.context.checkout, &["remote", "set-url", "origin", url]);
        assert!(context.switch("loop-syn-reminder", true, 2000).is_err());
        assert_eq!(f.saved(), before);
    }
    git(
        &f.context.checkout,
        &[
            "remote",
            "set-url",
            "origin",
            "https://github.com/synthetic-owner/synthetic-repo.git",
        ],
    );
    git(
        &f.context.checkout,
        &[
            "config",
            "--add",
            "remote.origin.url",
            "https://github.com/synthetic-owner/foreign.git",
        ],
    );
    assert!(context.switch("loop-syn-reminder", true, 2000).is_err());
    assert_eq!(f.saved(), before);
    git(
        &f.context.checkout,
        &[
            "config",
            "--unset-all",
            "remote.origin.url",
            "https://github.com/synthetic-owner/foreign.git",
        ],
    );
    let path = f.context.checkout.join(".git/config");
    let clean = fs::read_to_string(&path).unwrap();
    assert!(
        !clean.contains("foreign.git"),
        "fixture cleanup must remove every added origin url"
    );
    // A literal GitHub origin whose real fetch URL an insteadOf rewrite sends
    // to another host still reads as GitHub to a guard that skips [url] sections.
    for rewrite in [
        "[url \"https://foreign.example.invalid/other/\"]\n\tinsteadOf = https://github.com/\n",
        "[URL \"https://foreign.example.invalid/other/\"]\n\tpushInsteadOf = https://github.com/\n",
        "[url \"https://foreign.example.invalid/other/\"]\n",
        "insteadOf = https://github.com/\n",
        "pushInsteadOf = https://github.com/\n",
    ] {
        fs::write(&path, format!("{clean}{rewrite}")).unwrap();
        assert!(
            context.switch("loop-syn-reminder", true, 2000).is_err(),
            "a config construct that changes the origin's meaning must refuse: {rewrite:?}"
        );
        assert_eq!(f.saved(), before);
    }
}

#[test]
fn real_cli_uses_install_operator_and_refuses_unconfigured_or_caller_identity() {
    use std::process::Command;
    let f = Fixture::new();
    git(
        &f.context.checkout,
        &[
            "remote",
            "add",
            "origin",
            "https://github.com/synthetic-owner/synthetic-repo.git",
        ],
    );
    let path = f.context.state.join("service/config.json");
    let mut configured = config(&f);
    fs::write(&path, configured.to_string()).unwrap();
    let binary = std::env::current_exe()
        .unwrap()
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("openwiz");
    assert!(
        binary.exists(),
        "build the changed CLI with cargo build -p openwiz-cli --bin openwiz before this fixture test"
    );
    let run = |args: &[&str]| {
        Command::new(&binary)
            .current_dir(&f.context.checkout)
            .env("OPENWIZ_STATE_DIR", &f.context.state)
            .args(args)
            .output()
            .unwrap()
    };
    let off = run(&["loop", "off", "loop-syn-reminder", "--json"]);
    assert!(
        off.status.success(),
        "{}",
        String::from_utf8_lossy(&off.stderr)
    );
    let event: Value = serde_json::from_slice(&off.stdout).unwrap();
    assert_eq!(event["actor"], "synthetic-installed-operator");
    let before = f.saved();
    let claimed = run(&["loop", "on", "loop-syn-reminder", "--operator", "caller"]);
    assert_eq!(claimed.status.code(), Some(2));
    configured.as_object_mut().unwrap().remove("operator");
    fs::write(path, configured.to_string()).unwrap();
    assert_eq!(
        run(&["loop", "on", "loop-syn-reminder"]).status.code(),
        Some(1)
    );
    assert_eq!(f.saved(), before);
}

#[test]
fn unsupported_or_ambiguous_origin_headers_are_refused() {
    let f = Fixture::new();
    git(
        &f.context.checkout,
        &[
            "remote",
            "add",
            "origin",
            "https://github.com/synthetic-owner/synthetic-repo.git",
        ],
    );
    fs::write(
        f.context.state.join("service/config.json"),
        config(&f).to_string(),
    )
    .unwrap();
    let context =
        openwiz_store::loops::config::installed(&f.context.checkout, &f.context.state).unwrap();
    context.switch("loop-syn-reminder", false, 1000).unwrap();
    let before = f.saved();
    let path = f.context.checkout.join(".git/config");
    let original = fs::read_to_string(&path).unwrap();
    for invalid in [
        original.replace("[remote \"origin\"]", "[remote \"ORIGIN\"]"),
        format!(
            "{original}\n[remote \"origin\" ]\nurl = https://github.com/synthetic-owner/foreign.git\n"
        ),
        format!(
            "{original}\n[remote.origin]\nurl = https://github.com/synthetic-owner/foreign.git\n"
        ),
    ] {
        fs::write(&path, invalid).unwrap();
        assert!(
            context.switch("loop-syn-reminder", true, 2000).is_err(),
            "unknown or ambiguous origin syntax must refuse"
        );
        assert_eq!(f.saved(), before);
    }
}
