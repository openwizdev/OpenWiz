//! S3-7: fleet reads use the same bounded, uncached single-flight runner.
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use openwiz_adapter_github::{fleets::GitHubFleets, tickets::Tickets};
use openwiz_core::fleet::fleets::{FleetsSource, IssueRow, Listed, PrRow};
use openwiz_core::fleet::model::{Check, Commit, Failed, MergedPr, NonEmpty, Number, Repository};
use openwiz_core::fleet::tickets::{GitHub, IssueAnswer, PrAnswer, RepositoryAnswer};
use openwiz_core::source::SourceError;
use openwiz_server::{Config, Fleets, Limits};

use crate::fake::Fake;
use crate::http;
use crate::support::{self, FakeGh, world::World};

struct Gate {
    state: Mutex<(usize, bool)>,
    changed: Condvar,
    list: GitHubFleets,
    detail: Tickets,
}

impl Gate {
    fn new(fake: &FakeGh) -> Arc<Self> {
        Arc::new(Self {
            state: Mutex::new((0, false)),
            changed: Condvar::new(),
            list: GitHubFleets::with_program(fake.program()),
            detail: Tickets::new(fake.program()),
        })
    }
    fn enter(&self) {
        let mut state = self.state.lock().unwrap();
        state.0 += 1;
        self.changed.notify_all();
        while !state.1 {
            state = self.changed.wait(state).unwrap();
        }
    }
    fn runs(&self) -> usize {
        self.state.lock().unwrap().0
    }
    /// The runs that have entered the gate once `n` have, or after 30 s.
    /// The server counts a core run when it spawns the run's thread, and
    /// the gate only when that thread reaches its first read, so a test
    /// that saw the server's count waits here for the thread (#1306).
    fn wait_runs(&self, n: usize) -> usize {
        let state = self.state.lock().unwrap();
        let (state, _) = self
            .changed
            .wait_timeout_while(state, Duration::from_secs(30), |state| state.0 < n)
            .unwrap();
        state.0
    }
    fn open(&self) {
        self.state.lock().unwrap().1 = true;
        self.changed.notify_all();
    }
    fn sources(self: &Arc<Self>) -> Fleets {
        Fleets {
            list: self.clone(),
            detail: self.clone(),
            agents: Arc::new(openwiz_core::fleet::tickets::NotRead),
        }
    }
}

// A failed assertion must still release the core run.
struct Release(Arc<Gate>);
impl Drop for Release {
    fn drop(&mut self) {
        self.0.open();
    }
}

impl FleetsSource for Gate {
    fn tested_version(&self) -> &str {
        self.list.tested_version()
    }
    fn version(&self, d: Instant) -> Result<NonEmpty, Failed> {
        self.enter();
        self.list.version(d)
    }
    fn repository(&self, d: Instant) -> Result<Repository, Failed> {
        self.list.repository(d)
    }
    fn issues(&self, d: Instant) -> Result<Listed<IssueRow>, Failed> {
        self.list.issues(d)
    }
    fn pull_requests(&self, d: Instant) -> Result<Listed<PrRow>, Failed> {
        self.list.pull_requests(d)
    }
    fn checks(&self, n: Number, d: Instant) -> Result<Vec<Check>, Failed> {
        self.list.checks(n, d)
    }
    fn comments(&self, n: Number, d: Instant) -> Result<Vec<String>, Failed> {
        self.list.comments(n, d)
    }
    fn on_base(&self, p: &MergedPr, d: Instant) -> Result<bool, Failed> {
        self.list.on_base(p, d)
    }
}
impl GitHub for Gate {
    fn version(&self, d: Instant) -> Result<String, SourceError> {
        self.enter();
        self.detail.version(d)
    }
    fn repository(&self, d: Instant) -> Result<RepositoryAnswer, SourceError> {
        self.detail.repository(d)
    }
    fn issue(&self, n: Number, d: Instant) -> Result<IssueAnswer, SourceError> {
        self.detail.issue(n, d)
    }
    fn pull_request(&self, n: Number, d: Instant) -> Result<PrAnswer, SourceError> {
        self.detail.pull_request(n, d)
    }
    fn checks(&self, n: Number, d: Instant) -> Result<Vec<Check>, SourceError> {
        self.detail.checks(n, d)
    }
    fn verdict_comments(&self, n: Number, d: Instant) -> Result<Vec<String>, SourceError> {
        self.detail.verdict_comments(n, d)
    }
    fn on_base(&self, c: &Commit, b: &NonEmpty, d: Instant) -> Result<bool, SourceError> {
        self.detail.on_base(c, b, d)
    }
}

#[test]
fn c3_each_route_shares_only_its_in_progress_result_then_starts_a_fresh_run() {
    for (n, target) in ["/api/v1/fleets", "/api/v1/fleets/901"]
        .into_iter()
        .enumerate()
    {
        let fake = support::world_fake(&format!("c3-flight-{n}"), &World::default().spec(901, &[]));
        let room = Fake::new(&format!("c3-flight-room-{n}"), "normal");
        let gate = Gate::new(&fake);
        let _release = Release(gate.clone());
        let s = support::serve(&room, gate.sources(), Config::default());
        let addr = s.addr;
        let clients: Vec<_> = (0..4)
            .map(|_| thread::spawn(move || http::get(addr, target)))
            .collect();
        s.wait_for("four requests sharing one fleet run", |st| {
            st.attached == 4 && st.core_runs == 1
        });
        assert_eq!(gate.wait_runs(1), 1);
        gate.open();
        let replies: Vec<_> = clients.into_iter().map(|c| c.join().unwrap()).collect();
        for r in &replies {
            assert_eq!(r.status, 200, "{}", r.text());
            assert_eq!(r.body, replies[0].body);
        }
        assert_eq!(gate.runs(), 1);
        assert_eq!(s.get(target).status, 200);
        assert_eq!(gate.runs(), 2, "no result cache");
        assert!(room.invocations().is_empty());
    }
}

#[test]
fn c3_distinct_specs_use_distinct_runs_and_share_the_inventory_cap() {
    let fake = support::world_fake("c3-cap", &World::default().spec(901, &[]).spec(930, &[]));
    let room = Fake::new("c3-cap-room", "normal");
    let gate = Gate::new(&fake);
    let _release = Release(gate.clone());
    let s = support::serve(
        &room,
        gate.sources(),
        Config {
            limits: Limits {
                slot_wait: Duration::from_millis(100),
                ..Limits::default()
            },
            ..Config::default()
        },
    );
    let addr = s.addr;
    let clients: Vec<_> = ["/api/v1/fleets/901", "/api/v1/fleets/930"]
        .into_iter()
        .map(|target| thread::spawn(move || http::get(addr, target)))
        .collect();
    s.wait_for("two distinct fleet runs", |st| {
        st.core_runs == 2 && st.attached == 2
    });
    assert_eq!(gate.wait_runs(2), 2);
    for target in ["/api/v1/fleets", "/api/v1/inventory"] {
        let r = s.get(target);
        assert_eq!((r.status, r.error().0.as_str()), (503, "busy"));
        assert_eq!(r.header("Retry-After"), Some("5"));
        crate::c3_routes::headers(&r);
    }
    assert!(
        room.invocations().is_empty(),
        "refused inventory starts nothing"
    );
    assert_eq!(gate.runs(), 2, "overflow starts nothing");
    gate.open();
    for c in clients {
        assert_eq!(c.join().unwrap().status, 200);
    }
    s.wait_for("fleet runs finish", |st| st.core_runs == 0);
    assert_eq!(s.get("/api/v1/inventory").status, 200);
}

#[test]
fn c3_each_route_past_the_deadline_keeps_its_shared_slot_until_done() {
    for (n, target) in ["/api/v1/fleets", "/api/v1/fleets/901"]
        .into_iter()
        .enumerate()
    {
        let fake = support::world_fake(
            &format!("c3-deadline-{n}"),
            &World::default().spec(901, &[]),
        );
        let room = Fake::new(&format!("c3-deadline-room-{n}"), "normal");
        // The closed gate must exhaust a real request deadline. Healthy
        // recovery also needs enough time for fresh subprocess reads under
        // load (#2779); calibrate the same route on an independent gate.
        // Stay below the core's 30 s budget so 504 still leaves a held run.
        let request_deadline = crate::real_time::scaled(
            "c3_request_deadline",
            Duration::from_secs(2),
            Duration::from_secs(20),
            || {
                let calibration = support::world_fake(
                    &format!("c3-deadline-calibrate-{n}"),
                    &World::default().spec(901, &[]),
                );
                let gate = Gate::new(&calibration);
                gate.open();
                let server = support::serve(&room, gate.sources(), Config::default());
                let response = server.get(target);
                assert_eq!(response.status, 200, "{}", response.text());
            },
        );
        let gate = Gate::new(&fake);
        let _release = Release(gate.clone());
        let s = support::serve(
            &room,
            gate.sources(),
            Config {
                limits: Limits {
                    max_core_runs: 1,
                    request_deadline,
                    slot_wait: Duration::from_millis(50),
                    ..Limits::default()
                },
                ..Config::default()
            },
        );
        let started = Instant::now();
        let r = s.get(target);
        assert_eq!((r.status, r.error().0.as_str()), (504, "deadline"));
        assert!(started.elapsed() >= request_deadline);
        crate::c3_routes::headers(&r);
        assert_eq!(s.server.stats().core_runs, 1);
        assert_eq!(gate.wait_runs(1), 1);
        assert_eq!(s.get("/api/v1/inventory").status, 503);
        assert!(room.invocations().is_empty());
        gate.open();
        s.wait_for("the late core run ends", |st| st.core_runs == 0);
        let recovered = s.get(target);
        assert_eq!(recovered.status, 200, "{}", recovered.text());
        assert_eq!(gate.runs(), 2);
    }
}
