//! T4: real updater + shared App client + T1 outcome sink, recording tools only.
//! synthetic_assumptions: token exchange and issue-comment projections are recorded fakes.
#![cfg(target_os = "linux")]
use super::update;
use openwiz_service as service;
use serde_json::{Value, json};
use service::state::State;
use std::{
    fs,
    path::Path,
    sync::{Arc, Mutex},
};
#[path = "install_engine_app_support.rs"]
mod support;
use support::{Fixture, NEW, OLD, records, rows};

struct Packages(Mutex<Vec<String>>);
impl update::Executor for Packages {
    fn run(&self, call: &update::Call) -> Result<String, String> {
        assert_eq!(
            call.program(),
            Path::new("python3"),
            "packaged path must run no source build gate"
        );
        let verb = call.argv()[1].as_str();
        self.0.lock().unwrap().push(verb.to_owned());
        match verb {
            "discover" => Ok(
                json!({"schema":"openwiz.package-candidate.v1","version":"0.0.99",
                "source":NEW,"target":"x86_64-unknown-linux-gnu","manifest_sha256":"3".repeat(64)})
                .to_string(),
            ),
            "stage" => Err("Synthetic verification failure after discovery.".into()),
            _ => panic!("unexpected package effect"),
        }
    }
}
#[test]
fn updater_app_outcomes_keep_delivery_identity_and_uncertainty_across_restart() {
    for mode in ["confirmed", "wrong", "missing", "lost"] {
        let fixture = Fixture::new(mode, "installed_engine_app::app_endpoint_process");
        let root = &fixture.root;
        let install = fixture.install.clone();
        let source = fixture.source.clone();
        let build = fixture.build.clone();
        let packages = Arc::new(Packages(Mutex::new(Vec::new())));
        let state = Arc::new(Mutex::new(State::load(&root.0, 1000).unwrap()));
        let updater = update::Updater::fixture(
            &root.0,
            &install,
            &source,
            OLD,
            records(&root.0),
            packages.clone(),
        )
        .unwrap();
        let outcome = updater.check(&state, 1000);
        if mode == "confirmed" {
            assert_eq!(outcome, Ok(false));
        } else {
            assert!(outcome.unwrap_err().contains("uncertain"));
        }
        let attempt = state.lock().unwrap().snapshot()["update"].clone();
        assert_eq!(attempt["from"], OLD);
        assert_eq!(attempt["to"], NEW);
        assert_eq!(attempt["outcome"]["state"], "kept");
        assert_eq!(attempt["outcome"]["step"], "fetch");
        assert_eq!(attempt["at"], 1000);
        let posted: Value =
            serde_json::from_slice(&fs::read(root.0.join("posted.json")).unwrap()).unwrap();
        let body = posted["body"].as_str().unwrap();
        let envelope: Value = serde_json::from_str(
            body.split("```json\n")
                .nth(1)
                .unwrap()
                .split("\n```")
                .next()
                .unwrap(),
        )
        .unwrap();
        assert_eq!(envelope["schema"], "openwiz.service-record.v1");
        assert_eq!(envelope["kind"], "update");
        assert_eq!(envelope["from"], OLD);
        assert_eq!(envelope["to"], NEW);
        assert_eq!(envelope["outcome"], attempt["outcome"]);
        assert_eq!(rows(&root.0).len(), if mode == "lost" { 1 } else { 2 });
        let journal = root.0.join("service/update-pending.json");
        if mode == "confirmed" {
            assert!(!journal.exists());
        } else {
            let pending: Value = serde_json::from_slice(&fs::read(&journal).unwrap()).unwrap();
            assert_eq!(pending["record_claimed"], true);
            let mut status: Value = include_str!("../../contracts/service.v1.md")
                .lines()
                .filter_map(|line| serde_json::from_str::<Value>(line).ok())
                .find(|value| value["schema"] == "openwiz.service-status.v1")
                .unwrap();
            status["update"] = attempt;
            status["service"]["build"] = json!(OLD);
            let status = update::record_status(&root.0, status).unwrap();
            assert_eq!(status["update_record"]["state"], "uncertain");
        }
        assert_eq!(*packages.0.lock().unwrap(), ["discover", "stage"]);
        drop(updater);
        drop(state);
        let before = rows(&root.0);
        let state = Arc::new(Mutex::new(State::load(&root.0, 2000).unwrap()));
        let restarted = update::Updater::fixture(
            &root.0,
            &install,
            &source,
            OLD,
            records(&root.0),
            packages.clone(),
        )
        .unwrap();
        assert_eq!(restarted.check(&state, 2000), Ok(false));
        assert_eq!(
            rows(&root.0),
            before,
            "restart must not post a second outcome"
        );
        assert_eq!(
            *packages.0.lock().unwrap(),
            if mode == "confirmed" {
                vec!["discover", "stage", "discover"]
            } else {
                vec!["discover", "stage"]
            }
        );
        assert_eq!(
            fs::read_link(install.join("current")).unwrap(),
            build,
            "failed package retains selected build"
        );
    }
}

#[test]
fn app_endpoint_process() {
    support::app_endpoint_process();
}
