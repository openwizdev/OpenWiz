use std::fs::File;
use std::io::{self, Read};
use std::path::Path;

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
