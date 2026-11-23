use std::path::Path;

use openwiz_core::messaging::send::UncertainReason;
use openwiz_core::model::Fact;
use openwiz_core::new_thread::outcome::{Outcome, RefusalReason};
use openwiz_core::new_thread::record::NewThreadRecord;
use openwiz_core::new_thread::{Binding, ProjectView};
use openwiz_core::prompt::{AttachmentId, PromptPayload, empty_attachments_digest};
use serde_json::{Value, json};

use crate::pattern;
use crate::support::*;

fn prompt_schema() -> Value {
    serde_json::from_str(&std::fs::read_to_string(PROMPT_SCHEMA).unwrap()).unwrap()
}

fn at(mut schema: Value, def: &str) -> Value {
    schema["$ref"] = json!(format!("#/$defs/{def}"));
    schema
}

fn table(name: &str, schema: &Value, rows: &[(bool, Value)]) {
    for (good, value) in rows {
        let errors = pattern::validate(schema, value);
        assert_eq!(errors.is_empty(), *good, "{name}: {value}\n{errors:#?}");
    }
}

fn with(value: &Value, pointer: &str, new: Value) -> Value {
    let mut v = value.clone();
    *v.pointer_mut(pointer)
        .unwrap_or_else(|| panic!("{pointer}")) = new;
    v
}

fn without(value: &Value, pointer: &str, key: &str) -> Value {
    let mut v = value.clone();
    v.pointer_mut(pointer)
        .and_then(Value::as_object_mut)
        .unwrap()
        .remove(key);
    v
}

fn adding(value: &Value, key: &str, new: Value) -> Value {
    let mut v = value.clone();
    v.as_object_mut().unwrap().insert(key.to_owned(), new);
    v
}

fn positional(value: &Value) -> Value {
    Value::Array(value.as_object().unwrap().values().cloned().collect())
}

#[test]
fn contract_tables_contracts_preserve_all_original_cases() {
    let cases: [(&str, fn()); 6] = [
        (
            "erased_created_records_require_both_digest_length_and_lowercase_hex",
            erased_created_records_require_both_digest_length_and_lowercase_hex,
        ),
        ("the_prompt_contract", the_prompt_contract),
        (
            "the_record_contract_with_nested_forms",
            the_record_contract_with_nested_forms,
        ),
        (
            "the_records_reader_follows_the_table",
            the_records_reader_follows_the_table,
        ),
        (
            "the_settings_and_project_reference_contracts",
            the_settings_and_project_reference_contracts,
        ),
        ("the_string_enum_contracts", the_string_enum_contracts),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: contract_tables::{name}");
        proof();
    }
}

fn the_prompt_contract() {
    let good = json!({"text": "Synthetic", "attachments": []});
    let rows = [
        (true, good.clone()),
        (false, json!(["Synthetic", []])),
        (false, positional(&good)),
        (false, adding(&good, "extra", json!(1))),
        (false, without(&good, "", "attachments")),
        (false, without(&good, "", "text")),
        (false, json!({"prompt": good})),
        (false, with(&good, "/text", json!(["Synthetic"]))),
        (false, with(&good, "/attachments", json!({}))),
        (false, with(&good, "/attachments", json!(["-att"]))),
        (false, with(&good, "/attachments", json!([""]))),
        (false, with(&good, "/attachments", json!(["a/b"]))),
        (false, with(&good, "/attachments", json!([1]))),
        (false, with(&good, "/text", json!(""))),
        (
            true,
            serde_json::to_value(PromptPayload::text("Synthetic")).unwrap(),
        ),
        (false, json!("Synthetic")),
        (false, Value::Null),
    ];
    table("prompt.v1", &prompt_schema(), &rows);
    table("new-thread prompt", &at(schema(), "prompt"), &rows);

    let messaging = at(
        serde_json::from_str(
            &std::fs::read_to_string(Path::new(ROOT).join("contracts/messaging.v1.schema.json"))
                .unwrap(),
        )
        .unwrap(),
        "request",
    );
    for (accepted, ids) in [
        (true, json!([])),
        (true, json!(["att-syn-0001"])),
        (true, json!(["att-syn-0001", "att-syn-0002"])),
        (false, json!(["att-syn-0001", "att-syn-0001"])),
    ] {
        let payload = with(&good, "/attachments", ids.clone());
        table(
            "prompt.v1",
            &prompt_schema(),
            &[(accepted, payload.clone())],
        );
        table(
            "new-thread prompt",
            &at(schema(), "prompt"),
            &[(accepted, payload)],
        );
        let request = json!({
            "target": "thr_syn_0001", "mode": "queue", "text": "Synthetic",
            "op_id": "op-synthetic", "attachments": ids,
        });
        let errors = crate::schema::validate(&messaging, &request);
        assert_eq!(errors.is_empty(), accepted, "messaging: {ids}: {errors:?}");
        let core = PromptPayload {
            text: "Synthetic".into(),
            attachments: ids
                .as_array()
                .unwrap()
                .iter()
                .map(|id| AttachmentId::parse(id.as_str().unwrap()).unwrap())
                .collect(),
        };
        assert_eq!(core.validate().is_ok(), accepted, "core: {ids}");
    }
}

fn the_settings_and_project_reference_contracts() {
    let settings = json!({"harness": "codex", "model": "syn-model", "effort": "high"});
    table(
        "settings",
        &at(schema(), "settings"),
        &[
            (true, settings.clone()),
            (false, json!(["codex", "syn-model", "high"])),
            (false, adding(&settings, "extra", json!("x"))),
            (false, without(&settings, "", "effort")),
            (false, json!({"settings": settings})),
            (false, with(&settings, "/effort", json!({"high": null}))),
        ],
    );
    let reference = json!({"kind": "id", "value": "prj_syn_0001"});
    table(
        "project_ref",
        &at(schema(), "project_ref"),
        &[
            (true, reference.clone()),
            (
                true,
                json!({"kind": "name", "value": "Synthetic project one"}),
            ),
            (false, json!(["id", "prj_syn_0001"])),
            (false, json!({"id": "prj_syn_0001"})),
            (false, json!({"kind": "id"})),
            (
                false,
                json!({"kind": "id", "value": "prj_syn_0001", "extra": 1}),
            ),
            (false, json!({"kind": "path", "value": "prj_syn_0001"})),
            (
                false,
                json!({"kind": {"id": null}, "value": "prj_syn_0001"}),
            ),
        ],
    );
}

fn the_string_enum_contracts() {
    for (def, label) in [
        ("record_state", "claimed"),
        ("status", "created"),
        ("binding_field", "project"),
        ("refusal_reason", "no_options"),
        ("fail_reason", "call_not_started"),
        ("uncertain_reason", "timed_out"),
    ] {
        table(
            def,
            &at(schema(), def),
            &[
                (true, json!(label)),
                (false, json!({label: null})),
                (false, json!({label: {}})),
                (false, json!([label])),
                (false, json!(format!("{label}-synthetic"))),
                (false, Value::Null),
            ],
        );
    }
}

fn record() -> Value {
    let r = request(offered(), "Synthetic", "op-tables");
    let mut record = NewThreadRecord::claimed(
        r.op_id.clone(),
        Binding::new(&r, empty_attachments_digest()),
        r.settings.clone(),
        "Synthetic",
        T0,
    );
    record.project = Some(ProjectView {
        id: "prj_syn_0001".to_owned(),
        name: Fact::Known("Synthetic project one".to_owned()),
    });
    serde_json::to_value(record).unwrap()
}

fn the_record_contract_with_nested_forms() {
    let claimed = record();
    let finished = with(
        &with(&claimed, "/state", json!("finished")),
        "/outcome",
        serde_json::to_value(Outcome::refused(RefusalReason::NoOptions)).unwrap(),
    );
    let uncertain = with(
        &finished,
        "/outcome",
        serde_json::to_value(Outcome::uncertain(UncertainReason::TimedOut)).unwrap(),
    );
    table(
        "record",
        &at(schema(), "record"),
        &[
            (true, claimed.clone()),
            (true, finished.clone()),
            (true, uncertain.clone()),
            (false, positional(&claimed)),
            (false, without(&claimed, "", "effects")),
            (false, without(&claimed, "", "outcome")),
            (false, with(&claimed, "/state", json!({"claimed": null}))),
            (false, adding(&claimed, "extra", json!(1))),
            (
                false,
                with(&claimed, "/binding", positional(&claimed["binding"])),
            ),
            (
                false,
                with(&claimed, "/binding/project", json!(["id", "prj_syn_0001"])),
            ),
            (
                false,
                with(&claimed, "/binding/project", json!({"id": "prj_syn_0001"})),
            ),
            (
                false,
                with(
                    &claimed,
                    "/requested",
                    json!(["codex", "syn-codex-model-01", "high"]),
                ),
            ),
            (false, without(&claimed, "/binding", "attachments_digest")),
            (
                false,
                with(&finished, "/outcome/reason", json!({"no_options": null})),
            ),
            (
                false,
                with(&finished, "/outcome/kind", json!({"refused": null})),
            ),
            (
                false,
                with(
                    &finished,
                    "/outcome",
                    json!({"refused": {"reason": "no_options"}}),
                ),
            ),
            (
                false,
                with(&uncertain, "/outcome/reason", json!(["timed_out"])),
            ),
            (
                false,
                with(
                    &claimed,
                    "/project",
                    json!(["prj_syn_0001", {"known": "Synthetic"}]),
                ),
            ),
            (false, json!({"record": claimed})),
        ],
    );
}

fn the_records_reader_follows_the_table() {
    let schema = at(schema(), "record");
    let claimed = record();
    let finished = with(
        &with(&claimed, "/state", json!("finished")),
        "/outcome",
        serde_json::to_value(Outcome::refused(RefusalReason::NoOptions)).unwrap(),
    );
    let mut rows = vec![claimed.clone(), finished.clone()];
    for (pointer, bad) in [
        ("/state", json!({"claimed": null})),
        ("/state", json!(["claimed"])),
        ("/state", json!("Claimed")),
        ("/binding", positional(&claimed["binding"])),
        ("/binding/project", json!(["id", "prj_syn_0001"])),
        ("/binding/project", json!({"id": "prj_syn_0001"})),
        ("/binding/project/kind", json!("path")),
        ("/binding/text_sha256", json!("ABC")),
        ("/binding/harness", json!("-codex")),
        ("/requested", json!(["codex", "syn-codex-model-01", "high"])),
        ("/requested/effort", json!(" high")),
        ("/op_id", json!("-op")),
        ("/request_id", json!("ow1-xyz")),
        ("/text", json!(7)),
        ("/text_bytes", json!(-1)),
        ("/text_bytes", json!(1.5)),
        ("/recovered", json!("false")),
        ("/claimed_at", json!(null)),
        ("/gaps", json!({})),
        ("/gaps", json!([{"subject": "s"}])),
        ("/project", json!(["prj_syn_0001", {"known": "Synthetic"}])),
        ("/project/name", json!("Synthetic")),
        ("/project/name", json!({"known": "a", "unknown": "b"})),
        ("/project/name", json!({"unknown": ""})),
        ("/schema", json!("openwiz.new-thread-record.v0")),
    ] {
        rows.push(with(&claimed, pointer, bad));
    }
    for (pointer, bad) in [
        ("/outcome/reason", json!({"no_options": null})),
        ("/outcome/kind", json!({"refused": null})),
        ("/outcome", json!({"refused": {"reason": "no_options"}})),
        ("/outcome/offered", json!("none")),
        ("/outcome/text", json!("")),
    ] {
        rows.push(with(&finished, pointer, bad));
    }
    rows.push(adding(&claimed, "extra", json!(1)));
    rows.push(without(&claimed, "", "effects"));
    rows.push(without(&claimed, "/binding", "attachments_digest"));
    rows.push(adding(
        &finished["outcome"].clone(),
        "kind",
        json!("created"),
    ));
    rows.push(positional(&claimed));
    for row in rows {
        let schema_ok = pattern::validate(&schema, &row).is_empty();
        let reader = read(&row);
        assert_eq!(
            reader.is_ok(),
            schema_ok,
            "{row}
{reader:?}"
        );
    }

    let text = claimed.to_string();
    for (from, to) in [
        ("\"schema\":", "\"schema\":\"x\",\"schema\":"),
        ("\"harness\":", "\"harness\":\"codex\",\"harness\":"),
        ("\"kind\":", "\"kind\":\"id\",\"kind\":"),
        ("\"known\":", "\"known\":\"a\",\"known\":"),
    ] {
        let twice = text.replacen(from, to, 1);
        assert_ne!(twice, text, "{from}");
        let tree: Result<openwiz_core::new_thread::read::StrictJson, _> =
            serde_json::from_str(&twice);
        assert!(tree.is_err(), "a key given twice: {twice}");
    }
}

fn erased_created_records_require_both_digest_length_and_lowercase_hex() {
    let claimed = read(&record()).unwrap();
    let created = claimed
        .dispatching(T0)
        .finished(Outcome::created("thr_syn_0021".to_owned()), T0);
    assert_eq!(
        created.text, None,
        "no text-hash consistency check can mask the shape rule"
    );
    let created = serde_json::to_value(created).unwrap();
    let schema = at(schema(), "record");
    for (valid, digest) in [
        (
            true,
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".to_owned(),
        ),
        (false, "a".repeat(63)),
        (false, "a".repeat(65)),
        (false, "g".repeat(64)),
        (false, "A".repeat(64)),
    ] {
        let row = with(&created, "/binding/text_sha256", json!(digest));
        let errors = pattern::validate(&schema, &row);
        assert_eq!(errors.is_empty(), valid, "schema: {digest}: {errors:?}");
        let result = read(&row);
        assert_eq!(
            result.is_ok(),
            valid,
            "strict record reader: {digest}: {result:?}"
        );
    }
}

fn read(value: &Value) -> Result<NewThreadRecord, String> {
    let tree: openwiz_core::new_thread::read::StrictJson =
        serde_json::from_str(&value.to_string()).map_err(|e| format!("tree: {e}"))?;
    NewThreadRecord::read(&tree).map_err(|e| e.0)
}
