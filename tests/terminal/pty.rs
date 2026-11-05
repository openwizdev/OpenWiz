//! CP3/CP4 pseudo-terminal proofs, with the real `openwiz` and
//! `openwiz-terminal` executables copied side by side into a private install
//! directory (Python's standard library drives the terminal): both entry
//! forms reach the same Home, resize keeps it readable, and quit, Ctrl-C and
//! a handled failure all restore the terminal. A controlled sibling proves
//! the fixed-sibling dispatch and its exit. No fixture variable exists.

use std::fs;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::OnceLock;
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::Value;

use super::dirs;
use super::support::{FixtureServer, ROOT};

/// `openwiz` and `openwiz-terminal`, built once from the workspace.
fn built() -> &'static (PathBuf, PathBuf) {
    static BUILT: OnceLock<(PathBuf, PathBuf)> = OnceLock::new();
    BUILT.get_or_init(|| {
        let target = Path::new(env!("CARGO_TARGET_TMPDIR")).parent().unwrap();
        let out = Command::new(env!("CARGO"))
            .args([
                "build",
                "--locked",
                "-p",
                "openwiz-cli",
                "-p",
                "openwiz-terminal",
                "--bins",
                "--target-dir",
            ])
            .arg(target)
            .current_dir(ROOT)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        (
            target.join("debug/openwiz"),
            target.join("debug/openwiz-terminal"),
        )
    })
}

/// Places the executable `src` at `dst`, owner-only. A separate `cp` process
/// writes it, so this process never holds a writable descriptor for it: a
/// child another test forks meanwhile would inherit one until its exec and
/// keep the file busy, so launching it would fail with ETXTBSY (#1754).
fn place(src: &Path, dst: &Path) {
    let out = Command::new("cp")
        .arg("--")
        .arg(src)
        .arg(dst)
        .output()
        .expect("cp runs");
    assert!(
        out.status.success(),
        "cp {}: {}",
        dst.display(),
        String::from_utf8_lossy(&out.stderr)
    );
    fs::set_permissions(dst, fs::Permissions::from_mode(0o700)).unwrap();
}

/// Places a script the same way, from a source file that never runs.
fn place_script(dst: &Path, text: &str) {
    let src = dst.with_extension("src");
    fs::write(&src, text).unwrap();
    place(&src, dst);
    fs::remove_file(&src).unwrap();
}

struct Install(PathBuf);

impl Install {
    /// A private directory with `openwiz` and, optionally, a sibling.
    fn new(sibling: Sibling) -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let dir = std::env::temp_dir().join(format!(
            "openwiz-t3-pty-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        dirs::private_dir(&dir).unwrap();
        let (cli, terminal) = built();
        place(cli, &dir.join("openwiz"));
        let sibling_path = dir.join("openwiz-terminal");
        match sibling {
            Sibling::Real => place(terminal, &sibling_path),
            Sibling::Recording(exit) => place_script(
                &sibling_path,
                &format!(
                    "#!/bin/sh\nt=''\n[ -t 0 ] && [ -t 1 ] && t=' tty'\n{{ printf 'args:'; for a in \"$@\"; do printf ' [%s]' \"$a\"; done; printf '%s\\n' \"$t\"; }} > \"$(dirname \"$0\")/sibling-ran\"\nprintf 'SIBLING-HOME\\n'\nexit {exit}\n"
                ),
            ),
            Sibling::Missing => {}
        }
        // A decoy on PATH that must never run.
        dirs::private_dir(dir.join("decoy")).unwrap();
        let decoy = dir.join("decoy/openwiz-terminal");
        place_script(&decoy, "#!/bin/sh\ntouch \"$(dirname \"$0\")/decoy-ran\"\n");
        Self(dir)
    }

    fn program(&self) -> PathBuf {
        self.0.join("openwiz")
    }
}

impl Drop for Install {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[derive(Clone, Copy)]
enum Sibling {
    Real,
    Recording(u8),
    Missing,
}

struct Run {
    exit: i64,
    steps: Vec<bool>,
    restored: bool,
    output: String,
}

fn drive(install: &Install, cols: u16, rows: u16, steps: Value, args: &[&str]) -> Run {
    let out = Command::new("python3")
        .arg("-I")
        .arg(Path::new(ROOT).join("tests/terminal/pty_drive.py"))
        .arg(cols.to_string())
        .arg(rows.to_string())
        .arg(steps.to_string())
        .arg(install.program())
        .args(args)
        .env_clear()
        .env(
            "PATH",
            format!("{}:/usr/bin:/bin", install.0.join("decoy").display()),
        )
        .env("HOME", &install.0)
        .env("TERM", "xterm-256color")
        .env("LANG", "C.UTF-8")
        .env("COLORTERM", "truecolor")
        .output()
        .expect("python3 runs the pty driver");
    assert!(
        out.status.success(),
        "driver incomplete: {}\n{}",
        String::from_utf8_lossy(&out.stderr),
        String::from_utf8_lossy(&out.stdout)
    );
    let report: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(report["incomplete"], false, "{report}");
    let output = report["output"].as_str().unwrap();
    let bytes = base64(output);
    assert!(
        !install.0.join("decoy/decoy-ran").exists(),
        "PATH was searched"
    );
    Run {
        exit: report["exit"].as_i64().unwrap(),
        steps: report["steps"]
            .as_array()
            .unwrap()
            .iter()
            .map(|s| s.as_bool().unwrap())
            .collect(),
        restored: report["restored"].as_bool().unwrap(),
        output: String::from_utf8_lossy(&bytes).into_owned(),
    }
}

/// A small standard base64 decoder (no new dependency).
fn base64(text: &str) -> Vec<u8> {
    let value = |c: u8| match c {
        b'A'..=b'Z' => c - b'A',
        b'a'..=b'z' => c - b'a' + 26,
        b'0'..=b'9' => c - b'0' + 52,
        b'+' => 62,
        _ => 63,
    };
    let clean: Vec<u8> = text.bytes().filter(|&c| c != b'=').collect();
    let mut out = Vec::new();
    for chunk in clean.chunks(4) {
        let n = chunk.iter().enumerate().fold(0u32, |acc, (i, &c)| {
            acc | (u32::from(value(c)) << (18 - 6 * i))
        });
        for i in 0..chunk.len().saturating_sub(1) {
            out.push((n >> (16 - 8 * i)) as u8);
        }
    }
    out
}

const ENTER_ALT: &str = "\u{1b}[?1049h";
const LEAVE_ALT: &str = "\u{1b}[?1049l";
const SHOW_CURSOR: &str = "\u{1b}[?25h";
const PASTE_ON: &str = "\u{1b}[?2004h";
const PASTE_OFF: &str = "\u{1b}[?2004l";

fn assert_restored(run: &Run, what: &str) {
    assert!(run.restored, "{what}: terminal attributes not restored");
    let enter = run
        .output
        .find(ENTER_ALT)
        .expect("entered the alternate screen");
    let leave = run
        .output
        .rfind(LEAVE_ALT)
        .expect("left the alternate screen");
    assert!(enter < leave, "{what}");
    // Bracketed paste was on while the app ran, and is off again.
    let on = run.output.find(PASTE_ON).expect("bracketed paste enabled");
    let off = run
        .output
        .rfind(PASTE_OFF)
        .expect("bracketed paste disabled");
    assert!(on < off, "{what}: bracketed paste restored");
    assert!(
        run.output.rfind(SHOW_CURSOR).unwrap() > enter,
        "{what}: cursor shown"
    );
}

#[test]
fn ui_and_interactive_no_argument_launch_reach_the_same_home() {
    let server = FixtureServer::home();
    let install = Install::new(Sibling::Real);
    let port = server.port.to_string();
    let run = drive(
        &install,
        120,
        40,
        serde_json::json!([
            {"wait": "Synthetic fleet spec", "body": true},
            {"wait": "Needs you", "body": true},
            {"send": "s"},
            {"wait": "Sessions", "body": true},
            {"wait": "Synthetic idle session", "body": true},
            {"send": "\u{1b}[B\r"},
            {"wait": "thr_syn_0301", "body": true},
            {"wait": "Synthetic final line one.", "body": true},
            {"send": "\u{1b}"},
            {"wait": "Sessions", "body": true},
            {"send": "f"},
            {"wait": "Fleets", "body": true},
            {"wait": "Synthetic fleet spec", "body": true},
            {"resize": [40, 10]},
            {"wait": "Fleets", "body": true},
            {"send": "h"},
            {"wait": "Needs you", "body": true},
            {"send": "q"}
        ]),
        &["ui", "--port", &port],
    );
    assert_eq!(run.steps, [true; 18], "{}", run.output);
    assert_eq!(run.exit, 0);
    assert_restored(&run, "ui then q");
    assert!(server.writes().is_empty());
    let mut paths = server.paths();
    paths.sort();
    paths.dedup();
    assert_eq!(
        paths,
        [
            "/api/v1/decisions",
            "/api/v1/fleets",
            "/api/v1/inventory",
            "/api/v1/sessions/thr_syn_0301"
        ]
    );

    // No arguments: the same Home, on the default port's server (none here
    // is assumed): its navigation and Needs you section, then quit.
    let run = drive(
        &install,
        80,
        24,
        serde_json::json!([
            {"wait": "Needs you", "body": true},
            {"wait": "Sessions"},
            {"wait": "127.0.0.1:7370"},
            {"send": "q"}
        ]),
        &[],
    );
    assert_eq!(run.steps, [true; 4], "{}", run.output);
    assert_eq!(run.exit, 0);
    assert_restored(&run, "no arguments then q");
}

#[test]
fn ctrl_c_and_a_handled_failure_restore_the_terminal() {
    let server = FixtureServer::home();
    let install = Install::new(Sibling::Real);
    let port = server.port.to_string();
    let run = drive(
        &install,
        80,
        24,
        serde_json::json!([{"wait": "Needs you"}, {"send": "\u{3}"}]),
        &["ui", "--port", &port],
    );
    assert_eq!(run.steps, [true, true], "{}", run.output);
    assert_eq!(run.exit, 0);
    assert_restored(&run, "Ctrl-C");
    // A terminal that reports no size cannot be drawn: exit 1, restored.
    let run = drive(
        &install,
        0,
        0,
        serde_json::json!([{"sleep": 1.0}]),
        &["ui", "--port", &port],
    );
    assert_eq!(run.exit, 1, "{}", run.output);
    assert_restored(&run, "handled failure");
    assert!(
        run.output.contains("the terminal reports no size"),
        "{}",
        run.output
    );
    assert!(server.writes().is_empty());
}

#[test]
fn dispatch_runs_only_the_fixed_sibling_with_parsed_settings_and_keeps_its_exit() {
    let install = Install::new(Sibling::Recording(7));
    let run = drive(
        &install,
        80,
        24,
        serde_json::json!([{"wait": "SIBLING-HOME"}]),
        &["ui", "--port=7371", "--allowed-host", "openwiz.example"],
    );
    assert_eq!(run.exit, 7, "the sibling's exit is preserved");
    let ran = fs::read_to_string(install.0.join("sibling-ran")).unwrap();
    assert_eq!(
        ran,
        "args: [--port] [7371] [--allowed-host] [openwiz.example] tty\n"
    );
    fs::remove_file(install.0.join("sibling-ran")).unwrap();
    let run = drive(
        &install,
        80,
        24,
        serde_json::json!([{"wait": "SIBLING-HOME"}]),
        &[],
    );
    assert_eq!(run.exit, 7);
    assert_eq!(
        fs::read_to_string(install.0.join("sibling-ran")).unwrap(),
        "args: tty\n",
        "no arguments forwards nothing"
    );
    // Without a sibling: an explicit unavailable error, no fallback.
    let missing = Install::new(Sibling::Missing);
    let run = drive(
        &missing,
        80,
        24,
        serde_json::json!([{"sleep": 0.3}]),
        &["ui"],
    );
    assert_eq!(run.exit, 1);
    assert!(
        run.output.contains("is not installed beside openwiz"),
        "{}",
        run.output
    );
    // A refused setting never launches anything.
    let run = drive(
        &install,
        80,
        24,
        serde_json::json!([{"sleep": 0.3}]),
        &["ui", "--port", "0"],
    );
    assert_eq!(run.exit, 2);
    assert!(
        !install.0.join("sibling-ran").exists() || {
            // The earlier run's record was read above; nothing new was written.
            fs::read_to_string(install.0.join("sibling-ran")).unwrap() == "args: tty\n"
        }
    );
}

#[test]
fn explicit_and_json_requests_never_launch_in_a_terminal() {
    let install = Install::new(Sibling::Recording(0));
    for args in [
        vec!["ui", "--json"],
        vec!["ui", "--help"],
        vec!["help", "--agent"],
        vec!["--json"],
    ] {
        let run = drive(&install, 80, 24, serde_json::json!([{"sleep": 0.3}]), &args);
        assert!(!install.0.join("sibling-ran").exists(), "{args:?} launched");
        assert!(
            !run.output.contains(ENTER_ALT),
            "{args:?} entered the screen"
        );
        assert!(run.restored);
    }
    let run = drive(
        &install,
        80,
        24,
        serde_json::json!([{"sleep": 0.3}]),
        &["ui", "--json"],
    );
    let line = run.output.lines().next().unwrap().trim_end_matches('\r');
    let doc: Value = serde_json::from_str(line).unwrap();
    // The installed app's registered actions, in registry order.
    let implemented: Vec<&str> = openwiz_terminal::actions::registry()
        .into_iter()
        .filter(|(_, action)| action.is_some())
        .map(|(id, _)| id.capability())
        .collect();
    assert_eq!(
        doc,
        serde_json::json!({"schema":"openwiz.terminal-capability.v1","available":true,"executable":"openwiz-terminal","transport":"loopback-http","actions":implemented,"reason":null})
    );
}

/// Descriptors of this process open for writing on `path`'s file.
#[cfg(target_os = "linux")]
fn writers(path: &Path) -> usize {
    use std::os::unix::fs::MetadataExt;
    let target = fs::metadata(path).unwrap();
    fs::read_dir("/proc/self/fd")
        .unwrap()
        .filter_map(|fd| {
            let fd = fd.ok()?.file_name();
            let file = fs::metadata(Path::new("/proc/self/fd").join(&fd)).ok()?;
            let info = fs::read_to_string(Path::new("/proc/self/fdinfo").join(&fd)).ok()?;
            let flags = info.lines().find_map(|l| l.strip_prefix("flags:"))?;
            let access = u32::from_str_radix(flags.trim(), 8).unwrap() & 3;
            (file.dev() == target.dev() && file.ino() == target.ino() && access != 0).then_some(())
        })
        .count()
}

/// #1754: a child another test forks while an executable is being placed
/// inherits every descriptor this process holds at that moment, until it
/// execs. A writable one keeps the placed file busy, so launching it fails
/// with ETXTBSY (errno 26). The copy is held mid-way on a FIFO, where this
/// process must hold no writer for it; then the placed program launches.
#[cfg(target_os = "linux")]
#[test]
fn placing_an_executable_leaves_no_writer_a_concurrent_fork_could_inherit() {
    let install = Install::new(Sibling::Missing);
    let program = install.program();
    fs::remove_file(&program).unwrap();
    let fifo = install.0.join("source.fifo");
    assert!(
        Command::new("mkfifo")
            .arg(&fifo)
            .status()
            .unwrap()
            .success()
    );
    let placing = {
        let (fifo, program) = (fifo.clone(), program.clone());
        thread::spawn(move || place(&fifo, &program))
    };
    // Opening returns once the copy's reader has the FIFO open.
    let mut source = fs::OpenOptions::new().write(true).open(&fifo).unwrap();
    let head = b"#!/bin/sh\n";
    source.write_all(head).unwrap();
    // Once the first bytes have landed, the placed file's writer is open.
    let deadline = Instant::now() + Duration::from_secs(10);
    while fs::metadata(&program).map_or(true, |m| m.len() < head.len() as u64) {
        assert!(Instant::now() < deadline, "the copy never started");
        thread::sleep(Duration::from_millis(10));
    }
    let held = writers(&program);
    source.write_all(b"printf 'PLACED\\n'\n").unwrap();
    drop(source);
    placing.join().unwrap();
    assert_eq!(
        held, 0,
        "mid-copy, this process held a writable descriptor for the placed \
         executable: a child forked then keeps it busy (ETXTBSY)"
    );
    let run = drive(
        &install,
        80,
        24,
        serde_json::json!([{"wait": "PLACED"}]),
        &[],
    );
    assert_eq!(run.steps, [true], "{}", run.output);
    assert_eq!(run.exit, 0);
}

/// Harness regressions use synthetic children only, including a 1 MiB quit.
#[test]
fn driver_fixture_regressions() {
    let out = Command::new("python3")
        .args(["-B", "-I"])
        .arg(Path::new(ROOT).join("tests/terminal/test_pty_drive.py"))
        .arg("-v")
        .output()
        .expect("python3 runs the driver fixture proofs");
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
}
