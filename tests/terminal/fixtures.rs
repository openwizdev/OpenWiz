//! The synthetic responses are the existing routes' real shapes: each
//! validates against its contract schema (with the checkers the inventory,
//! fleet and decisions tests already use), so the screens are tested on
//! bodies the server can send.

use std::fs;
use std::path::Path;

use serde_json::Value;

use super::support::{FIXTURE_DIRS, ROOT, fixture};
use super::{fleet_schema, pattern, schema};

fn contract(name: &str) -> Value {
    serde_json::from_str(&fs::read_to_string(Path::new(ROOT).join("contracts").join(name)).unwrap())
        .unwrap()
}

/// Drops `maxItems`, which the pattern checker does not know, as the web
/// API's decisions tests do; everything else is enforced.
fn strip(value: &mut Value) {
    match value {
        Value::Object(map) => {
            map.remove("maxItems");
            map.values_mut().for_each(strip);
        }
        Value::Array(items) => items.iter_mut().for_each(strip),
        _ => {}
    }
}

#[test]
fn every_fixture_matches_its_contract() {
    let inventory = contract("inventory.v1.schema.json");
    let fleet = contract("fleet.v1.schema.json");
    let mut decisions = contract("decisions.v1.schema.json");
    strip(&mut decisions);
    decisions["$ref"] = Value::from("#/$defs/response");
    assert_eq!(schema::lint(&inventory), Vec::<String>::new());
    assert_eq!(fleet_schema::lint(&fleet), Vec::<String>::new());
    assert_eq!(pattern::lint(&decisions), Vec::<String>::new());
    let mut checked = 0;
    for dir in FIXTURE_DIRS {
        for entry in fs::read_dir(Path::new(ROOT).join(dir)).unwrap() {
            let name = entry.unwrap().file_name().into_string().unwrap();
            assert!(name.ends_with(".json"), "{dir}/{name}");
            let body: Value = serde_json::from_slice(&fixture(&name)).unwrap();
            let errors = match body["schema"].as_str().unwrap() {
                "openwiz.inventory.v1" => schema::validate(&inventory, &body),
                "openwiz.fleet.v1" => fleet_schema::validate(&fleet, &body),
                "openwiz.decisions.v1" => pattern::validate(&decisions, &body),
                other => panic!("{name}: {other}"),
            };
            assert_eq!(errors, Vec::<String>::new(), "{name}");
            checked += 1;
        }
    }
    assert_eq!(checked, 10);
}

/// Every word a contract fixes: its `const` and `enum` strings.
fn words(schema: &Value, out: &mut Vec<String>) {
    match schema {
        Value::Object(map) => {
            for (key, child) in map {
                match (key.as_str(), child) {
                    ("const", Value::String(s)) => out.push(s.clone()),
                    ("enum", Value::Array(items)) => {
                        out.extend(items.iter().filter_map(Value::as_str).map(str::to_owned))
                    }
                    _ => words(child, out),
                }
            }
        }
        Value::Array(items) => items.iter().for_each(|i| words(i, out)),
        _ => {}
    }
}

fn synthetic(s: &str, contract_words: &[String]) -> bool {
    let id = |prefix: &str| {
        s.strip_prefix(prefix)
            .is_some_and(|n| n.len() == 4 && n.bytes().all(|b| b.is_ascii_digit()))
    };
    let read_id = s.len() >= 2 && s.starts_with('r') && s[1..].bytes().all(|b| b.is_ascii_digit());
    let room_version = s
        .strip_prefix('v')
        .is_some_and(|n| !n.is_empty() && n.bytes().all(|b| b.is_ascii_digit()));
    let version = room_version
        || s.split('.').count() == 3
            && s.split('.')
                .all(|p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit()));
    let fingerprint = s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit());
    contract_words.iter().any(|w| w == s)
        || s.starts_with("Synthetic")
        || s.starts_with("Needs you: Synthetic")
        || s.starts_with("https://example.invalid/synthetic/")
        || s.starts_with("synthetic")
        || id("thr_syn_")
        || id("prj_syn_")
        || read_id
        || version
        || fingerprint
}

fn scan(value: &Value, contract_words: &[String], at: &str, bad: &mut Vec<String>) {
    match value {
        Value::Object(map) => {
            for (key, child) in map {
                // OpenWiz's own reason words, as the fixture scan allows.
                if !matches!(key.as_str(), "reason" | "detail" | "unknown") {
                    scan(child, contract_words, &format!("{at}.{key}"), bad);
                }
            }
        }
        Value::Array(items) => {
            for (i, item) in items.iter().enumerate() {
                scan(item, contract_words, &format!("{at}[{i}]"), bad);
            }
        }
        Value::String(s) if !synthetic(s, contract_words) => bad.push(format!("{at}: {s:?}")),
        _ => {}
    }
}

/// The repository's fixture scan covers `tests/fixtures/`; the fleet and
/// decisions bodies kept here get the same rule: only contract words,
/// synthetic ids, read ids, versions and "Synthetic" text.
#[test]
fn the_fleet_and_decisions_bodies_hold_only_synthetic_values() {
    let mut contract_words = Vec::new();
    for name in ["fleet.v1.schema.json", "decisions.v1.schema.json"] {
        words(&contract(name), &mut contract_words);
    }
    let mut bad = Vec::new();
    for entry in fs::read_dir(Path::new(ROOT).join("tests/terminal/bodies")).unwrap() {
        let name = entry.unwrap().file_name().into_string().unwrap();
        let body: Value = serde_json::from_slice(&fixture(&name)).unwrap();
        scan(&body, &contract_words, &name, &mut bad);
    }
    assert_eq!(bad, Vec::<String>::new());
}

/// The action report bodies in `tests/terminal/actions/` are the fixture
/// CLI's own `--json` reports (byte for byte what the routes return), made
/// from the synthetic room-cli fixtures; each matches its contract
/// definition under the repository's pattern-aware checker.
#[test]
fn every_action_report_fixture_matches_its_contract() {
    let mut messaging = contract("messaging.v1.schema.json");
    let mut new_thread = contract("new-thread.v1.schema.json");
    strip(&mut messaging);
    strip(&mut new_thread);
    let mut checked = 0;
    for entry in fs::read_dir(Path::new(ROOT).join("tests/terminal/actions")).unwrap() {
        let path = entry.unwrap().path();
        let body: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        let (contract, def) = match body["schema"].as_str().unwrap() {
            "openwiz.messaging.v1" => (&messaging, "report"),
            "openwiz.send-preview.v1" => (&messaging, "preview"),
            "openwiz.send-lookup.v1" => (&messaging, "lookup"),
            "openwiz.cloud-options.v1" => (&new_thread, "options"),
            "openwiz.new-thread-preview.v1" => (&new_thread, "preview"),
            "openwiz.new-thread.v1" => (&new_thread, "report"),
            "openwiz.new-thread-status.v1" => (&new_thread, "status_read"),
            other => panic!("{path:?}: {other}"),
        };
        let mut schema = contract.clone();
        schema["$ref"] = Value::from(format!("#/$defs/{def}"));
        assert_eq!(
            pattern::validate(&schema, &body),
            Vec::<String>::new(),
            "{path:?}"
        );
        checked += 1;
    }
    assert_eq!(checked, 9);
}
