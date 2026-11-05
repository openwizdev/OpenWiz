//! #535 (0.0.10 T2), CK1: `GET /api/v1/cockpit` returns what
//! `contracts/cockpit.v1.md` says, on the fake `gh`, the scripted inventory
//! and fake CloudRoom reads: complete, partial (one project unreadable),
//! stale and unknown freshness, the three target states, Needs you's
//! unsupported facts and order, running agents and a truncated fleet read.
//! Fixture tests: they prove no live behaviour.

use serde_json::{Value, json};

use crate::c10_cockpit_support::{self as s, P1, P2, Room, Setup, TARGET};
use crate::fake::T0;

const DIAGNOSTIC: &str = "SYNTHETIC_PRIVATE_DIAGNOSTIC";

/// Two running agents (a Cloud one in P1, a local one in P2), an idle
/// session and the idle orchestrator thread.
fn inventory() -> crate::fake::ScriptedSource {
    s::inventory(vec![
        s::session(1, "active", P1, None),
        s::session(2, "active", P2, Some("mch_syn_0001")),
        s::session(3, "idle", P1, None),
        s::session(11, "idle", P1, None),
    ])
}

/// The repository's projects and its threads: `thr_syn_0001`'s branch is
/// PR #952's head, which closes ticket #903 of spec #901.
fn room(projects: &[&str]) -> std::sync::Arc<Room> {
    Room::new(
        projects,
        &[
            ("thr_syn_0001", P1, Some("room/syn-a2-0002")),
            ("thr_syn_0002", P2, None),
            ("thr_syn_0003", P1, Some("room/syn-unrelated")),
            ("thr_syn_0011", P1, Some("main")),
        ],
    )
}

fn ticket_state(fleets: &Value, ticket: u64) -> Value {
    fleets["data"]["tickets"]
        .as_array()
        .unwrap()
        .iter()
        .find(|t| t["number"] == ticket)
        .unwrap()["state"]
        .clone()
}

#[test]
fn c10_complete_two_projects_fresh_with_nothing_waiting() {
    // Every running agent is placed: the local thread's listed branch is
    // PR #953's head, which closes ticket #904 of spec #901.
    let room = room(&[P1, P2]);
    room.local_branch("thr_syn_0002", "room/syn-a3-0003");
    let setup = Setup::new(inventory(), s::gh("c10-complete", s::no_needs), room)
        .target(s::messenger("c10-complete-target", vec![]), Some(TARGET));
    let server = setup.serve();
    let body = s::read(&server);

    assert_eq!(body["schema"], "openwiz.cockpit.v1");
    assert_eq!(body["snapshot_at"], T0.0);
    for part in ["projects", "needs_you", "agents"] {
        assert_eq!(body[part]["coverage"], s::complete(), "{part}: {body:#}");
        assert_eq!(body[part]["freshness"], s::fresh(T0.0), "{part}");
    }
    assert_eq!(s::ids(&body), [P1, P2]);
    assert_eq!(
        s::project(&body, P1)["name"],
        json!({"known": "Synthetic project 1"})
    );
    assert_eq!(
        s::project(&body, P2)["name"],
        json!({"known": "Synthetic project 2"})
    );
    // The orchestrator thread is in P1, so the target is P1's alone.
    let p1 = &s::project(&body, P1)["orchestrator"];
    assert_eq!(p1["target"], json!({"known": TARGET}));
    assert_eq!(p1["coverage"], s::complete());
    assert_eq!(p1["freshness"], s::fresh(T0.0));
    let p2 = &s::project(&body, P2)["orchestrator"];
    assert!(s::unknown(&p2["target"]), "{p2:#}");
    assert_eq!(p2["coverage"]["state"], "partial");
    assert_eq!(p2["freshness"]["state"], "unknown");

    // Nothing waits: the one case the page may say "nothing needs you".
    assert_eq!(body["needs_you"]["items"], json!([]));

    assert_eq!(s::threads(&body), ["thr_syn_0001", "thr_syn_0002"]);
    let fleets = server.get("/api/v1/fleets").json();
    let placed = s::agent(&body, "thr_syn_0001");
    assert_eq!(
        placed,
        &json!({
            "thread": "thr_syn_0001",
            "project": {"known": P1},
            "title": {"known": "Synthetic session 1"},
            "fleet": {"known": 901},
            "ticket": {"known": 903},
            "activity": "active",
            "model": {"known": "synthetic-model-a"},
            "state": ticket_state(&fleets, 903),
            "location": {"known": {"kind": "cloud"}},
            "started_at": {"known": T0.0 - 3_600_000 - 1},
        })
    );
    assert!(placed["state"]["known"].is_string(), "{fleets:#}");
    let local = s::agent(&body, "thr_syn_0002");
    assert_eq!(
        local["location"],
        json!({"known": {"kind": "local", "machine": {"known": "Synthetic machine one"}}})
    );
    assert_eq!(local["fleet"], json!({"known": 901}));
    assert_eq!(local["ticket"], json!({"known": 904}));
    assert_eq!(local["state"], ticket_state(&fleets, 904));
    assert!(local["state"]["known"].is_string(), "{fleets:#}");
    assert_eq!(
        setup.room.asked.lock().unwrap().as_slice(),
        [Some(s::NAME_WITH_OWNER.to_owned())]
    );
}

#[test]
fn c10_partial_one_project_unreadable_keeps_every_usable_row() {
    let setup = Setup::new(
        inventory(),
        s::gh("c10-partial", s::issue_list_fails),
        room(&[P1]),
    )
    .target(s::messenger("c10-partial-target", vec![]), Some(TARGET));
    let server = setup.serve();
    let body = s::read(&server);
    assert!(!body.to_string().contains(DIAGNOSTIC), "{body:#}");

    // Both projects stay; the one without a fleet source is a gap.
    assert_eq!(s::ids(&body), [P1, P2]);
    assert_eq!(body["projects"]["coverage"]["state"], "partial");
    assert!(s::has_gap(
        &body["projects"],
        Some(P2),
        "unsupported",
        "fleet source"
    ));
    // P1's fleet source is unreadable: never a confident empty list.
    let needs = &body["needs_you"];
    assert_eq!(needs["coverage"]["state"], "partial");
    // gh's issue list is the fleet view's spec list read.
    assert!(
        s::has_gap(needs, Some(P1), "command_failed", "spec list"),
        "{needs:#}"
    );
    assert_eq!(needs["items"], json!([]));
    // Agents from both projects survive; P1's placement is unread.
    assert_eq!(body["agents"]["coverage"]["state"], "partial");
    assert_eq!(s::threads(&body), ["thr_syn_0001", "thr_syn_0002"]);
    let p2 = s::agent(&body, "thr_syn_0002");
    assert_eq!(p2["model"], json!({"known": "synthetic-model-a"}));
    assert_eq!(p2["title"], json!({"known": "Synthetic session 2"}));
    let p1 = s::agent(&body, "thr_syn_0001");
    for fact in ["fleet", "ticket", "state"] {
        assert!(s::unknown(&p1[fact]), "{fact}: {p1:#}");
    }
    // The target is checked independently of GitHub.
    assert_eq!(
        s::project(&body, P1)["orchestrator"]["target"],
        json!({"known": TARGET})
    );
    assert!(s::unknown(&s::project(&body, P2)["orchestrator"]["target"]));
}

#[test]
fn c10_stale_snapshots_stay_stale_after_a_new_assembly() {
    let clock = s::StepClock::at(T0);
    let room = room(&[P1, P2]);
    let moving = clock.clone();
    // The fleet reads finish 80 s of wall time after every source snapshot.
    *room.during.lock().unwrap() = Some(Box::new(move || {
        s::wait(300);
        moving.advance(80_000);
    }));
    let mut setup = Setup::new(inventory(), s::gh("c10-stale", s::no_needs), room)
        .target(s::messenger("c10-stale-target", vec![]), Some(TARGET));
    setup.clock = clock;
    let body = s::read(&setup.serve());

    let assembled = T0.0 + 80_000;
    assert!(assembled - T0.0 > s::STALE_AFTER_MS);
    assert_eq!(body["snapshot_at"], assembled);
    for part in ["projects", "needs_you", "agents"] {
        assert_eq!(body[part]["freshness"], s::stale(T0.0), "{part}: {body:#}");
    }
    // Coverage and freshness are independent.
    assert_eq!(body["needs_you"]["coverage"], s::complete());
    assert_eq!(body["needs_you"]["items"], json!([]));
    // The target was checked after the clock moved: its own time.
    let target = &s::project(&body, P1)["orchestrator"];
    assert_eq!(target["freshness"], s::fresh(assembled));
}

#[test]
fn c10_unknown_freshness_when_project_discovery_has_no_snapshot() {
    let setup = Setup::new(
        s::NoProjects(inventory()),
        s::gh("c10-unknown", s::no_needs),
        room(&[P1, P2]),
    );
    let body = s::read(&setup.serve());
    assert!(!body.to_string().contains(DIAGNOSTIC), "{body:#}");
    let projects = &body["projects"];
    assert_eq!(projects["freshness"]["state"], "unknown");
    assert!(s::unknown(&projects["freshness"]["snapshot_at"]));
    assert!(s::has_gap(projects, None, "command_failed", "project list"));
    // Discovery is part of every part's coverage and freshness.
    for part in ["needs_you", "agents"] {
        assert_eq!(body[part]["coverage"]["state"], "partial", "{part}");
        assert_eq!(body[part]["freshness"]["state"], "unknown", "{part}");
    }
    // The fleet source's projects are still discovered; ungrouped agents stay.
    assert_eq!(s::ids(&body), [P1, P2]);
    assert_eq!(s::threads(&body).len(), 2);
    for thread in ["thr_syn_0001", "thr_syn_0002"] {
        assert!(s::unknown(&s::agent(&body, thread)["project"]));
    }
}

#[test]
fn c10_target_checked_known_absent_and_unknown_stay_distinct() {
    let read = |name: &str, setup: Setup| {
        let body = s::read(&setup.serve());
        assert!(!body.to_string().contains(DIAGNOSTIC), "{name}: {body:#}");
        s::project(&body, P1)["orchestrator"].clone()
    };
    let make = |name: &str| Setup::new(inventory(), s::gh(name, s::no_needs), room(&[P1]));

    let checked = read(
        "checked",
        make("c10-target-checked").target(s::messenger("c10-t-checked", vec![]), Some(TARGET)),
    );
    assert_eq!(checked["target"], json!({"known": TARGET}));
    assert_eq!(checked["coverage"], s::complete());

    // Unset: the configuration was read and names no target.
    let unset = read(
        "unset",
        make("c10-target-unset").target(s::messenger("c10-t-unset", vec![]), None),
    );
    assert_eq!(unset["target"], json!({"known": null}));
    assert_eq!(unset["coverage"], s::complete());
    assert_eq!(unset["freshness"], s::fresh(T0.0));

    // Not found, after a good read: known absence too.
    let missing = read(
        "not found",
        make("c10-target-missing").target(
            s::messenger("c10-t-missing", vec![s::target_not_found()]),
            Some(TARGET),
        ),
    );
    assert_eq!(missing["target"], json!({"known": null}));
    assert_eq!(missing["coverage"], s::complete());

    // A failed check is unknown, never absence.
    let failed = read(
        "failed",
        make("c10-target-failed").target(
            s::messenger("c10-t-failed", vec![s::target_fails()]),
            Some(TARGET),
        ),
    );
    assert!(s::unknown(&failed["target"]), "{failed:#}");
    assert_eq!(failed["coverage"]["state"], "partial");
    assert!(s::has_gap(&failed, Some(P1), "command_failed", "target"));
    assert_eq!(failed["freshness"]["state"], "unknown");

    // A configured target without a reader to check it: unknown.
    let mut unchecked = make("c10-target-unchecked");
    unchecked.target = Some(Ok(Some(TARGET.to_owned())));
    let unchecked = read("unchecked", unchecked);
    assert!(s::unknown(&unchecked["target"]), "{unchecked:#}");
    assert_eq!(unchecked["coverage"]["state"], "partial");

    // An unreadable configuration: unknown.
    let mut unreadable = make("c10-target-unreadable");
    unreadable.target = Some(Err(()));
    let unreadable = read("unreadable", unreadable);
    assert!(s::unknown(&unreadable["target"]));
    assert_eq!(unreadable["coverage"]["state"], "partial");
}

#[test]
fn c10_needs_you_keeps_unsupported_facts_unknown_in_order() {
    let gh = s::gh("c10-needs", |_, issues, _| {
        s::add_label(issues, 907, "live");
        s::add_label(issues, 905, "held");
        s::add_label(issues, 905, "needs-info");
    });
    let setup = Setup::new(inventory(), gh, room(&[P1]));
    let body = s::read(&setup.serve());
    let needs = &body["needs_you"];
    let keys: Vec<(Value, Value, Value, Value)> = needs["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| {
            (
                i["project"].clone(),
                i["spec"].clone(),
                i["ticket"].clone(),
                i["kind"].clone(),
            )
        })
        .collect();
    let p1 = json!({"known": P1});
    assert_eq!(
        keys,
        [
            (p1.clone(), json!(901), json!(904), json!("needs_info")),
            (p1.clone(), json!(901), json!(905), json!("held")),
            (p1.clone(), json!(901), json!(905), json!("needs_info")),
            (p1.clone(), json!(901), json!(907), json!("held")),
        ],
        "{needs:#}"
    );
    for item in needs["items"].as_array().unwrap() {
        // The fleets view reads no question comment: never a title, never a
        // made-up age.
        assert!(s::unknown(&item["wording"]), "{item:#}");
        assert!(s::unknown(&item["age_ms"]), "{item:#}");
        if item["ticket"] == 907 {
            // The `live` label is an explicit risk classification.
            assert_eq!(item["risky"], json!({"known": true}));
        } else {
            // No label is never a known `false`.
            assert!(s::unknown(&item["risky"]), "{item:#}");
        }
    }
    assert_eq!(needs["coverage"]["state"], "partial");
    for field in ["wording", "age", "risk"] {
        assert!(
            s::has_gap(needs, Some(P1), "unsupported", field),
            "{field}: {needs:#}"
        );
    }
}

#[test]
fn c10_ambiguous_repository_lists_each_item_once_unassigned() {
    let setup = Setup::new(
        inventory(),
        s::gh("c10-ambiguous", |_, _, _| {}),
        room(&[P1, P2]),
    );
    let body = s::read(&setup.serve());
    let items = body["needs_you"]["items"].as_array().unwrap();
    let tickets: Vec<&Value> = items.iter().map(|i| &i["ticket"]).collect();
    assert_eq!(tickets, [&json!(904), &json!(907)], "{body:#}");
    for item in items {
        assert!(s::unknown(&item["project"]), "{item:#}");
    }
    assert!(s::has_gap(
        &body["needs_you"],
        None,
        "unsupported",
        "several projects"
    ));
}

#[test]
fn c10_agents_are_only_active_sessions_and_unplaced_ones_stay() {
    let mut unknown = s::session(5, "active", P1, None);
    unknown.status = openwiz_core::model::Fact::Unknown("not reported".to_owned());
    let mut titled = s::session(4, "active", P1, None);
    // A title never places an agent.
    titled.title = openwiz_core::model::Fact::Known("Synthetic builder for #903".to_owned());
    let source = s::inventory(vec![
        s::session(1, "active", P1, None),
        titled,
        unknown,
        s::session(6, "error", P1, None),
        s::session(7, "idle", P1, None),
    ])
    .with_failing_detail(
        "thr_syn_0004",
        openwiz_core::source::SourceError::CommandFailed {
            exit_code: Some(1),
            detail: DIAGNOSTIC.to_owned(),
        },
    );
    let room = Room::new(
        &[P1],
        &[
            ("thr_syn_0001", P1, Some("room/syn-a2-0002")),
            ("thr_syn_0004", P1, Some("room/syn-unrelated")),
            ("thr_syn_0005", P1, Some("room/syn-other")),
            ("thr_syn_0006", P1, Some("room/syn-error")),
            ("thr_syn_0007", P1, Some("room/syn-idle")),
        ],
    );
    let setup = Setup::new(source, s::gh("c10-agents", s::no_needs), room);
    let body = s::read(&setup.serve());
    let agents = &body["agents"];
    assert_eq!(
        s::threads(&body),
        ["thr_syn_0001", "thr_syn_0004"],
        "{agents:#}"
    );
    assert_eq!(
        s::agent(&body, "thr_syn_0001")["ticket"],
        json!({"known": 903})
    );
    let unplaced = s::agent(&body, "thr_syn_0004");
    for fact in ["fleet", "ticket", "state"] {
        assert!(s::unknown(&unplaced[fact]), "{fact}: {unplaced:#}");
    }
    // An unknown status: never claim no other agent runs.
    assert_eq!(agents["coverage"]["state"], "partial");
    assert!(
        s::has_gap(agents, Some(P1), "missing_field", "status"),
        "{agents:#}"
    );
    // A failed detail read: the model is unknown, the row stays.
    assert!(s::unknown(&unplaced["model"]), "{unplaced:#}");
    assert!(s::has_gap(agents, Some(P1), "command_failed", "detail"));
    assert_eq!(
        s::agent(&body, "thr_syn_0001")["model"],
        json!({"known": "synthetic-model-a"})
    );
    assert!(!body.to_string().contains(DIAGNOSTIC), "{body:#}");
}

#[test]
fn c10_truncated_fleet_read_keeps_its_gap() {
    let truncated: Vec<Value> = serde_json::from_str(
        &std::fs::read_to_string(
            std::path::Path::new(crate::support::FIXTURES).join("fleets/truncated/issues.json"),
        )
        .unwrap(),
    )
    .unwrap();
    let gh = s::gh("c10-truncated", move |_, issues, _| *issues = truncated);
    let setup = Setup::new(inventory(), gh, room(&[P1]));
    let body = s::read(&setup.serve());
    for part in ["needs_you", "agents"] {
        assert_eq!(body[part]["coverage"]["state"], "partial", "{part}");
        assert!(
            s::has_gap(&body[part], Some(P1), "truncated", ""),
            "{part}: {body:#}"
        );
    }
}

#[test]
fn c10_without_fleet_sources_nothing_is_claimed_complete() {
    let mut setup = Setup::new(
        inventory(),
        s::gh("c10-no-fleets", s::no_needs),
        room(&[P1]),
    );
    setup.fleets = false;
    let body = s::read(&setup.serve());
    assert_eq!(s::ids(&body), [P1, P2]);
    for project in [P1, P2] {
        assert!(s::has_gap(
            &body["projects"],
            Some(project),
            "unsupported",
            "fleet source"
        ));
        assert!(s::unknown(
            &s::project(&body, project)["orchestrator"]["target"]
        ));
    }
    assert_eq!(body["needs_you"]["coverage"]["state"], "partial");
    assert_eq!(body["needs_you"]["freshness"]["state"], "unknown");
    assert_eq!(body["needs_you"]["items"], json!([]));
    assert_eq!(s::threads(&body), ["thr_syn_0001", "thr_syn_0002"]);
}
