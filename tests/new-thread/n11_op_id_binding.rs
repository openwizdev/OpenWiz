use openwiz_core::messaging::sha256_hex;
use openwiz_core::new_thread::operation::NewThreadResult;
use openwiz_core::new_thread::outcome::Status;
use openwiz_core::new_thread::record::NewThreadRecord;
use openwiz_core::new_thread::{
    Binding, BindingField, ProjectRef, REQUEST_ID_DOMAIN, REQUEST_ID_PREFIX, request_id,
};
use openwiz_core::prompt::empty_attachments_digest;

use crate::support::*;

#[test]
fn n11_op_id_binding_contracts_preserve_all_original_cases() {
    let cases: [(&str, fn()); 5] = [
        (
            "an_op_id_held_by_a_live_process_is_in_progress_with_no_call",
            an_op_id_held_by_a_live_process_is_in_progress_with_no_call,
        ),
        (
            "any_difference_is_refused_with_zero_calls",
            any_difference_is_refused_with_zero_calls,
        ),
        (
            "the_record_and_the_call_carry_the_derived_request_id",
            the_record_and_the_call_carry_the_derived_request_id,
        ),
        (
            "the_request_id_is_derived_deterministically_and_is_safe",
            the_request_id_is_derived_deterministically_and_is_safe,
        ),
        (
            "the_same_op_id_and_binding_make_one_call",
            the_same_op_id_and_binding_make_one_call,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: n11_op_id_binding::{name}");
        proof();
    }
}

fn the_same_op_id_and_binding_make_one_call() {
    let client = FakeClient::new();
    let store = MemoryStore::new();
    let r = request(offered(), "Synthetic once", "op-n11-same");
    let first = create(&client, &store, &r);
    let again = create(&client, &store, &r);
    assert_eq!(client.spawns(), 1);
    assert_eq!(first.status, Status::Created);
    assert_eq!(again.status, Status::Created);
    let NewThreadResult::Outcome { replayed, .. } = again.result else {
        panic!("{again:?}")
    };
    assert!(replayed, "the second is the recorded outcome");
}

fn any_difference_is_refused_with_zero_calls() {
    let base = request(offered(), "Synthetic base", "op-n11-diff");
    let mut variants = Vec::new();
    let mut r = base.clone();
    r.project = ProjectRef::Id("prj_syn_0004".to_owned());
    variants.push((r, BindingField::Project));
    let mut r = base.clone();
    r.project = ProjectRef::Name("Synthetic project one".to_owned());
    variants.push((r, BindingField::Project));
    let mut r = base.clone();
    r.settings.harness = "claude-code".to_owned();
    variants.push((r, BindingField::Harness));
    let mut r = base.clone();
    r.settings.model = "syn-codex-model-02".to_owned();
    variants.push((r, BindingField::Model));
    let mut r = base.clone();
    r.settings.effort = "low".to_owned();
    variants.push((r, BindingField::Effort));
    let mut r = base.clone();
    r.prompt.text = "Synthetic other".to_owned();
    variants.push((r, BindingField::Text));
    for (variant, field) in variants {
        let client = FakeClient::new();
        let store = MemoryStore::new();
        create(&client, &store, &base);
        assert_eq!(client.spawns(), 1);
        let report = create(&client, &store, &variant);
        assert_eq!(report.status, Status::ConflictingReuse, "{field:?}");
        let NewThreadResult::ConflictingReuse { differs } = &report.result else {
            panic!("{report:?}")
        };
        assert_eq!(differs, &vec![field]);
        assert_eq!(client.spawns(), 1, "{field:?}: no second call");
    }
}

fn an_op_id_held_by_a_live_process_is_in_progress_with_no_call() {
    let client = FakeClient::new();
    let store = MemoryStore::new();
    let r = request(offered(), "Synthetic", "op-n11-live");
    store.seed(
        NewThreadRecord::claimed(
            r.op_id.clone(),
            Binding::new(&r, empty_attachments_digest()),
            r.settings.clone(),
            "Synthetic",
            T0,
        ),
        true,
    );
    let report = create(&client, &store, &r);
    assert_eq!(report.status, Status::InProgress);
    assert_eq!(client.calls(), 0);
}

fn is_safe_request_id(id: &str) -> bool {
    (1..=64).contains(&id.len())
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

fn the_request_id_is_derived_deterministically_and_is_safe() {
    let max = "a".repeat(64);
    for id in ["op-1", "A", "op_with_underscores", "0-0-0", max.as_str()] {
        let op_id = op(id);
        let rid = request_id(&op_id);
        assert_eq!(rid, request_id(&op(id)), "deterministic");
        assert!(is_safe_request_id(&rid), "{rid}");
        assert_eq!(rid.len(), 44);
        let digest = sha256_hex(format!("{REQUEST_ID_DOMAIN}{id}").as_bytes());
        assert_eq!(rid, format!("{REQUEST_ID_PREFIX}{}", &digest[..40]));
    }
    assert_ne!(request_id(&op("op-1")), request_id(&op("op-2")));
}

fn the_record_and_the_call_carry_the_derived_request_id() {
    let client = FakeClient::new();
    let store = MemoryStore::new();
    let r = request(offered(), "Synthetic", "op-n11-rid");
    let report = create(&client, &store, &r);
    let rid = request_id(&r.op_id);
    assert_eq!(report.request_id, rid);
    assert_eq!(store.get(&r.op_id).unwrap().request_id, rid);
    assert_eq!(client.spawned.lock().unwrap()[0].0.request_id, rid);
}

#[test]
fn synthetic_request_id_matches_contract_at_spawn() {
    let client = FakeClient::new();
    let store = MemoryStore::new();
    let r = request(offered(), "Synthetic", "op-syn-1");
    let report = create(&client, &store, &r);
    let expected = "ow1-642d3823231f202a8a6907a9546ea7999a351f9c";
    assert_eq!(report.status, Status::Created);
    assert_eq!(report.request_id, expected);
    let spawned = client.spawned.lock().unwrap();
    assert_eq!(spawned.len(), 1);
    assert_eq!(spawned[0].0.request_id, expected);
}
