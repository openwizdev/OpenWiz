//! The state directory's owner, for the loop switches' private-state checks.
//! Moved unchanged from the deleted attachment store (#1264), which the
//! folded `loops/paths.rs` and `loops/storage.rs` still call.

use std::fs::{self, File, OpenOptions};
use std::io::{self, Read};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::Path;

/// Derive the owner from a file this process exclusively creates in private
/// state (Jake, #1102 comment 6672035698). No subprocess or identity environment.
pub fn owner_uid_from_private_state(root: &Path) -> Result<u32, String> {
    use std::path::Component;
    if !root.is_absolute()
        || !root
            .components()
            .all(|part| matches!(part, Component::RootDir | Component::Normal(_)))
    {
        return Err("owner probe requires an absolute private state directory".to_owned());
    }
    for ancestor in root.ancestors() {
        let meta =
            fs::symlink_metadata(ancestor).map_err(|_| "cannot inspect owner probe ancestors")?;
        if !meta.is_dir() || meta.file_type().is_symlink() {
            return Err("owner probe refuses symlinked state ancestors".to_owned());
        }
        match fs::symlink_metadata(ancestor.join(".git")) {
            Ok(_) => return Err("owner probe must be outside repositories".to_owned()),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(_) => return Err("cannot inspect owner probe repository boundary".to_owned()),
        }
    }
    let directory =
        fs::symlink_metadata(root).map_err(|_| "cannot inspect owner probe directory")?;
    if directory.mode() & 0o077 != 0 {
        return Err("owner probe directory must be private".to_owned());
    }
    let id = new_id().map_err(|_| "cannot allocate private owner probe")?;
    let path = root.join(format!(".owner-{id}.tmp"));
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)
        .map_err(|_| "cannot create private owner probe")?;
    let result = (|| {
        let meta = file
            .metadata()
            .map_err(|_| "cannot inspect created owner probe")?;
        let current =
            fs::symlink_metadata(root).map_err(|_| "cannot recheck owner probe directory")?;
        if !meta.is_file()
            || meta.nlink() != 1
            || meta.mode() & 0o077 != 0
            || current.dev() != directory.dev()
            || current.ino() != directory.ino()
            || current.uid() != meta.uid()
            || current.mode() & 0o077 != 0
        {
            return Err("owner probe requires process-owned private state".to_owned());
        }
        Ok(meta.uid())
    })();
    // Remove exactly the exclusively created empty file on success or failure.
    let cleanup =
        fs::remove_file(&path).map_err(|_| "cannot remove private owner probe".to_owned());
    let uid = result.and_then(|uid| cleanup.map(|()| uid))?;
    #[cfg(target_os = "macos")]
    {
        if PROCESS_OWNER.get().is_some_and(|previous| *previous != uid) {
            return Err("process owner identity changed".to_owned());
        }
        let _ = PROCESS_OWNER.set(uid);
    }
    Ok(uid)
}

#[cfg(target_os = "macos")]
static PROCESS_OWNER: std::sync::OnceLock<u32> = std::sync::OnceLock::new();

/// Retain the existing Linux kernel owner query without starting a program.
#[cfg(target_os = "linux")]
pub fn effective_uid() -> Result<u32, String> {
    fs::metadata("/proc/self")
        .map(|meta| meta.uid())
        .map_err(|_| "cannot determine state owner".to_owned())
}

#[cfg(target_os = "macos")]
pub fn effective_uid() -> Result<u32, String> {
    if let Some(uid) = PROCESS_OWNER.get() {
        return Ok(*uid);
    }
    let root = super::default_state_dir(&|name| std::env::var_os(name))
        .map_err(|_| "cannot locate private owner state")?;
    owner_uid_from_private_state(&root)
}

#[cfg(not(any(target_os = "linux", target_os = "macos")))]
pub fn effective_uid() -> Result<u32, String> {
    Err("state ownership is unsupported on this platform".to_owned())
}

/// The probe's name: `att-` and 32 random hex digits, as before the move.
fn new_id() -> io::Result<String> {
    let mut bytes = [0u8; 16];
    File::open("/dev/urandom").and_then(|mut f| f.read_exact(&mut bytes))?;
    let hex: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
    Ok(format!("att-{hex}"))
}
