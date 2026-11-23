use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::thread;
use std::time::Duration;

use serde_json::{Map, Value};

const SCENARIO_FILE: &str = "fake-gh.scenario";
const LOG_FILE: &str = "gh-invocations.log";
const ENV_LOG_FILE: &str = "gh-environment.log";
const ENV_PREFIXES: &[&str] = &["GH_", "GITHUB_"];
const HANG_PID_FILE: &str = "gh-hang.pid";
const REFUSED: u8 = 97;
const NO_SCENARIO: u8 = 98;
const BAD_SCENARIO: u8 = 99;

const SCENARIO_KEYS: &[&str] = &[
    "scenario",
    "description",
    "synthetic_assumptions",
    "extends",
    "responses",
];
const RESPONSE_KEYS: &[&str] = &[
    "argv",
    "stdout",
    "stdout_file",
    "stderr",
    "exit",
    "delay_ms",
    "hang",
];

fn main() -> ExitCode {
    let mut args = std::env::args();
    let argv0 = PathBuf::from(args.next().unwrap_or_default());
    let argv: Vec<String> = args.collect();
    let dir = argv0.parent().unwrap_or(Path::new(".")).to_path_buf();

    append_line(&dir.join(LOG_FILE), &argv);
    append_line(&dir.join(ENV_LOG_FILE), &environment_names());

    let scenario = match fs::read_to_string(dir.join(SCENARIO_FILE)) {
        Ok(path) => PathBuf::from(path.trim()),
        Err(e) => {
            eprintln!("fake gh: no {SCENARIO_FILE} next to {argv0:?}: {e}");
            return ExitCode::from(NO_SCENARIO);
        }
    };
    match find_response(&scenario, &argv, 0) {
        Ok(Some(response)) => answer(&response, &dir),
        Ok(None) => {
            eprintln!(
                "fake gh: refused, no scenario response for: {}",
                argv.join(" ")
            );
            ExitCode::from(REFUSED)
        }
        Err(Problem::Missing(why)) => {
            eprintln!("fake gh: {why}");
            ExitCode::from(NO_SCENARIO)
        }
        Err(Problem::Malformed(why)) => {
            eprintln!("fake gh: bad scenario: {why}");
            ExitCode::from(BAD_SCENARIO)
        }
    }
}

fn append_line(path: &Path, value: &[String]) {
    let line = serde_json::to_string(value).expect("a list of strings serializes");
    if let Ok(mut f) = fs::OpenOptions::new().create(true).append(true).open(path) {
        let _ = f.write_all(format!("{line}\n").as_bytes());
    }
}

fn environment_names() -> Vec<String> {
    let mut names: Vec<String> = std::env::vars_os()
        .filter_map(|(name, _)| name.into_string().ok())
        .filter(|name| ENV_PREFIXES.iter().any(|p| name.starts_with(p)))
        .collect();
    names.sort();
    names
}

enum Problem {
    Missing(String),
    Malformed(String),
}

struct Response {
    stdout: Vec<u8>,
    stderr: Vec<u8>,
    exit: u8,
    delay_ms: u64,
    hang: bool,
}

const MAX_EXTENDS: usize = 8;

fn find_response(path: &Path, argv: &[String], depth: usize) -> Result<Option<Response>, Problem> {
    if depth > MAX_EXTENDS {
        return Err(Problem::Malformed(format!(
            "{path:?}: extends more than {MAX_EXTENDS} scenarios deep"
        )));
    }
    let text = fs::read_to_string(path)
        .map_err(|e| Problem::Missing(format!("cannot read {path:?}: {e}")))?;
    let malformed = |why: String| Problem::Malformed(format!("{path:?}: {why}"));
    let value: Value =
        serde_json::from_str(&text).map_err(|e| malformed(format!("not JSON: {e}")))?;
    let scenario = object(&value, SCENARIO_KEYS).map_err(malformed)?;
    for key in ["scenario", "description", "extends"] {
        if scenario.get(key).is_some_and(|v| !v.is_string()) {
            return Err(malformed(format!("{key} is not a string")));
        }
    }
    strings(scenario.get("synthetic_assumptions"))
        .map_err(|why| malformed(format!("synthetic_assumptions {why}")))?;
    let base = path.parent().unwrap_or(Path::new(".")).to_path_buf();
    let Some(Value::Array(responses)) = scenario.get("responses") else {
        return Err(malformed("responses is not a list".to_owned()));
    };
    let mut found = None;
    for (i, response) in responses.iter().enumerate() {
        let checked = check_response(response, &base)
            .map_err(|why| malformed(format!("response {i}: {why}")))?;
        if found.is_none() && checked.0 == argv {
            found = Some(checked.1);
        }
    }
    if found.is_some() {
        return Ok(found);
    }
    match scenario.get("extends").and_then(Value::as_str) {
        Some(parent) => {
            let parent = base.join("..").join(parent).join("scenario.json");
            find_response(&parent, argv, depth + 1)
        }
        None => Ok(None),
    }
}

fn object<'a>(value: &'a Value, allowed: &[&str]) -> Result<&'a Map<String, Value>, String> {
    let Value::Object(map) = value else {
        return Err("not an object".to_owned());
    };
    match map.keys().find(|k| !allowed.contains(&k.as_str())) {
        Some(key) => Err(format!("unknown key {key:?}")),
        None => Ok(map),
    }
}

fn strings(value: Option<&Value>) -> Result<Vec<String>, String> {
    let Some(Value::Array(items)) = value else {
        return Err("is not a list".to_owned());
    };
    items
        .iter()
        .map(|item| {
            item.as_str()
                .map(str::to_owned)
                .ok_or("holds a non-string".to_owned())
        })
        .collect()
}

fn check_response(value: &Value, base: &Path) -> Result<(Vec<String>, Response), String> {
    let map = object(value, RESPONSE_KEYS)?;
    let argv = strings(map.get("argv")).map_err(|why| format!("argv {why}"))?;
    let text = |key: &str| match map.get(key) {
        None => Ok(None),
        Some(Value::String(s)) => Ok(Some(s.clone())),
        Some(_) => Err(format!("{key} is not a string")),
    };
    let stdout = match (text("stdout")?, text("stdout_file")?) {
        (Some(_), Some(_)) => return Err("has both stdout and stdout_file".to_owned()),
        (Some(inline), None) => inline.into_bytes(),
        (None, Some(file)) => fs::read(base.join(&file))
            .map_err(|e| format!("cannot read stdout_file {file:?}: {e}"))?,
        (None, None) => Vec::new(),
    };
    let stderr = text("stderr")?.unwrap_or_default().into_bytes();
    let number = |key: &str| match map.get(key) {
        None => Ok(0),
        Some(v) => v.as_u64().ok_or(format!("{key} is not a whole number")),
    };
    let exit = u8::try_from(number("exit")?).map_err(|_| "exit is over 255".to_owned())?;
    let delay_ms = number("delay_ms")?;
    let hang = match map.get("hang") {
        None => false,
        Some(Value::Bool(b)) => *b,
        Some(_) => return Err("hang is not true or false".to_owned()),
    };
    Ok((
        argv,
        Response {
            stdout,
            stderr,
            exit,
            delay_ms,
            hang,
        },
    ))
}

fn answer(response: &Response, dir: &Path) -> ExitCode {
    thread::sleep(Duration::from_millis(response.delay_ms));
    if response.hang {
        let _ = fs::write(dir.join(HANG_PID_FILE), std::process::id().to_string());
        loop {
            thread::sleep(Duration::from_secs(3600));
        }
    }
    std::io::stdout()
        .write_all(&response.stdout)
        .and_then(|()| std::io::stdout().flush())
        .expect("stdout");
    std::io::stderr()
        .write_all(&response.stderr)
        .expect("stderr");
    ExitCode::from(response.exit)
}
