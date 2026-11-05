//! A4: no mutation surface. Only `GET` on the three allowlisted routes; every
//! other method is `405` and every other path `404`, with no read. The
//! server calls only the core's list and show, and makes exactly the reads
//! the CLI makes. P8(a) (in `tests/proof`) scans `crates/server` too.
//!
//! Updated for #9 (OpenWiz 0.0.3), with its reason recorded at each
//! change: the read routes keep these rules, and exactly one mutation is
//! added, the owner's send (W1 to W6, W15 in this suite). Updated again for
//! #12 (OpenWiz 0.0.4, A2), with its reason at the change: one more
//! mutation, the owner's create, and its three reads (U1 to U6, U9, U11,
//! U12 in this suite). Updated again for #16 (OpenWiz 0.0.4, B3), with its
//! reason at each change: the three attachment routes, which change only the
//! attachment store (AW1 to AW5 in this suite).

use std::collections::BTreeMap;

use std::io::Write;
use std::net::TcpStream;
use std::time::Duration;

use openwiz_server::{Config, Limits, ROUTES, Route};

use crate::fake::Fake;
use crate::http::{Response, clear_invocations, read_response, serve, serve_with};

const SERVER_SRC: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../crates/server/src");

fn server_sources() -> Vec<(String, String)> {
    let mut out = Vec::new();
    for entry in std::fs::read_dir(SERVER_SRC).expect("server sources") {
        let path = entry.expect("entry").path();
        if path.extension().is_some_and(|e| e == "rs") {
            out.push((
                path.display().to_string(),
                std::fs::read_to_string(&path).expect("source"),
            ));
        }
    }
    assert!(!out.is_empty());
    out
}

/// The historical catalog remains an exact prefix; notifications append only
/// the six method/path pairs pinned by the notification API contract, then
/// #2036's bound-target GET pinned in notifications.v1.
pub fn legacy_routes(routes: &[Route]) -> &[Route] {
    let notification_routes = [
        Route {
            method: "GET",
            path: "/api/v1/notifications/status",
        },
        Route {
            method: "GET",
            path: "/api/v1/notifications/preferences",
        },
        Route {
            method: "PUT",
            path: "/api/v1/notifications/preferences",
        },
        Route {
            method: "GET",
            path: "/api/v1/notifications/subscription",
        },
        Route {
            method: "PUT",
            path: "/api/v1/notifications/subscription",
        },
        Route {
            method: "DELETE",
            path: "/api/v1/notifications/subscription",
        },
        // #2036: the bound-target GET pinned in notifications.v1.
        Route {
            method: "GET",
            path: "/api/v1/notifications/targets/{token}",
        },
    ];
    assert_eq!(
        routes.len(),
        22 + notification_routes.len(),
        "no missing or extra route"
    );
    let (legacy, appended) = routes.split_at(22);
    assert_eq!(
        appended, notification_routes,
        "only the six approved notification pairs and the bound-target GET, exactly once and appended"
    );
    legacy
}

/// A4, updated for #9 (OpenWiz 0.0.3) with this reason: 0.0.2 proved there
/// was no mutation surface; #9 deliberately adds exactly one, the owner's
/// send (`POST /api/v1/sessions/{id}/messages`), and two reads that never send.
/// The read routes are still `GET` only, and W1 proves the one `POST` is
/// the only write.
///
/// Updated for #12 (OpenWiz 0.0.4, A2) with this reason: A2 deliberately
/// adds one more write, the owner's create (`POST
/// /api/v1/projects/{id}/threads`, sheet A-13), two `GET` reads that never
/// create (the Cloud options and the new-thread status), and the
/// new-thread preview, a `POST` only because it carries the prompt, which
/// reads and never creates (U9). U1 proves the route table and that there
/// is no retry route; U6, U11 and U12 that only the create creates.
///
/// Updated for #16 (OpenWiz 0.0.4, B3) with this reason: B3 adds the three
/// attachment routes (sheet B-9): the list, a `GET` that reads the
/// attachment store and calls no `room-cli`; the upload (`POST`) and the
/// removal (`DELETE`), which change only the controller's attachment store,
/// never CloudRoom. AW1 to AW5 prove them; none returns a file's bytes.
#[test]
fn the_route_table_is_the_read_routes_the_send_and_the_create() {
    let legacy = legacy_routes(ROUTES);
    let reads: Vec<&str> = legacy
        .iter()
        .filter(|r| r.method == "GET")
        .map(|r| r.path)
        .collect();
    assert_eq!(
        reads,
        [
            "/api/v1/inventory",
            "/api/v1/sessions/{id}",
            "/api/v1/sessions/{id}/preview",
            "/api/v1/sessions/{id}/messages/{op_id}",
            "/api/v1/health",
            "/api/v1/cloud-options",
            "/api/v1/new-threads/{op_id}",
            "/api/v1/attachments",
            "/api/v1/fleets",
            "/api/v1/fleets/{spec}",
            "/api/v1/plan",
            "/api/v1/decisions",
            "/api/v1/cockpit",
            "/api/v1/loops",
            "/api/v1/setup",
        ]
    );
    let posts: Vec<&Route> = legacy.iter().filter(|r| r.method != "GET").collect();
    assert_eq!(
        posts,
        [
            &Route {
                method: "POST",
                path: "/api/v1/sessions/{id}/messages",
            },
            &Route {
                method: "POST",
                path: "/api/v1/projects/{id}/threads/preview",
            },
            &Route {
                method: "POST",
                path: "/api/v1/projects/{id}/threads",
            },
            &Route {
                method: "POST",
                path: "/api/v1/attachments",
            },
            &Route {
                method: "DELETE",
                path: "/api/v1/attachments/{id}",
            },
            &Route {
                method: "POST",
                path: "/api/v1/loops/{name}/off"
            },
            &Route {
                method: "POST",
                path: "/api/v1/loops/{name}/on"
            },
        ]
    );
    // The extension guard itself refuses every malformed catalog shape.
    for mutation in 0..7 {
        let mut bad = ROUTES.to_vec();
        match mutation {
            0 => {
                bad.pop();
            }
            1 => bad.push(Route {
                method: "GET",
                path: "/api/v1/notifications/unknown",
            }),
            2 => bad[23] = bad[22],
            3 => bad[22].method = "POST",
            4 => bad[22].path = "/api/v1/notifications/unknown",
            5 => bad.swap(22, 23),
            _ => bad.push(bad[22]),
        }
        assert!(
            std::panic::catch_unwind(|| legacy_routes(&bad)).is_err(),
            "catalog mutation {mutation} must fail"
        );
    }
}

#[test]
fn every_other_method_is_405_and_reads_nothing() {
    let fake = Fake::new("web_a4_methods", "normal");
    let s = serve(&fake);
    for method in [
        "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "CONNECT", "TRACE", "PROPFIND",
        "MKCOL", "LINK", "get", "Get", "GETS", "X",
    ] {
        for target in [
            "/api/v1/inventory",
            "/api/v1/sessions/thr_syn_0001",
            "/api/v1/health",
            "/nowhere",
        ] {
            let r = s.request(method, target);
            assert_eq!(r.status, 405, "{method} {target}: {}", r.status_line);
            assert_eq!(r.header("Allow"), Some("GET"), "{method} {target}");
            // A response to HEAD has no body (J26); its own test checks it.
            if method != "HEAD" {
                assert_eq!(r.error().0, "method_not_allowed");
            }
        }
    }
    // A body on a refused method is never read as a request.
    let r = s.send(
        format!(
            "POST /api/v1/inventory HTTP/1.1\r\nHost: {}\r\nContent-Length: 2\r\n\r\n{{}}",
            s.host()
        )
        .as_bytes(),
    );
    assert_eq!(r.status, 405);
    assert!(fake.invocations().is_empty(), "{:?}", fake.invocations());
}

/// J26: HTTP forbids content in a response to `HEAD`. `HEAD` is still
/// refused (`405`, `Allow: GET`), as is anything else, but with no body.
#[test]
fn a_head_request_is_refused_without_a_body() {
    let fake = Fake::new("web_a4_head", "normal");
    let s = serve(&fake);
    let host = s.host();
    let mut cases: Vec<(String, u16)> = [
        "/api/v1/inventory",
        "/api/v1/inventory?detail=2",
        "/api/v1/sessions/thr_syn_0001",
        "/api/v1/health",
        "/nowhere",
    ]
    .iter()
    .map(|target| {
        (
            format!("HEAD {target} HTTP/1.1\r\nHost: {host}\r\n\r\n"),
            405,
        )
    })
    .collect();
    // Refused before the method is looked at: still no body for HEAD.
    cases.push((
        "HEAD /api/v1/health HTTP/1.1\r\nHost: other.example.invalid\r\n\r\n".to_owned(),
        421,
    ));
    cases.push(("HEAD /api/v1/health HTTP/1.1\r\n\r\n".to_owned(), 400));
    for (raw, status) in cases {
        let r = s.send(raw.as_bytes());
        assert_eq!(r.status, status, "{raw:?}");
        assert!(
            r.body.is_empty(),
            "{raw:?}: a response to HEAD carries {} body bytes",
            r.body.len()
        );
        assert!(
            r.header("Content-Length").is_none(),
            "{raw:?}: Content-Length {:?}",
            r.header("Content-Length")
        );
        if status == 405 {
            assert_eq!(r.header("Allow"), Some("GET"), "{raw:?}");
        }
        assert_eq!(r.header("Cache-Control"), Some("no-store"), "{raw:?}");
        assert_eq!(r.header("Connection"), Some("close"), "{raw:?}");
    }
    assert!(fake.invocations().is_empty(), "{:?}", fake.invocations());
}

fn assert_no_body(what: &str, r: &Response, status: u16) {
    assert_eq!(r.status, status, "{what}");
    assert!(
        r.body.is_empty(),
        "{what}: a response to HEAD carries {} body bytes",
        r.body.len()
    );
    assert!(
        r.header("Content-Length").is_none(),
        "{what}: Content-Length {:?}",
        r.header("Content-Length")
    );
}

/// J26, completed (Haiku delta F1): a HEAD request refused before its head
/// parses still has no body, since its request line already says HEAD:
/// `414`, `431`, `505`, a malformed request line (`400`), a head that
/// arrives too late (`408`) and the connection cap's `503`.
#[test]
fn a_head_request_refused_before_its_head_parses_has_no_body() {
    let fake = Fake::new("web_a4_head_early", "normal");
    let s = serve_with(
        &fake,
        Config {
            allowed_host: None,
            web_root: None,
            limits: Limits {
                head_timeout: Duration::from_millis(800),
                ..Limits::default()
            },
            sending: None,
            creating: None,
            attaching: None,
        },
    );
    let host = s.host();
    let many: String = (0..80).map(|i| format!("X-Synthetic-{i}: 1\r\n")).collect();
    for (what, raw, status) in [
        (
            "505",
            format!("HEAD /api/v1/health HTTP/2.0\r\nHost: {host}\r\n\r\n"),
            505,
        ),
        (
            "414",
            format!(
                "HEAD /{} HTTP/1.1\r\nHost: {host}\r\n\r\n",
                "a".repeat(2000)
            ),
            414,
        ),
        (
            "431",
            format!("HEAD /api/v1/health HTTP/1.1\r\nHost: {host}\r\n{many}\r\n"),
            431,
        ),
        ("400", "HEAD /api/v1/health\r\n\r\n".to_owned(), 400),
    ] {
        assert_no_body(what, &s.send(raw.as_bytes()), status);
    }
    // Half a HEAD request, then nothing: 408, still no body.
    let mut slow = TcpStream::connect(s.addr).unwrap();
    slow.set_read_timeout(Some(Duration::from_secs(10)))
        .unwrap();
    slow.write_all(b"HEAD /api/v1/he").unwrap();
    assert_no_body("408", &read_response(&mut slow), 408);
    assert!(fake.invocations().is_empty());

    // Over the connection cap: 503, still no body for HEAD.
    let capped = serve_with(
        &fake,
        Config {
            allowed_host: None,
            web_root: None,
            limits: Limits {
                max_connections: 1,
                head_timeout: Duration::from_secs(5),
                ..Limits::default()
            },
            sending: None,
            creating: None,
            attaching: None,
        },
    );
    let _idle = TcpStream::connect(capped.addr).unwrap();
    capped.wait_for("one connection", |st| st.connections == 1);
    let r = capped.request("HEAD", "/api/v1/health");
    assert_no_body("503", &r, 503);
    assert_eq!(r.header("Retry-After"), Some("5"));

    // Sol S4: the method arrives in pieces, slower than the server peeks.
    // A beginning of `HEAD ` may be HEAD, so the 503 still has no body.
    let host = capped.host();
    for first in ["H", "HEA", "HEAD"] {
        let mut split = TcpStream::connect(capped.addr).unwrap();
        split
            .set_read_timeout(Some(Duration::from_secs(10)))
            .unwrap();
        split.write_all(first.as_bytes()).unwrap();
        std::thread::sleep(Duration::from_millis(400));
        let rest = format!("HEAD /api/v1/health HTTP/1.1\r\nHost: {host}\r\n\r\n");
        let _ = split.write_all(&rest.as_bytes()[first.len()..]);
        assert_no_body(
            &format!("503 after {first:?}"),
            &read_response(&mut split),
            503,
        );
    }
    // Under the cap too: a head that stops inside the method is 408 with no
    // body when what arrived may be HEAD.
    let mut cut = TcpStream::connect(s.addr).unwrap();
    cut.set_read_timeout(Some(Duration::from_secs(10))).unwrap();
    cut.write_all(b"HEA").unwrap();
    assert_no_body("408 after \"HEA\"", &read_response(&mut cut), 408);
}

#[test]
fn every_other_path_is_404_and_reads_nothing() {
    let fake = Fake::new("web_a4_paths", "normal");
    let s = serve(&fake);
    for target in [
        "/",
        "/index.html",
        "/favicon.ico",
        "/static/app.js",
        "/api",
        "/api/",
        "/api/v1",
        "/api/v1/",
        "/api/v2/inventory",
        "/API/V1/INVENTORY",
        "/api/v1/inventory/",
        "/api/v1/inventory/thr_syn_0001",
        "/api/v1/inventory.json",
        "/api/v1/health/",
        "/api/v1/sessions",
        "/api/v1/sessions/",
        "/api/v1/sessions/thr_syn_0001/",
        "/api/v1/sessions/thr_syn_0001/output",
        "/api/v1/sessions/thr_syn_0001/messages/",
        "/api/v1/sessions/thr_syn_0001/messages/op-1/x",
        "/api/v1/sessions/thr_syn_0001/preview/",
        "/api/v1/sessions/thr_syn_0001/launch",
        "/api/v1/launch",
        "/api/v1/messages",
        "/api/v1/send",
        "/api/v1/sessions/thr_syn_0001/send",
        "/api/v1/sessions/thr_syn_0001/tell",
        "/api/v1/approve",
        "/api/v1/ws",
        "/api/v1/events",
        "//api/v1/inventory",
        "/api//v1/inventory",
        "/api/v1/./inventory",
        "/api/v1/../v1/inventory",
        "/../api/v1/inventory",
        "/%61pi/v1/inventory",
        "/api/v1/%69nventory",
        "/api/v1/inventory;x",
    ] {
        let r = s.get(target);
        assert_eq!(r.status, 404, "{target}: {}", r.text());
        assert_eq!(r.error().0, "no_route", "{target}");
    }
    // #9: `/api/v1/sessions/{id}/messages` is now the send route. This
    // server has no send configuration, so the send routes are absent, for
    // every method (Sol #91, finding 3): `404` with no `Allow`, as in 0.0.2.
    // With one, `GET` there is `405` with `Allow: POST` (W1).
    let r = s.get("/api/v1/sessions/thr_syn_0001/messages");
    assert_eq!(r.status, 404, "{}", r.text());
    assert_eq!(r.header("Allow"), None);
    assert!(fake.invocations().is_empty(), "{:?}", fake.invocations());
}

#[test]
fn health_reads_nothing() {
    let fake = Fake::new("web_a4_health", "version-0.44.0");
    let s = serve(&fake);
    let r = s.get("/api/v1/health");
    assert_eq!(r.status, 200, "{}", r.text());
    let body = r.json();
    assert_eq!(body["server"]["name"], "openwiz-server");
    assert_eq!(body["server"]["version"], env!("CARGO_PKG_VERSION"));
    assert_eq!(body["source"]["name"], "room-cli");
    assert_eq!(body["source"]["tested_version"], "v127");
    assert_eq!(
        body.as_object().unwrap().keys().collect::<Vec<_>>(),
        ["server", "source"]
    );
    assert!(
        fake.invocations().is_empty(),
        "health must not read room-cli"
    );
}

#[test]
fn an_upgrade_request_is_never_upgraded() {
    let fake = Fake::new("web_a4_upgrade", "normal");
    let s = serve(&fake);
    let r = s.send(
        format!(
            "GET /api/v1/health HTTP/1.1\r\nHost: {}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\
             Sec-WebSocket-Key: c3ludGhldGljIGtleSAwMQ==\r\nSec-WebSocket-Version: 13\r\n\r\n",
            s.host()
        )
        .as_bytes(),
    );
    assert_eq!(r.status, 200);
    assert_eq!(r.header("Upgrade"), None);
    assert_eq!(r.header("Connection"), Some("close"));
}

#[test]
fn the_server_calls_only_the_cores_list_and_show() {
    let sources = server_sources();
    let all: String = sources.iter().map(|(_, t)| t.as_str()).collect();
    assert!(all.contains("ops::list_report("), "the server calls list");
    assert!(all.contains("ops::show_report("), "the server calls show");
    let notification_error_import = |path: &str, text: &str, forbidden: &str| {
        forbidden == "openwiz_store"
            && path.ends_with("/crates/server/src/notifications.rs")
            && text.matches("openwiz_store").count() == 1
            && text
                .lines()
                .any(|line| line == "use openwiz_store::notifications::Error;")
    };
    let notification_path = "/synthetic/crates/server/src/notifications.rs";
    let error_import = "use openwiz_store::notifications::Error;";
    assert!(notification_error_import(
        notification_path,
        error_import,
        "openwiz_store"
    ));
    for forbidden_text in [
        "use openwiz_store::notifications::Store;",
        "use openwiz_store::notifications::{Error, Store};",
        "use openwiz_store::notifications::Error;\nopenwiz_store::FileStore::open(root);",
    ] {
        assert!(!notification_error_import(
            notification_path,
            forbidden_text,
            "openwiz_store"
        ));
    }
    assert!(!notification_error_import(
        "/synthetic/crates/server/src/other.rs",
        error_import,
        "openwiz_store"
    ));
    for forbidden in ["Command::new", "File::open", "allowlist", "ThreadTell"] {
        assert!(!notification_error_import(
            notification_path,
            &format!("{error_import}\n{forbidden}(input);"),
            forbidden
        ));
    }
    for (path, text) in &sources {
        for (i, _) in text.match_indices("ops::") {
            let rest = &text[i + "ops::".len()..];
            let names: Vec<String> = match rest.strip_prefix('{') {
                Some(list) => list[..list.find('}').expect("closing brace")]
                    .split(',')
                    .map(|n| n.trim().to_owned())
                    .filter(|n| !n.is_empty())
                    .collect(),
                None => vec![
                    rest.chars()
                        .take_while(|c| c.is_alphanumeric() || *c == '_')
                        .collect(),
                ],
            };
            for name in names {
                assert!(
                    [
                        "self",
                        "list_report",
                        "show_report",
                        "Clock",
                        "ListRequest",
                        "ShowRequest",
                        "Detail",
                        "OpError",
                        "Report",
                    ]
                    .contains(&name.as_str()),
                    "{path}: ops::{name} is not list_report, show_report or their types"
                );
            }
        }
        assert!(
            !text.contains("ops::list(") && !text.contains("ops::show("),
            "{path}: only the report forms, as the CLI uses"
        );
        for forbidden in [
            "process::Command",
            "Command::new",
            "allowlist",
            "Invocation",
            "\"room-cli\"",
            "from_path()",
            "std::fs",
            "File::open",
            "read_dir",
            // 0.0.3's send: since #9 the server calls the core's `send`,
            // `preview` and `lookup` (W5) through `Messenger` and
            // `SendStore`, but never builds a `room-cli` call itself, and
            // only main.rs opens the send record (U9).
            "openwiz_store",
            "ThreadTell",
        ] {
            let allowed_in_main =
                ["from_path()", "openwiz_store"].contains(&forbidden) && path.ends_with("main.rs");
            // A8 (#46): only web.rs reads files: the web page's, once, at
            // start (checked below: never while answering a request).
            let allowed_in_web = ["std::fs", "File::open", "read_dir"].contains(&forbidden)
                && path.ends_with("web.rs");
            // Updated for #16 (B3) with this reason: the attachment routes
            // call the attachment store (`openwiz_store`) through its own
            // API, its types named in lib.rs's configuration. The server still
            // opens no file itself: an upload streams into the store's staging
            // (#16's Q1).
            let allowed_for_attachments = forbidden == "openwiz_store"
                && (path.ends_with("attachments.rs") || path.ends_with("lib.rs"));
            assert!(
                !text.contains(forbidden)
                    || allowed_in_main
                    || allowed_in_web
                    || allowed_for_attachments
                    || notification_error_import(path, text, forbidden),
                "{path} contains {forbidden}"
            );
        }
    }
    // Sol, #50 round 1: the code that answers a web request (from `route`
    // on) touches no file; the export is in memory since the start.
    let web = sources
        .iter()
        .find(|(p, _)| p.ends_with("web.rs"))
        .expect("web.rs");
    let requests = web
        .1
        .split("pub(crate) fn route(")
        .nth(1)
        .expect("web.rs answers requests from fn route on");
    for forbidden in ["fs::", "File", "read", "Path", "open", "Metadata"] {
        assert!(
            !requests.contains(forbidden),
            "web.rs's request code contains {forbidden}"
        );
    }
    let main = sources
        .iter()
        .find(|(p, _)| p.ends_with("main.rs"))
        .expect("main.rs");
    assert!(
        main.1.contains("CloudRoomSource::from_path()"),
        "the server builds its source as the CLI does"
    );
}

fn sorted(invocations: Vec<Vec<String>>) -> BTreeMap<Vec<String>, usize> {
    let mut counts = BTreeMap::new();
    for i in invocations {
        *counts.entry(i).or_insert(0) += 1;
    }
    counts
}

#[test]
fn the_server_makes_exactly_the_reads_the_cli_makes() {
    let fake = Fake::new("web_a4_same_reads", "normal");
    let s = serve(&fake);
    for (target, args) in [
        ("/api/v1/inventory", &["ls", "--json"][..]),
        ("/api/v1/inventory?detail=2", &["ls", "-l", "--json"][..]),
        (
            "/api/v1/inventory?detail=2&hidden=1&archived=1&limit=3&offset=1",
            &[
                "ls", "-l", "--hidden", "-a", "--limit", "3", "--offset", "1", "--json",
            ][..],
        ),
        (
            "/api/v1/sessions/thr_syn_0002",
            &["show", "thr_syn_0002", "--json"][..],
        ),
        (
            "/api/v1/sessions/thr_syn_9999",
            &["show", "thr_syn_9999", "--json"][..],
        ),
    ] {
        clear_invocations(&fake);
        let r = s.get(target);
        assert!(r.status == 200 || r.status == 404, "{target}: {}", r.text());
        let by_server = sorted(fake.invocations());
        clear_invocations(&fake);
        fake.cli(args);
        let by_cli = sorted(fake.invocations());
        assert!(!by_cli.is_empty());
        assert_eq!(
            by_server, by_cli,
            "{target} reads differ from openwiz {args:?}"
        );
    }
}

/// Normal (not dev or build) dependencies of `package`, from `cargo metadata`.
fn normal_dependencies(meta: &serde_json::Value, package: &str) -> Vec<String> {
    meta["packages"]
        .as_array()
        .expect("packages")
        .iter()
        .find(|p| p["name"] == package)
        .unwrap_or_else(|| panic!("no package {package}"))["dependencies"]
        .as_array()
        .expect("dependencies")
        .iter()
        .filter(|d| d["kind"].is_null())
        .map(|d| d["name"].as_str().expect("name").to_owned())
        .collect()
}

fn workspace_metadata() -> serde_json::Value {
    static META: std::sync::OnceLock<serde_json::Value> = std::sync::OnceLock::new();
    META.get_or_init(|| {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("..");
        let out = std::process::Command::new(env!("CARGO"))
            .args(["metadata", "--format-version", "1", "--locked", "--offline"])
            .args([
                "--filter-platform",
                String::from_utf8(
                    std::process::Command::new("rustc")
                        .args(["--print", "host-tuple"])
                        .output()
                        .expect("rustc")
                        .stdout,
                )
                .expect("host")
                .trim(),
            ])
            .current_dir(&root)
            .output()
            .expect("run cargo metadata");
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        serde_json::from_slice(&out.stdout).expect("metadata JSON")
    })
    .clone()
}

fn server_dependency_violations(meta: &serde_json::Value) -> Vec<String> {
    let mut violations = Vec::new();
    for package in meta["packages"].as_array().expect("packages") {
        let name = package["name"].as_str().expect("name");
        let deps = normal_dependencies(meta, name);
        // The service is the sole normal entry point to the server. Forbid
        // incoming service edges too, so no client can reach it indirectly.
        if deps.contains(&"openwiz-service".to_owned()) {
            violations.push(format!("{name} depends on openwiz-service"));
        }
        if deps.contains(&"openwiz-server".to_owned()) != (name == "openwiz-service") {
            violations.push(format!("{name}: server dependency exception"));
        }
    }
    violations
}

#[test]
fn the_server_dependencies_point_inward_and_only_the_service_embeds_it() {
    let meta = workspace_metadata();
    let mut deps = normal_dependencies(&meta, "openwiz-server");
    deps.sort();
    // #9 (U9): the store, so that the server opens the same send record as
    // `openwiz send`. An in-workspace crate; no third-party crate.
    // #127: the existing GitHub adapter supplies both read-only fleet routes.
    assert_eq!(
        deps,
        [
            "openwiz-adapter-cloudroom",
            "openwiz-adapter-github",
            "openwiz-core",
            "openwiz-store",
            "serde",
            "serde_json"
        ]
    );
    assert_eq!(server_dependency_violations(&meta), Vec::<String>::new());
    let core = normal_dependencies(&meta, "openwiz-core");
    let adapter = normal_dependencies(&meta, "openwiz-adapter-cloudroom");
    assert!(
        !core
            .iter()
            .chain(&adapter)
            .any(|d| d == "openwiz-server" || d == "openwiz-cli")
    );
}

/// A synthetic dependency edge using Cargo's actual dependency object shape.
/// Only the declared normal/dev edges are inputs to this architecture gate.
fn metadata_with_edge(
    meta: &serde_json::Value,
    from: &str,
    to: &str,
    dev: bool,
) -> serde_json::Value {
    let mut edge = meta["packages"]
        .as_array()
        .unwrap()
        .iter()
        .find(|p| p["name"] == "openwiz-service")
        .unwrap()["dependencies"]
        .as_array()
        .unwrap()
        .iter()
        .find(|d| d["name"] == "openwiz-server")
        .unwrap()
        .clone();
    let target = meta["packages"]
        .as_array()
        .unwrap()
        .iter()
        .find(|p| p["name"] == to)
        .unwrap();
    edge["name"] = serde_json::json!(to);
    edge["path"] = serde_json::json!(
        std::path::Path::new(target["manifest_path"].as_str().unwrap())
            .parent()
            .unwrap()
    );
    edge["kind"] = if dev {
        serde_json::json!("dev")
    } else {
        serde_json::Value::Null
    };
    let mut mutated = meta.clone();
    mutated["packages"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|p| p["name"] == from)
        .unwrap()["dependencies"]
        .as_array_mut()
        .unwrap()
        .push(edge);
    mutated
}

#[test]
fn server_dependency_gate_rejects_indirect_normal_clients() {
    let meta = workspace_metadata();
    assert_eq!(server_dependency_violations(&meta), Vec::<String>::new());
    let direct = metadata_with_edge(&meta, "openwiz-cli", "openwiz-server", false);
    assert_eq!(
        server_dependency_violations(&direct),
        ["openwiz-cli: server dependency exception"]
    );
    for (from, expected) in [
        ("openwiz-cli", "openwiz-cli depends on openwiz-service"),
        ("openwiz-core", "openwiz-core depends on openwiz-service"),
    ] {
        let indirect = metadata_with_edge(&meta, from, "openwiz-service", false);
        assert_eq!(
            server_dependency_violations(&indirect),
            [expected],
            "{from} must not reach the server through the service"
        );
    }
    let dev_only = metadata_with_edge(&meta, "openwiz-cli", "openwiz-service", true);
    assert_eq!(
        server_dependency_violations(&dev_only),
        Vec::<String>::new(),
        "this gate governs normal dependencies"
    );
}
