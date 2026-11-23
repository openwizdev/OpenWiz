use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::thread;
use std::time::Duration;

use serde_json::Value;

const SCENARIO_FILE: &str = "fake-room-cli.scenario";
const LOG_FILE: &str = "invocations.log";
const ENV_LOG_FILE: &str = "environment.log";
const ENV_PREFIXES: &[&str] = &["ROOM_", "BB_", "CLOUDROOM_"];
const HANG_PID_FILE: &str = "hang.pid";
const REFUSED: u8 = 97;
const NO_FIXTURE: u8 = 98;
const NOT_FOUND_LINE: &str = "Error: HTTP 404: Thread not found";
const TELL_COUNT_FILE: &str = "tell-calls.count";
const STATE_DIR_ENV: &str = "OPENWIZ_STATE_DIR";
const STATE_FILE: &str = "fake-room-cli.state";
const SPAWN_COUNT_FILE: &str = "spawn-calls.count";
const THREADS_FILE: &str = "threads-created.count";
const REQUEST_IDS_FILE: &str = "request-ids.json";
const CONFLICT_LINE: &str =
    "Error: Failed to create thread: HTTP 409: Request ID was already used with different content";
const ATTACHMENTS_LOG: &str = "attachments.log";
const UPLOAD_FAILED: &str = "fake room-cli: an attachment could not be read for upload";
const ARCHIVE_COUNT_FILE: &str = "archive-calls.count";
const ARCHIVED_FILE: &str = "archived-threads.log";
const LOOP_WRITES_LOG: &str = "loop-writes.log";

fn main() -> ExitCode {
    let mut args = std::env::args();
    let argv0 = PathBuf::from(args.next().unwrap_or_default());
    let argv: Vec<String> = args.collect();
    let dir = argv0.parent().unwrap_or(Path::new(".")).to_path_buf();

    log_invocation(&dir, &argv);
    log_environment(&dir);

    if !allowlisted(&argv) {
        eprintln!(
            "fake room-cli: refused, not on the OpenWiz allowlist: {}",
            argv.join(" ")
        );
        return ExitCode::from(REFUSED);
    }

    let tell = is_tell(&argv);
    if tell {
        let n = count(&dir, TELL_COUNT_FILE);
        snapshot_records(&dir, "sends", &format!("records-at-tell-{n}.json"));
    }
    if is_spawn(&argv) {
        let n = count(&dir, SPAWN_COUNT_FILE);
        snapshot_records(&dir, "new-threads", &format!("records-at-spawn-{n}.json"));
    }
    if is_archive(&argv) {
        count(&dir, ARCHIVE_COUNT_FILE);
    }
    if let Some(write) = loop_write(&argv) {
        match record_loop_write(&dir, &argv, &write) {
            Ok(true) => {}
            Ok(false) => {
                eprintln!("fake room-cli: a loop file could not be read");
                return ExitCode::from(1);
            }
            Err(e) => {
                eprintln!(
                    "fake room-cli: the loop write could not be recorded in {LOOP_WRITES_LOG}: {e}"
                );
                return ExitCode::from(1);
            }
        }
    }

    let scenario_path = match fs::read_to_string(dir.join(SCENARIO_FILE)) {
        Ok(p) => PathBuf::from(p.trim()),
        Err(e) => {
            eprintln!("fake room-cli: no {SCENARIO_FILE} next to {argv0:?}: {e}");
            return ExitCode::from(NO_FIXTURE);
        }
    };

    let found = find_response(&scenario_path, &argv);
    let fails_after = found
        .as_ref()
        .and_then(|(response, _)| response["upload_fails_after"].as_u64());
    if (tell || is_spawn(&argv)) && !upload(&dir, &argv, fails_after) {
        eprintln!("{UPLOAD_FAILED}");
        return ExitCode::from(1);
    }

    if let Some((response, _)) = &found
        && is_archive(&argv)
        && response["archives"].as_bool() == Some(true)
    {
        archive(&dir, &argv[2]);
    }
    let found = found.map(|(response, base)| match response.get("after_archive") {
        Some(after) if is_show(&argv) && archived(&dir, &argv[2]) => (after.clone(), base),
        _ => (response, base),
    });

    match found {
        Some((response, _)) if is_spawn(&argv) && !request_id_table(&dir, &argv, &response) => {
            eprintln!("{CONFLICT_LINE}");
            ExitCode::from(1)
        }
        Some((response, base)) => answer(&response, &base, &dir),
        None if is_detail_read(&argv) => {
            eprintln!("{NOT_FOUND_LINE}");
            ExitCode::from(1)
        }
        None => {
            eprintln!("fake room-cli: no fixture for: {}", argv.join(" "));
            ExitCode::from(NO_FIXTURE)
        }
    }
}

fn log_invocation(dir: &Path, argv: &[String]) {
    let line = serde_json::to_string(argv).expect("argv serializes");
    if let Ok(mut f) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join(LOG_FILE))
    {
        let _ = f.write_all(format!("{line}\n").as_bytes());
    }
}

fn log_environment(dir: &Path) {
    let mut names: Vec<String> = std::env::vars_os()
        .filter_map(|(name, _)| name.into_string().ok())
        .filter(|name| ENV_PREFIXES.iter().any(|p| name.starts_with(p)))
        .collect();
    names.sort();
    let line = serde_json::to_string(&names).expect("names serialize");
    if let Ok(mut f) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join(ENV_LOG_FILE))
    {
        let _ = f.write_all(format!("{line}\n").as_bytes());
    }
}

fn allowlisted(argv: &[String]) -> bool {
    let a: Vec<&str> = argv.iter().map(String::as_str).collect();
    match a.as_slice() {
        ["--version"] => true,
        ["thread", "list", "--json", rest @ ..] => matches!(
            rest,
            [] | ["--include-hidden"]
                | ["--include-archived"]
                | ["--include-hidden", "--include-archived"]
        ),
        ["project", "list", "--json", "--include-personal", rest @ ..] => {
            matches!(rest, [] | ["--hidden"])
        }
        ["machine", "list", "--json"] => true,
        ["thread", "show" | "output", id, "--json"] => !id.starts_with('-'),
        [
            "thread",
            "tell",
            id,
            "--mode",
            mode @ ("queue" | "steer"),
            "--json",
            rest @ ..,
        ] => {
            let Some((pairs, ["--", _text])) = rest.split_last_chunk::<2>() else {
                return false;
            };
            !id.starts_with('-') && staged_pairs(pairs) && (pairs.is_empty() || *mode == "queue")
        }
        ["cloud", "status", "--json"] => true,
        ["cloud", "thread-workspace", id, "--json"] => !id.starts_with('-'),
        ["thread", "archive", id, "--json"] => is_thread_id(id),
        ["loop", "list", "--json"] => true,
        ["loop", "create" | "update", ..] => loop_write(argv).is_some(),
        [
            "thread",
            "spawn",
            "--project",
            project,
            "--machine",
            "cloud",
            "--provider",
            "codex" | "claude-code",
            "--model",
            model,
            "--reasoning-level",
            "low" | "medium" | "high" | "xhigh" | "max",
            "--request-id",
            request_id,
            "--json",
            rest @ ..,
        ] => {
            let Some((pairs, ["--prompt", _text])) = rest.split_last_chunk::<2>() else {
                return false;
            };
            !project.starts_with('-')
                && !model.starts_with('-')
                && is_request_id(request_id)
                && staged_pairs(pairs)
        }
        _ => false,
    }
}

fn staged_pairs(pairs: &[&str]) -> bool {
    pairs.len().is_multiple_of(2)
        && pairs
            .chunks(2)
            .all(|pair| matches!(pair[0], "--file" | "--image") && is_staged_path(pair[1]))
}

fn is_staged_path(path: &str) -> bool {
    let Some(rest) = path.strip_prefix('/') else {
        return false;
    };
    let parts: Vec<&str> = rest.split('/').collect();
    let plain = parts
        .iter()
        .all(|p| !p.is_empty() && *p != "." && *p != "..");
    let id_ok = |id: &str| {
        !id.is_empty()
            && id.len() <= 64
            && id.as_bytes()[0].is_ascii_alphanumeric()
            && id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
    };
    let name_ok = |name: &str| {
        !name.is_empty()
            && name.len() <= 179
            && !name.starts_with(['.', '-'])
            && name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
    };
    plain
        && !path.chars().any(char::is_control)
        && matches!(parts.as_slice(), [.., "attachments", id, name] if id_ok(id) && name_ok(name))
}

fn attachment_pairs(argv: &[String]) -> Vec<(String, String)> {
    let Some(json) = argv.iter().position(|w| w == "--json") else {
        return vec![];
    };
    let end = argv.len() - 2;
    argv[json + 1..end]
        .chunks(2)
        .map(|p| (p[0].clone(), p[1].clone()))
        .collect()
}

fn upload(dir: &Path, argv: &[String], fails_after: Option<u64>) -> bool {
    let pairs = attachment_pairs(argv);
    if pairs.is_empty() {
        return true;
    }
    let read = usize::try_from(fails_after.unwrap_or(u64::MAX)).unwrap_or(usize::MAX);
    let held: Vec<Option<Vec<u8>>> = pairs
        .iter()
        .enumerate()
        .map(|(i, (_, path))| if i < read { fs::read(path).ok() } else { None })
        .collect();
    let items: Vec<Value> = pairs
        .iter()
        .zip(&held)
        .map(|((flag, path), bytes)| {
            serde_json::json!({
                "flag": flag,
                "path": path,
                "sha256": bytes.as_deref().map(openwiz_core::messaging::sha256_hex),
                "size": bytes.as_ref().map(Vec::len),
            })
        })
        .collect();
    let line = serde_json::json!({
        "call": argv[1],
        "request_id": is_spawn(argv).then(|| argv[13].clone()),
        "items": items,
        "vm_hwm_kib": peak_memory_kib(),
    });
    if let Ok(mut f) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join(ATTACHMENTS_LOG))
    {
        let _ = f.write_all(format!("{line}\n").as_bytes());
    }
    let read_all = held.iter().all(Option::is_some);
    drop(held);
    read_all
}

fn peak_memory_kib() -> Option<u64> {
    let status = fs::read_to_string("/proc/self/status").ok()?;
    status
        .lines()
        .find_map(|l| l.strip_prefix("VmHWM:"))
        .and_then(|v| v.trim().trim_end_matches("kB").trim().parse().ok())
}

fn is_request_id(id: &str) -> bool {
    id.strip_prefix("ow1-").is_some_and(|hex| {
        hex.len() == 40 && hex.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
    })
}

fn is_spawn(argv: &[String]) -> bool {
    argv.len() >= 17 && argv[0] == "thread" && argv[1] == "spawn"
}

fn request_id_table(dir: &Path, argv: &[String], response: &Value) -> bool {
    let mut lock = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(dir.join(REQUEST_IDS_FILE))
        .expect("fake room-cli: open the request-ID table");
    lock.lock()
        .expect("fake room-cli: lock the request-ID table");
    let mut text = String::new();
    std::io::Read::read_to_string(&mut lock, &mut text).expect("read the request-ID table");
    let mut table: serde_json::Map<String, Value> = serde_json::from_str(&text).unwrap_or_default();
    let last = argv.len() - 1;
    let content: Vec<&String> = [3, 7, 9, 11, last].iter().map(|&i| &argv[i]).collect();
    let content = serde_json::to_value(content).expect("content serializes");
    let request_id = &argv[13];
    match table.get(request_id) {
        Some(known) => return *known == content,
        None if response["creates"].as_bool() == Some(true) => {
            table.insert(request_id.clone(), content);
            count(dir, THREADS_FILE);
        }
        None => return true,
    }
    let body = serde_json::to_string(&table).expect("table serializes");
    std::io::Seek::seek(&mut lock, std::io::SeekFrom::Start(0)).expect("seek");
    lock.set_len(0).expect("truncate");
    lock.write_all(body.as_bytes()).expect("write the table");
    lock.sync_all().expect("sync the table");
    true
}

fn is_tell(argv: &[String]) -> bool {
    argv.len() >= 8 && argv[0] == "thread" && argv[1] == "tell"
}

fn count(dir: &Path, name: &str) -> u64 {
    let mut file = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(dir.join(name))
        .expect("fake room-cli: open a counter");
    file.lock().expect("fake room-cli: lock a counter");
    let mut text = String::new();
    std::io::Read::read_to_string(&mut file, &mut text).expect("read a counter");
    let n = text.trim().parse::<u64>().unwrap_or(0) + 1;
    std::io::Seek::seek(&mut file, std::io::SeekFrom::Start(0)).expect("seek");
    file.set_len(0).expect("truncate");
    file.write_all(n.to_string().as_bytes())
        .expect("write a counter");
    file.sync_all().expect("sync a counter");
    n
}

fn snapshot_records(dir: &Path, kind: &str, into: &str) {
    let state = match fs::read_to_string(dir.join(STATE_FILE)) {
        Ok(path) => PathBuf::from(path.trim()),
        Err(_) => match std::env::var_os(STATE_DIR_ENV) {
            Some(path) => PathBuf::from(path),
            None => return,
        },
    };
    let mut records = Vec::new();
    if let Ok(entries) = fs::read_dir(Path::new(&state).join(kind)) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().is_some_and(|e| e == "json")
                && let Ok(text) = fs::read_to_string(&path)
                && let Ok(value) = serde_json::from_str::<Value>(&text)
            {
                records.push(value);
            }
        }
    }
    let _ = fs::write(
        dir.join(into),
        serde_json::to_string(&records).expect("records serialize"),
    );
}

fn is_thread_id(id: &str) -> bool {
    (1..=128).contains(&id.len())
        && !id.starts_with('-')
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

fn is_archive(argv: &[String]) -> bool {
    argv.len() == 4 && argv[0] == "thread" && argv[1] == "archive"
}

fn is_show(argv: &[String]) -> bool {
    argv.len() == 4 && argv[0] == "thread" && argv[1] == "show"
}

fn archive(dir: &Path, id: &str) {
    if let Ok(mut f) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join(ARCHIVED_FILE))
    {
        let _ = f.write_all(format!("{id}\n").as_bytes());
    }
}

fn archived(dir: &Path, id: &str) -> bool {
    fs::read_to_string(dir.join(ARCHIVED_FILE)).is_ok_and(|t| t.lines().any(|l| l == id))
}

fn is_detail_read(argv: &[String]) -> bool {
    matches!(argv.get(1).map(String::as_str), Some("show" | "output"))
}

struct LoopWrite<'a> {
    verb: &'static str,
    files: Vec<(&'static str, &'a str)>,
    webhook: bool,
}

fn loop_write(argv: &[String]) -> Option<LoopWrite<'_>> {
    let a: Vec<&str> = argv.iter().map(String::as_str).collect();
    match a.as_slice() {
        ["loop", "create", rest @ ..] => loop_create(rest),
        ["loop", "update", id, rest @ ..] if !id.starts_with('-') => loop_update(rest),
        _ => None,
    }
}

fn take<'a>(rest: &mut &[&'a str], flag: &str) -> Option<&'a str> {
    match *rest {
        &[f, value, ref tail @ ..] if f == flag => {
            *rest = tail;
            Some(value)
        }
        _ => None,
    }
}

fn take_switch(rest: &mut &[&str], flag: &str) -> bool {
    match *rest {
        &[f, ref tail @ ..] if f == flag => {
            *rest = tail;
            true
        }
        _ => false,
    }
}

fn take_agent(rest: &mut &[&str]) -> Option<()> {
    if take(rest, "--provider").is_none() {
        return Some(());
    }
    take(rest, "--model")?;
    take(rest, "--reasoning").map(|_| ())
}

#[derive(PartialEq)]
enum Trigger {
    Absent,
    Scheduled,
    Webhook,
}

fn take_trigger(rest: &mut &[&str], create: bool) -> Option<Trigger> {
    if take(rest, "--cron").is_some() {
        return take(rest, "--timezone").map(|_| Trigger::Scheduled);
    }
    Some(
        if take(rest, "--at").is_some() || (create && take(rest, "--in").is_some()) {
            Trigger::Scheduled
        } else if create && take_switch(rest, "--webhook") {
            Trigger::Webhook
        } else {
            Trigger::Absent
        },
    )
}

fn loop_create<'a>(mut rest: &[&'a str]) -> Option<LoopWrite<'a>> {
    let r = &mut rest;
    take(r, "--name")?;
    let mut files = vec![("--prompt-file", take(r, "--prompt-file")?)];
    let trigger = take_trigger(r, true).filter(|t| *t != Trigger::Absent)?;
    if !(take_switch(r, "--new-thread") || take_switch(r, "--same-thread")) {
        return None;
    }
    files.extend(take(r, "--script-file").map(|f| ("--script-file", f)));
    take_agent(r)?;
    take(r, "--priority").filter(|p| matches!(*p, "1" | "2" | "3" | "4"))?;
    take(r, "--secrets")?;
    r.is_empty().then_some(LoopWrite {
        verb: "create",
        files,
        webhook: trigger == Trigger::Webhook,
    })
}

fn loop_update<'a>(mut rest: &[&'a str]) -> Option<LoopWrite<'a>> {
    let given = !rest.is_empty();
    let r = &mut rest;
    take(r, "--name");
    if take(r, "--priority").is_some_and(|p| !matches!(p, "1" | "2" | "3" | "4")) {
        return None;
    }
    take(r, "--prompt");
    take_trigger(r, false)?;
    let files = take(r, "--script-file")
        .map(|f| ("--script-file", f))
        .into_iter()
        .collect();
    take_agent(r)?;
    take(r, "--secrets");
    (given && r.is_empty()).then_some(LoopWrite {
        verb: "update",
        files,
        webhook: false,
    })
}

fn record_loop_write(dir: &Path, argv: &[String], write: &LoopWrite) -> std::io::Result<bool> {
    let mut files = serde_json::Map::new();
    let mut readable = true;
    for &(flag, path) in &write.files {
        let text = fs::read_to_string(path).ok();
        readable &= text.is_some();
        files.insert(flag.to_owned(), text.map_or(Value::Null, Value::String));
    }
    let line = serde_json::json!({"argv": argv, "files": files});
    fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join(LOOP_WRITES_LOG))?
        .write_all(format!("{line}\n").as_bytes())?;
    Ok(readable)
}

fn find_response(scenario_path: &Path, argv: &[String]) -> Option<(Value, PathBuf)> {
    let text = fs::read_to_string(scenario_path)
        .unwrap_or_else(|e| panic!("fake room-cli: cannot read {scenario_path:?}: {e}"));
    let scenario: Value = serde_json::from_str(&text)
        .unwrap_or_else(|e| panic!("fake room-cli: {scenario_path:?} is not JSON: {e}"));
    let base = scenario_path
        .parent()
        .unwrap_or(Path::new("."))
        .to_path_buf();

    let own = scenario["responses"].as_array().into_iter().flatten();
    for response in own {
        let wanted: Vec<&str> = response["argv"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .collect();
        let mut got: Vec<&str> = argv.iter().map(String::as_str).collect();
        if response["any_attachments"].as_bool() == Some(true) && is_tell(argv) {
            let pairs = 2 * attachment_pairs(argv).len();
            got.drain(6..6 + pairs);
        }
        let got = if response["any_text"].as_bool() == Some(true) && is_tell(argv) {
            &got[..got.len() - 1]
        } else {
            &got[..]
        };
        let any_spawn = response["any_spawn"].as_bool() == Some(true) && is_spawn(argv);
        let any_loop_write = loop_write(argv).is_some_and(|write| {
            response["any_loop_write"].as_str() == Some(write.verb)
                && (response["webhook"].as_bool() != Some(true) || write.webhook)
        });
        if any_spawn || any_loop_write || wanted == got {
            return Some((response.clone(), base));
        }
    }
    let parent = scenario["extends"].as_str()?;
    find_response(&base.join("..").join(parent).join("scenario.json"), argv)
}

fn kill_parent() {
    let parent = std::os::unix::process::parent_id();
    let status = std::process::Command::new("kill")
        .args(["-9", &parent.to_string()])
        .status()
        .expect("fake room-cli: run kill");
    assert!(status.success(), "fake room-cli: kill {parent} failed");
    thread::sleep(Duration::from_millis(50));
}

fn answer(response: &Value, base: &Path, dir: &Path) -> ExitCode {
    if let Some(ms) = response["delay_ms"].as_u64() {
        thread::sleep(Duration::from_millis(ms));
    }
    if response["kill_parent"].as_bool() == Some(true) {
        kill_parent();
    }
    if response["abort"].as_bool() == Some(true) {
        std::process::abort();
    }
    if response["hang"].as_bool() == Some(true) {
        let _ = fs::write(dir.join(HANG_PID_FILE), std::process::id().to_string());
        loop {
            thread::sleep(Duration::from_secs(3600));
        }
    }
    if let Some(size) = response["oversized_stdout_bytes"].as_u64() {
        let body = vec![0_u8; usize::try_from(size).expect("oversized fixture size")];
        if std::io::stdout().lock().write_all(&body).is_err() {
            return ExitCode::FAILURE;
        }
    }
    if let Some(file) = response["stdout_file"].as_str() {
        let body = fs::read(base.join(file))
            .unwrap_or_else(|e| panic!("fake room-cli: cannot read {file}: {e}"));
        std::io::stdout().write_all(&body).expect("stdout");
    }
    if let Some(text) = response["stdout"].as_str() {
        print!("{text}");
    }
    if let Some(text) = response["stderr"].as_str() {
        eprintln!("{text}");
    }
    if response["kill_parent_after_answer"].as_bool() == Some(true) {
        std::io::stdout().flush().expect("stdout");
        kill_parent();
    }
    let code = response["exit"].as_u64().unwrap_or(0);
    ExitCode::from(u8::try_from(code).unwrap_or(1))
}
