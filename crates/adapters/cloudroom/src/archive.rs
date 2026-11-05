//! Archiving a finished agent's thread (OpenWiz 0.0.6 spec 2, B4,
//! ClosedWiz#120): spec #116's "New writes: CloudRoom `thread archive`".
//!
//! One thread, through exactly one [`Invocation::ThreadArchive`] (`thread
//! archive <id> --json`; observed in help (0.43.1), the call never run), and
//! read back:
//!
//! 1. **Read first:** `thread show <id> --json`. A thread already archived
//!    is done, with no call (`launch-fleet`'s archive row: "one already
//!    archived … is done"); one not found has nothing to archive; one that
//!    can't be read is not archived blind.
//! 2. **The one call**, never retried. What it prints is not observed, so
//!    nothing reads it.
//! 3. **Read back:** `thread show <id> --json` again. Only `archivedAt` set
//!    there makes it [`ArchiveOutcome::Archived`]; anything else says so.
//!
//! A `thread show` is read only for its `thread.id` and `thread.archivedAt`,
//! and only from JSON with no key given twice. Every message here is
//! OpenWiz's own words; nothing `room-cli` prints reaches one, except the
//! runner's safe first error line ([`SourceError`]'s own wording).

use std::fmt;
use std::time::Instant;

use serde::Serialize;
use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::Value;

use openwiz_core::source::SourceError;

use crate::allowlist::{Invocation, ThreadId};
use crate::process;
use crate::source::CloudRoomSource;

/// What archiving one thread came to.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ArchiveOutcome {
    /// It was archived already. No call was made.
    AlreadyArchived,
    /// The call was made, and `thread show` now shows it archived.
    Archived,
    /// `thread show` found no such thread. No call was made.
    NotFound,
    /// It could not be read first, so no call was made.
    NotRead { words: String },
    /// The call was made, and `thread show` shows it still not archived.
    NotArchived { words: String },
    /// The call was made, and whether it took can't be told: the read-back
    /// failed.
    Unconfirmed { words: String },
}

impl CloudRoomSource {
    /// Archives the thread `id`, once, within `deadline`. See the module
    /// documentation.
    pub fn archive_thread(&self, id: &ThreadId, deadline: Instant) -> ArchiveOutcome {
        match self.archived(id, deadline) {
            Ok(Some(true)) => return ArchiveOutcome::AlreadyArchived,
            Ok(Some(false)) => {}
            Ok(None) => return ArchiveOutcome::NotFound,
            Err(words) => return ArchiveOutcome::NotRead { words },
        }
        let call = process::run(
            self.program(),
            &Invocation::ThreadArchive(id.clone()),
            deadline,
        );
        match (self.archived(id, deadline), call) {
            (Ok(Some(true)), _) => ArchiveOutcome::Archived,
            (Ok(Some(false)), Ok(_)) => ArchiveOutcome::NotArchived {
                words: "thread archive exited 0, but thread show still shows it not archived"
                    .to_owned(),
            },
            (Ok(Some(false)), Err(e)) => ArchiveOutcome::NotArchived {
                words: format!("thread archive {e}; thread show still shows it not archived"),
            },
            (Ok(None), _) => ArchiveOutcome::Unconfirmed {
                words: "thread show no longer finds the thread after thread archive".to_owned(),
            },
            (Err(words), _) => ArchiveOutcome::Unconfirmed { words },
        }
    }

    /// Whether `thread show` says `id` is archived; `None` when it finds
    /// no such thread; why not, when it can't be read.
    fn archived(&self, id: &ThreadId, deadline: Instant) -> Result<Option<bool>, String> {
        match process::run(
            self.program(),
            &Invocation::ThreadShow(id.clone()),
            deadline,
        ) {
            Ok(out) => archived_at(&out, id).map(Some),
            Err(SourceError::CommandFailed { ref detail, .. })
                if detail.starts_with(process::NOT_FOUND_LINE) =>
            {
                Ok(None)
            }
            Err(e) => Err(format!("thread show {e}")),
        }
    }
}

/// `thread.archivedAt` of a `thread show` for `id`: a time (archived) or
/// null (not archived). Anything else is not read.
fn archived_at(out: &[u8], id: &ThreadId) -> Result<bool, String> {
    serde_json::from_slice::<NoRepeatedKeys>(out)
        .map_err(|_| "thread show printed something that is not JSON, or a key twice".to_owned())?;
    let doc: Value =
        serde_json::from_slice(out).map_err(|_| "thread show is not JSON".to_owned())?;
    let Some(thread) = doc.get("thread").filter(|t| t.is_object()) else {
        return Err("thread show has no thread object".to_owned());
    };
    if thread.get("id").and_then(Value::as_str) != Some(id.as_str()) {
        return Err("thread show describes another thread".to_owned());
    }
    match thread.get("archivedAt") {
        Some(Value::Null) => Ok(false),
        Some(Value::Number(n)) if n.as_u64().is_some() => Ok(true),
        Some(_) => Err("thread show's archivedAt is neither a time nor null".to_owned()),
        None => Err("thread show has no archivedAt".to_owned()),
    }
}

/// Any JSON value, read only to refuse a key given twice in one object.
struct NoRepeatedKeys;

impl<'de> Deserialize<'de> for NoRepeatedKeys {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_any(NoRepeatedKeysVisitor)
    }
}

struct NoRepeatedKeysVisitor;

impl<'de> Visitor<'de> for NoRepeatedKeysVisitor {
    type Value = NoRepeatedKeys;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("a JSON value with no key given twice")
    }

    fn visit_unit<E: de::Error>(self) -> Result<NoRepeatedKeys, E> {
        Ok(NoRepeatedKeys)
    }

    fn visit_bool<E: de::Error>(self, _: bool) -> Result<NoRepeatedKeys, E> {
        Ok(NoRepeatedKeys)
    }

    fn visit_i64<E: de::Error>(self, _: i64) -> Result<NoRepeatedKeys, E> {
        Ok(NoRepeatedKeys)
    }

    fn visit_u64<E: de::Error>(self, _: u64) -> Result<NoRepeatedKeys, E> {
        Ok(NoRepeatedKeys)
    }

    fn visit_f64<E: de::Error>(self, _: f64) -> Result<NoRepeatedKeys, E> {
        Ok(NoRepeatedKeys)
    }

    fn visit_str<E: de::Error>(self, _: &str) -> Result<NoRepeatedKeys, E> {
        Ok(NoRepeatedKeys)
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<NoRepeatedKeys, A::Error> {
        while seq.next_element::<NoRepeatedKeys>()?.is_some() {}
        Ok(NoRepeatedKeys)
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<NoRepeatedKeys, A::Error> {
        let mut keys: Vec<String> = Vec::new();
        while let Some(key) = map.next_key::<String>()? {
            if keys.contains(&key) {
                return Err(de::Error::custom("a key given twice"));
            }
            map.next_value::<NoRepeatedKeys>()?;
            keys.push(key);
        }
        Ok(NoRepeatedKeys)
    }
}
