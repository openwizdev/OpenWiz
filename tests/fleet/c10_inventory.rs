use std::fs;
use std::path::Path;
use std::time::Instant;

use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_core::model::{SessionId, Timestamp};
use openwiz_core::ops::{self, Clock, ListRequest, ShowRequest};
use serde_json::Value;

use crate::support::fakes_on_path;

struct FixedClock;

impl Clock for FixedClock {
    fn now(&self) -> Timestamp {
        Timestamp(1_700_000_600_000)
    }

    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}

#[test]
fn c10_unreported_start_stays_unknown_in_list_and_show_despite_creation_and_update_times() {
    let (dir, _) = fakes_on_path("c10-unreported-start");
    let scenario =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/room-cli-0.43.1/normal/scenario.json");
    fs::write(
        dir.join("fake-room-cli.scenario"),
        scenario.to_str().unwrap(),
    )
    .unwrap();
    let source = CloudRoomSource::new(dir.join("room-cli"));

    let listed = ops::list(&source, &FixedClock, &ListRequest::default()).unwrap();
    let shown = ops::show(
        &source,
        &FixedClock,
        &ShowRequest {
            id: SessionId("thr_syn_0001".into()),
            budget: openwiz_core::limits::RUN_BUDGET,
        },
    )
    .unwrap();
    let listed = serde_json::to_value(listed).unwrap();
    let shown = serde_json::to_value(shown).unwrap();
    let session = listed["data"]["sessions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["id"] == "thr_syn_0001")
        .unwrap();
    assert_eq!(session["updated_at"]["known"], 1_700_000_540_000_i64);
    assert_eq!(
        shown["data"]["session"]["updated_at"],
        session["updated_at"]
    );

    for row in [session, &shown["data"]["session"]] {
        assert!(
            row["started_at"]["unknown"]
                .as_str()
                .is_some_and(|reason| !reason.trim().is_empty()),
            "no reported start must be an explicit unknown: {:?}",
            row.get("started_at")
        );
    }

    let schema: Value = serde_json::from_str(
        &fs::read_to_string(
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../contracts/inventory.v1.schema.json"),
        )
        .unwrap(),
    )
    .unwrap();
    for envelope in [&listed, &shown] {
        assert_eq!(
            crate::schema::validate(&schema, envelope),
            Vec::<String>::new()
        );
    }
}

#[test]
fn c10_explicit_start_time_is_preserved_and_unusable_start_times_stay_unknown() {
    use serde_json::json;
    let normal = Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/room-cli-0.43.1/normal");
    let list: Value =
        serde_json::from_str(&fs::read_to_string(normal.join("thread-list.json")).unwrap())
            .unwrap();
    let show: Value =
        serde_json::from_str(&fs::read_to_string(normal.join("thread-show-0001.json")).unwrap())
            .unwrap();
    let cases = [
        (
            Some(json!(1_700_000_000_000_i64)),
            Some(1_700_000_000_000_i64),
        ),
        (Some(json!(0)), Some(0)),
        (None, None),
        (Some(Value::Null), None),
        (Some(json!("1700000000000")), None),
        (Some(json!(1.5)), None),
        (Some(json!(false)), None),
        (Some(json!(-1)), None),
        (Some(json!(1_700_000_600_001_i64)), None),
        (Some(json!({"known": 1700000000000_i64})), None),
    ];
    for (index, (reported, expected)) in cases.into_iter().enumerate() {
        let (dir, _) = fakes_on_path(&format!("c10-explicit-start-{index}"));
        let mut rows = list.clone();
        let mut detail = show.clone();
        match reported {
            Some(value) => {
                rows[0]["startedAt"] = value.clone();
                detail["thread"]["startedAt"] = value;
            }
            None => {
                rows[0].as_object_mut().unwrap().remove("startedAt");
                detail["thread"]
                    .as_object_mut()
                    .unwrap()
                    .remove("startedAt");
            }
        }
        let scenario = json!({"scenario": "c10-explicit-start", "extends": normal,
            "synthetic_assumptions": ["Every value is synthetic. startedAt is an unobserved hypothetical explicit running-start timestamp in Unix milliseconds; no live support is claimed."],
            "responses": [
                {"argv": ["thread", "list", "--json"], "stdout": rows.to_string()},
                {"argv": ["thread", "show", "thr_syn_0001", "--json"], "stdout": detail.to_string()}
            ]
        });
        let path = dir.join("scenario.json");
        fs::write(&path, scenario.to_string()).unwrap();
        fs::write(dir.join("fake-room-cli.scenario"), path.to_str().unwrap()).unwrap();
        let source = CloudRoomSource::new(dir.join("room-cli"));
        let listed =
            serde_json::to_value(ops::list(&source, &FixedClock, &ListRequest::default()).unwrap())
                .unwrap();
        let shown = serde_json::to_value(
            ops::show(
                &source,
                &FixedClock,
                &ShowRequest {
                    id: SessionId("thr_syn_0001".into()),
                    budget: openwiz_core::limits::RUN_BUDGET,
                },
            )
            .unwrap(),
        )
        .unwrap();
        let row = listed["data"]["sessions"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["id"] == "thr_syn_0001")
            .unwrap();
        for row in [row, &shown["data"]["session"]] {
            match expected {
                Some(time) => assert_eq!(row["started_at"], json!({"known": time}), "case {index}"),
                None => assert!(
                    row["started_at"]["unknown"]
                        .as_str()
                        .is_some_and(|s| !s.is_empty()),
                    "case {index}: unusable start is explicitly unknown"
                ),
            }
            assert_eq!(row["updated_at"]["known"], 1_700_000_540_000_i64);
        }
    }
}

#[test]
fn c10_long_inventory_keeps_a_start_only_its_detail_read_reports() {
    use openwiz_core::ops::Detail;
    use serde_json::json;
    let normal = Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/room-cli-0.43.1/normal");
    let mut rows: Value =
        serde_json::from_str(&fs::read_to_string(normal.join("thread-list.json")).unwrap())
            .unwrap();
    let mut detail: Value =
        serde_json::from_str(&fs::read_to_string(normal.join("thread-show-0001.json")).unwrap())
            .unwrap();
    rows[0].as_object_mut().unwrap().remove("startedAt");
    detail["thread"]["startedAt"] = json!(1_700_000_000_000_i64);
    let (dir, _) = fakes_on_path("c10-detail-only-start");
    let scenario = json!({"scenario": "c10-detail-only-start", "extends": normal,
        "synthetic_assumptions": ["Every value is synthetic. startedAt is an unobserved hypothetical explicit running-start timestamp in Unix milliseconds, reported here by thread show only; no live support is claimed."],
        "responses": [
            {"argv": ["thread", "list", "--json"], "stdout": rows.to_string()},
            {"argv": ["thread", "show", "thr_syn_0001", "--json"], "stdout": detail.to_string()}
        ]
    });
    let path = dir.join("scenario.json");
    fs::write(&path, scenario.to_string()).unwrap();
    fs::write(dir.join("fake-room-cli.scenario"), path.to_str().unwrap()).unwrap();
    let source = CloudRoomSource::new(dir.join("room-cli"));
    let row = |detail: Detail| {
        let listed = serde_json::to_value(
            ops::list(
                &source,
                &FixedClock,
                &ListRequest {
                    detail,
                    ..ListRequest::default()
                },
            )
            .unwrap(),
        )
        .unwrap();
        listed["data"]["sessions"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["id"] == "thr_syn_0001")
            .unwrap()["started_at"]
            .clone()
    };
    let shown = serde_json::to_value(
        ops::show(
            &source,
            &FixedClock,
            &ShowRequest {
                id: SessionId("thr_syn_0001".into()),
                budget: openwiz_core::limits::RUN_BUDGET,
            },
        )
        .unwrap(),
    )
    .unwrap();
    let known = json!({"known": 1_700_000_000_000_i64});
    assert_eq!(shown["data"]["session"]["started_at"], known, "show");
    assert_eq!(row(Detail::Long), known, "long inventory reads the detail");
    assert!(
        row(Detail::Short)["unknown"]
            .as_str()
            .is_some_and(|why| !why.is_empty()),
        "short inventory reads no detail, so its start stays unknown"
    );
}
