use openwiz_adapter_cloudroom::new_thread::{CLI_REASONING_LEVELS, parse_catalogue};
use openwiz_core::new_thread::operation::NewThreadError;
use openwiz_core::new_thread::options::{OptionsState, UnavailableReason, cloud_options};
use openwiz_core::new_thread::outcome::{Outcome, RefusalReason, Status};

use crate::support::*;

fn options() -> openwiz_core::new_thread::options::CloudOptions {
    cloud_options(
        parse_catalogue(&fixture("cloud-status.json")),
        CLI_REASONING_LEVELS,
        T0,
    )
}

#[test]
fn n4_offered_choice_contracts_preserve_all_original_cases() {
    let cases: [(&str, fn()); 12] = [
        (
            "a_model_with_no_shared_effort_is_not_offered",
            a_model_with_no_shared_effort_is_not_offered,
        ),
        (
            "an_off_catalogue_claude_code_model_is_refused",
            an_off_catalogue_claude_code_model_is_refused,
        ),
        (
            "an_unoffered_harness_model_or_effort_is_refused_with_zero_calls",
            an_unoffered_harness_model_or_effort_is_refused_with_zero_calls,
        ),
        (
            "an_unverified_mapping_is_unavailable_even_with_models",
            an_unverified_mapping_is_unavailable_even_with_models,
        ),
        (
            "conflicting_catalogue_rows_are_unavailable_in_both_orders",
            conflicting_catalogue_rows_are_unavailable_in_both_orders,
        ),
        (
            "conflicting_provider_mappings_are_unavailable_in_both_orders",
            conflicting_provider_mappings_are_unavailable_in_both_orders,
        ),
        (
            "each_model_uses_its_own_effort_levels",
            each_model_uses_its_own_effort_levels,
        ),
        (
            "identical_catalogue_rows_collapse_and_every_shown_choice_is_accepted",
            identical_catalogue_rows_collapse_and_every_shown_choice_is_accepted,
        ),
        (
            "no_options_refuses_everything",
            no_options_refuses_everything,
        ),
        ("nothing_is_defaulted", nothing_is_defaulted),
        (
            "only_codex_and_claude_code_are_offered_with_the_intersection_of_efforts",
            only_codex_and_claude_code_are_offered_with_the_intersection_of_efforts,
        ),
        (
            "the_refusal_names_what_is_offered_and_substitutes_nothing",
            the_refusal_names_what_is_offered_and_substitutes_nothing,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: n04_offered_only::{name}");
        proof();
    }
}

fn only_codex_and_claude_code_are_offered_with_the_intersection_of_efforts() {
    let o = options();
    assert_eq!(o.state, OptionsState::Offered);
    let offered: Vec<&str> = o.harnesses.iter().map(|h| h.harness.as_str()).collect();
    assert_eq!(offered, ["codex", "claude-code"]);
    assert_eq!(o.harnesses[0].models.len(), 10);
    assert_eq!(o.harnesses[1].models.len(), 9);
    for h in &o.harnesses {
        assert_eq!(h.provider, h.harness, "the verified mapping");
        for m in &h.models {
            assert_eq!(m.efforts, CLI_REASONING_LEVELS, "{}", m.model);
        }
    }
    let unavailable: Vec<(&str, UnavailableReason)> = o
        .unavailable
        .iter()
        .map(|u| (u.harness.as_str(), u.reason))
        .collect();
    assert_eq!(unavailable.len(), 7);
    assert!(
        unavailable
            .iter()
            .all(|(_, r)| *r == UnavailableReason::CatalogueNotReported),
        "{unavailable:?}"
    );
}

fn each_model_uses_its_own_effort_levels() {
    let mut doc = fixture_json("cloud-status.json");
    doc["harnesses"][0]["models"] = serde_json::json!([
        {"model": "syn-model-a", "reasoning_levels": ["high", "minimal"]},
        {"model": "syn-model-b", "reasoning_levels": ["low", "ultra"]}
    ]);
    let o = cloud_options(
        parse_catalogue(doc.to_string().as_bytes()),
        CLI_REASONING_LEVELS,
        T0,
    );
    assert_eq!(o.state, OptionsState::Offered);
    let codex = o
        .harnesses
        .iter()
        .find(|h| h.harness == "codex")
        .expect("codex is offered");
    assert_eq!(codex.models.len(), 2);
    assert_eq!(codex.models[0].model, "syn-model-a");
    assert_eq!(codex.models[0].efforts, ["high"]);
    assert_eq!(codex.models[1].model, "syn-model-b");
    assert_eq!(codex.models[1].efforts, ["low"]);
}

fn refused(settings: openwiz_core::new_thread::Settings, why: RefusalReason) {
    let client = FakeClient::new();
    let store = MemoryStore::new();
    let label = format!("{settings:?}");
    let report = create(&client, &store, &request(settings, "Synthetic", "op-n04"));
    assert_eq!(report.status, Status::Refused, "{label}");
    let openwiz_core::new_thread::operation::NewThreadResult::Outcome { outcome, .. } =
        &report.result
    else {
        panic!("{label}: {report:?}")
    };
    let Outcome::Refused { reason, .. } = outcome else {
        panic!("{label}: {outcome:?}")
    };
    assert_eq!(*reason, why, "{label}");
    assert_eq!(client.spawns(), 0, "{label}: zero spawn calls");
    assert!(report.summary.contains("nothing was created"), "{label}");
}

fn an_unoffered_harness_model_or_effort_is_refused_with_zero_calls() {
    refused(
        settings("cursor", "syn-cursor-default", "high"),
        RefusalReason::HarnessNotOffered,
    );
    refused(
        settings("syn-harness", "syn-codex-model-01", "high"),
        RefusalReason::HarnessNotOffered,
    );
    refused(
        settings("codex", "syn-claude-model-01", "high"),
        RefusalReason::ModelNotOffered,
    );
    refused(
        settings("codex", "syn-codex-default", "high"),
        RefusalReason::ModelNotOffered,
    );
    for effort in ["ultra", "none", "minimal", "syn-effort"] {
        refused(
            settings("codex", "syn-codex-model-01", effort),
            RefusalReason::EffortNotOffered,
        );
    }
}

fn an_off_catalogue_claude_code_model_is_refused() {
    refused(
        settings("claude-code", "syn-claude-model-99", "high"),
        RefusalReason::ModelNotOffered,
    );
}

fn the_refusal_names_what_is_offered_and_substitutes_nothing() {
    let client = FakeClient::new();
    let store = MemoryStore::new();
    let report = create(
        &client,
        &store,
        &request(
            settings("codex", "syn-codex-model-01", "ultra"),
            "Synthetic",
            "op-n04-o",
        ),
    );
    let openwiz_core::new_thread::operation::NewThreadResult::Outcome {
        outcome: Outcome::Refused { offered, text, .. },
        ..
    } = &report.result
    else {
        panic!("{report:?}")
    };
    assert_eq!(offered, &CLI_REASONING_LEVELS);
    assert!(text.contains("Nothing was substituted"), "{text}");
    assert_eq!(
        report.requested.effort, "ultra",
        "the request is kept as it was"
    );
}

fn no_options_refuses_everything() {
    for file in [
        "cloud-status-not-ready.json",
        "cloud-status-harnesses-null.json",
    ] {
        let client = FakeClient::with_catalogue(file);
        let store = MemoryStore::new();
        let report = create(
            &client,
            &store,
            &request(offered(), "Synthetic", "op-n04-none"),
        );
        assert_eq!(report.status, Status::Refused, "{file}");
        assert_eq!(client.spawns(), 0, "{file}");
    }
}

fn an_unverified_mapping_is_unavailable_even_with_models() {
    let mut doc = fixture_json("cloud-status.json");
    doc["harnesses"][1]["models"] =
        serde_json::json!([{"model": "syn-pi-model-01", "reasoning_levels": ["high"]}]);
    let o = cloud_options(
        parse_catalogue(doc.to_string().as_bytes()),
        CLI_REASONING_LEVELS,
        T0,
    );
    let pi = o
        .unavailable
        .iter()
        .find(|u| u.harness == "pi")
        .expect("pi");
    assert_eq!(pi.reason, UnavailableReason::IdMappingNotVerified);
    assert!(o.harnesses.iter().all(|h| h.harness != "pi"));
}

fn a_model_with_no_shared_effort_is_not_offered() {
    let mut doc = fixture_json("cloud-status.json");
    doc["harnesses"][0]["models"] = serde_json::json!([{"model": "syn-codex-model-01", "reasoning_levels": ["ultra", "minimal"]}]);
    let o = cloud_options(
        parse_catalogue(doc.to_string().as_bytes()),
        CLI_REASONING_LEVELS,
        T0,
    );
    let codex = o
        .unavailable
        .iter()
        .find(|u| u.harness == "codex")
        .expect("codex");
    assert_eq!(codex.reason, UnavailableReason::NoOfferedEffort);
}

fn nothing_is_defaulted() {
    let client = FakeClient::new();
    let store = MemoryStore::new();
    for s in [
        settings("", "syn-codex-model-01", "high"),
        settings("codex", "", "high"),
        settings("codex", "syn-codex-model-01", ""),
    ] {
        let label = format!("{s:?}");
        assert!(
            matches!(
                try_create(&client, &store, &request(s, "Synthetic", "op-n04-d")),
                Err(NewThreadError::Invalid(_))
            ),
            "{label}"
        );
    }
    assert_eq!(client.calls(), 0, "nothing was read or called");
    let json = serde_json::to_value(options()).unwrap();
    let mut words = Vec::new();
    strings(&json, &mut words);
    assert!(
        !words
            .iter()
            .any(|w| w == "default" || w.contains("-default")),
        "no default is offered: {words:?}"
    );
}

fn conflicting_catalogue_rows_are_unavailable_in_both_orders() {
    use openwiz_cli::models::render_options;
    use serde_json::json;

    let mut doc = fixture_json("cloud-status.json");
    doc["harnesses"][0]["models"] = json!([{"model": "syn-model", "reasoning_levels": ["low"]}]);
    let row = doc["harnesses"][0].clone();
    let unaffected = doc["harnesses"][3].clone();
    let mut conflicts = Vec::new();
    for levels in [json!(["high"]), json!(["low", "syn-unknown-effort"])] {
        let mut model_conflict = row.clone();
        let mut other_model = row["models"][0].clone();
        other_model["reasoning_levels"] = levels;
        model_conflict["models"]
            .as_array_mut()
            .unwrap()
            .push(other_model);
        conflicts.push(vec![model_conflict]);
    }
    for (pointer, value) in [
        ("/models/0/reasoning_levels", json!(["high"])),
        ("/models/0/model", json!("syn-other-model")),
        ("/models", json!(null)),
        ("/attachments/files", json!(false)),
        ("/attachments/images", json!(false)),
        ("/attachments", json!(null)),
        ("/steer", json!(false)),
    ] {
        let mut other = row.clone();
        *other.pointer_mut(pointer).unwrap() = value;
        conflicts.push(vec![row.clone(), other]);
    }
    for rows in conflicts {
        for reversed in [false, true] {
            let mut rows = rows.clone();
            if reversed {
                rows.reverse();
            } else if rows.len() == 1 {
                rows[0]["models"].as_array_mut().unwrap().reverse();
            }
            rows.push(unaffected.clone());
            doc["harnesses"] = json!(rows);
            let bytes = serde_json::to_vec(&doc).unwrap();
            let o = cloud_options(parse_catalogue(&bytes), CLI_REASONING_LEVELS, T0);
            assert_eq!(o.harnesses.len(), 1, "{rows:?}: {o:?}");
            assert_eq!(o.harnesses[0].harness, "claude-code");
            assert_eq!(o.unavailable.len(), 1, "{o:?}");
            assert_eq!(o.unavailable[0].harness, "codex");
            assert_eq!(
                o.unavailable[0].text,
                "unavailable (conflicting catalogue rows)"
            );
            assert!(validate_def("options", &serde_json::to_value(&o).unwrap()).is_empty());
            let text = render_options(&o);
            assert!(text.contains("codex: unavailable (conflicting catalogue rows)"));
            assert!(!text.contains("syn-model:"), "{text}");
            for effort in ["low", "high"] {
                let choice = settings("codex", "syn-model", effort);
                assert!(o.offered(&choice).is_err());
                let client = FakeClient {
                    catalogue: Ok(bytes.clone()),
                    ..FakeClient::new()
                };
                let report = create(
                    &client,
                    &MemoryStore::new(),
                    &request(choice, "Synthetic", "op-456"),
                );
                assert_eq!(report.status, Status::Refused);
                assert_eq!(client.spawns(), 0);
            }
            let choice = settings("claude-code", "syn-claude-model-01", "high");
            assert_eq!(o.offered(&choice).unwrap(), "claude-code");
        }
    }
}

fn conflicting_provider_mappings_are_unavailable_in_both_orders() {
    let catalogue = parse_catalogue(&fixture("cloud-status.json")).unwrap();
    for provider in [None, Some("syn-other-provider".to_owned())] {
        for reversed in [false, true] {
            let mut catalogue = catalogue.clone();
            let rows = catalogue.harnesses.as_mut().unwrap();
            let mut other = rows[0].clone();
            other.provider = provider.clone();
            rows.push(other);
            if reversed {
                rows.reverse();
            }
            rows.retain(|row| row.id == "codex");
            let o = cloud_options(Ok(catalogue), CLI_REASONING_LEVELS, T0);
            assert!(o.harnesses.is_empty());
            assert!(matches!(o.state, OptionsState::NoOptions { .. }));
            assert_eq!(o.unavailable.len(), 1);
            let conflict = o.unavailable.iter().find(|h| h.harness == "codex").unwrap();
            assert_eq!(conflict.text, "unavailable (conflicting catalogue rows)");
            assert!(o.offered(&offered()).is_err());
        }
    }
}

fn identical_catalogue_rows_collapse_and_every_shown_choice_is_accepted() {
    let unique = options();
    let mut doc = fixture_json("cloud-status.json");
    for row in doc["harnesses"].as_array_mut().unwrap() {
        if let Some(models) = row["models"].as_array_mut() {
            models.push(models[0].clone());
        }
    }
    let rows = doc["harnesses"].as_array_mut().unwrap();
    rows.extend(rows.clone());
    let o = cloud_options(
        parse_catalogue(&serde_json::to_vec(&doc).unwrap()),
        CLI_REASONING_LEVELS,
        T0,
    );
    assert_eq!(o, unique);
    for h in &o.harnesses {
        for m in &h.models {
            for e in &m.efforts {
                assert_eq!(
                    o.offered(&settings(&h.harness, &m.model, e)).unwrap(),
                    h.provider
                );
            }
        }
    }
}
