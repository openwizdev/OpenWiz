//! First review round of #794: public HTTP/source regressions for R1–R3.
use crate::{e11_decisions_support as s, fake::Fake};
use serde_json::json;
use std::fs;
use std::os::unix::fs::PermissionsExt;

#[test]
fn r1_null_subject_descriptions_retain_valid_requests() {
    for is_pr in [true, false] {
        let room = Fake::new(&format!("e11_r1_null_room_{is_pr}"), "normal");
        let mut row = s::comment(1001, "");
        let request = if is_pr {
            s::record("synthetic-current", "open")
        } else {
            row["issue_url"] =
                json!("https://api.github.com/repos/synthetic-owner/synthetic-repo/issues/902");
            json!({"schema":"openwiz.decisions.v1","kind":"spec_confirmation","id":"synthetic-spec","status":"open","fingerprint":"d25ef933277cd904bf4311991e9f9c422e2cb8a62ddd7567e9c3db13f6da55e3","risk":"release","spec":902,"summary":["Exact spec summary."],"headline":"Synthetic headline.","tickets":[],"graph":[]})
        };
        row["body"] = json!(s::fenced(&request));
        let gh = s::fake(&format!("e11_r1_null_gh_{is_pr}"), vec![row]);
        s::change(&gh, |scenario| {
            let n = if is_pr { 901 } else { 902 };
            let path = format!("repos/{{owner}}/{{repo}}/issues/{n}");
            let subject = scenario["responses"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|r| r["argv"][1] == path)
                .unwrap();
            subject["stdout"] =
                json!(json!({"number":n,"body":null,"is_pull_request":is_pr}).to_string());
        });
        let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
        s::check(&body);
        assert_eq!(body["items"].as_array().unwrap().len(), 1, "{body}");
        assert_eq!(body["items"][0]["request"], request);
        assert!(body["items"][0]["current"].get("unknown").is_some());
        assert_eq!(
            body["coverage"]["gaps"],
            json!([{"kind":"unsupported","detail":"independent saved proposal verification is unavailable"}])
        );
        assert_eq!(body["freshness"]["state"], "unknown");
        assert!(room.invocations().is_empty());
    }
}

#[test]
fn r2_quoted_prose_does_not_invalidate_the_fenced_request() {
    for (i, prose) in [
        "Ordinary prose: the user typed a single double quote (\").",
        "Ordinary prose with an unmatched quote and escape: \"bad\\q",
        "Ordinary prose before an escaped schema marker: \"",
    ]
    .into_iter()
    .enumerate()
    {
        let room = Fake::new(&format!("e11_r2_prose_room_{i}"), "normal");
        let request = s::record("synthetic-current", "open");
        let mut fenced = s::fenced(&request);
        if i == 2 {
            fenced = fenced.replace("openwiz.decisions.v1", r"\u006fpenwiz.decisions.v1");
        }
        let body = format!("{prose}\n{}\n{}", fenced, r#"Trailing ordinary prose: ""#);
        let gh = s::fake(
            &format!("e11_r2_prose_gh_{i}"),
            vec![s::comment(1001, &body)],
        );
        let response = s::serve(&gh, &room).get("/api/v1/decisions");
        assert_eq!(response.status, 200);
        let value = response.json();
        s::check(&value);
        assert_eq!(value["items"].as_array().unwrap().len(), 1, "{value}");
        assert_eq!(value["items"][0]["request"], request);
        assert_eq!(
            value["coverage"]["gaps"],
            json!([{"kind":"unsupported","detail":"independent saved proposal verification is unavailable"}])
        );
    }
}

#[test]
fn r1_subject_description_types_remain_strict() {
    for (i, value) in [
        json!(false),
        json!(7),
        json!([]),
        json!({"text":"Synthetic body"}),
    ]
    .into_iter()
    .enumerate()
    {
        let room = Fake::new(&format!("e11_r1_types_room_{i}"), "normal");
        let record = s::record("synthetic-current", "open");
        let gh = s::fake(
            &format!("e11_r1_types_gh_{i}"),
            vec![s::comment(1001, &s::fenced(&record))],
        );
        s::change(&gh, |scenario| {
            let subject = scenario["responses"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|r| r["argv"][1] == "repos/{owner}/{repo}/issues/901")
                .unwrap();
            subject["stdout"] =
                json!(json!({"number":901,"body":value,"is_pull_request":true}).to_string());
        });
        let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
        s::check(&body);
        assert_eq!(body["items"], json!([]));
        assert_eq!(body["coverage"]["gaps"].as_array().unwrap().len(), 1);
        assert_eq!(body["coverage"]["gaps"][0]["kind"], "malformed");
    }
}

/// Return successive synthetic answers for selected exact argv. All other
/// calls still use the existing strict fake. The wrapper never runs real gh.
fn scripted(gh: &crate::support::FakeGh, queues: serde_json::Value) {
    fn quote(text: &str) -> String {
        format!("'{}'", text.replace('\'', "'\"'\"'"))
    }
    std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-gh"), gh.dir.join("gh-base")).unwrap();
    fs::remove_file(gh.program()).unwrap();
    let mut script =
        String::from("#!/bin/sh\nset -eu\nu5_base=$(CDPATH= cd -P \"$(dirname \"$0\")\" && pwd)\n");
    for (index, queue) in queues.as_array().unwrap().iter().enumerate() {
        let args = queue["argv"].as_array().unwrap();
        assert!(args.len() < 10);
        script.push_str(&format!("if [ \"$#\" -eq {} ]", args.len()));
        for (i, arg) in args.iter().enumerate() {
            script.push_str(" && [ \"$");
            script.push_str(&(i + 1).to_string());
            script.push_str(&format!("\" = {} ]", quote(arg.as_str().unwrap())));
        }
        script.push_str(&format!("; then\nprintf '%s\\n' {} >> \"$u5_base/gh-invocations.log\"\nu5_seen=0\nif [ -f \"$u5_base/review-sequence-{index}\" ]; then IFS= read -r u5_seen < \"$u5_base/review-sequence-{index}\"; fi\ncase \"$u5_seen\" in\n",quote(&queue["argv"].to_string())));
        for (step, answer) in queue["answers"].as_array().unwrap().iter().enumerate() {
            if answer.get("hang").and_then(serde_json::Value::as_bool) == Some(true) {
                // exec makes the held process the adapter's own child, so its
                // deadline kills and reaps it without leaving a shell child.
                script.push_str(&format!("{step}) printf '%s\\n' {} > \"$u5_base/review-sequence-{index}\"; printf '%s\\n' \"$$\" > \"$u5_base/gh-hang.pid\"; exec sleep 60;;\n",step+1));
                continue;
            }
            let file = format!("review-answer-{index}-{step}");
            fs::write(
                gh.dir.join(&file),
                answer
                    .get("stdout")
                    .map(|v| v.as_str().unwrap())
                    .unwrap_or(""),
            )
            .unwrap();
            let exit = answer.get("exit").map(|v| v.as_u64().unwrap()).unwrap_or(0);
            assert!(exit <= 255);
            script.push_str(&format!("{step}) printf '%s\\n' {} > \"$u5_base/review-sequence-{index}\"; cat \"$u5_base/{file}\"; exit {exit};;\n",step+1));
        }
        script.push_str(
            "*) printf '%s\\n' 'unexpected extra synthetic read' >&2; exit 97;;\nesac\nfi\n",
        );
    }
    script.push_str("exec \"$u5_base/gh-base\" \"$@\"\n");
    // #1488: this multithreaded process never opens the fake for writing.
    // Another test's fork copies every open descriptor until its exec, even
    // CLOEXEC ones, and a writable copy makes the fake's start fail with
    // ETXTBSY. A child owns the only writer and has exited before any start,
    // as `plan_program` does in the GitHub adapter's process tests.
    let writer = std::process::Command::new("/bin/sh")
        .args(["-c", "umask 077; printf '%s' \"$2\" > \"$1\"", "sh"])
        .arg(gh.program())
        .arg(&script)
        .stdin(std::process::Stdio::null())
        .output()
        .unwrap();
    assert!(writer.status.success(), "fixture writer failed: {writer:?}");
    fs::set_permissions(gh.program(), fs::Permissions::from_mode(0o700)).unwrap();
}

#[test]
fn r3_equal_count_page_shift_retains_pending_records_and_reports_incomplete_discovery() {
    let room = Fake::new("e11_r3_shift_room", "normal");
    let old: Vec<_> = (1001..=1100)
        .map(|id| s::comment(id, "Synthetic ordinary comment."))
        .collect();
    let request = s::record("synthetic-last", "open");
    let pending = s::comment(1101, &s::fenced(&request));
    let added = s::comment(1102, "Synthetic inserted comment.");
    let mut current = old[1..].to_vec();
    current.push(pending);
    current.push(added.clone());
    let gh = s::fake("e11_r3_shift_gh", current.clone());
    let old_count = s::page(&old[..1], 101, 1);
    let new_count = s::page(&current[..1], 101, 1);
    scripted(
        &gh,
        json!([
            {"argv":s::argv(1,1),"answers":[{"stdout":old_count},{"stdout":new_count},{"stdout":new_count},{"stdout":new_count}]},
            {"argv":s::argv(1,100),"answers":[{"stdout":s::page(&old,101,100)},{"stdout":s::page(&current[..100],101,100)}]},
            {"argv":s::argv(2,100),"answers":[{"stdout":s::page(std::slice::from_ref(&added),101,100)},{"stdout":s::page(&current[100..],101,100)}]}
        ]),
    );
    let response = s::serve(&gh, &room).get("/api/v1/decisions");
    assert_eq!(response.status, 200);
    let body = response.json();
    s::check(&body);
    assert_eq!(body["items"].as_array().unwrap().len(), 1, "{body}");
    assert_eq!(body["items"][0]["comment_id"], 1101);
    assert_eq!(body["items"][0]["request"], request);
    assert_eq!(body["coverage"]["state"], "partial");
    assert_eq!(body["freshness"]["state"], "unknown");
    assert_eq!(
        body["coverage"]["gaps"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|g| g["kind"] == "malformed")
            .count(),
        1,
        "{body}"
    );
    let calls = gh.invocations();
    assert_eq!(calls.iter().filter(|a| **a == s::argv(1, 100)).count(), 2);
    assert_eq!(calls.iter().filter(|a| **a == s::argv(2, 100)).count(), 2);
    assert_eq!(calls.iter().filter(|a| **a == s::argv(1, 1)).count(), 4);
    assert!(room.invocations().is_empty());
}

#[test]
fn r3_changed_contents_prevent_confident_empty_discovery() {
    let room = Fake::new("e11_r3_contents_room", "normal");
    let old = s::comment(1001, "Synthetic original prose.");
    let new = s::comment(1001, "Synthetic edited prose.");
    let gh = s::fake("e11_r3_contents_gh", vec![new.clone()]);
    scripted(
        &gh,
        json!([
            {"argv":s::argv(1,1),"answers":[{"stdout":s::page(std::slice::from_ref(&old),1,1)},{"stdout":s::page(std::slice::from_ref(&new),1,1)},{"stdout":s::page(std::slice::from_ref(&new),1,1)},{"stdout":s::page(std::slice::from_ref(&new),1,1)}]},
            {"argv":s::argv(1,100),"answers":[{"stdout":s::page(&[old],1,100)},{"stdout":s::page(&[new],1,100)}]}
        ]),
    );
    let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
    s::check(&body);
    assert_eq!(body["items"], json!([]));
    assert_eq!(body["coverage"]["state"], "partial", "{body}");
    assert_eq!(body["freshness"]["state"], "unknown");
    assert_eq!(body["coverage"]["gaps"].as_array().unwrap().len(), 1);
    assert_eq!(body["coverage"]["gaps"][0]["kind"], "malformed");
    assert_eq!(
        gh.invocations()
            .iter()
            .filter(|a| **a == s::argv(1, 100))
            .count(),
        2
    );
}

#[test]
fn r3_unfinished_verification_retains_usable_first_scan_records() {
    let room = Fake::new("e11_r3_unfinished_room", "normal");
    let request = s::record("synthetic-current", "open");
    let row = s::comment(1001, &s::fenced(&request));
    let gh = s::fake("e11_r3_unfinished_gh", vec![row.clone()]);
    scripted(
        &gh,
        json!([{"argv":s::argv(1,100),"answers":[{"stdout":s::page(&[row],1,100)},{"exit":7}]}]),
    );
    let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
    s::check(&body);
    assert_eq!(body["items"].as_array().unwrap().len(), 1, "{body}");
    assert_eq!(body["items"][0]["request"], request);
    assert_eq!(body["coverage"]["state"], "partial");
    assert_eq!(body["freshness"]["state"], "unknown");
    assert_eq!(
        body["coverage"]["gaps"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|g| g["kind"] == "command_failed")
            .count(),
        1,
        "{body}"
    );
    assert_eq!(body["coverage"]["gaps"].as_array().unwrap().len(), 2);
    assert_eq!(
        gh.invocations()
            .iter()
            .filter(|a| **a == s::argv(1, 100))
            .count(),
        2
    );
}

#[test]
fn r3_partial_scans_retain_identical_and_newly_observed_requests() {
    for was_pending in [true, false] {
        let room = Fake::new(&format!("e11_r3_retention_room_{was_pending}"), "normal");
        let request = s::record("synthetic-current", "open");
        let old_body = if was_pending {
            format!("Synthetic original prose.\n{}", s::fenced(&request))
        } else {
            "Synthetic original prose.".to_owned()
        };
        let old = s::comment(1001, &old_body);
        let mut new = s::comment(
            1001,
            &format!("Synthetic edited prose.\n{}", s::fenced(&request)),
        );
        new["updated_at"] = json!("2026-01-01T00:00:01Z");
        let gh = s::fake(
            &format!("e11_r3_retention_gh_{was_pending}"),
            vec![new.clone()],
        );
        let first_count = s::page(std::slice::from_ref(&old), 1, 1);
        let last_count = s::page(std::slice::from_ref(&new), 1, 1);
        scripted(
            &gh,
            json!([
                {"argv":s::argv(1,1),"answers":[{"stdout":first_count},{"stdout":last_count},{"stdout":last_count},{"stdout":last_count}]},
                {"argv":s::argv(1,100),"answers":[{"stdout":s::page(&[old],1,100)},{"stdout":s::page(&[new],1,100)}]}
            ]),
        );
        let response = s::serve(&gh, &room).get("/api/v1/decisions");
        assert_eq!(response.status, 200);
        let body = response.json();
        s::check(&body);
        assert_eq!(body["items"].as_array().unwrap().len(), 1, "{body}");
        assert_eq!(body["items"][0]["comment_id"], 1001);
        assert_eq!(body["items"][0]["request"], request);
        assert!(body["items"][0]["current"].get("unknown").is_some());
        assert_eq!(body["coverage"]["state"], "partial");
        assert_eq!(body["freshness"]["state"], "unknown");
        assert_eq!(body["coverage"]["gaps"].as_array().unwrap().len(), 2);
        assert_eq!(body["coverage"]["gaps"][0]["kind"], "malformed");
        assert_eq!(body["coverage"]["gaps"][1]["kind"], "unsupported");
        let calls = gh.invocations();
        assert_eq!(calls.iter().filter(|a| **a == s::argv(1, 100)).count(), 2);
        assert_eq!(calls.iter().filter(|a| **a == s::argv(1, 1)).count(), 4);
        assert!(room.invocations().is_empty());
    }
}

#[test]
fn r3_duplicate_comment_id_within_one_scan_remains_ambiguous() {
    let room = Fake::new("e11_r3_duplicate_comment_room", "normal");
    let request = s::record("synthetic-current", "open");
    let row = s::comment(1001, &s::fenced(&request));
    let gh = s::fake("e11_r3_duplicate_comment_gh", vec![row.clone(), row]);
    let body = s::serve(&gh, &room).get("/api/v1/decisions").json();
    s::check(&body);
    assert_eq!(body["items"], json!([]), "{body}");
    assert_eq!(body["coverage"]["state"], "partial");
    assert_eq!(body["freshness"]["state"], "unknown");
    assert!(
        body["coverage"]["gaps"]
            .as_array()
            .unwrap()
            .iter()
            .all(|g| g["kind"] == "malformed")
    );
}

#[test]
fn r4_positively_unrelated_prose_and_fences_never_add_a_gap() {
    let cases = [
        "Ordinary prose with one stray quote: \"",
        r#"An ordinary Windows path: "C:\Users\x"."#,
        "An ordinary quote across\n\"two\nlines\".",
        "A list example:\n ```json\n{\"ordinary\":1}\n ```",
        "An example:\n```jsonc\n{\"ordinary\":1}\n```",
    ];
    let mut misclassified = Vec::new();
    for (index, prose) in cases.into_iter().enumerate() {
        for with_pending in [false, true] {
            let room = Fake::new(&format!("e11_r4_room_{index}_{with_pending}"), "normal");
            let request = s::record("synthetic-current", "open");
            let mut rows = vec![s::comment(1001, prose)];
            if with_pending {
                rows.push(s::comment(1002, &s::fenced(&request)));
            }
            let gh = s::fake(&format!("e11_r4_gh_{index}_{with_pending}"), rows);
            let response = s::serve(&gh, &room).get("/api/v1/decisions");
            assert_eq!(response.status, 200);
            let body = response.json();
            s::check(&body);
            let gaps = if with_pending {
                json!([{"kind":"unsupported","detail":"independent saved proposal verification is unavailable"}])
            } else {
                json!([])
            };
            if body["coverage"]["gaps"] != gaps {
                misclassified.push((index, with_pending, body["coverage"].clone()));
            }
            assert_eq!(
                body["items"].as_array().unwrap().len(),
                usize::from(with_pending)
            );
            if with_pending {
                assert_eq!(body["items"][0]["request"], request);
            }
            assert!(room.invocations().is_empty());
        }
    }
    assert!(misclassified.is_empty(), "{misclassified:?}");
}

/// Give the real process runner a few seconds left in the existing budget
/// (three in full, 1.5 in the fast form, more on a busy host).
/// This changes neither production limits nor the HTTP request deadline.
struct RemainingBudget(std::time::Duration);
impl RemainingBudget {
    /// The reads before the held one must still fit on a busy host (#2645):
    /// scaled to one unheld decisions read timed now. Stay well below the
    /// 15-second read timeout, so the budget, not that timeout, stops the
    /// held read.
    fn new() -> Self {
        static CALIBRATIONS: std::sync::atomic::AtomicUsize =
            std::sync::atomic::AtomicUsize::new(0);
        let n = CALIBRATIONS.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Self(crate::real_time::scaled(
            "e11_remaining_budget",
            crate::real_time::pick(
                "e11_remaining_budget",
                std::time::Duration::from_secs(3),
                std::time::Duration::from_millis(1500),
            ),
            std::time::Duration::from_secs(10),
            || {
                let room = Fake::new(&format!("e11_budget_calibrate_room_{n}"), "normal");
                let row = s::comment(1001, &s::fenced(&s::record("synthetic-current", "open")));
                let gh = s::fake(&format!("e11_budget_calibrate_gh_{n}"), vec![row]);
                let clock = std::sync::Arc::new(crate::fake::clock());
                let server = s::serve_with(&gh, &room, Default::default(), Ok(None), clock);
                assert_eq!(server.get("/api/v1/decisions").status, 200);
            },
        ))
    }
}
impl openwiz_core::ops::Clock for RemainingBudget {
    fn now(&self) -> openwiz_core::model::Timestamp {
        openwiz_core::model::Timestamp(1700000600000)
    }
    fn monotonic(&self) -> std::time::Instant {
        std::time::Instant::now() - (openwiz_core::limits::RUN_BUDGET - self.0)
    }
}

#[test]
fn r3_deadline_exhaustion_retains_verified_first_scan_requests() {
    crate::at_once::at_once(&[true, false], 2, |&verified| {
        let room = Fake::new(&format!("e11_r3_deadline_room_{verified}"), "normal");
        let request = s::record("synthetic-current", "open");
        let row = s::comment(1001, &s::fenced(&request));
        let gh = s::fake(&format!("e11_r3_deadline_gh_{verified}"), vec![row.clone()]);
        if !verified {
            s::change(&gh, |scenario| {
                let subject = scenario["responses"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|r| r["argv"][1] == "repos/{owner}/{repo}/issues/901")
                    .unwrap();
                subject["stdout"] =
                    json!("{\"number\":999,\"body\":null,\"is_pull_request\":true}");
            });
        }
        scripted(
            &gh,
            json!([
                {"argv":s::argv(1,100),"answers":[{"stdout":s::page(&[row],1,100)},{"hang":true}]}
            ]),
        );
        let server = s::serve_with(
            &gh,
            &room,
            Default::default(),
            Ok(None),
            std::sync::Arc::new(RemainingBudget::new()),
        );
        let response = server.get("/api/v1/decisions");
        assert_eq!(response.status, 200);
        let body = response.json();
        s::check(&body);
        assert!(
            gh.hung_pid().is_some(),
            "verification must really reach the held read"
        );
        assert_eq!(
            body["items"].as_array().unwrap().len(),
            usize::from(verified),
            "{body}"
        );
        if verified {
            assert_eq!(body["items"][0]["request"], request);
            assert!(body["items"][0]["current"].get("unknown").is_some());
        }
        assert_eq!(body["coverage"]["state"], "partial");
        assert_eq!(body["freshness"]["state"], "unknown");
        let gaps = body["coverage"]["gaps"].as_array().unwrap();
        assert_eq!(gaps.len(), 2, "{body}");
        assert_eq!(
            gaps.iter().filter(|g| g["kind"] == "timed_out").count(),
            1,
            "{body}"
        );
        assert_eq!(
            gaps[1]["kind"],
            if verified { "unsupported" } else { "malformed" }
        );
        let calls = gh.invocations();
        let subject = calls
            .iter()
            .position(|a| {
                a.get(1)
                    .is_some_and(|s| s == "repos/{owner}/{repo}/issues/901")
            })
            .expect("subject verified before deadline exhaustion");
        let verification = calls.iter().rposition(|a| *a == s::argv(1, 100)).unwrap();
        assert!(subject < verification, "{calls:?}");
        assert!(room.invocations().is_empty());
    });
}

#[test]
fn r5_mid_feed_deadline_retains_the_newest_verified_request() {
    // Independent directional responses: ascending really contains the oldest
    // 100 rows; descending contains the newest 100, including the pending row.
    fn feed(page: u64, size: u64, direction: &str) -> Vec<String> {
        vec![
            "api".into(),
            "--include".into(),
            format!(
                "repos/{{owner}}/{{repo}}/issues/comments?per_page={size}&sort=created&direction={direction}&page={page}"
            ),
            "--jq".into(),
            "[.[] | {id,body,issue_url,created_at,updated_at}]".into(),
        ]
    }
    fn page(rows: &[serde_json::Value], size: u64, direction: &str) -> String {
        format!(
            "HTTP/2.0 200 OK\r\nLink: <https://api.github.com/repos/synthetic-owner/synthetic-repo/issues/comments?per_page={size}&sort=created&direction={direction}&page={}>; rel=\"last\"\r\n\r\n{}",
            if size == 1 { 101 } else { 2 },
            json!(rows)
        )
    }
    let room = Fake::new("e11_r5_deadline_room", "normal");
    let request = s::record("synthetic-last", "open");
    let ascending: Vec<_> = (0..=100)
        .map(|n| {
            let body = if n == 100 {
                s::fenced(&request)
            } else {
                "Synthetic old prose.".into()
            };
            let mut row = s::comment(1001 + n, &body);
            let time = format!("2026-01-01T10:{:02}:{:02}Z", n / 60, n % 60);
            row["created_at"] = json!(time);
            row["updated_at"] = json!(time);
            row
        })
        .collect();
    let descending: Vec<_> = ascending.iter().rev().cloned().collect();
    let gh = s::fake("e11_r5_deadline_gh", vec![]);
    s::change(&gh, |scenario| {
        // The test supplies both supported histories. No response silently
        // serves newest rows for an oldest-first request.
        scenario["responses"].as_array_mut().unwrap().retain(|r| {
            !r["argv"]
                .as_array()
                .unwrap()
                .iter()
                .any(|a| a.as_str().is_some_and(|a| a.contains("/issues/comments?")))
        });
        for (direction, rows) in [("asc", &ascending), ("desc", &descending)] {
            scenario["responses"].as_array_mut().unwrap().extend([
                json!({"argv":feed(1,1,direction),"stdout":page(&rows[..1],1,direction)}),
                json!({"argv":feed(1,100,direction),"stdout":page(&rows[..100],100,direction)}),
                json!({"argv":feed(2,100,direction),"hang":true}),
            ]);
        }
    });
    let server = s::serve_with(
        &gh,
        &room,
        Default::default(),
        Ok(None),
        std::sync::Arc::new(RemainingBudget::new()),
    );
    let response = server.get("/api/v1/decisions");
    assert_eq!(response.status, 200);
    let body = response.json();
    s::check(&body);
    assert!(
        gh.hung_pid().is_some(),
        "the mid-feed read must actually exhaust its deadline"
    );
    assert_eq!(body["items"].as_array().unwrap().len(), 1, "{body}");
    assert_eq!(body["items"][0]["comment_id"], 1101);
    assert_eq!(body["items"][0]["request"], request);
    assert!(body["items"][0]["current"].get("unknown").is_some());
    assert_eq!(body["coverage"]["state"], "partial");
    assert_eq!(body["freshness"]["state"], "unknown");
    assert_eq!(body["coverage"]["gaps"].as_array().unwrap().len(), 2);
    assert_eq!(body["coverage"]["gaps"][0]["kind"], "timed_out");
    assert_eq!(body["coverage"]["gaps"][1]["kind"], "unsupported");
    let calls = gh.invocations();
    assert_eq!(
        calls.iter().filter(|a| **a == feed(1, 1, "desc")).count(),
        1
    );
    assert_eq!(
        calls.iter().filter(|a| **a == feed(1, 100, "desc")).count(),
        1
    );
    assert_eq!(
        calls.iter().filter(|a| **a == feed(2, 100, "desc")).count(),
        1
    );
    assert!(!calls.iter().flatten().any(|a| a.contains("direction=asc")));
    let subject = calls
        .iter()
        .position(|a| {
            a.get(1)
                .is_some_and(|s| s == "repos/{owner}/{repo}/issues/901")
        })
        .unwrap();
    let unfinished = calls
        .iter()
        .position(|a| *a == feed(2, 100, "desc"))
        .unwrap();
    assert!(subject < unfinished);
    assert!(room.invocations().is_empty());
}

/// Set only for the child process of the fork-load regression below.
const FORK_LOAD_CHILD: &str = "OPENWIZ_E11_1488_FORK_LOAD_CHILD";
const FORK_LOAD_ROUNDS: usize = 200;

/// #1488: a fork copies every descriptor its process has open until the
/// child execs, CLOEXEC or not, and a writable copy of the fake makes its
/// start fail with ETXTBSY. The load runs in its own test process, so its
/// slow children never copy another test's descriptors.
#[test]
fn r3_scripted_fakes_start_while_other_threads_fork_slow_children() {
    let out = std::process::Command::new(std::env::current_exe().expect("this test binary"))
        .args([
            "--exact",
            "e11_decisions_review::r3_fork_load_child",
            "--nocapture",
            "--test-threads=1",
            "-q",
        ])
        .env(FORK_LOAD_CHILD, "1")
        .stdin(std::process::Stdio::null())
        .output()
        .expect("run the fork-load child");
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        out.status.success(),
        "{stdout}\n{}",
        String::from_utf8_lossy(&out.stderr)
    );
    // libtest exits 0 when the filter matches nothing: require the child's
    // own line, so the regression cannot pass without running.
    assert_eq!(
        stdout
            .lines()
            .filter(|l| *l == format!("fork load: {FORK_LOAD_ROUNDS} fresh fakes started"))
            .count(),
        1,
        "{stdout}"
    );
}

/// The regression's child. Creates each scripted fake while other threads
/// keep forking children that search 3000 missing `PATH` directories before
/// their exec, as `tests/fleet/lock_release.rs` does, then starts it at once.
/// Without the child marker it does nothing: the regression above runs it.
#[test]
fn r3_fork_load_child() {
    use std::process::{Command, Stdio};
    use std::sync::atomic::{AtomicBool, Ordering};
    if std::env::var_os(FORK_LOAD_CHILD).is_none() {
        return;
    }
    const SPAWNERS: usize = 4;
    // Stops the load on every exit from the scope, a panic included.
    struct Stop<'a>(&'a AtomicBool);
    impl Drop for Stop<'_> {
        fn drop(&mut self) {
            self.0.store(true, Ordering::Relaxed);
        }
    }
    let mut path = vec!["/nonexistent-openwiz-e11-fork-load"; 3_000];
    path.push("/usr/bin:/bin");
    let path = path.join(":");
    let done = AtomicBool::new(false);
    let mut failed = Vec::new();
    std::thread::scope(|scope| {
        let _stop = Stop(&done);
        for _ in 0..SPAWNERS {
            scope.spawn(|| {
                while !done.load(Ordering::Relaxed) {
                    let status = Command::new("true")
                        .env("PATH", &path)
                        .stdin(Stdio::null())
                        .status()
                        .expect("spawn and reap a load child");
                    assert!(status.success(), "load child failed");
                }
            });
        }
        for round in 0..FORK_LOAD_ROUNDS {
            let gh = crate::support::FakeGh::new(
                &format!("e11_r3_fork_load_gh_{round}"),
                std::path::Path::new(crate::support::FIXTURES)
                    .join("fleets/complete/scenario.json")
                    .as_path(),
            );
            scripted(
                &gh,
                json!([{"argv":["synthetic", "probe"],"answers":[{"stdout":"synthetic answer\n"}]}]),
            );
            match Command::new(gh.program())
                .args(["synthetic", "probe"])
                .stdin(Stdio::null())
                .output()
            {
                Ok(out) => {
                    assert!(out.status.success(), "round {round}: {out:?}");
                    assert_eq!(out.stdout, b"synthetic answer\n");
                }
                Err(error) => failed.push((round, error.raw_os_error())),
            }
            fs::remove_dir_all(&gh.dir).unwrap();
        }
    });
    // 26 is ETXTBSY on Linux.
    assert!(
        failed.is_empty(),
        "{} of {FORK_LOAD_ROUNDS} fresh fakes could not start (round, errno): {failed:?}",
        failed.len()
    );
    println!("fork load: {FORK_LOAD_ROUNDS} fresh fakes started");
}
