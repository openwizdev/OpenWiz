//! PA1–PA7 interface proofs only. All examples are synthetic.
#![allow(dead_code)]

#[path = "../support/schema.rs"]
mod schema;

use serde_json::{Value, json};

fn notification_schema() -> Value {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../contracts/notifications.v1.schema.json"
    );
    let text = std::fs::read_to_string(path).expect("T1: notification schema must exist");
    serde_json::from_str(&text).expect("notification schema is JSON")
}

#[test]
fn notification_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 13] = [
        (
            "boundary_records_only_explicit_fixture_results_and_unavailable_has_no_effect",
            boundary_records_only_explicit_fixture_results_and_unavailable_has_no_effect,
        ),
        (
            "defaults_are_off_with_only_decision_and_recovery_categories_selected",
            defaults_are_off_with_only_decision_and_recovery_categories_selected,
        ),
        (
            "group_keys_bind_proposals_and_owner_incidents_without_poll_or_comment_identity",
            group_keys_bind_proposals_and_owner_incidents_without_poll_or_comment_identity,
        ),
        (
            "journal_transition_contract_requires_reservation_and_bound_reconciliation",
            journal_transition_contract_requires_reservation_and_bound_reconciliation,
        ),
        (
            "request_identity_uses_the_existing_decision_grammar",
            request_identity_uses_the_existing_decision_grammar,
        ),
        (
            "review_r1_unread_stock_counts_require_project_and_factory_gaps",
            review_r1_unread_stock_counts_require_project_and_factory_gaps,
        ),
        (
            "review_r2_unknown_category_availability_requires_status_gaps",
            review_r2_unknown_category_availability_requires_status_gaps,
        ),
        (
            "schema_and_strict_types_agree_on_all_examples_and_nested_shape_mutations",
            schema_and_strict_types_agree_on_all_examples_and_nested_shape_mutations,
        ),
        (
            "semantic_checks_refuse_false_coverage_counts_and_outcome_claims",
            semantic_checks_refuse_false_coverage_counts_and_outcome_claims,
        ),
        (
            "shared_contract_extensions_consume_the_same_typed_examples",
            shared_contract_extensions_consume_the_same_typed_examples,
        ),
        (
            "strict_notification_contract_exists_and_refuses_unknown_records",
            strict_notification_contract_exists_and_refuses_unknown_records,
        ),
        (
            "unknown_enums_bindings_and_private_payload_fields_are_refused",
            unknown_enums_bindings_and_private_payload_fields_are_refused,
        ),
        (
            "unknown_required_source_facts_cannot_claim_complete_coverage",
            unknown_required_source_facts_cannot_claim_complete_coverage,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: contract::{name}");
        proof();
    }
}

fn strict_notification_contract_exists_and_refuses_unknown_records() {
    let rules = notification_schema();
    assert_eq!(schema::lint(&rules), Vec::<String>::new());
    for bad in [
        json!(null),
        json!([]),
        json!({}),
        json!({"schema":"openwiz.notifications.v1", "record":{"unknown":{}}}),
    ] {
        assert!(!schema::validate(&rules, &bad).is_empty(), "accepted {bad}");
    }
}

use openwiz_core::notifications::{boundary::*, model::*};

fn fixtures() -> Value {
    let text = include_str!("../fixtures/notifications/contract/README.md");
    serde_json::from_str(
        text.split("```json\n")
            .nth(1)
            .unwrap()
            .split("\n```")
            .next()
            .unwrap(),
    )
    .unwrap()
}

fn objects(value: &Value, path: String, out: &mut Vec<String>) {
    match value {
        Value::Object(fields) => {
            out.push(path.clone());
            for (key, child) in fields {
                objects(child, format!("{path}/{key}"), out);
            }
        }
        Value::Array(items) => {
            for (index, child) in items.iter().enumerate() {
                objects(child, format!("{path}/{index}"), out);
            }
        }
        _ => {}
    }
}

fn agrees(rules: &Value, value: &Value, expected: bool) {
    assert_eq!(
        schema::validate(rules, value).is_empty(),
        expected,
        "schema: {value}"
    );
    assert_eq!(
        serde_json::from_value::<Document>(value.clone()).is_ok(),
        expected,
        "reader: {value}"
    );
}

fn schema_and_strict_types_agree_on_all_examples_and_nested_shape_mutations() {
    let rules = notification_schema();
    for (name, good) in fixtures().as_object().unwrap() {
        agrees(&rules, good, true);
        let decoded: Document = serde_json::from_value(good.clone()).unwrap();
        assert_eq!(serde_json::to_value(&decoded).unwrap(), *good, "{name}");
        decoded.check().unwrap_or_else(|e| panic!("{name}: {e}"));
        let mut paths = vec![];
        objects(good, String::new(), &mut paths);
        for path in paths {
            let object = good.pointer(&path).unwrap().as_object().unwrap();
            for key in object.keys() {
                let mut missing = good.clone();
                missing
                    .pointer_mut(&path)
                    .unwrap()
                    .as_object_mut()
                    .unwrap()
                    .remove(key);
                agrees(&rules, &missing, false);
            }
            let mut extra = good.clone();
            extra
                .pointer_mut(&path)
                .unwrap()
                .as_object_mut()
                .unwrap()
                .insert("synthetic_extra".into(), json!(true));
            agrees(&rules, &extra, false);
            let mut array = good.clone();
            *array.pointer_mut(&path).unwrap() =
                json!(object.values().cloned().collect::<Vec<_>>());
            agrees(&rules, &array, false);
            // Duplicate wire keys cannot be tested after Value has discarded them.
            if let Some((key, val)) = object.iter().next() {
                let body = serde_json::to_string(&Value::Object(object.clone())).unwrap();
                let duplicate = format!(
                    "{{{}:{},{}",
                    serde_json::to_string(key).unwrap(),
                    val,
                    &body[1..]
                );
                let raw = serde_json::to_string(good)
                    .unwrap()
                    .replacen(&body, &duplicate, 1);
                assert!(
                    serde_json::from_str::<Document>(&raw).is_err(),
                    "duplicate at {name}{path}"
                );
            }
        }
    }
}

fn unknown_enums_bindings_and_private_payload_fields_are_refused() {
    let rules = notification_schema();
    for (name, path, bad) in [
        (
            "decision",
            "/record/source_fact/decision/state",
            json!("unknown_state"),
        ),
        (
            "decision",
            "/record/source_fact/decision/current",
            json!({"known":"true"}),
        ),
        (
            "decision",
            "/record/source_fact/decision/current",
            json!({"unknown":""}),
        ),
        (
            "decision",
            "/record/source_fact/decision/risk",
            json!({"ordinary":null}),
        ),
        (
            "decision",
            "/record/source_fact/decision/binding/repository",
            json!("https://example.invalid/synthetic/repo"),
        ),
        (
            "decision",
            "/record/source_fact/decision/binding/comment_id",
            json!(1.0),
        ),
        (
            "decision",
            "/record/source_fact/decision/binding/subject/number",
            json!(0),
        ),
        (
            "decision",
            "/record/source_fact/decision/binding/fingerprint",
            json!("changed"),
        ),
        (
            "incident",
            "/record/source_fact/incident/binding/source",
            json!("invented_recovery"),
        ),
        (
            "event",
            "/record/source_fact/event/category",
            json!("recovery_escalation"),
        ),
        (
            "outcome-accepted",
            "/record/delivery_outcome/state",
            json!("displayed"),
        ),
        (
            "submission",
            "/record/submission/payload",
            json!({"title":"Synthetic private question","target_token":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}),
        ),
    ] {
        let mut v = fixtures()[name].clone();
        *v.pointer_mut(path).unwrap() = bad;
        agrees(&rules, &v, false);
    }
}

fn defaults_are_off_with_only_decision_and_recovery_categories_selected() {
    let expected = &fixtures()["preferences"]["record"]["preferences"];
    let off = Preferences::off();
    assert_eq!(serde_json::to_value(&off).unwrap(), *expected);
    assert_eq!(Category::ALL.len(), 16);
    for category in Category::ALL {
        assert_eq!(
            off.categories.enabled(category),
            matches!(category, Category::Decision | Category::RecoveryEscalation)
        );
    }
    let status = Status::unavailable();
    assert_eq!(status.state, StatusState::Off);
    assert_eq!(status.capability.state, CapabilityState::Unavailable);
    assert!(
        status
            .sources
            .iter()
            .all(|s| !matches!(s.available, Fact::Known(true)))
    );
    assert_eq!(status.sources.len(), 16);
    assert!(status.latest.is_none());
}

fn boundary_records_only_explicit_fixture_results_and_unavailable_has_no_effect() {
    let request: Document = serde_json::from_value(fixtures()["submission"].clone()).unwrap();
    let Record::Submission(request) = request.record else {
        panic!("fixture")
    };
    let mut unavailable = UnavailableDelivery;
    assert_eq!(unavailable.capability().state, CapabilityState::Unavailable);
    assert_eq!(unavailable.submit(&request).state, OutcomeState::Failed);
    let outcomes = [
        OutcomeState::Pending,
        OutcomeState::Accepted,
        OutcomeState::Failed,
        OutcomeState::Uncertain,
    ];
    let replies = outcomes
        .iter()
        .map(|&state| DeliveryOutcome {
            state,
            reason: Text::new("Synthetic fixture outcome").unwrap(),
        })
        .collect();
    let mut boundary = RecordingDelivery::new(replies);
    for state in outcomes {
        assert_eq!(boundary.submit(&request).state, state);
    }
    assert_eq!(
        boundary.submissions(),
        &[
            request.clone(),
            request.clone(),
            request.clone(),
            request.clone()
        ]
    );
    // Exhausting a script cannot invent a successful provider.
    assert_eq!(boundary.submit(&request).state, OutcomeState::Uncertain);
    assert_eq!(boundary.submissions().len(), 5);
}

fn journal_transition_contract_requires_reservation_and_bound_reconciliation() {
    use DispatchState::*;
    use TransitionCause::*;
    for (before, after, cause, expected) in [
        (Reserved, Submitting, BeforeSubmit, true),
        (Reserved, Accepted, BoundaryReply, false),
        (Reserved, Cancelled, BeforeSubmit, true),
        (Submitting, Uncertain, BoundaryReply, true),
        (Submitting, Accepted, BoundaryReply, true),
        (Pending, Uncertain, BoundaryReply, true),
        (Uncertain, Submitting, BeforeSubmit, false),
        (Uncertain, Failed, BoundaryReply, false),
        (Uncertain, Accepted, BoundReconciliation, true),
        (Uncertain, Failed, BoundReconciliation, true),
        (Accepted, Failed, BoundaryReply, false),
        (Cancelled, Submitting, BeforeSubmit, false),
        (Failed, Submitting, BeforeSubmit, false),
    ] {
        assert_eq!(
            before.permits(after, cause),
            expected,
            "{before:?} -> {after:?}"
        );
    }
}

fn semantic_checks_refuse_false_coverage_counts_and_outcome_claims() {
    for (name, path, bad) in [
        (
            "stock-fed",
            "/record/stock/totals/known/state",
            json!("low_stock"),
        ),
        (
            "stock-idle",
            "/record/stock/totals/known/state",
            json!("fed"),
        ),
        (
            "stock-dry",
            "/record/stock/totals/known/state",
            json!("fed"),
        ),
        (
            "stock-partial",
            "/record/stock/totals",
            fixtures()["stock-fed"]["record"]["stock"]["totals"].clone(),
        ),
        (
            "stock-stale",
            "/record/stock/totals",
            fixtures()["stock-fed"]["record"]["stock"]["totals"].clone(),
        ),
        (
            "dispatch-uncertain",
            "/record/dispatch/outcome/state",
            json!("failed"),
        ),
        (
            "dispatch-reserved",
            "/record/dispatch/outcome",
            json!({"state":"accepted","reason":"Synthetic wrong outcome"}),
        ),
        (
            "decision",
            "/record/source_fact/decision/coverage/gaps",
            json!([{"source":"decisions","reason":"Synthetic missing source"}]),
        ),
    ] {
        let mut v = fixtures()[name].clone();
        *v.pointer_mut(path).unwrap() = bad;
        assert!(
            serde_json::from_value::<Document>(v)
                .unwrap()
                .check()
                .is_err(),
            "{name}{path}"
        );
    }
}

fn group_keys_bind_proposals_and_owner_incidents_without_poll_or_comment_identity() {
    let decoded: Document = serde_json::from_value(fixtures()["decision"].clone()).unwrap();
    let Record::SourceFact(SourceFact::Decision(fact)) = decoded.record else {
        panic!("fixture")
    };
    let reference = Reference::Decision(fact.binding.clone());
    let key = reference.group_key();
    let mut copy = fact.binding.clone();
    copy.comment_id = 903.try_into().unwrap();
    assert_eq!(key, Reference::Decision(copy.clone()).group_key());
    copy.fingerprint =
        Fingerprint::new("cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc")
            .unwrap();
    assert_ne!(key, Reference::Decision(copy).group_key());
    let decoded: Document = serde_json::from_value(fixtures()["incident"].clone()).unwrap();
    let Record::SourceFact(SourceFact::Incident(fact)) = decoded.record else {
        panic!("fixture")
    };
    let key = Reference::Incident(fact.binding.clone()).group_key();
    let mut other = fact.binding;
    other.owner = Id::new("syn_other_owner").unwrap();
    assert_ne!(key, Reference::Incident(other).group_key());
}

fn request_identity_uses_the_existing_decision_grammar() {
    let rules = notification_schema();
    let mut v = fixtures()["decision"].clone();
    *v.pointer_mut("/record/source_fact/decision/binding/request_id")
        .unwrap() = json!("_syn_request");
    agrees(&rules, &v, false);
}

fn shared_contract_extensions_consume_the_same_typed_examples() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../contracts");
    let mut cockpit: Value = serde_json::from_str(
        &std::fs::read_to_string(root.join("cockpit.v1.schema.json")).unwrap(),
    )
    .unwrap();
    let mut service: Value = serde_json::from_str(
        &std::fs::read_to_string(root.join("service.v1.schema.json")).unwrap(),
    )
    .unwrap();
    assert!(schema::lint(&cockpit).is_empty());
    assert!(schema::lint(&service).is_empty());
    cockpit["$ref"] = json!("#/$defs/notification_stock");
    for (name, v) in fixtures().as_object().unwrap() {
        if name.starts_with("stock-") {
            assert!(
                schema::validate(&cockpit, &v["record"]["stock"]).is_empty(),
                "{name}"
            );
        }
    }
    service.as_object_mut().unwrap().remove("oneOf");
    service["$ref"] = json!("#/$defs/notification_runtime");
    let runtime = RuntimeState {
        state: StatusState::Off,
        preference_generation: 0,
        last_pass_at: Fact::Unknown(Text::new("Synthetic no completed pass").unwrap()),
        reason: Text::new("Synthetic unavailable binding").unwrap(),
    };
    let v = serde_json::to_value(&runtime).unwrap();
    assert!(schema::validate(&service, &v).is_empty());
    assert_eq!(serde_json::from_value::<RuntimeState>(v).unwrap(), runtime);
}

fn unknown_required_source_facts_cannot_claim_complete_coverage() {
    // PA1/PA7: unavailable verification or timestamps must carry source gaps.
    // The existing shape tests accepted these internally contradictory records.
    let mut accepted = vec![];
    for (name, path) in [
        ("decision", "/record/source_fact/decision/current"),
        ("incident", "/record/source_fact/incident/owner_escalated"),
        ("event", "/record/source_fact/event/current"),
        ("stock-fed", "/record/stock/freshness"),
        ("stock-fed", "/record/stock/projects/0/freshness"),
    ] {
        let mut value = fixtures()[name].clone();
        if path.ends_with("freshness") {
            *value.pointer_mut(path).unwrap() = json!({"state":"unknown","snapshot_at":{"unknown":"Synthetic required source timestamp unavailable"}});
            value["record"]["stock"]["totals"] =
                json!({"unknown":"Synthetic factory total unavailable"});
        } else {
            *value.pointer_mut(path).unwrap() =
                json!({"unknown":"Synthetic required verification unavailable"});
        }
        let record: Document = serde_json::from_value(value).unwrap();
        if record.check().is_ok() {
            accepted.push(format!("{name}{path}"));
        }
    }
    assert_eq!(
        accepted,
        Vec::<String>::new(),
        "unknown sources accepted without gaps"
    );
}

fn review_r1_unread_stock_counts_require_project_and_factory_gaps() {
    // PA7: unread counts need their own gaps; unknown totals cannot hide them.
    let partial = json!({"state":"partial","gaps":[{"source":"plan","reason":"Synthetic required project facts unread"}]});
    for (case, project_partial, factory_partial, unread_counts, expected) in [
        (
            "fresh unread counts with complete coverage",
            false,
            false,
            true,
            false,
        ),
        (
            "factory gap cannot replace a project gap",
            false,
            true,
            true,
            false,
        ),
        (
            "factory must reflect a project gap with known counts",
            true,
            false,
            false,
            false,
        ),
        (
            "factory must reflect a project gap with unread counts",
            true,
            false,
            true,
            false,
        ),
        (
            "unread counts with project and factory gaps",
            true,
            true,
            true,
            true,
        ),
    ] {
        let mut value = fixtures()["stock-fed"].clone();
        let stock = &mut value["record"]["stock"];
        stock["totals"] = json!({"unknown":"Synthetic factory total unread"});
        if project_partial {
            stock["projects"][0]["coverage"] = partial.clone();
        }
        if factory_partial {
            stock["coverage"] = partial.clone();
        }
        if unread_counts {
            stock["projects"][0]["counts"] = json!({"unknown":"Synthetic project counts unread"});
        }
        let record: Document = serde_json::from_value(value).unwrap();
        assert_eq!(record.check().is_ok(), expected, "{case}");
    }
    let stale: Document = serde_json::from_value(fixtures()["stock-stale"].clone()).unwrap();
    assert!(
        stale.check().is_ok(),
        "stale counts retain their last-good sample"
    );
}

fn review_r2_unknown_category_availability_requires_status_gaps() {
    // Unknown availability is a gap even while delivery/category is disabled.
    for (case, complete, only_merge_unknown, all_known, expected) in [
        (
            "all sources unknown under complete status",
            true,
            false,
            false,
            false,
        ),
        (
            "all sources unknown under partial status",
            false,
            false,
            false,
            true,
        ),
        (
            "disabled optional source unknown under complete status",
            true,
            true,
            false,
            false,
        ),
        (
            "disabled optional source unknown under partial status",
            false,
            true,
            false,
            true,
        ),
        (
            "positively known unavailable sources",
            true,
            false,
            true,
            true,
        ),
    ] {
        let mut value = fixtures()["status"].clone();
        let status = &mut value["record"]["status"];
        assert_eq!(status["preferences"]["enabled"], false);
        assert_eq!(status["preferences"]["categories"]["merge"], false);
        status["freshness"] = json!({"state":"fresh","snapshot_at":{"known":1700000000000_u64}});
        if complete {
            status["coverage"] = json!({"state":"complete","gaps":[]});
        }
        if only_merge_unknown || all_known {
            for source in status["sources"].as_array_mut().unwrap() {
                if all_known || source["category"] != "merge" {
                    source["available"] = json!({"known":false});
                }
            }
        }
        let record: Document = serde_json::from_value(value).unwrap();
        assert_eq!(record.check().is_ok(), expected, "{case}");
    }
}
