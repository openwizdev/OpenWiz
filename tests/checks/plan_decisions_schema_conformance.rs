//! EP1 and EP3's contract halves (#651). These checks use the existing
//! dependency-free schema checker, not a producer or a live GitHub read.
//! All fixtures are synthetic. Semantics follow the ruling on #651.

use serde_json::{Value, json};
use std::collections::BTreeSet;

const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../contracts");

fn schema(name: &str) -> Value {
    let text = std::fs::read_to_string(format!("{ROOT}/{name}.v1.schema.json"))
        .unwrap_or_else(|error| panic!("{name}.v1 schema must exist: {error}"));
    serde_json::from_str(&text).expect("schema must be JSON")
}

fn checked_schema(name: &str, id: &str) {
    let schema = schema(name);
    assert_eq!(schema["title"], id);
    assert_eq!(lint(&schema), Vec::<String>::new());
    for malformed in [
        json!(null),
        json!(false),
        json!(1),
        json!("Synthetic non-record"),
        json!([]),
        json!([901, "Synthetic positional record"]),
        json!({}),
    ] {
        let errors = validate(&schema, &malformed);
        assert!(
            !errors.is_empty(),
            "{name} must refuse malformed root {malformed}"
        );
        assert!(
            errors.iter().all(|error| !error.contains("unresolvable")),
            "{errors:#?}"
        );
    }
}

// Reuse cockpit's field/source table convention. This compares two public
// contract artifacts without choosing any field or source for either one.
fn fields_have_sources(name: &str) {
    let text = std::fs::read_to_string(format!("{ROOT}/{name}.v1.md"))
        .unwrap_or_else(|error| panic!("{name}.v1 contract must exist: {error}"));
    let mut sections = text.split("\n## Field sources\n");
    sections.next().expect("contract preamble");
    let section = sections.next().expect("one Field sources section");
    assert!(sections.next().is_none(), "duplicate Field sources section");
    let section = section.split("\n## ").next().unwrap();
    let mut documented = BTreeSet::new();
    for line in section.lines() {
        let Some(rest) = line.strip_prefix("| `") else {
            continue;
        };
        let (field, source) = rest.split_once("` | ").expect("field source row");
        assert!(
            !source.trim_matches([' ', '|']).is_empty(),
            "empty source for {field}"
        );
        assert!(
            documented.insert(field.to_owned()),
            "duplicate row: {field}"
        );
    }
    fn fields(node: &Value, name: &str, out: &mut BTreeSet<String>) {
        if let Some(properties) = node.get("properties").and_then(Value::as_object) {
            for (key, child) in properties {
                let field = format!("{name}.{key}");
                out.insert(field.clone());
                fields(child, &field, out);
            }
        }
        if let Some(items) = node.get("items") {
            fields(items, &format!("{name}[]"), out);
        }
        if let Some(choices) = node.get("oneOf").and_then(Value::as_array) {
            for choice in choices {
                fields(choice, name, out);
            }
        }
    }
    let schema = schema(name);
    let mut expected = BTreeSet::new();
    fields(&schema, "root", &mut expected);
    if let Some(definitions) = schema.get("$defs").and_then(Value::as_object) {
        for (definition, node) in definitions {
            fields(node, definition, &mut expected);
        }
    }
    assert!(!expected.is_empty(), "schema must declare record fields");
    assert_eq!(documented, expected, "every field needs exactly one source");
}

#[test]
fn plan_schema_uses_only_checked_keywords() {
    checked_schema("plan", "openwiz.plan.v1");
}

#[test]
fn decisions_schema_uses_only_checked_keywords() {
    checked_schema("decisions", "openwiz.decisions.v1");
}

#[test]
fn plan_every_schema_field_has_a_source_row() {
    fields_have_sources("plan");
}

#[test]
fn decisions_every_schema_field_has_a_source_row() {
    fields_have_sources("decisions");
}

// maxItems is standard JSON Schema; the shared checker does not implement it.
// Check its form everywhere, then apply it at the same resolved schema nodes.
fn without_max_items(node: &Value, errors: &mut Vec<String>) -> Value {
    match node {
        Value::Object(map) => {
            if let Some(bound) = map.get("maxItems")
                && (map.get("type") != Some(&json!("array")) || bound.as_u64().is_none())
            {
                errors.push("maxItems must be an unsigned integer on an array".into());
            }
            Value::Object(
                map.iter()
                    .filter(|(key, _)| key.as_str() != "maxItems")
                    .map(|(key, value)| (key.clone(), without_max_items(value, errors)))
                    .collect(),
            )
        }
        Value::Array(items) => {
            Value::Array(items.iter().map(|v| without_max_items(v, errors)).collect())
        }
        other => other.clone(),
    }
}

fn lint(schema: &Value) -> Vec<String> {
    let mut errors = vec![];
    let stripped = without_max_items(schema, &mut errors);
    errors.extend(crate::pattern::lint(&stripped));
    errors
}

fn validate(schema: &Value, value: &Value) -> Vec<String> {
    let mut errors = vec![];
    let stripped = without_max_items(schema, &mut errors);
    errors.extend(crate::pattern::validate(&stripped, value));
    if !errors.is_empty() {
        return errors;
    }
    fn walk(root: &Value, node: &Value, at: &str, value: &Value, errors: &mut Vec<String>) {
        if let Some(reference) = node.get("$ref").and_then(Value::as_str) {
            let pointer = reference.strip_prefix('#').unwrap();
            walk(root, root.pointer(pointer).unwrap(), pointer, value, errors);
        }
        if let (Some(max), Some(items)) = (
            node.get("maxItems").and_then(Value::as_u64),
            value.as_array(),
        ) && items.len() as u64 > max
        {
            errors.push(format!("{at}: {} items exceeds {max}", items.len()));
        }
        if let (Some(props), Some(object)) = (
            node.get("properties").and_then(Value::as_object),
            value.as_object(),
        ) {
            for (key, child) in object {
                if let Some(next) = props.get(key) {
                    walk(root, next, &format!("{at}/properties/{key}"), child, errors);
                }
            }
        }
        if let (Some(items), Some(values)) = (node.get("items"), value.as_array()) {
            for item in values {
                walk(root, items, &format!("{at}/items"), item, errors);
            }
        }
        if let Some(branches) = node.get("oneOf").and_then(Value::as_array) {
            for (i, branch) in branches.iter().enumerate() {
                let pointer = format!("{at}/oneOf/{i}");
                let probe = json!({"$defs": root["$defs"], "$ref": format!("#{pointer}")});
                let stripped = without_max_items(&probe, &mut vec![]);
                if crate::pattern::validate(&stripped, value).is_empty() {
                    walk(root, branch, &pointer, value, errors);
                }
            }
        }
    }
    walk(schema, schema, "", value, &mut errors);
    errors
}

fn plan() -> Value {
    json!({
        "schema": "openwiz.plan.v1", "snapshot_at": 1700000100000_u64,
        "coverage": {"state": "complete", "gaps": []},
        "freshness": {"state": "fresh", "snapshot_at": {"known": 1700000090000_u64}},
        "lanes": [
            {"kind": "version", "number": 1, "title": {"known": "0.0.91"}},
            {"kind": "side_spec", "number": 940, "title": {"known": "Synthetic side spec"}}
        ],
        "tickets": [
            {"number": 902, "title": {"known": "Synthetic owner gate"},
             "url": {"known": "https://github.com/synthetic-owner/synthetic-project/issues/902"},
             "spec": {"known": 901}, "lane": {"known": {"kind": "version", "number": 1}},
             "state": {"unknown": "Human ticket has no fleet state"},
             "column": {"known": "needs_you"}, "labels": {"known": ["ready-for-human"]},
             "yours": {"known": true}, "blockers": {"known": []},
             "dependents": {"known": [942]}, "pr": {"known": null}},
            {"number": 942, "title": {"known": "Synthetic dependent"},
             "url": {"known": "https://github.com/synthetic-owner/synthetic-project/issues/942"},
             "spec": {"known": 940}, "lane": {"known": {"kind": "side_spec", "number": 940}},
             "state": {"known": "blocked"}, "column": {"known": "waiting"},
             "labels": {"known": ["ready-for-agent"]}, "yours": {"known": false},
             "blockers": {"known": [902]}, "dependents": {"known": []}, "pr": {"known": null}}
        ],
        "critical_chain": {"known": {"root": 902, "blocked_count": 1, "path": [902, 942]}}
    })
}

fn records() -> Vec<Value> {
    let common = json!({"schema": "openwiz.decisions.v1", "id": "decision-syn-1",
        "status": "open", "risk": "ordinary", "fingerprint": "a".repeat(64)});
    [
        json!({"kind": "grill_round", "grill_file": "docs/grills/synthetic.md", "round": 1,
            "questions": [{"id": "G1", "decides": "Synthetic first choice",
                "context": "Synthetic context", "recommendation": "Use the synthetic option."}], "answered": []}),
        json!({"kind": "grill_confirmation", "grill_file": "docs/grills/synthetic.md",
            "summary": ["Synthetic summary decision."]}),
        json!({"kind": "spec_confirmation", "spec": 901, "summary": ["Synthetic spec summary."],
            "headline": "A synthetic capability.", "tickets": [], "graph": []}),
        json!({"kind": "plan_approval", "spec": 901, "summary": ["Synthetic plan summary."],
            "headline": "A synthetic capability.",
            "tickets": [{"number": 902, "title": "Synthetic first ticket", "blockers": []},
                {"number": 903, "title": "Synthetic second ticket", "blockers": [902]}],
            "graph": [{"blocker": 902, "ticket": 903}]})
    ].into_iter().enumerate().map(|(i, details)| {
        let mut record = common.clone();
        record.as_object_mut().unwrap().extend(details.as_object().unwrap().clone());
        record["id"] = json!(format!("decision-syn-{}", i + 1));
        record
    }).collect()
}

fn decisions() -> Value {
    json!({
        "schema": "openwiz.decisions.v1", "kind": "response", "snapshot_at": 1700000100000_u64,
        "coverage": {"state": "complete", "gaps": []},
        "freshness": {"state": "fresh", "snapshot_at": {"known": 1700000090000_u64}},
        "orchestrator": {
            "coverage": {"state": "complete", "gaps": []},
            "freshness": {"state": "fresh", "snapshot_at": {"known": 1700000090000_u64}},
            "target": {"known": "thr_syn_0001"}
        },
        "items": records().into_iter().enumerate().map(|(i, request)| json!({
            "comment_id": 100 + i, "subject": {"repository":"synthetic-owner/synthetic-repo", "kind": if i < 2 {"pull_request"} else {"issue"}, "number": 901},
            "created_at": 1700000000000_u64, "updated_at": 1700000090000_u64,
            "current": {"known": true}, "request": request
        })).collect::<Vec<_>>()
    })
}

fn verdict(schema: &Value, value: &Value, good: bool, label: &str) {
    let errors = validate(schema, value);
    assert_eq!(errors.is_empty(), good, "{label}: {errors:#?}");
}

#[test]
fn plan_valid_partial_stale_and_empty_fixtures() {
    let schema = schema("plan");
    let good = plan();
    let building = building_plan();
    let mut partial = good.clone();
    partial["coverage"] = json!({"state": "partial", "gaps": [{"kind": "timed_out", "detail": "Synthetic unavailable prerequisites"}]});
    partial["tickets"][1]["blockers"] = json!({"unknown": "Synthetic incomplete read"});
    partial["tickets"][0]["dependents"] = json!({"unknown": "Synthetic incomplete read"});
    partial["critical_chain"] = json!({"unknown": "Synthetic incomplete graph"});
    let mut stale = good.clone();
    stale["freshness"] = json!({"state": "stale", "snapshot_at": {"known": 1700000000000_u64}});
    let mut empty = good.clone();
    empty["lanes"] = json!([]);
    empty["tickets"] = json!([]);
    empty["critical_chain"] = json!({"known": null});
    for (label, fixture) in [
        ("valid", good),
        ("building", building),
        ("partial", partial),
        ("stale", stale),
        ("empty", empty),
    ] {
        verdict(&schema, &fixture, true, label);
    }
}

fn building_plan() -> Value {
    let mut building = plan();
    building["tickets"][0]["state"] = json!({"known": "building"});
    building["tickets"][0]["column"] = json!({"known": "building"});
    building["tickets"][0]["pr"] = json!({"known": {"number": 950, "url": "https://github.com/synthetic-owner/synthetic-project/pull/950"}});
    building
}

#[test]
fn decisions_all_variants_lifecycle_risks_and_empty_responses() {
    let schema = schema("decisions");
    assert_eq!(records().len(), 4);
    for record in records() {
        for status in ["open", "resolved", "superseded"] {
            for risk in ["ordinary", "live", "release", "publish", "unknown"] {
                let mut fixture = record.clone();
                fixture["status"] = json!(status);
                fixture["risk"] = json!(risk);
                if fixture["kind"] == "grill_round" && status == "resolved" {
                    fixture["answered"] = json!(["G1"]);
                }
                verdict(&schema, &fixture, true, &format!("{status}/{risk}"));
            }
        }
    }
    let good = decisions();
    let mut stale = good.clone();
    stale["freshness"] = json!({"state": "stale", "snapshot_at": {"known": 1700000000000_u64}});
    stale["items"][0]["current"] = json!({"known": false});
    let mut partial = good.clone();
    partial["coverage"] = json!({"state": "partial", "gaps": [{"kind": "malformed", "detail": "Synthetic malformed record omitted"}]});
    partial["items"][0]["current"] = json!({"unknown": "Synthetic fingerprint not checked"});
    let mut empty = good.clone();
    empty["items"] = json!([]);
    empty["orchestrator"]["target"] = json!({"known": null});
    for (label, fixture) in [
        ("valid", good),
        ("stale", stale),
        ("partial", partial),
        ("empty", empty),
    ] {
        verdict(&schema, &fixture, true, label);
    }
}

#[test]
fn plan_and_decisions_malformed_literals_fail() {
    for (name, good, mutations) in [
        (
            "plan",
            plan(),
            vec![
                ("/schema", json!("openwiz.plan.v2")),
                ("/snapshot_at", json!(-1)),
                ("/snapshot_at", json!(1.5)),
                ("/lanes/0/kind", json!("milestone")),
                ("/lanes/0/number", json!(0)),
                ("/tickets/0/title", json!("Synthetic title")),
                ("/tickets/0/title", json!({"known": ""})),
                ("/tickets/0/state", json!({"known": "done"})),
                ("/tickets/0/state", json!({"known": {"ready": null}})),
                ("/tickets/0/column", json!({"known": "yours"})),
                ("/tickets/0/yours", json!(true)),
                ("/tickets/0/labels", json!({"known": ["held", "held"]})),
                ("/tickets/1/blockers", json!({"known": [902, 902]})),
                (
                    "/critical_chain",
                    json!({"known": {"root": 902, "blocked_count": -1, "path": []}}),
                ),
                (
                    "/freshness",
                    json!({"state": "fresh", "snapshot_at": {"unknown": "Synthetic absent time"}}),
                ),
                ("/coverage", json!({"state": "partial", "gaps": []})),
                (
                    "/coverage/gaps",
                    json!([{"kind": "timed_out", "detail": "Synthetic gap"}]),
                ),
            ],
        ),
        (
            "decisions",
            decisions(),
            vec![
                ("/kind", json!("open")),
                ("/items/0/comment_id", json!(0)),
                ("/items/0/request/kind", json!({"grill_round": null})),
                ("/items/0/request/status", json!("resolved")),
                ("/items/0/request/risk", json!(false)),
                ("/items/0/request/fingerprint", json!("a".repeat(63))),
                ("/items/0/request/fingerprint", json!("a".repeat(65))),
                ("/items/0/request/fingerprint", json!("g".repeat(64))),
                ("/items/0/request/grill_file", json!("../synthetic.md")),
                ("/items/0/request/round", json!(0)),
                ("/items/0/request/questions", json!([])),
                ("/items/0/request/questions/0/context", json!("")),
                ("/items/0/request/answered", json!(["G1", "G1"])),
                ("/items/1/request/summary", json!([])),
                (
                    "/items/1/request/summary",
                    json!(["Synthetic line\nAnother line"]),
                ),
                (
                    "/items/2/request/tickets",
                    json!([{"number": 902, "title": "Synthetic ticket", "blockers": []}]),
                ),
                ("/items/3/request/spec", json!("901")),
                ("/orchestrator/target", json!({"known": "-bad"})),
                ("/orchestrator/target", json!({"known": "thr_\u{00e9}"})),
            ],
        ),
    ] {
        let schema = schema(name);
        for (pointer, replacement) in mutations {
            let mut bad = good.clone();
            *bad.pointer_mut(pointer).expect(pointer) = replacement;
            verdict(&schema, &bad, false, pointer);
        }
    }

    let schema = schema("plan");
    for (good, pointer, urls) in [
        (
            plan(),
            "/tickets/0/url/known",
            [
                "http://github.com/synthetic-owner/synthetic-project/issues/902",
                "https://example.test/synthetic-owner/synthetic-project/issues/902",
                "https://user@github.com/synthetic-owner/synthetic-project/issues/902",
                "https://github.com/synthetic-owner/synthetic-project/issues/902?q",
                "https://github.com/synthetic-owner/synthetic-project/issues/902#frag",
                "https://github.com/synthetic-owner/synthetic-project/../issues/902",
                "https://github.com/synthetic-owner/synthetic-project/pull/902",
                "https://github.com/synthetic-owner/synthetic-project/issues/0",
                "https://github.com/synthetic-owner/synthetic-project/issues/0902",
                "https://github.com/synthetic-owner/synthetic-project/issues/902/extra",
            ],
        ),
        (
            building_plan(),
            "/tickets/0/pr/known/url",
            [
                "http://github.com/synthetic-owner/synthetic-project/pull/950",
                "https://example.test/synthetic-owner/synthetic-project/pull/950",
                "https://user@github.com/synthetic-owner/synthetic-project/pull/950",
                "https://github.com/synthetic-owner/synthetic-project/pull/950?q",
                "https://github.com/synthetic-owner/synthetic-project/pull/950#frag",
                "https://github.com/synthetic-owner/synthetic-project/../pull/950",
                "https://github.com/synthetic-owner/synthetic-project/issues/950",
                "https://github.com/synthetic-owner/synthetic-project/pull/0",
                "https://github.com/synthetic-owner/synthetic-project/pull/0950",
                "https://github.com/synthetic-owner/synthetic-project/pull/950/extra",
            ],
        ),
    ] {
        verdict(&schema, &good, true, pointer);
        for url in urls {
            let mut bad = good.clone();
            *bad.pointer_mut(pointer).expect(pointer) = json!(url);
            let errors = validate(&schema, &bad);
            assert_eq!(errors.len(), 1, "{pointer}: {url}: {errors:#?}");
            assert!(
                errors[0].contains("does not match"),
                "{pointer}: {url}: {errors:#?}"
            );
        }
    }
}

#[test]
fn decisions_three_questions_and_ten_summary_lines_are_schema_bounds() {
    let schema = schema("decisions");
    let mut record = records().remove(0);
    let first = record["questions"][0].clone();
    record["questions"] = json!([first.clone(), {"id": "G2", "decides": "Synthetic second choice", "context": "Synthetic context", "recommendation": "Use it."}, {"id": "G3", "decides": "Synthetic third choice", "context": "Synthetic context", "recommendation": "Use it."}]);
    verdict(&schema, &record, true, "three questions");
    record["questions"].as_array_mut().unwrap().push(first);
    verdict(&schema, &record, false, "four questions");
    for mut summary in records().into_iter().skip(1) {
        let kind = summary["kind"].as_str().unwrap().to_owned();
        summary["summary"] = json!(vec!["Synthetic summary line."; 10]);
        verdict(&schema, &summary, true, &format!("ten lines for {kind}"));
        summary["summary"] = json!(vec!["Synthetic summary line."; 11]);
        verdict(
            &schema,
            &summary,
            false,
            &format!("eleven lines for {kind}"),
        );
    }
}

#[test]
fn plan_approval_fingerprint_names_the_existing_revision_script() {
    let text = std::fs::read_to_string(format!("{ROOT}/decisions.v1.md")).unwrap();
    let rule = text
        .split_once("## Fingerprints and current wording\n\n")
        .expect("fingerprint section")
        .1
        .split("\n\n")
        .next()
        .unwrap();
    let command = rule.split('`').nth(3).expect("revision command");
    assert_eq!(command, "skills/plan-graph/revision.sh <spec>");
    let script = command.strip_suffix(" <spec>").unwrap();
    assert!(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join(script)
            .is_file()
    );
}

#[test]
fn escaped_decision_markers_validate_and_have_a_discovery_rule() {
    let schema = schema("decisions");
    let record = serde_json::to_string(&records()[0]).unwrap();
    for escaped in [
        record.replace("openwiz.decisions.v1", r"openwiz\u002edecisions.v1"),
        record.replace("schema", r"sch\u0065ma"),
    ] {
        let parsed: Value = serde_json::from_str(&escaped).unwrap();
        assert_eq!(parsed["schema"], "openwiz.decisions.v1");
        verdict(&schema, &parsed, true, "escaped schema marker");
    }
    let text = std::fs::read_to_string(format!("{ROOT}/decisions.v1.md")).unwrap();
    let rules: Vec<_> = text
        .lines()
        .filter_map(|line| line.strip_prefix("**Candidate discovery:** "))
        .collect();
    assert_eq!(rules.len(), 1, "one operative candidate discovery rule");
    assert!(rules[0].contains("decoded JSON string tokens"));
}

fn object_paths(value: &Value, path: &str, out: &mut Vec<String>) {
    match value {
        Value::Object(object) => {
            out.push(path.to_owned());
            for (key, child) in object {
                object_paths(child, &format!("{path}/{key}"), out);
            }
        }
        Value::Array(items) => {
            for (i, child) in items.iter().enumerate() {
                object_paths(child, &format!("{path}/{i}"), out);
            }
        }
        _ => {}
    }
}

#[test]
fn every_fixture_object_refuses_missing_extra_and_positional_keys() {
    for (name, fixtures) in [
        ("plan", vec![plan()]),
        ("decisions", {
            let mut fixtures = records();
            fixtures.push(decisions());
            fixtures
        }),
    ] {
        let schema = schema(name);
        for fixture in fixtures {
            verdict(&schema, &fixture, true, "unmodified fixture");
            let mut paths = vec![];
            object_paths(&fixture, "", &mut paths);
            for path in paths {
                let mut extra = fixture.clone();
                extra
                    .pointer_mut(&path)
                    .unwrap()
                    .as_object_mut()
                    .unwrap()
                    .insert("synthetic_extra".into(), json!(true));
                verdict(&schema, &extra, false, &format!("extra at {path}"));
                let mut positional = fixture.clone();
                *positional.pointer_mut(&path).unwrap() = json!([]);
                verdict(
                    &schema,
                    &positional,
                    false,
                    &format!("positional at {path}"),
                );
                for key in fixture.pointer(&path).unwrap().as_object().unwrap().keys() {
                    let mut missing = fixture.clone();
                    missing
                        .pointer_mut(&path)
                        .unwrap()
                        .as_object_mut()
                        .unwrap()
                        .remove(key);
                    verdict(&schema, &missing, false, &format!("missing {path}/{key}"));
                }
            }
        }
    }
}

#[test]
fn plan_and_decisions_have_only_their_two_new_route_rows() {
    let text = std::fs::read_to_string(format!("{ROOT}/web-api.v1.md")).unwrap();
    for (route, contract) in [("plan", "plan.v1.md"), ("decisions", "decisions.v1.md")] {
        let prefix = format!("| `GET /api/v1/{route}` | ");
        let rows: Vec<_> = text
            .lines()
            .filter(|line| line.starts_with(&prefix))
            .collect();
        assert_eq!(rows.len(), 1, "one {route} route row");
        assert!(rows[0].contains(contract), "route links its contract");
    }
}

// U4 / EP3: these are the record outputs in the skill instructions themselves,
// not a second set of fixtures that could pass while the skills drift.
fn skill_decision_examples(text: &str) -> Vec<Value> {
    let section = text
        .split_once("\n## Decision records\n")
        .expect("the skill must give an operative decision-record step")
        .1
        .split("\n## ")
        .next()
        .unwrap();
    let mut lines = section.lines();
    let mut records = vec![];
    while let Some(line) = lines.next() {
        if line == "```json" {
            let mut block = String::new();
            loop {
                let line = lines.next().expect("a JSON fence must close");
                if line == "```" {
                    break;
                }
                block.push_str(line);
                block.push('\n');
            }
            records.push(serde_json::from_str(&block).expect("skill record must be JSON"));
        }
    }
    records
}

fn skill_text(name: &str) -> String {
    std::fs::read_to_string(format!("{ROOT}/../skills/{name}/SKILL.md")).unwrap()
}

#[test]
fn plan_approval_summary_names_its_saved_source() {
    let text = skill_text("plan-graph");
    let step = text
        .split_once("\n## Decision records\n")
        .unwrap()
        .1
        .split("\n## ")
        .next()
        .unwrap()
        .lines()
        .find(|line| line.starts_with("2. **Plan approval.** "))
        .expect("the operative plan approval step");
    assert!(
        step.contains("from its latest `spec_confirmation` record"),
        "plan approval must name the independently saved summary source"
    );
    assert!(step.contains("exact displayed 1–10 summary lines"));
    assert!(step.contains("spec's changelog headline word for word (`none` for infra)"));
    assert!(step.contains("do not truncate"));
    assert!(step.contains("A missing, unread or conflicting source stops the request"));
}

#[test]
fn plan_approval_command_runs_the_revision_v2_fixture_proof() {
    use std::os::unix::fs::PermissionsExt;

    let text = skill_text("plan-graph");
    let step = text
        .split_once("\n## Decision records\n")
        .unwrap()
        .1
        .split("\n## ")
        .next()
        .unwrap()
        .lines()
        .find(|line| line.starts_with("2. **Plan approval.** "))
        .expect("operative plan approval step");
    let relative_script = step
        .split_once("`sh <this skill's folder>/")
        .unwrap()
        .1
        .split_once(" <spec> > revision.txt`")
        .unwrap()
        .0;
    let skill = std::path::Path::new(ROOT).join("../skills/plan-graph");
    // The Rust CI step has native tools; Python is installed only later for
    // the skills' separate tests. Keep this proof runnable at that seam.
    let work = std::path::Path::new(env!("CARGO_TARGET_TMPDIR"))
        .join(format!("decision-revision-{}", std::process::id()));
    let bin = work.join("bin");
    crate::dirs::private_dir_all(&bin).unwrap();
    let path = std::env::var_os("PATH").unwrap();
    let native_tool = |name: &str| {
        std::env::split_paths(&path)
            .map(|dir| dir.join(name))
            .find(|program| program.is_file())
    };
    let hash = ["sha256sum", "shasum"]
        .into_iter()
        .find(|name| native_tool(name).is_some())
        .expect("a native SHA-256 tool");
    for name in [
        "sh", "dirname", "mktemp", "rm", "head", "tail", "sort", "wc", "tr", "sed", "cut", "cat",
    ]
    .into_iter()
    .chain([hash])
    {
        let program = native_tool(name).expect(name).canonicalize().unwrap();
        std::os::unix::fs::symlink(program, bin.join(name)).unwrap();
    }
    // Synthetic responses at the script's public gh seam. This fake refuses
    // any other command, field or query and needs neither Python nor jq.
    let fake = bin.join("gh");
    std::fs::write(
        &fake,
        r##"#!/bin/sh
[ "$#" -eq 7 ] && [ "$1" = issue ] && [ "$2" = view ] &&
  [ "$4" = --json ] && [ "$6" = --jq ] || exit 2
printf '%s\n' "$3:$5" >> "$FAKE_GH_LOG" || exit 2
case "$3:$5" in
  901:subIssues)
    [ "$7" = '.subIssues.totalCount, (.subIssues.nodes[].number)' ] || exit 2
    printf '1\n902\n' ;;
  901:body)
    [ "$7" = '.body' ] || exit 2
    printf '%s\n' '- [x] Synthetic plan.' ;;
  902:body)
    [ "$7" = '.body' ] || exit 2
    printf '%s\n' '- [X] Synthetic ticket.' ;;
  902:number,title,blockedBy)
    [ "$7" = '"#\(.number)\t\([.blockedBy.nodes[].number] | sort | map("#" + tostring) | join(" ") | if . == "" then "none" else . end)\t\(.title)"' ] || exit 2
    printf '#902\t#900\tSynthetic reader\n' ;;
  *) exit 2 ;;
esac
"##,
    )
    .unwrap();
    std::fs::set_permissions(&fake, std::fs::Permissions::from_mode(0o700)).unwrap();
    let log = work.join("gh.log");
    let output = std::process::Command::new(bin.join("sh"))
        .arg(skill.join(relative_script))
        .arg("901")
        .env("FAKE_GH_LOG", &log)
        .env("PATH", &bin)
        .output()
        .expect("run the documented script on fake GitHub reads");
    let calls = std::fs::read_to_string(&log);
    std::fs::remove_dir_all(&work).unwrap();
    assert!(
        output.status.success(),
        "documented revision command failed: {}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    // Independently calculated hashes of the literal unticked bodies above,
    // each including its final newline; not the script's normalization logic.
    assert_eq!(
        output.stdout,
        concat!(
            "plan-graph revision v2\n",
            "spec #901 body sha256 fb4216fac3ccc9e033ead93271e38fc3baa1b6c34e04464a903e0c96505b8685\n",
            "ticket #902 blocked-by #900 body sha256 3fd90c155a1468ed38b2e481518a3ffbdd3e7b072760ef7e92b6d824b3d9d259 title Synthetic reader\n"
        ).as_bytes()
    );
    assert_eq!(
        openwiz_core::messaging::sha256_hex(&output.stdout),
        "924f3fe485c7228ce0ceb00b9adb2d8052d8ec2a14f5af9226063868f3f1ebfc"
    );
    assert_eq!(
        calls.expect("read the entire fake gh log after the command exits"),
        "901:subIssues\n901:body\n902:number,title,blockedBy\n902:body\n"
    );
}

fn skill_plan_revision(text: &str) -> &str {
    text.split_once("### Synthetic plan revision\n\n```text\n")
        .expect("the plan example must show its revision-v2 input")
        .1
        .split_once("```\n")
        .unwrap()
        .0
}

fn assert_plan_revision_matches_record(record: &Value, revision: &str) {
    assert!(revision.starts_with("plan-graph revision v2\n"));
    assert!(revision.ends_with('\n'));
    let issue_number = |text: &str| {
        text.strip_prefix('#')
            .expect("revision issue number starts with #")
            .parse::<u64>()
            .expect("revision issue number is an integer")
    };
    let tickets: Vec<_> = revision
        .lines()
        .skip(2)
        .map(|line| {
            let (number, rest) = line
                .strip_prefix("ticket ")
                .expect("each revision row is a ticket")
                .split_once(" blocked-by ")
                .expect("ticket row names its blockers");
            let (blockers, rest) = rest
                .split_once(" body sha256 ")
                .expect("ticket row names its body hash");
            let (_, title) = rest
                .split_once(" title ")
                .expect("ticket row names its title");
            let blockers: Vec<_> = if blockers == "none" {
                vec![]
            } else {
                blockers.split(' ').map(issue_number).collect()
            };
            json!({"number": issue_number(number), "title": title, "blockers": blockers})
        })
        .collect();
    assert_eq!(
        record["tickets"],
        json!(tickets),
        "table must match revision rows"
    );
    let mut edges = BTreeSet::new();
    for ticket in record["tickets"].as_array().unwrap() {
        for blocker in ticket["blockers"].as_array().unwrap() {
            edges.insert((
                blocker.as_u64().unwrap(),
                ticket["number"].as_u64().unwrap(),
            ));
        }
    }
    let graph: Vec<_> = edges
        .into_iter()
        .map(|(blocker, ticket)| json!({"blocker": blocker, "ticket": ticket}))
        .collect();
    assert_eq!(
        record["graph"],
        json!(graph),
        "graph must come from the table"
    );
    assert_eq!(
        record["fingerprint"],
        openwiz_core::messaging::sha256_hex(revision.as_bytes())
    );
}

#[test]
fn skill_plan_record_rejects_rehashed_revision_drift() {
    let text = skill_text("plan-graph");
    let record = skill_decision_examples(&text).pop().unwrap();
    let revision = skill_plan_revision(&text);
    let mut changed_revisions: Vec<_> = [
        ("title Synthetic reader", "title Different reader"),
        ("ticket #902", "ticket #904"),
        ("blocked-by #900", "blocked-by #899"),
        ("blocked-by #900", "blocked-by none"),
        ("blocked-by #900", "blocked-by #899 #900"),
    ]
    .into_iter()
    .map(|(from, to)| revision.replacen(from, to, 1))
    .collect();
    let last_ticket = revision.lines().last().unwrap();
    changed_revisions.push(revision.replace(&format!("{last_ticket}\n"), ""));
    changed_revisions.push(format!("{revision}{last_ticket}\n"));
    for changed in changed_revisions {
        assert_ne!(changed, revision, "mutation must change the revision");
        let mut record = record.clone();
        record["fingerprint"] = json!(openwiz_core::messaging::sha256_hex(changed.as_bytes()));
        assert!(
            std::panic::catch_unwind(|| assert_plan_revision_matches_record(&record, &changed))
                .is_err(),
            "accepted revision drift after rehashing: {changed}"
        );
    }
}

#[test]
fn skill_plan_record_accepts_matching_rows_and_derives_sorted_graph() {
    let revision = concat!(
        "plan-graph revision v2\n",
        "spec #901 body sha256 ",
        "1111111111111111111111111111111111111111111111111111111111111111\n",
        "ticket #902 blocked-by #900 #901 body sha256 ",
        "2222222222222222222222222222222222222222222222222222222222222222 title Synthetic λ title reader\n",
        "ticket #903 blocked-by none body sha256 ",
        "3333333333333333333333333333333333333333333333333333333333333333 title Synthetic root\n",
        "ticket #904 blocked-by #900 body sha256 ",
        "4444444444444444444444444444444444444444444444444444444444444444 title Synthetic cards\n"
    );
    let mut record = json!({
        "tickets": [
            {"number": 902, "title": "Synthetic λ title reader", "blockers": [900, 901]},
            {"number": 903, "title": "Synthetic root", "blockers": []},
            {"number": 904, "title": "Synthetic cards", "blockers": [900]}
        ],
        "graph": [
            {"blocker": 900, "ticket": 902}, {"blocker": 900, "ticket": 904},
            {"blocker": 901, "ticket": 902}
        ],
        "fingerprint": openwiz_core::messaging::sha256_hex(revision.as_bytes())
    });
    assert_plan_revision_matches_record(&record, revision);
    record["graph"].as_array_mut().unwrap().reverse();
    assert!(
        std::panic::catch_unwind(|| assert_plan_revision_matches_record(&record, revision))
            .is_err()
    );
    record["graph"] = json!([]);
    assert!(
        std::panic::catch_unwind(|| assert_plan_revision_matches_record(&record, revision))
            .is_err()
    );
}

#[test]
fn skills_decision_record_outputs_validate_and_bind_the_proposal() {
    let schema = schema("decisions");
    for (name, kinds) in [
        ("grill", ["grill_round", "grill_confirmation"]),
        ("plan-graph", ["spec_confirmation", "plan_approval"]),
    ] {
        let text = skill_text(name);
        let records = skill_decision_examples(&text);
        assert_eq!(records.len(), 2, "exactly two request examples in {name}");
        for (record, kind) in records.iter().zip(kinds) {
            assert_eq!(record["kind"], kind);
            assert_eq!(record["status"], "open");
            verdict(&schema, record, true, &format!("{name}/{kind}"));
            let bytes = if kind == "plan_approval" {
                let revision = skill_plan_revision(&text);
                assert_plan_revision_matches_record(record, revision);
                revision.as_bytes().to_vec()
            } else {
                let mut proposal = record.as_object().unwrap().clone();
                for key in ["fingerprint", "status", "answered"] {
                    proposal.remove(key);
                }
                // serde_json's default sorted object map and compact UTF-8
                // encoding implement this contract's canonical JSON form.
                serde_json::to_vec(&proposal).unwrap()
            };
            assert_eq!(
                record["fingerprint"],
                openwiz_core::messaging::sha256_hex(&bytes),
                "{name}/{kind}"
            );
            let mut malformed = record.clone();
            malformed.as_object_mut().unwrap().remove("risk");
            verdict(
                &schema,
                &malformed,
                false,
                "skill output missing explicit risk",
            );
        }
    }
}
