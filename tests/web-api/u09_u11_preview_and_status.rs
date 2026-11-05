//! U9 and U11 (#12, A2), the server's half.
//!
//! - **U9 effects come before pressing,** in the core's words: the
//!   new-thread preview carries the core's effect lines (or why a create
//!   would stop), and never claims, records or calls `spawn`.
//! - **U11 uncertainty keeps everything, and nothing retries:** an
//!   uncertain create stays uncertain. The status route reads the record
//!   (and, for an uncertain create, the threads seen since: observations
//!   only), and never calls `spawn`; a repeat of the op id replays the
//!   uncertain outcome; there is no retry route (U1).

use serde_json::json;

use crate::new_support::{
    NO_REMOTE, NewFake, PROJECT, TEXT, body, create, preview_json, serve_new, status,
};

#[test]
fn u9_the_preview_carries_the_cores_effects_and_creates_nothing() {
    let fake = NewFake::new("web_u9_effects");
    let s = serve_new(&fake);
    let r = preview_json(&s, PROJECT, &body("u9-op-1", TEXT));
    assert_eq!(r.status, 200, "{}", r.text());
    let preview = r.json();
    assert_eq!(preview["schema"], "openwiz.new-thread-preview.v1");
    assert_eq!(preview["verdict"]["kind"], "ready", "{preview}");
    let effects = preview["effects"]["effects"].as_array().expect("effects");
    let kinds: Vec<&str> = effects
        .iter()
        .map(|e| e["kind"].as_str().unwrap())
        .collect();
    assert_eq!(
        kinds,
        [
            "creates_and_starts",
            "starts_from_github",
            "copies_env_files",
            "full_permissions",
            "uses_cloud_agent",
            "mac_stays_awake",
            "cloud_room_names_it",
        ]
    );
    assert!(
        effects[2]["text"].as_str().unwrap().contains(".env"),
        "{preview}"
    );
    assert_eq!(
        [
            effects[2]["text"].as_str().unwrap(),
            effects[5]["text"].as_str().unwrap(),
        ],
        [
            "copies the project's .env files from this computer",
            "this computer must stay awake until the start is confirmed",
        ],
        "{preview}"
    );
    // A project a create would refuse: the core's reason, and no effects.
    let r = preview_json(&s, NO_REMOTE, &body("u9-op-2", TEXT));
    assert_eq!(r.status, 200, "{}", r.text());
    assert_eq!(r.json()["verdict"]["kind"], "stopped", "{}", r.text());
    assert!(r.json()["effects"].is_null());
    // Reads only: no spawn, no claim, no record.
    for _ in 0..3 {
        let r = preview_json(&s, PROJECT, &body("u9-op-1", TEXT));
        assert_eq!(r.status, 200);
    }
    assert!(fake.writes().is_empty(), "{:?}", fake.writes());
    assert!(!fake.any_record());
    assert_eq!(fake.spawn_count(), 0);
}

#[test]
fn u11_an_uncertain_create_stays_uncertain_and_nothing_retries() {
    let fake = NewFake::with(
        "web_u11_uncertain",
        vec![json!({"any_spawn": true, "creates": true, "abort": true})],
    );
    let s = serve_new(&fake);
    let r = create(&s, PROJECT, &body("u11-op-1", TEXT));
    assert_eq!(r.status, 200, "{}", r.text());
    assert_eq!(r.json()["status"], "uncertain", "{}", r.text());
    assert_eq!(fake.spawn_count(), 1);
    let record = std::fs::read(fake.record_path("u11-op-1")).expect("the record");
    // Refresh status, as often as the page likes: reads only.
    for _ in 0..3 {
        let r = s.get(&status("u11-op-1"));
        assert_eq!(r.status, 200, "{}", r.text());
        let st = r.json();
        assert_eq!(st["result"]["kind"], "recorded");
        assert_eq!(st["result"]["report"]["status"], "uncertain", "{st}");
        let observations = &st["result"]["observations"];
        assert!(
            observations["text"]
                .as_str()
                .unwrap()
                .starts_with("observations only"),
            "{st}"
        );
    }
    // A repeat of the op id (a reload, a second tab): the recorded outcome.
    let r = create(&s, PROJECT, &body("u11-op-1", TEXT));
    assert_eq!(r.json()["status"], "uncertain");
    assert_eq!(r.json()["result"]["replayed"], true);
    assert_eq!(fake.spawn_count(), 1, "never a second call");
    assert_eq!(
        std::fs::read(fake.record_path("u11-op-1")).expect("the record"),
        record,
        "no status read or repeat changed the record"
    );
}

#[test]
fn u11_the_status_of_a_created_thread_reads_its_start_once() {
    let fake = NewFake::new("web_u11_created");
    let s = serve_new(&fake);
    let r = create(&s, PROJECT, &body("u11-op-2", TEXT));
    assert_eq!(r.json()["status"], "created", "{}", r.text());
    // The create's own answer carries the start, read once.
    let shows = |fake: &NewFake| {
        fake.invocations()
            .iter()
            .filter(|a| a.get(1).is_some_and(|w| w == "show"))
            .count()
    };
    assert_eq!(shows(&fake), 1, "{:?}", fake.invocations());
    assert!(r.json()["start"]["stage"].is_object(), "{}", r.text());
    let r = s.get(&status("u11-op-2"));
    assert_eq!(r.status, 200);
    assert!(
        r.json()["result"]["start"]["stage"].is_object(),
        "{}",
        r.text()
    );
    assert_eq!(shows(&fake), 2);
    assert_eq!(fake.spawn_count(), 1);
}

#[test]
fn cloud_options_share_only_an_in_progress_read() {
    use std::sync::{Arc, Condvar, Mutex};
    use std::thread;
    use std::time::Instant;

    use openwiz_adapter_cloudroom::source::CloudRoomSource;
    use openwiz_core::model::Timestamp;
    use openwiz_core::new_thread::effects::ProjectCandidate;
    use openwiz_core::new_thread::operation::{NewThreadClient, ObservedThread, SpawnRequest};
    use openwiz_core::new_thread::options::Catalogue;
    use openwiz_core::new_thread::outcome::SpawnReply;
    use openwiz_core::new_thread::start::ShownThread;
    use openwiz_core::source::SourceError;
    use openwiz_server::Limits;

    use crate::new_support::{OPTIONS, new_config, serve_config};

    // Hold the catalogue at the adapter seam until both HTTP requests
    // attach, regardless of how quickly the fake process would answer.
    struct GatedCatalogue {
        inner: CloudRoomSource,
        open: Mutex<bool>,
        opened: Condvar,
    }

    impl NewThreadClient for GatedCatalogue {
        fn name(&self) -> &str {
            NewThreadClient::name(&self.inner)
        }
        fn tested_version(&self) -> &str {
            NewThreadClient::tested_version(&self.inner)
        }
        fn cli_levels(&self) -> &[&str] {
            self.inner.cli_levels()
        }
        fn version(&self, deadline: Instant) -> Result<String, SourceError> {
            NewThreadClient::version(&self.inner, deadline)
        }
        fn projects(&self, deadline: Instant) -> Result<Vec<ProjectCandidate>, SourceError> {
            self.inner.projects(deadline)
        }
        fn catalogue(&self, deadline: Instant) -> Result<Catalogue, SourceError> {
            drop(
                self.opened
                    .wait_timeout_while(
                        self.open.lock().unwrap(),
                        deadline.saturating_duration_since(Instant::now()),
                        |open| !*open,
                    )
                    .unwrap(),
            );
            self.inner.catalogue(deadline)
        }
        fn spawn(&self, spawn: &SpawnRequest, deadline: Instant) -> SpawnReply {
            self.inner.spawn(spawn, deadline)
        }
        fn show_thread(&self, id: &str, deadline: Instant) -> Result<ShownThread, SourceError> {
            self.inner.show_thread(id, deadline)
        }
        fn threads_since(
            &self,
            project: &str,
            since: Timestamp,
            deadline: Instant,
        ) -> Result<Vec<ObservedThread>, SourceError> {
            self.inner.threads_since(project, since, deadline)
        }
    }

    // Release held runs even if a synchronization assertion fails.
    struct Release(Arc<GatedCatalogue>);
    impl Drop for Release {
        fn drop(&mut self) {
            *self.0.open.lock().unwrap() = true;
            self.0.opened.notify_all();
        }
    }

    let fake = NewFake::new("web_cloud_options_single_flight");
    let gated = Arc::new(GatedCatalogue {
        inner: fake.source(),
        open: Mutex::new(false),
        opened: Condvar::new(),
    });
    let mut config = new_config(&fake, Limits::default());
    config.creating.as_mut().unwrap().client = gated.clone();
    let s = serve_config(&fake, config);
    let release = Release(gated);
    let addr = s.addr;
    let first = thread::spawn(move || crate::http::get(addr, OPTIONS));
    let second = thread::spawn(move || crate::http::get(addr, OPTIONS));
    s.wait_for("both cloud-options requests attached", |st| {
        st.attached == 2
    });
    drop(release);

    let a = first.join().unwrap();
    let b = second.join().unwrap();
    assert_eq!(a.status, 200, "{}", a.text());
    assert_eq!(b.status, 200, "{}", b.text());
    assert_eq!(a.body, b.body, "both requests receive the shared result");
    assert_eq!(a.json()["schema"], "openwiz.cloud-options.v1");
    assert_eq!(a.json()["state"]["kind"], "offered");
    let read = vec!["cloud".to_owned(), "status".to_owned(), "--json".to_owned()];
    assert_eq!(fake.invocations(), vec![read.clone()], "one shared read");

    // Once the shared run ends, the next GET must read again.
    let later = s.get(OPTIONS);
    assert_eq!(later.status, 200, "{}", later.text());
    assert_eq!(later.json()["state"]["kind"], "offered");
    assert_eq!(fake.invocations(), vec![read.clone(), read], "no caching");
}
