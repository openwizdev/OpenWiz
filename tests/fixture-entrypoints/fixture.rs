use openwiz_adapter_cloudroom::locate::{Discovery, LauncherMetadata};
use std::fs;
use std::os::unix::fs::{DirBuilderExt, MetadataExt, PermissionsExt};
use std::path::PathBuf;

mod dirs {
    use super::*;
    pub fn private_dir_all(path: &std::path::Path) -> std::io::Result<()> {
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(path)
    }
    pub fn private_dir(path: &std::path::Path) -> std::io::Result<()> {
        fs::DirBuilder::new().mode(0o700).create(path)
    }
}

pub struct Bundle {
    root: PathBuf,
    cleanup: bool,
}

fn lower_read_timeout_from_environment() {
    let Some(value) = std::env::var_os("OPENWIZ_FIXTURE_READ_TIMEOUT_MS") else {
        return;
    };
    let ms = value
        .to_str()
        .filter(|v| !v.is_empty() && v.len() <= 5 && v.bytes().all(|b| b.is_ascii_digit()))
        .and_then(|v| v.parse::<u64>().ok())
        .filter(|ms| (1..=15_000).contains(ms))
        .unwrap_or_else(|| panic!("OPENWIZ_FIXTURE_READ_TIMEOUT_MS is not 1 to 15000: {value:?}"));
    openwiz_adapter_cloudroom::source::lower_read_timeout_for_fixtures(
        std::time::Duration::from_millis(ms),
    );
}

impl Bundle {
    pub fn from_environment() -> Self {
        lower_read_timeout_from_environment();
        openwiz_adapter_cloudroom::source::use_fast_polling_for_fixtures();
        if let Some(root) = std::env::var_os("OPENWIZ_FIXTURE_ROOT") {
            let root = PathBuf::from(root);
            assert!(root.is_absolute());
            return Self {
                root,
                cleanup: false,
            };
        }
        let program = std::env::var_os("OPENWIZ_FIXTURE_PROGRAM").map(PathBuf::from);
        let parent = program
            .as_ref()
            .map(|p| {
                assert!(p.is_absolute());
                p.parent().unwrap().with_extension("fixture-bundles")
            })
            .unwrap_or_else(|| std::env::temp_dir().join("openwiz-fixture-bundles"));
        dirs::private_dir_all(&parent).unwrap();
        let mut suffix = 0u64;
        let root = loop {
            let root = parent.join(format!("{}-{suffix}", std::process::id()));
            match dirs::private_dir(&root) {
                Ok(()) => break root,
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => suffix += 1,
                Err(error) => panic!("private fixture directory: {error}"),
            }
        };
        let proc = root.join("proc");
        dirs::private_dir_all(&proc.join("self")).unwrap();
        if let Some(program) = program {
            let dist = root.join(
                ".mount_synthetic/resources/app.asar.unpacked/node_modules/bb-app/host-daemon/dist",
            );
            dirs::private_dir_all(&dist).unwrap();
            let quoted = program.to_str().unwrap().replace('\'', "'\\''");
            let launcher = dist.join("room-cli");
            fs::write(
                &launcher,
                format!("#!/bin/sh\n\":\" //; exec '{quoted}' \"$@\"\n"),
            )
            .unwrap();
            fs::set_permissions(&launcher, fs::Permissions::from_mode(0o755)).unwrap();
            for name in ["daemon-bundle.mjs", "index.js"] {
                fs::write(dist.join(name), "synthetic sibling\n").unwrap();
            }
            let app = root.join(".mount_synthetic/synthetic-app");
            fs::write(&app, "synthetic process executable, never run\n").unwrap();
            fs::set_permissions(&app, fs::Permissions::from_mode(0o555)).unwrap();
            dirs::private_dir(&proc.join("101")).unwrap();
            std::os::unix::fs::symlink(app, proc.join("101/exe")).unwrap();
        }
        Self {
            root,
            cleanup: true,
        }
    }

    pub fn discovery(&self) -> Discovery {
        Discovery::pc(self.root.clone(), |m| LauncherMetadata {
            uid: 0,
            mode: m.mode(),
        })
        .with_process_root(self.root.join("proc"))
    }
}

impl Drop for Bundle {
    fn drop(&mut self) {
        if self.cleanup {
            let _ = fs::remove_dir_all(&self.root);
        }
    }
}
