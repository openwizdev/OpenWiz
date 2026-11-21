use serde_json::{Value, json};
use std::fs;

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

fn load(path: &str) -> Value {
    serde_json::from_str(&fs::read_to_string(format!("{ROOT}/{path}")).expect(path)).expect(path)
}

fn definition() -> Value {
    json!({
        "schema": "openwiz.loops.v1", "kind": "definition", "id": "loop-syn-1",
        "name": "Synthetic reminder", "owner": "synthetic-owner",
        "wake": {"kind": "interval", "every_ms": 60000, "anchor_ms": 0},
        "check": {"argv": ["sh", "loops/synthetic-check.sh"], "timeout_ms": 5000},
        "action": {"project": {"kind": "id", "value": "prj_syn_0001"},
            "harness": "codex", "model": "synthetic-model", "effort": "high",
            "brief": "Report only the synthetic finding."},
        "authority": {"approved_by": "synthetic-owner", "approval_ref": "synthetic-approval-1",
            "scope": "Notify the synthetic owner only."},
        "budget": {"window_ms": 3600000, "max_agent_starts": 4},
        "enabled": false, "mode": "shadow", "priority": "normal"
    })
}

fn run(result: Value) -> Value {
    json!({
        "schema": "openwiz.loops.v1", "kind": "run", "id": "run-syn-1",
        "loop_id": "loop-syn-1", "definition_revision": "synthetic-revision-1",
        "wake": {"kind": "interval", "due_at_ms": 60000},
        "started_at_ms": 60000, "updated_at_ms": 60010,
        "cost": {"kind": "unknown", "reason": "Not reported."},
        "result": result
    })
}

fn results() -> Vec<Value> {
    vec![
        json!({"kind": "checking"}),
        json!({"kind": "quiet"}),
        json!({"kind": "check_failed", "reason": "Synthetic nonzero exit."}),
        json!({"kind": "check_timed_out"}),
        json!({"kind": "shadow", "finding": "Synthetic work."}),
        json!({"kind": "deferred", "finding": "Synthetic work.", "reason": "Budget exhausted."}),
        json!({"kind": "not_created", "finding": "Synthetic work.", "op_id": "op-syn-1", "dispatch_at_ms": 60001, "reason": "New-thread confirmed no creation."}),
        json!({"kind": "dispatching", "finding": "Synthetic work.", "op_id": "op-syn-1", "dispatch_at_ms": 60001}),
        json!({"kind": "created", "finding": "Synthetic work.", "op_id": "op-syn-1", "dispatch_at_ms": 60001, "thread_id": "thr_syn_0001"}),
        json!({"kind": "refused", "finding": "Synthetic work.", "reason": "Synthetic refusal."}),
        json!({"kind": "uncertain", "finding": "Synthetic work.", "op_id": "op-syn-1", "dispatch_at_ms": 60001, "reason": "Receipt not confirmed."}),
    ]
}

fn validate(schema: &Value, value: &Value) -> Vec<String> {
    fn number_types(node: &mut Value) {
        match node {
            Value::Object(fields) => {
                if let Some(kind) = fields.get_mut("type") {
                    assert_ne!(
                        kind.as_str(),
                        Some("number"),
                        "numeric slots must all be integers"
                    );
                    assert!(!kind.is_array(), "add union-type support before using it");
                    if kind.as_str() == Some("integer") {
                        *kind = json!("number");
                    }
                }
                for child in fields.values_mut() {
                    number_types(child);
                }
            }
            Value::Array(items) => items.iter_mut().for_each(number_types),
            _ => {}
        }
    }
    fn fractions(value: &Value, path: &str, errors: &mut Vec<String>) {
        match value {
            Value::Number(n) if n.is_f64() && n.as_f64().unwrap().fract() != 0.0 => {
                errors.push(format!("{path}: a fractional number is not an integer"));
            }
            Value::Object(fields) => {
                for (key, child) in fields {
                    fractions(child, &format!("{path}.{key}"), errors);
                }
            }
            Value::Array(items) => {
                for (i, child) in items.iter().enumerate() {
                    fractions(child, &format!("{path}[{i}]"), errors);
                }
            }
            _ => {}
        }
    }
    let mut numeric_schema = schema.clone();
    number_types(&mut numeric_schema);
    let mut errors = crate::pattern::validate(&numeric_schema, value);
    fractions(value, "$", &mut errors);
    errors
}

fn verdict(schema: &Value, value: &Value, expected: bool, label: &str) {
    let errors = validate(schema, value);
    assert_eq!(errors.is_empty(), expected, "{label}: {value}\n{errors:#?}");
}

#[test]
fn loops_schema_definitions_and_records() {
    let schema = load("contracts/loops.v1.schema.json");
    assert_eq!(schema["title"], "openwiz.loops.v1");
    assert_eq!(crate::pattern::lint(&schema), Vec::<String>::new());
    let good = definition();
    verdict(&schema, &good, true, "interval definition");
    let mut v = good.clone();
    v["action"]["brief"] = json!("é".repeat(8193));
    verdict(&schema, &v, false, "brief byte cap");
    v["action"]["brief"] = json!("é".repeat(8192));
    verdict(&schema, &v, true, "brief byte boundary");
    for wake in [
        json!({"kind": "once", "at_ms": 60000}),
        json!({"kind": "event", "event": "github.pull_request_review"}),
        json!({"kind": "event", "event": "github.workflow_run"}),
        json!({"kind": "event", "event": "github.check_suite"}),
        json!({"kind": "event", "event": "github.issue_comment"}),
    ] {
        let mut v = good.clone();
        v["wake"] = wake;
        v["enabled"] = json!(true);
        v["mode"] = json!("active");
        v["priority"] = json!("urgent");
        verdict(&schema, &v, true, "wake variant");
    }
    let replacements = [
        ("/schema", json!("openwiz.loops.v2")),
        ("/kind", json!("unknown")),
        ("/id", json!("../loop")),
        ("/owner", json!(" ")),
        (
            "/wake",
            json!({"kind": "interval", "every_ms": 0, "anchor_ms": 0}),
        ),
        ("/wake", json!({"kind": "once", "at_ms": -1})),
        ("/wake", json!({"kind": "event", "event": "unknown"})),
        ("/check/timeout_ms", json!(0)),
        ("/check/timeout_ms", json!("5000")),
        ("/check/timeout_ms", json!(0.5)),
        ("/check/argv", json!([])),
        ("/check/argv", json!([""])),
        ("/action/brief", json!("\n\t")),
        ("/action/model", json!("--flag")),
        ("/action/effort", json!("é")),
        ("/action/project", json!({"kind": "id", "value": " "})),
        (
            "/authority",
            json!({"approved_by": "x", "approval_ref": "y", "scope": " "}),
        ),
        ("/budget/window_ms", json!(0)),
        ("/budget/max_agent_starts", json!(-1)),
        ("/enabled", json!("false")),
        ("/mode", json!({"shadow": null})),
        ("/priority", json!("unknown")),
    ];
    for (pointer, replacement) in replacements {
        let mut v = good.clone();
        *v.pointer_mut(pointer).expect(pointer) = replacement;
        verdict(&schema, &v, false, pointer);
    }
    for (pointer, key) in [
        ("/check", "timeout_ms"),
        ("", "authority"),
        ("/action", "project"),
        ("/action", "effort"),
        ("/authority", "approval_ref"),
        ("", "budget"),
        ("", "enabled"),
    ] {
        let mut v = good.clone();
        v.pointer_mut(pointer)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .remove(key);
        verdict(&schema, &v, false, key);
    }
    for pointer in ["", "/check", "/action", "/wake", "/authority", "/budget"] {
        let mut v = good.clone();
        v.pointer_mut(pointer)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert("unexpected".into(), json!(true));
        verdict(&schema, &v, false, "unknown definition field");
    }
    for result in results() {
        let v = run(result);
        verdict(&schema, &v, true, "run result");
        for key in v["result"].as_object().unwrap().keys() {
            let mut bad = v.clone();
            bad["result"].as_object_mut().unwrap().remove(key);
            verdict(&schema, &bad, false, "missing result field");
        }
        let mut bad = v.clone();
        bad["result"]["unexpected"] = json!(true);
        verdict(&schema, &bad, false, "unknown result field");
    }
    for wake in [
        json!({"kind": "once", "due_at_ms": 60000}),
        json!({"kind": "event", "event": "github.workflow_run", "event_id": "evt-syn-1"}),
    ] {
        let mut v = run(json!({"kind": "quiet"}));
        v["wake"] = wake;
        v["cost"] = json!({"kind": "known", "usd_micros": 0});
        verdict(&schema, &v, true, "record wake and known cost");
    }
    for (pointer, replacement) in [
        ("/result", json!({"kind": "shadow", "finding": ""})),
        ("/result", json!({"kind": "shadow", "finding": "a\0b"})),
        (
            "/result",
            json!({"kind": "quiet", "thread_id": "thr_syn_1"}),
        ),
        (
            "/result",
            json!({"kind": "created", "finding": "x", "op_id": "op-1"}),
        ),
        (
            "/result",
            json!({"kind": "uncertain", "finding": "x", "reason": "y"}),
        ),
        (
            "/result",
            json!({"kind": "created", "finding": "x", "op_id": "../op", "thread_id": "thr_syn_1"}),
        ),
        ("/result", json!({"kind": "unknown"})),
        ("/cost", json!({"kind": "unknown"})),
        ("/cost", json!({"kind": "known", "usd_micros": -1})),
        ("/started_at_ms", json!("60000")),
        (
            "/wake",
            json!({"kind": "event", "event": "github.workflow_run"}),
        ),
    ] {
        let mut v = run(json!({"kind": "quiet"}));
        *v.pointer_mut(pointer).unwrap() = replacement;
        verdict(&schema, &v, false, pointer);
    }
    for key in run(json!({"kind": "quiet"})).as_object().unwrap().keys() {
        let mut v = run(json!({"kind": "quiet"}));
        v.as_object_mut().unwrap().remove(key);
        verdict(&schema, &v, false, "missing record field");
    }
    verdict(&schema, &json!([]), false, "positional root");
    verdict(&schema, &json!(null), false, "null root");
}

#[test]
fn loops_schema_example_is_synthetic_and_valid() {
    let schema = load("contracts/loops.v1.schema.json");
    let example = load("loops/example.json");
    verdict(&schema, &example, true, "explicit example file");
    assert_eq!(example["enabled"], false);
    assert_eq!(example["mode"], "shadow");
    assert!(example["id"].as_str().unwrap().starts_with("loop-syn-"));
}
