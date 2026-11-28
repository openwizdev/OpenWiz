use std::ffi::OsString;
use std::fs::{self, DirBuilder, OpenOptions};
use std::io::Write;
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};
use std::path::{Component, Path, PathBuf};

use serde_json::{Value, json};

pub const SCHEMA: &str = "openwiz.ghost.v1";
const SETTINGS_NAME: &str = "settings.json";
const EVENTS_NAME: &str = "events.jsonl";

pub fn state_dir(env: &dyn Fn(&str) -> Option<OsString>) -> Result<PathBuf, String> {
    if let Some(dir) = env("OPENWIZ_STATE_DIR").filter(|v| !v.is_empty()) {
        let dir = PathBuf::from(dir);
        if !absolute_dir(&dir) {
            return Err("the state directory must be an absolute path".to_owned());
        }
        return Ok(dir);
    }
    let home = env("HOME")
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .filter(|p| absolute_dir(p))
        .ok_or_else(|| "no state directory".to_owned())?;
    if cfg!(target_os = "macos") {
        return Ok(home.join("Library/Application Support/openwiz"));
    }
    let base = env("XDG_STATE_HOME")
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .filter(|p| absolute_dir(p))
        .unwrap_or_else(|| home.join(".local/state"));
    Ok(base.join("openwiz"))
}

fn absolute_dir(path: &Path) -> bool {
    path.is_absolute() && !path.components().any(|c| matches!(c, Component::ParentDir))
}

pub fn events_path(state: &Path) -> PathBuf {
    state.join("ghost").join(EVENTS_NAME)
}

fn settings_path(state: &Path) -> PathBuf {
    state.join("ghost").join(SETTINGS_NAME)
}

pub fn logging_enabled(state: &Path) -> bool {
    if !absolute_dir(state) {
        return false;
    }
    let Ok(text) = fs::read_to_string(settings_path(state)) else {
        return false;
    };
    parse_logging(&text) == Some(true)
}

fn parse_logging(text: &str) -> Option<bool> {
    let compact: String = text.chars().filter(|c| !c.is_whitespace()).collect();
    match compact.as_str() {
        r#"{"logging":true}"# => Some(true),
        r#"{"logging":false}"# => Some(false),
        _ => None,
    }
}

pub fn set_logging(state: &Path, on: bool) -> Result<(), String> {
    require_state(state)?;
    ensure_ghost_dir(state)?;
    let body = if on {
        "{\"logging\":true}\n"
    } else {
        "{\"logging\":false}\n"
    };
    write_new(settings_path(state), body.as_bytes())
}

pub fn append_event(state: &Path, event: &Value) -> Result<bool, String> {
    require_state(state)?;
    validate_event(event)?;
    if !logging_enabled(state) {
        return Ok(false);
    }
    ensure_ghost_dir(state)?;
    let path = events_path(state);
    if is_symlink(&path)? {
        return Err("the ghost log must be a regular file".to_owned());
    }
    let line =
        serde_json::to_string(event).map_err(|_| "the ghost event is not valid".to_owned())?;
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .mode(0o600)
        .open(&path)
        .map_err(|_| "the ghost log could not be written".to_owned())?;
    writeln!(file, "{line}").map_err(|_| "the ghost log could not be written".to_owned())?;
    file.flush()
        .map_err(|_| "the ghost log could not be written".to_owned())?;
    Ok(true)
}

pub fn read_events(state: &Path) -> Result<Vec<Value>, String> {
    require_state(state)?;
    read_event_file(&events_path(state))
}

pub fn read_event_file(path: &Path) -> Result<Vec<Value>, String> {
    if is_symlink(path)? {
        return Err("the ghost log must be a regular file".to_owned());
    }
    let text = match fs::read_to_string(path) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(_) => return Err("the ghost log could not be read".to_owned()),
    };
    let mut events = Vec::new();
    for line in text.split('\n') {
        if line.is_empty() {
            continue;
        }
        if json_has_duplicate_keys(line) {
            return Err("the ghost log is not valid".to_owned());
        }
        let value: Value =
            serde_json::from_str(line).map_err(|_| "the ghost log is not valid".to_owned())?;
        validate_event(&value)?;
        events.push(value);
    }
    Ok(events)
}

pub fn forget(state: &Path) -> Result<bool, String> {
    require_state(state)?;
    let path = events_path(state);
    let meta = match fs::symlink_metadata(&path) {
        Ok(meta) => meta,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(_) => return Err("the ghost log could not be deleted".to_owned()),
    };
    if meta.is_dir() {
        return Err("the ghost log must be a regular file".to_owned());
    }
    fs::remove_file(&path).map_err(|_| "the ghost log could not be deleted".to_owned())?;
    Ok(true)
}

pub fn run_with(
    args: &[OsString],
    out: &mut dyn Write,
    err: &mut dyn Write,
    env: &dyn Fn(&str) -> Option<OsString>,
) -> i32 {
    let json = args.iter().any(|arg| arg == "--json");
    if args
        .iter()
        .any(|arg| arg_str(arg) == Some("--help") || arg_str(arg) == Some("-h"))
    {
        let _ = writeln!(
            out,
            "openwiz ghost forget [--json]\nDelete the opt-in local ghost event log."
        );
        return 0;
    }
    if args.iter().any(|arg| arg != "--json") {
        return failure(
            json,
            2,
            "usage",
            "unknown argument; see openwiz ghost forget --help.",
            out,
            err,
        );
    }
    let state = match state_dir(env) {
        Ok(dir) => dir,
        Err(message) => return failure(json, 1, "unavailable", &message, out, err),
    };
    match forget(&state) {
        Ok(_) => {
            if json {
                let _ = writeln!(out, "{}", json!({"deleted": true}));
            }
            0
        }
        Err(message) => failure(json, 1, "unavailable", &message, out, err),
    }
}

fn require_state(state: &Path) -> Result<(), String> {
    if absolute_dir(state) {
        Ok(())
    } else {
        Err("the state directory must be an absolute path".to_owned())
    }
}

fn ensure_ghost_dir(state: &Path) -> Result<(), String> {
    let dir = state.join("ghost");
    if dir.is_dir() {
        return Ok(());
    }
    if dir.exists() {
        return Err("the ghost directory is not a directory".to_owned());
    }
    DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&dir)
        .map_err(|_| "the ghost directory could not be created".to_owned())
}

fn write_new(path: PathBuf, body: &[u8]) -> Result<(), String> {
    if is_symlink(&path)? {
        return Err("the ghost settings must be a regular file".to_owned());
    }
    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .mode(0o600)
        .open(&path)
        .map_err(|_| "the ghost settings could not be written".to_owned())?;
    file.write_all(body)
        .and_then(|()| file.flush())
        .map_err(|_| "the ghost settings could not be written".to_owned())
}

fn is_symlink(path: &Path) -> Result<bool, String> {
    match fs::symlink_metadata(path) {
        Ok(meta) => Ok(meta.file_type().is_symlink()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(_) => Err("the ghost path could not be read".to_owned()),
    }
}

pub fn validate_event(value: &Value) -> Result<(), String> {
    let obj = value
        .as_object()
        .filter(|obj| obj.len() == 11)
        .ok_or_else(|| "the ghost event is not valid".to_owned())?;
    let need = |key: &str| {
        obj.get(key)
            .ok_or_else(|| "the ghost event is not valid".to_owned())
    };
    if need("schema")? != SCHEMA || need("kind")? != "event" {
        return Err("the ghost event is not valid".to_owned());
    }
    let at = need("at")?
        .as_str()
        .ok_or_else(|| "the ghost event is not valid".to_owned())?;
    if !is_time(at) {
        return Err("the ghost event is not valid".to_owned());
    }
    for key in ["suggestion_id", "session_id"] {
        let text = need(key)?
            .as_str()
            .ok_or_else(|| "the ghost event is not valid".to_owned())?;
        if text.is_empty() {
            return Err("the ghost event is not valid".to_owned());
        }
    }
    if !matches!(
        need("surface")?.as_str(),
        Some("openwiz-app" | "t3-code" | "bb-plugin" | "cli" | "other")
    ) || !matches!(
        need("outcome")?.as_str(),
        Some(
            "shown"
                | "accepted_all"
                | "accepted_word"
                | "typed_through"
                | "dismissed"
                | "typed_over"
        )
    ) || !matches!(
        need("tier")?.as_str(),
        Some("recall" | "small_model" | "draft")
    ) {
        return Err("the ghost event is not valid".to_owned());
    }
    let confidence = need("confidence")?
        .as_f64()
        .ok_or_else(|| "the ghost event is not valid".to_owned())?;
    let latency = need("latency_ms")?
        .as_f64()
        .ok_or_else(|| "the ghost event is not valid".to_owned())?;
    let chars = need("chars_accepted")?
        .as_u64()
        .ok_or_else(|| "the ghost event is not valid".to_owned())?;
    if !(0.0..=1.0).contains(&confidence) || latency < 0.0 {
        return Err("the ghost event is not valid".to_owned());
    }
    let outcome = need("outcome")?.as_str().unwrap_or("");
    if matches!(outcome, "shown" | "dismissed" | "typed_over") && chars != 0 {
        return Err("the ghost event is not valid".to_owned());
    }
    let _ = chars;
    Ok(())
}

fn is_time(text: &str) -> bool {
    let b = text.as_bytes();
    b.len() == 20
        && b[4] == b'-'
        && b[7] == b'-'
        && b[10] == b'T'
        && b[13] == b':'
        && b[16] == b':'
        && b[19] == b'Z'
        && b.iter()
            .enumerate()
            .all(|(i, c)| matches!(i, 4 | 7 | 10 | 13 | 16 | 19) || c.is_ascii_digit())
}

pub fn json_has_duplicate_keys(text: &str) -> bool {
    fn walk(bytes: &[u8], i: &mut usize) -> Result<(), ()> {
        skip_ws(bytes, i);
        if *i >= bytes.len() {
            return Err(());
        }
        match bytes[*i] {
            b'{' => {
                *i += 1;
                let mut keys = Vec::new();
                loop {
                    skip_ws(bytes, i);
                    if *i < bytes.len() && bytes[*i] == b'}' {
                        *i += 1;
                        return Ok(());
                    }
                    let key = parse_string(bytes, i)?;
                    if keys.iter().any(|have: &String| have == &key) {
                        return Err(());
                    }
                    keys.push(key);
                    skip_ws(bytes, i);
                    if *i >= bytes.len() || bytes[*i] != b':' {
                        return Err(());
                    }
                    *i += 1;
                    walk(bytes, i)?;
                    skip_ws(bytes, i);
                    if *i < bytes.len() && bytes[*i] == b',' {
                        *i += 1;
                        continue;
                    }
                    if *i < bytes.len() && bytes[*i] == b'}' {
                        *i += 1;
                        return Ok(());
                    }
                    return Err(());
                }
            }
            b'[' => {
                *i += 1;
                loop {
                    skip_ws(bytes, i);
                    if *i < bytes.len() && bytes[*i] == b']' {
                        *i += 1;
                        return Ok(());
                    }
                    walk(bytes, i)?;
                    skip_ws(bytes, i);
                    if *i < bytes.len() && bytes[*i] == b',' {
                        *i += 1;
                        continue;
                    }
                    if *i < bytes.len() && bytes[*i] == b']' {
                        *i += 1;
                        return Ok(());
                    }
                    return Err(());
                }
            }
            b'"' => {
                parse_string(bytes, i)?;
                Ok(())
            }
            b't' => literal(bytes, i, b"true"),
            b'f' => literal(bytes, i, b"false"),
            b'n' => literal(bytes, i, b"null"),
            b'-' | b'0'..=b'9' => parse_number(bytes, i),
            _ => Err(()),
        }
    }
    let bytes = text.as_bytes();
    let mut i = 0;
    if walk(bytes, &mut i).is_err() {
        return true;
    }
    skip_ws(bytes, &mut i);
    i != bytes.len()
}

fn skip_ws(bytes: &[u8], i: &mut usize) {
    while *i < bytes.len() && bytes[*i].is_ascii_whitespace() {
        *i += 1;
    }
}

fn literal(bytes: &[u8], i: &mut usize, word: &[u8]) -> Result<(), ()> {
    if bytes.get(*i..*i + word.len()) == Some(word) {
        *i += word.len();
        Ok(())
    } else {
        Err(())
    }
}

fn parse_number(bytes: &[u8], i: &mut usize) -> Result<(), ()> {
    if bytes.get(*i) == Some(&b'-') {
        *i += 1;
    }
    let start = *i;
    if bytes.get(*i) == Some(&b'0') {
        *i += 1;
    } else if matches!(bytes.get(*i), Some(b'1'..=b'9')) {
        while matches!(bytes.get(*i), Some(b'0'..=b'9')) {
            *i += 1;
        }
    } else {
        return Err(());
    }
    if start == *i {
        return Err(());
    }
    if bytes.get(*i) == Some(&b'.') {
        *i += 1;
        let frac = *i;
        while matches!(bytes.get(*i), Some(b'0'..=b'9')) {
            *i += 1;
        }
        if frac == *i {
            return Err(());
        }
    }
    if matches!(bytes.get(*i), Some(b'e' | b'E')) {
        *i += 1;
        if matches!(bytes.get(*i), Some(b'+' | b'-')) {
            *i += 1;
        }
        let exp = *i;
        while matches!(bytes.get(*i), Some(b'0'..=b'9')) {
            *i += 1;
        }
        if exp == *i {
            return Err(());
        }
    }
    Ok(())
}

fn parse_string(bytes: &[u8], i: &mut usize) -> Result<String, ()> {
    if bytes.get(*i) != Some(&b'"') {
        return Err(());
    }
    *i += 1;
    let mut out = String::new();
    while *i < bytes.len() {
        let c = bytes[*i];
        *i += 1;
        match c {
            b'"' => return Ok(out),
            b'\\' => {
                let esc = *bytes.get(*i).ok_or(())?;
                *i += 1;
                match esc {
                    b'"' | b'\\' | b'/' => out.push(esc as char),
                    b'b' => out.push('\u{0008}'),
                    b'f' => out.push('\u{000c}'),
                    b'n' => out.push('\n'),
                    b'r' => out.push('\r'),
                    b't' => out.push('\t'),
                    b'u' => {
                        let hex = bytes.get(*i..*i + 4).ok_or(())?;
                        *i += 4;
                        let text = std::str::from_utf8(hex).map_err(|_| ())?;
                        let code = u32::from_str_radix(text, 16).map_err(|_| ())?;
                        out.push(char::from_u32(code).ok_or(())?);
                    }
                    _ => return Err(()),
                }
            }
            0x20..=0x7f => out.push(c as char),
            _ => {
                let rest = bytes.get(*i - 1..).ok_or(())?;
                let ch = std::str::from_utf8(rest)
                    .map_err(|_| ())?
                    .chars()
                    .next()
                    .ok_or(())?;
                if ch.is_control() {
                    return Err(());
                }
                *i += ch.len_utf8() - 1;
                out.push(ch);
            }
        }
    }
    Err(())
}

fn arg_str(arg: &OsString) -> Option<&str> {
    arg.to_str()
}

fn failure(
    json: bool,
    code: i32,
    kind: &str,
    message: &str,
    out: &mut dyn Write,
    err: &mut dyn Write,
) -> i32 {
    if json {
        let report = json!({
            "schema": "openwiz.cli-error.v1",
            "command": "ghost",
            "exit_code": code,
            "error": { "kind": kind, "message": message }
        });
        let _ = writeln!(out, "{report}");
    } else {
        let _ = writeln!(err, "openwiz: {message}");
    }
    code
}
