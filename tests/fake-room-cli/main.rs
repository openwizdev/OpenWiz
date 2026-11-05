//! The fake `room-cli` the tests run in place of the real one. Test-only.
//!
//! A test makes a directory holding a symlink named `room-cli` to this
//! binary, plus a file `fake-room-cli.scenario` with the absolute path of a
//! fixture `scenario.json`. The fake finds that file next to the path it was
//! started as (`argv[0]`), so tests running in parallel never share state.
//!
//! For each call it:
//! 1. appends its arguments, as one JSON array per line, to `invocations.log`
//!    in the same directory, and the **names** (never the values) of the
//!    CloudRoom variables in its environment (`ROOM_*`, `BB_*` and
//!    `CLOUDROOM_*`), sorted, to `environment.log` (OpenWiz 0.0.4, N2);
//! 2. refuses anything outside the OpenWiz allowlist with exit 97;
//! 3. answers from the scenario: stdout (inline or from a file), stderr and an
//!    exit code, or never answers (`"hang": true`, after writing its process
//!    id to `hang.pid`).
//!    The oversized-response fixture uses `stream_stdout_file` to copy its
//!    file directly to stdout rather than loading it all into memory.
//!
//! A scenario may `extends` another; its own responses are tried first.
//! A `thread show` or `thread output` of an id with no response gets the
//! not-found answer observed in capture C.
//!
//! **`thread tell`** (OpenWiz 0.0.3, the one write; documented, not
//! observed). The fake accepts only the exact argument shape OpenWiz chose:
//! `thread tell <id> --mode queue|steer --json -- <text>`. For each accepted
//! call it first:
//! 1. adds one to `tell-calls.count` in the fake's directory, under an
//!    exclusive file lock, so concurrent processes are counted exactly;
//! 2. copies every send record under the state directory's `sends/` into
//!    `records-at-tell-<n>.json`, so a test can see what was on disk at the
//!    moment of the call. The state directory is named by the file
//!    `fake-room-cli.state` next to the fake, else by `$OPENWIZ_STATE_DIR`.
//!
//! A tell response matches on everything but the text when it has
//! `"any_text": true`. It may also `delay_ms` before answering, `abort`
//! (a crash: no exit code), `kill_parent` before answering (the sender dies
//! during the call), or `kill_parent_after_answer` (the sender dies after
//! the receipt is printed, before it can record the outcome).
//! `kill_parent` and `kill_parent_after_answer` send SIGKILL to whatever
//! started the fake: use them only when `openwiz` or the harness runs as its
//! own process, never with an in-process `send` (that would kill the test
//! runner).
//!
//! **`cloud status --json` and `thread spawn`** (OpenWiz 0.0.4, ClosedWiz#11,
//! A1 phase 2; the flags observed in spike run 3's help, the call never
//! observed). The fake accepts `spawn` only in the exact shape OpenWiz
//! chose: `thread spawn --project <id> --machine cloud --provider
//! codex|claude-code --model <m> --reasoning-level low|medium|high|xhigh|max
//! --request-id ow1-<40 hex> --json --prompt <text>`. For each accepted call
//! it first adds one to `spawn-calls.count` and copies the new-thread records
//! under the state directory's `new-threads/` into
//! `records-at-spawn-<n>.json`, as for `tell`. Then its **request-ID table**
//! (`request-ids.json`, under the same kind of lock) models what the
//! provider's source reads (#11, not observed): the same request id with
//! the same content (project, provider, model, effort, text) creates nothing
//! new; with different content it is refused with the documented 409 line;
//! a new one is recorded, and counted in `threads-created.count`, when the
//! response `creates`. A spawn response matches every accepted spawn with
//! `"any_spawn": true`.
//!
//! **Attachments** (OpenWiz 0.0.4, B2, ClosedWiz#15, sheet B-7; the flags
//! observed in spike run 3's help, a call with them never observed). The
//! fake accepts `--file <path>` and `--image <path>` pairs on `tell` (after
//! `--json`, before `--`, and never with `steer`) and on `spawn` (after
//! `--json`, before `--prompt`), each path absolute and of a staged copy's
//! shape, `…/attachments/<id>/<safe name>`, checked by its own copy of the
//! rules. Like `room-cli` (#15's F3 and F21, source-read), it then
//! **uploads** them before anything else: it reads every file whole, all
//! held in memory at once, and appends one JSON line to `attachments.log`:
//! the call, its request id (for `spawn`), each flag, path, SHA-256 and
//! size at that moment, and its peak memory (`VmHWM`, on Linux). A file it
//! can't read fails the call there, as an upload error would: exit 1 with a
//! line that is no documented rejection; so does a response with
//! `"upload_fails_after": <n>`, after reading `n` files. The request-ID table compares the
//! text, never the attachments, as CloudRoom's does (F17). A tell response
//! with `"any_attachments": true` matches whatever attachments the call
//! carries.
//!
//! **`thread archive`** (OpenWiz 0.0.6, B4, ClosedWiz#120; observed in help
//! (0.43.1), the call never run). The fake accepts only `thread archive
//! <id> --json`, and counts each accepted call in `archive-calls.count`.
//! A response with `"archives": true` archives the thread: its id is
//! appended to `archived-threads.log`. From then on, a `thread show` of that
//! id answers from its response's `after_archive` (a response of its own),
//! when it has one, so a test can read an archive back.

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

    let scenario_path = match fs::read_to_string(dir.join(SCENARIO_FILE)) {
        Ok(p) => PathBuf::from(p.trim()),
        Err(e) => {
            eprintln!("fake room-cli: no {SCENARIO_FILE} next to {argv0:?}: {e}");
            return ExitCode::from(NO_FIXTURE);
        }
    };

    let found = find_response(&scenario_path, &argv);
    // The upload, before the request (F3): every attachment read whole. A
    // response may make it fail after `upload_fails_after` files.
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
        // One write per line, so concurrent calls never interleave lines.
        let _ = f.write_all(format!("{line}\n").as_bytes());
    }
}

/// The names of the CloudRoom variables this call was started with.
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

/// The fake's own copy of the allowlist, kept independent of the adapter's
/// so that a mistake in one is caught by the other.
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
        // The one write, in exactly the shape OpenWiz chose (documented, not
        // observed): no other flag, never `auto`, `--` before the text; B2's
        // attachment pairs after `--json`, never with `steer`.
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
        // OpenWiz 0.0.4: the catalogue read, and the second write in exactly
        // its shape (the flags observed in help, spike run 3).
        ["cloud", "status", "--json"] => true,
        // OpenWiz 0.0.6 (A6, ClosedWiz#114): one Cloud thread's branch, the
        // read approved on #107, 2026-10-31 (approval provenance is linked
        // by crates/adapters/cloudroom/src/allowlist.rs).
        ["cloud", "thread-workspace", id, "--json"] => !id.starts_with('-'),
        // OpenWiz 0.0.6 (B4, ClosedWiz#120): the third write, in exactly
        // its shape (observed in help, 0.43.1): never `--self`.
        ["thread", "archive", id, "--json"] => is_thread_id(id),
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

/// B2: zero or more `--file <path>` or `--image <path>` pairs, each path a
/// staged copy's: absolute, no `.` or `..` and no empty component, no
/// control character, never a `file:` URL, and ending in
/// `attachments/<id>/<safe name>` (the fake's own copy of the id and safe
/// name rules).
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

/// The attachment pairs of an accepted `tell` or `spawn`: `(flag, path)`.
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

/// The upload `room-cli` makes before its request (F3, F21, source-read):
/// every attachment read whole, all held at once, then one line in
/// `attachments.log`. `false` when a file can't be read: the call fails
/// there.
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

/// This process's peak resident memory in KiB (`VmHWM`), on Linux.
fn peak_memory_kib() -> Option<u64> {
    let status = fs::read_to_string("/proc/self/status").ok()?;
    status
        .lines()
        .find_map(|l| l.strip_prefix("VmHWM:"))
        .and_then(|v| v.trim().trim_end_matches("kB").trim().parse().ok())
}

/// `ow1-` and 40 lowercase hex digits, as OpenWiz derives a request id.
fn is_request_id(id: &str) -> bool {
    id.strip_prefix("ow1-").is_some_and(|hex| {
        hex.len() == 40 && hex.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
    })
}

fn is_spawn(argv: &[String]) -> bool {
    argv.len() >= 17 && argv[0] == "thread" && argv[1] == "spawn"
}

/// The request-ID table, under its own lock: `false` when the request id
/// was used with other content (refused, nothing created). The same
/// content again creates nothing; a new request id is recorded, and
/// counted as a thread, when the response `creates`.
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
    // Everything but the request id: project, provider, model, effort, text.
    // Never the attachments: CloudRoom's dedup compares the text (F17).
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

/// Adds one to the cross-process counter in `name` and returns the new
/// count.
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

/// Copies the records under the state directory's `kind/` on disk at the
/// moment of a write call into `into`.
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

/// The fake's own copy of `ThreadId`'s rule: 1 to 128 ASCII letters,
/// digits, `_` or `-`, not starting with `-`.
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

/// Records the thread `id` as archived: one line, in one write.
fn archive(dir: &Path, id: &str) {
    if let Ok(mut f) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join(ARCHIVED_FILE))
    {
        let _ = f.write_all(format!("{id}\n").as_bytes());
    }
}

/// Whether a `thread archive` with `"archives": true` archived `id`.
fn archived(dir: &Path, id: &str) -> bool {
    fs::read_to_string(dir.join(ARCHIVED_FILE)).is_ok_and(|t| t.lines().any(|l| l == id))
}

fn is_detail_read(argv: &[String]) -> bool {
    matches!(argv.get(1).map(String::as_str), Some("show" | "output"))
}

/// Finds the response for `argv`, and the directory its files are relative to.
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
            // The call without its attachment pairs (B2).
            let pairs = 2 * attachment_pairs(argv).len();
            got.drain(6..6 + pairs);
        }
        let got = if response["any_text"].as_bool() == Some(true) && is_tell(argv) {
            &got[..got.len() - 1]
        } else {
            &got[..]
        };
        let any_spawn = response["any_spawn"].as_bool() == Some(true) && is_spawn(argv);
        if any_spawn || wanted == got {
            return Some((response.clone(), base));
        }
    }
    let parent = scenario["extends"].as_str()?;
    find_response(&base.join("..").join(parent).join("scenario.json"), argv)
}

/// Kills the process that started this fake (the sender), with SIGKILL,
/// and waits until `kill` has delivered it.
fn kill_parent() {
    let parent = std::os::unix::process::parent_id();
    let status = std::process::Command::new("kill")
        .args(["-9", &parent.to_string()])
        .status()
        .expect("fake room-cli: run kill");
    assert!(status.success(), "fake room-cli: kill {parent} failed");
    // The parent is gone; give the kernel a moment, then end quietly.
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
        // Lets a test check that the hung read was stopped.
        let _ = fs::write(dir.join(HANG_PID_FILE), std::process::id().to_string());
        loop {
            thread::sleep(Duration::from_secs(3600));
        }
    }
    if let Some(file) = response["stream_stdout_file"].as_str() {
        let input = fs::File::open(base.join(file))
            .unwrap_or_else(|e| panic!("fake room-cli: cannot open {file}: {e}"));
        // Rust's io::copy forbids its kernel shortcut from files to pipes.
        // This immutable fixture can use Python's explicit sendfile instead;
        // Python 3 is already required by the repository's test tooling.
        let status = std::process::Command::new("/usr/bin/python3")
            .args([
                "-I",
                "-S",
                "-c",
                r#"
import errno, os, sys
if sys.platform == "linux":
    import fcntl
    fcntl.fcntl(1, fcntl.F_SETPIPE_SZ, 1024 * 1024)
offset = 0
size = os.fstat(0).st_size
try:
    while offset < size:
        copied = os.sendfile(1, 0, offset, size - offset)
        if not copied:
            raise RuntimeError("short fixture file")
        offset += copied
except OSError as error:
    if error.errno not in (errno.EINVAL, errno.ENOSYS, errno.ENOTSOCK, errno.EOPNOTSUPP):
        raise
    import shutil
    os.lseek(0, offset, os.SEEK_SET)
    shutil.copyfileobj(sys.stdin.buffer, sys.stdout.buffer, 64 * 1024)
    sys.stdout.buffer.flush()
"#,
            ])
            .stdin(input)
            .status()
            .expect("stream oversized fixture");
        if !status.success() {
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
