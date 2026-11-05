//! #535 self-review round 1 (Codex Sol helper), each finding's proof, red
//! first: an unrecognized status, a usable fleet beside a truncated one, a
//! target grouped in another project, a contradictory placement, an
//! unverified project or machine, conflicting project names, a project
//! without a fleet-source snapshot, and the run's one source budget.
//! Fixture tests: they prove no live behaviour.

use std::sync::Arc;
use std::time::{Duration, Instant};

use openwiz_core::model::{Fact, ProjectId};
use openwiz_core::source::{
    MachineRecord, OutputRecord, ProjectRecord, Rows, SessionDetailRecord, SessionRecord,
    SessionScope, SessionSource, SourceError,
};
use serde_json::json;

use crate::c10_cockpit_support::{self as s, P1, P2, Room, Setup, TARGET};
use crate::fake::ScriptedSource;

fn room(projects: &[&str]) -> Arc<Room> {
    Room::new(
        projects,
        &[
            ("thr_syn_0001", P1, Some("room/syn-a2-0002")),
            ("thr_syn_0011", P1, Some("main")),
        ],
    )
}

/// R1: a status that is neither running nor a known idle/error state
/// proves nothing about running agents.
#[test]
fn c10_r1_an_unrecognized_status_is_partial_never_absent() {
    let setup = Setup::new(
        s::inventory(vec![s::session(1, "synthetic_new_status", P1, None)]),
        s::gh("c10-r1", s::no_needs),
        room(&[P1, P2]),
    );
    let body = s::read(&setup.serve());
    let agents = &body["agents"];
    assert_eq!(agents["items"], json!([]));
    assert!(
        s::has_gap(agents, Some(P1), "unsupported", "status"),
        "{agents:#}"
    );
}

/// R2: spec #930's truncated ticket list leaves spec #901's complete
/// reads, and so its Needs you items, usable.
#[test]
fn c10_r2_a_truncated_fleet_keeps_the_other_fleets_items() {
    let gh = s::gh("c10-r2", |_, issues, _| {
        let spec = issues.iter_mut().find(|i| i["number"] == 930).unwrap();
        spec["subIssues"]["totalCount"] = json!(3);
    });
    let setup = Setup::new(s::inventory(vec![]), gh, room(&[P1]));
    let body = s::read(&setup.serve());
    let needs = &body["needs_you"];
    assert_eq!(needs["coverage"]["state"], "partial");
    assert!(s::has_gap(needs, Some(P1), "truncated", ""), "{needs:#}");
    let tickets: Vec<_> = needs["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| i["ticket"].clone())
        .collect();
    assert_eq!(tickets, [json!(904), json!(907)], "{needs:#}");
}

/// R3: the source maps to P1 alone, but the target thread is verified in
/// P2: it is not P1's target.
#[test]
fn c10_r3_a_target_grouped_in_another_project_is_not_this_projects() {
    let setup = Setup::new(
        s::inventory(vec![s::session(11, "idle", P2, None)]),
        s::gh("c10-r3", s::no_needs),
        room(&[P1]),
    )
    .target(s::messenger("c10-r3-target", vec![]), Some(TARGET));
    let body = s::read(&setup.serve());
    let p1 = &s::project(&body, P1)["orchestrator"];
    assert!(s::unknown(&p1["target"]), "{p1:#}");
    assert_eq!(p1["coverage"]["state"], "partial");
    assert!(s::unknown(&s::project(&body, P2)["orchestrator"]["target"]));
}

/// R4: the inventory says P2, the fleet's thread list says P1: the chain
/// can't place it.
#[test]
fn c10_r4_a_placement_whose_project_contradicts_the_inventory_is_unknown() {
    let setup = Setup::new(
        s::inventory(vec![s::session(1, "active", P2, None)]),
        s::gh("c10-r4", s::no_needs),
        room(&[P1]),
    );
    let body = s::read(&setup.serve());
    let agent = s::agent(&body, "thr_syn_0001");
    for fact in ["fleet", "ticket", "state"] {
        assert!(s::unknown(&agent[fact]), "{fact}: {agent:#}");
    }
    assert!(s::has_gap(
        &body["agents"],
        Some(P2),
        "malformed",
        "project"
    ));
}

/// R5: an unverified project and an unknown local machine are unknown
/// facts of a running agent: gaps.
#[test]
fn c10_r5_an_unverified_project_or_machine_is_a_gap() {
    let setup = Setup::new(
        s::inventory(vec![
            s::session(4, "active", "prj_syn_0099", None),
            s::session(5, "active", P1, Some("mch_syn_0099")),
        ]),
        s::gh("c10-r5", s::no_needs),
        room(&[P1, P2]),
    );
    let body = s::read(&setup.serve());
    let agents = &body["agents"];
    assert!(s::unknown(&s::agent(&body, "thr_syn_0004")["project"]));
    assert!(
        s::has_gap(agents, None, "missing_field", "project"),
        "{agents:#}"
    );
    let local = &s::agent(&body, "thr_syn_0005")["location"]["known"];
    assert!(s::unknown(&local["machine"]), "{local:#}");
    assert!(
        s::has_gap(agents, Some(P1), "missing_field", "machine"),
        "{agents:#}"
    );
}

/// R6: one project listed twice with two names: neither is its name.
#[test]
fn c10_r6_conflicting_project_names_are_unknown() {
    let mut projects = s::projects(&[P1, P2]);
    projects.push(ProjectRecord {
        id: ProjectId(P1.to_owned()),
        name: Fact::Known("Synthetic conflicting name".to_owned()),
    });
    let setup = Setup::new(
        s::inventory(vec![]).with_projects(projects),
        s::gh("c10-r6", s::no_needs),
        room(&[P1, P2]),
    );
    let body = s::read(&setup.serve());
    assert!(s::unknown(&s::project(&body, P1)["name"]), "{body:#}");
    assert!(s::has_gap(&body["projects"], Some(P1), "malformed", "name"));
    assert_eq!(s::ids(&body), [P1, P2]);
}

/// R7: P2 has no fleet source, so Needs you has no snapshot for it.
#[test]
fn c10_r7_a_project_without_a_source_snapshot_is_unknown_freshness() {
    let setup = Setup::new(
        s::inventory(vec![]),
        s::gh("c10-r7", s::no_needs),
        room(&[P1]),
    );
    let body = s::read(&setup.serve());
    assert_eq!(body["needs_you"]["freshness"]["state"], "unknown");
    // With both projects sourced, the same reads are fresh.
    let setup = Setup::new(
        s::inventory(vec![]),
        s::gh("c10-r7-both", s::no_needs),
        room(&[P1, P2]),
    );
    let body = s::read(&setup.serve());
    assert_eq!(body["needs_you"]["freshness"]["state"], "fresh");
}

/// R9: project discovery takes time; the session list still ends at the
/// run's one deadline, never a new 30-second budget.
#[test]
fn c10_r9_the_inventory_keeps_the_runs_one_deadline() {
    struct SlowProjects(ScriptedSource);
    impl SessionSource for SlowProjects {
        fn name(&self) -> &str {
            self.0.name()
        }
        fn tested_version(&self) -> &str {
            self.0.tested_version()
        }
        fn version(&self, d: Instant) -> Result<String, SourceError> {
            self.0.version(d)
        }
        fn list_sessions(
            &self,
            s: SessionScope,
            d: Instant,
        ) -> Result<Rows<SessionRecord>, SourceError> {
            self.0.list_sessions(s, d)
        }
        fn list_projects(&self, h: bool, d: Instant) -> Result<Rows<ProjectRecord>, SourceError> {
            std::thread::sleep(Duration::from_millis(400));
            self.0.list_projects(h, d)
        }
        fn list_machines(&self, d: Instant) -> Result<Rows<MachineRecord>, SourceError> {
            self.0.list_machines(d)
        }
        fn session_detail(
            &self,
            id: &openwiz_core::model::SessionId,
            d: Instant,
        ) -> Result<SessionDetailRecord, SourceError> {
            self.0.session_detail(id, d)
        }
        fn session_output(
            &self,
            id: &openwiz_core::model::SessionId,
            d: Instant,
        ) -> Result<OutputRecord, SourceError> {
            self.0.session_output(id, d)
        }
    }
    let source = Arc::new(SlowProjects(s::inventory(vec![s::session(
        1, "active", P1, None,
    )])));
    let mut setup = Setup::new(
        s::inventory(vec![]),
        s::gh("c10-r9", s::no_needs),
        room(&[P1]),
    );
    setup.source = source.clone();
    s::read(&setup.serve());
    let deadlines = source.0.deadlines.lock().unwrap();
    let (first, last) = (
        *deadlines.iter().min().unwrap(),
        *deadlines.iter().max().unwrap(),
    );
    assert!(
        last.duration_since(first) < Duration::from_millis(200),
        "{:?} later",
        last.duration_since(first)
    );
}

/// Review 1, R1: two running Cloud threads on PR #952's head branch. The
/// chain places neither; the ambiguity is a gap, and both rows stay.
#[test]
fn c10_review1_r1_an_ambiguous_placement_is_a_gap() {
    let setup = Setup::new(
        s::inventory(vec![
            s::session(1, "active", P1, None),
            s::session(2, "active", P1, None),
        ]),
        s::gh("c10-review1-r1", s::no_needs),
        Room::new(
            &[P1, P2],
            &[
                ("thr_syn_0001", P1, Some("room/syn-a2-0002")),
                ("thr_syn_0002", P1, Some("room/syn-a2-0002")),
            ],
        ),
    );
    let body = s::read(&setup.serve());
    let agents = &body["agents"];
    assert_eq!(s::threads(&body), ["thr_syn_0001", "thr_syn_0002"]);
    for thread in ["thr_syn_0001", "thr_syn_0002"] {
        let agent = s::agent(&body, thread);
        for fact in ["fleet", "ticket", "state"] {
            assert!(s::unknown(&agent[fact]), "{fact}: {agent:#}");
        }
        assert_eq!(agent["model"], json!({"known": "synthetic-model-a"}));
    }
    assert_eq!(agents["coverage"]["state"], "partial", "{agents:#}");
    assert!(
        s::has_gap(agents, Some(P1), "unsupported", "ambiguous"),
        "{agents:#}"
    );
}

/// Review 1, R2: ticket #903 is closed without a verified merge, so the
/// fleet can't give its state; the agent stays placed, and the unknown
/// state is a gap.
#[test]
fn c10_review1_r2_a_placed_agents_unknown_state_is_a_gap() {
    let setup = Setup::new(
        s::inventory(vec![s::session(1, "active", P1, None)]),
        s::gh("c10-review1-r2", |scenario, issues, prs| {
            s::no_needs(scenario, issues, prs);
            let ticket = issues.iter_mut().find(|i| i["number"] == 903).unwrap();
            ticket["state"] = json!("CLOSED");
        }),
        Room::new(&[P1, P2], &[("thr_syn_0001", P1, Some("room/syn-a2-0002"))]),
    );
    let body = s::read(&setup.serve());
    let agents = &body["agents"];
    let agent = s::agent(&body, "thr_syn_0001");
    assert_eq!(agent["ticket"], json!({"known": 903}), "{agent:#}");
    assert_eq!(agent["fleet"], json!({"known": 901}));
    assert!(s::unknown(&agent["state"]), "{agent:#}");
    assert_eq!(agents["coverage"]["state"], "partial", "{agents:#}");
    assert!(
        s::has_gap(agents, Some(P1), "unsupported", "state"),
        "{agents:#}"
    );
}

/// Review 1, R1 again (re-check 1): the thread's branch is PR #952's head
/// (ticket #903 of fleet #901) and also PR #955's, which closes #931 and
/// #941 (fleet #930's ticket and another issue). One fleet's ambiguity
/// makes the whole placement doubtful: a doubtful link places nothing, and
/// another fleet's known placement can't hide the gap. The row stays.
#[test]
fn c10_review1_r1_another_fleets_ambiguity_is_not_hidden_by_a_placement() {
    let setup = Setup::new(
        s::inventory(vec![s::session(1, "active", P1, None)]),
        s::gh("c10-review1-r1-cross", |scenario, issues, prs| {
            s::no_needs(scenario, issues, prs);
            let reference = |number: u64| {
                json!({
                    "id": format!("syn-issue-{number:04}"),
                    "number": number,
                    "repository": {"id": "syn-repo-0001", "name": "syn-example-repo",
                        "owner": {"id": "syn-owner-0001", "login": "syn-owner"}},
                    "url": format!("https://example.invalid/synthetic/issues/{number}"),
                })
            };
            let pr = prs.iter_mut().find(|p| p["number"] == 955).unwrap();
            pr["baseRefName"] = json!("release-synthetic");
            pr["headRefName"] = json!("room/syn-a2-0002");
            pr["closingIssuesReferences"] = json!([reference(931), reference(941)]);
        }),
        Room::new(&[P1, P2], &[("thr_syn_0001", P1, Some("room/syn-a2-0002"))]),
    );
    let body = s::read(&setup.serve());
    let agents = &body["agents"];
    assert_eq!(s::threads(&body), ["thr_syn_0001"]);
    let agent = s::agent(&body, "thr_syn_0001");
    for fact in ["fleet", "ticket", "state"] {
        assert!(s::unknown(&agent[fact]), "{fact}: {agent:#}");
    }
    assert_eq!(agent["model"], json!({"known": "synthetic-model-a"}));
    assert_eq!(agents["coverage"]["state"], "partial", "{agents:#}");
    assert!(
        s::has_gap(agents, Some(P1), "unsupported", "ambiguous"),
        "{agents:#}"
    );
}

/// Self-review 2, H1: hidden and archived sessions that are positively
/// active are running agents too. The cockpit reads them, in pages, so
/// one past the 200-row page isn't lost either.
#[test]
fn c10_self2_h1_hidden_archived_and_later_page_agents_are_listed() {
    let mut hidden = s::session(1, "active", P1, None);
    hidden.hidden = Fact::Known(true);
    let mut archived = s::session(2, "active", P1, None);
    archived.archived = Fact::Known(true);
    let mut records: Vec<SessionRecord> = vec![hidden, archived];
    records.extend((3..=250).map(|n| s::session(n, "idle", P1, None)));
    // The oldest update, so the last of 250 rows: past the first page.
    let mut late = s::session(251, "active", P1, None);
    late.updated_at = Fact::Known(openwiz_core::model::Timestamp(crate::fake::T0.0 - 900_000));
    records.push(late);
    let setup = Setup::new(
        s::inventory(records),
        s::gh("c10-self2-h1", s::no_needs),
        room(&[P1, P2]),
    );
    let body = s::read(&setup.serve());
    let agents = &body["agents"];
    assert_eq!(
        s::threads(&body),
        ["thr_syn_0001", "thr_syn_0002", "thr_syn_0251"],
        "{agents:#}"
    );
    assert!(!s::has_gap(agents, None, "truncated", ""), "{agents:#}");
}

/// Self-review 2, H2: a running agent that no verified chain places has
/// unknown fleet, ticket and state; that is a gap, never complete.
#[test]
fn c10_self2_h2_an_unplaced_agent_is_a_gap() {
    let setup = Setup::new(
        s::inventory(vec![s::session(4, "active", P1, None)]),
        s::gh("c10-self2-h2", s::no_needs),
        Room::new(
            &[P1, P2],
            &[("thr_syn_0004", P1, Some("room/syn-unrelated"))],
        ),
    );
    let body = s::read(&setup.serve());
    let agents = &body["agents"];
    let agent = s::agent(&body, "thr_syn_0004");
    for fact in ["fleet", "ticket", "state"] {
        assert!(s::unknown(&agent[fact]), "{fact}: {agent:#}");
    }
    assert_eq!(agents["coverage"]["state"], "partial", "{agents:#}");
    assert!(
        s::has_gap(agents, Some(P1), "unsupported", "not placed"),
        "{agents:#}"
    );
}

/// Re-check 2, R3: the session list is read again for each 200-row page.
/// Here the only running session (the oldest, so the last row) has a new
/// update time on every read after the first, so independent pages would
/// repeat one row and lose it. One consistent enumeration per run keeps
/// it; anything less is never complete.
#[test]
fn c10_review2_r3_a_reordered_inventory_keeps_its_running_agent() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    struct Reordering {
        inner: ScriptedSource,
        reads: AtomicUsize,
    }
    impl SessionSource for Reordering {
        fn name(&self) -> &str {
            self.inner.name()
        }
        fn tested_version(&self) -> &str {
            self.inner.tested_version()
        }
        fn version(&self, d: Instant) -> Result<String, SourceError> {
            self.inner.version(d)
        }
        fn list_sessions(
            &self,
            scope: SessionScope,
            d: Instant,
        ) -> Result<Rows<SessionRecord>, SourceError> {
            let mut rows = self.inner.list_sessions(scope, d)?;
            if self.reads.fetch_add(1, Ordering::SeqCst) > 0 {
                let running = rows
                    .records
                    .iter_mut()
                    .find(|r| r.id.0 == "thr_syn_0201")
                    .unwrap();
                running.updated_at = Fact::Known(crate::fake::T0);
            }
            Ok(rows)
        }
        fn list_projects(&self, h: bool, d: Instant) -> Result<Rows<ProjectRecord>, SourceError> {
            self.inner.list_projects(h, d)
        }
        fn list_machines(&self, d: Instant) -> Result<Rows<MachineRecord>, SourceError> {
            self.inner.list_machines(d)
        }
        fn session_detail(
            &self,
            id: &openwiz_core::model::SessionId,
            d: Instant,
        ) -> Result<SessionDetailRecord, SourceError> {
            self.inner.session_detail(id, d)
        }
        fn session_output(
            &self,
            id: &openwiz_core::model::SessionId,
            d: Instant,
        ) -> Result<OutputRecord, SourceError> {
            self.inner.session_output(id, d)
        }
    }
    let records = (1..=201)
        .map(|n| s::session(n, if n == 201 { "active" } else { "idle" }, P1, None))
        .collect();
    let source = Arc::new(Reordering {
        inner: s::inventory(records),
        reads: AtomicUsize::new(0),
    });
    let mut setup = Setup::new(
        s::inventory(vec![]),
        s::gh("c10-review2-r3", s::no_needs),
        Room::new(&[P1, P2], &[("thr_syn_0201", P1, Some("room/syn-a2-0002"))]),
    );
    setup.source = source.clone();
    let body = s::read(&setup.serve());
    let agents = &body["agents"];
    assert_eq!(s::threads(&body), ["thr_syn_0201"], "{agents:#}");
    assert!(!s::has_gap(agents, None, "truncated", ""), "{agents:#}");
    // One session-list read per run, whatever the page count.
    assert_eq!(source.reads.load(Ordering::SeqCst), 1);
}
