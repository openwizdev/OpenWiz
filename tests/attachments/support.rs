use std::fs;

use serde_json::{Value, json};

pub const ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

pub const ATTACHMENT_SCHEMA: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../contracts/attachment.v1.schema.json"
);

pub fn attachment_schema() -> Value {
    serde_json::from_str(&fs::read_to_string(ATTACHMENT_SCHEMA).expect("schema")).expect("JSON")
}

pub fn validate_def(def: &str, value: &Value) -> Vec<String> {
    let mut schema = attachment_schema();
    schema["$ref"] = json!(format!("#/$defs/{def}"));
    crate::pattern::validate(&schema, value)
}
