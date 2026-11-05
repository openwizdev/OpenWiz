//! AC7: shipped tick through the service scheduler, fresh processes and state.
//! synthetic_assumptions: repository projections, provider catalogue, receipts,
//! branch metadata and manual legacy replacement records are synthetic.
use super::*;
use std::path::Path;

fn load(root: &Path) -> Value {
    serde_json::from_slice(&fs::read(root.join("fleet.json")).unwrap()).unwrap()
}
fn save(root: &Path, value: &Value) {
    fs::write(root.join("fleet.json"), value.to_string()).unwrap();
}
fn comment(id: u64, body: impl Into<String>) -> Value {
    json!({"id":id,"body":body.into(),"created":1_793_400_010_000_u64,"updated":1_793_400_010_000_u64})
}
fn thread(id: &str, provider: &str, archived: bool) -> Value {
    let mut value: Value = serde_json::from_str(include_str!(
        "../fixtures/room-cli-v127/new-thread/thread-show-active.json"
    ))
    .unwrap();
    value["thread"]["id"] = json!(id);
    value["thread"]["title"] = json!("#10: Synthetic ticket 10");
    value["thread"]["providerId"] = json!(provider);
    value["thread"]["status"] = json!("idle");
    value["thread"]["archivedAt"] = if archived {
        json!(1_793_400_010_000_u64)
    } else {
        Value::Null
    };
    value
}
fn world(f: &Fixture, builder: Option<&str>) {
    setup(f);
    let mut value = json!({"issues":synthetic_issues(false),"prs":[],"comments":{"9":[comment(100,include_str!("fixtures/t4-completion-approval.md"))]},"threads":{},"outputs":{},"spawns":[],"next":1000,"record_failure":null,"repository":"synthetic-owner/synthetic-repo"});
    value["is_private"] = json!(false);
    if let Some(provider) = builder {
        value["threads"]["thr_syn_builder"] = thread("thr_syn_builder", provider, false);
        value["outputs"]["thr_syn_builder"] = json!("Claude usage limit reached");
        value["comments"]["10"] = json!([
            comment(101, "launch-fleet: started"),
            comment(
                102,
                "launch-fleet: start checked, branch synthetic-branch-10"
            )
        ]);
    }
    save(&f.0, &value);
}
fn pr(value: &mut Value) {
    let (owner, name) = value["repository"]
        .as_str()
        .unwrap()
        .split_once('/')
        .unwrap();
    let (owner, name) = (owner.to_owned(), name.to_owned());
    value["prs"] = json!([{"baseRefName":"main","closingIssuesReferences":[{"id":"syn-issue-10","number":10,"repository":{"id":"syn-repo","name":name,"owner":{"id":"syn-owner","login":owner}},"url":format!("https://github.invalid/{}/issues/10",value["repository"].as_str().unwrap())}],"headRefName":"synthetic-branch-10","headRefOid":HEAD,"isDraft":false,"mergeCommit":null,"mergedAt":null,"number":110,"state":"OPEN"}]);
}
fn dry(f: &Fixture) -> Value {
    child(f, "fleet-dry");
    serde_json::from_slice(&fs::read(f.0.join("dry.json")).unwrap()).unwrap()
}
fn scheduled(f: &Fixture) -> String {
    let output = child(f, "fleet-scheduled");
    String::from_utf8(output.stderr).unwrap()
}
fn posts(f: &Fixture) -> Vec<Value> {
    calls(f)
        .into_iter()
        .filter(|row| {
            row["tool"] == "gh"
                && matches!(row["args"][0].as_str(), Some("issue" | "pr"))
                && row["args"][1] == "comment"
        })
        .collect()
}
fn no_starts(f: &Fixture) {
    assert_eq!(load(&f.0)["spawns"], json!([]));
    assert_eq!(
        calls(f)
            .iter()
            .filter(|row| row["args"][0] == "thread" && row["args"][1] == "spawn")
            .count(),
        0
    );
}

pub(super) fn response(root: &Path, tool: &str, args: &[&str]) -> Option<Value> {
    let mut value = load(root);
    let repository = value["repository"].as_str().unwrap().to_owned();
    if tool == "room-cli" {
        return match args {
            ["--version"] => Some(json!("v127")),
            ["project", "list", ..] => Some(
                json!([{"id":"prj_syn_0001","kind":"standard","name":"Synthetic project","gitRemoteUrl":format!("https://github.com/{repository}.git"),"createdAt":1_700_000_000_000_u64,"updatedAt":1_700_000_000_000_u64,"sources":[]}]),
            ),
            ["cloud", "status", "--json"] => {
                let mut catalogue: Value = serde_json::from_str(include_str!(
                    "../fixtures/room-cli-v127/new-thread/cloud-status.json"
                ))
                .unwrap();
                for harness in catalogue["harnesses"].as_array_mut().unwrap() {
                    let names: &[&str] = match harness["id"].as_str() {
                        Some("codex") => &["syn-builder", "syn-small", "syn-reviewer"],
                        Some("claude-code") => &["syn-claude", "syn-reviewer"],
                        _ => continue,
                    };
                    harness["models"] = json!(
                        names
                            .iter()
                            .map(|model| json!({"model":model,"reasoning_levels":["high"]}))
                            .collect::<Vec<_>>()
                    );
                }
                Some(catalogue)
            }
            ["thread", "list", ..] => Some(Value::Array(
                value["threads"]
                    .as_object()
                    .unwrap()
                    .values()
                    .map(|t| t["thread"].clone())
                    .collect(),
            )),
            ["thread", "show", id, "--json"] => value["threads"].get(*id).cloned(),
            ["thread", "output", id, "--json"] => Some(
                json!({"output":value["outputs"].get(*id).cloned().unwrap_or(json!("")),"error":null}),
            ),
            ["cloud", "thread-workspace", ..] => Some(
                json!({"branch":"synthetic-branch-10","head":"a".repeat(40),"path":"/synthetic/workspace"}),
            ),
            ["thread", "spawn", ..] => {
                let flag = |name| {
                    args.iter()
                        .position(|arg| *arg == name)
                        .and_then(|i| args.get(i + 1))
                        .copied()
                };
                let provider = flag("--provider")?;
                let id = format!(
                    "thr_syn_native_{}",
                    value["spawns"].as_array().unwrap().len() + 1
                );
                value["spawns"].as_array_mut().unwrap().push(json!({"provider":provider,"model":flag("--model"),"effort":flag("--reasoning-level")}));
                let mut shown = thread(&id, provider, false);
                shown["thread"]["title"] = json!("Synthetic anonymous thread");
                value["threads"][&id] = shown;
                save(root, &value);
                let mut receipt: Value = serde_json::from_str(include_str!(
                    "../fixtures/room-cli-v127/new-thread/spawn-receipt-created.json"
                ))
                .unwrap();
                receipt["id"] = json!(id);
                receipt["providerId"] = json!(provider);
                Some(receipt)
            }
            _ => None,
        };
    }
    match args {
        ["repo", "view", "--json", "nameWithOwner,isPrivate"] => {
            Some(json!({"nameWithOwner":repository,"isPrivate":value["is_private"]}))
        }
        ["repo", "view", ..] => Some(
            json!({"defaultBranchRef":{"name":"main"},"nameWithOwner":repository,"url":format!("https://github.invalid/{repository}")}),
        ),
        ["issue", "list", ..] => Some(value["issues"].clone()),
        ["pr", "list", ..] => Some(Value::Array(
            value["prs"]
                .as_array()
                .unwrap()
                .iter()
                .cloned()
                .map(|mut pr| {
                    pr["title"] = json!(format!("Synthetic PR {}", pr["number"]));
                    pr
                })
                .collect(),
        )),
        ["api", path, ..] => {
            let path = path.strip_prefix("repos/{owner}/{repo}/")?;
            if path.starts_with("git/ref/heads/") {
                return Some(json!({"sha":"a".repeat(40)}));
            }
            if path.starts_with("contents/docs/agents/fleet.md") {
                return Some(json!(fs::read_to_string(root.join("rules.md")).unwrap()));
            }
            if path.starts_with("issues/comments?") {
                let mut comments = Vec::new();
                for (number, rows) in value["comments"].as_object().unwrap() {
                    for row in rows.as_array().unwrap() {
                        let mut row = row.clone();
                        row["issue_url"] = json!(format!(
                            "https://github.invalid/api/v3/repos/{repository}/issues/{number}"
                        ));
                        comments.push(row);
                    }
                }
                return Some(json!(comments));
            }
            if let Some(rest) = path.strip_prefix("issues/") {
                let (number, kind) = rest.split_once('/')?;
                if kind.starts_with("comments?") {
                    return Some(value["comments"].get(number).cloned().unwrap_or(json!([])));
                }
                if kind.starts_with("timeline?") {
                    return Some(json!([]));
                }
            }
            if path.starts_with("commits/") {
                return Some(json!({"sha":HEAD,"subject":"Synthetic green"}));
            }
            if path.starts_with("actions/runs?") {
                return Some(
                    json!({"total_count":1,"runs":[{"id":110,"head_sha":HEAD,"event":"pull_request","run_attempt":1,"updated":1_793_400_010_000_u64,"prs":[{"number":110,"head":HEAD,"base":"a".repeat(40)}]}]}),
                );
            }
            if path.starts_with("actions/runs/110/jobs?") {
                return Some(
                    json!({"total_count":1,"jobs":[{"id":1100,"name":"rust","status":"completed","conclusion":"success","head_sha":HEAD,"run_id":110}]}),
                );
            }
            None
        }
        ["pr", "checks", ..] => Some(json!([{"bucket":"pass","name":"rust"}])),
        [
            "pr",
            "view",
            _,
            "--json",
            "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state",
        ] => value["prs"].as_array().unwrap().first().cloned(),
        ["issue" | "pr", "comment", number, "--body", body] => {
            assert!(
                !body.contains("thr_"),
                "public output contains private thread identity"
            );
            if value["record_failure"] == "refused" {
                std::process::exit(97);
            }
            let id = value["next"].as_u64().unwrap() + 1;
            value["next"] = json!(id);
            if value["comments"].get(*number).is_none() {
                value["comments"][*number] = json!([]);
            }
            value["comments"][*number]
                .as_array_mut()
                .unwrap()
                .push(comment(id, *body));
            save(root, &value);
            if value["record_failure"] == "lost" {
                std::process::exit(97);
            }
            Some(json!(format!(
                "https://github.invalid/{repository}/issues/{number}#issuecomment-{id}"
            )))
        }
        [kind @ ("issue" | "pr"), "view", number, "--json", "url"] => Some(
            json!({"url":format!("https://github.invalid/{repository}/{}/{number}",if *kind=="pr" {"pull"} else {"issues"})}),
        ),
        ["issue" | "pr", "view", number, "--json", "comments"] => Some(
            json!({"comments":value["comments"].get(*number).and_then(Value::as_array).into_iter().flatten().map(|c|json!({"id":format!("syn-comment-{}",c["id"]),"author":null,"authorAssociation":"OWNER","body":c["body"],"createdAt":"2026-10-30T00:00:00Z","includesCreatedEdit":false,"isMinimized":false,"minimizedReason":null,"reactionGroups":[],"url":format!("https://github.invalid/{repository}/issues/{number}#issuecomment-{}",c["id"]),"viewerDidAuthor":true})).collect::<Vec<_>>()}),
        ),
        _ => None,
    }
}

#[test]
fn scheduled_tick_uses_selected_small_builder_settings_once() {
    let f = Fixture::new();
    world(&f, None);
    let mut value = load(&f.0);
    value["issues"][1]["labels"].as_array_mut().unwrap().push(
        json!({"id":"syn-label-polish","name":"polish","description":"Synthetic","color":"ffffff"}),
    );
    save(&f.0, &value);
    let planned = dry(&f);
    assert_eq!(planned["actions"][0]["rule"], "frontier", "{planned}");
    assert_eq!(
        planned["actions"][0]["facts"]["settings"]["model"], "syn-small",
        "{planned}"
    );
    assert_eq!(scheduled(&f), "");
    assert_eq!(
        load(&f.0)["spawns"],
        json!([{"provider":"codex","model":"syn-small","effort":"high"}])
    );
    assert_eq!(scheduled(&f), "");
    assert_eq!(load(&f.0)["spawns"].as_array().unwrap().len(), 1);
    assert_eq!(posts(&f).len(), 1);
}

#[test]
fn scheduled_fallback_is_saved_once_before_judgment_and_never_starts_replacement() {
    let f = Fixture::new();
    world(&f, Some("claude-code"));
    let planned = dry(&f);
    assert_eq!(planned["actions"][0]["rule"], "restart", "{planned}");
    let first = scheduled(&f);
    assert_eq!(
        first,
        "fleet #9: #10 restart: branch synthetic-branch-10 with --provider codex --model syn-small --reasoning-level high\n"
    );
    let value = load(&f.0);
    assert_eq!(
        value["comments"]["10"]
            .as_array()
            .unwrap()
            .iter()
            .filter(
                |c| c["body"] == "launch-fleet: builder fallback due, branch synthetic-branch-10"
            )
            .count(),
        1
    );
    assert_eq!(posts(&f).len(), 1);
    assert_eq!(scheduled(&f), "");
    assert_eq!(posts(&f).len(), 1);
    no_starts(&f);
}

#[test]
fn scheduled_fallback_record_failure_or_lost_reply_never_prints_restart_judgment() {
    for mode in ["refused", "lost"] {
        let f = Fixture::new();
        world(&f, Some("claude-code"));
        let mut value = load(&f.0);
        value["record_failure"] = json!(mode);
        save(&f.0, &value);
        assert_eq!(dry(&f)["actions"][0]["rule"], "restart");
        let first = scheduled(&f);
        assert_eq!(
            first,
            "fleet #9: #10 restart uncertain: GitHub write not confirmed\n"
        );
        assert!(!first.contains("restart: branch"));
        let again = scheduled(&f);
        assert!(!again.contains("restart: branch"), "{again}");
        assert_eq!(again, if mode == "lost" { "" } else { first.as_str() });
        assert_eq!(posts(&f).len(), if mode == "lost" { 1 } else { 2 });
        let saved = load(&f.0)["comments"]["10"]
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
        assert_eq!(saved, usize::from(mode == "lost"));
        no_starts(&f);
    }
}

#[test]
fn scheduled_reviewer_uses_checked_provider_after_default_changes() {
    for (provider, expected) in [("claude-code", "codex"), ("codex", "claude-code")] {
        let f = Fixture::new();
        world(&f, Some(provider));
        let mut value = load(&f.0);
        pr(&mut value);
        value["outputs"]["thr_syn_builder"] = json!("");
        save(&f.0, &value);
        if provider == "codex" {
            let rules = fs::read_to_string(f.0.join("rules.md"))
                .unwrap()
                .replacen("--provider codex", "--provider claude-code", 1)
                .replacen("--model syn-builder", "--model syn-claude", 1);
            fs::write(f.0.join("rules.md"), rules).unwrap();
        }
        let planned = dry(&f);
        assert_eq!(planned["actions"].as_array().unwrap().len(), 1, "{planned}");
        assert_eq!(planned["actions"][0]["rule"], "first_review", "{planned}");
        assert_eq!(
            planned["actions"][0]["facts"]["settings"]["harness"], expected,
            "{planned}"
        );
        assert_eq!(scheduled(&f), "");
        assert_eq!(
            load(&f.0)["spawns"],
            json!([{"provider":expected,"model":"syn-reviewer","effort":"high"}])
        );
        // The upstream fixture deliberately dates review activity in the past.
        // A clean wake reports quiet judgment, while retaining the same reviewer.
        assert_eq!(
            scheduled(&f),
            format!(
                "fleet #9: #10 look: reviewer quiet for 30 minutes on {HEAD} since 1793400010000\n"
            )
        );
        assert_eq!(load(&f.0)["spawns"].as_array().unwrap().len(), 1);
        assert_eq!(posts(&f).len(), 1);
    }
}

#[test]
fn scheduled_missing_conflicting_or_wrong_branch_provider_never_starts_reviewer() {
    for mode in [
        "missing-check",
        "wrong-branch",
        "unknown-provider",
        "conflicting-checks",
        "conflicting-builders",
    ] {
        let f = Fixture::new();
        world(&f, Some("codex"));
        let mut value = load(&f.0);
        pr(&mut value);
        match mode {
            "missing-check" => {
                value["comments"]["10"].as_array_mut().unwrap().remove(1);
            }
            "wrong-branch" => {
                value["comments"]["10"][1]["body"] =
                    json!("launch-fleet: start checked, branch synthetic-other-branch");
            }
            "unknown-provider" => {
                value["threads"]["thr_syn_builder"]["thread"]["providerId"] =
                    json!("synthetic-unknown");
            }
            "conflicting-checks" => {
                value["comments"]["10"]
                    .as_array_mut()
                    .unwrap()
                    .push(comment(
                        103,
                        "launch-fleet: start checked, branch synthetic-other-branch",
                    ));
            }
            "conflicting-builders" => {
                value["threads"]["thr_syn_conflict"] =
                    thread("thr_syn_conflict", "claude-code", false);
            }
            _ => unreachable!(),
        }
        save(&f.0, &value);
        let planned = dry(&f);
        assert_eq!(
            planned["actions"].as_array().unwrap().len(),
            1,
            "{mode}: {planned}"
        );
        assert_eq!(planned["actions"][0]["rule"], "look", "{mode}: {planned}");
        for _ in 0..2 {
            let diagnostic = scheduled(&f);
            assert!(diagnostic.contains(" look:"), "{mode}: {diagnostic}");
            assert_eq!(diagnostic.lines().count(), 1, "{mode}: {diagnostic}");
        }
        no_starts(&f);
        assert_eq!(posts(&f).len(), 0, "{mode}");
    }
}

fn replacement_case(private_compatibility: bool) {
    for fresh in [false, true] {
        let f = Fixture::new();
        world(&f, Some("claude-code"));
        if private_compatibility {
            // Private compatibility is explicitly verified by synthetic metadata;
            // the namespace alone grants nothing. No live call exists.
            let mut value = load(&f.0);
            value["repository"] = json!("jparker2006/ClosedWiz");
            value["is_private"] = json!(true);
            save(&f.0, &value);
            let config_path = f.0.join("service/config.json");
            let mut config: Value =
                serde_json::from_slice(&fs::read(&config_path).unwrap()).unwrap();
            config["repository"] = json!({"owner":"jparker2006","name":"ClosedWiz"});
            fs::write(config_path, config.to_string()).unwrap();
        }
        let before = dry(&f);
        assert_eq!(before["actions"][0]["rule"], "restart", "{before}");
        let first = scheduled(&f);
        assert!(
            first.contains("restart: branch synthetic-branch-10"),
            "{first}"
        );
        let mut value = load(&f.0);
        // Synthetic private legacy handover is explicit operator input, not an
        // automatic replacement performed by the engine or a new public format.
        value["comments"]["10"] = json!([
            comment(101, "launch-fleet: started, thread thr_syn_builder"),
            comment(
                102,
                "launch-fleet: start checked, thread thr_syn_replacement, branch synthetic-branch-10"
            ),
            comment(
                1001,
                "launch-fleet: builder fallback due, thread thr_syn_builder, branch synthetic-branch-10\nReplacement: thr_syn_replacement"
            )
        ]);
        value["threads"]["thr_syn_builder"] = thread("thr_syn_builder", "claude-code", true);
        value["threads"]["thr_syn_replacement"] = thread("thr_syn_replacement", "codex", false);
        pr(&mut value);
        if fresh {
            let mut old = thread("thr_syn_given_up", "codex", true);
            old["thread"]["title"] = json!("Synthetic retired reviewer");
            value["threads"]["thr_syn_given_up"] = old;
            value["comments"]["110"] = json!([
                comment(
                    2001,
                    format!("launch-fleet: review started {HEAD}, thread thr_syn_given_up")
                ),
                comment(
                    2002,
                    format!(
                        "launch-fleet: review failed {HEAD}, thread thr_syn_given_up: synthetic stopped review"
                    )
                )
            ]);
        }
        save(&f.0, &value);
        let planned = dry(&f);
        assert_eq!(
            planned["actions"].as_array().unwrap().len(),
            1,
            "fresh={fresh}: {planned}"
        );
        assert_eq!(planned["actions"][0]["rule"], "look", "{planned}");
        let reason = if private_compatibility {
            "builder family unknown or conflicting"
        } else {
            "records unread"
        };
        assert_eq!(
            planned["actions"][0]["facts"]["reason"], reason,
            "{planned}"
        );
        for _ in 0..2 {
            assert_eq!(scheduled(&f), format!("fleet #9: #10 look: {reason}\n"));
        }
        no_starts(&f);
        assert_eq!(
            posts(&f).len(),
            1,
            "only the original fallback record was posted"
        );
    }
}

#[test]
fn scheduled_private_recorded_replacement_holds_first_and_fresh_review_across_wakes() {
    replacement_case(true);
}

#[test]
fn scheduled_unsettled_public_handover_never_assigns_first_or_fresh_review() {
    replacement_case(false);
}

#[test]
fn scheduled_empty_unapproved_or_idle_work_starts_nothing_across_wakes() {
    for mode in ["empty", "unapproved", "idle"] {
        let f = Fixture::new();
        world(&f, if mode == "idle" { Some("codex") } else { None });
        let mut value = load(&f.0);
        if mode == "empty" {
            value["issues"] = json!([]);
        }
        if mode == "unapproved" {
            value["comments"]["9"] = json!([]);
        }
        if mode == "idle" {
            value["outputs"]["thr_syn_builder"] = json!("");
        }
        save(&f.0, &value);
        assert_eq!(dry(&f)["actions"], json!([]), "{mode}");
        for _ in 0..2 {
            assert_eq!(scheduled(&f), "", "{mode}");
        }
        no_starts(&f);
        assert_eq!(posts(&f).len(), 0);
    }
}
