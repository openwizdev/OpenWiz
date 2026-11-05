//! Synthetic LP1/LP2: strict configuration projection at the planner/runner seam.
use openwiz_core::loops::*;
use openwiz_service::loops::limits;
use serde_json::{Value, json};
use std::{io, num::NonZeroU64};

#[path = "l11_limits/planner.rs"]
mod planner;
#[path = "l11_limits/runner.rs"]
mod runner;
#[path = "../fleet/schema.rs"]
mod schema;

const APPROVED: &str =
    r#"{"checks":{"max":4,"urgent_reserve":1},"agents":{"max":16,"urgent_reserve":4}}"#;
fn config(record: &str) -> String {
    format!(
        r#"{{"schema":"openwiz.service-config.v1","loops":{{"limits":{record},"approvals":[]}}}}"#
    )
}
fn approved() -> Limits {
    limits::read(config(APPROVED).as_bytes()).expect("explicit LP1 values")
}
fn record_verdict(value: &Value) -> bool {
    let mut contract: Value =
        serde_json::from_str(include_str!("../../contracts/service.v1.schema.json")).unwrap();
    contract["oneOf"] = json!([{"$ref":"#/$defs/loop_limits"}]);
    assert!(schema::lint(&contract).is_empty());
    schema::validate(&contract, value).is_empty()
}
#[test]
fn approved_record_and_schema() {
    assert!(record_verdict(&serde_json::from_str(APPROVED).unwrap()));
    assert_eq!(
        approved(),
        Limits {
            checks: Capacity {
                max: 4,
                urgent_reserve: 1
            },
            agents: Capacity {
                max: 16,
                urgent_reserve: 4
            },
        }
    );
}
fn invalid_records() -> Vec<String> {
    let mut cases = vec!["null".into(), "[]".into(), "{}".into()];
    let base: Value = serde_json::from_str(APPROVED).unwrap();
    for group in ["checks", "agents"] {
        let mut missing = base.clone();
        missing.as_object_mut().unwrap().remove(group);
        cases.push(missing.to_string());
        for replacement in [json!(null), json!([]), json!("private-synthetic-input")] {
            let mut bad = base.clone();
            bad[group] = replacement;
            cases.push(bad.to_string());
        }
        for field in ["max", "urgent_reserve"] {
            let mut missing = base.clone();
            missing[group].as_object_mut().unwrap().remove(field);
            cases.push(missing.to_string());
            for invalid in [
                json!(null),
                json!(true),
                json!("4"),
                json!([]),
                json!({}),
                json!(-1),
                json!(0),
                json!(2),
                json!(17),
                json!(u64::MAX),
            ] {
                let mut bad = base.clone();
                bad[group][field] = invalid;
                cases.push(bad.to_string());
            }
            // Strict service integer syntax: fractional and exponent forms fail,
            // even where JSON Schema treats an integral float as mathematical integer.
            let literal = format!("\"{field}\":{}", base[group][field]);
            for number in ["4.5", "4.0", "4e0", "18446744073709551616", "1e999"] {
                let mut bad = base.clone();
                bad[group][field] = json!("numeric-placeholder");
                cases.push(bad.to_string().replace("\"numeric-placeholder\"", number));
            }
            let original = base[group].to_string();
            cases.push(base.to_string().replacen(
                &original,
                &original.replacen(&literal, &format!("{literal},{literal}"), 1),
                1,
            ));
        }
        let mut extra = base.clone();
        extra[group]["fallback"] = json!(4);
        cases.push(extra.to_string());
    }
    let mut extra = base;
    extra["fleet"] = json!(16);
    cases.push(extra.to_string());
    cases
}
#[test]
fn refused_records() {
    for record in invalid_records() {
        assert!(
            limits::read(config(&record).as_bytes()).is_err(),
            "accepted {record}"
        );
        if let Ok(value) = serde_json::from_str::<Value>(&record)
            && !record.contains(".0")
            && !record.contains("e0")
            && !record.contains("18446744073709551616")
            && !record.contains("\"max\":4,\"max\":4")
            && !record.contains("\"max\":16,\"max\":16")
            && !record.contains("\"urgent_reserve\":1,\"urgent_reserve\":1")
            && !record.contains("\"urgent_reserve\":4,\"urgent_reserve\":4")
        {
            assert!(!record_verdict(&value), "schema accepted {record}");
        }
    }
}
fn invalid_configs() -> Vec<String> {
    vec![
        "".into(),
        "{".into(),
        "null".into(),
        "[]".into(),
        "{}".into(),
        r#"{"loops":null}"#.into(),
        r#"{"loops":[]}"#.into(),
        r#"{"loops":{}}"#.into(),
        format!("{} trailing", config(APPROVED)),
        format!(r#"{{"loops":{{"limits":{APPROVED},"limits":{APPROVED}}}}}"#),
        format!(r#"{{"loops":{{"limits":{APPROVED}}},"loops":{{"limits":{APPROVED}}}}}"#),
        format!(r#"{{"other":{{"x":1,"x":1}},"loops":{{"limits":{APPROVED}}}}}"#),
    ]
}
#[test]
fn refused_configurations() {
    for config in invalid_configs() {
        let error = limits::read(config.as_bytes()).unwrap_err();
        assert!(!error.contains("private-synthetic-input"));
    }
    assert!(limits::read(&b"\xff"[..]).is_err());
}
struct BrokenRead;
impl io::Read for BrokenRead {
    fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
        Err(io::Error::other("private-synthetic-input"))
    }
}
#[test]
fn unreadable_input() {
    let error = limits::read(BrokenRead).unwrap_err();
    assert!(!error.contains("private-synthetic-input"));
    // Complete bytes followed by an I/O failure must not become a valid record.
    assert!(limits::read(io::Read::chain(config(APPROVED).as_bytes(), BrokenRead)).is_err());
}
fn id(s: &str) -> OpId {
    OpId::parse(s).unwrap()
}
fn definition(n: usize, priority: Priority) -> Definition {
    Definition {
        id: id(&format!("loop-syn-{n:03}")),
        revision: NonEmpty::new("synthetic-revision").unwrap(),
        wake: Wake::Once { at_ms: 100 },
        enabled: true,
        mode: Mode::Active,
        priority,
        budget: Budget {
            window_ms: NonZeroU64::new(1000).unwrap(),
            max_agent_starts: 1,
        },
    }
}
fn run(d: &Definition, result: RunResult) -> Run {
    Run {
        id: id(&format!("run-{}", d.id.as_str())),
        loop_id: d.id.clone(),
        definition_revision: d.revision.clone(),
        wake: Occurrence::Scheduled { due_at_ms: 100 },
        started_at_ms: 100,
        updated_at_ms: 100,
        priority: d.priority,
        result,
    }
}
