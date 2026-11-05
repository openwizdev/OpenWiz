//! CK1 source-half proofs: synthetic issue comments and explicit risk labels.
//! The public GitHub issue reader feeds the fleet's public worked-value seam.

use std::num::NonZeroU64;

use openwiz_adapter_github::tickets::issue;
use openwiz_core::fleet::model::{Outcome, Read, ReadId, ReadKind};
use openwiz_core::fleet::tickets::{Records, Requires, needs_you};
use serde_json::{Value, json};

fn comment(body: &str, time: &str, suffix: &str) -> Value {
    json!({
        "id": format!("synthetic-comment-{suffix}"),
        "author": {"login": "synthetic-owner"},
        "authorAssociation": "OWNER", "body": body, "createdAt": time,
        "includesCreatedEdit": false, "isMinimized": false,
        "minimizedReason": "", "reactionGroups": [],
        "url": format!("https://example.invalid/synthetic/issues/902#issuecomment-{suffix}"),
        "viewerDidAuthor": true
    })
}

fn issue_document(labels: &[&str], comments: Vec<Value>) -> Value {
    json!({
        "blockedBy": {"nodes": [], "totalCount": 0},
        "body": "Synthetic ticket body mentions live release publish, never a question source.",
        "closedByPullRequestsReferences": [], "comments": comments,
        "labels": labels.iter().map(|label| json!({
            "color": "ededed", "description": "Synthetic label", "id": label, "name": label
        })).collect::<Vec<_>>(),
        "milestone": null, "state": "OPEN",
        "subIssues": {"nodes": [], "totalCount": 0},
        "title": "Synthetic live release publish title"
    })
}

fn item(document: Value) -> Value {
    let answer = issue(document.to_string().as_bytes()).expect("read synthetic issue comments");
    let number = NonZeroU64::new(902).unwrap();
    let reads = [Read {
        id: ReadId(1),
        kind: ReadKind::Issue {
            issue: number,
            outcome: Outcome::Complete {
                value: answer.issue,
            },
        },
    }];
    let items = needs_you(
        &Records::new(&reads),
        &Requires::new(),
        &[(NonZeroU64::new(901).unwrap(), number, ReadId(1))],
    );
    let value = serde_json::to_value(items).unwrap();
    let items = value["known"].as_array().expect("known Needs you list");
    assert_eq!(items.len(), 1);
    items[0].clone()
}

fn unknown(value: &Value) {
    assert!(
        value["unknown"]
            .as_str()
            .is_some_and(|why| !why.trim().is_empty()),
        "expected explicit unknown, got {value}"
    );
}

#[test]
fn c10_question_fact_contracts_preserve_all_original_cases() {
    let cases: [(&str, fn()); 10] = [
        (
            "c10_comment_metadata_types_are_not_silently_accepted",
            c10_comment_metadata_types_are_not_silently_accepted,
        ),
        (
            "c10_comment_wire_shapes_fail_closed",
            c10_comment_wire_shapes_fail_closed,
        ),
        (
            "c10_equal_newest_comment_times_leave_ambiguous_question_unknown",
            c10_equal_newest_comment_times_leave_ambiguous_question_unknown,
        ),
        (
            "c10_missing_question_and_missing_risk_are_independently_unknown",
            c10_missing_question_and_missing_risk_are_independently_unknown,
        ),
        (
            "c10_more_than_one_hundred_comments_still_give_the_newest_question",
            c10_more_than_one_hundred_comments_still_give_the_newest_question,
        ),
        (
            "c10_newest_marked_comment_supplies_exact_first_line_link_and_asked_time",
            c10_newest_marked_comment_supplies_exact_first_line_link_and_asked_time,
        ),
        (
            "c10_risk_requires_one_exact_label_never_words_or_conflicting_labels",
            c10_risk_requires_one_exact_label_never_words_or_conflicting_labels,
        ),
        (
            "c10_schema_accepts_closed_known_and_unknown_question_facts",
            c10_schema_accepts_closed_known_and_unknown_question_facts,
        ),
        (
            "c10_unmarked_comments_never_become_question_wording",
            c10_unmarked_comments_never_become_question_wording,
        ),
        (
            "c10_unminimized_comment_with_a_null_reason_is_read",
            c10_unminimized_comment_with_a_null_reason_is_read,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: c10_questions::{name}");
        proof();
    }
}

fn c10_newest_marked_comment_supplies_exact_first_line_link_and_asked_time() {
    let older = comment(
        "needs-you: Old proposal\nOld detail",
        "2023-11-14T22:13:20Z",
        "1",
    );
    let newest = comment(
        "Needs you: Choose synthetic option B\nDetails stay out of wording",
        "2023-11-14T22:14:20Z",
        "2",
    );
    let later_unmarked = comment("Unrelated note", "2023-11-14T22:15:20Z", "3");
    for comments in [
        vec![older.clone(), newest.clone(), later_unmarked.clone()],
        vec![later_unmarked, newest, older],
    ] {
        let need = item(issue_document(&["needs-info", "live"], comments));
        assert_eq!(
            need["wording"],
            json!({"known": "Needs you: Choose synthetic option B"})
        );
        assert_eq!(
            need["link"],
            json!({"known": "https://example.invalid/synthetic/issues/902#issuecomment-2"})
        );
        assert_eq!(need["asked_at"], json!({"known": 1_700_000_060_000_i64}));
        assert_eq!(need["risk"], json!({"known": "live"}));
    }
}

fn c10_missing_question_and_missing_risk_are_independently_unknown() {
    let no_question = item(issue_document(&["needs-info", "release"], vec![]));
    for key in ["wording", "link", "asked_at"] {
        unknown(&no_question[key]);
    }
    assert_eq!(no_question["risk"], json!({"known": "release"}));
    let no_risk = item(issue_document(
        &["needs-info"],
        vec![comment(
            "needs-you: Is this live release publish?",
            "2023-11-14T22:13:20Z",
            "1",
        )],
    ));
    assert_eq!(
        no_risk["wording"]["known"],
        "needs-you: Is this live release publish?"
    );
    unknown(&no_risk["risk"]);
}

fn c10_risk_requires_one_exact_label_never_words_or_conflicting_labels() {
    for risk in ["live", "release", "publish"] {
        let need = item(issue_document(&["held", risk], vec![]));
        assert_eq!(need["risk"], json!({"known": risk}));
    }
    for labels in [
        vec!["needs-info"],
        vec!["held", "Live"],
        vec!["needs-info", "live-ish"],
        vec!["held", "live", "release"],
        vec!["held", "publish", "release"],
    ] {
        let need = item(issue_document(
            &labels,
            vec![comment(
                "Needs you: live release publish",
                "2023-11-14T22:13:20Z",
                "1",
            )],
        ));
        unknown(&need["risk"]);
    }
}

fn c10_unmarked_comments_never_become_question_wording() {
    for body in [
        "unmarked",
        "Detail\nNeeds you: Not the first line",
        "NEEDS YOU: wrong case",
    ] {
        let need = item(issue_document(
            &["held"],
            vec![comment(body, "2023-11-14T22:13:20Z", "1")],
        ));
        for key in ["wording", "link", "asked_at", "risk"] {
            unknown(&need[key]);
        }
    }
}

fn c10_equal_newest_comment_times_leave_ambiguous_question_unknown() {
    let need = item(issue_document(
        &["held"],
        vec![
            comment("needs-you: Option A", "2023-11-14T22:13:20Z", "1"),
            comment("Needs you: Option B", "2023-11-14T22:13:20Z", "2"),
        ],
    ));
    for key in ["wording", "link", "asked_at"] {
        unknown(&need[key]);
    }
}

fn c10_schema_accepts_closed_known_and_unknown_question_facts() {
    let mut schema = crate::schema::load_schema();
    schema["$ref"] = json!("#/$defs/needs_you");
    let known = json!({
        "kind": "needs_info", "spec": 901, "ticket": 902,
        "wording": {"known": "Needs you: Synthetic question"},
        "link": {"known": "https://example.invalid/synthetic/issues/902#issuecomment-1"},
        "asked_at": {"known": 1_700_000_000_000_i64},
        "risk": {"known": "live"}
    });
    assert_eq!(
        crate::schema::validate(&schema, &known),
        Vec::<String>::new()
    );
    let mut unknowns = known.clone();
    for key in ["wording", "link", "asked_at", "risk"] {
        unknowns[key] = json!({"unknown": "synthetic source did not report this fact"});
    }
    assert_eq!(
        crate::schema::validate(&schema, &unknowns),
        Vec::<String>::new()
    );
    for key in ["wording", "link", "asked_at", "risk"] {
        let mut missing = known.clone();
        missing.as_object_mut().unwrap().remove(key);
        assert!(
            !crate::schema::validate(&schema, &missing).is_empty(),
            "missing {key}"
        );
        let mut positional = known.clone();
        positional[key] = json!(["live"]);
        assert!(
            !crate::schema::validate(&schema, &positional).is_empty(),
            "positional {key}"
        );
        let mut extra = known.clone();
        extra[key]["extra"] = json!(true);
        assert!(
            !crate::schema::validate(&schema, &extra).is_empty(),
            "extra {key}"
        );
    }
    for bad in [
        json!(false),
        json!("Live"),
        json!({"live": null}),
        json!("safe"),
    ] {
        let mut invalid = known.clone();
        invalid["risk"]["known"] = bad;
        assert!(!crate::schema::validate(&schema, &invalid).is_empty());
    }
    for bad in [json!(""), json!(42), Value::Null] {
        let mut invalid = known.clone();
        invalid["wording"]["known"] = bad;
        assert!(!crate::schema::validate(&schema, &invalid).is_empty());
    }
}

#[test]
fn c10_detail_reads_comment_facts_and_the_fleets_list_keeps_its_query() {
    use crate::support::FakeGh;
    use openwiz_adapter_github::fleets::GitHubFleets;
    use openwiz_adapter_github::tickets::{ISSUE_FIELDS, Tickets};
    use openwiz_core::fleet::fleets::fleets;
    use openwiz_core::fleet::tickets::{FleetRequest, NotRead, TestedVersions, fleet};
    use openwiz_core::model::Timestamp;
    use openwiz_core::ops::Clock;
    use std::fs;
    use std::path::Path;
    use std::time::Duration;
    use std::time::Instant;
    struct SourceClock;
    impl Clock for SourceClock {
        fn now(&self) -> Timestamp {
            Timestamp(1_700_000_600_000)
        }
        fn monotonic(&self) -> Instant {
            Instant::now()
        }
    }

    let question = comment(
        "Needs you: Choose synthetic option B\nPrivate synthetic detail",
        "2023-11-14T22:14:20Z",
        "2",
    );
    let ticket_doc = issue_document(&["needs-info", "live"], vec![question.clone()]);
    let mut spec_doc = issue_document(&[], vec![]);
    spec_doc["subIssues"] = json!({"nodes": [{"id": "synthetic-issue-902", "number": 902,
        "state": "OPEN", "title": "Synthetic ticket", "url": "https://example.invalid/synthetic/issues/902"}], "totalCount": 1});
    let detailed_scenario = json!({"scenario": "c10-detail-comments", "synthetic_assumptions": ["Every value is synthetic"], "responses": [
        {"argv": ["--version"], "stdout": "gh version 2.100.0 (2026-09-03)\n"},
        {"argv": ["repo", "view", "--json", "nameWithOwner,url"], "stdout": "{\"nameWithOwner\":\"synthetic-owner/example-repo\",\"url\":\"https://example.invalid/synthetic\"}"},
        {"argv": ["issue", "view", "901", "--json", ISSUE_FIELDS], "stdout": spec_doc.to_string()},
        {"argv": ["issue", "view", "902", "--json", ISSUE_FIELDS], "stdout": ticket_doc.to_string()}
    ]});
    let detail_path = Path::new(env!("CARGO_TARGET_TMPDIR")).join("c10-detail-sources.json");
    fs::write(&detail_path, detailed_scenario.to_string()).unwrap();
    let detailed_fake = FakeGh::new("c10-detail-comments", &detail_path);
    let detail = serde_json::to_value(fleet(
        FleetRequest {
            spec: NonZeroU64::new(901).unwrap(),
        },
        &Tickets::new(detailed_fake.program()),
        &NotRead,
        TestedVersions {
            github: "2.100.0",
            cloudroom: "v127",
        },
        &SourceClock,
        Duration::from_secs(30),
    ))
    .unwrap();
    assert_eq!(
        detailed_fake.invocations().len(),
        4,
        "only the four GitHub reads"
    );

    let list_args = [
        "issue",
        "list",
        "--state",
        "all",
        "--limit",
        "1000",
        "--json",
        "blockedBy,body,id,labels,milestone,number,state,subIssues,title",
    ];
    // The repository-wide list reads no comments (#539: with them, the live
    // list took 46 s against the 30 s run budget), so its rows carry none.
    let mut row = issue_document(&["needs-info", "live"], vec![]);
    for key in ["closedByPullRequestsReferences", "comments"] {
        row.as_object_mut().unwrap().remove(key);
    }
    row["id"] = json!("synthetic-issue-902");
    row["number"] = json!(902);
    let mut spec = row.clone();
    spec["id"] = json!("synthetic-issue-901");
    spec["number"] = json!(901);
    spec["labels"] = json!([]);
    spec["subIssues"] = json!({"nodes": [{"id": "synthetic-issue-902", "number": 902,
        "state": "OPEN", "title": "Synthetic ticket", "url": "https://example.invalid/synthetic/issues/902"}], "totalCount": 1});
    let scenario = json!({"scenario": "c10-comment-sources", "synthetic_assumptions": [
        "All values and the explicit pending-question/risk cases are synthetic; no live behavior is claimed."
    ], "responses": [
        {"argv": ["--version"], "stdout": "gh version 2.100.0 (2026-09-03)\n"},
        {"argv": ["repo", "view", "--json", "nameWithOwner"], "stdout": "{\"nameWithOwner\":\"synthetic-owner/example-repo\"}"},
        {"argv": list_args, "stdout": json!([spec, row]).to_string()},
        {"argv": ["pr", "list", "--state", "all", "--limit", "1000", "--json",
            "baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state,title"], "stdout": "[]"}
    ]});
    let path = Path::new(env!("CARGO_TARGET_TMPDIR")).join("c10-comment-sources.json");
    fs::write(&path, scenario.to_string()).unwrap();
    let fake = FakeGh::new("c10-list-comments", &path);
    let listed = serde_json::to_value(fleets(
        &GitHubFleets::with_program(fake.program()),
        &SourceClock,
        Duration::from_secs(30),
    ))
    .unwrap();
    assert_eq!(fake.invocations().len(), 4, "no read was added to fleets");
    let not_read =
        "the fleets view does not read comments; openwiz fleet <spec> reads the question";
    let expected = [
        json!({"known": [{"kind": "needs_info", "spec": 901, "ticket": 902,
            "wording": {"known": "Needs you: Choose synthetic option B"},
            "link": {"known": "https://example.invalid/synthetic/issues/902#issuecomment-2"},
            "asked_at": {"known": 1_700_000_060_000_i64}, "risk": {"known": "live"}
        }]}),
        json!({"known": [{"kind": "needs_info", "spec": 901, "ticket": 902,
            "wording": {"unknown": not_read}, "link": {"unknown": not_read},
            "asked_at": {"unknown": not_read}, "risk": {"known": "live"}
        }]}),
    ];
    for (envelope, expected) in [detail, listed].into_iter().zip(expected) {
        assert_eq!(envelope["data"]["needs_you"], expected);
        assert_eq!(
            crate::schema::validate(&crate::schema::load_schema(), &envelope),
            Vec::<String>::new()
        );
        assert!(
            !envelope.to_string().contains("Private synthetic detail"),
            "comment bodies are not exposed"
        );
    }
}

fn c10_more_than_one_hundred_comments_still_give_the_newest_question() {
    // `gh issue view --json comments` pages through every comment: #325's
    // view returned 148 (a count-only live read, 2026-11-06). So no page
    // boundary hides the newest one, and a busy ticket keeps its question.
    let mut comments: Vec<_> = (0..140)
        .map(|n| {
            comment(
                "Synthetic unmarked note",
                "2023-11-14T22:13:20Z",
                &n.to_string(),
            )
        })
        .collect();
    comments.insert(
        70,
        comment("Needs you: Synthetic option", "2023-11-14T22:14:20Z", "q"),
    );
    let need = item(issue_document(&["held", "live"], comments));
    assert_eq!(
        need["wording"],
        json!({"known": "Needs you: Synthetic option"})
    );
    assert_eq!(need["asked_at"], json!({"known": 1_700_000_060_000_i64}));
    assert_eq!(need["risk"], json!({"known": "live"}));
}

fn c10_unminimized_comment_with_a_null_reason_is_read() {
    let mut minimized = comment("Needs you: Synthetic question", "2023-11-14T22:13:20Z", "1");
    minimized["minimizedReason"] = Value::Null;
    let need = item(issue_document(&["held"], vec![minimized]));
    assert_eq!(
        need["wording"],
        json!({"known": "Needs you: Synthetic question"})
    );
}

fn c10_comment_wire_shapes_fail_closed() {
    let good = issue_document(
        &["held"],
        vec![comment(
            "Needs you: Synthetic question",
            "2023-11-14T22:13:20Z",
            "1",
        )],
    );
    let keys: Vec<_> = good["comments"][0]
        .as_object()
        .unwrap()
        .keys()
        .cloned()
        .collect();
    for key in keys {
        let mut missing = good.clone();
        missing["comments"][0].as_object_mut().unwrap().remove(&key);
        assert!(
            issue(missing.to_string().as_bytes()).is_err(),
            "missing comment key {key}"
        );
    }
    for bad in [json!([]), json!({"body": "Needs you: Synthetic question"})] {
        let mut invalid = good.clone();
        invalid["comments"][0] = bad;
        assert!(issue(invalid.to_string().as_bytes()).is_err());
    }
    for (field, value) in [
        ("body", json!(42)),
        ("url", json!("")),
        ("createdAt", json!(42)),
        ("createdAt", json!("invalid")),
        ("extra", json!(true)),
    ] {
        let mut invalid = good.clone();
        invalid["comments"][0][field] = value;
        assert!(
            issue(invalid.to_string().as_bytes()).is_err(),
            "bad {field}"
        );
    }
    let duplicate = good.to_string().replace(
        "\"body\":\"Needs you: Synthetic question\"",
        "\"body\":\"Needs you: Synthetic question\",\"body\":\"Needs you: Synthetic question\"",
    );
    assert!(issue(duplicate.as_bytes()).is_err(), "repeated comment key");
}

fn c10_comment_metadata_types_are_not_silently_accepted() {
    let good = issue_document(
        &["held"],
        vec![comment(
            "Needs you: Synthetic question",
            "2023-11-14T22:13:20Z",
            "1",
        )],
    );
    for (field, value) in [
        ("id", json!(42)),
        ("author", json!(42)),
        ("authorAssociation", json!(false)),
        ("includesCreatedEdit", json!([])),
        ("isMinimized", json!("false")),
        ("minimizedReason", json!({})),
        ("reactionGroups", Value::Null),
        ("viewerDidAuthor", json!(0)),
    ] {
        let mut invalid = good.clone();
        invalid["comments"][0][field] = value;
        assert!(
            issue(invalid.to_string().as_bytes()).is_err(),
            "mistyped comment metadata {field} must fail closed"
        );
    }
}
