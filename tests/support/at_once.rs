//! Runs independent cases at once (#1259): each case on one of at most
//! `workers` threads, every case exactly once. A case that panics fails
//! the test with its own message, after the other cases have finished.
//! Only for cases that share nothing: each has its own fakes, directories
//! and servers.

use std::sync::Mutex;
use std::thread;

/// Runs `case` for every item of `items`, on at most `workers` threads.
pub fn at_once<T: Sync>(items: &[T], workers: usize, case: impl Fn(&T) + Sync) {
    let next = Mutex::new(items.iter());
    let ran = Mutex::new(0usize);
    thread::scope(|scope| {
        for _ in 0..workers.clamp(1, items.len().max(1)) {
            scope.spawn(|| {
                loop {
                    let Some(item) = next.lock().unwrap_or_else(|p| p.into_inner()).next() else {
                        break;
                    };
                    case(item);
                    *ran.lock().unwrap_or_else(|p| p.into_inner()) += 1;
                }
            });
        }
    });
    assert_eq!(
        ran.into_inner().unwrap_or_else(|p| p.into_inner()),
        items.len(),
        "every case ran once"
    );
}
