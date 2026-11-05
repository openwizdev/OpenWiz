//! CP5: production terminal events -> screen -> recording HTTP. The old
//! unavailable stub cannot answer; wrong-target/extra-send bugs must fail here.
use openwiz_terminal::actions::ActionId;
use openwiz_terminal::app::{App, Key, KeyPress};
use openwiz_terminal::run::Shell;
use serde_json::Value;

use super::render::text;
use super::support::{FixtureServer, ROOT, Reply, SETTLE, client, now, settings};

const TARGET: &str = "thr_syn_0399";
const MESSAGES: &str = "/api/v1/sessions/thr_syn_0399/messages";

fn reply(name: &str) -> Value {
    serde_json::from_slice(
        &std::fs::read(format!("{ROOT}/tests/terminal/actions/{name}.json")).unwrap(),
    )
    .unwrap()
}
fn server() -> FixtureServer {
    let server = FixtureServer::home();
    let mut preview = reply("send-preview");
    preview["target"]["id"] = TARGET.into();
    server.route(
        &format!("/api/v1/sessions/{TARGET}/preview?mode=queue"),
        Reply::ok(serde_json::to_vec(&preview).unwrap()),
    );
    server
}
fn start(server: &FixtureServer) -> Shell {
    let prior_writes = server.writes().len();
    let mut shell = Shell::new(
        App::new(settings(server.port, Some("openwiz.example"))),
        client(server.port, Some("openwiz.example")),
    );
    assert!(shell.settle(now(0), SETTLE));
    key(&mut shell, Key::Char('1'));
    assert_eq!(
        server.writes().len(),
        prior_writes,
        "number selection is read-only"
    );
    key(&mut shell, Key::Char('a'));
    assert_eq!(shell.app.open_action(), Some(ActionId::Answer));
    shell
}
fn key(shell: &mut Shell, key: Key) {
    shell.key(KeyPress::press(key), now(1));
    assert!(shell.settle(now(1), SETTLE));
}
fn preview(shell: &mut Shell) {
    key(shell, Key::Ctrl('p'));
    let screen = text(&shell.app, now(1), 120, 40);
    assert!(screen.contains(TARGET), "{screen}");
}
#[test]
fn cp5_number_selection_previews_then_confirms_exact_spec_reply_once() {
    let server = server();
    let mut shell = start(&server);
    key(&mut shell, Key::Ctrl('s'));
    assert!(server.writes().is_empty(), "preview is required");
    preview(&mut shell);
    key(&mut shell, Key::Ctrl('y'));
    key(&mut shell, Key::Ctrl('s'));
    assert_eq!(server.writes().len(), 1);
    let write = &server.writes()[0];
    assert_eq!(write.path, MESSAGES);
    let body: Value = serde_json::from_slice(&write.body).unwrap();
    assert_eq!(body["text"], "confirm spec #9001");
    assert_eq!(body["mode"], "queue");
    assert_eq!(write.header("Host"), ["openwiz.example"]);
    assert_eq!(write.header("Origin"), ["https://openwiz.example"]);
    assert_eq!(write.header("Sec-Fetch-Site"), ["same-origin"]);
    assert_eq!(write.header("X-OpenWiz-Send"), ["1"]);
}

fn decisions() -> Value {
    serde_json::from_slice(&super::support::fixture("decisions.json")).unwrap()
}
fn set_decisions(server: &FixtureServer, d: &Value) {
    server.route(
        "/api/v1/decisions",
        Reply::ok(serde_json::to_vec(d).unwrap()),
    );
}
fn confirm(shell: &mut Shell) {
    let _ = text(&shell.app, now(1), 120, 40);
    let c = shell.app.confirm_key();
    key(shell, Key::Ctrl(c));
}
fn refresh(shell: &mut Shell) {
    shell.app.refresh(now(1));
    assert!(shell.settle(now(1), SETTLE));
}
fn own_words(shell: &mut Shell, words: &str) {
    // Confirmations: yes -> own words. Grill questions: yes -> simplify -> own.
    key(shell, Key::Char(' '));
    if shell.app.action_views[&ActionId::Answer].fields[0].2 == "simplify" {
        key(shell, Key::Char(' '));
    }
    key(shell, Key::Tab);
    shell.paste(words, now(1));
    assert!(shell.settle(now(1), SETTLE));
}
fn posted_text(server: &FixtureServer) -> String {
    let writes = server.writes();
    assert_eq!(writes.len(), 1);
    serde_json::from_slice::<Value>(&writes[0].body).unwrap()["text"]
        .as_str()
        .unwrap()
        .to_owned()
}
fn request_kind(d: &mut Value, kind: &str) {
    let r = &mut d["items"][0]["request"];
    r["kind"] = kind.into();
    match kind {
        "grill_round" => {
            for k in ["spec", "summary", "headline", "tickets", "graph"] {
                r.as_object_mut().unwrap().remove(k);
            }
            r["grill_file"] = "docs/grills/synthetic.md".into();
            r["round"] = 1.into();
            r["answered"] = serde_json::json!([]);
            r["questions"] = serde_json::json!([{"id":"G1", "decides":"Synthetic exact question?", "context":"Synthetic retained context.", "recommendation":"Synthetic recommended option A."}]);
            d["items"][0]["subject"]["kind"] = "pull_request".into();
        }
        "grill_confirmation" => {
            for k in ["spec", "headline", "tickets", "graph"] {
                r.as_object_mut().unwrap().remove(k);
            }
            r["grill_file"] = "docs/grills/synthetic.md".into();
            d["items"][0]["subject"]["kind"] = "pull_request".into();
        }
        _ => {}
    }
}

// CP5 owns reply spelling and exact bytes at the HTTP boundary. The stub
// missed every kind; a formatter could later trim or prefix own words.
#[test]
fn cp5_all_supported_reply_kinds_and_exact_own_words() {
    for (kind, simplify, expected) in [
        ("grill_round", false, "G1 yes"),
        ("grill_round", true, "simplify G1"),
        ("grill_confirmation", false, "confirm"),
        ("spec_confirmation", false, "confirm spec #9001"),
        ("plan_approval", false, "approve #9001"),
    ] {
        for own in [false, true] {
            let server = server();
            let mut d = decisions();
            request_kind(&mut d, kind);
            set_decisions(&server, &d);
            let mut shell = start(&server);
            let words = " \tSynthetic own words: — \"yes\"\nsecond line\r\n \t";
            if own {
                own_words(&mut shell, words);
            } else if simplify {
                key(&mut shell, Key::Char(' '));
            }
            preview(&mut shell);
            confirm(&mut shell);
            assert_eq!(
                posted_text(&server),
                if own { words } else { expected },
                "{kind}"
            );
        }
    }
}

// A fingerprint alone does not bind plan wording/risk. Mutate one field at
// a time after preview: no confirmation can redirect the recorded request.
#[test]
fn cp5_refresh_changes_removal_and_reorder_never_redirect() {
    for case in [
        "target",
        "fingerprint",
        "risk",
        "wording",
        "removed",
        "current false",
        "current unknown",
        "partial",
        "target partial",
        "stale",
        "target stale",
        "unknown source age",
        "unknown target age",
        "target absent",
        "target unknown",
    ] {
        let server = server();
        let mut shell = start(&server);
        preview(&mut shell);
        let mut d = decisions();
        match case {
            "target" => d["orchestrator"]["target"]["known"] = "thr_syn_0398".into(),
            "fingerprint" => d["items"][0]["request"]["fingerprint"] = "b".repeat(64).into(),
            "risk" => d["items"][0]["request"]["risk"] = "live".into(),
            "wording" => {
                d["items"][0]["request"]["summary"][0] = "Synthetic changed wording".into()
            }
            "removed" => d["items"] = serde_json::json!([]),
            "current false" => d["items"][0]["current"] = serde_json::json!({"known":false}),
            "current unknown" => {
                d["items"][0]["current"] =
                    serde_json::json!({"unknown":"Synthetic unavailable current wording"})
            }
            "partial" => {
                d["coverage"] = serde_json::json!({"state":"partial","gaps":[{"kind":"malformed","detail":"Synthetic incomplete required source"}]})
            }
            "target partial" => {
                d["orchestrator"]["coverage"] = serde_json::json!({"state":"partial","gaps":[{"kind":"malformed","detail":"Synthetic incomplete target"}]})
            }
            "stale" => d["freshness"]["state"] = "stale".into(),
            "target stale" => d["orchestrator"]["freshness"]["state"] = "stale".into(),
            "unknown source age" => {
                d["freshness"]["state"] = "unknown".into();
                d["freshness"]["snapshot_at"] =
                    serde_json::json!({"unknown":"Synthetic unavailable time"});
            }
            "unknown target age" => {
                d["orchestrator"]["freshness"]["state"] = "unknown".into();
                d["orchestrator"]["freshness"]["snapshot_at"] =
                    serde_json::json!({"unknown":"Synthetic unavailable target time"});
            }
            "target absent" => d["orchestrator"]["target"] = serde_json::json!({"known":null}),
            "target unknown" => {
                d["orchestrator"]["target"] =
                    serde_json::json!({"unknown":"Synthetic unverified target"})
            }
            _ => unreachable!(),
        }
        set_decisions(&server, &d);
        refresh(&mut shell);
        confirm(&mut shell);
        assert!(server.writes().is_empty(), "{case}");
        assert!(
            shell.app.action_views[&ActionId::Answer].reason.is_some(),
            "{case}"
        );
    }
    let server = server();
    let mut d = decisions();
    let mut second = d["items"][0].clone();
    second["comment_id"] = 7002.into();
    second["request"]["id"] = "synthetic-second".into();
    second["request"]["fingerprint"] = "b".repeat(64).into();
    second["subject"]["number"] = 9002.into();
    second["request"]["spec"] = 9002.into();
    d["items"].as_array_mut().unwrap().push(second);
    set_decisions(&server, &d);
    let mut shell = start(&server);
    preview(&mut shell);
    d["items"].as_array_mut().unwrap().reverse();
    set_decisions(&server, &d);
    refresh(&mut shell);
    confirm(&mut shell);
    assert_eq!(posted_text(&server), "confirm spec #9001");
}

#[test]
fn cp5_risk_second_confirmation_and_repeats_cancel_edits() {
    for risk in ["ordinary", "live", "release", "publish", "unknown"] {
        let server = server();
        let mut d = decisions();
        d["items"][0]["request"]["risk"] = risk.into();
        set_decisions(&server, &d);
        let mut shell = start(&server);
        preview(&mut shell);
        shell.key(
            KeyPress {
                key: Key::Ctrl('s'),
                repeat: true,
                release: false,
            },
            now(1),
        );
        assert!(server.writes().is_empty());
        confirm(&mut shell);
        assert_eq!(
            server.writes().len(),
            usize::from(risk == "ordinary"),
            "{risk}"
        );
        // A held legacy key produces repeated Press events, not Repeat.
        key(&mut shell, Key::Ctrl('s'));
        assert_eq!(server.writes().len(), usize::from(risk == "ordinary"));
        confirm(&mut shell);
        assert_eq!(
            server.writes().len(),
            usize::from(risk != "unknown"),
            "{risk}"
        );
        confirm(&mut shell);
        assert_eq!(server.writes().len(), usize::from(risk != "unknown"));
    }
    for cancel in [false, true] {
        let server = server();
        let mut shell = start(&server);
        preview(&mut shell);
        if cancel {
            key(&mut shell, Key::Esc);
            key(&mut shell, Key::Char('a'));
        } else {
            own_words(&mut shell, "Synthetic changed answer");
        }
        confirm(&mut shell);
        assert!(
            server.writes().is_empty(),
            "edit/cancel invalidates preview"
        );
    }
}

#[test]
fn cp5_invalid_text_missing_host_and_elapsed_source_time_refuse() {
    for words in [
        " \n\t".to_owned(),
        "Synthetic\0NUL".to_owned(),
        "é".repeat(8193),
    ] {
        let server = server();
        let mut shell = start(&server);
        own_words(&mut shell, &words);
        preview(&mut shell);
        confirm(&mut shell);
        assert!(server.writes().is_empty());
        assert!(shell.app.action_views[&ActionId::Answer].reason.is_some());
    }
    let server = server();
    let mut shell = start(&server);
    preview(&mut shell);
    let _ = text(&shell.app, now(70_001), 120, 40);
    shell.key(KeyPress::press(Key::Ctrl('s')), now(70_001));
    assert!(shell.settle(now(70_001), SETTLE));
    assert!(
        server.writes().is_empty(),
        "receipt did not renew oldest-source time"
    );
    let mut shell = Shell::new(
        App::new(settings(server.port, None)),
        client(server.port, None),
    );
    assert!(shell.settle(now(0), SETTLE));
    key(&mut shell, Key::Char('1'));
    key(&mut shell, Key::Char('a'));
    preview(&mut shell);
    confirm(&mut shell);
    assert!(server.writes().is_empty());
}

// The outcome must survive disconnect/navigation; lookup/restart never POST.
#[test]
fn cp5_disconnect_status_navigation_and_restart_never_replay() {
    let server = server();
    server.route(
        MESSAGES,
        Reply {
            raw: Some(Vec::new()),
            ..Reply::ok(Vec::new())
        },
    );
    let mut shell = start(&server);
    preview(&mut shell);
    confirm(&mut shell);
    assert!(
        shell.app.action_views[&ActionId::Answer]
            .outcome
            .as_ref()
            .unwrap()
            .contains("uncertain")
    );
    let op = shell.app.attempts[0].op_id.clone();
    let lookup = format!("{MESSAGES}/{op}");
    server.route(
        &lookup,
        Reply::status(503, "busy", "Synthetic busy status read"),
    );
    key(&mut shell, Key::Ctrl('r'));
    assert_eq!(server.count(&lookup), 1);
    assert!(
        shell.app.action_views[&ActionId::Answer]
            .outcome
            .as_ref()
            .unwrap()
            .contains("uncertain"),
        "a failed read cannot lower uncertain to refused"
    );
    key(&mut shell, Key::Esc);
    key(&mut shell, Key::Char('a'));
    confirm(&mut shell);
    assert_eq!(server.writes().len(), 1);
    let mut restarted = start(&server);
    confirm(&mut restarted);
    assert_eq!(
        server.writes().len(),
        1,
        "a new process has no restored preview/confirmation"
    );
}

// CP5 actual server integration. The recording server supplies only the
// synthetic decisions read. Preview, send, refusal and lookup below use the
// real server/core/store/allowlisted adapter and the real fake executable.
struct Backend {
    server: openwiz_server::Server,
    root: std::path::PathBuf,
}
impl Backend {
    fn new(host: bool) -> Self {
        use openwiz_adapter_cloudroom::source::CloudRoomSource;
        use openwiz_core::messaging::record::{SendStore, StoreError};
        use openwiz_server::{Config, SendHost, Sending};
        use openwiz_store::FileStore;
        use std::sync::Arc;
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "openwiz-answer-{}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        super::dirs::private_dir(&root).unwrap();
        let program = root.join("room-cli");
        std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-room-cli"), &program).unwrap();
        std::fs::write(
            root.join("fake-room-cli.scenario"),
            format!("{ROOT}/tests/fixtures/room-cli-0.43.1/send/scenario.json"),
        )
        .unwrap();
        std::fs::write(
            root.join("fake-room-cli.state"),
            root.join("state").to_str().unwrap(),
        )
        .unwrap();
        let state = root.join("state");
        let read_only = state.clone();
        let source = Arc::new(CloudRoomSource::new(program));
        let config = Config {
            allowed_host: Some("openwiz.example".into()),
            sending: Some(Sending {
                messenger: source.clone(),
                open_store: Arc::new(move || {
                    Ok(Box::new(FileStore::open(&state)?) as Box<dyn SendStore>)
                }),
                open_store_read_only: Arc::new(
                    move || -> Result<Option<Box<dyn SendStore>>, StoreError> {
                        Ok(FileStore::open_read_only(&read_only)?
                            .map(|s| Box::new(s) as Box<dyn SendStore>))
                    },
                ),
                host: host.then(|| SendHost::new("openwiz.example").unwrap()),
            }),
            ..Config::default()
        };
        let server = openwiz_server::start(
            openwiz_server::bind(0).unwrap(),
            config,
            source,
            Arc::new(FixedClock),
            Arc::new(|_| {}),
        )
        .unwrap();
        Self { server, root }
    }
    fn tells(&self) -> Vec<Vec<String>> {
        std::fs::read_to_string(self.root.join("invocations.log"))
            .unwrap_or_default()
            .lines()
            .map(|l| serde_json::from_str::<Vec<String>>(l).unwrap())
            .filter(|args| args.get(1).is_some_and(|a| a == "tell"))
            .collect()
    }
    fn calls(&self) -> Vec<Vec<String>> {
        std::fs::read_to_string(self.root.join("invocations.log"))
            .unwrap_or_default()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect()
    }
}
struct FixedClock;
impl openwiz_core::ops::Clock for FixedClock {
    fn now(&self) -> openwiz_core::model::Timestamp {
        openwiz_core::model::Timestamp(super::support::T)
    }
    fn monotonic(&self) -> std::time::Instant {
        std::time::Instant::now()
    }
}

#[test]
fn cp5_actual_fixture_server_one_allowlisted_send_guard_refusal_and_read_only_lookup() {
    for (allowed, disconnected) in [(true, false), (false, false), (true, true)] {
        let fixture = server();
        let mut d = decisions();
        d["orchestrator"]["target"]["known"] = "thr_syn_0001".into();
        d["items"][0]["request"]["risk"] = "live".into();
        set_decisions(&fixture, &d);
        let shell = start(&fixture);
        let backend = Backend::new(allowed);
        // Keep the same production app/decision binding, change only the
        // test HTTP peer from synthetic reads to the actual backend.
        let port = backend.server.local_addr().port();
        let mut shell = Shell::new(shell.app, client(port, Some("openwiz.example")));
        let words = " \tSynthetic actual-server answer\nexact final newline\n";
        own_words(&mut shell, words);
        key(&mut shell, Key::Ctrl('p'));
        assert_eq!(
            shell.app.action_views[&ActionId::Answer].status,
            "ready; nothing sent"
        );
        confirm(&mut shell);
        assert!(
            backend.tells().is_empty(),
            "first risky confirmation is not send"
        );
        let proxy = if disconnected {
            let (port, worker) = disconnect_after_response(backend.server.local_addr());
            shell = Shell::new(shell.app, client(port, Some("openwiz.example")));
            Some(worker)
        } else {
            None
        };
        confirm(&mut shell);
        if let Some(worker) = proxy {
            worker.join().unwrap();
        }
        let op = shell.app.attempts[0].op_id.clone();
        let outcome = shell.app.action_views[&ActionId::Answer]
            .outcome
            .as_ref()
            .unwrap();
        if allowed {
            assert!(
                outcome.starts_with(if disconnected {
                    "uncertain:"
                } else {
                    "accepted:"
                }),
                "{outcome}"
            );
            assert_eq!(
                backend.tells(),
                vec![
                    vec![
                        "thread",
                        "tell",
                        "thr_syn_0001",
                        "--mode",
                        "queue",
                        "--json",
                        "--",
                        words
                    ]
                    .into_iter()
                    .map(str::to_owned)
                    .collect::<Vec<_>>()
                ]
            );
            let record: Value = serde_json::from_slice(
                &std::fs::read(backend.root.join("state/sends").join(format!("{op}.json")))
                    .unwrap(),
            )
            .unwrap();
            assert_eq!(record["op_id"], op);
            assert_eq!(record["binding"]["target"], "thr_syn_0001");
        } else {
            assert!(outcome.starts_with("refused (HTTP 421)"), "{outcome}");
        }
        shell = Shell::new(shell.app, client(port, Some("openwiz.example")));
        let before_lookup = backend.calls();
        key(&mut shell, Key::Ctrl('r'));
        assert_eq!(
            backend.calls(),
            before_lookup,
            "lookup invokes no provider command"
        );
        confirm(&mut shell);
        key(&mut shell, Key::Esc);
        key(&mut shell, Key::Char('a'));
        confirm(&mut shell);
        assert_eq!(backend.tells().len(), usize::from(allowed));
        assert_eq!(
            shell.app.decisions.as_ref().unwrap().data.items.len(),
            1,
            "sent is not a saved/approved decision"
        );
        let view = &shell.app.action_views[&ActionId::Answer];
        assert!(
            view.effects
                .iter()
                .any(|s| s.contains("not a saved answer or approved decision"))
        );
        if allowed {
            assert_eq!(view.op_id.as_deref(), Some(op.as_str()));
        } else {
            assert_ne!(
                view.op_id.as_deref(),
                Some(op.as_str()),
                "an explicit refusal permits a fresh draft, never replay"
            );
        }
        // A new process starts without a restored preview. Opening the same
        // decision and pressing confirm alone cannot replay the saved send.
        let restarted = start(&fixture);
        let mut restarted = Shell::new(restarted.app, client(port, Some("openwiz.example")));
        confirm(&mut restarted);
        assert_eq!(backend.tells().len(), usize::from(allowed));
        drop(restarted);
        drop(shell);
        drop(backend.server);
        std::fs::remove_dir_all(backend.root).unwrap();
    }
}

/// Forward exactly one request to the actual backend, consume its complete
/// response, then close the client socket without returning it. The send has
/// happened, but the terminal cannot know that until a read-only lookup.
fn disconnect_after_response(peer: std::net::SocketAddr) -> (u16, std::thread::JoinHandle<()>) {
    use std::io::{Read, Write};
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let worker = std::thread::spawn(move || {
        let (mut client, _) = listener.accept().unwrap();
        client
            .set_read_timeout(Some(std::time::Duration::from_secs(10)))
            .unwrap();
        let mut bytes = Vec::new();
        let mut chunk = [0u8; 4096];
        loop {
            let n = client.read(&mut chunk).unwrap();
            assert_ne!(n, 0);
            bytes.extend_from_slice(&chunk[..n]);
            if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                let head = std::str::from_utf8(&bytes[..end]).unwrap();
                let length: usize = head
                    .lines()
                    .find_map(|l| {
                        l.to_ascii_lowercase()
                            .strip_prefix("content-length:")
                            .map(|v| v.trim().parse().unwrap())
                    })
                    .unwrap();
                if bytes.len() >= end + 4 + length {
                    break;
                }
            }
        }
        assert!(bytes.starts_with(b"POST /api/v1/sessions/thr_syn_0001/messages HTTP/1.1"));
        let mut backend = std::net::TcpStream::connect(peer).unwrap();
        backend
            .set_read_timeout(Some(std::time::Duration::from_secs(10)))
            .unwrap();
        backend.write_all(&bytes).unwrap();
        let mut response = Vec::new();
        backend.read_to_end(&mut response).unwrap();
        assert!(response.starts_with(b"HTTP/1.1 200"));
    });
    (port, worker)
}

// Screens come from the same production draw and key path. These assertions
// catch missing context/bytes or clipping that an HTTP-only proof misses.
#[test]
fn cp5_renders_context_recommendation_exact_bytes_and_resize_guard() {
    let server = server();
    let mut d = decisions();
    request_kind(&mut d, "grill_round");
    set_decisions(&server, &d);
    let mut shell = start(&server);
    preview(&mut shell);
    for (width, height) in [(120, 40), (80, 24), (36, 10), (24, 8)] {
        let screen = text(&shell.app, now(1), width, height);
        if width >= 36 {
            assert!(screen.contains("Answer Needs you"), "{screen}");
        }
        if width == 120 {
            assert!(
                screen.contains("Synthetic recommended option A."),
                "{screen}"
            );
        }
        if width == 24 {
            confirm_at_size(&mut shell, width, height);
            assert!(
                server.writes().is_empty(),
                "a clipped target cannot confirm"
            );
        }
        export_render(
            &shell.app,
            &format!("answer-ready-{width}x{height}"),
            width,
            height,
        );
    }
    own_words(&mut shell, " Synthetic exact words\nsecond line \t");
    preview(&mut shell);
    let mut all = String::new();
    for _ in 0..15 {
        all.push_str(&text(&shell.app, now(1), 80, 24));
        key(&mut shell, Key::PageDown);
    }
    let all = all.split_whitespace().collect::<Vec<_>>().join(" ");
    for word in [
        "Synthetic exact question?",
        "Synthetic retained context.",
        "Synthetic recommended option A.",
        "Fingerprint:",
        "Risk: ordinary",
        "ready; nothing sent",
    ] {
        assert!(all.contains(word), "{word}: {all}");
    }
    export_render(&shell.app, "answer-own-words-bottom-80x24", 80, 24);
    assert!(server.writes().is_empty());
}
fn confirm_at_size(shell: &mut Shell, width: u16, height: u16) {
    let _ = text(&shell.app, now(1), width, height);
    let c = shell.app.confirm_key();
    key(shell, Key::Ctrl(c));
}
fn export_render(app: &App, name: &str, width: u16, height: u16) {
    let Some(dir) = std::env::var_os("OPENWIZ_ANSWER_RENDER_OUT") else {
        return;
    };
    let dir = std::path::PathBuf::from(dir);
    super::dirs::private_dir_all(&dir).unwrap();
    let buffer = super::render::buffer(
        app,
        now(1),
        width,
        height,
        openwiz_terminal::render::Theme::TRUE_UNICODE,
    );
    std::fs::write(
        dir.join(format!("{name}.txt")),
        super::render::rows(&buffer).join("\n"),
    )
    .unwrap();
    let mut html = String::from(
        "<!doctype html><meta charset=utf-8><style>body{background:#0e0f11;margin:12px}pre{font:14px/18px 'DejaVu Sans Mono',monospace;margin:0;white-space:pre}</style><pre>",
    );
    let css = |c| match c {
        openwiz_terminal::ratatui::style::Color::Rgb(r, g, b) => format!("#{r:02x}{g:02x}{b:02x}"),
        _ => "#e8eaed".into(),
    };
    for y in 0..height {
        for x in 0..width {
            let c = &buffer[(x, y)];
            html.push_str(&format!(
                "<span style=\"color:{};background:{}\">{}</span>",
                css(c.fg),
                css(c.bg),
                c.symbol()
                    .replace('&', "&amp;")
                    .replace('<', "&lt;")
                    .replace('>', "&gt;")
            ));
        }
        html.push('\n');
    }
    html.push_str("</pre>");
    std::fs::write(dir.join(format!("{name}.html")), html).unwrap();
}

// A completed old HTTP read cannot bless a changed/cancelled draft. Hold
// exactly that completion so a newly requested preview cannot mask it.
#[test]
fn cp5_old_preview_completion_cannot_confirm_a_new_draft() {
    use openwiz_terminal::app::{Completion, Job};
    for cancel in [false, true] {
        let server = server();
        let mut shell = start(&server);
        shell.app.key(KeyPress::press(Key::Ctrl('p')), now(1));
        let mut jobs = shell.app.jobs(now(1));
        assert_eq!(jobs.len(), 1);
        let Job::Action { id, request, .. } = jobs.remove(0) else {
            panic!("expected one preview")
        };
        let result = openwiz_terminal::transport::execute(
            &client(server.port, Some("openwiz.example")),
            &request,
        );
        if cancel {
            shell.key(KeyPress::press(Key::Esc), now(1));
            shell.key(KeyPress::press(Key::Char('a')), now(1));
        } else {
            shell.key(KeyPress::press(Key::Char(' ')), now(1));
            shell.key(KeyPress::press(Key::Tab), now(1));
            shell.paste("Synthetic edited while previewing", now(1));
        }
        shell.app.key(KeyPress::press(Key::Ctrl('p')), now(1));
        shell
            .app
            .complete(Completion::Action { id, result }, now(1));
        assert_ne!(
            shell.app.action_views[&ActionId::Answer].status,
            "ready; nothing sent"
        );
        // Confirm before any newer queued preview can complete. A failed
        // confirmation invalidates that preview too; explicitly preview
        // again below before the one valid send.
        confirm(&mut shell);
        assert!(server.writes().is_empty());
        preview(&mut shell);
        confirm(&mut shell);
        assert_eq!(
            posted_text(&server),
            if cancel {
                "confirm spec #9001"
            } else {
                "Synthetic edited while previewing"
            }
        );
    }
}

// Self-review S1: a connection failure before dispatch is safe to retire,
// but only reopening + a new preview/confirmation can start another draft.
// The old module's unconditional sent marker prevents that recovery forever.
#[test]
fn cp5_failed_before_dispatch_requires_explicit_reopen_and_new_confirmation() {
    let server = server();
    let mut shell = start(&server);
    preview(&mut shell);
    let old_op = shell.app.action_views[&ActionId::Answer]
        .op_id
        .clone()
        .unwrap();
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let unavailable_port = listener.local_addr().unwrap().port();
    drop(listener);
    shell = Shell::new(shell.app, client(unavailable_port, Some("openwiz.example")));
    confirm(&mut shell);
    assert!(matches!(
        shell.app.attempts[0].outcome,
        Some(openwiz_terminal::actions::TransportResult::FailedBeforeDispatch { .. })
    ));
    assert!(!shell.app.attempts[0].locked());
    assert!(server.writes().is_empty());
    // Restoring the connection alone never retries anything.
    shell = Shell::new(shell.app, client(server.port, Some("openwiz.example")));
    confirm(&mut shell);
    assert!(server.writes().is_empty());
    key(&mut shell, Key::Esc);
    key(&mut shell, Key::Char('a'));
    let new_op = shell.app.action_views[&ActionId::Answer]
        .op_id
        .clone()
        .unwrap();
    assert_ne!(
        new_op, old_op,
        "explicitly reopened safe draft gets a new operation"
    );
    own_words(&mut shell, "Synthetic explicit new draft");
    confirm(&mut shell);
    assert!(
        server.writes().is_empty(),
        "reopening/editing still requires a new preview"
    );
    preview(&mut shell);
    confirm(&mut shell);
    assert_eq!(posted_text(&server), "Synthetic explicit new draft");
}

// Self-review S2: confirmations must expose every summary line with its
// contract number; an unnumbered copy obscures references to a specific line.
#[test]
fn cp5_confirmation_summaries_are_numbered_without_changing_the_words() {
    for kind in ["grill_confirmation", "spec_confirmation", "plan_approval"] {
        let server = server();
        let mut d = decisions();
        request_kind(&mut d, kind);
        set_decisions(&server, &d);
        let shell = start(&server);
        let screen = text(&shell.app, now(1), 120, 60);
        for expected in [
            "1. Synthetic summary line one.",
            "2. Synthetic summary line two.",
        ] {
            assert!(screen.contains(expected), "{kind}: {expected}:\n{screen}");
        }
        export_render(
            &shell.app,
            &format!("answer-{kind}-numbered-120x40"),
            120,
            40,
        );
        assert!(server.writes().is_empty());
    }
}

// Self-review S3 / CP5: schema-valid reports can still belong to another
// operation. Matching reports must be accepted, mismatches stay uncertain,
// and neither a bad send response nor a bad status response may replay POST.
fn accepted_report(op_id: &str) -> Value {
    let mut report = reply("send-accepted");
    report["op_id"] = op_id.into();
    report["target"]["id"] = TARGET.into();
    // Independent worked literal: Python hashlib.sha256(b"confirm spec #9001").
    report["text_sha256"] =
        "a9020507f23c7a02e4804677a2287ba14ece585325c4156f62e8098a099f7ed0".into();
    report["text_bytes"] = 18.into();
    report
}
fn mismatch_report(report: &mut Value, field: &str) {
    match field {
        "op" => report["op_id"] = "op-synthetic-other".into(),
        "target" => report["target"]["id"] = "thr_syn_0398".into(),
        "mode" => report["requested_mode"] = "steer".into(),
        "hash" => report["text_sha256"] = "b".repeat(64).into(),
        "bytes" => report["text_bytes"] = 19.into(),
        "good" => {}
        _ => unreachable!(),
    }
}
#[test]
fn cp5_send_and_lookup_response_identity_mismatches_stay_uncertain_without_replay() {
    for field in ["good", "op", "target", "mode", "hash", "bytes"] {
        let server = server();
        let mut shell = start(&server);
        preview(&mut shell);
        let op = shell.app.action_views[&ActionId::Answer]
            .op_id
            .clone()
            .unwrap();
        let mut report = accepted_report(&op);
        mismatch_report(&mut report, field);
        server.route(MESSAGES, Reply::ok(serde_json::to_vec(&report).unwrap()));
        confirm(&mut shell);
        assert!(
            matches!(
                shell.app.attempts[0].outcome,
                Some(openwiz_terminal::actions::TransportResult::Report { .. })
            ),
            "{field}: mismatched input must still be schema-valid"
        );
        let screen = text(&shell.app, now(1), 120, 80);
        assert!(
            screen.contains(if field == "good" {
                "accepted:"
            } else {
                "uncertain:"
            }),
            "send {field}: {screen}"
        );
        confirm(&mut shell);
        confirm(&mut shell);
        assert_eq!(server.writes().len(), 1, "send {field}: never replay");
    }
    for field in [
        "good",
        "outer op",
        "outer target",
        "op",
        "target",
        "mode",
        "hash",
        "bytes",
    ] {
        let server = server();
        let mut shell = start(&server);
        preview(&mut shell);
        let op = shell.app.action_views[&ActionId::Answer]
            .op_id
            .clone()
            .unwrap();
        let report = accepted_report(&op);
        server.route(MESSAGES, Reply::ok(serde_json::to_vec(&report).unwrap()));
        confirm(&mut shell);
        assert!(
            shell.app.action_views[&ActionId::Answer]
                .outcome
                .as_deref()
                .unwrap()
                .starts_with("accepted:")
        );
        let mut lookup = serde_json::json!({"schema":"openwiz.send-lookup.v1", "op_id":op, "target":TARGET, "summary":"Synthetic lookup; no call was made", "result":{"kind":"recorded", "report":report}});
        match field {
            "outer op" => lookup["op_id"] = "op-synthetic-other".into(),
            "outer target" => lookup["target"] = "thr_syn_0398".into(),
            _ => mismatch_report(&mut lookup["result"]["report"], field),
        }
        let path = format!("{MESSAGES}/{op}");
        server.route(&path, Reply::ok(serde_json::to_vec(&lookup).unwrap()));
        key(&mut shell, Key::Ctrl('r'));
        assert!(
            matches!(
                shell.app.attempts[0].last_status,
                Some(openwiz_terminal::actions::TransportResult::Report { .. })
            ),
            "lookup {field}: mismatched input must still be schema-valid"
        );
        let screen = text(&shell.app, now(1), 120, 80);
        assert!(
            screen.contains(if field == "good" {
                "Last status read: accepted:"
            } else {
                "Last status read: uncertain:"
            }),
            "lookup {field}: {screen}"
        );
        // A bad later read cannot rewrite the original matching acceptance.
        assert!(
            shell.app.action_views[&ActionId::Answer]
                .outcome
                .as_deref()
                .unwrap()
                .starts_with("accepted:")
        );
        confirm(&mut shell);
        assert_eq!(server.writes().len(), 1, "lookup {field}: never replay");
        assert_eq!(server.count(&path), 1);
        assert_eq!(server.writes()[0].path, MESSAGES);
    }
}

// Orchestrator's scope ruling: the shell must retain the binding from Open,
// not manufacture a new one at dispatch from a refreshed/reordered snapshot.
#[test]
fn cp5_shell_attempt_keeps_the_original_open_binding() {
    let server = server();
    let mut shell = start(&server);
    let generation = shell.app.decisions.as_ref().unwrap().generation;
    refresh(&mut shell);
    assert_ne!(generation, shell.app.decisions.as_ref().unwrap().generation);
    preview(&mut shell);
    confirm(&mut shell);
    let binding = shell.app.attempts[0]
        .decision
        .as_ref()
        .expect("Answer attempt retains its displayed decision");
    assert_eq!(binding.generation, generation);
    assert_eq!(
        (
            binding.subject_kind.as_str(),
            binding.subject_number,
            binding.comment_id
        ),
        ("issue", 9001, 7001)
    );
    assert_eq!(binding.request_id, "synthetic-spec-9001-r1");
    assert_eq!(binding.fingerprint, "a".repeat(64));
    assert_eq!(
        binding.proposal,
        [
            "Synthetic headline for spec 9001",
            "Synthetic summary line one.",
            "Synthetic summary line two."
        ]
    );
    assert_eq!(binding.record, decisions()["items"][0]["request"]);
    assert_eq!(
        binding.target,
        openwiz_terminal::model::Fact::Known(Some(TARGET.into()))
    );
}
fn two_items() -> Value {
    let mut d = decisions();
    let mut other = d["items"][0].clone();
    other["comment_id"] = 7002.into();
    other["subject"]["number"] = 9002.into();
    other["request"]["id"] = "synthetic-spec-9002-r1".into();
    other["request"]["spec"] = 9002.into();
    other["request"]["fingerprint"] = "b".repeat(64).into();
    d["items"].as_array_mut().unwrap().push(other);
    d
}
fn open_number(shell: &mut Shell, number: char) {
    if shell.app.open_action().is_some() {
        key(shell, Key::Esc);
    }
    if shell.app.detail.is_some() {
        key(shell, Key::Esc);
    }
    key(shell, Key::Char(number));
    key(shell, Key::Char('a'));
}
fn accept_draft(server: &FixtureServer, shell: &Shell) -> String {
    let view = &shell.app.action_views[&ActionId::Answer];
    let op = view.op_id.clone().unwrap();
    let mut report = accepted_report(&op);
    let words = view
        .fields
        .iter()
        .find(|f| f.0 == "sends")
        .unwrap()
        .2
        .as_str();
    report["text_sha256"] = match words {
        "confirm spec #9001" => "a9020507f23c7a02e4804677a2287ba14ece585325c4156f62e8098a099f7ed0",
        "confirm spec #9002" => "9ffa918e83a3918889514a8790b1a0a910456d5497a886de6707f9c722302ccb",
        "G1 yes" => "2355c3da83d13a6967e8b9794e942a49ab88bc65af8e5808ab2c86f4ac646605",
        "G2 yes" => "c6d64c16d79bdf320aeceb50005ef0ffad8b802881dc876bc9c8ad6994109eea",
        _ => panic!("unlisted independent reply literal: {words}"),
    }
    .into();
    report["text_bytes"] = (words.len() as u64).into();
    server.route(MESSAGES, Reply::ok(serde_json::to_vec(&report).unwrap()));
    op
}

// A known accepted message blocks a duplicate answer to that same item,
// while another item can be explicitly previewed/confirmed with a new op.
#[test]
fn cp5_accepted_answers_release_other_items_but_never_replay_an_old_item() {
    for grill in [false, true] {
        let server = server();
        let mut d = two_items();
        if grill {
            request_kind(&mut d, "grill_round");
            d["items"].as_array_mut().unwrap().truncate(1);
            let mut second = d["items"][0]["request"]["questions"][0].clone();
            second["id"] = "G2".into();
            second["decides"] = "Synthetic second question?".into();
            d["items"][0]["request"]["questions"]
                .as_array_mut()
                .unwrap()
                .push(second);
        }
        set_decisions(&server, &d);
        let mut shell = start(&server);
        preview(&mut shell);
        let first = accept_draft(&server, &shell);
        confirm(&mut shell);
        assert!(
            shell.app.action_views[&ActionId::Answer]
                .outcome
                .as_deref()
                .unwrap()
                .starts_with("accepted:")
        );
        open_number(&mut shell, '2');
        let second = shell.app.action_views[&ActionId::Answer]
            .op_id
            .clone()
            .unwrap();
        assert_ne!(first, second, "another item gets a fresh draft");
        confirm(&mut shell);
        assert_eq!(server.writes().len(), 1, "opening still needs preview");
        preview(&mut shell);
        accept_draft(&server, &shell);
        confirm(&mut shell);
        assert_eq!(server.writes().len(), 2);
        open_number(&mut shell, '1');
        assert_eq!(
            shell.app.action_views[&ActionId::Answer].op_id.as_deref(),
            Some(first.as_str()),
            "reopening A after B recovers A's exact attempt"
        );
        preview(&mut shell);
        confirm(&mut shell);
        assert_eq!(
            server.writes().len(),
            2,
            "accepted is not saved approval or authority to answer the same item twice"
        );
    }
}

// Refused HTTP requests made no effect; reopening is required and must use
// a fresh preview/confirmation, rather than replaying the refused operation.
#[test]
fn cp5_explicit_refusal_allows_an_explicit_new_draft() {
    for kind in ["http", "conflicting_reuse", "possible_duplicate_refused"] {
        let server = server();
        let mut shell = start(&server);
        preview(&mut shell);
        let old = shell.app.action_views[&ActionId::Answer]
            .op_id
            .clone()
            .unwrap();
        if kind == "http" {
            server.route(
                MESSAGES,
                Reply::status(403, "forbidden_origin", "Synthetic guard refusal"),
            );
        } else {
            let mut report = accepted_report(&old);
            report["status"] = kind.into();
            report["summary"] = "Synthetic explicit refusal; nothing was sent".into();
            report["result"] = if kind == "conflicting_reuse" {
                serde_json::json!({"kind":kind,"differs":["text"]})
            } else {
                serde_json::json!({"kind":kind,"earlier":[]})
            };
            server.route(MESSAGES, Reply::ok(serde_json::to_vec(&report).unwrap()));
        }
        confirm(&mut shell);
        assert_eq!(server.writes().len(), 1);
        open_number(&mut shell, '1');
        let new = shell.app.action_views[&ActionId::Answer]
            .op_id
            .clone()
            .unwrap();
        assert_ne!(old, new);
        confirm(&mut shell);
        assert_eq!(server.writes().len(), 1);
        preview(&mut shell);
        accept_draft(&server, &shell);
        confirm(&mut shell);
        assert_eq!(server.writes().len(), 2);
    }
}

// Only fresh complete coverage proving the old record gone can retire an
// uncertain answer for other items. Partial/stale absence proves nothing.
#[test]
fn cp5_uncertain_answer_blocks_until_fresh_complete_record_resolution() {
    let server = server();
    let mut d = two_items();
    set_decisions(&server, &d);
    server.route(
        MESSAGES,
        Reply {
            raw: Some(Vec::new()),
            ..Reply::ok(Vec::new())
        },
    );
    let mut shell = start(&server);
    preview(&mut shell);
    confirm(&mut shell);
    let old = shell.app.action_views[&ActionId::Answer]
        .op_id
        .clone()
        .unwrap();
    open_number(&mut shell, '2');
    assert_eq!(
        shell.app.action_views[&ActionId::Answer].op_id.as_deref(),
        Some(old.as_str())
    );
    confirm(&mut shell);
    assert_eq!(server.writes().len(), 1);
    d["items"].as_array_mut().unwrap().remove(0);
    let resolved = d.clone();
    for partial in [true, false] {
        d = resolved.clone();
        if partial {
            d["coverage"] = serde_json::json!({"state":"partial","gaps":[{"kind":"malformed","detail":"Synthetic incomplete discovery"}]});
        } else {
            d["freshness"]["state"] = "stale".into();
        }
        set_decisions(&server, &d);
        refresh(&mut shell);
        open_number(&mut shell, '1');
        assert_eq!(
            shell.app.action_views[&ActionId::Answer].op_id.as_deref(),
            Some(old.as_str())
        );
    }
    set_decisions(&server, &resolved);
    refresh(&mut shell);
    open_number(&mut shell, '1');
    assert_ne!(
        shell.app.action_views[&ActionId::Answer].op_id.as_deref(),
        Some(old.as_str())
    );
    preview(&mut shell);
    accept_draft(&server, &shell);
    confirm(&mut shell);
    assert_eq!(server.writes().len(), 2);
    assert!(
        matches!(
            shell.app.attempts[0].outcome,
            Some(openwiz_terminal::actions::TransportResult::UnknownAfterDispatch { .. })
        ),
        "resolution never rewrites the unknown delivery outcome"
    );
}

// Once multiple attempts exist, a late lookup belongs to its requested op,
// not the newest attempt or current pane. Completion order is controlled;
// the request itself still goes through real recording HTTP/transport.
#[test]
fn cp5_late_lookup_updates_its_original_attempt_only() {
    use openwiz_terminal::app::{Completion, Job};
    let server = server();
    set_decisions(&server, &two_items());
    let mut shell = start(&server);
    preview(&mut shell);
    let first = accept_draft(&server, &shell);
    confirm(&mut shell);
    let path = format!("{MESSAGES}/{first}");
    server.route(&path,Reply::ok(serde_json::to_vec(&serde_json::json!({"schema":"openwiz.send-lookup.v1","op_id":first,"target":TARGET,"summary":"Synthetic original operation; no call was made","result":{"kind":"recorded","report":accepted_report(&first)}})).unwrap()));
    shell.app.key(KeyPress::press(Key::Ctrl('r')), now(1));
    let job = shell
        .app
        .jobs(now(1))
        .into_iter()
        .find(|j| matches!(j, Job::Action { .. }))
        .unwrap();
    let Job::Action { id, request, .. } = job else {
        unreachable!()
    };
    let result = openwiz_terminal::transport::execute(
        &client(server.port, Some("openwiz.example")),
        &request,
    );
    open_number(&mut shell, '2');
    let second = shell.app.action_views[&ActionId::Answer]
        .op_id
        .clone()
        .unwrap();
    assert_ne!(first, second);
    preview(&mut shell);
    accept_draft(&server, &shell);
    confirm(&mut shell);
    let view = shell.app.action_views[&ActionId::Answer].clone();
    shell
        .app
        .complete(Completion::Action { id, result }, now(1));
    assert!(shell.app.attempts[0].last_status.is_some());
    assert!(shell.app.attempts[1].last_status.is_none());
    assert_eq!(
        shell.app.action_views[&ActionId::Answer],
        view,
        "the old read cannot change the new pane"
    );
    assert_eq!(server.count(&path), 1);
    assert_eq!(server.writes().len(), 2);
}

#[test]
fn cp5_unmatched_and_in_progress_reports_cannot_unlock_another_item() {
    for case in ["in_progress", "wrong op", "wrong hash", "wrong delivery"] {
        let server = server();
        set_decisions(&server, &two_items());
        let mut shell = start(&server);
        preview(&mut shell);
        let op = shell.app.action_views[&ActionId::Answer]
            .op_id
            .clone()
            .unwrap();
        let mut report = accepted_report(&op);
        match case {
            "in_progress" => {
                report["status"] = "in_progress".into();
                report["result"] = serde_json::json!({"kind":"in_progress","state":null});
            }
            "wrong op" => report["op_id"] = "op-synthetic-other".into(),
            "wrong hash" => report["text_sha256"] = "b".repeat(64).into(),
            "wrong delivery" => {
                report["result"]["delivery"] = serde_json::json!({"kind":"failed","reason":"not_found","text":"Synthetic failed delivery"})
            }
            _ => unreachable!(),
        }
        server.route(MESSAGES, Reply::ok(serde_json::to_vec(&report).unwrap()));
        confirm(&mut shell);
        assert!(
            matches!(
                shell.app.attempts[0].outcome,
                Some(openwiz_terminal::actions::TransportResult::Report { .. })
            ),
            "{case}: schema-valid mismatches must reach the binding guard"
        );
        open_number(&mut shell, '2');
        assert_eq!(
            shell.app.action_views[&ActionId::Answer].op_id.as_deref(),
            Some(op.as_str()),
            "{case}: still globally unresolved"
        );
        confirm(&mut shell);
        assert_eq!(server.writes().len(), 1);
    }
}

#[test]
fn cp5_a_matching_recorded_acceptance_can_settle_an_unknown_operation() {
    for later_failure in ["none", "503", "disconnect"] {
        let server = server();
        set_decisions(&server, &two_items());
        server.route(
            MESSAGES,
            Reply {
                raw: Some(Vec::new()),
                ..Reply::ok(Vec::new())
            },
        );
        let mut shell = start(&server);
        preview(&mut shell);
        confirm(&mut shell);
        let first = shell.app.action_views[&ActionId::Answer]
            .op_id
            .clone()
            .unwrap();
        let path = format!("{MESSAGES}/{first}");
        server.route(
            &path,
            Reply::status(503, "busy", "Synthetic unavailable status"),
        );
        key(&mut shell, Key::Ctrl('r'));
        open_number(&mut shell, '2');
        assert_eq!(
            shell.app.action_views[&ActionId::Answer].op_id.as_deref(),
            Some(first.as_str()),
            "failed reads cannot unlock uncertain delivery"
        );
        server.route(&path,Reply::ok(serde_json::to_vec(&serde_json::json!({"schema":"openwiz.send-lookup.v1","op_id":first,"target":TARGET,"summary":"Synthetic settled record; no call was made","result":{"kind":"recorded","report":accepted_report(&first)}})).unwrap()));
        key(&mut shell, Key::Ctrl('r'));
        if later_failure != "none" {
            server.route(
                &path,
                if later_failure == "503" {
                    Reply::status(503, "busy", "Synthetic later status failure")
                } else {
                    Reply {
                        raw: Some(Vec::new()),
                        ..Reply::ok(Vec::new())
                    }
                },
            );
            key(&mut shell, Key::Ctrl('r'));
        }
        let settled_screen = text(&shell.app, now(1), 120, 80);
        open_number(&mut shell, '2');
        assert_ne!(
            shell.app.action_views[&ActionId::Answer].op_id.as_deref(),
            Some(first.as_str())
        );
        assert!(
            settled_screen.contains("Confirmed outcome: accepted"),
            "positive settlement remains visible after {later_failure}: {settled_screen}"
        );
        preview(&mut shell);
        accept_draft(&server, &shell);
        confirm(&mut shell);
        assert_eq!(server.writes().len(), 2);
        assert_eq!(
            server.count(&path),
            if later_failure == "none" { 2 } else { 3 }
        );
        assert!(
            matches!(
                shell.app.attempts[0].outcome,
                Some(openwiz_terminal::actions::TransportResult::UnknownAfterDispatch { .. })
            ),
            "original outcome remains historical"
        );
    }
}

#[test]
fn cp5_saved_grill_question_releases_an_unresolved_attempt_for_the_next_question() {
    let server = server();
    let mut d = decisions();
    request_kind(&mut d, "grill_round");
    let mut second = d["items"][0]["request"]["questions"][0].clone();
    second["id"] = "G2".into();
    second["decides"] = "Synthetic second question?".into();
    d["items"][0]["request"]["questions"]
        .as_array_mut()
        .unwrap()
        .push(second);
    set_decisions(&server, &d);
    server.route(
        MESSAGES,
        Reply {
            raw: Some(Vec::new()),
            ..Reply::ok(Vec::new())
        },
    );
    let mut shell = start(&server);
    preview(&mut shell);
    confirm(&mut shell);
    let first = shell.app.action_views[&ActionId::Answer]
        .op_id
        .clone()
        .unwrap();
    d["items"][0]["request"]["answered"] = serde_json::json!(["G1"]);
    set_decisions(&server, &d);
    refresh(&mut shell);
    open_number(&mut shell, '1');
    assert_ne!(
        shell.app.action_views[&ActionId::Answer].op_id.as_deref(),
        Some(first.as_str())
    );
    preview(&mut shell);
    accept_draft(&server, &shell);
    confirm(&mut shell);
    assert_eq!(server.writes().len(), 2);
    let body: Value = serde_json::from_slice(&server.writes()[1].body).unwrap();
    assert_eq!(body["text"], "G2 yes");
}

// Audit L2: A's POST response may arrive after its lookup has established
// acceptance. Its completion must never consume B's pending preview or
// become B's outcome. Every HTTP request still runs real transport; the
// app applies completions in an explicit deterministic order (no sleeps).
#[test]
fn cp5_late_post_completion_cannot_change_another_items_preview_or_outcome() {
    use openwiz_terminal::app::{Completion, Job};
    fn take_action(shell: &mut Shell, key: Key) -> (u64, openwiz_terminal::actions::ActionRequest) {
        shell.app.key(KeyPress::press(key), now(1));
        let mut jobs = shell.app.jobs(now(1));
        assert_eq!(jobs.len(), 1);
        let Job::Action { id, request, .. } = jobs.remove(0) else {
            panic!("expected one action job")
        };
        (id, request)
    }
    for late_at in ["preview", "dispatch"] {
        for response in ["accepted", "disconnect"] {
            let server = server();
            set_decisions(&server, &two_items());
            let mut shell = start(&server);
            preview(&mut shell);
            let first = accept_draft(&server, &shell);
            if response == "disconnect" {
                server.route(
                    MESSAGES,
                    Reply {
                        raw: Some(Vec::new()),
                        ..Reply::ok(Vec::new())
                    },
                );
            }
            let c = shell.app.confirm_key();
            let (post_id, post_request) = take_action(&mut shell, Key::Ctrl(c));
            let http = client(server.port, Some("openwiz.example"));
            let post_result = openwiz_terminal::transport::execute(&http, &post_request);
            let path = format!("{MESSAGES}/{first}");
            server.route(&path,Reply::ok(serde_json::to_vec(&serde_json::json!({"schema":"openwiz.send-lookup.v1","op_id":first,"target":TARGET,"summary":"Synthetic accepted record; no call was made","result":{"kind":"recorded","report":accepted_report(&first)}})).unwrap()));
            let (lookup_id, lookup) = take_action(&mut shell, Key::Ctrl('r'));
            let found = openwiz_terminal::transport::execute(&http, &lookup);
            shell.app.complete(
                Completion::Action {
                    id: lookup_id,
                    result: found,
                },
                now(1),
            );
            open_number(&mut shell, '2');
            let second = shell.app.action_views[&ActionId::Answer]
                .op_id
                .clone()
                .unwrap();
            assert_ne!(first, second, "the lookup has positively settled A");
            let (preview_id, preview_request) = take_action(&mut shell, Key::Ctrl('p'));
            let preview_result = openwiz_terminal::transport::execute(&http, &preview_request);
            if late_at == "preview" {
                shell.app.complete(
                    Completion::Action {
                        id: post_id,
                        result: post_result,
                    },
                    now(1),
                );
                shell.app.complete(
                    Completion::Action {
                        id: preview_id,
                        result: preview_result,
                    },
                    now(1),
                );
                assert_eq!(
                    shell.app.action_views[&ActionId::Answer].status,
                    "ready; nothing sent",
                    "{late_at}/{response}: A must not consume B's preview"
                );
                accept_draft(&server, &shell);
                confirm(&mut shell);
            } else {
                shell.app.complete(
                    Completion::Action {
                        id: preview_id,
                        result: preview_result,
                    },
                    now(1),
                );
                let _ = text(&shell.app, now(1), 120, 40);
                accept_draft(&server, &shell);
                let c = shell.app.confirm_key();
                let (second_id, second_request) = take_action(&mut shell, Key::Ctrl(c));
                let second_result = openwiz_terminal::transport::execute(&http, &second_request);
                shell.app.complete(
                    Completion::Action {
                        id: post_id,
                        result: post_result,
                    },
                    now(1),
                );
                shell.app.complete(
                    Completion::Action {
                        id: second_id,
                        result: second_result,
                    },
                    now(1),
                );
            }
            let view = &shell.app.action_views[&ActionId::Answer];
            assert_eq!(view.op_id.as_deref(), Some(second.as_str()));
            assert!(
                view.outcome.as_deref().unwrap().starts_with("accepted:"),
                "{late_at}/{response}: A must not change B's outcome: {view:?}"
            );
            assert_eq!(server.writes().len(), 2);
            assert_eq!(server.count(&path), 1);
        }
    }
}

// R1: a preview started for B must never consume or replace A's status after
// A is reopened. Real HTTP results are applied in both explicit orders;
// no timers or sleeps determine which completion arrives first.
#[test]
fn cp5_late_preview_cannot_replace_reopened_attempt_status() {
    use openwiz_terminal::app::{Completion, Job};
    fn take_action(shell: &mut Shell, key: Key) -> (u64, openwiz_terminal::actions::ActionRequest) {
        shell.app.key(KeyPress::press(key), now(1));
        let mut jobs = shell.app.jobs(now(1));
        assert_eq!(jobs.len(), 1);
        let Job::Action { id, request, .. } = jobs.remove(0) else {
            panic!("expected one action job")
        };
        (id, request)
    }
    for lookup_first in [true, false] {
        for preview_reply in ["ready", "refused", "disconnect"] {
            let server = server();
            set_decisions(&server, &two_items());
            let mut shell = start(&server);
            preview(&mut shell);
            let first = accept_draft(&server, &shell);
            confirm(&mut shell);
            let path = format!("{MESSAGES}/{first}");
            server.route(&path,Reply::ok(serde_json::to_vec(&serde_json::json!({"schema":"openwiz.send-lookup.v1","op_id":first,"target":TARGET,"summary":"Synthetic accepted record; no call was made","result":{"kind":"recorded","report":accepted_report(&first)}})).unwrap()));
            open_number(&mut shell, '2');
            let second = shell.app.action_views[&ActionId::Answer]
                .op_id
                .clone()
                .unwrap();
            assert_ne!(first, second);
            let preview_path = format!("/api/v1/sessions/{TARGET}/preview?mode=queue");
            match preview_reply {
                "refused" => server.route(
                    &preview_path,
                    Reply::status(503, "busy", "Synthetic preview unavailable"),
                ),
                "disconnect" => server.route(
                    &preview_path,
                    Reply {
                        raw: Some(Vec::new()),
                        ..Reply::ok(Vec::new())
                    },
                ),
                _ => {}
            }
            let (preview_id, preview_request) = take_action(&mut shell, Key::Ctrl('p'));
            let http = client(server.port, Some("openwiz.example"));
            let preview_result = openwiz_terminal::transport::execute(&http, &preview_request);
            open_number(&mut shell, '1');
            assert_eq!(
                shell.app.action_views[&ActionId::Answer].op_id.as_deref(),
                Some(first.as_str())
            );
            let (lookup_id, lookup_request) = take_action(&mut shell, Key::Ctrl('r'));
            let lookup_result = openwiz_terminal::transport::execute(&http, &lookup_request);
            let preview_done = Completion::Action {
                id: preview_id,
                result: preview_result,
            };
            let lookup_done = Completion::Action {
                id: lookup_id,
                result: lookup_result,
            };
            let completions = if lookup_first {
                [lookup_done, preview_done]
            } else {
                [preview_done, lookup_done]
            };
            for completion in completions {
                shell.app.complete(completion, now(1));
            }
            let screen = text(&shell.app, now(1), 120, 80);
            assert!(
                screen.contains("Last status read: accepted:"),
                "{lookup_first}/{preview_reply}: {screen}"
            );
            assert!(
                !screen.contains("response identity does not match"),
                "{screen}"
            );
            assert_eq!(
                shell.app.action_views[&ActionId::Answer].op_id.as_deref(),
                Some(first.as_str())
            );
            assert!(shell.app.attempts[0].last_status.is_some());
            assert_eq!(server.count(&path), 1);
            assert_eq!(server.count(&preview_path), 2);
            confirm(&mut shell);
            assert_eq!(server.writes().len(), 1, "reopened A cannot replay");
        }
    }
}

// A queued preview keeps the draft identity from enqueue, even if the pane
// changes again before a lane becomes free. It cannot validate a newer draft.
#[test]
fn cp5_queued_preview_cannot_validate_a_newer_draft() {
    use openwiz_terminal::app::{Completion, Job};
    let server = server();
    let mut shell = start(&server);
    let http = client(server.port, Some("openwiz.example"));
    let take = |shell: &mut Shell| {
        let mut jobs = shell.app.jobs(now(1));
        assert_eq!(jobs.len(), 1);
        let Job::Action { id, request, .. } = jobs.remove(0) else {
            panic!("expected one action job")
        };
        let result = openwiz_terminal::transport::execute(&http, &request);
        Completion::Action { id, result }
    };
    shell.app.key(KeyPress::press(Key::Ctrl('p')), now(1));
    let oldest = take(&mut shell);
    open_number(&mut shell, '1');
    shell.app.key(KeyPress::press(Key::Ctrl('p')), now(1));
    assert!(
        shell.app.jobs(now(1)).is_empty(),
        "preview lane is occupied"
    );
    let queued_op = shell.app.action_views[&ActionId::Answer].op_id.clone();
    open_number(&mut shell, '1');
    let newest_op = shell.app.action_views[&ActionId::Answer].op_id.clone();
    assert_ne!(queued_op, newest_op);
    shell.app.complete(oldest, now(1));
    let queued = take(&mut shell);
    shell.app.key(KeyPress::press(Key::Ctrl('p')), now(1));
    assert!(shell.app.jobs(now(1)).is_empty());
    shell.app.complete(queued, now(1));
    assert_eq!(
        shell.app.action_views[&ActionId::Answer].status,
        "previewing; nothing sent"
    );
    assert_eq!(shell.app.action_views[&ActionId::Answer].op_id, newest_op);
    let newest = take(&mut shell);
    shell.app.complete(newest, now(1));
    assert_eq!(
        shell.app.action_views[&ActionId::Answer].status,
        "ready; nothing sent"
    );
    assert!(server.writes().is_empty());
    accept_draft(&server, &shell);
    confirm(&mut shell);
    assert_eq!(server.writes().len(), 1);
    assert_eq!(
        server.count(&format!("/api/v1/sessions/{TARGET}/preview?mode=queue")),
        3
    );
}

// Self-review: receipt and lookup have separate meanings even in the same
// pane. A late POST must not become the last status read (or vice versa).
#[test]
fn cp5_same_pane_receipt_and_status_keep_their_request_roles_in_either_order() {
    use openwiz_terminal::app::{Completion, Job};
    for lookup_first in [true, false] {
        for post_kind in ["accepted", "refused", "disconnect"] {
            for lookup_kind in ["accepted", "refused", "disconnect"] {
                let server = server();
                let mut shell = start(&server);
                preview(&mut shell);
                let op = accept_draft(&server, &shell);
                let failure = |kind| match kind {
                    "refused" => Reply::status(503, "busy", "Synthetic unavailable response"),
                    "disconnect" => Reply {
                        raw: Some(Vec::new()),
                        ..Reply::ok(Vec::new())
                    },
                    _ => unreachable!(),
                };
                if post_kind != "accepted" {
                    server.route(MESSAGES, failure(post_kind));
                }
                let path = format!("{MESSAGES}/{op}");
                server.route(&path, if lookup_kind == "accepted" { Reply::ok(serde_json::to_vec(&serde_json::json!({"schema":"openwiz.send-lookup.v1","op_id":op,"target":TARGET,"summary":"Synthetic recorded acceptance","result":{"kind":"recorded","report":accepted_report(&op)}})).unwrap()) } else { failure(lookup_kind) });
                let take = |shell: &mut Shell| {
                    let mut jobs = shell.app.jobs(now(1));
                    assert_eq!(jobs.len(), 1);
                    let Job::Action { id, request, .. } = jobs.remove(0) else {
                        panic!("expected one action")
                    };
                    let result = openwiz_terminal::transport::execute(
                        &client(server.port, Some("openwiz.example")),
                        &request,
                    );
                    Completion::Action { id, result }
                };
                let _ = text(&shell.app, now(1), 120, 40);
                let c = shell.app.confirm_key();
                shell.app.key(KeyPress::press(Key::Ctrl(c)), now(1));
                let post = take(&mut shell);
                shell.app.key(KeyPress::press(Key::Ctrl('r')), now(1));
                let lookup = take(&mut shell);
                let prefix = |kind| match kind {
                    "accepted" => "accepted:",
                    "refused" => "refused (HTTP 503):",
                    "disconnect" => "uncertain:",
                    _ => unreachable!(),
                };
                let post_prefix = prefix(post_kind);
                let status_prefix = format!("Last status read: {}", prefix(lookup_kind));
                let completions = if lookup_first {
                    [(false, lookup), (true, post)]
                } else {
                    [(true, post), (false, lookup)]
                };
                let mut saw_post = false;
                let mut saw_lookup = false;
                for (is_post, completion) in completions {
                    shell.app.complete(completion, now(1));
                    saw_post |= is_post;
                    saw_lookup |= !is_post;
                    let view = &shell.app.action_views[&ActionId::Answer];
                    assert_eq!(
                        view.outcome.is_some(),
                        saw_post,
                        "{lookup_first}/{post_kind}/{lookup_kind}: {view:?}"
                    );
                    if saw_post {
                        assert!(
                            view.outcome.as_deref().unwrap().starts_with(post_prefix),
                            "{view:?}"
                        );
                    }
                    assert_eq!(
                        view.effects.iter().any(|s| s.starts_with(&status_prefix)),
                        saw_lookup,
                        "{lookup_first}/{post_kind}/{lookup_kind}: {view:?}"
                    );
                }
                let outcome = shell.app.action_views[&ActionId::Answer].outcome.clone();
                if post_kind != "refused" {
                    open_number(&mut shell, '1');
                    let view = &shell.app.action_views[&ActionId::Answer];
                    assert_eq!(view.outcome, outcome);
                    assert!(
                        view.effects.iter().any(|s| s.starts_with(&status_prefix)),
                        "{view:?}"
                    );
                }
                confirm(&mut shell);
                assert_eq!(server.writes().len(), 1);
                assert_eq!(server.count(&path), 1);
            }
        }
    }
}

/// 2141: identical local IDs in a later repository cannot renew an opened
/// answer. Existing stale/wording tests changed other fields as well.
#[test]
fn cp5_repository_change_cannot_rebind_an_open_answer() {
    let server = server();
    let mut d = decisions();
    d["items"][0]["subject"]["repository"] = "synthetic-public/work".into();
    set_decisions(&server, &d);
    let mut shell = start(&server);
    preview(&mut shell);
    d["items"][0]["subject"]["repository"] = "synthetic-records/archive".into();
    set_decisions(&server, &d);
    refresh(&mut shell);
    confirm(&mut shell);
    assert!(
        server.writes().is_empty(),
        "a repository change must invalidate the old answer"
    );
    assert!(shell.app.action_views[&ActionId::Answer].reason.is_some());
}

/// The same numeric IDs/fingerprint/request may appear on different repos.
/// Selection and accepted-attempt recovery must keep their namespace, without
/// changing the message text, screen or confirmation keys.
#[test]
fn cp5_repository_namespaces_selection_and_accepted_recovery() {
    let server = server();
    let mut d = decisions();
    d["items"][0]["subject"]["repository"] = "synthetic-public/work".into();
    let mut second = d["items"][0].clone();
    second["subject"]["repository"] = "synthetic-records/archive".into();
    d["items"].as_array_mut().unwrap().push(second);
    set_decisions(&server, &d);
    let mut shell = start(&server);
    preview(&mut shell);
    let first = accept_draft(&server, &shell);
    confirm(&mut shell);
    assert_eq!(server.writes().len(), 1);
    open_number(&mut shell, '2');
    let second = shell.app.action_views[&ActionId::Answer]
        .op_id
        .clone()
        .unwrap();
    assert_ne!(
        first, second,
        "another repository cannot recover the first attempt"
    );
    confirm(&mut shell);
    assert_eq!(
        server.writes().len(),
        1,
        "the second record still requires preview"
    );
    preview(&mut shell);
    accept_draft(&server, &shell);
    confirm(&mut shell);
    assert_eq!(server.writes().len(), 2);
    for write in server.writes() {
        let body: Value = serde_json::from_slice(&write.body).unwrap();
        assert_eq!(body["text"], "confirm spec #9001");
    }
    open_number(&mut shell, '1');
    assert_eq!(
        shell.app.action_views[&ActionId::Answer].op_id.as_deref(),
        Some(first.as_str())
    );
    preview(&mut shell);
    confirm(&mut shell);
    assert_eq!(
        server.writes().len(),
        2,
        "recovering the first accepted answer never replays it"
    );
}

/// The existing wording status must come from the opened repository, even
/// when another repository has the same local IDs with a different status.
#[test]
fn cp5_repository_selects_its_own_current_wording_status() {
    let server = server();
    let mut d = decisions();
    d["items"][0]["subject"]["repository"] = "synthetic-public/work".into();
    let mut second = d["items"][0].clone();
    second["subject"]["repository"] = "synthetic-records/archive".into();
    d["items"][0]["current"] = serde_json::json!({"known":false});
    second["current"] = serde_json::json!({"known":true});
    d["items"].as_array_mut().unwrap().push(second);
    set_decisions(&server, &d);
    let mut shell = start(&server);
    open_number(&mut shell, '2');
    let view = &shell.app.action_views[&ActionId::Answer];
    assert!(
        view.effects
            .iter()
            .any(|s| s == "Risk: ordinary · wording: current"),
        "{:?}",
        view.effects
    );
    assert!(server.writes().is_empty());
}
