use openwiz_adapter_cloudroom::new_thread::spawn_argv;
use openwiz_core::messaging::sha256_hex;
use openwiz_core::new_thread::operation::{NewThreadError, SpawnRequest, preview_new_thread};
use openwiz_core::prompt::{
    AttachmentId, ReadyPrompt, attachments_digest, empty_attachments_digest,
};

use crate::support::*;

fn with_attachment() -> openwiz_core::new_thread::NewThreadRequest {
    let mut r = request(offered(), "Synthetic with a file", "op-n14");
    r.prompt.attachments = vec![AttachmentId::parse("att-syn-0001").unwrap()];
    r
}

#[test]
fn n14_prompt_seam_contracts_preserve_all_original_cases() {
    let cases: [(&str, fn()); 4] = [
        (
            "a_text_only_prompt_passes_no_attachment_flag",
            a_text_only_prompt_passes_no_attachment_flag,
        ),
        (
            "an_attachment_id_is_one_safe_segment",
            an_attachment_id_is_one_safe_segment,
        ),
        (
            "the_empty_list_has_its_fixed_digest_on_every_record",
            the_empty_list_has_its_fixed_digest_on_every_record,
        ),
        (
            "without_an_attachment_store_any_attachment_is_refused_with_zero_calls_and_no_claim",
            without_an_attachment_store_any_attachment_is_refused_with_zero_calls_and_no_claim,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: n14_prompt_seam::{name}");
        proof();
    }
}

fn without_an_attachment_store_any_attachment_is_refused_with_zero_calls_and_no_claim() {
    let client = FakeClient::new();
    let store = MemoryStore::new();
    let Err(NewThreadError::Invalid(why)) = try_create(&client, &store, &with_attachment()) else {
        panic!("not refused")
    };
    assert!(
        why.0.starts_with("attachment att-syn-0001 is not found")
            && why.0.contains("nothing was sent"),
        "{}",
        why.0
    );
    assert_eq!(client.calls(), 0);
    assert_eq!(store.writes(), 0, "nothing claimed");
    assert!(preview_new_thread(&client, &clock(), &with_attachment()).is_err());
    assert_eq!(client.calls(), 0);
}

fn a_text_only_prompt_passes_no_attachment_flag() {
    let spawn = SpawnRequest {
        project_id: "prj_syn_0001".to_owned(),
        provider: "codex".to_owned(),
        model: "syn-codex-model-01".to_owned(),
        effort: "high".to_owned(),
        request_id: "ow1-synthetic".to_owned(),
        prompt: ReadyPrompt::text("Synthetic"),
    };
    assert!(spawn_argv(&spawn).is_err());
    let spawn = SpawnRequest {
        request_id: openwiz_core::new_thread::request_id(&op("op-n14-seam")),
        ..spawn
    };
    let argv = spawn_argv(&spawn).expect("valid");
    assert!(!argv.iter().any(|w| w == "--file" || w == "--image"));
    assert_eq!(argv.last().map(String::as_str), Some("Synthetic"));
}

fn the_empty_list_has_its_fixed_digest_on_every_record() {
    assert_eq!(
        empty_attachments_digest(),
        sha256_hex(b"openwiz.prompt.attachments.v1\n")
    );
    assert_eq!(attachments_digest(&[]), empty_attachments_digest());
    let client = FakeClient::new();
    let store = MemoryStore::new();
    let r = request(offered(), "Synthetic", "op-n14-digest");
    let report = create(&client, &store, &r);
    assert_eq!(report.attachments_digest, empty_attachments_digest());
    assert_eq!(
        store.get(&r.op_id).unwrap().binding.attachments_digest,
        empty_attachments_digest()
    );
}

fn an_attachment_id_is_one_safe_segment() {
    for good in ["a", "att-syn-0001", "A_1"] {
        assert!(AttachmentId::parse(good).is_ok(), "{good}");
    }
    let long = "a".repeat(65);
    for bad in ["", "-a", "_a", "a/b", "..", "a b", long.as_str()] {
        assert!(AttachmentId::parse(bad).is_err(), "{bad}");
    }
}
