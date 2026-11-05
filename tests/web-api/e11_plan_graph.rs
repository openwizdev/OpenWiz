//! EP1 worked graph examples; expected answers are literal, independent paths.
use crate::{e11_plan_support as p, fake::Fake};
use serde_json::json;

fn graph(name: &str, edges: &[(u64, &[u64])]) -> serde_json::Value {
    let children: Vec<_> = edges.iter().map(|&(n, _)| n).collect();
    let mut issues = vec![p::issue(901, None, &children, &[], &[])];
    issues.extend(
        edges
            .iter()
            .map(|&(n, b)| p::issue(n, Some(901), &[], b, &["ready-for-agent"])),
    );
    let gh = p::github(name, p::responses(issues, vec![]));
    let room = Fake::new(&format!("{name}-room"), "normal");
    p::read(&p::serve(&room, &gh, Default::default()))
}
#[test]
fn e11_plan_chain_counts_distinct_diamond_reach_and_uses_all_numeric_ties() {
    for (name, edges, expected) in [
        (
            "ep1-diamond",
            vec![
                (902, &[][..]),
                (903, &[902][..]),
                (904, &[902][..]),
                (905, &[903, 904][..]),
            ],
            json!({"root":902,"blocked_count":3,"path":[902,903,905]}),
        ),
        (
            "ep1-length-tie",
            vec![
                (902, &[][..]),
                (903, &[902][..]),
                (904, &[902][..]),
                (905, &[903, 904][..]),
                (906, &[][..]),
                (907, &[906][..]),
                (908, &[907][..]),
                (909, &[908][..]),
            ],
            json!({"root":906,"blocked_count":3,"path":[906,907,908,909]}),
        ),
        (
            "ep1-root-tie",
            vec![
                (910, &[][..]),
                (911, &[910][..]),
                (912, &[910][..]),
                (913, &[910][..]),
                (914, &[910][..]),
                (915, &[][..]),
                (916, &[915][..]),
                (917, &[915][..]),
                (918, &[915][..]),
                (919, &[915][..]),
                (906, &[][..]),
                (907, &[906][..]),
                (908, &[907][..]),
                (909, &[908][..]),
            ],
            json!({"root":910,"blocked_count":4,"path":[910,911]}),
        ),
        (
            "ep1-single",
            vec![(902, &[][..])],
            json!({"root":902,"blocked_count":0,"path":[902]}),
        ),
    ] {
        let v = graph(name, &edges);
        assert_eq!(v["coverage"]["state"], "complete");
        assert_eq!(v["critical_chain"], json!({"known":expected}), "{name}");
    }
}
#[test]
fn e11_plan_cycles_and_missing_nodes_keep_rows_but_no_global_maximum() {
    let v = graph("ep1-cycle", &[(902, &[904]), (903, &[902]), (904, &[903])]);
    assert_eq!(v["tickets"].as_array().unwrap().len(), 3);
    assert_eq!(v["coverage"]["state"], "partial");
    assert!(v["critical_chain"]["unknown"].is_string());
    assert!(
        v["coverage"]["gaps"]
            .as_array()
            .unwrap()
            .iter()
            .any(|g| g["kind"] == "malformed")
    );
    let v = graph("ep1-missing", &[(902, &[907])]);
    assert_eq!(v["tickets"].as_array().unwrap().len(), 2);
    assert_eq!(v["coverage"]["state"], "partial");
    assert!(v["critical_chain"]["unknown"].is_string());
    assert!(p::row(&v, 907)["title"]["unknown"].is_string());
    assert!(p::row(&v, 902)["dependents"]["unknown"].is_string());
}
#[test]
fn e11_plan_empty_and_finished_plans_have_a_known_null_chain() {
    let gh = p::github(
        "ep1-empty",
        p::responses(vec![], vec![json!({"number":7,"title":"Empty version"})]),
    );
    let room = Fake::new("ep1-empty-room", "normal");
    let v = p::read(&p::serve(&room, &gh, Default::default()));
    assert_eq!(v["coverage"]["state"], "complete");
    assert_eq!(v["tickets"], json!([]));
    assert_eq!(v["critical_chain"], json!({"known":null}));
    assert_eq!(v["lanes"].as_array().unwrap().len(), 1);
    for (name, both) in [("ep1-finished", true), ("ep1-remove-merged", false)] {
        let mut a = p::issue(902, Some(901), &[], &[], &["ready-for-agent"]);
        p::closing(&mut a, &[1902]);
        let mut b = p::issue(903, Some(901), &[], &[902], &["ready-for-agent"]);
        let mut extra = p::pr_responses(1902, 902, "MERGED", false, json!([]), vec![], true);
        if both {
            p::closing(&mut b, &[1903]);
            extra.extend(p::pr_responses(
                1903,
                903,
                "MERGED",
                false,
                json!([]),
                vec![],
                true,
            ));
        }
        let mut responses = p::responses(
            vec![p::issue(901, None, &[902, 903], &[], &[]), a, b],
            vec![],
        );
        responses.extend(extra);
        let gh = p::github(name, responses);
        let room = Fake::new(&format!("{name}-room"), "normal");
        let v = p::read(&p::serve(&room, &gh, Default::default()));
        assert_eq!(
            v["critical_chain"],
            if both {
                json!({"known":null})
            } else {
                json!({"known":{"root":903,"blocked_count":0,"path":[903]}})
            }
        );
        assert_eq!(p::row(&v, 902)["dependents"], json!({"known":[903]}));
    }
}
