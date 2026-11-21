use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::sync::Mutex;
use std::time::Duration;

use openwiz_core::attachment::{
    Claim, FailReason, Kind, PromptAttachment, SafeName, Sha256, StagedAttachment, StagedPath,
};
use openwiz_core::messaging::record::StoreError;
use openwiz_core::messaging::send::{Delivery, WaitingOn};
use openwiz_core::messaging::{Mode, OpId, sha256_hex};
use openwiz_core::model::Timestamp;
use openwiz_core::new_thread::outcome::Outcome;
use openwiz_core::prompt::{
    AttachmentId, ClaimOutcome, GateError, Lookup, NOT_REPORTED, OpKind, OpRef, Problem,
    PromptPayload, ReadyPrompt, StagedAttachments, attachment_allowance, attachments_digest,
    claimable, empty_attachments_digest, gate, handed_over,
};
use serde_json::{Value, json};

use crate::support::ROOT;

const T0: Timestamp = Timestamp(1_700_000_600_000);
const TTL: Duration = Duration::from_secs(24 * 60 * 60);

fn read(path: &str) -> String {
    fs::read_to_string(Path::new(ROOT).join(path)).unwrap_or_else(|e| panic!("{path}: {e}"))
}

fn op(kind: OpKind, id: &str) -> OpRef {
    OpRef {
        kind,
        op_id: OpId::parse(id).unwrap(),
    }
}

fn attachment(id: &str, name: &str, kind: Kind, bytes: &[u8]) -> PromptAttachment {
    PromptAttachment {
        id: AttachmentId::parse(id).unwrap(),
        sha256: Sha256::parse(&sha256_hex(bytes)).unwrap(),
        size_bytes: bytes.len() as u64,
        kind,
        name: SafeName::parse(name).unwrap(),
    }
}

fn staged(a: PromptAttachment) -> StagedAttachment {
    StagedAttachment {
        path: StagedPath::new(Path::new("/synthetic/state/attachments"), &a.id, &a.name).unwrap(),
        attachment: a,
    }
}

#[test]
fn ad_static_affected_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 7] = [
        (
            "a_prompt_lists_an_attachment_once",
            a_prompt_lists_an_attachment_once,
        ),
        (
            "files_go_first_then_images_each_in_the_owners_order",
            files_go_first_then_images_each_in_the_owners_order,
        ),
        (
            "the_allowance_is_one_second_per_started_mib",
            the_allowance_is_one_second_per_started_mib,
        ),
        (
            "the_claim_rule_follows_retention",
            the_claim_rule_follows_retention,
        ),
        (
            "the_digest_is_the_canonical_list_in_the_owners_order_and_the_empty_one_is_fixed",
            the_digest_is_the_canonical_list_in_the_owners_order_and_the_empty_one_is_fixed,
        ),
        (
            "the_gate_passes_every_attachment_or_names_every_one_that_cant_go",
            the_gate_passes_every_attachment_or_names_every_one_that_cant_go,
        ),
        (
            "the_messaging_schema_takes_attachments_only_in_their_shape",
            the_messaging_schema_takes_attachments_only_in_their_shape,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: ad_static::{name}");
        proof();
    }
}

fn the_digest_is_the_canonical_list_in_the_owners_order_and_the_empty_one_is_fixed() {
    assert_eq!(
        attachments_digest(&[]),
        sha256_hex(b"openwiz.prompt.attachments.v1\n")
    );
    assert_eq!(empty_attachments_digest(), attachments_digest(&[]));
    let a = attachment("att-syn-1", "syn-notes.txt", Kind::File, b"notes");
    let b = attachment("att-syn-2", "syn-photo.png", Kind::Image, b"photo");
    let canonical = format!(
        "openwiz.prompt.attachments.v2\n{} 5 file syn-notes.txt\n{} 5 image syn-photo.png\n",
        sha256_hex(b"notes"),
        sha256_hex(b"photo")
    );
    assert_eq!(
        attachments_digest(&[a.clone(), b.clone()]),
        sha256_hex(canonical.as_bytes())
    );
    assert_ne!(
        attachments_digest(&[a.clone(), b.clone()]),
        attachments_digest(&[b.clone(), a.clone()])
    );
    let same_bytes = attachment("att-syn-9", "syn-notes.txt", Kind::File, b"notes");
    assert_eq!(attachments_digest(&[a]), attachments_digest(&[same_bytes]));
}

fn files_go_first_then_images_each_in_the_owners_order() {
    let prompt = ReadyPrompt {
        text: "Synthetic".to_owned(),
        attachments: vec![
            staged(attachment("att-i1", "i1.png", Kind::Image, b"1")),
            staged(attachment("att-f1", "f1.txt", Kind::File, b"2")),
            staged(attachment("att-i2", "i2.png", Kind::Image, b"3")),
            staged(attachment("att-f2", "f2.txt", Kind::File, b"4")),
        ],
    };
    let order: Vec<String> = prompt
        .dispatch_order()
        .iter()
        .map(|a| a.attachment.id.as_str().to_owned())
        .collect();
    assert_eq!(order, ["att-f1", "att-f2", "att-i1", "att-i2"]);
    let bound: Vec<String> = prompt
        .bound()
        .iter()
        .map(|a| a.id.as_str().to_owned())
        .collect();
    assert_eq!(bound, ["att-i1", "att-f1", "att-i2", "att-f2"]);
}

fn the_allowance_is_one_second_per_started_mib() {
    for (bytes, secs) in [
        (0, 0),
        (1, 1),
        (1024 * 1024, 1),
        (1024 * 1024 + 1, 2),
        (25 * 1024 * 1024, 25),
    ] {
        assert_eq!(
            attachment_allowance(bytes),
            Duration::from_secs(secs),
            "{bytes}"
        );
    }
}

fn a_prompt_lists_an_attachment_once() {
    let mut p = PromptPayload::text("Synthetic");
    p.attachments = vec![
        AttachmentId::parse("att-a").unwrap(),
        AttachmentId::parse("att-b").unwrap(),
    ];
    assert!(p.validate().is_ok());
    p.attachments.push(AttachmentId::parse("att-a").unwrap());
    assert!(
        p.validate()
            .unwrap_err()
            .0
            .contains("att-a is listed twice")
    );
}

fn the_claim_rule_follows_retention() {
    let me = op(OpKind::Send, "op-me");
    let other = op(OpKind::NewThread, "op-other");
    let fresh = Duration::from_secs(60);
    let old = TTL;
    assert_eq!(claimable(&me, None, fresh), Ok(()));
    assert_eq!(claimable(&me, None, old), Err(Problem::Expired));
    for claim in [
        Claim::Dispatching,
        Claim::Accepted,
        Claim::Uncertain,
        Claim::Failed,
    ] {
        assert_eq!(
            claimable(&me, Some(&(me.clone(), claim)), old),
            Ok(()),
            "{claim:?}"
        );
    }
    assert_eq!(
        claimable(&me, Some(&(other.clone(), Claim::Failed)), fresh),
        Ok(())
    );
    assert_eq!(
        claimable(&me, Some(&(other.clone(), Claim::Failed)), old),
        Err(Problem::Expired)
    );
    for claim in [Claim::Dispatching, Claim::Accepted, Claim::Uncertain] {
        assert_eq!(
            claimable(&me, Some(&(other.clone(), claim)), fresh),
            Err(Problem::InUse {
                op: other.clone(),
                claim
            }),
            "{claim:?}"
        );
    }
    let twin = op(OpKind::NewThread, "op-me");
    assert!(claimable(&me, Some(&(twin, Claim::Dispatching)), fresh).is_err());
}

#[derive(Default)]
struct Memory {
    lookups: BTreeMap<String, Lookup>,
    claims: Mutex<Vec<(OpRef, Vec<AttachmentId>)>>,
    reads: Mutex<Vec<String>>,
}

impl StagedAttachments for Memory {
    fn look_up(&self, id: &AttachmentId, _now: Timestamp) -> Result<Lookup, StoreError> {
        self.reads.lock().unwrap().push(id.as_str().to_owned());
        Ok(self
            .lookups
            .get(id.as_str())
            .cloned()
            .unwrap_or(Lookup::NotFound))
    }
    fn claim(
        &self,
        op: &OpRef,
        ids: &[AttachmentId],
        _now: Timestamp,
    ) -> Result<ClaimOutcome, StoreError> {
        self.claims.lock().unwrap().push((op.clone(), ids.to_vec()));
        Ok(ClaimOutcome::Claimed { new: ids.to_vec() })
    }
    fn unclaim(&self, _op: &OpRef, _ids: &[AttachmentId]) -> Result<(), StoreError> {
        Ok(())
    }
    fn settle(
        &self,
        _op: &OpRef,
        _ids: &[AttachmentId],
        _now: Timestamp,
    ) -> Result<(), StoreError> {
        Ok(())
    }
}

fn ready_lookup(a: PromptAttachment, at: Timestamp, claim: Option<(OpRef, Claim)>) -> Lookup {
    Lookup::Ready {
        staged: staged(a),
        ready_at: at,
        claim,
    }
}

fn the_gate_passes_every_attachment_or_names_every_one_that_cant_go() {
    let me = op(OpKind::Send, "op-gate");
    let other = op(OpKind::Send, "op-other");
    let mut memory = Memory::default();
    let good = attachment("att-good", "good.txt", Kind::File, b"good");
    memory
        .lookups
        .insert("att-good".into(), ready_lookup(good.clone(), T0, None));
    memory.lookups.insert(
        "att-expired".into(),
        ready_lookup(
            attachment("att-expired", "e.txt", Kind::File, b"e"),
            Timestamp(T0.0 - 25 * 3_600_000),
            None,
        ),
    );
    memory.lookups.insert(
        "att-busy".into(),
        ready_lookup(
            attachment("att-busy", "b.txt", Kind::File, b"b"),
            T0,
            Some((other.clone(), Claim::Dispatching)),
        ),
    );
    memory.lookups.insert(
        "att-broken".into(),
        Lookup::Failed(FailReason::SizeMismatch),
    );
    let mut payload = PromptPayload::text("Synthetic");
    payload.attachments = [
        "att-good",
        "att-missing",
        "att-expired",
        "att-busy",
        "att-broken",
    ]
    .iter()
    .map(|id| AttachmentId::parse(id).unwrap())
    .collect();
    let Err(GateError::Refused(refusal)) = gate(&memory, &payload, &me, T0) else {
        panic!("not refused")
    };
    let named: Vec<(&str, &Problem)> = refusal
        .problems
        .iter()
        .map(|p| (p.id.as_str(), &p.problem))
        .collect();
    assert_eq!(
        named,
        [
            ("att-missing", &Problem::NotFound),
            ("att-expired", &Problem::Expired),
            (
                "att-busy",
                &Problem::InUse {
                    op: other,
                    claim: Claim::Dispatching
                }
            ),
            ("att-broken", &Problem::Failed(FailReason::SizeMismatch)),
        ]
    );
    assert_eq!(memory.reads.lock().unwrap().len(), 5);
    assert!(memory.claims.lock().unwrap().is_empty());
    payload.attachments = vec![AttachmentId::parse("att-good").unwrap()];
    let ready = gate(&memory, &payload, &me, T0).unwrap();
    assert_eq!(ready.bound(), vec![good]);
    assert!(
        memory.claims.lock().unwrap().is_empty(),
        "the gate claims nothing"
    );
}

#[test]
fn ad08_the_wording_table_and_no_stronger_claim() {
    assert_eq!(
        handed_over(1),
        ", with 1 attachment handed to CloudRoom. Delivery to the agent's machine is not reported"
    );
    assert_eq!(
        handed_over(3),
        ", with 3 attachments handed to CloudRoom. Delivery to the agent's machine is not reported"
    );
    assert_eq!(
        NOT_REPORTED,
        "Delivery to the agent's machine is not reported"
    );
    let queued = Delivery::queued(WaitingOn::ThreadBusy, "qm_syn_1".to_owned()).with_attachments(2);
    assert_eq!(
        queued.text(),
        "queued: thread busy, with 2 attachments handed to CloudRoom. Delivery to the agent's \
         machine is not reported"
    );
    let sent = Delivery::accepted(Mode::Queue).with_attachments(1);
    assert!(sent.text().ends_with(&handed_over(1)), "{}", sent.text());
    let created = Outcome::created("thr_syn_1".to_owned()).with_attachments(2);
    assert!(
        created.text().ends_with(&handed_over(2)),
        "{}",
        created.text()
    );
    for unchanged in [
        Delivery::failed(openwiz_core::messaging::send::FailReason::InvalidInput)
            .with_attachments(2),
        Delivery::uncertain(openwiz_core::messaging::send::UncertainReason::TimedOut)
            .with_attachments(2),
    ] {
        assert!(
            !unchanged.text().contains("CloudRoom"),
            "{}",
            unchanged.text()
        );
    }
}

fn messaging_schema() -> Value {
    serde_json::from_str(&read("contracts/messaging.v1.schema.json")).unwrap()
}

fn validate_messaging(def: &str, value: &Value) -> Vec<String> {
    let mut schema = messaging_schema();
    schema["$ref"] = json!(format!("#/$defs/{def}"));
    crate::schema::validate(&schema, value)
}

fn the_messaging_schema_takes_attachments_only_in_their_shape() {
    let a = json!({
        "id": "att-syn-1",
        "sha256": "a".repeat(64),
        "size_bytes": 5,
        "kind": "file",
        "name": "syn-notes.txt",
    });
    assert_eq!(
        validate_messaging("prompt_attachment", &a),
        Vec::<String>::new()
    );
    for (key, bad) in [
        ("kind", json!("photo")),
        ("size_bytes", json!(-1)),
        ("sha256", json!("ABC")),
        ("name", json!("")),
    ] {
        let mut v = a.clone();
        v[key] = bad;
        assert!(
            !validate_messaging("prompt_attachment", &v).is_empty(),
            "{key}"
        );
    }
    let mut extra = a.clone();
    extra["display_name"] = json!("Synthetic.txt");
    assert!(!validate_messaging("prompt_attachment", &extra).is_empty());
    let read = |v: &Value| serde_json::from_value::<PromptAttachment>(v.clone());
    assert!(read(&a).is_ok());
    for (key, bad) in [
        ("kind", json!("photo")),
        ("size_bytes", json!(-1)),
        ("sha256", json!("ABC")),
        ("name", json!("")),
    ] {
        let mut v = a.clone();
        v[key] = bad;
        assert!(read(&v).is_err(), "{key}");
    }
    assert!(read(&extra).is_err(), "an extra key");
    let mut missing = a.clone();
    missing.as_object_mut().unwrap().remove("name");
    assert!(read(&missing).is_err(), "a missing key");
    assert!(!validate_messaging("prompt_attachment", &missing).is_empty());
    let twice = r#"{"id": "att-syn-1", "id": "att-syn-2", "sha256": "SHA", "size_bytes": 5, "kind": "file", "name": "syn-notes.txt"}"#
        .replace("SHA", &"a".repeat(64));
    assert!(serde_json::from_str::<PromptAttachment>(&twice).is_err());
    let binding = json!({
        "target": "thr_syn_0001",
        "mode": "queue",
        "text_sha256": "b".repeat(64),
        "attachments_digest": "c".repeat(64),
    });
    assert_eq!(
        validate_messaging("binding", &binding),
        Vec::<String>::new()
    );
    let mut old = binding.clone();
    old.as_object_mut().unwrap().remove("attachments_digest");
    assert_eq!(
        validate_messaging("binding", &old),
        Vec::<String>::new(),
        "absent means none"
    );
    let schema = messaging_schema();
    let report = &schema["$defs"]["report"]["properties"];
    assert!(report.get("attachments").is_some() && report.get("attachments_digest").is_some());
    let required = schema["$defs"]["report"]["required"].as_array().unwrap();
    assert!(
        !required.contains(&json!("attachments")),
        "absent when there are none"
    );
    let differs = &schema["$defs"]["result"];
    assert!(
        differs.to_string().contains("\"attachments\""),
        "differs names attachments"
    );
}
