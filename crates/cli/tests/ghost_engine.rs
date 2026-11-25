#[allow(
    dead_code,
    reason = "shared with other test targets; this one uses only part of it"
)]
#[path = "../../../tests/support/schema.rs"]
mod schema;

use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;

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
fn pair_subcommand_prints_one_time_code_and_schema_loads() {
    let _schema = load_ghost_schema();
    let args: Vec<OsString> = ["pair", "--json"].iter().map(OsString::from).collect();
    let mut out = Vec::new();
    let mut err = Vec::new();
    let code = openwiz_cli::ghost::run(&args, &mut out, &mut err);
    assert_eq!(
        code,
        0,
        "ghost pair --json must exit 0, got {code}, stderr={}",
        String::from_utf8_lossy(&err)
    );
    let parsed: Value = serde_json::from_slice(&out).expect("valid JSON output from ghost pair");
    assert!(
        parsed["code"].as_str().is_some_and(|c| !c.is_empty()),
        "ghost pair --json must print a non-empty one-time code: {parsed}"
    );
    let _ = validate_def;
}
