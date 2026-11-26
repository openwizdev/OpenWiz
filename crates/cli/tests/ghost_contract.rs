#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../../../tests/support/schema.rs"]
mod schema;

use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{Value, json};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace root")
        .to_path_buf()
}

fn read_json(rel: &str) -> Value {
    let path = repo_root().join(rel);
    let text = fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("failed to read {}: {e}", path.display()));
    serde_json::from_str(&text)
        .unwrap_or_else(|e| panic!("invalid JSON in {}: {e}", path.display()))
}

fn load_ghost_schema() -> Value {
    read_json("contracts/ghost.v1.schema.json")
}

fn validate_def(root: &Value, def_name: &str, value: &Value) -> Vec<String> {
    let mut wrapped = root.clone();
    wrapped
        .as_object_mut()
        .expect("schema is an object")
        .insert(
            "$ref".to_owned(),
            Value::String(format!("#/$defs/{def_name}")),
        );
    schema::validate(&wrapped, value)
}

#[test]
fn schema_lints_cleanly() {
    let s = load_ghost_schema();
    let errors = schema::lint(&s);
    assert!(
        errors.is_empty(),
        "schema lint errors:\n{}",
        errors.join("\n")
    );
}

#[test]
fn contract_doc_names_required_sections_and_rules() {
    let path = repo_root().join("contracts/ghost.v1.md");
    let doc = fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("failed to read {}: {e}", path.display()));
    for needle in [
        "openwiz.ghost.v1",
        "POST /ghost/v1/pair",
        "POST /ghost/v1/health",
        "POST /ghost/v1/context",
        "POST /ghost/v1/turns",
        "POST /ghost/v1/complete",
        "POST /ghost/v1/draft",
        "POST /ghost/v1/feedback",
        "POST /ghost/v1/bench",
        "127.0.0.1",
        "wizsite.pages.dev",
        "stdio",
        "openwiz ghost serve",
        "openwiz ghost --stdio",
        "openwiz ghost pair",
        "openwiz ghost bench",
        "openwiz ghost forget",
        "## Composer rules",
        "typed_over",
        "HTTP-only",
        "replay_path",
    ] {
        assert!(
            doc.contains(needle),
            "contracts/ghost.v1.md missing {needle:?}"
        );
    }
}

#[test]
fn golden_fixtures_validate_against_schema() {
    let s = load_ghost_schema();

    let context_pack = read_json("contracts/fixtures/ghost/context-pack.json");
    let errs = validate_def(&s, "context_pack", &context_pack);
    assert!(
        errs.is_empty(),
        "context-pack.json invalid:\n{}",
        errs.join("\n")
    );

    let recall = read_json("contracts/fixtures/ghost/recall-cases.json");
    let errs = validate_def(&s, "recall_fixture_set", &recall);
    assert!(
        errs.is_empty(),
        "recall-cases.json invalid:\n{}",
        errs.join("\n")
    );

    let replay = read_json("contracts/fixtures/ghost/replay-set.json");
    let errs = validate_def(&s, "replay_fixture_set", &replay);
    assert!(
        errs.is_empty(),
        "replay-set.json invalid:\n{}",
        errs.join("\n")
    );

    let samples = read_json("contracts/fixtures/ghost/messages.json");
    let map = samples
        .as_object()
        .expect("messages.json must be an object");
    for def in [
        "pair_request",
        "pair_response",
        "health_request",
        "health_response",
        "context_request",
        "context_response",
        "turns_request",
        "turns_response",
        "complete_request",
        "complete_response",
        "draft_request",
        "draft_response",
        "feedback_request",
        "feedback_response",
        "bench_request",
        "bench_response",
        "refusal",
        "stdio_request",
        "stdio_response",
        "event",
        "bench_report",
    ] {
        let sample = map
            .get(def)
            .unwrap_or_else(|| panic!("messages.json missing sample for {def}"));
        let errs = validate_def(&s, def, sample);
        assert!(
            errs.is_empty(),
            "sample {def} invalid:\n{}",
            errs.join("\n")
        );
    }
}

#[test]
fn recall_fixtures_cover_spec_table_and_interactions() {
    let recall = read_json("contracts/fixtures/ghost/recall-cases.json");
    let cases = recall["cases"].as_array().expect("cases array");

    let expected_rows: &[(&str, Option<&str>)] = &[
        ("J1", Some("J1 all recs")),
        ("approve #4", Some("approve #42 and merge")),
        ("ship magic", Some("ship magic-link sign-in")),
        ("all r", Some("all recs")),
        ("the seat bil", Some("the seat billing spec")),
        ("zzq", None),
    ];

    for (typed, expected_full) in expected_rows {
        let found = cases.iter().any(|case| {
            case["steps"].as_array().is_some_and(|steps| {
                steps.iter().any(|step| {
                    step["action"] == "type"
                        && step["expected_text"] == *typed
                        && match (expected_full, step["expected_ghost"].as_str()) {
                            (Some(full), Some(ghost)) => format!("{typed}{ghost}") == *full,
                            (None, None) => step["expected_ghost"].is_null(),
                            _ => false,
                        }
                })
            })
        });
        assert!(
            found,
            "recall-cases.json missing spec table row: typed={typed:?} expected={expected_full:?}"
        );
    }

    let has_action = |action: &str| {
        cases.iter().any(|c| {
            c["steps"]
                .as_array()
                .is_some_and(|s| s.iter().any(|st| st["action"] == action))
        })
    };
    assert!(has_action("accept_word"), "missing accept_word case");
    assert!(has_action("accept_all"), "missing accept_all case");
    assert!(has_action("dismiss"), "missing dismiss (Esc) case");

    let has_typed_through_no_request = cases.iter().any(|c| {
        c["steps"].as_array().is_some_and(|s| {
            s.iter()
                .any(|st| st["action"] == "type" && st["expected_request"] == false)
        })
    });
    assert!(
        has_typed_through_no_request,
        "missing typed-through step with expected_request=false"
    );

    for outcome in [
        "shown",
        "accepted_all",
        "accepted_word",
        "typed_through",
        "dismissed",
        "typed_over",
    ] {
        let seen = cases.iter().any(|c| {
            c["steps"].as_array().is_some_and(|s| {
                s.iter().any(|st| {
                    st["expected_events"]
                        .as_array()
                        .is_some_and(|ev| ev.iter().any(|e| e == outcome))
                })
            })
        });
        assert!(
            seen,
            "recall-cases.json missing expected_events covering {outcome}"
        );
    }
}

#[test]
fn schema_rejects_malformed_samples() {
    let s = load_ghost_schema();

    let bad_extra = json!({"code": "123456", "surface": "cli", "extra": true});
    assert!(
        !validate_def(&s, "pair_request", &bad_extra).is_empty(),
        "extra field should be rejected"
    );

    let bad_refusal = json!({"refusal": {"code": "made_up", "message": "nope"}});
    assert!(
        !validate_def(&s, "refusal", &bad_refusal).is_empty(),
        "unknown refusal code should be rejected"
    );

    let bad_event = json!({
        "schema": "openwiz.ghost.v1",
        "kind": "event",
        "at": "2026-11-24T12:00:00Z",
        "suggestion_id": "sug_syn_1",
        "session_id": "thr_syn_1",
        "surface": "openwiz-app",
        "outcome": "shown",
        "tier": "recall",
        "confidence": 1.5,
        "latency_ms": 1.0,
        "chars_accepted": 0
    });
    assert!(
        !validate_def(&s, "event", &bad_event).is_empty(),
        "confidence > 1.0 should be rejected"
    );

    let stdio_pair =
        json!({"id": "req_1", "route": "pair", "body": {"code": "SYN-1", "surface": "cli"}});
    assert!(
        !validate_def(&s, "stdio_request", &stdio_pair).is_empty(),
        "pair route over stdio should be rejected"
    );

    let empty_bench = json!({
        "schema": "openwiz.ghost.v1",
        "kind": "bench_report",
        "source": "fixtures",
        "messages": 0,
        "overall": {
            "shown": 0,
            "accepted": 0,
            "acceptance_rate": 0.0,
            "chars_saved_per_message": 0.0,
            "suggestions_per_message": 0.0,
            "p50_latency_ms": null,
            "p90_latency_ms": null
        },
        "per_tier": [],
        "per_surface": []
    });
    let errs = validate_def(&s, "bench_report", &empty_bench);
    assert!(
        errs.is_empty(),
        "bench_report with shown=0 and null latencies should be valid:\n{}",
        errs.join("\n")
    );
}

#[test]
fn cli_ghost_stubs_refuse_with_stable_exit_and_message() {
    let run_ghost = |args: &[&str]| -> (i32, String, String) {
        let os_args: Vec<OsString> = args.iter().map(OsString::from).collect();
        let mut out = Vec::new();
        let mut err = Vec::new();
        let code = openwiz_cli::ghost::run(&os_args, &mut out, &mut err);
        (
            code,
            String::from_utf8_lossy(&out).into_owned(),
            String::from_utf8_lossy(&err).into_owned(),
        )
    };

    for sub in ["serve", "--stdio", "pair", "bench", "forget"] {
        let (code, stdout, stderr) = run_ghost(&[sub]);
        assert_eq!(code, 5, "ghost {sub} should exit 5, stderr={stderr}");
        assert!(
            stderr.contains("not built yet") && stderr.contains(sub),
            "ghost {sub} stderr should mention not built yet and {sub}: {stderr}"
        );
        assert!(
            stdout.is_empty(),
            "ghost {sub} stdout should be empty in text mode"
        );
    }

    let (code, stdout, _stderr) = run_ghost(&["--help"]);
    assert_eq!(code, 0);
    for sub in ["serve", "--stdio", "pair", "bench", "forget"] {
        assert!(stdout.contains(sub), "ghost --help missing {sub}: {stdout}");
    }

    let (code, _stdout, _stderr) = run_ghost(&["nope"]);
    assert_eq!(code, 2, "unknown ghost subcommand should exit 2");
}
