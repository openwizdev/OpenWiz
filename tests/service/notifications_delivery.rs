//! #2035 PA1/PA2/PA5: the installed delivery factory under the named Web Push
//! assumption. Until T2 #2033's observed binding lands, the actual engine and
//! API built from it report unsupported and make zero submissions, even with
//! delivery enabled, an eligible current decision and a registered binding.
use openwiz_core::{model::Timestamp, notifications::model::*, ops::Clock};
use openwiz_server::notifications::{Api, Read};
use openwiz_service::notifications::{Batch, Engine, Sources, delivery};
use openwiz_store::notifications::{Error, Observation, Store, text};
use std::{
    fs,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
    time::{Duration, Instant},
};

struct Private(PathBuf);
impl Private {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "openwiz-notify-delivery-{}-{}",
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
/// One current, eligible synthetic decision; recheck returns it unchanged.
struct Current;
impl Sources for Current {
    fn read(&self, _: Instant) -> Result<Batch, Error> {
        Ok(Batch {
            observations: vec![decision()],
            sources: Category::ALL
                .into_iter()
                .map(|category| CategoryStatus {
                    category,
                    available: Fact::Known(category == Category::Decision),
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
    fn recheck(&self, _: &Observation, _: Instant) -> Result<Observation, Error> {
        Ok(decision())
    }
}
/// Owner opt-in with default categories and a registered local binding, written
/// directly to the protected store so only the delivery adapter can refuse.
fn opt_in(store: &Store) {
    store.initialize().unwrap();
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
fn status(engine: &Engine) -> Status {
    match engine.read(Read::Status, 100_000, until()).unwrap().record {
        Record::Status(s) => *s,
        other => panic!("status expected, got {other:?}"),
    }
}

#[test]
fn installed_web_push_adapter_is_unsupported_and_refuses_without_an_attempt() {
    let (mut adapter, binding) = delivery::installed();
    let capability = adapter.capability();
    assert_eq!(capability.state, CapabilityState::Unsupported);
    assert_eq!(capability.permission, Permission::Unknown);
    let reply = adapter.submit(&Submission {
        dispatch_id: OperationId::new("3".repeat(32)).unwrap(),
        group: Reference::Decision(match decision().fact {
            SourceFact::Decision(d) => d.binding,
            _ => unreachable!(),
        }),
        preference_generation: 1,
        subscription_generation: 1,
        payload: ExternalPayload {
            title: PayloadTitle::Attention,
            target_token: Fingerprint::new("c".repeat(64)).unwrap(),
        },
    });
    assert_eq!(
        reply.state,
        OutcomeState::Failed,
        "no attempt is positive non-acceptance"
    );
    assert!(
        !binding(&Id::new("synthetic-binding").unwrap(), until()),
        "no binding is verified before T2's observed interface"
    );
    assert!(delivery::ASSUMPTION.contains("Web Push"));
}

#[test]
fn opted_in_engine_from_the_installed_factory_submits_nothing_and_reports_unsupported() {
    let private = Private::new();
    let store = Store::new(&private.0);
    opt_in(&store);
    let (adapter, binding) = delivery::installed();
    let engine = Engine::new(
        store.clone(),
        Arc::new(Current),
        adapter,
        Arc::new(Fixed),
        binding,
    );
    engine.run(until()).unwrap();
    engine.run(until()).unwrap();
    let state = store.read().unwrap();
    assert_eq!(
        state.latest(),
        None,
        "zero reservations and zero submissions"
    );
    let s = status(&engine);
    assert_eq!(s.state, StatusState::Unsupported);
    assert_eq!(s.capability.state, CapabilityState::Unsupported);
    assert!(
        s.preferences.enabled,
        "the owner's saved choice is kept, not reset"
    );
}

#[test]
fn installed_api_engine_reads_the_same_store_through_the_same_adapter() {
    let private = Private::new();
    let store = Store::new(&private.0);
    store.initialize().unwrap();
    let api = delivery::api_engine(&private.0, Arc::new(Fixed));
    // Off by default: no opt-in on visit, install or refresh.
    let off = status(&api);
    assert_eq!(off.state, StatusState::Off);
    assert_eq!(off.capability.state, CapabilityState::Unsupported);
    opt_in(&store);
    let on = status(&api);
    assert_eq!(
        on.state,
        StatusState::Unsupported,
        "enabled delivery stays honestly unsupported"
    );
    // A new subscription registration is refused: no verified binding exists.
    let refused = api.write(
        document(SubscriptionWrite {
            operation_id: OperationId::new("4".repeat(32)).unwrap(),
            expected_generation: 1,
            binding_id: Id::new("synthetic-other").unwrap(),
        }),
        false,
        100_000,
        until(),
    );
    assert_eq!(
        refused,
        Err(Error::SubscriptionUnavailable),
        "no verified binding exists"
    );
    assert_eq!(store.read().unwrap().latest(), None);
}
fn document(w: SubscriptionWrite) -> Document {
    openwiz_store::notifications::document(Record::SubscriptionWrite(w))
}

// R3 (review round 1): only the actual runtime proves both production
// consumers take the installed factory. The child runs the real service
// runtime with a refusing fake `gh` first on PATH and CloudRoom discovery
// blocked, so no live read is possible. With delivery enabled, the scheduler's
// summary and that runtime's own HTTP status route must both say unsupported
// and show the same saved preferences.
#[test]
fn delivery_runtime_process() {
    let Some(root) = std::env::var_os("OPENWIZ_T4_RUNTIME_ROOT") else {
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
        |port| std::net::TcpListener::bind(("127.0.0.1", port)),
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
fn actual_runtime_job_and_http_status_both_report_the_installed_adapter() {
    use serde_json::{Value, json};
    let private = Private::new();
    let root = &private.0;
    let port = std::net::TcpListener::bind(("127.0.0.1", 0))
        .unwrap()
        .local_addr()
        .unwrap()
        .port();
    let config = json!({"schema":"openwiz.service-config.v1",
        "repository":{"owner":"Synthetic-Owner","name":"synthetic-repo"},
        "project":"prj_syn_0001","orchestrator_thread":"thr_syn_orchestrator","service_issue":901,
        "github_app":{"app_id":1001,"installation_id":2002},"tick":{"every_s":3600},
        "health":{"every_s":3600},"server":{"port":port,"allowed_host":null,"probe_timeout_s":10},
        "notifications":{"every_s":1}});
    let state = json!({"schema":"openwiz.service-state.v1","next_incident":1,
        "tick":{"running":null,"last_ended":null},"last_pass":null,"incidents":[],"update":null});
    for (path, body, mode) in [
        ("service/config.json", config.to_string(), 0o600),
        ("service/state.json", state.to_string(), 0o600),
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
    // The owner opted in before the service started: generation 1, enabled.
    opt_in(&Store::new(root));
    struct Child(std::process::Child);
    impl Drop for Child {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    let _child = Child(
        std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "delivery_runtime_process", "--nocapture"])
            .env("OPENWIZ_T4_RUNTIME_ROOT", root)
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
    let limit = Instant::now() + Duration::from_secs(60);
    let wait = |what: &str| {
        assert!(
            Instant::now() < limit,
            "{what}: {:?}",
            fs::read_to_string(root.join("runtime-error"))
        );
        std::thread::park_timeout(Duration::from_millis(50));
    };
    // The scheduler's own summary, after a completed notification pass.
    let summary = loop {
        if let Some(s) = openwiz_service::runtime::status(root)
            .ok()
            .filter(|s| s["notifications"]["last_pass_at"]["known"].is_u64())
        {
            break s["notifications"].clone();
        }
        wait("no notification pass");
    };
    assert_eq!(summary["state"], "unsupported", "job summary: {summary}");
    assert_eq!(summary["preference_generation"], 1);
    // The same runtime's HTTP status route.
    let body = loop {
        if let Some(body) = get_status(port) {
            break body;
        }
        wait("no HTTP status reply");
    };
    let doc: Value = serde_json::from_str(&body).unwrap();
    let status = &doc["record"]["status"];
    assert_eq!(status["state"], "unsupported", "HTTP status: {status}");
    assert_eq!(status["capability"]["state"], "unsupported");
    assert_eq!(status["preferences"]["generation"], 1);
    assert_eq!(status["preferences"]["enabled"], true);
    assert_eq!(
        Store::new(root).read().unwrap().latest(),
        None,
        "zero submissions"
    );
}

/// One GET of the runtime's status route over loopback; None until it answers 200.
fn get_status(port: u16) -> Option<String> {
    use std::io::{Read, Write};
    let mut stream = std::net::TcpStream::connect(("127.0.0.1", port)).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(5))).ok()?;
    write!(
        stream,
        "GET /api/v1/notifications/status HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    )
    .ok()?;
    let mut raw = String::new();
    stream.read_to_string(&mut raw).ok()?;
    let (head, body) = raw.split_once("\r\n\r\n")?;
    (head.split_whitespace().nth(1)? == "200").then(|| body.to_owned())
}
