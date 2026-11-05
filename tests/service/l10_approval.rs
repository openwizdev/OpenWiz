//! LP1 production approval proofs. Every identity, record and check is synthetic.
use openwiz_core::{
    loops::{Capacity, Limits},
    messaging::sha256_hex,
    model::{Fact, Timestamp},
    new_thread::{
        effects::ProjectCandidate,
        operation::{NewThreadClient, ObservedThread, SpawnRequest},
        options::{Catalogue, CatalogueHarness, CatalogueModel},
        outcome::SpawnReply,
        start::ShownThread,
    },
    ops::Clock,
    source::SourceError,
};
use openwiz_service::loops::{
    Approval, Config, Runner, Services,
    approval::{Approvals, InstalledApproval},
};
use openwiz_store::{NewThreadFileStore, loops::repository::Repository};
use serde_json::{Value, json};
use std::{
    fs,
    os::unix::fs::{DirBuilderExt, PermissionsExt, symlink},
    path::{Path, PathBuf},
    process::Command,
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
    },
    time::Instant,
};
#[path = "../support/schema.rs"]
#[allow(dead_code)]
mod schema;

const REPOSITORY: &str = "synthetic-owner/synthetic-repo";
const PROJECT: &str = "prj_syn_0001";
const APPROVAL: &str = "https://github.com/synthetic-private/records/issues/901#issuecomment-7001";

fn private_dir(path: &Path) {
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(path)
        .unwrap();
}
fn git(root: &Path, args: &[&str]) -> String {
    let out = Command::new("git")
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_CONFIG_SYSTEM", "/dev/null")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).unwrap().trim().to_owned()
}
struct FixedClock;
impl Clock for FixedClock {
    fn now(&self) -> Timestamp {
        Timestamp(1000)
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}
#[derive(Default)]
struct RecordingClient {
    starts: Mutex<Vec<SpawnRequest>>,
    revoke_on_preview: Option<PathBuf>,
}
impl NewThreadClient for RecordingClient {
    fn name(&self) -> &str {
        "synthetic"
    }
    fn tested_version(&self) -> &str {
        "synthetic"
    }
    fn cli_levels(&self) -> &[&str] {
        &["high"]
    }
    fn version(&self, _: Instant) -> Result<String, SourceError> {
        Ok("synthetic".into())
    }
    fn projects(&self, _: Instant) -> Result<Vec<ProjectCandidate>, SourceError> {
        Ok(vec![ProjectCandidate {
            id: PROJECT.into(),
            name: Fact::Known("Synthetic project".into()),
            kind: Fact::Known("standard".into()),
            github_remote: Fact::Known(true),
        }])
    }
    fn catalogue(&self, _: Instant) -> Result<Catalogue, SourceError> {
        if let Some(path) = &self.revoke_on_preview {
            fs::remove_file(path).unwrap();
        }
        Ok(Catalogue {
            ready: true,
            harnesses: Some(vec![CatalogueHarness {
                id: "codex".into(),
                provider: Some("codex".into()),
                models: Some(vec![CatalogueModel {
                    model: "synthetic-model".into(),
                    reasoning_levels: vec!["high".into()],
                }]),
                attachments: None,
                steer: None,
            }]),
        })
    }
    fn spawn(&self, request: &SpawnRequest, _: Instant) -> SpawnReply {
        self.starts.lock().unwrap().push(request.clone());
        SpawnReply::Created {
            thread_id: "thr_syn_0021".into(),
        }
    }
    fn show_thread(&self, _: &str, _: Instant) -> Result<ShownThread, SourceError> {
        Ok(ShownThread {
            status: Fact::Known("active".into()),
            last_error: Fact::Known(None),
            provider: Fact::Known("codex".into()),
            model: Fact::Known("synthetic-model".into()),
            effort: Fact::Known("high".into()),
            problems: vec![],
        })
    }
    fn threads_since(
        &self,
        _: &str,
        _: Timestamp,
        _: Instant,
    ) -> Result<Vec<ObservedThread>, SourceError> {
        Ok(vec![])
    }
}
struct Fixture {
    root: PathBuf,
    checkout: PathBuf,
    state: PathBuf,
    definition: Value,
    revision: String,
    bytes: Vec<u8>,
}
impl Fixture {
    fn new(mode: &str, script: &str) -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "ow-l10-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let checkout = root.join("checkout");
        let state = root.join("state");
        private_dir(&checkout.join("loops"));
        private_dir(&state.join("service"));
        let definition = json!({"schema":"openwiz.loops.v1","kind":"definition","id":"loop-synthetic","name":"Synthetic loop","owner":"synthetic-owner",
            "wake":{"kind":"once","at_ms":1000},"check":{"argv":["/bin/sh","-c",format!("printf x >> check-ran; {script}")],"timeout_ms":10000},
            "action":{"project":{"kind":"id","value":PROJECT},"harness":"codex","model":"synthetic-model","effort":"high","brief":"Handle synthetic findings only."},
            "authority":{"approved_by":"Synthetic approver","approval_ref":APPROVAL,"scope":"Synthetic effects only."},
            "budget":{"window_ms":60000,"max_agent_starts":1},"enabled":true,"mode":mode,"priority":"normal"});
        git(&checkout, &["init", "-q", "--initial-branch=main"]);
        git(&checkout, &["config", "user.name", "Synthetic Builder"]);
        git(
            &checkout,
            &["config", "user.email", "synthetic@example.invalid"],
        );
        git(
            &checkout,
            &[
                "config",
                "remote.origin.url",
                "https://github.com/synthetic-owner/synthetic-repo.git",
            ],
        );
        let mut f = Self {
            root,
            checkout,
            state,
            definition,
            revision: String::new(),
            bytes: vec![],
        };
        f.commit_bytes(f.definition.to_string().as_bytes());
        f.save_config(&f.config());
        f
    }
    fn commit_bytes(&mut self, bytes: &[u8]) {
        fs::write(self.checkout.join("loops/loop.json"), bytes).unwrap();
        git(&self.checkout, &["add", "loops"]);
        git(
            &self.checkout,
            &["commit", "-q", "--allow-empty", "-m", "Synthetic loop"],
        );
        git(
            &self.checkout,
            &["update-ref", "refs/remotes/origin/main", "HEAD"],
        );
        git(
            &self.checkout,
            &[
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/main",
            ],
        );
        self.revision = git(&self.checkout, &["rev-parse", "HEAD:loops/loop.json"]);
        self.bytes = bytes.to_vec();
    }
    fn record(&self) -> Value {
        json!({"repository":{"owner":"synthetic-owner","name":"synthetic-repo"},"project":PROJECT,"loop_id":"loop-synthetic", "definition_revision":self.revision,"sha256":sha256_hex(&self.bytes),"approved_by":"Synthetic approver","scope":"Synthetic effects only.","approval_ref":APPROVAL})
    }
    fn config(&self) -> Value {
        json!({"schema":"openwiz.service-config.v1","repository":{"owner":"synthetic-owner","name":"synthetic-repo"},"project":PROJECT,"loops":{"approvals":[self.record()]}})
    }
    fn config_path(&self) -> PathBuf {
        self.state.join("service/config.json")
    }
    fn save_config(&self, config: &Value) {
        self.save_raw(&config.to_string());
    }
    fn save_raw(&self, text: &str) {
        fs::write(self.config_path(), text).unwrap();
        fs::set_permissions(self.config_path(), fs::Permissions::from_mode(0o600)).unwrap();
    }
    fn verifier(&self) -> InstalledApproval {
        InstalledApproval::new(
            self.checkout.clone(),
            self.state.clone(),
            REPOSITORY.into(),
            PROJECT.into(),
        )
    }
    fn runner(&self, client: Arc<RecordingClient>, max_starts: u64) -> Runner {
        // Budget variations are committed/approved by the caller, not injected here.
        assert_eq!(self.definition["budget"]["max_agent_starts"], max_starts);
        Runner::new(
            Config {
                checkout: self.checkout.clone(),
                state: self.state.clone(),
                limits: Some(Limits {
                    checks: Capacity {
                        max: 4,
                        urgent_reserve: 1,
                    },
                    agents: Capacity {
                        max: 16,
                        urgent_reserve: 4,
                    },
                }),
            },
            Services {
                clock: Arc::new(FixedClock),
                client,
                new_threads: Arc::new(NewThreadFileStore::open(&self.state).unwrap()),
                approval: Some(Arc::new(self.verifier())),
            },
        )
    }
    fn check_count(&self) -> usize {
        fs::read(self.checkout.join("check-ran"))
            .unwrap_or_default()
            .len()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.root).unwrap();
    }
}

fn mismatched_bindings() -> Vec<(&'static str, Value)> {
    vec![
        (
            "repository",
            json!({"owner":"synthetic-owner","name":"other-repo"}),
        ),
        ("project", json!("prj_syn_other")),
        ("loop_id", json!("other-loop")),
        ("definition_revision", json!("a".repeat(40))),
        ("sha256", json!("0".repeat(64))),
        ("approved_by", json!("Other approver")),
        ("scope", json!("Other effects.")),
        (
            "approval_ref",
            json!("https://github.com/synthetic-private/records/issues/901#issuecomment-7002"),
        ),
    ]
}

#[test]
fn exact_binding_verifies_only_its_blob_definition_and_configured_identity() {
    let f = Fixture::new("active", "printf finding");
    let verifier = f.verifier();
    // Independent static vector computed with Python hashlib, not the verifier
    // or the Rust digest helper. It describes this exact ASCII fixture blob.
    let mut trusted = f.config();
    trusted["loops"]["approvals"][0]["sha256"] =
        json!("fa30a27149ef73b388009816819698b71797cd31becfb38c8c2a8db3740e9e57");
    f.save_config(&trusted);
    assert!(verifier.verify(&f.definition, &f.revision));
    for (field, value) in mismatched_bindings() {
        let mut config = f.config();
        config["loops"]["approvals"][0][field] = value;
        f.save_config(&config);
        assert!(
            !verifier.verify(&f.definition, &f.revision),
            "accepted mismatched {field}"
        );
    }
    f.save_config(&f.config());
    for pointer in [
        "/id",
        "/action/project/value",
        "/action/project/kind",
        "/authority/approved_by",
        "/authority/scope",
        "/authority/approval_ref",
        "/action/brief",
        "/check/argv/0",
    ] {
        let mut definition = f.definition.clone();
        *definition.pointer_mut(pointer).unwrap() = json!("synthetic-change");
        assert!(
            !verifier.verify(&definition, &f.revision),
            "accepted changed {pointer}"
        );
    }
    assert!(!verifier.verify(&f.definition, "HEAD"));
    for field in ["repository", "project"] {
        let mut config = f.config();
        config[field] = json!("wrong-installation");
        f.save_config(&config);
        assert!(!verifier.verify(&f.definition, &f.revision));
    }
    f.save_config(&f.config());
    assert!(
        !InstalledApproval::new(
            f.checkout.clone(),
            f.state.clone(),
            "synthetic-owner/other-repo".into(),
            PROJECT.into()
        )
        .verify(&f.definition, &f.revision)
    );
    assert!(
        !InstalledApproval::new(
            f.checkout.clone(),
            f.state.clone(),
            REPOSITORY.into(),
            "prj_syn_other".into()
        )
        .verify(&f.definition, &f.revision)
    );
    assert!(verifier.verify(&f.definition, &f.revision));
}

#[test]
fn exact_bytes_are_required_even_when_json_values_are_equal() {
    let mut f = Fixture::new("shadow", "printf finding");
    let original = f.record();
    let original_revision = f.revision.clone();
    let verifier = f.verifier();
    assert!(verifier.verify(&f.definition, &f.revision));
    f.commit_bytes(format!("{}\n", f.definition).as_bytes());
    assert_ne!(f.revision, original_revision);
    let mut config = f.config();
    config["loops"]["approvals"][0]["sha256"] = original["sha256"].clone();
    f.save_config(&config);
    assert!(
        !verifier.verify(&f.definition, &f.revision),
        "a parsed-value digest cannot approve changed bytes"
    );
    f.save_config(&f.config());
    assert!(verifier.verify(&f.definition, &f.revision));
    // Even the supplied parsed definition must be the blob at the revision.
    let mut other = f.definition.clone();
    other["name"] = json!("Forged parsed value");
    assert!(!verifier.verify(&other, &f.revision));
}

#[test]
fn strict_reader_and_schema_refuse_malformed_fields() {
    let f = Fixture::new("active", ":");
    let valid = json!([f.record()]);
    let mut root: Value =
        serde_json::from_str(include_str!("../../contracts/service.v1.schema.json")).unwrap();
    root.as_object_mut().unwrap().remove("oneOf");
    root["$ref"] = json!("#/$defs/loop_approvals");
    assert!(schema::lint(&root).is_empty(), "{:?}", schema::lint(&root));
    assert!(root["$defs"]["loop_approvals"].is_object());
    let verdict = |v: &Value, expected: bool| {
        assert_eq!(
            Approvals::read(&v.to_string()).is_ok(),
            expected,
            "reader: {v}"
        );
        assert_eq!(
            schema::validate(&root, v).is_empty(),
            expected,
            "schema: {v}"
        );
    };
    verdict(&valid, true);
    verdict(&json!([]), true);
    for v in [
        Value::Null,
        json!({}),
        json!("record"),
        json!([[]]),
        json!([null]),
    ] {
        verdict(&v, false);
    }
    for field in f.record().as_object().unwrap().keys() {
        let mut missing = valid.clone();
        missing[0].as_object_mut().unwrap().remove(field);
        verdict(&missing, false);
        for bad in [Value::Null, json!(true), json!(42), json!([])] {
            let mut row = valid.clone();
            row[0][field] = bad;
            verdict(&row, false);
        }
    }
    let mut extra = valid.clone();
    extra[0]["unknown"] = json!(true);
    verdict(&extra, false);
    for (field, bad) in [
        (
            "repository",
            json!({"owner":"synthetic-owner","name":"synthetic-repo","extra":0}),
        ),
        (
            "repository",
            json!({"owner":"bad/owner","name":"synthetic-repo"}),
        ),
        ("project", json!("")),
        ("project", json!("name with spaces")),
        ("loop_id", json!("-bad")),
        ("definition_revision", json!("a".repeat(39))),
        ("definition_revision", json!("A".repeat(40))),
        ("sha256", json!("f".repeat(63))),
        ("sha256", json!("g".repeat(64))),
        ("scope", json!(" \t")),
        ("approved_by", json!("\u{0000}")),
        (
            "approval_ref",
            json!("https://github.com/synthetic-private/records/issues/01#issuecomment-1"),
        ),
        (
            "approval_ref",
            json!("https://github.com/synthetic-private/records/issues/1#issuecomment-0"),
        ),
        ("approval_ref", json!("https://example.invalid/private")),
        ("approval_ref", json!(format!("{APPROVAL}?token=synthetic"))),
    ] {
        let mut rows = valid.clone();
        rows[0][field] = bad;
        verdict(&rows, false);
    }
}

#[test]
fn duplicate_keys_bindings_conflicts_and_trailing_data_are_refused() {
    let f = Fixture::new("active", ":");
    let row = f.record().to_string();
    for text in [
        format!("[{row},{row}]"),
        format!("[{row}] trailing"),
        "[".into(),
    ] {
        assert!(Approvals::read(&text).is_err());
    }
    for field in f.record().as_object().unwrap().keys() {
        let text = format!("[{{\"{field}\":null,{}]", &row[1..]);
        assert!(
            Approvals::read(&text).is_err(),
            "accepted duplicate {field}"
        );
    }
    let mut conflict = f.record();
    conflict["scope"] = json!("Other scope.");
    assert!(Approvals::read(&json!([f.record(), conflict]).to_string()).is_err());
    let nested = row.replace(
        "\"owner\":\"synthetic-owner\"",
        "\"owner\":\"synthetic-owner\",\"owner\":\"synthetic-owner\"",
    );
    assert!(Approvals::read(&format!("[{nested}]")).is_err());
}

#[test]
fn installed_record_is_reread_and_unavailable_or_unsafe_config_revokes_it() {
    let f = Fixture::new("active", ":");
    let verifier = f.verifier();
    assert!(verifier.verify(&f.definition, &f.revision));
    for config in [json!({}), json!({"loops":{}}), {
        let mut v = f.config();
        v["loops"]["approvals"] = json!([]);
        v
    }] {
        f.save_config(&config);
        assert!(!verifier.verify(&f.definition, &f.revision));
    }
    f.save_config(&f.config());
    assert!(verifier.verify(&f.definition, &f.revision));
    for text in [
        "not json".into(),
        f.config()
            .to_string()
            .replacen("\"loops\":", "\"loops\":{},\"loops\":", 1),
    ] {
        f.save_raw(&text);
        assert!(!verifier.verify(&f.definition, &f.revision));
    }
    f.save_config(&f.config());
    fs::set_permissions(f.config_path(), fs::Permissions::from_mode(0o644)).unwrap();
    assert!(!verifier.verify(&f.definition, &f.revision));
    fs::set_permissions(f.config_path(), fs::Permissions::from_mode(0o600)).unwrap();
    let backup = f.root.join("config-copy");
    fs::rename(f.config_path(), &backup).unwrap();
    assert!(!verifier.verify(&f.definition, &f.revision));
    symlink(&backup, f.config_path()).unwrap();
    assert!(!verifier.verify(&f.definition, &f.revision));
    fs::remove_file(f.config_path()).unwrap();
    fs::hard_link(&backup, f.config_path()).unwrap();
    assert!(!verifier.verify(&f.definition, &f.revision));
}

#[test]
fn checkout_origin_is_required_unique_and_matches_configured_repository() {
    let f = Fixture::new("active", ":");
    let verifier = f.verifier();
    assert!(verifier.verify(&f.definition, &f.revision));
    for remote in [
        "https://github.com/synthetic-owner/other-repo.git",
        "https://example.invalid/synthetic-owner/synthetic-repo",
        "/synthetic/local",
    ] {
        git(&f.checkout, &["config", "remote.origin.url", remote]);
        assert!(!verifier.verify(&f.definition, &f.revision));
    }
    for remote in [
        "https://github.com/synthetic-owner/synthetic-repo.git",
        "git@github.com:synthetic-owner/synthetic-repo",
        "ssh://git@github.com/synthetic-owner/synthetic-repo.git",
    ] {
        git(&f.checkout, &["config", "remote.origin.url", remote]);
        assert!(verifier.verify(&f.definition, &f.revision));
    }
    git(
        &f.checkout,
        &[
            "config",
            "--add",
            "remote.origin.url",
            "https://github.com/synthetic-owner/synthetic-repo.git",
        ],
    );
    assert!(!verifier.verify(&f.definition, &f.revision));
}

#[test]
fn runner_preserves_approved_quiet_shadow_active_and_off_behaviour() {
    for (mode, script, expected, starts) in [
        ("active", ":", "quiet", 0),
        ("shadow", "printf finding", "shadow", 0),
        ("active", "printf finding", "created", 1),
    ] {
        let f = Fixture::new(mode, script);
        let client = Arc::new(RecordingClient::default());
        let runner = f.runner(client.clone(), 1);
        let runs = runner.pass().unwrap();
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0]["result"]["kind"], expected);
        assert_eq!(f.check_count(), 1);
        assert_eq!(client.starts.lock().unwrap().len(), starts);
        assert_eq!(runner.pass().unwrap(), runs);
        assert_eq!(f.check_count(), 1);
    }
    let mut f = Fixture::new("active", "printf finding");
    f.definition["enabled"] = json!(false);
    f.commit_bytes(f.definition.to_string().as_bytes());
    f.save_config(&f.config());
    let client = Arc::new(RecordingClient::default());
    assert!(f.runner(client.clone(), 1).pass().unwrap().is_empty());
    assert_eq!(f.check_count(), 0);
    assert_eq!(client.starts.lock().unwrap().len(), 0);
}

#[test]
fn runner_refuses_each_untrusted_binding_before_check_in_active_and_shadow() {
    for mode in ["active", "shadow"] {
        let f = Fixture::new(mode, "printf finding");
        for (field, value) in mismatched_bindings() {
            let mut config = f.config();
            config["loops"]["approvals"][0][field] = value;
            f.save_config(&config);
            let client = Arc::new(RecordingClient::default());
            assert!(
                f.runner(client.clone(), 1).pass().unwrap().is_empty(),
                "{mode} {field}"
            );
            assert_eq!(f.check_count(), 0);
            assert_eq!(client.starts.lock().unwrap().len(), 0);
            let admission =
                fs::read_to_string(f.state.join("service/loops/admission.json")).unwrap();
            assert!(!admission.contains(APPROVAL));
            assert!(!admission.contains("Synthetic effects"));
        }
    }
}

#[test]
fn runner_rechecks_revocation_after_check_and_after_preview() {
    for during_preview in [false, true] {
        let f = Fixture::new(
            "active",
            if during_preview {
                "printf finding"
            } else {
                "rm ../state/service/config.json; printf finding"
            },
        );
        let client = Arc::new(RecordingClient {
            revoke_on_preview: during_preview.then(|| f.config_path()),
            ..Default::default()
        });
        let runs = f.runner(client.clone(), 1).pass().unwrap();
        assert_eq!(runs.len(), 1);
        assert_eq!(f.check_count(), 1);
        assert_eq!(client.starts.lock().unwrap().len(), 0);
        assert!(matches!(
            runs[0]["result"]["kind"].as_str(),
            Some("deferred" | "refused")
        ));
        assert!(runs[0]["result"].get("dispatch_at_ms").is_none());
    }
}

#[test]
fn schema_trust_alone_never_approves_an_uninstalled_definition() {
    let f = Fixture::new("shadow", ":");
    assert_eq!(
        Repository(f.checkout.clone()).current().unwrap()[0].value,
        f.definition
    );
    fs::remove_file(f.config_path()).unwrap();
    assert!(!f.verifier().verify(&f.definition, &f.revision));
}

// C2/C4: a schema-valid, newly approved blob must still target the configured
// id explicitly. An equal display name is not an installation identity.
#[test]
fn reapproved_blob_cannot_substitute_an_action_project_name_or_foreign_id() {
    for project in [
        json!({"kind":"name","value":PROJECT}),
        json!({"kind":"id","value":"prj_syn_other"}),
    ] {
        let mut f = Fixture::new("active", "printf finding");
        f.definition["action"]["project"] = project;
        f.commit_bytes(f.definition.to_string().as_bytes());
        f.save_config(&f.config());
        assert!(!f.verifier().verify(&f.definition, &f.revision));
        let client = Arc::new(RecordingClient::default());
        assert!(f.runner(client.clone(), 1).pass().unwrap().is_empty());
        assert_eq!(f.check_count(), 0);
        assert_eq!(client.starts.lock().unwrap().len(), 0);
    }
}

// C1/C3/C4: malformed and revoked trust must stop a real Runner, including
// shadow mode. Checking only a fragment parser would miss bad extraction/caching.
#[test]
fn runner_refuses_duplicate_revoked_and_byte_changed_records_before_checks() {
    for mode in ["active", "shadow"] {
        let mut f = Fixture::new(mode, "printf finding");
        let row = f.record();
        let valid = f.config();
        let mut conflict = row.clone();
        conflict["scope"] = json!("Conflicting synthetic scope.");
        let duplicate_field = valid
            .to_string()
            .replace("\"scope\":", "\"scope\":\"extra\",\"scope\":");
        let mut configs = vec!["{}".into(), "not json".into(), duplicate_field];
        for rows in [
            json!([]),
            json!([row.clone(), row.clone()]),
            json!([row.clone(), conflict]),
        ] {
            let mut config = valid.clone();
            config["loops"]["approvals"] = rows;
            configs.push(config.to_string());
        }
        for text in configs {
            f.save_raw(&text);
            let client = Arc::new(RecordingClient::default());
            assert!(f.runner(client.clone(), 1).pass().unwrap().is_empty());
            assert_eq!(f.check_count(), 0);
            assert_eq!(client.starts.lock().unwrap().len(), 0);
        }
        // A stale digest with the current revision must not approve identical
        // parsed JSON after a newline-only edit.
        f.commit_bytes(format!("{}\n", f.definition).as_bytes());
        let mut config = f.config();
        config["loops"]["approvals"][0]["sha256"] = row["sha256"].clone();
        f.save_config(&config);
        let client = Arc::new(RecordingClient::default());
        assert!(f.runner(client.clone(), 1).pass().unwrap().is_empty());
        assert_eq!(f.check_count(), 0);
        assert_eq!(client.starts.lock().unwrap().len(), 0);
    }
}

#[test]
fn public_reader_diagnostics_never_echo_private_input() {
    let f = Fixture::new("active", ":");
    let mut bad = f.record();
    bad["sha256"] = json!("synthetic-private-record-content");
    let result = Approvals::read(&json!([bad]).to_string());
    let error = result.err().expect("malformed digest must be refused");
    assert_eq!(error, "trusted loop approval is unavailable or invalid");
}

#[test]
fn runner_rechecks_approval_before_each_check_in_a_batch() {
    let mut f = Fixture::new("shadow", "rm ../state/service/config.json; printf finding");
    let mut second = f.definition.clone();
    second["id"] = json!("z-synthetic-loop");
    second["check"]["argv"] = json!(["/bin/sh", "-c", "printf y >> second-check"]);
    let second_bytes = second.to_string();
    fs::write(f.checkout.join("loops/second.json"), &second_bytes).unwrap();
    f.commit_bytes(f.definition.to_string().as_bytes());
    let mut second_approval = f.record();
    second_approval["loop_id"] = json!("z-synthetic-loop");
    second_approval["definition_revision"] =
        json!(git(&f.checkout, &["rev-parse", "HEAD:loops/second.json"]));
    second_approval["sha256"] = json!(sha256_hex(second_bytes.as_bytes()));
    let mut config = f.config();
    config["loops"]["approvals"] = json!([f.record(), second_approval]);
    f.save_config(&config);
    let client = Arc::new(RecordingClient::default());
    let runner = f.runner(client.clone(), 1);
    let runs = runner.pass().unwrap();
    assert_eq!(f.check_count(), 1, "the approved first check ran");
    assert!(
        !f.checkout.join("second-check").exists(),
        "the second check must reverify approval removed by the first check"
    );
    assert_eq!(runs.len(), 1, "a refused check saves no occurrence");
    assert_eq!(runs[0]["loop_id"], "loop-synthetic");
    f.save_config(&config);
    let resumed = runner.pass().unwrap();
    assert_eq!(
        resumed.len(),
        2,
        "restoring trust admits the skipped occurrence"
    );
    assert_eq!(fs::read(f.checkout.join("second-check")).unwrap(), b"y");
    assert_eq!(f.check_count(), 1, "the first occurrence is not repeated");
    assert_eq!(client.starts.lock().unwrap().len(), 0);
}
