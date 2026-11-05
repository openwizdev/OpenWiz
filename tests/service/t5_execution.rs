//! C3/C4 at the health executor: actual State and recording tool fakes.
use super::*;
use openwiz_adapter_github::process::Executor;
use openwiz_core::health::model::*;
use openwiz_service::{
    health::{Health, RuntimeFixes},
    state::State,
};
use serde_json::{Value, json};
use std::sync::{Arc, Mutex, atomic::AtomicBool};
struct Runtime(
    Mutex<Vec<&'static str>>,
    Mutex<Option<openwiz_service::scheduler::TickRun>>,
);
impl RuntimeFixes for Runtime {
    fn current_tick(&self) -> Result<Option<openwiz_service::scheduler::TickRun>, String> {
        Ok(*self.1.lock().unwrap())
    }
    fn restart_stalled_tick(
        &self,
        expected: openwiz_service::scheduler::TickRun,
        _: Instant,
    ) -> Result<(), String> {
        if *self.1.lock().unwrap() != Some(expected) {
            return Err("synthetic run changed".into());
        }
        self.0.lock().unwrap().push("tick");
        Ok(())
    }
    fn restart_tick(&self, _: Instant) -> Result<(), String> {
        self.0.lock().unwrap().push("tick");
        Ok(())
    }
    fn restart_server(&self, _: Instant) -> Result<(), String> {
        self.0.lock().unwrap().push("server");
        Ok(())
    }
}
struct World {
    f: Fixture,
    state: Arc<Mutex<State>>,
    runtime: Arc<Runtime>,
    calls: Arc<Mutex<Vec<Vec<String>>>>,
    comments: Arc<Mutex<Vec<Value>>>,
    lose: Arc<AtomicBool>,
    drop_record: Arc<AtomicBool>,
}

#[path = "t5_takeover_execution.rs"]
mod takeover;
impl World {
    fn new() -> Self {
        let f = Fixture::new();
        let state = super::restart::state(&f);
        let mut thread: Value = serde_json::from_str(include_str!(
            "../fixtures/room-cli-0.43.1/normal/thread-show-0001.json"
        ))
        .unwrap();
        thread["thread"]["projectId"] = json!("prj_syn_1");
        fs::write(f.0.join("thread.json"), thread.to_string()).unwrap();
        fs::write(
            f.0.join("tell.json"),
            include_str!("../fixtures/room-cli-0.43.1/send/tell-cloud-queue-observed.json"),
        )
        .unwrap();
        place_script(
            &f.0.join("room"),
            r#"#!/usr/bin/python3
import json,pathlib,sys
r=pathlib.Path(__file__).parent;a=sys.argv[1:]
with (r/'calls').open('a') as f:f.write(json.dumps(a)+'\n')
if a==['loop','list','--json']:print((r/'loops.json').read_text())
elif a==['loop','resume','loop_syn_1','--json']:
    if not (r/'fail-loop').exists():
        rows=json.loads((r/'loops.json').read_text());rows[0]['paused']=False;(r/'loops.json').write_text(json.dumps(rows))
    print('{}')
elif a==['--version']:print('v127')
elif a==['thread','show','thr_syn_0001','--json']:print((r/'thread.json').read_text())
elif a[:2]==['thread','list']:print(json.dumps([{'id':'thr_syn_0001','queuedWork':'none','hasPendingInteraction':False}]))
elif a[:2]==['thread','tell']:print((r/'tell.json').read_text())
else:sys.exit(2)
"#,
        );
        // Match the complete config's explicit orchestrator target.
        let config_path = f.0.join("service/config.json");
        let mut config: Value = serde_json::from_slice(&fs::read(&config_path).unwrap()).unwrap();
        config["orchestrator_thread"] = json!("thr_syn_0001");
        fs::write(config_path, config.to_string()).unwrap();
        Self {
            f,
            state,
            runtime: Arc::new(Runtime(Mutex::new(Vec::new()), Mutex::new(None))),
            calls: Arc::new(Mutex::new(Vec::new())),
            comments: Arc::new(Mutex::new(Vec::new())),
            lose: Arc::new(AtomicBool::new(false)),
            drop_record: Arc::new(AtomicBool::new(false)),
        }
    }
    fn github(&self) -> Executor {
        let calls = self.calls.clone();
        let comments = self.comments.clone();
        let lose = self.lose.clone();
        let root = self.f.0.clone();
        let drop_record = self.drop_record.clone();
        Executor::supplied(Arc::new(move |call, _| {
            let args = call
                .argv()
                .iter()
                .map(|s| s.to_string())
                .collect::<Vec<_>>();
            calls.lock().unwrap().push(args.clone());
            let words = args.iter().map(String::as_str).collect::<Vec<_>>();
            let mut cs = comments.lock().unwrap();
            let v = match &words[..] {
                ["issue", "list", ..] => json!([]),
                ["repo", "view", "--json", "nameWithOwner,isPrivate"] => {
                    if root.join("unknown-privacy").exists() {
                        return Err(openwiz_core::source::SourceError::Unavailable {
                            detail: "synthetic metadata unread".into(),
                        });
                    }
                    json!({"nameWithOwner":"synthetic-owner/synthetic-repo","isPrivate":!root.join("public-privacy").exists()})
                }
                ["repo", "view", ..] => {
                    json!({"defaultBranchRef":{"name":"main"},"nameWithOwner":"synthetic-owner/synthetic-repo","url":"https://github.invalid/synthetic-owner/synthetic-repo"})
                }
                ["api", path, ..] if path.contains("/comments?") => json!(*cs),
                ["issue", "comment", "901", "--body", body] => {
                    let id = 7000 + cs.len() as u64;
                    if !drop_record.load(Ordering::SeqCst) {
                        cs.push(json!({"id":id,"body":body,"created":2000,"updated":2000}));
                    }
                    if lose.swap(false, Ordering::SeqCst) {
                        return Err(openwiz_core::source::SourceError::Unavailable {
                            detail: "synthetic lost reply".into(),
                        });
                    }
                    return Ok(format!("https://github.invalid/synthetic-owner/synthetic-repo/issues/901#issuecomment-{id}\n").into_bytes());
                }
                ["issue", "view", "901", "--json", "comments"] => {
                    json!({"comments":cs.iter().map(|c|json!({"id":format!("syn-{}",c["id"]),"author":null,"authorAssociation":"OWNER","body":c["body"],"createdAt":"2023-11-14T22:13:20Z","includesCreatedEdit":false,"isMinimized":false,"minimizedReason":null,"reactionGroups":[],"url":format!("https://github.invalid/synthetic-owner/synthetic-repo/issues/901#issuecomment-{}",c["id"]),"viewerDidAuthor":true})).collect::<Vec<_>>()})
                }
                _ => {
                    return Err(openwiz_core::source::SourceError::Unavailable {
                        detail: "unexpected synthetic health call".into(),
                    });
                }
            };
            Ok(v.to_string().into_bytes())
        }))
    }
    fn engine(&self) -> Health {
        let config: Value =
            serde_json::from_slice(&fs::read(self.f.0.join("service/config.json")).unwrap())
                .unwrap();
        Health::new(
            &self.f.0,
            config,
            self.state.clone(),
            self.f.source(),
            self.github(),
            self.runtime.clone(),
        )
        .unwrap()
    }
    fn seen(&self, tick: bool, server: bool) -> Seen {
        *self.runtime.1.lock().unwrap() = tick.then_some(openwiz_service::scheduler::TickRun {
            generation: std::thread::current().id(),
            started_at: 1000,
        });
        let mut state = self.state.lock().unwrap();
        let mut value = state.snapshot().clone();
        value["tick"]["running"] = if tick {
            json!({"started_at":1000})
        } else {
            Value::Null
        };
        state.save(value).unwrap();
        drop(state);
        Seen {
            cloudroom: CloudRoomSeen::Running,
            loops: Listed::Read(self.f.source().health_loops(deadline()).unwrap()),
            tick_running_since: tick.then_some(openwiz_core::model::Timestamp(1000)),
            fleet_threads: Listed::Read(Vec::new()),
            server: if server {
                Known::Broken(ServerBroken::Refused)
            } else {
                Known::Healthy
            },
        }
    }
    fn posts(&self) -> Vec<Vec<String>> {
        self.calls
            .lock()
            .unwrap()
            .iter()
            .filter(|a| a.get(1).is_some_and(|s| s == "comment"))
            .cloned()
            .collect()
    }
}
#[test]
fn every_independent_fix_has_one_exact_record_and_no_foreign_loop_write() {
    let w = World::new();
    w.engine().pass(&w.seen(true, true), 4000).unwrap();
    assert_eq!(*w.runtime.0.lock().unwrap(), ["tick", "server"]);
    assert_eq!(w.posts().len(), 3);
    let cs = w.comments.lock().unwrap();
    for c in cs.iter() {
        assert_record(c["body"].as_str().unwrap());
    }
    let lines = cs
        .iter()
        .map(|c| c["body"].as_str().unwrap().lines().next().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(
        lines,
        [
            "openwiz-service: incident i1: the loop loop_syn_1 (launch-fleet synthetic-owner/synthetic-repo) is paused; try 1 of 2, resume it: done",
            "openwiz-service: incident i2: the tick is stalled; try 1 of 2, restart it: done",
            "openwiz-service: incident i3: the server is down (refused); try 1 of 2, restart it: done"
        ]
    );
    let tries = w.state.lock().unwrap().snapshot()["incidents"].clone();
    assert!(
        tries
            .as_array()
            .unwrap()
            .iter()
            .all(|i| i["tries"]["first"]["comment"].as_u64().is_some())
    );
    assert_eq!(
        w.f.calls()
            .iter()
            .filter(|a| a[0] == "loop" && a[1] == "resume")
            .cloned()
            .collect::<Vec<_>>(),
        vec![json!(["loop", "resume", "loop_syn_1", "--json"])]
    );
}
#[test]
fn two_failed_tries_emit_one_needs_you_and_restart_replays_no_effect() {
    let mut w = World::new();
    fs::write(w.f.0.join("fail-loop"), "").unwrap();
    for now in [4000, 5000, 6000, 7000] {
        w.engine().pass(&w.seen(false, false), now).unwrap();
    }
    let saved = State::load(&w.f.0, 7000).unwrap();
    w.state = Arc::new(Mutex::new(saved));
    w.engine().pass(&w.seen(false, false), 8000).unwrap();
    let mut rows: Value =
        serde_json::from_slice(&fs::read(w.f.0.join("loops.json")).unwrap()).unwrap();
    rows[0]["name"] = json!("launch-fleet synthetic-owner/synthetic-repo (PC hub)");
    fs::write(w.f.0.join("loops.json"), rows.to_string()).unwrap();
    w.engine().pass(&w.seen(false, false), 9000).unwrap();
    assert_eq!(w.posts().len(), 3);
    assert_eq!(
        w.f.calls()
            .iter()
            .filter(|a| a[0] == "loop" && a[1] == "resume")
            .count(),
        2
    );
    assert_eq!(
        w.f.calls()
            .iter()
            .filter(|a| a[0] == "thread" && a[1] == "tell")
            .count(),
        1
    );
    let cs = w.comments.lock().unwrap();
    assert_eq!(
        cs[2]["body"].as_str().unwrap().lines().next().unwrap(),
        "**Needs you:** incident i1: the loop loop_syn_1 (launch-fleet synthetic-owner/synthetic-repo) is paused; OpenWiz tried twice and couldn't fix it."
    );
    let tell =
        w.f.calls()
            .into_iter()
            .find(|a| a[0] == "thread" && a[1] == "tell")
            .unwrap();
    assert_eq!(
        tell.as_array().unwrap().last().unwrap(),
        "Needs you: incident i1: the loop loop_syn_1 (launch-fleet synthetic-owner/synthetic-repo) is paused; OpenWiz tried twice and couldn't fix it. Recorded on #901."
    );
}
#[test]
fn lost_record_reply_is_reconciled_without_another_post_or_resume() {
    let w = World::new();
    w.lose.store(true, Ordering::SeqCst);
    assert!(w.engine().pass(&w.seen(false, false), 4000).is_err());
    w.engine().pass(&w.seen(false, false), 5000).unwrap();
    assert_eq!(w.posts().len(), 1);
    assert_eq!(
        w.f.calls()
            .iter()
            .filter(|a| a[0] == "loop" && a[1] == "resume")
            .count(),
        1
    );
}
#[test]
fn uncertain_absent_record_never_gets_a_second_post() {
    let w = World::new();
    w.lose.store(true, Ordering::SeqCst);
    w.drop_record.store(true, Ordering::SeqCst);
    assert!(w.engine().pass(&w.seen(false, false), 4000).is_err());
    assert!(w.engine().pass(&w.seen(false, false), 5000).is_err());
    assert_eq!(w.posts().len(), 1);
}
#[test]
fn state_save_failure_precedes_every_effect() {
    let w = World::new();
    let seen = w.seen(false, false);
    fs::remove_file(w.f.0.join("service/state.json")).unwrap();
    DirBuilder::new()
        .mode(0o700)
        .create(w.f.0.join("service/state.json"))
        .unwrap();
    let before = w.f.calls();
    assert!(w.engine().pass(&seen, 4000).is_err());
    assert_eq!(w.f.calls(), before);
    assert!(w.posts().is_empty());
    assert!(w.runtime.0.lock().unwrap().is_empty());
}

#[test]
fn observation_uses_the_owned_loop_inventory_tick_state_and_actual_health_route() {
    let w = World::new();
    let server = super::server::server(Arc::new(|_| {}));
    let observed = w.engine().observe(server.local_addr().port()).unwrap();
    assert_eq!(observed.cloudroom, CloudRoomSeen::Running);
    assert_eq!(observed.server, Known::Healthy);
    assert_eq!(observed.tick_running_since, None);
    assert!(matches!(observed.fleet_threads,Listed::Read(ref rows) if rows.is_empty()));
    assert!(matches!(observed.loops,Listed::Read(ref rows) if rows.len()==2 && rows[0].paused));
    server.shutdown(deadline()).unwrap();
    server.join();
}
#[test]
fn probe_distinguishes_refused_and_wrong_answer() {
    use std::{
        io::{Read, Write},
        net::TcpListener,
        thread,
    };
    let w = World::new();
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    assert_eq!(
        w.engine().observe(port).unwrap().server,
        Known::Broken(ServerBroken::Refused)
    );
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let port = listener.local_addr().unwrap().port();
    let responder = thread::spawn(move || {
        let (mut socket, _) = listener.accept().unwrap();
        let mut request = Vec::new();
        let mut byte = [0];
        while !request.ends_with(b"\r\n\r\n") {
            socket.read_exact(&mut byte).unwrap();
            request.push(byte[0]);
        }
        let body = r#"{"server":{"name":"other"}}"#;
        write!(
            socket,
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n{body}",
            body.len()
        )
        .unwrap();
    });
    let result = w.engine().observe(port).unwrap();
    responder.join().unwrap();
    assert_eq!(result.server, Known::Broken(ServerBroken::WrongAnswer));
}
#[test]
fn registered_health_job_keeps_its_cadence_and_other_jobs() {
    use openwiz_service::scheduler::Scheduler;
    use std::num::NonZeroU64;
    let w = World::new();
    let server = super::server::server(Arc::new(|_| {}));
    let mut jobs = Scheduler::default();
    Arc::new(w.engine())
        .register(&mut jobs, server.local_addr().port(), || 4000)
        .unwrap();
    let count = Arc::new(AtomicU64::new(0));
    let other = count.clone();
    jobs.register("synthetic-other", NonZeroU64::new(1).unwrap(), move || {
        other.fetch_add(1, Ordering::SeqCst);
    })
    .unwrap();
    assert_eq!(jobs.poll(59).unwrap(), ["synthetic-other"]);
    jobs.wait("synthetic-other").unwrap();
    assert_eq!(jobs.poll(60).unwrap(), ["health", "synthetic-other"]);
    jobs.wait("health").unwrap();
    jobs.wait("synthetic-other").unwrap();
    assert_eq!(w.posts().len(), 1);
    assert_eq!(w.state.lock().unwrap().snapshot()["last_pass"]["at"], 4000);
    assert_eq!(jobs.poll(119).unwrap(), ["synthetic-other"]);
    jobs.wait("synthetic-other").unwrap();
    assert_eq!(jobs.poll(120).unwrap(), ["health", "synthetic-other"]);
    jobs.wait("health").unwrap();
    jobs.wait("synthetic-other").unwrap();
    assert_eq!(w.posts().len(), 1);
    assert_eq!(count.load(Ordering::SeqCst), 4);
    server.shutdown(deadline()).unwrap();
    server.join();
}

#[test]
fn foreign_project_notification_target_is_never_sent_a_message() {
    let w = World::new();
    fs::write(w.f.0.join("fail-loop"), "").unwrap();
    w.engine().pass(&w.seen(false, false), 4000).unwrap();
    w.engine().pass(&w.seen(false, false), 5000).unwrap();
    let path = w.f.0.join("thread.json");
    let mut thread: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    thread["thread"]["projectId"] = json!("prj_syn_foreign");
    fs::write(path, thread.to_string()).unwrap();
    assert!(w.engine().pass(&w.seen(false, false), 6000).is_err());
    assert_eq!(
        w.f.calls()
            .iter()
            .filter(|a| a[0] == "thread" && a[1] == "tell")
            .count(),
        0
    );
}

#[path = "../fleet/schema.rs"]
mod schema;
fn assert_record(body: &str) {
    assert!(
        !body.contains("thr_"),
        "public record exposes a thread: {body}"
    );
    let data = body
        .split_once("\n\n```json\n")
        .unwrap()
        .1
        .strip_suffix("\n```")
        .unwrap();
    let record: Value = serde_json::from_str(data).unwrap();
    let contract: Value =
        serde_json::from_str(include_str!("../../contracts/service.v1.schema.json")).unwrap();
    assert_eq!(
        schema::validate(&contract, &record),
        Vec::<String>::new(),
        "{record}"
    );
}
#[test]
fn recovered_interrupted_try_gets_a_record_without_redispatch() {
    use openwiz_core::{health, messaging::OpId, model::Timestamp};
    let mut w = World::new();
    let seen = w.seen(false, false);
    let plan = health::plan(
        &Incidents::default(),
        &seen,
        &Rules {
            repository: repo(),
            tick_every_s: std::num::NonZeroU64::new(2).unwrap(),
        },
        Timestamp(4000),
        &mut || OpId::parse("syn-recovery-notification").unwrap(),
    );
    {
        let mut state = w.state.lock().unwrap();
        let mut v = state.snapshot().clone();
        v["incidents"] = serde_json::to_value(plan.incidents.incidents).unwrap();
        v["next_incident"] = json!(plan.incidents.next_incident);
        v["last_pass"] = serde_json::to_value(plan.pass).unwrap();
        state.save(v).unwrap();
    }
    w.state = Arc::new(Mutex::new(State::load(&w.f.0, 5000).unwrap()));
    let mut unread_seen = seen;
    unread_seen.loops = Listed::Unread(Unread {
        gap: Gap::TimedOut,
        reason: NonEmpty::new("synthetic unread loop inventory").unwrap(),
    });
    let before = w.f.calls();
    w.engine().pass(&unread_seen, 5000).unwrap();
    assert_eq!(w.f.calls(), before);
    let cs = w.comments.lock().unwrap();
    assert_eq!(cs.len(), 1);
    let body = cs[0]["body"].as_str().unwrap();
    assert_eq!(
        body.lines().next().unwrap(),
        "openwiz-service: incident i1: the loop loop_syn_1 (launch-fleet synthetic-owner/synthetic-repo) is paused; try 1 of 2, resume it: interrupted"
    );
    assert_record(body);
}
#[test]
fn missing_fleet_record_dispatches_nothing_and_consumes_no_try() {
    let w = World::new();
    let mut seen = w.seen(false, false);
    seen.fleet_threads = Listed::Read(vec![SeenFleetThread {
        spec: Number::new(900).unwrap(),
        thread: Id::parse("thr_syn_dead").unwrap(),
        seen: ThreadSeen::Archived,
    }]);
    seen.loops = Listed::Read(vec![]);
    let before = w.state.lock().unwrap().snapshot().clone();
    let calls = w.f.calls();
    w.engine().pass(&seen, 4000).unwrap();
    let after = w.state.lock().unwrap().snapshot().clone();
    assert_eq!(after["incidents"], before["incidents"]);
    assert_eq!(after["next_incident"], before["next_incident"]);
    assert_eq!(w.f.calls(), calls);
    assert!(w.posts().is_empty());
    assert!(w.runtime.0.lock().unwrap().is_empty());
}

#[test]
fn failed_notification_cannot_block_unrelated_fixes_or_incident_healing() {
    let w = World::new();
    fs::write(w.f.0.join("fail-loop"), "").unwrap();
    w.engine().pass(&w.seen(false, false), 4000).unwrap();
    w.engine().pass(&w.seen(false, false), 5000).unwrap();
    let path = w.f.0.join("thread.json");
    let mut thread: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    thread["thread"]["projectId"] = json!("prj_syn_foreign");
    fs::write(path, thread.to_string()).unwrap();
    assert!(w.engine().pass(&w.seen(false, false), 6000).is_err());
    assert!(w.engine().pass(&w.seen(false, true), 7000).is_err());
    assert_eq!(
        *w.runtime.0.lock().unwrap(),
        ["server"],
        "old notification failure cannot gate another check"
    );
    let mut rows: Value =
        serde_json::from_slice(&fs::read(w.f.0.join("loops.json")).unwrap()).unwrap();
    rows[0]["paused"] = json!(false);
    fs::write(w.f.0.join("loops.json"), rows.to_string()).unwrap();
    assert!(w.engine().pass(&w.seen(false, false), 9000).is_err());
    assert!(w.engine().pass(&w.seen(false, false), 3_609_000).is_err());
    assert_eq!(w.state.lock().unwrap().snapshot()["incidents"], json!([]));
    assert_eq!(
        w.f.calls()
            .iter()
            .filter(|a| a[0] == "thread" && a[1] == "tell")
            .count(),
        0
    );
}

/// O9/2141: public records project private saved identities, including nested
/// legacy takeover outcomes. The old schema/exact-line cases never checked
/// this boundary, and frozen pre-upgrade drafts could bypass a new renderer.
#[test]
fn public_fleet_records_project_private_history_and_refuse_unsafe_frozen_drafts() {
    for frozen in ["none", "legacy", "escaped", "legacy-alias", "bad-shape"] {
        let w = World::new();
        let mut seen = w.seen(false, false);
        seen.loops = Listed::Read(vec![]);
        seen.fleet_threads = Listed::Unread(Unread {
            gap: Gap::TimedOut,
            reason: NonEmpty::new("synthetic fleet source unread").unwrap(),
        });
        let saved = json!({"id":"i1","check":"fleet_thread","spec":901,
            "thread":"thr_syn_old","opened_at":1000,"broken":{"state":"broken","what":"archived"},
            "healthy_since":null,"tries":{
                "first":{"at":2000,"outcome":{"state":"done","thread":"thr_syn_new"},"comment":null},
                "second":{"at":3000,"outcome":{"state":"failed","gap":"command_failed","reason":"synthetic refusal"},"comment":null}},
            "needs_you":{"at":3000,"op_id":"synthetic-public-record","comment":null}});
        {
            let mut state = w.state.lock().unwrap();
            let mut value = state.snapshot().clone();
            value["incidents"] = json!([saved]);
            value["next_incident"] = json!(2);
            state.save(value).unwrap();
        }
        if frozen != "none" {
            let dir = w.f.0.join("service/health");
            DirBuilder::new().mode(0o700).create(&dir).unwrap();
            let body = if frozen == "legacy" {
                "openwiz-service: synthetic legacy draft thr_syn_old\n\n```json\n{\"thread\":\"thr_syn_old\"}\n```"
            } else if frozen == "legacy-alias" {
                "openwiz-service: synthetic legacy owner\n\n```json\n{\"schema\":\"openwiz.service-record.v1\",\"kind\":\"fix\",\"at\":2000,\"incident\":\"i1\",\"check\":\"fleet_thread\",\"spec\":901,\"thread\":\"synthetic_legacy_owner\",\"broken\":{\"state\":\"broken\",\"what\":\"archived\"},\"fix\":\"take_over_fleet_thread\",\"try\":1,\"outcome\":{\"state\":\"done\",\"thread\":\"synthetic_new_owner\"}}\n```"
            } else if frozen == "bad-shape" {
                "openwiz-service: synthetic invalid draft\n\n```json\ntrue\n```"
            } else {
                "openwiz-service: synthetic draft\n\n```json\n{\"reason\":\"thr\\u005fsyn_old\"}\n```"
            };
            // Quarantine every pending body in this privacy-only table. The
            // separate R2 case proves unrelated deliveries/repairs still run.
            for key in [
                "901/i1/1000/first/2000",
                "901/i1/1000/second/3000",
                "901/\"synthetic-public-record\"",
            ] {
                let key = openwiz_core::messaging::sha256_hex(key.as_bytes());
                let path = dir.join(format!("body-{key}"));
                fs::write(
                    &path,
                    json!({"body":body,"sha256":openwiz_core::messaging::sha256_hex(body.as_bytes())})
                        .to_string(),
                )
                .unwrap();
                fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
            }
        }
        let result = w.engine().pass(&seen, 4000);
        if frozen != "none" {
            assert!(
                result.is_err(),
                "unsafe old draft must block public delivery"
            );
            assert!(w.posts().is_empty());
            assert!(w.f.calls().iter().all(|a| a[1] != "tell"));
        } else {
            result.unwrap();
            assert_eq!(w.posts().len(), 3);
            for comment in w.comments.lock().unwrap().iter() {
                assert_record(comment["body"].as_str().unwrap());
            }
        }
        let state = w.state.lock().unwrap();
        assert_eq!(state.snapshot()["incidents"][0]["thread"], "thr_syn_old");
        assert_eq!(
            state.snapshot()["incidents"][0]["tries"]["first"]["outcome"]["thread"],
            "thr_syn_new"
        );
    }
}

// Synthetic pre-upgrade record: its operational thread fields were legal in
// the old private history, but are never eligible for new public delivery.
const LEGACY_FLEET_BODY: &str = "openwiz-service: incident i1: the fleet thread thr_syn_old of #901 is gone (archived); try 1 of 2, take it over: done, new fleet thread thr_syn_new\n\n```json\n{\"schema\":\"openwiz.service-record.v1\",\"kind\":\"fix\",\"at\":2000,\"incident\":\"i1\",\"check\":\"fleet_thread\",\"spec\":901,\"thread\":\"thr_syn_old\",\"broken\":{\"state\":\"broken\",\"what\":\"archived\"},\"fix\":\"take_over_fleet_thread\",\"try\":1,\"outcome\":{\"state\":\"done\",\"thread\":\"thr_syn_new\"}}\n```";

/// R1: a claim outlives its incident. Public-delivery policy must not prevent
/// read-only confirmation of its unique late original comment after upgrade.
#[test]
fn legacy_claim_after_healing_gets_its_original_receipt_only_by_unique_readback() {
    let mut w = World::new();
    let mut seen = w.seen(false, false);
    seen.loops = Listed::Read(vec![]);
    let dir = w.f.0.join("service/health");
    DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let digest =
        openwiz_core::messaging::sha256_hex(format!("901\n{LEGACY_FLEET_BODY}").as_bytes());
    let claim = dir.join(&digest);
    let bytes = json!({"issue":901,"body":LEGACY_FLEET_BODY})
        .to_string()
        .into_bytes();
    fs::write(&claim, &bytes).unwrap();
    fs::set_permissions(&claim, fs::Permissions::from_mode(0o600)).unwrap();
    let receipt = dir.join(format!("confirmed-{digest}"));
    assert!(
        w.state.lock().unwrap().snapshot()["incidents"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    assert!(w.engine().pass(&seen, 4000).is_err());
    assert!(!receipt.exists(), "absence is not delivery confirmation");
    for id in [8001, 8002] {
        w.comments
            .lock()
            .unwrap()
            .push(json!({"id":id,"body":LEGACY_FLEET_BODY,"created":2000,"updated":2000}));
    }
    assert!(w.engine().pass(&seen, 5000).is_err());
    assert!(!receipt.exists(), "ambiguous exact readback stays pending");
    w.comments.lock().unwrap().pop();
    w.state = Arc::new(Mutex::new(State::load(&w.f.0, 6000).unwrap()));
    w.engine()
        .pass(&seen, 6000)
        .expect("the unique original late comment must settle the old claim");
    let recorded: Value = serde_json::from_slice(&fs::read(&receipt).unwrap()).unwrap();
    assert_eq!(recorded, json!({"comment":8001}));
    assert_eq!(
        fs::read(&claim).unwrap(),
        bytes,
        "never rebind the original claim"
    );
    assert!(w.posts().is_empty(), "reconciliation cannot POST again");
    assert!(w.f.calls().iter().all(|a| a[1] != "tell"));
    assert!(w.runtime.0.lock().unwrap().is_empty());
}

/// R2: a delivery quarantine is not journal corruption. Repeated passes must
/// still repair unrelated tick/server faults and heal known-healthy incidents.
#[test]
fn quarantined_frozen_delivery_keeps_other_repairs_and_healing_progressing() {
    for notification in [false, true] {
        for corrupt in [false, true] {
            let mut w = World::new();
            let mut loops: Value =
                serde_json::from_slice(&fs::read(w.f.0.join("loops.json")).unwrap()).unwrap();
            loops[0]["paused"] = json!(false);
            fs::write(w.f.0.join("loops.json"), loops.to_string()).unwrap();
            let fleet = json!({"id":"i1","check":"fleet_thread","spec":901,
                "thread":"thr_syn_old","opened_at":1000,"broken":{"state":"broken","what":"archived"},
                "healthy_since":null,"tries":{
                    "first":{"at":2000,"outcome":{"state":"done","thread":"thr_syn_new"},"comment":if notification {json!(6100)} else {Value::Null}},
                    "second":if notification {json!({"at":3000,"outcome":{"state":"failed","gap":"command_failed","reason":"synthetic refusal"},"comment":6101})} else {Value::Null}},
                "needs_you":if notification {json!({"at":3000,"op_id":"synthetic-quarantined-notification","comment":null})} else {Value::Null}});
            let healing = json!({"id":"i2","check":"loop","loop":{"id":"loop_syn_1","name":"launch-fleet synthetic-owner/synthetic-repo"},
                "opened_at":1000,"broken":{"state":"broken","what":"paused"},"healthy_since":null,
                "tries":{"first":{"at":2000,"outcome":{"state":"done"},"comment":6102},"second":null},"needs_you":null});
            {
                let mut state = w.state.lock().unwrap();
                let mut value = state.snapshot().clone();
                value["incidents"] = json!([fleet, healing]);
                value["next_incident"] = json!(3);
                state.save(value).unwrap();
            }
            let dir = w.f.0.join("service/health");
            DirBuilder::new().mode(0o700).create(&dir).unwrap();
            let key = if notification {
                "901/\"synthetic-quarantined-notification\""
            } else {
                "901/i1/1000/first/2000"
            };
            let path = dir.join(format!(
                "body-{}",
                openwiz_core::messaging::sha256_hex(key.as_bytes())
            ));
            let bytes = json!({"body":LEGACY_FLEET_BODY,"sha256":if corrupt {"0".repeat(64)} else {openwiz_core::messaging::sha256_hex(LEGACY_FLEET_BODY.as_bytes())}}).to_string().into_bytes();
            fs::write(&path, &bytes).unwrap();
            fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
            for now in [4000, 5000, 3_605_000] {
                let mut seen = w.seen(now == 4000, now == 4000);
                seen.fleet_threads = Listed::Unread(Unread {
                    gap: Gap::TimedOut,
                    reason: NonEmpty::new("synthetic fleet source unread").unwrap(),
                });
                let result = w.engine().pass(&seen, now);
                assert!(
                    result.is_err(),
                    "retained delivery remains pending: notification={notification}, corrupt={corrupt}, now={now}"
                );
                if corrupt {
                    assert!(result.unwrap_err().contains("checksum"));
                    assert!(
                        w.runtime.0.lock().unwrap().is_empty(),
                        "corrupt storage still stops dispatch"
                    );
                } else {
                    assert_eq!(
                        *w.runtime.0.lock().unwrap(),
                        ["tick", "server"],
                        "quarantine must not abort planning"
                    );
                }
                assert_eq!(
                    fs::read(&path).unwrap(),
                    bytes,
                    "never rewrite the retained body"
                );
                let state = w.state.lock().unwrap().snapshot().clone();
                let retained = &state["incidents"][0];
                assert_eq!(
                    retained, &fleet,
                    "private history and operation binding stay unchanged"
                );
                if corrupt {
                    assert_eq!(state["incidents"], json!([fleet, healing]));
                } else if now == 3_605_000 {
                    assert_eq!(
                        state["incidents"],
                        json!([fleet]),
                        "unrelated healthy incidents must heal"
                    );
                } else {
                    assert_eq!(state["incidents"][1]["healthy_since"], 4000);
                }
                w.state = Arc::new(Mutex::new(State::load(&w.f.0, now + 1).unwrap()));
            }
            assert_eq!(w.posts().len(), if corrupt { 0 } else { 2 });
            for comment in w.comments.lock().unwrap().iter() {
                assert_record(comment["body"].as_str().unwrap());
            }
            assert!(
                w.f.calls().iter().all(|a| a[1] != "tell"),
                "unsafe notification is never sent"
            );
            let unsafe_claim =
                openwiz_core::messaging::sha256_hex(format!("901\n{LEGACY_FLEET_BODY}").as_bytes());
            assert!(
                !dir.join(unsafe_claim).exists(),
                "quarantine must not attempt a new POST"
            );
        }
    }
}
