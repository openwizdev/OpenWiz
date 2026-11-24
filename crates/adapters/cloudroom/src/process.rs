use std::io::Read as _;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver};
use std::thread;
use std::time::{Duration, Instant};

use openwiz_core::limits::READ_TIMEOUT;
use openwiz_core::source::SourceError;

use crate::allowlist::Invocation;

pub const MAX_STDOUT_BYTES: usize = 32 * 1024 * 1024;

const MAX_STDERR_BYTES: usize = 64 * 1024;

const DRAIN_GRACE: Duration = Duration::from_millis(100);

const POLL: Duration = Duration::from_millis(5);

static FIXTURE_FAST_POLL: AtomicBool = AtomicBool::new(false);

pub(crate) fn use_fast_polling_for_fixtures() {
    FIXTURE_FAST_POLL.store(true, Ordering::SeqCst);
}

fn poll_interval() -> Duration {
    if FIXTURE_FAST_POLL.load(Ordering::SeqCst) {
        Duration::from_millis(1)
    } else {
        POLL
    }
}

pub const SCRUBBED_ENV: &[&str] = &["ROOM_THREAD_ID", "ROOM_PROJECT_ID"];

pub const SCRUBBED_ENV_PREFIX: &str = "BB_";

pub const KEPT_ENV: &str = "ROOM_SERVER_URL";

pub fn is_scrubbed(name: &str) -> bool {
    is_scrubbed_bytes(name.as_bytes())
}

fn is_scrubbed_bytes(name: &[u8]) -> bool {
    name != KEPT_ENV.as_bytes()
        && (SCRUBBED_ENV.iter().any(|n| n.as_bytes() == name)
            || name.starts_with(SCRUBBED_ENV_PREFIX.as_bytes()))
}

fn scrub(command: &mut Command) -> &mut Command {
    for (name, _) in std::env::vars_os() {
        if is_scrubbed_bytes(name.as_encoded_bytes()) {
            command.env_remove(&name);
        }
    }
    command
}

enum Failure {
    Source(SourceError),
    Exited {
        exit_code: Option<i32>,
        stderr: Vec<u8>,
    },
}

pub fn run(
    program: &Path,
    invocation: &Invocation,
    deadline: Instant,
) -> Result<Vec<u8>, SourceError> {
    run_with_read_timeout(program, invocation, deadline, read_timeout())
}

pub(crate) fn run_with_read_timeout(
    program: &Path,
    invocation: &Invocation,
    deadline: Instant,
    timeout: Duration,
) -> Result<Vec<u8>, SourceError> {
    execute_with_read_timeout(program, invocation, deadline, timeout.min(read_timeout())).map_err(
        |failure| match failure {
            Failure::Source(e) => e,
            Failure::Exited { exit_code, stderr } => SourceError::CommandFailed {
                exit_code,
                detail: diagnostic(&stderr),
            },
        },
    )
}

pub(crate) enum SpawnFailure {
    Source(SourceError),
    Exited {
        exit_code: Option<i32>,
        first_line: String,
    },
}

pub(crate) fn run_spawn(
    program: &Path,
    invocation: &Invocation,
    deadline: Instant,
) -> Result<Vec<u8>, SpawnFailure> {
    execute(program, invocation, deadline).map_err(|failure| match failure {
        Failure::Source(e) => SpawnFailure::Source(e),
        Failure::Exited { exit_code, stderr } => SpawnFailure::Exited {
            exit_code,
            first_line: String::from_utf8_lossy(&stderr)
                .lines()
                .map(str::trim)
                .find(|l| !l.is_empty())
                .unwrap_or_default()
                .to_owned(),
        },
    })
}

static FIXTURE_READ_TIMEOUT_MS: AtomicU64 = AtomicU64::new(0);

pub(crate) fn lower_read_timeout(timeout: Duration) {
    let ms = u64::try_from(timeout.as_millis())
        .unwrap_or(u64::MAX)
        .max(1);
    FIXTURE_READ_TIMEOUT_MS.store(ms, Ordering::SeqCst);
}

fn read_timeout() -> Duration {
    read_timeout_with(FIXTURE_READ_TIMEOUT_MS.load(Ordering::SeqCst))
}

fn read_timeout_with(fixture_ms: u64) -> Duration {
    match fixture_ms {
        0 => READ_TIMEOUT,
        ms => Duration::from_millis(ms).min(READ_TIMEOUT),
    }
}

fn execute(program: &Path, invocation: &Invocation, deadline: Instant) -> Result<Vec<u8>, Failure> {
    execute_with_read_timeout(program, invocation, deadline, read_timeout())
}

fn execute_with_read_timeout(
    program: &Path,
    invocation: &Invocation,
    deadline: Instant,
    timeout: Duration,
) -> Result<Vec<u8>, Failure> {
    let started = Instant::now();
    let stop_at = deadline.min(started + timeout + invocation.allowance());
    if started >= stop_at {
        return Err(Failure::Source(SourceError::TimedOut { after_ms: 0 }));
    }
    let resolved = crate::locate::programs(program).map_err(Failure::Source)?;
    let mut child = launch(&resolved, invocation, started, stop_at)?;
    let stdout = collect(child.stdout.take(), MAX_STDOUT_BYTES);
    let stderr = collect(child.stderr.take(), MAX_STDERR_BYTES);
    let timed_out = || {
        Failure::Source(SourceError::TimedOut {
            after_ms: u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX),
        })
    };

    let refuse_oversized_early = invocation.is_read();
    let mut collected_stdout = None;
    let status = loop {
        if refuse_oversized_early
            && collected_stdout.is_none()
            && let Ok(out) = stdout.try_recv()
        {
            if out.len() > MAX_STDOUT_BYTES {
                stop(&mut child);
                return Err(Failure::Source(SourceError::Malformed {
                    detail: format!("printed more than {MAX_STDOUT_BYTES} bytes"),
                }));
            }
            collected_stdout = Some(out);
        }
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => {
                let left = stop_at.saturating_duration_since(Instant::now());
                if left.is_zero() {
                    stop(&mut child);
                    return Err(timed_out());
                }
                thread::sleep(poll_interval().min(left));
            }
            Err(e) => {
                stop(&mut child);
                return Err(Failure::Source(SourceError::Unavailable {
                    detail: format!("waiting for room-cli failed ({:?})", e.kind()),
                }));
            }
        }
    };

    let drain_until = stop_at.max(Instant::now() + DRAIN_GRACE);
    let left = drain_until.saturating_duration_since(Instant::now());
    let out = match collected_stdout {
        Some(out) => out,
        None => stdout.recv_timeout(left).map_err(|_| timed_out())?,
    };
    let left = drain_until.saturating_duration_since(Instant::now());
    let err = stderr.recv_timeout(left).unwrap_or_default();

    if out.len() > MAX_STDOUT_BYTES {
        return Err(Failure::Source(SourceError::Malformed {
            detail: format!("printed more than {MAX_STDOUT_BYTES} bytes"),
        }));
    }
    if status.success() {
        return Ok(out);
    }
    Err(Failure::Exited {
        exit_code: status.code(),
        stderr: err,
    })
}

fn launch(
    resolved: &[std::path::PathBuf],
    invocation: &Invocation,
    started: Instant,
    stop_at: Instant,
) -> Result<Child, Failure> {
    let mut spawned = None;
    for program in resolved {
        if Instant::now() >= stop_at {
            return Err(Failure::Source(SourceError::TimedOut {
                after_ms: u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX),
            }));
        }
        match scrub(&mut Command::new(program))
            .args(invocation.argv())
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(child) => {
                spawned = Some(child);
                break;
            }
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => continue,
            Err(_) => break,
        }
    }
    spawned.ok_or_else(|| {
        Failure::Source(SourceError::Unavailable {
            detail: "room-cli could not be started".to_owned(),
        })
    })
}

const MAX_REASON_CHARS: usize = 60;

pub const NOT_FOUND_LINE: &str = "Error: HTTP 404: Thread not found";

fn diagnostic(stderr: &[u8]) -> String {
    let text = String::from_utf8_lossy(stderr);
    let Some(line) = text.lines().map(str::trim).find(|l| !l.is_empty()) else {
        return "no error output".to_owned();
    };
    if line != NOT_FOUND_LINE && line.contains("HTTP 404: Thread not found") {
        return format!("{NOT_FOUND_LINE} (detail withheld)");
    }
    if is_safe(line) {
        return line.to_owned();
    }
    match http_status(line) {
        Some(code) => format!("Error: HTTP {code} (detail withheld)"),
        None => "room-cli error (detail withheld)".to_owned(),
    }
}

fn is_safe(line: &str) -> bool {
    let Some((code, reason)) = line
        .strip_prefix("Error: HTTP ")
        .and_then(|rest| rest.split_at_checked(3))
    else {
        return false;
    };
    is_status(code)
        && (reason.is_empty()
            || reason.strip_prefix(": ").is_some_and(|phrase| {
                phrase.chars().count() <= MAX_REASON_CHARS
                    && phrase
                        .split(' ')
                        .all(|w| !w.is_empty() && w.bytes().all(|b| b.is_ascii_alphabetic()))
            }))
}

fn http_status(line: &str) -> Option<&str> {
    let bytes = line.as_bytes();
    line.match_indices("HTTP ").find_map(|(i, _)| {
        let code = line.get(i + 5..i + 8)?;
        let starts_word = i == 0 || !bytes[i - 1].is_ascii_alphanumeric();
        let ends_word = !bytes.get(i + 8).is_some_and(u8::is_ascii_digit);
        (starts_word && ends_word && is_status(code)).then_some(code)
    })
}

fn is_status(code: &str) -> bool {
    let b = code.as_bytes();
    b.len() == 3 && (b'1'..=b'5').contains(&b[0]) && b[1..].iter().all(u8::is_ascii_digit)
}

fn collect(pipe: Option<impl std::io::Read + Send + 'static>, limit: usize) -> Receiver<Vec<u8>> {
    let (tx, rx) = mpsc::channel();
    thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(pipe) = pipe {
            let _ = pipe.take(limit as u64 + 1).read_to_end(&mut buf);
        }
        let _ = tx.send(buf);
    });
    rx
}

fn stop(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(test)]
#[path = "../../../../tests/support/cloudroom_process_tests.rs"]
mod tests;

#[cfg(test)]
mod scrub_tests {
    use super::*;

    #[test]
    fn the_scrub_removes_thread_context_and_keeps_the_server_address() {
        for name in ["ROOM_THREAD_ID", "ROOM_PROJECT_ID", "BB_THREAD_ID", "BB_"] {
            assert!(is_scrubbed(name), "{name}");
        }
        for name in [
            "ROOM_SERVER_URL",
            "PATH",
            "HOME",
            "ROOM_THREAD",
            "XBB_THREAD_ID",
        ] {
            assert!(!is_scrubbed(name), "{name}");
        }
        assert!(is_scrubbed_bytes(b"BB_\xff"));
    }

    struct PrivateDir(std::path::PathBuf);

    impl PrivateDir {
        fn new(label: &str) -> Self {
            use std::os::unix::fs::DirBuilderExt;
            static NEXT: AtomicU64 = AtomicU64::new(0);
            loop {
                let path = std::env::temp_dir().join(format!(
                    "openwiz-2564-{label}-{}-{}",
                    std::process::id(),
                    NEXT.fetch_add(1, Ordering::SeqCst)
                ));
                match std::fs::DirBuilder::new().mode(0o700).create(&path) {
                    Ok(()) => return Self(path),
                    Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
                    Err(e) => panic!("private fixture directory: {e}"),
                }
            }
        }

        fn file(&self, name: &str, text: &str, mode: u32) -> std::path::PathBuf {
            use std::io::Write as _;
            use std::os::unix::fs::OpenOptionsExt;
            let path = self.0.join(name);
            std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(mode)
                .open(&path)
                .and_then(|mut f| f.write_all(text.as_bytes()))
                .unwrap();
            path
        }
    }

    impl Drop for PrivateDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    const PROBE: &str = "OPENWIZ_SYN_2564_PROBE";

    #[cfg(target_os = "linux")]
    #[test]
    fn a_child_loses_thread_context_and_keeps_the_server_address() {
        let dir = PrivateDir::new("scrub");
        dir.file(
            "room-cli",
            "#!/bin/sh\n/bin/cat /proc/$$/environ > \"${0%/*}/seen\"\n",
            0o700,
        );
        let parent = dir.file(
            "probe-parent",
            r#"#!/bin/sh
exec /usr/bin/env -i \
    ROOM_THREAD_ID=thr_syn_2564 ROOM_PROJECT_ID=prj_syn_2564 BB_THREAD_ID=thr_syn_2564 \
    ROOM_SERVER_URL=http://127.0.0.1:9 SYN_KEPT=synthetic \
    "BB_$(printf '\377')=synthetic" "OPENWIZ_SYN_2564_PROBE=${0%/*}" \
    "$OPENWIZ_SYN_2564_TEST_EXE" --exact process::scrub_tests::scrub_probe --nocapture
"#,
            0o700,
        );
        let out = Command::new(parent)
            .env_clear()
            .env(
                "OPENWIZ_SYN_2564_TEST_EXE",
                std::env::current_exe().unwrap(),
            )
            .stdin(Stdio::null())
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{}{}",
            String::from_utf8_lossy(&out.stdout),
            String::from_utf8_lossy(&out.stderr)
        );
        let seen = std::fs::read(dir.0.join("seen")).unwrap();
        let mut child: Vec<String> = seen
            .split(|b| *b == 0)
            .filter(|pair| !pair.is_empty())
            .map(|pair| String::from_utf8_lossy(pair).into())
            .collect();
        child.sort();
        assert_eq!(
            child,
            [
                format!("{PROBE}={}", dir.0.display()),
                "ROOM_SERVER_URL=http://127.0.0.1:9".into(),
                "SYN_KEPT=synthetic".into(),
            ]
        );
    }

    #[test]
    fn scrub_probe() {
        let Some(dir) = std::env::var_os(PROBE) else {
            return;
        };
        let program = std::path::PathBuf::from(dir).join("room-cli");
        let invocation = Invocation::ThreadList {
            include_hidden: false,
            include_archived: false,
        };
        run(
            &program,
            &invocation,
            Instant::now() + Duration::from_secs(10),
        )
        .unwrap();
    }

    #[test]
    fn the_launch_deadline_is_checked_before_each_candidate() {
        let dir = PrivateDir::new("denied");
        let denied = dir.file("room-cli", "#!/bin/sh\nexit 0\n", 0o600);
        let candidates = vec![denied; 2048];
        let invocation = Invocation::ThreadList {
            include_hidden: false,
            include_archived: false,
        };
        let budget = Duration::from_millis(20);
        let started = Instant::now();
        let result = launch(&candidates, &invocation, started, started + budget);
        let elapsed = started.elapsed();
        assert!(
            matches!(result, Err(Failure::Source(SourceError::TimedOut { .. }))),
            "after {elapsed:?}"
        );
    }
}
