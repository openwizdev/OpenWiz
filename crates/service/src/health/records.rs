//! Contract record formatting and conservative, durable comment reconciliation.
use openwiz_adapter_github::{
    process::Executor,
    tick::TickReads,
    writes::{self, Body, Confirmed, Write},
};
use openwiz_core::{health::model::Number, messaging::sha256_hex};
use serde_json::{Value, json};
use std::{
    fs::{self, DirBuilder, File, OpenOptions},
    io::Write as _,
    os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt},
    path::Path,
    sync::atomic::{AtomicU64, Ordering},
    time::Instant,
};
pub fn render(incident: &Value, slot: Option<&str>) -> Result<String, String> {
    let mut record = json!({"schema":"openwiz.service-record.v1","kind":if slot.is_some(){"fix"}else{"needs_you"},"incident":incident["id"],"check":incident["check"],"broken":incident["broken"]});
    for key in ["loop", "spec", "loop_id"] {
        if let Some(v) = incident.get(key) {
            record[key] = v.clone();
        }
    }
    let subject = match incident["check"].as_str().unwrap() {
        "loop" => format!(
            "the loop {} ({})",
            incident["loop"]["id"].as_str().unwrap(),
            incident["loop"]["name"].as_str().unwrap()
        ),
        "watchdog" => format!("the OpenWiz loop {}", incident["loop_id"].as_str().unwrap()),
        "tick" => "the tick".into(),
        "server" => "the server".into(),
        "cloudroom" => "CloudRoom".into(),
        "fleet_thread" => format!("the fleet thread of #{}", incident["spec"]),
        _ => return Err("invalid record subject".into()),
    };
    let watchdog_words;
    let broken = match incident["broken"]["what"].as_str().unwrap() {
        "missed" => {
            watchdog_words = format!("missed its check at {}", incident["broken"]["due_at_ms"]);
            watchdog_words.as_str()
        }
        "stuck" => {
            watchdog_words = format!(
                "has stuck run {} (started {}, limit {} ms)",
                incident["broken"]["run_id"].as_str().unwrap(),
                incident["broken"]["started_at_ms"],
                incident["broken"]["timeout_ms"]
            );
            watchdog_words.as_str()
        }
        "disabled_by_failures" => "was switched off by failures",
        "paused" => "is paused",
        "stalled" => "is stalled",
        "not_found" => "is gone (not found)",
        "archived" => "is gone (archived)",
        "refused" => "is down (refused)",
        "timed_out" => "is down (timed out)",
        "wrong_answer" => "is down (wrong answer)",
        "not_running" => "is not running",
        _ => return Err("invalid record fault".into()),
    };
    let line = if let Some(slot) = slot {
        let saved = &incident["tries"][slot];
        record["at"] = saved["at"].clone();
        record["try"] = json!(if slot == "first" { 1 } else { 2 });
        record["outcome"] = public_outcome(&saved["outcome"]);
        let (fix, words) = match incident["check"].as_str().unwrap() {
            "loop" => ("resume_loop", "resume it"),
            "tick" => ("restart_tick", "restart it"),
            "server" => ("restart_server", "restart it"),
            "fleet_thread" => ("take_over_fleet_thread", "take it over"),
            _ => return Err("check has no fix".into()),
        };
        record["fix"] = json!(fix);
        let outcome = match saved["outcome"]["state"].as_str() {
            Some("done") if saved["outcome"]["owner"] == "service_tick" => format!(
                "done, service tick owns the fleet, retired loop {}",
                saved["outcome"]["retired_loop"].as_str().unwrap()
            ),
            Some("done") if fix == "take_over_fleet_thread" => "done".into(),
            Some("done") => "done".into(),
            Some("interrupted") => "interrupted".into(),
            Some("failed") => format!(
                "failed ({}): {}",
                saved["outcome"]["gap"].as_str().unwrap(),
                saved["outcome"]["reason"].as_str().unwrap()
            ),
            _ => return Err("record outcome is still unknown".into()),
        };
        format!(
            "openwiz-service: incident {}: {subject} {broken}; try {} of 2, {words}: {outcome}",
            incident["id"].as_str().unwrap(),
            record["try"]
        )
    } else {
        record["at"] = incident["needs_you"]["at"].clone();
        let tail = if incident["check"] == "cloudroom" || incident["check"] == "watchdog" {
            "OpenWiz has no fix for it."
        } else {
            let mut tries = incident["tries"].clone();
            for slot in ["first", "second"] {
                tries[slot].as_object_mut().unwrap().remove("comment");
                tries[slot]["outcome"] = public_outcome(&tries[slot]["outcome"]);
            }
            record["tries"] = tries;
            "OpenWiz tried twice and couldn't fix it."
        };
        format!(
            "**Needs you:** incident {}: {subject} {broken}; {tail}",
            incident["id"].as_str().unwrap()
        )
    };
    Ok(format!("{line}\n\n```json\n{record}\n```"))
}
// Operational takeover identities stay in saved state; the GitHub record is
// a projection, never a replacement for that private recovery history.
fn public_outcome(saved: &Value) -> Value {
    let mut outcome = saved.clone();
    if let Some(object) = outcome.as_object_mut() {
        object.remove("thread");
    }
    outcome
}
fn public_body(body: &str) -> Result<(), String> {
    fn safe(text: &str) -> bool {
        !text.match_indices("thr_").any(|(at, _)| {
            text.as_bytes()
                .get(at + 4)
                .is_some_and(u8::is_ascii_alphanumeric)
        })
    }
    fn safe_value(value: &Value) -> bool {
        match value {
            Value::String(s) => safe(s),
            Value::Array(a) => a.iter().all(safe_value),
            Value::Object(o) => o.iter().all(|(k, v)| safe(k) && safe_value(v)),
            _ => true,
        }
    }
    let record = body
        .split_once("\n\n```json\n")
        .and_then(|(_, s)| s.strip_suffix("\n```"))
        .and_then(|s| crate::document::read(crate::document::Document::Record, s).ok());
    if !safe(body) || record.as_ref().is_none_or(|v| !safe_value(v)) {
        return Err("health record is unsafe for public delivery; private draft retained".into());
    }
    Ok(())
}
pub(super) fn checked(path: &Path, directory: bool) -> Result<(), String> {
    let m = fs::symlink_metadata(path).map_err(|_| "health journal cannot be inspected")?;
    if m.file_type().is_symlink()
        || m.uid() != openwiz_store::attachments::effective_uid()?
        || m.mode() & 0o077 != 0
        || (directory && !m.is_dir())
        || (!directory && (!m.is_file() || m.nlink() != 1))
    {
        return Err("health journal is not private and owner managed".into());
    }
    Ok(())
}
pub fn lock(root: &Path) -> Result<File, String> {
    crate::paths::inspect(root)?;
    let dir = root.join("service/health");
    match DirBuilder::new().mode(0o700).create(&dir) {
        Ok(()) => File::open(root.join("service"))
            .and_then(|f| f.sync_all())
            .map_err(|_| "health journal directory was not synced")?,
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(_) => return Err("health journal cannot be created".into()),
    }
    checked(&dir, true)?;
    let path = dir.join("lock");
    match fs::symlink_metadata(&path) {
        Ok(_) => checked(&path, false)?,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err("health pass lock cannot be inspected".into()),
    }
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(&path)
        .map_err(|_| "health pass lock cannot be opened")?;
    checked(&path, false)?;
    file.try_lock()
        .map_err(|_| "another health pass owns the state")?;
    Ok(file)
}
pub fn post(
    root: &Path,
    executor: &Executor,
    issue: Number,
    body: &str,
    deadline: Instant,
) -> Result<Number, String> {
    public_body(body)?;
    let dir = root.join("service/health");
    checked(&dir, true)?;
    let digest = sha256_hex(format!("{issue}\n{body}").as_bytes());
    let gh = TickReads::with_executor(executor.clone());
    let comments = gh
        .comments(issue, deadline)
        .map_err(|_| "health comment records are unread")?;
    let matches = comments
        .iter()
        .filter(|c| c.body == body)
        .collect::<Vec<_>>();
    match matches.as_slice() {
        [c] => {
            confirm(&dir, &digest, c.id)?;
            return Ok(c.id);
        }
        [] => {}
        _ => return Err("health record is ambiguous".into()),
    }
    let path = dir.join(&digest);
    match OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)
    {
        Ok(mut file) => {
            file.write_all(json!({"issue":issue,"body":body}).to_string().as_bytes())
                .and_then(|_| file.sync_all())
                .and_then(|_| File::open(&dir)?.sync_all())
                .map_err(|_| "health record claim was not synced")?;
        }
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
            checked(&path, false)?;
            return Err("health record delivery remains uncertain; refusing to post again".into());
        }
        Err(_) => return Err("health record cannot be claimed".into()),
    }
    let write = Write::IssueComment {
        issue,
        body: Body::parse(body).ok_or("invalid health record body")?,
    };
    let Confirmed::Commented { url } = writes::perform_with(executor, &write, deadline)
        .map_err(|_| "health record delivery was not confirmed")?
    else {
        return Err("health record readback is missing".into());
    };
    let id = url
        .rsplit_once("#issuecomment-")
        .and_then(|(_, s)| s.parse().ok())
        .and_then(Number::new)
        .ok_or("health record id was not confirmed")?;
    confirm(&dir, &digest, id)?;
    Ok(id)
}

fn confirmed(dir: &Path, digest: &str) -> Result<bool, String> {
    let path = dir.join(format!("confirmed-{digest}"));
    if !path
        .try_exists()
        .map_err(|_| "health receipt cannot be inspected")?
    {
        return Ok(false);
    }
    checked(&path, false)?;
    let value = openwiz_adapter_github::tick::document(
        &fs::read(path).map_err(|_| "health receipt cannot be read")?,
    )
    .map_err(|_| "health receipt is incomplete")?;
    openwiz_adapter_github::tick::object(&value, &["comment"])
        .map_err(|_| "health receipt has invalid fields")?;
    value["comment"]
        .as_u64()
        .and_then(Number::new)
        .ok_or("health receipt has an invalid comment id")?;
    Ok(true)
}
fn confirm(dir: &Path, digest: &str, comment: Number) -> Result<(), String> {
    if confirmed(dir, digest)? {
        return Ok(());
    }
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let temporary = dir.join(format!(
        ".receipt-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&temporary)
        .map_err(|_| "health receipt cannot be created")?;
    let result = file
        .write_all(json!({"comment":comment}).to_string().as_bytes())
        .and_then(|()| file.sync_all())
        .and_then(|()| fs::rename(&temporary, dir.join(format!("confirmed-{digest}"))))
        .and_then(|()| File::open(dir)?.sync_all());
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result.map_err(|_| "health receipt was not synced".into())
}

/// Claims outlive incidents. Reconcile only by exact readback, never another
/// POST, so healing cannot abandon an uncertain delivery or block other fixes.
pub fn reconcile(root: &Path, executor: &Executor, deadline: Instant) -> Result<bool, String> {
    let dir = root.join("service/health");
    checked(&dir, true)?;
    let entries = fs::read_dir(&dir).map_err(|_| "health delivery journal cannot be read")?;
    let gh = TickReads::with_executor(executor.clone());
    let mut pending = false;
    for entry in entries {
        let entry = entry.map_err(|_| "health delivery journal entry cannot be read")?;
        let Some(digest) = entry.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        if digest.len() != 64
            || !digest
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            continue;
        }
        let result = (|| {
            checked(&entry.path(), false)?;
            if confirmed(&dir, &digest)? {
                return Ok(());
            }
            let value = openwiz_adapter_github::tick::document(
                &fs::read(entry.path()).map_err(|_| "health claim cannot be read")?,
            )
            .map_err(|_| "health claim is incomplete")?;
            openwiz_adapter_github::tick::object(&value, &["issue", "body"])
                .map_err(|_| "health claim has invalid fields")?;
            let issue = value["issue"]
                .as_u64()
                .and_then(Number::new)
                .ok_or("health claim issue is invalid")?;
            let body = value["body"]
                .as_str()
                .ok_or("health claim body is invalid")?;
            Body::parse(body).ok_or("health claim body is invalid")?;
            if digest != sha256_hex(format!("{issue}\n{body}").as_bytes()) {
                return Err("health claim binding differs".into());
            }
            let comments = gh
                .comments(issue, deadline)
                .map_err(|_| "health claim readback is unread")?;
            let matches = comments
                .iter()
                .filter(|c| c.body == body)
                .collect::<Vec<_>>();
            match matches.as_slice() {
                [c] => confirm(&dir, &digest, c.id),
                _ => Err("health claim delivery remains unconfirmed".into()),
            }
        })();
        if result.is_err() {
            pending = true;
        }
    }
    Ok(pending)
}

/// Observations may change during one incident. A record or notification's
/// original body is immutable, so uncertain delivery and a saved send ID can
/// never be rebound to later words. None quarantines an intact body from public
/// delivery; corrupt or unsafe journal storage remains an error.
pub fn frozen(root: &Path, key: &str, proposed: &str) -> Result<Option<String>, String> {
    let dir = root.join("service/health");
    checked(&dir, true)?;
    let path = dir.join(format!("body-{}", sha256_hex(key.as_bytes())));
    let body = json!({"body":proposed,"sha256":sha256_hex(proposed.as_bytes())});
    match OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)
    {
        Ok(mut file) => file
            .write_all(body.to_string().as_bytes())
            .and_then(|_| file.sync_all())
            .and_then(|_| File::open(&dir)?.sync_all())
            .map_err(|_| "health record body was not synced")?,
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(_) => return Err("health record body cannot be frozen".into()),
    }
    checked(&path, false)?;
    let bytes = fs::read(path).map_err(|_| "health record body cannot be read")?;
    let value = openwiz_adapter_github::tick::document(&bytes)
        .map_err(|_| "health record body is incomplete")?;
    openwiz_adapter_github::tick::object(&value, &["body", "sha256"])
        .map_err(|_| "health record body has invalid fields")?;
    let text = value["body"]
        .as_str()
        .ok_or("health record body is not text")?;
    if value["sha256"].as_str() != Some(sha256_hex(text.as_bytes()).as_str()) {
        return Err("health record body checksum differs".into());
    }
    Ok(public_body(text).is_ok().then(|| text.to_owned()))
}
