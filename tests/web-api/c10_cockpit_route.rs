//! #535 (0.0.10 T2), CK1's route half: the cockpit read keeps every route's
//! checks (Host, method, query, body, headers, route-only logs), the shared
//! read slots, single flight and deadline, and never writes anything.
//! Fixture tests: they prove no live behaviour.

use std::sync::Arc;
use std::thread;
use std::time::Duration;

use openwiz_server::Limits;

use crate::c10_cockpit_support::{self as s, P1, P2, Room, Setup, TARGET};
use crate::http::{self, Gated};

fn setup(name: &str) -> Setup {
    Setup::new(
        s::inventory(vec![
            s::session(1, "active", P1, None),
            s::session(2, "active", P2, Some("mch_syn_0001")),
        ]),
        s::gh(name, s::no_needs),
        Room::new(&[P1], &[("thr_syn_0001", P1, Some("room/syn-a2-0002"))]),
    )
}

fn logged_private_value(log: &str) -> Option<&'static str> {
    log.lines().find_map(|line| {
        // Exempt only a complete access line's numeric elapsed field.
        // Unknown/malformed lines are scanned in full, including diagnostics.
        let fields: Vec<_> = line.split(' ').collect();
        let scan = match fields.as_slice() {
            [method, route, status, elapsed]
                if matches!(
                    *method,
                    "-" | "GET"
                        | "HEAD"
                        | "POST"
                        | "PUT"
                        | "PATCH"
                        | "DELETE"
                        | "OPTIONS"
                        | "CONNECT"
                        | "TRACE"
                ) && (*route == "-" || route.starts_with('/'))
                    && !route.chars().any(char::is_whitespace)
                    && status.len() == 3
                    && status.parse::<u16>().is_ok_and(|s| (100..600).contains(&s))
                    && elapsed.strip_suffix("ms").is_some_and(|ms| {
                        !ms.is_empty() && ms.bytes().all(|b| b.is_ascii_digit())
                    }) =>
            {
                &line[..line.len() - elapsed.len()]
            }
            _ => line,
        };
        ["thr_syn", "prj_syn", "Synthetic", "901", "syn-owner"]
            .into_iter()
            .find(|private| scan.contains(private))
    })
}

#[test]
fn c10_route_is_one_exact_get_with_the_standard_checks() {
    // Synthetic durations reproduce #1795 without relying on the clock.
    for elapsed in ["0", "901", "1901", "9010"] {
        let log = format!("GET /api/v1/cockpit 200 {elapsed}ms\n- - 400 {elapsed}ms\n");
        assert_eq!(logged_private_value(&log), None, "{log}");
    }
    // Every private substring must still be caught outside elapsed time,
    // on any line, including malformed lines and extra diagnostic fields.
    for private in ["thr_syn", "prj_syn", "Synthetic", "901", "syn-owner"] {
        for line in [
            format!("GET /api/v1/cockpit/{private} 200 1ms"),
            format!("{private} /api/v1/cockpit 200 1ms"),
            format!("GET /api/v1/cockpit {private} 1ms"),
            format!("GET /api/v1/cockpit 200 {private} 1ms"),
            format!("GET /api/v1/cockpit 200 1ms {private}"),
            format!("diagnostic: prefix{private}suffix"),
        ] {
            let log = format!("GET /api/v1/cockpit 200 1ms\n{line}\n");
            assert_eq!(logged_private_value(&log), Some(private), "{log}");
        }
    }
    for line in [
        "GET /api/v1/cockpit 200 +901ms",
        "GET /api/v1/cockpit 200 9.901ms",
        "GET /api/v1/cockpit 200 ９01901ms",
        "GET /api/v1/cockpit 200 prefix901suffixms",
        "GET /api/v1/cockpit 200 901s",
        "GET /api/v1/cockpit 200 901ms extra",
        "GET /api/v1/cockpit 200 901ms\t",
        "GET /api/v1/cockpit  200 901ms",
        "GET\t/api/v1/cockpit 200 901ms",
        "GET /api/v1/cockpit 901ms",
        "diagnostic: private fact 901ms",
    ] {
        assert_eq!(logged_private_value(line), Some("901"), "{line}");
    }

    assert!(openwiz_server::ROUTES.contains(&openwiz_server::Route {
        method: "GET",
        path: s::ROUTE,
    }));
    assert_eq!(
        openwiz_server::ROUTES
            .iter()
            .filter(|r| r.path.starts_with(s::ROUTE))
            .count(),
        1
    );
    let setup = setup("c10-route").target(s::messenger("c10-route-target", vec![]), Some(TARGET));
    let server = setup.serve();
    for method in ["POST", "PUT", "DELETE", "PATCH"] {
        let r = server.request(method, s::ROUTE);
        assert_eq!(
            (r.status, r.header("Allow")),
            (405, Some("GET")),
            "{method}"
        );
    }
    let head = server.request("HEAD", s::ROUTE);
    assert_eq!((head.status, head.header("Allow")), (405, Some("GET")));
    assert!(head.body.is_empty());
    assert_eq!(head.header("Content-Length"), None);
    for target in ["/api/v1/cockpit?", "/api/v1/cockpit?project=prj_syn_0001"] {
        let r = server.get(target);
        assert_eq!(
            (r.status, r.error().0.as_str()),
            (400, "invalid_request"),
            "{target}"
        );
    }
    for target in ["/api/v1/cockpit/", "/api/v1/cockpit/x"] {
        assert_eq!(server.get(target).status, 404, "{target}");
    }
    let body = server.send(
        format!(
            "GET {} HTTP/1.1\r\nHost: {}\r\nContent-Length: 2\r\n\r\n{{}}",
            s::ROUTE,
            server.host()
        )
        .as_bytes(),
    );
    assert_eq!(body.status, 400);
    let foreign = server
        .send(format!("GET {} HTTP/1.1\r\nHost: foreign.example\r\n\r\n", s::ROUTE).as_bytes());
    assert_eq!(foreign.status, 421);
    let ok = server.get(s::ROUTE);
    assert_eq!(ok.status, 200);
    crate::c3_routes::headers(&ok);

    // The log names the route and status only: never an id or a fact.
    let log = server.settled_log();
    assert!(log.contains("GET /api/v1/cockpit 200 "), "{log}");
    assert_eq!(logged_private_value(&log), None, "{log}");
}

#[test]
fn c10_the_cockpit_read_writes_nothing() {
    let setup =
        setup("c10-read-only").target(s::messenger("c10-read-only-target", vec![]), Some(TARGET));
    let server = setup.serve();
    s::read(&server);
    s::read(&server);
    let messenger = setup.messenger.as_ref().unwrap();
    let calls = messenger.invocations();
    assert!(!calls.is_empty(), "the target is checked");
    // #129's target check reads the thread and the thread list; nothing else.
    for call in &calls {
        assert!(
            matches!(&call[..2], [t, r] if t == "thread" && (r == "show" || r == "list")),
            "{calls:?}"
        );
    }
    assert!(crate::msg::sends_listing(messenger).is_empty());
    for call in setup.gh.invocations() {
        let read = matches!(
            call.first().map(String::as_str),
            Some("--version" | "repo" | "issue" | "pr" | "api")
        ) && !call.iter().any(|a| {
            [
                "edit", "comment", "create", "close", "merge", "--method", "-X", "-f",
            ]
            .contains(&a.as_str())
        });
        assert!(read, "{call:?}");
    }
}

#[test]
fn c10_identical_reads_share_one_run_and_a_later_read_reads_anew() {
    let mut setup = setup("c10-flight");
    let gate = Arc::new(Gated::new(setup.source.clone()));
    setup.source = gate.clone();
    let server = setup.serve();
    let addr = server.addr;
    let clients: Vec<_> = (0..3)
        .map(|_| thread::spawn(move || http::get(addr, s::ROUTE)))
        .collect();
    server.wait_for("three requests sharing one cockpit run", |st| {
        st.attached == 3 && st.core_runs == 1
    });
    gate.wait_held(1);
    gate.open();
    let replies: Vec<_> = clients.into_iter().map(|c| c.join().unwrap()).collect();
    for r in &replies {
        assert_eq!(r.status, 200, "{}", r.text());
        assert_eq!(r.body, replies[0].body);
    }
    assert_eq!(gate.runs(), 1);
    assert_eq!(server.get(s::ROUTE).status, 200);
    assert_eq!(gate.runs(), 2, "no result cache");
}

#[test]
fn c10_a_full_slot_is_503_and_a_late_read_is_504_keeping_its_slot() {
    // Busy: another read holds the only slot.
    let mut busy = setup("c10-busy");
    let gate = Arc::new(Gated::new(busy.source.clone()));
    busy.source = gate.clone();
    busy.limits = Limits {
        max_core_runs: 1,
        slot_wait: Duration::from_millis(100),
        ..Limits::default()
    };
    let server = busy.serve();
    let addr = server.addr;
    let holder = thread::spawn(move || http::get(addr, "/api/v1/inventory"));
    gate.wait_held(1);
    let r = server.get(s::ROUTE);
    assert_eq!((r.status, r.error().0.as_str()), (503, "busy"));
    assert_eq!(r.header("Retry-After"), Some("5"));
    gate.open();
    assert_eq!(holder.join().unwrap().status, 200);

    // Late: the cockpit read itself outlives the deadline.
    let mut late = setup("c10-late");
    let gate = Arc::new(Gated::new(late.source.clone()));
    late.source = gate.clone();
    late.limits = Limits {
        max_core_runs: 1,
        // The closed gate forces the timeout; recovery must also have room
        // for fresh subprocess reads on a busy host (#1841, #2645): scaled
        // to one unheld cockpit read timed now. Stay below the core's
        // 30-second budget so the gate still holds at 504.
        request_deadline: crate::real_time::scaled(
            "c10_late_read",
            crate::real_time::pick(
                "c10_late_read",
                Duration::from_secs(10),
                Duration::from_secs(2),
            ),
            Duration::from_secs(20),
            || assert_eq!(setup("c10-calibrate").serve().get(s::ROUTE).status, 200),
        ),
        slot_wait: Duration::from_millis(50),
        ..Limits::default()
    };
    let server = late.serve();
    let addr = server.addr;
    let reader = thread::spawn(move || http::get(addr, s::ROUTE));
    gate.wait_held(1);
    let r = reader.join().unwrap();
    assert_eq!((r.status, r.error().0.as_str()), (504, "deadline"));
    crate::c3_routes::headers(&r);
    assert_eq!(
        server.server.stats().core_runs,
        1,
        "the unfinished read keeps its slot"
    );
    assert_eq!(server.get("/api/v1/inventory").status, 503);
    gate.open();
    server.wait_for("the late cockpit run ends", |st| st.core_runs == 0);
    assert_eq!(server.get(s::ROUTE).status, 200);
}
