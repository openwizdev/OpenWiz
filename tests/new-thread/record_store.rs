//! The `new_thread` record kind in `openwiz-store` (A1 phase 2): owner-only,
//! outside every repository, beside the send record and apart from it; and
//! read back only through the core's strict reader, so a record on disk
//! that isn't exactly the contract's shape is refused, and nothing is
//! created from it.

use std::fs;
use std::os::unix::fs::PermissionsExt;

use openwiz_core::envelope::SourceInfo;
use openwiz_core::messaging::send::UncertainReason;
use openwiz_core::model::{Fact, Timestamp};
use openwiz_core::new_thread::effects::effects_for;
use openwiz_core::new_thread::outcome::{FailReason, Gap, Outcome, RefusalReason};
use openwiz_core::new_thread::read::StrictJson;
use openwiz_core::new_thread::record::{NewThreadRecord, NewThreadStore, recover};
use openwiz_core::new_thread::{Binding, ProjectRef, ProjectView};
use openwiz_core::prompt::empty_attachments_digest;
use openwiz_store::NewThreadFileStore;
use serde_json::{Value, json};

use crate::fake::*;
use crate::support::{T0, offered, private_dir, request};

fn mode_of(path: &std::path::Path) -> u32 {
    fs::metadata(path).unwrap().permissions().mode() & 0o777
}

/// Parse the complete stdout stream: a second document or prose is refused.
fn assert_status_store_error(output: &std::process::Output) {
    assert!(output.stdout.ends_with(b"\n"), "{output:?}");
    let value: Value = serde_json::from_slice(&output.stdout)
        .expect("exactly one complete JSON status error document");
    let schema: Value =
        serde_json::from_str(include_str!("../../contracts/cli.v1.schema.json")).unwrap();
    assert_eq!(
        crate::schema::validate(&schema, &value),
        Vec::<String>::new(),
        "{value}"
    );
    assert_eq!(value["schema"], "openwiz.cli-error.v1");
    assert_eq!(value["command"], "new.status");
    assert_eq!(value["exit_code"], 10);
    assert_eq!(value["error"]["kind"], "store_unavailable");
}

/// Every record shape the core writes: claimed, dispatching, and finished
/// with each outcome; by name and by id; recovered; with gaps.
pub fn every_record() -> Vec<NewThreadRecord> {
    let r = request(offered(), "Synthetic\nline two", "op-store-every");
    let claimed = NewThreadRecord::claimed(
        r.op_id.clone(),
        Binding::new(&r, empty_attachments_digest()),
        r.settings.clone(),
        &r.prompt.text,
        T0,
    );
    let project = ProjectView {
        id: "prj_syn_0001".to_owned(),
        name: Fact::Known("Synthetic project one".to_owned()),
    };
    let mut looked = claimed.clone();
    looked.project = Some(project.clone());
    looked.provider = Some("codex".to_owned());
    looked.source = Some(SourceInfo {
        name: "room-cli".to_owned(),
        version: Fact::Unknown("room-cli --version timed out after 1 ms".to_owned()),
        tested_version: "v127".to_owned(),
        version_tested: false,
    });
    looked.effects = Some(effects_for(&project, T0));
    looked.gaps.push(Gap {
        subject: "room-cli --version".to_owned(),
        detail: "Synthetic gap".to_owned(),
    });
    let dispatching = looked.dispatching(Timestamp(T0.0 + 1));
    let mut by_name = claimed.clone();
    by_name.binding.project = ProjectRef::Name("Synthetic shared~n_0004".to_owned());
    by_name.project = Some(ProjectView {
        id: "prj_syn_0004".to_owned(),
        name: Fact::Unknown("schema: name".to_owned()),
    });
    let later = Timestamp(T0.0 + 2);
    vec![
        claimed.clone(),
        by_name.clone(),
        dispatching.clone(),
        dispatching.finished(Outcome::created("thr_syn_0021".to_owned()), later),
        claimed.finished(
            Outcome::refused_because(
                RefusalReason::ModelNotOffered,
                "not offered",
                vec!["syn-codex-model-01".to_owned()],
            ),
            later,
        ),
        by_name.finished(Outcome::refused(RefusalReason::ProjectAmbiguous), later),
        looked.finished(Outcome::failed(FailReason::BudgetExhausted), later),
        dispatching.finished(Outcome::uncertain(UncertainReason::TimedOut), later),
        recover(&claimed, later),
        recover(&dispatching, later),
    ]
}

pub fn read(value: &Value) -> Result<NewThreadRecord, String> {
    let tree: StrictJson =
        serde_json::from_str(&value.to_string()).map_err(|e| format!("tree: {e}"))?;
    NewThreadRecord::read(&tree).map_err(|e| e.0)
}

#[test]
fn every_record_the_core_writes_reads_back_the_same() {
    for record in every_record() {
        let value = serde_json::to_value(&record).unwrap();
        assert!(
            crate::support::validate_def("record", &value).is_empty(),
            "{value}"
        );
        assert_eq!(read(&value).as_ref(), Ok(&record), "{value}");
    }
}

#[test]
fn the_record_is_owner_only_outside_the_repository_and_beside_the_send_record() {
    let fake = NewFake::new("store_layout");
    let (code, out, err) = fake.cli(
        &new_args("Synthetic project one", "op-store-layout", &[], "Synthetic"),
        "",
    );
    assert_eq!(code, 0, "{out}{err}");
    let dir = fake.state.join("new-threads");
    assert_eq!(mode_of(&fake.state), 0o700);
    assert_eq!(mode_of(&dir), 0o700);
    assert_eq!(mode_of(&dir.join("op-store-layout.json")), 0o600);
    assert_eq!(mode_of(&dir.join("op-store-layout.lock")), 0o600);
    assert!(
        !fake.state.join("sends").exists(),
        "a create writes no send record"
    );
    let names: Vec<String> = fs::read_dir(&dir)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    assert_eq!(names.len(), 2, "{names:?}: no temporary file is left");
    // The record holds no text once the thread is created.
    assert!(fake.record("op-store-layout")["text"].is_null());

    // The same refusals as the send record.
    let open = |dir: &std::path::Path| NewThreadFileStore::open(dir).map(|_| ());
    let shared = private_dir("store-shared");
    fs::set_permissions(&shared, fs::Permissions::from_mode(0o750)).unwrap();
    assert!(open(&shared).is_err(), "group may enter");
    assert!(open(std::path::Path::new("relative/state")).is_err());
    let root = std::path::Path::new(crate::support::ROOT)
        .canonicalize()
        .unwrap();
    assert!(
        open(&root.join("target/nt-state")).is_err(),
        "inside the repository"
    );
    let planted = private_dir("store-planted");
    std::os::unix::fs::symlink(&shared, planted.join("new-threads")).unwrap();
    assert!(
        open(&planted).is_err(),
        "a symlinked new-threads/ is refused"
    );
    // Read-only: nothing is made where nothing was.
    let empty = private_dir("store-empty").join("state");
    assert!(
        NewThreadFileStore::open_read_only(&empty)
            .unwrap()
            .is_none()
    );
    assert!(!empty.exists());
}

#[test]
fn a_record_that_is_not_exactly_its_shape_is_refused_and_nothing_is_created() {
    let fake = NewFake::new("store_refused");
    let args = new_args("Synthetic project one", "op-store-bad", &[], "Synthetic");
    let (code, _, _) = fake.cli(&args, "");
    assert_eq!(code, 0);
    let path = fake.record_path("op-store-bad");
    let good = fs::read_to_string(&path).unwrap();
    let value: Value = serde_json::from_str(&good).unwrap();
    let duplicate = good.replacen(
        "\"recovered\": false",
        "\"recovered\": false,\n  \"recovered\": false",
        1,
    );
    assert_ne!(duplicate, good);
    let mut extra = value.clone();
    extra["extra"] = json!(1);
    let mut tagged = value.clone();
    tagged["state"] = json!({"finished": null});
    let positional = Value::Array(value.as_object().unwrap().values().cloned().collect());
    for bad in [
        duplicate,
        extra.to_string(),
        tagged.to_string(),
        positional.to_string(),
        "not JSON".to_owned(),
    ] {
        fs::write(&path, &bad).unwrap();
        let before = fake.spawn_count();
        let (code, out, err) = fake.cli(&args, "");
        assert_eq!(code, 10, "{bad}\n{out}{err}");
        assert!(err.contains("is not a new-thread record"), "{err}");
        let (code, _, err) = fake.cli(&["new", "--status", "op-store-bad"], "");
        assert_eq!(code, 10, "{err}");
        assert_eq!(fake.spawn_count(), before, "nothing was created");
    }

    // A record in another op id's file is refused too.
    let mut moved = value.clone();
    moved["op_id"] = json!("op-store-other");
    moved["request_id"] = json!(openwiz_core::new_thread::request_id(
        &openwiz_core::messaging::OpId::parse("op-store-other").unwrap()
    ));
    fs::write(&path, moved.to_string()).unwrap();
    let (code, _, err) = fake.cli(&args, "");
    assert_eq!(code, 10, "{err}");
    assert!(err.contains("another op id"), "{err}");
}

#[test]
fn synthetic_status_refuses_kept_text_with_wrong_hash() {
    let fake = NewFake::new("store_bad_text_hash");
    let store = NewThreadFileStore::open(&fake.state).unwrap();
    let record = &every_record()[0];
    let mut value = serde_json::to_value(record).unwrap();
    assert_eq!(value["text"], "Synthetic\nline two");
    assert_eq!(record.text_bytes, 18);

    // Change only the text, preserving its byte length and the original binding.
    let replacement = "synthetic\nline two";
    assert_eq!(replacement.len(), 18);
    value["text"] = json!(replacement);
    fs::write(store.record_path(&record.op_id), value.to_string()).unwrap();

    let output = fake.run_process(&["new", "--status", "op-store-every", "--json"], "");
    assert_eq!(output.status.code(), Some(10), "{output:?}");
    assert_status_store_error(&output);
    assert_eq!(fake.spawn_count(), 0);
}

#[test]
fn synthetic_status_refuses_claimed_record_with_created_outcome() {
    let fake = NewFake::new("store_claimed_created");
    let store = fake.store();
    let record = &every_record()[3];
    let mut value = serde_json::to_value(record).unwrap();
    assert_eq!(value["outcome"]["kind"], "created");
    assert_eq!(value["dispatching_at"], json!(T0.0 + 1));
    assert_eq!(value["finished_at"], json!(T0.0 + 2));
    // Synthetic corrupt disk input: only the phase contradicts this creation.
    value["state"] = json!("claimed");
    let bytes = serde_json::to_vec(&value).unwrap();
    let path = store.record_path(&record.op_id);
    fs::write(&path, &bytes).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    // An existing, unlocked claim lets status recover the stopped owner.
    let lock = path.with_extension("lock");
    fs::write(&lock, b"").unwrap();
    fs::set_permissions(&lock, fs::Permissions::from_mode(0o600)).unwrap();

    let output = fake.run_process(&["new", "--status", "op-store-every", "--json"], "");
    assert_eq!(
        fs::read(&path).unwrap(),
        bytes,
        "status never rewrites disk"
    );
    assert_eq!(fake.invocations().len(), 0, "no provider call of any kind");
    assert_eq!(fake.spawn_count(), 0);
    assert_eq!(output.status.code(), Some(10), "{output:?}");
    assert_status_store_error(&output);
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("is not a new-thread record"),
        "{output:?}"
    );
}

#[test]
fn synthetic_status_preserves_finished_record_with_created_outcome() {
    let fake = NewFake::new("store_finished_created");
    let store = fake.store();
    let record = &every_record()[3];
    let bytes = serde_json::to_vec(record).unwrap();
    let path = store.record_path(&record.op_id);
    fs::write(&path, &bytes).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();

    let output = fake.run_process(&["new", "--status", "op-store-every", "--json"], "");
    let (code, status) = json_of(&output);
    assert_eq!(code, Some(0), "{output:?}");
    let report = &status["result"]["report"];
    assert_eq!(report["status"], "created");
    assert_eq!(report["result"]["outcome"]["kind"], "created");
    assert_eq!(report["result"]["outcome"]["thread_id"], "thr_syn_0021");
    assert_eq!(report["result"]["recovered"], false);
    assert_eq!(fs::read(&path).unwrap(), bytes);
    assert_eq!(
        fake.invocations(),
        vec![vec!["thread", "show", "thr_syn_0021", "--json"]]
    );
    assert_eq!(fake.spawn_count(), 0);
}

#[test]
fn synthetic_created_records_require_only_a_finished_phase() {
    for (state, expected_exit) in [("claimed", 10), ("dispatching", 10), ("finished", 0)] {
        for (d, dispatching_at) in [Value::Null, json!(T0.0 + 1)].into_iter().enumerate() {
            for (f, finished_at) in [Value::Null, json!(T0.0 + 2)].into_iter().enumerate() {
                let fake = NewFake::new(&format!("store_created_{state}_{d}_{f}"));
                let store = fake.store();
                let record = &every_record()[3];
                let mut value = serde_json::to_value(record).unwrap();
                value["state"] = json!(state);
                value["dispatching_at"] = dispatching_at.clone();
                value["finished_at"] = finished_at;
                let bytes = serde_json::to_vec(&value).unwrap();
                let path = store.record_path(&record.op_id);
                fs::write(&path, &bytes).unwrap();
                fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
                let lock = path.with_extension("lock");
                fs::write(&lock, b"").unwrap();
                fs::set_permissions(&lock, fs::Permissions::from_mode(0o600)).unwrap();

                let output = fake.run_process(&["new", "--status", "op-store-every", "--json"], "");
                assert_eq!(
                    output.status.code(),
                    Some(expected_exit),
                    "{value}: {output:?}"
                );
                if expected_exit == 0 {
                    let (code, status) = json_of(&output);
                    assert_eq!(code, Some(0), "{value}: {output:?}");
                    assert_eq!(status["result"]["report"]["status"], "created");
                    assert_eq!(
                        status["result"]["report"]["result"]["outcome"],
                        value["outcome"]
                    );
                    assert_eq!(
                        fake.invocations(),
                        vec![vec!["thread", "show", "thr_syn_0021", "--json"]]
                    );
                } else {
                    assert_status_store_error(&output);
                    assert!(
                        String::from_utf8_lossy(&output.stderr)
                            .contains("is not a new-thread record"),
                        "{output:?}"
                    );
                    assert_eq!(fake.invocations().len(), 0);
                }
                assert_eq!(fake.spawn_count(), 0);
                assert_eq!(fs::read(&path).unwrap(), bytes);
            }
        }
    }
}

#[test]
fn the_store_claims_once_and_recovers_a_stopped_owner() {
    let state = private_dir("store-claim").join("state");
    let store = NewThreadFileStore::open(&state).unwrap();
    let records = every_record();
    let claimed = &records[0];
    assert_eq!(
        store.claim(claimed, T0).unwrap(),
        openwiz_core::new_thread::record::Claim::Owned
    );
    // A second store in this process is another claimer: in progress.
    let other = NewThreadFileStore::open(&state).unwrap();
    assert!(matches!(
        other.claim(claimed, T0).unwrap(),
        openwiz_core::new_thread::record::Claim::InProgress(_)
    ));
    assert_eq!(
        other.inspect(&claimed.op_id, T0).unwrap().as_ref(),
        Some(claimed)
    );
    // The owner lets go without finishing: recovered as failed, once. A
    // child another test forked while the owner held the lock keeps a copy
    // of it until it runs its program (#146): wait until the lock is free.
    store.release(&claimed.op_id);
    let lock = state
        .join("new-threads")
        .join(format!("{}.lock", claimed.op_id));
    crate::forks::wait_until_unlocked(&lock);
    let later = Timestamp(T0.0 + 5);
    let shown = other.inspect(&claimed.op_id, later).unwrap().unwrap();
    assert_eq!(
        shown,
        recover(claimed, later),
        "shown as recovery would make it"
    );
    assert_eq!(
        other.record(&claimed.op_id).unwrap().as_ref(),
        Some(claimed),
        "not written"
    );
    // `inspect` took the lock to look: the same for its copies.
    crate::forks::wait_until_unlocked(&lock);
    match other.claim(claimed, later).unwrap() {
        openwiz_core::new_thread::record::Claim::Existing(r) => {
            assert_eq!(r, recover(claimed, later));
        }
        claim => panic!("{claim:?}"),
    }
    assert!(other.update(&records[2]).is_err(), "only the owner writes");
}

fn bounded_status(fake: &NewFake) -> std::process::Output {
    let mut child = fake
        .process(&["new", "--status", "op-store-every", "--json"])
        .spawn()
        .unwrap();
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    while child.try_wait().unwrap().is_none() {
        if std::time::Instant::now() >= deadline {
            child.kill().unwrap();
            child.wait().unwrap();
            panic!("status blocked on a synthetic record for five seconds");
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    child.wait_with_output().unwrap()
}

#[test]
fn status_refuses_non_regular_records_without_provider_calls() {
    use std::io::Write as _;
    for kind in ["socket", "directory", "fifo", "linked-fifo", "buffered"] {
        if kind == "buffered" && !cfg!(target_os = "linux") {
            continue; // Opening a FIFO read/write is Linux-specific.
        }
        let fake = NewFake::new(&format!("nr-{kind}"));
        let store = fake.store();
        let path = fake.record_path("op-store-every");
        let mut _reader = None;
        let _socket = match kind {
            "fifo" | "linked-fifo" | "buffered" => {
                let fifo = if kind == "linked-fifo" {
                    fake.dir.join("synthetic-fifo")
                } else {
                    path.clone()
                };
                assert!(
                    std::process::Command::new("mkfifo")
                        .args(["-m", "600"])
                        .arg(&fifo)
                        .status()
                        .unwrap()
                        .success()
                );
                if kind == "linked-fifo" {
                    std::os::unix::fs::symlink(&fifo, &path).unwrap();
                }
                if kind == "buffered" {
                    let mut writer = fs::OpenOptions::new()
                        .read(true)
                        .write(true)
                        .open(&fifo)
                        .unwrap();
                    _reader = Some(fs::File::open(&fifo).unwrap());
                    // Valid JSON with no writer: nonblocking alone would accept it.
                    writer
                        .write_all(&serde_json::to_vec(&every_record()[3]).unwrap())
                        .unwrap();
                }
                None
            }
            "directory" => {
                crate::dirs::private_dir(&path).unwrap();
                None
            }
            "socket" => Some(std::os::unix::net::UnixListener::bind(&path).unwrap()),
            _ => unreachable!(),
        };
        let before = fs::symlink_metadata(&path).unwrap().file_type();
        let output = bounded_status(&fake);
        assert_eq!(output.status.code(), Some(10), "{kind}: {output:?}");
        assert_status_store_error(&output);
        assert!(fake.invocations().is_empty(), "{kind}: provider was called");
        assert_eq!(fs::symlink_metadata(&path).unwrap().file_type(), before);
        assert_eq!(fs::read_dir(store.dir()).unwrap().count(), 1);
    }
}

#[test]
fn status_preserves_missing_malformed_and_valid_regular_record_behavior() {
    let fake = NewFake::new("store_regular_controls");
    let store = fake.store();
    let path = fake.record_path("op-store-every");
    let missing = bounded_status(&fake);
    assert_eq!(missing.status.code(), Some(11), "{missing:?}");
    let value: Value = serde_json::from_slice(&missing.stdout).unwrap();
    assert_eq!(value["result"], json!({"kind": "no_record"}));
    assert_eq!(fs::read_dir(store.dir()).unwrap().count(), 0);
    assert!(fake.invocations().is_empty());

    fs::write(&path, "not JSON").unwrap();
    let malformed = bounded_status(&fake);
    assert_eq!(malformed.status.code(), Some(10), "{malformed:?}");
    assert_status_store_error(&malformed);
    assert_eq!(fs::read(&path).unwrap(), b"not JSON");
    assert!(fake.invocations().is_empty());

    let bytes = serde_json::to_vec(&every_record()[3]).unwrap();
    fs::write(&path, &bytes).unwrap();
    let valid = bounded_status(&fake);
    assert_eq!(valid.status.code(), Some(0), "{valid:?}");
    let value: Value = serde_json::from_slice(&valid.stdout).unwrap();
    assert_eq!(
        value["result"]["report"]["result"]["outcome"]["kind"],
        "created"
    );
    assert_eq!(
        fake.invocations(),
        vec![vec!["thread", "show", THREAD, "--json"]]
    );
    assert_eq!(fs::read(&path).unwrap(), bytes);
    assert_eq!(fs::read_dir(store.dir()).unwrap().count(), 1);
}
