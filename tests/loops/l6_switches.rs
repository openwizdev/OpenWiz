use super::fixture::{Fixture, git};
use openwiz_cli::state::loops::Trust;
use serde_json::json;
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::Path,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
};

#[test]
fn off_and_on_save_exact_operator_time_and_identity_across_reopen() {
    let f = Fixture::new();
    let off = f
        .context
        .switch("Synthetic reminder (example only)", false, 1000)
        .expect("off must save its audited switch");
    assert_eq!(off["loop_id"], "loop-syn-reminder");
    assert_eq!(off["enabled"], false);
    assert_eq!(off["actor"], "synthetic-operator");
    assert_eq!(off["at_ms"], 1000);
    let reopened = f.context.clone();
    let on = reopened.switch("loop-syn-reminder", true, 2000).unwrap();
    let saved = f.saved();
    assert_eq!(saved["enabled"]["loop-syn-reminder"], true);
    assert_eq!(saved["events"], json!([off, on]));
    assert_eq!(
        fs::metadata(f.context.state.join("service/loops/enabled.json"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
}

struct Identity {
    verified: bool,
    actor: Option<String>,
}
impl Trust for Identity {
    fn verify(&self, _: &Path, _: &str, _: &str) -> bool {
        self.verified
    }
    fn actor(&self) -> Option<String> {
        self.actor.clone()
    }
}
#[test]
fn foreign_unknown_ambiguous_and_untrusted_targets_never_change_switches() {
    let mut f = Fixture::new();
    f.context.switch("loop-syn-reminder", false, 1000).unwrap();
    let before = f.saved();
    for target in [
        "",
        " ",
        "unknown",
        "cloudroom-owned-loop",
        "loop-syn-reminder/other",
        "loop-syn-reminder\0",
    ] {
        assert!(f.context.switch(target, true, 2000).is_err(), "{target:?}");
        assert_eq!(f.saved(), before);
    }
    for actor in [None, Some(""), Some("  "), Some("\0")] {
        let mut context = f.context.clone();
        context.trust = Some(Arc::new(Identity {
            verified: true,
            actor: actor.map(str::to_owned),
        }));
        assert!(context.switch("loop-syn-reminder", true, 2000).is_err());
        assert_eq!(f.saved(), before);
    }
    let mut context = f.context.clone();
    context.trust = None;
    assert!(context.switch("loop-syn-reminder", true, 2000).is_err());
    context.trust = Some(Arc::new(Identity {
        verified: false,
        actor: Some("synthetic-operator".to_owned()),
    }));
    assert!(context.switch("loop-syn-reminder", true, 2000).is_err());
    for (key, value) in [
        ("repository", "foreign-owner/foreign-repo"),
        ("project", "prj_syn_foreign"),
    ] {
        let mut context = f.context.clone();
        if key == "repository" {
            context.repository = value.to_owned();
        } else {
            context.project = value.to_owned();
        }
        assert!(context.switch("loop-syn-reminder", true, 2000).is_err());
    }
    for project in [
        json!({"kind":"id","value":"prj_syn_foreign"}),
        json!({"kind":"name","value":"prj_syn_example"}),
    ] {
        f.definition["action"]["project"] = project;
        f.commit();
        assert!(f.context.switch("loop-syn-reminder", true, 2000).is_err());
        assert_eq!(f.saved(), before);
    }
    f.definition["action"]["project"] = json!({"kind":"id","value":"prj_syn_example"});
    let mut duplicate = f.definition.clone();
    duplicate["id"] = json!("loop-syn-other");
    fs::write(
        f.context.checkout.join("loops/other.json"),
        duplicate.to_string(),
    )
    .unwrap();
    f.commit();
    assert!(
        f.context
            .switch("Synthetic reminder (example only)", true, 2000)
            .is_err()
    );
    assert_eq!(f.saved(), before);
}

#[test]
fn dirty_or_nondefault_checkout_and_clock_reversal_refuse_without_audit() {
    let f = Fixture::new();
    f.context.switch("loop-syn-reminder", false, 1000).unwrap();
    let before = f.saved();
    assert!(f.context.switch("loop-syn-reminder", true, 999).is_err());
    fs::write(f.context.checkout.join("loops/example.json"), "{}").unwrap();
    assert!(f.context.switch("loop-syn-reminder", true, 2000).is_err());
    git(&f.context.checkout, &["add", "loops"]);
    git(
        &f.context.checkout,
        &["commit", "-qm", "Unmerged synthetic proposal"],
    );
    assert!(f.context.switch("loop-syn-reminder", true, 2000).is_err());
    assert_eq!(f.saved(), before);
}

#[test]
fn corrupt_switch_documents_and_linked_files_fail_closed() {
    use std::os::unix::fs::symlink;
    let f = Fixture::new();
    f.context.switch("loop-syn-reminder", false, 1000).unwrap();
    let original = f.saved();
    let path = f.context.state.join("service/loops/enabled.json");
    let mut bad = vec![
        "[]".to_owned(),
        r#"{"loop-syn-reminder":true,"loop-syn-reminder":false}"#.to_owned(),
        r#"{"loop-syn-reminder":"true"}"#.to_owned(),
    ];
    for (pointer, value) in [
        ("/enabled/loop-syn-reminder", json!(true)),
        ("/events/0/actor", json!(null)),
        ("/events/0/actor", json!(" ")),
        ("/events/0/at_ms", json!(-1)),
        ("/events/0/extra", json!(true)),
    ] {
        let mut document = original.clone();
        if pointer.ends_with("/extra") {
            document["events"][0]["extra"] = value;
        } else {
            *document.pointer_mut(pointer).unwrap() = value;
        }
        bad.push(document.to_string());
    }
    for document in bad {
        fs::write(&path, &document).unwrap();
        assert!(
            f.context.switch("loop-syn-reminder", true, 2000).is_err(),
            "{document}"
        );
        assert_eq!(fs::read_to_string(&path).unwrap(), document);
    }
    fs::remove_file(&path).unwrap();
    let other = f.root.join("unrelated.json");
    fs::write(&other, "{}").unwrap();
    symlink(&other, &path).unwrap();
    assert!(f.context.switch("loop-syn-reminder", true, 2000).is_err());
    assert_eq!(fs::read_to_string(other).unwrap(), "{}");
}

#[test]
fn switch_and_scheduler_share_the_lock_and_authority_is_rechecked_under_it() {
    use openwiz_cli::state::loops::storage::Storage;
    let mut f = Fixture::new();
    f.context.switch("loop-syn-reminder", false, 1000).unwrap();
    let before = f.saved();
    let lock = Storage::open(&f.context.state).unwrap();
    assert!(matches!(
        f.context
            .switch_with_clock("loop-syn-reminder", true, &ExpiredClock::new()),
        Err(openwiz_cli::state::loops::SwitchError::Busy)
    ));
    assert_eq!(f.saved(), before);
    drop(lock);
    struct Revoked(AtomicU64);
    impl Trust for Revoked {
        fn verify(&self, _: &Path, _: &str, _: &str) -> bool {
            self.0.fetch_add(1, Ordering::SeqCst) == 0
        }
        fn actor(&self) -> Option<String> {
            Some("synthetic-operator".to_owned())
        }
    }
    f.context.trust = Some(Arc::new(Revoked(AtomicU64::new(0))));
    assert!(f.context.switch("loop-syn-reminder", true, 2000).is_err());
    assert_eq!(f.saved(), before);
}

pub struct ExpiredClock {
    base: std::time::Instant,
    calls: AtomicU64,
}
impl ExpiredClock {
    pub fn new() -> Self {
        Self {
            base: std::time::Instant::now(),
            calls: AtomicU64::new(0),
        }
    }
}
impl openwiz_core::ops::Clock for ExpiredClock {
    fn now(&self) -> openwiz_core::model::Timestamp {
        openwiz_core::model::Timestamp(3000)
    }
    fn monotonic(&self) -> std::time::Instant {
        self.base
            + if self.calls.fetch_add(1, Ordering::SeqCst) == 0 {
                std::time::Duration::ZERO
            } else {
                std::time::Duration::from_secs(30)
            }
    }
}
#[test]
fn r1_busy_deadline_changes_no_state_and_retry_saves_once() {
    use openwiz_cli::state::loops::{SwitchError, storage::Storage};
    let f = Fixture::new();
    f.context.switch("loop-syn-reminder", false, 1000).unwrap();
    let before = f.saved();
    let lock = Storage::open(&f.context.state).unwrap();
    for enabled in [false, true] {
        assert_eq!(
            f.context
                .switch_with_clock("loop-syn-reminder", enabled, &ExpiredClock::new()),
            Err(SwitchError::Busy)
        );
        assert_eq!(f.saved(), before);
    }
    drop(lock);
    f.context
        .switch_with_clock("loop-syn-reminder", true, &ExpiredClock::new())
        .unwrap();
    assert_eq!(f.saved()["events"].as_array().unwrap().len(), 2);
}
