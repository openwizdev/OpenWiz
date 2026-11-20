//! The command's state directory (#1264: folded from the old store crate):
//! one owner-only directory whose areas are opened through
//! the same checks. The start record lives in `starts/` ([`starts`]): one
//! record per builder or reviewer start, so a ticket never gets two builders
//! (OpenWiz 0.0.6, B4, ClosedWiz#120). [`StartFileStore`] is `Store<Starts>`.
//! The loop switches live in [`loops`].
//!
//! Layout, under the state directory (0700), for each kind (`starts/` for
//! the start record):
//!
//! - `starts/` (0700);
//! - `starts/<op id>.json` (0600): the record, replaced atomically (written
//!   to a temporary file, synced, renamed, and the directory synced);
//! - `starts/<op id>.lock` (0600): the claim. The process that owns an op id
//!   holds an exclusive lock on it until it finishes or stops. The lock is
//!   released by the operating system when the process ends, which is how
//!   a stopped owner is recognised and its record recovered.
//!
//! The state directory is outside the repository, in the owner's per-user
//! state directory (see [`default_state_dir`]). Provisional; Jake decides.
//!
//! Standard library only: `OpenOptions::create_new`, `File::try_lock`,
//! `sync_all` and Unix permissions.

pub mod loops;

use std::collections::HashMap;
use std::ffi::{OsStr, OsString};
use std::fs::{self, DirBuilder, File, OpenOptions};
use std::io::{self, Read, Write};
use std::marker::PhantomData;
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt};
use std::path::{Component, Path, PathBuf};
use std::sync::Mutex;

use openwiz_core::messaging::OpId;
use openwiz_core::messaging::record::StoreError;
use openwiz_core::model::Timestamp;

pub mod owner;
pub mod starts;

pub use starts::{StartFileStore, Starts};

/// Overrides the state directory, for tests and for owners who want it
/// elsewhere.
pub const STATE_DIR_ENV: &str = "OPENWIZ_STATE_DIR";

/// The default state directory: `$OPENWIZ_STATE_DIR`; else on macOS
/// `~/Library/Application Support/openwiz`; else `$XDG_STATE_HOME/openwiz`
/// (when it is absolute) or `~/.local/state/openwiz`. `var` looks up an
/// environment variable. Without an absolute home, nothing is guessed.
pub fn default_state_dir(var: &dyn Fn(&str) -> Option<OsString>) -> Result<PathBuf, StoreError> {
    let absolute = |name: &str| {
        var(name)
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
            .filter(|p| p.is_absolute())
    };
    if let Some(dir) = var(STATE_DIR_ENV).filter(|v| !v.is_empty()) {
        let dir = PathBuf::from(dir);
        if !dir.is_absolute() {
            return Err(StoreError(format!(
                "{STATE_DIR_ENV} must be an absolute path"
            )));
        }
        return Ok(dir);
    }
    let home = absolute("HOME").ok_or_else(|| {
        StoreError(format!(
            "no state directory: HOME is not an absolute path, and {STATE_DIR_ENV} is not set"
        ))
    })?;
    if cfg!(target_os = "macos") {
        return Ok(home.join("Library/Application Support/openwiz"));
    }
    Ok(absolute("XDG_STATE_HOME")
        .unwrap_or_else(|| home.join(".local/state"))
        .join("openwiz"))
}

/// Syncs one directory: a real `fsync`, or a test's recorder.
type SyncDir<'a> = dyn Fn(&Path) -> io::Result<()> + 'a;

/// One directory of the state directory: its name, and what it is called
/// in messages. Opening it runs the store's directory checks, the same for
/// every area.
pub trait Area: Send + Sync + 'static {
    /// Its directory under the state directory.
    const DIR: &'static str;
    /// What it holds, in messages.
    const WHAT: &'static str;
}

/// One kind of record the store keeps, in its own [`Area`], and how its
/// records are read, written and recovered. The claim, the lock, the
/// atomic write and the directory checks are the store's own, the same for
/// every kind.
pub trait Kind: Area {
    type Record: Clone + PartialEq;
    fn op_id(record: &Self::Record) -> &OpId;
    fn is_finished(record: &Self::Record) -> bool;
    /// Whether the record is still in the claimed state: nothing was read
    /// or sent for it yet.
    fn is_claimed(record: &Self::Record) -> bool;
    /// The core's recovery rule: never a redispatch.
    fn recover(record: &Self::Record, now: Timestamp) -> Self::Record;
    /// Reads a record file's text; why not, in OpenWiz's words.
    fn read(text: &str) -> Result<Self::Record, String>;
    /// The record's JSON.
    fn body(record: &Self::Record) -> Result<Vec<u8>, String>;
}

/// An acquired claim. A concurrent fork can inherit the file until exec;
/// explicitly unlock before closing ours so that copy cannot retain it.
struct ClaimLock(File);

impl Drop for ClaimLock {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

/// The file-backed record of one [`Kind`], or one other [`Area`].
pub struct Store<K: Area> {
    dir: PathBuf,
    /// The claims this process holds: the locked `.lock` file of each.
    held: Mutex<HashMap<OpId, ClaimLock>>,
    /// Refuses every write: opened by [`Store::open_read_only`].
    read_only: bool,
    kind: PhantomData<K>,
}

impl<K: Area> std::fmt::Debug for Store<K> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Store")
            .field("dir", &self.dir)
            .field("read_only", &self.read_only)
            .finish_non_exhaustive()
    }
}

/// Creates `dir` and any missing parents (0700), one at a time, syncing each
/// new directory's parent so the new entry itself is durable.
fn create_dir_synced(dir: &Path, sync: &dyn Fn(&Path) -> io::Result<()>) -> Result<(), StoreError> {
    let create_dir = |d: &Path| DirBuilder::new().mode(0o700).create(d);
    let mut missing = Vec::new();
    let mut next = Some(dir);
    while let Some(d) = next.filter(|d| !d.as_os_str().is_empty() && !d.exists()) {
        missing.push(d);
        next = d.parent();
    }
    for d in missing.into_iter().rev() {
        match create_dir(d) {
            Ok(()) => {}
            // Another process made it first; its parent is synced anyway.
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {}
            Err(e) => return Err(io_error("make", d, &e)),
        }
        let parent = d
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        sync(parent).map_err(|e| io_error("sync", parent, &e))?;
    }
    Ok(())
}

/// Syncs a directory, so the entries in it are durable.
fn fsync_dir(dir: &Path) -> io::Result<()> {
    File::open(dir)?.sync_all()
}

/// The repository `dir` would be inside, if any: the nearest existing
/// ancestor, resolved (symlinks too), or any of its ancestors, holds `.git`.
fn inside_repository(dir: &Path) -> Option<PathBuf> {
    let mut existing = dir;
    while !existing.exists() {
        existing = existing.parent()?;
    }
    let resolved = existing.canonicalize().ok()?;
    resolved
        .ancestors()
        .find(|a| a.join(".git").exists())
        .map(Path::to_path_buf)
}

fn io_error(what: &str, path: &Path, e: &io::Error) -> StoreError {
    StoreError(format!("could not {what} {}: {e}", path.display()))
}

impl<K: Area> Store<K> {
    /// Opens (and creates, 0700) the store under `state_dir`. Refuses a
    /// directory that group or others can read, write or enter, and one
    /// inside a repository.
    pub fn open(state_dir: &Path) -> Result<Self, StoreError> {
        Self::open_with_sync(state_dir, &fsync_dir)
    }

    /// [`open`](Self::open), with every directory sync made through `sync`.
    /// Tests pass a recorder; `open` passes a real `fsync`.
    ///
    /// - `state_dir` must be absolute, with no `.` or `..` component;
    /// - it must not be inside a repository, before anything is created, and
    ///   neither may the resolved state directory or the kind's directory
    ///   (`starts/`) afterwards;
    /// - the kind's directory must be a real directory, not a symlink;
    /// - every directory from the resolved kind's directory up to the root is
    ///   synced on every open, so a chain another process created and has
    ///   not synced yet is durable before this process dispatches.
    pub fn open_with_sync(
        state_dir: &Path,
        sync: &dyn Fn(&Path) -> io::Result<()>,
    ) -> Result<Self, StoreError> {
        let dir = Self::checked_sends(state_dir, Some(sync))?
            .ok_or_else(|| StoreError(format!("{} was not made", state_dir.display())))?;
        Ok(Self::new(dir, false))
    }

    /// Opens an existing store for reading only, for a lookup or a status
    /// read: nothing is created, synced or written, and every write is
    /// refused. `None` when the state directory or the kind's directory does
    /// not exist yet: nothing was ever claimed there. The same checks as
    /// [`open`](Self::open) otherwise.
    pub fn open_read_only(state_dir: &Path) -> Result<Option<Self>, StoreError> {
        Ok(Self::checked_sends(state_dir, None)?.map(|dir| Self::new(dir, true)))
    }

    fn new(dir: PathBuf, read_only: bool) -> Self {
        Self {
            dir,
            held: Mutex::new(HashMap::new()),
            read_only,
            kind: PhantomData,
        }
    }

    /// The checks of [`open_with_sync`](Self::open_with_sync), and the
    /// kind's directory. With `sync`, missing directories are made and the
    /// chain is synced. Without it nothing is made or synced, and a missing
    /// directory gives `None`. Named for the send record, the store's first
    /// kind (#79); it checks every area's directory the same way.
    fn checked_sends(
        state_dir: &Path,
        sync: Option<&SyncDir<'_>>,
    ) -> Result<Option<PathBuf>, StoreError> {
        let what = K::WHAT;
        let plain = state_dir.is_absolute()
            && state_dir
                .components()
                .all(|c| matches!(c, Component::RootDir | Component::Normal(_)));
        if !plain {
            return Err(StoreError(format!(
                "{} must be an absolute path with no . or .. component",
                state_dir.display()
            )));
        }
        let in_repository = |dir: &Path| {
            inside_repository(dir).map(|repo| {
                StoreError(format!(
                    "{} is inside the repository at {}; the {what} must be outside every \
                     repository",
                    dir.display(),
                    repo.display()
                ))
            })
        };
        if let Some(refused) = in_repository(state_dir) {
            return Err(refused);
        }
        let records = state_dir.join(K::DIR);
        for dir in [state_dir, &records] {
            if let Some(sync) = sync {
                create_dir_synced(dir, sync)?;
            }
            let meta = match fs::metadata(dir) {
                Ok(meta) => meta,
                Err(e) if sync.is_none() && e.kind() == io::ErrorKind::NotFound => {
                    return Ok(None);
                }
                Err(e) => return Err(io_error("read", dir, &e)),
            };
            if !meta.is_dir() {
                return Err(StoreError(format!("{} is not a directory", dir.display())));
            }
            let mode = meta.permissions().mode() & 0o777;
            if mode & 0o077 != 0 {
                return Err(StoreError(format!(
                    "{} is open to other users (mode {mode:o}); the {what} must be \
                     readable by its owner only (0700)",
                    dir.display()
                )));
            }
        }
        let records_meta =
            fs::symlink_metadata(&records).map_err(|e| io_error("read", &records, &e))?;
        if records_meta.file_type().is_symlink() {
            return Err(StoreError(format!(
                "{} is a symlink; the {what}'s directory must be a real directory",
                records.display()
            )));
        }
        let resolved = records
            .canonicalize()
            .map_err(|e| io_error("resolve", &records, &e))?;
        for dir in resolved.ancestors() {
            if let Some(refused) = in_repository(dir) {
                return Err(refused);
            }
        }
        if let Some(sync) = sync {
            for dir in resolved.ancestors() {
                sync(dir).map_err(|e| io_error("sync", dir, &e))?;
            }
        }
        Ok(Some(records))
    }

    /// The kind's directory (`starts/`), or the area's.
    pub fn dir(&self) -> &Path {
        &self.dir
    }

    fn refuse_if_read_only(&self) -> Result<(), StoreError> {
        if self.read_only {
            return Err(StoreError(format!(
                "the {} was opened for reading only",
                K::WHAT
            )));
        }
        Ok(())
    }
}

impl<K: Kind> Store<K> {
    /// The record file of `op_id`.
    pub fn record_path(&self, op_id: &OpId) -> PathBuf {
        self.dir.join(format!("{op_id}.json"))
    }

    fn lock_path(&self, op_id: &OpId) -> PathBuf {
        self.dir.join(format!("{op_id}.lock"))
    }

    /// Opens (creating it, 0600) the lock file of `op_id`, unlocked. Refused
    /// for a read-only store.
    fn lock_file(&self, op_id: &OpId) -> Result<File, StoreError> {
        self.refuse_if_read_only()?;
        let path = self.lock_path(op_id);
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .open(&path)
            .map_err(|e| io_error("open", &path, &e))
    }

    /// The record of `op_id` as it is on disk.
    pub fn record(&self, op_id: &OpId) -> Result<Option<K::Record>, StoreError> {
        self.read_record(&self.record_path(op_id))
    }

    fn read_record(&self, path: &Path) -> Result<Option<K::Record>, StoreError> {
        // O_NONBLOCK on the targets guarded by the compile_error below:
        // a FIFO substituted before open must not wait for a writer.
        let nonblock = if cfg!(target_vendor = "apple") {
            0x0004
        } else {
            0o4000
        };
        let mut file = match OpenOptions::new()
            .read(true)
            .custom_flags(nonblock)
            .open(path)
        {
            Ok(file) => file,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(io_error("read", path, &e)),
        };
        let metadata = file.metadata().map_err(|e| io_error("read", path, &e))?;
        if !metadata.is_file() {
            return Err(StoreError(format!(
                "{} is not a regular {} file",
                path.display(),
                K::WHAT
            )));
        }
        // Inspect and read the same descriptor: a later path swap cannot
        // replace the file whose type was checked above.
        let mut text = String::new();
        file.read_to_string(&mut text)
            .map_err(|e| io_error("read", path, &e))?;
        let record = K::read(&text).map_err(|why| {
            let why = if why.is_empty() {
                String::new()
            } else {
                format!(" ({why})")
            };
            StoreError(format!("{} is not a {}{why}", path.display(), K::WHAT))
        })?;
        // A record is only ever read from its own op id's file.
        if path.file_name() != Some(OsStr::new(&format!("{}.json", K::op_id(&record)))) {
            return Err(StoreError(format!(
                "{} holds the record of another op id",
                path.display()
            )));
        }
        Ok(Some(record))
    }

    /// Writes `record` in place of the old one: to a new temporary file
    /// (0600), synced, renamed over the record, and the directory synced.
    /// Refused for a read-only store.
    fn write_record(&self, record: &K::Record) -> Result<(), StoreError> {
        self.refuse_if_read_only()?;
        let op_id = K::op_id(record);
        let path = self.record_path(op_id);
        let temp = self.dir.join(format!(".{op_id}.json.tmp"));
        let mut body = K::body(record)
            .map_err(|_| StoreError(format!("a {} could not be serialized", K::WHAT)))?;
        body.push(b'\n');
        let _ = fs::remove_file(&temp);
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&temp)
            .map_err(|e| io_error("make", &temp, &e))?;
        file.write_all(&body)
            .and_then(|()| file.sync_all())
            .map_err(|e| io_error("write", &temp, &e))?;
        drop(file);
        fs::rename(&temp, &path).map_err(|e| io_error("replace", &path, &e))?;
        File::open(&self.dir)
            .and_then(|dir| dir.sync_all())
            .map_err(|e| io_error("sync", &self.dir, &e))
    }

    fn held_by_me(&self, op_id: &OpId) -> bool {
        self.held
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .contains_key(op_id)
    }

    /// Writes the owner's new version of a claimed record, synced.
    fn update_record(&self, record: &K::Record) -> Result<(), StoreError> {
        self.refuse_if_read_only()?;
        if !self.held_by_me(K::op_id(record)) {
            return Err(StoreError(format!(
                "op {} is not claimed by this process",
                K::op_id(record)
            )));
        }
        self.write_record(record)
    }

    /// Gives up this process's claim on `op_id`.
    fn release_claim(&self, op_id: &OpId) {
        self.held
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .remove(op_id);
    }
}

// The O_NONBLOCK values above are recorded only for Darwin and Linux's
// generic ones; any other target fails to build rather than guess. Moved
// here from the deleted attachment store (#1264), which held this guard.
#[cfg(not(any(
    target_vendor = "apple",
    all(
        target_os = "linux",
        any(
            target_arch = "x86",
            target_arch = "x86_64",
            target_arch = "arm",
            target_arch = "aarch64",
            target_arch = "riscv64"
        )
    )
)))]
compile_error!("O_NONBLOCK's value isn't recorded for this target (crates/cli/src/state/mod.rs)");
