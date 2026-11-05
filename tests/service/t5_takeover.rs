//! TK1 recording endpoint: pause only the exact recorded fleet loop.
//! synthetic_assumptions: pause uses the approved exact-ID argv shape; its
//! response is ignored. Only a fresh full inventory confirms the paused state.
use super::*;
use serde_json::{Value, json};

const RECORD: &str = "launch-fleet: fleet thread thr_syn_dead, loop loop_syn_1";
fn prepare(f: &Fixture) {
    fs::write(
        f.0.join("loops.json"),
        json!([
            {"id":"loop_syn_1","name":"launch-fleet #900 synthetic-owner/synthetic-repo","paused":false},
            {"id":"loop_syn_other","name":"launch-fleet #901 synthetic-owner/synthetic-repo","paused":false},
            {"id":"loop_other","name":"launch-fleet other-owner/other-repo","paused":false}
        ])
        .to_string(),
    )
    .unwrap();
}
fn pause(f: &Fixture, record: &str) -> Result<Id, openwiz_core::source::SourceError> {
    f.source().pause_fleet_loop(
        record,
        &Id::parse("thr_syn_dead").unwrap(),
        &repo(),
        deadline(),
    )
}
// TA2 takeover SourceError capture BEGIN
/// Called only by a failing assertion, alongside the fixture's bounded snapshot.
fn pause_result_failure_context(result: &Result<Id, openwiz_core::source::SourceError>) -> String {
    use std::fmt::{self, Write};
    struct Capped {
        text: String,
        truncated: bool,
    }
    impl Write for Capped {
        fn write_str(&mut self, value: &str) -> fmt::Result {
            let mut end = value.len().min(4096_usize.saturating_sub(self.text.len()));
            while !value.is_char_boundary(end) {
                end -= 1;
            }
            self.text.push_str(&value[..end]);
            if end != value.len() {
                self.truncated = true;
                return Err(fmt::Error);
            }
            Ok(())
        }
    }
    let mut out = Capped {
        text: String::new(),
        truncated: false,
    };
    let _ = write!(&mut out, "{result:?}");
    format!(
        "\n[TA2 service-ci-diagnostics takeover-source-result] truncated={} {}",
        out.truncated, out.text
    )
}
// TA2 takeover SourceError capture END
#[test]
fn exact_recorded_loop_is_paused_and_read_back_before_takeover_can_proceed() {
    for lost_reply in [false, true] {
        let f = Fixture::new();
        prepare(&f);
        if lost_reply {
            fs::write(f.0.join("lost-pause"), "").unwrap();
        }
        assert_eq!(pause(&f, RECORD).unwrap().as_str(), "loop_syn_1");
        assert_eq!(
            f.calls(),
            json!([
                ["loop", "list", "--json"],
                ["loop", "pause", "loop_syn_1", "--json"],
                ["loop", "list", "--json"]
            ])
            .as_array()
            .unwrap()
            .clone()
        );
        let rows: Value =
            serde_json::from_slice(&fs::read(f.0.join("loops.json")).unwrap()).unwrap();
        assert_eq!(rows[0]["paused"], true);
        assert_eq!(rows[1]["paused"], false, "another owned loop is untouched");
        assert_eq!(rows[2]["paused"], false, "another project is untouched");
        // Re-entry only reads the already paused exact ID; no second effect.
        pause(&f, RECORD).unwrap();
        assert_eq!(f.calls().len(), 4);
        assert_eq!(f.calls()[3], json!(["loop", "list", "--json"]));
    }
}
#[test]
fn missing_foreign_or_unconfirmed_pause_refuses_takeover() {
    for (record, mode) in [
        (
            "launch-fleet: fleet thread thr_syn_dead, loop loop_missing",
            None,
        ),
        (
            "launch-fleet: fleet thread thr_syn_dead, loop loop_other",
            None,
        ),
        (RECORD, Some("deny-pause")),
        (RECORD, Some("foreign-pause")),
        (RECORD, Some("missing-pause")),
        (RECORD, Some("malformed-pause")),
    ] {
        let f = Fixture::new();
        prepare(&f);
        if let Some(mode) = mode {
            fs::write(f.0.join(mode), "").unwrap();
        }
        assert!(pause(&f, record).is_err());
        let expected = if mode.is_some() {
            json!([
                ["loop", "list", "--json"],
                ["loop", "pause", "loop_syn_1", "--json"],
                ["loop", "list", "--json"]
            ])
        } else {
            json!([["loop", "list", "--json"]])
        };
        assert_eq!(f.calls(), *expected.as_array().unwrap());
    }
}
#[test]
fn absent_ambiguous_or_nonliteral_record_never_dispatches_a_pause() {
    for record in [
        "launch-fleet: fleet thread thr_syn_dead",
        "launch-fleet: fleet thread thr_syn_other, loop loop_syn_1",
        "launch-fleet: fleet thread thr_syn_dead, loop loop_*",
        "launch-fleet: fleet thread thr_syn_dead, loop -all",
        "launch-fleet: fleet thread thr_syn_dead, loop loop_syn_1, loop loop_syn_other",
        "launch-fleet: fleet thread thr_syn_dead, loop loop_syn_1\nother text",
    ] {
        let f = Fixture::new();
        prepare(&f);
        assert!(pause(&f, record).is_err());
        assert!(f.calls().is_empty());
    }
    for inventory in [
        r#"[{"id":"loop_syn_1","name":"launch-fleet synthetic-owner/synthetic-repo","paused":false},{"id":"loop_syn_1","name":"launch-fleet synthetic-owner/synthetic-repo","paused":false}]"#,
        r#"[{"id":"loop_syn_1","name":"launch-fleet synthetic-owner/synthetic-repo","paused":false,"paused":true}]"#,
        r#"[{"id":"loop_syn_1","name":"launch-fleet synthetic-owner/synthetic-repo","paused":"false"}]"#,
    ] {
        let f = Fixture::new();
        fs::write(f.0.join("loops.json"), inventory).unwrap();
        // TA2 takeover result context BEGIN
        let pause_result = pause(&f, RECORD);
        assert!(
            pause_result.is_err(),
            "{}",
            pause_result_failure_context(&pause_result)
        );
        assert_eq!(
            f.calls(),
            vec![json!(["loop", "list", "--json"])],
            "{}",
            pause_result_failure_context(&pause_result)
        );
        // TA2 takeover result context END
    }
}

#[test]
fn retired_loop_is_never_resumed_even_with_an_existing_incident() {
    use openwiz_core::{
        health::{self, model::*},
        messaging::OpId,
        model::Timestamp,
    };
    let seen = Seen {
        cloudroom: CloudRoomSeen::Running,
        loops: Listed::Read(vec![
            SeenLoop {
                id: Id::parse("loop_syn_1").unwrap(),
                name: "launch-fleet synthetic-owner/synthetic-repo".into(),
                paused: true,
            },
            SeenLoop {
                id: Id::parse("loop_syn_other").unwrap(),
                name: "launch-fleet synthetic-owner/synthetic-repo".into(),
                paused: true,
            },
        ]),
        tick_running_since: None,
        fleet_threads: Listed::Read(vec![]),
        server: Known::Healthy,
    };
    let rules = Rules {
        repository: repo(),
        tick_every_s: std::num::NonZeroU64::new(2).unwrap(),
    };
    let mut op = || OpId::parse(&"a".repeat(64)).unwrap();
    let mut before = health::plan(
        &Incidents::default(),
        &seen,
        &rules,
        Timestamp(1000),
        &mut op,
    )
    .incidents;
    for incident in &mut before.incidents {
        if let Fault::Loop { tries, .. } = &mut incident.fault {
            *tries = Tries::One(SavedTry {
                at: Timestamp(1000),
                outcome: Some(Outcome::Interrupted),
                comment: None,
            });
        }
    }
    let plan = health::plan_with_retired(
        &before,
        &seen,
        &rules,
        Timestamp(2000),
        &mut op,
        &[Id::parse("loop_syn_1").unwrap()],
    );
    assert_eq!(plan.pass.fixes.len(), 1);
    assert!(
        matches!(&plan.pass.fixes[0], Fix::ResumeLoop { subject, .. } if subject.id.as_str()=="loop_syn_other")
    );
    assert_eq!(
        plan.incidents.incidents.len(),
        1,
        "retired loop's old fault is gone"
    );
}

#[test]
fn retirement_state_and_service_tick_outcome_have_strict_additive_shapes() {
    use openwiz_service::document::{self, Document};
    let f = Fixture::new();
    let state = super::restart::state(&f);
    let old = state.lock().unwrap().snapshot().clone();
    let row = json!({"owner":"service_tick","spec":900,"thread":"thr_syn_dead","loop":"loop_syn_1","phase":"active","at":4000});
    let mut value = old.clone();
    value["retired_loops"] = json!([row]);
    value["next_incident"] = json!(2);
    value["incidents"] = json!([{
        "id":"i1","check":"fleet_thread","spec":900,"thread":"thr_syn_dead","broken":{"state":"broken","what":"archived"},
        "opened_at":4000,"healthy_since":null,"tries":{"first":{"at":4000,"outcome":{"state":"done","owner":"service_tick","retired_loop":"loop_syn_1"},"comment":null},"second":null},"needs_you":null
    }]);
    document::read(Document::State, &old.to_string()).unwrap();
    document::read(Document::State, &value.to_string()).unwrap();
    for (field, bad) in [
        ("owner", json!("other")),
        ("phase", json!("running")),
        ("spec", json!(0)),
        ("loop", json!("loop_*")),
        ("at", json!(1.5)),
        ("extra", json!(true)),
    ] {
        let mut bad_value = value.clone();
        bad_value["retired_loops"][0][field] = bad;
        assert!(
            document::read(Document::State, &bad_value.to_string()).is_err(),
            "{field}"
        );
    }
    let mut duplicate = value.clone();
    duplicate["retired_loops"].as_array_mut().unwrap().push(row);
    assert!(document::read(Document::State, &duplicate.to_string()).is_err());
    let mut mismatch = value.clone();
    mismatch["retired_loops"][0]["loop"] = json!("loop_syn_other");
    assert!(document::read(Document::State, &mismatch.to_string()).is_err());
    let mut mixed = value.clone();
    mixed["incidents"][0]["tries"]["first"]["outcome"]["thread"] =
        json!(concat!("thr_", "invented"));
    assert!(document::read(Document::State, &mixed.to_string()).is_err());
    let duplicate_key = value.to_string().replace(
        "\"owner\":\"service_tick\"",
        "\"owner\":\"service_tick\",\"owner\":\"service_tick\"",
    );
    assert!(document::read(Document::State, &duplicate_key).is_err());
}
