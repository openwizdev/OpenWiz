//! P4 Partial failures: errors, timeouts, malformed responses and a missing
//! session give an honest partial result or an explicit error, never
//! invented data.

use std::process::Command;
use std::time::{Duration, Instant};

use openwiz_core::envelope::{Completeness, GapKind};
use openwiz_core::model::{Fact, Grouping, SessionId};
use openwiz_core::ops::{ListRequest, OpError};
use openwiz_core::source::SourceError;

use crate::support::*;

#[path = "../support/real_time.rs"]
mod real_time;

/// Slack on top of a budget for process start-up and clean-up.
const SLACK: Duration = Duration::from_secs(3);

fn still_running(pid: &str) -> bool {
    Command::new("kill")
        .args(["-0", pid.trim()])
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

#[test]
fn thread_list_error_is_an_explicit_error() {
    let fake = Fake::new("p04_thread_list_error", "thread-list-error");
    match fake.list(&ListRequest::default()) {
        Err(OpError::ListFailed(SourceError::CommandFailed { exit_code, detail })) => {
            assert_eq!(exit_code, Some(1));
            assert!(
                detail.contains("HTTP 500"),
                "keeps the source's error line: {detail}"
            );
        }
        other => panic!("expected an explicit list error, got {other:?}"),
    }
}

#[test]
fn thread_list_timeout_is_explicit_bounded_and_cleaned_up() {
    let fake = Fake::new("p04_thread_list_timeout", "thread-list-timeout");
    // Keep the synthetic run budget below the real per-read timeout, but
    // leave room for healthy prerequisite reads on a busy runner (#2779).
    let budget = real_time::scaled(
        "p04_list_timeout",
        Duration::from_secs(1),
        Duration::from_secs(10),
        || {
            Fake::new("p04_list_timeout_calibrate", "normal")
                .list(&ListRequest::default())
                .expect("healthy list for calibration");
        },
    );
    let started = Instant::now();
    let result = fake.list(&ListRequest {
        budget,
        ..ListRequest::default()
    });
    let took = started.elapsed();
    assert!(took >= budget && took < budget + SLACK, "took {took:?}");
    assert!(
        matches!(
            result,
            Err(OpError::ListFailed(SourceError::TimedOut { .. }))
        ),
        "expected an explicit timeout, got {result:?}"
    );
    let pid = fake.hung_pid().expect("the fake hung");
    assert!(
        !still_running(&pid),
        "the hung room-cli is still running or was not reaped"
    );
}

#[test]
fn malformed_thread_list_is_an_explicit_error() {
    for scenario in ["thread-list-not-json", "thread-list-truncated"] {
        let fake = Fake::new(&format!("p04_malformed_{scenario}"), scenario);
        let result = fake.list(&ListRequest::default());
        assert!(
            matches!(
                result,
                Err(OpError::ListFailed(SourceError::Malformed { .. }))
            ),
            "{scenario}: expected an explicit malformed error, got {result:?}"
        );
    }
}

#[test]
fn project_list_failure_gives_a_partial_ungrouped_result() {
    let fake = Fake::new("p04_project_list_failure", "project-list-error");
    let env = fake
        .list(&ListRequest::default())
        .expect("honest partial list");
    assert_eq!(env.coverage.state, Completeness::Partial);
    assert!(
        has_gap(&env.gaps, GapKind::CommandFailed, "project list"),
        "{:?}",
        env.gaps
    );
    assert_eq!(env.data.sessions.len(), 6, "sessions are still listed");
    for s in &env.data.sessions {
        assert!(
            matches!(&s.group, Grouping::Ungrouped { reason } if !reason.is_empty()),
            "{}: grouping cannot be verified without the project list, got {:?}",
            s.id.0,
            s.group
        );
    }
}

/// Synthetic assumptions: a machine ID is repeated, with the supplied names.
fn machine_name_rows(test: &str, names: &[String]) -> Fake {
    use serde_json::{Value, json};
    let fake = Fake::new(test, "normal");
    let normal = std::path::Path::new(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/fixtures/room-cli-0.43.1/normal"
    ));
    let rows: Value = serde_json::from_str(
        &std::fs::read_to_string(normal.join("machine-list.json")).expect("machine fixture"),
    )
    .expect("machine JSON");
    let rows: Vec<_> = names
        .iter()
        .map(|name| {
            let mut row = rows[0].clone();
            row["name"] = json!(name);
            row
        })
        .collect();
    let scenario = json!({
        "extends": normal,
        "synthetic_assumptions": ["Repeated machine ID with synthetic name facts"],
        "responses": [{"argv": ["machine", "list", "--json"], "stdout": json!(rows).to_string()}]
    });
    let path = fake.dir.join("scenario.json");
    std::fs::write(&path, scenario.to_string()).expect("scenario");
    std::fs::write(
        fake.dir.join("fake-room-cli.scenario"),
        path.to_str().unwrap(),
    )
    .expect("scenario pointer");
    fake
}

#[test]
fn conflicting_machine_names_are_unknown_in_the_fixture_cli_in_either_order() {
    use serde_json::json;
    let prefix = "x".repeat(openwiz_core::limits::FIELD_MAX_CHARS);
    let a = "Synthetic machine A".to_owned();
    let b = "Synthetic machine B".to_owned();
    for (case, mut names) in [
        vec![a.clone(), b.clone()],
        vec![a.clone(), b.clone(), a],
        vec![b.clone(), "Synthetic machine A".to_owned(), b],
        vec![format!("{prefix}a"), format!("{prefix}b")],
    ]
    .into_iter()
    .enumerate()
    {
        let mut previous = None;
        for reverse in [false, true] {
            if reverse {
                names.reverse();
            }
            let fake = machine_name_rows(&format!("p04_machine_conflict_{case}_{reverse}"), &names);
            let env = fake.cli_json(&["ls", "--json"]);
            assert_eq!(env["coverage"]["state"], "partial", "{names:?}");
            let gaps = env["gaps"].as_array().expect("gaps");
            assert_eq!(gaps.len(), 1, "{gaps:?}");
            assert_eq!(gaps[0]["kind"], "malformed");
            assert_eq!(gaps[0]["subject"], "mch_syn_0001");
            assert!(gaps[0]["detail"].as_str().unwrap().contains("conflicting"));
            let sessions = env["data"]["sessions"].as_array().expect("sessions");
            assert_eq!(sessions.len(), 6);
            assert_eq!(env["coverage"]["counts"]["listed"], 6);
            assert_eq!(env["coverage"]["counts"]["shown"], 6);
            let local = sessions.iter().find(|s| s["id"] == "thr_syn_0002").unwrap();
            assert_eq!(local["location"]["known"]["kind"], "local");
            let reason = local["location"]["known"]["machine"]["unknown"]
                .as_str()
                .expect("unknown machine name");
            assert!(reason.contains("conflicting"), "{reason}");
            let cloud = sessions.iter().find(|s| s["id"] == "thr_syn_0001").unwrap();
            assert_eq!(cloud["location"], json!({"known": {"kind": "cloud"}}));
            assert_eq!(
                fake.invocations(),
                vec![
                    vec!["--version"],
                    vec!["thread", "list", "--json"],
                    vec!["project", "list", "--json", "--include-personal"],
                    vec!["machine", "list", "--json"],
                ]
            );
            if let Some(previous) = previous {
                assert_eq!(
                    env, previous,
                    "machine row order must not change the envelope"
                );
            }
            previous = Some(env);
        }
    }
}

#[test]
fn consistent_machine_names_resolve_normally_in_the_fixture_cli() {
    // Worked example of the 200-character cap: 199 x's and one cut marker.
    for (case, (name, expected)) in [
        (
            "Synthetic machine one".to_owned(),
            "Synthetic machine one".to_owned(),
        ),
        ("x".repeat(300), format!("{}…", "x".repeat(199))),
    ]
    .into_iter()
    .enumerate()
    {
        for count in [1, 3] {
            let fake = machine_name_rows(
                &format!("p04_machine_consistent_{case}_{count}"),
                &vec![name.clone(); count],
            );
            let env = fake.cli_json(&["ls", "--json"]);
            assert_eq!(env["coverage"]["state"], "complete");
            assert_eq!(env["gaps"], serde_json::json!([]));
            let local = env["data"]["sessions"]
                .as_array()
                .unwrap()
                .iter()
                .find(|s| s["id"] == "thr_syn_0002")
                .unwrap();
            assert_eq!(local["location"]["known"]["machine"]["known"], expected);
        }
    }
}

#[test]
fn detail_read_error_gives_a_partial_result_with_unknown_configuration() {
    let fake = Fake::new("p04_detail_read_error", "show-error");
    let env = fake.list(&long()).expect("honest partial list");
    assert_eq!(env.coverage.state, Completeness::Partial);
    assert!(
        has_gap(&env.gaps, GapKind::CommandFailed, "thr_syn_0002"),
        "{:?}",
        env.gaps
    );
    let failed = &session(&env, "thr_syn_0002").reported_configuration;
    unknown_reason(&failed.model);
    unknown_reason(&failed.effort);
    let fine = &session(&env, "thr_syn_0001").reported_configuration;
    assert_eq!(fine.model, Fact::Known("synthetic-model-a".to_owned()));
}

#[test]
fn detail_read_timeout_gives_a_partial_result_within_the_budget() {
    let fake = Fake::new("p04_detail_read_timeout", "show-timeout");
    let budget = real_time::scaled(
        "p04_detail_timeout",
        Duration::from_millis(1_500),
        Duration::from_secs(10),
        || {
            Fake::new("p04_detail_timeout_calibrate", "normal")
                .list(&long())
                .expect("healthy detailed list for calibration");
        },
    );
    let started = Instant::now();
    let env = fake
        .list(&ListRequest { budget, ..long() })
        .expect("honest partial list");
    let took = started.elapsed();
    assert!(took >= budget && took < budget + SLACK, "took {took:?}");
    assert_eq!(env.coverage.state, Completeness::Partial);
    assert!(
        has_gap(&env.gaps, GapKind::TimedOut, "thr_syn_0002")
            || has_gap(&env.gaps, GapKind::BudgetExhausted, "thr_syn_0002"),
        "{:?}",
        env.gaps
    );
    unknown_reason(&session(&env, "thr_syn_0002").reported_configuration.model);
    let pid = fake.hung_pid().expect("the fake hung");
    assert!(
        !still_running(&pid),
        "the hung room-cli is still running or was not reaped"
    );
}

#[test]
fn wrong_types_become_unknowns_not_invented_values() {
    let fake = Fake::new("p04_wrong_types", "thread-list-wrong-types");
    let env = fake
        .list(&ListRequest::default())
        .expect("honest partial list");
    assert_eq!(env.coverage.state, Completeness::Partial);
    unknown_reason(&session(&env, "thr_syn_0001").status);
    unknown_reason(&session(&env, "thr_syn_0002").updated_at);
    assert!(matches!(
        session(&env, "thr_syn_0003").group,
        Grouping::Ungrouped { .. }
    ));
    unknown_reason(&session(&env, "thr_syn_0004").recap);
    unknown_reason(&session(&env, "thr_syn_0005").parent);
    unknown_reason(&session(&env, "thr_syn_0006").location);
}

/// Is `argv` a detail read (`thread show` or `thread output`) of `id`?
fn is_detail_read_of(argv: &[String], id: &str) -> bool {
    argv.len() == 4
        && argv[0] == "thread"
        && (argv[1] == "show" || argv[1] == "output")
        && argv[2] == id
}

/// The not-found detail read is the last read, and the only one of `id`.
fn assert_stops_at_not_found(label: &str, calls: &[Vec<String>], id: &str) {
    let detail_reads = calls.iter().filter(|a| is_detail_read_of(a, id)).count();
    assert_eq!(
        detail_reads, 1,
        "{label}: one detail read of {id}: {calls:?}"
    );
    assert!(
        calls.last().is_some_and(|a| is_detail_read_of(a, id)),
        "{label}: no read after the not-found detail read: {calls:?}"
    );
}

/// Changed in ticket 1's correction round 1 (Sol S8): issue #3 says no
/// further read is made after not-found, so the invocation log is checked.
/// Changed after the internal Haiku review (H7): `--json` prints nothing, or
/// a JSON value with no `data`.
#[test]
fn show_of_a_nonexistent_session_is_not_found() {
    let fake = Fake::new("p04_show_nonexistent", "normal");
    match fake.show(MISSING_ID) {
        Err(OpError::NotFound(id)) => assert_eq!(id, SessionId(MISSING_ID.to_owned())),
        other => panic!("expected not found, got {other:?}"),
    }
    assert_stops_at_not_found("core show", &fake.invocations(), MISSING_ID);

    for args in [
        &["show", MISSING_ID][..],
        &["show", MISSING_ID, "--json"][..],
    ] {
        let fake = Fake::new(
            &format!("p04_show_nonexistent_cli_{}", args.len()),
            "normal",
        );
        let (code, out, err) = fake.cli(args);
        assert_ne!(code, 0);
        if args.contains(&"--json") && !out.trim().is_empty() {
            let value: serde_json::Value = serde_json::from_str(&out)
                .unwrap_or_else(|e| panic!("--json prints JSON or nothing ({e}): {out}"));
            assert!(
                value.get("data").is_none(),
                "no session is printed as if it existed: {out}"
            );
        } else {
            assert!(
                out.trim().is_empty(),
                "nothing is printed as if it existed: {out}"
            );
        }
        assert!(err.to_lowercase().contains("not found"), "{err}");
        assert_stops_at_not_found(&format!("{args:?}"), &fake.invocations(), MISSING_ID);
    }
}

#[test]
fn show_of_an_unsafe_id_is_refused_without_running_room_cli() {
    let fake = Fake::new("p04_show_unsafe_id", "normal");
    let result = fake.show("--work-status");
    assert!(
        matches!(result, Err(OpError::InvalidRequest(_))),
        "an unsafe id is an invalid request, not a missing session: {result:?}"
    );
    let calls = fake.invocations();
    assert!(
        calls
            .iter()
            .all(|argv| !argv.iter().any(|a| a == "--work-status")),
        "the id reached room-cli: {calls:?}"
    );
}

#[test]
fn final_output_read_error_gives_a_partial_show() {
    let fake = Fake::new("p04_final_output_read_error", "show-output-error");
    let env = fake.show("thr_syn_0002").expect("honest partial show");
    assert_eq!(env.coverage.state, Completeness::Partial);
    assert!(
        has_gap(&env.gaps, GapKind::CommandFailed, "thr_syn_0002"),
        "{:?}",
        env.gaps
    );
    unknown_reason(&env.data.final_output);
    unknown_reason(&env.data.reported_error);
    assert_eq!(
        env.data.session.status,
        Fact::Known("active".to_owned()),
        "the rest is still read"
    );
}

#[test]
fn final_output_read_timeout_gives_a_partial_show_within_the_budget() {
    let fake = Fake::new("p04_final_output_read_timeout", "show-output-timeout");
    let budget = real_time::scaled(
        "p04_output_timeout",
        Duration::from_millis(1_500),
        Duration::from_secs(10),
        || {
            Fake::new("p04_output_timeout_calibrate", "normal")
                .show("thr_syn_0002")
                .expect("healthy show for calibration");
        },
    );
    let started = Instant::now();
    let env = openwiz_core::ops::show(
        &fake.source(),
        &clock(),
        &openwiz_core::ops::ShowRequest {
            id: SessionId("thr_syn_0002".to_owned()),
            budget,
        },
    )
    .expect("honest partial show");
    let took = started.elapsed();
    assert!(took >= budget && took < budget + SLACK, "took {took:?}");
    assert_eq!(env.coverage.state, Completeness::Partial);
    assert!(
        has_gap(&env.gaps, GapKind::TimedOut, "thr_syn_0002")
            || has_gap(&env.gaps, GapKind::BudgetExhausted, "thr_syn_0002"),
        "{:?}",
        env.gaps
    );
    unknown_reason(&env.data.final_output);
    let pid = fake.hung_pid().expect("the fake hung");
    assert!(
        !still_running(&pid),
        "the hung room-cli is still running or was not reaped"
    );
}

/// Whether this run is the first attempt of a pull request to `main` on
/// GitHub Actions: exactly `GITHUB_ACTIONS=true`, `GITHUB_EVENT_NAME=
/// pull_request`, `GITHUB_BASE_REF=main` and `GITHUB_RUN_ATTEMPT=1`. The one
/// context the real 15-second proof below is moved out of (#1260, Q2): it
/// still runs on every push to `main`, the nightly run, every rerun, every
/// pull request to `release-*`, a merge group and every local run, and on any
/// missing or odd value.
fn first_pull_request_run_to_main(var: impl Fn(&str) -> Option<String>) -> bool {
    [
        ("GITHUB_ACTIONS", "true"),
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_BASE_REF", "main"),
        ("GITHUB_RUN_ATTEMPT", "1"),
    ]
    .iter()
    .all(|(key, value)| var(key).as_deref() == Some(*value))
}

#[test]
fn only_a_first_pull_request_run_to_main_moves_the_15_second_proof() {
    let pr = [
        ("GITHUB_ACTIONS", "true"),
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_BASE_REF", "main"),
        ("GITHUB_RUN_ATTEMPT", "1"),
    ];
    let with = |key: &'static str, value: Option<&'static str>| {
        let mut env: Vec<(&str, &str)> = pr.iter().copied().filter(|(k, _)| *k != key).collect();
        if let Some(value) = value {
            env.push((key, value));
        }
        env
    };
    // (what the context is, its variables, whether the proof moves)
    type Case = (String, Vec<(&'static str, &'static str)>, bool);
    let mut cases: Vec<Case> = vec![("a first pull request run to main".into(), pr.to_vec(), true)];
    cases.push(("no GitHub variables (a local run)".into(), vec![], false));
    for (key, odd) in [
        ("GITHUB_ACTIONS", vec!["false", "True", "true ", "1", ""]),
        (
            "GITHUB_EVENT_NAME",
            vec![
                "push",
                "schedule",
                "merge_group",
                "workflow_dispatch",
                "pull_request_target",
                "Pull_request",
                "",
            ],
        ),
        (
            "GITHUB_BASE_REF",
            vec!["release-0.0.9", "main-null", "Main", " main", ""],
        ),
        ("GITHUB_RUN_ATTEMPT", vec!["2", "10", "01", "1 ", "+1", ""]),
    ] {
        cases.push((format!("{key} missing"), with(key, None), false));
        for value in odd {
            cases.push((format!("{key}={value:?}"), with(key, Some(value)), false));
        }
    }
    for (name, env, moved) in cases {
        let var = |key: &str| {
            env.iter()
                .find(|(k, _)| *k == key)
                .map(|(_, v)| (*v).to_owned())
        };
        assert_eq!(first_pull_request_run_to_main(var), moved, "{name}");
    }
}

/// New in ticket 2. Issue #3: each read has a 15-second timeout, and there
/// are no retries; a timeout becomes a gap. With the default 30-second
/// budget, a read that never answers is stopped after 15 seconds, once.
///
/// Moved off a first pull request run to `main` (#1260, Q2): it waits on the
/// adapter's fixed `READ_TIMEOUT`, which no test can shorten, so it alone
/// would hold this binary over its 10-second budget. It runs, unchanged,
/// everywhere else (`first_pull_request_run_to_main`), and its moved-case
/// ledger records that move in X3's evidence.
#[test]
fn a_read_that_never_answers_is_stopped_after_15_seconds_and_not_retried() {
    if first_pull_request_run_to_main(|key| std::env::var(key).ok()) {
        eprintln!(
            "moved to main and nightly (#1260): this proof waits on the fixed 15-second read timeout"
        );
        return;
    }
    assert_eq!(
        openwiz_core::limits::READ_TIMEOUT,
        Duration::from_secs(15),
        "the approved read timeout"
    );
    let fifteen = Duration::from_secs(15);

    // Both halves wait for the real 15-second timeout: they run at once,
    // with the same assertions, so the test waits once, not twice.
    std::thread::scope(|scope| {
        scope.spawn(|| {
            let fake = Fake::new("p04_read_timeout_thread_list", "thread-list-timeout");
            let started = Instant::now();
            let result = fake.list(&ListRequest::default());
            let took = started.elapsed();
            assert!(
                matches!(
                    result,
                    Err(OpError::ListFailed(SourceError::TimedOut { .. }))
                ),
                "{result:?}"
            );
            assert!(took >= fifteen && took < fifteen + SLACK, "took {took:?}");
            let lists = fake
                .invocations()
                .iter()
                .filter(|a| a.len() >= 2 && a[0] == "thread" && a[1] == "list")
                .count();
            assert_eq!(lists, 1, "no retry: {:?}", fake.invocations());
            let pid = fake.hung_pid().expect("the fake hung");
            assert!(
                !still_running(&pid),
                "the hung room-cli is still running or was not reaped"
            );
        });
        scope.spawn(|| {
            let fake = Fake::new("p04_read_timeout_thread_show", "show-timeout");
            let started = Instant::now();
            let env = fake.list(&long()).expect("honest partial list");
            let took = started.elapsed();
            assert!(took >= fifteen && took < fifteen + SLACK, "took {took:?}");
            assert!(
                has_gap(&env.gaps, GapKind::TimedOut, "thr_syn_0002"),
                "the read timed out; the budget did not run out: {:?}",
                env.gaps
            );
            unknown_reason(&session(&env, "thr_syn_0002").reported_configuration.model);
            for id in ["thr_syn_0001", "thr_syn_0003", "thr_syn_0006"] {
                assert!(
                    matches!(
                        session(&env, id).reported_configuration.model,
                        Fact::Known(_)
                    ),
                    "{id} is still enriched"
                );
            }
            let shows = fake
                .invocations()
                .iter()
                .filter(|a| is_detail_read_of(a, "thr_syn_0002"))
                .count();
            assert_eq!(shows, 1, "no retry: {:?}", fake.invocations());
            let pid = fake.hung_pid().expect("the fake hung");
            assert!(
                !still_running(&pid),
                "the hung room-cli is still running or was not reaped"
            );
        });
    });
}

/// New in ticket 2. The exit codes `openwiz --help` documents: 0 a result
/// (complete or partial), 1 a failed read, 2 a usage error or out-of-bounds
/// request, 3 not found. Since #37 an untested `room-cli` version is never an
/// error (exit 0, marked untested). For read and usage errors, stdout is
/// empty and stderr has one `openwiz: ` message; a usage error reads nothing.
#[test]
fn exit_codes_are_documented_and_errors_go_to_stderr() {
    let cases: &[(&str, &[&str], i32)] = &[
        ("normal", &["ls"], 0),
        ("normal", &["ls", "-l", "--json"], 0),
        ("normal", &["show", "thr_syn_0001"], 0),
        ("project-list-error", &["ls"], 0),
        ("show-output-error", &["show", "thr_syn_0002", "--json"], 0),
        ("thread-list-error", &["ls"], 1),
        ("thread-list-not-json", &["ls", "--json"], 1),
        ("show-error", &["show", "thr_syn_0002"], 1),
        ("normal", &[], 2),
        ("normal", &["ls", "--bogus"], 2),
        ("normal", &["ls", "--limit"], 2),
        ("normal", &["ls", "--limit", "many"], 2),
        ("normal", &["ls", "--limit", "201"], 2),
        ("normal", &["ls", "--offset", "-1"], 2),
        ("normal", &["show"], 2),
        ("normal", &["show", "thr_syn_0001", "thr_syn_0002"], 2),
        ("normal", &["show", "--work-status"], 2),
        ("normal", &["rm", "thr_syn_0001"], 2),
        ("normal", &["show", MISSING_ID], 3),
        ("normal", &["show", MISSING_ID, "--json"], 3),
        ("version-0.44.0", &["ls"], 0),
        ("version-0.44.0", &["show", "thr_syn_0001", "--json"], 0),
        ("version-0.43.1", &["ls", "-l"], 0),
        ("version-unrecognised", &["ls"], 0),
    ];
    for (i, (scenario, args, wanted)) in cases.iter().enumerate() {
        let fake = Fake::new(&format!("p04_exit_code_{i}"), scenario);
        let (code, out, err) = fake.cli(args);
        assert_eq!(code, *wanted, "{scenario} openwiz {args:?}: {err}");
        if *wanted == 0 {
            assert!(!out.is_empty(), "{scenario} {args:?} prints a result");
        } else {
            assert!(out.is_empty(), "{scenario} {args:?}: stdout: {out}");
            assert!(
                err.starts_with("openwiz: "),
                "{scenario} {args:?}: stderr: {err}"
            );
        }
        if *wanted == 2 {
            assert!(
                fake.invocations().is_empty(),
                "{args:?}: a usage error reads nothing: {:?}",
                fake.invocations()
            );
        }
    }
}

/// New in ticket 2. `openwiz --help` documents the commands, the sort key
/// and the exit codes, and reads nothing.
#[test]
fn help_documents_the_commands_the_order_and_the_exit_codes() {
    for flag in ["--help", "-h"] {
        let fake = Fake::new(&format!("p04_help_{flag}"), "normal");
        let (code, out, err) = fake.cli(&[flag]);
        assert_eq!(code, 0, "{err}");
        for wanted in [
            "openwiz ls [-l] [-a] [--hidden] [--limit N] [--offset N] [--json]",
            "openwiz show <id> [--json]",
            "Order: most recently updated first, then by session id; sessions whose update time is unknown come last.",
            "Exit codes:",
            "  0  a result was printed, complete or partial",
            "  1  a read failed",
            "  1  ls, show, --help: the output could not be written or flushed;\n     some of it may already be on stdout",
            "On an error, stdout is empty unless ls, show or --help fails to write or flush output;\nsome output may already be on stdout in that case.",
            "  2  usage error, or a request out of bounds",
            "  3  show: the session was not found",
            "ls, show, send and new can read and show room-cli --version.",
            "send --preview, models and new --status do not read the version. send --check and attachment never run room-cli.",
            "Any version runs; one other than the run's own live-tested version is marked untested, or not live-tested while it has none.",
            "Live-tested: the reads with v127; send with no version yet; new with no version yet.",
        ] {
            assert!(
                out.contains(wanted),
                "{flag}: help should contain {wanted:?}:\n{out}"
            );
        }
        // #37: the version is never a gate, for the reads and for send.
        assert!(
            !out.lines().any(|l| l.starts_with("  4  ")),
            "{flag}: no exit code 4 since #37:\n{out}"
        );
        assert!(fake.invocations().is_empty(), "help reads nothing");
    }
}

/// New in ticket 2, after the internal Haiku review (A, R2): a switch takes
/// no value, so `--hidden=no` is a usage error, not `--hidden`.
#[test]
fn switches_take_no_value() {
    for (i, args) in [
        &["ls", "--hidden=no"][..],
        &["ls", "--json=false"][..],
        &["ls", "-l", "--hidden=yes"][..],
        &["show", "thr_syn_0001", "--json=yes"][..],
    ]
    .iter()
    .enumerate()
    {
        let fake = Fake::new(&format!("p04_switch_value_{i}"), "normal");
        let (code, out, err) = fake.cli(args);
        assert_eq!(code, 2, "openwiz {args:?}: {err}");
        assert!(out.is_empty(), "{args:?}: {out}");
        assert!(fake.invocations().is_empty(), "{args:?} reads nothing");
    }
}

/// New in ticket 2, after the internal Haiku review (A, R5): a response over
/// the size bound fails as malformed, also when the program stops with an
/// error once its output is no longer read. The native fake writes one
/// preallocated buffer beyond the 32 MiB bound (#2831).
#[test]
fn an_oversized_response_fails_as_malformed() {
    // Measurements repeat in this same libtest slot: CI still has eight
    // proof threads and 24 web-api threads, with no extra test processes.
    let rounds = match std::env::var_os("OPENWIZ_OVERSIZED_ROUNDS") {
        None => 1,
        Some(value) if value == "5" => 5,
        other => panic!("OPENWIZ_OVERSIZED_ROUNDS must be unset or 5, got {other:?}"),
    };
    for round in 1..=rounds {
        eprintln!("oversized_response_round={round}");
        oversized_response_round();
    }
}

fn oversized_response_round() {
    let fake = Fake::new("p04_oversized_response", "normal");
    // Just over 32 MiB + a 1 MiB pipe: even a full pipe cannot
    // hold the trailing bytes once the reader stops at the bound plus one.
    let scenario = fake.dir.join("oversized.json");
    std::fs::write(
        &scenario,
        serde_json::json!({
            "synthetic_assumptions": ["The oversized list is zero-filled, 33 MiB + 2 bytes, written from one preallocated in-memory buffer."],
            "responses": [
            {"argv": ["--version"], "stdout": "0.43.1\n"},
            {"argv": ["thread", "list", "--json"], "oversized_stdout_bytes": 34_603_010}
        ]})
        .to_string(),
    )
    .expect("oversized scenario");
    std::fs::write(
        fake.dir.join("fake-room-cli.scenario"),
        scenario.to_str().expect("scenario path"),
    )
    .expect("scenario pointer");
    let started = Instant::now();
    let result = fake.list(&ListRequest::default());
    eprintln!(
        "oversized_response_read_ms={:.3}",
        started.elapsed().as_secs_f64() * 1000.0
    );
    match result {
        Err(OpError::ListFailed(SourceError::Malformed { detail })) => {
            assert_eq!(detail, "printed more than 33554432 bytes");
        }
        other => panic!("expected an explicit malformed error, got {other:?}"),
    }

    // Independently check the fixture still exercises an unsuccessful
    // writer when its reader stops at the size bound, not just invalid JSON.
    use std::io::Read;
    use std::process::Stdio;
    let mut child = Command::new(fake.program())
        .args(["thread", "list", "--json"])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("start oversized fixture");
    let mut bytes = Vec::new();
    child
        .stdout
        .take()
        .expect("fixture stdout")
        .take(33_554_433)
        .read_to_end(&mut bytes)
        .expect("read through the size bound");
    assert_eq!(bytes.len(), 33_554_433);
    assert!(
        !child.wait().expect("reap oversized fixture").success(),
        "the oversized writer must still fail when its reader closes"
    );
}

/// #2831: the shared runner's size error on a completed write is an
/// uncertain receipt at the adapter boundary, never a confirmed refusal.
/// The held-write process proof separately rejects early stopping of writes.
#[test]
fn over_cap_send_and_new_receipts_stay_uncertain() {
    use openwiz_core::messaging::Mode;
    use openwiz_core::messaging::send::{Messenger, TellReply, UncertainReason};
    use openwiz_core::new_thread::operation::{NewThreadClient, SpawnRequest};
    use openwiz_core::new_thread::outcome::SpawnReply;
    use openwiz_core::prompt::ReadyPrompt;

    let fake = Fake::new("p04_oversized_write_receipts", "normal");
    let spawn = SpawnRequest {
        project_id: "prj_syn_2831".into(),
        provider: "codex".into(),
        model: "synthetic-model".into(),
        effort: "high".into(),
        request_id: "ow1-0123456789abcdef0123456789abcdef01234567".into(),
        prompt: ReadyPrompt::text("Synthetic"),
    };
    let scenario = fake.dir.join("oversized-writes.json");
    std::fs::write(&scenario, serde_json::json!({
        "synthetic_assumptions": ["Synthetic send and new responses exceed the 32 MiB cap."],
        "responses": [
            {"argv": ["thread", "tell", "thr_syn_0001", "--mode", "queue", "--json", "--", "Synthetic"], "oversized_stdout_bytes": 34_603_010},
            {"argv": openwiz_adapter_cloudroom::new_thread::spawn_argv(&spawn).unwrap(), "oversized_stdout_bytes": 34_603_010}
        ]
    }).to_string()).unwrap();
    std::fs::write(
        fake.dir.join("fake-room-cli.scenario"),
        scenario.to_str().unwrap(),
    )
    .unwrap();
    let source = fake.source();
    let sent = source.tell(
        &SessionId("thr_syn_0001".into()),
        Mode::Queue,
        "Synthetic",
        Instant::now() + Duration::from_secs(15),
    );
    assert!(
        matches!(
            sent,
            TellReply::Unclear {
                reason: UncertainReason::UnexpectedReceipt,
                ..
            }
        ),
        "oversized send receipt: {sent:?}"
    );
    let created = source.spawn(&spawn, Instant::now() + Duration::from_secs(15));
    assert!(
        matches!(
            created,
            SpawnReply::Unclear {
                reason: UncertainReason::UnexpectedReceipt,
                ..
            }
        ),
        "oversized new receipt: {created:?}"
    );
    assert_eq!(fake.invocations().len(), 2, "neither write is retried");
}
