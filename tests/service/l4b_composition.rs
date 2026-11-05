//! Production composition over synthetic GitHub documents and a fake room-cli.
//! synthetic_assumptions: all API documents, project/branch identity, CI results,
//! webhook metadata and receipts. No live endpoint or credential is used.
use crate::support::Fixture;
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_adapter_github::{
    process::Executor,
    tick::{JOBS, RUNS},
};
use openwiz_service::{events::intake, scheduler::Scheduler, tick::Sources};
use serde_json::{Value, json};
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::Path,
    sync::{Arc, Mutex},
    time::Instant,
};

struct Time;
impl openwiz_core::ops::Clock for Time {
    fn now(&self) -> openwiz_core::model::Timestamp {
        openwiz_core::model::Timestamp(1_793_400_020_000)
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}
const REPOSITORY: &str = "synthetic-owner/synthetic-repo";
const HEAD: &str = "1010101010101010101010101010101010101010";
const BASE: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
fn config() -> Value {
    json!({"schema":"openwiz.service-config.v1","repository":{"owner":"synthetic-owner","name":"synthetic-repo"},"project":"prj_syn_0001","orchestrator_thread":"thr_syn_0001","service_issue":901,"github_app":{"app_id":1001,"installation_id":2002},"tick":{"every_s":300},"health":{"every_s":60},"server":{"port":7370,"allowed_host":null,"probe_timeout_s":10},"events":{"hook_id":4101}})
}
fn link(numbers: &[u64]) -> Value {
    json!({"nodes":numbers.iter().map(|n|json!({"id":format!("syn-issue-{n}"),"number":n,"state":"OPEN","title":format!("Synthetic ticket {n}"),"url":format!("https://example.invalid/issues/{n}")})).collect::<Vec<_>>(),"totalCount":numbers.len()})
}
fn issues() -> Value {
    json!([
        {"blockedBy":link(&[]),"body":"Synthetic graph","id":"syn-issue-9","labels":[],"milestone":null,"number":9,"state":"OPEN","subIssues":link(&[10,11]),"title":"Synthetic graph"},
        {"blockedBy":link(&[]),"body":"**Owned paths:** `crates/example/one.rs`\n**Relies on:** nothing","id":"syn-issue-10","labels":[{"id":"syn-label-ready","name":"ready-for-agent","description":"Synthetic","color":"ffffff"}],"milestone":null,"number":10,"state":"OPEN","subIssues":link(&[]),"title":"Synthetic ticket 10"},
        {"blockedBy":link(&[10]),"body":"**Owned paths:** `crates/example/two.rs`\n**Relies on:** nothing","id":"syn-issue-11","labels":[{"id":"syn-label-ready","name":"ready-for-agent","description":"Synthetic","color":"ffffff"}],"milestone":null,"number":11,"state":"OPEN","subIssues":link(&[]),"title":"Synthetic ticket 11"}
    ])
}
fn prs() -> Value {
    json!([{"title":"Synthetic PR","baseRefName":"main","closingIssuesReferences":[{"id":"syn-issue-10","number":10,"repository":{"id":"syn-repo","name":"synthetic-repo","owner":{"id":"syn-owner","login":"synthetic-owner"}},"url":"https://github.invalid/synthetic-owner/synthetic-repo/issues/10"}],"headRefName":"synthetic-branch-10","headRefOid":HEAD,"isDraft":false,"mergeCommit":null,"mergedAt":null,"number":110,"state":"OPEN"}])
}
fn comments() -> Value {
    let row = |id, issue, body| json!({"id":id,"issue_url":format!("https://github.invalid/api/v3/repos/{REPOSITORY}/issues/{issue}"),"body":body,"created":1_793_400_010_000_u64,"updated":1_793_400_010_000_u64});
    json!([
        row(5100, 9, include_str!("fixtures/t4-completion-approval.md")),
        row(5101, 10, "launch-fleet: started"),
        row(
            5102,
            10,
            "launch-fleet: start checked, branch synthetic-branch-10"
        )
    ])
}
fn metadata() -> Value {
    json!({"id":6101,"guid":"delivery-syn-composition","delivered_at":"2026-01-01T00:00:00Z","redelivery":false,"duration":0.27,"status":"OK","status_code":200,"event":"workflow_run","action":"completed","installation_id":2002,"repository_id":3001,"throttled_at":null})
}
fn detail() -> Value {
    let mut value = metadata();
    value["url"] = json!("https://synthetic.invalid/withheld");
    value["request"] = json!({"headers":{},"payload":{"repository":{"full_name":REPOSITORY},"workflow_run":{"pull_requests":[{"number":110}]}}});
    value["response"] = json!({"headers":{},"payload":"ok"});
    value
}
fn github_response(
    args: &[&str],
    fail: bool,
) -> Result<Vec<u8>, openwiz_core::source::SourceError> {
    let value = match args {
        [
            "api",
            "repos/{owner}/{repo}/hooks/4101/deliveries?per_page=100",
        ] => json!([metadata()]),
        ["api", "repos/{owner}/{repo}/hooks/4101/deliveries/6101"] => detail(),
        ["repo", "view", "--json", "nameWithOwner,isPrivate"] => {
            json!({"nameWithOwner":REPOSITORY,"isPrivate":false})
        }
        ["repo", "view", ..] => {
            json!({"nameWithOwner":REPOSITORY,"url":format!("https://github.invalid/{REPOSITORY}"),"defaultBranchRef":{"name":"main"}})
        }
        ["issue", "list", ..] => issues(),
        ["pr", "list", ..] => prs(),
        ["pr", "view", ..] => {
            let mut pr = prs()[0].clone();
            pr.as_object_mut().unwrap().remove("title");
            pr
        }
        ["pr", "checks", ..] => {
            json!([{"bucket":"fail","name":"ci"},{"bucket":"pass","name":"web-test"},{"bucket":"pass","name":"web-build"}])
        }
        ["api", path, ..] if path.starts_with("repos/{owner}/{repo}/git/ref/heads/") => {
            json!({"sha":BASE})
        }
        ["api", path, ..]
            if path.starts_with("repos/{owner}/{repo}/contents/docs/agents/fleet.md") =>
        {
            return Ok(include_bytes!("../../docs/agents/fleet.md").to_vec());
        }
        ["api", path, ..] if path.starts_with("repos/{owner}/{repo}/issues/comments?") => {
            comments()
        }
        ["api", path, ..]
            if path.starts_with("repos/{owner}/{repo}/issues/") && path.contains("/comments?") =>
        {
            json!([])
        }
        ["api", path, ..] if path.starts_with("repos/{owner}/{repo}/commits/") => {
            json!({"sha":HEAD,"subject":"Synthetic green"})
        }
        ["api", path, "--paginate", "--jq", jq]
            if path.starts_with("repos/{owner}/{repo}/actions/runs?") && *jq == RUNS =>
        {
            if fail {
                return Err(openwiz_core::source::SourceError::Unavailable {
                    detail: "synthetic CI failure".into(),
                });
            }
            json!({"total_count":1,"runs":[{"id":110,"head_sha":HEAD,"event":"pull_request","run_attempt":1,"updated":1_793_400_010_000_u64,"prs":[{"number":110,"head":HEAD,"base":BASE}]}]})
        }
        ["api", path, "--paginate", "--jq", jq]
            if path.starts_with("repos/{owner}/{repo}/actions/runs/110/jobs?") && *jq == JOBS =>
        {
            json!({"total_count":3,"jobs": ([("ci","failure"),("web-test","success"),("web-build","success")].iter().enumerate().map(|(i,(name,result))|json!({"id":1100+i,"name":name,"status":"completed","conclusion":result,"head_sha":HEAD,"run_id":110})).collect::<Vec<_>>())})
        }
        _ => panic!("unplanned GitHub command: {args:?}"),
    };
    Ok(value.to_string().into_bytes())
}
fn quoted(path: &Path) -> String {
    format!("'{}'", path.to_str().unwrap().replace('\'', "'\\''"))
}
fn room(root: &Path) -> CloudRoomSource {
    let mut thread: Value = serde_json::from_str(include_str!(
        "../fixtures/room-cli-v127/new-thread/thread-show-active.json"
    ))
    .unwrap();
    thread["thread"]["title"] = json!("#10: Synthetic ticket 10");
    thread["thread"]["status"] = json!("idle");
    thread["thread"]["queuedWork"] = json!("none");
    thread["thread"]["hasPendingInteraction"] = json!(false);
    fs::write(root.join("thread.json"), thread.to_string()).unwrap();
    fs::write(
        root.join("list.json"),
        json!([thread["thread"]]).to_string(),
    )
    .unwrap();
    fs::write(root.join("projects.json"),json!([{"id":"prj_syn_0001","name":"Synthetic","gitRemoteUrl":format!("https://github.com/{REPOSITORY}.git")}]).to_string()).unwrap();
    let program = root.join("room-cli");
    let script = format!(
        r#"#!/bin/sh
umask 077
fixture_root={root}
printf '%s\0' "$@" > "$fixture_root/call-$$"
case "$1 $2" in
  '--version ') printf 'v127\n' ;;
  'project list') /bin/cat "$fixture_root/projects.json" ;;
  'thread list') /bin/cat "$fixture_root/list.json" ;;
  'thread show') /bin/cat "$fixture_root/thread.json" ;;
  'thread output') printf '{{"output":"","error":null}}' ;;
  'cloud thread-workspace') printf '{{"branch":"synthetic-branch-10","head":"{head}","path":"/synthetic/workspace"}}' ;;
  'thread tell') printf '{{"threadId":"thr_syn_0021","ok":true,"delivery":"sent","mode":"queue"}}' ;;
  *) exit 99 ;;
esac
"#,
        root = quoted(root),
        head = HEAD
    );
    // The writer is a reaped child, so no unrelated fork inherits a writable
    // executable and creates an ETXTBSY race with the fixture reader.
    let status = std::process::Command::new("/bin/sh")
        .args(["-c", "printf '%s' \"$2\" > \"$1\"", "sh"])
        .arg(&program)
        .arg(script)
        .status()
        .unwrap();
    assert!(status.success());
    fs::set_permissions(&program, fs::Permissions::from_mode(0o700)).unwrap();
    CloudRoomSource::new(program)
}
fn calls(root: &Path) -> Vec<Vec<String>> {
    fs::read_dir(root)
        .unwrap()
        .filter_map(|e| {
            let e = e.unwrap();
            if !e.file_name().to_str().unwrap().starts_with("call-") {
                return None;
            }
            let bytes = fs::read(e.path()).unwrap();
            Some(
                bytes
                    .split(|b| *b == 0)
                    .filter(|v| !v.is_empty())
                    .map(|v| String::from_utf8(v.to_vec()).unwrap())
                    .collect(),
            )
        })
        .collect()
}

#[test]
fn lp3b_production_composition_reads_current_world_and_sends_once() {
    for case in [
        "owned",
        "wrong-project",
        "wrong-repository",
        "unread-ci",
        "unknown-owner",
    ] {
        let fixture = Fixture::new();
        let log = Arc::new(Mutex::new(vec![]));
        let trace = Arc::clone(&log);
        let mut configured = config();
        if case == "wrong-project" {
            configured["project"] = json!("prj_syn_other");
        }
        if case == "wrong-repository" {
            configured["repository"] = json!({"owner":"synthetic-other","name":"project"});
        }
        let github = Executor::supplied(Arc::new(move |call, _| {
            trace.lock().unwrap().push(call.argv().to_vec());
            let args = call.argv().iter().map(String::as_str).collect::<Vec<_>>();
            if case == "wrong-repository"
                && args == ["api", "repos/{owner}/{repo}/hooks/4101/deliveries/6101"]
            {
                let mut delivery = detail();
                delivery["request"]["payload"]["repository"]["full_name"] =
                    json!("synthetic-other/project");
                return Ok(delivery.to_string().into_bytes());
            }
            github_response(&args, case == "unread-ci")
        }));
        let room = room(&fixture.0);
        if case == "unknown-owner" {
            fs::write(fixture.0.join("list.json"), "[]").unwrap();
        }
        let mut scheduler = Scheduler::default();
        assert!(
            intake::register_with_sources(
                &fixture.0,
                &configured,
                &mut scheduler,
                Sources { github, room },
                Arc::new(Time)
            )
            .unwrap()
        );
        for at in [10, 20] {
            assert_eq!(scheduler.poll(at).unwrap(), [intake::JOB]);
            scheduler.wait(intake::JOB).unwrap();
        }
        let sends = calls(&fixture.0)
            .into_iter()
            .filter(|args| args.get(1).is_some_and(|v| v == "tell"))
            .collect::<Vec<_>>();
        assert_eq!(
            sends.len(),
            usize::from(case == "owned"),
            "{case}; GitHub: {:?}",
            log.lock().unwrap()
        );
        if case == "owned" {
            assert_eq!(&sends[0][..3], ["thread", "tell", "thr_syn_0021"]);
            assert!(
                sends[0]
                    .last()
                    .unwrap()
                    .contains("CI failed for pull request #110")
            );
        }
        let log = log.lock().unwrap();
        assert_eq!(
            log.iter()
                .filter(|a| a[1] == "repos/{owner}/{repo}/hooks/4101/deliveries/6101")
                .count(),
            1,
            "{case}"
        );
        assert_eq!(
            log.iter()
                .filter(|a| a[0] == "issue" && a[1] == "list")
                .count(),
            1,
            "{case}: must reach fresh World before refusing"
        );
        // The supplied gh source panics on any unplanned call, including writes.
    }
}

#[test]
fn lp3b_production_registration_is_lazy_and_missing_app_key_cannot_fall_back() {
    let fixture = Fixture::new();
    let mut scheduler = Scheduler::default();
    let mut absent = config();
    absent.as_object_mut().unwrap().remove("events");
    assert!(!intake::register(&fixture.0, &absent, &mut scheduler).unwrap());
    assert!(scheduler.poll(9).unwrap().is_empty());
    assert!(intake::register(&fixture.0, &config(), &mut scheduler).unwrap());
    assert!(!fixture.0.join("events").exists());
    assert_eq!(scheduler.poll(19).unwrap(), [intake::JOB]);
    scheduler.wait(intake::JOB).unwrap();
    assert!(!fixture.0.join("events").exists());
    assert!(!fixture.0.join("sends").exists());
}

#[cfg(target_os = "linux")]
#[path = "l4b_auth.rs"]
mod auth;
