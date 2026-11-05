//! LP5 HTTP seam, private fixtures with explicit trusted operator context.
use super::{l6_cli::FixedClock, l6_switches::Fixture};
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_server::{Config, ReadSources, Server, loops::Switching};
use std::{
    io::{Read, Write},
    net::{Shutdown, TcpStream},
    sync::Arc,
    time::Duration,
};
const HOST: &str = "synthetic.openwiz.invalid";
fn serve(f: &Fixture) -> Server {
    serve_with_context(f, f.context.clone())
}
fn serve_with_context(f: &Fixture, context: openwiz_store::loops::Context) -> Server {
    serve_with_clock(f, context, Arc::new(FixedClock))
}
fn serve_with_clock(
    f: &Fixture,
    context: openwiz_store::loops::Context,
    clock: Arc<dyn openwiz_core::ops::Clock>,
) -> Server {
    serve_with_limits(f, context, clock, openwiz_server::Limits::default())
}
fn serve_with_limits(
    f: &Fixture,
    context: openwiz_store::loops::Context,
    clock: Arc<dyn openwiz_core::ops::Clock>,
    limits: openwiz_server::Limits,
) -> Server {
    openwiz_server::start_with_loop_switches(
        openwiz_server::bind(0).unwrap(),
        Config {
            allowed_host: Some(HOST.to_owned()),
            limits,
            ..Config::default()
        },
        Arc::new(CloudRoomSource::new(f.root.join("never-room-cli"))),
        clock,
        Arc::new(|_| {}),
        ReadSources::default(),
        Some(Switching { context }),
    )
    .unwrap()
}
fn request(server: &Server, method: &str, path: &str, headers: &str, body: &str) -> (u16, String) {
    let mut stream = TcpStream::connect(server.local_addr()).unwrap();
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    write!(
        stream,
        "{method} {path} HTTP/1.1\r\nHost: {HOST}\r\n{headers}Content-Length: {}\r\n\r\n{body}",
        body.len()
    )
    .unwrap();
    stream.shutdown(Shutdown::Write).unwrap();
    let mut response = String::new();
    stream.read_to_string(&mut response).unwrap();
    (
        response.split_whitespace().nth(1).unwrap().parse().unwrap(),
        response,
    )
}
fn headers() -> String {
    format!(
        "Origin: https://{HOST}\r\nSec-Fetch-Site: same-origin\r\nX-OpenWiz-Send: 1\r\nContent-Type: application/json\r\n"
    )
}
#[test]
fn api_off_and_on_return_the_same_durable_audit_as_cli() {
    let f = Fixture::new();
    let server = serve(&f);
    for (command, enabled) in [("off", false), ("on", true)] {
        let (status, response) = request(
            &server,
            "POST",
            &format!("/api/v1/loops/loop-syn-reminder/{command}"),
            &headers(),
            "{}",
        );
        assert_eq!(status, 200, "{response}");
        let body: serde_json::Value =
            serde_json::from_str(response.split_once("\r\n\r\n").unwrap().1).unwrap();
        assert_eq!(body["actor"], "synthetic-operator");
        assert_eq!(body["at_ms"], 3000);
        assert_eq!(body["enabled"], enabled);
    }
    assert_eq!(f.saved()["events"].as_array().unwrap().len(), 2);
}

#[test]
fn api_rejects_unapproved_shapes_identity_claims_and_origins_before_writing() {
    let f = Fixture::new();
    let server = serve(&f);
    for (method, suffix, body, expected) in [
        ("GET", "off", "{}", 405),
        ("DELETE", "on", "{}", 405),
        ("POST", "off?", "{}", 400),
        ("POST", "off?x=1", "{}", 400),
        ("POST", "off", "[]", 400),
        ("POST", "off", "null", 400),
        ("POST", "off", r#"{"actor":"caller"}"#, 400),
        ("POST", "on", r#"{"actor":"a","actor":"b"}"#, 400),
        ("POST", "off", r#"{"project":"prj_syn_foreign"}"#, 400),
        ("POST", "off", "{} {}", 400),
    ] {
        let (status, response) = request(
            &server,
            method,
            &format!("/api/v1/loops/loop-syn-reminder/{suffix}"),
            &headers(),
            body,
        );
        assert_eq!(status, expected, "{response}");
    }
    for (header, expected) in [
        (
            headers().replace(&format!("Origin: https://{HOST}\r\n"), ""),
            403,
        ),
        (headers().replace("same-origin", "cross-site"), 403),
        (headers().replace("X-OpenWiz-Send: 1\r\n", ""), 403),
        (headers().replace("application/json", "text/plain"), 415),
        (format!("{}Origin: https://{HOST}\r\n", headers()), 403),
        (format!("{}Transfer-Encoding: chunked\r\n", headers()), 400),
        (format!("{}Content-Length: 2\r\n", headers()), 400),
    ] {
        assert_eq!(
            request(
                &server,
                "POST",
                "/api/v1/loops/loop-syn-reminder/off",
                &header,
                "{}"
            )
            .0,
            expected
        );
    }
    assert!(!f.context.state.join("service/loops").exists());
}

#[test]
fn api_refuses_unknown_foreign_and_missing_trusted_context() {
    let mut f = Fixture::new();
    f.definition["action"]["project"]["value"] = serde_json::json!("prj_syn_foreign");
    f.commit();
    let server = serve(&f);
    for name in ["loop-syn-reminder", "unknown", "cloudroom-owned"] {
        assert_eq!(
            request(
                &server,
                "POST",
                &format!("/api/v1/loops/{name}/off"),
                &headers(),
                "{}"
            )
            .0,
            409
        );
    }
    assert!(!f.context.state.join("service/loops").exists());
    let unconfigured = openwiz_server::start(
        openwiz_server::bind(0).unwrap(),
        Config {
            allowed_host: Some(HOST.to_owned()),
            ..Config::default()
        },
        Arc::new(CloudRoomSource::new(f.root.join("never-room-cli"))),
        Arc::new(FixedClock),
        Arc::new(|_| {}),
    )
    .unwrap();
    assert_eq!(
        request(
            &unconfigured,
            "POST",
            "/api/v1/loops/loop-syn-reminder/off",
            &headers(),
            "{}"
        )
        .0,
        503
    );
    let mut stream = TcpStream::connect(server.local_addr()).unwrap();
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    write!(stream,"POST /api/v1/loops/loop-syn-reminder/off HTTP/1.1\r\nHost: {}\r\n{}Content-Length: 2\r\n\r\n{{}}",server.local_addr(),headers()).unwrap();
    stream.shutdown(Shutdown::Write).unwrap();
    let mut response = String::new();
    stream.read_to_string(&mut response).unwrap();
    assert_eq!(response.split_whitespace().nth(1), Some("421"));
}

#[test]
fn installed_api_attributes_to_local_operator_and_refuses_missing_invalid_or_foreign_context() {
    use super::{l6_config::config, l6_switches::git};
    use serde_json::{Value, json};
    use std::fs;
    let f = Fixture::new();
    git(
        &f.context.checkout,
        &[
            "remote",
            "add",
            "origin",
            "https://github.com/synthetic-owner/synthetic-repo.git",
        ],
    );
    let path = f.context.state.join("service/config.json");
    let configured = config(&f);
    fs::write(&path, configured.to_string()).unwrap();
    let context =
        openwiz_store::loops::config::installed(&f.context.checkout, &f.context.state).unwrap();
    let server = serve_with_context(&f, context);
    let (status, response) = request(
        &server,
        "POST",
        "/api/v1/loops/loop-syn-reminder/off",
        &headers(),
        "{}",
    );
    assert_eq!(status, 200, "{response}");
    let event: Value = serde_json::from_str(response.split_once("\r\n\r\n").unwrap().1).unwrap();
    assert_eq!(event["actor"], "synthetic-installed-operator");
    let before = f.saved();
    for operator in [
        json!(null),
        json!(false),
        json!(""),
        json!(" "),
        json!("\0"),
    ] {
        let mut invalid = configured.clone();
        invalid["operator"] = operator;
        fs::write(&path, invalid.to_string()).unwrap();
        for command in ["off", "on"] {
            assert_eq!(
                request(
                    &server,
                    "POST",
                    &format!("/api/v1/loops/loop-syn-reminder/{command}"),
                    &headers(),
                    "{}"
                )
                .0,
                409
            );
            assert_eq!(f.saved(), before);
        }
    }
    for invalid in [
        {
            let mut v = configured.clone();
            v.as_object_mut().unwrap().remove("operator");
            v
        },
        {
            let mut v = configured.clone();
            v["project"] = json!("prj_syn_foreign");
            v
        },
    ] {
        fs::write(&path, invalid.to_string()).unwrap();
        for command in ["off", "on"] {
            assert_eq!(
                request(
                    &server,
                    "POST",
                    &format!("/api/v1/loops/loop-syn-reminder/{command}"),
                    &headers(),
                    "{}"
                )
                .0,
                409
            );
            assert_eq!(f.saved(), before);
        }
    }
    let mut changed = configured;
    changed["operator"] = json!("synthetic-second-installed-operator");
    fs::write(&path, changed.to_string()).unwrap();
    assert_eq!(
        request(
            &server,
            "POST",
            "/api/v1/loops/loop-syn-reminder/on",
            &headers(),
            "{}"
        )
        .0,
        200
    );
    assert_eq!(
        f.saved()["events"][1]["actor"],
        "synthetic-second-installed-operator"
    );
    assert_eq!(f.saved()["events"].as_array().unwrap().len(), 2);
}

#[test]
fn route_inventory_appends_exactly_the_two_local_switch_writes() {
    use openwiz_server::{ROUTES, Route};
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
    assert_eq!(ROUTES.len(), 22 + notification_routes.len());
    let (legacy, appended) = ROUTES.split_at(22);
    assert_eq!(appended, notification_routes);
    assert_eq!(
        &legacy[20..],
        &[
            Route {
                method: "POST",
                path: "/api/v1/loops/{name}/off"
            },
            Route {
                method: "POST",
                path: "/api/v1/loops/{name}/on"
            },
        ]
    );
}

#[test]
fn r1_api_busy_is_retryable_and_failed_wait_has_no_audit_event() {
    use super::l6_switches::ExpiredClock;
    use openwiz_store::loops::storage::Storage;
    let f = Fixture::new();
    f.context.switch("loop-syn-reminder", false, 1000).unwrap();
    let before = f.saved();
    let lock = Storage::open(&f.context.state).unwrap();
    for command in ["off", "on"] {
        let server = serve_with_clock(&f, f.context.clone(), Arc::new(ExpiredClock::new()));
        let (status, response) = request(
            &server,
            "POST",
            &format!("/api/v1/loops/loop-syn-reminder/{command}"),
            &headers(),
            "{}",
        );
        assert_eq!(status, 503, "{response}");
        assert_eq!(response.matches("Retry-After: 5\r\n").count(), 1);
        let body: serde_json::Value =
            serde_json::from_str(response.split_once("\r\n\r\n").unwrap().1).unwrap();
        assert_eq!(body["error"]["kind"], "switch_busy");
        assert_eq!(f.saved(), before);
    }
    drop(lock);
    let server = serve(&f);
    assert_eq!(
        request(
            &server,
            "POST",
            "/api/v1/loops/loop-syn-reminder/on",
            &headers(),
            "{}"
        )
        .0,
        200
    );
    assert_eq!(f.saved()["events"].as_array().unwrap().len(), 2);
}

#[test]
fn r5_expired_request_deadline_never_saves_a_switch() {
    let f = Fixture::new();
    f.context.switch("loop-syn-reminder", false, 1000).unwrap();
    let before = f.saved();
    let server = serve_with_limits(
        &f,
        f.context.clone(),
        Arc::new(FixedClock),
        openwiz_server::Limits {
            request_deadline: Duration::ZERO,
            ..openwiz_server::Limits::default()
        },
    );
    for command in ["off", "on"] {
        let (status, response) = request(
            &server,
            "POST",
            &format!("/api/v1/loops/loop-syn-reminder/{command}"),
            &headers(),
            "{}",
        );
        assert_eq!(status, 503, "{response}");
        assert!(response.contains("\"kind\": \"switch_busy\""), "{response}");
        assert!(response.contains("Retry-After: 5\r\n"));
        assert_eq!(f.saved(), before);
    }
}

#[test]
fn r5_contended_request_uses_its_shorter_deadline() {
    use openwiz_core::{model::Timestamp, ops::Clock};
    use openwiz_store::loops::storage::Storage;
    use std::{
        sync::atomic::{AtomicUsize, Ordering},
        time::Instant,
    };
    struct SteppedClock {
        base: Instant,
        calls: AtomicUsize,
    }
    impl Clock for SteppedClock {
        fn now(&self) -> Timestamp {
            Timestamp(3000)
        }
        fn monotonic(&self) -> Instant {
            self.base
                + Duration::from_secs(match self.calls.fetch_add(1, Ordering::SeqCst) {
                    0 | 1 => 0,
                    2 => 2,
                    _ => 30,
                })
        }
    }
    let f = Fixture::new();
    f.context.switch("loop-syn-reminder", false, 1000).unwrap();
    let before = f.saved();
    let _lock = Storage::open(&f.context.state).unwrap();
    let clock = Arc::new(SteppedClock {
        base: Instant::now(),
        calls: AtomicUsize::new(0),
    });
    let server = serve_with_limits(
        &f,
        f.context.clone(),
        clock.clone(),
        openwiz_server::Limits {
            request_deadline: Duration::from_secs(1),
            ..openwiz_server::Limits::default()
        },
    );
    let (status, response) = request(
        &server,
        "POST",
        "/api/v1/loops/loop-syn-reminder/on",
        &headers(),
        "{}",
    );
    assert_eq!(status, 503, "{response}");
    assert!(response.contains("\"kind\": \"switch_busy\""), "{response}");
    assert_eq!(f.saved(), before);
    assert!(
        clock.calls.load(Ordering::SeqCst) <= 3,
        "wait continued to the simulated 30-second default after the 1-second request deadline"
    );
}

#[test]
fn r5_expiry_during_locked_authority_read_never_saves() {
    use openwiz_core::{model::Timestamp, ops::Clock};
    use openwiz_store::loops::Trust;
    use std::{
        path::Path,
        sync::atomic::{AtomicBool, AtomicUsize, Ordering},
        time::Instant,
    };
    struct ExpiringTrust {
        expired: Arc<AtomicBool>,
        calls: AtomicUsize,
    }
    impl Trust for ExpiringTrust {
        fn verify(&self, _: &Path, _: &str, _: &str) -> bool {
            if self.calls.fetch_add(1, Ordering::SeqCst) == 1 {
                self.expired.store(true, Ordering::SeqCst);
            }
            true
        }
        fn actor(&self) -> Option<String> {
            Some("synthetic-operator".to_owned())
        }
    }
    struct ExpiringClock {
        expired: Arc<AtomicBool>,
        base: Instant,
    }
    impl Clock for ExpiringClock {
        fn now(&self) -> Timestamp {
            Timestamp(3000)
        }
        fn monotonic(&self) -> Instant {
            self.base
                + if self.expired.load(Ordering::SeqCst) {
                    Duration::from_secs(60)
                } else {
                    Duration::ZERO
                }
        }
    }
    let f = Fixture::new();
    f.context.switch("loop-syn-reminder", false, 1000).unwrap();
    let before = f.saved();
    let expired = Arc::new(AtomicBool::new(false));
    let mut context = f.context.clone();
    context.trust = Some(Arc::new(ExpiringTrust {
        expired: expired.clone(),
        calls: AtomicUsize::new(0),
    }));
    let server = serve_with_clock(
        &f,
        context,
        Arc::new(ExpiringClock {
            expired,
            base: Instant::now(),
        }),
    );
    let (status, response) = request(
        &server,
        "POST",
        "/api/v1/loops/loop-syn-reminder/on",
        &headers(),
        "{}",
    );
    assert_eq!(status, 503, "{response}");
    assert!(response.contains("\"kind\": \"switch_busy\""), "{response}");
    assert_eq!(f.saved(), before);
}
