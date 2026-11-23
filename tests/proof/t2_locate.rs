use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};

use openwiz_adapter_cloudroom::locate::{
    Discovery, LauncherMetadata, LocateError, check_launcher_markers, pc_bundle_candidate,
};
use std::os::unix::fs::{MetadataExt, PermissionsExt};

use crate::dirs;

#[path = "../support/place.rs"]
mod place;

mod process {
    use std::os::unix::fs::PermissionsExt;
    use std::path::Path;

    use super::place::place_script;

    pub(super) fn executable(path: &Path, script: &str) {
        place_script(path, script);
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755)).unwrap();
    }
}

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
        fs::write(&path, "synthetic unverified candidate\n").unwrap();
        if path.file_name().is_some_and(|name| name == "room-cli") {
            for sibling in ["daemon-bundle.mjs", "index.js"] {
                fs::write(path.with_file_name(sibling), "synthetic sibling\n").unwrap();
            }
        }
        path
    }

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

#[test]
fn t2_discovery_verifies_the_file_before_returning_an_executable() {
    let f = Fixture::new();
    let candidate = f.file(format!(".mount_synthetic/{TAIL}"));
    f.running(".mount_synthetic", "101");
    fs::set_permissions(&candidate, fs::Permissions::from_mode(0o755)).unwrap();
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

fn path_launcher(f: &Fixture, dir: &str, mode: u32) -> PathBuf {
    let launcher = f.0.join(dir).join("room-cli");
    dirs::private_dir_all(launcher.parent().unwrap()).unwrap();
    process::executable(&launcher, "#!/bin/sh\nexit 0\n");
    fs::set_permissions(&launcher, fs::Permissions::from_mode(mode)).unwrap();
    launcher
}

fn relative_to_current_dir(path: &Path) -> PathBuf {
    let up = std::env::current_dir().unwrap().components().count() - 1;
    let mut relative: PathBuf = std::iter::repeat_n("..", up).collect();
    relative.push(path.strip_prefix("/").unwrap());
    relative
}

#[test]
fn t2_room_cli_on_path_is_found_when_no_bundle_is() {
    use openwiz_adapter_cloudroom::locate::{Basis, Located};
    for mounts in 0..=1 {
        let f = Fixture::new();
        for index in 0..mounts {
            let launcher = f.file(format!(".mount_synthetic_{index}/{TAIL}"));
            process::executable(&launcher, "#!/bin/sh\n\":\" //; exit 0\n");
        }
        let relative = path_launcher(&f, "relative-bin", 0o755);
        path_launcher(&f, "plain-file-bin", 0o644);
        path_launcher(&f, "writable-bin", 0o777);
        let expected = path_launcher(&f, "bin", 0o755);
        let search = std::env::join_paths([
            relative_to_current_dir(relative.parent().unwrap()),
            f.0.join("empty-bin"),
            f.0.join("plain-file-bin"),
            f.0.join("writable-bin"),
            f.0.join("bin"),
        ])
        .unwrap();
        assert_eq!(
            f.discovery().with_search_path(search).locate(),
            Ok(Located {
                launcher: expected,
                basis: Basis::Path
            }),
            "{mounts} mounts"
        );
    }
}

#[test]
fn t2_a_running_bundle_or_a_refused_one_is_never_replaced_from_path() {
    let f = Fixture::new();
    path_launcher(&f, "bin", 0o755);
    let search = f.0.join("bin").into_os_string();
    let active = f.file(format!(".mount_synthetic_active/{TAIL}"));
    process::executable(&active, "#!/bin/sh\n\":\" //; exit 0\n");
    f.running(".mount_synthetic_active", "101");
    assert_eq!(
        f.discovery().with_search_path(search.clone()).resolve(),
        Ok(active)
    );
    let other = f.file(format!(".mount_synthetic_other/{TAIL}"));
    process::executable(&other, "#!/bin/sh\n\":\" //; exit 0\n");
    f.running(".mount_synthetic_other", "102");
    assert_eq!(
        f.discovery().with_search_path(search).resolve(),
        Err(LocateError::Ambiguous)
    );
}

#[test]
fn t2_room_cli_missing_everywhere_says_to_open_cloudroom_once() {
    use openwiz_core::{ops::launch_failure_category, source::SourceError};
    for (mounts, error, reason, category) in [
        (
            0,
            LocateError::NotRunning,
            "no bundled launcher and no room-cli on PATH",
            "no bundle",
        ),
        (
            1,
            LocateError::NoRunningApp,
            "no running app identified",
            "no running app identified",
        ),
    ] {
        let f = Fixture::new();
        for index in 0..mounts {
            let launcher = f.file(format!(".mount_synthetic_stale_{index}/{TAIL}"));
            process::executable(&launcher, "#!/bin/sh\n\":\" //; exit 0\n");
        }
        let got = f
            .discovery()
            .with_search_path(f.0.join("empty-bin").into_os_string())
            .resolve()
            .unwrap_err();
        assert_eq!(got, error);
        let SourceError::Unavailable { detail } = got.into() else {
            panic!("a missing room-cli is unavailable");
        };
        assert_eq!(
            detail,
            format!(
                "CloudRoom not running: room-cli could not be started ({reason}). \
                 Open the CloudRoom app once and sign in."
            )
        );
        assert_eq!(launch_failure_category(&detail), Some(category));
    }
}

#[test]
fn t2_a_path_room_cli_the_caller_cannot_run_does_not_hide_a_later_one() {
    use std::process::Command;
    let f = Fixture::new();
    let denied = path_launcher(&f, "denied-bin", 0o601);
    let runnable = f.0.join("bin/room-cli");
    dirs::private_dir_all(runnable.parent().unwrap()).unwrap();
    process::executable(&runnable, "#!/bin/sh\nprintf 'v999\\n'\n");
    assert_eq!(
        Command::new(&denied).status().unwrap_err().kind(),
        std::io::ErrorKind::PermissionDenied,
        "the fixture's first room-cli must be refused to this caller"
    );
    let search = std::env::join_paths([f.0.join("denied-bin"), f.0.join("bin")]).unwrap();
    let output = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "t2_locate::t2_path_launch_worker", "--nocapture"])
        .env("synthetic_path_root", &f.0)
        .env("synthetic_path_search", search)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn t2_path_launch_worker() {
    use openwiz_adapter_cloudroom::{locate, source::CloudRoomSource};
    use openwiz_core::source::SessionSource;
    let (Some(root), Some(search)) = (
        std::env::var_os("synthetic_path_root"),
        std::env::var_os("synthetic_path_search"),
    ) else {
        return;
    };
    let root = PathBuf::from(root);
    locate::install(
        Discovery::pc(root.clone(), |m| LauncherMetadata {
            uid: 0,
            mode: m.mode(),
        })
        .with_process_root(root.join("proc"))
        .with_search_path(search),
    )
    .unwrap();
    dirs::private_dir_all(root.join("proc/self")).unwrap();
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
    assert_eq!(
        CloudRoomSource::from_path().version(deadline),
        Ok("v999".to_owned())
    );
}
