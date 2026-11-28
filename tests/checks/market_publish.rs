use std::fs;
use std::path::Path;

use serde_json::{Map, Value, json};

use crate::schema::{lint, validate};

const CONTRACTS: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../contracts");
const FIXTURES: &str = "fixtures/market-publish";

fn load(path: &Path) -> Value {
    let text = fs::read_to_string(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

fn fixtures(name: &str) -> Map<String, Value> {
    let path = Path::new(CONTRACTS).join(FIXTURES).join(name);
    let Value::Object(cases) = load(&path) else {
        panic!("{name} must be an object keyed by rule");
    };
    assert!(!cases.is_empty(), "{name} must contain fixtures");
    cases
}

#[test]
fn market_publish_schema_checks_every_fixture_pair() {
    let valid = fixtures("valid.json");
    let broken = fixtures("broken.json");
    assert_eq!(
        valid.keys().collect::<Vec<_>>(),
        broken.keys().collect::<Vec<_>>(),
        "every rule needs both a valid and a broken fixture"
    );

    let mut schema = load(&Path::new(CONTRACTS).join("market-publish.v1.schema.json"));
    let errors = lint(&schema);
    assert!(errors.is_empty(), "schema lint: {errors:?}");

    // The root validates the public result line. Select the fixture entry point
    // with the same definitions to check behavior that needs invocation context.
    for (rule, example) in &valid {
        for result in example["stdout"]
            .as_array()
            .into_iter()
            .flatten()
            .chain(example.get("recorded"))
        {
            let errors = validate(&schema, result);
            assert!(errors.is_empty(), "{rule} public result: {errors:?}");
        }
        assert!(
            !validate(&schema, example).is_empty(),
            "{rule}: fixture metadata passed as a public result"
        );
    }

    schema["$ref"] = json!("#/$defs/fixture");
    let errors = lint(&schema);
    assert!(errors.is_empty(), "fixture schema lint: {errors:?}");
    for (rule, example) in &valid {
        let errors = validate(&schema, example);
        assert!(errors.is_empty(), "{rule} valid fixture: {errors:?}");
        assert!(
            !validate(&schema, &broken[rule]).is_empty(),
            "{rule}: accepted broken fixture"
        );
    }
}
