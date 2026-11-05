//! Waiting out a forked child's copy of a lock (#176, the flakes on #146).
//!
//! A test binary runs its tests on several threads, and most of them start
//! programs. Each start forks this process, and the child keeps a copy of
//! every file this process had open at that moment until it runs its
//! program (each one is close-on-exec). A lock (`flock`) belongs to the open
//! file, and the child's copy is the same open file. So a lock a test has
//! just let go of can still be held for a moment by a child that another
//! test's thread forked while the test held it.
//!
//! [`wait_until_unlocked`] waits for the explicit state the test needs:
//! `/proc/locks` (Linux) lists no lock on the file. A lock stays listed
//! while any copy of its open file is left, even one a fork is still
//! making. It never takes the lock itself to look: a lock taken to look is
//! one more open file a fork could copy.

use std::fs;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::thread;
use std::time::{Duration, Instant};

/// How long a lock may stay held before the wait fails.
const LIMIT: Duration = Duration::from_secs(10);

/// Waits until no process holds a lock on `path`'s file. Call it once this
/// process has let go of the lock: from then on no new copy of it can be
/// made, and each copy left goes when its child runs its program. Fails
/// after [`LIMIT`], with the lock's line.
pub fn wait_until_unlocked(path: &Path) {
    let id = file_id(path);
    let started = Instant::now();
    while let Some(line) = lock_on(&id) {
        assert!(
            started.elapsed() < LIMIT,
            "{} is still locked after {LIMIT:?}: {line}",
            path.display()
        );
        thread::sleep(Duration::from_millis(1));
    }
}

/// The line of `/proc/locks` for a lock on the file `id` names, if any.
pub fn lock_on(id: &str) -> Option<String> {
    fs::read_to_string("/proc/locks")
        .expect("read /proc/locks")
        .lines()
        .find(|line| line.split_whitespace().any(|field| field == id))
        .map(str::to_owned)
}

/// How `/proc/locks` names `path`'s file: `MAJOR:MINOR:INODE`, the device
/// numbers in hex, split as Linux splits a device number.
pub fn file_id(path: &Path) -> String {
    let meta = fs::metadata(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let dev = meta.dev();
    let major = ((dev >> 8) & 0xfff) | ((dev >> 32) & !0xfff);
    let minor = (dev & 0xff) | ((dev >> 12) & !0xff);
    format!("{major:02x}:{minor:02x}:{}", meta.ino())
}

/// The wait's own proof: a lock is listed while it is held, a child's copy
/// of the open file keeps it listed after this process lets go, and it is
/// gone once that child is.
#[test]
fn a_lock_stays_listed_while_a_childs_copy_holds_it() {
    use std::process::{Command, Stdio};
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR"))
        .join("forks")
        .join(std::process::id().to_string());
    let _ = fs::remove_dir_all(&dir);
    crate::dirs::private_dir_all(&dir).expect("dir");
    let path = dir.join("held.lock");
    fs::write(&path, "").expect("file");
    let id = file_id(&path);
    assert_eq!(lock_on(&id), None, "never locked yet");
    let file = fs::File::open(&path).expect("open");
    file.try_lock().expect("lock");
    wait_until_listed(&id);
    // A child with a copy of the locked open file, as a fork makes one.
    let mut child = Command::new("sleep")
        .arg("600")
        .stdin(Stdio::from(file.try_clone().expect("a copy")))
        .spawn()
        .expect("start sleep");
    drop(file);
    let line = wait_until_listed(&id);
    assert!(line.contains("FLOCK"), "{line}");
    child.kill().expect("stop sleep");
    child.wait().expect("reap sleep");
    wait_until_unlocked(&path);
    assert_eq!(lock_on(&id), None, "nobody can lock it again");
    let _ = fs::remove_dir_all(&dir);
}

/// Other tests take and drop locks while /proc/locks is being read. A
/// single scan missed this proof's held lock on CI (#1391); re-read before
/// asserting presence. The kernel cause of that omission is unverified.
/// Only use this while a known open descriptor keeps the lock held.
fn wait_until_listed(id: &str) -> String {
    let started = Instant::now();
    loop {
        if let Some(line) = lock_on(id) {
            return line;
        }
        assert!(
            started.elapsed() < LIMIT,
            "held lock {id} was not listed in /proc/locks after {LIMIT:?}"
        );
        thread::sleep(Duration::from_millis(1));
    }
}
