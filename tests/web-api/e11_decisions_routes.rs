//! EP3: the decisions read uses the existing guarded HTTP seam.
use crate::{fake::Fake, http};

pub const DECISIONS_ROUTES: &[openwiz_server::Route] = &[openwiz_server::Route {
    method: "GET",
    path: "/api/v1/decisions",
}];

#[test]
fn e11_decisions_target_failure_keeps_its_kind_and_never_leaks_diagnostics() {
    use crate::{e11_decisions_support as s, msg::SendFake, send_support};
    let room = Fake::new("e11_target_failure_inventory", "normal");
    let messenger = SendFake::with(
        "e11_target_failure_messenger",
        vec![
            serde_json::json!({"argv":["thread","show","thr_syn_0011","--json"],"exit":1,"stderr":"SYNTHETIC_PRIVATE_DIAGNOSTIC\n"}),
        ],
    );
    let gh = s::fake("e11_target_failure_gh", vec![]);
    let server = s::serve_with(
        &gh,
        &room,
        send_support::send_config(&messenger, openwiz_server::Limits::default()),
        Ok(Some("thr_syn_0011".into())),
        std::sync::Arc::new(crate::fake::clock()),
    );
    let response = server.get("/api/v1/decisions");
    let body = response.json();
    s::check(&body);
    assert!(body["orchestrator"]["target"].get("unknown").is_some());
    assert_eq!(
        body["orchestrator"]["coverage"]["gaps"][0]["kind"],
        "command_failed"
    );
    assert_eq!(body["orchestrator"]["freshness"]["state"], "unknown");
    assert_eq!(
        body["coverage"],
        serde_json::json!({"state":"complete","gaps":[]})
    );
    assert!(!response.text().contains("SYNTHETIC_PRIVATE_DIAGNOSTIC"));
    assert!(
        !server
            .settled_log()
            .contains("SYNTHETIC_PRIVATE_DIAGNOSTIC")
    );
    assert!(messenger.tells().is_empty());
}

#[test]
fn e11_decisions_invalid_configured_target_never_reaches_the_provider() {
    use crate::{e11_decisions_support as s, msg::SendFake, send_support};
    for (index, id) in ["", "-option", "space id", "thr_é", &"a".repeat(129)]
        .into_iter()
        .enumerate()
    {
        let room = Fake::new(&format!("e11_invalid_target_inventory_{index}"), "normal");
        let messenger = SendFake::new(&format!("e11_invalid_target_messenger_{index}"), "send");
        let gh = s::fake(&format!("e11_invalid_target_gh_{index}"), vec![]);
        let server = s::serve_with(
            &gh,
            &room,
            send_support::send_config(&messenger, openwiz_server::Limits::default()),
            Ok(Some(id.into())),
            std::sync::Arc::new(crate::fake::clock()),
        );
        let body = server.get("/api/v1/decisions").json();
        s::check(&body);
        assert!(body["orchestrator"]["target"].get("unknown").is_some());
        assert_eq!(body["orchestrator"]["coverage"]["state"], "partial");
        assert!(messenger.invocations().is_empty());
    }
}

#[test]
fn e11_decisions_appends_exactly_one_get() {
    let legacy = crate::a4_no_mutation::legacy_routes(openwiz_server::ROUTES);
    let before = 15 + crate::e11_plan_routes::PLAN_ROUTES.len();
    assert_eq!(
        // Exclude the two L6 switches and #1100's appended setup GET.
        &legacy[before..legacy.len() - 2 - 1 - 1 /* #535 cockpit GET */ - 1 /* #549 loops GET */],
        DECISIONS_ROUTES
    );
}

#[test]
fn e11_decisions_configured_target_is_verified_by_read_only() {
    use crate::{e11_decisions_support as s, msg::SendFake, send_support};
    let room = Fake::new("e11_target_inventory", "normal");
    let messenger = SendFake::new("e11_target_messenger", "send");
    let gh = s::fake("e11_target_gh", vec![]);
    let server = s::serve_with(
        &gh,
        &room,
        send_support::send_config(&messenger, openwiz_server::Limits::default()),
        Ok(Some("thr_syn_0011".into())),
        std::sync::Arc::new(crate::fake::clock()),
    );
    let response = server.get("/api/v1/decisions");
    let body = response.json();
    crate::e11_decisions_support::check(&body);
    assert_eq!(response.status, 200);
    assert_eq!(
        body["orchestrator"]["target"],
        serde_json::json!({"known":"thr_syn_0011"})
    );
    assert_eq!(
        body["orchestrator"]["coverage"],
        serde_json::json!({"state":"complete","gaps":[]})
    );
    assert_eq!(
        body["coverage"],
        serde_json::json!({"state":"complete","gaps":[]})
    );
    let calls = messenger.invocations();
    assert_eq!(
        calls
            .iter()
            .filter(|args| args.iter().any(|a| a == "show"))
            .count(),
        1,
        "{calls:?}"
    );
    assert!(
        calls
            .iter()
            .all(|args| !args.iter().any(|a| ["tell", "spawn"].contains(&a.as_str())))
    );
    assert!(crate::msg::sends_listing(&messenger).is_empty());
}

#[test]
fn e11_decisions_unconfigured_read_is_an_honest_partial_envelope() {
    let fake = Fake::new("e11_decisions_unconfigured", "normal");
    let server = http::serve(&fake);
    let response = server.get("/api/v1/decisions");
    assert_eq!(response.status, 200, "{}", response.text());
    let body = response.json();
    assert_eq!(body["schema"], "openwiz.decisions.v1");
    assert_eq!(body["kind"], "response");
    assert_eq!(body["items"], serde_json::json!([]));
    assert_eq!(body["coverage"]["state"], "partial");
    assert!(!body["coverage"]["gaps"].as_array().unwrap().is_empty());
    assert_eq!(body["freshness"]["state"], "unknown");
    assert_eq!(response.header("Cache-Control"), Some("no-store"));
    assert!(fake.invocations().is_empty());
}
