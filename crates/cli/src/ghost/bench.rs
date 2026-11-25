//! Stub used by the red proof. The bench is not implemented yet.

use std::ffi::OsString;
use std::io::Write;
use std::path::Path;

use serde_json::{Value, json};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FixtureModel {
    Baseline,
    Slow,
    Weak,
}

impl FixtureModel {
    pub fn parse(value: Option<&str>) -> Result<Self, ()> {
        match value {
            None | Some("baseline") => Ok(Self::Baseline),
            Some("slow") => Ok(Self::Slow),
            Some("weak") => Ok(Self::Weak),
            Some(_) => Err(()),
        }
    }
}

pub fn fixture_suffix(
    _context_pack: &Path,
    _prefix: &str,
    _model: FixtureModel,
) -> Result<Option<String>, String> {
    Ok(None)
}

pub fn replay_file(
    _replay_path: &Path,
    _model: FixtureModel,
    _log_state: Option<&Path>,
) -> Result<Value, String> {
    Ok(json!({}))
}

pub fn report_log(_path: &Path) -> Result<Value, String> {
    Ok(json!({}))
}

pub fn run_with(
    _args: &[OsString],
    _out: &mut dyn Write,
    _err: &mut dyn Write,
    _env: &dyn Fn(&str) -> Option<OsString>,
) -> i32 {
    5
}
