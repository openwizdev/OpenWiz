//! EP1 usable facts survive independent failed reads (audit regressions).
use crate::{e11_plan_support as p, fake::Fake};
use openwiz_adapter_github::plan::Request;
use serde_json::{Value, json};

#[test]
fn e11_plan_milestones_with_unread_titles_remain_as_unknown_lanes() {
    let gh = p::github(
        "ep1-milestone-title-gap",
        p::responses(
            vec![],
            vec![
                json!({"number":7}),
                json!({"number":8,"title":"Retained version"}),
            ],
        ),
    );
    let room = Fake::new("ep1-milestone-title-room", "normal");
    let v = p::read(&p::serve(&room, &gh, Default::default()));
    assert_eq!(v["coverage"]["state"], "partial");
    let lanes = v["lanes"].as_array().unwrap();
    assert_eq!(lanes.len(), 2);
    assert_eq!(lanes[0]["number"], 7);
    assert!(lanes[0]["title"]["unknown"].is_string());
    assert_eq!(lanes[1]["title"], json!({"known":"Retained version"}));
}
#[test]
fn e11_plan_bad_page_metadata_preserves_usable_nodes() {
    for (case, field) in ["pageInfo", "totalCount"].into_iter().enumerate() {
        let mut responses = p::responses(
            vec![
                p::issue(901, None, &[902], &[], &[]),
                p::issue(902, Some(901), &[], &[], &["ready-for-agent"]),
            ],
            vec![],
        );
        let mut doc: Value =
            serde_json::from_str(responses[2]["stdout"].as_str().unwrap()).unwrap();
        doc["data"]["repository"]["issues"]
            .as_object_mut()
            .unwrap()
            .remove(field);
        responses[2]["stdout"] = json!(doc.to_string());
        let gh = p::github(&format!("ep1-page-metadata-{case}"), responses);
        let room = Fake::new(&format!("ep1-page-metadata-room-{case}"), "normal");
        let v = p::read(&p::serve(&room, &gh, Default::default()));
        assert_eq!(v["coverage"]["state"], "partial");
        assert_eq!(
            p::row(&v, 902)["title"],
            json!({"known":"Synthetic issue 902"})
        );
        assert!(v["critical_chain"]["unknown"].is_string());
    }
}
#[test]
fn e11_plan_partial_graphql_issue_keeps_its_readable_facts() {
    let mut responses = p::responses(vec![p::issue(901, None, &[902], &[], &[])], vec![]);
    let mut response = p::answer(
        Request::Issue(902),
        None,
        json!({"issue":p::issue(902,Some(901),&[],&[],&["ready-for-agent"])}),
    );
    let mut doc: Value = serde_json::from_str(response["stdout"].as_str().unwrap()).unwrap();
    doc["errors"] =
        json!([{"message":"synthetic-secret","path":["repository","issue","milestone"]}]);
    response["stdout"] = json!(doc.to_string());
    responses.push(response);
    let gh = p::github("ep1-partial-direct-issue", responses);
    let room = Fake::new("ep1-partial-direct-room", "normal");
    let v = p::read(&p::serve(&room, &gh, Default::default()));
    assert_eq!(v["coverage"]["state"], "partial");
    assert_eq!(
        p::row(&v, 902)["title"],
        json!({"known":"Synthetic issue 902"})
    );
    assert_eq!(
        p::row(&v, 902)["labels"],
        json!({"known":["ready-for-agent"]})
    );
    assert!(!v.to_string().contains("synthetic-secret"));
}
#[test]
fn e11_plan_complete_several_prs_preserves_fleet_held_and_blocker_semantics() {
    let mut a = p::issue(902, Some(901), &[], &[], &["held", "ready-for-agent"]);
    p::closing(&mut a, &[1902, 1903]);
    let mut responses = p::responses(
        vec![
            p::issue(901, None, &[902, 903], &[], &[]),
            a,
            p::issue(903, Some(901), &[], &[902], &["ready-for-agent"]),
        ],
        vec![],
    );
    responses.extend(p::pr_responses(
        1902,
        902,
        "OPEN",
        false,
        json!([]),
        vec![],
        false,
    ));
    responses.extend(p::pr_responses(
        1903,
        902,
        "OPEN",
        false,
        json!([]),
        vec![],
        false,
    ));
    let gh = p::github("ep1-several-complete", responses);
    let room = Fake::new("ep1-several-complete-room", "normal");
    let v = p::read(&p::serve(&room, &gh, Default::default()));
    assert_eq!(p::row(&v, 902)["state"], json!({"known":"held"}));
    assert_eq!(p::row(&v, 902)["column"], json!({"known":"needs_you"}));
    assert!(p::row(&v, 902)["pr"]["unknown"].is_string());
    assert_eq!(p::row(&v, 903)["state"], json!({"known":"blocked"}));
    assert_eq!(
        v["critical_chain"],
        json!({"known":{"root":902,"blocked_count":1,"path":[902,903]}})
    );
    assert_eq!(gh.invocations().len(), 5);
}
#[test]
fn e11_plan_positive_parent_link_is_known_despite_a_partial_child_listing() {
    let mut spec = p::issue(901, None, &[902], &[], &[]);
    spec["milestone"] = json!({"number":7,"title":"Version seven"});
    spec["subIssues"]["totalCount"] = json!(2);
    let gh = p::github(
        "ep1-partial-parent-children",
        p::responses(
            vec![
                spec,
                p::issue(902, Some(901), &[], &[], &["ready-for-agent"]),
            ],
            vec![json!({"number":7,"title":"Version seven"})],
        ),
    );
    let room = Fake::new("ep1-partial-parent-room", "normal");
    let v = p::read(&p::serve(&room, &gh, Default::default()));
    assert_eq!(v["coverage"]["state"], "partial");
    assert_eq!(p::row(&v, 902)["spec"], json!({"known":901}));
    assert_eq!(
        p::row(&v, 902)["lane"],
        json!({"known":{"kind":"version","number":7}})
    );
    assert!(v["critical_chain"]["unknown"].is_string());
}

#[test]
fn e11_plan_state_requires_a_complete_identified_issue_read() {
    for (case, field) in ["title", "url", "milestone", "milestone-title"]
        .into_iter()
        .enumerate()
    {
        let mut i = p::issue(902, Some(901), &[], &[], &["ready-for-agent"]);
        match field {
            "title" => i["title"] = Value::Null,
            "url" => i["url"] = json!("https://github.com/synthetic-owner/other/issues/902"),
            "milestone" => i["milestone"] = json!([]),
            _ => i["milestone"] = json!({"number":7,"title":null}),
        }
        let gh = p::github(
            &format!("ep1-state-own-issue-{case}"),
            p::responses(vec![p::issue(901, None, &[902], &[], &[]), i], vec![]),
        );
        let room = Fake::new(&format!("ep1-state-own-issue-room-{case}"), "normal");
        let v = p::read(&p::serve(&room, &gh, Default::default()));
        assert_eq!(v["coverage"]["state"], "partial", "{field}");
        assert!(
            p::row(&v, 902)["state"]["unknown"].is_string(),
            "{field}: {v:#}"
        );
        assert!(v["critical_chain"]["unknown"].is_string(), "{field}");
    }
}
