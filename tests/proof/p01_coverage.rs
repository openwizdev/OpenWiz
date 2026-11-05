//! P1 Coverage: every session from `thread list` appears exactly once, and
//! the counts reconcile.

use std::collections::BTreeSet;

use openwiz_core::envelope::{Completeness, Counts, GapKind};
use openwiz_core::limits::FIELD_MAX_CHARS;
use openwiz_core::model::{Fact, Grouping, ProjectId};
use openwiz_core::ops::ListRequest;
use openwiz_core::source::ProjectRecord;

use crate::support::*;

fn reconcile(c: &Counts) {
    assert_eq!(
        c.listed,
        c.unreadable + c.excluded_hidden + c.excluded_archived + c.matched,
        "listed must equal unreadable + excluded + matched: {c:?}"
    );
    let expected_shown = c.limit.min(c.matched.saturating_sub(c.offset));
    assert_eq!(
        c.shown, expected_shown,
        "shown must be min(limit, matched - offset): {c:?}"
    );
}

#[test]
fn every_listed_session_appears_exactly_once() {
    let fake = Fake::new("p01_every_listed_session_appears_exactly_once", "normal");
    let env = fake.list(&ListRequest::default()).expect("normal list");
    let listed = ids(&env);
    let unique: BTreeSet<_> = listed.iter().cloned().collect();
    assert_eq!(
        listed.len(),
        unique.len(),
        "a session appears twice: {listed:?}"
    );
    let expected: BTreeSet<String> = DEFAULT_IDS.iter().map(|s| s.to_string()).collect();
    assert_eq!(unique, expected);
}

#[test]
fn counts_reconcile_for_the_default_list() {
    let fake = Fake::new("p01_counts_reconcile_for_the_default_list", "normal");
    let env = fake.list(&ListRequest::default()).expect("normal list");
    let counts = env.coverage.counts.as_ref().expect("a list has counts");
    assert_eq!(counts.listed, 6);
    assert_eq!(counts.matched, 6);
    assert!(
        !counts.hidden_read && !counts.archived_read,
        "neither was asked for"
    );
    assert_eq!(counts.shown, env.data.sessions.len() as u64);
    reconcile(counts);
}

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
fn a_session_listed_twice_appears_once_with_a_gap() {
    let mut records = ScriptedSource::new(3).records;
    records.push(records[0].clone());
    let source = ScriptedSource::with_records(records);
    let env = list_scripted(&source, &ListRequest::default()).expect("list");
    let listed = ids(&env);
    assert_eq!(
        listed.iter().filter(|id| *id == "thr_syn_0001").count(),
        1,
        "{listed:?}"
    );
    assert_eq!(listed.len(), 3);
    reconcile(env.coverage.counts.as_ref().expect("counts"));
    assert!(
        env.gaps
            .iter()
            .any(|g| g.subject.as_deref() == Some("thr_syn_0001")
                || g.detail.contains("thr_syn_0001")),
        "the duplicate has a gap: {:?}",
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

#[test]
fn conflicting_unknown_session_statuses_stay_unknown_in_either_order() {
    let known = Fact::Known("idle".to_owned());
    let missing = Fact::Unknown("not reported".to_owned());
    let unreadable = Fact::Unknown("unreadable".to_owned());
    for statuses in [vec![known, missing.clone()], vec![missing, unreadable]] {
        for reverse in [false, true] {
            let mut records: Vec<_> = statuses
                .iter()
                .map(|status| {
                    let mut record = scripted_record(1);
                    record.status = status.clone();
                    record
                })
                .collect();
            if reverse {
                records.reverse();
            }
            let source = ScriptedSource::with_records(records);
            for request in [ListRequest::default(), long()] {
                let env = list_scripted(&source, &request).expect("list");
                assert_eq!(env.data.sessions.len(), 1);
                assert_eq!(
                    unknown_reason(&env.data.sessions[0].status),
                    "session list returned conflicting status facts for this session id"
                );
                assert_eq!(env.coverage.state, Completeness::Partial);
                assert_eq!(env.gaps.len(), 2);
                reconcile(env.coverage.counts.as_ref().expect("counts"));
            }
        }
    }
}

#[test]
fn conflicting_project_names_are_unknown_with_partial_coverage_in_either_order() {
    let a = Fact::Known("Synthetic project A".to_owned());
    let b = Fact::Known("Synthetic project B".to_owned());
    let unknown = Fact::Unknown("name not reported".to_owned());
    let prefix = "x".repeat(FIELD_MAX_CHARS);
    for names in [
        vec![a.clone(), b.clone()],
        vec![a.clone(), unknown.clone()],
        vec![unknown, Fact::Unknown("name unreadable".to_owned())],
        vec![a.clone(), b, a],
        vec![
            Fact::Known(format!("{prefix}A")),
            Fact::Known(format!("{prefix}B")),
        ],
    ] {
        let check = |names: Vec<Fact<String>>| {
            let mut projects: Vec<_> = names
                .into_iter()
                .map(|name| ProjectRecord {
                    id: ProjectId("prj_syn_0001".to_owned()),
                    name,
                })
                .collect();
            projects.push(ProjectRecord {
                id: ProjectId("prj_syn_0002".to_owned()),
                name: Fact::Known("Unaffected project".to_owned()),
            });
            let mut source = ScriptedSource::new(3).with_projects(projects);
            source.records[2].project_id = Fact::Known(ProjectId("prj_syn_0002".to_owned()));
            let env = list_scripted(&source, &ListRequest::default()).expect("honest list");
            assert_eq!(ids(&env), ["thr_syn_0001", "thr_syn_0002", "thr_syn_0003"]);
            let counts = env.coverage.counts.as_ref().expect("counts");
            assert_eq!(
                (
                    counts.listed,
                    counts.matched,
                    counts.shown,
                    counts.unreadable
                ),
                (3, 3, 3, 0)
            );
            reconcile(counts);
            assert_eq!(env.coverage.state, Completeness::Partial);
            assert_eq!(env.gaps.len(), 1);
            assert_eq!(env.gaps[0].kind, GapKind::Malformed);
            assert_eq!(env.gaps[0].subject.as_deref(), Some("prj_syn_0001"));
            assert!(env.gaps[0].detail.contains("conflicting"));
            for row in &env.data.sessions[..2] {
                match &row.group {
                    Grouping::Project {
                        id,
                        name: Fact::Unknown(reason),
                    } => {
                        assert_eq!(id.0, "prj_syn_0001");
                        assert!(reason.contains("conflicting"), "{reason}");
                    }
                    other => panic!("conflicting project name must be unknown: {other:?}"),
                }
            }
            assert_eq!(
                env.data.sessions[2].group,
                Grouping::Project {
                    id: ProjectId("prj_syn_0002".to_owned()),
                    name: Fact::Known("Unaffected project".to_owned()),
                }
            );
            env
        };
        let forward = check(names.clone());
        let reverse = check(names.into_iter().rev().collect());
        assert_eq!(
            forward, reverse,
            "project row order must not change inventory"
        );
    }
}

#[test]
fn two_conflicting_project_ids_merge_into_one_gap_in_id_order() {
    let row = |id: &str, name: &str| ProjectRecord {
        id: ProjectId(id.to_owned()),
        name: Fact::Known(name.to_owned()),
    };
    let check = |rows: Vec<ProjectRecord>| {
        let mut source = ScriptedSource::new(2).with_projects(rows);
        source.records[1].project_id = Fact::Known(ProjectId("prj_syn_0002".to_owned()));
        let env = list_scripted(&source, &ListRequest::default()).expect("honest list");
        assert_eq!(ids(&env), ["thr_syn_0001", "thr_syn_0002"]);
        assert_eq!(env.coverage.state, Completeness::Partial);
        assert_eq!(env.gaps.len(), 1);
        assert_eq!(env.gaps[0].kind, GapKind::Malformed);
        assert_eq!(
            env.gaps[0].subject.as_deref(),
            Some("2 subjects: prj_syn_0001, prj_syn_0002")
        );
        env
    };
    let rows = vec![
        row("prj_syn_0001", "Conflicting A"),
        row("prj_syn_0002", "Conflicting B"),
        row("prj_syn_0001", "Conflicting A again"),
        row("prj_syn_0002", "Conflicting B again"),
    ];
    let forward = check(rows.clone());
    let reverse = check(rows.into_iter().rev().collect());
    assert_eq!(
        forward, reverse,
        "project row order must not change the merged gap's subjects"
    );
}

#[test]
fn identical_project_name_facts_keep_their_single_row_behavior() {
    for name in [
        Fact::Known("Synthetic project".to_owned()),
        Fact::Unknown("name not reported".to_owned()),
    ] {
        for count in [1, 3] {
            let project = ProjectRecord {
                id: ProjectId("prj_syn_0001".to_owned()),
                name: name.clone(),
            };
            let source = ScriptedSource::new(1).with_projects(vec![project; count]);
            let env = list_scripted(&source, &ListRequest::default()).expect("list");
            assert_eq!(ids(&env), ["thr_syn_0001"]);
            assert_eq!(env.coverage.state, Completeness::Complete);
            assert!(env.gaps.is_empty());
            assert_eq!(
                env.data.sessions[0].group,
                Grouping::Project {
                    id: ProjectId("prj_syn_0001".to_owned()),
                    name: name.clone(),
                }
            );
            reconcile(env.coverage.counts.as_ref().expect("counts"));
        }
    }
}
