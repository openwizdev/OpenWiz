//! Runs one allowlisted `gh` call under a deadline (OpenWiz 0.0.6, A3,
//! ClosedWiz#111), shaped like the CloudRoom adapter's runner.
//!
//! Standard library only: a child process, two reader threads and polling.
//! A call is stopped at the earlier of the run's deadline and
//! [`READ_TIMEOUT`]; a stopped child is killed and reaped. Nothing is
//! retried.
//!
//! **Only an [`Invocation`] runs**, with exactly its arguments, and only an
//! argument list that some module's part of the allowlist allows builds
//! one. While every part is empty (A3), nothing can run.
//!
//! **Its stdin is closed**, so `gh` can never wait for input. **Its
//! environment passes through unchanged**: `gh` finds its login there.
//!
//! **None of `gh`'s error text is shown.** A1 saw no `gh` error line (every
//! read exited 0), so no safe grammar is known: a failed call is reported
//! only by its exit code and, when its first non-empty stderr line has one
//! as a word of its own, its HTTP status ([`diagnostic`]).
//!
//! Only the child itself is killed. A process it started that keeps the
//! pipes open is not; the call then times out without waiting longer.

use std::io::Read as _;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::thread;
use std::time::{Duration, Instant};

use openwiz_core::limits::READ_TIMEOUT;
use openwiz_core::source::SourceError;

use crate::allowlist::Invocation;

/// One explicit execution source, shared by nested reads and confirmed writes.
/// A supplied executor is authoritative: errors never fall back to a login.
pub type Execute = dyn Fn(&Invocation, Instant) -> Result<Vec<u8>, SourceError> + Send + Sync;

#[derive(Clone)]
pub struct Executor(Execution);

#[derive(Clone)]
enum Execution {
    Program(std::path::PathBuf, Duration),
    Supplied(std::sync::Arc<Execute>),
}

impl std::fmt::Debug for Executor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("GitHub executor")
    }
}

impl Executor {
    pub fn program(program: impl Into<std::path::PathBuf>) -> Self {
        Self(Execution::Program(program.into(), READ_TIMEOUT))
    }
    /// A synthetic program with a per-read cap, never above READ_TIMEOUT.
    /// Production executors keep the default cap and read no fixture settings.
    pub fn program_for_fixtures(
        program: impl Into<std::path::PathBuf>,
        read_timeout: Duration,
    ) -> Self {
        Self(Execution::Program(
            program.into(),
            read_timeout.min(READ_TIMEOUT),
        ))
    }

    pub fn supplied(execute: std::sync::Arc<Execute>) -> Self {
        Self(Execution::Supplied(execute))
    }
    pub fn run(&self, call: &Invocation, deadline: Instant) -> Result<Vec<u8>, SourceError> {
        match &self.0 {
            Execution::Program(program, timeout) => {
                run_inner(program, call, deadline, false, *timeout)?.ordinary()
            }
            Execution::Supplied(execute) => execute(call, deadline),
        }
    }
    pub(crate) fn checks(
        &self,
        call: &Invocation,
        deadline: Instant,
    ) -> Result<Vec<u8>, SourceError> {
        match &self.0 {
            Execution::Program(program, timeout) => run_checks(program, call, deadline, *timeout),
            Execution::Supplied(execute) => execute(call, deadline),
        }
    }
}

/// The most stdout a call may print. A1's largest answer was 361 KB (REST
/// `compare`). Provisional, as the CloudRoom adapter's.
pub const MAX_STDOUT_BYTES: usize = 32 * 1024 * 1024;

/// The most stderr kept from a call; only its first line is used, through
/// [`diagnostic`].
const MAX_STDERR_BYTES: usize = 64 * 1024;

/// How long the output of a child that has exited may still be collected
/// after the deadline.
const DRAIN_GRACE: Duration = Duration::from_millis(100);

/// How often a running call is checked.
const POLL: Duration = Duration::from_millis(5);

/// Runs `program` with exactly `invocation.argv()` and returns its stdout.
pub fn run(program: &Path, call: &Invocation, deadline: Instant) -> Result<Vec<u8>, SourceError> {
    run_inner(program, call, deadline, false, READ_TIMEOUT)?.ordinary()
}

/// A bounded GraphQL response with the command failure kept separately.
/// The plan reader must validate these bytes and retain any failure as a gap.
#[derive(Debug)]
pub(crate) struct PlanGraphqlOutput {
    pub stdout: Vec<u8>,
    pub failure: Option<SourceError>,
}

/// Only the existing exact plan GraphQL queries may retain failed stdout.
pub(crate) fn run_plan_graphql(
    program: &Path,
    call: &Invocation,
    deadline: Instant,
) -> Result<PlanGraphqlOutput, SourceError> {
    let words: Vec<_> = call.argv().iter().map(String::as_str).collect();
    if !(crate::plan::ALLOWLIST.allows)(&words) {
        return Err(SourceError::Unavailable {
            detail: "the plan GraphQL runner accepts only exact plan reads".to_owned(),
        });
    }
    let captured = run_inner(program, call, deadline, false, READ_TIMEOUT)?;
    if !captured.complete {
        return Err(SourceError::Malformed {
            detail: "plan GraphQL stdout was incomplete".to_owned(),
        });
    }
    Ok(PlanGraphqlOutput {
        stdout: captured.stdout,
        failure: captured.failure,
    })
}

/// The two checks reads also accept gh's exact no-checks diagnostic as
/// an empty JSON list. No other invocation or failure gets this treatment.
fn run_checks(
    program: &Path,
    call: &Invocation,
    deadline: Instant,
    read_timeout: Duration,
) -> Result<Vec<u8>, SourceError> {
    let argv = call.argv();
    if argv.len() != 5
        || argv[0] != "pr"
        || argv[1] != "checks"
        || argv[3] != "--json"
        || argv[4] != "bucket,name"
    {
        return Err(SourceError::Unavailable {
            detail: "the checks runner accepts only the checks read".to_owned(),
        });
    }
    run_inner(program, call, deadline, true, read_timeout)?.ordinary()
}

struct Captured {
    stdout: Vec<u8>,
    failure: Option<SourceError>,
    complete: bool,
}

impl Captured {
    fn ordinary(self) -> Result<Vec<u8>, SourceError> {
        match self.failure {
            Some(error) => Err(error),
            None => Ok(self.stdout),
        }
    }
}

fn run_inner(
    program: &Path,
    invocation: &Invocation,
    deadline: Instant,
    checks: bool,
    read_timeout: Duration,
) -> Result<Captured, SourceError> {
    let started = Instant::now();
    let stop_at = deadline.min(started + read_timeout);
    if started >= stop_at {
        return Err(SourceError::TimedOut { after_ms: 0 });
    }
    let child = Command::new(program)
        .args(invocation.argv())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| SourceError::Unavailable {
            detail: format!("{} could not be started: {e}", program.display()),
        })?;
    finish(child, started, stop_at, checks, program)
}

fn finish(
    mut child: Child,
    started: Instant,
    stop_at: Instant,
    checks: bool,
    program: &Path,
) -> Result<Captured, SourceError> {
    let stdout = collect(child.stdout.take(), MAX_STDOUT_BYTES);
    let stderr = collect(child.stderr.take(), MAX_STDERR_BYTES);
    let timed_out = || SourceError::TimedOut {
        after_ms: u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX),
    };

    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => {
                let left = stop_at.saturating_duration_since(Instant::now());
                if left.is_zero() {
                    stop(&mut child);
                    return Err(timed_out());
                }
                thread::sleep(POLL.min(left));
            }
            Err(e) => {
                stop(&mut child);
                return Err(SourceError::Unavailable {
                    detail: format!("waiting for {} failed: {e}", program.display()),
                });
            }
        }
    };

    // The pipes close when the child exits, unless something it started
    // still holds them; the deadline, plus a short grace for a child that
    // exited just before it, bounds that wait too.
    let drain_until = stop_at.max(Instant::now() + DRAIN_GRACE);
    let left = drain_until.saturating_duration_since(Instant::now());
    let (out, out_complete) = stdout.recv_timeout(left).map_err(|_| timed_out())?;
    let left = drain_until.saturating_duration_since(Instant::now());
    let (err, err_complete) = stderr.recv_timeout(left).unwrap_or_default();

    if out.len() > MAX_STDOUT_BYTES {
        return Err(SourceError::Malformed {
            detail: format!("printed more than {MAX_STDOUT_BYTES} bytes"),
        });
    }
    if status.success() {
        return Ok(Captured {
            stdout: out,
            failure: None,
            complete: out_complete,
        });
    }
    if checks
        && status.code() == Some(1)
        && out_complete
        && out.is_empty()
        && err_complete
        && err.len() <= MAX_STDERR_BYTES
        && no_checks(&err)
    {
        return Ok(Captured {
            stdout: b"[]".to_vec(),
            failure: None,
            complete: true,
        });
    }
    Ok(Captured {
        stdout: out,
        failure: Some(SourceError::CommandFailed {
            exit_code: status.code(),
            detail: diagnostic(&err),
        }),
        complete: out_complete,
    })
}

// T7 App runner. The personal runner above retains its original spawn chain.
pub(crate) fn run_app(
    program: &Path,
    call: &Invocation,
    credential: &str,
    repository: &str,
    deadline: Instant,
) -> Result<Vec<u8>, SourceError> {
    let started = Instant::now();
    let stop_at = deadline.min(started + READ_TIMEOUT);
    if started >= stop_at || credential.is_empty() {
        return Err(SourceError::TimedOut { after_ms: 0 });
    }
    let child = Command::new(program)
        .args(call.argv())
        .env_clear()
        .env("GH_TOKEN", credential)
        .env("GH_REPO", repository)
        .env("GH_HOST", "github.com")
        .env("PATH", "/usr/bin:/bin")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|_| SourceError::Unavailable {
            detail: "App child could not start".to_owned(),
        })?;
    let argv = call.argv();
    let checks = argv.len() == 5
        && argv[0] == "pr"
        && argv[1] == "checks"
        && argv[3] == "--json"
        && argv[4] == "bucket,name";
    finish(child, started, stop_at, checks, program)?.ordinary()
}

/// Bounded capture for T7's fixed signing and token-exchange children.
pub(crate) fn app_output(
    mut child: Child,
    input: Vec<u8>,
    deadline: Instant,
) -> Result<Vec<u8>, SourceError> {
    use std::io::Write as _;
    let started = Instant::now();
    let stop_at = deadline.min(started + READ_TIMEOUT);
    let stdin = child.stdin.take();
    let (sent, received) = mpsc::channel();
    thread::spawn(move || {
        let ok = stdin.is_some_and(|mut pipe| pipe.write_all(&input).is_ok());
        let _ = sent.send(ok);
    });
    let out = finish(child, started, stop_at, false, Path::new("App child"))?.ordinary()?;
    match received.recv_timeout(stop_at.saturating_duration_since(Instant::now())) {
        Ok(true) => Ok(out),
        _ => Err(SourceError::Unavailable {
            detail: "App child input failed".to_owned(),
        }),
    }
}
// End T7 App runner.

/// The complete, single-line gh 2.100.0 diagnostic, with a plain ASCII
/// branch under the fleet adapter's existing branch grammar. Never trim.
fn no_checks(stderr: &[u8]) -> bool {
    std::str::from_utf8(stderr)
        .ok()
        .and_then(|s| s.strip_prefix("no checks reported on the '"))
        .and_then(|s| s.strip_suffix("' branch\n"))
        .is_some_and(crate::fleets::is_branch)
}

/// What a failed call shows: `gh error: HTTP <status> (detail withheld)`
/// when its first non-empty stderr line has an HTTP status as a word of its
/// own, otherwise `gh error (detail withheld)`, or `no error output`.
/// Nothing else of `gh`'s text, so no path, URL, token or terminal control.
fn diagnostic(stderr: &[u8]) -> String {
    let text = String::from_utf8_lossy(stderr);
    let Some(line) = text.lines().map(str::trim).find(|l| !l.is_empty()) else {
        return "no error output".to_owned();
    };
    match http_status(line) {
        Some(code) => format!("gh error: HTTP {code} (detail withheld)"),
        None => "gh error (detail withheld)".to_owned(),
    }
}

/// The first `HTTP <code>` in `line` that is a word of its own.
fn http_status(line: &str) -> Option<&str> {
    let bytes = line.as_bytes();
    line.match_indices("HTTP ").find_map(|(i, _)| {
        let code = line.get(i + 5..i + 8)?;
        let starts_word = i == 0 || !bytes[i - 1].is_ascii_alphanumeric();
        let ends_word = !bytes.get(i + 8).is_some_and(u8::is_ascii_digit);
        (starts_word && ends_word && is_status(code)).then_some(code)
    })
}

/// Three ASCII digits from 100 to 599.
fn is_status(code: &str) -> bool {
    let b = code.as_bytes();
    b.len() == 3 && (b'1'..=b'5').contains(&b[0]) && b[1..].iter().all(u8::is_ascii_digit)
}

/// Reads a pipe to its end, or to `limit + 1` bytes, on its own thread.
fn collect(
    pipe: Option<impl std::io::Read + Send + 'static>,
    limit: usize,
) -> Receiver<(Vec<u8>, bool)> {
    let (tx, rx) = mpsc::channel();
    thread::spawn(move || {
        let mut buf = Vec::new();
        let complete =
            pipe.is_some_and(|pipe| pipe.take(limit as u64 + 1).read_to_end(&mut buf).is_ok());
        let _ = tx.send((buf, complete));
    });
    rx
}

/// Kills the child and reaps it, so no process is left behind.
fn stop(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::PathBuf;
    use std::time::Duration;

    use super::*;

    const SH: &str = "/bin/sh";

    /// `sh -c <script> sh <args>`, run by the runner.
    fn sh(script: &str, args: &[&str], deadline: Instant) -> Result<Vec<u8>, SourceError> {
        let mut argv = vec!["-c", script, "sh"];
        argv.extend_from_slice(args);
        run(Path::new(SH), &Invocation::for_test(&argv), deadline)
    }

    fn soon() -> Instant {
        Instant::now() + Duration::from_secs(10)
    }

    /// A private directory for one test.
    fn scratch(test: &str) -> PathBuf {
        let dir = std::env::temp_dir()
            .join(format!("openwiz-github-process-{}", std::process::id()))
            .join(test);
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("scratch directory");
        dir
    }

    #[test]
    fn x2_fixture_caps_are_local_and_cannot_raise_the_default() {
        let cap = |executor: Executor| match executor.0 {
            Execution::Program(_, timeout) => timeout,
            Execution::Supplied(_) => unreachable!(),
        };
        for (requested, expected) in [
            (Duration::ZERO, Duration::ZERO),
            (Duration::from_millis(100), Duration::from_millis(100)),
            (Duration::from_secs(15), Duration::from_secs(15)),
            (Duration::from_secs(16), Duration::from_secs(15)),
            (Duration::MAX, Duration::from_secs(15)),
        ] {
            assert_eq!(
                cap(Executor::program_for_fixtures("/synthetic/gh", requested)),
                expected
            );
            assert_eq!(
                cap(Executor::program("/synthetic/gh")),
                Duration::from_secs(15)
            );
        }
    }

    #[test]
    fn x2_fixture_checks_preserve_the_no_checks_exception() {
        let program = plan_program(
            "fixture-checks",
            "printf \"no checks reported on the 'room/syn-2' branch\\n\" >&2; exit 1",
        );
        let executor = Executor::program_for_fixtures(program, Duration::from_secs(1));
        let call = Invocation::new(&["pr", "checks", "1902", "--json", "bucket,name"]).unwrap();
        assert_eq!(executor.checks(&call, soon()), Ok(b"[]".to_vec()));
        assert!(matches!(
            executor.run(&call, soon()),
            Err(SourceError::CommandFailed {
                exit_code: Some(1),
                ..
            })
        ));
        let version = Invocation::new(&["--version"]).unwrap();
        assert!(matches!(
            executor.checks(&version, soon()),
            Err(SourceError::Unavailable { .. })
        ));
    }

    #[test]
    fn x2_fixture_timeout_reaps_the_read_without_exhausting_the_run() {
        let dir = scratch("fixture-timeout");
        let pid_file = dir.join("pid");
        let program = plan_program(
            "fixture-timeout",
            &format!("echo $$ > '{}'; kill -STOP $$", pid_file.display()),
        );
        let deadline = Instant::now() + Duration::from_secs(3);
        let executor = Executor::program_for_fixtures(&program, Duration::from_millis(100));
        let call = Invocation::new(&["--version"]).unwrap();
        let got = executor.run(&call, deadline);
        assert!(matches!(got, Err(SourceError::TimedOut { .. })), "{got:?}");
        let pid = fs::read_to_string(&pid_file).expect("the child started");
        assert!(
            !Path::new("/proc").join(pid.trim()).exists(),
            "child must be reaped"
        );
        let next = plan_program("fixture-next", "printf 'synthetic-next'");
        assert_eq!(
            Executor::program(next).run(&call, deadline),
            Ok(b"synthetic-next".to_vec())
        );
    }

    #[test]
    fn a_call_that_succeeds_returns_exactly_its_stdout() {
        assert_eq!(
            sh("printf 'a\\n\\tb'; printf 'ignored' >&2", &[], soon()),
            Ok(b"a\n\tb".to_vec())
        );
    }

    #[test]
    fn the_call_gets_exactly_the_invocations_arguments() {
        let args = ["one two", "--json", "-x", "", "a'b\"c", "$HOME"];
        assert_eq!(
            sh("printf '%s|' \"$@\"", &args, soon()),
            Ok(b"one two|--json|-x||a'b\"c|$HOME|".to_vec())
        );
    }

    #[test]
    fn its_stdin_is_closed_so_it_can_never_wait_for_input() {
        assert_eq!(sh("cat", &[], soon()), Ok(Vec::new()));
    }

    #[test]
    fn a_failed_call_shows_only_its_exit_code_and_an_http_status() {
        for (stderr, detail) in [
            (
                "HTTP 404: Not Found (https://api.github.invalid/repos/someone/repo/issues/1)",
                "gh error: HTTP 404 (detail withheld)",
            ),
            (
                "gh: Not Found (HTTP 404)",
                "gh error: HTTP 404 (detail withheld)",
            ),
            (
                "\n  \nHTTP 502: Bad Gateway",
                "gh error: HTTP 502 (detail withheld)",
            ),
            (
                "GraphQL: Could not resolve to an Issue with the number of 1. (repository.issue)",
                "gh error (detail withheld)",
            ),
            (
                "token=synthetic-secret /synthetic/path",
                "gh error (detail withheld)",
            ),
            ("\u{1b}[31merror\u{1b}[0m", "gh error (detail withheld)"),
            ("HTTP 4040: not a status", "gh error (detail withheld)"),
            ("XHTTP 404", "gh error (detail withheld)"),
            ("HTTP 700", "gh error (detail withheld)"),
            ("", "no error output"),
        ] {
            assert_eq!(
                sh("printf '%s' \"$1\" >&2; exit 3", &[stderr], soon()),
                Err(SourceError::CommandFailed {
                    exit_code: Some(3),
                    detail: detail.to_owned(),
                }),
                "{stderr:?}"
            );
        }
    }

    #[test]
    fn the_ordinary_runner_still_refuses_the_exact_no_checks_error() {
        assert_eq!(
            sh(
                "printf '%s' \"$1\" >&2; exit 1",
                &["no checks reported on the 'room/syn-2' branch\n"],
                soon(),
            ),
            Err(SourceError::CommandFailed {
                exit_code: Some(1),
                detail: "gh error (detail withheld)".to_owned(),
            })
        );
    }

    #[test]
    fn the_checks_runner_refuses_other_reads_before_starting_anything() {
        for argv in [
            &["--version"][..],
            &["repo", "view", "--json", "nameWithOwner"],
            &[
                "pr",
                "view",
                "2",
                "--json",
                "comments",
                "--jq",
                "[.comments[].body]",
            ],
        ] {
            let invocation = Invocation::new(argv).expect("an allowlisted read");
            assert_eq!(
                run_checks(
                    Path::new("/synthetic/missing-gh"),
                    &invocation,
                    soon(),
                    READ_TIMEOUT
                ),
                Err(SourceError::Unavailable {
                    detail: "the checks runner accepts only the checks read".to_owned(),
                })
            );
        }
    }

    #[test]
    fn a_call_is_stopped_at_the_deadline_and_reaped() {
        let dir = scratch("deadline");
        let pid_file = dir.join("pid");
        // Long enough that `sh` has written its pid first; the result is
        // judged only by its kind, never by a measured time.
        let deadline = Instant::now() + Duration::from_secs(2);
        let script = "echo $$ > \"$1\"; exec sleep 30";
        let got = sh(script, &[pid_file.to_str().unwrap()], deadline);
        assert!(matches!(got, Err(SourceError::TimedOut { .. })), "{got:?}");
        let pid = fs::read_to_string(&pid_file).expect("the call started");
        assert!(
            !Path::new("/proc").join(pid.trim()).exists(),
            "the stopped call {pid} is still there"
        );
    }

    #[test]
    fn a_deadline_already_passed_starts_nothing() {
        let dir = scratch("passed");
        let marker = dir.join("started");
        let got = sh("touch \"$1\"", &[marker.to_str().unwrap()], Instant::now());
        assert_eq!(got, Err(SourceError::TimedOut { after_ms: 0 }));
        assert!(!marker.exists(), "the call was started");
    }

    #[test]
    fn too_much_output_is_malformed() {
        let script = "head -c 33554433 /dev/zero";
        let got = sh(script, &[], soon());
        assert!(matches!(got, Err(SourceError::Malformed { .. })), "{got:?}");
    }

    #[test]
    fn a_program_that_cannot_start_is_unavailable() {
        let invocation = Invocation::for_test(&["--version"]);
        let got = run(Path::new("/synthetic/no/gh"), &invocation, soon());
        assert!(
            matches!(got, Err(SourceError::Unavailable { .. })),
            "{got:?}"
        );
    }

    fn plan_call() -> Invocation {
        let argv = crate::plan::Request::Issues.argv(None);
        Invocation::new(&argv.iter().map(String::as_str).collect::<Vec<_>>()).unwrap()
    }

    fn plan_program(name: &str, script: &str) -> PathBuf {
        use std::os::unix::fs::PermissionsExt;
        let program = scratch(name).join("gh");
        // A concurrent spawn can inherit this process's writable files until
        // exec, even with CLOEXEC. Let a child own the writer and wait for its
        // exit so no other test's fork can keep the script busy (ETXTBSY).
        assert_eq!(
            sh(
                "umask 077; printf '#!/bin/sh\\n%s\\n' \"$2\" > \"$1\"",
                &[program.to_str().unwrap(), script],
                soon(),
            ),
            Ok(Vec::new()),
            "fixture writer failed"
        );
        fs::set_permissions(&program, fs::Permissions::from_mode(0o700)).unwrap();
        program
    }

    #[test]
    fn plan_programs_run_while_other_threads_create_and_spawn_fixtures() {
        let start = std::sync::Barrier::new(8);
        thread::scope(|scope| {
            for worker in 0..8 {
                let start = &start;
                scope.spawn(move || {
                    start.wait();
                    for attempt in 0..16 {
                        let program = plan_program(
                            &format!("plan-concurrent-{worker}-{attempt}"),
                            "printf 'synthetic\\n'",
                        );
                        let result = run_plan_graphql(&program, &plan_call(), soon())
                            .expect("a complete fixture can execute during concurrent spawns");
                        assert_eq!(result.stdout, b"synthetic\n");
                        assert_eq!(result.failure, None);
                        fs::remove_dir_all(program.parent().unwrap()).unwrap();
                    }
                });
            }
        });
    }

    #[test]
    fn plan_graphql_retains_error_stdout_and_sanitizes_failure_while_ordinary_run_refuses_it() {
        let program = plan_program(
            "plan-partial",
            r#"printf '%s' '{"data":{"repository":{"issues":null}},"errors":[{"message":"synthetic"}]}'; printf '%s' 'HTTP 403 synthetic-secret /synthetic/path' >&2; exit 1"#,
        );
        let result =
            run_plan_graphql(&program, &plan_call(), soon()).expect("bounded partial result");
        assert_eq!(
            result.stdout,
            br#"{"data":{"repository":{"issues":null}},"errors":[{"message":"synthetic"}]}"#
        );
        assert_eq!(
            result.failure,
            Some(SourceError::CommandFailed {
                exit_code: Some(1),
                detail: "gh error: HTTP 403 (detail withheld)".to_owned()
            })
        );
        assert!(matches!(
            run(&program, &plan_call(), soon()),
            Err(SourceError::CommandFailed {
                exit_code: Some(1),
                ..
            })
        ));
    }

    #[test]
    fn plan_graphql_never_applies_the_checks_empty_list_exception() {
        let program = plan_program(
            "plan-no-checks",
            "printf \"no checks reported on the 'room/syn-2' branch\\n\" >&2; exit 1",
        );
        let result = run_plan_graphql(&program, &plan_call(), soon()).unwrap();
        assert!(result.stdout.is_empty());
        assert!(matches!(
            result.failure,
            Some(SourceError::CommandFailed {
                exit_code: Some(1),
                ..
            })
        ));
        let call = Invocation::new(&["pr", "checks", "1902", "--json", "bucket,name"]).unwrap();
        assert_eq!(
            run_checks(&program, &call, soon(), READ_TIMEOUT),
            Ok(b"[]".to_vec())
        );
    }

    #[test]
    fn plan_graphql_keeps_empty_and_malformed_error_output_as_failures_for_the_parser() {
        for (name, script, expected) in [
            ("empty", "exit 1", &b""[..]),
            (
                "malformed",
                "printf '%s' 'not JSON'; exit 1",
                &b"not JSON"[..],
            ),
        ] {
            let program = plan_program(&format!("plan-{name}"), script);
            let result = run_plan_graphql(&program, &plan_call(), soon()).unwrap();
            assert_eq!(result.stdout, expected);
            assert!(matches!(
                result.failure,
                Some(SourceError::CommandFailed {
                    exit_code: Some(1),
                    ..
                })
            ));
        }
    }

    #[test]
    fn plan_graphql_refuses_other_invocations_before_starting_the_program() {
        let dir = scratch("plan-refused");
        let marker = dir.join("started");
        let program = plan_program("plan-refused", &format!("touch '{}'", marker.display()));
        let valid = plan_call();
        let mut altered = valid.argv().to_vec();
        altered.push("--paginate".to_owned());
        for call in [
            Invocation::new(&["--version"]).unwrap(),
            Invocation::new(&["pr", "checks", "1902", "--json", "bucket,name"]).unwrap(),
            Invocation::for_test(&altered.iter().map(String::as_str).collect::<Vec<_>>()),
        ] {
            let result = run_plan_graphql(&program, &call, soon());
            assert!(
                matches!(result,Err(SourceError::Unavailable{detail}) if detail=="the plan GraphQL runner accepts only exact plan reads")
            );
            assert!(!marker.exists());
        }
    }

    #[test]
    fn plan_graphql_rejects_oversized_error_stdout_before_exposing_it() {
        let program = plan_program("plan-oversized", "head -c 33554433 /dev/zero; exit 1");
        assert!(matches!(
            run_plan_graphql(&program, &plan_call(), soon()),
            Err(SourceError::Malformed { .. })
        ));
    }

    #[test]
    fn plan_graphql_deadlines_discard_partial_stdout_and_reap_the_child() {
        let dir = scratch("plan-deadline");
        let pid_file = dir.join("pid");
        let program = plan_program(
            "plan-deadline",
            &format!(
                "echo $$ > '{}'; printf '%s' '{{\"data\":null}}'; exec sleep 30",
                pid_file.display()
            ),
        );
        let got = run_plan_graphql(
            &program,
            &plan_call(),
            Instant::now() + Duration::from_secs(2),
        );
        assert!(matches!(got, Err(SourceError::TimedOut { .. })), "{got:?}");
        let pid = fs::read_to_string(pid_file).unwrap();
        assert!(!Path::new("/proc").join(pid.trim()).exists());
        let marker = dir.join("started");
        let program = plan_program("plan-past", &format!("touch '{}'", marker.display()));
        assert!(matches!(
            run_plan_graphql(&program, &plan_call(), Instant::now()),
            Err(SourceError::TimedOut { after_ms: 0 })
        ));
        assert!(!marker.exists());
    }
}
