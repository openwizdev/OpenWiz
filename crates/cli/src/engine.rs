//! Thin installed-engine CLI. The packaged tool owns the durable setup store.
use std::{ffi::OsString, io::Write, process::Command};

pub const USAGE: &str = "  openwiz engine preview [--location cloud|local] [--state-dir DIR] [--json]\n  openwiz engine activate --yes --operation ID [--root DIR] [--state-dir DIR] [--json]\n  openwiz engine status [--state-dir DIR] [--json]\n";
pub const HELP: &str = "Engine preview, activation and status\nPreview saves one durable setup proposal; status only reads it. Engine location\nis separate from fleet-agent location. A Local engine activates on this PC through\nthe verified installation named by --root: activate installs the previewed service\nconfig once, then records one PC activation, which holds with no service start\nuntil native observation and owner authority exist.\nCloud engine activation is an unresolved gap pending its separate decision.\nLogin is reported as unknown.\nAn uncertain activation must be reconciled; another preview never retries it.\nCloud Credits use protected recorded evidence, with a labelled 30-day projection.\nUnknown cost establishes no affordable Cloud default. Provider charges are separate.\n";

pub fn run(args: &[OsString], out: &mut dyn Write, err: &mut dyn Write) -> i32 {
    let name = match args.first().and_then(|a| a.to_str()) {
        Some("preview") => "engine.preview",
        Some("activate") => "engine.activate",
        Some("status") => "engine.status",
        _ => "unknown",
    };
    let mut json = false;
    let mut value = false;
    for arg in args {
        if value {
            value = false;
            continue;
        }
        match arg.to_str() {
            Some("--state-dir" | "--operation" | "--location" | "--root") => value = true,
            Some("--json") => json = true,
            _ => {}
        }
    }
    if !args.is_empty()
        && args
            .iter()
            .all(|a| matches!(a.to_str(), Some("--help" | "-h" | "--json")))
        && args
            .iter()
            .any(|a| matches!(a.to_str(), Some("--help" | "-h")))
    {
        let help = crate::response::help(json, format!("{USAGE}\n{HELP}"));
        return if out
            .write_all(help.as_bytes())
            .and_then(|_| out.flush())
            .is_ok()
        {
            0
        } else {
            1
        };
    }
    if !args
        .first()
        .is_some_and(|a| matches!(a.to_str(), Some("preview" | "activate" | "status")))
        || args.iter().any(|a| a.to_str().is_none())
    {
        return failure(
            json,
            name,
            2,
            "usage",
            "Expected engine preview, activate or status; see openwiz engine --help.",
            out,
            err,
        );
    }
    let result = engine_process(args);
    let Some(result) = result else {
        return failure(
            json,
            name,
            1,
            "unavailable",
            "The verified packaged engine runtime is unavailable; reinstall the matching package.",
            out,
            err,
        );
    };
    let code = result.status.code().unwrap_or(1);
    let Some(report) = outcome(&result.stdout, name, code) else {
        return failure(
            json,
            name,
            1,
            "unavailable",
            "The engine outcome is unrecognized; inspect the same operation before retrying.",
            out,
            err,
        );
    };
    if json {
        if out
            .write_all(&result.stdout)
            .and_then(|_| out.flush())
            .is_err()
        {
            return 1;
        }
    } else {
        if report["schema"] == "openwiz.cli-error.v1" {
            let _ = writeln!(
                err,
                "openwiz: {}",
                report["error"]["message"]
                    .as_str()
                    .unwrap_or("Engine state is unavailable.")
            );
            return code;
        }
        let reason = report["reason"]
            .as_str()
            .or_else(|| report["error"]["message"].as_str())
            .unwrap_or("Engine state is unavailable.");
        if writeln!(
            out,
            "{reason}\nLocation: {}\nStatus: {}\nPC activation: {}\nLogin: {}",
            report["engine"]["location"]
                .as_str()
                .unwrap_or("unselected"),
            report["location_status"].as_str().unwrap_or("unknown"),
            report["pc_activation"]["state"]
                .as_str()
                .unwrap_or("unknown"),
            report["login"].as_str().unwrap_or("unknown")
        )
        .is_err()
        {
            return 1;
        }
        if let Some(id) = report["operation"]["operation_id"].as_str()
            && writeln!(out, "Operation: {id}").is_err()
        {
            return 1;
        }
    }
    code
}

fn failure(
    json: bool,
    name: &str,
    code: i32,
    kind: &str,
    message: &str,
    out: &mut dyn Write,
    err: &mut dyn Write,
) -> i32 {
    if json {
        let report = serde_json::json!({"schema":"openwiz.cli-error.v1","command":name,"exit_code":code,"error":{"kind":kind,"message":message}});
        if writeln!(out, "{report}").is_err() {
            return 1;
        }
    } else {
        let _ = writeln!(err, "openwiz: {message}");
    }
    code
}

// Read the installed child's complete declared outcome. The same embedded CLI
// contract supplies required fields, enums and bounds; unfamiliar rules refuse.
fn outcome(bytes: &[u8], command: &str, code: i32) -> Option<serde_json::Value> {
    use serde::Deserialize;
    static SCHEMA: std::sync::OnceLock<serde_json::Value> = std::sync::OnceLock::new();
    let mut input = serde_json::Deserializer::from_slice(bytes);
    let Strict(report) = Strict::deserialize(&mut input).ok()?;
    input.end().ok()?;
    let definition = match report["schema"].as_str()? {
        "openwiz.engine.v1" => "engine_report",
        "openwiz.cli-error.v1" => {
            if report["command"] != command || report["exit_code"].as_i64()? != i64::from(code) {
                return None;
            }
            "error"
        }
        _ => return None,
    };
    let schema = SCHEMA.get_or_init(|| {
        serde_json::from_str(include_str!("../../../contracts/cli.v1.schema.json"))
            .expect("compiled CLI schema")
    });
    ([0, 1, 2, 5, 6, 8, 10].contains(&code)
        && conforms(schema, &schema["$defs"][definition], &report))
    .then_some(report)
}

struct Strict(serde_json::Value);
impl<'de> serde::Deserialize<'de> for Strict {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        use serde::de::{self, MapAccess, SeqAccess, Visitor};
        use serde_json::{Map, Number, Value};
        struct StrictVisitor;
        impl<'de> Visitor<'de> for StrictVisitor {
            type Value = Strict;
            fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str("strict JSON")
            }
            fn visit_bool<E: de::Error>(self, v: bool) -> Result<Strict, E> {
                Ok(Strict(Value::Bool(v)))
            }
            fn visit_i64<E: de::Error>(self, v: i64) -> Result<Strict, E> {
                Ok(Strict(Value::Number(v.into())))
            }
            fn visit_u64<E: de::Error>(self, v: u64) -> Result<Strict, E> {
                Ok(Strict(Value::Number(v.into())))
            }
            fn visit_f64<E: de::Error>(self, v: f64) -> Result<Strict, E> {
                Number::from_f64(v)
                    .map(|n| Strict(Value::Number(n)))
                    .ok_or_else(|| E::custom("nonfinite number"))
            }
            fn visit_str<E: de::Error>(self, v: &str) -> Result<Strict, E> {
                Ok(Strict(Value::String(v.to_owned())))
            }
            fn visit_unit<E: de::Error>(self) -> Result<Strict, E> {
                Ok(Strict(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Strict, A::Error> {
                let mut values = Vec::new();
                while let Some(Strict(value)) = seq.next_element()? {
                    values.push(value);
                }
                Ok(Strict(Value::Array(values)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Strict, A::Error> {
                let mut values = Map::new();
                while let Some(key) = map.next_key::<String>()? {
                    if values.contains_key(&key) {
                        return Err(de::Error::custom("duplicate field"));
                    }
                    let Strict(value) = map.next_value()?;
                    values.insert(key, value);
                }
                Ok(Strict(Value::Object(values)))
            }
        }
        deserializer.deserialize_any(StrictVisitor)
    }
}

fn conforms(root: &serde_json::Value, rule: &serde_json::Value, value: &serde_json::Value) -> bool {
    use serde_json::Value;
    let Some(rules) = rule.as_object() else {
        return false;
    };
    const KEYS: &[&str] = &[
        "$ref",
        "type",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "oneOf",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
        "description",
    ];
    if rules.keys().any(|k| !KEYS.contains(&k.as_str())) {
        return false;
    }
    if let Some(reference) = rules.get("$ref")
        && !reference
            .as_str()
            .and_then(|s| s.strip_prefix('#'))
            .and_then(|s| root.pointer(s))
            .is_some_and(|target| conforms(root, target, value))
    {
        return false;
    }
    let matches_type = |kind: &str| match kind {
        "object" => value.is_object(),
        "array" => value.is_array(),
        "string" => value.is_string(),
        "integer" => value.is_i64() || value.is_u64(),
        "number" => value.is_number(),
        "boolean" => value.is_boolean(),
        "null" => value.is_null(),
        _ => false,
    };
    if let Some(kinds) = rules.get("type") {
        let valid = match kinds {
            Value::String(k) => matches_type(k),
            Value::Array(a) => a.iter().any(|k| k.as_str().is_some_and(matches_type)),
            _ => false,
        };
        if !valid {
            return false;
        }
    }
    if rules.get("const").is_some_and(|c| c != value)
        || rules
            .get("enum")
            .is_some_and(|e| !e.as_array().is_some_and(|a| a.contains(value)))
    {
        return false;
    }
    if let Some(options) = rules.get("oneOf")
        && !options
            .as_array()
            .is_some_and(|a| a.iter().filter(|r| conforms(root, r, value)).count() == 1)
    {
        return false;
    }
    if let Some(n) = value.as_f64()
        && (rules
            .get("minimum")
            .is_some_and(|m| m.as_f64().is_none_or(|m| n < m))
            || rules
                .get("maximum")
                .is_some_and(|m| m.as_f64().is_none_or(|m| n > m))
            || rules
                .get("exclusiveMinimum")
                .is_some_and(|m| m.as_f64().is_none_or(|m| n <= m)))
    {
        return false;
    }
    if let Some(s) = value.as_str() {
        let len = s.chars().count() as u64;
        if rules
            .get("minLength")
            .is_some_and(|m| m.as_u64().is_none_or(|m| len < m))
            || rules
                .get("maxLength")
                .is_some_and(|m| m.as_u64().is_none_or(|m| len > m))
            || rules
                .get("pattern")
                .is_some_and(|p| !p.as_str().is_some_and(|p| pattern(p, s)))
        {
            return false;
        }
    }
    if let Some(required) = rules.get("required")
        && !value.as_object().is_some_and(|o| {
            required.as_array().is_some_and(|a| {
                a.iter()
                    .all(|k| k.as_str().is_some_and(|k| o.contains_key(k)))
            })
        })
    {
        return false;
    }
    if let Some(properties) = rules.get("properties") {
        let (Some(properties), Some(object)) = (properties.as_object(), value.as_object()) else {
            return false;
        };
        if rule["additionalProperties"] != false
            || object
                .iter()
                .any(|(k, v)| !properties.get(k).is_some_and(|r| conforms(root, r, v)))
        {
            return false;
        }
    }
    if let Some(a) = value.as_array() {
        let len = a.len() as u64;
        if rules
            .get("minItems")
            .is_some_and(|m| m.as_u64().is_none_or(|m| len < m))
            || rules
                .get("maxItems")
                .is_some_and(|m| m.as_u64().is_none_or(|m| len > m))
            || rules
                .get("items")
                .is_some_and(|r| !a.iter().all(|v| conforms(root, r, v)))
        {
            return false;
        }
    }
    true
}

// Only pattern forms used by the engine's declared outcomes are recognized.
fn pattern(rule: &str, text: &str) -> bool {
    let hex = |s: &str, n| {
        s.len() == n
            && s.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    };
    let first = text.bytes().next();
    match rule {
        "^[0-9a-f]{32}$" => hex(text, 32),
        "^[0-9a-f]{64}$" => hex(text, 64),
        "^[A-Za-z0-9][-A-Za-z0-9]*$" => {
            first.is_some_and(|b| b.is_ascii_alphanumeric())
                && text.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
        }
        "^[A-Za-z0-9_][-A-Za-z0-9_]*$" => {
            first.is_some_and(|b| b.is_ascii_alphanumeric() || b == b'_')
                && text
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
        }
        "^[-A-Za-z0-9_.]*$" => text
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-.".contains(&b)),
        "^0\\.[0-9]{1,10}\\.[0-9]{1,10} [0-9a-f]{40}$" => {
            text.split_once(' ').is_some_and(|(v, s)| {
                let parts: Vec<_> = v.split('.').collect();
                hex(s, 40)
                    && parts.len() == 3
                    && parts[0] == "0"
                    && parts[1..].iter().all(|p| {
                        (1..=10).contains(&p.len()) && p.bytes().all(|b| b.is_ascii_digit())
                    })
            })
        }
        _ => false,
    }
}

fn engine_process(args: &[OsString]) -> Option<std::process::Output> {
    let exe = std::env::current_exe().ok()?.canonicalize().ok()?;
    let tool = exe.parent()?.join("runtime/engine/engine.py");
    // Only this installed sibling, never PATH or a source checkout fallback.
    let meta = std::fs::symlink_metadata(&tool).ok()?;
    if !meta.is_file() || meta.file_type().is_symlink() {
        return None;
    }
    if tool
        .ancestors()
        .skip(1)
        .any(|p| !std::fs::symlink_metadata(p).is_ok_and(|m| !m.file_type().is_symlink()))
    {
        return None;
    }
    let mut command = Command::new("/usr/bin/python3");
    command.arg("-I").arg(tool).args(args).env_clear();
    for name in ["HOME", "XDG_STATE_HOME", "OPENWIZ_STATE_DIR"] {
        if let Some(value) = std::env::var_os(name) {
            command.env(name, value);
        }
    }
    command.stdin(std::process::Stdio::null()).output().ok()
}
