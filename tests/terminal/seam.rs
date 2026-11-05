//! The shared action seam the later tickets implement against: a fixture
//! action, registered in place of a module, proves the shell's rules. Only a
//! distinct confirmation may yield a write; one attempt is locked once
//! dispatched; refresh and navigation deliver snapshots and never replace a
//! draft or submit.

use std::sync::{Arc, Mutex};

use openwiz_terminal::actions::{
    Action, ActionContext, ActionId, ActionInput, ActionRequest, ActionResult, ActionSeed,
    ActionView, Mode, SendInput, TransportResult,
};
use openwiz_terminal::app::{App, Key, KeyPress};
use openwiz_terminal::run::Shell;

use super::render::text;
use super::support::{FixtureServer, Reply, SETTLE, client, now, settings};

const HOST: &str = "openwiz.example";
const MESSAGES: &str = "/api/v1/sessions/thr_syn_0301/messages";

/// Records its inputs; asks for a write on whatever input `rogue` names, and
/// on every confirmation.
struct Fixture {
    seen: Arc<Mutex<Vec<ActionInput>>>,
    draft: String,
    target: String,
    rogue: Option<fn(&ActionInput) -> bool>,
}

impl Action for Fixture {
    fn id(&self) -> ActionId {
        ActionId::Send
    }

    fn update(&mut self, input: ActionInput, _context: &ActionContext) -> ActionResult {
        self.seen.lock().unwrap().push(input.clone());
        let rogue = self.rogue.is_some_and(|r| r(&input));
        match &input {
            ActionInput::Open(ActionSeed::Send { session_id }) => self.target = session_id.clone(),
            ActionInput::Edit { field, value } if field == "text" => self.draft = value.clone(),
            _ => {}
        }
        let send = ActionRequest::Send(SendInput {
            target: self.target.clone(),
            text: self.draft.clone(),
            mode: Mode::Queue,
            op_id: "op-syn-t3-seam".into(),
            resume_paused_queue: false,
            accept_possible_duplicate: false,
        });
        let request = match input {
            ActionInput::Confirm { .. } => Some(send),
            ActionInput::Preview => Some(ActionRequest::SendPreview {
                target: self.target.clone(),
                mode: Mode::Queue,
            }),
            _ if rogue => Some(send),
            _ => None,
        };
        ActionResult {
            view: ActionView {
                title: "Fixture message".into(),
                target: self.target.clone(),
                fields: vec![("text".into(), "text".into(), self.draft.clone(), true)],
                status: "editing".into(),
                ..ActionView::default()
            },
            request,
        }
    }
}

fn fixture_shell(
    server: &FixtureServer,
    rogue: Option<fn(&ActionInput) -> bool>,
) -> (Shell, Arc<Mutex<Vec<ActionInput>>>) {
    let seen = Arc::new(Mutex::new(Vec::new()));
    let action = Fixture {
        seen: Arc::clone(&seen),
        draft: String::new(),
        target: String::new(),
        rogue,
    };
    let app = App::with_actions(
        settings(server.port, Some(HOST)),
        vec![
            (ActionId::Answer, None),
            (ActionId::Send, Some(Box::new(action) as Box<dyn Action>)),
            (ActionId::NewThread, None),
        ],
    );
    let mut shell = Shell::new(app, client(server.port, Some(HOST)));
    assert!(shell.settle(now(0), SETTLE));
    (shell, seen)
}

fn open_compose(shell: &mut Shell) {
    for key in [Key::Char('s'), Key::Down, Key::Enter] {
        shell.key(KeyPress::press(key), now(1));
    }
    assert!(shell.settle(now(1), SETTLE));
    shell.key(KeyPress::press(Key::Char('m')), now(2));
    assert_eq!(shell.app.open_action(), Some(ActionId::Send));
    // As in the app, a draw shows the target before any key can confirm.
    let _ = text(&shell.app, now(2), 120, 40);
}

#[test]
fn the_registry_lists_every_action_module_in_order() {
    let registry = openwiz_terminal::actions::registry();
    assert_eq!(
        registry.iter().map(|(id, _)| *id).collect::<Vec<_>>(),
        ActionId::ALL
    );
    // Which are available is each module's own (its test file, owned by
    // T4-T6); the shell's seam rules hold either way.
    assert_eq!(
        ActionId::ALL.map(ActionId::capability),
        ["answer", "send", "new_thread"]
    );
}

#[test]
fn only_a_distinct_confirmation_dispatches_and_an_attempt_stays_locked() {
    let server = FixtureServer::home();
    server.route(
        MESSAGES,
        Reply::ok(
            std::fs::read(
                std::path::Path::new(super::support::ROOT)
                    .join("tests/terminal/actions/send-accepted.json"),
            )
            .unwrap(),
        ),
    );
    let (mut shell, seen) = fixture_shell(&server, None);
    open_compose(&mut shell);
    for c in "hi ".chars() {
        shell.key(KeyPress::press(Key::Char(c)), now(3));
    }
    // Navigation and refresh while composing: reads only, draft intact.
    shell.app.refresh(now(4));
    assert!(shell.settle(now(4), SETTLE));
    assert!(server.writes().is_empty());
    assert!(
        seen.lock()
            .unwrap()
            .iter()
            .any(|i| matches!(i, ActionInput::Snapshot { .. })),
        "refreshed snapshots reach the open action"
    );
    assert_eq!(shell.app.action_views[&ActionId::Send].fields[0].2, "hi ");
    // A held (auto-repeat) key never confirms.
    shell.key(
        KeyPress {
            key: Key::Ctrl('s'),
            repeat: true,
            release: false,
        },
        now(5),
    );
    assert!(shell.settle(now(5), SETTLE));
    assert!(server.writes().is_empty());
    // A distinct press: exactly one write, recorded and dispatched first.
    shell.key(KeyPress::press(Key::Ctrl('s')), now(2_000));
    assert!(shell.settle(now(2_000), SETTLE));
    assert_eq!(server.writes().len(), 1);
    let attempt = shell.app.attempts.last().unwrap();
    assert!(attempt.dispatched && attempt.locked());
    assert!(matches!(
        attempt.outcome,
        Some(TransportResult::Report { .. })
    ));
    // The next distinct confirmation (Ctrl-Y, without release reporting)
    // while that attempt stands: refused by the lock, no write.
    shell.key(KeyPress::press(Key::Ctrl('y')), now(4_000));
    assert!(shell.settle(now(4_000), SETTLE));
    assert_eq!(server.writes().len(), 1);
    assert!(
        shell
            .app
            .notice
            .as_deref()
            .unwrap()
            .contains("Nothing was sent")
    );
    // Without release reporting, two presses with nothing in between are
    // one held key: one confirmation, however long apart.
    let (mut shell, _) = fixture_shell(&server, None);
    open_compose(&mut shell);
    shell.key(KeyPress::press(Key::Ctrl('s')), now(10_000));
    shell.key(KeyPress::press(Key::Ctrl('s')), now(20_000));
    assert!(shell.settle(now(20_000), SETTLE));
    assert_eq!(
        server.writes().len(),
        2,
        "only the first of two quick presses"
    );
    // The body is the draft's exact bytes.
    let body: serde_json::Value = serde_json::from_slice(&server.writes()[0].body).unwrap();
    assert_eq!(body["text"], "hi ");
}

#[test]
fn opening_editing_snapshots_and_cancel_can_never_yield_a_write() {
    let server = FixtureServer::home();
    let (mut shell, _) = fixture_shell(
        &server,
        Some(|i| {
            matches!(
                i,
                ActionInput::Open(_)
                    | ActionInput::Edit { .. }
                    | ActionInput::Snapshot { .. }
                    | ActionInput::Cancel
                    | ActionInput::RefreshStatus
            )
        }),
    );
    open_compose(&mut shell);
    shell.key(KeyPress::press(Key::Char('x')), now(3));
    shell.app.refresh(now(4));
    assert!(shell.settle(now(4), SETTLE));
    shell.key(KeyPress::press(Key::Ctrl('r')), now(5));
    shell.key(KeyPress::press(Key::Esc), now(6));
    assert!(shell.settle(now(6), SETTLE));
    assert!(server.writes().is_empty(), "{:?}", server.writes());
    assert!(shell.app.attempts.is_empty());
    assert!(
        shell
            .app
            .notice
            .as_deref()
            .unwrap()
            .contains("refused a write")
    );
}

#[test]
fn previews_are_reads_through_the_action_lane() {
    let server = FixtureServer::home();
    let (mut shell, seen) = fixture_shell(&server, None);
    open_compose(&mut shell);
    shell.key(KeyPress::press(Key::Ctrl('p')), now(3));
    shell.key(KeyPress::press(Key::Ctrl('p')), now(3));
    assert!(shell.settle(now(3), SETTLE));
    let previews = server
        .paths()
        .iter()
        .filter(|p| p.ends_with("/preview?mode=queue"))
        .count();
    assert!((1..=2).contains(&previews), "{previews}");
    assert!(server.writes().is_empty());
    assert!(
        seen.lock()
            .unwrap()
            .iter()
            .any(|i| matches!(i, ActionInput::Response { .. }))
    );
}

#[test]
fn without_an_allowed_host_no_write_is_attempted() {
    let server = FixtureServer::home();
    let seen = Arc::new(Mutex::new(Vec::new()));
    let action = Fixture {
        seen,
        draft: "x".into(),
        target: String::new(),
        rogue: None,
    };
    let app = App::with_actions(
        settings(server.port, None),
        vec![(ActionId::Send, Some(Box::new(action) as Box<dyn Action>))],
    );
    let mut shell = Shell::new(app, client(server.port, None));
    assert!(shell.settle(now(0), SETTLE));
    open_compose(&mut shell);
    shell.key(KeyPress::press(Key::Ctrl('s')), now(3_000));
    assert!(shell.settle(now(3_000), SETTLE));
    assert!(server.writes().is_empty());
    assert!(
        shell
            .app
            .notice
            .as_deref()
            .unwrap()
            .contains("no allowed host")
    );
    let screen = text(&shell.app, now(3_000), 120, 40);
    assert!(screen.contains("writes: off (no host)"), "{screen}");
}
