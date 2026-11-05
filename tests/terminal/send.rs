//! CP6: production input → screen → recording HTTP, and the actual server.
//! T3 proved only a synthetic action; these cases catch an absent composer,
//! changed draft authorization, wrong binding, repeated POSTs and dishonest status.
use openwiz_terminal::actions::ActionId;
use openwiz_terminal::app::{App, Key, KeyPress};
use openwiz_terminal::run::Shell;
use serde_json::{Value, json};
use std::path::Path;
use std::time::Duration;

use super::render::text;
use super::support::{FixtureServer, ROOT, Reply, SETTLE, client, now, settings};

const TARGET: &str = "thr_syn_0301";
const PREVIEW: &str = "/api/v1/sessions/thr_syn_0301/preview?mode=queue";
const MESSAGES: &str = "/api/v1/sessions/thr_syn_0301/messages";
const HOST: &str = "openwiz.example";
const DRAFT: &str = "  Synthetic café\n--json ";

fn report(name: &str) -> Value {
    serde_json::from_slice(
        &std::fs::read(Path::new(ROOT).join("tests/terminal/actions").join(name)).unwrap(),
    )
    .unwrap()
}
fn preview(mode: &str, paused: bool) -> Value {
    let mut p = report("send-preview.json");
    p["target"]["id"] = json!(TARGET);
    p["requested_mode"] = json!(mode);
    p["effects"]["read_age_ms"] = json!(12_000);
    p["effects"]["needs_acknowledgement"] = json!(paused);
    p["effects"]["paused_queue"]["known"]["appears_paused"] = json!(paused);
    if paused {
        p["status"] = json!("needs_acknowledgement");
    }
    p
}
fn reply(value: Value) -> Reply {
    Reply::ok(serde_json::to_vec(&value).unwrap())
}
fn key(s: &mut Shell, k: Key) {
    s.key(KeyPress::press(k), now(2));
}
fn draw(s: &Shell) -> String {
    text(&s.app, now(2), 120, 40)
}
fn open(s: &mut Shell) {
    for k in [Key::Char('s'), Key::Down, Key::Enter] {
        key(s, k);
    }
    assert!(s.settle(now(2), SETTLE));
    key(s, Key::Char('m'));
    assert_eq!(s.app.open_action(), Some(ActionId::Send));
    draw(s);
}
fn compose(server: &FixtureServer) -> Shell {
    server.route(PREVIEW, reply(preview("queue", false)));
    let mut s = Shell::new(
        App::new(settings(server.port, Some(HOST))),
        client(server.port, Some(HOST)),
    );
    assert!(s.settle(now(0), SETTLE));
    open(&mut s);
    s.app.paste(DRAFT, now(2));
    s
}
fn ready(s: &mut Shell) {
    key(s, Key::Ctrl('p'));
    assert!(s.settle(now(2), SETTLE));
    draw(s);
}
fn confirm(s: &mut Shell) {
    let c = s.app.confirm_key();
    key(s, Key::Ctrl(c));
}
fn field(s: &Shell, id: &str) -> String {
    s.app.action_views[&ActionId::Send]
        .fields
        .iter()
        .find(|f| f.0 == id)
        .unwrap()
        .2
        .clone()
}
fn bound_report(s: &Shell, status: &str) -> Value {
    let mut r = report("send-accepted.json");
    r["target"]["id"] = json!(TARGET);
    r["op_id"] = json!(s.app.action_views[&ActionId::Send].op_id.clone().unwrap());
    r["text_bytes"] = json!(DRAFT.len());
    r["text_sha256"] = json!(openwiz_core::messaging::sha256_hex(DRAFT.as_bytes()));
    r["status"] = json!(status);
    r
}

#[test]
fn cp6_preview_cancel_and_changed_drafts_never_send() {
    let server = FixtureServer::home();
    let mut s = compose(&server);
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert!(server.writes().is_empty());
    ready(&mut s);
    let view = &s.app.action_views[&ActionId::Send];
    assert_eq!(view.target, TARGET);
    assert_eq!(view.status, "ready");
    assert!(
        view.effects
            .iter()
            .any(|e| e.contains("reported age 12000ms"))
    );
    assert!(
        view.effects
            .iter()
            .any(|e| e.contains("source read at 1793978204178"))
    );
    assert_eq!(field(&s, "text"), "  Synthetic café\\n--json ");
    assert!(draw(&s).contains("starts a turn"));
    s.app.paste("changed", now(2));
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert!(server.writes().is_empty());
    ready(&mut s);
    key(&mut s, Key::Esc);
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert!(server.writes().is_empty());
    assert!(s.app.attempts.is_empty());
}

#[test]
fn cp6_exact_body_once_with_held_keys_and_read_only_lookup() {
    let server = FixtureServer::home();
    let mut s = compose(&server);
    ready(&mut s);
    let r = bound_report(&s, "accepted");
    server.route(MESSAGES, reply(r.clone()));
    let op = s.app.action_views[&ActionId::Send].op_id.clone().unwrap();
    s.key(
        KeyPress {
            key: Key::Ctrl('s'),
            repeat: true,
            release: false,
        },
        now(2),
    );
    assert!(s.settle(now(2), SETTLE));
    assert!(server.writes().is_empty());
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    for _ in 0..5 {
        confirm(&mut s);
    }
    assert!(s.settle(now(2), SETTLE));
    let writes = server.writes();
    assert_eq!(writes.len(), 1);
    assert_eq!(writes[0].path, MESSAGES);
    assert_eq!(
        serde_json::from_slice::<Value>(&writes[0].body).unwrap(),
        json!({
            "op_id":op,"mode":"queue","text":DRAFT,"resume_paused_queue":false,"accept_possible_duplicate":false
        })
    );
    assert_eq!(writes[0].header("Host"), vec![HOST]);
    assert_eq!(s.app.action_views[&ActionId::Send].status, "accepted");
    assert!(
        s.app.action_views[&ActionId::Send]
            .outcome
            .as_deref()
            .unwrap()
            .contains("not completed")
    );
    let path = format!("{MESSAGES}/{op}");
    server.route(&path,reply(json!({"schema":"openwiz.send-lookup.v1","target":TARGET,"op_id":op,"summary":"Synthetic lookup","result":{"kind":"recorded","report":r}})));
    key(&mut s, Key::Ctrl('r'));
    assert!(s.settle(now(2), SETTLE));
    assert_eq!(server.count(&path), 1);
    assert_eq!(server.writes().len(), 1);
    assert!(s.app.attempts[0].locked());
    key(&mut s, Key::Esc);
    key(&mut s, Key::Char('m'));
    draw(&s);
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert_eq!(server.writes().len(), 1);
    assert_eq!(
        s.app.action_views[&ActionId::Send].op_id.as_deref(),
        Some(op.as_str())
    );
}

#[test]
fn cp6_explicit_acknowledgements_and_steer_require_a_new_preview() {
    let server = FixtureServer::home();
    let mut s = compose(&server);
    server.route(PREVIEW, reply(preview("queue", true)));
    ready(&mut s);
    assert_eq!(
        s.app.action_views[&ActionId::Send].status,
        "needs_acknowledgement"
    );
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert!(server.writes().is_empty());
    key(&mut s, Key::Tab); // mode
    key(&mut s, Key::Tab); // resume
    key(&mut s, Key::Char(' '));
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert!(server.writes().is_empty());
    key(&mut s, Key::Tab); // duplicate
    key(&mut s, Key::Char(' '));
    ready(&mut s);
    server.route(
        MESSAGES,
        Reply::status(403, "forbidden_origin", "Synthetic refusal"),
    );
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    let body: Value = serde_json::from_slice(&server.writes()[0].body).unwrap();
    assert_eq!(body["resume_paused_queue"], true);
    assert_eq!(body["accept_possible_duplicate"], true);
    assert_eq!(s.app.action_views[&ActionId::Send].status, "refused");
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert_eq!(server.writes().len(), 1);

    let server = FixtureServer::home();
    let mut s = compose(&server);
    ready(&mut s);
    key(&mut s, Key::Tab);
    key(&mut s, Key::Char(' '));
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert!(server.writes().is_empty());
    server.route(
        "/api/v1/sessions/thr_syn_0301/preview?mode=steer",
        reply(preview("steer", false)),
    );
    ready(&mut s);
    server.route(
        MESSAGES,
        Reply::status(403, "forbidden_origin", "Synthetic refusal"),
    );
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    let body: Value = serde_json::from_slice(&server.writes()[0].body).unwrap();
    assert_eq!(body["mode"], "steer");
    assert_eq!(body["text"], DRAFT);
}

#[test]
fn cp6_disconnect_lookup_failure_and_restart_never_replay() {
    let server = FixtureServer::home();
    let mut s = compose(&server);
    ready(&mut s);
    server.route(
        MESSAGES,
        Reply {
            raw: Some(Vec::new()),
            ..Reply::ok(Vec::new())
        },
    );
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert_eq!(s.app.action_views[&ActionId::Send].status, "uncertain");
    let op = s.app.action_views[&ActionId::Send].op_id.clone().unwrap();
    let path = format!("{MESSAGES}/{op}");
    server.route(&path,reply(json!({"schema":"openwiz.send-lookup.v1","op_id":op,"target":TARGET,"summary":"Synthetic no record","result":{"kind":"no_record"}})));
    key(&mut s, Key::Ctrl('r'));
    assert!(s.settle(now(2), SETTLE));
    assert_eq!(s.app.action_views[&ActionId::Send].status, "uncertain");
    assert!(
        s.app.action_views[&ActionId::Send]
            .reason
            .as_deref()
            .unwrap()
            .contains("no_record")
    );
    server.route(
        &path,
        Reply::status(500, "record_unavailable", "Synthetic unavailable"),
    );
    key(&mut s, Key::Ctrl('r'));
    assert!(s.settle(now(2), SETTLE));
    assert_eq!(s.app.action_views[&ActionId::Send].status, "uncertain");
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert_eq!(server.writes().len(), 1);
    drop(s);
    let mut restarted = compose(&server);
    confirm(&mut restarted);
    assert!(restarted.settle(now(2), SETTLE));
    assert_eq!(server.writes().len(), 1);
    assert!(draw(&restarted).contains("recovery unavailable"));
}

#[test]
fn cp6_late_or_mismatched_previews_and_invalid_text_cannot_authorize() {
    for bad in ["", " \n\t", "bad\0text", &"é".repeat(8193)] {
        let server = FixtureServer::home();
        let mut s = compose(&server);
        // Clear the exact draft through the real editor.
        for _ in DRAFT.chars() {
            key(&mut s, Key::Backspace);
        }
        s.app.paste(bad, now(2));
        ready(&mut s);
        confirm(&mut s);
        assert!(s.settle(now(2), SETTLE));
        assert_eq!(server.count(PREVIEW), 0, "{bad:?}");
        assert!(server.writes().is_empty());
    }
    let server = FixtureServer::home();
    let mut s = compose(&server);
    server.route(
        PREVIEW,
        reply(preview("queue", false)).delayed(Duration::from_millis(50)),
    );
    key(&mut s, Key::Ctrl('p'));
    s.pump(now(2));
    s.app.paste("changed", now(2));
    assert!(s.settle(now(2), SETTLE));
    draw(&s);
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert!(server.writes().is_empty());
    let mut p = preview("queue", false);
    p["target"]["id"] = json!("thr_syn_9999");
    server.route(PREVIEW, reply(p));
    ready(&mut s);
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert!(server.writes().is_empty());
    assert_eq!(s.app.action_views[&ActionId::Send].status, "refused");
}

// CP6 outcome honesty belongs at the visible production shell, rather than
// asserting a transport enum. Each reply is schema-valid but independent of
// the composer; the matching identity is substituted for this bound attempt.
#[test]
fn cp6_outcomes_stay_distinct_and_mismatched_reports_stay_uncertain() {
    use openwiz_core::messaging::send::{Delivery, FailReason, UncertainReason, WaitingOn};
    let cases = [
        (
            "queued",
            json!({"kind":"outcome","delivery":Delivery::queued(WaitingOn::ThreadBusy,"syn-queue".into()),"replayed":false,"recovered":false}),
        ),
        (
            "failed",
            json!({"kind":"outcome","delivery":Delivery::failed(FailReason::CallNotStarted),"replayed":false,"recovered":false}),
        ),
        (
            "uncertain",
            json!({"kind":"outcome","delivery":Delivery::uncertain(UncertainReason::UnexpectedReceipt),"replayed":false,"recovered":false}),
        ),
        (
            "in_progress",
            json!({"kind":"in_progress","state":"dispatching"}),
        ),
        (
            "possible_duplicate_refused",
            json!({"kind":"possible_duplicate_refused","earlier":[]}),
        ),
        (
            "conflicting_reuse",
            json!({"kind":"conflicting_reuse","differs":["text"]}),
        ),
    ];
    for (status, result) in cases {
        let server = FixtureServer::home();
        let mut s = compose(&server);
        ready(&mut s);
        let mut r = bound_report(&s, status);
        r["result"] = result;
        r["summary"] = json!(format!("Synthetic {status} outcome"));
        server.route(MESSAGES, reply(r));
        confirm(&mut s);
        assert!(s.settle(now(2), SETTLE));
        assert_eq!(s.app.action_views[&ActionId::Send].status, status);
        assert!(s.app.action_views[&ActionId::Send].op_id.is_some());
        if matches!(status, "uncertain" | "in_progress") {
            let op = s.app.action_views[&ActionId::Send].op_id.clone().unwrap();
            let mut failed = bound_report(&s, "failed");
            failed["result"] = report("send-failed.json")["result"].clone();
            failed["summary"] = json!("Synthetic recorded failure; nothing was sent");
            server.route(&format!("{MESSAGES}/{op}"), reply(json!({
                "schema":"openwiz.send-lookup.v1","op_id":op,"target":TARGET,
                "summary":"Synthetic recorded failure", "result":{"kind":"recorded","report":failed}
            })));
            key(&mut s, Key::Ctrl('r'));
            assert!(s.settle(now(2), SETTLE));
            assert_eq!(
                s.app.action_views[&ActionId::Send].status,
                "failed",
                "authoritative lookup settles {status}"
            );
            assert!(
                s.app.attempts[0].locked(),
                "recorded failure does not authorize replay"
            );
        }
        confirm(&mut s);
        key(&mut s, Key::Ctrl('p'));
        assert!(s.settle(now(2), SETTLE));
        assert_eq!(server.writes().len(), 1);
    }
    for changed in ["target", "mode", "op_id", "hash", "bytes"] {
        let server = FixtureServer::home();
        let mut s = compose(&server);
        ready(&mut s);
        let mut r = bound_report(&s, "accepted");
        match changed {
            "target" => r["target"]["id"] = json!("thr_syn_9999"),
            "mode" => r["requested_mode"] = json!("steer"),
            "op_id" => r["op_id"] = json!("op-synthetic-other"),
            "hash" => r["text_sha256"] = json!("0".repeat(64)),
            "bytes" => r["text_bytes"] = json!(1),
            _ => unreachable!(),
        }
        server.route(MESSAGES, reply(r));
        confirm(&mut s);
        assert!(s.settle(now(2), SETTLE));
        assert_eq!(
            s.app.action_views[&ActionId::Send].status,
            "uncertain",
            "{changed}"
        );
        confirm(&mut s);
        assert!(s.settle(now(2), SETTLE));
        assert_eq!(server.writes().len(), 1);
    }
}

fn save_cells(app: &App, width: u16, height: u16, name: &str, dir: &std::ffi::OsStr) {
    use openwiz_terminal::ratatui::style::Color;
    let buffer = super::render::buffer(
        app,
        now(2),
        width,
        height,
        openwiz_terminal::render::Theme::TRUE_UNICODE,
    );
    let css = |c: Color| match c {
        Color::Rgb(r, g, b) => format!("#{r:02x}{g:02x}{b:02x}"),
        _ => "inherit".into(),
    };
    let mut html = String::from(
        "<!doctype html><meta charset=utf-8><style>body{background:#0e0f11;margin:16px}pre{font:14px/18px monospace;margin:0}</style><pre>",
    );
    for y in 0..height {
        for x in 0..width {
            let cell = &buffer[(x, y)];
            let symbol = cell
                .symbol()
                .replace('&', "&amp;")
                .replace('<', "&lt;")
                .replace('>', "&gt;");
            html.push_str(&format!(
                "<span style=\"color:{};background:{}\">{symbol}</span>",
                css(cell.fg),
                css(cell.bg)
            ));
        }
        html.push('\n');
    }
    html.push_str("</pre>");
    std::fs::write(Path::new(dir).join(format!("{name}.html")), html).unwrap();
}

#[test]
fn cp6_renders_scrollable_effects_and_prevents_tiny_confirmation() {
    let server = FixtureServer::home();
    let mut s = compose(&server);
    ready(&mut s);
    if let Some(out) = std::env::var_os("OPENWIZ_SEND_RENDER_OUT") {
        for (w, h) in [(120, 40), (80, 24), (28, 8)] {
            let mut pages = Vec::new();
            pages.push(text(&s.app, now(2), w, h));
            save_cells(&s.app, w, h, &format!("send-{w}x{h}-draft"), &out);
            for _ in 0..8 {
                key(&mut s, Key::PageDown);
                pages.push(text(&s.app, now(2), w, h));
            }
            save_cells(&s.app, w, h, &format!("send-{w}x{h}-effects"), &out);
            std::fs::write(
                Path::new(&out).join(format!("send-{w}x{h}.txt")),
                pages.join("\n\n"),
            )
            .unwrap();
        }
    }
    for (w, h) in [(120, 40), (80, 24)] {
        key(&mut s, Key::PageUp);
        let shown = text(&s.app, now(2), w, h);
        assert!(shown.contains(TARGET));
        let mut all = shown;
        for _ in 0..8 {
            key(&mut s, Key::PageDown);
            all.push_str(&text(&s.app, now(2), w, h));
        }
        assert!(all.contains("starts a turn"), "{all}");
        assert!(all.contains("reported age 12000ms"), "{all}");
        assert!(all.contains("ready"), "{all}");
    }
    text(&s.app, now(2), 20, 8);
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert!(server.writes().is_empty());
}

// Same real server + absolute fake-room-cli + private FileStore as the API
// proofs, kept local because importing their suite changes crate-root wiring.
struct Actual {
    dir: std::path::PathBuf,
    state: std::path::PathBuf,
    server: openwiz_server::Server,
}
struct Clock;
impl openwiz_core::ops::Clock for Clock {
    fn now(&self) -> openwiz_core::model::Timestamp {
        openwiz_core::model::Timestamp(super::support::T)
    }
    fn monotonic(&self) -> std::time::Instant {
        std::time::Instant::now()
    }
}
impl Actual {
    fn new() -> Self {
        use openwiz_adapter_cloudroom::source::CloudRoomSource;
        use openwiz_core::messaging::record::{SendStore, StoreError};
        use openwiz_store::FileStore;
        use std::sync::Arc;
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let dir = std::env::temp_dir().join(format!(
            "openwiz-t5-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        super::dirs::private_dir(&dir).unwrap();
        let state = dir.join("state");
        std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-room-cli"), dir.join("room-cli"))
            .unwrap();
        std::fs::write(
            dir.join("fake-room-cli.scenario"),
            Path::new(ROOT)
                .join("tests/fixtures/room-cli-0.43.1/send/scenario.json")
                .to_str()
                .unwrap(),
        )
        .unwrap();
        std::fs::write(dir.join("fake-room-cli.state"), state.to_str().unwrap()).unwrap();
        let source = Arc::new(CloudRoomSource::new(dir.join("room-cli")));
        let write = state.clone();
        let read = state.clone();
        let sending =
            openwiz_server::Sending {
                messenger: source.clone(),
                host: Some(openwiz_server::SendHost::new(HOST).unwrap()),
                open_store: Arc::new(move || {
                    Ok(Box::new(FileStore::open(&write)?) as Box<dyn SendStore>)
                }),
                open_store_read_only: Arc::new(
                    move || -> Result<Option<Box<dyn SendStore>>, StoreError> {
                        Ok(FileStore::open_read_only(&read)?
                            .map(|s| Box::new(s) as Box<dyn SendStore>))
                    },
                ),
            };
        let server = openwiz_server::start(
            openwiz_server::bind(0).unwrap(),
            openwiz_server::Config {
                allowed_host: Some(HOST.into()),
                sending: Some(sending),
                ..openwiz_server::Config::default()
            },
            source,
            Arc::new(Clock),
            Arc::new(|_| {}),
        )
        .unwrap();
        Self { dir, state, server }
    }
    fn shell(&self, target: &str, host: &str) -> Shell {
        let port = self.server.local_addr().port();
        let mut s = Shell::new(
            App::new(settings(port, Some(host))),
            client(port, Some(host)),
        );
        assert!(s.settle(now(0), SETTLE));
        s.app.detail = Some(openwiz_terminal::app::Detail::Session(target.into()));
        key(&mut s, Key::Char('m'));
        assert_eq!(s.app.open_action(), Some(ActionId::Send));
        s.app.paste(DRAFT, now(2));
        draw(&s);
        s
    }
    fn tells(&self) -> Vec<Vec<String>> {
        std::fs::read_to_string(self.dir.join("invocations.log"))
            .unwrap_or_default()
            .lines()
            .map(|l| serde_json::from_str::<Vec<String>>(l).unwrap())
            .filter(|a| a.get(1).is_some_and(|s| s == "tell"))
            .collect()
    }
}
impl Drop for Actual {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

#[test]
fn cp6_actual_fixture_server_sends_exactly_once_and_guards_paused_and_host() {
    for mode in ["queue", "steer"] {
        let actual = Actual::new();
        let mut s = actual.shell("thr_syn_0001", HOST);
        if mode == "steer" {
            key(&mut s, Key::Tab);
            key(&mut s, Key::Char(' '));
        }
        ready(&mut s);
        assert_eq!(s.app.action_views[&ActionId::Send].status, "ready");
        let op = s.app.action_views[&ActionId::Send].op_id.clone().unwrap();
        confirm(&mut s);
        assert!(s.settle(now(2), SETTLE));
        assert_eq!(s.app.action_views[&ActionId::Send].status, "accepted");
        for _ in 0..4 {
            confirm(&mut s);
            key(&mut s, Key::Ctrl('r'));
            assert!(s.settle(now(2), SETTLE));
        }
        assert_eq!(
            actual.tells(),
            vec![
                vec![
                    "thread",
                    "tell",
                    "thr_syn_0001",
                    "--mode",
                    mode,
                    "--json",
                    "--",
                    DRAFT
                ]
                .into_iter()
                .map(str::to_owned)
                .collect::<Vec<_>>()
            ]
        );
        let record: Value = serde_json::from_slice(
            &std::fs::read(actual.state.join("sends").join(format!("{op}.json"))).unwrap(),
        )
        .unwrap();
        assert_eq!(record["binding"]["target"], "thr_syn_0001");
        assert_eq!(record["binding"]["mode"], mode);
    }
    let actual = Actual::new();
    let mut s = actual.shell("thr_syn_0011", HOST);
    ready(&mut s);
    assert_eq!(
        s.app.action_views[&ActionId::Send].status,
        "needs_acknowledgement"
    );
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert!(actual.tells().is_empty());
    key(&mut s, Key::Tab);
    key(&mut s, Key::Tab);
    key(&mut s, Key::Char(' '));
    ready(&mut s);
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert_eq!(actual.tells().len(), 1);
    let actual = Actual::new();
    let mut s = actual.shell("thr_syn_0001", "wrong.example");
    ready(&mut s);
    // Preview is a loopback read; the guarded POST must be refused by the real server.
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert_eq!(s.app.action_views[&ActionId::Send].status, "refused");
    assert!(actual.tells().is_empty());
}

#[test]
fn cp6_acknowledgements_do_not_follow_a_draft_to_another_target() {
    let server = FixtureServer::home();
    let mut s = compose(&server);
    key(&mut s, Key::Tab);
    key(&mut s, Key::Tab);
    key(&mut s, Key::Char(' '));
    key(&mut s, Key::Tab);
    key(&mut s, Key::Char(' '));
    assert_eq!(field(&s, "resume_paused_queue"), "[x]");
    assert_eq!(field(&s, "accept_possible_duplicate"), "[x]");
    key(&mut s, Key::Esc);
    s.app.detail = Some(openwiz_terminal::app::Detail::Session(
        "thr_syn_9999".into(),
    ));
    key(&mut s, Key::Char('m'));
    assert_eq!(s.app.action_views[&ActionId::Send].target, "thr_syn_9999");
    assert_eq!(field(&s, "resume_paused_queue"), "[ ]");
    assert_eq!(field(&s, "accept_possible_duplicate"), "[ ]");
    assert!(server.writes().is_empty());
}

#[test]
fn cp6_actual_duplicate_gate_needs_its_own_explicit_acknowledgement() {
    use openwiz_core::messaging::record::{Claim, SendRecord, SendStore};
    use openwiz_core::messaging::send::{Delivery, UncertainReason};
    use openwiz_core::messaging::{Binding, Mode, OpId};
    use openwiz_core::model::{SessionId, Timestamp};
    for acknowledge in [false, true] {
        let actual = Actual::new();
        let store = openwiz_store::FileStore::open(&actual.state).unwrap();
        let at = Timestamp(super::support::T);
        let id = OpId::parse("op-synthetic-earlier").unwrap();
        let record = SendRecord::claimed(
            id.clone(),
            Binding::new(SessionId("thr_syn_0001".into()), Mode::Queue, DRAFT),
            DRAFT,
            at,
        );
        assert_eq!(store.claim(&record, at).unwrap(), Claim::Owned);
        store
            .update(
                &record
                    .dispatching(at)
                    .finished(Delivery::uncertain(UncertainReason::CallNotConfirmed), at),
            )
            .unwrap();
        store.release(&id);
        drop(store);
        let mut s = actual.shell("thr_syn_0001", HOST);
        if acknowledge {
            for _ in 0..3 {
                key(&mut s, Key::Tab);
            }
            key(&mut s, Key::Char(' '));
        }
        ready(&mut s);
        confirm(&mut s);
        assert!(s.settle(now(2), SETTLE));
        let expected = if acknowledge {
            "accepted"
        } else {
            "possible_duplicate_refused"
        };
        assert_eq!(s.app.action_views[&ActionId::Send].status, expected);
        assert_eq!(actual.tells().len(), usize::from(acknowledge));
        for _ in 0..3 {
            confirm(&mut s);
            key(&mut s, Key::Ctrl('r'));
            assert!(s.settle(now(2), SETTLE));
        }
        assert_eq!(actual.tells().len(), usize::from(acknowledge));
    }
}

// A TCP failure known to precede dispatch is different from a recorded
// failure or lost answer. Repeated confirmation alone still does nothing;
// a person must edit, preview and confirm a new bound operation explicitly.
#[test]
fn cp6_before_dispatch_failure_requires_an_explicit_new_draft() {
    let server = FixtureServer::home();
    let mut s = compose(&server);
    ready(&mut s);
    let old = s.app.action_views[&ActionId::Send].op_id.clone().unwrap();
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    // Reconnect the same app to a closed endpoint: a real transport failure,
    // not an injected outcome; preview and draft stay the production app's.
    s = Shell::new(s.app, client(port, Some(HOST)));
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert_eq!(s.app.action_views[&ActionId::Send].status, "failed");
    assert!(!s.app.attempts[0].locked());
    s = Shell::new(s.app, client(server.port, Some(HOST)));
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    assert!(server.writes().is_empty());
    s.app.paste("new draft", now(2));
    assert_eq!(s.app.action_views[&ActionId::Send].status, "editing");
    assert!(field(&s, "text").ends_with("new draft"));
    ready(&mut s);
    let new = s.app.action_views[&ActionId::Send].op_id.clone().unwrap();
    assert_ne!(old, new);
    // Navigation while this new draft is ready must not resurrect the
    // previous, definitively undispatched attempt.
    key(&mut s, Key::Esc);
    key(&mut s, Key::Char('m'));
    ready(&mut s);
    server.route(
        MESSAGES,
        Reply::status(403, "forbidden_origin", "Synthetic refused"),
    );
    confirm(&mut s);
    assert!(s.settle(now(2), SETTLE));
    let writes = server.writes();
    assert_eq!(writes.len(), 1);
    let body: Value = serde_json::from_slice(&writes[0].body).unwrap();
    assert_ne!(body["op_id"], old);
    assert_eq!(body["text"], format!("{DRAFT}new draft"));
}
