//! S3-7 (#127): two read-only fleet routes, with the existing HTTP guards.
use openwiz_server::{ROUTES, Route};

use crate::fake::Fake;
use crate::http::Response;
use crate::support;

pub const FLEET_ROUTES: &[Route] = &[
    Route {
        method: "GET",
        path: "/api/v1/fleets",
    },
    Route {
        method: "GET",
        path: "/api/v1/fleets/{spec}",
    },
];

#[test]
fn c3_adds_exactly_two_gets_after_the_existing_routes() {
    let legacy = crate::a4_no_mutation::legacy_routes(ROUTES);
    assert_eq!(
        legacy.len(),
        15 + crate::e11_plan_routes::PLAN_ROUTES.len()
            + crate::e11_decisions_routes::DECISIONS_ROUTES.len()
            + 2 // L6 local switch routes.
            + 1 // #1100 setup GET.
            + 1 // #535 cockpit GET.
            + 1 // #549 loops GET.
    );
    assert_eq!(&legacy[13..15], FLEET_ROUTES);
}

pub fn headers(r: &Response) {
    for (name, value) in [
        ("Content-Type", "application/json"),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
        ("X-Frame-Options", "DENY"),
        (
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'",
        ),
        ("Connection", "close"),
    ] {
        assert_eq!(r.header(name), Some(value), "{name}: {r:?}");
        assert_eq!(r.headers_named(name), 1, "{name} once");
    }
    assert!(
        r.headers
            .iter()
            .all(|(k, _)| !k.to_ascii_lowercase().starts_with("access-control-"))
    );
}

#[test]
fn c3_rejects_methods_bodies_queries_and_noncanonical_spec_numbers_before_reads() {
    let fake = Fake::new("c3_refusals", "normal");
    let github = support::world_fake("c3-refusals-github", &support::world::World::default());
    let s = support::serve(
        &fake,
        support::sources(&github, &fake),
        openwiz_server::Config::default(),
    );
    for path in ["/api/v1/fleets", "/api/v1/fleets/901"] {
        for method in [
            "HEAD",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "OPTIONS",
            "CONNECT",
            "TRACE",
            "SYNTHETIC",
        ] {
            let r = s.request(method, path);
            assert_eq!(r.status, 405, "{method} {path}");
            assert_eq!(r.header("Allow"), Some("GET"));
            headers(&r);
            if method == "HEAD" {
                assert!(r.body.is_empty());
                assert_eq!(r.header("Content-Length"), None);
            } else {
                assert_eq!(r.error().0, "method_not_allowed");
            }
        }
        for suffix in ["?", "?limit=1", "?spec=901", "?x=%00", "?x=1&x=2"] {
            let r = s.get(&format!("{path}{suffix}"));
            assert_eq!((r.status, r.error().0.as_str()), (400, "invalid_request"));
            headers(&r);
        }
        for framing in [
            "Content-Length: 1\r\n",
            "Transfer-Encoding: chunked\r\n",
            "Content-Length: 0\r\nContent-Length: 0\r\n",
        ] {
            let r = s.send(
                format!(
                    "GET {path} HTTP/1.1\r\nHost: {}\r\n{framing}\r\nx",
                    s.host()
                )
                .as_bytes(),
            );
            assert_eq!((r.status, r.error().0.as_str()), (400, "bad_request"));
            headers(&r);
        }
        let r = s
            .send(format!("GET {path} HTTP/1.1\r\nHost: other.example.invalid\r\n\r\n").as_bytes());
        assert_eq!(r.status, 421);
        headers(&r);
    }
    for spec in [
        "0",
        "01",
        "-1",
        "+1",
        "1.0",
        "1e2",
        "10000000000",
        "%39%30%31",
        "abc",
        "%00",
    ] {
        let r = s.get(&format!("/api/v1/fleets/{spec}"));
        assert_eq!(
            (r.status, r.error().0.as_str()),
            (400, "invalid_request"),
            "{spec}"
        );
        headers(&r);
    }
    for path in [
        "/api/v1/fleets/",
        "/api/v1/fleets/901/",
        "/api/v1/fleets/901/tickets",
        "/api/v1/Fleets",
        "/api/v1//fleets",
    ] {
        let r = s.get(path);
        assert_eq!(
            (r.status, r.error().0.as_str()),
            (404, "no_route"),
            "{path}"
        );
        headers(&r);
    }
    assert!(github.invocations().is_empty());
    assert!(fake.invocations().is_empty());
}

#[test]
fn huntr_malformed_host_refused_as_bad_request() {
    let fake = Fake::new("huntr_host", "normal");
    let github = support::world_fake("huntr-host-gh", &support::world::World::default());
    let s = support::serve(
        &fake,
        support::sources(&github, &fake),
        openwiz_server::Config {
            allowed_host: Some("openwiz.example.invalid".to_owned()),
            ..Default::default()
        },
    );
    for host in [
        "foreign.example",
        "[::1]",
        "[::1]:",
        "[::1]:0",
        "[::1]:65536",
        "[2001:db8::1]:443",
        "[::ffff:192.0.2.1]:80",
        "[v1.a]:443",
        "[VF.a-b:c]",
        "localhost:0.example.invalid",
    ] {
        let r = s.send(format!("GET /api/v1/fleets HTTP/1.1\r\nHost: {host}\r\n\r\n").as_bytes());
        assert_eq!(
            (r.status, r.error().0.as_str()),
            (421, "misdirected"),
            "{host}"
        );
        headers(&r);
    }
    for host in [
        s.host(),
        format!("[::1]:{}", s.addr.port()),
        "OpenWiz.Example.Invalid".to_owned(),
    ] {
        let r = s.send(format!("GET /api/v1/health HTTP/1.1\r\nHost: {host}\r\n\r\n").as_bytes());
        assert_eq!(r.status, 200, "{host}");
    }
    assert!(github.invocations().is_empty());
    assert!(fake.invocations().is_empty());
    for host in [
        "[::1",
        "::1]",
        "[[::1]]",
        "[::1]]",
        "[::1]trailing",
        "[::1]:abc",
        "[::1]:80:90",
        "host[::1]",
        "[]",
        "[127.0.0.1]",
        "[::g]",
        "[1:2:3:4:5:6:7:8:9]",
        "[v.a]",
        "[v1.]",
    ] {
        for target in ["GET /api/v1/fleets", "POST /api/v1/fleets/901?unexpected=1"] {
            let r = s.send(
                format!("{target} HTTP/1.1\r\nHost: {host}\r\nContent-Length: 1\r\n\r\nx")
                    .as_bytes(),
            );
            assert!(github.invocations().is_empty());
            assert!(fake.invocations().is_empty());
            assert_eq!(
                (r.status, r.error().0.as_str()),
                (400, "bad_request"),
                "{host}: {target}"
            );
            assert_eq!(r.error().1, "the Host is malformed");
            headers(&r);
        }
    }
}
