//! `contracts/web-api.v1.md` documents every route, parameter, status,
//! error kind, header and limit the tests above check.

use openwiz_server::{
    ALLOWED_HOST_ENV, BODY_TIMEOUT, DEFAULT_PORT, HEAD_TIMEOUT, MAX_CONNECTIONS, MAX_CORE_RUNS,
    MAX_CREATES, MAX_FILE_BYTES, MAX_HEAD_BYTES, MAX_HEADER_LINES, MAX_SEND_BODY_BYTES, MAX_SENDS,
    MAX_TARGET_BYTES, MAX_WEB_BYTES, MAX_WEB_FILES, PAGE_CSP, REQUEST_DEADLINE, RETRY_AFTER_SECS,
    ROUTES, SLOT_WAIT, STATIC_CACHE, WEB_ROUTES, WRITE_TIMEOUT,
};

use crate::http::CLI_EXIT_TO_HTTP;

/// `n` with a space between each group of three digits, as the contract
/// writes numbers (`99 328`).
fn group(n: usize) -> String {
    let digits = n.to_string();
    let mut out = String::new();
    for (i, c) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i).is_multiple_of(3) {
            out.push(' ');
        }
        out.push(c);
    }
    out
}

const CONTRACT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../contracts/web-api.v1.md");

#[test]
fn general_protocol_accounts_for_the_two_loop_switch_posts() {
    let text = std::fs::read_to_string(CONTRACT).expect("web API contract");
    let protocol = text
        .lines()
        .find(|line| line.starts_with("- **`GET` only** on the API"))
        .expect("general protocol methods");
    assert!(protocol.contains("except six **`POST`** routes"));
    assert!(protocol.contains("the two local loop switches"));
}

#[test]
fn general_routes_loop_switch_wiring_is_current() {
    let text = std::fs::read_to_string(CONTRACT).expect("web API contract");
    let routes = text
        .split_once("## Routes\n")
        .expect("Routes section")
        .1
        .split_once("\nPaths match exactly")
        .expect("end of Routes table")
        .0;
    let rows: Vec<_> = routes
        .lines()
        .filter(|row| row.starts_with("| `POST /api/v1/loops/{name}/off` |"))
        .collect();
    assert_eq!(rows.len(), 1, "one general Routes row for loop off");
    assert!(rows[0].contains("No CloudRoom call, kill, activation or approval"));
    assert!(
        !rows[0].contains("production operator wiring pending"),
        "the installed operator is already wired"
    );
}

#[test]
fn general_methods_document_both_loop_switches_as_post_only() {
    let text = std::fs::read_to_string(CONTRACT).expect("web API contract");
    let rules = text
        .split_once("\nPaths match exactly")
        .expect("general route rules")
        .1
        .split_once("\n\n")
        .expect("end of general route rules")
        .0;
    let outcome = text
        .lines()
        .find(|line| line.starts_with("| `405` | `method_not_allowed` |"))
        .expect("405 outcome row");
    for section in [rules, outcome] {
        let post_rule = section
            .split(". ")
            .find(|sentence| sentence.starts_with("On `/api/v1/sessions/{id}/messages`"))
            .expect("POST-only rule");
        assert!(post_rule.contains("any method other than `POST`"));
        assert!(post_rule.ends_with("with `Allow: POST`"));
        for route in ["/api/v1/loops/{name}/off", "/api/v1/loops/{name}/on"] {
            assert_eq!(
                post_rule.matches(&format!("`{route}`")).count(),
                1,
                "{route} must appear once in the POST-only rule"
            );
        }
    }
}

#[test]
fn general_write_scope_documents_local_loop_switches() {
    let text = std::fs::read_to_string(CONTRACT).expect("web API contract");
    let scope = text
        .split_once("The send and the create are the only writes to CloudRoom;")
        .expect("general write scope")
        .1
        .split_once("\n\n")
        .expect("end of general write scope")
        .0;
    assert!(
        scope.contains("the two loop switches change only local loop state"),
        "the write scope must account for both local loop switches"
    );
    assert!(scope.contains("There are no retry, launch, approval or other write routes"));
    assert!(scope.contains("no route that returns an attachment's bytes"));
}

#[test]
fn general_routes_table_documents_both_fleet_reads() {
    let text = std::fs::read_to_string(CONTRACT).expect("web API contract");
    let routes = text
        .split_once("## Routes\n")
        .expect("Routes section")
        .1
        .split_once("\nPaths match exactly")
        .expect("end of Routes table")
        .0;
    for (route, cli) in [
        ("GET /api/v1/fleets", "openwiz fleets --json"),
        ("GET /api/v1/fleets/{spec}", "openwiz fleet <spec> --json"),
    ] {
        let prefix = format!("| `{route}` |");
        let rows: Vec<_> = routes
            .lines()
            .filter(|row| row.starts_with(&prefix))
            .collect();
        assert_eq!(rows.len(), 1, "one general Routes row for {route}");
        assert!(rows[0].contains(&format!("`{cli}`")), "CLI equivalent");
        assert!(
            rows[0].contains("(#fleets-revision-006-127)"),
            "Fleets link"
        );
    }
}

#[test]
fn general_outcomes_documents_the_fleet_detail_cleaning_exception() {
    let text = std::fs::read_to_string(CONTRACT).expect("web API contract");
    let introduction = text
        .split_once("## Outcomes\n\n")
        .expect("Outcomes section")
        .1
        .split_once("\n\n| CLI exit |")
        .expect("Outcomes status table")
        .0;
    assert!(
        introduction.contains("The fleet detail's `502` message keeps the CLI's terminal cleaning"),
        "Outcomes must state the fleet detail cleaning exception"
    );
    assert!(
        introduction.contains("(#fleets-revision-006-127)"),
        "Fleets link"
    );
}

#[test]
fn the_contract_documents_what_the_tests_check() {
    let text = std::fs::read_to_string(CONTRACT).expect("contracts/web-api.v1.md");
    let mut missing = Vec::new();
    let mut need = |what: String| {
        if !text.contains(&what) {
            missing.push(what);
        }
    };
    // T1 documents these paths in a table with separate Methods/Allow cells.
    // Keep exact route/method sets, including duplicate/extra-method refusal.
    let notification_rows = [
        ("/api/v1/notifications/status", "GET"),
        ("/api/v1/notifications/preferences", "GET, PUT"),
        ("/api/v1/notifications/subscription", "GET, PUT, DELETE"),
    ];
    let declared: Vec<_> = text
        .lines()
        .filter(|line| line.starts_with("| `/api/v1/notifications/"))
        .map(|line| {
            let cells: Vec<_> = line.split('|').collect();
            let path = cells[1]
                .trim()
                .strip_prefix('`')
                .unwrap()
                .strip_suffix('`')
                .unwrap();
            (path, cells[2].trim())
        })
        .collect();
    assert_eq!(
        declared, notification_rows,
        "exact notification table paths and Allow lists"
    );
    let is_notification_setting = |path: &str| {
        notification_rows
            .iter()
            .any(|(expected, _)| path == *expected)
    };
    let mut exported: Vec<_> = ROUTES
        .iter()
        .filter(|route| is_notification_setting(route.path))
        .map(|route| (route.path, route.method))
        .collect();
    let mut documented: Vec<_> = notification_rows
        .iter()
        .flat_map(|(path, methods)| methods.split(", ").map(move |method| (*path, method)))
        .collect();
    exported.sort_unstable();
    documented.sort_unstable();
    assert_eq!(
        exported, documented,
        "every notification method is documented exactly once"
    );
    for route in ROUTES {
        // #2036: the bound-target GET is pinned in notifications.v1, not web-api.v1.
        if route.path == "/api/v1/notifications/targets/{token}" {
            let pinned = std::fs::read_to_string(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/../contracts/notifications.v1.md"
            ))
            .unwrap();
            assert!(pinned.contains("`GET /api/v1/notifications/targets/<token>`"));
            continue;
        }
        if !is_notification_setting(route.path) {
            need(format!("`{} {}`", route.method, route.path));
        }
    }
    for param in [
        "`limit`",
        "`offset`",
        "`detail`",
        "`hidden`",
        "`archived`",
        "`{id}`",
        "`{op_id}`",
        "`mode=queue`",
        "`op_id`",
        "`mode`",
        "`text`",
        "`resume_paused_queue`",
        "`accept_possible_duplicate`",
        "`Origin`",
        "`Sec-Fetch-Site`",
        "`X-OpenWiz-Send`",
        "`Content-Length`",
        "openwiz.messaging.v1",
        "openwiz.send-preview.v1",
        "openwiz.send-lookup.v1",
        // #12 (A2): the new-thread routes.
        "`harness`",
        "`model`",
        "`effort`",
        "`attachments`",
        "openwiz.new-thread.v1",
        "openwiz.new-thread-preview.v1",
        "openwiz.cloud-options.v1",
        "openwiz.new-thread-status.v1",
        "contracts/new-thread.v1.schema.json",
        "There is no retry route",
        "`/api/v1/new-threads/{op_id}/retry`",
    ] {
        need(param.to_owned());
    }
    // Every status the server sends, with its error kind, is a row of the
    // contract's status table.
    need("| `200` | (none) |".to_owned());
    for (status, kind) in [
        (400, "bad_request"),
        (400, "invalid_request"),
        (403, "forbidden_origin"),
        (403, "missing_custom_header"),
        (404, "no_route"),
        (404, "not_found"),
        (405, "method_not_allowed"),
        (408, "request_timeout"),
        (411, "length_required"),
        (413, "body_too_large"),
        (415, "unsupported_media_type"),
        (414, "target_too_long"),
        (421, "misdirected"),
        (431, "head_too_large"),
        (500, "internal"),
        (500, "record_unavailable"),
        (502, "read_failed"),
        (503, "busy"),
        (504, "deadline"),
        (505, "http_version"),
    ] {
        need(format!("| `{status}` | `{kind}` |"));
    }
    for (exit, status, kind) in CLI_EXIT_TO_HTTP {
        need(format!("| {exit} | `{status}` | `{kind}` |"));
    }
    for header in [
        "`Content-Type: application/json`",
        "`Cache-Control: no-store`",
        "`X-Content-Type-Options: nosniff`",
        "`Referrer-Policy: no-referrer`",
        "`X-Frame-Options: DENY`",
        "`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`",
        "`Connection: close`",
        "`Allow: GET`",
        "`Allow: POST`",
        "`Retry-After: 5`",
    ] {
        need(header.to_owned());
    }
    for value in [
        format!("{MAX_CONNECTIONS} connections"),
        format!("{MAX_CORE_RUNS} core runs"),
        format!("{} seconds for a core run slot", SLOT_WAIT.as_secs()),
        format!("`Retry-After: {RETRY_AFTER_SECS}`"),
        format!(
            "{} seconds from the end of the request head",
            REQUEST_DEADLINE.as_secs()
        ),
        format!(
            "{} seconds for the whole request head",
            HEAD_TIMEOUT.as_secs()
        ),
        format!("{} seconds for the whole response", WRITE_TIMEOUT.as_secs()),
        format!("{MAX_TARGET_BYTES} bytes"),
        format!("{} KiB", MAX_HEAD_BYTES / 1024),
        format!("{MAX_HEADER_LINES} header lines"),
        format!("{MAX_SENDS} sends"),
        format!("**{MAX_CREATES} create**"),
        format!("{} bytes", group(MAX_SEND_BODY_BYTES)),
        format!("{} seconds of the end of the head", BODY_TIMEOUT.as_secs()),
        format!("`{ALLOWED_HOST_ENV}`"),
        format!("`{DEFAULT_PORT}`"),
        "openwiz.inventory.v1".to_owned(),
        "contracts/inventory.v1.schema.json".to_owned(),
    ] {
        need(value);
    }
    // A8 (#46): the web page.
    need("`--web-root`".to_owned());
    need("`Allow: GET, HEAD`".to_owned());
    need(format!("`Content-Security-Policy: {PAGE_CSP}`"));
    need(format!("`{STATIC_CACHE}`"));
    need(format!("{} MiB per file", MAX_FILE_BYTES / (1024 * 1024)));
    need(format!("{MAX_WEB_FILES} files"));
    need(format!("{} MiB in all", MAX_WEB_BYTES / (1024 * 1024)));
    need("No request touches the filesystem".to_owned());
    need("restart the server".to_owned());
    for route in WEB_ROUTES {
        need(format!("| `{route}` |"));
    }
    for (extension, content_type) in [
        ("html", "text/html; charset=utf-8"),
        ("js", "text/javascript; charset=utf-8"),
        ("css", "text/css; charset=utf-8"),
        ("woff2", "font/woff2"),
        ("txt", "text/plain; charset=utf-8"),
        ("webmanifest", "application/manifest+json"),
        ("png", "image/png"),
    ] {
        need(format!("| `.{extension}` | `{content_type}` |"));
    }
    assert!(
        missing.is_empty(),
        "the contract does not document: {missing:#?}"
    );
}

/// #37 (policy (b)): the `room-cli` version is never a gate, so no status or
/// CLI exit is documented for an untested version any more.
#[test]
fn the_contract_has_no_untested_version_outcome() {
    let text = std::fs::read_to_string(CONTRACT).expect("contracts/web-api.v1.md");
    assert!(
        !text.contains("`untested_version`"),
        "contracts/web-api.v1.md still documents an untested_version outcome"
    );
}
