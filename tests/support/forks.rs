use std::fs;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::thread;
use std::time::{Duration, Instant};

pub const LIMIT: Duration = Duration::from_secs(10);

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

pub fn lock_on(id: &str) -> Option<String> {
    fs::read_to_string("/proc/locks")
        .expect("read /proc/locks")
        .lines()
        .find(|line| line.split_whitespace().any(|field| field == id))
        .map(str::to_owned)
}

pub fn file_id(path: &Path) -> String {
    let meta = fs::metadata(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let dev = meta.dev();
    let major = ((dev >> 8) & 0xfff) | ((dev >> 32) & !0xfff);
    let minor = (dev & 0xff) | ((dev >> 12) & !0xff);
    format!("{major:02x}:{minor:02x}:{}", meta.ino())
}
