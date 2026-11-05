//! PA2/PA3/PA5: actual service engine and protected store, synthetic source owners.
use openwiz_core::{
    model::Timestamp,
    notifications::{
        boundary::{DeliveryBoundary, RecordingDelivery},
        model::*,
    },
    ops::Clock,
};
use openwiz_service::notifications::{Batch, Engine, Sources};
use openwiz_store::notifications::{Error, Observation, Store, text};
use std::{
    fs,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
    },
    time::{Duration, Instant},
};
struct Private(PathBuf);
impl Private {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "openwiz-notify-engine-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(root.join("service"))
            .unwrap();
        fs::write(root.join("service/config.json"), "{}").unwrap();
        fs::set_permissions(
            root.join("service/config.json"),
            fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        Self(root)
    }
    fn store(&self) -> Store {
        Store::new(&self.0)
    }
}
impl Drop for Private {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
struct Fixed;
impl Clock for Fixed {
    fn now(&self) -> Timestamp {
        Timestamp(100_000)
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}
fn until() -> Instant {
    Instant::now() + Duration::from_secs(5)
}
fn decision() -> Observation {
    Observation {
        fact: SourceFact::Decision(DecisionFact {
            binding: DecisionRef {
                repository: Repository::new("synthetic/factory").unwrap(),
                subject: Subject {
                    kind: SubjectKind::Issue,
                    number: 41.try_into().unwrap(),
                },
                comment_id: 51.try_into().unwrap(),
                request_id: RequestId::new("request-1").unwrap(),
                fingerprint: Fingerprint::new("a".repeat(64)).unwrap(),
            },
            state: RequestState::Open,
            current: Fact::Known(true),
            risk: Risk::Ordinary,
            coverage: Coverage {
                state: CoverageState::Complete,
                gaps: vec![],
            },
            freshness: Freshness {
                state: FreshnessState::Fresh,
                snapshot_at: Fact::Known(100_000),
            },
        }),
        content_binding: Fingerprint::new("b".repeat(64)).unwrap(),
    }
}
struct Reader(Mutex<Vec<Observation>>);
impl Sources for Reader {
    fn read(&self, _: Instant) -> Result<Batch, Error> {
        let observations = self.0.lock().unwrap().clone();
        Ok(Batch {
            observations: observations.clone(),
            sources: Category::ALL
                .into_iter()
                .map(|category| CategoryStatus {
                    category,
                    available: Fact::Known(observations.iter().any(|o| {
                        openwiz_core::notifications::policy::category(&o.fact) == category
                    })),
                    reason: text("Synthetic source availability; no installed intake claim"),
                })
                .collect(),
            coverage: Coverage {
                state: CoverageState::Complete,
                gaps: vec![],
            },
            freshness: Freshness {
                state: FreshnessState::Fresh,
                snapshot_at: Fact::Known(100_000),
            },
        })
    }
    fn recheck(&self, original: &Observation, _: Instant) -> Result<Observation, Error> {
        let rows = self.0.lock().unwrap();
        let found: Vec<_> = rows
            .iter()
            .filter(|o| {
                openwiz_core::notifications::grouping::key(&o.fact)
                    == openwiz_core::notifications::grouping::key(&original.fact)
            })
            .collect();
        if found.is_empty() || found.iter().any(|o| *o != found[0]) {
            return Err(Error::Unavailable);
        }
        Ok(found[0].clone())
    }
}
// Only the fixture implements ready capability. T1's recording boundary still
// reports unavailable, and the production constructor uses UnavailableDelivery.
struct Delivery(Arc<Mutex<RecordingDelivery>>);
impl DeliveryBoundary for Delivery {
    fn capability(&self) -> Capability {
        Capability {
            state: CapabilityState::Ready,
            permission: Permission::Granted,
            reason: text("Synthetic prerequisites verified"),
            next: text("Recording acceptance is not phone receipt"),
        }
    }
    fn submit(&mut self, s: &Submission) -> DeliveryOutcome {
        self.0.lock().unwrap().submit(s)
    }
}
fn enable(store: &Store) {
    store
        .write_preferences(
            &PreferenceWrite {
                operation_id: OperationId::new("1".repeat(32)).unwrap(),
                expected_generation: 0,
                enabled: true,
                categories: Toggles::defaults(),
            },
            100_000,
        )
        .unwrap();
    store
        .write_subscription(
            &SubscriptionWrite {
                operation_id: OperationId::new("2".repeat(32)).unwrap(),
                expected_generation: 0,
                binding_id: Id::new("synthetic-binding").unwrap(),
            },
            false,
            100_000,
            |_| true,
        )
        .unwrap();
}
#[test]
fn enabled_source_engine_journal_and_restart_have_one_recorded_effect() {
    let private = Private::new();
    let store = private.store();
    store.initialize().unwrap();
    let reader = Arc::new(Reader(Mutex::new(vec![decision()])));
    let delivery = Arc::new(Mutex::new(RecordingDelivery::new(vec![DeliveryOutcome {
        state: OutcomeState::Accepted,
        reason: text("Synthetic acceptance"),
    }])));
    let engine = Engine::new(
        store.clone(),
        reader.clone(),
        Box::new(Delivery(delivery.clone())),
        Arc::new(Fixed),
        Arc::new(|id, _| id.as_str() == "synthetic-binding"),
    );
    engine.run(until()).unwrap();
    assert_eq!(delivery.lock().unwrap().submissions().len(), 0);
    enable(&store);
    engine.run(until()).unwrap();
    assert_eq!(
        delivery.lock().unwrap().submissions().len(),
        1,
        "one durable effect after opt-in"
    );
    let first = store.read().unwrap().latest().unwrap();
    assert_eq!(first.state, DispatchState::Accepted);
    let token = &first.submission.payload.target_token;
    assert!(store.target(token).unwrap() == Some(decision()));
    engine.run(until()).unwrap();
    let restarted = Engine::new(
        private.store(),
        reader,
        Box::new(Delivery(delivery.clone())),
        Arc::new(Fixed),
        Arc::new(|id, _| id.as_str() == "synthetic-binding"),
    );
    restarted.run(until()).unwrap();
    assert_eq!(delivery.lock().unwrap().submissions().len(), 1);
    assert_eq!(store.read().unwrap().latest(), Some(first));
}

use openwiz_core::{model::SessionId, source::*};
struct NoRoom;
impl SessionSource for NoRoom {
    fn name(&self) -> &str {
        "synthetic refusing source"
    }
    fn tested_version(&self) -> &str {
        "synthetic"
    }
    fn version(&self, _: Instant) -> Result<String, SourceError> {
        panic!("notification API must not read CloudRoom")
    }
    fn list_sessions(
        &self,
        _: SessionScope,
        _: Instant,
    ) -> Result<Rows<SessionRecord>, SourceError> {
        panic!("unexpected CloudRoom read")
    }
    fn list_projects(&self, _: bool, _: Instant) -> Result<Rows<ProjectRecord>, SourceError> {
        panic!("unexpected CloudRoom read")
    }
    fn list_machines(&self, _: Instant) -> Result<Rows<MachineRecord>, SourceError> {
        panic!("unexpected CloudRoom read")
    }
    fn session_detail(
        &self,
        _: &SessionId,
        _: Instant,
    ) -> Result<SessionDetailRecord, SourceError> {
        panic!("unexpected CloudRoom read")
    }
    fn session_output(&self, _: &SessionId, _: Instant) -> Result<OutputRecord, SourceError> {
        panic!("unexpected CloudRoom read")
    }
}
fn http(
    server: &openwiz_server::Server,
    method: &str,
    path: &str,
    body: &str,
    headers: &str,
) -> (u16, String, String) {
    http_host(server, method, path, body, headers, "synthetic.invalid")
}
fn http_host(
    server: &openwiz_server::Server,
    method: &str,
    path: &str,
    body: &str,
    headers: &str,
    host: &str,
) -> (u16, String, String) {
    use std::{
        io::{Read, Write},
        net::{Shutdown, TcpStream},
    };
    let mut stream = TcpStream::connect(server.local_addr()).unwrap();
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    write!(
        stream,
        "{method} {path} HTTP/1.1\r\nHost: {host}\r\nContent-Length: {}\r\n{headers}\r\n{body}",
        body.len()
    )
    .unwrap();
    stream.shutdown(Shutdown::Write).unwrap();
    let mut raw = String::new();
    stream.read_to_string(&mut raw).unwrap();
    let (head, body) = raw.split_once("\r\n\r\n").unwrap();
    (
        head.split_whitespace().nth(1).unwrap().parse().unwrap(),
        head.to_owned(),
        body.to_owned(),
    )
}
const GUARDS: &str = "Origin: https://synthetic.invalid\r\nSec-Fetch-Site: same-origin\r\nX-OpenWiz-Send: 1\r\nContent-Type: application/json\r\n";
fn serve(engine: Arc<Engine>) -> openwiz_server::Server {
    openwiz_service::start_notification_api(
        openwiz_server::bind(0).unwrap(),
        openwiz_server::Config {
            allowed_host: Some("synthetic.invalid".into()),
            ..Default::default()
        },
        Arc::new(NoRoom),
        Arc::new(Fixed),
        Arc::new(|_| {}),
        engine,
    )
    .unwrap()
}
#[test]
fn installed_api_persists_preferences_with_guards_and_no_work_effects() {
    let private = Private::new();
    let store = private.store();
    store.initialize().unwrap();
    let engine = Arc::new(Engine::unavailable(store.clone(), Arc::new(Fixed)));
    let server = serve(engine);
    let (status, _, raw) = http(&server, "GET", "/api/v1/notifications/preferences", "", "");
    assert_eq!(
        status, 200,
        "installed API must expose durable preferences: {raw}"
    );
    assert_eq!(
        serde_json::from_str::<Document>(&raw).unwrap().record,
        Record::Preferences(Preferences::off())
    );
    let request =
        openwiz_store::notifications::document(Record::PreferenceWrite(PreferenceWrite {
            operation_id: OperationId::new("c".repeat(32)).unwrap(),
            expected_generation: 0,
            enabled: true,
            categories: Toggles::defaults(),
        }));
    let body = serde_json::to_string(&request).unwrap();
    assert_eq!(
        http(
            &server,
            "PUT",
            "/api/v1/notifications/preferences",
            &body,
            ""
        )
        .0,
        403
    );
    assert!(!store.preferences().unwrap().enabled);
    let (status, _, result) = http(
        &server,
        "PUT",
        "/api/v1/notifications/preferences",
        &body,
        GUARDS,
    );
    assert_eq!(status, 200, "{result}");
    assert!(store.preferences().unwrap().enabled);
    let (status, _, raw) = http(&server, "GET", "/api/v1/notifications/status", "", "");
    assert_eq!(status, 200);
    let document = serde_json::from_str::<Document>(&raw).unwrap();
    document.check().unwrap();
    let Record::Status(status) = document.record else {
        panic!("expected status");
    };
    assert_eq!(status.state, StatusState::Unavailable);
    assert_eq!(status.capability.state, CapabilityState::Unavailable);
    assert!(status.latest.is_none());
    assert_eq!(
        http(&server, "GET", "/api/v1/notifications/preferences?", "", "").0,
        400
    );
    let (code, head, body) = http(&server, "HEAD", "/api/v1/notifications/preferences", "", "");
    assert_eq!(code, 405);
    assert!(head.contains("Allow: GET, PUT"));
    assert!(body.is_empty());
    assert!(!head.to_ascii_lowercase().contains("content-length"));
}

#[test]
fn changed_saved_content_under_same_proposal_never_becomes_an_alert() {
    let private = Private::new();
    let store = private.store();
    store.initialize().unwrap();
    let mut baseline = decision();
    if let SourceFact::Decision(d) = &mut baseline.fact {
        d.freshness.snapshot_at = Fact::Known(99_999);
    }
    let reader = Arc::new(Reader(Mutex::new(vec![baseline])));
    let delivery = Arc::new(Mutex::new(RecordingDelivery::new(vec![])));
    let engine = Engine::new(
        store.clone(),
        reader.clone(),
        Box::new(Delivery(delivery.clone())),
        Arc::new(Fixed),
        Arc::new(|_, _| true),
    );
    engine.run(until()).unwrap(); // baseline observed before enable
    let mut changed = decision();
    changed.content_binding = Fingerprint::new("d".repeat(64)).unwrap();
    if let SourceFact::Decision(d) = &mut changed.fact {
        d.risk = Risk::Live;
    }
    *reader.0.lock().unwrap() = vec![changed];
    enable(&store);
    engine.run(until()).unwrap();
    assert_eq!(
        delivery.lock().unwrap().submissions().len(),
        0,
        "saved wording/risk/target mutation cannot acquire fresh authority under an old fingerprint"
    );
}

fn build(
    private: &Private,
    reader: Arc<dyn Sources>,
    delivery: Arc<Mutex<RecordingDelivery>>,
) -> Engine {
    Engine::new(
        private.store(),
        reader,
        Box::new(Delivery(delivery)),
        Arc::new(Fixed),
        Arc::new(|_, _| true),
    )
}
#[test]
fn every_boundary_outcome_stays_distinct_without_resend_or_private_diagnostics() {
    for (outcome, expected) in [
        (OutcomeState::Pending, DispatchState::Pending),
        (OutcomeState::Accepted, DispatchState::Accepted),
        (OutcomeState::Failed, DispatchState::Failed),
        (OutcomeState::Uncertain, DispatchState::Uncertain),
    ] {
        let private = Private::new();
        let store = private.store();
        store.initialize().unwrap();
        enable(&store);
        let reader = Arc::new(Reader(Mutex::new(vec![decision()])));
        let delivery = Arc::new(Mutex::new(RecordingDelivery::new(vec![DeliveryOutcome {
            state: outcome,
            reason: text("SYNTHETIC_PRIVATE provider endpoint/key/decision wording"),
        }])));
        build(&private, reader.clone(), delivery.clone())
            .run(until())
            .unwrap();
        assert_eq!(store.read().unwrap().latest().unwrap().state, expected);
        build(&private, reader, delivery.clone())
            .run(until())
            .unwrap();
        assert_eq!(store.read().unwrap().latest().unwrap().state, expected);
        assert_eq!(delivery.lock().unwrap().submissions().len(), 1);
        assert!(
            !fs::read_to_string(private.0.join("service/notifications/state.json"))
                .unwrap()
                .contains("SYNTHETIC_PRIVATE")
        );
        let server = serve(Arc::new(Engine::unavailable(store, Arc::new(Fixed))));
        let (_, _, body) = http(&server, "GET", "/api/v1/notifications/status", "", "");
        assert!(!body.contains("SYNTHETIC_PRIVATE"));
        let document: Document = serde_json::from_str(&body).unwrap();
        let Record::Status(s) = document.record else {
            panic!("status expected");
        };
        assert_eq!(s.latest.unwrap().state, expected);
    }
}
#[test]
fn two_concurrent_passes_duplicate_and_restarted_observations_have_one_dispatch() {
    let private = Private::new();
    private.store().initialize().unwrap();
    enable(&private.store());
    let reader = Arc::new(Reader(Mutex::new(vec![decision()])));
    let delivery = Arc::new(Mutex::new(RecordingDelivery::new(vec![])));
    let a = build(&private, reader.clone(), delivery.clone());
    let b = build(&private, reader.clone(), delivery.clone());
    let barrier = Arc::new(std::sync::Barrier::new(2));
    std::thread::scope(|scope| {
        let one = barrier.clone();
        let first = scope.spawn(move || {
            one.wait();
            a.run(until())
        });
        let two = barrier.clone();
        let second = scope.spawn(move || {
            two.wait();
            b.run(until())
        });
        for result in [first.join().unwrap(), second.join().unwrap()] {
            assert!(result.is_ok() || result == Err(Error::Busy));
        }
    });
    build(&private, reader, delivery.clone())
        .run(until())
        .unwrap();
    assert_eq!(delivery.lock().unwrap().submissions().len(), 1);
    assert_eq!(private.store().read().unwrap().groups.len(), 1);
}
#[test]
fn closed_group_survives_late_open_and_a_new_proposal_is_distinct() {
    let private = Private::new();
    let store = private.store();
    store.initialize().unwrap();
    enable(&store);
    let reader = Arc::new(Reader(Mutex::new(vec![decision()])));
    let delivery = Arc::new(Mutex::new(RecordingDelivery::new(vec![])));
    let engine = build(&private, reader.clone(), delivery.clone());
    engine.run(until()).unwrap();
    let mut closed = decision();
    if let SourceFact::Decision(d) = &mut closed.fact {
        d.state = RequestState::Resolved;
    }
    *reader.0.lock().unwrap() = vec![closed];
    engine.run(until()).unwrap();
    let mut late = decision();
    if let SourceFact::Decision(d) = &mut late.fact {
        d.freshness.snapshot_at = Fact::Known(99_000);
    }
    *reader.0.lock().unwrap() = vec![late];
    engine.run(until()).unwrap();
    assert!(store.read().unwrap().groups[0].closed);
    let mut new = decision();
    if let SourceFact::Decision(d) = &mut new.fact {
        d.binding.fingerprint = Fingerprint::new("e".repeat(64)).unwrap();
    }
    *reader.0.lock().unwrap() = vec![new];
    engine.run(until()).unwrap();
    assert_eq!(delivery.lock().unwrap().submissions().len(), 2);
    assert_eq!(store.read().unwrap().groups.len(), 2);
}
struct Recheck {
    inner: Arc<Reader>,
    mode: u8,
}
impl Sources for Recheck {
    fn read(&self, deadline: Instant) -> Result<Batch, Error> {
        self.inner.read(deadline)
    }
    fn recheck(&self, original: &Observation, deadline: Instant) -> Result<Observation, Error> {
        if self.mode == 0 {
            return Err(Error::Unavailable);
        }
        let mut current = self.inner.recheck(original, deadline)?;
        match self.mode {
            1 => current.content_binding = Fingerprint::new("c".repeat(64)).unwrap(),
            2 => {
                if let SourceFact::Decision(d) = &mut current.fact {
                    d.risk = Risk::Publish;
                }
            }
            3 => {
                if let SourceFact::Decision(d) = &mut current.fact {
                    d.state = RequestState::Resolved;
                }
            }
            _ => {
                if let SourceFact::Decision(d) = &mut current.fact {
                    d.current = Fact::Known(false);
                }
            }
        }
        Ok(current)
    }
}
#[test]
fn immediate_independent_recheck_refuses_unread_changed_resolved_or_noncurrent() {
    for mode in 0..5 {
        let private = Private::new();
        let store = private.store();
        store.initialize().unwrap();
        enable(&store);
        let reader = Arc::new(Recheck {
            inner: Arc::new(Reader(Mutex::new(vec![decision()]))),
            mode,
        });
        let delivery = Arc::new(Mutex::new(RecordingDelivery::new(vec![])));
        build(&private, reader, delivery.clone())
            .run(until())
            .unwrap();
        assert_eq!(
            delivery.lock().unwrap().submissions().len(),
            0,
            "recheck case {mode}"
        );
        assert_eq!(
            store.read().unwrap().latest().unwrap().state,
            DispatchState::Cancelled
        );
    }
}
#[test]
fn subscription_revoked_between_reservation_and_submit_cancels_with_no_effect() {
    let private = Private::new();
    let store = private.store();
    store.initialize().unwrap();
    enable(&store);
    let delivery = Arc::new(Mutex::new(RecordingDelivery::new(vec![])));
    let checks = Arc::new(AtomicU64::new(0));
    let calls = checks.clone();
    let engine = Engine::new(
        store.clone(),
        Arc::new(Reader(Mutex::new(vec![decision()]))),
        Box::new(Delivery(delivery.clone())),
        Arc::new(Fixed),
        Arc::new(move |_, _| calls.fetch_add(1, Ordering::SeqCst) == 0),
    );
    engine.run(until()).unwrap();
    assert_eq!(delivery.lock().unwrap().submissions().len(), 0);
    assert_eq!(
        store.read().unwrap().latest().unwrap().state,
        DispatchState::Cancelled
    );
}

struct CrashReader {
    inner: Reader,
    mode: String,
}
impl Sources for CrashReader {
    fn read(&self, deadline: Instant) -> Result<Batch, Error> {
        if self.mode == "before_reserve" {
            std::process::exit(23);
        }
        self.inner.read(deadline)
    }
    fn recheck(&self, original: &Observation, deadline: Instant) -> Result<Observation, Error> {
        if self.mode == "reserved" {
            std::process::exit(23);
        }
        self.inner.recheck(original, deadline)
    }
}
struct CrashDelivery {
    root: PathBuf,
    mode: String,
}
impl DeliveryBoundary for CrashDelivery {
    fn capability(&self) -> Capability {
        Delivery(Arc::new(Mutex::new(RecordingDelivery::new(vec![])))).capability()
    }
    fn submit(&mut self, _: &Submission) -> DeliveryOutcome {
        use std::{fs::OpenOptions, io::Write, os::unix::fs::OpenOptionsExt};
        if self.mode == "submitting" {
            std::process::exit(23);
        }
        let mut effect = OpenOptions::new()
            .append(true)
            .create(true)
            .mode(0o600)
            .open(self.root.join("synthetic-provider-effects"))
            .unwrap();
        effect.write_all(b"one synthetic submission\n").unwrap();
        effect.sync_all().unwrap();
        if self.mode == "submitted" {
            std::process::exit(23);
        }
        if self.mode == "outcome_save" {
            fs::set_permissions(
                self.root.join("service/notifications/state.json"),
                fs::Permissions::from_mode(0o644),
            )
            .unwrap();
        }
        DeliveryOutcome {
            state: OutcomeState::Accepted,
            reason: text("Synthetic accepted dispatch, no phone observation"),
        }
    }
}
// This is only a test-binary subprocess entry, never a production environment seam.
#[test]
fn notification_crash_child() {
    let Some(root) = std::env::var_os("OPENWIZ_NOTIFICATION_CRASH_ROOT") else {
        return;
    };
    let mode = std::env::var("OPENWIZ_NOTIFICATION_CRASH_POINT").unwrap();
    let root = PathBuf::from(root);
    let engine = Engine::new(
        Store::new(&root),
        Arc::new(CrashReader {
            inner: Reader(Mutex::new(vec![decision()])),
            mode: mode.clone(),
        }),
        Box::new(CrashDelivery {
            root,
            mode: mode.clone(),
        }),
        Arc::new(Fixed),
        Arc::new(|_, _| true),
    );
    let result = engine.run(until());
    if mode == "outcome_save" {
        assert_eq!(result, Err(Error::Unavailable));
        std::process::exit(24);
    }
    result.unwrap();
    std::process::exit(23);
}
#[test]
fn process_crashes_before_and_after_every_effect_boundary_never_blindly_resend() {
    for (point, state, resume, prior) in [
        ("before_reserve", None, 1, 0),
        ("reserved", Some(DispatchState::Reserved), 1, 0),
        ("submitting", Some(DispatchState::Uncertain), 0, 0),
        ("submitted", Some(DispatchState::Uncertain), 0, 1),
        ("outcome_save", Some(DispatchState::Uncertain), 0, 1),
        ("settled", Some(DispatchState::Accepted), 0, 1),
    ] {
        let private = Private::new();
        let store = private.store();
        store.initialize().unwrap();
        enable(&store);
        let status = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "notification_crash_child", "--nocapture"])
            .env("OPENWIZ_NOTIFICATION_CRASH_ROOT", &private.0)
            .env("OPENWIZ_NOTIFICATION_CRASH_POINT", point)
            .output()
            .unwrap()
            .status;
        assert_eq!(
            status.code(),
            Some(if point == "outcome_save" { 24 } else { 23 }),
            "crash point {point}"
        );
        fs::set_permissions(
            private.0.join("service/notifications/state.json"),
            fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        assert_eq!(
            store.read().unwrap().latest().map(|d| d.state),
            state,
            "crash point {point}"
        );
        let calls =
            fs::read_to_string(private.0.join("synthetic-provider-effects")).unwrap_or_default();
        assert_eq!(calls.lines().count(), prior);
        let delivery = Arc::new(Mutex::new(RecordingDelivery::new(vec![])));
        build(
            &private,
            Arc::new(Reader(Mutex::new(vec![decision()]))),
            delivery.clone(),
        )
        .run(until())
        .unwrap();
        assert_eq!(
            delivery.lock().unwrap().submissions().len(),
            resume,
            "crash point {point}"
        );
    }
}

#[test]
fn actual_api_opt_in_subscription_dispatch_disable_and_restart_share_one_store() {
    let private = Private::new();
    let store = private.store();
    store.initialize().unwrap();
    let delivery = Arc::new(Mutex::new(RecordingDelivery::new(vec![DeliveryOutcome {
        state: OutcomeState::Accepted,
        reason: text("Synthetic acceptance only"),
    }])));
    let reader = Arc::new(Reader(Mutex::new(vec![decision()])));
    let engine = Arc::new(build(&private, reader.clone(), delivery.clone()));
    let server = serve(engine.clone());
    engine.run(until()).unwrap();
    assert_eq!(delivery.lock().unwrap().submissions().len(), 0);
    let request =
        openwiz_store::notifications::document(Record::PreferenceWrite(PreferenceWrite {
            operation_id: OperationId::new("c".repeat(32)).unwrap(),
            expected_generation: 0,
            enabled: true,
            categories: Toggles::defaults(),
        }));
    let body = serde_json::to_string(&request).unwrap();
    let first = http(
        &server,
        "PUT",
        "/api/v1/notifications/preferences",
        &body,
        GUARDS,
    );
    assert_eq!(first.0, 200);
    assert_eq!(
        http(
            &server,
            "PUT",
            "/api/v1/notifications/preferences",
            &body,
            GUARDS
        )
        .2,
        first.2
    );
    let mut subscription = SubscriptionWrite {
        operation_id: OperationId::new("d".repeat(32)).unwrap(),
        expected_generation: 0,
        binding_id: Id::new("synthetic-binding").unwrap(),
    };
    let body = serde_json::to_string(&openwiz_store::notifications::document(
        Record::SubscriptionWrite(subscription.clone()),
    ))
    .unwrap();
    assert_eq!(
        http(
            &server,
            "PUT",
            "/api/v1/notifications/subscription",
            &body,
            GUARDS
        )
        .0,
        200
    );
    engine.run(until()).unwrap();
    let (code, headers, raw) = http(&server, "GET", "/api/v1/notifications/status", "", "");
    assert_eq!(code, 200);
    let document: Document = serde_json::from_str(&raw).unwrap();
    document.check().unwrap();
    let Record::Status(status) = document.record else {
        panic!("status expected");
    };
    assert_eq!(status.state, StatusState::Accepted);
    assert_eq!(status.latest.unwrap().state, DispatchState::Accepted);
    assert!(raw.contains("phone receipt is unverified"));
    let headers = headers.to_ascii_lowercase();
    assert!(headers.contains("cache-control: no-store"));
    assert!(headers.contains("x-content-type-options: nosniff"));
    assert!(!headers.contains("set-cookie"));
    assert!(!headers.contains("access-control-allow-origin"));
    subscription.expected_generation = 1;
    subscription.operation_id = OperationId::new("e".repeat(32)).unwrap();
    let body = serde_json::to_string(&openwiz_store::notifications::document(
        Record::SubscriptionWrite(subscription),
    ))
    .unwrap();
    assert_eq!(
        http(
            &server,
            "DELETE",
            "/api/v1/notifications/subscription",
            &body,
            GUARDS
        )
        .0,
        200
    );
    let mut off = match request.record {
        Record::PreferenceWrite(w) => w,
        _ => unreachable!(),
    };
    off.expected_generation = 1;
    off.operation_id = OperationId::new("f".repeat(32)).unwrap();
    off.enabled = false;
    let body = serde_json::to_string(&openwiz_store::notifications::document(
        Record::PreferenceWrite(off),
    ))
    .unwrap();
    assert_eq!(
        http(
            &server,
            "PUT",
            "/api/v1/notifications/preferences",
            &body,
            GUARDS
        )
        .0,
        200
    );
    let (_, _, raw) = http(&server, "GET", "/api/v1/notifications/status", "", "");
    assert!(raw.contains("already submitted effects cannot be retracted"));
    let Record::Status(status) = serde_json::from_str::<Document>(&raw).unwrap().record else {
        panic!("status expected");
    };
    assert_eq!(status.state, StatusState::Off);
    assert_eq!(status.latest.unwrap().state, DispatchState::Accepted);
    build(&private, reader, delivery.clone())
        .run(until())
        .unwrap();
    assert_eq!(delivery.lock().unwrap().submissions().len(), 1);
}
#[test]
fn strict_http_write_shapes_methods_origins_and_generation_conflicts_fail_closed() {
    let private = Private::new();
    let store = private.store();
    store.initialize().unwrap();
    let server = serve(Arc::new(Engine::unavailable(
        store.clone(),
        Arc::new(Fixed),
    )));
    let request =
        openwiz_store::notifications::document(Record::PreferenceWrite(PreferenceWrite {
            operation_id: OperationId::new("c".repeat(32)).unwrap(),
            expected_generation: 0,
            enabled: true,
            categories: Toggles::defaults(),
        }));
    let valid = serde_json::to_string(&request).unwrap();
    for bad in [
        "[]".to_owned(),
        "{}".to_owned(),
        valid.replacen(
            "\"expected_generation\":0",
            "\"expected_generation\":0.0",
            1,
        ),
        valid.replacen("\"enabled\":true", "\"enabled\":true,\"enabled\":false", 1),
        valid.replacen("\"decision\":true", "\"decision\":true,\"secret\":false", 1),
        valid.replace("openwiz.notifications.v1", "openwiz.notifications.v9"),
        valid.replacen("\"loop_missed\":false,", "", 1),
        valid.clone() + "{}",
    ] {
        let response = http(
            &server,
            "PUT",
            "/api/v1/notifications/preferences",
            &bad,
            GUARDS,
        );
        assert_eq!(response.0, 400, "strict body refusal: {}", response.2);
    }
    for (method, path, body, headers, expected) in [
        ("GET", "/api/v1/notifications/preferences", "{}", "", 400),
        (
            "PUT",
            "/api/v1/notifications/preferences?",
            valid.as_str(),
            GUARDS,
            400,
        ),
        (
            "PUT",
            "/api/v1/notifications/preferences",
            valid.as_str(),
            "Origin: https://foreign.invalid\r\nSec-Fetch-Site: same-origin\r\nX-OpenWiz-Send: 1\r\nContent-Type: application/json\r\n",
            403,
        ),
        (
            "PUT",
            "/api/v1/notifications/preferences",
            valid.as_str(),
            "Origin: https://synthetic.invalid\r\nSec-Fetch-Site: same-origin\r\nContent-Type: application/json\r\n",
            403,
        ),
        (
            "PUT",
            "/api/v1/notifications/preferences",
            valid.as_str(),
            "Origin: https://synthetic.invalid\r\nSec-Fetch-Site: same-origin\r\nX-OpenWiz-Send: 1\r\nContent-Type: text/plain\r\n",
            415,
        ),
        (
            "POST",
            "/api/v1/notifications/preferences",
            valid.as_str(),
            GUARDS,
            405,
        ),
        (
            "PUT",
            "/api/v1/notifications/status",
            valid.as_str(),
            GUARDS,
            405,
        ),
        (
            "PUT",
            "/api/v1/notifications/subscription",
            valid.as_str(),
            GUARDS,
            400,
        ),
    ] {
        assert_eq!(http(&server, method, path, body, headers).0, expected);
    }
    let loopback = format!("127.0.0.1:{}", server.local_addr().port());
    assert_eq!(
        http_host(
            &server,
            "PUT",
            "/api/v1/notifications/preferences",
            &valid,
            GUARDS,
            &loopback
        )
        .0,
        421
    );
    assert_eq!(
        http(
            &server,
            "PUT",
            "/api/v1/notifications/preferences",
            &valid,
            &format!("Host: synthetic.invalid\r\n{GUARDS}")
        )
        .0,
        400
    );
    assert_eq!(store.preferences().unwrap().generation, 0);
    assert_eq!(
        http(
            &server,
            "PUT",
            "/api/v1/notifications/preferences",
            &valid,
            GUARDS
        )
        .0,
        200
    );
    let conflict = valid.replace("\"enabled\":true", "\"enabled\":false");
    let r = http(
        &server,
        "PUT",
        "/api/v1/notifications/preferences",
        &conflict,
        GUARDS,
    );
    assert_eq!(r.0, 409);
    assert!(r.2.contains("operation_conflict"));
    let stale = valid.replace(&"c".repeat(32), &"d".repeat(32));
    let r = http(
        &server,
        "PUT",
        "/api/v1/notifications/preferences",
        &stale,
        GUARDS,
    );
    assert_eq!(r.0, 409);
    assert!(r.2.contains("generation_conflict"));
    let sub =
        openwiz_store::notifications::document(Record::SubscriptionWrite(SubscriptionWrite {
            operation_id: OperationId::new("a".repeat(32)).unwrap(),
            expected_generation: 0,
            binding_id: Id::new("missing-binding").unwrap(),
        }));
    let r = http(
        &server,
        "PUT",
        "/api/v1/notifications/subscription",
        &serde_json::to_string(&sub).unwrap(),
        GUARDS,
    );
    assert_eq!(r.0, 409);
    assert!(r.2.contains("subscription_unavailable"));
}
struct HeldDelivery {
    entered: std::sync::mpsc::Sender<()>,
    release: std::sync::mpsc::Receiver<()>,
}
impl DeliveryBoundary for HeldDelivery {
    fn capability(&self) -> Capability {
        Delivery(Arc::new(Mutex::new(RecordingDelivery::new(vec![])))).capability()
    }
    fn submit(&mut self, _: &Submission) -> DeliveryOutcome {
        self.entered.send(()).unwrap();
        self.release.recv_timeout(Duration::from_secs(5)).unwrap();
        DeliveryOutcome {
            state: OutcomeState::Accepted,
            reason: text("Synthetic accepted"),
        }
    }
}
#[test]
fn disable_cannot_overtake_admitted_submission_and_retains_its_outcome() {
    let private = Private::new();
    let store = private.store();
    store.initialize().unwrap();
    enable(&store);
    let (entered_tx, entered_rx) = std::sync::mpsc::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let engine = Arc::new(Engine::new(
        store.clone(),
        Arc::new(Reader(Mutex::new(vec![decision()]))),
        Box::new(HeldDelivery {
            entered: entered_tx,
            release: release_rx,
        }),
        Arc::new(Fixed),
        Arc::new(|_, _| true),
    ));
    let running = engine.clone();
    let worker = std::thread::spawn(move || running.run(until()));
    entered_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    let off = PreferenceWrite {
        operation_id: OperationId::new("c".repeat(32)).unwrap(),
        expected_generation: 1,
        enabled: false,
        categories: Toggles::defaults(),
    };
    assert_eq!(store.write_preferences(&off, 100_000), Err(Error::Busy));
    let server = serve(engine.clone());
    let body = serde_json::to_string(&openwiz_store::notifications::document(
        Record::PreferenceWrite(off),
    ))
    .unwrap();
    std::thread::scope(|scope| {
        let pending = scope.spawn(|| {
            http(
                &server,
                "PUT",
                "/api/v1/notifications/preferences",
                &body,
                GUARDS,
            )
        });
        release_tx.send(()).unwrap();
        worker.join().unwrap().unwrap();
        assert_eq!(pending.join().unwrap().0, 200);
    });
    assert!(!store.preferences().unwrap().enabled);
    assert_eq!(store.preferences().unwrap().generation, 2);
    assert_eq!(
        store.read().unwrap().latest().unwrap().state,
        DispatchState::Accepted
    );
    engine.run(until()).unwrap();
    assert_eq!(store.read().unwrap().groups.len(), 1);
}

#[test]
fn notification_reads_share_core_slots_and_deadlines_and_do_not_write_state() {
    use std::sync::mpsc;
    let private = Private::new();
    let store = private.store();
    store.initialize().unwrap();
    enable(&store);
    let before = fs::read(private.0.join("service/notifications/state.json")).unwrap();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release_rx = Mutex::new(release_rx);
    let (done_tx, done_rx) = mpsc::channel();
    let engine = Arc::new(Engine::new(
        store.clone(),
        Arc::new(Reader(Mutex::new(vec![]))),
        Box::new(Delivery(Arc::new(Mutex::new(RecordingDelivery::new(
            vec![],
        ))))),
        Arc::new(Fixed),
        Arc::new(move |_, _| {
            entered_tx.send(()).unwrap();
            release_rx
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(5))
                .unwrap();
            done_tx.send(()).unwrap();
            true
        }),
    ));
    let config = openwiz_server::Config {
        allowed_host: Some("synthetic.invalid".into()),
        limits: openwiz_server::Limits {
            max_core_runs: 1,
            slot_wait: Duration::from_millis(10),
            request_deadline: Duration::from_millis(150),
            ..Default::default()
        },
        ..Default::default()
    };
    let server = openwiz_service::start_notification_api(
        openwiz_server::bind(0).unwrap(),
        config,
        Arc::new(NoRoom),
        Arc::new(Fixed),
        Arc::new(|_| {}),
        engine,
    )
    .unwrap();
    std::thread::scope(|scope| {
        let pending = scope.spawn(|| http(&server, "GET", "/api/v1/notifications/status", "", ""));
        entered_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        let (status, headers, _) =
            http(&server, "GET", "/api/v1/notifications/preferences", "", "");
        assert_eq!(status, 503);
        assert!(headers.contains("Retry-After"));
        assert_eq!(pending.join().unwrap().0, 504);
        release_tx.send(()).unwrap();
        done_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    });
    assert_eq!(
        fs::read(private.0.join("service/notifications/state.json")).unwrap(),
        before
    );
}

#[test]
fn repeated_facts_are_one_group_and_copied_comments_are_ambiguous() {
    for ambiguous in [false, true] {
        let private = Private::new();
        let store = private.store();
        store.initialize().unwrap();
        enable(&store);
        let original = decision();
        let mut copy = original.clone();
        if ambiguous && let SourceFact::Decision(d) = &mut copy.fact {
            d.binding.comment_id = 52.try_into().unwrap();
        }
        let reader = Arc::new(Reader(Mutex::new(vec![original, copy])));
        let delivery = Arc::new(Mutex::new(RecordingDelivery::new(vec![])));
        build(&private, reader, delivery.clone())
            .run(until())
            .unwrap();
        assert_eq!(
            delivery.lock().unwrap().submissions().len(),
            if ambiguous { 0 } else { 1 }
        );
        assert_eq!(store.read().unwrap().groups.len(), 1);
        if ambiguous {
            assert_eq!(
                store.read().unwrap().coverage.state,
                CoverageState::Partial,
                "refused ambiguity must remain visible, not vanish from status"
            );
        }
    }
}
fn incident(owner: &str, id: &str, state: IncidentState) -> Observation {
    Observation {
        fact: SourceFact::Incident(IncidentFact {
            binding: IncidentRef {
                repository: Repository::new("synthetic/factory").unwrap(),
                owner: Id::new(owner).unwrap(),
                source: RecoverySource::ServiceHealth,
                subject: Id::new("health-check").unwrap(),
                incident: Id::new(id).unwrap(),
            },
            state,
            owner_escalated: Fact::Known(true),
            coverage: Coverage {
                state: CoverageState::Complete,
                gaps: vec![],
            },
            freshness: Freshness {
                state: FreshnessState::Fresh,
                snapshot_at: Fact::Known(100_000),
            },
        }),
        content_binding: Fingerprint::new("a".repeat(64)).unwrap(),
    }
}
#[test]
fn recovery_closes_an_incident_and_owner_or_incident_changes_are_distinct() {
    let private = Private::new();
    let store = private.store();
    store.initialize().unwrap();
    enable(&store);
    let mut repairing = incident("owner-1", "incident-1", IncidentState::Repairing);
    if let SourceFact::Incident(i) = &mut repairing.fact {
        i.freshness.snapshot_at = Fact::Known(99_999);
    }
    let reader = Arc::new(Reader(Mutex::new(vec![repairing])));
    let delivery = Arc::new(Mutex::new(RecordingDelivery::new(vec![])));
    let engine = build(&private, reader.clone(), delivery.clone());
    engine.run(until()).unwrap();
    assert_eq!(delivery.lock().unwrap().submissions().len(), 0);
    *reader.0.lock().unwrap() = vec![incident("owner-1", "incident-1", IncidentState::Escalated)];
    engine.run(until()).unwrap();
    *reader.0.lock().unwrap() = vec![incident("owner-1", "incident-2", IncidentState::Escalated)];
    engine.run(until()).unwrap();
    *reader.0.lock().unwrap() = vec![incident("owner-1", "incident-2", IncidentState::Recovered)];
    engine.run(until()).unwrap();
    *reader.0.lock().unwrap() = vec![incident("owner-1", "incident-2", IncidentState::Escalated)];
    engine.run(until()).unwrap();
    *reader.0.lock().unwrap() = vec![incident("owner-2", "incident-2", IncidentState::Escalated)];
    engine.run(until()).unwrap();
    assert_eq!(delivery.lock().unwrap().submissions().len(), 3);
    assert_eq!(store.read().unwrap().groups.len(), 3);
}
#[test]
fn preference_change_cancels_reserved_attempt_before_any_later_admission() {
    let private = Private::new();
    let store = private.store();
    store.initialize().unwrap();
    enable(&store);
    {
        let mut locked = store.lock().unwrap();
        let index = locked.observe(&decision(), 100_000).unwrap();
        locked.reserve(index, 100_000).unwrap();
    }
    let mut categories = Toggles::defaults();
    categories.decision = false;
    store
        .write_preferences(
            &PreferenceWrite {
                operation_id: OperationId::new("c".repeat(32)).unwrap(),
                expected_generation: 1,
                enabled: true,
                categories,
            },
            100_000,
        )
        .unwrap();
    assert_eq!(
        store.read().unwrap().latest().unwrap().state,
        DispatchState::Cancelled
    );
    let delivery = Arc::new(Mutex::new(RecordingDelivery::new(vec![])));
    build(
        &private,
        Arc::new(Reader(Mutex::new(vec![decision()]))),
        delivery.clone(),
    )
    .run(until())
    .unwrap();
    assert_eq!(delivery.lock().unwrap().submissions().len(), 0);
}

struct UnreadSource;
impl Sources for UnreadSource {
    fn read(&self, _: Instant) -> Result<Batch, Error> {
        Err(Error::Unavailable)
    }
    fn recheck(&self, _: &Observation, _: Instant) -> Result<Observation, Error> {
        Err(Error::Unavailable)
    }
}
#[test]
fn unread_source_pass_is_a_visible_gap_and_never_a_fresh_empty_success() {
    let private = Private::new();
    let store = private.store();
    store.initialize().unwrap();
    enable(&store);
    let delivery = Arc::new(Mutex::new(RecordingDelivery::new(vec![])));
    build(
        &private,
        Arc::new(Reader(Mutex::new(vec![decision()]))),
        delivery.clone(),
    )
    .run(until())
    .unwrap();
    assert_eq!(
        store.read().unwrap().coverage.state,
        CoverageState::Complete
    );
    assert_eq!(
        build(&private, Arc::new(UnreadSource), delivery.clone()).run(until()),
        Err(Error::Unavailable)
    );
    let state = store.read().unwrap();
    assert_eq!(
        state.coverage.state,
        CoverageState::Partial,
        "failed source pass must replace confident coverage with an explicit gap"
    );
    assert_eq!(state.freshness.state, FreshnessState::Unknown);
    assert_eq!(delivery.lock().unwrap().submissions().len(), 1);
}

// #2034 (T3): production source bindings and the registered job. Synthetic
// decisions-route documents and saved health state only; no live read.
mod installed {
    use super::*;
    use openwiz_service::notifications::sources::{
        CommentRecord, CommentsRead, DecisionsRead, Installed, loopback_decisions,
    };
    use serde_json::{Value, json};

    fn config(notifications: bool) -> Value {
        let mut config = json!({"schema":"openwiz.service-config.v1",
            "repository":{"owner":"Synthetic-Owner","name":"synthetic-repo"},
            "project":"prj_syn_0001","orchestrator_thread":"thr_syn_orchestrator","service_issue":901,
            "github_app":{"app_id":1001,"installation_id":2002},"tick":{"every_s":3600},
            "health":{"every_s":3600},"server":{"port":7370,"allowed_host":null,"probe_timeout_s":10}});
        if notifications {
            config["notifications"] = json!({"every_s":1});
        }
        config
    }
    pub(super) fn route(current: bool, fresh: bool) -> Value {
        json!({"schema":"openwiz.decisions.v1","kind":"response","snapshot_at":100_000,
            "coverage":{"state":"complete","gaps":[]},
            "freshness": if fresh {json!({"state":"fresh","snapshot_at":{"known":100_000}})}
                else {json!({"state":"stale","snapshot_at":{"known":20_000}})},
            "orchestrator":{"coverage":{"state":"complete","gaps":[]},
                "freshness":{"state":"fresh","snapshot_at":{"known":100_000}},
                "target":{"known":"thr_syn_orchestrator"}},
            "items":[{"comment_id":9_100_001,
                "subject":{"repository":"synthetic-owner/synthetic-repo","kind":"pull_request","number":2731},
                "created_at":1000,"updated_at":2000,"current":{"known":current},
                "request":{"schema":"openwiz.decisions.v1","kind":"grill_round","id":"dr_syn_r1",
                    "status":"open","fingerprint":"1f".repeat(32),"risk":"ordinary",
                    "grill_file":"docs/grills/synthetic.md","round":1,
                    "questions":[{"id":"G1","decides":"Synthetic choice?","context":"Synthetic.","recommendation":"Keep it."}],
                    "answered":[]}}]})
    }
    fn escalated(id: &str, opened: u64) -> Value {
        json!({"id":id,"check":"cloudroom","opened_at":opened,"broken":{"state":"broken","what":"not_running"},
            "healthy_since":null,"needs_you":{"at":opened,"op_id":format!("syn-needs-you-{id}"),"comment":null}})
    }
    pub(super) fn health(last_pass: Option<u64>) -> Value {
        // i1: the owner's explicit Needs you. i2: active repair (a try, no
        // Needs you). i3: escalated earlier but healthy since: not escalated now.
        let healed = json!({"id":"i3","check":"server","opened_at":96_000,
            "broken":{"state":"broken","what":"refused"},"healthy_since":99_000,
            "tries":{"first":{"at":96_000,"outcome":{"state":"interrupted"},"comment":null},
                     "second":{"at":97_000,"outcome":{"state":"interrupted"},"comment":null}},
            "needs_you":{"at":98_000,"op_id":"syn-needs-you-i3","comment":null}});
        json!({"schema":"openwiz.service-state.v1","next_incident":4,
            "tick":{"running":null,"last_ended":null},
            "last_pass": last_pass.map(|at| json!({"at":at,"fixes":[],"needs_you":[],"results":[
                {"check":"cloudroom","observed":{"state":"broken","what":"not_running"}},
                {"check":"tick","observed":{"state":"broken","what":"stalled","run_started_at":80_000}},
                {"check":"server","observed":{"state":"healthy"}}]})),
            "incidents":[escalated("i1", 90_000),
                {"id":"i2","check":"tick","opened_at":95_000,
                 "broken":{"state":"broken","what":"stalled","run_started_at":80_000},"healthy_since":null,
                 "tries":{"first":{"at":95_000,"outcome":{"state":"interrupted"},"comment":null},"second":null},
                 "needs_you":null},
                healed],
            "update":null})
    }
    fn state(private: &Private, saved: &Value) -> Arc<Mutex<openwiz_service::state::State>> {
        let path = private.0.join("service/state.json");
        fs::write(&path, saved.to_string()).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        Arc::new(Mutex::new(
            openwiz_service::state::State::load(&private.0, 100_000).unwrap(),
        ))
    }
    fn fixed(doc: Value) -> DecisionsRead {
        Arc::new(move |_| Ok(doc.clone()))
    }
    fn job(
        private: &Private,
        state: &Arc<Mutex<openwiz_service::state::State>>,
        decisions: DecisionsRead,
        delivery: &Arc<Mutex<RecordingDelivery>>,
    ) -> impl Fn() + Send + Sync + use<> {
        job_with(
            private,
            state,
            decisions,
            no_comments(),
            delivery,
            Arc::new(Fixed),
        )
    }
    fn no_comments() -> CommentsRead {
        Arc::new(|_| Err(Error::Unavailable))
    }
    fn job_with(
        private: &Private,
        state: &Arc<Mutex<openwiz_service::state::State>>,
        decisions: DecisionsRead,
        comments: CommentsRead,
        delivery: &Arc<Mutex<RecordingDelivery>>,
        clock: Arc<dyn Clock>,
    ) -> impl Fn() + Send + Sync + use<> {
        let (every, job) = openwiz_service::notification_job(
            &private.0,
            &config(true),
            Arc::clone(state),
            decisions,
            comments,
            Box::new(Delivery(delivery.clone())),
            Arc::new(|id, _| id.as_str() == "synthetic-binding"),
            clock,
        )
        .unwrap()
        .expect("configured notifications register one job");
        assert_eq!(every.get(), 1);
        job
    }
    fn accepted(n: usize) -> Arc<Mutex<RecordingDelivery>> {
        Arc::new(Mutex::new(RecordingDelivery::new(
            (0..n)
                .map(|_| DeliveryOutcome {
                    state: OutcomeState::Accepted,
                    reason: text("Synthetic acceptance"),
                })
                .collect(),
        )))
    }
    fn published(state: &Arc<Mutex<openwiz_service::state::State>>) -> Value {
        state.lock().unwrap().snapshot()["notifications"].clone()
    }
    fn availability(private: &Private, category: Category) -> Fact<bool> {
        private
            .store()
            .read()
            .unwrap()
            .sources
            .into_iter()
            .find(|s| s.category == category)
            .unwrap()
            .available
    }

    // PA1 red first: current decision + explicit Needs you alert; repair,
    // healthy-since and routine facts stay quiet; nothing before opt-in.
    #[test]
    fn production_sources_alert_only_current_decisions_and_owner_escalations() {
        let private = Private::new();
        let state = state(&private, &health(Some(100_000)));
        let delivery = accepted(2);
        let run = job(&private, &state, fixed(route(true, true)), &delivery);
        run();
        assert_eq!(
            delivery.lock().unwrap().submissions().len(),
            0,
            "off by default"
        );
        assert_eq!(
            published(&state),
            json!({"state":"off","preference_generation":0,"last_pass_at":{"known":100_000},
                "reason":"Delivery is off; already submitted effects cannot be retracted"})
        );
        enable(&private.store());
        run();
        run();
        let groups: Vec<Reference> = delivery
            .lock()
            .unwrap()
            .submissions()
            .iter()
            .map(|s| s.group.clone())
            .collect();
        assert_eq!(
            groups,
            vec![
                Reference::Decision(DecisionRef {
                    repository: Repository::new("synthetic-owner/synthetic-repo").unwrap(),
                    subject: Subject {
                        kind: SubjectKind::PullRequest,
                        number: 2731.try_into().unwrap()
                    },
                    comment_id: 9_100_001.try_into().unwrap(),
                    request_id: RequestId::new("dr_syn_r1").unwrap(),
                    fingerprint: Fingerprint::new("1f".repeat(32)).unwrap(),
                }),
                Reference::Incident(IncidentRef {
                    repository: Repository::new("synthetic-owner/synthetic-repo").unwrap(),
                    owner: Id::new("prj_syn_0001").unwrap(),
                    source: RecoverySource::ServiceHealth,
                    subject: Id::new("cloudroom").unwrap(),
                    incident: Id::new("i1-90000").unwrap(),
                }),
            ],
            "exactly one alert each; repeats stay grouped"
        );
        assert_eq!(published(&state)["state"], "accepted");
        assert_eq!(published(&state)["preference_generation"], 1);
        assert_eq!(
            availability(&private, Category::Decision),
            Fact::Known(true)
        );
        assert_eq!(
            availability(&private, Category::CiFailed),
            Fact::Known(false)
        );
    }

    // Acceptance 1: stale reads, unread owners and a not-yet-recovered engine
    // are never relabelled an unrecoverable factory or a current decision.
    #[test]
    fn stale_unread_or_restarted_sources_are_never_relabelled_escalations() {
        for (last_pass, decisions) in [
            (Some(100_000 - 70_001), fixed(route(true, false))),
            (
                None,
                Arc::new(|_: Instant| Err(Error::Unavailable)) as DecisionsRead,
            ),
            (Some(100_000), fixed(route(false, true))),
        ] {
            let private = Private::new();
            private.store().initialize().unwrap();
            enable(&private.store());
            let state = state(&private, &health(last_pass));
            let delivery = accepted(2);
            let run = job(&private, &state, decisions, &delivery);
            run();
            run();
            let submitted: Vec<_> = delivery
                .lock()
                .unwrap()
                .submissions()
                .iter()
                .map(|s| s.group.clone())
                .collect();
            if last_pass == Some(100_000) {
                // Only the explicit Needs you; the noncurrent decision stays quiet.
                assert_eq!(submitted.len(), 1);
                assert!(matches!(submitted[0], Reference::Incident(_)));
            } else {
                assert_eq!(submitted, vec![], "stale or unread facts submit nothing");
                assert!(matches!(
                    availability(&private, Category::RecoveryEscalation),
                    Fact::Unknown(_)
                ));
                assert_eq!(
                    private.store().read().unwrap().coverage.state,
                    CoverageState::Partial
                );
            }
            assert_eq!(published(&state)["last_pass_at"], json!({"known":100_000}));
        }
    }

    // Acceptance 2: one job in the existing scheduler, never overlapping;
    // absent configuration registers nothing and creates no store.
    #[test]
    fn registered_job_is_bounded_nonoverlapping_and_absent_config_adds_nothing() {
        let private = Private::new();
        let state = state(&private, &health(Some(100_000)));
        let absent = openwiz_service::notification_job(
            &private.0,
            &config(false),
            Arc::clone(&state),
            fixed(route(true, true)),
            no_comments(),
            Box::new(Delivery(accepted(0))),
            Arc::new(|_, _| true),
            Arc::new(Fixed),
        )
        .unwrap();
        assert!(absent.is_none());
        assert!(!private.0.join("service/notifications").exists());
        let (entered_tx, entered) = std::sync::mpsc::channel();
        let (release, held) = std::sync::mpsc::channel::<()>();
        let held = Mutex::new(held);
        let reads = Arc::new(AtomicU64::new(0));
        let counted = Arc::clone(&reads);
        let blocking: DecisionsRead = Arc::new(move |_| {
            counted.fetch_add(1, Ordering::SeqCst);
            entered_tx.send(()).unwrap();
            held.lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(5))
                .unwrap();
            Ok(route(true, true))
        });
        let mut scheduler = openwiz_service::scheduler::Scheduler::default();
        scheduler
            .register(
                openwiz_service::NOTIFICATION_JOB,
                1.try_into().unwrap(),
                job(&private, &state, blocking, &accepted(0)),
            )
            .unwrap();
        assert_eq!(scheduler.poll(1).unwrap(), vec!["notifications"]);
        entered.recv_timeout(Duration::from_secs(5)).unwrap();
        assert_eq!(
            scheduler.poll(2).unwrap(),
            Vec::<String>::new(),
            "no overlap"
        );
        release.send(()).unwrap();
        scheduler.wait(openwiz_service::NOTIFICATION_JOB).unwrap();
        assert_eq!(reads.load(Ordering::SeqCst), 1);
        assert_eq!(published(&state)["last_pass_at"], json!({"known":100_000}));
    }

    // Only the actual runtime catches an omitted registration. The child runs
    // the real service runtime with a refusing fake `gh` first on PATH and
    // CloudRoom discovery blocked, so no live read is possible.
    #[test]
    fn notification_runtime_process() {
        let Some(root) = std::env::var_os("OPENWIZ_T3_RUNTIME_ROOT") else {
            return;
        };
        let root = PathBuf::from(root);
        use openwiz_adapter_cloudroom::locate::{self, Discovery, LauncherMetadata};
        locate::install(Discovery::fixed(root.join("no-real-room-cli"), |_| {
            LauncherMetadata { uid: 0, mode: 0 }
        }))
        .unwrap();
        let result = openwiz_service::runtime::run_with_health_sources(
            &root,
            &root.join("web"),
            &"a".repeat(40),
            openwiz_service::scheduler::Scheduler::default(),
            |_| std::net::TcpListener::bind(("127.0.0.1", 0)),
            openwiz_service::health::Sources {
                room: openwiz_adapter_cloudroom::source::CloudRoomSource::new(
                    "/synthetic/unreachable-room",
                ),
                github: openwiz_adapter_github::process::Executor::program(root.join("bin/gh")),
            },
        );
        fs::write(root.join("runtime-error"), format!("{result:?}")).unwrap();
    }
    #[test]
    fn actual_runtime_registers_the_configured_notification_job() {
        let private = Private::new();
        let root = &private.0;
        let now = u64::try_from(openwiz_server::SystemClock.now().0).unwrap();
        let mut saved = health(Some(now));
        saved["incidents"][0]["opened_at"] = json!(now);
        saved["incidents"][0]["needs_you"]["at"] = json!(now);
        for (path, body, mode) in [
            ("service/config.json", config(true).to_string(), 0o600),
            ("service/state.json", saved.to_string(), 0o600),
            ("web/index.html", "Synthetic page".to_owned(), 0o600),
            ("bin/gh", "#!/bin/sh\nexit 1\n".to_owned(), 0o700),
        ] {
            let path = root.join(path);
            fs::DirBuilder::new()
                .recursive(true)
                .mode(0o700)
                .create(path.parent().unwrap())
                .unwrap();
            fs::write(&path, body).unwrap();
            fs::set_permissions(&path, fs::Permissions::from_mode(mode)).unwrap();
        }
        struct Child(std::process::Child);
        impl Drop for Child {
            fn drop(&mut self) {
                let _ = self.0.kill();
                let _ = self.0.wait();
            }
        }
        let _child = Child(
            std::process::Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "installed::notification_runtime_process",
                    "--nocapture",
                ])
                .env("OPENWIZ_T3_RUNTIME_ROOT", root)
                .env("OPENWIZ_STATE_DIR", root)
                .env(
                    "PATH",
                    format!("{}:/usr/bin:/bin", root.join("bin").display()),
                )
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .spawn()
                .unwrap(),
        );
        // Wait, with a limit, for the running service's own status to show a
        // completed notification pass; never a fixed sleep.
        let limit = Instant::now() + Duration::from_secs(60);
        let status = loop {
            let status = openwiz_service::runtime::status(root).ok();
            if let Some(status) =
                status.filter(|s| s["notifications"]["last_pass_at"]["known"].is_u64())
            {
                break status;
            }
            assert!(
                Instant::now() < limit,
                "no notification pass: {:?}",
                fs::read_to_string(root.join("runtime-error"))
            );
            std::thread::park_timeout(Duration::from_millis(50));
        };
        assert_eq!(status["notifications"]["state"], "off");
        assert_eq!(status["notifications"]["preference_generation"], 0);
        let store = private.store().read().unwrap();
        // The owner's escalation was recorded durably; the unread decisions
        // route (refusing `gh`) stays a gap, and nothing was submitted.
        assert!(store.groups.iter().any(|g| matches!(&g.observation.fact,
            SourceFact::Incident(i) if i.state == IncidentState::Escalated)));
        assert!(store.groups.iter().all(|g| g.dispatch.is_none()));
        assert!(
            store
                .coverage
                .gaps
                .iter()
                .any(|g| g.source == SourceOwner::Decisions)
        );
    }

    // The installed decisions read is the actual route over loopback; an
    // unconfigured route is an unread decision source, never empty work.
    #[test]
    fn loopback_reads_the_actual_decisions_route_and_its_gaps() {
        let server = openwiz_server::start_with_read_sources(
            openwiz_server::bind(0).unwrap(),
            openwiz_server::Config::default(),
            Arc::new(NoRoom),
            Arc::new(Fixed),
            Arc::new(|_| {}),
            openwiz_server::ReadSources::default(),
        )
        .unwrap();
        let read = loopback_decisions(server.local_addr().port());
        let doc = read(until()).unwrap();
        assert_eq!(doc["schema"], "openwiz.decisions.v1");
        assert_eq!(doc["coverage"]["state"], "partial");
        let sources = Installed::new(
            &config(true),
            read,
            Arc::new(|| Ok(health(Some(100_000)))),
            no_comments(),
            Arc::new(Fixed),
        )
        .unwrap();
        let batch = sources.read(until()).unwrap();
        let decision = batch
            .sources
            .iter()
            .find(|s| s.category == Category::Decision)
            .unwrap();
        assert!(matches!(decision.available, Fact::Unknown(_)));
        assert!(
            batch
                .observations
                .iter()
                .all(|o| matches!(o.fact, SourceFact::Incident(_)))
        );
        let closed = openwiz_server::bind(0).unwrap();
        let port = closed.local_addr().unwrap().port();
        drop(closed);
        assert!(loopback_decisions(port)(until()).is_err());
    }

    // ---- Review round 1 regressions (R1-R4), each red first. ----
    struct At(AtomicU64);
    impl Clock for At {
        fn now(&self) -> Timestamp {
            Timestamp(i64::try_from(self.0.load(Ordering::SeqCst)).unwrap())
        }
        fn monotonic(&self) -> Instant {
            Instant::now()
        }
    }
    fn valid(doc: &Value) -> Value {
        openwiz_service::document::read(
            openwiz_service::document::Document::State,
            &doc.to_string(),
        )
        .unwrap_or_else(|why| panic!("synthetic state must be valid: {why}"))
    }
    fn tries(at: u64) -> Value {
        json!({"first":{"at":at,"outcome":{"state":"interrupted"},"comment":null},
               "second":{"at":at + 1,"outcome":{"state":"interrupted"},"comment":null}})
    }
    fn needs(id: &str, at: u64) -> Value {
        json!({"at":at,"op_id":format!("syn-needs-you-{id}"),"comment":null})
    }
    fn passed(at: u64, incidents: Value, extra: Vec<Value>) -> Value {
        let mut results = vec![
            json!({"check":"cloudroom","observed":{"state":"healthy"}}),
            json!({"check":"tick","observed":{"state":"healthy"}}),
            json!({"check":"server","observed":{"state":"healthy"}}),
        ];
        results.extend(extra);
        valid(
            &json!({"schema":"openwiz.service-state.v1","next_incident":4,
            "tick":{"running":null,"last_ended":null},
            "last_pass":{"at":at,"results":results,"fixes":[],"needs_you":[]},
            "incidents":incidents,"update":null}),
        )
    }
    const LOOP: &str = r#"{"id":"loop-syn","name":"launch-fleet synthetic-owner/synthetic-repo"}"#;
    fn loop_incident() -> Value {
        json!({"id":"i1","check":"loop","loop":serde_json::from_str::<Value>(LOOP).unwrap(),
            "opened_at":90_000,"broken":{"state":"broken","what":"paused"},"healthy_since":null,
            "tries":tries(90_000),"needs_you":needs("i1", 95_000)})
    }
    fn loop_broken() -> Value {
        json!({"check":"loop","loop":serde_json::from_str::<Value>(LOOP).unwrap(),
            "observed":{"state":"broken","what":"paused"}})
    }
    fn loop_unread() -> Value {
        json!({"check":"loop","unread":{"gap":"command_failed","reason":"Synthetic loop list unread"}})
    }
    fn submitted(private: &Private, saved: Value) -> usize {
        private.store().initialize().unwrap();
        enable(&private.store());
        let state = state(private, &saved);
        let delivery = accepted(1);
        let run = job(private, &state, fixed(route(false, true)), &delivery);
        run();
        delivery.lock().unwrap().submissions().len()
    }

    // R1: a recent pass does not refresh a retained escalation whose own
    // subject is unread or unknown; only a positively broken subject counts.
    #[test]
    fn unread_or_unknown_incident_subjects_never_submit() {
        let watchdog = json!({"id":"i1","check":"watchdog","loop_id":"loop-syn","opened_at":99_000,
            "broken":{"state":"broken","what":"missed","due_at_ms":98_000},"healthy_since":null,
            "needs_you":needs("i1", 99_000)});
        let open = json!([{"loop_id":"loop-syn","broken":{"state":"broken","what":"missed","due_at_ms":98_000}}]);
        let fleet = json!({"id":"i1","check":"fleet_thread","spec":900,"thread":"thr_syn_dead",
            "opened_at":90_000,"broken":{"state":"broken","what":"archived"},"healthy_since":null,
            "tries":tries(90_000),"needs_you":needs("i1", 95_000)});
        let cases = [
            (
                "loop list unread",
                json!([loop_incident()]),
                vec![loop_unread()],
            ),
            (
                "fleet thread unknown",
                json!([fleet]),
                vec![json!({"check":"fleet_thread","spec":900,
                "thread":"thr_syn_dead","observed":{"state":"unknown","gap":"command_failed","reason":"Synthetic unknown"}})],
            ),
            (
                "watchdog loop unknown",
                json!([watchdog.clone()]),
                vec![json!({"check":"watchdog",
                "open":open,"unknown":[{"loop_id":"loop-syn","kind":"missed"}],"snapshot_unknown":false})],
            ),
            (
                "watchdog snapshot unknown",
                json!([watchdog]),
                vec![json!({"check":"watchdog",
                "open":open,"unknown":[],"snapshot_unknown":true})],
            ),
        ];
        for (name, incidents, extra) in cases {
            let private = Private::new();
            assert_eq!(
                submitted(&private, passed(100_000, incidents, extra)),
                0,
                "{name}"
            );
            let store = private.store().read().unwrap();
            assert_eq!(
                store.coverage.state,
                CoverageState::Partial,
                "{name}: explicit gap"
            );
            assert!(
                store
                    .coverage
                    .gaps
                    .iter()
                    .any(|g| g.source == SourceOwner::ServiceHealth),
                "{name}"
            );
        }
        // Control: the same retained escalation with its subject positively broken.
        let private = Private::new();
        assert_eq!(
            submitted(
                &private,
                passed(100_000, json!([loop_incident()]), vec![loop_broken()])
            ),
            1
        );
    }

    // R1: the immediate independent recheck repeats the subject binding.
    #[test]
    fn subject_becoming_unread_before_submit_cancels_with_no_effect() {
        let broken = passed(100_000, json!([loop_incident()]), vec![loop_broken()]);
        let unread = passed(100_000, json!([loop_incident()]), vec![loop_unread()]);
        let calls = Arc::new(AtomicU64::new(0));
        let counted = Arc::clone(&calls);
        let sources = Installed::new(
            &config(true),
            fixed(route(false, true)),
            Arc::new(move || {
                Ok(if counted.fetch_add(1, Ordering::SeqCst) == 0 {
                    broken.clone()
                } else {
                    unread.clone()
                })
            }),
            no_comments(),
            Arc::new(Fixed),
        )
        .unwrap();
        let private = Private::new();
        let store = private.store();
        store.initialize().unwrap();
        enable(&store);
        let delivery = accepted(1);
        Engine::new(
            store.clone(),
            Arc::new(sources),
            Box::new(Delivery(delivery.clone())),
            Arc::new(Fixed),
            Arc::new(|_, _| true),
        )
        .run(until())
        .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 2, "one read, one recheck");
        assert_eq!(delivery.lock().unwrap().submissions().len(), 0);
        assert_eq!(
            store.read().unwrap().latest().unwrap().state,
            DispatchState::Cancelled
        );
    }

    // R2: resolution is the request's own comment record; recovery is the
    // owner's healing rule. Both close permanently, across restart and late
    // open observations; absence alone closes nothing.
    #[test]
    fn resolved_decisions_and_healed_incidents_close_groups_across_restart() {
        let clock = Arc::new(At(AtomicU64::new(100_000)));
        let private = Private::new();
        private.store().initialize().unwrap();
        enable(&private.store());
        let state = state(&private, &health(Some(100_000)));
        let doc = Arc::new(Mutex::new(route(true, true)));
        let comments = Arc::new(Mutex::new(Vec::<CommentRecord>::new()));
        let reads = |doc: &Arc<Mutex<Value>>, comments: &Arc<Mutex<Vec<CommentRecord>>>| {
            let (doc, comments) = (Arc::clone(doc), Arc::clone(comments));
            (
                Arc::new(move |_: Instant| Ok(doc.lock().unwrap().clone())) as DecisionsRead,
                Arc::new(move |_: Instant| Ok(comments.lock().unwrap().clone())) as CommentsRead,
            )
        };
        let delivery = accepted(4);
        let (d, c) = reads(&doc, &comments);
        let run = job_with(&private, &state, d, c, &delivery, clock.clone());
        run();
        assert_eq!(delivery.lock().unwrap().submissions().len(), 2);
        let group = |decision: bool| {
            private
                .store()
                .read()
                .unwrap()
                .groups
                .into_iter()
                .find(|g| matches!(g.observation.fact, SourceFact::Decision(_)) == decision)
                .unwrap()
        };
        // Absent from the complete open list, its comment still open: stays open.
        let mut record = route(true, true)["items"][0]["request"].clone();
        let comment = |record: &Value| CommentRecord {
            repository: "synthetic-owner/synthetic-repo".into(),
            id: 9_100_001,
            subject: 2731,
            body: format!("Synthetic question.\n\n```json\n{record}\n```\n"),
        };
        doc.lock().unwrap()["items"] = json!([]);
        *comments.lock().unwrap() = vec![comment(&record)];
        run();
        assert!(!group(true).closed, "absence is not resolution");
        record["status"] = json!("resolved");
        record["answered"] = json!(["G1"]);
        *comments.lock().unwrap() = vec![comment(&record)];
        run();
        let closed = group(true);
        assert!(closed.closed);
        assert_eq!(closed.dispatch.unwrap().group_state, GroupState::Closed);
        // Restart: a fresh job seeded from the store; a late open observation
        // of the resolved request never reopens or resubmits it.
        *doc.lock().unwrap() = route(true, true);
        let (d, c) = reads(&doc, &comments);
        let restarted = job_with(&private, &state, d, c, &delivery, clock.clone());
        restarted();
        assert!(group(true).closed);
        assert!(!group(false).closed);
        // The incident: healthy since 100 s, then dropped by the owner.
        let healthy = |at: u64, since: Option<u64>| {
            let mut i1 = health(Some(100_000))["incidents"][0].clone();
            i1["healthy_since"] = json!(since);
            passed(
                at,
                if since.is_some() {
                    json!([i1])
                } else {
                    json!([])
                },
                vec![],
            )
        };
        state
            .lock()
            .unwrap()
            .save(healthy(100_000, Some(100_000)))
            .unwrap();
        restarted();
        assert!(!group(false).closed, "healthy-since is not yet recovery");
        let healed = 100_000 + openwiz_core::health::HEALTHY_FOR_MS.unsigned_abs();
        clock.0.store(healed - 1, Ordering::SeqCst);
        state
            .lock()
            .unwrap()
            .save(healthy(healed - 1, None))
            .unwrap();
        restarted();
        assert!(
            !group(false).closed,
            "absence before the owner's healing rule"
        );
        clock.0.store(healed, Ordering::SeqCst);
        state.lock().unwrap().save(healthy(healed, None)).unwrap();
        restarted();
        let recovered = group(false);
        assert!(recovered.closed);
        assert_eq!(recovered.dispatch.unwrap().group_state, GroupState::Closed);
        assert_eq!(delivery.lock().unwrap().submissions().len(), 2);
    }

    // R3: a reply that trickles in cannot keep the pass past its deadline.
    #[test]
    fn trickling_decisions_reply_cannot_outlive_the_deadline() {
        use std::io::{Read as _, Write as _};
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = std::thread::spawn(move || {
            let (mut peer, _) = listener.accept().unwrap();
            let mut request = [0u8; 512];
            let _ = peer.read(&mut request);
            for _ in 0..150 {
                if peer.write_all(b"H").is_err() {
                    return;
                }
                std::thread::sleep(Duration::from_millis(20));
            }
        });
        let started = Instant::now();
        let result = loopback_decisions(port)(started + Duration::from_millis(200));
        let elapsed = started.elapsed();
        assert!(result.is_err());
        assert!(
            elapsed < Duration::from_secs(1),
            "read ran {elapsed:?} past a 200 ms deadline"
        );
        server.join().unwrap();
    }

    // R4: an owner write briefly holding the store at startup keeps the job;
    // passes submit nothing while it is busy and recover once it is free.
    #[test]
    fn busy_store_at_startup_keeps_the_job_and_later_passes_recover() {
        let private = Private::new();
        private.store().initialize().unwrap();
        enable(&private.store());
        let state = state(&private, &health(Some(100_000)));
        let delivery = accepted(2);
        let held = private.store().lock().unwrap();
        let run = job(&private, &state, fixed(route(true, true)), &delivery);
        run();
        assert_eq!(delivery.lock().unwrap().submissions().len(), 0);
        assert!(published(&state)["last_pass_at"]["unknown"].is_string());
        drop(held);
        run();
        assert_eq!(delivery.lock().unwrap().submissions().len(), 2);
        assert_eq!(published(&state)["last_pass_at"], json!({"known":100_000}));
    }

    // ---- Re-check regressions (R6, R2), each red first. ----
    fn watchdog(id: &str, broken: &Value, at: u64) -> Value {
        json!({"id":id,"check":"watchdog","loop_id":"loop-syn","opened_at":at,"broken":broken,
            "healthy_since":null,"needs_you":needs(id, at)})
    }
    fn watchdog_result(open: &[&Value], unknown: &[&str]) -> Value {
        json!({"check":"watchdog",
            "open": open.iter().map(|b| json!({"loop_id":"loop-syn","broken":b})).collect::<Vec<_>>(),
            "unknown": unknown.iter().map(|k| json!({"loop_id":"loop-syn","kind":k})).collect::<Vec<_>>(),
            "snapshot_unknown":false})
    }
    fn missed(due: u64) -> Value {
        json!({"state":"broken","what":"missed","due_at_ms":due})
    }
    fn stuck() -> Value {
        json!({"state":"broken","what":"stuck","run_id":"run-syn","started_at_ms":10_000,"timeout_ms":1000})
    }
    fn incident_group(private: &Private, incident: &str) -> openwiz_store::notifications::Group {
        private
            .store()
            .read()
            .unwrap()
            .groups
            .into_iter()
            .find(|g| {
                matches!(&g.observation.fact,
                SourceFact::Incident(i) if i.binding.incident.as_str() == incident)
            })
            .unwrap_or_else(|| panic!("no group for {incident}"))
    }

    // R6: unknown evidence about another fault kind of the loop (production
    // always publishes disabled_by_failures as unknown) never hides a known,
    // escalated missed/stuck problem; the same kind unknown still refuses.
    #[test]
    fn known_watchdog_problems_alert_despite_unrelated_unknown_kinds() {
        for (name, broken, unknown, expected) in [
            (
                "missed, other kind unknown",
                missed(98_000),
                "disabled_by_failures",
                1,
            ),
            (
                "stuck, other kind unknown",
                stuck(),
                "disabled_by_failures",
                1,
            ),
            ("missed, same kind unknown", missed(98_000), "missed", 0),
            ("stuck, same kind unknown", stuck(), "stuck", 0),
        ] {
            let private = Private::new();
            let saved = passed(
                100_000,
                json!([watchdog("i1", &broken, 99_000)]),
                vec![watchdog_result(&[&broken], &[unknown])],
            );
            assert_eq!(submitted(&private, saved), expected, "{name}");
        }
    }

    // R6: one incident's unread subject is its own gap; an independently
    // current escalation in the same pass still alerts.
    #[test]
    fn unread_incident_does_not_block_an_unrelated_current_escalation() {
        let private = Private::new();
        let mut unread = loop_incident();
        unread["id"] = json!("i2");
        unread["needs_you"] = needs("i2", 95_000);
        let broken = missed(98_000);
        let saved = passed(
            100_000,
            json!([watchdog("i1", &broken, 99_000), unread]),
            vec![
                loop_unread(),
                watchdog_result(&[&broken], &["disabled_by_failures"]),
            ],
        );
        assert_eq!(submitted(&private, saved), 1);
        assert_eq!(
            availability(&private, Category::RecoveryEscalation),
            Fact::Known(true)
        );
        let store = private.store().read().unwrap();
        assert_eq!(
            store.coverage.state,
            CoverageState::Partial,
            "the gap stays visible"
        );
        assert!(incident_group(&private, "i1-99000").dispatch.is_some());
        // The unread incident is a gap only: never recorded, never submitted.
        assert!(!store.groups.iter().any(|g| matches!(&g.observation.fact,
            SourceFact::Incident(i) if i.binding.incident.as_str() == "i2-90000")));
    }

    // R2: recovery evidence survives a restart: a group whose healthy-since was
    // seen before the restart closes once the owner removes it after healing.
    #[test]
    fn healed_incident_closes_after_a_restart_following_owner_removal() {
        let clock = Arc::new(At(AtomicU64::new(100_000)));
        let private = Private::new();
        private.store().initialize().unwrap();
        enable(&private.store());
        let state = state(&private, &health(Some(100_000)));
        let delivery = accepted(2);
        let run = |state: &Arc<Mutex<openwiz_service::state::State>>| {
            job_with(
                &private,
                state,
                fixed(route(false, true)),
                no_comments(),
                &delivery,
                clock.clone(),
            )
        };
        let first = run(&state);
        first();
        assert!(incident_group(&private, "i1-90000").dispatch.is_some());
        let mut i1 = health(Some(100_000))["incidents"][0].clone();
        i1["healthy_since"] = json!(100_000);
        state
            .lock()
            .unwrap()
            .save(passed(100_000, json!([i1]), vec![]))
            .unwrap();
        first();
        drop(first);
        // Restart; meanwhile the owner heals and removes the incident.
        let healed = 100_000 + openwiz_core::health::HEALTHY_FOR_MS.unsigned_abs();
        clock.0.store(healed, Ordering::SeqCst);
        state
            .lock()
            .unwrap()
            .save(passed(healed, json!([]), vec![]))
            .unwrap();
        run(&state)();
        let group = incident_group(&private, "i1-90000");
        assert!(
            group.closed,
            "positively healed incident closes after restart"
        );
        assert_eq!(group.dispatch.unwrap().group_state, GroupState::Closed);
    }

    // R2: a watchdog group closes on its own exact problem, across a restart,
    // even while a new, different problem of the same loop is open.
    #[test]
    fn watchdog_group_closes_on_its_exact_problem_across_restart() {
        let clock = Arc::new(At(AtomicU64::new(100_000)));
        let private = Private::new();
        private.store().initialize().unwrap();
        enable(&private.store());
        let first_problem = missed(98_000);
        let state = state(
            &private,
            &passed(
                100_000,
                json!([watchdog("i1", &first_problem, 99_000)]),
                vec![watchdog_result(
                    &[&first_problem],
                    &["disabled_by_failures"],
                )],
            ),
        );
        let delivery = accepted(2);
        let run = || {
            job_with(
                &private,
                &state,
                fixed(route(false, true)),
                no_comments(),
                &delivery,
                clock.clone(),
            )
        };
        run()();
        assert!(incident_group(&private, "i1-99000").dispatch.is_some());
        // Restart; the first problem is no longer open, a new one of the same
        // loop and kind is (its own incident).
        let second = missed(100_500);
        clock.0.store(101_000, Ordering::SeqCst);
        state
            .lock()
            .unwrap()
            .save(passed(
                101_000,
                json!([watchdog("i2", &second, 100_900)]),
                vec![watchdog_result(&[&second], &["disabled_by_failures"])],
            ))
            .unwrap();
        run()();
        let old = incident_group(&private, "i1-99000");
        assert!(old.closed, "its exact problem is positively no longer open");
        assert_eq!(old.dispatch.unwrap().group_state, GroupState::Closed);
        let new = incident_group(&private, "i2-100900");
        assert!(!new.closed);
        assert_eq!(delivery.lock().unwrap().submissions().len(), 2);
    }
}
