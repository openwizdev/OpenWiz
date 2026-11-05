//! PA7: the real cockpit route retains unread project stock, never invents zero.
//! Current tests predate the optional stock extension and miss its absence.
use crate::c10_cockpit_support::{self as s, P1, P2, Room, Setup};

#[test]
fn ready_stock_missing_sources_are_visible_and_totals_are_unknown() {
    let setup = Setup::new(
        s::inventory(vec![]),
        s::gh("stock-missing", s::no_needs),
        Room::new(&[P1], &[]),
    );
    let server = setup.serve();
    let response = server.get(s::ROUTE);
    assert_eq!(response.status, 200);
    let body = response.json();
    let stock = &body["ready_stock"];
    assert!(
        stock.is_object(),
        "cockpit must expose stock, including source gaps"
    );
    assert_eq!(stock["coverage"]["state"], "partial");
    assert!(stock["totals"]["unknown"].is_string());
    let projects = stock["projects"].as_array().unwrap();
    assert_eq!(projects.len(), 2);
    for id in [P1, P2] {
        let p = projects.iter().find(|p| p["project"] == id).unwrap();
        assert_eq!(p["coverage"]["state"], "partial");
        assert!(!p["coverage"]["gaps"].as_array().unwrap().is_empty());
    }
    s::check(&body);
}

use openwiz_core::model::Timestamp;
use openwiz_core::notifications::{model::*, stock::*};
use openwiz_core::ops::Clock;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicUsize, Ordering},
};
use std::time::Instant;
struct Fixed;
impl Clock for Fixed {
    fn now(&self) -> Timestamp {
        Timestamp(200_000)
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}
struct Injected {
    rows: Vec<ProjectFacts>,
    calls: Arc<AtomicUsize>,
}
impl openwiz_server::StockSource for Injected {
    fn read(&self, _: &[Id], _: Instant) -> Vec<ProjectFacts> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.rows.clone()
    }
}
fn ticket(n: u64) -> TicketFacts {
    TicketFacts {
        number: n,
        open: Fact::Known(true),
        merged: Fact::Known(false),
        labels: Fact::Known(vec!["ready-for-agent".into()]),
        start_recorded: Fact::Known(false),
        matching_open_pr: Fact::Known(false),
        blockers_merged: Fact::Known(true),
        capacity_refused: None,
    }
}
fn project_input(id: &str, rows: Vec<TicketFacts>) -> ProjectFacts {
    ProjectFacts {
        project: Id::new(id).unwrap(),
        coverage: Coverage {
            state: CoverageState::Complete,
            gaps: vec![],
        },
        snapshot_at: Fact::Known(190_000),
        tickets: Fact::Known(rows),
        last_good: None,
    }
}
fn installed(rows: Vec<ProjectFacts>) -> (crate::http::TestServer, Arc<AtomicUsize>) {
    let calls = Arc::new(AtomicUsize::new(0));
    let lines = Arc::new(Mutex::new(Vec::new()));
    let log = lines.clone();
    let server = openwiz_server::start_with_stock_source(
        openwiz_server::bind(0).unwrap(),
        openwiz_server::Config::default(),
        Arc::new(s::inventory(vec![])),
        Arc::new(Fixed),
        Arc::new(move |line| log.lock().unwrap().push(line.to_owned())),
        openwiz_server::ReadSources::default(),
        Arc::new(Injected {
            rows,
            calls: calls.clone(),
        }),
    )
    .unwrap();
    (
        crate::http::TestServer {
            addr: server.local_addr(),
            server,
            log: lines,
        },
        calls,
    )
}
#[test]
fn ready_stock_injected_source_to_cockpit_count_matrix() {
    // PA6 synthetic injected source facts. NOT current production source proof.
    for (ready, running, state) in [
        (4, 2, "fed"),
        (3, 2, "low_stock"),
        (0, 2, "running_dry"),
        (3, 0, "no_builders"),
        (0, 0, "running_dry"),
    ] {
        let mut rows = vec![];
        for n in 1..=ready {
            rows.push(ticket(n));
        }
        for n in 100..100 + running {
            let mut t = ticket(n);
            t.start_recorded = Fact::Known(true);
            t.blockers_merged = Fact::Known(false);
            rows.push(t);
        }
        for (n, label) in [
            (200, "held"),
            (201, "needs-info"),
            (202, "ready-for-human"),
            (203, "unapproved"),
        ] {
            let mut t = ticket(n);
            t.labels = Fact::Known(vec![label.into()]);
            rows.push(t);
        }
        let mut t = ticket(204);
        t.blockers_merged = Fact::Known(false);
        rows.push(t);
        let mut t = ticket(205);
        t.capacity_refused = Some(Fact::Known(true));
        rows.push(t);
        let (server, calls) = installed(vec![project_input(P1, rows), project_input(P2, vec![])]);
        let r = server.get(s::ROUTE);
        assert_eq!(r.status, 200);
        let body = r.json();
        s::check(&body);
        let stock = &body["ready_stock"];
        assert_eq!(
            stock["totals"]["known"],
            serde_json::json!({"ready":ready,"running":running,"blocked":1,"held":1,"unapproved":1,"owner_wait":2,"capacity_wait":1,"unknown":0,"state":state})
        );
        assert_eq!(stock["freshness"]["snapshot_at"]["known"], 190_000);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert!(
            server
                .settled_log()
                .lines()
                .all(|l| l.starts_with("GET /api/v1/cockpit 200 "))
        );
    }
}
#[test]
fn ready_stock_partial_stale_future_missing_and_last_good_keep_original_evidence() {
    for kind in [
        "partial",
        "stale",
        "future",
        "missing",
        "unread-counts",
        "unverified-blocker",
        "unknown-title",
        "unknown-capacity",
    ] {
        let mut p = project_input(P2, vec![ticket(1)]);
        let sample = StockSample {
            snapshot_at: 100_000,
            counts: StockCounts {
                ready: 2,
                running: 1,
                blocked: 0,
                held: 0,
                unapproved: 0,
                owner_wait: 0,
                capacity_wait: 0,
                unknown: 0,
                state: StockState::Fed,
            },
        };
        p.last_good = Some(sample);
        match kind {
            "partial" => gap(&mut p.coverage, "Synthetic incomplete source"),
            "stale" => p.snapshot_at = Fact::Known(129_999),
            "future" => p.snapshot_at = Fact::Known(200_001),
            "unread-counts" => p.tickets = unknown("Synthetic unread tickets"),
            "unverified-blocker" | "unknown-title" | "unknown-capacity" => {
                let Fact::Known(rows) = &mut p.tickets else {
                    unreachable!()
                };
                match kind {
                    "unverified-blocker" => {
                        rows[0].blockers_merged = unknown("Synthetic merge gap")
                    }
                    "unknown-title" => rows[0].matching_open_pr = unknown("Synthetic title gap"),
                    _ => rows[0].capacity_refused = Some(unknown("Synthetic capacity gap")),
                }
            }
            _ => {}
        }
        let rows = if kind == "missing" {
            vec![project_input(P1, vec![])]
        } else {
            vec![project_input(P1, vec![]), p]
        };
        let (server, _) = installed(rows);
        let body = server.get(s::ROUTE).json();
        s::check(&body);
        let stock = &body["ready_stock"];
        assert!(stock["totals"]["unknown"].is_string(), "{kind}: {stock}");
        assert_eq!(stock["projects"].as_array().unwrap().len(), 2);
        if kind != "missing" {
            assert_eq!(stock["projects"][1]["last_good"]["snapshot_at"], 100_000);
        }
        if kind == "stale" {
            assert_eq!(stock["freshness"]["state"], "stale");
            assert_eq!(stock["freshness"]["snapshot_at"]["known"], 129_999);
        }
        if kind == "future" {
            assert_eq!(stock["freshness"]["state"], "unknown");
        }
    }
}

fn custom(
    source: Arc<dyn openwiz_core::source::SessionSource>,
    clock: Arc<dyn Clock>,
    reads: openwiz_server::ReadSources,
    stock: Arc<dyn openwiz_server::StockSource>,
) -> crate::http::TestServer {
    let lines = Arc::new(Mutex::new(Vec::new()));
    let log = lines.clone();
    let server = openwiz_server::start_with_stock_source(
        openwiz_server::bind(0).unwrap(),
        openwiz_server::Config::default(),
        source,
        clock,
        Arc::new(move |line| log.lock().unwrap().push(line.to_owned())),
        reads,
        stock,
    )
    .unwrap();
    crate::http::TestServer {
        addr: server.local_addr(),
        server,
        log: lines,
    }
}
#[test]
fn ready_stock_review_partial_fleet_discovery_prevents_known_totals() {
    use openwiz_core::fleet::model::{ListOutcome, NonEmpty, Truncated};
    let fake = s::gh("stock-partial-discovery", s::no_needs);
    let room = Room::new(&[P1], &[]);
    {
        let mut reads = room.reads.lock().unwrap();
        let ListOutcome::Complete { value } = reads.projects.clone() else {
            unreachable!()
        };
        reads.projects = ListOutcome::Partial {
            gap: Truncated::Truncated,
            reason: NonEmpty::new("Synthetic incomplete mapping").unwrap(),
            value,
        };
    }
    let reads = openwiz_server::ReadSources {
        fleets: Some(openwiz_server::Fleets {
            list: Arc::new(openwiz_adapter_github::fleets::GitHubFleets::with_program(
                fake.program(),
            )),
            detail: Arc::new(openwiz_adapter_github::tickets::Tickets::new(
                fake.program(),
            )),
            agents: Arc::new(s::RoomAgents(room)),
        }),
        ..Default::default()
    };
    let server = custom(
        Arc::new(s::inventory(vec![])),
        Arc::new(Fixed),
        reads,
        Arc::new(Injected {
            rows: vec![
                project_input(P1, vec![ticket(1)]),
                project_input(P2, vec![]),
            ],
            calls: Arc::new(AtomicUsize::new(0)),
        }),
    );
    let body = server.get(s::ROUTE).json();
    assert_eq!(body["ready_stock"]["coverage"]["state"], "partial");
    assert!(body["ready_stock"]["totals"]["unknown"].is_string());
}
struct MovingClock(Arc<std::sync::atomic::AtomicI64>);
impl Clock for MovingClock {
    fn now(&self) -> Timestamp {
        Timestamp(self.0.load(Ordering::SeqCst))
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}
struct AdvancingStock(Arc<std::sync::atomic::AtomicI64>);
impl openwiz_server::StockSource for AdvancingStock {
    fn read(&self, _: &[Id], _: Instant) -> Vec<ProjectFacts> {
        self.0.store(200_000, Ordering::SeqCst);
        [P1, P2]
            .map(|id| {
                let mut p = project_input(id, vec![]);
                p.snapshot_at = Fact::Known(150_000);
                p
            })
            .into()
    }
}
#[test]
fn ready_stock_review_assembly_time_follows_the_provider_read() {
    let now = Arc::new(std::sync::atomic::AtomicI64::new(100_000));
    let server = custom(
        Arc::new(s::inventory(vec![])),
        Arc::new(MovingClock(now.clone())),
        Default::default(),
        Arc::new(AdvancingStock(now)),
    );
    let body = server.get(s::ROUTE).json();
    assert_eq!(body["snapshot_at"], 200_000);
    assert_eq!(
        body["ready_stock"]["projects"][0]["freshness"]["state"],
        "fresh"
    );
    assert_eq!(body["ready_stock"]["freshness"]["state"], "stale");
    assert!(body["ready_stock"]["totals"]["unknown"].is_string());
}
// R1: discovery must be judged at final assembly, after the provider returns.
// A slow read or backwards clock cannot positively retire a missing identity.
struct DiscoveryTimeStock {
    now: Arc<std::sync::atomic::AtomicI64>,
    finish: Arc<std::sync::atomic::AtomicI64>,
}
impl openwiz_server::StockSource for DiscoveryTimeStock {
    fn read(&self, _: &[Id], _: Instant) -> Vec<ProjectFacts> {
        self.now
            .store(self.finish.load(Ordering::SeqCst), Ordering::SeqCst);
        let mut p = project_input(P1, vec![ticket(1)]);
        p.snapshot_at = Fact::Known(100_000);
        vec![p]
    }
}
#[test]
fn ready_stock_review_stale_or_future_discovery_cannot_retire_a_project() {
    for (scan_at, finish_at, state) in [(100_000, 200_000, "stale"), (200_000, 100_000, "unknown")]
    {
        let now = Arc::new(std::sync::atomic::AtomicI64::new(100_000));
        let finish = Arc::new(std::sync::atomic::AtomicI64::new(100_000));
        let source = Arc::new(s::inventory(vec![]).with_projects(s::projects(&[P1])));
        let server = custom(
            source.clone(),
            Arc::new(MovingClock(now.clone())),
            Default::default(),
            Arc::new(DiscoveryTimeStock {
                now: now.clone(),
                finish: finish.clone(),
            }),
        );
        let first = server.get(s::ROUTE).json();
        assert_eq!(first["ready_stock"]["totals"]["known"]["ready"], 1);
        source.set_projects(vec![]);
        now.store(scan_at, Ordering::SeqCst);
        finish.store(finish_at, Ordering::SeqCst);
        let missing = server.get(s::ROUTE).json();
        s::check(&missing);
        assert_eq!(s::ids(&missing), [P1]);
        assert_eq!(missing["projects"]["freshness"]["state"], state);
        let row = &missing["ready_stock"]["projects"][0];
        assert_eq!(row["project"], P1);
        assert!(
            row["counts"]["unknown"].is_string(),
            "an unrequested provider fact cannot make a missing project current"
        );
        assert_eq!(row["last_good"]["snapshot_at"], 100_000);
        assert_eq!(row["last_good"]["counts"]["ready"], 1);
        assert!(missing["ready_stock"]["totals"]["unknown"].is_string());
    }
}

#[test]
fn ready_stock_review_opaque_project_ids_preserve_cockpit_without_partial_extension() {
    let source = s::inventory(vec![]).with_projects(s::projects(&[P1, "zz.synthetic"]));
    let server = custom(
        Arc::new(source),
        Arc::new(Fixed),
        Default::default(),
        Arc::new(Injected {
            rows: vec![project_input(P1, vec![])],
            calls: Arc::new(AtomicUsize::new(0)),
        }),
    );
    let body = server.get(s::ROUTE).json();
    s::check(&body);
    assert_eq!(body["projects"]["items"].as_array().unwrap().len(), 2);
    assert_eq!(body["projects"]["items"][1]["id"], "zz.synthetic");
    // The optional stock contract has a narrower ID domain. Refuse the whole
    // extension instead of dropping a project or invalidating old cockpit data.
    assert!(body.get("ready_stock").is_none());
}

// Existing reader injection → default installed stock join. No precomputed stock
// or notification provider is injected; inventory has no active session.
mod installed_facts {
    use super::*;
    use openwiz_core::fleet::{
        fleets::{FleetsSource, IssueRow, Link, Links, Listed, PrFacts, PrRow, StockPr},
        model::{self as m, NonEmpty, Number},
        tickets::{self, GitHub, IssueAnswer, ListAnswer, PrAnswer, RepositoryAnswer},
    };
    use openwiz_core::model::Fact as F;
    use openwiz_core::source::SourceError;
    fn n(v: u64) -> Number {
        Number::new(v).unwrap()
    }
    fn ne(s: &str) -> NonEmpty {
        NonEmpty::new(s).unwrap()
    }
    fn link(v: u64) -> Link {
        Link {
            number: n(v),
            id: ne(&format!("synthetic-issue-{v}")),
        }
    }
    fn links(ids: &[u64]) -> Links {
        Links {
            nodes: ids.iter().copied().map(link).collect(),
            total: ids.len() as u64,
        }
    }
    struct World {
        issues: Vec<IssueRow>,
        prs: Vec<StockPr>,
        starts: std::collections::BTreeSet<u64>,
        issue_partial: std::sync::atomic::AtomicBool,
        pr_partial: bool,
        repository_failed: bool,
        repository_name: &'static str,
        merge: bool,
        comments: bool,
        lists: AtomicUsize,
        pr_lists: AtomicUsize,
        merges: AtomicUsize,
    }
    fn world() -> World {
        let mut issues = vec![IssueRow {
            number: n(901),
            id: link(901).id,
            title: "Synthetic plan".into(),
            state: m::IssueState::Open,
            milestone: None,
            labels: vec![],
            body: String::new(),
            sub_issues: links(&(902..=911).collect::<Vec<_>>()),
            blocked_by: links(&[]),
        }];
        for (id, label, blockers) in [
            (902, "ready-for-agent", vec![]),
            (903, "held", vec![906]),
            (904, "ready-for-agent", vec![]),
            (905, "ready-for-agent", vec![906]),
            (906, "unapproved", vec![]),
            (907, "held", vec![]),
            (908, "needs-info", vec![]),
            (909, "ready-for-human", vec![]),
            (910, "unapproved", vec![]),
            (911, "ready-for-agent", vec![812]),
        ] {
            issues.push(IssueRow {
                number: n(id),
                id: link(id).id,
                title: format!("Synthetic ticket {id}"),
                state: m::IssueState::Open,
                milestone: None,
                labels: vec![ne(label)],
                body: String::new(),
                sub_issues: links(&[]),
                blocked_by: links(&blockers),
            });
        }
        issues.push(IssueRow {
            number: n(812),
            id: link(812).id,
            title: "Synthetic closed blocker".into(),
            state: m::IssueState::Closed,
            milestone: None,
            labels: vec![],
            body: String::new(),
            sub_issues: links(&[]),
            blocked_by: links(&[]),
        });
        let facts = |id, closes| PrFacts {
            number: n(id),
            draft: false,
            head_branch: ne("room/synthetic"),
            head_commit: m::Commit::parse(&"1".repeat(40)).unwrap(),
            base_branch: ne("main"),
            closes,
        };
        let prs = vec![
            StockPr {
                pr: PrRow::Open(facts(95, vec![])),
                title: F::Known(ne("#902: Synthetic title builder")),
            },
            StockPr {
                pr: PrRow::Merged {
                    facts: facts(96, vec![link(812)]),
                    merge_commit: m::Commit::parse(&"2".repeat(40)).unwrap(),
                    merged_at: Timestamp(100_000),
                },
                title: F::Known(ne("Synthetic merged prerequisite")),
            },
        ];
        World {
            issues,
            prs,
            starts: [903].into(),
            issue_partial: std::sync::atomic::AtomicBool::new(false),
            pr_partial: false,
            repository_failed: false,
            repository_name: "synthetic",
            merge: true,
            comments: true,
            lists: AtomicUsize::new(0),
            pr_lists: AtomicUsize::new(0),
            merges: AtomicUsize::new(0),
        }
    }
    impl FleetsSource for World {
        fn tested_version(&self) -> &str {
            "2.100.0"
        }
        fn version(&self, _: Instant) -> Result<NonEmpty, m::Failed> {
            Ok(ne("2.100.0"))
        }
        fn repository(&self, _: Instant) -> Result<m::Repository, m::Failed> {
            if self.repository_failed {
                return Err(m::Failed {
                    gap: openwiz_core::envelope::GapKind::CommandFailed,
                    reason: ne("Synthetic unread repository"),
                });
            }
            Ok(m::Repository {
                name: ne(self.repository_name),
            })
        }
        fn issues(&self, _: Instant) -> Result<Listed<IssueRow>, m::Failed> {
            self.lists.fetch_add(1, Ordering::SeqCst);
            Ok(Listed {
                rows: self.issues.clone(),
                cut_short: self.issue_partial.load(Ordering::SeqCst),
            })
        }
        fn pull_requests(&self, d: Instant) -> Result<Listed<PrRow>, m::Failed> {
            self.stock_pull_requests(d).map(|v| Listed {
                rows: v.rows.into_iter().map(|p| p.pr).collect(),
                cut_short: v.cut_short,
            })
        }
        fn stock_pull_requests(&self, _: Instant) -> Result<Listed<StockPr>, m::Failed> {
            self.pr_lists.fetch_add(1, Ordering::SeqCst);
            Ok(Listed {
                rows: self.prs.clone(),
                cut_short: self.pr_partial,
            })
        }
        fn checks(&self, _: Number, _: Instant) -> Result<Vec<m::Check>, m::Failed> {
            Ok(vec![])
        }
        fn comments(&self, _: Number, _: Instant) -> Result<Vec<String>, m::Failed> {
            Ok(vec![])
        }
        fn on_base(&self, _: &m::MergedPr, _: Instant) -> Result<bool, m::Failed> {
            self.merges.fetch_add(1, Ordering::SeqCst);
            Ok(self.merge)
        }
    }
    impl GitHub for World {
        fn version(&self, _: Instant) -> Result<String, SourceError> {
            Ok("2.100.0".into())
        }
        fn repository(&self, _: Instant) -> Result<RepositoryAnswer, SourceError> {
            Ok(RepositoryAnswer {
                name: ne("synthetic"),
                name_with_owner: ne("synthetic/repo"),
                url: ne("https://example.invalid/synthetic/repo"),
            })
        }
        fn issue(&self, id: Number, _: Instant) -> Result<IssueAnswer, SourceError> {
            let i = self
                .issues
                .iter()
                .find(|i| i.number == id)
                .ok_or(SourceError::NotFound {
                    subject: "synthetic issue".into(),
                })?;
            let list = |ls: &Links| ListAnswer {
                nodes: ls
                    .nodes
                    .iter()
                    .map(|l| tickets::Link {
                        number: l.number,
                        url: format!("https://example.invalid/synthetic/repo/issues/{}", l.number),
                    })
                    .collect(),
                total: ls.total,
            };
            Ok(IssueAnswer {
                issue: m::Issue {
                    title: i.title.clone(),
                    state: i.state,
                    milestone: None,
                    labels: i.labels.clone(),
                    owned_paths: None,
                    relies_on: None,
                    pending_question: None,
                },
                sub_issues: list(&i.sub_issues),
                blocked_by: list(&i.blocked_by),
                closed_by: vec![],
            })
        }
        fn stock_issue(
            &self,
            id: Number,
            d: Instant,
        ) -> Result<(IssueAnswer, F<bool>), SourceError> {
            Ok((
                GitHub::issue(self, id, d)?,
                if self.comments {
                    F::Known(self.starts.contains(&id.get()))
                } else {
                    F::Unknown("Synthetic unread comments".into())
                },
            ))
        }
        fn pull_request(&self, _: Number, _: Instant) -> Result<PrAnswer, SourceError> {
            Err(SourceError::Unavailable {
                detail: "unused synthetic PR view".into(),
            })
        }
        fn checks(&self, _: Number, _: Instant) -> Result<Vec<m::Check>, SourceError> {
            Ok(vec![])
        }
        fn verdict_comments(&self, _: Number, _: Instant) -> Result<Vec<String>, SourceError> {
            Ok(vec![])
        }
        fn on_base(&self, _: &m::Commit, _: &NonEmpty, _: Instant) -> Result<bool, SourceError> {
            Ok(self.merge)
        }
    }
    fn serve(w: Arc<World>, missing: bool) -> crate::http::TestServer {
        serve_clock(w, missing, Arc::new(Fixed))
    }
    fn serve_clock(w: Arc<World>, missing: bool, clock: Arc<dyn Clock>) -> crate::http::TestServer {
        let source = Arc::new(s::inventory(vec![]).with_projects(s::projects(if missing {
            &[P1, P2]
        } else {
            &[P1]
        })));
        serve_sources(w, clock, source, Room::new(&[P1], &[]))
    }
    fn serve_sources(
        w: Arc<World>,
        clock: Arc<dyn Clock>,
        source: Arc<crate::fake::ScriptedSource>,
        room: Arc<Room>,
    ) -> crate::http::TestServer {
        let lines = Arc::new(Mutex::new(vec![]));
        let log = lines.clone();
        let server = openwiz_server::start_with_read_sources(
            openwiz_server::bind(0).unwrap(),
            Default::default(),
            source,
            clock,
            Arc::new(move |line| log.lock().unwrap().push(line.to_owned())),
            openwiz_server::ReadSources {
                fleets: Some(openwiz_server::Fleets {
                    list: w.clone(),
                    detail: w,
                    agents: Arc::new(s::RoomAgents(room)),
                }),
                ..Default::default()
            },
        )
        .unwrap();
        crate::http::TestServer {
            addr: server.local_addr(),
            server,
            log: lines,
        }
    }
    #[test]
    fn ready_stock_installed_sources_use_title_comments_native_merge_and_optional_capacity() {
        let w = Arc::new(world());
        let server = serve(w.clone(), false);
        let body = server.get(s::ROUTE).json();
        s::check(&body);
        assert_eq!(
            body["ready_stock"]["totals"]["known"],
            serde_json::json!({"ready":2,"running":2,"blocked":1,"held":1,"unapproved":2,"owner_wait":2,"capacity_wait":0,"unknown":0,"state":"low_stock"})
        );
        assert!(body["agents"]["items"].as_array().unwrap().is_empty());
        assert_eq!(
            w.lists.load(Ordering::SeqCst),
            1,
            "reuse the existing enumeration"
        );
        assert_eq!(
            w.pr_lists.load(Ordering::SeqCst),
            1,
            "reuse the title-bearing list"
        );
        assert_eq!(
            w.merges.load(Ordering::SeqCst),
            1,
            "reuse verified merge evidence"
        );
    }
    #[test]
    fn ready_stock_installed_sources_never_invent_empty_or_fed_from_gaps() {
        let mut mistaken = vec![];
        for case in [
            "issues",
            "prs",
            "comments",
            "merge",
            "project",
            "repository",
            "repository_mismatch",
            "partial_positive",
            "native_identity",
            "native_partial",
            "closing_identity",
            "pr_duplicate",
            "numeric_title_boundary",
        ] {
            let mut w = world();
            match case {
                "issues" => w.issue_partial.store(true, Ordering::SeqCst),
                "prs" => w.pr_partial = true,
                "comments" => w.comments = false,
                "merge" => w.merge = false,
                "repository" => w.repository_failed = true,
                "repository_mismatch" => w.repository_name = "other-synthetic",
                "partial_positive" => {
                    w.issues.retain(|r| r.number == n(902));
                    w.prs.truncate(1);
                    w.pr_partial = true;
                }
                "native_identity" => {
                    w.issues[10].blocked_by.nodes[0].id = ne("synthetic-foreign-812")
                }
                "native_partial" => w.issues[10].blocked_by.total = 2,
                "closing_identity" => {
                    if let PrRow::Merged { facts, .. } = &mut w.prs[1].pr {
                        facts.closes[0].id = ne("synthetic-foreign-812");
                    }
                }
                "pr_duplicate" => w.prs.push(w.prs[0].clone()),
                "numeric_title_boundary" => {
                    w.issues.retain(|r| r.number == n(902));
                    w.prs.truncate(1);
                    w.prs[0].title = F::Known(ne("#902٣: Synthetic numeric boundary"));
                }
                _ => {}
            }
            let server = serve(Arc::new(w), case == "project");
            let body = server.get(s::ROUTE).json();
            s::check(&body);
            if !body["ready_stock"]["totals"]["unknown"].is_string() {
                mistaken.push(case);
            }
        }
        assert!(
            mistaken.is_empty(),
            "Incomplete source incorrectly produced complete totals: {mistaken:?}"
        );
    }
    #[test]
    fn ready_stock_installed_source_failure_retains_original_last_good() {
        let now = Arc::new(std::sync::atomic::AtomicI64::new(100_000));
        let w = Arc::new(world());
        let server = serve_clock(w.clone(), false, Arc::new(MovingClock(now.clone())));
        let first = server.get(s::ROUTE).json();
        assert_eq!(first["ready_stock"]["totals"]["known"]["ready"], 2);
        now.store(200_000, Ordering::SeqCst);
        w.issue_partial.store(true, Ordering::SeqCst);
        let second = server.get(s::ROUTE).json();
        s::check(&second);
        assert!(second["ready_stock"]["totals"]["unknown"].is_string());
        let project = &second["ready_stock"]["projects"][0];
        assert!(project["counts"]["unknown"].is_string());
        assert_eq!(project["last_good"]["snapshot_at"], 100_000);
        assert_eq!(project["last_good"]["counts"]["ready"], 2);
        assert_eq!(project["last_good"]["counts"]["running"], 2);
    }
    #[test]
    fn ready_stock_installed_source_state_matrix_and_standalone_approval_universe() {
        for (ready, running, state, closed_history) in [
            (4, 2, "fed", None),
            (3, 2, "low_stock", None),
            (0, 2, "running_dry", None),
            (3, 0, "no_builders", None),
            (2, 2, "low_stock", Some(false)),
            (2, 2, "low_stock", Some(true)),
        ] {
            let mut w = world();
            if let Some(unread_blockers) = closed_history {
                let row = w.issues.iter_mut().find(|r| r.number == n(910)).unwrap();
                row.state = m::IssueState::Closed;
                if unread_blockers {
                    row.blocked_by.total = 1;
                }
            }
            if ready > 2 {
                for id in 920..920 + ready - 2 - u64::from(running == 0) {
                    let mut row = w
                        .issues
                        .iter()
                        .find(|r| r.number == n(904))
                        .unwrap()
                        .clone();
                    row.number = n(id);
                    row.id = link(id).id;
                    w.issues.push(row);
                }
            } else if ready == 0 {
                w.issues.retain(|r| !matches!(r.number.get(), 904 | 911));
                w.issues[0].sub_issues = links(&[902, 903, 905, 906, 907, 908, 909, 910]);
            }
            if running == 0 {
                w.starts.clear();
                w.prs.retain(|p| !matches!(p.pr, PrRow::Open(_)));
            }
            let server = serve(Arc::new(w), false);
            let body = server.get(s::ROUTE).json();
            s::check(&body);
            if closed_history.is_some() {
                let project_counts = &body["ready_stock"]["projects"][0]["counts"]["known"];
                assert_eq!(
                    project_counts["unknown"], 0,
                    "R2: unrelated closed child must not poison open stock"
                );
                assert_eq!(project_counts["unapproved"], 1);
            }
            let counts = &body["ready_stock"]["totals"]["known"];
            assert_eq!(
                (
                    counts["ready"].as_u64(),
                    counts["running"].as_u64(),
                    counts["state"].as_str()
                ),
                (Some(ready), Some(running), Some(state))
            );
        }
        // No native spec at all: approved standalone work must still be read.
        for (title, ready, running) in [
            ("#9020: another ticket", 1, 0),
            ("#902: building", 0, 1),
            ("#902", 0, 1),
        ] {
            let mut w = world();
            w.issues.retain(|r| r.number == n(902));
            w.prs.truncate(1);
            w.prs[0].title = F::Known(ne(title));
            let server = serve(Arc::new(w), false);
            let body = server.get(s::ROUTE).json();
            s::check(&body);
            assert_eq!(body["ready_stock"]["totals"]["known"]["ready"], ready);
            assert_eq!(body["ready_stock"]["totals"]["known"]["running"], running);
        }
    }
    #[test]
    fn ready_stock_review_partial_discovery_cannot_erase_last_good() {
        // R1: missing identities must remain visible, including projects that
        // have never supplied good counts. Both cockpit/stock retain the set.
        for configured in [vec![P1], vec![P1, P2]] {
            let now = Arc::new(std::sync::atomic::AtomicI64::new(100_000));
            let w = Arc::new(world());
            let source = Arc::new(s::inventory(vec![]).with_projects(s::projects(&configured)));
            let room = Room::new(&[P1], &[]);
            let server = serve_sources(
                w.clone(),
                Arc::new(MovingClock(now.clone())),
                source.clone(),
                room.clone(),
            );
            let first = server.get(s::ROUTE).json();
            assert_eq!(
                first["ready_stock"]["projects"][0]["counts"]["known"]["ready"],
                2
            );
            let listing = room.reads.lock().unwrap().projects.clone();
            source.set_projects(vec![]);
            room.reads.lock().unwrap().projects = m::ListOutcome::Partial {
                gap: m::Truncated::Truncated,
                reason: ne("Synthetic incomplete discovery"),
                value: vec![],
            };
            now.store(120_000, Ordering::SeqCst);
            let omitted = server.get(s::ROUTE).json();
            s::check(&omitted);
            assert_eq!(
                s::ids(&omitted),
                configured,
                "retain missing cockpit projects"
            );
            let stocks = omitted["ready_stock"]["projects"].as_array().unwrap();
            assert_eq!(
                stocks
                    .iter()
                    .map(|p| p["project"].as_str().unwrap())
                    .collect::<Vec<_>>(),
                configured
            );
            for project in stocks {
                assert!(project["counts"]["unknown"].is_string());
                assert_eq!(project["coverage"]["state"], "partial");
                assert!(!project["coverage"]["gaps"].as_array().unwrap().is_empty());
            }
            assert_eq!(stocks[0]["last_good"]["snapshot_at"], 100_000);
            assert_eq!(stocks[0]["last_good"]["counts"]["ready"], 2);
            assert_eq!(stocks[0]["last_good"]["counts"]["running"], 2);
            assert!(omitted["ready_stock"]["totals"]["unknown"].is_string());
            for part in ["projects", "needs_you", "agents"] {
                assert_eq!(omitted[part]["coverage"]["state"], "partial");
            }
            assert!(
                omitted["projects"]["items"][0]["orchestrator"]["target"]["unknown"].is_string()
            );
            source.set_projects(s::projects(&configured));
            room.reads.lock().unwrap().projects = listing.clone();
            now.store(200_000, Ordering::SeqCst);
            w.issue_partial.store(true, Ordering::SeqCst);
            let returned = server.get(s::ROUTE).json();
            s::check(&returned);
            let project = &returned["ready_stock"]["projects"][0];
            assert!(project["counts"]["unknown"].is_string());
            assert_eq!(project["last_good"]["snapshot_at"], 100_000);
            assert_eq!(project["last_good"]["counts"]["ready"], 2);
            // A complete fresh empty discovery positively retires identities
            // and their samples. A later failed read cannot resurrect them.
            source.set_projects(vec![]);
            room.reads.lock().unwrap().projects = m::ListOutcome::Complete { value: vec![] };
            now.store(220_000, Ordering::SeqCst);
            let removed = server.get(s::ROUTE).json();
            s::check(&removed);
            assert!(s::ids(&removed).is_empty());
            assert!(
                removed["ready_stock"]["projects"]
                    .as_array()
                    .unwrap()
                    .is_empty()
            );
            source.set_projects(s::projects(&configured));
            room.reads.lock().unwrap().projects = listing;
            now.store(240_000, Ordering::SeqCst);
            let back = server.get(s::ROUTE).json();
            s::check(&back);
            assert!(back["ready_stock"]["projects"][0]["last_good"].is_null());
        }
    }
}
