//! #267's fixture-only layout and marker checks. Ownership cases use
//! synthetic metadata; the executable proofs share production dispatch
//! through the approved fixture-only binaries.
//! Claim: only the fixed bundle layout yields a candidate; no candidate,
//! ambiguity and unexpected file types are refused, without executing them.
//!
//! Red run 1 (2026-11-01), before candidate selection was implemented:
//! `cargo test -p openwiz-tests --test service t2_only_the_fixed_bundle_layout_supplies_a_candidate`
//! exited 101. The literal bundle-path assertion failed: left Err(NotRunning),
//! right Ok(the fixture's .mount_synthetic/resources/.../dist/room-cli).
//! `test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 26 filtered out; finished in 0.00s`
//!
//! Red run 6 (full-set check 9 at ce192b6, 2026-11-01):
//! `cargo test --workspace` exited 101. The existing directory-mode check
//! reported four calls here leaving mode to the umask (lines 33, 39, 166,
//! 220 before this comment). Checks result: 37 passed; 1 failed.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};

use openwiz_adapter_cloudroom::locate::{
    Discovery, LauncherMetadata, LocateError, check_launcher_markers, pc_bundle_candidate,
};
use std::os::unix::fs::{MetadataExt, PermissionsExt};

#[path = "../support/dirs.rs"]
mod dirs;

#[path = "t2_process.rs"]
mod process;

#[path = "t2_docs.rs"]
mod docs;

#[path = "t2_bundle_pair.rs"]
mod bundle_pair;

const TAIL: &str = "resources/app.asar.unpacked/node_modules/bb-app/host-daemon/dist/room-cli";

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let root = Path::new(env!("CARGO_TARGET_TMPDIR")).join(format!(
            "t2-bundle-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        dirs::private_dir(&root).unwrap();
        Self(root)
    }

    fn file(&self, relative: impl AsRef<Path>) -> PathBuf {
        let path = self.0.join(relative);
        dirs::private_dir_all(path.parent().unwrap()).unwrap();
        // Deliberately not an executable or a claimed real launcher.
        fs::write(&path, "synthetic unverified candidate\n").unwrap();
        if path.file_name().is_some_and(|name| name == "room-cli") {
            for sibling in ["daemon-bundle.mjs", "index.js"] {
                fs::write(path.with_file_name(sibling), "synthetic sibling\n").unwrap();
            }
        }
        path
    }

    // Synthetic assumptions: proc entries identify a root-owned executable
    // directly in its AppImage mount. This shape has NOT been observed on PC.
    fn process_root(&self) -> PathBuf {
        let root = self.0.join("proc");
        dirs::private_dir_all(root.join("self")).unwrap();
        root
    }

    fn running(&self, mount: &str, pid: &str) {
        let app = self.0.join(format!("{mount}/synthetic-app"));
        if !app.exists() {
            self.file(format!("{mount}/synthetic-app"));
            fs::set_permissions(&app, fs::Permissions::from_mode(0o555)).unwrap();
        }
        let process = self.process_root().join(pid);
        dirs::private_dir_all(&process).unwrap();
        std::os::unix::fs::symlink(app, process.join("exe")).unwrap();
    }

    fn discovery(&self) -> Discovery {
        Discovery::pc(self.0.clone(), |m| LauncherMetadata {
            uid: 0,
            mode: m.mode(),
        })
        .with_process_root(self.process_root())
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
fn t2_active_process_selects_one_bundle_beside_a_stale_mount() {
    let f = Fixture::new();
    let active = f.file(format!(".mount_synthetic_active/{TAIL}"));
    let stale = f.file(format!(".mount_synthetic_stale/{TAIL}"));
    for candidate in [&active, &stale] {
        process::executable(candidate, "#!/bin/sh\n\":\" //; exit 0\n");
    }
    f.running(".mount_synthetic_active", "101");
    // Layout alone remains ambiguous; only process evidence can select it.
    assert_eq!(pc_bundle_candidate(&f.0), Err(LocateError::Ambiguous));
    assert_eq!(f.discovery().resolve(), Ok(active.clone()));
    let calls = f.0.join("active-calls");
    process::executable(
        &active,
        &format!(
            "#!/bin/sh\n\":\" //; printf '%s\\n' \"$*\" >> '{}'\ncase \"$1\" in\n--version) printf 'v141\\n';;\nproject) printf '%s\\n' '[{{\"id\":\"prj_synthetic\",\"name\":\"Synthetic\",\"gitRemoteUrl\":\"https://github.com/synthetic-owner/synthetic-repo\"}}]';;\n*) printf '[]\\n';;\nesac\n",
            calls.display()
        ),
    );
    use openwiz_adapter_cloudroom::{fleet, source::CloudRoomSource};
    use openwiz_core::fleet::model::{ListOutcome, NonEmpty, Outcome};
    use std::time::{Duration, Instant};
    let source = CloudRoomSource::new(active);
    let reads = fleet::read(
        &source,
        &fleet::Repository::parse("synthetic-owner/synthetic-repo").unwrap(),
        Instant::now() + Duration::from_secs(5),
    );
    assert_eq!(
        reads.version,
        Outcome::Complete {
            value: NonEmpty::new("v141").unwrap()
        }
    );
    assert!(matches!(reads.projects, ListOutcome::Complete { value } if value.len() == 1));
    assert_eq!(reads.threads, ListOutcome::Complete { value: vec![] });
    assert_eq!(
        fs::read_to_string(calls)
            .unwrap()
            .lines()
            .collect::<Vec<_>>(),
        [
            "--version",
            "project list --json --include-personal",
            "thread list --json --include-hidden"
        ]
    );
}

#[test]
fn t2_unreadable_unrelated_process_does_not_hide_a_verified_running_app() {
    struct Restore(PathBuf);
    impl Drop for Restore {
        fn drop(&mut self) {
            fs::set_permissions(&self.0, fs::Permissions::from_mode(0o700)).unwrap();
        }
    }
    for has_active_app in [true, false] {
        let f = Fixture::new();
        let candidate = f.file(format!(".mount_synthetic/{TAIL}"));
        process::executable(&candidate, "#!/bin/sh\n\":\" //; exit 0\n");
        if has_active_app {
            f.running(".mount_synthetic", "101");
        }
        let proc = f.process_root();
        let restore = Restore(proc.join("102"));
        dirs::private_dir(&restore.0).unwrap();
        let unrelated = f.file("bin/synthetic-unrelated-app");
        std::os::unix::fs::symlink(unrelated, restore.0.join("exe")).unwrap();
        fs::set_permissions(&restore.0, fs::Permissions::from_mode(0o000)).unwrap();
        // Synthetic non-dumpable-process analogue: the proc directory still
        // belongs to this user, but its exe link supplies no readable evidence.
        assert_eq!(
            fs::metadata(&restore.0).unwrap().uid(),
            fs::metadata(proc.join("self")).unwrap().uid()
        );
        assert_eq!(
            fs::read_link(restore.0.join("exe")).unwrap_err().kind(),
            std::io::ErrorKind::PermissionDenied
        );
        let result = f.discovery().resolve();
        if has_active_app {
            assert_eq!(result, Ok(candidate));
        } else {
            assert_eq!(
                result,
                Err(LocateError::NoRunningApp),
                "an unreadable process cannot select a stale bundle"
            );
        }
    }
}

#[test]
fn t2_absent_and_unmatched_bundles_have_distinct_safe_reasons_without_execution() {
    use openwiz_core::{model::Fact, ops::version_fact};
    for mounts in 0..=2 {
        let f = Fixture::new();
        let calls = f.0.join("unexpected-launcher-call");
        for index in 0..mounts {
            let launcher = f.file(format!(".mount_synthetic_{index}/{TAIL}"));
            process::executable(
                &launcher,
                &format!(
                    "#!/bin/sh\n\":\" //; printf called > '{}'\nexit 97\n",
                    calls.display()
                ),
            );
        }
        let error = f.discovery().resolve().unwrap_err();
        let category = if mounts == 0 {
            "no bundle"
        } else {
            "no running app identified"
        };
        assert_eq!(
            version_fact("room-cli --version", "v127", Err(error.into())),
            (
                Fact::Unknown(format!("room-cli --version could not be run ({category})")),
                false
            )
        );
        assert!(!calls.exists(), "layout inspection must execute nothing");
    }
}

// Red run 4 (2026-11-01): the command selecting this test exited 101.
// An empty prefix got Ok(()), expected Err(UnexpectedFile).
// Result: 0 passed; 1 failed; 29 filtered out.
#[test]
fn t2_launcher_markers_require_the_observed_prefix_and_safe_root_permissions() {
    let observed_prefix = b"#!/bin/sh\n\":\" //;";
    assert_eq!(
        check_launcher_markers(
            LauncherMetadata {
                uid: 0,
                mode: 0o755
            },
            observed_prefix
        ),
        Ok(())
    );
    // Expected values come from the read-only PC observation on #267;
    // every rejected value below is a synthetic mutation of those facts.
    let bad_prefixes: &[&[u8]] = &[
        b"",
        b"#!/bin/sh",
        b"#!/bin/sh\n",
        b"#!/bin/sh\n\":\" //",
        b"#!/bin/bash\n\":\" //;",
        b"#!/bin/sh\r\n\":\" //;",
        b"#!/bin/sh \n\":\" //;",
        b"#!/bin/sh\n# \":\" //;",
        b"\xef\xbb\xbf#!/bin/sh\n\":\" //;",
        b"#!/bin/sh\n\":\" /\xff;",
    ];
    for prefix in bad_prefixes {
        assert_eq!(
            check_launcher_markers(
                LauncherMetadata {
                    uid: 0,
                    mode: 0o755
                },
                prefix
            ),
            Err(LocateError::UnexpectedFile),
            "prefix {prefix:?}"
        );
    }
    for (uid, mode) in [
        (1000, 0o755),
        (0, 0o775),
        (0, 0o757),
        (0, 0o777),
        (0, 0o644),
    ] {
        assert_eq!(
            check_launcher_markers(LauncherMetadata { uid, mode }, observed_prefix),
            Err(LocateError::UnexpectedFile),
            "uid={uid}, mode={mode:o}"
        );
    }
}

#[test]
fn t2_only_the_fixed_bundle_layout_supplies_a_candidate() {
    let f = Fixture::new();
    // These are plausible decoys, including a PATH-style bin directory.
    for relative in [
        "bin/room-cli".to_owned(),
        format!("mount_synthetic/{TAIL}"),
        format!(".mount_synthetic/extra/{TAIL}"),
        ".mount_synthetic/resources/room-cli".to_owned(),
    ] {
        f.file(relative);
    }
    assert_eq!(pc_bundle_candidate(&f.0), Err(LocateError::NotRunning));
    let expected = f.file(format!(".mount_synthetic/{TAIL}"));
    assert_eq!(pc_bundle_candidate(&f.0), Ok(expected));
}

// Red run 2 (2026-11-01): the command selecting this test exited 101.
// The two-bundle assertion got Ok(the first fixture path), expected
// Err(Ambiguous). Result: 0 passed; 1 failed; 27 filtered out.
#[test]
fn t2_ambiguity_is_refused_and_selection_is_not_cached() {
    let f = Fixture::new();
    assert_eq!(pc_bundle_candidate(&f.0), Err(LocateError::NotRunning));
    let first = f.file(format!(".mount_synthetic_one/{TAIL}"));
    assert_eq!(pc_bundle_candidate(&f.0), Ok(first.clone()));
    let second = f.file(format!(".mount_synthetic_two/{TAIL}"));
    assert_eq!(pc_bundle_candidate(&f.0), Err(LocateError::Ambiguous));
    fs::remove_dir_all(f.0.join(".mount_synthetic_one")).unwrap();
    assert_eq!(pc_bundle_candidate(&f.0), Ok(second.clone()));
    // A restart may use the same bundle name later; never cache either path.
    fs::remove_dir_all(f.0.join(".mount_synthetic_two")).unwrap();
    assert_eq!(pc_bundle_candidate(&f.0), Err(LocateError::NotRunning));
    let first_again = f.file(format!(".mount_synthetic_one/{TAIL}"));
    assert_eq!(pc_bundle_candidate(&f.0), Ok(first_again));
    let missing = f.0.join("absent");
    assert_eq!(pc_bundle_candidate(&missing), Err(LocateError::NotRunning));
    let not_a_root = f.file("ordinary-file");
    assert_eq!(
        pc_bundle_candidate(&not_a_root),
        Err(LocateError::Unreadable)
    );
}

// Red run 3 (2026-11-01): the command selecting this test exited 101.
// A directory at the CLI leaf got Err(NotRunning), expected
// Err(UnexpectedFile). Result: 0 passed; 1 failed; 28 filtered out.
#[test]
fn t2_unexpected_files_and_symlink_components_are_refused() {
    let f = Fixture::new();
    let leaf = f.0.join(format!(".mount_synthetic/{TAIL}"));
    dirs::private_dir_all(&leaf).unwrap();
    assert_eq!(pc_bundle_candidate(&f.0), Err(LocateError::UnexpectedFile));

    let f = Fixture::new();
    f.file(".mount_synthetic");
    assert_eq!(pc_bundle_candidate(&f.0), Err(LocateError::NotRunning));

    let components = [
        ".mount_synthetic",
        "resources",
        "app.asar.unpacked",
        "node_modules",
        "bb-app",
        "host-daemon",
        "dist",
        "room-cli",
    ];
    for end in 1..=components.len() {
        let f = Fixture::new();
        f.file(format!(".mount_synthetic/{TAIL}"));
        let component = components[..end].iter().collect::<PathBuf>();
        let original = f.0.join(&component);
        let target = f.0.join("relocated");
        fs::rename(&original, &target).unwrap();
        std::os::unix::fs::symlink(&target, &original).unwrap();
        assert_eq!(
            pc_bundle_candidate(&f.0),
            Err(if end == 1 {
                LocateError::NotRunning
            } else {
                LocateError::UnexpectedFile
            }),
            "symlink at {component:?} must not escape the bundle pattern"
        );
    }

    let f = Fixture::new();
    std::os::unix::fs::symlink(f.0.join("missing"), f.0.join(".mount_synthetic")).unwrap();
    assert_eq!(pc_bundle_candidate(&f.0), Err(LocateError::NotRunning));

    let f = Fixture::new();
    f.file(".mount_synthetic/resources");
    assert_eq!(pc_bundle_candidate(&f.0), Err(LocateError::UnexpectedFile));
}

// Red run 5 (2026-11-01): the command selecting this test exited 101.
// Missing daemon-bundle.mjs got Ok(the candidate), expected Err(UnexpectedFile).
// Result: 0 passed; 1 failed; 30 filtered out.
#[test]
fn t2_both_recorded_siblings_must_be_regular_files() {
    for sibling in ["daemon-bundle.mjs", "index.js"] {
        for kind in ["missing", "directory", "symlink"] {
            let f = Fixture::new();
            let candidate = f.file(format!(".mount_synthetic/{TAIL}"));
            let path = candidate.with_file_name(sibling);
            fs::remove_file(&path).unwrap();
            match kind {
                "missing" => {}
                "directory" => dirs::private_dir(&path).unwrap(),
                "symlink" => {
                    let target = f.file("synthetic-target");
                    std::os::unix::fs::symlink(target, &path).unwrap();
                }
                _ => unreachable!(),
            }
            assert_eq!(
                pc_bundle_candidate(&f.0),
                Err(LocateError::UnexpectedFile),
                "{sibling}: {kind}"
            );
        }
    }
}

// Red run 7 (2026-11-01): selecting this test exited 101. Discovery
// returned Ok(the executable candidate) for a file with the wrong prefix,
// rather than Err(UnexpectedFile). The layout-only scanner was insufficient.
#[test]
fn t2_discovery_verifies_the_file_before_returning_an_executable() {
    let f = Fixture::new();
    let candidate = f.file(format!(".mount_synthetic/{TAIL}"));
    f.running(".mount_synthetic", "101");
    fs::set_permissions(&candidate, fs::Permissions::from_mode(0o755)).unwrap();
    // Synthetic ownership is injected only in the test; the other metadata
    // and all file bytes and sibling checks are read from the private bundle.
    let discovery = f.discovery();
    assert_eq!(discovery.resolve(), Err(LocateError::UnexpectedFile));
    process::executable(&candidate, "#!/bin/sh\n\":\" //; exit 0\n");
    assert_eq!(discovery.resolve(), Ok(candidate.clone()));
    fs::set_permissions(&candidate, fs::Permissions::from_mode(0o777)).unwrap();
    assert_eq!(discovery.resolve(), Err(LocateError::UnexpectedFile));
    fs::set_permissions(&candidate, fs::Permissions::from_mode(0o755)).unwrap();
    let non_root = Discovery::pc(f.0.clone(), |m| LauncherMetadata {
        uid: 1000,
        mode: m.mode(),
    })
    .with_process_root(f.process_root());
    assert_eq!(non_root.resolve(), Err(LocateError::UnexpectedFile));
}

#[test]
fn t2_only_unique_running_bundle_identity_selects_a_launcher() {
    for state in [
        "none",
        "one",
        "same-mount-twice",
        "two-mounts",
        "name-only",
        "outside",
        "nested",
        "process-symlink",
    ] {
        let f = Fixture::new();
        let first = f.file(format!(".mount_synthetic_one/{TAIL}"));
        let second = f.file(format!(".mount_synthetic_two/{TAIL}"));
        for path in [&first, &second] {
            process::executable(path, "#!/bin/sh\n\":\" //; exit 0\n");
        }
        let proc = f.process_root();
        let expected = match state {
            "none" => Err(LocateError::NoRunningApp),
            "one" | "same-mount-twice" => {
                f.running(".mount_synthetic_one", "101");
                if state == "same-mount-twice" {
                    f.running(".mount_synthetic_one", "102");
                }
                Ok(first)
            }
            "two-mounts" => {
                f.running(".mount_synthetic_one", "101");
                f.running(".mount_synthetic_two", "102");
                Err(LocateError::Ambiguous)
            }
            "name-only" => {
                dirs::private_dir(proc.join("101")).unwrap();
                fs::write(proc.join("101/comm"), "Cloudroom\n").unwrap();
                fs::write(
                    proc.join("101/cmdline"),
                    first.as_os_str().as_encoded_bytes(),
                )
                .unwrap();
                Err(LocateError::NoRunningApp)
            }
            "process-symlink" => {
                f.running(".mount_synthetic_one", "101");
                std::os::unix::fs::symlink(proc.join("101"), proc.join("102")).unwrap();
                Err(LocateError::UnexpectedFile)
            }
            "outside" | "nested" => {
                let target = if state == "outside" {
                    f.file("bin/Cloudroom")
                } else {
                    f.file(".mount_synthetic_one/nested/Cloudroom")
                };
                fs::set_permissions(&target, fs::Permissions::from_mode(0o755)).unwrap();
                dirs::private_dir(proc.join("101")).unwrap();
                std::os::unix::fs::symlink(target, proc.join("101/exe")).unwrap();
                Err(LocateError::NoRunningApp)
            }
            _ => unreachable!(),
        };
        assert_eq!(f.discovery().resolve(), expected, "{state}");
    }
    // A lone stale mount is never enough, even if its name claims activity.
    let f = Fixture::new();
    let path = f.file(format!(".mount_active/{TAIL}"));
    process::executable(&path, "#!/bin/sh\n\":\" //; exit 0\n");
    assert_eq!(f.discovery().resolve(), Err(LocateError::NoRunningApp));
}

#[test]
fn t2_process_evidence_cannot_bypass_bundle_or_executable_checks() {
    for state in [
        "prefix",
        "owner",
        "app-owner",
        "writable",
        "app-writable",
        "not-executable",
        "app-symlink",
        "leaf-symlink",
        "mount-symlink",
        "component-symlink",
        "missing-sibling",
        "directory-sibling",
        "symlink-sibling",
    ] {
        let f = Fixture::new();
        let candidate = f.file(format!(".mount_synthetic/{TAIL}"));
        process::executable(&candidate, "#!/bin/sh\n\":\" //; exit 0\n");
        f.running(".mount_synthetic", "101");
        let app = f.0.join(".mount_synthetic/synthetic-app");
        match state {
            "prefix" => process::executable(&candidate, "#!/bin/bash\n\":\" //; exit 0\n"),
            "writable" | "app-writable" | "not-executable" => {
                let path = if state == "app-writable" {
                    &app
                } else {
                    &candidate
                };
                let mode = if state == "not-executable" {
                    0o644
                } else {
                    0o777
                };
                fs::set_permissions(path, fs::Permissions::from_mode(mode)).unwrap();
            }
            "app-symlink" | "leaf-symlink" | "mount-symlink" | "component-symlink" => {
                let path = match state {
                    "app-symlink" => app.clone(),
                    "leaf-symlink" => candidate.clone(),
                    "mount-symlink" => f.0.join(".mount_synthetic"),
                    _ => f.0.join(".mount_synthetic/resources"),
                };
                let target = f.0.join("relocated");
                fs::rename(&path, &target).unwrap();
                std::os::unix::fs::symlink(target, path).unwrap();
            }
            "missing-sibling" | "directory-sibling" | "symlink-sibling" => {
                let sibling = candidate.with_file_name("index.js");
                fs::remove_file(&sibling).unwrap();
                match state {
                    "directory-sibling" => dirs::private_dir(&sibling).unwrap(),
                    "symlink-sibling" => std::os::unix::fs::symlink(&app, sibling).unwrap(),
                    _ => {}
                }
            }
            _ => {}
        }
        // Distinct fixture modes let this non-capturing metadata seam
        // mutate the app or launcher owner independently.
        let metadata: fn(&fs::Metadata) -> LauncherMetadata = match state {
            "owner" => |m| LauncherMetadata {
                uid: if m.mode() & 0o777 == 0o755 { 1000 } else { 0 },
                mode: m.mode(),
            },
            "app-owner" => |m| LauncherMetadata {
                uid: if m.mode() & 0o777 == 0o555 { 1000 } else { 0 },
                mode: m.mode(),
            },
            _ => |m| LauncherMetadata {
                uid: 0,
                mode: m.mode(),
            },
        };
        let discovery = Discovery::pc(f.0.clone(), metadata).with_process_root(f.process_root());
        assert!(discovery.resolve().is_err(), "{state}");
    }
}

#[test]
fn t2_unreadable_active_bundle_is_distinct_from_no_running_bundle() {
    struct Restore(PathBuf);
    impl Drop for Restore {
        fn drop(&mut self) {
            fs::set_permissions(&self.0, fs::Permissions::from_mode(0o700)).unwrap();
        }
    }
    let f = Fixture::new();
    let candidate = f.file(format!(".mount_synthetic/{TAIL}"));
    process::executable(&candidate, "#!/bin/sh\n\":\" //; exit 0\n");
    f.running(".mount_synthetic", "101");
    let restore = Restore(f.0.join(".mount_synthetic/resources"));
    fs::set_permissions(&restore.0, fs::Permissions::from_mode(0o000)).unwrap();
    assert_eq!(f.discovery().resolve(), Err(LocateError::Unreadable));
}

fn ta3_launcher(f: &Fixture, mount: &str) -> PathBuf {
    let candidate = f.file(format!("{mount}/{TAIL}"));
    process::executable(
        &candidate,
        &format!(
            "#!/bin/sh\n\":\" //; printf called > '{}'\nexit 97\n",
            f.0.join("unexpected-call").display()
        ),
    );
    candidate
}

#[test]
fn ta3_non_pid_entries_never_hide_or_select_a_launcher() {
    for name in ["status", "0123", "0", "leading-zero-app", "canonical-pid"] {
        let f = Fixture::new();
        let candidate = ta3_launcher(&f, ".mount_synthetic");
        f.running(".mount_synthetic", "101");
        if name == "leading-zero-app" || name == "canonical-pid" {
            ta3_launcher(&f, ".mount_synthetic_two");
            f.running(
                ".mount_synthetic_two",
                if name == "canonical-pid" {
                    "123"
                } else {
                    "0123"
                },
            );
        } else {
            f.file(format!("proc/{name}"));
        }
        let expected = if name == "canonical-pid" {
            Err(LocateError::Ambiguous)
        } else {
            Ok(candidate)
        };
        assert_eq!(f.discovery().resolve(), expected, "{name}");
        assert!(!f.0.join("unexpected-call").exists());
    }
}

#[test]
fn ta3_running_app_requires_execute_bits_independently() {
    for (mode, accepted) in [(0o644, false), (0o444, false), (0o555, true), (0o755, true)] {
        let f = Fixture::new();
        let candidate = ta3_launcher(&f, ".mount_synthetic");
        f.running(".mount_synthetic", "101");
        fs::set_permissions(
            f.0.join(".mount_synthetic/synthetic-app"),
            fs::Permissions::from_mode(mode),
        )
        .unwrap();
        assert_eq!(
            f.discovery().resolve(),
            if accepted {
                Ok(candidate)
            } else {
                Err(LocateError::UnexpectedFile)
            },
            "mode {mode:o}"
        );
        assert!(!f.0.join("unexpected-call").exists());
    }
}

// #1677/#1679: inject OS results only in a separate process, and judge the
// public resolver's result. The parent test's environment is never changed.
#[cfg(target_os = "linux")]
#[test]
fn ta3_locate_faults_preserve_errors_and_executable_identity() {
    use std::process::Command;
    let compiler_fixture = Fixture::new();
    let library = compiler_fixture.0.join("locate-faults.so");
    let compile = Command::new("cc")
        .args(["-shared", "-fPIC", "-Wall", "-Wextra", "-Werror"])
        .arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/locate-faults.c"))
        .arg("-o")
        .arg(&library)
        .arg("-ldl")
        .output()
        .unwrap();
    assert!(
        compile.status.success(),
        "{}",
        String::from_utf8_lossy(&compile.stderr)
    );
    // Exact fixture paths and occurrences describe external filesystem
    // evidence, not a count or shape of production implementation calls.
    for (op, leaf, occurrence, fault, expected) in [
        ("statx", "proc/102", "1", "missing", "selected"),
        ("statx", "proc/102", "1", "io", "unreadable"),
        ("statx", "proc/102", "1", "denied", "unreadable"),
        ("readlink", "proc/102/exe", "1", "missing", "selected"),
        ("readlink", "proc/102/exe", "1", "denied", "selected"),
        ("readlink", "proc/102/exe", "1", "invalid", "unexpected"),
        ("readlink", "proc/102/exe", "1", "io", "unreadable"),
        (
            "statx",
            ".mount_synthetic_two/synthetic-app",
            "1",
            "missing",
            "selected",
        ),
        (
            "statx",
            ".mount_synthetic_two/synthetic-app",
            "1",
            "io",
            "unreadable",
        ),
        ("readlink", "proc/102/exe", "2", "missing", "selected"),
        ("readlink", "proc/102/exe", "2", "io", "unreadable"),
        ("statx", "proc/102/exe", "1", "same", "ambiguous"),
        ("statx", "proc/102/exe", "1", "inode", "unexpected"),
        ("statx", "proc/102/exe", "1", "device", "unexpected"),
        ("statx", "proc/102/exe", "1", "device-inode", "unexpected"),
    ] {
        let f = Fixture::new();
        for (mount, pid) in [(".mount_synthetic", "101"), (".mount_synthetic_two", "102")] {
            ta3_launcher(&f, mount);
            f.running(mount, pid);
        }
        let log = f.0.join("fault-hit");
        let output = Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "t2_locate::ta3_locate_fault_worker",
                "--nocapture",
            ])
            .env("LD_PRELOAD", &library)
            .env("synthetic_locate_root", &f.0)
            .env("synthetic_locate_op", format!("synthetic-{op}"))
            .env("synthetic_locate_path", f.0.join(leaf))
            .env("synthetic_locate_occurrence", occurrence)
            .env("synthetic_locate_fault", format!("synthetic-{fault}"))
            .env("synthetic_locate_log", &log)
            .env("synthetic_locate_expected", expected)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{op} {leaf} occurrence {occurrence} {fault}:\n{}\n{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
    }
    let f = Fixture::new();
    let candidate = f.file(format!(".mount_synthetic/{TAIL}"));
    process::executable(&candidate, "#!/bin/sh\n\":\" //; exit 97\n");
    f.running(".mount_synthetic", "101");
    assert_eq!(f.discovery().resolve(), Ok(candidate));
    // A real non-symlink exe is malformed evidence, not an I/O failure.
    fs::remove_file(f.process_root().join("101/exe")).unwrap();
    f.file("proc/101/exe");
    assert_eq!(f.discovery().resolve(), Err(LocateError::UnexpectedFile));
}

#[cfg(target_os = "linux")]
#[test]
fn ta3_locate_fault_worker() {
    let Some(root) = std::env::var_os("synthetic_locate_root") else {
        return;
    };
    let root = PathBuf::from(root);
    let discovery = Discovery::pc(root.clone(), |m| LauncherMetadata {
        uid: 0,
        mode: m.mode(),
    })
    .with_process_root(root.join("proc"));
    let result = discovery.resolve();
    assert!(!root.join("unexpected-call").exists());
    let fault = std::env::var("synthetic_locate_fault").unwrap();
    let fault = fault.strip_prefix("synthetic-").unwrap();
    let log = fs::read_to_string(std::env::var_os("synthetic_locate_log").unwrap())
        .expect("the actual Rust/libc syscall hook must be hit");
    assert_eq!(log.lines().count(), 1, "exactly one injected result: {log}");
    if ["same", "inode", "device", "device-inode"].contains(&fault) {
        let fields: Vec<u64> = log
            .strip_prefix("synthetic ")
            .unwrap()
            .split_whitespace()
            .map(|n| n.parse().unwrap())
            .collect();
        assert_eq!(fields.len(), 4);
        assert_eq!(fields[0] != fields[2], fault.contains("device"));
        assert_eq!(fields[1] != fields[3], fault.contains("inode"));
    } else {
        assert_eq!(log, format!("synthetic-{fault}\n"));
    }
    let expected = match std::env::var("synthetic_locate_expected").unwrap().as_str() {
        "selected" => Ok(root.join(format!(".mount_synthetic/{TAIL}"))),
        "ambiguous" => Err(LocateError::Ambiguous),
        "unreadable" => Err(LocateError::Unreadable),
        "unexpected" => Err(LocateError::UnexpectedFile),
        other => panic!("unknown fixture verdict {other}"),
    };
    assert_eq!(result, expected, "{fault}");
}
