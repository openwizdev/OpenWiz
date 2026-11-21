use std::fs;
use std::fs::DirBuilder;
use std::num::NonZeroU64;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use openwiz_adapter_github::writes::{self, Body, Confirmed, Label, Write, WriteError};
use openwiz_core::fleet::model::Commit;
use openwiz_core::source::SourceError;
use serde_json::{Value, json};

use crate::support::FakeGh;

const HEAD: &str = "0123456789abcdef0123456789abcdef01234567";
const OTHER_HEAD: &str = "89abcdef0123456789abcdef0123456789abcdef";
const MERGE_COMMIT: &str = "fedcba9876543210fedcba9876543210fedcba98";
const ISSUE: &str = "https://github.invalid/synthetic/repo/issues/7";
const ISSUE_URL: &str = "https://github.invalid/synthetic/repo/issues/7#issuecomment-1001";
const PR_URL: &str = "https://github.invalid/synthetic/repo/pull/8#issuecomment-1002";

const QUEUE_QUERY: &str = "query=query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number){isMergeQueueEnabled}}}";

fn queue_check() -> Vec<String> {
    words(&[
        "api",
        "graphql",
        "-f",
        QUEUE_QUERY,
        "-F",
        "owner={owner}",
        "-F",
        "repo={repo}",
        "-F",
        "number=8",
    ])
}

fn queue(enabled: Value) -> String {
    json!({"data": {"repository": {"pullRequest": {"isMergeQueueEnabled": enabled}}}}).to_string()
}

const TEXT: &str = "-x --help\nline two 'a' \"b\" $HOME `c` \\ Ünïcødé ✓\n";

fn n(number: u64) -> NonZeroU64 {
    NonZeroU64::new(number).expect("not zero")
}

fn issue_comment() -> Write {
    Write::IssueComment {
        issue: n(7),
        body: Body::parse(TEXT).unwrap(),
    }
}

fn pr_comment() -> Write {
    Write::PrComment {
        pr: n(8),
        body: Body::parse(TEXT).unwrap(),
    }
}

fn add_label() -> Write {
    Write::AddLabel {
        issue: n(7),
        label: Label::parse("held").unwrap(),
    }
}

fn remove_label() -> Write {
    Write::RemoveLabel {
        issue: n(7),
        label: Label::parse("held").unwrap(),
    }
}

fn close_issue() -> Write {
    Write::CloseIssue { issue: n(7) }
}

fn merge() -> Write {
    Write::Merge {
        pr: n(8),
        head: Commit::parse(HEAD).unwrap(),
        body: Body::parse(TEXT).unwrap(),
    }
}

fn every_write() -> Vec<Write> {
    vec![
        issue_comment(),
        pr_comment(),
        add_label(),
        remove_label(),
        close_issue(),
        merge(),
    ]
}

fn kind(write: &Write) -> &'static str {
    match write {
        Write::IssueComment { .. } => "issue-comment",
        Write::PrComment { .. } => "pr-comment",
        Write::AddLabel { .. } => "add-label",
        Write::RemoveLabel { .. } => "remove-label",
        Write::CloseIssue { .. } => "close-issue",
        Write::Merge { .. } => "merge",
    }
}

fn words(w: &[&str]) -> Vec<String> {
    w.iter().map(|w| (*w).to_owned()).collect()
}

fn expected_calls(write: &Write) -> Vec<Vec<String>> {
    match write {
        Write::IssueComment { .. } => vec![
            words(&["issue", "comment", "7", "--body", TEXT]),
            words(&["issue", "view", "7", "--json", "comments"]),
        ],
        Write::PrComment { .. } => vec![
            words(&["pr", "comment", "8", "--body", TEXT]),
            words(&["pr", "view", "8", "--json", "comments"]),
        ],
        Write::AddLabel { .. } => vec![
            words(&["issue", "edit", "7", "--add-label", "held"]),
            words(&["issue", "view", "7", "--json", "labels"]),
        ],
        Write::RemoveLabel { .. } => vec![
            words(&["issue", "edit", "7", "--remove-label", "held"]),
            words(&["issue", "view", "7", "--json", "labels"]),
        ],
        Write::CloseIssue { .. } => vec![
            words(&["issue", "view", "7", "--json", "url"]),
            words(&["issue", "close", "7"]),
            words(&["issue", "view", "7", "--json", "state"]),
        ],
        Write::Merge { .. } => vec![
            queue_check(),
            words(&[
                "pr",
                "merge",
                "8",
                "--merge",
                "--match-head-commit",
                HEAD,
                "--body",
                TEXT,
            ]),
            words(&["pr", "view", "8", "--json", "state,mergeCommit,headRefOid"]),
        ],
    }
}

fn write_and_read(write: &Write) -> (Vec<String>, Vec<String>) {
    let mut calls = expected_calls(write);
    let read = calls.pop().unwrap();
    (calls.pop().unwrap(), read)
}

fn before(write: &Write) -> Vec<Value> {
    match write {
        Write::CloseIssue { .. } => vec![answer(
            &words(&["issue", "view", "7", "--json", "url"]),
            &json!({ "url": ISSUE }).to_string(),
        )],
        Write::Merge { .. } => vec![answer(&queue_check(), &queue(json!(false)))],
        _ => vec![],
    }
}

fn comment(url: &str, body: &str) -> Value {
    json!({
        "id": "IC_synthetic",
        "author": {"login": "synthetic-login"},
        "authorAssociation": "OWNER",
        "body": body,
        "createdAt": "2026-01-01T00:00:00Z",
        "includesCreatedEdit": false,
        "isMinimized": false,
        "minimizedReason": "",
        "reactionGroups": [],
        "url": url,
        "viewerDidAuthor": true
    })
}

fn label(name: &str) -> Value {
    json!({"id": "LA_synthetic", "name": name, "description": "Synthetic", "color": "ededed"})
}

fn comments(items: &[Value]) -> String {
    json!({ "comments": items }).to_string()
}

fn labels(names: &[&str]) -> String {
    json!({ "labels": names.iter().map(|n| label(n)).collect::<Vec<_>>() }).to_string()
}

fn pr_state(state: &str, merge_commit: Value, head: &str) -> String {
    json!({"headRefOid": head, "mergeCommit": merge_commit, "state": state}).to_string()
}

fn printed(write: &Write) -> String {
    match write {
        Write::IssueComment { .. } => format!("{ISSUE_URL}\n"),
        Write::PrComment { .. } => format!("{PR_URL}\n"),
        _ => String::new(),
    }
}

fn shown(write: &Write) -> String {
    match write {
        Write::IssueComment { .. } => comments(&[
            comment(
                "https://github.invalid/synthetic/repo/issues/7#issuecomment-1000",
                "earlier",
            ),
            comment(ISSUE_URL, TEXT),
        ]),
        Write::PrComment { .. } => comments(&[comment(PR_URL, TEXT)]),
        Write::AddLabel { .. } => labels(&["ready-for-agent", "held"]),
        Write::RemoveLabel { .. } => labels(&["ready-for-agent"]),
        Write::CloseIssue { .. } => json!({"state": "CLOSED"}).to_string(),
        Write::Merge { .. } => pr_state("MERGED", json!({"oid": MERGE_COMMIT}), HEAD),
    }
}

fn confirmed(write: &Write) -> Confirmed {
    match write {
        Write::IssueComment { .. } => Confirmed::Commented {
            url: ISSUE_URL.to_owned(),
        },
        Write::PrComment { .. } => Confirmed::Commented {
            url: PR_URL.to_owned(),
        },
        Write::AddLabel { .. } => Confirmed::Labelled,
        Write::RemoveLabel { .. } => Confirmed::Unlabelled,
        Write::CloseIssue { .. } => Confirmed::Closed,
        Write::Merge { .. } => Confirmed::Merged {
            merge_commit: Commit::parse(MERGE_COMMIT).unwrap(),
        },
    }
}

fn answers(write: &Write, printed: &str, read_back: &str) -> Vec<Value> {
    let (call, read) = write_and_read(write);
    let mut all = before(write);
    all.push(answer(&call, printed));
    all.push(answer(&read, read_back));
    all
}

fn scenario(test: &str, responses: Vec<Value>) -> PathBuf {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR"))
        .join("b3-scenarios")
        .join(test);
    let _ = fs::remove_dir_all(&dir);
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&dir)
        .expect("create the scenario directory");
    let path = dir.join("scenario.json");
    let scenario = json!({
        "scenario": test,
        "description": "Synthetic answers for one B3 write test.",
        "synthetic_assumptions": [
            "Every value is synthetic. What the writes print (a comment's URL on stdout; nothing read from the others) is from gh 2.100.0's source, unobserved: no write has run live (B6, #122)."
        ],
        "responses": responses,
    });
    fs::write(&path, scenario.to_string()).expect("write the scenario");
    path
}

fn answer(argv: &[String], stdout: &str) -> Value {
    json!({"argv": argv, "stdout": stdout})
}

fn soon() -> Instant {
    Instant::now() + Duration::from_secs(10)
}

fn run(
    test: &str,
    write: &Write,
    responses: Vec<Value>,
) -> (Result<Confirmed, WriteError>, Vec<Vec<String>>) {
    let fake = FakeGh::new(&format!("b3-{test}"), &scenario(test, responses));
    let result = writes::perform(&fake.program(), write, soon());
    (result, fake.invocations())
}

#[test]
fn each_write_makes_exactly_its_calls_and_is_confirmed() {
    for write in every_write() {
        let calls = expected_calls(&write);
        assert_eq!(write.calls(), calls, "{write:?}");
        let (result, log) = run(
            &format!("works-{}", kind(&write)),
            &write,
            answers(&write, &printed(&write), &shown(&write)),
        );
        assert_eq!(result, Ok(confirmed(&write)), "{write:?}");
        assert_eq!(log, calls, "{write:?}: exactly these calls, in order");
    }
}

#[test]
fn a_write_that_fails_is_never_read_back_and_its_effect_is_unknown() {
    for write in every_write() {
        let (call, read) = write_and_read(&write);
        let mut until_the_write = expected_calls(&write);
        until_the_write.pop();
        for (case, response, detail) in [
            (
                "exit-1",
                json!({"argv": call, "stderr": "HTTP 422: Unprocessable (https://api.github.invalid/x)\n", "exit": 1}),
                "gh error: HTTP 422 (detail withheld)",
            ),
            (
                "exit-1-silent",
                json!({"argv": call, "exit": 1}),
                "no error output",
            ),
        ] {
            let mut responses = before(&write);
            responses.push(response);
            responses.push(answer(&read, &shown(&write)));
            let (result, log) = run(&format!("fails-{case}-{}", kind(&write)), &write, responses);
            assert_eq!(
                result,
                Err(WriteError::Failed(SourceError::CommandFailed {
                    exit_code: Some(1),
                    detail: detail.to_owned()
                })),
                "{write:?}"
            );
            assert_eq!(log, until_the_write, "{write:?}: no read back");
        }
        let mut responses = before(&write);
        responses.push(answer(&read, &shown(&write)));
        let (result, log) = run(&format!("unanswered-{}", kind(&write)), &write, responses);
        assert!(
            matches!(
                result,
                Err(WriteError::Failed(SourceError::CommandFailed {
                    exit_code: Some(97),
                    ..
                }))
            ),
            "{write:?}: {result:?}"
        );
        assert_eq!(log, until_the_write, "{write:?}: no read back");
    }
}

#[test]
fn a_write_that_hangs_is_stopped_at_the_deadline_and_never_read_back() {
    let write = merge();
    let (call, read) = write_and_read(&write);
    let fake = FakeGh::new(
        "b3-hangs",
        &scenario("hangs", {
            let mut responses = before(&write);
            responses.push(json!({"argv": call, "hang": true}));
            responses.push(answer(&read, &shown(&write)));
            responses
        }),
    );
    let deadline = Instant::now() + Duration::from_secs(2);
    let result = writes::perform(&fake.program(), &write, deadline);
    assert!(
        matches!(
            result,
            Err(WriteError::Failed(SourceError::TimedOut { .. }))
        ),
        "{result:?}"
    );
    assert_eq!(
        fake.invocations(),
        vec![queue_check(), call],
        "no read back"
    );
    let pid = fake.hung_pid().expect("the fake hung");
    assert!(
        !Path::new("/proc").join(pid.trim()).exists(),
        "the stopped call {pid} is still there"
    );
}

#[test]
fn a_deadline_already_passed_runs_nothing() {
    for write in every_write() {
        let fake = FakeGh::new(
            &format!("b3-passed-{}", kind(&write)),
            &scenario(
                &format!("passed-{}", kind(&write)),
                answers(&write, &printed(&write), &shown(&write)),
            ),
        );
        let result = writes::perform(&fake.program(), &write, Instant::now());
        let stopped = SourceError::TimedOut { after_ms: 0 };
        let expected = match write {
            Write::CloseIssue { .. } | Write::Merge { .. } => WriteError::CheckFailed(stopped),
            _ => WriteError::Failed(stopped),
        };
        assert_eq!(result, Err(expected), "{write:?}");
        assert_eq!(
            fake.invocations(),
            Vec::<Vec<String>>::new(),
            "{write:?}: no call"
        );
        assert_eq!(
            writes::perform(&fake.program(), &write, soon()),
            Ok(confirmed(&write))
        );
        assert_eq!(fake.invocations(), expected_calls(&write), "{write:?}");
    }
}

fn not_shown_cases() -> Vec<(&'static str, Write, String, String)> {
    let issue_line = format!("{ISSUE_URL}\n");
    let pr_line = format!("{PR_URL}\n");
    let hundred: Vec<String> = (0..100).map(|i| format!("synthetic-{i}")).collect();
    let hundred: Vec<&str> = hundred.iter().map(String::as_str).collect();
    vec![
        (
            "comment-absent",
            issue_comment(),
            issue_line.clone(),
            comments(&[]),
        ),
        (
            "comment-other-url",
            issue_comment(),
            issue_line.clone(),
            comments(&[comment(
                "https://github.invalid/synthetic/repo/issues/7#issuecomment-9999",
                TEXT,
            )]),
        ),
        (
            "comment-other-text",
            issue_comment(),
            issue_line.clone(),
            comments(&[comment(ISSUE_URL, "Synthetic, not the text sent")]),
        ),
        (
            "comment-text-trimmed",
            issue_comment(),
            issue_line.clone(),
            comments(&[comment(ISSUE_URL, TEXT.trim())]),
        ),
        (
            "comment-twice",
            issue_comment(),
            issue_line.clone(),
            comments(&[comment(ISSUE_URL, TEXT), comment(ISSUE_URL, TEXT)]),
        ),
        (
            "comment-no-url-printed",
            issue_comment(),
            String::new(),
            comments(&[comment(ISSUE_URL, TEXT)]),
        ),
        (
            "comment-url-printed-twice",
            issue_comment(),
            format!("{ISSUE_URL}\n{ISSUE_URL}\n"),
            comments(&[comment(ISSUE_URL, TEXT)]),
        ),
        (
            "comment-url-without-its-newline",
            issue_comment(),
            ISSUE_URL.to_owned(),
            comments(&[comment(ISSUE_URL, TEXT)]),
        ),
        (
            "comment-not-a-comment-url",
            issue_comment(),
            format!("{ISSUE}\n"),
            comments(&[comment(ISSUE, TEXT)]),
        ),
        (
            "comment-not-https",
            issue_comment(),
            "http://github.invalid/synthetic/repo/issues/7#issuecomment-1001\n".to_owned(),
            comments(&[comment(
                "http://github.invalid/synthetic/repo/issues/7#issuecomment-1001",
                TEXT,
            )]),
        ),
        (
            "comment-url-with-space",
            issue_comment(),
            "https://github.invalid/synthetic repo/issues/7#issuecomment-1001\n".to_owned(),
            comments(&[comment(
                "https://github.invalid/synthetic repo/issues/7#issuecomment-1001",
                TEXT,
            )]),
        ),
        (
            "comment-empty-id",
            issue_comment(),
            format!("{ISSUE}#issuecomment-\n"),
            comments(&[comment(&format!("{ISSUE}#issuecomment-"), TEXT)]),
        ),
        (
            "pr-comment-absent",
            pr_comment(),
            pr_line.clone(),
            comments(&[]),
        ),
        (
            "pr-comment-other-text",
            pr_comment(),
            pr_line,
            comments(&[comment(PR_URL, "Synthetic, not the text sent")]),
        ),
        (
            "label-absent",
            add_label(),
            String::new(),
            labels(&["ready-for-agent"]),
        ),
        ("label-none", add_label(), String::new(), labels(&[])),
        (
            "label-other-case",
            add_label(),
            String::new(),
            labels(&["Held"]),
        ),
        (
            "label-still-there",
            remove_label(),
            String::new(),
            labels(&["held"]),
        ),
        (
            "label-still-there-other-case",
            remove_label(),
            String::new(),
            labels(&["HELD", "ready-for-agent"]),
        ),
        (
            "label-maybe-cut-off",
            remove_label(),
            String::new(),
            labels(&hundred),
        ),
        (
            "close-still-open",
            close_issue(),
            String::new(),
            json!({"state": "OPEN"}).to_string(),
        ),
        (
            "merge-still-open",
            merge(),
            String::new(),
            pr_state("OPEN", Value::Null, HEAD),
        ),
        (
            "merge-closed",
            merge(),
            String::new(),
            pr_state("CLOSED", Value::Null, HEAD),
        ),
        (
            "merge-other-head",
            merge(),
            String::new(),
            pr_state("MERGED", json!({"oid": MERGE_COMMIT}), OTHER_HEAD),
        ),
        (
            "merge-no-merge-commit",
            merge(),
            String::new(),
            pr_state("MERGED", Value::Null, HEAD),
        ),
    ]
}

#[test]
fn a_read_back_that_does_not_show_the_write_never_confirms_it() {
    for (case, write, printed, read_back) in not_shown_cases() {
        let (result, log) = run(
            &format!("not-shown-{case}"),
            &write,
            answers(&write, &printed, &read_back),
        );
        assert!(
            matches!(result, Err(WriteError::NotShown(_))),
            "{case}: {result:?}"
        );
        assert_eq!(log, expected_calls(&write), "{case}: exactly these calls");
    }
}

fn malformed_cases() -> Vec<(&'static str, Write, String)> {
    let changed = |f: &dyn Fn(&mut Value)| {
        let mut v = comment(ISSUE_URL, TEXT);
        f(&mut v);
        v
    };
    let extra_key = changed(&|v| v["extra"] = json!(1));
    let missing_key = changed(&|v| {
        v.as_object_mut().unwrap().remove("viewerDidAuthor");
    });
    let body_not_text = changed(&|v| v["body"] = json!(1));
    let url_null = changed(&|v| v["url"] = Value::Null);
    let author_null = changed(&|v| v["author"] = Value::Null);
    let comment_key_twice = format!(
        "{{\"comments\":[{}]}}",
        comment(ISSUE_URL, TEXT).to_string().replacen(
            "\"body\":",
            "\"body\":\"Synthetic\",\"body\":",
            1
        )
    );
    let label_with = |extra: Value| json!({"labels": [extra]}).to_string();
    let merged = || pr_state("MERGED", json!({"oid": MERGE_COMMIT}), HEAD);
    vec![
        ("not-json", issue_comment(), "not json".to_owned()),
        ("empty", issue_comment(), String::new()),
        (
            "trailing",
            issue_comment(),
            format!("{} {{}}", comments(&[comment(ISSUE_URL, TEXT)])),
        ),
        ("array", issue_comment(), json!([{"comments": []}]).to_string()),
        ("comments-not-list", issue_comment(), json!({"comments": {}}).to_string()),
        ("comments-key-missing", issue_comment(), json!({}).to_string()),
        (
            "comments-extra-top-key",
            issue_comment(),
            json!({"comments": [], "body": "x"}).to_string(),
        ),
        (
            "comments-key-twice",
            issue_comment(),
            "{\"comments\":[],\"comments\":[]}".to_owned(),
        ),
        ("comment-extra-key", issue_comment(), comments(std::slice::from_ref(&extra_key))),
        ("comment-missing-key", issue_comment(), comments(&[missing_key])),
        ("comment-body-not-text", issue_comment(), comments(&[body_not_text])),
        ("comment-url-null", issue_comment(), comments(&[url_null])),
        ("comment-key-twice", issue_comment(), comment_key_twice),
        ("comment-not-object", issue_comment(), json!({"comments": ["x"]}).to_string()),
        (
            "comment-one-bad-of-two",
            issue_comment(),
            comments(&[author_null, extra_key]),
        ),
        ("pr-comments-array", pr_comment(), json!([]).to_string()),
        ("labels-not-list", add_label(), json!({"labels": "held"}).to_string()),
        (
            "labels-extra-top-key",
            add_label(),
            json!({"labels": [], "state": "OPEN"}).to_string(),
        ),
        (
            "label-extra-key",
            add_label(),
            label_with(json!({"id": "LA_s", "name": "held", "description": "", "color": "ededed", "extra": 1})),
        ),
        (
            "label-missing-key",
            remove_label(),
            label_with(json!({"id": "LA_s", "name": "held", "color": "ededed"})),
        ),
        (
            "label-name-not-text",
            add_label(),
            label_with(json!({"id": "LA_s", "name": 1, "description": "", "color": "ededed"})),
        ),
        (
            "label-name-null-on-remove",
            remove_label(),
            label_with(json!({"id": "LA_s", "name": null, "description": "", "color": "ededed"})),
        ),
        ("labels-key-twice", remove_label(), "{\"labels\":[],\"labels\":[]}".to_owned()),
        ("state-unknown", close_issue(), json!({"state": "closed"}).to_string()),
        ("state-merged-on-an-issue", close_issue(), json!({"state": "MERGED"}).to_string()),
        ("state-not-text", close_issue(), json!({"state": 1}).to_string()),
        ("state-tagged", close_issue(), json!({"state": {"CLOSED": null}}).to_string()),
        (
            "state-extra-key",
            close_issue(),
            json!({"state": "CLOSED", "stateReason": "COMPLETED"}).to_string(),
        ),
        (
            "state-key-twice",
            close_issue(),
            "{\"state\":\"OPEN\",\"state\":\"CLOSED\"}".to_owned(),
        ),
        (
            "pr-missing-key",
            merge(),
            json!({"state": "MERGED", "mergeCommit": {"oid": MERGE_COMMIT}}).to_string(),
        ),
        (
            "pr-extra-key",
            merge(),
            json!({"state": "MERGED", "mergeCommit": {"oid": MERGE_COMMIT}, "headRefOid": HEAD, "baseRefName": "main"}).to_string(),
        ),
        ("pr-state-unknown", merge(), pr_state("DRAFT", Value::Null, HEAD)),
        ("pr-state-lower", merge(), pr_state("merged", json!({"oid": MERGE_COMMIT}), HEAD)),
        ("pr-head-short", merge(), pr_state("MERGED", json!({"oid": MERGE_COMMIT}), "0123456")),
        (
            "pr-head-upper",
            merge(),
            pr_state("MERGED", json!({"oid": MERGE_COMMIT}), &HEAD.to_uppercase()),
        ),
        ("pr-head-null", merge(), json!({"state": "MERGED", "mergeCommit": {"oid": MERGE_COMMIT}, "headRefOid": null}).to_string()),
        ("pr-merge-commit-short", merge(), pr_state("MERGED", json!({"oid": "fedcba9"}), HEAD)),
        ("pr-merge-commit-text", merge(), pr_state("MERGED", json!(MERGE_COMMIT), HEAD)),
        (
            "pr-merge-commit-extra-key",
            merge(),
            pr_state("MERGED", json!({"oid": MERGE_COMMIT, "url": "x"}), HEAD),
        ),
        ("pr-merge-commit-empty", merge(), pr_state("MERGED", json!({}), HEAD)),
        ("pr-merge-commit-array", merge(), pr_state("MERGED", json!([MERGE_COMMIT]), HEAD)),
        (
            "pr-key-twice",
            merge(),
            format!("{{\"state\":\"OPEN\",{}", &merged()[1..]),
        ),
        (
            "pr-positional",
            merge(),
            json!(["MERGED", {"oid": MERGE_COMMIT}, HEAD]).to_string(),
        ),
    ]
}

#[test]
fn a_read_back_that_is_not_the_exact_shape_never_confirms_the_write() {
    for (case, write, read_back) in malformed_cases() {
        let (result, log) = run(
            &format!("malformed-{case}"),
            &write,
            answers(&write, &printed(&write), &read_back),
        );
        assert!(
            matches!(
                result,
                Err(WriteError::ReadBackFailed(SourceError::Malformed { .. }))
            ),
            "{case}: {result:?}"
        );
        assert_eq!(log, expected_calls(&write), "{case}: exactly these calls");
    }
}

#[test]
fn a_read_back_that_fails_never_confirms_the_write() {
    for write in every_write() {
        let (call, read) = write_and_read(&write);
        let mut responses = before(&write);
        responses.push(answer(&call, &printed(&write)));
        responses.push(json!({"argv": read, "stderr": "HTTP 502: Bad Gateway\n", "exit": 1}));
        let (result, log) = run(
            &format!("read-back-fails-{}", kind(&write)),
            &write,
            responses,
        );
        assert_eq!(
            result,
            Err(WriteError::ReadBackFailed(SourceError::CommandFailed {
                exit_code: Some(1),
                detail: "gh error: HTTP 502 (detail withheld)".to_owned()
            })),
            "{write:?}"
        );
        assert_eq!(
            log,
            expected_calls(&write),
            "{write:?}: exactly these calls"
        );
    }
}

#[test]
fn an_error_shows_nothing_gh_printed() {
    let mut errors = Vec::new();
    for (case, write, printed, read_back) in not_shown_cases() {
        let (result, _) = run(
            &format!("quiet-{case}"),
            &write,
            answers(&write, &printed, &read_back),
        );
        errors.push((case, format!("{result:?}")));
        errors.push((
            case,
            format!(
                "Err({})",
                result.err().map(|e| e.to_string()).unwrap_or_default()
            ),
        ));
    }
    for (case, write, read_back) in malformed_cases() {
        let (result, _) = run(
            &format!("quiet-malformed-{case}"),
            &write,
            answers(&write, &printed(&write), &read_back),
        );
        errors.push((case, format!("{result:?}")));
        errors.push((
            case,
            format!(
                "Err({})",
                result.err().map(|e| e.to_string()).unwrap_or_default()
            ),
        ));
    }
    for (case, error) in errors {
        assert!(error.starts_with("Err("), "{case}: {error}");
        let error = error.replace("(withheld)", "");
        for leak in [
            "github.invalid",
            "issuecomment",
            "Synthetic",
            "synthetic",
            "held",
            "HELD",
            "earlier",
            MERGE_COMMIT,
            OTHER_HEAD,
            HEAD,
            "line two",
            "not json",
        ] {
            assert!(!error.contains(leak), "{case}: {error} shows {leak:?}");
        }
    }
}
