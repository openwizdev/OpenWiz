//! A6 (ClosedWiz#114): the CloudRoom reads behind the chain
//! (`openwiz_adapter_cloudroom::fleet`), on the fake `room-cli` and inline
//! synthetic answers. Fixture tests only.
//!
//! - **Only allowlisted reads run,** each once, in order: `--version`,
//!   `project list --json --include-personal`, `thread list --json
//!   --include-hidden`, then
//!   `cloud thread-workspace <id> --json` for each listed Cloud thread. A
//!   thread id that could become a flag is never passed. The fake's own
//!   copy of the allowlist takes exactly that one new form.
//! - **The readers are strict:** a table of good and bad answers for each
//!   read, with the gap each bad one gets. A key given twice, a positional
//!   array, a tagged object, a missing or extra key or a wrong type fails
//!   the read; nothing is guessed.
//! - **A failed read says so in OpenWiz's words,** never `room-cli`'s; a
//!   read the deadline leaves no time for is not made, and is failed with
//!   `budget_exhausted`.

use std::fs;
use std::fs::DirBuilder;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use openwiz_adapter_cloudroom::allowlist::{Invocation, ThreadId};
use openwiz_adapter_cloudroom::fleet::{
    self, NOT_READ_NO_PROJECTS, Reads, Repository, parse_projects, parse_threads, parse_workspace,
};
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_core::envelope::GapKind;
use openwiz_core::fleet::model::{Failed, ListOutcome, NonEmpty, Outcome, Project, Thread};
use serde_json::{Value, json};

fn ne(s: &str) -> NonEmpty {
    NonEmpty::new(s).expect("not empty")
}

fn failed(gap: GapKind, reason: &str) -> Failed {
    Failed {
        gap,
        reason: ne(reason),
    }
}

fn repo() -> Repository {
    Repository::parse("synthetic-owner/synthetic-repo").expect("a repository")
}

const HEAD: &str = "0123456789abcdef0123456789abcdef01234567";

#[test]
fn cloudroom_read_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 6] = [
        (
            "a_repository_is_exactly_owner_and_name",
            a_repository_is_exactly_owner_and_name,
        ),
        (
            "only_this_repositorys_remote_names_it",
            only_this_repositorys_remote_names_it,
        ),
        (
            "the_new_invocation_is_exactly_its_approved_form",
            the_new_invocation_is_exactly_its_approved_form,
        ),
        (
            "the_project_reader_keeps_this_repositorys_projects_strictly",
            the_project_reader_keeps_this_repositorys_projects_strictly,
        ),
        (
            "the_thread_reader_keeps_these_projects_threads_strictly",
            the_thread_reader_keeps_these_projects_threads_strictly,
        ),
        (
            "the_workspace_reader_takes_only_its_exact_shape",
            the_workspace_reader_takes_only_its_exact_shape,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: a6_agents::reads::{name}");
        proof();
    }
}

fn the_new_invocation_is_exactly_its_approved_form() {
    let id = ThreadId::parse("thr_syn_0001").expect("an id");
    assert_eq!(
        Invocation::CloudThreadWorkspace(id).argv(),
        ["cloud", "thread-workspace", "thr_syn_0001", "--json"]
    );
}

fn the_workspace_reader_takes_only_its_exact_shape() {
    let good = [
        (
            json!({"branch": "room/syn-a6-0941", "head": HEAD, "path": "/synthetic/work"}),
            "room/syn-a6-0941",
        ),
        (
            json!({"path": "/synthetic/work", "head": HEAD, "branch": "room/syn-a6-0942"}),
            "room/syn-a6-0942",
        ),
    ];
    for (answer, branch) in good {
        let text = format!("\n {answer} \n");
        assert_eq!(parse_workspace(text.as_bytes()), Ok(ne(branch)), "{text}");
    }

    let not_json = failed(
        GapKind::Malformed,
        "room-cli cloud thread-workspace printed something that is not JSON",
    );
    let twice = failed(
        GapKind::Malformed,
        "room-cli cloud thread-workspace gave a key twice",
    );
    let not_object = failed(
        GapKind::WrongType,
        "room-cli cloud thread-workspace: a workspace is not a JSON object",
    );
    let missing = |key: &str| {
        failed(
            GapKind::MissingField,
            &format!("room-cli cloud thread-workspace: a workspace has no {key}"),
        )
    };
    let wrong = |key: &str| {
        failed(
            GapKind::WrongType,
            &format!("room-cli cloud thread-workspace: a workspace's {key} has an unexpected type"),
        )
    };
    let unknown_key = failed(
        GapKind::Malformed,
        "room-cli cloud thread-workspace printed a key OpenWiz doesn't know",
    );
    let bad: Vec<(String, Failed)> = vec![
        (String::new(), not_json.clone()),
        ("room/syn-a6-0941".to_owned(), not_json.clone()),
        (
            format!(r#"{{"branch": "room/syn-a6-0941", "head": "{HEAD}", "path": "/synthetic/work""#),
            not_json.clone(),
        ),
        (
            format!(
                r#"{{"branch": "room/syn-x", "branch": "room/syn-a6-0941", "head": "{HEAD}", "path": "/synthetic/work"}}"#
            ),
            twice.clone(),
        ),
        (
            format!(
                r#"{{"branch": "room/syn-a6-0941", "head": "{HEAD}", "path": "/synthetic/work", "extra": {{"a": 1, "a": 2}}}}"#
            ),
            twice,
        ),
        (
            format!(r#"["room/syn-a6-0941", "{HEAD}", "/synthetic/work"]"#),
            not_object.clone(),
        ),
        (r#""room/syn-a6-0941""#.to_owned(), not_object.clone()),
        ("null".to_owned(), not_object),
        (
            json!({"head": HEAD, "path": "/synthetic/work"}).to_string(),
            missing("branch"),
        ),
        (
            json!({"branch": "room/syn-a6-0941", "path": "/synthetic/work"}).to_string(),
            missing("head"),
        ),
        (
            json!({"branch": "room/syn-a6-0941", "head": HEAD}).to_string(),
            missing("path"),
        ),
        (json!({}).to_string(), missing("head")),
        (
            json!({"branch": "room/syn-a6-0941", "head": HEAD, "path": "/synthetic/work", "pullRequest": null}).to_string(),
            unknown_key,
        ),
        (
            json!({"branch": 941, "head": HEAD, "path": "/synthetic/work"}).to_string(),
            wrong("branch"),
        ),
        (
            json!({"branch": null, "head": HEAD, "path": "/synthetic/work"}).to_string(),
            wrong("branch"),
        ),
        (
            json!({"branch": {"room/syn-a6-0941": null}, "head": HEAD, "path": "/synthetic/work"})
                .to_string(),
            wrong("branch"),
        ),
        (
            json!({"branch": ["room/syn-a6-0941"], "head": HEAD, "path": "/synthetic/work"})
                .to_string(),
            wrong("branch"),
        ),
        (
            json!({"branch": true, "head": HEAD, "path": "/synthetic/work"}).to_string(),
            wrong("branch"),
        ),
        (
            json!({"branch": "room/syn-a6-0941", "head": 1, "path": "/synthetic/work"}).to_string(),
            wrong("head"),
        ),
        (
            json!({"branch": "room/syn-a6-0941", "head": HEAD, "path": null}).to_string(),
            wrong("path"),
        ),
        (
            json!({"branch": "", "head": HEAD, "path": "/synthetic/work"}).to_string(),
            failed(
                GapKind::Malformed,
                "room-cli cloud thread-workspace: a workspace's branch is empty",
            ),
        ),
    ];
    for (answer, want) in bad {
        assert_eq!(parse_workspace(answer.as_bytes()), Err(want), "{answer}");
    }
}

fn a_repository_is_exactly_owner_and_name() {
    for good in [
        "synthetic-owner/synthetic-repo",
        "Synthetic_Owner/synthetic.repo-1",
        "o/n",
    ] {
        assert!(Repository::parse(good).is_some(), "{good}");
    }
    for bad in [
        "",
        "synthetic-repo",
        "synthetic-owner/",
        "/synthetic-repo",
        "synthetic-owner/synthetic-repo/x",
        "synthetic-owner/..",
        "./synthetic-repo",
        "synthetic owner/synthetic-repo",
        "synthetic-owner/synthetic-repo\n",
        "synthétique/synthetic-repo",
        "synthetic-owner:synthetic-repo",
    ] {
        assert!(Repository::parse(bad).is_none(), "{bad:?}");
    }
    let long = format!("{}/n", "o".repeat(101));
    assert!(Repository::parse(&long).is_none());
}

fn only_this_repositorys_remote_names_it() {
    let repo = repo();
    for remote in [
        "https://github.com/synthetic-owner/synthetic-repo",
        "https://github.com/synthetic-owner/synthetic-repo.git",
        "ssh://git@github.com/synthetic-owner/synthetic-repo.git",
        "git@github.com:synthetic-owner/synthetic-repo.git",
        "git@github.com:synthetic-owner/synthetic-repo",
        "https://github.com/Synthetic-Owner/Synthetic-Repo",
    ] {
        assert!(repo.is_remote(remote), "{remote}");
    }
    for remote in [
        "",
        "https://github.com/synthetic-owner/synthetic-repo-2",
        "https://github.com/synthetic-owner/synthetic-rep",
        "https://github.com/other-owner/synthetic-repo",
        "https://github.com/synthetic-owner/synthetic-repo/",
        "https://github.com/synthetic-owner/synthetic-repo.git.git",
        "https://github.com/synthetic-owner/synthetic-repo ",
        " https://github.com/synthetic-owner/synthetic-repo",
        "http://github.com/synthetic-owner/synthetic-repo",
        "https://gitlab.example.invalid/synthetic-owner/synthetic-repo",
        "https://github.com.example.invalid/synthetic-owner/synthetic-repo",
        "https://user@github.com/synthetic-owner/synthetic-repo",
        "https://github.com/synthetic-owner/synthetic-repo/tree/main",
        "git@github.com:/synthetic-owner/synthetic-repo",
        "synthetic-owner/synthetic-repo",
        "/synthetic/path/synthetic-repo",
    ] {
        assert!(!repo.is_remote(remote), "{remote:?}");
    }
}

fn project(id: &str, name: &str) -> Project {
    Project {
        id: ne(id),
        name: name.to_owned(),
    }
}

fn project_row(id: &str, remote: Option<&str>) -> Value {
    json!({
        "id": id,
        "kind": "standard",
        "name": format!("Synthetic {id}"),
        "gitRemoteUrl": remote,
        "createdAt": 1_793_000_000_000_i64,
        "updatedAt": 1_793_000_000_000_i64,
        "sources": []
    })
}

const OURS: &str = "https://github.com/synthetic-owner/synthetic-repo";

fn the_project_reader_keeps_this_repositorys_projects_strictly() {
    let rows = json!([
        project_row("prj_syn_0001", Some(OURS)),
        project_row("prj_syn_0002", Some("https://github.com/synthetic-owner/other-repo")),
        project_row("prj_syn_0003", None),
        project_row("prj_syn_0004", Some("git@github.com:synthetic-owner/synthetic-repo.git")),
        // Not this repository's, so its fields aren't read.
        {"gitRemoteUrl": null, "id": 4, "name": null},
    ]);
    assert_eq!(
        parse_projects(rows.to_string().as_bytes(), &repo()),
        Ok(vec![
            project("prj_syn_0001", "Synthetic prj_syn_0001"),
            project("prj_syn_0004", "Synthetic prj_syn_0004"),
        ])
    );
    assert_eq!(parse_projects(b"[]", &repo()), Ok(vec![]));

    let read = "room-cli project list";
    let bad: Vec<(String, Failed)> = vec![
        (
            "not json".to_owned(),
            failed(
                GapKind::Malformed,
                &format!("{read} printed something that is not JSON"),
            ),
        ),
        (
            json!({"projects": []}).to_string(),
            failed(
                GapKind::WrongType,
                &format!("{read} printed something that is not a JSON list"),
            ),
        ),
        (
            json!([["prj_syn_0001", "Synthetic", OURS]]).to_string(),
            failed(
                GapKind::WrongType,
                &format!("{read}: a project is not a JSON object"),
            ),
        ),
        (
            json!([{"id": "prj_syn_0001", "name": "Synthetic"}]).to_string(),
            failed(
                GapKind::MissingField,
                &format!("{read}: a project has no gitRemoteUrl"),
            ),
        ),
        (
            json!([{"id": "prj_syn_0001", "name": "Synthetic", "gitRemoteUrl": 1}]).to_string(),
            failed(
                GapKind::WrongType,
                &format!("{read}: a project's gitRemoteUrl has an unexpected type"),
            ),
        ),
        (
            json!([{"id": "prj_syn_0001", "name": "Synthetic", "gitRemoteUrl": {"url": OURS}}])
                .to_string(),
            failed(
                GapKind::WrongType,
                &format!("{read}: a project's gitRemoteUrl has an unexpected type"),
            ),
        ),
        (
            json!([{"name": "Synthetic", "gitRemoteUrl": OURS}]).to_string(),
            failed(
                GapKind::MissingField,
                &format!("{read}: a project has no id"),
            ),
        ),
        (
            json!([{"id": 1, "name": "Synthetic", "gitRemoteUrl": OURS}]).to_string(),
            failed(
                GapKind::WrongType,
                &format!("{read}: a project's id has an unexpected type"),
            ),
        ),
        (
            json!([{"id": "", "name": "Synthetic", "gitRemoteUrl": OURS}]).to_string(),
            failed(
                GapKind::Malformed,
                &format!("{read}: a project's id is empty"),
            ),
        ),
        (
            json!([{"id": "prj_syn_0001", "gitRemoteUrl": OURS}]).to_string(),
            failed(
                GapKind::MissingField,
                &format!("{read}: a project has no name"),
            ),
        ),
        (
            json!([
                project_row("prj_syn_0001", Some(OURS)),
                project_row("prj_syn_0001", Some(OURS))
            ])
            .to_string(),
            failed(
                GapKind::Malformed,
                &format!("{read} listed one of this repository's projects twice"),
            ),
        ),
        (
            // A key given twice, even in a project that isn't this
            // repository's, refuses the whole list.
            format!(
                r#"[{{"id": "prj_syn_0001", "name": "Synthetic", "gitRemoteUrl": "{OURS}"}}, {{"id": "prj_syn_0002", "name": "Synthetic", "gitRemoteUrl": null, "gitRemoteUrl": "{OURS}"}}]"#
            ),
            failed(GapKind::Malformed, &format!("{read} gave a key twice")),
        ),
    ];
    for (answer, want) in bad {
        assert_eq!(
            parse_projects(answer.as_bytes(), &repo()),
            Err(want),
            "{answer}"
        );
    }
}

fn cloud_row(id: &str, project: &str) -> Value {
    json!({
        "id": id,
        "projectId": project,
        "title": "Synthetic thread",
        "archivedAt": null,
        "executionTarget": "cloud",
        "environmentHostId": null,
        "environmentBranchName": null
    })
}

fn local_row(id: &str, project: &str, branch: Option<&str>) -> Value {
    json!({
        "id": id,
        "projectId": project,
        "title": "Synthetic thread",
        "archivedAt": null,
        "environmentHostId": "host_syn_0001",
        "environmentBranchName": branch
    })
}

fn ours() -> Vec<Project> {
    vec![
        project("prj_syn_0001", "Synthetic one"),
        project("prj_syn_0002", "Synthetic two"),
    ]
}

fn cloud(id: &str, project: &str) -> Thread {
    Thread::Cloud {
        thread: ne(id),
        project: ne(project),
    }
}

fn local(id: &str, project: &str, branch: Option<&str>) -> Thread {
    Thread::Local {
        thread: ne(id),
        project: ne(project),
        branch: branch.map(ne),
    }
}

fn the_thread_reader_keeps_these_projects_threads_strictly() {
    let mut archived = cloud_row("thr_syn_0005", "prj_syn_0001");
    archived["archivedAt"] = json!(1_793_000_000_000_i64);
    let rows = json!([
        cloud_row("thr_syn_0001", "prj_syn_0001"),
        local_row("thr_syn_0002", "prj_syn_0002", Some("room/syn-local-0002")),
        local_row("thr_syn_0003", "prj_syn_0001", None),
        archived,
        cloud_row("thr_syn_0006", "prj_syn_0099"),
        // Another project's, so nothing else of it is read.
        {"projectId": "prj_syn_0099", "id": 6, "executionTarget": "elsewhere"},
    ]);
    assert_eq!(
        parse_threads(rows.to_string().as_bytes(), &ours()),
        Ok(vec![
            cloud("thr_syn_0001", "prj_syn_0001"),
            local("thr_syn_0002", "prj_syn_0002", Some("room/syn-local-0002")),
            local("thr_syn_0003", "prj_syn_0001", None),
        ])
    );

    let read = "room-cli thread list";
    let with = |key: &str, value: Value| {
        let mut row = cloud_row("thr_syn_0001", "prj_syn_0001");
        row[key] = value;
        json!([row]).to_string()
    };
    let without = |row: Value, key: &str| {
        let mut row = row;
        row.as_object_mut().expect("a row").remove(key);
        json!([row]).to_string()
    };
    let local_with = |key: &str, value: Value| {
        let mut row = local_row("thr_syn_0001", "prj_syn_0001", Some("room/syn-local"));
        row[key] = value;
        json!([row]).to_string()
    };
    let wrong = |key: &str| {
        failed(
            GapKind::WrongType,
            &format!("{read}: a thread's {key} has an unexpected type"),
        )
    };
    let missing = |key: &str| {
        failed(
            GapKind::MissingField,
            &format!("{read}: a thread has no {key}"),
        )
    };
    let unsafe_id = failed(
        GapKind::Malformed,
        &format!("{read}: a thread id is not safe to pass to room-cli"),
    );
    let neither = failed(
        GapKind::MissingField,
        &format!("{read}: a thread has no executionTarget and no environmentHostId"),
    );
    let bad: Vec<(String, Failed)> = vec![
        (
            "[{".to_owned(),
            failed(GapKind::Malformed, &format!("{read} printed something that is not JSON")),
        ),
        (
            json!({"threads": []}).to_string(),
            failed(GapKind::WrongType, &format!("{read} printed something that is not a JSON list")),
        ),
        (
            json!([["thr_syn_0001", "prj_syn_0001", "cloud"]]).to_string(),
            failed(GapKind::WrongType, &format!("{read}: a thread is not a JSON object")),
        ),
        (
            without(cloud_row("thr_syn_0001", "prj_syn_0001"), "projectId"),
            missing("projectId"),
        ),
        (with("projectId", json!(1)), wrong("projectId")),
        (with("projectId", Value::Null), wrong("projectId")),
        (without(cloud_row("thr_syn_0001", "prj_syn_0001"), "id"), missing("id")),
        (with("id", json!(1)), wrong("id")),
        (
            with("id", json!("")),
            failed(GapKind::Malformed, &format!("{read}: a thread's id is empty")),
        ),
        (with("id", json!("--work-status")), unsafe_id.clone()),
        (with("id", json!("thr syn 0001")), unsafe_id.clone()),
        (with("id", json!("thr_syn_0001;x")), unsafe_id),
        (
            without(cloud_row("thr_syn_0001", "prj_syn_0001"), "archivedAt"),
            missing("archivedAt"),
        ),
        (with("archivedAt", json!("yesterday")), wrong("archivedAt")),
        (with("archivedAt", json!(1.5)), wrong("archivedAt")),
        (with("archivedAt", json!(false)), wrong("archivedAt")),
        (
            with("executionTarget", json!("local")),
            failed(
                GapKind::Malformed,
                &format!("{read}: a thread's executionTarget is not one OpenWiz knows"),
            ),
        ),
        (
            with("executionTarget", json!("Cloud")),
            failed(
                GapKind::Malformed,
                &format!("{read}: a thread's executionTarget is not one OpenWiz knows"),
            ),
        ),
        (with("executionTarget", Value::Null), wrong("executionTarget")),
        (
            with("executionTarget", json!({"cloud": null})),
            wrong("executionTarget"),
        ),
        (local_with("environmentHostId", Value::Null), neither.clone()),
        (
            without(
                local_row("thr_syn_0001", "prj_syn_0001", None),
                "environmentHostId",
            ),
            neither,
        ),
        (local_with("environmentHostId", json!(5)), wrong("environmentHostId")),
        (
            without(
                local_row("thr_syn_0001", "prj_syn_0001", None),
                "environmentBranchName",
            ),
            missing("environmentBranchName"),
        ),
        (
            local_with("environmentBranchName", json!("")),
            failed(
                GapKind::Malformed,
                &format!("{read}: a thread's environmentBranchName is empty"),
            ),
        ),
        (
            local_with("environmentBranchName", json!(5)),
            wrong("environmentBranchName"),
        ),
        (
            local_with("environmentBranchName", json!(["room/syn-local"])),
            wrong("environmentBranchName"),
        ),
        (
            json!([
                cloud_row("thr_syn_0001", "prj_syn_0001"),
                local_row("thr_syn_0001", "prj_syn_0002", None)
            ])
            .to_string(),
            failed(GapKind::Malformed, &format!("{read} listed one thread twice")),
        ),
        (
            r#"[{"id": "thr_syn_0001", "projectId": "prj_syn_0099", "projectId": "prj_syn_0001", "archivedAt": null, "executionTarget": "cloud"}]"#
                .to_owned(),
            failed(GapKind::Malformed, &format!("{read} gave a key twice")),
        ),
    ];
    for (answer, want) in bad {
        assert_eq!(
            parse_threads(answer.as_bytes(), &ours()),
            Err(want),
            "{answer}"
        );
    }
}

// The reads end to end, on the fake `room-cli`.

/// A private directory with the fake `room-cli` and one scenario, written
/// here: `responses`, each `{"argv": [...], "stdout"?, "stderr"?, "exit"?,
/// "hang"?}`.
struct Fake {
    dir: PathBuf,
}

impl Fake {
    fn new(test: &str, responses: Value) -> Self {
        let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join("a6").join(test);
        let _ = fs::remove_dir_all(&dir);
        DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(&dir)
            .expect("create the fake's directory");
        std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-room-cli"), dir.join("room-cli"))
            .expect("link the fake room-cli");
        let scenario = dir.join("scenario.json");
        fs::write(
            &scenario,
            json!({"scenario": test, "responses": responses}).to_string(),
        )
        .expect("write the scenario");
        fs::write(
            dir.join("fake-room-cli.scenario"),
            scenario.to_str().expect("a UTF-8 path"),
        )
        .expect("write the scenario pointer");
        Self { dir }
    }

    fn source(&self) -> CloudRoomSource {
        CloudRoomSource::new(self.dir.join("room-cli"))
    }

    /// Every argument list the fake received, in order.
    fn calls(&self) -> Vec<Vec<String>> {
        let Ok(text) = fs::read_to_string(self.dir.join("invocations.log")) else {
            return vec![];
        };
        text.lines()
            .map(|l| serde_json::from_str(l).expect("a JSON list"))
            .collect()
    }
}

fn answer(argv: &[&str], stdout: &Value) -> Value {
    json!({"argv": argv, "stdout": stdout.to_string()})
}

fn workspace_answer(id: &str, branch: &str) -> Value {
    answer(
        &["cloud", "thread-workspace", id, "--json"],
        &json!({"branch": branch, "head": HEAD, "path": "/synthetic/work"}),
    )
}

fn soon() -> Instant {
    Instant::now() + Duration::from_secs(10)
}

const VERSION: &[&str] = &["--version"];
const PROJECT_LIST: &[&str] = &["project", "list", "--json", "--include-personal"];
/// Hidden threads too: the contract leaves out only archived ones
/// (orchestrator, #114, 2026-11-01: "(a)").
const THREAD_LIST: &[&str] = &["thread", "list", "--json", "--include-hidden"];

fn words(calls: &[&[&str]]) -> Vec<Vec<String>> {
    calls
        .iter()
        .map(|c| c.iter().map(|w| (*w).to_owned()).collect())
        .collect()
}

#[test]
fn every_read_runs_once_in_order_and_only_from_the_allowlist() {
    let mut archived = cloud_row("thr_syn_0013", "prj_syn_0001");
    archived["archivedAt"] = json!(1_793_000_000_000_i64);
    // A hidden thread is one of the projects' threads: it is read.
    let mut hidden = cloud_row("thr_syn_0016", "prj_syn_0001");
    hidden["visibility"] = json!("hidden");
    let fake = Fake::new(
        "every_read_runs_once",
        json!([
            {"argv": VERSION, "stdout": "v132\n"},
            answer(
                PROJECT_LIST,
                &json!([
                    project_row("prj_syn_0001", Some(OURS)),
                    project_row("prj_syn_0002", Some("https://github.com/synthetic-owner/other-repo"))
                ])
            ),
            answer(
                THREAD_LIST,
                &json!([
                    cloud_row("thr_syn_0011", "prj_syn_0001"),
                    local_row("thr_syn_0012", "prj_syn_0001", Some("room/syn-local-0012")),
                    archived,
                    cloud_row("thr_syn_0014", "prj_syn_0002"),
                    cloud_row("thr_syn_0015", "prj_syn_0001"),
                    hidden
                ])
            ),
            workspace_answer("thr_syn_0011", "room/syn-a6-0011"),
            workspace_answer("thr_syn_0015", "room/syn-a6-0015"),
            workspace_answer("thr_syn_0016", "room/syn-a6-0016")
        ]),
    );
    let reads = fleet::read(&fake.source(), &repo(), soon());
    assert_eq!(
        reads,
        Reads {
            version: Outcome::Complete { value: ne("v132") },
            projects: ListOutcome::Complete {
                value: vec![project("prj_syn_0001", "Synthetic prj_syn_0001")]
            },
            threads: ListOutcome::Complete {
                value: vec![
                    cloud("thr_syn_0011", "prj_syn_0001"),
                    local("thr_syn_0012", "prj_syn_0001", Some("room/syn-local-0012")),
                    cloud("thr_syn_0015", "prj_syn_0001"),
                    cloud("thr_syn_0016", "prj_syn_0001"),
                ]
            },
            workspaces: vec![
                (
                    ne("thr_syn_0011"),
                    Outcome::Complete {
                        value: ne("room/syn-a6-0011")
                    }
                ),
                (
                    ne("thr_syn_0015"),
                    Outcome::Complete {
                        value: ne("room/syn-a6-0015")
                    }
                ),
                (
                    ne("thr_syn_0016"),
                    Outcome::Complete {
                        value: ne("room/syn-a6-0016")
                    }
                ),
            ],
        }
    );
    assert_eq!(
        fake.calls(),
        words(&[
            VERSION,
            PROJECT_LIST,
            THREAD_LIST,
            &["cloud", "thread-workspace", "thr_syn_0011", "--json"],
            &["cloud", "thread-workspace", "thr_syn_0015", "--json"],
            &["cloud", "thread-workspace", "thr_syn_0016", "--json"],
        ])
    );
}

#[test]
fn a_failed_workspace_read_says_so_in_openwizs_words() {
    let fake = Fake::new(
        "a_failed_workspace_read",
        json!([
            {
                "argv": ["cloud", "thread-workspace", "thr_syn_0021", "--json"],
                "stdout": "{\"branch\": \"room/syn-secret-0021\"",
                "stderr": "Error: HTTP 500: Synthetic secret detail at /synthetic/home/token",
                "exit": 1
            },
            {
                "argv": ["cloud", "thread-workspace", "thr_syn_0022", "--json"],
                "stdout": "{\"branch\": \"room/syn-a6\", \"head\": 7, \"path\": \"/synthetic/workspace/secret\"}"
            }
        ]),
    );
    let source = fake.source();
    assert_eq!(
        fleet::workspace(&source, &ne("thr_syn_0021"), soon()),
        Outcome::Failed(failed(
            GapKind::CommandFailed,
            "room-cli cloud thread-workspace exited 1"
        ))
    );
    assert_eq!(
        fleet::workspace(&source, &ne("thr_syn_0022"), soon()),
        Outcome::Failed(failed(
            GapKind::WrongType,
            "room-cli cloud thread-workspace: a workspace's head has an unexpected type"
        ))
    );
    // A thread with no answer: the fake's "no fixture", exit 98.
    assert_eq!(
        fleet::workspace(&source, &ne("thr_syn_0023"), soon()),
        Outcome::Failed(failed(
            GapKind::CommandFailed,
            "room-cli cloud thread-workspace exited 98"
        ))
    );
}

#[test]
fn a_thread_id_that_could_become_a_flag_is_never_passed() {
    let fake = Fake::new("a_thread_id_never_passed", json!([]));
    for id in [
        "--work-status",
        "-x",
        "thr syn",
        "thr_syn_0001 --git-diff",
        "thr/../x",
    ] {
        assert_eq!(
            fleet::workspace(&fake.source(), &ne(id), soon()),
            Outcome::Failed(failed(
                GapKind::Malformed,
                "not read: the thread id is not safe to pass to room-cli"
            )),
            "{id}"
        );
    }
    assert_eq!(fake.calls(), Vec::<Vec<String>>::new());
}

#[test]
fn a_read_the_deadline_leaves_no_time_for_is_not_made() {
    let fake = Fake::new(
        "the_deadline_passed",
        json!([{"argv": VERSION, "stdout": "v132\n"}]),
    );
    let gone = Instant::now();
    let budget = || failed(GapKind::BudgetExhausted, "not read: budget");
    assert_eq!(
        fleet::read(&fake.source(), &repo(), gone),
        Reads {
            version: Outcome::Failed(budget()),
            projects: ListOutcome::Failed(budget()),
            threads: ListOutcome::Failed(failed(GapKind::BudgetExhausted, NOT_READ_NO_PROJECTS)),
            workspaces: vec![],
        }
    );
    assert_eq!(
        fleet::workspace(&fake.source(), &ne("thr_syn_0031"), gone),
        Outcome::Failed(budget())
    );
    assert_eq!(fake.calls(), Vec::<Vec<String>>::new());
}

#[test]
fn a_hung_read_is_stopped_at_the_deadline() {
    let fake = Fake::new(
        "a_hung_read",
        json!([{"argv": ["cloud", "thread-workspace", "thr_syn_0041", "--json"], "hang": true}]),
    );
    let outcome = fleet::workspace(
        &fake.source(),
        &ne("thr_syn_0041"),
        // P4's budget: long enough that the fake has started and written
        // its pid before it is stopped (helper auditor 1, item 3).
        Instant::now() + Duration::from_secs(2),
    );
    let Outcome::Failed(Failed { gap, reason }) = outcome else {
        panic!("a hung read is not complete");
    };
    assert_eq!(gap, GapKind::TimedOut);
    assert!(
        reason
            .as_str()
            .starts_with("room-cli cloud thread-workspace timed out after "),
        "{reason:?}"
    );
    let pid = fs::read_to_string(fake.dir.join("hang.pid")).expect("the fake hung");
    assert!(
        !Path::new("/proc").join(pid.trim()).exists(),
        "the hung fake was stopped and reaped"
    );
}

#[test]
fn when_the_projects_fail_or_are_none_no_thread_is_read() {
    // The project list failed: its threads can't be told, so the thread
    // list isn't run, and no branch is read.
    let fake = Fake::new(
        "the_projects_failed",
        json!([
            {"argv": VERSION, "stdout": "v132\n"},
            {"argv": PROJECT_LIST, "stderr": "Error: HTTP 503", "exit": 1}
        ]),
    );
    let reads = fleet::read(&fake.source(), &repo(), soon());
    assert_eq!(
        reads.projects,
        ListOutcome::Failed(failed(
            GapKind::CommandFailed,
            "room-cli project list exited 1"
        ))
    );
    assert_eq!(
        reads.threads,
        ListOutcome::Failed(failed(GapKind::BudgetExhausted, NOT_READ_NO_PROJECTS))
    );
    assert_eq!(reads.workspaces, vec![]);
    assert_eq!(fake.calls(), words(&[VERSION, PROJECT_LIST]));

    // No project has this repository's remote: it has no threads, and the
    // thread list isn't run.
    let fake = Fake::new(
        "no_project_is_ours",
        json!([
            {"argv": VERSION, "stdout": "v132\n"},
            answer(PROJECT_LIST, &json!([project_row("prj_syn_0002", None)]))
        ]),
    );
    let reads = fleet::read(&fake.source(), &repo(), soon());
    assert_eq!(reads.projects, ListOutcome::Complete { value: vec![] });
    assert_eq!(reads.threads, ListOutcome::Complete { value: vec![] });
    assert_eq!(fake.calls(), words(&[VERSION, PROJECT_LIST]));
}

#[test]
fn a_version_is_reported_and_an_unrecognised_one_withheld() {
    let fake = Fake::new(
        "the_version",
        json!([{"argv": VERSION, "stdout": "synthetic-version /synthetic/home\n"}]),
    );
    assert_eq!(
        fleet::version(&fake.source(), soon()),
        Outcome::Failed(failed(
            GapKind::UntestedVersion,
            "room-cli --version printed a version that is not N.N.N or v<N> (detail withheld)"
        ))
    );
    let fake = Fake::new(
        "the_version_v999",
        json!([{"argv": VERSION, "stdout": "v999\n"}]),
    );
    assert_eq!(
        fleet::version(&fake.source(), soon()),
        Outcome::Complete { value: ne("v999") }
    );
}

#[test]
fn safe_bundle_failure_categories_survive_version_sanitizing() {
    use openwiz_adapter_cloudroom::locate::LocateError;
    use openwiz_core::model::Fact;
    use openwiz_core::ops::version_fact;
    use openwiz_core::source::SourceError;

    for (error, category) in [
        (LocateError::NotRunning, "no bundle"),
        (LocateError::NoRunningApp, "no running app identified"),
        (LocateError::Ambiguous, "ambiguous bundle"),
        (LocateError::UnexpectedFile, "unexpected bundle"),
        (LocateError::Unreadable, "unreadable bundle"),
    ] {
        assert_eq!(
            version_fact("room-cli --version", "0.43.1", Err(error.into())),
            (
                Fact::Unknown(format!("room-cli --version could not be run ({category})")),
                false
            )
        );
    }
    // An allowlisted phrase embedded in private/OS text is not allowlisted.
    for detail in [
        "/synthetic/private/path: no bundled launcher",
        "CloudRoom not running: room-cli could not be started (no bundled launcher) /synthetic/private",
        "CloudRoom not running: room-cli could not be started (no running app identified) /synthetic/private",
        "waiting for room-cli failed (PermissionDenied)",
        "room-cli could not be started (NotFound)",
    ] {
        assert_eq!(
            version_fact(
                "room-cli --version",
                "0.43.1",
                Err(SourceError::Unavailable {
                    detail: detail.to_owned()
                })
            ),
            (
                Fact::Unknown("room-cli --version could not be run (detail withheld)".to_owned()),
                false
            )
        );
    }
}

#[test]
fn executable_start_failure_is_safe_in_fleet_read_records() {
    use openwiz_core::fleet::model::{Read, ReadId, ReadKind, SourceName};
    let fake = Fake::new("missing_launcher_category", json!([]));
    let source = CloudRoomSource::new(fake.dir.join("missing-private-launcher"));
    let reads = fleet::read(&source, &repo(), soon());
    assert_eq!(
        reads.version,
        Outcome::Failed(failed(
            GapKind::UntestedVersion,
            "room-cli --version could not be run (executable could not start)"
        ))
    );
    assert_eq!(
        reads.projects,
        ListOutcome::Failed(failed(
            GapKind::CommandFailed,
            "room-cli project list could not be run (executable could not start)"
        ))
    );
    assert_eq!(
        reads.threads,
        ListOutcome::Failed(failed(GapKind::BudgetExhausted, NOT_READ_NO_PROJECTS))
    );
    assert_eq!(reads.workspaces, vec![]);
    assert_eq!(fake.calls(), Vec::<Vec<String>>::new());
    let schema = crate::a6_agents::sub_schema("#/$defs/read");
    for (index, kind) in [
        ReadKind::Version {
            source: SourceName::Cloudroom,
            outcome: reads.version,
        },
        ReadKind::Projects {
            outcome: reads.projects,
        },
        ReadKind::Threads {
            outcome: reads.threads,
        },
    ]
    .into_iter()
    .enumerate()
    {
        let value = serde_json::to_value(Read {
            id: ReadId(u32::try_from(index).unwrap() + 1),
            kind,
        })
        .unwrap();
        assert_eq!(
            crate::schema::validate(&schema, &value),
            Vec::<String>::new()
        );
        let text = value.to_string();
        for secret in [
            fake.dir.to_str().unwrap(),
            "PermissionDenied",
            "NotFound",
            "pid",
            "missing-private-launcher",
        ] {
            assert!(!text.contains(secret), "{text}");
        }
    }
}

#[test]
fn discovery_failure_categories_survive_to_fleet_json() {
    for category in [
        "no bundle",
        "no running app identified",
        "ambiguous bundle",
        "unexpected bundle",
        "unreadable bundle",
    ] {
        // One configured discovery per process, as in the real entrypoint.
        let out = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "a6_agents::reads::discovery_failure_fixture",
                "--nocapture",
            ])
            .env("OPENWIZ_T1010_FAILURE_CASE", category)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{category}: {} {}",
            String::from_utf8_lossy(&out.stdout),
            String::from_utf8_lossy(&out.stderr)
        );
    }
}

#[test]
fn discovery_failure_fixture() {
    use openwiz_adapter_cloudroom::locate::{self, Discovery, LauncherMetadata};
    use openwiz_core::fleet::{
        agents,
        model::{Read, ReadId, ReadKind, SourceName},
    };
    use std::os::unix::fs::{MetadataExt, PermissionsExt};
    let Ok(category) = std::env::var("OPENWIZ_T1010_FAILURE_CASE") else {
        return;
    };
    let fake = Fake::new(
        &format!("launch-category-{}", category.replace(' ', "-")),
        json!([]),
    );
    let root = fake.dir.join("bundles");
    let proc = fake.dir.join("proc");
    let launcher_calls = fake.dir.join("unexpected-launcher-call");
    let make_private = |path: &Path| {
        DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(path)
            .unwrap();
    };
    make_private(&root);
    make_private(&proc);
    if category != "unreadable bundle" {
        make_private(&proc.join("self"));
    }
    if matches!(
        category.as_str(),
        "ambiguous bundle" | "unexpected bundle" | "no running app identified"
    ) {
        let mounts = if category == "unexpected bundle" {
            1
        } else {
            2
        };
        for index in 1..=mounts {
            let mount = root.join(format!(".mount_synthetic_{index}"));
            let dist =
                mount.join("resources/app.asar.unpacked/node_modules/bb-app/host-daemon/dist");
            make_private(&dist);
            let launcher = dist.join("room-cli");
            let prefix = if category == "unexpected bundle" {
                "#!/bin/bash"
            } else {
                "#!/bin/sh"
            };
            fs::write(
                &launcher,
                format!(
                    "{prefix}\n\":\" //; printf called > '{}'\nexit 97\n",
                    launcher_calls.display()
                ),
            )
            .unwrap();
            fs::set_permissions(&launcher, fs::Permissions::from_mode(0o755)).unwrap();
            for sibling in ["index.js", "daemon-bundle.mjs"] {
                fs::write(dist.join(sibling), "synthetic").unwrap();
            }
            if category == "no running app identified" {
                continue; // Mounted, valid bundles, with no process evidence.
            }
            let app = mount.join("synthetic-app");
            fs::write(&app, "synthetic executable, never run").unwrap();
            fs::set_permissions(&app, fs::Permissions::from_mode(0o755)).unwrap();
            let process = proc.join(format!("10{index}"));
            make_private(&process);
            std::os::unix::fs::symlink(app, process.join("exe")).unwrap();
        }
    }
    locate::install(
        Discovery::pc(root, |m| LauncherMetadata {
            uid: 0,
            mode: m.mode(),
        })
        .with_process_root(proc),
    )
    .unwrap();
    let got = fleet::read(&CloudRoomSource::from_path(), &repo(), soon());
    assert_eq!(
        got.version,
        Outcome::Failed(failed(
            GapKind::UntestedVersion,
            &format!("room-cli --version could not be run ({category})")
        ))
    );
    assert_eq!(
        got.projects,
        ListOutcome::Failed(failed(
            GapKind::CommandFailed,
            &format!("room-cli project list could not be run ({category})")
        ))
    );
    assert_eq!(
        got.threads,
        ListOutcome::Failed(failed(GapKind::BudgetExhausted, NOT_READ_NO_PROJECTS))
    );
    assert!(got.workspaces.is_empty());
    assert!(fake.calls().is_empty());
    assert!(!launcher_calls.exists(), "a refused launcher was executed");

    let mut records = super::two_tickets().reads();
    records.retain(|read| !matches!(read.kind, ReadKind::Workspace { .. }));
    for record in &mut records {
        match &mut record.kind {
            ReadKind::Projects { outcome } => *outcome = got.projects.clone(),
            ReadKind::Threads { outcome } => *outcome = got.threads.clone(),
            _ => {}
        }
    }
    records.push(Read {
        id: ReadId(8),
        kind: ReadKind::Version {
            source: SourceName::Cloudroom,
            outcome: got.version,
        },
    });
    let placements = agents::place(super::n(super::SPEC), &records).unwrap();
    for ticket in [941, 942] {
        assert_eq!(
            super::printed(&placements.builder(super::n(ticket))),
            json!({"unread": ["r4", "r5"]})
        );
    }
    assert_eq!(
        super::unplaced(&placements),
        json!({"unread": ["r4", "r5"]})
    );
    let schema = crate::a6_agents::sub_schema("#/$defs/read");
    for record in &records {
        let value = serde_json::to_value(record).unwrap();
        assert_eq!(
            crate::schema::validate(&schema, &value),
            Vec::<String>::new()
        );
    }
    let text = serde_json::to_string(&records).unwrap();
    for secret in [
        fake.dir.to_str().unwrap(),
        "synthetic-app",
        "should not execute",
        "PermissionDenied",
        "NotFound",
        "101",
        "102",
    ] {
        assert!(!text.contains(secret), "{text}");
    }
}

#[test]
fn the_fakes_allowlist_takes_exactly_the_one_new_form() {
    // The fake's own copy of the allowlist, called directly: the new form,
    // and nothing near it.
    let fake = Fake::new(
        "the_fakes_allowlist",
        json!([workspace_answer("thr_syn_0051", "room/syn-a6-0051")]),
    );
    let run = |args: &[&str]| {
        std::process::Command::new(fake.dir.join("room-cli"))
            .args(args)
            .output()
            .expect("run the fake")
            .status
            .code()
    };
    assert_eq!(
        run(&["cloud", "thread-workspace", "thr_syn_0051", "--json"]),
        Some(0)
    );
    for refused in [
        &["cloud", "thread-workspace", "thr_syn_0051"][..],
        &["cloud", "thread-workspace", "--json"],
        &["cloud", "thread-workspace", "-x", "--json"],
        &["cloud", "thread-workspace", "--json", "thr_syn_0051"],
        &[
            "cloud",
            "thread-workspace",
            "thr_syn_0051",
            "--json",
            "--work-status",
        ],
        &["cloud", "thread-workspaces", "thr_syn_0051", "--json"],
        &["cloud", "workspace", "thr_syn_0051", "--json"],
        &["thread", "workspace", "thr_syn_0051", "--json"],
    ] {
        assert_eq!(run(refused), Some(97), "{refused:?}");
    }
}

#[test]
fn every_read_record_the_adapter_gives_matches_the_schema() {
    use openwiz_core::fleet::model::{Read, ReadId, ReadKind, SourceName};
    let schema = crate::a6_agents::sub_schema("#/$defs/read");
    // A planted bad record: the sub-schema really checks.
    for bad in [
        json!({"id": "r1", "kind": "workspace", "thread": "thr_syn_0001", "outcome": {"state": "complete", "value": ""}}),
        json!({"id": "r1", "kind": "threads", "outcome": {"state": "complete", "value": [{"thread": "thr_syn_0001", "project": "prj_syn_0001", "kind": "local"}]}}),
        json!({"id": "r1", "kind": "projects", "outcome": {"state": "failed", "gap": "not_ours", "reason": "synthetic"}}),
    ] {
        assert!(!crate::schema::validate(&schema, &bad).is_empty(), "{bad}");
    }

    // Complete reads, then failed ones of every kind the adapter gives.
    let mut runs: Vec<Reads> = Vec::new();
    let complete = Fake::new(
        "schema_complete",
        json!([
            {"argv": VERSION, "stdout": "v132\n"},
            answer(PROJECT_LIST, &json!([project_row("prj_syn_0001", Some(OURS))])),
            answer(
                THREAD_LIST,
                &json!([
                    cloud_row("thr_syn_0061", "prj_syn_0001"),
                    local_row("thr_syn_0062", "prj_syn_0001", Some("room/syn-local-0062")),
                    local_row("thr_syn_0063", "prj_syn_0001", None)
                ])
            ),
            workspace_answer("thr_syn_0061", "room/syn-a6-0061")
        ]),
    );
    runs.push(fleet::read(&complete.source(), &repo(), soon()));
    let failing = Fake::new(
        "schema_failing",
        json!([
            {"argv": VERSION, "stdout": "not a version\n"},
            answer(PROJECT_LIST, &json!([project_row("prj_syn_0001", Some(OURS))])),
            {"argv": THREAD_LIST, "stdout": "[{\"id\": 1}]"},
        ]),
    );
    runs.push(fleet::read(&failing.source(), &repo(), soon()));
    let broken_branch = Fake::new(
        "schema_broken_branch",
        json!([
            {"argv": VERSION, "exit": 2},
            answer(PROJECT_LIST, &json!([project_row("prj_syn_0001", Some(OURS))])),
            answer(THREAD_LIST, &json!([cloud_row("thr_syn_0064", "prj_syn_0001")])),
            {"argv": ["cloud", "thread-workspace", "thr_syn_0064", "--json"], "stdout": "{}"}
        ]),
    );
    runs.push(fleet::read(&broken_branch.source(), &repo(), soon()));
    runs.push(fleet::read(
        &broken_branch.source(),
        &repo(),
        Instant::now(),
    ));

    let mut checked = 0;
    for run in runs {
        let mut kinds = vec![
            ReadKind::Version {
                source: SourceName::Cloudroom,
                outcome: run.version,
            },
            ReadKind::Projects {
                outcome: run.projects,
            },
            ReadKind::Threads {
                outcome: run.threads,
            },
        ];
        for (thread, outcome) in run.workspaces {
            kinds.push(ReadKind::Workspace { thread, outcome });
        }
        for (i, kind) in kinds.into_iter().enumerate() {
            let record = Read {
                id: ReadId(u32::try_from(i).expect("few") + 1),
                kind,
            };
            let value = serde_json::to_value(&record).expect("prints");
            assert_eq!(
                crate::schema::validate(&schema, &value),
                Vec::<String>::new(),
                "{value}"
            );
            checked += 1;
        }
    }
    assert_eq!(checked, 4 + 3 + 4 + 3);
}
