use std::{fs, path::Path};

use serde_json::{Map, Value, json};

use crate::schema::{lint, validate};

const CONTRACTS: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../contracts");

fn read_json(path: &Path) -> Value {
    let bytes = fs::read(path);
    assert!(
        bytes.is_ok(),
        "cannot read {}",
        path.file_name().unwrap().display()
    );
    serde_json::from_slice(&bytes.unwrap()).expect("expected JSON")
}

fn validate_with_key_map_expanded(schema: &Value, answer: &Value) -> Vec<String> {
    let mut schema = schema.clone();
    let keys = schema["$defs"]["key_map"].as_object_mut().unwrap();
    let row_rule = keys.remove("additionalProperties").unwrap();
    let properties: Map<String, Value> = answer
        .pointer("/settings/keys")
        .and_then(Value::as_object)
        .into_iter()
        .flatten()
        .map(|(name, _)| (name.clone(), row_rule.clone()))
        .collect();
    keys.insert("properties".into(), Value::Object(properties));
    keys.insert("additionalProperties".into(), json!(false));
    let unsupported = lint(&schema);
    assert!(unsupported.is_empty(), "{unsupported:?}");
    validate(&schema, answer)
}

#[test]
fn settings_cli_schema_checks_every_fixture() {
    let contracts = Path::new(CONTRACTS);
    let schema = read_json(&contracts.join("settings-cli.v1.schema.json"));
    let fixtures = contracts.join("fixtures/settings-cli");

    for (directory, valid, expected) in [
        (
            "valid",
            true,
            &[
                "changed",
                "history",
                "missing",
                "refused",
                "restored",
                "show",
                "show_path",
            ][..],
        ),
        (
            "invalid",
            false,
            &[
                "changed-without-version",
                "history-too-long",
                "key-with-value",
                "multiline-refusal",
                "unknown-field",
            ][..],
        ),
    ] {
        let mut seen = Vec::new();
        for entry in fs::read_dir(fixtures.join(directory)).unwrap() {
            let path = entry.unwrap().path();
            if path.extension().is_none_or(|extension| extension != "json") {
                continue;
            }
            let name = path.file_stem().unwrap().to_str().unwrap();
            let answer = read_json(&path);
            let errors = validate_with_key_map_expanded(&schema, &answer);
            assert_eq!(errors.is_empty(), valid, "{directory}/{name}: {errors:?}");
            if valid {
                assert_eq!(answer["kind"], name, "{name}: fixture kind");
            }
            seen.push(name.to_owned());
        }
        seen.sort();
        assert_eq!(seen, expected, "{directory}: fixture coverage");
    }
}
