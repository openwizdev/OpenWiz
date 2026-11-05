//! Synthetic state only: inspection must tolerate the service's atomic save.
#![cfg(target_os = "linux")]

use std::fs::{self, DirBuilder, OpenOptions};
use std::io::Write;
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Barrier};

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "openwiz-atomic-state-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        DirBuilder::new().mode(0o700).create(&path).unwrap();
        DirBuilder::new()
            .mode(0o700)
            .create(path.join("service"))
            .unwrap();
        for name in ["config.json", "state.json"] {
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(path.join("service").join(name))
                .unwrap()
                .write_all(b"{}")
                .unwrap();
        }
        Self(path)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
fn inspect_never_refuses_private_state_during_atomic_replacement() {
    let fixture = Fixture::new();
    let stop = Arc::new(AtomicBool::new(false));
    let start = Arc::new(Barrier::new(2));
    let root = fixture.0.clone();
    let writer_stop = stop.clone();
    let writer_start = start.clone();
    let writer = std::thread::spawn(move || {
        let temporary = root.join("service/state.tmp");
        let state = root.join("service/state.json");
        writer_start.wait();
        let mut replacements = 0_u64;
        while !writer_stop.load(Ordering::Relaxed) {
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&temporary)
                .unwrap()
                .write_all(b"{}")
                .unwrap();
            fs::rename(&temporary, &state).unwrap();
            replacements += 1;
        }
        replacements
    });
    start.wait();
    let mut failures = std::collections::BTreeMap::<String, usize>::new();
    for _ in 0..100_000 {
        if let Err(error) = openwiz_store::loops::inspect_state(&fixture.0) {
            *failures.entry(error).or_default() += 1;
        }
    }
    stop.store(true, Ordering::Relaxed);
    let replacements = writer.join().unwrap();
    eprintln!("100000 inspections, {replacements} atomic replacements; refusals: {failures:?}");
    assert!(
        replacements > 0,
        "the writer must exercise atomic replacement"
    );
    assert!(
        failures.is_empty(),
        "safe atomic saves must never refuse: {failures:?}"
    );
}
