//! #244: binding reads expose the stored record without inspecting its
//! owner's lock or recovering it. The strict record reader still applies.

use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

use openwiz_core::model::Timestamp;
use openwiz_core::new_thread::record::NewThreadStore;
use openwiz_store::NewThreadFileStore;
use serde_json::{Value, json};

use crate::record_store::every_record;
use crate::support::{T0, op, private_dir};

fn snapshot(dir: &Path) -> BTreeMap<OsString, (Vec<u8>, u32)> {
    fs::read_dir(dir)
        .unwrap()
        .map(|entry| {
            let entry = entry.unwrap();
            (
                entry.file_name(),
                (
                    fs::read(entry.path()).unwrap(),
                    entry.metadata().unwrap().permissions().mode(),
                ),
            )
        })
        .collect()
}

#[test]
fn binding_reads_are_raw_read_only_and_never_inspect_the_claim_lock() {
    let state = private_dir("raw-binding-read").join("state");
    let store = NewThreadFileStore::open(&state).unwrap();
    let records = every_record();
    let path = store.record_path(&records[0].op_id);
    let dir = path.parent().unwrap();
    let lock = path.with_extension("lock");
    fs::write(&lock, "Synthetic lock sentinel").unwrap();
    let attempts = Arc::new(AtomicUsize::new(0));
    let count = Arc::clone(&attempts);
    let reader = NewThreadFileStore::open_read_only(&state)
        .unwrap()
        .unwrap()
        .with_before_lock(move |_| {
            count.fetch_add(1, Ordering::SeqCst);
        });
    for record in &records {
        fs::write(&path, serde_json::to_vec(record).unwrap()).unwrap();
        let before = snapshot(dir);
        assert_eq!(reader.load(&record.op_id).unwrap(), Some(record.clone()));
        assert_eq!(snapshot(dir), before, "no write or new file");
    }
    let before = snapshot(dir);
    assert_eq!(reader.load(&op("op-raw-missing")).unwrap(), None);
    assert_eq!(snapshot(dir), before, "an absent record stays absent");
    assert_eq!(attempts.load(Ordering::SeqCst), 0, "no lock attempt");

    // Status inspections still show recovery in memory, while binding
    // reads expose the unfinished record. Neither writes that recovery.
    fs::write(&path, serde_json::to_vec(&records[0]).unwrap()).unwrap();
    let before = snapshot(dir);
    let shown = reader
        .inspect(&records[0].op_id, Timestamp(T0.0 + 5))
        .unwrap()
        .unwrap();
    assert!(shown.recovered);
    assert_eq!(
        reader.load(&records[0].op_id).unwrap(),
        Some(records[0].clone())
    );
    assert_eq!(
        attempts.load(Ordering::SeqCst),
        1,
        "only inspect tried the lock"
    );
    assert_eq!(snapshot(dir), before);

    // A binding read must work even when the lock cannot be opened.
    fs::set_permissions(&lock, fs::Permissions::from_mode(0o000)).unwrap();
    assert_eq!(
        reader.load(&records[0].op_id).unwrap(),
        Some(records[0].clone())
    );
    fs::set_permissions(&lock, fs::Permissions::from_mode(0o600)).unwrap();
}

#[test]
fn binding_reads_refuse_malformed_and_foreign_op_records_without_writing() {
    let state = private_dir("strict-binding-read").join("state");
    let store = NewThreadFileStore::open(&state).unwrap();
    let record = &every_record()[0];
    let path = store.record_path(&record.op_id);
    let good = serde_json::to_string(record).unwrap();
    let value: Value = serde_json::from_str(&good).unwrap();
    let duplicate = good.replacen(
        "\"recovered\":false",
        "\"recovered\":false,\"recovered\":false",
        1,
    );
    assert_ne!(duplicate, good);
    let mut extra = value.clone();
    extra["extra"] = json!(1);
    let mut wrong_type = value.clone();
    wrong_type["text_bytes"] = json!("Synthetic wrong type");
    let mut tagged = value.clone();
    tagged["state"] = json!({"claimed": null});
    let mut moved = record.clone();
    moved.op_id = op("op-raw-foreign");
    moved.request_id = openwiz_core::new_thread::request_id(&moved.op_id);
    for bad in [
        duplicate,
        extra.to_string(),
        wrong_type.to_string(),
        tagged.to_string(),
        json!([]).to_string(),
        "not JSON".to_owned(),
        serde_json::to_string(&moved).unwrap(),
    ] {
        fs::write(&path, &bad).unwrap();
        let before = snapshot(path.parent().unwrap());
        assert!(store.load(&record.op_id).is_err(), "{bad}");
        assert_eq!(snapshot(path.parent().unwrap()), before, "no write");
    }
}
