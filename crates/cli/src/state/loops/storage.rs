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
        let state = Self { dir, _lock: lock };
        if fresh {
            state.save("index.json", &serde_json::json!([]))?;
            state.save("enabled.json", &serde_json::json!({}))?;
        }
        Ok(state)
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
    pub fn save_switch_state(&self, state: &SwitchState) -> Result<(), String> {
        self.save("enabled.json", &serde_json::json!({"schema":"openwiz.loop-switches.v1", "enabled":state.enabled,"events":state.events}))
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

#[cfg(test)]
mod tests {
    use super::Reader;
    use std::fs::{DirBuilder, OpenOptions};
    use std::io::Write;
    use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};

    #[test]
    fn an_indexed_run_without_its_record_is_refused_never_an_empty_history() {
        let dir = (0..100)
            .map(|n| {
                std::env::temp_dir().join(format!("openwiz-loop-index-{}-{n}", std::process::id()))
            })
            .find(|dir| DirBuilder::new().mode(0o700).create(dir).is_ok())
            .expect("a fresh fixture folder");
        DirBuilder::new()
            .mode(0o700)
            .create(dir.join("runs"))
            .unwrap();
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(dir.join("index.json"))
            .unwrap()
            .write_all(br#"["syn-run-1"]"#)
            .unwrap();
        let runs = Reader { dir: dir.clone() }.runs();
        std::fs::remove_dir_all(&dir).unwrap();
        assert_eq!(
            runs,
            Err("loop run history is incomplete or has unindexed records".to_owned())
        );
    }
}
