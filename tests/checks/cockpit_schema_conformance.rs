//! CK1's contract half (#534). Inline response fixtures remain available
//! when CI prunes private evidence. All values and rich-source shapes are
//! synthetic; current upstream gaps are represented explicitly as unknown.
//!
//! #556 red-first proof (disposable copy; no production schema change):
//! `cargo test --locked -p openwiz-tests --test checks cockpit_schema_conformance`
//! With gap.kind replaced by {"type":"string"}, original: 6 passed (exit 0);
//! kind case added: 5 passed, 1 failed (exit 101), accepted /agents/coverage
//! with kind="bogus", detail="Synthetic gap". Evidence: fixture/schema only.
//! With gap.detail.minLength removed, original: 6 passed (exit 0);
//! detail case added: 5 passed, 1 failed (exit 101), accepted /agents/coverage
//! with kind="timed_out", detail="". Each guard was removed independently.
//! Restored schema: 6 passed, 0 failed (exit 0), after each mutation.
//! Full fleet set: all 12 commands passed at a013431c; private evidence pruned.

use std::collections::BTreeSet;

use serde_json::{Value, json};

use crate::schema::{lint, validate};

const CONTRACT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../contracts/cockpit.v1.md");
const SCHEMA: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../contracts/cockpit.v1.schema.json"
);

fn schema() -> Value {
    let text = std::fs::read_to_string(SCHEMA).expect("CK1: cockpit.v1 schema must exist");
    serde_json::from_str(&text).expect("CK1: schema must be JSON")
}

fn complete() -> Value {
    // synthetic_assumptions: rich wording/risk/age/start fields illustrate
    // the contract, not observations or fields current upstreams produce.
    json!({
        "schema": "openwiz.cockpit.v1",
        "snapshot_at": 1700000600000_i64,
        "projects": {
            "coverage": {"state": "complete", "gaps": []},
            "freshness": {"state": "fresh", "snapshot_at": {"known": 1700000600000_i64}},
            "items": [
                {"id": "prj_syn_0001", "name": {"known": "Synthetic project one"},
                 "orchestrator": {
                    "coverage": {"state": "complete", "gaps": []},
                    "freshness": {"state": "fresh", "snapshot_at": {"known": 1700000600000_i64}},
                    "target": {"known": "thr_syn_0001"}}},
                {"id": "prj_syn_0002", "name": {"known": "Synthetic project two"},
                 "orchestrator": {
                    "coverage": {"state": "complete", "gaps": []},
                    "freshness": {"state": "fresh", "snapshot_at": {"known": 1700000600000_i64}},
                    "target": {"known": null}}}
            ]
        },
        "needs_you": {
            "coverage": {"state": "complete", "gaps": []},
            "freshness": {"state": "fresh", "snapshot_at": {"known": 1700000600000_i64}},
            "items": [
                {"project": {"known": "prj_syn_0001"}, "kind": "needs_info", "spec": 901, "ticket": 902,
                 "wording": {"known": "Synthetic question: keep the local index?"},
                 "age_ms": {"known": 600000}, "risky": {"known": false}},
                {"project": {"known": "prj_syn_0002"}, "kind": "release", "spec": 911, "ticket": 912,
                 "wording": {"known": "Synthetic proposal: release the synthetic build."},
                 "age_ms": {"known": 300000}, "risky": {"known": true}}
            ]
        },
        "agents": {
            "coverage": {"state": "complete", "gaps": []},
            "freshness": {"state": "fresh", "snapshot_at": {"known": 1700000600000_i64}},
            "items": [
                {"thread": "thr_syn_0002", "project": {"known": "prj_syn_0001"},
                 "title": {"known": "Synthetic builder"}, "fleet": {"known": 901},
                 "ticket": {"known": 902}, "activity": "active", "model": {"known": "synthetic-model-a"},
                 "state": {"known": "building"},
                 "location": {"known": {"kind": "local", "machine": {"known": "Synthetic machine one"}}},
                 "started_at": {"known": 1700000000000_i64}},
                {"thread": "thr_syn_0003", "project": {"known": "prj_syn_0002"},
                 "title": {"known": "Synthetic builder two"}, "fleet": {"known": 911},
                 "ticket": {"known": 912}, "activity": "active", "model": {"known": "synthetic-model-b"},
                 "state": {"known": "in_review"}, "location": {"known": {"kind": "cloud"}},
                 "started_at": {"known": 1700000300000_i64}}
            ]
        }
    })
}

fn fixtures() -> Vec<(&'static str, Value)> {
    let mut partial = complete();
    partial["projects"]["coverage"] = json!({"state": "partial", "gaps": [
        {"project": "prj_syn_0002", "kind": "missing_field", "detail": "Synthetic project name unavailable"}
    ]});
    partial["needs_you"]["coverage"] = json!({"state": "partial", "gaps": [
        {"project": "prj_syn_0001", "kind": "unsupported", "detail": "Synthetic upstream lacks wording, risk and waiting age"},
        {"project": "prj_syn_0002", "kind": "unsupported", "detail": "Synthetic upstream lacks wording, risk and waiting age"}
    ]});
    for item in partial["needs_you"]["items"].as_array_mut().unwrap() {
        item["kind"] = json!("held");
        item["wording"] = json!({"unknown": "Synthetic upstream does not report proposal wording"});
        item["risky"] = json!({"unknown": "Synthetic upstream does not classify risk"});
        item["age_ms"] = json!({"unknown": "Synthetic upstream does not report waiting time"});
    }
    partial["agents"]["coverage"] = json!({"state": "partial", "gaps": [
        {"project": null, "kind": "unsupported", "detail": "Synthetic inventory lacks start time; one agent is unplaced"}
    ]});
    partial["agents"]["items"][0]["started_at"] =
        json!({"unknown": "Synthetic inventory has only update time"});
    let unplaced = &mut partial["agents"]["items"][1];
    for field in [
        "project",
        "title",
        "fleet",
        "ticket",
        "model",
        "state",
        "location",
        "started_at",
    ] {
        unplaced[field] = json!({"unknown": "Synthetic fact is unavailable"});
    }
    partial["projects"]["items"][1]["name"] =
        json!({"unknown": "Synthetic project name unavailable"});
    partial["projects"]["items"][1]["orchestrator"] = json!({
        "coverage": {"state": "partial", "gaps": [
            {"project": "prj_syn_0002", "kind": "timed_out", "detail": "Synthetic target check timed out"}
        ]},
        "freshness": {"state": "unknown", "snapshot_at": {"unknown": "Synthetic target never read"}},
        "target": {"unknown": "Synthetic target not verified"}
    });
    let mut stale = complete();
    for part in ["projects", "needs_you", "agents"] {
        stale[part]["freshness"] =
            json!({"state": "stale", "snapshot_at": {"known": 1700000500000_i64}});
    }
    for project in stale["projects"]["items"].as_array_mut().unwrap() {
        project["orchestrator"]["freshness"] =
            json!({"state": "stale", "snapshot_at": {"known": 1700000500000_i64}});
    }
    let mut empty = complete();
    for part in ["projects", "needs_you", "agents"] {
        empty[part]["items"] = json!([]);
    }
    vec![
        ("complete", complete()),
        ("partial", partial),
        ("stale", stale),
        ("empty", empty),
    ]
}

#[test]
fn cockpit_schema_uses_only_checked_keywords() {
    let schema = schema();
    assert_eq!(schema["title"], "openwiz.cockpit.v1");
    assert_eq!(lint(&schema), Vec::<String>::new());
    let errors = validate(&schema, &json!({}));
    assert!(
        !errors.is_empty(),
        "an empty object is not a cockpit response"
    );
    assert!(
        errors.iter().all(|e| !e.contains("unresolvable")),
        "{errors:#?}"
    );
}

#[test]
fn cockpit_complete_partial_stale_and_empty_responses_validate() {
    let schema = schema();
    let fixtures = fixtures();
    assert_eq!(fixtures.len(), 4);
    for (name, value) in &fixtures {
        let errors = validate(&schema, value);
        assert!(errors.is_empty(), "{name}: {errors:#?}");
    }
    // Empty arrays remain representable when reads are partial or stale.
    // The contract expressly forbids a verified-empty claim in these cases.
    for (name, mut value) in fixtures
        .into_iter()
        .filter(|(n, _)| *n == "partial" || *n == "stale")
    {
        value["needs_you"]["items"] = json!([]);
        assert!(validate(&schema, &value).is_empty(), "{name} empty");
    }
}

#[test]
fn cockpit_malformed_responses_fail() {
    let schema = schema();
    let good = complete();
    // These literals are independent examples of violations, not values
    // computed from the schema or an implementation under test.
    for (pointer, replacement) in [
        ("/schema", json!("openwiz.cockpit.v2")),
        ("/snapshot_at", json!(-1)),
        ("/snapshot_at", json!(1.5)),
        ("/snapshot_at", json!("1700000600000")),
        ("/projects/coverage/state", json!("unknown")),
        ("/projects/coverage/state", json!({"complete": null})),
        (
            "/projects/coverage/gaps",
            json!([{"project": null, "kind": "timed_out", "detail": "Synthetic gap"}]),
        ),
        ("/projects/items/0/id", json!("")),
        (
            "/projects/items/0/orchestrator/target",
            json!("thr_syn_0001"),
        ),
        ("/needs_you/freshness/state", json!("recent")),
        (
            "/needs_you/freshness/snapshot_at",
            json!({"unknown": "Synthetic no timestamp"}),
        ),
        ("/needs_you/items/0/project", json!("prj_syn_0001")),
        ("/needs_you/items/0/project", json!({"known": ""})),
        ("/needs_you/items/0/kind", json!({"held": null})),
        ("/needs_you/items/0/kind", json!("guessed")),
        ("/needs_you/items/0/spec", json!(0)),
        ("/needs_you/items/0/ticket", json!("902")),
        ("/needs_you/items/0/wording", json!({"known": ""})),
        ("/needs_you/items/0/age_ms", json!({"known": -1})),
        ("/needs_you/items/0/risky", json!(false)),
        ("/needs_you/items/1/risky", json!({"known": false})),
        (
            "/needs_you/items/1/risky",
            json!({"unknown": "Synthetic uncertain risk"}),
        ),
        ("/agents/items/0/thread", json!("")),
        ("/agents/items/0/activity", json!("idle")),
        ("/agents/items/0/model", json!({"known": null})),
        ("/agents/items/0/fleet", json!({"known": -1})),
        ("/agents/items/0/ticket", json!({"known": 0})),
        ("/agents/items/0/state", json!({"known": "MERGED"})),
        ("/agents/items/0/started_at", json!({"known": 1.5})),
        (
            "/agents/items/0/location",
            json!({"known": {"kind": "elsewhere"}}),
        ),
        (
            "/agents/items/0/location/known/machine",
            json!({"unknown": ""}),
        ),
        (
            "/agents/coverage",
            json!({"state": "partial", "gaps": [
                {"project": null, "kind": "bogus", "detail": "Synthetic gap"}
            ]}),
        ),
        (
            "/agents/coverage",
            json!({"state": "partial", "gaps": [
                {"project": null, "kind": "timed_out", "detail": ""}
            ]}),
        ),
    ] {
        let mut bad = good.clone();
        *bad.pointer_mut(pointer).unwrap() = replacement.clone();
        assert!(
            !validate(&schema, &bad).is_empty(),
            "accepted {pointer} = {replacement}"
        );
    }
    // Any exact object at any depth refuses a missing key, an extra key,
    // and a positional array. Exercise both known and unknown fixtures.
    fn objects(v: &Value, path: String, out: &mut Vec<String>) {
        match v {
            Value::Object(o) => {
                out.push(path.clone());
                for (key, value) in o {
                    objects(value, format!("{path}/{key}"), out);
                }
            }
            Value::Array(a) => {
                for (i, value) in a.iter().enumerate() {
                    objects(value, format!("{path}/{i}"), out);
                }
            }
            _ => {}
        }
    }
    for (name, good) in fixtures() {
        let mut paths = vec![];
        objects(&good, String::new(), &mut paths);
        for path in paths {
            let object = good.pointer(&path).unwrap().as_object().unwrap();
            for key in object.keys() {
                let mut bad = good.clone();
                bad.pointer_mut(&path)
                    .unwrap()
                    .as_object_mut()
                    .unwrap()
                    .remove(key);
                assert!(
                    !validate(&schema, &bad).is_empty(),
                    "{name}: missing {path}/{key}"
                );
            }
            for replacement in [
                {
                    let mut o = object.clone();
                    o.insert("unexpected".into(), json!(true));
                    Value::Object(o)
                },
                json!([]),
            ] {
                let mut bad = good.clone();
                *bad.pointer_mut(&path).unwrap() = replacement;
                assert!(
                    !validate(&schema, &bad).is_empty(),
                    "{name}: extra key/positional object {path}"
                );
            }
        }
    }
}

#[test]
fn cockpit_preserves_unknown_project_associations() {
    let schema = schema();
    let mut value = complete();
    value["needs_you"]["items"][0]["project"] =
        json!({"unknown": "Synthetic repository matches several projects"});
    value["needs_you"]["coverage"] = json!({"state": "partial", "gaps": [
        {"project": null, "kind": "unsupported", "detail": "Synthetic project mapping ambiguous"}
    ]});
    let errors = validate(&schema, &value);
    assert!(
        errors.is_empty(),
        "preserve the unassigned item: {errors:#?}"
    );
}

#[test]
fn cockpit_gap_project_cannot_be_empty() {
    let schema = schema();
    let mut value = complete();
    value["agents"]["coverage"] = json!({"state": "partial", "gaps": [
        {"project": "", "kind": "timed_out", "detail": "Synthetic timeout"}
    ]});
    assert!(
        !validate(&schema, &value).is_empty(),
        "accepted an empty project id in a gap"
    );
}

#[test]
fn cockpit_every_schema_field_has_a_source_row() {
    let schema = schema();
    let text = std::fs::read_to_string(CONTRACT).expect("cockpit contract");
    let rows: BTreeSet<_> = text
        .lines()
        .filter_map(|line| {
            let rest = line.strip_prefix("| `")?;
            let (field, source) = rest.split_once("` | ")?;
            assert!(
                !source.trim_matches([' ', '|']).is_empty(),
                "empty source for {field}"
            );
            Some(field.to_owned())
        })
        .collect();
    fn fields(v: &Value, name: &str, out: &mut BTreeSet<String>) {
        if let Some(p) = v.get("properties").and_then(Value::as_object) {
            for key in p.keys() {
                out.insert(format!("{name}.{key}"));
            }
        }
        if let Some(choices) = v.get("oneOf").and_then(Value::as_array) {
            for choice in choices {
                fields(choice, name, out);
            }
        }
    }
    let mut expected = BTreeSet::new();
    for (name, def) in schema["$defs"].as_object().unwrap() {
        fields(def, name, &mut expected);
    }
    assert_eq!(
        rows, expected,
        "trace every field exactly; no stale source rows"
    );
}
