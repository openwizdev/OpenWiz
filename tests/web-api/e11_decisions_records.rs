//! EP3: records returned through HTTP over the actual adapter and fake gh.
use crate::{e11_decisions_support as s, fake::Fake};

/// Numeric repository links are an observed GitHub shape; all identifiers,
/// comments and proposal wording in this two-comment fixture are synthetic.
#[test]
fn e11_decisions_numeric_repository_links_preserve_pending_comments() {
    let request = s::record("synthetic-current", "open");
    let gh = s::fake(
        "e11_numeric_links_gh",
        vec![
            s::comment(1001, &s::fenced(&request)),
            s::comment(1002, "Synthetic unrelated comment"),
        ],
    );
    s::change(&gh, |scenario| {
        for response in scenario["responses"].as_array_mut().unwrap() {
            if response["argv"][1] == "--include" {
                response["stdout"] = json!(response["stdout"].as_str().unwrap().replace(
                    "https://api.github.com/repos/synthetic-owner/synthetic-repo/issues/comments?",
                    "https://api.github.com/repositories/9001/issues/comments?",
                ));
            }
        }
    });
    let room = Fake::new("e11_numeric_links_room", "normal");
    let response = s::serve(&gh, &room).get("/api/v1/decisions");
    assert_eq!(response.status, 200);
    let body = response.json();
    s::check(&body);
    assert_eq!(body["items"].as_array().unwrap().len(), 1, "{body}");
    assert_eq!(body["items"][0]["comment_id"], 1001);
    assert_eq!(body["items"][0]["request"], request);
    // Pagination does not establish independent saved-source currentness.
    assert_eq!(
        body["items"][0]["current"],
        json!({"unknown":"independent saved proposal verification is unavailable"})
    );
    assert_eq!(
        body["coverage"]["gaps"],
        json!([{"kind":"unsupported","detail":"independent saved proposal verification is unavailable"}])
    );
    assert!(room.invocations().is_empty());
}

#[test]
fn e11_decisions_numeric_links_keep_url_query_relation_and_count_guards() {
    use openwiz_adapter_github::decisions::GitHubDecisions;
    use openwiz_core::source::SourceError;
    use std::time::{Duration, Instant};

    let root = "https://api.github.com/repositories/9001/issues/comments?";
    let link = format!("<{root}per_page=1&sort=created&direction=desc&page=2>; rel=\"last\"");
    let mut bad: Vec<String> = [
        "http://api.github.com/repositories/9001/issues/comments?",
        "https://example.invalid/repositories/9001/issues/comments?",
        "https://api.github.com.example.invalid/repositories/9001/issues/comments?",
        concat!(
            "https://user",
            "@api.github.com/repositories/9001/issues/comments?"
        ),
        "https://api.github.com:443/repositories/9001/issues/comments?",
        "https://api.github.com/repositories//issues/comments?",
        "https://api.github.com/repositories/0/issues/comments?",
        "https://api.github.com/repositories/09001/issues/comments?",
        "https://api.github.com/repositories/-1/issues/comments?",
        "https://api.github.com/repositories/+1/issues/comments?",
        "https://api.github.com/repositories/١/issues/comments?",
        "https://api.github.com/repositories/%31/issues/comments?",
        "https://api.github.com/repositories/18446744073709551616/issues/comments?",
        "https://api.github.com/repositories/9001/pulls/comments?",
        "https://api.github.com/repositories/9001/issues/comments/extra?",
        "https://api.github.com/repositories/9001/issues/comments/?",
        "https://api.github.com/repos/synthetic-owner/other-repo/issues/comments?",
    ]
    .into_iter()
    .map(|url| format!("Link: {}", link.replace(root, url)))
    .collect();
    for (from, to) in [
        ("per_page=1", "per_page=100"),
        ("per_page=1&", ""),
        ("sort=created", "sort=updated"),
        ("direction=desc", "direction=asc"),
        ("page=2", "page=0"),
        ("page=2", "page=02"),
        ("page=2", "page=١"),
        ("page=2", "page=18446744073709551616"),
        ("page=2", "page=2#fragment"),
        ("page=2", "page=2&extra=1"),
        ("page=2", "page=2&page=2"),
        ("rel=\"last\"", "rel=\"other\""),
        // Valid page numbers with inconsistent count/body metadata.
        ("page=2", "page=1"),
        ("page=2", "page=3"),
    ] {
        bad.push(format!("Link: {}", link.replace(from, to)));
    }
    bad.extend([
        format!("Link: {link}, {link}"),
        format!("Link: {link}\r\nLink: {link}"),
        // A valid last relation must not hide a malformed next relation.
        format!(
            "Link: {link}, {}",
            link.replace("9001", "0").replace("last", "next")
        ),
    ]);
    let good = format!("Link: {}, {link}", link.replace("last", "next"));
    for (index, header) in bad.iter().chain(std::iter::once(&good)).enumerate() {
        let gh = s::fake(
            &format!("e11_numeric_guard_{index}"),
            vec![
                s::comment(1001, "Synthetic first"),
                s::comment(1002, "Synthetic second"),
            ],
        );
        s::change(&gh, |scenario| {
            scenario["responses"][1]["stdout"] = json!(format!(
                "HTTP/2.0 200 OK\r\n{header}\r\n\r\n{}",
                json!([s::comment(1001, "Synthetic first")])
            ));
        });
        let read = GitHubDecisions::with_program(gh.program())
            .read(Instant::now() + Duration::from_secs(5));
        if index == bad.len() {
            assert!(read.snapshot_complete, "{header}: {:?}", read.errors);
            assert!(read.errors.is_empty());
            assert_eq!(
                read.comments.iter().map(|c| c.id).collect::<Vec<_>>(),
                [1001, 1002]
            );
        } else {
            assert!(!read.snapshot_complete, "{header}");
            assert!(read.comments.is_empty(), "{header}");
            assert!(
                matches!(read.errors.as_slice(), [SourceError::Malformed { .. }]),
                "{header}: {:?}",
                read.errors
            );
        }
    }
}

#[test]
fn e11_decisions_candidate_and_record_refusals_are_explicit_gaps() {
    let good = s::record("synthetic-bad", "open");
    let wire = good.to_string();
    let mut cases = vec![
        (
            "escaped-unfenced",
            r#"{"schema":"\u006fpenwiz.decisions.v1"}"#.to_owned(),
        ),
        (
            "unsupported",
            s::fenced(&json!({"schema":"openwiz.decisions.v2"})),
        ),
        (
            "duplicate-key",
            format!(
                "```json\n{}\n```",
                wire.replacen(
                    "\"risk\":\"ordinary\"",
                    "\"risk\":\"ordinary\",\"risk\":\"ordinary\"",
                    1
                )
            ),
        ),
        (
            "fractional-round",
            format!(
                "```json\n{}\n```",
                wire.replace("\"round\":1", "\"round\":1.0")
            ),
        ),
        (
            "multiple-fences",
            format!("{}\n```json\n{{}}\n```", s::fenced(&good)),
        ),
        (
            "unclosed-fence",
            "```json\n{\"unrelated\":\"\\u006f".to_owned(),
        ),
        (
            "bad-escape",
            "```json\n{\"unrelated\":\"bad\\q\\u006f\"}\n```".to_owned(),
        ),
        ("indented-fence", format!(" ```json\n{wire}\n```")),
        (
            "response-envelope",
            s::fenced(&json!({"schema":"openwiz.decisions.v1","kind":"response"})),
        ),
    ];
    for (label, key, value) in [
        ("extra", "extra", json!(true)),
        ("tagged-risk", "risk", json!({"ordinary":null})),
        ("bad-id", "id", json!("-bad")),
        ("bad-fingerprint", "fingerprint", json!("A".repeat(64))),
        (
            "traversal",
            "grill_file",
            json!("docs/grills/../../secret.md"),
        ),
        ("string-round", "round", json!("1")),
        ("missing-questions", "questions", json!([])),
        ("unknown-answer", "answered", json!(["G2"])),
        ("open-all-answered", "answered", json!(["G1"])),
    ] {
        let mut record = good.clone();
        record[key] = value;
        cases.push((label, s::fenced(&record)));
    }
    let mut missing = good.clone();
    missing.as_object_mut().unwrap().remove("risk");
    cases.push(("missing-risk", s::fenced(&missing)));
    let mut bad_question = good.clone();
    bad_question["questions"][0]["id"] = json!("G0");
    cases.push(("bad-question-id", s::fenced(&bad_question)));
    let mut duplicate_question = good.clone();
    duplicate_question["questions"] = json!([good["questions"][0], good["questions"][0]]);
    cases.push(("duplicate-question", s::fenced(&duplicate_question)));
    for (index, (label, body)) in cases.into_iter().enumerate() {
        let room = Fake::new(&format!("e11_bad_room_{index}"), "normal");
        let gh = s::fake(
            &format!("e11_bad_gh_{index}"),
            vec![s::comment(1001, &body)],
        );
        let server = s::serve(&gh, &room);
        let response = server.get("/api/v1/decisions");
        assert_eq!(response.status, 200, "{label}");
        let value = response.json();
        assert_eq!(value["items"], json!([]), "{label}: {value}");
        assert_eq!(value["coverage"]["state"], "partial", "{label}: {value}");
        assert_eq!(
            value["coverage"]["gaps"].as_array().unwrap().len(),
            1,
            "{label}: {value}"
        );
        assert_eq!(
            value["coverage"]["gaps"][0]["kind"], "malformed",
            "{label}: {value}"
        );
    }
}

#[test]
fn e11_decisions_non_ascii_timestamp_is_reported_without_panicking() {
    let mut row = s::comment(1001, &s::fenced(&s::record("synthetic-date", "open")));
    row["created_at"] = json!("é0é-01-01T00:00:01Z");
    let gh = s::fake("e11_unicode_date", vec![row]);
    let read = openwiz_adapter_github::decisions::GitHubDecisions::with_program(gh.program())
        .read(std::time::Instant::now() + std::time::Duration::from_secs(5));
    assert!(read.comments.is_empty());
    assert_eq!(read.errors.len(), 1);
}
use serde_json::json;

#[test]
fn e11_decisions_invalid_proposal_fingerprint_is_omitted_as_malformed() {
    let room = Fake::new("e11_bad_hash_open_room", "normal");
    let mut record = s::record("synthetic-current", "open");
    record["fingerprint"] = json!("0".repeat(64));
    let gh = s::fake(
        "e11_bad_hash_open_gh",
        vec![s::comment(1001, &s::fenced(&record))],
    );
    let value = s::serve(&gh, &room).get("/api/v1/decisions").json();
    s::check(&value);
    assert_eq!(value["items"], json!([]), "{value}");
    assert_eq!(
        value["coverage"]["gaps"],
        json!([{"kind":"malformed","detail":"decision fingerprint does not bind its proposal"}])
    );
}

#[test]
fn e11_decisions_invalid_proposal_fingerprint_is_reported_before_closed_filtering() {
    for status in ["resolved", "superseded"] {
        let room = Fake::new(&format!("e11_bad_hash_{status}_room"), "normal");
        let mut record = s::record("synthetic-current", status);
        record["fingerprint"] = json!("0".repeat(64));
        let gh = s::fake(
            &format!("e11_bad_hash_{status}_gh"),
            vec![s::comment(1001, &s::fenced(&record))],
        );
        let value = s::serve(&gh, &room).get("/api/v1/decisions").json();
        s::check(&value);
        assert_eq!(value["items"], json!([]));
        assert_eq!(
            value["coverage"]["gaps"],
            json!([{"kind":"malformed","detail":"decision fingerprint does not bind its proposal"}]),
            "{status}: {value}"
        );
    }
}

#[test]
fn e11_decisions_wrong_subject_is_reported_in_every_lifecycle_state() {
    for status in ["open", "resolved", "superseded"] {
        let room = Fake::new(&format!("e11_subject_{status}_room"), "normal");
        let record = s::record("synthetic-current", status);
        let gh = s::fake(
            &format!("e11_subject_{status}_gh"),
            vec![s::comment(1001, &s::fenced(&record))],
        );
        s::change(&gh, |scenario| {
            let row = scenario["responses"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|r| r["argv"][1] == "repos/{owner}/{repo}/issues/901")
                .unwrap();
            row["stdout"] = json!(
                "{\"number\":901,\"body\":\"Synthetic issue rather than a grill PR\",\"is_pull_request\":false}"
            );
        });
        let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
        s::check(&body);
        assert_eq!(body["items"], json!([]));
        assert_eq!(
            body["coverage"]["gaps"],
            json!([{"kind":"malformed","detail":"decision request is on the wrong subject"}]),
            "{status}: {body}"
        );
    }
}

#[test]
fn e11_decisions_open_returned_answered_omitted_malformed_reported() {
    let room = Fake::new("e11_records_room", "normal");
    let open = s::record("synthetic-open", "open");
    let rows = vec![
        s::comment(1001, &s::fenced(&open)),
        s::comment(
            1002,
            &s::fenced(&s::record("synthetic-answered", "resolved")),
        ),
        s::comment(
            1003,
            "```json\n{\"schema\":\"openwiz.decisions.v1\",\"kind\":false}\n```",
        ),
    ];
    let gh = s::fake("e11_mixed_records", rows);
    let server = s::serve(&gh, &room);
    let response = server.get("/api/v1/decisions");
    assert_eq!(response.status, 200, "{}", response.text());
    let body = response.json();
    s::check(&body);
    assert_eq!(body["items"].as_array().unwrap().len(), 1, "{body}");
    assert_eq!(body["items"][0]["request"], open);
    assert_eq!(
        body["items"][0]["subject"],
        json!({"repository":"synthetic-owner/synthetic-repo","kind":"pull_request","number":901})
    );
    assert_eq!(body["items"][0]["created_at"], 1000);
    assert_eq!(body["items"][0]["updated_at"], 2000);
    assert_eq!(body["coverage"]["state"], "partial");
    assert!(
        body["coverage"]["gaps"]
            .as_array()
            .unwrap()
            .iter()
            .any(|g| g["kind"] == "malformed")
    );
    assert_eq!(body["freshness"]["state"], "unknown");
    assert_eq!(body["coverage"]["gaps"].as_array().unwrap().len(), 2);
    assert_eq!(body["orchestrator"]["target"], json!({"known":null}));
    assert_eq!(
        body["orchestrator"]["coverage"],
        json!({"state":"complete","gaps":[]})
    );
    assert_eq!(
        gh.invocations(),
        vec![
            vec!["repo", "view", "--json", "nameWithOwner"]
                .into_iter()
                .map(str::to_owned)
                .collect(),
            s::argv(1, 1),
            s::argv(1, 100),
            vec![
                "api",
                "repos/{owner}/{repo}/issues/901",
                "--jq",
                "{number,body,is_pull_request:has(\"pull_request\")}"
            ]
            .into_iter()
            .map(str::to_owned)
            .collect(),
            serde_json::from_value(s::grill_head_argv()).unwrap(),
            serde_json::from_value(s::grill_blob_argv()).unwrap(),
            s::argv(1, 1),
            s::argv(1, 1),
            s::argv(1, 100),
            s::argv(1, 1),
        ]
    );
    assert!(room.invocations().is_empty());
}

#[test]
fn e11_decisions_paginates_the_entire_feed_and_retains_rows_after_a_page_failure() {
    let mut rows: Vec<_> = (0..101)
        .map(|i| s::comment(1001 + i, "Synthetic ordinary conversation."))
        .collect();
    rows[0] = s::comment(1001, &s::fenced(&s::record("synthetic-first", "open")));
    rows[100] = s::comment(1101, &s::fenced(&s::record("synthetic-last", "open")));
    for failed in [false, true] {
        let room = Fake::new(&format!("e11_pages_room_{failed}"), "normal");
        let gh = s::fake(&format!("e11_pages_gh_{failed}"), rows.clone());
        if failed {
            s::change(&gh, |scenario| {
                scenario["responses"]
                    .as_array_mut()
                    .unwrap()
                    .retain(|r| r["argv"] != json!(s::argv(2, 100)));
            });
        }
        let server = s::serve(&gh, &room);
        let response = server.get("/api/v1/decisions");
        let value = response.json();
        s::check(&value);
        let ids: Vec<_> = value["items"]
            .as_array()
            .unwrap()
            .iter()
            .map(|i| i["comment_id"].as_u64().unwrap())
            .collect();
        assert_eq!(ids, if failed { vec![1001] } else { vec![1001, 1101] });
        assert_eq!(value["freshness"]["state"], "unknown");
        let calls = gh.invocations();
        assert_eq!(
            calls
                .iter()
                .filter(|args| **args == s::argv(2, 100))
                .count(),
            if failed { 1 } else { 2 },
            "{calls:?}"
        );
        assert_eq!(
            calls.iter().filter(|args| **args == s::argv(1, 1)).count(),
            if failed { 1 } else { 4 }
        );
        if failed {
            assert!(
                value["coverage"]["gaps"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .any(|g| g["kind"] == "command_failed")
            );
        }
    }
}

#[test]
fn e11_decisions_duplicate_request_ids_never_select_a_winner() {
    let room = Fake::new("e11_duplicates_room", "normal");
    let record = s::record("synthetic-duplicate", "open");
    let gh = s::fake(
        "e11_duplicates_gh",
        vec![
            s::comment(1001, &s::fenced(&record)),
            s::comment(1002, &s::fenced(&record)),
        ],
    );
    let value = s::serve(&gh, &room).get("/api/v1/decisions").json();
    s::check(&value);
    assert_eq!(value["items"], json!([]));
    assert_eq!(value["coverage"]["state"], "partial");
    assert_eq!(value["coverage"]["gaps"].as_array().unwrap().len(), 2);
}

#[test]
fn e11_decisions_all_variants_and_partial_answer_progress_are_preserved() {
    let room = Fake::new("e11_variants_room", "normal");
    let mut round = s::record("synthetic-round", "open");
    round["questions"].as_array_mut().unwrap().push(json!({"id":"G2","decides":"Other choice?","context":"Exact context.","recommendation":"Keep it."}));
    round["answered"] = json!(["G1"]);
    round["fingerprint"] =
        json!("ab9b931ae7a67165e50281622cde4b3b3626698edbf236a2cdcfc8fa1f22a529");
    let grill = json!({"schema":"openwiz.decisions.v1","kind":"grill_confirmation","id":"synthetic-grill","status":"open","fingerprint":"e59aac30c5cea5f9b5b0cb8711575d928c670ebe8a70ee7ebdc53463161e58fd","risk":"live","grill_file":"docs/grills/synthetic-choice.md","summary":["Exact summary."]});
    let spec = json!({"schema":"openwiz.decisions.v1","kind":"spec_confirmation","id":"synthetic-spec","status":"open","fingerprint":"d25ef933277cd904bf4311991e9f9c422e2cb8a62ddd7567e9c3db13f6da55e3","risk":"release","spec":902,"summary":["Exact spec summary."],"headline":"Synthetic headline.","tickets":[],"graph":[]});
    let mut plan = spec.clone();
    plan["kind"] = json!("plan_approval");
    plan["id"] = json!("synthetic-plan");
    plan["risk"] = json!("publish");
    plan["tickets"] = json!([{"number":903,"title":"Synthetic ticket","blockers":[899]}]);
    plan["graph"] = json!([{"blocker":899,"ticket":903}]);
    let expected = [round, grill, spec, plan];
    let rows: Vec<_> = expected
        .iter()
        .enumerate()
        .map(|(i, r)| {
            let mut c = s::comment(1001 + i as u64, &s::fenced(r));
            if i >= 2 {
                c["issue_url"] =
                    json!("https://api.github.com/repos/synthetic-owner/synthetic-repo/issues/902");
            }
            c
        })
        .collect();
    let gh = s::fake("e11_variants_gh", rows);
    let value = s::serve(&gh, &room).get("/api/v1/decisions").json();
    s::check(&value);
    let actual: Vec<_> = value["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| i["request"].clone())
        .collect();
    assert_eq!(
        actual,
        vec![
            expected[2].clone(),
            expected[3].clone(),
            expected[0].clone(),
            expected[1].clone()
        ]
    );
    assert_eq!(
        value["items"][1]["current"],
        json!({"unknown":"independent saved proposal verification is unavailable"})
    );
}

#[test]
fn e11_decisions_matching_self_hash_does_not_verify_independent_saved_wording() {
    let room = Fake::new("e11_current_room", "normal");
    let mut record = s::record("synthetic-current", "open");
    // Independent Python hashlib over the literal canonical proposal, not
    // the production canonicalizer. Lifecycle fields are excluded.
    record["fingerprint"] =
        json!("941019e2a769a93d10140f9924b4ce021a041c21f74cd72514a9f51306ad1aa4");
    let gh = s::fake(
        "e11_current_gh",
        vec![s::comment(1001, &s::fenced(&record))],
    );
    let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
    s::check(&body);
    assert_eq!(body["items"].as_array().unwrap().len(), 1);
    assert_eq!(
        body["items"][0]["current"],
        json!({"unknown":"independent saved proposal verification is unavailable"})
    );
    assert_eq!(body["freshness"]["state"], "unknown");
    assert_eq!(
        body["coverage"]["gaps"],
        json!([{"kind":"unsupported","detail":"independent saved proposal verification is unavailable"}])
    );
}

#[test]
fn e11_decisions_schema_and_route_agree_on_parsed_shape_cases() {
    let good = s::record("synthetic-current", "open");
    let mut cases = vec![good.clone()];
    for (key, value) in [
        ("extra", json!(true)),
        ("risk", json!({"ordinary":null})),
        ("round", json!("1")),
        ("questions", json!([])),
        ("status", json!("done")),
        ("id", json!("")),
    ] {
        let mut bad = good.clone();
        bad[key] = value;
        cases.push(bad);
    }
    let mut missing = good.clone();
    missing.as_object_mut().unwrap().remove("risk");
    cases.push(missing);
    for (i, record) in cases.into_iter().enumerate() {
        let schema_accepts = s::schema_accepts(&record);
        assert_eq!(schema_accepts, i == 0, "contract fixture {i}");
        let room = Fake::new(&format!("e11_parity_{i}_room"), "normal");
        let gh = s::fake(
            &format!("e11_parity_{i}_gh"),
            vec![s::comment(1001, &s::fenced(&record))],
        );
        let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
        s::check(&body);
        assert_eq!(
            body["items"].as_array().unwrap().len(),
            usize::from(schema_accepts),
            "fixture {i}: {body}"
        );
    }
}

/// 2141: independent feeds may reuse every local identifier. A cwd-only read
/// misses both configured roles; global deduplication loses one valid request.
#[test]
fn e11_explicit_repository_pair_keeps_both_local_identities_and_partial_failures() {
    use openwiz_adapter_github::decisions::GitHubDecisions;
    use openwiz_server::Config;
    use std::sync::Arc;
    for mode in [
        "records",
        "empty",
        "public-unread",
        "private-unread",
        "wrong-visibility",
        "wrong-identity",
        "wrong-role",
        "bad-setting",
    ] {
        let room = Fake::new(&format!("e11_pair_room_{mode}"), "normal");
        let gh = s::fake(&format!("e11_pair_gh_{mode}"), vec![]);
        let settings = gh.dir.join("service-settings.json");
        let pair = json!({"decision_repositories":{
            "public":{"owner":"synthetic-public","name":"work"},
            "private":{"owner":"synthetic-records","name":"archive"}}});
        std::fs::write(
            &settings,
            if mode == "bad-setting" {
                "{bad json".to_owned()
            } else {
                pair.to_string()
            },
        )
        .unwrap();
        s::change(&gh, |scenario| {
            for (repo, private) in [
                ("synthetic-public/work", false),
                ("synthetic-records/archive", true),
            ] {
                let responses = scenario["responses"].as_array_mut().unwrap();
                let canonical = if mode == "wrong-identity" && private {
                    "synthetic-other/archive"
                } else {
                    repo
                };
                responses.push(json!({"argv":["repo","view",repo,"--json","nameWithOwner,isPrivate"],"stdout":json!({"nameWithOwner":canonical,"isPrivate":if mode == "wrong-visibility" {false} else {private}}).to_string()}));
                let private_kind = private != (mode == "wrong-role");
                let request = if private_kind {
                    s::record("synthetic-open", "open")
                } else {
                    json!({"schema":"openwiz.decisions.v1","kind":"plan_approval","id":"synthetic-open","status":"open","fingerprint":"a362c2cc752a0ee9f7be29ef3fdf2f29286ae9b8a2611e68515ffe8f51a4bf49","risk":"ordinary","spec":901,"summary":["Synthetic public plan."],"headline":"none","tickets":[],"graph":[]})
                };
                let mut row = s::comment(1001, &s::fenced(&request));
                row["issue_url"] = json!(format!("https://api.github.com/repos/{repo}/issues/901"));
                let rows = if matches!(mode, "empty" | "bad-setting") {
                    vec![]
                } else {
                    vec![row]
                };
                for size in [1, 100] {
                    let argv = s::argv(1, size)
                        .iter()
                        .map(|a| a.replace("{owner}/{repo}", repo))
                        .collect::<Vec<_>>();
                    responses.push(
                        if (mode == "public-unread" && !private)
                            || (mode == "private-unread" && private)
                        {
                            json!({"argv":argv,"exit":1,"stderr":"SYNTHETIC_PAIR_SECRET"})
                        } else {
                            json!({"argv":argv,"stdout":s::page(&rows,rows.len() as u64,size)})
                        },
                    );
                }
                responses.push(json!({"argv":["api",format!("repos/{repo}/issues/901"),"--jq","{number,body,is_pull_request:has(\"pull_request\")}"],"stdout":json!({"number":901,"body":"Synthetic source","is_pull_request":private_kind}).to_string()}));
            }
        });
        let server = s::serve_source(
            &room,
            Config::default(),
            Ok(None),
            Arc::new(crate::fake::clock()),
            GitHubDecisions::with_program(gh.program()).with_settings(&settings),
        );
        let response = server.get("/api/v1/decisions");
        let value = response.json();
        s::check(&value);
        assert_eq!(response.status, 200);
        if mode == "records" {
            assert_eq!(value["items"].as_array().unwrap().len(), 2, "{value}");
            let mut repositories = value["items"]
                .as_array()
                .unwrap()
                .iter()
                .map(|i| i["subject"]["repository"].as_str().unwrap())
                .collect::<Vec<_>>();
            repositories.sort();
            assert_eq!(
                repositories,
                ["synthetic-public/work", "synthetic-records/archive"]
            );
            assert!(
                value["coverage"]["gaps"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .all(|g| g["kind"] != "malformed"),
                "{value}"
            );
        } else if matches!(
            mode,
            "public-unread" | "private-unread" | "wrong-visibility" | "wrong-identity"
        ) {
            let items = value["items"].as_array().unwrap();
            assert_eq!(
                items.len(),
                1,
                "the healthy feed must survive: {mode}: {value}"
            );
            assert_eq!(
                items[0]["subject"]["repository"],
                if mode == "public-unread" {
                    "synthetic-records/archive"
                } else {
                    "synthetic-public/work"
                }
            );
            assert_eq!(value["coverage"]["state"], "partial");
            assert!(!value["coverage"]["gaps"].as_array().unwrap().is_empty());
        } else {
            assert_eq!(value["items"], json!([]), "{mode}: {value}");
            assert_eq!(
                value["coverage"]["state"],
                if mode == "empty" {
                    "complete"
                } else {
                    "partial"
                },
                "{mode}: {value}"
            );
        }
        assert!(!response.text().contains("SYNTHETIC_PAIR_SECRET"));
    }
}

pub(crate) const SAVED_ROUND: &str = "# Grill: synthetic choice (2099-01-01)\n\n## Round 1\nRisk: ordinary\n\n**G1 - Synthetic choice?** Exact context 合成.\n➡️ Keep spaces. \n\n**Robin:**\n> A synthetic reply.\n\nSettled: none. Open: G1.\n";

#[test]
fn e11_decisions_saved_wording_changes_are_known_false() {
    // These expectations come from literal independently saved human wording,
    // not a self-hash or a second copy of the request JSON.
    for (index, saved) in [
        SAVED_ROUND.replace("Synthetic choice?", "Changed choice?"),
        SAVED_ROUND.replace("合成.", "合成!"),
        SAVED_ROUND.replace("Keep spaces. ", "Keep spaces."),
        format!("{SAVED_ROUND}\n## Round 2\nRisk: ordinary\n\n**G1, re-asked - Simplified choice?** Exact context 合成.\n➡️ Keep spaces. \n"),
    ].into_iter().enumerate() {
        let room = Fake::new(&format!("e11_wording_room_{index}"), "normal");
        let record = s::record("synthetic-current", "open");
        let gh = s::fake(&format!("e11_wording_gh_{index}"), vec![s::comment(1001, &s::fenced(&record))]);
        s::saved_grill(&gh, &saved);
        let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
        s::check(&body);
        assert_eq!(body["items"].as_array().unwrap().len(), 1, "{body}");
        assert_eq!(body["items"][0]["current"], json!({"known":false}), "{index}: {body}");
        assert_eq!(body["items"][0]["request"], record);
        assert_eq!(body["coverage"]["state"], "complete", "{body}");
        assert_eq!(body["freshness"]["state"], "fresh");
        assert!(room.invocations().is_empty());
    }
}

#[test]
fn e11_decisions_matching_saved_words_without_risk_remain_unknown() {
    let room = Fake::new("e11_wording_risk_room", "normal");
    let record = s::record("synthetic-current", "open");
    let gh = s::fake(
        "e11_wording_risk_gh",
        vec![s::comment(1001, &s::fenced(&record))],
    );
    s::saved_grill(&gh, &SAVED_ROUND.replace("Risk: ordinary\n", ""));
    let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
    s::check(&body);
    assert_eq!(body["items"].as_array().unwrap().len(), 1, "{body}");
    assert_eq!(
        body["items"][0]["current"],
        json!({"unknown":"independent saved risk verification is unavailable"})
    );
    assert_eq!(
        body["coverage"]["gaps"],
        json!([{"kind":"unsupported","detail":"independent saved risk verification is unavailable"}])
    );
    assert_eq!(body["freshness"]["state"], "unknown");
    assert!(room.invocations().is_empty());
}

#[test]
fn e11_decisions_latest_saved_summary_is_compared_exactly() {
    let record = json!({"schema":"openwiz.decisions.v1","kind":"grill_confirmation","id":"synthetic-grill","status":"open","fingerprint":"e59aac30c5cea5f9b5b0cb8711575d928c670ebe8a70ee7ebdc53463161e58fd","risk":"live","grill_file":"docs/grills/synthetic-choice.md","summary":["Exact summary."]});
    let summary = "# Grill: synthetic\n\n## Summary (shown to Robin for confirmation)\nRisk: live\n\n1. Exact summary.\n";
    // Saving a reopened round precedes updating the still-open request comment.
    // Its unchanged summary must stop being current during that window.
    let reopened = format!(
        "{summary}\n**Robin:**\n> Reopen permissions before confirming.\n\n## Round 2\nRisk: ordinary\n\n**G2 - Which permissions?** Permissions remain undecided.\n➡️ Require explicit permission.\n"
    );
    for (index, (source, expected)) in [
        (summary.to_owned(), json!({"known":true})),
        (reopened.clone(), json!({"known":false})),
        (format!("{reopened}\n## Summary (shown to Robin for confirmation)\nRisk: live\n\n1. Exact summary.\n"), json!({"known":true})),
        (format!("{reopened}\n## Summary, corrected (shown to Robin for confirmation)\nRisk: live\n\n1. Exact summary.\n"), json!({"known":true})),
        (format!("{summary}\n**Robin:**\n> A synthetic correction.\n\n## Summary, corrected (shown to Robin for confirmation)\nRisk: live\n\n1. Corrected summary.\n"), json!({"known":false})),
        (summary.replace("1. Exact summary.", "1. Exact summary. "), json!({"known":false})),
        (format!("{summary}\n## Summary, corrected (shown to Robin for confirmation)\nRisk: release\n\n1. Exact summary.\n"), json!({"known":false})),
        (format!("{summary}\n## Summary, corrected (shown to Robin for confirmation)\n\n1. Exact summary.\n"), json!({"unknown":"independent saved risk verification is unavailable"})),
    ]
    .into_iter()
    .enumerate()
    {
        let room = Fake::new(&format!("e11_summary_source_room_{index}"), "normal");
        let gh = s::fake(
            &format!("e11_summary_source_gh_{index}"),
            vec![s::comment(1001, &s::fenced(&record))],
        );
        s::saved_grill(&gh, &source);
        let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
        s::check(&body);
        assert_eq!(body["items"].as_array().unwrap().len(), 1, "{body}");
        assert_eq!(body["items"][0]["current"], expected, "{index}: {body}");
        assert!(room.invocations().is_empty());
    }
}

#[test]
fn e11_decisions_unverified_pr_heads_and_blobs_stay_unknown() {
    let head = json!({"number":901,"head_sha":s::GRILL_HEAD});
    let blob = json!({"data":{"repository":{"pullRequest":{"number":901,"headRefOid":s::GRILL_HEAD},"object":{"__typename":"Blob","text":SAVED_ROUND,"isTruncated":false}}}});
    let mut cases = Vec::new();
    for (field, value) in [
        ("number", json!(902)),
        ("head_sha", json!("main")),
        ("extra", json!(true)),
    ] {
        let mut value_head = head.clone();
        value_head[field] = value;
        cases.push((true, value_head.to_string()));
    }
    cases.push((
        true,
        format!(
            "{{\"number\":901,\"head_sha\":\"{}\",\"head_sha\":\"{}\"}}",
            s::GRILL_HEAD,
            s::GRILL_HEAD
        ),
    ));
    for (pointer, value) in [
        (
            "/data/repository/pullRequest/headRefOid",
            json!("b".repeat(40)),
        ),
        ("/data/repository/pullRequest/number", json!(902)),
        ("/data/repository/object", json!(null)),
        ("/data/repository/object/__typename", json!("Tree")),
        ("/data/repository/object/isTruncated", json!(true)),
        ("/data/repository/object/isTruncated", json!("false")),
        ("/data/repository/object/text", json!(null)),
    ] {
        let mut bad = blob.clone();
        *bad.pointer_mut(pointer).unwrap() = value;
        cases.push((false, bad.to_string()));
    }
    let mut errors = blob.clone();
    errors["errors"] = json!([{"message":"synthetic-private-diagnostic"}]);
    cases.push((false, errors.to_string()));
    cases.push((
        false,
        blob.to_string().replace(
            "\"isTruncated\":false",
            "\"isTruncated\":false,\"isTruncated\":false",
        ),
    ));
    for (index, (is_head, output)) in cases.into_iter().enumerate() {
        let room = Fake::new(&format!("e11_bad_source_room_{index}"), "normal");
        let record = s::record("synthetic-current", "open");
        let gh = s::fake(
            &format!("e11_bad_source_gh_{index}"),
            vec![s::comment(1001, &s::fenced(&record))],
        );
        s::saved_grill(&gh, SAVED_ROUND);
        s::change(&gh, |scenario| {
            let args = if is_head {
                s::grill_head_argv()
            } else {
                s::grill_blob_argv()
            };
            let response = scenario["responses"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|r| r["argv"] == args)
                .unwrap();
            response["stdout"] = json!(output);
        });
        let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
        s::check(&body);
        assert_eq!(
            body["items"].as_array().unwrap().len(),
            1,
            "{index}: {body}"
        );
        assert!(
            body["items"][0]["current"].get("unknown").is_some(),
            "{index}: {body}"
        );
        assert_eq!(
            body["coverage"]["gaps"].as_array().unwrap().len(),
            2,
            "{index}: {body}"
        );
        assert_eq!(
            body["coverage"]["gaps"][0]["kind"], "malformed",
            "{index}: {body}"
        );
        assert_eq!(body["freshness"]["state"], "unknown");
        assert!(!body.to_string().contains("synthetic-private-diagnostic"));
        assert!(room.invocations().is_empty());
    }
}

#[test]
fn e11_decisions_failed_saved_source_reads_have_sanitized_gaps() {
    for (index, args) in [s::grill_head_argv(), s::grill_blob_argv()]
        .into_iter()
        .enumerate()
    {
        let room = Fake::new(&format!("e11_source_failure_room_{index}"), "normal");
        let record = s::record("synthetic-current", "open");
        let gh = s::fake(
            &format!("e11_source_failure_gh_{index}"),
            vec![s::comment(1001, &s::fenced(&record))],
        );
        s::saved_grill(&gh, SAVED_ROUND);
        s::change(&gh, |scenario| {
            let response = scenario["responses"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|r| r["argv"] == args)
                .unwrap();
            *response = json!({"argv":args,"exit":7,"stderr":"synthetic-private-diagnostic"});
        });
        let server = s::serve(&gh, &room);
        let body = server.get("/api/v1/decisions").json();
        s::check(&body);
        assert_eq!(body["items"].as_array().unwrap().len(), 1, "{body}");
        assert!(body["items"][0]["current"].get("unknown").is_some());
        assert_eq!(
            body["coverage"]["gaps"].as_array().unwrap().len(),
            2,
            "{body}"
        );
        assert_eq!(body["coverage"]["gaps"][0]["kind"], "command_failed");
        assert_eq!(body["freshness"]["state"], "unknown");
        assert!(!body.to_string().contains("synthetic-private-diagnostic"));
        assert!(
            !server
                .settled_log()
                .contains("synthetic-private-diagnostic")
        );
        assert!(room.invocations().is_empty());
    }
}

#[test]
fn e11_decisions_saved_risk_matches_all_explicit_classes() {
    // Independent Python hashlib vectors over the exact canonical proposals;
    // the saved Risk line is outside the request and never part of a self-check.
    for (index, (risk, fingerprint)) in [
        (
            "ordinary",
            "941019e2a769a93d10140f9924b4ce021a041c21f74cd72514a9f51306ad1aa4",
        ),
        (
            "live",
            "971ba6f799c30910f5be8e550f71f6f933524305208b483d653907c67d9b1d28",
        ),
        (
            "release",
            "ba51b97121961fb0a08ff72d6cdfe2199469a224ca47c279671a87495c0606a8",
        ),
        (
            "publish",
            "1c130208548e6099cdf1b798382ae8cba6a734b9ef6f57fe9c092c01385b1004",
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let room = Fake::new(&format!("e11_risk_match_room_{index}"), "normal");
        let mut record = s::record("synthetic-current", "open");
        record["risk"] = json!(risk);
        record["fingerprint"] = json!(fingerprint);
        let gh = s::fake(
            &format!("e11_risk_match_gh_{index}"),
            vec![s::comment(1001, &s::fenced(&record))],
        );
        s::saved_grill(
            &gh,
            &SAVED_ROUND.replace("Risk: ordinary", &format!("Risk: {risk}")),
        );
        let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
        s::check(&body);
        assert_eq!(body["items"].as_array().unwrap().len(), 1, "{body}");
        assert_eq!(
            body["items"][0]["current"],
            json!({"known":true}),
            "{risk}: {body}"
        );
        assert_eq!(body["items"][0]["request"], record);
        assert_eq!(body["coverage"], json!({"state":"complete","gaps":[]}));
        assert_eq!(body["freshness"]["state"], "fresh");
        assert_eq!(
            body["freshness"]["snapshot_at"],
            json!({"known":1_700_000_600_000_u64})
        );
        assert!(
            room.invocations().is_empty(),
            "a current read sends nothing"
        );
    }
}

#[test]
fn e11_decisions_changed_or_unread_risk_never_becomes_current() {
    for (index, (line, expected)) in [
        ("Risk: release", Some(false)),
        ("Risk: live", Some(false)),
        ("Risk: publish", Some(false)),
        ("Risk: unknown", None),
        ("Risk: Ordinary", None),
        ("Risk: ordinary ", None),
        ("Risk:  ordinary", None),
        (" Risk: ordinary", None),
        ("Risk : ordinary", None),
        ("Risk: ordіnary", None),
        ("", None),
        ("Risk: ordinary\nRisk: live", None),
        ("\nRisk: ordinary", None),
    ]
    .into_iter()
    .enumerate()
    {
        for changed_words in [false, true] {
            let room = Fake::new(
                &format!("e11_risk_bad_room_{index}_{changed_words}"),
                "normal",
            );
            let record = s::record("synthetic-current", "open");
            let gh = s::fake(
                &format!("e11_risk_bad_gh_{index}_{changed_words}"),
                vec![s::comment(1001, &s::fenced(&record))],
            );
            let mut saved = SAVED_ROUND.replace("Risk: ordinary", line);
            if changed_words {
                saved = saved.replace("Synthetic choice?", "Changed choice?");
            }
            s::saved_grill(&gh, &saved);
            let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
            s::check(&body);
            assert_eq!(
                body["items"].as_array().unwrap().len(),
                1,
                "{index}: {body}"
            );
            match expected {
                Some(current) => {
                    assert_eq!(
                        body["items"][0]["current"],
                        json!({"known":current}),
                        "{index}: {body}"
                    );
                    assert_eq!(body["coverage"]["state"], "complete");
                }
                None => {
                    assert!(
                        body["items"][0]["current"].get("unknown").is_some(),
                        "{index}: {body}"
                    );
                    assert_eq!(body["coverage"]["state"], "partial");
                    assert_eq!(body["coverage"]["gaps"].as_array().unwrap().len(), 1);
                    assert_eq!(body["freshness"]["state"], "unknown");
                }
            }
            assert!(room.invocations().is_empty());
        }
    }
}

#[test]
fn e11_decisions_saved_grill_uses_the_configured_private_repository() {
    use openwiz_adapter_github::decisions::GitHubDecisions;
    use std::sync::Arc;
    let room = Fake::new("e11_bound_grill_room", "normal");
    // The legacy cwd fake has no verifiable saved wording. Only this explicit
    // private feed has the matching source, so falling back cannot pass.
    let gh = s::fake("e11_bound_grill_gh", vec![]);
    let settings = gh.dir.join("bound-settings.json");
    std::fs::write(
        &settings,
        json!({"decision_repositories":{
        "public":{"owner":"synthetic-public","name":"work"},
        "private":{"owner":"synthetic-records","name":"archive"}}})
        .to_string(),
    )
    .unwrap();
    let record = s::record("synthetic-current", "open");
    s::change(&gh, |scenario| {
        let responses = scenario["responses"].as_array_mut().unwrap();
        for (repo, private) in [
            ("synthetic-public/work", false),
            ("synthetic-records/archive", true),
        ] {
            responses.push(json!({"argv":["repo","view",repo,"--json","nameWithOwner,isPrivate"],"stdout":json!({"nameWithOwner":repo,"isPrivate":private}).to_string()}));
            let rows = if private {
                let mut row = s::comment(1001, &s::fenced(&record));
                row["issue_url"] = json!(format!("https://api.github.com/repos/{repo}/issues/901"));
                vec![row]
            } else {
                vec![]
            };
            for size in [1, 100] {
                let args: Vec<_> = s::argv(1, size)
                    .iter()
                    .map(|a| a.replace("{owner}/{repo}", repo))
                    .collect();
                responses.push(json!({"argv":args,"stdout":s::page(&rows,rows.len() as u64,size)}));
            }
        }
        responses.push(json!({"argv":["api","repos/synthetic-records/archive/issues/901","--jq","{number,body,is_pull_request:has(\"pull_request\")}"],"stdout":json!({"number":901,"body":"Synthetic source","is_pull_request":true}).to_string()}));
        let mut head = s::grill_head_argv();
        head[1] = json!("repos/synthetic-records/archive/pulls/901");
        responses.push(json!({"argv":head,"stdout":json!({"number":901,"head_sha":s::GRILL_HEAD}).to_string()}));
        let mut blob = s::grill_blob_argv();
        blob[2] = json!("-f");
        blob[3] = json!("owner=synthetic-records");
        blob[4] = json!("-f");
        blob[5] = json!("name=archive");
        responses.push(json!({"argv":blob,"stdout":json!({"data":{"repository":{"pullRequest":{"number":901,"headRefOid":s::GRILL_HEAD},"object":{"__typename":"Blob","text":SAVED_ROUND,"isTruncated":false}}}}).to_string()}));
    });
    let server = s::serve_source(
        &room,
        openwiz_server::Config::default(),
        Ok(None),
        Arc::new(crate::fake::clock()),
        GitHubDecisions::with_program(gh.program()).with_settings(&settings),
    );
    let body = server.get("/api/v1/decisions").json();
    s::check(&body);
    assert_eq!(body["items"].as_array().unwrap().len(), 1, "{body}");
    assert_eq!(
        body["items"][0]["subject"]["repository"],
        "synthetic-records/archive"
    );
    assert_eq!(body["items"][0]["current"], json!({"known":true}), "{body}");
    assert_eq!(body["coverage"], json!({"state":"complete","gaps":[]}));
    assert_eq!(body["freshness"]["state"], "fresh");
    assert!(room.invocations().is_empty());
}

#[test]
fn e11_decisions_exact_lookup_retains_lifecycle_and_verified_repository() {
    use openwiz_adapter_github::decisions::GitHubDecisions;
    use openwiz_core::notifications::model::{DecisionRef, TargetState};
    use openwiz_server::Decisions;
    for (index, (status, state)) in [
        ("open", TargetState::Unread),
        ("resolved", TargetState::Resolved),
        ("superseded", TargetState::Resolved),
    ]
    .into_iter()
    .enumerate()
    {
        let record = s::record("synthetic-current", status);
        let gh = s::fake(
            &format!("e11_exact_lifecycle_{index}"),
            vec![s::comment(1001, &s::fenced(&record))],
        );
        let source = Decisions {
            github: GitHubDecisions::with_program(gh.program()),
            target: Ok(None),
        };
        let binding: DecisionRef = serde_json::from_value(json!({
            "repository":"synthetic-owner/synthetic-repo", "subject":{"kind":"pull_request","number":901},
            "comment_id":1001,"request_id":"synthetic-current","fingerprint":record["fingerprint"]
        })).unwrap();
        let found = source.lookup(&binding, &crate::fake::clock());
        assert_eq!(found.state, state, "{status}");
        assert_eq!(found.snapshot_at.is_some(), status != "open");
        let room = Fake::new(&format!("e11_exact_existing_{index}"), "normal");
        let response = s::serve(&gh, &room).get("/api/v1/decisions").json();
        s::check(&response);
        assert_eq!(
            response["items"].as_array().unwrap().len(),
            usize::from(status == "open")
        );
        assert!(!gh.invocations().iter().any(|args| {
            args.iter()
                .any(|arg| matches!(arg.as_str(), "POST" | "PATCH" | "tell" | "spawn"))
        }));
    }
}

#[test]
fn e11_decisions_exact_lookup_never_substitutes_another_binding() {
    use openwiz_adapter_github::decisions::GitHubDecisions;
    use openwiz_core::notifications::model::{DecisionRef, TargetState};
    use openwiz_server::Decisions;
    let record = s::record("synthetic-current", "resolved");
    let binding = json!({
        "repository":"synthetic-owner/synthetic-repo", "subject":{"kind":"pull_request","number":901},
        "comment_id":1001,"request_id":"synthetic-current","fingerprint":record["fingerprint"]
    });
    let mut cases = Vec::new();
    for (key, value, expected) in [
        // The single configured repository is the only one read; a foreign
        // repository was never read, so its absence is not Missing (#2150).
        (
            "repository",
            json!("synthetic-other/synthetic-repo"),
            TargetState::Unread,
        ),
        (
            "subject",
            json!({"kind":"issue","number":901}),
            TargetState::Changed,
        ),
        (
            "subject",
            json!({"kind":"pull_request","number":902}),
            TargetState::Changed,
        ),
        ("comment_id", json!(999), TargetState::Missing),
        ("request_id", json!("synthetic-other"), TargetState::Changed),
        ("fingerprint", json!("f".repeat(64)), TargetState::Changed),
    ] {
        let mut changed = binding.clone();
        changed[key] = value;
        cases.push((
            changed,
            vec![s::comment(1001, &s::fenced(&record))],
            expected,
        ));
    }
    cases.push((
        binding.clone(),
        vec![
            s::comment(1001, &s::fenced(&record)),
            s::comment(1002, &s::fenced(&record)),
        ],
        TargetState::Ambiguous,
    ));
    let mut corrupt = record.clone();
    corrupt["risk"] = json!("release"); // Deliberately retains the old self-hash.
    cases.push((
        binding.clone(),
        vec![s::comment(1001, &s::fenced(&corrupt))],
        TargetState::Unread,
    ));
    for (index, (binding, rows, expected)) in cases.into_iter().enumerate() {
        let gh = s::fake(&format!("e11_exact_binding_{index}"), rows);
        let source = Decisions {
            github: GitHubDecisions::with_program(gh.program()),
            target: Ok(None),
        };
        let binding: DecisionRef = serde_json::from_value(binding).unwrap();
        let found = source.lookup(&binding, &crate::fake::clock());
        assert_eq!(found.state, expected, "case {index}");
        s::change(&gh, |scenario| scenario["responses"][0]["exit"] = json!(1));
        assert_eq!(
            source.lookup(&binding, &crate::fake::clock()).state,
            TargetState::Unread
        );
    }
}

/// #2036 after #2150: a bound reference selects only within its own verified
/// repository. Equal local ids in the other configured repository never
/// substitute, and an unread or unconfigured repository is never Missing.
#[test]
fn e11_decisions_exact_lookup_is_qualified_by_the_bound_repository() {
    use openwiz_adapter_github::decisions::GitHubDecisions;
    use openwiz_core::notifications::model::{DecisionRef, TargetState};
    use openwiz_server::Decisions;
    let grill = s::record("synthetic-current", "open");
    // Same literal plan proposal and fingerprint as the pair test above.
    let plan = json!({"schema":"openwiz.decisions.v1","kind":"plan_approval","id":"synthetic-open","status":"open","fingerprint":"a362c2cc752a0ee9f7be29ef3fdf2f29286ae9b8a2611e68515ffe8f51a4bf49","risk":"ordinary","spec":901,"summary":["Synthetic public plan."],"headline":"none","tickets":[],"graph":[]});
    let pair = |name: &str, public_fails: bool| {
        let gh = s::fake(name, vec![]);
        let settings = gh.dir.join("bound-settings.json");
        std::fs::write(
            &settings,
            json!({"decision_repositories":{
            "public":{"owner":"synthetic-public","name":"work"},
            "private":{"owner":"synthetic-records","name":"archive"}}})
            .to_string(),
        )
        .unwrap();
        s::change(&gh, |scenario| {
            let responses = scenario["responses"].as_array_mut().unwrap();
            for (repo, private) in [
                ("synthetic-public/work", false),
                ("synthetic-records/archive", true),
            ] {
                responses.push(json!({"argv":["repo","view",repo,"--json","nameWithOwner,isPrivate"],"stdout":json!({"nameWithOwner":repo,"isPrivate":private}).to_string()}));
                // Both repositories hold local comment 1001 on subject 901.
                let mut row = s::comment(1001, &s::fenced(if private { &grill } else { &plan }));
                row["issue_url"] = json!(format!("https://api.github.com/repos/{repo}/issues/901"));
                let rows = vec![row];
                for size in [1, 100] {
                    let args: Vec<_> = s::argv(1, size)
                        .iter()
                        .map(|a| a.replace("{owner}/{repo}", repo))
                        .collect();
                    responses.push(if public_fails && !private {
                        json!({"argv":args,"exit":1,"stderr":"synthetic failure"})
                    } else {
                        json!({"argv":args,"stdout":s::page(&rows,rows.len() as u64,size)})
                    });
                }
                responses.push(json!({"argv":["api",format!("repos/{repo}/issues/901"),"--jq","{number,body,is_pull_request:has(\"pull_request\")}"],"stdout":json!({"number":901,"body":"Synthetic source","is_pull_request":private}).to_string()}));
            }
            let mut head = s::grill_head_argv();
            head[1] = json!("repos/synthetic-records/archive/pulls/901");
            responses.push(json!({"argv":head,"stdout":json!({"number":901,"head_sha":s::GRILL_HEAD}).to_string()}));
            let mut blob = s::grill_blob_argv();
            blob[2] = json!("-f");
            blob[3] = json!("owner=synthetic-records");
            blob[4] = json!("-f");
            blob[5] = json!("name=archive");
            responses.push(json!({"argv":blob,"stdout":json!({"data":{"repository":{"pullRequest":{"number":901,"headRefOid":s::GRILL_HEAD},"object":{"__typename":"Blob","text":SAVED_ROUND,"isTruncated":false}}}}).to_string()}));
        });
        let github = GitHubDecisions::with_program(gh.program()).with_settings(&settings);
        (
            gh,
            Decisions {
                github,
                target: Ok(None),
            },
        )
    };
    let binding = |repository: &str, kind: &str, request: &serde_json::Value| -> DecisionRef {
        serde_json::from_value(json!({
            "repository":repository, "subject":{"kind":kind,"number":901},
            "comment_id":1001,"request_id":request["id"],"fingerprint":request["fingerprint"]
        }))
        .unwrap()
    };
    let cases = [
        // The private grill's own saved source verifies it: exactly that item.
        (
            binding("synthetic-records/archive", "pull_request", &grill),
            false,
            TargetState::Current,
        ),
        // The public plan has no independent verifier yet: never current.
        (
            binding("synthetic-public/work", "issue", &plan),
            false,
            TargetState::Unread,
        ),
        // The other repository's equal local id never substitutes.
        (
            binding("synthetic-records/archive", "pull_request", &plan),
            false,
            TargetState::Changed,
        ),
        // An unconfigured repository was never read: not Missing.
        (
            binding("synthetic-other/archive", "pull_request", &grill),
            false,
            TargetState::Unread,
        ),
        // A failed configured role makes the source partial: not current.
        (
            binding("synthetic-records/archive", "pull_request", &grill),
            true,
            TargetState::Unread,
        ),
    ];
    for (index, (bound, public_fails, expected)) in cases.into_iter().enumerate() {
        let (gh, source) = pair(&format!("e11_exact_pair_{index}"), public_fails);
        let found = source.lookup(&bound, &crate::fake::clock());
        assert_eq!(found.state, expected, "case {index}");
        assert_eq!(
            found.snapshot_at.is_some(),
            matches!(expected, TargetState::Current | TargetState::Changed),
            "case {index}"
        );
        assert!(!gh.invocations().iter().any(|args| {
            args.iter()
                .any(|arg| matches!(arg.as_str(), "POST" | "PATCH" | "tell" | "spawn"))
        }));
    }
}

/// #2036 option A: an open grill is current only through the decisions
/// owner's independent saved-grill verifier; changed saved wording or risk is
/// Changed, and an unverifiable saved source stays Unread.
#[test]
fn e11_decisions_exact_lookup_reuses_the_saved_grill_verifier() {
    use openwiz_adapter_github::decisions::GitHubDecisions;
    use openwiz_core::notifications::model::{DecisionRef, TargetState};
    use openwiz_server::Decisions;
    let record = s::record("synthetic-current", "open");
    for (index, (saved, expected)) in [
        (SAVED_ROUND.to_owned(), TargetState::Current),
        (
            SAVED_ROUND.replace("Synthetic choice?", "Changed choice?"),
            TargetState::Changed,
        ),
        (
            SAVED_ROUND.replace("Risk: ordinary", "Risk: release"),
            TargetState::Changed,
        ),
        (
            SAVED_ROUND.replace("Risk: ordinary\n", ""),
            TargetState::Unread,
        ),
        ("Synthetic source".to_owned(), TargetState::Unread),
    ]
    .into_iter()
    .enumerate()
    {
        let gh = s::fake(
            &format!("e11_exact_saved_{index}"),
            vec![s::comment(1001, &s::fenced(&record))],
        );
        s::saved_grill(&gh, &saved);
        let source = Decisions {
            github: GitHubDecisions::with_program(gh.program()),
            target: Ok(None),
        };
        let binding: DecisionRef = serde_json::from_value(json!({
            "repository":"synthetic-owner/synthetic-repo", "subject":{"kind":"pull_request","number":901},
            "comment_id":1001,"request_id":"synthetic-current","fingerprint":record["fingerprint"]
        }))
        .unwrap();
        assert_eq!(
            source.lookup(&binding, &crate::fake::clock()).state,
            expected,
            "case {index}"
        );
        // The decisions route agrees with the same owner verifier.
        let room = Fake::new(&format!("e11_exact_saved_room_{index}"), "normal");
        let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
        let current = &body["items"][0]["current"];
        match expected {
            TargetState::Current => assert_eq!(current, &json!({"known":true}), "{body}"),
            TargetState::Changed => assert_eq!(current, &json!({"known":false}), "{body}"),
            _ => assert!(current.get("unknown").is_some(), "{body}"),
        }
    }
}
