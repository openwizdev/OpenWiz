//! EP1 pagination, strict input, URL identity and source-clock proofs.
use crate::{e11_plan_support as p, fake::Fake};
use openwiz_adapter_github::{
    allowlist,
    plan::{Relation, Request},
};
use serde_json::{Value, json};

fn more(nodes: Vec<Value>, total: u64, cursor: &str) -> Value {
    json!({"nodes":nodes,"totalCount":total,"pageInfo":{"hasNextPage":true,"endCursor":cursor}})
}

#[test]
fn e11_plan_pages_repository_and_nested_relations_without_skipping_first_pages() {
    let mut spec = p::issue(901, None, &[], &[], &[]);
    spec["subIssues"] = more(vec![p::link(902)], 2, "C2");
    spec["milestone"] = json!({"number":7,"title":"Version seven"});
    let mut a = p::issue(902, Some(901), &[], &[], &["ready-for-agent"]);
    a["closedByPullRequestsReferences"] = more(
        vec![json!({"number":1902,"url":format!("{}/pull/1902",p::REPO)})],
        2,
        "P2",
    );
    let mut b = p::issue(903, Some(901), &[], &[], &[]);
    b["labels"] = more(vec![json!({"name":"ready-for-human"})], 2, "L2");
    b["blockedBy"] = more(vec![p::link(902)], 2, "B2");
    let first = vec![spec, a];
    let rest = vec![
        b,
        p::issue(905, None, &[909], &[], &[]),
        p::issue(907, None, &[], &[909], &["ready-for-agent"]),
        p::issue(909, Some(905), &[], &[], &["ready-for-agent"]),
    ];
    let mut responses = p::responses(vec![], vec![]);
    responses[1] = p::answer(
        Request::Milestones,
        None,
        json!({"milestones":more(vec![json!({"number":7,"title":"Version seven"})],2,"M2")}),
    );
    responses[2] = p::answer(Request::Issues, None, json!({"issues":more(first,6,"I2")}));
    responses.extend([
        p::answer(Request::Milestones,Some("M2"),json!({"milestones":p::page(vec![json!({"number":8,"title":"Empty version"})])})),
        p::answer(Request::Issues,Some("I2"),json!({"issues":p::page(rest)})),
        p::answer(Request::Relation(901,Relation::SubIssues),Some("C2"),json!({"issue":{"subIssues":p::page(vec![p::link(903)])}})),
        p::answer(Request::Relation(902,Relation::ClosingPrs),Some("P2"),json!({"issue":{"closedByPullRequestsReferences":p::page(vec![json!({"number":1903,"url":format!("{}/pull/1903",p::REPO)})])}})),
        p::answer(Request::Relation(903,Relation::Labels),Some("L2"),json!({"issue":{"labels":p::page(vec![json!({"name":"synthetic-label"})])}})),
        p::answer(Request::Relation(903,Relation::BlockedBy),Some("B2"),json!({"issue":{"blockedBy":p::page(vec![p::link(907)])}})),
    ]);
    // Every page reports the connection's total, rather than its page size.
    for response in &mut responses {
        if let Some(raw) = response["stdout"].as_str() {
            let mut v: Value = serde_json::from_str(raw).unwrap();
            for (pointer, total) in [
                ("/data/repository/milestones", 2),
                ("/data/repository/issues", 6),
                ("/data/repository/issue/subIssues", 2),
                ("/data/repository/issue/closedByPullRequestsReferences", 2),
                ("/data/repository/issue/labels", 2),
                ("/data/repository/issue/blockedBy", 2),
            ] {
                if let Some(p) = v.pointer_mut(pointer) {
                    p["totalCount"] = json!(total);
                }
            }
            response["stdout"] = json!(v.to_string());
        }
    }
    responses.extend(p::pr_responses(
        1902,
        902,
        "OPEN",
        false,
        json!([{"name":"synthetic","bucket":"pass"}]),
        vec![],
        false,
    ));
    responses.extend(p::pr_responses(
        1903,
        902,
        "CLOSED",
        false,
        json!([]),
        vec![],
        false,
    ));
    let gh = p::github("ep1-paging", responses);
    let room = Fake::new("ep1-paging-room", "normal");
    let v = p::read(&p::serve(&room, &gh, Default::default()));
    assert_eq!(v["coverage"], json!({"state":"complete","gaps":[]}));
    assert_eq!(
        v["tickets"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| r["number"].as_u64().unwrap())
            .collect::<Vec<_>>(),
        vec![902, 903, 907, 909]
    );
    assert_eq!(p::row(&v, 903)["blockers"], json!({"known":[902,907]}));
    assert_eq!(
        p::row(&v, 903)["labels"],
        json!({"known":["ready-for-human","synthetic-label"]})
    );
    assert_eq!(
        v["critical_chain"],
        json!({"known":{"root":909,"blocked_count":2,"path":[909,907,903]}})
    );
    assert_eq!(gh.invocations().len(), 13);
}

#[test]
fn e11_plan_failed_later_page_preserves_read_rows_and_unknown_inverse() {
    let mut responses = p::responses(
        vec![],
        vec![json!({"number":7,"title":"Retained empty version"})],
    );
    responses[2] = p::answer(
        Request::Issues,
        None,
        json!({"issues":more(vec![p::issue(901,None,&[902],&[],&[]),p::issue(902,Some(901),&[],&[],&["ready-for-agent"])],4,"I2")}),
    );
    responses.push(json!({"argv":Request::Issues.argv(Some("I2")),"exit":1,"stderr":"synthetic-secret /synthetic/path"}));
    let gh = p::github("ep1-page-failure", responses);
    let room = Fake::new("ep1-page-failure-room", "normal");
    let v = p::read(&p::serve(&room, &gh, Default::default()));
    assert_eq!(v["coverage"]["state"], "partial");
    assert_eq!(v["tickets"].as_array().unwrap().len(), 1);
    assert_eq!(
        p::row(&v, 902)["title"],
        json!({"known":"Synthetic issue 902"})
    );
    assert!(p::row(&v, 902)["dependents"]["unknown"].is_string());
    assert!(v["critical_chain"]["unknown"].is_string());
    assert!(!v.to_string().contains("synthetic-secret"));
}

#[test]
fn e11_plan_malformed_pages_totals_links_and_fields_are_never_complete() {
    for (case, kind) in [
        "duplicate-key",
        "float-number",
        "extra-key",
        "wrong-type",
        "missing-field",
        "truncated",
        "duplicate-row",
        "foreign-url",
        "wrong-number",
        "foreign-blocker",
        "cycle-cursor",
        "failed-root",
    ]
    .into_iter()
    .enumerate()
    {
        let mut t = p::issue(902, Some(901), &[], &[], &["ready-for-agent"]);
        match kind {
            "wrong-type" => t["labels"] = json!([]),
            "missing-field" => {
                t.as_object_mut().unwrap().remove("parent");
            }
            "foreign-url" => {
                t["url"] = json!("https://github.com/synthetic-owner/other/issues/902")
            }
            "wrong-number" => t["url"] = json!(format!("{}/issues/903", p::REPO)),
            "foreign-blocker" => {
                t["blockedBy"] = p::page(vec![
                    json!({"number":902,"url":"https://github.com/synthetic-owner/other/issues/902"}),
                ])
            }
            _ => {}
        }
        let mut rows = vec![p::issue(901, None, &[902], &[], &[]), t];
        if kind == "duplicate-row" {
            rows.push(rows[1].clone());
        }
        let mut responses = p::responses(rows, vec![]);
        match kind {
            "duplicate-key" | "float-number" | "extra-key" => {
                let s = responses[2]["stdout"].as_str().unwrap().to_owned();
                responses[2]["stdout"] = json!(match kind {
                    "duplicate-key" =>
                        s.replacen("\"number\":902", "\"number\":902,\"number\":902", 1),
                    "float-number" => s.replacen("\"number\":902", "\"number\":902.0", 1),
                    _ => s.replacen(
                        "\"repository\":{",
                        "\"repository\":{\"unexpected\":true,",
                        1
                    ),
                });
            }
            "truncated" | "cycle-cursor" => {
                let mut v: Value =
                    serde_json::from_str(responses[2]["stdout"].as_str().unwrap()).unwrap();
                v["data"]["repository"]["issues"]["totalCount"] = json!(5);
                if kind == "cycle-cursor" {
                    v["data"]["repository"]["issues"]["pageInfo"] =
                        json!({"hasNextPage":true,"endCursor":"I2"});
                    responses.push(p::answer(
                        Request::Issues,
                        Some("I2"),
                        json!({"issues":more(vec![],5,"I2")}),
                    ));
                }
                responses[2]["stdout"] = json!(v.to_string());
            }
            "failed-root" => {
                responses[2] =
                    json!({"argv":Request::Issues.argv(None),"exit":1,"stderr":"synthetic-secret"})
            }
            _ => {}
        }
        let gh = p::github(&format!("ep1-malformed-{case}"), responses);
        let room = Fake::new(&format!("ep1-malformed-room-{case}"), "normal");
        let v = p::read(&p::serve(&room, &gh, Default::default()));
        assert_eq!(v["coverage"]["state"], "partial", "{kind}: {v:#}");
        assert!(v["critical_chain"]["unknown"].is_string(), "{kind}: {v:#}");
    }
}

#[test]
fn e11_plan_allowlist_refuses_mutations_extra_flags_and_noncanonical_parameters() {
    for request in [
        Request::Milestones,
        Request::Issues,
        Request::Issue(902),
        Request::Pr(1902),
        Request::Relation(902, Relation::BlockedBy),
        Request::Relation(1902, Relation::Comments),
    ] {
        let argv = request.argv(None);
        let words: Vec<_> = argv.iter().map(String::as_str).collect();
        assert!(allowlist::Invocation::new(&words).is_some());
        for changed in [
            argv.iter()
                .cloned()
                .chain(["--method".to_owned(), "POST".to_owned()])
                .collect::<Vec<_>>(),
            argv.iter()
                .map(|s| s.replace("query=", "query=mutation "))
                .collect(),
            argv.iter()
                .map(|s| s.replace("owner={owner}", "owner=foreign"))
                .collect(),
        ] {
            let words: Vec<_> = changed.iter().map(String::as_str).collect();
            assert!(allowlist::Invocation::new(&words).is_none(), "{changed:?}");
        }
    }
    for request in [Request::Issue(0), Request::Issue(10000000000)] {
        let argv = request.argv(None);
        assert!(
            allowlist::Invocation::new(&argv.iter().map(String::as_str).collect::<Vec<_>>())
                .is_none()
        );
    }
    for cursor in ["", "bad&cursor", "$(synthetic)", "é"] {
        let argv = Request::Issues.argv(Some(cursor));
        assert!(
            allowlist::Invocation::new(&argv.iter().map(String::as_str).collect::<Vec<_>>())
                .is_none()
        );
    }
}

#[test]
fn e11_plan_freshness_ages_the_oldest_read_and_does_not_hide_partial_coverage() {
    use openwiz_core::{model::Timestamp, ops::Clock};
    use std::{
        sync::{
            Arc,
            atomic::{AtomicUsize, Ordering},
        },
        time::Instant,
    };
    struct C {
        start: i64,
        end: i64,
        calls: AtomicUsize,
    }
    impl Clock for C {
        fn now(&self) -> Timestamp {
            Timestamp(if self.calls.fetch_add(1, Ordering::SeqCst) == 0 {
                self.start
            } else {
                self.end
            })
        }
        fn monotonic(&self) -> Instant {
            Instant::now()
        }
    }
    for (case, start, end, state, partial) in [
        (0, 100_000, 170_000, "fresh", false),
        (1, 100_000, 170_001, "stale", false),
        (2, -1, 170_000, "unknown", false),
        (3, 200_000, 170_000, "unknown", false),
        (4, 100_000, -1, "unknown", false),
        (5, 100_000, 170_000, "fresh", true),
    ] {
        let mut responses = p::responses(vec![], vec![]);
        if partial {
            responses[2] = json!({"argv":Request::Issues.argv(None),"exit":1});
        }
        let gh = p::github(&format!("ep1-clock-{case}"), responses);
        let room = Fake::new(&format!("ep1-clock-room-{case}"), "normal");
        let s = p::serve_clock(
            &room,
            &gh,
            Default::default(),
            Arc::new(C {
                start,
                end,
                calls: AtomicUsize::new(0),
            }),
        );
        let v = p::read(&s);
        assert_eq!(v["snapshot_at"], end.max(0));
        assert_eq!(v["freshness"]["state"], state);
        assert_eq!(
            v["coverage"]["state"],
            if partial { "partial" } else { "complete" }
        );
        if state != "unknown" {
            assert_eq!(v["freshness"]["snapshot_at"], json!({"known":start}));
        }
    }
}
