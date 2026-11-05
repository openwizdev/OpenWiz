//! Existing configured target file boundary, with synthetic private documents.
use super::configured_target;
use serde_json::{Value, json};
use std::{
    fs,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

struct Private(PathBuf);
impl Private {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "openwiz-target-read-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(root.join("service"))
            .unwrap();
        Self(root)
    }
    fn write(&self, bytes: impl AsRef<[u8]>) {
        let file = self.0.join("service/config.json");
        fs::write(&file, bytes).unwrap();
        fs::set_permissions(file, fs::Permissions::from_mode(0o600)).unwrap();
    }
}
impl Drop for Private {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
fn failed_configured_target_read_is_an_error_not_absence_or_a_diagnostic() {
    let root = Private::new();
    assert_eq!(
        configured_target(&root.0),
        Err(()),
        "missing config remains unknown"
    );
    let path = root.0.join("service/config.json");
    fs::DirBuilder::new().mode(0o700).create(&path).unwrap();
    assert_eq!(
        configured_target(&root.0),
        Err(()),
        "failed file read remains unknown"
    );
    fs::remove_dir(path).unwrap();
    for raw in [
        b"SYNTHETIC_PRIVATE_DIAGNOSTIC /synthetic/private".as_slice(),
        b"\xff".as_slice(),
        b"{}".as_slice(),
        b"[]".as_slice(),
    ] {
        root.write(raw);
        assert_eq!(
            configured_target(&root.0),
            Err(()),
            "invalid config retains only the opaque error"
        );
    }
}

#[test]
fn configured_target_requires_the_valid_explicit_document() {
    let root = Private::new();
    let mut config: Value = include_str!("../../contracts/service.v1.md")
        .lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .find(|value| value["schema"] == "openwiz.service-config.v1")
        .unwrap();
    config["orchestrator_thread"] = json!("thr_syn_selected_target");
    root.write(config.to_string());
    assert_eq!(
        configured_target(&root.0),
        Ok(Some("thr_syn_selected_target".into()))
    );
    for bad in [
        Value::Null,
        json!("-synthetic"),
        json!(""),
        json!({"known":"thr_syn_selected_target"}),
    ] {
        config["orchestrator_thread"] = bad;
        root.write(config.to_string());
        assert_eq!(configured_target(&root.0), Err(()));
    }
    config
        .as_object_mut()
        .unwrap()
        .remove("orchestrator_thread");
    root.write(config.to_string());
    assert_eq!(
        configured_target(&root.0),
        Err(()),
        "missing required target is not an unconfigured success"
    );
}
