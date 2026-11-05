//! #244: hold the inspection/fork/claim window open at the store seam.
//! The inspection fixture gives a child a clone of its locked open file,
//! as a concurrent fork can. Claim still runs through the real file store.

use std::fs::File;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use openwiz_core::messaging::OpId;
use openwiz_core::messaging::record::StoreError;
use openwiz_core::messaging::send::UncertainReason;
use openwiz_core::model::Timestamp;
use openwiz_core::new_thread::Binding;
use openwiz_core::new_thread::operation::{NewThreadResult, new_thread_with};
use openwiz_core::new_thread::outcome::{FailReason, Outcome, Status};
use openwiz_core::new_thread::record::{Claim, NewThreadRecord, NewThreadStore, recover};
use openwiz_core::prompt::{NoAttachments, empty_attachments_digest};
use openwiz_store::NewThreadFileStore;

use crate::support::{FakeClient, T0, clock, offered, private_dir, request};

struct InspectionCopy {
    inner: NewThreadFileStore,
    lock: PathBuf,
    child: Mutex<Option<Child>>,
}

impl Drop for InspectionCopy {
    fn drop(&mut self) {
        if let Some(mut child) = self.child.lock().unwrap().take() {
            child.kill().expect("stop this test's child");
            child.wait().expect("reap this test's child");
        }
    }
}

impl NewThreadStore for InspectionCopy {
    fn load(&self, op_id: &OpId) -> Result<Option<NewThreadRecord>, StoreError> {
        self.inner.load(op_id)
    }

    fn claim(&self, record: &NewThreadRecord, now: Timestamp) -> Result<Claim, StoreError> {
        self.inner.claim(record, now)
    }

    fn update(&self, record: &NewThreadRecord) -> Result<(), StoreError> {
        self.inner.update(record)
    }

    fn release(&self, op_id: &OpId) {
        self.inner.release(op_id);
    }

    fn inspect(&self, op_id: &OpId, now: Timestamp) -> Result<Option<NewThreadRecord>, StoreError> {
        // A stopped-owner inspection: take the lock, reread, recover only
        // in memory. Keep its child's copy until after the following claim,
        // explicitly widening the real fork-to-exec window (#176/#244).
        let file = File::open(&self.lock).expect("inspection lock");
        file.try_lock().expect("the owner's lock is free");
        let shown = self.inner.record(op_id)?.map(|r| recover(&r, now));
        let child = Command::new("sleep")
            .arg("600")
            .stdin(Stdio::from(file.try_clone().expect("copy the open file")))
            .spawn()
            .expect("a child with the inspection's locked open file");
        *self.child.lock().unwrap() = Some(child);
        drop(file);
        let id = crate::forks::file_id(&self.lock);
        assert!(
            crate::forks::lock_on(&id).is_some(),
            "the child's copy still holds the inspection lock"
        );
        Ok(shown)
    }

    fn withdraw(&self, op_id: &OpId) -> Result<(), StoreError> {
        self.inner.withdraw(op_id)
    }
}

#[test]
fn a_stopped_owner_recovers_despite_a_child_copy_of_an_inspection_lock() {
    stopped_owner(
        "claimed",
        false,
        Status::Failed,
        Outcome::failed(FailReason::InterruptedBeforeDispatch),
    );
}

#[test]
fn a_stopped_dispatching_owner_stays_uncertain_despite_an_inspection_copy() {
    stopped_owner(
        "dispatching",
        true,
        Status::Uncertain,
        Outcome::uncertain(UncertainReason::InterruptedAfterDispatchMark),
    );
}

fn stopped_owner(name: &str, dispatching: bool, status: Status, expected: Outcome) {
    let state = private_dir(&format!("inspect-claim-{name}")).join("state");
    let owner = NewThreadFileStore::open(&state).unwrap();
    let request = request(offered(), "Synthetic stopped owner", "op-inspect-claim");
    let claimed = NewThreadRecord::claimed(
        request.op_id.clone(),
        Binding::new(&request, empty_attachments_digest()),
        request.settings.clone(),
        &request.prompt.text,
        T0,
    );
    assert_eq!(owner.claim(&claimed, T0).unwrap(), Claim::Owned);
    if dispatching {
        owner.update(&claimed.dispatching(T0)).unwrap();
    }
    owner.release(&request.op_id);
    let lock = state.join("new-threads/op-inspect-claim.lock");
    crate::forks::wait_until_unlocked(&lock);
    let store = InspectionCopy {
        inner: NewThreadFileStore::open(&state).unwrap(),
        lock,
        child: Mutex::new(None),
    };
    let client = FakeClient::new();
    let report = new_thread_with(&client, &store, &NoAttachments, &clock(), &request)
        .expect("recover the stopped owner");
    let NewThreadResult::Outcome {
        outcome, recovered, ..
    } = report.result
    else {
        panic!("expected recovery, got {report:?}");
    };
    assert_eq!(outcome, expected, "{name}");
    assert!(recovered, "{name}");
    assert_eq!(report.status, status, "{name}");
    assert_eq!(client.calls(), 0, "recovery makes no client call");
    let saved = store.inner.record(&request.op_id).unwrap().unwrap();
    assert!(saved.recovered, "claim persists the recovered outcome");
    assert_eq!(saved.outcome, Some(expected));
}
