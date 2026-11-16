//! Sol, round 1, R2: the two JSON documents `room-cli` hands a create, the
//! `spawn` receipt and the `cloud status` catalogue, are read with strict,
//! hand-written readers that see every key as the text gives it (B1's
//! pattern), never through `serde_json::Value`, which keeps only the last of
//! a key given twice.
//!
//! - **The receipt:** `id` and `projectId` required, each a string, each
//!   once; any other key of any type is accepted unread (#949), but no key
//!   may be given twice at any depth. Anything else is uncertain, with the
//!   prompt kept.
//! - **The catalogue:** only sheet A-2's keys are read, each typed, each
//!   once; every other key is still dropped unread (A-2). Anything else
//!   offers nothing and dispatches nothing.

use openwiz_adapter_cloudroom::new_thread::{parse_catalogue, spawn_receipt};
use openwiz_core::messaging::send::UncertainReason;
use openwiz_core::new_thread::outcome::SpawnReply;
use openwiz_core::source::SourceError;
use serde_json::{Value, json};

use crate::fake::*;
use crate::support::{fixture, fixture_json};

/// `text` with the first `from` replaced by `to`: a key given twice, which
/// no `Value` can hold.
fn twice(text: &str, from: &str, to: &str) -> String {
    let changed = text.replacen(from, to, 1);
    assert_ne!(changed, text, "{from} is in the document");
    changed
}

fn with(value: &Value, key: &str, new: Value) -> String {
    let mut v = value.clone();
    v[key] = new;
    v.to_string()
}

fn without(value: &Value, key: &str) -> String {
    let mut v = value.clone();
    v.as_object_mut().unwrap().remove(key);
    v.to_string()
}

/// Sol's counterexample, as he ran it.
const SOLS_RECEIPT: &str = r#"{"id":"thr_syn_wrong","id":"thr_syn_0021","projectId":"prj_syn_wrong","projectId":"prj_syn_0001","unexpected":true}"#;

#[test]
fn boundary_readers_affected_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 2] = [
        ("the_catalogue_table", the_catalogue_table),
        ("the_receipt_table", the_receipt_table),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: boundary_readers::{name}");
        proof();
    }
}

fn the_receipt_table() {
    let receipt = fixture_json("spawn-receipt-created.json");
    let text = receipt.to_string();
    let mut documented = receipt.clone();
    for (key, value) in [
        (
            "purpose",
            json!({"text": "Synthetic purpose.", "percent": 0}),
        ),
        ("activity", json!({"activeGoalCount": 0})),
        ("runtime", json!({"displayStatus": "idle"})),
        ("projectCopy", Value::Null),
        ("queuedWork", json!("none")),
        ("hasPendingInteraction", json!(false)),
        ("environmentHostId", Value::Null),
        ("environmentIsWorktree", Value::Null),
        ("lastError", Value::Null),
    ] {
        documented[key] = value;
    }
    let good = [
        text.clone(),
        documented.to_string(),
        // #949: room-cli v155's declared receipt adds keys the old reader refused.
        String::from_utf8(fixture("spawn-receipt-created-v155.json")).unwrap(),
        json!({"id": "thr_syn_0021", "projectId": "prj_syn_0001", "status": "pending"}).to_string(),
        // #949: only id and projectId are read; any other key, of any type,
        // is not drift (an additive room-cli release must not break new).
        with(&receipt, "unexpected", json!(true)),
        with(&receipt, "thread", json!({})),
        with(
            &receipt,
            "syntheticExtraField",
            json!([{"a": null}, 1.5, "x"]),
        ),
        with(&receipt, "createdAt", json!("1700000600000")),
        with(&receipt, "canSpawnChild", json!("true")),
        with(&receipt, "title", json!(7)),
        with(&receipt, "status", Value::Null),
        with(&receipt, "purpose", json!("Synthetic purpose")),
    ];
    for row in &good {
        assert_eq!(
            spawn_receipt(row.as_bytes(), "prj_syn_0001"),
            SpawnReply::Created {
                thread_id: "thr_syn_0021".to_owned()
            },
            "{row}"
        );
    }
    let bad = [
        SOLS_RECEIPT.to_owned(),
        twice(&text, "\"id\":", "\"id\":\"thr_syn_0099\",\"id\":"),
        twice(&text, "\"id\":", "\"id\":\"thr_syn_0021\",\"id\":"),
        twice(
            &text,
            "\"projectId\":",
            "\"projectId\":\"prj_syn_0002\",\"projectId\":",
        ),
        twice(&text, "\"title\":", "\"title\":\"Synthetic\",\"title\":"),
        twice(
            &documented.to_string(),
            "\"percent\":",
            "\"percent\":1,\"percent\":",
        ),
        without(&receipt, "id"),
        without(&receipt, "projectId"),
        Value::Array(receipt.as_object().unwrap().values().cloned().collect()).to_string(),
        json!({"thread": receipt}).to_string(),
        json!({"created": receipt}).to_string(),
        with(&receipt, "id", json!(21)),
        with(&receipt, "projectId", json!({"id": "prj_syn_0001"})),
        with(&receipt, "id", Value::Null),
        with(&receipt, "projectId", Value::Null),
        // #949: a key given twice inside a key OpenWiz does not read.
        twice(
            &with(&receipt, "syntheticExtraField", json!({"x": 1})),
            "\"x\":",
            "\"x\":2,\"x\":",
        ),
    ];
    for row in &bad {
        let reply = spawn_receipt(row.as_bytes(), "prj_syn_0001");
        let SpawnReply::Unclear { reason, gaps } = &reply else {
            panic!("accepted: {row}\n{reply:?}")
        };
        assert_eq!(*reason, UncertainReason::UnexpectedReceipt, "{row}");
        let shown = format!("{gaps:?}");
        for echoed in [
            "thr_syn_wrong",
            "prj_syn_wrong",
            "thr_syn_0099",
            "unexpected",
        ] {
            assert!(!shown.contains(echoed), "{echoed} echoed: {shown}");
        }
    }
}

#[test]
fn sols_duplicate_receipt_is_uncertain_and_keeps_the_prompt() {
    let fake = NewFake::with(
        "r2_receipt",
        vec![json!({"any_spawn": true, "stdout": SOLS_RECEIPT, "creates": true})],
    );
    let args = new_args(
        "Synthetic project one",
        "op-r2-receipt",
        &["--json"],
        "Synthetic",
    );
    let (code, json) = json_of(&fake.run_process(&args, ""));
    assert_eq!(code, Some(6), "{json}");
    assert_eq!(json["status"], "uncertain");
    assert_eq!(json["result"]["outcome"]["reason"], "unexpected_receipt");
    assert_eq!(fake.record("op-r2-receipt")["text"], "Synthetic");
    assert_eq!(fake.spawn_count(), 1, "nothing was sent again");
}

// #606 evidence: synthetic fixtures/mutation only; no live behaviour claim.
// Base: 84da996d2fbbfa383735d4cc9d41e6daa53c440e, Rust 1.99.1, two build jobs.
// Disposable-copy plant: clone KeysOnceVisitor as ReceiptKeysOnceVisitor,
// replace its map.next_value::<KeysOnce>() with serde_json::Value, and use
// that visitor only in ObjectKeysOnce. Shared KeysOnce and shallow receipt
// duplicate checks stay intact. No production mutation lands on this branch.
// Before adding this test, under that plant:
// cargo test --locked -p openwiz-tests --test new-thread
// test result: ok. 152 passed; 0 failed; 0 ignored; 0 filtered out.
// After adding this test, under the same plant:
// cargo test --locked -p openwiz-tests --test new-thread \
//   boundary_readers::nested_duplicate_receipt_is_uncertain_through_cli -- --exact
// exit 101; left: Some(0), right: Some(6); 0 passed; 1 failed; 152 filtered out.
// Restoring pristine production, the same exact command exits 0:
// test result: ok. 1 passed; 0 failed; 0 ignored; 152 filtered out.
// Helper: Scout, boundary-reader/CLI seam, at the base above; PASS (read only).
// Used 5 pointers, ignored 2, wrong 0; builder checked the used pointers.
// No-push: clean #606: nothing changed but the writes you named (branches 0,
// comments 5). Helper archived before the check.
#[test]
fn nested_duplicate_receipt_is_uncertain_through_cli() {
    // Keep this as JSON text: Value would silently discard the first x.
    let receipt =
        r#"{"id":"thr_syn_0021","projectId":"prj_syn_0001","purpose":{"detail":{"x":1,"x":2}}}"#;
    let fake = NewFake::with(
        "nested_receipt",
        vec![json!({"any_spawn": true, "stdout": receipt, "creates": true})],
    );
    let args = new_args(
        "Synthetic project one",
        "op-nested-receipt",
        &["--json"],
        "Synthetic prompt retained after receipt drift.",
    );
    let (code, report) = json_of(&fake.run_process(&args, ""));
    assert_eq!(code, Some(6), "{report}");
    assert_eq!(report["status"], "uncertain");
    assert_eq!(report["result"]["outcome"]["reason"], "unexpected_receipt");
    assert_eq!(
        fake.record("op-nested-receipt")["text"],
        "Synthetic prompt retained after receipt drift."
    );
    assert_eq!(fake.spawn_count(), 1, "nothing was sent again");
}

fn catalogue_text() -> String {
    String::from_utf8(fixture("cloud-status.json")).unwrap()
}

fn the_catalogue_table() {
    let catalogue = fixture_json("cloud-status.json");
    let compact = catalogue.to_string();
    // A-2: everything outside the catalogue keys is dropped unread, at
    // every level, whatever its type.
    let mut planted = catalogue.clone();
    planted["account"] = json!({"email": "synthetic-account-marker"});
    planted["planUsage"] = json!("Synthetic plan text");
    planted["harnesses"][0]["secretToken"] = json!(["Synthetic"]);
    planted["harnesses"][0]["models"][0]["syntheticOwner"] = json!({"x": 1});
    planted["harnesses"][0]["attachments"]["audio"] = json!("Synthetic");
    let mut nulls = catalogue.clone();
    nulls["harnesses"][0]["attachments"] = Value::Null;
    nulls["harnesses"][0]["steer"] = Value::Null;
    nulls["harnesses"][3]["models"] = Value::Null;
    let good = [
        catalogue_text(),
        compact.clone(),
        planted.to_string(),
        nulls.to_string(),
    ];
    for doc in &good {
        assert!(parse_catalogue(doc.as_bytes()).is_ok(), "{doc}");
    }
    let row = |i: usize, key: &str, value: Value| {
        let mut v = catalogue.clone();
        v["harnesses"][i][key] = value;
        v.to_string()
    };
    let entry = |key: &str, value: Value| {
        let mut v = catalogue.clone();
        v["harnesses"][0]["models"][0][key] = value;
        v.to_string()
    };
    let drop_row_key = |key: &str| {
        let mut v = catalogue.clone();
        v["harnesses"][0].as_object_mut().unwrap().remove(key);
        v.to_string()
    };
    let drop_entry_key = |key: &str| {
        let mut v = catalogue.clone();
        v["harnesses"][0]["models"][0]
            .as_object_mut()
            .unwrap()
            .remove(key);
        v.to_string()
    };
    let bad = [
        // Sol's counterexample, in the file as it is written.
        twice(
            &catalogue_text(),
            "\"ready\": true",
            "\"ready\": false, \"ready\": true",
        ),
        twice(&compact, "\"ready\":", "\"ready\":true,\"ready\":"),
        twice(
            &compact,
            "\"harnesses\":",
            "\"harnesses\":null,\"harnesses\":",
        ),
        twice(
            &compact,
            "\"id\":\"codex\"",
            "\"id\":\"pi\",\"id\":\"codex\"",
        ),
        twice(
            &compact,
            "{\"model\":\"syn-codex-model-01\"",
            "{\"model\":\"syn-codex-model-02\",\"model\":\"syn-codex-model-01\"",
        ),
        twice(&compact, "\"files\":true", "\"files\":false,\"files\":true"),
        twice(&compact, "\"steer\":", "\"steer\":false,\"steer\":"),
        twice(
            &compact,
            "\"signingIn\":",
            "\"signingIn\":true,\"signingIn\":",
        ),
        without(&catalogue, "ready"),
        without(&catalogue, "harnesses"),
        Value::Array(catalogue.as_object().unwrap().values().cloned().collect()).to_string(),
        json!({"catalogue": catalogue}).to_string(),
        with(&catalogue, "ready", json!("true")),
        with(&catalogue, "ready", json!({"true": null})),
        with(
            &catalogue,
            "harnesses",
            json!({"codex": catalogue["harnesses"][0]}),
        ),
        with(&catalogue, "harnesses", json!([["codex"]])),
        with(
            &catalogue,
            "harnesses",
            json!([{"codex": catalogue["harnesses"][0]}]),
        ),
        row(0, "id", json!(5)),
        row(0, "model", json!(["syn-codex-default"])),
        row(0, "model", json!({"syn-codex-default": null})),
        row(0, "reasoning_levels", json!({"high": true})),
        row(0, "reasoning_levels", json!([1, 2])),
        row(0, "models", json!({"syn-codex-model-01": ["high"]})),
        row(0, "attachments", json!({"files": "yes", "images": true})),
        row(0, "attachments", json!([true, true])),
        row(0, "steer", json!("yes")),
        drop_row_key("id"),
        drop_row_key("model"),
        drop_row_key("reasoning_levels"),
        entry("model", json!(3)),
        entry("reasoning_levels", json!("high")),
        drop_entry_key("reasoning_levels"),
        drop_entry_key("model"),
    ];
    for doc in &bad {
        assert!(
            matches!(
                parse_catalogue(doc.as_bytes()),
                Err(SourceError::Malformed { .. })
            ),
            "accepted: {doc}"
        );
    }
}

#[test]
fn sols_duplicate_ready_offers_nothing_and_creates_nothing() {
    let doc = twice(
        &catalogue_text(),
        "\"ready\": true",
        "\"ready\": false, \"ready\": true",
    );
    let fake = NewFake::with(
        "r2_catalogue",
        vec![json!({"argv": ["cloud", "status", "--json"], "stdout": doc})],
    );
    let (code, models) = json_of(&fake.run_process(&["models", "--json"], ""));
    assert_eq!(code, Some(13), "{models}");
    assert_eq!(models["state"]["reason"], "unexpected_shape");
    let args = new_args(
        "Synthetic project one",
        "op-r2-catalogue",
        &["--json"],
        "Synthetic",
    );
    let (code, json) = json_of(&fake.run_process(&args, ""));
    assert_eq!(code, Some(5), "{json}");
    assert_eq!(json["result"]["outcome"]["reason"], "no_options");
    assert_eq!(fake.spawn_count(), 0, "nothing was dispatched");
}

/// The other reads a create makes: the project list (which decides where a
/// create may go), and the start's `thread show` and the observations'
/// `thread list` (shown only). A key given twice anywhere refuses the read,
/// rather than keep one of the two silently.
#[test]
fn the_other_reads_refuse_a_key_given_twice() {
    use openwiz_adapter_cloudroom::new_thread::{
        parse_observed_threads, parse_projects, parse_shown_thread,
    };
    use openwiz_core::model::Timestamp;

    let projects = project_list().to_string();
    assert!(parse_projects(projects.as_bytes()).is_ok());
    let flipped = twice(
        &projects,
        "\"kind\":\"personal\"",
        "\"kind\":\"personal\",\"kind\":\"standard\"",
    );
    assert!(parse_projects(flipped.as_bytes()).is_err(), "{flipped}");

    let shown = fixture_json("thread-show-error.json").to_string();
    assert!(parse_shown_thread(shown.as_bytes(), THREAD).is_ok());
    let flipped = twice(&shown, "\"status\":", "\"status\":\"active\",\"status\":");
    assert!(parse_shown_thread(flipped.as_bytes(), THREAD).is_err());

    let list = fixture_json("thread-list.json").to_string();
    let since = Timestamp(0);
    assert!(parse_observed_threads(list.as_bytes(), PROJECT, since).is_ok());
    let flipped = twice(
        &list,
        "\"projectId\":",
        "\"projectId\":\"prj_syn_0004\",\"projectId\":",
    );
    assert!(parse_observed_threads(flipped.as_bytes(), PROJECT, since).is_err());

    // Through the CLI: a project list with a flipped kind creates nothing.
    let fake = NewFake::with(
        "r2_projects",
        vec![json!({
            "argv": ["project", "list", "--json", "--include-personal"],
            "stdout": twice(
                &projects,
                "\"kind\":\"standard\"",
                "\"kind\":\"personal\",\"kind\":\"standard\"",
            ),
        })],
    );
    let args = new_args(
        "Synthetic project one",
        "op-r2-projects",
        &["--json"],
        "Synthetic",
    );
    let (code, json) = json_of(&fake.run_process(&args, ""));
    assert_eq!(code, Some(5), "{json}");
    assert_eq!(json["result"]["outcome"]["reason"], "projects_not_read");
    assert_eq!(fake.spawn_count(), 0);
}

#[test]
fn thread_show_distinguishes_not_found_from_other_command_failures() {
    use openwiz_core::new_thread::operation::NewThreadClient;
    use std::time::{Duration, Instant};

    for (name, stderr, not_found) in [
        ("show_404", "Error: HTTP 404: Thread not found", true),
        ("show_500", "Error: HTTP 500: Temporary failure", false),
    ] {
        let fake = NewFake::with(
            name,
            vec![json!({
                "argv": ["thread", "show", THREAD, "--json"],
                "stderr": stderr,
                "exit": 1,
            })],
        );
        let result = fake
            .source()
            .show_thread(THREAD, Instant::now() + Duration::from_secs(5));
        if not_found {
            assert!(
                matches!(result, Err(SourceError::NotFound { ref subject })
                if subject == THREAD),
                "{stderr}: {result:?}"
            );
        } else {
            assert!(
                matches!(result, Err(SourceError::CommandFailed {
                exit_code: Some(1), ref detail,
            }) if detail == "output withheld"),
                "{stderr}: {result:?}"
            );
        }
    }
}
