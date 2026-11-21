#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../support/dirs.rs"]
mod dirs;

use std::fs;
use std::path::Path;
use std::time::{Duration, Instant};

use serde_json::{Value, json};

use openwiz_adapter_github::fleets::GitHubFleets;
use openwiz_cli::fleets;
use openwiz_core::model::Timestamp;
use openwiz_core::ops::Clock;

use super::{
    FIXTURES, ISSUE_LIST, PR_LIST, checks_argv, comments_argv, commit, fleet, json_run, read,
    stage, ticket,
};
use crate::schema::{load_schema, validate};
use crate::support::FakeGh;

fn pr_list(edit: impl FnOnce(&mut Vec<Value>)) -> Value {
    let path = Path::new(FIXTURES).join("fleets/complete/prs.json");
    let mut prs: Vec<Value> = serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap();
    edit(&mut prs);
    json!({"argv": PR_LIST, "stdout": serde_json::to_string(&prs).unwrap()})
}

fn issue_list(edit: impl FnOnce(&mut Vec<Value>)) -> Value {
    let path = Path::new(FIXTURES).join("fleets/complete/issues.json");
    let mut rows: Vec<Value> = serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap();
    edit(&mut rows);
    json!({"argv": ISSUE_LIST, "stdout": serde_json::to_string(&rows).unwrap()})
}

fn pr_row(number: u64, state: &str, head: char, closes: &[u64], merge: Option<char>) -> Value {
    let refs: Vec<Value> = closes
        .iter()
        .map(|n| {
            json!({"id": format!("syn-issue-{n:04}"), "number": n,
                   "repository": {"id": "syn-repo-0001", "name": "syn-example-repo",
                                  "owner": {"id": "syn-owner-0001", "login": "syn-owner"}},
                   "url": format!("https://example.invalid/synthetic/issues/{n}")})
        })
        .collect();
    json!({"baseRefName": "main", "closingIssuesReferences": refs,
           "headRefName": format!("room/syn-extra-{number}"), "headRefOid": commit(head),
           "isDraft": false,
           "mergeCommit": merge.map(|c| json!({"oid": commit(c)})),
           "mergedAt": merge.map(|_| "2026-10-30T18:30:00Z"),
           "number": number, "state": state, "title": format!("Synthetic PR {number}")})
}

fn closed_merge_facts_fail(test: &str, with_commit: bool, with_time: bool) {
    let list = pr_list(|prs| {
        let mut row = pr_row(958, "CLOSED", '8', &[903], Some('8'));
        if !with_commit {
            row["mergeCommit"] = Value::Null;
        }
        if !with_time {
            row["mergedAt"] = Value::Null;
        }
        prs.push(row);
    });
    let (doc, ran) = json_run(test, "complete", vec![list]);
    let discoveries: Vec<_> = doc["reads"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|r| r["kind"] == "pr_discovery")
        .collect();
    assert_eq!(discoveries.len(), 13);
    for r in discoveries {
        assert_eq!(r["outcome"]["state"], "failed", "{r}");
        assert_eq!(r["outcome"]["gap"], "malformed", "{r}");
        assert!(r["outcome"].get("value").is_none(), "{r}");
    }
    assert_eq!(doc["coverage"], json!({"state": "partial"}));
    assert_eq!(ticket(&doc, 903)["state"], json!({"unread": ["r8", "r11"]}));
    assert_eq!(
        ticket(&doc, 908)["state"],
        json!({"unread": ["r11", "r26", "r34", "r36"]})
    );
    for t in doc["data"]["tickets"].as_array().unwrap() {
        assert!(t["state"].get("unread").is_some(), "{t}");
        assert_eq!(
            (&t["ci"], &t["review"], &t["on_base"]),
            (&Value::Null, &Value::Null, &Value::Null)
        );
    }
    for b in doc["data"]["blockers"].as_array().unwrap() {
        assert!(b["merged"].get("unread").is_some(), "{b}");
    }
    for f in doc["data"]["fleets"].as_array().unwrap() {
        assert!(f["progress"].get("unread").is_some(), "{f}");
    }
    assert_eq!(ran.gh, super::want_first(), "no per-pull-request reads");
}

#[test]
fn closed_merge_commit_only_fails_discovery() {
    closed_merge_facts_fail("closed-merge-commit", true, false);
}

#[test]
fn closed_merge_time_only_fails_discovery() {
    closed_merge_facts_fail("closed-merge-time", false, true);
}

#[test]
fn closed_merge_legitimate_rows_preserve_discovery_and_readback() {
    let (doc, _) = json_run("closed-merge-controls", "complete", vec![]);
    assert_eq!(doc["coverage"], json!({"state": "complete"}));
    assert_eq!(
        read(&doc, "pr_discovery", "issue", json!(906))["outcome"],
        json!({"state": "complete", "value": null})
    );
    let merged = &read(&doc, "pr_discovery", "issue", json!(902))["outcome"]["value"];
    assert_eq!(merged["state"], "merged");
    assert_eq!(merged["number"], 951);
    assert_eq!(
        merged["merge_commit"],
        "2222222222222222222222222222222222222222"
    );
    assert_eq!(merged["merged_at"], 1_793_385_000_000_u64);
    assert_eq!(
        read(&doc, "merge_readback", "pr", json!(951))["outcome"],
        json!({"state": "complete", "value": true})
    );
    assert_eq!(ticket(&doc, 902)["state"], json!({"known": "merged"}));
}

#[test]
fn several_open_pull_requests_are_none_of_them_its() {
    let list = pr_list(|prs| prs.push(pr_row(958, "OPEN", '8', &[903], None)));
    let (doc, ran) = json_run("several-open", "complete", vec![list]);
    assert_eq!(
        read(&doc, "pr_discovery", "issue", json!(903))["outcome"],
        json!({"state": "complete", "value": {"state": "several", "numbers": [952, 958]}})
    );
    let t = ticket(&doc, 903);
    assert_eq!(
        (&t["ci"], &t["review"], &t["on_base"]),
        (&Value::Null, &Value::Null, &Value::Null)
    );
    assert_eq!(
        t["state"],
        json!({"unknown": "several open pull requests close it: none of them is its"})
    );
    assert!(
        !ran.gh.contains(&checks_argv(952)) && !ran.gh.contains(&comments_argv(952)),
        "a pull request that isn't its was read"
    );
    assert_eq!(ticket(&doc, 908)["state"], json!({"known": "blocked"}));
}

#[test]
fn several_open_pull_requests_validate_closing_reference_identity() {
    for invalid_pr in [952, 958] {
        let list = pr_list(|prs| {
            prs.push(pr_row(958, "OPEN", '8', &[903], None));
            let pr = prs.iter_mut().find(|p| p["number"] == invalid_pr).unwrap();
            pr["closingIssuesReferences"][0]["number"] = json!(904);
        });
        let (doc, ran) = json_run(
            &format!("several-invalid-{invalid_pr}"),
            "complete",
            vec![list],
        );
        let discovery = read(&doc, "pr_discovery", "issue", json!(903));
        assert_eq!(
            discovery["outcome"],
            json!({"state": "failed", "gap": "malformed",
                   "reason": format!("pull request #{invalid_pr} closes an issue that can't be told to be this repository's")})
        );
        assert_eq!(doc["coverage"], json!({"state": "partial"}));
        assert_eq!(
            ticket(&doc, 903)["state"],
            json!({"unread": [discovery["id"]]})
        );
        for pr in [952, 958] {
            assert!(!ran.gh.contains(&checks_argv(pr)));
            assert!(!ran.gh.contains(&comments_argv(pr)));
        }
    }
}

#[test]
fn a_merged_pull_request_precedes_inconsistent_open_candidates() {
    let list = pr_list(|prs| {
        for number in [958, 959] {
            let mut pr = pr_row(number, "OPEN", '8', &[902], None);
            pr["closingIssuesReferences"][0]["number"] = json!(903);
            prs.push(pr);
        }
    });
    let (doc, ran) = json_run("merged-before-invalid-open", "complete", vec![list]);
    let outcome = &read(&doc, "pr_discovery", "issue", json!(902))["outcome"];
    assert_eq!(outcome["state"], "complete");
    assert_eq!(outcome["value"]["state"], "merged");
    assert_eq!(outcome["value"]["number"], 951);
    assert_eq!(ticket(&doc, 902)["state"], json!({"known": "merged"}));
    for pr in [958, 959] {
        assert!(!ran.gh.contains(&checks_argv(pr)));
        assert!(!ran.gh.contains(&comments_argv(pr)));
    }
}

#[test]
fn two_merged_pull_requests_are_never_a_guess() {
    let list = pr_list(|prs| prs.push(pr_row(959, "MERGED", '9', &[902], Some('8'))));
    let (doc, _) = json_run("two-merged", "complete", vec![list]);
    assert_eq!(
        read(&doc, "pr_discovery", "issue", json!(902))["outcome"],
        json!({"state": "failed", "gap": "malformed",
               "reason": "more than one merged pull request closes #902"})
    );
    assert_eq!(read(&doc, "pr_discovery", "issue", json!(902))["id"], "r8");
    assert_eq!(ticket(&doc, 902)["state"], json!({"unread": ["r8"]}));
    for t in [903, 906] {
        assert_eq!(ticket(&doc, t)["state"], json!({"unread": ["r8"]}), "#{t}");
    }
    assert_eq!(fleet(&doc, 930)["progress"]["unread"], json!(["r8"]));
}

#[test]
fn a_closing_reference_to_another_repository_fails_the_read() {
    let list = pr_list(|prs| {
        let pr = prs.iter_mut().find(|p| p["number"] == 952).unwrap();
        let mut other = pr["closingIssuesReferences"][0].clone();
        other["id"] = json!("syn-issue-elsewhere-0904");
        other["number"] = json!(904);
        pr["closingIssuesReferences"]
            .as_array_mut()
            .unwrap()
            .push(other);
    });
    let (doc, _) = json_run("foreign-closes", "complete", vec![list]);
    assert_eq!(
        read(&doc, "pr_discovery", "issue", json!(903))["outcome"],
        json!({"state": "failed", "gap": "malformed",
               "reason": "pull request #952 closes an issue that can't be told to be this repository's"})
    );
    assert_eq!(
        read(&doc, "pr_discovery", "issue", json!(904))["outcome"]["value"]["number"],
        953
    );
}

#[test]
fn an_issue_list_of_1000_rows_is_cut_short() {
    let list = issue_list(|rows| {
        let filler = rows.iter().find(|r| r["number"] == 941).unwrap().clone();
        for n in 0..(1000 - rows.len()) {
            let mut row = filler.clone();
            let number = 2000 + n;
            row["number"] = json!(number);
            row["id"] = json!(format!("syn-issue-{number:04}"));
            rows.push(row);
        }
        assert_eq!(rows.len(), 1000);
    });
    let (doc, _) = json_run("issues-cut-short", "complete", vec![list]);
    assert_eq!(
        read(&doc, "spec_list", "", Value::Null)["outcome"],
        json!({"state": "partial", "gap": "truncated",
               "reason": "GitHub listed 1000 issues, the most one read asks for: there may be more",
               "value": [901, 930]})
    );
    assert_eq!(doc["data"]["needs_you"], json!({"unread": ["r3"]}));
    for b in doc["data"]["blockers"].as_array().unwrap() {
        assert_eq!(b["fleet"], json!({"unread": ["r3"]}), "{b}");
    }
    assert_eq!(fleet(&doc, 901)["progress"]["known"]["tickets"], 9);
}

#[test]
fn a_pull_request_list_of_1000_rows_is_cut_short() {
    let list = pr_list(|prs| {
        for n in 0..(1000 - prs.len()) {
            prs.push(pr_row(3000 + n as u64, "CLOSED", 'e', &[], None));
        }
    });
    let (doc, ran) = json_run("prs-cut-short", "complete", vec![list]);
    let discoveries = doc["reads"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|r| r["kind"] == "pr_discovery")
        .count();
    assert_eq!(discoveries, 13, "#902-#910, #931, #932, #811 and #812");
    for r in doc["reads"].as_array().unwrap() {
        if r["kind"] == "pr_discovery" {
            let n = r["issue"].as_u64().unwrap();
            assert_eq!(
                r["outcome"],
                json!({"state": "failed", "gap": "budget_exhausted",
                       "reason": format!("GitHub listed 1000 pull requests, the most one read asks for: one that closes #{n} may be missing")})
            );
        }
    }
    assert_eq!(ran.gh.len(), 4, "no per-pull-request read");
}

#[test]
fn a_malformed_latest_verdict_is_never_replaced_by_an_older_one() {
    let bodies = [
        format!("VERDICT: CHANGES at {}", commit('4')),
        format!("VERDICT: APPROVE at {}", &commit('4')[..7]),
    ];
    let answer =
        json!({"argv": comments_argv(953), "stdout": serde_json::to_string(&bodies).unwrap()});
    let (doc, _) = json_run("verdict-malformed", "complete", vec![answer]);
    assert_eq!(
        read(&doc, "comments", "pr", json!(953))["outcome"],
        json!({"state": "failed", "gap": "malformed",
               "reason": "the latest VERDICT comment on pull request #953 isn't review-ticket's form"})
    );
    assert_eq!(ticket(&doc, 904)["state"], json!({"unread": ["r19"]}));
}

#[test]
fn two_checks_with_one_name_fail_the_read() {
    let answer = json!({"argv": checks_argv(952),
        "stdout": "[{\"bucket\": \"pass\", \"name\": \"syn-build\"}, {\"bucket\": \"fail\", \"name\": \"syn-build\"}]"});
    let (doc, _) = json_run("checks-twice", "complete", vec![answer]);
    assert_eq!(
        read(&doc, "checks", "pr", json!(952))["outcome"],
        json!({"state": "failed", "gap": "malformed",
               "reason": "pull request #952 has two checks with one name"})
    );
}

#[test]
fn a_ticket_never_blocks_itself_and_a_spec_is_never_its_own_sub_issue() {
    let list = issue_list(|rows| {
        let node = |rows: &Vec<Value>, n: u64| {
            let r = rows.iter().find(|r| r["number"] == n).unwrap();
            json!({"id": r["id"], "number": n, "state": r["state"], "title": r["title"],
                   "url": format!("https://example.invalid/synthetic/issues/{n}")})
        };
        let (n905, n930) = (node(rows, 905), node(rows, 930));
        for r in rows.iter_mut() {
            if r["number"] == 905 {
                r["blockedBy"] = json!({"nodes": [n905.clone()], "totalCount": 1});
            }
            if r["number"] == 930 {
                r["subIssues"]["nodes"]
                    .as_array_mut()
                    .unwrap()
                    .push(n930.clone());
                r["subIssues"]["totalCount"] = json!(3);
            }
        }
    });
    let (doc, _) = json_run("self-links", "complete", vec![list]);
    assert_eq!(
        read(&doc, "blocked_by", "ticket", json!(905))["outcome"],
        json!({"state": "failed", "gap": "malformed",
               "reason": "GitHub listed #905 as its own blocker"})
    );
    assert_eq!(ticket(&doc, 905)["state"], json!({"unread": ["r21"]}));
    assert_eq!(
        read(&doc, "sub_issues", "spec", json!(930))["outcome"],
        json!({"state": "failed", "gap": "malformed",
               "reason": "GitHub listed #930 as its own sub-issue"})
    );
    assert_eq!(fleet(&doc, 930)["progress"]["unread"], json!(["r49"]));
}

struct OutOfBudgetAfter {
    log: std::path::PathBuf,
    starts: usize,
    far: Instant,
}

impl Clock for OutOfBudgetAfter {
    fn now(&self) -> Timestamp {
        Timestamp(1_793_437_200_000)
    }

    fn monotonic(&self) -> Instant {
        let started = fs::read_to_string(&self.log).map_or(0, |t| t.lines().count());
        if started >= self.starts {
            self.far
        } else {
            Instant::now()
        }
    }
}

#[test]
fn reads_the_budget_leaves_are_recorded_as_not_read() {
    let slow = |argv: Vec<String>| json!({"argv": argv, "stdout": "[]", "delay_ms": 60000});
    let extra = vec![
        slow(checks_argv(952)),
        slow(comments_argv(952)),
        slow(checks_argv(953)),
        slow(comments_argv(953)),
    ];
    let scenario = stage("budget", "complete", extra);
    let fake = FakeGh::new("a4-budget", &scenario);
    let source = GitHubFleets::with_program(fake.program());
    let (mut out, mut err) = (Vec::new(), Vec::new());
    let clock = OutOfBudgetAfter {
        log: fake.dir.join("gh-invocations.log"),
        starts: 8,
        far: Instant::now() + Duration::from_secs(86_400),
    };
    let code = fleets::run_with(
        &["--json".into()],
        &source,
        &clock,
        Duration::from_secs(5),
        &mut out,
        &mut err,
    );
    assert_eq!((code, String::from_utf8(err).unwrap()), (0, String::new()));
    let doc: Value = serde_json::from_slice(&out).unwrap();
    assert_eq!(validate(&load_schema(), &doc), Vec::<String>::new());
    let gap = |id: &str| {
        let r = doc["reads"]
            .as_array()
            .unwrap()
            .iter()
            .find(|r| r["id"] == id)
            .unwrap();
        (
            r["outcome"]["state"].as_str().unwrap().to_owned(),
            r["outcome"]["gap"].as_str().unwrap_or("").to_owned(),
        )
    };
    for id in ["r13", "r14", "r18", "r19"] {
        assert_eq!(
            gap(id),
            ("failed".to_owned(), "timed_out".to_owned()),
            "{id}"
        );
    }
    for id in ["r9", "r23", "r24", "r40", "r41", "r44", "r47"] {
        assert_eq!(
            gap(id),
            ("failed".to_owned(), "budget_exhausted".to_owned()),
            "{id}"
        );
        let r = doc["reads"]
            .as_array()
            .unwrap()
            .iter()
            .find(|r| r["id"] == id)
            .unwrap();
        assert_eq!(r["outcome"]["reason"], "not read: budget");
    }
    let started: Vec<Vec<String>> = fake.invocations();
    assert_eq!(started.len(), 8, "{started:?}");
    for argv in &started {
        let argv: Vec<&str> = argv.iter().map(String::as_str).collect();
        assert!(
            openwiz_adapter_github::allowlist::allowed(&argv),
            "{argv:?}"
        );
    }
    assert_eq!(doc["coverage"], json!({"state": "partial"}));
    assert_eq!(doc["freshness"]["snapshot_at"], 1_793_437_200_000_i64);
}

#[test]
fn a_failed_version_read_is_an_untested_version() {
    let fails = json!({"argv": ["--version"], "stderr": "Synthetic failure\n", "exit": 1});
    let (doc, ran) = json_run("version-fails", "complete", vec![fails]);
    assert_eq!(
        read(&doc, "version", "source", json!("github"))["outcome"],
        json!({"state": "failed", "gap": "untested_version",
               "reason": "gh --version exited 1: gh error (detail withheld)"})
    );
    assert_eq!(doc["sources"]["github"]["version_tested"], false);
    assert_eq!(ran.gh.len(), 13, "every other read still runs");
}

#[test]
fn a_link_a_cut_short_list_does_not_hold_fails_its_read() {
    let list = issue_list(|rows| {
        rows.retain(|r| r["number"] != 811);
        let filler = rows.iter().find(|r| r["number"] == 941).unwrap().clone();
        for n in 0..(1000 - rows.len()) {
            let mut row = filler.clone();
            let number = 2000 + n;
            row["number"] = json!(number);
            row["id"] = json!(format!("syn-issue-{number:04}"));
            rows.push(row);
        }
    });
    let (doc, _) = json_run("unknown-link", "complete", vec![list]);
    assert_eq!(
        read(&doc, "blocked_by", "ticket", json!(908))["outcome"],
        json!({"state": "failed", "gap": "budget_exhausted",
               "reason": "#908's blocker #811 isn't among the 1000 issues GitHub listed, the most one read asks for"})
    );
    assert_eq!(ticket(&doc, 908)["state"], json!({"unread": ["r32"]}));
}

#[test]
fn each_guard_refuses_the_violation_it_exists_for() {
    let node = |n: u64| {
        json!({"id": format!("syn-issue-{n:04}"), "number": n, "state": "CLOSED",
               "title": "Synthetic", "url": format!("https://example.invalid/synthetic/issues/{n}")})
    };
    let blocked_908 = |nodes: Vec<Value>, total: u64| {
        issue_list(move |rows| {
            let r = rows.iter_mut().find(|r| r["number"] == 908).unwrap();
            r["blockedBy"] = json!({"nodes": nodes, "totalCount": total});
        })
    };
    type Case = (
        &'static str,
        Value,
        (&'static str, &'static str, Value),
        Value,
    );
    let cases: Vec<Case> = vec![
        (
            "issue-twice",
            issue_list(|rows| {
                let first = rows[0].clone();
                rows.push(first);
            }),
            ("spec_list", "", Value::Null),
            json!({"state": "failed", "gap": "malformed",
                   "reason": "GitHub's issue list named one issue twice"}),
        ),
        (
            "label-twice",
            issue_list(|rows| {
                let r = rows.iter_mut().find(|r| r["number"] == 903).unwrap();
                let label = r["labels"][0].clone();
                r["labels"].as_array_mut().unwrap().push(label);
            }),
            ("issue", "issue", json!(903)),
            json!({"state": "failed", "gap": "malformed", "reason": "#903 has one label twice"}),
        ),
        (
            "link-twice",
            blocked_908(vec![node(811), node(811), node(812), node(903)], 4),
            ("blocked_by", "ticket", json!(908)),
            json!({"state": "failed", "gap": "malformed",
                   "reason": "GitHub listed one of #908's blockers twice"}),
        ),
        (
            "more-than-total",
            blocked_908(vec![node(811), node(812), node(903)], 2),
            ("blocked_by", "ticket", json!(908)),
            json!({"state": "failed", "gap": "malformed",
                   "reason": "GitHub listed more of #908's blockers than its own total"}),
        ),
        (
            "closes-twice",
            pr_list(|prs| {
                let pr = prs.iter_mut().find(|p| p["number"] == 952).unwrap();
                let again = pr["closingIssuesReferences"][0].clone();
                pr["closingIssuesReferences"]
                    .as_array_mut()
                    .unwrap()
                    .push(again);
            }),
            ("pr_discovery", "issue", json!(903)),
            json!({"state": "failed", "gap": "malformed",
                   "reason": "pull request #952 lists one closing reference twice"}),
        ),
        (
            "closes-100",
            pr_list(|prs| {
                let many: Vec<u64> = (2000..2100).collect();
                let pr = prs.iter_mut().find(|p| p["number"] == 957).unwrap();
                *pr = pr_row(957, "OPEN", 'e', &many, None);
            }),
            ("pr_discovery", "issue", json!(903)),
            json!({"state": "failed", "gap": "budget_exhausted",
                   "reason": "a pull request lists 100 closing references, the most gh reads: one that closes #903 may be missing"}),
        ),
    ];
    for (name, answer, (kind, key, subject), want) in cases {
        let (doc, _) = json_run(&format!("guard-{name}"), "complete", vec![answer]);
        assert_eq!(read(&doc, kind, key, subject)["outcome"], want, "{name}");
        assert_eq!(doc["coverage"], json!({"state": "partial"}), "{name}");
    }
}

#[test]
fn needs_you_is_by_spec_ticket_then_kind() {
    let list = issue_list(|rows| {
        let r = rows.iter_mut().find(|r| r["number"] == 904).unwrap();
        let mut held = r["labels"][0].clone();
        held["name"] = json!("held");
        held["id"] = json!("syn-label-held");
        r["labels"].as_array_mut().unwrap().push(held);
    });
    let (doc, _) = json_run("both-labels", "complete", vec![list]);
    assert_eq!(
        doc["data"]["needs_you"],
        json!({"known": [
            {"kind": "held", "spec": 901, "ticket": 904, "wording": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "link": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "asked_at": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "risk": {"unknown": "no explicit risk classification was reported"}},
            {"kind": "needs_info", "spec": 901, "ticket": 904, "wording": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "link": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "asked_at": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "risk": {"unknown": "no explicit risk classification was reported"}},
            {"kind": "held", "spec": 901, "ticket": 907, "wording": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "link": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "asked_at": {"unknown": "the fleets view does not read comments; openwiz fleet <spec> reads the question"}, "risk": {"unknown": "no explicit risk classification was reported"}},
        ]})
    );
}

#[test]
fn a_pull_request_list_naming_one_twice_is_never_taken() {
    let identical = pr_list(|prs| {
        let again = prs.iter().find(|p| p["number"] == 952).unwrap().clone();
        prs.push(again);
    });
    let conflicting = pr_list(|prs| {
        prs.iter_mut().find(|p| p["number"] == 953).unwrap()["number"] = json!(952);
    });
    for (name, list) in [
        ("prs-identical", identical),
        ("prs-conflicting", conflicting),
    ] {
        let (doc, ran) = json_run(name, "complete", vec![list]);
        let discoveries: Vec<&Value> = doc["reads"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|r| r["kind"] == "pr_discovery")
            .collect();
        assert_eq!(discoveries.len(), 13, "{name}");
        for r in discoveries {
            assert_eq!(
                r["outcome"],
                json!({"state": "failed", "gap": "malformed",
                       "reason": "GitHub's pull request list named one pull request twice"}),
                "{name}: {r}"
            );
        }
        assert_eq!(ran.gh.len(), 4, "{name}: no per-pull-request read");
    }
}

pub(super) fn batch_argv(pairs: &[(String, String)]) -> Vec<String> {
    let mut vars = String::new();
    let mut body = String::new();
    for i in 0..pairs.len() {
        vars.push_str(&format!(",$base{i}:String!,$head{i}:String!"));
        body.push_str(&format!("r{i}:ref(qualifiedName:$base{i}){{target{{oid}} comparison:compare(headRef:$head{i}){{status aheadBy behindBy baseTarget{{oid}} headTarget{{oid}}}}}}"));
    }
    let mut args: Vec<String> = [
        "api",
        "graphql",
        "-F",
        "owner={owner}",
        "-F",
        "name={repo}",
        "-f",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect();
    args.push(format!("query=query($owner:String!,$name:String!{vars}){{repository(owner:$owner,name:$name){{{body}}}}}"));
    for (i, (base, head)) in pairs.iter().enumerate() {
        args.extend([
            "-f".into(),
            format!("base{i}=refs/heads/{base}"),
            "-f".into(),
            format!("head{i}={head}"),
        ]);
    }
    args
}

fn batch_value(head: &str) -> Value {
    json!({"target":{"oid":commit('f')}, "comparison":{
        "status":"BEHIND", "aheadBy":0, "behindBy":10,
        "baseTarget":{"oid":commit('f')}, "headTarget":{"oid":head}}})
}

fn scale_scenario(name: &str, latency: u64) -> std::path::PathBuf {
    let seed: Vec<Value> = serde_json::from_str(
        &fs::read_to_string(Path::new(FIXTURES).join("fleets/complete/issues.json")).unwrap(),
    )
    .unwrap();
    let template = seed.iter().find(|v| v["number"] == 902).unwrap();
    let node = |n: u64| json!({"id":format!("syn-issue-{n:04}"),"number":n,"state":"OPEN","title":"Synthetic","url":format!("https://example.invalid/synthetic/issues/{n}")});
    let mut issues = Vec::new();
    for n in (100..116).chain(1000..1137).chain(2000..2011) {
        let mut row = template.clone();
        row["number"] = json!(n);
        row["id"] = json!(format!("syn-issue-{n:04}"));
        row["state"] = json!("OPEN");
        row["labels"] = json!([]);
        let subs: Vec<Value> = if n < 116 {
            (1000..1137)
                .filter(|t| (t - 1000) % 16 == n - 100)
                .map(node)
                .collect()
        } else {
            vec![]
        };
        row["subIssues"] = json!({"totalCount":subs.len(),"nodes":subs});
        let blockers: Vec<Value> = if n == 1136 {
            (2000..2011).map(node).collect()
        } else {
            vec![]
        };
        row["blockedBy"] = json!({"totalCount":blockers.len(),"nodes":blockers});
        issues.push(row);
    }
    let mut prs = Vec::new();
    let mut responses = vec![
        json!({"argv":["--version"],"stdout":"gh version 2.100.0"}),
        json!({"argv":["repo","view","--json","nameWithOwner"],"stdout":"{\"nameWithOwner\":\"syn-owner/syn-repo\"}"}),
        json!({"argv":ISSUE_LIST,"stdout":serde_json::to_string(&issues).unwrap()}),
    ];
    let mut pairs = Vec::new();
    for i in 0..79_u64 {
        let mut pr = pr_row(
            3000 + i,
            if i < 73 { "MERGED" } else { "OPEN" },
            'a',
            &[1000 + i],
            if i < 73 { Some('b') } else { None },
        );
        if i < 73 {
            let sha = format!("{i:040x}");
            pr["mergeCommit"] = json!({"oid":sha});
            pairs.push(("main".to_owned(), sha.clone()));
            responses.push(json!({"argv":["api",format!("repos/{{owner}}/{{repo}}/compare/{sha}...main"),"--jq","{status: .status, behind_by: .behind_by}"],"stdout":"{\"status\":\"ahead\",\"behind_by\":0}"}));
        } else {
            responses.push(json!({"argv":checks_argv(3000+i),"stdout":"[]"}));
            responses.push(json!({"argv":comments_argv(3000+i),"stdout":"[]"}));
        }
        prs.push(pr);
    }
    responses.push(json!({"argv":PR_LIST,"stdout":serde_json::to_string(&prs).unwrap()}));
    pairs.sort_by_key(|(_, sha)| {
        let n = u64::from_str_radix(sha, 16).unwrap();
        (n % 16, n)
    });
    for chunk in pairs.chunks(20) {
        let mut repo = serde_json::Map::new();
        for (i, (_, sha)) in chunk.iter().enumerate() {
            repo.insert(format!("r{i}"), batch_value(sha));
        }
        responses.push(json!({"argv":batch_argv(chunk),"stdout":json!({"data":{"repository":repo}}).to_string()}));
    }
    for response in &mut responses {
        response["delay_ms"] = json!(latency);
    }
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join(format!("a7-{name}"));
    dirs::private_dir_all(&dir).unwrap();
    let path = dir.join("scenario.json");
    fs::write(&path,json!({"synthetic_assumptions":["All values synthetic; raw merge SHA as GraphQL headRef and latency are unverified assumptions; no pagination"],"responses":responses}).to_string()).unwrap();
    path
}

fn scale_run_at(
    name: &str,
    path: &Path,
    budget: Duration,
    records: usize,
) -> (Value, usize, Duration) {
    scale_run_paced(name, path, budget, records, Pace::default())
}

#[derive(Default)]
struct Pace {
    transport: Option<Duration>,
    stall: Option<(usize, Duration)>,
}

fn scale_run_paced(
    name: &str,
    path: &Path,
    budget: Duration,
    records: usize,
    pace: Pace,
) -> (Value, usize, Duration) {
    let fake = FakeGh::new(&format!("a7-{name}"), path);
    let transport = pace.transport.map(|l| Arc::new(TransportClock::new(l)));
    let mut source = RecordingSource::new(GitHubFleets::with_program(fake.program()));
    source.stall = pace.stall;
    source.transport = transport.clone();
    let clock: &dyn Clock = match &transport {
        Some(transport) => &**transport,
        None => &openwiz_cli::SystemClock,
    };
    let start = Instant::now();
    let (mut out, mut err) = (Vec::new(), Vec::new());
    assert_eq!(
        fleets::run_with(
            &["--json".into()],
            &source,
            clock,
            budget,
            &mut out,
            &mut err
        ),
        0
    );
    assert!(err.is_empty());
    let elapsed = start.elapsed();
    let doc: Value = serde_json::from_slice(&out).unwrap();
    assert_eq!(validate(&load_schema(), &doc), Vec::<String>::new());
    let calls = fake.invocations().len();
    if transport.is_some() {
        assert_eq!(source.answered.load(Ordering::SeqCst), calls);
    }
    let peak = source.peak.load(std::sync::atomic::Ordering::SeqCst);
    assert!(peak <= 4, "peak={peak}");
    assert_eq!(source.active.load(std::sync::atomic::Ordering::SeqCst), 0);
    assert_eq!(doc["reads"].as_array().unwrap().len(), records);
    assert_eq!(doc["data"]["fleets"].as_array().unwrap().len(), 16);
    assert_eq!(doc["data"]["tickets"].as_array().unwrap().len(), 137);
    eprintln!(
        "A7 {name}: calls={calls}, peak={peak}, elapsed={elapsed:?}, coverage={}",
        doc["coverage"]
    );
    (doc, calls, elapsed)
}

#[test]
fn a7_scale_completes_with_twenty_calls_inside_the_scaled_budget() {
    let path = scale_scenario("scaled", 50);
    let pace = Pace {
        transport: Some(Duration::from_millis(50)),
        stall: Some((4, Duration::from_millis(1200))),
    };
    let (doc, calls, _) = scale_run_paced("scaled", &path, Duration::from_secs(1), 553, pace);
    assert_eq!(doc["coverage"]["state"], "complete");
    assert_eq!(calls, 20);
    for n in 1073..1079 {
        assert_eq!(ticket(&doc, n)["state"], json!({"known":"building"}));
    }
    for n in 1079..1137 {
        assert_eq!(
            ticket(&doc, n)["state"],
            json!({"unknown":"no pull request, and no ready label: not approved yet"})
        );
    }
    for n in 1000..1073 {
        assert_eq!(ticket(&doc, n)["state"], json!({"known":"merged"}));
    }
}

#[test]
fn a7_scale_transport_clock_spends_its_budget() {
    let path = scale_scenario("transport-spent", 50);
    let pace = Pace {
        transport: Some(Duration::from_millis(50)),
        stall: None,
    };
    let (doc, calls, _) = scale_run_paced(
        "transport-spent",
        &path,
        Duration::from_millis(350),
        553,
        pace,
    );
    assert_eq!(doc["coverage"]["state"], "partial");
    assert!((7..=16).contains(&calls), "calls={calls}");
}

use openwiz_core::fleet::fleets::{FleetsSource, IssueRow, Listed, PrRow};
use openwiz_core::fleet::model::{
    Check, Commit, Failed, MergedPr, NonEmpty, Number, PrFields, Repository,
};
use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, ThreadId};

struct TransportClock {
    origin: Instant,
    run: ThreadId,
    latency: Duration,
    lanes: Mutex<HashMap<ThreadId, Duration>>,
    reads_until: Instant,
}

impl TransportClock {
    fn new(latency: Duration) -> Self {
        let origin = Instant::now();
        Self {
            origin,
            run: thread::current().id(),
            latency,
            lanes: Mutex::new(HashMap::new()),
            reads_until: origin + openwiz_core::limits::RUN_BUDGET,
        }
    }

    fn lane<T>(&self, f: impl FnOnce(&mut Duration) -> T) -> T {
        let mut lanes = self.lanes.lock().unwrap();
        let run = lanes.get(&self.run).copied().unwrap_or_default();
        f(lanes.entry(thread::current().id()).or_insert(run))
    }

    fn charge(&self) {
        self.lane(|at| *at += self.latency);
    }
}

impl Clock for TransportClock {
    fn now(&self) -> Timestamp {
        openwiz_cli::SystemClock.now()
    }

    fn monotonic(&self) -> Instant {
        self.origin + self.lane(|at| *at)
    }
}

struct RecordingSource {
    inner: GitHubFleets,
    active: AtomicUsize,
    peak: AtomicUsize,
    answered: AtomicUsize,
    stall: Option<(usize, Duration)>,
    transport: Option<Arc<TransportClock>>,
}
impl RecordingSource {
    fn new(inner: GitHubFleets) -> Self {
        Self {
            inner,
            active: AtomicUsize::new(0),
            peak: AtomicUsize::new(0),
            answered: AtomicUsize::new(0),
            stall: None,
            transport: None,
        }
    }
    fn measure<T>(&self, deadline: Instant, call: impl FnOnce(&GitHubFleets, Instant) -> T) -> T {
        let deadline = self.transport.as_ref().map_or(deadline, |t| t.reads_until);
        let active = self.active.fetch_add(1, Ordering::SeqCst) + 1;
        self.peak.fetch_max(active, Ordering::SeqCst);
        let answer = call(&self.inner, deadline);
        self.active.fetch_sub(1, Ordering::SeqCst);
        if let Some(transport) = &self.transport {
            transport.charge();
        }
        let answered = self.answered.fetch_add(1, Ordering::SeqCst) + 1;
        if let Some((after, pause)) = self.stall
            && answered == after
        {
            thread::sleep(pause);
        }
        answer
    }
}
impl FleetsSource for RecordingSource {
    fn tested_version(&self) -> &str {
        self.inner.tested_version()
    }
    fn version(&self, d: Instant) -> Result<NonEmpty, Failed> {
        self.measure(d, |s, d| s.version(d))
    }
    fn repository(&self, d: Instant) -> Result<Repository, Failed> {
        self.measure(d, |s, d| s.repository(d))
    }
    fn issues(&self, d: Instant) -> Result<Listed<IssueRow>, Failed> {
        self.measure(d, |s, d| s.issues(d))
    }
    fn pull_requests(&self, d: Instant) -> Result<Listed<PrRow>, Failed> {
        self.measure(d, |s, d| s.pull_requests(d))
    }
    fn checks(&self, p: Number, d: Instant) -> Result<Vec<Check>, Failed> {
        self.measure(d, |s, d| s.checks(p, d))
    }
    fn comments(&self, p: Number, d: Instant) -> Result<Vec<String>, Failed> {
        self.measure(d, |s, d| s.comments(p, d))
    }
    fn on_base(&self, p: &MergedPr, d: Instant) -> Result<bool, Failed> {
        self.measure(d, |s, d| s.on_base(p, d))
    }
    fn on_bases(&self, p: &[MergedPr], d: Instant) -> Vec<Result<bool, Failed>> {
        self.measure(d, |s, d| s.on_bases(p, d))
    }
}

fn merged_pr(n: u64, base: &str, sha: &str) -> MergedPr {
    MergedPr {
        fields: PrFields {
            number: Number::new(n).unwrap(),
            draft: false,
            head_branch: NonEmpty::new("room/syn-batch").unwrap(),
            head_commit: Commit::parse(&commit('a')).unwrap(),
            base_branch: NonEmpty::new(base).unwrap(),
            closes: vec![],
        },
        merge_commit: Commit::parse(sha).unwrap(),
        merged_at: Timestamp(1_793_437_200_000),
    }
}

const BATCH_PROBE_BUDGET: Duration = Duration::from_secs(30);

fn batch_probe(
    name: &str,
    stdout: &str,
    exit: u8,
    budget: Duration,
    delay: u64,
) -> Vec<Result<bool, Failed>> {
    let pairs = vec![
        ("main".to_owned(), commit('b')),
        ("release/syn".to_owned(), commit('c')),
    ];
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join(format!("batch-probe-{name}"));
    dirs::private_dir_all(&dir).unwrap();
    let path = dir.join("scenario.json");
    fs::write(&path,json!({"synthetic_assumptions":["All values synthetic; GraphQL raw SHA headRef not live-verified"],"responses":[{"argv":batch_argv(&pairs),"stdout":stdout,"exit":exit,"delay_ms":delay}]}).to_string()).unwrap();
    let fake = FakeGh::new(&format!("batch-probe-{name}"), &path);
    let source = GitHubFleets::with_program(fake.program());
    let prs: Vec<_> = pairs
        .iter()
        .enumerate()
        .map(|(i, (base, sha))| merged_pr(3000 + i as u64, base, sha))
        .collect();
    let answers = source.on_bases(&prs, Instant::now() + budget);
    assert_eq!(
        answers.len(),
        2,
        "batch_probe case={name} budget={budget:?} delay_ms={delay}: answers={answers:?}"
    );
    assert_eq!(
        fake.invocations(),
        vec![batch_argv(&pairs)],
        "batch_probe case={name} budget={budget:?} delay_ms={delay}: answers={answers:?}"
    );
    answers
}

#[test]
fn a7_batch_direction_and_targets_are_verified_for_each_base() {
    for (status, ahead, behind, want) in [
        ("BEHIND", 0, 10, true),
        ("IDENTICAL", 0, 0, true),
        ("AHEAD", 3, 0, false),
        ("DIVERGED", 3, 10, false),
    ] {
        let mut first = batch_value(&commit('b'));
        first["comparison"]["status"] = json!(status);
        first["comparison"]["aheadBy"] = json!(ahead);
        first["comparison"]["behindBy"] = json!(behind);
        if status == "IDENTICAL" {
            first["target"]["oid"] = json!(commit('b'));
            first["comparison"]["baseTarget"]["oid"] = json!(commit('b'));
        }
        let out =
            json!({"data":{"repository":{"r0":first,"r1":batch_value(&commit('c'))}}}).to_string();
        assert_eq!(
            batch_probe(status, &out, 0, BATCH_PROBE_BUDGET, 0),
            vec![Ok(want), Ok(true)],
            "{status}"
        );
    }
}

#[test]
fn a7_bad_batch_members_never_prove_a_merge() {
    let good = json!({"data":{"repository":{"r0":batch_value(&commit('b')),"r1":batch_value(&commit('c'))}}});
    let mut cases = Vec::new();
    let mut v = good.clone();
    v["data"]["repository"]
        .as_object_mut()
        .unwrap()
        .remove("r0");
    cases.push(("missing", v));
    for (name, pointer, value) in [
        ("null-ref", "/data/repository/r0", Value::Null),
        (
            "null-comparison",
            "/data/repository/r0/comparison",
            Value::Null,
        ),
        (
            "wrong-head",
            "/data/repository/r0/comparison/headTarget/oid",
            json!(commit('d')),
        ),
        (
            "wrong-base",
            "/data/repository/r0/comparison/baseTarget/oid",
            json!(commit('d')),
        ),
        ("bad-oid", "/data/repository/r0/target/oid", json!("bad")),
        (
            "scalar",
            "/data/repository/r0/comparison/aheadBy",
            json!("0"),
        ),
        (
            "negative",
            "/data/repository/r0/comparison/aheadBy",
            json!(-1),
        ),
        (
            "overflow",
            "/data/repository/r0/comparison/aheadBy",
            json!(2147483648_u64),
        ),
        (
            "float",
            "/data/repository/r0/comparison/aheadBy",
            json!(0.0),
        ),
        (
            "contradiction",
            "/data/repository/r0/comparison/status",
            json!("IDENTICAL"),
        ),
        (
            "status",
            "/data/repository/r0/comparison/status",
            json!("UNKNOWN"),
        ),
    ] {
        let mut v = good.clone();
        *v.pointer_mut(pointer).unwrap() = value;
        cases.push((name, v));
    }
    for (name, v) in cases {
        let answers = batch_probe(name, &v.to_string(), 0, BATCH_PROBE_BUDGET, 0);
        assert!(answers[0].is_err(), "{name}: {answers:?}");
        assert_eq!(answers[1], Ok(true), "{name}: {answers:?}");
    }
    for (name, out, exit) in [
        (
            "field-error",
            format!(
                "{{\"data\":{},\"errors\":[{{\"message\":\"synthetic secret must be withheld\",\"path\":[\"repository\",\"r0\",\"comparison\"]}}]}}",
                good["data"]
            ),
            0,
        ),
        (
            "duplicate",
            format!("{{\"data\":{},\"data\":{}}}", good["data"], good["data"]),
            0,
        ),
        ("truncated", good.to_string()[..20].to_owned(), 0),
        ("nonzero", good.to_string(), 1),
    ] {
        let answers = batch_probe(name, &out, exit, BATCH_PROBE_BUDGET, 0);
        assert!(answers.iter().all(Result::is_err), "{name}: {answers:?}");
        for error in &answers {
            assert!(
                !error
                    .as_ref()
                    .unwrap_err()
                    .reason
                    .as_str()
                    .contains("synthetic secret"),
                "{name}: {answers:?}"
            );
        }
    }
    let answers = batch_probe(
        "timeout",
        &good.to_string(),
        0,
        Duration::from_secs(5),
        60_000,
    );
    assert!(
        answers
            .iter()
            .all(|r| matches!(r, Err(f) if f.gap == openwiz_core::envelope::GapKind::TimedOut)),
        "timeout: {answers:?}"
    );
}

#[test]
fn a7_shared_prs_and_merge_pairs_keep_their_own_read_records() {
    let path = scale_scenario("shared", 0);
    let mut scenario: Value = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
    let responses = scenario["responses"].as_array_mut().unwrap();
    let pr_response = responses
        .iter_mut()
        .find(|v| v["argv"] == json!(PR_LIST))
        .unwrap();
    let mut prs: Vec<Value> =
        serde_json::from_str(pr_response["stdout"].as_str().unwrap()).unwrap();
    let shared = prs[1]["closingIssuesReferences"][0].clone();
    prs[0]["closingIssuesReferences"]
        .as_array_mut()
        .unwrap()
        .push(shared);
    prs.remove(1);
    for pr in &mut prs {
        if pr["state"] == "MERGED" {
            pr["mergeCommit"]["oid"] = json!(commit('b'));
            if pr["number"].as_u64().unwrap() >= 3036 {
                pr["baseRefName"] = json!("release/syn");
            }
        }
    }
    pr_response["stdout"] = json!(serde_json::to_string(&prs).unwrap());
    responses.retain(|v| v["argv"][0] != "api");
    let pairs = vec![
        ("main".into(), commit('b')),
        ("release/syn".into(), commit('b')),
    ];
    let mut absent = batch_value(&commit('b'));
    absent["comparison"]["status"] = json!("AHEAD");
    absent["comparison"]["aheadBy"] = json!(2);
    absent["comparison"]["behindBy"] = json!(0);
    responses.push(json!({"argv":batch_argv(&pairs),"stdout":json!({"data":{"repository":{"r0":batch_value(&commit('b')),"r1":absent}}}).to_string()}));
    fs::write(&path, scenario.to_string()).unwrap();
    let (doc, calls, _) = scale_run_at("shared", &path, Duration::from_secs(5), 552);
    assert_eq!(
        calls, 17,
        "four initial + twelve open-PR + one distinct-pair batch"
    );
    assert_eq!(doc["coverage"]["state"], "complete");
    for n in [1000, 1001, 1016, 1035] {
        assert_eq!(ticket(&doc, n)["state"], json!({"known":"merged"}));
    }
    assert_eq!(
        ticket(&doc, 1000)["on_base"],
        ticket(&doc, 1001)["on_base"],
        "one shared PR record"
    );
    assert_ne!(
        ticket(&doc, 1000)["on_base"],
        ticket(&doc, 1016)["on_base"],
        "distinct PRs retain records for one pair"
    );
    for n in 1036..1073 {
        assert_ne!(ticket(&doc, n)["state"], json!({"known":"merged"}));
    }
}

#[test]
fn a7_failed_batches_and_exhausted_budget_retain_all_required_records() {
    for name in ["failed-batches", "exhausted"] {
        let path = scale_scenario(name, 0);
        let mut scenario: Value =
            serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
        for response in scenario["responses"].as_array_mut().unwrap() {
            if response["argv"][1] == "graphql" {
                response["stdout"] =
                    json!("{\"data\":null,\"errors\":[{\"message\":\"synthetic\"}]}");
            }
        }
        fs::write(&path, scenario.to_string()).unwrap();
        let budget = if name == "exhausted" {
            Duration::ZERO
        } else {
            Duration::from_secs(5)
        };
        if budget.is_zero() {
            let fake = FakeGh::new("a7-exhausted", &path);
            let source = GitHubFleets::with_program(fake.program());
            let clock = OutOfBudgetAfter {
                log: fake.dir.join("gh-invocations.log"),
                starts: 4,
                far: Instant::now() + Duration::from_secs(86400),
            };
            let (mut out, mut err) = (Vec::new(), Vec::new());
            assert_eq!(
                fleets::run_with(
                    &["--json".into()],
                    &source,
                    &clock,
                    Duration::from_secs(5),
                    &mut out,
                    &mut err
                ),
                0
            );
            let doc: Value = serde_json::from_slice(&out).unwrap();
            assert_eq!(doc["reads"].as_array().unwrap().len(), 553);
            assert_eq!(fake.invocations().len(), 4);
            for r in doc["reads"].as_array().unwrap().iter().filter(|r| {
                matches!(
                    r["kind"].as_str(),
                    Some("merge_readback" | "checks" | "comments")
                )
            }) {
                assert_eq!(r["outcome"]["gap"], "budget_exhausted");
            }
        } else {
            let (doc, calls, _) = scale_run_at(name, &path, budget, 553);
            assert_eq!(calls, 20);
            assert_eq!(doc["coverage"]["state"], "partial");
            assert_eq!(
                doc["reads"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .filter(|r| r["kind"] == "merge_readback")
                    .count(),
                73
            );
            for n in 1000..1073 {
                assert!(ticket(&doc, n)["state"].get("unread").is_some());
            }
        }
    }
}

#[test]
fn a7_mixed_bases_keep_plain_peers_and_per_pr_gaps_in_input_order() {
    use openwiz_core::envelope::GapKind;

    let pairs = vec![
        ("main".to_owned(), commit('b')),
        ("release/syn".to_owned(), commit('c')),
    ];
    let mut absent = batch_value(&commit('c'));
    absent["comparison"]["status"] = json!("AHEAD");
    absent["comparison"]["aheadBy"] = json!(3);
    absent["comparison"]["behindBy"] = json!(0);
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join("a7-mixed-bases");
    dirs::private_dir_all(&dir).unwrap();
    let path = dir.join("scenario.json");
    fs::write(&path, json!({
        "synthetic_assumptions": ["All values synthetic; raw SHA headRef acceptance remains unverified live"],
        "responses": [{"argv": batch_argv(&pairs), "stdout": json!({"data": {"repository": {
            "r0": batch_value(&commit('b')), "r1": absent
        }}}).to_string()}]
    }).to_string()).unwrap();
    let fake = FakeGh::new("a7-mixed-bases", &path);
    let source = GitHubFleets::with_program(fake.program());
    let bad = [
        merged_pr(3001, "feat+x", &commit('d')),
        merged_pr(3003, "feat+y", &commit('e')),
        merged_pr(3004, "feat+z", &commit('a')),
    ];
    let prs = [
        bad[0].clone(),
        merged_pr(3000, "main", &commit('b')),
        bad[1].clone(),
        merged_pr(3002, "release/syn", &commit('c')),
        bad[2].clone(),
    ];
    let refused = |n| {
        Err(Failed {
        gap: GapKind::Malformed,
        reason: NonEmpty::new(format!("the merge read back of pull request #{n} was not run: its base isn't a plain branch name")).unwrap(),
    })
    };
    let deadline = Instant::now() + Duration::from_secs(2);
    assert_eq!(
        source.on_bases(&prs, deadline),
        vec![
            refused(3001),
            Ok(true),
            refused(3003),
            Ok(false),
            refused(3004),
        ]
    );
    assert_eq!(
        source.on_bases(&bad, deadline),
        vec![refused(3001), refused(3003), refused(3004)]
    );
    assert!(source.on_bases(&[], deadline).is_empty());
    for pr in &bad {
        assert_eq!(
            source.on_base(pr, deadline),
            refused(pr.fields.number.get())
        );
    }
    assert_eq!(
        fake.invocations(),
        vec![batch_argv(&pairs)],
        "one plain-base batch; invalid-only and empty inputs start no transport"
    );
}
