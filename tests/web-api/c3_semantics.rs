//! S3-7: CLI byte equality on synthetic GitHub answers. Only the hang
//! fixture normalizes independently measured timeout milliseconds (R2).
use std::fs;
use std::path::Path;
use std::sync::Arc;

use openwiz_adapter_github::allowlist;
use openwiz_adapter_github::tickets::Tickets;
use openwiz_core::limits::RUN_BUDGET;
use openwiz_server::Config;
use serde_json::json;

use crate::c3_routes::headers;
use crate::fake::Fake;
use crate::support::{self, FIXTURES, FakeGh, cli, fleet_schema, sources, world};
use world::{IssueW, PrW, World, answer, issue_argv};

#[test]
fn c3_every_list_fixture_is_byte_for_byte_the_cli_json() {
    let mut paths: Vec<_> = fs::read_dir(Path::new(FIXTURES).join("fleets"))
        .unwrap()
        .map(|p| p.unwrap().path().join("scenario.json"))
        .filter(|p| p.is_file())
        .collect();
    paths.sort();
    assert_eq!(paths.len(), 10, "every existing fleet scenario");
    // Each scenario has its own fakes, and the route and the CLI only read
    // them, so all run at once (#1259: the hang scenario waited out its
    // read timeout twice, one after the other).
    std::thread::scope(|scope| {
        for (n, path) in paths.iter().enumerate() {
            scope.spawn(move || list_fixture_equals_the_cli(n, path));
        }
    });
}

fn list_fixture_equals_the_cli(n: usize, path: &Path) {
    let fake = FakeGh::new(&format!("c3-list-{n}"), path);
    let room = Fake::new(&format!("c3-list-room-{n}"), "normal");
    let s = support::serve(&room, sources(&fake, &room), Config::default());
    let (r, (code, out, err)) = std::thread::scope(|scope| {
        let route = scope.spawn(|| s.get("/api/v1/fleets"));
        let cli = cli(&fake, &room, None);
        (route.join().expect("the route's request"), cli)
    });
    assert_eq!(r.status, 200, "{path:?}: {}", r.text());
    assert_eq!((code, err), (0, String::new()));
    let hang = path.parent().unwrap().file_name().unwrap() == "hang";
    assert_eq!(
        list_comparison_body(&r.body, hang),
        list_comparison_body(&out, hang),
        "{path:?}: CLI bytes"
    );
    assert!(r.body.ends_with(b"\n"));
    let errors = fleet_schema::validate(&fleet_schema::load_schema(), &r.json());
    assert!(errors.is_empty(), "{errors:?}");
    headers(&r);
    let calls = fake.invocations();
    assert!(
        calls
            .iter()
            .all(|a| allowlist::allowed(&a.iter().map(String::as_str).collect::<Vec<_>>()))
    );
    assert_eq!(
        calls
            .iter()
            .filter(|a| a.as_slice() == ["--version"])
            .count(),
        2
    );
    assert!(room.invocations().is_empty());
}

fn detail_world() -> World {
    World::default()
        .spec(901, &[902, 903, 904])
        .issue(902, IssueW::ticket("Merged").closed().closed_by(&[952]))
        .pr(952, PrW::merged(&[902], '2', 'a'))
        .issue(903, IssueW::ticket("Unknown").closed())
        .issue(
            904,
            IssueW::ticket("Needs a decision")
                .labels(&["held", "needs-info"])
                .blocked_by(&[902]),
        )
}

#[test]
fn c3_detail_complete_partial_unreadable_and_boundary_specs_equal_the_cli() {
    let base = detail_world();
    let cases = [
        (base.clone(), "901"),
        (
            base.clone().answer(&issue_argv(902), answer("not JSON", 0)),
            "901",
        ),
        (base.clone().answer(&issue_argv(901), answer("", 1)), "901"),
        (
            base.clone().answer(&issue_argv(901), answer("{}", 0)),
            "901",
        ),
        (base.clone().spec(1, &[]), "1"),
        (base.spec(9_999_999_999, &[]), "9999999999"),
    ];
    for (n, (world, spec)) in cases.iter().enumerate() {
        let fake = support::world_fake(&format!("c3-detail-{n}"), world);
        let room = Fake::new(&format!("c3-detail-room-{n}"), "normal");
        let s = support::serve(&room, sources(&fake, &room), Config::default());
        let r = s.get(&format!("/api/v1/fleets/{spec}"));
        let (code, out, err) = cli(&fake, &room, Some(spec));
        if code == 0 {
            assert_eq!(r.status, 200, "{}", r.text());
            assert_eq!(r.body, out, "exact CLI bytes, case {n}");
            assert!(fleet_schema::validate(&fleet_schema::load_schema(), &r.json()).is_empty());
            assert_eq!(
                r.json()["coverage"]["state"],
                if n == 1 { "partial" } else { "complete" },
                "only the planted malformed ticket makes the answer partial"
            );
        } else {
            assert_eq!(code, 1);
            assert!(out.is_empty());
            assert_eq!(r.status, 502);
            assert_eq!(
                r.error(),
                (
                    "read_failed".to_owned(),
                    err.strip_prefix("openwiz: ")
                        .unwrap()
                        .trim_end_matches('\n')
                        .to_owned()
                )
            );
        }
        headers(&r);
        assert_eq!(
            fake.invocations()
                .iter()
                .filter(|a| a.as_slice() == ["--version"])
                .count(),
            2
        );
        assert_eq!(
            room.invocations()
                .iter()
                .filter(|a| a.as_slice() == ["--version"])
                .count(),
            2
        );
    }
}

#[test]
fn c3_detail_read_failure_cleans_controls_exactly_like_the_cli() {
    let fake = support::world_fake("c3-unclean-detail", &World::default().spec(901, &[]));
    let room = Fake::new("c3-unclean-detail-room", "normal");
    let github = Arc::new(support::UncleanTicketList(Tickets::new(fake.program())));
    let mut fleets = sources(&fake, &room);
    fleets.detail = github.clone();
    let agents = fleets.agents.clone();
    let s = support::serve(&room, fleets, Config::default());
    let r = s.get("/api/v1/fleets/901");
    assert_eq!(r.status, 502);
    let (kind, message) = r.error();
    assert_eq!(kind, "read_failed");
    for forbidden in ['\n', '\u{0001}', '\u{202e}'] {
        assert!(!message.contains(forbidden), "unclean message: {message:?}");
    }
    assert_eq!(
        message,
        "fleet: #901's tickets couldn't be read (malformed): #901 couldn't be read: returned malformed output: synthetic?line?control\u{fffd}bidi"
    );
    let (mut out, mut err) = (Vec::new(), Vec::new());
    let code = openwiz_cli::fleet::run_with(
        github.as_ref(),
        agents.as_ref(),
        &crate::fake::clock(),
        RUN_BUDGET,
        &["901".into(), "--json".into()],
        &mut out,
        &mut err,
    );
    assert_eq!(code, 1);
    assert!(out.is_empty());
    assert_eq!(
        String::from_utf8(err).unwrap(),
        format!("openwiz: {message}\n")
    );
    headers(&r);
}

#[test]
fn c3_refusals_read_neither_source_and_logs_expose_only_route_templates() {
    let fake = support::world_fake("c3-guard-sources", &World::default());
    let room = Fake::new("c3-guard-room", "normal");
    let s = support::serve(&room, sources(&fake, &room), Config::default());
    let cases = [
        (
            "/api/v1/fleets?secret=synthetic-query",
            400,
            "/api/v1/fleets",
        ),
        ("/api/v1/fleets/000901", 400, "/api/v1/fleets/{spec}"),
        (
            "/api/v1/fleets/901?secret=synthetic-query",
            400,
            "/api/v1/fleets/{spec}",
        ),
        ("/api/v1/fleets/901/tickets", 404, "-"),
    ];
    for (target, status, _) in cases {
        let r = s.get(target);
        assert_eq!(r.status, status);
        headers(&r);
    }
    let log = s.settled_log();
    assert_refusal_logs(&log, &cases);
    assert!(fake.invocations().is_empty());
    assert!(room.invocations().is_empty());
}

#[test]
fn c3_planted_github_diagnostics_do_not_escape_in_partial_results_or_errors() {
    let payload =
        "/synthetic/private/path GH_TOKEN=synthetic-secret traceback synthetic@example.invalid";
    for (n, spec) in [None, Some("901")].into_iter().enumerate() {
        let fake = support::world_fake(&format!("c3-diagnostic-{n}"), &detail_world());
        let scenario = fake.dir.join("scenario.json");
        let mut value: serde_json::Value =
            serde_json::from_slice(&fs::read(&scenario).unwrap()).unwrap();
        // Refuse every read, with a diagnostic that must be discarded by the adapter.
        for response in value["responses"].as_array_mut().unwrap() {
            response["stdout"] = json!("");
            response["stderr"] = json!(payload);
            response["exit"] = json!(1);
        }
        fs::write(&scenario, value.to_string()).unwrap();
        let room = Fake::new(&format!("c3-diagnostic-room-{n}"), "normal");
        let s = support::serve(&room, sources(&fake, &room), Config::default());
        let target = spec.map_or("/api/v1/fleets".to_owned(), |s| {
            format!("/api/v1/fleets/{s}")
        });
        let r = s.get(&target);
        assert_eq!(r.status, if spec.is_some() { 502 } else { 200 });
        let (code, out, err) = cli(&fake, &room, spec);
        if code == 0 {
            assert_eq!(r.body, out);
        } else {
            assert_eq!(
                r.error().1,
                err.strip_prefix("openwiz: ")
                    .unwrap()
                    .trim_end_matches('\n')
            );
        }
        for forbidden in [
            "synthetic-secret",
            "/synthetic/private",
            "GH_TOKEN",
            "traceback",
            "synthetic@example.invalid",
        ] {
            assert!(!r.text().contains(forbidden));
            assert!(!s.settled_log().contains(forbidden));
        }
        headers(&r);
        assert_eq!(room.invocations().len(), usize::from(spec.is_some()) * 2);
    }
}

fn assert_refusal_logs(log: &str, cases: &[(&str, u16, &str)]) {
    let lines: Vec<_> = log.lines().collect();
    assert_eq!(lines.len(), cases.len());
    let mut actual = Vec::new();
    for line in lines {
        let parts: Vec<_> = line.split_whitespace().collect();
        assert_eq!(parts.len(), 4, "{line:?}");
        let ms = parts[3].strip_suffix("ms").expect("duration in ms");
        assert!(
            !ms.is_empty() && ms.bytes().all(|b| b.is_ascii_digit()),
            "{line:?}"
        );
        actual.push((
            parts[0].to_owned(),
            parts[1].to_owned(),
            parts[2].to_owned(),
        ));
    }
    let mut expected: Vec<_> = cases
        .iter()
        .map(|(_, status, route)| ("GET".to_owned(), (*route).to_owned(), status.to_string()))
        .collect();
    // A response can arrive before its logger finishes. Only the complete
    // multiset is ordered here; each line and every duplicate still count.
    actual.sort_unstable();
    expected.sort_unstable();
    assert_eq!(actual, expected);
}

#[test]
fn c3_r1_refusal_logs_accept_completion_order_and_keep_exact_validation() {
    let cases = [
        ("/api/v1/fleets?x=1", 400, "/api/v1/fleets"),
        ("/api/v1/fleets/01", 400, "/api/v1/fleets/{spec}"),
        ("/api/v1/fleets/901?x=1", 400, "/api/v1/fleets/{spec}"),
        ("/api/v1/fleets/901/tickets", 404, "-"),
    ];
    let log = "GET /api/v1/fleets/{spec} 400 2ms\nGET - 404 0ms\nGET /api/v1/fleets 400 9ms\nGET /api/v1/fleets/{spec} 400 1ms\n";
    assert_refusal_logs(log, &cases);
    for bad in [
        log.lines().take(3).collect::<Vec<_>>().join("\n"),
        format!("{log}GET - 404 0ms\n"),
        log.replacen("GET - 404", "POST - 404", 1),
        log.replacen("GET - 404", "GET /api/v1/fleets/{spec} 404", 1),
        log.replacen("GET - 404", "GET - 400", 1),
        log.replacen(" 2ms", " ms", 1),
        log.replacen(" 2ms", " 2xs", 1),
        log.replacen(" 2ms", " 2ms extra", 1),
    ] {
        assert!(
            std::panic::catch_unwind(|| assert_refusal_logs(&bad, &cases)).is_err(),
            "accepted {bad:?}"
        );
    }
}

fn list_comparison_body(body: &[u8], hang: bool) -> Vec<u8> {
    if !hang {
        return body.to_vec();
    }
    const PREFIX: &str = "timed out after ";
    let mut remaining = std::str::from_utf8(body).expect("CLI JSON is UTF-8");
    let mut normalized = String::new();
    let mut timeouts = 0;
    while let Some(start) = remaining.find(PREFIX) {
        let end = start + PREFIX.len();
        normalized.push_str(&remaining[..end]);
        remaining = &remaining[end..];
        let digits = remaining.bytes().take_while(u8::is_ascii_digit).count();
        if digits > 0 && remaining[digits..].starts_with(" ms") {
            normalized.push_str("<elapsed>");
            remaining = &remaining[digits..];
            timeouts += 1;
        }
    }
    normalized.push_str(remaining);
    assert!(
        timeouts > 0,
        "the hang fixture must report a measured timeout"
    );
    normalized.into_bytes()
}

#[test]
fn c3_r2_only_hang_elapsed_digits_are_normalized() {
    let server = b"{\"snapshot\":1793437200000,\"reason\":\"checks timed out after 15000 ms\",\"gap\":\"checks timed out after 15003 ms\",\"other\":\"timed out after 4 retries; 15000ms\"}\n";
    let cli = b"{\"snapshot\":1793437200000,\"reason\":\"checks timed out after 15002 ms\",\"gap\":\"checks timed out after 15004 ms\",\"other\":\"timed out after 4 retries; 15000ms\"}\n";
    let expected = b"{\"snapshot\":1793437200000,\"reason\":\"checks timed out after <elapsed> ms\",\"gap\":\"checks timed out after <elapsed> ms\",\"other\":\"timed out after 4 retries; 15000ms\"}\n";
    assert_eq!(list_comparison_body(server, true), expected);
    assert_eq!(list_comparison_body(cli, true), expected);
    assert_eq!(list_comparison_body(server, false), server);
    assert_eq!(list_comparison_body(cli, false), cli);
    assert_ne!(
        list_comparison_body(server, false),
        list_comparison_body(cli, false)
    );
}

#[test]
fn c3_r2_hang_must_still_contain_an_actual_timeout_measurement() {
    for body in [
        b"{}".as_slice(),
        b"timed out after ms",
        b"timed out after 12 retries",
        b"timed out after 12ms",
    ] {
        assert!(
            std::panic::catch_unwind(|| list_comparison_body(body, true)).is_err(),
            "no timeout in {body:?}"
        );
        assert_eq!(list_comparison_body(body, false), body);
    }
}
