use openwiz_adapter_cloudroom::new_thread::spawn_argv;
use openwiz_core::messaging::sha256_hex;
use openwiz_core::new_thread::operation::SpawnRequest;
use openwiz_core::prompt::{ReadyPrompt, attachments_digest, empty_attachments_digest};

use crate::support::*;

#[test]
fn n14_prompt_seam_contracts_preserve_all_original_cases() {
    let cases: [(&str, fn()); 2] = [
        (
            "a_text_only_prompt_passes_no_attachment_flag",
            a_text_only_prompt_passes_no_attachment_flag,
        ),
        (
            "the_empty_list_has_its_fixed_digest_on_every_record",
            the_empty_list_has_its_fixed_digest_on_every_record,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: n14_prompt_seam::{name}");
        proof();
    }
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
