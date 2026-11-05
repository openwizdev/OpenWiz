//! Synthetic source/store boundary fixtures for CP2. No external account access.
use super::{ROOT, Sandbox, fixture_cli, schema};
use serde_json::{Value, json};
use std::{
    fs,
    io::Write,
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
    fn stdin(&self, args: &[&str], input: &[u8]) -> Output {
        let mut child = self
            .command(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        child.stdin.take().unwrap().write_all(input).unwrap();
        child.wait_with_output().unwrap()
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
    // New-thread/attachment schemas use the existing pattern checker.
    let errors = if matches!(file, "new-thread" | "attachment" | "messaging") {
        pattern::validate(&contract, &doc)
    } else if matches!(file, "fleet" | "fleet-tick") {
        fleet_schema::validate(&contract, &doc)
    } else {
        schema::validate(&contract, &doc)
    };
    assert_eq!(errors, Vec::<String>::new(), "{doc}");
    doc
}
#[allow(dead_code)]
#[path = "../new-thread/pattern.rs"]
mod pattern;

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

#[test]
fn cp2_stdin_and_store_errors_emit_documents_before_any_source_call() {
    for name in ["send", "new"] {
        for bytes in [b"".as_slice(), b" \n", &[0xff], b"synthetic\0text"] {
            let f = Fixture::new("send");
            let args = if name == "send" {
                vec!["send", "thr_syn_0001", "--op-id", "op-input", "--json"]
            } else {
                vec![
                    "new",
                    "--project-id",
                    "prj_syn_0001",
                    "--harness",
                    "codex",
                    "--model",
                    "syn-codex-model-01",
                    "--effort",
                    "high",
                    "--op-id",
                    "op-input",
                    "--json",
                    "--yes",
                ]
            };
            let doc = report(
                &f.stdin(&args, bytes),
                2,
                "cli",
                "error",
                "openwiz.cli-error.v1",
            );
            assert_eq!(doc["command"], name);
            assert!(f.calls().is_empty());
            assert!(!f.0.0.join("state").exists());
        }
    }
    for args in [
        vec![
            "send",
            "thr_syn_0001",
            "--op-id",
            "op-store",
            "--json",
            "--",
            "Synthetic",
        ],
        vec![
            "send",
            "thr_syn_0001",
            "--check",
            "--op-id",
            "op-store",
            "--json",
        ],
        vec!["new", "--status", "op-store", "--json"],
        vec![
            "new",
            "--project-id",
            "prj_syn_0001",
            "--harness",
            "codex",
            "--model",
            "syn-codex-model-01",
            "--effort",
            "high",
            "--op-id",
            "op-store",
            "--yes",
            "--json",
            "--",
            "Synthetic",
        ],
    ] {
        let f = Fixture::new("send");
        fs::write(
            f.0.0.join("state"),
            "synthetic regular file, not a directory",
        )
        .unwrap();
        let doc = report(&f.run(&args), 10, "cli", "error", "openwiz.cli-error.v1");
        assert_eq!(doc["error"]["kind"], "store_unavailable");
        assert!(f.calls().is_empty());
    }
}

#[test]
fn cp2_send_reports_cover_outcomes_replay_conflict_lookup_and_preview() {
    for (target, code, status) in [
        ("thr_syn_0001", 0, "accepted"),
        ("thr_syn_0006", 0, "queued"),
        ("thr_syn_0011", 5, "failed"),
        ("thr_syn_9999", 3, "failed"),
    ] {
        let f = Fixture::new("send");
        let args = [
            "send",
            target,
            "--op-id",
            "op-send",
            "--json",
            "--",
            "Synthetic",
        ];
        let doc = report(
            &f.run(&args),
            code,
            "messaging",
            "report",
            "openwiz.messaging.v1",
        );
        assert_eq!(doc["status"], status);
        assert_eq!(f.count("tell"), u64::from(code == 0));
        let before = f.count("tell");
        let replay = report(
            &f.run(&args),
            code,
            "messaging",
            "report",
            "openwiz.messaging.v1",
        );
        assert_eq!(replay["status"], status);
        assert_eq!(f.count("tell"), before);
        let lookup = report(
            &f.run(&["send", target, "--op-id", "op-send", "--check", "--json"]),
            code,
            "messaging",
            "lookup",
            "openwiz.send-lookup.v1",
        );
        assert_eq!(lookup["result"]["report"]["status"], status);
        report(
            &f.run(&[
                "send",
                target,
                "--op-id",
                "op-send",
                "--json",
                "--",
                "Changed synthetic",
            ]),
            8,
            "messaging",
            "report",
            "openwiz.messaging.v1",
        );
        assert_eq!(f.count("tell"), before);
    }
    let f = Fixture::new("send");
    for (target, code) in [("thr_syn_0001", 0), ("thr_syn_9999", 3)] {
        report(
            &f.run(&["send", target, "--preview", "--json"]),
            code,
            "messaging",
            "preview",
            "openwiz.send-preview.v1",
        );
    }
    report(
        &f.run(&[
            "send",
            "thr_syn_0001",
            "--check",
            "--op-id",
            "op-absent",
            "--json",
        ]),
        11,
        "messaging",
        "lookup",
        "openwiz.send-lookup.v1",
    );
    assert_eq!(f.count("tell"), 0);
    assert!(!f.0.0.join("state").exists());
}

#[test]
fn cp2_uncertain_send_is_not_retried_and_duplicate_stays_nonzero() {
    let f = Fixture::new("send");
    f.room("send", json!([{"argv":["thread","tell","thr_syn_0001","--mode","queue","--json","--"],"any_text":true,"abort":true}]));
    let args = [
        "send",
        "thr_syn_0001",
        "--op-id",
        "op-uncertain",
        "--json",
        "--",
        "Synthetic",
    ];
    for _ in 0..2 {
        let doc = report(
            &f.run(&args),
            6,
            "messaging",
            "report",
            "openwiz.messaging.v1",
        );
        assert_eq!(doc["status"], "uncertain");
    }
    report(
        &f.run(&[
            "send",
            "thr_syn_0001",
            "--op-id",
            "op-another",
            "--json",
            "--",
            "Synthetic",
        ]),
        9,
        "messaging",
        "report",
        "openwiz.messaging.v1",
    );
    assert_eq!(f.count("tell"), 1);
}

fn new_responses() -> Value {
    let fixture = |name: &str| {
        Path::new(ROOT)
            .join("tests/fixtures/room-cli-v127/new-thread")
            .join(name)
            .to_str()
            .unwrap()
            .to_owned()
    };
    json!([
        {"argv":["--version"],"stdout":"v127\n"},
        {"argv":["project","list","--json","--include-personal"],"stdout":json!([{
            "id":"prj_syn_0001","kind":"standard","name":"Synthetic project one","gitRemoteUrl":"https://github.com/synthetic-owner/synthetic-repo.git","createdAt":1699100600000_i64,"updatedAt":1699200600000_i64,"sources":[]
        }]).to_string()},
        {"argv":["cloud","status","--json"],"stdout_file":fixture("cloud-status.json")},
        {"any_spawn":true,"creates":true,"stdout_file":fixture("spawn-receipt-created.json")},
        {"argv":["thread","show","thr_syn_0021","--json"],"stdout_file":fixture("thread-show-active.json")}
    ])
}
fn new_args<'a>(extra: &[&'a str]) -> Vec<&'a str> {
    let mut args = vec![
        "new",
        "--project-id",
        "prj_syn_0001",
        "--harness",
        "codex",
        "--model",
        "syn-codex-model-01",
        "--effort",
        "high",
        "--op-id",
        "op-create",
        "--json",
    ];
    args.extend(extra);
    args.extend(["--", "Synthetic"]);
    args
}

#[test]
fn cp2_new_models_preview_create_replay_refusal_and_status() {
    let f = Fixture::new("normal");
    f.room("normal", new_responses());
    report(
        &f.run(&["models", "--json"]),
        0,
        "new-thread",
        "options",
        "openwiz.cloud-options.v1",
    );
    let preview = report(
        &f.run(&new_args(&[])),
        12,
        "new-thread",
        "preview",
        "openwiz.new-thread-preview.v1",
    );
    assert_eq!(preview["verdict"]["kind"], "ready");
    assert!(!f.0.0.join("state").exists());
    for _ in 0..2 {
        let doc = report(
            &f.run(&new_args(&["--yes"])),
            0,
            "new-thread",
            "report",
            "openwiz.new-thread.v1",
        );
        assert_eq!(doc["status"], "created");
    }
    assert_eq!(f.count("spawn"), 1);
    report(
        &f.run(&["new", "--status", "op-create", "--json"]),
        0,
        "new-thread",
        "status_read",
        "openwiz.new-thread-status.v1",
    );
    report(
        &f.run(&["new", "--status", "op-absent", "--json"]),
        11,
        "new-thread",
        "status_read",
        "openwiz.new-thread-status.v1",
    );
    let mut changed = new_args(&["--yes"]);
    *changed.last_mut().unwrap() = "Changed synthetic";
    report(
        &f.run(&changed),
        8,
        "new-thread",
        "report",
        "openwiz.new-thread.v1",
    );
    let mut refused = new_args(&["--yes"]);
    refused[8] = "unsupported-synthetic-effort";
    refused[10] = "op-refused";
    report(
        &f.run(&refused),
        5,
        "new-thread",
        "report",
        "openwiz.new-thread.v1",
    );
    assert_eq!(f.count("spawn"), 1);
}

#[test]
fn cp2_new_failed_uncertain_and_unavailable_options_remain_reports() {
    for (answer, code, status) in [
        (
            json!({"any_spawn":true,"exit":1,"stderr":"Error: Failed to create thread: HTTP 400: Message is empty"}),
            5,
            "refused",
        ),
        (
            json!({"any_spawn":true,"creates":true,"abort":true}),
            6,
            "uncertain",
        ),
    ] {
        let f = Fixture::new("normal");
        let mut responses = new_responses().as_array().unwrap().clone();
        responses.insert(0, answer);
        f.room("normal", json!(responses));
        for _ in 0..2 {
            let doc = report(
                &f.run(&new_args(&["--yes"])),
                code,
                "new-thread",
                "report",
                "openwiz.new-thread.v1",
            );
            assert_eq!(doc["status"], status);
        }
        assert_eq!(f.count("spawn"), 1);
    }
    let f = Fixture::new("normal");
    f.room("normal",json!([{"argv":["cloud","status","--json"],"exit":1,"stderr":"SYNTHETIC_SECRET_DO_NOT_PRINT"}]));
    let doc = report(
        &f.run(&["models", "--json"]),
        13,
        "new-thread",
        "options",
        "openwiz.cloud-options.v1",
    );
    assert!(!doc.to_string().contains("SYNTHETIC_SECRET_DO_NOT_PRINT"));
}

#[test]
fn cp2_attachment_reports_include_preparation_failures_and_partial_results() {
    let f = Fixture::new("normal");
    fs::write(f.0.0.join("synthetic.txt"), "Synthetic bytes").unwrap();
    let doc = report(
        &f.run(&[
            "attachment",
            "add",
            "--json",
            "synthetic.txt",
            "missing.txt",
        ]),
        5,
        "attachment",
        "add_report",
        "openwiz.attachment-add.v1",
    );
    assert_eq!(doc["ready"].as_array().unwrap().len(), 1);
    assert_eq!(doc["failed"].as_array().unwrap().len(), 1);
    let id = doc["ready"][0]["staged"]["attachment"]["id"]
        .as_str()
        .unwrap();
    report(
        &f.run(&["attachment", "ls", "--json"]),
        0,
        "attachment",
        "list_report",
        "openwiz.attachment-list.v1",
    );
    report(
        &f.run(&["attachment", "rm", "--json", id]),
        0,
        "attachment",
        "remove_report",
        "openwiz.attachment-remove.v1",
    );
    report(
        &f.run(&["attachment", "rm", "--json", id]),
        3,
        "attachment",
        "remove_report",
        "openwiz.attachment-remove.v1",
    );
    for args in [
        vec![
            "send",
            "thr_syn_0001",
            "--op-id",
            "op-attach",
            "--json",
            "--attach",
            "missing.txt",
            "--",
            "Synthetic",
        ],
        new_args(&["--yes", "--attach", "missing.txt"]),
        new_args(&["--attach", "missing.txt"]),
    ] {
        report(
            &f.run(&args),
            5,
            "attachment",
            "add_report",
            "openwiz.attachment-add.v1",
        );
    }
    assert!(f.calls().is_empty());
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
    for extra in [
        vec!["fleet", "tick", "--dry-run", "--json"],
        vec!["fleet", "tick", "--json"],
    ] {
        let doc = report(
            &w.run(&extra),
            0,
            "fleet-tick",
            "envelope",
            "openwiz.fleet-tick.v1",
        );
        assert_eq!(doc["actions"].as_array().unwrap().len(), 1);
        assert_eq!(doc["actions"][0]["rule"], "frontier");
    }
    assert_eq!(
        w.writes()
            .iter()
            .filter(|(tool, args)| tool == "room-cli"
                && args.starts_with(&["thread".to_owned(), "spawn".to_owned()]))
            .count(),
        1
    );
}

#[test]
fn cp2_fleet_source_failures_and_partial_fleets_preserve_reports() {
    for args in [
        vec!["fleet", "9", "--json"],
        vec!["fleet", "tick", "--json"],
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
fn cp2_claimed_operations_report_in_progress_then_failed_without_dispatch() {
    use openwiz_core::{
        messaging::{
            Binding, Mode, OpId,
            record::{SendRecord, SendStore},
        },
        model::{SessionId, Timestamp},
        new_thread::{
            self, NewThreadRequest, ProjectRef, Settings,
            record::{NewThreadRecord, NewThreadStore},
        },
        prompt::PromptPayload,
    };
    let f = Fixture::new("send");
    let now = Timestamp(1_700_000_000_000);
    let op = OpId::parse("op-held").unwrap();
    let store = openwiz_store::FileStore::open(&f.0.0.join("state")).unwrap();
    let record = SendRecord::claimed(
        op.clone(),
        Binding::new(SessionId("thr_syn_0001".into()), Mode::Queue, "Synthetic"),
        "Synthetic",
        now,
    );
    assert!(matches!(
        store.claim(&record, now).unwrap(),
        openwiz_core::messaging::record::Claim::Owned
    ));
    report(
        &f.run(&[
            "send",
            "thr_syn_0001",
            "--op-id",
            "op-held",
            "--json",
            "--",
            "Synthetic",
        ]),
        7,
        "messaging",
        "report",
        "openwiz.messaging.v1",
    );
    report(
        &f.run(&[
            "send",
            "thr_syn_0001",
            "--op-id",
            "op-held",
            "--check",
            "--json",
        ]),
        7,
        "messaging",
        "lookup",
        "openwiz.send-lookup.v1",
    );
    store.release(&op);
    report(
        &f.run(&[
            "send",
            "thr_syn_0001",
            "--op-id",
            "op-held",
            "--json",
            "--",
            "Synthetic",
        ]),
        5,
        "messaging",
        "report",
        "openwiz.messaging.v1",
    );

    let settings = Settings {
        harness: "codex".into(),
        model: "syn-codex-model-01".into(),
        effort: "high".into(),
    };
    let req = NewThreadRequest::new(
        ProjectRef::Id("prj_syn_0001".into()),
        settings.clone(),
        PromptPayload::text("Synthetic"),
        OpId::parse("op-create").unwrap(),
    );
    let record = NewThreadRecord::claimed(
        req.op_id.clone(),
        new_thread::Binding::new(&req, openwiz_core::prompt::empty_attachments_digest()),
        settings,
        "Synthetic",
        now,
    );
    let store = openwiz_store::NewThreadFileStore::open(&f.0.0.join("state")).unwrap();
    assert!(matches!(
        store.claim(&record, now).unwrap(),
        new_thread::record::Claim::Owned
    ));
    report(
        &f.run(&new_args(&["--yes"])),
        7,
        "new-thread",
        "report",
        "openwiz.new-thread.v1",
    );
    report(
        &f.run(&["new", "--status", "op-create", "--json"]),
        7,
        "new-thread",
        "status_read",
        "openwiz.new-thread-status.v1",
    );
    store.release(&req.op_id);
    report(
        &f.run(&new_args(&["--yes"])),
        5,
        "new-thread",
        "report",
        "openwiz.new-thread.v1",
    );
    assert!(f.calls().is_empty());
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
fn cp2_attachment_claim_refusal_keeps_copies_and_numeric_exit() {
    let f = Fixture::new("send");
    fs::write(f.0.0.join("synthetic.txt"), "Synthetic bytes").unwrap();
    let doc = report(
        &f.run(&["attachment", "add", "--json", "synthetic.txt"]),
        0,
        "attachment",
        "add_report",
        "openwiz.attachment-add.v1",
    );
    let id = doc["ready"][0]["staged"]["attachment"]["id"]
        .as_str()
        .unwrap();
    f.room("send",json!([{"argv":["thread","tell","thr_syn_0001","--mode","queue","--json","--"],"any_text":true,"any_attachments":true,"abort":true}]));
    report(
        &f.run(&[
            "send",
            "thr_syn_0001",
            "--op-id",
            "op-attached",
            "--json",
            "--attachment",
            id,
            "--",
            "Synthetic",
        ]),
        6,
        "messaging",
        "report",
        "openwiz.messaging.v1",
    );
    report(
        &f.run(&["attachment", "rm", "--json", id]),
        14,
        "attachment",
        "remove_report",
        "openwiz.attachment-remove.v1",
    );
    assert!(f.0.0.join("state/attachments").join(id).exists());
    assert_eq!(f.count("tell"), 1);
}

#[test]
fn cp2_delimiter_and_stdin_flag_text_reach_the_target_as_data() {
    for from_stdin in [false, true] {
        let f = Fixture::new("send");
        let out = if from_stdin {
            f.stdin(&["send", "thr_syn_0001", "--op-id", "op-data"], b"--json")
        } else {
            f.run(&["send", "thr_syn_0001", "--op-id", "op-data", "--", "--json"])
        };
        assert_eq!(
            out.status.code(),
            Some(0),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        assert!(!out.stdout.starts_with(b"{"));
        let tells: Vec<_> = f.calls().into_iter().filter(|a| a[1] == "tell").collect();
        assert_eq!(tells.len(), 1);
        assert_eq!(tells[0][7], "--json");
    }
    let f = Fixture::new("normal");
    f.room("normal", new_responses());
    let mut args = new_args(&["--yes"]);
    args.retain(|a| *a != "--json");
    *args.last_mut().unwrap() = "--json";
    let out = f.run(&args);
    assert_eq!(out.status.code(), Some(0));
    assert!(!out.stdout.starts_with(b"{"));
    assert_eq!(f.count("spawn"), 1);
    let spawns: Vec<_> = f.calls().into_iter().filter(|a| a[1] == "spawn").collect();
    assert_eq!(spawns.len(), 1);
    assert_eq!(spawns[0].as_array().unwrap().last().unwrap(), "--json");
}

#[test]
fn cp2_non_utf8_attachment_paths_remain_supported_without_lossy_input() {
    use std::{ffi::OsString, os::unix::ffi::OsStringExt};
    let f = Fixture::new("normal");
    let path = OsString::from_vec(b"synthetic-\xff.txt".to_vec());
    fs::write(f.0.0.join(&path), "Synthetic bytes").unwrap();
    let out = f
        .command(&["attachment", "add", "--json", "--"])
        .arg(&path)
        .output()
        .unwrap();
    let doc = report(
        &out,
        0,
        "attachment",
        "add_report",
        "openwiz.attachment-add.v1",
    );
    assert_eq!(doc["ready"].as_array().unwrap().len(), 1);
    assert!(f.calls().is_empty());
}

#[test]
fn cp2_late_duplicate_attachment_error_does_not_rollback_preparation() {
    for form in ["send", "new", "new.preview"] {
        let f = Fixture::new("normal");
        fs::write(f.0.0.join("old.txt"), "Synthetic old bytes").unwrap();
        fs::write(f.0.0.join("new.txt"), "Synthetic newly staged bytes").unwrap();
        let staged = report(
            &f.run(&["attachment", "add", "--json", "old.txt"]),
            0,
            "attachment",
            "add_report",
            "openwiz.attachment-add.v1",
        );
        let id = staged["ready"][0]["staged"]["attachment"]["id"]
            .as_str()
            .unwrap();
        let extra = [
            "--attach",
            "new.txt",
            "--attachment",
            id,
            "--attachment",
            id,
        ];
        let args = if form == "send" {
            let mut args = vec!["send", "thr_syn_0001", "--op-id", "op-late", "--json"];
            args.extend(extra);
            args.extend(["--", "Synthetic"]);
            args
        } else {
            let mut flags = extra.to_vec();
            if form == "new" {
                flags.push("--yes");
            }
            new_args(&flags)
        };
        report(&f.run(&args), 2, "cli", "error", "openwiz.cli-error.v1");
        let listed = report(
            &f.run(&["attachment", "ls", "--json"]),
            0,
            "attachment",
            "list_report",
            "openwiz.attachment-list.v1",
        );
        assert_eq!(listed["attachments"].as_array().unwrap().len(), 2);
        assert_eq!(f.0.0.join("state/sends").exists(), form == "send");
        assert!(!f.0.0.join("state/new-threads").exists());
        assert!(f.calls().is_empty());
    }
}

#[test]
fn cp2_broken_stdout_preserves_legacy_outcome_without_retry_or_stderr_document() {
    let f = Fixture::new("send");
    let mut child = f
        .command(&[
            "send",
            "thr_syn_0001",
            "--op-id",
            "op-broken-output",
            "--json",
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    // No result can be produced before the text arrives. Close its read end
    // first; do not race a completed write or measure time.
    drop(child.stdout.take());
    child.stdin.take().unwrap().write_all(b"Synthetic").unwrap();
    let output = child.wait_with_output().unwrap();
    assert_eq!(output.status.code(), Some(0)); // send's existing output limitation
    assert!(!String::from_utf8_lossy(&output.stderr).contains("openwiz.cli-error.v1"));
    assert_eq!(f.count("tell"), 1);
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
    report(
        &f.run(&[
            "send",
            "thr_syn_0001",
            "--op-id",
            "op-repeated-json",
            "--json",
            "--json",
            "--",
            "Synthetic",
        ]),
        0,
        "messaging",
        "report",
        "openwiz.messaging.v1",
    );
    report(
        &f.run(&["attachment", "ls", "--json", "--json"]),
        0,
        "attachment",
        "list_report",
        "openwiz.attachment-list.v1",
    );
    assert_eq!(f.count("tell"), 1);
    let f = Fixture::new("normal");
    f.room("normal", new_responses());
    report(
        &f.run(&new_args(&["--json", "--yes"])),
        0,
        "new-thread",
        "report",
        "openwiz.new-thread.v1",
    );
    assert_eq!(f.count("spawn"), 1);
}

#[test]
fn cp2_attachment_store_errors_return_one_cli_error() {
    for args in [
        vec!["attachment", "add", "--json", "missing.txt"],
        vec!["attachment", "ls", "--json"],
        vec!["attachment", "rm", "--json", "attachment-synthetic"],
    ] {
        let f = Fixture::new("normal");
        fs::write(f.0.0.join("state"), "Synthetic non-directory").unwrap();
        report(&f.run(&args), 10, "cli", "error", "openwiz.cli-error.v1");
        assert!(f.calls().is_empty());
    }
}
