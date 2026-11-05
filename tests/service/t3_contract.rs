//! The contract's own worked examples, reproduced by the planner. Each
//! expected value is read from `contracts/service.v1.md` itself: the
//! status report with two incidents (its last pass and its incidents), the
//! state behind it a moment later, with CloudRoom not running, and the fix
//! the planner returns for one try.

use openwiz_core::health::model::{
    CloudRoomSeen, Fault, FleetThreadBroken, Id, Incident, IncidentId, Incidents, Known, Listed,
    Outcome, Repository, SavedTry, Seen, ServerBroken, TakeoverOutcome, ThreadSeen, Tries,
};
use openwiz_core::model::Timestamp;
use serde_json::Value;

use super::{
    LOOP_ID, LOOP_NAME, Run, contract_text, fixes, healthy, id, number, seen_loop, seen_thread,
};

/// The contract's one line that starts with `prefix`, parsed.
fn example(prefix: &str) -> Value {
    let contract = contract_text();
    let lines: Vec<&str> = contract
        .lines()
        .filter(|line| line.starts_with(prefix))
        .collect();
    assert_eq!(lines.len(), 1, "one example starts {prefix:?}");
    serde_json::from_str(lines[0]).expect("the example is JSON")
}

/// The status report with two incidents.
fn status() -> Value {
    example(r#"{"schema": "openwiz.service-status.v1", "at": 1767229500000"#)
}

/// The state behind it, a moment later, with CloudRoom not running.
fn state() -> Value {
    example(r#"{"schema": "openwiz.service-state.v1""#)
}

/// The incidents before the status report's last pass, at 1767229440000:
/// `i3`'s fleet thread was taken over and has been healthy since
/// 1767229380000; `i4`'s server has had its first try, saved with its
/// comment.
fn before_the_status() -> Incidents {
    Incidents {
        next_incident: number(5),
        incidents: vec![
            Incident {
                id: IncidentId(number(3)),
                fault: Fault::FleetThread {
                    spec: number(900),
                    thread: id("thr_syn_0201"),
                    broken: FleetThreadBroken::Archived,
                    tries: Tries::One(SavedTry {
                        at: Timestamp(1_767_229_320_000),
                        outcome: Some(TakeoverOutcome::Done {
                            thread: id("thr_syn_0202"),
                        }),
                        comment: Some(number(7001)),
                    }),
                },
                opened_at: Timestamp(1_767_229_320_000),
                healthy_since: Some(Timestamp(1_767_229_380_000)),
                needs_you: None,
            },
            Incident {
                id: IncidentId(number(4)),
                fault: Fault::Server {
                    broken: ServerBroken::TimedOut,
                    tries: Tries::One(SavedTry {
                        at: Timestamp(1_767_229_380_000),
                        outcome: Some(Outcome::Done),
                        comment: Some(number(7002)),
                    }),
                },
                opened_at: Timestamp(1_767_229_380_000),
                healthy_since: None,
                needs_you: None,
            },
        ],
    }
}

/// What the status report's last pass saw: everything healthy but the
/// server, which timed out; spec #900's records name the new fleet thread.
fn seen_at_the_status() -> Seen {
    Seen {
        cloudroom: CloudRoomSeen::Running,
        loops: Listed::Read(vec![seen_loop(LOOP_ID, LOOP_NAME, false)]),
        tick_running_since: None,
        fleet_threads: Listed::Read(vec![seen_thread(900, "thr_syn_0202", ThreadSeen::Present)]),
        server: Known::Broken(ServerBroken::TimedOut),
    }
}

/// The executor's part after the status's pass: `i4`'s second try is done,
/// and its record's comment is 7003.
fn settle_second_try(run: &mut Run) {
    for incident in &mut run.incidents.incidents {
        if let Fault::Server { tries, .. } = &mut incident.fault
            && let Some(last) = tries.last_mut()
        {
            last.outcome = Some(Outcome::Done);
            last.comment = Some(number(7003));
        }
    }
}

/// The status report's last pass (the server's second try), and its
/// incidents once that try is saved.
#[test]
fn t3_contract_examples_preserve_each_original_proof() {
    let cases: [(&str, fn()); 4] = [
        (
            "ids_and_the_repository_refuse_what_the_schema_refuses",
            ids_and_the_repository_refuse_what_the_schema_refuses,
        ),
        ("the_fix_the_contract_shows", the_fix_the_contract_shows),
        (
            "the_state_a_moment_later_with_cloudroom_down",
            the_state_a_moment_later_with_cloudroom_down,
        ),
        (
            "the_status_reports_pass_and_incidents",
            the_status_reports_pass_and_incidents,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: t3_planner::contract::{name}");
        proof();
    }
}

fn the_status_reports_pass_and_incidents() {
    let status = status();
    let mut run = Run::from(before_the_status());
    let pass = run.pass(&seen_at_the_status(), 1_767_229_440_000);
    assert_eq!(
        json_of!(&pass),
        status["last_pass"],
        "the status's last pass"
    );
    settle_second_try(&mut run);
    assert_eq!(
        run.incidents_json(),
        status["incidents"],
        "the status's incidents"
    );
    assert_eq!(run.incidents.next_incident.get(), 5);
}

/// A moment later, with CloudRoom not running: the server is healthy (so
/// `i4` is healthy since now), the fleet thread unknown (so `i3` is
/// unchanged), the loops unread, and CloudRoom's own incident `i5` opens
/// with nothing due.
fn the_state_a_moment_later_with_cloudroom_down() {
    let state = state();
    let mut run = Run::from(before_the_status());
    run.pass(&seen_at_the_status(), 1_767_229_440_000);
    settle_second_try(&mut run);

    let seen = Seen {
        cloudroom: CloudRoomSeen::NotRunning,
        server: Known::Healthy,
        ..seen_at_the_status()
    };
    let pass = run.pass(&seen, 1_767_229_500_000);
    assert_eq!(json_of!(&pass), state["last_pass"], "the state's last pass");
    assert_eq!(
        run.incidents_json(),
        state["incidents"],
        "the state's incidents"
    );
    assert_eq!(
        serde_json::json!(run.incidents.next_incident.get()),
        state["next_incident"]
    );
}

/// "What the planner (T3) returns for one try": the contract's example.
fn the_fix_the_contract_shows() {
    let expected = example(r#"{"fix": "restart_server", "incident": "i3", "try": 1}"#);
    let mut seen = healthy();
    seen.server = Known::Broken(ServerBroken::Refused);
    let mut run = Run::from(Incidents {
        next_incident: number(3),
        incidents: vec![],
    });
    let pass = run.pass(&seen, 1_767_229_380_000);
    assert_eq!(fixes(&pass), Value::Array(vec![expected]));
}

/// The schema, with only the one `$defs` entry `name` at its top.
fn only(name: &str) -> Value {
    let mut schema = super::load_schema().clone();
    schema["oneOf"] = serde_json::json!([{"$ref": format!("#/$defs/{name}")}]);
    schema
}

/// An id and a repository refuse what the schema's `id`, `owner` and
/// `repo_name` refuse, and take what they take.
fn ids_and_the_repository_refuse_what_the_schema_refuses() {
    let long = "a".repeat(128);
    let too_long = "a".repeat(129);
    let ids = [
        "a",
        "_",
        "0",
        "thr_syn_0201",
        "loop_syn_0001",
        "a-b_c",
        &long,
        "",
        "-a",
        "a b",
        "a.b",
        "a/b",
        "é",
        "a\n",
        &too_long,
    ];
    let schema = only("id");
    for text in ids {
        let by_schema = super::schema::validate(&schema, &Value::from(text)).is_empty();
        assert_eq!(Id::parse(text).is_some(), by_schema, "id {text:?}");
    }

    let owners = [
        "synthetic-owner",
        "a",
        "A1",
        "a-",
        "",
        "-a",
        "a_b",
        "a.b",
        "a b",
        "é",
    ];
    let names = [
        "synthetic-repo",
        "a",
        ".github",
        "a_b.c-d",
        "-",
        "",
        "a b",
        "a/b",
        "é",
    ];
    let (owner_schema, name_schema) = (only("owner"), only("repo_name"));
    for owner in owners {
        for name in names {
            let by_schema = super::schema::validate(&owner_schema, &Value::from(owner)).is_empty()
                && super::schema::validate(&name_schema, &Value::from(name)).is_empty();
            assert_eq!(
                Repository::parse(owner, name).is_some(),
                by_schema,
                "repository {owner:?}/{name:?}"
            );
        }
    }
    let expected = [
        true, true, true, true, true, true, true, false, false, false, false, false, false, false,
        false,
    ];
    let by_code: Vec<bool> = ids.iter().map(|text| Id::parse(text).is_some()).collect();
    assert_eq!(by_code, expected, "the ids, one by one");
}
