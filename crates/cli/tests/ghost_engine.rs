#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../../../tests/support/schema.rs"]
mod schema;

use std::ffi::OsString;
use std::fs;
use std::io::{BufReader, Read, Write};
use std::net::{IpAddr, Ipv4Addr, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Instant;

use openwiz_adapter_github::fleets::GitHubFleets;
use openwiz_adapter_github::process::Executor;
use openwiz_cli::ghost::context::ContextStore;
use openwiz_cli::ghost::engine::GhostEngine;
use openwiz_cli::ghost::http::{bind_loopback, serve_with_shutdown};
use openwiz_cli::ghost::pairing::PairingStore;
use openwiz_cli::ghost::protocol::{ContextPack, Outcome};
use openwiz_cli::ghost::stdio::run_stdio;
use serde_json::{Value, json};

fn read_json(rel: &str) -> Value {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace root");
    let path: PathBuf = root.join(rel);
    serde_json::from_str(&fs::read_to_string(&path).expect("read fixture")).expect("valid JSON")
}

fn assert_valid(root: &Value, def_name: &str, value: &Value) {
    let mut wrapped = root.clone();
    wrapped.as_object_mut().unwrap().insert(
        "$ref".to_owned(),
        Value::String(format!("#/$defs/{def_name}")),
    );
    let errs = schema::validate(&wrapped, value);
    assert!(
        errs.is_empty(),
        "{def_name} invalid:\n{}\nvalue: {value}",
        errs.join("\n")
    );
}

fn send_raw_http(port: u16, raw: &str) -> (u16, String, String) {
    let mut stream = TcpStream::connect((Ipv4Addr::LOCALHOST, port)).expect("connect loopback");
    stream.write_all(raw.as_bytes()).expect("write request");
    stream.flush().expect("flush request");
    let mut resp = String::new();
    stream.read_to_string(&mut resp).expect("read response");
    let (head, body) = resp.split_once("\r\n\r\n").expect("HTTP head/body split");
    let status: u16 = head
        .lines()
        .next()
        .and_then(|l| l.split_whitespace().nth(1))
        .and_then(|s| s.parse().ok())
        .expect("HTTP status code");
    (status, head.to_owned(), body.to_owned())
}

fn post_json(
    port: u16,
    path: &str,
    host: &str,
    origin: Option<&str>,
    token: Option<&str>,
    body: &str,
) -> (u16, String, Value) {
    let mut req =
        format!("POST {path} HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n");
    if let Some(o) = origin {
        req.push_str(&format!("Origin: {o}\r\n"));
    }
    if let Some(t) = token {
        req.push_str(&format!("Authorization: Bearer {t}\r\n"));
    }
    req.push_str(&format!("Content-Length: {}\r\n\r\n{body}", body.len()));
    let (status, head, raw_body) = send_raw_http(port, &req);
    let parsed: Value = serde_json::from_str(&raw_body)
        .unwrap_or_else(|e| panic!("non-JSON body ({status}): {e}: {raw_body}"));
    (status, head, parsed)
}

struct TestServer {
    port: u16,
    engine: Arc<Mutex<GhostEngine>>,
    shutdown: Arc<AtomicBool>,
    handle: Option<thread::JoinHandle<()>>,
}

impl TestServer {
    fn start(engine: GhostEngine) -> Self {
        let listener = bind_loopback(0).expect("bind 127.0.0.1:0");
        let addr = listener.local_addr().expect("local_addr");
        assert_eq!(addr.ip(), IpAddr::V4(Ipv4Addr::LOCALHOST));
        let engine = Arc::new(Mutex::new(engine));
        let shutdown = Arc::new(AtomicBool::new(false));
        let (e2, s2) = (Arc::clone(&engine), Arc::clone(&shutdown));
        let handle = thread::spawn(move || {
            let _ = serve_with_shutdown(listener, e2, s2);
        });
        Self {
            port: addr.port(),
            engine,
            shutdown,
            handle: Some(handle),
        }
    }

    fn issue_and_pair(&self, origin: Option<&str>) -> String {
        let code = self
            .engine
            .lock()
            .unwrap()
            .pairing_mut()
            .issue_code()
            .unwrap();
        let body = json!({"code": code, "surface": "openwiz-app"}).to_string();
        let (st, _, resp) = post_json(
            self.port,
            "/ghost/v1/pair",
            &format!("127.0.0.1:{}", self.port),
            origin,
            None,
            &body,
        );
        assert_eq!(st, 200, "pair failed: {resp}");
        resp["token"].as_str().expect("token").to_owned()
    }
}

impl Drop for TestServer {
    fn drop(&mut self) {
        self.shutdown.store(true, Ordering::Relaxed);
        if let Some(h) = self.handle.take() {
            let _ = h.join();
        }
    }
}

#[test]
fn golden_recall_cases_pass_over_http_and_stdio() {
    let s = read_json("contracts/ghost.v1.schema.json");
    let pack: ContextPack =
        serde_json::from_value(read_json("contracts/fixtures/ghost/context-pack.json")).unwrap();
    let recall_set = read_json("contracts/fixtures/ghost/recall-cases.json");
    let srv = TestServer::start(GhostEngine::with_context_pack(
        pack.clone(),
        PairingStore::in_memory(),
    ));
    let token = srv.issue_and_pair(Some("https://openwiz.dev"));
    let host = format!("127.0.0.1:{}", srv.port);
    let mut stdio_engine = GhostEngine::with_context_pack(pack, PairingStore::in_memory());
    let mut seq = 1u64;

    for case in recall_set["cases"].as_array().unwrap() {
        let case_name = case["name"].as_str().unwrap();
        for step in case["steps"].as_array().unwrap() {
            if step["expected_request"] != true {
                continue;
            }
            let prefix = step["expected_text"].as_str().unwrap();
            let expected_ghost = step["expected_ghost"].as_str();
            let req_body = json!({"session_id": "thr_syn_demo_01", "surface": "openwiz-app", "prefix": prefix, "seq": seq});

            let (status, head, http_resp) = post_json(
                srv.port,
                "/ghost/v1/complete",
                &host,
                Some("https://openwiz.dev"),
                Some(&token),
                &req_body.to_string(),
            );
            assert_eq!(status, 200, "case {case_name} HTTP status");
            assert!(head.contains("Access-Control-Allow-Origin: https://openwiz.dev"));
            assert_valid(&s, "complete_response", &http_resp);

            let line = format!(
                "{}\n",
                json!({"id": format!("req-{seq}"), "route": "complete", "body": req_body})
            );
            let mut out = Vec::new();
            run_stdio(
                &mut stdio_engine,
                &mut BufReader::new(line.as_bytes()),
                &mut out,
            )
            .unwrap();
            let stdio_resp: Value = serde_json::from_slice(&out).unwrap();
            assert_valid(&s, "stdio_response", &stdio_resp);
            assert_eq!(stdio_resp["status"], 200);
            assert_valid(&s, "complete_response", &stdio_resp["body"]);

            for (transport, resp) in [("http", &http_resp), ("stdio", &stdio_resp["body"])] {
                match expected_ghost {
                    Some(exp) => {
                        let sug = resp["suggestion"].as_object().unwrap_or_else(|| {
                            panic!("{case_name} ({transport}): expected {exp:?}, got null")
                        });
                        assert_eq!(sug["text"].as_str(), Some(exp), "{case_name} ({transport})");
                        assert_eq!(
                            sug["full_text"].as_str(),
                            Some(format!("{prefix}{exp}").as_str())
                        );
                        assert_eq!(sug["tier"].as_str(), Some("recall"));
                    }
                    None => assert!(
                        resp["suggestion"].is_null(),
                        "{case_name} ({transport}): {resp}"
                    ),
                }
            }
            seq += 1;
        }
    }

    let event = read_json("contracts/fixtures/ghost/messages.json")["feedback_request"].clone();
    let (status, _, fb_resp) = post_json(
        srv.port,
        "/ghost/v1/feedback",
        &host,
        Some("https://openwiz.dev"),
        Some(&token),
        &event.to_string(),
    );
    assert_eq!(status, 200);
    assert_valid(&s, "feedback_response", &fb_resp);
    assert_eq!(fb_resp["recorded"], true);
    assert_eq!(fb_resp["logged"], false);
    let eng = srv.engine.lock().unwrap();
    assert_eq!(eng.counters().total, 1);
    assert_eq!(eng.counters().outcome_count(Outcome::AcceptedAll), 1);
}

#[test]
fn http_enforces_host_origin_cors_token_and_loopback_only() {
    let s = read_json("contracts/ghost.v1.schema.json");
    let args: Vec<OsString> = ["serve", "--host", "0.0.0.0"]
        .iter()
        .map(OsString::from)
        .collect();
    assert_eq!(
        openwiz_cli::ghost::run(&args, &mut Vec::new(), &mut Vec::new()),
        2
    );

    let srv = TestServer::start(GhostEngine::with_context_pack(
        ContextPack::empty("ctx-0001"),
        PairingStore::in_memory(),
    ));
    let host = format!("127.0.0.1:{}", srv.port);

    let (st, _, body) = post_json(
        srv.port,
        "/ghost/v1/health",
        "evil.example:17417",
        None,
        None,
        "{}",
    );
    assert_eq!(
        (st, body["refusal"]["code"].as_str()),
        (403, Some("host_not_allowed"))
    );
    assert_valid(&s, "refusal", &body);

    for bad_origin in [
        "https://evil.example",
        "https://a.b.wizsite.pages.dev",
        "https://openwiz.dev.evil.example",
    ] {
        let (st, head, body) = post_json(
            srv.port,
            "/ghost/v1/health",
            &host,
            Some(bad_origin),
            None,
            "{}",
        );
        assert_eq!(
            (st, body["refusal"]["code"].as_str()),
            (403, Some("origin_not_allowed"))
        );
        assert!(!head.contains("Access-Control-Allow-Origin"));
    }

    for ok_origin in [
        "https://openwiz.dev",
        "https://preview-1.wizsite.pages.dev",
        "http://localhost:3000",
        "http://127.0.0.1:8080",
    ] {
        let raw = format!(
            "OPTIONS /ghost/v1/complete HTTP/1.1\r\nHost: {host}\r\nOrigin: {ok_origin}\r\n\r\n"
        );
        let (st, head, _) = send_raw_http(srv.port, &raw);
        assert_eq!(st, 204, "preflight {ok_origin}");
        assert!(head.contains(&format!("Access-Control-Allow-Origin: {ok_origin}")));
        assert!(head.contains("Access-Control-Allow-Private-Network: true"));
        assert!(head.contains("Vary: Origin"));
    }
    let (st, _, _) = send_raw_http(
        srv.port,
        &format!("OPTIONS /ghost/v1/complete HTTP/1.1\r\nHost: {host}\r\n\r\n"),
    );
    assert_eq!(st, 403);

    let (st, _, b1) = post_json(srv.port, "/ghost/v1/health", &host, None, None, "{}");
    assert_eq!(
        (st, b1["refusal"]["code"].as_str()),
        (401, Some("missing_token"))
    );
    let (st, _, b2) = post_json(
        srv.port,
        "/ghost/v1/health",
        &host,
        None,
        Some("tok_wrong"),
        "{}",
    );
    assert_eq!(
        (st, b2["refusal"]["code"].as_str()),
        (401, Some("invalid_token"))
    );

    let code = srv
        .engine
        .lock()
        .unwrap()
        .pairing_mut()
        .issue_code()
        .unwrap();
    let pair_body = json!({"code": code, "surface": "cli"}).to_string();
    let (st, _, resp) = post_json(srv.port, "/ghost/v1/pair", &host, None, None, &pair_body);
    assert_eq!(st, 200);
    assert_valid(&s, "pair_response", &resp);
    let token = resp["token"].as_str().unwrap().to_owned();
    let (st, _, replay) = post_json(srv.port, "/ghost/v1/pair", &host, None, None, &pair_body);
    assert_eq!(
        (st, replay["refusal"]["code"].as_str()),
        (401, Some("invalid_pairing_code"))
    );

    let (st, _, health) = post_json(
        srv.port,
        "/ghost/v1/health",
        &host,
        None,
        Some(&token),
        "{}",
    );
    assert_eq!(st, 200);
    assert_valid(&s, "health_response", &health);

    let (st, _, _) = send_raw_http(
        srv.port,
        &format!(
            "GET /ghost/v1/health HTTP/1.1\r\nHost: {host}\r\nAuthorization: Bearer {token}\r\n\r\n"
        ),
    );
    assert_eq!(st, 405);
    let (st, _, unk) = post_json(
        srv.port,
        "/ghost/v1/unknown",
        &host,
        None,
        Some(&token),
        "{}",
    );
    assert_eq!(
        (st, unk["refusal"]["code"].as_str()),
        (404, Some("unknown_route"))
    );
    let (st, _, bad_bench) = post_json(
        srv.port,
        "/ghost/v1/bench",
        &host,
        None,
        Some(&token),
        &json!({"source": "fixtures", "surface": "cli", "replay_path": "/tmp/x"}).to_string(),
    );
    assert_eq!(
        (st, bad_bench["refusal"]["code"].as_str()),
        (400, Some("invalid_request"))
    );

    let mut stdio_eng =
        GhostEngine::with_context_pack(ContextPack::empty("ctx-0001"), PairingStore::in_memory());
    let input = "{\"id\":\"r1\",\"route\":\"pair\",\"body\":{\"code\":\"X\",\"surface\":\"cli\"}}\nnot-json\n";
    let mut out = Vec::new();
    run_stdio(
        &mut stdio_eng,
        &mut BufReader::new(input.as_bytes()),
        &mut out,
    )
    .unwrap();
    let lines: Vec<Value> = String::from_utf8(out)
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    assert_eq!(
        (
            lines[0]["status"].as_u64(),
            lines[0]["body"]["refusal"]["code"].as_str()
        ),
        (Some(404), Some("unknown_route"))
    );
    assert!(lines[1]["id"].is_null());
    assert_eq!(lines[1]["status"], 400);
}

#[test]
fn context_pack_from_gh_matches_contract_and_rebuilds_only_on_events() {
    let s = read_json("contracts/ghost.v1.schema.json");
    let gh_calls = Arc::new(AtomicUsize::new(0));
    let gh_calls_clone = Arc::clone(&gh_calls);

    let executor = Executor::supplied(Arc::new(move |inv, _deadline| {
        gh_calls_clone.fetch_add(1, Ordering::SeqCst);
        assert_eq!(inv.argv().first().map(String::as_str), Some("issue"));
        Ok(json!([
            {
                "number": 100, "id": "I_spec_100", "title": "0.2.0 spec: ghost billing", "state": "OPEN",
                "milestone": null, "labels": [], "body": "| J7 | Use fast recall? | all recs |",
                "subIssues": {"nodes": [{"number": 101, "id": "I_t_101", "state": "OPEN", "title": "magic-link sign-in", "url": "https://example.invalid/synthetic/issues/101"}], "totalCount": 1},
                "blockedBy": {"nodes": [], "totalCount": 0}
            },
            {
                "number": 101, "id": "I_t_101", "title": "magic-link sign-in", "state": "OPEN",
                "milestone": null, "labels": [], "body": "Implement ticket 101.",
                "subIssues": {"nodes": [], "totalCount": 0}, "blockedBy": {"nodes": [], "totalCount": 0}
            }
        ])
        .to_string()
        .into_bytes())
    }));

    let store = ContextStore::from_sources(
        Some(GitHubFleets::with_executor(executor)),
        None,
        None,
        vec!["looks good, merge it".to_owned()],
    );
    assert_eq!(gh_calls.load(Ordering::SeqCst), 1);

    let mut engine = GhostEngine::new(store, PairingStore::in_memory());
    let (st, ctx1) = engine.dispatch("context", json!({}), false);
    assert_eq!(st, 200);
    assert_valid(&s, "context_response", &ctx1);
    assert_valid(&s, "context_pack", &ctx1["pack"]);
    let rev1 = ctx1["revision"].as_str().unwrap().to_owned();

    let (st, ctx2) = engine.dispatch("context", json!({"if_revision": rev1}), false);
    assert_eq!(
        (st, ctx2["unchanged"].as_bool(), ctx2["pack"].is_null()),
        (200, Some(true), true)
    );

    let (st, comp) = engine.dispatch(
        "complete",
        json!({"session_id": "s1", "surface": "cli", "prefix": "J7", "seq": 1}),
        false,
    );
    assert_eq!(
        (st, comp["suggestion"]["text"].as_str()),
        (200, Some(" all recs"))
    );
    assert_eq!(
        gh_calls.load(Ordering::SeqCst),
        1,
        "gh must not be called per keystroke"
    );

    let rev2 = engine.context_mut().refresh_records().to_owned();
    assert_ne!(rev1, rev2);
    assert_eq!(gh_calls.load(Ordering::SeqCst), 2);
}

#[test]
fn recall_answers_under_5ms_per_call_on_fixtures() {
    let pack: ContextPack =
        serde_json::from_value(read_json("contracts/fixtures/ghost/context-pack.json")).unwrap();
    let mut engine = GhostEngine::with_context_pack(pack, PairingStore::in_memory());
    for (i, prefix) in [
        "J1",
        "approve #4",
        "ship magic",
        "all r",
        "the seat bil",
        "zzq",
    ]
    .iter()
    .enumerate()
    {
        let start = Instant::now();
        let (st, resp) = engine.dispatch(
            "complete",
            json!({"session_id": "perf", "surface": "cli", "prefix": prefix, "seq": i as u64 + 1}),
            false,
        );
        let elapsed_ms = start.elapsed().as_secs_f64() * 1000.0;
        assert_eq!(st, 200);
        assert!(
            elapsed_ms < 5.0,
            "recall for {prefix:?} took {elapsed_ms:.3} ms"
        );
        if let Some(lat) = resp["suggestion"]["latency_ms"].as_f64() {
            assert!(lat < 5.0, "reported latency_ms {lat:.3} >= 5 ms");
        }
    }
}

#[test]
fn pair_cli_prints_one_time_code() {
    let args: Vec<OsString> = ["pair", "--json"].iter().map(OsString::from).collect();
    let (mut out, mut err) = (Vec::new(), Vec::new());
    let code = openwiz_cli::ghost::run(&args, &mut out, &mut err);
    assert_eq!(code, 0, "stderr={}", String::from_utf8_lossy(&err));
    let parsed: Value = serde_json::from_slice(&out).expect("valid JSON");
    assert!(parsed["code"].as_str().is_some_and(|c| !c.is_empty()));
}
