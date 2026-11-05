//! The loopback transport: exact headers, the existing routes for every
//! action request, guarded requests only with the configured host, no retry,
//! and bounded framing. Fixture HTTP only.

use std::time::Duration;

use openwiz_terminal::actions::{ActionRequest, Mode, NewThreadInput, SendInput, TransportResult};
use openwiz_terminal::config::{self, Invocation, Settings};
use openwiz_terminal::http::{BODY_MAX_BYTES, Failure};
use openwiz_terminal::transport::execute;

use super::support::{FixtureServer, Reply, client};

const HOST: &str = "openwiz.example";

fn send_input() -> SendInput {
    SendInput {
        target: "thr_syn_0301".into(),
        text: "  exact bytes\n\twith spaces  ".into(),
        mode: Mode::Queue,
        op_id: "op-syn-t3-1".into(),
        resume_paused_queue: false,
        accept_possible_duplicate: true,
    }
}

fn new_input() -> NewThreadInput {
    NewThreadInput {
        project_id: "prj_syn_0301".into(),
        harness: "codex".into(),
        model: "synthetic-model-a".into(),
        effort: "high".into(),
        prompt: "Synthetic prompt".into(),
        op_id: "op-syn-t3-2".into(),
    }
}

#[test]
fn reads_use_loopback_host_and_one_request_per_connection() {
    let server = FixtureServer::home();
    let reply = client(server.port, Some(HOST))
        .get("/api/v1/inventory")
        .unwrap();
    assert_eq!(reply.status, 200);
    let request = &server.requests()[0];
    assert_eq!(request.method, "GET");
    assert_eq!(
        request.header("Host"),
        [format!("127.0.0.1:{}", server.port).as_str()]
    );
    assert_eq!(request.header("Connection"), ["close"]);
    assert!(request.header("Origin").is_empty() && request.header("X-OpenWiz-Send").is_empty());
}

#[test]
fn every_action_request_uses_its_existing_route_and_typed_body() {
    let server = FixtureServer::start();
    let client = client(server.port, Some(HOST));
    let cases = [
        (
            ActionRequest::SendPreview {
                target: "thr_syn_0301".into(),
                mode: Mode::Steer,
            },
            "GET",
            "/api/v1/sessions/thr_syn_0301/preview?mode=steer",
        ),
        (
            ActionRequest::Send(send_input()),
            "POST",
            "/api/v1/sessions/thr_syn_0301/messages",
        ),
        (
            ActionRequest::Lookup {
                target: "thr_syn_0301".into(),
                op_id: "op-syn-t3-1".into(),
            },
            "GET",
            "/api/v1/sessions/thr_syn_0301/messages/op-syn-t3-1",
        ),
        (ActionRequest::Options, "GET", "/api/v1/cloud-options"),
        (
            ActionRequest::NewPreview(new_input()),
            "POST",
            "/api/v1/projects/prj_syn_0301/threads/preview",
        ),
        (
            ActionRequest::Create(new_input()),
            "POST",
            "/api/v1/projects/prj_syn_0301/threads",
        ),
        (
            ActionRequest::Status {
                op_id: "op-syn-t3-2".into(),
            },
            "GET",
            "/api/v1/new-threads/op-syn-t3-2",
        ),
    ];
    for (request, method, path) in &cases {
        let _ = execute(&client, request);
        let recorded = server.requests().pop().unwrap();
        assert_eq!(
            (recorded.method.as_str(), recorded.path.as_str()),
            (*method, *path)
        );
        if *method == "POST" {
            assert_eq!(recorded.header("Host"), [HOST]);
            assert_eq!(
                recorded.header("Origin"),
                [format!("https://{HOST}").as_str()]
            );
            assert_eq!(recorded.header("Sec-Fetch-Site"), ["same-origin"]);
            assert_eq!(recorded.header("X-OpenWiz-Send"), ["1"]);
            assert_eq!(recorded.header("Content-Type"), ["application/json"]);
            assert_eq!(
                recorded.header("Content-Length"),
                [recorded.body.len().to_string().as_str()]
            );
        }
    }
    assert_eq!(
        server.requests().len(),
        cases.len(),
        "each request once, no retry"
    );
    let bodies: Vec<serde_json::Value> = server
        .writes()
        .iter()
        .map(|r| serde_json::from_slice(&r.body).unwrap())
        .collect();
    assert_eq!(
        bodies[0],
        serde_json::json!({"op_id": "op-syn-t3-1", "mode": "queue", "text": "  exact bytes\n\twith spaces  ", "resume_paused_queue": false, "accept_possible_duplicate": true})
    );
    assert_eq!(
        bodies[1],
        serde_json::json!({"op_id": "op-syn-t3-2", "harness": "codex", "model": "synthetic-model-a", "effort": "high", "text": "Synthetic prompt", "attachments": []})
    );
}

#[test]
fn guarded_requests_need_the_configured_host_and_are_never_retried() {
    let server = FixtureServer::start();
    let result = execute(
        &client(server.port, None),
        &ActionRequest::Send(send_input()),
    );
    assert!(
        matches!(result, TransportResult::FailedBeforeDispatch { .. }),
        "{result:?}"
    );
    assert!(server.requests().is_empty(), "nothing reached the server");
    // A bad id never becomes a path.
    let mut bad = send_input();
    bad.target = "../thr".into();
    let result = execute(&client(server.port, Some(HOST)), &ActionRequest::Send(bad));
    assert!(matches!(
        result,
        TransportResult::FailedBeforeDispatch { .. }
    ));
    assert!(server.requests().is_empty());
    // Refusals keep their status; a deadline is uncertain; neither retries.
    let path = "/api/v1/sessions/thr_syn_0301/messages";
    server.route(
        path,
        Reply::status(421, "misdirected", "this host name is not served here"),
    );
    let result = execute(
        &client(server.port, Some(HOST)),
        &ActionRequest::Send(send_input()),
    );
    assert_eq!(
        result,
        TransportResult::Refused {
            http_status: 421,
            reason: "HTTP 421 misdirected: this host name is not served here".into()
        }
    );
    server.route(
        path,
        Reply::status(504, "deadline", "no result within the request deadline"),
    );
    let result = execute(
        &client(server.port, Some(HOST)),
        &ActionRequest::Send(send_input()),
    );
    assert!(
        matches!(result, TransportResult::UnknownAfterDispatch { .. }),
        "{result:?}"
    );
    server.route(path, Reply::ok(b"{\"schema\":\"something.else\"}".to_vec()));
    let result = execute(
        &client(server.port, Some(HOST)),
        &ActionRequest::Send(send_input()),
    );
    assert!(
        matches!(result, TransportResult::UnknownAfterDispatch { .. }),
        "{result:?}"
    );
    server.route(
        path,
        Reply::ok(b"{}".to_vec()).delayed(Duration::from_millis(1500)),
    );
    let mut slow = client(server.port, Some(HOST));
    slow.deadline = Duration::from_millis(500);
    let result = execute(&slow, &ActionRequest::Send(send_input()));
    assert!(
        matches!(result, TransportResult::UnknownAfterDispatch { .. }),
        "{result:?}"
    );
    assert_eq!(
        server.count(path),
        4,
        "one request per attempt, never a retry"
    );
    // No server: nothing dispatched.
    let closed = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = closed.local_addr().unwrap().port();
    drop(closed);
    let result = execute(
        &client(port, Some(HOST)),
        &ActionRequest::Send(send_input()),
    );
    assert!(
        matches!(result, TransportResult::FailedBeforeDispatch { .. }),
        "{result:?}"
    );
}

fn raw(server: &FixtureServer, bytes: Vec<u8>) -> Result<openwiz_terminal::http::Reply, Failure> {
    server.route(
        "/api/v1/inventory",
        Reply {
            raw: Some(bytes),
            ..Reply::ok(Vec::new())
        },
    );
    client(server.port, None).get("/api/v1/inventory")
}

#[test]
fn malformed_oversized_and_redirected_answers_are_refused() {
    let server = FixtureServer::start();
    let many: String = (0..65).map(|i| format!("X-{i}: y\r\n")).collect();
    for (name, bytes) in [
        (
            "truncated",
            b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\n{}".to_vec(),
        ),
        (
            "too long",
            b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\n{}".to_vec(),
        ),
        (
            "two lengths",
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}".to_vec(),
        ),
        (
            "chunked",
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n".to_vec(),
        ),
        (
            "compressed",
            b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 2\r\n\r\n{}".to_vec(),
        ),
        (
            "redirect",
            b"HTTP/1.1 302 Found\r\nLocation: http://elsewhere/\r\nContent-Length: 0\r\n\r\n"
                .to_vec(),
        ),
        (
            "oversized",
            format!(
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n",
                BODY_MAX_BYTES + 1
            )
            .into_bytes(),
        ),
        (
            "big head",
            format!("HTTP/1.1 200 OK\r\nX: {}\r\n\r\n", "y".repeat(17 * 1024)).into_bytes(),
        ),
        (
            "many headers",
            format!("HTTP/1.1 200 OK\r\n{many}Content-Length: 2\r\n\r\n{{}}").into_bytes(),
        ),
        ("not http", b"SSH-2.0-x\r\n\r\n".to_vec()),
    ] {
        let result = raw(&server, bytes);
        assert!(result.is_err(), "{name}: {result:?}");
    }
    let ok = raw(
        &server,
        b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}".to_vec(),
    )
    .unwrap();
    assert_eq!(ok.body, b"{}");
    // Content-Length is one of the headers; the status and blank line are not.
    for (count, accepted) in [(63, true), (64, true), (65, false)] {
        let headers: String = (0..count - 1).map(|i| format!("X-{i}: y\r\n")).collect();
        let result = raw(
            &server,
            format!("HTTP/1.1 200 OK\r\n{headers}Content-Length: 2\r\n\r\n{{}}").into_bytes(),
        );
        assert_eq!(result.is_ok(), accepted, "{count} headers: {result:?}");
        match result {
            Ok(reply) => {
                assert_eq!(reply.status, 200);
                assert_eq!(reply.body, b"{}");
            }
            Err(failure) => {
                assert!(failure.dispatched);
                assert_eq!(failure.reason, "the answer has too many header lines");
            }
        }
    }
}

#[test]
fn settings_accept_only_a_port_and_the_owners_public_host() {
    let parse = |args: &[&str], env: Option<&str>| {
        config::parse(
            &args
                .iter()
                .map(std::ffi::OsString::from)
                .collect::<Vec<_>>(),
            env.map(std::ffi::OsString::from),
        )
    };
    assert_eq!(parse(&[], None), Ok(Invocation::Run(Settings::default())));
    assert_eq!(Settings::default().port, 7370);
    assert_eq!(
        parse(
            &["--port", "7371", "--allowed-host=openwiz.example"],
            Some("ignored.example")
        ),
        Ok(Invocation::Run(Settings {
            port: 7371,
            allowed_host: Some("openwiz.example".into())
        }))
    );
    assert_eq!(
        parse(&[], Some("env.example")),
        Ok(Invocation::Run(Settings {
            port: 7370,
            allowed_host: Some("env.example".into())
        }))
    );
    assert_eq!(
        parse(&[], Some("")),
        Ok(Invocation::Run(Settings::default()))
    );
    for bad in [
        vec!["--port", "0"],
        vec!["--port", "65536"],
        vec!["--port", "07370"],
        vec!["--port", "+1"],
        vec!["--port"],
        vec!["--port", "1", "--port", "2"],
        vec!["--allowed-host", "https://openwiz.example"],
        vec!["--allowed-host", "openwiz.example:443"],
        vec!["--allowed-host", "openwiz.example/x"],
        vec!["--allowed-host", "127.0.0.1"],
        vec!["--allowed-host", "localhost"],
        vec!["--allowed-host", "app.localhost"],
        vec!["--host", "example.com"],
        vec!["--url", "http://example.com"],
    ] {
        assert!(parse(&bad, None).is_err(), "{bad:?}");
    }
    assert!(
        parse(&[], Some("127.1")).is_err(),
        "a malformed owner setting is refused"
    );
    assert_eq!(parse(&["--help"], None), Ok(Invocation::Help));
}
