use openwiz_core::model::{Fact, Timestamp};
use openwiz_core::ops::ListRequest;

use crate::support::*;

#[test]
fn snapshot_time_and_source_version_are_reported() {
    let fake = Fake::new("p02_snapshot_time_and_source_version", "normal");
    let env = fake.list(&ListRequest::default()).expect("normal list");
    assert_eq!(env.freshness.snapshot_at, T0);
    assert_eq!(env.source.name, "room-cli");
    assert_eq!(env.source.version, Fact::Known("v127".to_owned()));
    assert_eq!(env.source.tested_version, "v127");
    assert!(env.source.version_tested);
}

#[test]
fn each_row_has_its_age_from_the_snapshot() {
    let fake = Fake::new("p02_each_row_has_its_age", "normal");
    let env = fake.list(&ListRequest::default()).expect("normal list");
    for (i, id) in DEFAULT_IDS.iter().enumerate() {
        let s = session(&env, id);
        let age = 60_000 * (i as i64 + 1);
        assert_eq!(s.updated_at, Fact::Known(Timestamp(T0.0 - age)), "{id}");
        assert_eq!(s.age_ms, Fact::Known(age), "{id}");
    }
}

#[test]
fn an_out_of_range_update_time_gives_an_unknown_age() {
    let mut records: Vec<_> = (1..=2).map(scripted_record).collect();
    records[0].updated_at = Fact::Known(Timestamp(i64::MIN));
    records[1].updated_at = Fact::Known(Timestamp(i64::MAX));
    let source = ScriptedSource::with_records(records);
    let env = list_scripted(&source, &ListRequest::default()).expect("list");
    unknown_reason(&session(&env, "thr_syn_0001").age_ms);
    assert_eq!(
        session(&env, "thr_syn_0002").age_ms,
        Fact::Known(T0.0 - i64::MAX),
        "an age that fits stays known"
    );
    let (code, text, err) = cli_with(&source, &["ls"]);
    assert_eq!(code, 0, "{err}");
    assert!(
        row_lines(&text, "thr_syn_0001")
            .iter()
            .any(|l| l.contains("age unknown (")),
        "{text}"
    );
}

#[test]
fn visibility_is_known_only_for_hidden_and_visible_at_adapter_reads() {
    use openwiz_core::envelope::GapKind;
    use openwiz_core::model::SessionId;
    use openwiz_core::source::{Placement, SessionScope, SessionSource};
    use serde_json::{Value, json};
    use std::time::{Duration, Instant};

    let original: Value = serde_json::from_str(include_str!(
        "../fixtures/room-cli-0.43.1/normal/thread-show-0001.json"
    ))
    .unwrap();
    let id = SessionId("thr_syn_0001".into());
    for (i, (visibility, known, gap)) in [
        (Some(json!("hidden")), Some(true), None),
        (Some(json!("visible")), Some(false), None),
        (
            Some(json!("synthetic-other")),
            None,
            Some(GapKind::WrongType),
        ),
        (None, None, Some(GapKind::MissingField)),
        (Some(json!(42)), None, Some(GapKind::WrongType)),
    ]
    .into_iter()
    .enumerate()
    {
        for detail in [false, true] {
            let mut doc = original.clone();
            let thread = doc["thread"].as_object_mut().unwrap();
            thread.remove("visibility");
            if let Some(value) = &visibility {
                thread.insert("visibility".into(), value.clone());
            }
            let (argv, raw, field) = if detail {
                (
                    vec!["thread", "show", &id.0, "--json"],
                    doc.to_string(),
                    "thread.visibility",
                )
            } else {
                (
                    vec!["thread", "list", "--json", "--include-hidden"],
                    json!([doc["thread"]]).to_string(),
                    "visibility",
                )
            };
            let fake = Fake::new(&format!("p02_visibility_{i}_{detail}"), "normal");
            let scenario = json!({
                "synthetic_assumptions": ["Synthetic visibility drift cases, never observed live."],
                "responses": [{"argv": argv, "stdout": raw}]
            });
            let path = fake.dir.join("scenario.json");
            std::fs::write(&path, scenario.to_string()).unwrap();
            std::fs::write(
                fake.dir.join("fake-room-cli.scenario"),
                path.to_str().unwrap(),
            )
            .unwrap();
            let source = fake.source();
            let deadline = Instant::now() + Duration::from_secs(5);
            let record = if detail {
                source.session_detail(&id, deadline).unwrap().session
            } else {
                let mut rows = source
                    .list_sessions(
                        SessionScope {
                            include_hidden: true,
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
            if let Some(hidden) = known {
                assert_eq!(
                    record.hidden,
                    Fact::Known(hidden),
                    "{detail}: {visibility:?}"
                );
                assert!(record.problems.is_empty(), "{:?}", record.problems);
            } else {
                assert!(matches!(record.hidden, Fact::Unknown(_)));
                assert_eq!(record.problems.len(), 1, "{:?}", record.problems);
                let problem = &record.problems[0];
                assert_eq!(Some(problem.kind), gap);
                assert_eq!(problem.subject.as_deref(), Some(id.0.as_str()));
                assert!(problem.detail.contains(field), "{problem:?}");
            }
        }
    }
}
