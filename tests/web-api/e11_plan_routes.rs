//! EP1: synthetic route proofs for the whole-repository plan.
use openwiz_server::{ROUTES, Route};

pub const PLAN_ROUTES: &[Route] = &[Route {
    method: "GET",
    path: "/api/v1/plan",
}];

#[test]
fn e11_plan_registers_exact_read_route() {
    assert!(ROUTES.contains(&Route {
        method: "GET",
        path: "/api/v1/plan",
    }));
    assert_eq!(
        ROUTES.iter().filter(|r| r.path == "/api/v1/plan").count(),
        1
    );
}

use crate::{e11_plan_support as p, fake::Fake};
use serde_json::json;

#[test]
fn e11_plan_reads_closed_specs_empty_versions_side_specs_and_recursive_prerequisites() {
    let mut spec = p::issue(901, None, &[902, 903, 904], &[], &[]);
    spec["state"] = json!("CLOSED");
    spec["milestone"] = json!({"number":7,"title":"Synthetic version"});
    let mut t = p::issue(902, Some(901), &[], &[], &["ready-for-agent"]);
    t["milestone"] = json!({"number":8,"title":"Wrong ticket milestone"});
    let issues = vec![
        p::issue(907, None, &[], &[], &["ready-for-agent"]),
        p::issue(906, Some(905), &[], &[907], &["ready-for-human"]),
        p::issue(905, None, &[906], &[], &[]),
        p::issue(904, Some(901), &[], &[902, 903], &["ready-for-agent"]),
        p::issue(903, Some(901), &[], &[902], &["ready-for-agent"]),
        t,
        spec,
    ];
    let gh = p::github(
        "ep1-universe",
        p::responses(
            issues,
            vec![
                json!({"number":8,"title":"Empty version"}),
                json!({"number":7,"title":"Synthetic version"}),
            ],
        ),
    );
    let room = Fake::new("ep1-universe-room", "normal");
    let s = p::serve(&room, &gh, Default::default());
    let v = p::read(&s);
    assert_eq!(v["coverage"], json!({"state":"complete","gaps":[]}));
    assert_eq!(
        v["lanes"],
        json!([{ "kind":"version","number":7,"title":{"known":"Synthetic version"}}, {"kind":"version","number":8,"title":{"known":"Empty version"}}, {"kind":"side_spec","number":905,"title":{"known":"Synthetic issue 905"}}])
    );
    assert_eq!(
        v["tickets"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| r["number"].as_u64().unwrap())
            .collect::<Vec<_>>(),
        vec![902, 903, 904, 906, 907]
    );
    assert_eq!(
        p::row(&v, 902)["lane"],
        json!({"known":{"kind":"version","number":7}})
    );
    assert_eq!(p::row(&v, 907)["spec"], json!({"known":null}));
    assert_eq!(p::row(&v, 907)["lane"], json!({"known":null}));
    assert_eq!(p::row(&v, 902)["dependents"], json!({"known":[903,904]}));
    assert_eq!(p::row(&v, 904)["blockers"], json!({"known":[902,903]}));
    assert_eq!(p::row(&v, 902)["state"], json!({"known":"ready"}));
    assert_eq!(p::row(&v, 904)["state"], json!({"known":"blocked"}));
    assert_eq!(p::row(&v, 906)["yours"], json!({"known":true}));
    assert_eq!(p::row(&v, 906)["column"], json!({"known":"waiting"}));
    assert_eq!(
        v["critical_chain"],
        json!({"known":{"root":902,"blocked_count":2,"path":[902,903,904]}})
    );
    assert!(room.invocations().is_empty());
    assert_eq!(gh.invocations().len(), 3);
}

#[test]
fn e11_plan_incomplete_state_reads_cannot_advertise_a_global_chain() {
    let mut ticket = p::issue(902, Some(901), &[], &[], &["ready-for-agent"]);
    ticket["labels"] = p::page(vec![
        json!({"name":"ready-for-agent"}),
        json!({"name":"ready-for-agent"}),
    ]);
    let gh = p::github(
        "ep1-label-gap",
        p::responses(vec![p::issue(901, None, &[902], &[], &[]), ticket], vec![]),
    );
    let room = Fake::new("ep1-label-gap-room", "normal");
    let s = p::serve(&room, &gh, Default::default());
    let v = p::read(&s);
    assert_eq!(v["coverage"]["state"], "partial");
    assert!(p::row(&v, 902)["labels"]["unknown"].is_string());
    assert!(p::row(&v, 902)["state"]["unknown"].is_string());
    assert!(v["critical_chain"]["unknown"].is_string(), "{v:#}");
}

#[test]
fn e11_plan_conflicting_parent_reads_are_unknown_not_a_guessed_lane() {
    let gh = p::github(
        "ep1-parent-conflict",
        p::responses(
            vec![
                p::issue(901, None, &[902], &[], &[]),
                p::issue(902, Some(905), &[], &[], &["ready-for-agent"]),
                p::issue(905, None, &[], &[], &[]),
            ],
            vec![],
        ),
    );
    let room = Fake::new("ep1-parent-conflict-room", "normal");
    let s = p::serve(&room, &gh, Default::default());
    let v = p::read(&s);
    assert_eq!(v["coverage"]["state"], "partial");
    assert!(p::row(&v, 902)["spec"]["unknown"].is_string(), "{v:#}");
    assert!(p::row(&v, 902)["lane"]["unknown"].is_string());
}

#[test]
fn e11_plan_retains_side_specs_when_no_child_row_is_usable() {
    let mut spec = p::issue(905, None, &[], &[], &[]);
    spec["subIssues"] = p::page(vec![
        json!({"number":0,"url":format!("{}/issues/0",p::REPO)}),
    ]);
    let gh = p::github(
        "ep1-unusable-side-children",
        p::responses(vec![spec], vec![]),
    );
    let room = Fake::new("ep1-unusable-side-room", "normal");
    let v = p::read(&p::serve(&room, &gh, Default::default()));
    assert_eq!(v["coverage"]["state"], "partial");
    assert_eq!(
        v["lanes"],
        json!([{"kind":"side_spec","number":905,"title":{"known":"Synthetic issue 905"}}])
    );
    assert!(v["critical_chain"]["unknown"].is_string());
}

#[test]
fn e11_plan_missing_parent_field_preserves_other_usable_ticket_facts() {
    let mut ticket = p::issue(902, Some(901), &[], &[], &["ready-for-agent"]);
    ticket.as_object_mut().unwrap().remove("parent");
    let gh = p::github(
        "ep1-field-retention",
        p::responses(vec![p::issue(901, None, &[902], &[], &[]), ticket], vec![]),
    );
    let room = Fake::new("ep1-field-retention-room", "normal");
    let v = p::read(&p::serve(&room, &gh, Default::default()));
    assert_eq!(v["coverage"]["state"], "partial");
    assert!(p::row(&v, 902)["spec"]["unknown"].is_string());
    assert_eq!(
        p::row(&v, 902)["title"],
        json!({"known":"Synthetic issue 902"})
    );
    assert_eq!(
        p::row(&v, 902)["labels"],
        json!({"known":["ready-for-agent"]})
    );
}
