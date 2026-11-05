//! Trusted exact-definition approvals from setup-owned service configuration.
//! This supplies only the existing Approval seam. L12 owns runtime registration.
use openwiz_core::messaging::{OpId, sha256_hex};
use openwiz_store::loops::{document, inspect_state, repository::Repository};
use serde_json::Value;
use std::{
    collections::BTreeSet,
    fs,
    io::Read,
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::PathBuf,
};

const REFUSED: &str = "trusted loop approval is unavailable or invalid";
const FIELDS: &[&str] = &[
    "repository",
    "project",
    "loop_id",
    "definition_revision",
    "sha256",
    "approved_by",
    "scope",
    "approval_ref",
];

/// Strict LP1 approvals fragment. Its presence/shape alone confers no trust;
/// only InstalledApproval reads it from the protected setup-owned config.
pub struct Approvals(Vec<Value>);
impl Approvals {
    pub fn read(text: &str) -> Result<Self, String> {
        let value = document::parse(text).map_err(|_| REFUSED)?;
        Self::from_value(&value).ok_or_else(|| REFUSED.into())
    }
    fn from_value(value: &Value) -> Option<Self> {
        let rows = value.as_array()?;
        let mut bindings = BTreeSet::new();
        for row in rows {
            let object = row.as_object()?;
            if object.len() != FIELDS.len() || !FIELDS.iter().all(|key| object.contains_key(*key)) {
                return None;
            }
            let repository = repository_name(&row["repository"])?;
            if !cloud_id(row["project"].as_str()?)
                || OpId::parse(row["loop_id"].as_str()?).is_err()
                || !blob_revision(row["definition_revision"].as_str()?)
                || !hex(row["sha256"].as_str()?, 64)
                || !nonblank(row["approved_by"].as_str()?)
                || !nonblank(row["scope"].as_str()?)
                || !approval_url(row["approval_ref"].as_str()?)
                || !bindings.insert((
                    repository.to_ascii_lowercase(),
                    row["project"].as_str()?,
                    row["loop_id"].as_str()?,
                    row["definition_revision"].as_str()?,
                ))
            {
                return None;
            }
        }
        Some(Self(rows.clone()))
    }
}

fn nonblank(s: &str) -> bool {
    !s.trim().is_empty() && !s.contains('\0')
}
fn cloud_id(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 128
        && s.bytes()
            .next()
            .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'_')
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}
fn hex(s: &str, len: usize) -> bool {
    s.len() == len
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn blob_revision(s: &str) -> bool {
    hex(s, 40) || hex(s, 64)
}
fn owner(s: &str) -> bool {
    s.bytes().next().is_some_and(|b| b.is_ascii_alphanumeric())
        && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
}
fn repo(s: &str) -> bool {
    !s.is_empty()
        && s != "."
        && s != ".."
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
}
fn repository_name(value: &Value) -> Option<String> {
    let object = value.as_object()?;
    let (o, n) = (
        object.get("owner")?.as_str()?,
        object.get("name")?.as_str()?,
    );
    (object.len() == 2 && owner(o) && repo(n)).then(|| format!("{o}/{n}"))
}
fn positive(s: &str) -> bool {
    s.starts_with(|c: char| matches!(c, '1'..='9')) && s.bytes().all(|b| b.is_ascii_digit())
}
fn approval_url(s: &str) -> bool {
    let Some(path) = s.strip_prefix("https://github.com/") else {
        return false;
    };
    let parts: Vec<_> = path.split('/').collect();
    let [o, n, kind, subject] = parts.as_slice() else {
        return false;
    };
    let Some((issue, comment)) = subject.split_once("#issuecomment-") else {
        return false;
    };
    owner(o)
        && repo(n)
        && matches!(*kind, "issues" | "pull")
        && positive(issue)
        && positive(comment)
}

/// Pinned installation identities come from trusted local composition, never
/// from a loop definition. Each verify rereads the setup-owned config so removal
/// or replacement cannot leave an in-memory approval active.
pub struct InstalledApproval {
    checkout: PathBuf,
    state: PathBuf,
    repository: String,
    project: String,
}
impl InstalledApproval {
    pub fn new(checkout: PathBuf, state: PathBuf, repository: String, project: String) -> Self {
        Self {
            checkout,
            state,
            repository,
            project,
        }
    }
    fn config(&self) -> Result<Value, String> {
        inspect_state(&self.state).map_err(|_| REFUSED)?;
        let path = self.state.join("service/config.json");
        let before = fs::symlink_metadata(&path).map_err(|_| REFUSED)?;
        // Use the store's assessed no-follow/nonblocking flags: a raced
        // symlink or FIFO must not become a trusted config read or block it.
        // Same supported targets/values as store::attachments::open_metadata.
        let nonblock = if cfg!(target_vendor = "apple") {
            0x0004
        } else {
            0o4000
        };
        let nofollow = if cfg!(target_vendor = "apple") {
            0x0100
        } else if cfg!(any(target_arch = "arm", target_arch = "aarch64")) {
            0o100000
        } else {
            0o400000
        };
        let mut file = fs::OpenOptions::new()
            .read(true)
            .custom_flags(nonblock | nofollow)
            .open(&path)
            .map_err(|_| REFUSED)?;
        let metadata = file.metadata().map_err(|_| REFUSED)?;
        #[cfg(target_vendor = "apple")]
        let uid = openwiz_store::attachments::owner_uid_from_private_state(&self.state)
            .map_err(|_| REFUSED)?;
        #[cfg(not(target_vendor = "apple"))]
        let uid = openwiz_store::attachments::effective_uid().map_err(|_| REFUSED)?;
        let safe = |m: &fs::Metadata| {
            m.is_file()
                && !m.file_type().is_symlink()
                && m.uid() == uid
                && m.mode() & 0o077 == 0
                && m.nlink() == 1
                && m.dev() == before.dev()
                && m.ino() == before.ino()
        };
        if !safe(&metadata) {
            return Err(REFUSED.into());
        }
        let mut text = String::new();
        file.read_to_string(&mut text).map_err(|_| REFUSED)?;
        let after = fs::symlink_metadata(&path).map_err(|_| REFUSED)?;
        if !safe(&after)
            || metadata.len() != after.len()
            || metadata.mtime() != after.mtime()
            || metadata.mtime_nsec() != after.mtime_nsec()
            || metadata.ctime() != after.ctime()
            || metadata.ctime_nsec() != after.ctime_nsec()
        {
            return Err(REFUSED.into());
        }
        inspect_state(&self.state).map_err(|_| REFUSED)?;
        // Full duplicate detection precedes extraction. Enclosing config
        // validation/registration remains L12; no existing config reader changes.
        document::parse(&text).map_err(|_| REFUSED.into())
    }
    fn verified(&self, definition: &Value, revision: &str) -> Option<()> {
        if !blob_revision(revision) || !cloud_id(&self.project) {
            return None;
        }
        let config = self.config().ok()?;
        if config["schema"] != "openwiz.service-config.v1"
            || repository_name(&config["repository"])? != self.repository
            || config["project"] != self.project
        {
            return None;
        }
        let approvals = Approvals::from_value(&config["loops"]["approvals"])?;
        // A record for a different installation is conflicting input, even if
        // another row would match. No personal-project or repo fallback.
        if approvals
            .0
            .iter()
            .any(|row| row["repository"] != config["repository"] || row["project"] != self.project)
        {
            return None;
        }
        let record = approvals.0.iter().find(|row| {
            row["loop_id"] == definition["id"] && row["definition_revision"] == revision
        })?;
        if definition["action"]["project"] != serde_json::json!({"kind":"id","value":self.project})
            || ["approved_by", "scope", "approval_ref"]
                .iter()
                .any(|key| definition["authority"][key] != record[key])
        {
            return None;
        }
        let repository = Repository(self.checkout.clone());
        if !repository.matches_repository(&self.repository).ok()? {
            return None;
        }
        // blob() validates the actual definition/action, while blob_bytes()
        // retains its exact serialization for the independently approved hash.
        let blob = repository.blob(revision).ok()?;
        if &blob.value != definition
            || record["sha256"] != sha256_hex(&repository.blob_bytes(revision).ok()?)
        {
            return None;
        }
        Some(())
    }
}
impl super::Approval for InstalledApproval {
    fn verify(&self, definition: &Value, revision: &str) -> bool {
        self.verified(definition, revision).is_some()
    }
}
