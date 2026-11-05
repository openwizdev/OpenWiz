//! PR 788 correction proofs: the public plan HTTP seam, synthetic sources only.
use crate::{e11_plan_support as p, fake::Fake};
use serde_json::json;

#[test]
fn e11_plan_review_r2_multiple_merged_prs_leave_merge_and_chain_unknown() {
    let mut blocker = p::issue(902, Some(901), &[], &[], &["held", "ready-for-agent"]);
    p::closing(&mut blocker, &[1902, 1903]);
    let mut responses = p::responses(
        vec![
            p::issue(901, None, &[902, 903], &[], &[]),
            blocker,
            p::issue(903, Some(901), &[], &[902], &["ready-for-agent"]),
        ],
        vec![],
    );
    for pr in [1902, 1903] {
        responses.extend(p::pr_responses(
            pr,
            902,
            "MERGED",
            false,
            json!([]),
            vec![],
            true,
        ));
    }
    let gh = p::github("ep1-review-r2-merged", responses);
    let room = Fake::new("ep1-review-r2-merged-room", "normal");
    let v = p::read(&p::serve(&room, &gh, Default::default()));
    assert_eq!(v["coverage"]["state"], "partial");
    assert!(p::row(&v, 902)["pr"]["unknown"].is_string());
    assert!(p::row(&v, 902)["state"]["unknown"].is_string());
    assert!(p::row(&v, 902)["column"]["unknown"].is_string());
    assert!(p::row(&v, 903)["state"]["unknown"].is_string(), "{v:#}");
    assert!(v["critical_chain"]["unknown"].is_string());
    assert!(
        v["coverage"]["gaps"]
            .as_array()
            .unwrap()
            .iter()
            .any(|g| g["kind"] == "malformed")
    );
    assert_eq!(gh.invocations().len(), 5);
    assert!(room.invocations().is_empty());
}

#[test]
fn e11_plan_review_r3_partial_reciprocal_absence_preserves_the_native_parent() {
    for (case, total, other_parent, known_parent) in [
        (0, 2, false, true),
        (1, 1, false, false),
        (2, 2, true, false),
    ] {
        let mut spec = p::issue(901, None, &[903], &[], &[]);
        spec["milestone"] = json!({"number":7,"title":"Version seven"});
        spec["subIssues"]["totalCount"] = json!(total);
        let mut issues = vec![
            spec,
            p::issue(902, Some(901), &[], &[], &["ready-for-agent"]),
            p::issue(903, Some(901), &[], &[], &["ready-for-agent"]),
        ];
        if other_parent {
            issues.push(p::issue(905, None, &[902], &[], &[]));
        }
        let gh = p::github(
            &format!("ep1-review-r3-{case}"),
            p::responses(issues, vec![json!({"number":7,"title":"Version seven"})]),
        );
        let room = Fake::new(&format!("ep1-review-r3-room-{case}"), "normal");
        let v = p::read(&p::serve(&room, &gh, Default::default()));
        assert_eq!(v["coverage"]["state"], "partial");
        let ticket = p::row(&v, 902);
        if known_parent {
            assert_eq!(ticket["spec"], json!({"known":901}));
            assert_eq!(
                ticket["lane"],
                json!({"known":{"kind":"version","number":7}})
            );
        } else {
            assert!(ticket["spec"]["unknown"].is_string());
            assert!(ticket["lane"]["unknown"].is_string());
        }
        if total == 2 {
            assert!(v["critical_chain"]["unknown"].is_string());
        }
        assert_eq!(ticket["title"], json!({"known":"Synthetic issue 902"}));
        assert_eq!(gh.invocations().len(), 3);
    }
}

use openwiz_adapter_github::plan::Request;
use serde_json::Value;

fn graphql_error(response: &mut Value, path: Option<Value>, exit: i32) {
    let mut doc: Value = serde_json::from_str(response["stdout"].as_str().unwrap()).unwrap();
    let mut error = json!({"message":"synthetic-secret /synthetic/path"});
    if let Some(path) = path {
        error["path"] = path;
    }
    doc["errors"] = json!([error]);
    response["stdout"] = json!(doc.to_string());
    response["stderr"] = json!("synthetic-secret /synthetic/path");
    response["exit"] = json!(exit);
}

#[test]
fn e11_plan_review_r4_validates_the_entire_path_before_a_bubbled_null() {
    let mut failures = vec![];
    for (case, suffix, malformed) in [
        ("boolean", json!(false), true),
        ("negative", json!(-1), true),
        ("float", json!(1.0), true),
        ("empty-field", json!(""), true),
        ("null", Value::Null, true),
        ("object", json!({}), true),
        ("array", json!([]), true),
        ("field", json!("title"), false),
        ("index", json!(0), false),
    ] {
        for exit in [0, 1] {
            let mut responses = p::responses(
                vec![
                    p::issue(901, None, &[902], &[], &[]),
                    p::issue(902, Some(901), &[], &[], &["ready-for-agent"]),
                ],
                vec![],
            );
            graphql_error(
                &mut responses[2],
                Some(json!([
                    "repository",
                    "issues",
                    "nodes",
                    1,
                    "milestone",
                    "title",
                    suffix
                ])),
                exit,
            );
            let gh = p::github(&format!("ep1-review-r4-{case}-{exit}"), responses);
            let room = Fake::new(&format!("ep1-review-r4-room-{case}-{exit}"), "normal");
            let v = p::read(&p::serve(&room, &gh, Default::default()));
            let ticket = p::row(&v, 902);
            assert_eq!(v["coverage"]["state"], "partial");
            assert_eq!(v["tickets"].as_array().unwrap().len(), 1);
            assert_eq!(ticket["title"], json!({"known":"Synthetic issue 902"}));
            if malformed {
                if !ticket["pr"]["unknown"].is_string()
                    || !ticket["blockers"]["unknown"].is_string()
                    || !ticket["labels"]["unknown"].is_string()
                {
                    failures.push(format!(
                        "{case}, exit {exit}: pr={}, blockers={}",
                        ticket["pr"], ticket["blockers"]
                    ));
                }
            } else {
                assert_eq!(ticket["labels"], json!({"known":["ready-for-agent"]}));
                assert_eq!(ticket["pr"], json!({"known":null}), "{case}");
                assert_eq!(ticket["blockers"], json!({"known":[]}), "{case}");
                assert_eq!(ticket["spec"], json!({"known":901}), "{case}");
            }
            assert!(ticket["state"]["unknown"].is_string());
            assert!(v["critical_chain"]["unknown"].is_string());
            assert!(!v.to_string().contains("synthetic-secret"));
            assert!(!v.to_string().contains("/synthetic/path"));
            assert_eq!(gh.invocations().len(), 3);
            assert!(room.invocations().is_empty());
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn e11_plan_review_r1_graphql_error_exits_retain_first_later_and_direct_rows() {
    for phase in ["first", "later", "direct"] {
        let mut spec = p::issue(901, None, &[902], &[], &[]);
        let ticket = p::issue(902, Some(901), &[], &[], &["ready-for-agent"]);
        let mut responses;
        match phase {
            "first" => {
                spec["title"] = Value::Null;
                responses = p::responses(vec![spec, ticket], vec![]);
                graphql_error(
                    &mut responses[2],
                    Some(json!(["repository", "issues", "nodes", 0, "title"])),
                    1,
                );
            }
            "later" => {
                responses = p::responses(vec![spec], vec![]);
                let mut doc: Value =
                    serde_json::from_str(responses[2]["stdout"].as_str().unwrap()).unwrap();
                doc["data"]["repository"]["issues"]["totalCount"] = json!(3);
                doc["data"]["repository"]["issues"]["pageInfo"] =
                    json!({"hasNextPage":true,"endCursor":"I2"});
                responses[2]["stdout"] = json!(doc.to_string());
                let mut sibling = p::issue(904, None, &[], &[], &[]);
                sibling["title"] = Value::Null;
                let mut page = p::page(vec![ticket, sibling]);
                page["totalCount"] = json!(3);
                let mut response = p::answer(Request::Issues, Some("I2"), json!({"issues":page}));
                graphql_error(
                    &mut response,
                    Some(json!(["repository", "issues", "nodes", 1, "title"])),
                    1,
                );
                responses.push(response);
            }
            _ => {
                responses = p::responses(vec![spec], vec![]);
                let mut response = p::answer(Request::Issue(902), None, json!({"issue":ticket}));
                graphql_error(
                    &mut response,
                    Some(json!(["repository", "issue", "milestone"])),
                    1,
                );
                responses.push(response);
            }
        }
        let gh = p::github(&format!("ep1-review-r1-exit-{phase}"), responses);
        let room = Fake::new(&format!("ep1-review-r1-exit-room-{phase}"), "normal");
        let v = p::read(&p::serve(&room, &gh, Default::default()));
        assert_eq!(v["coverage"]["state"], "partial");
        assert_eq!(v["tickets"].as_array().unwrap().len(), 1, "{phase}: {v:#}");
        assert_eq!(
            p::row(&v, 902)["title"],
            json!({"known":"Synthetic issue 902"})
        );
        assert_eq!(
            p::row(&v, 902)["labels"],
            json!({"known":["ready-for-agent"]})
        );
        if phase != "direct" {
            assert_eq!(p::row(&v, 902)["state"], json!({"known":"ready"}));
        }
        assert!(v["critical_chain"]["unknown"].is_string());
        assert_eq!(gh.invocations().len(), if phase == "first" { 3 } else { 4 });
        assert!(!v.to_string().contains("synthetic-secret"));
        assert!(!v.to_string().contains("/synthetic/path"));
        assert!(room.invocations().is_empty());
    }
}

#[test]
fn e11_plan_review_r1_nullable_error_paths_do_not_become_known_absence() {
    for (case, field, path, unknown) in [
        (
            0,
            "milestone",
            Some(json!(["repository", "issues", "nodes", 1, "milestone"])),
            true,
        ),
        (
            1,
            "milestone",
            Some(json!([
                "repository",
                "issues",
                "nodes",
                1,
                "milestone",
                "title"
            ])),
            true,
        ),
        (
            2,
            "milestone",
            Some(json!(["repository", "issues", "nodes", 0, "title"])),
            false,
        ),
        (3, "milestone", None, true),
        (
            4,
            "milestone",
            Some(json!(["repository", "issues", "nodes", 1.0, "milestone"])),
            true,
        ),
        (
            5,
            "milestone",
            Some(json!(["repository", "issues", "nodes", 99, "milestone"])),
            true,
        ),
        (
            6,
            "parent",
            Some(json!(["repository", "issues", "nodes", 2, "parent"])),
            true,
        ),
        (
            7,
            "parent",
            Some(json!([
                "repository",
                "issues",
                "nodes",
                2,
                "parent",
                "title"
            ])),
            true,
        ),
        (
            8,
            "parent",
            Some(json!(["repository", "issues", "nodes", 0, "title"])),
            false,
        ),
    ] {
        let mut spec = p::issue(901, None, &[902], &[], &[]);
        if !unknown {
            spec["title"] = Value::Null;
        }
        let issues = vec![
            spec,
            p::issue(902, Some(901), &[], &[907], &["ready-for-agent"]),
            p::issue(907, None, &[], &[], &["ready-for-agent"]),
        ];
        let mut responses = p::responses(issues, vec![]);
        graphql_error(&mut responses[2], path, 0);
        let gh = p::github(&format!("ep1-review-r1-null-{case}"), responses);
        let room = Fake::new(&format!("ep1-review-r1-null-room-{case}"), "normal");
        let v = p::read(&p::serve(&room, &gh, Default::default()));
        assert_eq!(v["coverage"]["state"], "partial");
        if field == "milestone" {
            if unknown {
                assert!(
                    p::row(&v, 902)["state"]["unknown"].is_string(),
                    "{case}: {v:#}"
                );
            } else {
                assert_eq!(p::row(&v, 902)["state"], json!({"known":"blocked"}));
            }
        } else if unknown {
            assert!(
                p::row(&v, 907)["spec"]["unknown"].is_string(),
                "{case}: {v:#}"
            );
            assert!(p::row(&v, 907)["lane"]["unknown"].is_string());
        } else {
            assert_eq!(p::row(&v, 907)["spec"], json!({"known":null}));
            assert_eq!(p::row(&v, 907)["lane"], json!({"known":null}));
        }
        assert_eq!(
            p::row(&v, 902)["title"],
            json!({"known":"Synthetic issue 902"})
        );
        assert!(v["critical_chain"]["unknown"].is_string());
        assert!(!v.to_string().contains("synthetic-secret"));
    }
}

#[test]
fn e11_plan_review_r1_overlapping_paths_keep_independent_fields_known() {
    let mut response = p::responses(
        vec![
            p::issue(901, None, &[902], &[], &[]),
            p::issue(902, Some(901), &[], &[], &["ready-for-agent"]),
        ],
        vec![],
    );
    graphql_error(
        &mut response[2],
        Some(json!(["repository", "issues", "nodes", 1, "milestone"])),
        0,
    );
    let mut doc: Value = serde_json::from_str(response[2]["stdout"].as_str().unwrap()).unwrap();
    doc["errors"].as_array_mut().unwrap().push(json!({"message":"synthetic-secret","path":["repository","issues","nodes",1,"milestone","title"]}));
    response[2]["stdout"] = json!(doc.to_string());
    let gh = p::github("ep1-review-r1-overlapping", response);
    let room = Fake::new("ep1-review-r1-overlapping-room", "normal");
    let v = p::read(&p::serve(&room, &gh, Default::default()));
    assert_eq!(
        p::row(&v, 902)["labels"],
        json!({"known":["ready-for-agent"]})
    );
    assert_eq!(p::row(&v, 902)["spec"], json!({"known":901}));
    assert!(p::row(&v, 902)["state"]["unknown"].is_string());
    assert!(v["critical_chain"]["unknown"].is_string());
}

#[test]
fn e11_plan_review_r1_errored_list_elements_keep_usable_rows_and_unknown_edges() {
    let mut ticket = p::issue(902, Some(901), &[], &[908, 907], &["ready-for-agent"]);
    ticket["blockedBy"]["nodes"][0] = Value::Null;
    let mut response = p::responses(
        vec![
            p::issue(901, None, &[902], &[], &[]),
            ticket,
            p::issue(907, None, &[], &[], &["ready-for-agent"]),
        ],
        vec![],
    );
    graphql_error(
        &mut response[2],
        Some(json!([
            "repository",
            "issues",
            "nodes",
            1,
            "blockedBy",
            "nodes",
            0,
            "number"
        ])),
        0,
    );
    let gh = p::github("ep1-review-r1-list-element", response);
    let room = Fake::new("ep1-review-r1-list-element-room", "normal");
    let v = p::read(&p::serve(&room, &gh, Default::default()));
    assert_eq!(v["tickets"].as_array().unwrap().len(), 2);
    assert_eq!(
        p::row(&v, 907)["title"],
        json!({"known":"Synthetic issue 907"})
    );
    assert!(p::row(&v, 902)["blockers"]["unknown"].is_string());
    assert!(p::row(&v, 902)["state"]["unknown"].is_string());
    assert!(v["critical_chain"]["unknown"].is_string());
}

#[test]
fn e11_plan_review_r1_unusable_error_stdout_never_becomes_a_complete_empty_plan() {
    for (case, stdout) in [
        "",
        "not JSON",
        r#"{"data":null}"#,
        r#"{"data":{"repository":{"issues":null}}}"#,
    ]
    .into_iter()
    .enumerate()
    {
        let mut responses =
            p::responses(vec![], vec![json!({"number":7,"title":"Retained version"})]);
        responses[2]["stdout"] = json!(stdout);
        responses[2]["exit"] = json!(1);
        responses[2]["stderr"] = json!("synthetic-secret /synthetic/path");
        let gh = p::github(&format!("ep1-review-r1-bad-output-{case}"), responses);
        let room = Fake::new(&format!("ep1-review-r1-bad-output-room-{case}"), "normal");
        let v = p::read(&p::serve(&room, &gh, Default::default()));
        assert_eq!(v["coverage"]["state"], "partial");
        assert_eq!(v["tickets"], json!([]));
        assert_eq!(v["lanes"].as_array().unwrap().len(), 1);
        assert!(v["critical_chain"]["unknown"].is_string());
        assert!(!v.to_string().contains("synthetic-secret"));
        assert_eq!(gh.invocations().len(), 3);
    }
}

#[test]
fn e11_plan_review_r1_unlocated_error_exit_preserves_positive_rows_without_guessing_absences() {
    let mut responses = p::responses(
        vec![
            p::issue(901, None, &[902], &[], &[]),
            p::issue(902, Some(901), &[], &[], &["ready-for-agent"]),
        ],
        vec![],
    );
    responses[2]["exit"] = json!(1);
    let gh = p::github("ep1-review-r1-unlocated-exit", responses);
    let room = Fake::new("ep1-review-r1-unlocated-exit-room", "normal");
    let v = p::read(&p::serve(&room, &gh, Default::default()));
    assert_eq!(v["coverage"]["state"], "partial");
    assert_eq!(
        p::row(&v, 902)["title"],
        json!({"known":"Synthetic issue 902"})
    );
    assert_eq!(p::row(&v, 902)["spec"], json!({"known":901}));
    for field in ["pr", "blockers", "labels", "state"] {
        assert!(
            p::row(&v, 902)[field]["unknown"].is_string(),
            "{field}: {v:#}"
        );
    }
    assert!(v["critical_chain"]["unknown"].is_string());
}
