//! LP5: real scheduler, synthetic checks and never a live provider.
#[path = "l6_switches.rs"]
mod fixtures;
use fixtures::Fixture;
use openwiz_adapter_cloudroom::source::CloudRoomSource;
use openwiz_core::{
    loops::{Capacity, Limits},
    model::Timestamp,
    ops::Clock,
};
use openwiz_service::loops::{Approval, Config, Runner, Services};
use openwiz_store::NewThreadFileStore;
use serde_json::{Value, json};
use std::{fs, os::unix::fs::PermissionsExt, sync::Arc, time::Instant};
struct Time;
impl Clock for Time {
    fn now(&self) -> Timestamp {
        Timestamp(5000)
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}
struct Exact(Value);
impl Approval for Exact {
    fn verify(&self, definition: &Value, revision: &str) -> bool {
        definition == &self.0 && revision.len() == 40
    }
}
fn runner(f: &Fixture, agents: usize) -> Runner {
    let fake = f.root.join("fake-room-cli");
    fs::write(
        &fake,
        format!(
            "#!/bin/sh\nprintf called >> '{}'\nexit 1\n",
            f.root.join("provider-calls").display()
        ),
    )
    .unwrap();
    fs::set_permissions(&fake, fs::Permissions::from_mode(0o700)).unwrap();
    Runner::new(
        Config {
            checkout: f.context.checkout.clone(),
            state: f.context.state.clone(),
            limits: Some(Limits {
                checks: Capacity {
                    max: 1,
                    urgent_reserve: 0,
                },
                agents: Capacity {
                    max: agents,
                    urgent_reserve: 0,
                },
            }),
        },
        Services {
            clock: Arc::new(Time),
            client: Arc::new(CloudRoomSource::new(fake)),
            new_threads: Arc::new(NewThreadFileStore::open(&f.context.state).unwrap()),
            approval: Some(Arc::new(Exact(f.definition.clone()))),
        },
    )
}
#[test]
fn off_survives_restart_and_refresh_and_runner_preserves_every_audit_event() {
    let mut f = Fixture::new();
    let marker = f.root.join("checks");
    f.definition["wake"] = json!({"kind":"once","at_ms":1000});
    f.definition["check"]["argv"] = json!([
        "/bin/sh",
        "-c",
        format!("printf checked >> '{}'", marker.display())
    ]);
    f.commit();
    let off = f.context.switch("loop-syn-reminder", false, 1000).unwrap();
    assert!(runner(&f, 1).pass().unwrap().is_empty());
    assert!(!marker.exists());
    assert_eq!(f.saved()["events"], json!([off.clone()]));
    f.definition["authority"]["scope"] = json!("Refreshed synthetic scope only.");
    f.commit();
    assert!(runner(&f, 1).pass().unwrap().is_empty());
    assert!(!marker.exists());
    let on = f.context.switch("loop-syn-reminder", true, 2000).unwrap();
    let runs = runner(&f, 1).pass().unwrap();
    assert_eq!(runs.len(), 1);
    assert_eq!(runs[0]["result"]["kind"], "quiet");
    assert_eq!(fs::read_to_string(marker).unwrap(), "checked");
    assert_eq!(f.saved()["events"], json!([off, on]));
    assert!(!f.root.join("provider-calls").exists());
}
#[test]
fn off_prevents_a_deferred_agent_even_after_restart() {
    let mut f = Fixture::new();
    f.definition["mode"] = json!("active");
    f.definition["wake"] = json!({"kind":"once","at_ms":1000});
    f.definition["check"]["argv"] = json!(["/bin/sh", "-c", "printf synthetic-finding"]);
    f.commit();
    let first = runner(&f, 0).pass().unwrap();
    assert_eq!(first.len(), 1);
    assert_eq!(first[0]["result"]["kind"], "deferred");
    f.context.switch("loop-syn-reminder", false, 2000).unwrap();
    assert_eq!(runner(&f, 1).pass().unwrap(), first);
    assert!(!f.root.join("provider-calls").exists());
    assert_eq!(f.saved()["events"].as_array().unwrap().len(), 1);
}

#[test]
fn service_and_switch_config_readers_preserve_optional_operator_shape_and_duplicates() {
    use openwiz_service::document::{Document, read};
    let base = include_str!("../../contracts/service.v1.md")
        .lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .find(|v| v["schema"] == "openwiz.service-config.v1")
        .unwrap();
    assert!(read(Document::Config, &base.to_string()).is_ok());
    assert!(openwiz_store::loops::document::service_config(&base.to_string()).is_ok());
    for (operator, expected) in [
        (json!("synthetic-operator"), true),
        (json!(""), false),
        (json!(null), false),
        (json!(false), false),
        (json!({"name":"synthetic-operator"}), false),
    ] {
        let mut config = base.clone();
        config["operator"] = operator;
        assert_eq!(
            read(Document::Config, &config.to_string()).is_ok(),
            expected
        );
        assert_eq!(
            openwiz_store::loops::document::service_config(&config.to_string()).is_ok(),
            expected
        );
    }
    let mut config = base;
    config["operator"] = json!("synthetic-operator");
    let duplicated = config
        .to_string()
        .replacen("{", "{\"operator\":\"synthetic-other\",", 1);
    assert!(read(Document::Config, &duplicated).is_err());
    assert!(openwiz_store::loops::document::service_config(&duplicated).is_err());
}

#[test]
fn r1_switch_waits_for_running_check_then_saves_once() {
    use std::{
        process::Command,
        sync::{
            atomic::{AtomicU64, Ordering},
            mpsc,
        },
        thread,
        time::Duration,
    };
    let mut f = Fixture::new();
    let gate = f.root.join("check-gate");
    let started = f.root.join("check-started");
    assert!(
        Command::new("mkfifo")
            .arg(&gate)
            .status()
            .unwrap()
            .success()
    );
    f.definition["wake"] = json!({"kind":"once","at_ms":1000});
    f.definition["check"]["argv"] = json!([
        "/bin/sh",
        "-c",
        format!(
            "printf ready > '{}'; cat '{}' > /dev/null",
            started.display(),
            gate.display()
        )
    ]);
    f.definition["check"]["timeout_ms"] = json!(10000);
    f.commit();
    enum Event {
        Waiting,
        Done(Result<Value, String>),
    }
    struct WaitingClock {
        base: Instant,
        calls: AtomicU64,
        now: AtomicU64,
        events: mpsc::Sender<Event>,
    }
    impl Clock for WaitingClock {
        fn now(&self) -> Timestamp {
            Timestamp(self.now.load(Ordering::SeqCst) as i64)
        }
        fn monotonic(&self) -> Instant {
            if self.calls.fetch_add(1, Ordering::SeqCst) > 0 {
                let _ = self.events.send(Event::Waiting);
            }
            self.base
        }
    }
    let (send, receive) = mpsc::channel();
    let clock = Arc::new(WaitingClock {
        base: Instant::now(),
        calls: AtomicU64::new(0),
        now: AtomicU64::new(5000),
        events: send.clone(),
    });
    let pass = runner(&f, 1);
    thread::scope(|scope| {
        let running = scope.spawn(move || pass.pass());
        let deadline = Instant::now() + Duration::from_secs(5);
        while !started.exists() {
            assert!(Instant::now() < deadline, "check did not start");
            thread::yield_now();
        }
        let context = f.context.clone();
        let switch_clock = clock.clone();
        let switching = scope.spawn(move || {
            let result = context
                .switch_with_clock("loop-syn-reminder", false, switch_clock.as_ref())
                .map_err(|error| error.to_string());
            send.send(Event::Done(result)).unwrap();
        });
        let first = receive.recv_timeout(Duration::from_secs(5));
        clock.now.store(6000, Ordering::SeqCst);
        // Release the blocked check before asserting, even on the red path.
        fs::write(&gate, b"release").unwrap();
        let mut event = first.expect("no switch progress");
        while matches!(event, Event::Waiting) {
            event = receive.recv_timeout(Duration::from_secs(5)).unwrap();
        }
        switching.join().unwrap();
        let runs = running.join().unwrap().unwrap();
        assert_eq!(runs.len(), 1);
        let Event::Done(result) = event else {
            unreachable!()
        };
        let saved = result.expect("switch must wait for the running check, then save");
        assert_eq!(saved["enabled"], false);
        assert_eq!(saved["at_ms"], 6000);
        assert_eq!(f.saved()["events"], json!([saved]));
    });
    assert!(!f.root.join("provider-calls").exists());
}
