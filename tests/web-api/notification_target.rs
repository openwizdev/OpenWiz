//! PA4/PA5 fixture proof: actual target GET over the existing bounded readers.
//! No fixture currentness or authentication response proves installed authority.
use crate::{e11_decisions_support as s, fake::Fake};
use openwiz_core::notifications::model::{Document, Reference};
use openwiz_server::{NotificationTargets, TargetReadError};
use serde_json::json;
use std::sync::Arc;

fn token() -> String {
    "1".repeat(64)
}
fn binding() -> Reference {
    serde_json::from_value(json!({"decision": {
        "repository":"synthetic-owner/synthetic-repo", "subject":{"kind":"pull_request","number":901},
        "comment_id":1001,"request_id":"synthetic-current", "fingerprint":"941019e2a769a93d10140f9924b4ce021a041c21f74cd72514a9f51306ad1aa4"
    }})).unwrap()
}
fn targets(reference: Reference) -> NotificationTargets {
    NotificationTargets {
        read_mapping: Arc::new(move |key, _deadline| {
            Ok((key == token()).then(|| reference.clone()))
        }),
    }
}

#[test]
fn notification_target_resolves_exact_lifecycle_without_work_effects() {
    for (index, (status, saved, expected)) in [
        ("open", "Synthetic source", "unread"),
        // Only the decisions owner's saved-grill verifier makes it current.
        ("open", crate::e11_decisions_records::SAVED_ROUND, "current"),
        ("resolved", "Synthetic source", "resolved"),
        ("superseded", "Synthetic source", "resolved"),
    ]
    .into_iter()
    .enumerate()
    {
        let room = Fake::new(&format!("notification_target_room_{index}"), "normal");
        let record = s::record("synthetic-current", status);
        let gh = s::fake(
            &format!("notification_target_gh_{index}"),
            vec![s::comment(1001, &s::fenced(&record))],
        );
        s::saved_grill(&gh, saved);
        let server = s::serve_targets(&gh, &room, targets(binding()));
        let response = server.get(&format!("/api/v1/notifications/targets/{}", token()));
        assert_eq!(response.status, 200, "{}", response.text());
        let document: Document = serde_json::from_slice(&response.body).unwrap();
        document.check().unwrap();
        let value = response.json();
        let result = &value["record"]["target_result"];
        assert_eq!(
            result["reference"],
            serde_json::to_value(binding()).unwrap()
        );
        assert_eq!(result["state"], expected);
        assert_eq!(
            result["freshness"]["state"],
            if expected == "unread" {
                "unknown"
            } else {
                "fresh"
            }
        );
        assert!(room.invocations().is_empty());
        let log = server.settled_log();
        assert!(!log.contains(&token()));
        assert!(log.contains("/api/v1/notifications/targets/*"));
        assert!(!gh.invocations().iter().any(|args| {
            args.iter()
                .any(|arg| matches!(arg.as_str(), "POST" | "PATCH" | "tell" | "spawn"))
        }));
    }
}

#[test]
fn notification_target_unknown_mapping_and_access_refusal_reveal_no_detail() {
    for (index, refusal) in [
        TargetReadError::SignedOut,
        TargetReadError::Denied,
        TargetReadError::Unavailable,
    ]
    .into_iter()
    .enumerate()
    {
        let room = Fake::new(
            &format!("notification_target_denied_room_{index}"),
            "normal",
        );
        let gh = s::fake(&format!("notification_target_denied_gh_{index}"), vec![]);
        let source = NotificationTargets {
            read_mapping: Arc::new(move |_, _| Err(refusal)),
        };
        let server = s::serve_targets(&gh, &room, source);
        let response = server.get(&format!("/api/v1/notifications/targets/{}", token()));
        assert_eq!(response.status, [401, 403, 404][index]);
        assert_eq!(response.header("Cache-Control"), Some("no-store"));
        assert!(response.json().get("record").is_none());
        assert!(!response.text().contains("synthetic-owner"));
        assert!(gh.invocations().is_empty());
        assert!(room.invocations().is_empty());
    }
}

#[test]
fn notification_target_only_accepts_an_exact_get_without_query_or_body() {
    let room = Fake::new("notification_target_guards_room", "normal");
    let gh = s::fake("notification_target_guards_gh", vec![]);
    let server = s::serve_targets(&gh, &room, targets(binding()));
    let path = format!("/api/v1/notifications/targets/{}", token());
    for suffix in ["?", "?next=other", "/", "0"] {
        assert_eq!(server.get(&format!("{path}{suffix}")).status, 400);
    }
    assert_eq!(server.get("/api/v1/notifications/targets/%31").status, 400);
    for method in ["POST", "PUT", "DELETE", "HEAD"] {
        let response = server.request(method, &path);
        assert_eq!(response.status, 405);
        assert_eq!(response.header("Allow"), Some("GET"));
        if method == "HEAD" {
            assert!(response.body.is_empty());
            assert_eq!(response.header("Content-Length"), None);
        }
    }
    let body = server.send(
        format!(
            "GET {path} HTTP/1.1\r\nHost: {}\r\nContent-Length: 1\r\nConnection: close\r\n\r\nx",
            server.host()
        )
        .as_bytes(),
    );
    assert_eq!(body.status, 400);
    let unknown = server.get(&format!("/api/v1/notifications/targets/{}", "2".repeat(64)));
    assert_eq!(unknown.status, 404);
    assert_eq!(unknown.json()["error"]["kind"], "no_route");
    assert!(gh.invocations().is_empty());
    assert!(room.invocations().is_empty());
}

#[test]
fn notification_target_incident_retains_its_source_without_inventing_escalation() {
    for (index, source) in ["service_health", "loop_watchdog"].into_iter().enumerate() {
        let room = Fake::new(&format!("notification_incident_room_{index}"), "normal");
        let gh = s::fake(&format!("notification_incident_gh_{index}"), vec![]);
        let reference: Reference = serde_json::from_value(json!({"incident": {
            "repository":"synthetic-owner/synthetic-repo", "owner":"synthetic-engine", "source":source,
            "subject":"synthetic-server", "incident":"synthetic-incident"
        }})).unwrap();
        let server = s::serve_targets(&gh, &room, targets(reference.clone()));
        let response = server.get(&format!("/api/v1/notifications/targets/{}", token()));
        assert_eq!(response.status, 200);
        let document: Document = serde_json::from_slice(&response.body).unwrap();
        document.check().unwrap();
        let result = &response.json()["record"]["target_result"];
        assert_eq!(
            result["reference"],
            serde_json::to_value(reference).unwrap()
        );
        assert_eq!(result["state"], "unread");
        assert_eq!(result["coverage"]["gaps"][0]["source"], source);
        assert!(gh.invocations().is_empty());
        assert!(room.invocations().is_empty());
    }
}

#[test]
fn notification_target_expired_mapping_budget_starts_no_further_read() {
    use openwiz_core::{model::Timestamp, ops::Clock};
    use std::{
        sync::atomic::{AtomicUsize, Ordering},
        time::{Duration, Instant},
    };
    struct BudgetClock {
        start: Instant,
        calls: AtomicUsize,
    }
    impl Clock for BudgetClock {
        fn now(&self) -> Timestamp {
            Timestamp(10_000)
        }
        fn monotonic(&self) -> Instant {
            self.start
                + if self.calls.fetch_add(1, Ordering::SeqCst) == 0 {
                    Duration::ZERO
                } else {
                    Duration::from_secs(31)
                }
        }
    }
    let room = Fake::new("notification_budget_room", "normal");
    let record = s::record("synthetic-current", "resolved");
    let gh = s::fake(
        "notification_budget_gh",
        vec![s::comment(1001, &s::fenced(&record))],
    );
    let server = s::serve_targets_with_clock(
        &gh,
        &room,
        targets(binding()),
        Arc::new(BudgetClock {
            start: Instant::now(),
            calls: AtomicUsize::new(0),
        }),
    );
    let response = server.get(&format!("/api/v1/notifications/targets/{}", token()));
    assert_eq!(response.status, 504, "{}", response.text());
    assert!(gh.invocations().is_empty());
    assert!(room.invocations().is_empty());
}

#[test]
fn notification_target_stale_source_keeps_original_observation_age() {
    use openwiz_core::{model::Timestamp, ops::Clock};
    use std::{
        sync::atomic::{AtomicUsize, Ordering},
        time::Instant,
    };
    struct AgingClock(AtomicUsize);
    impl Clock for AgingClock {
        fn now(&self) -> Timestamp {
            Timestamp(if self.0.fetch_add(1, Ordering::SeqCst) == 0 {
                1000
            } else {
                80_001
            })
        }
        fn monotonic(&self) -> Instant {
            Instant::now()
        }
    }
    let room = Fake::new("notification_stale_room", "normal");
    let record = s::record("synthetic-current", "resolved");
    let gh = s::fake(
        "notification_stale_gh",
        vec![s::comment(1001, &s::fenced(&record))],
    );
    let server = s::serve_targets_with_clock(
        &gh,
        &room,
        targets(binding()),
        Arc::new(AgingClock(AtomicUsize::new(0))),
    );
    let response = server.get(&format!("/api/v1/notifications/targets/{}", token()));
    assert_eq!(response.status, 200);
    let document: Document = serde_json::from_slice(&response.body).unwrap();
    document.check().unwrap();
    let result = &response.json()["record"]["target_result"];
    assert_eq!(result["state"], "unread");
    assert_eq!(
        result["freshness"],
        json!({"state":"stale","snapshot_at":{"known":1000}})
    );
    assert_eq!(result["coverage"]["state"], "partial");
    assert!(room.invocations().is_empty());
}
