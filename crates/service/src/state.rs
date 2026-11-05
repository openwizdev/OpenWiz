//! The service's owner-only, atomic state. Startup never re-dispatches a try.
use crate::document::{self, Document};
use serde_json::{Value, json};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    os::unix::fs::OpenOptionsExt,
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};

pub struct State {
    root: PathBuf,
    value: Value,
}
impl State {
    pub fn load(root: &Path, now: u64) -> Result<Self, String> {
        let (text, missing) = match openwiz_store::loops::read_service_state(root)? {
            Some(text) => (text, false),
            None => (include_str!("empty-state.json").to_owned(), true),
        };
        let mut value = document::read(Document::State, &text)
            .map_err(|why| format!("service/state.json: {why}"))?;
        let before = value.clone();
        if let Some(started) = value["tick"]["running"]["started_at"].as_u64() {
            if started > now {
                return Err("service/state.json: tick start is after startup".to_owned());
            }
            value["tick"]["running"] = Value::Null;
            value["tick"]["last_ended"] =
                json!({"started_at":started,"ended_at":now,"how":"stopped"});
        }
        for incident in value["incidents"].as_array_mut().unwrap() {
            if let Some(tries) = incident.get_mut("tries") {
                for name in ["first", "second"] {
                    if !tries[name].is_null() && tries[name]["outcome"].is_null() {
                        tries[name]["outcome"] = json!({"state":"interrupted"});
                    }
                }
            }
        }
        let mut state = Self {
            root: root.to_owned(),
            value: before,
        };
        if missing || value != state.value {
            state.save(value)?;
        }
        Ok(state)
    }
    pub fn snapshot(&self) -> &Value {
        &self.value
    }

    /// #2034: publish only the optional public notification summary
    /// `{state, preference_generation, last_pass_at, reason}`. It holds no
    /// subscription, token, key, endpoint or path; other fields are unchanged.
    pub fn publish_notifications(&mut self, summary: Value) -> Result<(), String> {
        let mut value = self.value.clone();
        value["notifications"] = summary;
        self.save(value)
    }

    /// Save and sync before publishing the new in-memory state.
    pub fn save(&mut self, value: Value) -> Result<(), String> {
        let body = value.to_string();
        document::read(Document::State, &body)?;
        crate::paths::inspect(&self.root)?;
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let temp = self.root.join("service").join(format!(
            ".state-{}-{}.tmp",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&temp)
            .map_err(|_| "service/state.json: cannot create private temporary state".to_owned())?;
        let write = (|| -> std::io::Result<()> {
            file.write_all(body.as_bytes())?;
            file.sync_all()?;
            fs::rename(&temp, self.root.join("service/state.json"))?;
            File::open(self.root.join("service"))?.sync_all()
        })();
        if write.is_err() {
            let _ = fs::remove_file(&temp);
            return Err("service/state.json: atomic save or sync failed".to_owned());
        }
        self.value = value;
        Ok(())
    }
}

pub fn status(
    state: &Value,
    build: &str,
    since: u64,
    port: u16,
    server_since: Option<u64>,
    now: u64,
) -> Result<Value, String> {
    let mut value = state.clone();
    value.as_object_mut().unwrap().remove("next_incident");
    value["schema"] = json!("openwiz.service-status.v1");
    value["at"] = json!(now);
    value["service"] = json!({"build":build,"since":since});
    value["server"] =
        json!({"port":port,"running":server_since.map(|since| json!({"since":since}))});
    document::read(Document::Status, &value.to_string())
}
