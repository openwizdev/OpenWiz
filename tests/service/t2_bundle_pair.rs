//! BX1 (#2098): CloudRoom runs one app as two mounts of the same AppImage
//! file: the GUI on one mount, and its direct child, the AppImage bridge
//! supervisor, on another. Only that exact pair is accepted, and its
//! launcher comes from the bridge's mount; every other shape of two or more
//! running roots stays `Ambiguous`.
//!
//! Synthetic proc and mount relationships only; no real process is read.
//! Synthetic assumptions (shape seen in the read-only PC discovery, values
//! invented): the GUI's own environment names no mount, its direct parent
//! (the AppImage's launcher shell, outside every mount) carries `APPDIR` =
//! the GUI's mount, and the bridge head carries `APPDIR` = its own mount;
//! both carry the same `APPIMAGE`.
//!
//! Red run (2026-11-08, before the pair rule): `cargo test -p openwiz-tests
//! --test service t2_bundle_pair` exited 101: the accepted pair got
//! `Err(Ambiguous)`, expected `Ok(<bridge mount>/.../room-cli)`, in both
//! tests (the refusal table's first baseline is that pair). Log:
//! `private/evidence/bx1/red-run.txt`. Each refusal row's guard is proven by
//! the mutation runs in `private/evidence/bx1/mutations.txt`.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

use openwiz_adapter_cloudroom::locate::{Basis, LocateError};

use super::{Fixture, TAIL, dirs};

const GUI: &str = ".mount_synthetic_gui";
const BRIDGE: &str = ".mount_synthetic_bridge";
const THIRD: &str = ".mount_synthetic_third";
const LAUNCHER: &str = "#!/bin/sh\n\":\" //; exit 0\n";

/// The PC's shape: launcher shell 100 starts the GUI 201 on GUI, which
/// starts the bridge supervisor 301 on BRIDGE; each has a child.
struct Pair {
    f: Fixture,
    appimage: PathBuf,
}

impl Pair {
    fn new() -> Self {
        let f = Fixture::new();
        for mount in [GUI, BRIDGE, THIRD] {
            let cli = f.file(format!("{mount}/{TAIL}"));
            super::process::executable(&cli, LAUNCHER);
        }
        let appimage = f.file("home/Synthetic-x86_64.AppImage");
        let pair = Self { f, appimage };
        pair.shell("100", "1", &pair.record(GUI));
        pair.app("201", GUI, "100", None);
        pair.app("202", GUI, "201", None);
        pair.app("301", BRIDGE, "201", Some(&pair.record(BRIDGE)));
        pair.app("302", BRIDGE, "301", Some(&pair.record(BRIDGE)));
        pair
    }

    fn mount(&self, mount: &str) -> PathBuf {
        self.f.0.join(mount)
    }

    fn cli(&self, mount: &str) -> PathBuf {
        self.mount(mount).join(TAIL)
    }

    fn proc(&self, pid: &str) -> PathBuf {
        self.f.process_root().join(pid)
    }

    /// The AppImage runtime's environment for `mount`, among unrelated values.
    fn record(&self, mount: &str) -> Vec<u8> {
        environ(&[
            "HOME=/home/synthetic".as_bytes(),
            format!("APPDIR={}", self.mount(mount).display()).as_bytes(),
            format!("APPIMAGE={}", self.appimage.display()).as_bytes(),
            b"OWD=/home/synthetic",
        ])
    }

    fn stat(&self, pid: &str, ppid: &str) {
        fs::write(
            self.proc(pid).join("stat"),
            format!("{pid} (synthetic (x)) S {ppid} {pid} {pid} 0 -1 4194560 0\n"),
        )
        .unwrap();
    }

    /// A process outside every mount (the launcher shell), with its parent.
    fn shell(&self, pid: &str, ppid: &str, environ: &[u8]) {
        let shell = self.f.0.join("bin/synthetic-shell");
        if !shell.exists() {
            self.f.file("bin/synthetic-shell");
        }
        dirs::private_dir_all(self.proc(pid)).unwrap();
        std::os::unix::fs::symlink(shell, self.proc(pid).join("exe")).unwrap();
        self.stat(pid, ppid);
        fs::write(self.proc(pid).join("environ"), environ).unwrap();
    }

    /// A process running the mount's app binary, with its parent and,
    /// optionally, a readable environment.
    fn app(&self, pid: &str, mount: &str, ppid: &str, environ: Option<&[u8]>) {
        self.f.running(mount, pid);
        self.stat(pid, ppid);
        if let Some(environ) = environ {
            fs::write(self.proc(pid).join("environ"), environ).unwrap();
        }
    }

    fn set_environ(&self, pid: &str, environ: &[u8]) {
        fs::write(self.proc(pid).join("environ"), environ).unwrap();
    }

    fn resolve(&self) -> Result<PathBuf, LocateError> {
        self.f.discovery().resolve()
    }
}

fn environ(entries: &[&[u8]]) -> Vec<u8> {
    let mut bytes = Vec::new();
    for entry in entries {
        bytes.extend_from_slice(entry);
        bytes.push(0);
    }
    bytes
}

/// A record naming `appdir` and `appimage` exactly, nothing else checked.
fn named(appdir: &Path, appimage: &Path) -> Vec<u8> {
    environ(&[
        format!("APPDIR={}", appdir.display()).as_bytes(),
        format!("APPIMAGE={}", appimage.display()).as_bytes(),
    ])
}

#[test]
fn t2_bundle_pair_gui_and_its_bridge_from_one_appimage_select_the_bridge_launcher() {
    let pair = Pair::new();
    assert_eq!(pair.resolve(), Ok(pair.cli(BRIDGE)));
    // The diagnostics record the choice: the bridge's mount, beside the GUI's.
    let located = pair.f.discovery().locate().unwrap();
    assert_eq!(
        located.basis,
        Basis::AppImagePair {
            gui: pair.mount(GUI),
            bridge: pair.mount(BRIDGE),
        }
    );
    assert_eq!(
        located.basis.describe(),
        format!(
            "room-cli from the bridge's mount {} (paired with the GUI's mount {}: \
             one AppImage file, identical room-cli)",
            pair.mount(BRIDGE).display(),
            pair.mount(GUI).display()
        )
    );
    // The same pair with the bridge's own helpers gone is still the pair.
    fs::remove_dir_all(pair.proc("302")).unwrap();
    assert_eq!(pair.resolve(), Ok(pair.cli(BRIDGE)));
    // With the GUI's tree gone, the bridge's mount is the one running root,
    // selected as before BX1 with no record read.
    for pid in ["100", "201", "202"] {
        fs::remove_dir_all(pair.proc(pid)).unwrap();
    }
    fs::remove_file(pair.proc("301").join("environ")).unwrap();
    let located = pair.f.discovery().locate().unwrap();
    assert_eq!(
        (located.launcher, located.basis),
        (pair.cli(BRIDGE), Basis::OneRoot)
    );
}

#[test]
fn t2_bundle_pair_every_other_shape_stays_ambiguous() {
    type Shape = fn(&Pair);
    let shapes: [(&str, Shape); 34] = [
        // Two unrelated apps.
        ("bridge started by init, not the GUI", |p| {
            p.stat("301", "1")
        }),
        ("bridge started by the launcher shell", |p| {
            p.stat("301", "100")
        }),
        ("bridge started by a GUI helper", |p| p.stat("301", "202")),
        ("GUI started by the bridge", |p| {
            p.stat("301", "100");
            p.stat("201", "301");
        }),
        // Lineage that doesn't check out.
        ("a second, independent start on the bridge mount", |p| {
            p.app("303", BRIDGE, "1", Some(&p.record(BRIDGE)));
        }),
        ("a second, independent start on the GUI mount", |p| {
            p.app("203", GUI, "100", None);
        }),
        ("a GUI-mount process under the bridge", |p| {
            p.app("203", GUI, "301", None);
        }),
        ("a parent cycle on the bridge mount", |p| {
            p.app("303", BRIDGE, "304", None);
            p.app("304", BRIDGE, "303", None);
        }),
        ("a bridge-mount process with no parent record", |p| {
            fs::remove_file(p.proc("302").join("stat")).unwrap();
        }),
        ("the GUI with no parent record", |p| {
            fs::remove_file(p.proc("201").join("stat")).unwrap();
        }),
        ("a stat line for another pid", |p| {
            fs::write(p.proc("301").join("stat"), "999 (synthetic) S 201 1\n").unwrap();
        }),
        ("a malformed parent field", |p| {
            fs::write(p.proc("301").join("stat"), "301 (synthetic) S +201 1\n").unwrap();
        }),
        ("the GUI's launcher runs from the bridge's mount", |p| {
            p.stat("201", "302");
            p.set_environ("302", &p.record(GUI));
        }),
        ("the GUI's launcher is gone", |p| {
            fs::remove_dir_all(p.proc("100")).unwrap();
        }),
        // Different AppImage files, or records that don't name them.
        ("bridge from another AppImage file", |p| {
            let other = p.f.file("home/Other-x86_64.AppImage");
            p.set_environ("301", &named(&p.mount(BRIDGE), &other));
        }),
        ("GUI from another AppImage file", |p| {
            let other = p.f.file("home/Other-x86_64.AppImage");
            p.set_environ("100", &named(&p.mount(GUI), &other));
        }),
        ("the same AppImage through a symlink", |p| {
            let link = p.f.0.join("home/link.AppImage");
            std::os::unix::fs::symlink(&p.appimage, &link).unwrap();
            p.set_environ("301", &named(&p.mount(BRIDGE), &link));
        }),
        (
            "both records name the AppImage through a symlinked folder",
            |p| {
                let folder = p.f.0.join("home-link");
                std::os::unix::fs::symlink(p.f.0.join("home"), &folder).unwrap();
                let link = folder.join("Synthetic-x86_64.AppImage");
                p.set_environ("301", &named(&p.mount(BRIDGE), &link));
                p.set_environ("100", &named(&p.mount(GUI), &link));
            },
        ),
        ("the AppImage path is gone", |p| {
            fs::remove_file(&p.appimage).unwrap()
        }),
        ("the AppImage path is a directory", |p| {
            fs::remove_file(&p.appimage).unwrap();
            dirs::private_dir(&p.appimage).unwrap();
        }),
        ("a relative AppImage path", |p| {
            let relative = Path::new("home/Synthetic-x86_64.AppImage");
            p.set_environ("301", &named(&p.mount(BRIDGE), relative));
            p.set_environ("100", &named(&p.mount(GUI), relative));
        }),
        ("the bridge record names the GUI's mount", |p| {
            p.set_environ("301", &named(&p.mount(GUI), &p.appimage));
        }),
        ("the launcher record names the bridge's mount", |p| {
            p.set_environ("100", &named(&p.mount(BRIDGE), &p.appimage));
        }),
        ("the bridge head has no record", |p| {
            fs::remove_file(p.proc("301").join("environ")).unwrap();
        }),
        ("the bridge record has APPDIR twice", |p| {
            let mut twice = p.record(BRIDGE);
            twice.extend(environ(&[
                format!("APPDIR={}", p.mount(BRIDGE).display()).as_bytes()
            ]));
            p.set_environ("301", &twice);
        }),
        ("the launcher record has no APPIMAGE", |p| {
            p.set_environ(
                "100",
                &environ(&[format!("APPDIR={}", p.mount(GUI).display()).as_bytes()]),
            );
        }),
        // Differing launcher bytes.
        ("differing room-cli bytes", |p| {
            super::process::executable(&p.cli(GUI), "#!/bin/sh\n\":\" //; exit 1\n");
        }),
        // A third root.
        ("a third running root", |p| p.app("401", THIRD, "201", None)),
        // A failed permission check on either root.
        ("GUI room-cli group-writable", |p| {
            fs::set_permissions(p.cli(GUI), fs::Permissions::from_mode(0o775)).unwrap();
        }),
        ("bridge room-cli not executable", |p| {
            fs::set_permissions(p.cli(BRIDGE), fs::Permissions::from_mode(0o644)).unwrap();
        }),
        ("GUI room-cli missing a sibling", |p| {
            fs::remove_file(p.cli(GUI).with_file_name("index.js")).unwrap();
        }),
        ("bridge room-cli missing a sibling", |p| {
            fs::remove_file(p.cli(BRIDGE).with_file_name("daemon-bundle.mjs")).unwrap();
        }),
        ("GUI app binary group-writable", |p| {
            let app = p.mount(GUI).join("synthetic-app");
            fs::set_permissions(app, fs::Permissions::from_mode(0o575)).unwrap();
        }),
        ("GUI room-cli without the launcher prefix", |p| {
            super::process::executable(&p.cli(GUI), "#!/bin/sh\nexit 0\n");
            super::process::executable(&p.cli(BRIDGE), "#!/bin/sh\nexit 0\n");
        }),
    ];
    // The scan's existing per-process checks refuse these before any pair
    // is considered, with their existing error, as for one running root.
    let scan_refusals = [
        "GUI room-cli missing a sibling",
        "bridge room-cli missing a sibling",
        "GUI app binary group-writable",
    ];
    for (name, shape) in shapes {
        let pair = Pair::new();
        assert_eq!(pair.resolve(), Ok(pair.cli(BRIDGE)), "baseline for {name}");
        shape(&pair);
        let expected = if scan_refusals.contains(&name) {
            LocateError::UnexpectedFile
        } else {
            LocateError::Ambiguous
        };
        assert_eq!(pair.resolve(), Err(expected), "{name}");
    }
}

// R1 (#2101 review): the choice reaches the owner through production
// dispatch, as one sanitized stderr diagnostic beside the one JSON document,
// once per process however many room-cli calls the command makes.
// Red run (2026-11-08, before the diagnostic): this test exited 101: stderr
// was empty, expected the one note line. Log: `private/evidence/bx1/red-run-r1.txt`.
#[test]
fn t2_bundle_pair_the_cli_reports_the_chosen_mount_once_on_stderr() {
    let pair = Pair::new();
    let calls = answering(&pair);
    let out = std::process::Command::new(super::process::fixture_binary("openwiz"))
        .args(["ls", "--json"])
        .env("OPENWIZ_FIXTURE_ROOT", &pair.f.0)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let json: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(json["schema"], "openwiz.inventory.v1");
    assert_eq!(
        String::from_utf8(out.stderr).unwrap(),
        format!(
            "openwiz: note: room-cli from the bridge's mount {} (paired with the GUI's \
             mount {}: one AppImage file, identical room-cli)\n",
            pair.mount(BRIDGE).display(),
            pair.mount(GUI).display()
        )
    );
    let ran: Vec<_> = fs::read_to_string(&calls)
        .unwrap()
        .lines()
        .map(|line| line.split_once(' ').unwrap().0.to_owned())
        .collect();
    assert_eq!(ran.len(), 4, "every room-cli call of ls");
    assert!(
        ran.iter().all(|path| Path::new(path) == pair.cli(BRIDGE)),
        "{ran:?}"
    );
    // One running root, as before BX1: no note at all.
    for pid in ["100", "201", "202"] {
        fs::remove_dir_all(pair.proc(pid)).unwrap();
    }
    let out = std::process::Command::new(super::process::fixture_binary("openwiz"))
        .args(["ls", "--json"])
        .env("OPENWIZ_FIXTURE_ROOT", &pair.f.0)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert_eq!(String::from_utf8(out.stderr).unwrap(), "");
}

#[test]
fn t2_bundle_pair_the_description_carries_no_control_characters() {
    let basis = Basis::AppImagePair {
        gui: PathBuf::from("/tmp/.mount_gui\u{1b}[31m"),
        bridge: PathBuf::from("/tmp/.mount_bridge\nforged line\r"),
    };
    assert_eq!(
        basis.describe(),
        "room-cli from the bridge's mount /tmp/.mount_bridge?forged line? (paired with the \
         GUI's mount /tmp/.mount_gui?[31m: one AppImage file, identical room-cli)"
    );
}

/// Byte-identical answering launchers in both mounts; each call's `$0` (which
/// mount's file ran) and arguments go to the returned log.
fn answering(pair: &Pair) -> PathBuf {
    let calls = pair.f.0.join("calls");
    let script = format!(
        "#!/bin/sh\n\":\" //; printf '%s %s\\n' \"$0\" \"$*\" >> '{}'\nif [ \"$1\" = --version ]; then printf 'v141\\n'; else printf '[]\\n'; fi\n",
        calls.display()
    );
    for mount in [GUI, BRIDGE] {
        super::process::executable(&pair.cli(mount), &script);
    }
    calls
}

/// Runs the fixture `openwiz` (production dispatch) with `stderr`, and gives
/// it 60 seconds to finish; a hung run is killed and fails the test.
fn bounded(pair: &Pair, args: &[&str], stderr: std::process::Stdio) -> std::process::Output {
    let empty = pair.f.0.join("empty-path");
    if !empty.exists() {
        dirs::private_dir(&empty).unwrap();
    }
    let child = std::process::Command::new(super::process::fixture_binary("openwiz"))
        .args(args)
        .env("OPENWIZ_FIXTURE_ROOT", &pair.f.0)
        // No gh: GitHub's reads fail at once; CloudRoom's still run.
        .env("PATH", &empty)
        .stdout(std::process::Stdio::piped())
        .stderr(stderr)
        .spawn()
        .unwrap();
    let pid = child.id();
    let (done, finished) = std::sync::mpsc::channel();
    std::thread::spawn(move || done.send(child.wait_with_output()));
    match finished.recv_timeout(std::time::Duration::from_secs(60)) {
        Ok(out) => out.unwrap(),
        Err(_) => {
            let _ = std::process::Command::new("/bin/kill")
                .args(["-KILL", &pid.to_string()])
                .status();
            panic!("openwiz {args:?} did not finish within 60 s");
        }
    }
}

// R2 (#2101 review 2): `fleet` reads CloudRoom on a worker thread while CLI
// dispatch holds the stderr lock; the pair note must not wait for that lock.
// Red run (2026-11-08, before the fix): killed after 60 s, deadlocked.
// Log: `private/evidence/bx1/red-run-r2-r3.txt`.
#[test]
fn t2_bundle_pair_fleet_reads_cloudroom_off_the_main_thread_without_hanging() {
    let pair = Pair::new();
    let calls = answering(&pair);
    let out = bounded(
        &pair,
        &["fleet", "1", "--json"],
        std::process::Stdio::piped(),
    );
    let stderr = String::from_utf8(out.stderr).unwrap();
    assert_eq!(
        stderr
            .matches("openwiz: note: room-cli from the bridge's mount")
            .count(),
        1,
        "{stderr}"
    );
    let doc: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert!(doc.is_object(), "{doc}");
    let ran = fs::read_to_string(&calls).unwrap();
    assert!(
        ran.lines().any(|line| line.ends_with(" --version")),
        "{ran}"
    );
}

// R3 (#2101 review 2): a failing diagnostic sink never aborts the command.
// Red run (2026-11-08, before the fix): exit 101, the `eprintln!` panic
// (its own message could not reach the full stderr either).
#[test]
fn t2_bundle_pair_a_failing_stderr_never_aborts_the_command() {
    let pair = Pair::new();
    answering(&pair);
    let full = fs::OpenOptions::new()
        .write(true)
        .open("/dev/full")
        .unwrap();
    let out = bounded(&pair, &["ls", "--json"], std::process::Stdio::from(full));
    assert_eq!(out.status.code(), Some(0));
    let doc: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(doc["schema"], "openwiz.inventory.v1");
}
