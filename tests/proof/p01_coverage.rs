use openwiz_core::envelope::GapKind;
use openwiz_core::limits::FIELD_MAX_CHARS;
use openwiz_core::ops::ListRequest;

use crate::support::*;

#[test]
fn counts_reconcile_with_hidden_and_archived_included() {
    let fake = Fake::new("p01_counts_reconcile_with_hidden_and_archived", "normal");
    let request = ListRequest {
        include_hidden: true,
        include_archived: true,
        ..ListRequest::default()
    };
    let env = fake.list(&request).expect("list with -a --hidden");
    let counts = env.coverage.counts.as_ref().expect("a list has counts");
    assert_eq!(counts.listed, 8);
    assert_eq!(counts.matched, 8);
    assert!(counts.hidden_read && counts.archived_read);
    assert_eq!(env.data.sessions.len(), 8);
    reconcile(counts);
}

#[test]
fn unreadable_rows_are_counted_not_dropped() {
    let fake = Fake::new(
        "p01_unreadable_rows_are_counted",
        "thread-list-missing-fields",
    );
    let env = fake
        .list(&ListRequest::default())
        .expect("honest partial list");
    let counts = env.coverage.counts.as_ref().expect("a list has counts");
    assert_eq!(counts.listed, 6, "every row the source returned is counted");
    assert_eq!(
        counts.unreadable, 1,
        "the row without an id is counted as unreadable"
    );
    assert_eq!(env.data.sessions.len(), 5);
    reconcile(counts);
    assert!(
        env.gaps
            .iter()
            .any(|g| g.kind == GapKind::MissingField && g.detail.contains("id")),
        "the unreadable row has a gap: {:?}",
        env.gaps
    );
}

#[test]
fn duplicate_session_statuses_are_honest_in_the_fixture_cli() {
    use serde_json::{Value, json};
    use std::fs;

    let normal = std::path::Path::new(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/fixtures/room-cli-0.43.1/normal"
    ));
    let prefix = "x".repeat(FIELD_MAX_CHARS);
    let cases = [
        (vec!["idle".to_owned()], false),
        (vec!["idle".to_owned(); 3], false),
        (vec!["idle".to_owned(), "active".to_owned()], true),
        (
            vec!["idle".to_owned(), "active".to_owned(), "idle".to_owned()],
            true,
        ),
        (vec![format!("{prefix}A"), format!("{prefix}B")], true),
    ];
    for (case, (statuses, conflict)) in cases.into_iter().enumerate() {
        for reverse in [false, true] {
            for args in [&["ls", "--json"][..], &["ls", "-l", "--json"][..]] {
                let fake = Fake::new(
                    &format!("p01_status_{case}_{reverse}_{}", args.len()),
                    "normal",
                );
                let rows: Value = serde_json::from_str(
                    &fs::read_to_string(normal.join("thread-list.json")).expect("fixture"),
                )
                .expect("rows");
                let mut duplicates: Vec<_> = statuses
                    .iter()
                    .map(|status| {
                        let mut row = rows[0].clone();
                        row["status"] = json!(status);
                        row
                    })
                    .collect();
                if reverse {
                    duplicates.reverse();
                }
                duplicates.extend_from_slice(&rows.as_array().expect("rows")[1..]);
                let scenario = fake.dir.join("scenario.json");
                fs::write(
                    &scenario,
                    json!({
                        "extends": normal,
                        "responses": [{"argv": ["thread", "list", "--json"],
                            "stdout": serde_json::to_string(&duplicates).expect("rows")}]
                    })
                    .to_string(),
                )
                .expect("scenario");
                fs::write(
                    fake.dir.join("fake-room-cli.scenario"),
                    scenario.to_str().expect("path"),
                )
                .expect("pointer");
                let env = fake.cli_json(args);
                let sessions = env["data"]["sessions"].as_array().expect("sessions");
                assert_eq!(
                    sessions
                        .iter()
                        .map(|s| s["id"].as_str().expect("id"))
                        .collect::<Vec<_>>(),
                    DEFAULT_IDS
                );
                let counts = &env["coverage"]["counts"];
                assert_eq!(
                    counts,
                    &json!({"listed": 5 + statuses.len(), "unreadable": statuses.len() - 1,
                        "matched": 6, "shown": 6, "excluded_hidden": 0, "excluded_archived": 0,
                        "hidden_read": false, "archived_read": false, "offset": 0, "limit": 100})
                );
                assert_eq!(
                    env["coverage"]["state"],
                    if statuses.len() == 1 {
                        "complete"
                    } else {
                        "partial"
                    }
                );
                let gaps = env["gaps"].as_array().expect("gaps");
                if conflict {
                    let reason = sessions[0]["status"]["unknown"]
                        .as_str()
                        .expect("conflicting status must be unknown");
                    assert_eq!(
                        reason,
                        "session list returned conflicting status facts for this session id"
                    );
                    assert!(gaps.iter().any(|g| g["detail"] == reason));
                } else {
                    assert_eq!(sessions[0]["status"], json!({"known": "idle"}));
                }
                assert_eq!(
                    gaps.len(),
                    usize::from(statuses.len() > 1) + usize::from(conflict)
                );
                for gap in gaps {
                    assert_eq!(gap["kind"], "malformed");
                    assert_eq!(gap["subject"], "thr_syn_0001");
                }
                for (row, original) in sessions[1..]
                    .iter()
                    .zip(&rows.as_array().expect("rows")[1..])
                {
                    assert_eq!(row["status"], json!({"known": original["status"]}));
                }
            }
        }
    }
}
