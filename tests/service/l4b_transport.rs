//! Option A synthetic configuration and allowlist boundaries, never live.
#[path = "../fleet/schema.rs"]
mod schema;
use openwiz_adapter_github::allowlist::Invocation;
use openwiz_service::document::{self, Document};
use serde_json::{Value, json};

fn config() -> Value {
    include_str!("../../contracts/service.v1.md")
        .lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .find(|v| v["schema"] == "openwiz.service-config.v1")
        .unwrap()
}

#[test]
fn lp3b_hook_configuration_and_schema_accept_only_an_explicit_positive_id() {
    let contract: Value =
        serde_json::from_str(include_str!("../../contracts/service.v1.schema.json")).unwrap();
    assert!(schema::lint(&contract).is_empty());
    let mut cases = vec![(config(), true)];
    let mut enabled = config();
    enabled["events"] = json!({"hook_id": 4101});
    cases.push((enabled, true));
    for bad in [
        json!(null),
        json!([]),
        json!({}),
        json!({"hook_id": 0}),
        json!({"hook_id": -1}),
        json!({"hook_id": 1.0}),
        json!({"hook_id": "4101"}),
        json!({"hook_id": true}),
        json!({"hook_id": 4101, "extra": true}),
        json!({"hook_id": 4101, "every_s": 1}),
    ] {
        let mut v = config();
        v["events"] = bad;
        cases.push((v, false));
    }
    for (value, expected) in cases {
        assert_eq!(
            document::read(Document::Config, &value.to_string()).is_ok(),
            expected,
            "reader: {value}"
        );
        assert_eq!(
            schema::validate(&contract, &value).is_empty(),
            expected,
            "schema: {value}"
        );
    }
    let duplicate =
        config()
            .to_string()
            .replacen('{', "{\"events\":{\"hook_id\":4101,\"hook_id\":4102},", 1);
    assert!(document::read(Document::Config, &duplicate).is_err());
}

#[test]
fn lp3b_delivery_allowlist_grants_only_the_two_read_forms() {
    for path in [
        "repos/{owner}/{repo}/hooks/4101/deliveries?per_page=100",
        "repos/{owner}/{repo}/hooks/4101/deliveries?per_page=1",
        "repos/{owner}/{repo}/hooks/4101/deliveries/5101",
    ] {
        assert!(Invocation::new(&["api", path]).is_some(), "{path}");
        for flags in [
            &["--method", "POST"][..],
            &["--method", "GET"],
            &["--paginate"],
            &["--include"],
            &["-f", "secret=synthetic"],
        ] {
            let mut argv = vec!["api", path];
            argv.extend_from_slice(flags);
            assert!(Invocation::new(&argv).is_none(), "{argv:?}");
        }
    }
    for path in [
        "repos/{owner}/{repo}/hooks",
        "repos/{owner}/{repo}/hooks/4101",
        "repos/{owner}/{repo}/hooks/4101/deliveries",
        "repos/{owner}/{repo}/hooks/4101/deliveries/5101/attempts",
        "repos/{owner}/{repo}/hooks/0/deliveries?per_page=100",
        "repos/{owner}/{repo}/hooks/04101/deliveries?per_page=100",
        "repos/{owner}/{repo}/hooks/4101/deliveries?per_page=101",
        "repos/{owner}/{repo}/hooks/4101/deliveries?per_page=0",
        "repos/{owner}/{repo}/hooks/4101/deliveries?per_page=100&cursor=5100",
        "repos/{owner}/{repo}/hooks/4101/deliveries/0",
        "repos/{owner}/{repo}/hooks/4101/deliveries/05101",
        "repos/{owner}/{repo}/hooks/4101/deliveries/-1",
        "repos/{owner}/{repo}/hooks/4101/deliveries/18446744073709551616",
        "repos/{owner}/{repo}/hooks/4101/deliveries/１",
        "repos/other/project/hooks/4101/deliveries?per_page=100",
        "https://github.invalid/repos/other/project/hooks/4101/deliveries?per_page=100",
    ] {
        assert!(Invocation::new(&["api", path]).is_none(), "{path}");
    }
}

use openwiz_adapter_github::{
    events::{Deliveries as Reads, Summary},
    process::Executor,
};
use openwiz_core::{limits::RUN_BUDGET, source::SourceError};
use std::{
    num::NonZeroU64,
    sync::{Arc, Mutex},
    time::Instant,
};

// synthetic_assumptions: complete documented delivery metadata and payload
// envelopes. No shape or value was observed from this project's webhook.
fn metadata(id: u64, guid: &str, event: &str) -> Value {
    json!({"id":id,"guid":guid,"delivered_at":"2026-01-01T00:00:00Z","redelivery":false,"duration":0.27,"status":"OK","status_code":200,"event":event,"action":"completed","installation_id":2101,"repository_id":3101,"throttled_at":null})
}
fn summary(id: u64, guid: &str, event: &str) -> Summary {
    Summary {
        id: NonZeroU64::new(id).unwrap(),
        guid: guid.into(),
        event: event.into(),
    }
}
fn detail(meta: Value) -> Value {
    let mut v = meta;
    v["url"] = json!("https://synthetic.invalid/private-hook-destination");
    v["request"] = json!({"headers":{"X-Synthetic-Secret":"withheld"},"payload":{"repository":{"full_name":"synthetic/project"},"workflow_run":{"pull_requests":[{"number":1901}]}}});
    v["response"] =
        json!({"headers":{"Content-Type":"text/plain"},"payload":"synthetic private response"});
    v
}
fn reads(responses: Vec<Result<Vec<u8>, SourceError>>) -> (Reads, Arc<Mutex<Vec<Vec<String>>>>) {
    let log = Arc::new(Mutex::new(vec![]));
    let calls = Arc::clone(&log);
    let replies = Mutex::new(std::collections::VecDeque::from(responses));
    let execute = Executor::supplied(Arc::new(move |call, _| {
        calls.lock().unwrap().push(call.argv().to_vec());
        replies
            .lock()
            .unwrap()
            .pop_front()
            .expect("no unplanned read")
    }));
    (Reads::new(NonZeroU64::new(4101).unwrap(), execute), log)
}
fn wire(value: &Value) -> Result<Vec<u8>, SourceError> {
    Ok(value.to_string().into_bytes())
}
fn deadline() -> Instant {
    Instant::now() + RUN_BUDGET
}

#[test]
fn lp3b_documented_delivery_reads_keep_guid_and_payload_without_transport_secrets() {
    let meta = metadata(5101, "delivery-syn-1", "workflow_run");
    let delivered = detail(meta.clone());
    let (reader, log) = reads(vec![wire(&json!([meta])), wire(&delivered)]);
    let list = reader.list(deadline()).unwrap();
    assert_eq!(list, [summary(5101, "delivery-syn-1", "workflow_run")]);
    let got = reader.detail(&list[0], deadline()).unwrap();
    assert_eq!(got.summary, list[0]);
    let body: Value = serde_json::from_slice(&got.payload).unwrap();
    assert_eq!(
        body,
        json!({"repository":{"full_name":"synthetic/project"},"workflow_run":{"pull_requests":[{"number":1901}]}})
    );
    assert_eq!(log.lock().unwrap().len(), 2);
}

#[test]
fn lp3b_delivery_reader_refuses_partial_or_malformed_documents_and_changed_identity() {
    let meta = metadata(5101, "delivery-syn-1", "workflow_run");
    let mut bad_lists = vec![
        json!(null),
        json!({}),
        json!([[]]),
        json!([meta.clone(), meta.clone()]),
    ];
    for (key, bad) in [
        ("id", json!(0)),
        ("id", json!(1.0)),
        ("id", json!("5101")),
        ("guid", json!("../escape")),
        ("event", json!({"workflow_run":null})),
        ("redelivery", json!("false")),
        ("duration", json!(-1)),
        ("status_code", json!("200")),
        ("repository_id", json!("3101")),
        ("throttled_at", json!(false)),
    ] {
        let mut v = meta.clone();
        v[key] = bad;
        bad_lists.push(json!([v]));
    }
    for key in meta
        .as_object()
        .unwrap()
        .keys()
        .filter(|k| k.as_str() != "throttled_at")
    {
        let mut v = meta.clone();
        v.as_object_mut().unwrap().remove(key);
        bad_lists.push(json!([v]));
    }
    let mut extra = meta.clone();
    extra["extra"] = json!("synthetic");
    bad_lists.push(json!([extra]));
    for bad in bad_lists {
        let (reader, log) = reads(vec![wire(&bad)]);
        assert!(reader.list(deadline()).is_err(), "{bad}");
        assert_eq!(log.lock().unwrap().len(), 1);
    }
    let valid = detail(meta);
    let expected = summary(5101, "delivery-syn-1", "workflow_run");
    let mut bad_details = vec![json!([]), json!({})];
    for (key, bad) in [
        ("id", json!(5102)),
        ("guid", json!("delivery-syn-other")),
        ("event", json!("issue_comment")),
        ("request", json!({"headers":{},"payload":[]})),
        ("request", json!({"headers":{"key":2},"payload":{}})),
        ("response", json!({"headers":{},"payload":false})),
    ] {
        let mut v = valid.clone();
        v[key] = bad;
        bad_details.push(v);
    }
    for bad in bad_details {
        let (reader, _) = reads(vec![wire(&bad)]);
        assert!(reader.detail(&expected, deadline()).is_err(), "{bad}");
    }
    for bytes in [
        b"{not JSON".to_vec(),
        valid
            .to_string()
            .replacen('{', "{\"id\":5101,", 1)
            .into_bytes(),
        valid
            .to_string()
            .replacen(
                "\"workflow_run\":{",
                "\"repository\":{},\"workflow_run\":{",
                1,
            )
            .into_bytes(),
    ] {
        let (reader, _) = reads(vec![Ok(bytes)]);
        assert!(reader.detail(&expected, deadline()).is_err());
    }
    let (reader, log) = reads(vec![]);
    assert!(reader.list(Instant::now()).is_err());
    assert!(log.lock().unwrap().is_empty());
    let (reader, log) = reads(vec![Err(SourceError::Unavailable {
        detail: "synthetic App denial".into(),
    })]);
    assert!(reader.list(deadline()).is_err());
    assert_eq!(log.lock().unwrap().len(), 1);
}

use crate::support::{self, Fake, Fixed, Fixture};
use openwiz_service::{
    events::{self as routing, intake, route_next},
    scheduler::Scheduler,
};

fn polling_config() -> Value {
    let mut v = config();
    v["repository"] = json!({"owner":"synthetic","name":"project"});
    v["events"] = json!({"hook_id":4101});
    v
}
fn executor(responses: Vec<Result<Vec<u8>, SourceError>>) -> (Executor, Arc<Mutex<usize>>) {
    let count = Arc::new(Mutex::new(0));
    let calls = Arc::clone(&count);
    let queue = Mutex::new(std::collections::VecDeque::from(responses));
    (
        Executor::supplied(Arc::new(move |_, _| {
            *calls.lock().unwrap() += 1;
            queue
                .lock()
                .unwrap()
                .pop_front()
                .expect("no unexpected command or personal fallback")
        })),
        count,
    )
}
fn route(
    fake: Arc<Fake>,
    root: std::path::PathBuf,
    seen: Arc<Mutex<Vec<String>>>,
) -> Arc<intake::Route> {
    Arc::new(move |event, _| {
        seen.lock().unwrap().push(event.event_id.clone());
        let sends = openwiz_store::FileStore::open(&root).unwrap();
        let mut source = support::Source(std::collections::VecDeque::from([event]));
        route_next(&support::router(&fake, &sends), &mut source).map(|_| ())
    })
}

#[test]
fn lp3b_registered_polling_routes_once_on_cadence_across_duplicates_late_hints_and_restart() {
    let fixture = Fixture::new();
    let fake = Arc::new(Fake::new(support::snapshot()));
    let seen = Arc::new(Mutex::new(vec![]));
    let config = polling_config();
    let first = metadata(5101, "delivery-syn-1", "workflow_run");
    let mut repeat = metadata(5102, "delivery-syn-1", "workflow_run");
    repeat["redelivery"] = json!(true);
    let late = metadata(5103, "delivery-syn-late", "workflow_run");
    let irrelevant = metadata(5104, "delivery-syn-lifecycle", "pull_request");
    let batch = json!([first.clone(), repeat.clone(), late.clone(), irrelevant]);
    let (github, calls) = executor(vec![
        wire(&batch),
        wire(&detail(first.clone())),
        wire(&detail(late.clone())),
        wire(&batch),
        wire(&batch),
    ]);
    let callback = route(Arc::clone(&fake), fixture.0.clone(), Arc::clone(&seen));
    let mut scheduler = Scheduler::default();
    assert!(
        intake::register_with(
            &fixture.0,
            &config,
            &mut scheduler,
            github.clone(),
            Arc::clone(&callback),
            Arc::new(Fixed)
        )
        .unwrap()
    );
    assert!(scheduler.poll(0).unwrap().is_empty());
    assert!(scheduler.poll(9).unwrap().is_empty());
    assert_eq!(*calls.lock().unwrap(), 0);
    for at in [10, 20] {
        assert_eq!(scheduler.poll(at).unwrap(), [intake::JOB]);
        scheduler.wait(intake::JOB).unwrap();
        assert_eq!(fake.calls().len(), 1);
        assert_eq!(
            *seen.lock().unwrap(),
            ["delivery-syn-1", "delivery-syn-late"]
        );
    }
    let mut restarted = Scheduler::default();
    assert!(
        intake::register_with(
            &fixture.0,
            &config,
            &mut restarted,
            github,
            callback,
            Arc::new(Fixed)
        )
        .unwrap()
    );
    assert_eq!(restarted.poll(10).unwrap(), [intake::JOB]);
    restarted.wait(intake::JOB).unwrap();
    assert_eq!(fake.calls().len(), 1);
    assert_eq!(seen.lock().unwrap().len(), 2);
    assert_eq!(*calls.lock().unwrap(), 5);
    let sent = fake.calls();
    assert_eq!(sent[0].0, "thr_syn_builder");
    assert!(sent[0].1.contains("CI failed for pull request #1901"));
}

#[test]
fn lp3b_absent_or_invalid_config_reads_nothing_and_intake_failure_preserves_check_in() {
    let fixture = Fixture::new();
    let fake = Arc::new(Fake::new(support::snapshot()));
    let seen = Arc::new(Mutex::new(vec![]));
    let callback = route(Arc::clone(&fake), fixture.0.clone(), Arc::clone(&seen));
    let (unused, calls) = executor(vec![]);
    let mut scheduler = Scheduler::default();
    assert!(
        !intake::register_with(
            &fixture.0,
            &config(),
            &mut scheduler,
            unused.clone(),
            Arc::clone(&callback),
            Arc::new(Fixed)
        )
        .unwrap()
    );
    let mut invalid = polling_config();
    invalid["events"] = json!({"hook_id":0});
    assert!(
        intake::register_with(
            &fixture.0,
            &invalid,
            &mut scheduler,
            unused,
            Arc::clone(&callback),
            Arc::new(Fixed)
        )
        .is_err()
    );
    assert!(scheduler.poll(100).unwrap().is_empty());
    assert_eq!(*calls.lock().unwrap(), 0);
    let meta = metadata(5101, "delivery-syn-1", "workflow_run");
    let failure = || {
        Err(SourceError::Unavailable {
            detail: "synthetic App failure".into(),
        })
    };
    let (github, calls) = executor(vec![
        failure(),
        wire(&json!([meta.clone()])),
        failure(),
        wire(&json!([meta.clone()])),
        wire(&detail(meta)),
    ]);
    assert!(
        intake::register_with(
            &fixture.0,
            &polling_config(),
            &mut scheduler,
            github,
            callback,
            Arc::new(Fixed)
        )
        .unwrap()
    );
    for at in [110, 120] {
        assert_eq!(scheduler.poll(at).unwrap(), [intake::JOB]);
        scheduler.wait(intake::JOB).unwrap();
        assert!(seen.lock().unwrap().is_empty());
        assert!(fake.calls().is_empty());
    }
    // Independent check-in still reconciles work after the failed intake.
    let sends = fixture.store();
    let r = support::router(&fake, &sends);
    assert!(matches!(
        r.route_pr(support::n(1901)),
        routing::RouteResult::Send(_)
    ));
    assert_eq!(fake.calls().len(), 1);
    assert_eq!(scheduler.poll(130).unwrap(), [intake::JOB]);
    scheduler.wait(intake::JOB).unwrap();
    assert_eq!(*seen.lock().unwrap(), ["delivery-syn-1"]);
    assert_eq!(fake.calls().len(), 1);
    assert_eq!(*calls.lock().unwrap(), 5);
}
