//! The shared server dispatch configures the fleet sources on recording fakes.
//!
//! #267 CI red run: after merging main's C3 proof, `cargo test -p
//! openwiz-tests --test web-api c3_server_program_matches_the_cli_agent_chain`
//! exited 101: the fleet coverage was "partial", expected "complete".
//! The helper supplied room-cli only on PATH, which is no longer its seam.
use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::thread::{self, JoinHandle};
use std::time::Duration;

use crate::{http, support};
use serde_json::{Value, json};
use std::fs;

struct Process {
    child: Child,
    reader: Option<JoinHandle<()>>,
}

/// 2141: a settings-root error cannot turn into cwd discovery. Existing
/// in-process pair tests always supplied a settings path successfully.
#[test]
fn c3_decisions_unread_settings_root_never_falls_back_to_cwd() {
    let gh = support::world_fake(
        "c3-decisions-unread-root",
        &support::world::World::default(),
    );
    let room = crate::fake::Fake::new("c3-decisions-unread-root", "normal");
    let path = format!("{}:{}", gh.dir.display(), std::env::var("PATH").unwrap());
    let mut child = Command::new(http::server_binary())
        .args(["--port", "0"])
        .env("PATH", path)
        .env("OPENWIZ_FIXTURE_PROGRAM", room.program())
        .env("OPENWIZ_STATE_DIR", "relative-synthetic-state")
        .env_remove("OPENWIZ_SERVER_ALLOWED_HOST")
        .env_remove("OPENWIZ_ORCHESTRATOR_THREAD_ID")
        .current_dir(&gh.dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let stderr = child.stderr.take().unwrap();
    let (tx, rx) = mpsc::channel();
    let reader = thread::spawn(move || {
        for line in BufReader::new(stderr).lines() {
            if tx.send(line.unwrap()).is_err() {
                break;
            }
        }
    });
    let process = Process {
        child,
        reader: Some(reader),
    };
    let start = rx.recv_timeout(Duration::from_secs(10)).unwrap();
    let address = start
        .strip_prefix("openwiz-server: listening on http://")
        .unwrap()
        .split_whitespace()
        .next()
        .unwrap()
        .parse()
        .unwrap();
    let response = http::get(address, "/api/v1/decisions");
    assert_eq!(response.status, 200);
    let value: Value = serde_json::from_slice(&response.body).unwrap();
    assert_eq!(value["coverage"]["state"], "partial");
    assert_eq!(value["items"], json!([]));
    crate::e11_decisions_support::check(&value);
    let line = rx.recv_timeout(Duration::from_secs(10)).unwrap();
    assert!(line.starts_with("openwiz-server: GET /api/v1/decisions 200 "));
    drop(process);
    assert!(
        gh.invocations().is_empty(),
        "an unread root must not read cwd"
    );
    assert!(room.invocations().is_empty());
}
impl Drop for Process {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        if let Some(reader) = self.reader.take() {
            reader.join().unwrap();
        }
    }
}

#[test]
fn c3_server_program_matches_the_cli_agent_chain() {
    let fake = support::world_fake(
        "c3-server-binary",
        &support::world::World::default()
            .spec(901, &[902])
            .issue(
                902,
                support::world::IssueW::ticket("Synthetic builder").closed_by(&[952]),
            )
            .pr(952, support::world::PrW::open(&[902], 'a')),
    );
    std::os::unix::fs::symlink(
        env!("CARGO_BIN_EXE_fake-room-cli"),
        fake.dir.join("room-cli"),
    )
    .unwrap();
    let room_scenario = fake.dir.join("room-scenario.json");
    let rows = vec![
        json!({"argv": ["--version"], "stdout": "0.43.1\n"}),
        json!({"argv": ["project", "list", "--json", "--include-personal"], "stdout": json!([
            {"id": "prj_syn_0001", "name": "Synthetic project", "gitRemoteUrl": "https://github.com/synthetic-owner/example-repo.git"}
        ]).to_string()}),
        json!({"argv": ["thread", "list", "--json", "--include-hidden"], "stdout": json!([
            {"id": "thr_syn_0001", "projectId": "prj_syn_0001", "archivedAt": null, "executionTarget": "cloud"}
        ]).to_string()}),
        json!({"argv": ["cloud", "thread-workspace", "thr_syn_0001", "--json"], "stdout": json!({
            "branch": "room/syn-902", "head": "a".repeat(40), "path": "/synthetic/workspace"
        }).to_string()}),
    ];
    fs::write(&room_scenario, json!({"synthetic_assumptions": ["Synthetic A6 shapes, as #372's fixture tests."], "responses": rows}).to_string()).unwrap();
    fs::write(
        fake.dir.join("fake-room-cli.scenario"),
        room_scenario.to_str().unwrap(),
    )
    .unwrap();
    let path = format!("{}:{}", fake.dir.display(), std::env::var("PATH").unwrap());
    let mut child = Command::new(http::server_binary())
        .args(["--port", "0"])
        .env("PATH", &path)
        .env("OPENWIZ_FIXTURE_PROGRAM", fake.dir.join("room-cli"))
        .env_remove("OPENWIZ_SERVER_ALLOWED_HOST")
        // A configured target adds its own room-cli reads (#2814).
        .env_remove("OPENWIZ_ORCHESTRATOR_THREAD_ID")
        .env("OPENWIZ_STATE_DIR", fake.dir.join("unused-state"))
        .current_dir(&fake.dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let stderr = child.stderr.take().unwrap();
    let (tx, rx) = mpsc::channel();
    let reader = thread::spawn(move || {
        for line in BufReader::new(stderr).lines() {
            if tx.send(line.unwrap()).is_err() {
                break;
            }
        }
    });
    let _process = Process {
        child,
        reader: Some(reader),
    };
    let start = rx.recv_timeout(Duration::from_secs(10)).unwrap();
    let address = start
        .strip_prefix("openwiz-server: listening on http://")
        .unwrap()
        .split_whitespace()
        .next()
        .unwrap()
        .parse()
        .unwrap();
    let mut detail = Value::Null;
    for (path, view) in [
        ("/api/v1/fleets", "fleets"),
        ("/api/v1/fleets/901", "fleet"),
    ] {
        let r = http::get(address, path);
        assert_eq!(r.status, 200, "{}", r.text());
        let value: Value = serde_json::from_slice(&r.body).unwrap();
        assert_eq!(value["data"]["view"], view);
        if view == "fleet" {
            assert_eq!(value["coverage"]["state"], "complete");
            assert_eq!(
                value["data"]["tickets"][0]["builder"],
                json!({"known": "thr_syn_0001"})
            );
        }
        crate::c3_routes::headers(&r);
        assert!(
            support::fleet_schema::validate(&support::fleet_schema::load_schema(), &value)
                .is_empty()
        );
        if view == "fleet" {
            detail = value.clone();
        }
        let line = rx.recv_timeout(Duration::from_secs(10)).unwrap();
        let route = if view == "fleet" {
            "/api/v1/fleets/{spec}"
        } else {
            "/api/v1/fleets"
        };
        assert!(
            line.starts_with(&format!("openwiz-server: GET {route} 200 ")),
            "{line}"
        );
    }
    assert_eq!(
        fake.invocations()
            .iter()
            .filter(|a| a.as_slice() == ["--version"])
            .count(),
        2
    );
    let calls: Vec<Vec<String>> = fs::read_to_string(fake.dir.join("invocations.log"))
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    let expected = vec![
        vec!["--version"],
        vec!["project", "list", "--json", "--include-personal"],
        vec!["thread", "list", "--json", "--include-hidden"],
        vec!["cloud", "thread-workspace", "thr_syn_0001", "--json"],
    ];
    assert_eq!(calls, expected);
    // The production CLI has its own private adapter glue. Compare that
    // too, normalizing only the wall-clock snapshot that cannot be shared.
    let output = Command::new(support::openwiz_release())
        .args(["fleet", "901", "--json"])
        .env("PATH", &path)
        .env("OPENWIZ_FIXTURE_PROGRAM", fake.dir.join("room-cli"))
        .current_dir(&fake.dir)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    let mut cli: Value = serde_json::from_slice(&output.stdout).unwrap();
    cli["freshness"]["snapshot_at"] = detail["freshness"]["snapshot_at"].clone();
    assert_eq!(detail, cli, "production server and CLI agree on every fact");
    assert!(!fake.dir.join("unused-state").exists(), "no state writes");
}
