//! One owner per pass and atomic, synced private records. No repository writes.
use super::{SwitchError, document};
use openwiz_core::messaging::OpId;
use serde_json::Value;
use std::{
    fs::{self, File, OpenOptions, TryLockError},
    io::Write,
    os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};

pub struct Storage {
    pub dir: PathBuf,
    _lock: File,
}
impl Drop for Storage {
    fn drop(&mut self) {
        // A concurrent fork can temporarily inherit the descriptor before
        // exec closes it. Release the lock explicitly, as the service does,
        // so that inherited descriptor cannot hold the next pass out.
        let _ = self._lock.unlock();
    }
}
fn inspect(path: &Path, directory: bool) -> Result<(), String> {
    let meta =
        fs::symlink_metadata(path).map_err(|_| "cannot inspect private loop state".to_owned())?;
    let uid = crate::state::owner::effective_uid()?;
    if meta.uid() != uid
        || meta.mode() & 0o077 != 0
        || if directory {
            !meta.is_dir()
        } else {
            !meta.is_file() || meta.nlink() != 1
        }
    {
        return Err("loop state must be owner-only, regular and not linked".to_owned());
    }
    Ok(())
}
fn directory(path: &Path) -> Result<(), String> {
    match fs::symlink_metadata(path) {
        Ok(_) => inspect(path, true),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            fs::DirBuilder::new()
                .mode(0o700)
                .create(path)
                .map_err(|_| "cannot create private loop directory".to_owned())?;
            File::open(path.parent().unwrap())
                .and_then(|f| f.sync_all())
                .map_err(|_| "cannot sync loop directory".to_owned())?;
            inspect(path, true)
        }
        Err(_) => Err("cannot inspect loop directory".to_owned()),
    }
}
impl Storage {
    pub fn open(root: &Path) -> Result<Self, String> {
        Self::open_with_retry(root, &mut || false).map_err(|error| match error {
            SwitchError::Busy => "another loop pass owns the state".to_owned(),
            SwitchError::Refused(reason) => reason,
        })
    }
    pub(super) fn open_with_retry(
        root: &Path,
        retry: &mut dyn FnMut() -> bool,
    ) -> Result<Self, SwitchError> {
        super::paths::inspect(root)?;
        let dir = root.join("service/loops");
        let fresh = match fs::symlink_metadata(&dir) {
            Ok(_) => false,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => true,
            Err(_) => return Err("cannot inspect loop directory".into()),
        };
        directory(&dir)?;
        if fresh {
            directory(&dir.join("runs"))?;
        } else {
            inspect(&dir.join("runs"), true)?;
        }
        let path = dir.join("run.lock");
        match fs::symlink_metadata(&path) {
            Ok(_) => inspect(&path, false)?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err("cannot inspect loop lock".into()),
        }
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .open(&path)
            .map_err(|_| "cannot open loop lock".to_owned())?;
        inspect(&path, false)?;
        loop {
            match lock.try_lock() {
                Ok(()) => break,
                Err(TryLockError::WouldBlock) if retry() => continue,
                Err(TryLockError::WouldBlock) => return Err(SwitchError::Busy),
                Err(TryLockError::Error(_)) => {
                    return Err("cannot acquire private loop state lock".into());
                }
            }
        }
        // Re-read every snapshot only after taking this cross-process lock.
        let state = Self { dir, _lock: lock };
        if fresh {
            state.save("index.json", &serde_json::json!([]))?;
            state.save("enabled.json", &serde_json::json!({}))?;
        }
        Ok(state)
    }
    fn index(&self) -> Result<Vec<String>, String> {
        Reader {
            dir: self.dir.clone(),
        }
        .index()
    }
    pub fn runs(&self) -> Result<Vec<Value>, String> {
        Reader {
            dir: self.dir.clone(),
        }
        .runs()
    }
    pub fn switches(&self) -> Result<serde_json::Map<String, Value>, String> {
        Ok(self.switch_state()?.enabled)
    }
    pub fn switch_state(&self) -> Result<SwitchState, String> {
        Reader {
            dir: self.dir.clone(),
        }
        .switch_state()
    }
}

// Shared strict decoders; this handle neither creates state nor owns a lock.
struct Reader {
    dir: PathBuf,
}
impl Reader {
    fn index(&self) -> Result<Vec<String>, String> {
        let path = self.dir.join("index.json");
        inspect(&path, false)?;
        let value = document::parse(
            &fs::read_to_string(path)
                .map_err(|_| "cannot read complete loop run index".to_owned())?,
        )?;
        let values = value.as_array().ok_or("invalid loop run index")?;
        let mut ids = std::collections::BTreeSet::new();
        for value in values {
            let id = value
                .as_str()
                .filter(|id| OpId::parse(id).is_ok())
                .ok_or("invalid loop run index")?;
            if !ids.insert(id.to_owned()) {
                return Err("duplicate loop run index entry".to_owned());
            }
        }
        Ok(ids.into_iter().collect())
    }
    pub fn runs(&self) -> Result<Vec<Value>, String> {
        let expected = self.index()?;
        let mut runs = Vec::new();
        for entry in fs::read_dir(self.dir.join("runs"))
            .map_err(|_| "cannot read complete loop run history".to_owned())?
        {
            let entry = entry.map_err(|_| "cannot read complete loop run history".to_owned())?;
            let name = entry.file_name();
            let name = name.to_str().ok_or("invalid run filename")?;
            if name.starts_with(".tmp-") {
                continue;
            }
            let id = name
                .strip_suffix(".json")
                .and_then(|s| OpId::parse(s).ok())
                .ok_or("unexpected loop run file")?;
            inspect(&entry.path(), false)?;
            let body = fs::read_to_string(entry.path())
                .map_err(|_| "cannot read complete loop run history".to_owned())?;
            let run = document::read("run", &body)?;
            if run["id"].as_str() != Some(id.as_str()) {
                return Err("loop run filename differs from its identity".to_owned());
            }
            runs.push(run);
        }
        runs.sort_by(|a, b| a["id"].as_str().cmp(&b["id"].as_str()));
        if runs
            .iter()
            .map(|r| r["id"].as_str().unwrap())
            .ne(expected.iter().map(String::as_str))
        {
            return Err("loop run history is incomplete or has unindexed records".to_owned());
        }
        Ok(runs)
    }
    pub fn switch_state(&self) -> Result<SwitchState, String> {
        let path = self.dir.join("enabled.json");
        inspect(&path, false)?;
        let value = document::parse(
            &fs::read_to_string(path).map_err(|_| "cannot read durable loop switches")?,
        )?;
        let object = value.as_object().ok_or("invalid durable loop switches")?;
        // L3's existing map contains only initial/effective states, no invented
        // historical actor. First L6 save upgrades it atomically.
        if object.values().all(Value::is_boolean) {
            validate_enabled(object)?;
            return Ok(SwitchState {
                enabled: object.clone(),
                events: vec![],
            });
        }
        if !exact(object, &["schema", "enabled", "events"])
            || value["schema"] != "openwiz.loop-switches.v1"
        {
            return Err("invalid audited loop switches".to_owned());
        }
        let enabled = value["enabled"]
            .as_object()
            .ok_or("invalid switch states")?;
        validate_enabled(enabled)?;
        let events = value["events"].as_array().ok_or("invalid switch audit")?;
        let mut previous = 0;
        let mut latest = std::collections::BTreeMap::new();
        for event in events {
            let object = event.as_object().ok_or("invalid switch event")?;
            if !exact(
                object,
                &[
                    "loop_id",
                    "definition_revision",
                    "repository",
                    "project",
                    "enabled",
                    "actor",
                    "at_ms",
                ],
            ) || event["loop_id"]
                .as_str()
                .is_none_or(|id| OpId::parse(id).is_err())
                || event["definition_revision"].as_str().is_none_or(|id| {
                    !matches!(id.len(), 40 | 64)
                        || !id
                            .bytes()
                            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                })
                || event["repository"].as_str().is_none_or(|repo| {
                    openwiz_core::fleet::starts::Repository::parse(repo).is_err()
                })
                || event["project"]
                    .as_str()
                    .is_none_or(|id| !super::valid_project(id))
                || event["actor"]
                    .as_str()
                    .is_none_or(|actor| !super::valid_actor(actor))
                || !event["enabled"].is_boolean()
                || event["at_ms"].as_u64().is_none_or(|at| at < previous)
            {
                return Err("invalid switch event".to_owned());
            }
            previous = event["at_ms"].as_u64().unwrap();
            latest.insert(event["loop_id"].as_str().unwrap(), &event["enabled"]);
        }
        if latest.iter().any(|(id, on)| enabled.get(*id) != Some(*on)) {
            return Err("switch audit disagrees with effective state".to_owned());
        }
        Ok(SwitchState {
            enabled: enabled.clone(),
            events: events.clone(),
        })
    }
}

impl Storage {
    pub fn save_switches(&self, enabled: &serde_json::Map<String, Value>) -> Result<(), String> {
        let mut state = self.switch_state()?;
        state.enabled = enabled.clone();
        self.save_switch_state(&state)
    }
    pub fn save_switch_state(&self, state: &SwitchState) -> Result<(), String> {
        self.save("enabled.json", &serde_json::json!({"schema":"openwiz.loop-switches.v1", "enabled":state.enabled,"events":state.events}))
    }
    pub fn save_run(&self, run: &Value) -> Result<(), String> {
        document::validate("run", run)?;
        let id = run["id"].as_str().unwrap();
        let mut ids = self.index()?;
        if !ids.iter().any(|old| old == id) {
            ids.push(id.to_owned());
            ids.sort();
            // Index the identity before its first record, which itself is
            // saved before the check. A partial save cannot become an empty
            // history and replay an occurrence on restart.
            self.save("index.json", &serde_json::json!(ids))?;
        }
        self.save(&format!("runs/{}.json", run["id"].as_str().unwrap()), run)
    }
    /// Read optional settled observations under the pass lock; only absence is empty.
    pub fn settled_agents(&self) -> Result<Option<Value>, String> {
        let path = self.dir.join("settled.json");
        match fs::symlink_metadata(&path) {
            Ok(_) => inspect(&path, false)?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err("cannot inspect settled loop agents".to_owned()),
        }
        let text =
            fs::read_to_string(path).map_err(|_| "cannot read settled loop agents".to_owned())?;
        document::parse(&text).map(Some)
    }
    pub fn save(&self, name: &str, value: &Value) -> Result<(), String> {
        let path = self.dir.join(name);
        let parent = path.parent().unwrap();
        inspect(parent, true)?;
        match fs::symlink_metadata(&path) {
            Ok(_) => inspect(&path, false)?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err("cannot inspect loop record".to_owned()),
        }
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let temp = parent.join(format!(
            ".tmp-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let result = (|| -> std::io::Result<()> {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&temp)?;
            file.write_all(value.to_string().as_bytes())?;
            file.sync_all()?;
            fs::rename(&temp, &path)?;
            File::open(parent)?.sync_all()
        })();
        if result.is_err() {
            let _ = fs::remove_file(temp);
            return Err("cannot save and sync loop state".to_owned());
        }
        Ok(())
    }
}

/// Effective state and its audit are replaced in one durable write.
pub struct SwitchState {
    pub enabled: serde_json::Map<String, Value>,
    pub events: Vec<Value>,
}
fn exact(object: &serde_json::Map<String, Value>, keys: &[&str]) -> bool {
    object.len() == keys.len() && keys.iter().all(|key| object.contains_key(*key))
}
fn validate_enabled(enabled: &serde_json::Map<String, Value>) -> Result<(), String> {
    if enabled
        .iter()
        .any(|(id, on)| OpId::parse(id).is_err() || !on.is_boolean())
    {
        return Err("invalid durable loop switches".to_owned());
    }
    Ok(())
}

#[derive(Debug, PartialEq)]
pub struct Snapshot {
    pub runs: Vec<Value>,
    pub enabled: serde_json::Map<String, Value>,
}
/// One bounded read of existing state, independent of the scheduler's lock.
/// Two complete matching collections are required. A partial admission or a
/// changing record refuses the snapshot; callers must preserve unknown.
pub fn read_snapshot(root: &Path) -> Result<Snapshot, String> {
    if !root.is_absolute()
        || root.components().any(|c| {
            !matches!(
                c,
                std::path::Component::RootDir | std::path::Component::Normal(_)
            )
        })
    {
        return Err("invalid loop state path".into());
    }
    for ancestor in root.ancestors() {
        let m =
            fs::symlink_metadata(ancestor).map_err(|_| "cannot inspect loop state ancestors")?;
        if m.file_type().is_symlink()
            || !m.is_dir()
            || ancestor
                .join(".git")
                .try_exists()
                .map_err(|_| "cannot inspect loop state boundary")?
        {
            return Err("unsafe loop state boundary".into());
        }
    }
    for path in [
        root.to_owned(),
        root.join("service"),
        root.join("service/loops"),
        root.join("service/loops/runs"),
    ] {
        inspect(&path, true)?;
    }
    let reader = Reader {
        dir: root.join("service/loops"),
    };
    let collect = || -> Result<_, String> { Ok((reader.runs()?, reader.switch_state()?)) };
    let (runs, switches) = collect()?;
    let (again, next) = collect()?;
    if runs != again || switches.enabled != next.enabled || switches.events != next.events {
        return Err("loop observation changed during read".into());
    }
    Ok(Snapshot {
        runs,
        enabled: switches.enabled,
    })
}
