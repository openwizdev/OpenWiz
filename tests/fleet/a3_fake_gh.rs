//! A3 (ClosedWiz#111): the fake `gh`. It records every call exactly,
//! answers only a call its scenario answers with exactly those arguments,
//! answers byte for byte, can hang, can extend a scenario, logs only the
//! names of GitHub variables, and refuses a malformed scenario.
//!
//! Each test writes its own synthetic scenarios in its own directory.

use std::fs;
use std::fs::DirBuilder;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::time::{Duration, Instant};

use serde_json::{Value, json};

use crate::support::FakeGh;

const REFUSED: i32 = 97;
const NO_SCENARIO: i32 = 98;
const BAD_SCENARIO: i32 = 99;

/// Writes `scenario` as `<test>/<name>/scenario.json`, with `files` beside
/// it, and returns its path.
fn scenario(test: &str, name: &str, scenario: &Value, files: &[(&str, &str)]) -> PathBuf {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR"))
        .join("fake-gh-scenarios")
        .join(test)
        .join(name);
    let _ = fs::remove_dir_all(&dir);
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&dir)
        .expect("create the scenario directory");
    for (file, body) in files {
        fs::write(dir.join(file), body).expect("write a scenario file");
    }
    let path = dir.join("scenario.json");
    fs::write(&path, scenario.to_string()).expect("write the scenario");
    path
}

fn run(fake: &FakeGh, args: &[&str]) -> Output {
    Command::new(fake.program())
        .args(args)
        .output()
        .expect("run the fake gh")
}

fn text(output: &Output) -> (Option<i32>, String, String) {
    (
        output.status.code(),
        String::from_utf8_lossy(&output.stdout).into_owned(),
        String::from_utf8_lossy(&output.stderr).into_owned(),
    )
}

/// An exit code, stdout and stderr.
type Answer = (i32, &'static str, &'static str);

fn owned(args: &[&str]) -> Vec<String> {
    args.iter().map(|a| (*a).to_owned()).collect()
}

#[test]
fn it_records_every_call_and_answers_only_exactly_what_its_scenario_answers() {
    let path = scenario(
        "a3_answers",
        "base",
        &json!({
            "scenario": "base",
            "description": "Synthetic answers for the fake's own test.",
            "synthetic_assumptions": ["Every value is synthetic."],
            "responses": [
                {"argv": ["--version"], "stdout": "gh version 0.0.0 (synthetic)\n"},
                {"argv": ["issue", "view", "1", "--json", "title"], "stdout_file": "issue.json"},
                {"argv": ["pr", "view", "2"], "stderr": "synthetic failure\n", "exit": 1},
                {"argv": ["repo", "view"], "stdout": "{}", "delay_ms": 1}
            ]
        }),
        &[("issue.json", "{\"title\":\"Synthetic ticket\"}")],
    );
    let fake = FakeGh::new("a3_answers", &path);
    let calls: &[(&[&str], Answer)] = &[
        (&["--version"], (0, "gh version 0.0.0 (synthetic)\n", "")),
        (
            &["issue", "view", "1", "--json", "title"],
            (0, "{\"title\":\"Synthetic ticket\"}", ""),
        ),
        (&["pr", "view", "2"], (1, "", "synthetic failure\n")),
        (&["repo", "view"], (0, "{}", "")),
    ];
    // Near misses: each is refused, and still recorded.
    let misses: &[&[&str]] = &[
        &[],
        &["--version", "--extra"],
        &["issue", "view", "1"],
        &["issue", "view", "1", "--json", "title", "--jq", ".title"],
        &["Issue", "view", "1", "--json", "title"],
        &["issue", "view", "01", "--json", "title"],
        &["issue", "view", "1", "--json", "title "],
        &["view", "issue", "1", "--json", "title"],
    ];
    let mut expected_log = Vec::new();
    for (args, (code, out, err)) in calls {
        let got = run(&fake, args);
        assert_eq!(
            text(&got),
            (Some(*code), (*out).to_owned(), (*err).to_owned()),
            "{args:?}"
        );
        expected_log.push(owned(args));
    }
    for args in misses {
        let got = run(&fake, args);
        assert_eq!(
            text(&got),
            (
                Some(REFUSED),
                String::new(),
                format!(
                    "fake gh: refused, no scenario response for: {}\n",
                    args.join(" ")
                )
            ),
            "{args:?}"
        );
        expected_log.push(owned(args));
    }
    assert_eq!(
        fake.invocations(),
        expected_log,
        "every call, in order, once"
    );
    assert_eq!(fake.environments().len(), expected_log.len());
}

#[test]
fn it_answers_byte_for_byte() {
    let stdout = "{\"a\":1}\n\n  \u{e9}\ttrailing ";
    let stderr = "first line\nsecond line";
    let path = scenario(
        "a3_bytes",
        "bytes",
        &json!({
            "synthetic_assumptions": [],
            "responses": [{"argv": ["api", "synthetic"], "stdout": stdout, "stderr": stderr}]
        }),
        &[],
    );
    let fake = FakeGh::new("a3_bytes", &path);
    let got = run(&fake, &["api", "synthetic"]);
    assert_eq!(got.status.code(), Some(0));
    assert_eq!(got.stdout, stdout.as_bytes());
    assert_eq!(got.stderr, stderr.as_bytes());
}

#[test]
fn a_scenario_extends_another_and_its_own_responses_come_first() {
    let parent = json!({
        "synthetic_assumptions": [],
        "responses": [
            {"argv": ["--version"], "stdout": "parent version"},
            {"argv": ["repo", "view"], "stdout": "parent repo"}
        ]
    });
    scenario("a3_extends", "parent", &parent, &[]);
    let child = scenario(
        "a3_extends",
        "child",
        &json!({
            "synthetic_assumptions": [],
            "extends": "parent",
            "responses": [{"argv": ["--version"], "stdout": "child version"}]
        }),
        &[],
    );
    let fake = FakeGh::new("a3_extends", &child);
    assert_eq!(text(&run(&fake, &["--version"])).1, "child version");
    assert_eq!(text(&run(&fake, &["repo", "view"])).1, "parent repo");
    assert_eq!(text(&run(&fake, &["pr", "list"])).0, Some(REFUSED));
}

#[test]
fn a_hanging_answer_writes_its_pid_and_never_answers() {
    let path = scenario(
        "a3_hang",
        "hang",
        &json!({
            "synthetic_assumptions": [],
            "responses": [{"argv": ["issue", "list"], "stdout": "never", "hang": true}]
        }),
        &[],
    );
    let fake = FakeGh::new("a3_hang", &path);
    let mut child = Command::new(fake.program())
        .args(["issue", "list"])
        .stdout(Stdio::piped())
        .spawn()
        .expect("start the fake gh");
    let pid = child.id().to_string();
    let limit = Instant::now() + Duration::from_secs(10);
    while fake.hung_pid().as_deref() != Some(pid.as_str()) {
        assert!(Instant::now() < limit, "no gh-hang.pid with {pid}");
        assert!(
            child.try_wait().expect("poll the fake").is_none(),
            "the fake exited instead of hanging"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
    child.kill().expect("stop the fake");
    let output = child.wait_with_output().expect("reap the fake");
    assert!(output.stdout.is_empty(), "a hung call never answers");
    assert_eq!(fake.invocations(), [owned(&["issue", "list"])]);
}

#[test]
fn it_logs_the_names_of_github_variables_never_their_values() {
    let path = scenario(
        "a3_environment",
        "environment",
        &json!({"synthetic_assumptions": [], "responses": [{"argv": ["--version"]}]}),
        &[],
    );
    let fake = FakeGh::new("a3_environment", &path);
    let got = Command::new(fake.program())
        .arg("--version")
        .env_clear()
        .env("GITHUB_SYNTHETIC", "syn-value-1")
        .env("GH_TOKEN", "syn-value-2")
        .env("OTHER_SYNTHETIC", "syn-value-3")
        .env("XGH_SYNTHETIC", "syn-value-4")
        .output()
        .expect("run the fake gh");
    assert_eq!(got.status.code(), Some(0));
    assert_eq!(
        fake.environments(),
        [owned(&["GH_TOKEN", "GITHUB_SYNTHETIC"])]
    );
    let log = fs::read_to_string(fake.dir.join("gh-environment.log")).expect("the log");
    assert!(!log.contains("syn-value"), "a value was logged: {log}");
}

#[test]
fn started_by_name_through_path_it_shares_a_directory_with_the_fake_room_cli() {
    let path = scenario(
        "a3_by_name",
        "by-name",
        &json!({"synthetic_assumptions": [], "responses": [{"argv": ["--version"], "stdout": "syn"}]}),
        &[],
    );
    let fake = FakeGh::new("a3_by_name", &path);
    std::os::unix::fs::symlink(
        env!("CARGO_BIN_EXE_fake-room-cli"),
        fake.dir.join("room-cli"),
    )
    .expect("link the fake room-cli");
    let got = Command::new("gh")
        .arg("--version")
        .env("PATH", &fake.dir)
        .current_dir(&fake.dir)
        .output()
        .expect("run gh by name");
    assert_eq!(text(&got), (Some(0), "syn".to_owned(), String::new()));
    assert_eq!(fake.invocations(), [owned(&["--version"])]);
    let mut files: Vec<String> = fs::read_dir(&fake.dir)
        .expect("read the directory")
        .map(|e| e.expect("entry").file_name().to_string_lossy().into_owned())
        .collect();
    files.sort();
    assert_eq!(
        files,
        [
            "fake-gh.scenario",
            "gh",
            "gh-environment.log",
            "gh-invocations.log",
            "room-cli"
        ],
        "only the fake gh's own files, none of the fake room-cli's"
    );
}

#[test]
fn a_malformed_scenario_stops_the_fake_and_answers_nothing() {
    let ok = json!({"argv": ["--version"], "stdout": "syn"});
    let with = |key: &str, value: Value| {
        let mut response = ok.clone();
        response[key] = value;
        json!({"synthetic_assumptions": [], "responses": [response]})
    };
    let bad: Vec<(&str, Value)> = vec![
        ("not an object", json!(["--version"])),
        (
            "an unknown top-level key",
            json!({"synthetic_assumptions": [], "responses": [ok], "respones": []}),
        ),
        ("no responses", json!({"synthetic_assumptions": []})),
        (
            "responses not a list",
            json!({"synthetic_assumptions": [], "responses": {"argv": ["--version"]}}),
        ),
        ("no synthetic_assumptions", json!({"responses": [ok]})),
        (
            "a synthetic assumption that is not a string",
            json!({"synthetic_assumptions": [1], "responses": [ok]}),
        ),
        (
            "a scenario name that is not a string",
            json!({"scenario": 1, "synthetic_assumptions": [], "responses": [ok]}),
        ),
        ("an unknown response key", with("stdout_fle", json!("x"))),
        (
            "no argv",
            json!({"synthetic_assumptions": [], "responses": [{"stdout": "syn"}]}),
        ),
        ("argv not a list", with("argv", json!("--version"))),
        (
            "argv with a number",
            with("argv", json!(["issue", "view", 1])),
        ),
        ("stdout not a string", with("stdout", json!(1))),
        (
            "both stdout and stdout_file",
            with("stdout_file", json!("x.json")),
        ),
        ("an exit over 255", with("exit", json!(256))),
        ("a negative exit", with("exit", json!(-1))),
        ("an exit as a string", with("exit", json!("1"))),
        ("a fractional delay", with("delay_ms", json!(1.5))),
        ("hang as a string", with("hang", json!("yes"))),
        (
            "a missing stdout_file",
            json!({"synthetic_assumptions": [], "responses": [{"argv": ["--version"], "stdout_file": "missing.json"}]}),
        ),
        (
            "a bad response after the one that matches",
            json!({"synthetic_assumptions": [], "responses": [ok, {"argv": ["x"], "exit": "1"}]}),
        ),
    ];
    for (i, (why, value)) in bad.iter().enumerate() {
        let path = scenario("a3_malformed", &format!("bad-{i}"), value, &[]);
        let fake = FakeGh::new(&format!("a3_malformed_{i}"), &path);
        let got = text(&run(&fake, &["--version"]));
        assert_eq!(got.0, Some(BAD_SCENARIO), "{why}: {got:?}");
        assert!(got.1.is_empty(), "{why}: answered {:?}", got.1);
        assert!(
            got.2.starts_with("fake gh: bad scenario: "),
            "{why}: {}",
            got.2
        );
    }
    // A scenario that extends itself stops too, at the depth limit.
    let looped = scenario(
        "a3_malformed",
        "loop",
        &json!({"synthetic_assumptions": [], "extends": "loop", "responses": []}),
        &[],
    );
    let fake = FakeGh::new("a3_malformed_loop", &looped);
    assert_eq!(text(&run(&fake, &["--version"])).0, Some(BAD_SCENARIO));
    // The good one, for contrast, answers.
    let good = scenario(
        "a3_malformed",
        "good",
        &json!({"synthetic_assumptions": [], "responses": [ok]}),
        &[],
    );
    let fake = FakeGh::new("a3_malformed_good", &good);
    assert_eq!(
        text(&run(&fake, &["--version"])),
        (Some(0), "syn".to_owned(), String::new())
    );
}

#[test]
fn with_no_scenario_it_answers_nothing() {
    let missing =
        Path::new(env!("CARGO_TARGET_TMPDIR")).join("fake-gh-scenarios/a3_none/missing.json");
    let fake = FakeGh::new("a3_no_scenario_file", &missing);
    assert_eq!(text(&run(&fake, &["--version"])).0, Some(NO_SCENARIO));
    fs::remove_file(fake.dir.join("fake-gh.scenario")).expect("remove the pointer");
    let got = text(&run(&fake, &["--version"]));
    assert_eq!((got.0, got.1.as_str()), (Some(NO_SCENARIO), ""));
    assert_eq!(
        fake.invocations().len(),
        2,
        "both calls were still recorded"
    );
}
