//! Synthetic source/store boundary fixtures for CP2. No external account access.
use super::{ROOT, Sandbox, fixture_cli, schema};
use serde_json::{Value, json};
use std::{
    fs,
    path::Path,
    process::{Command, Output, Stdio},
};

struct Fixture(Sandbox);
impl Fixture {
    fn new(scenario: &str) -> Self {
        let fixture = Self(Sandbox::new());
        let bin = fixture.0.0.join("bin");
        for (name, program) in [
            ("room-cli", env!("CARGO_BIN_EXE_fake-room-cli")),
            ("gh", env!("CARGO_BIN_EXE_fake-gh")),
        ] {
            fs::remove_file(bin.join(name)).unwrap();
            std::os::unix::fs::symlink(program, bin.join(name)).unwrap();
        }
        fs::write(
            bin.join("fake-room-cli.scenario"),
            Path::new(ROOT)
                .join(format!(
                    "tests/fixtures/room-cli-0.43.1/{scenario}/scenario.json"
                ))
                .to_str()
                .unwrap(),
        )
        .unwrap();
        fixture
    }
    fn room(&self, parent: &str, responses: Value) {
        let path = self.0.0.join("scenario.json");
        fs::write(&path, json!({"extends": Path::new(ROOT).join(format!("tests/fixtures/room-cli-0.43.1/{parent}")).to_str().unwrap(), "responses": responses}).to_string()).unwrap();
        fs::write(
            self.0.0.join("bin/fake-room-cli.scenario"),
            path.to_str().unwrap(),
        )
        .unwrap();
    }
    fn gh(&self, responses: Value) {
        let path = self.0.0.join("gh-scenario.json");
        fs::write(&path, json!({"synthetic_assumptions":["CP2 synthetic GitHub responses"], "responses":responses}).to_string()).unwrap();
        fs::write(self.0.0.join("fake-gh.scenario"), path.to_str().unwrap()).unwrap();
    }
    fn command(&self, args: &[&str]) -> Command {
        let mut cmd = Command::new(fixture_cli());
        cmd.args(args)
            .env_clear()
            .env(
                "PATH",
                format!(
                    "{}:{}",
                    self.0.0.join("bin").display(),
                    std::env::var("PATH").unwrap()
                ),
            )
            .env("HOME", self.0.0.join("home"))
            .env("OPENWIZ_STATE_DIR", self.0.0.join("state"))
            .env("OPENWIZ_FIXTURE_PROGRAM", self.0.0.join("bin/room-cli"))
            .current_dir(&self.0.0)
            .stdin(Stdio::null());
        cmd
    }
    fn run(&self, args: &[&str]) -> Output {
        self.command(args).output().unwrap()
    }
    fn calls(&self) -> Vec<Value> {
        fs::read_to_string(self.0.0.join("bin/invocations.log"))
            .unwrap_or_default()
            .lines()
            .map(|s| serde_json::from_str(s).unwrap())
            .collect()
    }
    fn count(&self, name: &str) -> u64 {
        fs::read_to_string(self.0.0.join(format!("bin/{name}-calls.count")))
            .unwrap_or_else(|_| "0".into())
            .trim()
            .parse()
            .unwrap()
    }
}

fn report(out: &Output, code: i32, file: &str, def: &str, id: &str) -> Value {
    assert_eq!(
        out.status.code(),
        Some(code),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(out.stdout.ends_with(b"\n"));
    let doc: Value = serde_json::from_slice(&out.stdout).expect("one complete JSON document");
    assert_eq!(doc["schema"], id);
    let mut contract: Value = serde_json::from_str(
        &fs::read_to_string(Path::new(ROOT).join(format!("contracts/{file}.v1.schema.json")))
            .unwrap(),
    )
    .unwrap();
    contract["$ref"] = json!(format!("#/$defs/{def}"));
    let errors = if matches!(file, "fleet" | "fleet-tick") {
        fleet_schema::validate(&contract, &doc)
    } else {
        schema::validate(&contract, &doc)
    };
    assert_eq!(errors, Vec::<String>::new(), "{doc}");
    doc
}

fn empty_github() -> Value {
    json!([
        {"argv":["repo","view","--json","defaultBranchRef,nameWithOwner,url"], "stdout":"{\"defaultBranchRef\":{\"name\":\"main\"},\"nameWithOwner\":\"synthetic/example\",\"url\":\"https://example.invalid/synthetic/example\"}"},
        {"argv":["issue","list","--state","all","--limit","1000","--json","blockedBy,body,id,labels,milestone,number,state,subIssues,title"],"stdout":"[]"},
        {"argv":["pr","list","--state","all","--limit","1000","--json","baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state,title"],"stdout":"[]"}
    ])
}

#[test]
fn cp2_due_has_a_json_empty_result_without_room_or_state() {
    let f = Fixture::new("normal");
    f.gh(empty_github());
    let doc = report(
        &f.run(&["fleet", "due", "--github-only", "--json"]),
        0,
        "cli",
        "fleet_due",
        "openwiz.fleet-due.v1",
    );
    assert_eq!(doc["candidates"], json!([]));
    assert!(f.calls().is_empty());
    assert!(!f.0.0.join("state").exists());
    assert!(f.run(&["fleet", "due", "--github-only"]).stdout.is_empty());
    let gh_calls = fs::read_to_string(f.0.0.join("gh-invocations.log")).unwrap();
    assert_eq!(gh_calls.lines().count(), 6);
}

#[test]
fn cp2_inventory_success_partial_and_failure_keep_their_meaning() {
    for (scenario, args, code, kind) in [
        ("normal", vec!["ls", "--json"], 0, "complete"),
        (
            "normal",
            vec!["show", "thr_syn_0001", "--json"],
            0,
            "complete",
        ),
        ("project-list-error", vec!["ls", "--json"], 0, "partial"),
        ("show-error", vec!["ls", "-l", "--json"], 0, "partial"),
    ] {
        let f = Fixture::new(scenario);
        let doc = report(
            &f.run(&args),
            code,
            "inventory",
            "envelope",
            "openwiz.inventory.v1",
        );
        assert_eq!(doc["coverage"]["state"], kind);
        let text_args: Vec<_> = args.into_iter().filter(|s| *s != "--json").collect();
        let text = f.run(&text_args);
        assert_eq!(text.status.code(), Some(code));
        assert!(String::from_utf8_lossy(&text.stdout).contains(kind));
        assert!(!f.0.0.join("state").exists());
    }
    for (args, code, kind) in [
        (vec!["ls", "--json"], 1, "read_failed"),
        (vec!["show", "thr_syn_0001", "--json"], 1, "read_failed"),
        (vec!["show", "thr_syn_9999", "--json"], 3, "not_found"),
    ] {
        let f = Fixture::new("normal");
        f.room("normal", json!([
            {"argv":["thread","list","--json"],"exit":1,"stderr":"SYNTHETIC_SECRET_DO_NOT_PRINT"},
            {"argv":["thread","show","thr_syn_0001","--json"],"exit":1,"stderr":"SYNTHETIC_SECRET_DO_NOT_PRINT"}
        ]));
        let doc = report(&f.run(&args), code, "cli", "error", "openwiz.cli-error.v1");
        assert_eq!(doc["error"]["kind"], kind);
        assert!(!doc.to_string().contains("SYNTHETIC_SECRET_DO_NOT_PRINT"));
        assert!(!f.0.0.join("state").exists());
    }
}

#[allow(dead_code)]
#[path = "../fleet/b5_fake.rs"]
mod fleet_fixture;
#[path = "../fleet/schema.rs"]
mod fleet_schema;

#[test]
fn cp2_due_candidates_and_tick_reports_follow_the_recorded_world() {
    let w = fleet_fixture::World::new("cp2-candidates");
    let text = w.run(&["fleet", "due", "--github-only"]);
    assert!(
        text.status.success(),
        "{}",
        String::from_utf8_lossy(&text.stderr)
    );
    assert_eq!(
        String::from_utf8(text.stdout).unwrap(),
        "fleet #9: candidate #10\n"
    );
    let doc = report(
        &w.run(&["fleet", "due", "--github-only", "--json"]),
        0,
        "cli",
        "fleet_due",
        "openwiz.fleet-due.v1",
    );
    assert_eq!(doc["candidates"], json!([{"spec":9,"ticket":10}]));
    assert!(w.calls().iter().all(|(tool, _)| tool == "gh"));
    assert!(w.writes().is_empty());
    assert!(!w.dir.join("state").exists());
    let doc = report(
        &w.run(&["fleet", "tick", "--dry-run", "--json"]),
        0,
        "fleet-tick",
        "envelope",
        "openwiz.fleet-tick.v1",
    );
    assert_eq!(doc["actions"].as_array().unwrap().len(), 1);
    assert_eq!(doc["actions"][0]["rule"], "frontier");
    // The plan reads only: the executing tick that acted on it was retired (#800).
    assert!(w.writes().is_empty());
}

#[test]
fn cp2_fleet_source_failures_and_partial_fleets_preserve_reports() {
    for args in [
        vec!["fleet", "9", "--json"],
        vec!["fleet", "tick", "--dry-run", "--json"],
        vec!["fleet", "due", "--github-only", "--json"],
    ] {
        let f = Fixture::new("normal");
        f.gh(json!([]));
        report(&f.run(&args), 1, "cli", "error", "openwiz.cli-error.v1");
        assert_eq!(f.count("tell"), 0);
        assert_eq!(f.count("spawn"), 0);
        assert!(!f.0.0.join("state").exists());
    }
    for scenario in ["complete", "issue-list-fails", "checks-fail"] {
        let f = Fixture::new("normal");
        fs::write(
            f.0.0.join("fake-gh.scenario"),
            Path::new(ROOT)
                .join(format!(
                    "tests/fixtures/github/fleets/{scenario}/scenario.json"
                ))
                .to_str()
                .unwrap(),
        )
        .unwrap();
        let doc = report(
            &f.run(&["fleets", "--json"]),
            0,
            "fleet",
            "envelope",
            "openwiz.fleet.v1",
        );
        assert!(doc["coverage"].is_object());
        assert!(f.calls().is_empty());
    }
    let f = Fixture::new("normal");
    let issue = json!({"blockedBy":{"nodes":[],"totalCount":0},"body":"Synthetic spec","closedByPullRequestsReferences":[],"comments":[],"labels":[],"milestone":null,"state":"OPEN","subIssues":{"nodes":[],"totalCount":0},"title":"Synthetic empty fleet"});
    f.gh(json!([
        {"argv":["--version"],"stdout":"gh version 2.100.0\n"},
        {"argv":["repo","view","--json","nameWithOwner,url"],"stdout":"{\"nameWithOwner\":\"synthetic-owner/synthetic-repo\",\"url\":\"https://example.invalid/synthetic/repo\"}"},
        {"argv":["issue","view","9","--json","blockedBy,body,closedByPullRequestsReferences,comments,labels,milestone,state,subIssues,title"],"stdout":issue.to_string()}
    ]));
    report(
        &f.run(&["fleet", "9", "--json"]),
        0,
        "fleet",
        "envelope",
        "openwiz.fleet.v1",
    );
}

#[test]
fn cp2_local_switch_events_keep_their_exact_unwrapped_shape() {
    use std::os::unix::fs::PermissionsExt;
    let f = Fixture::new("normal");
    let checkout = f.0.0.join("checkout");
    super::dirs::private_dir_all(checkout.join("loops")).unwrap();
    let git = |args: &[&str]| {
        let out = Command::new("git")
            .arg("-C")
            .arg(&checkout)
            .args(args)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
    };
    git(&["init", "-q", "--initial-branch=main"]);
    git(&["config", "user.name", "Synthetic Builder"]);
    git(&["config", "user.email", "synthetic@example.invalid"]);
    git(&[
        "remote",
        "add",
        "origin",
        "https://github.com/synthetic-owner/synthetic-repo.git",
    ]);
    fs::write(
        checkout.join("loops/example.json"),
        include_str!("../../loops/example.json"),
    )
    .unwrap();
    git(&["add", "loops"]);
    git(&["commit", "-qm", "Synthetic definition"]);
    git(&["update-ref", "refs/remotes/origin/main", "HEAD"]);
    git(&[
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        "refs/remotes/origin/main",
    ]);
    let mut config: Value = include_str!("../../contracts/service.v1.md")
        .lines()
        .filter_map(|l| serde_json::from_str::<Value>(l).ok())
        .find(|v| v["schema"] == "openwiz.service-config.v1")
        .unwrap();
    config["repository"] = json!({"owner":"synthetic-owner","name":"synthetic-repo"});
    config["project"] = json!("prj_syn_example");
    config["operator"] = json!("synthetic-installed-operator");
    let state = f.0.0.join("state/service");
    super::dirs::private_dir_all(&state).unwrap();
    fs::write(state.join("config.json"), config.to_string()).unwrap();
    fs::set_permissions(state.join("config.json"), fs::Permissions::from_mode(0o600)).unwrap();
    for (command, enabled) in [("off", false), ("on", true)] {
        let out = f
            .command(&["loop", command, "loop-syn-reminder", "--json"])
            .current_dir(&checkout)
            .output()
            .unwrap();
        assert_eq!(
            out.status.code(),
            Some(0),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        let doc: Value = serde_json::from_slice(&out.stdout).unwrap();
        let mut contract: Value =
            serde_json::from_str(include_str!("../../contracts/cli.v1.schema.json")).unwrap();
        contract["$ref"] = json!("#/$defs/loop_switch");
        assert_eq!(schema::validate(&contract, &doc), Vec::<String>::new());
        assert_eq!(doc["enabled"], enabled);
        assert_eq!(doc["actor"], "synthetic-installed-operator");
    }
    let out = f
        .command(&["loop", "off", "missing-synthetic", "--json"])
        .current_dir(&checkout)
        .output()
        .unwrap();
    report(&out, 1, "cli", "error", "openwiz.cli-error.v1");
    assert!(f.calls().is_empty());
}

#[test]
fn cp2_legacy_repeatable_json_switches_remain_idempotent() {
    let f = Fixture::new("send");
    report(
        &f.run(&["ls", "--json", "--json"]),
        0,
        "inventory",
        "envelope",
        "openwiz.inventory.v1",
    );
}
