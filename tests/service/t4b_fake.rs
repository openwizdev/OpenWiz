//! Recording tools supplied by this Rust test executable, without an interpreter.
//! synthetic_assumptions: archive stdout is unobserved and ignored by its reader.
use super::*;
use std::{fs::OpenOptions, io::Write, os::unix::fs::OpenOptionsExt};

const ISSUE: &str = "https://github.invalid/synthetic-owner/synthetic-repo/issues/10";

#[test]
fn tool_process() {
    let Some(root) = std::env::var_os("OPENWIZ_T4B_TOOL_ROOT") else {
        return;
    };
    let root = PathBuf::from(root);
    let request = PathBuf::from(std::env::var_os("OPENWIZ_T4B_TOOL_ARGS").unwrap());
    let bytes = fs::read(&request).unwrap();
    fs::remove_file(request).unwrap();
    assert_eq!(bytes.last(), Some(&0));
    let argv: Vec<_> = bytes[..bytes.len() - 1]
        .split(|b| *b == 0)
        .map(|arg| std::str::from_utf8(arg).unwrap().to_owned())
        .collect();
    let tool = std::env::var("OPENWIZ_T4B_TOOL").unwrap();
    let record = json!({"tool":tool,"args":argv,"token":std::env::var("GH_TOKEN").ok(),"repo":std::env::var("GH_REPO").ok()});
    OpenOptions::new()
        .create(true)
        .append(true)
        .mode(0o600)
        .open(root.join("calls.jsonl"))
        .unwrap()
        .write_all(format!("{record}\n").as_bytes())
        .unwrap();
    if root.join("deny.json").exists()
        && serde_json::from_slice::<Value>(&fs::read(root.join("deny.json")).unwrap()).unwrap()
            == json!(argv)
    {
        std::process::exit(97);
    }
    let args: Vec<_> = argv.iter().map(String::as_str).collect();
    let Some(answer) = response(&root, &tool, &args) else {
        std::process::exit(99);
    };
    let text = match answer {
        Value::String(s) => s,
        v => v.to_string(),
    };
    // Shell fd 3 preserves the caller's output pipe; libtest progress goes to
    // /dev/null. Like T7's fake, this needs neither unsafe code nor Python.
    let mut output = OpenOptions::new()
        .write(true)
        .open("/proc/self/fd/3")
        .unwrap();
    writeln!(output, "{text}").unwrap();
    std::process::exit(0);
}

fn links(numbers: &[u64]) -> Value {
    json!({"nodes":numbers.iter().map(|n| json!({"id":format!("syn-issue-{n}"),"number":n,"state":"CLOSED","title":"Synthetic","url":format!("https://example.invalid/issues/{n}")})).collect::<Vec<_>>(),"totalCount":numbers.len()})
}

fn response(root: &std::path::Path, tool: &str, args: &[&str]) -> Option<Value> {
    if root.join("fleet.json").exists() {
        return super::fleet::response(root, tool, args);
    }
    if root.join("completion.json").exists() {
        return completion_response(root, tool, args);
    }
    if tool == "room-cli" {
        return match args {
            ["--version"] => Some(json!("v127")),
            ["project", "list", ..] => Some(json!([{
                "id":"prj_syn_0001", "kind":"standard", "name":"Synthetic project",
                "gitRemoteUrl":"https://github.com/synthetic-owner/synthetic-repo.git",
                "createdAt":1_700_000_000_000_u64, "updatedAt":1_700_000_000_000_u64, "sources":[]
            }])),
            ["thread", "list", ..] => {
                let thread: Value =
                    serde_json::from_slice(&fs::read(root.join("thread.json")).unwrap()).unwrap();
                Some(json!([thread["thread"]]))
            }
            ["thread", "show", "thr_syn_0021", "--json"] => {
                Some(serde_json::from_slice(&fs::read(root.join("thread.json")).unwrap()).unwrap())
            }
            ["thread", "archive", "thr_syn_0021", "--json"] => {
                let mut thread: Value =
                    serde_json::from_slice(&fs::read(root.join("thread.json")).unwrap()).unwrap();
                thread["thread"]["archivedAt"] = json!(1_700_000_700_000_u64);
                fs::write(root.join("thread.json"), thread.to_string()).unwrap();
                Some(json!({"synthetic_archive_accepted":true}))
            }
            _ => None,
        };
    }
    let base = "a".repeat(40);
    let mut comments: Value =
        serde_json::from_slice(&fs::read(root.join("comments.json")).unwrap()).unwrap();
    match args {
        ["repo", "view", ..] => Some(json!({"defaultBranchRef":{"name":"main"},"nameWithOwner":"synthetic-owner/synthetic-repo","url":"https://github.invalid/synthetic-owner/synthetic-repo"})),
        ["issue", "list", ..] => Some(json!([9,10].map(|n| json!({"blockedBy":links(&[]),"body":"**Owned paths:** `crates/example.rs`\n**Relies on:** nothing","id":format!("syn-issue-{n}"),"labels":[],"milestone":null,"number":n,"state":"CLOSED","subIssues":links(if n==9 {&[10]} else {&[]}),"title":"Synthetic"})))),
        ["pr", "list", ..] => Some(json!([])),
        ["api", path, ..] => {
            let path = path.strip_prefix("repos/{owner}/{repo}/")?;
            if path.starts_with("git/ref/heads/") { return Some(json!({"sha":base})); }
            if path.starts_with("contents/docs/agents/fleet.md") { return Some(json!(fs::read_to_string(root.join("rules.md")).unwrap())); }
            if path.starts_with("issues/comments?") {
                let mut rows = comments.clone();
                for row in rows.as_array_mut().unwrap() { row["issue_url"] = json!("https://github.invalid/api/v3/repos/synthetic-owner/synthetic-repo/issues/10"); }
                return Some(rows);
            }
            if path.starts_with("issues/10/comments?") { return Some(comments); }
            if path.starts_with("actions/runs?") { return Some(json!({"total_count":1,"runs":[{"id":110,"head_sha":HEAD,"event":"pull_request","run_attempt":1,"updated":1_700_000_000_000_u64,"prs":[{"number":110,"head":HEAD,"base":base}]}]})); }
            if path.starts_with("actions/runs/110/jobs?") { return Some(json!({"total_count":1,"jobs":[{"id":1100,"name":"rust","status":"completed","conclusion":"success","head_sha":HEAD,"run_id":110}]})); }
            None
        }
        ["pr", "checks", ..] => Some(json!([{"bucket":"pass","name":"rust"}])),
        ["pr", "view", ..] => Some(json!({"baseRefName":"main","closingIssuesReferences":[],"headRefName":"synthetic-branch","headRefOid":HEAD,"isDraft":false,"mergeCommit":null,"mergedAt":null,"number":110,"state":"OPEN"})),
        ["issue", "comment", "10", "--body", body] => {
            if *body == "launch-fleet: archived" && root.join("fail-final-once").exists() {
                fs::remove_file(root.join("fail-final-once")).unwrap();
                std::process::exit(97);
            }
            comments.as_array_mut().unwrap().push(json!({"id":101,"body":body,"created":1_700_000_001_000_u64,"updated":1_700_000_001_000_u64}));
            fs::write(root.join("comments.json"), comments.to_string()).unwrap();
            Some(json!(format!("{ISSUE}#issuecomment-101")))
        }
        ["issue", "view", "10", "--json", "url"] => Some(json!({"url":ISSUE})),
        ["issue", "view", "10", "--json", "state"] => Some(json!({"state":"CLOSED"})),
        ["issue", "view", "10", "--json", "comments"] => Some(json!({"comments":comments.as_array().unwrap().iter().map(|c| json!({"id":format!("syn-comment-{}",c["id"]),"author":null,"authorAssociation":"OWNER","body":c["body"],"createdAt":"2023-11-14T22:13:20Z","includesCreatedEdit":false,"isMinimized":false,"minimizedReason":null,"reactionGroups":[],"url":format!("{ISSUE}#issuecomment-{}",c["id"]),"viewerDidAuthor":true})).collect::<Vec<_>>() })),
        ["issue", "close", "10"] => Some(json!("closed")),
        _ => None,
    }
}

// A complete approved graph whose tickets are closed, with no running agents.
// Values are upstream facts; the real planner chooses its completion action.
fn completion_response(root: &std::path::Path, tool: &str, args: &[&str]) -> Option<Value> {
    let mut data: Value =
        serde_json::from_slice(&fs::read(root.join("completion.json")).unwrap()).unwrap();
    if tool == "room-cli" {
        return match args {
            ["--version"] => Some(json!("v127")),
            ["project", "list", ..] => Some(json!([{
                "id":"prj_syn_0001", "kind":"standard", "name":"Synthetic project",
                "gitRemoteUrl":"https://github.com/synthetic-owner/synthetic-repo.git",
                "createdAt":1_700_000_000_000_u64, "updatedAt":1_700_000_000_000_u64, "sources":[]
            }])),
            ["thread", "list", ..] => Some(json!([])),
            ["thread", "show", "thr_syn_0001", "--json"] => {
                let mut thread: Value =
                    serde_json::from_slice(&fs::read(root.join("thread.json")).unwrap()).unwrap();
                thread["thread"]["id"] = json!("thr_syn_0001");
                thread["thread"]["archivedAt"] = Value::Null;
                Some(thread)
            }
            ["thread", "tell", "thr_syn_0001", ..] => {
                Some(json!({"threadId":"thr_syn_0001","ok":true,"delivery":"sent","mode":"queue"}))
            }
            _ => None,
        };
    }
    match args {
        ["repo", "view", ..] => Some(
            json!({"defaultBranchRef":{"name":"main"},"nameWithOwner":"synthetic-owner/synthetic-repo","url":"https://github.invalid/synthetic-owner/synthetic-repo"}),
        ),
        ["issue", "list", ..] => Some(data["issues"].clone()),
        ["pr", "list", ..] => Some(json!([])),
        ["api", path, ..] => {
            let path = path.strip_prefix("repos/{owner}/{repo}/")?;
            if path.starts_with("git/ref/heads/") {
                return Some(json!({"sha":"a".repeat(40)}));
            }
            if path.starts_with("contents/docs/agents/fleet.md") {
                return Some(json!(fs::read_to_string(root.join("rules.md")).unwrap()));
            }
            if path.starts_with("issues/comments?") {
                let mut comments = data["comments"].clone();
                for comment in comments.as_array_mut().unwrap() {
                    comment["issue_url"] = json!(
                        "https://github.invalid/api/v3/repos/synthetic-owner/synthetic-repo/issues/9"
                    );
                }
                return Some(comments);
            }
            if path.starts_with("issues/9/comments?") {
                return Some(data["comments"].clone());
            }
            if path.contains("/comments?") || path.contains("/timeline?") {
                return Some(json!([]));
            }
            None
        }
        ["issue", "comment", "9", "--body", body] => {
            data["comments"].as_array_mut().unwrap().push(json!({"id":901,"body":body,"created":1_793_400_010_000_u64,"updated":1_793_400_010_000_u64}));
            fs::write(root.join("completion.json"), data.to_string()).unwrap();
            Some(json!(
                "https://github.invalid/synthetic-owner/synthetic-repo/issues/9#issuecomment-901"
            ))
        }
        ["issue", "view", "9", "--json", "comments"] => Some(
            json!({"comments":data["comments"].as_array().unwrap().iter().map(|c| json!({"id":format!("syn-comment-{}",c["id"]),"author":null,"authorAssociation":"OWNER","body":c["body"],"createdAt":"2026-10-30T00:00:00Z","includesCreatedEdit":false,"isMinimized":false,"minimizedReason":null,"reactionGroups":[],"url":format!("https://github.invalid/synthetic-owner/synthetic-repo/issues/9#issuecomment-{}",c["id"]),"viewerDidAuthor":true})).collect::<Vec<_>>()}),
        ),
        ["issue", "view", "9", "--json", "url"] => {
            Some(json!({"url":"https://github.invalid/synthetic-owner/synthetic-repo/issues/9"}))
        }
        ["issue", "view", "9", "--json", "state"] => Some(
            json!({"state":if data["issues"][0]["state"] == "CLOSED" {"CLOSED"} else {"OPEN"}}),
        ),
        ["issue", "close", "9"] => {
            data["issues"][0]["state"] = json!("CLOSED");
            fs::write(root.join("completion.json"), data.to_string()).unwrap();
            Some(json!("closed"))
        }
        _ => None,
    }
}
