//! M5 Effects are worked out before sending, with the read's age, for every
//! state. A queue that appears paused is shown before anything is sent, and
//! the CLI does not send without the owner's acknowledgement. Unknowns stay
//! unknown.

use openwiz_core::messaging::Mode;
use openwiz_core::messaging::effects::{
    Activity, EffectKind, Effects, QueuedWork, TargetRecord, work_out,
};
use openwiz_core::messaging::send::Status;
use openwiz_core::model::{Fact, SessionId, Timestamp};
use openwiz_core::source::Placement;

use crate::support::*;

fn effects_of(fake: &SendFake, target: &str, mode: Mode, op_id: &str) -> Effects {
    let mut r = request(target, mode, "Synthetic", op_id);
    r.resume_paused_queue = true;
    r.accept_possible_duplicate = true;
    fake.report(&r)
        .effects
        .unwrap_or_else(|| panic!("{target}: no effects"))
}

fn kind(effects: &Effects) -> Option<EffectKind> {
    match &effects.effect {
        Fact::Known(effect) => Some(effect.kind),
        Fact::Unknown(_) => None,
    }
}

fn list_key_preview(read: &str, target: &str, case: usize, raw: &str) -> (i32, serde_json::Value) {
    let fake = SendFake::with(
        &format!("m05_{read}_keys_{case}"),
        vec![serde_json::json!({
            "argv": [read, "list", "--json"], "stdout": raw
        })],
    );
    let result = fake.cli_json(&[target, "--preview"], "");
    assert!(validate_def("preview", &result.1).is_empty(), "{result:?}");
    let mut calls = vec![
        vec!["thread", "show", target, "--json"],
        vec!["thread", "list", "--json"],
    ];
    if read == "machine" {
        calls.push(vec!["machine", "list", "--json"]);
    }
    assert_eq!(fake.invocations(), calls);
    assert!(fake.tells().is_empty());
    assert_eq!(fake.tell_count(), 0);
    assert!(!fake.state.exists(), "preview created state");
    result
}

#[test]
fn preview_refuses_repeated_thread_list_keys_and_keeps_single_key_facts() {
    use serde_json::json;
    // Raw, synthetic duplicate keys must survive until the adapter reads them.
    let controls = [
        (
            r#""queuedWork":"none","hasPendingInteraction":false"#,
            Some("starts_turn"),
            Some(false),
        ),
        (
            r#""queuedWork":"waiting","hasPendingInteraction":false"#,
            Some("starts_turn"),
            Some(true),
        ),
        (
            r#""queuedWork":"none","hasPendingInteraction":true"#,
            Some("waits_for_interaction"),
            Some(false),
        ),
    ];
    let malformed = [
        r#""queuedWork":"none","queuedWork":"waiting","hasPendingInteraction":false"#,
        r#""queuedWork":"waiting","queuedWork":"none","hasPendingInteraction":false"#,
        r#""queuedWork":"none","hasPendingInteraction":false,"hasPendingInteraction":true"#,
        r#""queuedWork":"none","hasPendingInteraction":true,"hasPendingInteraction":false"#,
        r#""queuedWork":"none","queuedWork":"none","hasPendingInteraction":false"#,
        r#""queuedWork":"none","hasPendingInteraction":false,"hasPendingInteraction":false"#,
        r#""queuedWork":"none","queued\u0057ork":"waiting","hasPendingInteraction":false"#,
        r#""queuedWork":"none","hasPendingInteraction":false,"hasPendingInter\u0061ction":true"#,
        r#""queuedWork":"none","hasPendingInteraction":false,"extra":[{"x":1,"x":2}]"#,
        "not JSON",
    ];
    let cases = controls
        .into_iter()
        .chain(malformed.map(|fields| (fields, None, None)));
    for (case, (fields, effect, paused)) in cases.into_iter().enumerate() {
        let raw = format!(r#"[{{"id":"thr_syn_0011",{fields}}}]"#);
        let (code, doc) = list_key_preview("thread", "thr_syn_0011", case, &raw);
        let ack = paused != Some(false);
        assert_eq!(code, if ack { 5 } else { 0 }, "case {case}: {doc:#}");
        assert_eq!(
            doc["status"],
            if ack {
                "needs_acknowledgement"
            } else {
                "ready"
            }
        );
        assert_eq!(doc["effects"]["needs_acknowledgement"], ack);
        if let Some(effect) = effect {
            assert_eq!(doc["effects"]["effect"]["known"]["kind"], effect);
            assert_eq!(
                doc["effects"]["paused_queue"]["known"]["appears_paused"],
                paused.unwrap()
            );
            assert_eq!(doc["gaps"], json!([]));
        } else {
            assert_eq!(
                doc["effects"]["effect"],
                json!({"unknown":
                "whether an interaction is pending: thread list returned output that is not JSON"})
            );
            assert_eq!(
                doc["effects"]["paused_queue"],
                json!({"unknown":
                "its queued work: thread list returned output that is not JSON"})
            );
            assert_eq!(
                doc["gaps"],
                json!([{"subject":"thread list",
                "detail":"thread list returned output that is not JSON"}])
            );
        }
    }
}

#[test]
fn preview_refuses_repeated_machine_list_keys_and_keeps_single_key_facts() {
    use serde_json::json;
    let controls = [
        (r#""status":"connected""#, Some("queues_behind_turn"), false),
        (r#""status":"disconnected""#, None, false),
    ];
    let malformed = [
        r#""status":"connected","status":"disconnected""#,
        r#""status":"disconnected","status":"connected""#,
        r#""status":"connected","status":"connected""#,
        r#""status":"connected","sta\u0074us":"disconnected""#,
        r#""status":"connected","extra":[{"x":1,"x":2}]"#,
        "not JSON",
    ];
    let cases = controls
        .into_iter()
        .chain(malformed.map(|fields| (fields, None, true)));
    for (case, (fields, effect, malformed)) in cases.into_iter().enumerate() {
        let raw = format!(r#"[{{"id":"mch_syn_0001",{fields}}}]"#);
        let (code, doc) = list_key_preview("machine", "thr_syn_0002", case, &raw);
        assert_eq!(code, 0, "case {case}: {doc:#}");
        assert_eq!(doc["status"], "ready");
        assert_eq!(doc["effects"]["needs_acknowledgement"], false);
        assert_eq!(
            doc["effects"]["paused_queue"]["known"]["appears_paused"],
            false
        );
        if let Some(effect) = effect {
            assert_eq!(doc["effects"]["effect"]["known"]["kind"], effect);
            assert_eq!(doc["gaps"], json!([]));
        } else {
            let why = if malformed {
                "machine list returned output that is not JSON"
            } else {
                "schema drift: machine list status has a value room-cli 0.43.1 did not document"
            };
            assert_eq!(
                doc["effects"]["effect"],
                json!({"unknown":
                format!("whether its host is connected: {why}")})
            );
            assert_eq!(
                doc["gaps"],
                json!([{"subject":"machine list", "detail":why}])
            );
        }
    }
}

#[test]
fn preview_refuses_repeated_show_keys_and_keeps_single_key_effects() {
    use openwiz_cli::send::{EXIT_DELIVERED, EXIT_SEND_FAILED};
    use serde_json::json;
    let original = std::fs::read_to_string(
        std::path::Path::new(FIXTURES).join("normal/thread-show-0001.json"),
    )
    .unwrap();
    // Raw JSON preserves these synthetic duplicates; Value would erase them.
    let cases = [
        (r#""status": "idle""#, Some("starts_turn")),
        (r#""status": "active""#, Some("queues_behind_turn")),
        (r#""status": "active", "status": "idle""#, None),
        (r#""status": "idle", "status": "active""#, None),
        (r#""status": "idle", "status": "idle""#, None),
        (r#""status": "active", "status": "active""#, None),
        (r#""status": "active", "sta\u0074us": "idle""#, None),
        (r#""status": null, "status": "idle""#, None),
        (r#""status": "idle", "extra": [{"x": 1, "x": 2}]"#, None),
        (
            r#""status": "idle", "extra": [null, true, -1, 1.5, "x", {"x": 1}, {"x": 2}]"#,
            Some("starts_turn"),
        ),
    ];
    let cases = cases
        .into_iter()
        .map(|(fields, expected)| {
            (
                original.replacen(r#""status": "idle""#, fields, 1),
                expected,
            )
        })
        .chain(std::iter::once((
            original.replacen(r#""thread": {"#, r#""thread": {}, "thread": {"#, 1),
            None,
        )));
    for (case, (raw, expected)) in cases.enumerate() {
        assert!(serde_json::from_str::<serde_json::Value>(&raw).is_ok());
        let fake = SendFake::with(
            &format!("m05_show_keys_{case}"),
            vec![json!({
                "argv": ["thread", "show", "thr_syn_0001", "--json"], "stdout": raw
            })],
        );
        let (code, doc) = fake.cli_json(&["thr_syn_0001", "--preview"], "");
        assert!(validate_def("preview", &doc).is_empty(), "{doc:#}");
        let reads = match expected {
            Some(effect) => {
                assert_eq!(code, EXIT_DELIVERED, "case {case}: {doc:#}");
                assert_eq!(doc["status"], "ready");
                assert_eq!(doc["effects"]["effect"]["known"]["kind"], effect);
                assert!(doc["refusal"].is_null());
                2
            }
            None => {
                assert_eq!(code, EXIT_SEND_FAILED, "case {case}: {doc:#}");
                assert_eq!(doc["status"], "refused");
                assert!(doc["effects"].is_null());
                assert_eq!(doc["refusal"]["reason"], "target_not_read");
                assert_eq!(
                    doc["refusal"]["text"],
                    "the target could not be read (the target read returned output that is not the documented shape); nothing was sent"
                );
                1
            }
        };
        let mut expected_reads = vec![vec!["thread", "show", "thr_syn_0001", "--json"]];
        if reads == 2 {
            expected_reads.push(vec!["thread", "list", "--json"]);
        }
        assert_eq!(fake.invocations(), expected_reads);
        assert!(fake.tells().is_empty());
        assert_eq!(fake.tell_count(), 0);
        assert!(!fake.state.exists(), "preview created state");
    }
}

#[test]
fn effects_for_every_state_read_through_the_adapter() {
    let fake = SendFake::new("m05_every_state", "send");
    let cases = [
        // idle cloud
        (
            "thr_syn_0001",
            Mode::Queue,
            Some(EffectKind::StartsTurn),
            false,
        ),
        // active cloud
        (
            "thr_syn_0006",
            Mode::Queue,
            Some(EffectKind::QueuesBehindTurn),
            false,
        ),
        (
            "thr_syn_0006",
            Mode::Steer,
            Some(EffectKind::AsksToSteer),
            false,
        ),
        // active local, host connected
        (
            "thr_syn_0002",
            Mode::Queue,
            Some(EffectKind::QueuesBehindTurn),
            false,
        ),
        // a pending interaction
        (
            "thr_syn_0012",
            Mode::Queue,
            Some(EffectKind::WaitsForInteraction),
            false,
        ),
        (
            "thr_syn_0012",
            Mode::Steer,
            Some(EffectKind::WaitsForInteraction),
            false,
        ),
        // a local host missing from the machine list: unknown
        ("thr_syn_0004", Mode::Queue, None, false),
        // an error status: unknown
        ("thr_syn_0003", Mode::Queue, None, false),
        // an unrecognised status: unknown
        ("thr_syn_0014", Mode::Queue, None, false),
        // missing from thread list: unknown, and a paused queue cannot be
        // ruled out
        ("thr_syn_0015", Mode::Queue, None, true),
        // idle with queued work waiting: appears paused
        (
            "thr_syn_0011",
            Mode::Queue,
            Some(EffectKind::StartsTurn),
            true,
        ),
    ];
    for (i, (target, mode, expected, ack)) in cases.into_iter().enumerate() {
        let effects = effects_of(&fake, target, mode, &format!("op-m05-{i}"));
        assert_eq!(kind(&effects), expected, "{target} {mode:?}: {effects:#?}");
        assert_eq!(effects.needs_acknowledgement, ack, "{target}: {effects:#?}");
        match (&effects.effect, expected) {
            (Fact::Known(effect), Some(kind)) => assert_eq!(effect.text, kind.words()),
            (Fact::Unknown(why), None) => assert!(!why.trim().is_empty()),
            other => panic!("{target}: {other:?}"),
        }
        assert_eq!(effects.read_at, T0, "the read's time");
        assert_eq!(effects.read_age_ms, 0, "the fixed clock does not move");
    }
    let words = effects_of(&fake, "thr_syn_0001", Mode::Queue, "op-m05-words");
    assert_eq!(
        words.effect,
        Fact::Known(openwiz_core::messaging::effects::Effect {
            kind: EffectKind::StartsTurn,
            text: "starts a turn; may wake it".to_owned()
        })
    );
    let paused = effects_of(&fake, "thr_syn_0011", Mode::Queue, "op-m05-paused");
    match &paused.paused_queue {
        Fact::Known(p) => {
            assert!(p.appears_paused);
            assert_eq!(p.queued_messages, Fact::Known(2));
            assert_eq!(
                p.text,
                "resumes the paused queue; 2 queued messages may run after this one"
            );
        }
        other => panic!("{other:?}"),
    }
    let missing = effects_of(&fake, "thr_syn_0015", Mode::Queue, "op-m05-missing");
    assert!(
        matches!(missing.paused_queue, Fact::Unknown(_)),
        "{missing:#?}"
    );
}

fn target() -> TargetRecord {
    TargetRecord {
        id: SessionId("thr_syn_0001".to_owned()),
        title: Fact::Known("Synthetic session 1".to_owned()),
        activity: Fact::Known(Activity::Idle),
        hidden: Fact::Known(false),
        archived: Fact::Known(false),
        placement: Fact::Known(Placement::Cloud),
        host_connected: None,
        queued_work: Fact::Known(QueuedWork::None),
        queued_message_count: Fact::Known(0),
        pending_interaction: Fact::Known(false),
        problems: vec![],
    }
}

#[test]
fn send_effects_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 2] = [
        (
            "the_core_rule_covers_states_the_fixtures_cannot_show",
            the_core_rule_covers_states_the_fixtures_cannot_show,
        ),
        (
            "waiting_work_on_an_errored_target_stays_unknown_and_requires_acknowledgement",
            waiting_work_on_an_errored_target_stays_unknown_and_requires_acknowledgement,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: m05_effects::{name}");
        proof();
    }
}

fn waiting_work_on_an_errored_target_stays_unknown_and_requires_acknowledgement() {
    let mut errored = target();
    errored.activity = Fact::Known(Activity::Errored);
    errored.queued_work = Fact::Known(QueuedWork::Waiting);
    errored.queued_message_count = Fact::Known(1);

    for mode in [Mode::Queue, Mode::Steer] {
        let effects = work_out(&errored, mode, T0, T0);
        assert_eq!(
            (
                matches!(effects.paused_queue, Fact::Unknown(_)),
                effects.needs_acknowledgement,
            ),
            (true, true),
            "{mode:?}: a paused queue cannot be ruled out on an errored target"
        );
    }
}

fn the_core_rule_covers_states_the_fixtures_cannot_show() {
    let read = Timestamp(1_000_000);
    let now = Timestamp(1_004_500);
    let base = work_out(&target(), Mode::Queue, read, now);
    assert_eq!(base.read_age_ms, 4_500, "the read's age when shown");
    assert_eq!(kind(&base), Some(EffectKind::StartsTurn));

    let mut offline = target();
    offline.placement = Fact::Known(Placement::Host("mch_syn_0001".to_owned()));
    offline.host_connected = Some(Fact::Known(false));
    let e = work_out(&offline, Mode::Steer, read, now);
    assert_eq!(kind(&e), Some(EffectKind::WaitsForHost));
    assert_eq!(
        EffectKind::WaitsForHost.words(),
        "waits for its host to come back online"
    );

    let mut host_unknown = offline.clone();
    host_unknown.host_connected = Some(Fact::Unknown("synthetic".to_owned()));
    assert_eq!(kind(&work_out(&host_unknown, Mode::Queue, read, now)), None);

    // Queued work waiting behind a running turn is not a paused queue.
    let mut running = target();
    running.activity = Fact::Known(Activity::Running);
    running.queued_work = Fact::Known(QueuedWork::Waiting);
    running.queued_message_count = Fact::Known(3);
    let e = work_out(&running, Mode::Queue, read, now);
    assert!(!e.needs_acknowledgement, "{e:#?}");
    assert_eq!(kind(&e), Some(EffectKind::QueuesBehindTurn));

    // Waiting work on a thread whose activity is unknown: cannot be ruled out.
    let mut unknown_activity = running.clone();
    unknown_activity.activity = Fact::Unknown("synthetic".to_owned());
    let e = work_out(&unknown_activity, Mode::Queue, read, now);
    assert!(e.needs_acknowledgement, "{e:#?}");
    assert!(matches!(e.paused_queue, Fact::Unknown(_)));
    assert_eq!(kind(&e), None);

    // Unknown queued work, but nothing queued: no paused queue to resume.
    let mut nothing_queued = target();
    nothing_queued.queued_work = Fact::Unknown("synthetic".to_owned());
    let e = work_out(&nothing_queued, Mode::Queue, read, now);
    assert!(!e.needs_acknowledgement, "{e:#?}");

    // An unknown count on a paused queue still names the effect.
    let mut paused = target();
    paused.queued_work = Fact::Known(QueuedWork::Waiting);
    paused.queued_message_count = Fact::Unknown("synthetic".to_owned());
    let e = work_out(&paused, Mode::Queue, read, now);
    assert!(e.needs_acknowledgement);
    match &e.paused_queue {
        Fact::Known(p) => assert_eq!(
            p.text,
            "resumes the paused queue; an unknown number of queued messages may run after this one"
        ),
        other => panic!("{other:?}"),
    }

    // A pending interaction that cannot be read: unknown, never guessed.
    let mut interaction = target();
    interaction.pending_interaction = Fact::Unknown("synthetic".to_owned());
    assert_eq!(kind(&work_out(&interaction, Mode::Queue, read, now)), None);
}

#[test]
fn effects_are_worked_out_and_recorded_before_the_call() {
    let fake = SendFake::new("m05_before_the_call", "send");
    let report = fake.report(&request(
        "thr_syn_0006",
        Mode::Queue,
        "Synthetic",
        "op-m05-before",
    ));
    let at_tell = fake.records_at_tell(1);
    assert_eq!(at_tell.len(), 1, "{at_tell:#?}");
    let on_disk = &at_tell[0];
    assert_eq!(on_disk["state"], "dispatching");
    assert_eq!(
        on_disk["effects"],
        serde_json::to_value(report.effects.as_ref().expect("effects")).unwrap(),
        "the effects shown are the ones on disk before the call"
    );
    assert_eq!(
        on_disk["effects"]["effect"]["known"]["text"],
        "queues behind the current turn"
    );
}

#[test]
fn a_paused_queue_is_shown_and_not_sent_without_acknowledgement() {
    let fake = SendFake::new("m05_paused_gate", "send");
    let (code, out, err) = fake.cli(&["thr_syn_0011", "--", "Synthetic"], "");
    assert_eq!(code, 5, "{out}{err}");
    assert!(
        out.contains("resumes the paused queue; 2 queued messages may run after this one"),
        "{out}"
    );
    assert!(out.contains("--resume-paused-queue"), "{out}");
    assert_eq!(fake.tell_count(), 0, "nothing sent");

    let (code, json) = fake.cli_json(&["thr_syn_0011", "--", "Synthetic again"], "");
    assert_eq!(code, 5);
    assert_eq!(json["status"], "failed");
    assert_eq!(
        json["result"]["delivery"]["reason"],
        "paused_queue_not_acknowledged"
    );
    assert_eq!(json["effects"]["needs_acknowledgement"], true);
    assert_eq!(fake.tell_count(), 0);

    let (code, out, err) = fake.cli(
        &["thr_syn_0011", "--resume-paused-queue", "--", "Synthetic"],
        "",
    );
    assert_eq!(code, 0, "{out}{err}");
    assert!(out.contains("resumes the paused queue"), "{out}");
    assert_eq!(fake.tell_count(), 1);
}

#[test]
fn duplicate_queue_rows_require_acknowledgement() {
    use openwiz_core::messaging::preview::{PreviewStatus, preview};
    use openwiz_core::messaging::send::{Delivery, FailReason, Messenger, SendResult};
    use serde_json::json;
    use std::time::{Duration, Instant};

    // Every duplicate shape is synthetic, including agreeing rows. Each row
    // has its own fake, so the rows run at once (#1260).
    let cases: Vec<(usize, [&str; 2], Mode)> = [
        ["none", "waiting"],
        ["waiting", "none"],
        ["none", "none"],
        ["waiting", "waiting"],
    ]
    .into_iter()
    .enumerate()
    .flat_map(|(case, work)| [Mode::Queue, Mode::Steer].map(|mode| (case, work, mode)))
    .collect();
    at_once(cases, |(case, work, mode)| {
        let rows = work.map(|work| {
            json!({
                "id": "thr_syn_0011", "queuedWork": work, "hasPendingInteraction": false
            })
        });
        let fake = SendFake::with(
            &format!("m05_duplicates_{case}_{mode:?}"),
            vec![json!({
                "argv": ["thread", "list", "--json"],
                "stdout": serde_json::to_string(&rows).unwrap()
            })],
        );
        let mut req = request(
            "thr_syn_0011",
            mode,
            "Synthetic",
            &format!("op-m05-duplicate-{case}"),
        );
        let refused = fake.report(&req);
        assert_eq!(fake.tell_count(), 0, "{work:?} {mode:?}");
        assert!(fake.tells().is_empty(), "no attempted tell");
        assert!(matches!(
            refused.result,
            SendResult::Outcome {
                delivery: Delivery::Failed {
                    reason: FailReason::PausedQueueNotAcknowledged,
                    ..
                },
                ..
            }
        ));
        let effects = refused.effects.unwrap();
        assert!(effects.needs_acknowledgement);
        assert!(matches!(effects.paused_queue, Fact::Unknown(_)));
        let shown = preview(&fake.source(), &clock(), &sid("thr_syn_0011"), mode).unwrap();
        assert_eq!(shown.status, PreviewStatus::NeedsAcknowledgement);
        assert_eq!(shown.effects, Some(effects.clone()));
        let target = fake
            .source()
            .read_target(
                &sid("thr_syn_0011"),
                Instant::now() + Duration::from_secs(3),
            )
            .unwrap();
        let why = "thread list has multiple rows for the session";
        assert_eq!(target.queued_work, Fact::Unknown(why.to_owned()));
        assert_eq!(target.pending_interaction, Fact::Unknown(why.to_owned()));
        assert_eq!(target.problems.len(), 1);
        assert_eq!(target.problems[0].subject, "thread list");
        assert_eq!(target.problems[0].detail, why);
        req.op_id = op(&format!("op-m05-duplicate-ack-{case}"));
        req.resume_paused_queue = true;
        let acknowledged = fake.report(&req);
        assert_eq!(acknowledged.effects, Some(effects));
        assert_eq!(fake.tell_count(), 1);
        assert_eq!(fake.tells().len(), 1);
    });
}

#[test]
fn unique_queue_rows_keep_their_effects() {
    use serde_json::json;
    for (work, ack) in [("none", false), ("waiting", true)] {
        let fake = SendFake::with(
            &format!("m05_unique_{work}"),
            vec![json!({
                "argv": ["thread", "list", "--json"],
                "stdout": json!([
                    {"id": "thr_syn_0001", "queuedWork": "waiting"},
                    {"id": "thr_syn_0011", "queuedWork": work, "hasPendingInteraction": false},
                    {"id": "thr_syn_0001", "queuedWork": "none"}
                ]).to_string()
            })],
        );
        let report = fake.report(&request(
            "thr_syn_0011",
            Mode::Queue,
            "Synthetic",
            &format!("op-m05-unique-{work}"),
        ));
        let effects = report.effects.unwrap();
        assert_eq!(effects.needs_acknowledgement, ack);
        assert_eq!(kind(&effects), Some(EffectKind::StartsTurn));
        assert!(matches!(effects.paused_queue, Fact::Known(p) if p.appears_paused == ack));
        assert_eq!(fake.tell_count(), u64::from(!ack));
        assert_eq!(fake.tells().len(), usize::from(!ack));
    }
}

#[test]
fn duplicate_host_rows_keep_preview_effects_unknown() {
    use openwiz_core::messaging::preview::preview;
    use serde_json::json;

    // Synthetic duplicate hosts, in both orders; no live connection claim.
    for (case, statuses) in [
        ["connected", "connected"],
        ["connected", "disconnected"],
        ["disconnected", "connected"],
        ["disconnected", "disconnected"],
        ["connected", "synthetic_unknown"],
        ["synthetic_unknown", "connected"],
    ]
    .into_iter()
    .enumerate()
    {
        for mode in [Mode::Queue, Mode::Steer] {
            let rows = statuses.map(|status| json!({"id": "mch_syn_0001", "status": status}));
            let fake = SendFake::with(
                &format!("m05_host_duplicate_{case}_{mode:?}"),
                vec![json!({
                    "argv": ["machine", "list", "--json"],
                    "stdout": serde_json::to_string(&rows).unwrap()
                })],
            );
            let report = preview(&fake.source(), &clock(), &sid("thr_syn_0002"), mode).unwrap();
            let effects = report.effects.unwrap();
            assert!(
                matches!(&effects.effect, Fact::Unknown(why) if !why.is_empty()),
                "{statuses:?} {mode:?}: {effects:?}"
            );
            assert_eq!(report.gaps.len(), 1);
            assert_eq!(report.gaps[0].subject, "machine list");
            assert_eq!(
                report.gaps[0].detail,
                "machine list has multiple rows for the host"
            );
            assert_eq!(fake.tell_count(), 0);
            assert_eq!(fake.invocations().len(), 3);
            assert!(fake.tells().is_empty());
            assert!(!fake.state.exists());
        }
    }
}

#[test]
fn unique_host_rows_preserve_preview_effects() {
    use openwiz_core::messaging::preview::preview;
    use serde_json::json;

    for (status, connected) in [
        ("connected", true),
        ("disconnected", false),
        ("synthetic_unknown", false),
    ] {
        for (mode, expected) in [
            (Mode::Queue, EffectKind::QueuesBehindTurn),
            (Mode::Steer, EffectKind::AsksToSteer),
        ] {
            let fake = SendFake::with(
                &format!("m05_host_unique_{status}_{mode:?}"),
                vec![json!({
                    "argv": ["machine", "list", "--json"],
                    "stdout": json!([
                        {"id": "mch_syn_0009", "status": "connected"},
                        {"id": "mch_syn_0001", "status": status},
                        {"id": "mch_syn_0009", "status": "disconnected"}
                    ]).to_string()
                })],
            );
            let report = preview(&fake.source(), &clock(), &sid("thr_syn_0002"), mode).unwrap();
            let effects = report.effects.unwrap();
            assert_eq!(
                kind(&effects),
                connected.then_some(expected),
                "{status} {mode:?}"
            );
            assert_eq!(report.gaps.len(), usize::from(!connected));
            assert_eq!(fake.tell_count(), 0);
            assert_eq!(fake.invocations().len(), 3);
            assert!(fake.tells().is_empty());
            assert!(!fake.state.exists());
        }
    }
}

#[test]
fn unknowns_stay_unknown_in_json_and_text() {
    let fake = SendFake::new("m05_unknowns", "send");
    let (code, json) = fake.cli_json(&["thr_syn_0014", "--", "Synthetic"], "");
    assert_eq!(code, 0, "{json}");
    let why = json["effects"]["effect"]["unknown"]
        .as_str()
        .expect("an unknown effect");
    assert!(!why.is_empty());
    let (_, text, _) = fake.cli(
        &[
            "thr_syn_0014",
            "--accept-possible-duplicate",
            "--",
            "Synthetic two",
        ],
        "",
    );
    assert!(text.contains(&format!("unknown ({why})")), "{text}");
    assert_eq!(fake.tell_count(), 2);
    let _ = Status::Accepted;
}

/// Sol S3: the read's age counts from the start of the target read, so a
/// slow later read (here `thread list`) is not hidden.
#[test]
fn the_reads_age_counts_from_the_start_of_the_target_read() {
    use openwiz_cli::SystemClock;
    use openwiz_core::messaging::send::send;
    let fake = SendFake::with(
        "m05_read_age",
        vec![serde_json::json!({
            "argv": ["thread", "list", "--json"],
            "delay_ms": 500,
            "stdout_file": send_fixtures().join("thread-list.json").to_str().unwrap()
        })],
    );
    let report = send(
        &fake.source(),
        &fake.store(),
        &SystemClock,
        &request("thr_syn_0001", Mode::Queue, "Synthetic", "op-m05-age"),
    )
    .unwrap();
    let effects = report.effects.expect("effects");
    assert!(
        effects.read_age_ms >= 400,
        "the age hides the slow read: {effects:#?}"
    );
}
