use super::fake::{self, World};
use serde_json::{Value, json};
use std::fs;

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
    let good = "[]\n[{\"id\":2,\"author\":\"syn-author\",\"body\":\"Synthetic\\nsecond line\",\"created\":10,\"updated\":10}]\n[{\"id\":1,\"author\":null,\"body\":\"Other\",\"created\":9,\"updated\":9}]";
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
        "[{\"id\":1,\"id\":2,\"author\":null,\"body\":\"S\",\"created\":9,\"updated\":9}]",
        "[{\"id\":1,\"author\":null,\"body\":\"S\",\"created\":9,\"updated\":9}]\n[{\"id\":1,\"author\":null,\"body\":\"S\",\"created\":9,\"updated\":9}]",
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
    json!({"issue_url":format!("https://github.invalid/api/v3/repos/jparker2006/ClosedWiz/issues/{issue}"),"id":id,"author":"openwiz[bot]","body":"Synthetic\nsecond line","created":100,"updated":101})
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

#[test]
fn b5_due_wakes_for_closed_ticket_with_unrecorded_agent_audit_comment() {
    let w = World::new("due_orphan");
    super::builder_started(&w);
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
fn b5_review_r2_github_only_cannot_distinguish_an_unlogged_local_start() {
    let absent = World::new("r2_absent");
    let local = World::new("r2_local");
    super::builder_started(&local);
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
