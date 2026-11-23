use openwiz_core::envelope::{Completeness, GapKind};
use openwiz_core::model::Fact;
use openwiz_core::ops::ListRequest;

use crate::support::*;

/// #37: Jake approved policy (b), 2026-10-28
/// ([private record](https://github.com/jparker2006/ClosedWiz/issues/1277#issuecomment-6704800036)): version changes never gate a read. Any version
/// is read, shown and the run goes on; one other than the live-tested version
/// is marked untested. Before #37 this test required a stop (issue #3).
/// Since #53 the live-tested version is v127, so 0.43.1 is untested too.
#[test]
fn an_untested_version_is_reported_and_never_stops() {
    for (scenario, version) in [("version-0.44.0", "0.44.0"), ("version-0.43.1", "0.43.1")] {
        for (name, request) in [("ls", ListRequest::default()), ("ls_long", long())] {
            let fake = Fake::new(&format!("p12_untested_{scenario}_{name}"), scenario);
            let env = fake
                .list(&request)
                .unwrap_or_else(|e| panic!("{scenario} {name}: still lists, got {e:?}"));
            assert_eq!(env.source.version, Fact::Known(version.to_owned()));
            assert_eq!(env.source.tested_version, "v127");
            assert!(!env.source.version_tested, "{scenario}: marked untested");
            assert!(!env.data.sessions.is_empty(), "{scenario}: sessions listed");
        }
        let fake = Fake::new(&format!("p12_untested_{scenario}_show"), scenario);
        let env = fake
            .show("thr_syn_0001")
            .unwrap_or_else(|e| panic!("{scenario} show: still shows, got {e:?}"));
        assert!(!env.source.version_tested);

        for args in [
            &["ls"][..],
            &["ls", "-l"][..],
            &["show", "thr_syn_0001"][..],
        ] {
            let fake = Fake::new(
                &format!("p12_untested_cli_{scenario}_{}", args.join("_")),
                scenario,
            );
            let (code, out, err) = fake.cli(args);
            assert_eq!(code, 0, "{scenario} openwiz {args:?}: {err}");
            let header = out.lines().next().unwrap_or_default();
            assert!(
                header.contains(&format!("room-cli {version} (untested")),
                "{scenario} {args:?} header: {header}"
            );
            assert!(out.contains("thr_syn_0001"), "{scenario} {args:?}: {out}");
        }
    }
}

#[test]
fn an_unrecognised_version_is_unknown_and_never_stops() {
    let fake = Fake::new("p12_unrecognised_version", "version-unrecognised");
    let env = fake.list(&ListRequest::default()).expect("still lists");
    unknown_reason(&env.source.version);
    assert!(!env.source.version_tested);
    assert!(
        env.gaps.iter().any(|g| g.kind == GapKind::UntestedVersion),
        "{:?}",
        env.gaps
    );
    assert!(!env.data.sessions.is_empty());
    let (code, out, err) = fake.cli(&["ls", "--json"]);
    assert_eq!(code, 0, "{err}");
    assert!(!out.contains("Synthetic not a version"), "{out}");
}

#[test]
fn a_failed_version_read_never_echoes_its_error_text() {
    const MARKER: &str = "Synthetic private version marker";
    let fake = Fake::new("p12_failed_version_core", "version-failed");
    let env = fake.list(&ListRequest::default()).expect("still lists");
    let reason = unknown_reason(&env.source.version).to_owned();
    assert!(!reason.contains(MARKER), "{reason}");
    assert!(
        reason.contains("exited 1 (detail withheld)"),
        "the safe fact is kept: {reason}"
    );
    assert!(
        env.gaps.iter().all(|g| !g.detail.contains(MARKER)),
        "{:?}",
        env.gaps
    );
    assert!(env.gaps.iter().any(|g| g.kind == GapKind::UntestedVersion));
    let shown = fake.show("thr_syn_0001").expect("still shows");
    assert!(matches!(shown.source.version, Fact::Unknown(_)));
    for args in [
        &["ls"][..],
        &["ls", "--json"][..],
        &["ls", "-l"][..],
        &["show", "thr_syn_0001"][..],
        &["show", "thr_syn_0001", "--json"][..],
    ] {
        let fake = Fake::new(
            &format!("p12_failed_version_cli_{}", args.join("_")),
            "version-failed",
        );
        let (code, out, err) = fake.cli(args);
        assert_eq!(code, 0, "openwiz {args:?}: {err}");
        assert!(
            !out.contains(MARKER) && !err.contains(MARKER),
            "openwiz {args:?}: {out}{err}"
        );
        assert!(
            out.contains("exited 1 (detail withheld)"),
            "openwiz {args:?}: {out}"
        );
    }
}

#[test]
fn missing_fields_are_reported_by_session_and_field() {
    let fake = Fake::new("p12_missing_fields", "thread-list-missing-fields");
    let env = fake
        .list(&ListRequest::default())
        .expect("honest partial list");
    assert_eq!(env.coverage.state, Completeness::Partial);
    for (id, field) in [
        ("thr_syn_0002", "status"),
        ("thr_syn_0003", "parentThreadId"),
        ("thr_syn_0004", "updatedAt"),
        ("thr_syn_0005", "projectId"),
    ] {
        assert!(
            env.gaps.iter().any(|g| g.kind == GapKind::MissingField
                && g.subject.as_deref().is_some_and(|s| s.contains(id))
                && g.detail.contains(field)),
            "no missing-field gap for {id} {field}: {:?}",
            env.gaps
        );
    }
}

#[test]
fn mistyped_fields_are_reported_by_session_and_field() {
    let fake = Fake::new("p12_mistyped_fields", "thread-list-wrong-types");
    let env = fake
        .list(&ListRequest::default())
        .expect("honest partial list");
    for (id, field) in [
        ("thr_syn_0001", "status"),
        ("thr_syn_0002", "updatedAt"),
        ("thr_syn_0003", "projectId"),
        ("thr_syn_0004", "purpose.text"),
        ("thr_syn_0005", "parentThreadId"),
        ("thr_syn_0006", "executionTarget"),
    ] {
        assert!(
            env.gaps.iter().any(|g| g.kind == GapKind::WrongType
                && g.subject.as_deref().is_some_and(|s| s.contains(id))
                && g.detail.contains(field)),
            "no wrong-type gap for {id} {field}: {:?}",
            env.gaps
        );
    }
}

#[test]
fn unknown_extra_fields_are_tolerated() {
    let normal = Fake::new("p12_extra_fields_normal", "normal")
        .list(&long())
        .expect("normal list");
    let extra = Fake::new("p12_extra_fields", "unknown-fields")
        .list(&long())
        .expect("list with extra fields");
    assert_eq!(extra.coverage.state, Completeness::Complete);
    assert_eq!(extra.data, normal.data, "extra fields change nothing");
}

fn normal_with_raw_response(test: &str, argv: &[&str], raw: &str) -> Fake {
    let fake = Fake::new(test, "normal");
    let scenario = serde_json::json!({
        "extends": concat!(env!("CARGO_MANIFEST_DIR"), "/fixtures/room-cli-0.43.1/normal"),
        "synthetic_assumptions": ["Synthetic duplicate keys or mistyped parent fields, never observed live."],
        "responses": [{"argv": argv, "stdout": raw}]
    });
    let path = fake.dir.join("scenario.json");
    std::fs::write(&path, scenario.to_string()).expect("raw response scenario");
    std::fs::write(
        fake.dir.join("fake-room-cli.scenario"),
        path.to_str().unwrap(),
    )
    .expect("scenario pointer");
    fake
}

#[test]
fn contradictory_status_keys_never_become_complete_known_facts() {
    let original = include_str!("../fixtures/room-cli-0.43.1/normal/thread-list.json");
    let argv = &["thread", "list", "--json"];
    let control = normal_with_raw_response("p12_duplicate_control", argv, original)
        .cli_json(&["ls", "--json"]);
    assert_eq!(control["coverage"]["state"], "complete");
    assert_eq!(control["gaps"], serde_json::json!([]));
    let mut failures = Vec::new();
    for (i, pair) in [
        r#""status": "active", "status": "idle""#,
        r#""status": "idle", "status": "active""#,
        r#""status": "idle", "status": "idle""#,
        r#""status": "active", "sta\u0074us": "idle""#,
        r#""status": "idle", "syntheticExtra": {"syntheticPrivateKey": 1, "syntheticPrivateKey": 2}"#,
        r#""status": "idle", "syntheticExtra": [{"syntheticPrivateKey": null, "syntheticPrivateKey": null}]"#,
    ]
    .into_iter()
    .enumerate()
    {
        let rows = original.replacen(r#""status": "idle""#, pair, 1);
        assert_ne!(rows, original, "the contradictory keys were planted");
        let fake = normal_with_raw_response(&format!("p12_duplicate_order_{i}"), argv, &rows);
        let (code, out, err) = fake.cli(&["ls", "--json"]);
        if code != 1 || !out.is_empty()
            || !err.starts_with("openwiz: thread list returned malformed output: ")
            || err.lines().count() != 1 || err.contains("syntheticPrivateKey")
        {
            let observed = if code == 0 {
            let doc: serde_json::Value = serde_json::from_str(&out).expect("inventory JSON");
            let sessions = doc["data"]["sessions"].as_array().expect("sessions");
            let status = &sessions.iter().find(|s| s["id"] == "thr_syn_0001").unwrap()["status"];
                format!(
                    "coverage={}, gaps={}, status={status}",
                    doc["coverage"]["state"],
                    doc["gaps"].as_array().unwrap().len()
                )
        } else {
                format!("exit={code}, stdout={out:?}, stderr={err:?}")
        };
            failures.push(format!("order {i}: {pair}: {observed}"));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn duplicate_keys_in_other_reads_leave_unaffected_inventory_available() {
    let normal = std::path::Path::new(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/fixtures/room-cli-0.43.1/normal"
    ));
    for (i, (file, argv, command)) in [
        (
            "project-list.json",
            vec!["project", "list", "--json", "--include-personal"],
            vec!["ls", "--json"],
        ),
        (
            "machine-list.json",
            vec!["machine", "list", "--json"],
            vec!["ls", "--json"],
        ),
        (
            "thread-show-0001.json",
            vec!["thread", "show", "thr_syn_0001", "--json"],
            vec!["ls", "-l", "--json"],
        ),
        (
            "thread-output-0001.json",
            vec!["thread", "output", "thr_syn_0001", "--json"],
            vec!["show", "thr_syn_0001", "--json"],
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let original = std::fs::read_to_string(normal.join(file)).unwrap();
        let raw = original.replacen(
            '{',
            r#"{"syntheticPrivateKey": "Synthetic private value", "syntheticPrivateKey": null,"#,
            1,
        );
        let fake = normal_with_raw_response(&format!("p12_other_duplicate_{i}"), &argv, &raw);
        let doc = fake.cli_json(&command);
        assert_eq!(doc["coverage"]["state"], "partial", "{file}");
        let gaps = doc["gaps"].as_array().unwrap();
        assert_eq!(gaps.len(), 1, "{file}: {gaps:?}");
        assert_eq!(gaps[0]["kind"], "malformed", "{file}");
        assert!(!doc.to_string().contains("syntheticPrivateKey"));
        assert!(!doc.to_string().contains("Synthetic private value"));
        if command[0] == "ls" {
            assert_eq!(doc["data"]["sessions"].as_array().unwrap().len(), 6);
        } else {
            assert_eq!(doc["data"]["session"]["id"], "thr_syn_0001");
        }
    }
}

#[test]
fn absent_optional_fields_keep_inventory_defaults_and_host_fallback() {
    let fake = normal_with_thread_list("p12_optional_fields", |rows| {
        let row = rows[0].as_object_mut().unwrap();
        row.remove("purpose");
        row.remove("executionTarget");
        row.insert("environmentHostId".into(), "mch_syn_0001".into());
    });
    let doc = fake.cli_json(&["ls", "--json"]);
    assert_eq!(doc["coverage"]["state"], "complete");
    assert_eq!(doc["gaps"], serde_json::json!([]));
    let sessions = doc["data"]["sessions"].as_array().unwrap();
    assert_eq!(sessions.len(), 6);
    let row = sessions.iter().find(|s| s["id"] == "thr_syn_0001").unwrap();
    assert_eq!(
        row["recap"],
        serde_json::json!({"known": {"kind": "no_recap_yet"}})
    );
    assert_eq!(
        row["location"],
        serde_json::json!({"known": {
            "kind": "local", "machine": {"known": "Synthetic machine one"}
        }})
    );
}

#[test]
fn missing_detail_fields_are_reported_by_session_and_field() {
    let fake = Fake::new("p12_missing_detail_fields", "show-missing-fields");
    let env = fake.list(&long()).expect("ls -l");
    for (id, field) in [
        ("thr_syn_0001", "model"),
        ("thr_syn_0006", "reasoningLevel"),
    ] {
        assert!(
            env.gaps.iter().any(|g| g.kind == GapKind::MissingField
                && g.subject.as_deref().is_some_and(|s| s.contains(id))
                && g.detail.contains(field)),
            "no missing-field gap for {id} {field}: {:?}",
            env.gaps
        );
    }
}

fn normal_with_thread_list(test: &str, edit: impl Fn(&mut serde_json::Value)) -> Fake {
    use serde_json::Value;
    use std::fs;
    let fake = Fake::new(test, "normal");
    let normal = std::path::Path::new(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/fixtures/room-cli-0.43.1/normal"
    ));
    let read = |name: &str| -> Value {
        serde_json::from_str(&fs::read_to_string(normal.join(name)).expect(name)).expect(name)
    };
    let mut rows = read("thread-list.json");
    edit(&mut rows);
    let rows_file = fake.dir.join("thread-list-edited.json");
    fs::write(&rows_file, rows.to_string()).expect("rows");
    let mut scenario = read("scenario.json");
    for response in scenario["responses"].as_array_mut().expect("responses") {
        if response["argv"] == serde_json::json!(["thread", "list", "--json"]) {
            response["stdout_file"] = Value::from(rows_file.to_str().expect("utf-8"));
        } else if let Some(file) = response["stdout_file"].as_str() {
            let absolute = normal.join(file);
            response["stdout_file"] = Value::from(absolute.to_str().expect("utf-8"));
        }
    }
    let scenario_file = fake.dir.join("scenario.json");
    fs::write(&scenario_file, scenario.to_string()).expect("scenario");
    fs::write(
        fake.dir.join("fake-room-cli.scenario"),
        scenario_file.to_str().expect("utf-8"),
    )
    .expect("pointer");
    fake
}

#[test]
fn unrecognised_values_are_reported_as_drift() {
    let fake = normal_with_thread_list("p12_unrecognised_values", |rows| {
        rows[0]["visibility"] = "synthetic-private".into();
        rows[5]["executionTarget"] = "synthetic-elsewhere".into();
    });
    let env = fake
        .list(&ListRequest::default())
        .expect("honest partial list");
    assert_eq!(env.coverage.state, Completeness::Partial);
    unknown_reason(&session(&env, "thr_syn_0001").hidden);
    unknown_reason(&session(&env, "thr_syn_0006").location);
    for (id, field) in [
        ("thr_syn_0001", "visibility"),
        ("thr_syn_0006", "executionTarget"),
    ] {
        assert!(
            env.gaps.iter().any(|g| g.kind == GapKind::WrongType
                && g.subject.as_deref().is_some_and(|s| s.contains(id))
                && g.detail.contains(field)),
            "no drift gap for {id} {field}: {:?}",
            env.gaps
        );
    }
}

#[test]
fn nullable_parent_preserves_primitive_type_drift_at_adapter_reads() {
    use openwiz_core::model::SessionId;
    use openwiz_core::source::{Placement, SessionScope, SessionSource};
    use serde_json::{Value, json};
    use std::time::{Duration, Instant};

    let original: Value = serde_json::from_str(include_str!(
        "../fixtures/room-cli-0.43.1/normal/thread-show-0001.json"
    ))
    .unwrap();
    let id = SessionId("thr_syn_0001".into());
    for (i, (parent, expected)) in [
        (json!(true), None),
        (json!(false), None),
        (json!(-1), None),
        (json!(1.25), None),
        (Value::Null, Some(None)),
        (
            json!("thr_syn_parent_1"),
            Some(Some(SessionId("thr_syn_parent_1".into()))),
        ),
    ]
    .into_iter()
    .enumerate()
    {
        for detail in [false, true] {
            let mut doc = original.clone();
            doc["thread"]["parentThreadId"] = parent.clone();
            let (argv, raw, field, read) = if detail {
                (
                    vec!["thread", "show", &id.0, "--json"],
                    doc.to_string(),
                    "thread.parentThreadId",
                    "thread show",
                )
            } else {
                (
                    vec!["thread", "list", "--json"],
                    json!([doc["thread"]]).to_string(),
                    "parentThreadId",
                    "thread list",
                )
            };
            let fake = normal_with_raw_response(&format!("p12_parent_{i}_{detail}"), &argv, &raw);
            let source = fake.source();
            let deadline = Instant::now() + Duration::from_secs(5);
            let record = if detail {
                source.session_detail(&id, deadline).unwrap().session
            } else {
                let mut rows = source
                    .list_sessions(
                        SessionScope {
                            include_hidden: false,
                            include_archived: false,
                        },
                        deadline,
                    )
                    .unwrap();
                assert!(rows.unreadable.is_empty(), "{:?}", rows.unreadable);
                assert_eq!(rows.records.len(), 1);
                rows.records.remove(0)
            };
            assert_eq!(record.id, id);
            assert_eq!(record.placement, Fact::Known(Placement::Cloud));
            if let Some(expected) = &expected {
                assert_eq!(&record.parent, &Fact::Known(expected.clone()));
                assert!(record.problems.is_empty(), "{:?}", record.problems);
            } else {
                assert_eq!(
                    record.parent,
                    Fact::Unknown(format!("schema: {field}")),
                    "{read}, parent={parent}"
                );
                assert_eq!(
                    record.problems,
                    vec![openwiz_core::envelope::Gap {
                        kind: GapKind::WrongType,
                        subject: Some(id.0.clone()),
                        detail: format!("schema drift: {read} {field}"),
                    }]
                );
            }
        }
    }
}
