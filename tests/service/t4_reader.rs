//! Independent schema checker versus the service's strict public reader.
#[path = "../fleet/schema.rs"]
mod schema;

use openwiz_service::document::{self, Document};
use serde_json::{Value, json};

const CONTRACT: &str = include_str!("../../contracts/service.v1.md");
const SCHEMA: &str = include_str!("../../contracts/service.v1.schema.json");

fn example(kind: &str) -> Value {
    CONTRACT
        .lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .find(|v| v["schema"] == kind)
        .unwrap()
}

#[test]
fn service_reader_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 10] = [
        (
            "config_state_and_status_obey_the_same_shape_as_the_schema",
            config_state_and_status_obey_the_same_shape_as_the_schema,
        ),
        (
            "duplicate_fields_at_every_depth_are_refused_without_echoing_values",
            duplicate_fields_at_every_depth_are_refused_without_echoing_values,
        ),
        (
            "fix_attempt_timestamp_is_at_or_after_incident_opening",
            fix_attempt_timestamp_is_at_or_after_incident_opening,
        ),
        (
            "health_pass_must_include_a_tick_result",
            health_pass_must_include_a_tick_result,
        ),
        (
            "persisted_comments_require_saved_outcomes",
            persisted_comments_require_saved_outcomes,
        ),
        (
            "persisted_needs_you_requires_both_completed_tries",
            persisted_needs_you_requires_both_completed_tries,
        ),
        (
            "persisted_state_must_keep_the_contracts_cross_field_rules",
            persisted_state_must_keep_the_contracts_cross_field_rules,
        ),
        (
            "state_reader_requires_cloudroom_as_the_first_health_result",
            state_reader_requires_cloudroom_as_the_first_health_result,
        ),
        (
            "status_reader_requires_fixes_to_name_open_incidents",
            status_reader_requires_fixes_to_name_open_incidents,
        ),
        (
            "unread_checks_exclude_subject_results",
            unread_checks_exclude_subject_results,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: {name}");
        proof();
    }
}

fn persisted_needs_you_requires_both_completed_tries() {
    let good = example("openwiz.service-state.v1");
    let first = good["incidents"][1]["tries"]["first"].clone();
    let second = good["incidents"][1]["tries"]["second"].clone();
    let mut pending_first = first.clone();
    pending_first["outcome"] = Value::Null;
    pending_first["comment"] = Value::Null;
    let mut pending_second = second.clone();
    pending_second["outcome"] = Value::Null;
    pending_second["comment"] = Value::Null;

    // S4 permits Needs you only after both tries have their outcomes.
    for (label, tries, accepts_needs_you) in [
        ("no tries", json!({"first": null, "second": null}), false),
        (
            "first still running",
            json!({"first": pending_first, "second": null}),
            false,
        ),
        (
            "only first completed",
            json!({"first": first, "second": null}),
            false,
        ),
        (
            "second still running",
            json!({"first": first, "second": pending_second}),
            false,
        ),
        (
            "both completed",
            json!({"first": first, "second": second}),
            true,
        ),
    ] {
        let mut value = good.clone();
        value["incidents"][1]["tries"] = tries;
        assert!(
            document::read(Document::State, &value.to_string()).is_ok(),
            "{label} is valid without Needs you"
        );
        value["incidents"][1]["needs_you"] =
            json!({"at": 1767229500000u64, "op_id": "synthetic_op", "comment": null});
        assert_eq!(
            document::read(Document::State, &value.to_string()).is_ok(),
            accepts_needs_you,
            "{label}: Needs you requires both completed tries"
        );
    }
}

fn config_state_and_status_obey_the_same_shape_as_the_schema() {
    let schema: Value = serde_json::from_str(SCHEMA).unwrap();
    assert!(schema::lint(&schema).is_empty());
    for (kind, name) in [
        (Document::Config, "openwiz.service-config.v1"),
        (Document::State, "openwiz.service-state.v1"),
        (Document::Status, "openwiz.service-status.v1"),
    ] {
        let good = example(name);
        let mut cases = vec![
            (good.clone(), true),
            (json!([]), false),
            (json!(null), false),
        ];
        for key in good.as_object().unwrap().keys() {
            let mut missing = good.clone();
            missing.as_object_mut().unwrap().remove(key);
            cases.push((missing, false));
        }
        let mut extra = good.clone();
        extra["extra"] = json!("synthetic");
        cases.push((extra, false));
        let mut wrong_schema = good.clone();
        wrong_schema["schema"] = json!({"openwiz.service-config.v1": null});
        cases.push((wrong_schema, false));
        if matches!(kind, Document::Config) {
            for bad in [json!(0), json!(1.0), json!("1"), json!(true), json!(-1)] {
                let mut value = good.clone();
                value["tick"]["every_s"] = bad;
                cases.push((value, false));
            }
            for bad in [json!("-bad"), json!("é"), json!(""), json!("x".repeat(129))] {
                let mut value = good.clone();
                value["project"] = bad;
                cases.push((value, false));
            }
            let mut positional = good.clone();
            positional["github_app"] = json!([1001, 2002]);
            cases.push((positional, false));
        }
        for (value, expected) in cases {
            assert_eq!(
                schema::validate(&schema, &value).is_empty(),
                expected,
                "schema: {value}"
            );
            assert_eq!(
                document::read(kind, &value.to_string()).is_ok(),
                expected,
                "reader: {value}"
            );
        }
    }
}

fn fix_attempt_timestamp_is_at_or_after_incident_opening() {
    let good = example("openwiz.service-state.v1");
    // S3 boundary from the contract's synthetic incident, with no second try.
    assert_eq!(
        good["incidents"][0]["opened_at"],
        json!(1_767_229_320_000_u64)
    );
    assert!(good["incidents"][0]["tries"]["second"].is_null());
    for (at, accepted) in [
        (1_767_229_319_999_u64, false),
        (1_767_229_320_000_u64, true),
        (1_767_229_320_001_u64, true),
    ] {
        let mut value = good.clone();
        value["incidents"][0]["tries"]["first"]["at"] = json!(at);
        assert_eq!(
            document::read(Document::State, &value.to_string()).is_ok(),
            accepted,
            "S3: first attempt at {at}"
        );
    }
}

fn duplicate_fields_at_every_depth_are_refused_without_echoing_values() {
    let text = example("openwiz.service-config.v1").to_string();
    for bad in [
        text.replacen("{", "{\"schema\":\"synthetic-secret\",", 1),
        text.replacen("\"every_s\":300", "\"every_s\":300,\"every_s\":300", 1),
        text.replacen("\"owner\":", "\"owner\":\"synthetic-secret\",\"owner\":", 1),
    ] {
        assert_ne!(bad, text);
        let error = document::read(Document::Config, &bad).expect_err("duplicate key");
        assert!(!error.contains("synthetic-secret"));
    }
    assert!(document::read(Document::Config, &(text + " null")).is_err());
}

fn unread_checks_exclude_subject_results() {
    let mut value = example("openwiz.service-state.v1");
    assert!(document::read(Document::State, &value.to_string()).is_ok());

    // S1: an unread check has no other result, even a unique healthy subject.
    value["last_pass"]["results"]
        .as_array_mut()
        .unwrap()
        .push(json!({
            "check": "loop",
            "loop": {
                "id": "loop_syn_0001",
                "name": "launch-fleet synthetic-owner/synthetic-repo"
            },
            "observed": {"state": "healthy"}
        }));
    assert!(
        document::read(Document::State, &value.to_string()).is_err(),
        "unread check has subject result"
    );
}

fn health_pass_must_include_a_tick_result() {
    let mut state = example("openwiz.service-state.v1");
    assert!(document::read(Document::State, &state.to_string()).is_ok());

    state["last_pass"]["results"]
        .as_array_mut()
        .unwrap()
        .retain(|result| result["check"] != "tick");

    assert!(
        document::read(Document::State, &state.to_string()).is_err(),
        "a health pass missing its tick result must be refused"
    );
}

fn persisted_comments_require_saved_outcomes() {
    for (incident, attempt) in [(0, "first"), (1, "second")] {
        let mut value = example("openwiz.service-state.v1");
        assert!(
            document::read(Document::State, &value.to_string()).is_ok(),
            "a completed {attempt} try with a saved comment is valid"
        );

        value["incidents"][incident]["tries"][attempt]["outcome"] = Value::Null;
        assert!(
            document::read(Document::State, &value.to_string()).is_err(),
            "a {attempt} comment cannot precede its saved outcome"
        );

        value["incidents"][incident]["tries"][attempt]["comment"] = Value::Null;
        assert!(
            document::read(Document::State, &value.to_string()).is_ok(),
            "a pending {attempt} try without a comment is valid"
        );
    }
}

fn persisted_state_must_keep_the_contracts_cross_field_rules() {
    let good = example("openwiz.service-state.v1");
    let mut cases = Vec::new();
    let mut v = good.clone();
    v["next_incident"] = json!(3);
    cases.push(v);
    let mut v = good.clone();
    v["incidents"]
        .as_array_mut()
        .unwrap()
        .push(good["incidents"][0].clone());
    cases.push(v);
    let mut v = good.clone();
    v["incidents"][0]["id"] = good["incidents"][1]["id"].clone();
    cases.push(v);
    let mut v = good.clone();
    v["tick"]["last_ended"]["ended_at"] = json!(0);
    cases.push(v);
    let mut v = good.clone();
    v["incidents"][1]["tries"]["first"] = Value::Null;
    cases.push(v);
    let mut v = good.clone();
    v["incidents"][1]["tries"]["second"]["at"] = json!(0);
    cases.push(v);
    let mut v = good.clone();
    v["last_pass"]["results"]
        .as_array_mut()
        .unwrap()
        .push(good["last_pass"]["results"][0].clone());
    cases.push(v);
    let mut v = good.clone();
    v["last_pass"]["needs_you"] = json!(["i999"]);
    cases.push(v);
    for value in cases {
        assert!(
            document::read(Document::State, &value.to_string()).is_err(),
            "{value}"
        );
    }
    let mut status = example("openwiz.service-status.v1");
    status["service"]["since"] = json!(u64::MAX);
    assert!(document::read(Document::Status, &status.to_string()).is_err());
    let mut status = example("openwiz.service-status.v1");
    status["service"]["build"] = json!("0".repeat(40));
    assert!(document::read(Document::Status, &status.to_string()).is_err());
}

#[test]
fn kept_update_retains_the_old_running_build() {
    let mut status = example("openwiz.service-status.v1");
    status["update"]["outcome"] = json!({
        "state": "kept",
        "step": "test",
        "reason": "synthetic test failure"
    });
    status["service"]["build"] = json!("fedcba9876543210fedcba9876543210fedcba98");
    assert!(
        document::read(Document::Status, &status.to_string()).is_ok(),
        "kept update accepts the old running build"
    );

    status["service"]["build"] = json!("0123456789abcdef0123456789abcdef01234567");
    assert!(
        document::read(Document::Status, &status.to_string()).is_err(),
        "kept update rejects the proposed new build"
    );
}

fn state_reader_requires_cloudroom_as_the_first_health_result() {
    let mut state = example("openwiz.service-state.v1");
    state["last_pass"]["results"]
        .as_array_mut()
        .unwrap()
        .swap(0, 1);
    assert!(
        document::read(Document::State, &state.to_string()).is_err(),
        "cloudroom must be first"
    );
}

fn status_reader_requires_fixes_to_name_open_incidents() {
    let mut status = CONTRACT
        .lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .find(|v| {
            v["schema"] == "openwiz.service-status.v1"
                && v["last_pass"]["fixes"]
                    .as_array()
                    .is_some_and(|fixes| !fixes.is_empty())
        })
        .expect("contract status with a saved fix");
    document::read(Document::Status, &status.to_string())
        .expect("valid contract status with a fix naming an open incident");
    assert!(
        status["incidents"]
            .as_array()
            .unwrap()
            .iter()
            .all(|incident| incident["id"] != "i999")
    );

    status["last_pass"]["fixes"][0]["incident"] = json!("i999");
    assert!(
        document::read(Document::Status, &status.to_string()).is_err(),
        "S7: a fix must name an open incident"
    );
}

/// 2141's explicit pair is optional; each configured role is a strict repo,
/// and roles cannot point at the same repository under case folding.
#[test]
fn explicit_decision_repositories_are_strict_and_optional() {
    let schema: Value = serde_json::from_str(SCHEMA).unwrap();
    let base = example("openwiz.service-config.v1");
    assert!(document::read(Document::Config, &base.to_string()).is_ok());
    let pair = json!({"public":{"owner":"synthetic-public","name":"work"},"private":{"owner":"synthetic-records","name":"decisions"}});
    let mut good = base.clone();
    good["decision_repositories"] = pair.clone();
    assert!(
        document::read(Document::Config, &good.to_string()).is_ok(),
        "explicit roles must be accepted"
    );
    assert!(schema::validate(&schema, &good).is_empty());
    // The schema and reader accept the same ordinary path names, including
    // leading dots, but neither accepts the special dot path components.
    for name in ["a", "ab", ".a", "..a", "...", ".work", "-work", "_"] {
        let mut value = good.clone();
        value["decision_repositories"]["public"]["name"] = json!(name);
        assert!(
            document::read(Document::Config, &value.to_string()).is_ok(),
            "{name}"
        );
        assert!(schema::validate(&schema, &value).is_empty(), "{name}");
    }
    for name in [".", ".."] {
        let mut value = good.clone();
        value["decision_repositories"]["public"]["name"] = json!(name);
        assert!(document::read(Document::Config, &value.to_string()).is_err());
        assert!(
            !schema::validate(&schema, &value).is_empty(),
            "schema accepted {name}"
        );
    }
    for bad in [
        json!({"public":{"owner":"synthetic-public","name":".."},"private":pair["private"]}),
        json!(null),
        json!([]),
        json!({"public":pair["public"]}),
        json!({"public":pair["public"],"private":pair["private"],"extra":true}),
        json!({"public":{"owner":"-bad","name":"work"},"private":pair["private"]}),
        json!({"public":pair["public"],"private":{"owner":"SYNTHETIC-PUBLIC","name":"WORK"}}),
    ] {
        let mut value = base.clone();
        value["decision_repositories"] = bad;
        assert!(
            document::read(Document::Config, &value.to_string()).is_err(),
            "{value}"
        );
    }
    let duplicate = good.to_string().replace(
        "\"decision_repositories\":",
        "\"decision_repositories\":{},\"decision_repositories\":",
    );
    assert!(document::read(Document::Config, &duplicate).is_err());
}
