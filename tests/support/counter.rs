//! Reading the fake `room-cli`'s call counters while a fake may be writing
//! one (#176, a flake on #146).
//!
//! The fake counts each accepted call in a file of its directory
//! (`tell-calls.count`, `spawn-calls.count`, `threads-created.count`):
//! under an exclusive lock it reads the count, empties the file and writes
//! the new count. A test that read the file without the lock while a fake
//! was counting could find it empty, and failed to parse it. [`read`] reads
//! it under a shared lock, so it waits out a count being written and sees a
//! whole one.

use std::fs::File;
use std::io::{self, Read};
use std::path::Path;

/// The count in `path`: 0 if there is no file yet, or if the fake has made
/// it and not yet written its first count (the only way it is empty under
/// the lock). Anything else that isn't a count fails the test.
pub fn read(path: &Path) -> u64 {
    let mut file = match File::open(path) {
        Ok(file) => file,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return 0,
        Err(e) => panic!("open {}: {e}", path.display()),
    };
    file.lock_shared()
        .unwrap_or_else(|e| panic!("lock {}: {e}", path.display()));
    let mut text = String::new();
    file.read_to_string(&mut text)
        .unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    if text.is_empty() {
        return 0;
    }
    text.parse()
        .unwrap_or_else(|_| panic!("{} is not a count: {text:?}", path.display()))
}
