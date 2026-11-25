//! Stub used by the red proof. The opt-in log is not implemented yet.

use std::ffi::OsString;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde_json::Value;

pub fn events_path(state: &Path) -> PathBuf {
    state.join("ghost").join("events.jsonl")
}

pub fn logging_enabled(_state: &Path) -> bool {
    true
}

pub fn set_logging(_state: &Path, _on: bool) -> Result<(), String> {
    Ok(())
}

pub fn append_event(_state: &Path, _event: &Value) -> Result<bool, String> {
    Ok(false)
}

pub fn read_events(_state: &Path) -> Result<Vec<Value>, String> {
    Ok(Vec::new())
}

pub fn read_event_file(_path: &Path) -> Result<Vec<Value>, String> {
    Ok(Vec::new())
}

pub fn forget(_state: &Path) -> Result<bool, String> {
    Ok(false)
}

pub fn json_has_duplicate_keys(_text: &str) -> bool {
    false
}

pub fn validate_event(_value: &Value) -> Result<(), String> {
    Ok(())
}

pub fn run_with(
    _args: &[OsString],
    _out: &mut dyn Write,
    _err: &mut dyn Write,
    _env: &dyn Fn(&str) -> Option<OsString>,
) -> i32 {
    5
}
