//! #372: the production CLI joins both adapters, on synthetic fakes only.

use super::{Command, fakes_on_path, left_behind, openwiz_release, world};

use std::fs;
use std::path::Path;

use serde_json::{Value, json};

use crate::schema;
use world::{IssueW, PrW, World, answer, argv};

const PROJECTS: &[&str] = &["project", "list", "--json", "--include-personal"];
const THREADS: &[&str] = &["thread", "list", "--json", "--include-hidden"];
const WORKSPACE1: &[&str] = &["cloud", "thread-workspace", "thr_syn_0001", "--json"];
const WORKSPACE2: &[&str] = &["cloud", "thread-workspace", "thr_syn_0002", "--json"];

fn world() -> World {
    World::default()
        .spec(1, &[2, 4])
        .issue(2, IssueW::ticket("Synthetic first").closed_by(&[3]))
        .pr(3, PrW::open(&[2], 'a'))
        .issue(4, IssueW::ticket("Synthetic second").closed_by(&[5]))
        .pr(5, PrW::open(&[4], 'b'))
}

fn room_answers() -> Vec<Value> {
    let answer = |args: &[&str], value: Value| json!({"argv": args, "stdout": value.to_string()});
    vec![
        json!({"argv": ["--version"], "stdout": "0.43.1\n"}),
        answer(
            PROJECTS,
            json!([{
                "id": "prj_syn_0001", "name": "Synthetic project",
                "gitRemoteUrl": "https://github.com/synthetic-owner/example-repo.git"
            }]),
        ),
        answer(
            THREADS,
            json!([
                {"id": "thr_syn_0001", "projectId": "prj_syn_0001", "archivedAt": null, "executionTarget": "cloud"},
                {"id": "thr_syn_0002", "projectId": "prj_syn_0001", "archivedAt": null, "executionTarget": "cloud"}
            ]),
        ),
        answer(
            WORKSPACE1,
            json!({"branch": "room/syn-2", "head": world::oid('a'), "path": "/synthetic/first"}),
        ),
        answer(
            WORKSPACE2,
            json!({"branch": "room/syn-4", "head": world::oid('b'), "path": "/synthetic/second"}),
        ),
    ]
}

fn assert_repository_read_error(stdout: &[u8]) {
    assert!(stdout.ends_with(b"\n"));
    let doc: Value = serde_json::from_slice(stdout).expect("one whole-stream CLI error document");
    let contract: Value =
        serde_json::from_str(include_str!("../../contracts/cli.v1.schema.json")).unwrap();
    assert_eq!(
        schema::validate(&contract, &doc),
        Vec::<String>::new(),
        "{doc}"
    );
    assert_eq!(doc["schema"], "openwiz.cli-error.v1");
    assert_eq!(doc["command"], "fleet");
    assert_eq!(doc["exit_code"], 1);
    assert_eq!(doc["error"]["kind"], "read_failed");
}

fn run(
    test: &str,
    world: &World,
    answers: Vec<Value>,
    json_output: bool,
    expected_exit: i32,
) -> (Value, Vec<Vec<String>>, Vec<String>) {
    let (dir, path) = fakes_on_path(test);
    for (tool, scenario) in [
        ("gh", world.scenario()),
        (
            "room-cli",
            json!({"synthetic_assumptions": ["All projects, threads, branches and paths are synthetic."], "responses": answers}),
        ),
    ] {
        let file = dir.join(format!("{tool}-scenario.json"));
        fs::write(&file, scenario.to_string()).expect("write scenario");
        fs::write(
            dir.join(format!("fake-{tool}.scenario")),
            file.to_str().unwrap(),
        )
        .expect("point fake at scenario");
    }
    let mut command = Command::new(openwiz_release());
    command.args(["fleet", "1"]);
    if json_output {
        command.arg("--json");
    }
    let out = command
        .env("PATH", path)
        .env("OPENWIZ_FIXTURE_PROGRAM", dir.join("room-cli"))
        .current_dir(&dir)
        .output()
        .expect("run CLI");
    assert_eq!(
        out.status.code(),
        Some(expected_exit),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let result = if expected_exit != 0 {
        if json_output {
            assert_repository_read_error(&out.stdout);
        } else {
            assert!(out.stdout.is_empty());
        }
        json!(String::from_utf8(out.stderr).unwrap())
    } else if json_output {
        assert!(out.stderr.is_empty());
        let got: Value = serde_json::from_slice(&out.stdout).expect("JSON envelope");
        assert_eq!(
            schema::validate(&schema::load_schema(), &got),
            Vec::<String>::new()
        );
        got
    } else {
        json!(String::from_utf8(out.stdout).unwrap())
    };
    (result, calls(&dir), left_behind(&dir))
}

fn calls(dir: &Path) -> Vec<Vec<String>> {
    fs::read_to_string(dir.join("invocations.log"))
        .unwrap_or_default()
        .lines()
        .map(|line| serde_json::from_str(line).expect("JSON argv"))
        .collect()
}

fn read<'a>(got: &'a Value, kind: &str) -> &'a Value {
    got["reads"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["kind"] == kind)
        .unwrap()
}

#[test]
fn cli_agents_complete_answers_place_both_builders() {
    let expected_files = [
        "environment.log",
        "fake-gh.scenario",
        "fake-room-cli.scenario",
        "gh-environment.log",
        "gh-invocations.log",
        "gh-scenario.json",
        "invocations.log",
        "room-cli-scenario.json",
    ];
    let (got, calls, left) = run("372-complete", &world(), room_answers(), true, 0);
    assert_eq!(left, expected_files, "fleet left an unexpected file");
    assert_eq!(
        calls,
        [
            argv(&["--version"]),
            argv(PROJECTS),
            argv(THREADS),
            argv(WORKSPACE1),
            argv(WORKSPACE2)
        ]
    );
    assert_eq!(got["coverage"]["state"], "complete");
    assert_eq!(
        got["data"]["tickets"][0]["builder"],
        json!({"known": "thr_syn_0001"})
    );
    assert_eq!(
        got["data"]["tickets"][1]["builder"],
        json!({"known": "thr_syn_0002"})
    );
    assert_eq!(got["data"]["unplaced"], json!({"known": []}));
    let (text, _, left) = run("372-complete-text", &world(), room_answers(), false, 0);
    assert_eq!(left, expected_files, "fleet left an unexpected file");
    let text = text.as_str().unwrap();
    for line in [
        "  builder: thr_syn_0001",
        "  builder: thr_syn_0002",
        "complete: every read was complete",
    ] {
        assert!(text.lines().any(|l| l == line), "{text}");
    }
}

fn conflicting_project_remote(reverse: bool) {
    let matching = json!("https://github.com/synthetic-owner/example-repo.git");
    let other = json!("https://github.com/synthetic-owner/other-repo");
    let remotes = if reverse {
        [other, matching]
    } else {
        [matching, other]
    };
    duplicate_project_rows(&format!("876-conflict-{reverse}"), remotes, true);
}

fn duplicate_project_rows(test: &str, remotes: [Value; 2], selected: bool) {
    let mut answers = room_answers();
    let mut rows: Vec<Value> =
        serde_json::from_str(answers[1]["stdout"].as_str().unwrap()).unwrap();
    let mut duplicate = rows[0].clone();
    if selected {
        rows.clear();
    } else {
        duplicate["id"] = json!("prj_syn_0002");
    }
    for remote in remotes {
        let mut row = duplicate.clone();
        row["gitRemoteUrl"] = remote;
        rows.push(row);
    }
    answers[1]["stdout"] = json!(serde_json::to_string(&rows).unwrap());
    let (got, calls, _) = run(test, &world(), answers, true, 0);
    assert_eq!(got["coverage"]["state"], "partial");
    assert_eq!(read(&got, "projects")["outcome"]["state"], "failed");
    assert_eq!(read(&got, "projects")["outcome"]["gap"], "malformed");
    assert_eq!(read(&got, "threads")["outcome"]["state"], "failed");
    let unread = json!({"unread": [
        read(&got, "projects")["id"], read(&got, "threads")["id"]
    ]});
    assert_eq!(got["data"]["tickets"].as_array().unwrap().len(), 2);
    for ticket in got["data"]["tickets"].as_array().unwrap() {
        assert_eq!(ticket["builder"], unread);
    }
    assert_eq!(got["data"]["unplaced"], unread);
    assert_eq!(calls, [argv(&["--version"]), argv(PROJECTS)]);
}

#[test]
fn cli_agents_conflicting_project_remote_before_matching_makes_placement_unread() {
    conflicting_project_remote(true);
}

#[test]
fn cli_agents_conflicting_project_remote_after_matching_makes_placement_unread() {
    conflicting_project_remote(false);
}

#[test]
fn cli_agents_missing_reads_name_exact_placement_gaps() {
    for (missing, kinds, expected_calls, reasons) in [
        (
            1,
            vec!["projects", "threads"],
            vec![argv(&["--version"]), argv(PROJECTS)],
            vec![
                "room-cli project list exited 98",
                "not read: the projects couldn't be read",
            ],
        ),
        (
            2,
            vec!["threads"],
            vec![argv(&["--version"]), argv(PROJECTS), argv(THREADS)],
            vec!["room-cli thread list exited 98"],
        ),
        (
            3,
            vec!["workspace"],
            vec![
                argv(&["--version"]),
                argv(PROJECTS),
                argv(THREADS),
                argv(WORKSPACE1),
                argv(WORKSPACE2),
            ],
            vec!["room-cli cloud thread-workspace exited 98"],
        ),
    ] {
        let mut answers = room_answers();
        answers.remove(missing);
        let (got, calls, _) = run(
            &format!("372-missing-{missing}"),
            &world(),
            answers,
            true,
            0,
        );
        assert_eq!(calls, expected_calls);
        assert_eq!(got["coverage"]["state"], "partial");
        let ids: Vec<Value> = kinds
            .iter()
            .map(|kind| read(&got, kind)["id"].clone())
            .collect();
        for ticket in got["data"]["tickets"].as_array().unwrap() {
            assert_eq!(ticket["builder"], json!({"unread": ids}));
        }
        assert_eq!(got["data"]["unplaced"], json!({"unread": ids}));
        let failed: Vec<&Value> = got["reads"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|r| r["outcome"]["state"] == "failed")
            .collect();
        assert_eq!(
            failed.iter().map(|r| r["id"].clone()).collect::<Vec<_>>(),
            ids
        );
        assert_eq!(
            failed
                .iter()
                .map(|r| r["outcome"]["reason"].as_str().unwrap())
                .collect::<Vec<_>>(),
            reasons
        );
    }
}

#[test]
fn cli_agents_unread_or_invalid_repository_never_selects_projects() {
    for (name, response) in [
        ("unread", answer("", 1)),
        (
            "invalid",
            answer(
                &json!({"nameWithOwner": "synthetic owner/example-repo", "url": world::REPO_URL})
                    .to_string(),
                0,
            ),
        ),
    ] {
        let world = world().answer(
            &argv(&["repo", "view", "--json", "nameWithOwner,url"]),
            response,
        );
        let (got, calls, _) = run(
            &format!("372-repository-{name}"),
            &world,
            room_answers(),
            true,
            if name == "unread" { 1 } else { 0 },
        );
        assert_eq!(calls, [argv(&["--version"])]);
        if name == "unread" {
            assert!(
                got.as_str()
                    .unwrap()
                    .contains("this repository couldn't be read")
            );
            continue;
        }
        assert_eq!(got["coverage"]["state"], "partial");
        for kind in ["projects", "threads"] {
            assert_eq!(read(&got, kind)["outcome"]["state"], "failed");
        }
        let ids = [
            read(&got, "projects")["id"].clone(),
            read(&got, "threads")["id"].clone(),
        ];
        for ticket in got["data"]["tickets"].as_array().unwrap() {
            assert_eq!(ticket["builder"], json!({"unread": ids}));
        }
        assert_eq!(got["data"]["unplaced"], json!({"unread": ids}));
        assert_eq!(
            read(&got, "projects")["outcome"]["reason"],
            "not read: the repository couldn't be read or identified"
        );
        assert_eq!(
            read(&got, "threads")["outcome"]["reason"],
            "not read: the projects couldn't be read"
        );
    }
}

fn conflicting_archive_states(archived_first: bool) {
    let mut answers = room_answers();
    let mut rows: Vec<Value> =
        serde_json::from_str(answers[2]["stdout"].as_str().unwrap()).unwrap();
    let mut archived = rows[0].clone();
    archived["archivedAt"] = json!(123);
    rows.insert(if archived_first { 0 } else { 2 }, archived);
    answers[2]["stdout"] = json!(serde_json::to_string(&rows).unwrap());
    let (got, calls, _) = run(
        &format!("618-archive-conflict-{archived_first}"),
        &world(),
        answers,
        true,
        0,
    );
    assert_eq!(got["coverage"]["state"], "partial");
    assert_eq!(
        read(&got, "threads")["outcome"],
        json!({"state": "failed", "gap": "malformed", "reason": "room-cli thread list listed one thread twice"})
    );
    let unread = json!({"unread": [read(&got, "threads")["id"]]});
    assert_eq!(got["data"]["tickets"].as_array().unwrap().len(), 2);
    for ticket in got["data"]["tickets"].as_array().unwrap() {
        assert_eq!(ticket["builder"], unread);
    }
    assert_eq!(got["data"]["unplaced"], unread);
    assert_eq!(calls, [argv(&["--version"]), argv(PROJECTS), argv(THREADS)]);
    let incomplete: Vec<_> = got["reads"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|r| r["outcome"]["state"] != "complete")
        .map(|r| r["id"].clone())
        .collect();
    assert_eq!(incomplete, [read(&got, "threads")["id"].clone()]);
}

#[test]
fn cli_agents_archived_duplicate_before_active_makes_placement_unread() {
    conflicting_archive_states(true);
}

#[test]
fn cli_agents_archived_duplicate_after_active_makes_placement_unread() {
    conflicting_archive_states(false);
}

#[test]
fn cli_agents_archived_and_unrelated_rows_preserve_placement() {
    for (name, id, project, index) in [
        ("archived", "thr_syn_0003", "prj_syn_0001", 2),
        ("unrelated-before", "thr_syn_0001", "prj_syn_0099", 0),
        ("unrelated-after", "thr_syn_0001", "prj_syn_0099", 2),
    ] {
        let mut answers = room_answers();
        let mut rows: Vec<Value> =
            serde_json::from_str(answers[2]["stdout"].as_str().unwrap()).unwrap();
        rows.insert(
            index,
            json!({"id": id, "projectId": project, "archivedAt": 123}),
        );
        answers[2]["stdout"] = json!(serde_json::to_string(&rows).unwrap());
        let (got, calls, _) = run(&format!("618-{name}"), &world(), answers, true, 0);
        assert_eq!(got["coverage"]["state"], "complete");
        assert_eq!(got["data"]["tickets"].as_array().unwrap().len(), 2);
        assert_eq!(
            got["data"]["tickets"][0]["builder"],
            json!({"known": "thr_syn_0001"})
        );
        assert_eq!(
            got["data"]["tickets"][1]["builder"],
            json!({"known": "thr_syn_0002"})
        );
        assert_eq!(got["data"]["unplaced"], json!({"known": []}));
        assert_eq!(
            calls,
            [
                argv(&["--version"]),
                argv(PROJECTS),
                argv(THREADS),
                argv(WORKSPACE1),
                argv(WORKSPACE2)
            ]
        );
    }
}

#[test]
fn cli_agents_unique_project_remote_controls_preserve_placement() {
    for remote in [
        json!("https://github.com/synthetic-owner/other-repo"),
        Value::Null,
    ] {
        for index in [0, 1] {
            let mut answers = room_answers();
            let mut rows: Vec<Value> =
                serde_json::from_str(answers[1]["stdout"].as_str().unwrap()).unwrap();
            let mut unrelated = rows[0].clone();
            unrelated["id"] = json!("prj_syn_0002");
            unrelated["gitRemoteUrl"] = remote.clone();
            rows.insert(index, unrelated);
            answers[1]["stdout"] = json!(serde_json::to_string(&rows).unwrap());
            let (got, calls, _) = run(
                &format!("876-unique-{}-{index}", remote.is_null()),
                &world(),
                answers,
                true,
                0,
            );
            assert_eq!(got["coverage"]["state"], "complete");
            assert_eq!(
                read(&got, "projects")["outcome"],
                json!({"state": "complete", "value": [
                    {"id": "prj_syn_0001", "name": "Synthetic project"}
                ]})
            );
            let builders: Vec<_> = got["data"]["tickets"]
                .as_array()
                .unwrap()
                .iter()
                .map(|ticket| ticket["builder"].clone())
                .collect();
            assert_eq!(
                builders,
                [
                    json!({"known": "thr_syn_0001"}),
                    json!({"known": "thr_syn_0002"})
                ]
            );
            assert_eq!(got["data"]["unplaced"], json!({"known": []}));
            assert_eq!(
                calls,
                [
                    argv(&["--version"]),
                    argv(PROJECTS),
                    argv(THREADS),
                    argv(WORKSPACE1),
                    argv(WORKSPACE2)
                ]
            );
        }
    }
}

#[test]
fn cli_agents_duplicate_project_ids_are_refused_before_remote_filtering() {
    let matching = "https://github.com/synthetic-owner/example-repo.git";
    let other = "https://github.com/synthetic-owner/other-repo";
    let third = "https://github.com/synthetic-owner/third-repo";
    for (case, remotes, selected) in [
        ("matching", [Some(matching), Some(matching)], true),
        ("unrelated-same", [Some(other), Some(other)], false),
        ("unrelated-different", [Some(other), Some(third)], false),
        ("null", [None, None], false),
        ("mixed", [Some(other), None], false),
    ] {
        for reverse in [false, true] {
            let mut remotes = remotes.map(|remote| json!(remote));
            if reverse {
                remotes.reverse();
            }
            duplicate_project_rows(&format!("876-{case}-{reverse}"), remotes, selected);
        }
    }
}
