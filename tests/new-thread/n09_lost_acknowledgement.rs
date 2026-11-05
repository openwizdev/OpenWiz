//! N9 Lost acknowledgement: a fake that creates the thread and then never
//! answers gives **uncertain**, keeps the text in the record and makes no
//! second call. Nothing is retried by itself: not the same op id again, not
//! a status read, not anything else that runs next. The fake's request-ID
//! table counts one thread.

use std::time::Duration;

use openwiz_core::new_thread::operation::new_thread;
use openwiz_core::new_thread::{NewThreadRequest, ProjectRef};
use openwiz_core::prompt::PromptPayload;
use serde_json::{Value, json};

use crate::fake::*;
use crate::support::{clock, offered, op};

const TEXT: &str = "Synthetic lost acknowledgement";

fn uncertain_create(fake: &NewFake, op_id: &str) -> Value {
    let mut request = NewThreadRequest::new(
        ProjectRef::Name("Synthetic project one".to_owned()),
        offered(),
        PromptPayload::text(TEXT),
        op(op_id),
    );
    // Short (#1260): a hung create waits for it.
    request.budget = Duration::from_millis(1_500);
    let report = new_thread(&fake.source(), &fake.store(), &clock(), &request).expect("a report");
    serde_json::to_value(report).unwrap()
}

#[test]
fn a_create_that_times_out_is_uncertain_and_is_never_redone() {
    let fake = NewFake::with(
        "n09_timeout",
        vec![json!({"any_spawn": true, "creates": true, "hang": true})],
    );
    let report = uncertain_create(&fake, "op-n09-lost");
    assert_eq!(report["status"], "uncertain", "{report}");
    assert_eq!(report["result"]["outcome"]["reason"], "timed_out");
    assert_eq!(fake.spawn_count(), 1);
    assert_eq!(fake.threads_created(), 1, "the fake did create it");
    let record = fake.record("op-n09-lost");
    assert_eq!(record["state"], "finished");
    assert_eq!(record["text"], TEXT, "the text is kept");
    assert_eq!(record["outcome"]["kind"], "uncertain");

    // The same op id again: its recorded outcome, no call.
    let args = new_args("Synthetic project one", "op-n09-lost", &["--json"], TEXT);
    let (code, json) = json_of(&fake.run_process(&args, ""));
    assert_eq!(code, Some(6), "{json}");
    assert_eq!(json["status"], "uncertain");
    assert_eq!(json["result"]["replayed"], true);
    // A status read: still uncertain, no call.
    let (code, status) =
        json_of(&fake.run_process(&["new", "--status", "op-n09-lost", "--json"], ""));
    assert_eq!(code, Some(6), "{status}");
    assert_eq!(status["result"]["report"]["status"], "uncertain");
    // Anything else that runs next.
    for args in [&["ls", "-l", "--json"][..], &["models", "--json"][..]] {
        let out = fake.run_process(args, "");
        assert!(out.status.code().is_some(), "{args:?}");
    }
    assert_eq!(fake.spawn_count(), 1, "nothing was redone");
    assert_eq!(fake.threads_created(), 1, "one thread in all");
}

#[test]
fn a_create_that_crashes_or_answers_garbage_is_uncertain() {
    for (test, response, reason) in [
        (
            "n09_abort",
            json!({"any_spawn": true, "creates": true, "abort": true}),
            "ended_without_exit_code",
        ),
        (
            "n09_not_json",
            json!({"any_spawn": true, "creates": true, "stdout": "Synthetic not JSON"}),
            "not_json",
        ),
        (
            "n09_undocumented",
            json!({
                "any_spawn": true,
                "creates": true,
                "stderr": "Error: Failed to create thread: HTTP 500: Synthetic server error",
                "exit": 1,
            }),
            "undocumented_error",
        ),
    ] {
        let fake = NewFake::with(test, vec![response]);
        let args = new_args("Synthetic project one", "op-n09", &["--json"], TEXT);
        let (code, json) = json_of(&fake.run_process(&args, ""));
        assert_eq!(code, Some(6), "{test}: {json}");
        assert_eq!(
            json["result"]["outcome"]["reason"], reason,
            "{test}: {json}"
        );
        assert_eq!(fake.record("op-n09")["text"], TEXT, "{test}");
        // No room-cli words reach the report.
        assert!(
            !json.to_string().contains("Synthetic server error"),
            "{json}"
        );
        assert!(!json.to_string().contains("Synthetic not JSON"), "{json}");
        let (code, _) = json_of(&fake.run_process(&args, ""));
        assert_eq!(code, Some(6));
        assert_eq!(fake.spawn_count(), 1, "{test}: one call, ever");
    }
}

#[test]
fn a_documented_refusal_is_refused_and_creates_nothing() {
    let fake = NewFake::with(
        "n09_refused",
        vec![json!({
            "any_spawn": true,
            "stderr": "Error: Failed to create thread: HTTP 400: This model is unavailable on Cloud",
            "exit": 1,
        })],
    );
    let args = new_args("Synthetic project one", "op-n09-refused", &["--json"], TEXT);
    let (code, json) = json_of(&fake.run_process(&args, ""));
    assert_eq!(code, Some(5), "{json}");
    assert_eq!(
        json["result"]["outcome"]["reason"],
        "provider_model_unavailable"
    );
    assert_eq!(fake.threads_created(), 0);
}

/// A status read of an uncertain create lists the threads seen in the
/// project since the attempt: observations only, which never settle it.
#[test]
fn observations_never_settle_an_uncertain_create() {
    use openwiz_adapter_cloudroom::new_thread::parse_observed_threads;
    use openwiz_core::model::{Fact, Timestamp};

    let since = Timestamp(1_700_000_600_000);
    let list = std::fs::read(file("thread-list.json")).unwrap();
    let seen = parse_observed_threads(&list, PROJECT, since).expect("parsed");
    let ids: Vec<&str> = seen.iter().map(|t| t.id.as_str()).collect();
    assert_eq!(ids, ["thr_syn_0021", "thr_syn_0025", "thr_syn_0026"]);
    assert_eq!(seen[0].created_at, Fact::Known(since));
    assert!(matches!(seen[2].created_at, Fact::Unknown(_)));
    assert!(parse_observed_threads(b"{}", PROJECT, since).is_err());

    let fake = NewFake::with(
        "n09_observations",
        vec![
            json!({"any_spawn": true, "creates": true, "abort": true}),
            json!({"argv": ["thread", "list", "--json"], "stdout_file": file("thread-list.json")}),
        ],
    );
    let args = new_args("Synthetic project one", "op-n09-seen", &["--json"], TEXT);
    let (code, _) = json_of(&fake.run_process(&args, ""));
    assert_eq!(code, Some(6));
    let (code, status) =
        json_of(&fake.run_process(&["new", "--status", "op-n09-seen", "--json"], ""));
    assert_eq!(code, Some(6), "still uncertain: {status}");
    let observations = &status["result"]["observations"];
    assert!(
        observations["text"]
            .as_str()
            .unwrap()
            .starts_with("observations only"),
        "{status}"
    );
    assert!(!observations["threads"].as_array().unwrap().is_empty());
    assert_eq!(status["result"]["report"]["status"], "uncertain");
    assert_eq!(fake.spawn_count(), 1);
}

#[test]
fn synthetic_status_observations_use_claim_time() {
    // Synthetic rows straddle uncertain_create's fixed claim time by 1 ms.
    let rows = json!([
        {"id": "thr_syn_before", "projectId": PROJECT, "createdAt": 1_700_000_599_999_i64},
        {"id": "thr_syn_at", "projectId": PROJECT, "createdAt": 1_700_000_600_000_i64},
    ]);
    let fake = NewFake::with(
        "n09_claim_cutoff",
        vec![
            json!({"any_spawn": true, "abort": true}),
            json!({"argv": ["thread", "list", "--json"], "stdout": rows.to_string()}),
        ],
    );
    assert_eq!(
        uncertain_create(&fake, "op-n09-cutoff")["status"],
        "uncertain"
    );

    let (code, status) =
        json_of(&fake.run_process(&["new", "--status", "op-n09-cutoff", "--json"], ""));
    assert_eq!(code, Some(6), "{status}");
    assert_eq!(status["result"]["report"]["status"], "uncertain");
    let ids: Vec<_> = status["result"]["observations"]["threads"]
        .as_array()
        .expect("observed threads")
        .iter()
        .map(|thread| thread["id"].as_str().expect("observed thread ID"))
        .collect();
    assert_eq!(ids, ["thr_syn_at"]);
    assert_eq!(fake.spawn_count(), 1);
}

#[test]
fn synthetic_status_text_labels_observations_as_inconclusive() {
    let fake = NewFake::with(
        "n09_status_text_label",
        vec![
            json!({"any_spawn": true, "creates": true, "abort": true}),
            json!({"argv": ["thread", "list", "--json"], "stdout_file": file("thread-list.json")}),
        ],
    );
    let args = new_args("Synthetic project one", "op-n09-text", &["--json"], TEXT);
    let (code, _) = json_of(&fake.run_process(&args, ""));
    assert_eq!(code, Some(6));

    let status = fake.run_process(&["new", "--status", "op-n09-text"], "");
    let out = String::from_utf8(status.stdout).expect("UTF-8 status text");
    assert_eq!(status.status.code(), Some(6), "{out}");
    assert!(out.contains("seen: thr_syn_0026"), "{out}");
    assert!(
        out.contains(
            "observations only: no documented field ties a listed thread \
             to this request, so the outcome stays uncertain"
        ),
        "{out}"
    );
    assert_eq!(fake.spawn_count(), 1);
}

#[test]
fn synthetic_status_text_preserves_known_observed_creation_time() {
    let fake = NewFake::with(
        "n09_status_text_created_at",
        vec![
            json!({"any_spawn": true, "creates": true, "abort": true}),
            json!({"argv": ["thread", "list", "--json"], "stdout_file": file("thread-list.json")}),
        ],
    );
    let report = uncertain_create(&fake, "op-n09-text-created-at");
    assert_eq!(report["status"], "uncertain", "{report}");

    let status = fake.run_process(&["new", "--status", "op-n09-text-created-at"], "");
    let out = String::from_utf8(status.stdout).expect("UTF-8 status text");
    assert_eq!(status.status.code(), Some(6), "{out}");
    assert!(
        out.contains("seen: thr_syn_0021 · created 2023-11-14T22:23:20Z"),
        "{out}"
    );
}
