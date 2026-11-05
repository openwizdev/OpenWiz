//! Schema parity (Sol round 1, finding 2): `contracts/prompt.v1.schema.json`
//! and `contracts/new-thread.v1.schema.json` accept exactly what the Rust
//! core accepts, for the prompt text, the op id, the attachment id, the
//! three settings and the project reference. The schemas use `pattern` and
//! the companion `maxUtf8Bytes`, enforced by [`crate::pattern`].
//! The text table also checks messaging request text through the shared checker (#1889).

use openwiz_core::messaging::{MAX_TEXT_BYTES, OpId, validate_text};
use openwiz_core::new_thread::ProjectRef;
use openwiz_core::prompt::{AttachmentId, PromptPayload};
use serde_json::{Value, json};

use crate::pattern;
use crate::support::*;

fn prompt_schema() -> Value {
    serde_json::from_str(&std::fs::read_to_string(PROMPT_SCHEMA).unwrap()).unwrap()
}

fn messaging_request_schema() -> Value {
    at(
        serde_json::from_str(
            &std::fs::read_to_string(format!("{ROOT}/contracts/messaging.v1.schema.json")).unwrap(),
        )
        .unwrap(),
        "request",
    )
}

fn at(mut schema: Value, def: &str) -> Value {
    schema["$ref"] = json!(format!("#/$defs/{def}"));
    schema
}

fn schema_accepts(schema: &Value, value: &Value) -> bool {
    pattern::validate(schema, value).is_empty()
}

fn texts() -> Vec<(String, bool)> {
    let mut t: Vec<(String, bool)> = [
        ("Synthetic", true),
        (" Synthetic padded ", true),
        ("-leading dash", true),
        ("Line one\nLine two", true),
        ("\u{FEFF}", true),
        ("\u{200B}", true),
        ("Synthétique 合成 🧪", true),
        ("", false),
        (" ", false),
        ("\t\n\r\u{B}\u{C}", false),
        ("\u{85}", false),
        ("\u{A0}", false),
        ("\u{3000}", false),
        ("\u{2028}\u{2029}", false),
        ("a\u{0}b", false),
        ("\u{0}", false),
    ]
    .iter()
    .map(|(s, expected)| (s.to_string(), *expected))
    .collect();
    t.push(("a".repeat(MAX_TEXT_BYTES), true));
    t.push(("a".repeat(MAX_TEXT_BYTES + 1), false));
    t.push(("é".repeat(MAX_TEXT_BYTES / 2), true));
    t.push(("é".repeat(MAX_TEXT_BYTES / 2 + 1), false));
    t.push(("🧪".repeat(MAX_TEXT_BYTES / 4), true));
    t.push(("🧪".repeat(MAX_TEXT_BYTES / 4 + 1), false));
    t.push((format!("{} x", " ".repeat(MAX_TEXT_BYTES - 2)), true));
    t
}

fn label(s: &str) -> String {
    if s.len() > 40 {
        format!("{} chars, {} bytes", s.chars().count(), s.len())
    } else {
        format!("{s:?}")
    }
}

#[test]
fn schema_parity_contracts_preserve_all_original_cases() {
    let cases: [(&str, fn()); 8] = [
        ("attachment_ids_match_rust", attachment_ids_match_rust),
        ("both_contracts_lint_clean", both_contracts_lint_clean),
        ("op_ids_match_rust", op_ids_match_rust),
        (
            "patterns_under_one_of_are_enforced",
            patterns_under_one_of_are_enforced,
        ),
        (
            "project_references_match_rust",
            project_references_match_rust,
        ),
        ("settings_match_rust", settings_match_rust),
        (
            "the_prompt_text_matches_rust_in_both_contracts",
            the_prompt_text_matches_rust_in_both_contracts,
        ),
        (
            "the_round_1_counterexamples_are_refused",
            the_round_1_counterexamples_are_refused,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: schema_parity::{name}");
        proof();
    }
}

fn both_contracts_lint_clean() {
    assert_eq!(pattern::lint(&prompt_schema()), Vec::<String>::new());
    assert_eq!(pattern::lint(&schema()), Vec::<String>::new());
    assert_eq!(
        crate::schema::lint(&messaging_request_schema()),
        Vec::<String>::new()
    );
}

// The same literal controls must agree across send and new-thread requests.
// Previously this table never exercised messaging, so its length-only text
// rule accepted whitespace and NULs despite the runtime refusing both.
fn the_prompt_text_matches_rust_in_both_contracts() {
    let messaging = messaging_request_schema();
    for (text, expected) in texts() {
        let rust = PromptPayload::text(text.clone()).validate().is_ok();
        assert_eq!(rust, expected, "prompt runtime: {}", label(&text));
        assert_eq!(
            validate_text(&text).is_ok(),
            expected,
            "messaging runtime: {}",
            label(&text)
        );
        let value = json!({"text": text, "attachments": []});
        assert_eq!(
            schema_accepts(&prompt_schema(), &value),
            rust,
            "prompt.v1: {}",
            label(&text)
        );
        let request = json!({
            "target": "thr_syn_0001", "mode": "queue",
            "text": text, "op_id": "op-synthetic"
        });
        assert_eq!(
            crate::schema::validate(&messaging, &request).is_empty(),
            expected,
            "messaging request: {}",
            label(&text)
        );
        assert_eq!(
            schema_accepts(&at(schema(), "prompt"), &value),
            rust,
            "new-thread prompt: {}",
            label(&text)
        );
    }
}

/// Every single character, as a whole prompt: the schema's whitespace and
/// NUL rules are Rust's, character for character.
#[test]
fn every_single_character_prompt_matches_rust() {
    let schema = prompt_schema();
    let p = schema
        .pointer("/$defs/prompt/properties/text/pattern")
        .and_then(Value::as_str)
        .expect("a text pattern");
    let p = pattern::Pattern::new(p);
    // Every code point, in four ranges at once (#1260).
    std::thread::scope(|scope| {
        for part in 0..4u32 {
            let p = &p;
            scope.spawn(move || {
                let range = (part * 0x11_0000 / 4)..((part + 1) * 0x11_0000 / 4);
                for c in range.filter_map(char::from_u32) {
                    let text = c.to_string();
                    let rust = PromptPayload::text(text.clone()).validate().is_ok();
                    assert_eq!(p.is_match(&text), rust, "U+{:04X}", c as u32);
                }
            });
        }
    });
}

fn op_ids_match_rust() {
    let long = "a".repeat(64);
    let longer = "a".repeat(65);
    for id in [
        "op-1",
        "A",
        "0-0",
        long.as_str(),
        "",
        "../x",
        "-a",
        "_a",
        "a b",
        "é",
        "a/b",
        longer.as_str(),
    ] {
        assert_eq!(
            schema_accepts(&at(schema(), "op_id"), &json!(id)),
            OpId::parse(id).is_ok(),
            "{id:?}"
        );
    }
}

fn attachment_ids_match_rust() {
    let longer = "a".repeat(65);
    for id in [
        "att-syn-0001",
        "A_1",
        "",
        "-a",
        "_a",
        "../x",
        "a b",
        longer.as_str(),
    ] {
        assert_eq!(
            schema_accepts(&at(prompt_schema(), "attachment_id"), &json!(id)),
            AttachmentId::parse(id).is_ok(),
            "{id:?}"
        );
    }
}

fn settings_match_rust() {
    let long = "x".repeat(128);
    let longer = "x".repeat(129);
    for value in [
        "codex",
        "syn-codex-model-01",
        "syn-model[1m]",
        "!",
        "~",
        long.as_str(),
        "",
        "--model",
        "-x",
        "a b",
        "é",
        "a\tb",
        "a\u{7F}",
        longer.as_str(),
    ] {
        let mut r = request(offered(), "Synthetic", "op-parity");
        r.settings.model = value.to_owned();
        assert_eq!(
            schema_accepts(&at(schema(), "setting"), &json!(value)),
            r.validate().is_ok(),
            "{value:?}"
        );
    }
}

fn project_references_match_rust() {
    for value in [
        "prj_syn_0001",
        "Synthetic shared~000005",
        "Synthétique 🧪",
        "",
        " ",
        "\u{3000}",
        "a\u{0}b",
    ] {
        for (kind, reference) in [
            ("id", ProjectRef::Id(value.to_owned())),
            ("name", ProjectRef::Name(value.to_owned())),
        ] {
            let mut r = request(offered(), "Synthetic", "op-parity");
            r.project = reference;
            assert_eq!(
                schema_accepts(
                    &at(schema(), "project_ref"),
                    &json!({"kind": kind, "value": value})
                ),
                r.validate().is_ok(),
                "{kind} {value:?}"
            );
        }
    }
}

/// Sol's counterexamples, each refused by the schema as by Rust.
fn the_round_1_counterexamples_are_refused() {
    let valid = json!({
        "project": {"kind": "id", "value": "prj_syn_0001"},
        "harness": "codex",
        "model": "syn-codex-model-01",
        "effort": "high",
        "prompt": {"text": "Synthetic", "attachments": []},
        "op_id": "op-1",
    });
    assert!(schema_accepts(&at(schema(), "request"), &valid));
    for (pointer, bad) in [
        ("/prompt/text", json!(" \t\n")),
        ("/prompt/text", json!("a\u{0}b")),
        ("/prompt/text", json!("a".repeat(MAX_TEXT_BYTES + 1))),
        ("/op_id", json!("../x")),
        ("/model", json!("--model")),
        ("/harness", json!("a b")),
        ("/effort", json!("é")),
    ] {
        let mut value = valid.clone();
        *value.pointer_mut(pointer).unwrap() = bad;
        assert!(
            !schema_accepts(&at(schema(), "request"), &value),
            "accepted at {pointer}: {}",
            label(&value.to_string())
        );
    }
}

/// A pattern under a `oneOf` branch is enforced: a status read whose report
/// carries an unsafe op id is refused.
fn patterns_under_one_of_are_enforced() {
    let client = FakeClient::new();
    let store = MemoryStore::new();
    let report = create(
        &client,
        &store,
        &request(offered(), "Synthetic", "op-parity-one-of"),
    );
    let mut status = json!({
        "schema": "openwiz.new-thread-status.v1",
        "op_id": "op-parity-one-of",
        "result": {"kind": "recorded", "report": report, "start": null, "observations": null},
    });
    assert!(schema_accepts(&at(schema(), "status_read"), &status));
    status["result"]["report"]["op_id"] = json!("../x");
    assert!(!schema_accepts(&at(schema(), "status_read"), &status));
    status["result"]["report"]["op_id"] = json!("op-parity-one-of");
    status["result"]["report"]["text_sha256"] = json!("Z".repeat(64));
    assert!(!schema_accepts(&at(schema(), "status_read"), &status));
}
