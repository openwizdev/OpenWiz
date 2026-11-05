//! The start record on disk (OpenWiz 0.0.6 spec 2, B4, ClosedWiz#120): one
//! record per start (a ticket's builder, or a reviewer for one pull request
//! at one head commit), in the same state directory as the send and
//! new-thread records, through the same [`Store`] code: the directory
//! checks, the lock files and the atomic, synced writes.
//!
//! Layout, under the state directory (0700):
//!
//! - `starts/` (0700);
//! - `starts/<start id>.json` (0600): the record, replaced atomically. The
//!   id is [`StartKey::id`]: a hash of the start's key, so a repository's
//!   name never reaches a file name;
//! - `starts/<start id>.lock` (0600): the start's lock. A tick holds it from
//!   reading the record until it has recorded what came of its one call, so
//!   two ticks never start one agent twice. The operating system lets go of
//!   it when the tick stops.
//!
//! Unlike `send`'s and `new_thread`'s claims, the lock is taken again by
//! every tick, and the record keeps changing: one attempt after another.
//! A tick that stopped leaves its last attempt pending; nothing here
//! recovers it, because only `new_thread`'s status read can say what came of
//! it, and the core reads that before anything else
//! ([`start_agent`](openwiz_core::fleet::starts::start_agent)).
//!
//! A record is read back strictly, by hand ([`read`]): never serde's derived
//! readers. A record that isn't exactly its shape, or doesn't agree with
//! itself, is refused, and nothing is started from it.

use std::fs::TryLockError;

use openwiz_core::fleet::model::{Commit, Number};
use openwiz_core::fleet::starts::{
    Attempt, AttemptOutcome, Locked, NotCreated, Repository, START_RECORD_SCHEMA_ID, StartKey,
    StartRecord, StartStore,
};
use openwiz_core::messaging::OpId;
use openwiz_core::messaging::record::StoreError;
use openwiz_core::model::Timestamp;
use openwiz_core::new_thread::Settings;
use openwiz_core::new_thread::read::StrictJson;
use serde_json::{Map, Value};

use crate::{Area, Kind, Store, io_error};

/// The start record (OpenWiz 0.0.6, ClosedWiz#120): `starts/`.
#[derive(Debug)]
pub struct Starts;

impl Area for Starts {
    const DIR: &'static str = "starts";
    const WHAT: &'static str = "start record";
}

/// Only the record's reading, writing and file name are the store's
/// [`Kind`] here. A start record is never claimed or recovered through the
/// store's claims (see the module documentation), so it is always
/// "finished" to them, never "claimed", and recovering one changes nothing.
impl Kind for Starts {
    type Record = StartRecord;

    fn op_id(record: &StartRecord) -> &OpId {
        record.id()
    }

    fn is_finished(_: &StartRecord) -> bool {
        true
    }

    fn is_claimed(_: &StartRecord) -> bool {
        false
    }

    fn recover(record: &StartRecord, _: Timestamp) -> StartRecord {
        record.clone()
    }

    fn read(text: &str) -> Result<StartRecord, String> {
        read(text)
    }

    fn body(record: &StartRecord) -> Result<Vec<u8>, String> {
        serde_json::to_vec_pretty(record).map_err(|e| e.to_string())
    }
}

/// The file-backed start record.
pub type StartFileStore = Store<Starts>;

impl StartStore for Store<Starts> {
    fn lock(&self, key: &StartKey) -> Result<Locked, StoreError> {
        self.refuse_if_read_only()?;
        let id = key.id();
        let lock = self.lock_file(&id)?;
        match lock.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Ok(Locked::Busy),
            Err(TryLockError::Error(e)) => {
                return Err(io_error("lock", &self.lock_path(&id), &e));
            }
        }
        let lock = crate::ClaimLock(lock);
        // Under the lock: the record as it is now, never as it was read
        // before.
        let record = self.record(&id)?;
        if let Some(r) = &record
            && r.key() != key
        {
            return Err(StoreError(format!(
                "{} holds the record of another start",
                self.record_path(&id).display()
            )));
        }
        self.held
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .insert(id, lock);
        Ok(Locked::Mine(record.map(Box::new)))
    }

    fn write(&self, record: &StartRecord) -> Result<(), StoreError> {
        self.update_record(record)
    }

    fn unlock(&self, key: &StartKey) {
        self.release_claim(&key.id());
    }

    fn inspect(&self, key: &StartKey) -> Result<Option<StartRecord>, StoreError> {
        let id = key.id();
        let record = self.record(&id)?;
        if let Some(r) = &record
            && r.key() != key
        {
            return Err(StoreError(format!(
                "{} holds the record of another start",
                self.record_path(&id).display()
            )));
        }
        Ok(record)
    }
}

/// Reads a start record's text, strictly: JSON with no key given twice and
/// no fractional number ([`StrictJson`]); every object with exactly its
/// keys, each of its own type; each label a string from its list; each
/// outcome exactly its kind's keys; then the core's own checks
/// ([`StartRecord::from_parts`]). Why not, in OpenWiz's words, with the path
/// of what was refused, never the record's content.
pub fn read(text: &str) -> Result<StartRecord, String> {
    serde_json::from_str::<StrictJson>(text)
        .map_err(|_| "not JSON, or a key given twice".to_owned())?;
    let doc: Value = serde_json::from_str(text).map_err(|_| "not JSON".to_owned())?;
    let path = "record";
    let top = exact(&doc, path, &RECORD_KEYS)?;
    if string(top, path, "schema")? != START_RECORD_SCHEMA_ID {
        return Err(format!("{path}.schema: not {START_RECORD_SCHEMA_ID}"));
    }
    let id = OpId::parse(&string(top, path, "id")?).map_err(|_| format!("{path}.id: not an id"))?;
    let key = read_key(&top["key"])?;
    let project_id = string(top, path, "project_id")?;
    let settings = read_settings(&top["settings"])?;
    let Value::Array(items) = &top["attempts"] else {
        return Err(format!("{path}.attempts: not a list"));
    };
    let attempts = items
        .iter()
        .enumerate()
        .map(|(i, item)| read_attempt(item, &format!("{path}.attempts[{i}]")))
        .collect::<Result<Vec<_>, _>>()?;
    StartRecord::from_parts(id, key, project_id, settings, attempts)
}

const RECORD_KEYS: [&str; 6] = ["schema", "id", "key", "project_id", "settings", "attempts"];

/// `value` as an object with exactly `keys` (each once: the text was read
/// with no key twice).
fn exact<'a>(
    value: &'a Value,
    path: &str,
    keys: &[&str],
) -> Result<&'a Map<String, Value>, String> {
    let Value::Object(map) = value else {
        return Err(format!("{path}: not an object"));
    };
    if map.keys().any(|k| !keys.contains(&k.as_str())) {
        return Err(format!("{path}: has a key that is not one of its keys"));
    }
    if let Some(missing) = keys.iter().find(|k| !map.contains_key(**k)) {
        return Err(format!("{path}.{missing}: missing"));
    }
    Ok(map)
}

fn string(map: &Map<String, Value>, path: &str, key: &str) -> Result<String, String> {
    match &map[key] {
        Value::String(s) => Ok(s.clone()),
        _ => Err(format!("{path}.{key}: not a string")),
    }
}

fn read_key(value: &Value) -> Result<StartKey, String> {
    let path = "record.key";
    let map = exact(value, path, &["repository", "role", "number", "commit"])?;
    let written = string(map, path, "repository")?;
    let repository =
        Repository::parse(&written).map_err(|_| format!("{path}.repository: not owner/name"))?;
    // Only as the store writes it: in lower case (review R2).
    if repository.as_str() != written {
        return Err(format!("{path}.repository: not in lower case"));
    }
    let number = match &map["number"] {
        Value::Number(n) => n.as_u64().and_then(Number::new),
        _ => None,
    }
    .ok_or_else(|| format!("{path}.number: not a whole number of 1 or more"))?;
    let commit = match &map["commit"] {
        Value::Null => None,
        Value::String(s) => {
            Some(Commit::parse(s).ok_or_else(|| format!("{path}.commit: not a full commit id"))?)
        }
        _ => return Err(format!("{path}.commit: not a string or null")),
    };
    match (string(map, path, "role")?.as_str(), commit) {
        ("builder", None) => Ok(StartKey::builder(repository, number)),
        ("reviewer", Some(commit)) => Ok(StartKey::reviewer(repository, number, commit)),
        ("builder", Some(_)) => Err(format!("{path}.commit: a builder's is null")),
        ("reviewer", None) => Err(format!("{path}.commit: a reviewer's is a commit")),
        _ => Err(format!("{path}.role: not builder or reviewer")),
    }
}

fn read_settings(value: &Value) -> Result<Settings, String> {
    let path = "record.settings";
    let map = exact(value, path, &["harness", "model", "effort"])?;
    Ok(Settings {
        harness: string(map, path, "harness")?,
        model: string(map, path, "model")?,
        effort: string(map, path, "effort")?,
    })
}

fn read_attempt(value: &Value, path: &str) -> Result<Attempt, String> {
    let map = exact(value, path, &["op_id", "at", "outcome"])?;
    let op_id = OpId::parse(&string(map, path, "op_id")?)
        .map_err(|_| format!("{path}.op_id: not an op id"))?;
    let at = match &map["at"] {
        Value::Number(n) => n.as_i64().map(Timestamp),
        _ => None,
    }
    .ok_or_else(|| format!("{path}.at: not a time in milliseconds"))?;
    let outcome = read_outcome(&map["outcome"], &format!("{path}.outcome"))?;
    Ok(Attempt { op_id, at, outcome })
}

fn read_outcome(value: &Value, path: &str) -> Result<AttemptOutcome, String> {
    let kind = match value {
        Value::Object(map) => match map.get("kind") {
            Some(Value::String(kind)) => kind.as_str(),
            _ => return Err(format!("{path}.kind: missing, or not a string")),
        },
        _ => return Err(format!("{path}: not an object")),
    };
    Ok(match kind {
        "pending" => {
            exact(value, path, &["kind"])?;
            AttemptOutcome::Pending
        }
        "created" => {
            let map = exact(value, path, &["kind", "thread_id"])?;
            AttemptOutcome::Created {
                thread_id: string(map, path, "thread_id")?,
            }
        }
        "not_created" => {
            let map = exact(value, path, &["kind", "status", "words"])?;
            let status = match string(map, path, "status")?.as_str() {
                "refused" => NotCreated::Refused,
                "failed" => NotCreated::Failed,
                _ => return Err(format!("{path}.status: not refused or failed")),
            };
            AttemptOutcome::NotCreated {
                status,
                words: string(map, path, "words")?,
            }
        }
        "uncertain" => {
            let map = exact(value, path, &["kind", "words"])?;
            AttemptOutcome::Uncertain {
                words: string(map, path, "words")?,
            }
        }
        _ => return Err(format!("{path}.kind: not one of its kinds")),
    })
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    /// A builder's record, its one attempt pending, by hand; synthetic.
    fn good() -> Value {
        let key = StartKey::builder(
            Repository::parse("synthetic-owner/synthetic-repo").unwrap(),
            Number::new(7).unwrap(),
        );
        json!({
            "schema": "openwiz.start-record.v1",
            "id": key.id().as_str(),
            "key": {
                "repository": "synthetic-owner/synthetic-repo",
                "role": "builder",
                "number": 7,
                "commit": null,
            },
            "project_id": "prj_syn_0001",
            "settings": {"harness": "codex", "model": "gpt-6.1-sol", "effort": "high"},
            "attempts": [
                {"op_id": "op-syn-1", "at": 0, "outcome": {"kind": "pending"}},
            ],
        })
    }

    #[test]
    fn reader_errors_keep_paths_without_record_content() {
        const MARKER: &str = "SYNTHETIC_PRIVATE_KEY_MARKER";
        let mut leaks = Vec::new();
        for outcome in [
            json!({"kind": "pending"}),
            json!({"kind": "created", "thread_id": "thr_syn_0001"}),
            json!({"kind": "not_created", "status": "refused", "words": "Synthetic refusal"}),
            json!({"kind": "uncertain", "words": "Synthetic uncertainty"}),
        ] {
            let mut baseline = good();
            baseline["attempts"][0]["outcome"] = outcome;
            read(&baseline.to_string()).expect("the unmodified record is valid");
            for (pointer, path) in [
                ("", "record"),
                ("/key", "record.key"),
                ("/settings", "record.settings"),
                ("/attempts/0", "record.attempts[0]"),
                ("/attempts/0/outcome", "record.attempts[0].outcome"),
            ] {
                let mut record = baseline.clone();
                record
                    .pointer_mut(pointer)
                    .unwrap()
                    .as_object_mut()
                    .unwrap()
                    .insert(MARKER.to_owned(), json!(null));
                let error = read(&record.to_string()).expect_err("unknown keys must be refused");
                assert!(error.starts_with(&format!("{path}:")), "{path}: {error}");
                if error.contains(MARKER) {
                    leaks.push(error);
                }
            }
        }
        assert!(leaks.is_empty(), "record content leaked: {leaks:#?}");
    }
}
