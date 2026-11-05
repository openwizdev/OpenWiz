//! LP3's production half, transport-independent (#805): GitHub deliveries ->
//! L4's router, once. Every payload here is synthetic: shaped after GitHub's
//! documented webhook payloads, never observed from this project's webhook.
//! Option A polling is exercised only through synthetic command responses.
//! No App permission, credential or live call is used.
#[path = "l4_support.rs"]
mod support;

use openwiz_core::fleet::model::CheckResult;
use openwiz_core::messaging::send::Status;
use openwiz_core::model::Timestamp;
use openwiz_core::ops::Clock;
use openwiz_service::events::intake::{self, Delivery, DeliverySource};
use openwiz_service::events::*;
use std::collections::VecDeque;
use std::fs::DirBuilder;
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::time::Instant;
use support::*;

/// Synthetic deliveries; `Err` entries model a failing transport.
struct Deliveries(VecDeque<Result<Delivery, EventError>>);
impl Deliveries {
    fn of(items: impl IntoIterator<Item = Delivery>) -> Self {
        Self(items.into_iter().map(Ok).collect())
    }
}
impl DeliverySource for Deliveries {
    fn next(&mut self) -> Result<Option<Delivery>, EventError> {
        self.0.pop_front().transpose()
    }
}

struct At(i64);
impl Clock for At {
    fn now(&self) -> Timestamp {
        Timestamp(self.0)
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}

const DAY_MS: i64 = 86_400_000;

fn delivery(id: &str, event: &str, payload: serde_json::Value) -> Delivery {
    Delivery {
        id: id.into(),
        event: event.into(),
        payload: payload.to_string().into_bytes(),
    }
}

fn repo_json() -> serde_json::Value {
    serde_json::json!({"full_name": "Synthetic/Project"})
}

/// A synthetic `workflow_run` naming PR 1901, the support fixture's open PR.
fn ci(id: &str) -> Delivery {
    delivery(
        id,
        "workflow_run",
        serde_json::json!({
            "action": "completed",
            "repository": repo_json(),
            "workflow_run": {"pull_requests": [{"number": 1901}]}
        }),
    )
}

fn kinds(events: &[Option<Event>]) -> Vec<Option<(EventKind, Vec<u64>, String)>> {
    events
        .iter()
        .map(|e| {
            e.as_ref().map(|e| {
                (
                    e.kind,
                    e.pull_requests.iter().map(|n| n.get()).collect(),
                    e.event_id.clone(),
                )
            })
        })
        .collect()
}

#[test]
fn lp3b_each_payload_maps_to_its_event_by_launch_fleets_number_table() {
    let r = repo_json();
    let cases = [
        delivery(
            "d-review",
            "pull_request_review",
            serde_json::json!({"repository": r, "pull_request": {"number": 1901}}),
        ),
        delivery(
            "d-ci",
            "workflow_run",
            serde_json::json!({"repository": r, "workflow_run": {"pull_requests": [{"number": 1901}, {"number": 1902}]}}),
        ),
        delivery(
            "d-suite",
            "check_suite",
            serde_json::json!({"repository": r, "check_suite": {"pull_requests": [{"number": 1902}]}}),
        ),
        delivery(
            "d-comment",
            "issue_comment",
            serde_json::json!({"repository": r, "issue": {"number": 1901, "pull_request": {}}}),
        ),
    ];
    let parsed: Vec<_> = cases
        .iter()
        .map(|d| intake::parse(&repository(), d))
        .collect();
    assert_eq!(
        kinds(&parsed),
        [
            Some((EventKind::PullRequestReview, vec![1901], "d-review".into())),
            Some((EventKind::WorkflowRun, vec![1901, 1902], "d-ci".into())),
            Some((EventKind::CheckSuite, vec![1902], "d-suite".into())),
            Some((EventKind::IssueComment, vec![1901], "d-comment".into())),
        ]
    );
    assert!(
        parsed
            .iter()
            .flatten()
            .all(|e| e.repository == repository())
    );
}

#[test]
fn lp3b_anything_else_is_no_event_and_never_a_guess() {
    let r = repo_json();
    let refused = [
        // Not one of L4's four kinds (loops.v1 accepts no others).
        delivery("d-ping", "ping", serde_json::json!({"repository": r})),
        delivery(
            "d-issues",
            "issues",
            serde_json::json!({"repository": r, "issue": {"number": 7}}),
        ),
        delivery(
            "d-pr",
            "pull_request",
            serde_json::json!({"repository": r, "pull_request": {"number": 1901}}),
        ),
        // A comment on a plain issue names no pull request.
        delivery(
            "d-issue-comment",
            "issue_comment",
            serde_json::json!({"repository": r, "issue": {"number": 7}}),
        ),
        // Another repository, or none.
        delivery(
            "d-other",
            "pull_request_review",
            serde_json::json!({"repository": {"full_name": "other/project"}, "pull_request": {"number": 1901}}),
        ),
        delivery(
            "d-norepo",
            "pull_request_review",
            serde_json::json!({"pull_request": {"number": 1901}}),
        ),
        // CI with no pull request, or a bad number.
        delivery(
            "d-empty",
            "workflow_run",
            serde_json::json!({"repository": r, "workflow_run": {"pull_requests": []}}),
        ),
        delivery(
            "d-zero",
            "pull_request_review",
            serde_json::json!({"repository": r, "pull_request": {"number": 0}}),
        ),
        delivery(
            "d-text",
            "pull_request_review",
            serde_json::json!({"repository": r, "pull_request": {"number": "1901"}}),
        ),
        delivery(
            "d-bad-entry",
            "check_suite",
            serde_json::json!({"repository": r, "check_suite": {"pull_requests": [{"number": 1901}, {}]}}),
        ),
        // Bad delivery ids.
        delivery(
            "",
            "pull_request_review",
            serde_json::json!({"repository": r, "pull_request": {"number": 1901}}),
        ),
        delivery(
            "bad\0id",
            "pull_request_review",
            serde_json::json!({"repository": r, "pull_request": {"number": 1901}}),
        ),
        delivery(
            "../escape",
            "pull_request_review",
            serde_json::json!({"repository": r, "pull_request": {"number": 1901}}),
        ),
        delivery(
            &"x".repeat(129),
            "pull_request_review",
            serde_json::json!({"repository": r, "pull_request": {"number": 1901}}),
        ),
        Delivery {
            id: "d-json".into(),
            event: "pull_request_review".into(),
            payload: b"{not json".to_vec(),
        },
    ];
    for d in &refused {
        assert!(
            intake::parse(&repository(), d).is_none(),
            "{} {}",
            d.id,
            d.event
        );
    }
}

#[test]
fn lp3b_a_delivery_reaches_the_router_once_and_is_sent_to_its_owner() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let store = fixture.store();
    let mut source = Deliveries::of([ci("d-1")]);
    let mut intake = intake::Intake::open(&fixture.0, repository(), &mut source, &Fixed).unwrap();
    let routes = intake::drain(&router(&fake, &store), &mut intake).unwrap();
    assert_eq!(routes.len(), 1);
    assert_eq!(routes[0].len(), 1);
    let RouteResult::Send(report) = &routes[0][0].1 else {
        panic!("expected a send: {routes:?}");
    };
    assert_eq!(report.status, Status::Accepted);
    assert_eq!(
        fake.calls(),
        [(
            "thr_syn_builder".into(),
            format!(
                "CI failed for pull request #1901 at {} (ci). Read the failed job log, fix it, and hand back a new green head.",
                "a".repeat(40)
            )
        )]
    );
    assert_eq!(*fake.trace.lock().unwrap(), ["facts", "tell"]);
}

#[test]
fn lp3b_a_duplicate_delivery_reaches_the_router_never_again_even_after_a_restart() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let store = fixture.store();
    let router = router(&fake, &store);
    let mut source = Deliveries::of([ci("d-1"), ci("d-1")]);
    let mut intake = intake::Intake::open(&fixture.0, repository(), &mut source, &Fixed).unwrap();
    assert_eq!(intake::drain(&router, &mut intake).unwrap().len(), 1);
    drop(intake);
    // A new process on the same state directory: the delivery is still known.
    let mut again = Deliveries::of([ci("d-1")]);
    let mut intake = intake::Intake::open(&fixture.0, repository(), &mut again, &Fixed).unwrap();
    assert!(intake::drain(&router, &mut intake).unwrap().is_empty());
    assert_eq!(*fake.trace.lock().unwrap(), ["facts", "tell"]);
    assert_eq!(fake.calls().len(), 1);
}

#[test]
fn lp3b_a_late_delivery_changes_nothing() {
    // A second delivery for a relay already sent: the router re-reads, and the
    // shared relay record answers; no second tell.
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let store = fixture.store();
    let mut source = Deliveries::of([ci("d-1"), ci("d-2-late")]);
    let mut intake = intake::Intake::open(&fixture.0, repository(), &mut source, &Fixed).unwrap();
    let routes = intake::drain(&router(&fake, &store), &mut intake).unwrap();
    assert_eq!(routes.len(), 2);
    assert_eq!(fake.calls().len(), 1);

    // A late failure for CI that has since passed: no relay is due, nothing is
    // sent; the green PR's first review stays the check-in's (L4's rule).
    let fixture = Fixture::new();
    let mut current = snapshot();
    for check in &mut pr(&mut current).ci.as_mut().unwrap().checks {
        check.result = CheckResult::Pass;
    }
    let fake = Fake::new(current);
    let store = fixture.store();
    let mut source = Deliveries::of([ci("d-3-late")]);
    let mut intake = intake::Intake::open(&fixture.0, repository(), &mut source, &Fixed).unwrap();
    let routes = intake::drain(&router(&fake, &store), &mut intake).unwrap();
    assert!(
        matches!(
            routes[0][0].1,
            RouteResult::CheckIn(CheckInReason::OwnershipUnknown)
        ),
        "{routes:?}"
    );
    assert!(fake.calls().is_empty());
}

#[test]
fn lp3b_irrelevant_deliveries_are_skipped_and_the_rest_still_arrive() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let store = fixture.store();
    let mut source = Deliveries::of([
        delivery("d-ping", "ping", serde_json::json!({"zen": "synthetic"})),
        ci("d-1"),
    ]);
    let mut intake = intake::Intake::open(&fixture.0, repository(), &mut source, &Fixed).unwrap();
    let routes = intake::drain(&router(&fake, &store), &mut intake).unwrap();
    assert_eq!(routes.len(), 1);
    assert_eq!(fake.calls().len(), 1);
}

#[test]
fn lp3b_a_failing_transport_routes_nothing_and_leaves_the_check_in_its_work() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let store = fixture.store();
    let router = router(&fake, &store);
    let mut source = Deliveries(VecDeque::from([
        Err(EventError::SourceUnavailable),
        Ok(ci("d-1")),
    ]));
    let mut intake = intake::Intake::open(&fixture.0, repository(), &mut source, &Fixed).unwrap();
    assert_eq!(
        intake::drain(&router, &mut intake).unwrap_err(),
        EventError::SourceUnavailable
    );
    assert!(fake.trace.lock().unwrap().is_empty());
    // The check-in's reconcile seam still does the work, once.
    assert!(matches!(router.route_pr(n(1901)), RouteResult::Send(_)));
    assert_eq!(fake.calls().len(), 1);
    // The same delivery, once the transport is back, repeats nothing.
    let mut intake = intake::Intake::open(&fixture.0, repository(), &mut source, &Fixed).unwrap();
    assert_eq!(intake::drain(&router, &mut intake).unwrap().len(), 1);
    assert_eq!(fake.calls().len(), 1);
}

#[test]
fn lp3b_an_unwritable_intake_record_routes_nothing_and_leaves_the_check_in_its_work() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let store = fixture.store();
    let router = router(&fake, &store);
    let mut empty = Deliveries::of([]);
    drop(intake::Intake::open(&fixture.0, repository(), &mut empty, &Fixed).unwrap());
    let seen = fixture.0.join("events").join("intake");
    std::fs::set_permissions(&seen, std::fs::Permissions::from_mode(0o500)).unwrap();
    let mut source = Deliveries::of([ci("d-1")]);
    let mut intake = intake::Intake::open(&fixture.0, repository(), &mut source, &Fixed).unwrap();
    let outcome = intake::drain(&router, &mut intake);
    std::fs::set_permissions(&seen, std::fs::Permissions::from_mode(0o700)).unwrap();
    assert_eq!(outcome.unwrap_err(), EventError::SourceUnavailable);
    assert!(fake.trace.lock().unwrap().is_empty());
    assert!(matches!(router.route_pr(n(1901)), RouteResult::Send(_)));
    assert_eq!(fake.calls().len(), 1);
}

#[test]
fn lp3b_an_unsafe_intake_directory_is_refused() {
    for case in ["file", "symlink", "open-mode"] {
        let fixture = Fixture::new();
        let events = fixture.0.join("events");
        DirBuilder::new().mode(0o700).create(&events).unwrap();
        let seen = events.join("intake");
        match case {
            "file" => std::fs::write(&seen, "").unwrap(),
            "symlink" => std::os::unix::fs::symlink(&fixture.0, &seen).unwrap(),
            _ => {
                DirBuilder::new().mode(0o700).create(&seen).unwrap();
                std::fs::set_permissions(&seen, std::fs::Permissions::from_mode(0o755)).unwrap();
            }
        }
        let mut source = Deliveries::of([ci("d-1")]);
        assert_eq!(
            intake::Intake::open(&fixture.0, repository(), &mut source, &Fixed).err(),
            Some(EventError::SourceUnavailable),
            "{case}"
        );
    }
}

#[test]
fn lp3b_old_delivery_records_are_pruned_after_retention_and_a_redelivery_is_harmless() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let store = fixture.store();
    let router = router(&fake, &store);
    let start = 2_000_000;
    let mut source = Deliveries::of([ci("d-1")]);
    let clock = At(start);
    let mut intake = intake::Intake::open(&fixture.0, repository(), &mut source, &clock).unwrap();
    assert_eq!(intake::drain(&router, &mut intake).unwrap().len(), 1);
    drop(intake);
    let count = || {
        std::fs::read_dir(fixture.0.join("events/intake"))
            .unwrap()
            .count()
    };
    assert_eq!(count(), 1);

    // Within retention: still a duplicate.
    let clock = At(start + intake::RETAIN_MS - 1);
    let mut source = Deliveries::of([ci("d-1")]);
    let mut intake = intake::Intake::open(&fixture.0, repository(), &mut source, &clock).unwrap();
    assert!(intake::drain(&router, &mut intake).unwrap().is_empty());
    drop(intake);
    assert_eq!(count(), 1);

    // Past retention: the record is gone, and the router's relay record still
    // keeps the send at one.
    let clock = At(start + intake::RETAIN_MS + 1);
    let mut source = Deliveries::of([ci("d-1")]);
    let mut intake = intake::Intake::open(&fixture.0, repository(), &mut source, &clock).unwrap();
    assert_eq!(intake::drain(&router, &mut intake).unwrap().len(), 1);
    assert_eq!(fake.calls().len(), 1);
    // Longer than the three days of deliveries GitHub documents keeping.
    const { assert!(intake::RETAIN_MS > 3 * DAY_MS) };
}

#[test]
fn lp3b_r1_each_new_directory_entry_is_synced_into_its_parent_or_nothing_is_admitted() {
    // A directory that can't be opened can't be synced: Linux needs the parent
    // opened to persist a new entry, so these modes plant a failed parent sync
    // (the test runs as a non-root user, as AP5 does).
    for (case, locked) in [
        ("fresh root", ""),
        ("existing events", ""),
        ("existing intake", "events"),
    ] {
        let fixture = Fixture::new();
        if case != "fresh root" {
            DirBuilder::new()
                .mode(0o700)
                .create(fixture.0.join("events"))
                .unwrap();
        }
        if case == "existing intake" {
            DirBuilder::new()
                .mode(0o700)
                .create(fixture.0.join("events/intake"))
                .unwrap();
        }
        let dir = fixture.0.join(locked);
        // Write and search only: entries can still be made, never synced.
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o300)).unwrap();
        let fake = Fake::new(snapshot());
        let mut source = Deliveries::of([ci("d-1")]);
        let opened = intake::Intake::open(&fixture.0, repository(), &mut source, &Fixed)
            .map(|_| ())
            .err();
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700)).unwrap();
        assert_eq!(opened, Some(EventError::SourceUnavailable), "{case}");
        assert!(fake.trace.lock().unwrap().is_empty(), "{case}");
        assert!(fake.calls().is_empty(), "{case}");
    }
}

#[path = "l4b_transport.rs"]
mod transport;

#[path = "l4b_composition.rs"]
mod composition;
