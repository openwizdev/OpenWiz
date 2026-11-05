//! B5 CLI proofs. Every value and external response is synthetic.
use std::fs;
use std::process::Command;

use serde_json::json;

#[test]
fn b5_due_empty_repository_is_silent_and_never_reads_cloudroom() {
    let (dir, path) = crate::support::fakes_on_path("b5_due_empty");
    let scenario = dir.join("scenario.json");
    fs::write(&scenario, serde_json::to_vec(&json!({
        "synthetic_assumptions": ["An empty synthetic repository, no fleet or CloudRoom read"],
        "responses": [
            {"argv": ["repo", "view", "--json", "defaultBranchRef,nameWithOwner,url"],
             "stdout": "{\"defaultBranchRef\":{\"name\":\"main\"},\"nameWithOwner\":\"synthetic/example\",\"url\":\"https://example.invalid/synthetic/example\"}"},
            {"argv": ["issue", "list", "--state", "all", "--limit", "1000", "--json", "blockedBy,body,id,labels,milestone,number,state,subIssues,title"], "stdout": "[]"},
            {"argv": ["pr", "list", "--state", "all", "--limit", "1000", "--json", "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state,title"], "stdout": "[]"}
        ]
    })).unwrap()).unwrap();
    fs::write(dir.join("fake-gh.scenario"), scenario.to_str().unwrap()).unwrap();
    let out = Command::new(crate::support::openwiz_release())
        .args(["fleet", "due", "--github-only"])
        .current_dir(&dir)
        .env("PATH", path)
        .env("OPENWIZ_STATE_DIR", dir.join("absent-state"))
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(out.stdout.is_empty());
    assert!(out.stderr.is_empty());
    assert!(!dir.join("absent-state").exists());
    assert!(!dir.join("room-invocations.log").exists());
    assert!(!dir.join("invocations.log").exists());
    let calls = fs::read_to_string(dir.join("gh-invocations.log")).unwrap();
    assert_eq!(calls.lines().count(), 3, "{calls}");
}

#[path = "b5_fake.rs"]
mod fake;

#[path = "b5_public.rs"]
mod public;

// Preserve the pre-cut-over fixtures explicitly now that the writer is public.
fn legacy_records(w: &fake::World) {
    w.change(|s| {
        for cs in s["comments"].as_object_mut().unwrap().values_mut() {
            for c in cs.as_array_mut().unwrap() {
                let body = c["body"].as_str().unwrap().to_owned();
                c["body"] = if body == "launch-fleet: started" {
                    "launch-fleet: started, thread thr_syn_b5_1".to_owned()
                } else if body.starts_with("launch-fleet: start checked, branch ") {
                    body.replace(
                        "start checked, branch ",
                        "start checked, thread thr_syn_b5_1, branch ",
                    )
                } else if body.starts_with("launch-fleet: review started ")
                    && !body.contains(", thread ")
                {
                    format!("{body}, thread thr_syn_b5_2")
                } else if body.starts_with("launch-fleet: builder fallback due, branch ") {
                    body.replace(
                        "builder fallback due, branch ",
                        "builder fallback due, thread thr_syn_b5_1, branch ",
                    )
                } else {
                    body
                }
                .into();
            }
        }
    });
}

#[test]
fn b5_synthetic_fleet_reaches_last_merge_without_duplicate_builders() {
    let w = fake::World::new("lifecycle");
    let dry = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(
        dry.status.success(),
        "{}",
        String::from_utf8_lossy(&dry.stderr)
    );
    let dry: serde_json::Value = serde_json::from_slice(&dry.stdout).unwrap();
    assert_eq!(dry["actions"][0]["rule"], "frontier", "{dry}");
    assert_eq!(dry["actions"].as_array().unwrap().len(), 1);
    assert!(w.writes().is_empty());
    assert!(!w.dir.join("state").exists());
    for ticket in [10, 11] {
        let start = w.tick();
        if ticket == 10 {
            assert_eq!(start["actions"][0]["outcome"]["state"], "done", "{start}");
        }
        let count = w.load()["spawn_count"].as_u64().unwrap();
        w.tick();
        assert_eq!(w.load()["spawn_count"], count);
        w.pr(ticket);
        let review = w.tick();
        assert_eq!(review["actions"][0]["rule"], "first_review", "{review}");
        assert_eq!(review["actions"][0]["outcome"]["state"], "done", "{review}");
        w.approve(ticket);
        let merge = w.tick();
        assert_eq!(merge["actions"][0]["rule"], "adr_0008", "{merge}");
        assert_eq!(merge["actions"][0]["outcome"]["state"], "done", "{merge}");
        // Closed by the fake's merge, as GitHub does. Archive occurs next tick.
        // The next ticket is also ready, so this dry run must not spawn it.
        let o = w.run(&["fleet", "tick", "--dry-run", "--json"]);
        assert!(o.status.success());
        if ticket == 10 {
            // First archive plus next builder start happen in one subsequent tick.
            let next = w.tick();
            assert!(
                next["actions"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .any(|a| a["rule"] == "finished"),
                "{next}"
            );
        }
    }
    let final_tick = w.tick();
    assert!(
        final_tick["actions"]
            .as_array()
            .unwrap()
            .iter()
            .any(|a| a["rule"] == "finished"),
        "{final_tick}"
    );
    let s = w.load();
    assert_eq!(s["spawn_count"], 4, "{s}");
    assert!(
        s["threads"]
            .as_object()
            .unwrap()
            .values()
            .all(|t| t["archived"] == true)
    );
    assert_eq!(s["merge_bodies"].as_array().unwrap().len(), 2);
    for body in s["merge_bodies"].as_array().unwrap() {
        let b = body.as_str().unwrap();
        assert!(b.contains("ADR 0008: approval revision 1 (comment 100), APPROVE (comment "));
    }
    let writes = w.writes();
    assert_eq!(writes.len(), 18, "{writes:?}");
    for (tool, kind, count) in [
        ("room-cli", "spawn", 4),
        ("room-cli", "archive", 4),
        ("gh", "merge", 2),
        ("gh", "comment", 8),
    ] {
        assert_eq!(
            writes
                .iter()
                .filter(|(t, a)| t == tool && a.get(1).is_some_and(|k| k == kind))
                .count(),
            count,
            "{writes:?}"
        );
    }
    let spawns = writes
        .iter()
        .filter(|(t, a)| t == "room-cli" && a[1] == "spawn")
        .collect::<Vec<_>>();
    let mut request_ids = std::collections::BTreeSet::new();
    for ((_, argv), (role, number, thread)) in spawns.iter().zip([
        ("builder", 10, "thr_syn_b5_1"),
        ("reviewer", 110, "thr_syn_b5_2"),
        ("builder", 11, "thr_syn_b5_3"),
        ("reviewer", 111, "thr_syn_b5_4"),
    ]) {
        assert_eq!(argv.len(), 17, "{argv:?}");
        let head = if number == 110 {
            fake::HEAD10
        } else {
            fake::HEAD11
        };
        let brief = if role == "builder" {
            format!(
                "You are the builder for #{number}. Read skills/build-ticket/SKILL.md and follow it."
            )
        } else {
            format!(
                "You are the reviewer for pull request #{number} at {head}. Read skills/review-ticket/SKILL.md and follow it."
            )
        };
        let provider = if role == "builder" {
            "claude-code"
        } else {
            "codex"
        };
        let model = if role == "builder" {
            "claude-opus-5-5"
        } else {
            "gpt-6.1-sol"
        };
        let effort = if role == "builder" { "xhigh" } else { "high" };
        assert_eq!(
            &argv[..12],
            [
                "thread",
                "spawn",
                "--project",
                "prj_syn_0001",
                "--machine",
                "cloud",
                "--provider",
                provider,
                "--model",
                model,
                "--reasoning-level",
                effort
            ]
        );
        assert_eq!(argv[12], "--request-id");
        assert!(
            argv[13].starts_with("ow1-")
                && argv[13].len() == 44
                && argv[13][4..].bytes().all(|b| b.is_ascii_hexdigit())
        );
        assert!(request_ids.insert(argv[13].clone()));
        assert_eq!(&argv[14..], ["--json", "--prompt", &brief]);
        assert!(
            writes
                .iter()
                .any(|(t, a)| t == "room-cli" && a == &["thread", "archive", thread, "--json"])
        );
    }
    for (tool, args) in w.calls() {
        if tool == "gh" {
            let a = args.iter().map(String::as_str).collect::<Vec<_>>();
            assert!(
                openwiz_adapter_github::allowlist::Invocation::new(&a).is_some(),
                "{args:?}"
            );
        }
    }
}

#[test]
fn b5_due_running_builder_is_idle_without_cloudroom_or_state() {
    let w = fake::World::new("due_running");
    w.tick();
    legacy_records(&w);
    let before = w.calls().len();
    let o = w.run(&["fleet", "due", "--github-only"]);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    assert!(
        o.stdout.is_empty(),
        "{}",
        String::from_utf8_lossy(&o.stdout)
    );
    assert!(w.calls()[before..].iter().all(|(t, _)| t == "gh"));
}

#[test]
fn b5_merge_requires_every_observed_gate_including_real_success() {
    let cases = [
        "stale_plan",
        "no_approval",
        "base_moved",
        "ci_failed",
        "ci_skipped",
        "release",
        "draft",
        "own_output_differs",
        "malformed_report",
        "duplicate_report",
    ];
    // Each gate has its own world, so they run at once (#1259).
    crate::at_once::at_once(&cases, 4, |&case| {
        let w = fake::World::new(&format!("gate_{case}"));
        w.tick();
        w.pr(10);
        w.tick();
        w.approve(10);
        w.change(|s| match case {
            "stale_plan" => s["issues"][1]["title"] = "Changed synthetic ticket".into(),
            "no_approval" => s["comments"]["9"] = json!([]),
            "base_moved" => s["base"] = "cccccccccccccccccccccccccccccccccccccccc".into(),
            "ci_failed" => s["prs"][0]["ci"] = "failure".into(),
            "ci_skipped" => s["prs"][0]["ci"] = "skipped".into(),
            "release" => s["prs"][0]["branch"] = "release-synthetic".into(),
            "draft" => s["prs"][0]["draft"] = true.into(),

            "own_output_differs" => {
                s["prs"][0]["report"] =
                    "VERDICT: APPROVE at cccccccccccccccccccccccccccccccccccccccc".into()
            }
            "malformed_report" => {
                s["comments"]["110"]
                    .as_array_mut()
                    .unwrap()
                    .last_mut()
                    .unwrap()["body"] = "VERDICT:APPROVE".into()
            }
            "duplicate_report" => {
                let c = s["comments"]["110"]
                    .as_array()
                    .unwrap()
                    .last()
                    .unwrap()
                    .clone();
                s["comments"]["110"].as_array_mut().unwrap().push(c);
            }
            _ => unreachable!(),
        });
        w.tick();
        assert_eq!(
            w.load()["merge_bodies"].as_array().unwrap().len(),
            0,
            "{case}"
        );
    });
}

#[test]
fn b5_pre_merge_base_recheck_refuses_a_move_after_authority_refresh() {
    let w = fake::World::new("pre_merge_base_recheck");
    w.tick();
    w.pr(10);
    w.tick();
    w.approve(10);
    // Planning and the authority refresh each read the rules' base and the
    // PR's base. Move it after those four reads, before the final write check.
    w.change(|s| s["move_base_after_reads"] = 4.into());
    let doc = w.tick();
    assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{doc}");
    assert_eq!(doc["actions"][0]["kind"], "merge", "{doc}");
    assert_eq!(
        doc["actions"][0]["outcome"],
        json!({"state":"refused", "reason":"base moved since CI"}),
        "{doc}"
    );
    assert_eq!(w.load()["move_base_after_reads"], 0);
    assert_eq!(w.load()["base"], "cccccccccccccccccccccccccccccccccccccccc");
    assert_eq!(w.load()["prs"][0]["merged"], false);
    assert_eq!(w.load()["merge_bodies"], json!([]));
    assert!(w.writes().iter().all(|(_, a)| a[1] != "merge"));

    w.change(|s| s["base"] = fake::BASE.into());
    let retry = w.tick();
    assert_eq!(retry["actions"][0]["outcome"]["state"], "done", "{retry}");
    assert_eq!(w.load()["prs"][0]["merged"], true);
    assert_eq!(
        w.writes().iter().filter(|(_, a)| a[1] == "merge").count(),
        1
    );
    assert_eq!(w.load()["merge_bodies"].as_array().unwrap().len(), 1);
}

#[test]
fn b5_pre_merge_authority_recheck_refuses_a_revoked_plan_approval() {
    let w = fake::World::new("pre_merge_authority_recheck");
    w.tick();
    w.pr(10);
    w.tick();
    w.approve(10);
    w.change(|s| s["revoke_approval_after_comments"] = true.into());
    let doc = w.tick();
    assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{doc}");
    assert_eq!(doc["actions"][0]["kind"], "merge", "{doc}");
    assert_eq!(
        doc["actions"][0]["outcome"],
        json!({"state":"refused", "reason":"action authority changed or unread"}),
        "{doc}"
    );
    assert_eq!(w.load()["revoke_approval_after_comments"], false);
    assert_eq!(w.load()["comments"]["9"], json!([]));
    assert_eq!(w.load()["prs"][0]["merged"], false);
    assert_eq!(w.load()["merge_bodies"], json!([]));
    assert!(w.writes().iter().all(|(_, a)| a[1] != "merge"));

    w.change(|s| {
        s["comments"]["9"] = json!([{
            "id":100,"body":fake::APPROVAL,"created":1793400000000_u64,"updated":1793400000000_u64
        }])
    });
    let retry = w.tick();
    assert_eq!(retry["actions"][0]["outcome"]["state"], "done", "{retry}");
    assert_eq!(w.load()["prs"][0]["merged"], true);
    assert_eq!(
        w.writes().iter().filter(|(_, a)| a[1] == "merge").count(),
        1
    );
    assert_eq!(w.load()["merge_bodies"].as_array().unwrap().len(), 1);
}

#[test]
fn b5_crash_after_dispatch_never_repeats_an_uncertain_start() {
    use std::os::unix::process::ExitStatusExt;
    let w = fake::World::new("crash_dispatch");
    w.change(|s| s["crash"] = "after-spawn".into());
    let o = w.run(&["fleet", "tick", "--json"]);
    assert_eq!(o.status.signal(), Some(9));
    w.change(|s| s["crash"] = "".into());
    for _ in 0..2 {
        let doc = w.tick();
        assert!(
            doc["actions"]
                .as_array()
                .unwrap()
                .iter()
                .any(|a| a["rule"] == "look"),
            "{doc}"
        );
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

#[test]
fn b5_pending_created_start_is_recovered_without_a_second_builder() {
    let w = fake::World::new("pending_created");
    w.tick();
    let dir = w.dir.join("state/starts");
    let file = fs::read_dir(&dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .find(|p| p.extension().is_some_and(|e| e == "json"))
        .unwrap();
    let mut r: serde_json::Value = serde_json::from_slice(&fs::read(&file).unwrap()).unwrap();
    r["attempts"][0]["outcome"] = json!({"kind":"pending"});
    fs::write(file, serde_json::to_vec(&r).unwrap()).unwrap();
    w.change(|s| s["comments"]["10"] = json!([]));
    w.tick();
    w.tick();
    assert_eq!(w.load()["spawn_count"], 1);
    assert_eq!(
        w.load()["comments"]["10"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|c| c["body"].as_str().unwrap().eq("launch-fleet: started"))
            .count(),
        1
    );
}

#[test]
fn b5_plain_tick_names_a_failed_recovery_outcome_without_repeating_it() {
    // #516/R1: a recovery action whose GitHub write fails must be visible in
    // plain output, without reexecuting it or duplicating a confirmed start.
    let w = fake::World::new("plain_recovery_failed");
    w.tick();
    let dir = w.dir.join("state/starts");
    let file = fs::read_dir(&dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .find(|p| p.extension().is_some_and(|e| e == "json"))
        .unwrap();
    let mut r: serde_json::Value = serde_json::from_slice(&fs::read(&file).unwrap()).unwrap();
    r["attempts"][0]["outcome"] = json!({"kind":"pending"});
    fs::write(file, serde_json::to_vec(&r).unwrap()).unwrap();
    w.change(|s| {
        s["comments"]["10"] = json!([]);
        s["fail_record"] = "launch-fleet: started".into();
    });
    let out = w.run(&["fleet", "tick"]);
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let lines = String::from_utf8(out.stdout).unwrap();
    assert_eq!(
        lines, "fleet #9: #10 frontier uncertain: GitHub write not confirmed\n",
        "{lines:?}"
    );
    // The start is reconciled, never repeated, and no record is written.
    assert_eq!(w.load()["spawn_count"], 1);
    assert_eq!(
        w.calls()
            .iter()
            .filter(|(t, a)| t == "room-cli" && a.get(1).is_some_and(|s| s == "spawn"))
            .count(),
        1
    );
    assert!(
        w.load()["comments"]["10"]
            .as_array()
            .is_none_or(|cs| cs.is_empty()),
        "{:?}",
        w.load()["comments"]["10"]
    );
}

#[test]
fn b5_concurrent_ticks_share_one_builder_start() {
    let w = fake::World::new("concurrent");
    let a = w
        .command(&["fleet", "tick", "--json"])
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    let b = w
        .command(&["fleet", "tick", "--json"])
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    assert!(a.wait_with_output().unwrap().status.success());
    assert!(b.wait_with_output().unwrap().status.success());
    assert_eq!(w.load()["spawn_count"], 1);
}

#[test]
fn b5_missing_orchestrator_leaves_notification_due_and_no_completion_record() {
    let w = fake::World::new("missing_orchestrator");
    w.change(|s| {
        s["issues"][1]["labels"] = json!(["ready-for-human"]);
        s["comments"]["9"][0]["body"] = fake::APPROVAL
            .replace(
                "#10 | Synthetic ticket 10 | none | ready-for-agent",
                "#10 | Synthetic ticket 10 | none | ready-for-human",
            )
            .into();
    });
    for _ in 0..2 {
        let doc = w.tick();
        let a = &doc["actions"][0];
        assert_eq!(a["rule"], "person_ready", "{doc}");
        assert_eq!(a["outcome"]["state"], "failed", "{doc}");
    }
    assert!(w.writes().is_empty());
    assert!(!w.load()["comments"]["10"].as_array().is_some_and(|cs| {
        cs.iter()
            .any(|c| c["body"] == "launch-fleet: told the user")
    }));
}

#[test]
fn b5_plain_tick_names_a_failed_action_and_stays_silent_on_success() {
    // #516/R5: without --json, an action that did not end `done` must be
    // visible; a mechanical success stays silent.
    let w = fake::World::new("plain_failed");
    w.change(|s| {
        s["issues"][1]["labels"] = json!(["ready-for-human"]);
        s["comments"]["9"][0]["body"] = fake::APPROVAL
            .replace(
                "#10 | Synthetic ticket 10 | none | ready-for-agent",
                "#10 | Synthetic ticket 10 | none | ready-for-human",
            )
            .into();
    });
    let out = w.run(&["fleet", "tick"]);
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let lines = String::from_utf8(out.stdout).unwrap();
    assert_eq!(
        lines, "fleet #9: #10 person_ready failed: orchestrator thread missing or invalid\n",
        "{lines:?}"
    );
    assert!(w.writes().is_empty());

    // The same action with a destination succeeds and prints its judgment line.
    w.change(|s| {
        s["threads"]["thr_syn_orchestrator"] =
            json!({"provider":"codex","model":"gpt-6.1-sol","effort":"high","archived":false,"prompt":"Synthetic orchestrator"});
    });
    let out = w
        .command(&["fleet", "tick"])
        .env("OPENWIZ_ORCHESTRATOR_THREAD_ID", "thr_syn_orchestrator")
        .output()
        .unwrap();
    assert!(out.status.success());
    let lines = String::from_utf8(out.stdout).unwrap();
    assert_eq!(lines, "fleet #9: #10 person_ready\n", "{lines:?}");
    assert_eq!(w.load()["comments"]["10"].as_array().unwrap().len(), 1);
}

#[test]
fn b5_plain_tick_names_a_refused_or_uncertain_action() {
    // A refused merge prints one diagnostic line, unlike the previous silent
    // tick, and does not merge.
    let w = fake::World::new("plain_refused");
    w.tick();
    w.pr(10);
    w.tick();
    w.approve(10);
    w.change(|s| s["revoke_approval_after_comments"] = true.into());
    let out = w.run(&["fleet", "tick"]);
    assert!(out.status.success());
    let lines = String::from_utf8(out.stdout).unwrap();
    assert_eq!(
        lines, "fleet #9: #10 adr_0008 refused: action authority changed or unread\n",
        "{lines:?}"
    );
    assert_eq!(w.load()["prs"][0]["merged"], false);
    assert!(w.writes().iter().all(|(_, a)| a[1] != "merge"));
}

#[test]
fn b5_additional_readers_and_allowlist_refuse_shape_drift() {
    use openwiz_adapter_github::tick::{comments, document, repository};
    for raw in [r#"{"a":1,"a":2}"#, r#"{"a":{"x":1,"x":2}}"#, r#"{"a":1.0}"#] {
        assert!(document(raw.as_bytes()).is_err(), "{raw}");
    }
    let good = json!({"defaultBranchRef":{"name":"main"},"nameWithOwner":"synthetic/example","url":"https://example.invalid"});
    assert!(repository(&good).is_ok());
    for bad in [
        json!(["main", "synthetic/example", "url"]),
        json!({"defaultBranchRef":{"name":"main","extra":true},"nameWithOwner":"synthetic/example","url":"u"}),
        json!({"defaultBranchRef":{"name":"-bad"},"nameWithOwner":"synthetic/example","url":"u"}),
        json!({"defaultBranchRef":null,"nameWithOwner":"synthetic/example","url":"u"}),
    ] {
        assert!(repository(&bad).is_err(), "{bad}");
    }
    let row = json!({"id":1,"body":"Synthetic","created":100,"updated":100});
    assert!(comments(&json!([[row.clone()]])).is_ok());
    for bad in [
        json!([row.clone()]),
        json!([[row.clone(), row.clone()]]),
        json!([[{"id":1,"body":"Synthetic","created":100,"updated":99}]]),
        json!([[{"id":"1","body":"Synthetic","created":100,"updated":100}]]),
        json!([[{"id":1,"body":[],"created":100,"updated":100}]]),
    ] {
        assert!(comments(&bad).is_err(), "{bad}");
    }
    for argv in [
        vec![
            "api",
            "repos/{owner}/{repo}/issues/+1/comments?per_page=100",
            "--paginate",
            "--slurp",
            "--jq",
            openwiz_adapter_github::tick::COMMENTS,
        ],
        vec![
            "api",
            "repos/foreign/repo/git/ref/heads/main",
            "--jq",
            openwiz_adapter_github::tick::REF,
        ],
        vec![
            "api",
            "repos/{owner}/{repo}/git/ref/heads/main?x=y",
            "--jq",
            openwiz_adapter_github::tick::REF,
        ],
    ] {
        assert!(
            openwiz_adapter_github::allowlist::Invocation::new(&argv).is_none(),
            "{argv:?}"
        );
    }
}

#[path = "b5_edges.rs"]
mod edges;

// #1196: assertions use the actual spawn boundary, with synthetic providers.
fn conditional_rules(w: &fake::World) {
    assert!(
        w.load()["rules"]
            .as_str()
            .unwrap()
            .contains("## Builder for small tickets")
    );
}

#[test]
fn b5_1196_small_ticket_uses_small_builder() {
    for label in ["polish", "huntr", "proposal"] {
        let w = fake::World::new(&format!("1196-class-{label}"));
        conditional_rules(&w);
        w.change(|s| {
            s["issues"][1]["labels"]
                .as_array_mut()
                .unwrap()
                .push(label.into())
        });
        let doc = w.tick();
        assert_eq!(doc["actions"][0]["outcome"]["state"], "done", "{doc}");
        assert_eq!(
            w.load()["threads"]["thr_syn_b5_1"]["provider"],
            "codex",
            "{label}"
        );
    }
}

fn checked_builder(w: &fake::World, branch: &str) {
    w.change(|s| {
        s["comments"]["10"].as_array_mut().unwrap().push(json!({
            "id": 1900, "created": 1_793_400_010_000_u64, "updated": 1_793_400_010_000_u64,
            "body": format!("launch-fleet: start checked, thread thr_syn_b5_1, branch {branch}")
        }));
    });
}

#[test]
fn b5_1196_reviews_follow_the_recorded_builder_family() {
    for (provider, model, expected) in [
        ("claude-code", "claude-opus-5-5", "codex"),
        ("codex", "gpt-6.1-sol", "claude-code"),
    ] {
        let w = fake::World::new(&format!("1196-family-{provider}"));
        conditional_rules(&w);
        w.change(|s| {
            s["rules"] = s["rules"]
                .as_str()
                .unwrap()
                .replacen(
                    "--provider claude-code",
                    &format!("--provider {provider}"),
                    1,
                )
                .replacen("--model claude-opus-5-5", &format!("--model {model}"), 1)
                .into();
        });
        w.tick();
        w.pr(10);
        checked_builder(&w, "synthetic-branch-10");
        // Today's default changes after the builder started; its provider still wins.
        w.change(|s| {
            let current = s["rules"].as_str().unwrap();
            s["rules"] = current
                .replacen(
                    &format!("--provider {provider}"),
                    if provider == "codex" {
                        "--provider claude-code"
                    } else {
                        "--provider codex"
                    },
                    1,
                )
                .into();
        });
        let doc = w.tick();
        assert_eq!(doc["actions"][0]["rule"], "first_review", "{doc}");
        assert_eq!(doc["actions"][0]["outcome"]["state"], "done", "{doc}");
        assert_eq!(w.load()["threads"]["thr_syn_b5_2"]["provider"], expected);
    }
}

#[test]
fn b5_1196_unknown_builder_family_refuses_a_reviewer() {
    for branch in [None, Some("wrong-branch")] {
        let w = fake::World::new(&format!("1196-unknown-{branch:?}"));
        conditional_rules(&w);
        w.tick();
        w.pr(10);
        w.change(|s| {
            s["comments"]["10"].as_array_mut().unwrap().retain(|c| {
                !c["body"]
                    .as_str()
                    .unwrap()
                    .starts_with("launch-fleet: start checked,")
            })
        });
        if let Some(branch) = branch {
            checked_builder(&w, branch);
        }
        let before = w.load()["spawn_count"].clone();
        let doc = w.tick();
        assert_eq!(w.load()["spawn_count"], before, "{doc}");
        assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{doc}");
        assert_eq!(doc["actions"][0]["rule"], "look", "{doc}");
    }
}

#[test]
fn b5_1196_claude_limit_prints_one_restart_and_keeps_the_branch() {
    let w = fake::World::new("1196-limit");
    conditional_rules(&w);
    w.tick();
    checked_builder(&w, "synthetic-branch-10");
    w.change(|s| s["threads"]["thr_syn_b5_1"]["output"] = "Claude usage limit reached".into());
    let before = w.load()["spawn_count"].clone();
    let out = w.run(&["fleet", "tick"]);
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let lines = String::from_utf8(out.stdout).unwrap();
    assert_eq!(lines.lines().count(), 1, "{lines}");
    assert!(lines.contains("restart"), "{lines}");
    assert!(lines.contains("synthetic-branch-10"), "{lines}");
    assert_eq!(w.load()["spawn_count"], before);
    let again = w.run(&["fleet", "tick"]);
    assert!(again.status.success());
    assert!(
        again.stdout.is_empty(),
        "{}",
        String::from_utf8_lossy(&again.stdout)
    );
}

#[test]
fn b5_1330_claude_fallback_is_refused_without_consuming_the_restart() {
    let w = fake::World::new("1330-limited-family");
    w.tick();
    checked_builder(&w, "synthetic-branch-10");
    let codex_rules = w.load()["rules"].as_str().unwrap().to_owned();
    w.change(|s| {
        s["threads"]["thr_syn_b5_1"]["output"] = "Claude usage limit reached".into();
        let (before, tail) = codex_rules
            .split_once("## Builder for small tickets")
            .unwrap();
        let (small, after) = tail.split_once("## Reviewer for Claude-built").unwrap();
        let small = small
            .replace("--provider codex", "--provider claude-code")
            .replace("--model gpt-6.1-sol", "--model claude-opus-5-5");
        s["rules"] = format!(
            "{before}## Builder for small tickets{small}## Reviewer for Claude-built{after}"
        )
        .into();
    });
    let writes = w.writes();
    let dry = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(dry.status.success());
    let doc: serde_json::Value = serde_json::from_slice(&dry.stdout).unwrap();
    assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{doc}");
    assert_eq!(doc["actions"][0]["rule"], "look", "{doc}");
    assert_eq!(
        doc["actions"][0]["facts"]["reason"],
        "fallback builder is the limited family"
    );
    assert_eq!(w.writes(), writes, "dry run must write nothing");
    let out = w.run(&["fleet", "tick"]);
    assert!(out.status.success());
    let lines = String::from_utf8(out.stdout).unwrap();
    assert_eq!(lines.lines().count(), 1, "{lines}");
    assert!(
        lines.contains("look: fallback builder is the limited family"),
        "{lines}"
    );
    assert_eq!(w.writes(), writes, "refusal must save no fallback record");
    assert_eq!(w.load()["spawn_count"], 1);

    // Refusing the limited family leaves the one allowed fallback available.
    w.change(|s| s["rules"] = codex_rules.into());
    let doc = w.tick();
    assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{doc}");
    assert_eq!(doc["actions"][0]["rule"], "restart", "{doc}");
    assert_eq!(doc["actions"][0]["facts"]["branch"], "synthetic-branch-10");
    assert_eq!(
        doc["actions"][0]["facts"]["settings"],
        json!({"harness":"codex","model":"gpt-6.1-sol","effort":"high"})
    );
    assert_eq!(w.load()["spawn_count"], 1);
    let records = w.load()["comments"]["10"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| {
            c["body"]
                .as_str()
                .unwrap()
                .starts_with("launch-fleet: builder fallback due,")
        })
        .count();
    assert_eq!(records, 1);
    let writes = w.writes();
    assert!(w.tick()["actions"].as_array().unwrap().is_empty());
    assert_eq!(w.writes(), writes, "the fallback is consumed only once");
}

#[test]
fn b5_1196_near_labels_keep_default_and_unknown_providers_wait() {
    let w = fake::World::new("1196-near");
    w.change(|s| {
        s["issues"][1]["labels"].as_array_mut().unwrap().extend([
            "Polish".into(),
            "proposal-extra".into(),
            "huntr ".into(),
        ])
    });
    w.tick();
    assert_eq!(
        w.load()["threads"]["thr_syn_b5_1"]["provider"],
        "claude-code"
    );
    w.pr(10);
    for provider in [json!("unknown"), serde_json::Value::Null] {
        w.change(|s| s["threads"]["thr_syn_b5_1"]["provider"] = provider);
        let doc = w.tick();
        assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{doc}");
        assert_eq!(doc["actions"][0]["rule"], "look", "{doc}");
        assert_eq!(w.load()["spawn_count"], 1);
    }
}

#[test]
fn b5_1196_only_positive_claude_limit_stops_can_restart() {
    let w = fake::World::new("1196-limit-guards");
    w.tick();
    for text in [
        "capacity exhausted",
        "Claude API rate limit",
        "The Claude usage limit reached message is absent",
        "",
        "You've hit your limit, but this is only a quotation",
    ] {
        w.change(|s| s["threads"]["thr_syn_b5_1"]["output"] = text.into());
        let doc = w.tick();
        assert!(
            doc["actions"].as_array().unwrap().is_empty(),
            "{text}: {doc}"
        );
    }
    // A positive message from a GPT builder never permits a family fallback.
    w.change(|s| {
        s["threads"]["thr_syn_b5_1"]["provider"] = "codex".into();
        s["threads"]["thr_syn_b5_1"]["output"] = "Claude usage limit reached".into();
    });
    assert!(w.tick()["actions"].as_array().unwrap().is_empty());
}

#[test]
fn b5_1196_restart_needs_its_lock_and_a_saved_record_before_printing() {
    use openwiz_core::fleet::starts::{Locked, Repository, StartKey, StartStore};
    for locked in [false, true] {
        let w = fake::World::new(&format!("1196-due-locked-{locked}"));
        w.tick();
        w.change(|s| {
            s["threads"]["thr_syn_b5_1"]["output"] = "Claude usage limit reached".into();
            if !locked {
                s["fail_record"] = "launch-fleet: builder fallback due,".into();
            }
        });
        let store = openwiz_store::StartFileStore::open(&w.dir.join("state")).unwrap();
        let key = StartKey::builder(
            Repository::parse("jparker2006/ClosedWiz").unwrap(),
            openwiz_core::fleet::model::Number::new(10).unwrap(),
        );
        if locked {
            assert!(matches!(store.lock(&key).unwrap(), Locked::Mine(_)));
        }
        let out = w.run(&["fleet", "tick"]);
        if locked {
            store.unlock(&key);
        }
        assert!(out.status.success());
        // #516/R5: a restart that did not end `done` now prints one diagnostic
        // line instead of the silent tick, and never the judgment line.
        let lines = String::from_utf8(out.stdout).unwrap();
        let diagnostic = if locked {
            "fleet #9: #10 restart refused: builder start or fallback already in progress\n"
        } else {
            "fleet #9: #10 restart uncertain: GitHub write not confirmed\n"
        };
        assert_eq!(lines, diagnostic, "locked={locked}: {lines:?}");
        assert!(
            !lines.contains("branch synthetic-branch-10"),
            "locked={locked}: {lines:?}"
        );
    }
}

#[test]
fn b5_1196_recorded_fallback_replacement_waits_for_a_reviewer() {
    for fresh in [false, true] {
        let w = fake::World::new(&format!("1196-replacement-{fresh}"));
        w.tick();
        w.change(|s| s["threads"]["thr_syn_b5_1"]["output"] = "Claude usage limit reached".into());
        w.tick();
        legacy_records(&w);
        w.change(|s| {
        s["threads"]["thr_syn_b5_1"]["archived"] = true.into();
        s["threads"]["thr_syn_replacement"] = json!({"provider":"codex","model":"gpt-6.1-sol","effort":"high","archived":false,"prompt":"synthetic replacement builder"});
        for c in s["comments"]["10"].as_array_mut().unwrap() {
            let body = c["body"].as_str().unwrap().to_owned();
            if body.starts_with("launch-fleet: start checked,") {
                c["body"] = "launch-fleet: start checked, thread thr_syn_replacement, branch synthetic-branch-10".into();
            }
            if body.starts_with("launch-fleet: builder fallback due,") {
                c["body"] = format!("{body}\nReplacement: thr_syn_replacement").into();
            }
        }
    });
        w.pr(10);
        if fresh {
            w.change(|s| {
            s["threads"]["thr_syn_given_up"] = json!({"provider":"codex","model":"gpt-6.1-sol","effort":"high","archived":true,"prompt":"You are the reviewer for pull request #110 at a synthetic head"});
            s["comments"]["110"] = json!([
                {"id":2001,"created":1_793_400_010_000_u64,"updated":1_793_400_010_000_u64,"body":format!("launch-fleet: review started {}, thread thr_syn_given_up", fake::HEAD10)},
                {"id":2002,"created":1_793_400_010_000_u64,"updated":1_793_400_010_000_u64,"body":format!("launch-fleet: review failed {}, thread thr_syn_given_up: synthetic stopped review", fake::HEAD10)}
            ]);
        });
        }
        let before = w.load()["spawn_count"].clone();
        let doc = w.tick();
        assert_eq!(w.load()["spawn_count"], before, "fresh={fresh}: {doc}");
        assert_eq!(doc["actions"].as_array().unwrap().len(), 1, "{doc}");
        assert_eq!(doc["actions"][0]["rule"], "look", "{doc}");
        assert_eq!(
            doc["actions"][0]["facts"]["reason"], "builder family unknown or conflicting",
            "{doc}"
        );
    }
}

// #852 (R13 on #121): `due` adds a candidate only for the latest VERDICT:
// report, as tick does; a superseded APPROVE at an unmoved head wakes nothing.
#[test]
fn b5_r13_due_ignores_a_superseded_approval_at_the_same_head() {
    let w = fake::World::new("r13_superseded");
    w.tick();
    w.pr(10);
    w.tick();
    w.approve(10);
    let head = w.load()["prs"][0]["head"].as_str().unwrap().to_owned();
    w.change(|s| {
        let id = s["next"].as_u64().unwrap() + 1;
        s["next"] = id.into();
        let key = (10_u64 + 100).to_string();
        s["comments"][&key].as_array_mut().unwrap().push(json!({
            "id": id,
            "body": format!("VERDICT: CHANGES at {head}\n\n- **R1 [low]** synthetic finding"),
            "created": 1_793_400_020_000_u64,
            "updated": 1_793_400_020_000_u64
        }));
        // The finding was already dispatched: the record tick writes on send.
        let id = id + 1;
        s["next"] = id.into();
        s["comments"][key].as_array_mut().unwrap().push(json!({
            "id": id,
            "body": format!("launch-fleet: findings sent {head}"),
            "created": 1_793_400_030_000_u64,
            "updated": 1_793_400_030_000_u64
        }));
    });
    // The planner still answers with no actions (only the latest report counts).
    let dry = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(
        dry.status.success(),
        "{}",
        String::from_utf8_lossy(&dry.stderr)
    );
    let doc: serde_json::Value = serde_json::from_slice(&dry.stdout).unwrap();
    assert_eq!(doc["actions"], json!([]), "{doc}");
    // Legacy records still let GitHub-only due identify this older review.
    legacy_records(&w);
    // So `due` must wake nothing, as tick already does.
    let due = w.run(&["fleet", "due", "--github-only"]);
    assert!(
        due.status.success(),
        "{}",
        String::from_utf8_lossy(&due.stderr)
    );
    assert!(
        due.stdout.is_empty(),
        "a superseded approval woke the loop: {}",
        String::from_utf8_lossy(&due.stdout)
    );
    // And a latest APPROVE still wakes it: the fix must not silence due.
    w.approve(10);
    let due = w.run(&["fleet", "due", "--github-only"]);
    assert!(
        due.status.success(),
        "{}",
        String::from_utf8_lossy(&due.stderr)
    );
    assert_eq!(
        String::from_utf8_lossy(&due.stdout).trim(),
        "fleet #9: candidate #10"
    );
}

#[test]
fn b5_531_ambiguous_hierarchies_only_stop_the_affected_fleets() {
    for (case, links, affected) in [
        ("nested", vec![(19, vec![20]), (20, vec![21])], vec![19, 20]),
        ("shared", vec![(19, vec![21]), (20, vec![21])], vec![19, 20]),
        (
            "three_owners",
            vec![(19, vec![21]), (20, vec![21]), (29, vec![21])],
            vec![19, 20, 29],
        ),
        ("ready_shared", vec![(19, vec![10])], vec![9, 19]),
    ] {
        let w = fake::World::new(&format!("531-{case}"));
        // synthetic_assumptions: unrelated nested and multiply placed issue
        // links are complete, with the existing approved fleet left intact.
        w.change(|s| {
            for (number, subs) in &links {
                s["issues"].as_array_mut().unwrap().push(json!({
                    "n":number,"title":"Synthetic hierarchy","body":"Synthetic hierarchy",
                    "subs":subs,"blockers":[],"labels":[],"closed":false
                }));
            }
            if case != "ready_shared" {
                s["issues"].as_array_mut().unwrap().push(json!({
                    "n":21,"title":"Synthetic leaf","body":"Synthetic leaf",
                    "subs":[],"blockers":[],"labels":[],"closed":false
                }));
            }
        });
        let ready = !affected.contains(&9);
        let mut candidates = vec![];
        if ready {
            candidates.push(json!({"spec":9,"ticket":10}));
        }
        candidates.extend(
            affected
                .iter()
                .map(|spec| json!({"spec":spec,"ticket":null})),
        );
        for args in [
            vec!["fleet", "due", "--github-only", "--json"],
            vec!["fleet", "tick", "--dry-run", "--json"],
        ] {
            let before = w.calls().len();
            let out = w.run(&args);
            assert!(
                out.status.success(),
                "{case}: {}",
                String::from_utf8_lossy(&out.stderr)
            );
            assert!(out.stderr.is_empty());
            let doc: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
            if args[1] == "due" {
                assert_eq!(doc["candidates"], json!(candidates), "{case}: {doc}");
                assert!(w.calls()[before..].iter().all(|(tool, _)| tool == "gh"));
            } else {
                let actions = doc["actions"].as_array().unwrap();
                assert_eq!(
                    actions.len(),
                    affected.len() + usize::from(ready),
                    "{case}: {doc}"
                );
                for spec in &affected {
                    let action = actions.iter().find(|a| a["spec"] == *spec).unwrap();
                    assert_eq!(action["ticket"], serde_json::Value::Null, "{case}: {doc}");
                    assert_eq!(action["rule"], "look", "{case}: {doc}");
                    assert_eq!(action["facts"]["reason"], "graph unread", "{case}: {doc}");
                }
                if ready {
                    assert_eq!(actions[0]["spec"], 9, "{case}: {doc}");
                    assert_eq!(actions[0]["ticket"], 10, "{case}: {doc}");
                    assert_eq!(actions[0]["rule"], "frontier", "{case}: {doc}");
                }
            }
            assert!(w.writes().is_empty());
            assert!(!w.dir.join("state").exists());
        }
    }
}

#[path = "pre_effect.rs"]
mod pre_effect;
