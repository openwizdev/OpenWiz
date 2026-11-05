//! #502: a released start claim must not stay held by another thread's
//! forked child. Fixtures only; no CloudRoom calls.

use std::fs;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Barrier};
use std::thread;

use openwiz_core::fleet::starts::{Locked, StartStore};
use openwiz_core::model::Timestamp;
use openwiz_core::new_thread::record::{Claim, NewThreadRecord, NewThreadStore};
use openwiz_core::new_thread::{Binding, ProjectRef};
use openwiz_core::prompt::empty_attachments_digest;

use crate::b4_starts::fake::{Fake, builder};

#[test]
fn released_claims_are_free_while_other_threads_spawn_children() {
    let fake = Fake::new("lock-release-fork-load", vec![]);
    let owner = fake.starts();
    let contender = fake.starts();
    under_fork_load(20_000, |round| {
        let key = builder(round as u64).key;
        assert_eq!(owner.lock(&key).unwrap(), Locked::Mine(None));
        assert_eq!(contender.lock(&key).unwrap(), Locked::Busy);
        owner.unlock(&key);
        match contender.lock(&key).unwrap() {
            Locked::Mine(None) => {
                contender.unlock(&key);
                true
            }
            Locked::Busy => false,
            other => panic!("unexpected handoff: {other:?}"),
        }
    });
    fs::remove_dir_all(&fake.state).expect("remove temporary state");
    assert!(!fake.state.try_exists().expect("check temporary state"));
}

#[test]
fn failed_claims_are_free_while_other_threads_spawn_children() {
    let fake = Fake::new("failed-lock-fork-load", vec![]);
    let owner = fake.starts();
    let contender = fake.starts();
    under_fork_load(20_000, |round| {
        let key = builder(round as u64).key;
        let path = owner.record_path(&key.id());
        fs::write(&path, "{broken").unwrap();
        assert!(owner.lock(&key).is_err());
        fs::remove_file(path).unwrap();
        match contender.lock(&key).unwrap() {
            Locked::Mine(None) => {
                contender.unlock(&key);
                true
            }
            Locked::Busy => false,
            other => panic!("unexpected handoff: {other:?}"),
        }
    });
    fs::remove_dir_all(&fake.state).expect("remove temporary state");
    assert!(!fake.state.try_exists().expect("check temporary state"));
}

#[test]
fn inspected_claims_are_free_while_other_threads_spawn_children() {
    let fake = Fake::new("inspect-lock-fork-load", vec![]);
    let inspector = fake.threads();
    let contender = fake.threads();
    let settings = builder(518).settings;
    let binding = Binding {
        project: ProjectRef::Id("prj_syn_0001".to_owned()),
        harness: settings.harness.clone(),
        model: settings.model.clone(),
        effort: settings.effort.clone(),
        text_sha256: openwiz_core::messaging::sha256_hex(b"Synthetic"),
        attachments_digest: empty_attachments_digest(),
    };
    under_fork_load(2_000, |round| {
        let record = NewThreadRecord::claimed(
            crate::b4_starts::fake::op(&format!("op-inspect-{round}")),
            binding.clone(),
            settings.clone(),
            "Synthetic",
            Timestamp(0),
        );
        let bytes = serde_json::to_vec(&record).unwrap();
        let path = inspector.record_path(&record.op_id);
        fs::write(&path, &bytes).unwrap();
        fs::write(path.with_extension("lock"), "").unwrap();
        let shown = inspector
            .inspect(&record.op_id, Timestamp(1))
            .unwrap()
            .unwrap();
        assert!(shown.recovered);
        assert_eq!(fs::read(path).unwrap(), bytes, "inspect never writes");
        match contender.claim(&record, Timestamp(1)).unwrap() {
            Claim::Existing(recovered) => {
                assert!(recovered.recovered);
                let lock =
                    fs::File::open(contender.record_path(&record.op_id).with_extension("lock"))
                        .unwrap();
                // Also checks the recovery return from claim_record.
                if lock.try_lock().is_err() {
                    return false;
                }
                lock.unlock().unwrap();
                assert!(matches!(
                    inspector.claim(&record, Timestamp(2)).unwrap(),
                    Claim::Existing(_)
                ));
                // And its already-finished return.
                let free = lock.try_lock().is_ok();
                if free {
                    lock.unlock().unwrap();
                }
                free
            }
            Claim::InProgress(_) => false,
            other => panic!("unexpected handoff: {other:?}"),
        }
    });
    fs::remove_dir_all(&fake.state).expect("remove temporary state");
    assert!(!fake.state.try_exists().expect("check temporary state"));
}

/// Runs `handoff` once per round, up to `rounds`, while two threads fork and
/// reap load children. The rounds stop once the load stops: after it, no
/// forked child can hold an inherited descriptor, so a later round could
/// never catch the leak (#1259: the inspect case spent 23 of its 24 s on
/// such rounds; a planted leak failed every round inside the load).
fn under_fork_load(rounds: usize, mut handoff: impl FnMut(usize) -> bool) {
    const SPAWNERS: usize = 2;
    const CHILDREN: usize = 128;
    // Each child searches missing directories before exec, keeping all
    // inherited descriptors alive longer. Change only that child's PATH,
    // as in #176's forker; no unsafe pre_exec hook or new dependency.
    let mut path = vec!["/nonexistent-openwiz-lock-release"; 3_000];
    path.push("/usr/bin:/bin");
    let path = path.join(":");
    let barrier = Arc::new(Barrier::new(SPAWNERS + 1));
    let loading = AtomicUsize::new(SPAWNERS);
    let mut busy_after_release = 0;
    let mut under_load = 0;
    thread::scope(|scope| {
        let spawners: Vec<_> = (0..SPAWNERS)
            .map(|_| {
                let barrier = barrier.clone();
                let path = &path;
                let loading = &loading;
                scope.spawn(move || {
                    barrier.wait();
                    for _ in 0..CHILDREN {
                        assert!(
                            Command::new("true")
                                .env("PATH", path)
                                .stdin(Stdio::null())
                                .status()
                                .expect("spawn and reap a load child")
                                .success(),
                            "load child failed"
                        );
                    }
                    loading.fetch_sub(1, Ordering::SeqCst);
                    CHILDREN
                })
            })
            .collect();
        barrier.wait();
        for round in 1..=rounds {
            if loading.load(Ordering::SeqCst) == 0 {
                break;
            }
            under_load += 1;
            // Use a new key each round so a failing handoff cannot make
            // the next round wait for that same inherited descriptor.
            if !handoff(round) {
                busy_after_release += 1;
            }
        }
        for spawner in spawners {
            assert_eq!(spawner.join().expect("load thread"), CHILDREN);
        }
    });
    assert!(under_load > 0, "no handoff ran under the fork load");
    assert_eq!(
        busy_after_release, 0,
        "a released claim stayed Busy during {under_load} handoffs under fork load"
    );
}
