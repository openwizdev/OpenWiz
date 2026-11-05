//! TK1 at the real Health/State, tool and runtime-owner boundaries.
use super::*;
use openwiz_core::source::SourceError;
use openwiz_service::{health::runtime::channel, scheduler::Scheduler, tick};
use std::{num::NonZeroU64, thread};

const RECORD: &str = "launch-fleet: fleet thread thr_syn_dead, loop loop_syn_1";

#[test]
fn r2_refreshes_the_real_current_run_before_saving_a_stalled_try() {
    use openwiz_service::scheduler::{TickMonitor, TickRun};
    use std::sync::mpsc;
    struct ObservedRuntime {
        monitor: TickMonitor,
        repairs: Arc<AtomicU64>,
    }
    impl RuntimeFixes for ObservedRuntime {
        fn current_tick(&self) -> Result<Option<TickRun>, String> {
            self.monitor.current()
        }
        fn restart_tick(&self, _: Instant) -> Result<(), String> {
            self.repairs.fetch_add(1, Ordering::SeqCst);
            Err("unexpected stale repair".into())
        }
        fn restart_stalled_tick(&self, _: TickRun, _: Instant) -> Result<(), String> {
            self.repairs.fetch_add(1, Ordering::SeqCst);
            Err("unexpected stale repair".into())
        }
        fn restart_server(&self, _: Instant) -> Result<(), String> {
            panic!("no server repair is due")
        }
    }
    let w = World::new();
    let clock = Arc::new(AtomicU64::new(2000));
    let clock_worker = clock.clone();
    let count = Arc::new(AtomicU64::new(0));
    let count_worker = count.clone();
    let release = Arc::new(AtomicU64::new(0));
    let release_worker = release.clone();
    let (entered, started) = mpsc::channel();
    let mut jobs = Scheduler::default();
    tick::register_with_control(
        &mut jobs,
        NonZeroU64::new(2).unwrap(),
        w.state.clone(),
        move || clock_worker.load(Ordering::SeqCst),
        move |stop| {
            let n = count_worker.fetch_add(1, Ordering::SeqCst);
            entered.send(n).unwrap();
            let until = Instant::now() + RUN_BUDGET;
            while (n == 0 || n == 2)
                && release_worker.load(Ordering::SeqCst) <= n
                && !stop.load(Ordering::SeqCst)
            {
                assert!(
                    Instant::now() < until,
                    "controlled release was not delivered"
                );
                thread::park_timeout(Duration::from_millis(1));
            }
            Ok(())
        },
    )
    .unwrap();
    jobs.poll(2).unwrap();
    assert_eq!(started.recv_timeout(RUN_BUDGET).unwrap(), 0);
    let observed = jobs.tick_monitor().current().unwrap().unwrap();
    release.store(1, Ordering::SeqCst);
    jobs.wait(tick::JOB).unwrap();
    clock.store(4000, Ordering::SeqCst);
    jobs.poll(4).unwrap();
    jobs.wait(tick::JOB).unwrap();
    assert_eq!(started.recv_timeout(RUN_BUDGET).unwrap(), 1);
    clock.store(6000, Ordering::SeqCst);
    jobs.poll(6).unwrap();
    assert_eq!(started.recv_timeout(RUN_BUDGET).unwrap(), 2);
    let repairs = Arc::new(AtomicU64::new(0));
    let h = engine(
        &w,
        Arc::new(ObservedRuntime {
            monitor: jobs.tick_monitor(),
            repairs: repairs.clone(),
        }),
    );
    let observation = Seen {
        cloudroom: CloudRoomSeen::Running,
        loops: Listed::Read(vec![]),
        fleet_threads: Listed::Read(vec![]),
        tick_running_since: Some(openwiz_core::model::Timestamp(observed.started_at as i64)),
        server: Known::Healthy,
    };
    let outcome = h.pass(&observation, 6100);
    release.store(3, Ordering::SeqCst);
    jobs.wait(tick::JOB).unwrap();
    outcome.unwrap();
    assert_eq!(repairs.load(Ordering::SeqCst), 0);
    assert!(
        w.state.lock().unwrap().snapshot()["incidents"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    assert!(w.posts().is_empty());
}
fn setup(w: &World) {
    let mut rows: Value =
        serde_json::from_slice(&fs::read(w.f.0.join("loops.json")).unwrap()).unwrap();
    rows[0]["paused"] = json!(false);
    fs::write(w.f.0.join("loops.json"), rows.to_string()).unwrap();
    let mut dead: Value =
        serde_json::from_slice(&fs::read(w.f.0.join("thread.json")).unwrap()).unwrap();
    dead["thread"]["id"] = json!("thr_syn_dead");
    dead["thread"]["archivedAt"] = json!(2000);
    fs::write(w.f.0.join("dead.json"), dead.to_string()).unwrap();
    fs::write(w.f.0.join("ownership"), RECORD).unwrap();
    let path = w.f.0.join("room");
    let source = fs::read_to_string(&path).unwrap().replace(
        "elif a==['--version']:",
        r#"elif a==['loop','pause','loop_syn_1','--json']:
    saved=json.loads((r/'service/state.json').read_text())
    assert saved['retired_loops'][0]['phase']=='pause_pending'
    assert any(i['check']=='fleet_thread' and any(t and t['outcome'] is None for t in i['tries'].values()) for i in saved['incidents'])
    if not (r/'deny-pause').exists():
        rows=json.loads((r/'loops.json').read_text());rows[0]['paused']=True;(r/'loops.json').write_text(json.dumps(rows))
    print('{}')
elif a==['thread','show','thr_syn_dead','--json']:print((r/'dead.json').read_text())
elif a==['--version']:"#,
    );
    place_script(&path, &source);
}
fn seen(w: &World) -> Seen {
    let mut seen = w.seen(false, false);
    seen.fleet_threads = Listed::Read(vec![SeenFleetThread {
        spec: Number::new(900).unwrap(),
        thread: Id::parse("thr_syn_dead").unwrap(),
        seen: ThreadSeen::Archived,
    }]);
    seen
}
fn github(w: &World) -> Executor {
    let base = w.github();
    let root = w.f.0.clone();
    let cs = w.comments.clone();
    let calls = w.calls.clone();
    Executor::supplied(Arc::new(move |call, deadline| {
        let args = call.argv().to_vec();
        let words = args.iter().map(String::as_str).collect::<Vec<_>>();
        let rows = || {
            let mut rows = vec![
                json!({"id":100,"body":fs::read_to_string(root.join("ownership")).unwrap(),"created":1000,"updated":1000}),
            ];
            rows.extend(cs.lock().unwrap().clone());
            rows
        };
        let result = match words.as_slice() {
            ["issue", "list", ..] => Some(
                json!([{"number":900,"id":"syn-issue-900","state":"OPEN","title":"Synthetic","body":"","labels":[],"milestone":null,"blockedBy":{"nodes":[],"totalCount":0},"subIssues":{"nodes":[{"number":901,"id":"syn-issue-901","state":"OPEN","title":"Synthetic","url":"https://example.invalid/issues/901"}],"totalCount":1}}]),
            ),
            ["api", path, ..] if path.contains("issues/900/comments?") => Some(json!(rows())),
            ["issue", "comment", "900", "--body", body] => {
                let mut comments = cs.lock().unwrap();
                let id = 7000 + comments.len() as u64;
                comments.push(json!({"id":id,"body":body,"created":4000,"updated":4000}));
                calls.lock().unwrap().push(args.clone());
                return Ok(format!("https://github.invalid/synthetic-owner/synthetic-repo/issues/900#issuecomment-{id}\n").into_bytes());
            }
            ["issue", "view", "900", "--json", "comments"] => Some(
                json!({"comments":rows().iter().map(|c|json!({"id":format!("syn-{}",c["id"]),"author":null,"authorAssociation":"OWNER","body":c["body"],"createdAt":"2023-11-14T22:13:20Z","includesCreatedEdit":false,"isMinimized":false,"minimizedReason":null,"reactionGroups":[],"url":format!("https://github.invalid/synthetic-owner/synthetic-repo/issues/900#issuecomment-{}",c["id"]),"viewerDidAuthor":true})).collect::<Vec<_>>()}),
            ),
            _ => None,
        };
        if let Some(value) = result {
            calls.lock().unwrap().push(args);
            Ok(value.to_string().into_bytes())
        } else {
            base.run(call, deadline)
        }
    }))
}
fn engine(w: &World, runtime: Arc<dyn RuntimeFixes>) -> Health {
    Health::new(
        &w.f.0,
        serde_json::from_slice(&fs::read(w.f.0.join("service/config.json")).unwrap()).unwrap(),
        w.state.clone(),
        w.f.source(),
        github(w),
        runtime,
    )
    .unwrap()
}
fn writes(w: &World) -> Vec<Value> {
    w.f.calls()
        .into_iter()
        .filter(|a| {
            a[0] == "loop" && (a[1] == "pause" || a[1] == "resume")
                || a[0] == "thread" && a[1] == "tell"
        })
        .collect()
}
#[test]
fn takeover_confirms_pause_and_saved_retirement_before_the_real_tick_replacement() {
    assert_takeover(false);
    assert_takeover(true);
}

fn assert_takeover(public: bool) {
    let mut w = World::new();
    setup(&w);
    if public {
        fs::write(
            w.f.0.join("ownership"),
            "launch-fleet: fleet active, loop loop_syn_1",
        )
        .unwrap();
        let path = w.f.0.join("service/fleet-map.json");
        fs::write(
            &path,
            json!({"repo":"synthetic-owner/synthetic-repo","threads":{"fleet:900":"thr_syn_dead"}})
                .to_string(),
        )
        .unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
    }
    let mut jobs = Scheduler::default();
    let count = Arc::new(AtomicU64::new(0));
    let worker_count = count.clone();
    let root = w.f.0.clone();
    tick::register_with_control(
        &mut jobs,
        NonZeroU64::new(2).unwrap(),
        w.state.clone(),
        || 2000,
        move |_| {
            if worker_count.fetch_add(1, Ordering::SeqCst) > 0 {
                let saved: Value =
                    serde_json::from_slice(&fs::read(root.join("service/state.json")).unwrap())
                        .unwrap();
                assert!(matches!(
                    saved["retired_loops"][0]["phase"].as_str(),
                    Some("paused" | "active")
                ));
                let rows: Value =
                    serde_json::from_slice(&fs::read(root.join("loops.json")).unwrap()).unwrap();
                assert_eq!(rows[0]["paused"], true);
            }
            Ok(())
        },
    )
    .unwrap();
    jobs.poll(2).unwrap();
    jobs.wait(tick::JOB).unwrap();
    let (control, requests) = channel();
    let health = engine(&w, control);
    let observation = seen(&w);
    let pass = thread::spawn(move || health.pass(&observation, 4000));
    // The health pass verifies retirement before sending; allow its full budget
    // for that preparation under load, while still waiting for the exact event.
    let request = requests
        .recv_timeout(RUN_BUDGET)
        .expect("health pass must request takeover within its run budget before replacement");
    assert_eq!(
        count.load(Ordering::SeqCst),
        1,
        "replacement is not yet run"
    );
    let mut server = super::super::server::server(Arc::new(|_| {}));
    assert!(!request.apply(&mut jobs, &mut server, || panic!(
        "takeover cannot replace HTTP"
    )));
    pass.join().unwrap().unwrap();
    jobs.wait(tick::JOB).unwrap();
    assert_eq!(count.load(Ordering::SeqCst), 2);
    server.shutdown(deadline()).unwrap();
    server.join();
    assert_eq!(
        w.f.calls(),
        vec![
            json!(["loop", "list", "--json"]),
            json!(["thread", "show", "thr_syn_dead", "--json"]),
            json!(["thread", "show", "thr_syn_dead", "--json"]),
            json!(["loop", "list", "--json"]),
            json!(["loop", "pause", "loop_syn_1", "--json"]),
            json!(["loop", "list", "--json"]),
            json!(["thread", "show", "thr_syn_dead", "--json"]),
        ]
    );
    assert_eq!(
        writes(&w),
        vec![json!(["loop", "pause", "loop_syn_1", "--json"])]
    );
    let snapshot = w.state.lock().unwrap().snapshot().clone();
    assert_eq!(
        snapshot["retired_loops"],
        json!([{"owner":"service_tick","spec":900,"thread":"thr_syn_dead","loop":"loop_syn_1","phase":"active","at":4000}])
    );
    assert_eq!(
        snapshot["incidents"][0]["tries"]["first"]["outcome"],
        json!({"state":"done","owner":"service_tick","retired_loop":"loop_syn_1"})
    );
    assert_eq!(w.posts().len(), 1);
    let comments = w.comments.lock().unwrap();
    let body = comments[0]["body"].as_str().unwrap();
    assert_eq!(
        body.lines().next().unwrap(),
        "openwiz-service: incident i1: the fleet thread of #900 is gone (archived); try 1 of 2, take it over: done, service tick owns the fleet, retired loop loop_syn_1"
    );
    assert_record(body);
    drop(comments);
    w.state = Arc::new(Mutex::new(State::load(&w.f.0, 5000).unwrap()));
    for now in [5000, 3_605_000] {
        engine(&w, w.runtime.clone()).pass(&seen(&w), now).unwrap();
    }
    assert_eq!(
        writes(&w),
        vec![json!(["loop", "pause", "loop_syn_1", "--json"])]
    );
    assert!(w.runtime.0.lock().unwrap().is_empty());
    assert_eq!(w.posts().len(), 1);
    assert!(
        w.state.lock().unwrap().snapshot()["incidents"]
            .as_array()
            .unwrap()
            .is_empty()
    );
}

#[test]
fn paused_fleet_candidate_is_not_resumed_before_takeover() {
    let w = World::new();
    setup(&w);
    let mut rows: Value =
        serde_json::from_slice(&fs::read(w.f.0.join("loops.json")).unwrap()).unwrap();
    rows[0]["paused"] = json!(true);
    fs::write(w.f.0.join("loops.json"), rows.to_string()).unwrap();
    engine(&w, w.runtime.clone()).pass(&seen(&w), 4000).unwrap();
    assert!(writes(&w).is_empty());
    assert_eq!(*w.runtime.0.lock().unwrap(), ["tick"]);
    assert_eq!(w.posts().len(), 1);
    assert_eq!(
        w.state.lock().unwrap().snapshot()["retired_loops"][0]["phase"],
        "active"
    );
}

struct RefuseRuntime;
impl RuntimeFixes for RefuseRuntime {
    fn restart_tick(&self, _: Instant) -> Result<(), String> {
        Err("synthetic unconfirmed stop".into())
    }
    fn restart_server(&self, _: Instant) -> Result<(), String> {
        panic!("no server repair is due")
    }
}
#[test]
fn failed_replacement_retains_pause_and_retry_never_pauses_again() {
    let mut w = World::new();
    setup(&w);
    engine(&w, Arc::new(RefuseRuntime))
        .pass(&seen(&w), 4000)
        .unwrap();
    assert_eq!(
        w.state.lock().unwrap().snapshot()["retired_loops"][0]["phase"],
        "paused"
    );
    w.state = Arc::new(Mutex::new(State::load(&w.f.0, 5000).unwrap()));
    engine(&w, w.runtime.clone()).pass(&seen(&w), 5000).unwrap();
    assert_eq!(
        writes(&w),
        vec![json!(["loop", "pause", "loop_syn_1", "--json"])]
    );
    assert_eq!(*w.runtime.0.lock().unwrap(), ["tick"]);
    assert_eq!(w.posts().len(), 2);
    assert_eq!(
        w.state.lock().unwrap().snapshot()["retired_loops"][0]["phase"],
        "active"
    );
}

#[test]
fn crash_after_pause_recovers_the_saved_try_without_repeating_that_effect() {
    for phase in ["pause_pending", "paused"] {
        let mut w = World::new();
        setup(&w);
        let mut rows: Value =
            serde_json::from_slice(&fs::read(w.f.0.join("loops.json")).unwrap()).unwrap();
        rows[0]["paused"] = json!(true);
        fs::write(w.f.0.join("loops.json"), rows.to_string()).unwrap();
        let mut value = w.state.lock().unwrap().snapshot().clone();
        value["retired_loops"] = json!([{"owner":"service_tick","spec":900,"thread":"thr_syn_dead","loop":"loop_syn_1","phase":phase,"at":4000}]);
        value["next_incident"] = json!(2);
        value["incidents"] = json!([{"id":"i1","check":"fleet_thread","spec":900,"thread":"thr_syn_dead","broken":{"state":"broken","what":"archived"},"opened_at":4000,"healthy_since":null,"tries":{"first":{"at":4000,"outcome":null,"comment":null},"second":null},"needs_you":null}]);
        w.state.lock().unwrap().save(value).unwrap();
        w.state = Arc::new(Mutex::new(State::load(&w.f.0, 5000).unwrap()));
        engine(&w, w.runtime.clone()).pass(&seen(&w), 5000).unwrap();
        assert!(writes(&w).is_empty(), "{phase}");
        assert_eq!(*w.runtime.0.lock().unwrap(), ["tick"]);
        assert_eq!(w.posts().len(), 2);
        let value = w.state.lock().unwrap().snapshot().clone();
        assert_eq!(
            value["incidents"][0]["tries"]["first"]["outcome"]["state"],
            "interrupted"
        );
        assert_eq!(
            value["incidents"][0]["tries"]["second"]["outcome"],
            json!({"state":"done","owner":"service_tick","retired_loop":"loop_syn_1"})
        );
        for c in w.comments.lock().unwrap().iter() {
            assert_record(c["body"].as_str().unwrap());
        }
    }
}
#[test]
fn unconfirmed_pause_never_replaces_and_two_tries_give_one_spec_notification() {
    let mut w = World::new();
    setup(&w);
    fs::write(w.f.0.join("deny-pause"), "").unwrap();
    for now in [4000, 5000, 6000, 7000] {
        engine(&w, w.runtime.clone()).pass(&seen(&w), now).unwrap();
    }
    w.state = Arc::new(Mutex::new(State::load(&w.f.0, 8000).unwrap()));
    engine(&w, w.runtime.clone()).pass(&seen(&w), 8000).unwrap();
    assert!(w.runtime.0.lock().unwrap().is_empty());
    let writes = writes(&w);
    assert_eq!(writes.len(), 3);
    assert_eq!(
        writes[..2],
        [
            json!(["loop", "pause", "loop_syn_1", "--json"]),
            json!(["loop", "pause", "loop_syn_1", "--json"])
        ]
    );
    assert_eq!(writes[2][1], "tell");
    assert_eq!(
        writes[2].as_array().unwrap().last().unwrap(),
        "Needs you: incident i1: the fleet thread of #900 is gone (archived); OpenWiz tried twice and couldn't fix it. Recorded on #900."
    );
    assert_eq!(w.posts().len(), 3);
    for c in w.comments.lock().unwrap().iter() {
        assert_record(c["body"].as_str().unwrap());
    }
    assert_eq!(
        w.state.lock().unwrap().snapshot()["retired_loops"][0]["phase"],
        "pause_pending"
    );
}
#[test]
fn changed_ownership_live_or_foreign_thread_and_unread_records_make_no_takeover_effect() {
    for mode in ["changed", "no-loop", "live", "foreign", "unread"] {
        let w = World::new();
        setup(&w);
        if mode == "changed" {
            fs::write(
                w.f.0.join("ownership"),
                "launch-fleet: fleet thread thr_syn_other, loop loop_syn_1",
            )
            .unwrap();
        }
        if mode == "no-loop" {
            fs::write(
                w.f.0.join("ownership"),
                "launch-fleet: fleet thread thr_syn_dead",
            )
            .unwrap();
        }
        if matches!(mode, "live" | "foreign") {
            let path = w.f.0.join("dead.json");
            let mut dead: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
            if mode == "live" {
                dead["thread"]["archivedAt"] = Value::Null;
            } else {
                dead["thread"]["projectId"] = json!("prj_syn_foreign");
            }
            fs::write(path, dead.to_string()).unwrap();
        }
        let mut source = github(&w);
        if mode == "unread" {
            let base = source;
            source = Executor::supplied(Arc::new(move |call, until| {
                if call
                    .argv()
                    .iter()
                    .any(|a| a.contains("issues/900/comments?"))
                {
                    Err(SourceError::Unavailable {
                        detail: "synthetic unread".into(),
                    })
                } else {
                    base.run(call, until)
                }
            }));
        }
        let config =
            serde_json::from_slice(&fs::read(w.f.0.join("service/config.json")).unwrap()).unwrap();
        let h = Health::new(
            &w.f.0,
            config,
            w.state.clone(),
            w.f.source(),
            source,
            w.runtime.clone(),
        )
        .unwrap();
        h.pass(&seen(&w), 4000).unwrap();
        assert!(writes(&w).is_empty(), "{mode}");
        assert!(w.posts().is_empty(), "{mode}");
        assert!(w.runtime.0.lock().unwrap().is_empty(), "{mode}");
    }
}

#[test]
fn only_exact_not_found_authorizes_takeover() {
    for (message, allowed) in [
        ("Error: HTTP 404: Thread not found", true),
        (
            "Error: HTTP 500: upstream returned HTTP 404: Thread not found",
            false,
        ),
        ("Error: HTTP 404: Thread not found (detail withheld)", false),
    ] {
        let w = World::new();
        setup(&w);
        let path = w.f.0.join("room");
        let script=fs::read_to_string(&path).unwrap().replace(
            "elif a==['thread','show','thr_syn_dead','--json']:print((r/'dead.json').read_text())",
            &format!("elif a==['thread','show','thr_syn_dead','--json']:\n    print({message:?},file=sys.stderr);sys.exit(2)")
        );
        place_script(&path, &script);
        engine(&w, w.runtime.clone()).pass(&seen(&w), 4000).unwrap();
        assert_eq!(writes(&w).len(), usize::from(allowed), "{message}");
        assert_eq!(
            w.runtime.0.lock().unwrap().len(),
            usize::from(allowed),
            "{message}"
        );
    }
}

#[test]
fn stalled_tick_cannot_bypass_an_unconfirmed_takeover_pause() {
    let w = World::new();
    setup(&w);
    fs::write(w.f.0.join("deny-pause"), "").unwrap();
    let mut observation = seen(&w);
    observation.tick_running_since = w.seen(true, false).tick_running_since;
    engine(&w, w.runtime.clone())
        .pass(&observation, 4000)
        .unwrap();
    assert!(
        w.runtime.0.lock().unwrap().is_empty(),
        "no replacement can precede confirmed retirement"
    );
}

#[test]
fn retirement_remains_visible_in_status() {
    let w = World::new();
    setup(&w);
    engine(&w, w.runtime.clone()).pass(&seen(&w), 4000).unwrap();
    let snapshot = w.state.lock().unwrap().snapshot().clone();
    let status =
        openwiz_service::state::status(&snapshot, &"a".repeat(40), 1000, 7370, Some(1000), 5000)
            .unwrap();
    assert_eq!(status["retired_loops"], snapshot["retired_loops"]);
}

#[test]
fn a_later_dead_fleet_binding_keeps_historical_outcomes_and_other_fixes_progressing() {
    let w = World::new();
    setup(&w);
    engine(&w, w.runtime.clone()).pass(&seen(&w), 4000).unwrap();
    let new_record = "launch-fleet: fleet thread thr_syn_next, loop loop_syn_next";
    fs::write(w.f.0.join("ownership"), new_record).unwrap();
    let path = w.f.0.join("dead.json");
    let mut dead: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    dead["thread"]["id"] = json!("thr_syn_next");
    fs::write(path, dead.to_string()).unwrap();
    let path = w.f.0.join("room");
    let script = fs::read_to_string(&path).unwrap().replace(
        "['thread','show','thr_syn_dead','--json']",
        "['thread','show','thr_syn_next','--json']",
    );
    place_script(&path, &script);
    let path = w.f.0.join("loops.json");
    let mut rows: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    rows.as_array_mut().unwrap().push(json!({"id":"loop_syn_next","name":"launch-fleet synthetic-owner/synthetic-repo","paused":false}));
    fs::write(path, rows.to_string()).unwrap();
    let mut observation = seen(&w);
    if let Listed::Read(rows) = &mut observation.fleet_threads {
        rows[0].thread = Id::parse("thr_syn_next").unwrap();
    }
    observation.server = Known::Broken(ServerBroken::Refused);
    engine(&w, w.runtime.clone())
        .pass(&observation, 5000)
        .unwrap();
    assert_eq!(*w.runtime.0.lock().unwrap(), ["tick", "server"]);
    let snapshot = w.state.lock().unwrap().snapshot().clone();
    assert_eq!(
        snapshot["incidents"][0]["tries"]["first"]["outcome"]["retired_loop"],
        "loop_syn_1"
    );
    assert_eq!(snapshot["incidents"][0]["thread"], "thr_syn_next");
}

#[test]
fn healing_keeps_uncertain_record_delivery_until_its_exact_late_readback() {
    let w = World::new();
    setup(&w);
    let base = github(&w);
    let calls = w.calls.clone();
    let source = Executor::supplied(Arc::new(move |call, until| {
        let args = call.argv();
        if args.get(1).is_some_and(|s| s == "comment") && args.get(2).is_some_and(|s| s == "900") {
            calls.lock().unwrap().push(args.to_vec());
            return Err(SourceError::Unavailable {
                detail: "synthetic claim then lost dispatch".into(),
            });
        }
        base.run(call, until)
    }));
    let config =
        serde_json::from_slice(&fs::read(w.f.0.join("service/config.json")).unwrap()).unwrap();
    let h = Health::new(
        &w.f.0,
        config,
        w.state.clone(),
        w.f.source(),
        source,
        w.runtime.clone(),
    )
    .unwrap();
    for now in [4000, 5000, 3_605_000, 3_606_000] {
        assert!(
            h.pass(&seen(&w), now).is_err(),
            "pending delivery remains reported at {now}"
        );
    }
    assert!(
        w.state.lock().unwrap().snapshot()["incidents"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    let mut other = seen(&w);
    other.server = Known::Broken(ServerBroken::Refused);
    assert!(h.pass(&other, 3_607_000).is_err());
    assert_eq!(*w.runtime.0.lock().unwrap(), ["tick", "server"]);
    let calls = w.calls.lock().unwrap();
    let posts = calls
        .iter()
        .filter(|a| {
            a.get(1).is_some_and(|s| s == "comment") && a.get(2).is_some_and(|s| s == "900")
        })
        .collect::<Vec<_>>();
    assert_eq!(posts.len(), 1);
    let body = posts[0][4].clone();
    drop(calls);
    w.comments
        .lock()
        .unwrap()
        .push(json!({"id":9000,"body":body,"created":4000,"updated":4000}));
    h.pass(&other, 3_608_000).unwrap();
    assert_eq!(
        w.calls
            .lock()
            .unwrap()
            .iter()
            .filter(|a| a.get(1).is_some_and(|s| s == "comment")
                && a.get(2).is_some_and(|s| s == "900"))
            .count(),
        1
    );
}

#[test]
fn public_fleet_observation_is_unread_until_the_private_owner_is_proven() {
    for mode in [
        "good",
        "missing",
        "wrong-repository",
        "missing-owner",
        "bad-id",
        "duplicate-key",
        "unsafe-mode",
        "public-legacy",
        "unknown-legacy",
        "bad-legacy-loop",
    ] {
        let w = World::new();
        setup(&w);
        fs::write(
            w.f.0.join("ownership"),
            "launch-fleet: fleet active, loop loop_syn_1",
        )
        .unwrap();
        if mode.ends_with("legacy") {
            fs::write(w.f.0.join("ownership"), RECORD).unwrap();
            fs::write(
                w.f.0.join(if mode == "public-legacy" {
                    "public-privacy"
                } else {
                    "unknown-privacy"
                }),
                "",
            )
            .unwrap();
        }
        if mode == "bad-legacy-loop" {
            fs::write(
                w.f.0.join("ownership"),
                "launch-fleet: fleet thread thr_syn_dead, loop invalid loop",
            )
            .unwrap();
        }
        let path = w.f.0.join("service/fleet-map.json");
        let mut map =
            json!({"repo":"synthetic-owner/synthetic-repo","threads":{"fleet:900":"thr_syn_dead"}});
        if mode == "wrong-repository" {
            map["repo"] = json!("synthetic-owner/other");
        }
        if mode == "missing-owner" {
            map["threads"] = json!({});
        }
        if mode == "bad-id" {
            map["threads"]["fleet:900"] = json!("-bad");
        }
        if mode != "missing" {
            let text = if mode == "duplicate-key" {
                map.to_string()
                    .replace("\"threads\":", "\"threads\":{},\"threads\":")
            } else {
                map.to_string()
            };
            fs::write(&path, text).unwrap();
            fs::set_permissions(
                &path,
                fs::Permissions::from_mode(if mode == "unsafe-mode" { 0o644 } else { 0o600 }),
            )
            .unwrap();
        }
        let server = super::super::server::server(Arc::new(|_| {}));
        let observed = engine(&w, w.runtime.clone())
            .observe(server.local_addr().port())
            .unwrap();
        server.shutdown(deadline()).unwrap();
        server.join();
        match observed.fleet_threads {
            Listed::Read(rows) if mode == "good" => {
                assert_eq!(rows.len(), 1);
                assert_eq!(rows[0].thread.as_str(), "thr_syn_dead");
                assert_eq!(rows[0].spec.get(), 900);
            }
            Listed::Unread(_) if mode != "good" => {}
            other => panic!("{mode}: {other:?}"),
        }
        assert!(writes(&w).is_empty(), "observations never write");
        assert!(w.posts().is_empty());
    }
}
