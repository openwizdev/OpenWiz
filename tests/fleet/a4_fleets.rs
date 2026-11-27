#[path = "a4_allowlist.rs"]
mod allowlist_forms;
#[path = "a4_edges.rs"]
mod edges;
#[path = "a4_no_checks.rs"]
pub(crate) mod no_checks;

use std::fs::{self, DirBuilder};
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::{Value, json};

use openwiz_adapter_github::allowlist;
use openwiz_cli::fleets;

use crate::schema::{load_schema, validate};
use crate::support::{FIXTURES, fakes_on_path, in_process, left_behind, openwiz_release};

const CONTRACT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../contracts/fleet.v1.md");

const ISSUE_LIST: &[&str] = &[
    "issue",
    "list",
    "--state",
    "all",
    "--limit",
    "1000",
    "--json",
    "blockedBy,body,id,labels,milestone,number,state,subIssues,title",
];
const PR_LIST: &[&str] = &[
    "pr",
    "list",
    "--state",
    "all",
    "--limit",
    "1000",
    "--json",
    "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state,title",
];

fn checks_argv(pr: u64) -> Vec<String> {
    words(&["pr", "checks", &pr.to_string(), "--json", "bucket,name"])
}

fn comments_argv(pr: u64) -> Vec<String> {
    words(&[
        "pr",
        "view",
        &pr.to_string(),
        "--json",
        "comments",
        "--jq",
        "[.comments[].body]",
    ])
}

fn batch_response(commits: &[char], absent: Option<char>) -> Value {
    let pairs: Vec<_> = commits
        .iter()
        .map(|&c| ("main".to_owned(), commit(c)))
        .collect();
    let mut repo = serde_json::Map::new();
    for (i, &c) in commits.iter().enumerate() {
        let missing = absent == Some(c);
        repo.insert(
            format!("r{i}"),
            json!({
            "target": {"oid": commit('f')},
            "comparison": {"status": if missing {"AHEAD"} else {"BEHIND"},
                "aheadBy": if missing {3} else {0}, "behindBy": if missing {0} else {3},
                "baseTarget": {"oid": commit('f')}, "headTarget": {"oid": commit(c)}}}),
        );
    }
    json!({"argv": edges::batch_argv(&pairs), "stdout": json!({"data":{"repository":repo}}).to_string()})
}

fn batch_responses() -> Vec<Value> {
    (1..8)
        .map(|mask| {
            let commits: Vec<_> = ['2', 'b', 'd']
                .into_iter()
                .enumerate()
                .filter_map(|(i, c)| (mask & (1 << i) != 0).then_some(c))
                .collect();
            batch_response(&commits, None)
        })
        .collect()
}

fn words(w: &[&str]) -> Vec<String> {
    w.iter().map(|s| (*s).to_owned()).collect()
}

fn commit(c: char) -> String {
    c.to_string().repeat(40)
}

fn comments() -> Vec<Value> {
    let answer = |pr: u64, bodies: &[String]| {
        json!({
            "argv": comments_argv(pr),
            "stdout": serde_json::to_string(bodies).unwrap(),
        })
    };
    vec![
        answer(
            952,
            &[
                "Synthetic comment".to_owned(),
                format!("VERDICT: APPROVE at {}\n\nSynthetic report", commit('3')),
            ],
        ),
        answer(
            953,
            &[format!(
                "VERDICT: CHANGES at {}\r\n\r\nSynthetic report",
                commit('4')
            )],
        ),
        answer(954, &[]),
        answer(
            955,
            &[
                format!("VERDICT: APPROVE at {}", commit('7')),
                format!("VERDICT: CHANGES at {}", commit('7')),
                "Synthetic later comment".to_owned(),
            ],
        ),
    ]
}

struct Ran {
    code: Option<i32>,
    stdout: String,
    stderr: String,
    gh: Vec<Vec<String>>,
    left: Vec<String>,
}

impl Ran {
    fn json(&self) -> Value {
        assert_eq!(
            (self.code, self.stderr.as_str()),
            (Some(0), ""),
            "{}",
            self.stdout
        );
        serde_json::from_str(&self.stdout).expect("stdout is one JSON document")
    }
}

fn private_dir(dir: &Path) {
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(dir)
        .expect("create a test directory");
}

fn copy_dir(from: &Path, to: &Path) {
    private_dir(to);
    for entry in fs::read_dir(from).expect("read the fixtures") {
        let path = entry.expect("entry").path();
        let target = to.join(path.file_name().expect("a name"));
        if path.is_dir() {
            copy_dir(&path, &target);
        } else {
            fs::copy(&path, &target).expect("copy a fixture");
        }
    }
}

fn stage(test: &str, base: &str, extra: Vec<Value>) -> PathBuf {
    let root = Path::new(env!("CARGO_TARGET_TMPDIR"))
        .join("a4-scenarios")
        .join(test);
    let _ = fs::remove_dir_all(&root);
    copy_dir(&Path::new(FIXTURES).join("fleets"), &root);
    let mut responses = extra;
    responses.extend(comments());
    responses.extend(batch_responses());
    let scenario = json!({
        "scenario": "run",
        "description": "Synthetic answers the fixture scan has no form for",
        "synthetic_assumptions": ["Every value is synthetic", "GraphQL comparison fields are documented; raw merge SHA headRef acceptance has not been observed live"],
        "extends": base,
        "responses": responses,
    });
    let path = root.join("run").join("scenario.json");
    private_dir(path.parent().unwrap());
    fs::write(&path, serde_json::to_string_pretty(&scenario).unwrap()).unwrap();
    path
}

fn run(test: &str, base: &str, extra: Vec<Value>, args: &[&str]) -> Ran {
    let scenario = stage(test, base, extra);
    let (dir, path) = fakes_on_path(&format!("a4-{test}"));
    fs::write(dir.join("fake-gh.scenario"), scenario.to_str().unwrap()).unwrap();
    let out = Command::new(openwiz_release())
        .arg("fleets")
        .args(args)
        .env("PATH", &path)
        .env("OPENWIZ_FIXTURE_PROGRAM", dir.join("room-cli"))
        .current_dir(&dir)
        .output()
        .expect("run openwiz");
    let gh: Vec<Vec<String>> = fs::read_to_string(dir.join("gh-invocations.log"))
        .unwrap_or_default()
        .lines()
        .map(|l| serde_json::from_str(l).expect("a JSON list"))
        .collect();
    for argv in &gh {
        let argv: Vec<&str> = argv.iter().map(String::as_str).collect();
        assert!(
            allowlist::allowed(&argv),
            "{test}: not allowlisted: {argv:?}"
        );
    }
    Ran {
        code: out.status.code(),
        stdout: String::from_utf8(out.stdout).expect("UTF-8 stdout"),
        stderr: String::from_utf8(out.stderr).expect("UTF-8 stderr"),
        gh,
        left: left_behind(&dir),
    }
}

fn json_run(test: &str, base: &str, extra: Vec<Value>) -> (Value, Ran) {
    let ran = run(test, base, extra, &["--json"]);
    let doc = ran.json();
    let errors = validate(&load_schema(), &doc);
    assert_eq!(
        errors,
        Vec::<String>::new(),
        "{test}: the schema refuses it"
    );
    (doc, ran)
}

fn example_one(snapshot_at: &Value) -> Value {
    let text = fs::read_to_string(CONTRACT).expect("the contract");
    let block = text
        .split("```json\n")
        .nth(1)
        .and_then(|rest| rest.split("\n```").next())
        .expect("example 1");
    let mut doc: Value = serde_json::from_str(block).expect("example 1 is JSON");
    for read in doc["reads"].as_array_mut().unwrap() {
        let kind = read["kind"].as_str().unwrap().to_owned();
        let value = &mut read["outcome"]["value"];
        match kind.as_str() {
            "repository" => value["name"] = json!("syn-example-repo"),
            "issue" => {
                for label in value["labels"].as_array_mut().unwrap() {
                    if *label == "spec" {
                        *label = json!("documentation");
                    }
                }
            }
            "checks" => {
                for check in value.as_array_mut().unwrap() {
                    let name = format!("syn-{}", check["name"].as_str().unwrap());
                    check["name"] = json!(name);
                }
            }
            _ => {}
        }
    }
    doc["freshness"]["snapshot_at"] = snapshot_at.clone();
    doc
}

fn read<'a>(doc: &'a Value, kind: &str, key: &str, subject: Value) -> &'a Value {
    doc["reads"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["kind"] == kind && (key.is_empty() || r[key] == subject))
        .unwrap_or_else(|| panic!("no {kind} read of {subject}"))
}

fn ticket(doc: &Value, number: u64) -> &Value {
    doc["data"]["tickets"]
        .as_array()
        .unwrap()
        .iter()
        .find(|t| t["number"] == number)
        .unwrap_or_else(|| panic!("no ticket {number}"))
}

fn fleet(doc: &Value, spec: u64) -> &Value {
    doc["data"]["fleets"]
        .as_array()
        .unwrap()
        .iter()
        .find(|f| f["spec"] == spec)
        .unwrap_or_else(|| panic!("no fleet {spec}"))
}

fn same_but(doc: &Value, base: &Value, paths: &[&str]) {
    let mut a = doc.clone();
    let mut b = base.clone();
    for p in paths {
        let pointer = format!("/{p}");
        for v in [&mut a, &mut b] {
            if let Some(x) = v.pointer_mut(&pointer) {
                *x = json!("(changed)");
            }
        }
    }
    assert_eq!(a, b, "only {paths:?} differ");
}

const FAKE_GH_FILES: &[&str] = &[
    "fake-gh.scenario",
    "gh-environment.log",
    "gh-invocations.log",
];

fn complete(test: &str) -> (Value, Ran) {
    json_run(&format!("{test}-base"), "complete", vec![])
}

#[test]
fn the_complete_scenario_prints_the_contracts_first_example() {
    let (doc, ran) = complete("example-one");
    assert_eq!(doc, example_one(&doc["freshness"]["snapshot_at"]));
    assert_eq!(ran.left, FAKE_GH_FILES, "room-cli was called");
}

#[test]
fn every_read_id_is_its_place_in_the_reads() {
    let (doc, _) = complete("read-order");
    let ids: Vec<&str> = doc["reads"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| r["id"].as_str().unwrap())
        .collect();
    assert!(!ids.is_empty());
    assert_eq!(
        ids,
        (1..=ids.len()).map(|n| format!("r{n}")).collect::<Vec<_>>()
    );
}

#[test]
fn only_the_allowlisted_reads_run_once_each_and_never_room_cli() {
    let mut want: Vec<Vec<String>> = vec![
        words(&["--version"]),
        words(&["repo", "view", "--json", "nameWithOwner"]),
        words(ISSUE_LIST),
        words(PR_LIST),
    ];
    for pr in [952, 953, 954, 955] {
        want.push(checks_argv(pr));
        want.push(comments_argv(pr));
    }
    want.push(edges::batch_argv(
        &['2', 'b', 'd'].map(|c| ("main".to_owned(), commit(c))),
    ));
    want.sort();
    for args in [&["--json"][..], &[]] {
        let ran = run("allowlisted", "complete", vec![], args);
        assert_eq!(ran.code, Some(0), "{}", ran.stderr);
        assert_eq!(ran.gh[..4], want_first(), "{args:?}");
        let mut got = ran.gh.clone();
        got.sort();
        assert_eq!(got, want, "{args:?}");
        for argv in &ran.gh {
            let argv: Vec<&str> = argv.iter().map(String::as_str).collect();
            assert!(allowlist::allowed(&argv), "not allowlisted: {argv:?}");
        }
        assert_eq!(ran.left, FAKE_GH_FILES, "room-cli was called");
    }
}

fn want_first() -> Vec<Vec<String>> {
    vec![
        words(&["--version"]),
        words(&["repo", "view", "--json", "nameWithOwner"]),
        words(ISSUE_LIST),
        words(PR_LIST),
    ]
}

#[test]
fn the_text_shows_needs_you_first_then_each_fleets_progress() {
    let ran = run("text", "complete", vec![], &[]);
    assert_eq!((ran.code, ran.stderr.as_str()), (Some(0), ""));
    let (header, rest) = ran.stdout.split_once('\n').expect("a header line");
    assert!(
        header.starts_with("openwiz fleets · syn-example-repo · gh 2.100.0 (tested) · snapshot 20")
            && header.ends_with("Z · complete"),
        "{header}"
    );
    assert_eq!(
        rest,
        "
needs you
  #904 needs-info, in fleet #901
  #907 held, in fleet #901

fleets
  #901 Synthetic spec one (0.9.1): 1 of 9 merged, 4 moving, 1 blocked
      ready 1, building 2, in review 1, changes requested 1, held 1, unknown 1
      #909 unknown: closed on GitHub, and no merge was read back
  #930 Synthetic spec two: 0 of 2 merged, 0 moving, 1 blocked
      ready 1
"
    );
}

#[test]
fn a_failed_checks_read_leaves_only_what_requires_it_unread() {
    let (doc, ran) = json_run("checks-fail", "checks-fail", vec![]);
    let (base, _) = complete("checks-fail");
    assert_eq!(
        read(&doc, "checks", "pr", json!(952))["outcome"],
        json!({"state": "failed", "gap": "command_failed",
               "reason": "gh pr checks 952 exited 1: gh error (detail withheld)"})
    );
    assert_eq!(read(&doc, "checks", "pr", json!(952))["id"], "r13");
    assert_eq!(ticket(&doc, 903)["state"], json!({"unread": ["r13"]}));
    assert_eq!(fleet(&doc, 901)["progress"], json!({"unread": ["r13"]}));
    assert_eq!(doc["coverage"], json!({"state": "partial"}));
    same_but(
        &doc,
        &base,
        &[
            "reads/12/outcome",
            "data/tickets/1/state",
            "data/fleets/0/progress",
            "coverage/state",
            "freshness/snapshot_at",
        ],
    );
    let text = run("checks-fail-text", "checks-fail", vec![], &[]);
    assert!(text.stdout.contains(
        "  #901 Synthetic spec one (0.9.1): progress unread (r13)\n      #903 unread (r13)\n      #909 unknown: closed on GitHub, and no merge was read back\n"
    ), "{}", text.stdout);
    assert!(text.stdout.ends_with(
        "\ngaps\n  r13 checks of pull request #952: failed (command_failed): gh pr checks 952 exited 1: gh error (detail withheld)\n"
    ), "{}", text.stdout);
    assert!(
        text.stdout
            .lines()
            .next()
            .unwrap()
            .ends_with(" · partial, 1 gaps")
    );
    assert_eq!(ran.left, FAKE_GH_FILES);
}

#[test]
fn a_malformed_checks_answer_is_never_read_as_a_value() {
    let (doc, _) = json_run("malformed-checks", "malformed-checks", vec![]);
    assert_eq!(
        read(&doc, "checks", "pr", json!(952))["outcome"],
        json!({"state": "failed", "gap": "malformed",
               "reason": "gh pr checks 952 printed an answer OpenWiz can't read: [0]: a key it shouldn't have"})
    );
    assert_eq!(ticket(&doc, 903)["state"], json!({"unread": ["r13"]}));
}

#[test]
fn a_read_that_hangs_times_out_and_the_run_goes_on() {
    let (doc, ran) = json_run("hang", "hang", vec![]);
    let outcome = &read(&doc, "checks", "pr", json!(953))["outcome"];
    assert_eq!(read(&doc, "checks", "pr", json!(953))["id"], "r18");
    assert_eq!(
        (&outcome["state"], &outcome["gap"]),
        (&json!("failed"), &json!("timed_out"))
    );
    let reason = outcome["reason"].as_str().unwrap();
    assert!(
        reason.starts_with("gh pr checks 953 timed out after ") && reason.ends_with(" ms"),
        "{reason}"
    );
    assert_eq!(ticket(&doc, 904)["state"], json!({"unread": ["r18"]}));
    assert_eq!(fleet(&doc, 901)["progress"], json!({"unread": ["r18"]}));
    assert_eq!(ticket(&doc, 903)["state"], json!({"known": "in_review"}));
    assert_eq!(fleet(&doc, 930)["progress"]["known"]["tickets"], 2);
    assert!(
        ran.left.contains(&"gh-hang.pid".to_owned()),
        "{:?}",
        ran.left
    );
}

#[test]
fn a_blocker_list_cut_short_is_partial_and_its_ticket_unread() {
    let (doc, _) = json_run("truncated", "truncated", vec![]);
    let (base, _) = complete("truncated");
    assert_eq!(
        read(&doc, "blocked_by", "ticket", json!(932))["outcome"],
        json!({"state": "partial", "gap": "truncated",
               "reason": "GitHub listed 1 of #932's 2 blockers", "value": [931]})
    );
    assert_eq!(ticket(&doc, 932)["state"], json!({"unread": ["r54"]}));
    assert_eq!(fleet(&doc, 930)["progress"], json!({"unread": ["r54"]}));
    same_but(
        &doc,
        &base,
        &[
            "reads/53/outcome",
            "data/tickets/10/state",
            "data/fleets/1/progress",
            "coverage/state",
            "freshness/snapshot_at",
        ],
    );
}

#[test]
fn a_blocker_from_another_repository_is_never_taken_for_this_ones() {
    let (doc, _) = json_run("foreign-blocker", "foreign-blocker", vec![]);
    assert_eq!(
        read(&doc, "blocked_by", "ticket", json!(908))["outcome"],
        json!({"state": "failed", "gap": "not_found",
               "reason": "#908's blocker #811 isn't one of this repository's issues"})
    );
    assert_eq!(read(&doc, "blocked_by", "ticket", json!(908))["id"], "r32");
    assert_eq!(ticket(&doc, 908)["state"], json!({"unread": ["r32"]}));
    assert_eq!(fleet(&doc, 901)["progress"], json!({"unread": ["r32"]}));
    let blockers: Vec<&Value> = doc["data"]["blockers"]
        .as_array()
        .unwrap()
        .iter()
        .map(|b| &b["number"])
        .collect();
    assert_eq!(blockers, [&json!(902), &json!(931)]);
    assert!(
        doc["reads"]
            .as_array()
            .unwrap()
            .iter()
            .all(|r| r["issue"] != 811 && r["issue"] != 812),
        "no read of #811 or #812 is made"
    );
}

#[test]
fn without_the_pull_request_list_no_ticket_is_ever_merged() {
    let (doc, ran) = json_run("pr-list-fails", "pr-list-fails", vec![]);
    let reason = "gh pr list exited 1: gh error (detail withheld)";
    for r in doc["reads"].as_array().unwrap() {
        let kind = r["kind"].as_str().unwrap();
        assert!(
            !["checks", "comments", "merge_readback"].contains(&kind),
            "{r}"
        );
        if kind == "pr_discovery" {
            assert_eq!(
                r["outcome"],
                json!({"state": "failed", "gap": "command_failed", "reason": reason})
            );
        }
    }
    for t in doc["data"]["tickets"].as_array().unwrap() {
        assert!(t["state"].get("unread").is_some(), "{t}");
        assert_eq!(
            (&t["ci"], &t["review"], &t["on_base"]),
            (&Value::Null, &Value::Null, &Value::Null)
        );
    }
    assert_eq!(
        ticket(&doc, 908)["state"],
        json!({"unread": ["r11", "r26", "r34", "r36"]})
    );
    assert_eq!(ticket(&doc, 903)["state"], json!({"unread": ["r8", "r11"]}));
    for b in doc["data"]["blockers"].as_array().unwrap() {
        assert!(b["merged"].get("unread").is_some(), "{b}");
    }
    assert_eq!(
        doc["data"]["needs_you"]["known"].as_array().map(Vec::len),
        Some(2),
        "the labels are still known"
    );
    assert_eq!(ran.gh, want_first());
}

#[test]
fn without_the_issue_list_no_fleet_is_shown_and_needs_you_is_unread() {
    for scenario in ["issue-list-fails", "malformed-issues"] {
        let (doc, ran) = json_run(scenario, scenario, vec![]);
        let reason = if scenario == "issue-list-fails" {
            json!({"state": "failed", "gap": "command_failed",
                   "reason": "gh issue list exited 1: gh error (detail withheld)"})
        } else {
            json!({"state": "failed", "gap": "malformed",
                   "reason": "gh issue list printed something that isn't one JSON value with each key once"})
        };
        assert_eq!(doc["reads"].as_array().unwrap().len(), 3, "{scenario}");
        assert_eq!(read(&doc, "spec_list", "", Value::Null)["outcome"], reason);
        assert_eq!(
            doc["data"],
            json!({"view": "fleets", "repository": "r2", "specs": "r3", "fleets": [],
                   "tickets": [], "blockers": [], "needs_you": {"unread": ["r3"]}})
        );
        assert_eq!(doc["coverage"], json!({"state": "partial"}));
        assert_eq!(
            ran.gh,
            want_first()[..3],
            "{scenario}: no pull request read"
        );
    }
    let text = run("issue-list-fails-text", "issue-list-fails", vec![], &[]);
    assert!(text.stdout.contains("\nneeds you\n  unread: r3\n\nfleets\n  none listed\n\ngaps\n  r3 the spec list: failed (command_failed): gh issue list exited 1: gh error (detail withheld)\n"), "{}", text.stdout);
}

#[test]
fn an_unreadable_version_is_reported_and_never_a_gate() {
    let (doc, ran) = json_run("version-unreadable", "version-unreadable", vec![]);
    let (base, _) = complete("version-unreadable");
    assert_eq!(
        read(&doc, "version", "source", json!("github"))["outcome"],
        json!({"state": "failed", "gap": "untested_version",
               "reason": "gh --version printed no recognised version (withheld)"})
    );
    assert_eq!(doc["sources"]["github"]["version_tested"], false);
    same_but(
        &doc,
        &base,
        &[
            "reads/0/outcome",
            "sources/github/version_tested",
            "coverage/state",
            "freshness/snapshot_at",
        ],
    );
    assert_eq!(ran.gh.len(), 13);
}

#[test]
fn a_merge_not_found_on_its_base_is_never_merged() {
    let behind = batch_response(&['2', 'b', 'd'], Some('2'));
    let (doc, _) = json_run("not-on-base", "complete", vec![behind]);
    assert_eq!(
        read(&doc, "merge_readback", "pr", json!(951))["outcome"],
        json!({"state": "complete", "value": false})
    );
    assert_eq!(
        ticket(&doc, 902)["state"],
        json!({"unknown": "closed on GitHub, and no merge was read back"})
    );
    let b902 = doc["data"]["blockers"]
        .as_array()
        .unwrap()
        .iter()
        .find(|b| b["number"] == 902)
        .unwrap();
    assert_eq!(b902["merged"], json!({"known": false}));
    assert_eq!(ticket(&doc, 906)["state"], json!({"known": "blocked"}));
    assert_eq!(ticket(&doc, 903)["state"], json!({"known": "in_review"}));
    assert_eq!(
        fleet(&doc, 901)["progress"],
        json!({"known": {"tickets": 9, "ready": 0, "building": 2, "in_review": 1,
                         "changes_requested": 1, "merged": 0, "held": 1, "blocked": 2,
                         "unknown": 2}})
    );
    assert_eq!(doc["coverage"], json!({"state": "complete"}));
}

fn cli_document(text: &str) -> Value {
    assert!(text.ends_with('\n'));
    let doc: Value = serde_json::from_str(text).expect("one whole-stream CLI document");
    let schema: Value =
        serde_json::from_str(include_str!("../../contracts/cli.v1.schema.json")).unwrap();
    assert_eq!(validate(&schema, &doc), Vec::<String>::new(), "{doc}");
    doc
}

#[test]
fn a_usage_error_reads_nothing() {
    for (args, why, json_output) in [
        (
            &["95"][..],
            "fleets takes no argument (one fleet is openwiz fleet <spec>)",
            false,
        ),
        (
            &["--json", "95"],
            "fleets takes no argument (one fleet is openwiz fleet <spec>)",
            true,
        ),
        (&["-x"], "unknown option -x", false),
        (&["--limit", "5"], "unknown option --limit", false),
        (&["--json", "--json"], "--json is given twice", true),
    ] {
        assert_eq!(
            in_process(fleets::run, args),
            (
                2,
                String::new(),
                format!("openwiz: fleets: {why}; nothing was read (see openwiz --help)\n")
            ),
            "{args:?}"
        );
        let ran = run("usage", "complete", vec![], args);
        assert_eq!(ran.code, Some(2), "{args:?}");
        if json_output {
            let doc = cli_document(&ran.stdout);
            assert_eq!(doc["schema"], "openwiz.cli-error.v1");
            assert_eq!(doc["command"], "fleets");
            assert_eq!(doc["exit_code"], 2);
            assert_eq!(doc["error"]["kind"], "usage");
        } else {
            assert!(ran.stdout.is_empty(), "{args:?}");
        }
        assert_eq!(
            ran.gh,
            Vec::<Vec<String>>::new(),
            "{args:?}: something was read"
        );
    }
    for (args, json_output) in [
        (&["--help"][..], false),
        (&["-h"], false),
        (&["--json", "--help"], true),
    ] {
        let (code, stdout, stderr) = in_process(fleets::run, args);
        assert_eq!(code, 0, "{args:?}");
        assert!(stderr.is_empty(), "{args:?}");
        if json_output {
            assert_eq!(
                cli_document(&stdout),
                json!({"schema":"openwiz.cli-help.v1", "text":openwiz_cli::help()})
            );
        } else {
            assert_eq!(stdout, openwiz_cli::help(), "{args:?}");
        }
        let ran = run("help", "complete", vec![], args);
        assert_eq!(ran.code, Some(0));
        assert_eq!(ran.stdout, stdout, "{args:?}");
        assert!(ran.gh.is_empty(), "{args:?}: help read a source");
    }
    assert_eq!(fleets::USAGE, "  openwiz fleets [--json]\n");
}

#[test]
fn no_checks_reported_keeps_the_ticket_building_and_fleet_progress_known() {
    let response = json!({"argv": checks_argv(954), "exit": 1,
        "stderr": "no checks reported on the 'room/syn-a5-0005' branch\n"});
    let mut prs: Vec<Value> = serde_json::from_str(
        &fs::read_to_string(Path::new(FIXTURES).join("fleets/complete/prs.json")).unwrap(),
    )
    .unwrap();
    prs.iter_mut().find(|p| p["number"] == 954).unwrap()["isDraft"] = json!(false);
    let list = json!({"argv": PR_LIST, "stdout": serde_json::to_string(&prs).unwrap()});
    let (doc, ran) = json_run("no-checks-reported", "complete", vec![response, list]);
    assert_eq!(
        read(&doc, "checks", "pr", json!(954))["outcome"],
        json!({"state": "complete", "value": []})
    );
    assert_eq!(
        ticket(&doc, 905)["ci"],
        read(&doc, "checks", "pr", json!(954))["id"]
    );
    assert_eq!(ticket(&doc, 905)["state"], json!({"known": "building"}));
    assert_eq!(doc["coverage"], json!({"state": "complete"}));
    assert_eq!(
        fleet(&doc, 901)["progress"],
        json!({"known": {
            "tickets": 9, "merged": 1, "ready": 1, "building": 2,
            "in_review": 1, "changes_requested": 1, "held": 1, "blocked": 1, "unknown": 1
        }})
    );
    assert_eq!(ran.gh.iter().filter(|a| **a == checks_argv(954)).count(), 1);
    assert_eq!(ran.left, FAKE_GH_FILES);
}

#[test]
fn no_checks_near_misses_leave_ticket_and_progress_unread() {
    for (i, mut response) in no_checks::failures().into_iter().enumerate() {
        response["argv"] = json!(checks_argv(954));
        let (doc, ran) = json_run(
            &format!("no-checks-near-miss-{i}"),
            "complete",
            vec![response],
        );
        let checks = read(&doc, "checks", "pr", json!(954));
        assert_eq!(checks["outcome"]["state"], "failed", "case {i}");
        assert_eq!(checks["outcome"]["gap"], "command_failed", "case {i}");
        assert_eq!(
            ticket(&doc, 905)["state"],
            json!({"unread": [checks["id"]]})
        );
        assert_eq!(
            fleet(&doc, 901)["progress"],
            json!({"unread": [checks["id"]]})
        );
        let reason = checks["outcome"]["reason"].as_str().unwrap();
        assert!(
            reason.ends_with("gh error (detail withheld)")
                || reason.ends_with("gh error: HTTP 403 (detail withheld)")
                || reason.ends_with("no error output"),
            "{reason}"
        );
        assert_eq!(ran.gh.iter().filter(|a| **a == checks_argv(954)).count(), 1);
    }
}
