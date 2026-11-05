//! State-path guards, on private synthetic directories only.
#![cfg(target_os = "linux")]
use std::fs::{self, DirBuilder};
use std::os::unix::fs::{DirBuilderExt, PermissionsExt, symlink};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "openwiz-t4-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        DirBuilder::new().mode(0o700).create(&path).unwrap();
        DirBuilder::new()
            .mode(0o700)
            .create(path.join("service"))
            .unwrap();
        fs::write(path.join("service/config.json"), "synthetic config bytes").unwrap();
        fs::set_permissions(
            path.join("service/config.json"),
            fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        Self(path)
    }
    fn file(&self, suffix: &str) -> PathBuf {
        self.0.join("service").join(suffix)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
fn service_private_paths_preserve_original_cases() {
    let cases: [(&str, fn()); 7] = [
        (
            "every_named_sensitive_path_refuses_symlinks_and_public_modes",
            every_named_sensitive_path_refuses_symlinks_and_public_modes,
        ),
        (
            "inspecting_paths_is_read_only_and_requires_private_real_paths",
            inspecting_paths_is_read_only_and_requires_private_real_paths,
        ),
        (
            "private_owner_probe_derives_kernel_identity_and_leaves_no_state",
            private_owner_probe_derives_kernel_identity_and_leaves_no_state,
        ),
        (
            "private_owner_probe_refuses_unsafe_roots_before_writing",
            private_owner_probe_refuses_unsafe_roots_before_writing,
        ),
        (
            "sensitive_config_refuses_a_nested_service_repository",
            sensitive_config_refuses_a_nested_service_repository,
        ),
        (
            "sensitive_state_refuses_hard_links",
            sensitive_state_refuses_hard_links,
        ),
        (
            "state_cannot_live_in_a_repository_or_behind_a_symlink",
            state_cannot_live_in_a_repository_or_behind_a_symlink,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: {name}");
        proof();
    }
}

fn inspecting_paths_is_read_only_and_requires_private_real_paths() {
    let f = Fixture::new();
    assert!(openwiz_service::paths::inspect(&f.0).is_ok());
    assert_eq!(
        fs::read(f.file("config.json")).unwrap(),
        b"synthetic config bytes"
    );
    assert_eq!(fs::read_dir(f.0.join("service")).unwrap().count(), 1);
    assert!(openwiz_service::paths::inspect(Path::new("relative")).is_err());
    for (path, mode) in [
        (&f.0, 0o755),
        (&f.0.join("service"), 0o750),
        (&f.file("config.json"), 0o644),
    ] {
        fs::set_permissions(path, fs::Permissions::from_mode(mode)).unwrap();
        assert!(openwiz_service::paths::inspect(&f.0).is_err());
        fs::set_permissions(
            path,
            fs::Permissions::from_mode(if path.is_dir() { 0o700 } else { 0o600 }),
        )
        .unwrap();
    }
}

fn every_named_sensitive_path_refuses_symlinks_and_public_modes() {
    for (suffix, directory) in [
        ("state.json", false),
        ("app", true),
        ("app/private-key.pem", false),
        ("clone", true),
        ("builds", true),
    ] {
        let f = Fixture::new();
        let path = f.file(suffix);
        if suffix.contains('/') {
            DirBuilder::new()
                .mode(0o700)
                .create(path.parent().unwrap())
                .unwrap();
        }
        if directory {
            DirBuilder::new().mode(0o700).create(&path).unwrap();
        } else {
            fs::write(&path, "synthetic-secret-marker").unwrap();
            fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        }
        assert!(openwiz_service::paths::inspect(&f.0).is_ok(), "{suffix}");
        fs::set_permissions(
            &path,
            fs::Permissions::from_mode(if directory { 0o755 } else { 0o644 }),
        )
        .unwrap();
        let error = openwiz_service::paths::inspect(&f.0).unwrap_err();
        assert!(error.contains(suffix));
        assert!(!error.contains("synthetic-secret-marker"));
        fs::set_permissions(
            &path,
            fs::Permissions::from_mode(if directory { 0o700 } else { 0o600 }),
        )
        .unwrap();
        let target = f.0.join("synthetic-target");
        fs::rename(&path, &target).unwrap();
        symlink(&target, &path).unwrap();
        assert!(openwiz_service::paths::inspect(&f.0).is_err(), "{suffix}");
    }
}

fn state_cannot_live_in_a_repository_or_behind_a_symlink() {
    let f = Fixture::new();
    DirBuilder::new()
        .mode(0o700)
        .create(f.0.join(".git"))
        .unwrap();
    assert!(openwiz_service::paths::inspect(&f.0).is_err());
    fs::remove_dir(f.0.join(".git")).unwrap();
    let alias = f.0.join("alias");
    symlink(f.0.join("service"), &alias).unwrap();
    assert!(openwiz_service::paths::inspect(&alias).is_err());
    fs::remove_file(alias).unwrap();
    fs::remove_file(f.file("config.json")).unwrap();
    assert!(openwiz_service::paths::inspect(&f.0).is_err());
}

fn sensitive_state_refuses_hard_links() {
    let f = Fixture::new();
    fs::hard_link(f.file("config.json"), f.0.join("other-config")).unwrap();
    assert!(
        openwiz_service::paths::inspect(&f.0).is_err(),
        "multiply linked config must not cross the private boundary"
    );
}

fn sensitive_config_refuses_a_nested_service_repository() {
    let f = Fixture::new();
    fs::write(f.file(".git"), "gitdir: synthetic-only").unwrap();
    assert!(
        openwiz_service::paths::inspect(&f.0).is_err(),
        "the config and key must remain outside nested repositories too"
    );
}

fn private_owner_probe_derives_kernel_identity_and_leaves_no_state() {
    use std::os::unix::fs::MetadataExt;
    let f = Fixture::new();
    let before = fs::read_dir(&f.0)
        .unwrap()
        .map(|e| e.unwrap().file_name())
        .collect::<Vec<_>>();
    for _ in 0..2 {
        let uid = openwiz_store::attachments::owner_uid_from_private_state(&f.0).unwrap();
        assert_eq!(uid, fs::metadata("/proc/self").unwrap().uid());
        assert_eq!(
            fs::read(f.file("config.json")).unwrap(),
            b"synthetic config bytes"
        );
        let after = fs::read_dir(&f.0)
            .unwrap()
            .map(|e| e.unwrap().file_name())
            .collect::<Vec<_>>();
        assert_eq!(
            after, before,
            "the probe must remove only its own temporary file"
        );
    }
}

fn private_owner_probe_refuses_unsafe_roots_before_writing() {
    let f = Fixture::new();
    let probe = openwiz_store::attachments::owner_uid_from_private_state;
    assert!(probe(Path::new("relative")).is_err());
    assert!(probe(&f.file("config.json")).is_err());
    fs::set_permissions(&f.0, fs::Permissions::from_mode(0o755)).unwrap();
    assert!(probe(&f.0).is_err());
    fs::set_permissions(&f.0, fs::Permissions::from_mode(0o700)).unwrap();
    let nested = f.file("nested");
    DirBuilder::new().mode(0o700).create(&nested).unwrap();
    let alias = f.0.join("alias");
    symlink(f.0.join("service"), &alias).unwrap();
    assert!(probe(&alias.join("nested")).is_err());
    assert_eq!(fs::read_dir(&nested).unwrap().count(), 0);
    fs::write(f.0.join(".git"), "gitdir: synthetic-only").unwrap();
    assert!(probe(&f.0).is_err());
    assert_eq!(fs::read_dir(&f.0).unwrap().count(), 3);
}
