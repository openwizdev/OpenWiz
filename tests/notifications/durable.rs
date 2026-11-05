//! PA2/PA3/PA5: durable owner choices, journal identity and failure boundaries.
use openwiz_core::notifications::model::*;
use openwiz_store::notifications::{Error, Store};
use std::{
    fs,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

pub struct Private(pub PathBuf);
impl Private {
    pub fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "openwiz-notifications-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(root.join("service"))
            .unwrap();
        fs::write(root.join("service/config.json"), "{}").unwrap();
        fs::set_permissions(
            root.join("service/config.json"),
            fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        Self(root)
    }
}
impl Drop for Private {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn write() -> PreferenceWrite {
    PreferenceWrite {
        operation_id: OperationId::new("1".repeat(32)).unwrap(),
        expected_generation: 0,
        enabled: true,
        categories: Toggles::defaults(),
    }
}

#[test]
fn preferences_persist_and_operation_identity_binds_exact_write() {
    let private = Private::new();
    let store = Store::new(&private.0);
    store.initialize().unwrap();
    assert_eq!(store.preferences().unwrap(), Preferences::off());
    let request = write();
    let saved = store.write_preferences(&request, 100_000).unwrap();
    assert!(saved.enabled, "explicit enable must be retained");
    assert_eq!(saved.generation, 1);
    let reopened = Store::new(&private.0);
    assert_eq!(reopened.preferences().unwrap(), saved);
    assert_eq!(
        reopened.write_preferences(&request, 100_001).unwrap(),
        saved
    );
    let mut conflict = request.clone();
    conflict.enabled = false;
    assert_eq!(
        reopened.write_preferences(&conflict, 100_002),
        Err(Error::OperationConflict)
    );
    conflict.operation_id = OperationId::new("2".repeat(32)).unwrap();
    assert_eq!(
        reopened.write_preferences(&conflict, 100_002),
        Err(Error::GenerationConflict)
    );
    conflict.expected_generation = 1;
    let disabled = reopened.write_preferences(&conflict, 100_002).unwrap();
    assert!(!disabled.enabled);
    assert_eq!(disabled.generation, 2);
    assert_eq!(
        reopened.write_preferences(&request, 100_003).unwrap(),
        saved
    );
    assert_eq!(
        reopened.preferences().unwrap(),
        disabled,
        "replay returns original receipt, never reapplies old enable"
    );
}

#[test]
fn every_optional_toggle_is_independent_and_survives_restart() {
    let private = Private::new();
    let store = Store::new(&private.0);
    store.initialize().unwrap();
    let defaults = serde_json::to_value(Toggles::defaults()).unwrap();
    let mut generation = 0;
    for (i, (category, default)) in defaults.as_object().unwrap().iter().enumerate() {
        let mut value = defaults.clone();
        value[category] = serde_json::json!(!default.as_bool().unwrap());
        let toggles: Toggles = serde_json::from_value(value).unwrap();
        let request = PreferenceWrite {
            operation_id: OperationId::new(format!("{:032x}", i + 1)).unwrap(),
            expected_generation: generation,
            enabled: false,
            categories: toggles.clone(),
        };
        let saved = store.write_preferences(&request, 100_000).unwrap();
        generation += 1;
        assert!(!saved.enabled);
        assert_eq!(saved.categories, toggles);
        assert_eq!(saved.generation, generation);
        assert_eq!(Store::new(&private.0).preferences().unwrap(), saved);
    }
}

#[test]
fn missing_malformed_unprotected_or_substituted_state_refuses_reads_and_writes() {
    use std::os::unix::fs::symlink;
    let private = Private::new();
    let store = Store::new(&private.0);
    assert_eq!(store.preferences(), Err(Error::Unavailable));
    assert_eq!(
        store.write_preferences(&write(), 100_000),
        Err(Error::Unavailable)
    );
    store.initialize().unwrap();
    let state = private.0.join("service/notifications/state.json");
    let valid = fs::read_to_string(&state).unwrap();
    for body in [
        "{}".to_string(),
        valid.replacen("\"schema\":", "\"schema\":\"bad\",\"schema\":", 1),
        valid.replacen("\"generation\":0", "\"generation\":0.0", 1),
        valid.replacen("\"enabled\":false", "\"enabled\":false,\"extra\":1", 1),
    ] {
        fs::write(&state, body).unwrap();
        assert_eq!(store.preferences(), Err(Error::Unavailable));
        assert_eq!(
            store.write_preferences(&write(), 100_000),
            Err(Error::Unavailable)
        );
    }
    fs::write(&state, &valid).unwrap();
    fs::set_permissions(&state, fs::Permissions::from_mode(0o644)).unwrap();
    assert_eq!(store.preferences(), Err(Error::Unavailable));
    fs::set_permissions(&state, fs::Permissions::from_mode(0o600)).unwrap();
    fs::rename(&state, state.with_extension("backup")).unwrap();
    symlink(state.with_extension("backup"), &state).unwrap();
    assert_eq!(store.preferences(), Err(Error::Unavailable));
    fs::remove_file(&state).unwrap();
    assert_eq!(store.preferences(), Err(Error::Unavailable));
    assert_eq!(
        store.initialize(),
        Err(Error::Unavailable),
        "missing journal cannot reset durable identity"
    );
}

#[test]
fn subscription_generation_method_and_binding_identity_are_once_only() {
    let private = Private::new();
    let store = Store::new(&private.0);
    store.initialize().unwrap();
    let request = SubscriptionWrite {
        operation_id: OperationId::new("3".repeat(32)).unwrap(),
        expected_generation: 0,
        binding_id: Id::new("synthetic-binding").unwrap(),
    };
    assert_eq!(
        store.write_subscription(&request, false, 100_000, |_| false),
        Err(Error::SubscriptionUnavailable)
    );
    let registered = store
        .write_subscription(&request, false, 100_000, |_| true)
        .unwrap();
    assert_eq!(registered.generation, 1);
    assert_eq!(
        store.write_subscription(&request, false, 100_001, |_| panic!(
            "replay must reuse receipt"
        )),
        Ok(registered.clone())
    );
    assert_eq!(
        store.write_subscription(&request, true, 100_001, |_| true),
        Err(Error::OperationConflict)
    );
    let mut remove = request.clone();
    remove.operation_id = OperationId::new("4".repeat(32)).unwrap();
    remove.expected_generation = 1;
    remove.binding_id = Id::new("another-binding").unwrap();
    assert_eq!(
        store.write_subscription(&remove, true, 100_002, |_| true),
        Err(Error::SubscriptionUnavailable)
    );
    remove.binding_id = request.binding_id.clone();
    let revoked = store
        .write_subscription(&remove, true, 100_002, |_| {
            panic!("local removal makes no provider call")
        })
        .unwrap();
    assert_eq!(revoked.state, SubscriptionState::Revoked);
    assert_eq!(revoked.generation, 2);
    assert!(revoked.binding_id.is_none());
    assert_eq!(
        store
            .write_subscription(&request, false, 100_003, |_| true)
            .unwrap(),
        registered
    );
    assert_eq!(store.read().unwrap().subscription, revoked);
}
