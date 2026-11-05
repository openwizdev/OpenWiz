//! Checked descriptors, cross-process admission serialization and atomic sync.
use super::*;
use std::{
    fs::{self, DirBuilder, File, OpenOptions, TryLockError},
    io::{Read, Write},
    os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt},
    sync::atomic::{AtomicU64, Ordering},
};

pub struct Locked {
    pub state: State,
    dir: PathBuf,
    lock: File,
    read_only: bool,
}
impl Drop for Locked {
    fn drop(&mut self) {
        let _ = self.lock.unlock();
    }
}
fn unavailable<T>(_: T) -> Error {
    Error::Unavailable
}
fn flags() -> i32 {
    if cfg!(target_vendor = "apple") {
        0x0100 | 0x0004
    } else if cfg!(any(target_arch = "arm", target_arch = "aarch64")) {
        0o100000 | 0o4000
    } else {
        0o400000 | 0o4000
    }
}
fn check(meta: &fs::Metadata, directory: bool, uid: u32) -> Result<(), Error> {
    if meta.uid() != uid
        || meta.mode() & 0o077 != 0
        || if directory {
            !meta.is_dir()
        } else {
            !meta.is_file() || meta.nlink() != 1
        }
    {
        return Err(Error::Unavailable);
    }
    Ok(())
}
fn boundary(root: &Path) -> Result<(PathBuf, u32), Error> {
    crate::loops::inspect_state(root).map_err(unavailable)?;
    let uid = fs::symlink_metadata(root).map_err(unavailable)?.uid();
    let dir = root.join("service/notifications");
    let meta = fs::symlink_metadata(&dir).map_err(unavailable)?;
    check(&meta, true, uid)?;
    if dir.join(".git").try_exists().map_err(unavailable)? {
        return Err(Error::Unavailable);
    }
    Ok((dir, uid))
}
fn file(path: &Path, uid: u32, write: bool) -> Result<File, Error> {
    let meta = fs::symlink_metadata(path).map_err(unavailable)?;
    check(&meta, false, uid)?;
    let file = OpenOptions::new()
        .read(true)
        .write(write)
        .custom_flags(flags())
        .open(path)
        .map_err(unavailable)?;
    let opened = file.metadata().map_err(unavailable)?;
    check(&opened, false, uid)?;
    if opened.ino() != meta.ino() || opened.dev() != meta.dev() {
        return Err(Error::Unavailable);
    }
    Ok(file)
}
fn acquire(file: &File, read_only: bool) -> Result<(), Error> {
    let result = if read_only {
        file.try_lock_shared()
    } else {
        file.try_lock()
    };
    result.map_err(|e| match e {
        TryLockError::WouldBlock => Error::Busy,
        _ => Error::Unavailable,
    })
}
pub(super) fn initialize(root: &Path) -> Result<(), Error> {
    crate::loops::inspect_state(root).map_err(unavailable)?;
    let dir = root.join("service/notifications");
    match DirBuilder::new().mode(0o700).create(&dir) {
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
            open(root, true)?;
            return Ok(());
        }
        Err(_) => return Err(Error::Unavailable),
        Ok(()) => File::open(root.join("service"))
            .and_then(|f| f.sync_all())
            .map_err(unavailable)?,
    }
    let (_, uid) = boundary(root)?;
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(flags())
        .open(dir.join("admission.lock"))
        .map_err(unavailable)?;
    check(&lock.metadata().map_err(unavailable)?, false, uid)?;
    acquire(&lock, false)?;
    lock.sync_all().map_err(unavailable)?;
    File::open(&dir)
        .and_then(|f| f.sync_all())
        .map_err(unavailable)?;
    let mut guard = Locked {
        state: State::initial(),
        dir,
        lock,
        read_only: false,
    };
    guard.save()
}
pub(super) fn open(root: &Path, read_only: bool) -> Result<Locked, Error> {
    let (dir, uid) = boundary(root)?;
    let lock = file(&dir.join("admission.lock"), uid, !read_only)?;
    acquire(&lock, read_only)?;
    let mut data = String::new();
    file(&dir.join("state.json"), uid, false)?
        .read_to_string(&mut data)
        .map_err(unavailable)?;
    // Strict duplicate/integer/shape validation uses the map-only decoder below.
    let state = decode(&data)?;
    Ok(Locked {
        state,
        dir,
        lock,
        read_only,
    })
}
impl Locked {
    pub fn save(&mut self) -> Result<(), Error> {
        if self.read_only {
            return Err(Error::Unavailable);
        }
        self.state.check()?;
        let uid = self.lock.metadata().map_err(unavailable)?.uid();
        check(
            &fs::symlink_metadata(&self.dir).map_err(unavailable)?,
            true,
            uid,
        )?;
        let path = self.dir.join("state.json");
        match fs::symlink_metadata(&path) {
            Ok(meta) => check(&meta, false, uid)?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err(Error::Unavailable),
        }
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let temp = self.dir.join(format!(
            ".tmp-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let bytes = serde_json::to_vec(&self.state).map_err(unavailable)?;
        let result = (|| -> std::io::Result<()> {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .custom_flags(flags())
                .open(&temp)?;
            file.write_all(&bytes)?;
            file.sync_all()?;
            fs::rename(&temp, &path)?;
            File::open(&self.dir)?.sync_all()
        })();
        if result.is_err() {
            let _ = fs::remove_file(&temp);
            return Err(Error::Unavailable);
        }
        Ok(())
    }
}
pub(super) fn random_hex<const N: usize>() -> Result<String, Error> {
    let mut bytes = [0u8; N];
    File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut bytes))
        .map_err(unavailable)?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}
fn decode(text: &str) -> Result<State, Error> {
    let mut decoder = serde_json::Deserializer::from_str(text);
    let Strict(value) = Strict::deserialize(&mut decoder).map_err(unavailable)?;
    decoder.end().map_err(unavailable)?;
    let state: State = serde_json::from_value(value.clone()).map_err(unavailable)?;
    if serde_json::to_value(&state).map_err(unavailable)? != value {
        return Err(Error::Unavailable);
    }
    state.check()?;
    Ok(state)
}
struct Strict(serde_json::Value);
impl<'de> Deserialize<'de> for Strict {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        use serde::de::{self, MapAccess, SeqAccess, Visitor};
        use serde_json::{Map, Value};
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = Strict;
            fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str("strict notification state")
            }
            fn visit_bool<E: de::Error>(self, v: bool) -> Result<Strict, E> {
                Ok(Strict(Value::Bool(v)))
            }
            fn visit_u64<E: de::Error>(self, v: u64) -> Result<Strict, E> {
                Ok(Strict(Value::Number(v.into())))
            }
            fn visit_str<E: de::Error>(self, v: &str) -> Result<Strict, E> {
                Ok(Strict(Value::String(v.into())))
            }
            fn visit_unit<E: de::Error>(self) -> Result<Strict, E> {
                Ok(Strict(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut a: A) -> Result<Strict, A::Error> {
                let mut values = vec![];
                while let Some(Strict(v)) = a.next_element()? {
                    values.push(v);
                }
                Ok(Strict(Value::Array(values)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut a: A) -> Result<Strict, A::Error> {
                let mut values = Map::new();
                while let Some(key) = a.next_key::<String>()? {
                    if values.contains_key(&key) {
                        return Err(de::Error::custom("duplicate state key"));
                    }
                    let Strict(v) = a.next_value()?;
                    values.insert(key, v);
                }
                Ok(Strict(Value::Object(values)))
            }
        }
        d.deserialize_any(V)
    }
}
