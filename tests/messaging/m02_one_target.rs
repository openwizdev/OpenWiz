//! M2 One target: exactly one id, resolved in the same operation. Not found
//! means zero `tell` calls. Archived and hidden targets are refused
//! (provisional choice 3), also with zero calls.

use openwiz_core::messaging::Mode;
use openwiz_core::messaging::send::{Delivery, FailReason, SendResult, Status};
use openwiz_core::model::Fact;

use crate::support::*;

fn failed_reason(result: &SendResult) -> FailReason {
    match result {
        SendResult::Outcome {
            delivery: Delivery::Failed { reason, .. },
            ..
        } => *reason,
        other => panic!("expected failed, got {other:?}"),
    }
}

#[test]
fn a_target_that_is_not_found_gets_no_tell() {
    let fake = SendFake::new("m02_not_found", "send");
    let report = fake.report(&request(
        "thr_syn_9999",
        Mode::Queue,
        "Synthetic",
        "op-m02-nf",
    ));
    assert_eq!(report.status, Status::Failed);
    assert_eq!(failed_reason(&report.result), FailReason::NotFound);
    assert!(report.summary.contains("not found"), "{}", report.summary);
    assert_eq!(fake.tell_count(), 0);
    assert!(fake.tells().is_empty());

    let (code, out, err) = fake.cli(&["thr_syn_9999", "--", "Synthetic"], "");
    assert_eq!(code, 3, "{out}{err}");
    assert!(fake.tells().is_empty());
}

#[test]
fn the_target_is_resolved_in_the_same_operation() {
    let fake = SendFake::new("m02_resolved", "send");
    let report = fake.report(&request(
        "thr_syn_0001",
        Mode::Queue,
        "Synthetic",
        "op-m02-resolved",
    ));
    assert_eq!(report.target.id.0, "thr_syn_0001");
    assert_eq!(
        report.target.title,
        Fact::Known("Synthetic session 1".to_owned())
    );
    let calls = fake.invocations();
    let show = calls
        .iter()
        .position(|a| a.get(..2) == Some(&["thread".to_owned(), "show".to_owned()][..]))
        .expect("thread show");
    let tell = calls
        .iter()
        .position(|a| a.get(..2) == Some(&["thread".to_owned(), "tell".to_owned()][..]))
        .expect("thread tell");
    assert!(show < tell, "{calls:?}");
    assert_eq!(calls[show][2], "thr_syn_0001");
    assert_eq!(calls[tell][2], "thr_syn_0001", "the same target");
}

#[test]
fn archived_and_hidden_targets_are_refused_with_no_tell() {
    let fake = SendFake::new("m02_archived_hidden", "send");
    for (target, reason) in [
        ("thr_syn_0008", FailReason::TargetArchived),
        ("thr_syn_0007", FailReason::TargetHidden),
    ] {
        let report = fake.report(&request(
            target,
            Mode::Queue,
            "Synthetic",
            &format!("op-m02-{target}"),
        ));
        assert_eq!(failed_reason(&report.result), reason, "{target}");
    }
    assert_eq!(fake.tell_count(), 0);
}

fn assert_visibility_refused(case: &str, visibility: Option<&str>) {
    let mut show: serde_json::Value = serde_json::from_slice(
        &std::fs::read(send_fixtures().join("thread-show-0015.json")).unwrap(),
    )
    .unwrap();
    // Synthetic missing/future visibility, never an observed provider shape.
    show["thread"].as_object_mut().unwrap().remove("visibility");
    if let Some(visibility) = visibility {
        show["thread"]["visibility"] = serde_json::json!(visibility);
    }
    let fake = SendFake::with(
        &format!("m02_visibility_{case}"),
        vec![serde_json::json!({
            "argv": ["thread", "show", "thr_syn_0015", "--json"],
            "stdout": show.to_string()
        })],
    );
    let mut req = request(
        "thr_syn_0015",
        Mode::Queue,
        "Synthetic",
        &format!("op-m02-visibility-{case}"),
    );
    // The paused-queue acknowledgement must not mask a visibility bypass.
    req.resume_paused_queue = true;
    let report = fake.report(&req);
    assert_eq!(
        failed_reason(&report.result),
        FailReason::TargetVisibilityUnknown
    );
    assert_eq!(report.status, Status::Failed);
    assert_eq!(fake.tell_count(), 0);
    assert!(fake.tells().is_empty());
}

#[test]
fn missing_visibility_is_refused_without_a_tell() {
    assert_visibility_refused("missing", None);
}

#[test]
fn unknown_visibility_is_refused_without_a_tell() {
    assert_visibility_refused("unknown", Some("synthetic_future_value"));
}

#[test]
fn the_cli_takes_exactly_one_target() {
    let fake = SendFake::new("m02_cli_one_target", "send");
    for args in [
        vec!["thr_syn_0001", "thr_syn_0002", "Synthetic"],
        vec!["thr_syn_0001,thr_syn_0002", "--", "Synthetic"],
        vec!["thr_syn_0001 thr_syn_0002", "--", "Synthetic"],
        vec!["--", "-thr_syn_0001", "Synthetic"],
        vec![],
    ] {
        let (code, out, err) = fake.cli(&args, "Synthetic");
        assert_eq!(code, 2, "{args:?}: {out}{err}");
    }
    assert_eq!(
        fake.invocations(),
        Vec::<Vec<String>>::new(),
        "nothing is read or sent"
    );
}
