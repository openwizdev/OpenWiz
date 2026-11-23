use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_core::envelope::Envelope;
use openwiz_core::model::{Inventory, SessionId, SessionView};
use openwiz_core::ops::{self, ListRequest, OpError, ShowRequest};
use openwiz_core::source::SessionSource;
use serde_json::Value;

#[path = "../../crates/core/tests/support/scripted.rs"]
mod scripted;
pub use scripted::*;

pub const DEFAULT_IDS: [&str; 6] = [
    "thr_syn_0001",
    "thr_syn_0002",
    "thr_syn_0003",
    "thr_syn_0004",
    "thr_syn_0005",
    "thr_syn_0006",
];
pub const HIDDEN_ID: &str = "thr_syn_0007";
pub const ARCHIVED_ID: &str = "thr_syn_0008";
pub const MISSING_ID: &str = "thr_syn_9999";

const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/fixtures/room-cli-0.43.1");

pub struct Fake {
    pub dir: PathBuf,
}

impl Fake {
    pub fn new(test: &str, scenario: &str) -> Self {
        let dir = Path::new(env!("CARGO_TARGET_TMPDIR"))
            .join("fake-room-cli")
            .join(test);
        let _ = fs::remove_dir_all(&dir);
        crate::dirs::private_dir_all(&dir).expect("create fake dir");
        std::os::unix::fs::symlink(env!("CARGO_BIN_EXE_fake-room-cli"), dir.join("room-cli"))
            .expect("link fake room-cli");
        let scenario_file = Path::new(FIXTURES).join(scenario).join("scenario.json");
        assert!(scenario_file.is_file(), "no scenario {scenario}");
        fs::write(
            dir.join("fake-room-cli.scenario"),
            scenario_file.to_str().expect("utf-8 path"),
        )
        .expect("write scenario pointer");
        Self { dir }
    }

    pub fn set_scenario(&self, scenario: &str) {
        let scenario_file = Path::new(FIXTURES).join(scenario).join("scenario.json");
        assert!(scenario_file.is_file(), "no scenario {scenario}");
        fs::write(
            self.dir.join("fake-room-cli.scenario"),
            scenario_file.to_str().expect("utf-8 path"),
        )
        .expect("write scenario pointer");
    }

    pub fn program(&self) -> PathBuf {
        self.dir.join("room-cli")
    }

    pub fn source(&self) -> CloudRoomSource {
        CloudRoomSource::new(self.program())
    }

    pub fn invocations(&self) -> Vec<Vec<String>> {
        let Ok(text) = fs::read_to_string(self.dir.join("invocations.log")) else {
            return vec![];
        };
        text.lines()
            .map(|l| serde_json::from_str(l).expect("log line is JSON"))
            .collect()
    }

    pub fn hung_pid(&self) -> Option<String> {
        fs::read_to_string(self.dir.join("hang.pid")).ok()
    }

    pub fn list(&self, request: &ListRequest) -> Result<Envelope<Inventory>, OpError> {
        ops::list(&self.source(), &clock(), request)
    }

    pub fn show(&self, id: &str) -> Result<Envelope<SessionView>, OpError> {
        ops::show(
            &self.source(),
            &clock(),
            &ShowRequest {
                id: SessionId(id.to_owned()),
                budget: openwiz_core::limits::RUN_BUDGET,
            },
        )
    }

    pub fn cli(&self, args: &[&str]) -> (i32, String, String) {
        cli_with(&self.source(), args)
    }

    pub fn cli_json(&self, args: &[&str]) -> Value {
        let (code, out, err) = self.cli(args);
        assert_eq!(code, 0, "openwiz {args:?} failed: {err}");
        serde_json::from_str(&out).unwrap_or_else(|e| panic!("stdout is not JSON ({e}): {out}"))
    }
}

pub fn cli_with(source: &dyn SessionSource, args: &[&str]) -> (i32, String, String) {
    let args: Vec<String> = args.iter().map(|a| (*a).to_owned()).collect();
    let (mut out, mut err) = (Vec::new(), Vec::new());
    let code = openwiz_cli::run(&args, source, &clock(), &mut out, &mut err);
    (
        code,
        String::from_utf8(out).expect("stdout is UTF-8"),
        String::from_utf8(err).expect("stderr is UTF-8"),
    )
}

pub fn cli_json_with(source: &dyn SessionSource, args: &[&str]) -> Value {
    let (code, out, err) = cli_with(source, args);
    assert_eq!(code, 0, "openwiz {args:?} failed: {err}");
    serde_json::from_str(&out).unwrap_or_else(|e| panic!("stdout is not JSON ({e}): {out}"))
}

pub fn row_lines<'a>(text: &'a str, id: &str) -> Vec<&'a str> {
    text.lines()
        .filter(|l| !l.trim_start().starts_with(GAP_PREFIX))
        .filter(|l| {
            l.find("thr_syn_").is_some_and(|i| {
                l[i..].starts_with(id)
                    && !l[i + id.len()..].starts_with(|c: char| c.is_ascii_digit())
            })
        })
        .collect()
}

pub const GAP_PREFIX: &str = "gap: ";
pub const COUNTS_PREFIX: &str = "counts: ";
pub const GROUP_ROOT: &str = "/factories/";
pub const UNGROUPED_HEADER: &str = "/factories/_ungrouped/";
pub const CUT_MARKER: char = '…';

pub fn utc_text(ms: i64) -> String {
    let secs = ms.div_euclid(1000);
    let (days, rem) = (secs.div_euclid(86_400), secs.rem_euclid(86_400));
    let z = days + 719_468;
    let (era, doe) = (z.div_euclid(146_097), z.rem_euclid(146_097));
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        rem / 3_600,
        rem % 3_600 / 60,
        rem % 60
    )
}

pub fn age_text(ms: i64) -> String {
    assert!(ms >= 0, "the text contract defines non-negative ages only");
    let s = ms / 1_000;
    for (unit, size) in [("d", 86_400), ("h", 3_600), ("m", 60)] {
        if s >= size {
            return format!("{}{unit}", s / size);
        }
    }
    format!("{s}s")
}

pub fn fact_text(fact: &Value) -> String {
    if let Some(reason) = fact["unknown"].as_str() {
        return format!("unknown ({reason})");
    }
    match &fact["known"] {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

pub fn age_token(row: &Value) -> String {
    match row["age_ms"]["known"].as_i64() {
        Some(ms) => format!("age {}", age_text(ms)),
        None => format!("age {}", fact_text(&row["age_ms"])),
    }
}

pub fn location_token(row: &Value) -> String {
    let location = &row["location"];
    if location.get("unknown").is_some() {
        return format!("location {}", fact_text(location));
    }
    let known = &location["known"];
    match known["kind"].as_str() {
        Some("cloud") => "location cloud".to_owned(),
        Some("local") => format!("location local on {}", fact_text(&known["machine"])),
        other => panic!("unexpected location kind {other:?}: {location}"),
    }
}

pub fn parent_token(row: &Value) -> String {
    match &row["parent"]["known"] {
        Value::Null if row["parent"].get("known").is_some() => "parent none".to_owned(),
        Value::String(id) => format!("parent {id}"),
        _ => format!("parent {}", fact_text(&row["parent"])),
    }
}

pub fn configuration_text(row: &Value) -> String {
    let config = &row["reported_configuration"];
    format!(
        "reported configuration: model {}, effort {}",
        fact_text(&config["model"]),
        fact_text(&config["effort"])
    )
}

pub fn shared_project_names() -> BTreeSet<String> {
    let path = Path::new(FIXTURES).join("normal/project-list.json");
    let projects: Value =
        serde_json::from_str(&fs::read_to_string(path).expect("project list")).expect("JSON");
    let names: Vec<&str> = projects
        .as_array()
        .expect("project array")
        .iter()
        .filter_map(|p| p["name"].as_str())
        .collect();
    names
        .iter()
        .filter(|n| names.iter().filter(|m| m == n).count() > 1)
        .map(|n| (*n).to_owned())
        .collect()
}

pub fn last_six(id: &str) -> String {
    let chars: Vec<char> = id.chars().collect();
    chars[chars.len().saturating_sub(6)..].iter().collect()
}

pub fn group_header(row: &Value, shared: &BTreeSet<String>) -> String {
    let group = &row["group"];
    match group["kind"].as_str() {
        Some("ungrouped") => UNGROUPED_HEADER.to_owned(),
        Some("project") => {
            let name = fact_text(&group["name"]);
            let id = group["id"].as_str().expect("project id");
            if shared.contains(&name) {
                format!("{GROUP_ROOT}{name}~{}/", last_six(id))
            } else {
                format!("{GROUP_ROOT}{name}/")
            }
        }
        other => panic!("unexpected group kind {other:?}: {group}"),
    }
}

pub fn row_id(line: &str) -> Option<String> {
    if line.trim_start().starts_with(GAP_PREFIX) {
        return None;
    }
    let i = line.find("thr_syn_")?;
    let digits: String = line[i + 8..]
        .chars()
        .take_while(char::is_ascii_digit)
        .collect();
    (!digits.is_empty()).then(|| format!("thr_syn_{digits}"))
}

pub fn rows_by_group(text: &str) -> Vec<(String, Option<String>)> {
    let mut header = None;
    let mut out = Vec::new();
    for line in text.lines() {
        let t = line.trim();
        if t.starts_with(GROUP_ROOT) && t.ends_with('/') {
            header = Some(t.to_owned());
        } else if let Some(id) = row_id(line) {
            out.push((id, header.clone()));
        }
    }
    out
}

pub fn text_counts(text: &str) -> Vec<(String, String)> {
    let lines: Vec<&str> = text
        .lines()
        .filter_map(|l| l.trim().strip_prefix(COUNTS_PREFIX))
        .collect();
    assert_eq!(lines.len(), 1, "one counts line:\n{text}");
    lines[0]
        .split(", ")
        .map(|pair| {
            let (k, v) = pair
                .split_once(' ')
                .unwrap_or_else(|| panic!("counts pair {pair:?}"));
            (k.to_owned(), v.to_owned())
        })
        .collect()
}

pub fn gap_lines(text: &str) -> Vec<&str> {
    text.lines()
        .filter(|l| l.trim_start().starts_with(GAP_PREFIX))
        .collect()
}

pub fn capped(original: &str) -> String {
    if original.chars().count() <= openwiz_core::limits::FIELD_MAX_CHARS {
        return original.to_owned();
    }
    let mut kept: String = original
        .chars()
        .take(openwiz_core::limits::FIELD_MAX_CHARS - 1)
        .collect();
    kept.push(CUT_MARKER);
    kept
}
