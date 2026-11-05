//! The executor's strict reader and an independent schema checker agree.
use super::*;
fn contract() -> Value {
    serde_json::from_str(include_str!("../../contracts/loops.v1.schema.json")).unwrap()
}
#[test]
fn definitions_match_schema_good_and_bad_tables() {
    let f = Fixture::new("printf ''");
    let schema = contract();
    assert_eq!(pattern::lint(&schema), Vec::<String>::new());
    assert!(pattern::validate(&schema, &f.definition).is_empty());
    assert_eq!(f.runner().pass().unwrap().len(), 1);
    let mut bad = Vec::new();
    for key in ["authority", "check", "wake", "action", "budget", "enabled"] {
        let mut d = f.definition.clone();
        d.as_object_mut().unwrap().remove(key);
        bad.push(d);
    }
    for (pointer, value) in [
        ("/check/timeout_ms", json!(0)),
        ("/check/argv", json!([])),
        ("/check/argv", json!(["sh", ""])),
        ("/check/argv", json!(["sh", "\0"])),
        ("/enabled", json!("true")),
        ("/mode", json!({"active":null})),
        ("/priority", json!("unknown")),
        ("/action/project", json!(["id", "synthetic"])),
        ("/action/model", json!("-model")),
        ("/action/brief", json!("\u{3000}")),
        ("/action/brief", json!("é".repeat(8193))),
        ("/id", json!("é")),
        ("/authority/scope", json!("\0")),
        ("/wake/kind", json!("cron")),
    ] {
        let mut d = f.definition.clone();
        *d.pointer_mut(pointer).unwrap() = value;
        bad.push(d);
    }
    let mut extra = f.definition.clone();
    extra["unexpected"] = json!(true);
    bad.push(extra);
    for (i, definition) in bad.into_iter().enumerate() {
        assert!(
            !pattern::validate(&schema, &definition).is_empty(),
            "schema accepted bad case {i}"
        );
        f.commit_raw(&definition.to_string());
        assert!(f.runner().pass().is_err(), "executor accepted bad case {i}");
    }
    let duplicate = f.definition.to_string().replacen(
        "\"enabled\":true",
        "\"enabled\":true,\"enabled\":true",
        1,
    );
    assert_ne!(duplicate, f.definition.to_string());
    f.commit_raw(&duplicate);
    assert!(f.runner().pass().is_err());
    assert_eq!(f.spawns().len(), 0);
}
#[test]
fn exact_mathematical_integers_remain_valid() {
    let f = Fixture::new("printf ''");
    let bytes = f
        .definition
        .to_string()
        .replace("\"timeout_ms\":100", "\"timeout_ms\":1e2");
    assert_ne!(bytes, f.definition.to_string());
    f.commit_raw(&bytes);
    assert_eq!(f.runner().pass().unwrap().len(), 1);
}
#[test]
fn saved_run_is_schema_valid_and_owner_only() {
    let f = Fixture::new("printf finding");
    let runs = f.runner().pass().unwrap();
    assert_eq!(runs.len(), 1);
    assert!(pattern::validate(&contract(), &runs[0]).is_empty());
    let path = f.state.join(format!(
        "service/loops/runs/{}.json",
        runs[0]["id"].as_str().unwrap()
    ));
    assert_eq!(
        fs::metadata(&path).unwrap().permissions().mode() & 0o777,
        0o600
    );
    assert_eq!(
        fs::metadata(path.parent().unwrap())
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o700
    );
    assert_eq!(
        runs[0]["cost"],
        json!({"kind":"unknown","reason":"Not reported."})
    );
}
#[test]
fn duplicate_definition_ids_refuse_the_whole_pass() {
    let f = Fixture::new("printf ran > check-ran");
    fs::write(f.checkout.join("loops/copy.json"), f.definition.to_string()).unwrap();
    f.commit();
    assert!(f.runner().pass().is_err());
    assert!(!f.checkout.join("check-ran").exists());
    assert_eq!(f.spawns().len(), 0);
}
