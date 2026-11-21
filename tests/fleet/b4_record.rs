use std::fs;
use std::os::unix::fs::PermissionsExt;

use openwiz_cli::state::StartFileStore;
use openwiz_cli::state::starts::read;
use openwiz_core::fleet::starts::{Attempt, AttemptOutcome, Locked, StartRecord, StartStore};
use openwiz_core::model::Timestamp;
use serde_json::{Value, json};

use super::fake::*;

fn good() -> Value {
    json!({
        "schema": "openwiz.start-record.v1",
        "id": builder(7).key.id().as_str(),
        "key": {
            "repository": REPOSITORY,
            "role": "builder",
            "number": 7,
            "commit": null,
        },
        "project_id": PROJECT,
        "settings": {"harness": "claude-code", "model": "claude-opus-5-5", "effort": "xhigh"},
        "attempts": [
            {"op_id": "op-b4-r-1", "at": T0, "outcome": {"kind": "pending"}},
        ],
    })
}

fn good_reviewer() -> Value {
    json!({
        "schema": "openwiz.start-record.v1",
        "id": reviewer(9).key.id().as_str(),
        "key": {
            "repository": REPOSITORY,
            "role": "reviewer",
            "number": 9,
            "commit": COMMIT,
        },
        "project_id": PROJECT,
        "settings": {"harness": "codex", "model": "gpt-6.1-sol", "effort": "high"},
        "attempts": [
            {"op_id": "op-b4-r-1", "at": T0, "outcome":
                {"kind": "not_created", "status": "refused", "words": "Synthetic refusal"}},
            {"op_id": "op-b4-r-2", "at": T0, "outcome":
                {"kind": "not_created", "status": "failed", "words": "Synthetic failure"}},
            {"op_id": "op-b4-r-3", "at": T0, "outcome":
                {"kind": "created", "thread_id": THREAD}},
        ],
    })
}

fn with(edit: impl FnOnce(&mut Value)) -> String {
    let mut record = good();
    edit(&mut record);
    record.to_string()
}

#[test]
fn the_reader_takes_each_good_record_exactly() {
    let builder_record = read(&good().to_string()).expect("good");
    assert_eq!(builder_record.key(), &builder(7).key);
    assert_eq!(builder_record.settings(), &builder_settings());
    assert_eq!(
        builder_record.attempts()[0].outcome,
        AttemptOutcome::Pending
    );
    let reviewer_record = read(&good_reviewer().to_string()).expect("good");
    assert_eq!(reviewer_record.key(), &reviewer(9).key);
    assert_eq!(
        reviewer_record.attempts()[2].outcome,
        AttemptOutcome::Created {
            thread_id: THREAD.to_owned()
        }
    );
    let uncertain = with(|r| {
        r["attempts"][0]["outcome"] = json!({"kind": "uncertain", "words": "Synthetic"});
    });
    let record = read(&uncertain).expect("good");
    let again = read(&serde_json::to_string(&record).unwrap()).expect("its own JSON");
    assert_eq!(again, record);
    let again = read(&serde_json::to_string(&reviewer_record).unwrap()).expect("its own JSON");
    assert_eq!(again, reviewer_record);
}

#[test]
fn start_thread_ids_preserve_interior_hyphens_and_refuse_forbidden_bytes() {
    use openwiz_core::fleet::starts::safe_id;

    for (id, valid) in [
        ("a", true),
        ("_a", true),
        ("thr_syn-a_1", true),
        (&"a".repeat(128), true),
        ("", false),
        ("-thr_syn", false),
        (&"a".repeat(129), false),
        ("thr/syn", false),
        ("thr.syn", false),
        ("thr syn", false),
        ("thr\nsyn", false),
        ("thr\0syn", false),
        ("thr_é", false),
    ] {
        let request = builder(7);
        let outcome = AttemptOutcome::Created {
            thread_id: id.to_owned(),
        };
        let record = StartRecord::from_parts(
            request.key.id(),
            request.key,
            PROJECT.to_owned(),
            builder_settings(),
            vec![Attempt {
                op_id: op("op-id-grammar"),
                at: Timestamp(T0),
                outcome: outcome.clone(),
            }],
        );
        let decoded = read(&with(|r| {
            r["attempts"][0]["outcome"] = json!({"kind": "created", "thread_id": id})
        }));
        assert_eq!(
            decoded.is_ok(),
            valid,
            "strict reader thread {id:?}: {decoded:?}"
        );
        assert_eq!(
            record.is_ok(),
            valid,
            "from_parts thread {id:?}: {record:?}"
        );
        assert_eq!(safe_id(id), valid, "safe_id({id:?})");
        if valid {
            assert_eq!(record.unwrap().attempts()[0].outcome, outcome);
            assert_eq!(decoded.unwrap().attempts()[0].outcome, outcome);
        }
    }
}

#[test]
fn the_reader_refuses_every_other_shape() {
    let other_key_id = builder(8).key.id().as_str().to_owned();
    let pending = json!({"op_id": "op-b4-r-0", "at": T0, "outcome": {"kind": "pending"}});
    let cases: Vec<(&str, String)> = vec![
        ("not JSON", "{".to_owned()),
        (
            "a positional array",
            json!(["openwiz.start-record.v1"]).to_string(),
        ),
        (
            "a key given twice",
            good()
                .to_string()
                .replacen("\"schema\":", "\"schema\":\"x\",\"schema\":", 1),
        ),
        (
            "a nested key given twice",
            good()
                .to_string()
                .replacen("\"role\":", "\"role\":\"reviewer\",\"role\":", 1),
        ),
        (
            "a fractional number",
            with(|r| r["key"]["number"] = json!(7.0)),
        ),
        ("an extra key", with(|r| r["extra"] = json!(1))),
        (
            "a missing key",
            with(|r| {
                r.as_object_mut().unwrap().remove("project_id");
            }),
        ),
        (
            "another schema",
            with(|r| r["schema"] = json!("openwiz.start-record.v2")),
        ),
        (
            "an id not its key's",
            with(|r| r["id"] = json!(other_key_id)),
        ),
        ("an id not an id", with(|r| r["id"] = json!("-start"))),
        (
            "a key as a list",
            with(|r| r["key"] = json!([REPOSITORY, "builder", 7, null])),
        ),
        (
            "a key with an extra key",
            with(|r| r["key"]["extra"] = json!(1)),
        ),
        (
            "a role not in its list",
            with(|r| r["key"]["role"] = json!("Builder")),
        ),
        (
            "a role as a tagged object",
            with(|r| r["key"]["role"] = json!({"builder": null})),
        ),
        ("number 0", with(|r| r["key"]["number"] = json!(0))),
        (
            "a negative number",
            with(|r| r["key"]["number"] = json!(-7)),
        ),
        (
            "a number as a string",
            with(|r| r["key"]["number"] = json!("7")),
        ),
        (
            "a builder with a commit",
            with(|r| r["key"]["commit"] = json!(COMMIT)),
        ),
        (
            "a reviewer without a commit",
            with(|r| r["key"]["role"] = json!("reviewer")),
        ),
        (
            "a short commit",
            with(|r| {
                r["key"]["role"] = json!("reviewer");
                r["key"]["commit"] = json!("0123456");
            }),
        ),
        (
            "an upper-case commit",
            with(|r| {
                r["key"]["role"] = json!("reviewer");
                r["key"]["commit"] = json!(COMMIT.to_uppercase());
            }),
        ),
        (
            "a repository without an owner",
            with(|r| r["key"]["repository"] = json!("repo")),
        ),
        (
            "a repository not in lower case",
            with(|r| r["key"]["repository"] = json!("Synthetic-Owner/synthetic-repo-0001")),
        ),
        (
            "a repository named ..",
            with(|r| r["key"]["repository"] = json!("synthetic-owner/..")),
        ),
        (
            "a project id like a flag",
            with(|r| r["project_id"] = json!("-prj")),
        ),
        ("an empty project id", with(|r| r["project_id"] = json!(""))),
        (
            "settings without an effort",
            with(|r| {
                r["settings"].as_object_mut().unwrap().remove("effort");
            }),
        ),
        (
            "settings with an extra key",
            with(|r| r["settings"]["x"] = json!("y")),
        ),
        (
            "a setting with a space",
            with(|r| r["settings"]["model"] = json!("opus 5")),
        ),
        (
            "an empty setting",
            with(|r| r["settings"]["effort"] = json!("")),
        ),
        ("no attempt", with(|r| r["attempts"] = json!([]))),
        (
            "attempts as an object",
            with(|r| r["attempts"] = json!({"0": pending})),
        ),
        (
            "an op id not an op id",
            with(|r| r["attempts"][0]["op_id"] = json!("op id")),
        ),
        (
            "a time as a string",
            with(|r| r["attempts"][0]["at"] = json!("1700000000000")),
        ),
        (
            "a time before 1970",
            with(|r| r["attempts"][0]["at"] = json!(-1)),
        ),
        (
            "an outcome as a plain string",
            with(|r| r["attempts"][0]["outcome"] = json!("pending")),
        ),
        (
            "an outcome as a tagged object",
            with(|r| r["attempts"][0]["outcome"] = json!({"pending": null})),
        ),
        (
            "an outcome of no kind",
            with(|r| r["attempts"][0]["outcome"] = json!({"kind": "started"})),
        ),
        (
            "a pending outcome with an extra key",
            with(|r| r["attempts"][0]["outcome"]["words"] = json!("x")),
        ),
        (
            "a created outcome without its thread",
            with(|r| r["attempts"][0]["outcome"] = json!({"kind": "created"})),
        ),
        (
            "a created thread like a flag",
            with(|r| {
                r["attempts"][0]["outcome"] = json!({"kind": "created", "thread_id": "-thr"});
            }),
        ),
        (
            "a status not in its list",
            with(|r| {
                r["attempts"][0]["outcome"] =
                    json!({"kind": "not_created", "status": "uncertain", "words": "x"});
            }),
        ),
        (
            "an uncertain outcome without words",
            with(|r| r["attempts"][0]["outcome"] = json!({"kind": "uncertain"})),
        ),
        (
            "an attempt before the last one still pending",
            with(|r| r["attempts"] = json!([pending, r["attempts"][0].clone()])),
        ),
        (
            "an attempt before the last one that created its thread",
            with(|r| {
                let mut created = pending.clone();
                created["outcome"] = json!({"kind": "created", "thread_id": THREAD});
                r["attempts"] = json!([created, r["attempts"][0].clone()]);
            }),
        ),
        (
            "an op id given twice",
            with(|r| {
                let mut first = r["attempts"][0].clone();
                first["outcome"] = json!({"kind": "not_created", "status": "failed", "words": "x"});
                r["attempts"] = json!([first, r["attempts"][0].clone()]);
            }),
        ),
    ];
    for (what, text) in &cases {
        assert!(read(text).is_err(), "{what}: accepted {text}");
    }
    assert!(read(&with(|_| {})).is_ok());
}

fn record(value: &Value) -> StartRecord {
    read(&value.to_string()).expect("a good record")
}

#[test]
fn the_store_keeps_records_owner_only_and_writes_only_under_the_lock() {
    let fake = Fake::new("b4_store", vec![]);
    let (first, second) = (fake.starts(), fake.starts());
    let request = builder(7);
    let pending = record(&good());

    assert!(first.write(&pending).is_err());
    assert_eq!(first.lock(&request.key).unwrap(), Locked::Mine(None));
    assert_eq!(second.lock(&request.key).unwrap(), Locked::Busy);
    first.write(&pending).unwrap();
    first.unlock(&request.key);
    assert_eq!(
        second.lock(&request.key).unwrap(),
        Locked::Mine(Some(Box::new(pending.clone())))
    );
    second.unlock(&request.key);
    assert_eq!(first.inspect(&request.key).unwrap(), Some(pending));

    let dir = fake.state.join("starts");
    let mode = |p: &std::path::Path| fs::metadata(p).unwrap().permissions().mode() & 0o777;
    assert_eq!(mode(&dir), 0o700);
    let file = dir.join(format!("{}.json", request.key.id()));
    assert_eq!(mode(&file), 0o600);

    let other = builder(8);
    fs::copy(&file, dir.join(format!("{}.json", other.key.id()))).unwrap();
    assert!(first.inspect(&other.key).is_err());
    assert!(first.lock(&other.key).is_err());

    let read_only = StartFileStore::open_read_only(&fake.state)
        .unwrap()
        .expect("the record directory exists");
    assert!(read_only.lock(&request.key).is_err());
    assert!(read_only.inspect(&request.key).unwrap().is_some());
}
