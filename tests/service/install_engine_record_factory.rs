//! Granted default factory seam: packaged config -> real App client -> T1 sink.
//! Native recording endpoint and synthetic identities only; live exchange unused.
use super::{RecordError, configured_records_at};
use crate as service;
use crate::update;
use serde_json::{Value, json};
use std::fs;
#[path = "install_engine_app_support.rs"]
mod support;
use support::{Fixture, client, config, file, rows};
const ENDPOINT: &str = "update::record_factory_tests::app_endpoint_process";

#[test]
fn app_endpoint_process() {
    support::app_endpoint_process();
}

#[test]
fn configured_factory_binds_selected_repository_issue_and_uncertain_delivery() {
    for mode in ["confirmed", "lost"] {
        let fixture = Fixture::new(mode, ENDPOINT);
        let root = &fixture.root.0;
        file(
            &root.join("expected-repository"),
            "synthetic-other/other-repo",
        );
        file(&root.join("expected-issue"), "903");
        let mut selected = config();
        selected["repository"] = json!({"owner":"synthetic-other","name":"other-repo"});
        selected["service_issue"] = json!(903);
        file(&root.join("service/config.json"), selected.to_string());
        let records = configured_records_at(root, &selected, &fixture.install, client).unwrap();
        assert_eq!(
            records(901, "Synthetic wrong issue"),
            Err(RecordError::Unsent)
        );
        assert_eq!(records(903, "\0"), Err(RecordError::Unsent));
        assert_eq!(rows(root).len(), 0);
        let outcome = records(903, "Synthetic configured outcome.");
        assert_eq!(
            outcome,
            if mode == "lost" {
                Err(RecordError::Uncertain)
            } else {
                Ok(())
            }
        );
        let observed = rows(root);
        assert_eq!(observed.len(), if mode == "lost" { 1 } else { 2 });
        assert!(
            observed
                .iter()
                .all(|row| row["repo"] == "github.com/synthetic-other/other-repo"
                    && row["issue"] == "903")
        );
        let posted: Value =
            serde_json::from_slice(&fs::read(root.join("posted.json")).unwrap()).unwrap();
        assert_eq!(posted["body"], "Synthetic configured outcome.");
        assert_eq!(
            posted["url"],
            "https://github.com/synthetic-other/other-repo/issues/903#issuecomment-123"
        );
    }
}

#[test]
fn configured_factory_preserves_source_default_and_refuses_unsafe_channel() {
    let fixture = Fixture::new("confirmed", ENDPOINT);
    let root = &fixture.root.0;
    let path = fixture.install.join("channel.json");
    fs::remove_file(&path).unwrap();
    assert!(
        configured_records_at(root, &config(), &fixture.install, |_, _| panic!(
            "source default must not construct an App client"
        ))
        .is_err()
    );
    for channel in ["source", "unrecognized"] {
        file(
            &path,
            json!({"schema":"openwiz.update-channel.v1","channel":channel}).to_string(),
        );
        assert!(
            configured_records_at(root, &config(), &fixture.install, |_, _| panic!(
                "nonpackaged channel must not construct an App client"
            ))
            .is_err()
        );
    }
    file(&path, "SYNTHETIC_PRIVATE_DIAGNOSTIC /synthetic/private");
    assert!(
        configured_records_at(root, &config(), &fixture.install, |_, _| panic!(
            "invalid channel must not construct an App client"
        ))
        .is_err()
    );
    assert_eq!(rows(root).len(), 0);
}

#[test]
fn configured_factory_rejects_invalid_selected_config_without_provider_effects() {
    let fixture = Fixture::new("confirmed", ENDPOINT);
    let root = &fixture.root.0;
    for mutation in [
        json!({"service_issue":0}),
        json!({"service_issue":"903"}),
        json!({"repository":null}),
        json!({"repository":{"owner":"synthetic-owner","name":"../private"}}),
        json!({"github_app":null}),
    ] {
        let mut selected = config();
        for (key, value) in mutation.as_object().unwrap() {
            selected[key] = value.clone();
        }
        let mut constructions = 0;
        let result = configured_records_at(root, &selected, &fixture.install, |root, text| {
            constructions += 1;
            client(root, text)
        });
        assert_eq!(constructions, 1);
        assert!(result.is_err());
        assert_eq!(
            result.err().unwrap(),
            "cannot configure the service App record client"
        );
        assert_eq!(rows(root).len(), 0);
    }
}
