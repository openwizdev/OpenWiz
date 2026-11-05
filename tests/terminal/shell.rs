//! CP3: Home, Sessions and Fleets through the production shell and its real
//! HTTP client, against the recording fixture server: what is read, what is
//! shown, and that refresh is bounded and never invents completeness.

use std::time::Duration;

use openwiz_terminal::actions::{ActionId, registry};
use openwiz_terminal::app::{Detail, Key, KeyPress, LaneKind, Nav, NeedKey};

use super::render::text;
use super::support::{FixtureServer, Reply, SETTLE, fixture, now, shell};

fn press(c: char) -> KeyPress {
    KeyPress::press(Key::Char(c))
}

fn assert_action_availability(screen: &str, id: ActionId) {
    let available = registry()
        .into_iter()
        .any(|(registered, action)| registered == id && action.is_some());
    let (key, label) = match id {
        ActionId::Answer => ('a', "Answer"),
        ActionId::Send => ('m', "Message"),
        ActionId::NewThread => ('n', "New thread"),
    };
    assert_eq!(
        screen.contains(&format!("{label}: unavailable in this build")),
        !available,
        "{screen}"
    );
    if available {
        assert!(screen.contains(&format!("{key}  {label}")), "{screen}");
    }
}

#[test]
fn home_reads_the_three_existing_routes_and_numbers_needs_you_first() {
    let server = FixtureServer::home();
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    let mut paths = server.paths();
    paths.sort();
    assert_eq!(
        paths,
        ["/api/v1/decisions", "/api/v1/fleets", "/api/v1/inventory"],
        "Home reads the existing routes once each, and no cockpit"
    );
    assert!(server.max_in_flight() <= 2, "at most two reads at once");
    assert!(server.writes().is_empty());
    assert_eq!(shell.app.nav, Nav::Home);
    assert_eq!(
        shell.app.needs(),
        [
            NeedKey::Decision {
                repository: "synthetic-owner/synthetic-repo".into(),
                comment_id: 7001,
                fingerprint: "a".repeat(64),
                question: None,
            },
            NeedKey::Fleet {
                kind: "held".into(),
                spec: 9001,
                ticket: 9003
            }
        ]
    );
    let screen = text(&shell.app, now(0), 120, 40);
    let needs = screen.find("Needs you").unwrap();
    let fleets = screen.find("Fleets\n").or(screen.rfind("Fleets")).unwrap();
    let sessions = screen.rfind("Sessions").unwrap();
    assert!(
        needs < fleets && fleets < sessions,
        "Needs you comes first:\n{screen}"
    );
    for expected in [
        "1 ◆ #9001 spec confirmation",
        "Synthetic headline for spec 9001",
        "2 ◆ #9003 held",
        "fleet label only: no answerable proposal",
        "question not read: the fleets view does not read comments",
        "#9001 Synthetic fleet spec",
        "1 of 3 merged",
        "Synthetic active session",
        "decisions: complete · read 1s ago",
        "sessions: complete · read 0s ago",
    ] {
        assert!(screen.contains(expected), "{expected:?} missing:\n{screen}");
    }
}

#[test]
fn number_keys_open_the_exact_item_and_a_reorder_never_rebinds_it() {
    let server = FixtureServer::home();
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    shell.key(press('2'), now(1));
    let held = Detail::Need(NeedKey::Fleet {
        kind: "held".into(),
        spec: 9001,
        ticket: 9003,
    });
    assert_eq!(shell.app.detail, Some(held.clone()));
    assert!(text(&shell.app, now(1), 120, 40).contains("#9003"));
    shell.key(KeyPress::press(Key::Esc), now(2));
    shell.key(press('1'), now(3));
    let decision = Detail::Need(NeedKey::Decision {
        repository: "synthetic-owner/synthetic-repo".into(),
        comment_id: 7001,
        fingerprint: "a".repeat(64),
        question: None,
    });
    assert_eq!(shell.app.detail, Some(decision.clone()));
    let screen = text(&shell.app, now(3), 120, 40);
    for expected in [
        "Synthetic summary line one.",
        "risk          ordinary",
        "answer to     thr_syn_0399",
    ] {
        assert!(screen.contains(expected), "{expected:?} missing:\n{screen}");
    }
    assert_action_availability(&screen, ActionId::Answer);
    // The decision disappears and the list reorders: the open item stays
    // bound to its identity and says so, rather than showing the new item 1.
    server.route(
        "/api/v1/decisions",
        Reply::ok(fixture("decisions-empty.json")),
    );
    shell.key(press('r'), now(4));
    assert!(shell.settle(now(5), SETTLE));
    assert_eq!(shell.app.detail, Some(decision));
    let screen = text(&shell.app, now(5), 120, 40);
    assert!(
        screen.contains("This item is no longer listed. Nothing was answered"),
        "{screen}"
    );
    assert!(!screen.contains("#9003"), "never rebound to the new item 1");
    // Number keys select only on Home's list, never inside an item.
    shell.key(press('1'), now(6));
    assert!(matches!(
        shell.app.detail,
        Some(Detail::Need(NeedKey::Decision { .. }))
    ));
    assert!(server.writes().is_empty());
}

#[test]
fn sessions_and_fleets_lists_open_their_details_through_existing_routes() {
    let server = FixtureServer::home();
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    shell.key(press('s'), now(1));
    assert_eq!(shell.app.nav, Nav::Sessions);
    let list = text(&shell.app, now(1), 120, 40);
    for title in [
        "Synthetic active session",
        "Synthetic idle session",
        "Synthetic �[31mred� title",
    ] {
        assert!(list.contains(title), "{title:?}:\n{list}");
    }
    shell.key(KeyPress::press(Key::Down), now(2));
    shell.key(KeyPress::press(Key::Enter), now(3));
    assert_eq!(
        shell.app.detail,
        Some(Detail::Session("thr_syn_0301".into()))
    );
    assert!(shell.settle(now(3), SETTLE));
    assert_eq!(server.count("/api/v1/sessions/thr_syn_0301"), 1);
    let detail = text(&shell.app, now(3), 120, 60);
    for expected in [
        "Synthetic final line one.",
        "Synthetic �]0;title�line two�.",
        "model synthetic-model-a, effort high",
        "started       5m ago",
        "session: complete · read 0s ago",
    ] {
        assert!(detail.contains(expected), "{expected:?}:\n{detail}");
    }
    assert_action_availability(&detail, ActionId::Send);
    assert_action_availability(&detail, ActionId::NewThread);
    shell.key(KeyPress::press(Key::Esc), now(4));
    shell.key(press('f'), now(5));
    shell.key(KeyPress::press(Key::Enter), now(6));
    assert_eq!(shell.app.detail, Some(Detail::Fleet(9001)));
    assert!(shell.settle(now(6), SETTLE));
    assert_eq!(server.count("/api/v1/fleets/9001"), 1);
    let fleet = text(&shell.app, now(6), 120, 40);
    for expected in [
        "Fleet #9001",
        "fleet: partial · 1 gap",
        "timed_out threads r17: thread list timed out after 30000 ms",
        "held 1",
        "#9003 Synthetic held ticket",
        "Needs you: Synthetic question for ticket 9003 �[2Jhere?",
        "asked 2m ago · risk live",
        "merged 1",
        "building 1",
    ] {
        assert!(fleet.contains(expected), "{expected:?}:\n{fleet}");
    }
    // Leaving a detail stops its automatic reads.
    shell.key(KeyPress::press(Key::Esc), now(7));
    assert!(shell.settle(now(200_000), SETTLE));
    assert_eq!(server.count("/api/v1/fleets/9001"), 1);
    assert_eq!(server.count("/api/v1/sessions/thr_syn_0301"), 1);
    assert!(server.writes().is_empty());
}

#[test]
fn refresh_is_bounded_per_lane_and_two_overall_and_coalesces_manual_requests() {
    let server = FixtureServer::home();
    server.route(
        "/api/v1/inventory",
        Reply::ok(fixture("inventory.json")).delayed(Duration::from_millis(600)),
    );
    let mut shell = shell(&server);
    let first = shell.app.jobs(now(0));
    assert_eq!(first.len(), 2, "two reads at once, the third waits");
    for job in first {
        let _ = job; // dropped: the lanes stay held until a completion
    }
    assert_eq!(shell.app.reads_in_flight(), 2);
    assert!(
        shell.app.jobs(now(100_000)).is_empty(),
        "held lanes never overlap"
    );

    let mut shell = super::support::shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    assert_eq!(server.count("/api/v1/inventory"), 1);
    // Inventory: 10 s after a settled read; nothing earlier.
    assert_eq!(shell.app.next_due(LaneKind::Inventory), 10_000);
    shell.pump(now(9_999));
    assert_eq!(shell.app.in_flight(LaneKind::Inventory), None);
    shell.pump(now(10_000));
    assert!(shell.app.in_flight(LaneKind::Inventory).is_some());
    // Manual refreshes while it is in flight never start a second read.
    shell.key(KeyPress::press(Key::Char('r')), now(10_001));
    shell.key(KeyPress::press(Key::Char('r')), now(10_002));
    assert!(shell.app.jobs(now(10_003)).iter().all(|j| !matches!(
        j,
        openwiz_terminal::app::Job::Read {
            kind: LaneKind::Inventory,
            ..
        }
    )));
    assert!(shell.settle(now(10_700), SETTLE));
    // One coalesced read followed the in-flight one, then the interval.
    assert_eq!(server.count("/api/v1/inventory"), 3);
    assert!(server.max_in_flight() <= 2);
    // Fleets and decisions keep the 60-second cadence.
    assert_eq!(server.count("/api/v1/fleets"), 2);
    assert_eq!(shell.app.next_due(LaneKind::Fleets), 70_700);
    assert!(server.writes().is_empty());
}

#[test]
fn failures_back_off_honour_retry_after_and_keep_the_last_good_snapshot() {
    let server = FixtureServer::home();
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    assert!(shell.app.inventory.is_some());
    server.route(
        "/api/v1/inventory",
        Reply::status(503, "busy", "too many requests in progress; retry later")
            .header("Retry-After", "5"),
    );
    shell.pump(now(10_000));
    assert!(shell.settle(now(10_000), SETTLE));
    assert_eq!(shell.app.failures(LaneKind::Inventory), 1);
    // max(2 s backoff, min(Retry-After 5 s, 30 s cap)).
    assert_eq!(shell.app.next_due(LaneKind::Inventory), 15_000);
    server.route(
        "/api/v1/inventory",
        Reply::status(
            502,
            "read_failed",
            "thread list: room-cli error (detail withheld)",
        ),
    );
    for (at, due) in [
        (15_000, 19_000),
        (19_000, 27_000),
        (27_000, 43_000),
        (43_000, 73_000),
        (73_000, 103_000),
    ] {
        assert!(shell.settle(now(at), SETTLE));
        assert_eq!(shell.app.next_due(LaneKind::Inventory), due, "after {at}");
    }
    assert!(
        shell.app.inventory.is_some(),
        "the last good snapshot stays"
    );
    let screen = text(&shell.app, now(103_000), 200, 40);
    assert!(
        screen.contains("sessions: complete · read 1m ago · stale · last refresh failed: HTTP 502 read_failed: thread list: room-cli error (detail withheld)"),
        "{screen}"
    );
    // Recovery resets the backoff.
    server.route("/api/v1/inventory", Reply::ok(fixture("inventory.json")));
    assert!(shell.settle(now(103_000), SETTLE));
    assert_eq!(shell.app.failures(LaneKind::Inventory), 0);
    assert_eq!(shell.app.next_due(LaneKind::Inventory), 113_000);
}

#[test]
fn partial_stale_unavailable_and_empty_reads_never_claim_nothing_needs_you() {
    // Complete, fresh and empty everywhere: the only case that may say so.
    let server = FixtureServer::home();
    server.route(
        "/api/v1/decisions",
        Reply::ok(fixture("decisions-empty.json")),
    );
    server.route("/api/v1/fleets", Reply::ok(fixture("fleets-empty.json")));
    server.route(
        "/api/v1/inventory",
        Reply::ok(fixture("inventory-empty.json")),
    );
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    let screen = text(&shell.app, now(0), 120, 40);
    assert!(
        screen.contains("Nothing needs you: decisions and fleets are complete and fresh"),
        "{screen}"
    );
    assert!(
        screen.contains("No fleets") && screen.contains("No sessions"),
        "{screen}"
    );
    // The same snapshot once stale (no refresh for over 70 s) says nothing.
    let stale = text(&shell.app, now(80_000), 120, 40);
    assert!(!stale.contains("Nothing needs you"), "{stale}");
    assert!(
        stale.contains("not a claim that nothing needs you"),
        "{stale}"
    );
    assert!(
        stale.contains("decisions: complete · read 1m ago · stale"),
        "{stale}"
    );

    // Partial decisions with unknown freshness: no claim, and the gap shows.
    server.route(
        "/api/v1/decisions",
        Reply::ok(fixture("decisions-partial.json")),
    );
    server.route(
        "/api/v1/inventory",
        Reply::ok(fixture("inventory-partial.json")),
    );
    let mut shell = super::support::shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    let screen = text(&shell.app, now(0), 120, 40);
    for expected in [
        "decisions: partial · 1 gap",
        "decision sources: freshness unknown",
        "not a claim that nothing needs you",
        "sessions: partial · 1 gap",
    ] {
        assert!(screen.contains(expected), "{expected:?}:\n{screen}");
    }
    assert!(!screen.contains("Nothing needs you:"));

    // No server at all: every part is unavailable, never empty.
    let closed = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = closed.local_addr().unwrap().port();
    drop(closed);
    let mut shell = openwiz_terminal::run::Shell::new(
        openwiz_terminal::app::App::new(super::support::settings(port, None)),
        super::support::client(port, None),
    );
    assert!(shell.settle(now(0), SETTLE));
    let screen = text(&shell.app, now(0), 120, 40);
    for expected in [
        "decisions: unavailable · the server at 127.0.0.1:",
        "is unavailable",
        "disconnected",
        "not a claim that nothing needs you",
    ] {
        assert!(screen.contains(expected), "{expected:?}:\n{screen}");
    }
    assert!(!screen.contains("No sessions"), "unavailable is not empty");
}

#[test]
fn malformed_duplicate_wrong_type_and_unknown_variant_bodies_are_errors_not_data() {
    let server = FixtureServer::home();
    let inventory = String::from_utf8(fixture("inventory.json")).unwrap();
    let cases = [
        (
            "truncated",
            inventory[..inventory.len() / 2].to_owned(),
            "invalid JSON",
        ),
        (
            "duplicate key",
            inventory.replacen("\"gaps\": []", "\"gaps\": [], \"gaps\": []", 1),
            "repeats a key",
        ),
        (
            "wrong type",
            inventory.replacen("\"sessions\": [", "\"sessions\": {\"x\": [", 1),
            "invalid JSON",
        ),
        (
            "unknown variant",
            inventory.replacen("\"state\": \"complete\"", "\"state\": \"mostly\"", 1),
            "unknown variant",
        ),
        (
            "another schema",
            inventory.replacen("openwiz.inventory.v1", "openwiz.inventory.v9", 1),
            "not openwiz.inventory.v1",
        ),
    ];
    for (name, body, why) in cases {
        server.route("/api/v1/inventory", Reply::ok(body.into_bytes()));
        let mut shell = shell(&server);
        assert!(shell.settle(now(0), SETTLE));
        assert!(shell.app.inventory.is_none(), "{name}");
        let error = &shell.app.errors[&LaneKind::Inventory].reason;
        assert!(error.contains(why), "{name}: {error}");
        let screen = text(&shell.app, now(0), 120, 40);
        assert!(
            screen.contains("sessions: unavailable"),
            "{name}:\n{screen}"
        );
        assert!(!screen.contains("No sessions"), "{name}");
    }
}

#[test]
fn a_late_completion_never_replaces_a_newer_selection() {
    let server = FixtureServer::home();
    let mut other = String::from_utf8(fixture("session-thr_syn_0301.json")).unwrap();
    other = other.replace("thr_syn_0301", "thr_syn_0302");
    server.route(
        "/api/v1/sessions/thr_syn_0301",
        Reply::ok(fixture("session-thr_syn_0301.json")).delayed(Duration::from_millis(500)),
    );
    server.route(
        "/api/v1/sessions/thr_syn_0302",
        Reply::ok(other.into_bytes()),
    );
    let mut shell = shell(&server);
    assert!(shell.settle(now(0), SETTLE));
    shell.key(KeyPress::press(Key::Char('s')), now(1));
    shell.key(KeyPress::press(Key::Down), now(1));
    shell.key(KeyPress::press(Key::Enter), now(2));
    assert!(shell.app.in_flight(LaneKind::SessionDetail).is_some());
    shell.key(KeyPress::press(Key::Esc), now(3));
    shell.key(KeyPress::press(Key::Down), now(3));
    shell.key(KeyPress::press(Key::Enter), now(4));
    assert_eq!(
        shell.app.detail,
        Some(Detail::Session("thr_syn_0302".into()))
    );
    // Still one session read in flight: the new selection waits for the lane.
    assert_eq!(
        shell.app.in_flight(LaneKind::SessionDetail).unwrap().0,
        "thr_syn_0301"
    );
    assert!(shell.settle(now(5), SETTLE));
    assert_eq!(server.count("/api/v1/sessions/thr_syn_0302"), 1);
    assert_eq!(
        shell.app.detail,
        Some(Detail::Session("thr_syn_0302".into()))
    );
    let screen = text(&shell.app, now(5), 120, 40);
    assert!(screen.contains("thr_syn_0302"), "{screen}");
    assert!(!screen.contains("thr_syn_0301"), "{screen}");
}
