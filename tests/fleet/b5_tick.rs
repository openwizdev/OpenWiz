use std::fs;
use std::process::Command;

use openwiz_core::fleet::model::{Commit, Number};
use openwiz_core::fleet::starts::{Repository, StartKey};
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

fn start_record(w: &fake::World, key: StartKey, settings: [&str; 3], op: &str, thread: &str) {
    use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};
    let starts = w.dir.join("state/starts");
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&starts)
        .unwrap();
    let at = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis();
    let [harness, model, effort] = settings;
    let id = key.id().as_str().to_owned();
    let record = json!({
        "schema": "openwiz.start-record.v1",
        "id": id,
        "key": {
            "repository": key.repository().as_str(),
            "role": key.role().as_str(),
            "number": key.number(),
            "commit": key.commit().map(|c| c.as_str()),
        },
        "project_id": "prj_syn_0001",
        "settings": {"harness": harness, "model": model, "effort": effort},
        "attempts": [{"op_id": op, "at": at, "outcome": {"kind": "created", "thread_id": thread}}]
    });
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(starts.join(format!("{id}.json")))
        .unwrap();
    std::io::Write::write_all(&mut file, &serde_json::to_vec_pretty(&record).unwrap()).unwrap();
}

fn repository(w: &fake::World) -> Repository {
    let s = w.load();
    let name = s["repository"].as_str().unwrap_or("jparker2006/ClosedWiz");
    Repository::parse(name).unwrap()
}

fn builder_started(w: &fake::World) {
    let at = 1_793_400_010_000_u64;
    w.change(|s| {
        s["comments"]["10"] = json!([
            {"id": 1001, "body": "launch-fleet: started", "created": at, "updated": at},
            {"id": 1002, "body": "launch-fleet: start checked, branch synthetic-branch-10", "created": at, "updated": at}
        ]);
        s["next"] = 1002.into();
        s["spawn_count"] = 1.into();
        s["threads"]["thr_syn_b5_1"] = json!({
            "archived": false, "branch": "synthetic-branch-10", "effort": "xhigh",
            "model": "claude-opus-5-5", "provider": "claude-code",
            "prompt": "You are the builder for #10. Read skills/build-ticket/SKILL.md and follow it."
        });
    });
    start_record(
        w,
        StartKey::builder(repository(w), Number::new(10).unwrap()),
        ["claude-code", "claude-opus-5-5", "xhigh"],
        "op-0082199868a240f3fdfd5f64ab5afb2e",
        "thr_syn_b5_1",
    );
}

fn review_started(w: &fake::World) {
    let at = 1_793_400_010_000_u64;
    w.change(|s| {
        let id = s["next"].as_u64().unwrap() + 1;
        s["next"] = id.into();
        s["comments"]["110"] = json!([
            {"id": id, "body": format!("launch-fleet: review started {}", fake::HEAD10), "created": at, "updated": at}
        ]);
        s["spawn_count"] = (s["spawn_count"].as_u64().unwrap() + 1).into();
        s["threads"]["thr_syn_b5_2"] = json!({
            "archived": false, "branch": null, "effort": "high",
            "model": "gpt-6.1-sol", "provider": "codex",
            "prompt": format!("You are the reviewer for pull request #110 at {}. Read skills/review-ticket/SKILL.md and follow it.", fake::HEAD10)
        });
    });
    start_record(
        w,
        StartKey::reviewer(
            repository(w),
            Number::new(110).unwrap(),
            Commit::parse(fake::HEAD10).unwrap(),
        ),
        ["codex", "gpt-6.1-sol", "high"],
        "op-cf5e71f091fe69436eb125ee18352c89",
        "thr_syn_b5_2",
    );
}

#[test]
fn b5_due_running_builder_is_idle_without_cloudroom_or_state() {
    let w = fake::World::new("due_running");
    builder_started(&w);
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
    let row = json!({"id":1,"author":"syn-author","body":"Synthetic","created":100,"updated":100});
    assert!(comments(&json!([[row.clone()]])).is_ok());
    let ghost = json!({"id":1,"author":null,"body":"Synthetic","created":100,"updated":100});
    assert_eq!(comments(&json!([[ghost]])).unwrap()[0].author, None);
    for bad in [
        json!([row.clone()]),
        json!([[{"id":1,"body":"Synthetic","created":100,"updated":100}]]),
        json!([[{"id":1,"author":7,"body":"Synthetic","created":100,"updated":100}]]),
        json!([[row.clone(), row.clone()]]),
        json!([[{"id":1,"author":"syn-author","body":"Synthetic","created":100,"updated":99}]]),
        json!([[{"id":"1","author":"syn-author","body":"Synthetic","created":100,"updated":100}]]),
        json!([[{"id":1,"author":"syn-author","body":[],"created":100,"updated":100}]]),
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

#[test]
fn b5_r13_due_ignores_a_superseded_approval_at_the_same_head() {
    let w = fake::World::new("r13_superseded");
    builder_started(&w);
    w.pr(10);
    review_started(&w);
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
        let id = id + 1;
        s["next"] = id.into();
        s["comments"][key].as_array_mut().unwrap().push(json!({
            "id": id,
            "body": format!("launch-fleet: findings sent {head}"),
            "created": 1_793_400_030_000_u64,
            "updated": 1_793_400_030_000_u64
        }));
    });
    let dry = w.run(&["fleet", "tick", "--dry-run", "--json"]);
    assert!(
        dry.status.success(),
        "{}",
        String::from_utf8_lossy(&dry.stderr)
    );
    let doc: serde_json::Value = serde_json::from_slice(&dry.stdout).unwrap();
    assert_eq!(doc["actions"], json!([]), "{doc}");
    legacy_records(&w);
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
