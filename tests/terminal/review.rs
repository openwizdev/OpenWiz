//! The first review's findings on #1446 (R1–R9), each as a proof through the
//! shell, the renderer or the transport. Synthetic fixtures only.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use serde_json::{Value, json};

use openwiz_terminal::actions::{
    Action, ActionContext, ActionId, ActionInput, ActionRequest, ActionResult, ActionView, Mode,
    NewThreadInput, SendInput, TransportResult,
};
use openwiz_terminal::app::{App, Detail, Key, KeyPress, NeedKey};
use openwiz_terminal::transport::execute;

use super::render::text;
use super::support::{FixtureServer, Reply, SETTLE, T, client, fixture, now, settings, shell};

fn body(name: &str) -> Value {
    serde_json::from_slice(&fixture(name)).unwrap()
}

fn press(key: Key) -> KeyPress {
    KeyPress::press(key)
}

/// R1: a grill round shows and binds each pending question on its own;
/// answered questions are not shown.
#[test]
fn r1_each_pending_grill_question_is_its_own_bound_item() {
    let server = FixtureServer::home();
    let mut decisions = body("decisions.json");
    decisions["items"][0]["request"] = json!({
        "schema": "openwiz.decisions.v1", "id": "synthetic-grill-r1", "status": "open",
        "fingerprint": "b".repeat(64), "risk": "ordinary", "kind": "grill_round",
        "grill_file": "docs/grills/synthetic.md", "round": 1, "answered": ["Q1"],
        "questions": [
            {"id": "Q1", "context": "Synthetic first context", "decides": "Synthetic first decision", "recommendation": "Synthetic first choice"},
            {"id": "Q2", "context": "Synthetic second context", "decides": "Synthetic second decision", "recommendation": "Synthetic second choice"},
            {"id": "Q3", "context": "Synthetic third context", "decides": "Synthetic third decision", "recommendation": "Synthetic third choice"}
        ]
    });
    server.route(
        "/api/v1/decisions",
        Reply::ok(decisions.to_string().into_bytes()),
    );
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    let home = text(&shell.app, now(0), 120, 40);
    assert!(!home.contains("Synthetic first decision"), "{home}");
    assert!(
        home.contains("Synthetic second decision") && home.contains("Synthetic third decision")
    );
    shell.key(press(Key::Char('2')), now(1));
    let Some(Detail::Need(key)) = shell.app.detail.clone() else {
        panic!("item 2 opens");
    };
    let binding = shell.app.binding(&key).unwrap();
    assert_eq!(binding.question_id.as_deref(), Some("Q3"));
    assert_eq!(binding.proposal, ["Synthetic third decision"]);
    assert_eq!(binding.recommendation, ["Synthetic third choice"]);
    assert_eq!(binding.comment_id, 7001);
    assert_eq!(binding.fingerprint, "b".repeat(64));
    let detail = text(&shell.app, now(1), 120, 40);
    assert!(detail.contains("Synthetic third context"), "{detail}");
    assert!(!detail.contains("Synthetic second"), "{detail}");
}

struct LongAction;
impl Action for LongAction {
    fn id(&self) -> ActionId {
        ActionId::Send
    }
    fn update(&mut self, _: ActionInput, _: &ActionContext) -> ActionResult {
        ActionResult {
            view: ActionView {
                title: "Synthetic message".into(),
                target: "thr_syn_0301".into(),
                fields: (0..5)
                    .map(|n| {
                        (
                            format!("f{n}"),
                            format!("field{n}"),
                            "synthetic value".into(),
                            true,
                        )
                    })
                    .collect(),
                effects: (0..7)
                    .map(|n| format!("Synthetic effect {n}: inspect before confirmation"))
                    .collect(),
                status: "ready".into(),
                outcome: Some("SYNTHETIC-OUTCOME".into()),
                ..ActionView::default()
            },
            request: None,
        }
    }
}

fn long_action_app() -> App {
    let mut app = App::with_actions(
        settings(1, Some("openwiz.example")),
        vec![(
            ActionId::Send,
            Some(Box::new(LongAction) as Box<dyn Action>),
        )],
    );
    app.detail = Some(Detail::Session("thr_syn_0301".into()));
    app.key(press(Key::Char('m')), now(0));
    assert_eq!(app.open_action(), Some(ActionId::Send));
    app
}

/// R2: the action pane scrolls with non-editing keys, every effect and the
/// outcome are reachable, the target stays shown, and a pane too small to
/// show the target cannot confirm.
#[test]
fn r2_the_action_pane_scrolls_and_never_confirms_an_unreadable_target() {
    let mut app = long_action_app();
    let mut seen = String::new();
    for _ in 0..12 {
        let screen = text(&app, now(1), 80, 24);
        assert!(screen.contains("to            thr_syn_0301"), "{screen}");
        seen.push_str(&screen);
        app.key(press(Key::PageDown), now(1));
    }
    for n in 0..7 {
        assert!(
            seen.contains(&format!("Synthetic effect {n}")),
            "effect {n}"
        );
    }
    assert!(seen.contains("SYNTHETIC-OUTCOME"));
    assert_eq!(
        app.action_views[&ActionId::Send].fields[0].2,
        "synthetic value",
        "no edit"
    );
    // Too small to show the exact target: confirming is refused.
    let count = Arc::new(AtomicUsize::new(0));
    let mut app = App::with_actions(
        settings(1, Some("openwiz.example")),
        vec![(
            ActionId::Send,
            Some(Box::new(Counting(count.clone())) as Box<dyn Action>),
        )],
    );
    app.detail = Some(Detail::Session("thr_syn_0301".into()));
    app.key(press(Key::Char('m')), now(0));
    let _ = text(&app, now(0), 20, 5);
    app.key(press(Key::Ctrl('s')), now(1));
    assert_eq!(count.load(Ordering::SeqCst), 0);
    assert!(
        app.notice.as_deref().unwrap().contains("too small"),
        "{:?}",
        app.notice
    );
    let _ = text(&app, now(2), 80, 24);
    app.key(press(Key::Ctrl('s')), now(3));
    assert_eq!(count.load(Ordering::SeqCst), 1);
}

struct Counting(Arc<AtomicUsize>);
impl Action for Counting {
    fn id(&self) -> ActionId {
        ActionId::Send
    }
    fn update(&mut self, input: ActionInput, _: &ActionContext) -> ActionResult {
        if matches!(input, ActionInput::Confirm { .. }) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
        ActionResult {
            view: ActionView {
                target: "thr_syn_0301".into(),
                ..ActionView::default()
            },
            request: None,
        }
    }
}

/// R3: freshness is the source's: an oldest decision source already 69 s old
/// is stale 2 s later, so "Nothing needs you" is withdrawn.
#[test]
fn r3_source_age_not_receipt_decides_staleness() {
    let server = FixtureServer::home();
    let mut decisions = body("decisions-empty.json");
    decisions["freshness"]["snapshot_at"]["known"] = json!(T - 69_000);
    server.route(
        "/api/v1/decisions",
        Reply::ok(decisions.to_string().into_bytes()),
    );
    server.route("/api/v1/fleets", Reply::ok(fixture("fleets-empty.json")));
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    assert!(openwiz_terminal::render::nothing_needs_you(
        &shell.app,
        now(0)
    ));
    assert!(!openwiz_terminal::render::nothing_needs_you(
        &shell.app,
        now(2_001)
    ));
    let screen = text(&shell.app, now(2_001), 120, 40);
    assert!(
        screen.contains("decisions: complete · read 1m ago · stale"),
        "{screen}"
    );
}

/// R4: Home scrolls to its lower parts at a very small size, and every
/// Needs you item, past nine too, can be selected and opened.
#[test]
fn r4_home_scrolls_and_selects_every_item() {
    let server = FixtureServer::home();
    let mut decisions = body("decisions.json");
    let item = decisions["items"][0].clone();
    let items: Vec<Value> = (0..12)
        .map(|n| {
            let mut i = item.clone();
            i["comment_id"] = json!(8000 + n);
            i["request"]["fingerprint"] = json!(format!("{n:064x}"));
            i
        })
        .collect();
    decisions["items"] = Value::Array(items);
    server.route(
        "/api/v1/decisions",
        Reply::ok(decisions.to_string().into_bytes()),
    );
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    let mut reached = false;
    for _ in 0..40 {
        shell.key(press(Key::PageDown), now(1));
        if text(&shell.app, now(1), 36, 10).contains("Synthetic active") {
            reached = true;
            break;
        }
    }
    assert!(reached, "Home's sessions are reachable");
    // The first Down selects item 1; eleven more reach item 12.
    for _ in 0..12 {
        shell.key(press(Key::Down), now(2));
        let _ = text(&shell.app, now(2), 36, 10);
    }
    shell.key(press(Key::Enter), now(3));
    assert_eq!(
        shell.app.detail,
        Some(Detail::Need(NeedKey::Decision {
            repository: "synthetic-owner/synthetic-repo".into(),
            comment_id: 8011,
            fingerprint: format!("{:064x}", 11),
            question: None,
        })),
        "the twelfth item opens"
    );
}

/// R5: scrolling counts wrapped rows: a long final output's tail is reachable.
#[test]
fn r5_a_wrapped_detail_tail_is_reachable() {
    let server = FixtureServer::home();
    let mut session = body("session-thr_syn_0301.json");
    session["data"]["final_output"]["known"]["text"] =
        json!(format!("{} SYNTHETIC-END", "x".repeat(5000)));
    server.route(
        "/api/v1/sessions/thr_syn_0301",
        Reply::ok(session.to_string().into_bytes()),
    );
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    for key in [Key::Char('s'), Key::Down, Key::Enter] {
        shell.key(press(key), now(1));
    }
    assert!(shell.settle(now(1), SETTLE));
    let mut reached = false;
    for _ in 0..100 {
        let _ = text(&shell.app, now(1), 80, 24);
        shell.key(press(Key::PageDown), now(1));
        if text(&shell.app, now(1), 80, 24).contains("SYNTHETIC-END") {
            reached = true;
            break;
        }
    }
    assert!(reached);
}

/// Each update's (sources age, target age), when decisions were read.
type Ages = Option<(Option<u64>, Option<u64>)>;
struct Observe(Arc<Mutex<Vec<Ages>>>);
impl Action for Observe {
    fn id(&self) -> ActionId {
        ActionId::Answer
    }
    fn update(&mut self, _: ActionInput, context: &ActionContext) -> ActionResult {
        self.0.lock().unwrap().push(
            context
                .decision_ages
                .map(|a| (a.sources_age_ms, a.target_age_ms)),
        );
        ActionResult {
            view: ActionView::default(),
            request: None,
        }
    }
}

/// R6: the target's own verification time is kept and its current age is
/// given to an action, apart from the sources' age.
#[test]
fn r6_the_target_verification_age_reaches_the_action() {
    let server = FixtureServer::home();
    let mut decisions = body("decisions.json");
    decisions["orchestrator"]["freshness"]["snapshot_at"]["known"] = json!(T - 60_000);
    server.route(
        "/api/v1/decisions",
        Reply::ok(decisions.to_string().into_bytes()),
    );
    let seen = Arc::new(Mutex::new(Vec::new()));
    let app = App::with_actions(
        settings(server.port, None),
        vec![(
            ActionId::Answer,
            Some(Box::new(Observe(seen.clone())) as Box<dyn Action>),
        )],
    );
    let mut shell = openwiz_terminal::run::Shell::new(app, client(server.port, None));
    assert!(shell.settle(now(0), SETTLE));
    shell.key(press(Key::Char('1')), now(5_000));
    let Some(Detail::Need(key)) = shell.app.detail.clone() else {
        panic!()
    };
    assert_eq!(
        shell.app.binding(&key).unwrap().target_snapshot_at,
        openwiz_terminal::model::Fact::Known(T - 60_000)
    );
    shell.key(press(Key::Char('a')), now(5_000));
    assert_eq!(seen.lock().unwrap()[0], Some((Some(6_000), Some(65_000))));
}

/// R7: a report is the route's complete existing shape: real bodies pass,
/// schema-only or malformed ones never become reports.
#[test]
fn r7_reports_are_validated_against_their_full_contract_shape() {
    let server = FixtureServer::start();
    let host = Some("openwiz.example");
    let send = SendInput {
        target: "thr_syn_0001".into(),
        text: "Synthetic".into(),
        mode: Mode::Queue,
        op_id: "op-send".into(),
        resume_paused_queue: false,
        accept_possible_duplicate: false,
    };
    let new = NewThreadInput {
        project_id: "prj_syn_0001".into(),
        harness: "codex".into(),
        model: "syn-codex-model-01".into(),
        effort: "high".into(),
        prompt: "Synthetic".into(),
        op_id: "op-create".into(),
    };
    let cases = [
        (
            ActionRequest::SendPreview {
                target: "thr_syn_0001".into(),
                mode: Mode::Queue,
            },
            "send-preview.json",
        ),
        (ActionRequest::Send(send.clone()), "send-accepted.json"),
        (ActionRequest::Send(send), "send-failed.json"),
        (
            ActionRequest::Lookup {
                target: "thr_syn_0001".into(),
                op_id: "op-send".into(),
            },
            "send-lookup.json",
        ),
        (
            ActionRequest::Lookup {
                target: "thr_syn_0001".into(),
                op_id: "op-send".into(),
            },
            "send-lookup-none.json",
        ),
        (ActionRequest::Options, "cloud-options.json"),
        (ActionRequest::NewPreview(new.clone()), "new-preview.json"),
        (ActionRequest::Create(new), "new-created.json"),
        (
            ActionRequest::Status {
                op_id: "op-create".into(),
            },
            "new-status.json",
        ),
    ];
    for (request, file) in &cases {
        let path = request.route().1;
        let real = std::fs::read(
            std::path::Path::new(super::support::ROOT)
                .join("tests/terminal/actions")
                .join(file),
        )
        .unwrap();
        server.route(&path, Reply::ok(real.clone()));
        let result = execute(&client(server.port, host), request);
        assert!(
            matches!(result, TransportResult::Report { .. }),
            "{file}: {result:?}"
        );
        // The same schema with a field removed, a wrong type, or a made-up
        // variant is never a report.
        let mut doc: Value = serde_json::from_slice(&real).unwrap();
        let first = doc
            .as_object()
            .unwrap()
            .keys()
            .find(|k| *k != "schema")
            .unwrap()
            .clone();
        for broken in [
            {
                let mut d = doc.clone();
                d.as_object_mut().unwrap().remove(&first);
                d
            },
            {
                let mut d = doc.clone();
                d[&first] = json!(false);
                d
            },
            {
                doc["invented"] = json!("synthetic");
                doc.clone()
            },
        ] {
            server.route(&path, Reply::ok(broken.to_string().into_bytes()));
            let result = execute(&client(server.port, host), request);
            assert!(
                !matches!(result, TransportResult::Report { .. }),
                "{file}: {broken}"
            );
            if request.is_dispatch() {
                assert!(
                    matches!(result, TransportResult::UnknownAfterDispatch { .. }),
                    "{file}"
                );
            }
        }
    }
    server.route(
        "/api/v1/cloud-options",
        Reply::ok(br#"{"schema":"openwiz.cloud-options.v1","projects":false}"#.to_vec()),
    );
    assert!(!matches!(
        execute(&client(server.port, host), &ActionRequest::Options),
        TransportResult::Report { .. }
    ));
}

/// R8: a write's ambiguous server failure is uncertain, never a refusal;
/// only the contract's nothing-happened failures are refusals.
#[test]
fn r8_ambiguous_write_failures_are_uncertain() {
    let server = FixtureServer::start();
    let send = ActionRequest::Send(SendInput {
        target: "thr_syn_0301".into(),
        text: "Synthetic message".into(),
        mode: Mode::Queue,
        op_id: "op-syn-test".into(),
        resume_paused_queue: false,
        accept_possible_duplicate: false,
    });
    let path = "/api/v1/sessions/thr_syn_0301/messages";
    for (status, kind, uncertain) in [
        (500, "internal", true),
        (502, "read_failed", true),
        (504, "deadline", true),
        (500, "record_unavailable", false),
        (500, "store_unavailable", false),
        (503, "busy", false),
        (421, "misdirected", false),
        (400, "invalid_request", false),
    ] {
        server.route(path, Reply::status(status, kind, "synthetic"));
        let result = execute(&client(server.port, Some("openwiz.example")), &send);
        assert_eq!(
            matches!(result, TransportResult::UnknownAfterDispatch { .. }),
            uncertain,
            "{status} {kind}: {result:?}"
        );
    }
}

/// R9: a reported repeat is always a repeat, and without release reporting a
/// second confirmation needs a distinct press (another key in between); with
/// it, a release.
#[test]
fn r9_held_keys_never_make_a_second_confirmation() {
    use openwiz_terminal::ratatui::crossterm::event::{
        KeyCode, KeyEvent, KeyEventKind, KeyModifiers,
    };
    use openwiz_terminal::run::key_press;
    let event = |kind| KeyEvent::new_with_kind(KeyCode::Char('s'), KeyModifiers::CONTROL, kind);
    let repeat = key_press(&event(KeyEventKind::Repeat), false).unwrap();
    assert!(repeat.repeat, "a reported repeat stays a repeat");
    for release_reported in [false, true] {
        let count = Arc::new(AtomicUsize::new(0));
        let mut app = App::with_actions(
            settings(1, Some("openwiz.example")),
            vec![(
                ActionId::Send,
                Some(Box::new(Counting(count.clone())) as Box<dyn Action>),
            )],
        );
        app.key_release_reported = release_reported;
        app.detail = Some(Detail::Session("thr_syn_0301".into()));
        app.key(press(Key::Char('m')), now(0));
        let _ = text(&app, now(0), 80, 24);
        let feed = |app: &mut App, kind, at| {
            if let Some(k) = key_press(&event(kind), release_reported) {
                app.key(k, now(at));
            }
        };
        feed(&mut app, KeyEventKind::Press, 1_000);
        feed(&mut app, KeyEventKind::Repeat, 1_500);
        feed(&mut app, KeyEventKind::Press, 2_001);
        assert_eq!(
            count.load(Ordering::SeqCst),
            1,
            "release reported: {release_reported}"
        );
        if release_reported {
            feed(&mut app, KeyEventKind::Release, 2_100);
            feed(&mut app, KeyEventKind::Press, 2_200);
        } else {
            // R9 re-check: another key (a pasted Tab while Ctrl-S is held)
            // no longer re-arms Ctrl-S; the next confirmation is Ctrl-Y.
            app.key(press(Key::Tab), now(2_100));
            feed(&mut app, KeyEventKind::Press, 2_150);
            assert_eq!(
                count.load(Ordering::SeqCst),
                1,
                "a pasted Tab never re-arms"
            );
            app.key(press(Key::Ctrl('y')), now(2_200));
        }
        assert_eq!(
            count.load(Ordering::SeqCst),
            2,
            "release reported: {release_reported}"
        );
    }
}

/// R9 re-check: without release reporting, confirmations alternate Ctrl-S,
/// Ctrl-Y, Ctrl-S…, which one held key can never produce; pasted text is a
/// paste (bracketed paste is on), which edits the focused field and never
/// confirms or re-arms.
#[test]
fn r9b_legacy_confirmations_alternate_keys_and_a_paste_never_confirms() {
    let count = Arc::new(AtomicUsize::new(0));
    let mut app = App::with_actions(
        settings(1, Some("openwiz.example")),
        vec![(
            ActionId::Send,
            Some(Box::new(Counting(count.clone())) as Box<dyn Action>),
        )],
    );
    app.detail = Some(Detail::Session("thr_syn_0301".into()));
    app.key(press(Key::Char('m')), now(0));
    let _ = text(&app, now(0), 80, 24);
    // Held Ctrl-S with a paste in the middle: bytes 13 09 13 as a legacy
    // terminal without bracketed paste would deliver them, and as a paste.
    app.key(press(Key::Ctrl('s')), now(1));
    app.key(press(Key::Tab), now(2));
    app.key(press(Key::Ctrl('s')), now(3));
    app.paste("\t", now(4));
    app.key(press(Key::Ctrl('s')), now(5));
    assert_eq!(count.load(Ordering::SeqCst), 1);
    app.paste("\x19", now(6));
    assert_eq!(
        count.load(Ordering::SeqCst),
        1,
        "a pasted Ctrl-Y is text, not a key"
    );
    app.key(press(Key::Ctrl('y')), now(7));
    assert_eq!(count.load(Ordering::SeqCst), 2);
    app.key(press(Key::Ctrl('y')), now(8));
    assert_eq!(
        count.load(Ordering::SeqCst),
        2,
        "a held Ctrl-Y is one confirmation"
    );
    app.key(press(Key::Ctrl('s')), now(9));
    assert_eq!(count.load(Ordering::SeqCst), 3);
}

/// R11: a selected row taller than the view keeps one anchor (its top):
/// identical idle draws show identical screens, in lists and the pane.
#[test]
fn r11_identical_draws_are_stable_when_the_selected_row_is_taller_than_the_view() {
    let server = FixtureServer::home();
    let mut inventory = body("inventory.json");
    inventory["data"]["sessions"][0]["title"]["known"] =
        json!(format!("Synthetic {}", "t".repeat(190)));
    inventory["data"]["sessions"][0]["group"]["name"]["known"] =
        json!(format!("Synthetic {}", "p".repeat(190)));
    server.route(
        "/api/v1/inventory",
        Reply::ok(inventory.to_string().into_bytes()),
    );
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    shell.key(press(Key::Char('s')), now(1));
    shell.key(press(Key::Down), now(1));
    let _ = text(&shell.app, now(1), 80, 24);
    let screens: Vec<String> = (0..3).map(|_| text(&shell.app, now(1), 36, 10)).collect();
    assert_eq!(screens[0], screens[1]);
    assert_eq!(screens[1], screens[2]);
    assert!(
        screens[0].contains("◉ Synthetic"),
        "the selected row's top: {}",
        screens[0]
    );
    // The pane, with a field taller than its body.
    struct Tall;
    impl Action for Tall {
        fn id(&self) -> ActionId {
            ActionId::Send
        }
        fn update(&mut self, _: ActionInput, _: &ActionContext) -> ActionResult {
            ActionResult {
                view: ActionView {
                    target: "thr_syn_0301".into(),
                    fields: vec![(
                        "text".into(),
                        "text".into(),
                        format!("Synthetic {}", "x".repeat(2000)),
                        true,
                    )],
                    ..ActionView::default()
                },
                request: None,
            }
        }
    }
    let mut app = App::with_actions(
        settings(1, None),
        vec![(ActionId::Send, Some(Box::new(Tall) as Box<dyn Action>))],
    );
    app.detail = Some(Detail::Session("thr_syn_0301".into()));
    app.key(press(Key::Char('m')), now(0));
    let screens: Vec<String> = (0..3).map(|_| text(&app, now(1), 80, 24)).collect();
    assert_eq!(screens[0], screens[1]);
    assert_eq!(screens[1], screens[2]);
    assert!(
        screens[0].contains("text          Synthetic"),
        "{}",
        screens[0]
    );
}

/// R5 re-check: a large supported page (200 decision records with long
/// headlines, far more wrapped rows than u16 holds) neither overflows nor
/// hides its later items.
#[test]
fn r5b_a_large_page_selects_and_shows_its_last_item() {
    let mut decisions = body("decisions.json");
    let item = decisions["items"][0].clone();
    decisions["items"] = Value::Array(
        (0..200)
            .map(|n| {
                let mut i = item.clone();
                i["comment_id"] = json!(9000 + n);
                i["subject"]["number"] = json!(5000 + n);
                i["request"]["spec"] = json!(5000 + n);
                i["request"]["id"] = json!(format!("synthetic-spec-{n}"));
                i["request"]["fingerprint"] = json!(format!("{n:064x}"));
                i["request"]["headline"] =
                    json!(format!("Synthetic headline {n} {}", "h".repeat(20_000)));
                i
            })
            .collect(),
    );
    let mut app = App::new(settings(1, None));
    app.decisions = Some(openwiz_terminal::app::Good {
        data: openwiz_terminal::model::decisions(&decisions).unwrap(),
        received_mono: 0,
        received_wall: T,
        generation: 1,
    });
    for _ in 0..200 {
        app.key(press(Key::Down), now(1));
    }
    let screen = text(&app, now(1), 36, 10);
    assert!(
        screen.contains("#5199"),
        "the 200th item is in view: {screen}"
    );
    assert!(
        app.view_offset.get() > usize::from(u16::MAX),
        "past u16 rows"
    );
    // Page keys between draws add up; the end is reachable.
    for _ in 0..200 {
        app.key(press(Key::PageDown), now(2));
    }
    let _ = text(&app, now(2), 36, 10);
    assert_eq!(app.view_offset.get(), app.view_max.get());
    assert!(
        app.view_max.get() > usize::from(u16::MAX),
        "the page is larger than u16 rows"
    );
    assert!(
        text(&app, now(2), 36, 10).contains("Sessions"),
        "its end is reachable"
    );
}

/// R7 re-check: the contracts' string patterns are enforced too, and a
/// write's malformed reply stays uncertain.
#[test]
fn r7b_report_patterns_are_enforced() {
    let real: Value = serde_json::from_slice(
        &std::fs::read(
            std::path::Path::new(super::support::ROOT)
                .join("tests/terminal/actions/new-created.json"),
        )
        .unwrap(),
    )
    .unwrap();
    assert_eq!(
        openwiz_terminal::schema::validate_report("openwiz.new-thread.v1", &real),
        Ok(())
    );
    let server = FixtureServer::start();
    let new = NewThreadInput {
        project_id: "prj_syn_0001".into(),
        harness: "codex".into(),
        model: "syn-codex-model-01".into(),
        effort: "high".into(),
        prompt: "Synthetic".into(),
        op_id: "op-create".into(),
    };
    for (pointer, bad) in [
        ("/request_id", json!("/".repeat(44))),
        ("/op_id", json!("bad/op")),
        ("/text_sha256", json!("g".repeat(64))),
        ("/attachments_digest", json!("g".repeat(64))),
        ("/requested/model", json!("bad model")),
    ] {
        let mut doc = real.clone();
        *doc.pointer_mut(pointer).unwrap() = bad;
        assert!(
            openwiz_terminal::schema::validate_report("openwiz.new-thread.v1", &doc).is_err(),
            "{pointer}"
        );
        server.route(
            "/api/v1/projects/prj_syn_0001/threads",
            Reply::ok(doc.to_string().into_bytes()),
        );
        let result = execute(
            &client(server.port, Some("openwiz.example")),
            &ActionRequest::Create(new.clone()),
        );
        assert!(
            matches!(result, TransportResult::UnknownAfterDispatch { .. }),
            "{pointer}: {result:?}"
        );
    }
}

/// Pre-handback audit A3: a decisions body that breaks its contract (a
/// confirmation without its headline, or with the wrong types) is an error,
/// never a shown proposal.
#[test]
fn a3_decisions_that_break_their_contract_are_errors() {
    let good = body("decisions.json");
    for (name, change) in [
        ("missing headline", json!(null)),
        ("headline as a list", json!(["Synthetic headline"])),
    ] {
        let mut d = good.clone();
        let request = &mut d["items"][0]["request"];
        if change.is_null() {
            request.as_object_mut().unwrap().remove("headline");
        } else {
            request["headline"] = change;
        }
        let server = FixtureServer::home();
        server.route("/api/v1/decisions", Reply::ok(d.to_string().into_bytes()));
        let mut shell = shell(&server);
        assert!(shell.settle(now(0), SETTLE));
        assert!(shell.app.decisions.is_none(), "{name}");
        let mut d = good.clone();
        d["items"][0]["request"]["summary"] = json!("Synthetic summary as a string");
        server.route("/api/v1/decisions", Reply::ok(d.to_string().into_bytes()));
        let mut shell = super::support::shell(&server);
        assert!(shell.settle(now(0), SETTLE));
        assert!(shell.app.decisions.is_none(), "summary as a string");
    }
}

/// Pre-handback audit A4: each part's gaps are shown, not only counted.
#[test]
fn a4_gap_details_are_shown() {
    let server = FixtureServer::home();
    server.route(
        "/api/v1/decisions",
        Reply::ok(fixture("decisions-partial.json")),
    );
    server.route(
        "/api/v1/inventory",
        Reply::ok(fixture("inventory-partial.json")),
    );
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    let home = text(&shell.app, now(0), 160, 60);
    assert!(
        home.contains("gap timed_out: decision source read timed out"),
        "{home}"
    );
    assert!(
        home.contains("gap command_failed thr_syn_0309: thread show exited 1"),
        "{home}"
    );
    shell.key(press(Key::Char('s')), now(1));
    let sessions = text(&shell.app, now(1), 160, 40);
    assert!(
        sessions.contains("gap command_failed thr_syn_0309"),
        "{sessions}"
    );
}

/// R12: a pane with no width shows nothing, so it can never confirm.
#[test]
fn r12_a_zero_width_pane_never_confirms() {
    let count = Arc::new(AtomicUsize::new(0));
    let mut app = App::with_actions(
        settings(1, Some("openwiz.example")),
        vec![(
            ActionId::Send,
            Some(Box::new(Counting(count.clone())) as Box<dyn Action>),
        )],
    );
    app.detail = Some(Detail::Session("thr_syn_0301".into()));
    app.key(press(Key::Char('m')), now(0));
    let _ = text(&app, now(0), 0, 24);
    app.key(press(Key::Ctrl('s')), now(1));
    assert_eq!(count.load(Ordering::SeqCst), 0);
    assert!(app.notice.as_deref().unwrap().contains("too small"));
    // Resized back: confirmable again.
    let _ = text(&app, now(2), 80, 24);
    app.key(press(Key::Ctrl('s')), now(3));
    assert_eq!(count.load(Ordering::SeqCst), 1);
}

/// R13: a long valid decision summary is readable to its end: very long
/// lines are drawn in pieces, never cut; the binding keeps every byte.
#[test]
fn r13_a_long_decision_summary_is_readable_to_its_end() {
    let server = FixtureServer::home();
    let mut decisions = body("decisions.json");
    let long = format!("Synthetic {} SYNTHETIC-TAIL", "s".repeat(20_000));
    decisions["items"][0]["request"]["summary"] = json!([long.clone()]);
    server.route(
        "/api/v1/decisions",
        Reply::ok(decisions.to_string().into_bytes()),
    );
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    shell.key(press(Key::Char('1')), now(1));
    let Some(Detail::Need(key)) = shell.app.detail.clone() else {
        panic!()
    };
    assert!(shell.app.binding(&key).unwrap().proposal.contains(&long));
    let mut seen = false;
    for _ in 0..200 {
        let screen = text(&shell.app, now(1), 80, 24);
        if screen.contains("SYNTHETIC-TAIL") {
            seen = true;
            break;
        }
        assert!(!screen.contains("not shown"), "nothing is cut");
        for _ in 0..5 {
            shell.key(press(Key::PageDown), now(1));
        }
    }
    assert!(seen, "the summary's tail is reachable");
}

/// R13 re-check: pieces split at grapheme boundaries, so a combining mark
/// at the boundary is never detached and dropped (with adjacent controls).
#[test]
fn r13b_a_combining_mark_at_a_piece_boundary_stays_visible() {
    for padding in [16_380, 16_381, 16_382] {
        let server = FixtureServer::home();
        let mut decisions = body("decisions.json");
        let long = format!("{}e\u{0301}SYNTHETIC-TAIL", "s".repeat(padding));
        decisions["items"][0]["request"]["summary"] = json!([long.clone()]);
        server.route(
            "/api/v1/decisions",
            Reply::ok(decisions.to_string().into_bytes()),
        );
        let mut shell = shell(&server);
        assert!(shell.settle(now(0), SETTLE));
        shell.key(press(Key::Char('1')), now(1));
        let mut accent = false;
        let mut tail = false;
        for _ in 0..200 {
            let mut terminal = openwiz_terminal::ratatui::Terminal::new(
                openwiz_terminal::ratatui::backend::TestBackend::new(80, 24),
            )
            .unwrap();
            terminal
                .draw(|f| {
                    openwiz_terminal::render::draw(
                        f,
                        &shell.app,
                        now(1),
                        &openwiz_terminal::render::Theme::TRUE_UNICODE,
                    )
                })
                .unwrap();
            let buffer = terminal.backend().buffer();
            accent |= buffer.content.iter().any(|c| c.symbol() == "e\u{0301}");
            tail |= super::render::rows(buffer)
                .join("\n")
                .contains("SYNTHETIC-TAIL");
            if tail && accent {
                break;
            }
            shell.key(press(Key::PageDown), now(1));
        }
        assert!(tail, "padding {padding}: the tail is reachable");
        assert!(accent, "padding {padding}: the combining accent is drawn");
    }
}
