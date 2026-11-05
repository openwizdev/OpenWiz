//! EP1 state precedence and complete-input requirements at the HTTP seam.
use crate::{e11_plan_support as p, fake::Fake};
use serde_json::json;

#[test]
fn e11_plan_preserves_every_fleet_state_and_ordered_column() {
    let children: Vec<u64> = (902..=917).collect();
    let mut issues = vec![p::issue(901, None, &children, &[], &[])];
    let mut extra = vec![];
    for n in children {
        let labels = match n {
            907 | 908 => vec!["held", "needs-info", "ready-for-human"],
            910 => vec!["needs-info", "ready-for-agent"],
            911 | 912 => vec!["ready-for-human"],
            913 => vec![],
            _ => vec!["ready-for-agent"],
        };
        let mut i = p::issue(
            n,
            Some(901),
            &[],
            if n == 903 || n == 912 { &[902] } else { &[] },
            &labels,
        );
        if n == 908 || n == 909 {
            i["state"] = json!("CLOSED");
        }
        if matches!(n,904..=908|914..=917) {
            let pr = n + 1000;
            p::closing(&mut i, &[pr]);
            let state = if n == 908 || n == 914 {
                "MERGED"
            } else {
                "OPEN"
            };
            let checks = if n == 916 {
                json!([{"name":"synthetic","bucket":"fail"}])
            } else if n == 917 {
                json!([])
            } else {
                json!([{"name":"synthetic","bucket":"pass"}])
            };
            let current = format!("VERDICT: CHANGES at {}", p::HEAD);
            let old = format!("VERDICT: CHANGES at {}", "c".repeat(40));
            let bodies = if n == 906 {
                vec![current.as_str()]
            } else if n == 915 {
                vec![old.as_str()]
            } else {
                vec![]
            };
            extra.extend(p::pr_responses(
                pr,
                n,
                state,
                n == 904,
                checks,
                bodies,
                n != 914,
            ));
        }
        issues.push(i);
    }
    let mut responses = p::responses(issues, vec![]);
    responses.extend(extra);
    let gh = p::github("ep1-states", responses);
    let room = Fake::new("ep1-states-room", "normal");
    let s = p::serve(&room, &gh, Default::default());
    let v = p::read(&s);
    assert_eq!(v["coverage"], json!({"state":"complete","gaps":[]}));
    for (n, state, column, yours) in [
        (902, Some("ready"), Some("waiting"), false),
        (903, Some("blocked"), Some("waiting"), false),
        (904, Some("building"), Some("building"), false),
        (905, Some("in_review"), Some("building"), false),
        (906, Some("changes_requested"), Some("building"), false),
        (907, Some("held"), Some("needs_you"), true),
        (908, Some("merged"), Some("done"), true),
        (909, None, None, false),
        (910, Some("ready"), Some("needs_you"), false),
        (911, None, Some("needs_you"), true),
        (912, Some("blocked"), Some("waiting"), true),
        (913, None, None, false),
        (914, None, None, false),
        (915, Some("in_review"), Some("building"), false),
        (916, Some("building"), Some("building"), false),
        (917, Some("building"), Some("building"), false),
    ] {
        let r = p::row(&v, n);
        for (field, expected) in [("state", state), ("column", column)] {
            match expected {
                Some(s) => assert_eq!(r[field], json!({"known":s}), "#{n} {field}"),
                None => assert!(r[field]["unknown"].is_string(), "#{n} {field}: {r}"),
            }
        }
        assert_eq!(r["yours"], json!({"known":yours}), "#{n}");
    }
    assert_eq!(
        v["critical_chain"],
        json!({"known":{"root":902,"blocked_count":2,"path":[902,903]}})
    );
    assert_eq!(
        p::row(&v, 905)["pr"],
        json!({"known":{"number":1905,"url":format!("{}/pull/1905",p::REPO)}})
    );
    assert!(room.invocations().is_empty());
    assert_eq!(gh.invocations().len(), 28);
}

#[test]
fn e11_plan_every_required_pr_read_is_fail_closed_even_for_a_held_ticket() {
    for (case, change) in ["pr", "checks", "comments", "readback", "reciprocal", "url"]
        .into_iter()
        .enumerate()
    {
        let mut i = p::issue(902, Some(901), &[], &[], &["held", "ready-for-agent"]);
        p::closing(
            &mut i,
            if change == "ambiguous" {
                &[1902, 1903]
            } else {
                &[1902]
            },
        );
        let state = if change == "readback" {
            "MERGED"
        } else {
            "OPEN"
        };
        let mut extra = p::pr_responses(
            1902,
            902,
            state,
            false,
            json!([{"name":"synthetic","bucket":"pass"}]),
            vec![],
            true,
        );
        if change == "ambiguous" {
            extra.extend(p::pr_responses(
                1903,
                902,
                "OPEN",
                false,
                json!([]),
                vec![],
                false,
            ));
        }
        match change {
            "pr" => {
                extra[0] = json!({"argv":extra[0]["argv"],"exit":1,"stderr":"synthetic-secret /synthetic/path"})
            }
            "checks" | "comments" | "readback" => {
                let ix = if change == "comments" { 2 } else { 1 };
                extra[ix] = json!({"argv":extra[ix]["argv"],"exit":1,"stderr":"synthetic-secret /synthetic/path"});
            }
            "reciprocal" | "url" => {
                let mut node = p::pr(
                    1902,
                    if change == "reciprocal" { 903 } else { 902 },
                    "OPEN",
                    false,
                );
                if change == "url" {
                    node["url"] = json!("https://github.com/synthetic-owner/other/pull/1902");
                }
                extra[0] = p::answer(
                    openwiz_adapter_github::plan::Request::Pr(1902),
                    None,
                    json!({"pullRequest":node}),
                );
            }
            _ => {}
        }
        let mut responses = p::responses(vec![p::issue(901, None, &[902], &[], &[]), i], vec![]);
        responses.extend(extra);
        let gh = p::github(&format!("ep1-pr-miss-{case}"), responses);
        let room = Fake::new(&format!("ep1-pr-miss-room-{case}"), "normal");
        let s = p::serve(&room, &gh, Default::default());
        let v = p::read(&s);
        assert_eq!(v["coverage"]["state"], "partial", "{change}");
        assert!(
            p::row(&v, 902)["state"]["unknown"].is_string(),
            "{change}: {v:#}"
        );
        assert!(v["critical_chain"]["unknown"].is_string(), "{change}");
        let text = v.to_string();
        assert!(!text.contains("synthetic-secret"));
        assert!(!text.contains("/synthetic/path"));
    }
}
