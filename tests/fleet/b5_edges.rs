//! Boundary and interruption proofs suggested by the independent helpers;
//! verified and written by the builder. All data is synthetic.
use super::fake::{self, World};
use serde_json::{Value, json};
use std::fs;
use std::os::unix::fs::DirBuilderExt;

fn stray(w: &World, n: u64, body: &str) {
    w.change(|s| {
        let mut i = s["issues"][1].clone();
        i["n"] = n.into();
        i["title"] = format!("Synthetic stray {n}").into();
        i["body"] = body.into();
        i["labels"] = json!([]);
        s["issues"].as_array_mut().unwrap().push(i);
    });
}
#[test]
fn b5_approval_v1_is_stale_and_aligned_table_is_valid() {
    for v1 in [true, false] {
        let w = World::new(if v1 { "approval_v1" } else { "aligned_table" });
        w.change(|s| {
            s["comments"]["9"][0]["body"] = if v1 {
                fake::APPROVAL
                    .replace("revision v2", "revision v1")
                    .replace(
                        "5a46b243aa88e90eaae1c4332f4d625154c4299a6fc3f15f9f75bc6ab414c66c",
                        "88124b667a17b6e2af5801fdd316936be1ce90f5f07f6ece6022b9968329fc70",
                    )
            } else {
                fake::APPROVAL.replace(
                    "| --- | --- | --- | --- |",
                    "| :--- | ---: | :---: | ---- |",
                )
            }
            .into()
        });
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success());
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        let expected = if v1 { "re_approve" } else { "frontier" };
        assert!(
            doc["actions"]
                .as_array()
                .unwrap()
                .iter()
                .any(|a| a["rule"] == expected),
            "{doc}"
        );
        assert!(w.writes().is_empty());
    }
}

// synthetic_assumptions: Markdown serialization variants of the approved
// fixture; the issue and hashed revision use the raw title, while only the
// table cell contains Markdown pipe escapes.
fn r1_approval_world(name: &str, title: &str, table_title: &str) -> World {
    use openwiz_core::messaging::sha256_hex;
    let w = World::new(name);
    w.change(|s| {
        s["issues"][1]["title"] = title.into();
        let body = fake::APPROVAL
            .replace("Synthetic ticket 10", title)
            .replacen(
                &format!("| #10 | {title} |"),
                &format!("| #10 | {table_title} |"),
                1,
            );
        let revision = body
            .split_once("```text\n")
            .unwrap()
            .1
            .split_once("```")
            .unwrap()
            .0;
        s["comments"]["9"][0]["body"] = body
            .replace(
                "5a46b243aa88e90eaae1c4332f4d625154c4299a6fc3f15f9f75bc6ab414c66c",
                &sha256_hex(revision.as_bytes()),
            )
            .into();
    });
    w
}

#[test]
fn b5_r1_approval_accepts_trailing_table_whitespace() {
    for (case, suffix) in [" ", "\t", " \t\r"].iter().enumerate() {
        let w = r1_approval_world(
            &format!("r1_whitespace_{case}"),
            "Synthetic ticket 10",
            "Synthetic ticket 10",
        );
        w.change(|s| {
            s["comments"]["9"][0]["body"] = s["comments"]["9"][0]["body"]
                .as_str()
                .unwrap()
                .lines()
                .map(|line| {
                    if line.starts_with('|') {
                        format!("{line}{suffix}")
                    } else {
                        line.to_owned()
                    }
                })
                .collect::<Vec<_>>()
                .join("\n")
                .into();
        });
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{doc}");
        assert_eq!(doc["actions"][0]["rule"], "frontier", "{doc}");
        assert_eq!(doc["actions"][0]["facts"]["approval"]["comment"], 100);
        assert!(w.writes().is_empty());
    }
}

#[test]
fn b5_r1_approval_accepts_escaped_title_pipes() {
    for (case, (table_title, title)) in [
        (r"Synthetic left \| right", "Synthetic left | right"),
        (
            r"Synthetic left \| middle \| right",
            "Synthetic left | middle | right",
        ),
        (
            r"Synthetic backslashes \\\| right",
            r"Synthetic backslashes \\| right",
        ),
        (r"Synthetic path \folder", r"Synthetic path \folder"),
    ]
    .iter()
    .enumerate()
    {
        let w = r1_approval_world(&format!("r1_escaped_{case}"), title, table_title);
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{doc}");
        assert_eq!(doc["actions"][0]["rule"], "frontier", "{doc}");
        assert_eq!(doc["actions"][0]["facts"]["approval"]["comment"], 100);
        assert!(w.writes().is_empty());
    }
}

#[test]
fn b5_r1_approval_refuses_unescaped_cells_and_escaped_closing_pipe() {
    for (case, title) in [
        "Synthetic left | right",
        r"Synthetic backslashes \\| right",
        "Synthetic ticket 10",
    ]
    .iter()
    .enumerate()
    {
        let w = r1_approval_world(&format!("r1_malformed_{case}"), title, title);
        if case == 2 {
            w.change(|s| {
                s["comments"]["9"][0]["body"] = s["comments"]["9"][0]["body"]
                    .as_str()
                    .unwrap()
                    .replace("none | ready-for-agent |", "none | ready-for-agent \\|")
                    .into();
            });
        }
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{doc}");
        assert_eq!(doc["actions"][0]["rule"], "look", "{doc}");
        assert_eq!(
            doc["actions"][0]["facts"]["reason"], "graph unread",
            "{doc}"
        );
        assert!(w.writes().is_empty());
        assert_eq!(w.load()["spawn_count"], 0);
    }
}
#[test]
fn b5_standalone_follow_up_is_summarized_and_prevents_spec_close() {
    let w = World::new("follow_up");
    stray(&w, 12, "Follow-up of #10 (spec #9)\nSynthetic follow-up.");
    w.change(|s| {
        for i in s["issues"].as_array_mut().unwrap() {
            if i["n"] == 10 || i["n"] == 11 {
                i["closed"] = true.into();
            }
        }
    });
    let doc = w.tick();
    let a = doc["actions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|a| a["rule"] == "spec_summary")
        .unwrap();
    assert_eq!(a["facts"]["follow_ups"], json!([12]), "{doc}");
    w.change(|s|s["comments"]["9"].as_array_mut().unwrap().push(json!({"id":900,"body":"launch-fleet: spec summary: synthetic","created":1793400010000_u64,"updated":1793400010000_u64})));
    let doc = w.tick();
    assert!(
        !doc["actions"]
            .as_array()
            .unwrap()
            .iter()
            .any(|a| a["rule"] == "all_closed"),
        "{doc}"
    );
    assert_eq!(w.load()["issues"][0]["closed"], false);
}
#[test]
fn b5_unrelated_pr_without_closing_reference_does_not_block_the_fleet() {
    let w = World::new("unrelated_pr");
    stray(&w, 12, "Synthetic unrelated issue");
    w.pr(12);
    w.change(|s| s["prs"][0]["no_closes"] = true.into());
    let doc = w.tick();
    assert_eq!(doc["actions"][0]["rule"], "frontier", "{doc}");
    assert_eq!(doc["actions"][0]["outcome"]["state"], "done", "{doc}");
}
#[test]
fn b5_due_has_one_line_per_candidate_and_reports_failed_global_reads() {
    let w = World::new("due_candidates");
    let o = w
        .command(&["fleet", "due", "--github-only"])
        .env("OPENWIZ_STATE_DIR", "relative-invalid")
        .env_remove("HOME")
        .output()
        .unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    assert_eq!(
        String::from_utf8(o.stdout).unwrap(),
        "fleet #9: candidate #10\n"
    );
    assert!(w.calls().iter().all(|(t, _)| t == "gh"));
    assert!(w.writes().is_empty());
    w.change(|s| {
        let key = json!([
            "gh",
            [
                "repo",
                "view",
                "--json",
                "defaultBranchRef,nameWithOwner,url"
            ]
        ])
        .to_string();
        s["overrides"][key] = 1.into();
    });
    let o = w.run(&["fleet", "due", "--github-only"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(o.stdout.is_empty());
}
#[test]
fn b5_due_wakes_for_closed_ticket_with_unrecorded_agent_audit_comment() {
    let w = World::new("due_orphan");
    w.tick();
    w.change(|s| {
        s["comments"]["10"] = json!([]);
        for i in s["issues"].as_array_mut().unwrap() {
            i["closed"] = true.into();
        }
    });
    let before = w.calls().len();
    let o = w.run(&["fleet", "due", "--github-only"]);
    assert!(o.status.success());
    assert!(
        String::from_utf8(o.stdout)
            .unwrap()
            .contains("candidate #10\n")
    );
    assert!(w.calls()[before..].iter().all(|(t, _)| t == "gh"));
}
#[test]
fn b5_external_failing_check_never_disappears_from_merge_authority() {
    let w = World::new("external_check");
    w.tick();
    w.pr(10);
    w.tick();
    w.approve(10);
    w.change(|s| s["extra_checks"] = json!([{"name":"external-synthetic","bucket":"fail"}]));
    w.tick();
    assert_eq!(w.load()["merge_bodies"].as_array().unwrap().len(), 0);
}
#[test]
fn b5_latest_individual_job_beats_workflow_update_order() {
    use openwiz_adapter_github::tick::{JOBS, RUNS, TickReads};
    use openwiz_core::fleet::model::{CheckResult, Commit, Number};
    let w = World::new("job_order");
    w.pr(10);
    w.change(|s|{
        s["prs"][0]["ci"]="failure".into();
        let runs=json!([{"total_count":2,"runs":[
            {"id":501,"head_sha":fake::HEAD10,"event":"pull_request","run_attempt":1,"updated":2000,"prs":[{"number":110,"head":fake::HEAD10,"base":fake::BASE}]},
            {"id":502,"head_sha":fake::HEAD10,"event":"pull_request","run_attempt":1,"updated":1000,"prs":[{"number":110,"head":fake::HEAD10,"base":fake::BASE}]}
        ]}]);
        let key=json!(["gh",["api",format!("repos/{{owner}}/{{repo}}/actions/runs?head_sha={}&per_page=100",fake::HEAD10),"--paginate","--jq",RUNS]]).to_string();s["overrides"][key]=runs;
        for (run,id,result) in [(501,1001,"success"),(502,1002,"failure")]{
            let key=json!(["gh",["api",format!("repos/{{owner}}/{{repo}}/actions/runs/{run}/jobs?filter=latest&per_page=100"),"--paginate","--jq",JOBS]]).to_string();
            s["overrides"][key]=json!([{"total_count":1,"jobs":[{"id":id,"name":"rust","status":"completed","conclusion":result,"head_sha":fake::HEAD10,"run_id":run}]}]);
        }
    });
    let checks = TickReads::new(w.dir.join("bin/gh"))
        .checks(
            Number::new(110).unwrap(),
            &Commit::parse(fake::HEAD10).unwrap(),
            std::time::Instant::now() + std::time::Duration::from_secs(5),
        )
        .unwrap()
        .unwrap();
    assert_eq!(checks.checks.len(), 1);
    assert_eq!(checks.checks[0].result, CheckResult::Fail);
}
#[test]
fn b5_release_rechecks_approval_before_removing_held() {
    let w = World::new("release_authority");
    stray(&w, 12, "Synthetic completed contract change");
    w.pr(12);
    let body = "launch-fleet: held for #112: contract changed, re-approve. crates/example/one.rs changed in #112.";
    w.change(|s| {
        s["prs"][0]["merged"] = true.into();
        s["prs"][0]["merged_at"] = "2026-10-29T00:00:00Z".into();
        s["issues"][3]["closed"] = true.into();
        s["issues"][1]["labels"] = json!(["held"]);
        s["comments"]["10"] =
            json!([{"id":90,"body":body,"created":1793300010000_u64,"updated":1793300010000_u64}]);
        s["timeline"]["10"] = json!([
            {"id":80,"event":"labeled","label":"held","body":null,"at":1793300000000_u64},
            {"id":90,"event":"commented","label":null,"body":body,"at":1793300010000_u64}
        ]);
        s["flip_approval_on_timeline"] = true.into();
    });
    let doc = w.tick();
    assert!(
        doc["actions"]
            .as_array()
            .unwrap()
            .iter()
            .any(|a| a["rule"] == "release"),
        "{doc}"
    );
    assert_eq!(w.load()["issues"][1]["labels"], json!(["held"]));
    assert!(
        !w.writes()
            .iter()
            .any(|(_, a)| a.get(3).is_some_and(|s| s == "--remove-label"))
    );
}
#[test]
fn b5_archive_retains_reviewer_start_order_after_a_recheck() {
    let w = World::new("reviewer_order");
    w.tick();
    w.pr(10);
    w.tick();
    for e in fs::read_dir(w.dir.join("state/starts")).unwrap() {
        let p = e.unwrap().path();
        if p.extension().is_none_or(|e| e != "json") {
            continue;
        }
        let mut r: Value = serde_json::from_slice(&fs::read(&p).unwrap()).unwrap();
        if r["key"]["role"] == "reviewer" {
            r["attempts"][0]["at"] = 1793400010000_u64.into();
            fs::write(p, serde_json::to_vec(&r).unwrap()).unwrap();
        }
    }
    w.change(|s|{
        s["issues"][1]["closed"]=true.into();s["issues"][2]["closed"]=true.into();
        s["threads"]["thr_syn_b5_30"]=s["threads"]["thr_syn_b5_2"].clone();
        s["comments"]["110"].as_array_mut().unwrap().extend([
            json!({"id":2001,"body":format!("launch-fleet: review started {}, thread thr_syn_b5_30",fake::HEAD10),"created":1793400020000_u64,"updated":1793400020000_u64}),
            json!({"id":2002,"body":format!("launch-fleet: re-check sent {}, thread thr_syn_b5_2",fake::HEAD10),"created":1793400030000_u64,"updated":1793400030000_u64})
        ]);
    });
    let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(o.status.success());
    let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
    let a = doc["actions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|a| a["rule"] == "finished")
        .unwrap();
    assert_eq!(
        a["facts"]["threads"],
        json!([{"thread":"thr_syn_b5_1","role":"builder"},{"thread":"thr_syn_b5_2","role":"reviewer"},{"thread":"thr_syn_b5_30","role":"reviewer"}]),
        "{doc}"
    );
}
#[test]
fn b5_timed_out_start_is_uncertain_and_never_retried() {
    let w = World::new("timeout");
    w.change(|s| s["crash"] = "timeout".into());
    // Real time: the hung start is stopped at the real 15 s READ_TIMEOUT.
    // The fast form (#1259) lowers the fixture openwiz's read timeout to
    // 1 s, with every assertion below.
    let fast: &[(&str, &str)] = &[("OPENWIZ_FIXTURE_READ_TIMEOUT_MS", "1000")];
    let doc = w.tick_with(crate::real_time::pick("b5_timed_out_start", &[], fast));
    assert_eq!(doc["actions"][0]["outcome"]["state"], "uncertain", "{doc}");
    w.change(|s| s["crash"] = "".into());
    for _ in 0..2 {
        let doc = w.tick();
        assert_eq!(doc["actions"][0]["rule"], "look", "{doc}");
    }
    assert_eq!(w.load()["spawn_count"], 1);
    assert_eq!(
        w.calls()
            .iter()
            .filter(|(t, a)| t == "room-cli" && a.get(1).is_some_and(|s| s == "spawn"))
            .count(),
        1
    );
}
/// #1259: the fixture `openwiz` (never the production one) can lower its
/// read timeout, so a hung start is stopped early, with the same outcome.
#[test]
fn x2_a_fixture_read_timeout_stops_a_hung_start_early() {
    let w = World::new("fixture_read_timeout");
    w.change(|s| s["crash"] = "timeout".into());
    // Fixture compilation is setup, not part of the bounded read.
    let _ = crate::support::openwiz_release();
    let started = std::time::Instant::now();
    let doc = w.tick_with(&[("OPENWIZ_FIXTURE_READ_TIMEOUT_MS", "1000")]);
    let elapsed = started.elapsed();
    assert_eq!(doc["actions"][0]["outcome"]["state"], "uncertain", "{doc}");
    assert_eq!(w.load()["spawn_count"], 1);
    assert!(
        elapsed < std::time::Duration::from_secs(10),
        "the hung start took {elapsed:?}"
    );
}

/// #1259: a fixture read timeout that is not a whole number of
/// milliseconds from 1 to 15000 stops the fixture before any call.
#[test]
fn x2_a_malformed_fixture_read_timeout_makes_no_call() {
    for (n, bad) in [
        "",
        "0",
        "abc",
        "-1",
        "1000ms",
        " 1000",
        "+5",
        "15001",
        "99999999999999999999",
    ]
    .into_iter()
    .enumerate()
    {
        let w = World::new(&format!("bad_read_timeout_{n}"));
        let o = w
            .command(&["fleet", "tick", "--json"])
            .env("OPENWIZ_FIXTURE_READ_TIMEOUT_MS", bad)
            .output()
            .unwrap();
        assert!(!o.status.success(), "{bad:?} was accepted");
        assert_eq!(w.calls(), vec![], "{bad:?}");
    }
}

#[test]
fn b5_ordinary_tick_prints_judgment_only() {
    let w = World::new("text");
    let o = w.run(&["fleet", "tick"]);
    assert!(o.status.success());
    assert!(o.stdout.is_empty());
    assert_eq!(w.load()["spawn_count"], 1);
    w.change(|s|{s["issues"][1]["labels"]=json!(["ready-for-agent","needs-info"]);s["comments"]["10"].as_array_mut().unwrap().push(json!({"id":2000,"body":"Synthetic question whose content stays off stdout","created":1793400100000_u64,"updated":1793400100000_u64}));});
    let o = w.run(&["fleet", "tick"]);
    assert!(o.status.success());
    assert_eq!(
        String::from_utf8(o.stdout).unwrap(),
        "fleet #9: #10 needs_info\n"
    );
}
#[test]
fn b5_notification_finishes_last_after_a_partial_failure() {
    let w = World::new("partial_notification");
    w.change(|s|{
        s["issues"][1]["labels"]=json!(["ready-for-human"]);
        s["comments"]["9"][0]["body"]=fake::APPROVAL.replace("#10 | Synthetic ticket 10 | none | ready-for-agent","#10 | Synthetic ticket 10 | none | ready-for-human").into();
        s["threads"]["thr_syn_orchestrator"]=json!({"provider":"codex","model":"gpt-6.1-sol","effort":"high","archived":false,"prompt":"Synthetic orchestrator"});
        s["fail_record"]="launch-fleet: told the user".into();
    });
    let run = || {
        let o = w
            .command(&["fleet", "tick", "--json"])
            .env("OPENWIZ_ORCHESTRATOR_THREAD_ID", "thr_syn_orchestrator")
            .output()
            .unwrap();
        assert!(o.status.success());
        serde_json::from_slice::<Value>(&o.stdout).unwrap()
    };
    let doc = run();
    assert_eq!(doc["actions"][0]["outcome"]["state"], "uncertain", "{doc}");
    assert_eq!(
        doc["actions"][0]["outcome"]["reason"], "GitHub write not confirmed",
        "the send must succeed before the injected comment failure: {doc}"
    );
    assert_eq!(
        w.load()["comments"]["9"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|c| c["body"]
                .as_str()
                .unwrap()
                .starts_with("**Needs you:** #10 is ready"))
            .count(),
        1,
        "the reason comment must precede the failed completion record"
    );
    assert!(w.load()["comments"]["10"].as_array().is_none_or(|cs| {
        cs.iter()
            .all(|c| c["body"] != "launch-fleet: told the user")
    }));
    w.change(|s| s["fail_record"] = "".into());
    let doc = run();
    assert_eq!(doc["actions"][0]["outcome"]["state"], "done", "{doc}");
    let s = w.load();
    assert_eq!(
        s["comments"]["9"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|c| c["body"]
                .as_str()
                .unwrap()
                .starts_with("**Needs you:** #10 is ready"))
            .count(),
        1
    );
    assert_eq!(
        s["comments"]["10"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|c| c["body"] == "launch-fleet: told the user")
            .count(),
        1
    );
    assert_eq!(
        w.calls()
            .iter()
            .filter(|(t, a)| t == "room-cli" && a.get(1).is_some_and(|s| s == "tell"))
            .count(),
        2
    );
}
#[test]
fn b5_close_retries_state_but_never_repeats_its_reason_comment() {
    let w = World::new("partial_close");
    w.tick();
    w.pr(10);
    w.tick();
    w.approve(10);
    w.tick();
    w.change(|s| {
        s["issues"][1]["closed"] = false.into();
        s["fail_close_once"] = true.into();
    });
    let doc = w.tick();
    assert_eq!(doc["actions"][0]["rule"], "merged", "{doc}");
    assert_eq!(doc["actions"][0]["outcome"]["state"], "uncertain");
    assert_eq!(w.load()["issues"][1]["closed"], false);
    let doc = w.tick();
    assert_eq!(doc["actions"][0]["outcome"]["state"], "done", "{doc}");
    assert_eq!(w.load()["issues"][1]["closed"], true);
    assert_eq!(
        w.load()["comments"]["10"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|c| c["body"]
                .as_str()
                .unwrap()
                .starts_with("launch-fleet: closed: merged in #110"))
            .count(),
        1
    );
    assert_eq!(
        w.calls()
            .iter()
            .filter(|(t, a)| t == "gh" && a.get(1).is_some_and(|s| s == "close"))
            .count(),
        2
    );
}
#[test]
fn b5_noncontiguous_or_repeated_approval_table_separator_grants_no_authority() {
    for separated in [true, false] {
        let w = World::new(if separated {
            "split_approval"
        } else {
            "repeated_separator"
        });
        w.change(|s| {
            s["comments"]["9"][0]["body"] = if separated {
                fake::APPROVAL.replace("| #11", "\n| #11")
            } else {
                fake::APPROVAL.replace("| #11", "| --- | --- | --- | --- |\n| #11")
            }
            .into()
        });
        let doc = w.tick();
        assert!(
            !doc["actions"]
                .as_array()
                .unwrap()
                .iter()
                .any(|a| a["kind"] == "start_builder"),
            "{doc}"
        );
        assert_eq!(w.load()["spawn_count"], 0);
    }
}
fn stale_start_context(project: bool) {
    let w = World::new(if project {
        "project_changed"
    } else {
        "rules_changed"
    });
    w.change(|s| {
        s[if project {
            "flip_project"
        } else {
            "flip_rules"
        }] = true.into()
    });
    let doc = w.tick();
    assert_eq!(doc["actions"][0]["rule"], "frontier", "{doc}");
    assert_eq!(w.load()["spawn_count"], 0, "{doc}");
    assert_eq!(doc["actions"][0]["outcome"]["state"], "refused", "{doc}");
}
#[test]
fn b5_start_refuses_changed_rules() {
    stale_start_context(false);
}
#[test]
fn b5_start_refuses_changed_project_mapping() {
    stale_start_context(true);
}
#[test]
fn b5_pending_recovery_refuses_changed_project_mapping() {
    use openwiz_core::fleet::model::Number;
    use openwiz_core::fleet::starts::{
        Attempt, AttemptOutcome, Repository, StartKey, StartRecord, StartStore,
    };
    use openwiz_core::messaging::OpId;
    use openwiz_core::model::Timestamp;
    use openwiz_core::new_thread::Settings;
    let w = World::new("pending_project_changed");
    let key = StartKey::builder(
        Repository::parse("jparker2006/ClosedWiz").unwrap(),
        Number::new(10).unwrap(),
    );
    let r = StartRecord::from_parts(
        key.id(),
        key.clone(),
        "prj_syn_0001".into(),
        Settings {
            harness: "claude-code".into(),
            model: "claude-opus-5-5".into(),
            effort: "xhigh".into(),
        },
        vec![Attempt {
            op_id: OpId::parse("syn-b5-pending").unwrap(),
            at: Timestamp(1793400000000),
            outcome: AttemptOutcome::Pending,
        }],
    )
    .unwrap();
    let store = openwiz_store::StartFileStore::open(&w.dir.join("state")).unwrap();
    store.lock(&key).unwrap();
    store.write(&r).unwrap();
    store.unlock(&key);
    w.change(|s| s["flip_project"] = true.into());
    let doc = w.tick();
    assert_eq!(w.load()["spawn_count"], 0, "{doc}");
    assert!(
        doc["actions"]
            .as_array()
            .unwrap()
            .iter()
            .all(|a| a["kind"] != "start_builder"),
        "{doc}"
    );
}
#[test]
fn b5_recovered_starts_are_reported_with_their_outcomes() {
    use openwiz_core::fleet::model::{Commit, Number};
    use openwiz_core::fleet::starts::{
        Attempt, AttemptOutcome, Repository, StartKey, StartRecord, StartStore,
    };
    use openwiz_core::messaging::OpId;
    use openwiz_core::model::Timestamp;
    use openwiz_core::new_thread::Settings;

    // synthetic_assumptions: a crash left only a pending start record;
    // the fake reconciles it as absent, then accepts one new start.
    for reviewer in [false, true] {
        for record_fails in [false, true] {
            let w = World::new(&format!("recovery_report_{reviewer}_{record_fails}"));
            let repo = Repository::parse("jparker2006/ClosedWiz").unwrap();
            let key = if reviewer {
                w.tick();
                w.pr(10);
                StartKey::reviewer(
                    repo,
                    Number::new(110).unwrap(),
                    Commit::parse(fake::HEAD10).unwrap(),
                )
            } else {
                StartKey::builder(repo, Number::new(10).unwrap())
            };
            let r = StartRecord::from_parts(
                key.id(),
                key.clone(),
                "prj_syn_0001".into(),
                Settings {
                    harness: if reviewer { "codex" } else { "claude-code" }.into(),
                    model: if reviewer {
                        "gpt-6.1-sol"
                    } else {
                        "claude-opus-5-5"
                    }
                    .into(),
                    effort: if reviewer { "high" } else { "xhigh" }.into(),
                },
                vec![Attempt {
                    op_id: OpId::parse("syn-b5-report-pending").unwrap(),
                    at: Timestamp(1793400000000),
                    outcome: AttemptOutcome::Pending,
                }],
            )
            .unwrap();
            let store = openwiz_store::StartFileStore::open(&w.dir.join("state")).unwrap();
            store.lock(&key).unwrap();
            store.write(&r).unwrap();
            store.unlock(&key);
            if record_fails {
                w.change(|s| {
                    s["fail_record"] = if reviewer {
                        "launch-fleet: review started"
                    } else {
                        "launch-fleet: started"
                    }
                    .into()
                });
            }
            let before = w.load()["spawn_count"].as_u64().unwrap();
            let dry = w.run(&["fleet", "tick", "--dry-run", "--json"]);
            assert!(dry.status.success());
            let dry: Value = serde_json::from_slice(&dry.stdout).unwrap();
            assert_eq!(dry["actions"][0]["rule"], "look", "{dry}");
            assert_eq!(dry["actions"][0]["outcome"]["state"], "planned");
            assert_eq!(w.load()["spawn_count"], before);

            let doc = w.tick();
            assert_eq!(w.load()["spawn_count"], before + 1, "{doc}");
            let starts = doc["actions"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|a| {
                    a["kind"]
                        == if reviewer {
                            "start_reviewer"
                        } else {
                            "start_builder"
                        }
                })
                .collect::<Vec<_>>();
            assert_eq!(starts.len(), 1, "recovery must be reported: {doc}");
            let a = starts[0];
            assert_eq!(a["spec"], 9);
            assert_eq!(a["ticket"], 10);
            assert_eq!(
                a["rule"],
                if reviewer { "first_review" } else { "frontier" }
            );
            assert_eq!(
                a["outcome"]["state"],
                if record_fails { "uncertain" } else { "done" }
            );
            if record_fails {
                assert_eq!(a["outcome"]["reason"], "GitHub write not confirmed");
            }
            w.tick();
            assert_eq!(w.load()["spawn_count"], before + 1, "no duplicate start");
        }
    }
}
#[test]
fn b5_recording_fake_runs_with_the_required_node_runtime() {
    // The Rust CI step has Node but has not installed Python yet. Exercise
    // the real fake through Node, rather than relying on this host's Python.
    let w = World::new("node_runtime");
    let o = std::process::Command::new(super::fake::node())
        .arg(w.dir.join("gh"))
        .env("PATH", &w.dir)
        .args([
            "repo",
            "view",
            "--json",
            "defaultBranchRef,nameWithOwner,url",
        ])
        .output()
        .unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let value: Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(value["nameWithOwner"], "jparker2006/ClosedWiz");
    assert_eq!(
        w.calls(),
        vec![(
            "gh".into(),
            vec![
                "repo".into(),
                "view".into(),
                "--json".into(),
                "defaultBranchRef,nameWithOwner,url".into()
            ]
        )]
    );
}

#[test]
fn b5_recording_fake_finds_ci_node_outside_path() {
    // Rust CI has not run setup-node, but the image pins this tool-cache layout.
    let w = World::new("node_tool_cache");
    let node = super::fake::node();
    let cache = w.dir.join("cache");
    let bin = cache.join("node/24.22.1/x64/bin");
    std::fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&bin)
        .unwrap();
    std::os::unix::fs::symlink(&node, bin.join("node")).unwrap();
    assert_eq!(
        super::fake::node_in(
            std::ffi::OsStr::new("/synthetic/no-executables"),
            Some(&cache)
        ),
        Some(node)
    );
}

#[test]
fn b5_review_r1_real_gh_page_stream_is_strict_and_preserves_pages() {
    use openwiz_adapter_github::tick::{COMMENTS, TickReads};
    use openwiz_core::fleet::model::Number;
    let w = World::new("r1_pages");
    let key = json!([
        "gh",
        [
            "api",
            "repos/{owner}/{repo}/issues/9/comments?per_page=100",
            "--paginate",
            "--jq",
            COMMENTS
        ]
    ])
    .to_string();
    let good = "[]\n[{\"id\":2,\"body\":\"Synthetic\\nsecond line\",\"created\":10,\"updated\":10}]\n[{\"id\":1,\"body\":\"Other\",\"created\":9,\"updated\":9}]";
    w.change(|s| s["overrides"][&key] = good.into());
    let read = || {
        TickReads::new(w.dir.join("bin/gh")).comments(
            Number::new(9).unwrap(),
            std::time::Instant::now() + std::time::Duration::from_secs(5),
        )
    };
    let rows = read().expect("real gh emits separate compact page values, without --slurp");
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0].id.get(), 1);
    assert_eq!(rows[1].body, "Synthetic\nsecond line");
    for bad in [
        "",
        "[]\n\n[]",
        "{}",
        "[] {}",
        "[{}]",
        "[]\nnot JSON",
        "[{\"id\":1,\"id\":2,\"body\":\"S\",\"created\":9,\"updated\":9}]",
        "[{\"id\":1,\"body\":\"S\",\"created\":9,\"updated\":9}]\n[{\"id\":1,\"body\":\"S\",\"created\":9,\"updated\":9}]",
    ] {
        w.change(|s| s["overrides"][&key] = bad.into());
        assert!(read().is_err(), "{bad}");
    }
    w.change(|s| s["overrides"][&key] = json!({"fake_stdout":good,"fake_exit":1}));
    assert!(
        read().is_err(),
        "a failed command cannot supply partial page authority"
    );
    assert!(
        w.calls()
            .iter()
            .all(|(_, a)| !a.iter().any(|s| s == "--slurp"))
    );
}

#[test]
fn b5_review_r4_latest_nonblank_approval_never_falls_back() {
    let w = World::new("r4_latest");
    w.change(|s| {
        s["comments"]["9"].as_array_mut().unwrap().push(json!({
        "id":101,"body":"\n  **Plan graph approved by Jake, 2026-10-30, revision 2:** \"changed\"",
        "created":1793400010000_u64,"updated":1793400010000_u64
    }))
    });
    let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(o.status.success());
    let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
    assert!(
        doc["actions"]
            .as_array()
            .unwrap()
            .iter()
            .all(|a| a["kind"] != "start_builder"),
        "{doc}"
    );
    assert!(w.writes().is_empty());
}
#[test]
fn b5_review_r4_fenced_example_tables_grant_no_authority() {
    let table = "| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n| #10 | Synthetic ticket 10 | none | ready-for-agent |\n| #11 | Synthetic ticket 11 | #10 | ready-for-agent |";
    for (name, open, close) in [
        ("backtick", "```md", "```"),
        ("tilde", "  ~~~~md", "  ~~~~~ "),
        ("long", "````md", "````"),
    ] {
        let w = World::new(&format!("r4_fence_{name}"));
        w.change(|s| {
            s["comments"]["9"][0]["body"] = fake::APPROVAL
                .replace(table, &format!("{open}\n{table}\n{close}"))
                .into()
        });
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success());
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        assert!(
            doc["actions"]
                .as_array()
                .unwrap()
                .iter()
                .all(|a| a["kind"] != "start_builder"),
            "{name}: {doc}"
        );
        assert!(w.writes().is_empty());
    }
}

#[test]
fn b5_review_r4_valid_approval_accepts_first_nonblank_trimmed_heading() {
    let w = World::new("r4_valid_heading");
    w.change(|s| s["comments"]["9"][0]["body"] = format!("\n  {}", fake::APPROVAL).into());
    let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(o.status.success());
    let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(doc["actions"][0]["rule"], "frontier", "{doc}");
    assert_eq!(doc["actions"][0]["facts"]["approval"]["comment"], 100);
    assert!(w.writes().is_empty());
}

#[test]
fn r9_approval_accepts_bracketed_source_after_the_quoted_words() {
    for (name, words) in [
        ("i5_swap", "\"approved\" (the I5 swap, orchestrator thread)"),
        (
            "parallel_ci",
            "\"approved\" (orchestrator thread, to: \"run them side by side\")",
        ),
        (
            "nested_parens",
            "\"approved\" (orchestrator thread (the I5 swap))",
        ),
        ("interior_quote_bare", "\"approve the \"CI\" change\""),
        (
            "interior_quote_with_source",
            "\"approve the \"CI\" change\" (orchestrator thread)",
        ),
    ] {
        let w = World::new(&format!("r9_words_{name}"));
        w.change(|s| {
            s["comments"]["9"][0]["body"] = fake::APPROVAL.replace("\"approved\"", words).into()
        });
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(
            o.status.success(),
            "{name}: status={}\nstdout:\n{}\nstderr:\n{}",
            o.status,
            String::from_utf8_lossy(&o.stdout),
            String::from_utf8_lossy(&o.stderr),
        );
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        assert_eq!(doc["actions"][0]["rule"], "frontier", "{name}: {doc}");
        assert_eq!(
            doc["actions"][0]["facts"]["approval"]["comment"], 100,
            "{name}: {doc}"
        );
        assert!(w.writes().is_empty(), "{name}");
    }
}

#[test]
fn r9_approval_still_refuses_words_before_the_closing_quote() {
    for (name, words) in [
        ("no_quote", "approved (the I5 swap)"),
        ("unclosed", "\"approved (the I5 swap)"),
        ("only_quote", "\""),
        ("empty_words", "\"\" (the I5 swap)"),
        ("no_space_before_source", "\"approved\"(the I5 swap)"),
        ("unclosed_source", "\"approved\" ("),
        ("unclosed_source_text", "\"approved\" (the I5 swap"),
        (
            "trailing_prose_after_source",
            "\"approved\" (the I5 swap), with Jake's CI grill decisions",
        ),
        ("source_then_words", "\"approved\" (the I5 swap) more"),
    ] {
        let w = World::new(&format!("r9_refuse_{name}"));
        w.change(|s| {
            s["comments"]["9"][0]["body"] = fake::APPROVAL.replace("\"approved\"", words).into()
        });
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success(), "{name}");
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        assert!(
            doc["actions"]
                .as_array()
                .unwrap()
                .iter()
                .all(|a| a["kind"] != "start_builder"),
            "{name}: {doc}"
        );
        assert!(w.writes().is_empty(), "{name}");
    }
}

fn r3_history(w: &World) {
    stray(w, 30, "Synthetic unrelated history");
    w.pr(30);
    w.change(|s| {
        s["issues"].as_array_mut().unwrap().last_mut().unwrap()["closed"] = true.into();
        s["prs"][0]["merged"] = true.into();
        s["prs"][0]["files"] =
            json!([{"path":"src/unrelated.rs","previous":null,"status":"modified"}]);
    });
}
fn r3_calls(w: &World, needle: &str) -> usize {
    w.calls()
        .iter()
        .filter(|(tool, a)| tool == "gh" && a.get(1).is_some_and(|s| s.contains(needle)))
        .count()
}
#[test]
fn b5_review_r3_no_contract_paths_skip_history_reads() {
    let w = World::new("r3_no_paths");
    r3_history(&w);
    let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(o.status.success());
    let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(doc["actions"][0]["rule"], "frontier", "{doc}");
    assert_eq!(r3_calls(&w, "/files?"), 0);
    assert_eq!(r3_calls(&w, "/compare/"), 0);
}
#[test]
fn b5_review_r3_closed_spec_skips_contract_history_but_keeps_cleanup() {
    let w = World::new("r3_closed");
    w.tick();
    r3_history(&w);
    w.change(|s| {
        for i in s["issues"].as_array_mut().unwrap() {
            i["closed"] = true.into()
        }
    });
    let doc = w.tick();
    assert_eq!(doc["actions"][0]["rule"], "finished", "{doc}");
    assert_eq!(r3_calls(&w, "/files?"), 0);
    assert_eq!(r3_calls(&w, "/compare/"), 0);
    assert_eq!(w.load()["threads"]["thr_syn_b5_1"]["archived"], true);
}
#[test]
fn b5_review_r3_shared_history_and_targeted_authority_have_bounded_reads() {
    let w = World::new("r3_shared");
    w.change(|s| {
        s["issues"][1]["body"] =
            "**Owned paths:** `crates/example/one.rs`\n**Relies on:** `contracts/synthetic.v1.md`"
                .into();
        let a = fake::APPROVAL
            .replace(
                "60c009f9e72945c1dc45fe9f9bd9cd09dc092b5f87fcb23e3c873cf4372dca9e",
                "72dd97831192271a7b5e9bf2b1e1f900dd60a41f6e7e045ba94f407b6b99b94c",
            )
            .replace(
                "5a46b243aa88e90eaae1c4332f4d625154c4299a6fc3f15f9f75bc6ab414c66c",
                "0013041eb04bb41d913dec01d1cf15937677b7c28db2bb9bcd716a13d9e9dbf4",
            );
        s["comments"]["9"][0]["body"] = a.clone().into();
        let mut spec = s["issues"][0].clone();
        spec["n"] = 19.into();
        spec["subs"] = json!([20, 21]);
        let mut one = s["issues"][1].clone();
        one["n"] = 20.into();
        let mut two = s["issues"][2].clone();
        two["n"] = 21.into();
        two["blockers"] = json!([20]);
        s["issues"].as_array_mut().unwrap().extend([spec, one, two]);
        let a = a
            .replace("#11", "#21")
            .replace("#10", "#20")
            .replace("#9", "#19")
            .replace(
                "0013041eb04bb41d913dec01d1cf15937677b7c28db2bb9bcd716a13d9e9dbf4",
                "ff6cc86f2e1852e2d756bfd09469e3eb777163e9ee5d6e04990a4e7b48f84ba0",
            );
        s["comments"]["19"] =
            json!([{"id":200,"body":a,"created":1793400000000_u64,"updated":1793400000000_u64}]);
    });
    r3_history(&w);
    let doc = w.tick();
    assert_eq!(doc["actions"].as_array().unwrap().len(), 2, "{doc}");
    assert!(
        doc["actions"]
            .as_array()
            .unwrap()
            .iter()
            .all(|a| a["rule"] == "frontier" && a["outcome"]["state"] == "done"),
        "{doc}"
    );
    assert_eq!(r3_calls(&w, "/files?"), 1);
    assert_eq!(r3_calls(&w, "/compare/"), 1);
    assert_eq!(r3_calls(&w, "/issues/comments?"), 1);
    assert_eq!(r3_calls(&w, "/issues/9/comments?"), 1);
    assert_eq!(r3_calls(&w, "/issues/19/comments?"), 1);
}

#[test]
fn b5_review_r3_new_contract_merge_and_base_invalidate_cached_authority() {
    let w = World::new("r3_cache_authority");
    w.change(|s| {
        s["issues"][1]["body"] =
            "**Owned paths:** `crates/example/one.rs`\n**Relies on:** `contracts/synthetic.v1.md`"
                .into();
        s["comments"]["9"][0]["body"] = fake::APPROVAL
            .replace(
                "60c009f9e72945c1dc45fe9f9bd9cd09dc092b5f87fcb23e3c873cf4372dca9e",
                "72dd97831192271a7b5e9bf2b1e1f900dd60a41f6e7e045ba94f407b6b99b94c",
            )
            .replace(
                "5a46b243aa88e90eaae1c4332f4d625154c4299a6fc3f15f9f75bc6ab414c66c",
                "0013041eb04bb41d913dec01d1cf15937677b7c28db2bb9bcd716a13d9e9dbf4",
            )
            .into();
        s["merge_contract_after_files"] = true.into();
    });
    r3_history(&w);
    let doc = w.tick();
    assert_eq!(doc["actions"][0]["rule"], "frontier", "{doc}");
    assert_eq!(doc["actions"][0]["outcome"]["state"], "refused", "{doc}");
    assert_eq!(w.load()["spawn_count"], 0);
    assert_eq!(r3_calls(&w, "/pulls/130/files?"), 1);
    assert_eq!(r3_calls(&w, "/pulls/131/files?"), 1);
    let compared = w
        .calls()
        .into_iter()
        .filter_map(|(tool, a)| {
            (tool == "gh" && a.get(1).is_some_and(|p| p.contains("/compare/")))
                .then(|| a[1].clone())
        })
        .collect::<Vec<_>>();
    assert_eq!(
        compared,
        vec![
            format!(
                "repos/{{owner}}/{{repo}}/compare/{}...{}",
                "a".repeat(40),
                fake::BASE
            ),
            format!(
                "repos/{{owner}}/{{repo}}/compare/{}...{}",
                "a".repeat(40),
                "e".repeat(40)
            ),
            format!(
                "repos/{{owner}}/{{repo}}/compare/{}...{}",
                "d".repeat(40),
                "e".repeat(40)
            ),
        ]
    );
}
#[test]
fn b5_approval_time_is_creation_not_edit() {
    let w = World::new("approval_created");
    w.change(|s| {
        s["issues"][1]["body"] =
            "**Owned paths:** `crates/example/one.rs`\n**Relies on:** `contracts/synthetic.v1.md`"
                .into();
        s["comments"]["9"][0]["body"] = fake::APPROVAL
            .replace(
                "60c009f9e72945c1dc45fe9f9bd9cd09dc092b5f87fcb23e3c873cf4372dca9e",
                "72dd97831192271a7b5e9bf2b1e1f900dd60a41f6e7e045ba94f407b6b99b94c",
            )
            .replace(
                "5a46b243aa88e90eaae1c4332f4d625154c4299a6fc3f15f9f75bc6ab414c66c",
                "0013041eb04bb41d913dec01d1cf15937677b7c28db2bb9bcd716a13d9e9dbf4",
            )
            .into();
        // The approval was created before the merge below and edited after it.
        s["comments"]["9"][0]["created"] = json!(1793400000000_u64);
        s["comments"]["9"][0]["updated"] = json!(1793406000000_u64);
    });
    stray(&w, 30, "Synthetic completed contract change");
    w.pr(30);
    w.change(|s| {
        s["issues"].as_array_mut().unwrap().last_mut().unwrap()["closed"] = true.into();
        s["prs"][0]["merged"] = true.into();
        s["prs"][0]["merged_at"] = "2026-10-30T23:00:00Z".into();
        s["prs"][0]["files"] =
            json!([{"path":"contracts/synthetic.v1.md","previous":null,"status":"modified"}]);
    });
    let doc = w.tick();
    assert_eq!(doc["actions"][0]["rule"], "contract_hold", "{doc}");
}

#[test]
fn b5_review_r3_targeted_refresh_still_refuses_global_placement_conflicts() {
    let w = World::new("r3_placement_authority");
    w.change(|s| s["duplicate_placement_after_comments"] = true.into());
    let doc = w.tick();
    assert_eq!(doc["actions"][0]["rule"], "frontier", "{doc}");
    assert_eq!(doc["actions"][0]["outcome"]["state"], "refused", "{doc}");
    assert_eq!(w.load()["spawn_count"], 0);
    assert!(w.writes().is_empty());
}

#[test]
fn b5_review_r3_fifteen_closed_specs_and_two_hundred_merges_keep_cleanup_readable() {
    use openwiz_core::messaging::sha256_hex;
    let w = World::new("r3_scale");
    w.tick();
    w.change(|s| {
        let templates = s["issues"].as_array().unwrap().clone();
        for k in 0..14 {
            let spec = 100 + k*3;
            let one = spec + 1;
            let two = spec + 2;
            let mut rows = templates.clone();
            rows[0]["n"] = spec.into();rows[0]["subs"] = json!([one,two]);
            rows[1]["n"] = one.into();rows[2]["n"] = two.into();rows[2]["blockers"] = json!([one]);
            s["issues"].as_array_mut().unwrap().extend(rows);
            let body = fake::APPROVAL.replace("#11", "TWO").replace("#10", "ONE").replace("#9", "SPEC")
                .replace("TWO", &format!("#{two}")).replace("ONE", &format!("#{one}")).replace("SPEC", &format!("#{spec}"));
            let revision = body.split_once("```text\n").unwrap().1.split_once("```").unwrap().0;
            let body = body.replace("5a46b243aa88e90eaae1c4332f4d625154c4299a6fc3f15f9f75bc6ab414c66c", &sha256_hex(revision.as_bytes()));
            s["comments"][spec.to_string()] = json!([{"id":2000+k,"body":body,"created":1793400000000_u64,"updated":1793400000000_u64}]);
        }
        let mut history = templates[1].clone();history["n"] = 500.into();s["issues"].as_array_mut().unwrap().push(history);
        for row in s["issues"].as_array_mut().unwrap() {row["closed"] = true.into();}
        let tickets = s["issues"].as_array().unwrap().iter().filter(|i| i["subs"].as_array().unwrap().is_empty() && i["n"] != 500).map(|i| i["n"].as_u64().unwrap()).collect::<Vec<_>>();
        for n in 600..800 {
            let ticket = tickets[(n-600) as usize % tickets.len()];
            s["prs"].as_array_mut().unwrap().push(json!({"n":n,"ticket":ticket,"head":fake::HEAD11,"base":fake::BASE,"merged":true,"report":null,"files":[],"subject":"Synthetic historical merge","ci":"success"}));
        }
    });
    let doc = w.tick();
    assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{doc}");
    assert_eq!(doc["actions"][0]["rule"], "finished", "{doc}");
    assert_eq!(doc["actions"][0]["outcome"]["state"], "done", "{doc}");
    assert_eq!(r3_calls(&w, "/files?"), 0);
    assert_eq!(r3_calls(&w, "/compare/"), 0);
}

#[test]
fn b5_review_r2_archive_record_recovers_after_agents_are_already_archived() {
    let w = World::new("r2_archive_record");
    w.tick();
    w.change(|s| {
        s["issues"][1]["closed"] = true.into();
        s["fail_record"] = "launch-fleet: archived".into();
    });
    let first = w.tick();
    assert_eq!(first["actions"][0]["rule"], "finished", "{first}");
    assert_eq!(
        first["actions"][0]["outcome"]["state"], "uncertain",
        "{first}"
    );
    assert_eq!(w.load()["threads"]["thr_syn_b5_1"]["archived"], true);
    w.change(|s| s["fail_record"] = "".into());
    let retry = w.tick();
    assert_eq!(retry["actions"][0]["rule"], "finished", "{retry}");
    assert_eq!(retry["actions"][0]["outcome"]["state"], "done", "{retry}");
    assert_eq!(
        w.calls()
            .iter()
            .filter(|(tool, a)| tool == "room-cli" && a.get(1).is_some_and(|v| v == "archive"))
            .count(),
        1
    );
    assert_eq!(
        w.load()["comments"]["10"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|c| c["body"] == "launch-fleet: archived")
            .count(),
        1
    );
    assert!(w.tick()["actions"].as_array().unwrap().is_empty());
    let due = w.run(&["fleet", "due", "--github-only"]);
    assert!(due.status.success());
    assert!(due.stdout.is_empty());
}

#[test]
fn b5_review_r2_github_only_cannot_distinguish_an_unlogged_local_start() {
    let absent = World::new("r2_absent");
    let local = World::new("r2_local");
    local.tick();
    for w in [&absent, &local] {
        w.change(|s| {
            s["issues"][1]["closed"] = true.into();
            s["comments"]["10"] = json!([]);
        });
    }
    for field in ["issues", "prs", "comments", "base", "rules"] {
        assert_eq!(absent.load()[field], local.load()[field], "{field}");
    }
    assert_eq!(absent.load()["spawn_count"], 0);
    assert_eq!(local.load()["spawn_count"], 1);
    for w in [&absent, &local] {
        let before = w.calls().len();
        let o = w
            .command(&["fleet", "due", "--github-only"])
            .env("OPENWIZ_STATE_DIR", "relative-forbidden")
            .env_remove("HOME")
            .output()
            .unwrap();
        assert!(o.status.success());
        assert_eq!(
            String::from_utf8(o.stdout).unwrap(),
            "fleet #9: candidate #10\n"
        );
        assert!(w.calls()[before..].iter().all(|(tool, _)| tool == "gh"));
    }
}

#[test]
fn b5_review_r3b_due_reads_one_inventory_and_one_repository_comment_snapshot() {
    let w = World::new("r3b_bulk_due");
    let o = w
        .command(&["fleet", "due", "--github-only"])
        .env("OPENWIZ_STATE_DIR", "relative-forbidden")
        .env_remove("HOME")
        .output()
        .unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    assert_eq!(
        String::from_utf8(o.stdout).unwrap(),
        "fleet #9: candidate #10\n"
    );
    let calls = w.calls();
    for pair in [["repo", "view"], ["issue", "list"], ["pr", "list"]] {
        assert_eq!(
            calls
                .iter()
                .filter(|(tool, a)| tool == "gh"
                    && a.first().map(String::as_str) == Some(pair[0])
                    && a.get(1).map(String::as_str) == Some(pair[1]))
                .count(),
            if pair == ["repo", "view"] { 2 } else { 1 },
            "{pair:?}: {calls:?}"
        );
    }
    // The two repo reads have distinct contracts: one inventory identity and
    // one freshly verified privacy fact. Neither may be repeated or omitted.
    for fields in [
        "defaultBranchRef,nameWithOwner,url",
        "nameWithOwner,isPrivate",
    ] {
        assert_eq!(
            calls
                .iter()
                .filter(|(tool, args)| tool == "gh"
                    && args
                        .iter()
                        .map(String::as_str)
                        .eq(["repo", "view", "--json", fields]))
                .count(),
            1,
            "{fields}: {calls:?}"
        );
    }
    assert_eq!(r3_calls(&w, "/issues/comments?"), 1);
    assert_eq!(
        calls
            .iter()
            .filter(|(_, a)| a
                .get(1)
                .is_some_and(|s| s.contains("/comments?") && !s.contains("/issues/comments?")))
            .count(),
        0
    );
    assert!(calls.iter().all(|(tool, _)| tool == "gh"));
    assert!(!w.dir.join("state").exists());
}

fn r3b_comments_key() -> String {
    r3b_comments_page_key(1)
}
fn r3b_comments_page_key(page: usize) -> String {
    json!([
        "gh",
        [
            "api",
            format!("repos/{{owner}}/{{repo}}/issues/comments?per_page=100&page={page}"),
            "--jq",
            openwiz_adapter_github::tick::REPOSITORY_COMMENTS
        ]
    ])
    .to_string()
}
fn r3b_comment_row(issue: u64, id: u64) -> Value {
    json!({"issue_url":format!("https://github.invalid/api/v3/repos/jparker2006/ClosedWiz/issues/{issue}"),"id":id,"body":"Synthetic\nsecond line","created":100,"updated":101})
}
#[test]
fn b5_review_r3b_bulk_comments_keep_page_identity_and_comment_order() {
    use openwiz_adapter_github::tick::{Repository, TickReads};
    use openwiz_core::fleet::model::{NonEmpty, Number};
    let w = World::new("r3b_grouped");
    let key = r3b_comments_key();
    w.change(|s| {
        let mut first = vec![r3b_comment_row(9, 20), r3b_comment_row(110, 11)];
        first.extend((1000..1098).map(|id| r3b_comment_row(110, id)));
        s["overrides"][&key] = json!(first);
        s["overrides"][r3b_comments_page_key(2)] = json!([r3b_comment_row(9, 10)]);
    });
    let reader = TickReads::new(w.dir.join("bin/gh"));
    let deadline = || std::time::Instant::now() + std::time::Duration::from_secs(5);
    let repo = reader.repository(deadline()).unwrap();
    let snapshot = reader.repository_comments(&repo, deadline()).unwrap();
    assert!(snapshot.unread.is_empty());
    let grouped = snapshot.comments;
    assert_eq!(grouped.len(), 2);
    assert_eq!(
        grouped[&Number::new(9).unwrap()]
            .iter()
            .map(|c| c.id.get())
            .collect::<Vec<_>>(),
        vec![10, 20]
    );
    assert_eq!(
        grouped[&Number::new(110).unwrap()][0].body,
        "Synthetic\nsecond line"
    );
    assert!(!grouped.contains_key(&Number::new(10).unwrap()));
    let repo = Repository {
        name: repo.name,
        default: NonEmpty::new("main").unwrap(),
        url: "https://github.com/jparker2006/ClosedWiz".into(),
    };
    let mut row = r3b_comment_row(9, 1);
    row["issue_url"] = "https://api.github.com/repos/jparker2006/ClosedWiz/issues/9".into();
    w.change(|s| s["overrides"][&key] = json!([row]));
    assert_eq!(
        reader
            .repository_comments(&repo, deadline())
            .unwrap()
            .comments
            .len(),
        1
    );
}
#[test]
fn b5_review_r3b_bulk_comments_refuse_ambiguous_or_partial_facts() {
    use openwiz_adapter_github::tick::TickReads;
    let w = World::new("r3b_bad_groups");
    let key = r3b_comments_key();
    let reader = TickReads::new(w.dir.join("bin/gh"));
    let deadline = || std::time::Instant::now() + std::time::Duration::from_secs(5);
    let repo = reader.repository(deadline()).unwrap();
    let good = r3b_comment_row(9, 1);
    for url in [
        "https://foreign.invalid/api/v3/repos/jparker2006/ClosedWiz/issues/9",
        "https://github.invalid/api/v3/repos/foreign/repo/issues/9",
        "http://github.invalid/api/v3/repos/jparker2006/ClosedWiz/issues/9",
        "https://github.invalid/api/v3/repos/jparker2006/ClosedWiz/issues/09",
        "https://github.invalid/api/v3/repos/jparker2006/ClosedWiz/issues/+9",
        "https://github.invalid/api/v3/repos/jparker2006/ClosedWiz/issues/%39",
        "https://github.invalid/api/v3/repos/jparker2006/ClosedWiz/issues/9/",
        "https://github.invalid/api/v3/repos/jparker2006/ClosedWiz/issues/9?x=1",
        "https://github.invalid/api/v3/repos/jparker2006/ClosedWiz/issues/9#x",
    ] {
        let mut row = good.clone();
        row["issue_url"] = url.into();
        w.change(|s| s["overrides"][&key] = json!([row]));
        assert!(
            reader.repository_comments(&repo, deadline()).is_err(),
            "{url}"
        );
    }
    let mut missing = good.clone();
    missing.as_object_mut().unwrap().remove("issue_url");
    let mut extra = good.clone();
    extra["extra"] = true.into();
    let mut bad_id = good.clone();
    bad_id["id"] = 0.into();
    let mut bad_time = good.clone();
    bad_time["updated"] = 99.into();
    let mut bad_body = good.clone();
    bad_body["body"] = json!({});
    let mut same_id_elsewhere = good.clone();
    same_id_elsewhere["issue_url"] = r3b_comment_row(110, 1)["issue_url"].clone();
    w.change(|s| s["overrides"][&key] = json!([missing]));
    assert!(reader.repository_comments(&repo, deadline()).is_err());
    for pages in [
        json!([extra]),
        json!([bad_id]),
        json!([bad_time]),
        json!([bad_body]),
        json!([good.clone(), same_id_elsewhere]),
        json!([good.clone(), good.clone()]),
    ] {
        w.change(|s| s["overrides"][&key] = pages);
        let snapshot = reader.repository_comments(&repo, deadline()).unwrap();
        assert!(
            snapshot
                .unread
                .contains(&openwiz_core::fleet::model::Number::new(9).unwrap())
        );
        assert!(
            !snapshot
                .comments
                .contains_key(&openwiz_core::fleet::model::Number::new(9).unwrap())
        );
    }
    for raw in ["", "{}", "[]\nnot JSON", "[] []", "[{\"id\":1,\"id\":2}]"] {
        w.change(|s| s["overrides"][&key] = raw.into());
        assert!(
            reader.repository_comments(&repo, deadline()).is_err(),
            "{raw}"
        );
    }
    w.change(|s| {
        s["overrides"][&key] = json!({"fake_exit":1,"fake_stdout":json!([good]).to_string()})
    });
    assert!(reader.repository_comments(&repo, deadline()).is_err());
    let before = w.calls().len();
    assert!(
        reader
            .repository_comments(
                &repo,
                std::time::Instant::now() - std::time::Duration::from_secs(1)
            )
            .is_err()
    );
    assert_eq!(w.calls().len(), before);
}
#[test]
fn b5_review_r3b_bulk_allowlist_and_global_failure_are_exact() {
    use openwiz_adapter_github::{allowlist::Invocation, tick::REPOSITORY_COMMENTS};
    let good = [
        "api",
        "repos/{owner}/{repo}/issues/comments?per_page=100&page=1",
        "--jq",
        REPOSITORY_COMMENTS,
    ];
    assert!(Invocation::new(&good).is_some());
    for index in 0..good.len() {
        let mut bad = good;
        bad[index] = "unexpected";
        assert!(Invocation::new(&bad).is_none(), "{index}");
    }
    let mut bad = good;
    bad[1] = "repos/foreign/repo/issues/comments?per_page=100&page=1";
    assert!(Invocation::new(&bad).is_none());
    let mut bad = good;
    bad[2] = "--slurp";
    assert!(Invocation::new(&bad).is_none());
    let w = World::new("r3b_bulk_failure");
    w.change(|s| s["overrides"][r3b_comments_key()] = 1.into());
    let o = w.run(&["fleet", "due", "--github-only"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(o.stdout.is_empty());
    assert!(w.writes().is_empty());
    assert!(w.calls().iter().all(|(tool, _)| tool == "gh"));
}

#[test]
fn b5_review_r3b_independent_containment_reads_rendezvous_before_summary() {
    let w = World::new("r3b_parallel_compares");
    w.pr(10);
    w.pr(11);
    w.change(|s| {
        s["issues"][1]["closed"] = true.into();
        s["issues"][2]["closed"] = true.into();
        s["prs"][0]["merged"] = true.into();
        s["prs"][1]["merged"] = true.into();
        s["prs"][1]["merge"] = "c".repeat(40).into();
        s["compare_barrier"] = true.into();
    });
    let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(o.status.success());
    let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{doc}");
    assert_eq!(doc["actions"][0]["rule"], "spec_summary", "{doc}");
    assert_eq!(
        doc["actions"][0]["facts"]["merged"],
        json!([{"ticket":10,"pr":110},{"ticket":11,"pr":111}])
    );
    assert_eq!(r3_calls(&w, "/compare/"), 2);
    assert!(w.writes().is_empty());
}
#[test]
fn b5_review_r3b_closed_ticket_pr_is_not_read_until_a_summary_is_due() {
    let w = World::new("r3b_no_summary_read");
    w.pr(10);
    w.change(|s| {
        s["issues"][1]["closed"] = true.into();
        s["issues"][2]["blockers"] = json!([]);
        s["issues"][2]["labels"] = json!([]);
        s["prs"][0]["merged"] = true.into();
    });
    let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(o.status.success());
    let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
    assert!(doc["actions"].as_array().unwrap().is_empty(), "{doc}");
    assert_eq!(r3_calls(&w, "/compare/"), 0);
}

fn r8_two_blockers(name: &str, cell: &str) -> World {
    let w = World::new(name);
    stray(&w, 12, "Synthetic second blocker");
    w.pr(10);
    w.pr(12);
    w.change(|s| {
        s["issues"][1]["closed"] = true.into();
        s["issues"][3]["closed"] = true.into();
        s["issues"][2]["blockers"] = json!([12, 10]);
        s["prs"][0]["merged"] = true.into();
        s["prs"][1]["merged"] = true.into();
        s["comments"]["9"][0]["body"] = fake::APPROVAL
            .replace(
                "| #11 | Synthetic ticket 11 | #10 |",
                &format!("| #11 | Synthetic ticket 11 | {cell} |"),
            )
            .replace(
                "ticket #11 blocked-by #10 body",
                "ticket #11 blocked-by #10 #12 body",
            )
            .replace(
                "5a46b243aa88e90eaae1c4332f4d625154c4299a6fc3f15f9f75bc6ab414c66c",
                "9fbe94b6e579f4b5019c7536e2e2bd42dec8ab3c665f0c8e2b38795649d3c08c",
            )
            .into();
    });
    w
}
#[test]
fn b5_review_r8_blocker_order_does_not_change_current_approval_authority() {
    for (i, cell) in [
        "#12, #10",
        "#12 #10",
        "#12,#10",
        "#10,#12",
        "#10, #12",
        "#12,\t#10",
        "#12 \t#10",
    ]
    .into_iter()
    .enumerate()
    {
        let w = r8_two_blockers(&format!("r8_order_{i}"), cell);
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        let a = doc["actions"]
            .as_array()
            .unwrap()
            .iter()
            .find(|a| a["rule"] == "frontier")
            .expect("an equal blocker set preserves approval");
        assert_eq!(a["ticket"], 11, "{cell}: {doc}");
        assert_eq!(a["facts"]["approval"]["comment"], 100);
        assert_eq!(
            a["facts"]["blockers"]
                .as_array()
                .unwrap()
                .iter()
                .map(|b| b["number"].as_u64().unwrap())
                .collect::<Vec<_>>(),
            vec![10, 12]
        );
        assert!(w.writes().is_empty());
    }
}
#[test]
fn b5_review_r8_blocker_mismatches_duplicates_and_bad_tokens_grant_no_authority() {
    for (i, cell) in [
        "#10",
        "#10 #12 #13",
        "none",
        "#10 #10 #12",
        "#10, #12, #12",
        "#10,,#12",
        ",#10 #12",
        "#10 #12,",
        "#010 #12",
        "#0 #12",
        "#10 #+12",
        "#10 #12 trailing",
        "#10, none",
        "",
        "#10;#12",
        "#1,0 #12",
        "10 #12",
        "#10 #18446744073709551616",
    ]
    .into_iter()
    .enumerate()
    {
        let w = r8_two_blockers(&format!("r8_bad_{i}"), cell);
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success());
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{cell}: {doc}");
        assert_eq!(doc["actions"][0]["rule"], "look", "{cell}: {doc}");
        assert!(w.writes().is_empty());
    }
}
#[test]
fn b5_review_r8_duplicate_revision_blockers_are_refused_even_with_a_valid_hash() {
    for (i, cell) in ["#10 #12", "#10 #10 #12"].into_iter().enumerate() {
        let w = r8_two_blockers(&format!("r8_duplicate_revision_{i}"), cell);
        w.change(|s| {
            s["comments"]["9"][0]["body"] = s["comments"]["9"][0]["body"]
                .as_str()
                .unwrap()
                .replace(
                    "ticket #11 blocked-by #10 #12 body",
                    "ticket #11 blocked-by #10 #10 #12 body",
                )
                .replace(
                    "9fbe94b6e579f4b5019c7536e2e2bd42dec8ab3c665f0c8e2b38795649d3c08c",
                    "c56b7d06982acf19aaa63163fecbdec8186100c8db98fb9be1f3440ec971b7c6",
                )
                .into()
        });
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success());
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        assert_eq!(doc["actions"][0]["rule"], "look", "{doc}");
        assert!(w.writes().is_empty());
    }
}

#[test]
fn b5_review_r8_none_is_the_only_empty_blocker_set() {
    for (i, cell) in ["none", "", ",", "None", "none none"]
        .into_iter()
        .enumerate()
    {
        let w = World::new(&format!("r8_empty_{i}"));
        w.change(|s| {
            s["comments"]["9"][0]["body"] = fake::APPROVAL
                .replace(
                    "| #10 | Synthetic ticket 10 | none |",
                    &format!("| #10 | Synthetic ticket 10 | {cell} |"),
                )
                .into();
        });
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success());
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{cell}: {doc}");
        assert_eq!(
            doc["actions"][0]["rule"],
            if cell == "none" { "frontier" } else { "look" },
            "{cell}: {doc}"
        );
        assert!(w.writes().is_empty());
    }
}

#[test]
fn b5_review_r11_summary_record_forms_prevent_repeat_notification_and_due() {
    for (i, body) in [
        "launch-fleet: spec summary",
        "launch-fleet: spec summary\nSynthetic summary body.",
        "launch-fleet: spec summary: synthetic",
        "launch-fleet: spec summary:synthetic",
        "launch-fleet: spec summaryish",
    ]
    .into_iter()
    .enumerate()
    {
        let w = World::new(&format!("r11_summary_{i}"));
        stray(&w, 12, "Follow-up of #10 (spec #9)\nSynthetic follow-up.");
        w.pr(10);
        w.pr(11);
        w.change(|s| {
            s["issues"][1]["closed"] = true.into();
            s["issues"][2]["closed"] = true.into();
            s["prs"][0]["merged"] = true.into();
            s["prs"][1]["merged"] = true.into();
            for (n, id, text) in [(9, 900, body), (10, 901, "launch-fleet: archived"), (11, 902, "launch-fleet: archived")] {
                s["comments"][n.to_string()].as_array_mut().map(|cs| cs.push(json!({"id":id,"body":text,"created":1793400010000_u64,"updated":1793400010000_u64}))).unwrap_or_else(|| {
                    s["comments"][n.to_string()] = json!([{ "id":id,"body":text,"created":1793400010000_u64,"updated":1793400010000_u64}]);
                });
            }
        });
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success());
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        let expected = if i == 4 { vec!["spec_summary"] } else { vec![] };
        assert_eq!(
            doc["actions"]
                .as_array()
                .unwrap()
                .iter()
                .map(|a| a["rule"].as_str().unwrap())
                .collect::<Vec<_>>(),
            expected,
            "{body}: {doc}"
        );
        let due = w.run(&["fleet", "due", "--github-only"]);
        assert!(due.status.success());
        assert_eq!(
            String::from_utf8(due.stdout).unwrap(),
            if i == 4 {
                "fleet #9: candidate spec\n"
            } else {
                ""
            },
            "{body}"
        );
        assert!(w.writes().is_empty());
    }
}

fn r12_closed_review(name: &str) -> World {
    let w = World::new(name);
    w.tick();
    w.pr(10);
    w.tick();
    w.change(|s| {
        s["issues"][1]["closed"] = true.into();
        let mut replacement = s["prs"][0].clone();
        replacement["n"] = 210.into();
        replacement["merged"] = true.into();
        s["prs"][0]["closed"] = true.into();
        s["prs"].as_array_mut().unwrap().push(replacement);
    });
    w
}
#[test]
fn b5_review_r12_closed_unmerged_pr_reviewer_is_archived_before_completion_record() {
    let w = r12_closed_review("r12_closed_review");
    let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(o.status.success());
    let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
    let a = doc["actions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|a| a["rule"] == "finished")
        .unwrap();
    assert_eq!(
        a["facts"]["threads"],
        json!([
            {"thread":"thr_syn_b5_1","role":"builder"},
            {"thread":"thr_syn_b5_2","role":"reviewer"}
        ]),
        "{doc}"
    );
    let doc = w.tick();
    assert!(
        doc["actions"]
            .as_array()
            .unwrap()
            .iter()
            .any(|a| a["rule"] == "finished" && a["outcome"]["state"] == "done"),
        "{doc}"
    );
    for thread in ["thr_syn_b5_1", "thr_syn_b5_2"] {
        assert_eq!(w.load()["threads"][thread]["archived"], true);
        assert_eq!(
            w.calls()
                .iter()
                .filter(
                    |(tool, a)| tool == "room-cli" && a == &["thread", "archive", thread, "--json"]
                )
                .count(),
            1
        );
    }
    assert_eq!(
        w.load()["comments"]["10"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|c| c["body"] == "launch-fleet: archived")
            .count(),
        1
    );
    let again = w.tick();
    assert!(
        !again["actions"]
            .as_array()
            .unwrap()
            .iter()
            .any(|a| a["rule"] == "finished" && a["ticket"] == 10),
        "{again}"
    );
}
#[test]
fn b5_review_r12_unread_or_foreign_closed_review_association_cannot_finish_cleanup() {
    for (i, foreign) in [false, true].into_iter().enumerate() {
        let w = r12_closed_review(&format!("r12_unread_{i}"));
        w.change(|s| {
            if foreign {
                s["prs"][0]["closing_url"] =
                    "https://foreign.invalid/other/repository/issues/10".into();
            } else {
                s["prs"][0]["no_closes"] = true.into();
            }
        });
        let before = w.writes().len();
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success());
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        assert!(
            doc["actions"]
                .as_array()
                .unwrap()
                .iter()
                .any(|a| a["ticket"] == 10 && a["rule"] == "look"),
            "{doc}"
        );
        assert!(
            !doc["actions"]
                .as_array()
                .unwrap()
                .iter()
                .any(|a| a["ticket"] == 10 && a["rule"] == "finished"),
            "{doc}"
        );
        assert_eq!(w.writes().len(), before);
        assert!(
            w.load()["comments"]["10"]
                .as_array()
                .unwrap()
                .iter()
                .all(|c| c["body"] != "launch-fleet: archived")
        );
    }
}

#[test]
fn b5_r19_unlinked_closed_review_comments_only_block_their_own_ticket_cleanup() {
    r19_unlinked_closed_review_cleanup(false);
}

#[test]
fn b5_r19_foreign_closed_reference_still_blocks_a_replaced_review_head() {
    let w = r12_closed_review("r19_foreign_replaced_head");
    w.change(|s| {
        s["prs"][0]["closing_url"] = "https://foreign.invalid/other/repository/issues/10".into();
        s["prs"][1]["head"] = fake::HEAD11.into();
    });
    r19_assert_cleanup_is_unread(&w);
}

#[test]
fn b5_r19_unlinked_replaced_head_comments_cannot_finish_cleanup() {
    r19_unlinked_replacement_review("comments");
}

#[test]
fn b5_r19_unlinked_replaced_head_starts_cannot_finish_cleanup() {
    r19_unlinked_replacement_review("starts");
}

#[test]
fn b5_r19_unlinked_replaced_head_unread_comments_cannot_finish_cleanup() {
    r19_unlinked_replacement_review("unread");
}

fn r19_unlinked_replacement_review(source: &str) {
    let w = r12_closed_review(&format!("r19_unlinked_replaced_{source}"));
    if source != "starts" {
        fs::remove_dir_all(w.dir.join("state/starts")).unwrap();
    }
    w.change(|s| {
        s["prs"][0]["no_closes"] = true.into();
        s["prs"][1]["head"] = fake::HEAD11.into();
        match source {
            "starts" => s["comments"]["110"] = json!([]),
            "unread" => s["comments"]["110"][0]["body"] = Value::Null,
            "comments" => {}
            _ => panic!("unknown synthetic review source"),
        }
    });
    r19_assert_cleanup_is_unread(&w);
}

fn r19_assert_cleanup_is_unread(w: &World) {
    let before = w.writes().len();
    let out = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let doc: Value = serde_json::from_slice(&out.stdout).unwrap();
    let actions = doc["actions"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|a| a["ticket"] == 10)
        .collect::<Vec<_>>();
    assert_eq!(actions.len(), 1, "{doc}");
    assert_eq!(actions[0]["rule"], "look", "{doc}");
    assert_eq!(actions[0]["facts"]["reason"], "records unread", "{doc}");
    assert_eq!(w.writes().len(), before);
    let doc = w.tick();
    assert!(
        doc["actions"]
            .as_array()
            .unwrap()
            .iter()
            .all(|a| a["ticket"] != 10 || a["rule"] == "look"),
        "{doc}"
    );
    let state = w.load();
    for thread in ["thr_syn_b5_1", "thr_syn_b5_2"] {
        assert_eq!(state["threads"][thread]["archived"], false);
    }
    assert!(
        state["comments"]["10"]
            .as_array()
            .unwrap()
            .iter()
            .all(|c| c["body"] != "launch-fleet: archived")
    );
}

#[test]
fn b5_r19_unlinked_closed_review_starts_only_block_their_own_ticket_cleanup() {
    r19_unlinked_closed_review_cleanup(true);
}

fn r19_unlinked_closed_review_cleanup(durable: bool) {
    let w = r12_closed_review(&format!("r19_unlinked_review_{durable}"));
    if !durable {
        fs::remove_dir_all(w.dir.join("state/starts")).unwrap();
    }
    w.pr(11);
    w.change(|s| {
        if durable {
            s["comments"]["110"] = json!([]);
        }
        s["prs"][0]["no_closes"] = true.into();
        s["issues"][2]["closed"] = true.into();
        s["prs"][2]["merged"] = true.into();
        s["threads"]["thr_syn_ticket11"] = json!({"provider":"claude-code","model":"claude-opus-5-5","effort":"xhigh","archived":false,"prompt":"synthetic builder"});
        s["comments"]["11"] = json!([{"id":1900,"body":"launch-fleet: start checked, thread thr_syn_ticket11, branch synthetic-branch-11","created":1793400010000_u64,"updated":1793400010000_u64}]);
    });
    let before = w.writes().len();
    let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(
        doc["actions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|a| (a["ticket"].as_u64(), a["rule"].as_str().unwrap()))
            .collect::<Vec<_>>(),
        [(Some(10), "look"), (Some(11), "finished")],
        "{doc}"
    );
    assert_eq!(
        doc["actions"][1]["facts"]["threads"],
        json!([{"thread":"thr_syn_ticket11","role":"builder"}]),
        "{doc}"
    );
    assert_eq!(w.writes().len(), before);

    let doc = w.tick();
    assert_eq!(doc["actions"][1]["outcome"]["state"], "done", "{doc}");
    let writes = w.writes();
    assert_eq!(writes.len() - before, 2, "{writes:?}");
    assert_eq!(
        writes[before],
        (
            "room-cli".into(),
            vec![
                "thread".into(),
                "archive".into(),
                "thr_syn_ticket11".into(),
                "--json".into()
            ]
        )
    );
    let state = w.load();
    assert_eq!(state["threads"]["thr_syn_ticket11"]["archived"], true);
    for thread in ["thr_syn_b5_1", "thr_syn_b5_2"] {
        assert_eq!(state["threads"][thread]["archived"], false);
    }
    for (ticket, expected) in [("10", 0), ("11", 1)] {
        assert_eq!(
            state["comments"][ticket]
                .as_array()
                .unwrap()
                .iter()
                .filter(|c| c["body"] == "launch-fleet: archived")
                .count(),
            expected
        );
    }
    super::legacy_records(&w);
    let due = w.run(&["fleet", "due", "--github-only"]);
    assert!(
        due.status.success(),
        "{}",
        String::from_utf8_lossy(&due.stderr)
    );
    assert_eq!(
        String::from_utf8(due.stdout).unwrap(),
        // GitHub-only due cannot see the durable reviewer start. With no
        // review comment it conservatively also lists possible spec work.
        if durable {
            "fleet #9: candidate spec\nfleet #9: candidate #10\n"
        } else {
            "fleet #9: candidate #10\n"
        }
    );
    assert_eq!(w.writes().len(), before + 2);
}

#[test]
fn b5_review_r10_inventory_reads_rendezvous_under_the_existing_cap() {
    let w = World::new("r10_inventory");
    w.change(|s| s["inventory_barrier"] = true.into());
    let o = w.run(&["fleet", "due", "--github-only"]);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    assert_eq!(
        String::from_utf8(o.stdout).unwrap(),
        "fleet #9: candidate #10\n"
    );
    let mut released = fs::read_to_string(w.dir.join("inventory-released"))
        .unwrap()
        .lines()
        .map(str::to_owned)
        .collect::<Vec<_>>();
    released.sort();
    assert_eq!(released, ["issues", "prs", "repo"]);
    assert!(w.calls().iter().all(|(tool, _)| tool == "gh"));
    assert!(w.writes().is_empty());
}
#[test]
fn b5_review_r10_independent_pr_ci_reads_rendezvous_without_partial_authority() {
    let w = World::new("r10_ci");
    w.pr(10);
    w.pr(11);
    w.change(|s| s["ci_barrier"] = 2.into());
    let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(o.status.success());
    let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
    assert!(
        doc["actions"]
            .as_array()
            .unwrap()
            .iter()
            .all(|a| a["facts"]["reason"] != "records unread"),
        "{doc}"
    );
    let mut released = fs::read_to_string(w.dir.join("ci-released"))
        .unwrap()
        .lines()
        .map(str::to_owned)
        .collect::<Vec<_>>();
    released.sort();
    assert_eq!(released, [fake::HEAD10, fake::HEAD11]);
    assert_eq!(r3_calls(&w, "/actions/runs?"), 2);
    assert_eq!(r3_calls(&w, "/actions/runs/"), 2);
    assert!(w.writes().is_empty());
}

#[test]
fn b5_review_r12_deleted_closed_pr_head_does_not_erase_reviewer_history() {
    let w = r12_closed_review("r12_deleted_head");
    w.change(|s| {
        s["prs"][0]["head"] = "".into();
        s["prs"][0]["branch"] = "".into();
    });
    let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
    let a = doc["actions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|a| a["rule"] == "finished")
        .unwrap();
    assert_eq!(
        a["facts"]["threads"],
        json!([
            {"thread":"thr_syn_b5_1","role":"builder"},
            {"thread":"thr_syn_b5_2","role":"reviewer"}
        ]),
        "{doc}"
    );
}

#[test]
fn b5_review_r10_workflow_jobs_share_available_slots_without_retrying_failed_pages() {
    use openwiz_adapter_github::tick::{JOBS, RUNS};
    for count in [1, 2] {
        let w = World::new(&format!("r10_workflows_{count}"));
        w.change(|s| {
            for ticket in 10..10+count {
                let thread = format!("thr_syn_workflow_{ticket}");
                s["threads"][&thread] = json!({"provider":"claude-code","model":"claude-opus-5-5","effort":"high","archived":false,"prompt":"synthetic builder"});
                s["comments"][ticket.to_string()] = json!([{"id":1900+ticket,"created":1_793_400_010_000_u64,"updated":1_793_400_010_000_u64,"body":format!("launch-fleet: start checked, thread {thread}, branch synthetic-branch-{ticket}")}]);
            }
        });
        w.pr(10);
        if count == 2 {
            w.pr(11);
        }
        let key = |args: Value| serde_json::to_string(&json!(["gh", args])).unwrap();
        let job_path = |id: u64| {
            format!("repos/{{owner}}/{{repo}}/actions/runs/{id}/jobs?filter=latest&per_page=100")
        };
        w.change(|s| {
            for ticket in 10..10+count {
                let head = if ticket == 10 { fake::HEAD10 } else { fake::HEAD11 };
                let pr = ticket + 100;
                let runs = (1..=3).map(|n| json!({"id":pr*10+n,"head_sha":head,"event":"pull_request","run_attempt":1,"updated":n,"prs":[{"number":pr,"head":head,"base":fake::BASE}]})).collect::<Vec<_>>();
                s["overrides"][key(json!(["api",format!("repos/{{owner}}/{{repo}}/actions/runs?head_sha={head}&per_page=100"),"--paginate","--jq",RUNS]))] = json!([{"total_count":3,"runs":runs}]);
                for n in 1..=3 {
                    let run = pr*10+n;
                    let path = job_path(run);
                    s["overrides"][key(json!(["api",path,"--paginate","--jq",JOBS]))] = json!([{"total_count":1,"jobs":[{"id":run*10,"name":"rust","status":"completed","conclusion":"success","head_sha":head,"run_id":run}]}]);
                    let (group, arrivals) = if count == 1 { ("workflow-single",3) } else if n <= 2 { ("workflow-first",4) } else { ("workflow-last",2) };
                    s["workflow_barriers"][path] = json!({"group":group,"count":arrivals,"id":run});
                }
            }
        });
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        let actions = doc["actions"].as_array().unwrap();
        assert_eq!(actions.len(), count as usize, "{doc}");
        assert!(actions.iter().all(|a| a["rule"] == "first_review"), "{doc}");
        assert_eq!(
            fs::read_to_string(w.dir.join("workflow-peak")).unwrap(),
            if count == 1 { "3" } else { "4" }
        );
        assert_eq!(r3_calls(&w, "/actions/runs/"), (3 * count) as usize);
        let before = w.calls().len();
        w.change(|s| {
            s["overrides"][key(json!(["api", job_path(1101), "--paginate", "--jq", JOBS]))] =
                1.into()
        });
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success());
        let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
        assert!(
            doc["actions"]
                .as_array()
                .unwrap()
                .iter()
                .any(|a| a["ticket"] == 10 && a["rule"] == "look"),
            "{doc}"
        );
        let calls = w.calls();
        assert_eq!(
            calls[before..]
                .iter()
                .filter(|(_, a)| a.get(1) == Some(&job_path(1101)))
                .count(),
            1
        );
        assert!(
            !calls[before..]
                .iter()
                .any(|(_, a)| a.get(..3) == Some(&["pr".into(), "view".into(), "110".into()]))
        );
        assert!(w.writes().is_empty());
    }
}

#[test]
fn b5_review_r10_opt_in_planning_allowance_rounds_batches_without_changing_limits() {
    use openwiz_core::limits::{READ_TIMEOUT, RUN_BUDGET, fleet_tick_planning_allowance};
    use std::time::Duration;
    for (work, seconds) in [
        (0, 0),
        (1, 15),
        (4, 15),
        (5, 30),
        (8, 30),
        (9, 45),
        (65, 255),
    ] {
        assert_eq!(
            fleet_tick_planning_allowance(work),
            Duration::from_secs(seconds)
        );
    }
    let max_seconds = if usize::BITS > 32 {
        64_424_509_425
    } else {
        16_106_127_360
    };
    assert_eq!(
        fleet_tick_planning_allowance(usize::MAX),
        Duration::from_secs(max_seconds)
    );
    assert_eq!(RUN_BUDGET, Duration::from_secs(30));
    assert_eq!(READ_TIMEOUT, Duration::from_secs(15));
    assert_eq!(openwiz_core::fleet::tickets::MAX_CONCURRENT_READS, 4);
    assert_eq!(openwiz_core::limits::MAX_CONCURRENT_DETAIL_READS, 4);
}

#[test]
fn b5_review_r12_closed_and_replacement_reviewers_keep_global_start_order() {
    let w = r12_closed_review("r12_global_order");
    for entry in fs::read_dir(w.dir.join("state/starts")).unwrap() {
        let path = entry.unwrap().path();
        if path.extension().is_none_or(|e| e != "json") {
            continue;
        }
        let mut record: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        if record["key"]["role"] == "reviewer" {
            record["attempts"][0]["at"] = 1793400010000_u64.into();
            fs::write(path, serde_json::to_vec(&record).unwrap()).unwrap();
        }
    }
    w.change(|s| {
        s["threads"]["thr_syn_b5_30"] = s["threads"]["thr_syn_b5_2"].clone();
        let prompt = s["threads"]["thr_syn_b5_30"]["prompt"].as_str().unwrap().replace("pull request #110", "pull request #210");
        s["threads"]["thr_syn_b5_30"]["prompt"] = prompt.into();
        s["comments"]["210"] = json!([{"id":2001,"body":format!("launch-fleet: review started {}, thread thr_syn_b5_30",fake::HEAD10),"created":1793400020000_u64,"updated":1793400020000_u64}]);
    });
    let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(o.status.success());
    let doc: Value = serde_json::from_slice(&o.stdout).unwrap();
    let a = doc["actions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|a| a["rule"] == "finished")
        .unwrap();
    assert_eq!(
        a["facts"]["threads"],
        json!([
            {"thread":"thr_syn_b5_1","role":"builder"},
            {"thread":"thr_syn_b5_2","role":"reviewer"},
            {"thread":"thr_syn_b5_30","role":"reviewer"}
        ]),
        "{doc}"
    );
}

// synthetic_assumptions: five page responses each take 6.5 seconds. The
// aggregate exceeds both READ_TIMEOUT and RUN_BUDGET, with no wall-clock race.
#[test]
fn b5_review_r18_comment_pages_outlive_one_read_and_keep_execution_budget() {
    let w = World::new("r18_slow_comment_pages");
    w.change(|s| {
        let mut pages = (0..4)
            .map(|page| {
                (0..100)
                    .map(|offset| r3b_comment_row(9000, 10_000 + page * 100 + offset))
                    .collect::<Vec<_>>()
            })
            .collect::<Vec<_>>();
        let mut approval = s["comments"]["9"][0].clone();
        approval["issue_url"] = r3b_comment_row(9, 100)["issue_url"].clone();
        pages.push(vec![approval]);
        s["repository_comment_pages"] = json!(pages);
        // Real time: five pages of 6.5 s, 32.5 s in all, past one
        // READ_TIMEOUT and the 30 s RUN_BUDGET. The fast form (#1259) keeps
        // every assertion below on 50 ms pages; the timing itself is only
        // proven in full.
        s["repository_comment_delay_ms"] =
            json!(crate::real_time::pick("r18_slow_comment_pages", 6500, 50));
    });
    let output = w.run(&["fleet", "tick", "--json"]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let doc: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(doc["actions"][0]["outcome"]["state"], "done", "{doc}");
    assert_eq!(w.load()["spawn_count"], 1);
    let calls = w
        .calls()
        .into_iter()
        .filter(|(_, a)| a.get(1).is_some_and(|p| p.contains("/issues/comments?")))
        .collect::<Vec<_>>();
    assert_eq!(calls.len(), 5, "{calls:?}");
    for (index, (tool, args)) in calls.iter().enumerate() {
        assert_eq!(tool, "gh");
        assert_eq!(
            args,
            &vec![
                "api".to_owned(),
                format!(
                    "repos/{{owner}}/{{repo}}/issues/comments?per_page=100&page={}",
                    index + 1
                ),
                "--jq".into(),
                openwiz_adapter_github::tick::REPOSITORY_COMMENTS.into(),
            ]
        );
    }
    // The comment phase is sequential and completes before other planning jobs.
    assert_eq!(fs::read_to_string(w.dir.join("comment-peak")).unwrap(), "1");
}

#[test]
fn b5_review_r18_page_allowlist_is_exact() {
    use openwiz_adapter_github::{allowlist::Invocation, tick::REPOSITORY_COMMENTS};
    for page in ["1", "2", "47", "18446744073709551615"] {
        let path = format!("repos/{{owner}}/{{repo}}/issues/comments?per_page=100&page={page}");
        assert!(
            Invocation::new(&["api", &path, "--jq", REPOSITORY_COMMENTS]).is_some(),
            "{path}"
        );
        assert!(
            Invocation::new(&["api", &path, "--paginate", "--jq", REPOSITORY_COMMENTS]).is_none()
        );
    }
    for suffix in [
        "",
        "0",
        "01",
        "-1",
        "+1",
        "1x",
        "18446744073709551616",
        "1&extra=1",
        "%31",
    ] {
        let path = format!("repos/{{owner}}/{{repo}}/issues/comments?per_page=100&page={suffix}");
        assert!(
            Invocation::new(&["api", &path, "--jq", REPOSITORY_COMMENTS]).is_none(),
            "{path}"
        );
    }
    assert!(
        Invocation::new(&[
            "api",
            "repos/{owner}/{repo}/issues/comments?per_page=100",
            "--paginate",
            "--jq",
            REPOSITORY_COMMENTS
        ])
        .is_none()
    );
}

#[test]
fn b5_review_r18_first_short_page_stops_and_cross_page_duplicates_stay_unread() {
    use openwiz_adapter_github::tick::TickReads;
    use openwiz_core::fleet::model::Number;
    let w = World::new("r18_short_page");
    let first = (1000..1100)
        .map(|id| r3b_comment_row(9, id))
        .collect::<Vec<_>>();
    w.change(|s| s["repository_comment_pages"] = json!([first, [], [r3b_comment_row(9, 2000)]]));
    let reader = TickReads::new(w.dir.join("bin/gh"));
    let deadline = || std::time::Instant::now() + std::time::Duration::from_secs(5);
    let repo = reader.repository(deadline()).unwrap();
    let snapshot = reader.repository_comments(&repo, deadline()).unwrap();
    assert_eq!(snapshot.comments[&Number::new(9).unwrap()].len(), 100);
    assert_eq!(r3_calls(&w, "/issues/comments?"), 2);
    w.change(|s| s["repository_comment_pages"] = json!([first, [r3b_comment_row(110, 1000)]]));
    let snapshot = reader.repository_comments(&repo, deadline()).unwrap();
    assert_eq!(
        snapshot.unread,
        [Number::new(9).unwrap(), Number::new(110).unwrap()].into()
    );
    assert!(snapshot.comments.is_empty());
}

#[test]
fn b5_review_r18_missing_or_failed_page_withholds_the_whole_snapshot() {
    for (index, answer) in [
        None,
        Some(json!({"fake_exit":1,"fake_stdout":"[]"})),
        Some(json!("")),
        Some(json!({})),
        Some(json!("[] []")),
        Some(json!("[{\"id\":1,\"id\":2}]")),
        Some(json!(
            (1000..1101)
                .map(|id| r3b_comment_row(9, id))
                .collect::<Vec<_>>()
        )),
    ]
    .into_iter()
    .enumerate()
    {
        let w = World::new(&format!("r18_bad_page_{index}"));
        w.change(|s| {
            let mut first = vec![s["comments"]["9"][0].clone()];
            first[0]["issue_url"] = r3b_comment_row(9, 100)["issue_url"].clone();
            first.extend((10_000..10_099).map(|id| r3b_comment_row(9000, id)));
            s["repository_comment_pages"] = json!([first]);
            if let Some(answer) = answer {
                s["overrides"][r3b_comments_page_key(2)] = answer;
            }
        });
        let out = w.run(&["fleet", "due", "--github-only"]);
        assert_eq!(
            out.status.code(),
            Some(1),
            "case {index}: {}",
            String::from_utf8_lossy(&out.stdout)
        );
        assert!(out.stdout.is_empty());
        assert_eq!(r3_calls(&w, "/issues/comments?"), 2);
        assert!(w.writes().is_empty());
        assert!(w.calls().iter().all(|(tool, _)| tool == "gh"));
        assert!(!w.dir.join("state").exists());
    }
}

#[test]
fn b5_review_r18_exhausted_page_budget_exposes_no_partial_snapshot() {
    use openwiz_adapter_github::tick::TickReads;
    let w = World::new("r18_page_budget");
    w.change(|s| {
        s["repository_comment_pages"] = json!([
            (1000..1100)
                .map(|id| r3b_comment_row(9, id))
                .collect::<Vec<_>>(),
            []
        ]);
    });
    let reader = TickReads::new(w.dir.join("bin/gh"));
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    let repo = reader.repository(deadline).unwrap();
    let mut requested = Vec::new();
    let result = reader.repository_comments_with_page_deadline(&repo, |page| {
        requested.push(page);
        if page == 1 {
            Ok(deadline)
        } else {
            Err("synthetic planning budget exhausted")
        }
    });
    assert_eq!(result.err(), Some("synthetic planning budget exhausted"));
    assert_eq!(requested, vec![1, 2]);
    assert_eq!(r3_calls(&w, "/issues/comments?"), 1);
}

// X2: active worlds share a fake process, but never state or teardown.
#[test]
fn x2_shared_fake_keeps_worlds_independent_when_a_world_is_dropped() {
    let first = World::new("x2-shared-first");
    let second = World::new("x2-shared-second");
    assert_eq!(first.tick()["actions"][0]["outcome"]["state"], "done");
    assert_eq!(second.load()["spawn_count"], 0);
    assert_eq!(second.tick()["actions"][0]["outcome"]["state"], "done");
    assert_eq!(first.load()["spawn_count"], 1);
    assert_eq!(second.load()["spawn_count"], 1);
    drop(first);
    second.pr(10);
    let review = second.tick();
    assert_eq!(review["actions"][0]["rule"], "first_review", "{review}");
    assert_eq!(review["actions"][0]["outcome"]["state"], "done");
    assert_eq!(second.load()["spawn_count"], 2);
}

// R2: a killed fixture client must stop its delayed work, not merely hide its
// answer. A second arrival would let a surviving worker write its release.
#[test]
fn x2_killing_a_client_cancels_its_worker_without_stopping_other_worlds() {
    use std::process::{Child, Command, Stdio};
    use std::time::{Duration, Instant};
    struct Reap(Child);
    impl Drop for Reap {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    let w = World::new("x2-client-cancellation");
    let other = World::new("x2-client-cancellation-other");
    let args = |id| vec!["api".to_owned(), format!("synthetic/jobs/{id}")];
    w.change(|s| {
        for id in [1, 2] {
            let argv = args(id);
            s["overrides"][serde_json::to_string(&json!(["gh", argv])).unwrap()] = json!([[]]);
            s["workflow_barriers"][&argv[1]] = json!({"group":"client-death","count":2,"id":id});
        }
    });
    let program = w.dir.join("bin/gh");
    let mut client = Reap(
        Command::new(&program)
            .args(args(1))
            .stdout(Stdio::null())
            .spawn()
            .unwrap(),
    );
    let active = w.dir.join(format!("workflow-active-{}", client.0.id()));
    let until = Instant::now() + Duration::from_secs(5);
    while !w.dir.join("client-death-arrival-1").exists() {
        assert!(Instant::now() < until, "delayed worker never arrived");
        std::thread::park_timeout(Duration::from_millis(1));
    }
    assert!(active.exists(), "the killed client's work started");
    client.0.kill().unwrap();
    client.0.wait().unwrap();
    let live = Command::new(program).args(args(2)).output().unwrap();
    assert!(live.status.success(), "{live:?}");
    assert_eq!(live.stdout, b"[]\n");
    w.settle(); // Read-only acknowledgement, never cancellation or teardown.
    assert_eq!(
        fs::read_to_string(w.dir.join("client-death-released")).unwrap(),
        "2\n",
        "the dead client's delayed work must never release"
    );
    assert!(
        active.exists(),
        "the dead worker must not finish its cleanup"
    );
    assert_eq!(other.tick()["actions"][0]["outcome"]["state"], "done");
    assert_eq!(other.load()["spawn_count"], 1);
}
