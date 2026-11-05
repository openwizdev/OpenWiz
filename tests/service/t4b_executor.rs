//! Recording command fakes: manual CLI and scheduled service use the same tick.
//! All data, credentials, endpoint responses and archive states are synthetic.
use super::*;
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_adapter_github::{
    app::{Clock, Error, Exchange},
    process::Executor,
    tick::TickReads,
    writes::{self, Confirmed, Write},
};
use openwiz_cli::fleet::tick::{self as cli, Args, Context};
use openwiz_core::fleet::model::{Commit, Number};
use openwiz_service::{app::Client, scheduler::Scheduler, tick};
use std::sync::{Arc, Mutex};

#[path = "t4b_fake.rs"]
mod fake;
#[path = "../fixture-entrypoints/fixture.rs"]
mod fixture;
#[path = "t4b_fleet.rs"]
mod fleet;

const HEAD: &str = "1010101010101010101010101010101010101010";
const APP_TOKEN: &str = "synthetic-t4b-installation-token";
const PERSONAL: &str = "synthetic-t4b-personal-token";
const RULES: &str = "## Builder\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Codex | `--provider codex` |\n| Model | Synthetic | `--model syn-builder` |\n| Effort | High | `--reasoning-level high` |\n## Reviewer\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Claude | `--provider claude-code` |\n| Model | Synthetic | `--model syn-reviewer` |\n| Effort | High | `--reasoning-level high` |\n## CI checks\n| Check | Runs | Required on |\n| --- | --- | --- |\n| `rust` | tests | `main` |\n## Standing merge rules\n| Pull request | Review | Merged by, and when |\n| --- | --- | --- |\n| A ticket in an approved plan graph | reviewer | The loop, as soon as the reviewer's APPROVE names that exact commit |\n";

// Synthetic #1196 tables for CI's newer parser. Keep RULES's older Reviewer
// section too, so the branch and its merge with main exercise the same input.
const CONDITIONAL_RULES: &str = r#"## Builder for small tickets
| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Codex | `--provider codex` |
| Model | Synthetic small | `--model syn-small` |
| Effort | High | `--reasoning-level high` |
## Reviewer for Claude-built
| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Codex | `--provider codex` |
| Model | Synthetic reviewer | `--model syn-reviewer` |
| Effort | High | `--reasoning-level high` |
## Reviewer for GPT-built
| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Claude | `--provider claude-code` |
| Model | Synthetic reviewer | `--model syn-reviewer` |
| Effort | High | `--reasoning-level high` |
"#;

struct FixedClock;
impl Clock for FixedClock {
    fn now_s(&self) -> u64 {
        1_893_456_000
    }
}
struct Token(String);
impl Exchange for Token {
    fn exchange(
        &self,
        installation: u64,
        jwt: &str,
        body: &[u8],
        _: Instant,
    ) -> Result<Vec<u8>, Error> {
        assert_eq!(installation, 2002);
        assert_eq!(jwt.split('.').count(), 3);
        assert_eq!(
            serde_json::from_slice::<Value>(body).unwrap()["repositories"],
            json!([self.0])
        );
        Ok(json!({"token":APP_TOKEN,"expires_at":"2030-01-01T01:00:00Z","permissions":{"metadata":"read","contents":"write","issues":"write","pull_requests":"write","checks":"read","actions":"read"}}).to_string().into_bytes())
    }
}

fn setup(f: &Fixture) {
    fs::write(f.0.join("rules.md"), format!("{RULES}{CONDITIONAL_RULES}")).unwrap();
    let quote =
        |path: &std::path::Path| format!("'{}'", path.to_str().unwrap().replace('\'', "'\\''"));
    for tool in ["gh", "room-cli"] {
        let launcher = format!(
            "#!/bin/sh\numask 077\nexport OPENWIZ_T4B_TOOL_ROOT={}\nexport OPENWIZ_T4B_TOOL_ARGS={}/args-$$\nexport OPENWIZ_T4B_TOOL={tool}\nprintf '%s\\0' \"$@\" > \"$OPENWIZ_T4B_TOOL_ARGS\"\nexec {} --exact executor::fake::tool_process --nocapture 3>&1 >/dev/null\n",
            quote(&f.0),
            quote(&f.0),
            quote(&std::env::current_exe().unwrap())
        );
        place_script(&f.0.join(tool), &launcher);
    }
    let mut thread: Value = serde_json::from_str(include_str!(
        "../fixtures/room-cli-v127/new-thread/thread-show-active.json"
    ))
    .unwrap();
    thread["thread"]["archivedAt"] = json!(1_700_000_700_000_u64);
    thread["thread"]["title"] = json!("#10: Synthetic");
    fs::write(f.0.join("thread.json"), thread.to_string()).unwrap();
    fs::write(f.0.join("comments.json"), json!([{"id":100,"body":"launch-fleet: started","created":1_700_000_000_000_u64,"updated":1_700_000_000_000_u64}]).to_string()).unwrap();
    DirBuilder::new()
        .mode(0o700)
        .create(f.0.join("service/app"))
        .unwrap();
    let key = f.0.join("service/app/private-key.pem");
    let out = Command::new("/usr/bin/openssl")
        .args([
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:2048",
            "-out",
        ])
        .arg(&key)
        .output()
        .unwrap();
    assert!(out.status.success());
    fs::set_permissions(key, fs::Permissions::from_mode(0o600)).unwrap();
}
fn executor(f: &Fixture) -> Executor {
    let config: Value =
        serde_json::from_slice(&fs::read(f.0.join("service/config.json")).unwrap()).unwrap();
    let client = Client::with_exchange(
        &f.0,
        &config.to_string(),
        f.0.join("gh"),
        Arc::new(Token(
            config["repository"]["name"]
                .as_str()
                .unwrap()
                .to_ascii_lowercase(),
        )),
        Arc::new(FixedClock),
    )
    .unwrap();
    Executor::supplied(Arc::new(move |call, deadline| {
        client
            .execute(call, deadline)
            .map_err(|_| openwiz_core::source::SourceError::Unavailable {
                detail: "synthetic App failure".into(),
            })
    }))
}
fn run_tick(f: &Fixture, dry: bool, github: &TickReads) -> Result<Value, &'static str> {
    let mut out = Vec::new();
    cli::run_with(
        Args {
            due: false,
            dry_run: dry,
            json: true,
        },
        Context {
            github,
            room: &CloudRoomSource::new(f.0.join("room-cli")),
            state: &f.0,
            orchestrator: Some("thr_syn_0001"),
        },
        &mut out,
    )?;
    Ok(serde_json::from_slice(&out).unwrap())
}
fn calls(f: &Fixture) -> Vec<Value> {
    fs::read_to_string(f.0.join("calls.jsonl"))
        .unwrap_or_default()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect()
}
fn comments(f: &Fixture) -> Value {
    serde_json::from_slice(&fs::read(f.0.join("comments.json")).unwrap()).unwrap()
}
fn child(f: &Fixture, case: &str) -> std::process::Output {
    let out = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "executor::executor_process", "--nocapture"])
        .env("OPENWIZ_T4B_CASE", case)
        .env("OPENWIZ_T4B_PROCESS_ROOT", &f.0)
        .env("OPENWIZ_STATE_DIR", &f.0)
        .env("OPENWIZ_FIXTURE_PROGRAM", f.0.join("room-cli"))
        .env_remove("OPENWIZ_FIXTURE_ROOT")
        .env("PATH", &f.0)
        .env("GH_TOKEN", PERSONAL)
        .stdin(Stdio::null())
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    out
}

#[test]
fn manual_and_scheduled_ticks_have_identical_records_and_dry_run_gates() {
    let manual = Fixture::new();
    setup(&manual);
    child(&manual, "manual");
    let scheduled = Fixture::new();
    setup(&scheduled);
    child(&scheduled, "scheduled");
    assert_eq!(comments(&manual), comments(&scheduled));
    assert_eq!(comments(&scheduled)[1]["body"], "launch-fleet: archived");
    assert_eq!(comments(&scheduled).as_array().unwrap().len(), 2);
    let manual_calls = calls(&manual);
    let scheduled_calls = calls(&scheduled);
    // Compare every argument, in exact order per tool; parallel inventory reads
    // may complete in either order, so compare their sorted multisets.
    for tool in ["gh", "room-cli"] {
        let args = |log: &[Value]| {
            let mut rows = log
                .iter()
                .filter(|v| v["tool"] == tool)
                .map(|v| v["args"].to_string())
                .collect::<Vec<_>>();
            rows.sort();
            rows
        };
        let mut expected = args(&manual_calls);
        let actual = args(&scheduled_calls);
        if tool == "room-cli" {
            let project_read =
                json!(["project", "list", "--json", "--include-personal"]).to_string();
            assert_eq!(expected.iter().filter(|v| **v == project_read).count(), 3);
            assert_eq!(actual.iter().filter(|v| **v == project_read).count(), 4);
            // The service revalidates configured-project placement immediately
            // before its one action. Every other read/write remains identical.
            expected.push(project_read);
            expected.sort();
        }
        assert_eq!(expected, actual, "{tool}");
    }
    let gh = scheduled_calls
        .iter()
        .filter(|v| v["tool"] == "gh")
        .collect::<Vec<_>>();
    assert!(!gh.is_empty());
    assert!(gh.iter().all(
        |v| v["token"] == APP_TOKEN && v["repo"] == "github.com/synthetic-owner/synthetic-repo"
    ));
    assert!(
        manual_calls
            .iter()
            .filter(|v| v["tool"] == "gh")
            .all(|v| v["token"] == PERSONAL)
    );
}

#[test]
fn nested_ci_reads_and_confirmed_writes_keep_app_execution_on_success_and_error() {
    let f = Fixture::new();
    setup(&f);
    child(&f, "nested");
}

#[test]
fn command_fakes_work_without_system_python() {
    let f = Fixture::new();
    setup(&f);
    // Model CI's absent /usr/bin/python3 without changing the host's tools.
    // PATH in child() already contains only our fakes. A native launcher needs
    // no rewriting; the old Python shebang now fails with the same ENOENT.
    let launcher = f.0.join("gh");
    let source = fs::read_to_string(&launcher).unwrap();
    let missing = f.0.join("absent-system-python");
    assert!(!missing.exists());
    place_script(
        &launcher,
        &source.replacen("#!/usr/bin/python3", &format!("#!{}", missing.display()), 1),
    );
    child(&f, "nested");
}

#[test]
fn executor_process() {
    let Ok(case) = std::env::var("OPENWIZ_T4B_CASE") else {
        return;
    };
    // Parent owns cleanup; this child exits without running Fixture::drop.
    let f = std::mem::ManuallyDrop::new(Fixture(PathBuf::from(
        std::env::var_os("OPENWIZ_T4B_PROCESS_ROOT").unwrap(),
    )));
    if case == "nested" {
        nested(&f);
        return;
    }
    let bundle = fixture::Bundle::from_environment();
    openwiz_adapter_cloudroom::locate::install(bundle.discovery()).unwrap();
    if case == "completion-control" {
        let gh = TickReads::with_executor(executor(&f));
        let dry = run_tick(&f, true, &gh).unwrap();
        let expected: String =
            serde_json::from_slice::<Value>(&fs::read(f.0.join("expected-rule.json")).unwrap())
                .unwrap()
                .as_str()
                .unwrap()
                .into();
        assert_eq!(dry["actions"].as_array().unwrap().len(), 1, "{dry}");
        assert_eq!(dry["actions"][0]["rule"], expected, "{dry}");
        assert_eq!(dry["actions"][0]["outcome"]["state"], "planned");
        let control = cli::Control::new(
            "prj_syn_0001",
            Arc::new(std::sync::atomic::AtomicBool::new(false)),
        )
        .unwrap();
        let mut out = Vec::new();
        cli::run_with_control(
            Args {
                due: false,
                dry_run: false,
                json: true,
            },
            Context {
                github: &gh,
                room: &CloudRoomSource::new(f.0.join("room-cli")),
                state: &f.0,
                orchestrator: Some("thr_syn_0001"),
            },
            &mut out,
            &control,
        )
        .unwrap();
        let actual: Value = serde_json::from_slice(&out).unwrap();
        assert_eq!(actual["actions"][0]["rule"], expected, "{actual}");
        assert_eq!(
            actual["actions"][0]["outcome"]["state"], "refused",
            "{actual}"
        );
        assert_eq!(
            actual["actions"][0]["outcome"]["reason"],
            "completion verification is unavailable; orchestrator judgment required",
            "{actual}"
        );
        return;
    }
    if case == "fleet-dry" {
        let value = run_tick(&f, true, &TickReads::with_executor(executor(&f))).unwrap();
        fs::write(f.0.join("dry.json"), value.to_string()).unwrap();
        return;
    }
    if case == "fleet-scheduled" {
        archive_pass(&f, 5000);
        return;
    }
    if case == "completion-scheduled" {
        archive_pass(&f, 4000);
        return;
    }
    if case.starts_with("archive-") {
        archive_pass(&f, if case == "archive-first" { 2000 } else { 4000 });
        return;
    }
    let before = comments(&f);
    let entries = || {
        let mut names = fs::read_dir(&f.0)
            .unwrap()
            .map(|e| e.unwrap().file_name())
            .filter(|n| n != "calls.jsonl")
            .collect::<Vec<_>>();
        names.sort();
        names
    };
    let before_files = entries();
    if case == "manual" {
        let mut out = Vec::new();
        let mut err = Vec::new();
        let args = |dry| {
            let mut a = vec!["tick".into(), "--json".into()];
            if dry {
                a.push("--dry-run".into());
            }
            a
        };
        assert_eq!(
            cli::run(&args(true), &mut out, &mut err),
            0,
            "manual dry run: {}",
            String::from_utf8_lossy(&err)
        );
        assert_eq!(
            serde_json::from_slice::<Value>(&out).unwrap()["actions"][0]["outcome"]["state"],
            "planned"
        );
        assert_eq!(comments(&f), before);
        assert_eq!(entries(), before_files, "dry run creates no store or lock");
        assert_eq!(cli::run(&args(false), &mut Vec::new(), &mut err), 0);
        assert_eq!(cli::run(&args(false), &mut Vec::new(), &mut err), 0);
        assert!(err.is_empty());
    } else {
        let gh = Arc::new(TickReads::with_executor(executor(&f)));
        let dry = run_tick(&f, true, &gh).unwrap();
        assert_eq!(dry["mode"], "dry_run");
        assert_eq!(dry["actions"].as_array().unwrap().len(), 1);
        assert_eq!(dry["actions"][0]["outcome"]["state"], "planned");
        assert_eq!(comments(&f), before);
        assert_eq!(entries(), before_files, "dry run creates no store or lock");
        let state = Arc::new(Mutex::new(f.state()));
        let mut scheduler = Scheduler::default();
        let mut config = f.config(7370);
        config["tick"]["every_s"] = json!(3);
        tick::register_with_sources(
            &f.0,
            &config,
            state.clone(),
            &mut scheduler,
            tick::Sources {
                github: executor(&f),
                room: CloudRoomSource::new(f.0.join("room-cli")),
            },
            || 2000,
        )
        .unwrap();
        assert!(scheduler.poll(2).unwrap().is_empty());
        assert_eq!(scheduler.poll(3).unwrap(), [tick::JOB]);
        scheduler.wait(tick::JOB).unwrap();
        assert_eq!(scheduler.poll(6).unwrap(), [tick::JOB]);
        scheduler.wait(tick::JOB).unwrap();
        assert_eq!(
            state.lock().unwrap().snapshot()["tick"]["last_ended"]["how"],
            "finished"
        );
    }
    assert_eq!(
        comments(&f).as_array().unwrap().len(),
        2,
        "repeat never duplicates record"
    );
}

fn nested(f: &Fixture) {
    let execute = executor(f);
    let gh = TickReads::with_executor(execute.clone());
    let until = || Instant::now() + Duration::from_secs(5);
    let ci = gh
        .checks(
            Number::new(110).unwrap(),
            &Commit::parse(HEAD).unwrap(),
            until(),
        )
        .unwrap()
        .unwrap();
    assert_eq!(ci.checks.len(), 1);
    let write = Write::CloseIssue {
        issue: Number::new(10).unwrap(),
    };
    assert_eq!(
        writes::perform_with(&execute, &write, until()).unwrap(),
        Confirmed::Closed
    );
    let success = calls(f);
    let paths = success
        .iter()
        .map(|v| v["args"].clone())
        .collect::<Vec<_>>();
    assert_eq!(paths.len(), 7, "4 CI reads and 3 close calls");
    assert_eq!(
        paths[2],
        json!(["pr", "checks", "110", "--json", "bucket,name"])
    );
    assert_eq!(paths[4], json!(["issue", "view", "10", "--json", "url"]));
    assert_eq!(paths[5], json!(["issue", "close", "10"]));
    assert_eq!(paths[6], json!(["issue", "view", "10", "--json", "state"]));
    assert!(success.iter().all(|v| v["token"] == APP_TOKEN));
    for (index, path) in paths.iter().enumerate() {
        fs::write(f.0.join("deny.json"), path.to_string()).unwrap();
        let before = calls(f).len();
        if index < 4 {
            assert!(
                gh.checks(
                    Number::new(110).unwrap(),
                    &Commit::parse(HEAD).unwrap(),
                    until()
                )
                .is_err()
            );
        } else {
            assert!(writes::perform_with(&execute, &write, until()).is_err());
        }
        let log = calls(f);
        let new = &log[before..];
        assert_eq!(new.last().unwrap()["args"], *path);
        assert_eq!(
            new.len(),
            if index < 4 { index + 1 } else { index - 3 },
            "stop at first failure"
        );
        assert!(
            new.iter().all(|v| v["token"] == APP_TOKEN),
            "no personal login fallback"
        );
    }
}

fn archive_pass(f: &Fixture, at: u64) {
    let state = Arc::new(Mutex::new(
        openwiz_service::state::State::load(&f.0, at).unwrap(),
    ));
    let mut scheduler = Scheduler::default();
    let mut config: Value =
        serde_json::from_slice(&fs::read(f.0.join("service/config.json")).unwrap()).unwrap();
    config["tick"]["every_s"] = json!(3);
    tick::register_with_sources(
        &f.0,
        &config,
        state,
        &mut scheduler,
        tick::Sources {
            github: executor(f),
            room: CloudRoomSource::new(f.0.join("room-cli")),
        },
        move || at,
    )
    .unwrap();
    assert_eq!(scheduler.poll(3).unwrap(), [tick::JOB]);
    scheduler.wait(tick::JOB).unwrap();
}

#[test]
fn scheduled_archive_recovers_one_final_record_after_clean_wake() {
    let f = Fixture::new();
    setup(&f);
    let mut thread: Value =
        serde_json::from_slice(&fs::read(f.0.join("thread.json")).unwrap()).unwrap();
    thread["thread"]["archivedAt"] = Value::Null;
    fs::write(f.0.join("thread.json"), thread.to_string()).unwrap();
    fs::write(
        f.0.join("fail-final-once"),
        "Synthetic final-record failure.",
    )
    .unwrap();
    let archive_count = || {
        calls(&f)
            .iter()
            .filter(|c| c["tool"] == "room-cli" && c["args"][1] == "archive")
            .count()
    };
    let final_count = || {
        comments(&f)
            .as_array()
            .unwrap()
            .iter()
            .filter(|c| c["body"] == "launch-fleet: archived")
            .count()
    };
    child(&f, "archive-first");
    let archived: Value =
        serde_json::from_slice(&fs::read(f.0.join("thread.json")).unwrap()).unwrap();
    assert!(archived["thread"]["archivedAt"].is_number());
    assert_eq!(archive_count(), 1);
    assert_eq!(final_count(), 0, "failed record remains outstanding");
    child(&f, "archive-again");
    assert_eq!(
        archive_count(),
        1,
        "clean wake must not archive the same thread twice"
    );
    assert_eq!(final_count(), 1);
    child(&f, "archive-again");
    assert_eq!(archive_count(), 1);
    assert_eq!(
        final_count(),
        1,
        "another wake must not duplicate the final record"
    );
    assert_eq!(comments(&f).as_array().unwrap().len(), 2);
    assert!(
        calls(&f)
            .iter()
            .filter(|c| c["tool"] == "gh")
            .all(|c| c["token"] == APP_TOKEN)
    );
}

// The dry-run control proves completion is due. Closed tickets alone do not
// authorize completion, and the scheduled hold must reach private diagnostics.
fn completion_case(rule: &str, summarized: bool) {
    let f = Fixture::new();
    setup(&f);
    let mut comments = vec![
        json!({"id":100,"body":include_str!("fixtures/t4-completion-approval.md"),"created":1_793_400_000_000_u64,"updated":1_793_400_000_000_u64}),
    ];
    if summarized {
        comments.push(json!({"id":101,"body":"launch-fleet: spec summary: synthetic","created":1_793_400_010_000_u64,"updated":1_793_400_010_000_u64}));
    }
    let issues = synthetic_issues(true);
    fs::write(
        f.0.join("completion.json"),
        json!({"issues":issues,"comments":comments}).to_string(),
    )
    .unwrap();
    fs::write(f.0.join("expected-rule.json"), json!(rule).to_string()).unwrap();
    let before = fs::read(f.0.join("completion.json")).unwrap();
    child(&f, "completion-control");
    for _ in 0..2 {
        let output = child(&f, "completion-scheduled");
        let diagnostic = String::from_utf8_lossy(&output.stderr);
        assert!(
            diagnostic.contains(rule),
            "missing scheduled rule: {diagnostic}"
        );
        assert!(
            diagnostic
                .contains("completion verification is unavailable; orchestrator judgment required"),
            "{diagnostic}"
        );
        assert_eq!(fs::read(f.0.join("completion.json")).unwrap(), before);
    }
    let log = calls(&f);
    assert!(
        !log.iter().any(|row| matches!(
            (row["args"][0].as_str(), row["args"][1].as_str()),
            (Some("issue"), Some("comment" | "close"))
                | (Some("thread"), Some("tell" | "spawn" | "archive"))
        )),
        "completion produced effects: {log:?}"
    );
    assert!(
        log.iter()
            .filter(|row| row["tool"] == "gh")
            .all(|row| row["token"] == APP_TOKEN
                && row["repo"] == "github.com/synthetic-owner/synthetic-repo")
    );
}

#[test]
fn spec_summary_completion_is_held_across_clean_wakes() {
    completion_case("spec_summary", false);
}

#[test]
fn all_closed_completion_is_held_across_clean_wakes() {
    completion_case("all_closed", true);
}

fn synthetic_issues(closed: bool) -> Vec<Value> {
    let mut issues = Vec::new();
    for (number, title, body, blockers, children) in [
        (
            9,
            "Synthetic graph",
            "Synthetic graph",
            vec![],
            vec![10, 11],
        ),
        (
            10,
            "Synthetic ticket 10",
            "**Owned paths:** `crates/example/one.rs`\n**Relies on:** nothing",
            vec![],
            vec![],
        ),
        (
            11,
            "Synthetic ticket 11",
            "**Owned paths:** `crates/example/two.rs`\n**Relies on:** nothing",
            vec![10],
            vec![],
        ),
    ] {
        let links = |ns: &[u64]| json!({"nodes":ns.iter().map(|n| json!({"id":format!("syn-issue-{n}"),"number":n,"state":if closed {"CLOSED"} else {"OPEN"},"title":format!("Synthetic ticket {n}"),"url":format!("https://example.invalid/issues/{n}")})).collect::<Vec<_>>(),"totalCount":ns.len()});
        issues.push(json!({"blockedBy":links(&blockers),"body":body,"id":format!("syn-issue-{number}"),"labels":if number==9 {json!([])} else {json!([{"id":"syn-label-ready-for-agent","name":"ready-for-agent","description":"Synthetic","color":"ffffff"}])},"milestone":null,"number":number,"state":if number==9 || !closed {"OPEN"} else {"CLOSED"},"subIssues":links(&children),"title":title}));
    }
    issues
}

/// Places the executable `src` at `dst`, owner-only. A separate `cp` process
/// writes it, so this process never holds a writable descriptor for it: a
/// child another test forks meanwhile would inherit one until its exec and
/// keep the file busy, so launching it would fail with ETXTBSY (#2583, as
/// #2559 and #1754).
fn place(src: &std::path::Path, dst: &std::path::Path) {
    placed(copier(src, dst), dst);
}
/// Starts `place`'s `cp`, with no input and its output captured.
fn copier(src: &std::path::Path, dst: &std::path::Path) -> std::process::Child {
    use std::process::Stdio;
    // `cp` would copy into a directory and succeed (#2721, #2731).
    assert!(!dst.is_dir(), "{} is a directory", dst.display());
    std::process::Command::new("cp")
        .arg("--")
        .arg(src)
        .arg(dst)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("cp runs")
}
/// Waits for `place`'s `cp` to succeed, then makes `dst` executable, owner-only.
fn placed(cp: std::process::Child, dst: &std::path::Path) {
    use std::os::unix::fs::PermissionsExt;
    let out = cp.wait_with_output().expect("cp runs");
    assert!(
        out.status.success(),
        "cp {}: {}",
        dst.display(),
        String::from_utf8_lossy(&out.stderr)
    );
    std::fs::set_permissions(dst, std::fs::Permissions::from_mode(0o700)).unwrap();
}
/// Places a fixture script the same way, from a source file that never runs.
fn place_script(dst: &std::path::Path, text: &str) {
    let src = dst.with_extension("src");
    std::fs::write(&src, text).unwrap();
    place(&src, dst);
    std::fs::remove_file(&src).unwrap();
}
/// Descriptors of this process open for writing on `path`'s file.
#[cfg(target_os = "linux")]
fn writers(path: &std::path::Path) -> usize {
    use std::os::unix::fs::MetadataExt;
    let (fds, infos) = (
        std::path::Path::new("/proc/self/fd"),
        std::path::Path::new("/proc/self/fdinfo"),
    );
    let target = std::fs::metadata(path).unwrap();
    std::fs::read_dir(fds)
        .unwrap()
        .filter_map(|fd| {
            let fd = fd.ok()?.file_name();
            let file = std::fs::metadata(fds.join(&fd)).ok()?;
            let info = std::fs::read_to_string(infos.join(&fd)).ok()?;
            let flags = info.lines().find_map(|l| l.strip_prefix("flags:"))?;
            let access = u32::from_str_radix(flags.trim(), 8).unwrap() & 3;
            (file.dev() == target.dev() && file.ino() == target.ino() && access != 0).then_some(())
        })
        .count()
}
/// #2583 (as #2559): this binary's fakes are placed while other test threads
/// fork. The copy is held mid-way on a FIFO, where this process must hold no
/// writer for the placed file; then the placed program launches.
#[cfg(target_os = "linux")]
#[test]
fn placing_a_fake_executable_leaves_no_writer_a_concurrent_fork_could_inherit() {
    let dir = PlaceDir::new("ow-place-t4b");
    let program = dir.0.join("placed");
    let held = writers_mid_copy(&dir.0, &program);
    assert_eq!(
        held, 0,
        "mid-copy, this process held a writable descriptor for the placed \
         executable: a child forked then keeps it busy (ETXTBSY)"
    );
    let run = std::process::Command::new(&program).output().unwrap();
    assert!(run.status.success());
    assert_eq!(run.stdout, b"PLACED\n");
}
/// #2731 (as #2721): a directory at the exact destination is refused,
/// instead of `cp` placing the program inside that directory and reporting
/// success.
#[test]
fn placing_onto_a_directory_destination_is_refused() {
    use std::os::unix::fs::DirBuilderExt;
    let dir = std::env::temp_dir().join(format!("ow-place-dir-t4b-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let destination = dir.join("placed");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&destination)
        .unwrap();
    let placed = std::panic::catch_unwind(|| place_script(&destination, "#!/bin/sh\nexit 0\n"));
    assert!(
        placed.is_err(),
        "a directory destination was accepted; the program landed inside it"
    );
    assert_eq!(std::fs::read_dir(&destination).unwrap().count(), 0);
    std::fs::remove_dir_all(&dir).unwrap();
}
/// #2699 (as #2594): the proof above fails, never hangs, when its copier fails
/// before opening the FIFO. Here `cp` cannot stat a destination under a
/// regular file.
#[cfg(target_os = "linux")]
#[test]
#[should_panic(expected = "the copier ended before opening the FIFO")]
fn the_fifo_proof_fails_when_its_copier_fails_before_the_rendezvous() {
    let dir = PlaceDir::new("ow-place-t4b-early");
    let file = dir.0.join("file");
    std::fs::write(&file, "").unwrap();
    writers_mid_copy(&dir.0, &file.join("placed"));
}
/// #2707, #2734: a copier still waiting on the FIFO when a proof fails is
/// killed and reaped as its `Copy` unwinds, never left behind. With no writer
/// started, the copier stays blocked opening the FIFO past the deadline.
#[cfg(target_os = "linux")]
#[test]
fn the_fifo_proof_reaps_a_copier_that_misses_its_deadline() {
    let dir = PlaceDir::new("ow-place-t4b-late");
    let fifo = dir.0.join("late.fifo");
    let made = std::process::Command::new("mkfifo").arg(&fifo).status();
    assert!(made.unwrap().success());
    let program = dir.0.join("placed");
    let cp = copier(&fifo, &program);
    let pid = cp.id();
    let unwound = std::panic::catch_unwind(move || {
        let _copy = Copy {
            source: None,
            cp: Some(cp),
            program,
            until: std::time::Instant::now(),
        };
        panic!("the proof failed while its copier waited");
    });
    assert!(unwound.is_err());
    let left = std::fs::metadata(format!("/proc/{pid}")).map(|_| ());
    assert_eq!(
        left.map_err(|e| e.kind()),
        Err(std::io::ErrorKind::NotFound),
        "the copier was left running or unreaped after the proof unwound"
    );
}
/// An owner-only scratch directory for one FIFO proof, removed when dropped,
/// even by a failing proof.
#[cfg(target_os = "linux")]
struct PlaceDir(std::path::PathBuf);
#[cfg(target_os = "linux")]
impl PlaceDir {
    fn new(prefix: &str) -> Self {
        use std::os::unix::fs::DirBuilderExt;
        let dir = std::env::temp_dir().join(format!("{prefix}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
        Self(dir)
    }
}
#[cfg(target_os = "linux")]
impl Drop for PlaceDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
/// Places a script at `program` as `place` does, from a FIFO in `dir` this
/// process writes, and returns how many writers this process held for
/// `program` while the copy was held mid-way.
#[cfg(target_os = "linux")]
fn writers_mid_copy(dir: &std::path::Path, program: &std::path::Path) -> usize {
    use std::time::{Duration, Instant};
    let fifo = dir.join("source.fifo");
    let made = std::process::Command::new("mkfifo").arg(&fifo).status();
    assert!(made.unwrap().success());
    let mut copy = Copy::start(&fifo, program, Instant::now() + Duration::from_secs(10));
    let head = b"#!/bin/sh\n";
    copy.write(head);
    // Once the first bytes have landed, the placed file's writer is open.
    while std::fs::metadata(program).map_or(true, |m| m.len() < head.len() as u64) {
        copy.check("the copy started");
    }
    let held = writers(program);
    copy.write(b"printf 'PLACED\\n'\n");
    copy.finish();
    held
}
/// `place`'s `cp` copying a FIFO to `program`, and this process's writer for
/// that FIFO. Dropped, even by a failing proof, it closes the writer, so the
/// copier reads its end, then kills a copier still running after a short
/// grace and reaps it (#2707).
#[cfg(target_os = "linux")]
struct Copy {
    source: Option<std::fs::File>,
    cp: Option<std::process::Child>,
    program: std::path::PathBuf,
    until: std::time::Instant,
}
#[cfg(target_os = "linux")]
impl Copy {
    /// Starts the copier and opens the FIFO's writer once the copier's reader
    /// has it open, failing if the copier ends first or `until` passes.
    fn start(fifo: &std::path::Path, program: &std::path::Path, until: std::time::Instant) -> Self {
        let mut copy = Self {
            source: None,
            cp: Some(copier(fifo, program)),
            program: program.to_owned(),
            until,
        };
        // Opening blocks until a reader has the FIFO open, so it runs on its
        // own thread while this one watches the copier and the deadline.
        let opening = {
            let fifo = fifo.to_owned();
            std::thread::spawn(move || std::fs::OpenOptions::new().write(true).open(fifo))
        };
        while !opening.is_finished() {
            if copy.ended() || std::time::Instant::now() >= until {
                // A reader of this process's own completes the open; dropped
                // with it, so the copier sees an empty source if it opens late.
                let reader = std::fs::File::open(fifo);
                drop(opening.join());
                drop(reader);
                assert!(!copy.ended(), "the copier ended before opening the FIFO");
                panic!("the copier never opened the FIFO");
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        copy.source = Some(opening.join().unwrap().unwrap());
        copy
    }
    fn ended(&mut self) -> bool {
        self.cp
            .as_mut()
            .is_none_or(|cp| cp.try_wait().unwrap().is_some())
    }
    /// Fails if the copier has ended or `until` has passed; else waits a moment.
    fn check(&mut self, waiting_for: &str) {
        assert!(!self.ended(), "the copier ended before {waiting_for}");
        assert!(
            std::time::Instant::now() < self.until,
            "the deadline passed before {waiting_for}"
        );
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    fn write(&mut self, bytes: &[u8]) {
        use std::io::Write;
        self.source.as_mut().unwrap().write_all(bytes).unwrap();
    }
    /// Closes the writer and waits, by `until`, for the copier to succeed.
    fn finish(mut self) {
        drop(self.source.take());
        while !self.ended() {
            assert!(
                std::time::Instant::now() < self.until,
                "the copier never finished"
            );
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        placed(self.cp.take().unwrap(), &self.program);
    }
}
#[cfg(target_os = "linux")]
impl Drop for Copy {
    fn drop(&mut self) {
        drop(self.source.take());
        // The copier ends soon after its end of file: a short grace past a
        // missed deadline, never an unbounded wait.
        let now = std::time::Instant::now();
        let until = self.until.max(now + std::time::Duration::from_secs(1));
        while !self.ended() && std::time::Instant::now() < until {
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        if let Some(mut cp) = self.cp.take() {
            let _ = cp.kill();
            let _ = cp.wait();
        }
    }
}
