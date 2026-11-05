//! CP7: production terminal input → screen → guarded HTTP. Synthetic only.
use serde_json::{Value, json};

use openwiz_terminal::actions::ActionId;
use openwiz_terminal::app::{App, Key, KeyPress};
use openwiz_terminal::run::Shell;

use super::render::text;
use super::support::{FixtureServer, ROOT, Reply, SETTLE, client, now, settings};

const HOST: &str = "openwiz.example";
const CREATE: &str = "/api/v1/projects/prj_syn_0301/threads";
const PREVIEW: &str = "/api/v1/projects/prj_syn_0301/threads/preview";
const PROMPT: &str = "  --synthetic 'quoted' ☃\nsecond line\t ";

fn fixture(name: &str) -> Value {
    serde_json::from_slice(
        &std::fs::read(format!("{ROOT}/tests/terminal/actions/{name}.json")).unwrap(),
    )
    .unwrap()
}
fn key(shell: &mut Shell, key: Key) {
    shell.key(KeyPress::press(key), now(1));
}
fn settle(shell: &mut Shell) {
    assert!(shell.settle(now(1), SETTLE));
}
fn view(shell: &Shell) -> &openwiz_terminal::actions::ActionView {
    &shell.app.action_views[&ActionId::NewThread]
}
fn field(shell: &Shell, name: &str) -> String {
    view(shell)
        .fields
        .iter()
        .find(|f| f.0 == name)
        .unwrap()
        .2
        .clone()
}
fn recording_server() -> FixtureServer {
    let server = FixtureServer::home();
    server.route(
        "/api/v1/cloud-options",
        Reply::ok(fixture("cloud-options").to_string().into_bytes()),
    );
    server
}
fn open(server: &FixtureServer, host: Option<&str>) -> Shell {
    let mut shell = Shell::new(
        App::new(settings(server.port, host)),
        client(server.port, host),
    );
    settle(&mut shell);
    for k in [Key::Char('s'), Key::Down, Key::Char('n')] {
        key(&mut shell, k);
    }
    settle(&mut shell);
    assert_eq!(shell.app.open_action(), Some(ActionId::NewThread));
    shell
}
fn compose(shell: &mut Shell, prompt: &str) {
    // Project is seeded from the selected existing session. All settings
    // start blank. Space cycles offered choices, Tab advances the field.
    assert_eq!(field(shell, "harness"), "");
    assert_eq!(field(shell, "model"), "");
    assert_eq!(field(shell, "effort"), "");
    key(shell, Key::Tab);
    key(shell, Key::Char(' '));
    key(shell, Key::Tab);
    key(shell, Key::Char(' '));
    key(shell, Key::Tab);
    // First catalogue effort is low, then medium, then high.
    for _ in 0..3 {
        key(shell, Key::Char(' '));
    }
    key(shell, Key::Tab);
    shell.paste(prompt, now(1));
}
fn bound_fixture(name: &str, shell: &Shell, prompt: &str) -> Value {
    let mut value = fixture(name);
    value["op_id"] = json!(view(shell).op_id.as_ref().unwrap());
    value["request_id"] = json!(openwiz_core::new_thread::request_id(
        &openwiz_core::messaging::OpId::parse(view(shell).op_id.as_ref().unwrap()).unwrap()
    ));
    value["text_sha256"] = json!(openwiz_core::messaging::sha256_hex(prompt.as_bytes()));
    value["text_bytes"] = json!(prompt.len());
    value["project_ref"]["value"] = json!("prj_syn_0301");
    value["project"]["id"] = json!("prj_syn_0301");
    value["effects"]["project"]["id"] = json!("prj_syn_0301");
    value
}
fn preview(server: &FixtureServer, shell: &mut Shell, prompt: &str) {
    server.route(
        PREVIEW,
        Reply::ok(
            bound_fixture("new-preview", shell, prompt)
                .to_string()
                .into_bytes(),
        ),
    );
    key(shell, Key::Ctrl('p'));
    settle(shell);
    assert_eq!(view(shell).status, "ready", "{:?}", view(shell));
    let rendered = text(&shell.app, now(1), 120, 40);
    assert!(rendered.contains("prj_syn_0301"), "{rendered}");
    assert!(rendered.contains("syn-codex-model-01"), "{rendered}");
}
fn confirm(shell: &mut Shell) {
    text(&shell.app, now(1), 120, 40);
    let k = shell.app.confirm_key();
    key(shell, Key::Ctrl(k));
    settle(shell);
}
fn creates(server: &FixtureServer) -> Vec<super::support::Recorded> {
    server
        .requests()
        .into_iter()
        .filter(|r| r.path == CREATE)
        .collect()
}

#[test]
fn cp7_preview_cancel_and_exact_confirm() {
    let server = recording_server();
    let mut shell = open(&server, Some(HOST));
    compose(&mut shell, PROMPT);
    preview(&server, &mut shell, PROMPT);
    assert!(creates(&server).is_empty());
    assert!(
        view(&shell)
            .effects
            .iter()
            .any(|e| e.contains("full permissions"))
    );
    assert_eq!(field(&shell, "prompt"), PROMPT);
    let op = view(&shell).op_id.clone().unwrap();
    key(&mut shell, Key::Esc);
    assert!(creates(&server).is_empty());
    key(&mut shell, Key::Char('n'));
    settle(&mut shell);
    compose(&mut shell, PROMPT);
    preview(&server, &mut shell, PROMPT);
    server.route(
        CREATE,
        Reply::ok(
            bound_fixture("new-created", &shell, PROMPT)
                .to_string()
                .into_bytes(),
        ),
    );
    text(&shell.app, now(1), 120, 40);
    shell.key(
        KeyPress {
            key: Key::Ctrl('s'),
            repeat: true,
            release: false,
        },
        now(1),
    );
    settle(&mut shell);
    assert!(
        creates(&server).is_empty(),
        "held confirmation cannot create"
    );
    confirm(&mut shell);
    let requests = creates(&server);
    assert_eq!(requests.len(), 1);
    let sent: Value = serde_json::from_slice(&requests[0].body).unwrap();
    assert_ne!(sent["op_id"], op);
    assert_eq!(
        sent,
        json!({"op_id":view(&shell).op_id, "harness":"codex", "model":"syn-codex-model-01", "effort":"high", "text":PROMPT, "attachments":[]})
    );
    assert_eq!(requests[0].header("host"), [HOST]);
    assert_eq!(requests[0].header("origin"), ["https://openwiz.example"]);
    assert_eq!(requests[0].header("sec-fetch-site"), ["same-origin"]);
    assert_eq!(requests[0].header("x-openwiz-send"), ["1"]);
    for repeat in [true, false, false] {
        shell.key(
            KeyPress {
                key: Key::Ctrl('s'),
                repeat,
                release: false,
            },
            now(2),
        );
        confirm(&mut shell);
    }
    assert_eq!(creates(&server).len(), 1);
    assert_eq!(shell.app.attempts.len(), 1);
}

#[test]
fn cp7_options_and_prompt_validation_fail_closed() {
    for prompt in ["", " \t\n", "bad\0prompt", &"é".repeat(8193)] {
        let server = recording_server();
        let mut shell = open(&server, Some(HOST));
        compose(&mut shell, prompt);
        key(&mut shell, Key::Ctrl('p'));
        confirm(&mut shell);
        assert!(server.writes().is_empty(), "invalid prompt was submitted");
        assert!(view(&shell).reason.is_some());
    }
    let server = recording_server();
    let mut options = fixture("cloud-options");
    options["state"] =
        json!({"kind":"no_options","reason":"not_ready","text":"synthetic catalogue unavailable"});
    options["harnesses"] = json!([]);
    server.route(
        "/api/v1/cloud-options",
        Reply::ok(options.to_string().into_bytes()),
    );
    let mut shell = open(&server, Some(HOST));
    compose(&mut shell, "synthetic");
    key(&mut shell, Key::Ctrl('p'));
    confirm(&mut shell);
    assert!(server.writes().is_empty());
    assert!(format!("{:?}", view(&shell)).contains("synthetic catalogue unavailable"));
}

#[test]
fn cp7_changes_and_stale_preview_cannot_confirm() {
    let server = recording_server();
    let mut shell = open(&server, Some(HOST));
    compose(&mut shell, PROMPT);
    preview(&server, &mut shell, PROMPT);
    shell.paste("changed", now(1));
    confirm(&mut shell);
    assert!(creates(&server).is_empty());
    assert_ne!(view(&shell).status, "ready");
    // A response to a now-edited draft must not restore readiness.
    let updated = format!("{PROMPT}changed");
    server.route(
        PREVIEW,
        Reply::ok(
            bound_fixture("new-preview", &shell, &updated)
                .to_string()
                .into_bytes(),
        ),
    );
    key(&mut shell, Key::Ctrl('p'));
    shell.paste("again", now(1));
    settle(&mut shell);
    confirm(&mut shell);
    assert!(creates(&server).is_empty());
    assert_ne!(view(&shell).status, "ready");
}

#[test]
fn cp7_outcomes_status_navigation_and_restart_never_replay() {
    for (status, result) in [
        (
            "created",
            json!({"kind":"outcome","outcome":{"kind":"created","thread_id":"thr_syn_0021","text":"Synthetic recorded prompt"},"replayed":false,"recovered":false}),
        ),
        (
            "refused",
            json!({"kind":"outcome","outcome":{"kind":"refused","reason":"harness_not_offered","offered":[],"text":"Synthetic refused"},"replayed":false,"recovered":false}),
        ),
        (
            "failed",
            json!({"kind":"outcome","outcome":{"kind":"failed","reason":"call_not_started","text":"Synthetic failed"},"replayed":false,"recovered":false}),
        ),
        (
            "uncertain",
            json!({"kind":"outcome","outcome":{"kind":"uncertain","reason":"unexpected_receipt","text":"Synthetic uncertain"},"replayed":false,"recovered":false}),
        ),
        (
            "in_progress",
            json!({"kind":"in_progress","state":"dispatching"}),
        ),
        (
            "conflicting_reuse",
            json!({"kind":"conflicting_reuse","differs":["text"]}),
        ),
    ] {
        let server = recording_server();
        let mut shell = open(&server, Some(HOST));
        compose(&mut shell, PROMPT);
        preview(&server, &mut shell, PROMPT);
        let mut report = bound_fixture("new-created", &shell, PROMPT);
        report["status"] = json!(status);
        report["result"] = result;
        report["summary"] = json!(format!("Synthetic {status}"));
        report["start"] = Value::Null;
        server.route(CREATE, Reply::ok(report.to_string().into_bytes()));
        confirm(&mut shell);
        assert_eq!(view(&shell).status, status, "{:?}", view(&shell));
        if status == "created" {
            assert!(
                view(&shell)
                    .effects
                    .iter()
                    .any(|e| e == "Start: unknown; creation does not confirm start")
            );
        }
        let op = view(&shell).op_id.clone().unwrap();
        let path = format!("/api/v1/new-threads/{op}");
        let mut status_body = fixture("new-status");
        status_body["op_id"] = json!(op);
        status_body["result"]["report"] = report.clone();
        status_body["result"]["start"] = Value::Null;
        server.route(&path, Reply::ok(status_body.to_string().into_bytes()));
        for _ in 0..12 {
            key(&mut shell, Key::Ctrl('r'));
            settle(&mut shell);
        }
        assert_eq!(
            server.count(&path),
            12,
            "only explicit status checks; no automatic polling"
        );
        assert_eq!(creates(&server).len(), 1);
        assert_eq!(view(&shell).status, status);
        if matches!(status, "uncertain" | "in_progress") {
            let previous_effects = view(&shell).effects.clone();
            for (later_status, outcome) in [
                (
                    "refused",
                    json!({"kind":"refused","reason":"harness_not_offered","offered":[],"text":"Synthetic later refusal"}),
                ),
                (
                    "failed",
                    json!({"kind":"failed","reason":"call_not_started","text":"Synthetic later failure"}),
                ),
            ] {
                let mut later = report.clone();
                later["status"] = json!(later_status);
                later["result"] =
                    json!({"kind":"outcome","outcome":outcome,"replayed":false,"recovered":false});
                let body = recorded_status(&shell, later, Value::Null, Value::Null);
                server.route(&path, Reply::ok(body.to_string().into_bytes()));
                key(&mut shell, Key::Ctrl('r'));
                settle(&mut shell);
                assert_eq!(
                    view(&shell).status,
                    status,
                    "later {later_status} downgraded unresolved attempt"
                );
                assert_eq!(view(&shell).effects, previous_effects);
                assert!(
                    view(&shell)
                        .reason
                        .as_ref()
                        .is_some_and(|r| r.contains("did not resolve"))
                );
                assert_eq!(creates(&server).len(), 1);
            }
        }
        server.route(&path, Reply::ok(json!({"schema":"openwiz.new-thread-status.v1","op_id":op,"result":{"kind":"no_record"}}).to_string().into_bytes()));
        key(&mut shell, Key::Ctrl('r'));
        settle(&mut shell);
        assert_eq!(view(&shell).status, status);
        assert!(
            view(&shell)
                .reason
                .as_ref()
                .unwrap()
                .contains("does not prove nothing happened")
        );
        server.route(
            &path,
            Reply::status(503, "busy", "Synthetic status unavailable"),
        );
        key(&mut shell, Key::Ctrl('r'));
        settle(&mut shell);
        assert_eq!(view(&shell).status, status);
        key(&mut shell, Key::Esc);
        key(&mut shell, Key::Char('h'));
        key(&mut shell, Key::Char('s'));
        key(&mut shell, Key::Char('n'));
        settle(&mut shell);
        assert_eq!(view(&shell).op_id.as_deref(), Some(op.as_str()));
        confirm(&mut shell);
        assert_eq!(creates(&server).len(), 1);
        assert!(
            view(&shell)
                .effects
                .iter()
                .any(|e| e.contains("Restart recovery is unavailable"))
        );
        drop(shell);
        let mut restarted = open(&server, Some(HOST));
        assert!(restarted.app.attempts.is_empty());
        confirm(&mut restarted);
        key(&mut restarted, Key::Ctrl('r'));
        settle(&mut restarted);
        assert_eq!(creates(&server).len(), 1, "restart never replays a create");
    }
}

#[test]
fn cp7_guard_rejection_disconnect_and_malformed_response_lock_attempt() {
    for reply in [
        Reply::status(403, "forbidden_origin", "Synthetic guard refusal"),
        Reply::status(504, "deadline", "Synthetic deadline"),
        Reply::ok(b"{}".to_vec()),
        Reply {
            raw: Some(Vec::new()),
            ..Reply::ok(Vec::new())
        },
    ] {
        let uncertain = reply.status != 403;
        let server = recording_server();
        let mut shell = open(&server, Some(HOST));
        compose(&mut shell, PROMPT);
        preview(&server, &mut shell, PROMPT);
        server.route(CREATE, reply);
        confirm(&mut shell);
        assert_eq!(
            view(&shell).status == "uncertain",
            uncertain,
            "{:?}",
            view(&shell)
        );
        for _ in 0..3 {
            confirm(&mut shell);
            key(&mut shell, Key::Ctrl('p'));
        }
        key(&mut shell, Key::Esc);
        key(&mut shell, Key::Char('n'));
        settle(&mut shell);
        confirm(&mut shell);
        assert_eq!(creates(&server).len(), 1);
    }
    let server = recording_server();
    let mut shell = open(&server, None);
    compose(&mut shell, PROMPT);
    key(&mut shell, Key::Ctrl('p'));
    settle(&mut shell);
    confirm(&mut shell);
    assert!(server.writes().is_empty(), "no host: even preview disabled");
}

#[test]
fn cp7_project_settings_and_response_binding_fail_closed() {
    let server = recording_server();
    let mut shell = open(&server, Some(HOST));
    compose(&mut shell, PROMPT);
    preview(&server, &mut shell, PROMPT);
    // Project is the first editable field, reached from prompt by Tab.
    key(&mut shell, Key::Tab);
    key(&mut shell, Key::Char(' '));
    assert_eq!(field(&shell, "project"), "prj_syn_0302");
    confirm(&mut shell);
    assert!(creates(&server).is_empty());
    // An arbitrary project id cannot be used, even with all settings chosen.
    shell.paste("/unknown", now(1));
    key(&mut shell, Key::Ctrl('p'));
    settle(&mut shell);
    assert_eq!(server.count(PREVIEW), 1);
    // Each setting is independently rejected with a valid project/prompt
    // and otherwise offered settings. No earlier guard can mask this one.
    for (name, tabs) in [("harness", 2), ("model", 3), ("effort", 4)] {
        let server = recording_server();
        let mut shell = open(&server, Some(HOST));
        compose(&mut shell, PROMPT);
        assert_eq!(field(&shell, "project"), "prj_syn_0301");
        for _ in 0..tabs {
            key(&mut shell, Key::Tab);
        }
        shell.paste("-unavailable", now(1));
        key(&mut shell, Key::Ctrl('p'));
        settle(&mut shell);
        confirm(&mut shell);
        assert!(server.writes().is_empty(), "unoffered {name} was submitted");
        assert!(
            view(&shell)
                .reason
                .as_ref()
                .is_some_and(|r| r.contains(name)),
            "{:?}",
            view(&shell)
        );
    }

    for wrong in ["project", "prompt", "settings", "op", "effects"] {
        let server = recording_server();
        let mut shell = open(&server, Some(HOST));
        compose(&mut shell, PROMPT);
        let mut reply = bound_fixture("new-preview", &shell, PROMPT);
        match wrong {
            "project" => reply["project"]["id"] = json!("prj_syn_9999"),
            "prompt" => reply["text_sha256"] = json!("0".repeat(64)),
            "settings" => reply["requested"]["effort"] = json!("low"),
            "op" => reply["op_id"] = json!("op-synthetic-other"),
            "effects" => reply["effects"]["project"]["id"] = json!("prj_syn_9999"),
            _ => unreachable!(),
        }
        server.route(PREVIEW, Reply::ok(reply.to_string().into_bytes()));
        key(&mut shell, Key::Ctrl('p'));
        settle(&mut shell);
        confirm(&mut shell);
        assert!(
            creates(&server).is_empty(),
            "wrong {wrong} preview confirmed"
        );
    }
}

/// Actual production server and adapter; the executable is only the
/// existing fake-room-cli. Every path/state/scenario is private per case.
#[cfg(unix)]
struct ActualServer {
    root: std::path::PathBuf,
    fake: std::path::PathBuf,
    server: openwiz_server::Server,
}
#[cfg(unix)]
impl ActualServer {
    fn new(case: &str, uncertain: bool) -> Self {
        use openwiz_core::new_thread::record::NewThreadStore;
        use std::sync::Arc;
        let root = std::env::temp_dir().join(format!(
            "openwiz-t6-{}-{case}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        super::dirs::private_dir(&root).unwrap();
        let fake = root.join("fake");
        super::dirs::private_dir(&fake).unwrap();
        let state = root.join("state");
        let normal = format!("{ROOT}/tests/fixtures/room-cli-0.43.1/normal");
        let files = format!("{ROOT}/tests/fixtures/room-cli-v127/new-thread");
        let mut projects: Value =
            serde_json::from_slice(&std::fs::read(format!("{normal}/project-list.json")).unwrap())
                .unwrap();
        projects[0]["gitRemoteUrl"] =
            json!("https://github.com/synthetic-owner/synthetic-repo-0001.git");
        let spawn = if uncertain {
            json!({"any_spawn":true,"creates":true,"abort":true})
        } else {
            json!({"any_spawn":true,"creates":true,"stdout_file":format!("{files}/spawn-receipt-created.json")})
        };
        let scenario = json!({
            "scenario":"own", "description":"Synthetic CP7 actual server.", "extends":normal,
            "synthetic_assumptions":["Generated synthetic scenario with GitHub project, catalogue, receipt and start; no live sources."],
            "responses":[
                {"argv":["project","list","--json","--include-personal"],"stdout":projects.to_string()},
                {"argv":["cloud","status","--json"],"stdout_file":format!("{files}/cloud-status.json")},
                spawn,
                {"argv":["thread","show","thr_syn_0021","--json"],"stdout_file":format!("{files}/thread-show-active.json")}
            ]
        });
        std::fs::write(fake.join("scenario.json"), scenario.to_string()).unwrap();
        std::fs::write(
            fake.join("fake-room-cli.scenario"),
            fake.join("scenario.json").to_str().unwrap(),
        )
        .unwrap();
        std::fs::write(fake.join("fake-room-cli.state"), state.to_str().unwrap()).unwrap();
        std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-room-cli"), fake.join("room-cli"))
            .unwrap();
        let source = Arc::new(openwiz_adapter_cloudroom::source::CloudRoomSource::new(
            fake.join("room-cli"),
        ));
        let read_state = state.clone();
        let config = openwiz_server::Config {
            allowed_host: Some(HOST.into()),
            creating: Some(openwiz_server::Creating {
                client: source.clone(),
                host: Some(openwiz_server::SendHost::new(HOST).unwrap()),
                open_store: Arc::new(move || {
                    Ok(Box::new(openwiz_store::NewThreadFileStore::open(&state)?)
                        as Box<dyn NewThreadStore>)
                }),
                open_store_read_only: Arc::new(move || {
                    Ok(
                        openwiz_store::NewThreadFileStore::open_read_only(&read_state)?
                            .map(|s| Box::new(s) as Box<dyn NewThreadStore>),
                    )
                }),
            }),
            ..openwiz_server::Config::default()
        };
        let server = openwiz_server::start(
            openwiz_server::bind(0).unwrap(),
            config,
            source,
            Arc::new(openwiz_server::SystemClock),
            Arc::new(|_: &str| {}),
        )
        .unwrap();
        Self { root, fake, server }
    }
    fn count(&self, name: &str) -> u64 {
        std::fs::read_to_string(self.fake.join(name))
            .ok()
            .and_then(|s| s.trim().parse().ok())
            .unwrap_or(0)
    }
    fn invocations(&self) -> Vec<Vec<String>> {
        std::fs::read_to_string(self.fake.join("invocations.log"))
            .unwrap()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect()
    }
}
#[cfg(unix)]
impl Drop for ActualServer {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.root).unwrap();
    }
}

#[test]
#[cfg(unix)]
fn cp7_actual_server_creates_once_with_exact_prompt_and_settings() {
    for (case, uncertain, refused, disconnected) in [
        ("created", false, false, false),
        ("uncertain", true, false, false),
        ("guard-refused", false, true, false),
        ("http-disconnected", false, false, true),
    ] {
        let actual = ActualServer::new(case, uncertain);
        let proxy = disconnected.then(|| DisconnectProxy::new(actual.server.local_addr()));
        let port = actual.server.local_addr().port();
        let mut shell = Shell::new(
            App::new(settings(port, Some(HOST))),
            client(port, Some(HOST)),
        );
        settle(&mut shell);
        let session = shell
            .app
            .inventory
            .as_ref()
            .unwrap()
            .data
            .sessions
            .iter()
            .find(|s| s.project.as_ref().is_some_and(|p| p.0 == "prj_syn_0001"))
            .unwrap()
            .id
            .clone();
        shell.app.selected_session = Some(session);
        for k in [Key::Char('s'), Key::Char('n')] {
            key(&mut shell, k);
        }
        settle(&mut shell);
        compose(&mut shell, PROMPT);
        key(&mut shell, Key::Ctrl('p'));
        settle(&mut shell);
        assert_eq!(view(&shell).status, "ready", "{:?}", view(&shell));
        assert_eq!(actual.count("spawn-calls.count"), 0);
        let op = view(&shell).op_id.clone().unwrap();
        if refused {
            // Preview was accepted by the actual server; now the create's
            // configured Host differs, exercising the production guard.
            shell = Shell::new(shell.app, client(port, Some("foreign.example")));
        } else if let Some(proxy) = &proxy {
            // Only the create connection is cut; loopback reads keep the
            // actual server's exact Host/port check.
            shell = Shell::new(shell.app, client(proxy.port, Some(HOST)));
        }
        confirm(&mut shell);
        assert_eq!(
            view(&shell).status,
            if refused {
                "refused/failed: nothing created by this request"
            } else if uncertain || disconnected {
                "uncertain"
            } else {
                "created"
            },
            "{:?}",
            view(&shell)
        );
        if disconnected {
            shell = Shell::new(shell.app, client(port, Some(HOST)));
        }
        if !uncertain && !disconnected && !refused {
            assert!(
                view(&shell)
                    .effects
                    .iter()
                    .any(|e| e.contains("started: its first turn is running"))
            );
        }
        for _ in 0..3 {
            confirm(&mut shell);
            key(&mut shell, Key::Ctrl('r'));
            settle(&mut shell);
        }
        key(&mut shell, Key::Esc);
        key(&mut shell, Key::Char('n'));
        settle(&mut shell);
        confirm(&mut shell);
        let expected = u64::from(!refused);
        assert_eq!(actual.count("spawn-calls.count"), expected);
        assert_eq!(actual.count("threads-created.count"), expected);
        // A new terminal retains the same production server/private store;
        // opening/confirming without a draft cannot replay the old create.
        drop(shell);
        let mut restarted = Shell::new(
            App::new(settings(port, Some(HOST))),
            client(port, Some(HOST)),
        );
        settle(&mut restarted);
        let session = restarted
            .app
            .inventory
            .as_ref()
            .unwrap()
            .data
            .sessions
            .iter()
            .find(|s| s.project.as_ref().is_some_and(|p| p.0 == "prj_syn_0001"))
            .unwrap()
            .id
            .clone();
        restarted.app.selected_session = Some(session);
        key(&mut restarted, Key::Char('s'));
        key(&mut restarted, Key::Char('n'));
        settle(&mut restarted);
        confirm(&mut restarted);
        let status_read = openwiz_terminal::transport::execute(
            &client(port, Some(HOST)),
            &openwiz_terminal::actions::ActionRequest::Status { op_id: op.clone() },
        );
        let openwiz_terminal::actions::TransportResult::Report { body, .. } = status_read else {
            panic!("status read failed: {status_read:?}");
        };
        if refused {
            assert_eq!(body["result"]["kind"], "no_record");
        } else {
            assert_eq!(
                body["result"]["report"]["status"],
                if uncertain { "uncertain" } else { "created" }
            );
        }
        assert_eq!(actual.count("spawn-calls.count"), expected);
        assert_eq!(actual.count("threads-created.count"), expected);
        let calls = actual.invocations();
        let spawns: Vec<_> = calls
            .iter()
            .filter(|a| a.get(1).is_some_and(|s| s == "spawn"))
            .collect();
        if refused {
            assert!(spawns.is_empty());
            assert!(
                !actual
                    .root
                    .join("state/new-threads")
                    .join(format!("{op}.json"))
                    .exists()
            );
            continue;
        }
        let request_id = openwiz_core::new_thread::request_id(
            &openwiz_core::messaging::OpId::parse(&op).unwrap(),
        );
        assert_eq!(
            spawns,
            [&vec![
                "thread",
                "spawn",
                "--project",
                "prj_syn_0001",
                "--machine",
                "cloud",
                "--provider",
                "codex",
                "--model",
                "syn-codex-model-01",
                "--reasoning-level",
                "high",
                "--request-id",
                &request_id,
                "--json",
                "--prompt",
                PROMPT
            ]
            .into_iter()
            .map(str::to_owned)
            .collect::<Vec<_>>()]
        );
        assert!(calls.iter().all(|a| a.get(1).is_none_or(|s| s != "tell")));
        let record: Value = serde_json::from_slice(
            &std::fs::read(
                actual
                    .root
                    .join("state/new-threads")
                    .join(format!("{op}.json")),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(record["text_bytes"], PROMPT.len());
        assert_eq!(
            record["text"],
            if uncertain {
                json!(PROMPT)
            } else {
                Value::Null
            }
        );
    }
}

// A stopped preview may have no resolved project/effects. The useful
// server refusal must survive; T3 transport tests do not check action text.
#[test]
fn cp7_stopped_preview_keeps_its_reason() {
    let server = recording_server();
    let mut shell = open(&server, Some(HOST));
    compose(&mut shell, PROMPT);
    let mut reply = bound_fixture("new-preview", &shell, PROMPT);
    reply["project"] = Value::Null;
    reply["effects"] = Value::Null;
    reply["verdict"] = json!({"kind":"stopped","outcome":{"kind":"refused","reason":"project_no_github_remote","offered":[],"text":"Synthetic project has no GitHub remote"}});
    server.route(PREVIEW, Reply::ok(reply.to_string().into_bytes()));
    key(&mut shell, Key::Ctrl('p'));
    settle(&mut shell);
    assert_eq!(
        view(&shell).reason.as_deref(),
        Some("Synthetic project has no GitHub remote")
    );
    confirm(&mut shell);
    assert!(creates(&server).is_empty());
}

// A valid-schema response can still name another thread's start stage.
// Never describe the requested create as started from that evidence.
#[test]
fn cp7_foreign_start_never_proves_this_thread_started() {
    let server = recording_server();
    let mut shell = open(&server, Some(HOST));
    compose(&mut shell, PROMPT);
    preview(&server, &mut shell, PROMPT);
    let mut reply = bound_fixture("new-created", &shell, PROMPT);
    reply["start"]["thread_id"] = json!("thr_syn_9999");
    server.route(CREATE, Reply::ok(reply.to_string().into_bytes()));
    confirm(&mut shell);
    assert_eq!(view(&shell).status, "created");
    assert!(
        !view(&shell)
            .effects
            .iter()
            .any(|e| e.contains("started: its first turn is running"))
    );
    assert!(
        view(&shell)
            .effects
            .iter()
            .any(|e| e.contains("Start: unknown"))
    );
}

fn save_render(name: &str, buffer: &openwiz_terminal::ratatui::buffer::Buffer) {
    let Some(dir) = std::env::var_os("OPENWIZ_T6_RENDER_OUT") else {
        return;
    };
    let dir = std::path::PathBuf::from(dir);
    std::fs::write(
        dir.join(format!("{name}.txt")),
        super::render::rows(buffer).join("\n"),
    )
    .unwrap();
    let mut html = String::from(
        "<!doctype html><meta charset=utf-8><style>body{margin:0;background:#101014}pre{font:14px/18px monospace;margin:16px}</style><pre>",
    );
    let rgb = |color| match color {
        openwiz_terminal::ratatui::style::Color::Rgb(r, g, b) => format!("#{r:02x}{g:02x}{b:02x}"),
        _ => "#bbbbbb".into(),
    };
    for y in 0..buffer.area.height {
        for x in 0..buffer.area.width {
            let cell = &buffer[(x, y)];
            let escaped = cell
                .symbol()
                .replace('&', "&amp;")
                .replace('<', "&lt;")
                .replace('>', "&gt;");
            html.push_str(&format!(
                "<span style=\"color:{};background:{}\">{escaped}</span>",
                rgb(cell.fg),
                rgb(cell.bg)
            ));
        }
        html.push('\n');
    }
    html.push_str("</pre>");
    std::fs::write(dir.join(format!("{name}.html")), html).unwrap();
}

// CP4/CP7 display boundary: pane scroll reaches every exact effect and the
// outcome at normal/narrow sizes; tiny targets never authorize creation.
#[test]
fn cp7_render_sizes_scroll_effects_and_outcomes() {
    use openwiz_terminal::render::Theme;
    let server = recording_server();
    let mut shell = open(&server, Some(HOST));
    compose(&mut shell, PROMPT);
    preview(&server, &mut shell, PROMPT);
    let effects = view(&shell).effects.clone();
    for (width, height) in [(120, 40), (80, 24)] {
        let mut screens = Vec::new();
        for page in 0..30 {
            let buffer =
                super::render::buffer(&shell.app, now(1), width, height, Theme::TRUE_UNICODE);
            save_render(&format!("ready-{width}x{height}-p{page}"), &buffer);
            screens.push(super::render::rows(&buffer).join("\n"));
            if shell.app.action_offset.get() == shell.app.action_max.get() {
                break;
            }
            key(&mut shell, Key::PageDown);
        }
        let all: String = screens
            .join("\n")
            .chars()
            .filter(|c| !c.is_whitespace())
            .collect();
        for effect in &effects {
            assert!(
                all.contains(
                    &effect
                        .chars()
                        .filter(|c| !c.is_whitespace())
                        .collect::<String>()
                ),
                "{width}x{height} missing {effect}"
            );
        }
        assert!(screens.iter().all(|s| s.contains("prj_syn_0301")));
        for _ in 0..30 {
            key(&mut shell, Key::PageUp);
        }
    }
    let tiny = super::render::buffer(&shell.app, now(1), 20, 6, Theme::TRUE_UNICODE);
    save_render("ready-20x6", &tiny);
    assert!(!shell.app.target_shown.get());
    key(&mut shell, Key::Ctrl('s'));
    settle(&mut shell);
    assert!(creates(&server).is_empty());
    server.route(
        CREATE,
        Reply::ok(
            bound_fixture("new-created", &shell, PROMPT)
                .to_string()
                .into_bytes(),
        ),
    );
    confirm(&mut shell);
    for (width, height) in [(120, 40), (80, 24)] {
        let mut combined = String::new();
        for page in 0..30 {
            let buffer =
                super::render::buffer(&shell.app, now(1), width, height, Theme::TRUE_UNICODE);
            save_render(&format!("created-{width}x{height}-p{page}"), &buffer);
            combined.push_str(&super::render::rows(&buffer).join("\n"));
            if shell.app.action_offset.get() == shell.app.action_max.get() {
                break;
            }
            key(&mut shell, Key::PageDown);
        }
        let words: String = combined.chars().filter(|c| !c.is_whitespace()).collect();
        assert!(words.contains("created:promptrecorded;started"));
        assert!(words.contains("Ctrl-Rstatus(readonly)"));
        for _ in 0..30 {
            key(&mut shell, Key::PageUp);
        }
    }
}

#[test]
fn cp7_start_stages_and_reported_configuration_remain_separate() {
    for (kind, stage) in [
        (
            "waiting_to_start",
            json!({"kind":"waiting_to_start","text":"Synthetic waiting to start"}),
        ),
        (
            "idle_as_reported",
            json!({"kind":"idle_as_reported","text":"Synthetic idle; first prompt not confirmed"}),
        ),
        (
            "unknown",
            json!({"kind":"unknown","reason":"Synthetic read failed","text":"Synthetic start unknown"}),
        ),
        (
            "start_failed",
            json!({"kind":"start_failed","last_error":{"known":"Synthetic provider failed to boot"},"text":"Synthetic start failed"}),
        ),
    ] {
        let server = recording_server();
        let mut shell = open(&server, Some(HOST));
        compose(&mut shell, PROMPT);
        preview(&server, &mut shell, PROMPT);
        let mut reply = bound_fixture("new-created", &shell, PROMPT);
        let expected_stage = stage["text"].as_str().unwrap().to_owned();
        reply["start"]["stage"] = stage;
        reply["start"]["reported"]["model"]["reported"] = json!({"known":"syn-codex-model-02"});
        reply["start"]["reported"]["model"]["differs_from_requested"] = json!({"known":true});
        reply["start"]["reported"]["model"]["text"] =
            json!("Synthetic model syn-codex-model-02 differs from requested syn-codex-model-01");
        server.route(CREATE, Reply::ok(reply.to_string().into_bytes()));
        confirm(&mut shell);
        assert_eq!(view(&shell).status, "created");
        assert_eq!(field(&shell, "model"), "syn-codex-model-01");
        assert!(
            view(&shell)
                .effects
                .contains(&format!("Start: {expected_stage}")),
            "{kind}: {:?}",
            view(&shell)
        );
        assert!(
            !view(&shell)
                .effects
                .iter()
                .any(|e| e.contains("started: its first turn is running")),
            "{kind}: {:?}",
            view(&shell)
        );
        assert!(
            view(&shell)
                .effects
                .iter()
                .any(|e| e.contains("syn-codex-model-02 differs"))
        );
        assert!(
            view(&shell)
                .effects
                .iter()
                .any(|e| e.contains("never the serving model"))
        );
        if kind == "start_failed" {
            assert!(
                view(&shell)
                    .effects
                    .iter()
                    .any(|e| e.contains("Synthetic provider failed to boot"))
            );
        }
    }
}

// Self-review: diagnostics describe the latest successful read, without
// accumulating old failures or hiding source gaps. Existing happy statuses
// cannot expose either bug because they contain no diagnostic gap at all.
fn recorded_status(shell: &Shell, report: Value, start: Value, observations: Value) -> Value {
    json!({"schema":"openwiz.new-thread-status.v1", "op_id":view(shell).op_id, "result":{"kind":"recorded","report":report,"start":start,"observations":observations}})
}
fn status_route(server: &FixtureServer, shell: &Shell, body: Value) {
    server.route(
        &format!(
            "/api/v1/new-threads/{}",
            view(shell).op_id.as_ref().unwrap()
        ),
        Reply::ok(body.to_string().into_bytes()),
    );
}

#[test]
fn cp7_diagnostics_start_gaps_are_current() {
    let server = recording_server();
    let mut shell = open(&server, Some(HOST));
    compose(&mut shell, PROMPT);
    preview(&server, &mut shell, PROMPT);
    let mut report = bound_fixture("new-created", &shell, PROMPT);
    let fresh_start = report["start"].clone();
    report["start"]["stage"] = json!({"kind":"unknown","reason":"Synthetic failed show","text":"Synthetic start unavailable"});
    report["start"]["gaps"] =
        json!([{"subject":"thread show","detail":"Synthetic earlier thread-show failure"}]);
    server.route(CREATE, Reply::ok(report.to_string().into_bytes()));
    confirm(&mut shell);
    assert!(
        view(&shell)
            .effects
            .iter()
            .any(|e| e.contains("Synthetic earlier thread-show failure"))
    );
    report["start"] = Value::Null;
    status_route(
        &server,
        &shell,
        recorded_status(&shell, report, fresh_start, Value::Null),
    );
    key(&mut shell, Key::Ctrl('r'));
    settle(&mut shell);
    assert!(
        !view(&shell)
            .effects
            .iter()
            .any(|e| e.contains("Synthetic earlier thread-show failure")),
        "{:?}",
        view(&shell)
    );
    assert!(
        view(&shell)
            .effects
            .iter()
            .any(|e| e.contains("started: its first turn is running"))
    );
    assert_eq!(creates(&server).len(), 1);
}

#[test]
fn cp7_diagnostics_observations_do_not_accumulate() {
    let server = recording_server();
    let mut shell = open(&server, Some(HOST));
    compose(&mut shell, PROMPT);
    preview(&server, &mut shell, PROMPT);
    let mut report = bound_fixture("new-created", &shell, PROMPT);
    report["status"] = json!("uncertain");
    report["result"] = json!({"kind":"outcome","outcome":{"kind":"uncertain","reason":"unexpected_receipt","text":"Synthetic uncertain"},"replayed":false,"recovered":false});
    report["start"] = Value::Null;
    server.route(CREATE, Reply::ok(report.to_string().into_bytes()));
    confirm(&mut shell);
    let observations = json!({"read_at":1700000600000_i64,"threads":[],"text":openwiz_core::new_thread::status::OBSERVATIONS_ONLY,"gaps":[]});
    status_route(
        &server,
        &shell,
        recorded_status(&shell, report, Value::Null, observations),
    );
    for _ in 0..3 {
        key(&mut shell, Key::Ctrl('r'));
        settle(&mut shell);
    }
    assert_eq!(view(&shell).status, "uncertain");
    assert_eq!(
        view(&shell)
            .effects
            .iter()
            .filter(|e| e.contains("observations only:"))
            .count(),
        1
    );
    assert_eq!(creates(&server).len(), 1);
}

#[test]
fn cp7_diagnostics_preview_and_observation_gaps_are_visible() {
    let server = recording_server();
    let mut shell = open(&server, Some(HOST));
    compose(&mut shell, PROMPT);
    let mut preview = bound_fixture("new-preview", &shell, PROMPT);
    preview["gaps"] = json!([{"subject":"source","detail":"Synthetic preview source gap"}]);
    server.route(PREVIEW, Reply::ok(preview.to_string().into_bytes()));
    key(&mut shell, Key::Ctrl('p'));
    settle(&mut shell);
    assert!(
        view(&shell)
            .effects
            .iter()
            .any(|e| e.contains("Synthetic preview source gap"))
    );
    server.route(CREATE, Reply::ok(b"{}".to_vec()));
    confirm(&mut shell);
    let mut report = bound_fixture("new-created", &shell, PROMPT);
    report["status"] = json!("uncertain");
    report["result"] = json!({"kind":"outcome","outcome":{"kind":"uncertain","reason":"unexpected_receipt","text":"Synthetic uncertain"},"replayed":false,"recovered":false});
    report["start"] = Value::Null;
    let mut observations = json!({"read_at":1700000600000_i64,"threads":[],"text":openwiz_core::new_thread::status::OBSERVATIONS_ONLY,"gaps":[{"subject":"thread list","detail":"Synthetic observation read failed"}]});
    status_route(
        &server,
        &shell,
        recorded_status(&shell, report.clone(), Value::Null, observations.clone()),
    );
    key(&mut shell, Key::Ctrl('r'));
    settle(&mut shell);
    assert_eq!(view(&shell).status, "uncertain");
    assert!(
        view(&shell)
            .effects
            .iter()
            .any(|e| e.contains("Synthetic observation read failed"))
    );
    observations["gaps"] = json!([]);
    status_route(
        &server,
        &shell,
        recorded_status(&shell, report, Value::Null, observations),
    );
    key(&mut shell, Key::Ctrl('r'));
    settle(&mut shell);
    assert!(
        !view(&shell)
            .effects
            .iter()
            .any(|e| e.contains("Synthetic observation read failed"))
    );
    assert_eq!(view(&shell).status, "uncertain");
    assert_eq!(creates(&server).len(), 1);
}

/// Forwards real HTTP to the production fixture server and discards only
/// the create response after that server has finished. No scripted report.
/// A bounded single worker is stopped and joined on Drop.
#[cfg(unix)]
struct DisconnectProxy {
    port: u16,
    stopped: std::sync::Arc<std::sync::atomic::AtomicBool>,
    worker: Option<std::thread::JoinHandle<()>>,
}
#[cfg(unix)]
impl DisconnectProxy {
    fn new(target: std::net::SocketAddr) -> Self {
        use std::io::{Read, Write};
        use std::sync::Arc;
        use std::sync::atomic::{AtomicBool, Ordering};
        use std::time::Duration;
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let stopped = Arc::new(AtomicBool::new(false));
        let stop = stopped.clone();
        let worker = std::thread::spawn(move || {
            for incoming in listener.incoming() {
                let mut stream = incoming.unwrap();
                if stop.load(Ordering::SeqCst) {
                    break;
                }
                stream
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                let mut request = Vec::new();
                let mut chunk = [0; 4096];
                let end = loop {
                    if let Some(i) = request.windows(4).position(|w| w == b"\r\n\r\n") {
                        break i + 4;
                    }
                    let n = stream.read(&mut chunk).unwrap();
                    assert!(n > 0 && request.len() < 1_000_000);
                    request.extend_from_slice(&chunk[..n]);
                };
                let head = std::str::from_utf8(&request[..end]).unwrap();
                let create = head.starts_with("POST /api/v1/projects/")
                    && head.lines().next().unwrap().ends_with("/threads HTTP/1.1");
                let length: usize = head
                    .lines()
                    .filter_map(|line| line.split_once(':'))
                    .find(|(key, _)| key.eq_ignore_ascii_case("content-length"))
                    .map_or(0, |(_, n)| n.trim().parse().unwrap());
                while request.len() < end + length {
                    let n = stream.read(&mut chunk).unwrap();
                    assert!(n > 0 && request.len() < 1_000_000);
                    request.extend_from_slice(&chunk[..n]);
                }
                let mut upstream = std::net::TcpStream::connect(target).unwrap();
                upstream
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                upstream.write_all(&request).unwrap();
                let mut response = Vec::new();
                upstream.read_to_end(&mut response).unwrap();
                if !create {
                    stream.write_all(&response).unwrap();
                }
                // Dropping this client connection gives the terminal EOF
                // after the actual create, with its recorded outcome kept.
            }
        });
        Self {
            port,
            stopped,
            worker: Some(worker),
        }
    }
}
#[cfg(unix)]
impl Drop for DisconnectProxy {
    fn drop(&mut self) {
        self.stopped
            .store(true, std::sync::atomic::Ordering::SeqCst);
        let _ = std::net::TcpStream::connect(("127.0.0.1", self.port));
        self.worker.take().unwrap().join().unwrap();
    }
}

/// R1: competing production actions may supersede a queued read, but the
/// displaced action must remain able to read its retained operation. T3's
/// single-action tests cannot expose a read owned by another action.
#[test]
fn cp7_r1_superseded_cross_action_status_can_be_requested_again() {
    use openwiz_terminal::app::{Completion, Job};
    const MESSAGES: &str = "/api/v1/sessions/thr_syn_0301/messages";
    for new_first in [true, false] {
        let server = recording_server();
        let mut shell = open(&server, Some(HOST));
        compose(&mut shell, PROMPT);
        preview(&server, &mut shell, PROMPT);
        let mut created = bound_fixture("new-created", &shell, PROMPT);
        server.route(CREATE, Reply::ok(created.to_string().into_bytes()));
        confirm(&mut shell);
        let new_op = view(&shell).op_id.clone().unwrap();
        let new_path = format!("/api/v1/new-threads/{new_op}");
        created["start"] = Value::Null;
        server.route(
            &new_path,
            Reply::ok(
                recorded_status(&shell, created, Value::Null, Value::Null)
                    .to_string()
                    .into_bytes(),
            ),
        );
        key(&mut shell, Key::Esc);
        key(&mut shell, Key::Enter);
        settle(&mut shell);
        let mut send_preview = fixture("send-preview");
        send_preview["target"]["id"] = json!("thr_syn_0301");
        server.route(
            "/api/v1/sessions/thr_syn_0301/preview?mode=queue",
            Reply::ok(send_preview.to_string().into_bytes()),
        );
        key(&mut shell, Key::Char('m'));
        shell.paste("Synthetic R1 message", now(1));
        key(&mut shell, Key::Ctrl('p'));
        settle(&mut shell);
        assert_eq!(shell.app.action_views[&ActionId::Send].status, "ready");
        let send_op = shell.app.action_views[&ActionId::Send]
            .op_id
            .clone()
            .unwrap();
        let mut sent = fixture("send-accepted");
        sent["target"]["id"] = json!("thr_syn_0301");
        sent["op_id"] = json!(send_op);
        sent["text_bytes"] = json!(20);
        sent["text_sha256"] = json!(openwiz_core::messaging::sha256_hex(b"Synthetic R1 message"));
        server.route(MESSAGES, Reply::ok(sent.to_string().into_bytes()));
        confirm(&mut shell);
        assert_eq!(shell.app.action_views[&ActionId::Send].status, "accepted");
        let send_path = format!("{MESSAGES}/{send_op}");
        server.route(&send_path, Reply::ok(json!({"schema":"openwiz.send-lookup.v1","target":"thr_syn_0301","op_id":send_op,"summary":"Synthetic R1 lookup","result":{"kind":"recorded","report":sent}}).to_string().into_bytes()));
        key(&mut shell, Key::Esc);
        let attempts = shell.app.attempts.clone();
        assert_eq!(attempts.len(), 2);
        assert!(attempts.iter().all(|a| a.locked()));

        // Reserve both real scheduler slots without starting their HTTP
        // workers. The test owns these jobs/completions, so no sleep or
        // timing race can decide whether the action reads were queued.
        shell.app.refresh(now(1));
        let held = shell.app.jobs(now(1));
        assert_eq!(held.len(), 2);
        assert_eq!(shell.app.reads_in_flight(), 2);
        let (first, second, first_path, second_path) = if new_first {
            ('n', 'm', &new_path, &send_path)
        } else {
            ('m', 'n', &send_path, &new_path)
        };
        for k in [
            Key::Char(first),
            Key::Ctrl('r'),
            Key::Esc,
            Key::Char(second),
            Key::Ctrl('r'),
        ] {
            shell.app.key(KeyPress::press(k), now(1));
            assert!(
                shell.app.jobs(now(1)).is_empty(),
                "occupied slots must hold the queued reads"
            );
            assert_eq!(shell.app.reads_in_flight(), 2);
        }
        assert_eq!(server.count(first_path), 0);
        assert_eq!(server.count(second_path), 0);
        for job in held {
            let Job::Read { id, path, .. } = job else {
                panic!("background job must be a read");
            };
            let result = client(server.port, Some(HOST)).get(&path);
            shell.app.complete(Completion::Read { id, result }, now(1));
        }
        settle(&mut shell);
        assert_eq!(
            server.count(first_path),
            0,
            "superseded read must not dispatch"
        );
        assert_eq!(
            server.count(second_path),
            1,
            "latest queued read dispatches exactly once"
        );
        assert_eq!(shell.app.reads_in_flight(), 0);
        key(&mut shell, Key::Esc);
        key(&mut shell, Key::Char(first));
        key(&mut shell, Key::Ctrl('r'));
        settle(&mut shell);
        assert_eq!(
            server.count(first_path),
            1,
            "displaced action must be able to read status again"
        );
        assert_eq!(server.count(second_path), 1);
        assert_eq!(
            shell.app.action_views[&ActionId::NewThread].status,
            "created"
        );
        assert_eq!(shell.app.action_views[&ActionId::Send].status, "accepted");
        for (before, after) in attempts.iter().zip(&shell.app.attempts) {
            assert_eq!(after.request, before.request);
            assert_eq!(after.op_id, before.op_id);
            assert_eq!(after.outcome, before.outcome);
            assert!(after.locked());
        }
        confirm(&mut shell);
        key(&mut shell, Key::Esc);
        key(&mut shell, Key::Char(second));
        confirm(&mut shell);
        assert_eq!(creates(&server).len(), 1);
        assert_eq!(server.count(MESSAGES), 1);
        assert!(server.max_in_flight() <= 2);
    }
}
