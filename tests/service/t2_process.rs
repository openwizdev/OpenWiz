//! Verified bundle calls through the same CLI/server dispatch as production.
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::OnceLock;

use super::{Fixture, TAIL};

pub(super) fn fixture_binary(name: &str) -> PathBuf {
    static BUILT: OnceLock<()> = OnceLock::new();
    BUILT.get_or_init(|| {
        let out = Command::new(env!("CARGO"))
            .args(["build", "-p", "openwiz-tests", "--examples"])
            .current_dir(Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap())
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
    });
    Path::new(env!("CARGO_TARGET_TMPDIR"))
        .parent()
        .unwrap()
        .join("debug/examples")
        .join(name)
}

pub(super) fn executable(path: &Path, script: &str) {
    place_script(path, script);
    fs::set_permissions(path, fs::Permissions::from_mode(0o755)).unwrap();
}

#[allow(dead_code)]
#[path = "../support/schema.rs"]
mod cli_schema;

fn assert_discovery_error(stdout: &[u8], private_roots: &[&Path]) {
    assert!(stdout.ends_with(b"\n"));
    let doc: serde_json::Value =
        serde_json::from_slice(stdout).expect("exactly one complete CLI error document");
    let schema: serde_json::Value =
        serde_json::from_str(include_str!("../../contracts/cli.v1.schema.json")).unwrap();
    assert_eq!(
        cli_schema::validate(&schema, &doc),
        Vec::<String>::new(),
        "{doc}"
    );
    assert_eq!(doc["schema"], "openwiz.cli-error.v1");
    assert_eq!(doc["command"], "ls");
    assert_eq!(doc["exit_code"], 1);
    assert_eq!(doc["error"]["kind"], "read_failed");
    let decoded = doc.to_string();
    for root in private_roots {
        assert!(
            !decoded.contains(root.to_str().unwrap()),
            "private path leaked into JSON"
        );
    }
}

// Red run 8 (2026-11-01): selecting this test exited 101. The CLI ignored
// its injected verified bundle and executed the PATH trap: "thread list
// exited 97: no error output". The same dispatch is used by production.
#[test]
fn t2_cli_uses_only_the_verified_bundle_and_never_the_path_decoy() {
    let f = Fixture::new();
    let candidate = f.file(format!(".mount_synthetic/{TAIL}"));
    let calls = f.0.join("bundle-calls");
    executable(
        &candidate,
        &format!(
            "#!/bin/sh\n\":\" //; printf '%s\\n' \"$*\" >> '{}'\nif [ \"$1\" = --version ]; then printf 'v141\\n'; else printf '[]\\n'; fi\n",
            calls.display()
        ),
    );
    f.running(".mount_synthetic", "101");
    let stale = f.file(format!(".mount_synthetic_stale/{TAIL}"));
    let stale_calls = f.0.join("stale-called");
    executable(
        &stale,
        &format!(
            "#!/bin/sh\n\":\" //; printf stale > '{}'\nexit 97\n",
            stale_calls.display()
        ),
    );
    let trap = Fixture::new();
    let trap_calls = trap.0.join("path-was-searched");
    executable(
        &trap.0.join("room-cli"),
        &format!(
            "#!/bin/sh\nprintf trap > '{}'\nexit 97\n",
            trap_calls.display()
        ),
    );
    let wrapper = trap.file(".local/bin/room-cli");
    let wrapper_calls = trap.0.join("wrapper-called");
    executable(
        &wrapper,
        &format!(
            "#!/bin/sh\nprintf wrapper > '{}'\nexit 97\n",
            wrapper_calls.display()
        ),
    );
    let out = Command::new(fixture_binary("openwiz"))
        .args(["ls", "--json"])
        .env("OPENWIZ_FIXTURE_ROOT", &f.0)
        .env("PATH", &trap.0)
        .env("ROOM_CLI_PATH", &wrapper)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(!trap_calls.exists(), "PATH decoy ran");
    assert!(!wrapper_calls.exists(), "stable wrapper decoy ran");
    assert!(!stale_calls.exists(), "stale bundle ran");
    let mut calls: Vec<_> = fs::read_to_string(calls)
        .unwrap()
        .lines()
        .map(str::to_owned)
        .collect();
    calls.sort();
    assert_eq!(
        calls,
        [
            "--version",
            "machine list --json",
            "project list --json --include-personal",
            "thread list --json"
        ]
    );
    let json: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(json["source"]["version"]["known"], "v141");
    assert_eq!(json["source"]["version_tested"], false);
}

#[test]
fn t2_missing_ambiguous_and_wrong_launchers_run_nothing() {
    for state in [
        "missing",
        "not-running",
        "ambiguous",
        "wrong-prefix",
        "writable",
        "symlink",
    ] {
        let f = Fixture::new();
        f.process_root();
        let calls = f.0.join("unexpected-call");
        let script = format!(
            "#!/bin/sh\n\":\" //; printf called > '{}'\nexit 97\n",
            calls.display()
        );
        if state != "missing" {
            let candidate = f.file(format!(".mount_synthetic/{TAIL}"));
            executable(&candidate, &script);
            if state != "not-running" {
                f.running(".mount_synthetic", "101");
            }
            match state {
                "ambiguous" => {
                    let second = f.file(format!(".mount_synthetic_two/{TAIL}"));
                    executable(&second, &script);
                    f.running(".mount_synthetic_two", "102");
                }
                "wrong-prefix" => {
                    executable(&candidate, &script.replacen("#!/bin/sh", "#!/bin/bash", 1))
                }
                "writable" => {
                    fs::set_permissions(&candidate, fs::Permissions::from_mode(0o777)).unwrap()
                }
                "symlink" => {
                    let target = f.0.join("target");
                    fs::rename(&candidate, &target).unwrap();
                    std::os::unix::fs::symlink(target, candidate).unwrap();
                }
                "not-running" => {}
                _ => unreachable!(),
            }
        }
        let trap = Fixture::new();
        executable(&trap.0.join("room-cli"), &script);
        let out = Command::new(fixture_binary("openwiz"))
            .args(["ls", "--json"])
            .env("OPENWIZ_FIXTURE_ROOT", &f.0)
            .env("PATH", &trap.0)
            .output()
            .unwrap();
        assert_eq!(out.status.code(), Some(1), "{state}");
        assert_discovery_error(&out.stdout, &[&f.0, &trap.0]);
        let error = String::from_utf8(out.stderr).unwrap();
        if state == "not-running" {
            assert!(error.contains("(no running app identified)"), "{error}");
        } else if state == "missing" {
            assert!(error.contains("(no bundled launcher)"), "{error}");
        }
        assert!(error.contains("CloudRoom not running"), "{state}: {error}");
        assert!(error.contains("could not be started"), "{state}: {error}");
        assert!(
            !error.contains(f.0.to_str().unwrap()),
            "private path leaked"
        );
        assert!(!calls.exists(), "{state} executed a candidate or PATH trap");
    }
}

#[test]
fn t2_fixed_mac_location_uses_the_same_verification_without_a_search() {
    use openwiz_adapter_cloudroom::locate::{Discovery, LauncherMetadata, LocateError};
    use std::os::unix::fs::MetadataExt;
    let f = Fixture::new();
    let candidate = f.file("Cloudroom.app/Contents/Resources/app.asar.unpacked/node_modules/bb-app/host-daemon/dist/room-cli");
    executable(&candidate, "#!/bin/sh\n\":\" //; exit 0\n");
    let discovery = Discovery::fixed(candidate.clone(), |m| LauncherMetadata {
        uid: 0,
        mode: m.mode(),
    });
    assert_eq!(discovery.resolve(), Ok(candidate.clone()));
    fs::remove_file(candidate).unwrap();
    assert_eq!(discovery.resolve(), Err(LocateError::Unreadable));
}

// Red run 11 (2026-11-01): selecting this test exited 101. The fixed Mac
// launcher was rejected as UnexpectedFile when its synthetic app and file
// were both owned by the installing user; the PC-only root rule had leaked.
#[test]
fn t2_fixed_mac_launcher_is_owned_by_its_app_installer() {
    use openwiz_adapter_cloudroom::locate::{Discovery, LauncherMetadata, LocateError};
    use std::os::unix::fs::MetadataExt;
    let f = Fixture::new();
    let candidate = f.file("Cloudroom.app/Contents/Resources/app.asar.unpacked/node_modules/bb-app/host-daemon/dist/room-cli");
    executable(&candidate, "#!/bin/sh\n\":\" //; exit 0\n");
    // The Mac's fixed app may be installed by its user; it is not an
    // AppImage mount. These owners are fixture facts, never live metadata.
    let installed_by_user = Discovery::fixed(candidate.clone(), |m| LauncherMetadata {
        uid: 1000,
        mode: m.mode(),
    });
    assert_eq!(installed_by_user.resolve(), Ok(candidate.clone()));
    let changed_owner = Discovery::fixed(candidate, |m| LauncherMetadata {
        uid: if m.is_dir() { 1000 } else { 1001 },
        mode: m.mode(),
    });
    assert_eq!(changed_owner.resolve(), Err(LocateError::UnexpectedFile));
}

#[test]
fn t2_discovery_errors_are_typed_and_relative_programs_are_refused() {
    use openwiz_adapter_cloudroom::locate::{LocateError, program};
    use openwiz_core::source::SourceError;
    for error in [
        LocateError::NotRunning,
        LocateError::NoRunningApp,
        LocateError::Ambiguous,
        LocateError::UnexpectedFile,
        LocateError::Unreadable,
    ] {
        assert!(
            matches!(SourceError::from(error), SourceError::Unavailable { detail } if detail.contains("CloudRoom not running") && detail.contains("could not be started"))
        );
    }
    assert!(matches!(
        program(Path::new("untrusted-relative-program")),
        Err(SourceError::Unavailable { .. })
    ));
}

// Red run 9 (2026-11-01): selecting this test exited 101. A relative
// discovery root reached filesystem lookup (NotRunning) rather than being
// refused as UnexpectedFile before a basename could reach Command.
#[test]
fn t2_discovery_refuses_relative_roots_before_any_file_lookup() {
    use openwiz_adapter_cloudroom::locate::{Discovery, LauncherMetadata, LocateError};
    let metadata: fn(&fs::Metadata) -> LauncherMetadata = |_| LauncherMetadata {
        uid: 0,
        mode: 0o755,
    };
    for discovery in [
        Discovery::pc(PathBuf::from("relative"), metadata),
        Discovery::fixed(PathBuf::from("room-cli"), metadata),
    ] {
        assert_eq!(discovery.resolve(), Err(LocateError::UnexpectedFile));
    }
    let f = Fixture::new();
    assert_eq!(
        f.discovery()
            .with_process_root(PathBuf::from("relative"))
            .resolve(),
        Err(LocateError::UnexpectedFile)
    );
}

#[test]
fn t2_running_server_resolves_again_after_the_app_mount_changes() {
    use std::io::{BufRead, BufReader, Read, Write};
    use std::net::{SocketAddr, TcpStream};
    use std::process::{Child, Stdio};
    use std::sync::mpsc;
    use std::time::Duration;

    struct Server(Child);
    impl Drop for Server {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    let f = Fixture::new();
    let candidate = f.file(format!(".mount_synthetic/{TAIL}"));
    let script = |version: &str| {
        format!(
            "#!/bin/sh\n\":\" //; if [ \"$1\" = --version ]; then printf '{version}\\n'; else printf '[]\\n'; fi\n"
        )
    };
    executable(&candidate, &script("0.43.1"));
    f.running(".mount_synthetic", "101");
    let child = Command::new(fixture_binary("openwiz-server"))
        .args(["--port", "0"])
        .env("OPENWIZ_FIXTURE_ROOT", &f.0)
        .env_remove(openwiz_server::ALLOWED_HOST_ENV)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let mut server = Server(child);
    let stderr = server.0.stderr.take().unwrap();
    let (tx, rx) = mpsc::channel();
    let reader = std::thread::spawn(move || {
        let mut stderr = BufReader::new(stderr);
        let mut first = String::new();
        stderr.read_line(&mut first).unwrap();
        tx.send(first).unwrap();
        let mut rest = String::new();
        stderr.read_to_string(&mut rest).unwrap();
    });
    let first = rx.recv_timeout(Duration::from_secs(10)).unwrap();
    let address: SocketAddr = first
        .trim()
        .strip_prefix("openwiz-server: listening on http://")
        .and_then(|s| s.split(' ').next())
        .unwrap()
        .parse()
        .unwrap();
    let get = |path: &str| {
        let mut stream = TcpStream::connect(address).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(10)))
            .unwrap();
        write!(
            stream,
            "GET {path} HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n"
        )
        .unwrap();
        let mut response = String::new();
        stream.read_to_string(&mut response).unwrap();
        let (headers, body) = response.split_once("\r\n\r\n").unwrap();
        let status: u16 = headers.split_whitespace().nth(1).unwrap().parse().unwrap();
        (
            status,
            serde_json::from_str::<serde_json::Value>(body).unwrap(),
        )
    };
    let (status, first) = get("/api/v1/inventory");
    assert_eq!(status, 200);
    assert_eq!(first["source"]["version"]["known"], "0.43.1");
    // Restart into a new mount while the old, still-valid mount remains.
    let second = f.file(format!(".mount_synthetic_second/{TAIL}"));
    executable(&second, &script("0.44.0"));
    fs::remove_dir_all(f.process_root().join("101")).unwrap();
    f.running(".mount_synthetic_second", "102");
    let (status, second) = get("/api/v1/inventory?hidden=1");
    assert_eq!(status, 200);
    assert_eq!(second["source"]["version"]["known"], "0.44.0");
    fs::remove_dir_all(f.process_root().join("102")).unwrap();
    assert_eq!(get("/api/v1/inventory?archived=1").0, 502);
    drop(server);
    reader.join().unwrap();
}

#[test]
fn t2_production_entrypoints_keep_system_discovery_and_ignore_fixture_settings() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
    let wired = |source: &str| {
        source
            .split("fn main() -> ExitCode {")
            .nth(1)
            .and_then(|s| s.split("\n}").next())
            .map(|body| body.split_whitespace().collect::<String>())
            == Some("dispatch(openwiz_adapter_cloudroom::locate::Discovery::system())".to_owned())
    };
    for source in ["crates/cli/src/main.rs", "crates/server/src/main.rs"] {
        let source = fs::read_to_string(root.join(source)).unwrap();
        assert!(wired(&source));
        assert!(!source.contains("OPENWIZ_FIXTURE"));
        assert!(
            !wired(&source.replacen(
                "Discovery::system()",
                "Discovery::pc(private_root, synthetic_metadata)",
                1
            )),
            "tripwire missed a fixture-wired production entrypoint"
        );
    }
    let locator = fs::read_to_string(root.join("crates/adapters/cloudroom/src/locate.rs")).unwrap();
    assert!(!locator.contains("std::env::"));
    assert!(!locator.contains("env!("));
}

// Red run 10 (2026-11-01): selecting this test exited 101. The unavailable
// error included the absolute private fixture path before "could not be
// started". A resolved bundle path must not become an output diagnostic.
#[test]
fn t2_a_spawn_failure_never_discloses_the_resolved_program_path() {
    use openwiz_adapter_cloudroom::source::CloudRoomSource;
    use openwiz_core::messaging::OpId;
    use openwiz_core::new_thread::operation::{NewThreadClient, SpawnRequest};
    use openwiz_core::new_thread::{outcome::SpawnReply, request_id};
    use openwiz_core::prompt::ReadyPrompt;
    use openwiz_core::source::{SessionSource, SourceError};
    use std::time::{Duration, Instant};
    let f = Fixture::new();
    let source = CloudRoomSource::new(f.0.join("missing-resolved-launcher"));
    let error =
        SessionSource::version(&source, Instant::now() + Duration::from_secs(1)).unwrap_err();
    assert!(
        matches!(&error, SourceError::Unavailable { detail } if detail.contains("could not be started"))
    );
    assert!(
        !error.to_string().contains(f.0.to_str().unwrap()),
        "{error}"
    );
    let request = SpawnRequest {
        project_id: "prj_syn_0001".to_owned(),
        provider: "codex".to_owned(),
        model: "syn-codex-model-01".to_owned(),
        effort: "high".to_owned(),
        request_id: request_id(&OpId::parse("op-synthetic-launch-failure").unwrap()),
        prompt: ReadyPrompt::text("Synthetic prompt"),
    };
    assert!(openwiz_adapter_cloudroom::new_thread::spawn_argv(&request).is_ok());
    assert_eq!(
        source.spawn(&request, Instant::now() + Duration::from_secs(1)),
        SpawnReply::NotStarted
    );
}

// R2 red run (2026-11-01): selecting this test exited 101. A genuine
// bundle plus a regular .mount_otherapp file returned UnexpectedFile
// instead of the genuine candidate. No unrelated entry may hide it.
#[test]
fn t2_unrelated_mount_entries_do_not_hide_a_genuine_bundle() {
    use openwiz_adapter_cloudroom::locate::pc_bundle_candidate;
    for kind in ["file", "symlink", "unsearchable"] {
        let f = Fixture::new();
        let candidate = f.file(format!(".mount_synthetic/{TAIL}"));
        let unrelated = f.0.join(".mount_otherapp");
        struct Restore(PathBuf);
        impl Drop for Restore {
            fn drop(&mut self) {
                let _ = fs::set_permissions(&self.0, fs::Permissions::from_mode(0o700));
            }
        }
        let mut restore = None;
        match kind {
            "file" => fs::write(&unrelated, "synthetic lock file").unwrap(),
            "symlink" => {
                std::os::unix::fs::symlink(f.0.join(".mount_synthetic"), &unrelated).unwrap()
            }
            "unsearchable" => {
                super::dirs::private_dir(&unrelated).unwrap();
                restore = Some(Restore(unrelated.clone()));
                fs::set_permissions(&unrelated, fs::Permissions::from_mode(0o000)).unwrap();
                assert_eq!(
                    fs::symlink_metadata(unrelated.join("resources"))
                        .unwrap_err()
                        .kind(),
                    std::io::ErrorKind::PermissionDenied,
                    "this fixture requires an unprivileged test process"
                );
            }
            _ => unreachable!(),
        }
        assert_eq!(pc_bundle_candidate(&f.0), Ok(candidate), "{kind}");
        drop(restore);
    }
}

#[test]
fn t2_cli_reads_the_genuine_bundle_beside_other_appimage_entries() {
    for kind in ["file", "unsearchable"] {
        let f = Fixture::new();
        let candidate = f.file(format!(".mount_synthetic/{TAIL}"));
        executable(
            &candidate,
            "#!/bin/sh\n\":\" //; if [ \"$1\" = --version ]; then printf '0.43.1\\n'; else printf '[]\\n'; fi\n",
        );
        f.running(".mount_synthetic", "101");
        let other = f.0.join(".mount_otherapp");
        struct Restore(PathBuf);
        impl Drop for Restore {
            fn drop(&mut self) {
                let _ = fs::set_permissions(&self.0, fs::Permissions::from_mode(0o700));
            }
        }
        let restore = if kind == "unsearchable" {
            super::dirs::private_dir(&other).unwrap();
            fs::set_permissions(&other, fs::Permissions::from_mode(0o000)).unwrap();
            Some(Restore(other))
        } else {
            fs::write(other, "synthetic lock file").unwrap();
            None
        };
        let out = Command::new(fixture_binary("openwiz"))
            .args(["ls", "--json"])
            .env("OPENWIZ_FIXTURE_ROOT", &f.0)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{kind}: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&out.stdout).unwrap()["source"]["version"]
                ["known"],
            "0.43.1"
        );
        drop(restore);
    }
}

// #1669: expected sizes come from the approved 32 MiB limit, independently
// of the implementation constant. The executable writes bounded chunks.
#[test]
fn ta3_stdout_accepts_the_full_read_limit_and_rejects_one_extra_byte() {
    use openwiz_adapter_cloudroom::source::CloudRoomSource;
    use openwiz_core::source::SessionSource;
    use openwiz_core::source::SourceError;
    use std::time::{Duration, Instant};
    for size in [64, 2_097_152, 33_554_432, 33_554_433] {
        let f = Fixture::new();
        let program = f.0.join("synthetic-output");
        executable(
            &program,
            &format!(
                r#"#!/usr/bin/python3
import os
os.write(1, b'{{"output":"')
remaining = {size} - 26
while remaining:
    written = os.write(1, b'x' * min(remaining, 65536))
    remaining -= written
os.write(1, b'","error":null}}')
"#
            ),
        );
        let result = CloudRoomSource::new(program).session_output(
            &openwiz_core::model::SessionId("thr_syn_0001".to_owned()),
            Instant::now() + Duration::from_secs(10),
        );
        if size == 33_554_433 {
            assert_eq!(
                result,
                Err(SourceError::Malformed {
                    detail: "printed more than 33554432 bytes".to_owned(),
                })
            );
        } else {
            let record = result.unwrap();
            assert_eq!(
                record.output,
                openwiz_core::model::Fact::Known(Some("x".repeat(size - 26)))
            );
            assert_eq!(record.error, openwiz_core::model::Fact::Known(None));
            assert!(record.problems.is_empty());
        }
    }
}

#[test]
fn ta3_stderr_retains_a_safe_line_after_blank_output_but_stays_bounded() {
    use openwiz_adapter_cloudroom::source::CloudRoomSource;
    use openwiz_core::source::SessionSource;
    use openwiz_core::source::SourceError;
    use std::time::{Duration, Instant};
    for (blank_bytes, expected) in [
        (0, "Error: HTTP 503: Busy"),
        (2048, "Error: HTTP 503: Busy"),
        (131_072, "no error output"),
    ] {
        let f = Fixture::new();
        let program = f.0.join("synthetic-error");
        executable(
            &program,
            &format!(
                r#"#!/usr/bin/python3
import os
try:
    remaining = {blank_bytes}
    while remaining:
        remaining -= os.write(2, b'\n' * min(remaining, 4096))
    os.write(2, b'Error: HTTP 503: Busy\n')
except BrokenPipeError:
    pass
os._exit(1)
"#
            ),
        );
        assert_eq!(
            CloudRoomSource::new(program).version(Instant::now() + Duration::from_secs(5)),
            Err(SourceError::CommandFailed {
                exit_code: Some(1),
                detail: expected.to_owned()
            }),
            "blank prefix {blank_bytes}"
        );
    }
}

// #1671 / #1732: synthetic processes only. The supervisor stops the caller
// while the direct child exits and its deadline passes. A lower-bound grace
// check tolerates scheduling delays; no action must fit inside the grace.
#[cfg(target_os = "linux")]
#[test]
fn ta3_exited_child_stdout_gets_only_the_bounded_drain_grace() {
    use openwiz_adapter_cloudroom::source::CloudRoomSource;
    use openwiz_core::source::{SessionSource, SourceError};
    use std::io::Write;
    use std::os::unix::net::UnixStream;
    use std::time::{Duration, Instant};

    if let Some(root) = std::env::var_os("OW_DRAIN_WORKER") {
        let root = PathBuf::from(root);
        let mut control = UnixStream::connect(root.join("control.sock")).unwrap();
        control.write_all(b"R\n").unwrap();
        let result = CloudRoomSource::new(root.join("synthetic-drain"))
            .version(Instant::now() + Duration::from_secs(5));
        // Tell the supervisor when the public call returns, before the test
        // harness exits. The descendant still holds stdout in the held case.
        control.write_all(b"D").unwrap();
        if std::env::var("OW_DRAIN_CASE").unwrap() == "complete" {
            assert_eq!(result, Ok("v127".to_owned()));
        } else {
            assert!(
                matches!(result, Err(SourceError::TimedOut { .. })),
                "{result:?}"
            );
        }
        return;
    }

    let f = Fixture::new();
    let socket = f.0.join("control.sock");
    executable(
        &f.0.join("synthetic-drain"),
        &format!(
            r#"#!/usr/bin/python3
import os, socket
writer = os.fork() == 0
if writer:
    os.close(2)
peer = socket.socket(socket.AF_UNIX)
peer.settimeout(30)
peer.connect({socket:?})
peer.sendall(('W' if writer else 'P').encode() + str(os.getpid()).encode() + b'\n')
try:
    assert peer.recv(1) == b'x'
    if writer:
        try:
            os.write(1, b'v127\n')
        except BrokenPipeError:
            pass
        os.close(1)
        peer.sendall(b'D')
finally:
    os._exit(0)
"#,
            socket = socket.to_str().unwrap()
        ),
    );
    let supervisor = f.0.join("supervisor.py");
    fs::write(
        &supervisor,
        r#"
import ctypes, os, select, signal, socket, subprocess, sys, time
assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
listener = socket.socket(socket.AF_UNIX)
listener.bind(os.path.join(sys.argv[3], 'control.sock'))
listener.listen(3)
listener.settimeout(15)
for case in ['complete', 'held']:
    peers = {}
    worker = subprocess.Popen([sys.argv[1], '--exact', sys.argv[2], '--nocapture'],
        env=dict(os.environ, OW_DRAIN_WORKER=sys.argv[3], OW_DRAIN_CASE=case))
    try:
        for _ in range(3):
            peer, _ = listener.accept()
            peer.settimeout(15)
            ready = peer.makefile('rb', buffering=0).readline().decode().strip()
            role = ready[0]
            assert role in ['R', 'P', 'W'] and role not in peers, ready
            peers[role] = peer
            if role == 'P':
                parent_pid = int(ready[1:])
        if case == 'complete':
            # Output and EOF precede direct-child exit: no timed release.
            peers['W'].sendall(b'x')
            assert peers['W'].recv(1) == b'D'
            peers['P'].sendall(b'x')
            assert peers['R'].recv(1) == b'D'
        else:
            # No caller thread can reap while the process is stopped.
            os.kill(worker.pid, signal.SIGSTOP)
            pid, status = os.waitpid(worker.pid, os.WUNTRACED)
            assert pid == worker.pid and os.WIFSTOPPED(status)
            parent_exit = os.pidfd_open(parent_pid)
            try:
                peers['P'].sendall(b'x')
                assert select.select([parent_exit], [], [], 10)[0], 'child did not exit'
            finally:
                os.close(parent_exit)
            # The call's five-second deadline began before helper readiness.
            # Advance comfortably beyond it while the exited child stays
            # unreaped and the descendant keeps stdout open.
            time.sleep(6)
            resumed = time.monotonic()
            os.kill(worker.pid, signal.SIGCONT)
            assert peers['R'].recv(1) == b'D'
            elapsed = time.monotonic() - resumed
            # Approved grace: 100 ms. Delays can only increase this interval;
            # the 15-second socket watchdog supplies generous upper headroom.
            assert elapsed >= 0.090, f'drain grace omitted: {elapsed:.6f}s < 90 ms'
            assert not os.path.exists(f'/proc/{parent_pid}'), 'child was not reaped'
            print(f'held stdout: call returned after {elapsed:.6f}s; writer still held', flush=True)
            peers['W'].sendall(b'x')
            assert peers['W'].recv(1) == b'D'
        assert worker.wait(timeout=15) == 0, case
    finally:
        # EOF releases even a stopped-helper setup failure. Kill/reap only
        # this worker; the subreaper then owns both synthetic descendants.
        for peer in peers.values():
            peer.close()
        if worker.poll() is None:
            worker.kill()
        worker.wait()
        while True:
            try:
                os.waitpid(-1, 0)
            except ChildProcessError:
                break
listener.close()
"#,
    )
    .unwrap();
    let output = Command::new("/usr/bin/python3")
        .arg(supervisor)
        .arg(std::env::current_exe().unwrap())
        .arg("t2_locate::process::ta3_exited_child_stdout_gets_only_the_bounded_drain_grace")
        .arg(&f.0)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    print!("{}", String::from_utf8_lossy(&output.stdout));
}

/// Places the executable `src` at `dst`, owner-only. A separate `cp` process
/// writes it, so this process never holds a writable descriptor for it: a
/// child another test forks meanwhile would inherit one until its exec and
/// keep the file busy, so launching it would fail with ETXTBSY (#2583, as
/// #2559 and #1754).
fn place(src: &std::path::Path, dst: &std::path::Path) {
    placed(copier(src, dst), dst);
}
/// Starts `place`'s `cp`, with no input and its output captured.
fn copier(src: &std::path::Path, dst: &std::path::Path) -> std::process::Child {
    use std::process::Stdio;
    // `cp` would copy into a directory and succeed (#2721, #2731).
    assert!(!dst.is_dir(), "{} is a directory", dst.display());
    std::process::Command::new("cp")
        .arg("--")
        .arg(src)
        .arg(dst)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("cp runs")
}
/// Waits for `place`'s `cp` to succeed, then makes `dst` executable, owner-only.
fn placed(cp: std::process::Child, dst: &std::path::Path) {
    use std::os::unix::fs::PermissionsExt;
    let out = cp.wait_with_output().expect("cp runs");
    assert!(
        out.status.success(),
        "cp {}: {}",
        dst.display(),
        String::from_utf8_lossy(&out.stderr)
    );
    std::fs::set_permissions(dst, std::fs::Permissions::from_mode(0o700)).unwrap();
}
/// Places a fixture script the same way, from a source file that never runs.
fn place_script(dst: &std::path::Path, text: &str) {
    let src = dst.with_extension("src");
    std::fs::write(&src, text).unwrap();
    place(&src, dst);
    std::fs::remove_file(&src).unwrap();
}
/// Descriptors of this process open for writing on `path`'s file.
#[cfg(target_os = "linux")]
fn writers(path: &std::path::Path) -> usize {
    use std::os::unix::fs::MetadataExt;
    let (fds, infos) = (
        std::path::Path::new("/proc/self/fd"),
        std::path::Path::new("/proc/self/fdinfo"),
    );
    let target = std::fs::metadata(path).unwrap();
    std::fs::read_dir(fds)
        .unwrap()
        .filter_map(|fd| {
            let fd = fd.ok()?.file_name();
            let file = std::fs::metadata(fds.join(&fd)).ok()?;
            let info = std::fs::read_to_string(infos.join(&fd)).ok()?;
            let flags = info.lines().find_map(|l| l.strip_prefix("flags:"))?;
            let access = u32::from_str_radix(flags.trim(), 8).unwrap() & 3;
            (file.dev() == target.dev() && file.ino() == target.ino() && access != 0).then_some(())
        })
        .count()
}
/// #2583 (as #2559): this binary's fakes are placed while other test threads
/// fork. The copy is held mid-way on a FIFO, where this process must hold no
/// writer for the placed file; then the placed program launches.
#[cfg(target_os = "linux")]
#[test]
fn placing_a_fake_executable_leaves_no_writer_a_concurrent_fork_could_inherit() {
    let dir = PlaceDir::new("ow-place-t2");
    let program = dir.0.join("placed");
    let held = writers_mid_copy(&dir.0, &program);
    assert_eq!(
        held, 0,
        "mid-copy, this process held a writable descriptor for the placed \
         executable: a child forked then keeps it busy (ETXTBSY)"
    );
    let run = std::process::Command::new(&program).output().unwrap();
    assert!(run.status.success());
    assert_eq!(run.stdout, b"PLACED\n");
}
/// #2731 (as #2721): a directory at the exact destination is refused,
/// instead of `cp` placing the program inside that directory and reporting
/// success.
#[test]
fn placing_onto_a_directory_destination_is_refused() {
    use std::os::unix::fs::DirBuilderExt;
    let dir = std::env::temp_dir().join(format!("ow-place-dir-t2-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let destination = dir.join("placed");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&destination)
        .unwrap();
    let placed = std::panic::catch_unwind(|| place_script(&destination, "#!/bin/sh\nexit 0\n"));
    assert!(
        placed.is_err(),
        "a directory destination was accepted; the program landed inside it"
    );
    assert_eq!(std::fs::read_dir(&destination).unwrap().count(), 0);
    std::fs::remove_dir_all(&dir).unwrap();
}
/// #2699 (as #2594): the proof above fails, never hangs, when its copier fails
/// before opening the FIFO. Here `cp` cannot stat a destination under a
/// regular file.
#[cfg(target_os = "linux")]
#[test]
#[should_panic(expected = "the copier ended before opening the FIFO")]
fn the_fifo_proof_fails_when_its_copier_fails_before_the_rendezvous() {
    let dir = PlaceDir::new("ow-place-t2-early");
    let file = dir.0.join("file");
    std::fs::write(&file, "").unwrap();
    writers_mid_copy(&dir.0, &file.join("placed"));
}
/// #2707, #2734: a copier still waiting on the FIFO when a proof fails is
/// killed and reaped as its `Copy` unwinds, never left behind. With no writer
/// started, the copier stays blocked opening the FIFO past the deadline.
#[cfg(target_os = "linux")]
#[test]
fn the_fifo_proof_reaps_a_copier_that_misses_its_deadline() {
    let dir = PlaceDir::new("ow-place-t2-late");
    let fifo = dir.0.join("late.fifo");
    let made = std::process::Command::new("mkfifo").arg(&fifo).status();
    assert!(made.unwrap().success());
    let program = dir.0.join("placed");
    let cp = copier(&fifo, &program);
    let pid = cp.id();
    let unwound = std::panic::catch_unwind(move || {
        let _copy = Copy {
            source: None,
            cp: Some(cp),
            program,
            until: std::time::Instant::now(),
        };
        panic!("the proof failed while its copier waited");
    });
    assert!(unwound.is_err());
    let left = std::fs::metadata(format!("/proc/{pid}")).map(|_| ());
    assert_eq!(
        left.map_err(|e| e.kind()),
        Err(std::io::ErrorKind::NotFound),
        "the copier was left running or unreaped after the proof unwound"
    );
}
/// An owner-only scratch directory for one FIFO proof, removed when dropped,
/// even by a failing proof.
#[cfg(target_os = "linux")]
struct PlaceDir(std::path::PathBuf);
#[cfg(target_os = "linux")]
impl PlaceDir {
    fn new(prefix: &str) -> Self {
        use std::os::unix::fs::DirBuilderExt;
        let dir = std::env::temp_dir().join(format!("{prefix}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
        Self(dir)
    }
}
#[cfg(target_os = "linux")]
impl Drop for PlaceDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
/// Places a script at `program` as `place` does, from a FIFO in `dir` this
/// process writes, and returns how many writers this process held for
/// `program` while the copy was held mid-way.
#[cfg(target_os = "linux")]
fn writers_mid_copy(dir: &std::path::Path, program: &std::path::Path) -> usize {
    use std::time::{Duration, Instant};
    let fifo = dir.join("source.fifo");
    let made = std::process::Command::new("mkfifo").arg(&fifo).status();
    assert!(made.unwrap().success());
    let mut copy = Copy::start(&fifo, program, Instant::now() + Duration::from_secs(10));
    let head = b"#!/bin/sh\n";
    copy.write(head);
    // Once the first bytes have landed, the placed file's writer is open.
    while std::fs::metadata(program).map_or(true, |m| m.len() < head.len() as u64) {
        copy.check("the copy started");
    }
    let held = writers(program);
    copy.write(b"printf 'PLACED\\n'\n");
    copy.finish();
    held
}
/// `place`'s `cp` copying a FIFO to `program`, and this process's writer for
/// that FIFO. Dropped, even by a failing proof, it closes the writer, so the
/// copier reads its end, then kills a copier still running after a short
/// grace and reaps it (#2707).
#[cfg(target_os = "linux")]
struct Copy {
    source: Option<std::fs::File>,
    cp: Option<std::process::Child>,
    program: std::path::PathBuf,
    until: std::time::Instant,
}
#[cfg(target_os = "linux")]
impl Copy {
    /// Starts the copier and opens the FIFO's writer once the copier's reader
    /// has it open, failing if the copier ends first or `until` passes.
    fn start(fifo: &std::path::Path, program: &std::path::Path, until: std::time::Instant) -> Self {
        let mut copy = Self {
            source: None,
            cp: Some(copier(fifo, program)),
            program: program.to_owned(),
            until,
        };
        // Opening blocks until a reader has the FIFO open, so it runs on its
        // own thread while this one watches the copier and the deadline.
        let opening = {
            let fifo = fifo.to_owned();
            std::thread::spawn(move || std::fs::OpenOptions::new().write(true).open(fifo))
        };
        while !opening.is_finished() {
            if copy.ended() || std::time::Instant::now() >= until {
                // A reader of this process's own completes the open; dropped
                // with it, so the copier sees an empty source if it opens late.
                let reader = std::fs::File::open(fifo);
                drop(opening.join());
                drop(reader);
                assert!(!copy.ended(), "the copier ended before opening the FIFO");
                panic!("the copier never opened the FIFO");
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        copy.source = Some(opening.join().unwrap().unwrap());
        copy
    }
    fn ended(&mut self) -> bool {
        self.cp
            .as_mut()
            .is_none_or(|cp| cp.try_wait().unwrap().is_some())
    }
    /// Fails if the copier has ended or `until` has passed; else waits a moment.
    fn check(&mut self, waiting_for: &str) {
        assert!(!self.ended(), "the copier ended before {waiting_for}");
        assert!(
            std::time::Instant::now() < self.until,
            "the deadline passed before {waiting_for}"
        );
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    fn write(&mut self, bytes: &[u8]) {
        use std::io::Write;
        self.source.as_mut().unwrap().write_all(bytes).unwrap();
    }
    /// Closes the writer and waits, by `until`, for the copier to succeed.
    fn finish(mut self) {
        drop(self.source.take());
        while !self.ended() {
            assert!(
                std::time::Instant::now() < self.until,
                "the copier never finished"
            );
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        placed(self.cp.take().unwrap(), &self.program);
    }
}
#[cfg(target_os = "linux")]
impl Drop for Copy {
    fn drop(&mut self) {
        drop(self.source.take());
        // The copier ends soon after its end of file: a short grace past a
        // missed deadline, never an unbounded wait.
        let now = std::time::Instant::now();
        let until = self.until.max(now + std::time::Duration::from_secs(1));
        while !self.ended() && std::time::Instant::now() < until {
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        if let Some(mut cp) = self.cp.take() {
            let _ = cp.kill();
            let _ = cp.wait();
        }
    }
}
