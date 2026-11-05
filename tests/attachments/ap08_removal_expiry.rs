//! AP8 Removal and expiry. `rm` deletes the bytes and the metadata. A ready
//! attachment no operation has claimed expires 24 hours after it became
//! ready (sheet B-2): it is deleted and reported as expired, once. Removal
//! is refused while its operation is dispatching or uncertain, and expiry
//! keeps it then (sheet B-6), against a claim source the test sets: the
//! real claims are B2's. Unfinished copies go when the store opens.

use std::cell::Cell;
use std::ffi::OsString;
use std::fs::{self, File, TryLockError};
use std::os::unix::fs::PermissionsExt;

use openwiz_core::attachment::{AttachmentId, Claim};
use openwiz_core::messaging::record::StoreError;
use openwiz_core::model::Timestamp;
use openwiz_store::attachments::{
    CLAIM, CLAIMS_LOCK, Claims, META, NoClaims, PARTIAL_SUFFIX, RecordedClaims, Removal,
    STAGING_LOCK, Staged,
};

use crate::bench::{Bench, CONTENT, ClaimsOf, Free, PLENTY, T0};
use crate::support::{PNG, padded};

// Sheet B-2's approved 24 hours, independent of the implementation's constant.
const TTL_MS: i64 = 86_400_000;

fn add(bench: &Bench, name: &str) -> String {
    let source = bench.source(name, &padded(PNG, 2_000));
    let run = bench.cli(&["add", "--json", source.to_str().unwrap()]);
    assert_eq!(run.code, 0, "{run:?}");
    run.json()["ready"][0]["staged"]["attachment"]["id"]
        .as_str()
        .unwrap()
        .to_owned()
}

fn at(ms: i64) -> Timestamp {
    Timestamp(T0.0 + ms)
}

#[test]
fn list_text_reports_actual_elapsed_age() {
    let bench = Bench::new("ap08_text_age");
    let id = add(&bench, "syn-ap08-age.png");
    let run = bench.cli_at(&["ls"], at(7_200_000));
    assert_eq!(run.code, 0, "{run:?}");
    let line = run.out.lines().find(|line| line.starts_with(&id)).unwrap();
    assert!(line.contains(" · age 2h · "), "{line}");
}

fn damage(bench: &Bench, id: &str, name: &str) {
    let copy = bench.attachments().join(id).join(name);
    fs::set_permissions(&copy, fs::Permissions::from_mode(0o600)).unwrap();
    fs::write(copy, b"synthetic residual bytes").unwrap();
}

#[test]
fn ls_lists_ready_attachments_oldest_first() {
    // ID order and directory order can oppose each other (for example on
    // tmpfs). Each gets its own adversarial fixture, never a combined gate.
    for order in ["id", "directory"] {
        let bench = Bench::new(&format!("ap08_oldest_first_{order}"));
        let first = bench.source("syn-old.txt", b"synthetic oldest");
        let second = bench.source("syn-new.txt", b"synthetic newest");
        let stage = |source: &std::path::Path, ms| {
            let run = bench.cli_at(&["add", "--json", source.to_str().unwrap()], at(ms));
            assert_eq!(run.code, 0, "{run:?}");
            run.json()["ready"][0]["staged"]["attachment"]["id"]
                .as_str()
                .unwrap()
                .to_owned()
        };
        let mut expected = None;
        for attempt in 0..128 {
            // The ID fixture always creates the newer attachment first.
            // The directory fixture tries both creation orders because
            // iteration can follow or reverse creation order.
            let (old_id, new_id) = if order == "directory" && attempt % 2 == 1 {
                let old_id = stage(&first, 0);
                let new_id = stage(&second, 1_000);
                (old_id, new_id)
            } else {
                let new_id = stage(&second, 1_000);
                let old_id = stage(&first, 0);
                (old_id, new_id)
            };
            // Regenerate both IDs on retry rather than fixing an unlucky
            // random threshold. Never select by the CLI's list output.
            let arranged = if order == "id" {
                new_id < old_id
            } else {
                let directory_ids: Vec<String> = fs::read_dir(bench.attachments())
                    .unwrap()
                    .map(|entry| entry.unwrap().file_name().into_string().unwrap())
                    .filter(|name| name == &new_id || name == &old_id)
                    .collect();
                directory_ids == [new_id.clone(), old_id.clone()]
            };
            if arranged {
                expected = Some([old_id, new_id]);
                break;
            }
            let removed = bench.cli_at(&["rm", "--json", &new_id, &old_id], at(2_000));
            assert_eq!(removed.code, 0, "{removed:?}");
            assert!(bench.ids().is_empty(), "retry must remove both attachments");
        }
        let expected =
            expected.unwrap_or_else(|| panic!("could not arrange newest-first {order} order"));

        let run = bench.cli_at(&["ls", "--json"], at(2_000));
        assert_eq!(run.code, 0, "{run:?}");
        let report = run.json();
        let ids: Vec<&str> = report["attachments"]
            .as_array()
            .unwrap()
            .iter()
            .map(|a| a["attachment"]["id"].as_str().unwrap())
            .collect();
        assert_eq!(ids, expected, "{order} fixture must list oldest first");
    }
}

#[test]
fn a_damaged_unclaimed_copy_expires_at_its_time_to_live() {
    let bench = Bench::new("ap08_damaged_expiry");
    let name = "syn-ap08-damaged.png";
    let id = add(&bench, name);
    let dir = bench.attachments().join(&id);
    damage(&bench, &id, name);

    let before = bench.cli_at(&["ls", "--json"], at(TTL_MS - 1));
    assert_eq!(before.code, 0, "{before:?}");
    assert_eq!(before.json()["broken"].as_array().unwrap().len(), 1);
    assert!(before.json()["expired"].as_array().unwrap().is_empty());
    assert!(dir.exists(), "damage does not expire the copy early");

    let expired = bench.cli_at(&["ls", "--json"], at(TTL_MS));
    assert_eq!(expired.code, 0, "{expired:?}");
    assert!(!dir.exists(), "expired unclaimed copy still exists");
    let report = expired.json();
    assert_eq!(report["expired"].as_array().unwrap().len(), 1);
    assert_eq!(report["expired"][0]["attachment"]["id"], id);
    assert_eq!(report["expired"][0]["readiness"]["state"], "expired");
    assert!(report["attachments"].as_array().unwrap().is_empty());
    assert!(report["broken"].as_array().unwrap().is_empty());

    let again = bench.cli_at(&["ls", "--json"], at(TTL_MS + 1));
    assert_eq!(again.code, 0, "{again:?}");
    assert!(again.json()["expired"].as_array().unwrap().is_empty());
}

#[test]
fn damaged_copies_are_kept_while_their_operations_may_use_them() {
    for (label, claim) in [
        ("dispatching", Claim::Dispatching),
        ("uncertain", Claim::Uncertain),
    ] {
        let bench = Bench::new(&format!("ap08_damaged_{label}"));
        let name = "syn-ap08-damaged-claimed.png";
        let id = add(&bench, name);
        damage(&bench, &id, name);
        let claims = ClaimsOf::default();
        claims.set(&id, claim);

        let store = bench.store();
        let swept = store.sweep(at(TTL_MS + 1), &claims).unwrap();
        assert!(swept.expired.is_empty());
        assert_eq!(swept.released, 0);
        let removal = store
            .remove(&AttachmentId::parse(&id).unwrap(), &claims)
            .unwrap();
        assert_eq!(removal, Removal::Refused(claim));
        assert_eq!(
            fs::read(bench.attachments().join(&id).join(name)).unwrap(),
            b"synthetic residual bytes"
        );
    }
}

// #762: a damaged copy's claim still decides its retention. An accepted
// claim releases it at once, before its time-to-live; a failed claim keeps
// it before the time-to-live and expires it at the time-to-live. Each step
// checks the bytes are really gone, so a mutation that keeps damaged
// accepted copies (or never expires damaged failed ones) fails.
#[test]
fn damaged_accepted_copies_are_released_and_failed_copies_expire() {
    // Accepted: released before its time-to-live, exactly once.
    {
        let bench = Bench::new("ap08_damaged_accepted");
        let name = "syn-ap08-damaged-accepted.png";
        let id = add(&bench, name);
        damage(&bench, &id, name);
        let claims = ClaimsOf::default();
        claims.set(&id, Claim::Accepted);

        let store = bench.store();
        let swept = store.sweep(at(1), &claims).unwrap();
        assert!(swept.expired.is_empty(), "an accepted copy is not expired");
        assert_eq!(swept.released, 1, "an accepted copy is released at once");
        assert!(
            !bench.attachments().join(&id).exists(),
            "an accepted damaged copy's bytes are gone"
        );

        let again = store.sweep(at(TTL_MS), &claims).unwrap();
        assert!(again.expired.is_empty());
        assert_eq!(again.released, 0, "it is released only once");
    }

    // Failed: kept before its time-to-live, expired at it.
    {
        let bench = Bench::new("ap08_damaged_failed");
        let name = "syn-ap08-damaged-failed.png";
        let id = add(&bench, name);
        damage(&bench, &id, name);
        let claims = ClaimsOf::default();
        claims.set(&id, Claim::Failed);

        let store = bench.store();
        let before = store.sweep(at(TTL_MS - 1), &claims).unwrap();
        assert!(before.expired.is_empty(), "kept before its time-to-live");
        assert_eq!(before.released, 0);
        assert!(
            bench.attachments().join(&id).join(name).exists(),
            "a failed damaged copy is kept before its time-to-live"
        );

        let late = store.sweep(at(TTL_MS), &claims).unwrap();
        assert_eq!(late.expired.len(), 1, "a failed copy expires at its TTL");
        assert_eq!(late.expired[0].attachment.id.as_str(), id);
        assert_eq!(late.released, 0);
        assert!(
            !bench.attachments().join(&id).exists(),
            "an expired failed damaged copy's bytes are gone"
        );
    }
}

#[test]
fn damaged_copies_with_unreadable_metadata_are_kept() {
    for case in ["malformed", "different_id", "unreadable"] {
        let bench = Bench::new(&format!("ap08_damaged_meta_{case}"));
        let name = "syn-ap08-damaged-meta.png";
        let id = add(&bench, name);
        let meta = bench.attachments().join(&id).join(META);
        let mut record: serde_json::Value =
            serde_json::from_slice(&fs::read(&meta).unwrap()).unwrap();
        damage(&bench, &id, name);
        match case {
            "malformed" => fs::write(&meta, b"not synthetic metadata").unwrap(),
            "different_id" => {
                let other = AttachmentId::parse("att-synthetic-other").unwrap();
                assert_ne!(other.as_str(), id);
                record[0]["id"] = other.as_str().into();
                fs::write(&meta, serde_json::to_vec(&record).unwrap()).unwrap();
            }
            "unreadable" => {
                fs::set_permissions(&meta, fs::Permissions::from_mode(0o0)).unwrap();
                assert!(fs::read(&meta).is_err(), "run as a non-root user");
            }
            _ => unreachable!(),
        }

        let swept = bench.store().sweep(at(TTL_MS + 1), &NoClaims).unwrap();
        assert!(swept.expired.is_empty(), "{case}");
        assert_eq!(swept.released, 0, "{case}");
        assert_eq!(
            fs::read(bench.attachments().join(&id).join(name)).unwrap(),
            b"synthetic residual bytes"
        );
        fs::set_permissions(meta, fs::Permissions::from_mode(0o600)).unwrap();
    }
}

#[test]
fn damaged_copies_with_unknown_claims_are_kept_under_the_claims_lock() {
    struct LockedClaims {
        recorded: RecordedClaims,
        lock: File,
        reads: Cell<usize>,
        /// Fail on this many-th read (1-based); 0 never fails.
        fail_on: Cell<usize>,
    }

    impl Claims for LockedClaims {
        fn claim(&self, id: &AttachmentId) -> Result<Claim, StoreError> {
            assert!(matches!(
                self.lock.try_lock(),
                Err(TryLockError::WouldBlock)
            ));
            let read = self.reads.get() + 1;
            self.reads.set(read);
            if self.fail_on.get() == read {
                return Err(StoreError("synthetic claim lookup failure".to_owned()));
            }
            self.recorded.claim(id)
        }
    }

    for case in ["malformed", "unreadable"] {
        let bench = Bench::new(&format!("ap08_damaged_claim_{case}"));
        let name = "syn-ap08-damaged-claim.png";
        let id = add(&bench, name);
        damage(&bench, &id, name);
        let claim = bench.attachments().join(&id).join(CLAIM);
        fs::write(&claim, b"not a synthetic claim").unwrap();
        let mode = if case == "unreadable" { 0o0 } else { 0o600 };
        fs::set_permissions(&claim, fs::Permissions::from_mode(mode)).unwrap();
        let id = AttachmentId::parse(&id).unwrap();
        let claims = LockedClaims {
            recorded: RecordedClaims::new(&bench.state, at(TTL_MS)),
            lock: File::open(bench.attachments().join(CLAIMS_LOCK)).unwrap(),
            reads: Cell::new(0),
            fail_on: Cell::new(0),
        };
        assert!(claims.recorded.of(&id).is_err());
        assert!(bench.store().sweep(at(TTL_MS), &claims).is_err());
        assert_eq!(claims.reads.get(), 1);
        assert_eq!(
            fs::read(bench.attachments().join(id.as_str()).join(name)).unwrap(),
            b"synthetic residual bytes"
        );
        fs::set_permissions(claim, fs::Permissions::from_mode(0o600)).unwrap();
    }
}

// #762: the sweep reads every claim before deleting any copy (see the
// "Read every claim before deleting any ready copy" step in `sweep`). Two
// damaged copies are both past their time-to-live, so either one would be
// deleted by a sweep that deleted each copy before reading the next. The
// claim source fails on the second read; after the error both copies are
// still present, whichever one `entries()` visits first. This makes the
// proof independent of the directory order the random ids give.
#[test]
fn a_claim_read_failure_after_an_expired_copy_keeps_it() {
    struct SecondReadFails {
        lock: File,
        reads: Cell<usize>,
    }

    impl Claims for SecondReadFails {
        fn claim(&self, _id: &AttachmentId) -> Result<Claim, StoreError> {
            assert!(matches!(
                self.lock.try_lock(),
                Err(TryLockError::WouldBlock)
            ));
            let read = self.reads.get() + 1;
            self.reads.set(read);
            if read == 2 {
                return Err(StoreError("synthetic second-read failure".to_owned()));
            }
            Ok(Claim::Unclaimed)
        }
    }

    let bench = Bench::new("ap08_damaged_two_copies");
    let older_name = "syn-ap08-damaged-older.png";
    let newer_name = "syn-ap08-damaged-newer.png";
    let older = add(&bench, older_name);
    let newer = bench.source(newer_name, &padded(PNG, 2_000));
    let run = bench.cli_at(&["add", "--json", newer.to_str().unwrap()], at(1_000));
    assert_eq!(run.code, 0, "{run:?}");
    let newer = run.json()["ready"][0]["staged"]["attachment"]["id"]
        .as_str()
        .unwrap()
        .to_owned();
    assert_ne!(older, newer);
    damage(&bench, &older, older_name);
    damage(&bench, &newer, newer_name);

    let claims = SecondReadFails {
        lock: File::open(bench.attachments().join(CLAIMS_LOCK)).unwrap(),
        reads: Cell::new(0),
    };
    // Both copies are expired: the newer one at ready_at + 1_000 ms.
    assert!(
        bench.store().sweep(at(TTL_MS + 1_000), &claims).is_err(),
        "the claim read failure reaches the caller"
    );
    assert_eq!(claims.reads.get(), 2, "both claims were read");
    // Either expired copy would have been deleted had the sweep deleted each
    // copy before reading the next. Nothing is deleted before every claim is
    // read, so both remain whichever `entries()` visits first.
    assert_eq!(
        fs::read(bench.attachments().join(&older).join(older_name)).unwrap(),
        b"synthetic residual bytes"
    );
    assert_eq!(
        fs::read(bench.attachments().join(&newer).join(newer_name)).unwrap(),
        b"synthetic residual bytes"
    );
}

#[test]
fn rm_deletes_the_bytes_and_the_metadata() {
    let bench = Bench::new("ap08_rm");
    let id = add(&bench, "syn-ap08-rm.png");
    let other = add(&bench, "syn-ap08-kept.png");
    let dir = bench.attachments().join(&id);
    assert!(dir.join("syn-ap08-rm.png").exists());

    let run = bench.cli(&["rm", &id]);
    assert_eq!(run.code, 0, "{run:?}");
    assert!(run.out.contains(&format!("{id}: removed")), "{}", run.out);
    assert!(!dir.exists(), "the bytes and the metadata are gone");
    assert_eq!(bench.ids(), std::slice::from_ref(&other));

    let ls = bench.cli(&["ls", "--json"]).json();
    let listed: Vec<&str> = ls["attachments"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a["attachment"]["id"].as_str().unwrap())
        .collect();
    assert_eq!(listed, [other.as_str()]);

    // Again: not found, exit 3, the other untouched.
    let run = bench.cli(&["rm", &id, &other]);
    assert_eq!(run.code, 3, "{run:?}");
    assert!(run.out.contains(&format!("{id}: not found")), "{}", run.out);
    assert!(
        run.out.contains(&format!("{other}: removed")),
        "{}",
        run.out
    );
    assert!(bench.ids().is_empty());
}

#[test]
fn an_unclaimed_attachment_expires_at_its_time_to_live() {
    let bench = Bench::new("ap08_expiry");
    let id = add(&bench, "syn-ap08-expiry.png");

    let ls = bench.cli_at(&["ls", "--json"], at(TTL_MS - 1)).json();
    assert_eq!(ls["attachments"][0]["attachment"]["id"], id.as_str());
    assert_eq!(ls["attachments"][0]["expires_at"], T0.0 + TTL_MS);
    assert_eq!(ls["attachments"][0]["age_ms"], TTL_MS - 1);
    assert!(ls["expired"].as_array().unwrap().is_empty());

    let run = bench.cli_at(&["ls"], at(TTL_MS));
    assert_eq!(run.code, 0, "{run:?}");
    assert!(run.out.contains(&format!("expired {id}")), "{}", run.out);
    assert!(bench.ids().is_empty(), "its bytes are deleted");

    // Reported once: it is gone.
    let ls = bench.cli_at(&["ls", "--json"], at(TTL_MS + 1)).json();
    assert!(ls["attachments"].as_array().unwrap().is_empty());
    assert!(ls["expired"].as_array().unwrap().is_empty());
}

#[test]
fn an_attachment_that_expires_as_rm_runs_is_reported_expired() {
    let bench = Bench::new("ap08_rm_expired");
    let id = add(&bench, "syn-ap08-rm-expired.png");
    let run = bench.cli_at(&["rm", "--json", &id], at(TTL_MS));
    assert_eq!(run.code, 0, "{run:?}");
    let json = run.json();
    assert_eq!(json["ids"][0]["result"], "expired");
    assert_eq!(json["expired"][0]["attachment"]["id"], id.as_str());
    assert!(bench.ids().is_empty());
}

#[test]
fn every_open_expires_and_add_reports_it() {
    let bench = Bench::new("ap08_add_expires");
    let old = add(&bench, "syn-ap08-old.png");
    let source = bench.source("syn-ap08-new.png", &padded(PNG, 2_000));
    let run = bench.cli_at(&["add", "--json", source.to_str().unwrap()], at(TTL_MS));
    assert_eq!(run.code, 0, "{run:?}");
    let json = run.json();
    assert_eq!(json["expired"][0]["attachment"]["id"], old.as_str());
    assert_eq!(json["expired"][0]["readiness"]["state"], "expired");
    let new = json["ready"][0]["staged"]["attachment"]["id"]
        .as_str()
        .unwrap();
    assert_eq!(bench.ids(), [new.to_owned()]);
}

#[test]
fn a_claimed_attachment_is_kept_while_its_operation_may_use_it() {
    let bench = Bench::new("ap08_claimed");
    let claims = ClaimsOf::default();
    let names = [
        "dispatching",
        "uncertain",
        "accepted",
        "failed",
        "unclaimed",
    ];
    let ids: Vec<String> = names
        .iter()
        .map(|n| add(&bench, &format!("syn-ap08-{n}.png")))
        .collect();
    for (id, claim) in ids.iter().zip([
        Claim::Dispatching,
        Claim::Uncertain,
        Claim::Accepted,
        Claim::Failed,
        Claim::Unclaimed,
    ]) {
        claims.set(id, claim);
    }
    let sorted = |mut v: Vec<String>| {
        v.sort();
        v
    };
    let run = |args: &[&str], now: Timestamp| {
        let args: Vec<OsString> = args.iter().map(OsString::from).collect();
        bench.cli_with(&args, now, &Free::new(PLENTY), &claims)
    };

    // Removal is refused while dispatching or uncertain: nothing deleted.
    let store = bench.store();
    for id in &ids[..2] {
        let id = AttachmentId::parse(id).unwrap();
        let removal = store.remove(&id, &claims).unwrap();
        assert!(matches!(removal, Removal::Refused(_)), "{removal:?}");
    }
    assert_eq!(bench.ids().len(), 5, "nothing was deleted");

    // Through the CLI: exit 14. Its open also lets the accepted one go
    // (B-6: its operation's outcome is recorded).
    let refused = run(&["rm", &ids[0], &ids[1]], T0);
    assert_eq!(refused.code, 14, "{refused:?}");
    assert!(
        refused.out.contains(&format!("{}: refused", ids[0])),
        "{}",
        refused.out
    );
    assert_eq!(
        bench.ids(),
        sorted(vec![
            ids[0].clone(),
            ids[1].clone(),
            ids[3].clone(),
            ids[4].clone()
        ])
    );

    // Past the time-to-live: the failed and unclaimed ones expire, the
    // dispatching and uncertain ones are kept.
    let ls = run(&["ls", "--json"], at(TTL_MS));
    assert_eq!(ls.code, 0, "{ls:?}");
    let expired: Vec<String> = ls.json()["expired"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| e["attachment"]["id"].as_str().unwrap().to_owned())
        .collect();
    assert_eq!(
        sorted(expired),
        sorted(vec![ids[3].clone(), ids[4].clone()])
    );
    assert_eq!(bench.ids(), sorted(vec![ids[0].clone(), ids[1].clone()]));

    // Once its operation is no longer in flight, it can go.
    claims.set(&ids[0], Claim::Accepted);
    claims.set(&ids[1], Claim::Unclaimed);
    let removed = run(&["rm", "--json", &ids[1]], at(TTL_MS - 1));
    assert_eq!(removed.code, 0, "{removed:?}");
    assert_eq!(removed.json()["ids"][0]["result"], "removed");
    assert!(bench.ids().is_empty());
}

#[test]
fn unfinished_copies_go_when_the_store_opens() {
    let bench = Bench::new("ap08_unfinished");
    let id = add(&bench, "syn-ap08-ready.png");
    // A staging that stopped: a directory with a partial and no metadata.
    let stopped = bench.attachments().join("att-synthetic-stopped");
    crate::dirs::private_dir(&stopped).unwrap();
    fs::write(
        stopped.join(format!("syn-ap08-stopped.txt{PARTIAL_SUFFIX}")),
        CONTENT,
    )
    .unwrap();
    // `add` held the staging lock (shared), and a child another test forked
    // meanwhile keeps a copy of it until it runs its program, which keeps
    // the sweep from seeing that no staging is in progress (#176): wait
    // until the lock is free.
    crate::forks::wait_until_unlocked(&bench.attachments().join(STAGING_LOCK));
    let run = bench.cli(&["ls"]);
    assert_eq!(run.code, 0, "{run:?}");
    assert!(!stopped.exists(), "the unfinished copy is deleted");
    assert_eq!(bench.ids(), [id]);
    // Never listed as anything.
    assert!(!run.out.contains("att-synthetic-stopped"), "{}", run.out);

    // A sweep finds nothing more.
    let swept = bench.store().sweep(T0, &NoClaims).unwrap();
    assert_eq!(swept.unfinished, 0);
    assert!(matches!(
        bench.store().stage(
            &bench.source("syn-ap08-after.txt", CONTENT.as_bytes()),
            T0,
            &Free::new(PLENTY)
        ),
        Ok(Staged::Ready(_))
    ));
}

#[test]
fn present_unreadable_metadata_is_broken_and_removable() {
    let (sent, received) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        for case in ["dangling", "valid_link", "fifo"] {
            let bench = Bench::new(&format!("ap08_meta_{case}"));
            let id = add(&bench, "syn-ap08-meta.png");
            let dir = bench.attachments().join(&id);
            let meta = dir.join(".meta.json");
            let original = fs::read(&meta).unwrap();
            let target = bench.source("syn-external-meta.json", &original);
            fs::remove_file(&meta).unwrap();
            match case {
                "dangling" => {
                    std::os::unix::fs::symlink(target.with_extension("missing"), &meta).unwrap()
                }
                "valid_link" => std::os::unix::fs::symlink(&target, &meta).unwrap(),
                _ => assert!(
                    std::process::Command::new("mkfifo")
                        .arg(&meta)
                        .status()
                        .unwrap()
                        .success()
                ),
            }
            let run = bench.cli_at(&["ls", "--json"], at(TTL_MS));
            assert_eq!(run.code, 0, "{run:?}");
            let listed = run.json();
            assert_eq!(listed["attachments"], serde_json::json!([]));
            assert_eq!(listed["expired"], serde_json::json!([]));
            assert_eq!(listed["broken"].as_array().unwrap().len(), 1, "{listed}");
            assert_eq!(listed["broken"][0]["id"], id);
            assert_eq!(
                listed["broken"][0]["readiness"],
                serde_json::json!({"state":"failed","reason":"unreadable"})
            );
            assert!(dir.join("syn-ap08-meta.png").exists());
            let removed = bench.cli(&["rm", "--json", &id]);
            assert_eq!(removed.code, 0, "{removed:?}");
            assert_eq!(removed.json()["ids"].as_array().unwrap().len(), 1);
            assert_eq!(removed.json()["ids"][0]["result"], "removed");
            assert!(!dir.exists());
            assert_eq!(fs::read(&target).unwrap(), original);
        }
        let _ = sent.send(());
    });
    received
        .recv_timeout(std::time::Duration::from_secs(20))
        .expect("metadata classification/removal failed or waited for a FIFO writer");
}

#[test]
fn dangling_metadata_removal_preserves_claim_guards() {
    use openwiz_core::messaging::record::StoreError;
    struct ClaimSource(Option<Claim>);
    impl openwiz_store::attachments::Claims for ClaimSource {
        fn claim(&self, _: &AttachmentId) -> Result<Claim, StoreError> {
            self.0
                .ok_or_else(|| StoreError("synthetic claim lookup failure".to_owned()))
        }
    }
    for (case, claim) in [Some(Claim::Dispatching), Some(Claim::Uncertain), None]
        .into_iter()
        .enumerate()
    {
        let bench = Bench::new(&format!("ap08_meta_claim_{case}"));
        let id = add(&bench, "syn-ap08-claimed.png");
        let dir = bench.attachments().join(&id);
        let meta = dir.join(".meta.json");
        fs::remove_file(&meta).unwrap();
        std::os::unix::fs::symlink(bench.root.join("syn-missing-meta"), &meta).unwrap();
        let args: Vec<OsString> = ["rm", "--json", &id]
            .into_iter()
            .map(OsString::from)
            .collect();
        let run = bench.cli_with(&args, at(TTL_MS), &Free::new(PLENTY), &ClaimSource(claim));
        assert_eq!(run.code, if claim.is_some() { 14 } else { 10 }, "{run:?}");
        assert_eq!(run.json()["ids"].as_array().unwrap().len(), 1);
        assert_eq!(
            run.json()["ids"][0]["result"],
            if claim.is_some() {
                "refused"
            } else {
                "not_removed"
            }
        );
        assert!(dir.join("syn-ap08-claimed.png").exists());
        let removed = bench.cli_at(&["rm", "--json", &id], at(TTL_MS));
        assert_eq!(removed.code, 0, "{removed:?}");
        assert_eq!(removed.json()["ids"][0]["result"], "removed");
        assert!(!dir.exists());
    }
}
